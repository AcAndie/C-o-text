"""web.py — Tải ảnh qua HTTP sử dụng DomainSessionPool."""
from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Any

from cao_text.images.base import ImageFetchStrategy, detect_image_extension
from cao_text.models import ImageRef

logger = logging.getLogger(__name__)

MAX_IMAGE_SIZE: int = 5 * 1024 * 1024  # 5MB trần an toàn
IMAGE_FETCH_CONCURRENCY: int = 5


class WebImageFetcher(ImageFetchStrategy):
    """Chiến lược tải ảnh trực tiếp từ Web qua DomainSessionPool."""

    def __init__(self, pool: Any, chapter_index: int) -> None:
        self.pool = pool
        self.chapter_index = chapter_index
        self._last_ct: dict[str, str | None] = {}

    async def fetch(self, ref: ImageRef) -> bytes | None:
        """Tải dữ liệu ảnh từ URL gốc."""
        try:
            status, data, ct = await self.pool.fetch_bytes(ref.original_url, timeout=30)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning("[WebImageFetcher] fetch failed %s: %s", ref.original_url, e)
            return None

        if status != 200:
            logger.debug("[WebImageFetcher] HTTP %d for %s", status, ref.original_url)
            return None

        if len(data) > MAX_IMAGE_SIZE:
            logger.warning(
                "[WebImageFetcher] oversize %d bytes (>%d) — skip %s",
                len(data),
                MAX_IMAGE_SIZE,
                ref.original_url,
            )
            return None

        self._last_ct[ref.original_url] = ct
        return data

    async def fetch_batch(
        self, refs: list[ImageRef], output_dir: str | Path
    ) -> list[ImageRef]:
        """Tải đồng thời danh sách ảnh với semaphore giới hạn kết nối."""
        out = Path(output_dir)
        images_dir = out / "images"
        images_dir.mkdir(parents=True, exist_ok=True)
        sem = asyncio.Semaphore(IMAGE_FETCH_CONCURRENCY)

        async def _one(idx: int, ref: ImageRef) -> None:
            async with sem:
                try:
                    data = await self.fetch(ref)
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    logger.warning("[WebImageFetcher] _one failed: %s", e)
                    ref.local_path = None
                    return

                if data is None:
                    ref.local_path = None
                    return

                ref.local_path = self._save(idx, ref, data, out)

        await asyncio.gather(*(_one(i, r) for i, r in enumerate(refs)))
        return refs

    def _save(
        self, idx: int, ref: ImageRef, data: bytes, output_dir: Path
    ) -> str | None:
        """Ghi atomic dữ liệu ảnh vào output_dir/images/ch_NNNN_idx.ext."""
        ct = self._last_ct.get(ref.original_url)
        ext = detect_image_extension(ct, data[:16])
        filename = f"ch_{self.chapter_index:04d}_{idx}{ext}"
        rel_path = f"images/{filename}"
        abs_path = output_dir / "images" / filename
        tmp_path = abs_path.with_suffix(abs_path.suffix + ".tmp")

        try:
            tmp_path.write_bytes(data)
            os.replace(tmp_path, abs_path)
        except Exception as e:
            logger.warning("[WebImageFetcher] save failed %s: %s", abs_path, e)
            if tmp_path.exists():
                try:
                    tmp_path.unlink()
                except OSError:
                    pass
            return None

        return rel_path
