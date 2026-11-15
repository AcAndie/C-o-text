"""obsidian.py — Bộ ghi Markdown chuẩn cho Obsidian Vault kèm YAML frontmatter.

Đặc điểm:
  - Tên file: `0042_Chapter_Title.md` qua `format_chapter_filename`.
  - YAML frontmatter: title, chapter_index, source_url / source_path, story_name, author, language, failed_images.
  - Lùi đầu dòng đoạn văn (indent paragraphs) bằng U+2003 em-space cho dòng đầu của đoạn văn thường.
  - Không lùi đầu dòng cho heading (#), blockquote/callout (>), danh sách (-, *, 1.), bảng (|), hr (---), ảnh (![), code block.
"""
from __future__ import annotations

import functools
import re
import unicodedata
from pathlib import Path
from typing import Any

from cao_text.extract.title import strip_site_suffix
from cao_text.models import CleanedChapter
from cao_text.writers.base import ChapterWriter

_FRONTMATTER_META_KEYS = ("story_name", "language", "author")

# Em-space (U+2003) lùi đầu dòng trực quan mà không bị CommonMark coi là 4 spaces code block
_PARA_INDENT = " "

_NO_INDENT_RE = re.compile(
    r"^("
    r"\s*#"               # heading
    r"|\s*>"              # blockquote / callout
    r"|\s*[-*+]\s"        # bullet list
    r"|\s*\d+\.\s"        # numbered list
    r"|\s*---\s*$"        # HR
    r"|\s*\|"             # table row
    r"|\s*<!--"           # HTML comment
    r"|\s*!\["            # image-only line
    r")"
)

# ── Slugify Filename Helpers ──────────────────────────────────────────────────

_SLUG_REPLACE = {
    "–": "-", "—": "-", "…": "...", "‘": "'", "’": "'",
    "\u201c": '"', "\u201d": '"', "«": '"', "»": '"',
    "×": "x", "÷": "-", "©": "", "®": "", "™": "",
    "→": "-", "←": "-", "↑": "", "↓": "",
    "★": "", "☆": "", "♥": "", "♦": "", "♠": "", "♣": "",
    "•": "-", "·": "-", "。": ".", "，": ",",
}

_SLUG_UNSAFE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_SLUG_SPACES = re.compile(r"[\s_]+")
_SLUG_DOTS = re.compile(r"\.{2,}")
_SLUG_EDGES = re.compile(r"^[\s.\-_]+|[\s.\-_]+$")
_WIN_RESERVED = re.compile(r"^(CON|PRN|AUX|NUL|COM[0-9]|LPT[0-9])$", re.IGNORECASE)


def slugify_filename(text: str, max_len: int = 80) -> str:
    """Chuyển đổi chuỗi text thành tên file an toàn cho hệ thống tập tin (đặc biệt là Windows)."""
    if not text:
        return "untitled"
    text = unicodedata.normalize("NFKC", text)
    for src, dst in _SLUG_REPLACE.items():
        text = text.replace(src, dst)
    text = _SLUG_UNSAFE.sub("", text)
    text = _SLUG_SPACES.sub("_", text)
    text = _SLUG_DOTS.sub(".", text)
    text = _SLUG_EDGES.sub("", text)
    if len(text) > max_len:
        text = text[:max_len]
        text = _SLUG_EDGES.sub("", text)
    if not text:
        return "untitled"
    stem = text.rsplit(".", 1)[0] if "." in text else text
    if _WIN_RESERVED.match(stem):
        text = text + "_file"
    return text


# ── Filename Formatting Helpers ───────────────────────────────────────────────

_RE_PIPE_SUFFIX = re.compile(r"\s*\|.*$")
_RAW_TITLE_MAX_LEN = 200

_GARBAGE_SUBTITLE_PATTERNS = (
    re.compile(r"^a\s+\S.{2,70}\s+fanfic(?:tion)?\s*$", re.IGNORECASE),
    re.compile(r"^translated\s+by\b", re.IGNORECASE),
    re.compile(r"^edited\s+by\b", re.IGNORECASE),
    re.compile(r"^(?:official\s+)?(?:epub|pdf|translation)\b", re.IGNORECASE),
)


def _is_garbage_subtitle(sub: str) -> bool:
    """Kiểm tra subtitle có phải rác không (fanfic descriptor, dịch giả, format file)."""
    if not sub or len(sub) < 2:
        return True
    for pat in _GARBAGE_SUBTITLE_PATTERNS:
        if pat.match(sub.strip()):
            return True
    if len(sub) > 60 and not re.search(r"[.!?,;:'\"()]", sub):
        return True
    return False


