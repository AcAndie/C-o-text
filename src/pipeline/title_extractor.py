"""
pipeline/title_extractor.py — Title extraction blocks.

Batch B: Xóa to_config(), from_config(), make_title_block(), registry dict.
  Blocks được instantiate trực tiếp bởi PipelineRunner._title_blocks().

Fix TITLE-A: SelectorTitleBlock apply strip_site_suffix() unconditionally.
Fix TITLE-B: H1TitleBlock apply strip_site_suffix() trước normalize_title().

Blocks (theo thứ tự ưu tiên trong title_vote chain):
    SelectorTitleBlock  — CSS selector từ profile (chính xác nhất)
    H1TitleBlock        — <h1> tag
    TitleTagBlock       — <title> tag, stripped site suffix
    OgTitleBlock        — og:title meta, stripped site suffix
    UrlSlugTitleBlock   — Extract từ URL slug (fallback cuối)
"""
from __future__ import annotations

import asyncio
import re
import time
from urllib.parse import unquote, urlparse

from pipeline.base import BlockType, BlockResult, PipelineContext, ScraperBlock
from utils.string_helpers import normalize_title, strip_site_suffix


_MIN_TITLE_LEN = 3
# Fix TITLE-C: titles longer than this are almost certainly extracted from
# a container like <select> dropdown (FFN chap_select), <nav>, or full body.
# Real chapter titles top out around 100-150 chars even with long subtitles.
# Reject + fall through to next title block in chain.
_MAX_TITLE_LEN = 200

# Fix TITLE-D: selectors pointing at these element types extract container
# text (all children concatenated) — almost never a single chapter title.
# Drop selector candidate at execute-time even if AI/profile chose them.
_FORBIDDEN_TITLE_TAGS = {"select", "option", "nav", "ul", "ol", "table", "tbody"}

# URL slug → title helper (inlined from former core/extractor.py in Phase 6).
_SLUG_CLEAN_RE   = re.compile(r"[-_]+")
_SLUG_CHAPTER_RE = re.compile(
    r"(?:chapter|chap|ch|episode|ep|part)[_-]?\d+", re.IGNORECASE,
)


def _title_from_url(url: str) -> str | None:
    """
    Extract title hint từ URL path slug. Last-resort fallback cho
    UrlSlugTitleBlock.

    Ví dụ:
        /chapter-5-the-rise-of-heroes → "The Rise Of Heroes"
        /s/12345678/5/My-Story-Title  → "My Story Title"
        /fiction/55418/the-wandering-inn → "The Wandering Inn"

    v1.0.13: reject file paths (no http/https scheme). EPUB orchestrator
    sets ctx.url = epub file path → URL slug ate full Windows path as title.
    """
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return None
        path     = parsed.path
        segments = [s for s in path.strip("/").split("/") if s]
        if not segments:
            return None

        # Slug dài nhất không phải số thuần
        slug = None
        for seg in reversed(segments):
            if not seg.isdigit() and len(seg) > 3:
                slug = seg
                break
        if not slug:
            return None

        slug  = unquote(slug)
        slug  = _SLUG_CHAPTER_RE.sub("", slug).strip("-_ ")
        words = _SLUG_CLEAN_RE.sub(" ", slug).strip()
        if not words or len(words) < 3:
            return None
        return words.title()
    except Exception:
        return None


# ── 1. Selector Title Block ───────────────────────────────────────────────────

class SelectorTitleBlock(ScraperBlock):
    """CSS selector title extraction — highest confidence."""
    block_type = BlockType.TITLE
    name       = "selector"

    def __init__(self, selector: str | None = None) -> None:
        self.selector = selector

    async def execute(self, ctx: PipelineContext) -> BlockResult:
        start = time.monotonic()
        try:
            sel = self.selector or ctx.profile.get("title_selector")
            if not sel:
                return self._timed(BlockResult.skipped("no title_selector"), start)

            soup = ctx.soup
            if soup is None:
                return self._timed(BlockResult.skipped("no soup"), start)

            el = soup.select_one(sel)
            if el is None:
                return self._timed(
                    BlockResult.failed(f"title selector {sel!r} matched nothing"),
                    start,
                )

            # Fix TITLE-D: reject container elements (select/nav/ul/...) — they
            # concat ALL child text. Common AI mistake: picking <select> dropdown
            # of chapter list as title selector (FFN `select#chap_select`).
            tag_name = (getattr(el, "name", "") or "").lower()
            if tag_name in _FORBIDDEN_TITLE_TAGS:
                return self._timed(
                    BlockResult.failed(
                        f"title selector {sel!r} resolves to <{tag_name}> container"
                    ),
                    start,
                )

            raw = el.get_text(strip=True)

            # Fix TITLE-A: Apply strip_site_suffix() unconditionally — handles
            # site name suffixes, FFN fanfic descriptors, AND word count artifacts
            # ("[ ... words ]") which appear in any element, not just <title>.
            raw  = strip_site_suffix(raw)
            text = normalize_title(raw)

            if len(text) < _MIN_TITLE_LEN:
                return self._timed(
                    BlockResult.failed(f"title too short: {text!r}"),
                    start,
                )

            # Fix TITLE-C: reject suspiciously long titles. Real chapter titles
            # top out ~150 chars. >200 = container text leak (multiple options
            # joined, nav text, etc). Fall through to H1/TitleTag fallback.
            if len(text) > _MAX_TITLE_LEN:
                return self._timed(
                    BlockResult.failed(
                        f"title selector {sel!r} produced {len(text)} chars — "
                        f"likely container leak, falling through"
                    ),
                    start,
                )

            return self._timed(
                BlockResult.success(
                    data        = text,
                    method_used = f"title_selector:{sel}",
                    confidence  = 0.95,
                ),
                start,
            )
        except asyncio.CancelledError:
            raise
        except Exception as e:
            return self._timed(BlockResult.failed(str(e) or repr(e)), start)


