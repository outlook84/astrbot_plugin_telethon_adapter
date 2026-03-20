from __future__ import annotations

import html
import re
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Pattern

from bs4 import BeautifulSoup
import markdown

ThreadRunner = Callable[..., Awaitable[str]]


@dataclass(slots=True)
class TelethonTextRenderer:
    max_message_length: int
    split_patterns: dict[str, Pattern[str]]
    markdown_hint_patterns: tuple[Pattern[str], ...]

    @staticmethod
    def format_at_text(item: Any) -> str:
        qq_str = str(item.qq).strip()
        if qq_str.startswith("@"):
            return f"{qq_str} "
        display = str(item.name or "").strip()
        if display.startswith("@"):
            return f"{display} "
        if display and " " not in display:
            return f"@{display} "
        if qq_str:
            return f"@{qq_str} "
        return f"@{qq_str} "

    @classmethod
    def format_at_html(cls, item: Any) -> str | None:
        qq_str = str(item.qq).strip()
        display = cls.format_at_text(item).strip()
        if qq_str.isdigit():
            href = f"tg://user?id={qq_str}"
            return f'<a href="{href}">{html.escape(display)}</a> '

        username = ""
        if qq_str.startswith("@"):
            username = qq_str[1:]
        elif qq_str and " " not in qq_str:
            username = qq_str
        else:
            raw_name = str(item.name or "").strip()
            if raw_name.startswith("@"):
                username = raw_name[1:]
            elif raw_name and " " not in raw_name:
                username = raw_name

        if not username:
            return None
        href = f"https://t.me/{html.escape(username, quote=True)}"
        return f'<a href="{href}">{html.escape(display)}</a> '

    def split_message(self, text: str) -> list[str]:
        if len(text) <= self.max_message_length:
            return [text]
        chunks: list[str] = []
        while text:
            if len(text) <= self.max_message_length:
                chunks.append(text)
                break

            split_point = self.max_message_length
            segment = text[: self.max_message_length]
            for _, pattern in self.split_patterns.items():
                matches = list(pattern.finditer(segment))
                if matches:
                    split_point = matches[-1].end()
                    break
            chunks.append(text[:split_point])
            text = text[split_point:].lstrip()
        return chunks

    def split_html_message(self, html_text: str) -> list[str]:
        if len(html_text) <= self.max_message_length:
            return [html_text]

        token_pattern = re.compile(r"(<[^>]+>)")
        void_tags = {"br", "hr"}
        stack: list[tuple[str, str]] = []
        chunks: list[str] = []
        current = ""

        def closing_tags() -> str:
            return "".join(f"</{tag}>" for tag, _ in reversed(stack))

        def opening_tags() -> str:
            return "".join(open_tag for _, open_tag in stack)

        def flush_current() -> None:
            nonlocal current
            if current:
                if current == opening_tags():
                    stack.clear()
                    current = ""
                    return
                chunks.append(current + closing_tags())
                current = opening_tags()

        def append_text(text: str) -> None:
            nonlocal current
            while text:
                reserved = len(closing_tags())
                available = self.max_message_length - len(current) - reserved
                if available <= 0:
                    if stack and current == opening_tags():
                        # Reopening tags can consume the entire chunk budget for
                        # deeply nested or long-link markup. Drop that carry-over
                        # formatting so we can keep splitting instead of looping.
                        stack.clear()
                        current = ""
                        continue
                    flush_current()
                    continue
                if len(text) <= available:
                    current += text
                    return
                current += text[:available]
                text = text[available:]
                flush_current()

        for token in token_pattern.split(html_text):
            if not token:
                continue
            if token.startswith("<") and token.endswith(">"):
                tag_match = re.match(r"</?([a-zA-Z0-9]+)", token)
                if not tag_match:
                    append_text(token)
                    continue
                tag_name = tag_match.group(1).lower()
                is_closing = token.startswith("</")
                is_self_closing = token.endswith("/>") or tag_name in void_tags
                if is_closing:
                    closing_index = None
                    for index in range(len(stack) - 1, -1, -1):
                        if stack[index][0] == tag_name:
                            closing_index = index
                            break
                    if closing_index is None:
                        continue
                if len(current) + len(token) + len(closing_tags()) > self.max_message_length:
                    flush_current()
                current += token
                if is_closing:
                    del stack[closing_index:]
                elif not is_self_closing:
                    stack.append((tag_name, token))
                continue
            append_text(token)

        if current:
            chunks.append(current + closing_tags())
        return [chunk for chunk in chunks if chunk]

    def pack_text_chunks(
        self,
        text_parts: list[tuple[str, bool]],
    ) -> list[list[tuple[str, bool]]]:
        packed: list[list[tuple[str, bool]]] = []
        current: list[tuple[str, bool]] = []
        current_length = 0

        def flush_current() -> None:
            nonlocal current
            nonlocal current_length
            if current:
                packed.append(current)
                current = []
                current_length = 0

        for part, is_html in text_parts:
            if not part:
                continue
            if is_html and len(part) > self.max_message_length:
                flush_current()
                packed.extend([[(chunk, True)] for chunk in self.split_html_message(part)])
                continue
            if not is_html and len(part) > self.max_message_length:
                flush_current()
                packed.extend([[(chunk, False)] for chunk in self.split_message(part)])
                continue
            if current_length + len(part) <= self.max_message_length:
                current.append((part, is_html))
                current_length += len(part)
            else:
                flush_current()
                current = [(part, is_html)]
                current_length = len(part)
        flush_current()
        return packed

    @staticmethod
    def render_text_chunk(text_parts: list[tuple[str, bool]]) -> str:
        return "".join(part if is_html else html.escape(part) for part, is_html in text_parts)

    def looks_like_markdown(self, text: str) -> bool:
        return any(pattern.search(text) for pattern in self.markdown_hint_patterns)

    @staticmethod
    def render_table(node: Any) -> str:
        rows: list[list[str]] = []
        for tr in node.find_all("tr"):
            cells = [cell.get_text(" ", strip=True) for cell in tr.find_all(["th", "td"])]
            if cells:
                rows.append(cells)
        if not rows:
            return ""

        column_count = max(len(row) for row in rows)
        normalized_rows = [row + [""] * (column_count - len(row)) for row in rows]
        widths = [
            max(len(row[index]) for row in normalized_rows)
            for index in range(column_count)
        ]

        rendered_rows: list[str] = []
        for index, row in enumerate(normalized_rows):
            rendered_rows.append(
                " | ".join(cell.ljust(widths[cell_index]) for cell_index, cell in enumerate(row))
            )
            if index == 0 and len(normalized_rows) > 1:
                rendered_rows.append("-+-".join("-" * width for width in widths))
        table_text = "\n".join(rendered_rows).rstrip()
        return f"<pre><code>{html.escape(table_text)}</code></pre>\n"

    @classmethod
    def format_markdown_for_telethon_html(cls, text: str) -> str:
        raw_html = markdown.markdown(text, extensions=["fenced_code", "tables"])
        soup = BeautifulSoup(raw_html, "html.parser")
        block_container_tags = {"ul", "ol", "blockquote"}

        def should_skip_whitespace_text(node: Any) -> bool:
            return (
                getattr(node.parent, "name", None) in block_container_tags
                and not str(node).strip()
            )

        def is_list_item_paragraph(node: Any) -> bool:
            return getattr(node.parent, "name", None) == "li"

        def convert(node: Any) -> str:
            if node.name is None:
                if should_skip_whitespace_text(node):
                    return ""
                return html.escape(str(node))

            tag = node.name
            if tag == "pre":
                code_node = node.find("code")
                code_text = html.escape(node.get_text())
                language = ""
                if code_node:
                    for css_class in code_node.get("class", []):
                        if css_class.startswith("language-"):
                            language = css_class[len("language-") :]
                            break
                inner_tag = f'<code class="{html.escape(language)}">' if language else "<code>"
                return f"<pre>{inner_tag}{code_text}</code></pre>"
            if tag == "table":
                return cls.render_table(node)

            inner = "".join(convert(child) for child in node.children)

            if tag in ("b", "strong"):
                return f"<b>{inner}</b>"
            if tag in ("i", "em"):
                return f"<i>{inner}</i>"
            if tag in ("s", "del", "strike"):
                return f"<s>{inner}</s>"
            if tag == "u":
                return f"<u>{inner}</u>"
            if tag == "code":
                return f"<code>{inner}</code>"
            if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
                return f"<b>{inner}</b>\n"
            if tag == "p":
                if is_list_item_paragraph(node):
                    return inner
                return f"{inner}\n"
            if tag == "br":
                return "\n"
            if tag == "hr":
                return "\n------\n"
            if tag == "a":
                href = html.escape(node.get("href", ""))
                return f'<a href="{href}">{inner}</a>'
            if tag in ("ul", "ol"):
                return inner
            if tag == "li":
                return f"• {inner.strip()}\n"
            if tag == "blockquote":
                return f"<blockquote>{inner.strip()}</blockquote>\n"
            return inner

        result = "".join(convert(child) for child in soup.children)
        return re.sub(r"\n{3,}", "\n\n", result).strip()

    async def format_markdown_async(
        self,
        text: str,
        *,
        formatter: Callable[[str], str],
        thread_runner: ThreadRunner,
    ) -> str:
        return await thread_runner(formatter, text)
