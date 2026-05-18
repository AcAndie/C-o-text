"""
ingest/epub.py — EPUB input adapter (P3.4).

v1.0.14: TOC-driven chapter plan (ingest/epub_structure). Front + back matter
docs merged into a single index-0 RawDocument titled "Front Matter".
Continuation spine docs (not in TOC, between TOC chapters) merged into
preceding chapter.

v1.1.1: No-TOC fallback — EPUBs without table of contents (vd txt→epub
converters dump everything into single HTML) get pattern-split via TXT
chapter detection (Chương N / Chapter N regex + AI fallback). Triggers
when plan has 0 real chapters (only matter bucket).

Decision #22 (BLUEPRINT §6 "Route: EPUB"):
  Naming via Dublin Core metadata first.

Yields:
  RawDocument per chapter plan entry. `metadata`:
    - story_name      : Dublin Core title
    - kind            : "chapter" | "matter"
    - toc_title       : TOC entry title (if matched) — orchestrator title hint
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, AsyncIterator

from bs4 import BeautifulSoup
from ebooklib import epub

from ingest.types import RawDocument
from ingest.epub_structure import build_chapter_plan

if TYPE_CHECKING:
    from ai.client import AIRateLimiter

logger = logging.getLogger(__name__)


# Legacy filename heuristic — kept for back-compat tests; planner uses richer rules.
SKIP_PATTERNS = ("toc", "cover", "copyright", "title", "nav", "front")

# v1.1.1: minimum chapter count to accept no-TOC pattern split. Less than this
# = pattern too sparse, likely false positive (e.g. matches metadata header).
_NO_TOC_MIN_CHAPTERS = 5


async def ingest_epub(
    path       : str,
    plan       : list | None = None,
    ai_limiter : "AIRateLimiter | None" = None,
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

    # v1.1.1: No-TOC fallback. EPUB with no TOC produces plan = [matter_bucket]
    # (1 entry containing all spine docs). Try pattern-split via TXT detection.
    real_chapter_count = sum(1 for p in plan if p.kind == "chapter")
    if real_chapter_count == 0 and plan and plan[0].kind == "matter":
        body_text = _extract_doc_text(book, plan[0].doc_ids)
        if body_text and len(body_text) > 1000:
            split_chapters = await _try_no_toc_split(body_text, ai_limiter)
            if split_chapters:
                print(
                    f"  [EPUB] 📖 No-TOC EPUB → pattern-split {len(split_chapters)} chapters",
                    flush=True,
                )
                for idx, title, body in split_chapters:
                    meta = dict(base_meta)
                    meta["kind"]      = "chapter"
                    meta["toc_title"] = title
                    yield RawDocument(
                        chapter_index = idx,
                        html          = _wrap_chapter_html(title, body),
                        source_path   = source_path,
                        metadata      = meta,
                    )
                return
            else:
                print(
                    f"  [EPUB] ⚠ No-TOC EPUB + pattern detect failed → "
                    f"emit as single Front Matter",
                    flush=True,
                )

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


# ── v1.1.1: No-TOC pattern split helpers ─────────────────────────────────────

def _extract_doc_text(book: epub.EpubBook, doc_ids: list[str]) -> str:
    """Plain text from concatenated docs. Preserves line breaks so chapter
    boundary headings (vd '<p>Chapter 1</p>' → 'Chapter 1\\n') are detectable
    by TXT regex."""
    parts: list[str] = []
    for doc_id in doc_ids:
        item = book.get_item_with_id(doc_id)
        if item is None:
            continue
        try:
            raw = item.get_content().decode("utf-8", errors="replace")
        except Exception:
            continue
        soup = BeautifulSoup(raw, "html.parser")
        body = soup.find("body") or soup
        # separator="\n" critical — chapter headings in <p>/<h*> tags become
        # standalone lines so anchored regex `^Chapter \d+$` matches.
        text = body.get_text(separator="\n", strip=True)
        if text:
            parts.append(text)
    return "\n\n".join(parts)


async def _try_no_toc_split(
    body_text  : str,
    ai_limiter : "AIRateLimiter | None",
) -> list[tuple[int, str, str]] | None:
    """Detect chapter pattern (regex → AI fallback), split body. Return
    list[(idx, title, body)] or None if pattern detection fails / produces
    too few chapters."""
    from ingest.txt import detect_pattern_regex, split_into_chapters

    # Regex first (sync, instant). AI fallback only if regex returns nothing —
    # avoids unnecessary AI cost on common cases (English/Vietnamese).
    case = detect_pattern_regex(body_text)
    if case is None and ai_limiter is not None:
        try:
            from ingest.txt import detect_pattern
            case = await detect_pattern(body_text, ai_limiter=ai_limiter)
        except Exception as e:
            logger.warning("[EPUB no-TOC] AI pattern detect failed: %s", e)
            return None
    if case is None:
        return None

    chapters = split_into_chapters(body_text, case)
    if len(chapters) < _NO_TOC_MIN_CHAPTERS:
        logger.info(
            "[EPUB no-TOC] only %d chapters from pattern %r — below min %d",
            len(chapters), case.get("id"), _NO_TOC_MIN_CHAPTERS,
        )
        return None
    return chapters


def _wrap_chapter_html(title: str, body: str) -> str:
    """Reuse TXT HTML wrapper — produces <article><h1>title</h1><p>body</p>"""
    from ingest.txt import _build_chapter_html
    return _build_chapter_html(title, body)


__all__ = ["RawDocument", "ingest_epub", "SKIP_PATTERNS"]
