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

# OBFUSCATED-CLASS (v1.0.3): sites like RoyalRoad inject anti-piracy watermarks
# inside <span class="cjBiZWI1ZTRlZTQzODQ0ODRhMjEzNmE0MjdjNzY0MTY4"> — random
# alphanumeric class names that rotate per-render (can't be hardcoded).
#
# Strategy: strip any element whose ONLY class is 40+ pure alphanumeric chars.
# This signature is statistically incompatible with framework classes:
#   - Bootstrap: short readable names (col-md-3, container)
#   - Tailwind: short utility names (pt-4, text-center)
#   - CSS-in-JS build hashes: typically 6-12 chars (sc-jSdvCN, css-1q2x3y)
#   - Module bundler scopes: usually <20 chars
# 40+ chars is the threshold where signal becomes anti-piracy obfuscation.
#
# Conservative: requires SOLE class match (not class list). Real prose elements
# never have a single 40+ char alphanumeric class — almost certainly noise.
_OBFUSCATED_CLASS_RE = re.compile(r"^[A-Za-z0-9]{40,}$")


def _is_alive(el) -> bool:
    """
    True nếu element vẫn trong DOM (chưa decomposed).
    Fix v1.0.9: BS4 decompose() clear attrs → descendant Tag trong find_all
    snapshot crash khi gọi .get(...). Skip decomposed elements.
    """
    if el is None:
        return False
    if getattr(el, "attrs", None) is None:
        return False
    # Soup root has parent=None but name=[document] — allow it.
    if el.parent is None and getattr(el, "name", None) != "[document]":
        return False
    return True


def _strip_obfuscated_class_elements(soup: BeautifulSoup) -> int:
    """
    Strip elements whose only class matches OBFUSCATED-CLASS pattern.
    Returns count of stripped elements. Logs each strip at debug level.

    Fix v1.0.9: snapshot via list() + _is_alive() guard. Decompose ancestor
    cascade nullifies descendant attrs → unguarded .get() crash with
    'NoneType object has no attribute get' → entire html_filter fallback
    to raw parse → watermarks leak.
    """
    stripped = 0
    for el in list(soup.find_all(True)):
        if not _is_alive(el):
            continue
        classes = el.get("class") or []
        # Require SOLE class match — strict rule to avoid FP on legit
        # framework class lists that happen to include one long hash.
        if not (len(classes) == 1 and _OBFUSCATED_CLASS_RE.match(classes[0])):
            continue

        # v1.0.21: RR escalated anti-piracy — wraps EVERY <p> in obfuscated
        # class to defeat scrapers. Original rule nuked real prose.
        # Safe-guard: never strip <p> (paragraphs are prose by nature in
        # chapter pages — watermarks insert as span/div siblings/wrappers).
        if el.name == "p":
            continue
        # Also skip if element holds substantial prose (>40 chars). Real
        # watermarks are short ("Read on X.com", "Stolen from Y" — typically
        # <30c). Cross-chapter AdsFilter handles long-form watermark via
        # frequency learning.
        if len(el.get_text(strip=True)) > 40:
            continue

        logger.debug(
            "[HtmlFilter] Stripped obfuscated-class element: <%s class=%r> text=%r",
            el.name, classes[0], el.get_text(strip=True)[:60],
        )
        el.decompose()
        stripped += 1
    return stripped


# VISIBILITY-FILTER (v1.0.4): strip elements hidden from normal users via
# inline style, HTML5 attributes, or well-known semantic class names. Targets
# anti-piracy watermarks that escape OBFUSCATED-CLASS detection by using
# different hiding techniques (display:none, aria-hidden, off-screen position,
# sr-only screen-reader text, etc).
#
# Philosophy: "only scrape what visible to normal users". Hidden = noise.
# Anything wrapped in display:none, visibility:hidden, opacity:0, off-screen
# position, or sr-only convention is by-definition not part of user-visible
# story content.
#
# Limitation: only catches INLINE style + HTML attr + well-known classes.
# CSS-rule-defined `.foo { display:none }` requires browser computed style →
# needs Playwright. Out of scope for HTML-only filter. Cross-chapter learning
# (AdsFilter) is the fallback for rule-based hidden content.
#
# Conservative class match: exact class name, lowercased. Won't strip
# .hidden-menu or .my-hide-button (partial matches).

