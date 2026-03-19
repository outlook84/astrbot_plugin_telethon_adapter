from __future__ import annotations

from dataclasses import dataclass
import importlib
from typing import Any, Awaitable, Callable

BuildInputMedia = Callable[..., Awaitable[tuple[Any, Any, bool]]]
ShouldUseFastUpload = Callable[[Any, str], bool]


def _telethon_functions() -> Any:
    return importlib.import_module("telethon.functions")


def _telethon_types() -> Any:
    return importlib.import_module("telethon.types")


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

        types = _telethon_types()
        effective_reply_to = (
            normalized_reply_to if normalized_reply_to is not None else self.thread_id
        )
        return types.InputReplyToMessage(
            reply_to_msg_id=effective_reply_to,
            top_msg_id=self.thread_id,
        )

    @staticmethod
    def normalize_low_level_reply_to(reply_to: Any | None) -> Any | None:
        types = _telethon_types()
        if reply_to is None or isinstance(reply_to, types.InputReplyToMessage):
            return reply_to
        return types.InputReplyToMessage(reply_to_msg_id=int(reply_to))

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
        types = _telethon_types()
        return isinstance(reply_to, types.InputReplyToMessage)

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

    async def send_media(
        self,
        file_path: str,
        *,
        caption: str | None,
        parse_mode: str | None,
        reply_to_msg_id: Any | None,
        mime_type: str | None = None,
        attributes: list[Any] | None = None,
        force_low_level: bool = False,
    ) -> Any:
        reply_to = self.build_reply_to(reply_to_msg_id)
        use_fast_upload = bool(
            self.should_use_fast_upload and self.should_use_fast_upload(self.client, file_path)
        )
        if not force_low_level and not self.should_use_low_level_request(reply_to) and not use_fast_upload:
            payload: dict[str, Any] = {
                "caption": caption,
                "reply_to": reply_to,
            }
            if parse_mode is not None:
                payload["parse_mode"] = parse_mode
            if mime_type is not None:
                payload["mime_type"] = mime_type
            if attributes:
                payload["attributes"] = attributes
            return await self.client.send_file(self.peer, file=file_path, **payload)

        if self.build_input_media is None:
            raise ValueError("build_input_media is required for low-level media requests")

        entity = await self.resolve_input_peer()
        parsed_caption, msg_entities = await self.parse_formatting_entities(
            caption or "",
            parse_mode,
        )
        _file_handle, media, _is_image = await self.build_input_media(
            self.client,
            file_path,
            **self._build_media_kwargs(mime_type=mime_type, attributes=attributes),
        )
        request = _telethon_functions().messages.SendMediaRequest(
            peer=entity,
            media=media,
            reply_to=self.normalize_low_level_reply_to(reply_to),
            message=parsed_caption,
            entities=msg_entities,
        )
        return await self.execute_request(request, entity)

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
