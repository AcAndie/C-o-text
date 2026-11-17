"""tests/test_web_session.py — Kiểm tra ScrapeSession, Outcome enum và các guard §6.2 (Task 5.2)."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from cao_text.ai.fake import FakeProvider
from cao_text.ai.schemas import (
    ExtractedContentOutput,
    PageClassificationOutput,
    VerifyAdsOutput,
)
from cao_text.html.ads import (
    AdsFilter,
    compute_auto_threshold,
    is_likely_dialogue_or_scene_break,
    is_valid_ads_keyword,
)
from cao_text.log import IssueReporter
from cao_text.models import RunConfig, SiteProfile
from cao_text.storage import ProfileStore, ProgressStore
from cao_text.web.session import (
    Outcome,
    ScrapeSession,
    is_junk_page,
    make_fingerprint,
)


class FakePool:
    """Fake HTTP pool trả về (status, html) phục vụ test offline 100%."""

    def __init__(self, pages: dict[str, tuple[int, str] | list[tuple[int, str]]]) -> None:
        self.pages = pages
        self.calls: list[str] = []

    async def fetch(self, url: str, timeout: float | None = None, referer: str | None = None) -> tuple[int, str]:
        self.calls.append(url)
        entry = self.pages.get(url)
        if entry is None:
            return 404, "<html><head><title>404 Not Found</title></head><body>Not found</body></html>"
        if isinstance(entry, list):
            if len(entry) > 1:
                return entry.pop(0)
            return entry[0]
        return entry


def _make_chapter_html(
    title: str,
    body_text: str,
    next_url: str | None = None,
    story_title: str = "Test Novel",
) -> str:
    next_link = f'<a class="btn-next" rel="next" href="{next_url}">Next Chapter</a>' if next_url else ""
    return f"""<!DOCTYPE html>
<html>
<head><title>{title} | {story_title}</title></head>
<body>
    <h1 class="chap-title">{title}</h1>
    <div class="chapter-content">
        <p>{body_text}</p>
        <p>Additional narrative prose to ensure content exceeds minimum length requirements easily.</p>
        <p>More storytelling sentences describing the journey of the protagonist across the realm.</p>
    </div>
    <div class="nav">{next_link}</div>
