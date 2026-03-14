from __future__ import annotations

import html
import re
from contextlib import asynccontextmanager
from typing import Any

from bs4 import BeautifulSoup
import markdown
from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, MessageChain
from astrbot.api.message_components import (
    At,
    File,
    Image,
    Location,
    Plain,
    Record,
    Reply,
    Video,
)
from astrbot.api.platform import AstrBotMessage, PlatformMetadata
from telethon import functions, types


class TelethonEvent(AstrMessageEvent):
    MAX_MESSAGE_LENGTH = 4096
    SPLIT_PATTERNS = {
        "paragraph": re.compile(r"\n\n"),
        "line": re.compile(r"\n"),
        "sentence": re.compile(r"[.!?。！？]"),
        "word": re.compile(r"\s"),
    }
    MARKDOWN_HINT_PATTERNS = (
        re.compile(r"```"),
        re.compile(r"(?m)^\s{0,3}#{1,6}\s+\S"),
        re.compile(r"(?m)^\s{0,3}>\s+\S"),
        re.compile(r"(?m)^\s{0,3}(?:[-*+]\s+\S|\d+\.\s+\S)"),
        re.compile(r"(?m)^\|.+\|\s*$"),
        re.compile(r"\[[^\]\n]+\]\((?:https?://|tg://)[^)]+\)"),
        re.compile(r"(?<!\*)\*\*[^*\n]+\*\*(?!\*)"),
        re.compile(r"(?<!_)__[^_\n]+__(?!_)"),
        re.compile(r"`[^`\n]+`"),
    )

    def __init__(
        self,
        message_str: str,
        message_obj: AstrBotMessage,
        platform_meta: PlatformMetadata,
        session_id: str,
        client: Any,
    ) -> None:
        super().__init__(message_str, message_obj, platform_meta, session_id)
        self.client = client
        self.peer = int(session_id)

    async def _send_chat_action(self, action: types.TypeSendMessageAction) -> None:
        try:
            await self.client(
                functions.messages.SetTypingRequest(
                    peer=self.peer,
                    action=action,
                )
            )
        except Exception as e:
            logger.warning(f"[Telethon] 发送 chat action 失败: {e!s}")

    @asynccontextmanager
    async def _chat_action_scope(
        self,
        action_name: str,
        fallback_action: types.TypeSendMessageAction,
    ):
        action_method = getattr(self.client, "action", None)
        if callable(action_method):
            try:
                async with action_method(self.peer, action_name):
                    yield
                return
            except Exception as e:
                logger.debug(
                    f"[Telethon] action 上下文不可用，回退单次 chat action: {e!s}"
                )

        await self._send_chat_action(fallback_action)
        yield

    async def _flush_text(
        self, text_parts: list[str], reply_to: int | None
    ) -> int | None:
        if not text_parts:
            return reply_to
        chunks = self._pack_text_chunks(text_parts)
        text_parts.clear()
        for chunk in chunks:
            if not chunk.strip():
                continue
            await self._send_text_with_action(chunk, reply_to)
        return reply_to

    async def _send_media(
        self,
        path: str,
        caption: str | None,
        reply_to: int | None,
        action_name: str,
        fallback_action: types.TypeSendMessageAction,
    ) -> int | None:
        try:
            async with self._chat_action_scope(action_name, fallback_action):
                await self.client.send_file(
                    self.peer,
                    file=path,
                    caption=caption,
                    reply_to=reply_to,
                )
        except Exception:
            logger.exception("[Telethon] 发送媒体失败: path=%s", path)
        return reply_to

    async def send_typing(self) -> None:
        await self._send_chat_action(types.SendMessageTypingAction())

    async def send(self, message: MessageChain):
        reply_to: int | None = None
        text_parts: list[str] = []

        for item in message.chain:
            if isinstance(item, Reply):
                try:
                    reply_to = int(item.id)
                except (TypeError, ValueError):
                    logger.warning(f"[Telethon] 无法解析 Reply ID: {item.id}")
                continue

            if isinstance(item, At):
                text_parts.append(self._format_at_text(item))
                continue

            if isinstance(item, Plain):
                text_parts.append(item.text)
                continue

            if isinstance(item, Location):
                text_parts.append(
                    f"[位置] {item.lat},{item.lon} {item.title or ''}".strip()
                )
                continue

            # 发送媒体前先把缓冲文本发掉，避免消息顺序错乱。
            reply_to = await self._flush_text(text_parts, reply_to)

            if isinstance(item, Image):
                file_path = await item.convert_to_file_path()
                reply_to = await self._send_media(
                    file_path,
                    None,
                    reply_to,
                    "photo",
                    types.SendMessageUploadPhotoAction(progress=0),
                )
                continue

            if isinstance(item, Video):
                file_path = await item.convert_to_file_path()
                reply_to = await self._send_media(
                    file_path,
                    None,
                    reply_to,
                    "video",
                    types.SendMessageUploadVideoAction(progress=0),
                )
                continue

            if isinstance(item, Record):
                file_path = await item.convert_to_file_path()
                reply_to = await self._send_media(
                    file_path,
                    item.text,
                    reply_to,
                    "audio",
                    types.SendMessageUploadAudioAction(progress=0),
                )
                continue

            if isinstance(item, File):
                file_path = await item.get_file()
                reply_to = await self._send_media(
                    file_path,
                    item.name,
                    reply_to,
                    "document",
                    types.SendMessageUploadDocumentAction(progress=0),
                )
                continue

            logger.warning(f"[Telethon] 暂不支持消息段类型: {item.type}")

        await self._flush_text(text_parts, reply_to)
        await super().send(message)

    @staticmethod
    def _format_at_text(item: At) -> str:
        qq_str = str(item.qq).strip()
        if qq_str.startswith("@"):
            return f"{qq_str} "
        display = str(item.name or "").strip()
        if display.startswith("@"):
            return f"{display} "
        if display and " " not in display:
            return f"@{display} "
        if qq_str:
            return f"@{qq_str} "
        return f"@{qq_str} "

    @classmethod
    def _split_message(cls, text: str) -> list[str]:
        if len(text) <= cls.MAX_MESSAGE_LENGTH:
            return [text]
        chunks: list[str] = []
        while text:
            if len(text) <= cls.MAX_MESSAGE_LENGTH:
                chunks.append(text)
                break

            split_point = cls.MAX_MESSAGE_LENGTH
            segment = text[: cls.MAX_MESSAGE_LENGTH]
            for _, pattern in cls.SPLIT_PATTERNS.items():
                matches = list(pattern.finditer(segment))
                if matches:
                    split_point = matches[-1].end()
                    break
            chunks.append(text[:split_point])
            text = text[split_point:].lstrip()
        return chunks

    def _pack_text_chunks(self, text_parts: list[str]) -> list[str]:
        packed: list[str] = []
        current = ""

        def flush_current():
            nonlocal current
            if current:
                packed.append(current)
                current = ""

        for part in text_parts:
            if not part:
                continue
            if len(part) > self.MAX_MESSAGE_LENGTH:
                flush_current()
                packed.extend(self._split_message(part))
                continue
            if len(current) + len(part) <= self.MAX_MESSAGE_LENGTH:
                current += part
            else:
                flush_current()
                current = part
        flush_current()
        return packed

    @classmethod
    def _looks_like_markdown(cls, text: str) -> bool:
        return any(pattern.search(text) for pattern in cls.MARKDOWN_HINT_PATTERNS)

    @staticmethod
    def _render_table(node) -> str:
        rows: list[list[str]] = []
        for tr in node.find_all("tr"):
            cells = [cell.get_text(" ", strip=True) for cell in tr.find_all(["th", "td"])]
            if cells:
                rows.append(cells)
        if not rows:
            return ""

        column_count = max(len(row) for row in rows)
        normalized_rows = [row + [""] * (column_count - len(row)) for row in rows]
        widths = [
            max(len(row[index]) for row in normalized_rows)
            for index in range(column_count)
        ]

        rendered_rows: list[str] = []
        for index, row in enumerate(normalized_rows):
            rendered_rows.append(
                " | ".join(cell.ljust(widths[cell_index]) for cell_index, cell in enumerate(row))
            )
            if index == 0 and len(normalized_rows) > 1:
                rendered_rows.append(
                    "-+-".join("-" * width for width in widths)
                )
        table_text = "\n".join(rendered_rows).rstrip()
        return f"<pre><code>{html.escape(table_text)}</code></pre>\n"

    @classmethod
    def _format_markdown_for_telethon_html(cls, text: str) -> str:
        raw_html = markdown.markdown(
            text,
            extensions=["fenced_code", "tables"],
        )
        soup = BeautifulSoup(raw_html, "html.parser")
        block_container_tags = {"ul", "ol", "blockquote"}

        def should_skip_whitespace_text(node) -> bool:
            return (
                getattr(node.parent, "name", None) in block_container_tags
                and not str(node).strip()
            )

        def is_list_item_paragraph(node) -> bool:
            return getattr(node.parent, "name", None) == "li"

        def convert(node) -> str:
            if node.name is None:
                if should_skip_whitespace_text(node):
                    return ""
                return html.escape(str(node))

            tag = node.name
            if tag == "pre":
                code_node = node.find("code")
                code_text = html.escape(node.get_text())
                language = ""
                if code_node:
                    for css_class in code_node.get("class", []):
                        if css_class.startswith("language-"):
                            language = css_class[len("language-") :]
                            break
                inner_tag = (
                    f'<code class="{html.escape(language)}">' if language else "<code>"
                )
                return f"<pre>{inner_tag}{code_text}</code></pre>"
            if tag == "table":
                return cls._render_table(node)

            inner = "".join(convert(child) for child in node.children)

            if tag in ("b", "strong"):
                return f"<b>{inner}</b>"
            if tag in ("i", "em"):
                return f"<i>{inner}</i>"
            if tag in ("s", "del", "strike"):
                return f"<s>{inner}</s>"
            if tag == "u":
                return f"<u>{inner}</u>"
            if tag == "code":
                return f"<code>{inner}</code>"
            if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
                return f"<b>{inner}</b>\n"
            if tag == "p":
                if is_list_item_paragraph(node):
                    return inner
                return f"{inner}\n"
            if tag == "br":
                return "\n"
            if tag == "hr":
                return "\n------\n"
            if tag == "a":
                href = html.escape(node.get("href", ""))
                return f'<a href="{href}">{inner}</a>'
            if tag in ("ul", "ol"):
                return inner
            if tag == "li":
                return f"• {inner.strip()}\n"
            if tag == "blockquote":
                return f"<blockquote>{inner.strip()}</blockquote>\n"
            return inner

        result = "".join(convert(child) for child in soup.children)
        result = re.sub(r"\n{3,}", "\n\n", result)
        return result.strip()

    async def _send_text_with_action(self, text: str, reply_to: int | None):
        await self.send_typing()
        payload = {
            "reply_to": reply_to,
            "link_preview": False,
        }
        if not self._looks_like_markdown(text):
            return await self.client.send_message(
                self.peer,
                text,
                **payload,
            )
        try:
            formatted_text = self._format_markdown_for_telethon_html(text)
            return await self.client.send_message(
                self.peer,
                formatted_text,
                parse_mode="html",
                **payload,
            )
        except Exception as e:
            logger.warning(f"[Telethon] Markdown转HTML发送失败，使用普通文本: {e!s}")
        return await self.client.send_message(
            self.peer,
            text,
            **payload,
        )

    async def react(self, emoji: str) -> None:
        raw_message = getattr(self.message_obj, "raw_message", None)
        react_method = getattr(raw_message, "react", None)
        if callable(react_method):
            try:
                await react_method(emoji)
                return
            except Exception as e:
                logger.warning(f"[Telethon] 原生 reaction 失败，尝试 MTProto 兜底: {e!s}")

        message_id = getattr(self.message_obj, "message_id", None)
        try:
            await self.client(
                functions.messages.SendReactionRequest(
                    peer=self.peer,
                    msg_id=int(message_id),
                    reaction=[types.ReactionEmoji(emoticon=emoji)],
                )
            )
            return
        except Exception as e:
            logger.warning(f"[Telethon] MTProto reaction 失败: {e!s}")

        logger.warning("[Telethon] 当前消息对象不支持原生 reaction，已跳过预回应表情")
