"""
ingest/epub_structure.py — TOC-driven chapter plan (v1.0.14).

Step 1 of TOC analyzer (no AI). Read EPUB TOC, classify each entry as
real chapter vs front/back matter, build per-chapter plan that merges
non-TOC spine continuations into preceding chapter.

Front + back matter gộp vô 1 "Front Matter" entry (index 0, filename
`0000_Front_Matter.md`).

Classification rules:
  - TOC title matches FRONT_MATTER_KEYWORDS → matter
  - TOC title matches BACK_MATTER_KEYWORDS → matter
  - Filename matches *_PATTERNS → matter (even if in TOC, e.g. "Cover")
  - Else → real chapter (use TOC title as hint)

Spine docs NOT in TOC:
  - Before first TOC chapter → matter
  - Between TOC chapters → continuation (merge with preceding chapter)
  - After last TOC chapter → matter (unless preceding chapter was matter)
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import threading
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from bs4 import BeautifulSoup
from ebooklib import ITEM_DOCUMENT, epub

from config import DATA_DIR

logger = logging.getLogger(__name__)

# AI cache
_CACHE_FILE = os.path.join(DATA_DIR, "epub_analyses.json")
_CACHE_LOCK = threading.Lock()


# TOC-title keyword classification (case-insensitive substring match)
FRONT_MATTER_KEYWORDS = frozenset({
    "contents", "table of contents", "cover", "title page",
    "about the book", "about the author", "dedication",
    "preface", "foreword", "introduction", "front matter",
    "publisher", "imprint", "credits",
})

BACK_MATTER_KEYWORDS = frozenset({
    "acknowledg", "copyright", "appendix", "afterword",
    "back matter", "reading group", "discussion question",
    "newsletter", "about the author",
})

# Promo/excerpt cho TRUYỆN KHÁC — KHÔNG ghi file, skip hoàn toàn.
# v1.0.16: tách khỏi BACK_MATTER vì không phải back matter của truyện này.
SKIP_KEYWORDS = frozenset({
    "extract from", "excerpt from", "also by", "praise for",
    "advert", "advertisement", "back ad", "out now",
    "find out what happens", "read on for", "preview of",
    "sneak peek",
})

# Filename patterns (case-insensitive substring) — fallback when TOC missing
MATTER_FILENAME_PATTERNS = (
    "toc", "contents", "cover", "title", "copyright", "dedication",
    "acknowledg", "about_author", "about_book", "nav", "front",
    "publisher", "imprint", "footnote",
)

# Filename patterns → SKIP entirely (promo/advert)
SKIP_FILENAME_PATTERNS = (
    "advert", "ads_", "ads_back", "ads_front", "promo", "excerpt",
)


@dataclass
class ChapterPlan:
    """One unit in the chapter plan."""
    index   : int                          # 0 = matter bucket, 1+ = real chapter
    kind    : str                          # "chapter" | "matter" | "skip"
    title   : str | None = None            # TOC hint (None = use h1/h2/default)
    doc_ids : list[str] = field(default_factory=list)   # spine item IDs to merge


# ── TOC reader ────────────────────────────────────────────────────────────────

def _flatten_toc(items) -> list[tuple[str, str]]:
    """Walk book.toc recursively. Return [(title, href_no_fragment)]."""
    result: list[tuple[str, str]] = []
    for item in items:
        if isinstance(item, tuple):
            # (Section, [children]) — include section if has href
            section, children = item
            title = (getattr(section, "title", "") or "").strip()
            href  = getattr(section, "href", "") or ""
            if title and href:
                result.append((title, href.split("#", 1)[0]))
            result.extend(_flatten_toc(children))
        else:
            title = (getattr(item, "title", "") or "").strip()
            href  = getattr(item, "href", "") or ""
            if title and href:
                result.append((title, href.split("#", 1)[0]))
    return result


def _normalize_href(href: str) -> str:
    """Normalize TOC href for comparison with spine item file_name."""
    if not href:
        return ""
    # Strip fragment, lowercase, normalize separator
    href = href.split("#", 1)[0]
    href = href.replace("\\", "/").lower()
    return href


def _is_matter_title(title: str) -> bool:
    lo = title.lower()
    if any(kw in lo for kw in FRONT_MATTER_KEYWORDS):
        return True
    if any(kw in lo for kw in BACK_MATTER_KEYWORDS):
        return True
    return False


def _is_matter_filename(filename: str) -> bool:
    lo = (filename or "").lower()
    return any(p in lo for p in MATTER_FILENAME_PATTERNS)


def _is_skip_title(title: str) -> bool:
    """Promo/excerpt cho truyện khác — skip không ghi file."""
    lo = title.lower()
    return any(kw in lo for kw in SKIP_KEYWORDS)


def _is_skip_filename(filename: str) -> bool:
    lo = (filename or "").lower()
    return any(p in lo for p in SKIP_FILENAME_PATTERNS)


def smart_title_from_toc(toc_title: str, chapter_idx: int) -> str:
    """
    Convert TOC label thành title hiển thị tốt hơn.
      - "0000" → "Prologue" (convention)
      - "0001"..."0099" (numeric) → "Chapter N" (strip leading zeros)
      - Non-numeric → keep as-is
    """
    if not toc_title:
        return f"Chapter {chapter_idx}"

    t = toc_title.strip()
    if t.isdigit():
        n = int(t)
        if n == 0:
            return "Prologue"
        return f"Chapter {n}"
    return t


# ── Planner ────────────────────────────────────────────────────────────────────

def build_chapter_plan(book: epub.EpubBook) -> list[ChapterPlan]:
    """
    Build ordered list of ChapterPlan from EPUB spine + TOC.

    Algorithm:
      1. Flatten TOC → href → title map.
      2. Walk spine in order:
         - Matter filename → matter bucket
         - In TOC + matter title → matter bucket
         - In TOC + real title → new chapter (close previous if open)
         - Not in TOC + current chapter open → continuation (merge)
         - Not in TOC + no chapter yet → matter bucket
    """
    toc_entries = _flatten_toc(book.toc) if book.toc else []
    # Map normalized href → title (last entry wins if dup)
    toc_map = {_normalize_href(href): title for title, href in toc_entries}

    matter_bucket : list[str] = []
    skip_ids      : list[str] = []
    chapters      : list[ChapterPlan] = []
    current       : ChapterPlan | None = None

    chapter_idx = 0

    for spine_entry in book.spine:
        item_id = spine_entry[0] if isinstance(spine_entry, tuple) else spine_entry
        item = book.get_item_with_id(item_id)
        if item is None or item.get_type() != ITEM_DOCUMENT:
            continue

        filename = item.file_name or ""
        norm_fn  = _normalize_href(filename)

        # Match TOC by exact or suffix match (TOC href may include OPS/ prefix)
        toc_title = toc_map.get(norm_fn)
        if toc_title is None:
            base = PurePosixPath(norm_fn).name
            for href, title in toc_map.items():
                if PurePosixPath(href).name == base:
                    toc_title = title
                    break

        # SKIP detection FIRST (highest priority) — promo/excerpt cho truyện khác
        is_skip = (
            _is_skip_filename(filename)
            or (toc_title is not None and _is_skip_title(toc_title))
        )
        if is_skip:
            if current is not None:
                chapters.append(current)
                current = None
            skip_ids.append(item_id)
            continue

        is_matter = (
            _is_matter_filename(filename)
            or (toc_title is not None and _is_matter_title(toc_title))
        )

        if is_matter:
            if current is not None:
                chapters.append(current)
                current = None
            matter_bucket.append(item_id)
            continue

        if toc_title is not None:
            if current is not None:
                chapters.append(current)
            chapter_idx += 1
            current = ChapterPlan(
                index   = chapter_idx,
                kind    = "chapter",
                title   = smart_title_from_toc(toc_title, chapter_idx),
                doc_ids = [item_id],
            )
        elif current is not None:
            current.doc_ids.append(item_id)
        else:
            matter_bucket.append(item_id)

    if current is not None:
        chapters.append(current)

    # Assemble: matter at index 0 (if any), then chapters
    plan: list[ChapterPlan] = []
    if matter_bucket:
        plan.append(ChapterPlan(
            index   = 0,
            kind    = "matter",
            title   = "Front Matter",
            doc_ids = matter_bucket,
        ))
    plan.extend(chapters)

    # Skip entries do NOT appear in plan — not written to disk.
    # Track separately for log + future inspection (not yielded).
    logger.info(
        "[EpubStructure] Plan: %d chapters + %d matter docs + %d skipped",
        len(chapters), len(matter_bucket), len(skip_ids),
    )
    if skip_ids:
        logger.info("[EpubStructure] Skipped docs: %s", skip_ids[:10])
    return plan


# ── AI cache helpers ──────────────────────────────────────────────────────────

def _epub_hash(path: str) -> str:
    """SHA256 of EPUB file content — cache key."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def _load_cache() -> dict:
    if not os.path.exists(_CACHE_FILE):
        return {}
    try:
        with open(_CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f) or {}
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("[EpubStructure] cache load failed: %s — reset", e)
        return {}


