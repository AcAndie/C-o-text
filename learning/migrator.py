"""
learning/migrator.py — Migrate SiteProfile v1 → v2 (pipeline config).

v2 changes:
  MIG-1: Xóa migrate_all() — dead code, không có chỗ nào gọi.
         Caller (scraper.py) gọi migrate_profile() theo từng domain.

Format v1 (legacy):
    {
        "domain": "royalroad.com",
        "content_selector": "div.chapter-content",
        ...
    }

Format v2 (pipeline):
    {
        "domain": "royalroad.com",
        "pipeline": {"fetch_chain": {...}, ...},
        "content_selector": "...",   ← giữ lại cho backward compat
        ...
    }
"""
from __future__ import annotations

import logging

from pipeline.base import ChainConfig, PipelineConfig, StepConfig

logger = logging.getLogger(__name__)

CURRENT_VERSION = 2


def needs_migration(profile: dict) -> bool:
    """True nếu profile không có "pipeline" key hoặc version < 2."""
    if not profile:
        return False
    if "pipeline" not in profile:
        return True
    v = profile.get("pipeline", {}).get("optimizer_version", 1)
    return int(v) < CURRENT_VERSION


def migrate_profile(profile: dict) -> tuple[dict, bool]:
    """
    Migrate profile v1 → v2.

    Returns:
        (migrated_profile, requires_relearn)
        requires_relearn = True nếu thiếu selectors quan trọng
                           → caller nên force relearn thay vì dùng migrated profile
    """
    if not needs_migration(profile):
        return profile, False

    domain = profile.get("domain", "unknown")
    logger.info("[Migrator] Migrating profile: %s", domain)

    content_sel = profile.get("content_selector")
    next_sel    = profile.get("next_selector")
    title_sel   = profile.get("title_selector")
    nav_type    = profile.get("nav_type")
    requires_pw = bool(profile.get("requires_playwright", False))

    # Fetch chain
    fetch_steps = (
        [StepConfig("playwright"), StepConfig("hybrid")]
        if requires_pw
        else [StepConfig("hybrid"), StepConfig("playwright")]
    )

    # Extract chain
    extract_steps: list[StepConfig] = []
    if content_sel:
        extract_steps.append(StepConfig("selector", {"selector": content_sel}))
    extract_steps += [
        StepConfig("json_ld"),
        StepConfig("density_heuristic"),
        StepConfig("fallback_list"),
        StepConfig("ai_extract"),
    ]

    # Title chain
    title_steps: list[StepConfig] = []
    if title_sel:
        title_steps.append(StepConfig("selector", {"selector": title_sel}))
    title_steps += [
        StepConfig("h1_tag"),
        StepConfig("title_tag"),
        StepConfig("og_title"),
        StepConfig("url_slug"),
    ]

    # Nav chain
    _NAV_TYPE_MAP = {
        "rel_next"       : "rel_next",
        "selector"       : "selector",
        "slug_increment" : "slug_increment",
        "fanfic"         : "fanfic",
        "select_dropdown": "select_dropdown",
    }
    nav_steps: list[StepConfig] = []
    if nav_type and nav_type in _NAV_TYPE_MAP:
        mapped     = _NAV_TYPE_MAP[nav_type]
        step_params: dict = {}
        if mapped == "selector" and next_sel:
            step_params = {"selector": next_sel}
        nav_steps.append(StepConfig(mapped, step_params))

    # Thêm selector nếu có next_sel và chưa trong nav_steps
    if next_sel and not any(
        s.type == "selector" and s.params.get("selector") == next_sel
        for s in nav_steps
    ):
        nav_steps.append(StepConfig("selector", {"selector": next_sel}))

    # Fallback chain đầy đủ
    for step_type in ("rel_next", "anchor_text", "slug_increment", "fanfic", "ai_nav"):
        if not any(s.type == step_type for s in nav_steps):
            nav_steps.append(StepConfig(step_type))

    # Validate chain
    validate_steps = [
        StepConfig("length",         {"min_chars": 100}),
        StepConfig("prose_richness", {"min_word_count": 20}),
    ]

    pipeline_config = PipelineConfig(
        domain         = domain,
        fetch_chain    = ChainConfig("fetch",    fetch_steps),
        extract_chain  = ChainConfig("extract",  extract_steps),
        title_chain    = ChainConfig("title",    title_steps),
        nav_chain      = ChainConfig("navigate", nav_steps),
        validate_chain = ChainConfig("validate", validate_steps),
        score          = float(profile.get("confidence", 0.5)),
        notes          = "migrated_from_v1",
    )

    # Xác định có cần relearn không
    missing: list[str] = []
    if not content_sel:
        missing.append("content_selector")
    if not next_sel and nav_type not in ("rel_next", "slug_increment", "fanfic"):
        missing.append("next_selector")

    requires_relearn = bool(missing)
    if requires_relearn:
        logger.warning("[Migrator] %s missing %s → requires_relearn", domain, missing)

    migrated                     = dict(profile)
    migrated["pipeline"]         = pipeline_config.to_dict()
    migrated["requires_relearn"] = requires_relearn
    migrated["profile_version"]  = CURRENT_VERSION
    migrated["migration_notes"]  = (
        "auto_migrated from v1. "
        + (f"Missing: {missing}. " if missing else "")
        + ("Requires relearn." if requires_relearn else "Migration complete.")
    )

    print(
        f"  [Migrator] ✅ {domain}: migrated"
        + (f" (⚠ requires_relearn: {missing})" if requires_relearn else ""),
        flush=True,
    )
    return migrated, requires_relearn