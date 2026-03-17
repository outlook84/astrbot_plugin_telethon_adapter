import asyncio
import importlib.util
import os
import sys
import tempfile
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

        def error(self, *args, **kwargs):
            return None

        def debug(self, *args, **kwargs):
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

    class MessageMember(_BaseComponent):
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
    errors_module = types.ModuleType("telethon.errors")
    errors_common_module = types.ModuleType("telethon.errors.common")
    network_module = types.ModuleType("telethon.network")
    connection_module = types.ModuleType("telethon.network.connection")
    sessions_module = types.ModuleType("telethon.sessions")
    events_module = types.ModuleType("telethon.events")
    tl_module = types.ModuleType("telethon.tl")
    tl_types_module = types.ModuleType("telethon.tl.types")

    class TelegramClient:
        def __init__(self, *args, **kwargs):
            return None

    class _RPCError(Exception):
        pass

    class UnauthorizedError(_RPCError):
        pass

    class AuthKeyError(_RPCError):
        pass

    class BadRequestError(_RPCError):
        pass

    class ForbiddenError(_RPCError):
        pass

    class NotFoundError(_RPCError):
        pass

    class InvalidDCError(_RPCError):
        pass

    class ServerError(_RPCError):
        pass

    class TimedOutError(_RPCError):
        pass

    class FloodError(_RPCError):
        pass

    class AuthKeyNotFound(Exception):
        pass

    class SecurityError(Exception):
        pass

    class InvalidBufferError(BufferError):
        pass

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
    telethon_module.errors = errors_module
    network_module.connection = connection_module
    sessions_module.StringSession = StringSession
    events_module.NewMessage = _NewMessage()
    events_module.Raw = _Raw()
    errors_module.RPCError = _RPCError
    errors_module.UnauthorizedError = UnauthorizedError
    errors_module.AuthKeyError = AuthKeyError
    errors_module.BadRequestError = BadRequestError
    errors_module.ForbiddenError = ForbiddenError
    errors_module.NotFoundError = NotFoundError
    errors_module.InvalidDCError = InvalidDCError
    errors_module.ServerError = ServerError
    errors_module.TimedOutError = TimedOutError
    errors_module.FloodError = FloodError
    errors_module.common = errors_common_module
    errors_common_module.AuthKeyNotFound = AuthKeyNotFound
    errors_common_module.SecurityError = SecurityError
    errors_common_module.InvalidBufferError = InvalidBufferError

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
    sys.modules["telethon.errors"] = errors_module
    sys.modules["telethon.errors.common"] = errors_common_module
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

        @staticmethod
        def extract_thread_id(message):
            reply_to = getattr(message, "reply_to", None)
            return str(getattr(reply_to, "reply_to_top_id", "")) or None

        @staticmethod
        def build_session_id(chat_id, thread_id, *, is_private):
            if is_private or not thread_id:
                return chat_id
            return f"{chat_id}#{thread_id}"

        @staticmethod
        def resolve_is_private(message, event_is_private=False):
            if event_is_private:
                return True
            peer = getattr(message, "peer_id", None)
            return type(peer).__name__ == "PeerUser"

        @staticmethod
        def is_topic_service_message(message):
            action = getattr(message, "action", None)
            return type(action).__name__.startswith("MessageActionTopic") if action is not None else False

        async def should_treat_reply_to_self_as_command(self, message, *, is_private):
            return bool(
                getattr(self.adapter, "reply_to_self_triggers_command", False)
                and getattr(message, "reply_to_self_trigger", False)
                and not is_private
            )

    telethon_event_module.TelethonEvent = type("TelethonEvent", (), {})
    message_converter_module.TelethonMessageConverter = TelethonMessageConverter

    sys.modules["telethon_adapter.telethon_event"] = telethon_event_module
    sys.modules["telethon_adapter.message_converter"] = message_converter_module


def _load_adapter_module():
    for module_name in list(sys.modules):
        if module_name == "telethon_adapter" or module_name.startswith("telethon_adapter."):
            sys.modules.pop(module_name, None)
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


