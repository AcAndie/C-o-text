"""FakeProvider: LLMProvider giả lập phục vụ kiểm thử offline và chạy mô phỏng không tốn API quota."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, TypeVar

from pydantic import BaseModel

from cao_text.ai.provider import LLMProvider
from cao_text.ai.schemas import (
    EpubRulesOutput,
    ExtractedContentOutput,
    PageClassificationOutput,
    SiteAnalysisOutput,
    SiteRepairOutput,
    TxtPatternOutput,
    VerifyAdsOutput,
)

T = TypeVar("T", bound=BaseModel)


@dataclass
class FakeCall:
    """Ghi nhận chi tiết tham số của một lần gọi generate()."""

    prompt: str
    schema: type[BaseModel]
    system_instruction: str | None = None
    temperature: float | None = None


class FakeProvider(LLMProvider):
    """LLMProvider giả lập cho test offline, trả về output định sẵn hoặc mặc định theo schema."""

    def __init__(
        self,
        *,
        responses: dict[type[BaseModel] | str, Any] | None = None,
        queue: list[Any] | None = None,
        error_to_raise: Exception | None = None,
        error_sequence: list[Exception | None] | None = None,
        custom_handler: Callable[[str, type[BaseModel]], Any] | None = None,
        model_name: str = "fake-model",
    ) -> None:
        self._responses = dict(responses or {})
        self._queue = list(queue or [])
        self._error_to_raise = error_to_raise
        self._error_sequence = list(error_sequence or [])
        self._custom_handler = custom_handler
        self._model_name = model_name
        self.calls: list[FakeCall] = []

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def call_count(self) -> int:
        return len(self.calls)

    def set_response(self, schema: type[BaseModel] | str, response: Any) -> None:
        """Đăng ký phản hồi định sẵn cho một schema."""
        self._responses[schema] = response

    def enqueue_response(self, response: Any) -> None:
        """Thêm một phản hồi vào hàng đợi tuần tự (FIFO)."""
        self._queue.append(response)

    async def generate(
        self,
        prompt: str,
        schema: type[T],
        *,
        system_instruction: str | None = None,
        temperature: float | None = None,
    ) -> T:
        call = FakeCall(
            prompt=prompt,
            schema=schema,
            system_instruction=system_instruction,
            temperature=temperature,
        )
        self.calls.append(call)

        # 1. Kiểm tra chuỗi lỗi giả lập
        if self._error_sequence:
            err = self._error_sequence.pop(0)
            if err is not None:
                raise err

        if self._error_to_raise is not None:
            raise self._error_to_raise

        # 2. Kiểm tra hàng đợi FIFO
        if self._queue:
            item = self._queue.pop(0)
            if isinstance(item, Exception):
                raise item
            return self._validate_as_schema(item, schema)

        # 3. Kiểm tra custom handler
        if self._custom_handler is not None:
            res = self._custom_handler(prompt, schema)
            if isinstance(res, Exception):
                raise res
            return self._validate_as_schema(res, schema)

        # 4. Kiểm tra phản hồi theo schema class hoặc tên schema
        schema_key = schema
        schema_name = schema.__name__
        if schema_key in self._responses:
            return self._validate_as_schema(self._responses[schema_key], schema)
        if schema_name in self._responses:
            return self._validate_as_schema(self._responses[schema_name], schema)

        # 5. Phản hồi mặc định thông minh theo loại schema
        return self._make_default_schema_instance(schema)

    def _validate_as_schema(self, data: Any, schema: type[T]) -> T:
        if isinstance(data, schema):
            return data
        if isinstance(data, dict):
            return schema.model_validate(data)
        if isinstance(data, str):
            return schema.model_validate_json(data)
        raise ValueError(f"Không thể chuyển đổi {type(data)} thành {schema}")

    def _make_default_schema_instance(self, schema: type[T]) -> T:
        """Sinh instance mặc định hợp lệ cho các schema chuẩn của hệ thống."""
        if issubclass(schema, SiteAnalysisOutput):
            return schema(
                content_selector="div.chapter-content",
                title_selector="h1.chapter-title",
                next_selector="a.next-chapter",
                nav_type="selector",
                remove_selectors=[".ads", ".comment-section"],
                confidence=0.9,
            )
        if issubclass(schema, SiteRepairOutput):
            return schema(
                content_selector="div.chapter-content",
                title_selector="h1.chapter-title",
                next_selector="a.next-chapter",
                reasoning="Fake repair response",
            )
        if issubclass(schema, PageClassificationOutput):
            return schema(
                page_type="chapter",
                story_title="Fake Story",
                chapter_title="Chapter 1",
                next_chapter_url="https://fake.site/c2",
                confidence=0.9,
            )
        if issubclass(schema, ExtractedContentOutput):
            return schema(
                title="Chapter 1",
                content_text="Đoạn văn 1.\n\nĐoạn văn 2.",
                next_url="https://fake.site/c2",
            )
        if issubclass(schema, VerifyAdsOutput):
            return schema(
                ad_lines=["Quảng cáo giả"],
                safe_lines=["Lời thoại giả"],
                reasoning="Fake verify ads",
            )
        if issubclass(schema, TxtPatternOutput):
            return schema(
                pattern_id="vn_chuong_so",
                language="vi",
                chapter_regex=r"^Chương\s+\d+",
                example_matches=["Chương 1", "Chương 2"],
                confidence=0.9,
            )
        if issubclass(schema, EpubRulesOutput):
            return schema(
                story_title="Fake Book",
                chapter_title_regex=r"^(?:Chapter|Chương)\s+\d+",
                divider_title_regex=r"^Part\s+\d+",
                front_matter_keywords=["cover", "toc"],
                front_matter_hrefs=["cover.xhtml"],
                back_matter_hrefs=[],
                merge_unnamed_into_previous=True,
                confidence=0.9,
            )

        try:
            return schema()
        except Exception as e:
            raise ValueError(
                f"FakeProvider không có sẵn phản hồi định trước cho schema {schema.__name__}. "
                f"Vui lòng cung cấp qua responses={{...}} hoặc queue=[...]."
            ) from e
