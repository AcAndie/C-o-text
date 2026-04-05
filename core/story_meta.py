"""
core/story_meta.py — Story metadata helpers.

Extracted từ core/scraper.py để giảm God Object.

Public API:
    extract_story_title()    — lấy tên truyện từ raw <title> page tag
    build_story_id_regex()   — tạo regex để lock story ID (tránh drift sang truyện khác)
    is_chapter_url()         — kiểm tra URL có phải chapter URL không
    story_id_ok()            — kiểm tra URL thuộc đúng story đang cào
"""
from __future__ import annotations

import re
from urllib.parse import urlparse

from config import RE_CHAP_URL
from utils.types import ProgressDict, SiteProfile

# Sites mà tên của chúng không bao giờ là tên truyện
_KNOWN_SITES = frozenset({
    "royalroad", "royal road", "scribblehub", "wattpad", "fanfiction",
    "fanfiction.net", "archiveofourown", "ao3", "webnovel", "novelfire",
    "novelupdates", "lightnovelreader", "novelfull", "wuxiaworld",
})

# Pattern nhận ra chapter title (để loại khi tìm story title)
_CHAPTER_TITLE_RE = re.compile(
    r"^\s*(?:chapter|chap|ch|episode|ep|part|chuong|phan)\b[\s.\-:]*\d*",
    re.IGNORECASE | re.UNICODE,
)


def extract_story_title(raw_page_title: str) -> str | None:
    """
    Lấy tên truyện từ raw <title> tag của trang.

    Heuristic: split theo | – — rồi loại bỏ:
        - Phần quá ngắn (< 3 ký tự)
        - Chapter title patterns ("Chapter 5", "Ep. 3", v.v.)
        - Tên site đã biết ("Royal Road", "FanFiction.net", v.v.)
    Chọn candidate dài nhất còn lại.

    Examples:
        "Chapter 5 – The Rise | Rock Falls | Royal Road"
        → candidates: ["The Rise", "Rock Falls"]
        → "Rock Falls" (dài hơn "The Rise")

        "Monster Cultivator Chapter 10 - WuxiaWorld"
        → candidates: ["Monster Cultivator Chapter 10"]  (site bị loại)
        → "Monster Cultivator Chapter 10"
    """
    parts      = re.split(r"\s*[\|–—]\s*", raw_page_title)
    candidates = []
    for part in parts:
        part = part.strip()
        if len(part) < 3:
            continue
        if _CHAPTER_TITLE_RE.match(part):
            continue
        if part.lower() in _KNOWN_SITES:
            continue
        candidates.append(part)
    return max(candidates, key=len) if candidates else None


def build_story_id_regex(url: str) -> str | None:
    """
    Tạo regex pattern để nhận dạng URL thuộc cùng story.

    Dùng để guard scraper khỏi "drift" sang story khác khi:
        - next_url sai (dẫn đến story khác cùng site)
        - Site redirect về trang khác

    Logic:
        - fanfiction.net: "/s/{story_id}/"
        - Generic: tìm segment số đầu tiên trong path,
                   build prefix path tới đó

    Examples:
        build_story_id_regex("https://fanfiction.net/s/12345678/1/My-Story")
        → r"/s/12345678/"

        build_story_id_regex("https://royalroad.com/fiction/55418/the-wandering-inn")
        → r"/fiction/55418/"
    """
    try:
        path     = urlparse(url).path
        segments = [s for s in path.split("/") if s]

        # fanfiction.net pattern: /s/{id}/{chapter_num}/{slug}
        if len(segments) >= 3 and segments[0] == "s" and segments[1].isdigit():
            return re.escape(f"/s/{segments[1]}/")

        # Generic: đường dẫn tới segment số đầu tiên
        for i, seg in enumerate(segments):
            if seg.isdigit() and i > 0:
                story_path = "/" + "/".join(segments[:i+1]) + "/"
                return re.escape(story_path)
    except Exception:
        pass
    return None


def is_chapter_url(url: str, profile: SiteProfile) -> bool:
    """
    Kiểm tra URL có phải chapter URL không.

    Ưu tiên regex từ profile (đã học), fallback về RE_CHAP_URL heuristic.
    """
    pattern = profile.get("chapter_url_pattern")
    if pattern:
        try:
            if re.search(pattern, url, re.IGNORECASE):
                return True
        except re.error:
            pass
    return bool(RE_CHAP_URL.search(url))


def story_id_ok(url: str, progress: ProgressDict) -> bool:
    """
    Kiểm tra URL thuộc đúng story đang cào.

    Nếu story_id chưa bị lock → luôn trả về True (chưa guard).
    Nếu đã lock → kiểm tra URL match story_id_regex.
    """
    if not progress.get("story_id_locked"):
        return True
    pattern = progress.get("story_id_regex")
    if not pattern:
        return True
    try:
        return bool(re.search(pattern, url))
    except re.error:
        return True