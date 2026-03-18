import importlib.util
import sys
import sysconfig
import types
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REAL_TELETHON_SITE_PACKAGES = PROJECT_ROOT / ".venv" / sysconfig.get_path(
    "purelib",
    vars={"base": str(PROJECT_ROOT / ".venv"), "platbase": str(PROJECT_ROOT / ".venv")},
).removeprefix(str(PROJECT_ROOT / ".venv/"))


def _install_telethon_stubs() -> None:
    telethon_module = types.ModuleType("telethon")
    telethon_functions_module = types.ModuleType("telethon.functions")
    telethon_functions_messages_module = types.ModuleType("telethon.functions.messages")
    telethon_types_module = types.ModuleType("telethon.types")

    class InputReplyToMessage:
        def __init__(self, reply_to_msg_id, top_msg_id=None):
            self.reply_to_msg_id = reply_to_msg_id
            self.top_msg_id = top_msg_id

    class SendMessageRequest:
        def __init__(self, peer, message, entities=None, no_webpage=True, reply_to=None, **kwargs):
            self.peer = peer
            self.message = message
            self.entities = entities
            self.no_webpage = no_webpage
            self.reply_to = reply_to
            self.kwargs = kwargs

    class SendMediaRequest:
        def __init__(self, peer, media, reply_to=None, message="", entities=None, **kwargs):
            self.peer = peer
            self.media = media
            self.reply_to = reply_to
            self.message = message
            self.entities = entities
            self.kwargs = kwargs

    telethon_types_module.InputReplyToMessage = InputReplyToMessage
    telethon_functions_messages_module.SendMessageRequest = SendMessageRequest
    telethon_functions_messages_module.SendMediaRequest = SendMediaRequest
    telethon_functions_module.messages = telethon_functions_messages_module
    telethon_module.types = telethon_types_module
    telethon_module.functions = telethon_functions_module
    sys.modules["telethon"] = telethon_module
    sys.modules["telethon.functions"] = telethon_functions_module
    sys.modules["telethon.functions.messages"] = telethon_functions_messages_module
    sys.modules["telethon.types"] = telethon_types_module


def _load_sender_module():
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

    module_name = f"{services_name}.sender"
    module_path = services_path / "sender.py"
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _load_sender_module_with_real_telethon():
    for module_name in list(sys.modules):
        if module_name == "telethon" or module_name.startswith("telethon."):
            sys.modules.pop(module_name, None)

    site_packages = str(REAL_TELETHON_SITE_PACKAGES)
    if site_packages not in sys.path:
        sys.path.insert(0, site_packages)

    package_name = "telethon_adapter"
    package_path = PROJECT_ROOT / package_name
    package_module = types.ModuleType(package_name)
    package_module.__path__ = [str(package_path)]
    sys.modules[package_name] = package_module

    services_name = f"{package_name}.services"
    services_path = package_path / "services"
    services_module = types.ModuleType(services_name)
    services_module.__path__ = [str(services_path)]
    sys.modules[services_name] = services_module

    module_name = f"{services_name}.sender_real"
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
        self.requests = []

    async def __call__(self, request):
        self.requests.append(request)
        return {"request": request}

    async def send_message(self, peer, text, **kwargs):
        self.sent_messages.append((peer, text, kwargs))
        return types.SimpleNamespace(id=88)

    async def send_file(self, peer, file, caption=None, **kwargs):
        self.sent_files.append((peer, file, caption, kwargs))
        return types.SimpleNamespace(id=89)

    async def delete_messages(self, peer, message_ids, revoke=True):
        self.deleted.append((peer, list(message_ids), revoke))

    async def get_input_entity(self, peer):
        return f"input:{peer}"

    async def _parse_message_text(self, text, parse_mode):
        return text, [types.SimpleNamespace(parse_mode=parse_mode)]

    async def _file_to_media(self, file, **kwargs):
        return None, f"media:{file}", False

    def _get_response_message(self, request, result, entity):
        return types.SimpleNamespace(id=90, request=request, entity=entity)


