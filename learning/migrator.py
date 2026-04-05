"""
learning/migrator.py — Migrate SiteProfile format cũ → format mới (với pipeline config).

Format cũ (v1):
    {
        "domain": "royalroad.com",
        "content_selector": "div.chapter-content",
        "next_selector": "a.btn-primary[rel='next']",
        "nav_type": "rel_next",
        ...
    }

Format mới (v2):
    {
        "domain": "royalroad.com",
        "pipeline": {
            "fetch_chain": {...},
            "extract_chain": {...},
            ...
        },
        # Giữ lại các field cũ để backward compat
        "content_selector": "div.chapter-content",
        ...
    }

migrate_profile():
    - Đọc profile cũ
    - Map các field sang PipelineConfig tương ứng
    - Trả về profile mới + cờ requires_relearn nếu mapping không đủ thông tin

Backward compatibility:
    PipelineRunner.from_profile() kiểm tra "pipeline" key trước.
    Nếu không có → trả về None → caller dùng default pipeline.
    Không breaking change cho code cũ.
"""
from __future__ import annotations

import logging

from pipeline.base import ChainConfig, PipelineConfig, StepConfig

logger = logging.getLogger(__name__)

# Profile version hiện tại
CURRENT_VERSION = 2


def needs_migration(profile: dict) -> bool:
    """
    Kiểm tra profile có cần migrate không.
    True nếu: không có "pipeline" key HOẶC version < CURRENT_VERSION.
    """
    if not profile:
        return False
    if "pipeline" not in profile:
        return True
    v = profile.get("pipeline", {}).get("optimizer_version", 1)
    return int(v) < CURRENT_VERSION


def migrate_profile(profile: dict) -> tuple[dict, bool]:
    """
    Migrate profile cũ sang format mới.

    Returns:
        (migrated_profile, requires_relearn)
        requires_relearn = True nếu migration không đủ thông tin
                           (thiếu selectors quan trọng → cần re-optimize)
    """
    if not needs_migration(profile):
        return profile, False

    domain = profile.get("domain", "unknown")
    logger.info("[Migrator] Migrating profile for %s", domain)

    # ── Map các field cũ → PipelineConfig ────────────────────────────────────
    content_sel  = profile.get("content_selector")
    next_sel     = profile.get("next_selector")
    title_sel    = profile.get("title_selector")
    nav_type     = profile.get("nav_type")
    requires_pw  = bool(profile.get("requires_playwright", False))
    remove_sels  = profile.get("remove_selectors") or []

    # Fetch chain
    if requires_pw:
        fetch_steps = [StepConfig("playwright"), StepConfig("hybrid")]
    else:
        fetch_steps = [StepConfig("hybrid"), StepConfig("playwright")]

    # Extract chain
    extract_steps: list[StepConfig] = []
    if content_sel:
        extract_steps.append(StepConfig("selector", {"selector": content_sel}))
    extract_steps += [
        StepConfig("json_ld"),
        StepConfig("density_heuristic"),
        StepConfig("fallback_list"),
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

    # Nav chain — map nav_type sang block tương ứng
    nav_steps: list[StepConfig] = []
    _NAV_TYPE_MAP = {
        "rel_next"       : "rel_next",
        "selector"       : "selector",
        "slug_increment" : "slug_increment",
        "fanfic"         : "fanfic",
        "select_dropdown": "select_dropdown",
    }
    if nav_type and nav_type in _NAV_TYPE_MAP:
        mapped = _NAV_TYPE_MAP[nav_type]
        step_params: dict = {}
        if mapped == "selector" and next_sel:
            step_params = {"selector": next_sel}
        nav_steps.append(StepConfig(mapped, step_params))

    # Thêm selector nav nếu chưa có và có next_sel
    if next_sel and not any(
        s.type == "selector" and s.params.get("selector") == next_sel
        for s in nav_steps
    ):
        nav_steps.append(StepConfig("selector", {"selector": next_sel}))

    # Luôn có fallback chain đầy đủ
    for step_type in ("rel_next", "anchor_text", "slug_increment", "fanfic", "ai_nav"):
        if not any(s.type == step_type for s in nav_steps):
            nav_steps.append(StepConfig(step_type))

    # Validate chain
    validate_steps = [
        StepConfig("length",        {"min_chars": 100}),
        StepConfig("prose_richness",{"min_word_count": 20}),
    ]

    pipeline_config = PipelineConfig(
        domain         = domain,
        fetch_chain    = ChainConfig("fetch",    fetch_steps),
        extract_chain  = ChainConfig("extract",  extract_steps),
        title_chain    = ChainConfig("title",    title_steps),
        nav_chain      = ChainConfig("navigate", nav_steps),
        validate_chain = ChainConfig("validate", validate_steps),
        score          = float(profile.get("confidence", 0.5)),
        notes          = f"migrated_from_v1",
    )

    # ── Xác định có cần relearn không ────────────────────────────────────────
    requires_relearn = False
    missing = []
    if not content_sel:
        missing.append("content_selector")
    if not next_sel and nav_type not in ("rel_next", "slug_increment", "fanfic"):
        missing.append("next_selector")
    if missing:
        requires_relearn = True
        logger.warning(
            "[Migrator] %s missing critical fields %s → requires_relearn",
            domain, missing,
        )

    # ── Build migrated profile ────────────────────────────────────────────────
    migrated = dict(profile)   # giữ nguyên tất cả fields cũ
    migrated["pipeline"]         = pipeline_config.to_dict()
    migrated["requires_relearn"] = requires_relearn
    migrated["profile_version"]  = CURRENT_VERSION

    # Ghi chú migration
    migrated["migration_notes"] = (
        f"auto_migrated from v1. "
        + (f"Missing: {missing}. " if missing else "")
        + ("Requires relearn." if requires_relearn else "Migration complete.")
    )

    print(
        f"  [Migrator] ✅ {domain}: migrated "
        + (f"(⚠ requires_relearn: {missing})" if requires_relearn else "(complete)"),
        flush=True,
    )
    return migrated, requires_relearn


def migrate_all(profiles: dict[str, dict]) -> tuple[dict[str, dict], list[str]]:
    """
    Migrate tất cả profiles trong dict.

    Returns:
        (migrated_profiles, list_of_domains_requiring_relearn)
    """
    migrated: dict[str, dict] = {}
    relearn_domains: list[str] = []

    for domain, profile in profiles.items():
        if needs_migration(profile):
            new_profile, requires_relearn = migrate_profile(profile)
            migrated[domain] = new_profile
            if requires_relearn:
                relearn_domains.append(domain)
        else:
            migrated[domain] = profile

    if relearn_domains:
        logger.info(
            "[Migrator] %d domains need relearn: %s",
            len(relearn_domains), relearn_domains,
        )

    return migrated, relearn_domains