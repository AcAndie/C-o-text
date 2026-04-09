"""
core/extractor.py — URL-based title extraction helper.

Dùng bởi UrlSlugTitleBlock như last-resort fallback.
"""
from __future__ import annotations

import re
from urllib.parse import urlparse, unquote


_SLUG_CLEAN = re.compile(r"[-_]+")
_CHAPTER_RE = re.compile(
    r"(?:chapter|chap|ch|episode|ep|part)[_-]?\d+",
    re.IGNORECASE,
)


def _title_from_url(url: str) -> str | None:
    """
    Extract title hint từ URL path slug.

    Ví dụ:
        /chapter-5-the-rise-of-heroes → "The Rise Of Heroes"
        /s/12345678/5/My-Story-Title  → "My Story Title"
        /fiction/55418/the-wandering-inn → "The Wandering Inn"
    """
    try:
        path     = urlparse(url).path
        segments = [s for s in path.strip("/").split("/") if s]

        if not segments:
            return None

        # Thử lấy slug dài nhất có vẻ là title (không phải số thuần)
        slug = None
        for seg in reversed(segments):
            if not seg.isdigit() and len(seg) > 3:
                slug = seg
                break

        if not slug:
            return None

        slug  = unquote(slug)
        # Loại bỏ chapter keyword prefix nếu có
        slug  = _CHAPTER_RE.sub("", slug).strip("-_ ")
        words = _SLUG_CLEAN.sub(" ", slug).strip()

        if not words or len(words) < 3:
            return None

        # Title case
        return words.title()

    except Exception:
        return None