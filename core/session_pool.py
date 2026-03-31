"""
core/session_pool.py — Quản lý HTTP sessions và Playwright browser pool.

THAY ĐỔI (v2) — PlaywrightPool:
  PW-MEM: Thêm _fetch_count counter. Cứ sau PW_RESTART_EVERY lần fetch
          (mặc định 300), chủ động restart browser để giải phóng RAM.
          Chromium headless chạy lâu có xu hướng leak memory do:
            - Các page/context cũ không được GC hoàn toàn
            - V8 JS engine giữ cache
            - Playwright internal event listeners tích lũy
          Restart định kỳ giúp giữ RAM ổn định khi cào 1000+ chương.

Fixes từ phiên bản trước vẫn còn:
  FIX-PW1: _ensure_started() kiểm tra browser.is_connected()
  FIX-PW2: fetch() retry 1 lần khi gặp browser crash errors
  FIX-PW3: context.close() trong finally bắt Exception riêng
"""
import asyncio

from config import CHROME_UA, pick_chrome_version, make_headers, REQUEST_TIMEOUT
from utils.string_helpers import CF_CHALLENGE_TITLES


# Số lần fetch trước khi restart browser để giải phóng RAM
# 300 = ~300 chương Playwright mode ≈ vài giờ chạy liên tục
# Tăng lên 500 nếu RAM máy nhiều; giảm xuống 100 nếu bị OOM
PW_RESTART_EVERY = 300


# ── DomainSessionPool ─────────────────────────────────────────────────────────

class DomainSessionPool:
    """
    Pool curl_cffi session — 1 session/domain.
    Domain từng trigger CF challenge sẽ được chuyển thẳng sang Playwright.
    """

    def __init__(self) -> None:
        self._sessions:   dict[str, object] = {}
        self._versions:   dict[str, str]    = {}
        self._cf_domains: set[str]           = set()
        self._lock = asyncio.Lock()

    def mark_cf_domain(self, domain: str) -> None:
        self._cf_domains.add(domain)

    def is_cf_domain(self, domain: str) -> bool:
        return domain in self._cf_domains

    async def _get_session(self, domain: str):
        async with self._lock:
            if domain not in self._sessions:
                try:
                    from curl_cffi.requests import AsyncSession
                except ImportError:
                    raise ImportError("curl_cffi chưa cài:\n  pip install curl_cffi")
                version = pick_chrome_version()
                self._versions[domain] = version
                self._sessions[domain] = AsyncSession(impersonate=version)
            return self._sessions[domain], self._versions[domain]

    async def fetch(self, url: str) -> tuple[int, str]:
        from urllib.parse import urlparse
        domain           = urlparse(url).netloc.lower()
        session, version = await self._get_session(domain)
        headers          = make_headers(version)
        resp             = await session.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
        return resp.status_code, resp.text

    async def close_all(self) -> None:
        async with self._lock:
            for session in self._sessions.values():
                try:
                    await session.close()
                except Exception:
                    pass
            self._sessions.clear()
            self._versions.clear()


# ── PlaywrightPool ────────────────────────────────────────────────────────────

_BROWSER_CRASH_SIGNALS = (
    "Connection closed",
    "Browser.new_context",
    "Protocol error",
    "Target closed",
    "browser has disconnected",
)


