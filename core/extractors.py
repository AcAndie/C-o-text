# core/extractors.py
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

# ── Strip "StoryNameChapter 1" (attached, no separator) ──────────────────────
_RE_CHAP_NO_SEPARATOR = re.compile(
    r'(?<=[a-zA-Z])(Chapter\s+\d+.+)$',
    re.IGNORECASE,
)

# ── Strip "Story Title! Chapter 3, a percy jackson fanfic" ───────────────────
# Tách: bất kỳ non-word nào (! ? . ,) + space → Chapter N...
_RE_CHAP_AFTER_PUNCT = re.compile(
    r'^.+?[^\w\s]\s+(Chapter\s+\d+(?:\s*[-–—:]\s*.+)?)$',
    re.IGNORECASE,
)

# ── Strip ", a X fanfic | FanFiction" suffix ─────────────────────────────────
_RE_FANFIC_SUFFIX = re.compile(
    r',\s*a\s+\S.*?\s+(?:fanfic|fanfiction)\b.*$',
    re.IGNORECASE,
)

# ── Strip leading "N. " from select option text ("3. Chapter 3") ─────────────
_RE_OPTION_NUM_PREFIX = re.compile(r'^\d+\.\s*')


def _strip_story_prefix(raw: str) -> str:
    """
    Xử lý title concat nhiều dạng:
      1. 'StoryNameChapter 1 - Title'       → 'Chapter 1 - Title'  (attached)
      2. 'Story Title! Chapter 3, a X fanfic' → 'Chapter 3'        (punct sep + fanfic suffix)
      3. Không match → trả về nguyên gốc
    """
    # Bước 1: Strip fanfic suffix trước
    cleaned = _RE_FANFIC_SUFFIX.sub("", raw).strip()

    # Bước 2: Attached (no separator) — 'StoryNameChapter 1'
    m = _RE_CHAP_NO_SEPARATOR.search(cleaned)
    if m:
        return m.group(1).strip()

    # Bước 3: Punct separator — 'Story Title! Chapter 3 - Title'
    m = _RE_CHAP_AFTER_PUNCT.match(cleaned)
    if m:
        return m.group(1).strip()

    return cleaned


# ── TitleExtractor ────────────────────────────────────────────────────────────

class TitleExtractor:
    """
    Trích xuất tiêu đề chương từ BeautifulSoup bằng đa-nguồn + voting.

    Nguồn ưu tiên (thứ tự cao → thấp):
      1. Chapter select dropdown  ← MỚI: chính xác nhất cho fanfiction.net
      2. Dedicated chapter-title class
      3. <h1> / <h2>
      4. <title> + <meta og:title>  (sau khi strip story prefix)
      5. URL slug
      6. Content heading (h1/h2/h3 trong content div)
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

        # ── Nguồn 1: Chapter select dropdown ─────────────────────────────────
        # Fanfiction.net: <select name="chapter"><option selected>3. Chapter 3</option>
        # Một số site khác dùng select để chọn chapter hiện tại
        chap_select = soup.find("select", {"name": re.compile(r"chapter", re.I)})
        if chap_select:
            selected_opt = chap_select.find("option", selected=True)
            if selected_opt:
                opt_text = selected_opt.get_text(strip=True)
                # Strip "3. " prefix
                clean = _RE_OPTION_NUM_PREFIX.sub("", opt_text).strip()
                if len(clean) >= _MIN_TITLE_LEN:
                    # Thêm 2 lần để tăng weight trong voting
                    result.append(clean)
                    result.append(clean)

        # ── Nguồn 2: Dedicated chapter-title class ────────────────────────────
        for cls in ("chapter-title", "chap-title", "chapter_title", "entry-title",
                    "chapter-name", "chap-name"):
            el = soup.find(class_=cls)
            if el:
                text = el.get_text(strip=True)
                if len(text) >= _MIN_TITLE_LEN:
                    result.append(text)
                    result.append(text)  # weight cao
                break

        # ── Nguồn 3: <h1>, <h2> ──────────────────────────────────────────────
        for tag_name in ("h1", "h2"):
            el = soup.find(tag_name)
            if el:
                raw = el.get_text(strip=True)
                result.append(raw)

        # ── Nguồn 4: <title> và <meta og:title> ──────────────────────────────
        for tag_name, attr in [("title", None), ("meta", "og:title")]:
            if attr:
                el = soup.find(tag_name, property=attr)
                if el and el.get("content"):
                    raw = el["content"].strip()
                    result.append(_strip_story_prefix(raw))
            else:
                el = soup.find(tag_name)
                if el:
                    raw = el.get_text(strip=True)
                    result.append(_strip_story_prefix(raw))

        # ── Nguồn 5: itemprop="name" ──────────────────────────────────────────
        prop = soup.find(attrs={"itemprop": "name"})
        if prop:
            result.append(prop.get_text(strip=True))

        # ── Nguồn 6: URL slug ─────────────────────────────────────────────────
        slug = self._from_url_slug(url)
        if slug:
            result.append(slug)

        # ── Nguồn 7: Heading trong content div ───────────────────────────────
        for sel in ("#chapter-c", "#chr-content", "div.chapter-content",
                    "#storytext", "article"):
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
        """
        Trích tiêu đề từ URL slug.
        Fanfiction.net: /s/14427661/3/Monster-No-Im-A-Cultivator → "Chapter 3"
        Các site khác:  /chapter-5-the-battle → "Chapter 5 The Battle"
        """
        try:
            parsed = urlparse(url)
            path   = parsed.path.rstrip("/")
            parts  = [p for p in path.split("/") if p]

            # Fanfiction.net pattern: /s/{story_id}/{chapter_num}/{slug}
            # parts = ['s', '14427661', '3', 'Monster-No-...']
            if len(parts) >= 3 and parts[0] == "s" and parts[1].isdigit():
                chap_num = parts[2]
                if chap_num.isdigit():
                    return f"Chapter {chap_num}"

            slug  = parts[-1] if parts else ""
            slug  = unquote(slug)
            if slug.isdigit():
                return None

            # Nếu slug là chapter number dạng "chapter-5-title"
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