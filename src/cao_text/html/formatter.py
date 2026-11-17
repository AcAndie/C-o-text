"""MarkdownFormatter: chuyển đổi HTML sang Markdown định dạng chuẩn Obsidian.

Bao gồm:
  - Tách đoạn và dòng trống hợp lệ.
  - Định dạng in đậm (bold) và in nghiêng (italic), xử lý ranh giới khoảng trắng CommonMark.
  - Escape các ký tự đặc biệt Markdown trong văn bản gốc (*, `, [, ], \\).
  - Định dạng bảng biểu (table và dl).
  - Đường kẻ ngang phân đoạn (hr dividers).
  - Hộp hệ thống (system_box) và ghi chú tác giả (author_note).
  - Trích xuất ảnh nhúng (inline image) trả về ImageRef và placeholder marker.
"""
from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import urljoin

from bs4 import NavigableString, Tag

from cao_text.models import FormattingRules, ImageRef

logger = logging.getLogger(__name__)

# Các thẻ luôn bỏ qua khi bóc tách văn bản
_EXTRACT_SKIP_TAGS = frozenset({
    "script",
    "style",
    "noscript",
    "iframe",
    "nav",
    "header",
    "footer",
    "aside",
    "button",
    "form",
    "input",
    "select",
    "figure",
})

_WS_RE = re.compile(r"[ \t]+")
_BLANK_LINES = re.compile(r"\n{3,}")

# Escape các ký tự Markdown trong văn bản gốc để tránh làm vỡ định dạng hiển thị
_MD_ESCAPE_RE = re.compile(r"([\\*`\[\]])")

# Thứ tự các thuộc tính src của thẻ <img> (hỗ trợ lazy-loading)
_IMG_SRC_ATTRS = ("src", "data-src", "data-original", "data-lazy-src", "data-actual-src")


def _escape_md(text: str) -> str:
    """Escape ký tự Markdown trong văn bản nguồn."""
    return _MD_ESCAPE_RE.sub(r"\\\1", text)


def _wrap_emphasis(marker: str, inner: str) -> str:
    """Bao bọc văn bản bằng marker (* hoặc **).

    Đẩy khoảng trắng đầu/cuối ra ngoài marker để CommonMark nhận diện ranh giới từ hợp lệ.
    """
    if not inner:
        return ""
    core = inner.strip()
    if not core:
        return inner
    lead = inner[: len(inner) - len(inner.lstrip())]
    trail = inner[len(inner.rstrip()) :]
    return f"{lead}{marker}{core}{marker}{trail}"


def resolve_image_url(tag: Tag, base_url: str) -> str | None:
    """Chuẩn hóa URL của thẻ <img> thành absolute URL.

    Trả về None nếu:
      - Không có src/data-src/srcset hợp lệ.
      - Là inline base64 (data: URI).
      - URL rỗng.
    """
    url: str | None = None

    for attr in _IMG_SRC_ATTRS:
        val = tag.get(attr)
        if val and isinstance(val, str) and not val.startswith("data:"):
            url = val
            break

    if not url:
        srcset = tag.get("srcset")
        if srcset and isinstance(srcset, str):
            parts = [p.strip() for p in srcset.split(",") if p.strip()]
            if parts:
                last = parts[-1].split()
                if last:
                    url = last[0]

    if not url or url.startswith("data:"):
        return None

    if url.startswith("//"):
        return "https:" + url
    if url.startswith(("http://", "https://")):
        return url
    return urljoin(base_url, url)


