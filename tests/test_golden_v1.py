"""
tests/test_golden_v1.py — Kiểm tra code cũ v1.2.1 so với golden baselines.
Phải vượt qua (xanh) ngay sau khi tạo golden ở Task 0.7.
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

import pytest

from conftest import (
    assert_dir_contents_match,
    assert_json_extract_match,
)
from core.chapter_writer import strip_nav_edges
from core.navigator import find_next_url
from core.orchestrator import run_epub_flow, run_txt_flow
from pipeline.executor import PipelineRunner
from utils.types import RunConfig

PROJECT_ROOT = Path(__file__).resolve().parent.parent
FIXTURES_ROOT = PROJECT_ROOT / "tests" / "fixtures"
FIXTURES_LOCAL_ROOT = PROJECT_ROOT / "tests" / "fixtures_local"
GOLDEN_ROOT = PROJECT_ROOT / "tests" / "golden"
GOLDEN_LOCAL_ROOT = PROJECT_ROOT / "tests" / "golden_local"


# ── TXT Commitable Tests ──────────────────────────────────────────────────────

@pytest.mark.parametrize("txt_stem", ["vn_chuong_sample", "en_chapter_sample"])
@pytest.mark.parametrize("mode", ["obsidian", "translate", "raw"])
async def test_golden_txt_commitable(txt_stem: str, mode: str) -> None:
    txt_path = FIXTURES_ROOT / "txt" / f"{txt_stem}.txt"
    expected_dir = GOLDEN_ROOT / "txt" / txt_stem / mode

    assert txt_path.exists(), f"Thiếu fixture TXT: {txt_path}"
    assert expected_dir.exists(), f"Thiếu golden TXT: {expected_dir}"

    with tempfile.TemporaryDirectory() as td:
        cfg = RunConfig(
            output_mode=mode,  # type: ignore[arg-type]
            download_images=(mode == "obsidian"),
            image_placeholder=(mode == "translate"),
            fetch_metadata=(mode == "obsidian"),
            output_dir=td,
        )
        await run_txt_flow(str(txt_path), cfg, ai_limiter=None)

        subdirs = [p for p in Path(td).iterdir() if p.is_dir()]
        assert subdirs, "run_txt_flow không tạo thư mục đầu ra"
        actual_dir = subdirs[0]

        assert_dir_contents_match(actual_dir, expected_dir, is_synthetic=True)


# ── EPUB Commitable Tests ─────────────────────────────────────────────────────

@pytest.mark.parametrize("epub_stem", ["sample_with_toc", "sample_no_toc_part_divider"])
@pytest.mark.parametrize("mode", ["obsidian", "translate", "raw"])
async def test_golden_epub_commitable(epub_stem: str, mode: str) -> None:
    epub_path = FIXTURES_ROOT / "epub" / f"{epub_stem}.epub"
    expected_dir = GOLDEN_ROOT / "epub" / epub_stem / mode

    assert epub_path.exists(), f"Thiếu fixture EPUB: {epub_path}"
    assert expected_dir.exists(), f"Thiếu golden EPUB: {expected_dir}"

    with tempfile.TemporaryDirectory() as td:
        cfg = RunConfig(
            output_mode=mode,  # type: ignore[arg-type]
            download_images=(mode == "obsidian"),
            image_placeholder=(mode == "translate"),
            fetch_metadata=(mode == "obsidian"),
            output_dir=td,
        )
        await run_epub_flow(str(epub_path), cfg, ai_limiter=None)

        subdirs = [p for p in Path(td).iterdir() if p.is_dir()]
        assert subdirs, "run_epub_flow không tạo thư mục đầu ra"
        actual_dir = subdirs[0]

        assert_dir_contents_match(actual_dir, expected_dir, is_synthetic=True)


# ── Web Local Tests ───────────────────────────────────────────────────────────

def _get_web_stories() -> list[tuple[str, str]]:
    web_dir = FIXTURES_LOCAL_ROOT / "web"
    if not web_dir.exists():
        return []
    stories = []
    for domain_dir in sorted(web_dir.iterdir()):
        if not domain_dir.is_dir():
            continue
        for story_dir in sorted(domain_dir.iterdir()):
            if (story_dir / "meta.json").exists():
                stories.append((domain_dir.name, story_dir.name))
    return stories


_WEB_STORIES = _get_web_stories()


@pytest.mark.skipif(not _WEB_STORIES, reason="Không tìm thấy tests/fixtures_local/web")
@pytest.mark.parametrize("domain, story", _WEB_STORIES)
async def test_golden_web_local(domain: str, story: str) -> None:
    fixture_story_dir = FIXTURES_LOCAL_ROOT / "web" / domain / story
    golden_story_dir = GOLDEN_LOCAL_ROOT / "web" / domain / story

    assert fixture_story_dir.exists(), f"Thiếu fixture web: {fixture_story_dir}"
    assert golden_story_dir.exists(), f"Thiếu golden web: {golden_story_dir}"

    with open(fixture_story_dir / "meta.json", encoding="utf-8") as f:
        meta: dict[str, Any] = json.load(f)

    profile = meta.get("profile", {})
    chapters = meta.get("chapters", [])
    assert chapters, f"meta.json không có chapters: {fixture_story_dir}"

    runner = PipelineRunner.from_profile(profile)

    for ch in chapters:
        file_name = ch["file"]
        html_path = fixture_story_dir / file_name
        golden_json_path = golden_story_dir / (Path(file_name).stem + ".json")

        assert html_path.exists(), f"Thiếu file HTML: {html_path}"
        assert golden_json_path.exists(), f"Thiếu file golden JSON: {golden_json_path}"

        html = html_path.read_text(encoding="utf-8")
        url = ch["url"]

        ctx = await runner.run(
            url=url,
            profile=profile,
            progress={},
            pool=None,
            pw_pool=None,
            ai_limiter=None,
            prefetched_html=html,
        )

        title = ctx.title_clean or "Unknown Title"
        content = ctx.content or ""

        stripped = strip_nav_edges(content)
        if stripped and len(stripped.strip()) >= 100:
            content = stripped

        content_lines = content.split("\n")
        if content_lines:
            first_line = content_lines[0].strip().lstrip("#").strip()
            if first_line and title and first_line.lower() == title.lower():
                content = "\n".join(content_lines[1:]).lstrip("\n")

        next_url = ctx.next_url
        if not next_url and ctx.soup:
            next_url = find_next_url(ctx.soup, url, profile)

        actual_record = {
            "url": url,
            "title": title,
            "content": content,
            "next_url": next_url,
            "nav_method": ctx.nav_method,
            "selector_used": ctx.selector_used,
        }

        with open(golden_json_path, encoding="utf-8") as f:
            expected_record: dict[str, Any] = json.load(f)

        assert_json_extract_match(
            actual_record,
            expected_record,
            min_content_ratio=0.99,
            context=f"{domain}/{story}/{file_name}",
        )


# ── EPUB Local Tests (Small) ──────────────────────────────────────────────────

_LOCAL_EPUB_SMALL = ["Ready_Player_One", "Around_the_World_in_Eighty_Days"]


def _local_epub_available(name: str) -> bool:
    return (FIXTURES_LOCAL_ROOT / "epub" / f"{name}.epub").exists()


@pytest.mark.skipif(
    not (FIXTURES_LOCAL_ROOT / "epub").exists(),
    reason="Không có tests/fixtures_local/epub",
)
@pytest.mark.parametrize("epub_stem", _LOCAL_EPUB_SMALL)
@pytest.mark.parametrize("mode", ["obsidian", "translate", "raw"])
async def test_golden_epub_local_small(epub_stem: str, mode: str) -> None:
    epub_path = FIXTURES_LOCAL_ROOT / "epub" / f"{epub_stem}.epub"
    expected_dir = GOLDEN_LOCAL_ROOT / "epub" / epub_stem / mode

    if not epub_path.exists():
        pytest.skip(f"Thiếu file EPUB local: {epub_path}")
    if not expected_dir.exists():
        pytest.skip(f"Thiếu golden EPUB local: {expected_dir}")

    with tempfile.TemporaryDirectory() as td:
        cfg = RunConfig(
            output_mode=mode,  # type: ignore[arg-type]
            download_images=(mode == "obsidian"),
            image_placeholder=(mode == "translate"),
            fetch_metadata=(mode == "obsidian"),
            output_dir=td,
        )
        await run_epub_flow(str(epub_path), cfg, ai_limiter=None)

        subdirs = [p for p in Path(td).iterdir() if p.is_dir()]
        assert subdirs, "run_epub_flow không tạo thư mục đầu ra"
        actual_dir = subdirs[0]

        assert_dir_contents_match(
            actual_dir,
            expected_dir,
            is_synthetic=False,
            min_ratio=0.99,
        )


# ── EPUB Local Tests (Large, Slow) ────────────────────────────────────────────

@pytest.mark.skipif(
    not (FIXTURES_LOCAL_ROOT / "epub" / "Dinh_Cap_Khi_Van_1631_chaps.epub").exists(),
    reason="Thiếu file EPUB lớn 1631 chaps",
)
async def test_golden_epub_local_large(run_slow: bool) -> None:
    if not run_slow:
        pytest.skip("Chạy kèm flag '--run-slow' để kiểm tra bộ EPUB 1631 chương (~60s)")

    epub_path = FIXTURES_LOCAL_ROOT / "epub" / "Dinh_Cap_Khi_Van_1631_chaps.epub"
    expected_dir = GOLDEN_LOCAL_ROOT / "epub" / "Dinh_Cap_Khi_Van_1631_chaps" / "obsidian"

    with tempfile.TemporaryDirectory() as td:
        cfg = RunConfig(
            output_mode="obsidian",
            download_images=False,
            image_placeholder=False,
            fetch_metadata=False,
            output_dir=td,
        )
        await run_epub_flow(str(epub_path), cfg, ai_limiter=None)

        subdirs = [p for p in Path(td).iterdir() if p.is_dir()]
        assert subdirs, "run_epub_flow không tạo thư mục đầu ra"
        actual_dir = subdirs[0]

        assert_dir_contents_match(
            actual_dir,
            expected_dir,
            is_synthetic=False,
            min_ratio=0.99,
        )
