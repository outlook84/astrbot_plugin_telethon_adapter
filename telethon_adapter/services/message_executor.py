from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import importlib
from typing import Any, Awaitable, Callable

from astrbot.api import logger

try:
    from .contracts import TelethonEventContext, TelethonExecutionHost
except ImportError:
    from telethon_adapter.services.contracts import TelethonEventContext, TelethonExecutionHost

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

    async def send_media(
        self,
        event: TelethonExecutionHost,
        path: str,
        caption: str | None,
        reply_to: int | None,
        action_name: str,
        fallback_action: Any,
        mime_type: str | None = None,
        attributes: list[Any] | None = None,
        spoiler: bool = False,
    ) -> int | None:
        effective_reply_to = event._effective_reply_to(reply_to)
        try:
            async with self.chat_action_scope(event, action_name, fallback_action):
                await event._send_media_request(
                    path,
                    caption=caption,
                    reply_to=reply_to,
                    mime_type=mime_type,
                    attributes=attributes,
                    spoiler=spoiler,
                )
        except Exception:
            context = self.message_log_context(event, effective_reply_to)
            logger.exception(
                "[Telethon] Failed to send media: chat_id=%s thread_id=%s msg_id=%s sender_id=%s reply_to=%s action=%s path=%s",
                context["chat_id"],
                context["thread_id"],
                context["msg_id"],
                context["sender_id"],
                context["reply_to"],
                action_name,
                path,
            )
        return reply_to

    async def build_album_media(
        self,
        event: TelethonExecutionHost,
        entity: Any,
        path: str,
        *,
        spoiler: bool = False,
        supports_streaming: bool = False,
    ) -> Any:
        types = _telethon_types()
        telethon_utils = _telethon_utils()
        functions = _telethon_functions()
        media_kwargs: dict[str, Any] = {}
        if supports_streaming:
            media_kwargs["supports_streaming"] = True
            media_kwargs["nosound_video"] = True

        _file_handle, media, _is_image = await self._build_input_media(
            event.client,
            path,
            **media_kwargs,
        )
        if spoiler:
            return await self.finalize_spoiler_media(
                event,
                entity,
                media,
                mime_type="video/mp4" if supports_streaming else None,
            )

        if isinstance(media, (types.InputMediaUploadedPhoto, types.InputMediaPhotoExternal)):
            result = await event.client(
                functions.messages.UploadMediaRequest(peer=entity, media=media)
            )
            return telethon_utils.get_input_media(result.photo)

        if isinstance(media, (types.InputMediaUploadedDocument, types.InputMediaDocumentExternal)):
            result = await event.client(
                functions.messages.UploadMediaRequest(peer=entity, media=media)
            )
            return telethon_utils.get_input_media(
                result.document,
                supports_streaming=supports_streaming,
            )

        return media

    async def send_local_media_group_request(
        self,
        event: TelethonExecutionHost,
        media_items: list[tuple[str, bool, bool]],
        *,
        caption: str | None,
        reply_to: int | None,
    ) -> None:
        functions = _telethon_functions()
        types = _telethon_types()
        entity = await event._resolve_input_peer()
        parsed_caption, msg_entities = await event._parse_formatting_entities(caption or "", None)
        single_media: list[Any] = []

        for index, (path, spoiler, is_video) in enumerate(media_items):
            media = await self.build_album_media(
                event,
                entity,
                path,
                spoiler=spoiler,
                supports_streaming=is_video,
            )
            single_media.append(
                types.InputSingleMedia(
                    media=media,
                    message=parsed_caption if index == 0 else "",
                    entities=msg_entities if index == 0 else None,
                )
            )

        request = functions.messages.SendMultiMediaRequest(
            peer=entity,
            multi_media=single_media,
            reply_to=event._normalize_low_level_reply_to(event._build_reply_to(reply_to)),
        )
        await event.client(request)

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
