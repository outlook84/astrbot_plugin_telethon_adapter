from __future__ import annotations

from dataclasses import dataclass
import importlib
from typing import Any, Awaitable, Callable

from ..services.message_planner import MediaAction, MediaGroupAction

BuildInputMedia = Callable[..., Awaitable[tuple[Any, Any, bool]]]
ShouldUseFastUpload = Callable[[Any, str], bool]


def _telethon_functions() -> Any:
    return importlib.import_module("telethon.functions")


def _telethon_types() -> Any:
    return importlib.import_module("telethon.types")


def _telethon_utils() -> Any:
    return importlib.import_module("telethon.utils")


def _input_reply_to_message_type() -> type[Any]:
    types_module = _telethon_types()
    reply_type = getattr(types_module, "InputReplyToMessage", None)
    if reply_type is not None:
        return reply_type

    try:
        tl_types = importlib.import_module("telethon.tl.types")
    except ImportError:
        tl_types = None
    if tl_types is not None:
        reply_type = getattr(tl_types, "InputReplyToMessage", None)
        if reply_type is not None:
            return reply_type

    class InputReplyToMessage:
        def __init__(self, reply_to_msg_id: int, top_msg_id: int | None = None):
            self.reply_to_msg_id = reply_to_msg_id
            self.top_msg_id = top_msg_id

    return InputReplyToMessage


def _input_single_media_type() -> type[Any]:
    types_module = _telethon_types()
    input_single_media = getattr(types_module, "InputSingleMedia", None)
    if input_single_media is not None:
        return input_single_media

    class InputSingleMedia:
        def __init__(self, media: Any, message: str = "", entities: Any = None, **kwargs):
            self.media = media
            self.message = message
            self.entities = entities
            self.kwargs = kwargs

    return InputSingleMedia


def _send_multi_media_request_type() -> type[Any]:
    messages_module = _telethon_functions().messages
    request_type = getattr(messages_module, "SendMultiMediaRequest", None)
    if request_type is not None:
        return request_type

    class SendMultiMediaRequest:
        def __init__(self, peer: Any, multi_media: list[Any], reply_to: Any = None, **kwargs):
            self.peer = peer
            self.multi_media = multi_media
            self.reply_to = reply_to
            self.kwargs = kwargs

    return SendMultiMediaRequest


def _upload_media_request_type() -> type[Any]:
    messages_module = _telethon_functions().messages
    request_type = getattr(messages_module, "UploadMediaRequest", None)
    if request_type is not None:
        return request_type

    class UploadMediaRequest:
        def __init__(self, peer: Any, media: Any, **kwargs):
            self.peer = peer
            self.media = media
            self.kwargs = kwargs

    return UploadMediaRequest


