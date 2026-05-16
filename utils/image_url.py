"""
utils/image_url.py — Image URL resolver + extension detector (P2.1).

Standalone helper cho image fetch pipeline (BLUEPRINT §5 image_pipeline).
Không import từ pipeline/core/learning — pure utility.

resolve_image_url(): chuẩn hoá <img> tag URL về absolute. Handle lazy-load
variants (data-src, data-original, ...), protocol-relative (//cdn/...),
relative (/img/...), srcset (pick highest descriptor), skip data URI.

detect_image_extension(): Content-Type header trước, magic bytes fallback,
.jpg safe default.
"""
from __future__ import annotations

from urllib.parse import urljoin

from bs4 import Tag


# Order of preference — `src` first, lazy-load variants sau.
# Site dùng lazy-load thường có `src` = placeholder (data: hoặc spacer.gif),
# data attribute chứa URL thật.
_IMG_SRC_ATTRS = ("src", "data-src", "data-original", "data-lazy-src", "data-actual-src")

# Content-Type → extension map
_CT_TO_EXT = {
    "image/jpeg": ".jpg",
    "image/jpg" : ".jpg",
    "image/png" : ".png",
    "image/webp": ".webp",
    "image/gif" : ".gif",
}


def resolve_image_url(tag: Tag, base_url: str) -> str | None:
    """
    Resolve <img> tag's URL về absolute form.

    Return None nếu:
      - Tag không có src/data-src/srcset hợp lệ
      - URL là data: URI (inline base64 — không download)
      - URL rỗng

    Order:
      1. _IMG_SRC_ATTRS (lazy-load variants)
      2. srcset → pick last entry (thường highest descriptor)
      3. Skip data: URI
      4. Protocol-relative → prepend https:
      5. Relative → urljoin(base_url, url)
      6. Absolute → return as-is
    """
    url: str | None = None

    for attr in _IMG_SRC_ATTRS:
        val = tag.get(attr)
        if val and isinstance(val, str) and not val.startswith("data:"):
            url = val
            break

    if not url:
        srcset = tag.get("srcset")
        if srcset and isinstance(srcset, str):
            # "url1 1x, url2 2x" → pick last entry (thường largest descriptor)
            parts = [p.strip() for p in srcset.split(",") if p.strip()]
            if parts:
                last = parts[-1].split()
                if last:
                    url = last[0]

    if not url:
        return None
    if url.startswith("data:"):
        return None

    if url.startswith("//"):
        return "https:" + url
    if url.startswith(("http://", "https://")):
        return url
    return urljoin(base_url, url)


def detect_image_extension(content_type: str | None, magic_bytes: bytes) -> str:
    """
    Detect file extension từ Content-Type trước, magic bytes fallback.

    Content-Type có thể bị lừa (server trả `text/html` thay vì `image/jpeg`)
    — magic bytes check 4 byte signature là defense layer 2.

    Fallback `.jpg` nếu không detect được — safer than không có extension.
    """
    if content_type:
        ct = content_type.lower().split(";")[0].strip()
        if ct in _CT_TO_EXT:
            return _CT_TO_EXT[ct]

    if magic_bytes.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if magic_bytes.startswith(b"\x89PNG"):
        return ".png"
    if magic_bytes.startswith(b"RIFF") and b"WEBP" in magic_bytes[:12]:
        return ".webp"
    if magic_bytes.startswith(b"GIF8"):
        return ".gif"

    return ".jpg"
