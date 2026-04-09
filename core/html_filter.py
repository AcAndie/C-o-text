"""
core/html_filter.py — HTML pre-processing trước khi pipeline extract.

Public API:
    prepare_soup(html, remove_selectors, content_selector, title_selector)
        → BeautifulSoup

Logic:
    1. Parse HTML
    2. Xóa các elements trong remove_selectors
       (KHÔNG xóa nếu là ancestor của content hoặc title selector)
    3. Trả về soup đã filtered
"""
from __future__ import annotations

import logging

from bs4 import BeautifulSoup, Tag

logger = logging.getLogger(__name__)

# Tags luôn xóa — không cần selector
_ALWAYS_REMOVE = frozenset({"script", "style", "noscript", "iframe"})


def prepare_soup(
    html             : str,
    remove_selectors : list[str],
    content_selector : str | None = None,
    title_selector   : str | None = None,
) -> BeautifulSoup:
    """
    Parse HTML và apply remove_selectors.

    Safety: không xóa element nào là ancestor của content hay title.
    """
    soup = BeautifulSoup(html, "html.parser")

    # Luôn xóa noise tags
    for tag in soup.find_all(_ALWAYS_REMOVE):
        tag.decompose()

    if not remove_selectors:
        return soup

    # Xác định các "protected" elements
    protected: list[Tag] = []
    for sel in (content_selector, title_selector):
        if sel:
            try:
                el = soup.select_one(sel)
                if el:
                    protected.append(el)
            except Exception:
                pass

    # Apply remove selectors
    for sel in remove_selectors:
        if not sel or not sel.strip():
            continue
        try:
            for el in soup.select(sel):
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
        # p là el, hoặc p là hậu duệ của el (tức el là ancestor của p)
        if el == p:
            return True
        # Check if p is a descendant of el
        try:
            if el in p.parents:
                return True
        except Exception:
            pass
    return False