import importlib.util
from io import BytesIO
import sys
import types
import unittest
from pathlib import Path

from PIL import Image


def _install_astrbot_stubs() -> None:
    astrbot_module = types.ModuleType("astrbot")
    api_module = types.ModuleType("astrbot.api")

    class _Logger:
        def debug(self, *args, **kwargs):
            return None

        def warning(self, *args, **kwargs):
            return None

        def exception(self, *args, **kwargs):
            return None

    api_module.logger = _Logger()
    sys.modules["astrbot"] = astrbot_module
    sys.modules["astrbot.api"] = api_module


def _install_telethon_stubs() -> None:
    telethon_module = types.ModuleType("telethon")
    functions_module = types.ModuleType("telethon.functions")
    messages_module = types.ModuleType("telethon.functions.messages")
    stickers_module = types.ModuleType("telethon.functions.stickers")
    utils_module = types.ModuleType("telethon.utils")
    types_module = types.ModuleType("telethon.types")
    rpcerrorlist_module = types.ModuleType("telethon.errors.rpcerrorlist")

    class StickersetInvalidError(Exception):
        pass

    class UploadMediaRequest:
        def __init__(self, peer, media):
            self.peer = peer
            self.media = media

    class AddStickerToSetRequest:
        def __init__(self, stickerset, sticker):
            self.stickerset = stickerset
            self.sticker = sticker

    class CreateStickerSetRequest:
        def __init__(self, user_id, title, short_name, stickers):
            self.user_id = user_id
            self.title = title
            self.short_name = short_name
            self.stickers = stickers

    class InputPeerSelf:
        pass

    class InputUserSelf:
        pass

    class InputMediaUploadedDocument:
        def __init__(self, file, mime_type, attributes):
            self.file = file
            self.mime_type = mime_type
            self.attributes = attributes

    class InputStickerSetItem:
        def __init__(self, document, emoji):
            self.document = document
            self.emoji = emoji

    class InputStickerSetShortName:
        def __init__(self, short_name):
            self.short_name = short_name

    class DocumentAttributeSticker:
        def __init__(self, alt=""):
            self.alt = alt

    messages_module.UploadMediaRequest = UploadMediaRequest
    stickers_module.AddStickerToSetRequest = AddStickerToSetRequest
    stickers_module.CreateStickerSetRequest = CreateStickerSetRequest
    functions_module.messages = messages_module
    functions_module.stickers = stickers_module
    utils_module.get_input_document = lambda document: f"input:{document.id}"
    types_module.InputPeerSelf = InputPeerSelf
    types_module.InputUserSelf = InputUserSelf
    types_module.InputMediaUploadedDocument = InputMediaUploadedDocument
    types_module.InputStickerSetItem = InputStickerSetItem
    types_module.InputStickerSetShortName = InputStickerSetShortName
    types_module.DocumentAttributeSticker = DocumentAttributeSticker
    rpcerrorlist_module.StickersetInvalidError = StickersetInvalidError

    telethon_module.functions = functions_module
    telethon_module.types = types_module
    telethon_module.utils = utils_module

    sys.modules["telethon"] = telethon_module
    sys.modules["telethon.functions"] = functions_module
    sys.modules["telethon.functions.messages"] = messages_module
    sys.modules["telethon.functions.stickers"] = stickers_module
    sys.modules["telethon.types"] = types_module
    sys.modules["telethon.utils"] = utils_module
    sys.modules["telethon.errors.rpcerrorlist"] = rpcerrorlist_module


def _load_sticker_service_module():
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

    module_name = f"{services_name}.sticker_service"
    module_path = services_path / "sticker_service.py"
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


sticker_service_module = _load_sticker_service_module()
TelethonStickerService = sticker_service_module.TelethonStickerService
StickersetInvalidError = sys.modules["telethon.errors.rpcerrorlist"].StickersetInvalidError
UploadMediaRequest = sys.modules["telethon.functions.messages"].UploadMediaRequest
AddStickerToSetRequest = sys.modules["telethon.functions.stickers"].AddStickerToSetRequest
CreateStickerSetRequest = sys.modules["telethon.functions.stickers"].CreateStickerSetRequest
DocumentAttributeSticker = sys.modules["telethon.types"].DocumentAttributeSticker


class _FakeReplyMessage:
    def __init__(self, *, image_bytes=None, photo=None, document=None, sticker=None):
        self._image_bytes = image_bytes or b""
        self.photo = photo
        self.document = document
        self.sticker = sticker

    async def download_media(self, file=None):
        file.write(self._image_bytes)
        file.seek(0)
        return file


class _FakeClient:
    def __init__(self):
        self.uploaded_files = []
        self.requests = []
        self.pack_exists = False

    async def get_me(self):
        return types.SimpleNamespace(id=123456)

    async def upload_file(self, file_obj):
        self.uploaded_files.append(getattr(file_obj, "name", ""))
        return types.SimpleNamespace(id=77)

    async def __call__(self, request):
        self.requests.append(request)
        if isinstance(request, UploadMediaRequest):
            return types.SimpleNamespace(document=types.SimpleNamespace(id=88))
        if isinstance(request, AddStickerToSetRequest):
            if not self.pack_exists:
                raise StickersetInvalidError("missing")
            return types.SimpleNamespace(ok=True)
        if isinstance(request, CreateStickerSetRequest):
            self.pack_exists = True
            return types.SimpleNamespace(ok=True)
        raise AssertionError(f"unexpected request: {request!r}")


