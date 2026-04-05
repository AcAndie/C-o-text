"""
pipeline/navigator.py — Navigation blocks (tìm URL chương tiếp theo).

Blocks (theo thứ tự ưu tiên trong default chain):
    RelNextNavBlock      — <link rel="next"> hoặc <a rel="next"> (chuẩn nhất)
    SelectorNavBlock     — CSS selector đã học từ profile
    AnchorTextNavBlock   — Tìm link có text "Next", "Next Chapter", v.v.
    SlugIncrementNavBlock — /chapter-5 → /chapter-6 (URL pattern)
    FanficNavBlock       — fanfiction.net /s/{id}/{num}/ pattern
    SelectDropdownNavBlock — Site dùng <select> dropdown để chọn chapter
    AINavBlock           — AI fallback (tốn API call)

SelectDropdownNavBlock là block MỚI — code cũ chưa có.
Một số site dùng <select id="chapter-select"> thay vì link thông thường.
"""
from __future__ import annotations

import asyncio
import re
import time
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

from config import RE_NEXT_BTN, RE_CHAP_SLUG, RE_FANFIC
from pipeline.base import BlockType, BlockResult, PipelineContext, ScraperBlock


# ── 1. Rel Next Block ─────────────────────────────────────────────────────────

class RelNextNavBlock(ScraperBlock):
    """
    Tìm URL tiếp theo qua HTML rel="next".
    Chuẩn nhất — nếu site implement đúng SEO standard thì dùng cái này.
    
    Support: <link rel="next" href="..."> (SEO) và <a rel="next" href="...">
    """
    block_type = BlockType.NAVIGATE
    name       = "rel_next"

    async def execute(self, ctx: PipelineContext) -> BlockResult:
        start = time.monotonic()
        try:
            soup = ctx.soup
            if soup is None:
                return self._timed(BlockResult.skipped("no soup"), start)

            el = soup.find("link", rel="next") or soup.find("a", rel="next")
            if el and el.get("href"):
                url = urljoin(ctx.url, el["href"])
                return self._timed(
                    BlockResult.success(
                        data        = url,
                        method_used = "rel_next",
                        confidence  = 0.98,
                    ),
                    start,
                )

            return self._timed(BlockResult.failed("no rel=next found"), start)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            return self._timed(BlockResult.failed(str(e) or repr(e)), start)

    def to_config(self) -> dict:
        return {"type": self.name}

    @classmethod
    def from_config(cls, config: dict) -> "RelNextNavBlock":
        return cls()


# ── 2. Selector Nav Block ─────────────────────────────────────────────────────

