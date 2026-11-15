"""
tests/test_golden_web.py — Kiểm tra hàm thuần process_page của package mới cao_text
so với golden baselines v1 (fixtures_local/web).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from cao_text.extract.page import process_page
from cao_text.models import SiteProfile
from conftest import (
    assert_json_extract_match,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
FIXTURES_LOCAL_ROOT = PROJECT_ROOT / "tests" / "fixtures_local"
GOLDEN_LOCAL_ROOT = PROJECT_ROOT / "tests" / "golden_local"


def profile_v2_to_v3(raw_profile: dict[str, Any]) -> SiteProfile:
    """Chuyển đổi profile v2 từ meta.json sang SiteProfile v3."""
    p = dict(raw_profile)
    p["profile_version"] = 3
    if "formatting_rules" not in p or not isinstance(p["formatting_rules"], dict):
        p["formatting_rules"] = {}
    return SiteProfile.model_validate(p)


def _get_web_stories() -> list[tuple[str, str]]:
    web_dir = FIXTURES_LOCAL_ROOT / "web"
    if not web_dir.exists():
        return []
    stories = []
    for domain_dir in sorted(web_dir.iterdir()):
        if not domain_dir.is_dir():
            continue
        for story_dir in sorted(domain_dir.iterdir()):
            if (story_dir / "meta.json").exists():
                stories.append((domain_dir.name, story_dir.name))
    return stories


_WEB_STORIES = _get_web_stories()


@pytest.mark.skipif(not _WEB_STORIES, reason="Không tìm thấy tests/fixtures_local/web")
@pytest.mark.parametrize("domain, story", _WEB_STORIES)
def test_golden_web_process_page(domain: str, story: str, update_golden: bool) -> None:
    """Chạy process_page trên toàn bộ fixtures web và so sánh với golden v1."""
    fixture_story_dir = FIXTURES_LOCAL_ROOT / "web" / domain / story
    golden_story_dir = GOLDEN_LOCAL_ROOT / "web" / domain / story

    assert fixture_story_dir.exists(), f"Thiếu fixture web: {fixture_story_dir}"
    if not update_golden:
        assert golden_story_dir.exists(), f"Thiếu golden web: {golden_story_dir}"

    with open(fixture_story_dir / "meta.json", encoding="utf-8") as f:
        meta: dict[str, Any] = json.load(f)

    raw_profile = meta.get("profile", {})
    profile_v3 = profile_v2_to_v3(raw_profile) if raw_profile else None
    chapters = meta.get("chapters", [])
    assert chapters, f"meta.json không có chapters: {fixture_story_dir}"

    for ch in chapters:
        file_name = ch["file"]
        html_path = fixture_story_dir / file_name
        golden_json_path = golden_story_dir / (Path(file_name).stem + ".json")

        assert html_path.exists(), f"Thiếu file HTML: {html_path}"
        if not update_golden:
            assert golden_json_path.exists(), f"Thiếu file golden JSON: {golden_json_path}"

        html = html_path.read_text(encoding="utf-8")
        url = ch["url"]

        res = process_page(html, url, profile=profile_v3, source="web")

        actual_record = {
            "url": url,
            "title": res.title or "Unknown Title",
            "content": res.content_md or "",
            "next_url": res.next_url,
            "nav_method": res.nav_method if (res.next_url and res.nav_method != "none") else "",
            "selector_used": res.selector_used,
        }

        if update_golden:
            golden_json_path.parent.mkdir(parents=True, exist_ok=True)
            golden_json_path.write_text(
                json.dumps(actual_record, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            continue

        with open(golden_json_path, encoding="utf-8") as f:
            expected_record: dict[str, Any] = json.load(f)

        assert_json_extract_match(
            actual_record,
            expected_record,
            min_content_ratio=0.99,
            context=f"{domain}/{story}/{file_name}",
        )
