from __future__ import annotations

import asyncio
import os
import re
from typing import Any

from astrbot.api import logger
from astrbot.api.event import MessageChain
from astrbot.api.message_components import At, File, Image, Location, Plain, Record, Reply, Video
from astrbot.api.platform import (
    AstrBotMessage,
    MessageMember,
    MessageType,
    Platform,
    PlatformMetadata,
    register_platform_adapter,
)
from astrbot.core.platform.astr_message_event import MessageSesion

try:
    from astrbot.core.utils.astrbot_path import get_astrbot_temp_path
except Exception:
    get_astrbot_temp_path = None

from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.tl.types import (
    DocumentAttributeAudio,
    DocumentAttributeFilename,
    DocumentAttributeSticker,
    DocumentAttributeVideo,
    GeoPointEmpty,
    MessageEntityMention,
    MessageEntityMentionName,
    MessageEntityTextUrl,
    MessageMediaContact,
    MessageMediaGeo,
    MessageMediaGeoLive,
)

from .lazy_media import LazyFile, LazyImage, LazyRecord, LazyVideo, TelethonLazyMedia
from .telethon_event import TelethonEvent


TELETHON_CONFIG_METADATA = {
    "api_id": {
        "description": "Telegram API ID",
        "type": "int",
        "hint": "在 my.telegram.org 申请得到的 API ID。",
    },
    "api_hash": {
        "description": "Telegram API Hash",
        "type": "string",
        "hint": "在 my.telegram.org 申请得到的 API Hash。",
    },
    "session_string": {
        "description": "Telethon StringSession",
        "type": "text",
        "hint": "先通过 scripts/generate_session.py 交互登录，再把输出的 StringSession 填到这里。",
    },
    "id": {
        "description": "适配器 ID",
        "type": "string",
        "hint": "平台实例唯一标识，用于区分多个 Telegram 适配器实例。",
    },
    "trigger_prefix": {
        "description": "触发前缀",
        "type": "string",
        "hint": "仅处理以此前缀开头的消息。留空表示处理所有消息。",
    },
    "ignore_self_messages": {
        "description": "忽略自身发送者消息",
        "type": "bool",
        "hint": "开启后，不处理 sender_id 等于当前账号 ID 的消息。",
    },
    "download_incoming_media": {
        "description": "下载入站媒体",
        "type": "bool",
        "hint": "关闭后，不下载收到的图片、文件、音视频附件。",
    },
    "incoming_media_ttl_seconds": {
        "description": "入站媒体缓存 TTL",
        "type": "float",
        "hint": "媒体下载到本地后保留的秒数。设为 0 或负数表示仅在适配器退出时清理。",
    },
    "log_processed_messages_only": {
        "description": "仅记录已处理消息",
        "type": "bool",
        "hint": "开启后，只记录真正提交给 AstrBot 处理的消息。",
    },
    "telethon_media_group_timeout": {
        "description": "媒体组聚合延迟",
        "type": "float",
        "hint": "媒体组防抖等待时间，单位秒。",
    },
    "telethon_media_group_max_wait": {
        "description": "媒体组最大等待时间",
        "type": "float",
        "hint": "媒体组聚合的最长等待时间，单位秒。",
    },
}


