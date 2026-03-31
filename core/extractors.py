# core/extractors.py
"""
core/extractors.py — Trích xuất tiêu đề chương và tên truyện.

BUG-2 FIX: Thêm _strip_story_prefix() + _RE_CHAP_NO_SEPARATOR.
  Vấn đề: Một số site (novelfire, v.v.) trả <title> dạng:
    "The Primal HunterChapter 1 - Another Monday Morning"
  (tên truyện + tiêu đề chương ghép trực tiếp, KHÔNG có separator).
  normalize_title() không xử lý được vì không có dấu | – —.
  TitleExtractor._collect_candidates() bây giờ tự động strip prefix
  cho <title> tag và <meta og:title> trước khi đưa vào voting pool.

API không đổi:
  TitleExtractor.extract(soup, url, ai_limiter?)
  extract_story_title(soup, url)
"""
from __future__ import annotations

import re
from collections import Counter
from typing import TYPE_CHECKING
from urllib.parse import urlparse, unquote

from bs4 import BeautifulSoup

from utils.string_helpers import normalize_title

if TYPE_CHECKING:
    from ai.client import AIRateLimiter

_MIN_TITLE_LEN = 3

_RE_FANDOM_TAG  = re.compile(r",\s*a\s+.+$")
_RE_CHAP_SUFFIX = re.compile(r"\s+chapter\s+\d+.*$", re.IGNORECASE)

# ── BUG-2 FIX ─────────────────────────────────────────────────────────────────
# Phát hiện "StoryNameChapter N" — "Chapter" gắn trực tiếp vào chữ cái
# mà không có space / dash / em-dash trước nó.
#
# Lookbehind (?<=[a-zA-Z]) khớp khi ký tự TRƯỚC "Chapter" là chữ cái Latin.
# Điều này đảm bảo:
#   "The Primal HunterChapter 1 - ..."  → khớp ("r" trước "C")
#   "Chapter 1 - ..."                   → KHÔNG khớp (đầu chuỗi)
#   "Rock Falls - Chapter 1 - ..."      → KHÔNG khớp (space trước "C")
#   "EpicChapterOneWithoutNumber"       → KHÔNG khớp (không có số sau Chapter)
_RE_CHAP_NO_SEPARATOR = re.compile(
    r'(?<=[a-zA-Z])(Chapter\s+\d+.+)$',
    re.IGNORECASE,
)


def _strip_story_prefix(raw: str) -> str:
    """
    Xử lý title concat không separator: 'StoryNameChapter 1 - Title' → 'Chapter 1 - Title'.

    Chỉ kích hoạt khi 'Chapter N' gắn trực tiếp vào chữ cái (không space/dash trước).
    Nếu không match → trả về nguyên gốc, không thay đổi gì.

    Ví dụ:
      'The Primal HunterChapter 1 - Monday' → 'Chapter 1 - Monday'  ✓
      'Chapter 1 - Monday'                  → 'Chapter 1 - Monday'  ✓ (no-op)
      'Rock Falls - Chapter 2 - ...'        → 'Rock Falls - Chapter 2 - ...' ✓ (no-op)
    """
    m = _RE_CHAP_NO_SEPARATOR.search(raw)
    return m.group(1).strip() if m else raw


# ── TitleExtractor ────────────────────────────────────────────────────────────

