"""
utils/ads_filter.py — v6: Deferred ads confirmation + retroactive file cleanup.

Thay đổi so với v5:
  NEW-1: scan_edges_for_suspects() — quét edges (đầu/cuối) mỗi chương,
         track frequency các dòng LẠ (chưa có trong keywords).
         Không xóa gì cả trong bước này.
  NEW-2: get_new_frequency_suspects() — trả về dòng lạ xuất hiện
         trong ≥ N chapter files khác nhau.
  NEW-3: post_process_directory() — sau khi AI confirm, xóa retroactively
         từ tất cả .md files trong output_dir. Atomic write.
  REMOVE: get_candidates_by_frequency() auto_add tier không còn bypass AI.
          Mọi candidate mới đều phải qua AI trước khi xóa.

Pipeline ads mới:
  [Scraping]
    filter()                  → xóa confirmed keywords ngay (seeds + profile)
    scan_edges_for_suspects() → log dòng lạ edges, KHÔNG xóa
    write_markdown()          → save file với dòng lạ còn nguyên

  [Cuối session]
    get_candidates_by_frequency(min_count=3) → candidates từ session_log
    get_new_frequency_suspects(min_count=5)  → candidates từ edge scan
    ai_verify_ads()                          → AI xác nhận tất cả
    post_process_directory(confirmed, dir)   → xóa retroactively từ files
    add_ads_to_profile()                     → lưu profile cho lần sau
"""
from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from config import ADS_DB_FILE

if TYPE_CHECKING:
    from utils.types import SiteProfile

logger = logging.getLogger(__name__)

_MIN_LINE_LEN   = 15
_ADS_REVIEW_DIR = os.path.join(os.path.dirname(ADS_DB_FILE), "ads_review")

# Suspect edge scan config
_SUSPECT_SCAN_EDGES = 8    # Quét N dòng đầu và N dòng cuối mỗi chapter
_SUSPECT_MAX_LEN    = 250  # Watermarks hiếm khi dài hơn thế này
_SUSPECT_MIN_FILES  = 5    # Xuất hiện trong ≥ N chapter files mới là suspect

# ── Global keywords ───────────────────────────────────────────────────────────
_SEED_GLOBAL_KEYWORDS: list[str] = [
    # Stolen content notices
    "stolen content", "stolen from", "this content is stolen",
    "this chapter is stolen", "has been taken without permission",

    # Author/translation attribution boilerplate
    "please support the author", "support the original",
    "translation by", "mtl by", "machine translated",
    "if you find any errors",

    # Read-at / piracy watermarks
    "read latest chapters at", "read advance chapters at",
    "chapters are updated daily",
    "read at", "read on", "find this novel at",
    "visit to read", "originally published at",

    # Donation / monetization CTAs
    "patreon.com/", "ko-fi.com/",

    # Social share CTAs
    "share to your friends",
    "share this chapter",
    "share this novel",
    "share this story",
    "share on facebook", "share on twitter", "share on reddit",

    # Navigation labels lặp lại
    "previous chapter", "next chapter",
    "table of contents",
]

# ── Per-domain seed keywords ──────────────────────────────────────────────────
_SEED_DOMAIN_KEYWORDS: dict[str, list[str]] = {
    "royalroad.com": [
        "read at royalroad", "read on royalroad",
        "find this and other great novels",
        "keyboard keys to browse between chapters",
        "use left, right keyboard keys",
    ],
    "scribblehub.com": [
        "read at scribblehub", "read on scribblehub",
        "sh-notice",
    ],
    "webnovel.com": [
        "original at webnovel", "read on webnovel",
    ],
    "novelfire.net": [
        "share to your friends",
        "share this chapter",
        "novelfire.net",
        "read at novelfire",
    ],
    "lightnovelreader.me": ["visit lightnovelreader"],
    "novelfull.com"      : ["visit novelfull"],
    "wuxiaworld.com"     : ["visit wuxiaworld"],
    "fanfiction.net"     : ["story text placeholder"],
}

