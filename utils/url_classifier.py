"""
utils/url_classifier.py — Upfront URL classification cache (v1.0.5).

User pastes a URL. It may point at:
  - Chapter page (start scraping immediately)
  - Index page / story root (need to find chapter 1 first)

Classifier runs 1 AI call per new URL, caches result so re-runs are
free. Detects language + chapter_keyword for multi-lang support
(CN/JP/RU/...).

Cache file: data/url_classifications.json
Format:
  {
    "https://example.com/story/abc": {
      "classified_at": "2026-05-17T12:34:56Z",
      "page_type": "chapter" | "index" | "story_root" | "unknown",
      "language": "en",
      "chapter_keyword": "Chapter",
      "first_chapter_url": "https://...",
      "confidence": 0.95
    }
  }

Cache hit policy: if URL exact-matches and `confidence >= 0.7`, skip AI.
Force re-classify: delete the entry from JSON manually.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from config import DATA_DIR

if TYPE_CHECKING:
    from ai.client import AIRateLimiter
    from core.session_pool import DomainSessionPool, PlaywrightPool


logger = logging.getLogger(__name__)

_CACHE_FILE = os.path.join(DATA_DIR, "url_classifications.json")
_CACHE_LOCK = threading.Lock()
_MIN_CACHE_CONFIDENCE = 0.7


def _load_cache() -> dict:
    if not os.path.exists(_CACHE_FILE):
        return {}
    try:
        with open(_CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f) or {}
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("[URLClassifier] cache load failed: %s — resetting", e)
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
            logger.warning("[URLClassifier] cache save failed: %s", e)


async def classify_url(
    url        : str,
    pool       : "DomainSessionPool",
    pw_pool    : "PlaywrightPool",
    ai_limiter : "AIRateLimiter",
    *,
    force      : bool = False,
) -> dict | None:
    """
    Classify URL upfront. Returns dict per _S_INPUT_CLASSIFY schema or None
    on failure.

    Flow:
      1. Cache lookup (skip if `force=True`)
      2. Fetch URL HTML
      3. AI classify
      4. Cache result if confidence >= threshold
      5. Return classification
    """
    cache = _load_cache()
    cached = cache.get(url)
    if not force and cached and cached.get("confidence", 0) >= _MIN_CACHE_CONFIDENCE:
        logger.info(
            "[URLClassifier] cache hit %s page_type=%s lang=%s",
            url[:60], cached.get("page_type"), cached.get("language"),
        )
        return cached

    # Fetch HTML for classification
    from core.fetch import fetch_page
    try:
        status, html = await fetch_page(url, pool, pw_pool, profile=None)
    except asyncio.CancelledError:
        raise
    except Exception as e:
        logger.warning("[URLClassifier] fetch failed for %s: %s", url, e)
        return None

    if status >= 400 or not html or len(html) < 200:
        logger.warning(
            "[URLClassifier] bad fetch status=%s len=%d for %s",
            status, len(html or ""), url,
        )
        return None

    # AI classify
    from ai.agents import ai_classify_input_url
    result = await ai_classify_input_url(html, url, ai_limiter)
    if not result:
        return None

    # Stamp + cache
    result["classified_at"] = datetime.now(timezone.utc).isoformat()
    if result.get("confidence", 0) >= _MIN_CACHE_CONFIDENCE:
        cache[url] = result
        _save_cache(cache)
        logger.info(
            "[URLClassifier] cached %s page_type=%s lang=%s conf=%.2f",
            url[:60], result.get("page_type"), result.get("language"),
            result.get("confidence", 0),
        )

    return result


async def resolve_to_chapter_url(
    url        : str,
    pool       : "DomainSessionPool",
    pw_pool    : "PlaywrightPool",
    ai_limiter : "AIRateLimiter",
) -> tuple[str, dict | None]:
    """
    High-level helper for main.py: classify URL and return (final_url, info).

    If user paste:
      - chapter URL  → return as-is + classification
      - index URL    → return first_chapter_url + classification
      - unknown      → return original URL + classification (best-effort)
      - AI failed    → return original URL + None (fallback to old behavior)
    """
    info = await classify_url(url, pool, pw_pool, ai_limiter)
    if not info:
        print(
            f"  [URLClassifier] ℹ️  Không classify được, dùng URL gốc: {url[:60]}",
            flush=True,
        )
        return url, None

    page_type = info.get("page_type", "unknown")
    lang      = info.get("language", "unknown")
    first_url = info.get("first_chapter_url")

    if page_type in ("index", "story_root") and first_url and first_url != url:
        print(
            f"  [URLClassifier] 📚 {page_type} detected → redirect chapter 1: "
            f"{first_url[:70]} (lang={lang})",
            flush=True,
        )
        return first_url, info

    if page_type == "chapter":
        print(
            f"  [URLClassifier] 📖 Chapter detected (lang={lang}) — start scrape",
            flush=True,
        )
    else:
        print(
            f"  [URLClassifier] ⚠ page_type={page_type!r} lang={lang} — best-effort",
            flush=True,
        )

    return url, info


__all__ = ["classify_url", "resolve_to_chapter_url"]
