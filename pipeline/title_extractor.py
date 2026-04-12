"""
pipeline/title_extractor.py — Title extraction blocks.

Blocks (theo thứ tự ưu tiên trong default chain):
    SelectorTitleBlock  — CSS selector từ profile (chính xác nhất)
    H1TitleBlock        — <h1> tag (phổ biến nhất)
    TitleTagBlock       — <title> tag, stripped site suffix
    OgTitleBlock        — og:title meta, stripped site suffix
    UrlSlugTitleBlock   — Extract từ URL slug (fallback cuối)

Tất cả blocks đều chạy qua normalize_title() để chuẩn hóa kết quả.
Kết quả cuối được chọn qua majority vote trong TitleChainBlock (executor xử lý).

Fix TITLE-A: SelectorTitleBlock apply strip_site_suffix() khi el.name == "title".
  Trước: selector="title" → normalize(raw) → full raw title với site suffix còn nguyên.
         AI#5 thường learn "title" làm title_selector, route sang SelectorTitleBlock
         thay vì TitleTagBlock, mất hoàn toàn suffix stripping.
  Sau:   Khi element là <title> HTML tag → apply strip_site_suffix() trước normalize().
         Đây là semantic contract của <title> element: nó LUÔN LUÔN chứa site suffix.
         Không phải special-case mà là hoàn thiện contract giống TitleTagBlock.
"""
from __future__ import annotations

import asyncio
import re
import time

from pipeline.base import BlockType, BlockResult, PipelineContext, ScraperBlock
from utils.string_helpers import normalize_title, strip_site_suffix


_MIN_TITLE_LEN = 3


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

            raw = el.get_text(strip=True)

            # Fix TITLE-A: <title> HTML element luôn chứa site suffix và fanfic
            # descriptor — apply strip_site_suffix() như TitleTagBlock làm.
            # Condition: el.name check DOM element type, không phải selector string,
            # vì selector "div.chapter-container h1" cũng có thể chứa "title" substring.
            if el.name and el.name.lower() == "title":
                raw = strip_site_suffix(raw)

            text = normalize_title(raw)
            if len(text) < _MIN_TITLE_LEN:
                return self._timed(
                    BlockResult.failed(f"title too short: {text!r}"),
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

    def to_config(self) -> dict:
        d: dict = {"type": self.name}
        if self.selector:
            d["selector"] = self.selector
        return d

    @classmethod
    def from_config(cls, config: dict) -> "SelectorTitleBlock":
        return cls(selector=config.get("selector"))


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

            # Thử h1, h2 theo thứ tự
            for tag in ("h1", "h2"):
                el = soup.find(tag)
                if el:
                    text = normalize_title(el.get_text(strip=True))
                    if len(text) >= _MIN_TITLE_LEN:
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

    def to_config(self) -> dict:
        return {"type": self.name}

    @classmethod
    def from_config(cls, config: dict) -> "H1TitleBlock":
        return cls()


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

    def to_config(self) -> dict:
        return {"type": self.name}

    @classmethod
    def from_config(cls, config: dict) -> "TitleTagBlock":
        return cls()


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

    def to_config(self) -> dict:
        return {"type": self.name}

    @classmethod
    def from_config(cls, config: dict) -> "OgTitleBlock":
        return cls()


# ── 5. URL Slug Title Block ───────────────────────────────────────────────────

class UrlSlugTitleBlock(ScraperBlock):
    """Extract title từ URL path slug — fallback cuối cùng."""
    block_type = BlockType.TITLE
    name       = "url_slug"

    async def execute(self, ctx: PipelineContext) -> BlockResult:
        start = time.monotonic()
        try:
            from core.extractor import _title_from_url
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

    def to_config(self) -> dict:
        return {"type": self.name}

    @classmethod
    def from_config(cls, config: dict) -> "UrlSlugTitleBlock":
        return cls()


# ── Registry ──────────────────────────────────────────────────────────────────

_TITLE_BLOCK_MAP: dict[str, type[ScraperBlock]] = {
    "selector" : SelectorTitleBlock,
    "h1_tag"   : H1TitleBlock,
    "title_tag": TitleTagBlock,
    "og_title" : OgTitleBlock,
    "url_slug" : UrlSlugTitleBlock,
}


def make_title_block(config: dict) -> ScraperBlock:
    """Factory: tạo title block từ StepConfig dict."""
    block_type = config.get("type", "h1_tag")
    cls = _TITLE_BLOCK_MAP.get(block_type)
    if cls is None:
        raise ValueError(
            f"Unknown title block type: {block_type!r}. "
            f"Available: {list(_TITLE_BLOCK_MAP)}"
        )
    return cls.from_config(config)