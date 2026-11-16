"""Điều hướng chương tiếp theo và phân loại loại trang (gộp core + pipeline navigator)."""
from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from cao_text.models import SiteProfile

logger = logging.getLogger(__name__)

# Regex nhận diện nút next (đa ngôn ngữ EN, VN, ES, ZH, JA, KO)
RE_NEXT_BTN = re.compile(
    r"\b(next|tiếp|sau|next\s*chapter|chương\s*tiếp|siguiente)\b"
    r"|下一[章页節话話节回]"
    r"|下章|下页|下節|下一篇"
    r"|次[へのページ章話]"
    r"|次のページ|つぎへ|つぎのページ"
    r"|다음[\s ]*(?:화|장|편|페이지)?",
    re.IGNORECASE | re.UNICODE,
)

# Regex nhận diện slug chương có số ở cuối URL
RE_CHAP_SLUG = re.compile(
    r"(.*?(?:chapter|chuong|chap|/c|/ep|episode|part|phan|tap)[s_-]?)(\d+)(/?(?:[?#].*)?)$",
    re.IGNORECASE,
)

# Regex nhận diện URL FanFiction.net
RE_FANFIC = re.compile(r"(/s/\d+/)(\d+)(/.+)?$")

# Regex nhận diện URL chương thông dụng
RE_CHAP_URL = re.compile(
    r"(?:chapter|chuong|chap|ch)[_\-/]?\d+"
    r"|/ch?[/_-]\d+"
    r"|(?:episode|ep|part)[_\-/]?\d+"
    r"|/s/\d+/\d+"
    r"|/txt/\d+/\d+",
    re.IGNORECASE,
)

# Regex từ khóa chương
RE_CHAP_KW = re.compile(
    r"\b(chapter|chap|chương|episode|ep|part)\b[\s.\-:]*\d+",
    re.IGNORECASE | re.UNICODE,
)

# Regex nhận diện đường dẫn trang mục lục / index
_INDEX_PATH_RE = re.compile(
    r"/(chapters|chapter-list|table-of-contents?|toc|contents|index|fiction|novel|works?)"
    r"(?:[/?#]|$)",
    re.IGNORECASE,
)

_INDEX_TITLE_RE = re.compile(
    r"\b(table of contents?|toc|all chapters?|chapter list)\b",
    re.IGNORECASE,
)

_DROPDOWN_SELECTORS = [
    "select#chapterList",
    "select.chapter-select",
    "select[name='chapter']",
    "select.selectpicker",
    "select#chapter",
    "select.chapter-dropdown",
    "select",
]


def detect_page_type(soup: BeautifulSoup, url: str) -> str:
    """Phân loại trang: "chapter", "index" hoặc "other".

    Quy tắc thứ tự (§6.2):
      1. Kiểm tra RE_CHAP_URL trước (URL chương RoyalRoad có cả /fiction/ và /chapter/ -> phải là chapter).
      2. Kiểm tra đường dẫn index (_INDEX_PATH_RE) hoặc tiêu đề index (_INDEX_TITLE_RE).
      3. Kiểm tra tiêu đề h1/h2 có từ khóa chương.
    """
    if RE_CHAP_URL.search(url):
        return "chapter"

    path = urlparse(url).path
    if _INDEX_PATH_RE.search(path):
        return "index"

    title_tag = soup.find("title")
    if title_tag and _INDEX_TITLE_RE.search(title_tag.get_text(strip=True)):
        return "index"

    for tag in ("h1", "h2"):
        el = soup.find(tag)
        if el and RE_CHAP_KW.search(el.get_text(strip=True)):
            return "chapter"

    return "other"


