"""tests/test_epub_plan.py — Kiểm thử lập kế hoạch EPUB qua rules và AI, fix §7.3 (Task 6.2)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from ebooklib import epub

from cao_text.ai.schemas import EpubRulesOutput
from cao_text.files.epub_plan import (
    ChapterPlan,
    EpubPlanCache,
    apply_epub_rules,
    build_chapter_plan,
    build_chapter_plan_rule_based,
    compute_file_sha256,
    flatten_toc,
    is_divider_title,
    is_rule_plan_reliable,
    merge_dividers,
    normalize_href,
    smart_title_from_toc,
    verify_epub_plan,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
FIXTURES_ROOT = PROJECT_ROOT / "tests" / "fixtures" / "epub"
LOCAL_EPUB_ROOT = PROJECT_ROOT / "tests" / "fixtures_local" / "epub"


# ── 1. Helper & Unit Tests ────────────────────────────────────────────────────

def test_normalize_href() -> None:
    assert normalize_href("text/ch01.xhtml#sub1") == "text/ch01.xhtml"
    assert normalize_href("/Text/Chapter02.HTML") == "text/chapter02.html"
    assert normalize_href(None) == ""


def test_flatten_toc() -> None:
    class FakeTocItem:
        def __init__(self, title: str, href: str) -> None:
            self.title = title
            self.href = href

    toc = [
        FakeTocItem("Cover", "cover.xhtml"),
        (
            FakeTocItem("Part 1", "part1.xhtml"),
            [
                FakeTocItem("Chapter 1", "ch01.xhtml"),
                FakeTocItem("Chapter 2", "ch02.xhtml"),
            ],
        ),
        FakeTocItem("Epilogue", "epilogue.xhtml"),
    ]

    flat = flatten_toc(toc)
    assert len(flat) == 5
    assert flat[0] == ("Cover", "cover.xhtml")
    assert flat[1] == ("Part 1", "part1.xhtml")
    assert flat[2] == ("Chapter 1", "ch01.xhtml")
    assert flat[3] == ("Chapter 2", "ch02.xhtml")
    assert flat[4] == ("Epilogue", "epilogue.xhtml")


def test_is_divider_title() -> None:
    assert is_divider_title("Part 1")
    assert is_divider_title("Part One:")
    assert is_divider_title("Level Two")
    assert is_divider_title("Book 3 —")
    assert is_divider_title("Quyển 1")
    assert is_divider_title("Phần II.")
    assert not is_divider_title("Chapter 1: The Beginning")
    assert not is_divider_title("Something else")
    assert not is_divider_title(None)


def test_smart_title_from_toc() -> None:
    assert smart_title_from_toc("0", 0) == "Prologue"
    assert smart_title_from_toc("1", 1) == "Chapter 1"
    assert smart_title_from_toc("Chapter 42: Battle", 42) == "Chapter 42: Battle"
    assert smart_title_from_toc(None, 5) == "Chapter 5"


def test_apply_epub_rules_unit() -> None:
    epub_path = FIXTURES_ROOT / "sample_with_toc.epub"
    book = epub.read_epub(str(epub_path))
    rules = EpubRulesOutput(
        chapter_title_regex=r"Chapter\s+\d+",
        front_matter_keywords=["cover"],
        back_matter_keywords=["about"],
        front_matter_hrefs=[],
        back_matter_hrefs=[],
        divider_title_regex=r"Part\s+\d+",
        merge_unnamed_into_previous=True,
    )
    plan = apply_epub_rules(book, rules)
    assert len(plan) > 0
    chapters = [p for p in plan if p.kind == "chapter"]
    assert len(chapters) >= 2


def test_merge_dividers() -> None:
    chapters = [
        ChapterPlan(index=1, kind="chapter", title="Part 1", doc_ids=["p1"]),
        ChapterPlan(index=2, kind="chapter", title="Chapter 1: Dawn", doc_ids=["d1"]),
        ChapterPlan(index=3, kind="chapter", title="Chapter 2: Dusk", doc_ids=["d2"]),
        ChapterPlan(index=4, kind="chapter", title="Level Two", doc_ids=["p2"]),
        ChapterPlan(index=5, kind="chapter", title="Chapter 3: Night", doc_ids=["d3"]),
    ]

    merged = merge_dividers(chapters)
    assert len(merged) == 3
    assert merged[0].title == "Part 1 — Chapter 1: Dawn"
    assert merged[0].doc_ids == ["p1", "d1"]
    assert merged[0].index == 1

    assert merged[1].title == "Chapter 2: Dusk"
    assert merged[1].doc_ids == ["d2"]
    assert merged[1].index == 2

    assert merged[2].title == "Level Two — Chapter 3: Night"
    assert merged[2].doc_ids == ["p2", "d3"]
    assert merged[2].index == 3


# ── 2. Rule-Based Plan on Sample Fixtures ─────────────────────────────────────

def test_build_chapter_plan_rule_based_sample_with_toc() -> None:
    epub_path = FIXTURES_ROOT / "sample_with_toc.epub"
    assert epub_path.exists()
    book = epub.read_epub(str(epub_path))

    plan = build_chapter_plan_rule_based(book)
    assert len(plan) > 0
    assert is_rule_plan_reliable(plan, book) is True

    # Kiểm tra có mục kind="chapter"
    chapters = [p for p in plan if p.kind == "chapter"]
    assert len(chapters) == 3
    assert "Chapter 1" in (chapters[0].title or "")
    assert "Part 1 — Chapter 2" in (chapters[1].title or "")
    assert "Chapter 3" in (chapters[2].title or "")


def test_build_chapter_plan_rule_based_no_toc() -> None:
    epub_path = FIXTURES_ROOT / "sample_no_toc_part_divider.epub"
    assert epub_path.exists()
    book = epub.read_epub(str(epub_path))

    plan = build_chapter_plan_rule_based(book)
    # File này không có TOC nên tất cả tài liệu dồn vào matter/bucket ban đầu
    # hoặc trả về plan không tin cậy -> kích hoạt tách no-TOC ở flow
    assert len(plan) > 0


# ── 3. Verification & Guard against §7.3 Token Exhaustion ──────────────────────

def test_verify_epub_plan_token_exhaustion_guard() -> None:
    dummy_book = MagicMock()

    # Kế hoạch hợp lệ: 10 chương, mỗi chương 1-2 docs
    valid_plan = [
        ChapterPlan(index=i, kind="chapter", title=f"Chapter {i}", doc_ids=[f"doc_{i}"])
        for i in range(1, 11)
    ]
    ok, reason = verify_epub_plan(valid_plan, dummy_book)
    assert ok is True
    assert reason == "Hợp lệ"

    # Kế hoạch bị lỗi §7.3: 9 chương đầu mỗi chương 1 doc, nhưng chương cuối gom 50 docs
    # vì AI chạm trần token làm đứt danh sách
    corrupted_plan = [
        ChapterPlan(index=i, kind="chapter", title=f"Chapter {i}", doc_ids=[f"doc_{i}"])
        for i in range(1, 10)
    ]
    corrupted_plan.append(
        ChapterPlan(
            index=10,
            kind="chapter",
            title="Chapter 10",
            doc_ids=[f"tail_doc_{j}" for j in range(50)],
        )
    )

    ok_corrupted, reason_corrupted = verify_epub_plan(corrupted_plan, dummy_book)
    assert ok_corrupted is False
    assert "> 5× trung vị" in reason_corrupted


# ── 4. Cache Versioning & Backward Compatibility ──────────────────────────────

def test_epub_plan_cache_version2_and_legacy(tmp_path: Path) -> None:
    cache_file = tmp_path / "epub_analyses.json"
    cache = EpubPlanCache(cache_file)

    # 1. Ban đầu cache rỗng
    assert cache.get("abc123hash") is None

    # 2. Giả lập cache cũ format v1 (chưa có trường version: 2)
    v1_data = {
        "old_hash_111": {
            "filename": "old_book.epub",
            "plan": [{"index": 1, "kind": "chapter", "title": "Old Chap 1", "doc_ids": ["d1"]}],
        }
    }
    cache_file.write_text(json.dumps(v1_data), encoding="utf-8")

    # 3. Ghi cache mới version 2
    new_plan = [
        ChapterPlan(index=1, kind="chapter", title="New Chap 1", doc_ids=["doc_a", "doc_b"])
    ]
    cache.set(
        file_hash="new_hash_222",
        filename="new_book.epub",
        rules={"rule": "regex"},
        plan=new_plan,
    )

    # 4. Kiểm tra file cache trên đĩa
    saved_data = json.loads(cache_file.read_text(encoding="utf-8"))
    assert saved_data.get("version") == 2
    assert "new_hash_222" in saved_data["analyses"]
    # Dữ liệu v1 cũ phải được bảo toàn trong legacy_v1
    assert "legacy_v1" in saved_data
    assert "old_hash_111" in saved_data["legacy_v1"]

    # 5. Đọc lại từ cache
    retrieved = cache.get("new_hash_222")
    assert retrieved is not None
    assert len(retrieved) == 1
    assert retrieved[0].title == "New Chap 1"
    assert retrieved[0].doc_ids == ["doc_a", "doc_b"]


# ── 5. AI Rules Application & Fallback ────────────────────────────────────────

class MockAiProvider:
    def __init__(self, rules_output: EpubRulesOutput | Exception) -> None:
        self.rules_output = rules_output
        self.call_count = 0

    async def generate(self, prompt: str, schema: Any) -> Any:
        self.call_count += 1
        if isinstance(self.rules_output, Exception):
            raise self.rules_output
        return self.rules_output


@pytest.mark.asyncio
async def test_build_chapter_plan_with_ai_success(tmp_path: Path) -> None:
    epub_path = FIXTURES_ROOT / "sample_with_toc.epub"
    book = epub.read_epub(str(epub_path))
    cache_file = tmp_path / "cache.json"

    ai_output = EpubRulesOutput(
        chapter_title_regex=r"Chapter\s+\d+",
        front_matter_keywords=["cover", "toc"],
        back_matter_keywords=["epilogue", "about"],
        front_matter_hrefs=[],
        back_matter_hrefs=[],
        divider_title_regex=r"Part\s+\d+",
        merge_unnamed_into_previous=True,
    )
    provider = MockAiProvider(ai_output)

    plan = await build_chapter_plan(
        book=book,
        epub_path=epub_path,
        ai_provider=provider,  # type: ignore[arg-type]
        force_ai=True,
        cache_file=cache_file,
    )

    assert provider.call_count == 1
    assert len(plan) > 0
    # Đã lưu vào cache
    cache = EpubPlanCache(cache_file)
    cached = cache.get(compute_file_sha256(epub_path))
    assert cached is not None


@pytest.mark.asyncio
async def test_build_chapter_plan_with_ai_failure_fallback(tmp_path: Path) -> None:
    epub_path = FIXTURES_ROOT / "sample_with_toc.epub"
    book = epub.read_epub(str(epub_path))
    cache_file = tmp_path / "cache.json"

    # AI ném lỗi ngoại lệ
    provider = MockAiProvider(RuntimeError("AI network error"))

    plan = await build_chapter_plan(
        book=book,
        epub_path=epub_path,
        ai_provider=provider,  # type: ignore[arg-type]
        force_ai=True,
        cache_file=cache_file,
    )

    # An toàn quay về rule_plan
    assert len(plan) > 0
    assert any(p.kind == "chapter" for p in plan)


# ── 6. Large EPUB Fixture Test (Fix §7.3 Verification) ────────────────────────

def test_large_epub_fixture_plan_if_available() -> None:
    large_epub = LOCAL_EPUB_ROOT / "Dinh_Cap_Khi_Van_1631_chaps.epub"
    if not large_epub.exists():
        pytest.skip(f"Không có fixture EPUB lớn tại {large_epub}")

    book = epub.read_epub(str(large_epub))
    plan = build_chapter_plan_rule_based(book)

    # File có 1631 chương, TOC đầy đủ
    chapters = [p for p in plan if p.kind == "chapter"]
    assert len(chapters) >= 1000, f"Số chương tìm được ({len(chapters)}) phải >= 1000"

    # Kiểm chứng an toàn: không chương nào bị dồn > 5× trung vị
    ok, reason = verify_epub_plan(plan, book)
    assert ok is True, f"Kiểm chứng plan thất bại: {reason}"
