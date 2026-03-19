from __future__ import annotations

from dataclasses import dataclass, field
import importlib
from typing import Any

from astrbot.api import logger


def _message_components() -> Any:
    return importlib.import_module("astrbot.api.message_components")


def _telethon_types() -> Any:
    return importlib.import_module("telethon.types")


@dataclass(slots=True)
class TextAction:
    parts: list[tuple[str, bool]]


@dataclass(slots=True)
class MediaAction:
    path: str
    caption: str | None
    caption_parse_mode: str | None
    reply_to: int | None
    action_name: str
    fallback_action: Any
    mime_type: str | None = None
    attributes: list[Any] | None = None
    spoiler: bool = False


@dataclass(slots=True)
class MediaGroupAction:
    media_items: list[tuple[str, bool, bool]]
    caption: str | None
    caption_parse_mode: str | None
    reply_to: int | None
    action_name: str
    fallback_action: Any


@dataclass(slots=True)
class TelegramSendPlan:
    reply_to: int | None = None
    actions: list[TextAction | MediaAction] = field(default_factory=list)


@dataclass(slots=True)
class _TextBuffer:
    rich_parts: list[tuple[str, bool]] = field(default_factory=list)
    caption_parts: list[str] = field(default_factory=list)

    def append_plain(self, text: str) -> None:
        self.rich_parts.append((text, False))
        self.caption_parts.append(text)

    def append_rich(self, rich_text: str, fallback_text: str) -> None:
        self.rich_parts.append((rich_text, True))
        self.caption_parts.append(fallback_text)

    def has_content(self) -> bool:
        return bool(self.rich_parts)

    def to_text_action(self) -> TextAction:
        return TextAction(parts=list(self.rich_parts))

    def clear(self) -> None:
        self.rich_parts.clear()
        self.caption_parts.clear()


