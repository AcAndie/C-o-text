"""DomainSessionPool: curl_cffi, impersonate Chrome, per-host semaphore, delay, CF detect."""
from __future__ import annotations

import asyncio
import logging
import random
import re
from typing import Any
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# ── Exception Hierarchy ───────────────────────────────────────────────────────

class HttpError(Exception):
    """Lỗi HTTP chung trong net package."""


class RateLimitedError(HttpError, RuntimeError):
    """HTTP 429 Too Many Requests — yêu cầu retry/backoff, không kết thúc truyện."""

    def __init__(self, url: str, status_code: int = 429, detail: str = "") -> None:
        self.url = url
        self.status_code = status_code
        self.detail = detail
        msg = f"HTTP {status_code} rate limited: {url}"
        if detail:
            msg += f" ({detail})"
        super().__init__(msg)


class CloudflareBlockedError(HttpError):
    """Cloudflare challenge hoặc 403 anti-bot reject."""

    def __init__(self, url: str, status_code: int = 403, detail: str = "") -> None:
        self.url = url
        self.status_code = status_code
        self.detail = detail
        msg = f"Cloudflare/Anti-bot blocked [{status_code}]: {url}"
        if detail:
            msg += f" ({detail})"
        super().__init__(msg)


# ── Chrome Fingerprint & Headers ──────────────────────────────────────────────

CHROME_VERSIONS: list[str] = [
    "chrome119",
    "chrome120",
    "chrome123",
    "chrome124",
    "chrome131",
]

CHROME_UA: dict[str, str] = {
    "chrome119": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36"
    ),
    "chrome120": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "chrome123": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
    ),
    "chrome124": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "chrome131": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
}


def pick_chrome_version() -> str:
    """Chọn ngẫu nhiên phiên bản Chrome để impersonate."""
    return random.choice(CHROME_VERSIONS)


def make_headers(version: str | None = None, referer: str | None = None) -> dict[str, str]:
    """Tạo request headers giả lập Chrome browser, hỗ trợ Referer cho site yêu cầu."""
    ver = version or pick_chrome_version()
    headers = {
        "User-Agent": CHROME_UA.get(ver, CHROME_UA["chrome124"]),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
    }
    if referer:
        headers["Referer"] = referer
    return headers


# ── Delay Profiles ────────────────────────────────────────────────────────────

_DELAY_PROFILES: dict[str, tuple[float, float]] = {
    "royalroad.com": (6.0, 14.0),
    "scribblehub.com": (4.0, 10.0),
    "wattpad.com": (3.0, 8.0),
    "fanfiction.net": (2.0, 6.0),
    "archiveofourown.org": (2.0, 5.0),
    "webnovel.com": (3.0, 7.0),
    "69shuba.com": (12.0, 25.0),
}
_DEFAULT_DELAY: tuple[float, float] = (1.0, 3.0)


def _normalize_domain(domain_or_url: str) -> str:
    """Chuẩn hóa netloc về chữ thường và bỏ tiền tố www."""
    netloc = urlparse(domain_or_url).netloc if "://" in domain_or_url else domain_or_url
    domain = netloc.lower().strip()
    if domain.startswith("www."):
        domain = domain[4:]
    return domain


def get_delay(url: str, custom_profiles: dict[str, tuple[float, float]] | None = None) -> float:
    """Lấy khoảng delay ngẫu nhiên (giây) theo domain profile."""
    domain = _normalize_domain(url)
    profiles = custom_profiles or _DELAY_PROFILES
    lo, hi = profiles.get(domain, _DEFAULT_DELAY)
    return random.uniform(lo, hi)


async def sleep_delay(url: str, custom_profiles: dict[str, tuple[float, float]] | None = None) -> float:
    """Tạm dừng ngẫu nhiên theo cấu hình domain của URL."""
    delay = get_delay(url, custom_profiles=custom_profiles)
    await asyncio.sleep(delay)
    return delay


# ── Cloudflare Detection ──────────────────────────────────────────────────────

_CF_PATTERNS = [
    re.compile(r"<title>[^<]*just a moment[^<]*</title>", re.IGNORECASE),
    re.compile(r"<title>[^<]*cloudflare[^<]*</title>", re.IGNORECASE),
    re.compile(r"cf-browser-verification", re.IGNORECASE),
    re.compile(r"checking your browser", re.IGNORECASE),
    re.compile(r"enable javascript and cookies", re.IGNORECASE),
    re.compile(r"ray id.*cloudflare", re.IGNORECASE),
    re.compile(r'id="challenge-form"', re.IGNORECASE),
    re.compile(r"__cf_chl_opt", re.IGNORECASE),
]


