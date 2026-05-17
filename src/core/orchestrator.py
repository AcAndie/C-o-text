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

import asyncio
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from ebooklib import epub

from core.image_pipeline.epub_extractor import EpubImageExtractor
from ingest.epub                       import ingest_epub
from ingest.router                     import detect_input_type
from ingest.txt                        import ingest_txt
from pipeline.base                     import CleanedChapter
from pipeline.executor                 import (
    ChainExecutor, PipelineRunner, build_cleaned_chapter, build_soup, make_context,
)
from utils.ads_filter                  import AdsFilter
from utils.string_helpers              import slugify_filename
from writers.factory                   import build_writer

# AdsFilter thresholds — single-run auto-apply only (no AI verify cho file input).
# Watermark "Read more at xyz.com" trong pirate EPUB/TXT sẽ appear N+ chapter edges
# → auto-add → post_process strip khỏi files đã ghi. Reused cho cả EPUB + TXT
# (cả 2 đều offline file source, không có ai_limiter bắt buộc).
_FILE_ADS_AUTO_THRESHOLD = 10

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
        await run_txt_flow(input_path, run_config, ai_limiter=ai_limiter)
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
) -> int:
    """
    Read EPUB → iterate spine → run pipeline (extract + title) → image stage
    via EpubImageExtractor → writer.write.

    Skip:
      - Fetch chain (have prefetched html từ ebooklib)
      - Nav chain (no next URL trong EPUB)
      - Validate chain (LengthValidator có thể reject short chapter hợp lệ)
      - Naming Phase (DC metadata thay thế)
      - Learning Phase (EPUB structured HTML đủ cho DensityHeuristic)
      - Progress/resume (defer P6+; atomic write idempotent)

    AdsFilter (P3.7):
      domain_key = f"epub:{story_slug}" — persist per-EPUB watermark set
      vào data/ads_keywords.json. Filter Pass 1+2 per chapter (giống
      scraper). Cuối run: auto-apply suspects ≥10 occurrences, save,
      post_process_directory strip khỏi files đã ghi.
    """
    # P4.3: writer factory dispatch theo run_config.output_mode.
    # Output mode unknown → factory raise ValueError (fail loud).

    book = epub.read_epub(input_path)

    # ── Naming via Dublin Core (Decision #22) ─────────────────────────────────
    title_meta = book.get_metadata("DC", "title")
    story_name = (title_meta[0][0] if title_meta else None) or Path(input_path).stem
    story_slug = slugify_filename(story_name)

    out_dir = Path(run_config.output_dir) / story_slug
    out_dir.mkdir(parents=True, exist_ok=True)

    writer = build_writer(str(out_dir), run_config)
    runner = PipelineRunner.default()   # empty profile — heuristic-only

    # P3.7: AdsFilter per-EPUB. Domain key namespace "epub:" tránh collision
    # với web domain (vd "epub:thieu_nien_hanh" vs "novelfire.net").
    domain_key = f"epub:{story_slug}"
    ads_filter = AdsFilter.load(domain=domain_key)

    print(
        f"📖 EPUB: {story_name!r} → {out_dir}\n"
        f"   mode={run_config.output_mode} download_images={run_config.download_images}\n"
        f"   ads_domain={domain_key!r} known_kws={ads_filter.stats}",
        flush=True,
    )

    # v1.0.16: Build chapter plan — Tier 2 (AI) default, Tier 1 (rules) fallback
    # Config: [epub] analyzer = "ai" | "rules"  (config.toml)
    import config as _cfg
    from ingest.epub_structure import build_chapter_plan, build_chapter_plan_with_ai
    analyzer = _cfg._get("epub", "analyzer", "ai")
    if analyzer == "ai" and ai_limiter is not None:
        plan = await build_chapter_plan_with_ai(book, input_path, ai_limiter)
    else:
        plan = build_chapter_plan(book)

    n_ok      = 0
    n_skipped = 0

    async for doc in ingest_epub(input_path, plan=plan):
        try:
            chapter = await _build_chapter_from_epub_doc(
                doc        = doc,
                runner     = runner,
                run_config = run_config,
                ai_limiter = ai_limiter,
                story_name = story_name,
                ads_filter = ads_filter,
            )
        except Exception as e:
            logger.warning("[EPUB] chapter %d build failed: %s", doc.chapter_index, e)
            n_skipped += 1
            continue

        if chapter is None:
            n_skipped += 1
            continue

        # Image stage — mode-aware (P4.3)
        if chapter.images:
            chapter.body_markdown = await _apply_epub_image_stage(
                content     = chapter.body_markdown,
                image_refs  = chapter.images,
                run_config  = run_config,
                book        = book,
                chapter_num = chapter.index,
                out_dir     = str(out_dir),
            )

        path = await writer.write(chapter)
        n_ok += 1

        # P3.7: scan edges sau khi write — track watermark frequency cross-chapter
        ads_filter.scan_edges_for_suspects(
            chapter.body_markdown, chapter_url="", chapter_file=str(path),
        )

        if n_ok % 25 == 0:
            print(f"   ... {n_ok} chapters written", flush=True)

    # P3.7: end-of-run auto-apply suspects vượt threshold + post-process
    auto, _ai_pending = ads_filter.get_candidates_by_frequency(
        auto_threshold = _FILE_ADS_AUTO_THRESHOLD,
        min_count      = _FILE_ADS_AUTO_THRESHOLD,   # bỏ AI branch — no AI verify cho EPUB
        max_results    = 50,
    )
    if auto:
        added = ads_filter.apply_verified(auto)
        ads_filter.save()
        removed = AdsFilter.post_process_directory(auto, str(out_dir))
        print(
            f"   🧹 AdsFilter: +{added} kws (threshold ≥{_FILE_ADS_AUTO_THRESHOLD}), "
            f"stripped {removed} lines từ files đã ghi",
            flush=True,
        )
    else:
        ads_filter.save()   # persist scan state cho run sau

    # v1.0.12: Index TOC + top/bottom nav for Obsidian readers (.md only).
    if writer.__class__.__name__ == "ObsidianWriter":
        try:
            from writers.nav_injector import inject_nav_and_index
            n_nav, idx_written = await asyncio.to_thread(
                inject_nav_and_index, str(out_dir), story_name,
            )
            idx_msg = " + index" if idx_written else ""
            if n_nav or idx_written:
                print(f"   🔗 Nav: {n_nav} chapters{idx_msg}", flush=True)
        except Exception as e:
            logger.warning("[EPUB] nav_injector failed: %s", e)

    print(f"\n✔ EPUB done: {n_ok} chapters written, {n_skipped} skipped → {out_dir}", flush=True)
    return n_ok


