from __future__ import annotations

import re
from contextlib import asynccontextmanager
from typing import Any

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
        display = str(item.name or qq_str).strip() or qq_str
        if qq_str.startswith("@"):
            return f"{qq_str} "
        if qq_str.isdigit():
            escaped_display = display.replace("]", r"\]")
            return f"[{escaped_display}](tg://user?id={qq_str}) "
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

    async def _send_text_with_action(self, text: str, reply_to: int | None):
        await self.send_typing()
        try:
            return await self.client.send_message(
                self.peer,
                text,
                reply_to=reply_to,
                parse_mode="md",
                link_preview=False,
            )
        except Exception as e:
            logger.warning(f"[Telethon] Markdown发送失败，使用普通文本: {e!s}")
        return await self.client.send_message(
            self.peer,
            text,
            reply_to=reply_to,
            link_preview=False,
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
