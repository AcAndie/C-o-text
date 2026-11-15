"""clean_extracted_content & strip_nav_edges: hậu xử lý văn bản chương.

Bao gồm:
  - 8 pass làm sạch nội dung (Pass 0 -> Pass 7) loại bỏ comment, settings, metadata, UI text...
  - Xử lý status block thành Obsidian callout (> [!info]+ Status).
  - Sửa lỗi broken bold (**word: ** -> **word:** ).
  - strip_nav_edges: xóa dòng điều hướng / boilerplate lặp lại ở hai đầu chương.
  - strip_duplicate_title_header: xóa dòng tiêu đề trùng lặp ở đầu nội dung.
  - Trần an toàn: không bao giờ xóa quá 60% dung lượng văn bản gốc.
"""
from __future__ import annotations

import re

# ── Ngưỡng an toàn ────────────────────────────────────────────────────────────

_MIN_REMAINING: int = 100
_MIN_PROSE_WORDS: int = 7
_MAX_STRIP_RATIO: float = 0.60
_NAV_EDGE_SCAN: int = 7

# ── Pass 0: Raw script/HTML lines ─────────────────────────────────────────────

_RAW_SCRIPT_LINE_RE = re.compile(r"^\s*<script\b", re.IGNORECASE)


def _strip_raw_script_lines(text: str) -> str:
    """Xóa các dòng chứa text thô của thẻ <script> (gặp ở NovelFire)."""
    lines = text.splitlines()
    result = [line for line in lines if not _RAW_SCRIPT_LINE_RE.match(line)]
    candidate = "\n".join(result)
    return candidate if len(candidate.strip()) >= _MIN_REMAINING else text


# ── Pass 0b: Unicode blank/spacer-only lines ──────────────────────────────────

_UNICODE_BLANK_LINE_RE = re.compile(r"^[\s  -‏    ⠀　﻿]*$")


def _strip_unicode_blank_lines(text: str) -> str:
    """Xóa các dòng chỉ chứa ký tự khoảng trắng Unicode vô hình (U+2800 braille, NBSP...).

    Giữ nguyên dòng rỗng chuẩn (\\n\\n) để không làm gộp đoạn.
    """
    lines = text.splitlines()
    result = [
        line for line in lines
        if not (line and _UNICODE_BLANK_LINE_RE.match(line))
    ]
    candidate = "\n".join(result)
    return candidate if len(candidate.strip()) >= _MIN_REMAINING else text


# ── Pass 1: Comment section ────────────────────────────────────────────────────

_COMMENT_MARKERS = [
    re.compile(r"begin\s+comments?", re.IGNORECASE),
    re.compile(r"^comments?\s*\(\d+\)\s*$", re.IGNORECASE),
    re.compile(r"^log\s+in\s+to\s+comment\s*$", re.IGNORECASE),
    re.compile(r"^write\s+a\s+review\s*$", re.IGNORECASE),
    re.compile(r"^post\s+a\s+comment\s*$", re.IGNORECASE),
    re.compile(r"^leave\s+a\s+comment\s*$", re.IGNORECASE),
]


def _strip_comment_section(text: str) -> str:
    """Cắt bỏ phần bình luận ở cuối trang (từ 30% nội dung trở xuống)."""
    lines = text.splitlines()
    n = len(lines)
    cutoff = max(5, int(n * 0.30))

    for i, line in enumerate(lines):
        if i < cutoff:
            continue
        stripped = line.strip()
        if not stripped:
            continue
        if any(p.search(stripped) for p in _COMMENT_MARKERS):
            following = [item.strip() for item in lines[i + 1 : i + 7] if item.strip()]
            prose_count = sum(
                1
                for item in following
                if len(item.split()) >= _MIN_PROSE_WORDS and not any(p.search(item) for p in _COMMENT_MARKERS)
            )
            if prose_count <= 1:
                candidate = "\n".join(lines[:i])
                if len(candidate.strip()) >= _MIN_REMAINING:
                    return candidate
    return text


# ── Pass 2: Settings panel ─────────────────────────────────────────────────────

_SETTINGS_EXACT = frozenset({
    "font size",
    "font family",
    "font color",
    "font",
    "color",
    "color scheme",
    "theme",
    "background",
    "dim background",
    "reader width",
    "width",
    "line spacing",
    "paragraph spacing",
    "reading mode",
    "reading options",
    "expand",
    "tighten",
    "3/4",
    "1/2",
})

