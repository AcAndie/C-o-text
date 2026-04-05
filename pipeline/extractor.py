"""
pipeline/extractor.py — Content extraction blocks.

v2 changes:
  EXT-1: AIExtractBlock được implement thật — không còn luôn trả về SKIPPED.
         Gọi Gemini để extract content khi mọi heuristic đều thất bại.
         Đây là "last resort" thật sự, không phải stub.

  EXT-2: FallbackListExtractBlock bỏ "body text" fallback.
         extract_plain_text(body) trên toàn bộ <body> lấy ra nav, footer,
         ads, script text — garbage. Tốt hơn là fail rõ ràng và để
         AIExtractBlock xử lý.

  EXT-3: AIExtractBlock đọc ai_limiter từ ctx.runtime — không còn
         ctx.profile.get("_ai_limiter").

Blocks:
    SelectorExtractBlock     — CSS selector từ profile (fastest)
    JsonLdExtractBlock       — JSON-LD Article schema
    DensityHeuristicBlock    — Text density scoring (works on any site)
    XPathExtractBlock        — XPath alternative
    FallbackListExtractBlock — Known selector list
    AIExtractBlock           — Gemini AI extraction (last resort, REAL)
"""
from __future__ import annotations

import asyncio
import json
import math
import time
from typing import Any

from bs4 import BeautifulSoup, Tag

from config import FALLBACK_CONTENT_SELECTORS
from pipeline.base import BlockType, BlockResult, PipelineContext, ScraperBlock

_MIN_CONTENT_CHARS = 150
_MIN_PROSE_WORDS   = 30


# ── 1. Selector Extract ────────────────────────────────────────────────────────

class SelectorExtractBlock(ScraperBlock):
    """CSS selector đã học — primary strategy, fastest."""
    block_type = BlockType.EXTRACT
    name       = "selector"

    def __init__(
        self,
        selector : str | None = None,
        min_chars: int = _MIN_CONTENT_CHARS,
    ) -> None:
        self.selector  = selector
        self.min_chars = min_chars

    async def execute(self, ctx: PipelineContext) -> BlockResult:
        start = time.monotonic()
        try:
            sel = self.selector or ctx.profile.get("content_selector")
            if not sel:
                return self._timed(BlockResult.skipped("no content_selector"), start)

            soup = ctx.soup
            if soup is None:
                return self._timed(BlockResult.skipped("no soup"), start)

            el = soup.select_one(sel)
            if el is None:
                return self._timed(
                    BlockResult.failed(f"selector {sel!r} matched nothing"),
                    start,
                )

            text = _format_element(el, ctx.profile.get("formatting_rules"))
            if len(text.strip()) < self.min_chars:
                return self._timed(
                    BlockResult.failed(
                        f"selector {sel!r}: {len(text.strip())} chars < {self.min_chars}"
                    ),
                    start,
                )

            return self._timed(
                BlockResult.success(
                    data        = text,
                    method_used = f"selector:{sel}",
                    confidence  = 0.95,
                    char_count  = len(text),
                    selector    = sel,
                ),
                start,
            )
        except asyncio.CancelledError:
            raise
        except Exception as e:
            return self._timed(BlockResult.failed(str(e) or repr(e)), start)

    def to_config(self) -> dict:
        d: dict[str, Any] = {"type": self.name}
        if self.selector:
            d["selector"] = self.selector
        if self.min_chars != _MIN_CONTENT_CHARS:
            d["min_chars"] = self.min_chars
        return d

    @classmethod
    def from_config(cls, config: dict) -> "SelectorExtractBlock":
        return cls(
            selector  = config.get("selector"),
            min_chars = int(config.get("min_chars", _MIN_CONTENT_CHARS)),
        )


# ── 2. JSON-LD Extract ────────────────────────────────────────────────────────

