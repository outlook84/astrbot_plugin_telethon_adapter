from __future__ import annotations

from typing import Any


class TelethonSender:
    async def send_html_message(
        self,
        event: Any,
        text: str,
        file_path: str | None = None,
    ) -> None:
        client = getattr(event, "client", None)
        peer = getattr(event, "peer", None)
        if client is None or peer is None:
            raise ValueError("当前事件没有可用的 Telethon 发送上下文。")

        if file_path:
            await client.send_file(
                peer,
                file=file_path,
                caption=text,
                parse_mode="html",
                link_preview=False,
            )
        else:
            await client.send_message(
                peer,
                text,
                parse_mode="html",
                link_preview=False,
            )

        stop_event = getattr(event, "stop_event", None)
        if callable(stop_event):
            stop_event()
