from __future__ import annotations

import re
from typing import List


# ── Thresholds ─────────────────────────────────────────────────────────────────

_MIN_REMAINING   = 100
_MIN_PROSE_WORDS = 7
_MAX_STRIP_RATIO = 0.60


# ── Pass 0: Raw script/HTML lines ─────────────────────────────────────────────
#
# Một số sites (VD: NovelFire) inject <script> tags dưới dạng TEXT NODE bên trong
# content div. BeautifulSoup parse chúng thành NavigableString (không phải Tag),
# nên _EXTRACT_SKIP_TAGS và prepare_soup() đều không bắt được.
# Kết quả: script tag text xuất hiện verbatim trong extracted content.
#
# Pattern: line bắt đầu bằng "<script" (sau khi strip whitespace).
# Không dùng broad HTML regex để tránh false positive với
# nội dung truyện chứa ký tự < (VD: "< 5 minutes", math expressions).
#
_RAW_SCRIPT_LINE_RE = re.compile(r"^\s*<script\b", re.IGNORECASE)


# ── Pass 0b: Unicode blank/spacer-only lines (v1.0.2) ─────────────────────────
#
# Some sites (esp. RoyalRoad) inject Unicode blank chars for vertical spacing:
#   - U+2800 BRAILLE PATTERN BLANK (`⠀`) — visually empty but not whitespace
#   - U+00A0 NBSP
#   - U+200B/200C/200D zero-width chars
#   - U+FEFF BOM
#   - U+3000 ideographic space
#
# These render as lines of "invisible content" — clutter in Obsidian / batch
# translate. ASCII whitespace stripping (`line.strip()`) treats most of these
# as non-whitespace → line survives. Pass 0b targets lines containing ONLY
# Unicode blanks (any combo) and drops them.
#
# Conservative: only line-only blanks. Inline blanks inside prose preserved
# (could be intentional formatting trick).
#
_UNICODE_BLANK_LINE_RE = re.compile(
    r"^[\s  -‏    ⠀　﻿]*$"
)


def _strip_unicode_blank_lines(text: str) -> str:
    """
    Drop lines that contain ONLY Unicode whitespace / blank chars (incl. braille
    U+2800 used as RoyalRoad spacer). Preserves inline use within prose.

    Fix v1.0.13: skip pure empty lines (`""`) — they're paragraph breaks in
    Markdown. Bug halved newlines in EPUB output (`\\n\\n` → `\\n`), joining
    all paragraphs into one giant line. Only drop if line has ≥1 char.
    """
    lines  = text.splitlines()
    result = [
        line for line in lines
        if not (line and _UNICODE_BLANK_LINE_RE.match(line))
    ]
    candidate = "\n".join(result)
    return candidate if len(candidate.strip()) >= _MIN_REMAINING else text


def _strip_raw_script_lines(text: str) -> str:
    """
    Strip lines that are raw <script> tag content rendered as text.

    Chỉ strip lines BẮT ĐẦU bằng <script — không strip content truyện
    có thể chứa < ở giữa câu.
    """
    lines = text.splitlines()
    result = []
    for line in lines:
        if _RAW_SCRIPT_LINE_RE.match(line):
            continue
        result.append(line)

    candidate = "\n".join(result)
    return candidate if len(candidate.strip()) >= _MIN_REMAINING else text


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

_SETTINGS_EXACT = frozenset({
    "font size", "font family", "font color", "font",
    "color", "color scheme", "theme",
    "background", "dim background",
    "reader width", "width", "line spacing", "paragraph spacing",
    "reading mode", "reading options",
    "expand", "tighten",
    "3/4", "1/2",
})

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
    lines  = text.splitlines()
    result : List[str] = []
    i      = 0

    while i < len(lines):
        window_size    = min(8, len(lines) - i)
        window         = lines[i: i + window_size]
        settings_count = sum(1 for l in window if _is_settings_line(l))

        if settings_count >= 4:
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


# ── Pass 3: Postfix support/nav section ───────────────────────────────────────

_POSTFIX_SECTION_MARKERS = [
    re.compile(r"^#{1,6}\s+support\b",           re.I),
    re.compile(r"^#{1,6}\s+about\s+the\s+author", re.I),
    re.compile(r"^#{1,6}\s+author.{0,20}note",   re.I),
    re.compile(r"^-{3,}\s*$"),
]

