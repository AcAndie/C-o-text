# core/extractors.py
"""
CHANGES (v3 — source tracking):
  TitleExtractor:
    - _collect_candidates() giờ trả về list[tuple[str, str]] thay vì list[str]
      Tuple = (source_label, candidate_text)
    - extract() tracking source nào win → self.last_source
    - last_source được dùng bởi dom_observer.observe_chapter_structure()
      để ghi vào StructuralObservation["title_source"]

  Source labels chuẩn:
    "dropdown"           — chapter <select> dropdown (fanfiction.net)
    "class:<classname>"  — dedicated chapter-title class element
    "h1" / "h2"          — heading tags
    "title_tag"          — <title> element
    "og:title"           — <meta property="og:title">
    "itemprop:name"      — itemprop="name"
    "url_slug"           — trích từ URL path
    "content_heading"    — h1/h2/h3/strong bên trong content div
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

_RE_CHAP_NO_SEPARATOR = re.compile(
    r'(?<=[a-zA-Z])(Chapter\s+\d+.+)$',
    re.IGNORECASE,
)
_RE_CHAP_AFTER_PUNCT = re.compile(
    r'^.+?[^\w\s]\s+(Chapter\s+\d+(?:\s*[-–—:]\s*.+)?)$',
    re.IGNORECASE,
)
_RE_FANFIC_SUFFIX = re.compile(
    r',\s*a\s+\S.*?\s+(?:fanfic|fanfiction)\b.*$',
    re.IGNORECASE,
)
_RE_OPTION_NUM_PREFIX = re.compile(r'^\d+\.\s*')


def _strip_story_prefix(raw: str) -> str:
    cleaned = _RE_FANFIC_SUFFIX.sub("", raw).strip()
    m = _RE_CHAP_NO_SEPARATOR.search(cleaned)
    if m:
        return m.group(1).strip()
    m = _RE_CHAP_AFTER_PUNCT.match(cleaned)
    if m:
        return m.group(1).strip()
    return cleaned


# ── TitleExtractor ────────────────────────────────────────────────────────────

class TitleExtractor:
    """
    Trích xuất tiêu đề chương từ BeautifulSoup bằng đa-nguồn + voting.

    Thuộc tính công khai sau mỗi lần extract():
      last_source: str | None — source label của candidate đã win.
        Được dom_observer.observe_chapter_structure() đọc để ghi vào
        StructuralObservation["title_source"].

    Nguồn ưu tiên (thứ tự cao → thấp):
      1. Chapter select dropdown  (weight x2)
      2. Dedicated chapter-title class  (weight x2)
      3. <h1> / <h2>
      4. <title> + <meta og:title>  (sau khi strip story prefix)
      5. itemprop="name"
      6. URL slug
      7. Content heading (h1/h2/h3 trong content div)
    """

    def __init__(self) -> None:
        self.last_source: str | None = None

    async def extract(
        self,
        soup: BeautifulSoup,
        url: str,
        ai_limiter: "AIRateLimiter | None" = None,
    ) -> str:
        # _collect_candidates trả về list[(source_label, text)]
        raw_candidates: list[tuple[str, str]] = self._collect_candidates(soup, url)

        cleaned: list[tuple[str, str]] = []
        for source, raw in raw_candidates:
            if not raw:
                continue
            t = normalize_title(raw)
            if len(t) >= _MIN_TITLE_LEN:
                cleaned.append((source, t))

        if not cleaned:
            self.last_source = "url_slug"
            return self._from_url_slug(url) or "Không rõ tiêu đề"

        # lower_text → (first_source, display_text)
        lower_map: dict[str, tuple[str, str]] = {}
        for source, t in cleaned:
            key = t.lower()
            if key not in lower_map:
                lower_map[key] = (source, t)

        counts = Counter(t.lower() for _, t in cleaned)
        top2   = counts.most_common(2)

        if len(top2) == 1 or top2[0][1] != top2[1][1]:
            winner_lower      = top2[0][0]
            winner_source, winner_text = lower_map[winner_lower]
            self.last_source  = winner_source
            return winner_text

        # ── Vote hòa ──────────────────────────────────────────────────────────
        tied_items = [(lower_map[t[0]][0], lower_map[t[0]][1]) for t in top2]

        if ai_limiter is not None:
            from ai.agents import ai_validate_title
            body_el = soup.find("body")
            snippet = body_el.get_text(separator=" ", strip=True)[:300] if body_el else ""
            # Ưu tiên candidate ngắn hơn (thường là title thuần)
            primary_source, primary = min(tied_items, key=lambda x: len(x[1]))
            validated = await ai_validate_title(
                candidate       = primary,
                chapter_url     = url,
                content_snippet = snippet,
                ai_limiter      = ai_limiter,
            )
            if validated:
                self.last_source = f"ai_validated:{primary_source}"
                return normalize_title(validated)

        # Fallback: chọn candidate dài hơn
        winner_source, winner_text = max(tied_items, key=lambda x: len(x[1]))
        self.last_source = winner_source
        return winner_text

    def _collect_candidates(
        self,
        soup: BeautifulSoup,
        url: str,
    ) -> list[tuple[str, str]]:
        """
        Thu thập candidates từ tất cả sources.
        Returns list[tuple[source_label, candidate_text]].
        Một source có thể xuất hiện nhiều lần để tăng weight trong voting.
        """
        result: list[tuple[str, str]] = []

        # ── Nguồn 1: Chapter select dropdown ─────────────────────────────────
        # Fanfiction.net: <select name="chapter"><option selected>3. Chapter 3</option>
        chap_select = soup.find("select", {"name": re.compile(r"chapter", re.I)})
        if chap_select:
            selected_opt = chap_select.find("option", selected=True)
            if selected_opt:
                opt_text = selected_opt.get_text(strip=True)
                clean = _RE_OPTION_NUM_PREFIX.sub("", opt_text).strip()
                if len(clean) >= _MIN_TITLE_LEN:
                    result.append(("dropdown", clean))
                    result.append(("dropdown", clean))   # weight x2

        # ── Nguồn 2: Dedicated chapter-title class ────────────────────────────
        for cls in ("chapter-title", "chap-title", "chapter_title", "entry-title",
                    "chapter-name", "chap-name"):
            el = soup.find(class_=cls)
            if el:
                text = el.get_text(strip=True)
                if len(text) >= _MIN_TITLE_LEN:
                    label = f"class:{cls}"
                    result.append((label, text))
                    result.append((label, text))   # weight x2
                break

        # ── Nguồn 3: <h1>, <h2> ──────────────────────────────────────────────
        for tag_name in ("h1", "h2"):
            el = soup.find(tag_name)
            if el:
                raw = el.get_text(strip=True)
                result.append((tag_name, raw))

        # ── Nguồn 4: <title> và <meta og:title> ──────────────────────────────
        title_tag = soup.find("title")
        if title_tag:
            raw = title_tag.get_text(strip=True)
            result.append(("title_tag", _strip_story_prefix(raw)))

        og_title = soup.find("meta", property="og:title")
        if og_title and og_title.get("content"):
            raw = og_title["content"].strip()
            result.append(("og:title", _strip_story_prefix(raw)))

        # ── Nguồn 5: itemprop="name" ──────────────────────────────────────────
        prop = soup.find(attrs={"itemprop": "name"})
        if prop:
            result.append(("itemprop:name", prop.get_text(strip=True)))

        # ── Nguồn 6: URL slug ─────────────────────────────────────────────────
        slug = self._from_url_slug(url)
        if slug:
            result.append(("url_slug", slug))

        # ── Nguồn 7: Heading trong content div ───────────────────────────────
        for sel in ("#chapter-c", "#chr-content", "div.chapter-content",
                    "#storytext", "article"):
            content_div = soup.select_one(sel)
            if content_div:
                for tag in content_div.find_all(["h1", "h2", "h3", "strong"]):
                    text = tag.get_text(strip=True)
                    if len(text) > _MIN_TITLE_LEN:
                        result.append(("content_heading", text))
                        break
                break

        return result

    def _from_url_slug(self, url: str) -> str | None:
        try:
            parsed = urlparse(url)
            path   = parsed.path.rstrip("/")
            parts  = [p for p in path.split("/") if p]

            # Fanfiction.net: /s/{story_id}/{chapter_num}/{slug}
            if len(parts) >= 3 and parts[0] == "s" and parts[1].isdigit():
                chap_num = parts[2]
                if chap_num.isdigit():
                    return f"Chapter {chap_num}"

            slug  = parts[-1] if parts else ""
            slug  = unquote(slug)
            if slug.isdigit():
                return None

            m = re.match(r'chapter[-_](\d+)([-_].+)?', slug, re.IGNORECASE)
            if m:
                num   = m.group(1)
                title = m.group(2) or ""
                title = re.sub(r'^[-_]', '', title).replace("-", " ").replace("_", " ").strip()
                return f"Chapter {num}" + (f" - {title.title()}" if title else "")

            words = re.split(r"[-_]", slug)
            title = " ".join(w.capitalize() for w in words if w).strip()
            return title or None
        except Exception:
            return None


# ── Story title extraction ────────────────────────────────────────────────────

def extract_story_title(soup: BeautifulSoup, url: str) -> str | None:
    """Trích tên truyện (không phải tiêu đề chương) từ BeautifulSoup."""
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