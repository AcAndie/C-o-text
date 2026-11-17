"""ScrapeSession: vòng lặp cào web, các bộ bảo vệ (guards §6.2) và resume (Task 5.2)."""
from __future__ import annotations

import asyncio
import hashlib
import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from cao_text.ai.prompts import prompt_classify_page, prompt_extract_content
from cao_text.ai.provider import LLMProvider
from cao_text.ai.schemas import ExtractedContentOutput, PageClassificationOutput
from cao_text.ai.skeleton import compress_dom_to_skeleton
from cao_text.extract.nav import RE_CHAP_KW, RE_CHAP_URL, RE_NEXT_BTN, find_next_url
from cao_text.extract.page import process_page
from cao_text.html.cleaner import (
    clean_extracted_content,
    strip_duplicate_title_header,
    strip_nav_edges,
)
from cao_text.html.filter import prepare_soup
from cao_text.images.stage import apply_image_stage
from cao_text.images.web import WebImageFetcher
from cao_text.log import IssueReporter
from cao_text.models import CleanedChapter, RunConfig, SiteProfile, StoryState
from cao_text.net.http import (
    CloudflareBlockedError,
    RateLimitedError,
    fetch_page,
    get_delay,
    is_cloudflare_challenge,
)
from cao_text.storage import (
    ProfileStore,
    ProgressStore,
    make_story_key,
    resolve_story_output_dir,
)
from cao_text.web.start import (
    build_story_id_regex,
    extract_story_title,
    is_chapter_url,
    resolve_start_url,
    story_id_ok,
)
from cao_text.writers.base import ChapterWriter
from cao_text.writers.factory import build_writer
from cao_text.writers.nav_injector import inject_nav_and_index

logger = logging.getLogger(__name__)

# ── Hằng số các bộ bảo vệ (§6.2) ─────────────────────────────────────────────

MAX_EMPTY_STREAK: int = 5
MAX_CONSECUTIVE_ERRORS: int = 5
MAX_CONSECUTIVE_TIMEOUTS: int = 3
TIMEOUT_BACKOFF_BASE: float = 30.0
EMPTY_BACKOFF_SCHEDULE: list[float] = [60.0, 120.0, 300.0]
MAX_CHAPTERS: int = 5000
_CANCEL_SAVE_TIMEOUT_SEC: float = 3.0

_JUNK_PATTERNS = [
    re.compile(r"<title>\s*404\b[^<]*</title>", re.IGNORECASE),
    re.compile(r"<title>\s*(?:page\s+)?not\s+found\b[^<]*</title>", re.IGNORECASE),
    re.compile(r"<title>\s*(?:internal\s+server\s+)?error\b[^<]*</title>", re.IGNORECASE),
    re.compile(r"<title>\s*access\s+denied\b[^<]*</title>", re.IGNORECASE),
    re.compile(r"<title>\s*forbidden\b[^<]*</title>", re.IGNORECASE),
]

# §6.2: HTTP 429 KHÔNG nằm trong _JUNK_STATUSES (429 là rate limit tạm thời, không phải hết truyện)
_JUNK_STATUSES = frozenset({400, 401, 403, 404, 410, 500, 502, 503, 504})


class Outcome(StrEnum):
    """Kết quả xử lý từng chương trong ScrapeSession."""

    WROTE = "WROTE"
    EMPTY = "EMPTY"
    DUPLICATE = "DUPLICATE"
    END = "END"
    BLOCKED = "BLOCKED"
    RATE_LIMITED = "RATE_LIMITED"
    ERROR = "ERROR"


@dataclass
class StepResult:
    """Thông tin chi tiết kết quả một bước cào chương."""

    outcome: Outcome
    url: str
    next_url: str | None = None
    chapter_num: int = 0
    title: str | None = None
    filepath: Path | None = None
    detail: str | None = None


# ── Helpers (§6.2) ────────────────────────────────────────────────────────────

def make_fingerprint(content: str) -> str:
    """Tạo mã băm MD5 16 ký tự từ nội dung chương đã chuẩn hóa khoảng trắng."""
    normalized = re.sub(r"\s+", " ", content.strip())
    return hashlib.md5(normalized.encode("utf-8", errors="replace")).hexdigest()[:16]


def is_junk_page(html: str, status: int = 200) -> bool:
    """Kiểm tra trang lỗi/rỗng (404, 403, 500, HTML < 200 ký tự). Không coi 429 là junk."""
    if not html or len(html.strip()) < 200:
        return True
    if status in _JUNK_STATUSES:
        return True
    sample = html[:2000]
    return any(pattern.search(sample) for pattern in _JUNK_PATTERNS)


