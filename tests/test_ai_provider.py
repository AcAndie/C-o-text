from __future__ import annotations

import pytest
from pydantic import BaseModel

from cao_text.ai.provider import (
    AIError,
    AIFatal,
    AIInvalidOutput,
    AIRateLimited,
    AITransient,
    LLMProvider,
)


def test_exception_hierarchy() -> None:
    """Tất cả lỗi chuẩn hóa đều là con của AIError và Exception."""
    err_rate = AIRateLimited("Rate limited", retry_after=60.0, key_hint="key-1")
    err_transient = AITransient("Server timeout", status_code=504)
    err_fatal = AIFatal("Unauthorized API Key", status_code=401)
    err_invalid = AIInvalidOutput("Cannot parse JSON", raw_text="{bad_json}")

    for err in [err_rate, err_transient, err_fatal, err_invalid]:
        assert isinstance(err, AIError)
        assert isinstance(err, Exception)

    # Bắt được qua AIError
    with pytest.raises(AIError) as exc_info:
        raise err_rate
    assert exc_info.value.status_code == 429


def test_exception_attributes() -> None:
    """Kiểm tra các thuộc tính chi tiết trên từng loại lỗi."""
    # AIRateLimited
    rate_err = AIRateLimited("Too many requests", retry_after=30.5, key_hint="key-2", status_code=429)
    assert rate_err.retry_after == 30.5
    assert rate_err.key_hint == "key-2"
    assert rate_err.status_code == 429
    assert str(rate_err) == "Too many requests"

    # AITransient
    trans_err = AITransient("Service Unavailable", status_code=503)
    assert trans_err.status_code == 503

    # AIFatal
    fatal_err = AIFatal("Invalid argument", status_code=400)
    assert fatal_err.status_code == 400

    # AIInvalidOutput
    val_err = ValueError("Missing field")
    inv_err = AIInvalidOutput("Validation failed", raw_text='{"a": 1}', validation_error=val_err)
    assert inv_err.raw_text == '{"a": 1}'
    assert inv_err.validation_error is val_err


class _ValidProvider:
    @property
    def model_name(self) -> str:
        return "gemini-3.8-flash"

    async def generate(
        self,
        prompt: str,
        schema: type[BaseModel],
        *,
        system_instruction: str | None = None,
        temperature: float | None = None,
    ) -> BaseModel:
        return schema.model_validate({"answer": f"Echo: {prompt}"})


class _MissingGenerateProvider:
    @property
    def model_name(self) -> str:
        return "gemini-3.8-flash"


class _MissingModelNameProvider:
    async def generate(
        self,
        prompt: str,
        schema: type[BaseModel],
        *,
        system_instruction: str | None = None,
        temperature: float | None = None,
    ) -> BaseModel:
        return schema()


def test_llm_provider_protocol_runtime_check() -> None:
    """Protocol LLMProvider có runtime_checkable và phân biệt đúng class cài đặt."""
    valid = _ValidProvider()
    assert isinstance(valid, LLMProvider)

    missing_gen = _MissingGenerateProvider()
    assert not isinstance(missing_gen, LLMProvider)

    missing_model = _MissingModelNameProvider()
    assert not isinstance(missing_model, LLMProvider)


class _DummyEchoSchema(BaseModel):
    answer: str


@pytest.mark.asyncio
async def test_valid_provider_generate() -> None:
    """Provider tuân thủ protocol sinh được Pydantic model hợp lệ."""
    provider = _ValidProvider()
    res = await provider.generate("hello world", _DummyEchoSchema)
    assert isinstance(res, _DummyEchoSchema)
    assert res.answer == "Echo: hello world"