class JsonLdExtractBlock(ScraperBlock):
    """
    Extract từ JSON-LD Article/BlogPosting schema.
    Không cần CSS selector — works even when DOM structure changes.
    """
    block_type = BlockType.EXTRACT
    name       = "json_ld"

    async def execute(self, ctx: PipelineContext) -> BlockResult:
        start = time.monotonic()
        try:
            soup = ctx.soup
            if soup is None:
                return self._timed(BlockResult.skipped("no soup"), start)

            for script in soup.find_all("script", type="application/ld+json"):
                try:
                    raw = script.get_text(strip=True)
                    if not raw:
                        continue
                    data  = json.loads(raw)
                    items = data if isinstance(data, list) else [data]
                    for item in items:
                        body = (
                            item.get("articleBody")
                            or item.get("text")
                            or item.get("description")
                        )
                        schema_type = item.get("@type", "")
                        if (
                            body
                            and isinstance(body, str)
                            and len(body.strip()) >= _MIN_CONTENT_CHARS
                            and schema_type in (
                                "Article", "BlogPosting", "NewsArticle",
                                "WebPage", "",
                            )
                        ):
                            return self._timed(
                                BlockResult.success(
                                    data        = body.strip(),
                                    method_used = f"json_ld:{schema_type or 'unknown'}",
                                    confidence  = 0.85,
                                    char_count  = len(body),
                                ),
                                start,
                            )
                except (json.JSONDecodeError, AttributeError):
                    continue

            return self._timed(BlockResult.failed("no usable JSON-LD"), start)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            return self._timed(BlockResult.failed(str(e) or repr(e)), start)

    def to_config(self) -> dict:
        return {"type": self.name}

    @classmethod
    def from_config(cls, config: dict) -> "JsonLdExtractBlock":
        return cls()


# ── 3. Density Heuristic ──────────────────────────────────────────────────────

class DensityHeuristicBlock(ScraperBlock):
    """
    Trafilatura-style: tìm block có mật độ text cao nhất.
    score = text_density × (1 - link_density) × log(text_len + 1)

    Works on any site without any selector knowledge.
    """
    block_type = BlockType.EXTRACT
    name       = "density_heuristic"

    _CANDIDATE_TAGS = frozenset({"article", "main", "section", "div", "td"})
    _SKIP_TAGS      = frozenset({
        "script", "style", "nav", "header", "footer",
        "aside", "form", "noscript", "iframe",
    })

    def __init__(self, min_chars: int = _MIN_CONTENT_CHARS) -> None:
        self.min_chars = min_chars

    async def execute(self, ctx: PipelineContext) -> BlockResult:
        start = time.monotonic()
        try:
            soup = ctx.soup
            if soup is None:
                return self._timed(BlockResult.skipped("no soup"), start)

            best_el    = None
            best_score = 0.0

            for el in soup.find_all(True):
                if not isinstance(el, Tag):
                    continue
                tag = el.name.lower() if el.name else ""
                if tag in self._SKIP_TAGS or tag not in self._CANDIDATE_TAGS:
                    continue

                score, text_len = self._score_element(el)
                if score > best_score and text_len >= self.min_chars:
                    best_score = score
                    best_el    = el

            if best_el is None or best_score == 0:
                return self._timed(
                    BlockResult.failed("no content block found by density"),
                    start,
                )

            text = _format_element(best_el, ctx.profile.get("formatting_rules"))
            if len(text.strip()) < self.min_chars:
                return self._timed(
                    BlockResult.failed(f"density winner too short: {len(text.strip())}c"),
                    start,
                )

            confidence = min(0.85, 0.4 + best_score * 0.1)

            return self._timed(
                BlockResult.success(
                    data          = text,
                    method_used   = "density_heuristic",
                    confidence    = confidence,
                    char_count    = len(text),
                    density_score = round(best_score, 3),
                ),
                start,
            )
        except asyncio.CancelledError:
            raise
        except Exception as e:
            return self._timed(BlockResult.failed(str(e) or repr(e)), start)

    def _score_element(self, el: Tag) -> tuple[float, int]:
        full_html    = str(el)
        html_len     = max(len(full_html), 1)
        text         = el.get_text(separator=" ", strip=True)
        text_len     = len(text)
        if text_len < 50:
            return 0.0, 0

        link_text    = "".join(
            a.get_text(separator=" ", strip=True) for a in el.find_all("a")
        )
        link_density = len(link_text) / max(text_len, 1)
        if link_density > 0.6:
            return 0.0, 0

        text_density = text_len / html_len
        p_count      = len(el.find_all("p"))
        p_bonus      = min(p_count * 0.05, 0.3)

        score = (
            text_density
            * (1.0 - link_density)
            * math.log(text_len + 1)
            * (1.0 + p_bonus)
        )
        return score, text_len

    def to_config(self) -> dict:
        d: dict[str, Any] = {"type": self.name}
        if self.min_chars != _MIN_CONTENT_CHARS:
            d["min_chars"] = self.min_chars
        return d

    @classmethod
    def from_config(cls, config: dict) -> "DensityHeuristicBlock":
        return cls(min_chars=int(config.get("min_chars", _MIN_CONTENT_CHARS)))


