"""
pipeline/executor.py — ChainExecutor và PipelineRunner.

v2 changes:
  EXEC-1: PipelineRunner inject RuntimeContext vào ctx.runtime thay vì
          nhét live objects vào ctx.profile dict (anti-pattern cũ).

  EXEC-2: Title vote dùng confidence-weighted voting thay vì unweighted.
          Trước: "Chapter 5" (slug, conf=0.40) có thể đánh bại
                 "Chapter 5 – The Beginning" (selector, conf=0.95).
          Bây giờ: confidence của mỗi block là trọng số vote của nó.

  EXEC-3: _build_soup đổi thành build_soup (public). Không ai nên import
          private function từ module khác.

  EXEC-4: Sau fetch chain, executor đọc BlockResult.metadata["js_heavy"]
          và set ctx.detected_js_heavy — KHÔNG để block tự mutate profile.
          Caller (scraper.py) nhận signal này và persist nếu cần.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from bs4 import BeautifulSoup

from pipeline.base import (
    BlockResult, BlockStatus, BlockType,
    ChainConfig, PipelineConfig, PipelineContext,
    RuntimeContext, StepConfig,
)

logger = logging.getLogger(__name__)


# ── Block factories ────────────────────────────────────────────────────────────

def _make_block(chain_type: str, step: StepConfig):
    """Factory: tạo block instance từ chain_type + StepConfig (lazy import)."""
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


# ── HTML filter + soup builder ────────────────────────────────────────────────

async def build_soup(ctx: PipelineContext) -> None:
    """
    Parse HTML → BeautifulSoup và apply html_filter.
    Kết quả ghi vào ctx.soup.

    Public function — optimizer.py và bất kỳ module nào có thể import
    mà không cần hack private function.
    """
    if not ctx.html:
        return

    profile           = ctx.profile
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
        logger.warning("[Executor] html_filter thất bại, dùng raw parse: %s", e)
        ctx.soup = BeautifulSoup(ctx.html, "html.parser")


# ── ChainExecutor ──────────────────────────────────────────────────────────────

class ChainExecutor:
    """
    Thực thi một chain (ordered list of strategies).

    Chế độ mặc định: first-wins — dừng tại step đầu tiên có ok result.
    Chế độ title_vote: chạy hết tất cả blocks, chọn bằng weighted vote.
    """

    def __init__(self, chain: ChainConfig, special_mode: str = "") -> None:
        self.chain        = chain
        self.special_mode = special_mode

    async def run(self, ctx: PipelineContext) -> BlockResult:
        if self.special_mode == "title_vote":
            return await self._run_title_vote(ctx)
        return await self._run_first_wins(ctx)

    async def _run_first_wins(self, ctx: PipelineContext) -> BlockResult:
        """Standard: dừng tại step đầu tiên thành công."""
        last_result = BlockResult.failed("chain is empty")

        for step in self.chain.steps:
            try:
                block = _make_block(self.chain.chain_type, step)
            except ValueError as e:
                logger.warning(
                    "[Chain:%s] unknown block %r: %s",
                    self.chain.chain_type, step.type, e,
                )
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
                continue

            if result.ok:
                logger.debug(
                    "[Chain:%s] ✓ %s (conf=%.2f dur=%.0fms)",
                    self.chain.chain_type, step.type,
                    result.confidence, result.duration_ms,
                )
                return result

            logger.debug(
                "[Chain:%s] ✗ %s — %s",
                self.chain.chain_type, step.type, result.error or "failed",
            )

        logger.debug(
            "[Chain:%s] all %d steps failed",
            self.chain.chain_type, len(self.chain.steps),
        )
        return last_result

    async def _run_title_vote(self, ctx: PipelineContext) -> BlockResult:
        """
        Title vote: chạy hết tất cả title blocks, chọn bằng confidence-weighted vote.

        Cơ chế:
        - Mỗi block vote cho title của mình với trọng số = confidence của nó.
        - Winner = title có tổng trọng số lớn nhất.
        - Tie-break: title dài nhất (thường đầy đủ hơn).
        - Final confidence = tổng trọng số của winner / tổng trọng số tất cả.

        Ví dụ:
            url_slug      "Chapter 5"                  conf=0.40  weight=0.40
            title_tag     "Chapter 5 – The Beginning"  conf=0.65  weight=0.65
            selector      "Chapter 5 – The Beginning"  conf=0.95  weight=0.95
            → "chapter 5 – the beginning" total_weight=1.60 vs "chapter 5" total=0.40
            → Winner: "Chapter 5 – The Beginning" với confidence=1.60/2.00=0.80
        """
        candidates:    list[str]   = []
        confidences:   list[float] = []
        methods:       list[str]   = []

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

            if result.ok and isinstance(result.data, str):
                title = result.data.strip()
                if len(title) >= 3:
                    candidates.append(title)
                    confidences.append(result.confidence)
                    methods.append(step.type)

        if not candidates:
            return BlockResult.failed("all title blocks failed")

        # Confidence-weighted voting
        vote_weights:  dict[str, float] = {}   # lowercase title → total weight
        original_case: dict[str, str]   = {}   # lowercase → best case version

        for title, conf in zip(candidates, confidences):
            key = title.lower()
            vote_weights[key]  = vote_weights.get(key, 0.0) + conf
            if key not in original_case:
                original_case[key] = title
            # Nếu cùng title nhưng case khác → giữ version dài hơn
            elif len(title) > len(original_case[key]):
                original_case[key] = title

        # Chọn winner
        winner_lower = max(vote_weights, key=vote_weights.__getitem__)
        top_weight   = vote_weights[winner_lower]

        # Tie-break: nếu có nhiều title cùng weight → dài nhất
        top_weight_val = max(vote_weights.values())
        tied_keys = [k for k, w in vote_weights.items() if w == top_weight_val]
        if len(tied_keys) > 1:
            winner_lower = max(tied_keys, key=len)

        winner       = original_case[winner_lower]
        total_weight = sum(vote_weights.values())
        confidence   = vote_weights[winner_lower] / total_weight if total_weight > 0 else 0.0

        return BlockResult.success(
            data        = winner,
            method_used = "title_vote",
            confidence  = round(confidence, 3),
            vote_weights = dict(vote_weights),
            candidates  = candidates,
        )


# ── PipelineRunner ─────────────────────────────────────────────────────────────

class PipelineRunner:
    """
    Orchestrate toàn bộ pipeline cho một chapter.

    Tạo RuntimeContext và inject vào ctx.runtime trước khi chạy bất kỳ block nào.
    Blocks truy cập pool/pw_pool/ai_limiter qua ctx.runtime — KHÔNG qua ctx.profile.

    Xử lý signals từ blocks:
        - fetch_result.metadata["js_heavy"] → ctx.detected_js_heavy = True
          (Caller scraper.py sẽ persist thông tin này vào profile)
    """

    def __init__(self, config: PipelineConfig) -> None:
        self.config = config

    async def run(
        self,
        url            : str,
        profile        : dict,
        progress       : dict,
        pool           : Any   = None,
        pw_pool        : Any   = None,
        ai_limiter     : Any   = None,
        prefetched_html: str | None = None,
    ) -> PipelineContext:
        """
        Thực thi full pipeline cho một chapter URL.

        Args:
            url:             URL chapter cần scrape
            profile:         SiteProfile dict (READ-ONLY, không mutate)
            progress:        ProgressDict
            pool:            DomainSessionPool (curl)
            pw_pool:         PlaywrightPool
            ai_limiter:      AIRateLimiter
            prefetched_html: HTML đã fetch sẵn (learning phase reuse)

        Returns:
            PipelineContext — caller đọc .content, .title_clean, .next_url, etc.
            Chú ý ctx.detected_js_heavy — nếu True, caller nên persist vào profile.
        """
        from pipeline.context import make_context

        ctx = make_context(url=url, profile=dict(profile), progress=progress)

        # ── Inject runtime deps (KHÔNG put vào ctx.profile) ──────────────────
        ctx.runtime = RuntimeContext.create(
            pool       = pool,
            pw_pool    = pw_pool,
            ai_limiter = ai_limiter,
        )

        # ── 1. Fetch ──────────────────────────────────────────────────────────
        if prefetched_html is not None:
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

            # Đọc signal js_heavy từ block metadata — KHÔNG để block mutate profile
            if fetch_result.metadata.get("js_heavy"):
                ctx.detected_js_heavy = True
                logger.info("[Runner] js_heavy detected for %s", url)

        # ── 2. Parse + filter HTML ────────────────────────────────────────────
        await build_soup(ctx)

        if ctx.soup is None:
            logger.warning("[Runner] soup is None after parse for %s", url)
            return ctx

        # ── 3. Extract content ────────────────────────────────────────────────
        extract_result = await ChainExecutor(self.config.extract_chain).run(ctx)
        if extract_result.ok:
            ctx.content       = extract_result.data
            ctx.selector_used = extract_result.metadata.get("selector")

        # ── 4. Extract title (confidence-weighted vote) ───────────────────────
        title_result = await ChainExecutor(
            self.config.title_chain, special_mode="title_vote"
        ).run(ctx)
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
        Trả về None nếu profile không có pipeline config.
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
        """Default runner cho domain chưa có profile."""
        return cls(PipelineConfig.default_for_domain(domain))


# ── Convenience shortcut ───────────────────────────────────────────────────────

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
    Dùng bởi core/scraper.py.
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