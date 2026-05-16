"""
ingest/web.py — Web input adapter (P3.3, symbolic re-export).

Phase 3 scope: thin façade re-export `run_novel_task` + `run_learning_only`
từ `core/scraper.py`. KHÔNG refactor caller chain — `main.py` vẫn import
trực tiếp từ `core.scraper` tới khi Phase 6 orchestrator route các adapter.

Why re-export only:
  - Phase 3 build adapter skeleton (web/epub/txt) cho Phase 6 route.
  - Refactor caller bây giờ = đụng main.py + scraper API trước khi
    EPUB/TXT adapter có → 2 refactor lần.
  - Phase 6 `core/orchestrator.py` là chỗ refactor 1 lần khi cả 3 adapter
    sẵn sàng.

`scrape_web()` wrapper provided as canonical entry — Phase 6 dùng cái này
thay vì gọi thẳng `run_novel_task`.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from core.scraper import run_learning_only, run_novel_task

if TYPE_CHECKING:
    from core.session_pool import DomainSessionPool, PlaywrightPool
    from learning.profile_manager import ProfileManager
    from ai.client import AIRateLimiter
    from utils.types import RunConfig


async def scrape_web(
    start_url     : str,
    output_dir    : str,
    progress_path : str,
    pool          : "DomainSessionPool",
    pw_pool       : "PlaywrightPool",
    pm            : "ProfileManager",
    ai_limiter    : "AIRateLimiter",
    run_config    : "RunConfig | None" = None,
    on_chapter_done = None,
) -> None:
    """
    Canonical entry cho web input. Thin pass-through tới `run_novel_task`.

    Phase 6 orchestrator gọi `scrape_web()` sau khi `detect_input_type()`
    return "web". Hiện tại `main.py` vẫn gọi `run_novel_task` trực tiếp —
    backward compat giữ nguyên.
    """
    await run_novel_task(
        start_url       = start_url,
        output_dir      = output_dir,
        progress_path   = progress_path,
        pool            = pool,
        pw_pool         = pw_pool,
        pm              = pm,
        ai_limiter      = ai_limiter,
        run_config      = run_config,
        on_chapter_done = on_chapter_done,
    )


__all__ = ["scrape_web", "run_novel_task", "run_learning_only"]
