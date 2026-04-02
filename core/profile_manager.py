# core/profile_manager.py
"""
core/profile_manager.py — Thread-safe wrapper quản lý site profiles.

CHANGES (v4):
  merge_calibration_fixes(): Apply kết quả từ ask_ai_calibration_review().
    Không có confidence threshold — fixes dựa trên evidence cụ thể từ probe.
    Reset working_content_selector khi content_selector thay đổi.

CHANGES (v3 — observation-based refinement):
  record_observation(): Lưu StructuralObservation vào profile.observations.
    Trim list xuống OBS_MAX_STORED nhưng observation_count là monotonic.

  should_refine(): Kiểm tra điều kiện trigger AI refinement.
    True nếu: chưa refine + đủ chapters + đủ observations.

  get_observations_summary(): Format observations thành text để gửi AI.
    Aggregate theo: content selector stats, title struct patterns, nav patterns.

  merge_refined_result(): Apply kết quả từ ask_ai_refine_profile().
    Chỉ update field nếu AI confident >= threshold (mặc định OBS_CONFIDENCE_MIN).
    Không bao giờ override field đang work tốt với selector kém confidence.

  mark_refined(): Set profile_refined=True + refined_at_chapter.
    Ngăn trigger lại trên domain đó trong các session sau.
"""
from __future__ import annotations

import asyncio
import logging
from collections import Counter
from datetime import datetime, timezone

