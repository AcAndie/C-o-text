from __future__ import annotations

import json
import logging
import os
import re
import threading
from collections import Counter

from config import ADS_DB_FILE
from utils.string_helpers import is_valid_ads_keyword as _is_valid_ads_keyword

logger = logging.getLogger(__name__)

_MIN_LINE_LEN = 10
_MAX_LINE_LEN = 300

# FIX-ADSSAVE: module-level threading lock cho save().
_ADS_SAVE_LOCK = threading.Lock()

# ADS-RR-BUILTIN (v1.0.2): pre-seed known site-specific watermarks. AdsFilter
# auto-learning needs ≥10 cross-chapter occurrences before adding a keyword;
# user wouldn't see protection until chapter 10+. Pre-seed common boilerplate
# so Pass 1 filter catches from chapter 1.
#
# Keys = canonical domain (with/without www variants both apply via load()).
# Values = lowercase substring fragments. Filter does `kw in line.lower()`,
# so fragments must be unique enough not to false-positive on real prose.
_BUILTIN_DOMAIN_WATERMARKS: dict[str, list[str]] = {
    # Substring fragments kept for backward compat. Most RR watermarks now
    # caught by _BUILTIN_DOMAIN_WATERMARK_PATTERNS below (regex, covers
    # rotated variants without enumerating each phrase).
    "royalroad.com": [
        "support the author by reading on royal road",
        "read the original on royal road",
        "royal road is the home of this novel",
        "royal road as an amazon associate",
    ],
}


