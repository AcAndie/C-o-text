"""Protocol LLMProvider và hệ thống lỗi chuẩn hóa cho các dịch vụ mô hình ngôn ngữ lớn (LLMs)."""
from __future__ import annotations

from typing import Protocol, TypeVar, runtime_checkable

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class AIError(Exception):
    """Lớp cha cơ sở cho tất cả các ngoại lệ liên quan tới tầng AI."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class AIRateLimited(AIError):
    """Lỗi khi bị giới hạn tốc độ gọi API (HTTP 429 hoặc 503 ResourceExhausted).

    Cho phép provider thực hiện cooldown, xoay key trong key pool hoặc áp dụng backoff.
    """

    def __init__(
        self,
        message: str,
        *,
        retry_after: float | None = None,
        key_hint: str | None = None,
        status_code: int = 429,
    ) -> None:
        super().__init__(message, status_code=status_code)
        self.retry_after = retry_after
        self.key_hint = key_hint


class AITransient(AIError):
    """Lỗi tạm thời từ mạng hoặc máy chủ có thể thử lại (5xx, timeout, ngắt kết nối)."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message, status_code=status_code)


class AIFatal(AIError):
    """Lỗi nghiêm trọng không thể khắc phục bằng cách thử lại (400, 401/403, Model not found)."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message, status_code=status_code)


class AIInvalidOutput(AIError):
    """Lỗi khi output từ LLM không khớp với cấu trúc Pydantic schema hoặc không thể phân tích (parse)."""

    def __init__(
        self,
        message: str,
        *,
        raw_text: str | None = None,
        validation_error: Exception | None = None,
        status_code: int | None = None,
    ) -> None:
        super().__init__(message, status_code=status_code)
        self.raw_text = raw_text
        self.validation_error = validation_error


@runtime_checkable
class LLMProvider(Protocol):
    """Protocol chuẩn hóa cho LLM Provider (GeminiProvider, FakeProvider, v.v.).

    Đảm bảo tính độc lập: các tầng nghiệp vụ (learn, web, files) chỉ tương tác qua
    protocol này mà không phụ thuộc trực tiếp vào SDK cụ thể.
    """

    @property
    def model_name(self) -> str:
        """Tên model chính mà provider đang cấu hình để sử dụng."""
        ...

    async def generate(
        self,
        prompt: str,
        schema: type[T],
        *,
        system_instruction: str | None = None,
        temperature: float | None = None,
    ) -> T:
        """Gửi prompt và yêu cầu phản hồi có cấu trúc tuân thủ Pydantic schema `schema`.

        Args:
            prompt: Nội dung prompt gửi tới mô hình.
            schema: Lớp Pydantic Model định nghĩa cấu trúc dữ liệu mong đợi.
            system_instruction: Chỉ dẫn hệ thống (tùy chọn).
            temperature: Nhiệt độ sinh văn bản (tùy chọn).

        Returns:
            Instance của `schema` (kiểu `T`) đã được parse và validate thành công.

        Raises:
            AIRateLimited: Khi bị giới hạn tần suất gọi API (429/503).
            AITransient: Khi gặp lỗi mạng / server tạm thời (5xx, timeout, connect drop).
            AIFatal: Khi gặp lỗi nghiêm trọng (sai key, sai cấu hình, model bị cấm).
            AIInvalidOutput: Khi phản hồi không hợp lệ hoặc không parse được theo schema.
            AIError: Lớp cha chung của mọi ngoại lệ AI.
        """
        ...
