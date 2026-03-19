from __future__ import annotations

from dataclasses import replace
from typing import Any

from astrbot.api import logger
try:
    from .contracts import TelethonDispatcherHost
except ImportError:
    from telethon_adapter.services.contracts import TelethonDispatcherHost
try:
    from .message_planner import MediaAction, TelethonMessagePlanner, TextAction
except ImportError:
    from telethon_adapter.services.message_planner import (
        MediaAction,
        TelethonMessagePlanner,
        TextAction,
    )
class TelethonMessageDispatcher:
    def __init__(self) -> None:
        self._planner = TelethonMessagePlanner()

    async def send(self, event: TelethonDispatcherHost, message: Any) -> None:
        if await self.try_send_local_media_group(event, message):
            await event._send_base_message(message)
            return

        plan = await self._planner.build(event, message)
        reply_to: int | None = plan.reply_to
        for action in plan.actions:
            if isinstance(action, TextAction):
                reply_to = await event._flush_text(list(action.parts), reply_to)
                continue
            if isinstance(action, MediaAction):
                effective_action = (
                    replace(action, reply_to=reply_to)
                    if reply_to is not None and action.reply_to != reply_to
                    else action
                )
                reply_to = await event._execute_media_action(effective_action)
        await event._send_base_message(message)

    async def try_send_local_media_group(self, event: TelethonDispatcherHost, message: Any) -> bool:
        plan = await self._planner.build_media_group_action(event, message)
        if plan is None:
            return False

        try:
            async with event._chat_action_scope(plan.action_name, plan.fallback_action):
                await event._execute_media_group_action(plan)
        except Exception:
            context = event._message_log_context(plan.reply_to)
            logger.exception(
                "[Telethon] Failed to send local media group: chat_id=%s thread_id=%s msg_id=%s sender_id=%s reply_to=%s count=%s",
                context["chat_id"],
                context["thread_id"],
                context["msg_id"],
                context["sender_id"],
                context["reply_to"],
                len(plan.media_items),
            )
            return False
        return True
