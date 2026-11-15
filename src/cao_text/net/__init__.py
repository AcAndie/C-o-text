"""Lớp mạng HTTP và trình duyệt Playwright."""
from __future__ import annotations

from cao_text.net.browser import PlaywrightPool
from cao_text.net.http import (
    CHROME_UA,
    CHROME_VERSIONS,
    CloudflareBlockedError,
    DomainSessionPool,
    HttpError,
    RateLimitedError,
    fetch_page,
    get_delay,
    is_cloudflare_challenge,
    make_headers,
    pick_chrome_version,
    sleep_delay,
)

__all__ = [
    "CHROME_UA",
    "CHROME_VERSIONS",
    "CloudflareBlockedError",
    "DomainSessionPool",
    "HttpError",
    "PlaywrightPool",
    "RateLimitedError",
    "fetch_page",
    "get_delay",
    "is_cloudflare_challenge",
    "make_headers",
    "pick_chrome_version",
    "sleep_delay",
]
