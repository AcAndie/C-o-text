"""
utils/file_io.py — Toàn bộ thao tác I/O file theo mô hình async-safe.

Tất cả hàm ghi dùng pattern .tmp + os.replace() → atomic write,
tránh corrupt file khi bị kill giữa chừng.

asyncio.to_thread() đẩy I/O đồng bộ xuống thread-pool, giải phóng event loop.

Quy ước:
  _sync_*  → hàm đồng bộ, chỉ gọi qua asyncio.to_thread()
  async    → wrapper công khai
"""
import asyncio
import json
import os

from config import PROFILES_FILE


# ── site_profiles.json ────────────────────────────────────────────────────────

def _sync_load_profiles() -> dict:
    if os.path.exists(PROFILES_FILE):
        try:
            with open(PROFILES_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def _sync_save_profiles(profiles: dict) -> None:
    tmp = PROFILES_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(profiles, f, ensure_ascii=False, indent=2)
    os.replace(tmp, PROFILES_FILE)

async def load_profiles() -> dict:
    return await asyncio.to_thread(_sync_load_profiles)

async def save_profiles(profiles: dict) -> None:
    await asyncio.to_thread(_sync_save_profiles, profiles)


# ── progress file ─────────────────────────────────────────────────────────────

def make_default_progress() -> dict:
    return {
        "current_url"      : None,
        "chapter_count"    : 0,
        "story_title"      : None,   # tên truyện (được ghi sau chương 1)
        "all_visited_urls" : [],
        "fingerprints"     : [],
        "collected_urls"   : [],
        "story_id"         : None,
        "story_id_regex"   : None,
        "story_id_locked"  : False,
        "story_id_attempts": 0,
        "completed"        : False,   # True khi hết truyện tự nhiên
        "completed_at_url" : None,
        "last_scraped_url" : None,    # URL chương vừa xong (debug)
        "last_title"       : None,    # tiêu đề chương cuối (dùng bởi confirm_same_story)
    }

def _sync_load_progress(path: str) -> dict:
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            # Backfill bất kỳ key mới nào bị thiếu trong progress cũ
            defaults = make_default_progress()
            for k, v in defaults.items():
                data.setdefault(k, v)
            return data
        except Exception:
            pass
    return make_default_progress()

def _sync_save_progress(path: str, data: dict) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)
    os.replace(tmp, path)

async def load_progress(path: str) -> dict:
    return await asyncio.to_thread(_sync_load_progress, path)

async def save_progress(path: str, data: dict) -> None:
    await asyncio.to_thread(_sync_save_progress, path, data)


# ── file .md ──────────────────────────────────────────────────────────────────

def _sync_write_markdown(path: str, content: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)

async def write_markdown(path: str, content: str) -> None:
    await asyncio.to_thread(_sync_write_markdown, path, content)
