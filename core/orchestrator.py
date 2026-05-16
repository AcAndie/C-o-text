"""
core/orchestrator.py — Input-type router (P3.6).

Entry point cho mọi input. Detect type qua ingest.router, dispatch:
  - web  → existing core/scraper flow (main.py giữ nguyên, không refactor)
  - epub → run_epub_flow (new, ở đây)
  - txt  → NotImplementedError (Phase 5)

Phase 3 scope: web flow KHÔNG refactor — main.py vẫn gọi run_novel_task
trực tiếp cho input web. Orchestrator chỉ cần thiết khi input là EPUB.
main.py thêm early branch detect EPUB → run_epub_flow, web path
unchanged → zero regression risk.

EPUB flow:
  - read_epub once
  - Naming via Dublin Core (Decision #22)
  - Iterate spine via ingest_epub
  - Per chapter:
      * make_context với empty profile + prefetched html
      * build_soup (no remove_selectors, no protected selectors)
      * Manual chain run: Extract (DensityHeuristic etc) + Title
      * Skip Nav (EPUB không có next URL)
      * Skip Validate (LengthValidator có thể fail on legitimate short chapter)
      * content_cleaner pass
      * build_cleaned_chapter
      * Image stage (EpubImageExtractor) — nếu obsidian mode
      * writer.write
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from ebooklib import epub

from core.image_pipeline.epub_extractor import EpubImageExtractor
from ingest.epub                       import ingest_epub
from ingest.router                     import detect_input_type
from pipeline.base                     import CleanedChapter
from pipeline.executor                 import (
    ChainExecutor, PipelineRunner, build_cleaned_chapter, build_soup, make_context,
)
from utils.string_helpers              import slugify_filename
from writers.obsidian                  import ObsidianWriter

if TYPE_CHECKING:
    from ai.client       import AIRateLimiter
    from utils.types     import RunConfig

logger = logging.getLogger(__name__)


# ── Public dispatcher ─────────────────────────────────────────────────────────

async def run(
    input_path : str,
    run_config : "RunConfig",
    ai_limiter : "AIRateLimiter | None" = None,
) -> None:
    """
    Route input theo type. Web KHÔNG được handle ở đây — main.py giữ flow
    cũ cho web (Phase 3 scope, refactor defer Phase 6).
    """
    t = detect_input_type(input_path)
    if t == "epub":
        await run_epub_flow(input_path, run_config, ai_limiter=ai_limiter)
    elif t == "txt":
        raise NotImplementedError(
            "TXT adapter chưa implement — Phase 5. Hiện tại chỉ hỗ trợ web + epub."
        )
    elif t == "web":
        raise RuntimeError(
            "Web flow phải gọi qua main.py existing path, không qua orchestrator.run() "
            "(Phase 3 scope — Phase 6 sẽ refactor)."
        )
    else:
        raise ValueError(f"Unknown input type: {t!r}")


# ── EPUB flow ─────────────────────────────────────────────────────────────────

async def run_epub_flow(
    input_path : str,
    run_config : "RunConfig",
    ai_limiter : "AIRateLimiter | None" = None,
) -> None:
    """
    Read EPUB → iterate spine → run pipeline (extract + title) → image stage
    via EpubImageExtractor → writer.write.

    Skip:
      - Fetch chain (have prefetched html từ ebooklib)
      - Nav chain (no next URL trong EPUB)
      - Validate chain (LengthValidator có thể reject short chapter hợp lệ)
      - Naming Phase (DC metadata thay thế)
      - Learning Phase (EPUB structured HTML đủ cho DensityHeuristic)
      - AdsFilter (defer P3.7)
      - Progress/resume (defer P6+; atomic write idempotent)
    """
    if run_config.output_mode != "obsidian":
        raise NotImplementedError(
            f"Output mode {run_config.output_mode!r} chưa implement cho EPUB — "
            "chỉ obsidian khả dụng ở Phase 3. TranslationWriter/RawWriter defer Phase 4."
        )

    book = epub.read_epub(input_path)

    # ── Naming via Dublin Core (Decision #22) ─────────────────────────────────
    title_meta = book.get_metadata("DC", "title")
    story_name = (title_meta[0][0] if title_meta else None) or Path(input_path).stem
    story_slug = slugify_filename(story_name)

    out_dir = Path(run_config.output_dir) / story_slug
    out_dir.mkdir(parents=True, exist_ok=True)

    writer = ObsidianWriter(output_dir=str(out_dir), run_config=run_config)
    runner = PipelineRunner.default()   # empty profile — heuristic-only

    print(
        f"📖 EPUB: {story_name!r} → {out_dir}\n"
        f"   mode={run_config.output_mode} download_images={run_config.download_images}",
        flush=True,
    )

    n_ok      = 0
    n_skipped = 0

    async for doc in ingest_epub(input_path):
        try:
            chapter = await _build_chapter_from_epub_doc(
                doc        = doc,
                runner     = runner,
                run_config = run_config,
                ai_limiter = ai_limiter,
                story_name = story_name,
            )
        except Exception as e:
            logger.warning("[EPUB] chapter %d build failed: %s", doc.chapter_index, e)
            n_skipped += 1
            continue

        if chapter is None:
            n_skipped += 1
            continue

        # Image stage — obsidian mode only
        if chapter.images and run_config.download_images:
            extractor = EpubImageExtractor(book, chapter.index)
            try:
                await extractor.fetch_batch(chapter.images, str(out_dir))
            except Exception as e:
                logger.warning("[EPUB] image batch failed ch.%d: %s", chapter.index, e)
            chapter.body_markdown = _rewrite_epub_image_placeholders(
                chapter.body_markdown, chapter.images,
            )

        await writer.write(chapter)
        n_ok += 1

        if n_ok % 25 == 0:
            print(f"   ... {n_ok} chapters written", flush=True)

    print(f"\n✔ EPUB done: {n_ok} chapters written, {n_skipped} skipped → {out_dir}", flush=True)


# ── Per-chapter pipeline ──────────────────────────────────────────────────────

async def _build_chapter_from_epub_doc(
    doc,
    runner     : PipelineRunner,
    run_config : "RunConfig",
    ai_limiter : "AIRateLimiter | None",
    story_name : str,
) -> CleanedChapter | None:
    """
    Run Extract + Title chains manually (skip Fetch/Nav/Validate).
    Return None nếu content extract fail — caller skip ghi file.
    """
    from utils.content_cleaner import clean_extracted_content

    ctx = make_context(url=doc.source_path or "", profile={}, progress={})
    ctx.html = doc.html
    ctx.run_config = run_config
    # runtime: AI limiter optional cho AIExtractBlock fallback (hiếm khi hit)
    if ai_limiter is not None:
        ctx.runtime.ai_limiter = ai_limiter

    await build_soup(ctx)
    if ctx.soup is None:
        return None

    # Extract chain — first-wins từ profile rỗng = heuristics
    extract_result = await ChainExecutor(runner._extract_blocks(), "extract").run(ctx)
    if extract_result.ok and extract_result.data:
        ctx.content       = extract_result.data
        ctx.selector_used = extract_result.metadata.get("selector")
    else:
        # EPUB body fallback — DensityHeuristic fails on flat <body><h1><p>... structure
        # phổ biến trong EPUB. Format trực tiếp body element qua MarkdownFormatter.
        from core.formatter import MarkdownFormatter
        body_tag = ctx.soup.find("body") or ctx.soup
        formatter = MarkdownFormatter({})
        content, images = formatter.format(body_tag, base_url="")
        if not content.strip():
            return None
        ctx.content = content
        ctx.image_refs.extend(images)
        ctx.selector_used = "epub_body_fallback"

    ctx.content = clean_extracted_content(ctx.content)

    # Title chain — H1 thường winner cho EPUB chapter
    title_result = await ChainExecutor(runner._title_blocks(), "title").run(ctx)
    if title_result.ok:
        ctx.title_clean = title_result.data
        ctx.title_raw   = title_result.data
    else:
        ctx.title_clean = f"Chapter {doc.chapter_index}"

    # Title dedup — body fallback path includes <h1> trong content. Drop dòng đầu
    # nếu trùng title (same logic as core/scraper.py:303-307).
    content_lines = ctx.content.split("\n")
    if content_lines:
        first = content_lines[0].strip().lstrip("#").strip()
        if first and ctx.title_clean and first.lower() == ctx.title_clean.lower():
            ctx.content = "\n".join(content_lines[1:]).lstrip("\n")

    body    = f"# {ctx.title_clean}\n\n{ctx.content}\n"
    chapter = build_cleaned_chapter(ctx, doc.chapter_index, progress={}, body=body)
    chapter.title       = ctx.title_clean
    chapter.source_url  = None
    chapter.source_path = doc.source_path
    chapter.images      = list(ctx.image_refs)

    # Metadata: story_name từ DC; chapter_keyword default "Chapter" (writer fallback)
    chapter.metadata["story_name"]      = story_name
    chapter.metadata["chapter_keyword"] = "Chapter"

    return chapter


# ── Image placeholder rewrite (parallel to scraper._apply_image_stage) ────────

def _rewrite_epub_image_placeholders(content: str, image_refs: list) -> str:
    """
    Rewrite `![alt](IMG_PLACEHOLDER_N)` → `![alt]({local_path or original})`.

    Mirror logic của core.scraper._apply_image_stage (obsidian branch) nhưng
    không gọi WebImageFetcher — image_refs đã được EpubImageExtractor populate
    `local_path` rồi.
    """
    for ref in image_refs:
        old    = f"![{ref.alt_text}]({ref.position_marker})"
        target = ref.local_path or ref.original_url
        new    = f"![{ref.alt_text}]({target})"
        content = content.replace(old, new, 1)
    return content


__all__ = ["run", "run_epub_flow"]
