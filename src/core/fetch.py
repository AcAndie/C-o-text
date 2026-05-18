"""
core/fetch.py — Generic fetch_page() dispatcher.

Lựa chọn curl vs Playwright dựa trên:
  1. profile.requires_playwright
  2. Domain đã bị flagged CF trong pool
  3. Default: curl, fallback playwright nếu CF challenge

Public API:
    fetch_page(url, pool, pw_pool, profile=None) → (status, html)
"""
from __future__ import annotations

import asyncio
import logging
from urllib.parse import urlparse

from utils.string_helpers import is_cloudflare_challenge

logger = logging.getLogger(__name__)


async def fetch_page(
    url        : str,
    pool,
    pw_pool,
    profile    : dict | None = None,
    timeout    : int = 60,
    referer    : str | None = None,
) -> tuple[int, str]:
    """
    Fetch một URL. Trả về (status_code, html).

    Logic:
        - requires_playwright=True hoặc domain flagged CF → Playwright thẳng
        - Else: thử curl, nếu CF challenge / 403 → Playwright fallback
        - v1.0.24: status 403 cũng trigger PW fallback (anti-bot reject)
        - v1.0.24: optional referer cho sites kiểm tra referer header
    """
    domain      = urlparse(url).netloc.lower()
    requires_pw = bool((profile or {}).get("requires_playwright", False))

    if requires_pw or (pool and pool.is_cf_domain(domain)):
        return await pw_pool.fetch(url, timeout=timeout, referer=referer)

    try:
        status, html = await pool.fetch(url, timeout=timeout, referer=referer)

        # v1.0.24: 403 = anti-bot outright reject (no challenge body).
        # PW with real browser fingerprint may pass. Flag domain to skip
        # curl retry trên subsequent fetches.
        if status == 403 or is_cloudflare_challenge(html):
            reason = "403" if status == 403 else "CF challenge"
            logger.info("[Fetch] %s on %s → Playwright", reason, domain)
            pool.mark_cf_domain(domain)
            return await pw_pool.fetch(url, timeout=timeout, referer=referer)

        return status, html

    except asyncio.CancelledError:
        raise
    except Exception as e:
        logger.warning("[Fetch] curl failed for %s: %s — trying Playwright", url, e)
        return await pw_pool.fetch(url, timeout=timeout, referer=referer)