def _save_cache(data: dict) -> None:
    with _CACHE_LOCK:
        os.makedirs(os.path.dirname(os.path.abspath(_CACHE_FILE)), exist_ok=True)
        tmp = _CACHE_FILE + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, _CACHE_FILE)
        except OSError as e:
            logger.warning("[EpubStructure] cache save failed: %s", e)


# ── AI analyzer (Tier 2) ──────────────────────────────────────────────────────

def _gather_doc_meta(book: epub.EpubBook) -> list[dict]:
    """Build per-doc metadata list for AI analysis input."""
    toc_entries = _flatten_toc(book.toc) if book.toc else []
    toc_map = {_normalize_href(href): title for title, href in toc_entries}

    meta_list: list[dict] = []
    for pos, spine_entry in enumerate(book.spine):
        item_id = spine_entry[0] if isinstance(spine_entry, tuple) else spine_entry
        item = book.get_item_with_id(item_id)
        if item is None or item.get_type() != ITEM_DOCUMENT:
            continue

        filename = item.file_name or ""
        norm_fn  = _normalize_href(filename)

        toc_title = toc_map.get(norm_fn)
        if toc_title is None:
            base = PurePosixPath(norm_fn).name
            for href, title in toc_map.items():
                if PurePosixPath(href).name == base:
                    toc_title = title
                    break

        try:
            raw  = item.get_content().decode("utf-8", errors="replace")
            soup = BeautifulSoup(raw, "html.parser")
            text = soup.get_text(separator=" ", strip=True)[:300]
            h1   = soup.find("h1")
            h2   = soup.find("h2")
            size = len(raw)
        except Exception:
            text, h1, h2, size = "", None, None, 0

        meta_list.append({
            "doc_id"          : item_id,
            "name"            : filename,
            "spine_pos"       : pos,
            "toc_title"       : toc_title,
            "size_bytes"      : size,
            "first_300_chars" : text,
            "first_h1"        : h1.get_text(strip=True) if h1 else None,
            "first_h2"        : h2.get_text(strip=True) if h2 else None,
        })
    return meta_list


