"""tests/test_file_flow.py — Kiểm thử luồng xử lý file hợp nhất run_file_flow (Task 6.1)."""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from cao_text.files.flow import detect_input_type, run_file_flow
from cao_text.models import FileSpec, RunConfig
from conftest import assert_dir_contents_match

PROJECT_ROOT = Path(__file__).resolve().parent.parent
FIXTURES_ROOT = PROJECT_ROOT / "tests" / "fixtures"
GOLDEN_ROOT = PROJECT_ROOT / "tests" / "golden"


# ── Test detect_input_type ────────────────────────────────────────────────────

def test_detect_input_type(tmp_path: Path) -> None:
    # 1. EPUB
    epub_file = tmp_path / "book.epub"
    epub_file.write_bytes(b"dummy")
    assert detect_input_type(epub_file) == "epub"

    # 2. TXT raw text
    txt_file = tmp_path / "novel.txt"
    txt_file.write_text("Chương 1: Khởi đầu\nNội dung truyện...", encoding="utf-8")
    assert detect_input_type(txt_file) == "txt"

    # 3. TXT containing web URLs (links file)
    links_file = tmp_path / "links.txt"
    links_file.write_text(
        "# Danh sách truyện\nhttps://www.webnovel.com/book/123\n",
        encoding="utf-8",
    )
    assert detect_input_type(links_file) == "web"

    # 4. Unknown extension
    other_file = tmp_path / "data.json"
    other_file.write_text("{}", encoding="utf-8")
    assert detect_input_type(other_file) == "web"


# ── Test run_file_flow with EPUB (3 output modes vs golden) ───────────────────

@pytest.mark.parametrize("epub_stem", ["sample_with_toc", "sample_no_toc_part_divider"])
@pytest.mark.parametrize("mode", ["obsidian", "translate", "raw"])
async def test_run_file_flow_epub_golden(epub_stem: str, mode: str) -> None:
    epub_path = FIXTURES_ROOT / "epub" / f"{epub_stem}.epub"
    expected_dir = GOLDEN_ROOT / "epub" / epub_stem / mode

    assert epub_path.exists(), f"Thiếu fixture EPUB: {epub_path}"
    assert expected_dir.exists(), f"Thiếu golden EPUB: {expected_dir}"

    with tempfile.TemporaryDirectory() as td:
        cfg = RunConfig.create_for_mode(mode, output_dir=td)  # type: ignore[arg-type]
        spec = FileSpec(
            input_path=epub_path,
            run_config=cfg,
            input_type="epub",
        )
        count = await run_file_flow(spec)
        assert count > 0

        subdirs = [p for p in Path(td).iterdir() if p.is_dir()]
        assert subdirs, "run_file_flow không tạo thư mục đầu ra"
        actual_dir = subdirs[0]

        assert_dir_contents_match(
            actual_dir,
            expected_dir,
            is_synthetic=True,
            update_golden=False,
        )


# ── Test run_file_flow with TXT (3 output modes vs golden) ────────────────────

@pytest.mark.parametrize("txt_stem", ["vn_chuong_sample", "en_chapter_sample"])
@pytest.mark.parametrize("mode", ["obsidian", "translate", "raw"])
async def test_run_file_flow_txt_golden(txt_stem: str, mode: str) -> None:
    txt_path = FIXTURES_ROOT / "txt" / f"{txt_stem}.txt"
    expected_dir = GOLDEN_ROOT / "txt" / txt_stem / mode

    assert txt_path.exists(), f"Thiếu fixture TXT: {txt_path}"
    assert expected_dir.exists(), f"Thiếu golden TXT: {expected_dir}"

    with tempfile.TemporaryDirectory() as td:
        cfg = RunConfig.create_for_mode(mode, output_dir=td)  # type: ignore[arg-type]
        spec = FileSpec(
            input_path=txt_path,
            run_config=cfg,
            input_type="txt",
        )
        count = await run_file_flow(spec)
        assert count > 0

        subdirs = [p for p in Path(td).iterdir() if p.is_dir()]
        assert subdirs, "run_file_flow không tạo thư mục đầu ra"
        actual_dir = subdirs[0]

        assert_dir_contents_match(
            actual_dir,
            expected_dir,
            is_synthetic=True,
            update_golden=False,
        )


# ── Test run_file_flow callbacks & error handling ─────────────────────────────

