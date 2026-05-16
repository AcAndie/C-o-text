"""
core/formatter.py — HTML → Markdown/plain-text conversion.

Public API:
    MarkdownFormatter(formatting_rules).format(element, base_url="")
        → tuple[str, list[ImageRef]]
    extract_plain_text(element) → str

P2.3: format() return tuple (text, images). Image emit
`![alt](IMG_PLACEHOLDER_N)` placeholder + ImageRef registered trong list.
Position marker tăng dần theo HTML traversal order. Caller (pipeline image
stage) sẽ resolve placeholder → relative path sau khi fetch.

MarkdownFormatter xử lý:
  - Paragraph separation
  - Bold / italic
  - Tables → Markdown table syntax (nếu formatting_rules.tables = True)
  - HR dividers → ---
  - System boxes → > **System:** ...
  - Author notes → > 📝 ...
  - Inline image → ![alt](IMG_PLACEHOLDER_N) (P2.3, new)

extract_plain_text: strip mọi tag, giữ paragraph breaks. Không handle img
(fallback path khi profile thiếu formatting_rules — caller wrap (text, [])).
"""
from __future__ import annotations

import re
from typing import Any

from bs4 import BeautifulSoup, NavigableString, Tag

from pipeline.base    import ImageRef
from utils.image_url  import resolve_image_url

# Tags cần skip hoàn toàn khi extract
_EXTRACT_SKIP_TAGS = frozenset({
    "script", "style", "noscript", "iframe",
    "nav", "header", "footer", "aside",
    "button", "form", "input", "select",
    "figure",
})

_WS_RE       = re.compile(r"[ \t]+")
_BLANK_LINES = re.compile(r"\n{3,}")


def extract_plain_text(el: Tag) -> str:
    """
    Extract plain text từ BeautifulSoup element.
    Giữ paragraph breaks, strip HTML noise.
    """
    lines: list[str] = []

    def _walk(node: Any, depth: int = 0) -> None:
        if isinstance(node, NavigableString):
            text = str(node)
            if text.strip():
                lines.append(text)
            return

        if not isinstance(node, Tag):
            return

        tag = node.name.lower() if node.name else ""
        if tag in _EXTRACT_SKIP_TAGS:
            return

        if tag in ("p", "div", "article", "section", "blockquote"):
            # Flush current line, process children, then blank line
            inner = _collect_text(node)
            if inner.strip():
                lines.append("\n" + inner.strip() + "\n")
        elif tag == "br":
            lines.append("\n")
        elif tag in ("h1", "h2", "h3", "h4"):
            inner = _collect_text(node)
            if inner.strip():
                lines.append("\n" + inner.strip() + "\n")
        elif tag == "hr":
            lines.append("\n---\n")
        elif tag in ("li",):
            inner = _collect_text(node)
            if inner.strip():
                lines.append("- " + inner.strip())
        else:
            for child in node.children:
                _walk(child, depth + 1)

    def _collect_text(node: Tag) -> str:
        parts: list[str] = []
        for child in node.children:
            if isinstance(child, NavigableString):
                parts.append(str(child))
            elif isinstance(child, Tag):
                ctag = child.name.lower() if child.name else ""
                if ctag in _EXTRACT_SKIP_TAGS:
                    continue
                elif ctag == "br":
                    parts.append("\n")
                elif ctag in ("b", "strong"):
                    parts.append(_collect_text(child))
                elif ctag in ("i", "em"):
                    parts.append(_collect_text(child))
                else:
                    parts.append(_collect_text(child))
        return "".join(parts)

    for child in el.children:
        _walk(child)

    result = "".join(lines)
    result = _WS_RE.sub(" ", result)
    result = _BLANK_LINES.sub("\n\n", result)
    return result.strip()


