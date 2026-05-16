"""
core/image_pipeline/base.py — ImageFetchStrategy ABC (P2.2).

Contract chung cho web HTTP fetch (WebImageFetcher) và EPUB zip extract
(EpubImageExtractor — P3.5). Pipeline image stage gọi strategy.fetch_batch(),
không quan tâm source.

Failure policy:
- 1 image fail (404/timeout/oversize) → ref.local_path = None, log warning,
  continue batch
- Toàn batch fail → return list với mọi ref.local_path = None — writer
  vẫn xuất chapter, frontmatter `failed_images` list URL
"""
from __future__ import annotations

import logging
import os
from abc import ABC, abstractmethod

from pipeline.base import ImageRef

logger = logging.getLogger(__name__)


class ImageFetchStrategy(ABC):
    """
    Abstract strategy. Subclass implement fetch() — bytes loader cho 1 ref.
    fetch_batch() default sequential; subclass override cho concurrent
    (vd WebImageFetcher dùng asyncio.gather + semaphore).
    """

    @abstractmethod
    async def fetch(self, ref: ImageRef) -> bytes | None:
        """
        Fetch image bytes cho 1 ref. Return None on failure (404, timeout,
        oversize, network error). Không raise — caller batch không break.
        """

    async def fetch_batch(
        self, refs: list[ImageRef], output_dir: str,
    ) -> list[ImageRef]:
        """
        Default sequential. Populate ref.local_path. Subclass nên override
        để concurrent (gather + semaphore).
        """
        os.makedirs(os.path.join(output_dir, "images"), exist_ok=True)
        for idx, ref in enumerate(refs):
            try:
                data = await self.fetch(ref)
                if data:
                    ref.local_path = self._save(idx, ref, data, output_dir)
                else:
                    ref.local_path = None
            except Exception as e:
                logger.warning(
                    "[ImageFetch] failed: %s — %s", ref.original_url, e,
                )
                ref.local_path = None
        return refs

    def _save(self, idx: int, ref: ImageRef, data: bytes, output_dir: str) -> str | None:
        """
        Default no-op. Subclass tự implement save logic vì naming convention
        + extension detection khác giữa web (Content-Type) và epub (media_type).
        """
        return None
