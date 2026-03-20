import importlib.util
import io
import sys
import types
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _install_astrbot_stubs() -> None:
    astrbot_module = types.ModuleType("astrbot")
    api_module = types.ModuleType("astrbot.api")

    class _Logger:
        def __init__(self) -> None:
            self.debugs = []
            self.warnings = []

        def debug(self, *args, **kwargs):
            self.debugs.append((args, kwargs))

        def warning(self, *args, **kwargs):
            self.warnings.append((args, kwargs))

    api_module.logger = _Logger()
    sys.modules["astrbot"] = astrbot_module
    sys.modules["astrbot.api"] = api_module


def _install_telethon_stubs() -> None:
    telethon_module = types.ModuleType("telethon")
    client_module = types.ModuleType("telethon.client")
    uploads_module = types.ModuleType("telethon.client.uploads")
    network_module = types.ModuleType("telethon.network")
    tl_module = types.ModuleType("telethon.tl")
    tl_types_module = types.ModuleType("telethon.tl.types")
    alltlobjects_module = types.ModuleType("telethon.tl.alltlobjects")
    functions_module = types.ModuleType("telethon.tl.functions")
    auth_module = types.ModuleType("telethon.tl.functions.auth")
    upload_module = types.ModuleType("telethon.tl.functions.upload")

    class _Helpers:
        @staticmethod
        def generate_random_long():
            return 1

    class _Utils:
        @staticmethod
        def get_appropriated_part_size(file_size):
            return 512

    class MTProtoSender:
        pass

    class InvokeWithLayerRequest:
        def __init__(self, *args, **kwargs):
            return None

    class ExportAuthorizationRequest:
        pass

    class ImportAuthorizationRequest:
        def __init__(self, *args, **kwargs):
            return None

    class SaveBigFilePartRequest:
        def __init__(self, file_id, index, part_count, data):
            self.file_part = index
            self.bytes = data

    class SaveFilePartRequest:
        def __init__(self, file_id, index, data):
            self.file_part = index
            self.bytes = data

    uploads_module._resize_photo_if_needed = lambda *args, **kwargs: None
    network_module.MTProtoSender = MTProtoSender
    alltlobjects_module.LAYER = 1
    functions_module.InvokeWithLayerRequest = InvokeWithLayerRequest
    auth_module.ExportAuthorizationRequest = ExportAuthorizationRequest
    auth_module.ImportAuthorizationRequest = ImportAuthorizationRequest
    upload_module.SaveBigFilePartRequest = SaveBigFilePartRequest
    upload_module.SaveFilePartRequest = SaveFilePartRequest
    telethon_module.helpers = _Helpers()
    telethon_module.utils = _Utils()

    sys.modules["telethon"] = telethon_module
    sys.modules["telethon.client"] = client_module
    sys.modules["telethon.client.uploads"] = uploads_module
    sys.modules["telethon.network"] = network_module
    sys.modules["telethon.tl"] = tl_module
    sys.modules["telethon.tl.types"] = tl_types_module
    sys.modules["telethon.tl.alltlobjects"] = alltlobjects_module
    sys.modules["telethon.tl.functions"] = functions_module
    sys.modules["telethon.tl.functions.auth"] = auth_module
    sys.modules["telethon.tl.functions.upload"] = upload_module


def _load_fast_upload_module():
    _install_astrbot_stubs()
    _install_telethon_stubs()
    module_path = PROJECT_ROOT / "telethon_adapter" / "fast_upload.py"
    spec = importlib.util.spec_from_file_location("test_fast_upload_module", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


class _FakeSender:
    def __init__(self, *, should_fail: bool = False):
        self.should_fail = should_fail
        self.disconnected = False

    async def disconnect(self):
        self.disconnected = True
        if self.should_fail:
            raise RuntimeError("disconnect failed")


class FastUploadTests(unittest.IsolatedAsyncioTestCase):
    def test_should_use_fast_upload_returns_false_when_disabled_by_config(self):
        module = _load_fast_upload_module()
        client = types.SimpleNamespace(
            telethon_fast_upload_enabled=False,
            session=types.SimpleNamespace(dc_id=1, auth_key=b"key"),
            _call=object(),
            _get_dc=object(),
            _connection=object(),
            _log=object(),
        )

        enabled = module.should_use_fast_upload(client, __file__)

        self.assertFalse(enabled)
        self.assertTrue(module.logger.debugs)
        self.assertIn("reason=disabled_by_config", module.logger.debugs[-1][0][0])

    async def test_finish_upload_waits_for_all_disconnects_and_logs_errors(self):
        module = _load_fast_upload_module()
        transferrer = module._ParallelTransferrer(client=types.SimpleNamespace(session=types.SimpleNamespace(dc_id=1, auth_key=None)))
        sender_ok = _FakeSender()
        sender_fail = _FakeSender(should_fail=True)
        transferrer.senders = [sender_ok, sender_fail]

        await transferrer.finish_upload()

        self.assertTrue(sender_ok.disconnected)
        self.assertTrue(sender_fail.disconnected)
        self.assertIsNone(transferrer.senders)
        self.assertEqual(len(module.logger.warnings), 1)

    def test_log_upload_target_preprocess_describes_memory_target(self):
        module = _load_fast_upload_module()
        client = types.SimpleNamespace()
        buffer = io.BytesIO(b"data")
        buffer.name = "a.jpg"

        module._log_upload_target_preprocess(client, "/tmp/source.jpg", buffer)

        self.assertTrue(module.logger.debugs)
        message = module.logger.debugs[-1][0][0]
        args = module.logger.debugs[-1][0][1:]
        self.assertIn("upload_target_preprocessed", message)
        self.assertEqual(args[0], "/tmp/source.jpg")
        self.assertEqual(args[1], "BytesIO")
        self.assertEqual(args[2], "a.jpg")


if __name__ == "__main__":
    unittest.main()
