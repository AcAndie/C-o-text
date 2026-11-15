"""Trích xuất tiêu đề chương theo thứ tự ưu tiên first-wins."""
from __future__ import annotations

import logging
import re
import unicodedata
from typing import Any
from urllib.parse import unquote, urlparse

from bs4 import BeautifulSoup

from cao_text.models import SiteProfile

logger = logging.getLogger(__name__)

_MIN_TITLE_LEN: int = 3
_MAX_TITLE_LEN: int = 200

# Thẻ chứa danh sách nhiều mục - không được lấy làm tiêu đề chương
_FORBIDDEN_TITLE_TAGS: frozenset[str] = frozenset({
    "select",
    "option",
    "nav",
    "ul",
    "ol",
    "table",
    "tbody",
})

# Từ khóa trong class/id của tổ tiên cần loại bỏ (tránh nhặt tiêu đề bình luận, gợi ý...)
_TITLE_EXCLUDE_ANCESTOR_KEYWORDS: frozenset[str] = frozenset({
    "comment",
    "comments",
    "review",
    "reviews",
    "rating",
    "ratings",
    "sidebar",
    "footer",
    "related",
    "recommendation",
    "recommendations",
    "discussion",
    "feedback",
    "social",
    "share",
    "ads",
    "advert",
})

# Ký tự phân cách site suffix trong <title> và og:title (giữ nguyên logic code cũ v1: chỉ strip khi có | hoặc dash dài)
_TITLE_TAG_SEP_RE = re.compile(r"[\|–—]")

# Mẫu hậu tố tên website phổ biến
_SITE_SUFFIX_RE = re.compile(
    r"\s*[\|–—\-]\s*(?:"
    r"royal\s*road"
    r"|scribble\s*hub"
    r"|wattpad"
    r"|fanfiction(?:\.net)?"
    r"|archiveofourown(?:\.org)?"
    r"|ao3"
    r"|webnovel"
    r"|novelfire"
    r"|novelupdates"
    r"|lightnovelreader"
    r"|novelfull"
    r"|wuxiaworld"
    r"|readlightnovel"
    r"|fandom(?:\.com)?"
    r"|[a-z0-9\-]+\.(?:com|net|org|io)"
    r")\s*$",
    re.IGNORECASE,
)

_FANFIC_DESCRIPTOR_RE = re.compile(
    r",\s*a\s+.{3,80}?\s+fanfic(?:tion)?\s*$",
    re.IGNORECASE,
)

_WORD_COUNT_ARTIFACT_RE = re.compile(
    r"\s*\[\s*[\d,.\s]*\.?\s*words?\s*\]\s*$",
    re.IGNORECASE,
)

_TRAILING_DASH_RE = re.compile(r"[\-–—]+\s*$")
_SLUG_CLEAN_RE = re.compile(r"[-_]+")
_SLUG_CHAPTER_RE = re.compile(
    r"(?:chapter|chap|ch|episode|ep|part)[_-]?\d+",
    re.IGNORECASE,
)


def clean_title_trailing_dash(text: str) -> str:
    """Xóa các dấu gạch nối và khoảng trắng dư ở cuối tiêu đề."""
    return _TRAILING_DASH_RE.sub("", text).strip()


def normalize_title(text: str) -> str:
    """Chuẩn hóa ký tự điều khiển, khoảng trắng và gạch ngang ở cuối tiêu đề."""
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", text)
    text = re.sub(r"[\x00-\x1f\x7f]", "", text)
    text = re.sub(r"[ \t]+", " ", text).strip()
    return clean_title_trailing_dash(text)


def strip_site_suffix(text: str) -> str:
    """Xóa tên trang, mô tả fanfic và số lượng chữ dính vào tiêu đề."""
    text = _SITE_SUFFIX_RE.sub("", text).strip()
    text = _FANFIC_DESCRIPTOR_RE.sub("", text).strip()
    text = _WORD_COUNT_ARTIFACT_RE.sub("", text).strip()
    return text


