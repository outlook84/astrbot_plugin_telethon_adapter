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
from .telethon_adapter.services import TelethonSender
from .telethon_adapter import TelethonPlatformAdapter  # noqa: F401


@register(PLUGIN_NAME, PLUGIN_AUTHOR, PLUGIN_DESC, PLUGIN_VERSION, PLUGIN_REPO)
class TelethonAdapterPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        self.context = context
        self._profile_service = TelethonProfileService()
        self._sender = TelethonSender()

    @filter.command_group("tg")
    def tg(self) -> None:
        """Telethon 扩展命令。"""

    @tg.command("profile")
    async def tg_profile(
        self,
        event: AstrMessageEvent,
        target: str = "",
    ) -> None:
        """获取 Telegram 用户/群组/频道资料。tg profile [@username|id|t.me 链接]"""
        if not self._profile_service.supports_event(event):
            event.set_result("当前事件不来自 Telethon 适配器，无法获取 MTProto 资料。")
            return

        try:
            payload = await self._profile_service.build_profile_payload(
                event,
                target,
                detailed=True,
            )
        except ValueError as exc:
            event.set_result(str(exc))
            return
        except Exception as exc:
            logger.exception("[Telethon] 获取 profile 失败: target=%r", target)
            event.set_result(f"获取资料失败: {exc}")
            return

        try:
            await self._sender.send_html_message(
                event,
                payload.text,
                file_path=payload.avatar_path,
            )
        except ValueError:
            event.set_result(payload.text)
        except Exception as exc:
            logger.exception("[Telethon] 发送 profile 结果失败: target=%r", target)
            event.set_result(f"发送资料失败: {exc}")
