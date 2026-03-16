import importlib.util
import sys
import types
import unittest
from datetime import datetime, timezone
from pathlib import Path


def _install_astrbot_stubs() -> None:
    astrbot_module = types.ModuleType("astrbot")
    api_module = types.ModuleType("astrbot.api")
    message_components_module = types.ModuleType("astrbot.api.message_components")

    class _Logger:
        def debug(self, *args, **kwargs):
            return None

        def warning(self, *args, **kwargs):
            return None

        def exception(self, *args, **kwargs):
            return None

    class At:
        def __init__(self, qq, name=""):
            self.qq = qq
            self.name = name

    api_module.logger = _Logger()
    message_components_module.At = At

    sys.modules["astrbot"] = astrbot_module
    sys.modules["astrbot.api"] = api_module
    sys.modules["astrbot.api.message_components"] = message_components_module


def _install_telethon_stubs() -> None:
    telethon_module = types.ModuleType("telethon")
    functions_module = types.ModuleType("telethon.functions")
    users_module = types.ModuleType("telethon.functions.users")
    messages_module = types.ModuleType("telethon.functions.messages")
    channels_module = types.ModuleType("telethon.functions.channels")
    tl_module = types.ModuleType("telethon.tl")
    tl_types_module = types.ModuleType("telethon.tl.types")

    class User:
        def __init__(self, **kwargs):
            for key, value in kwargs.items():
                setattr(self, key, value)

    class Chat:
        def __init__(self, **kwargs):
            for key, value in kwargs.items():
                setattr(self, key, value)

    class Channel:
        def __init__(self, **kwargs):
            for key, value in kwargs.items():
                setattr(self, key, value)

    class InputPeerSelf:
        pass

    class GetFullUserRequest:
        def __init__(self, entity):
            self.entity = entity

    class GetFullChatRequest:
        def __init__(self, chat_id):
            self.chat_id = chat_id

    class GetFullChannelRequest:
        def __init__(self, entity):
            self.entity = entity

    tl_types_module.User = User
    tl_types_module.Chat = Chat
    tl_types_module.Channel = Channel
    tl_types_module.InputPeerSelf = InputPeerSelf
    users_module.GetFullUserRequest = GetFullUserRequest
    messages_module.GetFullChatRequest = GetFullChatRequest
    channels_module.GetFullChannelRequest = GetFullChannelRequest
    functions_module.users = users_module
    functions_module.messages = messages_module
    functions_module.channels = channels_module

    sys.modules["telethon"] = telethon_module
    sys.modules["telethon.functions"] = functions_module
    sys.modules["telethon.functions.users"] = users_module
    sys.modules["telethon.functions.messages"] = messages_module
    sys.modules["telethon.functions.channels"] = channels_module
    sys.modules["telethon.tl"] = tl_module
    sys.modules["telethon.tl.types"] = tl_types_module


def _load_profile_service_module():
    _install_astrbot_stubs()
    _install_telethon_stubs()

    package_name = "telethon_adapter"
    package_path = Path(__file__).resolve().parents[1] / package_name
    package_module = types.ModuleType(package_name)
    package_module.__path__ = [str(package_path)]
    sys.modules[package_name] = package_module

    services_name = f"{package_name}.services"
    services_path = package_path / "services"
    services_module = types.ModuleType(services_name)
    services_module.__path__ = [str(services_path)]
    sys.modules[services_name] = services_module

    module_name = f"{services_name}.profile_service"
    module_path = services_path / "profile_service.py"
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


profile_service_module = _load_profile_service_module()
TelethonProfileService = profile_service_module.TelethonProfileService
ResolvedProfile = profile_service_module.ResolvedProfile
User = sys.modules["telethon.tl.types"].User
Channel = sys.modules["telethon.tl.types"].Channel
At = sys.modules["astrbot.api.message_components"].At


class _FakeClient:
    def __init__(self):
        self.lookups = []
        self.profile_downloads = []
        self.media_downloads = []

    async def get_entity(self, value):
        self.lookups.append(value)
        return f"entity:{value}"

    async def download_profile_photo(self, entity, file=None, download_big=True):
        self.profile_downloads.append((entity, file, download_big))
        raise RuntimeError("profile photo unavailable")

    async def download_media(self, media, file=None):
        self.media_downloads.append((media, file))
        return None


class _FakeMessageObj:
    def __init__(self, message, self_id="999"):
        self.message = message
        self.self_id = self_id


