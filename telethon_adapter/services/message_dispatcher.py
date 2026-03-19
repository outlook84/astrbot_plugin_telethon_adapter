from __future__ import annotations

import importlib
from typing import Any

from astrbot.api import logger
try:
    from .contracts import TelethonDispatcherHost
except ImportError:
    from telethon_adapter.services.contracts import TelethonDispatcherHost


def _message_components() -> Any:
    return importlib.import_module("astrbot.api.message_components")


def _telethon_types() -> Any:
    return importlib.import_module("telethon.types")


class TelethonMessageDispatcher:
    async def send(self, event: TelethonDispatcherHost, message: Any) -> None:
        components = _message_components()
        types = _telethon_types()
        if await self.try_send_local_media_group(event, message):
            await event._send_base_message(message)
            return

        reply_to: int | None = None
        text_parts: list[tuple[str, bool]] = []

        for item in message.chain:
            if isinstance(item, components.Reply):
                try:
                    reply_to = int(item.id)
                except (TypeError, ValueError):
                    logger.warning(f"[Telethon] Failed to parse reply ID: {item.id}")
                continue

            if isinstance(item, components.At):
                at_html = event._format_at_html(item)
                if at_html:
                    text_parts.append((at_html, True))
                else:
                    text_parts.append((event._format_at_text(item), False))
                continue

            if isinstance(item, components.Plain):
                text_parts.append((item.text, False))
                continue

            if isinstance(item, components.Location):
                text_parts.append(
                    (
                        f"{event._label('message.media.location')} "
                        f"{item.lat},{item.lon} {item.title or ''}".strip(),
                        False,
                    )
                )
                continue

            reply_to = await event._flush_text(text_parts, reply_to)

            if isinstance(item, components.Image):
                file_path = await item.convert_to_file_path()
                is_gif = event._is_gif_path(file_path)
                reply_to = await event._send_media(
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
                    spoiler=event._component_has_spoiler(item),
                )
                continue

            if isinstance(item, components.Video):
                file_path = await item.convert_to_file_path()
                reply_to = await event._send_media(
                    file_path,
                    None,
                    reply_to,
                    "video",
                    types.SendMessageUploadVideoAction(progress=0),
                    spoiler=event._component_has_spoiler(item),
                )
                continue

            if isinstance(item, components.Record):
                file_path = await item.convert_to_file_path()
                reply_to = await event._send_media(
                    file_path,
                    item.text,
                    reply_to,
                    "audio",
                    types.SendMessageUploadAudioAction(progress=0),
                )
                continue

            if isinstance(item, components.File):
                file_path = await item.get_file()
                reply_to = await event._send_media(
                    file_path,
                    item.name,
                    reply_to,
                    "document",
                    types.SendMessageUploadDocumentAction(progress=0),
                )
                continue

            logger.warning(
                f"[Telethon] Unsupported message segment type: {getattr(item, 'type', type(item).__name__)}"
            )

        await event._flush_text(text_parts, reply_to)
        await event._send_base_message(message)

    async def try_send_local_media_group(self, event: TelethonDispatcherHost, message: Any) -> bool:
        components = _message_components()
        types = _telethon_types()
        meta = getattr(message, event.META_ATTR, None)
        if not isinstance(meta, dict) or meta.get("intent") != event.MEDIA_GROUP_INTENT:
            return False

        reply_to: int | None = None
        caption_parts: list[str] = []
        media_items: list[tuple[str, bool, bool]] = []
        action_name = "photo"
        has_spoiler = False

        for item in message.chain:
            if isinstance(item, components.Reply):
                try:
                    reply_to = int(item.id)
                except (TypeError, ValueError):
                    logger.warning(f"[Telethon] Failed to parse media-group reply ID: {item.id}")
                    return False
                continue
            if isinstance(item, components.Plain):
                caption_parts.append(item.text)
                continue
            if isinstance(item, components.Image):
                file_path = await item.convert_to_file_path()
                if event._is_gif_path(file_path):
                    return False
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
            async with event._chat_action_scope(action_name, fallback_action):
                if not event._should_use_low_level_media_group_request(
                    has_spoiler=has_spoiler
                ) and not any(
                    event._request_sender().should_use_fast_upload(event.client, path)
                    for path, _spoiler, _is_video in media_items
                ):
                    await event.client.send_file(
                        event.peer,
                        file=[path for path, _spoiler, _is_video in media_items],
                        caption=caption,
                        reply_to=event._build_reply_to(reply_to),
                    )
                else:
                    await event._send_local_media_group_request(
                        media_items,
                        caption=caption,
                        reply_to=reply_to,
                    )
        except Exception:
            context = event._message_log_context(reply_to)
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