_NAV_CLUSTER_WORDS = frozenset({
    "previous", "prev", "next", "fiction", "chapter",
    "home", "contents", "toc", "index", "donate", "patreon",
    "report", "subscribe",
})

_NAV_CLUSTER_THRESHOLD = 3


def _strip_postfix_section(text: str) -> str:
    lines  = text.splitlines()
    n      = len(lines)
    cutoff = max(3, int(n * 0.35))

    for i, line in enumerate(lines):
        if i < cutoff:
            continue
        stripped = line.strip()

        if any(p.search(stripped) for p in _POSTFIX_SECTION_MARKERS[:2]):
            candidate = "\n".join(lines[:i])
            if len(candidate.strip()) >= _MIN_REMAINING:
                return candidate

        window = [l.strip().lower() for l in lines[i: i + 5] if l.strip()]
        nav_hits = sum(1 for w in window if w in _NAV_CLUSTER_WORDS)
        if nav_hits >= _NAV_CLUSTER_THRESHOLD:
            candidate = "\n".join(lines[:i])
            if len(candidate.strip()) >= _MIN_REMAINING:
                return candidate

    return text


# ── Pass 4: Story metadata header ─────────────────────────────────────────────

_META_RE = [
    re.compile(r"^by\s*:?\s*\S",               re.I),
    re.compile(r"^by\s*$",                     re.I),
    re.compile(
        r"\b(?:words?|chapters?|reviews?|favs?|favorites?|follows?)\s*:",
        re.I,
    ),
    re.compile(r"\b(?:updated|published|posted)\s*:", re.I),
    re.compile(r"^\s*id\s*:\s*\d+\s*$",        re.I),
    re.compile(r"^fiction\s+[TKM]\b",           re.I),
    re.compile(r"^rated\s*:",                    re.I),
    re.compile(
        r"[-–]\s*(?:english|french|spanish|japanese|korean|chinese)\s*[-–]",
        re.I,
    ),
    re.compile(r"\d{1,3},\d{3}\s+words?\b",     re.I),
    re.compile(r"^(?:genre|category|status)\s*:", re.I),
    re.compile(r"^fiction\s+page\s*$",           re.I),
    re.compile(r"^donate\s*$",                   re.I),
    re.compile(r"^report\s+chapter\s*$",         re.I),
    re.compile(r"^#{1,6}\s*$"),
]


def _strip_metadata_header(text: str) -> str:
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
        is_list_meta = (
            stripped.startswith("-")
            and len(stripped) <= 100
            and in_block
        )
        is_artifact = (
            in_block
            and len(stripped) <= 8
            and re.match(r"^[\d+/\-.,\*#]+$", stripped)
        )

        if is_meta or is_list_meta or is_artifact:
            if not in_block:
                in_block = True
            meta_end = i + 1
        elif in_block:
            if len(stripped.split()) >= _MIN_PROSE_WORDS:
                break
            else:
                meta_end = i + 1

    if meta_end >= 3 and in_block:
        while meta_end < len(lines) and not lines[meta_end].strip():
            meta_end += 1
        candidate = "\n".join(lines[meta_end:])
        if len(candidate.strip()) >= _MIN_REMAINING:
            return candidate

    return text


# ── Pass 5: Static UI navigation text patterns ────────────────────────────────
#
# Bổ sung cho ads_filter (dynamic). Pass này là static — hardcoded patterns phổ biến.
# Belt-and-suspenders: ads_filter học từ dữ liệu, pass này là safety net.
#
# Batch C: đây là Pass 5 mới (trước là Pass 6).
# Pass 5 cũ (_strip_author_bio) đã bị xóa — quá speculative, high false positive risk
# (cutoff 55% quá aggressive với chapters có epilogue/author note ở cuối).

_UI_NAV_PATTERNS: list[re.Pattern] = [
    re.compile(r"^restore scroll position\s*$",                     re.I),
    re.compile(r"^tap the middle of the screen to reveal",          re.I),
    re.compile(r"^tip\s*:\s*you can use left.*right.*keyboard",     re.I),
    re.compile(r"^share to your friends\s*$",                       re.I),
    re.compile(r"^if you find any errors.*let us know\s*",          re.I),
    re.compile(r"^report chapter\s*$",                              re.I),
    re.compile(r"^report error\s*$",                                re.I),
    re.compile(r"^support the (author|translator|series)\s*$",      re.I),
    re.compile(r"^add to library\s*$",                              re.I),
    re.compile(r"^send gift\s*$",                                   re.I),
    re.compile(r"^vote for this chapter\s*$",                       re.I),
    re.compile(r"^unlock.*chapter\s*$",                             re.I),
    re.compile(r"^locked chapter\s*$",                              re.I),
    re.compile(r"^read more at\b",                                  re.I),
    re.compile(r"^visit.*for the latest",                           re.I),
    re.compile(r"^the source of this content is\b",                 re.I),
    re.compile(r"^this content is taken from",                      re.I),
    re.compile(r"^please read this on the (original|official)",     re.I),
    re.compile(r"^if you want to read more chapters.*follow.*on",   re.I),
]


