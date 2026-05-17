"""
ingest/types.py — shared DTO for input adapters.

`RawDocument` is the common contract between every input adapter
(`ingest/epub.py`, `ingest/txt.py`, future web adapter) and the
pipeline core. Pipeline core does not know the source — it only sees
`chapter_index` + `html`.

Moved here in Phase 6 cleanup. Was originally co-located with
`ingest/epub.py` (the first adapter) but now shared.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class RawDocument:
    """
    Common contract giữa input adapter và pipeline core.

    `source_url` cho web, `source_path` cho epub/txt.
    `metadata` carry naming hint (story_name từ DC, language, txt_case, ...)
    qua orchestrator về writer.
    """
    chapter_index: int
    html         : str
    source_url   : str | None       = None
    source_path  : str | None       = None
    metadata     : dict             = field(default_factory=dict)


__all__ = ["RawDocument"]
