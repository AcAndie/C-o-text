"""tests/test_learn_learner.py — Kiểm tra luồng học cấu trúc site (learn_site) với FakeProvider.

Kiểm tra:
1. Luồng chuẩn 1 AI call: AI phân tích chính xác, kiểm chứng V1–V6 pass ngay, ai_calls=1.
2. Luồng sửa lỗi (Repair Flow): Call #1 đưa selector lỗi, V2 đánh fail, Call #2 sửa thành công, ai_calls=2.
3. Luồng fallback: Sau tối đa 2 vòng sửa lỗi mà vẫn thất bại, fallback về ứng viên bước 2, confidence <= 0.3, ghi issues.md.
4. Xử lý thiếu mẫu (<3 chương): raise RuntimeError rõ ràng.
5. Tự động lưu profile v3 vào ProfileStore.
6. Mô phỏng dữ liệu thật Webnovel (sửa lỗi div.cha-page sang div.cha-words) và RoyalRoad.
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from cao_text.ai.fake import FakeProvider
from cao_text.ai.schemas import SiteAnalysisOutput, SiteRepairOutput
from cao_text.learn.learner import learn_site
from cao_text.log import IssueReporter
from cao_text.storage import ProfileStore

PROJECT_ROOT = Path(__file__).resolve().parent.parent
FIXTURES_LOCAL = PROJECT_ROOT / "tests" / "fixtures_local" / "web"


# ── Synthetic Helpers ─────────────────────────────────────────────────────────

def _make_sample(ch_num: int, next_url: str | None = None) -> tuple[str, str]:
    curr_url = f"https://example.com/novel/ch{ch_num}"
    next_html = f'<a class="next-btn" rel="next" href="{next_url}">Next</a>' if next_url else ""
    html = f"""<!DOCTYPE html>
<html>
<head><title>Chapter {ch_num} - Novel Story</title></head>
<body>
    <header class="site-header"><span class="logo">NovelSite</span></header>
    <div class="page-container">
        <h1 class="chapter-title">Chapter {ch_num}: The Beginning</h1>
        <div class="story-content">
            <p>Paragraph 1 for chapter {ch_num} containing narrative storytelling text to introduce the scene.</p>
            <p>The brave adventurers ventured deep into the dark caves seeking the lost artifact of ancient power.</p>
            <p>Every shadow held potential danger, but their courage never wavered for even a single fleeting moment.</p>
            <p>They discovered a hidden door carved directly into the bedrock with shimmering golden runes.</p>
            <p>Conclusion of chapter {ch_num} with substantial descriptive prose for rigorous automated testing.</p>
        </div>
        <div class="nav-bar">{next_html}</div>
    </div>
</body>
</html>
"""
    return curr_url, html


def _make_samples(n: int = 4) -> list[tuple[str, str]]:
    samples = []
    for i in range(1, n + 1):
        nxt = f"https://example.com/novel/ch{i + 1}" if i < n else None
        samples.append(_make_sample(i, nxt))
    return samples


# ── Tests ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_learn_site_happy_path_single_call() -> None:
    """Luồng chuẩn: AI call #1 thành công và qua kiểm chứng ngay (ai_calls = 1)."""
    samples = _make_samples(4)

    fake_ai = FakeProvider()
    fake_ai.set_response(
        SiteAnalysisOutput,
        SiteAnalysisOutput(
            content_selector="div.story-content",
            title_selector="h1.chapter-title",
            next_selector="a.next-btn",
            nav_type="selector",
            story_name_clean="Novel Story",
            chapter_keyword="Chapter",
            has_chapter_subtitle=True,
            story_prefix_strip="Novel Story - ",
        ),
    )

    result = await learn_site(
        start_url="https://example.com/novel/ch1",
        ai_provider=fake_ai,
        prefetched_samples=samples,
        auto_save=False,
    )

    # 1. Chỉ gọi đúng 1 AI call
    assert result.ai_calls_count == 1
    assert result.used_fallback is False

    # 2. Profile v3 được tạo đúng
    prof = result.profile
    assert prof.domain == "example.com"
    assert prof.content_selector == "div.story-content"
    assert prof.title_selector == "h1.chapter-title"
    assert prof.next_selector == "a.next-btn"
    assert prof.confidence == 1.0
    assert prof.profile_version == 3

    # 3. Đặt tên (naming) đầy đủ
    assert result.naming.story_name_clean == "Novel Story"
    assert result.naming.chapter_keyword == "Chapter"
    assert result.naming.has_chapter_subtitle is True

    # 4. Kiểm chứng pass
    assert result.verification.passed is True


