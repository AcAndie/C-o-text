"""
core/chapter_writer.py — Chapter filename formatting và content post-processing.

Fix P2-11: lru_cache cho _get_chapter_re() thay vì re.compile() trong hot path.

Fix FILENAME-B: Bỏ has_chapter_subtitle gate.
  Trước: subtitle chỉ được include vào filename khi has_chapter_subtitle=True.
         "Chapter 23: Interlude 1" với has_chapter_subtitle=False → "0023_Chapter23.md"
         → Hai chapter khác nhau có thể cùng tên file.
  Sau:   Subtitle luôn được dùng khi có.
         Logic: nếu có subtitle → chỉ dùng subtitle (số thứ tự 0023 đã là prefix).
                nếu không có   → keyword+number là identifier.

  "Chapter 23: Interlude 1" → "0023_Interlude_1.md"   (unique)
  "Chapter 23"              → "0023_Chapter23.md"     (no subtitle fallback)
  "Prologue"                → "0001_Prologue.md"      (no keyword match)
  "Chapter 1"               → "0001_Chapter1.md"      (no subtitle)
"""
from __future__ import annotations

import functools
import re

from utils.string_helpers import slugify_filename
from utils.types import ProgressDict

# ── Constants ──────────────────────────────────────────────────────────────────

_RE_PIPE_SUFFIX = re.compile(r"\s*\|.*$")

_RE_WORD_COUNT = re.compile(
    r"^\[\s*[\d,.\s]+words?\s*\]$|^\[\s*\.+\s*words?\s*\]$",
    re.IGNORECASE,
)

_NAV_EDGE_SCAN = 7


# ── Cached regex factory ───────────────────────────────────────────────────────

@functools.lru_cache(maxsize=32)
def _get_chapter_re(chapter_kw: str) -> re.Pattern:
    """
    Compile và cache regex cho chapter keyword.
    Fix P2-11: hot path, lru_cache đảm bảo chỉ compile một lần.
    """
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

    Logic (Fix FILENAME-B):
        1. Bóc story prefix nếu có (VD: "Monster Cultivator Chapter 5" → "Chapter 5")
        2. Parse chapter keyword + số
        3. Nếu có subtitle → dùng CHỈ subtitle làm tên file
           (số thứ tự 0000 đã là prefix duy nhất, tránh "0023_Chapter23_Chapter23")
        4. Nếu không có subtitle → dùng keyword+number
        5. Fallback: slugify toàn bộ title

    Examples:
        "Chapter 23: Interlude 1" → "0023_Interlude_1.md"
        "Chapter 23"              → "0023_Chapter23.md"
        "Prologue: The Beginning" → "0001_Prologue_The_Beginning.md"
        "Prologue"                → "0001_Prologue.md"
        "Interlude 1"             → "0023_Interlude_1.md"  (no keyword match → full title)
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

    # Fix P2-11: dùng cached regex
    m = _get_chapter_re(chapter_kw).search(title)

    if m:
        n       = m.group("n")
        sub_raw = m.group("sub").strip(" -–—:[]().")
        sub_raw = _RE_PIPE_SUFFIX.sub("", sub_raw).strip()

        if sub_raw and len(sub_raw) >= 2:
            # Fix FILENAME-B: có subtitle → dùng CHỈ subtitle.
            # "Chapter 23: Interlude 1" → "0023_Interlude_1.md"
            # Không prefix "Chapter23_" vì 0023 đã là unique identifier.
            name = f"{chapter_num:04d}_{slugify_filename(sub_raw, max_len=80)}"
        else:
            # Không có subtitle → keyword+number là identifier duy nhất.
            # "Chapter 23" → "0023_Chapter23.md"
            chap_id = f"{chapter_kw}{n}"
            name    = f"{chapter_num:04d}_{chap_id}"
    else:
        # Không match chapter keyword → dùng toàn bộ title.
        # "Prologue" → "0001_Prologue.md"
        # "Interlude 1" → "0001_Interlude_1.md"
        fallback = (title or raw_title).strip()
        name     = f"{chapter_num:04d}_{slugify_filename(fallback, max_len=80)}"

    return slugify_filename(name, max_len=120) + ".md"


# ── strip_nav_edges ────────────────────────────────────────────────────────────

def strip_nav_edges(text: str) -> str:
    """
    Xóa navigation/boilerplate text ở đầu và cuối chapter content.

    Phát hiện:
        - Lines xuất hiện ở CẢ đầu VÀ cuối (repeated navigation)
        - "[1,234 words]" / "[... words]" patterns
        - Lines ngắn chỉ có chữ cái (Prev/Next/TOC labels)
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