"""
core/image_pipeline/web_fetcher.py — WebImageFetcher (P2.2).

HTTP image fetch via DomainSessionPool.fetch_bytes (curl_cffi). Reuse
session để giữ TLS fingerprint + cookie consistent với chapter fetch.

Concurrent fetch_batch (asyncio.gather + semaphore IMAGE_FETCH_CONCURRENCY).
Atomic write via .tmp + os.replace. Extension detect từ Content-Type + magic
bytes fallback.

Failure modes:
- HTTP non-200 → None
- Content size > MAX_IMAGE_SIZE → None (skip oversize, log warning)
- Network error → None (log warning)
- All silent → caller sees local_path = None, writer logs failed_images
"""
from __future__ import annotations

import asyncio
import logging
import os

from pipeline.base import ImageRef
from core.image_pipeline.base import ImageFetchStrategy
from core.session_pool import DomainSessionPool
from utils.image_url import detect_image_extension

logger = logging.getLogger(__name__)

MAX_IMAGE_SIZE          = 5 * 1024 * 1024   # 5MB
IMAGE_FETCH_CONCURRENCY = 5


class WebImageFetcher(ImageFetchStrategy):
    """
    HTTP fetcher via DomainSessionPool. chapter_index dùng cho filename
    naming: `ch_NNNN_idx.ext`.
    """

    def __init__(self, pool: DomainSessionPool, chapter_index: int) -> None:
        self.pool          = pool
        self.chapter_index = chapter_index
        # Cache Content-Type per fetch (set trong fetch(), read trong _save)
        self._last_ct: dict[str, str | None] = {}

    async def fetch(self, ref: ImageRef) -> bytes | None:
        """
        Fetch bytes. Return None nếu fail, oversize, hoặc non-200.
        Content-Type cache vào self._last_ct[url] cho _save() dùng.
        """
        try:
            status, data, ct = await self.pool.fetch_bytes(ref.original_url, timeout=30)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning("[WebImageFetcher] %s — %s", ref.original_url, e)
            return None

        if status != 200:
            logger.debug("[WebImageFetcher] HTTP %d for %s", status, ref.original_url)
            return None
        if len(data) > MAX_IMAGE_SIZE:
            logger.warning(
                "[WebImageFetcher] oversize %d bytes (>%d) — skip %s",
                len(data), MAX_IMAGE_SIZE, ref.original_url,
            )
            return None

        self._last_ct[ref.original_url] = ct
        return data

    async def fetch_batch(
        self, refs: list[ImageRef], output_dir: str,
    ) -> list[ImageRef]:
        """
        Concurrent fetch_batch với semaphore. Save vào {output_dir}/images/.
        Populate ref.local_path relative path (vd "images/ch_0042_0.jpg")
        để writer link vào Markdown.
        """
        images_dir = os.path.join(output_dir, "images")
        os.makedirs(images_dir, exist_ok=True)
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

                ref.local_path = self._save(idx, ref, data, output_dir)

        await asyncio.gather(*(_one(i, r) for i, r in enumerate(refs)))
        return refs

    def _save(
        self, idx: int, ref: ImageRef, data: bytes, output_dir: str,
    ) -> str | None:
        """
        Atomic write: data → {output_dir}/images/ch_NNNN_idx.ext.
        Extension từ Content-Type (cached) hoặc magic bytes fallback.
        Return relative path "images/filename" cho Markdown link.
        """
        ct       = self._last_ct.get(ref.original_url)
        ext      = detect_image_extension(ct, data[:16])
        filename = f"ch_{self.chapter_index:04d}_{idx}{ext}"
        rel_path = f"images/{filename}"
        abs_path = os.path.join(output_dir, "images", filename)
        tmp      = abs_path + ".tmp"

        try:
            with open(tmp, "wb") as f:
                f.write(data)
            os.replace(tmp, abs_path)
        except Exception as e:
            logger.warning("[WebImageFetcher] save failed: %s — %s", abs_path, e)
            if os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except Exception:
                    pass
            return None

        return rel_path
