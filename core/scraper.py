# core/scraper.py
"""
core/scraper.py — v5: ProfileManager integration.

Mọi thao tác profile đi qua ProfileManager (pm):
  pm.record_content_hit()      → selector_stats, working_content_selector
  pm.record_playwright_required() → requires_playwright flag
  pm.record_nav_edges()        → has_nav_edges flag
  pm.record_ai_fallback()      → ai_fallback_count
  pm.record_chapter_done()     → chapters_scraped, sample_urls
  pm.update_chapter_url_pattern() → chapter_url_pattern từ story_id

Lần sau vào cùng domain:
  - working_content_selector → shortcut, không thử cả CONTENT_SELECTORS list
  - requires_playwright      → dùng thẳng Playwright, không curl_cffi roundtrip
  - has_nav_edges            → luôn strip nav, không detect lại
  - chapter_url_pattern      → detect_page_type chính xác hơn
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
from urllib.parse import urlparse
from bs4 import BeautifulSoup

from config import (
    CONTENT_SELECTORS, MAX_CHAPTERS, MAX_CONSECUTIVE_ERRORS,
    MAX_CONSECUTIVE_TIMEOUTS, TIMEOUT_BACKOFF_BASE,
    STORY_ID_LEARN_AFTER, STORY_ID_MAX_ATTEMPTS,
    ADS_AI_SCAN_EVERY, RE_CHAP_URL, get_delay_seconds,
)
from utils.file_io import load_progress, save_progress, write_markdown
from utils.string_helpers import (
    is_junk_page, make_fingerprint, clean_chapter_text,
    normalize_title, slugify_filename, truncate, extract_text_blocks,
)
from utils.types import AiClassifyResult, ProgressDict, SiteProfileDict, StoryIdResult
from utils.ads_filter import SimpleAdsFilter, ADS_DB_FILE as _ADS_DB_FILE
from core.profile_manager import ProfileManager

from ai.client import AIRateLimiter
from ai.agents import (
    ask_ai_for_story_id, ai_find_first_chapter_url, ai_classify_and_find,
    ask_ai_build_profile, ask_ai_confirm_same_story, ai_detect_ads_content,
)
from core.fetch        import fetch_page
from core.navigator    import find_next_url, detect_page_type
from core.html_filter  import remove_hidden_elements
from core.extractors   import TitleExtractor, extract_story_title
from core.session_pool import DomainSessionPool, PlaywrightPool

logger = logging.getLogger(__name__)
_COLLECTED_URL_CAP = 20


# ── Nav-edge strip ────────────────────────────────────────────────────────────

_RE_WORD_COUNT_LINE = re.compile(
    r"^\[\s*[\d,.\s]+words?\s*\]$|^\[\s*\.+\s*words?\s*\]$", re.IGNORECASE)
_NAV_EDGE_SCAN = 7


def _strip_nav_edges(text: str) -> str:
    lines = text.splitlines()
    n = len(lines)
    if n < 8:
        return text
    EDGE = _NAV_EDGE_SCAN
    top_set = {lines[i].strip() for i in range(min(EDGE, n)) if lines[i].strip()}
    bot_set = {lines[n-1-i].strip() for i in range(min(EDGE, n)) if lines[n-1-i].strip()}
    repeated = top_set & bot_set

    def _is_nav(line: str) -> bool:
        s = line.strip()
        if not s: return True
        if _RE_WORD_COUNT_LINE.match(s): return True
        if len(s) <= 10 and re.match(r"^[A-Za-z\s]+$", s): return True
        return s in repeated

    last_top_nav = -1
    for i in range(min(EDGE, n)):
        if _is_nav(lines[i]):
            last_top_nav = i
    start = last_top_nav + 1
    while start < n and not lines[start].strip():
        start += 1
    end = n
    for i in range(min(EDGE, n)):
        idx = n - 1 - i
        if idx <= start: break
        if not lines[idx].strip() or _is_nav(lines[idx]):
            end = idx
        else:
            break
    while end > start and not lines[end-1].strip():
        end -= 1
    if start >= end:
        return text
    return "\n".join(lines[start:end])


# ── CPU-bound helpers ─────────────────────────────────────────────────────────

def _sync_parse_and_clean(html: str) -> tuple[BeautifulSoup, str]:
    soup = BeautifulSoup(html, "html.parser")
    remove_hidden_elements(soup)
    return soup, str(soup)


def _sync_detect_page_type(html: str, url: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    return detect_page_type(soup, url)


def _try_selector(soup: BeautifulSoup, selector: str) -> str | None:
    try:
        el = soup.select_one(selector)
        if el:
            text = extract_text_blocks(el)
            if len(text.strip()) > 200:
                return text
    except Exception:
        pass
    return None


def _sync_extract_content(
    soup: BeautifulSoup,
    profile: SiteProfileDict,
) -> tuple[str | None, str | None]:
    """
    Returns (content, winning_selector).

    Thứ tự:
      1. profile["working_content_selector"] — shortcut đã proven
      2. CONTENT_SELECTORS list
      3. profile["content_selector"] — AI-generated fallback
    """
    # 1. Shortcut
    working = profile.get("working_content_selector")
    if working:
        text = _try_selector(soup, working)
        if text:
            return text, working

    # 2. Hand-crafted list
    for sel in CONTENT_SELECTORS:
        text = _try_selector(soup, sel)
        if text:
            return text, sel

    # 3. AI selector
    ai_sel = profile.get("content_selector")
    if ai_sel and ai_sel not in CONTENT_SELECTORS:
        text = _try_selector(soup, ai_sel)
        if text:
            return text, ai_sel

    return None, None


# ── Story ID guard ────────────────────────────────────────────────────────────

def _check_story_id_guard(url: str, progress: ProgressDict) -> bool:
    if not progress.get("story_id_locked"):
        return True
    pattern = progress.get("story_id_regex")
    if not pattern:
        return True
    try:
        return bool(re.search(pattern, url))
    except re.error:
        return True


# ── Find start chapter ────────────────────────────────────────────────────────

async def check_and_find_start_chapter(
    start_url: str,
    progress_path: str,
    pool: DomainSessionPool,
    pw_pool: PlaywrightPool,
    pm: ProfileManager,
    ai_limiter: AIRateLimiter,
) -> tuple[str, ProgressDict]:
    progress = await load_progress(progress_path)

    if progress.get("current_url"):
        print(f"  [Resume] ▶ {progress['current_url'][:70]}", flush=True)
        return progress["current_url"], progress  # type: ignore[return-value]

    if progress.get("completed"):
        raise RuntimeError("Truyện đã hoàn thành, bỏ qua.")

    status, html = await fetch_page(start_url, pool, pw_pool)
    if status not in (200, 206):
        raise RuntimeError(f"HTTP {status}: {start_url}")
    if is_junk_page(html, status):
        raise RuntimeError(f"Trang khởi đầu lỗi/rỗng: {start_url}")

    page_type = await asyncio.to_thread(_sync_detect_page_type, html, start_url)

    # Path-A: URL không có pattern chương → force index
    if page_type == "chapter" and not RE_CHAP_URL.search(start_url):
        page_type = "index"

    if page_type == "chapter":
        domain  = urlparse(start_url).netloc.lower()
        profile = pm.get(domain)
        soup_check, _ = await asyncio.to_thread(_sync_parse_and_clean, html)
        content_check, _ = await asyncio.to_thread(_sync_extract_content, soup_check, profile)
        if content_check and len(content_check.strip()) > 200:
            print(f"  [Start] 📖 Chapter: {start_url[:70]}", flush=True)
            return start_url, progress
        print(f"  [Start] 🔄 Detect chapter nhưng không có content → fallback...", flush=True)

    print(f"  [Start] 📋 Tìm chapter đầu từ index...", flush=True)
    first_url = await ai_find_first_chapter_url(html, start_url, ai_limiter)
    if first_url and first_url != start_url:
        print(f"  [Start] ✅ {first_url[:70]}", flush=True)
        return first_url, progress

    print(f"  [Start] 🤖 AI classify...", flush=True)
    result: AiClassifyResult | None = await ai_classify_and_find(html, start_url, ai_limiter)
    if result:
        if result.get("page_type") == "chapter" and RE_CHAP_URL.search(start_url):
            return start_url, progress
        for key in ("first_chapter_url", "next_url"):
            found = result.get(key)  # type: ignore[literal-required]
            if found and found != start_url:
                print(f"  [Start] ✅ AI: {found[:70]}", flush=True)
                return found, progress

    raise RuntimeError(f"Không tìm được điểm bắt đầu: {start_url}")


# ── Next URL helper ───────────────────────────────────────────────────────────

async def _find_next_url_with_fallback(
    soup: BeautifulSoup,
    clean_html: str,
    url: str,
    profile: SiteProfileDict,
    ai_classify_cache: AiClassifyResult | None,
    ai_limiter: AIRateLimiter,
    pm: ProfileManager,
    domain: str,
) -> tuple[str | None, AiClassifyResult | None]:
    next_url = find_next_url(soup, url, profile)
    if next_url:
        return next_url, ai_classify_cache

    if ai_classify_cache is not None:
        return ai_classify_cache.get("next_url"), ai_classify_cache

    try:
        result = await ai_classify_and_find(clean_html, url, ai_limiter)
        if result:
            await pm.record_ai_fallback(domain)
            return result.get("next_url"), result
    except Exception as e:
        logger.warning("[NextURL] AI thất bại: %s", e)

    return None, None


# ── Scrape one chapter ────────────────────────────────────────────────────────

async def scrape_one_chapter(
    url: str,
    progress: ProgressDict,
    progress_path: str,
    output_dir: str,
    pool: DomainSessionPool,
    pw_pool: PlaywrightPool,
    pm: ProfileManager,
    ai_limiter: AIRateLimiter,
    title_extractor: TitleExtractor,
    ads_filter: SimpleAdsFilter,
) -> str | None:
    all_visited: set[str] = set(progress.get("all_visited_urls") or [])
    domain = urlparse(url).netloc.lower()

    if url in all_visited:
        return await _advance_past_visited(
            url, all_visited, progress, progress_path, pool, pw_pool, pm, ai_limiter)

    status, html = await fetch_page(url, pool, pw_pool)
    if is_junk_page(html, status):
        print(f"  [End] 🏁 Lỗi/hết truyện: {url[:60]}", flush=True)
        return None

    soup, clean_html = await asyncio.to_thread(_sync_parse_and_clean, html)

    # Guard: index page được resume nhầm
    if not RE_CHAP_URL.search(url):
        page_type_guard = await asyncio.to_thread(_sync_detect_page_type, html, url)
        if page_type_guard == "index":
            print(f"\n  ⚠️  [Guard] INDEX page!\n     {url[:70]}\n     👉 Xóa progress file.\n", flush=True)
            progress["completed"] = True
            progress["completed_at_url"] = url
            await save_progress(progress_path, progress)
            return None

    profile = pm.get(domain)

    # ── Extract content ───────────────────────────────────────────────────────
    content, winning_selector = await asyncio.to_thread(_sync_extract_content, soup, profile)

    ai_classify_cache: AiClassifyResult | None = None

    if content is None:
        # Build/update profile
        if not profile.get("content_selector"):
            print(f"  [Profile] 🔍 Build profile {domain}...", flush=True)
            new_data = await ask_ai_build_profile(clean_html, url, ai_limiter)
            if new_data:
                await pm.merge_ai_result(domain, new_data)
                profile = pm.get(domain)
                print(
                    f"  [Profile] ✅ content={new_data.get('content_selector')!r}"
                    f" next={new_data.get('next_selector')!r}"
                    f" dropdown={new_data.get('has_chapter_dropdown')}"
                    f" rel_next={new_data.get('has_rel_next')}"
                    f" pattern={new_data.get('chapter_url_pattern')!r}",
                    flush=True,
                )

        content, winning_selector = await asyncio.to_thread(_sync_extract_content, soup, profile)

    # Record selector outcome
    if winning_selector:
        await pm.record_content_hit(domain, winning_selector)
    elif content is None:
        await pm.record_extraction_failure(domain)

    # Background profile build cho domain mới ở chapter đầu
    if not profile.get("next_selector") and progress.get("chapter_count", 0) == 0:
        new_data = await ask_ai_build_profile(clean_html, url, ai_limiter)
        if new_data:
            await pm.merge_ai_result(domain, new_data)
            profile = pm.get(domain)

    # AI body fallback
    if content is None:
        try:
            ai_classify_cache = await ai_classify_and_find(clean_html, url, ai_limiter)
            await pm.record_ai_fallback(domain)
        except Exception as e:
            logger.warning("[Content] AI classify thất bại: %s", e)
        if ai_classify_cache and ai_classify_cache.get("page_type") == "chapter":
            body = soup.find("body")
            if body:
                content = extract_text_blocks(body)

    if not content or len(content.strip()) < 100:
        print(f"  [Skip] {len((content or '').strip())} ký tự: {url[:60]}", flush=True)
        next_url, ai_classify_cache = await _find_next_url_with_fallback(
            soup, clean_html, url, profile, ai_classify_cache, ai_limiter, pm, domain)
        if next_url and next_url not in all_visited and _check_story_id_guard(next_url, progress):
            all_visited.add(url)
            progress["all_visited_urls"] = list(all_visited)
            progress["current_url"]      = next_url
            await save_progress(progress_path, progress)
            return next_url
        return None

    content = clean_chapter_text(content)

    # Nav-edge strip — detect + record
    content_stripped = _strip_nav_edges(content)
    if content_stripped and len(content_stripped.strip()) >= 100:
        if content_stripped != content:
            if not profile.get("has_nav_edges"):
                await pm.record_nav_edges(domain)
                print(f"  [Profile] 📌 {domain}: has_nav_edges=True", flush=True)
        content = content_stripped

    # Ads filter
    content_before = content
    content = ads_filter.filter_content(content)
    removed = len(content_before) - len(content)
    if removed > 0:
        after_set = set(content.splitlines())
        removed_lines = [l.strip() for l in content_before.splitlines()
                         if l.strip() and l not in after_set]
        preview = " | ".join(removed_lines[:3])
        print(f"  [Ads] 🧹 -{removed} ký tự: {preview[:80]}", flush=True)

    # Fingerprint
    fp = make_fingerprint(content)
    fingerprints = set(progress.get("fingerprints") or [])
    if fp in fingerprints:
        print(f"  [Loop] ♻ Lặp: {url[:60]}", flush=True)
        return None
    fingerprints.add(fp)
    progress["fingerprints"] = list(fingerprints)

    title = normalize_title(await title_extractor.extract(soup, url, ai_limiter))
    if progress.get("chapter_count", 0) == 0 and not progress.get("story_title"):
        st = extract_story_title(soup, url)
        if st:
            progress["story_title"] = st

    chapter_num = progress.get("chapter_count", 0) + 1

    # Ads AI scan
    if chapter_num % ADS_AI_SCAN_EVERY == 1:
        ctx = ads_filter.build_ai_context_block(content_before)
        if ctx:
            print(f"  [Ads] 🤖 Scan ch.{chapter_num}...", flush=True)
            try:
                raw = await ai_detect_ads_content(ctx, ai_limiter)
                if raw:
                    added = ads_filter.update_from_ai_result(raw)
                    if added:
                        print(f"  [Ads] ✅ +{added} ({ads_filter.keyword_count}kw/{ads_filter.pattern_count}pat)", flush=True)
            except Exception as e:
                logger.warning("[Ads] Scan thất bại: %s", e)

    # Write file
    filename     = f"{chapter_num:04d}_{slugify_filename(title, max_len=60)}.md"
    await write_markdown(os.path.join(output_dir, filename), f"# {title}\n\n{content}\n")

    progress["chapter_count"]    = chapter_num
    progress["last_title"]       = title
    progress["last_scraped_url"] = url
    all_visited.add(url)
    progress["all_visited_urls"] = list(all_visited)

    # Record chapter done
    await pm.record_chapter_done(domain, url)

    print(f"  ✅ Ch.{chapter_num:>4}: {truncate(title, 45):<45} | {len(content):>5} ký tự", flush=True)

    # Story ID guard
    if not progress.get("story_id_locked"):
        collected: list[str] = progress.get("collected_urls") or []
        if url not in collected:
            collected.append(url)
        progress["collected_urls"] = collected[-_COLLECTED_URL_CAP:]
        if (len(progress["collected_urls"]) >= STORY_ID_LEARN_AFTER
                and progress.get("story_id_attempts", 0) < STORY_ID_MAX_ATTEMPTS):
            try:
                sid: StoryIdResult | None = await ask_ai_for_story_id(
                    progress["collected_urls"], ai_limiter)
                if sid:
                    progress["story_id"]        = sid.get("story_id")
                    progress["story_id_regex"]  = sid.get("story_id_regex")
                    progress["story_id_locked"] = True
                    print(f"  [Guard] 🔐 ID={sid.get('story_id')}", flush=True)
                    if sid.get("story_id_regex"):
                        await pm.update_chapter_url_pattern(domain, sid["story_id_regex"])
                else:
                    progress["story_id_attempts"] = progress.get("story_id_attempts", 0) + 1
            except Exception as e:
                logger.warning("[StoryID] thất bại: %s", e)
                progress["story_id_attempts"] = progress.get("story_id_attempts", 0) + 1

    # Find next URL
    next_url, ai_classify_cache = await _find_next_url_with_fallback(
        soup, clean_html, url, profile, ai_classify_cache, ai_limiter, pm, domain)

    if not next_url:
        progress["completed"] = True
        progress["completed_at_url"] = url
        await save_progress(progress_path, progress)
        print(f"  [End] 🏁 Hết truyện.", flush=True)
        return None

    if not _check_story_id_guard(next_url, progress):
        print(f"  [Guard] ⛔ URL bị chặn: {next_url[:60]}", flush=True)
        return None

    if next_url in all_visited:
        print(f"  [Loop] ♻ Đã thăm: {next_url[:60]}", flush=True)
        return None

    cur_domain  = urlparse(url).netloc
    next_domain = urlparse(next_url).netloc
    if not progress.get("story_id_locked") and next_domain != cur_domain:
        print(f"  [Guard] ⚠️ Domain: {cur_domain} → {next_domain}", flush=True)
        try:
            is_same = await ask_ai_confirm_same_story(
                title1=title, url1=url, title2="", url2=next_url, ai_limiter=ai_limiter)
        except Exception:
            is_same = True
        if not is_same:
            print(f"  [Guard] ⛔ Truyện khác: {next_url[:60]}", flush=True)
            progress["completed"] = True
            progress["completed_at_url"] = url
            await save_progress(progress_path, progress)
            return None

    progress["current_url"] = next_url
    await save_progress(progress_path, progress)
    return next_url


# ── Run novel task ────────────────────────────────────────────────────────────

async def run_novel_task(
    start_url: str,
    output_dir: str,
    progress_path: str,
    pool: DomainSessionPool,
    pw_pool: PlaywrightPool,
    profiles: dict[str, SiteProfileDict],
    profiles_lock: asyncio.Lock,
    ai_limiter: AIRateLimiter,
    on_chapter_done=None,
) -> None:
    os.makedirs(output_dir, exist_ok=True)
    pm             = ProfileManager(profiles, profiles_lock)
    title_extractor = TitleExtractor()
    ads_filter      = SimpleAdsFilter.load()
    consecutive_errors   = 0
    consecutive_timeouts = 0

    domain = urlparse(start_url).netloc.lower()
    if pm.has_profile(domain):
        print(f"  [Profile] 📂 {pm.summary(domain)}", flush=True)

    try:
        current_url, progress = await check_and_find_start_chapter(
            start_url, progress_path, pool, pw_pool, pm, ai_limiter)
    except Exception as e:
        print(f"  [ERR] Không tìm được điểm bắt đầu: {e}", flush=True)
        return

    print(f"\n🚀 {progress.get('story_title') or start_url[:50]}", flush=True)

    while current_url and progress.get("chapter_count", 0) < MAX_CHAPTERS:
        if progress.get("completed"):
            break
        await asyncio.sleep(get_delay_seconds(current_url))
        try:
            prev_count = progress.get("chapter_count", 0)
            next_url = await scrape_one_chapter(
                url=current_url, progress=progress, progress_path=progress_path,
                output_dir=output_dir, pool=pool, pw_pool=pw_pool, pm=pm,
                ai_limiter=ai_limiter, title_extractor=title_extractor, ads_filter=ads_filter,
            )
            consecutive_errors   = 0
            consecutive_timeouts = 0
            if on_chapter_done and progress.get("chapter_count", 0) > prev_count:
                await on_chapter_done()
            current_url = next_url

        except asyncio.CancelledError:
            print(f"  [Cancel] 🛑 Ch.{progress.get('chapter_count', 0)}", flush=True)
            try:
                await save_progress(progress_path, progress)
                await pm.close()
            except Exception:
                pass
            raise

        except asyncio.TimeoutError:
            consecutive_timeouts += 1
            wait = TIMEOUT_BACKOFF_BASE * consecutive_timeouts
            print(f"  [Timeout #{consecutive_timeouts}] {wait}s", flush=True)
            if consecutive_timeouts >= MAX_CONSECUTIVE_TIMEOUTS:
                break
            await asyncio.sleep(wait)

        except Exception as e:
            consecutive_errors += 1
            print(f"  [ERR #{consecutive_errors}] {type(e).__name__}: {e}", flush=True)
            if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                break

    total     = progress.get("chapter_count", 0)
    completed = progress.get("completed", False)
    label     = progress.get("story_title") or start_url[:50]

    await pm.close()
    await asyncio.to_thread(ads_filter.save)
    print(f"  [Ads] 💾 {ads_filter.keyword_count}kw/{ads_filter.pattern_count}pat → {_ADS_DB_FILE}", flush=True)
    print(f"  [Profile] 📊 {pm.summary(domain)}", flush=True)
    print(f"\n{'✔' if completed else '⏸'} {label} — {total} chương", flush=True)


# ── Private helpers ───────────────────────────────────────────────────────────

async def _advance_past_visited(
    url: str,
    all_visited: set[str],
    progress: ProgressDict,
    progress_path: str,
    pool: DomainSessionPool,
    pw_pool: PlaywrightPool,
    pm: ProfileManager,
    ai_limiter: AIRateLimiter,
) -> str | None:
    print(f"  [Resume] ⏭ {url[:60]}", flush=True)
    try:
        _, html = await fetch_page(url, pool, pw_pool)
    except Exception:
        return None
    soup, clean = await asyncio.to_thread(_sync_parse_and_clean, html)
    domain  = urlparse(url).netloc.lower()
    profile = pm.get(domain)
    next_url, _ = await _find_next_url_with_fallback(
        soup, clean, url, profile, None, ai_limiter, pm, domain)
    if next_url and next_url not in all_visited:
        progress["current_url"] = next_url
        await save_progress(progress_path, progress)
    return next_url if (next_url and next_url not in all_visited) else None