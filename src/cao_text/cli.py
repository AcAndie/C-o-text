"""CLI cho Cào Text v2 (argparse, đọc links.md, dispatch web/epub/txt)."""
from __future__ import annotations

import argparse
from collections.abc import Sequence

from cao_text import __version__


def build_parser() -> argparse.ArgumentParser:
    """Khởi tạo ArgumentParser cho Cào Text v2."""
    parser = argparse.ArgumentParser(
        prog="cao-text",
        description="Cào Text v2 — Chuẩn hóa tiểu thuyết từ Web, EPUB, TXT sang Obsidian/translate/raw.",
    )
    parser.add_argument(
        "input",
        nargs="?",
        default=None,
        help="Đường dẫn file links.md/.txt, hoặc đường dẫn đơn lẻ tới file .epub/.txt.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
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
        help="Số instance Playwright tối đa chạy đồng thời.",
    )
    parser.add_argument(
        "--per-host-concurrency",
        type=int,
        default=None,
        help="Số request đồng thời tối đa trên mỗi domain.",
    )
    parser.add_argument(
        "--fast-learning",
        action="store_true",
        help="Chế độ học nhanh.",
    )
    parser.add_argument(
        "--no-validation",
        action="store_true",
        help="Bỏ qua bước kiểm chứng sau khi học profile.",
    )
    parser.add_argument(
        "--bulk-relearn",
        action="store_true",
        help="Học lại hàng loạt profile hiện có.",
    )
    parser.add_argument(
        "--pattern",
        default=None,
        help="Regex lọc domain khi dùng --bulk-relearn.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Thực thi thật khi dùng --bulk-relearn (mặc định dry-run).",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Hàm thực thi chính của CLI."""
    parser = build_parser()
    parser.parse_args(argv)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
