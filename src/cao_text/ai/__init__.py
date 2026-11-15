"""Lớp AI: LLMProvider protocol, GeminiProvider, schemas, prompts và DOM skeleton."""
from __future__ import annotations

from cao_text.ai.gemini import (
    AIRateLimiter,
    ApiKeyPool,
    GeminiProvider,
    classify_api_error,
)
from cao_text.ai.prompts import (
    prompt_analyze_site,
    prompt_classify_page,
    prompt_epub_rules,
    prompt_extract_content,
    prompt_repair_site,
    prompt_txt_pattern,
    prompt_verify_ads_lines,
)
from cao_text.ai.provider import (
    AIError,
    AIFatal,
    AIInvalidOutput,
    AIRateLimited,
    AITransient,
    LLMProvider,
)
from cao_text.ai.schemas import (
    EpubChapterItem,
    EpubRulesOutput,
    ExtractedContentOutput,
    PageClassificationOutput,
    SiteAnalysisOutput,
    SiteRepairOutput,
    TxtPatternOutput,
    VerifyAdsOutput,
)
from cao_text.ai.skeleton import compress_dom_to_skeleton

__all__ = [
    "AIError",
    "AIFatal",
    "AIInvalidOutput",
    "AIRateLimited",
    "AIRateLimiter",
    "AITransient",
    "ApiKeyPool",
    "EpubChapterItem",
    "EpubRulesOutput",
    "ExtractedContentOutput",
    "GeminiProvider",
    "LLMProvider",
    "PageClassificationOutput",
    "SiteAnalysisOutput",
    "SiteRepairOutput",
    "TxtPatternOutput",
    "VerifyAdsOutput",
    "classify_api_error",
    "compress_dom_to_skeleton",
    "prompt_analyze_site",
    "prompt_classify_page",
    "prompt_epub_rules",
    "prompt_extract_content",
    "prompt_repair_site",
    "prompt_txt_pattern",
    "prompt_verify_ads_lines",
]
