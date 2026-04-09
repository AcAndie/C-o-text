"""
core/session_pool.py — Connection pool management.

DomainSessionPool : curl_cffi session pool, per-domain CF tracking.
PlaywrightPool    : Playwright browser pool với semaphore + memory leak prevention.
"""
from __future__ import annotations

import asyncio
import logging
from urllib.parse import urlparse

from config import (
    PW_MAX_CONCURRENCY, REQUEST_TIMEOUT,
    pick_chrome_version, make_headers,
)

logger = logging.getLogger(__name__)


# ── DomainSessionPool ─────────────────────────────────────────────────────────

class DomainSessionPool:
    """
    curl_cffi async session pool.
    Một session per domain để tái dùng TCP connection + cookie jar.
    """

    def __init__(self) -> None:
        self._sessions: dict[str, object] = {}
        self._cf_domains: set[str] = set()
        self._lock = asyncio.Lock()

    def is_cf_domain(self, domain: str) -> bool:
        return domain in self._cf_domains

    def mark_cf_domain(self, domain: str) -> None:
        self._cf_domains.add(domain)
        logger.debug("[Pool] CF domain flagged: %s", domain)

    async def fetch(self, url: str, timeout: int = REQUEST_TIMEOUT) -> tuple[int, str]:
        """Fetch URL bằng curl_cffi. Returns (status_code, html)."""
        try:
            from curl_cffi.requests import AsyncSession

            domain  = urlparse(url).netloc.lower()
            version = pick_chrome_version()
            headers = make_headers(version)

            async with self._lock:
                if domain not in self._sessions:
                    self._sessions[domain] = AsyncSession(impersonate=version)
                session = self._sessions[domain]

            resp = await session.get(url, headers=headers, timeout=timeout)
            html = resp.text or ""
            return resp.status_code, html

        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning("[Pool] curl fetch failed for %s: %s", url, e)
            raise

    async def close_all(self) -> None:
        async with self._lock:
            for session in self._sessions.values():
                try:
                    if hasattr(session, "close"):
                        await session.close()
                except Exception:
                    pass
            self._sessions.clear()
        logger.debug("[Pool] All sessions closed.")


# ── PlaywrightPool ─────────────────────────────────────────────────────────────

class PlaywrightPool:
    """
    Playwright browser pool.

    - Semaphore kiểm soát concurrency (PW_MAX_CONCURRENCY).
    - Browser tự restart sau _RESTART_AFTER pages để tránh memory leak.
    - Mỗi fetch dùng một page riêng, đóng sau khi xong.
    """

    _RESTART_AFTER = 50   # restart browser sau N pages

    def __init__(self) -> None:
        self._semaphore   = asyncio.Semaphore(max(1, PW_MAX_CONCURRENCY))
        self._browser     = None
        self._playwright  = None
        self._page_count  = 0
        self._lock        = asyncio.Lock()

    async def _get_browser(self):
        """Lấy browser, restart nếu đã dùng quá _RESTART_AFTER pages."""
        async with self._lock:
            if self._browser is None or self._page_count >= self._RESTART_AFTER:
                await self._restart_browser()
        return self._browser

    async def _restart_browser(self) -> None:
        """Đóng browser cũ và khởi động mới."""
        if self._browser:
            try:
                await self._browser.close()
            except Exception:
                pass
        if self._playwright is None:
            from playwright.async_api import async_playwright
            self._playwright = await async_playwright().__aenter__()
        try:
            self._browser    = await self._playwright.chromium.launch(headless=True)
            self._page_count = 0
            logger.debug("[PW] Browser (re)started.")
        except Exception as e:
            logger.error("[PW] Browser launch failed: %s", e)
            raise

    async def fetch(self, url: str, timeout: int = REQUEST_TIMEOUT) -> tuple[int, str]:
        """Fetch URL bằng Playwright. Returns (status_code, html)."""
        async with self._semaphore:
            browser = await self._get_browser()
            page    = None
            status  = 200
            try:
                page      = await browser.new_page()
                version   = pick_chrome_version()
                headers   = make_headers(version)
                await page.set_extra_http_headers(headers)

                response = await page.goto(
                    url,
                    timeout      = timeout * 1000,
                    wait_until   = "domcontentloaded",
                )
                if response:
                    status = response.status

                # Chờ thêm để lazy-load content
                await page.wait_for_timeout(1500)
                html = await page.content()

                async with self._lock:
                    self._page_count += 1

                return status, html or ""

            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.warning("[PW] fetch failed for %s: %s", url, e)
                raise
            finally:
                if page:
                    try:
                        await page.close()
                    except Exception:
                        pass

    async def close(self) -> None:
        async with self._lock:
            if self._browser:
                try:
                    await self._browser.close()
                except Exception:
                    pass
                self._browser = None
            if self._playwright:
                try:
                    await self._playwright.__aexit__(None, None, None)
                except Exception:
                    pass
                self._playwright = None
        logger.debug("[PW] Pool closed.")