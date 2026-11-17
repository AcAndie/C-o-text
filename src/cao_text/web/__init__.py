"""Phân loại URL khởi đầu, điều phối task song song và vòng lặp cào truyện web."""
from __future__ import annotations

from cao_text.web.runner import (
    DomainLockManager,
    apply_relearn,
    is_valid_url,
    normalize_domain,
    parse_links,
    run_novel_task,
    run_web_tasks,
)
from cao_text.web.session import Outcome, ScrapeSession
from cao_text.web.start import (
    ClassificationStore,
    classify_url,
    is_chapter_url,
    resolve_start_url,
    story_id_ok,
)

__all__ = [
    "ClassificationStore",
    "DomainLockManager",
    "Outcome",
    "ScrapeSession",
    "apply_relearn",
    "classify_url",
    "is_chapter_url",
    "is_valid_url",
    "normalize_domain",
    "parse_links",
    "resolve_start_url",
    "run_novel_task",
    "run_web_tasks",
    "story_id_ok",
]