class _FakeEvent:
    def __init__(self, client, reply_to_msg_id=None, thread_id=None):
        self.client = client
        self.peer = "peer:test"
        self.thread_id = thread_id
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

    async def test_send_html_message_topic_defaults_to_thread_root(self):
        sender = TelethonSender()
        client = _FakeClient()

        await sender.send_html_message(
            _FakeEvent(client, thread_id=456),
            "hello",
        )

        request = client.requests[0]
        self.assertEqual(type(request).__name__, "SendMessageRequest")
        self.assertEqual(request.peer, "input:peer:test")
        self.assertEqual(type(request.reply_to).__name__, "InputReplyToMessage")
        self.assertEqual(request.reply_to.reply_to_msg_id, 456)
        self.assertEqual(request.reply_to.top_msg_id, 456)

    async def test_send_html_message_topic_preserves_reply_and_thread(self):
        sender = TelethonSender()
        client = _FakeClient()

        await sender.send_html_message(
            _FakeEvent(client, reply_to_msg_id=77, thread_id=456),
            "hello",
            follow_reply=True,
        )

        request = client.requests[0]
        self.assertEqual(type(request).__name__, "SendMessageRequest")
        self.assertEqual(type(request.reply_to).__name__, "InputReplyToMessage")
        self.assertEqual(request.reply_to.reply_to_msg_id, 77)
        self.assertEqual(request.reply_to.top_msg_id, 456)

    async def test_send_html_file_topic_uses_send_media_request(self):
        sender = TelethonSender()
        client = _FakeClient()

        result = await sender.send_html_message(
            _FakeEvent(client, thread_id=456),
            "hello",
            file_path="/tmp/avatar.png",
        )

        self.assertEqual(getattr(result, "id", None), 90)
        request = client.requests[0]
        self.assertEqual(type(request).__name__, "SendMediaRequest")
        self.assertEqual(request.peer, "input:peer:test")
        self.assertEqual(request.media, "media:/tmp/avatar.png")
        self.assertEqual(type(request.reply_to).__name__, "InputReplyToMessage")
        self.assertEqual(request.reply_to.reply_to_msg_id, 456)
        self.assertEqual(request.reply_to.top_msg_id, 456)

    async def test_send_html_file_fast_upload_uses_send_media_request(self):
        sender = TelethonSender()
        client = _FakeClient()
        original_should_use_fast_upload = sender_module.should_use_fast_upload
        original_build_input_media = sender_module.build_input_media

        sender_module.should_use_fast_upload = lambda _client, _file: True

        async def _build_input_media(_client, _file, **_kwargs):
            return None, "fast-media:/tmp/avatar.png", False

        sender_module.build_input_media = _build_input_media
        try:
            result = await sender.send_html_message(
                _FakeEvent(client),
                "hello",
                file_path="/tmp/avatar.png",
            )
        finally:
            sender_module.should_use_fast_upload = original_should_use_fast_upload
            sender_module.build_input_media = original_build_input_media

        self.assertEqual(getattr(result, "id", None), 90)
        self.assertEqual(len(client.sent_files), 0)
        request = client.requests[0]
        self.assertEqual(type(request).__name__, "SendMediaRequest")
        self.assertEqual(request.media, "fast-media:/tmp/avatar.png")

    async def test_send_html_file_fast_upload_wraps_reply_to_for_low_level_request(self):
        sender = TelethonSender()
        client = _FakeClient()
        original_should_use_fast_upload = sender_module.should_use_fast_upload
        original_build_input_media = sender_module.build_input_media

        sender_module.should_use_fast_upload = lambda _client, _file: True

        async def _build_input_media(_client, _file, **_kwargs):
            return None, "fast-media:/tmp/avatar.png", False

        sender_module.build_input_media = _build_input_media
        try:
            await sender.send_html_message(
                _FakeEvent(client, reply_to_msg_id=66),
                "hello",
                file_path="/tmp/avatar.png",
                follow_reply=True,
            )
        finally:
            sender_module.should_use_fast_upload = original_should_use_fast_upload
            sender_module.build_input_media = original_build_input_media

        request = client.requests[0]
        self.assertEqual(type(request).__name__, "SendMediaRequest")
        self.assertEqual(type(request.reply_to).__name__, "InputReplyToMessage")
        self.assertEqual(request.reply_to.reply_to_msg_id, 66)
        self.assertIsNone(request.reply_to.top_msg_id)

    async def test_schedule_delete_message_deletes_later(self):
        sender = TelethonSender()
        client = _FakeClient()
        event = _FakeEvent(client)
        sender.schedule_delete_message(event, types.SimpleNamespace(id=99), 0)
        await sender_module.asyncio.sleep(0)
        await sender_module.asyncio.sleep(0)

        self.assertEqual(client.deleted, [("peer:test", [99], True)])


@unittest.skipUnless(
    REAL_TELETHON_SITE_PACKAGES.exists(),
    "real Telethon test requires project .venv",
)
class TelethonSenderRealTelethonTests(unittest.IsolatedAsyncioTestCase):
    async def test_send_html_message_topic_uses_real_input_reply_to_message(self):
        real_sender_module = _load_sender_module_with_real_telethon()
        sender = real_sender_module.TelethonSender()
        client = _FakeClient()
        from telethon.tl.types import InputReplyToMessage

        await sender.send_html_message(
            _FakeEvent(client, thread_id=456),
            "hello",
        )

        from telethon.tl.functions.messages import SendMessageRequest

        request = next(
            request for request in client.requests if isinstance(request, SendMessageRequest)
        )
        self.assertIsInstance(request.reply_to, InputReplyToMessage)
        self.assertEqual(request.reply_to.reply_to_msg_id, 456)
        self.assertEqual(request.reply_to.top_msg_id, 456)

    async def test_send_html_message_topic_with_reply_uses_real_input_reply_to_message(self):
        real_sender_module = _load_sender_module_with_real_telethon()
        sender = real_sender_module.TelethonSender()
        client = _FakeClient()
        from telethon.tl.types import InputReplyToMessage

        await sender.send_html_message(
            _FakeEvent(client, reply_to_msg_id=77, thread_id=456),
            "hello",
            follow_reply=True,
        )

        from telethon.tl.functions.messages import SendMessageRequest

        request = next(
            request for request in client.requests if isinstance(request, SendMessageRequest)
        )
        self.assertIsInstance(request.reply_to, InputReplyToMessage)
        self.assertEqual(request.reply_to.reply_to_msg_id, 77)
        self.assertEqual(request.reply_to.top_msg_id, 456)