@dataclass(slots=True)
class TelethonRequestSender:
    client: Any
    peer: Any
    thread_id: int | None = None
    build_input_media: BuildInputMedia | None = None
    should_use_fast_upload: ShouldUseFastUpload | None = None

    @staticmethod
    def normalize_reply_to_message_id(reply_to_msg_id: Any) -> int | None:
        try:
            return int(reply_to_msg_id) if reply_to_msg_id is not None else None
        except (TypeError, ValueError):
            return None

    def build_reply_to(self, reply_to_msg_id: Any | None) -> Any | None:
        normalized_reply_to = self.normalize_reply_to_message_id(reply_to_msg_id)
        if self.thread_id is None:
            return normalized_reply_to

        effective_reply_to = (
            normalized_reply_to if normalized_reply_to is not None else self.thread_id
        )
        return _input_reply_to_message_type()(
            reply_to_msg_id=effective_reply_to,
            top_msg_id=self.thread_id,
        )

    @staticmethod
    def normalize_low_level_reply_to(reply_to: Any | None) -> Any | None:
        if reply_to is None or hasattr(reply_to, "reply_to_msg_id"):
            return reply_to
        return _input_reply_to_message_type()(reply_to_msg_id=int(reply_to))

    async def resolve_input_peer(self) -> Any:
        get_input_entity = getattr(self.client, "get_input_entity", None)
        if callable(get_input_entity):
            return await get_input_entity(self.peer)
        return self.peer

    async def parse_formatting_entities(
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

    async def execute_request(self, request: Any, entity: Any) -> Any:
        result = await self.client(request)
        get_response_message = getattr(self.client, "_get_response_message", None)
        if callable(get_response_message):
            return get_response_message(request, result, entity)
        return result

    def should_use_low_level_request(self, reply_to: Any | None) -> bool:
        return hasattr(reply_to, "reply_to_msg_id")

    async def send_text(
        self,
        text: str,
        *,
        parse_mode: str | None,
        reply_to_msg_id: Any | None,
        link_preview: bool,
        force_low_level: bool = False,
    ) -> Any:
        reply_to = self.build_reply_to(reply_to_msg_id)
        if not force_low_level and not self.should_use_low_level_request(reply_to):
            payload = {
                "reply_to": reply_to,
                "link_preview": link_preview,
            }
            if parse_mode is not None:
                payload["parse_mode"] = parse_mode
            return await self.client.send_message(self.peer, text, **payload)

        entity = await self.resolve_input_peer()
        message, entities = await self.parse_formatting_entities(text, parse_mode)
        request = _telethon_functions().messages.SendMessageRequest(
            peer=entity,
            message=message,
            entities=entities,
            no_webpage=not link_preview,
            reply_to=reply_to,
        )
        return await self.execute_request(request, entity)

    async def send_media_action(
        self,
        action: MediaAction,
        *,
        force_low_level: bool = False,
    ) -> Any:
        reply_to = self.build_reply_to(action.reply_to)
        use_fast_upload = bool(
            isinstance(action.path, str)
            and self.should_use_fast_upload
            and self.should_use_fast_upload(self.client, action.path)
        )
        if (
            not force_low_level
            and not self.should_use_low_level_request(reply_to)
            and not use_fast_upload
        ):
            payload: dict[str, Any] = {
                "caption": action.caption,
                "reply_to": reply_to,
            }
            if action.caption_parse_mode is not None:
                payload["parse_mode"] = action.caption_parse_mode
            if action.mime_type is not None:
                payload["mime_type"] = action.mime_type
            if action.attributes:
                payload["attributes"] = action.attributes
            return await self.client.send_file(self.peer, file=action.path, **payload)

        if self.build_input_media is None:
            raise ValueError("build_input_media is required for low-level media requests")

        entity = await self.resolve_input_peer()
        parsed_caption, msg_entities = await self.parse_formatting_entities(
            action.caption or "",
            action.caption_parse_mode,
        )
        _file_handle, media, _is_image = await self.build_input_media(
            self.client,
            action.path,
            **self._build_media_kwargs(
                mime_type=action.mime_type,
                attributes=action.attributes,
            ),
        )
        request = _telethon_functions().messages.SendMediaRequest(
            peer=entity,
            media=media,
            reply_to=self.normalize_low_level_reply_to(reply_to),
            message=parsed_caption,
            entities=msg_entities,
        )
        return await self.execute_request(request, entity)

    async def send_media_group_action(
        self,
        action: MediaGroupAction,
    ) -> Any:
        entity = await self.resolve_input_peer()
        parsed_caption, msg_entities = await self.parse_formatting_entities(
            action.caption or "",
            action.caption_parse_mode,
        )
        single_media: list[Any] = []
        if self.build_input_media is None:
            raise ValueError("build_input_media is required for low-level media requests")

        for index, (path, spoiler, is_video) in enumerate(action.media_items):
            media = await self._build_album_media(
                path,
                spoiler=spoiler,
                supports_streaming=is_video,
                entity=entity,
            )
            single_media.append(
                _input_single_media_type()(
                    media=media,
                    message=parsed_caption if index == 0 else "",
                    entities=msg_entities if index == 0 else None,
                )
            )

        request = _send_multi_media_request_type()(
            peer=entity,
            multi_media=single_media,
            reply_to=self.normalize_low_level_reply_to(self.build_reply_to(action.reply_to)),
        )
        return await self.execute_request(request, entity)

    async def _build_album_media(
        self,
        path: str,
        *,
        spoiler: bool,
        supports_streaming: bool,
        entity: Any,
    ) -> Any:
        if self.build_input_media is None:
            raise ValueError("build_input_media is required for low-level media requests")

        media_kwargs: dict[str, Any] = {}
        if supports_streaming:
            media_kwargs["supports_streaming"] = True
            media_kwargs["nosound_video"] = True

        _file_handle, media, _is_image = await self.build_input_media(
            self.client,
            path,
            **media_kwargs,
        )
        return await self._normalize_album_media(
            media,
            spoiler=spoiler,
            supports_streaming=supports_streaming,
            entity=entity,
        )

    async def _normalize_album_media(
        self,
        media: Any,
        *,
        spoiler: bool,
        supports_streaming: bool,
        entity: Any,
    ) -> Any:
        types = _telethon_types()
        functions = _telethon_functions()
        telethon_utils = _telethon_utils()
        uploaded_photo_type = getattr(types, "InputMediaUploadedPhoto", None)
        photo_external_type = getattr(types, "InputMediaPhotoExternal", None)
        uploaded_document_type = getattr(types, "InputMediaUploadedDocument", None)
        document_external_type = getattr(types, "InputMediaDocumentExternal", None)

        if spoiler and hasattr(media, "spoiler"):
            media.spoiler = True

        photo_types = tuple(
            media_type
            for media_type in (uploaded_photo_type, photo_external_type)
            if media_type is not None
        )
        if photo_types and isinstance(media, photo_types):
            result = await self.client(
                _upload_media_request_type()(peer=entity, media=media)
            )
            normalized_media = telethon_utils.get_input_media(result.photo)
            if spoiler and hasattr(normalized_media, "spoiler"):
                normalized_media.spoiler = True
            return normalized_media

        document_types = tuple(
            media_type
            for media_type in (uploaded_document_type, document_external_type)
            if media_type is not None
        )
        if document_types and isinstance(media, document_types):
            result = await self.client(
                _upload_media_request_type()(peer=entity, media=media)
            )
            normalized_media = telethon_utils.get_input_media(
                result.document,
                supports_streaming=supports_streaming,
            )
            if spoiler and hasattr(normalized_media, "spoiler"):
                normalized_media.spoiler = True
            return normalized_media

        return media

    @staticmethod
    def _build_media_kwargs(
        *,
        mime_type: str | None,
        attributes: list[Any] | None,
    ) -> dict[str, Any]:
        media_kwargs: dict[str, Any] = {}
        if mime_type is not None:
            media_kwargs["mime_type"] = mime_type
        if attributes:
            media_kwargs["attributes"] = attributes
        return media_kwargs
