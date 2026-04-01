# utils/types.py
"""
utils/types.py — TypedDict definitions cho toàn bộ project.

CHANGES (v4):
  StructuralObservation (NEW): Snapshot cấu trúc DOM của một chương.
    Tích lũy qua OBS_REFINE_AFTER chương rồi gửi AI để refine profile.

  SiteProfileDict — Thêm NHÓM 8 (Structural observations):
    observations, observation_count, profile_refined, refined_at_chapter
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


# ── Structural observation ────────────────────────────────────────────────────

class StructuralObservation(TypedDict, total=False):
    """
    Snapshot cấu trúc DOM của một chương đã cào thành công.

    Được tạo bởi dom_observer.observe_chapter_structure() và tích lũy
    trong SiteProfileDict["observations"].

    Sau OBS_REFINE_AFTER chương, ProfileManager tổng hợp tất cả observations
    thành một summary và gửi AI (ask_ai_refine_profile) để tinh chỉnh profile
    selectors với confidence score.

    Chỉ lưu metadata (tag, classes, id) — KHÔNG lưu content text.
    Tất cả field total=False để backward-compatible với profile cũ.
    """
    # ── Identity ──────────────────────────────────────────────────────────────
    url:             str           # URL chương này
    chapter_num:     int           # Số thứ tự chương

    # ── Content element signals ───────────────────────────────────────────────
    content_selector_hit: Optional[str]   # CSS selector đã win extract
    content_tag:          Optional[str]   # div / article / section / ...
    content_id:           Optional[str]   # id attribute của element
    content_classes:      list[str]       # class list (tối đa 5)

    # ── Title element signals ─────────────────────────────────────────────────
    title_source:    Optional[str]   # nguồn win: "dropdown" | "h1" | "h2" |
                                     # "class:chapter-title" | "og:title" |
                                     # "itemprop:name" | "url_slug" | "content_heading"
    title_tag:       Optional[str]   # tag của element chứa title text
    title_id:        Optional[str]   # id attribute
    title_classes:   list[str]       # class list (tối đa 5)

    # ── Nav next element signals ──────────────────────────────────────────────
    nav_next_tag:     Optional[str]  # a / button
    nav_next_classes: list[str]      # class list
    nav_next_text:    Optional[str]  # button text (truncated 40 chars)
    nav_next_rel:     Optional[str]  # "next" nếu có rel="next"


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
      working_content_selector: selector trong CONTENT_SELECTORS đã proven work.
      selector_stats: {selector: {hits, total_tries}} — confidence tracking.

    NHÓM 3 — Site behavior flags:
      requires_playwright, has_nav_edges, has_chapter_dropdown, has_rel_next.

    NHÓM 4 — URL knowledge:
      chapter_url_pattern, sample_urls.

    NHÓM 5 — Navigation:
      nav_type: strategy đã biết cho site này.

    NHÓM 6 — Watermarks (persist để inject vào AdsFilter ngay khi khởi động).

    NHÓM 7 — Statistics & metadata.

    NHÓM 8 — Structural observations (v4 NEW):
      observations: list observations từ nhiều chương (tối đa OBS_MAX_STORED).
      observation_count: tổng số observations đã record (không giảm khi trim).
      profile_refined: đã qua AI refinement chưa → không trigger lại.
      refined_at_chapter: chương nào đã trigger refinement.
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

    # NHÓM 5 — Navigation
    nav_type:               Optional[str]

    # NHÓM 6 — Watermarks
    domain_watermarks:      list[str]

    # NHÓM 7 — Statistics
    ai_fallback_count:              int
    content_extraction_failures:    int
    chapters_scraped:               int
    last_updated:                   Optional[str]
    profile_version:                int
    site_notes:                     Optional[str]

    # NHÓM 8 — Structural observations (v4 NEW)
    observations:           list[StructuralObservation]
    observation_count:      int        # Tổng obs đã record (monotonic)
    profile_refined:        bool       # True sau khi AI refinement chạy xong
    refined_at_chapter:     int        # Chapter number khi refinement diễn ra


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
    Superset của SiteProfileDict — chỉ chứa những field AI có thể suy luận.
    """
    next_selector:        Optional[str]
    title_selector:       Optional[str]
    content_selector:     Optional[str]
    nav_type:             Optional[str]
    has_chapter_dropdown: bool
    has_rel_next:         bool
    chapter_url_regex:    Optional[str]
    chapter_url_pattern:  Optional[str]
    domain_watermarks:    list[str]
    site_notes:           Optional[str]
    ai_notes:             Optional[str]


# ── AI refinement result (v4 NEW) ─────────────────────────────────────────────

class AiRefinedProfile(TypedDict, total=False):
    """
    Kết quả từ ask_ai_refine_profile() sau khi phân tích StructuralObservations.

    Mỗi selector đi kèm confidence score (0.0–1.0).
    ProfileManager.merge_refined_result() chỉ apply field nếu confidence
    >= OBS_CONFIDENCE_MIN (mặc định 0.8).
    """
    content_selector:   Optional[str]
    content_confidence: float    # 0.0–1.0

    title_selector:     Optional[str]
    title_confidence:   float

    next_selector:      Optional[str]
    next_confidence:    float

    notes:              Optional[str]  # Ghi chú tùy ý từ AI