@pytest.mark.asyncio
async def test_learn_site_repair_flow_success() -> None:
    """Luồng sửa lỗi: Call #1 đưa selector bọc UI, Call #2 sửa đúng -> pass ở vòng 2."""
    # Tạo mẫu có outer wrapper bọc noise
    samples = []
    for i in range(1, 5):
        nxt = f"https://site.com/ch{i + 1}" if i < 4 else ""
        html = f"""
        <div class="outer-wrap">
            <div class="cha-header"><h1>Chapter {i}</h1></div>
            <div class="inner-prose">
                <p>Paragraph 1 of good prose lorem ipsum dolor sit amet describing exciting and dangerous action.</p>
                <p>Paragraph 2 continues the storyline with extensive details, atmosphere, and meaningful character dialogue.</p>
                <p>Paragraph 3 reveals a ancient mystery hidden deep inside the long-forgotten subterranean chamber.</p>
                <p>Paragraph 4 concludes the chapter text nicely with descriptive prose for robust automated testing.</p>
            </div>
            <div class="j_bottom_comments"><p>Comments area</p></div>
            <div class="nav"><a class="btn-nxt" rel="next" href="{nxt}">Next</a></div>
        </div>
        """
        samples.append((f"https://site.com/ch{i}", html))

    fake_ai = FakeProvider()
    # Call 1: AI đề xuất outer wrapper (sẽ bị V2 đánh fail vì chứa .cha-header và .j_bottom_comments)
    # Call 2: AI sửa thành inner-prose
    fake_ai.enqueue_responses([
        SiteAnalysisOutput(
            content_selector="div.outer-wrap",
            title_selector="h1",
            next_selector="a.btn-nxt",
            nav_type="selector",
        ),
        SiteRepairOutput(
            content_selector="div.inner-prose",
            title_selector="h1",
            next_selector="a.btn-nxt",
            nav_type="selector",
            reasoning="Outer container contained UI noise, switching to inner-prose",
        ),
    ])

    result = await learn_site(
        start_url="https://site.com/ch1",
        ai_provider=fake_ai,
        prefetched_samples=samples,
        auto_save=False,
    )

    # Đã gọi 2 lần (1 analyze + 1 repair)
    assert result.ai_calls_count == 2
    assert result.used_fallback is False
    assert result.profile.content_selector == "div.inner-prose"
    assert result.profile.confidence == 1.0
    assert result.verification.passed is True


@pytest.mark.asyncio
async def test_learn_site_fallback_when_repairs_exhausted() -> None:
    """Hết số vòng sửa lỗi (max 2 vòng) mà vẫn sai -> fallback về ứng viên bước 2."""
    samples = _make_samples(4)

    fake_ai = FakeProvider()
    # Cả 3 lần AI đều trả về selector không tồn tại
    fake_ai.enqueue_responses([
        SiteAnalysisOutput(content_selector="div.hallucinated-1"),
        SiteRepairOutput(content_selector="div.hallucinated-2", reasoning="try 2"),
        SiteRepairOutput(content_selector="div.hallucinated-3", reasoning="try 3"),
    ])

    with tempfile.TemporaryDirectory() as td:
        issues_path = Path(td) / "issues.md"
        reporter = IssueReporter(domain="example.com", story_label="Test Story", issues_file=issues_path)

        result = await learn_site(
            start_url="https://example.com/novel/ch1",
            ai_provider=fake_ai,
            prefetched_samples=samples,
            issue_reporter=reporter,
            max_repair_rounds=2,
            auto_save=False,
        )

        # 1 analyze + 2 repair = 3 calls
        assert result.ai_calls_count == 3
        assert result.used_fallback is True
        assert result.profile.confidence <= 0.3
        # Fallback về ứng viên bước 2 tìm được (div.story-content)
        assert result.profile.content_selector == "div.story-content"

        # Đã ghi nhận issue
        assert any(i.issue_type == "LEARNING_FAILED" for i in reporter.issues)
        issues_text = issues_path.read_text(encoding="utf-8")
        assert "Học cấu trúc site" in issues_text
        assert "Fallback confidence=0.3" in issues_text


@pytest.mark.asyncio
async def test_learn_site_not_enough_samples_raises() -> None:
    """Ít hơn 3 chương mẫu phải raise RuntimeError."""
    samples = _make_samples(2)
    fake_ai = FakeProvider()

    with pytest.raises(RuntimeError, match="Không đủ mẫu chương"):
        await learn_site(
            start_url="https://example.com/ch1",
            ai_provider=fake_ai,
            prefetched_samples=samples,
            auto_save=False,
        )