# ── Regex patterns (global) ───────────────────────────────────────────────────
_SEED_PATTERNS_RAW: list[str] = [
    r"^Tip:\s+You can use",
    r"<script[\s>]", r"</script>",
    r"window\.pubfuturetag", r"window\.googletag",
    r"window\.adsbygoogle", r"googletag\.cmd\.push",
    r"pubfuturetag\.push\(",
    r'"unit"\s*:\s*"[^"]+"\s*,\s*"id"\s*:\s*"pf-',
    r"window\.\w+\s*=\s*window\.\w+\s*\|\|\s*\[\]",
    r"p[.\s]*a[.\s]*t[.\s]*r[.\s]*e[.\s]*o[.\s]*n",
    r"b[.\s]*o[.\s]*o[.\s]*s[.\s]*t[.\s]*y",
    r"read\s+\d+\s+chapter[s]?\s+ahead",
    r"chapter[s]?\s+ahead\s+(on|at|over)\s+(my\s+)?",
]

_GENERIC_KEYWORD_BLACKLIST: frozenset[str] = frozenset({
    "search", "log in", "login", "read", "find", "chapter", "story",
    "novel", "series", "book", "text", "content", "page", "link", "click",
    "here", "site", "web", "online", "free",
    "royal road", "royalroad", "fanfiction", "wattpad", "webnovel",
    "scribble", "archive", "ao3",
    "the primal hunter", "monster cultivator", "system", "bloodline",
    "realm", "cultivation", "dungeon", "quest", "skill", "class",
})

# Heuristic: dòng nào khớp pattern này gần như chắc chắn là nội dung truyện
_STORY_LINE_RE = re.compile(
    r'^["""''„]'                          # bắt đầu bằng dấu ngoặc kép (dialogue)
    r'|["""''„]$'                         # kết thúc bằng dấu ngoặc kép
    r'|^(The |A |An |He |She |I |It |'
    r'They |We |You |But |And |Or |'
    r'His |Her |My |Our |Their )',         # narrative starters phổ biến
    re.IGNORECASE,
)