async def build_chapter_plan_with_ai(
    book        : epub.EpubBook,
    epub_path   : str,
    ai_limiter,           # AIRateLimiter (type quoted to avoid import cycle)
    force       : bool = False,
) -> list[ChapterPlan]:
    """
    Tier 2: AI-driven chapter plan. Cache by EPUB SHA256 (re-process = 0 AI cost).

    Flow:
      1. Hash EPUB → cache lookup (skip AI if hit + not force)
      2. Gather doc metadata
      3. Call AI analyzer
      4. Apply decisions → ChapterPlan list
      5. Cache result
      6. Fallback to rule-based (build_chapter_plan) on any failure
    """
    from ai.agents import ai_analyze_epub_structure

    # Cache lookup
    try:
        file_hash = _epub_hash(epub_path)
    except OSError as e:
        logger.warning("[EpubStructure] hash failed: %s — fallback rules", e)
        return build_chapter_plan(book)

    cache = _load_cache()
    cached = cache.get(file_hash) if not force else None
    if cached:
        logger.info("[EpubStructure] AI plan cache hit for %s", os.path.basename(epub_path))
        decisions = cached.get("decisions", [])
    else:
        meta = _gather_doc_meta(book)
        if not meta:
            return build_chapter_plan(book)

        print(
            f"  🤖 AI analyzing EPUB structure ({len(meta)} docs)...",
            flush=True,
        )
        decisions = await ai_analyze_epub_structure(meta, ai_limiter)
        if decisions is None:
            print(
                f"  ⚠ AI analyzer failed → fallback to rule-based plan",
                flush=True,
            )
            return build_chapter_plan(book)

        cache[file_hash] = {
            "filename" : os.path.basename(epub_path),
            "decisions": decisions,
        }
        _save_cache(cache)

    return _apply_decisions(book, decisions)


