"""
pipeline/validator.py — Content validation blocks.

Blocks:
    LengthValidatorBlock      — Kiểm tra content đủ dài (min_chars)
    ProseRichnessBlock        — Kiểm tra content là văn xuôi thật (không phải HTML rác)
    FingerprintDedupBlock     — Kiểm tra content không trùng lặp (dedup)

ProseRichnessBlock sử dụng heuristics:
    - Word count >= threshold
    - Average sentence length reasonable (không quá ngắn = menu links)
    - Paragraph count > 0
    - Không quá nhiều ALL_CAPS lines (ads/navigation)
"""
from __future__ import annotations

import asyncio
import re
import time

from pipeline.base import BlockType, BlockResult, PipelineContext, ScraperBlock


# ── 1. Length Validator ───────────────────────────────────────────────────────

class LengthValidatorBlock(ScraperBlock):
    """
    Kiểm tra content.strip() >= min_chars.
    Validation đơn giản nhất — chạy đầu tiên.
    """
    block_type = BlockType.VALIDATE
    name       = "length"

    def __init__(self, min_chars: int = 100) -> None:
        self.min_chars = min_chars

    async def execute(self, ctx: PipelineContext) -> BlockResult:
        start = time.monotonic()
        content = ctx.content or ""
        stripped = content.strip()
        char_count = len(stripped)

        if char_count < self.min_chars:
            ctx.is_valid = False
            return self._timed(
                BlockResult.failed(
                    f"content too short: {char_count} chars (min={self.min_chars})"
                ),
                start,
            )

        # Partial score: thưởng cho content dài
        score = min(1.0, char_count / 2000)
        ctx.validation_score = max(ctx.validation_score, score * 0.5)
        ctx.is_valid = True

        return self._timed(
            BlockResult.success(
                data        = char_count,
                method_used = "length_check",
                confidence  = 1.0,
                char_count  = char_count,
                length_score = round(score, 3),
            ),
            start,
        )

    def to_config(self) -> dict:
        return {"type": self.name, "min_chars": self.min_chars}

    @classmethod
    def from_config(cls, config: dict) -> "LengthValidatorBlock":
        return cls(min_chars=int(config.get("min_chars", 100)))


# ── 2. Prose Richness Validator ───────────────────────────────────────────────

