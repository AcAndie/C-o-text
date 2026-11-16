"""tests/test_learn_candidates.py — Kiểm tra bộ tìm ứng viên content/title/next bằng code thuần.

Kiểm tra:
1. Ứng viên vùng chứa nội dung (mật độ text, thẻ p, link density, phân biệt outer vs inner wrapper).
2. Ứng viên tiêu đề chương (h1/h2, loại bỏ tên site cố định không đổi, từ khóa chương).
3. Ứng viên nút next (khớp URL chuyển tiếp thật, rel=next, anchor text, slug increment).
4. Phát hiện các dòng lặp lại nghi ngờ là rác/watermark giữa các chương.
5. Định dạng đầu ra to_prompt_dict tương thích với prompt_analyze_site.
6. Xử lý an toàn với input rỗng, HTML lỗi, trang không có nội dung văn xuôi.
7. Kiểm thử với fixtures thật RoyalRoad và Webnovel nếu có trong fixtures_local.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from cao_text.learn.candidates import (
    find_content_candidates,
    find_next_candidates,
    find_raw_titles,
    find_repeated_lines,
    find_site_candidates,
    find_title_candidates,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
FIXTURES_LOCAL = PROJECT_ROOT / "tests" / "fixtures_local" / "web"


# ── Synthetic HTML Samples ───────────────────────────────────────────────────

def _make_synthetic_sample(ch_num: int, next_url: str | None = None) -> tuple[str, str]:
    """Tạo mẫu HTML giả lập cấu trúc web novel chuẩn."""
    curr_url = f"https://example.com/novel/chapter-{ch_num}"
    next_html = f'<a class="btn-next" rel="next" href="{next_url}">Next Chapter</a>' if next_url else ""

    html = f"""<!DOCTYPE html>
<html>
<head>
    <title>Chapter {ch_num}: The Journey Begins - NovelSite</title>
    <meta property="og:title" content="Chapter {ch_num}: The Journey Begins" />
</head>
<body>
    <header class="site-header">
        <div class="logo">NovelSite</div>
        <nav><a href="/">Home</a> | <a href="/novels">Novels</a></nav>
    </header>

    <div class="page-container has-sidebar">
        <div class="cha-header">
            <h1 class="chapter-title">Chapter {ch_num}: The Journey Begins</h1>
            <span class="site-branding">NovelSite Official</span>
        </div>

        <div class="content-box">
            <div class="prose-body">
                <p>This is paragraph one of chapter {ch_num}. It contains plenty of narrative prose describing the scene.</p>
                <p>The wind was howling through the ancient forest, whispering secrets of forgotten lore and untold mysteries.</p>
                <p>Hero stepped forward with courage, gripping his weapon tightly while gazing into the horizon.</p>
                <p>Every step brought new challenges and unexpected discoveries that would test their resolve to the limit.</p>
                <p>This novel is exclusively published on NovelSite. Please support the original author!</p>
            </div>
        </div>

        <div class="chapter-nav">
            <a class="btn-prev" href="/novel/chapter-{ch_num - 1}">Previous</a>
            {next_html}
        </div>

        <footer class="comments-section">
            <div class="comment">Great chapter {ch_num}!</div>
        </footer>
    </div>
