import asyncio
from typing import Awaitable, Callable, TypeVar

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, register

from .plugin_info import (
    PLUGIN_AUTHOR,
    PLUGIN_DESC,
    PLUGIN_NAME,
    PLUGIN_REPO,
    PLUGIN_VERSION,
)
from .telethon_adapter.i18n import t
from .telethon_adapter.services.profile_service import TelethonProfileService
from .telethon_adapter.services import (
    TelethonPruneService,
    TelethonSender,
    TelethonStickerService,
    TelethonStatusService,
)

PRUNE_RESULT_TTL_SECONDS = 15.0
T = TypeVar("T")


@register(PLUGIN_NAME, PLUGIN_AUTHOR, PLUGIN_DESC, PLUGIN_VERSION, PLUGIN_REPO)
class TelethonAdapterPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        from .telethon_adapter import TelethonPlatformAdapter  # noqa: F401

        self.context = context
        self._profile_service = TelethonProfileService()
        self._prune_service = TelethonPruneService()
        self._prune_lock = asyncio.Lock()
        self._sticker_service = TelethonStickerService(self)
        self._status_service = TelethonStatusService(context)
        self._sender = TelethonSender()

    @filter.command_group("tg")
    @filter.permission_type(filter.PermissionType.ADMIN)
    def tg(self) -> None:
        """Telethon 扩展命令. Telethon extension commands."""

    def _log_command_debug(self, event: AstrMessageEvent, command: str, **kwargs: str) -> None:
        extra = " ".join(f"{key}=%r" for key in kwargs)
        suffix = f" {extra}" if extra else ""
        logger.debug(
            f"[Telethon] command_received: command=%s session_id=%s sender_id=%s "
            f"platform_id=%s{suffix}",
            command,
            getattr(event, "session_id", None),
            getattr(event, "get_sender_id", lambda: "")(),
            getattr(getattr(event, "platform_meta", None), "id", None),
            *kwargs.values(),
        )

    def _ensure_supported_event(self, event: AstrMessageEvent, message: str) -> bool:
        if self._profile_service.supports_event(event):
            return True
        event.set_result(message)
        return False

    @staticmethod
    def _parse_optional_count(count: str, usage_message: str) -> int | None:
        normalized_count = str(count or "").strip()
        if not normalized_count:
            return None
        try:
            return int(normalized_count)
        except ValueError as exc:
            raise ValueError(usage_message) from exc

    @staticmethod
    def _normalize_prune_args(log_name: str, target: str = "", count: str = "") -> tuple[str, str]:
        normalized_target = str(target or "").strip()
        normalized_count = str(count or "").strip()
        if (
            log_name == "tg_youprune"
            and normalized_target
            and not normalized_count
            and normalized_target.lstrip("-").isdigit()
        ):
            normalized_count = normalized_target
            normalized_target = ""
        return normalized_target, normalized_count

    async def _send_text_result(
        self,
        event: AstrMessageEvent,
        text: str,
        *,
        auto_delete_after: float | None = None,
        link_preview: bool = False,
        **log_kwargs: str,
    ) -> bool:
        try:
            sent_message = await self._sender.send_html_message(
                event,
                text,
                link_preview=link_preview,
            )
        except ValueError:
            event.set_result(text)
            return False
        except Exception as exc:
            logger.exception("[Telethon] Failed to send result", extra=log_kwargs or None)
            event.set_result(t(event, "errors.send_result_failed", error=exc))
            return False
        else:
            if auto_delete_after is not None:
                self._sender.schedule_delete_message(
                    event,
                    sent_message,
                    auto_delete_after,
                )
            return True

    async def _try_delete_command_message(self, event: AstrMessageEvent) -> None:
        raw_message = getattr(getattr(event, "message_obj", None), "raw_message", None)
        if raw_message is None:
            return

        message_id = getattr(raw_message, "id", None)
        try:
            message_id = int(message_id) if message_id is not None else None
        except (TypeError, ValueError):
            return
        if message_id is None:
            return

        if bool(getattr(raw_message, "out", False)) or await self._can_delete_in_chat(raw_message):
            self._sender.schedule_delete_message(
                event,
                raw_message,
                0,
            )

    async def _can_delete_in_chat(self, raw_message: object) -> bool:
        get_chat = getattr(raw_message, "get_chat", None)
        if not callable(get_chat):
            return False
        try:
            chat = await get_chat()
        except Exception:
            return False
        if chat is None:
            return False
        if bool(getattr(chat, "creator", False)):
            return True
        admin_rights = getattr(chat, "admin_rights", None)
        return bool(getattr(admin_rights, "delete_messages", False))

    async def _run_prune_command(
        self,
        event: AstrMessageEvent,
        *,
        count: str,
        usage_message: str,
        log_name: str,
        only_self: bool = False,
        target: str = "",
    ) -> None:
        if not self._ensure_supported_event(event, t(event, "errors.unsupported_prune")):
            return

        normalized_target, normalized_count = self._normalize_prune_args(
            log_name,
            target,
            count,
        )
        self._log_command_debug(
            event,
            log_name,
            target=normalized_target,
            count=normalized_count,
        )
        if self._prune_lock.locked():
            event.set_result(t(event, "prune.busy"))
            return

        async with self._prune_lock:
            try:
                prune_count = self._parse_optional_count(normalized_count, usage_message)
                target_user = None
                if log_name == "tg_youprune":
                    target_user = await self._prune_service.resolve_target_user(event, normalized_target)
                result = await self._prune_service.prune_messages(
                    event,
                    prune_count,
                    only_self=only_self,
                    target_user=target_user,
                )
            except ValueError as exc:
                logger.debug(
                    "[Telethon] command_rejected: command=%s target=%r count=%r error=%s",
                    log_name,
                    normalized_target,
                    normalized_count,
                    exc,
                )
                event.set_result(str(exc))
                return
            except Exception as exc:
                logger.exception(
                    "[Telethon] Command %s failed: target=%r count=%r",
                    log_name.removeprefix("tg_"),
                    target,
                    count,
                )
                event.set_result(t(event, "errors.prune_failed", error=exc))
                return

        await self._send_text_result(
            event,
            self._prune_service.format_result_text(result),
            auto_delete_after=PRUNE_RESULT_TTL_SECONDS,
        )

    async def _run_query_command(
        self,
        event: AstrMessageEvent,
        *,
        log_name: str,
        unsupported_message: str,
        failure_key: str,
        execute: Callable[[], Awaitable[T]],
        send_result: Callable[[T], Awaitable[object]],
    ) -> None:
        self._log_command_debug(event, log_name)
        if not self._ensure_supported_event(event, unsupported_message):
            return

        try:
            payload = await execute()
        except ValueError as exc:
            event.set_result(str(exc))
            return
        except Exception as exc:
            logger.exception("[Telethon] Command %s failed", log_name.removeprefix("tg_"))
            event.set_result(t(event, failure_key, error=exc))
            return

        sent = await send_result(payload)
        if sent:
            await self._try_delete_command_message(event)

    @tg.command("profile")
    @filter.permission_type(filter.PermissionType.ADMIN)
    async def tg_profile(
        self,
        event: AstrMessageEvent,
        target: str = "",
    ) -> None:
        """获取 Telegram 用户/群组/频道资料. Get Telegram user/group/channel profile. tg profile [@username|id|t.me link]"""
        async def _execute():
            return await self._profile_service.build_profile_payload(
                event,
                target,
                detailed=True,
            )

        async def _send(payload) -> bool:
            try:
                await self._sender.send_html_message(
                    event,
                    payload.text,
                    file_path=payload.avatar_file,
                    follow_reply=True,
                )
                return True
            except ValueError:
                event.set_result(payload.text)
                return False
            except Exception as exc:
                logger.exception("[Telethon] Failed to send profile result: target=%r", target)
                event.set_result(t(event, "errors.profile_send_failed", error=exc))
                return False

        await self._run_query_command(
            event,
            log_name="tg_profile",
            unsupported_message=t(event, "errors.unsupported_profile"),
            failure_key="errors.profile_failed",
            execute=_execute,
            send_result=_send,
        )

    @tg.command("status")
    @filter.permission_type(filter.PermissionType.ADMIN)
    async def tg_status(self, event: AstrMessageEvent) -> None:
        """获取当前 AstrBot 进程的运行状态. Show current AstrBot process status. tg status"""
        async def _execute():
            return await self._status_service.build_status_text(event)

        async def _send(status_text: str) -> bool:
            return await self._send_text_result(event, status_text)

        await self._run_query_command(
            event,
            log_name="tg_status",
            unsupported_message=t(event, "errors.unsupported_status"),
            failure_key="errors.status_failed",
            execute=_execute,
            send_result=_send,
        )

    @tg.command("sticker")
    @filter.permission_type(filter.PermissionType.ADMIN)
    async def tg_sticker(
        self,
        event: AstrMessageEvent,
        arg1: str = "",
        arg2: str = "",
    ) -> None:
        """设置默认贴纸包名，或把回复的图片/贴纸加入自己的贴纸包. Set default sticker pack or add replied media. tg sticker [pack_name|emoji] [emoji]"""
        self._log_command_debug(event, "tg_sticker", arg1=arg1, arg2=arg2)
        if not self._profile_service.supports_event(event):
            await self._send_text_result(
                event,
                t(event, "errors.unsupported_sticker"),
                auto_delete_after=PRUNE_RESULT_TTL_SECONDS,
            )
            return

        try:
            payload = await self._sticker_service.handle_command(event, arg1, arg2)
        except ValueError as exc:
            await self._send_text_result(
                event,
                str(exc),
                auto_delete_after=PRUNE_RESULT_TTL_SECONDS,
            )
            return
        except Exception as exc:
            logger.exception("[Telethon] Sticker command failed: arg1=%r arg2=%r", arg1, arg2)
            await self._send_text_result(
                event,
                t(event, "errors.sticker_failed", error=exc),
                auto_delete_after=PRUNE_RESULT_TTL_SECONDS,
            )
            return

        sent = await self._send_text_result(
            event,
            payload.text,
            link_preview=payload.link_preview,
            auto_delete_after=PRUNE_RESULT_TTL_SECONDS,
        )
        if sent:
            await self._try_delete_command_message(event)

    @tg.command("prune")
    @filter.permission_type(filter.PermissionType.ADMIN)
    async def tg_prune(self, event: AstrMessageEvent, count: str = "") -> None:
        """批量删除当前会话中的最近消息. Delete recent messages in current chat. tg prune [count], or reply to a message and omit count."""
        await self._run_prune_command(
            event,
            count=count,
            usage_message=t(event, "prune.usage"),
            log_name="tg_prune",
        )

    @tg.command("selfprune")
    @filter.permission_type(filter.PermissionType.ADMIN)
    async def tg_selfprune(self, event: AstrMessageEvent, count: str = "") -> None:
        """仅删除自己发出的消息. Delete only your own messages. tg selfprune [count], or reply to a message and omit count."""
        await self._run_prune_command(
            event,
            count=count,
            usage_message=t(event, "prune.self_usage"),
            log_name="tg_selfprune",
            only_self=True,
        )

    @tg.command("youprune")
    @filter.permission_type(filter.PermissionType.ADMIN)
    async def tg_youprune(
        self,
        event: AstrMessageEvent,
        target: str = "",
        count: str = "",
    ) -> None:
        """删除指定用户的消息. Delete messages from a target user. tg youprune [@username] [count], or use a mention/reply."""
        await self._run_prune_command(
            event,
            count=count,
            usage_message=t(event, "prune.you_usage"),
            log_name="tg_youprune",
            target=target,
        )
