import importlib.util
from contextlib import contextmanager
import sys
import types
import unittest
from pathlib import Path


def _install_astrbot_stubs() -> None:
    astrbot_module = types.ModuleType("astrbot")
    api_module = types.ModuleType("astrbot.api")
    event_module = types.ModuleType("astrbot.api.event")
    message_components_module = types.ModuleType("astrbot.api.message_components")

    class _Logger:
        def warning(self, *args, **kwargs):
            return None

        def exception(self, *args, **kwargs):
            return None

    class MessageChain:
        def __init__(self, chain=None):
            self.chain = chain or []

    class _BaseComponent:
        def __init__(self, **kwargs):
            for key, value in kwargs.items():
                setattr(self, key, value)

    class At(_BaseComponent):
        pass

    class File(_BaseComponent):
        pass

    class Image(_BaseComponent):
        pass

    class Location(_BaseComponent):
        pass

    class Plain(_BaseComponent):
        pass

    class Record(_BaseComponent):
        pass

    class Reply(_BaseComponent):
        pass

    class Video(_BaseComponent):
        pass

    api_module.logger = _Logger()
    event_module.MessageChain = MessageChain
    message_components_module.At = At
    message_components_module.File = File
    message_components_module.Image = Image
    message_components_module.Location = Location
    message_components_module.Plain = Plain
    message_components_module.Record = Record
    message_components_module.Reply = Reply
    message_components_module.Video = Video

    sys.modules["astrbot"] = astrbot_module
    sys.modules["astrbot.api"] = api_module
    sys.modules["astrbot.api.event"] = event_module
    sys.modules["astrbot.api.message_components"] = message_components_module


def _install_telethon_stubs() -> None:
    telethon_module = types.ModuleType("telethon")
    telethon_types_module = types.ModuleType("telethon.types")

    class SendMessageUploadPhotoAction:
        def __init__(self, progress=0):
            self.progress = progress

    telethon_types_module.SendMessageUploadPhotoAction = SendMessageUploadPhotoAction
    telethon_types_module.SendMessageUploadVideoAction = SendMessageUploadPhotoAction
    telethon_types_module.SendMessageUploadAudioAction = SendMessageUploadPhotoAction
    telethon_types_module.SendMessageUploadDocumentAction = SendMessageUploadPhotoAction
    telethon_types_module.DocumentAttributeAnimated = type("DocumentAttributeAnimated", (), {})
    telethon_types_module.TypeSendMessageAction = type("TypeSendMessageAction", (), {})
    telethon_module.types = telethon_types_module

    sys.modules["telethon"] = telethon_module
    sys.modules["telethon.types"] = telethon_types_module


def _load_message_dispatcher_module():
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

    contracts_name = f"{services_name}.contracts"
    contracts_path = services_path / "contracts.py"
    contracts_spec = importlib.util.spec_from_file_location(contracts_name, contracts_path)
    contracts_module = importlib.util.module_from_spec(contracts_spec)
    assert contracts_spec and contracts_spec.loader
    sys.modules[contracts_name] = contracts_module
    contracts_spec.loader.exec_module(contracts_module)

    module_name = f"{services_name}.message_dispatcher"
    module_path = services_path / "message_dispatcher.py"
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


dispatcher_module = _load_message_dispatcher_module()
TelethonMessageDispatcher = dispatcher_module.TelethonMessageDispatcher


@contextmanager
def _isolated_stub_modules():
    module_names = [
        "astrbot",
        "astrbot.api",
        "astrbot.api.event",
        "astrbot.api.message_components",
        "telethon",
        "telethon.types",
    ]
    originals = {name: sys.modules.get(name) for name in module_names}
    try:
        _install_astrbot_stubs()
        _install_telethon_stubs()
        yield
    finally:
        for name, module in originals.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module


class _FakeClient:
    def __init__(self):
        self.sent_files = []

    async def send_file(self, peer, file, caption=None, reply_to=None, **kwargs):
        self.sent_files.append((peer, file, caption, reply_to, kwargs))


class _FakeEvent:
    META_ATTR = "_gdl_meta"
    MEDIA_GROUP_INTENT = "media_group"

    def __init__(self):
        self.client = _FakeClient()
        self.peer = 123
        self.base_sent = []

    async def _send_base_message(self, message):
        self.base_sent.append(message)

    async def _flush_text(self, text_parts, reply_to):
        self.flushed = list(text_parts)
        text_parts.clear()
        return reply_to

    def _format_at_html(self, item):
        return None

    def _format_at_text(self, item):
        return "@x "

    def _label(self, key):
        return "[loc]"

    def _is_gif_path(self, path):
        return False

    async def _send_media(self, *args, **kwargs):
        self.media_call = (args, kwargs)
        return None

    def _component_has_spoiler(self, item):
        return False

    async def _send_local_media_group_request(self, media_items, *, caption, reply_to):
        self.low_level_media_group = (media_items, caption, reply_to)

    def _should_use_low_level_media_group_request(self, *, has_spoiler):
        return False

    def _request_sender(self):
        return types.SimpleNamespace(should_use_fast_upload=lambda _client, _path: False)

    def _build_reply_to(self, reply_to):
        return reply_to

    def _message_log_context(self, reply_to=None):
        return {
            "chat_id": 123,
            "thread_id": None,
            "msg_id": None,
            "sender_id": None,
            "reply_to": reply_to,
        }

    def _chat_action_scope(self, action_name, fallback_action):
        class _Scope:
            async def __aenter__(self_inner):
                return None

            async def __aexit__(self_inner, exc_type, exc, tb):
                return False

        return _Scope()


def _make_image_component(path):
    image_type = sys.modules["astrbot.api.message_components"].Image
    image = image_type()

    async def _convert_to_file_path():
        return path

    image.convert_to_file_path = _convert_to_file_path
    return image


class TelethonMessageDispatcherTests(unittest.IsolatedAsyncioTestCase):
    async def test_send_flushes_plain_text_and_calls_base_send(self):
        with _isolated_stub_modules():
            dispatcher = TelethonMessageDispatcher()
            event = _FakeEvent()
            plain_type = sys.modules["astrbot.api.message_components"].Plain
            chain_type = sys.modules["astrbot.api.event"].MessageChain

            message = chain_type([plain_type(text="hello")])

            await dispatcher.send(event, message)

            self.assertEqual(event.flushed, [("hello", False)])
            self.assertEqual(event.base_sent, [message])

    async def test_try_send_local_media_group_uses_album_send_file(self):
        with _isolated_stub_modules():
            dispatcher = TelethonMessageDispatcher()
            event = _FakeEvent()
            plain_type = sys.modules["astrbot.api.message_components"].Plain
            chain_type = sys.modules["astrbot.api.event"].MessageChain
            message = chain_type(
                [
                    plain_type(text="done"),
                    _make_image_component("/tmp/a.png"),
                    _make_image_component("/tmp/b.png"),
                ]
            )
            message._gdl_meta = {
                "version": 1,
                "intent": "media_group",
                "media_group": {"kind": "album", "media_type": "image"},
            }

            result = await dispatcher.try_send_local_media_group(event, message)

            self.assertTrue(result)
            self.assertEqual(
                event.client.sent_files,
                [(123, ["/tmp/a.png", "/tmp/b.png"], "done", None, {})],
            )
