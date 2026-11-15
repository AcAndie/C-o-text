"""PlaywrightPool: quản lý trình duyệt headless kèm stealth best-effort."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from cao_text.net.http import (
    RateLimitedError,
    make_headers,
    pick_chrome_version,
)

logger = logging.getLogger(__name__)


class PlaywrightPool:
    """Quản lý trình duyệt Playwright headless cho các trang yêu cầu JS hoặc anti-bot.

    Đặc điểm:
      - Giới hạn số lượng instance đồng thời qua Semaphore (mặc định 2).
      - Tự động restart browser sau mỗi `_RESTART_AFTER` (50) pages để tránh memory leak.
      - Tích hợp playwright-stealth (best-effort) che giấu dấu vết automation.
      - Giả lập User-Agent Chrome và headers đồng bộ với curl_cffi.
      - HTTP 429 với HTML rỗng bắt buộc raise RateLimitedError.
      - Đảm bảo đóng page trong finally block.
    """

    _RESTART_AFTER: int = 50

    def __init__(self, max_concurrency: int = 2) -> None:
        self.max_concurrency = max(1, max_concurrency)
        self._semaphore = asyncio.Semaphore(self.max_concurrency)
        self._browser: Any = None
        self._playwright: Any = None
        self._page_count: int = 0
        self._lock = asyncio.Lock()

    async def _get_browser(self) -> Any:
        """Lấy instance browser, tự restart nếu đã đạt ngưỡng _RESTART_AFTER."""
        async with self._lock:
            if self._browser is None or self._page_count >= self._RESTART_AFTER:
                await self._restart_browser()
            return self._browser

    async def _restart_browser(self) -> None:
        """Đóng browser hiện tại (nếu có) và khởi động instance mới."""
        if self._browser is not None:
            try:
                await self._browser.close()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.debug("[PW] Error closing old browser: %s", e)
            self._browser = None

        if self._playwright is None:
            from playwright.async_api import async_playwright

            self._playwright = await async_playwright().__aenter__()

        try:
            self._browser = await self._playwright.chromium.launch(headless=True)
            self._page_count = 0
            logger.debug("[PW] Browser started (max_concurrency=%d).", self.max_concurrency)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error("[PW] Browser launch failed: %s", e)
            raise

    async def fetch(
        self,
        url: str,
        timeout: float = 60.0,
        referer: str | None = None,
    ) -> tuple[int, str]:
        """Tải trang web bằng Playwright headless browser.

        Trả về (status_code, html).
        """
        async with self._semaphore:
            browser = await self._get_browser()
            page = None
            status = 200

            try:
                page = await browser.new_page()

                # Áp dụng stealth best-effort (không làm gián đoạn nếu thư viện lỗi)
                try:
                    from playwright_stealth import Stealth

                    await Stealth().apply_stealth_async(page)
                except asyncio.CancelledError:
                    raise
                except Exception as se:
                    logger.debug("[PW] playwright-stealth apply failed: %s", se)

                version = pick_chrome_version()
                headers = make_headers(version, referer=referer)
                await page.set_extra_http_headers(headers)

                timeout_ms = int(timeout * 1000)
                response = await page.goto(
                    url,
                    timeout=timeout_ms,
                    wait_until="domcontentloaded",
                )
                if response is not None:
                    status = response.status

                # Chờ thêm 1.5s để nội dung lazy-load hoàn tất
                await page.wait_for_timeout(1500)
                html = await page.content()

                async with self._lock:
                    self._page_count += 1

                # Quy tắc §6.2: HTTP 429 với HTML rỗng -> raise, không coi là hết truyện
                if status == 429 and not (html or "").strip():
                    raise RateLimitedError(url, status_code=429, detail="HTML body is empty")

                return status, html or ""

            except asyncio.CancelledError:
                raise
            except RateLimitedError:
                raise
            except Exception as e:
                logger.warning("[PW] fetch failed for %s: %s", url, e)
                raise
            finally:
                if page is not None:
                    try:
                        await page.close()
                    except asyncio.CancelledError:
                        raise
                    except Exception as ce:
                        logger.debug("[PW] page.close error: %s", ce)

    async def close(self) -> None:
        """Đóng toàn bộ browser và engine Playwright."""
        async with self._lock:
            if self._browser is not None:
                try:
                    await self._browser.close()
                except asyncio.CancelledError:
                    raise
                except Exception as be:
                    logger.debug("[PW] browser.close error: %s", be)
                self._browser = None

            if self._playwright is not None:
                try:
                    await self._playwright.__aexit__(None, None, None)
                except asyncio.CancelledError:
                    raise
                except Exception as pe:
                    logger.debug("[PW] playwright exit error: %s", pe)
                self._playwright = None

            self._page_count = 0
        logger.debug("[PW] PlaywrightPool closed.")
