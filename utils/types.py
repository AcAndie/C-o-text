# utils/types.py
"""
utils/types.py — TypedDict + dataclass definitions cho toàn bộ project.

Batch B: Xóa pipeline/optimizer_score/requires_relearn/migration_notes khỏi SiteProfile.
  Các fields này chỉ được dùng bởi PipelineConfig serialization — đã xóa.
  Profile v1 cũ có 'pipeline' field sẽ bị reject bởi ProfileManager.get() —
  user phải re-learn (!relearn hoặc --bulk-relearn).
  profile_version giữ lại như metadata vô hại.

P1.1: Thêm RunConfig dataclass (per-run, transient — không persist).
  Drive output mode + image policy + metadata fetch theo CLI args.
  BLUEPRINT §8 + Decision #13 (image policy per-mode).
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Literal, Optional, TypedDict


# ── Formatting rules ──────────────────────────────────────────────────────────

class SpecialElementRule(TypedDict, total=False):
    found     : bool
    selectors : list[str]
    convert_to: str
    prefix    : str


class FormattingRules(TypedDict, total=False):
    """
    P1.2: Writer-facing formatting rules (BLUEPRINT §8 + Decision #23).

    Schema mới — replace 100% schema cũ (tables/math_support/system_box ...).
    Runtime dict vẫn carry legacy keys tới khi consumers migrate sang fields
    mới (P1.5+). TypedDict total=False nên runtime không enforce — IDE hints
    follow schema mới, dict storage vẫn tolerate legacy.

    image_alt_strategy thay cho boolean image_alt_text cũ — explicit về
    behavior. Default "preserve" (BLUEPRINT line 591).
    """
    # Tag → Markdown mapping decisions
    headings_as_h2       : bool
    preserve_bold        : bool
    preserve_italic      : bool
    preserve_blockquote  : bool
    paragraph_separator  : str
    list_style           : Literal["dash", "asterisk"]

    # Image handling (single source of truth)
    image_alt_strategy   : Literal["preserve", "skip", "fallback_to_filename"]

    # Stripping
    strip_inline_links   : bool
    strip_html_comments  : bool

    # Language/encoding
    text_encoding        : str


# ── Site profile ──────────────────────────────────────────────────────────────

class SiteProfile(TypedDict, total=False):
    # ── Core identity ─────────────────────────────────────────────────────────
    domain               : str
    last_learned         : str
    confidence           : float
    profile_version      : int          # Metadata — kept for reference

    # ── Selector fields ───────────────────────────────────────────────────────
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

    # ── Debug / meta ──────────────────────────────────────────────────────────
    uncertain_fields     : list[str]
    learning_version     : int          # 1=5-call, 2=8-call (Batch A), 3=future


# ── Progress ──────────────────────────────────────────────────────────────────

class ProgressDict(TypedDict, total=False):
    current_url      : Optional[str]
    chapter_count    : int
    story_title      : Optional[str]
    all_visited_urls : list[str]
    fingerprints     : list[str]

    last_title       : Optional[str]
    last_scraped_url : Optional[str]

    story_id         : Optional[str]
    story_id_regex   : Optional[str]
    story_id_locked  : bool

    completed        : bool
    completed_at_url : Optional[str]

    learning_done    : bool
    start_url        : str

    # ── Naming phase ──────────────────────────────────────────────────────────
    naming_done          : bool
    story_name_clean     : Optional[str]
    chapter_keyword      : Optional[str]
    has_chapter_subtitle : bool
    story_prefix_strip   : Optional[str]
    output_dir_final     : Optional[str]


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


# ── Run config (P1.1, BLUEPRINT §8) ───────────────────────────────────────────

@dataclass
class RunConfig:
    """
    Per-run, transient config. Drive output mode + image policy + metadata fetch.

    KHÔNG persist. Tạo 1 lần từ CLI args đầu mỗi run, pass xuống PipelineContext
    sau (Phase 1.5).

    Default derivation per mode (BLUEPRINT §4 + Decision #13):
      obsidian  → download_images=True,  image_placeholder=False, fetch_metadata=True
      translate → download_images=False, image_placeholder=True,  fetch_metadata=False
      raw       → download_images=False, image_placeholder=False, fetch_metadata=False
    """
    output_mode      : Literal["obsidian", "translate", "raw"]
    download_images  : bool
    image_placeholder: bool
    fetch_metadata   : bool
    output_dir       : str
    max_pw_instances : int  = 2
    fast_learning    : bool = False
    no_validation    : bool = False

    @classmethod
    def from_cli(cls, args) -> "RunConfig":
        mode = args.output_mode
        defaults = {
            "obsidian" : {"dl": True,  "ph": False, "meta": True},
            "translate": {"dl": False, "ph": True,  "meta": False},
            "raw"      : {"dl": False, "ph": False, "meta": False},
        }[mode]
        return cls(
            output_mode       = mode,
            download_images   = defaults["dl"],
            image_placeholder = defaults["ph"],
            fetch_metadata    = defaults["meta"],
            output_dir        = args.output_dir,
            max_pw_instances  = args.max_pw_instances or 2,
            fast_learning     = args.fast_learning,
            no_validation     = args.no_validation,
        )