_SETTINGS_PREFIX = (
    "theme (",
    "font size",
    "font family",
    "reading settings",
    "display settings",
    "site settings",
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
    """Xóa khối giao diện cài đặt đọc (Reading Settings) ở bất kỳ vị trí nào."""
    lines = text.splitlines()
    result: list[str] = []
    i = 0

    while i < len(lines):
        window_size = min(8, len(lines) - i)
        window = lines[i : i + window_size]
        settings_count = sum(1 for wline in window if _is_settings_line(wline))

        if settings_count >= 4:
            j = i + window_size
            prose_streak = 0
            while j < len(lines):
                line_str = lines[j].strip()
                if not line_str:
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
    re.compile(r"^#{1,6}\s+support\b", re.IGNORECASE),
    re.compile(r"^#{1,6}\s+about\s+the\s+author", re.IGNORECASE),
    re.compile(r"^#{1,6}\s+author.{0,20}note", re.IGNORECASE),
    re.compile(r"^-{3,}\s*$"),
]

_NAV_CLUSTER_WORDS = frozenset({
    "previous",
    "prev",
    "next",
    "fiction",
    "chapter",
    "home",
    "contents",
    "toc",
    "index",
    "donate",
    "patreon",
    "report",
    "subscribe",
})

_NAV_CLUSTER_THRESHOLD = 3


def _strip_postfix_section(text: str) -> str:
    """Xóa phần kêu gọi donate/support hoặc cụm nút điều hướng ở cuối trang."""
    lines = text.splitlines()
    n = len(lines)
    cutoff = max(3, int(n * 0.35))

    for i, line in enumerate(lines):
        if i < cutoff:
            continue
        stripped = line.strip()

        if any(p.search(stripped) for p in _POSTFIX_SECTION_MARKERS[:2]):
            candidate = "\n".join(lines[:i])
            if len(candidate.strip()) >= _MIN_REMAINING:
                return candidate

        window = [wline.strip().lower() for wline in lines[i : i + 5] if wline.strip()]
        nav_hits = sum(1 for w in window if w in _NAV_CLUSTER_WORDS)
        if nav_hits >= _NAV_CLUSTER_THRESHOLD:
            candidate = "\n".join(lines[:i])
            if len(candidate.strip()) >= _MIN_REMAINING:
                return candidate

    return text


# ── Pass 4: Story metadata header ─────────────────────────────────────────────

_META_RE = [
    re.compile(r"^by\s*:?\s*\S", re.IGNORECASE),
    re.compile(r"^by\s*$", re.IGNORECASE),
    re.compile(r"\b(?:words?|chapters?|reviews?|favs?|favorites?|follows?)\s*:", re.IGNORECASE),
    re.compile(r"\b(?:updated|published|posted)\s*:", re.IGNORECASE),
    re.compile(r"^\s*id\s*:\s*\d+\s*$", re.IGNORECASE),
    re.compile(r"^fiction\s+[TKM]\b", re.IGNORECASE),
    re.compile(r"^rated\s*:", re.IGNORECASE),
    re.compile(r"[-–]\s*(?:english|french|spanish|japanese|korean|chinese)\s*[-–]", re.IGNORECASE),
    re.compile(r"\d{1,3},\d{3}\s+words?\b", re.IGNORECASE),
    re.compile(r"^(?:genre|category|status)\s*:", re.IGNORECASE),
    re.compile(r"^fiction\s+page\s*$", re.IGNORECASE),
    re.compile(r"^donate\s*$", re.IGNORECASE),
    re.compile(r"^report\s+chapter\s*$", re.IGNORECASE),
    re.compile(r"^#{1,6}\s*$"),
]


def _strip_metadata_header(text: str) -> str:
    """Xóa khối metadata truyện dính ở 25 dòng đầu tiên."""
    lines = text.splitlines()
    meta_end = 0
    in_block = False

    for i, line in enumerate(lines[:25]):
        stripped = line.strip()
        if not stripped:
            if in_block:
                meta_end = i + 1
            continue

        is_meta = any(p.search(stripped) for p in _META_RE)
        is_list_meta = stripped.startswith("-") and len(stripped) <= 100 and in_block
        is_artifact = in_block and len(stripped) <= 8 and re.match(r"^[\d+/\-.,\*#]+$", stripped) is not None

        if is_meta or is_list_meta or is_artifact:
            if not in_block:
                in_block = True
            meta_end = i + 1
        elif in_block:
            if len(stripped.split()) >= _MIN_PROSE_WORDS:
                break
            meta_end = i + 1

    if meta_end >= 3 and in_block:
        while meta_end < len(lines) and not lines[meta_end].strip():
            meta_end += 1
        candidate = "\n".join(lines[meta_end:])
        if len(candidate.strip()) >= _MIN_REMAINING:
            return candidate

    return text


