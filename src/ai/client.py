"""
ai/client.py — Gemini client và AIRateLimiter (token bucket).

FIX-RATELEAK: Rollback timestamp nếu coroutine bị cancel trong jitter sleep.
  Trước: acquire() thêm timestamp vào _timestamps, rồi await asyncio.sleep(jitter).
         Nếu bị cancel trong sleep → timestamp đã tồn tại nhưng request chưa gửi.
         Rate limiter "nghĩ" đã dùng 1 slot → các coroutine khác phải chờ thêm.
         Tự heal sau 60s nhưng gây rate limit sai trong thời gian đó.
  Sau:  Wrap jitter sleep trong try/except CancelledError.
        Nếu cancel: xóa timestamp vừa thêm (rollback), re-raise.
        now được lưu lại trước khi thêm timestamp để dùng làm key khi remove.
        list.remove() xóa lần xuất hiện đầu tiên — safe vì mỗi acquire() thêm
        đúng 1 timestamp với giá trị time.monotonic() khác nhau.
"""
import asyncio
import logging
import random
import time

from google import genai

from config import ALL_GEMINI_KEYS, GEMINI_API_KEY, AI_MAX_RPM, AI_JITTER

logger = logging.getLogger(__name__)


# v1.0.35: Multi-key Gemini pool. Backward compat: single-key setups still work
# because pool degrades to len=1 list. Key rotation triggers on 429/503 retriable
# errors — cooled key skipped until cooldown expires (default 60s, matches
# Gemini per-key quota window).
class ApiKeyPool:
    """Round-robin Gemini API key pool with per-key cooldown on rate limit."""

    def __init__(self, keys: list[str]) -> None:
        if not keys:
            raise ValueError("ApiKeyPool needs ≥1 key")
        self._clients : list[genai.Client] = [genai.Client(api_key=k) for k in keys]
        self._n       : int               = len(self._clients)
        self._cooldown: list[float]       = [0.0] * self._n
        self._idx     : int               = 0
        self._lock                        = asyncio.Lock()

    @property
    def size(self) -> int:
        return self._n

    def has_active_key(self) -> bool:
        """Return True if at least one key is not cooling. Used by retry loop
        to skip backoff wait when alternate key available — v1.1.1 multi-key
        503 instant rotation."""
        now = time.monotonic()
        return any(cool <= now for cool in self._cooldown)

    async def get_client(self) -> genai.Client:
        """Return active (non-cooling) client. Wait if ALL keys cooling."""
        async with self._lock:
            now = time.monotonic()
            for _ in range(self._n):
                if self._cooldown[self._idx] <= now:
                    return self._clients[self._idx]
                self._idx = (self._idx + 1) % self._n
            wait_until = min(self._cooldown)
            wait_sec   = wait_until - now
        if wait_sec > 0:
            print(
                f"  [AI] ⏳ All {self._n} keys cooling. Wait {wait_sec:.1f}s...",
                flush=True,
            )
            await asyncio.sleep(wait_sec)
        return self._clients[self._idx]

    async def mark_rate_limited(self, cooldown_sec: float = 60.0) -> None:
        """Mark current key as cooling for `cooldown_sec` then advance rotation."""
        async with self._lock:
            cooled_idx = self._idx
            self._cooldown[cooled_idx] = time.monotonic() + cooldown_sec
            self._idx = (self._idx + 1) % self._n
        if self._n > 1:
            print(
                f"  [AI] 🔁 Key #{cooled_idx + 1} cooling {cooldown_sec:.0f}s → "
                f"rotate to key #{self._idx + 1}/{self._n}",
                flush=True,
            )


ai_pool = ApiKeyPool(ALL_GEMINI_KEYS or [GEMINI_API_KEY])
# Backward compat: keep ai_client for legacy direct import. Equals first key
# client (not pool-managed — only single-key code paths use this).
ai_client = ai_pool._clients[0]


class AIRateLimiter:
    """
    Token bucket — giới hạn AI calls / phút.
    Lock được release TRƯỚC khi sleep để không block các coroutine khác.
    """

    def __init__(self, max_rpm: int = AI_MAX_RPM) -> None:
        self.max_rpm    = max_rpm
        self._timestamps: list[float] = []
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        # ── Bước 1: chờ đến khi có slot trống, rồi claim slot ────────────────
        claimed_at: float | None = None

        while True:
            async with self._lock:
                now = time.monotonic()
                self._timestamps = [t for t in self._timestamps if now - t < 60.0]
                if len(self._timestamps) < self.max_rpm:
                    # Claim slot: lưu timestamp ngay trong lock
                    self._timestamps.append(now)
                    claimed_at = now
                    break
                oldest   = self._timestamps[0]
                wait_sec = 60.0 - (now - oldest) + 0.1
            print(f"  [AI] ⏳ Rate limit: chờ {wait_sec:.1f}s...", flush=True)
            await asyncio.sleep(wait_sec)

        # ── Bước 2: jitter sleep ngoài lock ──────────────────────────────────
        # FIX-RATELEAK: nếu bị cancel tại đây, request chưa được gửi
        # nhưng timestamp đã được claim ở Bước 1. Cần rollback.
        lo, hi = AI_JITTER
        try:
            await asyncio.sleep(random.uniform(lo, hi))
        except asyncio.CancelledError:
            # Rollback: xóa timestamp vừa claim để không "lãng phí" rate limit slot
            if claimed_at is not None:
                async with self._lock:
                    try:
                        self._timestamps.remove(claimed_at)
                    except ValueError:
                        pass  # đã bị expire và xóa bởi acquire() khác — ok
            raise