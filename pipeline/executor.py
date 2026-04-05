"""
pipeline/executor.py — ChainExecutor và PipelineRunner.

ChainExecutor:
    Nhận một ChainConfig + PipelineContext.
    Thử từng step theo thứ tự, dừng khi có kết quả ok (SUCCESS/FALLBACK).
    Ghi kết quả vào context và block_results.

PipelineRunner:
    Orchestrate toàn bộ pipeline cho một chapter:
        1. fetch_chain   → ctx.html, ctx.fetch_method
        2. (parse soup)  → ctx.soup
        3. (html_filter) → ctx.soup cleaned
        4. extract_chain → ctx.content, ctx.selector_used
        5. title_chain   → ctx.title_clean (majority vote từ nhiều sources)
        6. nav_chain     → ctx.next_url
        7. validate_chain → ctx.is_valid, ctx.validation_score

    Inject runtime dependencies (_pool, _pw_pool, _ai_limiter) vào ctx.profile
    trước khi chạy blocks — đây là cách blocks truy cập shared resources
    mà không cần pass qua constructor.

Title Majority Vote:
    Chạy TẤT CẢ title blocks (không dừng sớm).
    Chọn title được đề xuất nhiều nhất (lowercase comparison).
    Tie-break: title dài nhất.
"""
from __future__ import annotations

import asyncio
import logging
from collections import Counter
from typing import Any

from bs4 import BeautifulSoup

from pipeline.base import (
    BlockResult, BlockStatus, BlockType,
    ChainConfig, PipelineConfig, PipelineContext, StepConfig,
)

logger = logging.getLogger(__name__)


# ── Block factories (lazy import để tránh circular) ───────────────────────────

def _make_block(chain_type: str, step: StepConfig):
    """
    Factory: tạo block instance từ chain_type + StepConfig.
    Lazy import để tránh circular dependency.
    """
    cfg = step.to_dict()

    if chain_type == "fetch":
        from pipeline.fetcher import make_fetch_block
        return make_fetch_block(cfg)

    if chain_type == "extract":
        from pipeline.extractor import make_extract_block
        return make_extract_block(cfg)

    if chain_type == "navigate":
        from pipeline.navigator import make_nav_block
        return make_nav_block(cfg)

    if chain_type == "title":
        from pipeline.title_extractor import make_title_block
        return make_title_block(cfg)

    if chain_type == "validate":
        from pipeline.validator import make_validate_block
        return make_validate_block(cfg)

    raise ValueError(f"Unknown chain_type: {chain_type!r}")


# ── ChainExecutor ─────────────────────────────────────────────────────────────

