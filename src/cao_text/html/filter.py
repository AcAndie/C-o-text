"""prepare_soup: lọc rác DOM, bảo vệ tổ tiên selector và xóa phần tử ẩn."""
from __future__ import annotations

import logging
import re
from typing import Any

from bs4 import BeautifulSoup, Tag

logger = logging.getLogger(__name__)

_ALWAYS_REMOVE: frozenset[str] = frozenset({"script", "style", "noscript", "iframe"})

# Pattern hỗ trợ `:contains()` pseudo-selector (jQuery extension không được bs4 hỗ trợ trực tiếp)
_CONTAINS_RE = re.compile(
    r'^(.*?):contains\(\s*["\'](.+?)["\']\s*\)\s*$',
    re.DOTALL,
)

# Obfuscated class watermark: RoyalRoad chèn watermark vào class ngẫu nhiên 40+ ký tự
_OBFUSCATED_CLASS_RE = re.compile(r"^[A-Za-z0-9]{40,}$")

# Các mẫu CSS style ẩn phần tử
_HIDDEN_STYLE_RE = re.compile(
    r"\b("
    r"display\s*:\s*none"
    r"|visibility\s*:\s*hidden"
    r"|opacity\s*:\s*0(?:\.0+)?(?=\s*[;\"']|\s*$)"
    r"|font-size\s*:\s*0(?:px|pt|em|rem)?(?=\s*[;\"']|\s*$)"
    r"|(?:left|right|top|bottom)\s*:\s*-9{3,}"
    r"|clip\s*:\s*rect\s*\(\s*0(?:\s*,?\s*0){3}\s*\)"
    r"|transform\s*:\s*scale\s*\(\s*0\s*\)"
    r")",
    re.IGNORECASE,
)

# Các class ngữ nghĩa biểu thị phần tử bị ẩn
_HIDDEN_CLASSES: frozenset[str] = frozenset({
    "sr-only",
    "sr-only-focusable",
    "visually-hidden",
    "visually-hidden-focusable",
    "screen-reader-only",
    "screenreader-only",
    "screenreader-text",
    "screen-reader-text",
    "d-none",
    "hidden",
    "invisible",
    "hide",
    "is-hidden",
    "u-hidden",
    "js-hidden",
    "hidden-text",
    "hide-text",
    "off-screen",
    "offscreen",
    "no-display",
    "nodisplay",
    "aria-hidden",
})

# Known noise selectors: bộ lọc an toàn mức global cho các thành phần rác phổ biến
KNOWN_NOISE_SELECTORS: list[str] = [
    # FanFiction.net
    "#profile_top",
    "#pre_story_links",
    # Royal Road
    ".author-note-portlet",
    ".portlet.blog-post",
    ".comment-container",
    ".comments-list",
    ".reading-settings",
    "#settings-popover",
    # ScribbleHub / generic
    ".chapter-comments",
    "#chapter-comments",
    ".author-bio-box",
    "[class='reading-options']",
]


def _is_alive(el: Any) -> bool:
    """Kiểm tra element còn hợp lệ trong DOM hay đã bị decompose."""
    if el is None:
        return False
    if getattr(el, "attrs", None) is None:
        return False
    if el.parent is None and getattr(el, "name", None) != "[document]":
        return False
    return True


def _strip_obfuscated_class_elements(soup: BeautifulSoup) -> int:
    """Xóa các phần tử chứa watermark dạng obfuscated class (40+ ký tự ngẫu nhiên).

    Quy tắc an toàn:
      - Bỏ qua thẻ <p> (RoyalRoad bao bọc mọi <p> trong obfuscated class).
      - Bỏ qua các phần tử có độ dài văn bản > 40 ký tự (chứa đoạn văn xuôi thật).
    """
    stripped = 0
    for el in list(soup.find_all(True)):
        if not _is_alive(el):
            continue
        classes = el.get("class") or []
        if not (len(classes) == 1 and _OBFUSCATED_CLASS_RE.match(classes[0])):
            continue

        # Quy tắc §6.4: RoyalRoad gắn class ngẫu nhiên cho mọi <p> -> không xóa <p>
        if el.name == "p":
            continue

        # Bỏ qua nếu chứa văn bản dài (watermark thường ngắn < 40 ký tự)
        if len(el.get_text(strip=True)) > 40:
            continue

        logger.debug(
            "[HtmlFilter] Stripped obfuscated-class element: <%s class=%r> text=%r",
            el.name,
            classes[0],
            el.get_text(strip=True)[:60],
        )
        el.decompose()
        stripped += 1
    return stripped


