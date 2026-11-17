"""inbox.py — Quản lý và tự động xử lý thư mục EPUB inbox với manifest SHA256 (Task 7.1).

Người dùng thả các file .epub vào thư mục inbox (mặc định Vault/_Scraper/epub_inbox/).
Mỗi lần chạy CLI:
  1. Quét thư mục inbox.
  2. Bỏ qua các file đã xử lý (đã có mã băm SHA256 trong data/processed_epubs.json).
  3. Xử lý các file mới bằng run_file_flow.
  4. Sau khi hoàn thành thành công, ghi nhận mã băm vào manifest.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from cao_text.files.flow import run_file_flow
from cao_text.models import FileSpec, RunConfig
from cao_text.settings import get_settings
from cao_text.storage import atomic_write_json
from cao_text.writers.obsidian import slugify_filename

if TYPE_CHECKING:
    from cao_text.ai.provider import LLMProvider

logger = logging.getLogger(__name__)

_MANIFEST_LOCK = threading.Lock()


def sha256_file(path: str | Path, chunk_size: int = 65536) -> str:
    """Tính mã băm SHA256 của file theo từng khối để xử lý an toàn file lớn."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(chunk_size):
            h.update(chunk)
    return h.hexdigest()


def load_manifest(manifest_path: str | Path | None = None) -> dict[str, Any]:
    """Đọc dữ liệu manifest các file EPUB đã xử lý."""
    p = (
        Path(manifest_path)
        if manifest_path is not None
        else Path(get_settings().paths.data_dir) / "processed_epubs.json"
    )
    if not p.exists():
        return {}
    with _MANIFEST_LOCK:
        try:
            with open(p, encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except Exception as e:
            logger.warning("[EpubInbox] Đọc manifest thất bại (%s): %s", p, e)
            return {}


def save_manifest(data: dict[str, Any], manifest_path: str | Path | None = None) -> None:
    """Lưu dữ liệu manifest an toàn với atomic write."""
    p = (
        Path(manifest_path)
        if manifest_path is not None
        else Path(get_settings().paths.data_dir) / "processed_epubs.json"
    )
    with _MANIFEST_LOCK:
        atomic_write_json(p, data)


def mark_processed(
    file_hash: str,
    filename: str,
    slug: str,
    chapters: int,
    manifest_path: str | Path | None = None,
) -> None:
    """Ghi nhận một file EPUB đã được bóc tách thành công vào manifest."""
    manifest = load_manifest(manifest_path)
    manifest[file_hash] = {
        "filename": filename,
        "slug": slug,
        "processed_at": datetime.now(UTC).isoformat(),
        "chapters": chapters,
    }
    save_manifest(manifest, manifest_path)


def scan_inbox(
    inbox_dir: str | Path | None = None,
    manifest_path: str | Path | None = None,
) -> tuple[list[tuple[Path, str]], list[Path]]:
    """Quét thư mục inbox và so sánh với manifest.

    Trả về:
      todo: danh sách (path, sha256) các file mới cần xử lý
      skipped: danh sách các file đã xử lý trước đó
    """
    inbox = (
        Path(inbox_dir)
        if inbox_dir is not None
        else Path(get_settings().paths.epub_inbox_dir)
    )
    if not inbox.exists():
        return [], []

    manifest = load_manifest(manifest_path)
    todo: list[tuple[Path, str]] = []
    skipped: list[Path] = []

    for fpath in sorted(inbox.glob("*.epub")):
        if not fpath.is_file():
            continue
        try:
            h = sha256_file(fpath)
        except OSError as e:
            logger.warning("[EpubInbox] Không thể tính hash file %s: %s", fpath.name, e)
            continue

        if h in manifest:
            skipped.append(fpath)
        else:
            todo.append((fpath, h))

    return todo, skipped


async def process_epub_inbox(
    inbox_dir: str | Path | None = None,
    manifest_path: str | Path | None = None,
    run_config: RunConfig | None = None,
    ai_provider: LLMProvider | None = None,
) -> int:
    """Xử lý hàng loạt các file EPUB mới trong inbox.

    Returns:
      Số lượng file EPUB được xử lý thành công.
    """
    todo, skipped = scan_inbox(inbox_dir, manifest_path)
    if not todo and not skipped:
        return 0

    print(f"\n📥 EPUB Inbox: {len(todo)} mới, {len(skipped)} đã xử lý", flush=True)
    for p in skipped:
        print(f"  ⏭  Bỏ qua: {p.name}", flush=True)

    if not todo:
        return 0

    cfg = run_config or RunConfig()
    processed_count = 0

    for fpath, file_hash in todo:
        print(f"\n📖 [Inbox] Xử lý: {fpath.name}", flush=True)
        try:
            spec = FileSpec(
                input_path=fpath,
                run_config=cfg,
                input_type="epub",
                ai_provider=ai_provider,
            )
            n_chapters = await run_file_flow(spec)
            mark_processed(
                file_hash=file_hash,
                filename=fpath.name,
                slug=slugify_filename(fpath.stem),
                chapters=n_chapters,
                manifest_path=manifest_path,
            )
            processed_count += 1
        except asyncio.CancelledError:
            raise
        except Exception as e:
            print(f"  ❌ {fpath.name}: {e} (sẽ thử lại lần sau)", flush=True)
            logger.warning("[EpubInbox] Lỗi xử lý %s: %s", fpath.name, e)

    print(f"\n✔ EPUB Inbox hoàn thành: {processed_count}/{len(todo)} file đã xử lý\n", flush=True)
    return processed_count


__all__ = [
    "load_manifest",
    "mark_processed",
    "process_epub_inbox",
    "save_manifest",
    "scan_inbox",
    "sha256_file",
]
