from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import html
import os
import re
import tempfile
from typing import Any

from astrbot.api import logger
from astrbot.api.message_components import At
from telethon import functions
from telethon.tl import types

from .data_center import format_data_center


def _type_tuple(*names: str) -> tuple[type, ...]:
    resolved = [getattr(types, name, None) for name in names]
    return tuple(item for item in resolved if isinstance(item, type))


USER_TYPES = _type_tuple("User")
CHAT_TYPES = _type_tuple("Chat", "ChatForbidden")
CHANNEL_TYPES = _type_tuple("Channel", "ChannelForbidden")
INPUT_SELF_TYPES = _type_tuple("InputPeerSelf")


@dataclass(slots=True)
class ResolvedProfile:
    entity: Any
    full: Any | None
    source: str


@dataclass(slots=True)
class ProfilePayload:
    text: str
    avatar_path: str | None = None


class TelethonProfileService:
    @staticmethod
    def supports_event(event: Any) -> bool:
        debug_logging = bool(getattr(event, "telethon_debug_logging", False))
        client = getattr(event, "client", None)
        if client is None:
            if debug_logging:
                logger.info("[Telethon][Debug] supports_event: client missing")
            return False

        platform_name = str(getattr(getattr(event, "platform_meta", None), "name", "") or "")
        raw_message = getattr(getattr(event, "message_obj", None), "raw_message", None)
        result = False
        if platform_name == "telegram" and raw_message is not None:
            result = True
        elif raw_message is not None and raw_message.__class__.__module__.startswith("telethon"):
            result = True
        else:
            result = hasattr(raw_message, "get_reply_message") or hasattr(raw_message, "peer_id")

        if debug_logging:
            logger.info(
                "[Telethon][Debug] supports_event: result=%s platform_name=%s "
                "raw_message_type=%s has_reply=%s has_peer=%s",
                result,
                platform_name,
                type(raw_message).__name__ if raw_message is not None else None,
                hasattr(raw_message, "get_reply_message"),
                hasattr(raw_message, "peer_id"),
            )
        return result

    async def build_profile_payload(
        self,
        event: Any,
        target: str = "",
        detailed: bool = False,
    ) -> ProfilePayload:
        client = getattr(event, "client", None)
        if client is None:
            raise ValueError("当前事件没有可用的 Telethon client。")

        resolved = await self._resolve_profile(event, target)
        avatar_path = await self._download_profile_photo(
            client,
            resolved.entity,
            resolved.full,
        )
        return ProfilePayload(
            text=self._format_profile_text(resolved, detailed=detailed),
            avatar_path=avatar_path,
        )

    async def render_profile(
        self,
        event: Any,
        target: str = "",
        detailed: bool = False,
    ) -> str:
        payload = await self.build_profile_payload(event, target, detailed=detailed)
        return payload.text

    async def _resolve_profile(self, event: Any, target: str) -> ResolvedProfile:
        entity, source = await self._resolve_entity(event, target)
        full = await self._fetch_full_entity(getattr(event, "client", None), entity)
        return ResolvedProfile(entity=entity, full=full, source=source)

    async def _resolve_entity(self, event: Any, target: str) -> tuple[Any, str]:
        client = getattr(event, "client", None)
        raw_message = getattr(getattr(event, "message_obj", None), "raw_message", None)

        normalized_target = self._normalize_target(target)
        if normalized_target:
            return await client.get_entity(normalized_target), f"显式参数 {target.strip()}"

        mention_entity = await self._resolve_mention_entity(
            client,
            getattr(event, "message_obj", None),
        )
        if mention_entity is not None:
            return mention_entity, "当前消息中的 @ 提及"

        reply_entity = await self._resolve_reply_entity(raw_message)
        if reply_entity is not None:
            return reply_entity, "回复消息"

        if getattr(event, "is_private_chat", lambda: False)():
            if raw_message is not None:
                get_chat = getattr(raw_message, "get_chat", None)
                if callable(get_chat):
                    try:
                        chat = await get_chat()
                    except Exception:
                        logger.debug("[Telethon] 拉取私聊对话对象失败", exc_info=True)
                    else:
                        if chat is not None:
                            return chat, "当前私聊对象"

                peer = getattr(raw_message, "peer_id", None)
                if peer is not None:
                    try:
                        return await client.get_entity(peer), "当前私聊对象"
                    except Exception:
                        logger.debug("[Telethon] 通过 peer_id 解析私聊对象失败", exc_info=True)

            sender_id = getattr(event, "get_sender_id", lambda: "")()
            if sender_id:
                return await client.get_entity(int(sender_id)), "当前私聊对象"

        if raw_message is not None:
            get_chat = getattr(raw_message, "get_chat", None)
            if callable(get_chat):
                chat = await get_chat()
                if chat is not None:
                    return chat, "当前会话"

            peer = getattr(raw_message, "peer_id", None)
            if peer is not None:
                return await client.get_entity(peer), "当前会话"

        session_id = getattr(event, "session_id", "")
        if session_id:
            try:
                return await client.get_entity(int(session_id)), "当前会话"
            except Exception:
                logger.debug(
                    "[Telethon] 使用 session_id 解析 profile 目标失败: session_id=%s",
                    session_id,
                    exc_info=True,
                )

        raise ValueError(
            "未找到可查询的目标。可传 @username / 数字 ID / t.me 链接，"
            "也可以直接回复某条消息后再执行 `tg profile`。"
        )

    async def _resolve_reply_entity(self, raw_message: Any) -> Any | None:
        get_reply_message = getattr(raw_message, "get_reply_message", None)
        if not callable(get_reply_message):
            return None
        try:
            reply_message = await get_reply_message()
        except Exception:
            logger.debug("[Telethon] 拉取回复消息失败，跳过 reply 目标解析", exc_info=True)
            return None
        if reply_message is None:
            return None

        get_sender = getattr(reply_message, "get_sender", None)
        if callable(get_sender):
            try:
                sender = await get_sender()
            except Exception:
                logger.debug("[Telethon] 拉取 reply sender 失败", exc_info=True)
            else:
                if sender is not None:
                    return sender

        get_chat = getattr(reply_message, "get_chat", None)
        if callable(get_chat):
            try:
                chat = await get_chat()
            except Exception:
                logger.debug("[Telethon] 拉取 reply chat 失败", exc_info=True)
            else:
                if chat is not None:
                    return chat
        return None

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
                lookup = int(qq) if qq.isdigit() else qq
                return await client.get_entity(lookup)
            except Exception:
                logger.debug("[Telethon] 解析 @ 提及目标失败: qq=%s", qq, exc_info=True)
        return None

    async def _fetch_full_entity(self, client: Any, entity: Any) -> Any | None:
        if client is None or entity is None:
            return None
        try:
            if USER_TYPES and isinstance(entity, USER_TYPES):
                result = await client(functions.users.GetFullUserRequest(entity))
                return getattr(result, "full_user", result)
            if CHAT_TYPES and isinstance(entity, CHAT_TYPES):
                result = await client(functions.messages.GetFullChatRequest(entity.id))
                return getattr(result, "full_chat", result)
            if CHANNEL_TYPES and isinstance(entity, CHANNEL_TYPES):
                result = await client(functions.channels.GetFullChannelRequest(entity))
                return getattr(result, "full_chat", result)
        except Exception:
            logger.warning(
                "[Telethon] 获取完整 profile 失败: entity_type=%s entity_id=%s",
                type(entity).__name__,
                getattr(entity, "id", None),
                exc_info=True,
            )
        return None

    @classmethod
    def _format_profile_text(
        cls,
        resolved: ResolvedProfile,
        detailed: bool = False,
    ) -> str:
        entity = resolved.entity
        full = resolved.full
        lines: list[str] = []

        if USER_TYPES and isinstance(entity, USER_TYPES):
            cls._append_user_lines(lines, entity, full, detailed=detailed)
        elif CHAT_TYPES and isinstance(entity, CHAT_TYPES):
            cls._append_chat_lines(lines, entity, full, detailed=detailed)
        elif CHANNEL_TYPES and isinstance(entity, CHANNEL_TYPES):
            cls._append_channel_lines(lines, entity, full, detailed=detailed)
        else:
            cls._append_field(lines, "类型", cls._entity_kind(entity))
            cls._append_field(lines, "ID", getattr(entity, "id", None))
            cls._append_field(lines, "名称", cls._display_name(entity))
            cls._append_field(lines, "链接", cls._format_entity_link(entity, full))
            cls._append_field(lines, "用户名", getattr(entity, "username", None))
            cls._append_field(lines, "显示名", cls._display_name(entity))
            if detailed:
                cls._append_generic_fields(
                    lines,
                    entity,
                    (
                        ("创建日期", "date"),
                        ("访问哈希", "access_hash"),
                    ),
                )

        return "\n".join(lines).strip()

    @classmethod
    def _append_user_lines(
        cls,
        lines: list[str],
        entity: Any,
        full: Any | None,
        detailed: bool = False,
    ) -> None:
        lines.append("")
        cls._append_field(lines, "类型", "机器人" if getattr(entity, "bot", False) else "用户")
        cls._append_field(lines, "ID", getattr(entity, "id", None))
        cls._append_field(lines, "显示名", cls._display_name(entity))
        cls._append_field(lines, "用户名", cls._primary_username(entity))
        cls._append_field(lines, "链接", cls._format_entity_link(entity, full))
        cls._append_field(lines, "用户名列表", cls._format_usernames(entity))
        cls._append_field(lines, "数据中心", cls._infer_data_center(entity, full))
        cls._append_phone_field(lines, entity)
        cls._append_field(lines, "简介", getattr(full, "about", None))
        cls._append_field(lines, "共同群组数", getattr(full, "common_chats_count", None))
        cls._append_field(lines, "状态", cls._user_status(entity))
        cls._append_flags(
            lines,
            entity,
            (
                ("contact", "联系人"),
                ("mutual_contact", "互相联系人"),
                ("verified", "已认证"),
                ("premium", "高级会员"),
                ("scam", "诈骗风险"),
                ("fake", "伪装账号"),
                ("restricted", "受限"),
                ("support", "官方支持"),
                ("deleted", "已删除"),
            ),
        )
        if detailed:
            cls._append_generic_fields(
                lines,
                entity,
                (
                    ("语言", "lang_code"),
                    ("Emoji 状态", "emoji_status"),
                    ("动态最大 ID", "stories_max_id"),
                    ("机器人活跃用户", "bot_active_users"),
                    ("机器人信息版本", "bot_info_version"),
                    ("Inline 占位文本", "bot_inline_placeholder"),
                    ("付费消息星星数", "send_paid_messages_stars"),
                ),
            )
            cls._append_flags(
                lines,
                entity,
                (
                    ("close_friend", "亲密好友"),
                    ("stories_hidden", "隐藏动态"),
                    ("stories_unavailable", "动态不可用"),
                    ("contact_require_premium", "联系需高级会员"),
                    ("bot_chat_history", "机器人可读历史"),
                    ("bot_nochats", "机器人禁止群聊"),
                    ("bot_inline_geo", "机器人内联地理"),
                    ("bot_attach_menu", "机器人附件菜单"),
                    ("attach_menu_enabled", "附件菜单已启用"),
                    ("bot_can_edit", "机器人可编辑"),
                    ("bot_business", "商业机器人"),
                    ("bot_has_main_app", "机器人主应用"),
                    ("bot_forum_view", "机器人论坛视图"),
                ),
            )
            cls._append_generic_fields(
                lines,
                full,
                (
                    ("已拉黑", "blocked"),
                    ("可语音通话", "phone_calls_available"),
                    ("语音通话私密", "phone_calls_private"),
                    ("可视频通话", "video_calls_available"),
                    ("禁止语音留言", "voice_messages_forbidden"),
                    ("可置顶消息", "can_pin_message"),
                    ("有定时消息", "has_scheduled"),
                    ("禁用翻译", "translations_disabled"),
                    ("动态置顶可用", "stories_pinned_available"),
                    ("屏蔽我的动态", "blocked_my_stories_from"),
                    ("私聊读回执", "read_dates_private"),
                    ("私聊转发名", "private_forward_name"),
                    ("TTL", "ttl_period"),
                    ("置顶消息 ID", "pinned_msg_id"),
                    ("文件夹 ID", "folder_id"),
                    ("个人频道 ID", "personal_channel_id"),
                    ("个人频道消息", "personal_channel_message"),
                    ("生日", "birthday"),
                    ("商业简介", "business_intro"),
                    ("商业位置", "business_location"),
                    ("商业营业时间", "business_work_hours"),
                    ("商业欢迎消息", "business_greeting_message"),
                    ("商业离开消息", "business_away_message"),
                    ("星礼物数量", "stargifts_count"),
                    ("星星评分", "stars_rating"),
                    ("我的待处理星星评分", "stars_my_pending_rating"),
                ),
            )

    @classmethod
    def _append_chat_lines(
        cls,
        lines: list[str],
        entity: Any,
        full: Any | None,
        detailed: bool = False,
    ) -> None:
        lines.append("")
        cls._append_field(lines, "ID", getattr(entity, "id", None))
        cls._append_field(lines, "名称", cls._display_name(entity))
        cls._append_field(lines, "链接", cls._format_entity_link(entity, full))
        cls._append_field(lines, "可见性", cls._entity_visibility(entity, full))
        cls._append_field(lines, "类型", "基础群组")
        cls._append_field(lines, "数据中心", cls._infer_data_center(entity, full))
        cls._append_field(lines, "成员数", getattr(full, "participants_count", None))
        cls._append_field(lines, "在线数", getattr(full, "online_count", None))
        cls._append_field(lines, "管理员数", getattr(full, "admins_count", None))
        cls._append_field(lines, "已踢人数", getattr(full, "kicked_count", None))
        cls._append_field(lines, "已封禁人数", getattr(full, "banned_count", None))
        cls._append_field(lines, "简介", getattr(full, "about", None))
        cls._append_field(lines, "邀请链接", getattr(full, "exported_invite", None))
        cls._append_flags(
            lines,
            entity,
            (
                ("deactivated", "已停用"),
            ),
        )
        if detailed:
            cls._append_flags(
                lines,
                entity,
                (
                    ("call_active", "通话中"),
                    ("call_not_empty", "通话非空"),
                    ("noforwards", "禁止转发"),
                ),
            )
            cls._append_generic_fields(
                lines,
                entity,
                (
                    ("创建日期", "date"),
                    ("版本", "version"),
                    ("迁移到", "migrated_to"),
                    ("默认封禁权限", "default_banned_rights"),
                ),
            )
            cls._append_generic_fields(
                lines,
                full,
                (
                    ("置顶消息 ID", "pinned_msg_id"),
                    ("文件夹 ID", "folder_id"),
                    ("TTL", "ttl_period"),
                    ("主题表情", "theme_emoticon"),
                    ("待处理申请", "requests_pending"),
                    ("最近申请者", "recent_requesters"),
                    ("表情回应", "available_reactions"),
                    ("回应上限", "reactions_limit"),
                    ("可设置用户名", "can_set_username"),
                    ("有定时消息", "has_scheduled"),
                    ("禁用翻译", "translations_disabled"),
                    ("群通话", "call"),
                    ("默认加入身份", "groupcall_default_join_as"),
                ),
            )

    @classmethod
    def _append_channel_lines(
        cls,
        lines: list[str],
        entity: Any,
        full: Any | None,
        detailed: bool = False,
    ) -> None:
        lines.append("")
        cls._append_field(lines, "ID", getattr(entity, "id", None))
        cls._append_field(lines, "名称", cls._display_name(entity))
        cls._append_field(lines, "链接", cls._format_entity_link(entity, full))
        cls._append_field(lines, "可见性", cls._entity_visibility(entity, full))
        cls._append_field(lines, "类型", cls._channel_kind(entity))
        cls._append_field(lines, "数据中心", cls._infer_data_center(entity, full))
        cls._append_field(lines, "简介", getattr(full, "about", None))
        cls._append_field(lines, "成员数", getattr(full, "participants_count", None))
        cls._append_field(lines, "在线数", getattr(full, "online_count", None))
        cls._append_field(lines, "管理员数", getattr(full, "admins_count", None))
        cls._append_field(lines, "已踢人数", getattr(full, "kicked_count", None))
        cls._append_field(lines, "已封禁人数", getattr(full, "banned_count", None))
        cls._append_field(lines, "慢速模式(s)", getattr(full, "slowmode_seconds", None))
        cls._append_field(lines, "讨论组 ID", getattr(full, "linked_chat_id", None))
        cls._append_field(lines, "地理位置", cls._format_location(getattr(full, "location", None)))
        cls._append_field(lines, "邀请链接", getattr(full, "exported_invite", None))
        cls._append_flags(
            lines,
            entity,
            (
                ("verified", "已认证"),
                ("restricted", "受限"),
                ("scam", "诈骗风险"),
                ("fake", "伪装频道"),
            ),
        )
        if detailed:
            cls._append_flags(
                lines,
                entity,
                (
                    ("forum", "论坛"),
                    ("monoforum", "单话题"),
                    ("signatures", "显示签名"),
                    ("has_link", "有公开链接"),
                    ("has_geo", "有地理位置"),
                    ("slowmode_enabled", "启用慢速模式"),
                    ("call_active", "通话中"),
                    ("call_not_empty", "通话非空"),
                    ("noforwards", "禁止转发"),
                    ("join_to_send", "需加入后发言"),
                    ("join_request", "需申请加入"),
                    ("stories_hidden", "隐藏动态"),
                    ("stories_unavailable", "动态不可用"),
                    ("signature_profiles", "签名资料"),
                    ("autotranslation", "自动翻译"),
                    ("broadcast_messages_allowed", "允许频道发言"),
                ),
            )
            cls._append_generic_fields(
                lines,
                entity,
                (
                    ("创建日期", "date"),
                    ("动态最大 ID", "stories_max_id"),
                    ("订阅到期", "subscription_until_date"),
                    ("级别", "level"),
                    ("关联单话题 ID", "linked_monoforum_id"),
                    ("限制原因", "restriction_reason"),
                    ("当前限制规则", "banned_rights"),
                    ("默认成员限制", "default_banned_rights"),
                ),
            )
            cls._append_generic_fields(
                lines,
                full,
                (
                    ("来源群 ID", "migrated_from_chat_id"),
                    ("来源群消息 ID", "migrated_from_max_id"),
                    ("最小可用消息 ID", "available_min_id"),
                    ("文件夹 ID", "folder_id"),
                    ("慢速模式下次发送", "slowmode_next_send_date"),
                    ("TTL", "ttl_period"),
                    ("待处理建议", "pending_suggestions"),
                    ("待处理申请", "requests_pending"),
                    ("最近申请者", "recent_requesters"),
                    ("回应上限", "reactions_limit"),
                    ("已应用助推", "boosts_applied"),
                    ("助推解限", "boosts_unrestrict"),
                    ("星礼物数量", "stargifts_count"),
                    ("付费消息星星数", "send_paid_messages_stars"),
                    ("隐藏历史", "hidden_prehistory"),
                    ("有定时消息", "has_scheduled"),
                    ("已拉黑", "blocked"),
                    ("反垃圾", "antispam"),
                    ("隐藏成员", "participants_hidden"),
                    ("禁用翻译", "translations_disabled"),
                    ("动态置顶可用", "stories_pinned_available"),
                    ("论坛视图为消息", "view_forum_as_messages"),
                    ("限制赞助消息", "restricted_sponsored"),
                    ("可看营收", "can_view_revenue"),
                    ("允许付费媒体", "paid_media_allowed"),
                    ("可看星星营收", "can_view_stars_revenue"),
                    ("允许星礼物", "stargifts_available"),
                    ("允许付费消息", "paid_messages_available"),
                    ("默认发送身份", "default_send_as"),
                    ("表情回应", "available_reactions"),
                    ("主题表情", "theme_emoticon"),
                ),
            )

    @staticmethod
    def _normalize_target(target: str) -> str | int:
        value = str(target or "").strip()
        if not value:
            return ""
        lowered = value.lower()
        if lowered in {"me", "self"}:
            if INPUT_SELF_TYPES:
                return INPUT_SELF_TYPES[0]()
            return "me"
        if lowered.startswith("https://t.me/") or lowered.startswith("http://t.me/"):
            value = value.split("t.me/", 1)[1]
        if lowered.startswith("https://telegram.me/") or lowered.startswith("http://telegram.me/"):
            value = value.split("telegram.me/", 1)[1]
        value = value.strip("/")
        if value.startswith("@"):
            value = value[1:]
        if value.lstrip("-").isdigit():
            return int(value)
        return value

    @staticmethod
    def _entity_kind(entity: Any) -> str:
        if USER_TYPES and isinstance(entity, USER_TYPES):
            return "user"
        if CHAT_TYPES and isinstance(entity, CHAT_TYPES):
            return "group"
        if CHANNEL_TYPES and isinstance(entity, CHANNEL_TYPES):
            return "channel_or_supergroup"
        return type(entity).__name__

    @staticmethod
    def _display_name(entity: Any) -> str | None:
        title = getattr(entity, "title", None)
        if title:
            return str(title)
        first_name = str(getattr(entity, "first_name", "") or "").strip()
        last_name = str(getattr(entity, "last_name", "") or "").strip()
        full_name = " ".join(part for part in [first_name, last_name] if part)
        return full_name or None

    @staticmethod
    def _primary_username(entity: Any) -> str | None:
        username = str(getattr(entity, "username", "") or "").strip()
        if username:
            return f"@{username}"

        for item in getattr(entity, "usernames", None) or []:
            candidate = str(getattr(item, "username", "") or "").strip()
            if candidate:
                return f"@{candidate}"
        return None

    @classmethod
    def _entity_link(cls, entity: Any) -> str | None:
        username = str(getattr(entity, "username", "") or "").strip()
        if not username:
            for item in getattr(entity, "usernames", None) or []:
                candidate = str(getattr(item, "username", "") or "").strip()
                if candidate:
                    username = candidate
                    break
        if username:
            return f"https://t.me/{username}"
        entity_id = getattr(entity, "id", None)
        if entity_id is not None and USER_TYPES and isinstance(entity, USER_TYPES):
            return f"tg://user?id={entity_id}"
        return None

    @classmethod
    def _format_entity_link(cls, entity: Any, full: Any | None = None) -> str | None:
        link = cls._entity_link(entity)
        if link:
            return f'<a href="{html.escape(link, quote=True)}">{html.escape(link)}</a>'
        return None

    @classmethod
    def _entity_visibility(cls, entity: Any, full: Any | None = None) -> str | None:
        if USER_TYPES and isinstance(entity, USER_TYPES):
            return None

        if cls._entity_link(entity):
            return "公开"

        if getattr(full, "exported_invite", None) is not None:
            return "私有"

        if CHAT_TYPES and isinstance(entity, CHAT_TYPES):
            return "私有"

        return None

    @classmethod
    def _format_usernames(cls, entity: Any) -> str | None:
        usernames = getattr(entity, "usernames", None) or []
        values = []
        for item in usernames:
            username = str(getattr(item, "username", "") or "").strip()
            if not username:
                continue
            marker = ""
            if getattr(item, "active", False):
                marker = " (active)"
            values.append(f"@{username}{marker}")
        if not values:
            return None
        primary = cls._primary_username(entity)
        if primary and primary not in values:
            values.insert(0, primary)
        return ", ".join(values)

    @staticmethod
    def _user_status(entity: Any) -> str | None:
        status = getattr(entity, "status", None)
        if status is None:
            return None
        status_name = type(status).__name__
        until = getattr(status, "was_online", None) or getattr(status, "expires", None)
        status_map = {
            "UserStatusOnline": "在线",
            "UserStatusOffline": "离线",
            "UserStatusRecently": "最近活跃",
            "UserStatusLastWeek": "一周内活跃",
            "UserStatusLastMonth": "一月内活跃",
            "UserStatusEmpty": "状态未知",
        }
        display = status_map.get(status_name, status_name)
        if status_name == "UserStatusOffline" and until:
            return f"{display}（最后上线 {TelethonProfileService._format_datetime(until)}）"
        if status_name == "UserStatusOnline" and until:
            return f"{display}（状态有效至 {TelethonProfileService._format_datetime(until)}）"
        return display

    @staticmethod
    def _channel_kind(entity: Any) -> str:
        if getattr(entity, "broadcast", False):
            return "频道"
        if getattr(entity, "gigagroup", False):
            return "广播群组"
        if getattr(entity, "megagroup", False):
            return "超级群组"
        return "频道/群组"

    @staticmethod
    def _format_location(location: Any) -> str | None:
        if location is None:
            return None
        geo = getattr(location, "geo_point", None)
        if geo is None:
            return getattr(location, "address", None)
        lat = getattr(geo, "lat", None)
        lon = getattr(geo, "long", None)
        address = getattr(location, "address", None)
        if lat is None or lon is None:
            return address
        if address:
            return f"{lat},{lon} ({address})"
        return f"{lat},{lon}"

    @staticmethod
    def _format_datetime(value: Any) -> str:
        if isinstance(value, datetime):
            local_value = value
            if value.tzinfo is not None:
                local_value = value.astimezone()
                offset = local_value.strftime("%z")
                if offset:
                    offset = f"UTC{offset[:3]}:{offset[3:]}"
                else:
                    offset = ""
                return (
                    f"{local_value.strftime('%Y-%m-%d %H:%M:%S')} {offset}".rstrip()
                )
            return local_value.strftime("%Y-%m-%d %H:%M:%S")
        return str(value)

    @classmethod
    def _format_invite(cls, invite: Any) -> str | None:
        if invite is None:
            return None

        link = getattr(invite, "link", None)
        if isinstance(link, str) and link.strip():
            parts = ["🙈 已隐藏"]
            detail_parts = []

            title = getattr(invite, "title", None)
            if title:
                detail_parts.append(f"标题={title}")

            if getattr(invite, "permanent", False):
                detail_parts.append("永久")
            if getattr(invite, "revoked", False):
                detail_parts.append("已撤销")
            if getattr(invite, "request_needed", False):
                detail_parts.append("需审核")

            usage = getattr(invite, "usage", None)
            usage_limit = getattr(invite, "usage_limit", None)
            if usage is not None or usage_limit is not None:
                limit_text = usage_limit if usage_limit is not None else "不限"
                detail_parts.append(f"使用次数={usage or 0}/{limit_text}")

            expire_date = getattr(invite, "expire_date", None)
            if expire_date:
                detail_parts.append(f"过期时间={cls._format_datetime(expire_date)}")

            if detail_parts:
                parts.append(f"({' ; '.join(detail_parts)})")
            return " ".join(parts)

        return None

    @classmethod
    def _format_admin_rights(cls, rights: Any) -> str | None:
        if rights is None or type(rights).__name__ != "ChatAdminRights":
            return None
        mappings = (
            ("change_info", "修改资料"),
            ("post_messages", "发布消息"),
            ("edit_messages", "编辑消息"),
            ("delete_messages", "删除消息"),
            ("ban_users", "封禁用户"),
            ("invite_users", "邀请用户"),
            ("pin_messages", "置顶消息"),
            ("add_admins", "添加管理员"),
            ("anonymous", "匿名管理"),
            ("manage_call", "管理通话"),
            ("manage_topics", "管理话题"),
            ("post_stories", "发布动态"),
            ("edit_stories", "编辑动态"),
            ("delete_stories", "删除动态"),
            ("manage_direct_messages", "管理私信"),
        )
        enabled = [label for attr, label in mappings if getattr(rights, attr, False)]
        if getattr(rights, "other", False):
            enabled.append("其它管理权限")
        return "、".join(enabled) if enabled else "无"

    @classmethod
    def _format_banned_rights(cls, rights: Any) -> str | None:
        if rights is None or type(rights).__name__ != "ChatBannedRights":
            return None
        denied_mappings = (
            ("view_messages", "查看消息"),
            ("send_messages", "发送消息"),
            ("send_media", "发送媒体"),
            ("send_stickers", "发送贴纸"),
            ("send_gifs", "发送 GIF"),
            ("send_games", "发送游戏"),
            ("send_inline", "发送内联"),
            ("embed_links", "附带链接预览"),
            ("send_polls", "发送投票"),
            ("change_info", "修改资料"),
            ("invite_users", "邀请用户"),
            ("pin_messages", "置顶消息"),
            ("manage_topics", "管理话题"),
            ("send_photos", "发送图片"),
            ("send_videos", "发送视频"),
            ("send_roundvideos", "发送圆视频"),
            ("send_audios", "发送音频"),
            ("send_voices", "发送语音"),
            ("send_docs", "发送文档"),
            ("send_plain", "发送纯文本"),
        )
        denied = [label for attr, label in denied_mappings if getattr(rights, attr, False)]
        until = getattr(rights, "until_date", None)
        until_text = cls._format_until_date(until)
        if denied:
            return f"{until_text}；限制: {'、'.join(denied)}"
        return until_text

    @classmethod
    def _format_until_date(cls, value: Any) -> str:
        if not value:
            return "未设置时限"
        if isinstance(value, datetime):
            if value.year >= 2038:
                return "长期有效"
            return f"至 {cls._format_datetime(value)}"
        return f"至 {value}"

    @classmethod
    def _format_restriction_reason(cls, value: Any) -> str | None:
        if not isinstance(value, list):
            return None
        parts = []
        for item in value:
            platform = getattr(item, "platform", None)
            reason = getattr(item, "reason", None)
            text = getattr(item, "text", None)
            detail = " / ".join(str(x) for x in [platform, reason, text] if x)
            if detail:
                parts.append(detail)
        return "；".join(parts) if parts else None

    @classmethod
    def _format_chat_reactions(cls, value: Any) -> str | None:
        if value is None:
            return None
        type_name = type(value).__name__
        if type_name == "ChatReactionsNone":
            return "不允许"
        if type_name == "ChatReactionsAll":
            return "允许所有（含自定义）" if getattr(value, "allow_custom", False) else "允许所有"
        if type_name == "ChatReactionsSome":
            reactions = getattr(value, "reactions", None) or []
            parts = []
            for reaction in reactions:
                emoticon = getattr(reaction, "emoticon", None)
                if emoticon:
                    parts.append(str(emoticon))
                    continue
                document_id = getattr(reaction, "document_id", None)
                if document_id is not None:
                    parts.append(f"自定义表情 {document_id}")
            return f"允许部分：{'、'.join(parts)}" if parts else "允许部分"
        return None

    @classmethod
    def _format_emoji_status(cls, value: Any) -> str | None:
        if value is None:
            return None
        type_name = type(value).__name__
        if type_name not in {"EmojiStatus", "EmojiStatusUntil"}:
            return None

        until = getattr(value, "until", None)
        if until:
            return f"有效期至 {cls._format_datetime(until)}"
        if type_name == "EmojiStatus":
            return "长期"
        return "已设置"

    async def _download_profile_photo(
        self,
        client: Any,
        entity: Any,
        full: Any | None = None,
    ) -> str | None:
        if client is None or entity is None:
            return None
        try:
            prefix = f"telethon_profile_{getattr(entity, 'id', 'unknown')}_"
            temp_dir = tempfile.mkdtemp(prefix=prefix)
            path = await client.download_profile_photo(entity, file=temp_dir, download_big=True)
            if isinstance(path, str) and path and os.path.exists(path):
                return self._resize_avatar(path)
        except Exception:
            logger.debug(
                "[Telethon] 下载头像失败: entity_type=%s entity_id=%s",
                type(entity).__name__,
                getattr(entity, "id", None),
                exc_info=True,
            )

        fallback_photo = getattr(full, "chat_photo", None) or getattr(full, "profile_photo", None)
        if fallback_photo is not None:
            try:
                prefix = f"telethon_profile_{getattr(entity, 'id', 'unknown')}_"
                temp_dir = tempfile.mkdtemp(prefix=prefix)
                path = await client.download_media(fallback_photo, file=temp_dir)
                if isinstance(path, str) and path and os.path.exists(path):
                    return self._resize_avatar(path)
            except Exception:
                logger.debug(
                    "[Telethon] 使用 full photo 下载头像失败: entity_type=%s entity_id=%s",
                    type(entity).__name__,
                    getattr(entity, "id", None),
                    exc_info=True,
                )
        return None

    @staticmethod
    def _resize_avatar(path: str) -> str:
        try:
            from PIL import Image
        except Exception:
            return path

        try:
            with Image.open(path) as image:
                width, height = image.size
                image_format = (image.format or "").upper()
                if image_format not in {"JPEG", "JPG", "PNG", "WEBP"}:
                    return path
                if width <= 300 or width <= 0 or height <= 0:
                    return path
                resized_height = max(1, int(height * (300 / width)))
                resized = image.resize((300, resized_height), Image.Resampling.LANCZOS)
                save_kwargs: dict[str, Any] = {}
                if image_format in {"JPEG", "JPG"}:
                    save_kwargs.update({"format": "JPEG", "quality": 95, "subsampling": 0})
                elif image_format == "PNG":
                    save_kwargs.update({"format": "PNG", "compress_level": 1})
                elif image_format == "WEBP":
                    save_kwargs.update({"format": "WEBP", "quality": 95})
                resized.save(path, **save_kwargs)
        except Exception:
            logger.debug("[Telethon] 缩放头像失败: path=%s", path, exc_info=True)
        return path

    @classmethod
    def _stringify_value(cls, value: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, bool):
            return "✅" if value else None
        if isinstance(value, (str, int, float)):
            return value
        if isinstance(value, datetime):
            return cls._format_datetime(value)

        invite_text = cls._format_invite(value)
        if invite_text:
            return invite_text

        admin_rights_text = cls._format_admin_rights(value)
        if admin_rights_text:
            return admin_rights_text

        banned_rights_text = cls._format_banned_rights(value)
        if banned_rights_text:
            return banned_rights_text

        restriction_reason_text = cls._format_restriction_reason(value)
        if restriction_reason_text:
            return restriction_reason_text

        chat_reactions_text = cls._format_chat_reactions(value)
        if chat_reactions_text:
            return chat_reactions_text

        emoji_status_text = cls._format_emoji_status(value)
        if emoji_status_text:
            return emoji_status_text

        username = getattr(value, "username", None)
        if isinstance(username, str) and username.strip():
            return f"@{username.strip()}"

        link = getattr(value, "link", None)
        if isinstance(link, str) and link.strip():
            return link.strip()

        address = getattr(value, "address", None)
        if isinstance(address, str) and address.strip():
            return address.strip()

        title = getattr(value, "title", None)
        if isinstance(title, str) and title.strip():
            return title.strip()

        return str(value)

    @classmethod
    def _append_flags(
        cls,
        lines: list[str],
        entity: Any,
        mappings: tuple[tuple[str, str], ...],
    ) -> None:
        flags = [label for attr, label in mappings if getattr(entity, attr, False)]
        if flags:
            cls._append_field(lines, "标记", "、".join(flags))

    @staticmethod
    def _append_field(lines: list[str], label: str, value: Any) -> None:
        value = TelethonProfileService._stringify_value(value)
        if value is None:
            return
        if isinstance(value, str) and not value.strip():
            return
        if isinstance(value, str) and TelethonProfileService._looks_like_html_value(value):
            lines.append(f"<b>{html.escape(label)}:</b> {value}")
            return
        lines.append(f"<b>{html.escape(label)}:</b> {html.escape(str(value))}")

    @classmethod
    def _append_generic_fields(
        cls,
        lines: list[str],
        source: Any,
        mappings: tuple[tuple[str, str], ...],
    ) -> None:
        if source is None:
            return
        for label, attr in mappings:
            value = getattr(source, attr, None)
            if value is False:
                continue
            if attr == "stats_dc":
                value = cls._format_data_center(value)
            cls._append_field(lines, label, value)

    @classmethod
    def _append_phone_field(cls, lines: list[str], entity: Any) -> None:
        phone = getattr(entity, "phone", None)
        if not phone:
            return
        cls._append_field(lines, "手机号", "🙈 已隐藏")

    @staticmethod
    def _looks_like_html_value(value: str) -> bool:
        return bool(re.search(r"</?(?:a|b|i|u|s|code|pre|blockquote)\b", value, re.IGNORECASE))

    @staticmethod
    def _format_data_center(value: Any) -> str | None:
        return format_data_center(value)

    @classmethod
    def _infer_data_center(cls, entity: Any, full: Any | None = None) -> str | None:
        stats_dc = getattr(full, "stats_dc", None)
        if stats_dc not in (None, False):
            return cls._format_data_center(stats_dc)

        photo = getattr(entity, "photo", None)
        dc_id = getattr(photo, "dc_id", None)
        if dc_id not in (None, False):
            return cls._format_data_center(dc_id)
        return None