class TelethonMessagePlanner:
    CAPTION_LIMIT = 1024

    async def build(self, event: Any, message: Any) -> TelegramSendPlan:
        components = _message_components()
        types = _telethon_types()
        reply_to: int | None = None
        text_buffer = _TextBuffer()
        actions: list[TextAction | MediaAction] = []

        for item in message.chain:
            if isinstance(item, components.Reply):
                reply_to = self._parse_reply_to(item.id)
                continue

            if self._append_text_like_component(
                event,
                item,
                text_buffer,
                allow_html_at=True,
            ):
                continue

            if isinstance(item, components.Image):
                file_path = await item.convert_to_file_path()
                is_gif = event._is_gif_path(file_path)
                actions.extend(
                    self._build_media_action(
                        event,
                        text_buffer,
                        path=file_path,
                        reply_to=reply_to,
                        action_name="video" if is_gif else "photo",
                        fallback_action=(
                            types.SendMessageUploadVideoAction(progress=0)
                            if is_gif
                            else types.SendMessageUploadPhotoAction(progress=0)
                        ),
                        mime_type="image/gif" if is_gif else None,
                        attributes=[types.DocumentAttributeAnimated()] if is_gif else None,
                        spoiler=event._component_has_spoiler(item),
                    )
                )
                continue

            if isinstance(item, components.Video):
                file_path = await item.convert_to_file_path()
                actions.extend(
                    self._build_media_action(
                        event,
                        text_buffer,
                        path=file_path,
                        reply_to=reply_to,
                        action_name="video",
                        fallback_action=types.SendMessageUploadVideoAction(progress=0),
                        spoiler=event._component_has_spoiler(item),
                    )
                )
                continue

            if isinstance(item, components.Record):
                file_path = await item.convert_to_file_path()
                actions.extend(
                    self._build_media_action(
                        event,
                        text_buffer,
                        path=file_path,
                        reply_to=reply_to,
                        action_name="audio",
                        fallback_action=types.SendMessageUploadAudioAction(progress=0),
                        fallback_caption=getattr(item, "text", None),
                    )
                )
                continue

            if isinstance(item, components.File):
                file_path = await item.get_file()
                actions.extend(
                    self._build_media_action(
                        event,
                        text_buffer,
                        path=file_path,
                        reply_to=reply_to,
                        action_name="document",
                        fallback_action=types.SendMessageUploadDocumentAction(progress=0),
                        fallback_caption=getattr(item, "name", None),
                    )
                )
                continue

            if text_buffer.has_content():
                actions.append(text_buffer.to_text_action())
                text_buffer.clear()
            logger.warning(
                f"[Telethon] Unsupported message segment type: {getattr(item, 'type', type(item).__name__)}"
            )

        if text_buffer.has_content():
            actions.append(text_buffer.to_text_action())
            text_buffer.clear()

        return TelegramSendPlan(reply_to=reply_to, actions=actions)

    async def build_media_group_action(self, event: Any, message: Any) -> MediaGroupAction | None:
        components = _message_components()
        types = _telethon_types()
        meta = getattr(message, event.META_ATTR, None)
        if not isinstance(meta, dict) or meta.get("intent") != event.MEDIA_GROUP_INTENT:
            return None

        reply_to: int | None = None
        text_buffer = _TextBuffer()
        media_items: list[tuple[str, bool, bool]] = []
        action_name = "photo"
        has_spoiler = False

        for item in message.chain:
            if isinstance(item, components.Reply):
                reply_to = self._parse_reply_to(item.id)
                if reply_to is None:
                    logger.warning(f"[Telethon] Failed to parse media-group reply ID: {item.id}")
                    return None
                continue

            if media_items and self._is_text_like_component(components, item):
                return None

            if self._append_text_like_component(
                event,
                item,
                text_buffer,
                allow_html_at=True,
            ):
                continue

            if isinstance(item, components.Image):
                file_path = await item.convert_to_file_path()
                if event._is_gif_path(file_path):
                    return None
                item_spoiler = event._component_has_spoiler(item)
                has_spoiler = has_spoiler or item_spoiler
                media_items.append((file_path, item_spoiler, False))
                continue

            if isinstance(item, components.Video):
                file_path = await item.convert_to_file_path()
                item_spoiler = event._component_has_spoiler(item)
                has_spoiler = has_spoiler or item_spoiler
                action_name = "video"
                media_items.append((file_path, item_spoiler, True))
                continue

            return None

        if len(media_items) < 2:
            return None

        caption, caption_parse_mode = self._caption_from_buffer(event, text_buffer)
        if caption is None and text_buffer.caption_parts:
            return None

        if action_name == "photo":
            fallback_action = types.SendMessageUploadPhotoAction(progress=0)
        else:
            fallback_action = types.SendMessageUploadVideoAction(progress=0)

        return MediaGroupAction(
            media_items=media_items,
            caption=caption,
            caption_parse_mode=caption_parse_mode,
            reply_to=reply_to,
            action_name=action_name,
            fallback_action=fallback_action,
        )

    def _build_media_action(
        self,
        event: Any,
        text_buffer: _TextBuffer,
        *,
        path: str,
        reply_to: int | None,
        action_name: str,
        fallback_action: Any,
        mime_type: str | None = None,
        attributes: list[Any] | None = None,
        spoiler: bool = False,
        fallback_caption: str | None = None,
    ) -> list[TextAction | MediaAction]:
        actions: list[TextAction | MediaAction] = []
        caption, caption_parse_mode = self._caption_from_buffer(event, text_buffer)
        if caption is None and text_buffer.caption_parts:
            actions.append(text_buffer.to_text_action())
        text_buffer.clear()

        actions.append(
            MediaAction(
                path=path,
                caption=caption if caption is not None else fallback_caption,
                caption_parse_mode=caption_parse_mode if caption is not None else None,
                reply_to=reply_to,
                action_name=action_name,
                fallback_action=fallback_action,
                mime_type=mime_type,
                attributes=attributes,
                spoiler=spoiler,
            )
        )
        return actions

    def _caption_from_buffer(
        self,
        event: Any,
        text_buffer: _TextBuffer,
    ) -> tuple[str | None, str | None]:
        caption = "".join(text_buffer.caption_parts).strip()
        if not caption:
            return None, None
        if len(caption) > self.CAPTION_LIMIT:
            return None, None
        if any(is_html for _part, is_html in text_buffer.rich_parts):
            return event._render_text_chunk(text_buffer.rich_parts), "html"
        if event._looks_like_markdown(caption):
            return caption, "markdown"
        return caption, None

    def _append_text_like_component(
        self,
        event: Any,
        item: Any,
        text_buffer: _TextBuffer,
        *,
        allow_html_at: bool,
    ) -> bool:
        components = _message_components()
        if isinstance(item, components.At):
            at_text = event._format_at_text(item)
            if allow_html_at:
                at_html = event._format_at_html(item)
                if at_html:
                    text_buffer.append_rich(at_html, at_text)
                    return True
            text_buffer.append_plain(at_text)
            return True

        if isinstance(item, components.Plain):
            text_buffer.append_plain(item.text)
            return True

        if isinstance(item, components.Location):
            location_text = (
                f"{event._label('message.media.location')} "
                f"{item.lat},{item.lon} {item.title or ''}".strip()
            )
            text_buffer.append_plain(location_text)
            return True

        return False

    @staticmethod
    def _is_text_like_component(components: Any, item: Any) -> bool:
        return isinstance(item, (components.At, components.Plain, components.Location))

    @staticmethod
    def _parse_reply_to(reply_id: Any) -> int | None:
        try:
            return int(reply_id)
        except (TypeError, ValueError):
            logger.warning(f"[Telethon] Failed to parse reply ID: {reply_id}")
            return None
