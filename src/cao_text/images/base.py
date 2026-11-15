"""base.py — Lớp cơ sở ImageFetchStrategy và nhận diện phần mở rộng ảnh."""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from pathlib import Path

from cao_text.models import ImageRef

logger = logging.getLogger(__name__)

# Bảng ánh xạ Content-Type sang đuôi mở rộng file
_CT_TO_EXT: dict[str, str] = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
    "image/svg+xml": ".svg",
}


def detect_image_extension(content_type: str | None, magic_bytes: bytes) -> str:
    """Xác định đuôi file ảnh (.jpg, .png, .webp, .gif) từ Content-Type hoặc magic bytes."""
    if content_type:
        ct = content_type.lower().split(";")[0].strip()
        if ct in _CT_TO_EXT:
            return _CT_TO_EXT[ct]

    if magic_bytes.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if magic_bytes.startswith(b"\x89PNG"):
        return ".png"
    if magic_bytes.startswith(b"RIFF") and b"WEBP" in magic_bytes[:16]:
        return ".webp"
    if magic_bytes.startswith((b"GIF87a", b"GIF89a")):
        return ".gif"

    return ".jpg"


class ImageFetchStrategy(ABC):
    """Chiến lược nạp dữ liệu ảnh (từ web hoặc từ file nén EPUB)."""

    @abstractmethod
    async def fetch(self, ref: ImageRef) -> bytes | None:
        """Nạp dữ liệu nhị phân của một ảnh. Trả về None nếu gặp lỗi."""

    @abstractmethod
    async def fetch_batch(
        self, refs: list[ImageRef], output_dir: str | Path
    ) -> list[ImageRef]:
        """Nạp và lưu hàng loạt ảnh vào thư mục output_dir/images/.

        Cập nhật `local_path` cho từng ImageRef thành công.
        """
