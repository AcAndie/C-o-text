"""tests/test_cli.py — Kiểm thử giao diện dòng lệnh CLI và EPUB inbox (Task 7.1 & 7.2)."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from cao_text.cli import (
    apply_cli_overrides,
    async_main,
    build_parser,
    format_elapsed,
    main,
    run_bulk_relearn,
)
from cao_text.files.inbox import (
    load_manifest,
    mark_processed,
    process_epub_inbox,
    scan_inbox,
    sha256_file,
)
from cao_text.models import SiteProfile
from cao_text.settings import get_settings
from cao_text.storage import ProfileStore
from cao_text.writers.nav_injector import heal_missing_indexes

PROJECT_ROOT = Path(__file__).resolve().parent.parent
FIXTURES_ROOT = PROJECT_ROOT / "tests" / "fixtures"


# ── 1. Parser & CLI Overrides Tests (Task 7.2) ────────────────────────────────

def test_build_parser_options() -> None:
    parser = build_parser()
    args = parser.parse_args([
        "my_links.md",
        "--output-mode", "translate",
        "--output-dir", "custom_out",
        "--max-pw-instances", "4",
        "--per-host-concurrency", "5",
        "--fast-learning",
        "--no-validation",
        "--bulk-relearn",
        "--pattern", "royalroad",
        "--apply",
    ])
    assert args.input == "my_links.md"
    assert args.output_mode == "translate"
    assert args.output_dir == "custom_out"
    assert args.max_pw_instances == 4
    assert args.per_host_concurrency == 5
    assert args.fast_learning is True
    assert args.no_validation is True
    assert args.bulk_relearn is True
    assert args.pattern == "royalroad"
    assert args.apply is True


def test_apply_cli_overrides() -> None:
    parser = build_parser()
    args = parser.parse_args([
        "--output-mode", "raw",
        "--output-dir", "test_vault",
        "--max-pw-instances", "3",
        "--per-host-concurrency", "2",
        "--fast-learning",
        "--no-validation",
    ])
    settings = get_settings()
    apply_cli_overrides(args, settings)

    assert settings.output.mode == "raw"
    assert settings.paths.output_dir == "test_vault"
    assert settings.scraper.max_pw_instances == 3
    assert settings.http.per_host_concurrency == 2
    assert settings.learning.fast_learning is True
    assert settings.learning.no_validation is True


def test_format_elapsed() -> None:
    assert format_elapsed(45) == "00:00:45"
    assert format_elapsed(125) == "00:02:05"
    assert format_elapsed(3665) == "01:01:05"


# ── 2. Bulk Relearn Tests (Task 7.2) ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_bulk_relearn_dry_run_and_apply(tmp_path: Path) -> None:
    profiles_file = tmp_path / "site_profiles.json"
    store = ProfileStore(profiles_file)

    p1 = SiteProfile(domain="royalroad.com", content_selector="div.chapter-inner")
    p2 = SiteProfile(domain="webnovel.com", content_selector="div.cha-words")
    p3 = SiteProfile(domain="69shuba.cx", content_selector="div.txtnav")
    await store.save(p1)
    await store.save(p2)
    await store.save(p3)

    # 1. Dry run: không xóa gì
    ret = await run_bulk_relearn(pattern="royalroad", apply=False, profile_store=store)
    assert ret == 0
    assert await store.get("royalroad.com") is not None

    # 2. Apply nhưng gõ sai xác nhận
    with patch("builtins.input", return_value="sai_xac_nhan"):
        ret_fail = await run_bulk_relearn(pattern="royalroad", apply=True, profile_store=store)
        assert ret_fail == 1
        assert await store.get("royalroad.com") is not None

    # 3. Apply với xác nhận chính xác
    with patch("builtins.input", return_value="delete 1 profiles"):
        ret_ok = await run_bulk_relearn(pattern="royalroad", apply=True, profile_store=store)
        assert ret_ok == 0
        assert await store.get("royalroad.com") is None
        assert await store.get("webnovel.com") is not None


# ── 3. EPUB Inbox Tests (Task 7.1) ────────────────────────────────────────────

def test_sha256_file_and_manifest(tmp_path: Path) -> None:
    sample_file = tmp_path / "test.epub"
    sample_file.write_bytes(b"epub sample binary content")

    h = sha256_file(sample_file)
    assert len(h) == 64

    manifest_file = tmp_path / "processed_epubs.json"
    assert load_manifest(manifest_file) == {}

    mark_processed(
        file_hash=h,
        filename="test.epub",
        slug="test_epub",
        chapters=10,
        manifest_path=manifest_file,
    )

    loaded = load_manifest(manifest_file)
    assert h in loaded
    assert loaded[h]["filename"] == "test.epub"
    assert loaded[h]["chapters"] == 10


@pytest.mark.asyncio
async def test_process_epub_inbox_workflow(tmp_path: Path) -> None:
    inbox_dir = tmp_path / "inbox"
    inbox_dir.mkdir(parents=True, exist_ok=True)
    manifest_file = tmp_path / "processed_epubs.json"
    out_dir = tmp_path / "out"

    # Chép 1 file fixture vào inbox
    fixture_epub = FIXTURES_ROOT / "epub" / "sample_with_toc.epub"
    assert fixture_epub.exists()
    dest_epub = inbox_dir / "my_story.epub"
    dest_epub.write_bytes(fixture_epub.read_bytes())

    todo, skipped = scan_inbox(inbox_dir=inbox_dir, manifest_path=manifest_file)
    assert len(todo) == 1
    assert len(skipped) == 0

    # Chạy xử lý inbox
    from cao_text.models import RunConfig
    cfg = RunConfig.create_for_mode("raw", output_dir=out_dir)

    n_processed = await process_epub_inbox(
        inbox_dir=inbox_dir,
        manifest_path=manifest_file,
        run_config=cfg,
    )
    assert n_processed == 1

    # Quét lại lần 2: file đã xử lý phải nằm trong danh sách skipped
    todo_2, skipped_2 = scan_inbox(inbox_dir=inbox_dir, manifest_path=manifest_file)
    assert len(todo_2) == 0
    assert len(skipped_2) == 1


# ── 4. Dispatch Input Tests (Task 7.1) ────────────────────────────────────────

@pytest.mark.asyncio
async def test_cli_dispatch_epub_single(tmp_path: Path) -> None:
    epub_path = FIXTURES_ROOT / "epub" / "sample_with_toc.epub"
    out_dir = tmp_path / "vault"

    code = await async_main([str(epub_path), "--output-mode", "raw", "--output-dir", str(out_dir)])
    assert code == 0

    subdirs = [p for p in out_dir.iterdir() if p.is_dir()]
    assert len(subdirs) == 1
    files = list(subdirs[0].glob("*.txt"))
    assert len(files) >= 2


@pytest.mark.asyncio
async def test_cli_dispatch_txt_single(tmp_path: Path) -> None:
    txt_path = FIXTURES_ROOT / "txt" / "vn_chuong_sample.txt"
    out_dir = tmp_path / "vault"

    code = await async_main([str(txt_path), "--output-mode", "raw", "--output-dir", str(out_dir)])
    assert code == 0

    subdirs = [p for p in out_dir.iterdir() if p.is_dir()]
    assert len(subdirs) == 1
    files = list(subdirs[0].glob("*.txt"))
    assert len(files) == 3


@pytest.mark.asyncio
async def test_cli_missing_input_file(tmp_path: Path) -> None:
    code = await async_main([str(tmp_path / "khong_ton_tai.md")])
    assert code == 1


# ── 5. Index Auto-Heal Test (§6.1) ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_heal_missing_indexes_on_startup(tmp_path: Path) -> None:
    output_root = tmp_path / "output_vault"
    story_dir = output_root / "Tien_Nghich"
    story_dir.mkdir(parents=True, exist_ok=True)

    # Giả lập 2 file chương .md tồn tại nhưng chưa có 0000_Index.md (do Ctrl+C ngắt quãng)
    (story_dir / "0001_Chuong_1.md").write_text("# Chương 1\nNội dung...", encoding="utf-8")
    (story_dir / "0002_Chuong_2.md").write_text("# Chương 2\nNội dung...", encoding="utf-8")

    index_file = story_dir / "0000_Index.md"
    assert not index_file.exists()

    healed_count = await heal_missing_indexes(output_root)
    assert healed_count >= 1
    assert index_file.exists()
    assert "Tien Nghich" in index_file.read_text(encoding="utf-8")


def test_main_entry_help() -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0
