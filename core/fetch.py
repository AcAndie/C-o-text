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

from utils.string_helpers import is_cloudflare_challenge, is_junk_page

logger = logging.getLogger(__name__)


async def fetch_page(
    url        : str,
    pool,
    pw_pool,
    profile    : dict | None = None,
    timeout    : int = 60,
) -> tuple[int, str]:
    """
    Fetch một URL. Trả về (status_code, html).

    Logic:
        - requires_playwright=True hoặc domain flagged CF → Playwright thẳng
        - Else: thử curl, nếu CF challenge → Playwright fallback
    """
    domain      = urlparse(url).netloc.lower()
    requires_pw = bool((profile or {}).get("requires_playwright", False))

    if requires_pw or (pool and pool.is_cf_domain(domain)):
        return await pw_pool.fetch(url, timeout=timeout)

    try:
        status, html = await pool.fetch(url, timeout=timeout)

        if is_cloudflare_challenge(html):
            logger.info("[Fetch] CF challenge on %s → Playwright", domain)
            pool.mark_cf_domain(domain)
            return await pw_pool.fetch(url, timeout=timeout)

        return status, html

    except asyncio.CancelledError:
        raise
    except Exception as e:
        logger.warning("[Fetch] curl failed for %s: %s — trying Playwright", url, e)
        return await pw_pool.fetch(url, timeout=timeout)