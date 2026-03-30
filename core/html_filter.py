"""
core/html_filter.py — Loại bỏ element ẩn / watermark khỏi BeautifulSoup tree.

Tách khỏi scraper.py để có thể test độc lập và thêm rule dễ dàng.

Thêm rule mới:
  - Style: bổ sung vào _HIDDEN_STYLE_RE
  - Class: bổ sung vào _HIDDEN_CLASS_RE
"""
import logging
import re

from bs4 import BeautifulSoup, Tag

logger = logging.getLogger(__name__)

# ── Compiled regexes ──────────────────────────────────────────────────────────

_HIDDEN_STYLE_RE = re.compile(
    r"display\s*:\s*none"
    r"|visibility\s*:\s*hidden"
    r"|opacity\s*:\s*0(?:\.0+)?\b"
    r"|font-size\s*:\s*0"
    r"|color\s*:\s*transparent"
    r"|width\s*:\s*0"
    r"|height\s*:\s*0",
    re.IGNORECASE,
)

_HIDDEN_CLASS_RE = re.compile(
    r"\b(?:hidden|invisible|sr-only|visually-hidden|"
    r"d-none|display-none|hide|offscreen|"
    r"watermark|wm-text|protect-text|anti-theft)\b",
    re.IGNORECASE,
)


# ── Public API ────────────────────────────────────────────────────────────────

def remove_hidden_elements(soup: BeautifulSoup) -> BeautifulSoup:
    """
    Xóa tất cả DOM element bị ẩn, bao gồm:
      - hidden attribute hoặc aria-hidden="true"
      - CSS inline: display:none, visibility:hidden, opacity:0, ...
      - Class chứa: hidden, invisible, watermark, anti-theft, ...

    Trả về cùng đối tượng soup (mutate in-place) để tiện chain.
    """
    removed = 0
    for el in soup.find_all(True):
        if isinstance(el, Tag) and isinstance(el.attrs, dict) and _is_hidden(el):
            el.decompose()
            removed += 1

    if removed:
        logger.debug("[HiddenFilter] Đã xóa %d element ẩn", removed)
    return soup


# ── Private helpers ───────────────────────────────────────────────────────────

def _is_hidden(el: Tag) -> bool:
    """Kiểm tra một element có đang bị ẩn hay không."""
    # HTML hidden attribute hoặc ARIA
    if el.has_attr("hidden") or el.get("aria-hidden") == "true":
        return True

    # Inline CSS style
    style = el.get("style", "")
    if style and _HIDDEN_STYLE_RE.search(style):
        return True

    # CSS class
    classes = " ".join(el.get("class", []))
    if classes and _HIDDEN_CLASS_RE.search(classes):
        return True

    return False