"""
pipeline/extractor.py — Content extraction blocks.

Blocks (theo thứ tự ưu tiên trong default chain):
    SelectorExtractBlock     — CSS selector từ learned profile (nhanh nhất)
    JsonLdExtractBlock       — JSON-LD Article/BlogPosting schema (nhiều site embed sẵn)
    DensityHeuristicBlock    — Trafilatura-style: tìm block có mật độ text cao nhất
    XPathExtractBlock        — XPath alternative cho sites dùng id/attribute phức tạp
    FallbackListExtractBlock — Thử danh sách FALLBACK_CONTENT_SELECTORS đã biết
    AIExtractBlock           — AI last resort (tốn API calls, chỉ dùng khi mọi thứ fail)

Content Quality Scoring (dùng trong DensityHeuristic):
    Mỗi block element được chấm điểm:
        text_density = text_len / max(html_len, 1)
        link_density = link_text_len / max(text_len, 1)
        score = text_density * (1 - link_density) * log(text_len + 1)
    Block có score cao nhất = main content.
"""
from __future__ import annotations

import asyncio
import json
import math
import re
import time
from typing import Any

from bs4 import BeautifulSoup, Tag

from config import FALLBACK_CONTENT_SELECTORS
from pipeline.base import BlockType, BlockResult, PipelineContext, ScraperBlock

_MIN_CONTENT_CHARS = 150   # Tối thiểu để coi là content hợp lệ
_MIN_PROSE_WORDS   = 30    # Tối thiểu word count cho prose richness check


# ── 1. Selector Extract Block ─────────────────────────────────────────────────

class SelectorExtractBlock(ScraperBlock):
    """
    Extract content bằng CSS selector đã học từ profile.
    Primary strategy — nhanh nhất khi profile đã có selector tốt.
    """
    block_type = BlockType.EXTRACT
    name       = "selector"

    def __init__(self, selector: str | None = None, min_chars: int = _MIN_CONTENT_CHARS) -> None:
        # selector=None → đọc từ ctx.profile["content_selector"] khi execute
        self.selector  = selector
        self.min_chars = min_chars

    async def execute(self, ctx: PipelineContext) -> BlockResult:
        start = time.monotonic()
        try:
            sel = self.selector or ctx.profile.get("content_selector")
            if not sel:
                return self._timed(BlockResult.skipped("no selector"), start)

            soup = ctx.soup
            if soup is None:
                return self._timed(BlockResult.skipped("no soup in context"), start)

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
                        f"selector {sel!r} returned only {len(text.strip())} chars "
                        f"(min={self.min_chars})"
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


# ── 2. JSON-LD Extract Block ──────────────────────────────────────────────────

