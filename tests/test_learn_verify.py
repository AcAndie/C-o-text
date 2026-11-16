"""tests/test_learn_verify.py — Kiểm tra bộ kiểm chứng SiteProfile V1–V6.

Yêu cầu theo AGENTS.md Task 4.2:
- V1: content_selector khớp trong mọi mẫu.
- V2: Độ dài ≥300 ký tự và ≥60% khối text dày nhất (không quá hẹp);
      Link density ≤30% và không chứa thành phần UI/bình luận/quảng cáo.
      ĐẶC BIỆT: profile cũ của Webnovel (`div.cha-page`) phải bị V2 đánh fail!
- V3: title_selector tìm thấy ở ≥80% mẫu và khác nhau giữa các chương (loại bỏ logo/tên site).
- V4: next dẫn đúng URL chương mẫu kế tiếp.
- V5: remove_selectors không làm mất >20% nội dung.
- V6: Mỗi dòng ads_keywords xuất hiện nguyên văn ở ≥2 mẫu.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from cao_text.learn.verify import (
    verify_site_profile,
    verify_v1,
    verify_v2,
    verify_v3,
    verify_v4,
    verify_v5,
    verify_v6,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
FIXTURES_LOCAL = PROJECT_ROOT / "tests" / "fixtures_local" / "web"


# ── Synthetic Helpers ─────────────────────────────────────────────────────────

def _make_sample(ch_num: int, next_url: str | None = None) -> tuple[str, str]:
    curr_url = f"https://example.com/ch{ch_num}"
    next_html = f'<a class="next-btn" rel="next" href="{next_url}">Next</a>' if next_url else ""
    html = f"""<!DOCTYPE html>
<html>
<head><title>Chapter {ch_num} - Site</title></head>
<body>
    <header class="site-header"><span class="logo">Site Logo</span></header>
    <div class="content-wrapper">
        <h1 class="entry-title">Chapter {ch_num}: Title of Chapter</h1>
        <div class="chapter-body">
            <p>This is paragraph one for chapter {ch_num} containing narrative prose with descriptions.</p>
            <p>The journey continues into deeper territories full of unexpected surprises and adventures.</p>
            <p>Every hero must face trials and overcome obstacles to reach their true potential.</p>
            <p>Concluding paragraph for the story chapter to ensure text length is substantial enough.</p>
        </div>
        <div class="nav-links">{next_html}</div>
    </div>
    <footer class="site-footer"><p>Copyright 2026</p></footer>
