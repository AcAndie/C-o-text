# core/dom_observer.py
"""
core/dom_observer.py — Quan sát cấu trúc DOM của một chương đã cào thành công.

Không gọi AI, không có side-effect, không raise exception ra ngoài.
Được gọi một lần sau mỗi chương thành công trong scrape_one_chapter().

Output (StructuralObservation) được tích lũy qua OBS_REFINE_AFTER chương.
Sau đó ProfileManager tổng hợp thành summary và AI refine profile.

Signals thu thập:
  - Content element: tag, id, classes của element chứa nội dung
  - Title element: tag, id, classes của element chứa tiêu đề chương
  - Nav next element: tag, classes, text của nút/link "Next Chapter"

Design:
  - Mỗi hàm _find_* nhận soup và ghi vào obs dict in-place (fail-safe)
  - Chỉ lưu metadata, KHÔNG lưu text content
  - Giới hạn số classes lưu để tránh JSON bloat
"""
from __future__ import annotations

import re
from bs4 import BeautifulSoup, NavigableString, Tag

from utils.types import StructuralObservation


_MAX_CLASSES      = 5     # Số classes tối đa lưu per element
_TITLE_MAX_RATIO  = 3.0   # Tránh match div quá rộng: len(el_text) <= len(title) * ratio
_TITLE_MATCH_MIN  = 4     # Độ dài tối thiểu của title để tìm element

_RE_NEXT = re.compile(
    r"\b(next|tiếp|sau|next\s*chapter|chương\s*tiếp|chương\s*sau)\b",
    re.IGNORECASE | re.UNICODE,
)

# Không tìm nav inside content — sẽ match nút sai
_NAV_SKIP_SELECTORS = (
    "#chapter-c", "#chr-content", "div.chapter-content",
    "article", "#storytext",
)


def observe_chapter_structure(
    soup: BeautifulSoup,
    url: str,
    chapter_num: int,
    winning_selector: str | None,
    title: str,
    title_source: str | None,
) -> StructuralObservation:
    """
    Phân tích DOM của một chương và trả về StructuralObservation.

    Thiết kế fail-safe: bất kỳ lỗi nội bộ nào đều bị catch riêng,
    caller không bao giờ thấy exception từ hàm này.

    Args:
        soup:              BeautifulSoup đã qua remove_hidden_elements()
        url:               URL chương
        chapter_num:       Số thứ tự chương trong session hiện tại
        winning_selector:  CSS selector đã win khi extract content (hoặc None)
        title:             Tiêu đề đã được normalize (từ TitleExtractor)
        title_source:      Nguồn tiêu đề (TitleExtractor.last_source)

    Returns:
        StructuralObservation với tất cả signals tìm được.
        Fields không tìm thấy = None hoặc empty list.
    """
    obs: StructuralObservation = {
        "url":                  url,
        "chapter_num":          chapter_num,
        "content_selector_hit": winning_selector,
        "title_source":         title_source,
        "content_classes":      [],
        "title_classes":        [],
        "nav_next_classes":     [],
    }

    # ── Content element ───────────────────────────────────────────────────────
    if winning_selector:
        _find_content_element(soup, winning_selector, obs)

    # ── Title element ─────────────────────────────────────────────────────────
    if title and title != "Không rõ tiêu đề" and len(title) >= _TITLE_MATCH_MIN:
        _find_title_element(soup, title, obs)

    # ── Nav next element ──────────────────────────────────────────────────────
    _find_nav_next(soup, obs)

    return obs


# ── Private finders ───────────────────────────────────────────────────────────

def _find_content_element(
    soup: BeautifulSoup,
    selector: str,
    obs: StructuralObservation,
) -> None:
    """Tìm content element bằng winning_selector và ghi metadata vào obs."""
    try:
        el = soup.select_one(selector)
        if el and isinstance(el, Tag):
            obs["content_tag"]     = el.name
            obs["content_id"]      = el.get("id") or None
            obs["content_classes"] = _get_classes(el)
    except Exception:
        pass


