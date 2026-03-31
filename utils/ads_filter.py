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


class SimpleAdsFilter:
    """
    Filter watermark/ads nhẹ cho plain-text nội dung chương.

    BUG-3 FIX: Seed patterns được compile và nạp ngay từ __init__,
    bao gồm regex cho "Tip: You can use..." pattern của novelfire.
    """

    def __init__(self) -> None:
        self._keywords: set[str] = {kw.lower() for kw in _SEED_KEYWORDS}
        self._patterns: list[re.Pattern[str]] = []

        # BUG-3 FIX: Nạp seed patterns vào
        for pat_str in _SEED_PATTERNS_RAW:
            try:
                self._patterns.append(re.compile(pat_str, re.IGNORECASE))
            except re.error as e:
                logger.warning("[AdsFilter] Seed pattern lỗi: %r — %s", pat_str, e)

    # ── Public API ────────────────────────────────────────────────────────────

    def filter_content(self, text: str) -> str:
        lines  = text.splitlines()
        kept   = [line for line in lines if not self._is_ads_line(line)]

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
        suspicious_indices = [
            i for i, line in enumerate(lines)
            if self._is_ads_line(line)
        ]

        if not suspicious_indices:
            return None

        blocks: list[str] = []
        for idx in suspicious_indices[:_MAX_CONTEXT_BLOCKS]:
            start = max(0, idx - _CONTEXT_WINDOW)
            end   = min(len(lines), idx + _CONTEXT_WINDOW + 1)

            context_lines: list[str] = []
            for i in range(start, end):
                if i == idx:
                    context_lines.append(f">>> {lines[i]} <<<")
                else:
                    context_lines.append(lines[i])

            blocks.append("\n".join(context_lines))

        if not blocks:
            return None

        return "\n\n---\n\n".join(blocks)

    def update_from_ai_result(self, raw_json: str) -> int:
        if not raw_json:
            return 0
        try:
            data = json.loads(raw_json.strip())
        except (json.JSONDecodeError, AttributeError, ValueError):
            logger.debug("[AdsFilter] JSON parse thất bại từ AI response")
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
                logger.debug("[AdsFilter] Keyword mới: %r", kw_lower)

        for pat_str in data.get("patterns", []):
            if not isinstance(pat_str, str) or not pat_str.strip():
                continue
            try:
                compiled = re.compile(pat_str.strip(), re.IGNORECASE)
                self._patterns.append(compiled)
                added += 1
                logger.debug("[AdsFilter] Pattern mới: %r", pat_str)
            except re.error as e:
                logger.debug("[AdsFilter] Regex lỗi (bỏ qua): %r — %s", pat_str, e)

        return added

    @property
    def keyword_count(self) -> int:
        return len(self._keywords)

    @property
    def pattern_count(self) -> int:
        return len(self._patterns)

    # ── Private ───────────────────────────────────────────────────────────────

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