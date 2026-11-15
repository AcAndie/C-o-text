from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from cao_text.models import SiteProfile, StoryState
from cao_text.storage import (
    ProfileStore,
    ProgressStore,
    async_atomic_write_json,
    async_atomic_write_text,
    atomic_write_json,
    atomic_write_text,
)

# ── Test Atomic Write ─────────────────────────────────────────────────────────

def test_atomic_write_sync(tmp_path: Path) -> None:
    """Kiểm tra ghi text và JSON đồng bộ bằng atomic write."""
    text_file = tmp_path / "hello.txt"
    atomic_write_text(text_file, "Xin chào thế giới")
    assert text_file.exists()
    assert text_file.read_text(encoding="utf-8").strip() == "Xin chào thế giới"

    json_file = tmp_path / "data.json"
    atomic_write_json(json_file, {"key": "giá trị", "number": 42})
    assert json_file.exists()
    loaded = json.loads(json_file.read_text(encoding="utf-8"))
    assert loaded["key"] == "giá trị"
    assert loaded["number"] == 42


def test_atomic_write_cleans_tmp_on_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Khi xảy ra lỗi trong lúc ghi, file .tmp phải được xóa sạch."""
    target_file = tmp_path / "corrupt.txt"
    tmp_file = target_file.with_suffix(target_file.suffix + ".tmp")

    def _mock_replace(src: Path, dst: Path) -> None:
        raise OSError("Mô phỏng lỗi khi replace")

    monkeypatch.setattr("os.replace", _mock_replace)

    with pytest.raises(OSError, match="Mô phỏng lỗi khi replace"):
        atomic_write_text(target_file, "Dữ liệu lỗi")

    assert not target_file.exists()
    assert not tmp_file.exists(), "File .tmp phải được dọn dẹp sau khi gặp lỗi"


async def test_async_atomic_write(tmp_path: Path) -> None:
    """Kiểm tra ghi text và JSON bất đồng bộ."""
    text_file = tmp_path / "async_hello.txt"
    await async_atomic_write_text(text_file, "Async content")
    assert text_file.read_text(encoding="utf-8").strip() == "Async content"

    json_file = tmp_path / "async_data.json"
    await async_atomic_write_json(json_file, {"async": True})
    loaded = json.loads(json_file.read_text(encoding="utf-8"))
    assert loaded["async"] is True


# ── Test ProfileStore ─────────────────────────────────────────────────────────

async def test_profile_store_crud(tmp_path: Path) -> None:
    """Kiểm tra các thao tác get/save/delete/has trong ProfileStore."""
    profiles_file = tmp_path / "site_profiles.json"
    store = ProfileStore(profiles_file)

    assert await store.load_all() == {}
    assert await store.get("royalroad.com") is None
    assert await store.has("royalroad.com") is False

    # 1. Lưu profile mới
    p1 = SiteProfile(
        domain="royalroad.com",
        content_selector="div.chapter-content",
        confidence=0.95,
    )
    await store.save(p1)

    assert await store.has("royalroad.com") is True
    # Thử fallback www.
    got = await store.get("www.royalroad.com")
    assert got is not None
    assert got.content_selector == "div.chapter-content"

    # 2. Xóa profile
    deleted = await store.delete("royalroad.com")
    assert deleted is True
    assert await store.has("royalroad.com") is False


def test_profile_is_fresh() -> None:
    """Kiểm tra ProfileStore.is_fresh()."""
    # 5 ngày trước -> fresh
    recent_dt = (datetime.now(UTC) - timedelta(days=5)).isoformat()
    fresh_profile = SiteProfile(domain="fresh.com", last_learned=recent_dt)
    assert ProfileStore.is_fresh(fresh_profile, max_age_days=30) is True

    # 45 ngày trước -> stale
    old_dt = (datetime.now(UTC) - timedelta(days=45)).isoformat()
    stale_profile = SiteProfile(domain="stale.com", last_learned=old_dt)
    assert ProfileStore.is_fresh(stale_profile, max_age_days=30) is False


# ── Test ProgressStore ────────────────────────────────────────────────────────

async def test_progress_store_save_load_seen(tmp_path: Path) -> None:
    """Kiểm tra lưu StoryState và ghi seen.jsonl trong ProgressStore."""
    store = ProgressStore(base_dir=tmp_path)
    story_key = "test_story_novel"

    state = StoryState(
        story_key=story_key,
        start_url="https://site.com/ch/1",
        current_url="https://site.com/ch/5",
        chapter_count=5,
    )
    await store.save_state(state)

    loaded = await store.load_state(story_key)
    assert loaded is not None
    assert loaded.chapter_count == 5
    assert loaded.current_url == "https://site.com/ch/5"

    # Ghi nhận seen
    await store.record_seen(story_key, "https://site.com/ch/1", fingerprint="fp1", chapter_num=1)
    await store.record_seen(story_key, "https://site.com/ch/2", fingerprint="fp2", chapter_num=2)

    seen_urls = await store.load_seen_urls(story_key)
    assert seen_urls == {"https://site.com/ch/1", "https://site.com/ch/2"}

    seen_fps = await store.load_fingerprints(story_key)
    assert seen_fps == {"fp1", "fp2"}


async def test_progress_store_auto_migrate_v1(tmp_path: Path) -> None:
    """Kiểm tra tự động chuyển đổi file progress v1 cũ sang cấu trúc v2."""
    progress_dir = tmp_path / "progress"
    progress_dir.mkdir(parents=True, exist_ok=True)

    # Giả lập file progress v1 cũ
    v1_file = progress_dir / "royalroad_rock_falls_legacy_hash123.json"
    v1_data = {
        "start_url": "https://www.royalroad.com/ch/1",
        "current_url": "https://www.royalroad.com/ch/3",
        "chapter_count": 3,
        "completed": True,
        "completed_at_url": "https://www.royalroad.com/ch/3",
        "all_visited_urls": [
            "https://www.royalroad.com/ch/1",
            "https://www.royalroad.com/ch/2",
            "https://www.royalroad.com/ch/3",
        ],
        "fingerprints": ["fp_1", "fp_2", "fp_3"],
        "story_name_clean": "Rock falls, everyone dies",
    }
    v1_file.write_text(json.dumps(v1_data, ensure_ascii=False), encoding="utf-8")

    store = ProgressStore(base_dir=progress_dir)
    story_key = "rock_falls"

    migrated_state = await store.load_state(story_key)
    assert migrated_state is not None
    assert migrated_state.chapter_count == 3
    assert migrated_state.completed is True
    assert migrated_state.story_name_clean == "Rock falls, everyone dies"

    # Kiểm tra cấu trúc v2 đã được tạo
    story_dir = progress_dir / story_key
    assert (story_dir / "state.json").exists()
    assert (story_dir / "seen.jsonl").exists()

    # Kiểm tra seen urls & fingerprints
    urls = await store.load_seen_urls(story_key)
    assert len(urls) == 3
    assert "https://www.royalroad.com/ch/1" in urls

    fps = await store.load_fingerprints(story_key)
    assert fps == {"fp_1", "fp_2", "fp_3"}

    # File cũ phải được đổi tên backup sang .v1.json
    assert not v1_file.exists()
    backup_file = progress_dir / "royalroad_rock_falls_legacy_hash123.v1.json"
    assert backup_file.exists()
