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
from .telethon_adapter.services.profile_service import TelethonProfileService
from .telethon_adapter.services import (
    TelethonPruneService,
    TelethonSender,
    TelethonStatusService,
)
from .telethon_adapter import TelethonPlatformAdapter  # noqa: F401

PRUNE_RESULT_TTL_SECONDS = 15.0


@register(PLUGIN_NAME, PLUGIN_AUTHOR, PLUGIN_DESC, PLUGIN_VERSION, PLUGIN_REPO)
class TelethonAdapterPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        self.context = context
        self._profile_service = TelethonProfileService()
        self._prune_service = TelethonPruneService()
        self._status_service = TelethonStatusService(context)
        self._sender = TelethonSender()

    @filter.command_group("tg")
    def tg(self) -> None:
        """Telethon 扩展命令。"""

    def _log_command_debug(self, event: AstrMessageEvent, command: str, **kwargs: str) -> None:
        if not bool(getattr(event, "telethon_debug_logging", False)):
            return

        extra = " ".join(f"{key}=%r" for key in kwargs)
        suffix = f" {extra}" if extra else ""
        logger.info(
            f"[Telethon][Debug] {command}: session_id=%s sender_id=%s "
            f"platform_id=%s message_str=%r{suffix}",
            getattr(event, "session_id", None),
            getattr(event, "get_sender_id", lambda: "")(),
            getattr(getattr(event, "platform_meta", None), "id", None),
            getattr(event, "message_str", ""),
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

    async def _send_text_result(
        self,
        event: AstrMessageEvent,
        text: str,
        *,
        auto_delete_after: float | None = None,
        **log_kwargs: str,
    ) -> bool:
        try:
            sent_message = await self._sender.send_html_message(event, text)
        except ValueError:
            event.set_result(text)
            return False
        except Exception as exc:
            logger.exception("[Telethon] 发送结果失败", extra=log_kwargs or None)
            event.set_result(f"发送结果失败: {exc}")
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
        self._log_command_debug(event, log_name, target=target, count=count)
        if not self._ensure_supported_event(event, "当前事件不来自 Telethon 适配器，无法执行批量删除。"):
            return

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
            event.set_result(str(exc))
            return
        except Exception as exc:
            logger.exception(
                "[Telethon] 执行 %s 失败: target=%r count=%r",
                log_name.removeprefix("tg_"),
                target,
                count,
            )
            event.set_result(f"批量删除失败: {exc}")
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
        failure_message: str,
        execute: callable,
        send_result: callable,
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
            logger.exception("[Telethon] 执行 %s 失败", log_name.removeprefix("tg_"))
            event.set_result(f"{failure_message}: {exc}")
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
        """获取 Telegram 用户/群组/频道资料。tg profile [@username|id|t.me 链接]"""
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
                    file_path=payload.avatar_path,
                    follow_reply=True,
                )
                return True
            except ValueError:
                event.set_result(payload.text)
                return False
            except Exception as exc:
                logger.exception("[Telethon] 发送 profile 结果失败: target=%r", target)
                event.set_result(f"发送资料失败: {exc}")
                return False

        await self._run_query_command(
            event,
            log_name="tg_profile",
            unsupported_message="当前事件不来自 Telethon 适配器，无法获取 MTProto 资料。",
            failure_message="获取资料失败",
            execute=_execute,
            send_result=_send,
        )

    @tg.command("status")
    @filter.permission_type(filter.PermissionType.ADMIN)
    async def tg_status(self, event: AstrMessageEvent) -> None:
        """获取当前 AstrBot 进程的运行状态。tg status"""
        async def _execute():
            return await self._status_service.build_status_text(event)

        async def _send(status_text: str) -> bool:
            return await self._send_text_result(event, status_text)

        await self._run_query_command(
            event,
            log_name="tg_status",
            unsupported_message="当前事件不来自 Telethon 适配器，无法获取状态信息。",
            failure_message="获取状态失败",
            execute=_execute,
            send_result=_send,
        )

    @tg.command("prune")
    @filter.permission_type(filter.PermissionType.ADMIN)
    async def tg_prune(self, event: AstrMessageEvent, count: str = "") -> None:
        """批量删除当前会话中的最近消息。tg prune [数量]，回复某条消息时可省略数量。"""
        await self._run_prune_command(
            event,
            count=count,
            usage_message="删除数量必须是正整数。用法: `tg prune 20`。",
            log_name="tg_prune",
        )

    @tg.command("selfprune")
    @filter.permission_type(filter.PermissionType.ADMIN)
    async def tg_selfprune(self, event: AstrMessageEvent, count: str = "") -> None:
        """仅删除自己发出的消息。tg selfprune [数量]，回复某条消息时可省略数量。"""
        await self._run_prune_command(
            event,
            count=count,
            usage_message="删除数量必须是正整数。用法: `tg selfprune 20`。",
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
        """删除指定用户的消息。tg youprune [@username] [数量]，也支持配合 @ 提及或回复目标消息。"""
        await self._run_prune_command(
            event,
            count=count,
            usage_message=(
                "删除数量必须是正整数。用法: `tg youprune @username 20`，"
                "或回复目标消息后执行 `tg youprune 20`。"
            ),
            log_name="tg_youprune",
            target=target,
        )
