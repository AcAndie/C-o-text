"""
main.py — Điểm khởi chạy duy nhất của chương trình.

BUG-1 FIX: asyncio.gather() bây giờ được bọc trong try/except CancelledError.
  Khi Ctrl+C được nhấn, event loop cancel tất cả tasks. CancelledError
  sẽ được bắt ở đây để:
  1. In thông báo rõ ràng thay vì traceback dài
  2. Đảm bảo finally block (pool.close_all, app.close) luôn chạy
  3. Không bị confuse với "crash" — đây là shutdown bình thường
"""
import sys
import io
import asyncio
import hashlib
import os
from datetime import datetime
from urllib.parse import urlparse

import warnings
warnings.filterwarnings("ignore", category=UserWarning)
warnings.filterwarnings("ignore", category=FutureWarning)

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True)
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace", line_buffering=True)

from config import INIT_STAGGER, AI_MAX_RPM
from ai.client import AIRateLimiter
from core.session_pool import DomainSessionPool, PlaywrightPool
from utils.file_io import load_profiles
from core.scraper import run_novel_task


# ── AppState ──────────────────────────────────────────────────────────────────

class AppState:
    __slots__ = (
        "profiles_lock", "total_lock",
        "ai_limiter", "pw_pool",
        "_total_this_sess", "_session_start",
    )

    def __init__(self) -> None:
        self.profiles_lock    = asyncio.Lock()
        self.total_lock       = asyncio.Lock()
        self.ai_limiter       = AIRateLimiter(AI_MAX_RPM)
        self.pw_pool          = PlaywrightPool()
        self._total_this_sess = 0
        self._session_start   = datetime.now()

    @property
    def total(self) -> int:
        return self._total_this_sess

    async def inc_total(self) -> int:
        async with self.total_lock:
            self._total_this_sess += 1
            return self._total_this_sess

    def elapsed_str(self) -> str:
        s      = int((datetime.now() - self._session_start).total_seconds())
        h, rem = divmod(s, 3600)
        m, sec = divmod(rem, 60)
        return f"{h:02d}:{m:02d}:{sec:02d}"

    async def close(self) -> None:
        await self.pw_pool.close()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _is_valid_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
        return parsed.scheme in ("http", "https") and bool(parsed.netloc)
    except Exception:
        return False

def _make_output_dir(url: str) -> str:
    parsed = urlparse(url)
    domain = parsed.netloc.replace("www.", "").replace(".", "_")
    parts  = [p for p in parsed.path.strip("/").split("/") if p][:2]
    slug   = "_".join(parts) if parts else "unknown"
    return os.path.join("output", f"{domain}_{slug}")

def _make_progress_path(url: str) -> str:
    out_dir   = _make_output_dir(url)
    domain    = urlparse(url).netloc.replace(".", "_")
    url_hash  = hashlib.md5(url.encode()).hexdigest()[:8]
    base_slug = out_dir.split(os.sep)[-1]
    return f"progress_{domain}_{base_slug}_{url_hash}.json"


# ── Main ──────────────────────────────────────────────────────────────────────

async def main() -> None:
    links_file = sys.argv[1] if len(sys.argv) > 1 else "links.txt"
    if not os.path.exists(links_file):
        print(f"[ERR] Không tìm thấy {links_file}")
        return

    with open(links_file, "r", encoding="utf-8") as f:
        raw_urls = [
            line.strip()
            for line in f
            if line.strip() and not line.strip().startswith("#")
        ]

    urls = [u for u in raw_urls if _is_valid_url(u)]
    skipped = len(raw_urls) - len(urls)
    if skipped:
        print(f"[WARN] Bỏ qua {skipped} URL không hợp lệ (thiếu http:// hoặc sai định dạng)")

    if not urls:
        print("[ERR] Không có URL hợp lệ nào trong links.txt")
        return

    print(f"📚 Tìm thấy {len(urls)} truyện cần cào\n")

    app      = AppState()
    pool     = DomainSessionPool()
    profiles = await load_profiles()
    print(f"📋 Đã load {len(profiles)} domain profile\n")

    async def _staggered_task(url: str, idx: int):
        await asyncio.sleep(idx * INIT_STAGGER)
        await run_novel_task(
            start_url       = url,
            output_dir      = _make_output_dir(url),
            progress_path   = _make_progress_path(url),
            pool            = pool,
            pw_pool         = app.pw_pool,
            profiles        = profiles,
            profiles_lock   = app.profiles_lock,
            ai_limiter      = app.ai_limiter,
            on_chapter_done = app.inc_total,
        )

    # BUG-1 FIX: Bắt CancelledError (Ctrl+C / external shutdown) để:
    #   1. In thông báo rõ ràng
    #   2. Đảm bảo finally block chạy (đóng pool, lưu progress)
    #   3. Tránh traceback dài confusing
    cancelled = False
    try:
        results = await asyncio.gather(
            *[_staggered_task(url, i) for i, url in enumerate(urls)],
            return_exceptions=True,
        )
    except asyncio.CancelledError:
        cancelled = True
        print(
            f"\n⚠️  Nhận tín hiệu dừng (Ctrl+C). Progress đã được lưu tự động.",
            flush=True,
        )
        results = []
    finally:
        await pool.close_all()
        await app.close()

    if not cancelled:
        for url, result in zip(urls, results):
            if isinstance(result, Exception):
                print(
                    f"[ERR] Truyện thất bại: {url[:60]}\n"
                    f"      {type(result).__name__}: {result}",
                    flush=True,
                )

    print(
        f"\n{'─'*60}\n"
        f"✔ Tổng kết: {app.total} chương "
        f"trong {app.elapsed_str()}\n"
        f"{'─'*60}"
    )


if __name__ == "__main__":
    asyncio.run(main())