from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import importlib
from typing import Any, Awaitable, Callable

from astrbot.api import logger

from .contracts import TelethonEventContext, TelethonExecutionHost
from .message_planner import MediaAction, MediaGroupAction

BuildInputMedia = Callable[..., Awaitable[tuple[Any, Any, bool]]]


def _telethon_functions() -> Any:
    return importlib.import_module("telethon.functions")


def _telethon_types() -> Any:
    return importlib.import_module("telethon.types")


def _telethon_utils() -> Any:
    return importlib.import_module("telethon.utils")


class TelethonMessageExecutor:
    def __init__(self, *, build_input_media: BuildInputMedia) -> None:
        self._build_input_media = build_input_media

    def build_event_context(
        self,
        event: TelethonExecutionHost,
        reply_to: int | None = None,
    ) -> TelethonEventContext:
        message_obj = getattr(event, "message_obj", None)
        sender = getattr(message_obj, "sender", None)
        return TelethonEventContext(
            chat_id=event.peer,
            thread_id=event.thread_id,
            msg_id=getattr(message_obj, "message_id", None),
            sender_id=getattr(sender, "user_id", None),
            reply_to=event._effective_reply_to(reply_to),
        )

    def message_log_context(
        self,
        event: TelethonExecutionHost,
        reply_to: int | None = None,
    ) -> dict[str, Any]:
        context = self.build_event_context(event, reply_to)
        return {
            "chat_id": context.chat_id,
            "thread_id": context.thread_id,
            "msg_id": context.msg_id,
            "sender_id": context.sender_id,
            "reply_to": context.reply_to,
        }

    async def finalize_spoiler_media(
        self,
        event: TelethonExecutionHost,
        entity: Any,
        media: Any,
        *,
        mime_type: str | None,
    ) -> Any:
        functions = _telethon_functions()
        types = _telethon_types()
        telethon_utils = _telethon_utils()
        if hasattr(media, "spoiler"):
            media.spoiler = True

        if isinstance(media, types.InputMediaUploadedPhoto):
            result = await event.client(
                functions.messages.UploadMediaRequest(peer=entity, media=media)
            )
            spoiler_media = telethon_utils.get_input_media(result.photo)
            if hasattr(spoiler_media, "spoiler"):
                spoiler_media.spoiler = True
            return spoiler_media

        if isinstance(media, types.InputMediaUploadedDocument):
            result = await event.client(
                functions.messages.UploadMediaRequest(peer=entity, media=media)
            )
            spoiler_media = telethon_utils.get_input_media(
                result.document,
                supports_streaming=bool(mime_type and mime_type.startswith("video/")),
            )
            if hasattr(spoiler_media, "spoiler"):
                spoiler_media.spoiler = True
            return spoiler_media

        return media

    async def send_chat_action(self, event: TelethonExecutionHost, action: Any) -> None:
        functions = _telethon_functions()
        try:
            await event.client(
                functions.messages.SetTypingRequest(
                    peer=event.peer,
                    action=action,
                    top_msg_id=event.thread_id,
                )
            )
        except Exception as e:
            context = self.message_log_context(event)
            logger.warning(
                "[Telethon] Failed to send chat action: chat_id=%s msg_id=%s sender_id=%s error=%s",
                context["chat_id"],
                context["msg_id"],
                context["sender_id"],
                e,
            )

    @asynccontextmanager
    async def chat_action_scope(
        self,
        event: TelethonExecutionHost,
        action_name: str,
        fallback_action: Any,
    ):
        action_method = getattr(event.client, "action", None)
        if callable(action_method):
            try:
                async with action_method(event.peer, action_name):
                    yield
                return
            except Exception as e:
                context = self.message_log_context(event)
                logger.debug(
                    "[Telethon] Chat action context unavailable, falling back to a single chat action: "
                    "chat_id=%s msg_id=%s sender_id=%s action=%s error=%s",
                    context["chat_id"],
                    context["msg_id"],
                    context["sender_id"],
                    action_name,
                    e,
                )

        await self.send_chat_action(event, fallback_action)
        yield

    async def flush_text(
        self,
        event: TelethonExecutionHost,
        text_parts: list[tuple[str, bool]],
        reply_to: int | None,
    ) -> int | None:
        if not text_parts:
            return reply_to
        chunks = event._pack_text_chunks(text_parts)
        text_parts.clear()
        if chunks:
            await self.send_chat_action(event, _telethon_types().SendMessageTypingAction())
        for chunk in chunks:
            if not event._render_text_chunk(chunk).strip():
                continue
            await self.send_text_with_action(
                event,
                chunk,
                reply_to,
                send_typing_action=False,
            )
        return reply_to

    async def send_text_with_action(
        self,
        event: TelethonExecutionHost,
        text: str | list[tuple[str, bool]],
        reply_to: int | None,
        *,
        send_typing_action: bool = True,
    ) -> Any:
        if send_typing_action:
            await self.send_chat_action(event, _telethon_types().SendMessageTypingAction())
        effective_reply_to = event._effective_reply_to(reply_to)
        if isinstance(text, list):
            formatted_text = event._render_text_chunk(text)
            if any(is_html for _, is_html in text):
                return await event._send_text_request(
                    formatted_text,
                    parse_mode="html",
                    reply_to=reply_to,
                    link_preview=False,
                )
            text = "".join(part for part, _ in text)
        if not event._looks_like_markdown(text):
            return await event._send_text_request(
                text,
                parse_mode=None,
                reply_to=reply_to,
                link_preview=False,
            )
        try:
            formatted_text = await event._format_markdown_for_telethon_html_async(text)
            html_chunks = event._split_html_message(formatted_text)
            result = None
            for html_chunk in html_chunks:
                result = await event._send_text_request(
                    html_chunk,
                    parse_mode="html",
                    reply_to=reply_to,
                    link_preview=False,
                )
            return result
        except Exception as e:
            context = self.message_log_context(event, effective_reply_to)
            logger.warning(
                "[Telethon] Failed to convert Markdown to HTML, falling back to plain text: "
                "chat_id=%s thread_id=%s msg_id=%s sender_id=%s reply_to=%s error=%s",
                context["chat_id"],
                context["thread_id"],
                context["msg_id"],
                context["sender_id"],
                context["reply_to"],
                e,
            )
        return await event._send_text_request(
            text,
            parse_mode=None,
            reply_to=reply_to,
            link_preview=False,
        )

    async def execute_media_action(
        self,
        event: TelethonExecutionHost,
        action: MediaAction,
    ) -> int | None:
        effective_reply_to = event._effective_reply_to(action.reply_to)
        try:
            async with self.chat_action_scope(event, action.action_name, action.fallback_action):
                await event._send_media_request(action)
        except Exception:
            context = self.message_log_context(event, effective_reply_to)
            logger.exception(
                "[Telethon] Failed to send media: chat_id=%s thread_id=%s msg_id=%s sender_id=%s reply_to=%s action=%s path=%s",
                context["chat_id"],
                context["thread_id"],
                context["msg_id"],
                context["sender_id"],
                context["reply_to"],
                action.action_name,
                action.path,
            )
        return action.reply_to

    async def react(self, event: TelethonExecutionHost, emoji: str) -> None:
        functions = _telethon_functions()
        types = _telethon_types()
        raw_message = getattr(event.message_obj, "raw_message", None)
        react_method = getattr(raw_message, "react", None)
        if callable(react_method):
            try:
                await react_method(emoji)
                return
            except Exception as e:
                context = self.message_log_context(event)
                logger.warning(
                    "[Telethon] Native reaction failed, trying MTProto fallback: "
                    "chat_id=%s msg_id=%s sender_id=%s emoji=%s error=%s",
                    context["chat_id"],
                    context["msg_id"],
                    context["sender_id"],
                    emoji,
                    e,
                )

        message_id = getattr(event.message_obj, "message_id", None)
        try:
            await event.client(
                functions.messages.SendReactionRequest(
                    peer=event.peer,
                    msg_id=int(message_id),
                    reaction=[types.ReactionEmoji(emoticon=emoji)],
                )
            )
            return
        except Exception as e:
            context = self.message_log_context(event)
            logger.warning(
                "[Telethon] MTProto reaction failed: chat_id=%s msg_id=%s sender_id=%s emoji=%s error=%s",
                context["chat_id"],
                context["msg_id"],
                context["sender_id"],
                emoji,
                e,
            )

        logger.warning(
            "[Telethon] Current message object does not support native reactions; skipped pre-reaction emoji"
        )