</body>
</html>
"""
    return curr_url, html


def _make_chain(n: int = 4) -> list[tuple[str, str]]:
    chain = []
    for i in range(1, n + 1):
        nxt = f"https://example.com/ch{i + 1}" if i < n else None
        chain.append(_make_sample(i, nxt))
    return chain


# ── V1 Tests ──────────────────────────────────────────────────────────────────


def test_verify_v1_success_and_failure() -> None:
    samples = _make_chain(3)
    soups = [BeautifulSoup(h, "lxml") for _, h in samples]

    # Khớp toàn bộ mẫu -> PASS
    res_ok = verify_v1("div.chapter-body", samples, soups)
    assert res_ok.passed is True
    assert "3/3" in res_ok.message

    # Thiếu ở mẫu khác -> FAIL
    res_fail = verify_v1("div.non-existent-class", samples, soups)
    assert res_fail.passed is False
    assert "không tìm thấy" in res_fail.message

    # Rỗng -> FAIL
    res_empty = verify_v1("", samples, soups)
    assert res_empty.passed is False
    assert "rỗng" in res_empty.message


# ── V2 Tests ──────────────────────────────────────────────────────────────────


def test_verify_v2_success_synthetic() -> None:
    samples = _make_chain(3)
    soups = [BeautifulSoup(h, "lxml") for _, h in samples]

    res = verify_v2("div.chapter-body", samples, soups)
    assert res.passed is True


def test_verify_v2_too_short_fails() -> None:
    samples = [
        ("https://site.com/1", "<div><p>Short</p></div>"),
        ("https://site.com/2", "<div><p>Tiny</p></div>"),
    ]
    soups = [BeautifulSoup(h, "lxml") for _, h in samples]

    res = verify_v2("div", samples, soups)
    assert res.passed is False
    assert "quá ngắn" in res.message


def test_verify_v2_too_narrow_fails() -> None:
    # Đoạn text được chọn chỉ là 1 câu nhỏ (<60% tổng văn bản)
    samples = [
        (
            f"https://site.com/{i}",
            """
            <body>
                <div class="note"><p>Tiny author note here with 320 chars of text: """
            + "A" * 320
            + """</p></div>
                <div class="main-novel"><p>Huge novel prose: """
            + "B" * 3000
            + """</p></div>
            </body>
            """,
        )
        for i in range(1, 4)
    ]
    soups = [BeautifulSoup(h, "lxml") for _, h in samples]

    res = verify_v2("div.note", samples, soups)
    assert res.passed is False
    assert "quá hẹp" in res.message


def test_verify_v2_high_link_density_fails() -> None:
    samples = [
        (
            f"https://site.com/{i}",
            """
            <div class="toc">
                <a href="/1">Chapter 1 Title Long Text Entry For Navigation</a>
                <a href="/2">Chapter 2 Title Long Text Entry For Navigation</a>
                <a href="/3">Chapter 3 Title Long Text Entry For Navigation</a>
                <a href="/4">Chapter 4 Title Long Text Entry For Navigation</a>
                <a href="/5">Chapter 5 Title Long Text Entry For Navigation</a>
                <a href="/6">Chapter 6 Title Long Text Entry For Navigation</a>
                <a href="/7">Chapter 7 Title Long Text Entry For Navigation</a>
                <p>Some minor prose text lorem ipsum dolor sit amet describing novel events.</p>
            </div>
            """,
        )
        for i in range(1, 4)
    ]
    soups = [BeautifulSoup(h, "lxml") for _, h in samples]

    res = verify_v2("div.toc", samples, soups)
    assert res.passed is False
    assert "Mật độ liên kết quá cao" in res.message


def test_verify_v2_outer_wrapper_with_ui_fails() -> None:
    """Outer container bọc UI như comment/header phải bị V2 đánh fail."""
    samples = [
        (
            f"https://site.com/{i}",
            """
            <div class="page-container">
                <div class="cha-header"><h1>Header</h1></div>
                <div class="prose-content"><p>"""
            + "Substantial novel prose " * 30
            + """</p></div>
                <div class="j_bottom_comments"><p>Comments area</p></div>
            </div>
            """,
        )
        for i in range(1, 4)
    ]
    soups = [BeautifulSoup(h, "lxml") for _, h in samples]

    # Outer bọc noise -> FAIL
    res_outer = verify_v2("div.page-container", samples, soups)
    assert res_outer.passed is False
    assert "quá rộng" in res_outer.message

    # Inner sạch -> PASS
    res_inner = verify_v2("div.prose-content", samples, soups)
    assert res_inner.passed is True


# ── Webnovel Requirement (Task 4.2 Core Requirement) ─────────────────────────


@pytest.mark.skipif(
    not (FIXTURES_LOCAL / "www.webnovel.com" / "zero_fate_against_the_world" / "meta.json").exists(),
    reason="Thiếu fixtures_local Webnovel",
)
def test_verify_v2_webnovel_old_profile_fails() -> None:
    """Task 4.2: Profile cũ của Webnovel dùng div.cha-page PHẢI bị V2 đánh fail.

    Và profile mới dùng div.cha-words phải đạt chuẩn (PASS).
    """
    meta_path = FIXTURES_LOCAL / "www.webnovel.com" / "zero_fate_against_the_world" / "meta.json"
    with open(meta_path, encoding="utf-8") as f:
        meta = json.load(f)

    story_dir = meta_path.parent
    samples = [
        (ch["url"], (story_dir / ch["file"]).read_text(encoding="utf-8"))
        for ch in meta["chapters"][:5]
    ]
    soups = [BeautifulSoup(h, "lxml") for _, h in samples]

    # 1. Profile cũ (div.cha-page) -> PHẢI BỊ V2 ĐÁNH FAIL
    res_old = verify_v2("div.cha-page", samples, soups)
    assert res_old.passed is False
    assert "quá rộng" in res_old.message
    assert any(ns in str(res_old.details) for ns in (".cha-page-ft", ".j_bottom_comments", ".j_bottom"))

    # 2. Profile mới (div.cha-words) -> PHẢI ĐƯỢC V2 THÔNG QUA
    res_new = verify_v2("div.cha-words", samples, soups)
    assert res_new.passed is True


# ── V3 Tests ──────────────────────────────────────────────────────────────────


def test_verify_v3_distinct_titles_success() -> None:
    samples = _make_chain(3)
    soups = [BeautifulSoup(h, "lxml") for _, h in samples]

    res = verify_v3("h1.entry-title", samples, soups)
    assert res.passed is True
    assert "hợp lệ" in res.message


def test_verify_v3_static_logo_title_fails() -> None:
    """Nếu selector trỏ vào logo hoặc tên site không đổi giữa các chương -> FAIL."""
    samples = _make_chain(3)
    soups = [BeautifulSoup(h, "lxml") for _, h in samples]

    res = verify_v3("header.site-header span.logo", samples, soups)
    assert res.passed is False
    assert "không thay đổi" in res.message


def test_verify_v3_fallback_chain_success() -> None:
    """Khi title_selector rỗng, kiểm tra chuỗi fallback (h1/og:title/slug)."""
    samples = _make_chain(3)
    soups = [BeautifulSoup(h, "lxml") for _, h in samples]

    res = verify_v3(None, samples, soups)
    assert res.passed is True


# ── V4 Tests ──────────────────────────────────────────────────────────────────


def test_verify_v4_next_navigation_success() -> None:
    samples = _make_chain(4)
    soups = [BeautifulSoup(h, "lxml") for _, h in samples]

    profile = {"next_selector": "a.next-btn", "nav_type": "selector"}
    res = verify_v4(profile, samples, soups)
    assert res.passed is True
    assert "3/3" in res.message


def test_verify_v4_wrong_next_fails() -> None:
    # Mẫu HTML có nút next nhưng trỏ sai URL (trỏ về trang chủ thay vì chương kế)
    samples = [
        (
            f"https://example.com/ch{i}",
            f'<div><p>Prose line {i}...</p><a href="https://example.com/home">Next</a></div>',
        )
        for i in range(1, 5)
    ]
    soups = [BeautifulSoup(h, "lxml") for _, h in samples]

    # Selector trỏ tới link không tồn tại hoặc sai URL
    profile = {"next_selector": "a.wrong-btn", "nav_type": "selector"}
    res = verify_v4(profile, samples, soups)
    assert res.passed is False
    assert "chỉ dẫn đúng 0/3" in res.message


# ── V5 Tests ──────────────────────────────────────────────────────────────────


def test_verify_v5_safe_removals_pass() -> None:
    samples = [
        (
            f"https://site.com/{i}",
            """
            <div class="content">
                <p class="ad">Buy our merch</p>
                <p>"""
            + "Real chapter narrative text " * 50
            + """</p>
            </div>
            """,
        )
        for i in range(1, 4)
    ]
    soups = [BeautifulSoup(h, "lxml") for _, h in samples]

    res = verify_v5("div.content", ["p.ad"], samples, soups)
    assert res.passed is True


def test_verify_v5_over_aggressive_removals_fail() -> None:
    """remove_selectors làm mất > 20% nội dung phải bị chặn lại."""
    samples = [
        (
            f"https://site.com/{i}",
            """
            <div class="content">
                <p>Paragraph 1 of narrative</p>
                <p>Paragraph 2 of narrative</p>
                <p>Paragraph 3 of narrative</p>
            </div>
            """,
        )
        for i in range(1, 4)
    ]
    soups = [BeautifulSoup(h, "lxml") for _, h in samples]

    # Xóa toàn bộ thẻ <p> làm mất 100% nội dung
    res = verify_v5("div.content", ["p"], samples, soups)
    assert res.passed is False
    assert "làm mất" in res.message


# ── V6 Tests ──────────────────────────────────────────────────────────────────


def test_verify_v6_repeated_keywords_pass() -> None:
    samples = [
        (f"https://site.com/{i}", "<div><p>Watermark phrase for novel site</p><p>Prose</p></div>")
        for i in range(1, 4)
    ]
    soups = [BeautifulSoup(h, "lxml") for _, h in samples]

    res = verify_v6(["Watermark phrase for novel site"], samples, soups)
    assert res.passed is True


def test_verify_v6_hallucinated_keyword_fails() -> None:
    samples = [
        ("https://site.com/1", "<div><p>Appears once here only</p></div>"),
        ("https://site.com/2", "<div><p>Different text</p></div>"),
        ("https://site.com/3", "<div><p>Another text</p></div>"),
    ]
    soups = [BeautifulSoup(h, "lxml") for _, h in samples]

    res = verify_v6(["Appears once here only"], samples, soups)
    assert res.passed is False
    assert "không xuất hiện ở ≥2 mẫu" in res.message


# ── Full verify_site_profile Tests ───────────────────────────────────────────


def test_verify_site_profile_full_success_synthetic() -> None:
    samples = _make_chain(4)
    profile = {
        "content_selector": "div.chapter-body",
        "title_selector": "h1.entry-title",
        "next_selector": "a.next-btn",
        "nav_type": "selector",
        "remove_selectors": [],
        "ads_keywords": [],
    }

    res = verify_site_profile(profile, samples)
    assert res.passed is True
    assert len(res.errors) == 0
    assert res.v1.passed is True
    assert res.v2.passed is True
    assert res.v3.passed is True
    assert res.v4.passed is True
    assert res.v5.passed is True
    assert res.v6.passed is True


@pytest.mark.skipif(
    not (FIXTURES_LOCAL / "www.royalroad.com" / "rock_falls_everyone_dies" / "meta.json").exists(),
    reason="Thiếu fixtures_local RoyalRoad",
)
def test_verify_site_profile_royalroad_fixture_passes() -> None:
    meta_path = FIXTURES_LOCAL / "www.royalroad.com" / "rock_falls_everyone_dies" / "meta.json"
    with open(meta_path, encoding="utf-8") as f:
        meta = json.load(f)

    story_dir = meta_path.parent
    samples = [
        (ch["url"], (story_dir / ch["file"]).read_text(encoding="utf-8"))
        for ch in meta["chapters"][:5]
    ]

    res = verify_site_profile(meta["profile"], samples)
    assert res.passed is True
    assert res.v1.passed is True
    assert res.v2.passed is True
    assert res.v3.passed is True
    assert res.v4.passed is True
