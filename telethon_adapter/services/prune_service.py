from __future__ import annotations

import asyncio
import html
from dataclasses import dataclass
from typing import Any

from astrbot.api import logger
from astrbot.api.message_components import At

try:
    from telethon import errors as telethon_errors
except ImportError:
    telethon_errors = None

PRUNE_MAX_COUNT = 200
PRUNE_BATCH_SIZE = 100
PRUNE_BATCH_DELAY_SECONDS = 1.0
PRUNE_FLOOD_WAIT_RETRY_SECONDS = 10
PRUNE_FILTERED_SCAN_LIMIT = 1000


def _error_type(name: str) -> type[BaseException] | None:
    if telethon_errors is None:
        return None
    value = getattr(telethon_errors, name, None)
    return value if isinstance(value, type) else None


FloodWaitError = _error_type("FloodWaitError")
MessageDeleteForbiddenError = _error_type("MessageDeleteForbiddenError")
MessageIdInvalidError = _error_type("MessageIdInvalidError")
ChatAdminRequiredError = _error_type("ChatAdminRequiredError")
ForbiddenError = _error_type("ForbiddenError")
RPCError = _error_type("RPCError")


def _has_user_identity(entity: Any) -> bool:
    if entity is None:
        return False
    user_id = TelethonPruneService._coerce_message_id(getattr(entity, "id", None))
    if user_id is None:
        return False
    if bool(getattr(entity, "bot", False)):
        return True
    if bool(getattr(entity, "self", False)):
        return True
    if hasattr(entity, "first_name") or hasattr(entity, "last_name") or hasattr(entity, "username"):
        return True
    return False


@dataclass(slots=True)
class PruneResult:
    requested_count: int | None
    scanned_count: int
    scan_limit: int | None
    hit_scan_limit: bool
    matched_count: int
    deleted_count: int
    filtered_out_count: int
    skipped_count: int
    failed_count: int
    used_reply_anchor: bool
    reply_anchor_id: int | None
    only_self: bool = False
    target_user_id: int | None = None
    command_deleted: bool = False
    partial: bool = False


