"""
utils/file_io.py — Async file I/O helpers.

Public API:
    load_profiles()                       → dict[str, SiteProfile]
    save_profiles(profiles)               → None
    load_progress(path)                   → ProgressDict
    save_progress(path, progress)         → None
    write_markdown(path, content)         → None
    ensure_dirs()                         → None
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path

from config import PROFILES_FILE, DATA_DIR, OUTPUT_DIR, PROGRESS_DIR
from utils.types import ProgressDict, SiteProfile

logger = logging.getLogger(__name__)

_WRITE_LOCK: dict[str, asyncio.Lock] = {}


def _get_lock(path: str) -> asyncio.Lock:
    if path not in _WRITE_LOCK:
        _WRITE_LOCK[path] = asyncio.Lock()
    return _WRITE_LOCK[path]


# ── Profiles ──────────────────────────────────────────────────────────────────

async def load_profiles() -> dict[str, SiteProfile]:
    """Load site_profiles.json. Returns {} nếu file không tồn tại."""
    try:
        if not os.path.exists(PROFILES_FILE):
            return {}
        content = await asyncio.to_thread(_read_file, PROFILES_FILE)
        data    = json.loads(content)
        if isinstance(data, dict):
            return data  # type: ignore[return-value]
        return {}
    except Exception as e:
        logger.warning("[FileIO] load_profiles failed: %s", e)
        return {}


async def save_profiles(profiles: dict) -> None:
    """Save profiles dict xuống disk (atomic write)."""
    async with _get_lock(PROFILES_FILE):
        await asyncio.to_thread(_atomic_write, PROFILES_FILE, json.dumps(profiles, ensure_ascii=False, indent=2))


# ── Progress ──────────────────────────────────────────────────────────────────

async def load_progress(path: str) -> ProgressDict:
    """Load progress JSON. Returns empty ProgressDict nếu file không tồn tại."""
    try:
        if not os.path.exists(path):
            return {}  # type: ignore[return-value]
        content = await asyncio.to_thread(_read_file, path)
        data    = json.loads(content)
        return data if isinstance(data, dict) else {}  # type: ignore[return-value]
    except Exception as e:
        logger.warning("[FileIO] load_progress failed for %s: %s", path, e)
        return {}  # type: ignore[return-value]


async def save_progress(path: str, progress: dict) -> None:
    """Save progress dict xuống disk."""
    async with _get_lock(path):
        await asyncio.to_thread(_atomic_write, path, json.dumps(progress, ensure_ascii=False, indent=2))


# ── Markdown output ───────────────────────────────────────────────────────────

async def write_markdown(path: str, content: str) -> None:
    """Write chapter content ra file .md."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    async with _get_lock(path):
        await asyncio.to_thread(_write_file, path, content)


# ── Dirs ──────────────────────────────────────────────────────────────────────

def ensure_dirs() -> None:
    """Tạo tất cả thư mục cần thiết."""
    for d in (DATA_DIR, OUTPUT_DIR, PROGRESS_DIR):
        os.makedirs(d, exist_ok=True)


# ── Sync helpers ──────────────────────────────────────────────────────────────

def _read_file(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _write_file(path: str, content: str) -> None:
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(content)


def _atomic_write(path: str, content: str) -> None:
    """Write qua temp file để đảm bảo atomicity."""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            f.write(content)
        os.replace(tmp, path)
    except Exception:
        # Fallback: direct write
        _write_file(path, content)
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except Exception:
                pass