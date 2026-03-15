import importlib.util
import sys
import types
import unittest
from pathlib import Path


class _BootstrapPsutil(types.ModuleType):
    def Process(self):
        raise NotImplementedError

    def cpu_percent(self):
        return 0.0

    def cpu_count(self, logical=True):
        return 1

    def virtual_memory(self):
        raise NotImplementedError

    def swap_memory(self):
        raise NotImplementedError


def _load_status_service_module():
    sys.modules.setdefault("psutil", _BootstrapPsutil("psutil"))

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

    module_name = f"{services_name}.status_service"
    module_path = services_path / "status_service.py"
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


status_service_module = _load_status_service_module()
TelethonStatusService = status_service_module.TelethonStatusService


class _FakeMemoryInfo:
    rss = 512


class _FakeVirtualMemory:
    total = 2048
    percent = 37.5


class _FakeSwapMemory:
    percent = 12.5


class _FakeProcess:
    def __init__(self):
        self._cpu_calls = 0

    def create_time(self):
        return 1_700_000_000

    def cpu_percent(self):
        self._cpu_calls += 1
        if self._cpu_calls == 1:
            return 0.0
        return 80.0

    def memory_info(self):
        return _FakeMemoryInfo()


class _FakePsutil:
    def __init__(self):
        self._cpu_calls = 0

    def Process(self):
        return _FakeProcess()

    def cpu_percent(self):
        self._cpu_calls += 1
        if self._cpu_calls == 1:
            return 0.0
        return 42.5

    def cpu_count(self, logical=True):
        return 8

    def virtual_memory(self):
        return _FakeVirtualMemory()

    def swap_memory(self):
        return _FakeSwapMemory()


class TelethonStatusServiceTest(unittest.IsolatedAsyncioTestCase):
    def test_human_time_duration(self):
        self.assertEqual(TelethonStatusService.human_time_duration(59), "59秒")
        self.assertEqual(
            TelethonStatusService.human_time_duration(3661),
            "1小时 01分钟 01秒",
        )
        self.assertEqual(
            TelethonStatusService.human_time_duration(90061),
            "1天 01小时 01分钟 01秒",
        )

    async def test_build_status_text(self):
        fake_psutil = _FakePsutil()
        original_psutil = status_service_module.psutil
        original_datetime = status_service_module.datetime
        original_sleep = status_service_module.asyncio.sleep

        class _FakeDateTime:
            @staticmethod
            def fromtimestamp(value, tz=None):
                return original_datetime.fromtimestamp(value, tz=tz)

            @staticmethod
            def now(tz=None):
                return original_datetime.fromtimestamp(1_700_003_661, tz=tz)

        async def _fake_sleep(_seconds):
            return None

        status_service_module.psutil = fake_psutil
        status_service_module.datetime = _FakeDateTime
        status_service_module.asyncio.sleep = _fake_sleep
        try:
            service = TelethonStatusService()
            text = await service.build_status_text()
        finally:
            status_service_module.psutil = original_psutil
            status_service_module.datetime = original_datetime
            status_service_module.asyncio.sleep = original_sleep

        self.assertIn("<b>插件版本:</b>", text)
        self.assertIn("<b>运行时长:</b> 1小时 01分钟 01秒", text)
        self.assertIn("<b>系统 CPU:</b> 42.50%", text)
        self.assertIn("<b>系统内存:</b> 37.50%", text)
        self.assertIn("<b>系统 Swap:</b> 12.50%", text)
        self.assertIn("<b>进程 CPU:</b> 10.00%", text)
        self.assertIn("<b>进程内存:</b> 25.00%", text)
