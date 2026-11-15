"""stage.py — Hàm apply_image_stage hợp nhất dùng chung cho cả Web và EPUB."""
from __future__ import annotations

import asyncio
import logging
import re
from pathlib import Path

from cao_text.images.base import ImageFetchStrategy
from cao_text.models import ImageRef, RunConfig

logger = logging.getLogger(__name__)

_IMG_PLACEHOLDER_RE = re.compile(r"!\[[^\]]*\]\(IMG_PLACEHOLDER_\d+\)")


async def apply_image_stage(
    content: str,
    image_refs: list[ImageRef],
    strategy: ImageFetchStrategy | None,
    run_config: RunConfig,
    out_dir: str | Path,
    chapter_num: int,
) -> str:
    """Xử lý hình ảnh tương ứng theo chế độ output_mode trong run_config.

    Chế độ:
      - obsidian (download_images=True):
          Gọi strategy.fetch_batch() để tải và lưu ảnh vào output_dir/images/.
          Thay thế placeholder bằng `![alt](local_path)`.
          Nếu tải lỗi: fallback giữ link gốc `![alt](original_url)` (để link không hỏng,
          đồng thời ObsidianWriter sẽ ghi URL lỗi vào frontmatter `failed_images`).
      - translate (image_placeholder=True):
          Thay thế `![alt](IMG_PLACEHOLDER_N)` thành `[IMAGE: alt]`. Không tải ảnh.
      - raw:
          Xóa bỏ hoàn toàn các thẻ placeholder ảnh.
    """
    if not image_refs:
        return content

    if run_config.download_images:
        # Chế độ Obsidian: Tải ảnh và ghi đè đường dẫn local
        if strategy is not None:
            try:
                await strategy.fetch_batch(image_refs, out_dir)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.warning(
                    "[ImageStage] fetch_batch failed ch.%d: %s", chapter_num, e
                )

        for ref in image_refs:
            old = f"![{ref.alt_text}]({ref.position_marker})"
            target = ref.local_path or ref.original_url  # Giữ link gốc nếu tải thất bại
            new = f"![{ref.alt_text}]({target})"
            content = content.replace(old, new, 1)

    elif run_config.image_placeholder:
        # Chế độ dịch: Giữ placeholder dạng [IMAGE: alt]
        for ref in image_refs:
            old = f"![{ref.alt_text}]({ref.position_marker})"
            new = f"[IMAGE: {ref.alt_text}]"
            content = content.replace(old, new, 1)

    else:
        # Chế độ raw: Xóa sạch toàn bộ ảnh
        content = _IMG_PLACEHOLDER_RE.sub("", content)

    return content


__all__ = ["apply_image_stage"]
