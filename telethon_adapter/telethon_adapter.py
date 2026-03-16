from __future__ import annotations

import asyncio
import os
import re
import tempfile
from pathlib import Path
from typing import Any

from astrbot.api import logger
from astrbot.api.event import MessageChain
from astrbot.api.platform import (
    AstrBotMessage,
    Platform,
    PlatformMetadata,
    register_platform_adapter,
)
from astrbot.core.platform.astr_message_event import MessageSesion

try:
    from astrbot.core.utils.astrbot_path import get_astrbot_temp_path
except ImportError:
    get_astrbot_temp_path = None
try:
    from python_socks import ProxyType
except ImportError:
    ProxyType = None

from telethon import TelegramClient, events
from telethon.network import connection
from telethon.sessions import StringSession
from .config import (
    DEFAULT_CONFIG_TEMPLATE,
    TELETHON_CONFIG_METADATA,
    TELETHON_I18N_RESOURCES,
    apply_config,
    config_error,
    validate_config,
)
from .message_converter import TelethonMessageConverter
from .telethon_event import TelethonEvent

PLUGIN_ROOT = Path(__file__).resolve().parent.parent


@register_platform_adapter(
    "telethon_userbot",
    "Telethon Userbot 适配器",
    logo_path=str(PLUGIN_ROOT / "logo.png"),
    support_streaming_message=False,
    default_config_tmpl=DEFAULT_CONFIG_TEMPLATE,
    config_metadata=TELETHON_CONFIG_METADATA,
    i18n_resources=TELETHON_I18N_RESOURCES,
)
class TelethonPlatformAdapter(Platform):
    def __init__(
        self,
        platform_config: dict,
        platform_settings: dict,
        event_queue: asyncio.Queue,
    ) -> None:
        super().__init__(platform_config, event_queue)
        self.settings = platform_settings

        apply_config(self)

        self.client: TelegramClient | None = None
        self.self_id = ""
        self.self_username = ""
        self._running = False
        self._main_task: asyncio.Task | None = None
        self._cleanup_task: asyncio.Task | None = None
        self._media_group_cache: dict[tuple[str, int], dict[str, Any]] = {}
        self._recent_event_keys: dict[tuple[str, int], float] = {}
        self._recent_event_keys_cleanup_at = 0.0
        self._downloaded_temp_files: dict[str, float] = {}
        self._media_temp_dir = self._build_media_temp_dir()
        self._message_converter = TelethonMessageConverter(self)

    def meta(self) -> PlatformMetadata:
        adapter_id = str(self.config.get("id") or "telethon_userbot")
        return PlatformMetadata(
            # AstrBot core uses platform_meta.name as the canonical adapter type
            # for platform filters and compatibility checks.
            name="telethon_userbot",
            description="Telethon Userbot Adapter",
            id=adapter_id,
            support_streaming_message=False,
        )

    async def run(self):
        validate_config(self)

        client_kwargs = self._build_client_kwargs()
        self.client = TelegramClient(
            StringSession(self.session_string),
            self.api_id,
            self.api_hash,
            **client_kwargs,
        )

        try:
            self._running = True
            await self.client.connect()
            if not await self.client.is_user_authorized():
                raise RuntimeError(
                    "[Telethon] The current session_string is unauthorized. Regenerate a valid StringSession."
                )

            me = await self.client.get_me()
            self.self_id = str(me.id)
            self.self_username = str(getattr(me, "username", "") or "").strip().lower()

            logger.info(
                "[Telethon] Userbot started: %s username=%s "
                "download_incoming_media=%s incoming_media_ttl_seconds=%s "
                "trigger_prefix=%r log_processed_messages_only=%s proxy_type=%s "
                "proxy_host=%s proxy_port=%s raw_config=%s",
                self.self_id,
                self.self_username,
                self.download_incoming_media,
                self.incoming_media_ttl_seconds,
                self.trigger_prefix,
                self.log_processed_messages_only,
                self.proxy_type or "direct",
                self.proxy_host or "",
                self.proxy_port or 0,
                {
                    "trigger_prefix": self.config.get("trigger_prefix"),
                    "download_incoming_media": self.config.get("download_incoming_media"),
                    "incoming_media_ttl_seconds": self.config.get(
                        "incoming_media_ttl_seconds"
                    ),
                    "log_processed_messages_only": self.config.get(
                        "log_processed_messages_only"
                    ),
                    "proxy_type": self.config.get("proxy_type"),
                    "proxy_host": self.config.get("proxy_host"),
                    "proxy_port": self.config.get("proxy_port"),
                    "proxy_rdns": self.config.get("proxy_rdns"),
                },
            )
            self.client.add_event_handler(
                self._on_new_message,
                events.NewMessage(incoming=True, outgoing=False),
            )
            self.client.add_event_handler(
                self._on_new_message,
                events.NewMessage(incoming=False, outgoing=True),
            )
            if not self.log_processed_messages_only:
                self.client.add_event_handler(self._on_raw_event, events.Raw())
            if self.incoming_media_ttl_seconds > 0:
                self._cleanup_task = asyncio.create_task(self._cleanup_temp_files_loop())
            self._main_task = asyncio.create_task(self.client.run_until_disconnected())
            await self._main_task
        except asyncio.CancelledError:
            logger.info("[Telethon] Adapter task cancelled")
        finally:
            self._running = False
            await self.terminate()

    async def terminate(self) -> None:
        if self._cleanup_task and not self._cleanup_task.done():
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass

        for entry in self._media_group_cache.values():
            task = entry.get("task")
            if task and not task.done():
                task.cancel()
        self._media_group_cache.clear()
        await self._cleanup_expired_temp_files(force=True)
        self._remove_media_temp_dir_if_empty()

        if self.client:
            try:
                await self.client.disconnect()
            except Exception:
                logger.exception("[Telethon] Failed to close connection")

        if self._main_task and not self._main_task.done():
            self._main_task.cancel()
            try:
                await self._main_task
            except asyncio.CancelledError:
                pass

    async def send_by_session(
        self, session: MessageSesion, message_chain: MessageChain
    ) -> None:
        if not self.client:
            raise RuntimeError("[Telethon] Client is not initialized")

        inner_message = AstrBotMessage()
        inner_message.session_id = session.session_id
        inner_message.type = session.message_type
        message_event = TelethonEvent(
            message_str=message_chain.get_plain_text(),
            message_obj=inner_message,
            platform_meta=self.meta(),
            session_id=session.session_id,
            client=self.client,
        )
        message_event.telethon_language = self.language
        await message_event.send(message_chain)
        await super().send_by_session(session, message_chain)

    def get_client(self):
        return self.client

    def _build_client_kwargs(self) -> dict[str, Any]:
        if not self.proxy_type:
            return {}

        if not self.proxy_host or not self.proxy_port:
            raise ValueError("[Telethon] Proxy is configured, but proxy_host or proxy_port is missing")

        if self.proxy_type in {"socks5", "socks4", "http"}:
            if ProxyType is None:
                raise RuntimeError(
                    "[Telethon] SOCKS/HTTP proxy is configured, but python-socks is not installed"
                )
            proxy_type_map = {
                "socks5": ProxyType.SOCKS5,
                "socks4": ProxyType.SOCKS4,
                "http": ProxyType.HTTP,
            }
            return {
                "proxy": (
                    proxy_type_map[self.proxy_type],
                    self.proxy_host,
                    self.proxy_port,
                    self.proxy_rdns,
                    self.proxy_username or None,
                    self.proxy_password or None,
                )
            }

        if self.proxy_type == "mtproto":
            if not self.proxy_secret:
                raise ValueError(
                    "[Telethon] MTProto proxy requires proxy_secret"
                )
            mtproto_connection = getattr(
                connection, "ConnectionTcpMTProxyRandomizedIntermediate", None
            ) or getattr(connection, "ConnectionTcpMTProxyIntermediate", None)
            if mtproto_connection is None:
                raise RuntimeError(
                    "[Telethon] The current Telethon version does not provide an MTProto proxy connection class"
                )
            return {
                "connection": mtproto_connection,
                "proxy": (
                    self.proxy_host,
                    self.proxy_port,
                    self.proxy_secret,
                ),
            }

        raise ValueError(
            "[Telethon] Unsupported proxy_type. Valid values: socks5, socks4, http, mtproto"
        )

    def _config_error(self, field_name: str, current_value: Any, suggestion: str) -> ValueError:
        return config_error(field_name, current_value, suggestion)

    def _validate_config(self) -> None:
        validate_config(self)

    def _log_unprocessed(self, message: str, *args: Any) -> None:
        if not self.log_processed_messages_only:
            logger.info(message, *args)

    async def _on_new_message(self, event: events.NewMessage.Event) -> None:
        if not self._running:
            return
        if not getattr(event, "message", None):
            self._log_unprocessed("[Telethon] Ignoring message: empty event.message")
            return
        if self._message_converter.is_topic_service_message(event.message):
            self._log_unprocessed(
                "[Telethon] Ignoring topic service message: chat_id=%s msg_id=%s action=%s",
                getattr(event, "chat_id", None),
                getattr(event.message, "id", None),
                type(getattr(event.message, "action", None)).__name__,
            )
            return

        event_key = (
            str(getattr(event, "chat_id", "")),
            int(getattr(event.message, "id", 0)),
        )
        loop = asyncio.get_running_loop()
        now = loop.time()
        if now >= self._recent_event_keys_cleanup_at:
            stale_keys = [
                key for key, seen_at in self._recent_event_keys.items() if now - seen_at > 30
            ]
            for key in stale_keys:
                self._recent_event_keys.pop(key, None)
            self._recent_event_keys_cleanup_at = now + 30
        if event_key in self._recent_event_keys:
            self._log_unprocessed("[Telethon] Ignoring message: duplicate event %s", event_key)
            return
        self._recent_event_keys[event_key] = now

        self._log_unprocessed(
            "[Telethon] Received message event: chat_id=%s sender_id=%s out=%s private=%s text=%r",
            getattr(event, "chat_id", None),
            getattr(event, "sender_id", None),
            getattr(event.message, "out", None) if getattr(event, "message", None) else None,
            getattr(event, "is_private", None),
            getattr(event.message, "raw_text", "") if getattr(event, "message", None) else "",
        )
        if self.debug_logging:
            peer = getattr(getattr(event, "message", None), "peer_id", None)
            self._log_unprocessed(
                "[Telethon][Debug] raw_event: chat_id=%s sender_id=%s peer_type=%s "
                "msg_id=%s grouped_id=%s out=%s private=%s",
                getattr(event, "chat_id", None),
                getattr(event, "sender_id", None),
                type(peer).__name__ if peer is not None else None,
                getattr(getattr(event, "message", None), "id", None),
                getattr(getattr(event, "message", None), "grouped_id", None),
                getattr(getattr(event, "message", None), "out", None),
                getattr(event, "is_private", None),
            )
        grouped_id = getattr(event.message, "grouped_id", None)
        if grouped_id:
            await self._handle_grouped_message(
                event,
                self._grouped_message_session_id(event),
                int(grouped_id),
            )
            return

        raw_text = str(getattr(event.message, "raw_text", "") or "")
        if self.trigger_prefix and not raw_text.startswith(self.trigger_prefix):
            self._log_unprocessed(
                "[Telethon] Ignoring message: missing trigger_prefix %r text=%r",
                self.trigger_prefix,
                raw_text,
            )
            return

        try:
            abm = await self._convert_message(event, include_reply=True)
        except Exception:
            logger.exception(
                "[Telethon] Failed to convert message: chat_id=%s msg_id=%s sender_id=%s reply_to=%s",
                getattr(event, "chat_id", None),
                getattr(event.message, "id", None),
                getattr(event, "sender_id", None),
                getattr(getattr(event.message, "reply_to", None), "reply_to_msg_id", None),
            )
            return

        logger.info(
            "[Telethon] Committing AstrBot event: session_id=%s type=%s sender=%s text=%r",
            getattr(abm, "session_id", None),
            getattr(abm, "type", None),
            getattr(getattr(abm, "sender", None), "user_id", None),
            getattr(abm, "message_str", ""),
        )
        if self.debug_logging:
            logger.info(
                "[Telethon][Debug] commit_event: platform_id=%s self_id=%s session_id=%s "
                "message_id=%s type=%s text=%r",
                getattr(self.meta(), "id", None),
                getattr(abm, "self_id", None),
                getattr(abm, "session_id", None),
                getattr(abm, "message_id", None),
                getattr(abm, "type", None),
                getattr(abm, "message_str", ""),
            )
        self._commit_abm(abm)

    async def _on_raw_event(self, event: events.Raw) -> None:
        if not self._running:
            return

        update = getattr(event, "update", None)
        if update is None:
            return

        update_name = type(update).__name__
        message = getattr(update, "message", None)
        if message is None:
            return

        peer_id = getattr(message, "peer_id", None)
        from_id = getattr(message, "from_id", None)
        raw_text = getattr(message, "message", "")
        out = getattr(message, "out", None)
        msg_id = getattr(message, "id", None)

        logger.info(
            "[Telethon][Raw] update=%s msg_id=%s out=%s peer_id=%s from_id=%s text=%r",
            update_name,
            msg_id,
            out,
            type(peer_id).__name__ if peer_id else None,
            type(from_id).__name__ if from_id else None,
            raw_text,
        )

    def _commit_abm(self, abm: AstrBotMessage) -> None:
        message_event = TelethonEvent(
            message_str=abm.message_str,
            message_obj=abm,
            platform_meta=self.meta(),
            session_id=abm.session_id,
            client=self.client,
        )
        message_event.telethon_debug_logging = self.debug_logging
        message_event.telethon_language = self.language
        self.commit_event(message_event)

    async def _handle_grouped_message(
        self,
        event: events.NewMessage.Event,
        session_id: str,
        grouped_id: int,
    ) -> None:
        cache_key = (session_id, grouped_id)
        loop = asyncio.get_running_loop()
        now = loop.time()
        entry = self._media_group_cache.get(cache_key)
        if not entry:
            entry = {
                "created_at": now,
                "items": [],
                "task": None,
            }
            self._media_group_cache[cache_key] = entry

        entry["items"].append(event)
        elapsed = now - float(entry["created_at"])
        delay = 0 if elapsed >= self.media_group_max_wait else self.media_group_timeout

        task = entry.get("task")
        if task and not task.done():
            task.cancel()
        entry["task"] = asyncio.create_task(
            self._process_grouped_message(cache_key, delay)
        )

    async def _process_grouped_message(
        self,
        cache_key: tuple[str, int],
        delay: float,
    ) -> None:
        try:
            if delay > 0:
                await asyncio.sleep(delay)
        except asyncio.CancelledError:
            return

        entry = self._media_group_cache.pop(cache_key, None)
        if not entry:
            return

        events_list = entry.get("items", [])
        if not events_list:
            return
        session_id, grouped_id = cache_key
        events_list = sorted(events_list, key=lambda e: int(getattr(e.message, "id", 0)))

        trigger_event = None
        if self.trigger_prefix:
            for candidate in events_list:
                raw_text = str(getattr(candidate.message, "raw_text", "") or "")
                if raw_text.startswith(self.trigger_prefix):
                    trigger_event = candidate
                    break
            if trigger_event is None:
                self._log_unprocessed(
                    "[Telethon] Ignoring media group: missing trigger_prefix %r session_id=%s grouped_id=%s",
                    self.trigger_prefix,
                    session_id,
                    grouped_id,
                )
                return
        else:
            trigger_event = events_list[0]

        try:
            merged = await self._convert_message(trigger_event, include_reply=True)
        except Exception:
            logger.exception(
                "[Telethon] Failed to convert media group primary message: session_id=%s chat_id=%s grouped_id=%s msg_id=%s sender_id=%s reply_to=%s",
                session_id,
                getattr(trigger_event, "chat_id", None),
                grouped_id,
                getattr(trigger_event.message, "id", None),
                getattr(trigger_event, "sender_id", None),
                getattr(
                    getattr(trigger_event.message, "reply_to", None),
                    "reply_to_msg_id",
                    None,
                ),
            )
            return

        for extra_event in events_list:
            if extra_event is trigger_event:
                continue
            try:
                extra = await self._convert_message(extra_event, include_reply=False)
            except Exception:
                logger.exception(
                    "[Telethon] Failed to convert media group child message: session_id=%s chat_id=%s grouped_id=%s msg_id=%s sender_id=%s reply_to=%s",
                    session_id,
                    getattr(extra_event, "chat_id", None),
                    grouped_id,
                    getattr(extra_event.message, "id", None),
                    getattr(extra_event, "sender_id", None),
                    getattr(
                        getattr(extra_event.message, "reply_to", None),
                        "reply_to_msg_id",
                        None,
                    ),
                )
                continue

            merged.message.extend(extra.message)
            if not merged.message_str and extra.message_str:
                merged.message_str = extra.message_str

        if not merged.message_str:
            merged.message_str = "[媒体组]"
        self._commit_abm(merged)

    def _grouped_message_session_id(self, event: events.NewMessage.Event) -> str:
        message = getattr(event, "message", None)
        peer = getattr(message, "peer_id", None)
        is_private = bool(getattr(event, "is_private", False))
        if not is_private and type(peer).__name__ == "PeerUser":
            is_private = True
        chat_id = str(getattr(event, "chat_id", ""))
        thread_id = None if is_private else self._message_converter.extract_thread_id(message)
        return self._message_converter.build_session_id(
            chat_id,
            thread_id,
            is_private=is_private,
        )

    def _get_media_temp_dir(self) -> str:
        os.makedirs(self._media_temp_dir, exist_ok=True)
        return self._media_temp_dir

    def _build_media_temp_dir(self) -> str:
        base_dir = tempfile.gettempdir()
        if get_astrbot_temp_path:
            try:
                base_dir = str(get_astrbot_temp_path())
            except Exception:
                logger.warning(
                    "[Telethon] Failed to get AstrBot temp directory, falling back to the system temp directory: adapter_id=%s",
                    self.config.get("id") or "telethon_userbot",
                    exc_info=True,
                )

        adapter_id = str(self.config.get("id") or "telethon_userbot").strip() or "telethon_userbot"
        safe_adapter_id = re.sub(r"[^A-Za-z0-9_.-]+", "_", adapter_id)
        return os.path.join(base_dir, f"telethon_adapter_{safe_adapter_id}")

    def _register_temp_file(self, path: str) -> None:
        if path:
            expires_at = 0.0
            if self.incoming_media_ttl_seconds > 0:
                expires_at = asyncio.get_running_loop().time() + self.incoming_media_ttl_seconds
            self._downloaded_temp_files[os.path.abspath(path)] = expires_at

    async def _cleanup_temp_files_loop(self) -> None:
        interval = min(max(self.incoming_media_ttl_seconds / 2, 30.0), 300.0)
        try:
            while self._running:
                await asyncio.sleep(interval)
                await self._cleanup_expired_temp_files(force=False)
        except asyncio.CancelledError:
            return

    async def _cleanup_expired_temp_files(self, force: bool) -> None:
        if not self._downloaded_temp_files:
            return

        now = asyncio.get_running_loop().time()
        for path, expires_at in list(self._downloaded_temp_files.items()):
            if not force and expires_at > 0 and now < expires_at:
                continue
            try:
                if os.path.exists(path):
                    os.remove(path)
            except Exception:
                logger.exception("[Telethon] Failed to clean up temporary media file: %s", path)
                continue
            self._downloaded_temp_files.pop(path, None)
        if force or not self._downloaded_temp_files:
            self._remove_media_temp_dir_if_empty()

    def _remove_media_temp_dir_if_empty(self) -> None:
        if not self._media_temp_dir:
            return
        if not os.path.isdir(self._media_temp_dir):
            return
        try:
            if not os.listdir(self._media_temp_dir):
                os.rmdir(self._media_temp_dir)
        except OSError:
            pass

    async def _convert_message(
        self,
        event: events.NewMessage.Event,
        include_reply: bool = True,
    ) -> AstrBotMessage:
        return await self._message_converter.convert_message(event, include_reply)
