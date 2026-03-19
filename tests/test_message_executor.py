import importlib.util
from contextlib import contextmanager
import sys
import types
import unittest
from pathlib import Path


def _install_astrbot_stubs() -> None:
    astrbot_module = types.ModuleType("astrbot")
    api_module = types.ModuleType("astrbot.api")

    class _Logger:
        def warning(self, *args, **kwargs):
            return None

        def exception(self, *args, **kwargs):
            return None

        def debug(self, *args, **kwargs):
            return None

    api_module.logger = _Logger()
    sys.modules["astrbot"] = astrbot_module
    sys.modules["astrbot.api"] = api_module


def _install_telethon_stubs() -> None:
    telethon_module = types.ModuleType("telethon")
    functions_module = types.ModuleType("telethon.functions")
    messages_module = types.ModuleType("telethon.functions.messages")
    types_module = types.ModuleType("telethon.types")
    utils_module = types.ModuleType("telethon.utils")

    class SetTypingRequest:
        def __init__(self, peer, action, top_msg_id=None):
            self.peer = peer
            self.action = action
            self.top_msg_id = top_msg_id

    class SendReactionRequest:
        def __init__(self, peer, msg_id, reaction):
            self.peer = peer
            self.msg_id = msg_id
            self.reaction = reaction

    class UploadMediaRequest:
        def __init__(self, peer, media):
            self.peer = peer
            self.media = media

    class ReactionEmoji:
        def __init__(self, emoticon):
            self.emoticon = emoticon

    class InputMediaUploadedPhoto:
        pass

    messages_module.SetTypingRequest = SetTypingRequest
    messages_module.SendReactionRequest = SendReactionRequest
    messages_module.UploadMediaRequest = UploadMediaRequest
    functions_module.messages = messages_module
    types_module.ReactionEmoji = ReactionEmoji
    types_module.InputMediaUploadedPhoto = InputMediaUploadedPhoto
    types_module.InputMediaUploadedDocument = type("InputMediaUploadedDocument", (), {})
    types_module.InputMediaPhotoExternal = type("InputMediaPhotoExternal", (), {})
    types_module.InputMediaDocumentExternal = type("InputMediaDocumentExternal", (), {})
    types_module.InputSingleMedia = type("InputSingleMedia", (), {})
    telethon_module.functions = functions_module
    telethon_module.types = types_module
    utils_module.get_input_media = lambda media, **kwargs: media

    sys.modules["telethon"] = telethon_module
    sys.modules["telethon.functions"] = functions_module
    sys.modules["telethon.functions.messages"] = messages_module
    sys.modules["telethon.types"] = types_module
    sys.modules["telethon.utils"] = utils_module


@contextmanager
def _isolated_stub_modules():
    module_names = [
        "astrbot",
        "astrbot.api",
        "telethon",
        "telethon.functions",
        "telethon.functions.messages",
        "telethon.types",
        "telethon.utils",
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


def _load_message_executor_module():
    with _isolated_stub_modules():
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

        module_name = f"{services_name}.message_executor"
        module_path = services_path / "message_executor.py"
        spec = importlib.util.spec_from_file_location(module_name, module_path)
        module = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        return module


message_executor_module = _load_message_executor_module()
TelethonMessageExecutor = message_executor_module.TelethonMessageExecutor


class _FakeClient:
    def __init__(self):
        self.requests = []

    async def __call__(self, request):
        self.requests.append(request)
        return types.SimpleNamespace(photo=types.SimpleNamespace(spoiler=False))


class _FakeEvent:
    def __init__(self):
        self.client = _FakeClient()
        self.peer = 123
        self.thread_id = 456
        self.message_obj = types.SimpleNamespace(
            message_id=77,
            sender=types.SimpleNamespace(user_id=88),
            raw_message=types.SimpleNamespace(),
        )

    def _effective_reply_to(self, reply_to):
        return reply_to if reply_to is not None else self.thread_id


class TelethonMessageExecutorTests(unittest.IsolatedAsyncioTestCase):
    async def test_message_log_context_reads_event_state(self):
        with _isolated_stub_modules():
            executor = TelethonMessageExecutor(build_input_media=None)
            event = _FakeEvent()

            event_context = executor.build_event_context(event, 99)
            context = executor.message_log_context(event, 99)

            self.assertEqual(event_context.chat_id, 123)
            self.assertEqual(event_context.thread_id, 456)
            self.assertEqual(event_context.msg_id, 77)
            self.assertEqual(event_context.sender_id, 88)
            self.assertEqual(event_context.reply_to, 99)
            self.assertEqual(
                context,
                {
                    "chat_id": 123,
                    "thread_id": 456,
                    "msg_id": 77,
                    "sender_id": 88,
                    "reply_to": 99,
                },
            )

    async def test_send_chat_action_builds_set_typing_request(self):
        with _isolated_stub_modules():
            executor = TelethonMessageExecutor(build_input_media=None)
            event = _FakeEvent()

            await executor.send_chat_action(event, action="typing")

            request = event.client.requests[0]
            self.assertEqual(type(request).__name__, "SetTypingRequest")
            self.assertEqual(request.peer, 123)
            self.assertEqual(request.top_msg_id, 456)

    async def test_react_falls_back_to_mtproto_request(self):
        with _isolated_stub_modules():
            executor = TelethonMessageExecutor(build_input_media=None)
            event = _FakeEvent()

            await executor.react(event, "👍")

            request = event.client.requests[0]
            self.assertEqual(type(request).__name__, "SendReactionRequest")
            self.assertEqual(request.peer, 123)
            self.assertEqual(request.msg_id, 77)
            self.assertEqual(request.reaction[0].emoticon, "👍")