async def test_run_file_flow_callback_and_shorthand(tmp_path: Path) -> None:
    txt_path = FIXTURES_ROOT / "txt" / "vn_chuong_sample.txt"
    out_dir = tmp_path / "output"

    events: list[tuple[int, str]] = []

    def on_done(idx: int, title: str) -> None:
        events.append((idx, title))

    cfg = RunConfig.create_for_mode("raw", output_dir=str(out_dir))

    # Gọi dạng shorthand run_file_flow(path, run_config=cfg)
    count = await run_file_flow(
        txt_path,
        run_config=cfg,
        on_chapter_done=on_done,
    )
    assert count == 3
    assert len(events) == 3
    assert events[0] == (1, "Chương 1: Khởi đầu nơi sơn thôn")


async def test_run_file_flow_invalid_type(tmp_path: Path) -> None:
    dummy = tmp_path / "invalid.pdf"
    dummy.write_bytes(b"%PDF-1.4")

    with pytest.raises(ValueError, match="Không hỗ trợ xử lý file"):
        await run_file_flow(dummy)


# ── Test run_file_flow với EPUB Local (Small & Large, Task 6.5) ───────────────

FIXTURES_LOCAL_ROOT = PROJECT_ROOT / "tests" / "fixtures_local"
GOLDEN_LOCAL_ROOT = PROJECT_ROOT / "tests" / "golden_local"


@pytest.mark.skipif(
    not (FIXTURES_LOCAL_ROOT / "epub").exists(),
    reason="Không có tests/fixtures_local/epub",
)
@pytest.mark.parametrize("epub_stem", ["Ready_Player_One", "Around_the_World_in_Eighty_Days"])
@pytest.mark.parametrize("mode", ["obsidian", "translate", "raw"])
async def test_run_file_flow_epub_local_small(epub_stem: str, mode: str) -> None:
    epub_path = FIXTURES_LOCAL_ROOT / "epub" / f"{epub_stem}.epub"
    expected_dir = GOLDEN_LOCAL_ROOT / "epub" / epub_stem / mode

    if not epub_path.exists():
        pytest.skip(f"Thiếu file EPUB local: {epub_path}")
    if not expected_dir.exists():
        pytest.skip(f"Thiếu golden EPUB local: {expected_dir}")

    with tempfile.TemporaryDirectory() as td:
        cfg = RunConfig.create_for_mode(mode, output_dir=td)  # type: ignore[arg-type]
        spec = FileSpec(
            input_path=epub_path,
            run_config=cfg,
            input_type="epub",
        )
        count = await run_file_flow(spec)
        assert count > 0

        subdirs = [p for p in Path(td).iterdir() if p.is_dir()]
        assert subdirs, "run_file_flow không tạo thư mục đầu ra"
        actual_dir = subdirs[0]

        assert_dir_contents_match(
            actual_dir,
            expected_dir,
            is_synthetic=False,
            min_ratio=0.99,
            update_golden=False,
        )


@pytest.mark.skipif(
    not (FIXTURES_LOCAL_ROOT / "epub" / "Dinh_Cap_Khi_Van_1631_chaps.epub").exists(),
    reason="Thiếu file EPUB lớn 1631 chaps",
)
async def test_run_file_flow_epub_local_large(run_slow: bool) -> None:
    if not run_slow:
        pytest.skip("Chạy kèm flag '--run-slow' để kiểm tra bộ EPUB 1631 chương (~60s)")

    epub_path = FIXTURES_LOCAL_ROOT / "epub" / "Dinh_Cap_Khi_Van_1631_chaps.epub"
    expected_dir = GOLDEN_LOCAL_ROOT / "epub" / "Dinh_Cap_Khi_Van_1631_chaps" / "obsidian"

    with tempfile.TemporaryDirectory() as td:
        cfg = RunConfig.create_for_mode("obsidian", output_dir=td)
        cfg.download_images = False
        spec = FileSpec(
            input_path=epub_path,
            run_config=cfg,
            input_type="epub",
        )
        count = await run_file_flow(spec)
        # Kiểm tra DoD Task 6.5: tách đúng >= 1500 chương, không dồn chương
        assert count >= 1500, f"Số chương tạo ra ({count}) phải >= 1500"

        subdirs = [p for p in Path(td).iterdir() if p.is_dir()]
        assert subdirs, "run_file_flow không tạo thư mục đầu ra"
        actual_dir = subdirs[0]

        assert_dir_contents_match(
            actual_dir,
            expected_dir,
            is_synthetic=False,
            min_ratio=0.99,
            update_golden=False,
        )

