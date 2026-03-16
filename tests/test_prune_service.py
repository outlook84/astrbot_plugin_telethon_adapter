import importlib.util
import sys
import types
import unittest
from pathlib import Path


def _install_astrbot_stubs() -> None:
    astrbot_module = types.ModuleType("astrbot")
    api_module = types.ModuleType("astrbot.api")
    message_components_module = types.ModuleType("astrbot.api.message_components")

    class _Logger:
        def debug(self, *args, **kwargs):
            return None

        def info(self, *args, **kwargs):
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
    sys.modules["astrbot"] = astrbot_module
    sys.modules["astrbot.api"] = api_module
    message_components_module.At = At
    sys.modules["astrbot.api.message_components"] = message_components_module


def _install_telethon_stubs() -> None:
    telethon_module = types.ModuleType("telethon")
    errors_module = types.ModuleType("telethon.errors")

    class RPCError(Exception):
        pass

    class FloodWaitError(RPCError):
        def __init__(self, seconds):
            super().__init__(f"FLOOD_WAIT_{seconds}")
            self.seconds = seconds

    class MessageDeleteForbiddenError(RPCError):
        pass

    class MessageIdInvalidError(RPCError):
        pass

    class ChatAdminRequiredError(RPCError):
        pass

    class ForbiddenError(RPCError):
        pass

    errors_module.RPCError = RPCError
    errors_module.FloodWaitError = FloodWaitError
    errors_module.MessageDeleteForbiddenError = MessageDeleteForbiddenError
    errors_module.MessageIdInvalidError = MessageIdInvalidError
    errors_module.ChatAdminRequiredError = ChatAdminRequiredError
    errors_module.ForbiddenError = ForbiddenError

    telethon_module.errors = errors_module

    sys.modules["telethon"] = telethon_module
    sys.modules["telethon.errors"] = errors_module


def _load_prune_service_module():
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

    module_name = f"{services_name}.prune_service"
    module_path = services_path / "prune_service.py"
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


prune_service_module = _load_prune_service_module()
TelethonPruneService = prune_service_module.TelethonPruneService
FloodWaitError = sys.modules["telethon.errors"].FloodWaitError
MessageDeleteForbiddenError = sys.modules["telethon.errors"].MessageDeleteForbiddenError
ChatAdminRequiredError = sys.modules["telethon.errors"].ChatAdminRequiredError
At = sys.modules["astrbot.api.message_components"].At


class _FakeMessage:
    def __init__(self, message_id, action=None, out=False, sender_id=None):
        self.id = message_id
        self.action = action
        self.out = out
        self.sender_id = sender_id


class _FakeClient:
    def __init__(self, messages, delete_side_effects=None, me_id=42):
        self._messages = list(messages)
        self.delete_calls = []
        self.delete_side_effects = list(delete_side_effects or [])
        self.me_id = me_id
        self.entities = {}
        self.iter_calls = []

    def iter_messages(self, peer, offset_id=None, reply_to=None, from_user=None):
        self.iter_calls.append(
            {
                "peer": peer,
                "offset_id": offset_id,
                "reply_to": reply_to,
                "from_user": from_user,
            }
        )
        async def _iterator():
            for message in self._messages:
                yield message

        return _iterator()

    async def delete_messages(self, peer, message_ids, revoke=True):
        self.delete_calls.append((peer, list(message_ids), revoke))
        if self.delete_side_effects:
            effect = self.delete_side_effects.pop(0)
            if isinstance(effect, BaseException):
                raise effect
        return None

    async def get_me(self):
        return types.SimpleNamespace(id=self.me_id)

    async def get_entity(self, value):
        if value in self.entities:
            return self.entities[value]
        raise ValueError(f"unknown entity: {value}")


