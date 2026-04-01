# utils/types.py
"""
utils/types.py — TypedDict definitions cho toàn bộ project.

CHANGES (v3):
  SiteProfileDict: Thêm 2 field còn thiếu:
    - nav_type: str | None         — dùng trong navigator.py profile.get("nav_type")
    - domain_watermarks: list[str] — persist watermarks AI học được cho domain
  Cả 2 field đều total=False → backward-compatible với profile JSON cũ.
"""
from __future__ import annotations

from typing import Optional, TypedDict


# ── Progress ──────────────────────────────────────────────────────────────────

class ProgressDict(TypedDict, total=False):
    current_url:       Optional[str]
    chapter_count:     int
    story_title:       Optional[str]
    all_visited_urls:  list[str]
    fingerprints:      list[str]
    collected_urls:    list[str]
    story_id:          Optional[str]
    story_id_regex:    Optional[str]
    story_id_locked:   bool
    story_id_attempts: int
    completed:         bool
    completed_at_url:  Optional[str]
    last_scraped_url:  Optional[str]
    last_title:        Optional[str]


# ── Site profile ──────────────────────────────────────────────────────────────

class SelectorStats(TypedDict, total=False):
    """Hit/try stats cho một CSS selector cụ thể."""
    hits:        int
    total_tries: int


class SiteProfileDict(TypedDict, total=False):
    """
    Profile đầy đủ cho một domain — persist qua các lần chạy.

    NHÓM 1 — CSS Selectors (AI-generated):
      next_selector, title_selector, content_selector

    NHÓM 2 — Selector performance (tự cập nhật khi scrape):
      working_content_selector: selector trong CONTENT_SELECTORS đã proven
        work trên site này. Dùng làm shortcut ở run sau, không cần thử hết list.
      selector_stats: {selector: {hits, total_tries}} — confidence tracking.

    NHÓM 3 — Site behavior flags:
      requires_playwright: Bỏ qua curl_cffi ngay, dùng Playwright.
      has_nav_edges: Luôn chạy _strip_nav_edges() cho site này.
      has_chapter_dropdown: TitleExtractor ưu tiên nguồn <select>.
      has_rel_next: find_next_url ưu tiên rel="next" link.

    NHÓM 4 — URL knowledge:
      chapter_url_pattern: regex nhận diện chapter URL của site này.
      sample_urls: Tối đa 5 URL chapter mẫu đã cào thành công.

    NHÓM 5 — Navigation:
      nav_type: Strategy điều hướng đã biết cho site này.
        Giá trị hợp lệ: "selector" | "rel_next" | "slug_increment"
                        | "dropdown" | "fanfic" | "button" | None
        Dùng trong navigator.py: profile.get("nav_type") để fast-path.
        FIX v3: Field này bị thiếu trong TypedDict mặc dù đã được dùng.

    NHÓM 6 — Watermarks (FIX v3):
      domain_watermarks: Danh sách keyword watermark đặc trưng của domain.
        Được học qua ask_ai_build_profile() và persist vào site_profiles.json.
        Khi run_novel_task() khởi động, inject vào AdsFilter để áp dụng ngay
        từ chương đầu mà không cần AI scan lại.

    NHÓM 7 — Statistics & metadata:
      ai_fallback_count: Số lần heuristic fail, phải gọi AI.
      content_extraction_failures: Số lần không extract được content.
      chapters_scraped: Tổng số chapter đã cào từ site này.
      last_updated: ISO timestamp lần cuối profile cập nhật.
      profile_version: Version schema (dùng cho migration sau này).
      site_notes: Ghi chú tự do về đặc điểm site.
    """

    # NHÓM 1 — CSS Selectors
    next_selector:    Optional[str]
    title_selector:   Optional[str]
    content_selector: Optional[str]

    # NHÓM 2 — Selector performance
    working_content_selector:   Optional[str]
    selector_stats:             dict[str, SelectorStats]

    # NHÓM 3 — Behavior flags
    requires_playwright:    bool
    has_nav_edges:          bool
    has_chapter_dropdown:   bool
    has_rel_next:           bool

    # NHÓM 4 — URL knowledge
    chapter_url_pattern:    Optional[str]
    sample_urls:            list[str]

    # NHÓM 5 — Navigation (FIX v3: field bị thiếu)
    nav_type:               Optional[str]

    # NHÓM 6 — Watermarks (FIX v3: field bị thiếu)
    domain_watermarks:      list[str]

    # NHÓM 7 — Statistics
    ai_fallback_count:              int
    content_extraction_failures:    int
    chapters_scraped:               int
    last_updated:                   Optional[str]
    profile_version:                int
    site_notes:                     Optional[str]


# ── AI results ────────────────────────────────────────────────────────────────

class AiClassifyResult(TypedDict, total=False):
    page_type:         str
    next_url:          Optional[str]
    first_chapter_url: Optional[str]


class StoryIdResult(TypedDict, total=False):
    story_id:       str
    story_id_regex: str


# ── AI profile result (extended) ──────────────────────────────────────────────

class AiProfileResult(TypedDict, total=False):
    """
    Kết quả đầy đủ từ ask_ai_build_profile (prompt mới).
    Superset của SiteProfileDict — chỉ chứa những field AI có thể suy luận
    từ HTML, không có field chỉ runtime mới biết (requires_playwright, ...).

    NOTE: chapter_url_regex (AI field) ≠ chapter_url_pattern (profile field).
    ProfileManager.merge_ai_result() xử lý mapping này.
    """
    next_selector:        Optional[str]
    title_selector:       Optional[str]
    content_selector:     Optional[str]
    nav_type:             Optional[str]
    has_chapter_dropdown: bool
    has_rel_next:         bool
    chapter_url_regex:    Optional[str]   # AI output name
    chapter_url_pattern:  Optional[str]   # Profile field name (fallback)
    domain_watermarks:    list[str]
    site_notes:           Optional[str]
    ai_notes:             Optional[str]