def is_cloudflare_challenge(html: str) -> bool:
    """Kiểm tra HTML có chứa dấu hiệu Cloudflare challenge / Turnstile hay không."""
    if not html or len(html) < 40:
        return False
    sample = html[:5000]
    return any(p.search(sample) is not None for p in _CF_PATTERNS)


# ── DomainSessionPool ─────────────────────────────────────────────────────────

class DomainSessionPool:
    """Quản lý curl_cffi async session theo domain.

    Đặc điểm:
      - Tái sử dụng session per domain (TCP keep-alive + cookie jar).
      - Per-host semaphore mặc định 3 (giới hạn concurrency in-flight tránh IP ban).
      - Impersonate Chrome xoay vòng phiên bản.
      - Nhận diện Cloudflare và đánh dấu domain để chuyển Playwright.
      - Phương thức fetch_bytes tải ảnh nhúng an toàn.
      - Quy tắc an toàn: HTTP 429 với body rỗng bắt buộc raise RateLimitedError.
    """

    def __init__(
        self,
        per_host_concurrency: int = 3,
        default_timeout: float = 60.0,
    ) -> None:
        self.per_host_concurrency = max(1, per_host_concurrency)
        self.default_timeout = default_timeout
        self._sessions: dict[str, Any] = {}
        self._host_semaphores: dict[str, asyncio.Semaphore] = {}
        self._cf_domains: set[str] = set()
        self._lock = asyncio.Lock()

    def is_cf_domain(self, domain_or_url: str) -> bool:
        """Kiểm tra domain đã bị đánh dấu cần Playwright hay chưa."""
        domain = _normalize_domain(domain_or_url)
        return domain in self._cf_domains

    def mark_cf_domain(self, domain_or_url: str) -> None:
        """Đánh dấu domain gặp Cloudflare hoặc 403 để các lượt fetch sau dùng Playwright."""
        domain = _normalize_domain(domain_or_url)
        self._cf_domains.add(domain)
        logger.debug("[Pool] CF domain flagged: %s", domain)

    def get_delay(self, url: str) -> float:
        """Lấy giá trị delay ngẫu nhiên theo domain."""
        return get_delay(url)

    async def sleep_delay(self, url: str) -> float:
        """Tạm dừng ngẫu nhiên theo domain."""
        return await sleep_delay(url)

    async def _get_or_create_session(self, domain: str) -> tuple[Any, asyncio.Semaphore]:
        """Lấy session và semaphore cho domain (tạo mới nếu chưa có)."""
        async with self._lock:
            if domain not in self._sessions:
                from curl_cffi.requests import AsyncSession

                version = pick_chrome_version()
                self._sessions[domain] = AsyncSession(impersonate=version)
            if domain not in self._host_semaphores:
                self._host_semaphores[domain] = asyncio.Semaphore(self.per_host_concurrency)

            return self._sessions[domain], self._host_semaphores[domain]

    async def fetch(
        self,
        url: str,
        timeout: float | None = None,
        referer: str | None = None,
    ) -> tuple[int, str]:
        """Fetch URL bằng curl_cffi. Trả về (status_code, html).

        Raise:
            RateLimitedError: Nếu gặp HTTP 429 với HTML rỗng.
            asyncio.CancelledError: Khi coroutine bị cancel.
        """
        domain = _normalize_domain(url)
        version = pick_chrome_version()
        headers = make_headers(version, referer=referer)
        req_timeout = timeout if timeout is not None else self.default_timeout

        try:
            session, sem = await self._get_or_create_session(domain)
            async with sem:
                resp = await session.get(url, headers=headers, timeout=req_timeout)
                html = resp.text or ""
                status = resp.status_code

                # Quy tắc §6.2: HTTP 429 với HTML rỗng -> raise, không coi là hết truyện
                if status == 429 and not html.strip():
                    raise RateLimitedError(url, status_code=429, detail="HTML body is empty")

                return status, html

        except asyncio.CancelledError:
            raise
        except RateLimitedError:
            raise
        except Exception as e:
            logger.warning("[Pool] curl fetch failed for %s: %s", url, e)
            raise

    async def fetch_bytes(
        self,
        url: str,
        timeout: float | None = None,
        referer: str | None = None,
    ) -> tuple[int, bytes, str | None]:
        """Tải dữ liệu nhị phân (hình ảnh) dùng chung session và semaphore theo domain.

        Trả về (status_code, content_bytes, content_type).
        """
        domain = _normalize_domain(url)
        version = pick_chrome_version()
        headers = make_headers(version, referer=referer)
        req_timeout = timeout if timeout is not None else self.default_timeout

        try:
            session, sem = await self._get_or_create_session(domain)
            async with sem:
                resp = await session.get(url, headers=headers, timeout=req_timeout)
                content = resp.content or b""
                content_type = resp.headers.get("Content-Type") if hasattr(resp, "headers") else None
                return resp.status_code, content, content_type

        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning("[Pool] curl fetch_bytes failed for %s: %s", url, e)
            raise

    async def close_domain(self, domain_or_url: str) -> None:
        """Đóng session của một domain cụ thể."""
        domain = _normalize_domain(domain_or_url)
        async with self._lock:
            session = self._sessions.pop(domain, None)
            if session and hasattr(session, "close"):
                try:
                    await session.close()
                except Exception:
                    pass

    async def close_all(self) -> None:
        """Đóng tất cả các session đang mở trong pool."""
        async with self._lock:
            for session in self._sessions.values():
                try:
                    if hasattr(session, "close"):
                        await session.close()
                except Exception:
                    pass
            self._sessions.clear()
            self._host_semaphores.clear()
        logger.debug("[Pool] All domain sessions closed.")


