"""
core/extractors.py — Trích xuất tiêu đề chương và tên truyện.

Hai thứ công khai:
  TitleExtractor        — trích tiêu đề một chương (từ HTML)
  extract_story_title() — trích tên truyện (từ breadcrumb / <title>)
"""
import re
from collections import Counter
from urllib.parse import urlparse, unquote

from bs4 import BeautifulSoup

from utils.string_helpers import normalize_title

_MIN_TITLE_LEN = 3

# Xóa phần ", a <fandom>" của fanfiction.net
_RE_FANDOM_TAG = re.compile(r",\s*a\s+.+$")
# Xóa suffix "Chapter N" ở cuối title
_RE_CHAP_SUFFIX = re.compile(r"\s+chapter\s+\d+.*$", re.IGNORECASE)


# ── TitleExtractor ────────────────────────────────────────────────────────────

class TitleExtractor:
    """
    Trích xuất tiêu đề chương từ HTML bằng đa-nguồn + voting.

    Không cần state → có thể dùng như singleton (khởi tạo 1 lần).
    Tham số ai_limiter đã được XÓA (từng dùng ai_validate_title,
    hiện không cần thiết vì tie-breaking dựa vào độ dài).
    """

    async def extract(self, html: str, url: str) -> str:
        soup       = BeautifulSoup(html, "html.parser")
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

        # Deduplicate case-insensitive, giữ lần xuất hiện đầu tiên
        lower_map: dict[str, str] = {}
        for t in cleaned:
            key = t.lower()
            if key not in lower_map:
                lower_map[key] = t

        counts = Counter(t.lower() for t in cleaned)
        top2   = counts.most_common(2)

        # Khi hòa → chọn title dài nhất (thường đầy đủ hơn)
        if len(top2) > 1 and top2[0][1] == top2[1][1]:
            tied = [lower_map[t[0]] for t in top2]
            return max(tied, key=len)

        return lower_map[top2[0][0]]

    def _collect_candidates(self, soup: BeautifulSoup, url: str) -> list[str]:
        result: list[str] = []

        for tag_name, attr in [
            ("title",  None),
            ("meta",   "og:title"),
            ("h1",     None),
            ("h2",     None),
        ]:
            if attr:
                el = soup.find(tag_name, property=attr)
                if el and el.get("content"):
                    result.append(el["content"].strip())
            else:
                el = soup.find(tag_name)
                if el:
                    result.append(el.get_text(strip=True))

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
    Trích tên truyện (không phải tiêu đề chương) từ HTML.

    Nguồn theo thứ tự ưu tiên:
      1. Breadcrumb — phần tử áp chót thường là tên truyện
      2. <title> dạng "Story Name Chapter N | SiteName"
         → lấy phần trước |, xóa fandom tag và chapter suffix

    Trả về None nếu không tìm được.
    """
    # 1. Breadcrumb
    for bc in soup.find_all(attrs={"class": re.compile(r"breadcrumb", re.I)}):
        items = bc.find_all(["a", "span", "li"])
        if len(items) >= 2:
            candidate = items[-2].get_text(strip=True)
            if len(candidate) > 3:
                return normalize_title(candidate)

    # 2. <title> tag
    title_tag = soup.find("title")
    if title_tag:
        raw = title_tag.get_text(strip=True)
        if "|" in raw:
            before_pipe = raw.split("|")[0].strip()
            before_pipe = _RE_FANDOM_TAG.sub("",   before_pipe).strip()
            before_pipe = _RE_CHAP_SUFFIX.sub("",  before_pipe).strip()
            if len(before_pipe) > 3:
                return normalize_title(before_pipe)

    return None