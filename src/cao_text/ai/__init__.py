"""Lớp AI: LLMProvider protocol, GeminiProvider, schemas, prompts và DOM skeleton."""
from __future__ import annotations

from cao_text.ai.gemini import (
    AIRateLimiter,
    ApiKeyPool,
    GeminiProvider,
    classify_api_error,
)
from cao_text.ai.provider import (
    AIError,
    AIFatal,
    AIInvalidOutput,
    AIRateLimited,
    AITransient,
    LLMProvider,
)

__all__ = [
    "AIError",
    "AIFatal",
    "AIInvalidOutput",
    "AIRateLimited",
    "AIRateLimiter",
    "AITransient",
    "ApiKeyPool",
    "GeminiProvider",
    "LLMProvider",
    "classify_api_error",
]
