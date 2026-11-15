"""Kiểm tra độ dài và độ "văn xuôi" (prose richness) của nội dung chương."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

_SENTENCE_END_RE = re.compile(r"[.!?。！？]+")
_WORD_RE = re.compile(r"\b\w+\b")
_CAPS_LINE_RE = re.compile(r"^[A-Z\s\d\W]{5,}$")


@dataclass
class ValidationResult:
    """Kết quả kiểm chứng chất lượng nội dung chương."""

    is_valid: bool
    score: float
    notes: list[str] = field(default_factory=list)


def validate_content(
    content: str,
    *,
    min_chars: int = 100,
    min_word_count: int = 20,
    skip_validation: bool = False,
) -> ValidationResult:
    """Kiểm tra độ dài và chất lượng văn xuôi của chương.

    Bao gồm:
      - Kiểm tra độ dài tối thiểu (mặc định 100 ký tự).
      - Đánh giá độ phong phú của văn xuôi (số lượng từ, độ dài câu, mật độ đoạn, tỉ lệ chữ in hoa, đa dạng từ vựng).
    """
    stripped = (content or "").strip()
    char_count = len(stripped)

    # 1. Kiểm tra độ dài cơ bản (luôn áp dụng)
    if char_count < min_chars:
        return ValidationResult(
            is_valid=False,
            score=0.0,
            notes=[f"content too short: {char_count}c (min={min_chars})"],
        )

    # Nếu người dùng cấu hình bỏ qua xác thực (--no-validation hoặc CAO_NO_VALIDATION=1)
    if skip_validation or os.getenv("CAO_NO_VALIDATION") == "1":
        return ValidationResult(
            is_valid=True,
            score=1.0,
            notes=["validation_skipped"],
        )

    notes: list[str] = []
    scores: list[float] = []

    words = _WORD_RE.findall(stripped)
    word_count = len(words)

    # 1. Số lượng từ
    if word_count < min_word_count:
        wc_score = word_count / min_word_count * 0.5
        notes.append(f"low word count: {word_count}")
    else:
        wc_score = min(1.0, word_count / 200)
    scores.append(wc_score)

    # 2. Độ dài câu trung bình
    sentences = [s.strip() for s in _SENTENCE_END_RE.split(stripped) if s.strip()]
    if sentences:
        avg_sent = word_count / len(sentences)
        if 5 <= avg_sent <= 50:
            sent_score = 1.0
        elif avg_sent < 5:
            sent_score = avg_sent / 5
            notes.append(f"sentences too short (avg={avg_sent:.1f}w)")
        else:
            sent_score = max(0.3, 1.0 - (avg_sent - 50) / 100)
    else:
        sent_score = 0.3
    scores.append(sent_score)

    # 3. Mật độ đoạn văn
    lines = [line for line in stripped.splitlines() if line.strip()]
    blank_gaps = stripped.count("\n\n")
    para_score = min(1.0, (blank_gaps + 1) / max(len(lines) / 3, 1))
    scores.append(para_score)

    # 4. Tỉ lệ dòng in hoa toàn bộ (ALL_CAPS)
    caps_lines = sum(1 for line in lines if _CAPS_LINE_RE.match(line))
    caps_ratio = caps_lines / max(len(lines), 1)
    caps_score = max(0.0, 1.0 - caps_ratio * 3)
    if caps_ratio > 0.3:
        notes.append(f"high ALL_CAPS ratio: {caps_ratio:.0%}")
    scores.append(caps_score)

    # 5. Đa dạng từ vựng (Vocabulary diversity)
    if words:
        unique_ratio = len(set(w.lower() for w in words)) / len(words)
        uniq_score = min(1.0, unique_ratio * 1.5)
        if unique_ratio < 0.3:
            notes.append(f"low vocab diversity: {unique_ratio:.0%}")
    else:
        uniq_score = 0.0
    scores.append(uniq_score)

    overall_score = round(sum(scores) / len(scores), 3)
    is_valid = overall_score >= 0.3

    return ValidationResult(
        is_valid=is_valid,
        score=overall_score,
        notes=notes,
    )
