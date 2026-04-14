"""
core/chapter_writer.py — Chapter filename formatting và content post-processing.

Fix P2-11: lru_cache cho _get_chapter_re() thay vì re.compile() trong hot path.

Fix FILENAME-B: Bỏ has_chapter_subtitle gate.

Fix FILENAME-C: _is_garbage_subtitle() guard.

Fix FILENAME-D: Strip comma khỏi sub_raw trước khi check _is_garbage_subtitle().

Fix FILENAME-E: Apply strip_site_suffix() lên sub_raw.
  Trước: subtitle "Enjoying life[ ... words ]" bị dùng nguyên làm filename
         → "0025_Enjoying_life[_..._words_].md"
  Sau:   strip_site_suffix(sub_raw) → "Enjoying life" → "0025_Enjoying_life.md"
  
  Belt-and-suspenders: title_extractor.py (Fix TITLE-A/B) đã strip ở level ctx.title_clean,
  nhưng format_chapter_filename() nhận raw_title từ progress fallback path
  (prefetch_map, reuse chapters) có thể bypass title_vote. Double-guard ở đây.
"""
from __future__ import annotations

import functools
import re

from utils.string_helpers import slugify_filename, strip_site_suffix
from utils.types import ProgressDict

# ── Constants ──────────────────────────────────────────────────────────────────

_RE_PIPE_SUFFIX = re.compile(r"\s*\|.*$")

_RE_WORD_COUNT = re.compile(
    r"^\[\s*[\d,.\s]+words?\s*\]$|^\[\s*\.+\s*words?\s*\]$",
    re.IGNORECASE,
)

_NAV_EDGE_SCAN = 7


# ── Garbage subtitle detection (Fix FILENAME-C) ────────────────────────────────

_GARBAGE_SUBTITLE_PATTERNS = (
    re.compile(r"^a\s+\S.{2,70}\s+fanfic(?:tion)?\s*$", re.IGNORECASE),
    re.compile(r"^translated\s+by\b", re.IGNORECASE),
    re.compile(r"^edited\s+by\b",     re.IGNORECASE),
    re.compile(r"^(?:official\s+)?(?:epub|pdf|translation)\b", re.IGNORECASE),
)


def _is_garbage_subtitle(sub: str) -> bool:
    if not sub or len(sub) < 2:
        return True
    for pat in _GARBAGE_SUBTITLE_PATTERNS:
        if pat.match(sub.strip()):
            return True
    if len(sub) > 60 and not re.search(r"[.!?,;:'\"()]", sub):
        return True
    return False


# ── Cached regex factory ───────────────────────────────────────────────────────

@functools.lru_cache(maxsize=32)
def _get_chapter_re(chapter_kw: str) -> re.Pattern:
    """Fix P2-11: compile và cache regex cho chapter keyword."""
    kw_esc = re.escape(chapter_kw)
    return re.compile(
        rf"(?:{kw_esc})\s*(?P<n>\d+)\s*[-–—:.]?\s*(?P<sub>.*)",
        re.IGNORECASE,
    )


# ── format_chapter_filename ────────────────────────────────────────────────────

def format_chapter_filename(
    chapter_num: int,
    raw_title  : str,
    progress   : ProgressDict,
) -> str:
    """
    Tạo tên file .md cho một chapter.

    Logic (Fix FILENAME-B + C + D + E):
        1. Bóc story prefix nếu có
        2. Bóc pipe suffix
        3. Parse chapter keyword + số
        4. Strip leading comma khỏi sub_raw (Fix FILENAME-D)
        5. Strip site suffix / word count artifacts (Fix FILENAME-E)
        6. Validate subtitle: nếu là garbage → fallback về keyword+number
        7. Nếu subtitle thật → dùng CHỈ subtitle làm tên file
        8. Nếu không có subtitle → keyword+number
        9. Fallback: slugify toàn bộ title

    Examples:
        "Chapter 23: Interlude 1"                        → "0023_Interlude_1.md"
        "Chapter 25: Enjoying life[ ... words ]"         → "0025_Enjoying_life.md" (Fix E)
        "Chapter 1, a percy jackson fanfic"              → "0001_Chapter1.md"      (Fix C+D)
        "Chapter 23"                                     → "0023_Chapter23.md"
        "Prologue: The Beginning"                        → "0001_Prologue_The_Beginning.md"
    """
    chapter_kw   = (progress.get("chapter_keyword") or "Chapter").strip()
    prefix_strip = (progress.get("story_prefix_strip") or "").strip()

    title = raw_title.strip()

    # Bóc story prefix
    if prefix_strip:
        lo_title  = title.lower()
        lo_prefix = prefix_strip.lower()
        if lo_title.startswith(lo_prefix):
            title = title[len(prefix_strip):].lstrip(" ,;:-–—")

    # Bóc pipe suffix
    title = _RE_PIPE_SUFFIX.sub("", title).strip()

    m = _get_chapter_re(chapter_kw).search(title)

    if m:
        n       = m.group("n")
        # Fix FILENAME-D: strip comma trước khi strip separators khác.
        sub_raw = m.group("sub").strip(" ,-–—:[]().")
        sub_raw = _RE_PIPE_SUFFIX.sub("", sub_raw).strip()
        # Fix FILENAME-E: strip word count artifacts và site suffixes từ subtitle.
        # "Enjoying life[ ... words ]" → "Enjoying life"
        sub_raw = strip_site_suffix(sub_raw).strip()

        if sub_raw and len(sub_raw) >= 2 and not _is_garbage_subtitle(sub_raw):
            name = f"{chapter_num:04d}_{slugify_filename(sub_raw, max_len=80)}"
        else:
            chap_id = f"{chapter_kw}{n}"
            name    = f"{chapter_num:04d}_{chap_id}"
    else:
        fallback = (title or raw_title).strip()
        name     = f"{chapter_num:04d}_{slugify_filename(fallback, max_len=80)}"

    return slugify_filename(name, max_len=120) + ".md"


# ── strip_nav_edges ────────────────────────────────────────────────────────────

def strip_nav_edges(text: str) -> str:
    """
    Xóa navigation/boilerplate text ở đầu và cuối chapter content.
    """
    lines = text.splitlines()
    n     = len(lines)

    if n < 8:
        return text

    EDGE    = _NAV_EDGE_SCAN
    top_set = {lines[i].strip() for i in range(min(EDGE, n)) if lines[i].strip()}
    bot_set = {lines[n-1-i].strip() for i in range(min(EDGE, n)) if lines[n-1-i].strip()}
    repeated = top_set & bot_set

    def _is_nav(line: str) -> bool:
        s = line.strip()
        if not s:
            return True
        if _RE_WORD_COUNT.match(s):
            return True
        if len(s) <= 10 and re.match(r"^[A-Za-z\s]+$", s):
            return True
        return s in repeated

    start = 0
    for i in range(min(EDGE, n)):
        if _is_nav(lines[i]):
            start = i + 1
        else:
            break
    while start < n and not lines[start].strip():
        start += 1

    end = n
    for i in range(min(EDGE, n)):
        idx = n - 1 - i
        if idx <= start:
            break
        if not lines[idx].strip() or _is_nav(lines[idx]):
            end = idx
        else:
            break
    while end > start and not lines[end-1].strip():
        end -= 1

    return "\n".join(lines[start:end]) if start < end else text