from __future__ import annotations

import asyncio
import heapq
from typing import Any

from telethon import functions, types

from ..fast_upload import build_input_media, should_use_fast_upload


class TelethonSender:
    def __init__(self) -> None:
        self._delete_heap: list[tuple[float, int, Any, Any, int]] = []
        self._delete_worker_task: asyncio.Task | None = None
        self._delete_wakeup = asyncio.Event()
        self._delete_seq = 0

    async def send_html_message(
        self,
        event: Any,
        text: str,
        file_path: str | None = None,
        follow_reply: bool = False,
        link_preview: bool = False,
    ) -> Any:
        client = getattr(event, "client", None)
        peer = getattr(event, "peer", None)
        if client is None or peer is None:
            raise ValueError("No Telethon send context is available for the current event.")
        reply_to = self._build_reply_to(event, follow_reply=follow_reply)

        if file_path:
            sent_message = await self._send_media_message(
                client,
                peer,
                file_path,
                text,
                reply_to=reply_to,
            )
        else:
            sent_message = await self._send_text_message(
                client,
                peer,
                text,
                reply_to=reply_to,
                link_preview=link_preview,
            )

        stop_event = getattr(event, "stop_event", None)
        if callable(stop_event):
            stop_event()
        return sent_message

    @staticmethod
    def _resolve_reply_to_message_id(event: Any) -> int | None:
        raw_message = getattr(getattr(event, "message_obj", None), "raw_message", None)
        reply_to = getattr(raw_message, "reply_to", None)
        reply_to_msg_id = getattr(reply_to, "reply_to_msg_id", None)
        try:
            return int(reply_to_msg_id) if reply_to_msg_id is not None else None
        except (TypeError, ValueError):
            return None

    @classmethod
    def _build_reply_to(cls, event: Any, *, follow_reply: bool) -> Any | None:
        thread_id = getattr(event, "thread_id", None)
        try:
            thread_id = int(thread_id) if thread_id is not None else None
        except (TypeError, ValueError):
            thread_id = None

        reply_to_msg_id = cls._resolve_reply_to_message_id(event) if follow_reply else None
        if thread_id is None:
            return reply_to_msg_id

        effective_reply_to = reply_to_msg_id if reply_to_msg_id is not None else thread_id
        return types.InputReplyToMessage(
            reply_to_msg_id=effective_reply_to,
            top_msg_id=thread_id,
        )

    @staticmethod
    def _normalize_low_level_reply_to(reply_to: Any | None) -> Any | None:
        if reply_to is None or isinstance(reply_to, types.InputReplyToMessage):
            return reply_to
        return types.InputReplyToMessage(reply_to_msg_id=int(reply_to))

    @staticmethod
    async def _resolve_input_peer(client: Any, peer: Any) -> Any:
        get_input_entity = getattr(client, "get_input_entity", None)
        if callable(get_input_entity):
            return await get_input_entity(peer)
        return peer

    @staticmethod
    async def _parse_formatting_entities(
        client: Any,
        text: str,
        parse_mode: str | None,
    ) -> tuple[str, Any | None]:
        if parse_mode is None:
            return text, None
        parse_message_text = getattr(client, "_parse_message_text", None)
        if callable(parse_message_text):
            return await parse_message_text(text, parse_mode)
        return text, None

    @staticmethod
    async def _execute_request(client: Any, request: Any, entity: Any) -> Any:
        result = await client(request)
        get_response_message = getattr(client, "_get_response_message", None)
        if callable(get_response_message):
            return get_response_message(request, result, entity)
        return result

    async def _send_text_message(
        self,
        client: Any,
        peer: Any,
        text: str,
        *,
        reply_to: Any | None,
        link_preview: bool,
    ) -> Any:
        if not self._should_use_low_level_request(reply_to):
            return await client.send_message(
                peer,
                text,
                parse_mode="html",
                link_preview=link_preview,
                reply_to=reply_to,
            )

        entity = await self._resolve_input_peer(client, peer)
        message, entities = await self._parse_formatting_entities(client, text, "html")
        request = functions.messages.SendMessageRequest(
            peer=entity,
            message=message,
            entities=entities,
            no_webpage=not link_preview,
            reply_to=reply_to,
        )
        return await self._execute_request(client, request, entity)

    async def _send_media_message(
        self,
        client: Any,
        peer: Any,
        file_path: str,
        caption: str | None,
        *,
        reply_to: Any | None,
    ) -> Any:
        if not self._should_use_low_level_request(reply_to) and not should_use_fast_upload(
            client,
            file_path,
        ):
            return await client.send_file(
                peer,
                file=file_path,
                caption=caption,
                parse_mode="html",
                reply_to=reply_to,
            )

        entity = await self._resolve_input_peer(client, peer)
        parsed_caption, msg_entities = await self._parse_formatting_entities(
            client,
            caption or "",
            "html",
        )
        low_level_reply_to = self._normalize_low_level_reply_to(reply_to)
        _file_handle, media, _is_image = await build_input_media(client, file_path)
        request = functions.messages.SendMediaRequest(
            peer=entity,
            media=media,
            reply_to=low_level_reply_to,
            message=parsed_caption,
            entities=msg_entities,
        )
        return await self._execute_request(client, request, entity)

    @staticmethod
    def _should_use_low_level_request(reply_to: Any | None) -> bool:
        return isinstance(reply_to, types.InputReplyToMessage)

    def schedule_delete_message(
        self,
        event: Any,
        message: Any,
        delay_seconds: float,
    ) -> None:
        message_id = getattr(message, "id", None)
        if message_id is None or delay_seconds < 0:
            return

        client = getattr(event, "client", None)
        peer = getattr(event, "peer", None)
        if client is None or peer is None:
            return

        loop = asyncio.get_running_loop()
        self._delete_seq += 1
        heapq.heappush(
            self._delete_heap,
            (
                loop.time() + float(delay_seconds),
                self._delete_seq,
                client,
                peer,
                int(message_id),
            ),
        )
        if self._delete_worker_task is None or self._delete_worker_task.done():
            self._delete_worker_task = asyncio.create_task(self._delete_worker())
        self._delete_wakeup.set()

    async def _delete_worker(self) -> None:
        loop = asyncio.get_running_loop()
        while self._delete_heap:
            deadline, _seq, client, peer, message_id = self._delete_heap[0]
            delay_seconds = deadline - loop.time()
            if delay_seconds > 0:
                self._delete_wakeup.clear()
                try:
                    await asyncio.wait_for(
                        self._delete_wakeup.wait(),
                        timeout=delay_seconds,
                    )
                except TimeoutError:
                    pass
                continue

            heapq.heappop(self._delete_heap)
            try:
                await client.delete_messages(peer, [message_id], revoke=True)
            except Exception:
                continue
