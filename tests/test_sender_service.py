import importlib.util
import sys
import types
import unittest
from pathlib import Path


def _load_sender_module():
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

    module_name = f"{services_name}.sender"
    module_path = services_path / "sender.py"
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


sender_module = _load_sender_module()
TelethonSender = sender_module.TelethonSender


class _FakeClient:
    def __init__(self):
        self.deleted = []
        self.sent_messages = []
        self.sent_files = []

    async def send_message(self, peer, text, **kwargs):
        self.sent_messages.append((peer, text, kwargs))
        return types.SimpleNamespace(id=88)

    async def send_file(self, peer, file, caption=None, **kwargs):
        self.sent_files.append((peer, file, caption, kwargs))
        return types.SimpleNamespace(id=89)

    async def delete_messages(self, peer, message_ids, revoke=True):
        self.deleted.append((peer, list(message_ids), revoke))


class _FakeEvent:
    def __init__(self, client, reply_to_msg_id=None):
        self.client = client
        self.peer = "peer:test"
        self.message_obj = types.SimpleNamespace(
            raw_message=types.SimpleNamespace(
                reply_to=types.SimpleNamespace(reply_to_msg_id=reply_to_msg_id),
            )
        )


class TelethonSenderTest(unittest.IsolatedAsyncioTestCase):
    async def test_send_html_message_returns_sent_message(self):
        sender = TelethonSender()
        client = _FakeClient()

        result = await sender.send_html_message(_FakeEvent(client), "hello")

        self.assertEqual(getattr(result, "id", None), 88)
        self.assertEqual(client.sent_messages[0][0], "peer:test")
        self.assertIsNone(client.sent_messages[0][2]["reply_to"])

    async def test_send_html_message_reuses_reply_target(self):
        sender = TelethonSender()
        client = _FakeClient()

        await sender.send_html_message(
            _FakeEvent(client, reply_to_msg_id=77),
            "hello",
            follow_reply=True,
        )

        self.assertEqual(client.sent_messages[0][2]["reply_to"], 77)

    async def test_send_html_file_reuses_reply_target(self):
        sender = TelethonSender()
        client = _FakeClient()

        result = await sender.send_html_message(
            _FakeEvent(client, reply_to_msg_id=66),
            "hello",
            file_path="/tmp/avatar.png",
            follow_reply=True,
        )

        self.assertEqual(getattr(result, "id", None), 89)
        self.assertEqual(client.sent_files[0][3]["reply_to"], 66)

    async def test_schedule_delete_message_deletes_later(self):
        sender = TelethonSender()
        client = _FakeClient()
        event = _FakeEvent(client)
        sender.schedule_delete_message(event, types.SimpleNamespace(id=99), 0)
        await sender_module.asyncio.sleep(0)
        await sender_module.asyncio.sleep(0)

        self.assertEqual(client.deleted, [("peer:test", [99], True)])
