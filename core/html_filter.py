"""
core/html_filter.py — HTML pre-processing trước khi pipeline extract.

Public API:
    prepare_soup(html, remove_selectors, content_selector, title_selector)
        → BeautifulSoup

Logic:
    1. Parse HTML
    2. Xóa _ALWAYS_REMOVE tags (script, style, ...)
    3. Xóa KNOWN_NOISE_SELECTORS (global safety net — TRƯỚC profile selectors)
    4. Xóa profile remove_selectors (learned per-domain)
       (KHÔNG xóa nếu là ancestor của content hoặc title selector)
    5. Trả về soup đã filtered

KNOWN_NOISE_SELECTORS vs remove_selectors:
    KNOWN_NOISE_SELECTORS : site-agnostic, hardcoded, luôn áp dụng
    remove_selectors      : learned per-domain, từ AI/profile
    Hai lớp bổ sung cho nhau — profile có thể miss noise,
    global list catch những trường hợp phổ biến.
"""
from __future__ import annotations

import logging

from bs4 import BeautifulSoup, Tag

from config import KNOWN_NOISE_SELECTORS

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
    Parse HTML và apply 3-layer filtering.

    Safety: không xóa element nào là ancestor của content hay title selector.
    Layer này chỉ apply cho remove_selectors (learned), không cho KNOWN_NOISE
    (global list không bao giờ overlap với content selectors đúng).
    """
    soup = BeautifulSoup(html, "html.parser")

    # Layer 1: Luôn xóa noise tags
    for tag in soup.find_all(_ALWAYS_REMOVE):
        tag.decompose()

    # Layer 2: Known noise selectors — global safety net
    # Áp dụng TRƯỚC profile selectors để tránh pollution ảnh hưởng content detect
    for sel in KNOWN_NOISE_SELECTORS:
        try:
            for el in soup.select(sel):
                el.decompose()
        except Exception as e:
            logger.debug("[HtmlFilter] KNOWN_NOISE selector error %r: %s", sel, e)

    # Layer 3: Profile-specific remove selectors
    if not remove_selectors:
        return soup

    # Xác định các "protected" elements (content và title containers)
    protected: list[Tag] = []
    for sel in (content_selector, title_selector):
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
        if el == p:
            return True
        try:
            if el in p.parents:
                return True
        except Exception:
            pass
    return False