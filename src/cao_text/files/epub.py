"""epub.py — Đọc file EPUB theo kế hoạch thành luồng tài liệu thô (RawDocument)."""
from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ebooklib import epub

from cao_text.models import RawDocument

if TYPE_CHECKING:
    from cao_text.ai.provider import LLMProvider

logger = logging.getLogger(__name__)


def extract_story_name_from_epub(path: str | Path) -> str:
    """Đọc tiêu đề truyện từ Dublin Core metadata của file EPUB (§6.6)."""
    try:
        book = epub.read_epub(str(path))
        meta = book.get_metadata("DC", "title")
        if meta and meta[0] and meta[0][0]:
            name = str(meta[0][0]).strip()
            if name:
                return name
    except Exception as e:
        logger.debug("[EPUB] Không thể đọc DC:title từ %s: %s", path, e)
    return Path(path).stem


async def read_epub_documents(
    path: str | Path,
    plan: list[Any] | None = None,
    ai_provider: LLMProvider | None = None,
) -> AsyncIterator[RawDocument]:
    """Đọc các chương từ file EPUB thành luồng RawDocument."""
    from ingest.epub import ingest_epub

    async for doc in ingest_epub(str(path), plan=plan, ai_limiter=None):
        yield RawDocument(
            chapter_index=doc.chapter_index,
            html=doc.html,
            source_url=doc.source_url,
            source_path=doc.source_path,
            metadata=dict(doc.metadata or {}),
        )


__all__ = [
    "RawDocument",
    "extract_story_name_from_epub",
    "read_epub_documents",
]