class _FakeRawMessage:
    def __init__(self, reply_message=None):
        self._reply_message = reply_message

    async def get_reply_message(self):
        return self._reply_message


class _FakeEvent:
    def __init__(self, client, reply_message=None, adapter_id="telethon_a"):
        self.client = client
        self.message_obj = types.SimpleNamespace(
            raw_message=_FakeRawMessage(reply_message=reply_message),
            self_id="123456",
        )
        self.platform_meta = types.SimpleNamespace(id=adapter_id)


class _FakeKVStore:
    def __init__(self):
        self.data = {}

    async def put_kv_data(self, key, value):
        self.data[key] = value

    async def get_kv_data(self, key, default):
        return self.data.get(key, default)


class TelethonStickerServiceTest(unittest.IsolatedAsyncioTestCase):
    def test_validate_pack_name(self):
        self.assertEqual(
            TelethonStickerService._validate_pack_name("Pack_01"),
            "Pack_01",
        )
        with self.assertRaisesRegex(ValueError, "字母开头"):
            TelethonStickerService._validate_pack_name("1bad")
        with self.assertRaisesRegex(ValueError, "连续下划线"):
            TelethonStickerService._validate_pack_name("bad__name")

    async def test_handle_command_sets_default_pack_name(self):
        kv_store = _FakeKVStore()
        service = TelethonStickerService(kv_store)
        event = _FakeEvent(_FakeClient())

        payload = await service.handle_command(event, "MyPack")

        self.assertIn("MyPack", payload.text)
        self.assertEqual(kv_store.data, {"sticker_pack_name:telethon_a": "MyPack"})

    async def test_handle_command_usage_with_default_uses_real_newlines(self):
        kv_store = _FakeKVStore()
        kv_store.data["sticker_pack_name:telethon_a"] = "MyPack"
        service = TelethonStickerService(kv_store)
        event = _FakeEvent(_FakeClient())

        payload = await service.handle_command(event, "")

        self.assertIn("当前默认贴纸包", payload.text)
        self.assertIn("\n查看链接:", payload.text)
        self.assertIn("\n用法:\n1.", payload.text)
        self.assertNotIn("<br/>", payload.text)

    async def test_handle_command_adds_replied_photo_to_pack(self):
        image_buffer = BytesIO()
        Image.new("RGBA", (1024, 600), (255, 0, 0, 255)).save(image_buffer, format="PNG")
        client = _FakeClient()
        reply_message = _FakeReplyMessage(
            image_bytes=image_buffer.getvalue(),
            photo=object(),
        )
        kv_store = _FakeKVStore()
        kv_store.data["sticker_pack_name:telethon_a"] = "MyPack"
        service = TelethonStickerService(kv_store)
        event = _FakeEvent(client, reply_message=reply_message)

        payload = await service.handle_command(event, "")

        self.assertIn("MyPack", payload.text)
        self.assertEqual(client.uploaded_files, ["sticker.webp"])
        self.assertEqual(
            [type(request).__name__ for request in client.requests],
            ["UploadMediaRequest", "AddStickerToSetRequest", "CreateStickerSetRequest"],
        )

    async def test_handle_command_uses_custom_emoji_for_reply(self):
        image_buffer = BytesIO()
        Image.new("RGBA", (300, 300), (0, 255, 0, 255)).save(image_buffer, format="PNG")
        client = _FakeClient()
        reply_message = _FakeReplyMessage(
            image_bytes=image_buffer.getvalue(),
            photo=object(),
        )
        kv_store = _FakeKVStore()
        kv_store.data["sticker_pack_name:telethon_a"] = "MyPack"
        service = TelethonStickerService(kv_store)
        event = _FakeEvent(client, reply_message=reply_message)

        await service.handle_command(event, "😎")

        create_request = next(
            request for request in client.requests if isinstance(request, CreateStickerSetRequest)
        )
        self.assertEqual(create_request.stickers[0].emoji, "😎")

    async def test_handle_command_adds_replied_webm_sticker_to_pack(self):
        client = _FakeClient()
        reply_message = _FakeReplyMessage(
            image_bytes=b"webm-data",
            document=types.SimpleNamespace(
                mime_type="video/webm",
                attributes=[DocumentAttributeSticker()],
            ),
            sticker=types.SimpleNamespace(attributes=[DocumentAttributeSticker()]),
        )
        kv_store = _FakeKVStore()
        kv_store.data["sticker_pack_name:telethon_a"] = "MyPack"
        service = TelethonStickerService(kv_store)
        event = _FakeEvent(client, reply_message=reply_message)

        payload = await service.handle_command(event, "")

        self.assertIn("MyPack", payload.text)
        self.assertEqual(client.uploaded_files, ["sticker.webm"])
        upload_request = next(
            request for request in client.requests if isinstance(request, UploadMediaRequest)
        )
        self.assertEqual(upload_request.media.mime_type, "video/webm")

    async def test_handle_command_rejects_plain_webm_file(self):
        client = _FakeClient()
        reply_message = _FakeReplyMessage(
            image_bytes=b"webm-data",
            document=types.SimpleNamespace(mime_type="video/webm", attributes=[]),
            sticker=None,
        )
        kv_store = _FakeKVStore()
        kv_store.data["sticker_pack_name:telethon_a"] = "MyPack"
        service = TelethonStickerService(kv_store)
        event = _FakeEvent(client, reply_message=reply_message)

        with self.assertRaisesRegex(ValueError, "WEBM 视频贴纸"):
            await service.handle_command(event, "")