def _apply_decisions(book: epub.EpubBook, decisions: list[dict]) -> list[ChapterPlan]:
    """
    Convert AI decisions list → ChapterPlan list.
    decisions: [{doc_id, kind, title, merge_with_prev, reason}, ...]
    """
    dec_map = {d["doc_id"]: d for d in decisions if isinstance(d, dict) and d.get("doc_id")}

    matter_bucket : list[str] = []
    skip_count    : int       = 0
    chapters      : list[ChapterPlan] = []
    current       : ChapterPlan | None = None
    chapter_idx   = 0

    for spine_entry in book.spine:
        item_id = spine_entry[0] if isinstance(spine_entry, tuple) else spine_entry
        item = book.get_item_with_id(item_id)
        if item is None or item.get_type() != ITEM_DOCUMENT:
            continue

        dec = dec_map.get(item_id)
        if dec is None:
            # AI missed this doc → conservative: treat as continuation if chapter open, else matter
            if current is not None:
                current.doc_ids.append(item_id)
            else:
                matter_bucket.append(item_id)
            continue

        kind  = dec.get("kind", "chapter")
        title = dec.get("title")
        merge = dec.get("merge_with_prev", False)

        if kind == "skip":
            if current is not None:
                chapters.append(current)
                current = None
            skip_count += 1
            continue

        if kind in ("frontmatter", "backmatter"):
            if current is not None:
                chapters.append(current)
                current = None
            matter_bucket.append(item_id)
            continue

        # chapter or divider — both written to disk
        if merge and current is not None:
            current.doc_ids.append(item_id)
            continue

        if current is not None:
            chapters.append(current)
        chapter_idx += 1
        current = ChapterPlan(
            index   = chapter_idx,
            kind    = "chapter" if kind == "chapter" else "chapter",  # divider stored as chapter, just title differs
            title   = title or f"Chapter {chapter_idx}",
            doc_ids = [item_id],
        )

    if current is not None:
        chapters.append(current)

    plan: list[ChapterPlan] = []
    if matter_bucket:
        plan.append(ChapterPlan(
            index=0, kind="matter", title="Front Matter", doc_ids=matter_bucket,
        ))
    plan.extend(chapters)

    logger.info(
        "[EpubStructure] AI plan: %d chapters + %d matter + %d skipped",
        len(chapters), len(matter_bucket), skip_count,
    )
    return plan


__all__ = [
    "ChapterPlan",
    "build_chapter_plan",
    "build_chapter_plan_with_ai",
    "smart_title_from_toc",
    "FRONT_MATTER_KEYWORDS",
    "BACK_MATTER_KEYWORDS",
    "SKIP_KEYWORDS",
    "MATTER_FILENAME_PATTERNS",
    "SKIP_FILENAME_PATTERNS",
]