def _prepare_extract_fragment(html: str, url: str, max_chars: int = 25000) -> str:
    """Chuẩn bị văn bản sạch đầy đủ kèm gợi ý link điều hướng để gửi cho prompt_extract_content."""
    soup = prepare_soup(html)
    nav_hints: list[str] = []
    for tag_name in ("link", "a"):
        for el in soup.find_all(tag_name, href=True):
            href = el.get("href", "")
            if not href or href.startswith("#"):
                continue
            full_href = urljoin(url, href)
            rel = el.get("rel") or []
            if isinstance(rel, str):
                rel = [rel]
            text = el.get_text(strip=True)
            if "next" in rel or RE_NEXT_BTN.search(text) or RE_CHAP_URL.search(full_href):
                nav_hints.append(f"{text or '[rel=next]'} -> {full_href}")

    body_text = soup.get_text(separator="\n\n", strip=True)[:max_chars]
    if nav_hints:
        hints_block = "\n".join(nav_hints[:15])
        return f"{body_text}\n\n=== NAVIGATION LINKS ===\n{hints_block}"
    return body_text


# ── ScrapeSession ─────────────────────────────────────────────────────────────

class ScrapeSession:
    """Quản lý trạng thái và vòng lặp cào cho một bộ truyện web.

    Đóng gói toàn bộ state (thay thế 13 tham số rời rạc ở bản v1) và thực thi
    đầy đủ các bộ bảo vệ trong §6.2 AGENTS.md.
    """

    def __init__(
        self,
        start_url: str,
        profile: SiteProfile,
        pool: Any,
        *,
        pw_pool: Any = None,
        progress_store: ProgressStore | None = None,
        profile_store: ProfileStore | None = None,
        run_config: RunConfig | None = None,
        ai_provider: LLMProvider | None = None,
        ads_filter: Any = None,
        issue_reporter: IssueReporter | None = None,
        writer: ChapterWriter | None = None,
        prefetched_chapters: list[tuple[str, str]] | dict[str, str] | None = None,
        story_key: str | None = None,
        max_chapters: int = MAX_CHAPTERS,
        max_empty_streak: int = MAX_EMPTY_STREAK,
        max_consecutive_errors: int = MAX_CONSECUTIVE_ERRORS,
        max_consecutive_timeouts: int = MAX_CONSECUTIVE_TIMEOUTS,
        timeout_backoff_base: float = TIMEOUT_BACKOFF_BASE,
        sleep_fn: Callable[[float], Awaitable[None]] = asyncio.sleep,
        on_chapter_done: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        self.start_url = start_url
        self.domain = urlparse(start_url).netloc.lower()
        self.profile = profile
        self.pool = pool
        self.pw_pool = pw_pool
        self.progress_store = progress_store or ProgressStore()
        self.profile_store = profile_store
        self.run_config = run_config or RunConfig()
        self.ai_provider = ai_provider
        self.ads_filter = ads_filter
        self.issue_reporter = issue_reporter
        self._custom_writer = writer
        self.writer: ChapterWriter | None = writer

        if isinstance(prefetched_chapters, dict):
            self.prefetched_map: dict[str, str] = dict(prefetched_chapters)
        elif prefetched_chapters:
            self.prefetched_map = {u: h for u, h in prefetched_chapters}
        else:
            self.prefetched_map = {}

        self.story_key = story_key or make_story_key(start_url, self.run_config.output_dir)
        self.max_chapters = max_chapters
        self.max_empty_streak = max_empty_streak
        self.max_consecutive_errors = max_consecutive_errors
        self.max_consecutive_timeouts = max_consecutive_timeouts
        self.timeout_backoff_base = timeout_backoff_base
        self.sleep_fn = sleep_fn
        self.on_chapter_done = on_chapter_done

        self.state: StoryState = StoryState(story_key=self.story_key, start_url=start_url)
        self.visited_urls: set[str] = set()
        self.fingerprints: set[str] = set()
        self.output_dir: Path = Path(self.run_config.output_dir)

        self.consecutive_empty: int = 0
        self.consecutive_errors: int = 0
        self.consecutive_timeouts: int = 0
        self._initialized: bool = False

    async def _fetch_raw(self, url: str, referer: str | None = None) -> tuple[int, str]:
        """Tải trang qua fetch_page (nếu pool là DomainSessionPool) hoặc pool.fetch."""
        if url in self.prefetched_map:
            return 200, self.prefetched_map.pop(url)

        if hasattr(self.pool, "is_cf_domain"):
            return await fetch_page(
                url,
                self.pool,
                pw_pool=self.pw_pool,
                profile=self.profile,
                referer=referer,
            )

        res = await self.pool.fetch(url)
        if isinstance(res, tuple) and len(res) == 2:
            status, html = int(res[0]), str(res[1] or "")
            if status == 429 and not html.strip():
                raise RateLimitedError(url, status_code=429, detail="HTML body is empty")
            return status, html

        status = int(getattr(res, "status_code", 200))
        html = str(getattr(res, "text", "") or "")
        if status == 429 and not html.strip():
            raise RateLimitedError(url, status_code=429, detail="HTML body is empty")
        return status, html

    async def _ai_extract_content(self, html: str, url: str) -> ExtractedContentOutput | None:
        """Task 5.3: AI fallback trích xuất nội dung chỉ khi PageResult không có nội dung."""
        if self.ai_provider is None:
            return None
        try:
            fragment = await asyncio.to_thread(_prepare_extract_fragment, html, url)
            prompt = prompt_extract_content(fragment, url)
            out = await self.ai_provider.generate(prompt, ExtractedContentOutput)
            if out and out.content_text and len(out.content_text.strip()) >= 100:
                if out.next_url:
                    resolved_next = urljoin(url, out.next_url)
                    out.next_url = resolved_next if resolved_next != url else None
                return out
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning("[%s] AI extract_content fallback thất bại cho %s: %s", self.domain, url, e)
        return None

    async def _ai_find_next_url(self, html: str, soup: BeautifulSoup | None, url: str) -> str | None:
        """Task 5.3: AI fallback tìm next_url qua classify_page chỉ khi PageResult không có next."""
        if self.ai_provider is None:
            return None
        try:
            parsed_soup = soup or await asyncio.to_thread(BeautifulSoup, html, "lxml")
            skeleton = await asyncio.to_thread(compress_dom_to_skeleton, html)
            candidates: list[str] = []
            for a in parsed_soup.find_all("a", href=True):
                href = a.get("href", "")
                if not href or href.startswith("#"):
                    continue
                text = a.get_text(strip=True)
                full_href = urljoin(url, href)
                rel = a.get("rel") or []
                if isinstance(rel, str):
                    rel = [rel]
                if (
                    "next" in rel
                    or RE_NEXT_BTN.search(text)
                    or RE_CHAP_URL.search(full_href)
                    or RE_CHAP_KW.search(text)
                ):
                    candidates.append(f"{text} -> {full_href}")

            prompt = prompt_classify_page(skeleton, url, candidates[:30])
            ai_out = await self.ai_provider.generate(prompt, PageClassificationOutput)
            found = ai_out.next_chapter_url
            if found:
                resolved = urljoin(url, found)
                if (
                    resolved != url
                    and urlparse(resolved).netloc.lower() == self.domain
                    and resolved not in self.visited_urls
                    and story_id_ok(resolved, self.state.story_id_regex)
                ):
                    return resolved
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning("[%s] AI classify_page next_url fallback thất bại cho %s: %s", self.domain, url, e)
        return None

    async def setup(self) -> str | None:
        """Khởi tạo trạng thái truyện, tự động migrate progress v1, kiểm tra chương mới nếu đã hoàn thành.

        Trả về URL chương bắt đầu/tiếp tục, hoặc None nếu truyện đã hoàn thành và không có chương mới.
        """
        self.state = await self.progress_store.load_or_create(
            self.start_url,
            story_key=self.story_key,
            base_output_dir=self.run_config.output_dir,
        )
        self.visited_urls, self.fingerprints = await self.progress_store.load_seen(self.state.story_key)

        # 1. Nếu truyện đã completed: kiểm tra chương mới từ URL cuối (§6.2)
        if self.state.completed:
            last_url = (
                self.state.completed_at_url
                or self.state.last_scraped_url
                or self.state.current_url
            )
            if last_url:
                logger.info("[%s] Truyện đã hoàn thành — kiểm tra chương mới từ %s", self.domain, last_url)
                try:
                    status, html = await self._fetch_raw(last_url)
                    if html and not is_junk_page(html, status):
                        soup = await asyncio.to_thread(BeautifulSoup, html, "lxml")
                        next_url, _ = await asyncio.to_thread(find_next_url, soup, last_url, self.profile)
                        if not next_url:
                            next_url = await self._ai_find_next_url(html, soup, last_url)
                        if (
                            next_url
                            and next_url not in self.visited_urls
                            and story_id_ok(next_url, self.state.story_id_regex)
                        ):
                            logger.info("[%s] Phát hiện chương mới: %s", self.domain, next_url)
                            self.state.completed = False
                            self.state.completed_at = None
                            self.state.completed_at_url = None
                            self.state.current_url = next_url
                            await self.progress_store.save_state(self.state)
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    logger.warning("[%s] Kiểm tra chương mới thất bại: %s", self.domain, e)

            if self.state.completed:
                self._initialized = True
                return None

        # 2. Xác định URL bắt đầu / resume
        if self.state.current_url:
            current_url = self.state.current_url
        else:
            prefetched_start = self.prefetched_map.get(self.start_url)
            resolved_url, classification = await resolve_start_url(
                self.start_url,
                pool=self.pool,
                pw_pool=self.pw_pool,
                ai_provider=self.ai_provider,
                prefetched_html=prefetched_start,
            )
            if classification.story_title and not self.state.story_title:
                self.state.story_title = classification.story_title
            current_url = resolved_url
            self.state.current_url = current_url

        # 3. Khóa Story-ID regex để chống nhảy sang truyện khác (§6.2)
        if not self.state.story_id_locked:
            sid_regex = build_story_id_regex(current_url) or build_story_id_regex(self.start_url)
            if sid_regex:
                self.state.story_id_regex = sid_regex
                self.state.story_id_locked = True

        # 4. Xác định thư mục output (giữ nguyên thư mục cũ khi resume) và tạo Writer
        self.output_dir = resolve_story_output_dir(self.state, self.run_config.output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        if self._custom_writer is None:
            self.writer = build_writer(self.output_dir, self.run_config)

        if self.issue_reporter:
            label = (
                self.state.story_name_clean
                or self.state.story_title
                or self.domain
            )
            self.issue_reporter.set_story_label(label)

        if self.ads_filter is not None:
            if hasattr(self.ads_filter, "set_story_title"):
                self.ads_filter.set_story_title(
                    self.state.story_name_clean or self.state.story_title
                )
            if hasattr(self.ads_filter, "inject_from_profile"):
                self.ads_filter.inject_from_profile(self.profile)

        await self.progress_store.save_state(self.state)
        self._initialized = True
        return current_url

    async def step(self, url: str, *, prefetched_html: str | None = None) -> StepResult:
        """Xử lý một chương đơn lẻ và trả về StepResult chứa Outcome enum (§5.2 & §6.2)."""
        if not self._initialized:
            await self.setup()

        ch_hint = self.state.chapter_count + 1

        # ── Guard 1: URL đã thăm khi bắt đầu -> tìm next thay vì cào lại (§6.2) ──
        if url in self.visited_urls:
            try:
                if prefetched_html is not None:
                    html = prefetched_html
                else:
                    _, html = await self._fetch_raw(url, referer=self.state.last_scraped_url)
                soup = await asyncio.to_thread(BeautifulSoup, html, "lxml")
                next_url, _ = await asyncio.to_thread(
                    find_next_url,
                    soup,
                    url,
                    self.profile,
                    allow_slug_increment=False,
                )
                if not next_url:
                    next_url = await self._ai_find_next_url(html, soup, url)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.warning("[%s] Không thể tìm next cho URL đã thăm %s: %s", self.domain, url, e)
                next_url = None

            if (
                next_url
                and next_url not in self.visited_urls
                and story_id_ok(next_url, self.state.story_id_regex)
            ):
                self.state.current_url = next_url
                await self.progress_store.save_state(self.state)
                return StepResult(
                    outcome=Outcome.DUPLICATE,
                    url=url,
                    next_url=next_url,
                    chapter_num=self.state.chapter_count,
                    detail="already_visited_url",
                )

            return StepResult(
                outcome=Outcome.END,
                url=url,
                next_url=None,
                chapter_num=self.state.chapter_count,
                detail="already_visited_no_next",
            )

        # ── Bước 1: Fetch HTML & xử lý lỗi mạng / 429 / 403 / Cloudflare ─────
        try:
            if prefetched_html is not None:
                status, html = 200, prefetched_html
            else:
                status, html = await self._fetch_raw(url, referer=self.state.last_scraped_url)
        except asyncio.CancelledError:
            raise
        except RateLimitedError as e:
            return StepResult(
                outcome=Outcome.RATE_LIMITED,
                url=url,
                chapter_num=ch_hint,
                detail=str(e),
            )
        except CloudflareBlockedError as e:
            if self.issue_reporter:
                self.issue_reporter.report("BLOCKED", url, detail=str(e)[:120], chapter_num=ch_hint)
            return StepResult(
                outcome=Outcome.BLOCKED,
                url=url,
                chapter_num=ch_hint,
                detail=str(e),
            )
        except TimeoutError as e:
            return StepResult(
                outcome=Outcome.ERROR,
                url=url,
                chapter_num=ch_hint,
                detail=f"[{url}] TimeoutError: {e}",
            )
        except Exception as e:
            err_msg = str(e) or repr(e)
            if any(kw in err_msg.lower() for kw in ("403", "captcha", "cloudflare", "blocked")):
                if self.issue_reporter:
                    self.issue_reporter.report("BLOCKED", url, detail=err_msg[:120], chapter_num=ch_hint)
                return StepResult(
                    outcome=Outcome.BLOCKED,
                    url=url,
                    chapter_num=ch_hint,
                    detail=f"[{url}] {type(e).__name__}: {err_msg}",
                )
            if "429" in err_msg:
                return StepResult(
                    outcome=Outcome.RATE_LIMITED,
                    url=url,
                    chapter_num=ch_hint,
                    detail=f"[{url}] HTTP 429: {err_msg}",
                )
            return StepResult(
                outcome=Outcome.ERROR,
                url=url,
                chapter_num=ch_hint,
                detail=f"[{url}] {type(e).__name__}: {err_msg}",
            )

        # ── Guard 2: Kiểm tra HTTP 429 TRƯỚC is_junk_page (§6.2) ─────────────
        if status == 429:
            return StepResult(
                outcome=Outcome.RATE_LIMITED,
                url=url,
                chapter_num=ch_hint,
                detail=f"HTTP 429 rate limited: {url}",
            )

        # ── Guard 3: Kiểm tra 403 / Cloudflare / Junk page (§6.2) ────────────
        if status == 403 or is_cloudflare_challenge(html):
            detail_msg = f"HTTP {status}" if status == 403 else "Cloudflare challenge"
            if self.issue_reporter:
                self.issue_reporter.report("BLOCKED", url, detail=detail_msg, chapter_num=ch_hint)
            return StepResult(
                outcome=Outcome.BLOCKED,
                url=url,
                chapter_num=ch_hint,
                detail=detail_msg,
            )

        if not html or is_junk_page(html, status):
            return StepResult(
                outcome=Outcome.END,
                url=url,
                chapter_num=ch_hint,
                detail=f"junk_page (status={status})",
            )

        # ── Bước 2: Chạy hàm thuần process_page qua asyncio.to_thread (§3.1) ─
        page_res = await asyncio.to_thread(process_page, html, url, self.profile, source="web")

        # ── Guard 4: Trang index guard (§6.2) ────────────────────────────────
        # URL không giống URL chương + trang có dạng mục lục -> dừng, đánh dấu hoàn thành
        if not is_chapter_url(url, self.profile) and page_res.is_index_page:
            logger.info("[%s] Trang index guard kích hoạt tại %s -> đánh dấu hoàn thành", self.domain, url)
            self.state.mark_completed(url)
            self.state.current_url = None
            await self.progress_store.save_state(self.state)
            return StepResult(
                outcome=Outcome.END,
                url=url,
                next_url=None,
                chapter_num=self.state.chapter_count,
                detail="index_page_guard",
            )

        content = page_res.content_md
        title = page_res.title or "Unknown Title"
        title_method = page_res.title_method
        next_url = page_res.next_url
        nav_method = page_res.nav_method

        # ── Guard 5 & Task 5.3: Nội dung rỗng -> thử AI fallback extract_content ─
        if not content or len(content.strip()) < 100:
            ai_extracted = await self._ai_extract_content(html, url)
            if ai_extracted and ai_extracted.content_text:
                cleaned_ai = await asyncio.to_thread(clean_extracted_content, ai_extracted.content_text)
                stripped_ai = await asyncio.to_thread(strip_nav_edges, cleaned_ai)
                content = stripped_ai if (stripped_ai and len(stripped_ai.strip()) >= 100) else cleaned_ai
                if ai_extracted.title and (not page_res.title or title_method == "url_slug"):
                    title = ai_extracted.title
                    title_method = "ai_fallback"
                if not next_url and ai_extracted.next_url:
                    next_url = ai_extracted.next_url
                    nav_method = "ai_fallback"
                if self.issue_reporter:
                    self.issue_reporter.report(
                        "CONTENT_SUSPICIOUS",
                        url,
                        detail="Selector returned <100 chars; recovered via AI extract_content fallback",
                        chapter_num=ch_hint,
                    )

        if not content or len(content.strip()) < 100:
            if self.issue_reporter:
                detail_msg = (
                    "PageResult and AI extract_content fallback returned <100 chars"
                    if self.ai_provider is not None
                    else "pipeline returned 0 chars"
                )
                self.issue_reporter.report(
                    "CONTENT_SUSPICIOUS",
                    url,
                    detail=detail_msg,
                    chapter_num=ch_hint,
                )

            if not next_url:
                next_url = await self._ai_find_next_url(html, None, url)
                if next_url and self.issue_reporter:
                    self.issue_reporter.report(
                        "NEXT_URL_MISSING",
                        url,
                        detail=f"Empty-content chapter; recovered next_url via AI classify_page -> {next_url}",
                        chapter_num=ch_hint,
                    )
            if not next_url and self.issue_reporter:
                self.issue_reporter.report(
                    "NEXT_URL_MISSING",
                    url,
                    detail="Empty-content chapter",
                    chapter_num=ch_hint,
                )

            if (
                next_url
                and next_url not in self.visited_urls
                and story_id_ok(next_url, self.state.story_id_regex)
            ):
                self.state.current_url = next_url
                await self.progress_store.save_state(self.state)
            else:
                next_url = None

            return StepResult(
                outcome=Outcome.EMPTY,
                url=url,
                next_url=next_url,
                chapter_num=ch_hint,
                detail="empty_content",
            )

        # ── Bước 3: AdsFilter 2-pass & strip_nav_edges & Title deduplication ─
        if self.ads_filter is not None and hasattr(self.ads_filter, "filter"):
            # Nếu có bản trước khi strip_nav_edges từ process_page, dùng nó cho Pass 1
            # để bắt quảng cáo che khuất dòng điều hướng ở rìa chương
            base_for_ads = (
                page_res.diagnostics.get("cleaned_before_strip")
                if page_res.content_md is not None
                else None
            ) or content
            content = self.ads_filter.filter(base_for_ads, chapter_url=url)

        stripped = await asyncio.to_thread(strip_nav_edges, content)
        if stripped and len(stripped.strip()) >= 100:
            content = stripped

        if self.ads_filter is not None and hasattr(self.ads_filter, "filter"):
            content = self.ads_filter.filter(content, chapter_url=url)

        # §6.2: TITLE_FALLBACK chỉ báo khi tiêu đề thật sự lấy từ URL slug hoặc là "Unknown Title"
        if (title_method == "url_slug" or title == "Unknown Title") and self.issue_reporter:
            self.issue_reporter.report(
                "TITLE_FALLBACK",
                url,
                detail=f"Title='{title}' — URL slug fallback",
                chapter_num=ch_hint,
            )

        # §6.2: Bỏ dòng đầu nội dung nếu trùng tiêu đề
        content = strip_duplicate_title_header(content, title)

        # ── Guard 6: Phát hiện trùng fingerprint nội dung (chương khóa/lỗi, §6.2) ─
        fp = make_fingerprint(content)
        if fp in self.fingerprints:
            logger.info("[%s] Phát hiện trùng fingerprint tại %s -> tìm next không dùng slug_increment", self.domain, url)
            self.visited_urls.add(url)
            await self.progress_store.record_seen(
                self.state.story_key,
                url,
                fingerprint=None,
                chapter_num=self.state.chapter_count,
            )

            dup_next = next_url if nav_method != "slug_increment" else None
            if not dup_next:
                soup = await asyncio.to_thread(BeautifulSoup, html, "lxml")
                dup_next, _ = await asyncio.to_thread(
                    find_next_url,
                    soup,
                    url,
                    self.profile,
                    allow_slug_increment=False,
                )
            if not dup_next:
                dup_next = await self._ai_find_next_url(html, None, url)

            if (
                dup_next
                and dup_next not in self.visited_urls
                and story_id_ok(dup_next, self.state.story_id_regex)
            ):
                self.state.current_url = dup_next
                await self.progress_store.save_state(self.state)
                return StepResult(
                    outcome=Outcome.DUPLICATE,
                    url=url,
                    next_url=dup_next,
                    chapter_num=self.state.chapter_count,
                    detail="duplicate_fingerprint",
                )

            return StepResult(
                outcome=Outcome.END,
                url=url,
                next_url=None,
                chapter_num=self.state.chapter_count,
                detail="duplicate_fingerprint_no_next",
            )

        # ── Bước 4: Cập nhật story_title ở chương 1 nếu chưa có ──────────────
        if not self.state.story_title and not self.state.story_name_clean and self.state.chapter_count == 0:
            soup_for_title = await asyncio.to_thread(BeautifulSoup, html, "lxml")
            title_tag = soup_for_title.find("title")
            if title_tag:
                candidate_st = extract_story_title(title_tag.get_text(strip=True))
                if candidate_st:
                    self.state.story_title = candidate_st
                    if self.ads_filter is not None and hasattr(self.ads_filter, "set_story_title"):
                        self.ads_filter.set_story_title(candidate_st)

        # ── Bước 5: Image stage & Ghi file chương ────────────────────────────
        chapter_num = self.state.chapter_count + 1
        if page_res.images:
            strategy = WebImageFetcher(self.pool, chapter_num) if self.run_config.download_images else None
            content = await apply_image_stage(
                content=content,
                image_refs=page_res.images,
                strategy=strategy,
                run_config=self.run_config,
                out_dir=self.output_dir,
                chapter_num=chapter_num,
            )

        if self.writer is None:
            self.writer = build_writer(self.output_dir, self.run_config)

        story_display = self.state.story_name_clean or self.state.story_title or ""
        chapter_dto = CleanedChapter(
            index=chapter_num,
            title=title,
            body_markdown=content,
            images=list(page_res.images),
            source_url=url,
            metadata={"story_title": story_display},
        )
        filepath = await self.writer.write(chapter_dto)

        if self.ads_filter is not None and hasattr(self.ads_filter, "scan_edges_for_suspects"):
            self.ads_filter.scan_edges_for_suspects(content, chapter_url=url, chapter_file=str(filepath))

        # ── Guard 7: Chỉ thêm fingerprint / tăng chapter_count SAU KHI ghi file thành công (§6.2) ─
        self.fingerprints.add(fp)
        self.visited_urls.add(url)
        self.state.chapter_count = chapter_num
        self.state.last_title = title
        self.state.last_scraped_url = url
        await self.progress_store.record_seen(
            self.state.story_key,
            url,
            fingerprint=fp,
            chapter_num=chapter_num,
        )

        if self.issue_reporter:
            self.issue_reporter.mark_chapter_ok()

        # ── Bước 6: Tìm & kiểm tra next_url cho chương kế tiếp ───────────────
        if not next_url:
            next_url = await self._ai_find_next_url(html, None, url)
            if next_url and self.issue_reporter:
                self.issue_reporter.report(
                    "NEXT_URL_MISSING",
                    url,
                    detail=f"PageResult next_url missing; recovered via AI classify_page fallback -> {next_url}",
                    chapter_num=chapter_num,
                )

        if not next_url:
            if self.issue_reporter:
                self.issue_reporter.report(
                    "NEXT_URL_MISSING",
                    url,
                    detail="Pipeline + heuristic + AI all failed",
                    chapter_num=chapter_num,
                )
            self.state.mark_completed(url)
            self.state.current_url = None
            await self.progress_store.save_state(self.state)
            return StepResult(
                outcome=Outcome.WROTE,
                url=url,
                next_url=None,
                chapter_num=chapter_num,
                title=title,
                filepath=filepath,
                detail="completed_no_next_url",
            )

        # Guard 8: Story-ID guard (§6.2)
        if not story_id_ok(next_url, self.state.story_id_regex):
            logger.info("[%s] Story-ID guard chặn next_url khác truyện: %s", self.domain, next_url)
            self.state.current_url = None
            await self.progress_store.save_state(self.state)
            return StepResult(
                outcome=Outcome.WROTE,
                url=url,
                next_url=None,
                chapter_num=chapter_num,
                title=title,
                filepath=filepath,
                detail="stopped_story_id_guard",
            )

        # Guard 9: next_url đã thăm -> dừng (§6.2)
        if next_url in self.visited_urls:
            logger.info("[%s] next_url đã thăm (%s) -> dừng vòng lặp", self.domain, next_url)
            self.state.current_url = None
            await self.progress_store.save_state(self.state)
            return StepResult(
                outcome=Outcome.WROTE,
                url=url,
                next_url=None,
                chapter_num=chapter_num,
                title=title,
                filepath=filepath,
                detail="stopped_next_url_already_visited",
            )

        self.state.current_url = next_url
        await self.progress_store.save_state(self.state)
        return StepResult(
            outcome=Outcome.WROTE,
            url=url,
            next_url=next_url,
            chapter_num=chapter_num,
            title=title,
            filepath=filepath,
        )

    async def run(self) -> StoryState:
        """Chạy toàn bộ vòng lặp cào truyện với đầy đủ các guard và bảo vệ Ctrl+C."""
        current_url = await self.setup()
        if not current_url:
            return self.state

        first_step = True
        cancelled = False
        try:
            while (
                current_url
                and self.state.chapter_count < self.max_chapters
                and not self.state.completed
            ):
                try:
                    # Tạm dừng theo domain delay nếu không phải bản prefetched có sẵn
                    if not first_step and current_url not in self.prefetched_map:
                        delay = get_delay(current_url)
                        if delay > 0:
                            await self.sleep_fn(delay)
                    first_step = False

                    step_res = await self.step(current_url)
                    outcome = step_res.outcome

                    if outcome == Outcome.WROTE:
                        self.consecutive_empty = 0
                        self.consecutive_errors = 0
                        self.consecutive_timeouts = 0
                        if self.on_chapter_done is not None:
                            cb_res = self.on_chapter_done()
                            if asyncio.iscoroutine(cb_res) or hasattr(cb_res, "__await__"):
                                await cb_res
                        current_url = step_res.next_url

                    elif outcome == Outcome.DUPLICATE:
                        self.consecutive_errors = 0
                        self.consecutive_timeouts = 0
                        current_url = step_res.next_url

                    elif outcome == Outcome.EMPTY:
                        self.consecutive_errors = 0
                        self.consecutive_timeouts = 0
                        self.consecutive_empty += 1
                        if self.consecutive_empty >= self.max_empty_streak:
                            logger.warning(
                                "[%s] Chạm ngưỡng %d chương rỗng liên tiếp -> dừng",
                                self.domain,
                                self.max_empty_streak,
                            )
                            if self.issue_reporter:
                                self.issue_reporter.report(
                                    "EMPTY_STREAK",
                                    current_url,
                                    detail=f"{self.max_empty_streak} consecutive empty chapters.",
                                    chapter_num=self.state.chapter_count + 1,
                                )
                            await self.progress_store.save_state(self.state)
                            break

                        if not step_res.next_url:
                            break
                        current_url = step_res.next_url

                    elif outcome in (Outcome.END, Outcome.BLOCKED):
                        break

                    elif outcome == Outcome.RATE_LIMITED:
                        self.consecutive_errors += 1
                        if self.consecutive_errors >= self.max_consecutive_errors:
                            logger.warning(
                                "[%s] Chạm ngưỡng %d lỗi 429 liên tiếp -> dừng",
                                self.domain,
                                self.max_consecutive_errors,
                            )
                            break
                        idx = min(self.consecutive_errors - 1, len(EMPTY_BACKOFF_SCHEDULE) - 1)
                        await self.sleep_fn(EMPTY_BACKOFF_SCHEDULE[idx])
                        # Giữ nguyên current_url để thử lại chương bị 429

                    elif outcome == Outcome.ERROR:
                        detail_lower = (step_res.detail or "").lower()
                        if "timeout" in detail_lower:
                            self.consecutive_timeouts += 1
                            if self.consecutive_timeouts >= self.max_consecutive_timeouts:
                                logger.warning(
                                    "[%s] Chạm ngưỡng %d lần timeout liên tiếp -> dừng",
                                    self.domain,
                                    self.max_consecutive_timeouts,
                                )
                                break
                            await self.sleep_fn(self.timeout_backoff_base * self.consecutive_timeouts)
                        else:
                            self.consecutive_errors += 1
                            if self.consecutive_errors >= self.max_consecutive_errors:
                                logger.warning(
                                    "[%s] Chạm ngưỡng %d lỗi liên tiếp -> dừng",
                                    self.domain,
                                    self.max_consecutive_errors,
                                )
                                break
                            await self.sleep_fn(self.timeout_backoff_base)

                except asyncio.CancelledError:
                    cancelled = True
                    try:
                        await asyncio.wait_for(
                            asyncio.shield(self.progress_store.save_state(self.state)),
                            timeout=_CANCEL_SAVE_TIMEOUT_SEC,
                        )
                    except (TimeoutError, Exception) as save_err:
                        logger.warning("[%s] Lưu tiến độ khi cancel gặp lỗi: %s", self.domain, save_err)
                    raise

        finally:
            if self.issue_reporter:
                self.issue_reporter.summarize(self.state.chapter_count)

            if (
                self.writer is not None
                and self.writer.__class__.__name__ == "ObsidianWriter"
                and self.state.chapter_count > 0
            ):
                try:
                    story_display = (
                        self.state.story_name_clean
                        or self.state.story_title
                        or self.domain
                    )
                    await asyncio.shield(
                        asyncio.to_thread(inject_nav_and_index, self.output_dir, story_display)
                    )
                except Exception as e:
                    logger.warning("[%s] Chèn nav và index thất bại: %s", self.domain, e)

            if self.ads_filter is not None and hasattr(self.ads_filter, "finalize"):
                try:
                    await asyncio.wait_for(
                        asyncio.shield(
                            self.ads_filter.finalize(
                                ai_provider=self.ai_provider,
                                profile=self.profile,
                                profile_store=self.profile_store,
                                output_dir=self.output_dir,
                                total_chapters=self.state.chapter_count,
                                cancelled=cancelled,
                            )
                        ),
                        timeout=30.0,
                    )
                except Exception as e:
                    logger.warning("[%s] Hoàn tất AdsFilter thất bại: %s", self.domain, e)

        return self.state


__all__ = [
    "EMPTY_BACKOFF_SCHEDULE",
    "MAX_CHAPTERS",
    "MAX_CONSECUTIVE_ERRORS",
    "MAX_CONSECUTIVE_TIMEOUTS",
    "MAX_EMPTY_STREAK",
    "Outcome",
    "ScrapeSession",
    "StepResult",
    "TIMEOUT_BACKOFF_BASE",
    "is_junk_page",
    "make_fingerprint",
]
