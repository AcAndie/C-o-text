"""
writers/base.py — ChapterWriter ABC (P1.3, BLUEPRINT §5).

Contract: pipeline produce CleanedChapter DTO → writer consume → ghi file.
Mode-specific logic (frontmatter, image embed, plain text format) gói trong
concrete subclass (P1.4 ObsidianWriter, P4 TranslationWriter/RawWriter).
"""
from __future__ import annotations

import asyncio
import os
from abc import ABC, abstractmethod
from pathlib import Path

from pipeline.base import CleanedChapter
from utils.types  import RunConfig


class ChapterWriter(ABC):
    """
    Abstract writer. Concrete subclass implement filename + write logic
    cho 1 output mode cụ thể (obsidian / translate / raw).

    P1.5: _atomic_write_text giờ async + chạy trong thread + cancel handler
    cleanup .tmp file. Subclass phải `await self._atomic_write_text(...)`.
    """

    def __init__(self, output_dir: str, run_config: RunConfig) -> None:
        self.output_dir = output_dir
        self.run_config = run_config

    @abstractmethod
    async def write(self, chapter: CleanedChapter) -> Path:
        """Write CleanedChapter ra file. Return absolute path đã ghi."""

    @abstractmethod
    def filename_for(self, chapter: CleanedChapter) -> str:
        """Filename cho chapter (relative tới output_dir, không bao gồm dir)."""

    # ── Shared helpers ────────────────────────────────────────────────────────

    def _ensure_dir(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)

    async def _atomic_write_text(self, path: Path, content: str) -> None:
        """
        Atomic write qua .tmp + os.replace, run trong thread (file I/O ra
        khỏi event loop). Encoding utf-8 explicit.

        Cancel mid-write → cleanup .tmp file rồi re-raise CancelledError.
        """
        self._ensure_dir(path)
        tmp = path.with_suffix(path.suffix + ".tmp")
        try:
            await asyncio.to_thread(self._sync_atomic_write, path, tmp, content)
        except asyncio.CancelledError:
            if tmp.exists():
                try:
                    tmp.unlink()
                except Exception:
                    pass
            raise

    @staticmethod
    def _sync_atomic_write(path: Path, tmp: Path, content: str) -> None:
        tmp.write_text(content, encoding="utf-8")
        os.replace(tmp, path)
