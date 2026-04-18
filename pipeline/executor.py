"""
pipeline/executor.py

Batch B: PipelineRunner đọc trực tiếp từ SiteProfile flat fields.
  Trước: from_profile() deserialize profile["pipeline"] → PipelineConfig →
         StepConfig → _make_block(). Roundtrip qua JSON là root cause bug M4.
  Sau:   from_profile() nhận profile dict, _*_blocks() build danh sách block
         trực tiếp từ content_selector, next_selector, nav_type, v.v.
         Không còn _make_block(), không còn StepConfig/ChainConfig import.

Batch B: ChainExecutor nhận list[ScraperBlock] thay vì ChainConfig.
  Chains được build bởi PipelineRunner._*_blocks() methods.

Batch C: Bỏ title_vote mode — dùng first-wins với priority order.
  Trước: tất cả title blocks chạy, confidence-weighted vote chọn winner.
  Sau:   first-wins theo thứ tự ưu tiên đã encode trong _title_blocks().
         SelectorTitle(0.95) > H1(0.80) > TitleTag(0.65) > OgTitle(0.65) > UrlSlug(0.40)
         Bỏ: _run_title_vote(), _make_vote_key(), _DASH_NORM, _WS_NORM.

Batch C: Merge pipeline/context.py vào đây.
  make_context() là 5-line factory — không cần file riêng.
  context_summary() ít dùng, drop luôn.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from bs4 import BeautifulSoup

from pipeline.base import (
    BlockResult, BlockStatus,
    PipelineContext, RuntimeContext, ScraperBlock,
)

logger = logging.getLogger(__name__)


# ── make_context (merged from pipeline/context.py) ───────────────────────────

def make_context(
    url     : str,
    profile : dict | None = None,
    progress: dict | None = None,
) -> PipelineContext:
    """
    Factory function tạo PipelineContext mới cho một chapter.

    Batch C: Merged từ pipeline/context.py — file đó đã bị xóa.
    """
    return PipelineContext(
        url      = url,
        profile  = profile  or {},
        progress = progress or {},
    )


# ── HTML filter + soup builder ────────────────────────────────────────────────

async def build_soup(ctx: PipelineContext) -> None:
    """Parse HTML → BeautifulSoup và apply html_filter."""
    if not ctx.html:
        return
    profile          = ctx.profile
    remove_selectors = profile.get("remove_selectors") or []
    content_selector = profile.get("content_selector")
    title_selector   = profile.get("title_selector")
    try:
        from core.html_filter import prepare_soup
        ctx.soup = await asyncio.to_thread(
            prepare_soup,
            ctx.html,
            remove_selectors,
            content_selector,
            title_selector,
        )
    except Exception as e:
        logger.warning("[Executor] html_filter thất bại, dùng raw parse: %s", e)
        ctx.soup = BeautifulSoup(ctx.html, "html.parser")


# ── ChainExecutor ──────────────────────────────────────────────────────────────

class ChainExecutor:
    """
    Thực thi một chain (ordered list of blocks).
    First-wins: block đầu tiên thành công (SUCCESS hoặc FALLBACK) → dừng.

    Batch B: nhận list[ScraperBlock] trực tiếp thay vì ChainConfig.
    Batch C: Bỏ title_vote mode — tất cả chains dùng first-wins.
    """

    def __init__(
        self,
        blocks    : list[ScraperBlock],
        chain_type: str = "",
    ) -> None:
        self.blocks     = blocks
        self.chain_type = chain_type

    async def run(self, ctx: PipelineContext) -> BlockResult:
        last_result = BlockResult.failed("chain is empty")

        for block in self.blocks:
            block_key = f"{self.chain_type}:{block.name}"
            try:
                result = await block.execute(ctx)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                result = BlockResult.failed(str(e) or repr(e), method_used=block.name)

            result.method_used = result.method_used or block.name
            ctx.record(block_key, result)
            last_result = result

            if result.status == BlockStatus.SKIPPED:
                continue
            if result.ok:
                logger.debug("[Chain:%s] ✓ %s (conf=%.2f dur=%.0fms)",
                             self.chain_type, block.name,
                             result.confidence, result.duration_ms)
                return result
            logger.debug("[Chain:%s] ✗ %s — %s",
                         self.chain_type, block.name, result.error or "failed")

        logger.debug("[Chain:%s] all %d blocks failed", self.chain_type, len(self.blocks))
        return last_result


# ── PipelineRunner ─────────────────────────────────────────────────────────────

class PipelineRunner:
    """
    Batch B: đọc trực tiếp từ SiteProfile flat fields.

    Không còn deserialization qua PipelineConfig/StepConfig/ChainConfig.
    Mỗi _*_blocks() method build danh sách block từ profile fields:
      - content_selector   → SelectorExtractBlock
      - next_selector      → SelectorNavBlock
      - title_selector     → SelectorTitleBlock
      - requires_playwright → PlaywrightFetchBlock first vs HybridFetchBlock first
      - nav_type           → fallback nav block selection

    Profile có thể thiếu bất kỳ field nào (empty profile → chỉ dùng heuristics).
    """

    def __init__(self, profile: dict) -> None:
        self._profile = profile

    # ── Chain builders ─────────────────────────────────────────────────────────

    def _fetch_blocks(self) -> list[ScraperBlock]:
        from pipeline.fetcher import HybridFetchBlock, PlaywrightFetchBlock
        if self._profile.get("requires_playwright", False):
            return [PlaywrightFetchBlock(), HybridFetchBlock()]
        return [HybridFetchBlock(), PlaywrightFetchBlock()]

    def _extract_blocks(self) -> list[ScraperBlock]:
        from pipeline.extractor import (
            SelectorExtractBlock, JsonLdExtractBlock, DensityHeuristicBlock,
            FallbackListExtractBlock, AIExtractBlock,
        )
        blocks: list[ScraperBlock] = []
        sel = self._profile.get("content_selector")
        if sel:
            blocks.append(SelectorExtractBlock(selector=sel))
        blocks += [
            JsonLdExtractBlock(),
            DensityHeuristicBlock(),
            FallbackListExtractBlock(),
            AIExtractBlock(),
        ]
        return blocks

    def _title_blocks(self) -> list[ScraperBlock]:
        """
        Title chain — first-wins theo thứ tự ưu tiên (Batch C).

        Priority: SelectorTitle(0.95) → H1(0.80) → TitleTag(0.65)
                  → OgTitle(0.65) → UrlSlug(0.40)

        SelectorTitle đứng đầu nếu profile có title_selector.
        Nếu không, H1 là lựa chọn đầu tiên — thường chính xác nhất cho web novel.
        """
        from pipeline.title_extractor import (
            SelectorTitleBlock, H1TitleBlock, TitleTagBlock,
            OgTitleBlock, UrlSlugTitleBlock,
        )
        blocks: list[ScraperBlock] = []
        sel = self._profile.get("title_selector")
        if sel:
            blocks.append(SelectorTitleBlock(selector=sel))
        blocks += [H1TitleBlock(), TitleTagBlock(), OgTitleBlock(), UrlSlugTitleBlock()]
        return blocks

    def _nav_blocks(self) -> list[ScraperBlock]:
        from pipeline.navigator import (
            RelNextNavBlock, SelectorNavBlock, AnchorTextNavBlock,
            SlugIncrementNavBlock, FanficNavBlock, SelectDropdownNavBlock, AINavBlock,
        )
        blocks: list[ScraperBlock] = [RelNextNavBlock()]
        next_sel = self._profile.get("next_selector")
        nav_type = (self._profile.get("nav_type") or "").lower()

        if next_sel:
            blocks.append(SelectorNavBlock(selector=next_sel))
        elif nav_type == "slug_increment":
            blocks.append(SlugIncrementNavBlock())
        elif nav_type == "fanfic":
            blocks.append(FanficNavBlock())
        elif nav_type == "select_dropdown":
            blocks.append(SelectDropdownNavBlock())

        existing_types = {type(b) for b in blocks}
        for cls in (AnchorTextNavBlock, SlugIncrementNavBlock, FanficNavBlock, AINavBlock):
            if cls not in existing_types:
                blocks.append(cls())
        return blocks

    def _validate_blocks(self) -> list[ScraperBlock]:
        from pipeline.validator import LengthValidatorBlock, ProseRichnessBlock
        return [LengthValidatorBlock(min_chars=100), ProseRichnessBlock(min_word_count=20)]

    # ── Runner ─────────────────────────────────────────────────────────────────

    @classmethod
    def from_profile(cls, profile: dict) -> "PipelineRunner":
        """Tạo runner từ profile dict. Luôn thành công — không còn trả về None."""
        return cls(profile)

    @classmethod
    def default(cls, domain: str = "") -> "PipelineRunner":
        """Runner mặc định với empty profile — chỉ dùng heuristics."""
        return cls({})

    async def run(
        self,
        url            : str,
        profile        : dict,
        progress       : dict,
        pool           : Any = None,
        pw_pool        : Any = None,
        ai_limiter     : Any = None,
        prefetched_html: str | None = None,
    ) -> PipelineContext:
        ctx         = make_context(url=url, profile=dict(profile), progress=progress)
        ctx.runtime = RuntimeContext.create(pool=pool, pw_pool=pw_pool, ai_limiter=ai_limiter)

        # 1. Fetch
        if prefetched_html is not None:
            ctx.html         = prefetched_html
            ctx.status_code  = 200
            ctx.fetch_method = "prefetched"
        else:
            fetch_result = await ChainExecutor(self._fetch_blocks(), "fetch").run(ctx)
            if not fetch_result.ok:
                logger.warning("[Runner] fetch failed for %s: %s", url, fetch_result.error)
                return ctx
            ctx.html         = fetch_result.data
            ctx.fetch_method = fetch_result.method_used
            ctx.status_code  = fetch_result.metadata.get("status_code", 200)
            if fetch_result.metadata.get("js_heavy"):
                ctx.detected_js_heavy = True
                logger.info("[Runner] js_heavy detected for %s", url)

        # 2. Parse + filter
        await build_soup(ctx)
        if ctx.soup is None:
            logger.warning("[Runner] soup is None after parse for %s", url)
            return ctx

        # 3. Extract content
        extract_result = await ChainExecutor(self._extract_blocks(), "extract").run(ctx)
        if extract_result.ok:
            ctx.content       = extract_result.data
            ctx.selector_used = extract_result.metadata.get("selector")
            from utils.content_cleaner import clean_extracted_content
            cleaned = clean_extracted_content(ctx.content)
            if cleaned != ctx.content:
                logger.debug(
                    "[Runner] content_cleaner: %d→%d chars for %s",
                    len(ctx.content), len(cleaned), url[:55],
                )
            ctx.content = cleaned

        # 4. Extract title — first-wins (Batch C: bỏ title_vote)
        title_result = await ChainExecutor(self._title_blocks(), "title").run(ctx)
        if title_result.ok:
            ctx.title_clean = title_result.data
            ctx.title_raw   = title_result.data

        # 5. Navigate
        nav_result = await ChainExecutor(self._nav_blocks(), "navigate").run(ctx)
        if nav_result.ok:
            ctx.next_url   = nav_result.data
            ctx.nav_method = nav_result.method_used

        # 6. Validate
        await ChainExecutor(self._validate_blocks(), "validate").run(ctx)

        return ctx


# ── Convenience shortcut ───────────────────────────────────────────────────────

async def run_chapter(
    url            : str,
    profile        : dict,
    progress       : dict,
    pool           : Any = None,
    pw_pool        : Any = None,
    ai_limiter     : Any = None,
    prefetched_html: str | None = None,
) -> PipelineContext:
    """Shortcut: tạo PipelineRunner từ profile và chạy một chapter."""
    runner = PipelineRunner.from_profile(profile)
    return await runner.run(
        url             = url,
        profile         = profile,
        progress        = progress,
        pool            = pool,
        pw_pool         = pw_pool,
        ai_limiter      = ai_limiter,
        prefetched_html = prefetched_html,
    )