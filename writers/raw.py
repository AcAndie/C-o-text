"""
writers/raw.py — RawWriter (P4.2).

Rawest cleaned text — strip ALL markdown syntax + drop image entirely
(không placeholder). Notepad-friendly, smallest file size trong 3 modes.

Output convention:
  Filename:    NNNN.txt
  Frontmatter: none
  First line:  plain title
  Blank line
  Body:        markdown-stripped, image dropped entirely
  Paragraph:   spacing giữ nguyên (double newline → double newline)

Difference từ TranslationWriter:
  - Image `![alt](url)` → "" (dropped), không `[IMAGE: alt]` placeholder
  - Otherwise identical strip rules (bold/italic/link/heading/blockquote)
"""
from __future__ import annotations

import re
from pathlib import Path

from pipeline.base import CleanedChapter
from writers.base  import ChapterWriter


# Image: `![alt](url)` → dropped entirely
_RE_IMG_MD = re.compile(r"!\[[^\]]*\]\([^)]*\)")

# Link: `[text](url)` → `text` (preserve text content, drop URL)
_RE_LINK = re.compile(r"(?<!!)\[([^\]]+)\]\([^)]*\)")

# Bold / italic
_RE_BOLD_STAR = re.compile(r"\*\*(.+?)\*\*", re.DOTALL)
_RE_BOLD_UND  = re.compile(r"__(.+?)__", re.DOTALL)
_RE_ITAL_STAR = re.compile(r"(?<!\*)\*([^*\s][^*\n]*?[^*\s]|[^*\s])\*(?!\*)")
_RE_ITAL_UND  = re.compile(r"(?<!_)_([^_\s][^_\n]*?[^_\s]|[^_\s])_(?!_)")

# Heading / blockquote prefix per line
_RE_HEADING    = re.compile(r"^#{1,6}\s+", re.MULTILINE)
_RE_BLOCKQUOTE = re.compile(r"^>\s*", re.MULTILINE)

# Empty lines left từ stripped image — collapse 3+ → 2
_RE_MULTI_BLANK = re.compile(r"\n{3,}")


class RawWriter(ChapterWriter):
    """Plain text writer — minimal noise, image dropped entirely."""

    async def write(self, chapter: CleanedChapter) -> Path:
        filename = self.filename_for(chapter)
        path     = Path(self.output_dir) / filename
        content  = self._build_content(chapter)
        await self._atomic_write_text(path, content)
        return path

    def filename_for(self, chapter: CleanedChapter) -> str:
        return f"{chapter.index:04d}.txt"

    # ── Internals ─────────────────────────────────────────────────────────────

    def _build_content(self, chapter: CleanedChapter) -> str:
        body = chapter.body_markdown or ""

        # Drop `# {title}` first line (scraper prepends; title in metadata)
        lines = body.split("\n", 2)
        if lines and _RE_HEADING.match(lines[0]):
            body = "\n".join(lines[1:]).lstrip("\n")

        body = self._strip_markdown(body)

        title_line = (chapter.title or f"Chapter {chapter.index}").strip()
        return f"{title_line}\n\n{body}".rstrip() + "\n"

    @staticmethod
    def _strip_markdown(text: str) -> str:
        text = _RE_IMG_MD.sub("", text)         # drop image entirely (NO placeholder)
        text = _RE_LINK.sub(r"\1", text)
        text = _RE_BOLD_STAR.sub(r"\1", text)
        text = _RE_BOLD_UND.sub(r"\1", text)
        text = _RE_ITAL_STAR.sub(r"\1", text)
        text = _RE_ITAL_UND.sub(r"\1", text)
        text = _RE_HEADING.sub("", text)
        text = _RE_BLOCKQUOTE.sub("", text)
        text = _RE_MULTI_BLANK.sub("\n\n", text)
        return text


__all__ = ["RawWriter"]
