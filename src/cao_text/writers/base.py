"""base.py — Lớp cơ sở trừu tượng ChapterWriter cho các định dạng xuất bản.

Hợp đồng:
  - Input: CleanedChapter DTO từ pipeline trích xuất.
  - Output: Ghi file ra output_dir theo định dạng tương ứng (obsidian / translate / raw).
  - Ghi file an toàn bằng cơ chế atomic write (chạy bất đồng bộ, dọn file .tmp khi bị cancel).
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from cao_text.models import CleanedChapter, RunConfig
from cao_text.storage import async_atomic_write_text


class ChapterWriter(ABC):
    """Lớp trừu tượng cho các bộ ghi chương."""

    def __init__(self, output_dir: str | Path, run_config: RunConfig) -> None:
        self.output_dir = Path(output_dir)
        self.run_config = run_config

    @abstractmethod
    async def write(self, chapter: CleanedChapter) -> Path:
        """Ghi CleanedChapter ra đĩa và trả về đường dẫn Path tuyệt đối của file đã ghi."""

    @abstractmethod
    def filename_for(self, chapter: CleanedChapter) -> str:
        """Tên file của chương (tương đối so với output_dir, không gồm thư mục)."""

    async def _write_atomic(self, path: Path, content: str) -> None:
        """Ghi nội dung text an toàn bằng atomic write."""
        await async_atomic_write_text(path, content)