def _strip_ui_navigation_text(text: str) -> str:
    """
    Strip các dòng là UI navigation text phổ biến (static patterns).

    Không có cutoff threshold — các pattern này rất đặc trưng, ít false positive.
    """
    if not text:
        return text
    lines = text.splitlines()
    result = [line for line in lines
              if not any(p.match(line.strip()) for p in _UI_NAV_PATTERNS)]
    candidate = "\n".join(result)
    return candidate if len(candidate.strip()) >= _MIN_REMAINING else text


# ── Pass 6: Status box reformat (v1.0.11) ─────────────────────────────────────
#
# LitRPG/cultivation novels (RoyalRoad in particular) wrap status displays
# in <strong> per line:
#   <strong>HP</strong>: 144/144
#   <strong>Mana</strong>: 0/0
#   <strong>Level</strong>: 11
#
# MarkdownFormatter correctly emits:
#   **HP**: 144/144
#   **Mana**: 0/0
#   **Level**: 11
#
# Visual result in Obsidian: ugly wall of bold markers. Some lines have broken
# bold (whitespace inside markers) → not rendered as bold → user sees raw `**`.
#
# Fix: detect 3+ consecutive lines matching status pattern, wrap in Obsidian
# callout `> [!info]+ Status` block, strip inner bold (label is self-evident).
#
# Conservative: requires strict pattern — bold-prefix only, single line.
# Won't false-positive on prose with occasional bold emphasis.

# 3 patterns covering valid status line shapes. Order matters — most specific first.
# Constrain length (<160 chars) to avoid false positive on prose paragraphs that
# happen to start with a bold word.
_STATUS_LINE_PATTERNS = [
    re.compile(r"^\s*\*\*([^*\n]+?):\*\*\s*(.*?)\s*$"),         # **X:** value  (colon inside)
    re.compile(r"^\s*\*\*([^*\n]+?)\*\*\s*[:=]\s*(.+?)\s*$"),   # **X**: value  (colon outside)
    re.compile(r"^\s*\*\*([^*\n]+?)\*\*\s*$"),                  # **X**         (label only)
]

_MIN_STATUS_CLUSTER  = 3
_STATUS_LINE_MAX_LEN = 160

# v1.0.22: plain `Label:` line (no bold) — bridge giữa các bold status lines.
# VD RR chapter có:  **Quest:**  /  **Altitude**: 1m  /  Full Status:  /  **HP:** 22
# Mid-line `Full Status:` không match bold patterns → cluster break.
# Bridge cho phép nối nếu line ngắn + ends with colon + surrounded bởi real status.
_BRIDGE_LABEL_RE = re.compile(r"^\s*[A-Z][A-Za-z 0-9()/\-]{0,40}:\s*$")


def _match_status_line(line: str) -> tuple[str, str] | None:
    """Try each pattern. Return (label, value) on match, else None."""
    if len(line) > _STATUS_LINE_MAX_LEN:
        return None
    for p in _STATUS_LINE_PATTERNS:
        m = p.match(line)
        if m:
            label = m.group(1).strip()
            value = (m.group(2).strip() if m.lastindex and m.lastindex >= 2 else "")
            # Strip stray inner bold markers from value
            value = re.sub(r"^\*+|\*+$", "", value).strip()
            return (label, value)
    return None


def _is_bridge_label(line: str) -> bool:
    """v1.0.22: plain `Label:` line — bridge only, not cluster initiator."""
    return bool(_BRIDGE_LABEL_RE.match(line))


