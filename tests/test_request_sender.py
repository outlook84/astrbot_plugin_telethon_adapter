import importlib.util
import sys
import types
import unittest
from pathlib import Path


def _install_telethon_stubs() -> None:
    telethon_module = types.ModuleType("telethon")
    telethon_functions_module = types.ModuleType("telethon.functions")
    telethon_functions_messages_module = types.ModuleType("telethon.functions.messages")
    telethon_types_module = types.ModuleType("telethon.types")
    telethon_utils_module = types.ModuleType("telethon.utils")

    class InputReplyToMessage:
        def __init__(self, reply_to_msg_id, top_msg_id=None):
            self.reply_to_msg_id = reply_to_msg_id
            self.top_msg_id = top_msg_id

    class SendMessageRequest:
        def __init__(self, peer, message, entities=None, no_webpage=True, reply_to=None, **kwargs):
            self.peer = peer
            self.message = message
            self.entities = entities
            self.no_webpage = no_webpage
            self.reply_to = reply_to
            self.kwargs = kwargs

    class SendMediaRequest:
        def __init__(self, peer, media, reply_to=None, message="", entities=None, **kwargs):
            self.peer = peer
            self.media = media
            self.reply_to = reply_to
            self.message = message
            self.entities = entities
            self.kwargs = kwargs

    class SendMultiMediaRequest:
        def __init__(self, peer, multi_media, reply_to=None, **kwargs):
            self.peer = peer
            self.multi_media = multi_media
            self.reply_to = reply_to
            self.kwargs = kwargs

    class UploadMediaRequest:
        def __init__(self, peer, media, **kwargs):
            self.peer = peer
            self.media = media
            self.kwargs = kwargs

    class InputSingleMedia:
        def __init__(self, media, message="", entities=None, **kwargs):
            self.media = media
            self.message = message
            self.entities = entities
            self.kwargs = kwargs

    class InputMediaUploadedPhoto:
        def __init__(self, file, spoiler=False, **kwargs):
            self.file = file
            self.path = file
            self.spoiler = spoiler
            self.kwargs = kwargs

    class InputMediaUploadedDocument:
        def __init__(self, file, mime_type="application/octet-stream", attributes=None, spoiler=False, **kwargs):
            self.file = file
            self.path = file
            self.mime_type = mime_type
            self.attributes = attributes or []
            self.spoiler = spoiler
            self.kwargs = kwargs

    class InputMediaPhotoExternal:
        pass

    class InputMediaDocumentExternal:
        pass

    telethon_types_module.InputReplyToMessage = InputReplyToMessage
    telethon_types_module.InputSingleMedia = InputSingleMedia
    telethon_types_module.InputMediaUploadedPhoto = InputMediaUploadedPhoto
    telethon_types_module.InputMediaUploadedDocument = InputMediaUploadedDocument
    telethon_types_module.InputMediaPhotoExternal = InputMediaPhotoExternal
    telethon_types_module.InputMediaDocumentExternal = InputMediaDocumentExternal
    telethon_functions_messages_module.SendMessageRequest = SendMessageRequest
    telethon_functions_messages_module.SendMediaRequest = SendMediaRequest
    telethon_functions_messages_module.SendMultiMediaRequest = SendMultiMediaRequest
    telethon_functions_messages_module.UploadMediaRequest = UploadMediaRequest
    telethon_functions_module.messages = telethon_functions_messages_module

    def get_input_media(media, **kwargs):
        return types.SimpleNamespace(
            path=getattr(media, "path", None),
            spoiler=getattr(media, "spoiler", False),
            kwargs=kwargs,
        )

    telethon_utils_module.get_input_media = get_input_media
    telethon_module.types = telethon_types_module
    telethon_module.functions = telethon_functions_module
    telethon_module.utils = telethon_utils_module
    sys.modules["telethon"] = telethon_module
    sys.modules["telethon.functions"] = telethon_functions_module
    sys.modules["telethon.functions.messages"] = telethon_functions_messages_module
    sys.modules["telethon.types"] = telethon_types_module
    sys.modules["telethon.utils"] = telethon_utils_module


def _install_astrbot_stubs() -> None:
    astrbot_module = types.ModuleType("astrbot")
    api_module = types.ModuleType("astrbot.api")

    class _Logger:
        def warning(self, *args, **kwargs):
            return None

    api_module.logger = _Logger()
    sys.modules["astrbot"] = astrbot_module
    sys.modules["astrbot.api"] = api_module


