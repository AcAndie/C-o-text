"""Unit tests cho cao_text.net (DomainSessionPool, PlaywrightPool, fetch_page).

Chạy hoàn toàn OFFLINE bằng mock / fake objects theo quy tắc §3.2.
"""
from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cao_text.net.browser import PlaywrightPool
from cao_text.net.http import (
    CHROME_VERSIONS,
    CloudflareBlockedError,
    DomainSessionPool,
    RateLimitedError,
    fetch_page,
    get_delay,
    is_cloudflare_challenge,
    make_headers,
    pick_chrome_version,
)

# ── Headers & Chrome Fingerprint Tests ────────────────────────────────────────

def test_pick_chrome_version() -> None:
    ver = pick_chrome_version()
    assert ver in CHROME_VERSIONS


def test_make_headers() -> None:
    headers = make_headers("chrome124", referer="https://example.com/index")
    assert headers["User-Agent"]
    assert headers["Referer"] == "https://example.com/index"
    assert "gzip" in headers["Accept-Encoding"]

    headers_no_ref = make_headers("chrome124")
    assert "Referer" not in headers_no_ref


# ── Delay Tests ───────────────────────────────────────────────────────────────

def test_get_delay_domain_normalization() -> None:
    # royalroad.com: (6.0, 14.0)
    delay1 = get_delay("https://www.royalroad.com/fiction/123/chapter/1")
    assert 6.0 <= delay1 <= 14.0

    delay2 = get_delay("https://royalroad.com/fiction/123/chapter/1")
    assert 6.0 <= delay2 <= 14.0

    # default: (1.0, 3.0)
    delay_default = get_delay("https://unknown-site.org/ch1")
    assert 1.0 <= delay_default <= 3.0


# ── Cloudflare Detection Tests ────────────────────────────────────────────────

def test_is_cloudflare_challenge() -> None:
    assert not is_cloudflare_challenge("")
    assert not is_cloudflare_challenge("<html><body>Short</body></html>")
    assert not is_cloudflare_challenge(
        "<html><body><h1>Normal chapter content</h1>" + ("<p>Text</p>" * 50) + "</body></html>"
    )

    cf_html_1 = "<html><head><title>Just a moment...</title></head><body>Verify your browser please</body></html>"
    assert is_cloudflare_challenge(cf_html_1)

    cf_html_2 = (
        '<html><body><form id="challenge-form"><div class="cf-browser-verification"></div></form></body></html>'
    )
    assert is_cloudflare_challenge(cf_html_2)


# ── DomainSessionPool Tests ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_domain_session_pool_cf_flags() -> None:
    pool = DomainSessionPool(per_host_concurrency=2)
    url = "https://www.novel-site.com/ch1"
    domain = "novel-site.com"

    assert not pool.is_cf_domain(url)
    assert not pool.is_cf_domain(domain)

    pool.mark_cf_domain(url)
    assert pool.is_cf_domain(url)
    assert pool.is_cf_domain(domain)
    assert pool.is_cf_domain("https://novel-site.com/ch2")


@pytest.mark.asyncio
async def test_domain_session_pool_fetch_success() -> None:
    pool = DomainSessionPool(per_host_concurrency=2)

    fake_resp = MagicMock()
    fake_resp.status_code = 200
    fake_resp.text = "<html><body>Chapter 1 content</body></html>"

    fake_session = MagicMock()
    fake_session.get = AsyncMock(return_value=fake_resp)

    with patch("curl_cffi.requests.AsyncSession", return_value=fake_session):
        status, html = await pool.fetch("https://example.com/chapter-1")
        assert status == 200
        assert "Chapter 1" in html

        # Fetch URL cùng domain sẽ tái sử dụng session
        await pool.fetch("https://example.com/chapter-2")
        assert fake_session.get.call_count == 2
        assert len(pool._sessions) == 1

    await pool.close_all()
    assert len(pool._sessions) == 0


