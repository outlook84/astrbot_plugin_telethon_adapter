from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import html
from io import BytesIO
import os
import re
from typing import Any

from astrbot.api import logger
from astrbot.api.message_components import At
from telethon import functions
from telethon.tl import types

from ..i18n import (
    PROFILE_LABELS,
    PROFILE_TOKENS,
    format_data_center_label,
    get_event_language,
    normalize_language,
    t,
)


def _type_tuple(*names: str) -> tuple[type, ...]:
    resolved = [getattr(types, name, None) for name in names]
    return tuple(item for item in resolved if isinstance(item, type))


USER_TYPES = _type_tuple("User")
CHAT_TYPES = _type_tuple("Chat", "ChatForbidden")
CHANNEL_TYPES = _type_tuple("Channel", "ChannelForbidden")
INPUT_SELF_TYPES = _type_tuple("InputPeerSelf")

PROFILE_FIELD_LABEL_KEYS = {
    "type": "类型",
    "id": "ID",
    "name": "名称",
    "link": "链接",
    "username": "用户名",
    "display_name": "显示名",
    "username_list": "用户名列表",
    "data_center": "数据中心",
    "phone": "手机号",
    "bio": "简介",
    "common_chats": "共同群组数",
    "status": "状态",
    "flags": "标记",
    "language": "语言",
    "emoji_status": "Emoji 状态",
    "stories_max_id": "动态最大 ID",
    "bot_active_users": "机器人活跃用户",
    "bot_info_version": "机器人信息版本",
    "bot_inline_placeholder": "Inline 占位文本",
    "paid_message_stars": "付费消息星星数",
    "blocked": "已拉黑",
    "phone_calls_available": "可语音通话",
    "phone_calls_private": "语音通话私密",
    "video_calls_available": "可视频通话",
    "voice_messages_forbidden": "禁止语音留言",
    "can_pin_message": "可置顶消息",
    "has_scheduled": "有定时消息",
    "translations_disabled": "禁用翻译",
    "stories_pinned_available": "动态置顶可用",
    "blocked_my_stories_from": "屏蔽我的动态",
    "read_dates_private": "私聊读回执",
    "private_forward_name": "私聊转发名",
    "ttl": "TTL",
    "pinned_msg_id": "置顶消息 ID",
    "folder_id": "文件夹 ID",
    "personal_channel_id": "个人频道 ID",
    "personal_channel_message": "个人频道消息",
    "birthday": "生日",
    "business_intro": "商业简介",
    "business_location": "商业位置",
    "business_work_hours": "商业营业时间",
    "business_greeting_message": "商业欢迎消息",
    "business_away_message": "商业离开消息",
    "stargifts_count": "星礼物数量",
    "stars_rating": "星星评分",
    "stars_my_pending_rating": "我的待处理星星评分",
    "visibility": "可见性",
    "members": "成员数",
    "online": "在线数",
    "admins": "管理员数",
    "kicked": "已踢人数",
    "banned": "已封禁人数",
    "invite_link": "邀请链接",
    "created_at": "创建日期",
    "version": "版本",
    "migrated_to": "迁移到",
    "default_banned_rights": "默认封禁权限",
    "theme_emoticon": "主题表情",
    "pending_requests": "待处理申请",
    "recent_requesters": "最近申请者",
    "available_reactions": "表情回应",
    "reactions_limit": "回应上限",
    "can_set_username": "可设置用户名",
    "call": "群通话",
    "groupcall_default_join_as": "默认加入身份",
    "slowmode_seconds": "慢速模式(s)",
    "linked_chat_id": "讨论组 ID",
    "location": "地理位置",
    "subscription_until_date": "订阅到期",
    "level": "级别",
    "linked_monoforum_id": "关联单话题 ID",
    "restriction_reason": "限制原因",
    "banned_rights": "当前限制规则",
    "source_chat_id": "来源群 ID",
    "source_chat_message_id": "来源群消息 ID",
    "available_min_id": "最小可用消息 ID",
    "slowmode_next_send_date": "慢速模式下次发送",
    "pending_suggestions": "待处理建议",
    "boosts_applied": "已应用助推",
    "boosts_unrestrict": "助推解限",
    "hidden_prehistory": "隐藏历史",
    "antispam": "反垃圾",
    "participants_hidden": "隐藏成员",
    "view_forum_as_messages": "论坛视图为消息",
    "restricted_sponsored": "限制赞助消息",
    "can_view_revenue": "可看营收",
    "paid_media_allowed": "允许付费媒体",
    "can_view_stars_revenue": "可看星星营收",
    "stargifts_available": "允许星礼物",
    "paid_messages_available": "允许付费消息",
    "default_send_as": "默认发送身份",
    "access_hash": "访问哈希",
}