def _load_request_sender_module():
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

    planner_name = f"{services_name}.message_planner"
    planner_path = services_path / "message_planner.py"
    planner_spec = importlib.util.spec_from_file_location(planner_name, planner_path)
    planner_module = importlib.util.module_from_spec(planner_spec)
    assert planner_spec and planner_spec.loader
    sys.modules[planner_name] = planner_module
    planner_spec.loader.exec_module(planner_module)

    transport_name = f"{package_name}.transport"
    transport_path = package_path / "transport"
    transport_module = types.ModuleType(transport_name)
    transport_module.__path__ = [str(transport_path)]
    sys.modules[transport_name] = transport_module

    module_name = f"{transport_name}.request_sender"
    module_path = transport_path / "request_sender.py"
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


request_sender_module = _load_request_sender_module()
TelethonRequestSender = request_sender_module.TelethonRequestSender


def _ensure_media_stub_types():
    types_module = sys.modules["telethon.types"]
    if not hasattr(types_module, "InputMediaUploadedPhoto"):
        class InputMediaUploadedPhoto:
            def __init__(self, file, spoiler=False, **kwargs):
                self.file = file
                self.path = file
                self.spoiler = spoiler
                self.kwargs = kwargs

        types_module.InputMediaUploadedPhoto = InputMediaUploadedPhoto

    if not hasattr(types_module, "InputMediaUploadedDocument"):
        class InputMediaUploadedDocument:
            def __init__(self, file, mime_type="application/octet-stream", attributes=None, spoiler=False, **kwargs):
                self.file = file
                self.path = file
                self.mime_type = mime_type
                self.attributes = attributes or []
                self.spoiler = spoiler
                self.kwargs = kwargs

        types_module.InputMediaUploadedDocument = InputMediaUploadedDocument

    if not hasattr(types_module, "InputMediaPhotoExternal"):
        class InputMediaPhotoExternal:
            pass

        types_module.InputMediaPhotoExternal = InputMediaPhotoExternal

    if not hasattr(types_module, "InputMediaDocumentExternal"):
        class InputMediaDocumentExternal:
            pass

        types_module.InputMediaDocumentExternal = InputMediaDocumentExternal

    return types_module


class _FakeClient:
    def __init__(self):
        self.requests = []
        self.sent_messages = []
        self.sent_files = []

    async def __call__(self, request):
        self.requests.append(request)
        if type(request).__name__ == "UploadMediaRequest":
            media = request.media
            if type(media).__name__ == "InputMediaUploadedPhoto":
                return types.SimpleNamespace(photo=types.SimpleNamespace(path=media.file, spoiler=media.spoiler))
            return types.SimpleNamespace(document=types.SimpleNamespace(path=media.file, spoiler=media.spoiler))
        return {"request": request}

    async def send_message(self, peer, text, **kwargs):
        self.sent_messages.append((peer, text, kwargs))
        return types.SimpleNamespace(id=1)

    async def send_file(self, peer, file, **kwargs):
        self.sent_files.append((peer, file, kwargs))
        return types.SimpleNamespace(id=2)

    async def get_input_entity(self, peer):
        return f"input:{peer}"

    async def _parse_message_text(self, text, parse_mode):
        return text, [types.SimpleNamespace(parse_mode=parse_mode)]

    def _get_response_message(self, request, result, entity):
        return types.SimpleNamespace(id=3, request=request, entity=entity)


