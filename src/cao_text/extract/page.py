"""process_page: Hàm thuần túy, đồng bộ, không gọi mạng/AI/ghi file.

Chuyển đổi một trang HTML sang PageResult bao gồm:
  - content_md đã qua format, clean, strip nav edges, bỏ tiêu đề trùng
  - title và title_method
  - next_url và nav_method
  - danh sách images ImageRef
  - is_index_page
  - selector_used
  - diagnostics
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from cao_text.extract.content import extract_content
from cao_text.extract.nav import detect_page_type, find_next_url
from cao_text.extract.title import extract_title
from cao_text.extract.validate import validate_content
from cao_text.html.cleaner import (
    clean_extracted_content,
    strip_duplicate_title_header,
    strip_nav_edges,
)
from cao_text.html.filter import prepare_soup
from cao_text.models import ImageRef, SiteProfile


@dataclass
class PageResult:
    """Hợp đồng dữ liệu kết quả bóc tách một trang đơn."""

    content_md: str | None
    title: str | None
    title_method: str
    next_url: str | None
    nav_method: str
    images: list[ImageRef] = field(default_factory=list)
    selector_used: str | None = None
    is_index_page: bool = False
    diagnostics: dict[str, Any] = field(default_factory=dict)


def process_page(
    html: str,
    url: str,
    profile: SiteProfile | dict[str, Any] | None = None,
    *,
    source: Literal["web", "epub", "txt"] = "web",
) -> PageResult:
    """Hàm thuần xử lý trích xuất trang đơn (không I/O mạng, không AI, không ghi file)."""
    if not html or not html.strip():
        return PageResult(
            content_md=None,
            title=None,
            title_method="none",
            next_url=None,
            nav_method="none",
            images=[],
            selector_used=None,
            is_index_page=False,
            diagnostics={"empty_html": True},
        )

    # 1. Trích xuất các bộ chọn từ profile
    remove_selectors: list[str] = []
    content_selector: str | None = None
    title_selector: str | None = None
    next_selector: str | None = None

    if profile is not None:
        if hasattr(profile, "remove_selectors"):
            remove_selectors = list(profile.remove_selectors or [])
            content_selector = profile.content_selector
            title_selector = profile.title_selector
            next_selector = profile.next_selector
        elif isinstance(profile, dict):
            remove_selectors = list(profile.get("remove_selectors") or [])
            content_selector = profile.get("content_selector")
            title_selector = profile.get("title_selector")
            next_selector = profile.get("next_selector")

    # 2. Chuẩn bị soup sạch với NAV-PROTECT
    soup = prepare_soup(
        html,
        remove_selectors=remove_selectors,
        content_selector=content_selector,
        title_selector=title_selector,
        next_selector=next_selector,
    )

    # 3. Nhận diện trang mục lục (index page)
    is_index_page = False
    if source == "web":
        is_index_page = detect_page_type(soup, url) == "index"

    # 4. Trích xuất nội dung chương
    raw_content, content_method, images, selector_used = extract_content(
        soup, url, profile, source=source
    )

    content_md: str | None = None
    cleaned_before_strip: str | None = None
    if raw_content:
        cleaned = clean_extracted_content(raw_content)
        cleaned_before_strip = cleaned
        if source == "web":
            stripped = strip_nav_edges(cleaned)
            if stripped and len(stripped.strip()) >= 100:
                content_md = stripped
            else:
                content_md = cleaned
        else:
            content_md = cleaned

    # 5. Trích xuất tiêu đề chương
    title, title_method = extract_title(soup, url, profile)

    # Bỏ dòng tiêu đề bị trùng lặp ở đầu nội dung (§6.2)
    if content_md and title:
        content_md = strip_duplicate_title_header(content_md, title)

    # 6. Điều hướng link tiếp theo
    next_url: str | None = None
    nav_method: str = "none"
    if source == "web":
        next_url, nav_method = find_next_url(soup, url, profile)

    # 7. Kiểm chứng nội dung (§6.6: bỏ qua validate độ dài cho EPUB/TXT)
    if source == "web":
        val = validate_content(content_md or "")
        is_valid = val.is_valid
        val_score = val.score
        val_notes = val.notes
    else:
        is_valid = bool(content_md and content_md.strip())
        val_score = 1.0 if is_valid else 0.0
        val_notes = []

    diagnostics: dict[str, Any] = {
        "content_chars": len(content_md) if content_md else 0,
        "content_method": content_method,
        "title_method": title_method,
        "nav_method": nav_method,
        "is_valid": is_valid,
        "validation_score": val_score,
        "validation_notes": val_notes,
        "selector_used": selector_used,
        "cleaned_before_strip": cleaned_before_strip,
    }

    return PageResult(
        content_md=content_md,
        title=title,
        title_method=title_method,
        next_url=next_url,
        nav_method=nav_method,
        images=images,
        selector_used=selector_used,
        is_index_page=is_index_page,
        diagnostics=diagnostics,
    )
