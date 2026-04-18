from __future__ import annotations

import json
import logging
import os
import re
import threading
from collections import Counter
from pathlib import Path

from config import ADS_DB_FILE
from utils.string_helpers import is_valid_ads_keyword as _is_valid_ads_keyword

logger = logging.getLogger(__name__)

_MIN_LINE_LEN = 10
_MAX_LINE_LEN = 300

# FIX-ADSSAVE: module-level threading lock cho save().
_ADS_SAVE_LOCK = threading.Lock()

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

        return cls(domain=domain, known_keywords=global_kws | domain_kws)

    def inject_from_profile(self, profile: dict) -> int:
        kws = profile.get("ads_keywords_learned") or []
        before = len(self._keywords)
        for kw in kws:
            if isinstance(kw, str) and kw.strip() and _is_valid_ads_keyword(kw):
                self._keywords.add(kw.lower().strip())
        return len(self._keywords) - before

    # ── Filtering ─────────────────────────────────────────────────────────────

    def filter(self, content: str, chapter_url: str = "") -> str:
        if not self._keywords:
            return content

        lines   = content.splitlines()
        cleaned = []
        for line in lines:
            lo = line.lower().strip()
            if lo and any(kw in lo for kw in self._keywords):
                logger.debug("[Ads] Filtered: %r", line[:80])
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
