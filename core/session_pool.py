"""
core/session_pool.py — Quản lý HTTP sessions và Playwright browser pool.
"""
import asyncio

from config import CHROME_UA, pick_chrome_version, make_headers, REQUEST_TIMEOUT
from utils.string_helpers import CF_CHALLENGE_TITLES   # ← public name (không còn dấu _)


# ── DomainSessionPool ─────────────────────────────────────────────────────────

class DomainSessionPool:
    """
    Pool curl_cffi session — 1 session/domain.
    Domain từng trigger CF challenge sẽ được chuyển thẳng sang Playwright.
    """

    def __init__(self) -> None:
        self._sessions:  dict[str, object] = {}
        self._versions:  dict[str, str]    = {}
        self._cf_domains: set[str]          = set()
        self._lock = asyncio.Lock()

    def mark_cf_domain(self, domain: str) -> None:
        """Đánh dấu domain luôn cần Playwright — bỏ qua curl_cffi."""
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
        domain          = urlparse(url).netloc.lower()
        session, version = await self._get_session(domain)
        headers         = make_headers(version)
        resp            = await session.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
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

class PlaywrightPool:
    """
    Singleton Playwright browser — khởi động 1 lần, tái dùng suốt phiên.

    BUG FIX: Mỗi lần fetch tạo một browser context RIÊNG BIỆT thay vì
    dùng chung 1 context. Điều này tránh session/cookie bleed giữa các
    truyện cào song song.

    Chi phí: browser.new_context() rất nhẹ (không tạo process mới),
    chỉ là isolated session bên trong cùng browser process.
    """

    def __init__(self) -> None:
        self._pw      = None
        self._browser = None
        self._stealth = None
        self._lock    = asyncio.Lock()
        self._started = False

    async def _ensure_started(self) -> None:
        if self._started:
            return
        async with self._lock:
            if self._started:   # Double-checked locking
                return
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
                headless = True,
                args     = [
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

    async def fetch(self, url: str) -> tuple[int, str]:
        """
        Fetch URL bằng Playwright.

        Mỗi lần gọi tạo một context độc lập → cookies/localStorage không
        bị chia sẻ giữa các task song song.
        """
        await self._ensure_started()

        # Context mới cho mỗi request → session isolation
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

            # Chờ CF challenge tự giải (tối đa 20s)
            for _ in range(20):
                title = (await page.title()).strip().lower()
                if title not in CF_CHALLENGE_TITLES:
                    break
                await page.wait_for_timeout(1_000)
            else:
                print(f"  [Browser] ⚠️  CF vẫn còn sau 20s.", flush=True)

            html   = await page.content()
            status = resp.status if resp else 200
            return status, html

        finally:
            # Đóng cả context (không chỉ page) để giải phóng hoàn toàn
            await context.close()

    async def close(self) -> None:
        if not self._started:
            return
        try:
            if self._browser : await self._browser.close()
            if self._pw      : await self._pw.stop()
        except Exception:
            pass
        self._started = False