# ADS-RR-REGEX (v1.0.2): RR rotates anti-piracy watermark through ~20 phrase
# variants. All share signature: "amazon" within ~80 chars of an attribution
# verb (stolen/taken/pilfered/permission/consent/...) OR "royal road" within
# ~80 chars of same verb. Regex catches all variants without per-phrase
# enumeration. Real prose almost never co-locates these terms.
_BUILTIN_DOMAIN_WATERMARK_PATTERNS: dict[str, list[re.Pattern]] = {
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

class AdsFilter:

    def __init__(self, domain: str, known_keywords: set[str]) -> None:
        self._domain   = domain
        self._keywords : set[str] = known_keywords
        # Batch C: chỉ giữ edge suspects (_suspects + _file_counter).
        # Đã bỏ _inline_file_counter — inline watermark tracking (ADS-A)
        # là phức tạp, edge case, và 1.5× weighting gây noise hơn signal.
        self._suspects     : Counter = Counter()
        self._file_counter : Counter = Counter()
        self._pending_review: dict = {}
        self._new_suspects : set[str] = set()
        # ADS-RR-REGEX (v1.0.2): pre-compiled regex patterns for known site
        # rotating watermarks. Filter applies these IN ADDITION to substring
        # kws to catch variant phrasings without per-phrase enumeration.
        canonical = domain.lower().removeprefix("www.").removeprefix("epub:").removeprefix("txt:")
        self._regex_patterns: list[re.Pattern] = list(
            _BUILTIN_DOMAIN_WATERMARK_PATTERNS.get(canonical, [])
        )

    # ── Factory ───────────────────────────────────────────────────────────────

    @classmethod
    def load(cls, domain: str) -> "AdsFilter":
        global_kws: set[str] = set()
        domain_kws: set[str] = set()

        if os.path.exists(ADS_DB_FILE):
            try:
                with open(ADS_DB_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    global_kws = set(data.get("global", []))
                    domain_kws = set(data.get(domain, []))
            except Exception as e:
                logger.warning("[Ads] load failed: %s", e)

        # ADS-RR-BUILTIN: merge builtin site-specific watermarks (strip www. for
        # lookup). Domain key normalize to handle "royalroad.com" and
        # "www.royalroad.com" both matching the builtin entry.
        canonical = domain.lower().removeprefix("www.")
        builtin_kws = set(_BUILTIN_DOMAIN_WATERMARKS.get(canonical, []))

        return cls(
            domain         = domain,
            known_keywords = global_kws | domain_kws | builtin_kws,
        )

    def inject_from_profile(self, profile: dict) -> int:
        kws = profile.get("ads_keywords_learned") or []
        before = len(self._keywords)
        for kw in kws:
            if isinstance(kw, str) and kw.strip() and _is_valid_ads_keyword(kw):
                self._keywords.add(kw.lower().strip())
        return len(self._keywords) - before

    # ── Filtering ─────────────────────────────────────────────────────────────

    def filter(self, content: str, chapter_url: str = "") -> str:
        if not self._keywords and not self._regex_patterns:
            return content

        lines   = content.splitlines()
        cleaned = []
        for line in lines:
            lo = line.lower().strip()
            if not lo:
                cleaned.append(line)
                continue
            # Substring kws (cross-chapter learned + builtin exact phrases)
            if any(kw in lo for kw in self._keywords):
                logger.debug("[Ads] Filtered (kw): %r", line[:80])
                continue
            # Regex patterns (builtin rotating watermarks per-domain)
            if any(p.search(line) for p in self._regex_patterns):
                logger.debug("[Ads] Filtered (regex): %r", line[:80])
                continue
            cleaned.append(line)

        return "\n".join(cleaned)

    def scan_edges_for_suspects(
        self,
        content     : str,
        chapter_url : str = "",
        chapter_file: str = "",
    ) -> None:
        """Quét đầu/cuối chapter để tìm suspect lines."""
        lines = [l.strip() for l in content.splitlines() if l.strip()]
        if not lines:
            return

        edge = min(5, len(lines))
        candidates = lines[:edge] + lines[-edge:]

        for line in candidates:
            lo = line.lower()
            if _MIN_LINE_LEN <= len(lo) <= _MAX_LINE_LEN:
                if lo not in self._keywords and _is_valid_ads_keyword(lo):
                    self._suspects[lo] += 1
                    self._file_counter[lo] += 1

    # ── Candidate retrieval ───────────────────────────────────────────────────

    def get_candidates_by_frequency(
        self,
        auto_threshold: int = 10,
        min_count     : int = 3,
        max_results   : int = 20,
    ) -> tuple[list[str], list[str]]:
        """
        Returns (auto_candidates, ai_candidates).

        Batch C: Bỏ inline 1.5× weighting — chỉ dùng edge suspects trực tiếp.
        """
        auto: list[str] = []
        ai  : list[str] = []

        for line, count in self._suspects.most_common(max_results * 2):
            if line in self._keywords:
                continue
            if count >= auto_threshold:
                auto.append(line)
            elif count >= min_count:
                ai.append(line)
            if len(auto) + len(ai) >= max_results:
                break

        return auto[:max_results], ai[:max_results]

    def get_new_frequency_suspects(
        self,
        min_files  : int = 5,
        max_results: int = 20,
    ) -> list[str]:
        """
        Lines xuất hiện trong >= min_files chapters, chưa confirmed.

        Batch C: Bỏ inline threshold logic — chỉ dùng _file_counter.
        """
        result: list[str] = []
        seen  : set[str]  = set()

        for line, count in self._file_counter.most_common():
            if line in self._keywords or line in seen:
                continue
            if count >= min_files:
                seen.add(line)
                result.append(line)
                self._new_suspects.add(line)
            if len(result) >= max_results:
                break

        return result[:max_results]

    # ── Applying verified results ─────────────────────────────────────────────

    def apply_verified(self, lines: list[str]) -> int:
        """
        Thêm confirmed ads lines vào _keywords.

        FIX-ADSSAVE: Apply _is_valid_ads_keyword() để ngăn script tags
        và HTML được học vào keyword set.
        """
        added = 0
        for line in lines:
            lo = line.lower().strip()
            if lo and lo not in self._keywords and _is_valid_ads_keyword(lo):
                self._keywords.add(lo)
                added += 1
        return added

    def save_pending_review(
        self,
        domain_slug     : str,
        verified_results: dict | None = None,
    ) -> None:
        if verified_results:
            self._pending_review.update(verified_results)

    # ── Persistence ───────────────────────────────────────────────────────────

    def save(self) -> None:
        """
        Ghi ads keywords xuống disk.

        FIX-ADSSAVE: Dùng _ADS_SAVE_LOCK (threading.Lock) và atomic write
        để tránh concurrent corruption khi nhiều domain tasks save() đồng thời.
        """
        try:
            os.makedirs(os.path.dirname(os.path.abspath(ADS_DB_FILE)), exist_ok=True)
            with _ADS_SAVE_LOCK:
                data: dict = {}
                if os.path.exists(ADS_DB_FILE):
                    try:
                        with open(ADS_DB_FILE, "r", encoding="utf-8") as f:
                            loaded = json.load(f)
                        if isinstance(loaded, dict):
                            data = loaded
                    except (json.JSONDecodeError, OSError) as e:
                        logger.warning("[Ads] ads_keywords.json corrupt, resetting: %s", e)

                existing  = set(data.get(self._domain, []))
                valid_kws = {kw for kw in self._keywords if _is_valid_ads_keyword(kw)}
                merged    = sorted(existing | valid_kws)
                data[self._domain] = merged

                tmp = ADS_DB_FILE + ".tmp"
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                os.replace(tmp, ADS_DB_FILE)

        except Exception as e:
            logger.warning("[Ads] save failed: %s", e)

    @property
    def stats(self) -> str:
        return (
            f"known={len(self._keywords)} "
            f"edge_suspects={len(self._suspects)}"
        )

    # ── Post-processing ───────────────────────────────────────────────────────

    @staticmethod
    def post_process_directory(confirmed_lines: list[str], output_dir: str) -> int:
        if not confirmed_lines or not os.path.isdir(output_dir):
            return 0

        patterns = [line.lower().strip() for line in confirmed_lines if line.strip()]
        total_removed = 0

        for fname in os.listdir(output_dir):
            if not fname.endswith(".md"):
                continue
            fpath = os.path.join(output_dir, fname)
            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    lines = f.readlines()

                cleaned  = [l for l in lines if not any(p in l.lower() for p in patterns)]
                removed  = len(lines) - len(cleaned)

                if removed > 0:
                    with open(fpath, "w", encoding="utf-8", newline="\n") as f:
                        f.writelines(cleaned)
                    total_removed += removed

            except Exception as e:
                logger.debug("[Ads] post_process error on %s: %s", fname, e)

        return total_removed
