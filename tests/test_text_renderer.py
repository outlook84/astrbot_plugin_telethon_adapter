import importlib.util
import sys
import types
import unittest
from pathlib import Path


def _install_markdown_stubs() -> None:
    markdown_module = types.ModuleType("markdown")
    bs4_module = types.ModuleType("bs4")

    def markdownify(text, extensions=None):
        escaped = (
            text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
        )
        return f"<p>{escaped}</p>"

    class BeautifulSoup:
        def __init__(self, raw_html, parser):
            self.children = []

    markdown_module.markdown = markdownify
    bs4_module.BeautifulSoup = BeautifulSoup
    sys.modules["markdown"] = markdown_module
    sys.modules["bs4"] = bs4_module


def _load_text_renderer_module():
    _install_markdown_stubs()
    module_name = "test_text_renderer_under_test"
    module_path = Path(__file__).resolve().parents[1] / "telethon_adapter" / "rendering" / "text_renderer.py"
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


text_renderer_module = _load_text_renderer_module()
TelethonTextRenderer = text_renderer_module.TelethonTextRenderer


class _At:
    def __init__(self, qq, name):
        self.qq = qq
        self.name = name


class TelethonTextRendererTests(unittest.TestCase):
    def test_format_at_html_uses_clickable_links_when_possible(self):
        self.assertEqual(
            TelethonTextRenderer.format_at_html(_At(qq="123456", name="Alice")),
            '<a href="tg://user?id=123456">@Alice</a> ',
        )
        self.assertEqual(
            TelethonTextRenderer.format_at_html(_At(qq="@bob", name="Bob")),
            '<a href="https://t.me/bob">@bob</a> ',
        )

    def test_split_message_prefers_newline_boundaries(self):
        renderer = TelethonTextRenderer(
            max_message_length=4096,
            split_patterns={
                "paragraph": text_renderer_module.re.compile(r"\n\n"),
                "line": text_renderer_module.re.compile(r"\n"),
                "sentence": text_renderer_module.re.compile(r"[.!?。！？]"),
                "word": text_renderer_module.re.compile(r"\s"),
            },
            markdown_hint_patterns=(),
        )
        chunk = "a" * 4094 + "\nrest"

        parts = renderer.split_message(chunk)

        self.assertEqual(len(parts), 2)
        self.assertTrue(parts[0].endswith("\n"))
        self.assertEqual(parts[1], "rest")

    def test_split_html_message_drops_unreopenable_tags_instead_of_looping(self):
        renderer = TelethonTextRenderer(
            max_message_length=5,
            split_patterns={},
            markdown_hint_patterns=(),
        )

        parts = renderer.split_html_message("<b><i>x</i></b>")

        self.assertEqual(parts, ["x"])

    def test_markdown_conversion_skips_root_whitespace_between_block_nodes(self):
        class _FakeTextNode:
            name = None

            def __init__(self, text, parent=None):
                self._text = text
                self.parent = parent

            def __str__(self):
                return self._text

        class _FakeTag:
            def __init__(self, name, children=None, attrs=None, parent=None):
                self.name = name
                self.children = children or []
                self.attrs = attrs or {}
                self.parent = parent
                for child in self.children:
                    child.parent = self

            def find(self, name):
                for child in self.children:
                    if getattr(child, "name", None) == name:
                        return child
                return None

            def get(self, key, default=None):
                return self.attrs.get(key, default)

            def get_text(self):
                return "".join(
                    child.get_text() if getattr(child, "name", None) else str(child)
                    for child in self.children
                )

        class _FakeSoup:
            def __init__(self, children):
                self.children = children
                for child in self.children:
                    child.parent = self
                self.name = "[document]"

        first_paragraph = _FakeTag("p", [_FakeTextNode("text")])
        second_paragraph = _FakeTag(
            "p",
            [
                _FakeTag(
                    "a",
                    [_FakeTextNode("example")],
                    attrs={"href": "https://example.com"},
                )
            ],
        )
        fake_soup = _FakeSoup([first_paragraph, _FakeTextNode("\n"), second_paragraph])

        original_markdownify = text_renderer_module.markdown.markdown
        original_beautiful_soup = text_renderer_module.BeautifulSoup
        text_renderer_module.markdown.markdown = lambda text, extensions=None: "<ignored>"
        text_renderer_module.BeautifulSoup = lambda raw_html, parser: fake_soup
        try:
            rendered = TelethonTextRenderer.format_markdown_for_telethon_html("ignored")
        finally:
            text_renderer_module.markdown.markdown = original_markdownify
            text_renderer_module.BeautifulSoup = original_beautiful_soup

        self.assertEqual(rendered, 'text\n<a href="https://example.com">example</a>')