class ChainExecutor:
    """
    Thực thi một chain (ordered list of strategies).

    Thử từng step theo thứ tự.
    Dừng tại step đầu tiên có kết quả ok (SUCCESS hoặc FALLBACK).
    Ghi tất cả kết quả vào ctx.block_results.

    special_mode="title_vote": không dừng sớm, chạy hết → majority vote.
    """

    def __init__(self, chain: ChainConfig, special_mode: str = "") -> None:
        self.chain        = chain
        self.special_mode = special_mode

    async def run(self, ctx: PipelineContext) -> BlockResult:
        """
        Chạy chain. Trả về BlockResult tốt nhất.
        """
        if self.special_mode == "title_vote":
            return await self._run_title_vote(ctx)
        return await self._run_first_wins(ctx)

    async def _run_first_wins(self, ctx: PipelineContext) -> BlockResult:
        """
        Standard chain: dừng tại step đầu tiên thành công.
        """
        last_result = BlockResult.failed("chain is empty")

        for step in self.chain.steps:
            try:
                block = _make_block(self.chain.chain_type, step)
            except ValueError as e:
                logger.warning("[Chain:%s] unknown block %r: %s", self.chain.chain_type, step.type, e)
                continue

            block_key = f"{self.chain.chain_type}:{step.type}"

            try:
                result = await block.execute(ctx)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                result = BlockResult.failed(str(e) or repr(e), method_used=step.type)

            result.method_used = result.method_used or step.type
            ctx.record(block_key, result)
            last_result = result

            if result.status == BlockStatus.SKIPPED:
                # Block không applicable → thử tiếp
                continue

            if result.ok:
                # Thành công → dừng
                logger.debug(
                    "[Chain:%s] ✓ %s (conf=%.2f dur=%.0fms)",
                    self.chain.chain_type, step.type,
                    result.confidence, result.duration_ms,
                )
                return result

            # Failed → log và thử step tiếp theo
            logger.debug(
                "[Chain:%s] ✗ %s — %s",
                self.chain.chain_type, step.type, result.error or "failed",
            )

        # Tất cả steps thất bại
        logger.debug(
            "[Chain:%s] all %d steps failed",
            self.chain.chain_type, len(self.chain.steps),
        )
        return last_result

    async def _run_title_vote(self, ctx: PipelineContext) -> BlockResult:
        """
        Title vote mode: chạy hết tất cả title blocks, chọn majority.

        Mỗi block vote cho title của mình (lowercase).
        Winner = title được vote nhiều nhất.
        Tie-break: title dài nhất.
        Confidence = winning_votes / total_votes.
        """
        candidates: list[str] = []
        methods: list[str]    = []

        for step in self.chain.steps:
            try:
                block = _make_block(self.chain.chain_type, step)
            except ValueError:
                continue

            block_key = f"title:{step.type}"
            try:
                result = await block.execute(ctx)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                result = BlockResult.failed(str(e) or repr(e))

            ctx.record(block_key, result)

            if result.ok and result.data and isinstance(result.data, str):
                title = result.data.strip()
                if len(title) >= 3:
                    candidates.append(title)
                    methods.append(step.type)

        if not candidates:
            return BlockResult.failed("all title blocks failed")

        # Majority vote (lowercase comparison)
        counts       = Counter(t.lower() for t in candidates)
        top2         = counts.most_common(2)
        winner_lower = top2[0][0]
        winner_count = top2[0][1]

        # Lấy lại original case
        winner = next(
            (t for t in candidates if t.lower() == winner_lower),
            candidates[0],
        )

        # Tie → chọn dài nhất
        if len(top2) > 1 and top2[0][1] == top2[1][1]:
            winner = max(candidates, key=len)
            winner_lower = winner.lower()
            winner_count = counts[winner_lower]

        confidence = winner_count / len(candidates)

        return BlockResult.success(
            data        = winner,
            method_used = "title_vote",
            confidence  = confidence,
            candidates  = candidates,
            vote_counts = dict(counts),
        )


# ── HTML Filter helper ────────────────────────────────────────────────────────

async def _build_soup(ctx: PipelineContext) -> None:
    """
    Parse HTML → soup và apply html_filter (remove_selectors, hidden elements).
    Kết quả ghi vào ctx.soup.
    """
    if not ctx.html:
        return

    profile = ctx.profile
    remove_selectors  = profile.get("remove_selectors") or []
    content_selector  = profile.get("content_selector")
    title_selector    = profile.get("title_selector")

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
        logger.warning("[Executor] html_filter failed, fallback to raw parse: %s", e)
        ctx.soup = BeautifulSoup(ctx.html, "html.parser")


# ── PipelineRunner ────────────────────────────────────────────────────────────

