"""
ai/client.py — Khởi tạo Gemini client và rate limiter.
"""
import asyncio
import random
import time

from google import genai

from config import GEMINI_API_KEY, AI_MAX_RPM, AI_JITTER

ai_client = genai.Client(api_key=GEMINI_API_KEY)


class AIRateLimiter:
    """
    Token bucket giới hạn số lần gọi Gemini API / phút.

    BUG FIX: Lock được release TRƯỚC khi sleep → các coroutine khác
    không bị block trong thời gian chờ. Pattern: acquire lock → check →
    nếu cần chờ thì release lock → sleep → thử lại vòng lặp.
    """

    def __init__(self, max_rpm: int = AI_MAX_RPM) -> None:
        self.max_rpm = max_rpm
        self._timestamps: list[float] = []
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        while True:
            async with self._lock:
                now = time.monotonic()
                # Xóa timestamp cũ ngoài cửa sổ 60s
                self._timestamps = [t for t in self._timestamps if now - t < 60.0]

                if len(self._timestamps) < self.max_rpm:
                    # Còn slot → ghi timestamp và thoát khỏi lock ngay
                    self._timestamps.append(now)
                    break

                # Hết slot → tính thời gian chờ rồi release lock TRƯỚC khi sleep
                oldest   = self._timestamps[0]
                wait_sec = 60.0 - (now - oldest) + 0.1

            # ← Lock đã được release; các coroutine khác có thể acquire
            print(f"  [AI] ⏳ Rate limit: chờ {wait_sec:.1f}s...", flush=True)
            await asyncio.sleep(wait_sec)
            # Vòng lặp tiếp theo sẽ re-acquire lock và kiểm tra lại

        # Jitter nhỏ sau khi được cấp phép để giảm burst
        lo, hi = AI_JITTER
        await asyncio.sleep(random.uniform(lo, hi))