from __future__ import annotations

import html
import os
import re
from contextlib import asynccontextmanager
from typing import Any

from bs4 import BeautifulSoup
import markdown
from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, MessageChain
from astrbot.api.message_components import (
    At,
    File,
    Image,
    Location,
    Plain,
    Record,
    Reply,
    Video,
)
from astrbot.api.platform import AstrBotMessage, PlatformMetadata
from telethon import functions, types, utils as telethon_utils

try:
    from .i18n import get_event_language, t
except ImportError:
    from telethon_adapter.i18n import get_event_language, t

try:
    from .fast_upload import build_input_media, should_use_fast_upload
except ImportError:
    from telethon_adapter.fast_upload import build_input_media, should_use_fast_upload


class TelethonEvent(AstrMessageEvent):
    META_ATTR = "_gdl_meta"
    MEDIA_GROUP_INTENT = "media_group"
    MAX_MESSAGE_LENGTH = 4096
    SPLIT_PATTERNS = {
        "paragraph": re.compile(r"\n\n"),
        "line": re.compile(r"\n"),
        "sentence": re.compile(r"[.!?。！？]"),
        "word": re.compile(r"\s"),
    }
    MARKDOWN_HINT_PATTERNS = (
        re.compile(r"```"),
        re.compile(r"(?m)^\s{0,3}#{1,6}\s+\S"),
        re.compile(r"(?m)^\s{0,3}>\s+\S"),
        re.compile(r"(?m)^\s{0,3}(?:[-*+]\s+\S|\d+\.\s+\S)"),
        re.compile(r"(?m)^\|.+\|\s*$"),
        re.compile(r"\[[^\]\n]+\]\((?:https?://|tg://)[^)]+\)"),
        re.compile(r"(?<!\*)\*\*[^*\n]+\*\*(?!\*)"),
        re.compile(r"(?<!_)__[^_\n]+__(?!_)"),
        re.compile(r"`[^`\n]+`"),
    )

    @staticmethod
    def _is_gif_path(path: str) -> bool:
        if path.lower().endswith(".gif"):
            return True
        try:
            with open(path, "rb") as f:
                return f.read(6) in (b"GIF87a", b"GIF89a")
        except OSError:
            return False

    def __init__(
        self,
        message_str: str,
        message_obj: AstrBotMessage,
        platform_meta: PlatformMetadata,
        session_id: str,
        client: Any,
    ) -> None:
        super().__init__(message_str, message_obj, platform_meta, session_id)
        self.client = client
        self.peer, self.thread_id = self._parse_session_target(session_id)

    @staticmethod
    def _parse_session_target(session_id: str) -> tuple[int, int | None]:
        normalized = str(session_id or "").strip()
        if not normalized:
            raise ValueError("session_id is empty")
        peer_part, separator, thread_part = normalized.partition("#")
        peer = int(peer_part)
        if not separator:
            return peer, None
        return peer, int(thread_part) if thread_part else None

    def _effective_reply_to(self, reply_to: int | None) -> int | None:
        if reply_to is not None:
            return reply_to
        return self.thread_id

    def _build_reply_to(self, reply_to: int | None) -> Any | None:
        effective_reply_to = self._effective_reply_to(reply_to)
        if effective_reply_to is None:
            return None
        if self.thread_id is None:
            return effective_reply_to
        return types.InputReplyToMessage(
            reply_to_msg_id=effective_reply_to,
            top_msg_id=self.thread_id,
        )

    @staticmethod
    def _normalize_low_level_reply_to(reply_to: Any | None) -> Any | None:
        if reply_to is None or isinstance(reply_to, types.InputReplyToMessage):
            return reply_to
        return types.InputReplyToMessage(reply_to_msg_id=int(reply_to))

    async def _resolve_input_peer(self) -> Any:
        get_input_entity = getattr(self.client, "get_input_entity", None)
        if callable(get_input_entity):
            return await get_input_entity(self.peer)
        return self.peer

    async def _parse_formatting_entities(
        self,
        text: str,
        parse_mode: str | None,
    ) -> tuple[str, Any | None]:
        if parse_mode is None:
            return text, None
        parse_message_text = getattr(self.client, "_parse_message_text", None)
        if callable(parse_message_text):
            return await parse_message_text(text, parse_mode)
        return text, None

    async def _execute_request(self, request: Any, entity: Any) -> Any:
        result = await self.client(request)
        get_response_message = getattr(self.client, "_get_response_message", None)
        if callable(get_response_message):
            return get_response_message(request, result, entity)
        return result

    async def _send_text_request(
        self,
        text: str,
        *,
        parse_mode: str | None,
        reply_to: int | None,
        link_preview: bool,
    ) -> Any:
        telethon_reply_to = self._build_reply_to(reply_to)
        if not self._should_use_low_level_text_request():
            payload = {
                "reply_to": telethon_reply_to,
                "link_preview": link_preview,
            }
            if parse_mode is not None:
                payload["parse_mode"] = parse_mode
            return await self.client.send_message(
                self.peer,
                text,
                **payload,
            )

        entity = await self._resolve_input_peer()
        message, entities = await self._parse_formatting_entities(text, parse_mode)
        request = functions.messages.SendMessageRequest(
            peer=entity,
            message=message,
            entities=entities,
            no_webpage=not link_preview,
            reply_to=telethon_reply_to,
        )
        return await self._execute_request(request, entity)

    async def _send_media_request(
        self,
        path: str,
        *,
        caption: str | None,
        reply_to: int | None,
        mime_type: str | None = None,
        attributes: list[Any] | None = None,
        spoiler: bool = False,
    ) -> Any:
        telethon_reply_to = self._build_reply_to(reply_to)
        if not self._should_use_low_level_media_request(
            spoiler=spoiler
        ) and not should_use_fast_upload(self.client, path):
            payload: dict[str, Any] = {
                "caption": caption,
                "reply_to": telethon_reply_to,
            }
            if mime_type is not None:
                payload["mime_type"] = mime_type
            if attributes:
                payload["attributes"] = attributes
            return await self.client.send_file(self.peer, file=path, **payload)

        entity = await self._resolve_input_peer()
        parsed_caption, msg_entities = await self._parse_formatting_entities(
            caption or "",
            None,
        )
        low_level_reply_to = self._normalize_low_level_reply_to(telethon_reply_to)
        media_kwargs: dict[str, Any] = {}
        if mime_type is not None:
            media_kwargs["mime_type"] = mime_type
        if attributes:
            media_kwargs["attributes"] = attributes
        _file_handle, media, _is_image = await build_input_media(
            self.client,
            path,
            **media_kwargs,
        )
        if spoiler:
            media = await self._finalize_spoiler_media(
                entity,
                media,
                mime_type=mime_type,
            )
        request = functions.messages.SendMediaRequest(
            peer=entity,
            media=media,
            reply_to=low_level_reply_to,
            message=parsed_caption,
            entities=msg_entities,
        )
        return await self._execute_request(request, entity)

    async def _finalize_spoiler_media(
        self,
        entity: Any,
        media: Any,
        *,
        mime_type: str | None,
    ) -> Any:
        if hasattr(media, "spoiler"):
            media.spoiler = True

        if isinstance(media, types.InputMediaUploadedPhoto):
            result = await self.client(
                functions.messages.UploadMediaRequest(
                    peer=entity,
                    media=media,
                )
            )
            spoiler_media = telethon_utils.get_input_media(result.photo)
            if hasattr(spoiler_media, "spoiler"):
                spoiler_media.spoiler = True
            return spoiler_media

        if isinstance(media, types.InputMediaUploadedDocument):
            result = await self.client(
                functions.messages.UploadMediaRequest(
                    peer=entity,
                    media=media,
                )
            )
            spoiler_media = telethon_utils.get_input_media(
                result.document,
                supports_streaming=bool(mime_type and mime_type.startswith("video/")),
            )
            if hasattr(spoiler_media, "spoiler"):
                spoiler_media.spoiler = True
            return spoiler_media

        return media

    def _message_log_context(self, reply_to: int | None = None) -> dict[str, Any]:
        message_obj = getattr(self, "message_obj", None)
        sender = getattr(message_obj, "sender", None)
        return {
            "chat_id": self.peer,
            "thread_id": self.thread_id,
            "msg_id": getattr(message_obj, "message_id", None),
            "sender_id": getattr(sender, "user_id", None),
            "reply_to": self._effective_reply_to(reply_to),
        }

    def _label(self, key: str) -> str:
        return f"[{t(get_event_language(self), key)}]"

    async def _send_chat_action(self, action: types.TypeSendMessageAction) -> None:
        try:
            await self.client(
                functions.messages.SetTypingRequest(
                    peer=self.peer,
                    action=action,
                    top_msg_id=self.thread_id,
                )
            )
        except Exception as e:
            context = self._message_log_context()
            logger.warning(
                "[Telethon] Failed to send chat action: chat_id=%s msg_id=%s sender_id=%s error=%s",
                context["chat_id"],
                context["msg_id"],
                context["sender_id"],
                e,
            )

    @asynccontextmanager
    async def _chat_action_scope(
        self,
        action_name: str,
        fallback_action: types.TypeSendMessageAction,
    ):
        action_method = getattr(self.client, "action", None)
        if callable(action_method):
            try:
                async with action_method(self.peer, action_name):
                    yield
                return
            except Exception as e:
                context = self._message_log_context()
                logger.debug(
                    "[Telethon] Chat action context unavailable, falling back to a single chat action: "
                    "chat_id=%s msg_id=%s sender_id=%s action=%s error=%s",
                    context["chat_id"],
                    context["msg_id"],
                    context["sender_id"],
                    action_name,
                    e,
                )

        await self._send_chat_action(fallback_action)
        yield

    async def _flush_text(
        self, text_parts: list[tuple[str, bool]], reply_to: int | None
    ) -> int | None:
        if not text_parts:
            return reply_to
        chunks = self._pack_text_chunks(text_parts)
        text_parts.clear()
        if chunks:
            await self.send_typing()
        for chunk in chunks:
            if not self._render_text_chunk(chunk).strip():
                continue
            await self._send_text_with_action(chunk, reply_to, send_typing_action=False)
        return reply_to

    async def _send_media(
        self,
        path: str,
        caption: str | None,
        reply_to: int | None,
        action_name: str,
        fallback_action: types.TypeSendMessageAction,
        mime_type: str | None = None,
        attributes: list[Any] | None = None,
        spoiler: bool = False,
    ) -> int | None:
        effective_reply_to = self._effective_reply_to(reply_to)
        try:
            async with self._chat_action_scope(action_name, fallback_action):
                await self._send_media_request(
                    path,
                    caption=caption,
                    reply_to=reply_to,
                    mime_type=mime_type,
                    attributes=attributes,
                    spoiler=spoiler,
                )
        except Exception:
            context = self._message_log_context(effective_reply_to)
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

    async def _build_album_media(
        self,
        entity: Any,
        path: str,
        *,
        spoiler: bool = False,
        supports_streaming: bool = False,
    ) -> Any:
        media_kwargs: dict[str, Any] = {}
        if supports_streaming:
            media_kwargs["supports_streaming"] = True
            media_kwargs["nosound_video"] = True

        _file_handle, media, _is_image = await build_input_media(
            self.client,
            path,
            **media_kwargs,
        )
        if spoiler:
            return await self._finalize_spoiler_media(
                entity,
                media,
                mime_type="video/mp4" if supports_streaming else None,
            )

        if isinstance(media, (types.InputMediaUploadedPhoto, types.InputMediaPhotoExternal)):
            result = await self.client(
                functions.messages.UploadMediaRequest(
                    peer=entity,
                    media=media,
                )
            )
            return telethon_utils.get_input_media(result.photo)

        if isinstance(
            media,
            (types.InputMediaUploadedDocument, types.InputMediaDocumentExternal),
        ):
            result = await self.client(
                functions.messages.UploadMediaRequest(
                    peer=entity,
                    media=media,
                )
            )
            return telethon_utils.get_input_media(
                result.document,
                supports_streaming=supports_streaming,
            )

        return media

    async def _send_local_media_group_request(
        self,
        media_items: list[tuple[str, bool, bool]],
        *,
        caption: str | None,
        reply_to: int | None,
    ) -> None:
        entity = await self._resolve_input_peer()
        parsed_caption, msg_entities = await self._parse_formatting_entities(
            caption or "",
            None,
        )
        single_media: list[Any] = []

        for index, (path, spoiler, is_video) in enumerate(media_items):
            media = await self._build_album_media(
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
            reply_to=self._normalize_low_level_reply_to(self._build_reply_to(reply_to)),
        )
        await self.client(request)

    async def _try_send_local_media_group(self, message: MessageChain) -> bool:
        meta = getattr(message, self.META_ATTR, None)
        if not isinstance(meta, dict) or meta.get("intent") != self.MEDIA_GROUP_INTENT:
            return False

        reply_to: int | None = None
        caption_parts: list[str] = []
        media_items: list[tuple[str, bool, bool]] = []
        action_name = "photo"
        has_spoiler = False

        for item in message.chain:
            if isinstance(item, Reply):
                try:
                    reply_to = int(item.id)
                except (TypeError, ValueError):
                    logger.warning(
                        f"[Telethon] Failed to parse media-group reply ID: {item.id}"
                    )
                    return False
                continue
            if isinstance(item, Plain):
                caption_parts.append(item.text)
                continue
            if isinstance(item, Image):
                file_path = await item.convert_to_file_path()
                if self._is_gif_path(file_path):
                    return False
                item_spoiler = self._component_has_spoiler(item)
                has_spoiler = has_spoiler or item_spoiler
                media_items.append((file_path, item_spoiler, False))
                continue
            if isinstance(item, Video):
                file_path = await item.convert_to_file_path()
                item_spoiler = self._component_has_spoiler(item)
                has_spoiler = has_spoiler or item_spoiler
                action_name = "video"
                media_items.append((file_path, item_spoiler, True))
                continue
            return False

        if len(media_items) < 2:
            return False

        caption = "".join(caption_parts).strip() or None
        fallback_action: types.TypeSendMessageAction
        if action_name == "photo":
            fallback_action = types.SendMessageUploadPhotoAction(progress=0)
        else:
            fallback_action = types.SendMessageUploadVideoAction(progress=0)

        try:
            async with self._chat_action_scope(action_name, fallback_action):
                if not self._should_use_low_level_media_group_request(
                    has_spoiler=has_spoiler
                ) and not any(
                    should_use_fast_upload(self.client, path)
                    for path, _spoiler, _is_video in media_items
                ):
                    await self.client.send_file(
                        self.peer,
                        file=[path for path, _spoiler, _is_video in media_items],
                        caption=caption,
                        reply_to=self._build_reply_to(reply_to),
                    )
                else:
                    await self._send_local_media_group_request(
                        media_items,
                        caption=caption,
                        reply_to=reply_to,
                    )
        except Exception:
            context = self._message_log_context(reply_to)
            logger.exception(
                "[Telethon] Failed to send local media group: chat_id=%s thread_id=%s msg_id=%s sender_id=%s reply_to=%s count=%s",
                context["chat_id"],
                context["thread_id"],
                context["msg_id"],
                context["sender_id"],
                context["reply_to"],
                len(media_items),
            )
            return False
        return True

    def _should_use_low_level_text_request(self) -> bool:
        return self.thread_id is not None

    def _should_use_low_level_media_request(self, *, spoiler: bool) -> bool:
        return self.thread_id is not None or spoiler

    def _should_use_low_level_media_group_request(self, *, has_spoiler: bool) -> bool:
        return self.thread_id is not None or has_spoiler

    async def send_typing(self) -> None:
        await self._send_chat_action(types.SendMessageTypingAction())

    async def send(self, message: MessageChain):
        if await self._try_send_local_media_group(message):
            await super().send(message)
            return

        reply_to: int | None = None
        text_parts: list[tuple[str, bool]] = []

        for item in message.chain:
            if isinstance(item, Reply):
                try:
                    reply_to = int(item.id)
                except (TypeError, ValueError):
                    logger.warning(f"[Telethon] Failed to parse reply ID: {item.id}")
                continue

            if isinstance(item, At):
                at_html = self._format_at_html(item)
                if at_html:
                    text_parts.append((at_html, True))
                else:
                    text_parts.append((self._format_at_text(item), False))
                continue

            if isinstance(item, Plain):
                text_parts.append((item.text, False))
                continue

            if isinstance(item, Location):
                text_parts.append(
                    (
                        f"{self._label('message.media.location')} "
                        f"{item.lat},{item.lon} {item.title or ''}".strip(),
                        False,
                    )
                )
                continue

            # 发送媒体前先把缓冲文本发掉，避免消息顺序错乱。
            reply_to = await self._flush_text(text_parts, reply_to)

            if isinstance(item, Image):
                file_path = await item.convert_to_file_path()
                is_gif = self._is_gif_path(file_path)
                reply_to = await self._send_media(
                    file_path,
                    None,
                    reply_to,
                    "video" if is_gif else "photo",
                    (
                        types.SendMessageUploadVideoAction(progress=0)
                        if is_gif
                        else types.SendMessageUploadPhotoAction(progress=0)
                    ),
                    mime_type="image/gif" if is_gif else None,
                    attributes=[types.DocumentAttributeAnimated()] if is_gif else None,
                    spoiler=self._component_has_spoiler(item),
                )
                continue

            if isinstance(item, Video):
                file_path = await item.convert_to_file_path()
                reply_to = await self._send_media(
                    file_path,
                    None,
                    reply_to,
                    "video",
                    types.SendMessageUploadVideoAction(progress=0),
                    spoiler=self._component_has_spoiler(item),
                )
                continue

            if isinstance(item, Record):
                file_path = await item.convert_to_file_path()
                reply_to = await self._send_media(
                    file_path,
                    item.text,
                    reply_to,
                    "audio",
                    types.SendMessageUploadAudioAction(progress=0),
                )
                continue

            if isinstance(item, File):
                file_path = await item.get_file()
                reply_to = await self._send_media(
                    file_path,
                    item.name,
                    reply_to,
                    "document",
                    types.SendMessageUploadDocumentAction(progress=0),
                )
                continue

            logger.warning(f"[Telethon] Unsupported message segment type: {item.type}")

        await self._flush_text(text_parts, reply_to)
        await super().send(message)

    @staticmethod
    def _format_at_text(item: At) -> str:
        qq_str = str(item.qq).strip()
        if qq_str.startswith("@"):
            return f"{qq_str} "
        display = str(item.name or "").strip()
        if display.startswith("@"):
            return f"{display} "
        if display and " " not in display:
            return f"@{display} "
        if qq_str:
            return f"@{qq_str} "
        return f"@{qq_str} "

    @classmethod
    def _format_at_html(cls, item: At) -> str | None:
        qq_str = str(item.qq).strip()
        display = cls._format_at_text(item).strip()
        if qq_str.isdigit():
            href = f"tg://user?id={qq_str}"
            return f'<a href="{href}">{html.escape(display)}</a> '

        username = ""
        if qq_str.startswith("@"):
            username = qq_str[1:]
        elif qq_str and " " not in qq_str:
            username = qq_str
        else:
            raw_name = str(item.name or "").strip()
            if raw_name.startswith("@"):
                username = raw_name[1:]
            elif raw_name and " " not in raw_name:
                username = raw_name

        if not username:
            return None
        href = f"https://t.me/{html.escape(username, quote=True)}"
        return f'<a href="{href}">{html.escape(display)}</a> '

    @classmethod
    def _split_message(cls, text: str) -> list[str]:
        if len(text) <= cls.MAX_MESSAGE_LENGTH:
            return [text]
        chunks: list[str] = []
        while text:
            if len(text) <= cls.MAX_MESSAGE_LENGTH:
                chunks.append(text)
                break

            split_point = cls.MAX_MESSAGE_LENGTH
            segment = text[: cls.MAX_MESSAGE_LENGTH]
            for _, pattern in cls.SPLIT_PATTERNS.items():
                matches = list(pattern.finditer(segment))
                if matches:
                    split_point = matches[-1].end()
                    break
            chunks.append(text[:split_point])
            text = text[split_point:].lstrip()
        return chunks

    @classmethod
    def _split_html_message(cls, html_text: str) -> list[str]:
        if len(html_text) <= cls.MAX_MESSAGE_LENGTH:
            return [html_text]

        token_pattern = re.compile(r"(<[^>]+>)")
        void_tags = {"br", "hr"}
        stack: list[tuple[str, str]] = []
        chunks: list[str] = []
        current = ""

        def closing_tags() -> str:
            return "".join(f"</{tag}>" for tag, _ in reversed(stack))

        def opening_tags() -> str:
            return "".join(open_tag for _, open_tag in stack)

        def flush_current() -> None:
            nonlocal current
            if current:
                chunks.append(current + closing_tags())
                current = opening_tags()

        def append_text(text: str) -> None:
            nonlocal current
            while text:
                reserved = len(closing_tags())
                available = cls.MAX_MESSAGE_LENGTH - len(current) - reserved
                if available <= 0:
                    flush_current()
                    continue
                if len(text) <= available:
                    current += text
                    return
                current += text[:available]
                text = text[available:]
                flush_current()

        for token in token_pattern.split(html_text):
            if not token:
                continue
            if token.startswith("<") and token.endswith(">"):
                tag_match = re.match(r"</?([a-zA-Z0-9]+)", token)
                if not tag_match:
                    append_text(token)
                    continue
                tag_name = tag_match.group(1).lower()
                is_closing = token.startswith("</")
                is_self_closing = token.endswith("/>") or tag_name in void_tags
                if len(current) + len(token) + len(closing_tags()) > cls.MAX_MESSAGE_LENGTH:
                    flush_current()
                current += token
                if is_closing:
                    for index in range(len(stack) - 1, -1, -1):
                        if stack[index][0] == tag_name:
                            del stack[index:]
                            break
                elif not is_self_closing:
                    stack.append((tag_name, token))
                continue
            append_text(token)

        if current:
            chunks.append(current + closing_tags())
        return [chunk for chunk in chunks if chunk]

    @classmethod
    def _component_has_spoiler(cls, item: Any) -> bool:
        for attr_name in ("spoiler", "has_spoiler", "is_spoiler"):
            value = getattr(item, attr_name, None)
            if value is not None:
                return bool(value)

        meta = getattr(item, cls.META_ATTR, None)
        if isinstance(meta, dict):
            for key in ("spoiler", "has_spoiler", "is_spoiler"):
                if key in meta:
                    return bool(meta[key])

        extra = getattr(item, "extra", None)
        if isinstance(extra, dict):
            for key in ("spoiler", "has_spoiler", "is_spoiler"):
                if key in extra:
                    return bool(extra[key])

        return False

    def _pack_text_chunks(
        self, text_parts: list[tuple[str, bool]]
    ) -> list[list[tuple[str, bool]]]:
        packed: list[list[tuple[str, bool]]] = []
        current: list[tuple[str, bool]] = []
        current_length = 0

        def flush_current():
            nonlocal current
            nonlocal current_length
            if current:
                packed.append(current)
                current = []
                current_length = 0

        for part, is_html in text_parts:
            if not part:
                continue
            if is_html and len(part) > self.MAX_MESSAGE_LENGTH:
                flush_current()
                packed.extend(
                    [[(chunk, True)] for chunk in self._split_html_message(part)]
                )
                continue
            if not is_html and len(part) > self.MAX_MESSAGE_LENGTH:
                flush_current()
                packed.extend([[(chunk, False)] for chunk in self._split_message(part)])
                continue
            if current_length + len(part) <= self.MAX_MESSAGE_LENGTH:
                current.append((part, is_html))
                current_length += len(part)
            else:
                flush_current()
                current = [(part, is_html)]
                current_length = len(part)
        flush_current()
        return packed

    @staticmethod
    def _render_text_chunk(text_parts: list[tuple[str, bool]]) -> str:
        return "".join(
            part if is_html else html.escape(part)
            for part, is_html in text_parts
        )

    @classmethod
    def _looks_like_markdown(cls, text: str) -> bool:
        return any(pattern.search(text) for pattern in cls.MARKDOWN_HINT_PATTERNS)

    @staticmethod
    def _render_table(node) -> str:
        rows: list[list[str]] = []
        for tr in node.find_all("tr"):
            cells = [cell.get_text(" ", strip=True) for cell in tr.find_all(["th", "td"])]
            if cells:
                rows.append(cells)
        if not rows:
            return ""

        column_count = max(len(row) for row in rows)
        normalized_rows = [row + [""] * (column_count - len(row)) for row in rows]
        widths = [
            max(len(row[index]) for row in normalized_rows)
            for index in range(column_count)
        ]

        rendered_rows: list[str] = []
        for index, row in enumerate(normalized_rows):
            rendered_rows.append(
                " | ".join(cell.ljust(widths[cell_index]) for cell_index, cell in enumerate(row))
            )
            if index == 0 and len(normalized_rows) > 1:
                rendered_rows.append(
                    "-+-".join("-" * width for width in widths)
                )
        table_text = "\n".join(rendered_rows).rstrip()
        return f"<pre><code>{html.escape(table_text)}</code></pre>\n"

    @classmethod
    def _format_markdown_for_telethon_html(cls, text: str) -> str:
        raw_html = markdown.markdown(
            text,
            extensions=["fenced_code", "tables"],
        )
        soup = BeautifulSoup(raw_html, "html.parser")
        block_container_tags = {"ul", "ol", "blockquote"}

        def should_skip_whitespace_text(node) -> bool:
            return (
                getattr(node.parent, "name", None) in block_container_tags
                and not str(node).strip()
            )

        def is_list_item_paragraph(node) -> bool:
            return getattr(node.parent, "name", None) == "li"

        def convert(node) -> str:
            if node.name is None:
                if should_skip_whitespace_text(node):
                    return ""
                return html.escape(str(node))

            tag = node.name
            if tag == "pre":
                code_node = node.find("code")
                code_text = html.escape(node.get_text())
                language = ""
                if code_node:
                    for css_class in code_node.get("class", []):
                        if css_class.startswith("language-"):
                            language = css_class[len("language-") :]
                            break
                inner_tag = (
                    f'<code class="{html.escape(language)}">' if language else "<code>"
                )
                return f"<pre>{inner_tag}{code_text}</code></pre>"
            if tag == "table":
                return cls._render_table(node)

            inner = "".join(convert(child) for child in node.children)

            if tag in ("b", "strong"):
                return f"<b>{inner}</b>"
            if tag in ("i", "em"):
                return f"<i>{inner}</i>"
            if tag in ("s", "del", "strike"):
                return f"<s>{inner}</s>"
            if tag == "u":
                return f"<u>{inner}</u>"
            if tag == "code":
                return f"<code>{inner}</code>"
            if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
                return f"<b>{inner}</b>\n"
            if tag == "p":
                if is_list_item_paragraph(node):
                    return inner
                return f"{inner}\n"
            if tag == "br":
                return "\n"
            if tag == "hr":
                return "\n------\n"
            if tag == "a":
                href = html.escape(node.get("href", ""))
                return f'<a href="{href}">{inner}</a>'
            if tag in ("ul", "ol"):
                return inner
            if tag == "li":
                return f"• {inner.strip()}\n"
            if tag == "blockquote":
                return f"<blockquote>{inner.strip()}</blockquote>\n"
            return inner

        result = "".join(convert(child) for child in soup.children)
        result = re.sub(r"\n{3,}", "\n\n", result)
        return result.strip()

    async def _send_text_with_action(
        self,
        text: str | list[tuple[str, bool]],
        reply_to: int | None,
        *,
        send_typing_action: bool = True,
    ):
        if send_typing_action:
            await self.send_typing()
        effective_reply_to = self._effective_reply_to(reply_to)
        if isinstance(text, list):
            formatted_text = self._render_text_chunk(text)
            if any(is_html for _, is_html in text):
                return await self._send_text_request(
                    formatted_text,
                    parse_mode="html",
                    reply_to=reply_to,
                    link_preview=False,
                )
            text = "".join(part for part, _ in text)
        if not self._looks_like_markdown(text):
            return await self._send_text_request(
                text,
                parse_mode=None,
                reply_to=reply_to,
                link_preview=False,
            )
        try:
            formatted_text = self._format_markdown_for_telethon_html(text)
            html_chunks = self._split_html_message(formatted_text)
            result = None
            for html_chunk in html_chunks:
                result = await self._send_text_request(
                    html_chunk,
                    parse_mode="html",
                    reply_to=reply_to,
                    link_preview=False,
                )
            return result
        except Exception as e:
            context = self._message_log_context(effective_reply_to)
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
        return await self._send_text_request(
            text,
            parse_mode=None,
            reply_to=reply_to,
            link_preview=False,
        )

    async def react(self, emoji: str) -> None:
        raw_message = getattr(self.message_obj, "raw_message", None)
        react_method = getattr(raw_message, "react", None)
        if callable(react_method):
            try:
                await react_method(emoji)
                return
            except Exception as e:
                context = self._message_log_context()
                logger.warning(
                    "[Telethon] Native reaction failed, trying MTProto fallback: "
                    "chat_id=%s msg_id=%s sender_id=%s emoji=%s error=%s",
                    context["chat_id"],
                    context["msg_id"],
                    context["sender_id"],
                    emoji,
                    e,
                )

        message_id = getattr(self.message_obj, "message_id", None)
        try:
            await self.client(
                functions.messages.SendReactionRequest(
                    peer=self.peer,
                    msg_id=int(message_id),
                    reaction=[types.ReactionEmoji(emoticon=emoji)],
                )
            )
            return
        except Exception as e:
            context = self._message_log_context()
            logger.warning(
                "[Telethon] MTProto reaction failed: chat_id=%s msg_id=%s sender_id=%s emoji=%s error=%s",
                context["chat_id"],
                context["msg_id"],
                context["sender_id"],
                emoji,
                e,
            )

        logger.warning("[Telethon] Current message object does not support native reactions; skipped pre-reaction emoji")
