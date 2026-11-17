"""txt.py — Đọc file TXT theo mẫu nhận diện thành luồng tài liệu thô (RawDocument)."""
from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from pathlib import Path
from typing import TYPE_CHECKING

from cao_text.models import RawDocument

if TYPE_CHECKING:
    from cao_text.ai.provider import LLMProvider

logger = logging.getLogger(__name__)


def extract_story_name_from_txt(path: str | Path) -> str:
    """Đọc tiêu đề truyện từ tên file TXT (§6.6)."""
    return Path(path).stem


async def read_txt_documents(
    path: str | Path,
    pattern: str | None = None,
    ai_provider: LLMProvider | None = None,
) -> AsyncIterator[RawDocument]:
    """Đọc các chương từ file TXT thành luồng RawDocument."""
    from ingest.txt import ingest_txt

    async for doc in ingest_txt(str(path), ai_limiter=None):
        yield RawDocument(
            chapter_index=doc.chapter_index,
            html=doc.html,
            source_url=doc.source_url,
            source_path=doc.source_path,
            metadata=dict(doc.metadata or {}),
        )


__all__ = [
    "RawDocument",
    "extract_story_name_from_txt",
    "read_txt_documents",
]