@pytest.mark.asyncio
async def test_domain_session_pool_429_empty_raises() -> None:
    pool = DomainSessionPool()

    fake_resp = MagicMock()
    fake_resp.status_code = 429
    fake_resp.text = "   "  # HTML rỗng

    fake_session = MagicMock()
    fake_session.get = AsyncMock(return_value=fake_resp)

    with patch("curl_cffi.requests.AsyncSession", return_value=fake_session):
        with pytest.raises(RateLimitedError) as exc_info:
            await pool.fetch("https://example.com/chapter-1")

        assert exc_info.value.status_code == 429
        assert "rate limited" in str(exc_info.value).lower()
        # Xác nhận cũng là RuntimeError để tương thích guard cũ
        assert isinstance(exc_info.value, RuntimeError)

    await pool.close_all()


@pytest.mark.asyncio
async def test_domain_session_pool_fetch_bytes() -> None:
    pool = DomainSessionPool()

    fake_resp = MagicMock()
    fake_resp.status_code = 200
    fake_resp.content = b"\x89PNG\r\n\x1a\nfakeimagebytes"
    fake_resp.headers = {"Content-Type": "image/png"}

    fake_session = MagicMock()
    fake_session.get = AsyncMock(return_value=fake_resp)

    with patch("curl_cffi.requests.AsyncSession", return_value=fake_session):
        status, content, ctype = await pool.fetch_bytes("https://example.com/images/cover.png")
        assert status == 200
        assert content.startswith(b"\x89PNG")
        assert ctype == "image/png"

    await pool.close_all()


@pytest.mark.asyncio
async def test_domain_session_pool_concurrency_semaphore() -> None:
    pool = DomainSessionPool(per_host_concurrency=1)

    in_flight = 0
    max_in_flight = 0

    async def fake_get(*args: Any, **kwargs: Any) -> Any:
        nonlocal in_flight, max_in_flight
        in_flight += 1
        if in_flight > max_in_flight:
            max_in_flight = in_flight
        await asyncio.sleep(0.05)
        in_flight -= 1
        resp = MagicMock()
        resp.status_code = 200
        resp.text = "ok"
        return resp

    fake_session = MagicMock()
    fake_session.get = AsyncMock(side_effect=fake_get)

    with patch("curl_cffi.requests.AsyncSession", return_value=fake_session):
        tasks = [
            pool.fetch("https://example.com/ch1"),
            pool.fetch("https://example.com/ch2"),
            pool.fetch("https://example.com/ch3"),
        ]
        results = await asyncio.gather(*tasks)
        assert len(results) == 3
        assert max_in_flight == 1  # Bị chặn bởi per_host_concurrency=1

    await pool.close_all()


# ── PlaywrightPool Tests ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_playwright_pool_fetch_success() -> None:
    pool = PlaywrightPool(max_concurrency=2)

    fake_page = MagicMock()
    fake_page.goto = AsyncMock(return_value=MagicMock(status=200))
    fake_page.wait_for_timeout = AsyncMock()
    fake_page.content = AsyncMock(return_value="<html><body>PW Content</body></html>")
    fake_page.set_extra_http_headers = AsyncMock()
    fake_page.close = AsyncMock()

    fake_browser = MagicMock()
    fake_browser.new_page = AsyncMock(return_value=fake_page)
    fake_browser.close = AsyncMock()

    fake_pw = MagicMock()
    fake_pw.chromium.launch = AsyncMock(return_value=fake_browser)

    pool._playwright = fake_pw
    pool._browser = fake_browser

    status, html = await pool.fetch("https://example.com/pw-page")
    assert status == 200
    assert "PW Content" in html
    assert pool._page_count == 1
    fake_page.close.assert_awaited_once()

    await pool.close()
    fake_browser.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_playwright_pool_429_empty_raises() -> None:
    pool = PlaywrightPool()

    fake_page = MagicMock()
    fake_page.goto = AsyncMock(return_value=MagicMock(status=429))
    fake_page.wait_for_timeout = AsyncMock()
    fake_page.content = AsyncMock(return_value="")  # HTML rỗng
    fake_page.set_extra_http_headers = AsyncMock()
    fake_page.close = AsyncMock()

    fake_browser = MagicMock()
    fake_browser.new_page = AsyncMock(return_value=fake_page)
    fake_browser.close = AsyncMock()

    pool._browser = fake_browser

    with pytest.raises(RateLimitedError):
        await pool.fetch("https://example.com/rate-limited")

    fake_page.close.assert_awaited_once()
    await pool.close()