def _parse_bool(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized == "":
            return default
        if normalized in {"1", "true", "yes", "y", "on"}:
            return True
        if normalized in {"0", "false", "no", "n", "off"}:
            return False
    return default


@register_platform_adapter(
    "telethon_userbot",
    "Telethon Userbot 适配器",
    default_config_tmpl={
        "api_id": 123456,
        "api_hash": "your_api_hash",
        "session_string": "",
        "id": "telethon_userbot",
        "trigger_prefix": "-astr",
        "ignore_self_messages": False,
        "download_incoming_media": True,
        "incoming_media_ttl_seconds": 600.0,
        "log_processed_messages_only": True,
        "telethon_media_group_timeout": 1.2,
        "telethon_media_group_max_wait": 8.0,
    },
    config_metadata=TELETHON_CONFIG_METADATA,
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

        self.api_id = int(self.config.get("api_id", 0))
        self.api_hash = str(self.config.get("api_hash", "")).strip()
        self.session_string = str(self.config.get("session_string", "")).strip()
        self.trigger_prefix = str(self.config.get("trigger_prefix", "") or "")
        self.ignore_self_messages = _parse_bool(
            self.config.get("ignore_self_messages"), False
        )
        self.download_incoming_media = _parse_bool(
            self.config.get("download_incoming_media"), True
        )
        self.incoming_media_ttl_seconds = float(
            self.config.get("incoming_media_ttl_seconds", 600.0)
        )
        self.log_processed_messages_only = _parse_bool(
            self.config.get("log_processed_messages_only"), True
        )
        self.media_group_timeout = float(
            self.config.get("telethon_media_group_timeout", 1.2)
        )
        self.media_group_max_wait = float(
            self.config.get("telethon_media_group_max_wait", 8.0)
        )

        self.client: TelegramClient | None = None
        self.self_id = ""
        self._running = False
        self._main_task: asyncio.Task | None = None
        self._cleanup_task: asyncio.Task | None = None
        self._media_group_cache: dict[tuple[str, int], dict[str, Any]] = {}
        self._recent_event_keys: dict[tuple[str, int], float] = {}
        self._downloaded_temp_files: dict[str, float] = {}
        self._media_temp_dir = self._build_media_temp_dir()

    def meta(self) -> PlatformMetadata:
        adapter_id = str(self.config.get("id") or "telethon_userbot")
        return PlatformMetadata(
            name="Telethon_Userbot",
            description="Telethon Userbot 适配器",
            id=adapter_id,
        )

    async def run(self):
        if not self.api_id or not self.api_hash:
            raise ValueError("[Telethon] 缺少 api_id 或 api_hash")
        if not self.session_string:
            raise ValueError(
                "[Telethon] 缺少 session_string。请先生成 Telethon StringSession。"
            )

        self.client = TelegramClient(
            StringSession(self.session_string),
            self.api_id,
            self.api_hash,
        )

        try:
            self._running = True
            await self.client.connect()
            if not await self.client.is_user_authorized():
                raise RuntimeError(
                    "[Telethon] 当前 session_string 未授权。请重新生成有效 StringSession。"
                )

            me = await self.client.get_me()
            self.self_id = str(me.id)

            logger.info(
                "[Telethon] Userbot 已启动: %s ignore_self_messages=%s "
                "download_incoming_media=%s incoming_media_ttl_seconds=%s "
                "trigger_prefix=%r log_processed_messages_only=%s raw_config=%s",
                self.self_id,
                self.ignore_self_messages,
                self.download_incoming_media,
                self.incoming_media_ttl_seconds,
                self.trigger_prefix,
                self.log_processed_messages_only,
                {
                    "trigger_prefix": self.config.get("trigger_prefix"),
                    "ignore_self_messages": self.config.get("ignore_self_messages"),
                    "download_incoming_media": self.config.get("download_incoming_media"),
                    "incoming_media_ttl_seconds": self.config.get(
                        "incoming_media_ttl_seconds"
                    ),
                    "log_processed_messages_only": self.config.get(
                        "log_processed_messages_only"
                    ),
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
            logger.info("[Telethon] 适配器任务已取消")
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
            except Exception as e:
                logger.error(f"[Telethon] 关闭连接失败: {e}")

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
            raise RuntimeError("[Telethon] 客户端未初始化")

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
        await message_event.send(message_chain)
        await super().send_by_session(session, message_chain)

    def get_client(self):
        return self.client

    def _log_unprocessed(self, message: str, *args: Any) -> None:
        if not self.log_processed_messages_only:
            logger.info(message, *args)

    async def _on_new_message(self, event: events.NewMessage.Event) -> None:
        if not self._running:
            return
        if not getattr(event, "message", None):
            self._log_unprocessed("[Telethon] 忽略消息: empty event.message")
            return

        event_key = (
            str(getattr(event, "chat_id", "")),
            int(getattr(event.message, "id", 0)),
        )
        loop = asyncio.get_running_loop()
        now = loop.time()
        stale_keys = [
            key for key, seen_at in self._recent_event_keys.items() if now - seen_at > 30
        ]
        for key in stale_keys:
            self._recent_event_keys.pop(key, None)
        if event_key in self._recent_event_keys:
            self._log_unprocessed("[Telethon] 忽略消息: duplicate event %s", event_key)
            return
        self._recent_event_keys[event_key] = now

        self._log_unprocessed(
            "[Telethon] 收到消息事件: chat_id=%s sender_id=%s out=%s private=%s text=%r",
            getattr(event, "chat_id", None),
            getattr(event, "sender_id", None),
            getattr(event.message, "out", None) if getattr(event, "message", None) else None,
            getattr(event, "is_private", None),
            getattr(event.message, "raw_text", "") if getattr(event, "message", None) else "",
        )
        if self.ignore_self_messages and str(getattr(event, "sender_id", "")) == self.self_id:
            self._log_unprocessed("[Telethon] 忽略消息: self message")
            return

        raw_text = str(getattr(event.message, "raw_text", "") or "")
        if self.trigger_prefix and not raw_text.startswith(self.trigger_prefix):
            self._log_unprocessed(
                "[Telethon] 忽略消息: missing trigger_prefix %r text=%r",
                self.trigger_prefix,
                raw_text,
            )
            return

        grouped_id = getattr(event.message, "grouped_id", None)
        if grouped_id:
            await self._handle_grouped_message(
                event,
                str(event.chat_id),
                int(grouped_id),
            )
            return

        try:
            abm = await self._convert_message(event, include_reply=True)
        except Exception as e:
            logger.error(f"[Telethon] 转换消息失败: {e}")
            return

        logger.info(
            "[Telethon] 提交 AstrBot 事件: session_id=%s type=%s sender=%s text=%r",
            getattr(abm, "session_id", None),
            getattr(abm, "type", None),
            getattr(getattr(abm, "sender", None), "user_id", None),
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
        self.commit_event(message_event)

    async def _handle_grouped_message(
        self,
        event: events.NewMessage.Event,
        chat_id: str,
        grouped_id: int,
    ) -> None:
        cache_key = (chat_id, grouped_id)
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
        grouped_id = cache_key[1]
        events_list = sorted(events_list, key=lambda e: int(getattr(e.message, "id", 0)))

        try:
            merged = await self._convert_message(events_list[0], include_reply=True)
        except Exception as e:
            logger.error(f"[Telethon] 媒体组首条消息转换失败: {e}")
            return

        for extra_event in events_list[1:]:
            try:
                extra = await self._convert_message(extra_event, include_reply=False)
            except Exception as e:
                logger.warning(f"[Telethon] 媒体组子消息转换失败: {e}")
                continue

            merged.message.extend(extra.message)
            if not merged.message_str and extra.message_str:
                merged.message_str = extra.message_str

        if not merged.message_str:
            merged.message_str = "[媒体组]"
        self._commit_abm(merged)

    def _get_media_temp_dir(self) -> str:
        os.makedirs(self._media_temp_dir, exist_ok=True)
        return self._media_temp_dir

    def _build_media_temp_dir(self) -> str:
        base_dir = "/tmp"
        if get_astrbot_temp_path:
            try:
                base_dir = str(get_astrbot_temp_path())
            except Exception:
                pass

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
            except Exception as e:
                logger.warning(f"[Telethon] 清理临时媒体文件失败: {path} {e}")
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
        return await self._convert_telethon_message(
            msg=event.message,
            sender=await event.get_sender(),
            chat_id=str(event.chat_id),
            is_private=bool(getattr(event, "is_private", False)),
            include_reply=include_reply,
            strip_trigger_prefix=True,
        )

    async def _convert_telethon_message(
        self,
        msg: Any,
        sender: Any,
        chat_id: str,
        is_private: bool,
        include_reply: bool,
        strip_trigger_prefix: bool,
    ) -> AstrBotMessage:
        sender_name = (
            getattr(sender, "username", None)
            or " ".join(
                x for x in [getattr(sender, "first_name", ""), getattr(sender, "last_name", "")] if x
            ).strip()
            or getattr(sender, "title", None)
            or str(getattr(sender, "id", "unknown"))
        )

        message = AstrBotMessage()
        message.session_id = chat_id
        message.message_id = str(msg.id)
        message.self_id = self.self_id
        message.raw_message = msg
        message.sender = MessageMember(user_id=str(getattr(sender, "id", "0")), nickname=sender_name)
        message.message_str = msg.raw_text or ""
        message.message = []

        if (
            strip_trigger_prefix
            and self.trigger_prefix
            and message.message_str.startswith(self.trigger_prefix)
        ):
            message.message_str = message.message_str[len(self.trigger_prefix) :].lstrip()

        if is_private:
            message.type = MessageType.FRIEND_MESSAGE
        else:
            message.type = MessageType.GROUP_MESSAGE
            message.group_id = chat_id

        if include_reply and msg.reply_to and getattr(msg.reply_to, "reply_to_msg_id", None):
            reply_id = str(msg.reply_to.reply_to_msg_id)
            reply_component = Reply(
                id=reply_id,
                sender_id=0,
                sender_nickname="",
                message_str="",
                text="",
                qq=0,
            )
            try:
                reply_msg = await msg.get_reply_message()
                if reply_msg:
                    reply_sender = await reply_msg.get_sender()
                    reply_chat_id = str(getattr(reply_msg, "chat_id", chat_id))
                    reply_is_private = bool(getattr(reply_msg, "is_private", is_private))
                    reply_abm = await self._convert_telethon_message(
                        msg=reply_msg,
                        sender=reply_sender,
                        chat_id=reply_chat_id,
                        is_private=reply_is_private,
                        include_reply=False,
                        strip_trigger_prefix=False,
                    )
                    reply_component = Reply(
                        id=reply_abm.message_id,
                        chain=reply_abm.message,
                        sender_id=reply_abm.sender.user_id,
                        sender_nickname=reply_abm.sender.nickname,
                        time=int(getattr(getattr(reply_msg, "date", None), "timestamp", lambda: 0)()),
                        message_str=reply_abm.message_str,
                        text=reply_abm.message_str,
                        qq=reply_abm.sender.user_id,
                    )
            except Exception as e:
                logger.warning(f"[Telethon] 获取引用消息失败: {e}")
            message.message.append(
                reply_component
            )

        text_components = self._parse_text_components(
            msg.raw_text or "",
            getattr(msg, "entities", None),
        )
        if strip_trigger_prefix and self.trigger_prefix:
            text_components = self._strip_prefix_from_components(
                text_components,
                self.trigger_prefix,
            )
        message.message.extend(text_components)

        if msg.media:
            media_components = await self._parse_media_components(msg)
            message.message.extend(media_components)
            if not message.message_str and media_components:
                message.message_str = "[媒体消息]"

        return message

    @staticmethod
    def _strip_prefix_from_components(
        components: list[Any],
        prefix: str,
    ) -> list[Any]:
        if not prefix:
            return components

        remaining_prefix = prefix
        for component in components:
            if not remaining_prefix:
                break
            if not isinstance(component, Plain):
                break

            text = component.text or ""
            if not text:
                continue
            if text.startswith(remaining_prefix):
                component.text = text[len(remaining_prefix) :].lstrip()
                remaining_prefix = ""
                break
            if remaining_prefix.startswith(text):
                remaining_prefix = remaining_prefix[len(text) :]
                component.text = ""
                continue
            break

        return [
            component
            for component in components
            if not isinstance(component, Plain) or component.text
        ]

    def _parse_text_components(
        self,
        text: str,
        entities: list[Any] | None,
    ) -> list[Any]:
        if not text:
            return []
        if not entities:
            return [Plain(text=text)]

        components: list[Any] = []
        cursor = 0
        sorted_entities = sorted(
            entities,
            key=lambda e: int(getattr(e, "offset", 0)),
        )
        for entity in sorted_entities:
            offset = int(getattr(entity, "offset", 0))
            length = int(getattr(entity, "length", 0))
            if length <= 0:
                continue
            offset = max(0, offset)
            py_offset, py_end = self._utf16_span_to_py_span(text, offset, length)
            end = min(len(text), py_end)
            offset = min(len(text), py_offset)
            if end <= cursor:
                continue
            if offset > cursor:
                components.append(Plain(text=text[cursor:offset]))

            entity_text = text[offset:end]
            mention = self._entity_to_at(entity, entity_text)
            if mention:
                components.append(mention)
            elif isinstance(entity, MessageEntityTextUrl):
                url = str(getattr(entity, "url", "") or "").strip()
                if url:
                    display = entity_text.strip()
                    if display and display != url:
                        components.append(Plain(text=f"{display} ({url})"))
                    else:
                        components.append(Plain(text=url))
                else:
                    components.append(Plain(text=entity_text))
            else:
                components.append(Plain(text=entity_text))
            cursor = end

        if cursor < len(text):
            components.append(Plain(text=text[cursor:]))

        if not components:
            components.append(Plain(text=text))
        return components

    @staticmethod
    def _utf16_span_to_py_span(
        text: str,
        utf16_offset: int,
        utf16_length: int,
    ) -> tuple[int, int]:
        """Convert Telegram UTF-16 entity offsets to Python string indices."""
        if not text:
            return 0, 0

        utf16_end = max(utf16_offset, utf16_offset + utf16_length)
        current_utf16 = 0
        start_index: int | None = None
        end_index: int | None = None

        for index, char in enumerate(text):
            if start_index is None and current_utf16 >= utf16_offset:
                start_index = index
            if end_index is None and current_utf16 >= utf16_end:
                end_index = index
                break

            current_utf16 += len(char.encode("utf-16-le")) // 2

            if start_index is None and current_utf16 >= utf16_offset:
                start_index = index + 1
            if end_index is None and current_utf16 >= utf16_end:
                end_index = index + 1
                break

        if start_index is None:
            start_index = len(text)
        if end_index is None:
            end_index = len(text)

        return start_index, max(start_index, end_index)

    @staticmethod
    def _entity_to_at(entity: Any, entity_text: str) -> At | None:
        cleaned = entity_text.strip()
        if isinstance(entity, MessageEntityMention):
            username = cleaned.lstrip("@")
            if username:
                return At(qq=username, name=username)
            return None

        if isinstance(entity, MessageEntityMentionName):
            user_id = str(getattr(entity, "user_id", "")).strip()
            if user_id:
                display = cleaned.lstrip("@") or user_id
                return At(qq=user_id, name=display)
            return None

        if isinstance(entity, MessageEntityTextUrl):
            url = str(getattr(entity, "url", "") or "")
            match = re.search(r"tg://user\?id=(\d+)", url)
            if match:
                user_id = match.group(1)
                display = cleaned.lstrip("@") or user_id
                return At(qq=user_id, name=display)
        return None

    async def _parse_media_components(self, msg: Any) -> list[Any]:
        media = msg.media

        if isinstance(media, MessageMediaContact):
            first_name = str(getattr(media, "first_name", "") or "").strip()
            last_name = str(getattr(media, "last_name", "") or "").strip()
            full_name = " ".join(x for x in [first_name, last_name] if x).strip()
            phone_number = str(getattr(media, "phone_number", "") or "").strip()
            user_id = str(getattr(media, "user_id", "") or "").strip()
            text = f"[联系人] {full_name}".strip()
            if phone_number:
                text += f" {phone_number}"
            if user_id and user_id != "0":
                text += f" (id:{user_id})"
            return [Plain(text=text)]

        if isinstance(media, (MessageMediaGeo, MessageMediaGeoLive)):
            geo = getattr(media, "geo", None)
            if geo and not isinstance(geo, GeoPointEmpty):
                lat = float(getattr(geo, "lat", 0.0))
                lon = float(getattr(geo, "long", 0.0))
                return [
                    Location(lat=lat, lon=lon, title="Location", content=f"{lat},{lon}"),
                    Plain(text=f"[位置] {lat},{lon}"),
                ]

        if not self.download_incoming_media:
            return []

        components: list[Any] = []
        file_name = self._guess_media_name(msg)
        lazy_media = TelethonLazyMedia(
            msg=msg,
            temp_dir_getter=self._get_media_temp_dir,
            register_temp_file=self._register_temp_file,
            fallback_name=file_name,
        )

        if msg.photo:
            components.append(LazyImage(downloader=lazy_media))
            return components

        if msg.document:
            mime_type = getattr(msg.document, "mime_type", "") or ""
            attrs = getattr(msg.document, "attributes", []) or []
            is_video = any(isinstance(a, DocumentAttributeVideo) for a in attrs)
            is_audio = any(isinstance(a, DocumentAttributeAudio) for a in attrs)
            sticker_attr = next(
                (a for a in attrs if isinstance(a, DocumentAttributeSticker)),
                None,
            )

            if sticker_attr:
                sticker_emoji = str(getattr(sticker_attr, "alt", "") or "").strip()
                components.append(LazyImage(downloader=lazy_media))
                components.append(
                    Plain(text=f"[贴纸] {sticker_emoji}" if sticker_emoji else "[贴纸]")
                )
                return components

            if is_video or mime_type.startswith("video/"):
                components.append(LazyVideo(downloader=lazy_media))
            elif is_audio or mime_type.startswith("audio/"):
                components.append(LazyRecord(downloader=lazy_media))
                components.append(LazyFile(name=file_name, downloader=lazy_media))
                components.append(Plain(text=f"[音频] {file_name}"))
            else:
                components.append(LazyFile(name=file_name, downloader=lazy_media))
            return components

        components.append(LazyFile(name=file_name, downloader=lazy_media))
        return components

    @staticmethod
    def _guess_media_name(msg: Any) -> str:
        if getattr(msg, "file", None) and getattr(msg.file, "name", None):
            return str(msg.file.name)

        attrs = getattr(getattr(msg, "document", None), "attributes", []) or []
        for attr in attrs:
            if isinstance(attr, DocumentAttributeFilename):
                file_name = str(getattr(attr, "file_name", "") or "").strip()
                if file_name:
                    return file_name

        if getattr(msg, "photo", None):
            return f"telethon_photo_{getattr(msg, 'id', 'unknown')}.jpg"
        if getattr(msg, "document", None):
            return f"telethon_media_{getattr(msg, 'id', 'unknown')}.bin"
        return f"telethon_file_{getattr(msg, 'id', 'unknown')}.bin"
