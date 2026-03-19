from __future__ import annotations

import asyncio
import heapq
from typing import Any

from ..fast_upload import build_input_media, should_use_fast_upload
try:
    from ..transport.request_sender import TelethonRequestSender
except ImportError:
    from telethon_adapter.transport.request_sender import TelethonRequestSender
try:
    from .message_planner import MediaAction
except ImportError:
    from telethon_adapter.services.message_planner import MediaAction


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
        sender = self._build_request_sender(event)
        reply_to_msg_id = self._resolve_reply_to_message_id(event) if follow_reply else None

        if file_path:
            sent_message = await sender.send_media_action(
                MediaAction(
                    path=file_path,
                    caption=text,
                    caption_parse_mode="html",
                    reply_to=reply_to_msg_id,
                    action_name="document",
                    fallback_action=None,
                ),
            )
        else:
            sent_message = await sender.send_text(
                text,
                parse_mode="html",
                reply_to_msg_id=reply_to_msg_id,
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
        return TelethonRequestSender.normalize_reply_to_message_id(
            getattr(reply_to, "reply_to_msg_id", None)
        )

    @staticmethod
    def _build_request_sender(event: Any) -> TelethonRequestSender:
        thread_id = TelethonRequestSender.normalize_reply_to_message_id(
            getattr(event, "thread_id", None)
        )
        return TelethonRequestSender(
            client=getattr(event, "client", None),
            peer=getattr(event, "peer", None),
            thread_id=thread_id,
            build_input_media=build_input_media,
            should_use_fast_upload=should_use_fast_upload,
        )

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
