import importlib.util
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch


def _install_astrbot_stubs() -> None:
    astrbot_module = types.ModuleType("astrbot")
    api_module = types.ModuleType("astrbot.api")
    message_components_module = types.ModuleType("astrbot.api.message_components")

    class _Logger:
        def warning(self, *args, **kwargs):
            return None

    class _BaseComponent:
        def __init__(self, **kwargs):
            for key, value in kwargs.items():
                setattr(self, key, value)

    class File(_BaseComponent):
        def __init__(self, name="", file="", url="", **kwargs):
            super().__init__(name=name, file=file, url=url, **kwargs)

    class Image(_BaseComponent):
        def __init__(self, file="", **kwargs):
            super().__init__(file=file, **kwargs)

    class Record(_BaseComponent):
        def __init__(self, file="", **kwargs):
            super().__init__(file=file, **kwargs)

    class Video(_BaseComponent):
        def __init__(self, file="", **kwargs):
            super().__init__(file=file, **kwargs)

    api_module.logger = _Logger()
    message_components_module.File = File
    message_components_module.Image = Image
    message_components_module.Record = Record
    message_components_module.Video = Video

    sys.modules["astrbot"] = astrbot_module
    sys.modules["astrbot.api"] = api_module
    sys.modules["astrbot.api.message_components"] = message_components_module


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


def _load_lazy_media_module():
    _install_astrbot_stubs()
    _install_pydantic_stubs()
    module_path = Path(__file__).resolve().parents[1] / "telethon_adapter" / "lazy_media.py"
    spec = importlib.util.spec_from_file_location("test_lazy_media_module", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


class _FakeMessage:
    def __init__(self, download_path) -> None:
        self._download_path = download_path
        self.download_calls = 0

    async def download_media(self, file: str):
        self.download_calls += 1
        return self._download_path


class LazyMediaTests(unittest.IsolatedAsyncioTestCase):
    async def test_ensure_downloaded_reuses_cached_file_path(self):
        lazy_media = _load_lazy_media_module()

        with tempfile.TemporaryDirectory() as temp_dir:
            original_path = os.path.join(temp_dir, "photo.jpg")
            Path(original_path).write_bytes(b"jpg")
            message = _FakeMessage(original_path)
            downloader = lazy_media.TelethonLazyMedia(
                msg=message,
                temp_dir_getter=lambda: temp_dir,
                register_temp_file=lambda path: None,
                fallback_name="photo.jpg",
            )

            first = await downloader.ensure_downloaded()
            second = await downloader.ensure_downloaded()

        self.assertEqual(first, os.path.abspath(original_path))
        self.assertEqual(second, os.path.abspath(original_path))
        self.assertEqual(message.download_calls, 1)

    async def test_ensure_downloaded_writes_bytes_payload_with_fallback_name(self):
        lazy_media = _load_lazy_media_module()

        with tempfile.TemporaryDirectory() as temp_dir:
            message = _FakeMessage(b"payload")
            downloader = lazy_media.TelethonLazyMedia(
                msg=message,
                temp_dir_getter=lambda: temp_dir,
                register_temp_file=lambda path: None,
                fallback_name="payload.bin",
            )

            result = await downloader.ensure_downloaded()

            self.assertEqual(result, os.path.join(temp_dir, "payload.bin"))
            self.assertEqual(Path(result).read_bytes(), b"payload")

    async def test_ensure_downloaded_sanitizes_fallback_name_to_temp_dir(self):
        lazy_media = _load_lazy_media_module()

        with tempfile.TemporaryDirectory() as temp_dir:
            message = _FakeMessage(b"payload")
            downloader = lazy_media.TelethonLazyMedia(
                msg=message,
                temp_dir_getter=lambda: temp_dir,
                register_temp_file=lambda path: None,
                fallback_name="../nested/escape.bin",
            )

            result = await downloader.ensure_downloaded()

            self.assertEqual(result, os.path.join(temp_dir, "escape.bin"))
            self.assertEqual(Path(result).read_bytes(), b"payload")

    async def test_record_conversion_registers_original_and_wav_temp_files(self):
        lazy_media = _load_lazy_media_module()

        with tempfile.TemporaryDirectory() as temp_dir:
            original_path = os.path.join(temp_dir, "voice.ogg")
            converted_path = os.path.join(temp_dir, "voice.wav")
            Path(original_path).write_bytes(b"ogg")

            tracked: dict[str, float] = {}

            def register_temp_file(path: str) -> None:
                tracked[os.path.abspath(path)] = 1.0

            downloader = lazy_media.TelethonLazyMedia(
                msg=_FakeMessage(original_path),
                temp_dir_getter=lambda: temp_dir,
                register_temp_file=register_temp_file,
                fallback_name="voice.ogg",
            )
            record = lazy_media.LazyRecord(downloader=downloader)

            async def fake_convert_audio_to_wav(source: str, target: str) -> str:
                self.assertEqual(source, original_path)
                self.assertEqual(target, converted_path)
                Path(target).write_bytes(b"wav")
                return target

            with patch.object(lazy_media, "convert_audio_to_wav", fake_convert_audio_to_wav):
                result = await record.convert_to_file_path()

            self.assertEqual(result, os.path.abspath(converted_path))
            self.assertEqual(
                set(tracked.keys()),
                {os.path.abspath(original_path), os.path.abspath(converted_path)},
            )

    async def test_record_conversion_falls_back_to_original_when_converter_missing(self):
        lazy_media = _load_lazy_media_module()

        with tempfile.TemporaryDirectory() as temp_dir:
            original_path = os.path.join(temp_dir, "voice.ogg")
            Path(original_path).write_bytes(b"ogg")
            downloader = lazy_media.TelethonLazyMedia(
                msg=_FakeMessage(original_path),
                temp_dir_getter=lambda: temp_dir,
                register_temp_file=lambda path: None,
                fallback_name="voice.ogg",
            )
            record = lazy_media.LazyRecord(downloader=downloader)

            with patch.object(lazy_media, "convert_audio_to_wav", None):
                result = await record.convert_to_file_path()

        self.assertEqual(result, os.path.abspath(original_path))


if __name__ == "__main__":
    unittest.main()
