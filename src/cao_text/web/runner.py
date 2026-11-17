"""
src/cao_text/web/runner.py — Điều phối chạy song song các task cào web từ danh sách URL.

Hỗ trợ:
  - Đọc và phân tích cú pháp links.md / links.txt: URL hợp lệ, comment #, !relearn <domain>.
  - Khóa learning tuần tự theo domain: tránh việc nhiều task cùng học một domain đồng thời.
  - Cào song song: mỗi URL là một task chạy ScrapeSession độc lập.
  - Giãn cách khởi động (init_stagger) giữa các task để tránh nghẽn mạng/AI.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from cao_text.ai.provider import LLMProvider
from cao_text.learn.learner import learn_site
from cao_text.log import IssueReporter
from cao_text.models import RunConfig, SiteProfile, StoryState
from cao_text.settings import get_settings
from cao_text.storage import ProfileStore, ProgressStore
from cao_text.web.session import ScrapeSession
from cao_text.web.start import ClassificationStore, resolve_start_url

logger = logging.getLogger("cao_text.web.runner")


def normalize_domain(domain_or_url: str) -> str:
    """Chuẩn hóa domain: chữ thường, bỏ www., bỏ port và đường dẫn nếu có."""
    text = domain_or_url.strip().lower()
    if "://" in text:
        text = urlparse(text).netloc
    elif "/" in text:
        text = text.split("/", 1)[0]

    if ":" in text:
        text = text.split(":", 1)[0]
    if text.startswith("www."):
        text = text[4:]
    return text.strip()


def is_valid_url(url: str) -> bool:
    """Kiểm tra URL có hợp lệ (scheme http/https và có netloc)."""
    try:
        p = urlparse(url.strip())
        return p.scheme in ("http", "https") and bool(p.netloc)
    except Exception:
        return False


def parse_links(content_or_path: str | Path) -> tuple[list[str], list[str]]:
    """Phân tích nội dung hoặc file links.

    Trả về:
      (urls, relearn_domains)

    Bỏ qua:
      - Dòng trống
      - Dòng chú thích bắt đầu hoặc có comment '#'
    Bắt lệnh:
      - `!relearn <domain>`: thêm vào danh sách domain cần học lại
    """
    text: str
    if isinstance(content_or_path, Path):
        text = content_or_path.read_text(encoding="utf-8")
    elif isinstance(content_or_path, str) and "\n" not in content_or_path and Path(content_or_path).is_file():
        text = Path(content_or_path).read_text(encoding="utf-8")
    else:
        text = str(content_or_path)

    urls: list[str] = []
    relearn_domains: list[str] = []

    for raw_line in text.splitlines():
        # Cắt bỏ comment sau dấu #
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue

        if line.lower().startswith("!relearn"):
            parts = line.split(None, 1)
            if len(parts) == 2:
                dom = normalize_domain(parts[1])
                if dom:
                    relearn_domains.append(dom)
                    logger.info("Yêu cầu force re-learn cho domain: %s", dom)
            else:
                logger.warning("Bỏ qua chỉ thị !relearn không hợp lệ: %r", line)
            continue

        if is_valid_url(line):
            urls.append(line)
        else:
            logger.warning("Bỏ qua URL không hợp lệ: %r", line)

    return urls, relearn_domains


async def apply_relearn(
    relearn_domains: list[str],
    profile_store: ProfileStore,
) -> int:
    """Xóa profile của các domain được yêu cầu re-learn (cả dạng thường và www.)."""
    if not relearn_domains:
        return 0

    removed = 0
    for dom in relearn_domains:
        norm = normalize_domain(dom)
        variants = {norm, f"www.{norm}"}
        for v in variants:
            if await profile_store.delete(v):
                removed += 1
                logger.info("Đã xóa profile '%s' để học lại", v)
    return removed


class DomainLockManager:
    """Quản lý asyncio.Lock riêng cho từng domain (chuẩn hóa không phân biệt www)."""

    def __init__(self) -> None:
        self._locks: dict[str, asyncio.Lock] = {}

    def get_lock(self, domain_or_url: str) -> asyncio.Lock:
        norm = normalize_domain(domain_or_url)
        if norm not in self._locks:
            self._locks[norm] = asyncio.Lock()
        return self._locks[norm]


async def run_novel_task(
    url: str,
    *,
    index: int = 0,
    pool: Any,
    pw_pool: Any = None,
    profile_store: ProfileStore,
    progress_store: ProgressStore | None = None,
    run_config: RunConfig | None = None,
    ai_provider: LLMProvider | None = None,
    lock_manager: DomainLockManager | None = None,
    init_stagger: float = 0.0,
    sleep_fn: Callable[[float], Awaitable[None]] = asyncio.sleep,
    on_chapter_done: Callable[[], Any] | None = None,
    issue_reporter: IssueReporter | None = None,
    classify_cache: ClassificationStore | None = None,
    prefetched_chapters: list[tuple[str, str]] | dict[str, str] | None = None,
) -> StoryState:
    """Thực hiện một tác vụ cào tiểu thuyết từ URL.

    Các bước:
      1. Giãn cách khởi động `index * init_stagger`.
      2. Phân loại URL (chuyển index/mục lục -> chương 1 nếu cần).
      3. Đảm bảo profile: nếu thiếu, acquire domain lock và chạy learn_site tuần tự.
      4. Khởi chạy ScrapeSession và trả về StoryState.
    """
    domain = normalize_domain(url)
    cfg = run_config or RunConfig()
    prog_store = progress_store or ProgressStore()

    # 1. Giãn cách khởi động
    if index > 0 and init_stagger > 0:
        delay = index * init_stagger
        logger.info("[%s] Task #%d giãn cách khởi động %.1fs...", domain, index, delay)
        await sleep_fn(delay)

    # 2. Phân loại URL / Resolve start URL
    resolved_url = url
    try:
        prefetched_html = None
        if prefetched_chapters:
            if isinstance(prefetched_chapters, dict):
                prefetched_html = prefetched_chapters.get(url)
            else:
                for u, h in prefetched_chapters:
                    if u == url:
                        prefetched_html = h
                        break

        resolved_url, _classification = await resolve_start_url(
            url,
            pool=pool,
            pw_pool=pw_pool,
            ai_provider=ai_provider,
            cache_store=classify_cache,
            prefetched_html=prefetched_html,
        )
    except asyncio.CancelledError:
        raise
    except Exception as e:
        logger.warning(
            "[%s] Phân loại URL thất bại cho %s: %s (dùng URL ban đầu)",
            domain,
            url,
            e,
        )
        resolved_url = url

    resolved_domain = normalize_domain(resolved_url)

    # 3. Đảm bảo có profile cho domain (khóa tuần tự theo domain)
    profile: SiteProfile | None = await profile_store.get(resolved_domain)
    if profile is None or not profile.is_usable():
        mgr = lock_manager or DomainLockManager()
        async with mgr.get_lock(resolved_domain):
            # Double-check sau khi nhận lock
            profile = await profile_store.get(resolved_domain)
            if profile is None or not profile.is_usable():
                if ai_provider is None:
                    raise ValueError(
                        f"Domain '{resolved_domain}' chưa có profile cấu trúc site "
                        "và không có AI Provider để học mới."
                    )
                logger.info("[%s] Bắt đầu học cấu trúc site qua AI...", resolved_domain)
                learn_res = await learn_site(
                    resolved_url,
                    ai_provider=ai_provider,
                    pool=pool,
                    pw_pool=pw_pool,
                    profile_store=profile_store,
                    issue_reporter=issue_reporter,
                    auto_save=True,
                )
                profile = learn_res.profile
                if profile is None or not profile.is_usable():
                    diag = learn_res.verification.diagnostics if learn_res.verification else "Thất bại"
                    raise RuntimeError(
                        f"Không thể học cấu trúc site cho domain '{resolved_domain}': {diag}"
                    )

    # 4. Tạo ScrapeSession và chạy
    session = ScrapeSession(
        start_url=resolved_url,
        profile=profile,
        pool=pool,
        pw_pool=pw_pool,
        progress_store=prog_store,
        profile_store=profile_store,
        run_config=cfg,
        ai_provider=ai_provider,
        issue_reporter=issue_reporter,
        prefetched_chapters=prefetched_chapters,
        sleep_fn=sleep_fn,
        on_chapter_done=on_chapter_done,
    )

    return await session.run()


async def run_web_tasks(
    urls_or_file: list[str] | str | Path,
    *,
    pool: Any,
    pw_pool: Any = None,
    profile_store: ProfileStore | None = None,
    progress_store: ProgressStore | None = None,
    run_config: RunConfig | None = None,
    ai_provider: LLMProvider | None = None,
    init_stagger: float | None = None,
    sleep_fn: Callable[[float], Awaitable[None]] = asyncio.sleep,
    on_chapter_done: Callable[[], Any] | None = None,
    issue_reporter: IssueReporter | None = None,
    lock_manager: DomainLockManager | None = None,
    classify_cache: ClassificationStore | None = None,
) -> list[StoryState | Exception]:
    """Chạy song song các tác vụ cào truyện web từ danh sách URL hoặc file links.

    - Nếu đầu vào là đường dẫn file hoặc text content: tự động parse và thực thi !relearn.
    - Learning được tuần tự hóa theo từng domain qua DomainLockManager.
    - Cào các truyện song song qua asyncio.gather.
    - Khởi động mỗi task cách nhau `init_stagger` giây.
    """
    prof_store = profile_store or ProfileStore()
    prog_store = progress_store or ProgressStore()
    cfg = run_config or RunConfig()
    mgr = lock_manager or DomainLockManager()

    urls: list[str] = []
    if isinstance(urls_or_file, (str, Path)):
        parsed_urls, relearn_domains = parse_links(urls_or_file)
        if relearn_domains:
            await apply_relearn(relearn_domains, prof_store)
        urls = parsed_urls
    else:
        urls = [u.strip() for u in urls_or_file if is_valid_url(u)]

    if not urls:
        logger.warning("Không có URL hợp lệ nào để cào.")
        return []

    if init_stagger is None:
        init_stagger = get_settings().scraper.init_stagger

    logger.info(
        "Bắt đầu điều phối %d truyện web (init_stagger=%.1fs)...",
        len(urls),
        init_stagger,
    )

    tasks = [
        run_novel_task(
            url,
            index=i,
            pool=pool,
            pw_pool=pw_pool,
            profile_store=prof_store,
            progress_store=prog_store,
            run_config=cfg,
            ai_provider=ai_provider,
            lock_manager=mgr,
            init_stagger=init_stagger,
            sleep_fn=sleep_fn,
            on_chapter_done=on_chapter_done,
            issue_reporter=issue_reporter,
            classify_cache=classify_cache,
        )
        for i, url in enumerate(urls)
    ]

    try:
        results = await asyncio.gather(*tasks, return_exceptions=True)
        # Không bao giờ nuốt CancelledError (§3.2, §6.1)
        for res in results:
            if isinstance(res, asyncio.CancelledError):
                raise res
        return list(results)
    except asyncio.CancelledError:
        logger.warning("Quá trình cào web bị huỷ (CancelledError).")
        raise


__all__ = [
    "DomainLockManager",
    "apply_relearn",
    "is_valid_url",
    "normalize_domain",
    "parse_links",
    "run_novel_task",
    "run_web_tasks",
]
