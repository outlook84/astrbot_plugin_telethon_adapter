import importlib.util
import sys
import types
import unittest
from pathlib import Path


def _install_main_stubs():
    package_name = "astrbot_plugin_telethon_adapter"
    repo_root = Path(__file__).resolve().parents[1]

    package_module = types.ModuleType(package_name)
    package_module.__path__ = [str(repo_root)]
    sys.modules[package_name] = package_module

    astrbot_module = types.ModuleType("astrbot")
    api_module = types.ModuleType("astrbot.api")
    event_module = types.ModuleType("astrbot.api.event")
    star_module = types.ModuleType("astrbot.api.star")

    class _Logger:
        def debug(self, *args, **kwargs):
            return None

        def info(self, *args, **kwargs):
            return None

        def exception(self, *args, **kwargs):
            return None

    class _Filter:
        class PermissionType:
            ADMIN = "admin"

        @staticmethod
        def command_group(_name):
            def _decorator(func):
                func.command = _Filter.command
                return func

            return _decorator

        @staticmethod
        def permission_type(_permission):
            def _decorator(func):
                return func

            return _decorator

        @staticmethod
        def command(_name):
            def _decorator(func):
                return func

            return _decorator

    class _Star:
        def __init__(self, context):
            self.context = context

    def _register(*_args, **_kwargs):
        def _decorator(cls):
            return cls

        return _decorator

    api_module.logger = _Logger()
    event_module.AstrMessageEvent = object
    event_module.filter = _Filter()
    star_module.Context = object
    star_module.Star = _Star
    star_module.register = _register

    sys.modules["astrbot"] = astrbot_module
    sys.modules["astrbot.api"] = api_module
    sys.modules["astrbot.api.event"] = event_module
    sys.modules["astrbot.api.star"] = star_module

    plugin_info_module = types.ModuleType(f"{package_name}.plugin_info")
    plugin_info_module.PLUGIN_AUTHOR = "author"
    plugin_info_module.PLUGIN_DESC = "desc"
    plugin_info_module.PLUGIN_NAME = "name"
    plugin_info_module.PLUGIN_REPO = "repo"
    plugin_info_module.PLUGIN_VERSION = "version"
    sys.modules[f"{package_name}.plugin_info"] = plugin_info_module

    telethon_adapter_module = types.ModuleType(f"{package_name}.telethon_adapter")
    telethon_adapter_module.TelethonPlatformAdapter = object
    sys.modules[f"{package_name}.telethon_adapter"] = telethon_adapter_module

    i18n_module = types.ModuleType(f"{package_name}.telethon_adapter.i18n")
    i18n_module.t = lambda _event, key, **_kwargs: key
    sys.modules[f"{package_name}.telethon_adapter.i18n"] = i18n_module

    services_module = types.ModuleType(f"{package_name}.telethon_adapter.services")
    services_module.__path__ = [str(repo_root / "telethon_adapter" / "services")]

    class _DummyProfileService:
        def supports_event(self, _event):
            return True

    class _DummyPruneService:
        async def resolve_target_user(self, _event, _target):
            return None

        async def prune_messages(self, _event, _count, **_kwargs):
            return types.SimpleNamespace()

        def format_result_text(self, _result):
            return "ok"

    class _DummySender:
        async def send_html_message(self, _event, _text, link_preview=False):
            return None

        def schedule_delete_message(self, _event, _message, _ttl):
            return None

    services_module.TelethonPruneService = _DummyPruneService
    services_module.TelethonProfileService = _DummyProfileService
    services_module.TelethonStickerService = lambda _plugin: object()
    services_module.TelethonStatusService = lambda _context: object()
    services_module.TelethonSender = _DummySender
    sys.modules[f"{package_name}.telethon_adapter.services"] = services_module

    profile_service_module = types.ModuleType(
        f"{package_name}.telethon_adapter.services.profile_service"
    )
    profile_service_module.TelethonProfileService = _DummyProfileService
    sys.modules[
        f"{package_name}.telethon_adapter.services.profile_service"
    ] = profile_service_module

    module_name = f"{package_name}.main"
    module_path = repo_root / "main.py"
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


main_module = _install_main_stubs()
TelethonAdapterPlugin = main_module.TelethonAdapterPlugin


class _FakeEvent:
    def __init__(self):
        self.result = None

    def set_result(self, value):
        self.result = value


class _RecordingPruneService:
    def __init__(self):
        self.resolve_calls = []
        self.prune_calls = []

    async def resolve_target_user(self, _event, target):
        self.resolve_calls.append(target)
        return types.SimpleNamespace(id=123) if target else None

    async def prune_messages(self, _event, count, **kwargs):
        self.prune_calls.append((count, kwargs))
        return types.SimpleNamespace()

    def format_result_text(self, _result):
        return "ok"


class TelethonAdapterPluginPruneArgsTest(unittest.IsolatedAsyncioTestCase):
    async def test_youprune_single_numeric_arg_is_treated_as_count(self):
        plugin = TelethonAdapterPlugin(context=object())
        plugin._prune_service = _RecordingPruneService()
        plugin._send_text_result = _async_noop

        await plugin._run_prune_command(
            _FakeEvent(),
            count="",
            usage_message="usage",
            log_name="tg_youprune",
            target="2",
        )

        self.assertEqual(plugin._prune_service.resolve_calls, [""])
        self.assertEqual(
            plugin._prune_service.prune_calls,
            [(2, {"only_self": False, "target_user": None})],
        )

    async def test_prune_rejects_when_another_prune_is_running(self):
        plugin = TelethonAdapterPlugin(context=object())
        plugin._prune_service = _RecordingPruneService()
        await plugin._prune_lock.acquire()
        event = _FakeEvent()

        try:
            await plugin._run_prune_command(
                event,
                count="1",
                usage_message="usage",
                log_name="tg_selfprune",
            )
        finally:
            plugin._prune_lock.release()

        self.assertEqual(event.result, "prune.busy")
        self.assertEqual(plugin._prune_service.prune_calls, [])

    def test_normalize_prune_args_only_rewrites_youprune_numeric_target(self):
        self.assertEqual(
            TelethonAdapterPlugin._normalize_prune_args("tg_youprune", "2", ""),
            ("", "2"),
        )
        self.assertEqual(
            TelethonAdapterPlugin._normalize_prune_args("tg_selfprune", "2", ""),
            ("2", ""),
        )


async def _async_noop(*_args, **_kwargs):
    return True
