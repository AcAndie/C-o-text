"""cli.py — Giao diện dòng lệnh (CLI) chính của Cào Text v2 (Phase 7).

Hỗ trợ đầy đủ các hành vi và cờ CLI từ v1:
  - Input mặc định từ config.toml (settings.paths.links_file: Vault/_Scraper/links.md).
  - Điều phối 3 loại input: Web links file, file EPUB đơn lẻ, file TXT đơn lẻ.
  - Tự động quét và xử lý EPUB inbox (data/processed_epubs.json) trước khi cào web.
  - Tự động sửa chữa các file 0000_Index.md bị thiếu do Ctrl+C ở phiên trước (heal_missing_indexes).
  - Chế độ --bulk-relearn với dry-run mặc định và xác nhận --apply.
  - Hỗ trợ đầy đủ các cờ CLI: --output-mode, --output-dir, --max-pw-instances,
    --per-host-concurrency, --fast-learning, --no-validation, --pattern.
"""
from __future__ import annotations

import argparse
import asyncio
import io
import logging
import re
import sys
import time
from collections.abc import Sequence
from pathlib import Path

from cao_text import __version__
from cao_text.files.flow import detect_input_type, run_file_flow
from cao_text.files.inbox import process_epub_inbox
from cao_text.log import setup_logging
from cao_text.models import FileSpec, RunConfig
from cao_text.net.browser import PlaywrightPool
from cao_text.net.http import DomainSessionPool
from cao_text.settings import Settings, get_settings
from cao_text.storage import ProfileStore, ProgressStore
from cao_text.web.runner import (
    apply_relearn,
    close_pools,
    parse_links,
    run_web_tasks,
    silence_windows_transport_errors,
)
from cao_text.writers.nav_injector import heal_missing_indexes

logger = logging.getLogger("cao_text.cli")


def build_parser() -> argparse.ArgumentParser:
    """Khởi tạo ArgumentParser tương thích 100% với các cờ CLI cũ."""
    parser = argparse.ArgumentParser(
        prog="cao-text",
        description="Cào Text v2 — Chuẩn hóa tiểu thuyết từ Web, EPUB, TXT sang Obsidian/translate/raw.",
    )
    parser.add_argument(
        "input",
        nargs="?",
        default=None,
        help="Đường dẫn file links.md/.txt, hoặc đường dẫn đơn lẻ tới file .epub/.txt (mặc định lấy từ config).",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"Cào Text v{__version__}",
    )
    parser.add_argument(
        "--output-mode",
        choices=["obsidian", "translate", "raw"],
        default=None,
        help="Chế độ đầu ra: obsidian (mặc định), translate, hoặc raw.",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Thư mục lưu kết quả (ghi đè config.toml).",
    )
    parser.add_argument(
        "--max-pw-instances",
        type=int,
        default=None,
        metavar="N",
        help="Số instance Playwright tối đa chạy đồng thời (mặc định: 2).",
    )
    parser.add_argument(
        "--per-host-concurrency",
        type=int,
        default=None,
        metavar="N",
        help="Số request đồng thời tối đa trên mỗi domain (mặc định: 3).",
    )
    parser.add_argument(
        "--fast-learning",
        action="store_true",
        help="Bỏ qua bước phân tích độ trù phú văn xuôi khi học site để tăng tốc.",
    )
    parser.add_argument(
        "--no-validation",
        action="store_true",
        help="Bỏ qua bộ lọc kiểm chứng ProseRichness.",
    )
    parser.add_argument(
        "--bulk-relearn",
        action="store_true",
        help="Xóa hàng loạt profile để học lại từ đầu (mặc định dry-run, cần --apply).",
    )
    parser.add_argument(
        "--pattern",
        default=None,
        metavar="REGEX",
        help="Biểu thức chính quy lọc domain khi dùng --bulk-relearn, hoặc pattern ranh giới chương TXT.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Xác nhận thực thi xóa thật khi dùng --bulk-relearn.",
    )
    return parser


def apply_cli_overrides(args: argparse.Namespace, settings: Settings) -> None:
    """Cập nhật các thiết lập ghi đè từ tham số dòng lệnh vào đối tượng Settings."""
    if args.output_mode is not None:
        settings.output.mode = args.output_mode
    if args.output_dir is not None:
        settings.paths.output_dir = args.output_dir
    if args.max_pw_instances is not None:
        settings.scraper.max_pw_instances = args.max_pw_instances
    if args.per_host_concurrency is not None:
        settings.http.per_host_concurrency = args.per_host_concurrency
    if args.fast_learning:
        settings.learning.fast_learning = True
    if args.no_validation:
        settings.learning.no_validation = True


