"""learner.py — Luồng học cấu trúc site tự động (learn_site) cho Cào Text v2.

Quy trình 6 bước (Phase 4):
1. Lấy mẫu: fetch 3–5 chương liên tiếp bằng nav heuristic.
   Phát hiện JS-heavy: text Playwright > 1.5x curl và chênh > 500 ký tự -> requires_playwright=True.
2. Ứng viên bằng code (learn/candidates.py): tìm ứng viên content/title/next và dòng rác lặp lại.
3. AI call #1 analyze_site: gửi DOM skeleton 2 chương + ứng viên -> nhận SiteAnalysisOutput (gồm cả đặt tên).
4. Kiểm chứng bằng code (learn/verify.py) V1–V6 trên toàn bộ mẫu.
5. Sai -> AI call #2/#3 repair_site kèm báo cáo lỗi cụ thể (tối đa 2 vòng).
   Vẫn sai -> dùng ứng viên tốt nhất từ bước 2, gán confidence <= 0.3, ghi issues.md.
6. Lưu SiteProfile v3 vào ProfileStore.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from cao_text.ai.prompts import prompt_analyze_site, prompt_repair_site
from cao_text.ai.provider import LLMProvider
from cao_text.ai.schemas import SiteAnalysisOutput, SiteRepairOutput
from cao_text.ai.skeleton import compress_dom_to_skeleton
from cao_text.extract.nav import find_next_url
from cao_text.learn.candidates import find_site_candidates
from cao_text.learn.verify import VerificationResult, verify_site_profile
from cao_text.log import IssueReporter
from cao_text.models import FormattingRules, SiteProfile
from cao_text.net.http import DomainSessionPool, get_delay
from cao_text.storage import ProfileStore

logger = logging.getLogger(__name__)

LEARNING_CHAPTERS_COUNT: int = 5
MIN_REQUIRED_SAMPLES: int = 3
MAX_REPAIR_ROUNDS: int = 2


@dataclass
class StoryNaming:
    """Thông tin đặt tên truyện và chuẩn hóa tiêu đề chương học được từ AI."""

    story_name_clean: str | None = None
    chapter_keyword: str = "Chapter"
    has_chapter_subtitle: bool = False
    story_prefix_strip: str | None = None


@dataclass
class LearningResult:
    """Kết quả hoàn chỉnh của phiên học cấu trúc trang web."""

    profile: SiteProfile
    naming: StoryNaming
    verification: VerificationResult
    ai_calls_count: int
    chapters: list[tuple[str, str]] = field(default_factory=list)
    used_fallback: bool = False


# ── Sample Chapter Fetcher ────────────────────────────────────────────────────


async def _fetch_sample_chapters(
    start_url: str,
    pool: DomainSessionPool | None,
    pw_pool: Any,
    max_chapters: int = LEARNING_CHAPTERS_COUNT,
) -> tuple[list[tuple[str, str]], bool]:
    """Tải 3–5 chương mẫu bằng navigation heuristic và phát hiện site có cần Playwright không."""
    chapters: list[tuple[str, str]] = []
    requires_playwright = False
    current_url = start_url
    referer: str | None = None

    if pool is None:
        raise ValueError("DomainSessionPool là bắt buộc khi tải chương qua mạng")

    domain = urlparse(start_url).netloc.lower()

    for i in range(max_chapters):
        if not current_url:
            break

        logger.info("[%s] Đang tải mẫu chương %d/%d: %s", domain, i + 1, max_chapters, current_url)

        try:
            # Chương 1: Kiểm tra JS-heavy bằng cách so sánh curl vs Playwright (nếu pw_pool khả dụng)
            if i == 0 and pw_pool is not None:
                pw_status, pw_html = await pw_pool.fetch(current_url, referer=referer)
                try:
                    curl_status, curl_html = await pool.fetch(current_url, referer=referer)
                    curl_len = len(BeautifulSoup(curl_html, "lxml").get_text(strip=True))
                    pw_len = len(BeautifulSoup(pw_html, "lxml").get_text(strip=True))

                    # Phát hiện JS-heavy: text Playwright > 1.5x curl và chênh > 500 ký tự
                    if pw_len > curl_len * 1.5 and (pw_len - curl_len) > 500:
                        logger.info(
                            "[%s] Phát hiện JS-heavy site (curl=%d, pw=%d, ratio=%.1f) -> requires_playwright=True",
                            domain,
                            curl_len,
                            pw_len,
                            pw_len / max(1, curl_len),
                        )
                        requires_playwright = True
                except Exception as e:
                    logger.debug("[%s] Lỗi fetch curl Ch.1 để đo JS-heavy: %s", domain, e)

                html = pw_html if requires_playwright else curl_html
                status = pw_status if requires_playwright else curl_status
            else:
                # Các chương tiếp theo: tải qua Playwright nếu đã gắn cờ requires_playwright, ngược lại dùng curl
                if requires_playwright and pw_pool is not None:
                    status, html = await pw_pool.fetch(current_url, referer=referer)
                else:
                    status, html = await pool.fetch(current_url, referer=referer)

        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning("[%s] Tải mẫu chương %d thất bại: %s", domain, i + 1, e)
            break

        # Kiểm tra nội dung rỗng / lỗi
        if status >= 400 or len(html.strip()) < 200:
            logger.warning("[%s] Mẫu chương %d trả về status=%d hoặc HTML quá ngắn", domain, i + 1, status)
            break

        chapters.append((current_url, html))

        # Tìm URL chương tiếp theo bằng heuristic
        if i < max_chapters - 1:
            soup = BeautifulSoup(html, "lxml")
            next_url, _ = find_next_url(soup, current_url, profile=None)
            if not next_url:
                logger.warning("[%s] Không tìm thấy URL chương tiếp theo sau chương %d", domain, i + 1)
                break

            referer = current_url
            current_url = next_url
            delay = get_delay(current_url)
            if delay > 0:
                await asyncio.sleep(delay)

    return chapters, requires_playwright


# ── Main Learning Orchestrator ────────────────────────────────────────────────


async def learn_site(
    start_url: str,
    ai_provider: LLMProvider,
    *,
    pool: DomainSessionPool | None = None,
    pw_pool: Any = None,
    profile_store: ProfileStore | None = None,
    issue_reporter: IssueReporter | None = None,
    prefetched_samples: list[tuple[str, str]] | None = None,
    max_chapters: int = LEARNING_CHAPTERS_COUNT,
    max_repair_rounds: int = MAX_REPAIR_ROUNDS,
    auto_save: bool = True,
) -> LearningResult:
    """Học cấu trúc trang web: lấy mẫu -> tìm ứng viên -> AI phân tích -> kiểm chứng V1–V6 -> sửa lỗi -> lưu."""
    domain = urlparse(start_url).netloc.lower()
    logger.info("[%s] Bắt đầu học cấu trúc site từ: %s", domain, start_url)

    # ── Bước 1: Lấy mẫu ───────────────────────────────────────────────────────
    if prefetched_samples:
        chapters = list(prefetched_samples[:max_chapters])
        requires_playwright = False
        logger.info("[%s] Sử dụng %d mẫu chương có sẵn", domain, len(chapters))
    else:
        chapters, requires_playwright = await _fetch_sample_chapters(
            start_url,
            pool=pool,
            pw_pool=pw_pool,
            max_chapters=max_chapters,
        )

    if len(chapters) < MIN_REQUIRED_SAMPLES:
        msg = f"Không đủ mẫu chương để học site {domain} (yêu cầu ≥{MIN_REQUIRED_SAMPLES}, chỉ lấy được {len(chapters)})"
        if issue_reporter:
            issue_reporter.report("LEARNING_FAILED", start_url, msg)
            issue_reporter.summarize(len(chapters))
        raise RuntimeError(msg)

    # Parse soup một lần duy nhất cho toàn bộ quá trình học
    soups = [BeautifulSoup(h, "lxml") for _, h in chapters]

    # ── Bước 2: Tìm ứng viên bằng code ────────────────────────────────────────
    candidates = find_site_candidates(chapters)
    logger.info(
        "[%s] Ứng viên code thuần: content=%r (tight=%s), title=%r, next=%r (%s)",
        domain,
        candidates.best_content_selector,
        candidates.content_candidates[0].is_tight_wrapper if candidates.content_candidates else False,
        candidates.best_title_selector,
        candidates.best_next_selector,
        candidates.best_nav_type,
    )

    # ── Bước 3: AI call #1 analyze_site ───────────────────────────────────────
    # Nén DOM skeleton cho 2 chương đầu (hoặc 1 chương)
    sk1 = compress_dom_to_skeleton(chapters[0][1], max_chars=4000)
    sk2 = compress_dom_to_skeleton(chapters[1][1], max_chars=4000) if len(chapters) >= 2 else None
    skeletons = [sk1, sk2] if sk2 else sk1
    sample_urls = [chapters[0][0], chapters[1][0]] if sk2 else chapters[0][0]

    prompt = prompt_analyze_site(
        skeleton=skeletons,
        url=sample_urls,
        candidates=candidates.to_prompt_dict(),
        repeated_lines=candidates.repeated_lines[:20],
        raw_titles=candidates.raw_titles[:5],
    )

    logger.info("[%s] Gửi yêu cầu phân tích DOM skeleton (AI call #1)...", domain)
    analysis: SiteAnalysisOutput = await ai_provider.generate(prompt, SiteAnalysisOutput)
    ai_calls = 1

    # Trích xuất thông tin đặt tên từ kết quả AI
    naming = StoryNaming(
        story_name_clean=analysis.story_name_clean,
        chapter_keyword=analysis.chapter_keyword,
        has_chapter_subtitle=analysis.has_chapter_subtitle,
        story_prefix_strip=analysis.story_prefix_strip,
    )

    # Cấu hình profile ban đầu do AI đề xuất
    content_selector = analysis.content_selector
    title_selector = analysis.title_selector
    next_selector = analysis.next_selector
    nav_type = analysis.nav_type
    remove_selectors = list(
        dict.fromkeys(list(analysis.remove_selectors) + list(analysis.watermark_selectors))
    )
    ads_keywords = list(analysis.ads_keywords)
    formatting_rules: FormattingRules = analysis.build_formatting_rules()
    download_images = analysis.download_images
    image_selector = analysis.image_selector
    requires_playwright = requires_playwright or analysis.requires_playwright

    candidate_profile_dict: dict[str, Any] = {
        "content_selector": content_selector,
        "title_selector": title_selector,
        "next_selector": next_selector,
        "nav_type": nav_type,
        "remove_selectors": remove_selectors,
        "ads_keywords": ads_keywords,
    }

    # ── Bước 4: Kiểm chứng bằng code V1–V6 ────────────────────────────────────
    v_res = verify_site_profile(candidate_profile_dict, chapters, soups=soups)
    logger.info("[%s] Kết quả kiểm chứng ban đầu: passed=%s", domain, v_res.passed)

    # ── Bước 5: Sai -> AI call #2/#3 repair_site ──────────────────────────────
    used_fallback = False
    confidence = 1.0

    if not v_res.passed:
        for round_idx in range(1, max_repair_rounds + 1):
            failure_reason = v_res.summary()
            logger.warning(
                "[%s] Kiểm chứng thất bại vòng %d/%d. Báo lỗi cho AI sửa (AI call #%d):\n%s",
                domain,
                round_idx,
                max_repair_rounds,
                ai_calls + 1,
                failure_reason,
            )

            repair_prompt = prompt_repair_site(
                skeleton=sk1,
                url=chapters[0][0],
                current_profile=candidate_profile_dict,
                failure_reason=failure_reason,
            )

            repair_out: SiteRepairOutput = await ai_provider.generate(repair_prompt, SiteRepairOutput)
            ai_calls += 1

            # Áp dụng các thay đổi sửa lỗi
            if repair_out.content_selector:
                content_selector = repair_out.content_selector
                candidate_profile_dict["content_selector"] = content_selector
            if repair_out.title_selector:
                title_selector = repair_out.title_selector
                candidate_profile_dict["title_selector"] = title_selector
            if repair_out.next_selector:
                next_selector = repair_out.next_selector
                candidate_profile_dict["next_selector"] = next_selector
            if repair_out.nav_type:
                nav_type = repair_out.nav_type
                candidate_profile_dict["nav_type"] = nav_type

            for r in repair_out.remove_selectors_to_add:
                if r not in remove_selectors:
                    remove_selectors.append(r)
            for r in repair_out.remove_selectors_to_remove:
                if r in remove_selectors:
                    remove_selectors.remove(r)
            candidate_profile_dict["remove_selectors"] = remove_selectors

            # Tái kiểm chứng sau khi sửa
            v_res = verify_site_profile(candidate_profile_dict, chapters, soups=soups)
            if v_res.passed:
                logger.info("[%s] Đã sửa lỗi thành công ở vòng %d!", domain, round_idx)
                break

        # Nếu sau tối đa các vòng sửa lỗi mà vẫn thất bại -> fallback về ứng viên heuristic bước 2
        if not v_res.passed:
            logger.warning(
                "[%s] Vẫn không qua kiểm chứng sau %d lần sửa lỗi. Fallback về ứng viên code thuần bước 2",
                domain,
                max_repair_rounds,
            )
            used_fallback = True
            confidence = 0.3
            content_selector = candidates.best_content_selector
            title_selector = candidates.best_title_selector
            next_selector = candidates.best_next_selector
            nav_type = candidates.best_nav_type
            remove_selectors = []

            # Ghi nhận sự cố vào issues.md
            if issue_reporter:
                issue_reporter.report(
                    issue_type="LEARNING_FAILED",
                    url=start_url,
                    detail=(
                        f"AI learning failed after {ai_calls} calls. "
                        f"Fallback confidence=0.3 với selector={content_selector!r}.\n{v_res.summary()}"
                    ),
                )
                issue_reporter.summarize(len(chapters))

    # ── Bước 6: Lưu profile v3 ────────────────────────────────────────────────
    final_profile = SiteProfile(
        domain=domain,
        confidence=confidence,
        profile_version=3,
        content_selector=content_selector,
        next_selector=next_selector,
        title_selector=title_selector,
        remove_selectors=remove_selectors,
        nav_type=nav_type,
        requires_playwright=requires_playwright,
        formatting_rules=formatting_rules,
        ads_keywords_learned=ads_keywords,
        sample_urls=[url for url, _ in chapters],
        download_images=download_images,
        image_selector=image_selector,
        notes=analysis.notes,
    )

    if auto_save and profile_store is not None:
        logger.info("[%s] Lưu profile v3 vào ProfileStore (confidence=%.2f)", domain, confidence)
        await profile_store.save(final_profile)

    return LearningResult(
        profile=final_profile,
        naming=naming,
        verification=v_res,
        ai_calls_count=ai_calls,
        chapters=chapters,
        used_fallback=used_fallback,
    )
