"""
core/navigator.py — Navigation helpers.

Public API:
    find_next_url(soup, current_url, profile) → str | None
    detect_page_type(soup, url) → "chapter" | "index" | "other"
"""
from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup, Tag

from config import RE_NEXT_BTN, RE_CHAP_HREF, RE_CHAP_SLUG, RE_FANFIC, RE_CHAP_URL

# Patterns cho index/TOC pages
_INDEX_PATH_RE = re.compile(
    r"/(chapters?|table-of-contents?|toc|contents?|index|fiction|novel|works?)"
    r"(?:[/?#]|$)",
    re.IGNORECASE,
)
_INDEX_TITLE_RE = re.compile(
    r"\b(table of contents?|toc|all chapters?|chapter list)\b",
    re.IGNORECASE,
)


def find_next_url(
    soup        : BeautifulSoup,
    current_url : str,
    profile     : dict,
) -> str | None:
    """
    Tìm URL chapter tiếp theo. Thử theo thứ tự ưu tiên:
      1. rel="next" link
      2. CSS selector từ profile (next_selector)
      3. Anchor text regex (Next, Next Chapter, v.v.)
      4. Slug increment (/chapter-5 → /chapter-6)
      5. FanFiction.net pattern
    """
    # 1. rel="next"
    el = soup.find("link", rel="next") or soup.find("a", rel="next")
    if el and el.get("href"):
        return urljoin(current_url, el["href"])

    # 2. Profile selector
    next_sel = profile.get("next_selector")
    if next_sel:
        try:
            el = soup.select_one(next_sel)
            if el:
                href = el.get("href") or (el.find("a", href=True) or {}).get("href")
                if href:
                    return urljoin(current_url, href)
        except Exception:
            pass

    # 3. Anchor text
    for a in soup.find_all("a", href=True):
        if RE_NEXT_BTN.search(a.get_text(strip=True)):
            href = a.get("href", "")
            if href and not href.startswith("#"):
                return urljoin(current_url, href)

    # 4. Slug increment
    m = RE_CHAP_SLUG.search(current_url)
    if m:
        return f"{m.group(1)}{int(m.group(2)) + 1}{m.group(3)}"

    # 5. FanFiction.net
    m = RE_FANFIC.search(current_url)
    if m:
        return current_url[: m.start()] + m.group(1) + str(int(m.group(2)) + 1) + (m.group(3) or "")

    return None


def detect_page_type(soup: BeautifulSoup, url: str) -> str:
    """
    Phân loại trang: "chapter", "index", hoặc "other".

    Heuristic:
      - Index: path khớp /chapters/, /toc, /fiction/ hoặc title tag có "table of contents"
      - Chapter: URL khớp RE_CHAP_URL, hoặc có h1/h2 với chương keyword
      - Other: tất cả còn lại
    """
    path = urlparse(url).path

    # Check index patterns
    if _INDEX_PATH_RE.search(path):
        return "index"

    title_tag = soup.find("title")
    if title_tag and _INDEX_TITLE_RE.search(title_tag.get_text(strip=True)):
        return "index"

    # Check chapter patterns
    if RE_CHAP_URL.search(url):
        return "chapter"

    # Fallback: look for chapter content signals
    for tag in ("h1", "h2"):
        el = soup.find(tag)
        if el:
            from config import RE_CHAP_KW
            if RE_CHAP_KW.search(el.get_text(strip=True)):
                return "chapter"

    return "other"