async def run_bulk_relearn(
    pattern: str | None,
    apply: bool,
    profile_store: ProfileStore,
) -> int:
    """Quản lý xóa hàng loạt profile có xác nhận an toàn (Task 7.2)."""
    profiles = await profile_store.load_all()
    if not profiles:
        print("Không có profile nào trong cơ sở dữ liệu site_profiles.json.")
        return 0

    if pattern:
        try:
            rx = re.compile(pattern, re.IGNORECASE)
            matched = {k: v for k, v in profiles.items() if rx.search(k)}
        except re.error as e:
            print(f"[ERR] Biểu thức chính quy không hợp lệ: {e}")
            return 1
    else:
        matched = dict(profiles)

    if not matched:
        print(f"Không có profile nào khớp với pattern {pattern!r}.")
        return 0

    print(f"Phát hiện {len(matched)} profile khớp:")
    for dom in sorted(matched):
        p = matched[dom]
        last = getattr(p, "last_learned", None) or "?"
        conf = getattr(p, "confidence", 0.0)
        print(f"  - {dom} (độ tin cậy: {conf:.2f}, học lần cuối: {last})")

    if not apply:
        print("\n[DRY RUN] — Chưa thực hiện xóa. Hãy thêm cờ --apply để tiến hành xóa thật.")
        return 0

    expected = f"delete {len(matched)} profiles"
    print(f"\nĐể xác nhận xóa thật, vui lòng gõ chính xác: {expected}")
    try:
        ans = input("> ").strip()
    except (EOFError, KeyboardInterrupt):
        print("\nĐã hủy lệnh.")
        return 1

    if ans != expected:
        print("Xác nhận không khớp. Đã hủy lệnh xóa.")
        return 1

    deleted_count = 0
    for dom in matched:
        if await profile_store.delete(dom):
            deleted_count += 1

    print(f"\n✔ Đã xóa thành công {deleted_count} profile. Chạy lại để học lại cấu trúc site.")
    return 0


def format_elapsed(seconds: float) -> str:
    """Định dạng thời gian chạy hh:mm:ss."""
    s = int(seconds)
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{sec:02d}"


