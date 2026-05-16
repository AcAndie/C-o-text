"""
core/image_pipeline/epub_extractor.py — EpubImageExtractor (P3.5).

Read image binary trực tiếp từ EPUB zip in-memory. KHÔNG HTTP — `book`
object là `epub.EpubBook` đã `read_epub()` rồi.

Decision #19 (BLUEPRINT §6 "Image fetch strategy"):
  WebImageFetcher = HTTP via curl_cffi.
  EpubImageExtractor = binary từ zip.
  Cùng interface ImageFetchStrategy → pipeline image stage không quan tâm
  source type.

Href resolution:
  EPUB <img src="..."> dùng path relative tới chapter XHTML location.
  `book.get_item_with_href()` tìm theo manifest href — có thể không match
  nếu chapter ở subfolder. Fallback: thử strip leading "/" + try OEBPS prefix
  (convention phổ biến).

Sequential fetch_batch — local zip read, không cần concurrency.
"""
from __future__ import annotations

import logging
import os

from ebooklib import epub

from core.image_pipeline.base import ImageFetchStrategy
from pipeline.base import ImageRef
from utils.image_url import detect_image_extension

logger = logging.getLogger(__name__)


class EpubImageExtractor(ImageFetchStrategy):
    """
    Extract image bytes từ EPUB zip via ebooklib.
    `chapter_index` dùng cho filename naming: `ch_NNNN_idx.ext`.
    """

    def __init__(self, book: epub.EpubBook, chapter_index: int) -> None:
        self.book          = book
        self.chapter_index = chapter_index

    async def fetch(self, ref: ImageRef) -> bytes | None:
        """
        Resolve href → EpubItem → get_content() bytes.
        Try multiple href variants vì EPUB chapter có thể reference image
        bằng relative path khác cách manifest stores.
        """
        href = ref.original_url
        item = self.book.get_item_with_href(href)

        if item is None:
            for variant in (
                href.lstrip("/"),
                "OEBPS/" + href,
                "OEBPS/" + href.lstrip("/"),
            ):
                item = self.book.get_item_with_href(variant)
                if item:
                    break

        if item is None:
            logger.warning("[EpubImageExtractor] href not found: %s", href)
            return None

        try:
            return item.get_content()
        except Exception as e:
            logger.warning("[EpubImageExtractor] get_content failed: %s — %s", href, e)
            return None

    async def fetch_batch(
        self, refs: list[ImageRef], output_dir: str,
    ) -> list[ImageRef]:
        """
        Sequential — local zip read, no benefit from concurrency.
        Populate ref.local_path relative path ("images/ch_NNNN_idx.ext").
        """
        images_dir = os.path.join(output_dir, "images")
        os.makedirs(images_dir, exist_ok=True)

        for idx, ref in enumerate(refs):
            try:
                data = await self.fetch(ref)
            except Exception as e:
                logger.warning("[EpubImageExtractor] fetch raised: %s — %s",
                               ref.original_url, e)
                ref.local_path = None
                continue

            if not data:
                ref.local_path = None
                continue

            ref.local_path = self._save(idx, ref, data, output_dir)

        return refs

    def _save(
        self, idx: int, ref: ImageRef, data: bytes, output_dir: str,
    ) -> str | None:
        """
        Atomic write: data → {output_dir}/images/ch_NNNN_idx.ext.
        EPUB không có Content-Type header — chỉ dùng magic bytes detect.
        """
        ext      = detect_image_extension(None, data[:16])
        filename = f"ch_{self.chapter_index:04d}_{idx}{ext}"
        rel_path = f"images/{filename}"
        abs_path = os.path.join(output_dir, "images", filename)
        tmp      = abs_path + ".tmp"

        try:
            with open(tmp, "wb") as f:
                f.write(data)
            os.replace(tmp, abs_path)
        except Exception as e:
            logger.warning("[EpubImageExtractor] save failed: %s — %s", abs_path, e)
            if os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except Exception:
                    pass
            return None

        return rel_path


__all__ = ["EpubImageExtractor"]
