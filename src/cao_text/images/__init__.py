"""cao_text.images — Quản lý và xử lý tải hình ảnh minh họa cho tiểu thuyết."""
from __future__ import annotations

from cao_text.images.base import ImageFetchStrategy, detect_image_extension
from cao_text.images.epub import EpubImageExtractor
from cao_text.images.stage import apply_image_stage
from cao_text.images.web import WebImageFetcher

__all__ = [
    "EpubImageExtractor",
    "ImageFetchStrategy",
    "WebImageFetcher",
    "apply_image_stage",
    "detect_image_extension",
]