class JsonLdExtractBlock(ScraperBlock):
    """
    Extract content từ JSON-LD structured data (Article / BlogPosting schema).
    
    Nhiều web novel site nhúng Article schema:
        <script type="application/ld+json">
        {"@type": "Article", "articleBody": "..."}
        </script>
    
    Kỹ thuật này hoạt động ngay cả khi CSS selectors thay đổi.
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
                    data = json.loads(raw)
                    # Handle @graph arrays
                    items = data if isinstance(data, list) else [data]
                    for item in items:
                        body = (
                            item.get("articleBody")
                            or item.get("text")
                            or item.get("description")
                        )
                        schema_type = item.get("@type", "")
                        if body and isinstance(body, str) and len(body.strip()) >= _MIN_CONTENT_CHARS:
                            if schema_type in ("Article", "BlogPosting", "NewsArticle", "WebPage", ""):
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

            return self._timed(BlockResult.failed("no usable JSON-LD found"), start)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            return self._timed(BlockResult.failed(str(e) or repr(e)), start)

    def to_config(self) -> dict:
        return {"type": self.name}

    @classmethod
    def from_config(cls, config: dict) -> "JsonLdExtractBlock":
        return cls()


# ── 3. Density Heuristic Block ────────────────────────────────────────────────

class DensityHeuristicBlock(ScraperBlock):
    """
    Trafilatura-inspired content extraction bằng text density scoring.
    
    Không cần CSS selector — tìm block có mật độ text cao nhất:
        score = text_density × (1 - link_density) × log(text_len + 1)
    
    Loại bỏ blocks có link_density cao (navigation menus, footers).
    Ưu tiên blocks có nhiều <p> tags (văn xuôi).
    
    Works on ANY site kể cả khi selector hỏng hoàn toàn.
    """
    block_type = BlockType.EXTRACT
    name       = "density_heuristic"

    # Tags được xét là "content container"
    _CANDIDATE_TAGS = frozenset({
        "article", "main", "section", "div", "td",
    })
    # Tags bị loại (chắc chắn không phải content)
    _SKIP_TAGS = frozenset({
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
                if tag in self._SKIP_TAGS:
                    continue
                if tag not in self._CANDIDATE_TAGS:
                    continue

                score, text_len = self._score_element(el)
                if score > best_score and text_len >= self.min_chars:
                    best_score = score
                    best_el    = el

            if best_el is None or best_score == 0:
                return self._timed(
                    BlockResult.failed("no content block found by density heuristic"),
                    start,
                )

            text = _format_element(best_el, ctx.profile.get("formatting_rules"))
            if len(text.strip()) < self.min_chars:
                return self._timed(
                    BlockResult.failed(f"density winner too short: {len(text.strip())} chars"),
                    start,
                )

            # Confidence: dựa trên score (cao = chắc hơn)
            confidence = min(0.85, 0.4 + best_score * 0.1)

            return self._timed(
                BlockResult.success(
                    data        = text,
                    method_used = "density_heuristic",
                    confidence  = confidence,
                    char_count  = len(text),
                    density_score = round(best_score, 3),
                ),
                start,
            )
        except asyncio.CancelledError:
            raise
        except Exception as e:
            return self._timed(BlockResult.failed(str(e) or repr(e)), start)

    def _score_element(self, el: Tag) -> tuple[float, int]:
        """Tính content score và text length cho một element."""
        full_html = str(el)
        html_len  = max(len(full_html), 1)

        # Lấy text, tính độ dài
        text = el.get_text(separator=" ", strip=True)
        text_len = len(text)
        if text_len < 50:
            return 0.0, 0

        # Link density — cao = navigation, không phải content
        link_text = "".join(
            a.get_text(separator=" ", strip=True)
            for a in el.find_all("a")
        )
        link_len     = len(link_text)
        link_density = link_len / max(text_len, 1)

        if link_density > 0.6:   # >60% text là links → bỏ qua
            return 0.0, 0

        text_density = text_len / html_len
        p_count      = len(el.find_all("p"))
        p_bonus      = min(p_count * 0.05, 0.3)   # Tối đa +0.3 cho nhiều <p>

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


# ── 4. XPath Extract Block ────────────────────────────────────────────────────

class XPathExtractBlock(ScraperBlock):
    """
    Extract content bằng XPath expression.
    Alternative cho CSS selector khi site dùng id/attribute phức tạp.
    
    Ví dụ XPath hữu ích:
        //div[@id='chapter-content']
        //article[contains(@class,'chapter')]
        //*[@itemprop='articleBody']
    
    Dùng lxml parser cho XPath support.
    """
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

            # Lấy text từ node đầu tiên
            node = nodes[0]
            if hasattr(node, "text_content"):
                text = node.text_content()
            else:
                text = str(node)

            text = text.strip()
            if len(text) < self.min_chars:
                return self._timed(
                    BlockResult.failed(
                        f"xpath result too short: {len(text)} chars"
                    ),
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
            return self._timed(
                BlockResult.skipped("lxml not installed"),
                start,
            )
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


# ── 5. Fallback List Extract Block ────────────────────────────────────────────

class FallbackListExtractBlock(ScraperBlock):
    """
    Thử lần lượt danh sách FALLBACK_CONTENT_SELECTORS đã biết.
    Dùng khi không có profile selector và density heuristic thất bại.
    
    Fallback list từ config.py — các selectors phổ biến nhất trên web novel sites.
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

            # Last resort: body text
            body = soup.find("body")
            if body and isinstance(body, Tag):
                from core.formatter import extract_plain_text
                text = extract_plain_text(body)
                if len(text.strip()) >= self.min_chars:
                    return self._timed(
                        BlockResult.fallback(
                            data        = text,
                            method_used = "body_text",
                            confidence  = 0.4,
                        ),
                        start,
                    )

            return self._timed(
                BlockResult.failed("all fallback selectors failed"),
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
    AI-powered content extraction — last resort.
    
    Gọi Gemini để extract nội dung khi tất cả heuristic blocks thất bại.
    Tốn API call nhưng đảm bảo lấy được content trong mọi trường hợp.
    
    Kết quả tốt → update profile content_selector để lần sau không cần AI nữa.
    """
    block_type = BlockType.EXTRACT
    name       = "ai_extract"

    async def execute(self, ctx: PipelineContext) -> BlockResult:
        start = time.monotonic()
        try:
            ai_limiter = ctx.profile.get("_ai_limiter")
            if ai_limiter is None:
                return self._timed(
                    BlockResult.skipped("no ai_limiter in context"),
                    start,
                )

            html = ctx.html
            if not html:
                return self._timed(BlockResult.skipped("no html"), start)

            # Gọi AI classify + extract
            from ai.agents import ai_classify_and_find
            result = await ai_classify_and_find(html, ctx.url, ai_limiter)

            if not result:
                return self._timed(BlockResult.failed("AI returned None"), start)

            # ai_classify_and_find trả về next_url, không phải content
            # → cần dùng extract riêng. Dùng density heuristic với soup.
            # AI extract thực sự sẽ được build trong learning/optimizer.py
            return self._timed(
                BlockResult.skipped("ai_extract deferred to optimizer"),
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


# ── Utility: format element to markdown ──────────────────────────────────────

def _format_element(el: Tag, formatting_rules: dict | None) -> str:
    """
    Format một BeautifulSoup element thành Markdown.
    Dùng MarkdownFormatter nếu có formatting_rules, else extract_plain_text.
    """
    from core.formatter import MarkdownFormatter, extract_plain_text
    if formatting_rules:
        return MarkdownFormatter(formatting_rules).format(el)
    return extract_plain_text(el)


# ── Registry ──────────────────────────────────────────────────────────────────

_EXTRACT_BLOCK_MAP: dict[str, type[ScraperBlock]] = {
    "selector"         : SelectorExtractBlock,
    "json_ld"          : JsonLdExtractBlock,
    "density_heuristic": DensityHeuristicBlock,
    "xpath"            : XPathExtractBlock,
    "fallback_list"    : FallbackListExtractBlock,
    "ai_extract"       : AIExtractBlock,
}


def make_extract_block(config: dict) -> ScraperBlock:
    """Factory: tạo extract block từ StepConfig dict."""
    block_type = config.get("type", "fallback_list")
    cls = _EXTRACT_BLOCK_MAP.get(block_type)
    if cls is None:
        raise ValueError(
            f"Unknown extract block type: {block_type!r}. "
            f"Available: {list(_EXTRACT_BLOCK_MAP)}"
        )
    return cls.from_config(config)