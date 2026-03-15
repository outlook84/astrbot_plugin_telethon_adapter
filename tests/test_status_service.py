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


class _FakePlatformMeta:
    id = "telethon_userbot"


class _FakeSession:
    dc_id = 2


class _FakeClient:
    session = _FakeSession()


class _FakeEvent:
    client = _FakeClient()
    platform_meta = _FakePlatformMeta()


class _FakeCpuTimes:
    def __init__(self, user, system):
        self.user = user
        self.system = system


class _FakeProcess:
    def __init__(self):
        self._cpu_time_calls = 0

    def create_time(self):
        return 1_700_000_000

    def cpu_times(self):
        self._cpu_time_calls += 1
        if self._cpu_time_calls == 1:
            return _FakeCpuTimes(10.0, 2.0)
        return _FakeCpuTimes(10.4, 2.4)

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
        self.assertEqual(TelethonStatusService.human_time_duration(59), "0分钟")
        self.assertEqual(
            TelethonStatusService.human_time_duration(3661),
            "1小时1分钟",
        )
        self.assertEqual(
            TelethonStatusService.human_time_duration(90061),
            "1天1小时1分钟",
        )

    async def test_build_status_text(self):
        fake_psutil = _FakePsutil()
        original_psutil = status_service_module.psutil
        original_datetime = status_service_module.datetime
        original_sleep = status_service_module.asyncio.sleep
        original_platform = status_service_module.platform
        original_time = status_service_module.time
        original_astrbot_version = status_service_module.ASTRBOT_VERSION
        original_telethon_version = status_service_module.TELETHON_VERSION

        class _FakeDateTime:
            @staticmethod
            def fromtimestamp(value, tz=None):
                return original_datetime.fromtimestamp(value, tz=tz)

            @staticmethod
            def now(tz=None):
                return original_datetime.fromtimestamp(1_700_003_661, tz=tz)

        async def _fake_sleep(_seconds):
            return None

        class _FakePlatform:
            @staticmethod
            def system():
                return "Linux"

            @staticmethod
            def python_version():
                return "3.14.3"

        class _FakeTime:
            _calls = 0

            @classmethod
            def monotonic(cls):
                cls._calls += 1
                if cls._calls == 1:
                    return 100.0
                return 100.1

        status_service_module.psutil = fake_psutil
        status_service_module.datetime = _FakeDateTime
        status_service_module.asyncio.sleep = _fake_sleep
        status_service_module.platform = _FakePlatform
        status_service_module.time = _FakeTime
        status_service_module.ASTRBOT_VERSION = "4.20.0"
        status_service_module.TELETHON_VERSION = "1.41.2.dev1"
        try:
            service = TelethonStatusService()
            text = await service.build_status_text(_FakeEvent())
        finally:
            status_service_module.psutil = original_psutil
            status_service_module.datetime = original_datetime
            status_service_module.asyncio.sleep = original_sleep
            status_service_module.platform = original_platform
            status_service_module.time = original_time
            status_service_module.ASTRBOT_VERSION = original_astrbot_version
            status_service_module.TELETHON_VERSION = original_telethon_version

        self.assertIn("<b>运行状态</b>", text)
        self.assertIn("主机平台: <code>linux</code>", text)
        self.assertIn("Python 版本: <code>3.14.3</code>", text)
        self.assertIn("AstrBot 版本: <code>4.20.0</code>", text)
        self.assertIn("Telethon 版本: <code>1.41.2.dev1</code>", text)
        self.assertIn("插件版本: <code>", text)
        self.assertIn("适配器 ID: <code>telethon_userbot</code>", text)
        self.assertIn("数据中心: <code>🇳🇱 荷兰阿姆斯特丹（DC2）</code>", text)
        self.assertIn("系统 CPU: <code>42.5%</code>", text)
        self.assertIn("系统内存: <code>37.5%</code>", text)
        self.assertIn("系统 SWAP: <code>12.5%</code>", text)
        self.assertIn("进程 CPU: <code>100.0%</code>", text)
        self.assertIn("进程内存: <code>25.0%</code>", text)
        self.assertIn("运行时间: <code>1小时1分钟</code>", text)
        self.assertNotIn("主机名", text)
        self.assertNotIn("Kernel 版本", text)
