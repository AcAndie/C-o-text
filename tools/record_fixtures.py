"""
tools/record_fixtures.py — Tải HTML thô của N chương liên tiếp làm local fixtures.

Dùng DomainSessionPool (+ PlaywrightPool fallback) và find_next_url của code cũ
để đi theo next-link từ --url, lưu vào:
    tests/fixtures_local/web/<domain>/<story>/0001.html, 0002.html...
    tests/fixtures_local/web/<domain>/<story>/meta.json

Ví dụ chạy từ thư mục gốc dự án:
    python tools/record_fixtures.py \\
        --url "https://www.royalroad.com/fiction/55418/rock-falls-everyone-dies/chapter/1083016/chapter-1-a-rolling-stone-gathers-no-moss" \\
        --story "rock_falls_everyone_dies" \\
        --chapters 6
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from bs4 import BeautifulSoup  # noqa: E402

from config import PROFILES_FILE, get_delay  # noqa: E402
from core.fetch import fetch_page  # noqa: E402
from core.navigator import find_next_url  # noqa: E402
from core.session_pool import DomainSessionPool, PlaywrightPool  # noqa: E402
from utils.file_io import load_profiles  # noqa: E402

logger = logging.getLogger(__name__)

FIXTURES_WEB_ROOT = PROJECT_ROOT / "tests" / "fixtures_local" / "web"


def _atomic_write_text(path: Path, content: str) -> None:
    """Ghi text xuống đĩa theo kiểu atomic (.tmp -> os.replace)."""
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
    """Ghi JSON xuống đĩa theo kiểu atomic (.tmp -> os.replace)."""
    text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    _atomic_write_text(path, text)


def _derive_story_slug(url: str) -> str:
    """Tự suy ra tên thư mục story từ URL nếu user không truyền --story."""
    path = urlparse(url).path.strip("/")
    parts = [p for p in path.split("/") if p]
    # RoyalRoad: /fiction/55418/rock-falls-everyone-dies/chapter/...
    if len(parts) >= 3 and parts[0].lower() == "fiction":
        slug = parts[2]
    # Webnovel: /book/30780541908206305/82625129275771249
    elif len(parts) >= 2 and parts[0].lower() == "book":
        slug = f"book_{parts[1]}"
    elif parts:
        slug = parts[0]
    else:
        slug = "story"
    clean = re.sub(r"[^a-zA-Z0-9_-]+", "_", slug).strip("_").lower()
    return clean or "story"


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Ghi HTML thô của N chương liên tiếp vào tests/fixtures_local/web/<domain>/<story>/",
    )
    parser.add_argument(
        "--url",
        required=True,
        help="URL bắt đầu (chương 1 hoặc trang bất kỳ cần ghi).",
    )
    parser.add_argument(
        "--story",
        default=None,
        help="Tên thư mục story (mặc định tự suy từ URL).",
    )
    parser.add_argument(
        "--domain",
        default=None,
        help="Domain key trong site_profiles.json (mặc định lấy từ --url).",
    )
    parser.add_argument(
        "--chapters",
        type=int,
        default=6,
        help="Số chương liên tiếp cần tải (mặc định: 6).",
    )
    parser.add_argument(
        "--out-dir",
        default=None,
        help="Thư mục gốc lưu fixtures web (mặc định: tests/fixtures_local/web).",
    )
    parser.add_argument(
        "--no-delay",
        action="store_true",
        help="Tắt delay ngẫu nhiên giữa các chương (chỉ dùng khi debug nhanh).",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Bật log DEBUG.",
    )
    return parser.parse_args(argv)


async def record_story_fixtures(
    start_url: str,
    *,
    story_slug: str | None = None,
    domain: str | None = None,
    max_chapters: int = 6,
    out_root: Path = FIXTURES_WEB_ROOT,
    no_delay: bool = False,
) -> Path:
    """Tải N chương liên tiếp từ start_url và lưu HTML + meta.json."""
    parsed_domain = (domain or urlparse(start_url).netloc).lower().strip()
    slug = story_slug or _derive_story_slug(start_url)
    target_dir = out_root / parsed_domain / slug
    target_dir.mkdir(parents=True, exist_ok=True)

    profiles: dict[str, Any] = {}
    profiles_path = PROJECT_ROOT / PROFILES_FILE
    if profiles_path.exists():
        profiles = await load_profiles(str(profiles_path))

    profile: dict[str, Any] = dict(profiles.get(parsed_domain) or {})
    if not profile:
        # Thử fallback bỏ/thêm www.
        alt_domain = (
            parsed_domain.removeprefix("www.")
            if parsed_domain.startswith("www.")
            else f"www.{parsed_domain}"
        )
        profile = dict(profiles.get(alt_domain) or {})
        if profile:
            logger.info("Dùng profile từ domain tương đương: %s", alt_domain)

    if not profile:
        logger.warning(
            "Không tìm thấy profile cho %s trong %s — sẽ dùng heuristic điều hướng mặc định.",
            parsed_domain,
            PROFILES_FILE,
        )

    pool = DomainSessionPool()
    pw_pool = PlaywrightPool()

    recorded_items: list[dict[str, Any]] = []
    visited_urls: set[str] = set()
    current_url: str | None = start_url
    prev_url: str | None = None

    logger.info(
        "Bắt đầu ghi fixtures: domain=%s, story=%s, chapters=%d -> %s",
        parsed_domain,
        slug,
        max_chapters,
        target_dir,
    )

    try:
        for idx in range(1, max_chapters + 1):
            if not current_url:
                logger.info("Không còn next_url ở chương %d — dừng.", idx - 1)
                break

            if current_url in visited_urls:
                logger.warning("Phát hiện vòng lặp URL đã thăm (%s) — dừng.", current_url)
                break

            if idx > 1 and not no_delay:
                delay = get_delay(current_url)
                logger.info("Chờ %.1fs trước khi tải chương %d...", delay, idx)
                await asyncio.sleep(delay)

            logger.info("[%d/%d] Đang tải: %s", idx, max_chapters, current_url)
            status, html = await fetch_page(
                current_url,
                pool,
                pw_pool,
                profile=profile,
                referer=prev_url,
            )

            if status != 200 or not html.strip():
                logger.error(
                    "Tải thất bại ở chương %d (%s): HTTP %s, len=%d — dừng.",
                    idx,
                    current_url,
                    status,
                    len(html),
                )
                break

            file_name = f"{idx:04d}.html"
            file_path = target_dir / file_name
            _atomic_write_text(file_path, html)

            visited_urls.add(current_url)

            soup = await asyncio.to_thread(BeautifulSoup, html, "lxml")
            next_url = await asyncio.to_thread(
                find_next_url,
                soup,
                current_url,
                profile,
            )

            recorded_items.append(
                {
                    "index": idx,
                    "file": file_name,
                    "url": current_url,
                    "status_code": status,
                    "html_chars": len(html),
                    "next_url_discovered": next_url,
                }
            )
            logger.info(
                "Đã lưu %s (%d ký tự) -> next: %s",
                file_name,
                len(html),
                next_url or "<none>",
            )

            prev_url = current_url
            current_url = next_url

    except asyncio.CancelledError:
        logger.warning("Bị hủy (CancelledError) — vẫn lưu meta.json cho các chương đã tải.")
        raise
    finally:
        await pw_pool.close()
        if recorded_items:
            meta = {
                "domain": parsed_domain,
                "story": slug,
                "start_url": start_url,
                "recorded_at": datetime.now(UTC).isoformat(),
                "chapters_requested": max_chapters,
                "chapters_recorded": len(recorded_items),
                "urls": [item["url"] for item in recorded_items],
                "chapters": recorded_items,
                "profile": profile,
            }
            meta_path = target_dir / "meta.json"
            _atomic_write_json(meta_path, meta)
            logger.info("Đã ghi %s (%d chương).", meta_path, len(recorded_items))

    return target_dir


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )
    out_root = Path(args.out_dir) if args.out_dir else FIXTURES_WEB_ROOT
    asyncio.run(
        record_story_fixtures(
            args.url,
            story_slug=args.story,
            domain=args.domain,
            max_chapters=args.chapters,
            out_root=out_root,
            no_delay=args.no_delay,
        )
    )


if __name__ == "__main__":
    main()
