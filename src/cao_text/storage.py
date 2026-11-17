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
import hashlib
import json
import logging
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from cao_text.models import SiteProfile, StoryState
from cao_text.settings import get_settings

logger = logging.getLogger(__name__)

_HASH_SUFFIX_RE = re.compile(r"_[0-9a-f]{8}$")


# ── Story Key & Output Dir Helpers ────────────────────────────────────────────

def default_story_output_dir(url: str, base_output_dir: Path | str | None = None) -> str:
    """Tạo đường dẫn thư mục output mặc định từ URL theo chuẩn v1 (<base>/<domain>_<slug>)."""
    base = str(base_output_dir) if base_output_dir is not None else get_settings().paths.output_dir
    p = urlparse(url)
    domain = p.netloc.lower().replace("www.", "").replace(".", "_").replace(":", "_")
    parts = [seg for seg in p.path.strip("/").split("/") if seg][:2]
    slug = "_".join(parts) if parts else "unknown"
    return os.path.join(base, f"{domain}_{slug}")


def make_story_key(url: str, base_output_dir: Path | str | None = None) -> str:
    """Sinh story_key duy nhất dạng <domain>_<slug>_<hash> tương thích ngược 100% với v1."""
    out_dir = default_story_output_dir(url, base_output_dir)
    p = urlparse(url)
    domain = p.netloc.lower().replace(".", "_").replace(":", "_")
    dir_hash = hashlib.md5(out_dir.encode("utf-8")).hexdigest()[:8]
    base_slug = Path(out_dir).name
    return f"{domain}_{base_slug}_{dir_hash}"