</body>
</html>
"""


def _default_profile(domain: str = "example.com") -> SiteProfile:
    return SiteProfile(
        domain=domain,
        content_selector="div.chapter-content",
        title_selector="h1.chap-title",
        next_selector="a.btn-next",
        nav_type="selector",
    )


async def _noop_sleep(_: float) -> None:
    return None


# ── Helper Tests ──────────────────────────────────────────────────────────────

def test_make_fingerprint_and_is_junk_page() -> None:
    fp1 = make_fingerprint("Hello   world\n\nparagraph")
    fp2 = make_fingerprint("Hello world paragraph")
    assert fp1 == fp2
    assert len(fp1) == 16

    # HTTP 429 KHÔNG được coi là junk page (§6.2)
    long_html = "<html><head><title>Chapter 1</title></head><body>" + "A" * 300 + "</body></html>"
    assert is_junk_page(long_html, 200) is False
    assert is_junk_page(long_html, 429) is False
    assert is_junk_page(long_html, 404) is True
    assert is_junk_page(long_html, 403) is True
    assert is_junk_page("short", 200) is True
    assert is_junk_page("<html><head><title>404 Not Found</title></head><body>" + "X" * 300 + "</body></html>", 200) is True


# ── ScrapeSession Core & §6.2 Guards ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_scrape_session_happy_path_and_index_generation(tmp_path: Path) -> None:
    """Cào 3 chương liên tiếp -> Outcome.WROTE, tạo file .md + 0000_Index.md, đánh dấu completed."""
    ch1_url = "https://example.com/fiction/100/chapter/1"
    ch2_url = "https://example.com/fiction/100/chapter/2"
    ch3_url = "https://example.com/fiction/100/chapter/3"

    pool = FakePool({
        ch1_url: (200, _make_chapter_html("Chapter 1: Awakening", "Unique chapter 1 prose " * 10, ch2_url)),
        ch2_url: (200, _make_chapter_html("Chapter 2: Training", "Unique chapter 2 prose " * 10, ch3_url)),
        ch3_url: (200, _make_chapter_html("Chapter 3: Victory", "Unique chapter 3 prose " * 10, None)),
    })

    progress_store = ProgressStore(base_dir=tmp_path / "progress")
    out_root = tmp_path / "output"
    run_cfg = RunConfig.create_for_mode("obsidian", str(out_root))

    session = ScrapeSession(
        start_url=ch1_url,
        profile=_default_profile(),
        pool=pool,
        progress_store=progress_store,
        run_config=run_cfg,
        sleep_fn=_noop_sleep,
    )

    final_state = await session.run()
    assert final_state.chapter_count == 3
    assert final_state.completed is True
    assert final_state.completed_at_url == ch3_url
    assert final_state.story_id_locked is True

    # Kiểm tra file đã ghi và 0000_Index.md
    md_files = sorted(session.output_dir.glob("*.md"))
    names = [f.name for f in md_files]
    assert "0000_Index.md" in names
    assert len(md_files) == 4  # 3 chương + 1 index


@pytest.mark.asyncio
async def test_scrape_session_guards_duplicate_and_story_id(tmp_path: Path) -> None:
    """Kiểm tra guard trùng fingerprint (không dùng slug_increment) và Story-ID guard."""
    ch1_url = "https://example.com/fiction/100/chapter-1"
    ch2_url = "https://example.com/fiction/100/chapter-2"
    ch3_url = "https://example.com/fiction/100/chapter-3"
    other_story_url = "https://example.com/fiction/999/chapter-1"

    same_prose = "Identical locked chapter prose content repeated verbatim " * 10
    pool = FakePool({
        ch1_url: (200, _make_chapter_html("Chapter 1", same_prose, ch2_url)),
        # Chương 2 trùng nội dung với chương 1, nhưng có link sang chương 3
        ch2_url: (200, _make_chapter_html("Chapter 2 Locked", same_prose, ch3_url)),
        # Chương 3 có next_url nhảy sang truyện khác (/fiction/999/) -> phải bị Story-ID guard chặn
        ch3_url: (200, _make_chapter_html("Chapter 3 Real", "Brand new prose for chapter 3 " * 10, other_story_url)),
        other_story_url: (200, _make_chapter_html("Other Story Ch 1", "Other story prose " * 10, None)),
    })

    progress_store = ProgressStore(base_dir=tmp_path / "progress")
    run_cfg = RunConfig.create_for_mode("raw", str(tmp_path / "out"))

    session = ScrapeSession(
        start_url=ch1_url,
        profile=_default_profile(),
        pool=pool,
        progress_store=progress_store,
        run_config=run_cfg,
        sleep_fn=_noop_sleep,
    )

    await session.setup()
    r1 = await session.step(ch1_url)
    assert r1.outcome == Outcome.WROTE
    assert r1.chapter_num == 1

    # Bước 2: Nội dung trùng fingerprint -> Outcome.DUPLICATE, nhảy sang ch3_url, chapter_count vẫn là 1
    r2 = await session.step(ch2_url)
    assert r2.outcome == Outcome.DUPLICATE
    assert r2.next_url == ch3_url
    assert session.state.chapter_count == 1

    # Bước 3: Ghi chương 2 thực tế (từ ch3_url), nhưng chặn next_url sang /fiction/999/
    r3 = await session.step(ch3_url)
    assert r3.outcome == Outcome.WROTE
    assert r3.chapter_num == 2
    assert r3.next_url is None
    assert r3.detail == "stopped_story_id_guard"


@pytest.mark.asyncio
async def test_scrape_session_guards_empty_streak_429_blocked_and_index(tmp_path: Path) -> None:
    """Kiểm tra MAX_EMPTY_STREAK, HTTP 429 retry, 403 BLOCKED và Index Page Guard."""
    ch1_url = "https://example.com/fiction/100/chapter/1"
    ch2_url = "https://example.com/fiction/100/chapter/2"
    toc_url = "https://example.com/fiction/100/chapters"

    # 1. Test HTTP 429 lần đầu -> RATE_LIMITED, lần 2 -> 200 OK, sau đó nhảy về trang mục lục (index guard)
    toc_html = """<!DOCTYPE html>
    <html>
    <head><title>Table of Contents | Test Novel</title></head>
    <body>
        <h1>Table of Contents</h1>
        <div class="chapter-content"><p> Some text </p></div>
    </body>
    </html>
    """
    pool = FakePool({
        ch1_url: [
            (429, ""),  # Lần 1: 429 rỗng -> phải raise RateLimitedError và được retry
            (200, _make_chapter_html("Chapter 1", "Valid chapter 1 text " * 10, toc_url)),
        ],
        toc_url: (200, toc_html),
        ch2_url: (403, "<html><head><title>Access Denied</title></head><body>Blocked</body></html>"),
    })

    progress_store = ProgressStore(base_dir=tmp_path / "progress")
    reporter = IssueReporter(domain="example.com", issues_file=tmp_path / "issues.md")
    run_cfg = RunConfig.create_for_mode("raw", str(tmp_path / "out"))

    session = ScrapeSession(
        start_url=ch1_url,
        profile=_default_profile(),
        pool=pool,
        progress_store=progress_store,
        issue_reporter=reporter,
        run_config=run_cfg,
        sleep_fn=_noop_sleep,
    )

    state = await session.run()
    # Chương 1 đã vượt qua 429 ở lần thử thứ 2, sau đó gặp toc_url (Index page guard) -> completed=True
    assert state.chapter_count == 1
    assert state.completed is True
    assert state.completed_at_url == toc_url

    # 2. Kiểm tra 403 trả về Outcome.BLOCKED và ghi issue BLOCKED
    blocked_res = await session.step(ch2_url)
    assert blocked_res.outcome == Outcome.BLOCKED
    assert any(i.issue_type == "BLOCKED" for i in reporter.issues)

    # 3. Kiểm tra 5 chương rỗng liên tiếp -> dừng ở MAX_EMPTY_STREAK
    empty_pages: dict[str, Any] = {}
    for i in range(1, 8):
        u = f"https://example.com/fiction/200/chapter/{i}"
        nxt = f"https://example.com/fiction/200/chapter/{i + 1}"
        empty_pages[u] = (
            200,
            f"<html><head><title>Ch {i}</title></head><body>"
            + "<!-- padding -->" * 20
            + f'<div class="chapter-content"><p>Too short</p></div><a class="btn-next" href="{nxt}">Next</a></body></html>',
        )

    empty_session = ScrapeSession(
        start_url="https://example.com/fiction/200/chapter/1",
        profile=_default_profile(),
        pool=FakePool(empty_pages),
        progress_store=progress_store,
        issue_reporter=reporter,
        run_config=run_cfg,
        max_empty_streak=5,
        sleep_fn=_noop_sleep,
    )
    empty_state = await empty_session.run()
    assert empty_state.chapter_count == 0
    assert empty_session.consecutive_empty == 5
    assert any(i.issue_type == "EMPTY_STREAK" for i in reporter.issues)


@pytest.mark.asyncio
async def test_scrape_session_ai_fallbacks_task_5_3(tmp_path: Path) -> None:
    """Task 5.3: AI fallback tường minh chỉ gọi khi thiếu content (extract_content) hoặc thiếu next (classify_page), ghi issues.md."""
    ch1_url = "https://example.com/fiction/300/chapter/1"
    ch2_url = "https://example.com/fiction/300/chapter/2"
    ch3_url = "https://example.com/fiction/300/chapter/3"

    # Chương 1: có đủ content nhưng thiếu nút next chuẩn (chỉ có link lạ không khớp heuristic)
    ch1_html = """<!DOCTYPE html>
    <html>
    <head><title>Chapter 1 | Mystic Novel</title></head>
    <body>
        <h1 class="chap-title">Chapter 1: The Portal</h1>
        <div class="chapter-content">
            <p>""" + ("Valid prose for chapter one with rich narrative details. " * 8) + """</p>
            <p>""" + ("More paragraphs of story text to pass all validation checks. " * 8) + """</p>
        </div>
        <div class="weird-nav"><a href="/fiction/300/chapter/2">Proceed Forward</a></div>
    </body>
    </html>
    """

    # Chương 2: Đổi cấu trúc DOM khiến selector div.chapter-content không khớp (PageResult rỗng),
    # nhưng văn bản thật nằm trong thẻ <custom-story> -> cần AI extract_content cứu!
    full_ch2_paragraph = "This is a very long paragraph inside a custom tag that exceeds 80 chars easily so skeleton truncation would have destroyed it if used."
    ch2_html = f"""<!DOCTYPE html>
    <html>
    <head><title>Chapter 2 | Mystic Novel</title></head>
    <body>
        <h1>Chapter 2: Hidden Realm</h1>
        <custom-story>{full_ch2_paragraph}</custom-story>
        <a class="btn-next" rel="next" href="{ch3_url}">Next Chapter</a>
    </body>
    </html>
    """

    # Chương 3: Đầy đủ content, chương cuối (không có next)
    ch3_html = _make_chapter_html("Chapter 3: Finale", "Final chapter prose text " * 12, None)

    pool = FakePool({
        ch1_url: (200, ch1_html),
        ch2_url: (200, ch2_html),
        ch3_url: (200, ch3_html),
    })

    fake_ai = FakeProvider()
    # Cấu hình classify_page cho Ch1 (tìm next_chapter_url -> ch2_url) và Ch3 (chương cuối -> None, dù có first_chapter_url cũng không nhảy lùi)
    fake_ai.enqueue_responses([
        PageClassificationOutput(
            page_type="chapter",
            next_chapter_url="/fiction/300/chapter/2",
            first_chapter_url="/fiction/300/chapter/1",
            confidence=0.9,
        ),
        ExtractedContentOutput(
            title="Chapter 2: Hidden Realm",
            content_text=(full_ch2_paragraph + "\n\n") * 3,
            next_url=ch3_url,
        ),
        PageClassificationOutput(
            page_type="chapter",
            next_chapter_url=None,
            first_chapter_url="/fiction/300/chapter/1",
            confidence=0.9,
        ),
    ])

    issues_path = tmp_path / "issues.md"
    reporter = IssueReporter(domain="example.com", story_label="Mystic Novel", issues_file=issues_path)
    progress_store = ProgressStore(base_dir=tmp_path / "progress")
    run_cfg = RunConfig.create_for_mode("obsidian", str(tmp_path / "out"))

    session = ScrapeSession(
        start_url=ch1_url,
        profile=_default_profile(),
        pool=pool,
        progress_store=progress_store,
        ai_provider=fake_ai,
        issue_reporter=reporter,
        run_config=run_cfg,
        sleep_fn=_noop_sleep,
    )

    state = await session.run()
    assert state.chapter_count == 3
    assert state.completed is True
    assert state.completed_at_url == ch3_url

    # Kiểm tra prompt gửi cho AI extract_content ở Ch2 phải chứa toàn bộ câu dài >80 ký tự (không bị skeleton cắt ngắn)
    extract_calls = [c for c in fake_ai.calls if c.schema is ExtractedContentOutput]
    assert len(extract_calls) == 1
    assert full_ch2_paragraph in extract_calls[0].prompt

    # Kiểm tra issues.md đã ghi nhận cả CONTENT_SUSPICIOUS (AI extract_content) và NEXT_URL_MISSING (AI classify_page)
    issue_types = [i.issue_type for i in reporter.issues]
    assert "CONTENT_SUSPICIOUS" in issue_types
    assert "NEXT_URL_MISSING" in issue_types
    issues_md = issues_path.read_text(encoding="utf-8")
    assert "recovered via AI extract_content fallback" in issues_md
    assert "recovered via AI classify_page fallback" in issues_md


def test_ads_filter_validation_and_threshold_rules() -> None:
    """Task 5.4 & §6.5, §7.3: Kiểm tra quy tắc từ khóa quảng cáo, ngưỡng scale theo số chương và bảo vệ thoại ngắn."""
    assert is_valid_ads_keyword("Support the author on Patreon today", story_title="My Novel") is True
    assert is_valid_ads_keyword("short") is False
    assert is_valid_ads_keyword("<script>alert(1)</script>") is False
    assert is_valid_ads_keyword("# Chapter 1") is False
    assert is_valid_ads_keyword("https://example.com/ad") is False
    assert is_valid_ads_keyword("Next Chapter") is False
    assert is_valid_ads_keyword("login") is False
    assert is_valid_ads_keyword("My Novel", story_title="My Novel") is False

    # Ngưỡng §7.3: max(10, ceil(0.03 * total_chapters))
    assert compute_auto_threshold(20) == 10
    assert compute_auto_threshold(1500) == 45

    # Bảo vệ câu thoại ngắn / chuyển cảnh (§7.3)
    assert is_likely_dialogue_or_scene_break("Hàn Tuyệt nói:") is True
    assert is_likely_dialogue_or_scene_break("Cùng lúc đó.") is True
    assert is_likely_dialogue_or_scene_break('"Chạy mau!"') is True
    # Nếu có dấu hiệu watermark/URL thì không bảo vệ
    assert is_likely_dialogue_or_scene_break("Read on royalroad.com:") is False


@pytest.mark.asyncio
async def test_scrape_session_ads_filter_two_pass_and_finalize_task_5_4(tmp_path: Path) -> None:
    """Task 5.4: AdsFilter 2-pass (trước/sau strip_nav_edges), quét cạnh, AI xác minh nhóm 3-9 và hậu xử lý file đã ghi."""
    pages: dict[str, tuple[int, str]] = {}
    ad_edge_1 = "Support the author by reading on Royal Road"
    nav_edge = "Previous Chapter | Next Chapter"
    ad_edge_2 = "Read the original on Royal Road"
    suspect_ad = "Join our community group for early access chapters today"
    safe_dialogue = "Hàn Tuyệt trầm giọng nói:"

    for i in range(1, 5):
        u = f"https://www.royalroad.com/fiction/500/chapter/{i}"
        nxt = f"https://www.royalroad.com/fiction/500/chapter/{i + 1}" if i < 4 else None
        nxt_link = f'<a class="btn-next" rel="next" href="{nxt}">Next</a>' if nxt else ""
        pages[u] = (
            200,
            f"""<!DOCTYPE html>
            <html>
            <head><title>Chapter {i} | Immortal Path | Royal Road</title></head>
            <body>
                <h1 class="chap-title">Chapter {i}: Trial {i}</h1>
                <div class="chapter-content">
                    <p>{ad_edge_1}</p>
                    <p>{nav_edge}</p>
                    <p>{ad_edge_2}</p>
                    <p>{safe_dialogue}</p>
                    <p>Unique narrative prose for chapter {i} describing the cultivation journey in detail.</p>
                    <p>Another long paragraph of authentic story content for chapter {i} to pass validation.</p>
                    <p>Third paragraph of deep worldbuilding and character progression in chapter {i}.</p>
                    <p>Fourth paragraph concluding the dramatic scene of chapter {i} with suspense.</p>
                    <p>{suspect_ad}</p>
                    <p>{nav_edge}</p>
                </div>
                {nxt_link}
            </body>
            </html>
            """,
        )

    ads_db_path = tmp_path / "ads_keywords.json"
    ads_filter = AdsFilter.load("www.royalroad.com", ads_db_file=ads_db_path)

    fake_ai = FakeProvider()
    fake_ai.set_response(
        VerifyAdsOutput,
        VerifyAdsOutput(
            ad_lines=[suspect_ad],
            safe_lines=[safe_dialogue],
            reasoning="Confirmed community promo line as ad; kept character dialogue safe.",
        ),
    )

    profile = _default_profile("www.royalroad.com")
    profile_store = ProfileStore(tmp_path / "site_profiles.json")
    progress_store = ProgressStore(base_dir=tmp_path / "progress")
    out_root = tmp_path / "output"
    run_cfg = RunConfig.create_for_mode("raw", str(out_root))

    session = ScrapeSession(
        start_url="https://www.royalroad.com/fiction/500/chapter/1",
        profile=profile,
        pool=FakePool(pages),
        progress_store=progress_store,
        profile_store=profile_store,
        ai_provider=fake_ai,
        ads_filter=ads_filter,
        run_config=run_cfg,
        sleep_fn=_noop_sleep,
    )

    state = await session.run()
    assert state.chapter_count == 4
    assert state.completed is True

    # Kiểm tra các file chương đã ghi trên đĩa:
    # 1. Cả ad_edge_1, nav_edge (nhờ 2-pass!), và ad_edge_2 đều đã bị xóa ngay lúc cào
    # 2. Dòng suspect_ad (xuất hiện 4 lần -> nhóm 3-9) đã được AI xác nhận và hậu xử lý xóa khỏi cả 4 file!
    # 3. Câu thoại safe_dialogue ("Hàn Tuyệt trầm giọng nói:") vẫn còn nguyên vẹn!
    txt_files = sorted(session.output_dir.glob("*.txt"))
    assert len(txt_files) == 4
    for tf in txt_files:
        text = tf.read_text(encoding="utf-8")
        assert ad_edge_1.lower() not in text.lower()
        assert nav_edge.lower() not in text.lower()
        assert ad_edge_2.lower() not in text.lower()
        assert suspect_ad.lower() not in text.lower()
        assert safe_dialogue in text

    # Kiểm tra từ khóa mới đã được lưu vào ProfileStore và ads_keywords.json
    saved_prof = await profile_store.get("www.royalroad.com")
    assert saved_prof is not None
    assert suspect_ad.lower() in saved_prof.ads_keywords_learned
    assert ads_db_path.exists()


