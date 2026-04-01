# utils/ads_filter.py
"""
utils/ads_filter.py — Lightweight ads/watermark filter cho plain-text content.

BUG-3 FIX: Bổ sung seed keywords cho UI elements của novelfire.net và các
  aggregator site tương tự. Các dòng junk hay gặp ở cuối chương:
    "Share to your friends"
    "Tip: You can use left, right keyboard keys to browse between chapters."
    "If you find any errors (non-standard content, ads redirect...), Please let us know"
    "Report"  ← dưới _MIN_SUSPICIOUS_LINE_LEN, không cần keyword
  Thêm cả regex pattern để bắt biến thể.
"""
from __future__ import annotations

import json
import logging
import re

logger = logging.getLogger(__name__)

_SEED_KEYWORDS: list[str] = [
    # Generic stolen-content notice
    "stolen content",
    "stolen from",
    "this content is stolen",
    "this chapter is stolen",
    "this chapter was stolen",
    "this work has been stolen",
    "if you come across this story",
    "if you find this content",
    "this story has been stolen",
    "has been taken without permission",
    "taken without permission",

    # Site-specific "read at original"
    "read at royalroad",
    "read on royalroad",
    "read the original at",
    "read the original on",
    "original source",
    "find this and other great novels",
    "check out the original",
    "visit the original",

    # Support author
    "please support the author",
    "support the original",
    "support the original author",

    # "More at" aggregator links
    "for more, visit",
    "more chapters at",
    "read more at",

    # Monetization / donation links
    "patreon.com/",
    "ko-fi.com/",
    "buymeacoffee.com/",

    # ScribbleHub / Webnovel specific
    "read at scribblehub",
    "read on scribblehub",
    "original at webnovel",
    "read on webnovel",

    # Wattpad
    "read on wattpad",
    "find this story on wattpad",

    # Amazon / Kindle re-post notice
    "if you encounter this story on amazon",
    "encounter this story on amazon",
    "found on amazon, report it",

    # ── BUG-3 FIX: NovelFire / aggregator site UI elements ────────────────────
    # Các dòng này xuất hiện ở cuối chương do content_selector quá rộng,
    # bao gồm cả phần navigation/footer của site.

    # NovelFire social share bar
    "share to your friends",
    "share this chapter",
    "share this novel",

    # NovelFire / generic keyboard navigation tip
    "keyboard keys to browse between chapters",
    "use left, right keyboard keys",
    "you can use left, right",
    "left, right keyboard keys to browse",

    # NovelFire error report footer
    "if you find any errors",
    "non-standard content, ads redirect",
    "please let us know so we can fix",
    "let us know so we can fix it",

    # Translation credit lines (aggregator MTL sites)
    "translate by",
    "translation by",
    "translated by system",
    "mtl by",
    "machine translated by",
    "raw source:",

    # Generic aggregator footer
    "chapters are updated daily",
    "visit lightnovelreader",
    "visit novelfull",
    "visit wuxiaworld",
    "visit gravitytales",
    "read latest chapters at",
    "read advance chapters at",
    "for more chapters,",
]

_MIN_SUSPICIOUS_LINE_LEN = 15
_CONTEXT_WINDOW          = 10
_MAX_CONTEXT_BLOCKS      = 5

# ── BUG-3 FIX: Seed regex patterns cho UI elements ───────────────────────────
# Compile sẵn để tránh re-compile mỗi lần check.
_SEED_PATTERNS_RAW: list[str] = [
    # "Tip: You can use ..." — novelfire navigation hint
    r"^Tip:\s+You can use",
    # "Chapter N - Title" lặp lại ở cuối (navigation element)
    # Chỉ match khi ở cuối chuỗi ngắn (< 60 chars), không phải heading trong chương
    # → Handled by AdsFilter learning, không hardcode để tránh false positive
]


# utils/ads_filter.py — thêm load/save JSON

import json
import os

_ADS_DB_FILE = "ADs_keyword.json"

class SimpleAdsFilter:

    def __init__(self) -> None:
        self._keywords: set[str] = {kw.lower() for kw in _SEED_KEYWORDS}
        self._patterns_raw: list[str] = list(_SEED_PATTERNS_RAW)
        self._patterns: list[re.Pattern[str]] = []

        # Compile seed patterns
        for pat_str in self._patterns_raw:
            try:
                self._patterns.append(re.compile(pat_str, re.IGNORECASE))
            except re.error as e:
                logger.warning("[AdsFilter] Seed pattern lỗi: %r — %s", pat_str, e)

        # Load learned data từ file
        self._load()

    def _load(self) -> None:
        """Load keywords/patterns đã học từ file JSON."""
        if not os.path.exists(_ADS_DB_FILE):
            return
        try:
            with open(_ADS_DB_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)

            loaded_kw  = 0
            loaded_pat = 0

            for kw in data.get("keywords", []):
                kw_lower = kw.lower().strip()
                if kw_lower and kw_lower not in self._keywords:
                    self._keywords.add(kw_lower)
                    loaded_kw += 1

            for pat_str in data.get("patterns", []):
                if pat_str and pat_str not in self._patterns_raw:
                    try:
                        self._patterns.append(re.compile(pat_str, re.IGNORECASE))
                        self._patterns_raw.append(pat_str)
                        loaded_pat += 1
                    except re.error:
                        pass

            if loaded_kw or loaded_pat:
                logger.info(
                    "[AdsFilter] Loaded %d kw + %d pat từ %s",
                    loaded_kw, loaded_pat, _ADS_DB_FILE,
                )
        except Exception as e:
            logger.warning("[AdsFilter] Không load được %s: %s", _ADS_DB_FILE, e)

    def save(self) -> None:
        """
        Lưu toàn bộ learned keywords/patterns ra file JSON.
        Chỉ lưu phần đã học (loại seed ra) để file gọn.
        Dùng atomic write để tránh corrupt.
        """
        seed_kw  = {kw.lower() for kw in _SEED_KEYWORDS}
        seed_pat = set(_SEED_PATTERNS_RAW)

        learned_kw  = sorted(self._keywords - seed_kw)
        learned_pat = [p for p in self._patterns_raw if p not in seed_pat]

        data = {
            "keywords": learned_kw,
            "patterns": learned_pat,
            "_stats": {
                "total_keywords": len(self._keywords),
                "total_patterns": len(self._patterns_raw),
                "learned_keywords": len(learned_kw),
                "learned_patterns": len(learned_pat),
            }
        }

        tmp = _ADS_DB_FILE + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, _ADS_DB_FILE)
        except Exception as e:
            logger.warning("[AdsFilter] Không save được %s: %s", _ADS_DB_FILE, e)

    def update_from_ai_result(self, raw_json: str) -> int:
        # ... code cũ giữ nguyên, chỉ thêm tracking pattern_raw ...
        added = 0

        for kw in data.get("keywords", []):
            if not isinstance(kw, str):
                continue
            kw_lower = kw.lower().strip()
            if kw_lower and kw_lower not in self._keywords:
                self._keywords.add(kw_lower)
                added += 1

        for pat_str in data.get("patterns", []):
            if not isinstance(pat_str, str) or not pat_str.strip():
                continue
            try:
                compiled = re.compile(pat_str.strip(), re.IGNORECASE)
                self._patterns.append(compiled)
                self._patterns_raw.append(pat_str.strip())  # ← track raw string
                added += 1
            except re.error as e:
                logger.debug("[AdsFilter] Regex lỗi: %r — %s", pat_str, e)

        return added