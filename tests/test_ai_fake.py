from __future__ import annotations

import pytest
from pydantic import BaseModel

from cao_text.ai.fake import FakeProvider
from cao_text.ai.provider import AIRateLimited, LLMProvider
from cao_text.ai.schemas import (
    EpubRulesOutput,
    ExtractedContentOutput,
    PageClassificationOutput,
    SiteAnalysisOutput,
    SiteRepairOutput,
    TxtPatternOutput,
    VerifyAdsOutput,
)


@pytest.mark.asyncio
async def test_fake_provider_implements_protocol() -> None:
    """FakeProvider tuân thủ LLMProvider protocol."""
    fake = FakeProvider(model_name="mock-gemini")
    assert isinstance(fake, LLMProvider)
    assert fake.model_name == "mock-gemini"
    assert fake.call_count == 0


@pytest.mark.asyncio
async def test_fake_provider_default_instances_all_7_schemas() -> None:
    """FakeProvider tự động sinh instance mặc định hợp lệ cho toàn bộ 7 schemas chuẩn."""
    fake = FakeProvider()

    res_analysis = await fake.generate("prompt", SiteAnalysisOutput)
    assert isinstance(res_analysis, SiteAnalysisOutput)
    assert res_analysis.content_selector == "div.chapter-content"

    res_repair = await fake.generate("prompt", SiteRepairOutput)
    assert isinstance(res_repair, SiteRepairOutput)
    assert "repair" in res_repair.reasoning

    res_class = await fake.generate("prompt", PageClassificationOutput)
    assert isinstance(res_class, PageClassificationOutput)
    assert res_class.page_type == "chapter"

    res_extract = await fake.generate("prompt", ExtractedContentOutput)
    assert isinstance(res_extract, ExtractedContentOutput)
    assert "Đoạn văn" in res_extract.content_text

    res_ads = await fake.generate("prompt", VerifyAdsOutput)
    assert isinstance(res_ads, VerifyAdsOutput)
    assert len(res_ads.ad_lines) == 1

    res_txt = await fake.generate("prompt", TxtPatternOutput)
    assert isinstance(res_txt, TxtPatternOutput)
    assert res_txt.chapter_regex.startswith("^")

    res_epub = await fake.generate("prompt", EpubRulesOutput)
    assert isinstance(res_epub, EpubRulesOutput)
    assert len(res_epub.chapters) == 1

    assert fake.call_count == 7


@pytest.mark.asyncio
async def test_fake_provider_configured_response_by_schema_or_name() -> None:
    """FakeProvider trả về kết quả cấu hình sẵn theo Schema Class hoặc Tên Schema."""
    custom_analysis = SiteAnalysisOutput(
        content_selector="article.entry-content",
        title_selector="h2.title",
        confidence=0.99,
    )
    fake = FakeProvider(
        responses={
            SiteAnalysisOutput: custom_analysis,
            "TxtPatternOutput": {"chapter_regex": r"^Hồi\s+\d+", "example_matches": ["Hồi 1"]},
        }
    )

    out1 = await fake.generate("prompt 1", SiteAnalysisOutput)
    assert out1.content_selector == "article.entry-content"
    assert out1.confidence == 0.99

    out2 = await fake.generate("prompt 2", TxtPatternOutput)
    assert out2.chapter_regex == r"^Hồi\s+\d+"
    assert out2.example_matches == ["Hồi 1"]


@pytest.mark.asyncio
async def test_fake_provider_queue_fifo() -> None:
    """FakeProvider trả về các phản hồi theo hàng đợi tuần tự FIFO."""
    fake = FakeProvider()
    fake.enqueue_response({"page_type": "index", "first_chapter_url": "/c1"})
    fake.enqueue_response({"page_type": "chapter", "next_chapter_url": "/c2"})

    first = await fake.generate("check index", PageClassificationOutput)
    assert first.page_type == "index"
    assert first.first_chapter_url == "/c1"

    second = await fake.generate("check chapter", PageClassificationOutput)
    assert second.page_type == "chapter"
    assert second.next_chapter_url == "/c2"


@pytest.mark.asyncio
async def test_fake_provider_error_simulation() -> None:
    """FakeProvider có thể giả lập ngoại lệ hoặc chuỗi lỗi tuần tự."""
    # 1. Error to raise cố định
    fake_err = FakeProvider(error_to_raise=AIRateLimited("Rate limit hit"))
    with pytest.raises(AIRateLimited):
        await fake_err.generate("prompt", SiteAnalysisOutput)

    # 2. Error sequence: lần 1 lỗi, lần 2 thành công
    fake_seq = FakeProvider(
        error_sequence=[AIRateLimited("429 first time"), None],
        responses={SiteAnalysisOutput: {"content_selector": ".ok"}},
    )

    with pytest.raises(AIRateLimited):
        await fake_seq.generate("call 1", SiteAnalysisOutput)

    # Lần 2 thành công
    ok_res = await fake_seq.generate("call 2", SiteAnalysisOutput)
    assert ok_res.content_selector == ".ok"


class _CustomSample(BaseModel):
    echo: str


@pytest.mark.asyncio
async def test_fake_provider_custom_handler_and_call_history() -> None:
    """Custom handler động và lưu trữ lịch sử cuộc gọi."""

    def handler(prompt: str, schema: type[BaseModel]) -> dict[str, str]:
        return {"echo": f"Handled: {prompt}"}

    fake = FakeProvider(custom_handler=handler)
    res = await fake.generate(
        "Xin chào",
        _CustomSample,
        system_instruction="sys instruction",
        temperature=0.2,
    )
    assert res.echo == "Handled: Xin chào"

    assert fake.call_count == 1
    call = fake.calls[0]
    assert call.prompt == "Xin chào"
    assert call.schema is _CustomSample
    assert call.system_instruction == "sys instruction"
    assert call.temperature == 0.2
