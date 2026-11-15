"""translation.py — Bộ ghi file plain text (.txt) cho luồng dịch máy.

Đặc điểm:
  - Tên file: `0042.txt` (chỉ số index 4 chữ số, không kèm slug tiêu đề).
  - Không có YAML frontmatter.
  - Dòng đầu tiên: tiêu đề chương dạng plain text (không tiền tố `# `).
  - Dòng thứ 2: dòng trống.
  - Thân bài: đã loại bỏ toàn bộ cú pháp Markdown (in đậm, in nghiêng, link, heading, blockquote).
  - Ảnh: thay thế bằng placeholder `[IMAGE: alt]`.
"""
from __future__ import annotations

import re
from pathlib import Path

from cao_text.models import CleanedChapter
from cao_text.writers.base import ChapterWriter

CHUNK_THRESHOLD = 0

_RE_IMG_MD = re.compile(r"!\[([^\]]*)\]\([^)]*\)")
_RE_LINK = re.compile(r"(?<!!)\[([^\]]+)\]\([^)]*\)")
_RE_BOLD_STAR = re.compile(r"\*\*(.+?)\*\*", re.DOTALL)
_RE_BOLD_UND = re.compile(r"__(.+?)__", re.DOTALL)
_RE_ITAL_STAR = re.compile(r"(?<!\*)\*([^*\s][^*\n]*?[^*\s]|[^*\s])\*(?!\*)")
_RE_ITAL_UND = re.compile(r"(?<!_)_([^_\s][^_\n]*?[^_\s]|[^_\s])_(?!_)")
_RE_HEADING = re.compile(r"^#{1,6}\s+", re.MULTILINE)
_RE_BLOCKQUOTE = re.compile(r"^>\s*", re.MULTILINE)
_RE_MULTI_BLANK = re.compile(r"\n{3,}")


class TranslationWriter(ChapterWriter):
    """Bộ ghi file text cho downstream translation."""

    async def write(self, chapter: CleanedChapter) -> Path:
        filename = self.filename_for(chapter)
        path = self.output_dir / filename
        content = self._build_content(chapter)
        await self._write_atomic(path, content)
        return path

    def filename_for(self, chapter: CleanedChapter) -> str:
        return f"{chapter.index:04d}.txt"

    def _build_content(self, chapter: CleanedChapter) -> str:
        body = chapter.body_markdown or ""

        # Bỏ dòng heading # {title} ở đầu nếu có
        lines = body.split("\n", 2)
        if lines and _RE_HEADING.match(lines[0]):
            body = "\n".join(lines[1:]).lstrip("\n")

        body = self._strip_markdown(body)

        title_line = (chapter.title or f"Chapter {chapter.index}").strip()
        return f"{title_line}\n\n{body}".rstrip() + "\n"

    @staticmethod
    def _strip_markdown(text: str) -> str:
        """Loại bỏ cú pháp Markdown nhưng giữ cấu trúc đoạn văn."""
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