# ── TXT flow ──────────────────────────────────────────────────────────────────

async def run_txt_flow(
    input_path : str,
    run_config : "RunConfig",
    ai_limiter : "AIRateLimiter | None" = None,
) -> None:
    """
    Read TXT → detect chapter pattern (regex/AI) → split → run pipeline
    (extract + title) → writer.write.

    Skip:
      - Fetch chain (have prefetched html từ ingest_txt wrap)
      - Nav chain (no next URL trong TXT file)
      - Validate chain
      - Learning Phase
      - Image stage — TXT không có inline image (`<img>` tags absent
        từ ingest_txt HTML wrap). image_refs luôn empty → no-op.
      - Progress/resume (defer P6+)
      - Naming Phase (story_name = file stem)

    AdsFilter (P5.4):
      domain_key = f"txt:{story_slug}" — namespace tránh collision với
      epub: và web domain. Same single-pass auto-only threshold logic
      như EPUB (P3.7).

    Raises:
      UnicodeDecodeError — file không phải UTF-8 (ingest_txt fail-loud)
      ValueError — pattern detection fail hoàn toàn (regex + AI fallback)
    """
    text_path  = Path(input_path)
    story_name = text_path.stem
    story_slug = slugify_filename(story_name)

    out_dir = Path(run_config.output_dir) / story_slug
    out_dir.mkdir(parents=True, exist_ok=True)

    writer = build_writer(str(out_dir), run_config)
    runner = PipelineRunner.default()

    # P5.4: AdsFilter per-TXT. Namespace "txt:" tránh collision với
    # web domain ("epub:foo" và "txt:foo" cũng tách biệt).
    domain_key = f"txt:{story_slug}"
    ads_filter = AdsFilter.load(domain=domain_key)

    print(
        f"📄 TXT: {story_name!r} → {out_dir}\n"
        f"   mode={run_config.output_mode} download_images={run_config.download_images}\n"
        f"   ads_domain={domain_key!r} known_kws={ads_filter.stats}",
        flush=True,
    )

    n_ok      = 0
    n_skipped = 0

    async for doc in ingest_txt(input_path, ai_limiter=ai_limiter):
        try:
            chapter = await _build_chapter_from_epub_doc(
                doc        = doc,
                runner     = runner,
                run_config = run_config,
                ai_limiter = ai_limiter,
                story_name = story_name,
                ads_filter = ads_filter,
            )
        except Exception as e:
            logger.warning("[TXT] chapter %d build failed: %s", doc.chapter_index, e)
            n_skipped += 1
            continue

        if chapter is None:
            n_skipped += 1
            continue

        # TXT không có inline image — image_refs luôn empty. Skip image stage.
        # Carry language metadata từ txt_case (ingest_txt populate).
        if doc.metadata.get("language"):
            chapter.metadata["language"] = doc.metadata["language"]

        path = await writer.write(chapter)
        n_ok += 1

        # P5.4: scan edges sau khi write — track watermark frequency cross-chapter
        ads_filter.scan_edges_for_suspects(
            chapter.body_markdown, chapter_url="", chapter_file=str(path),
        )

        if n_ok % 25 == 0:
            print(f"   ... {n_ok} chapters written", flush=True)

    # End-of-run auto-apply (mirror EPUB P3.7)
    auto, _ai_pending = ads_filter.get_candidates_by_frequency(
        auto_threshold = _FILE_ADS_AUTO_THRESHOLD,
        min_count      = _FILE_ADS_AUTO_THRESHOLD,
        max_results    = 50,
    )
    if auto:
        added = ads_filter.apply_verified(auto)
        ads_filter.save()
        removed = AdsFilter.post_process_directory(auto, str(out_dir))
        print(
            f"   🧹 AdsFilter: +{added} kws (threshold ≥{_FILE_ADS_AUTO_THRESHOLD}), "
            f"stripped {removed} lines từ files đã ghi",
            flush=True,
        )
    else:
        ads_filter.save()

    print(f"\n✔ TXT done: {n_ok} chapters written, {n_skipped} skipped → {out_dir}", flush=True)


