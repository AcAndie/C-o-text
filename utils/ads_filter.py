# utils/ads_filter.py
"""
utils/ads_filter.py — Filter watermark/ads từ nội dung chương truyện.

CHANGES (v4):
  _SEED_PATTERNS_RAW: Thêm patterns bắt script tags và JS ad code xuất hiện
    dưới dạng text trong nội dung (novelfire.net và các aggregator tương tự
    inject pubfuturetag, googletag, adsbygoogle trực tiếp vào article body).

  inject_domain_keywords(): Nhận domain_watermarks từ SiteProfileDict.
  inject_domain_patterns(): Nhận regex patterns từ profile.
"""
from __future__ import annotations

import json
import logging
import os
import re

logger = logging.getLogger(__name__)

ADS_DB_FILE = "ADs_keyword.json"

_SEED_KEYWORDS: list[str] = [
    "stolen content", "stolen from", "this content is stolen",
    "this chapter is stolen", "this chapter was stolen",
    "this work has been stolen", "if you come across this story",
    "if you find this content", "this story has been stolen",
    "has been taken without permission", "taken without permission",
    "read at royalroad", "read on royalroad", "read the original at",
    "read the original on", "original source",
    "find this and other great novels", "check out the original",
    "visit the original", "please support the author",
    "support the original", "support the original author",
    "for more, visit", "more chapters at", "read more at",
    "patreon.com/", "ko-fi.com/", "buymeacoffee.com/",
    "read at scribblehub", "read on scribblehub",
    "original at webnovel", "read on webnovel",
    "read on wattpad", "find this story on wattpad",
    "if you encounter this story on amazon",
    "encounter this story on amazon", "found on amazon, report it",
    "share to your friends", "share this chapter", "share this novel",
    "keyboard keys to browse between chapters",
    "use left, right keyboard keys", "you can use left, right",
    "left, right keyboard keys to browse",
    "if you find any errors", "non-standard content, ads redirect",
    "please let us know so we can fix", "let us know so we can fix it",
    "translate by", "translation by", "translated by system",
    "mtl by", "machine translated by", "raw source:",
    "chapters are updated daily", "visit lightnovelreader",
    "visit novelfull", "visit wuxiaworld", "visit gravitytales",
    "read latest chapters at", "read advance chapters at",
    "for more chapters,",
]

_MIN_SUSPICIOUS_LINE_LEN = 15
_CONTEXT_WINDOW          = 10
_MAX_CONTEXT_BLOCKS      = 5

# FIX v4: Thêm patterns bắt JS ad injection xuất hiện dưới dạng text.
# Các site như novelfire.net nhúng <script>window.pubfuturetag...</script>
# trực tiếp vào content div. Dù extract_text_blocks đã fix để skip <script>
# tags, vẫn cần patterns này như safety net cho các dạng text-only injection.
_SEED_PATTERNS_RAW: list[str] = [
    # Existing
    r"^Tip:\s+You can use",

    # Script tag appearing as text (site embeds raw HTML in content)
    r"<script[\s>]",
    r"</script>",

    # Common ad network JS patterns
    r"window\.pubfuturetag",
    r"window\.googletag",
    r"window\.adsbygoogle",
    r"googletag\.cmd\.push",
    r"adsbygoogle\.push",
    r"\.pubads\(\)",

    # Generic ad push pattern: window.X = window.X || []; window.X.push({...})
    r"window\.\w+\s*=\s*window\.\w+\s*\|\|\s*\[\]",

    # pubfuturetag specific (novelfire)
    r"pubfuturetag\.push\(",
    r'"unit"\s*:\s*"[^"]+"\s*,\s*"id"\s*:\s*"pf-',
]