# ── fetch_page Dispatcher Tests ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_fetch_page_requires_playwright_profile() -> None:
    pool = MagicMock(spec=DomainSessionPool)
    pool.is_cf_domain.return_value = False
    pool.fetch = AsyncMock()

    pw_pool = MagicMock(spec=PlaywrightPool)
    pw_pool.fetch = AsyncMock(return_value=(200, "<html>pw rendered</html>"))

    profile = {"requires_playwright": True}

    status, html = await fetch_page("https://example.com/ch1", pool, pw_pool=pw_pool, profile=profile)
    assert status == 200
    assert "pw rendered" in html
    pw_pool.fetch.assert_awaited_once()
    pool.fetch.assert_not_called()


@pytest.mark.asyncio
async def test_fetch_page_cloudflare_challenge_fallback() -> None:
    pool = MagicMock(spec=DomainSessionPool)
    pool.is_cf_domain.return_value = False
    cf_html = "<html><head><title>Just a moment...</title></head><body>Cloudflare Challenge Body</body></html>"
    pool.fetch = AsyncMock(return_value=(200, cf_html))
    pool.mark_cf_domain = MagicMock()

    pw_pool = MagicMock(spec=PlaywrightPool)
    pw_pool.fetch = AsyncMock(return_value=(200, "<html>bypassed content</html>"))

    status, html = await fetch_page("https://cf-site.com/ch1", pool, pw_pool=pw_pool)
    assert status == 200
    assert "bypassed content" in html
    pool.mark_cf_domain.assert_called_with("cf-site.com")
    pw_pool.fetch.assert_awaited_once()


@pytest.mark.asyncio
async def test_fetch_page_403_fallback() -> None:
    pool = MagicMock(spec=DomainSessionPool)
    pool.is_cf_domain.return_value = False
    pool.fetch = AsyncMock(return_value=(403, "Forbidden"))
    pool.mark_cf_domain = MagicMock()

    pw_pool = MagicMock(spec=PlaywrightPool)
    pw_pool.fetch = AsyncMock(return_value=(200, "<html>real browser content</html>"))

    status, html = await fetch_page("https://69shuba.cx/ch1", pool, pw_pool=pw_pool)
    assert status == 200
    assert "real browser content" in html
    pool.mark_cf_domain.assert_called_with("69shuba.cx")


@pytest.mark.asyncio
async def test_fetch_page_blocked_without_pw_pool() -> None:
    pool = MagicMock(spec=DomainSessionPool)
    pool.is_cf_domain.return_value = False
    pool.fetch = AsyncMock(return_value=(403, "Access Denied"))
    pool.mark_cf_domain = MagicMock()

    with pytest.raises(CloudflareBlockedError) as exc_info:
        await fetch_page("https://blocked-site.com/ch1", pool, pw_pool=None)

    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_fetch_page_429_always_raises() -> None:
    pool = MagicMock(spec=DomainSessionPool)
    pool.is_cf_domain.return_value = False
    pool.fetch = AsyncMock(return_value=(429, "Too Many Requests"))

    with pytest.raises(RateLimitedError):
        await fetch_page("https://example.com/ch1", pool)


@pytest.mark.asyncio
async def test_fetch_page_curl_exception_fallback_pw() -> None:
    pool = MagicMock(spec=DomainSessionPool)
    pool.is_cf_domain.return_value = False
    pool.fetch = AsyncMock(side_effect=RuntimeError("Connection reset by peer"))

    pw_pool = MagicMock(spec=PlaywrightPool)
    pw_pool.fetch = AsyncMock(return_value=(200, "<html>recovered via pw</html>"))

    status, html = await fetch_page("https://example.com/ch1", pool, pw_pool=pw_pool)
    assert status == 200
    assert "recovered via pw" in html
    pw_pool.fetch.assert_awaited_once()