class _FakeEvent:
    def __init__(
        self,
        client,
        reply_to_msg_id=None,
        reply_to_top_id=None,
        chat=None,
        command_sender_id=900,
        command_out=False,
        message_chain=None,
        self_id="42",
        reply_sender=None,
        thread_id=None,
    ):
        raw_message = types.SimpleNamespace(
            id=300,
            peer_id="peer:chat",
            reply_to=types.SimpleNamespace(
                reply_to_msg_id=reply_to_msg_id,
                reply_to_top_id=reply_to_top_id,
            ),
            out=command_out,
            sender_id=command_sender_id,
        )
        async def _get_chat():
            return chat

        async def _get_reply_message():
            if reply_sender is None:
                return None
            return types.SimpleNamespace(
                get_sender=lambda: _awaitable(reply_sender),
            )

        raw_message.get_chat = _get_chat
        raw_message.get_reply_message = _get_reply_message
        self.client = client
        self.peer = "peer:event"
        self.thread_id = thread_id
        self.message_obj = types.SimpleNamespace(
            raw_message=raw_message,
            message=message_chain or [],
            self_id=self_id,
        )


class _ReplyMessageWithoutGetSender:
    def __init__(self, *, sender=None, sender_id=None, from_id=None):
        self.sender = sender
        self.sender_id = sender_id
        self.from_id = from_id


def _awaitable(value):
    async def _inner():
        return value

    return _inner()


