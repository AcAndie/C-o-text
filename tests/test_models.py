from __future__ import annotations

import json
from pathlib import Path

from cao_text.models import CleanedChapter, ImageRef, RunConfig, SiteProfile, StoryState
from cao_text.settings import Settings

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def test_site_profile_defaults_and_roundtrip() -> None:
    """Kiểm tra SiteProfile giá trị mặc định, version 3 và roundtrip serialization."""
    profile = SiteProfile(
        domain="example.com",
        content_selector="div.chapter",
        title_selector="h1",
    )
    assert profile.profile_version == 3
    assert profile.domain == "example.com"
    assert profile.is_usable() is True

    dumped = profile.model_dump()
    assert dumped["domain"] == "example.com"
    assert dumped["profile_version"] == 3

    reloaded = SiteProfile.model_validate(dumped)
    assert reloaded.domain == profile.domain
    assert reloaded.content_selector == profile.content_selector


def test_site_profile_loads_legacy_v2_profiles() -> None:
    """Kiểm tra SiteProfile nạp mượt mà các profile v2 hiện có trong data/site_profiles.json."""
    profiles_file = PROJECT_ROOT / "data" / "site_profiles.json"
    if not profiles_file.exists():
        return

    raw_data = json.loads(profiles_file.read_text(encoding="utf-8"))
    for domain, raw_profile in raw_data.items():
        profile = SiteProfile.model_validate(raw_profile)
        assert profile.domain == domain
        assert profile.content_selector is not None
        assert profile.formatting_rules.bold_italic is True


def test_story_state_lifecycle() -> None:
    """Kiểm tra StoryState lưu trạng thái và đánh dấu hoàn thành."""
    state = StoryState(
        story_key="royalroad_rock_falls",
        start_url="https://royalroad.com/ch/1",
        chapter_count=10,
    )
    assert state.completed is False
    assert state.completed_at is None

    state.mark_completed("https://royalroad.com/ch/10")
    assert state.completed is True
    assert state.completed_at is not None
    assert state.completed_at_url == "https://royalroad.com/ch/10"

    dumped = state.model_dump()
    restored = StoryState.model_validate(dumped)
    assert restored.story_key == state.story_key
    assert restored.completed is True


def test_run_config_mode_defaults() -> None:
    """Kiểm tra RunConfig tự động suy ra các cờ theo đúng §1 AGENTS.md."""
    # Obsidian mode
    cfg_obs = RunConfig.create_for_mode("obsidian", "out_obs")
    assert cfg_obs.output_mode == "obsidian"
    assert cfg_obs.download_images is True
    assert cfg_obs.image_placeholder is False
    assert cfg_obs.fetch_metadata is True
    assert cfg_obs.output_dir == "out_obs"

    # Translate mode
    cfg_trans = RunConfig.create_for_mode("translate", "out_trans")
    assert cfg_trans.output_mode == "translate"
    assert cfg_trans.download_images is False
    assert cfg_trans.image_placeholder is True
    assert cfg_trans.fetch_metadata is False

    # Raw mode
    cfg_raw = RunConfig.create_for_mode("raw", "out_raw")
    assert cfg_raw.output_mode == "raw"
    assert cfg_raw.download_images is False
    assert cfg_raw.image_placeholder is False
    assert cfg_raw.fetch_metadata is False


def test_run_config_from_settings() -> None:
    """Kiểm tra khởi tạo RunConfig từ Settings."""
    settings = Settings()
    settings.output.mode = "translate"
    settings.paths.output_dir = "custom_vault"

    cfg = RunConfig.from_settings(settings)
    assert cfg.output_mode == "translate"
    assert cfg.output_dir == "custom_vault"
    assert cfg.image_placeholder is True
    assert cfg.download_images is False


def test_cleaned_chapter_and_image_ref() -> None:
    """Kiểm tra DTO CleanedChapter và ImageRef."""
    img = ImageRef(
        original_url="https://example.com/map.png",
        local_path="images/0001_map.png",
        alt_text="World Map",
        position_marker="IMG_PLACEHOLDER_1",
        source_type="web",
    )
    chap = CleanedChapter(
        index=1,
        title="Chapter 1: Dawn",
        body_markdown="Paragraph one.\n\nParagraph two.",
        images=[img],
        source_url="https://example.com/ch1",
        metadata={"author": "Arthur"},
    )
    assert chap.index == 1
    assert chap.title == "Chapter 1: Dawn"
    assert len(chap.images) == 1
    assert chap.images[0].alt_text == "World Map"
    assert chap.metadata["author"] == "Arthur"
