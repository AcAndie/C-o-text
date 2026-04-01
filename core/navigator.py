# core/navigator.py
"""
core/navigator.py — Phát hiện URL chương tiếp theo và phân loại trang.

CHANGES (v2):
  find_next_url(): Dùng profile["nav_type"] để ưu tiên strategy đúng.
  Nếu nav_type đã biết, bỏ qua các strategy không phù hợp → nhanh hơn,
  ít false-positive hơn.

  nav_type mapping:
    "selector"       → Bước 1 (profile selector) — giữ nguyên
    "rel_next"       → Bước 2 — thử trước, bỏ qua anchor text scan
    "slug_increment" → Bước 5 — thử trước, bỏ qua rel/anchor
    "dropdown"       → Bước 4 — thử trước
    "fanfic"         → Bước 6 — thử trước, bỏ qua các bước khác
    None / unknown   → Thứ tự gốc (thử tất cả)
"""
from __future__ import annotations

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from config import (
    RE_NEXT_BTN,
    RE_CHAP_SLUG,
    RE_CHAP_URL,
    RE_CHAP_HREF,
    RE_CHAP_KW_URL,
)

_RE_FANFIC_CHAPTER = re.compile(r"(/s/\d+/)(\d+)(/.+)?$")


def find_next_url(
    soup: BeautifulSoup,
    current_url: str,
    profile: dict,
) -> str | None:
    """
    Tìm URL chương tiếp theo bằng heuristic (không gọi AI).

    ENHANCED: Đọc profile["nav_type"] để chọn strategy nhanh nhất.
    Nếu nav_type đã biết → thử strategy đó trước, chỉ fallback nếu thất bại.
    Nếu nav_type chưa biết → thử tất cả theo thứ tự gốc.

    Thứ tự mặc định (không có nav_type):
      1. CSS selector từ site profile
      2. <link rel="next"> hoặc <a rel="next">
      3. Anchor text "next / tiếp / sau"
      4. <select> dropdown
      5. Tăng số chương trong URL slug
      6. fanfiction.net pattern
    """
    base     = current_url
    nav_type = profile.get("nav_type")

    # ── Fast path: nav_type đã biết ──────────────────────────────────────────
    if nav_type:
        result = _try_nav_type(soup, base, profile, nav_type)
        if result:
            return result
        # nav_type không work (có thể trang này khác) → fallback toàn bộ

    # ── Standard path: thử tất cả theo thứ tự ────────────────────────────────
    return _try_all_strategies(soup, base, profile)


def _try_nav_type(
    soup: BeautifulSoup,
    base: str,
    profile: dict,
    nav_type: str,
) -> str | None:
    """Thử strategy tương ứng với nav_type."""
    if nav_type == "selector":
        return _try_selector(soup, base, profile)

    if nav_type == "rel_next":
        return _try_rel_next(soup, base)

    if nav_type == "slug_increment":
        return _try_slug_increment(base)

    if nav_type == "dropdown":
        return _try_dropdown(soup, base)

    if nav_type == "fanfic":
        return _try_fanfic(soup, base)

    return None


def _try_all_strategies(
    soup: BeautifulSoup,
    base: str,
    profile: dict,
) -> str | None:
    """Thử toàn bộ strategy theo thứ tự ưu tiên gốc."""
    result = _try_selector(soup, base, profile)
    if result:
        return result

    result = _try_rel_next(soup, base)
    if result:
        return result

    result = _try_anchor_text(soup, base)
    if result:
        return result

    result = _try_dropdown(soup, base)
    if result:
        return result

    result = _try_slug_increment(base)
    if result:
        return result

    return _try_fanfic(soup, base)


# ── Individual strategies ─────────────────────────────────────────────────────

def _try_selector(soup: BeautifulSoup, base: str, profile: dict) -> str | None:
    """Bước 1: CSS selector từ profile."""
    next_sel = profile.get("next_selector")
    if next_sel:
        try:
            el = soup.select_one(next_sel)
            if el and el.get("href"):
                return urljoin(base, el["href"])
        except Exception:
            pass
    return None


def _try_rel_next(soup: BeautifulSoup, base: str) -> str | None:
    """Bước 2: <link rel="next"> hoặc <a rel="next">."""
    rel_next = soup.find("link", rel="next") or soup.find("a", rel="next")
    if rel_next and rel_next.get("href"):
        return urljoin(base, rel_next["href"])
    return None


def _try_anchor_text(soup: BeautifulSoup, base: str) -> str | None:
    """Bước 3: Anchor text chứa 'next / tiếp / sau'."""
    for a in soup.find_all("a", href=True):
        if RE_NEXT_BTN.search(a.get_text(strip=True)):
            return urljoin(base, a["href"])
    return None


def _try_dropdown(soup: BeautifulSoup, base: str) -> str | None:
    """Bước 4: <select> dropdown chương."""
    for sel_tag in soup.find_all("select"):
        options = sel_tag.find_all("option")
        for i, opt in enumerate(options):
            href = opt.get("value", "")
            if href and base.endswith(href.lstrip("/")):
                if i + 1 < len(options):
                    next_val = options[i + 1].get("value", "")
                    if next_val:
                        return urljoin(base, next_val)
    return None


def _try_slug_increment(base: str) -> str | None:
    """Bước 5: Tăng số trong slug URL."""
    m = RE_CHAP_SLUG.search(base)
    if m:
        return f"{m.group(1)}{int(m.group(2)) + 1}{m.group(3)}"
    return None


def _try_fanfic(soup: BeautifulSoup, base: str) -> str | None:
    """Bước 6: fanfiction.net /s/{id}/{num}/ pattern."""
    m = _RE_FANFIC_CHAPTER.search(base)
    if m:
        return (
            base[: m.start()]
            + m.group(1)
            + str(int(m.group(2)) + 1)
            + (m.group(3) or "")
        )
    return None


# ── Page type detection ───────────────────────────────────────────────────────

def detect_page_type(soup: BeautifulSoup, url: str) -> str:
    """
    Phân loại trang: 'chapter' | 'index' | 'other'.
    Score-based: cộng điểm cho từng tín hiệu.
    """
    score: dict[str, int] = {"chapter": 0, "index": 0}

    if RE_CHAP_URL.search(url):
        score["chapter"] += 2

    anchors = soup.find_all("a")

    for a in anchors:
        text = a.get_text(strip=True)
        href = a.get("href", "")
        if RE_NEXT_BTN.search(text):
            score["chapter"] += 1
        if RE_CHAP_HREF.search(href):
            score["index"] += 1

    chap_links = sum(1 for a in anchors if RE_CHAP_KW_URL.search(a.get_text()))
    if chap_links > 5:
        score["index"] += 2
    elif chap_links > 1:
        score["index"] += 1

    if score["chapter"] > score["index"]:
        return "chapter"
    if score["index"] > score["chapter"]:
        return "index"
    return "other"