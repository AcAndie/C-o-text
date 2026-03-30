"""
core/fetch.py — fetch_page với Cloudflare fallback tự động.

Tách khỏi scraper.py để dễ test và thay thế transport layer.
"""
from urllib.parse import urlparse

from utils.string_helpers import is_cloudflare_challenge
from core.session_pool import DomainSessionPool, PlaywrightPool


async def fetch_page(
    url: str,
    pool: DomainSessionPool,
    pw_pool: PlaywrightPool,
) -> tuple[int, str]:
    """
    Fetch trang với tự động fallback Playwright khi gặp Cloudflare challenge.

    Flow:
      1. Domain đã biết cần PW → dùng thẳng Playwright
      2. curl_cffi trước (nhanh, ít overhead)
      3. Nếu CF challenge → đánh dấu domain, retry bằng Playwright
      4. Nếu Playwright vẫn bị CF → raise RuntimeError
    """
    domain = urlparse(url).netloc.lower()

    # Shortcut: domain đã bị đánh dấu CF từ lần trước
    if pool.is_cf_domain(domain):
        return await pw_pool.fetch(url)

    status, html = await pool.fetch(url)
    if not is_cloudflare_challenge(html):
        return status, html

    # Lần đầu gặp CF challenge
    print(f"  [CF] {domain} → chuyển sang Playwright cho toàn bộ phiên", flush=True)
    pool.mark_cf_domain(domain)
    status, html = await pw_pool.fetch(url)

    if is_cloudflare_challenge(html):
        raise RuntimeError(f"CF challenge không được giải: {url}")

    return status, html