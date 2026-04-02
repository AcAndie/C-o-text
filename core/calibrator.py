# core/calibrator.py
"""
core/calibrator.py — Calibration phase: probe N chương đầu, học profile, retry.

FLOW:
  run_calibration_phase():
    ┌─ Trước round 1: build domain profile nếu chưa có
    │
    └─ Lặp round 1..CALIBRATION_MAX_ROUNDS:
         _scrape_chapter_probe() × CALIBRATION_CHAPTERS  → records[]
         Collect all issues từ records

         Nếu 0 issues → PASS → trả records để ghi file
         Nếu có issues:
           _build_calibration_report() → report text
           ask_ai_calibration_review() → fixes dict
           pm.merge_calibration_fixes()
           → retry từ cùng URLs

         Sau MAX_ROUNDS: _print_failure_report() → return None (dừng)

write_calibration_results():
  Ghi file từ records đã pass, cập nhật progress dict.
  Chỉ gọi 1 lần khi PASS — Option B: không ghi file trong quá trình probe.

DESIGN:
  - Không import từ core.scraper (tránh circular import)
  - Tái dùng helpers từ các module lá (fetch, navigator, html_filter, extractors)
  - Records tích lũy trong memory, ghi file chỉ khi PASS
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
from collections import Counter
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from config import (
    CALIBRATION_CHAPTERS, CALIBRATION_MAX_ROUNDS, CALIBRATION_MIN_CONTENT,
    CONTENT_SELECTORS, get_delay_seconds,
)
from utils.types import CalibrationIssue, CalibrationRecord, ProgressDict, SiteProfileDict
from utils.file_io import save_progress, write_markdown
from utils.string_helpers import (
    is_junk_page, clean_chapter_text, normalize_title,
    slugify_filename, truncate, extract_text_blocks, make_fingerprint,
)
from utils.ads_filter import SimpleAdsFilter
from core.fetch import fetch_page
from core.navigator import find_next_url
from core.html_filter import remove_hidden_elements
from core.extractors import TitleExtractor, extract_story_title
from core.profile_manager import ProfileManager
from core.session_pool import DomainSessionPool, PlaywrightPool
from ai.client import AIRateLimiter
from ai.agents import ask_ai_build_profile, ai_classify_and_find, ask_ai_calibration_review

logger = logging.getLogger(__name__)

# Regex copy từ scraper.py để tránh circular import
_RE_WORD_COUNT_LINE = re.compile(
    r"^\[\s*[\d,.\s]+words?\s*\]$|^\[\s*\.+\s*words?\s*\]$", re.IGNORECASE
)
_NAV_EDGE_SCAN = 7


# ── Pure helpers ──────────────────────────────────────────────────────────────

def _sync_parse_and_clean(html: str) -> tuple[BeautifulSoup, str]:
    """Parse HTML và remove hidden elements. Chạy trong thread pool."""
    soup = BeautifulSoup(html, "html.parser")
    remove_hidden_elements(soup)
    return soup, str(soup)


def _sync_extract_content(
    soup: BeautifulSoup,
    profile: SiteProfileDict,
) -> tuple[str | None, str | None]:
    """
    Thử extract content bằng selectors theo thứ tự ưu tiên.
    Returns (content_text, winning_selector) hoặc (None, None).
    """
    def _try(selector: str) -> str | None:
        try:
            el = soup.select_one(selector)
            if el:
                text = extract_text_blocks(el)
                if len(text.strip()) > 200:
                    return text
        except Exception:
            pass
        return None

    # 1. working_content_selector (proven)
    working = profile.get("working_content_selector")
    if working:
        t = _try(working)
        if t:
            return t, working

    # 2. Hand-crafted list
    for sel in CONTENT_SELECTORS:
        t = _try(sel)
        if t:
            return t, sel

    # 3. AI-generated selector
    ai_sel = profile.get("content_selector")
    if ai_sel and ai_sel not in CONTENT_SELECTORS:
        t = _try(ai_sel)
        if t:
            return t, ai_sel

    return None, None


def _strip_nav_edges(text: str) -> str:
    """Xóa nav header/footer lặp lại ở đầu/cuối content."""
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
        if not s:
            return True
        if _RE_WORD_COUNT_LINE.match(s):
            return True
        if len(s) <= 10 and re.match(r"^[A-Za-z\s]+$", s):
            return True
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
        if idx <= start:
            break
        if not lines[idx].strip() or _is_nav(lines[idx]):
            end = idx
        else:
            break

    while end > start and not lines[end-1].strip():
        end -= 1

    if start >= end:
        return text
    return "\n".join(lines[start:end])


def _is_suspicious_title(title: str) -> bool:
    """True nếu title trông như slug, số đơn thuần, hoặc fallback mặc định."""
    if not title or len(title) < 3:
        return True
    if title == "Không rõ tiêu đề":
        return True
    if title.isdigit():
        return True
    # Quá nhiều ký tự slug
    slug_chars = sum(1 for c in title if c in "-_/")
    if slug_chars > len(title) * 0.3:
        return True
    # Toàn lowercase + dash → trông như URL path
    if re.match(r"^[a-z0-9\-_]+$", title) and len(title) > 10:
        return True
    return False


# ── Core probe ────────────────────────────────────────────────────────────────

async def _scrape_chapter_probe(
    url: str,
    chapter_num: int,
    pool: DomainSessionPool,
    pw_pool: PlaywrightPool,
    pm: ProfileManager,
    ai_limiter: AIRateLimiter,
    title_extractor: TitleExtractor,
    ads_filter: SimpleAdsFilter,
    is_first_chapter: bool = False,
) -> CalibrationRecord:
    """
    Probe một chương: fetch → extract → validate — KHÔNG ghi file.
    Trả CalibrationRecord với đầy đủ issues và next_url để chain.
    """
    issues: list[CalibrationIssue] = []
    domain = urlparse(url).netloc.lower()

    # ── Fetch ─────────────────────────────────────────────────────────────────
    try:
        status, html = await fetch_page(url, pool, pw_pool)
    except asyncio.CancelledError:
        raise
    except Exception as e:
        issues.append({"issue_type": "fetch_failed", "detail": str(e)[:100]})
        return CalibrationRecord(
            chapter_num=chapter_num, url=url, title="(fetch failed)",
            content="", content_preview="", content_length=0,
            selector_used=None, title_source=None,
            ai_fallback_used=False, next_url=None,
            story_title=None, issues=issues,
        )

    if is_junk_page(html, status):
        issues.append({
            "issue_type": "fetch_failed",
            "detail": f"HTTP {status} hoặc junk page",
        })
        return CalibrationRecord(
            chapter_num=chapter_num, url=url, title="(junk page)",
            content="", content_preview="", content_length=0,
            selector_used=None, title_source=None,
            ai_fallback_used=False, next_url=None,
            story_title=None, issues=issues,
        )

    soup, clean_html = await asyncio.to_thread(_sync_parse_and_clean, html)
    profile = pm.get(domain)

    # ── Extract content ───────────────────────────────────────────────────────
    content, selector_used = await asyncio.to_thread(_sync_extract_content, soup, profile)
    ai_fallback_used = False

    if content is None:
        ai_fallback_used = True
        issues.append({
            "issue_type": "ai_fallback",
            "detail": "content selector thất bại — dùng AI/body fallback",
        })
        try:
            ai_result = await ai_classify_and_find(clean_html, url, ai_limiter)
            if ai_result and ai_result.get("page_type") == "chapter":
                body = soup.find("body")
                if body:
                    content = extract_text_blocks(body)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning("[Cal] AI classify thất bại ch.%d: %s", chapter_num, e)

    # ── Process content ───────────────────────────────────────────────────────
    processed = ""
    if content:
        processed = clean_chapter_text(content)
        processed = _strip_nav_edges(processed)
        filtered  = ads_filter.filter_content(processed)
        removed   = len(processed) - len(filtered)
        if removed > 0:
            processed = filtered

        # Còn suspicious content sau filter → leak
        suspicious_ctx = ads_filter.build_ai_context_block(processed)
        if suspicious_ctx:
            issues.append({
                "issue_type": "ads_leaked",
                "detail": f"~{len(suspicious_ctx)} chars suspicious sau filter",
            })

    # Kiểm tra độ dài
    content_len = len(processed.strip())
    if content_len < CALIBRATION_MIN_CONTENT:
        issues.append({
            "issue_type": "content_short",
            "detail": f"{content_len} chars (min {CALIBRATION_MIN_CONTENT})",
        })

    # ── Title ─────────────────────────────────────────────────────────────────
    try:
        title = normalize_title(
            await title_extractor.extract(soup, url, ai_limiter)
        )
    except asyncio.CancelledError:
        raise
    except Exception:
        title = "Không rõ tiêu đề"

    if _is_suspicious_title(title):
        issues.append({
            "issue_type": "title_suspicious",
            "detail": f"nhận được: {title!r} (source: {title_extractor.last_source})",
        })

    # Story title từ chương đầu tiên
    story_title: str | None = None
    if is_first_chapter:
        try:
            story_title = extract_story_title(soup, url)
        except Exception:
            pass

    # Record selector hit để ProfileManager học working_content_selector
    if selector_used and not ai_fallback_used:
        await pm.record_content_hit(domain, selector_used)

    # ── Next URL ──────────────────────────────────────────────────────────────
    next_url = find_next_url(soup, url, profile)
    ai_fallback_for_nav = False

    if not next_url:
        ai_fallback_for_nav = True
        try:
            ai_nav = await ai_classify_and_find(clean_html, url, ai_limiter)
            if ai_nav:
                next_url = ai_nav.get("next_url")
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning("[Cal] AI nav thất bại ch.%d: %s", chapter_num, e)

        if not next_url:
            issues.append({
                "issue_type": "no_next_url",
                "detail": "cả heuristic lẫn AI đều không tìm được URL tiếp theo",
            })
        elif not ai_fallback_used:
            # Chỉ log nav ai_fallback nếu content không đã log rồi
            issues.append({
                "issue_type": "ai_fallback",
                "detail": "next_selector thất bại — dùng AI để tìm next URL",
            })

    if ai_fallback_used or ai_fallback_for_nav:
        ai_fallback_used = True

    return CalibrationRecord(
        chapter_num      = chapter_num,
        url              = url,
        title            = title,
        content          = processed,
        content_preview  = processed[:300] if processed else "",
        content_length   = content_len,
        selector_used    = selector_used,
        title_source     = title_extractor.last_source,
        ai_fallback_used = ai_fallback_used,
        next_url         = next_url,
        story_title      = story_title,
        issues           = issues,
    )


# ── Report builders ───────────────────────────────────────────────────────────

def _build_calibration_report(
    records: list[CalibrationRecord],
    round_num: int,
    domain: str,
    pm: ProfileManager,
) -> str:
    """Format calibration results thành text để gửi ask_ai_calibration_review()."""
    issue_counts: Counter = Counter()
    for r in records:
        for issue in r.get("issues") or []:
            issue_counts[issue.get("issue_type", "unknown")] += 1

    lines: list[str] = [
        f"=== CALIBRATION REPORT — Round {round_num}/{CALIBRATION_MAX_ROUNDS} ===",
        f"Domain: {domain}",
        f"Chapters probed: {len(records)}",
        "",
    ]

    for r in records:
        r_issues = r.get("issues") or []
        lines.append(f"--- Chương {r.get('chapter_num', '?')} ---")
        lines.append(f"URL: {r.get('url', '')}")
        lines.append(
            f"Title: {r.get('title')!r} "
            f"(source: {r.get('title_source')})"
        )
        lines.append(
            f"Content: {r.get('content_length', 0)} chars | "
            f"selector: {r.get('selector_used')!r} | "
            f"AI fallback: {r.get('ai_fallback_used', False)}"
        )
        if r_issues:
            details = "; ".join(
                f"{i.get('issue_type')}: {i.get('detail')}"
                for i in r_issues
            )
            lines.append(f"Issues: {details}")
        preview = r.get("content_preview") or ""
        if preview:
            lines.append(f"Preview: {preview[:250]!r}")
        lines.append("")

    lines.append("=== ISSUE SUMMARY ===")
    if issue_counts:
        for issue_type, count in issue_counts.most_common():
            lines.append(f"  {issue_type}: {count}/{len(records)} chương")
    else:
        lines.append("  (không có issues)")

    lines.append("")
    lines.append("=== CURRENT PROFILE ===")
    lines.append(pm.get_observations_summary(domain))

    return "\n".join(lines)


def _print_issue_summary(
    records: list[CalibrationRecord],
    round_num: int,
) -> None:
    """In tóm tắt issues của một round ra console."""
    all_issues = [i for r in records for i in (r.get("issues") or [])]
    counts: Counter = Counter(i.get("issue_type", "?") for i in all_issues)

    print(
        f"  [Cal] ⚠️  Round {round_num}: "
        f"{len(all_issues)} issues / {len(records)} chương — "
        + " | ".join(f"{k}×{v}" for k, v in counts.most_common()),
        flush=True,
    )
    for r in records:
        r_issues = r.get("issues") or []
        if r_issues:
            names = ", ".join(i.get("issue_type", "?") for i in r_issues)
            print(
                f"         Ch.{r.get('chapter_num', '?'):>2} "
                f"[{names}] — {r.get('title')!r}",
                flush=True,
            )


def _print_failure_report(
    records: list[CalibrationRecord],
    domain: str,
    rounds_done: int,
) -> None:
    """
    In báo cáo lỗi chi tiết khi calibration thất bại sau MAX_ROUNDS.
    Giúp user tự điều tra và fix thủ công nếu cần.
    """
    all_issues = [i for r in records for i in (r.get("issues") or [])]
    counts: Counter = Counter(i.get("issue_type", "?") for i in all_issues)

    sep = "─" * 60
    print(f"\n{sep}", flush=True)
    print(
        f"❌ [Cal] CALIBRATION THẤT BẠI — {domain}\n"
        f"   {rounds_done} rounds / {CALIBRATION_CHAPTERS} chương / "
        f"{len(all_issues)} issues còn lại",
        flush=True,
    )
    print(sep, flush=True)
    print("Issue breakdown:", flush=True)
    for issue_type, count in counts.most_common():
        print(f"  • {issue_type}: {count}/{len(records)} chương", flush=True)

    print("\nChương chi tiết:", flush=True)
    for r in records:
        for i in (r.get("issues") or []):
            print(
                f"  Ch.{r.get('chapter_num', '?'):>2} "
                f"[{i.get('issue_type')}] {i.get('detail', '')}",
                flush=True,
            )

    first_url = records[0].get("url") if records else "(unknown)"
    print(
        f"\nGợi ý:\n"
        f"  1. Kiểm tra thủ công URL: {first_url}\n"
        f"  2. Xem site_profiles.json → domain '{domain}' để biết selectors hiện tại\n"
        f"  3. Xóa progress file nếu muốn thử lại từ đầu\n"
        f"  4. Tăng CALIBRATION_MAX_ROUNDS trong config.py nếu site phức tạp",
        flush=True,
    )
    print(sep, flush=True)


# ── Main calibration phase ────────────────────────────────────────────────────

async def run_calibration_phase(
    start_url: str,
    progress: ProgressDict,
    progress_path: str,
    pool: DomainSessionPool,
    pw_pool: PlaywrightPool,
    pm: ProfileManager,
    ai_limiter: AIRateLimiter,
    ads_filter: SimpleAdsFilter,
) -> list[CalibrationRecord] | None:
    """
    Chạy calibration phase: probe CALIBRATION_CHAPTERS chương đầu,
    phát hiện issues, gọi AI cải thiện profile, retry nếu cần.

    Returns:
      list[CalibrationRecord] — nếu PASS (0 issues), caller sẽ ghi file
      None                    — nếu thất bại sau MAX_ROUNDS
    """
    domain = urlparse(start_url).netloc.lower()

    # ── Bước 0: Build profile nếu chưa có ────────────────────────────────────
    if not pm.get(domain).get("content_selector"):
        print(f"  [Cal] 🔍 Build domain profile trước calibration...", flush=True)
        try:
            _, init_html = await fetch_page(start_url, pool, pw_pool)
            new_data = await ask_ai_build_profile(init_html, start_url, ai_limiter)
            if new_data:
                await pm.merge_ai_result(domain, new_data)
                wm_added  = ads_filter.inject_domain_keywords(pm.get_domain_watermarks(domain))
                pat_added = ads_filter.inject_domain_patterns(pm.get_domain_patterns(domain))
                if wm_added + pat_added > 0:
                    print(
                        f"  [Cal] 🔑 +{wm_added}kw +{pat_added}pat từ profile build",
                        flush=True,
                    )
                print(
                    f"  [Cal] ✅ Profile: "
                    f"content={new_data.get('content_selector')!r} "
                    f"next={new_data.get('next_selector')!r}",
                    flush=True,
                )
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning("[Cal] Profile build thất bại: %s", e)

    # ── Resume support ────────────────────────────────────────────────────────
    start_round = progress.get("calibration_round") or 1
    seed_urls: list[str] | None = progress.get("calibration_urls") or None
    # Chỉ dùng seed_urls nếu đang resume từ round > 1
    if start_round == 1:
        seed_urls = None

    print(
        f"  [Cal] 🔬 Calibration phase — "
        f"{CALIBRATION_CHAPTERS} chương × tối đa {CALIBRATION_MAX_ROUNDS} rounds",
        flush=True,
    )

    for round_num in range(start_round, CALIBRATION_MAX_ROUNDS + 1):
        print(f"  [Cal] ── Round {round_num}/{CALIBRATION_MAX_ROUNDS} ──", flush=True)

        round_start = (
            seed_urls[0]
            if (seed_urls and round_num > 1)
            else start_url
        )

        title_extractor = TitleExtractor()
        records: list[CalibrationRecord] = []
        current_url: str | None = round_start

        for chap_idx in range(CALIBRATION_CHAPTERS):
            if not current_url:
                logger.warning(
                    "[Cal] next_url = None tại ch.%d, dừng round sớm", chap_idx + 1
                )
                break

            print(
                f"  [Cal] Ch.{chap_idx + 1:>2}/{CALIBRATION_CHAPTERS} "
                f"{current_url[:65]}",
                flush=True,
            )

            record = await _scrape_chapter_probe(
                url              = current_url,
                chapter_num      = chap_idx + 1,
                pool             = pool,
                pw_pool          = pw_pool,
                pm               = pm,
                ai_limiter       = ai_limiter,
                title_extractor  = title_extractor,
                ads_filter       = ads_filter,
                is_first_chapter = (chap_idx == 0),
            )
            records.append(record)

            # Delay lịch sự giữa các chương
            if chap_idx < CALIBRATION_CHAPTERS - 1 and record.get("next_url"):
                await asyncio.sleep(get_delay_seconds(current_url))

            current_url = record.get("next_url")

        # Persist progress để có thể resume nếu bị ngắt
        probed_urls = [r.get("url", "") for r in records if r.get("url")]
        progress["calibration_urls"]  = probed_urls
        progress["calibration_round"] = round_num
        await save_progress(progress_path, progress)

        # ── Đánh giá round ────────────────────────────────────────────────────
        all_issues = [i for r in records for i in (r.get("issues") or [])]

        if not all_issues:
            # ✅ PASS — 0 issues
            print(
                f"  [Cal] ✅ PASS! Round {round_num} — "
                f"0 issues / {len(records)} chương",
                flush=True,
            )
            return records

        # Có issues → in summary
        _print_issue_summary(records, round_num)

        if round_num >= CALIBRATION_MAX_ROUNDS:
            # ❌ Hết rounds — báo lỗi chi tiết và dừng
            _print_failure_report(records, domain, round_num)
            return None

        # ── AI review → fix profile → retry ──────────────────────────────────
        print(f"  [Cal] 🤖 Gửi issues cho AI review...", flush=True)
        report = _build_calibration_report(records, round_num, domain, pm)

        try:
            fixes = await ask_ai_calibration_review(report, ai_limiter)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning("[Cal] AI calibration review thất bại: %s", e)
            fixes = None

        if fixes:
            updated = await pm.merge_calibration_fixes(domain, fixes)
            print(
                f"  [Cal] 🔧 Profile updated: {updated} field(s) — "
                f"content={fixes.get('content_selector')!r} "
                f"next={fixes.get('next_selector')!r} "
                f"nav_type={fixes.get('nav_type')!r}",
                flush=True,
            )
            # Inject watermarks mới vào ads_filter ngay
            wm_added  = ads_filter.inject_domain_keywords(pm.get_domain_watermarks(domain))
            pat_added = ads_filter.inject_domain_patterns(pm.get_domain_patterns(domain))
            if wm_added + pat_added > 0:
                print(
                    f"  [Cal] 🔑 +{wm_added}kw +{pat_added}pat sau AI fix",
                    flush=True,
                )
        else:
            print(
                f"  [Cal] ⚠️  AI không trả về fixes — thử lại với profile hiện tại",
                flush=True,
            )

        # seed_urls đã set → round tiếp theo probe cùng N URLs
        seed_urls = probed_urls

    # Không bao giờ đến đây (loop handles max rounds), nhưng safe fallback
    return None


# ── Write calibration results ─────────────────────────────────────────────────

async def write_calibration_results(
    records: list[CalibrationRecord],
    output_dir: str,
    progress: ProgressDict,
    progress_path: str,
) -> None:
    """
    Ghi kết quả calibration đã PASS vào file và cập nhật progress.

    Chỉ gọi 1 lần sau khi run_calibration_phase() trả về records (PASS).
    Option B: không có file nào được ghi trong quá trình probe.
    """
    all_visited: list[str] = []
    fingerprints: list[str] = []
    written_count = 0

    for r in records:
        chapter_num = r.get("chapter_num") or 0
        title   = r.get("title") or "Không rõ tiêu đề"
        content = r.get("content") or ""
        url     = r.get("url") or ""

        if not content.strip():
            logger.warning(
                "[Cal] Ch.%d có nội dung rỗng — bỏ qua ghi file", chapter_num
            )
            continue

        filename = f"{chapter_num:04d}_{slugify_filename(title, max_len=60)}.md"
        filepath = os.path.join(output_dir, filename)
        await write_markdown(filepath, f"# {title}\n\n{content}\n")

        all_visited.append(url)
        fingerprints.append(make_fingerprint(content))
        written_count += 1

        print(
            f"  ✅ [Cal] Ch.{chapter_num:>4}: "
            f"{truncate(title, 45):<45} | {len(content):>5} ký tự",
            flush=True,
        )

    # URL tiếp theo sau chương cuối cùng trong calibration
    last_record = records[-1] if records else None
    next_url    = last_record.get("next_url") if last_record else None

    # Story title từ chương đầu
    if not progress.get("story_title") and records:
        st = records[0].get("story_title")
        if st:
            progress["story_title"] = st

    # Cập nhật progress để main loop tiếp tục từ chương sau
    progress["chapter_count"]    = written_count
    progress["current_url"]      = next_url
    progress["all_visited_urls"] = all_visited
    progress["fingerprints"]     = fingerprints
    progress["calibration_done"] = True

    await save_progress(progress_path, progress)

    print(
        f"  [Cal] 💾 Đã ghi {written_count} chương | "
        f"Tiếp tục từ: {(next_url or 'N/A')[:60]}",
        flush=True,
    )