def resolve_story_output_dir(
    state: StoryState,
    base_output_dir: Path | str | None = None,
) -> Path:
    """Xác định thư mục output cho truyện, ưu tiên giữ nguyên thư mục đã có để resume viết tiếp."""
    if state.output_dir_final:
        return Path(state.output_dir_final)

    base = str(base_output_dir) if base_output_dir is not None else get_settings().paths.output_dir
    if state.story_name_clean:
        from cao_text.writers.obsidian import slugify_filename

        story_slug = slugify_filename(state.story_name_clean, max_len=80)
        resolved = os.path.join(base, story_slug)
        state.output_dir_final = resolved
        return Path(resolved)

    return Path(default_story_output_dir(state.start_url, base))


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

    async def load_state(
        self,
        story_key: str,
        *,
        start_url: str | None = None,
    ) -> StoryState | None:
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
                    if isinstance(data, dict):
                        data.pop("all_visited_urls", None)
                        data.pop("fingerprints", None)
                    return StoryState.model_validate(data)
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    logger.warning("Không thể đọc state.json cho %s: %s", story_key, e)
                    return None

            # Kiểm tra và tự động chuyển đổi file v1 cũ nếu có
            migrated = await self._try_migrate_v1_progress(story_key, start_url=start_url)
            if migrated:
                return migrated

            return None

    async def load_or_create(
        self,
        start_url: str,
        *,
        story_key: str | None = None,
        base_output_dir: Path | str | None = None,
    ) -> StoryState:
        """Nạp StoryState hiện có (tự migrate v1 nếu gặp) hoặc khởi tạo mới cho start_url."""
        key = story_key or make_story_key(start_url, base_output_dir)
        existing = await self.load_state(key, start_url=start_url)
        if existing is not None:
            if not existing.start_url:
                existing.start_url = start_url
            return existing
        return StoryState(story_key=key, start_url=start_url)

    async def save_state(self, state: StoryState) -> None:
        """Lưu StoryState nguyên tử xuống state.json (không bao giờ lưu danh sách URL/fingerprint)."""
        async with self._get_lock(state.story_key):
            state_file = self.get_state_path(state.story_key)
            state_file.parent.mkdir(parents=True, exist_ok=True)
            dumped = state.model_dump()
            dumped.pop("all_visited_urls", None)
            dumped.pop("fingerprints", None)
            await async_atomic_write_json(state_file, dumped)

    async def clear(self, story_key: str) -> None:
        """Xóa tiến độ của một story_key (dùng khi học lại hoặc reset truyện)."""
        async with self._get_lock(story_key):
            for path in (self.get_state_path(story_key), self.get_seen_path(story_key)):
                if path.exists():
                    try:
                        await asyncio.to_thread(path.unlink)
                    except OSError as e:
                        logger.warning("Không thể xóa %s: %s", path, e)

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

    async def load_seen(self, story_key: str) -> tuple[set[str], set[str]]:
        """Tải đồng thời tập hợp (seen_urls, seen_fingerprints) chỉ trong 1 lần đọc seen.jsonl."""
        seen_file = self.get_seen_path(story_key)
        if not seen_file.exists():
            return set(), set()

        def _read() -> tuple[set[str], set[str]]:
            urls: set[str] = set()
            fps: set[str] = set()
            try:
                with open(seen_file, encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            item = json.loads(line)
                            u = item.get("url")
                            if u:
                                urls.add(str(u))
                            fp = item.get("fp")
                            if fp:
                                fps.add(str(fp))
                        except json.JSONDecodeError:
                            pass
            except OSError as e:
                logger.warning("Lỗi khi đọc %s: %s", seen_file, e)
            return urls, fps

        return await asyncio.to_thread(_read)

    async def load_seen_urls(self, story_key: str) -> set[str]:
        """Tải tập hợp các URL đã cào của story."""
        urls, _ = await self.load_seen(story_key)
        return urls

    async def load_fingerprints(self, story_key: str) -> set[str]:
        """Tải tập hợp các fingerprint nội dung đã gặp của story."""
        _, fps = await self.load_seen(story_key)
        return fps

    def _find_v1_progress_file(
        self,
        story_key: str,
        start_url: str | None = None,
    ) -> Path | None:
        """Tìm file tiến độ v1 cũ khớp với story_key hoặc start_url."""
        if not self.base_dir.exists():
            return None

        # 1. Khớp chính xác tên file <story_key>.json
        exact_v1 = self.base_dir / f"{story_key}.json"
        if exact_v1.exists() and exact_v1.is_file():
            return exact_v1

        v1_files = [
            p
            for p in sorted(self.base_dir.glob("*.json"))
            if p.is_file() and not p.name.endswith(".v1.json")
        ]
        if not v1_files:
            return None

        # 2. Khớp chuỗi con trực tiếp story_key trong tên file
        for p in v1_files:
            if story_key in p.stem or p.stem in story_key:
                return p

        # 3. Khớp theo core slug (bỏ hậu tố hash 8 ký tự và tiền tố www_)
        core_slug = _HASH_SUFFIX_RE.sub("", story_key).removeprefix("www_")
        if len(core_slug) >= 6:
            for p in v1_files:
                if core_slug in p.stem:
                    return p

        # 4. Nếu có start_url, kiểm tra core_slug từ start_url hoặc start_url bên trong JSON
        if start_url:
            url_key = make_story_key(start_url)
            url_core = _HASH_SUFFIX_RE.sub("", url_key).removeprefix("www_")
            for p in v1_files:
                if url_key == p.stem or (len(url_core) >= 6 and url_core in p.stem):
                    return p

            for p in v1_files:
                try:
                    raw = json.loads(p.read_text(encoding="utf-8"))
                    if isinstance(raw, dict):
                        if raw.get("start_url") == start_url:
                            return p
                        visited = raw.get("all_visited_urls") or []
                        if start_url in visited:
                            return p
                except Exception:
                    continue

        return None

    async def _try_migrate_v1_progress(
        self,
        story_key: str,
        start_url: str | None = None,
    ) -> StoryState | None:
        """Tìm và chuyển đổi file progress v1 (progress/*.json) cũ sang cấu trúc v2."""
        if not self.base_dir.exists():
            return None

        def _migrate() -> StoryState | None:
            candidate_file = self._find_v1_progress_file(story_key, start_url=start_url)
            if not candidate_file or not candidate_file.is_file():
                return None

            try:
                data = json.loads(candidate_file.read_text(encoding="utf-8"))
                if not isinstance(data, dict):
                    return None

                is_completed = bool(data.get("completed", False))
                completed_at = data.get("completed_at")
                if is_completed and not completed_at:
                    try:
                        mtime = candidate_file.stat().st_mtime
                        completed_at = datetime.fromtimestamp(mtime, tz=UTC).isoformat()
                    except OSError:
                        completed_at = datetime.now(UTC).isoformat()

                state = StoryState(
                    story_key=story_key,
                    start_url=data.get("start_url") or start_url or "",
                    current_url=data.get("current_url"),
                    chapter_count=int(data.get("chapter_count") or 0),
                    story_title=data.get("story_title"),
                    completed=is_completed,
                    completed_at=completed_at,
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

                # Ghi state.json gọn nhẹ (không chứa all_visited_urls / fingerprints)
                story_dir = self.get_story_dir(story_key)
                story_dir.mkdir(parents=True, exist_ok=True)
                dumped = state.model_dump()
                dumped.pop("all_visited_urls", None)
                dumped.pop("fingerprints", None)
                atomic_write_json(self.get_state_path(story_key), dumped)

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
                os.replace(candidate_file, backup_path)
                logger.info("Đã chuyển đổi tiến độ v1 (%s) sang v2 (%s)", candidate_file.name, story_dir)
                return state
            except Exception as e:
                logger.warning("Chuyển đổi file progress v1 thất bại: %s", e)
                return None

        return await asyncio.to_thread(_migrate)
