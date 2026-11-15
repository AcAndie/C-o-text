from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import BaseModel

from cao_text.ai.gemini import (
    AIRateLimiter,
    ApiKeyPool,
    GeminiProvider,
    classify_api_error,
)
from cao_text.ai.provider import (
    AIFatal,
    AIInvalidOutput,
    AIRateLimited,
    AITransient,
    LLMProvider,
)

# ── 1. Test classify_api_error theo mã lỗi (không dò message) ────────────────


class _FakeAPIError(Exception):
    def __init__(self, code: int, message: str, status: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


def test_classify_api_error_rate_limited() -> None:
    """Mã 429 hoặc 503 hoặc RESOURCE_EXHAUSTED phân loại thành AIRateLimited."""
    err_429 = _FakeAPIError(429, "Too Many Requests")
    c_429 = classify_api_error(err_429, key_hint="key1")
    assert isinstance(c_429, AIRateLimited)
    assert c_429.status_code == 429
    assert c_429.key_hint == "key1"

    err_503 = _FakeAPIError(503, "Service Unavailable")
    c_503 = classify_api_error(err_503)
    assert isinstance(c_503, AIRateLimited)
    assert c_503.status_code == 503

    err_resource = _FakeAPIError(0, "Quota", status="RESOURCE_EXHAUSTED")
    c_res = classify_api_error(err_resource)
    assert isinstance(c_res, AIRateLimited)


def test_classify_api_error_transient_and_fatal() -> None:
    """Mã >=500 (trừ 503) -> AITransient; Mã 4xx -> AIFatal."""
    err_500 = _FakeAPIError(500, "Internal Server Error")
    assert isinstance(classify_api_error(err_500), AITransient)

    err_504 = _FakeAPIError(504, "Gateway Timeout")
    assert isinstance(classify_api_error(err_504), AITransient)

    err_400 = _FakeAPIError(400, "Bad Request")
    assert isinstance(classify_api_error(err_400), AIFatal)

    err_401 = _FakeAPIError(401, "API Key Invalid")
    assert isinstance(classify_api_error(err_401), AIFatal)

    err_403 = _FakeAPIError(403, "Permission Denied")
    assert isinstance(classify_api_error(err_403), AIFatal)

    err_timeout = TimeoutError("Connection timed out")
    assert isinstance(classify_api_error(err_timeout), AITransient)

    err_conn = ConnectionError("Connection refused")
    assert isinstance(classify_api_error(err_conn), AITransient)


# ── 2. Test ApiKeyPool xoay vòng và cooldown ─────────────────────────────────


@pytest.mark.asyncio
async def test_api_key_pool_round_robin() -> None:
    """ApiKeyPool xoay vòng các key khi get_client."""
    keys = ["key-A", "key-B", "key-C"]
    pool = ApiKeyPool(keys, client_factory=lambda k: f"client_{k}")
    assert pool.size == 3

    c1, k1, idx1 = await pool.get_client()
    assert k1 == "key-A"
    assert idx1 == 0

    c2, k2, idx2 = await pool.get_client()
    assert k2 == "key-B"
    assert idx2 == 1

    c3, k3, idx3 = await pool.get_client()
    assert k3 == "key-C"
    assert idx3 == 2

    c4, k4, idx4 = await pool.get_client()
    assert k4 == "key-A"
    assert idx4 == 0


@pytest.mark.asyncio
async def test_api_key_pool_cooldown_and_has_active_key() -> None:
    """Key bị mark_cooling sẽ bị bỏ qua cho đến khi hết cooldown."""
    keys = ["key-1", "key-2"]
    pool = ApiKeyPool(keys, client_factory=lambda k: f"client_{k}")

    assert pool.has_active_key() is True

    # Làm nguội key-1
    await pool.mark_cooling(0, cooldown_sec=10.0)
    assert pool.has_active_key() is True

    # Lấy client tiếp theo phải ra key-2
    _, k2, idx2 = await pool.get_client()
    assert k2 == "key-2"
    assert idx2 == 1

    # Làm nguội nốt key-2
    await pool.mark_cooling(1, cooldown_sec=10.0)
    assert pool.has_active_key() is False


# ── 3. Test AIRateLimiter token-bucket và rollback khi Cancelled ─────────────


@pytest.mark.asyncio
async def test_rate_limiter_rollback_on_cancel() -> None:
    """Nếu task bị CancelledError trong lúc sleep jitter, timestamp đã claim phải rollback."""
    limiter = AIRateLimiter(max_rpm=5, jitter=(2.0, 5.0))

    async def acquire_and_cancel() -> None:
        await limiter.acquire()

    task = asyncio.create_task(acquire_and_cancel())
    # Đợi task chạy vào bước sleep jitter
    await asyncio.sleep(0.05)
    # Lúc này slot đã được claim trong timestamps
    assert len(limiter._timestamps) == 1

    # Huỷ task
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    # Slot phải được rollback
    assert len(limiter._timestamps) == 0


# ── 4. Test GeminiProvider structured output & repair ────────────────────────


class _MockSampleModel(BaseModel):
    title: str
    chapter_count: int


def _make_mock_client(response_obj: Any) -> MagicMock:
    client = MagicMock()
    client.aio = MagicMock()
    client.aio.models = MagicMock()
    client.aio.models.generate_content = AsyncMock(return_value=response_obj)
    return client


@pytest.mark.asyncio
async def test_gemini_provider_implements_protocol() -> None:
    """GeminiProvider tuân thủ LLMProvider Protocol."""
    provider = GeminiProvider(
        api_keys=["test-key"],
        client_factory=lambda k: _make_mock_client(MagicMock()),
    )
    assert isinstance(provider, LLMProvider)
    assert provider.model_name == "gemini-3.8-flash"


@pytest.mark.asyncio
async def test_gemini_provider_generate_with_parsed() -> None:
    """Khi SDK trả về response.parsed, trả về trực tiếp instance của schema."""
    expected = _MockSampleModel(title="Đại Phụng Đả Canh Nhân", chapter_count=900)
    mock_resp = MagicMock()
    mock_resp.parsed = expected

    provider = GeminiProvider(
        api_keys=["test-key"],
        jitter=(0.0, 0.0),
        client_factory=lambda k: _make_mock_client(mock_resp),
    )

    result = await provider.generate("tóm tắt truyện", _MockSampleModel)
    assert result == expected
    assert result.title == "Đại Phụng Đả Canh Nhân"
    assert result.chapter_count == 900


@pytest.mark.asyncio
async def test_gemini_provider_generate_with_raw_json_text() -> None:
    """Khi response.parsed là None, tự động parse từ response.text dạng JSON hoặc markdown block."""
    mock_resp = MagicMock()
    mock_resp.parsed = None
    mock_resp.text = '```json\n{"title": "Mục Thần Ký", "chapter_count": 1200}\n```'

    provider = GeminiProvider(
        api_keys=["test-key"],
        jitter=(0.0, 0.0),
        client_factory=lambda k: _make_mock_client(mock_resp),
    )

    result = await provider.generate("phân tích", _MockSampleModel)
    assert isinstance(result, _MockSampleModel)
    assert result.title == "Mục Thần Ký"
    assert result.chapter_count == 1200


@pytest.mark.asyncio
async def test_gemini_provider_schema_repair_success() -> None:
    """Khi output sai schema lần đầu, tự động gửi lại 1 lần kèm feedback lỗi và parse thành công."""
    bad_resp = MagicMock()
    bad_resp.parsed = None
    bad_resp.text = '{"title": "Thiếu chapter count"}'  # Sai schema do thiếu chapter_count

    good_resp = MagicMock()
    good_resp.parsed = _MockSampleModel(title="Đã sửa", chapter_count=50)

    client = MagicMock()
    client.aio = MagicMock()
    client.aio.models = MagicMock()
    client.aio.models.generate_content = AsyncMock(side_effect=[bad_resp, good_resp])

    provider = GeminiProvider(
        api_keys=["test-key"],
        jitter=(0.0, 0.0),
        client_factory=lambda k: client,
    )

    result = await provider.generate("prompt ban đầu", _MockSampleModel)
    assert result.title == "Đã sửa"
    assert result.chapter_count == 50
    # Đã gọi đúng 2 lần: lần đầu prompt gốc, lần 2 prompt repair
    assert client.aio.models.generate_content.call_count == 2
    repair_call_args = client.aio.models.generate_content.call_args_list[1]
    assert "LƯU Ý: Phản hồi trước đó không hợp lệ với schema" in repair_call_args.kwargs["contents"]


@pytest.mark.asyncio
async def test_gemini_provider_schema_repair_fails_raises_invalid_output() -> None:
    """Khi output sai schema cả 2 lần (sau khi thử repair), raise AIInvalidOutput."""
    bad_resp = MagicMock()
    bad_resp.parsed = None
    bad_resp.text = '{"invalid": "data"}'

    client = MagicMock()
    client.aio = MagicMock()
    client.aio.models = MagicMock()
    client.aio.models.generate_content = AsyncMock(return_value=bad_resp)

    provider = GeminiProvider(
        api_keys=["test-key"],
        jitter=(0.0, 0.0),
        max_retries=1,
        fallback_model="",  # Không bật fallback
        client_factory=lambda k: client,
    )

    with pytest.raises(AIInvalidOutput) as exc_info:
        await provider.generate("prompt", _MockSampleModel)
    assert "không tuân thủ schema" in str(exc_info.value)


@pytest.mark.asyncio
async def test_gemini_provider_instant_key_rotation_on_429() -> None:
    """Khi gặp 429 và pool còn key rảnh, xoay key ngay mà không ngủ backoff."""
    call_keys = []

    def factory(key: str) -> MagicMock:
        client = MagicMock()
        client.aio = MagicMock()
        client.aio.models = MagicMock()

        async def generate_mock(model: str, contents: str, config: Any) -> Any:
            call_keys.append(key)
            if key == "key-1":
                raise _FakeAPIError(429, "Quota exceeded")
            good = MagicMock()
            good.parsed = _MockSampleModel(title="Thành công", chapter_count=1)
            return good

        client.aio.models.generate_content = AsyncMock(side_effect=generate_mock)
        return client

    provider = GeminiProvider(
        api_keys=["key-1", "key-2"],
        jitter=(0.0, 0.0),
        client_factory=factory,
    )

    res = await provider.generate("test prompt", _MockSampleModel)
    assert res.title == "Thành công"
    assert call_keys == ["key-1", "key-2"]
    # key-1 đã vào cooldown
    assert provider.pool._cooldown[0] > 0


@pytest.mark.asyncio
async def test_gemini_provider_fallback_model_on_exhaustion() -> None:
    """Khi model chính thất bại sau max_retries, tự động thử fallback model 1 lần."""
    called_models = []

    def factory(key: str) -> MagicMock:
        client = MagicMock()
        client.aio = MagicMock()
        client.aio.models = MagicMock()

        async def generate_mock(model: str, contents: str, config: Any) -> Any:
            called_models.append(model)
            if model == "gemini-3.8-flash":
                raise _FakeAPIError(500, "Internal error")
            # fallback model thành công
            good = MagicMock()
            good.parsed = _MockSampleModel(title="Fallback thành công", chapter_count=2)
            return good

        client.aio.models.generate_content = AsyncMock(side_effect=generate_mock)
        return client

    provider = GeminiProvider(
        api_keys=["key-1"],
        model="gemini-3.8-flash",
        fallback_model="gemini-2.5-flash",
        max_retries=2,
        backoff_base=0.01,
        jitter=(0.0, 0.0),
        client_factory=factory,
    )

    res = await provider.generate("test", _MockSampleModel)
    assert res.title == "Fallback thành công"
    # Model chính thử 2 lần, sau đó fallback model được gọi 1 lần
    assert called_models == ["gemini-3.8-flash", "gemini-3.8-flash", "gemini-2.5-flash"]
