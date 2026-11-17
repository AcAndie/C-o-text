from __future__ import annotations

import asyncio
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
    default_story_output_dir,
    make_story_key,
    resolve_story_output_dir,
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


async def test_async_atomic_write_cleans_tmp_on_cancellation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Khi task async bị cancel giữa chừng, file .tmp phải được xóa và raise CancelledError."""
    target_file = tmp_path / "cancel_target.txt"
    tmp_file = target_file.with_suffix(target_file.suffix + ".tmp")

    def _slow_write(p: Path, c: str) -> None:
        # Tạo file .tmp rồi raise CancelledError giả lập ngắt task
        tmp_file.write_text("Dở dang...", encoding="utf-8")
        raise asyncio.CancelledError()

    monkeypatch.setattr("cao_text.storage.atomic_write_text", _slow_write)

    with pytest.raises(asyncio.CancelledError):
        await async_atomic_write_text(target_file, "Dữ liệu mới")

    assert not target_file.exists()
    assert not tmp_file.exists(), "File .tmp phải được dọn sạch khi bị CancelledError"


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


async def test_progress_store_task_5_1_full_lifecycle_and_v1_url_migration(tmp_path: Path) -> None:
    """Task 5.1: Kiểm tra make_story_key, state.json không lưu mảng URL, load_or_create, clear và giữ nguyên output_dir_final."""
    progress_dir = tmp_path / "progress"
    progress_dir.mkdir(parents=True, exist_ok=True)

    # 1. make_story_key: URL index và URL chương của cùng 1 truyện phải sinh cùng story_key
    rr_index = "https://www.royalroad.com/fiction/55418/rock-falls-everyone-dies"
    rr_ch1 = "https://www.royalroad.com/fiction/55418/rock-falls-everyone-dies/chapter/1083016/chapter-1"
    assert make_story_key(rr_index, "Vault/Novels") == make_story_key(rr_ch1, "Vault/Novels")

    wn_index = "https://www.webnovel.com/book/30780541908206305"
    wn_ch1 = "https://www.webnovel.com/book/30780541908206305/82625129275771249"
    assert make_story_key(wn_index, "Vault/Novels") == make_story_key(wn_ch1, "Vault/Novels")

    # 2. Giả lập file progress v1 thực tế với tên <domain>_<slug>_<hash>.json
    v1_filename = "www_webnovel_com_webnovel_com_book_30780541908206305_fab0f1a8.json"
    v1_path = progress_dir / v1_filename
    v1_payload = {
        "current_url": "https://www.webnovel.com/book/30780541908206305/83664006434312847",
        "chapter_count": 2,
        "story_title": None,
        "all_visited_urls": [
            "https://www.webnovel.com/book/30780541908206305/82625129275771249",
            "https://www.webnovel.com/book/30780541908206305/82646343729871690",
        ],
        "fingerprints": ["12dab5c025c43a72", "7e0b5620b3c976fd"],
        "story_id_regex": "/book/30780541908206305/",
        "story_id_locked": True,
        "completed": False,
        "completed_at_url": None,
        "start_url": wn_ch1,
        "naming_done": True,
        "story_name_clean": "Zero Fate Against the World (New Version)",
        "chapter_keyword": "Chapter",
        "has_chapter_subtitle": True,
        "story_prefix_strip": "Zero Fate Against the World (New Version)",
        "output_dir_final": "Vault/Novels\\Zero_Fate_Against_the_World_(New_Version)",
        "last_title": "Chapter 2",
        "last_scraped_url": "https://www.webnovel.com/book/30780541908206305/82646343729871690",
    }
    v1_path.write_text(json.dumps(v1_payload, ensure_ascii=False), encoding="utf-8")

    store = ProgressStore(base_dir=progress_dir)

    # Gọi load_or_create bằng URL index trong links.md (khác start_url chương 1 bên trong file)
    state = await store.load_or_create(wn_index, base_output_dir="Vault/Novels")
    assert state.chapter_count == 2
    assert state.naming_done is True
    assert state.output_dir_final == "Vault/Novels\\Zero_Fate_Against_the_World_(New_Version)"

    # Giữ nguyên thư mục output đã có để resume viết tiếp đúng chỗ
    resolved_dir = resolve_story_output_dir(state, base_output_dir="Vault/Novels")
    assert resolved_dir == Path("Vault/Novels\\Zero_Fate_Against_the_World_(New_Version)")

    # Kiểm tra state.json trên đĩa KHÔNG chứa all_visited_urls hay fingerprints
    raw_state_on_disk = json.loads(store.get_state_path(state.story_key).read_text(encoding="utf-8"))
    assert "all_visited_urls" not in raw_state_on_disk
    assert "fingerprints" not in raw_state_on_disk

    # Kiểm tra load_seen trả về cả (urls, fps) trong 1 lần đọc
    urls, fps = await store.load_seen(state.story_key)
    assert len(urls) == 2
    assert wn_ch1 in urls
    assert fps == {"12dab5c025c43a72", "7e0b5620b3c976fd"}

    # Backup .v1.json đã được tạo
    assert (progress_dir / "www_webnovel_com_webnovel_com_book_30780541908206305_fab0f1a8.v1.json").exists()

    # 3. Kiểm tra clear() xóa sạch state.json và seen.jsonl
    await store.clear(state.story_key)
    assert not store.get_state_path(state.story_key).exists()
    assert not store.get_seen_path(state.story_key).exists()

    # 4. Kiểm tra resolve_story_output_dir cho truyện mới chưa có output_dir_final
    fresh_state = await store.load_or_create("https://example.com/novel/my-story", base_output_dir="Vault/Novels")
    assert fresh_state.chapter_count == 0
    assert resolve_story_output_dir(fresh_state, "Vault/Novels") == Path(
        default_story_output_dir("https://example.com/novel/my-story", "Vault/Novels")
    )
    fresh_state.story_name_clean = "My Awesome Story: Rise!"
    named_dir = resolve_story_output_dir(fresh_state, "Vault/Novels")
    assert named_dir.name == "My_Awesome_Story_Rise!"
    assert fresh_state.output_dir_final is not None
