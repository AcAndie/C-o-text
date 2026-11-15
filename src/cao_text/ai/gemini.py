"""GeminiProvider: quản lý key pool, rate limiter, retry và fallback model bằng google-genai async."""
from __future__ import annotations

import asyncio
import json
import logging
import random
import re
import time
from collections.abc import Callable
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

try:
    from google import genai
    from google.genai import errors, types
except ImportError:  # pragma: no cover
    genai = None  # type: ignore[assignment]
    errors = None  # type: ignore[assignment]
    types = None  # type: ignore[assignment]

from cao_text.ai.provider import (
    AIError,
    AIFatal,
    AIInvalidOutput,
    AIRateLimited,
    AITransient,
    LLMProvider,
)

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

_JSON_BLOCK_RE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL | re.IGNORECASE)


def classify_api_error(exc: Exception, key_hint: str | None = None) -> AIError:
    """Phân loại ngoại lệ thành các lớp AIError chuẩn hóa theo mã lỗi SDK (không dò chữ trong message).

    Quy ước mã lỗi:
        - 429 hoặc 503 (hoặc RESOURCE_EXHAUSTED): AIRateLimited
        - 5xx khác (500, 502, 504), timeout, connect drop: AITransient
        - 4xx (400, 401, 403, 404...): AIFatal
    """
    # 1. Lỗi chính thức từ SDK google.genai
    if errors is not None and isinstance(exc, errors.APIError):
        code = getattr(exc, "code", None)
        status = getattr(exc, "status", None)
        msg = getattr(exc, "message", None) or str(exc)

        if code in (429, 503) or status == "RESOURCE_EXHAUSTED":
            return AIRateLimited(msg, key_hint=key_hint, status_code=code or 429)

        if code is not None and code >= 500:
            return AITransient(msg, status_code=code)

        if code is not None and 400 <= code < 500:
            return AIFatal(msg, status_code=code)

        return AIError(msg, status_code=code)

    # 2. Thuộc tính code / status dạng generic nếu đối tượng giả lập lỗi API
    generic_code = getattr(exc, "code", None) or getattr(exc, "status_code", None)
    status = getattr(exc, "status", None)
    msg = getattr(exc, "message", None) or str(exc)

    if status == "RESOURCE_EXHAUSTED" or generic_code in (429, 503):
        return AIRateLimited(msg, key_hint=key_hint, status_code=generic_code or 429)

    if isinstance(generic_code, int):
        if generic_code >= 500:
            return AITransient(msg, status_code=generic_code)
        if 400 <= generic_code < 500:
            return AIFatal(msg, status_code=generic_code)

    # 3. Lỗi mạng / timeout chuẩn
    if isinstance(exc, (TimeoutError, ConnectionError)):
        return AITransient(f"Lỗi kết nối mạng: {exc}")

    # 4. Lỗi httpx (nếu có thư viện httpx bên dưới SDK)
    try:
        import httpx

        if isinstance(exc, (httpx.TimeoutException, httpx.NetworkError)):
            return AITransient(f"Lỗi HTTP client: {exc}")
    except ImportError:
        pass

    return AIError(str(exc))


class AIRateLimiter:
    """Token-bucket rate limiter với cơ chế rollback slot an toàn khi coroutine bị cancel."""

    def __init__(self, max_rpm: int = 10, jitter: tuple[float, float] = (0.5, 2.0)) -> None:
        self.max_rpm = max(1, max_rpm)
        self.jitter = jitter
        self._timestamps: list[float] = []
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        """Xin một suất gọi API. Chờ nếu đã đạt trần requests/phút. Rollback nếu bị cancel."""
        claimed_at: float | None = None
        while True:
            async with self._lock:
                now = time.monotonic()
                # Dọn dẹp timestamps quá 60s
                self._timestamps = [t for t in self._timestamps if now - t < 60.0]
                if len(self._timestamps) < self.max_rpm:
                    self._timestamps.append(now)
                    claimed_at = now
                    break

                oldest = self._timestamps[0]
                wait_sec = 60.0 - (now - oldest) + 0.05

            logger.debug(
                "AIRateLimiter: trần RPM đạt (%d/%d), cần chờ %.2fs",
                len(self._timestamps),
                self.max_rpm,
                wait_sec,
            )
            await asyncio.sleep(wait_sec)

        # Ngủ một khoảng jitter ngẫu nhiên ngoài lock
        lo, hi = self.jitter
        sleep_dur = random.uniform(lo, hi) if hi > lo else lo
        if sleep_dur > 0:
            try:
                await asyncio.sleep(sleep_dur)
            except asyncio.CancelledError:
                # Rollback timestamp slot nếu bị huỷ trong lúc sleep jitter
                if claimed_at is not None:
                    async with self._lock:
                        try:
                            self._timestamps.remove(claimed_at)
                        except ValueError:
                            pass
                raise