def _strip_invisible_elements(soup: BeautifulSoup) -> int:
    """Xóa các phần tử bị ẩn với người dùng bình thường:

    1. Thuộc tính HTML5 [hidden].
    2. [aria-hidden="true"].
    3. Inline CSS ẩn: display:none, visibility:hidden, opacity:0, font-size:0...
    4. Tên class ngữ nghĩa ẩn (sr-only, d-none, hidden...).
    """
    stripped = 0
    for el in list(soup.find_all(True)):
        if not _is_alive(el):
            continue

        # 1. HTML5 [hidden]
        if el.has_attr("hidden"):
            logger.debug("[HtmlFilter] Stripped [hidden]: <%s>", el.name)
            el.decompose()
            stripped += 1
            continue

        # 2. aria-hidden="true"
        if (el.get("aria-hidden") or "").lower() == "true":
            logger.debug("[HtmlFilter] Stripped aria-hidden: <%s>", el.name)
            el.decompose()
            stripped += 1
            continue

        # 3. Inline style invisible
        style_attr = el.get("style") or ""
        if style_attr and _HIDDEN_STYLE_RE.search(style_attr):
            logger.debug(
                "[HtmlFilter] Stripped hidden inline style: <%s style=%r>",
                el.name,
                style_attr[:80],
            )
            el.decompose()
            stripped += 1
            continue

        # 4. Semantic hidden class
        classes = el.get("class") or []
        if any(c.lower() in _HIDDEN_CLASSES for c in classes):
            logger.debug(
                "[HtmlFilter] Stripped hidden class: <%s class=%r>",
                el.name,
                classes,
            )
            el.decompose()
            stripped += 1
            continue

    return stripped


def _iter_selector(soup: BeautifulSoup, sel: str) -> list[Tag]:
    """Hỗ trợ query selector thông thường và :contains('text') pseudo-selector."""
    m = _CONTAINS_RE.match(sel.strip())
    if m:
        base_sel = m.group(1).strip() or "*"
        search_text = m.group(2).lower()
        try:
            candidates = soup.select(base_sel) if base_sel != "*" else soup.find_all(True)
            return [el for el in candidates if search_text in el.get_text().lower()]
        except Exception as e:
            logger.debug("[HtmlFilter] :contains() fallback error for %r: %s", sel, e)
            return []
    try:
        return soup.select(sel)
    except Exception as e:
        logger.debug("[HtmlFilter] soup.select error for %r: %s", sel, e)
        return []


def _is_protected(el: Tag, protected: list[Tag]) -> bool:
    """Kiểm tra el là chính nó hoặc là tổ tiên (ancestor) của một protected element (NAV-PROTECT)."""
    for p in protected:
        if el == p:
            return True
        try:
            if el in p.parents:
                return True
        except Exception:
            pass
    return False


def prepare_soup(
    html: str,
    remove_selectors: list[str] | None = None,
    content_selector: str | None = None,
    title_selector: str | None = None,
    next_selector: str | None = None,
) -> BeautifulSoup:
    """Parse HTML và áp dụng các layer lọc làm sạch DOM.

    Các layer:
      1. Luôn xóa các thẻ script, style, noscript, iframe.
      1b. Xóa watermark obfuscated class (trừ thẻ <p> và văn bản > 40 ký tự).
      1c. Xóa các phần tử bị ẩn (inline style, hidden attribute, aria-hidden, semantic hidden classes).
      2. Xóa các phần tử khớp KNOWN_NOISE_SELECTORS.
      3. Xóa các phần tử khớp remove_selectors của profile, BẢO VỆ tổ tiên của content/title/next selector.
    """
    if not html or not html.strip():
        return BeautifulSoup("", "html.parser")

    soup = BeautifulSoup(html, "html.parser")

    # Layer 1: Luôn xóa noise tags
    for tag in soup.find_all(_ALWAYS_REMOVE):
        tag.decompose()

    # Layer 1b: OBFUSCATED-CLASS
    n_obfuscated = _strip_obfuscated_class_elements(soup)
    if n_obfuscated:
        logger.info("[HtmlFilter] Stripped %d obfuscated-class element(s)", n_obfuscated)

    # Layer 1c: VISIBILITY-FILTER
    n_invisible = _strip_invisible_elements(soup)
    if n_invisible:
        logger.info("[HtmlFilter] Stripped %d invisible element(s)", n_invisible)

    # Layer 2: Known noise selectors
    for sel in KNOWN_NOISE_SELECTORS:
        try:
            for el in _iter_selector(soup, sel):
                if not _is_alive(el):
                    continue
                el.decompose()
        except Exception as e:
            logger.debug("[HtmlFilter] KNOWN_NOISE selector error %r: %s", sel, e)

    # Layer 3: Profile-specific remove selectors
    if not remove_selectors:
        return soup

    protected: list[Tag] = []
    for sel in (content_selector, title_selector, next_selector):
        if sel:
            try:
                el = soup.select_one(sel)
                if el:
                    protected.append(el)
            except Exception:
                pass

    for sel in remove_selectors:
        if not sel or not sel.strip():
            continue
        try:
            for el in _iter_selector(soup, sel):
                if not _is_alive(el):
                    continue
                if _is_protected(el, protected):
                    logger.debug("[HtmlFilter] Skipped protected element: %s", sel)
                    continue
                el.decompose()
        except Exception as e:
            logger.debug("[HtmlFilter] Selector error %r: %s", sel, e)

    return soup