class TelethonPruneServiceTest(unittest.IsolatedAsyncioTestCase):
    async def test_prune_recent_messages_skips_service_messages(self):
        service = TelethonPruneService()
        client = _FakeClient(
            [
                _FakeMessage(299),
                _FakeMessage(298, action="join"),
                _FakeMessage(297),
                _FakeMessage(296),
            ]
        )

        result = await service.prune_messages(_FakeEvent(client), 3)

        self.assertEqual(result.deleted_count, 3)
        self.assertEqual(result.filtered_out_count, 1)
        self.assertEqual(result.skipped_count, 0)
        self.assertTrue(result.command_deleted)
        self.assertEqual(client.delete_calls, [("peer:event", [300, 299, 297, 296], True)])

    async def test_prune_without_reply_anchor_includes_command_message(self):
        service = TelethonPruneService()
        client = _FakeClient(
            [
                _FakeMessage(299),
                _FakeMessage(298),
            ]
        )

        result = await service.prune_messages(_FakeEvent(client), 2)

        self.assertEqual(result.deleted_count, 2)
        self.assertTrue(result.command_deleted)
        self.assertEqual(client.delete_calls, [("peer:event", [300, 299, 298], True)])

    async def test_prune_stops_at_reply_anchor(self):
        service = TelethonPruneService()
        client = _FakeClient(
            [
                _FakeMessage(299),
                _FakeMessage(298),
                _FakeMessage(297),
                _FakeMessage(296),
            ]
        )

        result = await service.prune_messages(_FakeEvent(client, reply_to_msg_id=297), 5)

        self.assertEqual(result.deleted_count, 2)
        self.assertTrue(result.used_reply_anchor)
        self.assertTrue(result.command_deleted)
        self.assertEqual(client.delete_calls, [("peer:event", [300, 299, 298], True)])

    async def test_prune_without_count_uses_reply_span(self):
        service = TelethonPruneService()
        client = _FakeClient(
            [
                _FakeMessage(299),
                _FakeMessage(298),
                _FakeMessage(297),
                _FakeMessage(296),
            ]
        )

        result = await service.prune_messages(_FakeEvent(client, reply_to_msg_id=296))

        self.assertIsNone(result.requested_count)
        self.assertEqual(result.deleted_count, 3)
        self.assertTrue(result.command_deleted)
        self.assertEqual(client.delete_calls, [("peer:event", [300, 299, 298, 297], True)])

    async def test_prune_topic_session_scans_only_current_thread(self):
        service = TelethonPruneService()
        client = _FakeClient(
            [
                _FakeMessage(299),
                _FakeMessage(298),
                _FakeMessage(297),
            ]
        )

        result = await service.prune_messages(
            _FakeEvent(client, thread_id=456),
            2,
        )

        self.assertEqual(client.iter_calls[0]["reply_to"], 456)
        self.assertEqual(result.deleted_count, 2)
        self.assertEqual(result.scanned_count, 2)
        self.assertEqual(client.delete_calls, [("peer:event", [300, 299, 298], True)])
        self.assertIsNone(client.iter_calls[0]["from_user"])

    async def test_prune_without_count_requires_reply_anchor(self):
        service = TelethonPruneService()
        client = _FakeClient([_FakeMessage(299)])

        with self.assertRaisesRegex(ValueError, "必须回复"):
            await service.prune_messages(_FakeEvent(client))

    async def test_prune_falls_back_to_single_delete_when_batch_forbidden(self):
        service = TelethonPruneService()
        client = _FakeClient(
            [
                _FakeMessage(299),
                _FakeMessage(298),
                _FakeMessage(297),
            ],
            delete_side_effects=[
                MessageDeleteForbiddenError("forbidden"),
                None,
                MessageDeleteForbiddenError("forbidden"),
                None,
            ],
        )

        result = await service.prune_messages(_FakeEvent(client), 3)

        self.assertEqual(result.deleted_count, 2)
        self.assertEqual(result.skipped_count, 1)
        self.assertTrue(result.partial)
        self.assertEqual(
            client.delete_calls,
            [
                ("peer:event", [300, 299, 298, 297], True),
                ("peer:event", [300], True),
                ("peer:event", [299], True),
                ("peer:event", [298], True),
                ("peer:event", [297], True),
            ],
        )

    async def test_prune_raises_permission_error(self):
        service = TelethonPruneService()
        client = _FakeClient([_FakeMessage(299)], delete_side_effects=[ChatAdminRequiredError("no admin")])

        with self.assertRaisesRegex(ValueError, "权限"):
            await service.prune_messages(_FakeEvent(client), 1)

    async def test_prune_prechecks_supergroup_delete_permission(self):
        service = TelethonPruneService()
        client = _FakeClient([_FakeMessage(299)])
        chat = types.SimpleNamespace(
            creator=False,
            megagroup=True,
            broadcast=False,
            admin_rights=types.SimpleNamespace(delete_messages=False),
        )

        with self.assertRaisesRegex(ValueError, "删除权限"):
            await service.prune_messages(_FakeEvent(client, chat=chat), 1)

    async def test_prune_retries_short_flood_wait(self):
        service = TelethonPruneService()
        client = _FakeClient(
            [_FakeMessage(299)],
            delete_side_effects=[FloodWaitError(1), None],
        )
        original_sleep = prune_service_module.asyncio.sleep

        async def _fake_sleep(_seconds):
            return None

        prune_service_module.asyncio.sleep = _fake_sleep
        try:
            result = await service.prune_messages(_FakeEvent(client), 1)
        finally:
            prune_service_module.asyncio.sleep = original_sleep

        self.assertEqual(result.deleted_count, 1)
        self.assertEqual(
            client.delete_calls,
            [
                ("peer:event", [300, 299], True),
                ("peer:event", [300, 299], True),
            ],
        )

    async def test_selfprune_only_deletes_own_messages(self):
        service = TelethonPruneService()
        client = _FakeClient(
            [
                _FakeMessage(299, out=True, sender_id=42),
                _FakeMessage(298, out=False, sender_id=100),
                _FakeMessage(297, out=False, sender_id=42),
                _FakeMessage(296, out=False, sender_id=200),
            ]
        )

        result = await service.prune_messages(_FakeEvent(client), 3, only_self=True)

        self.assertTrue(result.command_deleted)
        self.assertTrue(result.only_self)
        self.assertEqual(result.deleted_count, 2)
        self.assertEqual(result.filtered_out_count, 2)
        self.assertEqual(result.skipped_count, 0)
        self.assertEqual(client.delete_calls, [("peer:event", [300, 299, 297], True)])

    async def test_selfprune_without_count_uses_reply_span(self):
        service = TelethonPruneService()
        client = _FakeClient(
            [
                _FakeMessage(299, out=True, sender_id=42),
                _FakeMessage(298, out=False, sender_id=100),
                _FakeMessage(297, out=False, sender_id=42),
                _FakeMessage(296, out=False, sender_id=42),
            ]
        )

        result = await service.prune_messages(
            _FakeEvent(client, reply_to_msg_id=296),
            only_self=True,
        )

        self.assertTrue(result.command_deleted)
        self.assertEqual(result.deleted_count, 2)
        self.assertEqual(result.filtered_out_count, 1)
        self.assertEqual(result.skipped_count, 0)
        self.assertEqual(client.delete_calls, [("peer:event", [300, 299, 297], True)])

    async def test_selfprune_stops_at_scan_limit(self):
        service = TelethonPruneService()
        original_limit = prune_service_module.PRUNE_FILTERED_SCAN_LIMIT
        prune_service_module.PRUNE_FILTERED_SCAN_LIMIT = 3
        client = _FakeClient(
            [
                _FakeMessage(299, out=False, sender_id=100),
                _FakeMessage(298, out=False, sender_id=42),
                _FakeMessage(297, out=False, sender_id=100),
                _FakeMessage(296, out=False, sender_id=42),
            ]
        )

        try:
            result = await service.prune_messages(_FakeEvent(client), 5, only_self=True)
        finally:
            prune_service_module.PRUNE_FILTERED_SCAN_LIMIT = original_limit

        self.assertEqual(result.scan_limit, 3)
        self.assertTrue(result.hit_scan_limit)
        self.assertTrue(result.command_deleted)
        self.assertEqual(result.scanned_count, 3)
        self.assertEqual(result.deleted_count, 1)
        self.assertEqual(result.filtered_out_count, 2)
        self.assertEqual(result.skipped_count, 0)
        self.assertEqual(client.delete_calls, [("peer:event", [300, 298], True)])

    async def test_selfprune_topic_session_scans_only_current_thread(self):
        service = TelethonPruneService()
        client = _FakeClient(
            [
                _FakeMessage(299, sender_id=42),
                _FakeMessage(298, sender_id=42),
                _FakeMessage(297, sender_id=7),
            ]
        )

        result = await service.prune_messages(
            _FakeEvent(client, thread_id=456),
            2,
            only_self=True,
        )

        self.assertEqual(client.iter_calls[0]["reply_to"], 456)
        self.assertEqual(client.iter_calls[0]["from_user"], "me")
        self.assertEqual(result.deleted_count, 2)
        self.assertEqual(result.scanned_count, 2)
        self.assertEqual(result.filtered_out_count, 0)
        self.assertEqual(client.delete_calls, [("peer:event", [300, 299, 298], True)])

    async def test_youprune_resolves_target_from_mention(self):
        service = TelethonPruneService()
        client = _FakeClient(
            [
                _FakeMessage(299, sender_id=100),
                _FakeMessage(298, sender_id=200),
                _FakeMessage(297, sender_id=100),
            ]
        )
        client.entities[100] = types.SimpleNamespace(id=100, username="target100")

        target_user = await service.resolve_target_user(
            _FakeEvent(client, message_chain=[At(qq="100", name="target")]),
        )
        result = await service.prune_messages(
            _FakeEvent(client, message_chain=[At(qq="100", name="target")]),
            5,
            target_user=target_user,
        )

        self.assertTrue(result.command_deleted)
        self.assertEqual(getattr(target_user, "id", None), 100)
        self.assertEqual(result.target_user_id, 100)
        self.assertEqual(result.deleted_count, 2)
        self.assertEqual(result.filtered_out_count, 1)
        self.assertEqual(result.skipped_count, 0)
        self.assertEqual(client.delete_calls, [("peer:event", [300, 299, 297], True)])

    async def test_youprune_resolves_target_from_reply(self):
        service = TelethonPruneService()
        client = _FakeClient([_FakeMessage(299, sender_id=555)])
        target_user = types.SimpleNamespace(id=555, username="user555")

        resolved = await service.resolve_target_user(
            _FakeEvent(client, reply_to_msg_id=250, reply_sender=target_user),
        )

        self.assertEqual(getattr(resolved, "id", None), 555)

    async def test_youprune_prefers_reply_target_over_message_at(self):
        service = TelethonPruneService()
        client = _FakeClient([_FakeMessage(299, sender_id=555)])
        reply_target = types.SimpleNamespace(id=555, username="reply_user")
        mention_target = types.SimpleNamespace(id=777, username="mention_user")
        client.entities[777] = mention_target

        resolved = await service.resolve_target_user(
            _FakeEvent(
                client,
                reply_to_msg_id=250,
                reply_sender=reply_target,
                message_chain=[At(qq="777", name="mention_user")],
            ),
        )

        self.assertEqual(getattr(resolved, "id", None), 555)

    async def test_youprune_resolves_target_from_reply_sender_id_fallback(self):
        service = TelethonPruneService()
        client = _FakeClient([_FakeMessage(299, sender_id=555)])
        client.entities[555] = types.SimpleNamespace(id=555, username="user555")
        raw_message = types.SimpleNamespace(
            get_reply_message=lambda: _awaitable(_ReplyMessageWithoutGetSender(sender_id=555))
        )
        event = types.SimpleNamespace(
            client=client,
            message_obj=types.SimpleNamespace(raw_message=raw_message, message=[], self_id="42"),
        )

        resolved = await service.resolve_target_user(event)

        self.assertEqual(getattr(resolved, "id", None), 555)

    async def test_youprune_rejects_non_user_target(self):
        service = TelethonPruneService()
        client = _FakeClient([_FakeMessage(299)])
        client.entities["channel"] = types.SimpleNamespace(title="channel")

        with self.assertRaisesRegex(ValueError, "只能指定用户"):
            await service.resolve_target_user(_FakeEvent(client), "channel")

    async def test_youprune_rejects_numeric_target(self):
        service = TelethonPruneService()
        client = _FakeClient([_FakeMessage(299)])

        with self.assertRaisesRegex(ValueError, "未找到可删除的目标用户"):
            await service.resolve_target_user(_FakeEvent(client), "123456")

    async def test_youprune_rejects_non_user_reply_target(self):
        service = TelethonPruneService()
        client = _FakeClient([_FakeMessage(299)])
        reply_target = types.SimpleNamespace(id=777, title="channel")

        with self.assertRaisesRegex(ValueError, "回复目标不是用户"):
            await service.resolve_target_user(
                _FakeEvent(client, reply_to_msg_id=250, reply_sender=reply_target),
            )

    async def test_youprune_stops_at_scan_limit(self):
        service = TelethonPruneService()
        original_limit = prune_service_module.PRUNE_FILTERED_SCAN_LIMIT
        prune_service_module.PRUNE_FILTERED_SCAN_LIMIT = 2
        client = _FakeClient(
            [
                _FakeMessage(299, sender_id=200),
                _FakeMessage(298, sender_id=100),
                _FakeMessage(297, sender_id=100),
            ]
        )
        target_user = types.SimpleNamespace(id=100)

        try:
            result = await service.prune_messages(
                _FakeEvent(client),
                5,
                target_user=target_user,
            )
        finally:
            prune_service_module.PRUNE_FILTERED_SCAN_LIMIT = original_limit

    async def test_youprune_topic_session_scans_only_current_thread(self):
        service = TelethonPruneService()
        client = _FakeClient(
            [
                _FakeMessage(299, sender_id=555),
                _FakeMessage(298, sender_id=555),
                _FakeMessage(297, sender_id=555),
            ]
        )
        target_user = types.SimpleNamespace(id=555, username="user555")

        result = await service.prune_messages(
            _FakeEvent(client, reply_to_msg_id=250, thread_id=456, reply_sender=target_user),
            2,
            target_user=target_user,
        )

        self.assertEqual(result.deleted_count, 2)
        self.assertEqual(client.iter_calls[0]["reply_to"], 456)
        self.assertIs(client.iter_calls[0]["from_user"], target_user)
        self.assertEqual(result.scan_limit, prune_service_module.PRUNE_FILTERED_SCAN_LIMIT)
        self.assertFalse(result.hit_scan_limit)
        self.assertTrue(result.command_deleted)
        self.assertEqual(result.scanned_count, 2)
        self.assertEqual(result.filtered_out_count, 0)
        self.assertEqual(result.skipped_count, 0)
        self.assertEqual(client.delete_calls, [("peer:event", [300, 299, 298], True)])