class SelectorNavBlock(ScraperBlock):
    """
    Tìm next URL bằng CSS selector đã học từ profile.
    """
    block_type = BlockType.NAVIGATE
    name       = "selector"

    def __init__(self, selector: str | None = None) -> None:
        self.selector = selector   # None → đọc từ ctx.profile["next_selector"]

    async def execute(self, ctx: PipelineContext) -> BlockResult:
        start = time.monotonic()
        try:
            sel = self.selector or ctx.profile.get("next_selector")
            if not sel:
                return self._timed(BlockResult.skipped("no next_selector"), start)

            soup = ctx.soup
            if soup is None:
                return self._timed(BlockResult.skipped("no soup"), start)

            el = soup.select_one(sel)
            if el is None:
                return self._timed(
                    BlockResult.failed(f"selector {sel!r} matched nothing"),
                    start,
                )

            href = el.get("href")
            if not href:
                # Selector match nhưng không phải <a> → thử tìm <a> bên trong
                inner = el.find("a", href=True)
                href  = inner.get("href") if inner else None

            if not href:
                return self._timed(
                    BlockResult.failed(f"selector {sel!r} matched but no href"),
                    start,
                )

            url = urljoin(ctx.url, href)
            return self._timed(
                BlockResult.success(
                    data        = url,
                    method_used = f"selector:{sel}",
                    confidence  = 0.92,
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
    def from_config(cls, config: dict) -> "SelectorNavBlock":
        return cls(selector=config.get("selector"))


# ── 3. Anchor Text Nav Block ──────────────────────────────────────────────────

class AnchorTextNavBlock(ScraperBlock):
    """
    Tìm link có anchor text khớp "Next", "Next Chapter", "Tiếp", v.v.
    Dùng RE_NEXT_BTN từ config.
    """
    block_type = BlockType.NAVIGATE
    name       = "anchor_text"

    async def execute(self, ctx: PipelineContext) -> BlockResult:
        start = time.monotonic()
        try:
            soup = ctx.soup
            if soup is None:
                return self._timed(BlockResult.skipped("no soup"), start)

            for a in soup.find_all("a", href=True):
                if RE_NEXT_BTN.search(a.get_text(strip=True)):
                    url = urljoin(ctx.url, a["href"])
                    return self._timed(
                        BlockResult.success(
                            data        = url,
                            method_used = "anchor_text",
                            confidence  = 0.80,
                            anchor_text = a.get_text(strip=True)[:30],
                        ),
                        start,
                    )

            return self._timed(
                BlockResult.failed("no anchor with next-button text found"),
                start,
            )
        except asyncio.CancelledError:
            raise
        except Exception as e:
            return self._timed(BlockResult.failed(str(e) or repr(e)), start)

    def to_config(self) -> dict:
        return {"type": self.name}

    @classmethod
    def from_config(cls, config: dict) -> "AnchorTextNavBlock":
        return cls()


# ── 4. Slug Increment Block ───────────────────────────────────────────────────

class SlugIncrementNavBlock(ScraperBlock):
    """
    Tăng số chapter trong URL slug.
    /chapter-5 → /chapter-6, /chuong_10 → /chuong_11
    
    Dùng RE_CHAP_SLUG từ config.
    """
    block_type = BlockType.NAVIGATE
    name       = "slug_increment"

    async def execute(self, ctx: PipelineContext) -> BlockResult:
        start = time.monotonic()
        try:
            m = RE_CHAP_SLUG.search(ctx.url)
            if m:
                new_url = f"{m.group(1)}{int(m.group(2)) + 1}{m.group(3)}"
                return self._timed(
                    BlockResult.success(
                        data        = new_url,
                        method_used = "slug_increment",
                        confidence  = 0.70,
                    ),
                    start,
                )
            return self._timed(BlockResult.failed("no slug pattern in URL"), start)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            return self._timed(BlockResult.failed(str(e) or repr(e)), start)

    def to_config(self) -> dict:
        return {"type": self.name}

    @classmethod
    def from_config(cls, config: dict) -> "SlugIncrementNavBlock":
        return cls()


# ── 5. Fanfic Nav Block ───────────────────────────────────────────────────────

class FanficNavBlock(ScraperBlock):
    """
    fanfiction.net navigation: /s/{story_id}/{chapter_num}/{title}
    Tăng chapter_num lên 1.
    Dùng RE_FANFIC từ config.
    """
    block_type = BlockType.NAVIGATE
    name       = "fanfic"

    async def execute(self, ctx: PipelineContext) -> BlockResult:
        start = time.monotonic()
        try:
            m = RE_FANFIC.search(ctx.url)
            if m:
                new_url = (
                    ctx.url[: m.start()]
                    + m.group(1)
                    + str(int(m.group(2)) + 1)
                    + (m.group(3) or "")
                )
                return self._timed(
                    BlockResult.success(
                        data        = new_url,
                        method_used = "fanfic_increment",
                        confidence  = 0.72,
                    ),
                    start,
                )
            return self._timed(
                BlockResult.failed("URL does not match fanfic pattern"),
                start,
            )
        except asyncio.CancelledError:
            raise
        except Exception as e:
            return self._timed(BlockResult.failed(str(e) or repr(e)), start)

    def to_config(self) -> dict:
        return {"type": self.name}

    @classmethod
    def from_config(cls, config: dict) -> "FanficNavBlock":
        return cls()


# ── 6. Select Dropdown Nav Block [NEW] ────────────────────────────────────────

class SelectDropdownNavBlock(ScraperBlock):
    """
    [NEW] Tìm next chapter URL từ <select> dropdown.
    
    Một số site (lightnovelreader, novelfull, v.v.) dùng dropdown thay vì link:
        <select id="chapterList">
            <option value="/chapter-1">Chapter 1</option>
            <option value="/chapter-2" selected>Chapter 2</option>  ← current
            <option value="/chapter-3">Chapter 3</option>           ← next
        </select>
    
    Logic: tìm <option selected>, lấy <option> kế tiếp trong DOM.
    
    select_selector: CSS selector cho <select> element.
                     None → thử các selectors phổ biến tự động.
    """
    block_type = BlockType.NAVIGATE
    name       = "select_dropdown"

    # Các selectors phổ biến cho chapter dropdown
    _AUTO_SELECTORS = [
        "select#chapterList",
        "select.chapter-select",
        "select[name='chapter']",
        "select.selectpicker",
        "select#chapter",
        "select.chapter-dropdown",
        "select",  # last resort
    ]

    def __init__(self, select_selector: str | None = None) -> None:
        self.select_selector = select_selector

    async def execute(self, ctx: PipelineContext) -> BlockResult:
        start = time.monotonic()
        try:
            soup = ctx.soup
            if soup is None:
                return self._timed(BlockResult.skipped("no soup"), start)

            selectors = (
                [self.select_selector] if self.select_selector
                else self._AUTO_SELECTORS
            )

            for sel in selectors:
                try:
                    select_el = soup.select_one(sel)
                    if select_el is None:
                        continue

                    options = select_el.find_all("option")
                    if not options:
                        continue

                    # Tìm option đang được selected
                    current_idx = None
                    for i, opt in enumerate(options):
                        if opt.get("selected") is not None:
                            current_idx = i
                            break

                    # Fallback: tìm option có value khớp URL hiện tại
                    if current_idx is None:
                        for i, opt in enumerate(options):
                            val = opt.get("value", "")
                            if val and val in ctx.url:
                                current_idx = i
                                break

                    if current_idx is None or current_idx >= len(options) - 1:
                        continue

                    next_opt = options[current_idx + 1]
                    next_val = next_opt.get("value", "").strip()

                    if not next_val:
                        continue

                    url = urljoin(ctx.url, next_val)
                    return self._timed(
                        BlockResult.success(
                            data            = url,
                            method_used     = f"select_dropdown:{sel}",
                            confidence      = 0.85,
                            select_selector = sel,
                        ),
                        start,
                    )
                except Exception:
                    continue

            return self._timed(
                BlockResult.failed("no chapter dropdown found"),
                start,
            )
        except asyncio.CancelledError:
            raise
        except Exception as e:
            return self._timed(BlockResult.failed(str(e) or repr(e)), start)

    def to_config(self) -> dict:
        d: dict = {"type": self.name}
        if self.select_selector:
            d["select_selector"] = self.select_selector
        return d

    @classmethod
    def from_config(cls, config: dict) -> "SelectDropdownNavBlock":
        return cls(select_selector=config.get("select_selector"))


# ── 7. AI Nav Block ───────────────────────────────────────────────────────────

class AINavBlock(ScraperBlock):
    """
    AI fallback navigation — gọi Gemini để tìm next URL.
    Chỉ dùng khi tất cả heuristic blocks thất bại.
    """
    block_type = BlockType.NAVIGATE
    name       = "ai_nav"

    async def execute(self, ctx: PipelineContext) -> BlockResult:
        start = time.monotonic()
        try:
            ai_limiter = ctx.profile.get("_ai_limiter")
            if ai_limiter is None:
                return self._timed(
                    BlockResult.skipped("no ai_limiter"),
                    start,
                )

            html = ctx.html
            if not html:
                return self._timed(BlockResult.skipped("no html"), start)

            from ai.agents import ai_classify_and_find
            result = await ai_classify_and_find(html, ctx.url, ai_limiter)

            if result and result.get("next_url"):
                return self._timed(
                    BlockResult.fallback(
                        data        = result["next_url"],
                        method_used = "ai_nav",
                        confidence  = 0.75,
                    ),
                    start,
                )

            return self._timed(BlockResult.failed("AI could not find next URL"), start)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            return self._timed(BlockResult.failed(str(e) or repr(e)), start)

    def to_config(self) -> dict:
        return {"type": self.name}

    @classmethod
    def from_config(cls, config: dict) -> "AINavBlock":
        return cls()


# ── Registry ──────────────────────────────────────────────────────────────────

_NAV_BLOCK_MAP: dict[str, type[ScraperBlock]] = {
    "rel_next"       : RelNextNavBlock,
    "selector"       : SelectorNavBlock,
    "anchor_text"    : AnchorTextNavBlock,
    "slug_increment" : SlugIncrementNavBlock,
    "fanfic"         : FanficNavBlock,
    "select_dropdown": SelectDropdownNavBlock,
    "ai_nav"         : AINavBlock,
}


def make_nav_block(config: dict) -> ScraperBlock:
    """Factory: tạo navigation block từ StepConfig dict."""
    block_type = config.get("type", "anchor_text")
    cls = _NAV_BLOCK_MAP.get(block_type)
    if cls is None:
        raise ValueError(
            f"Unknown nav block type: {block_type!r}. "
            f"Available: {list(_NAV_BLOCK_MAP)}"
        )
    return cls.from_config(config)