@functools.lru_cache(maxsize=32)
def _get_chapter_re(chapter_kw: str) -> re.Pattern:
    """Tạo và cache biểu thức chính quy cho chapter keyword."""
    kw_esc = re.escape(chapter_kw)
    return re.compile(
        rf"(?:{kw_esc})\s*(?P<n>\d+)\s*[-–—:.]?\s*(?P<sub>.*)",
        re.IGNORECASE,
    )


def format_chapter_filename(
    chapter_num: int,
    raw_title: str,
    progress_like: dict[str, Any] | None = None,
) -> str:
    """Tạo tên file .md chuẩn cho chương: `0042_Ten_Chuong.md`."""
    progress = progress_like or {}
    chapter_kw = (progress.get("chapter_keyword") or "Chapter").strip()
    prefix_strip = (progress.get("story_prefix_strip") or "").strip()

    title = raw_title.strip()

    if len(title) > _RAW_TITLE_MAX_LEN:
        title = title[:_RAW_TITLE_MAX_LEN]

    # Bóc story prefix nếu có
    if prefix_strip:
        lo_title = title.lower()
        lo_prefix = prefix_strip.lower()
        if lo_title.startswith(lo_prefix):
            title = title[len(prefix_strip):].lstrip(" ,;:-–—")

    # Bóc pipe suffix
    title = _RE_PIPE_SUFFIX.sub("", title).strip()

    m = _get_chapter_re(chapter_kw).search(title)

    if m:
        n = m.group("n")
        sub_raw = m.group("sub").strip()
        sub_raw = _RE_PIPE_SUFFIX.sub("", sub_raw).strip()
        # Bóc word count artifacts và site suffixes trước khi strip các dấu câu ở hai đầu
        sub_raw = strip_site_suffix(sub_raw).strip()
        sub_raw = sub_raw.strip(" ,-–—:[]().")

        if sub_raw and len(sub_raw) >= 2 and not _is_garbage_subtitle(sub_raw):
            name = f"{chapter_num:04d}_{slugify_filename(sub_raw, max_len=80)}"
        else:
            chap_id = f"{chapter_kw}{n}"
            name = f"{chapter_num:04d}_{chap_id}"
    else:
        fallback = (title or raw_title).strip()
        name = f"{chapter_num:04d}_{slugify_filename(fallback, max_len=80)}"

    return slugify_filename(name, max_len=120) + ".md"


def _indent_paragraphs(body: str) -> str:
    """Thêm U+2003 em-space vào dòng đầu của mỗi đoạn văn xuôi."""
    if not body:
        return body

    lines = body.split("\n")
    in_code = False
    prev_blank = True

    for i, line in enumerate(lines):
        stripped = line.lstrip()

        if stripped.startswith("```"):
            in_code = not in_code
            prev_blank = False
            continue

        if in_code:
            prev_blank = False
            continue

        if not line.strip():
            prev_blank = True
            continue

        if prev_blank and not _NO_INDENT_RE.match(line):
            lines[i] = _PARA_INDENT + line
        prev_blank = False

    return "\n".join(lines)


# ── ObsidianWriter Implementation ─────────────────────────────────────────────

class ObsidianWriter(ChapterWriter):
    """Bộ ghi file Markdown cho Obsidian Vault."""

    async def write(self, chapter: CleanedChapter) -> Path:
        filename = self.filename_for(chapter)
        path = self.output_dir / filename
        content = self._build_content(chapter)
        await self._write_atomic(path, content)
        return path

    def filename_for(self, chapter: CleanedChapter) -> str:
        progress_like = {
            "chapter_keyword": chapter.metadata.get("chapter_keyword") or "Chapter",
            "story_prefix_strip": chapter.metadata.get("story_prefix_strip") or "",
        }
        return format_chapter_filename(chapter.index, chapter.title, progress_like)

    def _build_content(self, chapter: CleanedChapter) -> str:
        lines: list[str] = ["---"]
        lines.append(f"title: {chapter.title!r}")
        lines.append(f"chapter_index: {chapter.index}")

        if chapter.source_url:
            lines.append(f"source_url: {chapter.source_url}")
        if chapter.source_path:
            lines.append(f"source_path: {chapter.source_path}")

        for key in _FRONTMATTER_META_KEYS:
            val = chapter.metadata.get(key)
            if val:
                lines.append(f"{key}: {val!r}")

        # Nhật ký ảnh tải thất bại
        failed_imgs = [
            img.original_url
            for img in chapter.images
            if img.local_path is None and img.source_type == "web"
        ]
        if failed_imgs:
            lines.append(f"failed_images: {failed_imgs}")

        lines.append("---")
        lines.append("")
        lines.append(_indent_paragraphs(chapter.body_markdown))

        return "\n".join(lines)