class TelethonRequestSenderTests(unittest.IsolatedAsyncioTestCase):
    async def test_send_text_uses_send_message_without_thread(self):
        client = _FakeClient()
        sender = TelethonRequestSender(client=client, peer="peer:test")

        result = await sender.send_text(
            "hello",
            parse_mode="html",
            reply_to_msg_id=None,
            link_preview=True,
        )

        self.assertEqual(getattr(result, "id", None), 1)
        self.assertEqual(client.sent_messages[0][0], "peer:test")
        self.assertEqual(client.sent_messages[0][2]["parse_mode"], "html")
        self.assertEqual(client.sent_messages[0][2]["link_preview"], True)

    async def test_send_text_uses_request_in_topic(self):
        client = _FakeClient()
        sender = TelethonRequestSender(client=client, peer="peer:test", thread_id=456)

        result = await sender.send_text(
            "hello",
            parse_mode="html",
            reply_to_msg_id=None,
            link_preview=False,
        )

        self.assertEqual(getattr(result, "id", None), 3)
        request = client.requests[0]
        self.assertEqual(type(request).__name__, "SendMessageRequest")
        self.assertEqual(request.peer, "input:peer:test")
        self.assertEqual(request.reply_to.reply_to_msg_id, 456)
        self.assertEqual(request.reply_to.top_msg_id, 456)

    async def test_send_media_action_fast_upload_uses_request_and_wraps_reply_to(self):
        client = _FakeClient()

        async def _build_input_media(_client, _file, **_kwargs):
            return None, "fast-media:/tmp/a.png", False

        sender = TelethonRequestSender(
            client=client,
            peer="peer:test",
            build_input_media=_build_input_media,
            should_use_fast_upload=lambda _client, _file: True,
        )

        result = await sender.send_media_action(
            request_sender_module.MediaAction(
                path="/tmp/a.png",
                caption="hello",
                caption_parse_mode="html",
                reply_to=66,
                action_name="photo",
                fallback_action=None,
            ),
        )

        self.assertEqual(getattr(result, "id", None), 3)
        request = client.requests[0]
        self.assertEqual(type(request).__name__, "SendMediaRequest")
        self.assertEqual(request.media, "fast-media:/tmp/a.png")
        self.assertEqual(type(request.reply_to).__name__, "InputReplyToMessage")
        self.assertEqual(request.reply_to.reply_to_msg_id, 66)
        self.assertIsNone(request.reply_to.top_msg_id)

    async def test_send_media_action_uses_action_fields(self):
        client = _FakeClient()
        sender = TelethonRequestSender(client=client, peer="peer:test")
        planner_module = request_sender_module

        result = await sender.send_media_action(
            planner_module.MediaAction(
                path="/tmp/a.png",
                caption="hello",
                caption_parse_mode="html",
                reply_to=66,
                action_name="photo",
                fallback_action=None,
            ),
        )

        self.assertEqual(getattr(result, "id", None), 2)
        self.assertEqual(client.sent_files[0][0], "peer:test")
        self.assertEqual(client.sent_files[0][1], "/tmp/a.png")
        self.assertEqual(client.sent_files[0][2]["caption"], "hello")
        self.assertEqual(client.sent_files[0][2]["reply_to"], 66)

    async def test_send_media_group_action_uses_multi_media_request(self):
        client = _FakeClient()
        photo_media_type = _ensure_media_stub_types().InputMediaUploadedPhoto

        async def _build_input_media(_client, file_path, **_kwargs):
            return None, photo_media_type(file=file_path), False

        sender = TelethonRequestSender(
            client=client,
            peer="peer:test",
            thread_id=456,
            build_input_media=_build_input_media,
        )
        planner_module = request_sender_module

        result = await sender.send_media_group_action(
            planner_module.MediaGroupAction(
                media_items=[("/tmp/a.png", False, False), ("/tmp/b.png", False, False)],
                caption="done",
                caption_parse_mode="html",
                reply_to=None,
                action_name="photo",
                fallback_action=None,
            ),
        )

        self.assertEqual(getattr(result, "id", None), 3)
        request = next(
            request for request in client.requests if type(request).__name__ == "SendMultiMediaRequest"
        )
        self.assertEqual(type(request).__name__, "SendMultiMediaRequest")
        self.assertEqual(request.peer, "input:peer:test")
        self.assertEqual(len(request.multi_media), 2)
        self.assertEqual(request.multi_media[0].message, "done")
        self.assertEqual(request.multi_media[1].message, "")
        self.assertEqual(type(request.reply_to).__name__, "InputReplyToMessage")
        self.assertEqual(request.reply_to.reply_to_msg_id, 456)
        self.assertEqual(request.reply_to.top_msg_id, 456)

    async def test_send_media_group_action_preserves_video_and_spoiler_flags(self):
        client = _FakeClient()
        types_module = _ensure_media_stub_types()
        photo_media_type = types_module.InputMediaUploadedPhoto
        document_media_type = types_module.InputMediaUploadedDocument

        async def _build_input_media(_client, file_path, **kwargs):
            if file_path.endswith(".mp4"):
                return None, document_media_type(file=file_path), False
            return None, photo_media_type(file=file_path), False

        sender = TelethonRequestSender(
            client=client,
            peer="peer:test",
            build_input_media=_build_input_media,
        )

        await sender.send_media_group_action(
            request_sender_module.MediaGroupAction(
                media_items=[("/tmp/a.png", True, False), ("/tmp/b.mp4", False, True)],
                caption="done",
                caption_parse_mode=None,
                reply_to=None,
                action_name="photo",
                fallback_action=None,
            )
        )

        request = next(
            request for request in client.requests if type(request).__name__ == "SendMultiMediaRequest"
        )
        self.assertTrue(request.multi_media[0].media.spoiler)
        self.assertTrue(request.multi_media[1].media.kwargs["supports_streaming"])