async def async_main(argv: Sequence[str] | None = None) -> int:
    """Hàm bất đồng bộ chính của CLI."""
    parser = build_parser()
    args = parser.parse_args(argv)

    setup_logging()
    settings = get_settings()
    apply_cli_overrides(args, settings)

    profile_store = ProfileStore()
    progress_store = ProgressStore()

    # 1. Chế độ Bulk Relearn
    if args.bulk_relearn:
        return await run_bulk_relearn(args.pattern, args.apply, profile_store)

    run_config = RunConfig.create_for_mode(
        settings.output.mode,
        output_dir=settings.paths.output_dir,
    )

    print(
        f"⚙️  [Cấu hình] mode={run_config.output_mode} | "
        f"tải ảnh={run_config.download_images} | "
        f"output={run_config.output_dir!r}",
        flush=True,
    )

    # 2. Tự động sửa missing 0000_Index.md do Ctrl+C ở phiên trước (§6.1)
    if run_config.output_dir:
        try:
            await heal_missing_indexes(run_config.output_dir)
        except Exception as e:
            logger.debug("[Heal] Tự động sửa Index gặp lỗi: %s", e)

    # 3. Khởi tạo AI provider nếu có key
    ai_provider = None
    if settings.ai.api_keys:
        try:
            from cao_text.ai.gemini import GeminiProvider

            ai_provider = GeminiProvider(
                api_keys=settings.ai.api_keys,
                model=settings.ai.model,
                fallback_model=settings.ai.fallback_model,
                max_rpm=settings.ai.max_rpm,
            )
        except Exception as e:
            logger.warning("[AI] Không thể khởi tạo GeminiProvider: %s", e)

    # 4. Tự động xử lý EPUB inbox nếu có file mới (§7.1)
    inbox_processed = 0
    if settings.paths.epub_inbox_dir:
        inbox_processed = await process_epub_inbox(
            inbox_dir=settings.paths.epub_inbox_dir,
            run_config=run_config,
            ai_provider=ai_provider,
        )

    # 5. Xác định mục tiêu đầu vào
    target_input = args.input or settings.paths.links_file
    target_path = Path(target_input)

    if not target_path.exists():
        if inbox_processed > 0:
            # Inbox đã hoàn tất việc xử lý
            return 0
        print(f"[ERR] Không tìm thấy file đầu vào: {target_input}", flush=True)
        return 1

    input_type = detect_input_type(target_path)
    t0 = time.time()

    # 6. Dispatch theo loại đầu vào
    if input_type == "epub":
        print(f"\n📖 [EPUB] Bắt đầu xử lý file đơn lẻ: {target_path.name}", flush=True)
        spec = FileSpec(
            input_path=target_path,
            run_config=run_config,
            input_type="epub",
            ai_provider=ai_provider,
        )
        count = await run_file_flow(spec)
        elapsed = format_elapsed(time.time() - t0)
        print(f"\n✔ [EPUB] Hoàn tất {count} chương trong {elapsed}\n", flush=True)
        return 0

    if input_type == "txt":
        print(f"\n📄 [TXT] Bắt đầu xử lý file văn bản: {target_path.name}", flush=True)
        spec = FileSpec(
            input_path=target_path,
            run_config=run_config,
            input_type="txt",
            pattern=args.pattern,
            ai_provider=ai_provider,
        )
        count = await run_file_flow(spec)
        elapsed = format_elapsed(time.time() - t0)
        print(f"\n✔ [TXT] Hoàn tất {count} chương trong {elapsed}\n", flush=True)
        return 0

    # 7. Xử lý Web links file
    urls, relearn_domains = parse_links(target_path)
    if relearn_domains:
        removed = await apply_relearn(relearn_domains, profile_store)
        if removed:
            print(f"  [Config] 🗑 Đã xóa {removed} profile domain theo chỉ thị !relearn", flush=True)

    if not urls:
        if inbox_processed > 0:
            return 0
        print(f"[ERR] Không tìm thấy URL hợp lệ nào trong {target_input}", flush=True)
        return 1

    from cao_text.log import write_session_header

    print(f"📚 {len(urls)} truyện web cần cào\n", flush=True)
    write_session_header(len(urls))

    pool = DomainSessionPool(
        per_host_concurrency=settings.http.per_host_concurrency,
        default_timeout=settings.http.default_timeout,
    )
    pw_pool = PlaywrightPool(
        max_concurrency=settings.scraper.max_pw_instances,
    )

    total_chapters_done = 0

    def on_ch_done() -> None:
        nonlocal total_chapters_done
        total_chapters_done += 1

    try:
        results = await run_web_tasks(
            urls,
            pool=pool,
            pw_pool=pw_pool,
            profile_store=profile_store,
            progress_store=progress_store,
            run_config=run_config,
            ai_provider=ai_provider,
            init_stagger=settings.scraper.init_stagger,
            on_chapter_done=on_ch_done,
            issue_reporter=None,
            auto_heal_indexes=False,  # Đã heal ở đầu phiên
            close_pools_on_finish=False,
        )
    finally:
        await close_pools(pool=pool, pw_pool=pw_pool, timeout=5.0)

    elapsed = format_elapsed(time.time() - t0)
    failed_count = sum(1 for r in results if isinstance(r, Exception))

    print(f"\n{'─' * 60}", flush=True)
    if failed_count > 0:
        print(f"⚠️  Tổng kết: {total_chapters_done} chương hoàn thành ({failed_count} lỗi) trong {elapsed}", flush=True)
    else:
        print(f"✔ Tổng kết: {total_chapters_done} chương hoàn thành trong {elapsed}", flush=True)
    print(f"{'─' * 60}\n", flush=True)

    return 0 if failed_count == 0 else 1


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point đồng bộ cho CLI với xử lý an toàn tín hiệu Windows/Unix."""
    # Đảm bảo UTF-8 stream cho console Windows
    if sys.platform == "win32":
        if isinstance(sys.stdout, io.TextIOWrapper):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if isinstance(sys.stderr, io.TextIOWrapper):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    silence_windows_transport_errors()

    try:
        return asyncio.run(async_main(argv))
    except KeyboardInterrupt:
        print("\n⚠️  Nhận tín hiệu dừng (Ctrl+C). Tiến độ đã được lưu.", flush=True)
        return 130
    except asyncio.CancelledError:
        print("\n⚠️  Tiến trình bị hủy bỏ. Tiến độ đã được lưu.", flush=True)
        return 130
    except Exception as e:
        print(f"\n❌ Lỗi nghiêm trọng: {e}", flush=True)
        logger.exception("Lỗi không mong muốn trong main: %s", e)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
