import importlib.util
import sys
import types
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REAL_TELETHON_SITE_PACKAGES = (
    PROJECT_ROOT / ".venv" / "lib" / "python3.13" / "site-packages"
)


def _install_astrbot_stubs() -> None:
    astrbot_module = types.ModuleType("astrbot")
    api_module = types.ModuleType("astrbot.api")
    event_module = types.ModuleType("astrbot.api.event")
    message_components_module = types.ModuleType("astrbot.api.message_components")
    platform_module = types.ModuleType("astrbot.api.platform")

    class _Logger:
        def warning(self, *args, **kwargs):
            return None

        def exception(self, *args, **kwargs):
            return None

        def debug(self, *args, **kwargs):
            return None

    class AstrMessageEvent:
        def __init__(self, *args, **kwargs):
            return None

        async def send(self, message):
            return None

    class MessageChain:
        def __init__(self, chain=None):
            self.chain = chain or []

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

    class PlatformMetadata:
        pass

    api_module.logger = _Logger()
    event_module.AstrMessageEvent = AstrMessageEvent
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
    platform_module.PlatformMetadata = PlatformMetadata

    sys.modules["astrbot"] = astrbot_module
    sys.modules["astrbot.api"] = api_module
    sys.modules["astrbot.api.event"] = event_module
    sys.modules["astrbot.api.message_components"] = message_components_module
    sys.modules["astrbot.api.platform"] = platform_module


def _install_telethon_stubs() -> None:
    telethon_module = types.ModuleType("telethon")
    functions_module = types.ModuleType("telethon.functions")
    messages_module = types.ModuleType("telethon.functions.messages")
    types_module = types.ModuleType("telethon.types")

    class SetTypingRequest:
        def __init__(self, peer, action, top_msg_id=None):
            self.peer = peer
            self.action = action
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

    class SendMessageTypingAction:
        pass

    class SendMessageUploadPhotoAction:
        def __init__(self, progress=0):
            self.progress = progress

    class InputReplyToMessage:
        def __init__(self, reply_to_msg_id, top_msg_id=None):
            self.reply_to_msg_id = reply_to_msg_id
            self.top_msg_id = top_msg_id

    class TypeSendMessageAction:
        pass

    messages_module.SetTypingRequest = SetTypingRequest
    messages_module.SendMessageRequest = SendMessageRequest
    messages_module.SendMediaRequest = SendMediaRequest
    functions_module.messages = messages_module
    types_module.InputReplyToMessage = InputReplyToMessage
    types_module.SendMessageTypingAction = SendMessageTypingAction
    types_module.SendMessageUploadPhotoAction = SendMessageUploadPhotoAction
    types_module.SendMessageUploadVideoAction = SendMessageUploadPhotoAction
    types_module.SendMessageUploadAudioAction = SendMessageUploadPhotoAction
    types_module.SendMessageUploadDocumentAction = SendMessageUploadPhotoAction
    types_module.TypeSendMessageAction = TypeSendMessageAction
    telethon_module.functions = functions_module
    telethon_module.types = types_module

    sys.modules["telethon"] = telethon_module
    sys.modules["telethon.functions"] = functions_module
    sys.modules["telethon.functions.messages"] = messages_module
    sys.modules["telethon.types"] = types_module