def _wrap_status_blocks(text: str) -> str:
    """
    Detect consecutive `**X**` / `**X**: value` lines (3+) and wrap in
    Obsidian callout. Preserves prose around the block. Blank lines inside
    block tolerated.
    """
    if not text or "**" not in text:
        return text

    lines = text.splitlines()
    out: list[str] = []
    i      = 0
    while i < len(lines):
        cluster: list[tuple[str, str] | None] = []  # None = blank separator
        j = i
        while j < len(lines):
            line = lines[j]
            parsed = _match_status_line(line)
            if parsed is not None:
                cluster.append(parsed)
                j += 1
            elif (
                line.strip() == ""
                and cluster
                and j + 1 < len(lines)
                and _match_status_line(lines[j + 1]) is not None
            ):
                cluster.append(None)
                j += 1
            elif (
                _is_bridge_label(line)
                and cluster
                and j + 1 < len(lines)
                and _match_status_line(lines[j + 1]) is not None
            ):
                # v1.0.22: plain `Label:` bridge giữa bold status lines.
                # Emit as bold header trong callout để consistent với cluster
                # (treat as label-only entry, no value).
                cluster.append((line.strip().rstrip(":"), ""))
                j += 1
            else:
                break

        # Trim trailing blank markers
        while cluster and cluster[-1] is None:
            cluster.pop()
            j -= 1

        if sum(1 for x in cluster if x is not None) >= _MIN_STATUS_CLUSTER:
            out.append("> [!info]+ Status")
            for entry in cluster:
                if entry is None:
                    out.append(">")
                else:
                    label, value = entry
                    if value:
                        out.append(f"> **{label}:** {value}")
                    else:
                        out.append(f"> **{label}**")
            out.append("")   # blank after callout
            i = j
        else:
            out.append(lines[i])
            i += 1

    return "\n".join(out)


# ── Pass 7: Broken bold pattern fix (v1.0.11) ─────────────────────────────────
#
# CommonMark requires no whitespace at bold span boundary:
#   `**foo: **bar`        → NOT bold (space before closing **)
#   `**foo: ** bar`       → NOT bold
#   `**foo:** bar`        → OK
#
# RR HTML occasionally has `<strong>X: </strong>Y` with trailing space inside
# strong → formatter emits `**X: **Y` → Obsidian shows literal asterisks.
#
# Fix: detect `**...space**` and move whitespace out.

# [ \t] horizontal whitespace only — \s would match \n and cause cross-line
# greedy match (bug found smoke test v1.0.11).
_BROKEN_BOLD_RE = re.compile(r"\*\*([^*\n]+?)[ \t]+\*\*")


def _fix_broken_bold(text: str) -> str:
    """Move trailing whitespace out of bold span so CommonMark renders bold."""
    if not text or "**" not in text:
        return text
    return _BROKEN_BOLD_RE.sub(r"**\1** ", text)


# ── Main entry point ──────────────────────────────────────────────────────────

def clean_extracted_content(text: str) -> str:
    """
    Apply tất cả cleaning passes theo thứ tự.

    Pass order:
        0. _strip_raw_script_lines  (<script> text nodes từ sites như NovelFire)
        0b. _strip_unicode_blank_lines (U+2800 braille spacer, NBSP-only lines)
        1. _strip_comment_section   (từ 30% trở xuống)
        2. _strip_settings_panel    (bất kỳ vị trí)
        3. _strip_postfix_section   (từ 35% trở xuống)
        4. _strip_metadata_header   (25 dòng đầu)
        5. _strip_ui_navigation_text (static UI patterns — bất kỳ vị trí)

    Batch C: Bỏ Pass 5 cũ (_strip_author_bio, cutoff 55%) — quá speculative,
    false positive với chapters có epilogue/author note hợp lệ ở cuối.

    Conservative: không bao giờ return ít hơn 40% original content.
    """
    if not text or len(text.strip()) < _MIN_REMAINING:
        return text

    original_len = len(text.strip())
    result       = text

    result = _strip_raw_script_lines(result)    # Pass 0
    result = _strip_unicode_blank_lines(result) # Pass 0b
    result = _strip_comment_section(result)     # Pass 1
    result = _strip_settings_panel(result)      # Pass 2
    result = _strip_postfix_section(result)     # Pass 3
    result = _strip_metadata_header(result)     # Pass 4
    result = _strip_ui_navigation_text(result)  # Pass 5
    result = _fix_broken_bold(result)           # Pass 6  (v1.0.11)
    result = _wrap_status_blocks(result)        # Pass 7  (v1.0.11)

    cleaned_len = len(result.strip())

    # Safety: nếu strip > 60% → return original
    if cleaned_len < original_len * (1 - _MAX_STRIP_RATIO):
        return text

    return result.strip() if result.strip() else text