class ProseRichnessBlock(ScraperBlock):
    """
    Kiểm tra content có phải văn xuôi thật không.
    
    Tính điểm dựa trên:
        - word_count           >= min_word_count (default 20)
        - avg_sentence_length  trong khoảng [5, 50] words (prose range)
        - paragraph_count      > 0 nếu có newlines
        - caps_line_ratio      < 0.3 (ít ALL_CAPS = ít navigation/ads)
        - unique_word_ratio    > 0.3 (đa dạng từ vựng = thật)
    
    validation_score tổng hợp từ 5 dimensions.
    """
    block_type = BlockType.VALIDATE
    name       = "prose_richness"

    _SENTENCE_END = re.compile(r"[.!?。！？]+")
    _WORD_RE      = re.compile(r"\b\w+\b")
    _CAPS_LINE    = re.compile(r"^[A-Z\s\d\W]{5,}$")

    def __init__(self, min_word_count: int = 20) -> None:
        self.min_word_count = min_word_count

    async def execute(self, ctx: PipelineContext) -> BlockResult:
        start = time.monotonic()
        try:
            content = ctx.content or ""
            stripped = content.strip()

            if not stripped:
                ctx.is_valid = False
                return self._timed(BlockResult.failed("empty content"), start)

            score, notes = self._score_prose(stripped)
            ctx.validation_score = score
            ctx.is_valid         = score >= 0.3
            ctx.validation_notes = notes

            if not ctx.is_valid:
                return self._timed(
                    BlockResult.failed(
                        f"prose score too low: {score:.2f} — {'; '.join(notes)}"
                    ),
                    start,
                )

            return self._timed(
                BlockResult.success(
                    data        = score,
                    method_used = "prose_richness",
                    confidence  = score,
                    prose_score = round(score, 3),
                    notes       = notes,
                ),
                start,
            )
        except asyncio.CancelledError:
            raise
        except Exception as e:
            return self._timed(BlockResult.failed(str(e) or repr(e)), start)

    def _score_prose(self, text: str) -> tuple[float, list[str]]:
        """Tính prose richness score (0.0-1.0) và ghi chú."""
        notes: list[str] = []
        scores: list[float] = []

        words = self._WORD_RE.findall(text)
        word_count = len(words)

        # 1. Word count score
        if word_count < self.min_word_count:
            wc_score = word_count / self.min_word_count * 0.5
            notes.append(f"low word count: {word_count}")
        else:
            wc_score = min(1.0, word_count / 200)
        scores.append(wc_score)

        # 2. Average sentence length (prose: 5-50 words/sentence)
        sentences = [s.strip() for s in self._SENTENCE_END.split(text) if s.strip()]
        if sentences:
            avg_sent = word_count / len(sentences)
            if 5 <= avg_sent <= 50:
                sent_score = 1.0
            elif avg_sent < 5:
                sent_score = avg_sent / 5
                notes.append(f"sentences too short (avg={avg_sent:.1f} words)")
            else:
                sent_score = max(0.3, 1.0 - (avg_sent - 50) / 100)
        else:
            sent_score = 0.3
        scores.append(sent_score)

        # 3. Paragraph density
        lines      = [l for l in text.splitlines() if l.strip()]
        blank_gaps = text.count("\n\n")
        para_score = min(1.0, (blank_gaps + 1) / max(len(lines) / 3, 1))
        scores.append(para_score)

        # 4. ALL_CAPS ratio (navigation/ads thường in hoa)
        caps_lines  = sum(1 for l in lines if self._CAPS_LINE.match(l))
        caps_ratio  = caps_lines / max(len(lines), 1)
        caps_score  = max(0.0, 1.0 - caps_ratio * 3)
        if caps_ratio > 0.3:
            notes.append(f"high ALL_CAPS ratio: {caps_ratio:.0%}")
        scores.append(caps_score)

        # 5. Unique word ratio (đa dạng từ vựng)
        if words:
            unique_ratio = len(set(w.lower() for w in words)) / len(words)
            uniq_score   = min(1.0, unique_ratio * 1.5)
            if unique_ratio < 0.3:
                notes.append(f"low vocabulary diversity: {unique_ratio:.0%}")
        else:
            uniq_score = 0.0
        scores.append(uniq_score)

        final = sum(scores) / len(scores)
        return round(final, 3), notes

    def to_config(self) -> dict:
        return {"type": self.name, "min_word_count": self.min_word_count}

    @classmethod
    def from_config(cls, config: dict) -> "ProseRichnessBlock":
        return cls(min_word_count=int(config.get("min_word_count", 20)))


# ── 3. Fingerprint Dedup Block ────────────────────────────────────────────────

class FingerprintDedupBlock(ScraperBlock):
    """
    Kiểm tra content không trùng lặp với các chapter đã scrape.
    Dùng MD5 fingerprint từ progress["fingerprints"].
    """
    block_type = BlockType.VALIDATE
    name       = "fingerprint_dedup"

    async def execute(self, ctx: PipelineContext) -> BlockResult:
        start = time.monotonic()
        try:
            content = ctx.content or ""
            if not content.strip():
                return self._timed(BlockResult.skipped("no content to check"), start)

            from utils.string_helpers import make_fingerprint
            fp          = make_fingerprint(content)
            fingerprints = set(ctx.progress.get("fingerprints") or [])

            if fp in fingerprints:
                ctx.is_valid = False
                return self._timed(
                    BlockResult.failed("duplicate content detected (fingerprint match)"),
                    start,
                )

            return self._timed(
                BlockResult.success(
                    data        = fp,
                    method_used = "fingerprint_dedup",
                    confidence  = 1.0,
                    fingerprint = fp,
                ),
                start,
            )
        except asyncio.CancelledError:
            raise
        except Exception as e:
            return self._timed(BlockResult.failed(str(e) or repr(e)), start)

    def to_config(self) -> dict:
        return {"type": self.name}

    @classmethod
    def from_config(cls, config: dict) -> "FingerprintDedupBlock":
        return cls()


# ── Registry ──────────────────────────────────────────────────────────────────

_VALIDATE_BLOCK_MAP: dict[str, type[ScraperBlock]] = {
    "length"           : LengthValidatorBlock,
    "prose_richness"   : ProseRichnessBlock,
    "fingerprint_dedup": FingerprintDedupBlock,
}


def make_validate_block(config: dict) -> ScraperBlock:
    """Factory: tạo validate block từ StepConfig dict."""
    block_type = config.get("type", "length")
    cls = _VALIDATE_BLOCK_MAP.get(block_type)
    if cls is None:
        raise ValueError(
            f"Unknown validate block type: {block_type!r}. "
            f"Available: {list(_VALIDATE_BLOCK_MAP)}"
        )
    return cls.from_config(config)