class AdsFilter:
    """
    Lọc ads/watermark bằng keyword và regex.

    Hai tầng hoạt động:
      [Real-time]  filter()                  — xóa confirmed keywords
      [Deferred]   scan_edges_for_suspects() — track dòng lạ edges
      [Post-sess]  get_new_frequency_suspects() + ai_verify + post_process_directory()
    """

    def __init__(self, domain: str | None = None) -> None:
        self._domain = domain

        # Global confirmed keywords/patterns
        self._global_keywords: set[str] = {kw.lower() for kw in _SEED_GLOBAL_KEYWORDS}
        self._global_patterns: list[re.Pattern[str]] = []
        for raw in _SEED_PATTERNS_RAW:
            try:
                self._global_patterns.append(re.compile(raw, re.IGNORECASE))
            except re.error:
                pass

        # Domain-specific confirmed keywords/patterns
        self._domain_keywords: set[str] = set()
        self._domain_patterns: list[re.Pattern[str]] = []
        if domain:
            for key, kws in _SEED_DOMAIN_KEYWORDS.items():
                if key in domain:
                    for kw in kws:
                        self._domain_keywords.add(kw.lower())

        # Session log: tracks lines removed by filter() (confirmed keywords)
        # Used for auditing and learning new variants of known keywords
        self._session_log: list[dict] = []

        # Frequency counter: tracks edge-line appearances across chapters
        # key = line text → {"files": set[filepath], "urls": set[url]}
        # Dùng để phát hiện watermarks MỚI chưa có trong keywords
        self._freq_counter: dict[str, dict] = {}

    # ── Factory ───────────────────────────────────────────────────────────

    @classmethod
    def load(cls, domain: str | None = None) -> "AdsFilter":
        """Load từ file + seed keywords. Tự migrate format cũ."""
        instance = cls(domain)
        if not os.path.exists(ADS_DB_FILE):
            return instance
        try:
            with open(ADS_DB_FILE, "r", encoding="utf-8") as f:
                raw = f.read().strip()
            if not raw:
                return instance
            data = json.loads(raw)
            if "global" in data:
                _load_bucket(data["global"], instance._global_keywords, instance._global_patterns)
                if domain and "domains" in data:
                    for d_key, d_bucket in data["domains"].items():
                        if d_key in domain or domain in d_key:
                            _load_bucket(
                                d_bucket,
                                instance._domain_keywords,
                                instance._domain_patterns,
                            )
            else:
                logger.info("[AdsFilter] Migrating old format → global bucket")
                _load_bucket(data, instance._global_keywords, instance._global_patterns)
        except Exception as e:
            logger.warning("[AdsFilter] Load thất bại: %s", e)
        return instance

    # ── Core filtering (real-time, confirmed keywords only) ───────────────

    def filter(self, text: str, chapter_url: str = "") -> str:
        """
        Xóa các dòng khớp với CONFIRMED keywords/patterns (seeds + profile).
        Log các dòng bị xóa vào session_log để audit.

        KHÔNG xử lý 'dòng lạ mới' — việc đó do scan_edges_for_suspects().
        """
        lines = text.splitlines()
        kept: list[str] = []

        for ln in lines:
            stripped = ln.strip()
            if len(stripped) >= _MIN_LINE_LEN and self._is_ads(ln):
                self._session_log.append({
                    "line"       : stripped,
                    "chapter_url": chapter_url,
                })
            else:
                kept.append(ln)

        # Gộp blank lines thừa
        result: list[str] = []
        blanks = 0
        for ln in kept:
            if not ln.strip():
                blanks += 1
                if blanks <= 1:
                    result.append(ln)
            else:
                blanks = 0
                result.append(ln)
        return "\n".join(result)

    # ── Deferred suspect scanning ─────────────────────────────────────────

    def scan_edges_for_suspects(
        self,
        text          : str,
        chapter_url   : str = "",
        chapter_file  : str = "",
    ) -> None:
        """
        Quét N dòng đầu và N dòng cuối của chapter content.
        Track frequency các dòng ngắn/lạ chưa có trong confirmed keywords.
        KHÔNG xóa bất cứ thứ gì — chỉ ghi nhận để phân tích cuối session.

        Gọi SAU filter() và SAU write_markdown() để scan đúng nội dung đã lưu.

        Args:
            text:         Chapter content đã qua filter() (confirmed ads đã bị xóa)
            chapter_url:  URL chương (để audit)
            chapter_file: Đường dẫn file .md đã save (để post-process sau này)
        """
        lines = [ln for ln in text.splitlines() if ln.strip()]
        n     = len(lines)
        if n == 0:
            return

        edge = min(_SUSPECT_SCAN_EDGES, n // 2 + 1)
        edge_lines = lines[:edge] + lines[max(0, n - edge):]

        seen_this_chapter: set[str] = set()
        for ln in edge_lines:
            stripped = ln.strip()

            # Chỉ quan tâm đến dòng có độ dài hợp lý
            if not (_MIN_LINE_LEN <= len(stripped) <= _SUSPECT_MAX_LEN):
                continue

            # Bỏ qua nếu đã xử lý dòng này trong chapter hiện tại
            # (tránh đếm 2 lần nếu cùng dòng xuất hiện ở cả đầu lẫn cuối)
            if stripped in seen_this_chapter:
                continue
            seen_this_chapter.add(stripped)

            # Bỏ qua nếu đã là confirmed keyword
            lower = stripped.lower()
            if self._is_ads(stripped):
                continue

            # Bỏ qua nếu có dấu hiệu nội dung truyện
            if self._looks_like_story_content(stripped):
                continue

            self._update_freq(stripped, chapter_url, chapter_file)

    def _looks_like_story_content(self, line: str) -> bool:
        """
        Heuristic kiểm tra xem dòng có phải nội dung truyện không.
        Conservative: chỉ loại những dòng RÕ RÀNG là story.
        """
        # Dòng dài thường là nội dung story
        words = line.split()
        if len(words) > 10:
            return True
        # Dialogue / narrative starters phổ biến
        if _STORY_LINE_RE.match(line):
            return True
        return False

    def _update_freq(self, line: str, chapter_url: str, chapter_file: str) -> None:
        """Cập nhật frequency counter. Đếm theo UNIQUE chapter files."""
        if line not in self._freq_counter:
            self._freq_counter[line] = {"files": set(), "urls": set()}
        entry = self._freq_counter[line]
        if chapter_file:
            entry["files"].add(chapter_file)
        if chapter_url:
            entry["urls"].add(chapter_url)

    def get_new_frequency_suspects(
        self,
        min_files: int = _SUSPECT_MIN_FILES,
        max_results: int = 20,
    ) -> list[str]:
        """
        Trả về các dòng xuất hiện trong ≥ min_files chapter files khác nhau
        mà KHÔNG khớp với bất kỳ confirmed keyword nào.

        Đây là watermarks MỚI chưa học được — cần AI xác nhận trước khi xóa.

        Returns:
            List[str] — dòng text, sorted by file count descending.
        """
        suspects: list[tuple[str, int]] = []

        for line, info in self._freq_counter.items():
            file_count = len(info["files"])
            if file_count < min_files:
                continue
            # Double-check: không phải confirmed keyword
            lower = line.lower()
            if (any(kw in lower for kw in self._global_keywords) or
                    any(kw in lower for kw in self._domain_keywords)):
                continue
            suspects.append((line, file_count))

        suspects.sort(key=lambda x: -x[1])
        return [line for line, _ in suspects[:max_results]]

    def get_suspect_file_paths(self, line: str) -> list[str]:
        """Trả về danh sách file paths chứa dòng suspect này."""
        info = self._freq_counter.get(line)
        if not info:
            return []
        return list(info["files"])

    # ── Retroactive file post-processing ─────────────────────────────────

    @staticmethod
    def post_process_directory(
        confirmed_lines: list[str],
        output_dir     : str,
    ) -> int:
        """
        Xóa retroactively các dòng đã được AI xác nhận là ads khỏi tất cả
        .md files trong output_dir.

        Dùng exact stripped-line matching (case-insensitive) để an toàn.
        Atomic write: ghi .tmp rồi os.replace() — tránh corrupt file.

        Args:
            confirmed_lines: Danh sách dòng text đã được AI confirm là ads.
            output_dir:      Thư mục chứa chapter .md files.

        Returns:
            Tổng số dòng đã xóa trên toàn bộ files.
        """
        if not confirmed_lines or not os.path.isdir(output_dir):
            return 0

        confirmed_set = {ln.strip().lower() for ln in confirmed_lines if ln.strip()}
        if not confirmed_set:
            return 0

        total_removed = 0

        for fname in sorted(os.listdir(output_dir)):
            if not fname.endswith(".md"):
                continue
            fpath = os.path.join(output_dir, fname)
            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    raw_lines = f.readlines()

                new_lines    : list[str] = []
                file_removed : int       = 0

                for raw_ln in raw_lines:
                    if raw_ln.strip().lower() in confirmed_set:
                        file_removed += 1
                    else:
                        new_lines.append(raw_ln)

                if file_removed > 0:
                    tmp = fpath + ".tmp"
                    with open(tmp, "w", encoding="utf-8") as f:
                        f.writelines(new_lines)
                    os.replace(tmp, fpath)
                    total_removed += file_removed
                    logger.debug(
                        "[AdsFilter] post_process: -%d lines từ %s",
                        file_removed, fname,
                    )

            except Exception as e:
                logger.warning("[AdsFilter] post_process_directory %s: %s", fname, e)

        return total_removed

    # ── Session log API (từ session_log — confirmed keyword hits) ─────────

    def get_session_summary(self) -> dict[str, dict]:
        """Aggregate session log: line → {count, urls}."""
        summary: dict[str, dict] = {}
        for entry in self._session_log:
            line = entry["line"]
            if line not in summary:
                summary[line] = {"count": 0, "urls": []}
            summary[line]["count"] += 1
            url = entry.get("chapter_url", "")
            if url and url not in summary[line]["urls"]:
                summary[line]["urls"].append(url)
        return summary

    def get_unknown_candidates(
        self,
        min_count  : int = 2,
        max_results: int = 20,
    ) -> list[str]:
        """
        Trả về top N dòng bị filter() xóa mà CHƯA được cover bởi keyword rõ ràng.
        (Các dòng này bị bắt bởi regex pattern, không phải simple keyword.)
        """
        summary    = self.get_session_summary()
        candidates : list[str] = []
        for line, info in sorted(summary.items(), key=lambda x: -x[1]["count"]):
            if info["count"] < min_count:
                continue
            lower = line.lower()
            already_known = (
                any(kw in lower for kw in self._global_keywords) or
                any(kw in lower for kw in self._domain_keywords)
            )
            if already_known:
                continue
            candidates.append(line)
            if len(candidates) >= max_results:
                break
        return candidates

    def get_candidates_by_frequency(
        self,
        auto_threshold: int = 10,
        min_count     : int = 3,
        max_results   : int = 20,
    ) -> tuple[list[str], list[str]]:
        """
        Phân loại session_log candidates theo tần suất:
          auto_add  (count ≥ auto_threshold) → đủ tự tin, không cần AI
          ai_verify (min_count ≤ count < auto_threshold) → cần AI

        NOTE: Cả 2 tầng này đều là từ session_log (confirmed keyword hits).
              Chúng đã bị xóa khỏi files trong real-time.
              Mục đích: học keyword mới cho profile.

        Để phát hiện watermarks MỚI chưa có trong keywords, dùng
        get_new_frequency_suspects() (từ _freq_counter / edge scan).
        """
        summary   = self.get_session_summary()
        auto_add  : list[str] = []
        ai_verify : list[str] = []

        for line, info in sorted(summary.items(), key=lambda x: -x[1]["count"]):
            count = info["count"]
            if count < min_count:
                continue
            lower = line.lower()
            already_known = (
                any(kw in lower for kw in self._global_keywords) or
                any(kw in lower for kw in self._domain_keywords)
            )
            if already_known:
                continue
            if count >= auto_threshold:
                if len(auto_add) < max_results:
                    auto_add.append(line)
            else:
                if len(ai_verify) < max_results:
                    ai_verify.append(line)

        return auto_add, ai_verify

    def clear_session_log(self) -> None:
        self._session_log.clear()

    # ── Inject từ profile ─────────────────────────────────────────────────

    def inject_from_profile(self, profile: "SiteProfile") -> int:
        """Inject ads_keywords_learned từ profile → domain bucket."""
        added = 0
        for kw in profile.get("ads_keywords_learned") or []:
            if not isinstance(kw, str):
                continue
            kw_lower = kw.lower().strip()
            if (kw_lower and
                    kw_lower not in self._global_keywords and
                    kw_lower not in self._domain_keywords):
                self._domain_keywords.add(kw_lower)
                added += 1
        return added

    def add_keywords(self, keywords: list[str], to_domain: bool = True) -> int:
        """
        Thêm keywords mới vào domain bucket (default) hoặc global.
        Skip nếu trong blacklist, quá ngắn, hoặc đã tồn tại.
        """
        added    = 0
        use_domain = to_domain and bool(self._domain)

        for kw in keywords:
            if not isinstance(kw, str):
                continue
            kw_lower = kw.lower().strip()
            if not kw_lower:
                continue
            if kw_lower in _GENERIC_KEYWORD_BLACKLIST:
                logger.debug("[AdsFilter] Skip blacklist: %r", kw_lower)
                continue
            if len(kw_lower) < 8:
                logger.debug("[AdsFilter] Skip too short: %r", kw_lower)
                continue
            if kw_lower in self._global_keywords or kw_lower in self._domain_keywords:
                continue
            if use_domain:
                self._domain_keywords.add(kw_lower)
            else:
                self._global_keywords.add(kw_lower)
            added += 1

        return added

    def apply_verified(self, confirmed_lines: list[str]) -> int:
        """Thêm AI-confirmed lines vào domain keyword bucket."""
        return self.add_keywords(confirmed_lines, to_domain=True)

    # ── Core detection ────────────────────────────────────────────────────

    def _is_ads(self, line: str) -> bool:
        stripped = line.strip()
        if len(stripped) < _MIN_LINE_LEN:
            return False
        lower = stripped.lower()
        for kw in self._global_keywords:
            if kw in lower:
                return True
        for kw in self._domain_keywords:
            if kw in lower:
                return True
        for pat in self._global_patterns:
            if pat.search(stripped):
                return True
        for pat in self._domain_patterns:
            if pat.search(stripped):
                return True
        return False

    # ── Save/Load DB ──────────────────────────────────────────────────────

    def save(self) -> None:
        """Lưu tất cả keywords/patterns xuống file (merge, không overwrite domain khác)."""
        existing: dict = {"global": {"keywords": [], "patterns": []}, "domains": {}}
        if os.path.exists(ADS_DB_FILE):
            try:
                with open(ADS_DB_FILE, "r", encoding="utf-8") as f:
                    raw = json.load(f)
                if "global" in raw:
                    existing = raw
                else:
                    existing["global"]["keywords"] = raw.get("keywords", [])
                    existing["global"]["patterns"] = raw.get("patterns", [])
            except Exception:
                pass

        existing.setdefault("global",  {"keywords": [], "patterns": []})
        existing.setdefault("domains", {})

        g_kws = set(existing["global"].get("keywords", []))
        g_kws.update(self._global_keywords)
        existing["global"]["keywords"] = sorted(g_kws)

        g_pats = set(existing["global"].get("patterns", []))
        g_pats.update(p.pattern for p in self._global_patterns)
        existing["global"]["patterns"] = sorted(g_pats)

        if self._domain and (self._domain_keywords or self._domain_patterns):
            if self._domain not in existing["domains"]:
                existing["domains"][self._domain] = {"keywords": [], "patterns": []}
            d = existing["domains"][self._domain]
            d_kws = set(d.get("keywords", []))
            d_kws.update(self._domain_keywords)
            d["keywords"] = sorted(d_kws)
            d_pats = set(d.get("patterns", []))
            d_pats.update(p.pattern for p in self._domain_patterns)
            d["patterns"] = sorted(d_pats)

        os.makedirs(os.path.dirname(ADS_DB_FILE) or ".", exist_ok=True)
        tmp = ADS_DB_FILE + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(existing, f, ensure_ascii=False, indent=2)
            os.replace(tmp, ADS_DB_FILE)
        except Exception as e:
            logger.error("[AdsFilter] Lưu thất bại: %s", e)
            try:
                if os.path.exists(tmp):
                    os.remove(tmp)
            except Exception:
                pass

    # ── Persistent review file ────────────────────────────────────────────

    def save_pending_review(
        self,
        domain_slug     : str,
        verified_results: dict[str, bool] | None = None,
    ) -> str | None:
        """Merge session log vào file review bền vững."""
        summary = self.get_session_summary()
        if not summary:
            return None

        os.makedirs(_ADS_REVIEW_DIR, exist_ok=True)
        review_path = os.path.join(_ADS_REVIEW_DIR, f"{domain_slug}_pending.json")

        existing: dict[str, dict] = {}
        if os.path.exists(review_path):
            try:
                with open(review_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                for entry in data.get("entries", []):
                    existing[entry["line"]] = entry
            except Exception:
                pass

        now_iso = datetime.now(timezone.utc).isoformat()
        for line, info in summary.items():
            verified = (verified_results or {}).get(line)
            if line in existing:
                existing[line]["count"] += info["count"]
                for url in info["urls"]:
                    if url not in existing[line].get("story_urls", []):
                        existing[line].setdefault("story_urls", []).append(url)
                if verified is not None:
                    existing[line]["ai_verified"] = verified
                    existing[line]["verified_at"] = now_iso
            else:
                entry: dict = {
                    "line"      : line,
                    "count"     : info["count"],
                    "story_urls": info["urls"],
                    "ai_verified": verified,
                }
                if verified is not None:
                    entry["verified_at"] = now_iso
                existing[line] = entry

        output = {
            "domain"      : self._domain,
            "last_updated": now_iso,
            "entries"     : sorted(
                existing.values(),
                key=lambda x: x["count"],
                reverse=True,
            ),
        }
        tmp = review_path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(output, f, ensure_ascii=False, indent=2)
            os.replace(tmp, review_path)
            return review_path
        except Exception as e:
            logger.error("[AdsFilter] save_pending_review thất bại: %s", e)
            try:
                os.remove(tmp)
            except Exception:
                pass
            return None

    @property
    def stats(self) -> str:
        total_kw  = len(self._global_keywords) + len(self._domain_keywords)
        total_pat = len(self._global_patterns)  + len(self._domain_patterns)
        freq_cnt  = len(self._freq_counter)
        if self._domain:
            return (
                f"{total_kw}kw "
                f"({len(self._global_keywords)}g+{len(self._domain_keywords)}local)"
                f"/{total_pat}pat | {freq_cnt} tracked"
            )
        return f"{total_kw}kw/{total_pat}pat | {freq_cnt} tracked"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _load_bucket(
    bucket  : dict,
    kw_set  : set[str],
    pat_list: list[re.Pattern[str]],
) -> None:
    for kw in bucket.get("keywords", []):
        if isinstance(kw, str):
            kw_lower = kw.lower().strip()
            if kw_lower:
                kw_set.add(kw_lower)
    for pat in bucket.get("patterns", []):
        if isinstance(pat, str) and pat.strip():
            try:
                pat_list.append(re.compile(pat.strip(), re.IGNORECASE))
            except re.error:
                pass