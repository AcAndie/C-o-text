"""AdsFilter: phát hiện, lọc 2-pass, xác minh bằng AI và hậu xử lý dòng quảng cáo/watermark lặp lại (Task 5.4 & §6.5, §7.3)."""
from __future__ import annotations

import asyncio
import json
import logging
import math
import re
import threading
from collections import Counter
from pathlib import Path
from typing import Any

from cao_text.ai.prompts import prompt_verify_ads_lines
from cao_text.ai.provider import LLMProvider
from cao_text.ai.schemas import VerifyAdsOutput
from cao_text.models import SiteProfile
from cao_text.settings import get_settings
from cao_text.storage import ProfileStore, atomic_write_json, atomic_write_text
from cao_text.writers.nav_injector import INDEX_FILENAME

logger = logging.getLogger(__name__)

_MIN_LINE_LEN = 8
_MAX_LINE_LEN = 300

_ADS_SAVE_LOCK = threading.Lock()

# Các từ đơn giao diện chung chung không bao giờ được học làm từ khóa quảng cáo (§6.5)
_ADS_GENERIC_WORDS = frozenset({
    "title", "novel", "login", "browse", "filter", "random", "ranking",
    "author", "useful", "member", "update", "follow", "share", "report",
    "search", "logout", "signup", "rating", "review", "submit", "cancel",
    "saving", "reader", "latest", "recent", "posted", "edited", "status",
    "advertisement", "chapter", "index", "table of contents",
})

# Cụm điều hướng không được học làm từ khóa quảng cáo (§6.5)
_ADS_NAV_PHRASE_RE = re.compile(
    r"^(?:next|prev(?:ious)?)\s+(?:chapter|page|part)\s*$"
    r"|^(?:fiction|chapter|novel)\s+index\s*$"
    r"|^(?:chương|tập)\s+(?:trước|sau|tiếp)\s*$",
    re.IGNORECASE,
)

# Dấu hiệu rõ ràng của URL / tên miền / watermark bản quyền (§7.3)
_WATERMARK_HINT_RE = re.compile(
    r"(?:https?://|www\.|\b[a-z0-9\-]+\.(?:com|net|org|io|vn|me)\b"
    r"|royal\s*road|webnovel|patreon|discord|telegram|ko-fi|paypal|amazon"
    r"|stolen|pirated|unauthori[sz]ed|copyright|donate|vote\s+for|power\s+stone)",
    re.IGNORECASE,
)

# Ký tự mở đầu câu thoại hoặc chuyển cảnh (§7.3)
_DIALOGUE_START_CHARS = ('"', "'", "\u201c", "\u201d", "\u2018", "\u2019", "«", "「", "『", "-", "–", "—")

# Watermark cố định theo domain (bắt ngay từ chương 1)
_BUILTIN_DOMAIN_WATERMARKS: dict[str, list[str]] = {
    "royalroad.com": [
        "support the author by reading on royal road",
        "read the original on royal road",
        "royal road is the home of this novel",
        "royal road as an amazon associate",
    ],
}

# Regex bắt các biến thể câu chống trộm xoay vòng của RoyalRoad
_BUILTIN_DOMAIN_WATERMARK_PATTERNS: dict[str, list[re.Pattern[str]]] = {
    "royalroad.com": [
        re.compile(
            r"\bamazon\b.{0,80}\b("
            r"permission|consent|author|report|stolen|taken|pilfered|"
            r"appropriated|misappropriated|illicit|illegal|unlawful|"
            r"unauthori[sz]ed|violation"
            r")\b",
            re.IGNORECASE,
        ),
        re.compile(
            r"\b("
            r"permission|consent|stolen|taken|pilfered|appropriated|"
            r"misappropriated|illicit|illegal|unlawful|unauthori[sz]ed|"
            r"lifted|reported|report it"
            r")\b.{0,80}\bamazon\b",
            re.IGNORECASE,
        ),
        re.compile(
            r"\b("
            r"stolen|taken|pilfered|appropriated|misappropriated|illicit|"
            r"illegal|unlawful|unauthori[sz]ed|lifted"
            r")\b.{0,80}\broyal\s*road\b",
            re.IGNORECASE,
        ),
    ],
}


def compute_auto_threshold(total_chapters: int = 0, base_threshold: int = 10) -> int:
    """Tính ngưỡng tự động thêm từ khóa quảng cáo: max(10, ceil(0.03 * số chương)) (§7.3)."""
    return max(base_threshold, math.ceil(0.03 * max(0, total_chapters)))