def extract_plain_text(el: Tag) -> str:
    """Bóc tách văn bản thuần từ element, giữ lại phân tách đoạn, loại bỏ thẻ HTML."""
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
        elif tag == "li":
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
                if ctag == "br":
                    parts.append("\n")
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
    """Chuyển đổi HTML element sang Markdown dựa theo FormattingRules."""

    _DEFAULT_RULES: dict[str, Any] = {
        "tables": True,
        "bold_italic": True,
        "hr_dividers": True,
        "system_box": {},
        "author_note": {},
        "hidden_text": {},
    }

    def __init__(self, formatting_rules: dict[str, Any] | FormattingRules | None = None) -> None:
        if isinstance(formatting_rules, FormattingRules):
            raw_rules = formatting_rules.model_dump()
        elif isinstance(formatting_rules, dict):
            raw_rules = formatting_rules
        else:
            raw_rules = {}

        # §6.4: Đảm bảo đầy đủ các khóa mặc định để tránh crash
        self.rules: dict[str, Any] = {**self._DEFAULT_RULES, **raw_rules}
        self._images: list[ImageRef] = []
        self._base_url: str = ""

    def format(self, el: Tag, base_url: str = "") -> tuple[str, list[ImageRef]]:
        """Bóc tách element thành chuỗi markdown và danh sách tham chiếu ảnh ImageRef.

        Trả về (markdown_text, list[ImageRef]).
        """
        self._images = []
        self._base_url = base_url

        lines: list[str] = []
        for child in el.children:
            chunk = self._process_node(child)
            if chunk is not None:
                lines.append(chunk)

        result = "\n\n".join(lines)
        result = _BLANK_LINES.sub("\n\n", result)
        return result.strip(), list(self._images)

    def _handle_img(self, node: Tag) -> str | None:
        """Đăng ký ImageRef và trả về chuỗi placeholder cho ảnh nhúng."""
        src_url = resolve_image_url(node, self._base_url)
        if not src_url:
            return None
        idx = len(self._images)
        marker = f"IMG_PLACEHOLDER_{idx}"
        alt = (node.get("alt") or "").strip()
        self._images.append(
            ImageRef(
                original_url=src_url,
                local_path=None,
                alt_text=alt,
                position_marker=marker,
                source_type="web",
            )
        )
        return f'<div align="center">\n\n![{alt}]({marker})\n\n</div>'

    def _process_node(self, node: Any) -> str | None:
        if isinstance(node, NavigableString):
            text = str(node).strip()
            return _escape_md(text) if text else None

        if not isinstance(node, Tag):
            return None

        tag = node.name.lower() if node.name else ""

        if tag in _EXTRACT_SKIP_TAGS:
            return None

        if tag == "p":
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
            wrapped = _wrap_emphasis("**", inner)
            return wrapped if wrapped.strip() else None

        if tag in ("i", "em") and self.rules.get("bold_italic", True):
            inner = self._inline(node)
            wrapped = _wrap_emphasis("*", inner)
            return wrapped if wrapped.strip() else None

        if tag == "blockquote":
            inner = self._inline(node)
            if inner.strip():
                quoted = "\n".join(f"> {line}" for line in inner.strip().splitlines())
                return quoted
            return None

        # Luôn định dạng bảng <table> để tránh dồn text
        if tag == "table":
            return self._format_table(node)

        # Hỗ trợ <dl><dt>...<dd>... thành bảng 2 cột
        if tag == "dl":
            return self._format_dl(node)

        if tag in ("ul", "ol"):
            items: list[str] = []
            for li in node.find_all("li", recursive=False):
                items.append("- " + self._inline(li).strip())
            return "\n".join(items) if items else None

        if tag in ("div", "section", "article"):
            return self._check_special(node) or self._format_block(node)

        return self._format_block(node)

    def _check_special(self, node: Tag) -> str | None:
        """Kiểm tra system box hoặc author note."""
        for key, prefix_default in (
            ("system_box", "> [!info]+ Status"),
            ("author_note", "> 📝 "),
        ):
            rule = self.rules.get(key)
            if not isinstance(rule, dict) or not (rule.get("found") or rule.get("enabled")):
                continue
            selectors = rule.get("selectors") or ([rule["selector"]] if rule.get("selector") else [])
            for sel in selectors:
                try:
                    if node.select_one(sel) or (node.parent and node == node.parent.select_one(sel)):
                        prefix = rule.get("prefix", prefix_default)
                        inner = extract_plain_text(node)
                        lines = "\n".join(f"> {line}" for line in inner.splitlines())
                        return f"{prefix}\n{lines}"
                except Exception as e:
                    logger.debug("[Formatter] Callout selector %r failed: %s", sel, e)
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
        """Chuyển đổi node con sang định dạng inline."""
        parts: list[str] = []
        for child in node.children:
            if isinstance(child, NavigableString):
                parts.append(_escape_md(str(child)))
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
                    parts.append(_wrap_emphasis("**", inner))
                elif ctag in ("i", "em") and self.rules.get("bold_italic", True):
                    parts.append(_wrap_emphasis("*", inner))
                elif ctag == "br":
                    parts.append("\n")
                elif ctag == "a":
                    parts.append(inner)
                else:
                    parts.append(inner)
        return "".join(parts)

    def _format_dl(self, dl: Tag) -> str:
        """Chuyển đổi <dl><dt>key</dt><dd>val</dd></dl> sang bảng Markdown 2 cột."""
        rows: list[list[str]] = []
        current_dt: str | None = None
        for child in dl.children:
            if not isinstance(child, Tag):
                continue
            ctag = child.name.lower() if child.name else ""
            if ctag == "dt":
                current_dt = self._inline(child).strip().replace("|", "\\|")
            elif ctag == "dd" and current_dt is not None:
                dd_val = self._inline(child).strip().replace("|", "\\|")
                rows.append([current_dt, dd_val])
                current_dt = None
        if not rows:
            return extract_plain_text(dl)
        lines = ["|  |  |", "| --- | --- |"]
        for k, v in rows:
            lines.append(f"| {k} | {v} |")
        return "\n".join(lines)

    def _format_table(self, table: Tag) -> str:
        """Chuyển đổi thẻ <table> sang bảng chuẩn Markdown."""
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
        rows = [r + [""] * (max_cols - len(r)) for r in rows]

        lines: list[str] = [
            "| " + " | ".join(rows[0]) + " |",
            "| " + " | ".join(["---"] * max_cols) + " |",
        ]
        for row in rows[1:]:
            lines.append("| " + " | ".join(row) + " |")
        return "\n".join(lines)