class TelethonPruneService:
    async def prune_messages(
        self,
        event: Any,
        count: int | None = None,
        *,
        only_self: bool = False,
        target_user: Any | None = None,
    ) -> PruneResult:
        if count is not None and count <= 0:
            raise ValueError("删除数量必须是正整数。用法: `tg prune 20`。")
        if count is not None and count > PRUNE_MAX_COUNT:
            raise ValueError(
                f"单次最多只允许删除 {PRUNE_MAX_COUNT} 条消息，"
                "这是为了降低误删和风控风险。",
            )

        client = getattr(event, "client", None)
        raw_message = getattr(getattr(event, "message_obj", None), "raw_message", None)
        if client is None or raw_message is None:
            raise ValueError("当前事件没有可用的 Telethon 上下文。")

        chat = await self._get_chat(raw_message)
        peer = await self._resolve_peer(event, raw_message, chat)
        current_message_id = self._coerce_message_id(getattr(raw_message, "id", None))
        if current_message_id is None:
            raise ValueError("当前命令消息缺少有效的消息 ID，无法执行批量删除。")

        reply_anchor_id = self._extract_reply_anchor_id(raw_message)
        if count is None and reply_anchor_id is None:
            raise ValueError("省略数量时必须回复一条消息。用法: 回复目标后执行 `tg prune`。")

        await self._ensure_delete_permission(chat)
        command_message_id = self._collect_current_command_message(
            raw_message=raw_message,
            current_message_id=current_message_id,
            reply_anchor_id=reply_anchor_id,
            include_current_message=True,
        )
        candidate_ids, scanned_count, filtered_out_count = await self._collect_candidate_ids(
            client=client,
            peer=peer,
            current_message_id=current_message_id,
            reply_anchor_id=reply_anchor_id,
            count=count,
            self_id=await self._resolve_self_id(client, raw_message) if only_self else None,
            target_user_id=self._coerce_message_id(getattr(target_user, "id", None)),
            scan_limit=PRUNE_FILTERED_SCAN_LIMIT if (only_self or target_user is not None) else None,
        )
        all_candidate_ids = (
            [command_message_id, *candidate_ids]
            if command_message_id is not None
            else candidate_ids
        )
        if not all_candidate_ids:
            raise ValueError(
                "没有找到可删除的消息。"
                if reply_anchor_id is None
                else "回复锚点和当前命令之间没有可删除的普通消息。",
            )

        deleted_count = 0
        deleted_message_ids: set[int] = set()
        delete_skipped_count = 0
        failed_count = 0
        partial = False
        for index, batch in enumerate(self._chunked(all_candidate_ids, PRUNE_BATCH_SIZE)):
            try:
                batch_deleted, batch_skipped, batch_failed, batch_deleted_ids = await self._delete_batch(
                    client=client,
                    peer=peer,
                    message_ids=batch,
                )
            except Exception:
                partial = True
                raise

            deleted_count += batch_deleted
            deleted_message_ids.update(batch_deleted_ids)
            delete_skipped_count += batch_skipped
            failed_count += batch_failed

            if index + 1 < (len(all_candidate_ids) + PRUNE_BATCH_SIZE - 1) // PRUNE_BATCH_SIZE:
                await asyncio.sleep(PRUNE_BATCH_DELAY_SECONDS)

        hit_scan_limit = scanned_count >= PRUNE_FILTERED_SCAN_LIMIT if (only_self or target_user is not None) else False
        command_deleted = (
            command_message_id is not None and command_message_id in deleted_message_ids
        )
        displayed_deleted_count = max(deleted_count - (1 if command_deleted else 0), 0)
        if failed_count > 0 or displayed_deleted_count < len(candidate_ids) or hit_scan_limit:
            partial = True

        return PruneResult(
            requested_count=count,
            scanned_count=scanned_count,
            scan_limit=PRUNE_FILTERED_SCAN_LIMIT if (only_self or target_user is not None) else None,
            hit_scan_limit=hit_scan_limit,
            matched_count=len(candidate_ids),
            deleted_count=displayed_deleted_count,
            filtered_out_count=filtered_out_count,
            skipped_count=delete_skipped_count,
            failed_count=failed_count,
            used_reply_anchor=reply_anchor_id is not None,
            reply_anchor_id=reply_anchor_id,
            only_self=only_self,
            target_user_id=self._coerce_message_id(getattr(target_user, "id", None)),
            command_deleted=command_deleted,
            partial=partial,
        )

    def format_result_text(self, result: PruneResult) -> str:
        title = "批量删除完成" if not result.partial else "批量删除部分完成"
        requested_count = "自动" if result.requested_count is None else str(result.requested_count)
        lines = [
            f"<b>{html.escape(title)}</b>",
            f"请求数量: <code>{requested_count}</code>",
            f"扫描消息: <code>{result.scanned_count}</code>",
            f"匹配数量: <code>{result.matched_count}</code>",
            f"成功删除: <code>{result.deleted_count}</code>",
            f"过滤数量: <code>{result.filtered_out_count}</code>",
            f"跳过数量: <code>{result.skipped_count}</code>",
            f"失败数量: <code>{result.failed_count}</code>",
        ]
        if result.used_reply_anchor and result.reply_anchor_id is not None:
            lines.append(f"回复锚点: <code>{result.reply_anchor_id}</code>")
        if result.only_self:
            lines.append("删除范围: <code>仅自己的消息</code>")
        elif result.target_user_id is not None:
            lines.append(f"删除目标: <code>{result.target_user_id}</code>")
        if result.scan_limit is not None:
            lines.append(f"扫描上限: <code>{result.scan_limit}</code>")
        if result.hit_scan_limit:
            lines.append("提示: 已达到扫描上限，只处理当前窗口内命中的消息。")
        if result.command_deleted:
            lines.append("提示: 已附带删除当前命令消息。")
        return "\n".join(lines)

    async def _ensure_delete_permission(self, chat: Any) -> None:
        if chat is None:
            return

        creator = bool(getattr(chat, "creator", False))
        if creator:
            return

        admin_rights = getattr(chat, "admin_rights", None)
        if admin_rights is None:
            return

        can_delete = bool(getattr(admin_rights, "delete_messages", False))
        if can_delete:
            return

        if bool(getattr(chat, "megagroup", False)) or bool(getattr(chat, "broadcast", False)):
            raise ValueError("当前账号看起来没有该会话的删除权限。")

    async def _resolve_peer(self, event: Any, raw_message: Any, chat: Any | None) -> Any:
        peer = getattr(event, "peer", None)
        if peer is not None:
            return peer

        peer = getattr(raw_message, "peer_id", None)
        if peer is not None:
            return peer

        if chat is not None:
            return chat

        raise ValueError("无法解析当前会话，无法执行批量删除。")

    async def _get_chat(self, raw_message: Any) -> Any | None:
        get_chat = getattr(raw_message, "get_chat", None)
        if not callable(get_chat):
            return None
        try:
            return await get_chat()
        except Exception:
            logger.debug("[Telethon] 拉取当前会话 chat 失败", exc_info=True)
            return None

    async def _collect_candidate_ids(
        self,
        client: Any,
        peer: Any,
        current_message_id: int,
        reply_anchor_id: int | None,
        count: int | None,
        self_id: int | None,
        target_user_id: int | None,
        scan_limit: int | None,
    ) -> tuple[list[int], int, int]:
        candidate_ids: list[int] = []
        scanned_count = 0
        filtered_out_count = 0

        async for message in client.iter_messages(peer, offset_id=current_message_id):
            if scan_limit is not None and scanned_count >= scan_limit:
                break

            scanned_count, filtered_out_count = self._collect_message_candidate(
                message=message,
                current_message_id=current_message_id,
                reply_anchor_id=reply_anchor_id,
                self_id=self_id,
                target_user_id=target_user_id,
                candidate_ids=candidate_ids,
                scanned_count=scanned_count,
                filtered_out_count=filtered_out_count,
            )
            if count is not None and len(candidate_ids) >= count:
                break

        return candidate_ids, scanned_count, filtered_out_count

    def _collect_current_command_message(
        self,
        *,
        raw_message: Any,
        current_message_id: int,
        reply_anchor_id: int | None,
        include_current_message: bool,
    ) -> int | None:
        if not include_current_message:
            return None
        message_id = self._coerce_message_id(getattr(raw_message, "id", None))
        if message_id is None or message_id != current_message_id:
            return None
        if reply_anchor_id is not None and message_id <= reply_anchor_id:
            return None
        if self._should_skip_message(raw_message):
            return None
        return message_id

    def _collect_message_candidate(
        self,
        *,
        message: Any,
        current_message_id: int,
        reply_anchor_id: int | None,
        self_id: int | None,
        target_user_id: int | None,
        candidate_ids: list[int],
        scanned_count: int,
        filtered_out_count: int,
    ) -> tuple[int, int]:
        message_id = self._coerce_message_id(getattr(message, "id", None))
        if message_id is None or message_id > current_message_id:
            return scanned_count, filtered_out_count
        if reply_anchor_id is not None and message_id <= reply_anchor_id:
            return scanned_count, filtered_out_count

        scanned_count += 1
        if self._should_skip_message(message):
            return scanned_count, filtered_out_count + 1
        if self_id is not None and not self._is_own_message(message, self_id):
            return scanned_count, filtered_out_count + 1
        if target_user_id is not None and not self._is_target_user_message(message, target_user_id):
            return scanned_count, filtered_out_count + 1

        candidate_ids.append(message_id)
        return scanned_count, filtered_out_count

    async def _delete_batch(
        self,
        client: Any,
        peer: Any,
        message_ids: list[int],
    ) -> tuple[int, int, int, set[int]]:
        try:
            await self._delete_messages(client, peer, message_ids)
            return len(message_ids), 0, 0, set(message_ids)
        except Exception as exc:
            if self._is_instance(exc, FloodWaitError):
                return await self._handle_flood_wait(
                    client=client,
                    peer=peer,
                    message_ids=message_ids,
                    exc=exc,
                )
            if self._is_instance(exc, MessageDeleteForbiddenError) or self._is_instance(
                exc,
                MessageIdInvalidError,
            ):
                return await self._delete_individually(client, peer, message_ids)
            if self._is_instance(exc, ChatAdminRequiredError) or self._is_instance(
                exc,
                ForbiddenError,
            ):
                raise ValueError("没有删除这些消息所需的权限。")
            if self._is_instance(exc, RPCError):
                logger.warning(
                    "[Telethon] 批量删除失败: peer=%r ids=%s error=%s",
                    peer,
                    message_ids,
                    exc,
                    exc_info=True,
                )
                raise ValueError(f"批量删除失败: {exc}")
            raise

    async def _handle_flood_wait(
        self,
        client: Any,
        peer: Any,
        message_ids: list[int],
        exc: BaseException,
    ) -> tuple[int, int, int, set[int]]:
        wait_seconds = int(getattr(exc, "seconds", 0) or 0)
        if wait_seconds <= 0 or wait_seconds > PRUNE_FLOOD_WAIT_RETRY_SECONDS:
            raise ValueError(
                "删除请求触发了 Telegram 风控，请稍后再试。"
                f"服务器要求等待 {wait_seconds} 秒。"
            ) from exc

        logger.warning(
            "[Telethon] prune 命中 FloodWait，等待 %s 秒后重试: ids=%s",
            wait_seconds,
            message_ids,
        )
        await asyncio.sleep(wait_seconds)
        await self._delete_messages(client, peer, message_ids)
        return len(message_ids), 0, 0, set(message_ids)

    async def _delete_individually(
        self,
        client: Any,
        peer: Any,
        message_ids: list[int],
    ) -> tuple[int, int, int, set[int]]:
        deleted_count = 0
        deleted_message_ids: set[int] = set()
        skipped_count = 0
        failed_count = 0

        for message_id in message_ids:
            try:
                await self._delete_messages(client, peer, [message_id])
                deleted_count += 1
                deleted_message_ids.add(message_id)
            except Exception as exc:
                if self._is_instance(exc, FloodWaitError):
                    batch_deleted, batch_skipped, batch_failed, batch_deleted_ids = await self._handle_flood_wait(
                        client=client,
                        peer=peer,
                        message_ids=[message_id],
                        exc=exc,
                    )
                    deleted_count += batch_deleted
                    deleted_message_ids.update(batch_deleted_ids)
                    skipped_count += batch_skipped
                    failed_count += batch_failed
                    continue
                if self._is_instance(exc, MessageDeleteForbiddenError) or self._is_instance(
                    exc,
                    MessageIdInvalidError,
                ):
                    skipped_count += 1
                    logger.info(
                        "[Telethon] 跳过不可删除消息: peer=%r message_id=%s error=%s",
                        peer,
                        message_id,
                        exc,
                    )
                    continue
                if self._is_instance(exc, ChatAdminRequiredError) or self._is_instance(
                    exc,
                    ForbiddenError,
                ):
                    raise ValueError("没有删除这些消息所需的权限。") from exc
                if self._is_instance(exc, RPCError):
                    failed_count += 1
                    logger.warning(
                        "[Telethon] 删除单条消息失败: peer=%r message_id=%s error=%s",
                        peer,
                        message_id,
                        exc,
                        exc_info=True,
                    )
                    continue
                raise

        return deleted_count, skipped_count, failed_count, deleted_message_ids

    async def _delete_messages(self, client: Any, peer: Any, message_ids: list[int]) -> None:
        await client.delete_messages(peer, message_ids, revoke=True)

    @staticmethod
    def _extract_reply_anchor_id(raw_message: Any) -> int | None:
        reply_to = getattr(raw_message, "reply_to", None)
        return TelethonPruneService._coerce_message_id(
            getattr(reply_to, "reply_to_msg_id", None),
        )

    @staticmethod
    def _coerce_message_id(value: Any) -> int | None:
        try:
            return int(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    async def _resolve_self_id(self, client: Any, raw_message: Any) -> int | None:
        sender_id = self._coerce_message_id(getattr(raw_message, "sender_id", None))
        if bool(getattr(raw_message, "out", False)) and sender_id is not None:
            return sender_id

        get_me = getattr(client, "get_me", None)
        if callable(get_me):
            try:
                me = await get_me()
            except Exception:
                logger.debug("[Telethon] 解析当前账号身份失败", exc_info=True)
            else:
                return self._coerce_message_id(getattr(me, "id", None))
        return None

    @staticmethod
    def _should_skip_message(message: Any) -> bool:
        return getattr(message, "action", None) is not None

    @staticmethod
    def _is_own_message(message: Any, self_id: int) -> bool:
        if bool(getattr(message, "out", False)):
            return True
        sender_id = TelethonPruneService._coerce_message_id(getattr(message, "sender_id", None))
        if sender_id is not None:
            return sender_id == self_id
        sender = getattr(message, "sender", None)
        resolved_sender_id = TelethonPruneService._coerce_message_id(getattr(sender, "id", None))
        if resolved_sender_id is not None:
            return resolved_sender_id == self_id
        return False

    @staticmethod
    def _is_target_user_message(message: Any, target_user_id: int) -> bool:
        sender_id = TelethonPruneService._coerce_message_id(getattr(message, "sender_id", None))
        if sender_id is not None:
            return sender_id == target_user_id
        sender = getattr(message, "sender", None)
        resolved_sender_id = TelethonPruneService._coerce_message_id(getattr(sender, "id", None))
        if resolved_sender_id is not None:
            return resolved_sender_id == target_user_id
        return False

    async def resolve_target_user(self, event: Any, target: str = "") -> Any:
        client = getattr(event, "client", None)
        raw_message = getattr(getattr(event, "message_obj", None), "raw_message", None)
        if client is None:
            raise ValueError("当前事件没有可用的 Telethon client。")

        normalized_target = self._normalize_target(target)
        if normalized_target:
            entity = await client.get_entity(normalized_target)
            if not _has_user_identity(entity):
                raise ValueError("`youprune` 只能指定用户，不能指定群组或频道。")
            return entity

        mention_entity = await self._resolve_mention_entity(
            client,
            getattr(event, "message_obj", None),
        )
        if mention_entity is not None:
            return mention_entity

        reply_entity = await self._resolve_reply_entity(raw_message)
        if reply_entity is not None:
            if not _has_user_identity(reply_entity):
                raise ValueError("回复目标不是用户，无法执行 `youprune`。")
            return reply_entity

        raise ValueError(
            "未找到可删除的目标用户。可传 @username / t.me 链接，"
            "也可以在消息中 @ 对方，或直接回复对方消息后执行 `tg youprune`。"
        )

    @staticmethod
    def _normalize_target(target: str) -> str | None:
        normalized = str(target or "").strip()
        if not normalized:
            return None
        if normalized.startswith("https://t.me/") or normalized.startswith("http://t.me/"):
            normalized = normalized.rstrip("/").split("/")[-1]
        if normalized.startswith("@"):
            normalized = normalized[1:]
        if not normalized:
            return None
        if normalized.lstrip("-").isdigit():
            return None
        return normalized

    async def _resolve_mention_entity(self, client: Any, message_obj: Any) -> Any | None:
        chain = getattr(message_obj, "message", None) or []
        self_id = str(getattr(message_obj, "self_id", "") or "")
        for component in chain:
            if not isinstance(component, At):
                continue
            qq = str(getattr(component, "qq", "") or "").strip()
            if not qq or qq == self_id:
                continue
            try:
                lookup = int(qq) if qq.lstrip("-").isdigit() else qq
                entity = await client.get_entity(lookup)
            except Exception:
                logger.debug("[Telethon] 解析 prune @ 提及目标失败: qq=%s", qq, exc_info=True)
                continue
            if _has_user_identity(entity):
                return entity
        return None

    async def _resolve_reply_entity(self, raw_message: Any) -> Any | None:
        get_reply_message = getattr(raw_message, "get_reply_message", None)
        if not callable(get_reply_message):
            return None
        try:
            reply_message = await get_reply_message()
        except Exception:
            logger.debug("[Telethon] 拉取回复消息失败，跳过 prune reply 目标解析", exc_info=True)
            return None
        if reply_message is None:
            return None

        get_sender = getattr(reply_message, "get_sender", None)
        if not callable(get_sender):
            return None
        try:
            return await get_sender()
        except Exception:
            logger.debug("[Telethon] 拉取 prune reply sender 失败", exc_info=True)
            return None

    @staticmethod
    def _chunked(values: list[int], size: int) -> list[list[int]]:
        return [values[index : index + size] for index in range(0, len(values), size)]

    @staticmethod
    def _is_instance(exc: BaseException, error_type: type[BaseException] | None) -> bool:
        return error_type is not None and isinstance(exc, error_type)
