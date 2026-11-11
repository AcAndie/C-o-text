"""
tools/make_golden_v1.py — Chạy code cũ offline trên fixtures để tạo golden baseline.

Mục tiêu:
  - Web: với mỗi HTML fixture trong tests/fixtures_local/web/, chạy PipelineRunner.run()
    với profile trong meta.json, áp strip_nav_edges + bỏ dòng trùng tiêu đề.
    Lưu {url, title, content, next_url, nav_method, selector_used} thành JSON trong
    tests/golden_local/web/<domain>/<story>/<file_stem>.json.
  - EPUB/TXT: chạy run_epub_flow / run_txt_flow với ai_limiter=None cho cả 3 output mode
    (obsidian, translate, raw) vào thư mục tạm, chép kết quả vào tests/golden/ (cho fixtures
    commit được) và tests/golden_local/ (cho fixtures local).

Cách chạy:
    python tools/make_golden_v1.py           # chạy tất cả (web, epub, txt)
    python tools/make_golden_v1.py --web     # chỉ chạy web
    python tools/make_golden_v1.py --txt     # chỉ chạy txt
    python tools/make_golden_v1.py --epub    # chỉ chạy epub
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from config import ADS_DB_FILE  # noqa: E402
from core.chapter_writer import strip_nav_edges  # noqa: E402
from core.navigator import find_next_url  # noqa: E402
from core.orchestrator import run_epub_flow, run_txt_flow  # noqa: E402
from pipeline.executor import PipelineRunner  # noqa: E402
from utils.types import RunConfig  # noqa: E402

logger = logging.getLogger(__name__)

FIXTURES_ROOT = PROJECT_ROOT / "tests" / "fixtures"
FIXTURES_LOCAL_ROOT = PROJECT_ROOT / "tests" / "fixtures_local"
GOLDEN_ROOT = PROJECT_ROOT / "tests" / "golden"
GOLDEN_LOCAL_ROOT = PROJECT_ROOT / "tests" / "golden_local"

OUTPUT_MODES: list[str] = ["obsidian", "translate", "raw"]


def _atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(tmp_path, path)
    except BaseException:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass
        raise


def _atomic_write_json(path: Path, data: Any) -> None:
    text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    _atomic_write_text(path, text)


def _copy_dir_contents(src_dir: Path, dst_dir: Path) -> int:
    """Sao chép toàn bộ file trong src_dir sang dst_dir, xóa dst_dir cũ nếu có."""
    if dst_dir.exists():
        shutil.rmtree(dst_dir)
    dst_dir.mkdir(parents=True, exist_ok=True)
    count = 0
    for root, _, files in os.walk(src_dir):
        rel_root = Path(root).relative_to(src_dir)
        target_root = dst_dir / rel_root
        target_root.mkdir(parents=True, exist_ok=True)
        for f in sorted(files):
            shutil.copy2(Path(root) / f, target_root / f)
            count += 1
    return count


class _PreserveAdsDb:
    """Context manager bảo vệ file data/ads_keywords.json của user không bị thay đổi."""

    def __init__(self) -> None:
        self.ads_path = PROJECT_ROOT / ADS_DB_FILE
        self.backup_content: str | None = None

    def __enter__(self) -> None:
        if self.ads_path.exists():
            try:
                self.backup_content = self.ads_path.read_text(encoding="utf-8")
            except Exception as e:
                logger.warning("Không thể backup ads_keywords.json: %s", e)

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        if self.backup_content is not None:
            try:
                _atomic_write_text(self.ads_path, self.backup_content)
            except Exception as e:
                logger.warning("Không thể khôi phục ads_keywords.json: %s", e)


async def make_web_golden(
    fixtures_dir: Path = FIXTURES_LOCAL_ROOT / "web",
    out_dir: Path = GOLDEN_LOCAL_ROOT / "web",
) -> int:
    """Tạo golden output cho các HTML fixtures của web."""
    if not fixtures_dir.exists():
        logger.warning("Thư mục web fixtures không tồn tại: %s", fixtures_dir)
        return 0

    total_chapters = 0
    for domain_entry in sorted(fixtures_dir.iterdir()):
        if not domain_entry.is_dir():
            continue
        domain = domain_entry.name

        for story_entry in sorted(domain_entry.iterdir()):
            if not story_entry.is_dir():
                continue
            story = story_entry.name
            meta_path = story_entry / "meta.json"
            if not meta_path.exists():
                continue

            with open(meta_path, encoding="utf-8") as f:
                meta = json.load(f)

            profile = meta.get("profile", {})
            chapters = meta.get("chapters", [])
            target_story_dir = out_dir / domain / story
            target_story_dir.mkdir(parents=True, exist_ok=True)

            logger.info("Xử lý Web Golden: %s / %s (%d chương)", domain, story, len(chapters))

            runner = PipelineRunner.from_profile(profile)

            for ch in chapters:
                file_name = ch["file"]
                html_path = story_entry / file_name
                if not html_path.exists():
                    continue

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

                # 1. strip_nav_edges
                stripped = strip_nav_edges(content)
                if stripped and len(stripped.strip()) >= 100:
                    content = stripped

                # 2. Bỏ dòng tiêu đề trùng ở đầu content
                content_lines = content.split("\n")
                if content_lines:
                    first_line = content_lines[0].strip().lstrip("#").strip()
                    if first_line and title and first_line.lower() == title.lower():
                        content = "\n".join(content_lines[1:]).lstrip("\n")

                # 3. Next URL
                next_url = ctx.next_url
                if not next_url and ctx.soup:
                    next_url = find_next_url(ctx.soup, url, profile)

                golden_record = {
                    "url": url,
                    "title": title,
                    "content": content,
                    "next_url": next_url,
                    "nav_method": ctx.nav_method,
                    "selector_used": ctx.selector_used,
                }

                out_json_name = Path(file_name).stem + ".json"
                _atomic_write_json(target_story_dir / out_json_name, golden_record)
                total_chapters += 1

    logger.info("Đã tạo golden cho %d chương web -> %s", total_chapters, out_dir)
    return total_chapters


async def make_txt_golden(
    fixtures_dir: Path = FIXTURES_ROOT / "txt",
    out_dir: Path = GOLDEN_ROOT / "txt",
) -> int:
    """Tạo golden output cho các file TXT fixtures."""
    if not fixtures_dir.exists():
        logger.warning("Thư mục TXT fixtures không tồn tại: %s", fixtures_dir)
        return 0

    total_runs = 0
    txt_files = sorted(fixtures_dir.glob("*.txt"))

    for txt_path in txt_files:
        stem = txt_path.stem

        for mode in OUTPUT_MODES:
            logger.info("Xử lý TXT Golden: %s [mode=%s]", stem, mode)
            with tempfile.TemporaryDirectory() as td:
                cfg = RunConfig(
                    output_mode=mode,  # type: ignore[arg-type]
                    download_images=(mode == "obsidian"),
                    image_placeholder=(mode == "translate"),
                    fetch_metadata=(mode == "obsidian"),
                    output_dir=td,
                )
                await run_txt_flow(str(txt_path), cfg, ai_limiter=None)

                # Tìm thư mục đầu ra trong td
                subdirs = [p for p in Path(td).iterdir() if p.is_dir()]
                if not subdirs:
                    logger.warning("Không tìm thấy thư mục output cho TXT: %s [%s]", stem, mode)
                    continue
                src_story_dir = subdirs[0]
                target_mode_dir = out_dir / stem / mode
                count = _copy_dir_contents(src_story_dir, target_mode_dir)
                total_runs += 1
                logger.info("  -> Đã chép %d file vào %s", count, target_mode_dir)

    return total_runs


async def make_epub_golden(
    fixtures_dir: Path,
    out_dir: Path,
    label: str = "EPUB",
) -> int:
    """Tạo golden output cho các file EPUB fixtures."""
    if not fixtures_dir.exists():
        logger.warning("Thư mục EPUB %s không tồn tại: %s", label, fixtures_dir)
        return 0

    total_runs = 0
    epub_files = sorted(fixtures_dir.glob("*.epub"))

    for epub_path in epub_files:
        stem = epub_path.stem

        for mode in OUTPUT_MODES:
            logger.info("Xử lý %s Golden: %s [mode=%s]", label, stem, mode)
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
                if not subdirs:
                    logger.warning("Không tìm thấy output cho %s: %s [%s]", label, stem, mode)
                    continue
                src_story_dir = subdirs[0]
                target_mode_dir = out_dir / stem / mode
                count = _copy_dir_contents(src_story_dir, target_mode_dir)
                total_runs += 1
                logger.info("  -> Đã chép %d file vào %s", count, target_mode_dir)

    return total_runs


async def run_all(args: argparse.Namespace) -> None:
    do_all = not (args.web or args.txt or args.epub)
    include_commit = not args.only_local
    include_local = not args.only_commit

    with _PreserveAdsDb():
        if (do_all or args.web) and include_local:
            print("\n" + "=" * 60)
            print("▶ Bắt đầu sinh Golden cho Web (Local)...")
            print("=" * 60)
            await make_web_golden()

        if (do_all or args.txt) and include_commit:
            print("\n" + "=" * 60)
            print("▶ Bắt đầu sinh Golden cho TXT (Commitable)...")
            print("=" * 60)
            await make_txt_golden()

        if do_all or args.epub:
            if include_commit:
                print("\n" + "=" * 60)
                print("▶ Bắt đầu sinh Golden cho EPUB (Commitable)...")
                print("=" * 60)
                await make_epub_golden(
                    fixtures_dir=FIXTURES_ROOT / "epub",
                    out_dir=GOLDEN_ROOT / "epub",
                    label="EPUB (Commitable)",
                )

            if include_local:
                print("\n" + "=" * 60)
                print("▶ Bắt đầu sinh Golden cho EPUB (Local)...")
                print("=" * 60)
                await make_epub_golden(
                    fixtures_dir=FIXTURES_LOCAL_ROOT / "epub",
                    out_dir=GOLDEN_LOCAL_ROOT / "epub",
                    label="EPUB (Local)",
                )

    print("\n" + "=" * 60)
    print("✔ Hoàn thành tạo golden v1 baseline.")
    print("=" * 60)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Chạy code cũ v1.2.1 offline trên fixtures để tạo golden baseline."
    )
    parser.add_argument("--web", action="store_true", help="Chỉ sinh golden cho web.")
    parser.add_argument("--txt", action="store_true", help="Chỉ sinh golden cho txt.")
    parser.add_argument("--epub", action="store_true", help="Chỉ sinh golden cho epub.")
    parser.add_argument(
        "--only-commit",
        action="store_true",
        help="Chỉ sinh golden cho fixtures commit được (tests/fixtures/).",
    )
    parser.add_argument(
        "--only-local",
        action="store_true",
        help="Chỉ sinh golden cho fixtures local (tests/fixtures_local/).",
    )
    parser.add_argument("--verbose", action="store_true", help="Bật log DEBUG.")

    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    if sys.platform == "win32":
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        def _silence_transport_errors(lp: asyncio.AbstractEventLoop, context: dict[str, Any]) -> None:
            msg = context.get("message", "")
            exc = context.get("exception")
            exc_str = str(exc) if exc else ""
            if any(
                kw in msg.lower() or kw in exc_str.lower()
                for kw in ("i/o operation on closed", "transport", "pipe")
            ):
                return
            lp.default_exception_handler(context)

        loop.set_exception_handler(_silence_transport_errors)
        try:
            loop.run_until_complete(run_all(args))
        finally:
            loop.close()
    else:
        asyncio.run(run_all(args))


if __name__ == "__main__":
    main()