class TitleExtractor:
    """
    Trích xuất tiêu đề chương từ BeautifulSoup bằng đa-nguồn + voting.

    BUG-2 FIX: _collect_candidates() áp dụng _strip_story_prefix() cho
               <title> và <meta og:title> trước khi đưa vào voting pool.
               → Tránh title xấu như 'The Primal HunterChapter 1 - ...'
                 thắng vote vì nó dài hơn 'Chapter 1 - ...' sạch từ <h1>.
    """

    async def extract(
        self,
        soup: BeautifulSoup,
        url: str,
        ai_limiter: "AIRateLimiter | None" = None,
    ) -> str:
        candidates = self._collect_candidates(soup, url)

        cleaned: list[str] = []
        for raw in candidates:
            if not raw:
                continue
            t = normalize_title(raw)
            if len(t) >= _MIN_TITLE_LEN:
                cleaned.append(t)

        if not cleaned:
            return self._from_url_slug(url) or "Không rõ tiêu đề"

        lower_map: dict[str, str] = {}
        for t in cleaned:
            key = t.lower()
            if key not in lower_map:
                lower_map[key] = t

        counts = Counter(t.lower() for t in cleaned)
        top2   = counts.most_common(2)

        if len(top2) == 1 or top2[0][1] != top2[1][1]:
            return lower_map[top2[0][0]]

        # ── Vote hòa ──────────────────────────────────────────────────────────
        tied = [lower_map[t[0]] for t in top2]

        if ai_limiter is not None:
            from ai.agents import ai_validate_title
            body_el = soup.find("body")
            snippet = body_el.get_text(separator=" ", strip=True)[:300] if body_el else ""
            primary = min(tied, key=len)
            validated = await ai_validate_title(
                candidate       = primary,
                chapter_url     = url,
                content_snippet = snippet,
                ai_limiter      = ai_limiter,
            )
            if validated:
                return normalize_title(validated)

        return max(tied, key=len)

    def _collect_candidates(self, soup: BeautifulSoup, url: str) -> list[str]:
        result: list[str] = []

        for tag_name, attr in [
            ("title", None),
            ("meta",  "og:title"),
            ("h1",    None),
            ("h2",    None),
        ]:
            if attr:
                el = soup.find(tag_name, property=attr)
                if el and el.get("content"):
                    raw = el["content"].strip()
                    # BUG-2 FIX: og:title cũng có thể bị concat
                    result.append(_strip_story_prefix(raw))
            else:
                el = soup.find(tag_name)
                if el:
                    raw = el.get_text(strip=True)
                    # BUG-2 FIX: <title> tag thường bị concat — strip trước
                    result.append(_strip_story_prefix(raw) if tag_name == "title" else raw)

        prop = soup.find(attrs={"itemprop": "name"})
        if prop:
            result.append(prop.get_text(strip=True))

        for cls in ("chapter-title", "chap-title", "chapter_title", "entry-title"):
            el = soup.find(class_=cls)
            if el:
                result.append(el.get_text(strip=True))
                break

        slug = self._from_url_slug(url)
        if slug:
            result.append(slug)

        for sel in ("#chapter-c", "#chr-content", "div.chapter-content", "article"):
            content_div = soup.select_one(sel)
            if content_div:
                for tag in content_div.find_all(["h1", "h2", "h3", "strong"]):
                    text = tag.get_text(strip=True)
                    if len(text) > _MIN_TITLE_LEN:
                        result.append(text)
                        break
                break

        return result

    def _from_url_slug(self, url: str) -> str | None:
        try:
            path  = urlparse(url).path.rstrip("/")
            slug  = path.split("/")[-1]
            slug  = unquote(slug)
            if slug.isdigit():
                return None
            words = re.split(r"[-_]", slug)
            title = " ".join(w.capitalize() for w in words if w).strip()
            return title or None
        except Exception:
            return None


# ── Story title extraction ────────────────────────────────────────────────────

def extract_story_title(soup: BeautifulSoup, url: str) -> str | None:
    """
    Trích tên truyện (không phải tiêu đề chương) từ BeautifulSoup.
    """
    for bc in soup.find_all(attrs={"class": re.compile(r"breadcrumb", re.I)}):
        items = bc.find_all(["a", "span", "li"])
        if len(items) >= 2:
            candidate = items[-2].get_text(strip=True)
            if len(candidate) > 3:
                return normalize_title(candidate)

    title_tag = soup.find("title")
    if title_tag:
        raw = title_tag.get_text(strip=True)
        if "|" in raw:
            before_pipe = raw.split("|")[0].strip()
            before_pipe = _RE_FANDOM_TAG.sub("",  before_pipe).strip()
            before_pipe = _RE_CHAP_SUFFIX.sub("", before_pipe).strip()
            if len(before_pipe) > 3:
                return normalize_title(before_pipe)

    return None