def is_likely_dialogue_or_scene_break(line: str) -> bool:
    """Nhận diện dòng ngắn kiểu lời thoại hoặc chuyển cảnh không được tự động xóa (§7.3).

    Quy tắc §7.3:
      - Bắt đầu bằng dấu ngoặc kép / gạch đầu dòng thoại, HOẶC
      - Kết thúc bằng dấu hai chấm `:` / `：` (ví dụ: "Hàn Tuyệt nói:"), HOẶC
      - Ngắn < 25 ký tự (ví dụ: "Cùng lúc đó.")
      -> Trả về True (bảo vệ khỏi nhánh tự động xóa) TRỪ KHI có dấu hiệu URL/watermark rõ ràng.
    """
    s = line.strip()
    if not s:
        return True
    if _WATERMARK_HINT_RE.search(s):
        return False
    if s.startswith(_DIALOGUE_START_CHARS):
        return True
    if s.endswith((":", "：")):
        return True
    return len(s) < 25


def is_valid_ads_keyword(
    kw: str,
    *,
    story_title: str | None = None,
) -> bool:
    """Kiểm tra tính hợp lệ của từ khóa quảng cáo (§6.5).

    Quy tắc §6.5:
      - Văn bản thuần ≥ 8 ký tự và ≤ 200 ký tự.
      - Không phải thẻ HTML (<...>, </...>), không phải Markdown heading (#), không phải URL (://).
      - Không trùng tên truyện (story_title).
      - Không phải cụm điều hướng ("next chapter", "prev page"...).
      - Không nằm trong danh sách từ giao diện chung chung ("login", "title"...).
    """
    if not isinstance(kw, str) or not kw.strip():
        return False
    s = kw.strip()
    if (
        s.startswith("<")
        or s.startswith("#")
        or "</" in s
        or "://" in s
    ):
        return False
    if not (_MIN_LINE_LEN <= len(s) <= _MAX_LINE_LEN):
        return False
    lo = s.lower()
    if lo in _ADS_GENERIC_WORDS:
        return False
    if story_title and lo == story_title.strip().lower():
        return False
    if len(s.split()) > 20:
        return False
    return not _ADS_NAV_PHRASE_RE.match(s)