def _install_markdown_stubs() -> None:
    markdown_module = types.ModuleType("markdown")
    bs4_module = types.ModuleType("bs4")

    def markdownify(text, extensions=None):
        escaped = (
            text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
        )
        if text.startswith("## "):
            title, _, rest = text.partition("\n")
            title_html = f"<h2>{title[3:]}</h2>"
            if rest:
                items = "".join(
                    f"<li>{line[2:]}</li>" for line in rest.splitlines() if line.startswith("- ")
                )
                return f"{title_html}<ul>{items}</ul>"
            return title_html
        if "|" in text and "\n" in text:
            return (
                "<table>"
                "<tr><th>姓名</th><th>年龄</th></tr>"
                "<tr><td>小明</td><td>18</td></tr>"
                "</table>"
            )
        return f"<p>{escaped}</p>"

    class _Node:
        def __init__(self, item):
            self._item = item

        @property
        def name(self):
            return self._item.name if hasattr(self._item, "name") else None

        @property
        def parent(self):
            parent = getattr(self._item, "parent", None)
            return _Node(parent) if parent is not None else None

        @property
        def children(self):
            if hasattr(self._item, "contents"):
                return [_Node(child) for child in self._item.contents]
            return []

        def find(self, name):
            result = self._item.find(name)
            return _Node(result) if result is not None else None

        def find_all(self, names):
            return [_Node(child) for child in self._item.find_all(names)]

        def get(self, key, default=None):
            return self._item.attrs.get(key, default)

        def get_text(self, separator="", strip=False):
            return self._item.get_text(separator, strip=strip)

        def __str__(self):
            return str(self._item)

    class BeautifulSoup:
        def __init__(self, markup, parser):
            self._markup = markup
            self.children = [_Node(_SimpleHTMLParser.parse(markup))]

    class _Tag:
        def __init__(self, name, attrs=None, children=None, text=None, parent=None):
            self.name = name
            self.attrs = attrs or {}
            self.contents = children or []
            self._text = text
            self.parent = parent
            for child in self.contents:
                child.parent = self

        def find(self, name):
            for child in self.contents:
                if getattr(child, "name", None) == name:
                    return child
                found = child.find(name) if hasattr(child, "find") else None
                if found is not None:
                    return found
            return None

        def find_all(self, names):
            if isinstance(names, str):
                names = [names]
            result = []
            for child in self.contents:
                if getattr(child, "name", None) in names:
                    result.append(child)
                if hasattr(child, "find_all"):
                    result.extend(child.find_all(names))
            return result

        def get_text(self, separator="", strip=False):
            parts = []
            for child in self.contents:
                if hasattr(child, "get_text"):
                    parts.append(child.get_text(separator, strip=False))
                else:
                    parts.append(str(child))
            text = separator.join(part for part in parts if part)
            return text.strip() if strip else text

        def __str__(self):
            return self.get_text()

    class _TextNode:
        name = None

        def __init__(self, text, parent=None):
            self.text = text
            self.parent = parent

        def get_text(self, separator="", strip=False):
            return self.text.strip() if strip else self.text

        def __str__(self):
            return self.text

    class _SimpleHTMLParser:
        @staticmethod
        def parse(markup):
            if markup.startswith("<h2>"):
                inner = markup[len("<h2>") :]
                title, remainder = inner.split("</h2>", 1)
                list_items = []
                while "<li>" in remainder:
                    _, li_rest = remainder.split("<li>", 1)
                    item, remainder = li_rest.split("</li>", 1)
                    list_items.append(_Tag("li", children=[_TextNode(item)]))
                children = [_Tag("h2", children=[_TextNode(title)])]
                if list_items:
                    children.append(_Tag("ul", children=list_items))
                return _Tag("root", children=children)
            if markup.startswith("<table>"):
                return _Tag(
                    "root",
                    children=[
                        _Tag(
                            "table",
                            children=[
                                _Tag(
                                    "tr",
                                    children=[
                                        _Tag("th", children=[_TextNode("姓名")]),
                                        _Tag("th", children=[_TextNode("年龄")]),
                                    ],
                                ),
                                _Tag(
                                    "tr",
                                    children=[
                                        _Tag("td", children=[_TextNode("小明")]),
                                        _Tag("td", children=[_TextNode("18")]),
                                    ],
                                ),
                            ],
                        )
                    ],
                )
            if markup.startswith("<p>") and markup.endswith("</p>"):
                return _Tag("root", children=[_Tag("p", children=[_TextNode(markup[3:-4])])])
            return _Tag("root", children=[_TextNode(markup)])

    markdown_module.markdown = markdownify
    bs4_module.BeautifulSoup = BeautifulSoup
    sys.modules["markdown"] = markdown_module
    sys.modules["bs4"] = bs4_module