def find_next_url(
    soup: BeautifulSoup,
    current_url: str,
    profile: SiteProfile | dict[str, Any] | None = None,
    *,
    allow_slug_increment: bool = True,
) -> tuple[str | None, str]:
    """Tìm URL của chương kế tiếp theo các chiến lược xác định:

    1. rel="next" (<link rel="next"> hoặc <a rel="next">).
    2. Selector từ profile (next_selector).
    3. Anchor text (khớp RE_NEXT_BTN).
    4. Slug increment (/chapter-5 -> /chapter-6, chặn nếu URL có numeric ID trước slug như RoyalRoad).
    5. FanFiction.net pattern.
    6. Select dropdown (<select> chapter list).

    Trả về: (next_url, nav_method)
    """
    if soup is None:
        return None, "none"

    next_selector: str | None = None
    nav_type: str | None = None
    if profile is not None:
        if hasattr(profile, "next_selector"):
            next_selector = profile.next_selector
            nav_type = getattr(profile, "nav_type", None)
        elif isinstance(profile, dict):
            next_selector = profile.get("next_selector")
            nav_type = profile.get("nav_type")

    nav_type_lower = (nav_type or "").lower()

    # 1. rel="next"
    el = soup.find("link", rel="next") or soup.find("a", rel="next")
    if el and el.get("href"):
        href = el["href"]
        if href and not href.startswith("#"):
            return urljoin(current_url, href), "rel_next"

    # 2. Selector từ Profile
    if next_selector:
        try:
            sel_el = soup.select_one(next_selector)
            if sel_el is not None:
                href = sel_el.get("href")
                if not href:
                    inner_a = sel_el.find("a", href=True)
                    href = inner_a.get("href") if inner_a else None
                if href and not href.startswith("#"):
                    return urljoin(current_url, href), f"selector:{next_selector}"
        except Exception as e:
            logger.debug("[Nav] selector %r failed: %s", next_selector, e)

    # 3. Anchor text
    for a in soup.find_all("a", href=True):
        text = a.get_text(strip=True)
        if RE_NEXT_BTN.search(text):
            href = a.get("href", "")
            if href and not href.startswith("#"):
                return urljoin(current_url, href), "anchor_text"

    # 4. Slug increment (với guard chặn khi URL có numeric chapter ID dạng /chapter/123/name)
    has_numeric_id_before_slug = bool(re.search(r"/chapters?/\d+/[^/?#]+", current_url, re.IGNORECASE))
    if allow_slug_increment and not has_numeric_id_before_slug:
        m = RE_CHAP_SLUG.search(current_url)
        if m:
            new_url = f"{m.group(1)}{int(m.group(2)) + 1}{m.group(3)}"
            return new_url, "slug_increment"

    # 5. FanFiction.net pattern
    m_ffn = RE_FANFIC.search(current_url)
    if m_ffn:
        new_url = (
            current_url[: m_ffn.start()]
            + m_ffn.group(1)
            + str(int(m_ffn.group(2)) + 1)
            + (m_ffn.group(3) or "")
        )
        return new_url, "fanfic"

    # 6. Select Dropdown (chỉ kích hoạt khi profile chỉ định nav_type dropdown hoặc next_selector là thẻ select)
    is_dropdown_nav = (
        nav_type_lower in ("select_dropdown", "dropdown")
        or bool(next_selector and "select" in next_selector.lower())
    )
    if is_dropdown_nav:
        dropdown_selectors = (
            [next_selector] + [s for s in _DROPDOWN_SELECTORS if s != next_selector]
            if (next_selector and "select" in next_selector.lower())
            else _DROPDOWN_SELECTORS
        )
        for sel in dropdown_selectors:
            try:
                select_el = soup.select_one(sel)
                if select_el is None:
                    continue
                options = select_el.find_all("option")
                if not options:
                    continue

                current_idx: int | None = None
                for idx, opt in enumerate(options):
                    if opt.get("selected") is not None:
                        current_idx = idx
                        break

                if current_idx is None:
                    for idx, opt in enumerate(options):
                        val = opt.get("value", "")
                        if val and val in current_url:
                            current_idx = idx
                            break

                if current_idx is not None and current_idx < len(options) - 1:
                    next_val = options[current_idx + 1].get("value", "").strip()
                    if next_val and not next_val.startswith("#") and "javascript:" not in next_val.lower():
                        return urljoin(current_url, next_val), f"dropdown:{sel}"
            except Exception:
                continue

    return None, "none"
