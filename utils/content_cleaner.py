"""
utils/content_cleaner.py — Mandatory post-extraction content cleaner.

Chạy SAU mỗi extract operation để strip noise slipped qua CSS selectors,
bất kể profile được học tốt đến đâu. Defense-in-depth layer thứ 3
(sau html_filter và remove_selectors).

Vấn đề giải quyết:
  - Royal Road  : author bio + comment section + settings panel leak vào content
  - FanFiction  : story stats header (#profile_top) leak vào content
  - Generic     : bất kỳ site nào có content_selector hơi rộng

4 passes (theo thứ tự):
  1. _strip_comment_section  — "BEGIN COMMENTS" marker → xóa từ đó xuống
  2. _strip_settings_panel   — Font Size/Theme/Background blocks → xóa block
  3. _strip_metadata_header  — Story stats ở đầu (By:, Words:, Follows:, ...) → xóa
  4. _strip_author_bio       — Author bio/achievements ở cuối → xóa

Safety constraints:
  - Không strip nếu còn lại < _MIN_REMAINING chars
  - Không strip nếu stripped > 60% của original (heuristic fail-safe)
  - Comment markers chỉ cut sau first 30% của content
  - Bio markers chỉ cut sau first 60% của content
"""
from __future__ import annotations

import re
from typing import List


# ── Thresholds ─────────────────────────────────────────────────────────────────

_MIN_REMAINING   = 100   # ký tự tối thiểu sau khi strip
_MIN_PROSE_WORDS = 7     # từ tối thiểu để coi là "prose line"
_MAX_STRIP_RATIO = 0.60  # không strip nếu mất > 60% content


# ── Pass 1: Comment section ────────────────────────────────────────────────────

_COMMENT_MARKERS = [
    re.compile(r"begin\s+comments?",        re.I),
    re.compile(r"^comments?\s*\(\d+\)\s*$", re.I),
    re.compile(r"^log\s+in\s+to\s+comment\s*$", re.I),
    re.compile(r"^write\s+a\s+review\s*$",  re.I),
    re.compile(r"^post\s+a\s+comment\s*$",  re.I),
    re.compile(r"^leave\s+a\s+comment\s*$", re.I),
]


def _strip_comment_section(text: str) -> str:
    """
    Nếu thấy comment marker SAU first 30% content, strip từ đó xuống.

    Safety: chỉ strip nếu những dòng SAU marker cũng là noise
    (< 2 prose-length lines trong 6 dòng tiếp theo).
    """
    lines  = text.splitlines()
    n      = len(lines)
    cutoff = max(5, int(n * 0.30))

    for i, line in enumerate(lines):
        if i < cutoff:
            continue
        stripped = line.strip()
        if not stripped:
            continue
        if any(p.search(stripped) for p in _COMMENT_MARKERS):
            following  = [l.strip() for l in lines[i + 1: i + 7] if l.strip()]
            prose_count = sum(
                1 for l in following
                if len(l.split()) >= _MIN_PROSE_WORDS
                and not any(p.search(l) for p in _COMMENT_MARKERS)
            )
            if prose_count <= 1:
                candidate = "\n".join(lines[:i])
                if len(candidate.strip()) >= _MIN_REMAINING:
                    return candidate
    return text


# ── Pass 2: Settings panel ─────────────────────────────────────────────────────

# Exact lowercase matches cho settings keywords (short lines only)
_SETTINGS_EXACT = frozenset({
    "font size", "font family", "font color", "font",
    "color", "color scheme", "theme",
    "background", "dim background",
    "reader width", "width", "line spacing", "paragraph spacing",
    "reading mode", "reading options",
    "expand", "tighten",    # Royal Road width controls
    "3/4", "1/2",           # Royal Road width fraction options
})

# Prefix matches
_SETTINGS_PREFIX = (
    "theme (", "font size", "font family",
    "reading settings", "display settings", "site settings",
)


def _is_settings_line(line: str) -> bool:
    lo = line.strip().lower()
    if not lo:
        return False
    if lo in _SETTINGS_EXACT:
        return True
    if any(lo.startswith(sw) for sw in _SETTINGS_PREFIX):
        return True
    return False


def _strip_settings_panel(text: str) -> str:
    """
    Tìm và xóa settings panel blocks.
    Block = window 8 dòng có >= 4 dòng là settings-like.
    """
    lines  = text.splitlines()
    result : List[str] = []
    i      = 0

    while i < len(lines):
        window_size    = min(8, len(lines) - i)
        window         = lines[i: i + window_size]
        settings_count = sum(1 for l in window if _is_settings_line(l))

        if settings_count >= 4:
            # Skip block: tìm 2 prose lines liên tiếp để dừng
            j             = i + window_size
            prose_streak  = 0
            while j < len(lines):
                l = lines[j].strip()
                if not l:
                    j += 1
                    continue
                if not _is_settings_line(lines[j]):
                    prose_streak += 1
                    if prose_streak >= 2:
                        break
                else:
                    prose_streak = 0
                j += 1
            i = j
        else:
            result.append(lines[i])
            i += 1

    candidate = "\n".join(result)
    return candidate if len(candidate.strip()) >= _MIN_REMAINING else text


