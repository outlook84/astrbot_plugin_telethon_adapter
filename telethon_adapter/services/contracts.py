from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class TelethonEventContext:
    chat_id: Any
    thread_id: int | None
    msg_id: Any
    sender_id: Any
    reply_to: int | None


class TelethonDispatcherHost(Protocol):
    META_ATTR: str
    MEDIA_GROUP_INTENT: str
    client: Any
    peer: Any

    async def _send_base_message(self, message: Any) -> None: ...
    async def _flush_text(self, text_parts: list[tuple[str, bool]], reply_to: int | None) -> int | None: ...
    def _format_at_html(self, item: Any) -> str | None: ...
    def _format_at_text(self, item: Any) -> str: ...
    def _label(self, key: str) -> str: ...
    def _is_gif_path(self, path: str) -> bool: ...
    async def _send_media(
        self,
        path: str,
        caption: str | None,
        reply_to: int | None,
        action_name: str,
        fallback_action: Any,
        mime_type: str | None = None,
        attributes: list[Any] | None = None,
        spoiler: bool = False,
    ) -> int | None: ...
    def _component_has_spoiler(self, item: Any) -> bool: ...
    def _should_use_low_level_media_group_request(self, *, has_spoiler: bool) -> bool: ...
    def _request_sender(self) -> Any: ...
    def _build_reply_to(self, reply_to: int | None) -> Any | None: ...
    async def _send_local_media_group_request(
        self,
        media_items: list[tuple[str, bool, bool]],
        *,
        caption: str | None,
        reply_to: int | None,
    ) -> None: ...
    async def _chat_action_scope(self, action_name: str, fallback_action: Any): ...
    def _message_log_context(self, reply_to: int | None = None) -> dict[str, Any]: ...


class TelethonRuntimeHost(Protocol):
    client: Any
    peer: Any
    thread_id: int | None
    message_obj: Any

    def _effective_reply_to(self, reply_to: int | None) -> int | None: ...
    async def _send_media_request(
        self,
        path: str,
        *,
        caption: str | None,
        reply_to: int | None,
        mime_type: str | None = None,
        attributes: list[Any] | None = None,
        spoiler: bool = False,
    ) -> Any: ...
    async def _resolve_input_peer(self) -> Any: ...
    async def _parse_formatting_entities(
        self,
        text: str,
        parse_mode: str | None,
    ) -> tuple[str, Any | None]: ...
    def _normalize_low_level_reply_to(self, reply_to: Any | None) -> Any | None: ...
    def _build_reply_to(self, reply_to: int | None) -> Any | None: ...


class TelethonExecutionHost(TelethonRuntimeHost, Protocol):
    async def _send_text_request(
        self,
        text: str,
        *,
        parse_mode: str | None,
        reply_to: int | None,
        link_preview: bool,
    ) -> Any: ...
    def _pack_text_chunks(self, text_parts: list[tuple[str, bool]]) -> list[list[tuple[str, bool]]]: ...
    def _render_text_chunk(self, text_parts: list[tuple[str, bool]]) -> str: ...
    def _looks_like_markdown(self, text: str) -> bool: ...
    def _split_html_message(self, html_text: str) -> list[str]: ...
    async def _format_markdown_for_telethon_html_async(self, text: str) -> str: ...