class PipelineRunner:
    """
    Orchestrate toàn bộ pipeline cho một chapter.

    Nhận PipelineConfig (đã load từ profile) và thực thi 5 chains theo thứ tự.
    Inject runtime deps vào ctx.profile trước khi chạy.

    Usage:
        runner = PipelineRunner(pipeline_config)
        ctx = await runner.run(
            url        = chapter_url,
            profile    = site_profile,
            progress   = progress_dict,
            pool       = domain_session_pool,
            pw_pool    = playwright_pool,
            ai_limiter = ai_rate_limiter,
        )
        # ctx.content, ctx.title_clean, ctx.next_url, ctx.is_valid
    """

    def __init__(self, config: PipelineConfig) -> None:
        self.config = config

    async def run(
        self,
        url       : str,
        profile   : dict,
        progress  : dict,
        pool      : Any   = None,
        pw_pool   : Any   = None,
        ai_limiter: Any   = None,
        # Pre-fetched HTML (từ learning phase, không fetch lại)
        prefetched_html: str | None = None,
    ) -> PipelineContext:
        """
        Thực thi full pipeline cho một chapter URL.

        Args:
            url:            URL chapter cần scrape
            profile:        SiteProfile dict
            progress:       ProgressDict
            pool:           DomainSessionPool (curl)
            pw_pool:        PlaywrightPool
            ai_limiter:     AIRateLimiter
            prefetched_html: HTML đã fetch sẵn (learning phase reuse)

        Returns:
            PipelineContext sau khi chạy xong — caller đọc .content, .title_clean, etc.
        """
        from pipeline.context import make_context

        ctx = make_context(url=url, profile=dict(profile), progress=progress)

        # Inject runtime deps vào ctx.profile (blocks access qua ctx.profile["_key"])
        ctx.profile["_pool"]       = pool
        ctx.profile["_pw_pool"]    = pw_pool
        ctx.profile["_ai_limiter"] = ai_limiter

        # ── 1. Fetch ──────────────────────────────────────────────────────────
        if prefetched_html is not None:
            # Dùng HTML có sẵn — không chạy fetch chain
            ctx.html         = prefetched_html
            ctx.status_code  = 200
            ctx.fetch_method = "prefetched"
        else:
            fetch_result = await ChainExecutor(self.config.fetch_chain).run(ctx)
            if not fetch_result.ok:
                logger.warning("[Runner] fetch failed for %s: %s", url, fetch_result.error)
                return ctx
            ctx.html         = fetch_result.data
            ctx.fetch_method = fetch_result.method_used
            ctx.status_code  = fetch_result.metadata.get("status_code", 200)

        # ── 2. Parse + filter HTML ────────────────────────────────────────────
        await _build_soup(ctx)

        if ctx.soup is None:
            logger.warning("[Runner] soup is None after parse for %s", url)
            return ctx

        # ── 3. Extract content ────────────────────────────────────────────────
        extract_result = await ChainExecutor(self.config.extract_chain).run(ctx)
        if extract_result.ok:
            ctx.content       = extract_result.data
            ctx.selector_used = extract_result.metadata.get("selector")

        # ── 4. Extract title (majority vote) ─────────────────────────────────
        title_exec   = ChainExecutor(self.config.title_chain, special_mode="title_vote")
        title_result = await title_exec.run(ctx)
        if title_result.ok:
            ctx.title_clean = title_result.data
            ctx.title_raw   = title_result.data

        # ── 5. Navigate ───────────────────────────────────────────────────────
        nav_result = await ChainExecutor(self.config.nav_chain).run(ctx)
        if nav_result.ok:
            ctx.next_url   = nav_result.data
            ctx.nav_method = nav_result.method_used

        # ── 6. Validate ───────────────────────────────────────────────────────
        await ChainExecutor(self.config.validate_chain).run(ctx)

        return ctx

    @classmethod
    def from_profile(cls, profile: dict) -> "PipelineRunner | None":
        """
        Tạo PipelineRunner từ SiteProfile dict.
        Trả về None nếu profile không có pipeline config (cần learning).
        """
        pipeline_data = profile.get("pipeline")
        if not pipeline_data or not isinstance(pipeline_data, dict):
            return None
        try:
            config = PipelineConfig.from_dict(pipeline_data)
            return cls(config)
        except Exception as e:
            logger.warning("[Runner] cannot load pipeline config: %s", e)
            return None

    @classmethod
    def default(cls, domain: str) -> "PipelineRunner":
        """
        Tạo PipelineRunner với default config (chạy được ngay, chưa optimized).
        Dùng khi domain chưa có profile.
        """
        return cls(PipelineConfig.default_for_domain(domain))


# ── Convenience: run single chapter ──────────────────────────────────────────

async def run_chapter(
    url            : str,
    profile        : dict,
    progress       : dict,
    pool           : Any   = None,
    pw_pool        : Any   = None,
    ai_limiter     : Any   = None,
    prefetched_html: str | None = None,
) -> PipelineContext:
    """
    Shortcut: tạo PipelineRunner từ profile và chạy một chapter.

    Nếu profile có pipeline config → dùng config đó.
    Nếu không → dùng default config (naive fallback chain).
    """
    from urllib.parse import urlparse
    domain = urlparse(url).netloc.lower()

    runner = PipelineRunner.from_profile(profile) or PipelineRunner.default(domain)
    return await runner.run(
        url             = url,
        profile         = profile,
        progress        = progress,
        pool            = pool,
        pw_pool         = pw_pool,
        ai_limiter      = ai_limiter,
        prefetched_html = prefetched_html,
    )