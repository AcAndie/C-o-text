"""epub.py — Đọc file EPUB theo kế hoạch thành luồng tài liệu thô (RawDocument)."""
from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from pathlib import Path
from typing import TYPE_CHECKING, Any

from bs4 import BeautifulSoup
from ebooklib import epub

from cao_text.files.epub_plan import ChapterPlan, build_chapter_plan
from cao_text.models import RawDocument

if TYPE_CHECKING:
    from cao_text.ai.provider import LLMProvider

logger = logging.getLogger(__name__)

_NO_TOC_MIN_CHAPTERS = 5


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


def _extract_doc_text(book: epub.EpubBook, doc_ids: list[str]) -> str:
    """Trích xuất plain text từ các spine docs để phục vụ pattern split cho sách không có TOC."""
    parts: list[str] = []
    for doc_id in doc_ids:
        item = book.get_item_with_id(doc_id)
        if item is None:
            continue
        try:
            raw = item.get_content().decode("utf-8", errors="replace")
        except Exception:
            continue
        soup = BeautifulSoup(raw, "html.parser")
        body = soup.find("body") or soup
        text = body.get_text(separator="\n", strip=True)
        if text:
            parts.append(text)
    return "\n\n".join(parts)


async def _try_no_toc_split(
    body_text: str,
    ai_provider: LLMProvider | None = None,
) -> list[tuple[int, str, str]] | None:
    """Tách chương tự động cho sách EPUB không có mục lục (No-TOC fallback theo §6.6)."""
    from ingest.txt import detect_pattern_regex, split_into_chapters

    case = detect_pattern_regex(body_text)
    if case is None and ai_provider is not None:
        try:
            from ingest.txt import detect_pattern
            case = await detect_pattern(body_text, ai_limiter=None)
        except Exception as e:
            logger.warning("[EPUB no-TOC] AI pattern detect failed: %s", e)
            return None

    if case is None:
        return None

    chapters = split_into_chapters(body_text, case)
    if len(chapters) < _NO_TOC_MIN_CHAPTERS:
        logger.debug(
            "[EPUB no-TOC] Chỉ tìm thấy %d chương (ngưỡng tối thiểu %d)",
            len(chapters),
            _NO_TOC_MIN_CHAPTERS,
        )
        return None
    return chapters


async def read_epub_documents(
    path: str | Path,
    plan: list[ChapterPlan] | list[Any] | None = None,
    ai_provider: LLMProvider | None = None,
) -> AsyncIterator[RawDocument]:
    """Đọc các chương từ file EPUB thành luồng RawDocument theo kế hoạch đã lập."""
    book = epub.read_epub(str(path))
    story_name = extract_story_name_from_epub(path)
    source_path = str(Path(path).resolve())
    base_meta: dict[str, Any] = {"story_name": story_name}

    if plan is None:
        plan = await build_chapter_plan(book, path, ai_provider=ai_provider)

    # Xử lý No-TOC fallback: nếu plan chỉ có 1 matter_bucket và 0 chapter thực
    real_count = sum(1 for p in plan if getattr(p, "kind", "") == "chapter")
    if real_count == 0 and plan and getattr(plan[0], "kind", "") == "matter":
        matter_ids = getattr(plan[0], "doc_ids", [])
        body_text = _extract_doc_text(book, matter_ids)
        if body_text and len(body_text) > 1000:
            split_chapters = await _try_no_toc_split(body_text, ai_provider)
            if split_chapters:
                logger.info(
                    "  [EPUB] 📖 No-TOC EPUB → pattern-split %d chapters",
                    len(split_chapters),
                )
                from ingest.txt import _build_chapter_html
                for idx, title, body in split_chapters:
                    meta = dict(base_meta)
                    meta["kind"] = "chapter"
                    meta["toc_title"] = title
                    yield RawDocument(
                        chapter_index=idx,
                        html=_build_chapter_html(title, body),
                        source_path=source_path,
                        metadata=meta,
                    )
                return

    # Duyệt theo từng đơn vị trong kế hoạch (ChapterPlan)
    for entry in plan:
        body_chunks: list[str] = []
        doc_ids = getattr(entry, "doc_ids", [])
        for doc_id in doc_ids:
            item = book.get_item_with_id(doc_id)
            if item is None:
                continue
            try:
                raw = item.get_content().decode("utf-8", errors="replace")
            except Exception:
                continue

            doc_soup = BeautifulSoup(raw, "html.parser")
            doc_body = doc_soup.find("body")
            if doc_body is not None:
                inner = "".join(str(c) for c in doc_body.children)
            else:
                inner = raw
            if inner.strip():
                body_chunks.append(inner)

        if not body_chunks:
            continue

        if len(body_chunks) > 1:
            merged_body = "\n<hr/>\n".join(body_chunks)
        else:
            merged_body = body_chunks[0]

        merged_html = f"<html><body>{merged_body}</body></html>"

        meta = dict(base_meta)
        meta["kind"] = getattr(entry, "kind", "chapter")
        title = getattr(entry, "title", None)
        if title:
            meta["toc_title"] = title

        yield RawDocument(
            chapter_index=getattr(entry, "index", 0),
            html=merged_html,
            source_path=source_path,
            metadata=meta,
        )


__all__ = [
    "RawDocument",
    "extract_story_name_from_epub",
    "read_epub_documents",
]
