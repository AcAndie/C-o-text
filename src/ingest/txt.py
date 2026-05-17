"""
ingest/txt.py — TXT input adapter (P5.2).

Detect chapter boundary pattern → split file → yield RawDocument per chapter.

Detection flow:
  1. Read file UTF-8 strict (fail-loud non-UTF-8 — Decision: predictable
     behavior, no charset auto-detect trong v1.0).
  2. Regex match each case in data/txt_cases.json against first 100 lines.
     Score = count matches. Best score ≥1 wins.
  3. No regex match → AI fallback (`ai_detect_txt_pattern`). 50-line sample.
     - AI must return valid regex compileable.
     - AI verify: 3 random chunks of 80 lines, each must contain ≥1 match.
     - Pass → persist as new case (atomic) → use.
     - Fail → raise ValueError (loud).
  4. Apply chosen pattern → split into [(idx, title, body), ...].
  5. Each chunk → wrap as HTML article → RawDocument yield.

Scope v1.0 (Decision #21): VN + EN only. AI fallback may detect other
languages but persists with `language="other"` tag.

Pattern persistence (P5.2): AI-learned cases atomic-append to
data/txt_cases.json. Threading lock cho concurrent safety (mirror
ads_filter.save() pattern).
"""
from __future__ import annotations

import json
import logging
import os
import random
import re
import threading
from pathlib import Path
from typing import TYPE_CHECKING, AsyncIterator

from ingest.types import RawDocument

if TYPE_CHECKING:
    from ai.client import AIRateLimiter

logger = logging.getLogger(__name__)

# Path: data/txt_cases.json relative to project root
_TXT_CASES_PATH = Path(__file__).resolve().parent.parent / "data" / "txt_cases.json"

# Detection windows
_SAMPLE_LINES         = 100   # Regex detection scan window
_AI_SAMPLE_LINES      = 50    # AI fallback input
_AI_VERIFY_CHUNKS     = 3     # Number of random chunks AI verify
_AI_VERIFY_CHUNK_SIZE = 80    # Lines per verify chunk
_AI_LEARNED_CONF      = 0.7   # Confidence cho AI-learned cases (lower than authored)

# Concurrent write safety
_DB_LOCK = threading.Lock()


# ── DB load / persist ─────────────────────────────────────────────────────────

def load_cases() -> list[dict]:
    """Load TXT case database. Fail-loud if missing."""
    if not _TXT_CASES_PATH.exists():
        raise FileNotFoundError(
            f"TXT case DB missing: {_TXT_CASES_PATH}. "
            "Initial cases được ship trong repo — repo có thể bị corrupt."
        )
    with open(_TXT_CASES_PATH, "r", encoding="utf-8") as f:
        db = json.load(f)
    return db.get("cases", [])


def _persist_new_case(case: dict) -> None:
    """
    Atomic append-or-skip new case. Skip nếu id đã exist.
    Threading lock cho concurrent run safety.
    """
    with _DB_LOCK:
        with open(_TXT_CASES_PATH, "r", encoding="utf-8") as f:
            db = json.load(f)
        cases = db.setdefault("cases", [])
        if any(c.get("id") == case["id"] for c in cases):
            logger.info("[TXT] case id %r already in DB — skip persist", case["id"])
            return
        cases.append(case)
        tmp = str(_TXT_CASES_PATH) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(db, f, ensure_ascii=False, indent=2)
        os.replace(tmp, _TXT_CASES_PATH)
        logger.info("[TXT] persisted new case %r", case["id"])


# ── File read (fail-loud non-UTF-8) ───────────────────────────────────────────