# ── 4. XPath Extract ──────────────────────────────────────────────────────────

class XPathExtractBlock(ScraperBlock):
    """XPath alternative cho sites dùng id/attribute phức tạp. Requires lxml."""
    block_type = BlockType.EXTRACT
    name       = "xpath"

    def __init__(self, xpath: str, min_chars: int = _MIN_CONTENT_CHARS) -> None:
        self.xpath     = xpath
        self.min_chars = min_chars

    async def execute(self, ctx: PipelineContext) -> BlockResult:
        start = time.monotonic()
        try:
            from lxml import etree  # type: ignore[import]

            html = ctx.html
            if not html:
                return self._timed(BlockResult.skipped("no html"), start)

            parser = etree.HTMLParser()
            tree   = etree.fromstring(html.encode("utf-8", errors="replace"), parser)
            nodes  = tree.xpath(self.xpath)

            if not nodes:
                return self._timed(
                    BlockResult.failed(f"xpath {self.xpath!r} matched nothing"),
                    start,
                )

            node = nodes[0]
            text = (node.text_content() if hasattr(node, "text_content") else str(node)).strip()

            if len(text) < self.min_chars:
                return self._timed(
                    BlockResult.failed(f"xpath result too short: {len(text)}c"),
                    start,
                )

            return self._timed(
                BlockResult.success(
                    data        = text,
                    method_used = f"xpath:{self.xpath[:40]}",
                    confidence  = 0.85,
                    char_count  = len(text),
                ),
                start,
            )
        except ImportError:
            return self._timed(BlockResult.skipped("lxml not installed"), start)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            return self._timed(BlockResult.failed(str(e) or repr(e)), start)

    def to_config(self) -> dict:
        d: dict[str, Any] = {"type": self.name, "xpath": self.xpath}
        if self.min_chars != _MIN_CONTENT_CHARS:
            d["min_chars"] = self.min_chars
        return d

    @classmethod
    def from_config(cls, config: dict) -> "XPathExtractBlock":
        return cls(
            xpath     = config.get("xpath", "//article"),
            min_chars = int(config.get("min_chars", _MIN_CONTENT_CHARS)),
        )


# ── 5. Fallback List Extract ──────────────────────────────────────────────────

class FallbackListExtractBlock(ScraperBlock):
    """
    Thử lần lượt FALLBACK_CONTENT_SELECTORS đã biết.

    Không còn "body text" fallback — extract_plain_text(<body>) là garbage
    vì nó kéo cả nav/footer/ads vào. Thất bại rõ ràng tốt hơn garbage.
    Nếu fallback list cũng fail → AIExtractBlock sẽ xử lý.
    """
    block_type = BlockType.EXTRACT
    name       = "fallback_list"

    def __init__(
        self,
        extra_selectors: list[str] | None = None,
        min_chars      : int = _MIN_CONTENT_CHARS,
    ) -> None:
        self.extra_selectors = extra_selectors or []
        self.min_chars       = min_chars

    async def execute(self, ctx: PipelineContext) -> BlockResult:
        start = time.monotonic()
        try:
            soup = ctx.soup
            if soup is None:
                return self._timed(BlockResult.skipped("no soup"), start)

            selectors = list(self.extra_selectors) + list(FALLBACK_CONTENT_SELECTORS)

            for sel in selectors:
                try:
                    el = soup.select_one(sel)
                    if el is None:
                        continue
                    text = _format_element(el, ctx.profile.get("formatting_rules"))
                    if len(text.strip()) >= self.min_chars:
                        return self._timed(
                            BlockResult.fallback(
                                data        = text,
                                method_used = f"fallback_list:{sel}",
                                confidence  = 0.7,
                            ),
                            start,
                        )
                except Exception:
                    continue

            # KHÔNG fallback sang body text — AIExtractBlock xử lý case này
            return self._timed(
                BlockResult.failed("all known selectors exhausted"),
                start,
            )
        except asyncio.CancelledError:
            raise
        except Exception as e:
            return self._timed(BlockResult.failed(str(e) or repr(e)), start)

    def to_config(self) -> dict:
        d: dict[str, Any] = {"type": self.name}
        if self.extra_selectors:
            d["extra_selectors"] = self.extra_selectors
        return d

    @classmethod
    def from_config(cls, config: dict) -> "FallbackListExtractBlock":
        return cls(
            extra_selectors = config.get("extra_selectors", []),
            min_chars       = int(config.get("min_chars", _MIN_CONTENT_CHARS)),
        )


