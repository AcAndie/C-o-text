"""
ingest/epub.py — EPUB input adapter (P3.4).

v1.0.14: TOC-driven chapter plan (ingest/epub_structure). Front + back matter
docs merged into a single index-0 RawDocument titled "Front Matter".
Continuation spine docs (not in TOC, between TOC chapters) merged into
preceding chapter.

Decision #22 (BLUEPRINT §6 "Route: EPUB"):
  Naming via Dublin Core metadata first.

Yields:
  RawDocument per chapter plan entry. `metadata`:
    - story_name      : Dublin Core title
    - kind            : "chapter" | "matter"
    - toc_title       : TOC entry title (if matched) — orchestrator title hint
"""
from __future__ import annotations

from pathlib import Path
from typing import AsyncIterator

from bs4 import BeautifulSoup
from ebooklib import epub

from ingest.types import RawDocument
from ingest.epub_structure import build_chapter_plan


# Legacy filename heuristic — kept for back-compat tests; planner uses richer rules.
SKIP_PATTERNS = ("toc", "cover", "copyright", "title", "nav", "front")


async def ingest_epub(
    path : str,
    plan : list | None = None,
) -> AsyncIterator[RawDocument]:
    """
    Yield RawDocument per chapter from TOC-driven plan.

    Args:
        path: absolute / relative path to .epub file.
        plan: optional pre-built ChapterPlan list (from build_chapter_plan or
              build_chapter_plan_with_ai). If None, defaults to rule-based plan.

    Raises:
        ebooklib.epub.EpubException if file corrupt / not EPUB.
        FileNotFoundError if path invalid.
    """
    book = epub.read_epub(path)

    title_meta  = book.get_metadata("DC", "title")
    story_name  = title_meta[0][0] if title_meta else None
    source_path = str(Path(path).resolve())
    base_meta   = {"story_name": story_name} if story_name else {}

    if plan is None:
        plan = build_chapter_plan(book)

    for entry in plan:
        # Extract <body> inner content per doc, gộp dưới 1 <body> wrapper.
        # Fix v1.0.15: parsing multi-`<html>...<body>...` documents directly
        # caused BS4 to nest subsequent docs as siblings of first body,
        # `soup.find('body')` returned only first (often near-empty) body.
        body_chunks: list[str] = []
        for doc_id in entry.doc_ids:
            item = book.get_item_with_id(doc_id)
            if item is None:
                continue
            try:
                raw = item.get_content().decode("utf-8", errors="replace")
            except Exception:
                continue

            doc_soup = BeautifulSoup(raw, "html.parser")
            doc_body = doc_soup.find("body")
            if doc_body is not None:
                inner = "".join(str(c) for c in doc_body.children)
            else:
                inner = raw
            if inner.strip():
                body_chunks.append(inner)

        if not body_chunks:
            continue

        if len(body_chunks) > 1:
            merged_body = "\n<hr/>\n".join(body_chunks)
        else:
            merged_body = body_chunks[0]

        merged_html = f"<html><body>{merged_body}</body></html>"

        meta = dict(base_meta)
        meta["kind"] = entry.kind
        if entry.title:
            meta["toc_title"] = entry.title

        yield RawDocument(
            chapter_index = entry.index,
            html          = merged_html,
            source_path   = source_path,
            metadata      = meta,
        )


__all__ = ["RawDocument", "ingest_epub", "SKIP_PATTERNS"]
