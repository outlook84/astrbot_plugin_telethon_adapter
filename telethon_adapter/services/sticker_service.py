from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
import re
from typing import Any

from astrbot.api import logger
from PIL import Image
from PIL.Image import Resampling
from telethon import functions, types, utils
from telethon.errors.rpcerrorlist import StickersetInvalidError

from ..i18n import t

DEFAULT_STICKER_EMOJI = "\U0001F5BC"
MAX_STICKER_PACK_NAME_LENGTH = 64
STICKER_PACK_NAME_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")


@dataclass(slots=True)
class StickerCommandPayload:
    text: str
    link_preview: bool = False


class TelethonStickerService:
    def __init__(self, kv_store: Any) -> None:
        self._kv_store = kv_store

    @staticmethod
    def supports_event(event: Any) -> bool:
        client = getattr(event, "client", None)
        raw_message = getattr(getattr(event, "message_obj", None), "raw_message", None)
        return client is not None and raw_message is not None

    async def handle_command(self, event: Any, arg1: str = "", arg2: str = "") -> StickerCommandPayload:
        normalized_arg1 = str(arg1 or "").strip()
        normalized_arg2 = str(arg2 or "").strip()

        reply_message = await self._get_reply_message(event)
        if reply_message is None:
            if normalized_arg2:
                raise ValueError(t(event, "sticker.too_many_args"))
            if normalized_arg1:
                pack_name = self._validate_pack_name(event, normalized_arg1)
                storage_key = self._build_storage_key(event)
                await self._kv_store.put_kv_data(storage_key, pack_name)
                return StickerCommandPayload(
                    text=t(event, "sticker.default_pack_set", pack_name=pack_name),
                )
            return await self._build_usage_payload(event)

        if normalized_arg2:
            pack_name = self._validate_pack_name(event, normalized_arg1)
            emoji = normalized_arg2
        else:
            stored_pack_name = await self._load_pack_name(event)
            if normalized_arg1 and self._looks_like_pack_name(normalized_arg1):
                pack_name = self._validate_pack_name(event, normalized_arg1)
                emoji = ""
            else:
                pack_name = stored_pack_name
                emoji = normalized_arg1

            if not pack_name:
                raise ValueError(t(event, "sticker.default_pack_missing"))

        return await self._add_reply_media_to_pack(
            event,
            reply_message,
            pack_name,
            emoji=emoji,
        )

    async def _build_usage_payload(self, event: Any) -> StickerCommandPayload:
        pack_name = await self._load_pack_name(event)
        if pack_name:
            return StickerCommandPayload(
                text=t(event, "sticker.usage_with_default", pack_name=pack_name),
                link_preview=False,
            )
        return StickerCommandPayload(
            text=t(event, "sticker.usage_without_default"),
            link_preview=False,
        )

    async def _add_reply_media_to_pack(
        self,
        event: Any,
        reply_message: Any,
        pack_name: str,
        *,
        emoji: str = "",
    ) -> StickerCommandPayload:
        client = getattr(event, "client", None)
        if client is None:
            raise ValueError(t(event, "sticker.client_missing"))

        detected_emoji = await self._resolve_sticker_emoji(reply_message)
        final_emoji = str(emoji or detected_emoji or DEFAULT_STICKER_EMOJI).strip() or DEFAULT_STICKER_EMOJI

        sticker_file, mime_type = await self._prepare_sticker_file(reply_message)
        if sticker_file is None or not mime_type:
            raise ValueError(t(event, "sticker.unsupported_reply_media"))

        try:
            if mime_type == "application/x-tgsticker":
                upload_name = "sticker.tgs"
            elif mime_type == "video/webm":
                upload_name = "sticker.webm"
            else:
                upload_name = "sticker.webp"
            sticker_file.name = upload_name
            uploaded = await client.upload_file(sticker_file)
            upload_result = await client(
                functions.messages.UploadMediaRequest(
                    peer=types.InputPeerSelf(),
                    media=types.InputMediaUploadedDocument(
                        file=uploaded,
                        mime_type=mime_type,
                        attributes=[],
                    ),
                )
            )
            uploaded_document = getattr(upload_result, "document", None)
            if uploaded_document is None:
                raise TypeError("Upload result is not a valid Document")

            sticker_item = types.InputStickerSetItem(
                document=utils.get_input_document(uploaded_document),
                emoji=final_emoji,
            )
            created = await self._add_or_create_sticker_set(
                client,
                pack_name,
                sticker_item,
            )
        except ValueError:
            raise
        except Exception as exc:
            logger.exception("[Telethon] Sticker command processing failed: pack_name=%s", pack_name)
            raise ValueError(t(event, "sticker.add_failed", error=exc)) from exc

        action_text = (
            t(event, "sticker.created_and_added")
            if created
            else t(event, "sticker.added")
        )
        return StickerCommandPayload(
            text=t(
                event,
                "sticker.result",
                action=action_text,
                emoji=final_emoji,
                pack_name=pack_name,
            ),
            link_preview=False,
        )

    async def _add_or_create_sticker_set(self, client: Any, pack_name: str, sticker_item: Any) -> bool:
        try:
            await client(
                functions.stickers.AddStickerToSetRequest(
                    stickerset=types.InputStickerSetShortName(short_name=pack_name),
                    sticker=sticker_item,
                )
            )
            return False
        except StickersetInvalidError:
            pass
        except Exception as exc:
            if "STICKERSET_INVALID" not in str(exc):
                raise

        try:
            await client(
                functions.stickers.CreateStickerSetRequest(
                    user_id=types.InputUserSelf(),
                    title=pack_name,
                    short_name=pack_name,
                    stickers=[sticker_item],
                )
            )
            return True
        except Exception as exc:
            if "SHORT_NAME_OCCUPIED" not in str(exc) and "already exists" not in str(exc):
                raise
            await client(
                functions.stickers.AddStickerToSetRequest(
                    stickerset=types.InputStickerSetShortName(short_name=pack_name),
                    sticker=sticker_item,
                )
            )
            return False

    async def _prepare_sticker_file(self, reply_message: Any) -> tuple[BytesIO | None, str | None]:
        if getattr(reply_message, "photo", None):
            raw = await reply_message.download_media(file=BytesIO())
            return await self._normalize_sticker_image_async(raw), "image/webp"

        document = getattr(reply_message, "document", None)
        if document is None:
            return None, None

        mime_type = str(getattr(document, "mime_type", "") or "")
        is_sticker = self._is_sticker_message(reply_message)
        is_image = mime_type.startswith("image/")

        if is_sticker and mime_type == "application/x-tgsticker":
            raw = await reply_message.download_media(file=BytesIO())
            raw.seek(0)
            return raw, mime_type

        if is_sticker and mime_type == "image/webp":
            raw = await reply_message.download_media(file=BytesIO())
            return await self._normalize_sticker_image_async(raw), mime_type

        if is_sticker and mime_type == "video/webm":
            raw = await reply_message.download_media(file=BytesIO())
            raw.seek(0)
            return raw, mime_type

        if is_image:
            raw = await reply_message.download_media(file=BytesIO())
            return await self._normalize_sticker_image_async(raw), "image/webp"

        return None, None

    async def _resolve_sticker_emoji(self, reply_message: Any) -> str:
        attributes = self._get_sticker_attributes(reply_message)
        for attr in attributes:
            alt = getattr(attr, "alt", None)
            if alt:
                return str(alt)
        return ""

    @staticmethod
    def _get_sticker_attributes(reply_message: Any) -> list[Any]:
        document = getattr(reply_message, "document", None)
        if document is not None:
            attributes = list(getattr(document, "attributes", None) or [])
            if attributes:
                return attributes
        sticker = getattr(reply_message, "sticker", None)
        return list(getattr(sticker, "attributes", None) or [])

    @classmethod
    def _is_sticker_message(cls, reply_message: Any) -> bool:
        attr_types = tuple(
            item
            for item in (getattr(types, "DocumentAttributeSticker", None),)
            if isinstance(item, type)
        )
        for attr in cls._get_sticker_attributes(reply_message):
            if attr_types and isinstance(attr, attr_types):
                return True
            if type(attr).__name__ == "DocumentAttributeSticker":
                return True
            if hasattr(attr, "alt") or hasattr(attr, "stickerset"):
                return True
        return False

    async def _get_reply_message(self, event: Any) -> Any | None:
        raw_message = getattr(getattr(event, "message_obj", None), "raw_message", None)
        get_reply_message = getattr(raw_message, "get_reply_message", None)
        if not callable(get_reply_message):
            return None
        try:
            return await get_reply_message()
        except Exception:
            logger.debug("[Telethon] Failed to fetch replied message for tg sticker", exc_info=True)
            return None

    async def _resolve_account_key(self, event: Any) -> str:
        message_obj = getattr(event, "message_obj", None)
        self_id = str(getattr(message_obj, "self_id", "") or "").strip()
        if self_id:
            return self_id

        client = getattr(event, "client", None)
        if client is None:
            return "default"
        try:
            me = await client.get_me()
        except Exception:
            return "default"
        me_id = getattr(me, "id", None)
        return str(me_id or "default")

    async def _load_pack_name(self, event: Any) -> str:
        storage_key = self._build_storage_key(event)
        pack_name = await self._kv_store.get_kv_data(storage_key, "")
        return str(pack_name or "").strip()

    def _build_storage_key(self, event: Any) -> str:
        platform_meta = getattr(event, "platform_meta", None)
        adapter_id = str(getattr(platform_meta, "id", "") or "").strip() or "telethon_userbot"
        return f"sticker_pack_name:{adapter_id}"

    @staticmethod
    def _looks_like_pack_name(value: str) -> bool:
        return bool(STICKER_PACK_NAME_PATTERN.fullmatch(str(value or "").strip()))

    @staticmethod
    def _validate_pack_name(event_or_pack_name: Any, pack_name: str | None = None) -> str:
        event = event_or_pack_name if pack_name is not None else None
        raw_pack_name = event_or_pack_name if pack_name is None else pack_name
        normalized = str(raw_pack_name or "").strip()
        if not normalized:
            raise ValueError(t(event, "sticker.pack_name_empty"))
        if len(normalized) > MAX_STICKER_PACK_NAME_LENGTH:
            raise ValueError(
                t(event, "sticker.pack_name_too_long", limit=MAX_STICKER_PACK_NAME_LENGTH)
            )
        if not STICKER_PACK_NAME_PATTERN.fullmatch(normalized):
            raise ValueError(t(event, "sticker.pack_name_invalid_chars"))
        if "__" in normalized:
            raise ValueError(t(event, "sticker.pack_name_double_underscore"))
        return normalized

    @staticmethod
    def _normalize_sticker_image_sync(input_bytes: BytesIO) -> BytesIO:
        input_bytes.seek(0)
        image = Image.open(input_bytes).convert("RGBA")
        max_side = 512
        width, height = image.size
        if (width == max_side and height <= max_side) or (height == max_side and width <= max_side):
            resized = image
        else:
            scale = max_side / max(width, height)
            new_width = int(round(width * scale))
            new_height = int(round(height * scale))
            resized = image.resize((new_width, new_height), Resampling.LANCZOS)
        output = BytesIO()
        resized.save(output, format="WEBP", lossless=True, quality=100, method=5)
        output.seek(0)
        return output

    async def _normalize_sticker_image_async(self, input_bytes: BytesIO) -> BytesIO:
        return self._normalize_sticker_image_sync(input_bytes)