def _load_message_converter_module():
    for module_name in list(sys.modules):
        if module_name == "telethon_adapter" or module_name.startswith("telethon_adapter."):
            sys.modules.pop(module_name, None)
    _install_astrbot_stubs()
    _install_pydantic_stubs()
    _install_telethon_stubs()
    package_module = types.ModuleType("telethon_adapter")
    package_module.__path__ = [str(Path(__file__).resolve().parents[1] / "telethon_adapter")]
    sys.modules["telethon_adapter"] = package_module

    lazy_media_module = types.ModuleType("telethon_adapter.lazy_media")
    lazy_media_module.LazyFile = type("LazyFile", (), {})
    lazy_media_module.LazyImage = type("LazyImage", (), {})
    lazy_media_module.LazyRecord = type("LazyRecord", (), {})
    lazy_media_module.LazyVideo = type("LazyVideo", (), {})
    lazy_media_module.TelethonLazyMedia = type("TelethonLazyMedia", (), {})
    sys.modules["telethon_adapter.lazy_media"] = lazy_media_module

    module_path = Path(__file__).resolve().parents[1] / "telethon_adapter" / "message_converter.py"
    spec = importlib.util.spec_from_file_location(
        "telethon_adapter.message_converter",
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
        self.assertFalse(adapter.debug_logging)

    def test_init_parses_debug_logging_flag(self):
        module = _load_adapter_module()
        adapter = module.TelethonPlatformAdapter(
            {
                "api_id": 123,
                "api_hash": "hash",
                "session_string": "session",
                "debug_logging": "true",
            },
            {},
            asyncio.Queue(),
        )

        self.assertTrue(adapter.debug_logging)

    def test_init_parses_reply_to_self_triggers_command_flag(self):
        module = _load_adapter_module()
        adapter = module.TelethonPlatformAdapter(
            {
                "api_id": 123,
                "api_hash": "hash",
                "session_string": "session",
                "reply_to_self_triggers_command": "true",
            },
            {},
            asyncio.Queue(),
        )

        self.assertTrue(adapter.reply_to_self_triggers_command)

    def test_build_adapter_capability_uses_premium_limit_for_userbot(self):
        module = _load_adapter_module()
        adapter = module.TelethonPlatformAdapter(
            {
                "api_id": 123,
                "api_hash": "hash",
                "session_string": "session",
            },
            {},
            asyncio.Queue(),
        )
        adapter._is_premium_user = True

        capability = adapter._build_adapter_capability()

        self.assertTrue(capability["supports_spoiler"])
        self.assertEqual(capability["max_items"], 10)
        self.assertEqual(capability["supported_types"], ["image", "video"])
        self.assertEqual(
            capability["upload_constraints"]["max_single_file_bytes"],
            module.TELEGRAM_MAX_FILE_BYTES_PREMIUM,
        )

    def test_update_premium_status_tracks_get_me_flag(self):
        module = _load_adapter_module()
        adapter = module.TelethonPlatformAdapter(
            {
                "api_id": 123,
                "api_hash": "hash",
                "session_string": "session",
            },
            {},
            asyncio.Queue(),
        )

        adapter._update_premium_status(types.SimpleNamespace(premium=True))
        self.assertTrue(adapter._is_premium_user)

        adapter._update_premium_status(types.SimpleNamespace())
        self.assertFalse(adapter._is_premium_user)

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

    def test_validate_config_reports_invalid_required_field_in_english(self):
        module = _load_adapter_module()
        adapter = module.TelethonPlatformAdapter(
            {
                "api_id": "bad",
                "api_hash": "hash",
                "session_string": "session",
                "language": "en-US",
            },
            {},
            asyncio.Queue(),
        )

        with self.assertRaisesRegex(
            ValueError,
            r"api_id.*'bad'.*positive integer API ID",
        ):
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

    def test_build_client_kwargs_supports_socks5_proxy_tuple(self):
        module = _load_adapter_module()
        module.ProxyType = types.SimpleNamespace(
            SOCKS5="SOCKS5",
            SOCKS4="SOCKS4",
            HTTP="HTTP",
        )
        adapter = module.TelethonPlatformAdapter(
            {
                "api_id": 123,
                "api_hash": "hash",
                "session_string": "session",
                "proxy_type": "socks5",
                "proxy_host": "127.0.0.1",
                "proxy_port": "1080",
                "proxy_rdns": True,
                "proxy_username": "user",
                "proxy_password": "pass",
            },
            {},
            asyncio.Queue(),
        )

        kwargs = adapter._build_client_kwargs()

        self.assertEqual(
            kwargs,
            {
                "auto_reconnect": True,
                "connection_retries": 5,
                "proxy": (
                    "SOCKS5",
                    "127.0.0.1",
                    1080,
                    True,
                    "user",
                    "pass",
                ),
                "retry_delay": 1,
            },
        )

    def test_build_client_kwargs_supports_mtproto_proxy_tuple(self):
        module = _load_adapter_module()
        mtproto_connection = object()
        module.connection.ConnectionTcpMTProxyRandomizedIntermediate = mtproto_connection
        adapter = module.TelethonPlatformAdapter(
            {
                "api_id": 123,
                "api_hash": "hash",
                "session_string": "session",
                "proxy_type": "mtproto",
                "proxy_host": "127.0.0.1",
                "proxy_port": "443",
                "proxy_secret": "deadbeef",
            },
            {},
            asyncio.Queue(),
        )

        kwargs = adapter._build_client_kwargs()

        self.assertTrue(kwargs["auto_reconnect"])
        self.assertEqual(kwargs["connection_retries"], 5)
        self.assertEqual(kwargs["connection"], mtproto_connection)
        self.assertEqual(kwargs["proxy"], ("127.0.0.1", 443, "deadbeef"))
        self.assertEqual(kwargs["retry_delay"], 1)

    def test_build_client_kwargs_includes_explicit_telethon_reconnect_defaults(self):
        module = _load_adapter_module()
        adapter = module.TelethonPlatformAdapter(
            {
                "api_id": 123,
                "api_hash": "hash",
                "session_string": "session",
            },
            {},
            asyncio.Queue(),
        )

        kwargs = adapter._build_client_kwargs()

        self.assertEqual(
            kwargs,
            {
                "auto_reconnect": True,
                "connection_retries": 5,
                "retry_delay": 1,
            },
        )


class AdapterBehaviorTests(unittest.IsolatedAsyncioTestCase):
    async def test_should_retry_client_error_distinguishes_telethon_error_types(self):
        module = _load_adapter_module()
        adapter = module.TelethonPlatformAdapter(
            {
                "api_id": 123,
                "api_hash": "hash",
                "session_string": "session",
            },
            {},
            asyncio.Queue(),
        )

        self.assertTrue(adapter._should_retry_client_error(module.telethon_errors.ServerError()))
        self.assertTrue(adapter._should_retry_client_error(module.telethon_errors.TimedOutError()))
        self.assertFalse(adapter._should_retry_client_error(module.telethon_errors.AuthKeyError()))
        self.assertFalse(
            adapter._should_retry_client_error(module.telethon_errors.common.AuthKeyNotFound())
        )
        self.assertFalse(adapter._should_retry_client_error(RuntimeError("network parser bug")))

    async def test_run_recreates_client_after_disconnect(self):
        module = _load_adapter_module()
        adapter = module.TelethonPlatformAdapter(
            {
                "api_id": 123,
                "api_hash": "hash",
                "session_string": "session",
            },
            {},
            asyncio.Queue(),
        )
        sleep_delays = []
        created_clients = []

        class _FakeClient:
            def __init__(self, index):
                self.index = index
                self.handlers = []
                self.disconnect_calls = 0

            async def connect(self):
                return None

            async def is_user_authorized(self):
                return True

            async def get_me(self):
                return types.SimpleNamespace(id=1000 + self.index, username=f"user{self.index}")

            def add_event_handler(self, handler, event):
                self.handlers.append((handler, event))

            async def run_until_disconnected(self):
                if self.index >= 2:
                    adapter._stop_requested = True
                return None

            async def disconnect(self):
                self.disconnect_calls += 1

        def fake_create_client(client_kwargs):
            self.assertTrue(client_kwargs["auto_reconnect"])
            self.assertEqual(client_kwargs["connection_retries"], 5)
            self.assertEqual(client_kwargs["retry_delay"], 1)
            client = _FakeClient(len(created_clients) + 1)
            created_clients.append(client)
            return client

        async def fake_sleep(delay):
            sleep_delays.append(delay)

        adapter._create_client = fake_create_client
        adapter._sleep_before_reconnect = fake_sleep

        await adapter.run()

        self.assertEqual(len(created_clients), 2)
        self.assertEqual(sleep_delays, [1.0])
        self.assertEqual(adapter.self_id, "1002")
        self.assertEqual(adapter.self_username, "user2")
        self.assertGreaterEqual(created_clients[0].disconnect_calls, 1)
        self.assertGreaterEqual(created_clients[1].disconnect_calls, 1)
        self.assertEqual(len(created_clients[0].handlers), 2)

    async def test_run_does_not_retry_unauthorized_session(self):
        module = _load_adapter_module()
        adapter = module.TelethonPlatformAdapter(
            {
                "api_id": 123,
                "api_hash": "hash",
                "session_string": "session",
            },
            {},
            asyncio.Queue(),
        )
        created_clients = []
        sleep_delays = []

        class _FakeClient:
            async def connect(self):
                return None

            async def is_user_authorized(self):
                return False

            async def disconnect(self):
                return None

        def fake_create_client(client_kwargs):
            created_clients.append(client_kwargs)
            return _FakeClient()

        async def fake_sleep(delay):
            sleep_delays.append(delay)

        adapter._create_client = fake_create_client
        adapter._sleep_before_reconnect = fake_sleep

        with self.assertRaisesRegex(RuntimeError, "unauthorized"):
            await adapter.run()

        self.assertEqual(len(created_clients), 1)
        self.assertEqual(sleep_delays, [])

    async def test_run_stops_retrying_when_clean_disconnect_leaves_session_unauthorized(self):
        module = _load_adapter_module()
        adapter = module.TelethonPlatformAdapter(
            {
                "api_id": 123,
                "api_hash": "hash",
                "session_string": "session",
            },
            {},
            asyncio.Queue(),
        )
        created_clients = []
        sleep_delays = []

        class _FakeClient:
            def __init__(self):
                self.handlers = []
                self.authorized_checks = 0

            async def connect(self):
                return None

            async def is_user_authorized(self):
                self.authorized_checks += 1
                return self.authorized_checks == 1

            async def get_me(self):
                return types.SimpleNamespace(id=1001, username="user1")

            def add_event_handler(self, handler, event):
                self.handlers.append((handler, event))

            async def run_until_disconnected(self):
                return None

            async def disconnect(self):
                return None

        def fake_create_client(client_kwargs):
            created_clients.append(client_kwargs)
            return _FakeClient()

        async def fake_sleep(delay):
            sleep_delays.append(delay)

        adapter._create_client = fake_create_client
        adapter._sleep_before_reconnect = fake_sleep

        with self.assertRaisesRegex(RuntimeError, "no longer authorized"):
            await adapter.run()

        self.assertEqual(len(created_clients), 1)
        self.assertEqual(sleep_delays, [])

    async def test_on_new_message_allows_group_bot_sender_by_default(self):
        module = _load_adapter_module()
        adapter = module.TelethonPlatformAdapter(
            {
                "api_id": 123,
                "api_hash": "hash",
                "session_string": "session",
                "trigger_prefix": "-astr",
            },
            {},
            asyncio.Queue(),
        )
        adapter._running = True
        converted = []
        committed = []

        async def fake_convert_message(event, include_reply=True):
            converted.append((event.message.id, include_reply))
            return types.SimpleNamespace(
                message_id=str(event.message.id),
                message_str=event.message.raw_text,
                message=[],
                sender=types.SimpleNamespace(user_id="777", nickname="bot"),
                session_id=str(event.chat_id),
                type="group",
            )

        class _Event:
            def __init__(self):
                self.chat_id = "100"
                self.sender_id = "777"
                self.is_private = False
                self.message = types.SimpleNamespace(
                    id=10,
                    raw_text="-astr hello",
                    grouped_id=None,
                    out=False,
                )

            async def get_sender(self):
                return types.SimpleNamespace(id=777, bot=True)

        adapter._convert_message = fake_convert_message
        adapter._commit_abm = committed.append

        await adapter._on_new_message(_Event())

        self.assertEqual(converted, [(10, True)])
        self.assertEqual(len(committed), 1)

    async def test_process_grouped_message_merges_items_and_uses_prefixed_trigger(self):
        module = _load_adapter_module()
        adapter = module.TelethonPlatformAdapter(
            {
                "api_id": 123,
                "api_hash": "hash",
                "session_string": "session",
                "trigger_prefix": "-astr",
            },
            {},
            asyncio.Queue(),
        )
        converted_calls = []
        committed = []

        def make_abm(message_id: str, message_str: str, parts: list[str]):
            return types.SimpleNamespace(
                message_id=message_id,
                message_str=message_str,
                message=list(parts),
                sender=types.SimpleNamespace(user_id="42", nickname="alice"),
                session_id="100",
            )

        async def fake_convert_message(event, include_reply=True):
            converted_calls.append((event.message.id, include_reply))
            if event.message.id == 11:
                return make_abm("11", "caption", ["head"])
            return make_abm(str(event.message.id), "", [f"part-{event.message.id}"])

        adapter._convert_message = fake_convert_message
        adapter._commit_abm = committed.append

        event1 = types.SimpleNamespace(
            chat_id="100",
            sender_id="42",
            message=types.SimpleNamespace(id=10, raw_text="", reply_to=None),
        )
        event2 = types.SimpleNamespace(
            chat_id="100",
            sender_id="42",
            message=types.SimpleNamespace(id=11, raw_text="-astr caption", reply_to=None),
        )
        adapter._media_group_cache[("100", 999)] = {
            "created_at": 0.0,
            "items": [event1, event2],
            "task": None,
        }

        await adapter._process_grouped_message(("100", 999), delay=0)

        self.assertEqual(converted_calls, [(11, True), (10, False)])
        self.assertEqual(len(committed), 1)
        self.assertEqual(committed[0].message_str, "caption")
        self.assertEqual(committed[0].message, ["head", "part-10"])

    async def test_on_new_message_ignores_topic_service_message(self):
        module = _load_adapter_module()
        adapter = module.TelethonPlatformAdapter(
            {
                "api_id": 123,
                "api_hash": "hash",
                "session_string": "session",
            },
            {},
            asyncio.Queue(),
        )
        adapter._running = True
        converted = []
        committed = []

        async def fake_convert_message(event, include_reply=True):
            converted.append((event.message.id, include_reply))
            return types.SimpleNamespace(session_id=str(event.chat_id), message_str="", message=[], sender=None)

        adapter._convert_message = fake_convert_message
        adapter._commit_abm = committed.append

        class _Event:
            def __init__(self):
                self.chat_id = "100"
                self.sender_id = "777"
                self.is_private = False
                self.message = types.SimpleNamespace(
                    id=15,
                    raw_text="",
                    grouped_id=None,
                    out=False,
                    action=type("MessageActionTopicCreate", (), {})(),
                )

            async def get_sender(self):
                return types.SimpleNamespace(id=777, bot=True)

        await adapter._on_new_message(_Event())

        self.assertEqual(converted, [])
        self.assertEqual(committed, [])

    async def test_on_new_message_allows_reply_to_self_trigger_without_prefix(self):
        module = _load_adapter_module()
        adapter = module.TelethonPlatformAdapter(
            {
                "api_id": 123,
                "api_hash": "hash",
                "session_string": "session",
                "trigger_prefix": "-astr",
                "reply_to_self_triggers_command": True,
            },
            {},
            asyncio.Queue(),
        )
        adapter._running = True
        converted = []
        committed = []

        async def fake_convert_message(event, include_reply=True):
            converted.append((event.message.id, include_reply))
            return types.SimpleNamespace(
                message_id=str(event.message.id),
                message_str=event.message.raw_text,
                message=[],
                sender=types.SimpleNamespace(user_id="123", nickname="alice"),
                session_id=str(event.chat_id),
                type="group",
            )

        class _Event:
            def __init__(self):
                self.chat_id = "100"
                self.sender_id = "123"
                self.is_private = False
                self.message = types.SimpleNamespace(
                    id=16,
                    raw_text="tg status",
                    grouped_id=None,
                    out=False,
                    reply_to_self_trigger=True,
                )

            async def get_sender(self):
                return types.SimpleNamespace(id=123, bot=False)

        adapter._convert_message = fake_convert_message
        adapter._commit_abm = committed.append

        await adapter._on_new_message(_Event())

        self.assertEqual(converted, [(16, True)])
        self.assertEqual(len(committed), 1)

    async def test_grouped_message_session_id_includes_topic_thread(self):
        module = _load_adapter_module()
        adapter = module.TelethonPlatformAdapter(
            {
                "api_id": 123,
                "api_hash": "hash",
                "session_string": "session",
            },
            {},
            asyncio.Queue(),
        )

        event = types.SimpleNamespace(
            chat_id="-100123",
            is_private=False,
            message=types.SimpleNamespace(
                peer_id=type("PeerChannel", (), {})(),
                reply_to=types.SimpleNamespace(reply_to_top_id=456),
            ),
        )

        session_id = adapter._grouped_message_session_id(event)

        self.assertEqual(session_id, "-100123#456")

    async def test_process_grouped_message_keeps_topic_cache_separate(self):
        module = _load_adapter_module()
        adapter = module.TelethonPlatformAdapter(
            {
                "api_id": 123,
                "api_hash": "hash",
                "session_string": "session",
                "trigger_prefix": "",
            },
            {},
            asyncio.Queue(),
        )
        committed = []

        async def fake_convert_message(event, include_reply=True):
            return types.SimpleNamespace(
                message_id=str(event.message.id),
                message_str=f"text-{event.message.id}",
                message=[f"part-{event.message.id}"],
                sender=types.SimpleNamespace(user_id="42", nickname="alice"),
                session_id=f"{event.chat_id}#{event.message.reply_to.reply_to_top_id}",
            )

        adapter._convert_message = fake_convert_message
        adapter._commit_abm = committed.append

        event_topic_1 = types.SimpleNamespace(
            chat_id="-100500",
            sender_id="42",
            message=types.SimpleNamespace(
                id=21,
                raw_text="",
                reply_to=types.SimpleNamespace(reply_to_top_id=301),
            ),
        )
        event_topic_2 = types.SimpleNamespace(
            chat_id="-100500",
            sender_id="42",
            message=types.SimpleNamespace(
                id=22,
                raw_text="",
                reply_to=types.SimpleNamespace(reply_to_top_id=302),
            ),
        )
        adapter._media_group_cache[("-100500#301", 999)] = {
            "created_at": 0.0,
            "items": [event_topic_1],
            "task": None,
        }
        adapter._media_group_cache[("-100500#302", 999)] = {
            "created_at": 0.0,
            "items": [event_topic_2],
            "task": None,
        }

        await adapter._process_grouped_message(("-100500#301", 999), delay=0)
        await adapter._process_grouped_message(("-100500#302", 999), delay=0)

        self.assertEqual([item.session_id for item in committed], ["-100500#301", "-100500#302"])

    async def test_message_converter_peer_user_fallback_sets_friend_message_type(self):
        module = _load_message_converter_module()
        adapter = types.SimpleNamespace(trigger_prefix="-astr", self_id="", self_username="")
        converter = module.TelethonMessageConverter(adapter)

        class _Event:
            def __init__(self):
                self.chat_id = "42"
                self.is_private = False
                self.message = types.SimpleNamespace(
                    id=14,
                    raw_text="hello",
                    reply_to=None,
                    media=None,
                    entities=None,
                )

            async def get_sender(self):
                return types.SimpleNamespace(id=42, username="alice")

        event = _Event()
        event.message.peer_id = type("PeerUser", (), {})()

        abm = await converter.convert_message(event, include_reply=True)

        self.assertEqual(abm.type, "friend")
        self.assertEqual(abm.session_id, "42")
        self.assertFalse(hasattr(abm, "group_id"))


    async def test_cleanup_expired_temp_files_removes_expired_entries_and_empty_dir(self):
        module = _load_adapter_module()
        adapter = module.TelethonPlatformAdapter(
            {
                "api_id": 123,
                "api_hash": "hash",
                "session_string": "session",
            },
            {},
            asyncio.Queue(),
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            expired = os.path.join(temp_dir, "expired.bin")
            alive = os.path.join(temp_dir, "alive.bin")
            Path(expired).write_bytes(b"expired")
            Path(alive).write_bytes(b"alive")
            adapter._media_temp_dir = temp_dir
            adapter._downloaded_temp_files = {
                os.path.abspath(expired): 0.0,
                os.path.abspath(alive): asyncio.get_running_loop().time() + 60,
            }

            await adapter._cleanup_expired_temp_files(force=False)

            self.assertFalse(os.path.exists(expired))
            self.assertTrue(os.path.exists(alive))
            self.assertEqual(
                adapter._downloaded_temp_files,
                {os.path.abspath(alive): adapter._downloaded_temp_files[os.path.abspath(alive)]},
            )

            await adapter._cleanup_expired_temp_files(force=True)

            self.assertFalse(os.path.exists(alive))
            self.assertEqual(adapter._downloaded_temp_files, {})
            self.assertFalse(os.path.exists(temp_dir))


if __name__ == "__main__":
    unittest.main()