class PlaywrightPool:
    """
    Singleton Playwright browser — khởi động 1 lần, tái dùng suốt phiên.

    PW-MEM (mới): Đếm số lần fetch. Cứ sau PW_RESTART_EVERY lần,
                  chủ động restart để giải phóng RAM Chromium tích lũy.
                  Giúp ổn định khi cào 1000+ chương qua Playwright.

    FIX-PW1: _ensure_started() kiểm tra browser.is_connected()
    FIX-PW2: fetch() retry 1 lần khi gặp browser crash errors
    FIX-PW3: context.close() bọc try/except riêng trong finally
    """

    def __init__(self) -> None:
        self._pw          = None
        self._browser     = None
        self._stealth     = None
        self._lock        = asyncio.Lock()
        self._started     = False
        self._fetch_count = 0          # PW-MEM: đếm tổng số fetch

    # ── PW-MEM: Kiểm tra và trigger periodic restart ──────────────────────────

    async def _maybe_periodic_restart(self) -> None:
        """
        Kiểm tra xem có cần restart định kỳ không.

        Điều kiện: đã fetch đủ PW_RESTART_EVERY lần VÀ không có page đang mở.
        Reset counter sau khi restart.

        Gọi TRƯỚC _ensure_started() trong fetch() để đảm bảo thứ tự đúng.
        """
        if self._fetch_count > 0 and self._fetch_count % PW_RESTART_EVERY == 0:
            print(
                f"  [Browser] 🔄 Periodic restart sau {self._fetch_count} fetch"
                f" (giải phóng RAM)...",
                flush=True,
            )
            async with self._lock:
                await self._cleanup_unsafe()
            # _ensure_started() sẽ khởi động lại trong fetch()

    # ── FIX-PW1 ───────────────────────────────────────────────────────────────

    async def _ensure_started(self) -> None:
        if self._started and self._browser is not None and self._browser.is_connected():
            return

        async with self._lock:
            if self._started and self._browser is not None and self._browser.is_connected():
                return

            if self._started or self._browser is not None:
                print("  [Browser] 🔄 Phát hiện browser crash, đang restart...", flush=True)
                await self._cleanup_unsafe()

            await self._start_browser()

    async def _cleanup_unsafe(self) -> None:
        """Dọn dẹp browser cũ — gọi BÊN TRONG lock, không acquire thêm."""
        try:
            if self._browser:
                await self._browser.close()
        except Exception:
            pass
        try:
            if self._pw:
                await self._pw.stop()
        except Exception:
            pass
        self._browser = None
        self._pw      = None
        self._started = False

    async def _start_browser(self) -> None:
        """Khởi động Playwright + Chromium — gọi BÊN TRONG lock."""
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            raise ImportError(
                "Playwright chưa cài:\n"
                "  pip install playwright playwright-stealth\n"
                "  playwright install chromium"
            )

        self._pw      = await async_playwright().start()
        self._browser = await self._pw.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
            ],
        )
        try:
            from playwright_stealth import stealth_async
            self._stealth = stealth_async
        except ImportError:
            self._stealth = None

        self._started = True
        print("  [Browser] ✅ Playwright browser sẵn sàng.", flush=True)

    # ── FIX-PW2 + FIX-PW3 + PW-MEM ──────────────────────────────────────────

    async def fetch(self, url: str) -> tuple[int, str]:
        """
        Fetch URL bằng Playwright.

        PW-MEM: Kiểm tra periodic restart trước khi fetch.
        FIX-PW2: Retry 1 lần khi gặp browser crash.
        """
        # PW-MEM: check trước, không cần lock vì chỉ đọc counter
        await self._maybe_periodic_restart()

        max_attempts = 2

        for attempt in range(max_attempts):
            try:
                await self._ensure_started()
                result = await self._fetch_once(url)
                self._fetch_count += 1    # PW-MEM: tăng counter sau fetch thành công
                return result

            except Exception as e:
                err_str = str(e)
                is_crash = any(sig in err_str for sig in _BROWSER_CRASH_SIGNALS)

                if attempt < max_attempts - 1 and is_crash:
                    print(
                        f"  [Browser] ⚠️  Browser lỗi (lần {attempt + 1}): {err_str[:80]}",
                        flush=True,
                    )
                    async with self._lock:
                        await self._cleanup_unsafe()
                    continue

                raise

        raise RuntimeError("PlaywrightPool.fetch: retry logic không mong đợi")

    async def _fetch_once(self, url: str) -> tuple[int, str]:
        """Một lần fetch thực sự — FIX-PW3: context.close() an toàn."""
        context = await self._browser.new_context(
            user_agent         = CHROME_UA["chrome124"],
            viewport           = {"width": 1280, "height": 800},
            locale             = "en-US",
            timezone_id        = "America/New_York",
            extra_http_headers = {
                "Accept-Language": "en-US,en;q=0.9",
                "Accept"         : "text/html,application/xhtml+xml,*/*;q=0.8",
            },
        )
        page = await context.new_page()
        try:
            if self._stealth:
                await self._stealth(page)

            resp = await page.goto(url, wait_until="domcontentloaded", timeout=60_000)

            for _ in range(20):
                title = (await page.title()).strip().lower()
                if title not in CF_CHALLENGE_TITLES:
                    break
                await page.wait_for_timeout(1_000)
            else:
                print("  [Browser] ⚠️  CF vẫn còn sau 20s.", flush=True)

            html   = await page.content()
            status = resp.status if resp else 200
            return status, html

        finally:
            try:
                await context.close()
            except Exception as close_err:
                print(
                    f"  [Browser] ⚠️  context.close() warning (bỏ qua): "
                    f"{str(close_err)[:60]}",
                    flush=True,
                )

    @property
    def fetch_count(self) -> int:
        """Tổng số lần đã fetch qua Playwright — dùng để monitor."""
        return self._fetch_count

    async def close(self) -> None:
        if not self._started:
            return
        async with self._lock:
            await self._cleanup_unsafe()