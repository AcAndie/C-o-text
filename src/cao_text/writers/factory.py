"""factory.py — Điều phối khởi tạo ChapterWriter theo RunConfig.output_mode."""
from __future__ import annotations

from pathlib import Path

from cao_text.models import RunConfig
from cao_text.writers.base import ChapterWriter
from cao_text.writers.obsidian import ObsidianWriter
from cao_text.writers.raw import RawWriter
from cao_text.writers.translation import TranslationWriter

_WRITER_REGISTRY: dict[str, type[ChapterWriter]] = {
    "obsidian": ObsidianWriter,
    "translate": TranslationWriter,
    "raw": RawWriter,
}


def build_writer(output_dir: str | Path, run_config: RunConfig) -> ChapterWriter:
    """Khởi tạo writer tương ứng với run_config.output_mode.

    Ném ra ValueError nếu output_mode không hợp lệ.
    """
    cls = _WRITER_REGISTRY.get(run_config.output_mode)
    if cls is None:
        valid_modes = sorted(_WRITER_REGISTRY.keys())
        raise ValueError(
            f"Unknown output_mode {run_config.output_mode!r}. "
            f"Valid options: {valid_modes}"
        )
    return cls(output_dir, run_config)


__all__ = ["build_writer"]