@dataclass(slots=True)
class ResolvedProfile:
    entity: Any
    full: Any | None
    source: str


@dataclass(slots=True)
class ProfilePayload:
    text: str
    avatar_file: BytesIO | None = None


class TelethonProfileService:
    @staticmethod
    def _profile_label(key: str, language: str) -> str:
        zh_label = PROFILE_FIELD_LABEL_KEYS.get(key, key)
        if normalize_language(language) == "en-US":
            return PROFILE_LABELS.get(zh_label, zh_label)
        return zh_label

    @staticmethod
    def _profile_token(text: str, language: str) -> str:
        if normalize_language(language) == "en-US":
            return PROFILE_TOKENS.get(text, text)
        return text

    @classmethod
    def _profile_join(cls, items: list[str], language: str) -> str:
        separator = ", " if normalize_language(language) == "en-US" else "、"
        return separator.join(items)

    @staticmethod
    def supports_event(event: Any) -> bool:
        client = getattr(event, "client", None)
        if client is None:
            logger.debug("[Telethon] supports_event: client missing")
            return False

        platform_name = str(getattr(getattr(event, "platform_meta", None), "name", "") or "")
        raw_message = getattr(getattr(event, "message_obj", None), "raw_message", None)
        result = False
        if platform_name == "telethon_userbot" and raw_message is not None:
            result = True
        elif raw_message is not None and raw_message.__class__.__module__.startswith("telethon"):
            result = True
        else:
            result = hasattr(raw_message, "get_reply_message") or hasattr(raw_message, "peer_id")

        logger.debug(
            "[Telethon] supports_event: result=%s platform_name=%s raw_message_type=%s has_reply=%s has_peer=%s",
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
            raise ValueError(t(event, "profile.client_missing"))

        resolved = await self._resolve_profile(event, target)
        language = get_event_language(event)
        avatar_file = await self._download_profile_photo(
            client,
            resolved.entity,
            resolved.full,
        )
        return ProfilePayload(
            text=self._format_profile_text(
                resolved,
                detailed=detailed,
                language=language,
            ),
            avatar_file=avatar_file,
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
                        logger.debug("[Telethon] Failed to fetch private chat peer", exc_info=True)
                    else:
                        if chat is not None:
                            return chat, "当前私聊对象"

                peer = getattr(raw_message, "peer_id", None)
                if peer is not None:
                    try:
                        return await client.get_entity(peer), "当前私聊对象"
                    except Exception:
                        logger.debug("[Telethon] Failed to resolve private chat peer via peer_id", exc_info=True)

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
                peer_id = self._session_peer_id(session_id)
                if peer_id is not None:
                    return await client.get_entity(peer_id), "当前会话"
            except Exception:
                logger.debug(
                    "[Telethon] Failed to resolve profile target via session_id: session_id=%s",
                    session_id,
                    exc_info=True,
                )

        raise ValueError(t(event, "profile.resolve_failed"))

    @staticmethod
    def _session_peer_id(session_id: Any) -> int | None:
        normalized = str(session_id or "").strip()
        if not normalized:
            return None
        peer_part = normalized.split("#", 1)[0].strip()
        if not peer_part:
            return None
        try:
            return int(peer_part)
        except (TypeError, ValueError):
            return None

    async def _resolve_reply_entity(self, raw_message: Any) -> Any | None:
        get_reply_message = getattr(raw_message, "get_reply_message", None)
        if not callable(get_reply_message):
            return None
        try:
            reply_message = await get_reply_message()
        except Exception:
            logger.debug("[Telethon] Failed to fetch replied message; skipping reply target resolution", exc_info=True)
            return None
        if reply_message is None:
            return None

        get_sender = getattr(reply_message, "get_sender", None)
        if callable(get_sender):
            try:
                sender = await get_sender()
            except Exception:
                logger.debug("[Telethon] Failed to fetch reply sender", exc_info=True)
            else:
                if sender is not None:
                    return sender

        get_chat = getattr(reply_message, "get_chat", None)
        if callable(get_chat):
            try:
                chat = await get_chat()
            except Exception:
                logger.debug("[Telethon] Failed to fetch reply chat", exc_info=True)
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
                logger.debug("[Telethon] Failed to resolve @mention target: qq=%s", qq, exc_info=True)
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
                "[Telethon] Failed to fetch full profile: entity_type=%s entity_id=%s",
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
        language: str = "zh-CN",
    ) -> str:
        entity = resolved.entity
        full = resolved.full
        lines: list[str] = []

        if USER_TYPES and isinstance(entity, USER_TYPES):
            cls._append_user_lines(lines, entity, full, detailed=detailed, language=language)
        elif CHAT_TYPES and isinstance(entity, CHAT_TYPES):
            cls._append_chat_lines(lines, entity, full, detailed=detailed, language=language)
        elif CHANNEL_TYPES and isinstance(entity, CHANNEL_TYPES):
            cls._append_channel_lines(lines, entity, full, detailed=detailed, language=language)
        else:
            cls._append_field(lines, "type", cls._entity_kind(entity), language)
            cls._append_field(lines, "id", getattr(entity, "id", None), language)
            cls._append_field(lines, "name", cls._display_name(entity), language)
            cls._append_field(lines, "link", cls._format_entity_link(entity, full), language)
            cls._append_field(lines, "username", getattr(entity, "username", None), language)
            cls._append_field(lines, "display_name", cls._display_name(entity), language)
            if detailed:
                cls._append_generic_fields(
                    lines,
                    entity,
                    (
                        ("created_at", "date"),
                        ("access_hash", "access_hash"),
                    ),
                    language,
                )

        return "\n".join(lines).strip()

    @classmethod
    def _append_user_lines(
        cls,
        lines: list[str],
        entity: Any,
        full: Any | None,
        detailed: bool = False,
        language: str = "zh-CN",
    ) -> None:
        lines.append("")
        cls._append_field(
            lines,
            "type",
            cls._profile_token("机器人" if getattr(entity, "bot", False) else "用户", language),
            language,
        )
        cls._append_field(lines, "id", getattr(entity, "id", None), language)
        cls._append_field(lines, "display_name", cls._display_name(entity), language)
        cls._append_field(lines, "username", cls._primary_username(entity), language)
        cls._append_field(lines, "link", cls._format_entity_link(entity, full), language)
        cls._append_field(lines, "username_list", cls._format_usernames(entity), language)
        cls._append_field(lines, "data_center", cls._infer_data_center(entity, full, language), language)
        cls._append_phone_field(lines, entity, language)
        cls._append_field(lines, "bio", getattr(full, "about", None), language)
        cls._append_field(lines, "common_chats", getattr(full, "common_chats_count", None), language)
        cls._append_field(lines, "status", cls._user_status(entity, language), language)
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
            language,
        )
        if detailed:
            cls._append_generic_fields(
                lines,
                entity,
                (
                    ("language", "lang_code"),
                    ("emoji_status", "emoji_status"),
                    ("stories_max_id", "stories_max_id"),
                    ("bot_active_users", "bot_active_users"),
                    ("bot_info_version", "bot_info_version"),
                    ("bot_inline_placeholder", "bot_inline_placeholder"),
                    ("paid_message_stars", "send_paid_messages_stars"),
                ),
                language,
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
                language,
            )
            cls._append_generic_fields(
                lines,
                full,
                (
                    ("blocked", "blocked"),
                    ("phone_calls_available", "phone_calls_available"),
                    ("phone_calls_private", "phone_calls_private"),
                    ("video_calls_available", "video_calls_available"),
                    ("voice_messages_forbidden", "voice_messages_forbidden"),
                    ("can_pin_message", "can_pin_message"),
                    ("has_scheduled", "has_scheduled"),
                    ("translations_disabled", "translations_disabled"),
                    ("stories_pinned_available", "stories_pinned_available"),
                    ("blocked_my_stories_from", "blocked_my_stories_from"),
                    ("read_dates_private", "read_dates_private"),
                    ("private_forward_name", "private_forward_name"),
                    ("ttl", "ttl_period"),
                    ("pinned_msg_id", "pinned_msg_id"),
                    ("folder_id", "folder_id"),
                    ("personal_channel_id", "personal_channel_id"),
                    ("personal_channel_message", "personal_channel_message"),
                    ("birthday", "birthday"),
                    ("business_intro", "business_intro"),
                    ("business_location", "business_location"),
                    ("business_work_hours", "business_work_hours"),
                    ("business_greeting_message", "business_greeting_message"),
                    ("business_away_message", "business_away_message"),
                    ("stargifts_count", "stargifts_count"),
                    ("stars_rating", "stars_rating"),
                    ("stars_my_pending_rating", "stars_my_pending_rating"),
                ),
                language,
            )

    @classmethod
    def _append_chat_lines(
        cls,
        lines: list[str],
        entity: Any,
        full: Any | None,
        detailed: bool = False,
        language: str = "zh-CN",
    ) -> None:
        lines.append("")
        cls._append_field(lines, "id", getattr(entity, "id", None), language)
        cls._append_field(lines, "name", cls._display_name(entity), language)
        cls._append_field(lines, "link", cls._format_entity_link(entity, full), language)
        cls._append_field(lines, "visibility", cls._entity_visibility(entity, full, language), language)
        cls._append_field(lines, "type", cls._profile_token("基础群组", language), language)
        cls._append_field(lines, "data_center", cls._infer_data_center(entity, full, language), language)
        cls._append_field(lines, "members", getattr(full, "participants_count", None), language)
        cls._append_field(lines, "online", getattr(full, "online_count", None), language)
        cls._append_field(lines, "admins", getattr(full, "admins_count", None), language)
        cls._append_field(lines, "kicked", getattr(full, "kicked_count", None), language)
        cls._append_field(lines, "banned", getattr(full, "banned_count", None), language)
        cls._append_field(lines, "bio", getattr(full, "about", None), language)
        cls._append_field(lines, "invite_link", getattr(full, "exported_invite", None), language)
        cls._append_flags(
            lines,
            entity,
            (
                ("deactivated", "已停用"),
            ),
            language,
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
                language,
            )
            cls._append_generic_fields(
                lines,
                entity,
                (
                    ("created_at", "date"),
                    ("version", "version"),
                    ("migrated_to", "migrated_to"),
                    ("default_banned_rights", "default_banned_rights"),
                ),
                language,
            )
            cls._append_generic_fields(
                lines,
                full,
                (
                    ("pinned_msg_id", "pinned_msg_id"),
                    ("folder_id", "folder_id"),
                    ("ttl", "ttl_period"),
                    ("theme_emoticon", "theme_emoticon"),
                    ("pending_requests", "requests_pending"),
                    ("recent_requesters", "recent_requesters"),
                    ("available_reactions", "available_reactions"),
                    ("reactions_limit", "reactions_limit"),
                    ("can_set_username", "can_set_username"),
                    ("has_scheduled", "has_scheduled"),
                    ("translations_disabled", "translations_disabled"),
                    ("call", "call"),
                    ("groupcall_default_join_as", "groupcall_default_join_as"),
                ),
                language,
            )

    @classmethod
    def _append_channel_lines(
        cls,
        lines: list[str],
        entity: Any,
        full: Any | None,
        detailed: bool = False,
        language: str = "zh-CN",
    ) -> None:
        lines.append("")
        cls._append_field(lines, "id", getattr(entity, "id", None), language)
        cls._append_field(lines, "name", cls._display_name(entity), language)
        cls._append_field(lines, "link", cls._format_entity_link(entity, full), language)
        cls._append_field(lines, "visibility", cls._entity_visibility(entity, full, language), language)
        cls._append_field(lines, "type", cls._channel_kind(entity, language), language)
        cls._append_field(lines, "data_center", cls._infer_data_center(entity, full, language), language)
        cls._append_field(lines, "bio", getattr(full, "about", None), language)
        cls._append_field(lines, "members", getattr(full, "participants_count", None), language)
        cls._append_field(lines, "online", getattr(full, "online_count", None), language)
        cls._append_field(lines, "admins", getattr(full, "admins_count", None), language)
        cls._append_field(lines, "kicked", getattr(full, "kicked_count", None), language)
        cls._append_field(lines, "banned", getattr(full, "banned_count", None), language)
        cls._append_field(lines, "slowmode_seconds", getattr(full, "slowmode_seconds", None), language)
        cls._append_field(lines, "linked_chat_id", getattr(full, "linked_chat_id", None), language)
        cls._append_field(lines, "location", cls._format_location(getattr(full, "location", None)), language)
        cls._append_field(lines, "invite_link", getattr(full, "exported_invite", None), language)
        cls._append_flags(
            lines,
            entity,
            (
                ("verified", "已认证"),
                ("restricted", "受限"),
                ("scam", "诈骗风险"),
                ("fake", "伪装频道"),
            ),
            language,
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
                language,
            )
            cls._append_generic_fields(
                lines,
                entity,
                (
                    ("created_at", "date"),
                    ("stories_max_id", "stories_max_id"),
                    ("subscription_until_date", "subscription_until_date"),
                    ("level", "level"),
                    ("linked_monoforum_id", "linked_monoforum_id"),
                    ("restriction_reason", "restriction_reason"),
                    ("banned_rights", "banned_rights"),
                    ("default_banned_rights", "default_banned_rights"),
                ),
                language,
            )
            cls._append_generic_fields(
                lines,
                full,
                (
                    ("source_chat_id", "migrated_from_chat_id"),
                    ("source_chat_message_id", "migrated_from_max_id"),
                    ("available_min_id", "available_min_id"),
                    ("folder_id", "folder_id"),
                    ("slowmode_next_send_date", "slowmode_next_send_date"),
                    ("ttl", "ttl_period"),
                    ("pending_suggestions", "pending_suggestions"),
                    ("pending_requests", "requests_pending"),
                    ("recent_requesters", "recent_requesters"),
                    ("reactions_limit", "reactions_limit"),
                    ("boosts_applied", "boosts_applied"),
                    ("boosts_unrestrict", "boosts_unrestrict"),
                    ("stargifts_count", "stargifts_count"),
                    ("paid_message_stars", "send_paid_messages_stars"),
                    ("hidden_prehistory", "hidden_prehistory"),
                    ("has_scheduled", "has_scheduled"),
                    ("blocked", "blocked"),
                    ("antispam", "antispam"),
                    ("participants_hidden", "participants_hidden"),
                    ("translations_disabled", "translations_disabled"),
                    ("stories_pinned_available", "stories_pinned_available"),
                    ("view_forum_as_messages", "view_forum_as_messages"),
                    ("restricted_sponsored", "restricted_sponsored"),
                    ("can_view_revenue", "can_view_revenue"),
                    ("paid_media_allowed", "paid_media_allowed"),
                    ("can_view_stars_revenue", "can_view_stars_revenue"),
                    ("stargifts_available", "stargifts_available"),
                    ("paid_messages_available", "paid_messages_available"),
                    ("default_send_as", "default_send_as"),
                    ("available_reactions", "available_reactions"),
                    ("theme_emoticon", "theme_emoticon"),
                ),
                language,
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
    def _entity_visibility(
        cls,
        entity: Any,
        full: Any | None = None,
        language: str = "zh-CN",
    ) -> str | None:
        if USER_TYPES and isinstance(entity, USER_TYPES):
            return None

        if cls._entity_link(entity):
            return cls._profile_token("公开", language)

        if getattr(full, "exported_invite", None) is not None:
            return cls._profile_token("私有", language)

        if CHAT_TYPES and isinstance(entity, CHAT_TYPES):
            return cls._profile_token("私有", language)

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
    def _user_status(entity: Any, language: str = "zh-CN") -> str | None:
        status = getattr(entity, "status", None)
        if status is None:
            return None
        status_name = type(status).__name__
        until = getattr(status, "was_online", None) or getattr(status, "expires", None)
        status_map = {
            "UserStatusOnline": TelethonProfileService._profile_token("在线", language),
            "UserStatusOffline": TelethonProfileService._profile_token("离线", language),
            "UserStatusRecently": TelethonProfileService._profile_token("最近活跃", language),
            "UserStatusLastWeek": TelethonProfileService._profile_token("一周内活跃", language),
            "UserStatusLastMonth": TelethonProfileService._profile_token("一月内活跃", language),
            "UserStatusEmpty": TelethonProfileService._profile_token("状态未知", language),
        }
        display = status_map.get(status_name, status_name)
        if status_name == "UserStatusOffline" and until:
            if normalize_language(language) == "en-US":
                return f"{display} (last seen {TelethonProfileService._format_datetime(until)})"
            return f"{display}（最后上线 {TelethonProfileService._format_datetime(until)}）"
        if status_name == "UserStatusOnline" and until:
            if normalize_language(language) == "en-US":
                return f"{display} (valid until {TelethonProfileService._format_datetime(until)})"
            return f"{display}（状态有效至 {TelethonProfileService._format_datetime(until)}）"
        return display

    @classmethod
    def _channel_kind(cls, entity: Any, language: str = "zh-CN") -> str:
        if getattr(entity, "broadcast", False):
            return cls._profile_token("频道", language)
        if getattr(entity, "gigagroup", False):
            return cls._profile_token("广播群组", language)
        if getattr(entity, "megagroup", False):
            return cls._profile_token("超级群组", language)
        return cls._profile_token("频道/群组", language)

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
    def _format_invite(cls, invite: Any, language: str = "zh-CN") -> str | None:
        if invite is None:
            return None

        link = getattr(invite, "link", None)
        if isinstance(link, str) and link.strip():
            parts = [cls._profile_token("🙈 已隐藏", language)]
            detail_parts = []

            title = getattr(invite, "title", None)
            if title:
                prefix = cls._profile_token("标题=", language)
                detail_parts.append(f"{prefix}{title}")

            if getattr(invite, "permanent", False):
                detail_parts.append(cls._profile_token("永久", language))
            if getattr(invite, "revoked", False):
                detail_parts.append(cls._profile_token("已撤销", language))
            if getattr(invite, "request_needed", False):
                detail_parts.append(cls._profile_token("需审核", language))

            usage = getattr(invite, "usage", None)
            usage_limit = getattr(invite, "usage_limit", None)
            if usage is not None or usage_limit is not None:
                limit_text = usage_limit if usage_limit is not None else cls._profile_token("不限", language)
                detail_parts.append(
                    f"{cls._profile_token('使用次数=', language)}{usage or 0}/{limit_text}"
                )

            expire_date = getattr(invite, "expire_date", None)
            if expire_date:
                detail_parts.append(
                    f"{cls._profile_token('过期时间=', language)}{cls._format_datetime(expire_date)}"
                )

            if detail_parts:
                parts.append(f"({' ; '.join(detail_parts)})")
            return " ".join(parts)

        return None

    @classmethod
    def _format_admin_rights(cls, rights: Any, language: str = "zh-CN") -> str | None:
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
        enabled = [
            cls._profile_token(label, language)
            for attr, label in mappings
            if getattr(rights, attr, False)
        ]
        if getattr(rights, "other", False):
            enabled.append(cls._profile_token("其它管理权限", language))
        return cls._profile_join(enabled, language) if enabled else cls._profile_token("无", language)

    @classmethod
    def _format_banned_rights(cls, rights: Any, language: str = "zh-CN") -> str | None:
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
        denied = [
            cls._profile_token(label, language)
            for attr, label in denied_mappings
            if getattr(rights, attr, False)
        ]
        until = getattr(rights, "until_date", None)
        until_text = cls._format_until_date(until, language)
        if denied:
            if normalize_language(language) == "en-US":
                return f"{until_text}; Restrictions: {cls._profile_join(denied, language)}"
            return f"{until_text}；限制: {cls._profile_join(denied, language)}"
        return until_text

    @classmethod
    def _format_until_date(cls, value: Any, language: str = "zh-CN") -> str:
        if not value:
            return cls._profile_token("未设置时限", language)
        if isinstance(value, datetime):
            if value.year >= 2038:
                return cls._profile_token("长期有效", language)
            return f"{cls._profile_token('至 ', language)}{cls._format_datetime(value)}"
        return f"{cls._profile_token('至 ', language)}{value}"

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
    def _format_chat_reactions(cls, value: Any, language: str = "zh-CN") -> str | None:
        if value is None:
            return None
        type_name = type(value).__name__
        if type_name == "ChatReactionsNone":
            return cls._profile_token("不允许", language)
        if type_name == "ChatReactionsAll":
            return (
                cls._profile_token("允许所有（含自定义）", language)
                if getattr(value, "allow_custom", False)
                else cls._profile_token("允许所有", language)
            )
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
                    parts.append(f"{cls._profile_token('自定义表情 ', language)}{document_id}")
            if parts:
                return f"{cls._profile_token('允许部分：', language)}{cls._profile_join(parts, language)}"
            return cls._profile_token("允许部分", language)
        return None

    @classmethod
    def _format_emoji_status(cls, value: Any, language: str = "zh-CN") -> str | None:
        if value is None:
            return None
        type_name = type(value).__name__
        if type_name not in {"EmojiStatus", "EmojiStatusUntil"}:
            return None

        until = getattr(value, "until", None)
        if until:
            return f"{cls._profile_token('有效期至 ', language)}{cls._format_datetime(until)}"
        if type_name == "EmojiStatus":
            return cls._profile_token("长期", language)
        return cls._profile_token("已设置", language)

    async def _download_profile_photo(
        self,
        client: Any,
        entity: Any,
        full: Any | None = None,
    ) -> BytesIO | None:
        if client is None or entity is None:
            return None
        try:
            raw = await client.download_profile_photo(entity, file=BytesIO(), download_big=True)
            stream = self._normalize_avatar_stream(raw, entity)
            if stream is not None:
                return self._resize_avatar(stream, entity)
        except Exception:
            logger.debug(
                "[Telethon] Failed to download avatar: entity_type=%s entity_id=%s",
                type(entity).__name__,
                getattr(entity, "id", None),
                exc_info=True,
            )

        fallback_photo = getattr(full, "chat_photo", None) or getattr(full, "profile_photo", None)
        if fallback_photo is not None:
            try:
                raw = await client.download_media(fallback_photo, file=BytesIO())
                stream = self._normalize_avatar_stream(raw, entity)
                if stream is not None:
                    return self._resize_avatar(stream, entity)
            except Exception:
                logger.debug(
                    "[Telethon] Failed to download avatar via full photo: entity_type=%s entity_id=%s",
                    type(entity).__name__,
                    getattr(entity, "id", None),
                    exc_info=True,
                )
        return None

    @staticmethod
    def _avatar_filename(entity: Any, extension: str = ".jpg") -> str:
        entity_id = getattr(entity, "id", "unknown")
        safe_extension = extension if extension.startswith(".") else f".{extension}"
        return f"telethon_profile_{entity_id}{safe_extension}"

    @classmethod
    def _normalize_avatar_stream(cls, raw: Any, entity: Any) -> BytesIO | None:
        if raw is None:
            return None
        if isinstance(raw, BytesIO):
            stream = raw
        elif isinstance(raw, (bytes, bytearray, memoryview)):
            stream = BytesIO(bytes(raw))
        elif hasattr(raw, "read"):
            try:
                if hasattr(raw, "seek"):
                    raw.seek(0)
                stream = BytesIO(raw.read())
            except Exception:
                return None
        else:
            return None
        stream.seek(0)
        if not getattr(stream, "name", None):
            stream.name = cls._avatar_filename(entity)
        return stream

    @classmethod
    def _resize_avatar(cls, stream: BytesIO, entity: Any) -> BytesIO:
        try:
            from PIL import Image
        except Exception:
            stream.seek(0)
            return stream

        try:
            stream.seek(0)
            with Image.open(stream) as image:
                width, height = image.size
                image_format = (image.format or "").upper()
                if image_format not in {"JPEG", "JPG", "PNG", "WEBP"}:
                    stream.seek(0)
                    return stream
                if width <= 300 or width <= 0 or height <= 0:
                    stream.name = cls._avatar_filename(entity, cls._image_extension(image_format))
                    stream.seek(0)
                    return stream
                resized_height = max(1, int(height * (300 / width)))
                resized = image.resize((300, resized_height), Image.Resampling.LANCZOS)
                save_kwargs: dict[str, Any] = {}
                if image_format in {"JPEG", "JPG"}:
                    save_kwargs.update({"format": "JPEG", "quality": 95, "subsampling": 0})
                elif image_format == "PNG":
                    save_kwargs.update({"format": "PNG", "compress_level": 1})
                elif image_format == "WEBP":
                    save_kwargs.update({"format": "WEBP", "quality": 95})
                output = BytesIO()
                output.name = cls._avatar_filename(entity, cls._image_extension(image_format))
                resized.save(output, **save_kwargs)
                output.seek(0)
                return output
        except Exception:
            logger.debug(
                "[Telethon] Failed to resize avatar: entity_type=%s entity_id=%s",
                type(entity).__name__,
                getattr(entity, "id", None),
                exc_info=True,
            )
        stream.seek(0)
        return stream

    @staticmethod
    def _image_extension(image_format: str) -> str:
        normalized = str(image_format or "").upper()
        if normalized in {"JPEG", "JPG"}:
            return ".jpg"
        if normalized == "PNG":
            return ".png"
        if normalized == "WEBP":
            return ".webp"
        return ".jpg"

    @classmethod
    def _stringify_value(cls, value: Any, language: str = "zh-CN") -> Any:
        if value is None:
            return None
        if isinstance(value, bool):
            return "✅" if value else None
        if isinstance(value, (str, int, float)):
            return value
        if isinstance(value, datetime):
            return cls._format_datetime(value)

        invite_text = cls._format_invite(value, language)
        if invite_text:
            return invite_text

        admin_rights_text = cls._format_admin_rights(value, language)
        if admin_rights_text:
            return admin_rights_text

        banned_rights_text = cls._format_banned_rights(value, language)
        if banned_rights_text:
            return banned_rights_text

        restriction_reason_text = cls._format_restriction_reason(value)
        if restriction_reason_text:
            return restriction_reason_text

        chat_reactions_text = cls._format_chat_reactions(value, language)
        if chat_reactions_text:
            return chat_reactions_text

        emoji_status_text = cls._format_emoji_status(value, language)
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
        language: str,
    ) -> None:
        flags = [
            cls._profile_token(label, language)
            for attr, label in mappings
            if getattr(entity, attr, False)
        ]
        if flags:
            cls._append_field(lines, "flags", cls._profile_join(flags, language), language)

    @classmethod
    def _append_field(cls, lines: list[str], label_key: str, value: Any, language: str) -> None:
        value = TelethonProfileService._stringify_value(value, language)
        if value is None:
            return
        if isinstance(value, str) and not value.strip():
            return
        label = cls._profile_label(label_key, language)
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
        language: str,
    ) -> None:
        if source is None:
            return
        for label_key, attr in mappings:
            value = getattr(source, attr, None)
            if value is False:
                continue
            if attr == "stats_dc":
                value = cls._format_data_center(value, language)
            cls._append_field(lines, label_key, value, language)

    @classmethod
    def _append_phone_field(cls, lines: list[str], entity: Any, language: str) -> None:
        phone = getattr(entity, "phone", None)
        if not phone:
            return
        cls._append_field(lines, "phone", cls._profile_token("🙈 已隐藏", language), language)

    @staticmethod
    def _looks_like_html_value(value: str) -> bool:
        return bool(re.search(r"</?(?:a|b|i|u|s|code|pre|blockquote)\b", value, re.IGNORECASE))

    @staticmethod
    def _format_data_center(value: Any, language: str = "zh-CN") -> str | None:
        return format_data_center_label(value, language)

    @classmethod
    def _infer_data_center(
        cls,
        entity: Any,
        full: Any | None = None,
        language: str = "zh-CN",
    ) -> str | None:
        stats_dc = getattr(full, "stats_dc", None)
        if stats_dc not in (None, False):
            return cls._format_data_center(stats_dc, language)

        photo = getattr(entity, "photo", None)
        dc_id = getattr(photo, "dc_id", None)
        if dc_id not in (None, False):
            return cls._format_data_center(dc_id, language)
        return None
