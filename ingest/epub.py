"""
ingest/epub.py — EPUB input adapter (P3.4).

Parse EPUB via ebooklib, iterate spine, yield RawDocument per chapter.

Decision #22 (BLUEPRINT §6 "Route: EPUB"):
  Naming via Dublin Core metadata first — `book.get_metadata('DC', 'title')`.
  AI fallback (metadata trống) defer P3.6+ — current scope: trust source.

Spine iteration logic:
  - book.spine items can be (id, linear) tuple HOẶC plain string id.
  - get_item_with_id() returns None nếu id không match — skip.
  - get_type() != ITEM_DOCUMENT — skip (CSS, image, font, ...).
  - filename match SKIP_PATTERNS (toc/cover/copyright/title/nav/front) — skip.
    Heuristic — pirate EPUB thường có những file này ở đầu spine,
    không phải chapter thật.

P3.5 sẽ add EpubImageExtractor reuse `book` object — adapter này yield
RawDocument với `epub_book` reference qua metadata (hoặc orchestrator
hold book separately). Hiện tại P3.4 scope giới hạn: parse + yield.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import AsyncIterator

from ebooklib import ITEM_DOCUMENT, epub


@dataclass
class RawDocument:
    """
    Common contract giữa input adapter và pipeline core.

    Pipeline core không biết source — chỉ thấy chapter_index + html.
    `source_url` cho web, `source_path` cho epub/txt.
    `metadata` carry naming hint (story_name từ DC, ...) qua orchestrator
    về writer.
    """
    chapter_index: int
    html         : str
    source_url   : str | None       = None
    source_path  : str | None       = None
    metadata     : dict             = field(default_factory=dict)


# Filename heuristic — pirate EPUB thường có những file này ở đầu spine.
# Match substring, case-insensitive.
SKIP_PATTERNS = ("toc", "cover", "copyright", "title", "nav", "front")


async def ingest_epub(path: str) -> AsyncIterator[RawDocument]:
    """
    Yield RawDocument per chapter từ EPUB spine.

    Args:
        path: absolute hoặc relative path tới .epub file.

    Yields:
        RawDocument với chapter_index 1-based, html raw từ EpubHtml item.
        metadata['story_name'] set nếu Dublin Core title available.

    Raises:
        ebooklib.epub.EpubException nếu file corrupt / không phải EPUB.
        FileNotFoundError nếu path invalid.
    """
    book = epub.read_epub(path)

    # ── Naming via Dublin Core (Decision #22) ─────────────────────────────────
    title_meta = book.get_metadata("DC", "title")
    story_name = title_meta[0][0] if title_meta else None

    source_path = str(Path(path).resolve())
    base_meta   = {"story_name": story_name} if story_name else {}

    idx = 1
    for spine_entry in book.spine:
        # Spine entry: (id, linear_flag) tuple HOẶC plain id string
        item_id   = spine_entry[0] if isinstance(spine_entry, tuple) else spine_entry
        ebook_item = book.get_item_with_id(item_id)

        if ebook_item is None or ebook_item.get_type() != ITEM_DOCUMENT:
            continue

        filename = (ebook_item.file_name or "").lower()
        if any(p in filename for p in SKIP_PATTERNS):
            continue

        html = ebook_item.get_content().decode("utf-8", errors="replace")

        yield RawDocument(
            chapter_index = idx,
            html          = html,
            source_path   = source_path,
            metadata      = dict(base_meta),
        )
        idx += 1


__all__ = ["RawDocument", "ingest_epub", "SKIP_PATTERNS"]