# ── Pass 3: Story metadata header ─────────────────────────────────────────────

_META_RE = [
    re.compile(r"^by\s*:?\s*\S",               re.I),
    re.compile(
        r"\b(?:words?|chapters?|reviews?|favs?|favorites?|follows?)\s*:",
        re.I,
    ),
    re.compile(r"\b(?:updated|published|posted)\s*:", re.I),
    re.compile(r"^\s*id\s*:\s*\d+\s*$",         re.I),
    re.compile(r"^fiction\s+[TKM]\b",            re.I),
    re.compile(r"^rated\s*:",                     re.I),
    re.compile(
        r"[-–]\s*(?:english|french|spanish|japanese|korean|chinese)\s*[-–]",
        re.I,
    ),
    re.compile(r"\d{1,3},\d{3}\s+words?\b",      re.I),  # "228,167 words"
    re.compile(r"^(?:genre|category|status)\s*:", re.I),
]


def _strip_metadata_header(text: str) -> str:
    """
    Strip story metadata block ở đầu content (first 25 lines).

    Detect block có >= 3 lines match metadata patterns.
    Dừng khi gặp dòng prose thật (>= _MIN_PROSE_WORDS từ).
    """
    lines    = text.splitlines()
    meta_end = 0
    in_block = False

    for i, line in enumerate(lines[:25]):
        stripped = line.strip()
        if not stripped:
            if in_block:
                meta_end = i + 1
            continue

        is_meta    = any(p.search(stripped) for p in _META_RE)
        # Dash-list lines trong stats block: "- English - Adventure - Chapters: 70"
        is_list_meta = (
            stripped.startswith("-")
            and len(stripped) <= 100
            and in_block
        )
        # Rogue numbers/symbols trong stats: "+", "3/22", "1/2/2025"
        is_artifact = (
            in_block
            and len(stripped) <= 8
            and re.match(r"^[\d+/\-.,]+$", stripped)
        )

        if is_meta or is_list_meta or is_artifact:
            if not in_block:
                in_block = True
            meta_end = i + 1
        elif in_block:
            if len(stripped.split()) >= _MIN_PROSE_WORDS:
                break   # Prose thật → dừng
            else:
                # Short non-meta, có thể vẫn là artifact của block
                meta_end = i + 1

    if meta_end >= 3 and in_block:
        # Skip blank lines sau block
        while meta_end < len(lines) and not lines[meta_end].strip():
            meta_end += 1
        candidate = "\n".join(lines[meta_end:])
        if len(candidate.strip()) >= _MIN_REMAINING:
            return candidate

    return text


# ── Pass 4: Author bio ─────────────────────────────────────────────────────────

_BIO_RE = [
    re.compile(r"^\*+\s*bio\s*\*+\s*$",        re.I),
    re.compile(r"^achievements?\s*$",            re.I),
    re.compile(r"^follow\s+(?:the\s+)?author",   re.I),
    re.compile(r"^end\s+col-md-",               re.I),   # Royal Road layout artifact
    re.compile(r"^end\s+row\s*$",               re.I),
    re.compile(r"^\#\s+\w+$",                   re.I),   # "# AuthorName" heading
]


def _strip_author_bio(text: str) -> str:
    """
    Strip author bio / achievements section ở cuối content.
    Chỉ strip nếu marker xuất hiện sau first 60%.
    """
    lines  = text.splitlines()
    n      = len(lines)
    cutoff = max(5, int(n * 0.60))

    for i in range(n - 1, cutoff - 1, -1):
        stripped = lines[i].strip()
        if not stripped:
            continue
        if any(p.search(stripped) for p in _BIO_RE):
            candidate = "\n".join(lines[:i])
            if len(candidate.strip()) >= _MIN_REMAINING:
                return candidate

    return text


# ── Main entry point ──────────────────────────────────────────────────────────

def clean_extracted_content(text: str) -> str:
    """
    Apply tất cả 4 cleaning passes theo thứ tự.

    Conservative: không bao giờ return ít hơn 40% original content.
    Nếu passes strip quá nhiều → return original (selector issue → log separately).

    Args:
        text: Raw extracted content từ pipeline extract chain

    Returns:
        Cleaned prose text, hoặc original nếu cleaning quá aggressive
    """
    if not text or len(text.strip()) < _MIN_REMAINING:
        return text

    original_len = len(text.strip())
    result       = text

    result = _strip_comment_section(result)
    result = _strip_settings_panel(result)
    result = _strip_metadata_header(result)
    result = _strip_author_bio(result)

    cleaned_len = len(result.strip())

    # Safety: nếu strip > 60% → return original (something went wrong)
    if cleaned_len < original_len * (1 - _MAX_STRIP_RATIO):
        return text

    return result.strip() if result.strip() else text