@pytest.mark.asyncio
async def test_learn_site_auto_save_profile_store() -> None:
    """Tự động lưu SiteProfile vào ProfileStore."""
    samples = _make_samples(4)
    fake_ai = FakeProvider()
    fake_ai.set_response(
        SiteAnalysisOutput,
        SiteAnalysisOutput(
            content_selector="div.story-content",
            title_selector="h1.chapter-title",
            next_selector="a.next-btn",
            nav_type="selector",
        ),
    )

    with tempfile.TemporaryDirectory() as td:
        store = ProfileStore(Path(td) / "site_profiles.json")

        result = await learn_site(
            start_url="https://example.com/novel/ch1",
            ai_provider=fake_ai,
            prefetched_samples=samples,
            profile_store=store,
            auto_save=True,
        )
        assert result.profile.domain == "example.com"

        loaded = await store.get("example.com")
        assert loaded is not None
        assert loaded.content_selector == "div.story-content"
        assert loaded.profile_version == 3


# ── Integration with Real Web Fixtures ────────────────────────────────────────


@pytest.mark.skipif(
    not (FIXTURES_LOCAL / "www.webnovel.com" / "zero_fate_against_the_world" / "meta.json").exists(),
    reason="Thiếu fixtures_local Webnovel",
)
@pytest.mark.asyncio
async def test_learn_site_webnovel_repair_simulation() -> None:
    """Mô phỏng Webnovel: AI đề xuất div.cha-page (bị V2 đánh fail), AI sửa sang div.cha-words -> PASS."""
    meta_path = FIXTURES_LOCAL / "www.webnovel.com" / "zero_fate_against_the_world" / "meta.json"
    with open(meta_path, encoding="utf-8") as f:
        meta = json.load(f)

    story_dir = meta_path.parent
    samples = [
        (ch["url"], (story_dir / ch["file"]).read_text(encoding="utf-8"))
        for ch in meta["chapters"][:5]
    ]

    fake_ai = FakeProvider()
    fake_ai.enqueue_responses([
        # Call 1: Đưa profile cũ bị lỗi
        SiteAnalysisOutput(
            content_selector="div.cha-page",
            title_selector="h1",
            next_selector="link[rel~='next']",
            nav_type="rel_next",
        ),
        # Call 2: Sửa thành div.cha-words
        SiteRepairOutput(
            content_selector="div.cha-words",
            title_selector="h1",
            next_selector="link[rel~='next']",
            nav_type="rel_next",
            reasoning="Fixed outer wrapper div.cha-page to inner prose div.cha-words",
        ),
    ])

    result = await learn_site(
        start_url=meta["start_url"],
        ai_provider=fake_ai,
        prefetched_samples=samples,
        auto_save=False,
    )

    assert result.ai_calls_count == 2
    assert result.used_fallback is False
    assert result.profile.content_selector == "div.cha-words"
    assert result.profile.confidence == 1.0
    assert result.verification.passed is True


@pytest.mark.skipif(
    not (FIXTURES_LOCAL / "www.royalroad.com" / "rock_falls_everyone_dies" / "meta.json").exists(),
    reason="Thiếu fixtures_local RoyalRoad",
)
@pytest.mark.asyncio
async def test_learn_site_royalroad_simulation() -> None:
    """Mô phỏng RoyalRoad: AI phân tích chuẩn xác ngay ở Call #1 -> PASS."""
    meta_path = FIXTURES_LOCAL / "www.royalroad.com" / "rock_falls_everyone_dies" / "meta.json"
    with open(meta_path, encoding="utf-8") as f:
        meta = json.load(f)

    story_dir = meta_path.parent
    samples = [
        (ch["url"], (story_dir / ch["file"]).read_text(encoding="utf-8"))
        for ch in meta["chapters"][:5]
    ]

    fake_ai = FakeProvider()
    fake_ai.set_response(
        SiteAnalysisOutput,
        SiteAnalysisOutput(
            content_selector="div.chapter-content",
            title_selector="h1",
            next_selector="link[rel~='next']",
            nav_type="rel_next",
            story_name_clean="Rock falls, everyone dies",
            chapter_keyword="Chapter",
        ),
    )

    result = await learn_site(
        start_url=meta["start_url"],
        ai_provider=fake_ai,
        prefetched_samples=samples,
        auto_save=False,
    )

    assert result.ai_calls_count == 1
    assert result.used_fallback is False
    assert result.profile.content_selector == "div.chapter-content"
    assert result.profile.confidence == 1.0
    assert result.verification.passed is True
