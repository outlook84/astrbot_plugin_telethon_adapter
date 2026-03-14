import importlib.util
import sys
import tempfile
import types
import unittest
from pathlib import Path


def _install_astrbot_stubs() -> None:
    astrbot_module = types.ModuleType("astrbot")
    api_module = types.ModuleType("astrbot.api")
    message_components_module = types.ModuleType("astrbot.api.message_components")
    platform_module = types.ModuleType("astrbot.api.platform")

    class _Logger:
        def info(self, *args, **kwargs):
            return None

        def warning(self, *args, **kwargs):
            return None

        def exception(self, *args, **kwargs):
            return None

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

    api_module.logger = _Logger()
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

    sys.modules["astrbot"] = astrbot_module
    sys.modules["astrbot.api"] = api_module
    sys.modules["astrbot.api.message_components"] = message_components_module
    sys.modules["astrbot.api.platform"] = platform_module


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
    tl_module = types.ModuleType("telethon.tl")
    tl_types_module = types.ModuleType("telethon.tl.types")

    def _stub_type(name):
        return type(name, (), {})

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
    sys.modules["telethon.tl"] = tl_module
    sys.modules["telethon.tl.types"] = tl_types_module


def _load_message_converter_module():
    _install_astrbot_stubs()
    _install_pydantic_stubs()
    _install_telethon_stubs()

    package_name = "telethon_adapter"
    package_path = Path(__file__).resolve().parents[1] / package_name
    package_module = types.ModuleType(package_name)
    package_module.__path__ = [str(package_path)]
    sys.modules[package_name] = package_module

    for module_name in ["lazy_media", "message_converter"]:
        full_name = f"{package_name}.{module_name}"
        module_path = package_path / f"{module_name}.py"
        spec = importlib.util.spec_from_file_location(full_name, module_path)
        module = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        sys.modules[full_name] = module
        spec.loader.exec_module(module)

    return sys.modules["telethon_adapter.message_converter"]


class _FakeAdapter:
    def __init__(self, temp_dir: str, download_incoming_media: bool = True) -> None:
        self.self_id = "999"
        self.self_username = "astrbot"
        self.trigger_prefix = "-astr"
        self.download_incoming_media = download_incoming_media
        self._temp_dir = temp_dir
        self.registered_paths: list[str] = []

    def _get_media_temp_dir(self) -> str:
        return self._temp_dir

    def _register_temp_file(self, path: str) -> None:
        self.registered_paths.append(path)


class _FakeSender:
    def __init__(self, user_id: int, username: str | None = None) -> None:
        self.id = user_id
        self.username = username
        self.first_name = ""
        self.last_name = ""


class _FakeEvent:
    def __init__(self, message, sender, chat_id="100", is_private=False) -> None:
        self.message = message
        self.chat_id = chat_id
        self.is_private = is_private
        self._sender = sender

    async def get_sender(self):
        return self._sender


class _FakeMessage:
    def __init__(
        self,
        message_id: int,
        raw_text: str = "",
        entities=None,
        media=None,
        photo=None,
        document=None,
    ) -> None:
        self.id = message_id
        self.raw_text = raw_text
        self.entities = entities
        self.media = media
        self.photo = photo
        self.document = document
        self.reply_to = None


class MessageConverterTests(unittest.IsolatedAsyncioTestCase):
    async def test_convert_message_strips_trigger_prefix_and_adds_group_at(self):
        module = _load_message_converter_module()

        with tempfile.TemporaryDirectory() as temp_dir:
            converter = module.TelethonMessageConverter(_FakeAdapter(temp_dir))
            event = _FakeEvent(
                _FakeMessage(1, raw_text="-astr hello world"),
                _FakeSender(123, username="alice"),
            )

            result = await converter.convert_message(event)

        self.assertEqual(result.message_str, "hello world")
        self.assertEqual(result.type, "group")
        self.assertEqual(result.group_id, "100")
        self.assertEqual(type(result.message[0]).__name__, "At")
        self.assertEqual(result.message[0].qq, "999")
        self.assertEqual(type(result.message[1]).__name__, "Plain")
        self.assertEqual(result.message[1].text, "hello world")

    def test_parse_text_components_converts_tg_user_link_to_at(self):
        module = _load_message_converter_module()
        entity_type = sys.modules["telethon.tl.types"].MessageEntityTextUrl
        entity = entity_type()
        entity.offset = 6
        entity.length = 4
        entity.url = "tg://user?id=42"

        with tempfile.TemporaryDirectory() as temp_dir:
            converter = module.TelethonMessageConverter(_FakeAdapter(temp_dir))
            components = converter.parse_text_components("hello @bob", [entity])

        self.assertEqual(len(components), 2)
        self.assertEqual(type(components[0]).__name__, "Plain")
        self.assertEqual(components[0].text, "hello ")
        self.assertEqual(type(components[1]).__name__, "At")
        self.assertEqual(components[1].qq, "42")
        self.assertEqual(components[1].name, "bob")

    async def test_parse_media_components_maps_audio_document(self):
        module = _load_message_converter_module()
        tl_types = sys.modules["telethon.tl.types"]
        audio_attr = tl_types.DocumentAttributeAudio()
        filename_attr = tl_types.DocumentAttributeFilename()
        filename_attr.file_name = "voice.ogg"

        document = types.SimpleNamespace(
            mime_type="audio/ogg",
            attributes=[audio_attr, filename_attr],
        )
        msg = _FakeMessage(
            2,
            media=object(),
            document=document,
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            converter = module.TelethonMessageConverter(_FakeAdapter(temp_dir))
            components = await converter.parse_media_components(msg)

        self.assertEqual([type(component).__name__ for component in components], ["LazyRecord", "LazyFile", "Plain"])
        self.assertEqual(components[1].name, "voice.ogg")
        self.assertEqual(components[2].text, "[音频] voice.ogg")

    async def test_parse_media_components_skips_download_when_disabled(self):
        module = _load_message_converter_module()
        msg = _FakeMessage(
            3,
            media=object(),
            photo=object(),
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            converter = module.TelethonMessageConverter(
                _FakeAdapter(temp_dir, download_incoming_media=False)
            )
            components = await converter.parse_media_components(msg)

        self.assertEqual(components, [])


if __name__ == "__main__":
    unittest.main()