def _find_title_element(
    soup: BeautifulSoup,
    title: str,
    obs: StructuralObservation,
) -> None:
    """
    Tìm element DOM khớp với title text và ghi tag/id/classes vào obs.

    Logic: duyệt các tag theo độ ưu tiên (heading → span → div).
    Match nếu: title.lower() in el_text.lower() VÀ el_text không quá dài.
    """
    try:
        title_lower = title.lower().strip()
        title_len   = len(title_lower)

        for tag_name in ("h1", "h2", "h3", "h4", "span", "div"):
            for el in soup.find_all(tag_name):
                if not isinstance(el, Tag):
                    continue
                # Lấy text trực tiếp, không recurse deep — tránh match wrapper div
                direct_text = _direct_text(el)
                if not direct_text:
                    continue
                el_lower = direct_text.lower()
                el_len   = len(el_lower)

                # Match nếu title nằm trong el_text (hoặc ngược lại)
                match = title_lower in el_lower or el_lower in title_lower
                if not match:
                    continue
                # Tránh match element quá rộng (chứa cả đoạn văn)
                if el_len > title_len * _TITLE_MAX_RATIO:
                    continue

                obs["title_tag"]     = el.name
                obs["title_id"]      = el.get("id") or None
                obs["title_classes"] = _get_classes(el)
                return   # Lấy match đầu tiên (ưu tiên cao nhất)
    except Exception:
        pass


def _find_nav_next(soup: BeautifulSoup, obs: StructuralObservation) -> None:
    """
    Tìm nút/link "Next Chapter" và ghi metadata vào obs.

    Bỏ qua các anchor nằm bên trong content div (có thể là internal link).
    Ưu tiên: anchor text match → rel="next" fallback.
    """
    try:
        # Lấy set các element bên trong content div để skip
        content_skip: set[Tag] = set()
        for sel in _NAV_SKIP_SELECTORS:
            try:
                el = soup.select_one(sel)
                if el:
                    content_skip.update(el.find_all("a"))
            except Exception:
                pass

        # Tìm qua anchor text
        for a in soup.find_all("a", href=True):
            if a in content_skip:
                continue
            if not isinstance(a, Tag):
                continue
            text = a.get_text(strip=True)
            if _RE_NEXT.search(text):
                obs["nav_next_tag"]     = a.name
                obs["nav_next_classes"] = _get_classes(a)
                obs["nav_next_text"]    = text[:40]
                obs["nav_next_rel"]     = _get_rel(a)
                return

        # Fallback: rel="next"
        rel_next = soup.find("a", rel="next") or soup.find("link", rel="next")
        if rel_next and isinstance(rel_next, Tag):
            obs["nav_next_tag"]     = rel_next.name
            obs["nav_next_classes"] = _get_classes(rel_next)
            obs["nav_next_text"]    = rel_next.get_text(strip=True)[:40]
            obs["nav_next_rel"]     = "next"

    except Exception:
        pass


# ── Utilities ─────────────────────────────────────────────────────────────────

def _get_classes(el: Tag, limit: int = _MAX_CLASSES) -> list[str]:
    """Lấy danh sách classes của element, giới hạn số lượng."""
    classes = el.get("class") or []
    return [str(c) for c in classes[:limit]]


def _get_rel(el: Tag) -> str | None:
    """Lấy giá trị rel attribute an toàn."""
    rel = el.get("rel")
    if isinstance(rel, list):
        return rel[0] if rel else None
    return str(rel) if rel else None


def _direct_text(el: Tag) -> str:
    """
    Lấy text trực tiếp của element (không recurse sâu vào child elements).

    Chỉ lấy NavigableString trực tiếp + text của inline children (span, em, strong, a).
    Bỏ qua block children (div, p, ...) để tránh match element quá rộng.
    """
    _INLINE = frozenset({"span", "em", "strong", "a", "b", "i", "u", "small"})
    parts: list[str] = []
    for child in el.children:
        if isinstance(child, NavigableString):
            parts.append(str(child))
        elif isinstance(child, Tag) and child.name in _INLINE:
            parts.append(child.get_text())
    return " ".join(parts).strip()