from config import OBS_REFINE_AFTER, OBS_MIN_OBSERVATIONS, OBS_MAX_STORED
from utils.file_io import save_profiles
from utils.types import SiteProfileDict, StructuralObservation

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
        return self._profiles.get(domain, {})  # type: ignore[return-value]

    def has_profile(self, domain: str) -> bool:
        return domain in self._profiles

    def summary(self, domain: str) -> str:
        p = self._profiles.get(domain, {})
        if not p:
            return f"{domain}: no profile"
        content_sel = p.get("working_content_selector") or p.get("content_selector")
        obs_count   = p.get("observation_count", 0)
        refined     = "✓" if p.get("profile_refined") else f"{obs_count}/{OBS_REFINE_AFTER}"
        return (
            f"{domain}: {p.get('chapters_scraped', 0)} ch | "
            f"content={content_sel!r} | "
            f"nav_type={p.get('nav_type')!r} | "
            f"ai_fallback={p.get('ai_fallback_count', 0)} | "
            f"obs={refined} | "
            f"wm={len(p.get('domain_watermarks') or [])}kw"
        )

    def get_domain_watermarks(self, domain: str) -> list[str]:
        p  = self._profiles.get(domain, {})
        wm = p.get("domain_watermarks")
        return list(wm) if isinstance(wm, list) else []

    def get_domain_patterns(self, domain: str) -> list[str]:
        return []

    def should_refine(self, domain: str, chapter_count: int) -> bool:
        """
        Kiểm tra xem có nên trigger AI refinement không.

        Điều kiện (TẤT CẢ phải đúng):
          1. Profile chưa được refined trước đó (profile_refined = False)
          2. Đã scrape đủ OBS_REFINE_AFTER chương
          3. Đã tích lũy đủ OBS_MIN_OBSERVATIONS observations hợp lệ
        """
        p = self._profiles.get(domain, {})
        if p.get("profile_refined"):
            return False
        if chapter_count < OBS_REFINE_AFTER:
            return False
        if p.get("observation_count", 0) < OBS_MIN_OBSERVATIONS:
            return False
        return True

    def get_observations_summary(self, domain: str) -> str:
        """
        Tổng hợp observations thành text để gửi cho ask_ai_refine_profile().
        """
        p         = self._profiles.get(domain, {})
        obs_list  = list(p.get("observations") or [])
        total     = len(obs_list)

        if total == 0:
            return f"Domain: {domain}\nNo observations."

        content_sel_counts:    Counter = Counter()
        content_struct_counts: Counter = Counter()

        for obs in obs_list:
            sel = obs.get("content_selector_hit")
            if sel:
                content_sel_counts[sel] += 1

            tag = obs.get("content_tag")
            eid = obs.get("content_id")
            cls = obs.get("content_classes") or []
            if tag:
                sig = tag
                if eid:
                    sig += f"#{eid}"
                elif cls:
                    sig += "." + ".".join(cls[:2])
                content_struct_counts[sig] += 1

        title_source_counts: Counter = Counter()
        title_struct_counts: Counter = Counter()

        for obs in obs_list:
            src = obs.get("title_source")
            if src:
                title_source_counts[src] += 1

            tag = obs.get("title_tag")
            eid = obs.get("title_id")
            cls = obs.get("title_classes") or []
            if tag:
                sig = tag
                if eid:
                    sig += f"#{eid}"
                elif cls:
                    sig += "." + ".".join(cls[:2])
                title_struct_counts[sig] += 1

        nav_counts: Counter = Counter()

        for obs in obs_list:
            rel = obs.get("nav_next_rel")
            cls = obs.get("nav_next_classes") or []
            tag = obs.get("nav_next_tag")

            if rel == "next":
                nav_counts[f'{tag}[rel="next"]'] += 1
            elif cls:
                nav_counts[f"{tag}.{cls[0]}"] += 1
            elif tag:
                nav_counts[tag] += 1

        lines: list[str] = [
            f"Domain: {domain}",
            f"Chapters observed: {total}",
        ]

        lines.append("\n=== CONTENT ELEMENT ===")
        if content_sel_counts:
            lines.append("Selectors that successfully extracted content:")
            for sel, cnt in content_sel_counts.most_common(4):
                pct = int(cnt / total * 100)
                lines.append(f"  {sel!r}: {cnt}/{total} ({pct}%)")
        if content_struct_counts:
            lines.append("DOM structure of content element:")
            for sig, cnt in content_struct_counts.most_common(3):
                lines.append(f"  <{sig}>: {cnt}/{total}")
        if not content_sel_counts and not content_struct_counts:
            lines.append("  (no consistent content element found)")

        lines.append("\n=== TITLE ELEMENT ===")
        if title_source_counts:
            lines.append("Title extraction sources:")
            for src, cnt in title_source_counts.most_common(4):
                lines.append(f"  {src}: {cnt}/{total}")
        if title_struct_counts:
            lines.append("DOM structure of title element:")
            for sig, cnt in title_struct_counts.most_common(3):
                lines.append(f"  <{sig}>: {cnt}/{total}")
        if not title_source_counts and not title_struct_counts:
            lines.append("  (title source not consistently found)")

        lines.append("\n=== NAV NEXT ===")
        if nav_counts:
            for sig, cnt in nav_counts.most_common(3):
                pct = int(cnt / total * 100)
                lines.append(f"  {sig}: {cnt}/{total} ({pct}%)")
        else:
            lines.append("  (no consistent nav-next element found)")

        lines.append("\n=== CURRENT PROFILE ===")
        lines.append(f"  content_selector (AI): {p.get('content_selector')!r}")
        lines.append(f"  working_content_selector: {p.get('working_content_selector')!r}")
        lines.append(f"  title_selector: {p.get('title_selector')!r}")
        lines.append(f"  next_selector: {p.get('next_selector')!r}")
        lines.append(f"  nav_type: {p.get('nav_type')!r}")

        return "\n".join(lines)

    # ── Mutating helpers ──────────────────────────────────────────────────────

    def _ensure_profile(self, domain: str) -> SiteProfileDict:
        if domain not in self._profiles:
            self._profiles[domain] = {  # type: ignore[assignment]
                "selector_stats":               {},
                "sample_urls":                  [],
                "domain_watermarks":            [],
                "observations":                 [],
                "observation_count":            0,
                "profile_refined":              False,
                "ai_fallback_count":            0,
                "content_extraction_failures":  0,
                "chapters_scraped":             0,
                "profile_version":              _PROFILE_VERSION,
            }
        return self._profiles[domain]

    async def record_observation(
        self,
        domain: str,
        obs: StructuralObservation,
    ) -> None:
        async with self._lock:
            p    = self._ensure_profile(domain)
            obs_list: list = list(p.get("observations") or [])
            obs_list.append(dict(obs))
            p["observations"]      = obs_list[-OBS_MAX_STORED:]    # type: ignore[typeddict-unknown-key]
            p["observation_count"] = p.get("observation_count", 0) + 1  # type: ignore[typeddict-unknown-key]
            self._dirty = True

    async def merge_refined_result(
        self,
        domain: str,
        refined: dict,
        threshold: float = 0.8,
    ) -> int:
        updated = 0
        async with self._lock:
            p = self._ensure_profile(domain)

            field_pairs = [
                ("content_selector", "content_confidence"),
                ("title_selector",   "title_confidence"),
                ("next_selector",    "next_confidence"),
            ]
            for sel_key, conf_key in field_pairs:
                new_val = refined.get(sel_key)
                conf    = float(refined.get(conf_key, 0.0))

                if not new_val or not isinstance(new_val, str):
                    continue
                if conf < threshold:
                    logger.debug(
                        "[ProfileManager] %s %s skip (conf=%.2f < %.2f)",
                        domain, sel_key, conf, threshold,
                    )
                    continue

                if sel_key == "content_selector":
                    working = p.get("working_content_selector")
                    if working and working != new_val and conf < 0.9:
                        logger.debug(
                            "[ProfileManager] %s: keep working_content_selector %r (conf=%.2f)",
                            domain, working, conf,
                        )
                        continue

                old_val = p.get(sel_key)  # type: ignore[literal-required]
                if old_val != new_val:
                    p[sel_key] = new_val  # type: ignore[literal-required]
                    updated += 1
                    logger.info(
                        "[ProfileManager] %s %s: %r → %r (conf=%.2f)",
                        domain, sel_key, old_val, new_val, conf,
                    )

            if updated > 0:
                notes = refined.get("notes")
                if notes and isinstance(notes, str):
                    existing = p.get("site_notes") or ""
                    p["site_notes"] = (existing + f"\n[refined] {notes}").strip()
                p["last_updated"] = _now_iso()
                self._dirty = True

        return updated

    async def merge_calibration_fixes(self, domain: str, fixes: dict) -> int:
        """
        Apply kết quả từ ask_ai_calibration_review() vào SiteProfileDict.

        Khác merge_refined_result(): KHÔNG có confidence threshold —
        fixes dựa trên evidence cụ thể từ probe, không phải inference.

        Reset working_content_selector khi content_selector thay đổi
        để round tiếp theo re-learn từ selector mới.

        Returns: số fields thực sự được update.
        """
        updated = 0
        async with self._lock:
            p = self._ensure_profile(domain)

            # Selectors — apply trực tiếp nếu có giá trị
            for field in ("content_selector", "next_selector", "title_selector"):
                val = fixes.get(field)
                if val and isinstance(val, str) and val.strip():
                    if p.get(field) != val:  # type: ignore[literal-required]
                        old = p.get(field)   # type: ignore[literal-required]
                        p[field] = val       # type: ignore[literal-required]
                        updated += 1
                        logger.info(
                            "[ProfileManager] cal-fix %s %s: %r → %r",
                            domain, field, old, val,
                        )

            # Nếu content_selector thay đổi → reset working_content_selector
            # để round sau re-learn từ selector mới
            if fixes.get("content_selector"):
                new_cs = fixes["content_selector"]
                if new_cs != p.get("working_content_selector"):
                    p["working_content_selector"] = None  # type: ignore[typeddict-unknown-key]
                    logger.debug(
                        "[ProfileManager] %s: reset working_content_selector", domain
                    )

            # nav_type
            nav_type = fixes.get("nav_type")
            if nav_type and isinstance(nav_type, str):
                p["nav_type"] = nav_type  # type: ignore[typeddict-unknown-key]
                updated += 1

            # has_nav_edges
            if fixes.get("has_nav_edges") is True and not p.get("has_nav_edges"):
                p["has_nav_edges"] = True
                updated += 1

            # domain_watermarks — merge, không replace
            new_wm = fixes.get("domain_watermarks")
            if isinstance(new_wm, list) and new_wm:
                existing: list[str] = list(p.get("domain_watermarks") or [])
                merged: set[str] = {
                    kw.lower().strip()
                    for kw in (existing + new_wm)
                    if isinstance(kw, str) and kw.strip()
                }
                p["domain_watermarks"] = sorted(merged)  # type: ignore[typeddict-unknown-key]
                updated += 1

            if updated > 0:
                notes = fixes.get("notes")
                if notes and isinstance(notes, str):
                    existing_notes = p.get("site_notes") or ""
                    p["site_notes"] = (existing_notes + f"\n[cal-fix] {notes}").strip()
                p["last_updated"] = _now_iso()
                self._dirty = True

        return updated

    async def mark_refined(self, domain: str, chapter_count: int) -> None:
        async with self._lock:
            p = self._ensure_profile(domain)
            p["profile_refined"]    = True  # type: ignore[typeddict-unknown-key]
            p["refined_at_chapter"] = chapter_count  # type: ignore[typeddict-unknown-key]
            p["last_updated"]       = _now_iso()
            self._dirty = True

    async def record_content_hit(self, domain: str, selector: str) -> None:
        async with self._lock:
            p = self._ensure_profile(domain)
            stats: dict = p.setdefault("selector_stats", {})  # type: ignore[misc]
            if selector not in stats:
                stats[selector] = {"hits": 0, "total_tries": 0}
            stats[selector]["hits"]        = stats[selector].get("hits", 0) + 1
            stats[selector]["total_tries"] = stats[selector].get("total_tries", 0) + 1
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
        async with self._lock:
            p = self._ensure_profile(domain)

            for field in ("next_selector", "title_selector", "content_selector"):
                val = ai_data.get(field)
                if val and isinstance(val, str):
                    p[field] = val  # type: ignore[literal-required]

            nav_type = ai_data.get("nav_type")
            if nav_type and isinstance(nav_type, str):
                p["nav_type"] = nav_type  # type: ignore[typeddict-unknown-key]

            if ai_data.get("requires_playwright") is True:
                p["requires_playwright"] = True

            pattern = ai_data.get("chapter_url_regex") or ai_data.get("chapter_url_pattern")
            if pattern and isinstance(pattern, str):
                p["chapter_url_pattern"] = pattern

            if ai_data.get("has_chapter_dropdown") is True:
                p["has_chapter_dropdown"] = True
            if ai_data.get("has_rel_next") is True:
                p["has_rel_next"] = True

            notes = ai_data.get("site_notes") or ai_data.get("ai_notes")
            if notes and isinstance(notes, str):
                p["site_notes"] = notes

            new_wm = ai_data.get("domain_watermarks")
            if isinstance(new_wm, list) and new_wm:
                existing_wm: list[str] = list(p.get("domain_watermarks") or [])  # type: ignore[misc]
                merged_set: set[str] = {
                    kw.lower().strip()
                    for kw in (existing_wm + new_wm)
                    if isinstance(kw, str) and kw.strip()
                }
                p["domain_watermarks"] = sorted(merged_set)  # type: ignore[typeddict-unknown-key]

            p["last_updated"] = _now_iso()
            p.setdefault("profile_version", _PROFILE_VERSION)  # type: ignore[misc]
            self._dirty = True

    # ── Persistence ───────────────────────────────────────────────────────────

    async def close(self) -> None:
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