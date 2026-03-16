from __future__ import annotations

import re
from typing import Any

from astrbot.api import logger
from astrbot.api.message_components import At, Location, Plain, Record, Reply
from astrbot.api.platform import AstrBotMessage, MessageMember, MessageType
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


class TelethonMessageConverter:
    def __init__(self, adapter: Any) -> None:
        self.adapter = adapter

    async def convert_message(
        self,
        event: Any,
        include_reply: bool = True,
    ) -> AstrBotMessage:
        is_private = bool(getattr(event, "is_private", False))
        message = getattr(event, "message", None)
        peer = getattr(message, "peer_id", None)
        if not is_private:
            if type(peer).__name__ == "PeerUser":
                is_private = True
        if getattr(self.adapter, "debug_logging", False):
            logger.info(
                "[Telethon][Debug] convert_message: chat_id=%s sender_id=%s peer_type=%s "
                "is_private_event=%s is_private_final=%s raw_text=%r",
                getattr(event, "chat_id", None),
                getattr(event, "sender_id", None),
                type(peer).__name__ if peer is not None else None,
                getattr(event, "is_private", None),
                is_private,
                getattr(message, "raw_text", ""),
            )
        return await self.convert_telethon_message(
            msg=event.message,
            sender=await event.get_sender(),
            chat_id=str(event.chat_id),
            is_private=is_private,
            include_reply=include_reply,
            strip_trigger_prefix=True,
        )

    async def convert_telethon_message(
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
                x
                for x in [getattr(sender, "first_name", ""), getattr(sender, "last_name", "")]
                if x
            ).strip()
            or getattr(sender, "title", None)
            or str(getattr(sender, "id", "unknown"))
        )

        message = AstrBotMessage()
        message.session_id = chat_id
        message.message_id = str(msg.id)
        message.self_id = self.adapter.self_username or self.adapter.self_id
        message.raw_message = msg
        message.sender = MessageMember(
            user_id=str(getattr(sender, "id", "0")),
            nickname=sender_name,
        )
        message.message = []
        if is_private:
            message.type = MessageType.FRIEND_MESSAGE
        else:
            message.type = MessageType.GROUP_MESSAGE
            message.group_id = chat_id

        preserve_group_mention_wakeup = not is_private and not self.adapter.trigger_prefix
        if preserve_group_mention_wakeup:
            message.message_str = msg.raw_text or ""
        else:
            message.message_str = self.strip_self_mentions_from_text(
                msg.raw_text or "",
                getattr(msg, "entities", None),
            )

        inject_self_at = False
        if (
            strip_trigger_prefix
            and self.adapter.trigger_prefix
            and message.message_str.startswith(self.adapter.trigger_prefix)
        ):
            message.message_str = message.message_str[
                len(self.adapter.trigger_prefix) :
            ].lstrip()
            inject_self_at = not is_private

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
            except Exception as e:
                logger.warning(
                    "[Telethon] 拉取引用消息失败，退化为空引用: chat_id=%s message_id=%s reply_to=%s error=%s",
                    chat_id,
                    getattr(msg, "id", None),
                    reply_id,
                    e,
                )
            else:
                if reply_msg:
                    try:
                        reply_sender = await reply_msg.get_sender()
                        reply_chat_id = str(getattr(reply_msg, "chat_id", chat_id))
                        reply_is_private = bool(getattr(reply_msg, "is_private", is_private))
                        reply_abm = await self.convert_telethon_message(
                            msg=reply_msg,
                            sender=reply_sender,
                            chat_id=reply_chat_id,
                            is_private=reply_is_private,
                            include_reply=False,
                            strip_trigger_prefix=False,
                        )
                    except Exception:
                        logger.exception(
                            "[Telethon] 引用消息结构转换失败: chat_id=%s message_id=%s reply_to=%s",
                            chat_id,
                            getattr(msg, "id", None),
                            reply_id,
                        )
                    else:
                        reply_component = Reply(
                            id=reply_abm.message_id,
                            chain=reply_abm.message,
                            sender_id=reply_abm.sender.user_id,
                            sender_nickname=reply_abm.sender.nickname,
                            time=int(
                                getattr(
                                    getattr(reply_msg, "date", None),
                                    "timestamp",
                                    lambda: 0,
                                )()
                            ),
                            message_str=reply_abm.message_str,
                            text=reply_abm.message_str,
                            qq=reply_abm.sender.user_id,
                        )
            message.message.append(reply_component)

        text_components = self.parse_text_components(
            msg.raw_text or "",
            getattr(msg, "entities", None),
            preserve_self_mentions=preserve_group_mention_wakeup,
        )
        if strip_trigger_prefix and self.adapter.trigger_prefix:
            text_components = self.strip_prefix_from_components(
                text_components,
                self.adapter.trigger_prefix,
            )
        if inject_self_at:
            text_components = [
                At(qq=message.self_id, name=message.self_id),
                *text_components,
            ]
        message.message.extend(text_components)

        if msg.media:
            media_components = await self.parse_media_components(msg)
            message.message.extend(media_components)
            if not message.message_str and media_components:
                message.message_str = "[媒体消息]"

        if getattr(self.adapter, "debug_logging", False):
            logger.info(
                "[Telethon][Debug] convert_result: chat_id=%s type=%s session_id=%s "
                "message_str=%r component_types=%s",
                chat_id,
                getattr(message, "type", None),
                getattr(message, "session_id", None),
                getattr(message, "message_str", ""),
                [type(component).__name__ for component in message.message],
            )

        return message

    @staticmethod
    def strip_prefix_from_components(
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

    def strip_self_mentions_from_text(
        self,
        text: str,
        entities: list[Any] | None,
    ) -> str:
        if not text or not entities:
            return text

        spans_to_remove: list[tuple[int, int]] = []
        for entity in entities:
            offset = int(getattr(entity, "offset", 0))
            length = int(getattr(entity, "length", 0))
            if length <= 0:
                continue
            py_offset, py_end = self.utf16_span_to_py_span(text, max(0, offset), length)
            if py_end <= py_offset:
                continue
            entity_text = text[py_offset:py_end]
            if self.is_self_mention(entity, entity_text):
                spans_to_remove.append((py_offset, py_end))

        if not spans_to_remove:
            return text

        parts: list[str] = []
        cursor = 0
        for start, end in sorted(spans_to_remove):
            if start < cursor:
                continue
            if start > cursor:
                parts.append(text[cursor:start])
            cursor = end
        if cursor < len(text):
            parts.append(text[cursor:])
        return "".join(parts)

    def is_self_mention(self, entity: Any, entity_text: str) -> bool:
        username = str(getattr(self.adapter, "self_username", "") or "").strip().lower()
        self_id = str(getattr(self.adapter, "self_id", "") or "").strip()
        cleaned = entity_text.strip().lstrip("@").lower()

        if isinstance(entity, MessageEntityMention):
            return bool(username and cleaned == username)

        if isinstance(entity, MessageEntityMentionName):
            user_id = str(getattr(entity, "user_id", "") or "").strip()
            return bool(self_id and user_id == self_id)

        if isinstance(entity, MessageEntityTextUrl):
            url = str(getattr(entity, "url", "") or "")
            match = re.search(r"tg://user\?id=(\d+)", url)
            return bool(match and self_id and match.group(1) == self_id)

        return False

    def parse_text_components(
        self,
        text: str,
        entities: list[Any] | None,
        preserve_self_mentions: bool = False,
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
            py_offset, py_end = self.utf16_span_to_py_span(text, offset, length)
            end = min(len(text), py_end)
            offset = min(len(text), py_offset)
            if end <= cursor:
                continue
            if offset > cursor:
                components.append(Plain(text=text[cursor:offset]))

            entity_text = text[offset:end]
            if preserve_self_mentions and self.is_self_mention(entity, entity_text):
                components.append(Plain(text=entity_text))
                cursor = end
                continue
            mention = self.entity_to_at(entity, entity_text)
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
    def utf16_span_to_py_span(
        text: str,
        utf16_offset: int,
        utf16_length: int,
    ) -> tuple[int, int]:
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

    def entity_to_at(self, entity: Any, entity_text: str) -> At | None:
        cleaned = entity_text.strip()
        if isinstance(entity, MessageEntityMention):
            username = cleaned.lstrip("@")
            if username:
                return At(qq=username, name=username)
            return None

        if isinstance(entity, MessageEntityMentionName):
            display = cleaned.lstrip("@").strip()
            if display:
                return At(qq=display, name=display)
            return None

        if isinstance(entity, MessageEntityTextUrl):
            url = str(getattr(entity, "url", "") or "")
            match = re.search(r"tg://user\?id=(\d+)", url)
            if match:
                display = cleaned.lstrip("@").strip()
                if not display:
                    return None
                return At(qq=display, name=display)
        return None

    async def parse_media_components(self, msg: Any) -> list[Any]:
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

        if not self.adapter.download_incoming_media:
            return []

        components: list[Any] = []
        file_name = self.guess_media_name(msg)
        lazy_media = TelethonLazyMedia(
            msg=msg,
            temp_dir_getter=self.adapter._get_media_temp_dir,
            register_temp_file=self.adapter._register_temp_file,
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
    def guess_media_name(msg: Any) -> str:
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
