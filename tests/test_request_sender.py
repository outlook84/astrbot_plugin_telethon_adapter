import importlib.util
import sys
import types
import unittest
from pathlib import Path


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


def _load_request_sender_module():
    _install_telethon_stubs()
    module_name = "test_request_sender_under_test"
    module_path = Path(__file__).resolve().parents[1] / "telethon_adapter" / "transport" / "request_sender.py"
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


request_sender_module = _load_request_sender_module()
TelethonRequestSender = request_sender_module.TelethonRequestSender


class _FakeClient:
    def __init__(self):
        self.requests = []
        self.sent_messages = []
        self.sent_files = []

    async def __call__(self, request):
        self.requests.append(request)
        return {"request": request}

    async def send_message(self, peer, text, **kwargs):
        self.sent_messages.append((peer, text, kwargs))
        return types.SimpleNamespace(id=1)

    async def send_file(self, peer, file, **kwargs):
        self.sent_files.append((peer, file, kwargs))
        return types.SimpleNamespace(id=2)

    async def get_input_entity(self, peer):
        return f"input:{peer}"

    async def _parse_message_text(self, text, parse_mode):
        return text, [types.SimpleNamespace(parse_mode=parse_mode)]

    def _get_response_message(self, request, result, entity):
        return types.SimpleNamespace(id=3, request=request, entity=entity)


class TelethonRequestSenderTests(unittest.IsolatedAsyncioTestCase):
    async def test_send_text_uses_send_message_without_thread(self):
        client = _FakeClient()
        sender = TelethonRequestSender(client=client, peer="peer:test")

        result = await sender.send_text(
            "hello",
            parse_mode="html",
            reply_to_msg_id=None,
            link_preview=True,
        )

        self.assertEqual(getattr(result, "id", None), 1)
        self.assertEqual(client.sent_messages[0][0], "peer:test")
        self.assertEqual(client.sent_messages[0][2]["parse_mode"], "html")
        self.assertEqual(client.sent_messages[0][2]["link_preview"], True)

    async def test_send_text_uses_request_in_topic(self):
        client = _FakeClient()
        sender = TelethonRequestSender(client=client, peer="peer:test", thread_id=456)

        result = await sender.send_text(
            "hello",
            parse_mode="html",
            reply_to_msg_id=None,
            link_preview=False,
        )

        self.assertEqual(getattr(result, "id", None), 3)
        request = client.requests[0]
        self.assertEqual(type(request).__name__, "SendMessageRequest")
        self.assertEqual(request.peer, "input:peer:test")
        self.assertEqual(request.reply_to.reply_to_msg_id, 456)
        self.assertEqual(request.reply_to.top_msg_id, 456)

    async def test_send_media_fast_upload_uses_request_and_wraps_reply_to(self):
        client = _FakeClient()

        async def _build_input_media(_client, _file, **_kwargs):
            return None, "fast-media:/tmp/a.png", False

        sender = TelethonRequestSender(
            client=client,
            peer="peer:test",
            build_input_media=_build_input_media,
            should_use_fast_upload=lambda _client, _file: True,
        )

        result = await sender.send_media(
            "/tmp/a.png",
            caption="hello",
            parse_mode="html",
            reply_to_msg_id=66,
        )

        self.assertEqual(getattr(result, "id", None), 3)
        request = client.requests[0]
        self.assertEqual(type(request).__name__, "SendMediaRequest")
        self.assertEqual(request.media, "fast-media:/tmp/a.png")
        self.assertEqual(type(request.reply_to).__name__, "InputReplyToMessage")
        self.assertEqual(request.reply_to.reply_to_msg_id, 66)
        self.assertIsNone(request.reply_to.top_msg_id)