class AdsFilter:
    """Bộ lọc quảng cáo/watermark 2-pass kèm học tần suất và xác minh AI cuối truyện."""

    def __init__(
        self,
        domain: str,
        known_keywords: set[str] | None = None,
        *,
        ads_db_file: str | Path | None = None,
        story_title: str | None = None,
    ) -> None:
        self._domain = domain
        self._story_title = story_title
        self._ads_db_file = (
            Path(ads_db_file)
            if ads_db_file is not None
            else Path(get_settings().ads_keywords_file)
        )
        self._keywords: set[str] = {
            kw.lower().strip()
            for kw in (known_keywords or set())
            if is_valid_ads_keyword(kw, story_title=story_title)
        }
        self._suspects: Counter[str] = Counter()
        self._file_counter: Counter[str] = Counter()
        self._pending_review: dict[str, bool] = {}
        self._new_suspects: set[str] = set()

        canonical = (
            domain.lower()
            .removeprefix("www.")
            .removeprefix("epub:")
            .removeprefix("txt:")
        )
        self._regex_patterns: list[re.Pattern[str]] = list(
            _BUILTIN_DOMAIN_WATERMARK_PATTERNS.get(canonical, [])
        )

    @property
    def domain(self) -> str:
        return self._domain

    @property
    def keywords(self) -> set[str]:
        return set(self._keywords)

    @property
    def stats(self) -> str:
        return f"known={len(self._keywords)} edge_suspects={len(self._suspects)}"

    def set_story_title(self, story_title: str | None) -> None:
        """Cập nhật tên truyện để tránh học nhầm tên truyện làm từ khóa quảng cáo (§6.5)."""
        self._story_title = story_title
        if story_title:
            st_lo = story_title.strip().lower()
            self._keywords.discard(st_lo)

    # ── Factory ───────────────────────────────────────────────────────────────

    @classmethod
    def load(
        cls,
        domain: str,
        *,
        ads_db_file: str | Path | None = None,
        story_title: str | None = None,
    ) -> AdsFilter:
        """Khởi tạo AdsFilter từ file data/ads_keywords.json kết hợp builtin watermarks."""
        db_path = (
            Path(ads_db_file)
            if ads_db_file is not None
            else Path(get_settings().ads_keywords_file)
        )
        global_kws: set[str] = set()
        domain_kws: set[str] = set()

        if db_path.exists():
            try:
                raw_text = db_path.read_text(encoding="utf-8")
                data = json.loads(raw_text)
                if isinstance(data, dict):
                    global_kws = {str(x) for x in (data.get("global") or []) if isinstance(x, str)}
                    domain_kws = {str(x) for x in (data.get(domain) or []) if isinstance(x, str)}
                    alt_domain = (
                        domain.removeprefix("www.")
                        if domain.startswith("www.")
                        else f"www.{domain}"
                    )
                    domain_kws |= {str(x) for x in (data.get(alt_domain) or []) if isinstance(x, str)}
            except Exception as e:
                logger.warning("[Ads] Không thể đọc %s: %s", db_path, e)

        canonical = domain.lower().removeprefix("www.")
        builtin_kws = set(_BUILTIN_DOMAIN_WATERMARKS.get(canonical, []))

        return cls(
            domain=domain,
            known_keywords=global_kws | domain_kws | builtin_kws,
            ads_db_file=db_path,
            story_title=story_title,
        )

    def inject_from_profile(self, profile: SiteProfile | dict[str, Any] | None) -> int:
        """Nạp danh sách ads_keywords_learned từ SiteProfile vào bộ lọc."""
        if profile is None:
            return 0
        if hasattr(profile, "ads_keywords_learned"):
            kws = list(profile.ads_keywords_learned or [])
        elif isinstance(profile, dict):
            kws = list(profile.get("ads_keywords_learned") or [])
        else:
            return 0

        before = len(self._keywords)
        for kw in kws:
            if isinstance(kw, str) and is_valid_ads_keyword(kw, story_title=self._story_title):
                self._keywords.add(kw.lower().strip())
        return len(self._keywords) - before

    # ── Filtering & Edge Scanning ─────────────────────────────────────────────

    def filter(self, content: str, chapter_url: str = "") -> str:
        """Lọc bỏ các dòng chứa từ khóa quảng cáo hoặc khớp regex watermark."""
        if not content or (not self._keywords and not self._regex_patterns):
            return content

        lines = content.splitlines()
        cleaned: list[str] = []
        for line in lines:
            lo = line.lower().strip()
            if not lo:
                cleaned.append(line)
                continue
            if any(kw in lo for kw in self._keywords):
                logger.debug("[Ads] Filtered (kw) on %s: %r", chapter_url or self._domain, line[:80])
                continue
            if any(p.search(line) for p in self._regex_patterns):
                logger.debug("[Ads] Filtered (regex) on %s: %r", chapter_url or self._domain, line[:80])
                continue
            cleaned.append(line)

        return "\n".join(cleaned)

    def scan_edges_for_suspects(
        self,
        content: str,
        chapter_url: str = "",
        chapter_file: str = "",
    ) -> None:
        """Quét 5 dòng đầu và 5 dòng cuối của chương để thống kê tần suất các dòng nghi vấn."""
        lines = [line.strip() for line in content.splitlines() if line.strip()]
        if not lines:
            return

        edge = min(5, len(lines))
        candidates = lines[:edge] + (lines[-edge:] if len(lines) > edge else [])

        seen_in_chapter: set[str] = set()
        for line in candidates:
            lo = line.lower().strip()
            if (
                _MIN_LINE_LEN <= len(lo) <= _MAX_LINE_LEN
                and lo not in self._keywords
                and is_valid_ads_keyword(lo, story_title=self._story_title)
            ):
                self._suspects[lo] += 1
                if lo not in seen_in_chapter:
                    seen_in_chapter.add(lo)
                    self._file_counter[lo] += 1

    # ── Candidate Retrieval ───────────────────────────────────────────────────

    def get_candidates_by_frequency(
        self,
        auto_threshold: int | None = None,
        min_count: int = 3,
        max_results: int = 20,
        total_chapters: int = 0,
    ) -> tuple[list[str], list[str]]:
        """Phân loại ứng viên theo tần suất:
        - auto_candidates: xuất hiện ≥ ngưỡng (max(10, ceil(0.03 * total_chapters))) VÀ không phải câu thoại/chuyển cảnh ngắn (§7.3).
        - ai_candidates: xuất hiện từ min_count (3) đến < ngưỡng (3–9 lần), hoặc dòng thoại ngắn chạm ngưỡng cần AI xác minh.
        """
        threshold = (
            auto_threshold
            if auto_threshold is not None
            else compute_auto_threshold(total_chapters)
        )
        auto: list[str] = []
        ai: list[str] = []

        for line, count in self._suspects.most_common(max_results * 3):
            if line in self._keywords:
                continue
            if not is_valid_ads_keyword(line, story_title=self._story_title):
                continue

            if count >= threshold:
                if is_likely_dialogue_or_scene_break(line):
                    # §7.3: Không tự động xóa câu thoại ngắn / chuyển cảnh nếu không có dấu hiệu URL/watermark
                    ai.append(line)
                else:
                    auto.append(line)
            elif count >= min_count:
                ai.append(line)

            if len(auto) + len(ai) >= max_results * 2:
                break

        return auto[:max_results], ai[:max_results]

    def get_new_frequency_suspects(
        self,
        min_files: int = 5,
        max_results: int = 20,
    ) -> list[str]:
        """Lấy các dòng xuất hiện ở ≥ min_files chương khác nhau nhưng chưa được xác nhận."""
        result: list[str] = []
        seen: set[str] = set()

        for line, count in self._file_counter.most_common():
            if line in self._keywords or line in seen:
                continue
            if not is_valid_ads_keyword(line, story_title=self._story_title):
                continue
            if count >= min_files:
                seen.add(line)
                result.append(line)
                self._new_suspects.add(line)
            if len(result) >= max_results:
                break

        return result[:max_results]

    # ── Applying & Persisting Verified Results ────────────────────────────────

    def apply_verified(self, lines: list[str], *, is_auto: bool = False) -> int:
        """Thêm các dòng đã xác nhận vào tập từ khóa quảng cáo."""
        added = 0
        for line in lines:
            if not isinstance(line, str):
                continue
            lo = line.lower().strip()
            if not lo or lo in self._keywords:
                continue
            if not is_valid_ads_keyword(lo, story_title=self._story_title):
                continue
            if is_auto and is_likely_dialogue_or_scene_break(lo):
                continue
            self._keywords.add(lo)
            added += 1
        return added

    def save_pending_review(
        self,
        domain_slug: str,
        verified_results: dict[str, bool] | None = None,
    ) -> None:
        if verified_results:
            self._pending_review.update(verified_results)

    def save(self) -> None:
        """Lưu danh sách từ khóa quảng cáo xuống file data/ads_keywords.json bằng atomic write."""
        try:
            self._ads_db_file.parent.mkdir(parents=True, exist_ok=True)
            with _ADS_SAVE_LOCK:
                data: dict[str, Any] = {}
                if self._ads_db_file.exists():
                    try:
                        loaded = json.loads(self._ads_db_file.read_text(encoding="utf-8"))
                        if isinstance(loaded, dict):
                            data = loaded
                    except (json.JSONDecodeError, OSError) as e:
                        logger.warning("[Ads] File %s lỗi định dạng, tạo lại: %s", self._ads_db_file, e)

                existing = {
                    str(x).lower().strip()
                    for x in (data.get(self._domain) or [])
                    if isinstance(x, str)
                }
                valid_kws = {
                    kw
                    for kw in self._keywords
                    if is_valid_ads_keyword(kw, story_title=self._story_title)
                }
                data[self._domain] = sorted(existing | valid_kws)
                atomic_write_json(self._ads_db_file, data)
        except Exception as e:
            logger.warning("[Ads] Lưu %s thất bại: %s", self._ads_db_file, e)

    @staticmethod
    def post_process_directory(
        confirmed_lines: list[str],
        output_dir: str | Path,
    ) -> int:
        """Hậu xử lý xóa các dòng quảng cáo mới phát hiện khỏi các file chương đã ghi trên đĩa."""
        out_path = Path(output_dir)
        if not confirmed_lines or not out_path.is_dir():
            return 0

        patterns = [line.lower().strip() for line in confirmed_lines if isinstance(line, str) and line.strip()]
        if not patterns:
            return 0

        total_removed = 0
        for fpath in sorted(out_path.iterdir()):
            if not fpath.is_file():
                continue
            if fpath.suffix not in (".md", ".txt") or fpath.name == INDEX_FILENAME:
                continue
            try:
                content = fpath.read_text(encoding="utf-8")
                lines = content.splitlines(keepends=True)
                cleaned = [line for line in lines if not any(p in line.lower() for p in patterns)]
                removed = len(lines) - len(cleaned)
                if removed > 0:
                    atomic_write_text(fpath, "".join(cleaned))
                    total_removed += removed
            except OSError as e:
                logger.debug("[Ads] Lỗi hậu xử lý file %s: %s", fpath.name, e)

        return total_removed

    async def finalize(
        self,
        *,
        ai_provider: LLMProvider | None = None,
        profile: SiteProfile | None = None,
        profile_store: ProfileStore | None = None,
        output_dir: str | Path | None = None,
        total_chapters: int = 0,
        cancelled: bool = False,
        allow_ai: bool = True,
    ) -> int:
        """Cuối truyện: tự thêm ứng viên ≥ ngưỡng (§7.3), xác minh AI nhóm tần suất 3–9, hậu xử lý file đã ghi và lưu DB."""
        domain_slug = self._domain.replace(".", "_")
        verified_results: dict[str, bool] = {}
        newly_learned: list[str] = []

        auto_candidates, ai_candidates = self.get_candidates_by_frequency(
            total_chapters=total_chapters,
        )

        # 1. Nhánh tự động (≥ ngưỡng max(10, ceil(0.03 * total_chapters)))
        if auto_candidates:
            added = self.apply_verified(auto_candidates, is_auto=True)
            for line in auto_candidates:
                if line in self._keywords:
                    verified_results[line] = True
                    newly_learned.append(line)
            if added > 0:
                logger.info("[Ads] +%d từ khóa tự động học cho %s (%s)", added, self._domain, self.stats)

        # 2. Nhánh xác minh bằng AI cho các dòng tần suất 3–9 (chỉ áp dụng cho Web khi có ai_provider)
        new_suspect_lines = self.get_new_frequency_suspects(min_files=5, max_results=20)
        all_for_ai = [
            line
            for line in dict.fromkeys(ai_candidates + new_suspect_lines)
            if line not in self._keywords
        ]

        if allow_ai and not cancelled and ai_provider is not None and all_for_ai:
            try:
                prompt = prompt_verify_ads_lines(all_for_ai, self._domain)
                out: VerifyAdsOutput = await ai_provider.generate(prompt, VerifyAdsOutput)
                confirmed = [
                    line.lower().strip()
                    for line in (out.ad_lines or [])
                    if is_valid_ads_keyword(line, story_title=self._story_title)
                ]
                confirmed_set = set(confirmed)
                for line in all_for_ai:
                    verified_results[line] = line.lower().strip() in confirmed_set

                if confirmed:
                    self.apply_verified(confirmed, is_auto=False)
                    for c_line in confirmed:
                        if c_line in self._keywords and c_line not in newly_learned:
                            newly_learned.append(c_line)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.warning("[Ads] Xác minh quảng cáo bằng AI thất bại cho %s: %s", self._domain, e)

        # 3. Hậu xử lý xóa các dòng quảng cáo mới học khỏi những file chương đã ghi trước đó
        removed_from_files = 0
        if newly_learned and output_dir is not None:
            removed_from_files = await asyncio.to_thread(
                self.post_process_directory,
                newly_learned,
                output_dir,
            )
            if removed_from_files > 0:
                logger.info(
                    "[Ads] Đã hậu xử lý xóa %d dòng quảng cáo khỏi các file chương tại %s",
                    removed_from_files,
                    output_dir,
                )

        # 4. Cập nhật vào SiteProfile nếu có
        if newly_learned and profile is not None:
            existing_prof_kws = set(profile.ads_keywords_learned or [])
            updated_kws = list(existing_prof_kws | set(newly_learned))
            if len(updated_kws) > len(existing_prof_kws):
                profile.ads_keywords_learned = sorted(updated_kws)
                if profile_store is not None:
                    try:
                        await profile_store.save(profile)
                    except asyncio.CancelledError:
                        raise
                    except Exception as e:
                        logger.warning("[Ads] Không thể cập nhật ads_keywords vào ProfileStore: %s", e)

        self.save_pending_review(domain_slug, verified_results or None)
        await asyncio.to_thread(self.save)
        return removed_from_files


__all__ = [
    "AdsFilter",
    "compute_auto_threshold",
    "is_likely_dialogue_or_scene_break",
    "is_valid_ads_keyword",
]
