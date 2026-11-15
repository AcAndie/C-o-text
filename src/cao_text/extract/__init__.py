"""extract: Bóc tách nội dung, tiêu đề, điều hướng và kiểm chứng trang."""
from __future__ import annotations

from cao_text.extract.content import (
    FALLBACK_CONTENT_SELECTORS,
    extract_content,
)
from cao_text.extract.nav import (
    RE_CHAP_KW,
    RE_CHAP_SLUG,
    RE_CHAP_URL,
    RE_FANFIC,
    RE_NEXT_BTN,
    detect_page_type,
    find_next_url,
)
from cao_text.extract.page import (
    PageResult,
    process_page,
)
from cao_text.extract.title import (
    clean_title_trailing_dash,
    extract_title,
    normalize_title,
    strip_site_suffix,
    title_from_url,
)
from cao_text.extract.validate import (
    ValidationResult,
    validate_content,
)

__all__ = [
    "FALLBACK_CONTENT_SELECTORS",
    "PageResult",
    "RE_CHAP_KW",
    "RE_CHAP_SLUG",
    "RE_CHAP_URL",
    "RE_FANFIC",
    "RE_NEXT_BTN",
    "ValidationResult",
    "clean_title_trailing_dash",
    "detect_page_type",
    "extract_content",
    "extract_title",
    "find_next_url",
    "normalize_title",
    "process_page",
    "strip_site_suffix",
    "title_from_url",
    "validate_content",
]
