"""
pipeline/fetcher.py — Fetch blocks.

Blocks:
    CurlFetchBlock      — curl_cffi với Chrome TLS fingerprint (nhanh, ít RAM)
    PlaywrightFetchBlock — Playwright full browser (chậm, JS support, tốn RAM)
    HybridFetchBlock    — Thử curl trước, tự động fallback Playwright nếu:
                            (a) Cloudflare challenge detected
                            (b) Content quá ngắn so với Playwright version (JS-heavy detect)

HybridFetchBlock là block KHUYẾN NGHỊ cho mọi domain chưa biết.
Sau khi học, optimizer sẽ chọn CurlFetchBlock hoặc PlaywrightFetchBlock
tùy kết quả đánh giá.

JS-Heavy Detection (trong HybridFetchBlock):
    - Fetch Ch.1 bằng cả curl và Playwright
    - Nếu Playwright trả về > JS_CONTENT_RATIO lần content curl → đánh dấu requires_playwright
    - Kết quả được cache để không fetch lại lần 2
"""
from __future__ import annotations

import asyncio
import time

from utils.string_helpers import is_cloudflare_challenge, is_junk_page
from pipeline.base import (
    BlockType, BlockResult, PipelineContext, ScraperBlock,
)

# Ngưỡng để xác định site là JS-heavy
# Nếu Playwright trả về content dài hơn curl >= tỷ lệ này → requires_playwright
_JS_CONTENT_RATIO = 1.5   # 50% nhiều hơn
_JS_MIN_DIFF_CHARS = 500  # Chênh lệch tuyệt đối tối thiểu để tính (tránh noise)


class CurlFetchBlock(ScraperBlock):
    """
    Fetch bằng curl_cffi với Chrome TLS fingerprint.
    Nhanh nhất, ít RAM nhất. Không xử lý JS.
    Tự động mark domain là CF nếu gặp Cloudflare challenge.
    """
    block_type = BlockType.FETCH
    name       = "curl"

    async def execute(self, ctx: PipelineContext) -> BlockResult:
        start = time.monotonic()
        result = BlockResult.failed("not started")
        try:
            from core.session_pool import DomainSessionPool
            from urllib.parse import urlparse

            pool   = ctx.profile.get("_pool")      # injected by executor
            domain = urlparse(ctx.url).netloc.lower()

            if pool is None:
                return self._timed(BlockResult.failed("DomainSessionPool not in context"), start)

            if pool.is_cf_domain(domain):
                return self._timed(
                    BlockResult.skipped("domain flagged as CF — use playwright"),
                    start,
                )

            status, html = await pool.fetch(ctx.url)

            if is_cloudflare_challenge(html):
                pool.mark_cf_domain(domain)
                return self._timed(
                    BlockResult.failed("cloudflare_challenge — domain flagged"),
                    start,
                )

            if is_junk_page(html, status):
                return self._timed(
                    BlockResult.failed(f"junk_page status={status}"),
                    start,
                )

            result = BlockResult.success(
                data        = html,
                method_used = "curl",
                confidence  = 1.0,
                char_count  = len(html),
            )
        except asyncio.CancelledError:
            raise
        except Exception as e:
            err = str(e).strip() or repr(e)
            result = BlockResult.failed(err, method_used="curl")

        return self._timed(result, start)

    def to_config(self) -> dict:
        return {"type": self.name}

    @classmethod
    def from_config(cls, config: dict) -> "CurlFetchBlock":
        return cls()


class PlaywrightFetchBlock(ScraperBlock):
    """
    Fetch bằng Playwright full browser.
    Hỗ trợ JS, bypass một số anti-bot.
    Chậm hơn curl ~10x, tốn RAM.
    """
    block_type = BlockType.FETCH
    name       = "playwright"

    async def execute(self, ctx: PipelineContext) -> BlockResult:
        start = time.monotonic()
        result = BlockResult.failed("not started")
        try:
            pw_pool = ctx.profile.get("_pw_pool")  # injected by executor

            if pw_pool is None:
                return self._timed(
                    BlockResult.failed("PlaywrightPool not in context"),
                    start,
                )

            status, html = await pw_pool.fetch(ctx.url)

            if is_junk_page(html, status):
                return self._timed(
                    BlockResult.failed(f"junk_page status={status}"),
                    start,
                )

            result = BlockResult.success(
                data        = html,
                method_used = "playwright",
                confidence  = 1.0,
                char_count  = len(html),
            )
        except asyncio.CancelledError:
            raise
        except Exception as e:
            err = str(e).strip() or repr(e)
            result = BlockResult.failed(err, method_used="playwright")

        return self._timed(result, start)

    def to_config(self) -> dict:
        return {"type": self.name}

    @classmethod
    def from_config(cls, config: dict) -> "PlaywrightFetchBlock":
        return cls()