def _load_telethon_event_module():
    _install_astrbot_stubs()
    _install_telethon_stubs()
    _install_markdown_stubs()
    module_path = PROJECT_ROOT / "telethon_adapter" / "telethon_event.py"
    spec = importlib.util.spec_from_file_location("test_telethon_event_module", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def _load_telethon_event_module_with_real_telethon():
    _install_astrbot_stubs()
    _install_markdown_stubs()

    for module_name in list(sys.modules):
        if module_name == "telethon" or module_name.startswith("telethon."):
            sys.modules.pop(module_name, None)

    site_packages = str(REAL_TELETHON_SITE_PACKAGES)
    if site_packages not in sys.path:
        sys.path.insert(0, site_packages)

    module_path = PROJECT_ROOT / "telethon_adapter" / "telethon_event.py"
    spec = importlib.util.spec_from_file_location(
        "test_telethon_event_real_module",
        module_path,
    )
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


class _FakeClient:
    def __init__(self, fail_html: bool = False) -> None:
        self.fail_html = fail_html
        self.sent_messages = []
        self.typing_actions = []
        self.sent_files = []
        self.requests = []

    async def __call__(self, request):
        self.requests.append(request)
        if type(request).__name__ == "SetTypingRequest":
            self.typing_actions.append(request)
        return {"request": request}

    async def send_message(self, peer, text, **kwargs):
        if kwargs.get("parse_mode") == "html" and self.fail_html:
            raise RuntimeError("html failed")
        self.sent_messages.append((peer, text, kwargs))
        return {"peer": peer, "text": text, "kwargs": kwargs}

    async def send_file(self, peer, file, caption=None, reply_to=None):
        self.sent_files.append((peer, file, caption, reply_to))
        return {"peer": peer, "file": file, "caption": caption, "reply_to": reply_to}

    async def get_input_entity(self, peer):
        return f"input:{peer}"

    async def _parse_message_text(self, text, parse_mode):
        return text, [types.SimpleNamespace(parse_mode=parse_mode)]

    async def _file_to_media(self, file, **kwargs):
        return None, f"media:{file}", file.lower().endswith((".png", ".jpg", ".jpeg", ".gif"))

    def _get_response_message(self, request, result, entity):
        return {"request": request, "result": result, "entity": entity}


class _FakeImage:
    type = "Image"

    def __init__(self, path: str) -> None:
        self._path = path

    async def convert_to_file_path(self):
        return self._path


def _make_image_component(path: str):
    image_type = sys.modules["astrbot.api.message_components"].Image
    image = image_type()

    async def _convert_to_file_path():
        return path

    image.convert_to_file_path = _convert_to_file_path
    return image


class TelethonEventTests(unittest.IsolatedAsyncioTestCase):
    def test_parse_session_target_supports_topic_session_id(self):
        module = _load_telethon_event_module()

        peer, thread_id = module.TelethonEvent._parse_session_target("123456#789")

        self.assertEqual(peer, 123456)
        self.assertEqual(thread_id, 789)

    def test_split_message_prefers_newline_boundaries(self):
        module = _load_telethon_event_module()
        chunk = "a" * 4094 + "\nrest"

        parts = module.TelethonEvent._split_message(chunk)

        self.assertEqual(len(parts), 2)
        self.assertTrue(parts[0].endswith("\n"))
        self.assertEqual(parts[1], "rest")

    async def test_send_text_uses_html_for_markdown_like_text(self):
        module = _load_telethon_event_module()
        client = _FakeClient()
        event = module.TelethonEvent("", object(), object(), "123", client)

        await event._send_text_with_action("## title\n- item", 7)

        self.assertEqual(len(client.sent_messages), 1)
        peer, text, kwargs = client.sent_messages[0]
        self.assertEqual(peer, 123)
        self.assertEqual(text, "<b>title</b>\n• item")
        self.assertEqual(kwargs["parse_mode"], "html")
        self.assertEqual(kwargs["reply_to"], 7)
        self.assertFalse(kwargs["link_preview"])

    async def test_send_text_uses_plain_text_for_normal_text(self):
        module = _load_telethon_event_module()
        client = _FakeClient()
        event = module.TelethonEvent("", object(), object(), "123", client)

        await event._send_text_with_action("hello (world)_v2", None)

        self.assertEqual(len(client.sent_messages), 1)
        peer, text, kwargs = client.sent_messages[0]
        self.assertEqual(peer, 123)
        self.assertEqual(text, "hello (world)_v2")
        self.assertNotIn("parse_mode", kwargs)

    async def test_send_text_formats_table_as_pre_block(self):
        module = _load_telethon_event_module()
        client = _FakeClient()
        event = module.TelethonEvent("", object(), object(), "123", client)

        await event._send_text_with_action("| 姓名 | 年龄 |\n| --- | --- |\n| 小明 | 18 |", None)

        self.assertEqual(len(client.sent_messages), 1)
        _, text, kwargs = client.sent_messages[0]
        self.assertIn("<pre><code>", text)
        self.assertIn("姓名", text)
        self.assertIn("小明", text)
        self.assertEqual(kwargs["parse_mode"], "html")

    async def test_send_text_falls_back_to_plain_text_on_html_error(self):
        module = _load_telethon_event_module()
        client = _FakeClient(fail_html=True)
        event = module.TelethonEvent("", object(), object(), "123", client)

        await event._send_text_with_action("## title", None)

        self.assertEqual(len(client.sent_messages), 1)
        peer, text, kwargs = client.sent_messages[0]
        self.assertEqual(peer, 123)
        self.assertEqual(text, "## title")
        self.assertNotIn("parse_mode", kwargs)

    def test_format_at_text_matches_plain_prefix_behavior(self):
        module = _load_telethon_event_module()
        At = sys.modules["astrbot.api.message_components"].At

        self.assertEqual(module.TelethonEvent._format_at_text(At(qq="alice", name="alice")), "@alice ")
        self.assertEqual(module.TelethonEvent._format_at_text(At(qq="123456", name="Alice")), "@Alice ")
        self.assertEqual(module.TelethonEvent._format_at_text(At(qq="@bob", name="Bob")), "@bob ")

    def test_format_at_html_uses_clickable_links_when_possible(self):
        module = _load_telethon_event_module()
        At = sys.modules["astrbot.api.message_components"].At

        self.assertEqual(
            module.TelethonEvent._format_at_html(At(qq="123456", name="Alice")),
            '<a href="tg://user?id=123456">@Alice</a> ',
        )
        self.assertEqual(
            module.TelethonEvent._format_at_html(At(qq="@bob", name="Bob")),
            '<a href="https://t.me/bob">@bob</a> ',
        )

    async def test_send_splits_long_plain_text_and_preserves_reply_to(self):
        module = _load_telethon_event_module()
        client = _FakeClient()
        event = module.TelethonEvent("", object(), object(), "123", client)
        reply_type = sys.modules["astrbot.api.message_components"].Reply
        plain_type = sys.modules["astrbot.api.message_components"].Plain
        chain_type = sys.modules["astrbot.api.event"].MessageChain
        long_text = "x" * 5000

        await event.send(
            chain_type(
                [
                    reply_type(id="77"),
                    plain_type(text=long_text),
                ]
            )
        )

        self.assertEqual(len(client.sent_messages), 2)
        self.assertTrue(
            all(
                len(text) <= module.TelethonEvent.MAX_MESSAGE_LENGTH
                for _, text, _ in client.sent_messages
            )
        )
        self.assertEqual(client.sent_messages[0][2]["reply_to"], 77)
        self.assertEqual(client.sent_messages[1][2]["reply_to"], 77)
        self.assertEqual("".join(text for _, text, _ in client.sent_messages), long_text)

    async def test_send_uses_html_for_clickable_at_mentions(self):
        module = _load_telethon_event_module()
        client = _FakeClient()
        event = module.TelethonEvent("", object(), object(), "123", client)
        at_type = sys.modules["astrbot.api.message_components"].At
        plain_type = sys.modules["astrbot.api.message_components"].Plain
        chain_type = sys.modules["astrbot.api.event"].MessageChain

        await event.send(
            chain_type(
                [
                    at_type(qq="123456", name="Alice"),
                    plain_type(text=" hello <world>"),
                ]
            )
        )

        self.assertEqual(len(client.sent_messages), 1)
        peer, text, kwargs = client.sent_messages[0]
        self.assertEqual(peer, 123)
        self.assertEqual(
            text,
            '<a href="tg://user?id=123456">@Alice</a>  hello &lt;world&gt;',
        )
        self.assertEqual(kwargs["parse_mode"], "html")

    async def test_send_topic_session_defaults_reply_to_thread_root(self):
        module = _load_telethon_event_module()
        client = _FakeClient()
        event = module.TelethonEvent("", object(), object(), "123#456", client)
        plain_type = sys.modules["astrbot.api.message_components"].Plain
        chain_type = sys.modules["astrbot.api.event"].MessageChain

        await event.send(chain_type([plain_type(text="hello topic")]))

        self.assertEqual(len(client.sent_messages), 0)
        request = next(
            request for request in client.requests if type(request).__name__ == "SendMessageRequest"
        )
        self.assertEqual(request.peer, "input:123")
        self.assertEqual(request.message, "hello topic")
        self.assertEqual(type(request.reply_to).__name__, "InputReplyToMessage")
        self.assertEqual(request.reply_to.reply_to_msg_id, 456)
        self.assertEqual(request.reply_to.top_msg_id, 456)
        self.assertEqual(client.typing_actions[0].top_msg_id, 456)

    async def test_explicit_reply_overrides_topic_thread_root(self):
        module = _load_telethon_event_module()
        client = _FakeClient()
        event = module.TelethonEvent("", object(), object(), "123#456", client)
        plain_type = sys.modules["astrbot.api.message_components"].Plain
        reply_type = sys.modules["astrbot.api.message_components"].Reply
        chain_type = sys.modules["astrbot.api.event"].MessageChain

        await event.send(chain_type([reply_type(id="999"), plain_type(text="hello")]))

        request = next(
            request for request in client.requests if type(request).__name__ == "SendMessageRequest"
        )
        self.assertEqual(request.peer, "input:123")
        self.assertEqual(type(request.reply_to).__name__, "InputReplyToMessage")
        self.assertEqual(request.reply_to.reply_to_msg_id, 999)
        self.assertEqual(request.reply_to.top_msg_id, 456)

    async def test_send_topic_image_defaults_reply_to_thread_root(self):
        module = _load_telethon_event_module()
        client = _FakeClient()
        event = module.TelethonEvent("", object(), object(), "123#456", client)
        chain_type = sys.modules["astrbot.api.event"].MessageChain

        await event.send(chain_type([_make_image_component("/tmp/topic-image.png")]))

        self.assertEqual(len(client.sent_files), 0)
        request = next(
            request for request in client.requests if type(request).__name__ == "SendMediaRequest"
        )
        self.assertEqual(request.peer, "input:123")
        self.assertEqual(request.media, "media:/tmp/topic-image.png")
        self.assertEqual(request.message, "")
        self.assertEqual(type(request.reply_to).__name__, "InputReplyToMessage")
        self.assertEqual(request.reply_to.reply_to_msg_id, 456)
        self.assertEqual(request.reply_to.top_msg_id, 456)

    async def test_send_topic_image_preserves_explicit_reply_and_thread(self):
        module = _load_telethon_event_module()
        client = _FakeClient()
        event = module.TelethonEvent("", object(), object(), "123#456", client)
        reply_type = sys.modules["astrbot.api.message_components"].Reply
        chain_type = sys.modules["astrbot.api.event"].MessageChain

        await event.send(
            chain_type(
                [
                    reply_type(id="999"),
                    _make_image_component("/tmp/topic-image.png"),
                ]
            )
        )

        request = next(
            request for request in client.requests if type(request).__name__ == "SendMediaRequest"
        )
        self.assertEqual(request.peer, "input:123")
        self.assertEqual(request.media, "media:/tmp/topic-image.png")
        self.assertEqual(request.message, "")
        self.assertEqual(type(request.reply_to).__name__, "InputReplyToMessage")
        self.assertEqual(request.reply_to.reply_to_msg_id, 999)
        self.assertEqual(request.reply_to.top_msg_id, 456)


@unittest.skipUnless(
    REAL_TELETHON_SITE_PACKAGES.exists(),
    "real Telethon test requires project .venv",
)
class TelethonEventRealTelethonTests(unittest.IsolatedAsyncioTestCase):
    async def test_send_topic_session_uses_real_input_reply_to_message(self):
        module = _load_telethon_event_module_with_real_telethon()
        from telethon.tl.types import InputReplyToMessage

        client = _FakeClient()
        event = module.TelethonEvent("", object(), object(), "123#456", client)
        plain_type = sys.modules["astrbot.api.message_components"].Plain
        chain_type = sys.modules["astrbot.api.event"].MessageChain

        await event.send(chain_type([plain_type(text="hello topic")]))

        from telethon.tl.functions.messages import SendMessageRequest

        request = next(
            request for request in client.requests if isinstance(request, SendMessageRequest)
        )
        self.assertEqual(request.message, "hello topic")
        self.assertIsInstance(request.reply_to, InputReplyToMessage)
        self.assertEqual(request.reply_to.reply_to_msg_id, 456)
        self.assertEqual(request.reply_to.top_msg_id, 456)

    async def test_send_typing_uses_real_set_typing_request_with_thread(self):
        module = _load_telethon_event_module_with_real_telethon()
        from telethon.tl.functions.messages import SetTypingRequest

        client = _FakeClient()
        event = module.TelethonEvent("", object(), object(), "123#456", client)

        await event.send_typing()

        self.assertEqual(len(client.typing_actions), 1)
        request = client.typing_actions[0]
        self.assertIsInstance(request, SetTypingRequest)
        self.assertEqual(request.peer, 123)
        self.assertEqual(request.top_msg_id, 456)

    async def test_send_topic_image_uses_real_input_reply_to_message(self):
        module = _load_telethon_event_module_with_real_telethon()
        from telethon.tl.types import InputReplyToMessage

        client = _FakeClient()
        event = module.TelethonEvent("", object(), object(), "123#456", client)
        chain_type = sys.modules["astrbot.api.event"].MessageChain

        await event.send(chain_type([_make_image_component("/tmp/topic-image.png")]))

        from telethon.tl.functions.messages import SendMediaRequest

        request = next(
            request for request in client.requests if isinstance(request, SendMediaRequest)
        )
        self.assertEqual(request.media, "media:/tmp/topic-image.png")
        self.assertEqual(request.message, "")
        self.assertIsInstance(request.reply_to, InputReplyToMessage)
        self.assertEqual(request.reply_to.reply_to_msg_id, 456)
        self.assertEqual(request.reply_to.top_msg_id, 456)

    async def test_send_topic_image_with_explicit_reply_uses_real_input_reply_to_message(self):
        module = _load_telethon_event_module_with_real_telethon()
        from telethon.tl.types import InputReplyToMessage

        client = _FakeClient()
        event = module.TelethonEvent("", object(), object(), "123#456", client)
        reply_type = sys.modules["astrbot.api.message_components"].Reply
        chain_type = sys.modules["astrbot.api.event"].MessageChain

        await event.send(
            chain_type(
                [
                    reply_type(id="999"),
                    _make_image_component("/tmp/topic-image.png"),
                ]
            )
        )

        from telethon.tl.functions.messages import SendMediaRequest

        request = next(
            request for request in client.requests if isinstance(request, SendMediaRequest)
        )
        self.assertEqual(request.media, "media:/tmp/topic-image.png")
        self.assertEqual(request.message, "")
        self.assertIsInstance(request.reply_to, InputReplyToMessage)
        self.assertEqual(request.reply_to.reply_to_msg_id, 999)
        self.assertEqual(request.reply_to.top_msg_id, 456)


if __name__ == "__main__":
    unittest.main()