class SimpleAdsFilter:

    def __init__(self) -> None:
        self._keywords: set[str] = {kw.lower() for kw in _SEED_KEYWORDS}
        self._patterns: list[re.Pattern[str]] = []
        for pat_str in _SEED_PATTERNS_RAW:
            try:
                self._patterns.append(re.compile(pat_str, re.IGNORECASE))
            except re.error as e:
                logger.warning("[AdsFilter] Seed pattern lỗi: %r — %s", pat_str, e)

    @classmethod
    def load(cls) -> "SimpleAdsFilter":
        instance = cls()
        if not os.path.exists(ADS_DB_FILE):
            return instance
        try:
            with open(ADS_DB_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            loaded_kw = loaded_pat = 0
            for kw in data.get("keywords", []):
                if isinstance(kw, str):
                    kw_lower = kw.lower().strip()
                    if kw_lower and kw_lower not in instance._keywords:
                        instance._keywords.add(kw_lower)
                        loaded_kw += 1
            for pat_str in data.get("patterns", []):
                if isinstance(pat_str, str) and pat_str.strip():
                    try:
                        instance._patterns.append(re.compile(pat_str.strip(), re.IGNORECASE))
                        loaded_pat += 1
                    except re.error:
                        pass
            if loaded_kw or loaded_pat:
                logger.info("[AdsFilter] Load %d kw + %d pat từ %s", loaded_kw, loaded_pat, ADS_DB_FILE)
        except Exception as e:
            logger.warning("[AdsFilter] Không load được DB: %s", e)
        return instance

    def save(self) -> None:
        data = {
            "keywords": sorted(self._keywords),
            "patterns": [p.pattern for p in self._patterns],
        }
        tmp = ADS_DB_FILE + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, ADS_DB_FILE)
        except Exception as e:
            logger.error("[AdsFilter] Không lưu được DB: %s", e)
            try:
                if os.path.exists(tmp):
                    os.remove(tmp)
            except Exception:
                pass

    # ── Domain injection ──────────────────────────────────────────────────────

    def inject_domain_keywords(self, keywords: list[str]) -> int:
        """Inject domain_watermarks từ SiteProfileDict. Trả về số keyword mới."""
        added = 0
        for kw in keywords:
            if not isinstance(kw, str):
                continue
            kw_lower = kw.lower().strip()
            if kw_lower and kw_lower not in self._keywords:
                self._keywords.add(kw_lower)
                added += 1
        return added

    def inject_domain_patterns(self, patterns: list[str]) -> int:
        """Inject regex patterns từ domain profile."""
        added = 0
        existing = {p.pattern for p in self._patterns}
        for pat_str in patterns:
            if not isinstance(pat_str, str) or not pat_str.strip():
                continue
            if pat_str.strip() in existing:
                continue
            try:
                self._patterns.append(re.compile(pat_str.strip(), re.IGNORECASE))
                added += 1
            except re.error as e:
                logger.warning("[AdsFilter] Domain pattern lỗi: %r — %s", pat_str, e)
        return added

    # ── Core ──────────────────────────────────────────────────────────────────

    def filter_content(self, text: str) -> str:
        lines = text.splitlines()
        kept  = [line for line in lines if not self._is_ads_line(line)]
        result: list[str] = []
        blank_count = 0
        for line in kept:
            if not line.strip():
                blank_count += 1
                if blank_count <= 1:
                    result.append(line)
            else:
                blank_count = 0
                result.append(line)
        return "\n".join(result)

    def build_ai_context_block(self, text: str) -> str | None:
        lines = text.splitlines()
        suspicious_indices = [i for i, line in enumerate(lines) if self._is_ads_line(line)]
        if not suspicious_indices:
            return None
        blocks: list[str] = []
        for idx in suspicious_indices[:_MAX_CONTEXT_BLOCKS]:
            start = max(0, idx - _CONTEXT_WINDOW)
            end   = min(len(lines), idx + _CONTEXT_WINDOW + 1)
            context_lines = [
                f">>> {lines[i]} <<<" if i == idx else lines[i]
                for i in range(start, end)
            ]
            blocks.append("\n".join(context_lines))
        return "\n\n---\n\n".join(blocks) if blocks else None

    def update_from_ai_result(self, raw_json: str) -> int:
        if not raw_json:
            return 0
        try:
            data = json.loads(raw_json.strip())
        except (json.JSONDecodeError, AttributeError, ValueError):
            return 0
        if not isinstance(data, dict) or not data.get("found"):
            return 0
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
                self._patterns.append(re.compile(pat_str.strip(), re.IGNORECASE))
                added += 1
            except re.error:
                pass
        return added

    @property
    def keyword_count(self) -> int:
        return len(self._keywords)

    @property
    def pattern_count(self) -> int:
        return len(self._patterns)

    def _is_ads_line(self, line: str) -> bool:
        stripped = line.strip()
        if len(stripped) < _MIN_SUSPICIOUS_LINE_LEN:
            return False
        lower = stripped.lower()
        for kw in self._keywords:
            if kw in lower:
                return True
        for pat in self._patterns:
            if pat.search(stripped):
                return True
        return False