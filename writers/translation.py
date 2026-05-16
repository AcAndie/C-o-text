"""
writers/translation.py — TranslationWriter (P4.1).

Plain text output cho translation pipeline downstream (Gemini / Claude /
GPT). Strip Markdown formatting noise — translator wants raw prose, not
syntax noise like `**bold**` hoặc `# heading`.

Output convention:
  Filename:    NNNN.txt (no chapter slug — index only)
  Frontmatter: none
  First line:  plain title text ("Chapter 42: The Storm" — no `# ` prefix)
  Blank line
  Body:        markdown-stripped paragraphs, 1 paragraph per line,
               double newline between paragraphs
  Image:       [IMAGE: alt] placeholder inline

Chunking (Decision P4.1 — Option A):
  CHUNK_THRESHOLD = 0 (default OFF). Modern LLM context windows
  (Gemini 1M, Claude 200K, GPT-4o 128K) handle 30k chars fine. User
  splits downstream nếu cần.
  Future: configurable via RunConfig.chunk_threshold (P4 ship hoặc v1.1).

Defensive markdown strip:
  - Web flow: scraper._apply_image_stage rewrite `![alt](placeholder)`
    → `[IMAGE: alt]` cho translate mode TRƯỚC khi tới writer.
  - EPUB flow (P4 ship): orchestrator phải làm tương tự. Hiện P4.1 writer
    cũng strip image markdown defensively — nếu `![alt](url)` còn sót,
    convert thành `[IMAGE: alt]` tại writer.

Title placement (Decision P4.1):
  Keep title as plain first line (NO `# ` prefix). Translator wants
  context ("Chương 42: Tiêu đề" + body), không drop title.
"""
from __future__ import annotations

import re
from pathlib import Path

from pipeline.base import CleanedChapter
from writers.base import ChapterWriter


CHUNK_THRESHOLD = 0   # OFF default — see module docstring


# ── Markdown strip regexes ────────────────────────────────────────────────────

# Image: `![alt](url)` → `[IMAGE: alt]` (defensive — scraper usually pre-rewrites)
_RE_IMG_MD = re.compile(r"!\[([^\]]*)\]\([^)]*\)")

# Link: `[text](url)` → `text` (NOT preceded by `!`)
_RE_LINK = re.compile(r"(?<!!)\[([^\]]+)\]\([^)]*\)")

# Bold: `**text**` hoặc `__text__` → `text`. Non-greedy để handle nested
# (`**bold *italic* mixed**` → capture `bold *italic* mixed`, italic pass
# strip inner sau).
_RE_BOLD_STAR = re.compile(r"\*\*(.+?)\*\*", re.DOTALL)
_RE_BOLD_UND  = re.compile(r"__(.+?)__", re.DOTALL)

# Italic: `*text*` hoặc `_text_` → `text`. Phải sau bold pass (greedy
# `*x*y*` tránh ăn nhầm bold marker). Italic không match khoảng trắng đầu/cuối.
_RE_ITAL_STAR = re.compile(r"(?<!\*)\*([^*\s][^*\n]*?[^*\s]|[^*\s])\*(?!\*)")
_RE_ITAL_UND  = re.compile(r"(?<!_)_([^_\s][^_\n]*?[^_\s]|[^_\s])_(?!_)")

# Heading: line starting với 1-6 `#` + space
_RE_HEADING = re.compile(r"^#{1,6}\s+", re.MULTILINE)

# Blockquote: leading `> ` per line
_RE_BLOCKQUOTE = re.compile(r"^>\s*", re.MULTILINE)

# 3+ consecutive blank lines → 2 (double newline = paragraph separator)
_RE_MULTI_BLANK = re.compile(r"\n{3,}")


class TranslationWriter(ChapterWriter):
    """
    Plain text writer cho downstream translation tools. Strip Markdown
    noise, preserve paragraph structure.
    """

    async def write(self, chapter: CleanedChapter) -> Path:
        filename = self.filename_for(chapter)
        path     = Path(self.output_dir) / filename
        content  = self._build_content(chapter)
        await self._atomic_write_text(path, content)
        return path

    def filename_for(self, chapter: CleanedChapter) -> str:
        """`NNNN.txt` — index-only, no title slug. Spec P4.1."""
        return f"{chapter.index:04d}.txt"

    # ── Internals ─────────────────────────────────────────────────────────────

    def _build_content(self, chapter: CleanedChapter) -> str:
        """
        Title (plain) → blank line → markdown-stripped body.

        Body strip order matters: image trước link (image regex preceded
        by `!`, link explicitly excludes). Bold trước italic (avoid
        `**x**` bị italic regex ăn).
        """
        body = chapter.body_markdown or ""

        # Drop `# {title}` header line (scraper prepends `# {title}\n\n{content}`).
        # Title preserved separately as plain first line below.
        lines = body.split("\n", 2)
        if lines and _RE_HEADING.match(lines[0]):
            body = "\n".join(lines[1:]).lstrip("\n")

        body = self._strip_markdown(body)

        title_line = (chapter.title or f"Chapter {chapter.index}").strip()
        return f"{title_line}\n\n{body}".rstrip() + "\n"

    @staticmethod
    def _strip_markdown(text: str) -> str:
        """Apply strip regexes in safe order."""
        text = _RE_IMG_MD.sub(lambda m: f"[IMAGE: {m.group(1)}]", text)
        text = _RE_LINK.sub(r"\1", text)
        text = _RE_BOLD_STAR.sub(r"\1", text)
        text = _RE_BOLD_UND.sub(r"\1", text)
        text = _RE_ITAL_STAR.sub(r"\1", text)
        text = _RE_ITAL_UND.sub(r"\1", text)
        text = _RE_HEADING.sub("", text)
        text = _RE_BLOCKQUOTE.sub("", text)
        text = _RE_MULTI_BLANK.sub("\n\n", text)
        return text


__all__ = ["TranslationWriter", "CHUNK_THRESHOLD"]