</body>
</html>
"""
    return curr_url, html


def _make_samples_chain(n: int = 4) -> list[tuple[str, str]]:
    samples = []
    for i in range(1, n + 1):
        next_u = f"https://example.com/novel/chapter-{i + 1}" if i < n else None
        samples.append(_make_synthetic_sample(i, next_u))
    return samples


# ── Tests for Content Candidates ──────────────────────────────────────────────


def test_find_content_candidates_synthetic() -> None:
    samples = _make_samples_chain(3)
    candidates = find_content_candidates(samples, min_chars=100)

    assert len(candidates) > 0
    selectors = [c.selector for c in candidates]
    # Phải tìm thấy container văn xuôi
    assert any("prose-body" in s or "content-box" in s for s in selectors)

    top = candidates[0]
    assert top.hit_count == 3
    assert top.total_samples == 3
    assert top.has_p_tags is True
    assert top.link_density < 0.1
    assert top.is_tight_wrapper is True


def test_content_wrapper_tightness_penalty() -> None:
    """Outer container bọc cả comments/header phải bị đánh dấu tight=False và điểm thấp hơn inner."""
    samples = []
    for i in range(1, 4):
        html = f"""
        <div class="outer-page">
            <div class="cha-hd"><h1>Chapter {i}</h1></div>
            <div class="reading-content">
                <p>Paragraph 1 of novel content lorem ipsum dolor sit amet with substantial text.</p>
                <p>Paragraph 2 of novel content continues with more prose and storytelling details.</p>
                <p>Paragraph 3 concludes the core chapter prose for testing tightness scoring.</p>
            </div>
            <div class="j_bottom_comments">
                <p>Comment 1: Nice story!</p>
            </div>
        </div>
        """
        samples.append((f"https://site.com/ch{i}", html))

    candidates = find_content_candidates(samples, min_chars=100)
    assert len(candidates) >= 2

    tight_map = {c.selector: c.is_tight_wrapper for c in candidates}
    score_map = {c.selector: c.score for c in candidates}

    # Inner container sạch phải là tight=True
    assert tight_map.get("div.reading-content") is True
    # Outer container bọc noise selector (.cha-hd, .j_bottom_comments) phải bị tight=False
    assert tight_map.get("div.outer-page") is False
    # Điểm của inner phải cao hơn outer
    assert score_map["div.reading-content"] > score_map["div.outer-page"]


def test_content_link_density_filtering() -> None:
    """Thẻ chứa nhiều link như menu/mục lục phải bị loại bỏ do link_density cao."""
    samples = [
        (
            f"https://site.com/ch{i}",
            """
            <div class="nav-menu">
                <a href="/1">Chapter 1</a> <a href="/2">Chapter 2</a>
                <a href="/3">Chapter 3</a> <a href="/4">Chapter 4</a>
                <a href="/5">Chapter 5</a> <a href="/6">Chapter 6</a>
                <a href="/7">Chapter 7</a> <a href="/8">Chapter 8</a>
                <p><a href="/9">Chapter 9</a> <a href="/10">Chapter 10</a></p>
                <p><a href="/11">Chapter 11</a> <a href="/12">Chapter 12</a></p>
            </div>
            <div class="actual-prose">
                <p>Text line 1 without links describing events in great detail.</p>
                <p>Text line 2 continuing the journey into the unknown depths.</p>
            </div>
            """,
        )
        for i in range(1, 4)
    ]

    candidates = find_content_candidates(samples, min_chars=50)
    selectors = [c.selector for c in candidates]

    assert "div.actual-prose" in selectors
    assert "div.nav-menu" not in selectors


# ── Tests for Title Candidates ────────────────────────────────────────────────


def test_find_title_candidates_synthetic() -> None:
    samples = _make_samples_chain(3)
    candidates = find_title_candidates(samples)

    assert len(candidates) > 0
    top = candidates[0]
    assert "h1" in top.selector
    assert top.hit_count == 3
    assert top.distinct_titles_count == 3
    assert top.has_chapter_keyword is True


def test_title_rejects_static_site_name() -> None:
    """Class chứa text cố định không đổi (như 'NovelSite Official') không được chọn làm tiêu đề."""
    samples = _make_samples_chain(3)
    candidates = find_title_candidates(samples)

    branding_candidates = [c for c in candidates if "site-branding" in c.selector or "logo" in c.selector]
    assert len(branding_candidates) == 0


# ── Tests for Next Candidates ─────────────────────────────────────────────────


def test_find_next_candidates_transition_ground_truth() -> None:
    samples = _make_samples_chain(4)
    candidates = find_next_candidates(samples)

    assert len(candidates) > 0
    top = candidates[0]
    assert top.confidence == 1.0
    assert top.hit_count == 3  # 3 transitions giữa 4 samples
    # Khớp đúng URL mục tiêu
    assert top.resolved_urls == [
        "https://example.com/novel/chapter-2",
        "https://example.com/novel/chapter-3",
        "https://example.com/novel/chapter-4",
    ]


def test_find_next_candidates_slug_increment() -> None:
    """Khi không có thẻ link next, thuật toán nhận diện slug_increment từ URL."""
    samples = [
        (f"https://site.com/read/book/chapter-{i}", f"<div><p>Content {i} prose text...</p><p>Line 2</p></div>")
        for i in range(1, 4)
    ]
    candidates = find_next_candidates(samples)
    slug_cands = [c for c in candidates if c.nav_type == "slug_increment"]
    assert len(slug_cands) > 0
    assert slug_cands[0].confidence >= 0.70


def test_find_next_candidates_anchor_text() -> None:
    """Nhận diện thẻ <a> có text 'Next Chapter' / 'Chương sau'."""
    samples = [
        (
            f"https://site.com/ch{i}",
            f'<div><p>Content {i}...</p><p>Second line</p><a href="/ch{i + 1}">Next Chapter</a></div>',
        )
        for i in range(1, 4)
    ]
    candidates = find_next_candidates(samples)
    text_cands = [c for c in candidates if c.nav_type == "anchor_text"]
    assert len(text_cands) > 0
    assert text_cands[0].confidence >= 0.80


# ── Tests for Repeated Lines & Raw Titles ─────────────────────────────────────


def test_find_repeated_lines() -> None:
    samples = _make_samples_chain(3)
    repeated = find_repeated_lines(samples, content_selector="div.prose-body", min_appearances=2)

    assert len(repeated) > 0
    # Câu watermark lặp lại trong synthetic samples
    assert any("support the original author" in line for line in repeated)


def test_find_raw_titles() -> None:
    samples = _make_samples_chain(2)
    raw = find_raw_titles(samples)

    assert len(raw) > 0
    assert any("Chapter 1: The Journey Begins" in t for t in raw)
    assert any("Chapter 2: The Journey Begins" in t for t in raw)


# ── Tests for Full find_site_candidates & to_prompt_dict ─────────────────────


def test_find_site_candidates_full_flow() -> None:
    samples = _make_samples_chain(3)
    site_candidates = find_site_candidates(samples, min_chars=100)

    assert site_candidates.best_content_selector is not None
    assert site_candidates.best_title_selector is not None
    assert site_candidates.best_next_selector is not None or site_candidates.best_nav_type == "rel_next"
    assert len(site_candidates.repeated_lines) > 0
    assert len(site_candidates.raw_titles) > 0

    prompt_dict = site_candidates.to_prompt_dict()
    assert "content_candidates" in prompt_dict
    assert "title_candidates" in prompt_dict
    assert "next_candidates" in prompt_dict
    assert "best_guess" in prompt_dict
    assert prompt_dict["best_guess"]["content_selector"] == site_candidates.best_content_selector


def test_empty_and_degenerate_input_handling() -> None:
    """Input rỗng hoặc không có nội dung không gây crash."""
    empty_res = find_site_candidates([])
    assert empty_res.best_content_selector is None
    assert empty_res.best_title_selector is None
    assert empty_res.best_next_selector is None
    assert empty_res.content_candidates == []

    broken_samples = [("https://example.com/1", "<html><body>No prose here</body></html>")]
    broken_res = find_site_candidates(broken_samples)
    assert broken_res.content_candidates == []


# ── Tests with Local Fixtures (RoyalRoad & Webnovel) ──────────────────────────


@pytest.mark.skipif(
    not (FIXTURES_LOCAL / "www.royalroad.com" / "rock_falls_everyone_dies" / "meta.json").exists(),
    reason="Thiếu fixtures_local RoyalRoad",
)
def test_candidates_royalroad_fixture() -> None:
    meta_path = FIXTURES_LOCAL / "www.royalroad.com" / "rock_falls_everyone_dies" / "meta.json"
    with open(meta_path, encoding="utf-8") as f:
        meta = json.load(f)

    story_dir = meta_path.parent
    samples = [
        (ch["url"], (story_dir / ch["file"]).read_text(encoding="utf-8"))
        for ch in meta["chapters"][:5]
    ]

    res = find_site_candidates(samples)

    # 1. Content: phải tìm ra vùng chứa nội dung của RoyalRoad
    assert res.best_content_selector is not None
    assert any(tag in res.best_content_selector for tag in ("chapter-content", "chapter-inner"))
    assert res.content_candidates[0].is_tight_wrapper is True

    # 2. Title: tiêu đề h1
    assert res.best_title_selector == "h1"

    # 3. Next: tìm được rel_next hoặc link next với conf = 1.0
    assert res.best_nav_type in ("rel_next", "selector")
    assert res.next_candidates[0].confidence == 1.0

    # 4. Repeated lines: tìm được các dòng watermark/stats lặp lại
    assert len(res.repeated_lines) > 0


@pytest.mark.skipif(
    not (FIXTURES_LOCAL / "www.webnovel.com" / "zero_fate_against_the_world" / "meta.json").exists(),
    reason="Thiếu fixtures_local Webnovel",
)
def test_candidates_webnovel_fixture() -> None:
    meta_path = FIXTURES_LOCAL / "www.webnovel.com" / "zero_fate_against_the_world" / "meta.json"
    with open(meta_path, encoding="utf-8") as f:
        meta = json.load(f)

    story_dir = meta_path.parent
    samples = [
        (ch["url"], (story_dir / ch["file"]).read_text(encoding="utf-8"))
        for ch in meta["chapters"][:5]
    ]

    res = find_site_candidates(samples)

    # 1. Content: phải chọn `div.cha-words` hoặc `div.cha-content`, KHÔNG ĐƯỢC CHỌN `div.cha-page`
    assert res.best_content_selector in ("div.cha-words", "div.cha-content")
    # Kiểm tra `div.cha-page` bị đánh dấu tight=False
    cha_page_cand = next((c for c in res.content_candidates if c.selector == "div.cha-page"), None)
    assert cha_page_cand is not None
    assert cha_page_cand.is_tight_wrapper is False
    assert res.content_candidates[0].score > cha_page_cand.score

    # 2. Title: h1
    assert res.best_title_selector == "h1"

    # 3. Next: rel_next hoặc link[rel~='next'] với conf = 1.0
    assert res.next_candidates[0].confidence == 1.0