# ── Pass 5: Static UI navigation text patterns ────────────────────────────────

_UI_NAV_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"^restore scroll position\s*$", re.IGNORECASE),
    re.compile(r"^tap the middle of the screen to reveal", re.IGNORECASE),
    re.compile(r"^tip\s*:\s*you can use left.*right.*keyboard", re.IGNORECASE),
    re.compile(r"^share to your friends\s*$", re.IGNORECASE),
    re.compile(r"^if you find any errors.*let us know\s*", re.IGNORECASE),
    re.compile(r"^report chapter\s*$", re.IGNORECASE),
    re.compile(r"^report error\s*$", re.IGNORECASE),
    re.compile(r"^support the (author|translator|series)\s*$", re.IGNORECASE),
    re.compile(r"^add to library\s*$", re.IGNORECASE),
    re.compile(r"^send gift\s*$", re.IGNORECASE),
    re.compile(r"^vote for this chapter\s*$", re.IGNORECASE),
    re.compile(r"^unlock.*chapter\s*$", re.IGNORECASE),
    re.compile(r"^locked chapter\s*$", re.IGNORECASE),
    re.compile(r"^read more at\b", re.IGNORECASE),
    re.compile(r"^visit.*for the latest", re.IGNORECASE),
    re.compile(r"^the source of this content is\b", re.IGNORECASE),
    re.compile(r"^this content is taken from", re.IGNORECASE),
    re.compile(r"^please read this on the (original|official)", re.IGNORECASE),
    re.compile(r"^if you want to read more chapters.*follow.*on", re.IGNORECASE),
]


def _strip_ui_navigation_text(text: str) -> str:
    """Xóa các dòng rác giao diện web cố định (static UI navigation patterns)."""
    if not text:
        return text
    lines = text.splitlines()
    result = [
        line for line in lines
        if not any(p.match(line.strip()) for p in _UI_NAV_PATTERNS)
    ]
    candidate = "\n".join(result)
    return candidate if len(candidate.strip()) >= _MIN_REMAINING else text


# ── Pass 6: Broken bold pattern fix ───────────────────────────────────────────

_BROKEN_BOLD_RE = re.compile(r"\*\*([^*\n]+?)[ \t]+\*\*")


def _fix_broken_bold(text: str) -> str:
    """Chuyển khoảng trắng ở cuối cụm in đậm ra ngoài (**foo: ** -> **foo:** )."""
    if not text or "**" not in text:
        return text
    return _BROKEN_BOLD_RE.sub(r"**\1** ", text)


# ── Pass 7: Status box reformat ───────────────────────────────────────────────

_STATUS_LINE_PATTERNS = [
    re.compile(r"^\s*\*\*([^*\n]+?):\*\*\s*(.*?)\s*$"),
    re.compile(r"^\s*\*\*([^*\n]+?)\*\*\s*[:=]\s*(.+?)\s*$"),
    re.compile(r"^\s*\*\*([^*\n]+?)\*\*\s*([^\s*][^*\n]*)\s*$"),
    re.compile(r"^\s*\*\*([^*\n]+?)\*\*\s*$"),
]

_MIN_STATUS_CLUSTER = 3
_STATUS_LINE_MAX_LEN = 160
_BRIDGE_LABEL_RE = re.compile(r"^\s*[A-Z][A-Za-z 0-9()/\-]{0,40}:\s*$")
_BRIDGE_DECORATION_RE = re.compile(r"^[^\w\n]{1,10}$", re.UNICODE)


def _match_status_line(line: str) -> tuple[str, str] | None:
    if len(line) > _STATUS_LINE_MAX_LEN:
        return None
    for p in _STATUS_LINE_PATTERNS:
        m = p.match(line)
        if m:
            label = m.group(1).strip()
            value = m.group(2).strip() if m.lastindex and m.lastindex >= 2 else ""
            value = re.sub(r"^\*+|\*+$", "", value).strip()
            return (label, value)
    return None


def _is_bridge_label(line: str) -> bool:
    return bool(_BRIDGE_LABEL_RE.match(line))


