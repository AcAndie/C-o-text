# core/profile_manager.py
"""
core/profile_manager.py — Thread-safe wrapper quản lý site profiles.

Tất cả thao tác đọc/ghi profile đi qua đây để:
  1. Tập trung logic merge AI → profile (field name mapping)
  2. Thread-safe với asyncio.Lock chia sẻ từ AppState
  3. Lazy save: chỉ ghi file khi dirty, tránh I/O không cần thiết
  4. Expose domain_watermarks để scraper.py inject vào AdsFilter

CHANGES (v2):
  merge_ai_result(): Map đầy đủ 9 field từ AI result → SiteProfileDict,
    bao gồm domain_watermarks (FIX issue #2), chapter_url_regex → chapter_url_pattern,
    nav_type, requires_playwright, has_chapter_dropdown, has_rel_next.

  get_domain_watermarks(): Mới — cho scraper.py inject vào AdsFilter khi khởi động.
  get_domain_patterns(): Mới — cho scraper.py inject regex từ profile.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from utils.file_io import save_profiles
from utils.types import SiteProfileDict

logger = logging.getLogger(__name__)

_PROFILE_VERSION = 2
_SAMPLE_URL_CAP  = 5


class ProfileManager:
    """
    Quản lý dict[domain → SiteProfileDict] với asyncio.Lock.

    Được khởi tạo 1 lần trong run_novel_task và truyền xuống các hàm con.
    Lock được chia sẻ từ AppState.profiles_lock để các task song song
    không ghi đè nhau.
    """

    def __init__(
        self,
        profiles: dict[str, SiteProfileDict],
        lock: asyncio.Lock,
    ) -> None:
        self._profiles = profiles
        self._lock     = lock
        self._dirty    = False

    # ── Read-only helpers (no lock needed — Python GIL đủ cho dict read) ──────

    def get(self, domain: str) -> SiteProfileDict:
        """Trả về profile của domain hoặc empty dict nếu chưa có."""
        return self._profiles.get(domain, {})  # type: ignore[return-value]

    def has_profile(self, domain: str) -> bool:
        return domain in self._profiles

    def summary(self, domain: str) -> str:
        p = self._profiles.get(domain, {})
        if not p:
            return f"{domain}: no profile"
        content_sel = p.get("working_content_selector") or p.get("content_selector")
        return (
            f"{domain}: {p.get('chapters_scraped', 0)} ch | "
            f"content={content_sel!r} | "
            f"nav_type={p.get('nav_type')!r} | "
            f"ai_fallback={p.get('ai_fallback_count', 0)} | "
            f"wm={len(p.get('domain_watermarks') or [])}kw"  # type: ignore[arg-type]
        )

    def get_domain_watermarks(self, domain: str) -> list[str]:
        """
        Trả về danh sách watermark keywords của domain để inject vào AdsFilter.
        Gọi trong run_novel_task() ngay sau khi AdsFilter.load().
        """
        p = self._profiles.get(domain, {})
        wm = p.get("domain_watermarks")  # type: ignore[misc]
        return list(wm) if isinstance(wm, list) else []

    def get_domain_patterns(self, domain: str) -> list[str]:
        """
        Trả về danh sách regex patterns của domain để inject vào AdsFilter.
        Hiện chưa dùng nhưng chuẩn bị cho tương lai.
        """
        p = self._profiles.get(domain, {})
        # Không có field riêng — trả rỗng, để mở rộng sau
        return []

    # ── Mutating helpers (cần lock) ───────────────────────────────────────────

    def _ensure_profile(self, domain: str) -> SiteProfileDict:
        """Đảm bảo domain có entry trong dict. GỌI BÊN TRONG lock."""
        if domain not in self._profiles:
            self._profiles[domain] = {  # type: ignore[assignment]
                "selector_stats": {},
                "sample_urls": [],
                "domain_watermarks": [],
                "ai_fallback_count": 0,
                "content_extraction_failures": 0,
                "chapters_scraped": 0,
                "profile_version": _PROFILE_VERSION,
            }
        return self._profiles[domain]

    async def record_content_hit(self, domain: str, selector: str) -> None:
        async with self._lock:
            p = self._ensure_profile(domain)
            stats: dict = p.setdefault("selector_stats", {})  # type: ignore[misc]
            if selector not in stats:
                stats[selector] = {"hits": 0, "total_tries": 0}
            stats[selector]["hits"]        = stats[selector].get("hits", 0) + 1
            stats[selector]["total_tries"] = stats[selector].get("total_tries", 0) + 1
            # Promote selector to "working" if not yet set
            if not p.get("working_content_selector"):
                p["working_content_selector"] = selector
            p["last_updated"] = _now_iso()
            self._dirty = True

    async def record_extraction_failure(self, domain: str) -> None:
        async with self._lock:
            p = self._ensure_profile(domain)
            p["content_extraction_failures"] = p.get("content_extraction_failures", 0) + 1
            p["last_updated"] = _now_iso()
            self._dirty = True

    async def record_nav_edges(self, domain: str) -> None:
        async with self._lock:
            p = self._ensure_profile(domain)
            p["has_nav_edges"] = True
            p["last_updated"] = _now_iso()
            self._dirty = True

    async def record_playwright_required(self, domain: str) -> None:
        async with self._lock:
            p = self._ensure_profile(domain)
            p["requires_playwright"] = True
            p["last_updated"] = _now_iso()
            self._dirty = True

    async def record_ai_fallback(self, domain: str) -> None:
        async with self._lock:
            p = self._ensure_profile(domain)
            p["ai_fallback_count"] = p.get("ai_fallback_count", 0) + 1
            p["last_updated"] = _now_iso()
            self._dirty = True

    async def record_chapter_done(self, domain: str, url: str) -> None:
        async with self._lock:
            p = self._ensure_profile(domain)
            p["chapters_scraped"] = p.get("chapters_scraped", 0) + 1
            samples: list[str] = list(p.get("sample_urls") or [])
            if url not in samples:
                samples.append(url)
            p["sample_urls"] = samples[-_SAMPLE_URL_CAP:]
            p["last_updated"] = _now_iso()
            self._dirty = True

    async def update_chapter_url_pattern(self, domain: str, pattern: str) -> None:
        async with self._lock:
            p = self._ensure_profile(domain)
            p["chapter_url_pattern"] = pattern
            p["last_updated"] = _now_iso()
            self._dirty = True

    async def merge_ai_result(self, domain: str, ai_data: dict) -> None:
        """
        Merge kết quả từ ask_ai_build_profile() vào SiteProfileDict.

        Field mapping (AI result → SiteProfileDict):
          next_selector        → next_selector
          title_selector       → title_selector
          content_selector     → content_selector
          nav_type             → nav_type          (không có trong TypedDict nhưng used)
          requires_playwright  → requires_playwright
          chapter_url_regex    → chapter_url_pattern  ← tên khác nhau!
          has_chapter_dropdown → has_chapter_dropdown
          has_rel_next         → has_rel_next
          site_notes / ai_notes → site_notes
          domain_watermarks    → domain_watermarks  ← FIX issue #2: persist để
                                                      get_domain_watermarks() trả về
                                                      cho AdsFilter inject

        NOTE: domain_watermarks KHÔNG override hoàn toàn — merge (union) để
        không mất watermarks đã học trước đó.
        """
        async with self._lock:
            p = self._ensure_profile(domain)

            # ── Selectors ─────────────────────────────────────────────────────
            for field in ("next_selector", "title_selector", "content_selector"):
                val = ai_data.get(field)
                if val and isinstance(val, str):
                    p[field] = val  # type: ignore[literal-required]

            # ── Navigation type ───────────────────────────────────────────────
            nav_type = ai_data.get("nav_type")
            if nav_type and isinstance(nav_type, str):
                p["nav_type"] = nav_type  # type: ignore[typeddict-unknown-key]

            # ── Transport flag ────────────────────────────────────────────────
            if ai_data.get("requires_playwright") is True:
                p["requires_playwright"] = True

            # ── URL pattern (AI dùng "chapter_url_regex", profile dùng "chapter_url_pattern") ──
            pattern = ai_data.get("chapter_url_regex") or ai_data.get("chapter_url_pattern")
            if pattern and isinstance(pattern, str):
                p["chapter_url_pattern"] = pattern

            # ── Behavior flags ────────────────────────────────────────────────
            if ai_data.get("has_chapter_dropdown") is True:
                p["has_chapter_dropdown"] = True
            if ai_data.get("has_rel_next") is True:
                p["has_rel_next"] = True

            # ── Notes ─────────────────────────────────────────────────────────
            notes = ai_data.get("site_notes") or ai_data.get("ai_notes")
            if notes and isinstance(notes, str):
                p["site_notes"] = notes

            # ── Domain watermarks — FIX: persist vào profile ─────────────────
            # Sau khi gọi merge_ai_result, caller (scraper.py) nên gọi:
            #   ads_filter.inject_domain_keywords(pm.get_domain_watermarks(domain))
            # để inject ngay vào phiên hiện tại.
            new_wm = ai_data.get("domain_watermarks")
            if isinstance(new_wm, list) and new_wm:
                existing_wm: list[str] = list(p.get("domain_watermarks") or [])  # type: ignore[misc]
                # Union để không mất watermarks cũ
                merged_set: set[str] = {
                    kw.lower().strip()
                    for kw in (existing_wm + new_wm)
                    if isinstance(kw, str) and kw.strip()
                }
                p["domain_watermarks"] = sorted(merged_set)  # type: ignore[typeddict-unknown-key]
                logger.debug(
                    "[ProfileManager] %s domain_watermarks: %d → %d",
                    domain, len(existing_wm), len(merged_set),
                )

            p["last_updated"] = _now_iso()
            p.setdefault("profile_version", _PROFILE_VERSION)  # type: ignore[misc]
            self._dirty = True

    # ── Persistence ───────────────────────────────────────────────────────────

    async def close(self) -> None:
        """Lưu profiles xuống disk nếu có thay đổi trong phiên."""
        if not self._dirty:
            return
        try:
            async with self._lock:
                await save_profiles(self._profiles)
                self._dirty = False
            logger.debug("[ProfileManager] Profiles saved.")
        except Exception as e:
            logger.error("[ProfileManager] Không lưu được profiles: %s", e)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()