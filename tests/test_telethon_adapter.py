import importlib.util
import sys
import types
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _install_astrbot_stubs() -> None:
    astrbot_module = types.ModuleType("astrbot")
    api_module = types.ModuleType("astrbot.api")
    event_module = types.ModuleType("astrbot.api.event")
    platform_module = types.ModuleType("astrbot.api.platform")
    astr_message_event_module = types.ModuleType("astrbot.core.platform.astr_message_event")

    class _Logger:
        def info(self, *args, **kwargs):
            return None

        def warning(self, *args, **kwargs):
            return None

        def exception(self, *args, **kwargs):
            return None

    class MessageChain:
        def __init__(self, chain=None):
            self.chain = chain or []

        def get_plain_text(self):
            return ""

    class AstrBotMessage:
        pass

    class Platform:
        def __init__(self, platform_config=None, event_queue=None):
            self.config = platform_config or {}
            self.event_queue = event_queue

        async def send_by_session(self, session, message_chain):
            return None

    class PlatformMetadata:
        def __init__(self, **kwargs):
            for key, value in kwargs.items():
                setattr(self, key, value)

    def register_platform_adapter(*args, **kwargs):
        def decorator(cls):
            return cls

        return decorator

    class MessageSesion:
        def __init__(self, session_id="", message_type="group"):
            self.session_id = session_id
            self.message_type = message_type

    api_module.logger = _Logger()
    event_module.MessageChain = MessageChain
    platform_module.AstrBotMessage = AstrBotMessage
    platform_module.Platform = Platform
    platform_module.PlatformMetadata = PlatformMetadata
    platform_module.register_platform_adapter = register_platform_adapter
    astr_message_event_module.MessageSesion = MessageSesion

    sys.modules["astrbot"] = astrbot_module
    sys.modules["astrbot.api"] = api_module
    sys.modules["astrbot.api.event"] = event_module
    sys.modules["astrbot.api.platform"] = platform_module
    sys.modules["astrbot.core.platform.astr_message_event"] = astr_message_event_module


def _install_telethon_stubs() -> None:
    telethon_module = types.ModuleType("telethon")
    events_module = types.ModuleType("telethon.events")
    functions_module = types.ModuleType("telethon.functions")
    types_module = types.ModuleType("telethon.types")
    network_module = types.ModuleType("telethon.network")
    sessions_module = types.ModuleType("telethon.sessions")

    class TelegramClient:
        pass

    class _NewMessage:
        class Event:
            pass

    class MemorySession:
        pass

    events_module.NewMessage = _NewMessage
    network_module.connection = types.SimpleNamespace()
    sessions_module.MemorySession = MemorySession
    telethon_module.TelegramClient = TelegramClient
    telethon_module.events = events_module
    telethon_module.functions = functions_module
    telethon_module.types = types_module

    sys.modules["telethon"] = telethon_module
    sys.modules["telethon.events"] = events_module
    sys.modules["telethon.functions"] = functions_module
    sys.modules["telethon.types"] = types_module
    sys.modules["telethon.network"] = network_module
    sys.modules["telethon.sessions"] = sessions_module


def _install_local_module_stubs() -> None:
    package_name = "telethon_adapter"
    package_module = types.ModuleType(package_name)
    package_module.__path__ = [str(PROJECT_ROOT / package_name)]
    sys.modules[package_name] = package_module

    config_module = types.ModuleType(f"{package_name}.config")
    config_module.DEFAULT_CONFIG_TEMPLATE = {}
    config_module.TELETHON_CONFIG_METADATA = {}
    config_module.TELETHON_I18N_RESOURCES = {}
    config_module.apply_config = lambda adapter: None
    config_module.config_error = lambda *args, **kwargs: None
    config_module.validate_config = lambda adapter: None

    message_converter_module = types.ModuleType(f"{package_name}.message_converter")

    class TelethonMessageConverter:
        def __init__(self, adapter) -> None:
            self.adapter = adapter

        def resolve_is_private(self, message, is_private):
            return is_private

        def extract_thread_id(self, message):
            return None

        def build_session_id(self, chat_id, thread_id, is_private=False):
            return chat_id

    message_converter_module.TelethonMessageConverter = TelethonMessageConverter

    telethon_event_module = types.ModuleType(f"{package_name}.telethon_event")

    class TelethonEvent:
        pass

    telethon_event_module.TelethonEvent = TelethonEvent

    sys.modules[f"{package_name}.config"] = config_module
    sys.modules[f"{package_name}.message_converter"] = message_converter_module
    sys.modules[f"{package_name}.telethon_event"] = telethon_event_module


def _load_telethon_adapter_module():
    _install_astrbot_stubs()
    _install_telethon_stubs()
    _install_local_module_stubs()

    module_path = PROJECT_ROOT / "telethon_adapter" / "telethon_adapter.py"
    spec = importlib.util.spec_from_file_location(
        "telethon_adapter.telethon_adapter",
        module_path,
    )
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules["telethon_adapter.telethon_adapter"] = module
    spec.loader.exec_module(module)
    return module


class TelethonAdapterTests(unittest.IsolatedAsyncioTestCase):
    async def test_process_grouped_message_keeps_empty_message_str_without_text(self):
        module = _load_telethon_adapter_module()
        adapter = object.__new__(module.TelethonPlatformAdapter)
        committed = []

        async def _convert_message(event, include_reply=True):
            if getattr(event.message, "id", 0) == 1:
                return types.SimpleNamespace(message=["image-1"], message_str="")
            return types.SimpleNamespace(message=["image-2"], message_str="")

        adapter._media_group_cache = {
            ("session", 10): {
                "items": [
                    types.SimpleNamespace(message=types.SimpleNamespace(id=1)),
                    types.SimpleNamespace(message=types.SimpleNamespace(id=2)),
                ]
            }
        }
        adapter._convert_message = _convert_message
        adapter._commit_abm = committed.append

        await module.TelethonPlatformAdapter._process_grouped_message(
            adapter,
            ("session", 10),
            0,
        )

        self.assertEqual(len(committed), 1)
        self.assertEqual(committed[0].message, ["image-1", "image-2"])
        self.assertEqual(committed[0].message_str, "")


if __name__ == "__main__":
    unittest.main()