class ApiKeyPool:
    """Quản lý danh sách API key xoay vòng (round-robin) kèm cơ chế cooldown khi bị rate-limit."""

    def __init__(
        self,
        keys: list[str],
        client_factory: Callable[[str], Any] | None = None,
        cooldown_sec: float = 60.0,
    ) -> None:
        if not keys:
            raise ValueError("ApiKeyPool cần ít nhất 1 API key hợp lệ.")
        self._keys = list(keys)
        self._factory = client_factory or self._default_factory
        self._clients: list[Any] = [self._factory(k) for k in self._keys]
        self._cooldown: list[float] = [0.0] * len(self._keys)
        self.cooldown_sec = cooldown_sec
        self._idx = 0
        self._lock = asyncio.Lock()

    @staticmethod
    def _default_factory(api_key: str) -> Any:
        if genai is None:
            raise RuntimeError("Thư viện google-genai chưa được cài đặt.")
        return genai.Client(api_key=api_key)

    @property
    def size(self) -> int:
        return len(self._keys)

    def has_active_key(self) -> bool:
        """Kiểm tra xem còn ít nhất một key không nằm trong trạng thái cooldown."""
        now = time.monotonic()
        return any(c <= now for c in self._cooldown)

    async def get_client(self, *, ignore_cooldown: bool = False) -> tuple[Any, str, int]:
        """Lấy client và key index đang rảnh (không cooling).

        Nếu tất cả đều đang cooling:
            - Khi `ignore_cooldown=True` (ví dụ sau khi đã chờ backoff hoặc chuyển sang fallback model):
              chọn ngay key có thời hạn cooldown sắp hết sớm nhất.
            - Khi `ignore_cooldown=False`: chờ đến khi có ít nhất 1 key hết thời gian cooling.
        """
        while True:
            wait_sec = 0.0
            async with self._lock:
                now = time.monotonic()
                n = len(self._keys)
                for _ in range(n):
                    if self._cooldown[self._idx] <= now:
                        chosen_idx = self._idx
                        self._idx = (self._idx + 1) % n
                        return self._clients[chosen_idx], self._keys[chosen_idx], chosen_idx
                    self._idx = (self._idx + 1) % n

                if ignore_cooldown:
                    chosen_idx = min(range(n), key=lambda i: self._cooldown[i])
                    self._idx = (chosen_idx + 1) % n
                    return self._clients[chosen_idx], self._keys[chosen_idx], chosen_idx

                wait_until = min(self._cooldown)
                wait_sec = max(0.0, wait_until - now + 0.1)

            if wait_sec > 0:
                logger.warning(
                    "Tất cả %d Gemini API keys đều đang cooling. Chờ %.1fs...",
                    len(self._keys),
                    wait_sec,
                )
                await asyncio.sleep(wait_sec)

    async def mark_cooling(self, key_idx: int, cooldown_sec: float | None = None) -> None:
        """Đánh dấu một key cần làm nguội và xoay vòng ngay sang key tiếp theo."""
        dur = self.cooldown_sec if cooldown_sec is None else cooldown_sec
        async with self._lock:
            if 0 <= key_idx < len(self._cooldown):
                self._cooldown[key_idx] = time.monotonic() + dur
                self._idx = (key_idx + 1) % len(self._keys)
                masked = self._mask_key(self._keys[key_idx])
                active_count = sum(1 for c in self._cooldown if c <= time.monotonic())
                logger.info(
                    "API Key #%d (%s) vào cooldown %.0fs (còn %d/%d key active)",
                    key_idx + 1,
                    masked,
                    dur,
                    active_count,
                    len(self._keys),
                )

    @staticmethod
    def _mask_key(key: str) -> str:
        if len(key) <= 8:
            return "***"
        return f"{key[:4]}...{key[-4:]}"