# ── Per-chapter pipeline ──────────────────────────────────────────────────────

async def _build_chapter_from_epub_doc(
    doc,
    runner     : PipelineRunner,
    run_config : "RunConfig",
    ai_limiter : "AIRateLimiter | None",
    story_name : str,
    ads_filter : "AdsFilter | None" = None,
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
        # Body fallback — DensityHeuristic fails on flat <body><h1><p>... structure
        # (EPUB always, TXT short chapters). Format trực tiếp body element qua
        # MarkdownFormatter.
        from core.formatter import MarkdownFormatter
        body_tag = ctx.soup.find("body") or ctx.soup
        formatter = MarkdownFormatter({})
        content, images = formatter.format(body_tag, base_url="")
        if not content.strip():
            return None
        ctx.content = content
        ctx.image_refs.extend(images)
        ctx.selector_used = "body_fallback"

    ctx.content = clean_extracted_content(ctx.content)

    # P3.7: AdsFilter Pass 1 — strip known kws (mirror scraper Pass 1 behavior).
    # Pass 2 sau title dedup không cần thiết cho EPUB (no strip_nav_edges step).
    if ads_filter is not None:
        ctx.content = ads_filter.filter(ctx.content, chapter_url="")

    # Title resolution priority (v1.0.14):
    #   1. matter bucket → "Front Matter" (no chain run, deterministic)
    #   2. TOC entry title (non-numeric) → use directly
    #   3. Title chain (H1 typically winner)
    #   4. TOC entry title (numeric) → "Chapter N" with TOC label as suffix
    #   5. Default `Chapter N`
    doc_meta  = getattr(doc, "metadata", {}) or {}
    doc_kind  = doc_meta.get("kind", "chapter")
    toc_title = (doc_meta.get("toc_title") or "").strip()

    if doc_kind == "matter":
        ctx.title_clean = "Front Matter"
        ctx.title_raw   = ctx.title_clean
    elif toc_title and not toc_title.isdigit():
        ctx.title_clean = toc_title
        ctx.title_raw   = toc_title
    else:
        title_result = await ChainExecutor(runner._title_blocks(), "title").run(ctx)
        if title_result.ok:
            ctx.title_clean = title_result.data
            ctx.title_raw   = title_result.data
        elif toc_title:
            # Numeric TOC label as last resort, e.g. "0001"
            ctx.title_clean = f"Chapter {toc_title.lstrip('0') or '0'}"
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


# ── EPUB image stage (P4.3 mode-aware, mirror scraper._apply_image_stage) ────

import re as _re

_IMG_PLACEHOLDER_RE = _re.compile(r"!\[[^\]]*\]\(IMG_PLACEHOLDER_\d+\)")


async def _apply_epub_image_stage(
    content     : str,
    image_refs  : list,
    run_config  : "RunConfig",
    book        : "epub.EpubBook",
    chapter_num : int,
    out_dir     : str,
) -> str:
    """
    Mode-aware EPUB image handling. Mirror `core.scraper._apply_image_stage`
    nhưng dùng `EpubImageExtractor` (binary từ zip) thay vì `WebImageFetcher`.

    Modes (per RunConfig defaults):
      obsidian  (download_images=True)  → extract + rewrite local path
      translate (image_placeholder=True) → rewrite → `[IMAGE: alt]`
      raw       (else)                   → strip placeholder entirely
    """
    if not image_refs:
        return content

    if run_config.download_images:
        # Obsidian mode — extract binary + rewrite local path
        extractor = EpubImageExtractor(book, chapter_num)
        try:
            await extractor.fetch_batch(image_refs, out_dir)
        except Exception as e:
            logger.warning("[EPUB ImageStage] fetch_batch failed ch.%d: %s", chapter_num, e)

        for ref in image_refs:
            old    = f"![{ref.alt_text}]({ref.position_marker})"
            target = ref.local_path or ref.original_url
            new    = f"![{ref.alt_text}]({target})"
            content = content.replace(old, new, 1)

    elif run_config.image_placeholder:
        # Translate mode — `[IMAGE: alt]` placeholder, no fetch
        for ref in image_refs:
            old = f"![{ref.alt_text}]({ref.position_marker})"
            new = f"[IMAGE: {ref.alt_text}]"
            content = content.replace(old, new, 1)

    else:
        # Raw mode — strip placeholder entirely
        content = _IMG_PLACEHOLDER_RE.sub("", content)

    return content


__all__ = ["run", "run_epub_flow", "run_txt_flow"]
