# utils/types.py
"""
utils/types.py — TypedDict definitions cho toàn bộ project.
"""
from __future__ import annotations
from typing import Optional, TypedDict


# ── Formatting rules ──────────────────────────────────────────────────────────

class SpecialElementRule(TypedDict, total=False):
    found     : bool
    selectors : list[str]
    convert_to: str
    prefix    : str


class FormattingRules(TypedDict, total=False):
    tables            : bool
    bold_italic       : bool
    hr_dividers       : bool
    image_alt_text    : bool
    math_support      : bool
    math_format       : Optional[str]
    system_box        : Optional[SpecialElementRule]
    hidden_text       : Optional[SpecialElementRule]
    author_note       : Optional[SpecialElementRule]
    special_symbols   : list[str]


# ── Site profile ──────────────────────────────────────────────────────────────

class SiteProfile(TypedDict, total=False):
    domain               : str
    last_learned         : str
    confidence           : float
    content_selector     : Optional[str]
    next_selector        : Optional[str]
    title_selector       : Optional[str]
    remove_selectors     : list[str]
    nav_type             : Optional[str]
    chapter_url_pattern  : Optional[str]
    requires_playwright  : bool
    formatting_rules     : FormattingRules
    ads_keywords_learned : list[str]
    learned_chapters     : list[int]
    sample_urls          : list[str]


# ── Progress ──────────────────────────────────────────────────────────────────

class ProgressDict(TypedDict, total=False):
    current_url      : Optional[str]
    chapter_count    : int
    story_title      : Optional[str]
    all_visited_urls : list[str]
    fingerprints     : list[str]

    last_title       : Optional[str]
    last_scraped_url : Optional[str]

    story_id        : Optional[str]
    story_id_regex  : Optional[str]
    story_id_locked : bool

    completed        : bool
    completed_at_url : Optional[str]

    learning_done : bool
    start_url     : str

    # ── Naming phase (per-story, set once) ───────────────────────────────────
    naming_done          : bool           # True sau khi naming phase đã chạy
    story_name_clean     : Optional[str]  # "Monster, No, I'm a Cultivator!"
    chapter_keyword      : Optional[str]  # "Chapter" | "Episode" | "Ch." | ...
    has_chapter_subtitle : bool           # True nếu chapter có subtitle phụ
    story_prefix_strip   : Optional[str]  # prefix cần bóc trước khi parse chap title
    output_dir_final     : Optional[str]  # "output/Monster, No, I'm a Cultivator!"


# ── AI result types ───────────────────────────────────────────────────────────

class AiClassifyResult(TypedDict, total=False):
    page_type         : str
    next_url          : Optional[str]
    first_chapter_url : Optional[str]


class AiInitialProfile(TypedDict, total=False):
    content_selector    : Optional[str]
    next_selector       : Optional[str]
    title_selector      : Optional[str]
    remove_selectors    : list[str]
    nav_type            : Optional[str]
    chapter_url_pattern : Optional[str]
    requires_playwright : bool
    notes               : Optional[str]


class AiValidation(TypedDict, total=False):
    content_valid : bool
    content_fix   : Optional[str]
    next_valid    : bool
    next_fix      : Optional[str]
    title_valid   : bool
    title_fix     : Optional[str]
    remove_add    : list[str]
    notes         : Optional[str]


class AiSpecialContent(TypedDict, total=False):
    has_tables      : bool
    has_math        : bool
    math_format     : Optional[str]
    math_evidence   : list[str]
    special_symbols : list[str]
    notes           : Optional[str]


class AiFormattingAnalysis(TypedDict, total=False):
    system_box     : dict
    hidden_text    : dict
    author_note    : dict
    bold_italic    : bool
    hr_dividers    : bool
    image_alt_text : bool
    notes          : Optional[str]


class AiFinalCrosscheck(TypedDict, total=False):
    confidence             : float
    content_selector_final : Optional[str]
    next_selector_final    : Optional[str]
    title_selector_final   : Optional[str]
    remove_selectors_final : list[str]
    ads_keywords           : list[str]
    notes                  : Optional[str]