class MarkdownFormatter:
    """
    Convert HTML element → Markdown với formatting rules từ SiteProfile.

    P2.3: format() return tuple (text, images). self._images reset mỗi
    format() call. self._base_url dùng để resolve relative img src.
    """

    def __init__(self, formatting_rules: dict) -> None:
        self.rules    = formatting_rules or {}
        self._images  : list[ImageRef] = []
        self._base_url: str            = ""

    def format(self, el: Tag, base_url: str = "") -> tuple[str, list[ImageRef]]:
        """
        Main entry point. Return (markdown_text, list_of_image_refs).

        Image trong element → emit `![alt](IMG_PLACEHOLDER_N)` placeholder
        + ImageRef registered. Caller pipeline stage sẽ fetch + rewrite
        placeholder → relative path.
        """
        self._images   = []
        self._base_url = base_url

        lines: list[str] = []
        for child in el.children:
            chunk = self._process_node(child)
            if chunk is not None:
                lines.append(chunk)

        result = "\n".join(lines)
        result = _BLANK_LINES.sub("\n\n", result)
        return result.strip(), list(self._images)

    def _handle_img(self, node: Tag) -> str | None:
        """
        Resolve <img> tag → register ImageRef → return placeholder string.
        Return None nếu URL không hợp lệ (data: URI, missing src).
        """
        src_url = resolve_image_url(node, self._base_url)
        if not src_url:
            return None
        idx    = len(self._images)
        marker = f"IMG_PLACEHOLDER_{idx}"
        alt    = (node.get("alt") or "").strip()
        self._images.append(ImageRef(
            original_url    = src_url,
            local_path      = None,
            alt_text        = alt,
            position_marker = marker,
            source_type     = "web",
        ))
        return f"![{alt}]({marker})"

    def _process_node(self, node: Any) -> str | None:
        if isinstance(node, NavigableString):
            text = str(node).strip()
            return text if text else None

        if not isinstance(node, Tag):
            return None

        tag = node.name.lower() if node.name else ""

        if tag in _EXTRACT_SKIP_TAGS:
            return None

        if tag in ("p",):
            inner = self._inline(node)
            return inner.strip() if inner.strip() else None

        if tag == "br":
            return ""

        if tag == "img":
            return self._handle_img(node)

        if tag == "hr" and self.rules.get("hr_dividers", True):
            return "\n---\n"

        if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            level = int(tag[1])
            inner = self._inline(node)
            return f"{'#' * level} {inner.strip()}"

        if tag in ("b", "strong") and self.rules.get("bold_italic", True):
            inner = self._inline(node)
            return f"**{inner.strip()}**" if inner.strip() else None

        if tag in ("i", "em") and self.rules.get("bold_italic", True):
            inner = self._inline(node)
            return f"*{inner.strip()}*" if inner.strip() else None

        if tag == "blockquote":
            inner = self._inline(node)
            if inner.strip():
                quoted = "\n".join(f"> {line}" for line in inner.strip().splitlines())
                return quoted
            return None

        if tag == "table" and self.rules.get("tables", False):
            return self._format_table(node)

        if tag in ("ul", "ol"):
            items: list[str] = []
            for li in node.find_all("li", recursive=False):
                items.append("- " + self._inline(li).strip())
            return "\n".join(items) if items else None

        if tag in ("div", "section", "article"):
            return self._check_special(node) or self._format_block(node)

        # Generic: recurse
        return self._format_block(node)

    def _check_special(self, node: Tag) -> str | None:
        """Check system box / hidden text / author note."""
        for key, prefix_default in (
            ("system_box",  "> **System:**\n> "),
            ("author_note", "> 📝 "),
        ):
            rule = self.rules.get(key)
            if not isinstance(rule, dict) or not rule.get("found"):
                continue
            selectors = rule.get("selectors") or []
            for sel in selectors:
                try:
                    if node.select_one(sel) or node == node.parent.select_one(sel):
                        prefix = rule.get("prefix", prefix_default)
                        inner  = extract_plain_text(node)
                        lines  = "\n".join(f"> {l}" for l in inner.splitlines())
                        return f"{prefix}\n{lines}"
                except Exception:
                    pass
        return None

    def _format_block(self, node: Tag) -> str | None:
        parts: list[str] = []
        for child in node.children:
            chunk = self._process_node(child)
            if chunk is not None:
                parts.append(chunk)
        result = "\n".join(parts).strip()
        return result if result else None

    def _inline(self, node: Tag) -> str:
        """Convert node to inline text (single line), handling bold/italic."""
        parts: list[str] = []
        for child in node.children:
            if isinstance(child, NavigableString):
                parts.append(str(child))
            elif isinstance(child, Tag):
                ctag = child.name.lower() if child.name else ""
                if ctag in _EXTRACT_SKIP_TAGS:
                    continue
                if ctag == "img":
                    img_md = self._handle_img(child)
                    if img_md:
                        parts.append(img_md)
                    continue
                inner = self._inline(child)
                if ctag in ("b", "strong") and self.rules.get("bold_italic", True):
                    parts.append(f"**{inner}**")
                elif ctag in ("i", "em") and self.rules.get("bold_italic", True):
                    parts.append(f"*{inner}*")
                elif ctag == "br":
                    parts.append("\n")
                elif ctag == "a":
                    parts.append(inner)
                else:
                    parts.append(inner)
        return "".join(parts)

    def _format_table(self, table: Tag) -> str:
        """Convert <table> → Markdown table."""
        rows: list[list[str]] = []
        for tr in table.find_all("tr"):
            cells = [
                self._inline(td).strip().replace("|", "\\|")
                for td in tr.find_all(["th", "td"])
            ]
            if cells:
                rows.append(cells)

        if not rows:
            return extract_plain_text(table)

        max_cols = max(len(r) for r in rows)
        # Pad rows
        rows = [r + [""] * (max_cols - len(r)) for r in rows]

        lines: list[str] = []
        lines.append("| " + " | ".join(rows[0]) + " |")
        lines.append("| " + " | ".join(["---"] * max_cols) + " |")
        for row in rows[1:]:
            lines.append("| " + " | ".join(row) + " |")
        return "\n".join(lines)