# ── fetch_page Dispatcher ─────────────────────────────────────────────────────

async def fetch_page(
    url: str,
    pool: DomainSessionPool,
    pw_pool: Any = None,
    profile: Any = None,
    timeout: float = 60.0,
    referer: str | None = None,
) -> tuple[int, str]:
    """Dispatcher điều phối giữa curl_cffi và Playwright.

    Nguyên tắc điều phối:
      1. profile.requires_playwright = True hoặc domain đã bị flag CF -> gọi thẳng Playwright.
      2. Mặc định dùng curl_cffi.
      3. Nếu curl_cffi gặp status 403 hoặc Cloudflare challenge:
         - Flag domain thành CF domain.
         - Fallback sang Playwright (nếu pw_pool khả dụng).
      4. Nếu status 429: raise RateLimitedError (không bao giờ coi là hết truyện).
      5. Nếu curl_cffi bị lỗi mạng (Exception) và có pw_pool -> fallback sang Playwright.
    """
    domain = _normalize_domain(url)

    requires_pw = False
    if profile is not None:
        if hasattr(profile, "requires_playwright"):
            requires_pw = bool(profile.requires_playwright)
        elif isinstance(profile, dict):
            requires_pw = bool(profile.get("requires_playwright", False))

    if requires_pw or pool.is_cf_domain(domain):
        if pw_pool is not None:
            return await pw_pool.fetch(url, timeout=timeout, referer=referer)
        logger.warning("[Fetch] Domain %s requires Playwright nhưng pw_pool không khả dụng", domain)

    try:
        status, html = await pool.fetch(url, timeout=timeout, referer=referer)

        if status == 403 or is_cloudflare_challenge(html):
            reason = "HTTP 403" if status == 403 else "Cloudflare challenge"
            logger.info("[Fetch] %s on %s → Fallback Playwright", reason, domain)
            pool.mark_cf_domain(domain)
            if pw_pool is not None:
                return await pw_pool.fetch(url, timeout=timeout, referer=referer)
            if status == 403:
                raise CloudflareBlockedError(url, status_code=403, detail="Anti-bot reject (403)")
            raise CloudflareBlockedError(url, status_code=status, detail="Cloudflare challenge detected")

        if status == 429:
            raise RateLimitedError(url, status_code=429, detail="HTTP 429 rate limited")

        return status, html

    except asyncio.CancelledError:
        raise
    except (RateLimitedError, CloudflareBlockedError):
        raise
    except Exception as e:
        logger.warning("[Fetch] curl fetch failed for %s: %s — trying Playwright fallback", url, e)
        if pw_pool is not None:
            return await pw_pool.fetch(url, timeout=timeout, referer=referer)
        raise
