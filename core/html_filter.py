"""
core/html_filter.py — HTML pre-processing trước khi pipeline extract.

Public API:
    prepare_soup(html, remove_selectors, content_selector, title_selector, next_selector)
        → BeautifulSoup

Logic:
    1. Parse HTML
    2. Xóa _ALWAYS_REMOVE tags (script, style, ...)
    3. Xóa KNOWN_NOISE_SELECTORS (global safety net — TRƯỚC profile selectors)
    4. Xóa profile remove_selectors (learned per-domain)
       KHÔNG xóa nếu element là ancestor của content, title, HOẶC next selector
    5. Trả về soup đã filtered

Fix CONTAINS-SELECTOR: hỗ trợ `:contains()` pseudo-selector qua _iter_selector().
  BeautifulSoup/cssselect không support `:contains()` (jQuery extension).
  Trước: exception bị catch và silently ignored → selector không hoạt động.
  Sau: _iter_selector() detect pattern, tự implement text matching.
"""
from __future__ import annotations

import logging
import re

from bs4 import BeautifulSoup, Tag

from config import KNOWN_NOISE_SELECTORS

logger = logging.getLogger(__name__)

_ALWAYS_REMOVE = frozenset({"script", "style", "noscript", "iframe"})

# Fix CONTAINS-SELECTOR: pattern nhận diện `:contains()` pseudo-selector
# Ví dụ: "div.chapter-content > p:contains('Unauthorized usage')"
_CONTAINS_RE = re.compile(
    r'^(.*?):contains\(\s*["\'](.+?)["\']\s*\)\s*$',
    re.DOTALL,
)


def _iter_selector(soup: BeautifulSoup, sel: str) -> list[Tag]:
    """
    Wrapper quanh soup.select() có hỗ trợ `:contains()` pseudo-selector.

    Nếu selector có dạng `base:contains('text')`:
        1. Chạy soup.select(base) để lấy candidates
        2. Filter lấy những element có text chứa chuỗi cần tìm (case-insensitive)

    Nếu không có `:contains()` → dùng soup.select() bình thường.
    """
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
    # Normal CSS selector
    return soup.select(sel)


def prepare_soup(
    html             : str,
    remove_selectors : list[str],
    content_selector : str | None = None,
    title_selector   : str | None = None,
    next_selector    : str | None = None,
) -> BeautifulSoup:
    """
    Parse HTML và apply 3-layer filtering.
    """
    soup = BeautifulSoup(html, "html.parser")

    # Layer 1: Luôn xóa noise tags
    for tag in soup.find_all(_ALWAYS_REMOVE):
        tag.decompose()

    # Layer 2: Known noise selectors — global safety net
    for sel in KNOWN_NOISE_SELECTORS:
        try:
            for el in _iter_selector(soup, sel):
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
                if _is_protected(el, protected):
                    logger.debug("[HtmlFilter] Skipped protected element: %s", sel)
                    continue
                el.decompose()
        except Exception as e:
            logger.debug("[HtmlFilter] Selector error %r: %s", sel, e)

    return soup


def _is_protected(el: Tag, protected: list[Tag]) -> bool:
    """True nếu el là ancestor hoặc chính là một protected element."""
    for p in protected:
        if el == p:
            return True
        try:
            if el in p.parents:
                return True
        except Exception:
            pass
    return False