def _is_bridge_decoration(line: str) -> bool:
    s = line.strip()
    return bool(s) and bool(_BRIDGE_DECORATION_RE.match(s))


def _next_status_within(lines: list[str], start: int, window: int) -> bool:
    for k in range(start, min(start + window, len(lines))):
        if _match_status_line(lines[k]) is not None:
            return True
        s = lines[k].strip()
        if s == "":
            continue
        if _is_bridge_decoration(s):
            continue
        return False
    return False


def _wrap_status_blocks(text: str) -> str:
    """Gói các cụm 3+ dòng trạng thái liên tiếp vào Obsidian callout `> [!info]+ Status`."""
    if not text or "**" not in text:
        return text

    lines = text.splitlines()
    out: list[str] = []
    i = 0

    while i < len(lines):
        cluster: list[tuple[str, str] | None] = []
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
                and _next_status_within(lines, j + 1, 4)
            ):
                cluster.append(None)
                j += 1
            elif (
                _is_bridge_label(line)
                and cluster
                and j + 1 < len(lines)
                and _match_status_line(lines[j + 1]) is not None
            ):
                cluster.append((line.strip().rstrip(":"), ""))
                j += 1
            elif (
                _is_bridge_decoration(line)
                and cluster
                and _next_status_within(lines, j + 1, 4)
            ):
                j += 1
            else:
                break

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
            out.append("")
            i = j
        else:
            out.append(lines[i])
            i += 1

    return "\n".join(out)


# ── Main Entry: clean_extracted_content ───────────────────────────────────────

def clean_extracted_content(text: str) -> str:
    """Áp dụng toàn bộ các pass làm sạch văn bản theo thứ tự.

    Quy tắc an toàn: không bao giờ xóa quá 60% văn bản gốc (_MAX_STRIP_RATIO = 0.60).
    """
    if not text or len(text.strip()) < _MIN_REMAINING:
        return text

    original_len = len(text.strip())
    result = text

    result = _strip_raw_script_lines(result)      # Pass 0
    result = _strip_unicode_blank_lines(result)   # Pass 0b
    result = _strip_comment_section(result)       # Pass 1
    result = _strip_settings_panel(result)        # Pass 2
    result = _strip_postfix_section(result)       # Pass 3
    result = _strip_metadata_header(result)       # Pass 4
    result = _strip_ui_navigation_text(result)    # Pass 5
    result = _fix_broken_bold(result)             # Pass 6
    result = _wrap_status_blocks(result)          # Pass 7

    cleaned_len = len(result.strip())

    # Trần an toàn: nếu bị cắt > 60% -> giữ nguyên bản gốc
    if cleaned_len < original_len * (1 - _MAX_STRIP_RATIO):
        return text

    return result.strip() if result.strip() else text


# ── Nav Edges & Duplicate Title ───────────────────────────────────────────────

_RE_WORD_COUNT = re.compile(
    r"^\[\s*[\d,.\s]+words?\s*\]$|^\[\s*\.+\s*words?\s*\]$",
    re.IGNORECASE,
)


def strip_nav_edges(text: str) -> str:
    """Xóa navigation/boilerplate text ở đầu và cuối chapter content."""
    lines = text.splitlines()
    n = len(lines)

    if n < 8:
        return text

    edge = _NAV_EDGE_SCAN
    top_set = {lines[i].strip() for i in range(min(edge, n)) if lines[i].strip()}
    bot_set = {lines[n - 1 - i].strip() for i in range(min(edge, n)) if lines[n - 1 - i].strip()}
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
    for i in range(min(edge, n)):
        if _is_nav(lines[i]):
            start = i + 1
        else:
            break
    while start < n and not lines[start].strip():
        start += 1

    end = n
    for i in range(min(edge, n)):
        idx = n - 1 - i
        if idx <= start:
            break
        if not lines[idx].strip() or _is_nav(lines[idx]):
            end = idx
        else:
            break
    while end > start and not lines[end - 1].strip():
        end -= 1

    return "\n".join(lines[start:end]) if start < end else text


def strip_duplicate_title_header(content: str, title: str | None) -> str:
    """Xóa dòng tiêu đề ở đầu content nếu trùng với title đã bóc tách (NovelFire pattern)."""
    if not content or not title or not title.strip():
        return content
    lines = content.split("\n")
    if not lines:
        return content
    first_line = lines[0].strip().lstrip("#").strip()
    if first_line and first_line.lower() == title.strip().lower():
        return "\n".join(lines[1:]).lstrip("\n")
    return content