def _read_utf8(path: str) -> str:
    """
    Read TXT as UTF-8. Raise UnicodeDecodeError với user-friendly message
    nếu file không phải UTF-8.

    v1.0 không auto-detect encoding (charset-normalizer). Decision: predictable
    behavior > convenience. User convert qua iconv hoặc save lại từ editor
    với UTF-8 encoding.
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except UnicodeDecodeError as e:
        raise UnicodeDecodeError(
            e.encoding, e.object, e.start, e.end,
            f"File {path!r} không phải UTF-8 — Cào Text v1.0 chỉ hỗ trợ UTF-8. "
            f"Convert qua: `iconv -f <src-encoding> -t utf-8 <file>` hoặc save "
            f"lại từ editor với UTF-8 encoding. Original: {e.reason}",
        ) from e


# ── Regex-based detection ────────────────────────────────────────────────────

def _score_case(lines: list[str], pattern: str) -> int:
    """Count lines matching pattern. Return 0 nếu regex invalid (defensive)."""
    try:
        rx = re.compile(pattern)
    except re.error as e:
        logger.warning("[TXT] invalid regex %r: %s", pattern, e)
        return 0
    return sum(1 for ln in lines if rx.match(ln.strip()))


def detect_pattern_regex(text: str) -> dict | None:
    """
    Score each case against first _SAMPLE_LINES. Return best case nếu score ≥1.
    None nếu zero matches across all cases → caller try AI fallback.
    """
    cases = load_cases()
    lines = text.splitlines()[:_SAMPLE_LINES]

    scored = [(case, _score_case(lines, case["pattern"])) for case in cases]
    scored.sort(key=lambda x: x[1], reverse=True)

    if not scored:
        return None
    best_case, best_score = scored[0]
    logger.debug("[TXT] best regex match: %r score=%d", best_case["id"], best_score)
    if best_score >= 1:
        return best_case
    return None


# ── AI fallback + verify ──────────────────────────────────────────────────────

def _ai_verify_pattern(text: str, pattern: str) -> bool:
    """
    Pick _AI_VERIFY_CHUNKS random non-overlapping chunks (80 lines each)
    từ middle of file. Each chunk phải contain ≥1 boundary match.

    File quá nhỏ (< 3 chunks fit) → trust AI, skip verify, return True.
    """
    rx = re.compile(pattern)
    lines = text.splitlines()
    n = len(lines)

    if n < _AI_VERIFY_CHUNK_SIZE * _AI_VERIFY_CHUNKS:
        logger.info("[TXT] file too small (%d lines) cho verify — trust AI", n)
        return True

    positions = random.sample(
        range(0, n - _AI_VERIFY_CHUNK_SIZE), _AI_VERIFY_CHUNKS,
    )
    for pos in positions:
        chunk = lines[pos:pos + _AI_VERIFY_CHUNK_SIZE]
        if not any(rx.match(ln.strip()) for ln in chunk):
            logger.warning(
                "[TXT] verify FAIL — chunk at line %d không có boundary match", pos,
            )
            return False
    return True


async def detect_pattern(
    text       : str,
    ai_limiter : "AIRateLimiter | None" = None,
) -> dict:
    """
    Public detector. Regex first → AI fallback (nếu ai_limiter) → raise
    ValueError nếu tất cả fail.

    Caller (orchestrator) phải pass `ai_limiter` để enable AI fallback —
    None = skip fallback, raise nếu regex không match.
    """
    case = detect_pattern_regex(text)
    if case:
        return case

    if ai_limiter is None:
        raise ValueError(
            "TXT file không match case pattern nào trong data/txt_cases.json, "
            "và không có ai_limiter cho AI fallback detection. "
            "Add pattern thủ công vào data/txt_cases.json hoặc pass ai_limiter."
        )

    sample = "\n".join(text.splitlines()[:_AI_SAMPLE_LINES])
    from ai.agents import ai_detect_txt_pattern
    ai_result = await ai_detect_txt_pattern(sample, ai_limiter)

    if not ai_result or not ai_result.get("pattern"):
        raise ValueError(
            "TXT pattern detection failed. AI fallback không tìm thấy pattern "
            "khả dụng trong sample 50 dòng đầu. File có thể không có chapter "
            "boundary rõ ràng — kiểm tra format file."
        )

    pattern = ai_result["pattern"]
    try:
        re.compile(pattern)
    except re.error as e:
        raise ValueError(f"AI returned invalid regex {pattern!r}: {e}") from e

    if not _ai_verify_pattern(text, pattern):
        raise ValueError(
            f"AI-suggested pattern {pattern!r} failed verify — "
            f"< {_AI_VERIFY_CHUNKS} random chunks contained boundary match. "
            "Có thể pattern quá greedy hoặc chỉ match metadata header."
        )

    # Persist new case (best-effort, append to DB)
    new_case = {
        "id"        : ai_result.get("id") or f"ai_learned_{abs(hash(pattern)) % 0xffffffff:08x}",
        "language"  : ai_result.get("language", "other"),
        "pattern"   : pattern,
        "samples"   : ai_result.get("chapter_examples", []),
        "confidence": _AI_LEARNED_CONF,
    }
    try:
        _persist_new_case(new_case)
    except Exception as e:
        logger.warning("[TXT] persist new case failed: %s — continue without save", e)

    return new_case


# ── Split into chapters ───────────────────────────────────────────────────────

def split_into_chapters(text: str, case: dict) -> list[tuple[int, str, str]]:
    """
    Apply case pattern → return list[(chapter_idx, title, body)].

    Title = full original boundary line (preserve formatting).
    Body  = lines between this boundary và next (or EOF). Trimmed.
    Pre-boundary content (preface) → dropped. Caller có thể warn nếu cần.
    """
    rx = re.compile(case["pattern"])
    lines = text.splitlines()

    boundaries: list[tuple[int, str]] = []
    for i, line in enumerate(lines):
        if rx.match(line.strip()):
            boundaries.append((i, line.strip()))

    if not boundaries:
        return []

    chapters: list[tuple[int, str, str]] = []
    for chapter_idx, (start_line, title) in enumerate(boundaries, start=1):
        end_line = (
            boundaries[chapter_idx][0]
            if chapter_idx < len(boundaries) else len(lines)
        )
        body = "\n".join(lines[start_line + 1:end_line]).strip()
        chapters.append((chapter_idx, title, body))

    return chapters


# ── HTML wrap (pipeline downstream expects HTML) ──────────────────────────────

_HTML_ESCAPE = str.maketrans({"&": "&amp;", "<": "&lt;", ">": "&gt;"})


def _text_to_html_paragraphs(text: str) -> str:
    """
    Plain text → series of `<p>...</p>`. Double newline = paragraph break.
    Single newline within paragraph → preserved as <br> (rare, but novels
    sometimes có dialogue line breaks).
    """
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    out = []
    for p in paragraphs:
        escaped = p.translate(_HTML_ESCAPE)
        # Preserve intra-paragraph line breaks as <br/>
        escaped = escaped.replace("\n", "<br/>")
        out.append(f"<p>{escaped}</p>")
    return "".join(out)


def _build_chapter_html(title: str, body: str) -> str:
    """
    Wrap chapter content trong `<article>` để extract chain pickup
    qua DensityHeuristic hoặc selector-aware logic.
    """
    title_esc = title.translate(_HTML_ESCAPE)
    body_html = _text_to_html_paragraphs(body)
    return (
        f"<html><body><article>"
        f"<h1>{title_esc}</h1>"
        f"{body_html}"
        f"</article></body></html>"
    )


# ── Main entry ────────────────────────────────────────────────────────────────

async def ingest_txt(
    path       : str,
    ai_limiter : "AIRateLimiter | None" = None,
) -> AsyncIterator[RawDocument]:
    """
    Yield RawDocument per chapter từ TXT file.

    Args:
        path: absolute hoặc relative path tới .txt file
        ai_limiter: optional, enable AI fallback nếu regex không match

    Raises:
        UnicodeDecodeError nếu file không phải UTF-8
        ValueError nếu pattern detection fail hoàn toàn
        ValueError nếu pattern match nhưng 0 boundaries trong file
    """
    text = _read_utf8(path)
    case = await detect_pattern(text, ai_limiter=ai_limiter)
    chapters = split_into_chapters(text, case)

    if not chapters:
        raise ValueError(
            f"TXT pattern {case['id']!r} đã match trong sample nhưng tìm "
            f"thấy 0 boundaries khi split toàn file. File có thể bất nhất "
            "(sample khác phần còn lại) hoặc pattern sai."
        )

    source_path = str(Path(path).resolve())
    story_name  = Path(path).stem
    base_meta   = {
        "story_name": story_name,
        "language"  : case.get("language"),
        "txt_case"  : case.get("id"),
    }

    logger.info(
        "[TXT] %r → %d chapters via case %r (lang=%s)",
        path, len(chapters), case["id"], case.get("language"),
    )

    for chapter_idx, title, body in chapters:
        yield RawDocument(
            chapter_index = chapter_idx,
            html          = _build_chapter_html(title, body),
            source_path   = source_path,
            metadata      = dict(base_meta),
        )


__all__ = [
    "ingest_txt", "detect_pattern", "detect_pattern_regex",
    "split_into_chapters", "load_cases",
]
