"""
utils/epub_inbox.py — Watch folder for EPUB batch processing (v1.0.6).

User drops .epub files into INBOX_DIR. Each `python main.py` run scans
inbox, processes new files, skips already-done (SHA256 hash-based).

Manifest format (data/processed_epubs.json):
  {
    "<sha256-hex>": {
      "filename": "book.epub",
      "slug": "book_title",
      "processed_at": "2026-05-17T12:34:56Z",
      "chapters": 42
    }
  }

Skip semantics:
  - Same hash → skip (rename file = still skip; idempotent)
  - Different hash same name → process (file edited / replaced)
  - Hash missing from manifest → process

Manifest write happens AFTER successful run_epub_flow — fail mid-process
leaves no entry, so next run retries.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
from datetime import datetime, timezone
from pathlib import Path

from config import DATA_DIR

logger = logging.getLogger(__name__)

INBOX_DIR     = os.path.join("input", "epub")   # v1.0.10: nested under input/
MANIFEST_FILE = os.path.join(DATA_DIR, "processed_epubs.json")
_LOCK         = threading.Lock()


def ensure_inbox() -> Path:
    """Create input/epub/ if missing. Return Path."""
    p = Path(INBOX_DIR)
    p.mkdir(parents=True, exist_ok=True)
    return p


def sha256_file(path: str | Path, chunk_size: int = 65536) -> str:
    """SHA256 of file content. Streamed read for large EPUBs."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def load_manifest() -> dict:
    if not os.path.exists(MANIFEST_FILE):
        return {}
    try:
        with open(MANIFEST_FILE, "r", encoding="utf-8") as f:
            return json.load(f) or {}
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("[EpubInbox] manifest load failed: %s — resetting", e)
        return {}


def save_manifest(data: dict) -> None:
    with _LOCK:
        os.makedirs(os.path.dirname(os.path.abspath(MANIFEST_FILE)), exist_ok=True)
        tmp = MANIFEST_FILE + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, MANIFEST_FILE)
        except OSError as e:
            logger.warning("[EpubInbox] manifest save failed: %s", e)


def mark_processed(
    file_hash : str,
    filename  : str,
    slug      : str,
    chapters  : int,
) -> None:
    """Add entry to manifest after successful run_epub_flow."""
    manifest = load_manifest()
    manifest[file_hash] = {
        "filename"     : filename,
        "slug"         : slug,
        "processed_at" : datetime.now(timezone.utc).isoformat(),
        "chapters"     : chapters,
    }
    save_manifest(manifest)


def scan_inbox() -> tuple[list[tuple[Path, str]], list[Path]]:
    """
    Scan INBOX_DIR for .epub files. Compare against manifest.

    Returns:
        todo:    list[(path, hash)] — new files needing processing
        skipped: list[Path]         — already-processed files
    """
    inbox    = ensure_inbox()
    manifest = load_manifest()

    todo    : list[tuple[Path, str]] = []
    skipped : list[Path]             = []

    for p in sorted(inbox.glob("*.epub")):
        try:
            h = sha256_file(p)
        except OSError as e:
            logger.warning("[EpubInbox] cannot hash %s: %s", p.name, e)
            continue
        if h in manifest:
            skipped.append(p)
        else:
            todo.append((p, h))

    return todo, skipped


__all__ = [
    "INBOX_DIR", "MANIFEST_FILE",
    "ensure_inbox", "sha256_file",
    "load_manifest", "save_manifest", "mark_processed",
    "scan_inbox",
]