class _FakeEvent:
    def __init__(self, client, message_obj, raw_message=None, is_private=False, sender_id="", session_id=""):
        self.client = client
        self.message_obj = message_obj
        self.message_obj.raw_message = raw_message
        self._is_private = is_private
        self._sender_id = sender_id
        self.session_id = session_id

    def is_private_chat(self):
        return self._is_private

    def get_sender_id(self):
        return self._sender_id


class TelethonProfileServiceTest(unittest.IsolatedAsyncioTestCase):
    def test_supports_event_accepts_telethon_like_event(self):
        service = TelethonProfileService()
        event = types.SimpleNamespace(
            client=object(),
            platform_meta=types.SimpleNamespace(name="telethon_userbot"),
            message_obj=types.SimpleNamespace(raw_message=types.SimpleNamespace(peer_id=123)),
        )

        self.assertTrue(service.supports_event(event))

    def test_supports_event_rejects_non_telethon_event(self):
        service = TelethonProfileService()
        event = types.SimpleNamespace(
            client=None,
            platform_meta=types.SimpleNamespace(name="telethon_userbot"),
            message_obj=types.SimpleNamespace(raw_message=None),
        )

        self.assertFalse(service.supports_event(event))

    def test_normalize_target(self):
        self.assertEqual(
            TelethonProfileService._normalize_target("https://t.me/example_user/"),
            "example_user",
        )
        self.assertEqual(TelethonProfileService._normalize_target("@example"), "example")
        self.assertEqual(TelethonProfileService._normalize_target("-100123"), -100123)
        self.assertEqual(
            type(TelethonProfileService._normalize_target("me")).__name__,
            "InputPeerSelf",
        )

    async def test_resolve_mention_entity_uses_first_non_self_at(self):
        service = TelethonProfileService()
        client = _FakeClient()
        message_obj = _FakeMessageObj(
            [
                At(qq="999", name="self"),
                At(qq="12345", name="target"),
            ]
        )

        entity = await service._resolve_mention_entity(client, message_obj)

        self.assertEqual(entity, "entity:12345")
        self.assertEqual(client.lookups, [12345])

    async def test_resolve_entity_prefers_mention_over_reply(self):
        service = TelethonProfileService()
        client = _FakeClient()
        message_obj = _FakeMessageObj([At(qq="12345", name="target")])

        class _ReplyMessage:
            async def get_sender(self):
                return "reply:sender"

        class _RawMessage:
            async def get_reply_message(self):
                return _ReplyMessage()

        entity, source = await service._resolve_entity(
            _FakeEvent(client, message_obj, _RawMessage()),
            "",
        )

        self.assertEqual(entity, "entity:12345")
        self.assertEqual(source, "当前消息中的 @ 提及")

    async def test_resolve_entity_uses_topic_session_id_fallback(self):
        service = TelethonProfileService()
        client = _FakeClient()

        entity, source = await service._resolve_entity(
            _FakeEvent(
                client,
                _FakeMessageObj([]),
                raw_message=None,
                session_id="-100123456#789",
            ),
            "",
        )

        self.assertEqual(entity, "entity:-100123456")
        self.assertEqual(source, "当前会话")
        self.assertEqual(client.lookups, [-100123456])

    async def test_resolve_entity_prefers_private_chat_peer_over_sender(self):
        service = TelethonProfileService()
        client = _FakeClient()
        message_obj = _FakeMessageObj([])

        class _RawMessage:
            peer_id = "peer:bot"

            async def get_chat(self):
                return "entity:chat_target"

        entity, source = await service._resolve_entity(
            _FakeEvent(
                client,
                message_obj,
                _RawMessage(),
                is_private=True,
                sender_id="12345",
            ),
            "",
        )

        self.assertEqual(entity, "entity:chat_target")
        self.assertEqual(source, "当前私聊对象")
        self.assertEqual(client.lookups, [])

    def test_format_user_profile_text(self):
        status_cls = types.new_class("UserStatusOnline")
        entity = User(
            id=12345,
            first_name="Alice",
            last_name="Smith",
            username="alice",
            photo=types.SimpleNamespace(dc_id=2),
            phone="123456789",
            premium=True,
            verified=True,
            bot=False,
            contact=True,
            usernames=[types.SimpleNamespace(username="alice_archive", active=True)],
            status=status_cls(),
        )
        full = types.SimpleNamespace(
            about="Test bio",
            common_chats_count=8,
        )
        rendered = TelethonProfileService._format_profile_text(
            ResolvedProfile(entity=entity, full=full, source="显式参数 @alice")
        )

        self.assertNotIn("解析来源:", rendered)
        self.assertIn("<b>类型:</b> 用户", rendered)
        self.assertIn("<b>显示名:</b> Alice Smith", rendered)
        self.assertIn("<b>用户名:</b> @alice", rendered)
        self.assertIn('<b>链接:</b> <a href="https://t.me/alice">https://t.me/alice</a>', rendered)
        self.assertLess(rendered.index("<b>用户名:</b> @alice"), rendered.index('<b>链接:</b> <a href="https://t.me/alice">https://t.me/alice</a>'))
        self.assertIn("<b>数据中心:</b> 🇳🇱 荷兰阿姆斯特丹（DC2）", rendered)
        self.assertIn("<b>手机号:</b> 🙈 已隐藏", rendered)
        self.assertIn("<b>简介:</b> Test bio", rendered)
        self.assertIn("<b>共同群组数:</b> 8", rendered)
        self.assertIn("<b>状态:</b> 在线", rendered)
        self.assertIn("<b>标记:</b> 联系人、已认证、高级会员", rendered)
        self.assertNotIn("123456789", rendered)

    def test_format_self_user_hides_phone(self):
        entity = User(
            id=12345,
            first_name="Alice",
            username="alice",
            phone="123456789",
        )
        setattr(entity, "self", True)
        rendered = TelethonProfileService._format_profile_text(
            ResolvedProfile(entity=entity, full=None, source="当前私聊对象")
        )

        self.assertIn("<b>手机号:</b> 🙈 已隐藏", rendered)
        self.assertNotIn("123456789", rendered)

    def test_format_bot_profile_uses_robot_type_without_duplicate_flag(self):
        entity = User(
            id=54321,
            first_name="AstrBot",
            username="astrbot_helper",
            bot=True,
            verified=True,
        )

        rendered = TelethonProfileService._format_profile_text(
            ResolvedProfile(entity=entity, full=None, source="显式参数 @astrbot_helper")
        )

        self.assertIn("<b>类型:</b> 机器人", rendered)
        self.assertIn("<b>标记:</b> 已认证", rendered)
        self.assertNotIn("<b>标记:</b> 机器人", rendered)

    def test_format_channel_profile_text(self):
        entity = Channel(
            id=777,
            title="AstrBot Channel",
            broadcast=True,
            verified=True,
            usernames=[types.SimpleNamespace(username="astrbot_channel", active=True)],
        )
        full = types.SimpleNamespace(
            about="Release feed",
            participants_count=1024,
            admins_count=4,
            linked_chat_id=2048,
            slowmode_seconds=0,
        )
        rendered = TelethonProfileService._format_profile_text(
            ResolvedProfile(entity=entity, full=full, source="当前会话")
        )

        self.assertIn("<b>名称:</b> AstrBot Channel", rendered)
        self.assertIn('<b>链接:</b> <a href="https://t.me/astrbot_channel">https://t.me/astrbot_channel</a>', rendered)
        self.assertIn("<b>可见性:</b> 公开", rendered)
        self.assertIn("<b>类型:</b> 频道", rendered)
        self.assertLess(rendered.index('<b>链接:</b> <a href="https://t.me/astrbot_channel">https://t.me/astrbot_channel</a>'), rendered.index("<b>类型:</b> 频道"))
        self.assertIn("<b>成员数:</b> 1024", rendered)
        self.assertIn("<b>讨论组 ID:</b> 2048", rendered)
        self.assertIn("<b>标记:</b> 已认证", rendered)

    def test_format_user_profile_text_in_english(self):
        status_cls = types.new_class("UserStatusOnline")
        entity = User(
            id=12345,
            first_name="Alice",
            last_name="Smith",
            username="alice",
            photo=types.SimpleNamespace(dc_id=2),
            phone="123456789",
            premium=True,
            verified=True,
            bot=False,
            contact=True,
            usernames=[types.SimpleNamespace(username="alice_archive", active=True)],
            status=status_cls(),
        )
        full = types.SimpleNamespace(
            about="Test bio",
            common_chats_count=8,
        )

        rendered = TelethonProfileService._format_profile_text(
            ResolvedProfile(entity=entity, full=full, source="explicit parameter @alice"),
            language="en-US",
        )

        self.assertIn("<b>Type:</b> User", rendered)
        self.assertIn("<b>Display Name:</b> Alice Smith", rendered)
        self.assertIn("<b>Data Center:</b> 🇳🇱 Amsterdam, Netherlands (DC2)", rendered)
        self.assertIn("<b>Phone:</b> 🙈 Hidden", rendered)
        self.assertIn("<b>Status:</b> Online", rendered)
        self.assertIn("<b>Flags:</b> Contact, Verified, Premium", rendered)

    def test_format_private_group_link_uses_hidden_invite(self):
        entity = Channel(
            id=779,
            title="Private Group",
            megagroup=True,
        )
        full = types.SimpleNamespace(
            exported_invite=types.SimpleNamespace(
                link="https://t.me/+privateinvite",
                permanent=True,
            )
        )

        rendered = TelethonProfileService._format_profile_text(
            ResolvedProfile(entity=entity, full=full, source="当前会话")
        )

        self.assertIn("<b>可见性:</b> 私有", rendered)
        self.assertNotIn("<b>链接:</b>", rendered)

    def test_format_user_profilefull_text(self):
        entity = User(
            id=12345,
            first_name="Alice",
            username="alice",
            lang_code="zh-hans",
            premium=True,
            contact_require_premium=True,
            close_friend=True,
        )
        full = types.SimpleNamespace(
            about="Test bio",
            common_chats_count=8,
            blocked=True,
            translations_disabled=True,
            private_forward_name="AliceForward",
            phone_calls_available=False,
        )
        rendered = TelethonProfileService._format_profile_text(
            ResolvedProfile(entity=entity, full=full, source="显式参数 @alice"),
            detailed=True,
        )

        self.assertIn("<b>语言:</b> zh-hans", rendered)
        self.assertIn("<b>已拉黑:</b> ✅", rendered)
        self.assertIn("<b>禁用翻译:</b> ✅", rendered)
        self.assertIn("<b>私聊转发名:</b> AliceForward", rendered)
        self.assertIn("<b>标记:</b> 高级会员", rendered)
        self.assertIn("<b>标记:</b> 亲密好友、联系需高级会员", rendered)
        self.assertNotIn("可语音通话", rendered)

    def test_format_channel_profilefull_text(self):
        entity = Channel(
            id=777,
            title="AstrBot Channel",
            username="astrbot_channel",
            megagroup=True,
            forum=True,
            join_request=True,
            admin_rights=types.SimpleNamespace(dummy=True),
            access_hash=123456,
            creator=True,
            left=True,
            stories_max_id=88,
        )
        full = types.SimpleNamespace(
            about="Release feed",
            participants_count=1024,
            admins_count=4,
            linked_chat_id=2048,
            pinned_msg_id=999,
            read_inbox_max_id=837,
            read_outbox_max_id=288,
            unread_count=0,
            hidden_prehistory=True,
            can_view_participants=True,
            can_view_stats=True,
            can_delete_channel=True,
            can_set_username=True,
            can_set_stickers=True,
            can_set_location=True,
            participants_hidden=True,
            stats_dc=5,
            blocked=False,
            available_reactions="all",
        )
        rendered = TelethonProfileService._format_profile_text(
            ResolvedProfile(entity=entity, full=full, source="当前会话"),
            detailed=True,
        )

        self.assertIn("<b>名称:</b> AstrBot Channel", rendered)
        self.assertIn('<b>链接:</b> <a href="https://t.me/astrbot_channel">https://t.me/astrbot_channel</a>', rendered)
        self.assertIn("<b>类型:</b> 超级群组", rendered)
        self.assertLess(rendered.index('<b>链接:</b> <a href="https://t.me/astrbot_channel">https://t.me/astrbot_channel</a>'), rendered.index("<b>类型:</b> 超级群组"))
        self.assertIn("<b>动态最大 ID:</b> 88", rendered)
        self.assertIn("<b>数据中心:</b> 🇸🇬 新加坡（DC5）", rendered)
        self.assertIn("<b>表情回应:</b> all", rendered)
        self.assertIn("<b>标记:</b> 论坛、需申请加入", rendered)
        self.assertNotIn("已拉黑", rendered)
        self.assertNotIn("访问哈希", rendered)
        self.assertNotIn("置顶消息 ID", rendered)
        self.assertNotIn("可看成员", rendered)
        self.assertNotIn("可删除频道", rendered)
        self.assertNotIn("可设置用户名", rendered)
        self.assertNotIn("管理员权限", rendered)
        self.assertNotIn("可设置贴纸", rendered)
        self.assertNotIn("可设置位置", rendered)
        self.assertNotIn("可看统计", rendered)
        self.assertNotIn("你是创建者", rendered)
        self.assertNotIn("当前已退出", rendered)
        self.assertIn("<b>隐藏成员:</b> ✅", rendered)
        self.assertNotIn("最小隐藏动态", rendered)
        self.assertNotIn("已读收件箱 ID", rendered)
        self.assertNotIn("已读发件箱 ID", rendered)
        self.assertNotIn("未读数", rendered)

    def test_primary_username_and_link_fallback_to_usernames(self):
        entity = Channel(
            id=888,
            title="Fallback Channel",
            megagroup=True,
            usernames=[types.SimpleNamespace(username="fallback_group", active=True)],
        )

        rendered = TelethonProfileService._format_profile_text(
            ResolvedProfile(entity=entity, full=None, source="当前会话")
        )

        self.assertIn(
            '<b>链接:</b> <a href="https://t.me/fallback_group">https://t.me/fallback_group</a>',
            rendered,
        )

    def test_stringify_invite_object(self):
        invite = types.SimpleNamespace(
            link="https://t.me/+Ls0oRAPWobowMTc1",
            permanent=True,
            revoked=False,
            request_needed=False,
            usage=3,
            usage_limit=10,
            expire_date=None,
            title=None,
        )

        rendered = TelethonProfileService._stringify_value(invite)

        self.assertEqual(
            rendered,
            "🙈 已隐藏 (永久 ; 使用次数=3/10)",
        )

    def test_stringify_invite_object_in_english(self):
        invite = types.SimpleNamespace(
            link="https://t.me/+Ls0oRAPWobowMTc1",
            permanent=True,
            revoked=False,
            request_needed=False,
            usage=3,
            usage_limit=10,
            expire_date=None,
            title=None,
        )

        rendered = TelethonProfileService._stringify_value(invite, "en-US")

        self.assertEqual(
            rendered,
            "🙈 Hidden (permanent ; usage=3/10)",
        )

    def test_stringify_admin_rights_object(self):
        rights = types.new_class("ChatAdminRights")
        rights = rights()
        rights.change_info = True
        rights.delete_messages = True
        rights.manage_topics = True
        rights.other = True

        rendered = TelethonProfileService._stringify_value(rights)

        self.assertEqual(rendered, "修改资料、删除消息、管理话题、其它管理权限")

    def test_stringify_banned_rights_object(self):
        rights = types.new_class("ChatBannedRights")
        rights = rights()
        rights.until_date = datetime(2038, 1, 19, 3, 14, 7, tzinfo=timezone.utc)
        rights.send_messages = True
        rights.send_media = True
        rights.embed_links = True

        rendered = TelethonProfileService._stringify_value(rights)

        self.assertEqual(rendered, "长期有效；限制: 发送消息、发送媒体、附带链接预览")

    def test_stringify_emoji_status_object(self):
        emoji_status = types.new_class("EmojiStatus")
        emoji_status = emoji_status()
        emoji_status.document_id = 6264533697584696158
        emoji_status.until = None

        rendered = TelethonProfileService._stringify_value(emoji_status)

        self.assertEqual(rendered, "长期")

    def test_stringify_chat_reactions_all_object(self):
        reactions = types.new_class("ChatReactionsAll")
        reactions = reactions()
        reactions.allow_custom = True

        rendered = TelethonProfileService._stringify_value(reactions)

        self.assertEqual(rendered, "允许所有（含自定义）")

    def test_format_datetime_keeps_timezone_info(self):
        rendered = TelethonProfileService._format_datetime(
            datetime(2026, 3, 14, 6, 7, 0, tzinfo=timezone.utc)
        )

        self.assertIn("2026-03-14", rendered)
        self.assertIn("UTC", rendered)

    def test_user_status_online_uses_effective_until_wording(self):
        status_cls = types.new_class("UserStatusOnline")
        status = status_cls()
        status.expires = datetime(2026, 3, 14, 6, 7, 0, tzinfo=timezone.utc)
        entity = User(id=1, status=status)

        rendered = TelethonProfileService._user_status(entity)

        self.assertIn("在线（状态有效至", rendered)

    def test_user_status_online_uses_effective_until_wording_in_english(self):
        status_cls = types.new_class("UserStatusOnline")
        status = status_cls()
        status.expires = datetime(2026, 3, 14, 6, 7, 0, tzinfo=timezone.utc)
        entity = User(id=1, status=status)

        rendered = TelethonProfileService._user_status(entity, "en-US")

        self.assertIn("Online (valid until", rendered)

    async def test_download_profile_photo_falls_back_to_full_photo(self):
        service = TelethonProfileService()
        client = _FakeClient()
        entity = User(id=1)
        full = types.SimpleNamespace(chat_photo=object())

        path = await service._download_profile_photo(client, entity, full)

        self.assertIsNone(path)
        self.assertEqual(len(client.profile_downloads), 1)
        self.assertEqual(len(client.media_downloads), 1)


if __name__ == "__main__":
    unittest.main()
