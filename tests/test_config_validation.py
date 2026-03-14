import asyncio
import importlib.util
import sys
import types
import unittest
from pathlib import Path


def _install_astrbot_stubs() -> None:
    astrbot_module = types.ModuleType("astrbot")
    api_module = types.ModuleType("astrbot.api")
    event_module = types.ModuleType("astrbot.api.event")
    message_components_module = types.ModuleType("astrbot.api.message_components")
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
        pass

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

    class AstrBotMessage:
        pass

    class MessageMember:
        pass

    class MessageType:
        GROUP_MESSAGE = "group"
        FRIEND_MESSAGE = "friend"

    class PlatformMetadata:
        def __init__(self, **kwargs):
            for key, value in kwargs.items():
                setattr(self, key, value)

    class Platform:
        def __init__(self, platform_config, event_queue):
            self.config = platform_config
            self.event_queue = event_queue

        def commit_event(self, event):
            return None

    def register_platform_adapter(*args, **kwargs):
        def decorator(cls):
            return cls

        return decorator

    class MessageSesion:
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
    platform_module.AstrBotMessage = AstrBotMessage
    platform_module.MessageMember = MessageMember
    platform_module.MessageType = MessageType
    platform_module.Platform = Platform
    platform_module.PlatformMetadata = PlatformMetadata
    platform_module.register_platform_adapter = register_platform_adapter
    astr_message_event_module.MessageSesion = MessageSesion

    sys.modules["astrbot"] = astrbot_module
    sys.modules["astrbot.api"] = api_module
    sys.modules["astrbot.api.event"] = event_module
    sys.modules["astrbot.api.message_components"] = message_components_module
    sys.modules["astrbot.api.platform"] = platform_module
    sys.modules["astrbot.core.platform.astr_message_event"] = astr_message_event_module


def _install_pydantic_stubs() -> None:
    pydantic_module = types.ModuleType("pydantic")
    pydantic_v1_module = types.ModuleType("pydantic.v1")

    class _PrivateAttr:
        def __init__(self, default=None):
            self.default = default
            self.name = None

        def __set_name__(self, owner, name):
            self.name = name

        def __get__(self, instance, owner=None):
            if instance is None:
                return self
            return instance.__dict__.get(self.name, self.default)

        def __set__(self, instance, value):
            instance.__dict__[self.name] = value

    pydantic_module.PrivateAttr = _PrivateAttr
    pydantic_v1_module.PrivateAttr = _PrivateAttr
    sys.modules["pydantic"] = pydantic_module
    sys.modules["pydantic.v1"] = pydantic_v1_module


def _install_telethon_stubs() -> None:
    telethon_module = types.ModuleType("telethon")
    network_module = types.ModuleType("telethon.network")
    connection_module = types.ModuleType("telethon.network.connection")
    sessions_module = types.ModuleType("telethon.sessions")
    events_module = types.ModuleType("telethon.events")
    tl_module = types.ModuleType("telethon.tl")
    tl_types_module = types.ModuleType("telethon.tl.types")

    class TelegramClient:
        def __init__(self, *args, **kwargs):
            return None

    class StringSession:
        def __init__(self, value):
            self.value = value

    class _EventFactory:
        def __call__(self, *args, **kwargs):
            return ("event", args, kwargs)

    class _NewMessage:
        Event = object

        def __call__(self, *args, **kwargs):
            return ("new_message", args, kwargs)

    class _Raw:
        def __call__(self, *args, **kwargs):
            return ("raw", args, kwargs)

    def _stub_type(name):
        return type(name, (), {})

    telethon_module.TelegramClient = TelegramClient
    telethon_module.events = events_module
    network_module.connection = connection_module
    sessions_module.StringSession = StringSession
    events_module.NewMessage = _NewMessage()
    events_module.Raw = _Raw()

    for name in [
        "DocumentAttributeAudio",
        "DocumentAttributeFilename",
        "DocumentAttributeSticker",
        "DocumentAttributeVideo",
        "GeoPointEmpty",
        "MessageEntityMention",
        "MessageEntityMentionName",
        "MessageEntityTextUrl",
        "MessageMediaContact",
        "MessageMediaGeo",
        "MessageMediaGeoLive",
    ]:
        setattr(tl_types_module, name, _stub_type(name))

    sys.modules["telethon"] = telethon_module
    sys.modules["telethon.network"] = network_module
    sys.modules["telethon.network.connection"] = connection_module
    sys.modules["telethon.sessions"] = sessions_module
    sys.modules["telethon.events"] = events_module
    sys.modules["telethon.tl"] = tl_module
    sys.modules["telethon.tl.types"] = tl_types_module


