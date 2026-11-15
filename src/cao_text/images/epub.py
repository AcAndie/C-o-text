"""epub.py — Trích xuất ảnh trực tiếp từ file nén EPUB in-memory."""
from __future__ import annotations

import asyncio
import logging
import os
import posixpath
from pathlib import Path
from typing import Any

import ebooklib
from ebooklib import epub

from cao_text.images.base import ImageFetchStrategy, detect_image_extension
from cao_text.models import ImageRef

logger = logging.getLogger(__name__)


class EpubImageExtractor(ImageFetchStrategy):
    """Chiến lược trích xuất ảnh từ đối tượng EpubBook đã mở."""

    def __init__(self, book: epub.EpubBook | Any, chapter_index: int) -> None:
        self.book = book
        self.chapter_index = chapter_index

    async def fetch(self, ref: ImageRef) -> bytes | None:
        """Định vị và đọc dữ liệu ảnh từ EPUB qua 4 chiến lược giải quyết href và fallback basename."""
        href = ref.original_url
        item = self.book.get_item_with_href(href)

        # 2 & 3. Thử các biến thể tiền tố OEBPS/OPS và chuẩn hóa đường dẫn
        if item is None:
            for variant in (
                href.lstrip("/"),
                "OEBPS/" + href,
                "OEBPS/" + href.lstrip("/"),
                "OPS/" + href,
                "OPS/" + href.lstrip("/"),
                posixpath.normpath(href),
                posixpath.normpath("OPS/" + href.lstrip("/")),
                posixpath.normpath("OEBPS/" + href.lstrip("/")),
            ):
                item = self.book.get_item_with_href(variant)
                if item:
                    break

        # 4. Basename fallback: quét toàn bộ ITEM_IMAGE trong sách để tìm file trùng tên
        if item is None:
            target = posixpath.basename(href)
            if target:
                for it in self.book.get_items_of_type(ebooklib.ITEM_IMAGE):
                    if posixpath.basename(it.get_name()) == target:
                        item = it
                        break

        if item is None:
            logger.warning("[EpubImageExtractor] href not found: %s", href)
            return None

        try:
            return item.get_content()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning("[EpubImageExtractor] get_content failed %s: %s", href, e)
            return None

    async def fetch_batch(
        self, refs: list[ImageRef], output_dir: str | Path
    ) -> list[ImageRef]:
        """Trích xuất tuần tự các ảnh của chương từ file EPUB."""
        out = Path(output_dir)
        images_dir = out / "images"
        images_dir.mkdir(parents=True, exist_ok=True)

        for idx, ref in enumerate(refs):
            try:
                data = await self.fetch(ref)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.warning(
                    "[EpubImageExtractor] fetch raised for %s: %s",
                    ref.original_url,
                    e,
                )
                ref.local_path = None
                continue

            if not data:
                ref.local_path = None
                continue

            ref.local_path = self._save(idx, ref, data, out)

        return refs

    def _save(
        self, idx: int, ref: ImageRef, data: bytes, output_dir: Path
    ) -> str | None:
        """Ghi atomic dữ liệu ảnh vào output_dir/images/ch_NNNN_idx.ext."""
        ext = detect_image_extension(None, data[:16])
        filename = f"ch_{self.chapter_index:04d}_{idx}{ext}"
        rel_path = f"images/{filename}"
        abs_path = output_dir / "images" / filename
        tmp_path = abs_path.with_suffix(abs_path.suffix + ".tmp")

        try:
            tmp_path.write_bytes(data)
            os.replace(tmp_path, abs_path)
        except Exception as e:
            logger.warning("[EpubImageExtractor] save failed %s: %s", abs_path, e)
            if tmp_path.exists():
                try:
                    tmp_path.unlink()
                except OSError:
                    pass
            return None

        return rel_path