_HIDDEN_STYLE_RE = re.compile(
    r"\b("
    # display / visibility / opacity
    r"display\s*:\s*none"
    r"|visibility\s*:\s*hidden"
    r"|opacity\s*:\s*0(?:\.0+)?(?=\s*[;\"']|\s*$)"
    # size zero (text invisible)
    r"|font-size\s*:\s*0(?:px|pt|em|rem)?(?=\s*[;\"']|\s*$)"
    # off-screen position (left/right/top/bottom negative 4+ digits)
    r"|(?:left|right|top|bottom)\s*:\s*-9{3,}"
    # clip to nothing
    r"|clip\s*:\s*rect\s*\(\s*0(?:\s*,?\s*0){3}\s*\)"
    # transform scale 0
    r"|transform\s*:\s*scale\s*\(\s*0\s*\)"
    r")",
    re.IGNORECASE,
)

_HIDDEN_CLASSES = frozenset({
    # Bootstrap / Foundation accessibility
    "sr-only", "sr-only-focusable",
    "visually-hidden", "visually-hidden-focusable",
    "screen-reader-only", "screenreader-only", "screenreader-text",
    "screen-reader-text",
    # Bootstrap display utilities
    "d-none",
    # Tailwind
    "hidden", "invisible",
    # Common generic
    "hide", "is-hidden", "u-hidden", "js-hidden",
    "hidden-text", "hide-text",
    "off-screen", "offscreen",
    "no-display", "nodisplay",
    "aria-hidden",
})


def _strip_invisible_elements(soup: BeautifulSoup) -> int:
    """
    Strip elements not visible to normal users. Covers 4 hiding techniques:
      1. `hidden` HTML5 boolean attribute
      2. `aria-hidden="true"` attribute (intent: not for screen readers)
      3. Inline style: display:none, visibility:hidden, opacity:0,
         font-size:0, off-screen position, clip:rect(0,0,0,0), scale(0)
      4. Semantic class name: sr-only, visually-hidden, d-none, hidden,
         invisible, etc.

    Returns total stripped count. Cumulative across all 4 checks (one
    element may match multiple).
    """
    stripped = 0
    # Snapshot list — decompose during iteration is safe with list() copy
    for el in list(soup.find_all(True)):
        # Fix v1.0.9: tighten guard — also check attrs not None (was insufficient
        # — `el.parent is None` skip missed cases where parent still linked but
        # attrs cleared via cascade).
        if not _is_alive(el):
            continue

        # Check 1: HTML5 [hidden] attribute (boolean — presence = true)
        if el.has_attr("hidden"):
            logger.debug("[HtmlFilter] Stripped [hidden]: <%s>", el.name)
            el.decompose()
            stripped += 1
            continue

        # Check 2: [aria-hidden="true"]
        if (el.get("aria-hidden") or "").lower() == "true":
            logger.debug("[HtmlFilter] Stripped aria-hidden: <%s>", el.name)
            el.decompose()
            stripped += 1
            continue

        # Check 3: inline style invisible
        style_attr = el.get("style") or ""
        if style_attr and _HIDDEN_STYLE_RE.search(style_attr):
            logger.debug(
                "[HtmlFilter] Stripped hidden inline style: <%s style=%r>",
                el.name, style_attr[:80],
            )
            el.decompose()
            stripped += 1
            continue

        # Check 4: semantic hidden class (lowercased exact match)
        classes = el.get("class") or []
        if any(c.lower() in _HIDDEN_CLASSES for c in classes):
            logger.debug(
                "[HtmlFilter] Stripped hidden class: <%s class=%r>",
                el.name, classes,
            )
            el.decompose()
            stripped += 1
            continue

    return stripped


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

    # Layer 1b: OBFUSCATED-CLASS — strip anti-piracy watermarks wrapped in
    # random alphanumeric class (RR pattern: 40+ char class names rotating
    # per-render). Applied before profile selectors so text never reaches
    # downstream content_cleaner / AdsFilter.
    n_obfuscated = _strip_obfuscated_class_elements(soup)
    if n_obfuscated:
        logger.info("[HtmlFilter] Stripped %d obfuscated-class element(s)", n_obfuscated)

    # Layer 1c: VISIBILITY-FILTER — strip hidden elements (display:none,
    # aria-hidden, off-screen position, sr-only class, etc). Only scrape
    # what normal users see. Catches anti-piracy watermarks that escape
    # OBFUSCATED-CLASS detection via alternate hiding techniques.
    n_invisible = _strip_invisible_elements(soup)
    if n_invisible:
        logger.info("[HtmlFilter] Stripped %d invisible element(s)", n_invisible)

    # Layer 2: Known noise selectors — global safety net.
    # Fix v1.0.9: _is_alive guard skips elements already decomposed by Layer 1b/1c
    # cascade (avoid double-decompose noise + edge crashes).
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
                # Fix v1.0.9: skip already-decomposed (Layer 1b/1c/2 cascade).
                if not _is_alive(el):
                    continue
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