def _install_local_module_stubs() -> None:
    telethon_event_module = types.ModuleType("telethon_adapter.telethon_event")
    message_converter_module = types.ModuleType("telethon_adapter.message_converter")

    class TelethonMessageConverter:
        def __init__(self, adapter):
            self.adapter = adapter

    telethon_event_module.TelethonEvent = type("TelethonEvent", (), {})
    message_converter_module.TelethonMessageConverter = TelethonMessageConverter

    sys.modules["telethon_adapter.telethon_event"] = telethon_event_module
    sys.modules["telethon_adapter.message_converter"] = message_converter_module


def _load_adapter_module():
    _install_astrbot_stubs()
    _install_pydantic_stubs()
    _install_telethon_stubs()
    _install_local_module_stubs()
    package_module = types.ModuleType("telethon_adapter")
    package_module.__path__ = [str(Path(__file__).resolve().parents[1] / "telethon_adapter")]
    sys.modules["telethon_adapter"] = package_module
    module_path = Path(__file__).resolve().parents[1] / "telethon_adapter" / "telethon_adapter.py"
    spec = importlib.util.spec_from_file_location(
        "telethon_adapter.telethon_adapter",
        module_path,
    )
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


class ConfigValidationTests(unittest.TestCase):
    def test_init_tolerates_dirty_numeric_config(self):
        module = _load_adapter_module()
        adapter = module.TelethonPlatformAdapter(
            {
                "api_id": "bad",
                "incoming_media_ttl_seconds": "",
                "telethon_media_group_timeout": "oops",
                "telethon_media_group_max_wait": None,
                "proxy_port": "abc",
                "proxy_type": "mtproxy",
            },
            {},
            asyncio.Queue(),
        )

        self.assertEqual(adapter.api_id, 0)
        self.assertEqual(adapter.incoming_media_ttl_seconds, 600.0)
        self.assertEqual(adapter.media_group_timeout, 1.2)
        self.assertEqual(adapter.media_group_max_wait, 8.0)
        self.assertEqual(adapter.proxy_port, 0)
        self.assertEqual(adapter.proxy_type, "mtproto")

    def test_validate_config_reports_invalid_required_field(self):
        module = _load_adapter_module()
        adapter = module.TelethonPlatformAdapter(
            {
                "api_id": "bad",
                "api_hash": "hash",
                "session_string": "session",
            },
            {},
            asyncio.Queue(),
        )

        with self.assertRaisesRegex(ValueError, "api_id.*'bad'.*API ID"):
            adapter._validate_config()

    def test_validate_config_reports_invalid_proxy_settings(self):
        module = _load_adapter_module()
        adapter = module.TelethonPlatformAdapter(
            {
                "api_id": 123,
                "api_hash": "hash",
                "session_string": "session",
                "proxy_type": "http",
                "proxy_host": "",
                "proxy_port": "abc",
            },
            {},
            asyncio.Queue(),
        )

        with self.assertRaisesRegex(ValueError, "proxy_host.*''.*代理主机"):
            adapter._validate_config()

    def test_validate_config_requires_mtproto_proxy_secret(self):
        module = _load_adapter_module()
        adapter = module.TelethonPlatformAdapter(
            {
                "api_id": 123,
                "api_hash": "hash",
                "session_string": "session",
                "proxy_type": "mtproto",
                "proxy_host": "127.0.0.1",
                "proxy_port": "443",
                "proxy_secret": "",
            },
            {},
            asyncio.Queue(),
        )

        with self.assertRaisesRegex(ValueError, "proxy_secret.*''.*MTProto"):
            adapter._validate_config()

    def test_validate_config_allows_non_positive_media_ttl(self):
        module = _load_adapter_module()
        adapter = module.TelethonPlatformAdapter(
            {
                "api_id": 123,
                "api_hash": "hash",
                "session_string": "session",
                "incoming_media_ttl_seconds": "-1",
                "telethon_media_group_timeout": "0",
                "telethon_media_group_max_wait": "1",
            },
            {},
            asyncio.Queue(),
        )

        adapter._validate_config()


if __name__ == "__main__":
    unittest.main()
