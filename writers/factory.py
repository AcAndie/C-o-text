"""
writers/factory.py — Writer factory dispatch (P4.3).

Single entry point cho callers (scraper, orchestrator) build writer
theo `RunConfig.output_mode`. Tránh hardcode `ObsidianWriter` ở mỗi
call site.
"""
from __future__ import annotations

from utils.types          import RunConfig
from writers.base         import ChapterWriter
from writers.obsidian     import ObsidianWriter
from writers.raw          import RawWriter
from writers.translation  import TranslationWriter


_WRITER_REGISTRY: dict[str, type[ChapterWriter]] = {
    "obsidian" : ObsidianWriter,
    "translate": TranslationWriter,
    "raw"      : RawWriter,
}


def build_writer(output_dir: str, run_config: RunConfig) -> ChapterWriter:
    """
    Dispatch theo `run_config.output_mode`. Raise ValueError nếu mode
    unknown — fail loud, không silent fallback (CLAUDE §11).
    """
    cls = _WRITER_REGISTRY.get(run_config.output_mode)
    if cls is None:
        raise ValueError(
            f"Unknown output_mode {run_config.output_mode!r}. "
            f"Valid: {sorted(_WRITER_REGISTRY.keys())}"
        )
    return cls(output_dir, run_config)


__all__ = ["build_writer"]
