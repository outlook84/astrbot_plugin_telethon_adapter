from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

try:
    from .message_planner import MediaAction, MediaGroupAction
except ImportError:
    from telethon_adapter.services.message_planner import MediaAction, MediaGroupAction


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

    async def _send_base_message(self, message: Any) -> None: ...
    async def _flush_text(self, text_parts: list[tuple[str, bool]], reply_to: int | None) -> int | None: ...
    async def _execute_media_action(self, action: MediaAction) -> int | None: ...
    async def _execute_media_group_action(self, action: MediaGroupAction) -> None: ...
    async def _chat_action_scope(self, action_name: str, fallback_action: Any): ...
    def _message_log_context(self, reply_to: int | None = None) -> dict[str, Any]: ...


class TelethonRuntimeHost(Protocol):
    def _effective_reply_to(self, reply_to: int | None) -> int | None: ...
    async def _send_media_request(self, action: MediaAction) -> Any: ...
    client: Any
    peer: Any
    thread_id: int | None
    message_obj: Any


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