# ── 2. H1 Title Block ─────────────────────────────────────────────────────────

class H1TitleBlock(ScraperBlock):
    """Extract title từ <h1> tag."""
    block_type = BlockType.TITLE
    name       = "h1_tag"

    async def execute(self, ctx: PipelineContext) -> BlockResult:
        start = time.monotonic()
        try:
            soup = ctx.soup
            if soup is None:
                return self._timed(BlockResult.skipped("no soup"), start)

            for tag in ("h1", "h2"):
                el = soup.find(tag)
                if el:
                    # Fix TITLE-B: Apply strip_site_suffix() để strip
                    # "[ ... words ]" và các artifacts trước normalize.
                    raw  = strip_site_suffix(el.get_text(strip=True))
                    text = normalize_title(raw)
                    # Fix TITLE-C: length sanity (skip if container leak)
                    if _MIN_TITLE_LEN <= len(text) <= _MAX_TITLE_LEN:
                        return self._timed(
                            BlockResult.success(
                                data        = text,
                                method_used = tag,
                                confidence  = 0.80,
                            ),
                            start,
                        )

            return self._timed(BlockResult.failed("no h1/h2 found"), start)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            return self._timed(BlockResult.failed(str(e) or repr(e)), start)


# ── 3. Title Tag Block ────────────────────────────────────────────────────────

class TitleTagBlock(ScraperBlock):
    """Extract title từ <title> HTML tag, stripped site suffix."""
    block_type = BlockType.TITLE
    name       = "title_tag"

    _SEP_RE = re.compile(r"[\|–—]")

    async def execute(self, ctx: PipelineContext) -> BlockResult:
        start = time.monotonic()
        try:
            soup = ctx.soup
            if soup is None:
                return self._timed(BlockResult.skipped("no soup"), start)

            tag = soup.find("title")
            if not tag:
                return self._timed(BlockResult.failed("no <title> tag"), start)

            raw = tag.get_text(strip=True)
            if self._SEP_RE.search(raw):
                raw = strip_site_suffix(raw)
            text = normalize_title(raw)

            if len(text) < _MIN_TITLE_LEN:
                return self._timed(BlockResult.failed("title tag too short"), start)
            if len(text) > _MAX_TITLE_LEN:
                return self._timed(
                    BlockResult.failed(f"title tag too long ({len(text)} chars)"),
                    start,
                )

            return self._timed(
                BlockResult.success(
                    data        = text,
                    method_used = "title_tag",
                    confidence  = 0.65,
                ),
                start,
            )
        except asyncio.CancelledError:
            raise
        except Exception as e:
            return self._timed(BlockResult.failed(str(e) or repr(e)), start)


# ── 4. OG Title Block ─────────────────────────────────────────────────────────

class OgTitleBlock(ScraperBlock):
    """Extract title từ og:title meta tag."""
    block_type = BlockType.TITLE
    name       = "og_title"

    _SEP_RE = re.compile(r"[\|–—]")

    async def execute(self, ctx: PipelineContext) -> BlockResult:
        start = time.monotonic()
        try:
            soup = ctx.soup
            if soup is None:
                return self._timed(BlockResult.skipped("no soup"), start)

            og = soup.find("meta", property="og:title")
            if not og or not og.get("content"):
                return self._timed(BlockResult.failed("no og:title"), start)

            raw = og["content"].strip()
            if self._SEP_RE.search(raw):
                raw = strip_site_suffix(raw)
            text = normalize_title(raw)

            if len(text) < _MIN_TITLE_LEN:
                return self._timed(BlockResult.failed("og:title too short"), start)
            if len(text) > _MAX_TITLE_LEN:
                return self._timed(
                    BlockResult.failed(f"og:title too long ({len(text)} chars)"),
                    start,
                )

            return self._timed(
                BlockResult.success(
                    data        = text,
                    method_used = "og_title",
                    confidence  = 0.65,
                ),
                start,
            )
        except asyncio.CancelledError:
            raise
        except Exception as e:
            return self._timed(BlockResult.failed(str(e) or repr(e)), start)


# ── 5. URL Slug Title Block ───────────────────────────────────────────────────

class UrlSlugTitleBlock(ScraperBlock):
    """Extract title từ URL path slug — fallback cuối cùng."""
    block_type = BlockType.TITLE
    name       = "url_slug"

    async def execute(self, ctx: PipelineContext) -> BlockResult:
        start = time.monotonic()
        try:
            text = _title_from_url(ctx.url)
            if text and len(text) >= _MIN_TITLE_LEN:
                return self._timed(
                    BlockResult.fallback(
                        data        = normalize_title(text),
                        method_used = "url_slug",
                        confidence  = 0.40,
                    ),
                    start,
                )
            return self._timed(BlockResult.failed("cannot extract title from URL"), start)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            return self._timed(BlockResult.failed(str(e) or repr(e)), start)