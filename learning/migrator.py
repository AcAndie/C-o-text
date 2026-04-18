"""
learning/migrator.py — Profile version migration.

Xử lý chuyển đổi SiteProfile từ v1 (legacy) → v2 (current flat-field format).

v1 (legacy):
  - Có key "pipeline" chứa PipelineConfig serialization (đã bỏ ở Batch B)
  - profile_version = 1 hoặc không có key này

v2 (current):
  - Flat fields trực tiếp: content_selector, next_selector, title_selector, ...
  - Không có "pipeline" key
  - profile_version = 2

Public API:
    needs_migration(profile) → bool
    migrate_profile(profile) → (migrated_dict, requires_relearn: bool)
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# Fields bắt buộc cho v2 profile hợp lệ
# Thiếu bất kỳ field nào → requires_relearn = True
_REQUIRED_V2_FIELDS = ("content_selector", "nav_type")


def needs_migration(profile: dict) -> bool:
    """
    Kiểm tra profile có cần migration không.

    Returns True nếu:
        - profile_version < 2 (legacy v1)
        - profile_version key không tồn tại (rất cũ)
    """
    try:
        version = int(profile.get("profile_version", 1))
    except (TypeError, ValueError):
        version = 1
    return version < 2


def migrate_profile(profile: dict) -> tuple[dict, bool]:
    """
    Migrate profile v1 → v2.

    Migration steps:
        1. Xóa key "pipeline" (PipelineConfig serialization — Batch B cleanup)
        2. Set profile_version = 2
        3. Kiểm tra critical fields — requires_relearn nếu thiếu

    Returns:
        (migrated_profile, requires_relearn)
        requires_relearn = True → caller nên xóa profile và chạy lại learning phase.
    """
    migrated = dict(profile)
    domain   = migrated.get("domain", "unknown")

    # Step 1: Xóa legacy pipeline serialization (Batch B)
    if "pipeline" in migrated:
        migrated.pop("pipeline")
        logger.info("[Migrator] %s: removed legacy 'pipeline' key", domain)

    # Step 2: Mark as v2
    migrated["profile_version"] = 2

    # Step 3: Kiểm tra critical fields
    missing = [f for f in _REQUIRED_V2_FIELDS if not migrated.get(f)]
    requires_relearn = bool(missing)

    if requires_relearn:
        logger.warning(
            "[Migrator] %s: missing critical fields %s → requires relearn",
            domain, missing,
        )
    else:
        logger.info("[Migrator] %s: migrated v1 → v2 successfully", domain)

    return migrated, requires_relearn