class GeminiProvider(LLMProvider):
    """Cài đặt LLMProvider sử dụng Google Gemini SDK với async, key pool, retry và structured output."""

    def __init__(
        self,
        api_keys: list[str],
        *,
        model: str = "gemini-3.8-flash",
        fallback_model: str = "gemini-2.5-flash",
        max_rpm: int = 10,
        jitter: tuple[float, float] = (0.5, 2.0),
        max_retries: int = 3,
        backoff_base: float = 1.0,
        max_backoff: float = 30.0,
        cooldown_sec: float = 60.0,
        client_factory: Callable[[str], Any] | None = None,
    ) -> None:
        self.model = model
        self.fallback_model = fallback_model
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        self.max_backoff = max_backoff
        self.cooldown_sec = cooldown_sec
        self.pool = ApiKeyPool(
            api_keys,
            client_factory=client_factory,
            cooldown_sec=cooldown_sec,
        )
        self.limiter = AIRateLimiter(max_rpm=max_rpm, jitter=jitter)

    @property
    def model_name(self) -> str:
        return self.model

    async def generate(
        self,
        prompt: str,
        schema: type[T],
        *,
        system_instruction: str | None = None,
        temperature: float | None = None,
    ) -> T:
        """Gửi prompt và trả về kết quả tuân thủ Pydantic schema với cơ chế retry và fallback model."""
        last_error: AIError | None = None

        # 1. Thử trên model chính (kèm retry)
        for attempt in range(self.max_retries):
            is_last_attempt = attempt >= self.max_retries - 1
            try:
                return await self._execute_attempt(
                    model=self.model,
                    prompt=prompt,
                    schema=schema,
                    system_instruction=system_instruction,
                    temperature=temperature,
                    can_repair=True,
                    ignore_cooldown=(attempt > 0),
                )
            except asyncio.CancelledError:
                raise
            except AIFatal:
                # Lỗi nghiêm trọng (sai key, model cấm...) không retry
                raise
            except AIRateLimited as e:
                last_error = e
                # Kiểm tra nếu còn key khác rảnh trong pool thì bỏ qua sleep backoff để xoay key ngay
                if self.pool.has_active_key():
                    logger.info("Key bị rate-limit nhưng pool còn key khác. Thử ngay với key rảnh...")
                    continue
                if is_last_attempt:
                    break

                wait_sec = min(self.backoff_base * (2**attempt), self.max_backoff) + random.uniform(0.1, 0.5)
                logger.warning("Rate-limit toàn bộ keys (attempt %d/%d). Chờ %.1fs...", attempt + 1, self.max_retries, wait_sec)
                await asyncio.sleep(wait_sec)
            except (AITransient, AIInvalidOutput) as e:
                last_error = e
                if is_last_attempt:
                    break
                wait_sec = min(self.backoff_base * (2**attempt), self.max_backoff) + random.uniform(0.1, 0.5)
                logger.warning(
                    "%s trên model %s (attempt %d/%d). Chờ %.1fs...",
                    type(e).__name__,
                    self.model,
                    attempt + 1,
                    self.max_retries,
                    wait_sec,
                )
                await asyncio.sleep(wait_sec)
            except Exception as e:
                last_error = classify_api_error(e)
                if isinstance(last_error, AIFatal):
                    raise last_error from e
                if is_last_attempt:
                    break
                wait_sec = min(self.backoff_base * (2**attempt), self.max_backoff)
                await asyncio.sleep(wait_sec)

        # 2. Hết retry trên model chính -> thử fallback model một lần (nếu khác model chính)
        if self.fallback_model and self.fallback_model != self.model:
            logger.warning(
                "Model chính '%s' thất bại sau %d lần thử. Chuyển sang thử fallback model '%s' 1 lần duy nhất...",
                self.model,
                self.max_retries,
                self.fallback_model,
            )
            try:
                return await self._execute_attempt(
                    model=self.fallback_model,
                    prompt=prompt,
                    schema=schema,
                    system_instruction=system_instruction,
                    temperature=temperature,
                    can_repair=True,
                    ignore_cooldown=True,
                )
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error("Fallback model '%s' cũng thất bại: %s", self.fallback_model, e)
                last_error = classify_api_error(e)

        if last_error is not None:
            raise last_error
        raise AIError(f"Không thể sinh phản hồi từ model {self.model}")

    async def _execute_attempt(
        self,
        *,
        model: str,
        prompt: str,
        schema: type[T],
        system_instruction: str | None = None,
        temperature: float | None = None,
        can_repair: bool = True,
        ignore_cooldown: bool = False,
    ) -> T:
        """Thực hiện một lần gọi API với token bucket rate limit, xoay key và kiểm tra schema."""
        await self.limiter.acquire()
        client, key_str, key_idx = await self.pool.get_client(ignore_cooldown=ignore_cooldown)

        # Tạo cấu hình gọi API với structured output
        config_kwargs: dict[str, Any] = {
            "response_mime_type": "application/json",
            "response_schema": schema,
        }
        if system_instruction:
            config_kwargs["system_instruction"] = system_instruction
        if temperature is not None:
            config_kwargs["temperature"] = temperature

        config = types.GenerateContentConfig(**config_kwargs) if types is not None else None

        try:
            response = await client.aio.models.generate_content(
                model=model,
                contents=prompt,
                config=config,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            classified = classify_api_error(exc, key_hint=self.pool._mask_key(key_str))
            if isinstance(classified, AIRateLimited):
                await self.pool.mark_cooling(key_idx, cooldown_sec=self.cooldown_sec)
            raise classified from exc

        # Phân tích cú pháp phản hồi
        return await self._parse_and_validate_response(
            response=response,
            model=model,
            prompt=prompt,
            schema=schema,
            system_instruction=system_instruction,
            temperature=temperature,
            can_repair=can_repair,
        )

    async def _parse_and_validate_response(
        self,
        *,
        response: Any,
        model: str,
        prompt: str,
        schema: type[T],
        system_instruction: str | None,
        temperature: float | None,
        can_repair: bool,
    ) -> T:
        """Trích xuất và kiểm tra tính hợp lệ của output theo Pydantic schema."""
        parsed = getattr(response, "parsed", None)
        if parsed is not None:
            if isinstance(parsed, schema):
                return parsed
            if isinstance(parsed, dict):
                try:
                    return schema.model_validate(parsed)
                except ValidationError as e:
                    return await self._handle_schema_error(
                        error=e,
                        raw_text=json.dumps(parsed, ensure_ascii=False),
                        model=model,
                        prompt=prompt,
                        schema=schema,
                        system_instruction=system_instruction,
                        temperature=temperature,
                        can_repair=can_repair,
                    )

        # Nếu parsed không có sẵn, thử parse qua response.text
        raw_text = getattr(response, "text", "") or ""
        clean_text = raw_text.strip()
        match = _JSON_BLOCK_RE.match(clean_text)
        if match:
            clean_text = match.group(1).strip()

        if not clean_text:
            return await self._handle_schema_error(
                error=ValueError("Model trả về phản hồi rỗng"),
                raw_text="",
                model=model,
                prompt=prompt,
                schema=schema,
                system_instruction=system_instruction,
                temperature=temperature,
                can_repair=can_repair,
            )

        try:
            return schema.model_validate_json(clean_text)
        except (ValidationError, ValueError, json.JSONDecodeError) as e:
            return await self._handle_schema_error(
                error=e,
                raw_text=raw_text,
                model=model,
                prompt=prompt,
                schema=schema,
                system_instruction=system_instruction,
                temperature=temperature,
                can_repair=can_repair,
            )

    async def _handle_schema_error(
        self,
        *,
        error: Exception,
        raw_text: str,
        model: str,
        prompt: str,
        schema: type[T],
        system_instruction: str | None,
        temperature: float | None,
        can_repair: bool,
    ) -> T:
        """Xử lý lỗi schema: gọi lại 1 lần kèm phản hồi lỗi validate nếu can_repair=True."""
        inv_err = AIInvalidOutput(
            f"Phản hồi từ {model} không tuân thủ schema: {error}",
            raw_text=raw_text,
            validation_error=error,
        )

        if can_repair:
            logger.warning(
                "Phản hồi từ model %s sai schema: %s. Thử gọi lại 1 lần kèm lỗi validate...",
                model,
                error,
            )
            repair_prompt = (
                f"{prompt}\n\n"
                f"[LƯU Ý: Phản hồi trước đó không hợp lệ với schema]:\n"
                f"Lỗi xác thực: {error}\n"
                f"Nội dung nhận được: {raw_text[:300]}\n"
                f"Vui lòng chỉ trả về đúng định dạng JSON tuân thủ cấu trúc mong đợi."
            )
            return await self._execute_attempt(
                model=model,
                prompt=repair_prompt,
                schema=schema,
                system_instruction=system_instruction,
                temperature=temperature,
                can_repair=False,  # Chỉ sửa 1 lần
            )

        raise inv_err