class HybridFetchBlock(ScraperBlock):
    """
    Smart fetch block kết hợp Curl + Playwright.

    Runtime logic (khi đã có profile):
        1. Nếu profile.requires_playwright → dùng thẳng Playwright
        2. Nếu domain đã flagged CF    → dùng thẳng Playwright
        3. Thử Curl trước
        4. Nếu Cloudflare challenge    → fallback Playwright, flag domain

    Learning mode (lần đầu, detect_js=True):
        1. Fetch bằng cả Curl VÀ Playwright
        2. So sánh content length
        3. Nếu Playwright > Curl × JS_CONTENT_RATIO AND diff > 500 chars
           → site là JS-heavy → ghi requires_playwright=True vào profile
        4. Trả về HTML từ Playwright (đầy đủ nhất)

    detect_js: bool — chỉ True trong Learning Phase để không tốn 2 fetches mỗi chapter
    """
    block_type = BlockType.FETCH
    name       = "hybrid"

    def __init__(self, detect_js: bool = False) -> None:
        self.detect_js = detect_js

    async def execute(self, ctx: PipelineContext) -> BlockResult:
        start = time.monotonic()
        result = BlockResult.failed("not started")
        try:
            from urllib.parse import urlparse

            pool    = ctx.profile.get("_pool")
            pw_pool = ctx.profile.get("_pw_pool")
            domain  = urlparse(ctx.url).netloc.lower()

            if pool is None or pw_pool is None:
                return self._timed(
                    BlockResult.failed("session pools not in context"),
                    start,
                )

            requires_pw = bool(ctx.profile.get("requires_playwright", False))

            # ── Fast path: known PW-only domain ──────────────────────────────
            if requires_pw or pool.is_cf_domain(domain):
                status, html = await pw_pool.fetch(ctx.url)
                if is_junk_page(html, status):
                    return self._timed(
                        BlockResult.failed(f"junk_page status={status}"),
                        start,
                    )
                return self._timed(
                    BlockResult.success(
                        data        = html,
                        method_used = "playwright_direct",
                        confidence  = 1.0,
                        char_count  = len(html),
                    ),
                    start,
                )

            # ── JS detection mode (learning phase) ────────────────────────────
            if self.detect_js:
                return self._timed(
                    await self._detect_js_fetch(ctx, pool, pw_pool, domain),
                    start,
                )

            # ── Normal hybrid: curl first, PW fallback ─────────────────────
            try:
                status, html = await pool.fetch(ctx.url)
                if is_cloudflare_challenge(html):
                    raise _CloudflareError()
                if is_junk_page(html, status):
                    return self._timed(
                        BlockResult.failed(f"junk_page status={status}"),
                        start,
                    )
                result = BlockResult.success(
                    data        = html,
                    method_used = "curl",
                    confidence  = 1.0,
                    char_count  = len(html),
                )
            except _CloudflareError:
                print(f"  [Hybrid] ⚡ CF detected on {domain} → Playwright", flush=True)
                pool.mark_cf_domain(domain)
                status, html = await pw_pool.fetch(ctx.url)
                if is_junk_page(html, status):
                    return self._timed(
                        BlockResult.failed(f"junk_page status={status} (after CF bypass)"),
                        start,
                    )
                result = BlockResult.fallback(
                    data        = html,
                    method_used = "playwright_cf_fallback",
                    confidence  = 0.9,
                )
            except asyncio.CancelledError:
                raise
            except Exception as e:
                # Curl lỗi mạng → thử Playwright
                err_str = str(e).strip() or repr(e)
                print(f"  [Hybrid] curl error: {err_str[:60]} → Playwright", flush=True)
                try:
                    status, html = await pw_pool.fetch(ctx.url)
                    if is_junk_page(html, status):
                        return self._timed(
                            BlockResult.failed(f"junk_page status={status}"),
                            start,
                        )
                    result = BlockResult.fallback(
                        data        = html,
                        method_used = "playwright_network_fallback",
                        confidence  = 0.85,
                    )
                except asyncio.CancelledError:
                    raise
                except Exception as e2:
                    result = BlockResult.failed(
                        f"curl: {err_str[:60]} | playwright: {str(e2)[:60]}",
                    )

        except asyncio.CancelledError:
            raise
        except Exception as e:
            result = BlockResult.failed(str(e).strip() or repr(e))

        return self._timed(result, start)

    async def _detect_js_fetch(
        self,
        ctx   : PipelineContext,
        pool,
        pw_pool,
        domain: str,
    ) -> BlockResult:
        """
        Fetch bằng CẢ hai curl + Playwright, so sánh content length để detect JS.
        Chỉ gọi trong learning phase (detect_js=True).
        """
        from bs4 import BeautifulSoup

        curl_html = pw_html = ""
        curl_ok   = pw_ok   = False

        # Fetch curl
        try:
            _, curl_html = await pool.fetch(ctx.url)
            curl_ok = not is_cloudflare_challenge(curl_html) and not is_junk_page(curl_html)
        except asyncio.CancelledError:
            raise
        except Exception:
            pass

        # Fetch playwright
        try:
            _, pw_html = await pw_pool.fetch(ctx.url)
            pw_ok = not is_junk_page(pw_html)
        except asyncio.CancelledError:
            raise
        except Exception:
            pass

        if not pw_ok and not curl_ok:
            return BlockResult.failed("both curl and playwright failed")

        # So sánh text content length (bỏ HTML tags)
        def _text_len(html: str) -> int:
            if not html:
                return 0
            try:
                soup = BeautifulSoup(html, "html.parser")
                return len(soup.get_text())
            except Exception:
                return len(html)

        curl_len = _text_len(curl_html) if curl_ok else 0
        pw_len   = _text_len(pw_html)   if pw_ok   else 0

        is_js_heavy = (
            pw_ok and curl_ok
            and pw_len > curl_len * _JS_CONTENT_RATIO
            and (pw_len - curl_len) > _JS_MIN_DIFF_CHARS
        )

        if is_js_heavy:
            print(
                f"  [Hybrid] 🔍 JS-heavy detected on {domain}: "
                f"curl={curl_len:,} chars vs pw={pw_len:,} chars "
                f"(ratio={pw_len/max(curl_len,1):.1f}x)",
                flush=True,
            )
            # Ghi vào profile để lưu
            ctx.profile["requires_playwright"] = True

        # Trả về HTML tốt nhất
        best_html   = pw_html   if pw_ok   else curl_html
        best_method = "playwright" if pw_ok else "curl"
        is_cf       = curl_ok and is_cloudflare_challenge(curl_html)

        if is_cf:
            pool.mark_cf_domain(domain)

        return BlockResult.success(
            data        = best_html,
            method_used = f"hybrid_detect_{best_method}",
            confidence  = 1.0,
            char_count  = len(best_html),
            js_heavy    = is_js_heavy,
            curl_len    = curl_len,
            pw_len      = pw_len,
        )

    def to_config(self) -> dict:
        return {"type": self.name, "detect_js": self.detect_js}

    @classmethod
    def from_config(cls, config: dict) -> "HybridFetchBlock":
        return cls(detect_js=bool(config.get("detect_js", False)))


# ── Internal sentinel ─────────────────────────────────────────────────────────

class _CloudflareError(Exception):
    """Internal: signal CF challenge detected trong hybrid flow."""
    pass


# ── Registry helper ───────────────────────────────────────────────────────────

_FETCH_BLOCK_MAP: dict[str, type[ScraperBlock]] = {
    "curl"      : CurlFetchBlock,
    "playwright": PlaywrightFetchBlock,
    "hybrid"    : HybridFetchBlock,
}


def make_fetch_block(config: dict) -> ScraperBlock:
    """
    Factory: tạo fetch block từ StepConfig dict.
    
    Args:
        config: {"type": "curl"} hoặc {"type": "hybrid", "detect_js": true}
    
    Returns:
        ScraperBlock instance
    
    Raises:
        ValueError nếu type không được hỗ trợ
    """
    block_type = config.get("type", "hybrid")
    cls = _FETCH_BLOCK_MAP.get(block_type)
    if cls is None:
        raise ValueError(
            f"Unknown fetch block type: {block_type!r}. "
            f"Available: {list(_FETCH_BLOCK_MAP)}"
        )
    return cls.from_config(config)