# ── 6. AI Extract Block ───────────────────────────────────────────────────────

class AIExtractBlock(ScraperBlock):
    """
    AI-powered content extraction — last resort THẬT SỰ.

    Gọi Gemini để identify và extract chapter content khi tất cả
    heuristic blocks thất bại. Đây là "last resort" thật, không phải stub.

    Confidence thấp hơn selector (0.75) vì AI có thể miss formatting
    đặc biệt (tables, system boxes, v.v.) mà profile-based extraction
    sẽ xử lý tốt hơn.

    Đọc ai_limiter từ ctx.runtime — không còn ctx.profile["_ai_limiter"].
    """
    block_type = BlockType.EXTRACT
    name       = "ai_extract"

    def __init__(self, min_chars: int = _MIN_CONTENT_CHARS) -> None:
        self.min_chars = min_chars

    async def execute(self, ctx: PipelineContext) -> BlockResult:
        start = time.monotonic()
        try:
            ai_limiter = ctx.runtime.ai_limiter
            if ai_limiter is None:
                return self._timed(
                    BlockResult.skipped("no ai_limiter in runtime"),
                    start,
                )

            html = ctx.html
            if not html:
                return self._timed(BlockResult.skipped("no html"), start)

            from ai.agents import ai_extract_content
            content = await ai_extract_content(html, ctx.url, ai_limiter)

            if not content or len(content.strip()) < self.min_chars:
                return self._timed(
                    BlockResult.failed(
                        f"AI returned {len(content.strip()) if content else 0} chars"
                        f" (min={self.min_chars})"
                    ),
                    start,
                )

            return self._timed(
                BlockResult.fallback(   # fallback vì không từ learned selector
                    data        = content.strip(),
                    method_used = "ai_extract",
                    confidence  = 0.75,
                    char_count  = len(content),
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
    def from_config(cls, config: dict) -> "AIExtractBlock":
        return cls()


# ── Utility ────────────────────────────────────────────────────────────────────

def _format_element(el: Tag, formatting_rules: dict | None) -> str:
    """Format element → Markdown dùng MarkdownFormatter hoặc plain text."""
    from core.formatter import MarkdownFormatter, extract_plain_text
    if formatting_rules:
        return MarkdownFormatter(formatting_rules).format(el)
    return extract_plain_text(el)


# ── Registry ───────────────────────────────────────────────────────────────────

_EXTRACT_BLOCK_MAP: dict[str, type[ScraperBlock]] = {
    "selector"         : SelectorExtractBlock,
    "json_ld"          : JsonLdExtractBlock,
    "density_heuristic": DensityHeuristicBlock,
    "xpath"            : XPathExtractBlock,
    "fallback_list"    : FallbackListExtractBlock,
    "ai_extract"       : AIExtractBlock,
}


def make_extract_block(config: dict) -> ScraperBlock:
    block_type = config.get("type", "fallback_list")
    cls = _EXTRACT_BLOCK_MAP.get(block_type)
    if cls is None:
        raise ValueError(
            f"Unknown extract block type: {block_type!r}. "
            f"Available: {list(_EXTRACT_BLOCK_MAP)}"
        )
    return cls.from_config(config)