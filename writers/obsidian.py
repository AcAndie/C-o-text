"""
writers/obsidian.py — ObsidianWriter (P1.4).

Port từ core/chapter_writer.py. Output: Markdown chuẩn với YAML frontmatter,
filename `0042_Chapter_Title.md`, footer `> Source: {url}` cho web mode.

EXACT behavior preservation từ format_chapter_filename:
  - Garbage subtitle guard (FILENAME-C)
  - Site suffix stripping (FILENAME-E)
  - Slugify Vietnamese qua utils.string_helpers.slugify_filename
  - lru_cache regex (P2-11)

Naming context (chapter_keyword, story_prefix_strip) lấy từ
CleanedChapter.metadata. P1.5 refactor caller sẽ inject các field này khi
build DTO.

core/chapter_writer.py KEEP cho đến P1.5 — callers cũ chưa migrate.
"""
from __future__ import annotations

from pathlib import Path

from pipeline.base       import CleanedChapter
from writers.base        import ChapterWriter
from core.chapter_writer import format_chapter_filename


# Metadata keys được include trong frontmatter (mặc định)
_FRONTMATTER_META_KEYS = ("story_name", "language", "author")


class ObsidianWriter(ChapterWriter):
    """
    Markdown writer ready cho Obsidian vault. YAML frontmatter + body +
    optional source footer.
    """

    async def write(self, chapter: CleanedChapter) -> Path:
        filename = self.filename_for(chapter)
        path     = Path(self.output_dir) / filename
        content  = self._build_content(chapter)
        self._atomic_write_text(path, content)
        return path

    def filename_for(self, chapter: CleanedChapter) -> str:
        """
        Reuse format_chapter_filename() từ core/chapter_writer.py — preserve
        EXACT behavior (garbage detection, site suffix strip, slugify).

        Naming context (chapter_keyword + story_prefix_strip) read từ
        chapter.metadata. Default safe nếu metadata thiếu.
        """
        progress_like = {
            "chapter_keyword"   : chapter.metadata.get("chapter_keyword")    or "Chapter",
            "story_prefix_strip": chapter.metadata.get("story_prefix_strip") or "",
        }
        return format_chapter_filename(chapter.index, chapter.title, progress_like)  # type: ignore[arg-type]

    # ── Internals ─────────────────────────────────────────────────────────────

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

        # Failed image log (chỉ web — EPUB không fail HTTP)
        failed_imgs = [
            img.original_url for img in chapter.images
            if img.local_path is None and img.source_type == "web"
        ]
        if failed_imgs:
            lines.append(f"failed_images: {failed_imgs}")

        lines.append("---")
        lines.append("")
        lines.append(chapter.body_markdown)

        if chapter.source_url and self.run_config.output_mode == "obsidian":
            lines.append("")
            lines.append(f"> Source: {chapter.source_url}")

        return "\n".join(lines)
