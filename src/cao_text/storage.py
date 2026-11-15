"""storage.py — Lưu trữ nguyên tử và quản lý ProfileStore, ProgressStore cho Cào Text v2.

Quy tắc:
  - Ghi file quan trọng (profile, progress, chapter) bằng atomic write: ghi .tmp -> os.replace.
  - Khi bị cancel (CancelledError) hoặc gặp lỗi: tự động xóa file .tmp để không để lại rác.
  - ProfileStore: quản lý SiteProfile (load, save, delete, check fresh) với khóa async lock.
  - ProgressStore: lưu trữ tiến độ mỗi truyện theo cấu trúc mới:
        progress/<story_key>/state.json (StoryState nhỏ gọn)
        progress/<story_key>/seen.jsonl (append-only các chương đã cào)
    kèm cơ chế tự động chuyển đổi file progress v1 cũ sang cấu trúc mới.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from cao_text.models import SiteProfile, StoryState
from cao_text.settings import get_settings

logger = logging.getLogger(__name__)


# ── Atomic Write Helpers ──────────────────────────────────────────────────────

def atomic_write_text(path: Path | str, content: str) -> None:
    """Ghi nội dung text xuống disk bằng atomic write (.tmp -> os.replace).

    Nếu bị ngắt quãng hoặc có lỗi, file .tmp sẽ được dọn dẹp ngay lập tức.
    """
    target = Path(path).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = target.with_suffix(target.suffix + ".tmp")

    try:
        tmp_path.write_text(content, encoding="utf-8", newline="\n")
        os.replace(tmp_path, target)
    except BaseException:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass
        raise


def atomic_write_json(path: Path | str, data: Any, *, indent: int = 2) -> None:
    """Ghi dữ liệu JSON xuống disk bằng atomic write."""
    text = json.dumps(data, ensure_ascii=False, indent=indent) + "\n"
    atomic_write_text(path, text)


async def async_atomic_write_text(path: Path | str, content: str) -> None:
    """Phiên bản async của atomic_write_text (chạy qua to_thread)."""
    try:
        await asyncio.to_thread(atomic_write_text, path, content)
    except asyncio.CancelledError:
        # Đảm bảo dọn file .tmp nếu coroutine bị cancel giữa chừng
        tmp = Path(path).with_suffix(Path(path).suffix + ".tmp")
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass
        raise


async def async_atomic_write_json(path: Path | str, data: Any, *, indent: int = 2) -> None:
    """Phiên bản async của atomic_write_json."""
    try:
        await asyncio.to_thread(atomic_write_json, path, data, indent=indent)
    except asyncio.CancelledError:
        tmp = Path(path).with_suffix(Path(path).suffix + ".tmp")
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass
        raise


# ── ProfileStore ──────────────────────────────────────────────────────────────

class ProfileStore:
    """Quản lý đọc/ghi danh sách SiteProfile từ file site_profiles.json."""

    def __init__(self, profiles_file: Path | str | None = None) -> None:
        self.profiles_file = (
            Path(profiles_file) if profiles_file else Path(get_settings().profiles_file)
        )
        self._lock = asyncio.Lock()
        self._cache: dict[str, SiteProfile] | None = None

    async def load_all(self) -> dict[str, SiteProfile]:
        """Nạp toàn bộ SiteProfile từ đĩa. Trả về dict rỗng nếu file chưa tồn tại."""
        async with self._lock:
            return await self._load_all_unlocked()

    async def _load_all_unlocked(self) -> dict[str, SiteProfile]:
        if not self.profiles_file.exists():
            self._cache = {}
            return {}

        def _read() -> dict[str, SiteProfile]:
            try:
                raw_text = self.profiles_file.read_text(encoding="utf-8")
                raw_dict = json.loads(raw_text)
                if not isinstance(raw_dict, dict):
                    return {}
                result: dict[str, SiteProfile] = {}
                for domain, val in raw_dict.items():
                    try:
                        result[domain] = SiteProfile.model_validate(val)
                    except Exception as e:
                        logger.warning("Không thể parse profile cho %s: %s", domain, e)
                return result
            except Exception as e:
                logger.warning("Không thể đọc %s: %s", self.profiles_file, e)
                return {}

        loaded = await asyncio.to_thread(_read)
        self._cache = loaded
        return dict(self._cache)

    async def get(self, domain: str) -> SiteProfile | None:
        """Lấy profile của domain (thử cả domain gốc và biến thể www.)."""
        async with self._lock:
            if self._cache is None:
                await self._load_all_unlocked()
            assert self._cache is not None

            # 1. Khớp chính xác
            profile = self._cache.get(domain)
            if profile:
                return profile.model_copy()

            # 2. Thử fallback www.
            alt_domain = (
                domain.removeprefix("www.")
                if domain.startswith("www.")
                else f"www.{domain}"
            )
            alt_profile = self._cache.get(alt_domain)
            if alt_profile:
                return alt_profile.model_copy()

            return None

    async def save(self, profile: SiteProfile) -> None:
        """Lưu hoặc cập nhật một SiteProfile xuống đĩa."""
        async with self._lock:
            if self._cache is None:
                await self._load_all_unlocked()
            assert self._cache is not None

            self._cache[profile.domain] = profile.model_copy()
            dumped = {d: p.model_dump() for d, p in self._cache.items()}
            await async_atomic_write_json(self.profiles_file, dumped)

    async def save_all(self, profiles: dict[str, SiteProfile]) -> None:
        """Ghi đè toàn bộ danh sách profile."""
        async with self._lock:
            self._cache = {d: p.model_copy() for d, p in profiles.items()}
            dumped = {d: p.model_dump() for d, p in self._cache.items()}
            await async_atomic_write_json(self.profiles_file, dumped)

    async def delete(self, domain: str) -> bool:
        """Xóa profile của một domain."""
        async with self._lock:
            if self._cache is None:
                await self._load_all_unlocked()
            assert self._cache is not None

            if domain in self._cache:
                del self._cache[domain]
                dumped = {d: p.model_dump() for d, p in self._cache.items()}
                await async_atomic_write_json(self.profiles_file, dumped)
                return True
            return False

    async def has(self, domain: str) -> bool:
        """Kiểm tra xem domain đã có profile chưa."""
        return (await self.get(domain)) is not None

    @staticmethod
    def is_fresh(profile: SiteProfile, max_age_days: int = 30) -> bool:
        """Kiểm tra profile có còn mới không (dựa vào last_learned)."""
        if not profile.last_learned:
            return False
        try:
            learned_dt = datetime.fromisoformat(profile.last_learned)
            if learned_dt.tzinfo is None:
                learned_dt = learned_dt.replace(tzinfo=UTC)
            age_days = (datetime.now(UTC) - learned_dt).total_seconds() / 86400
            return age_days < max_age_days
        except Exception:
            return False


# ── ProgressStore (Khung kiến trúc mới v2) ────────────────────────────────────

class ProgressStore:
    """Lưu trữ tiến độ cào mỗi truyện: state.json + seen.jsonl (append-only).

    Cấu trúc:
        progress/<story_key>/state.json
        progress/<story_key>/seen.jsonl
    """

    def __init__(self, base_dir: Path | str | None = None) -> None:
        self.base_dir = (
            Path(base_dir) if base_dir else Path(get_settings().paths.progress_dir)
        )
        self._locks: dict[str, asyncio.Lock] = {}

    def _get_lock(self, story_key: str) -> asyncio.Lock:
        if story_key not in self._locks:
            self._locks[story_key] = asyncio.Lock()
        return self._locks[story_key]

    def get_story_dir(self, story_key: str) -> Path:
        """Thư mục lưu trữ tiến độ của story_key."""
        return self.base_dir / story_key

    def get_state_path(self, story_key: str) -> Path:
        return self.get_story_dir(story_key) / "state.json"

    def get_seen_path(self, story_key: str) -> Path:
        return self.get_story_dir(story_key) / "seen.jsonl"

    async def load_state(self, story_key: str) -> StoryState | None:
        """Nạp StoryState.

        Nếu chưa có cấu trúc v2, tự động tìm kiếm file tiến độ v1 cũ
        (progress/<story_key>.json hoặc progress/*<story_key>*.json) để chuyển đổi.
        """
        async with self._get_lock(story_key):
            state_file = self.get_state_path(story_key)
            if state_file.exists():
                try:
                    text = await asyncio.to_thread(state_file.read_text, encoding="utf-8")
                    data = json.loads(text)
                    return StoryState.model_validate(data)
                except Exception as e:
                    logger.warning("Không thể đọc state.json cho %s: %s", story_key, e)
                    return None

            # Kiểm tra và tự động chuyển đổi file v1 cũ nếu có
            migrated = await self._try_migrate_v1_progress(story_key)
            if migrated:
                return migrated

            return None

    async def save_state(self, state: StoryState) -> None:
        """Lưu StoryState nguyên tử xuống state.json."""
        async with self._get_lock(state.story_key):
            state_file = self.get_state_path(state.story_key)
            state_file.parent.mkdir(parents=True, exist_ok=True)
            await async_atomic_write_json(state_file, state.model_dump())

    async def record_seen(
        self,
        story_key: str,
        url: str,
        fingerprint: str | None = None,
        chapter_num: int = 0,
    ) -> None:
        """Ghi nhận một URL/chương đã xử lý vào seen.jsonl (append-only)."""
        async with self._get_lock(story_key):
            seen_file = self.get_seen_path(story_key)
            seen_file.parent.mkdir(parents=True, exist_ok=True)

            record = {
                "url": url,
                "fp": fingerprint,
                "ch": chapter_num,
                "ts": datetime.now(UTC).isoformat(),
            }
            line = json.dumps(record, ensure_ascii=False) + "\n"

            def _append() -> None:
                with open(seen_file, "a", encoding="utf-8", newline="\n") as f:
                    f.write(line)

            await asyncio.to_thread(_append)

    async def load_seen_urls(self, story_key: str) -> set[str]:
        """Tải tập hợp các URL đã cào của story."""
        seen_file = self.get_seen_path(story_key)
        if not seen_file.exists():
            return set()

        def _read() -> set[str]:
            urls: set[str] = set()
            try:
                with open(seen_file, encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            try:
                                item = json.loads(line)
                                if "url" in item:
                                    urls.add(item["url"])
                            except json.JSONDecodeError:
                                pass
            except OSError as e:
                logger.warning("Lỗi khi đọc %s: %s", seen_file, e)
            return urls

        return await asyncio.to_thread(_read)

    async def load_fingerprints(self, story_key: str) -> set[str]:
        """Tải tập hợp các fingerprint nội dung đã gặp của story."""
        seen_file = self.get_seen_path(story_key)
        if not seen_file.exists():
            return set()

        def _read() -> set[str]:
            fps: set[str] = set()
            try:
                with open(seen_file, encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            try:
                                item = json.loads(line)
                                if item.get("fp"):
                                    fps.add(item["fp"])
                            except json.JSONDecodeError:
                                pass
            except OSError as e:
                logger.warning("Lỗi khi đọc %s: %s", seen_file, e)
            return fps

        return await asyncio.to_thread(_read)

    async def _try_migrate_v1_progress(self, story_key: str) -> StoryState | None:
        """Tìm và chuyển đổi file progress v1 (progress/*.json) cũ sang cấu trúc v2."""
        if not self.base_dir.exists():
            return None

        # Tìm các file json ở root của progress/ khớp story_key
        candidate_file: Path | None = None
        exact_v1 = self.base_dir / f"{story_key}.json"
        if exact_v1.exists() and exact_v1.is_file():
            candidate_file = exact_v1
        else:
            for p in self.base_dir.glob("*.json"):
                if p.name.endswith(".v1.json"):
                    continue
                if story_key in p.stem:
                    candidate_file = p
                    break

        if not candidate_file or not candidate_file.is_file():
            return None

        def _migrate() -> StoryState | None:
            try:
                data = json.loads(candidate_file.read_text(encoding="utf-8"))
                if not isinstance(data, dict):
                    return None

                state = StoryState(
                    story_key=story_key,
                    start_url=data.get("start_url") or "",
                    current_url=data.get("current_url"),
                    chapter_count=int(data.get("chapter_count") or 0),
                    story_title=data.get("story_title"),
                    completed=bool(data.get("completed", False)),
                    completed_at_url=data.get("completed_at_url"),
                    story_id=data.get("story_id"),
                    story_id_regex=data.get("story_id_regex"),
                    story_id_locked=bool(data.get("story_id_locked", False)),
                    last_title=data.get("last_title"),
                    last_scraped_url=data.get("last_scraped_url"),
                    naming_done=bool(data.get("naming_done", False)),
                    story_name_clean=data.get("story_name_clean"),
                    chapter_keyword=data.get("chapter_keyword") or "Chapter",
                    has_chapter_subtitle=bool(data.get("has_chapter_subtitle", False)),
                    story_prefix_strip=data.get("story_prefix_strip"),
                    output_dir_final=data.get("output_dir_final"),
                )

                # Ghi state.json
                story_dir = self.get_story_dir(story_key)
                story_dir.mkdir(parents=True, exist_ok=True)
                atomic_write_json(self.get_state_path(story_key), state.model_dump())

                # Chuyển all_visited_urls và fingerprints sang seen.jsonl
                seen_file = self.get_seen_path(story_key)
                visited_urls: list[str] = data.get("all_visited_urls") or []
                fingerprints: list[str] = data.get("fingerprints") or []

                with open(seen_file, "w", encoding="utf-8", newline="\n") as sf:
                    max_len = max(len(visited_urls), len(fingerprints))
                    for i in range(max_len):
                        u = visited_urls[i] if i < len(visited_urls) else ""
                        fp = fingerprints[i] if i < len(fingerprints) else None
                        rec = {
                            "url": u,
                            "fp": fp,
                            "ch": i + 1,
                            "ts": datetime.now(UTC).isoformat(),
                        }
                        sf.write(json.dumps(rec, ensure_ascii=False) + "\n")

                # Đổi tên file cũ thành .v1.json làm backup
                backup_path = candidate_file.with_name(candidate_file.stem + ".v1.json")
                if not backup_path.exists():
                    shutil.move(candidate_file, backup_path)
                logger.info("Đã chuyển đổi tiến độ v1 (%s) sang v2 (%s)", candidate_file.name, story_dir)
                return state
            except Exception as e:
                logger.warning("Chuyển đổi file progress v1 thất bại: %s", e)
                return None

        return await asyncio.to_thread(_migrate)
