"""tests/test_web_start.py — Kiểm tra phân loại URL và tìm chương 1 (Task 4.4).

Kiểm tra:
1. Metadata helpers: extract_story_title, build_story_id_regex, is_chapter_url, story_id_ok.
2. ClassificationStore: đọc/ghi cache json, kiểm tra ngưỡng confidence.
3. Fast-path Webnovel: sắp xếp số nguyên chapter ID, smallest = chương 1.
4. Code-first Heuristic: nhận diện chapter & index với nút "Start Reading".
5. AI Classification: tích hợp FakeProvider khi heuristic không chắc chắn.
6. resolve_start_url: điều hướng index -> chapter 1, giữ nguyên chapter.
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from cao_text.ai.fake import FakeProvider
from cao_text.ai.schemas import PageClassificationOutput
from cao_text.models import SiteProfile
from cao_text.web.start import (
    ClassificationStore,
    build_story_id_regex,
    classify_url,
    extract_story_title,
    is_chapter_url,
    resolve_start_url,
    story_id_ok,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
FIXTURES_LOCAL = PROJECT_ROOT / "tests" / "fixtures_local" / "web"


# ── Metadata Helpers ─────────────────────────────────────────────────────────

def test_extract_story_title() -> None:
    # 1. RoyalRoad format
    title_rr = "Chapter 5 – The Rise | Rock Falls | Royal Road"
    assert extract_story_title(title_rr) == "Rock Falls"

    # 2. Known site stripped
    title_wx = "Monster Cultivator Chapter 10 - WuxiaWorld"
    assert extract_story_title(title_wx) == "Monster Cultivator Chapter 10"

    # 3. Tiếng Việt format
    title_vn = "Chương 1: Khởi đầu | Đạo Quân | TruyenFull"
    assert extract_story_title(title_vn) == "Đạo Quân"

    # 4. Rỗng hoặc chỉ có tên site
    assert extract_story_title("") is None
    assert extract_story_title("Royal Road | Webnovel") is None


def test_build_story_id_regex() -> None:
    # 1. Fanfiction.net
    re_ff = build_story_id_regex("https://fanfiction.net/s/12345678/1/My-Story")
    assert re_ff is not None
    assert r"/s/12345678/" in re_ff

    # 2. RoyalRoad
    re_rr = build_story_id_regex("https://royalroad.com/fiction/55418/the-wandering-inn/chapter/123")
    assert re_rr is not None
    assert r"/fiction/55418/" in re_rr

    # 3. ScribbleHub (id-then-slug)
    re_sh = build_story_id_regex("https://scribblehub.com/read/1539267-the-quantum-wanderer/chapter/1539274/")
    assert re_sh is not None
    assert r"/read/1539267" in re_sh


def test_is_chapter_url_and_story_id_ok() -> None:
    # 1. is_chapter_url
    assert is_chapter_url("https://royalroad.com/fiction/123/chapter/456") is True
    assert is_chapter_url("https://example.com/novel/ch1") is True
    assert is_chapter_url("https://example.com/novel/about") is False

    # Với profile có pattern riêng
    prof = SiteProfile(
        domain="custom.com",
        confidence=1.0,
        chapter_url_pattern=r"/doc/\d+\.html",
    )
    assert is_chapter_url("https://custom.com/doc/42.html", prof) is True
    assert is_chapter_url("https://custom.com/index.html", prof) is False

    # 2. story_id_ok
    guard_re = r"/fiction/55418/"
    assert story_id_ok("https://royalroad.com/fiction/55418/chapter/1", guard_re) is True
    assert story_id_ok("https://royalroad.com/fiction/99999/chapter/1", guard_re) is False
    assert story_id_ok("https://example.com/other", None) is True


# ── ClassificationStore ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_classification_store_cache() -> None:
    with tempfile.TemporaryDirectory() as td:
        cache_file = Path(td) / "url_classifications.json"
        store = ClassificationStore(cache_file)

        # 1. Chưa có trong cache -> None
        assert await store.get("https://example.com/ch1") is None

        # 2. Lưu kết quả có confidence cao -> lấy lại được
        item_high = PageClassificationOutput(
            page_type="chapter",
            story_title="Sample Story",
            confidence=0.85,
        )
        await store.set("https://example.com/ch1", item_high)
        cached = await store.get("https://example.com/ch1")
        assert cached is not None
        assert cached.page_type == "chapter"
        assert cached.story_title == "Sample Story"

        # 3. Kết quả có confidence thấp (< 0.7) -> get() bỏ qua
        item_low = PageClassificationOutput(
            page_type="unknown",
            confidence=0.5,
        )
        await store.set("https://example.com/low", item_low)
        assert await store.get("https://example.com/low") is None


# ── Webnovel Fast-Path ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_webnovel_fastpath_synthetic() -> None:
    book_id = "1234567890123"
    book_url = f"https://www.webnovel.com/book/{book_id}"

    # Giả lập HTML mục lục với 3 chapter ID lộn xộn
    html = f"""
    <html>
    <head><title>Zero Fate - Webnovel</title></head>
    <body>
        <h1>Zero Fate</h1>
        <div class="chapter-list">
            <a href="/book/{book_id}/9999999999003">Chapter 3</a>
            <a href="/book/{book_id}/9999999999001">Chapter 1</a>
            <a href="/book/{book_id}/9999999999002">Chapter 2</a>
        </div>
    </body>
    </html>
    """

    with tempfile.TemporaryDirectory() as td:
        store = ClassificationStore(Path(td) / "cache.json")
        res = await classify_url(
            book_url,
            prefetched_html=html,
            cache_store=store,
            force=True,
        )

        assert res.page_type == "index"
        assert res.confidence == 0.99
        assert res.first_chapter_url == f"https://www.webnovel.com/book/{book_id}/9999999999001"
        assert res.story_title == "Zero Fate"


@pytest.mark.skipif(
    not (FIXTURES_LOCAL / "www.webnovel.com" / "zero_fate_against_the_world" / "meta.json").exists(),
    reason="Thiếu fixtures_local Webnovel",
)
@pytest.mark.asyncio
async def test_webnovel_fastpath_with_fixture() -> None:
    meta_path = FIXTURES_LOCAL / "www.webnovel.com" / "zero_fate_against_the_world" / "meta.json"
    with open(meta_path, encoding="utf-8") as f:
        meta = json.load(f)

    first_ch = meta["chapters"][0]
    first_ch_url = first_ch["url"]
    first_ch_html = (meta_path.parent / first_ch["file"]).read_text(encoding="utf-8")

    with tempfile.TemporaryDirectory() as td:
        store = ClassificationStore(Path(td) / "cache.json")
        # Gọi với URL của chính chương 1
        res = await classify_url(
            first_ch_url,
            prefetched_html=first_ch_html,
            cache_store=store,
            force=True,
        )

        assert res.confidence == 0.99
        assert res.page_type == "chapter"
        # Fast path trích xuất first_chapter_url chứa ID nhỏ nhất
        assert res.first_chapter_url is not None


# ── Code-First Heuristic Classifier ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_classify_heuristic_chapter() -> None:
    url = "https://example.com/novel/the-story/chapter-1"
    html = """
    <html>
    <head><title>Chapter 1: The Awakening - The Story</title></head>
    <body>
        <h1>Chapter 1: The Awakening</h1>
        <div class="content">
            <p>Once upon a time in a far away realm of wonder.</p>
        </div>
    </body>
    </html>
    """
    res = await classify_url(url, prefetched_html=html, force=True)
    assert res.page_type == "chapter"
    assert res.confidence >= 0.8
    assert res.chapter_title == "Chapter 1: The Awakening"


@pytest.mark.asyncio
async def test_classify_heuristic_index_with_start_button() -> None:
    url = "https://example.com/novel/the-story"
    html = """
    <html>
    <head><title>The Story - NovelSite</title></head>
    <body>
        <h1>The Story</h1>
        <div class="actions">
            <a class="btn-read" href="/novel/the-story/ch1">Start Reading</a>
        </div>
    </body>
    </html>
    """
    res = await classify_url(url, prefetched_html=html, force=True)
    assert res.page_type == "index"
    assert res.confidence >= 0.8
    assert res.first_chapter_url == "https://example.com/novel/the-story/ch1"


# ── AI Classification Fallback & resolve_start_url ───────────────────────────

@pytest.mark.asyncio
async def test_classify_url_ai_fallback() -> None:
    """Khi HTML không rõ ràng (không match heuristic), gọi AI phân loại."""
    url = "https://ambiguous-site.com/fiction/item-99"
    html = """
    <html>
    <head><title>Ambiguous Fiction</title></head>
    <body>
        <div class="main-body">
            <p>Some random description without clear keywords.</p>
            <a href="/fiction/item-99/part-one">Begin Tale</a>
        </div>
    </body>
    </html>
    """

    fake_ai = FakeProvider()
    fake_ai.set_response(
        PageClassificationOutput,
        PageClassificationOutput(
            page_type="index",
            story_title="Ambiguous Fiction",
            first_chapter_url="/fiction/item-99/part-one",
            confidence=0.88,
            reasoning="AI identified landing page with Begin Tale link",
        ),
    )

    with tempfile.TemporaryDirectory() as td:
        store = ClassificationStore(Path(td) / "cache.json")

        # Lần 1: Gọi qua AI
        res = await classify_url(
            url,
            prefetched_html=html,
            ai_provider=fake_ai,
            cache_store=store,
        )

        assert res.page_type == "index"
        assert res.first_chapter_url == "https://ambiguous-site.com/fiction/item-99/part-one"
        assert fake_ai.call_count == 1

        # Lần 2: Cache hit -> không gọi AI thêm lần nào
        res2 = await classify_url(
            url,
            prefetched_html=html,
            ai_provider=fake_ai,
            cache_store=store,
        )
        assert res2.page_type == "index"
        assert fake_ai.call_count == 1  # Vẫn là 1


@pytest.mark.asyncio
async def test_resolve_start_url() -> None:
    """resolve_start_url chuyển hướng index -> first_chapter_url."""
    index_url = "https://example.com/novel/the-story"
    html_index = """
    <html>
    <head><title>The Story - NovelSite</title></head>
    <body>
        <a href="/novel/the-story/ch1">Start Reading</a>
    </body>
    </html>
    """

    final_url, classification = await resolve_start_url(
        index_url,
        prefetched_html=html_index,
        force=True,
    )
    assert final_url == "https://example.com/novel/the-story/ch1"
    assert classification.page_type == "index"

    # Với URL chương thì giữ nguyên
    chap_url = "https://example.com/novel/the-story/ch1"
    html_chap = "<html><head><title>Chapter 1</title></head><body><h1>Chapter 1</h1></body></html>"
    final_chap, _ = await resolve_start_url(chap_url, prefetched_html=html_chap, force=True)
    assert final_chap == chap_url


@pytest.mark.asyncio
async def test_classify_url_with_pool_tuple_return() -> None:
    """Kiểm tra classify_url và Webnovel fast-path hoạt động chuẩn khi gọi qua pool.fetch trả về (status, html)."""

    class DummyPool:
        def __init__(self, pages: dict[str, tuple[int, str]]) -> None:
            self.pages = pages

        async def fetch(self, url: str, timeout: float | None = None, referer: str | None = None) -> tuple[int, str]:
            return self.pages.get(url, (404, ""))

    book_id = "1234567890123"
    book_url = f"https://www.webnovel.com/book/{book_id}"
    wn_html = f"""
    <html>
    <head><title>Pool Story - Webnovel</title></head>
    <body>
        <a href="/book/{book_id}/9000000000002">Ch 2</a>
        <a href="/book/{book_id}/9000000000001">Ch 1</a>
    </body>
    </html>
    """
    generic_url = "https://example.com/novel/pool-test"
    generic_html = """
    <html>
    <head><title>Pool Novel</title></head>
    <body>
        <h1>Pool Novel</h1>
        <a href="/novel/pool-test/chapter-1">Start Reading</a>
    </body>
    </html>
    """
    pool = DummyPool({
        book_url: (200, wn_html),
        generic_url: (200, generic_html),
    })

    with tempfile.TemporaryDirectory() as td:
        store = ClassificationStore(Path(td) / "cache.json")

        # 1. Webnovel fast-path qua pool (không truyền prefetched_html)
        wn_res = await classify_url(book_url, pool=pool, cache_store=store, force=True)  # type: ignore[arg-type]
        assert wn_res.page_type == "index"
        assert wn_res.first_chapter_url == f"https://www.webnovel.com/book/{book_id}/9000000000001"
        assert wn_res.confidence == 0.99

        # 2. Generic URL qua pool (không truyền prefetched_html)
        gen_url, gen_res = await resolve_start_url(
            generic_url,
            pool=pool,  # type: ignore[arg-type]
            cache_store=store,
            force=True,
        )
        assert gen_res.page_type == "index"
        assert gen_url == "https://example.com/novel/pool-test/chapter-1"