def _has_excluded_ancestor(el: Any) -> bool:
    """Kiểm tra tổ tiên có chứa class hoặc id biểu thị vùng bình luận/sidebar hay không."""
    cur = el
    depth = 0
    while cur is not None and depth < 10:
        depth += 1
        if not hasattr(cur, "get"):
            cur = getattr(cur, "parent", None)
            continue
        classes = cur.get("class") or []
        id_val = (cur.get("id") or "").lower()
        for c in classes:
            cl = str(c).lower()
            if any(kw in cl for kw in _TITLE_EXCLUDE_ANCESTOR_KEYWORDS):
                return True
        if any(kw in id_val for kw in _TITLE_EXCLUDE_ANCESTOR_KEYWORDS):
            return True
        cur = getattr(cur, "parent", None)
    return False


def title_from_url(url: str) -> str | None:
    """Bóc tách gợi ý tiêu đề từ URL slug khi không có nguồn DOM nào khác."""
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return None
        path = parsed.path
        segments = [s for s in path.strip("/").split("/") if s]
        if not segments:
            return None

        slug = None
        for seg in reversed(segments):
            if not seg.isdigit() and len(seg) > 3:
                slug = seg
                break
        if not slug:
            return None

        slug = unquote(slug)
        slug = _SLUG_CHAPTER_RE.sub("", slug).strip("-_ ")
        words = _SLUG_CLEAN_RE.sub(" ", slug).strip()
        if not words or len(words) < _MIN_TITLE_LEN:
            return None
        return words.title()
    except Exception:
        return None


def extract_title(
    soup: BeautifulSoup,
    url: str,
    profile: SiteProfile | dict[str, Any] | None = None,
) -> tuple[str | None, str]:
    """Trích xuất tiêu đề chương theo chiến lược first-wins có thứ tự ưu tiên:

    1. Selector từ profile (độ tin cậy 0.95).
    2. Thẻ <h1> / <h2> không thuộc comment/sidebar (độ tin cậy 0.80).
    3. Thẻ <title> (độ tin cậy 0.65).
    4. Thẻ <meta property="og:title"> (độ tin cậy 0.65).
    5. URL slug (độ tin cậy 0.40).

    Trả về: (title, method_used)
    """
    if soup is None:
        fallback = title_from_url(url)
        return (normalize_title(fallback), "url_slug") if fallback else (None, "none")

    title_selector: str | None = None
    if profile is not None:
        if hasattr(profile, "title_selector"):
            title_selector = profile.title_selector
        elif isinstance(profile, dict):
            title_selector = profile.get("title_selector")

    # 1. Selector từ Profile
    if title_selector:
        try:
            el = soup.select_one(title_selector)
            if el is not None:
                tag_name = (getattr(el, "name", "") or "").lower()
                if tag_name not in _FORBIDDEN_TITLE_TAGS:
                    raw = strip_site_suffix(el.get_text(strip=True))
                    text = normalize_title(raw)
                    if _MIN_TITLE_LEN <= len(text) <= _MAX_TITLE_LEN:
                        return text, f"selector:{title_selector}"
        except Exception as e:
            logger.debug("[Title] selector %r failed: %s", title_selector, e)

    # 2. Thẻ h1 / h2
    for tag in ("h1", "h2"):
        for el in soup.find_all(tag):
            if _has_excluded_ancestor(el):
                continue
            raw = strip_site_suffix(el.get_text(strip=True))
            text = normalize_title(raw)
            if _MIN_TITLE_LEN <= len(text) <= _MAX_TITLE_LEN:
                return text, tag

    # 3. Thẻ <title>
    title_tag = soup.find("title")
    if title_tag:
        raw = title_tag.get_text(strip=True)
        if _TITLE_TAG_SEP_RE.search(raw):
            raw = strip_site_suffix(raw)
        text = normalize_title(raw)
        if _MIN_TITLE_LEN <= len(text) <= _MAX_TITLE_LEN:
            return text, "title_tag"

    # 4. Thẻ meta og:title
    og = soup.find("meta", property="og:title")
    if og and og.get("content"):
        raw = str(og["content"]).strip()
        if _TITLE_TAG_SEP_RE.search(raw):
            raw = strip_site_suffix(raw)
        text = normalize_title(raw)
        if _MIN_TITLE_LEN <= len(text) <= _MAX_TITLE_LEN:
            return text, "og"

    # 5. URL Slug fallback
    slug_title = title_from_url(url)
    if slug_title and len(slug_title) >= _MIN_TITLE_LEN:
        return normalize_title(slug_title), "url_slug"

    return None, "none"
