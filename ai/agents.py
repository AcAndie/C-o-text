# ai/agents.py
"""
ai/agents.py — Toàn bộ hàm gọi Gemini API.

THAY ĐỔI (v2):
  - Dùng PromptTemplates thay vì hardcode f-string → dễ tinh chỉnh prompt.
  - Thêm _generate_structured() dùng Gemini response_schema để ép output JSON
    → loại bỏ JSONDecodeError do AI sinh text thừa.
  - _generate_with_retry() giữ nguyên cho các agent không cần strict schema.
  - _parse_json_response() vẫn giữ làm safety net.

Retry policy (không đổi):
  - acquire() gọi MỘT LẦN duy nhất trước vòng lặp retry.
  - Tối đa 3 lần attempt, backoff 30s / 60s khi gặp 429.
"""
from __future__ import annotations

import asyncio
import json
import re
from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from config import GEMINI_MODEL, RE_CHAP_HINT, RE_NEXT_PREV
from ai.client  import ai_client, AIRateLimiter
from ai.prompts import PromptTemplates


# ── Retry helpers ─────────────────────────────────────────────────────────────

_MAX_RETRIES   = 3
_RETRY_BACKOFF = [30, 60]


def _is_rate_limit_error(e: Exception) -> bool:
    code = getattr(e, "status_code", None) or getattr(e, "code", None)
    if code == 429:
        return True
    msg = str(e).lower()
    return "429" in msg or "quota" in msg or "resource_exhausted" in msg


async def _generate_with_retry(prompt: str, ai_limiter: AIRateLimiter) -> str:
    """Gọi Gemini text generation với retry tự động khi gặp 429."""
    await ai_limiter.acquire()

    for attempt in range(_MAX_RETRIES):
        try:
            resp = await ai_client.aio.models.generate_content(
                model    = GEMINI_MODEL,
                contents = prompt,
            )
            return resp.text

        except Exception as e:
            is_last = attempt >= _MAX_RETRIES - 1
            if _is_rate_limit_error(e) and not is_last:
                wait = _RETRY_BACKOFF[attempt]
                print(
                    f"  [AI] ⚠ 429 Rate limit (lần {attempt + 1}/{_MAX_RETRIES}),"
                    f" thử lại sau {wait}s...",
                    flush=True,
                )
                await asyncio.sleep(wait)
            else:
                raise

    raise RuntimeError("_generate_with_retry: hết retry không mong đợi")


async def _generate_structured(
    prompt: str,
    ai_limiter: AIRateLimiter,
    response_schema: dict[str, Any],
) -> dict | list | None:
    """
    Gọi Gemini với response_schema để ép output JSON chính xác.

    Dùng Gemini Structured Output (JSON mode) — AI BẮT BUỘC trả về
    đúng schema, không thể thêm text thừa hay markdown fence.

    Ưu điểm so với _generate_with_retry + _parse_json_response:
      - Loại bỏ hoàn toàn JSONDecodeError
      - Không cần parse/strip markdown fence
      - Schema validate ngay tại API level

    Fallback: nếu model không hỗ trợ (gemini-1.0, edge case), tự động
    dùng _generate_with_retry + _parse_json_response.

    Args:
        response_schema: JSON Schema dict (OpenAPI subset mà Gemini hỗ trợ).
    """
    await ai_limiter.acquire()

    for attempt in range(_MAX_RETRIES):
        try:
            from google.genai import types as genai_types

            config = genai_types.GenerateContentConfig(
                response_mime_type = "application/json",
                response_schema    = response_schema,
            )
            resp = await ai_client.aio.models.generate_content(
                model    = GEMINI_MODEL,
                contents = prompt,
                config   = config,
            )
            return json.loads(resp.text)

        except json.JSONDecodeError:
            # API trả về JSON không hợp lệ (hiếm) — fallback parse thủ công
            return _parse_json_response(resp.text if resp else "")

        except Exception as e:
            is_last = attempt >= _MAX_RETRIES - 1

            # Nếu lỗi là "response_schema not supported" → fallback text mode
            err_msg = str(e).lower()
            if "response_schema" in err_msg or "mime_type" in err_msg:
                try:
                    text = await _generate_with_retry(prompt, ai_limiter)
                    return _parse_json_response(text)
                except Exception:
                    return None

            if _is_rate_limit_error(e) and not is_last:
                wait = _RETRY_BACKOFF[attempt]
                print(
                    f"  [AI] ⚠ 429 Rate limit (lần {attempt + 1}/{_MAX_RETRIES}),"
                    f" thử lại sau {wait}s...",
                    flush=True,
                )
                await asyncio.sleep(wait)
            else:
                raise

    return None


def _parse_json_response(text: str) -> dict | list | None:
    """Parse JSON từ response AI, chịu được ```json ... ``` fence. Safety net."""
    if not text:
        return None
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$",          "", text)
    # Tìm JSON object/array đầu tiên trong text (AI đôi khi thêm preamble)
    match = re.search(r"(\{[\s\S]*\}|\[[\s\S]*\])", text)
    if match:
        text = match.group(1)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


# ── Sync HTML helpers (chạy trong thread pool) ────────────────────────────────

def _sync_get_profile_snippet(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    return str(soup)[:8000]


def _sync_get_chapter_links(html: str, base_url: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    return [
        urljoin(base_url, a["href"])
        for a in soup.find_all("a", href=True)
        if RE_CHAP_HINT.search(a["href"])
    ]


def _sync_get_nav_hints_and_snippet(html: str, base_url: str) -> tuple[str, str]:
    soup = BeautifulSoup(html, "html.parser")
    nav_hints = [
        f"{a.get_text(strip=True)!r} → {urljoin(base_url, a['href'])}"
        for a in soup.find_all("a", href=True)
        if RE_NEXT_PREV.search(a.get_text(strip=True))
    ]
    hint_block = "\n".join(nav_hints[:10]) if nav_hints else "(không có)"
    snippet    = str(soup)[:6000]
    return hint_block, snippet


# ── JSON Schemas cho Structured Output ───────────────────────────────────────

_SCHEMA_PROFILE = {
    "type": "object",
    "properties": {
        "next_selector":    {"type": "string", "nullable": True},
        "title_selector":   {"type": "string", "nullable": True},
        "content_selector": {"type": "string", "nullable": True},
    },
}

_SCHEMA_STORY_ID = {
    "type": "object",
    "properties": {
        "story_id":       {"type": "string"},
        "story_id_regex": {"type": "string"},
    },
    "required": ["story_id", "story_id_regex"],
}

_SCHEMA_SAME_STORY = {
    "type": "object",
    "properties": {
        "same_story": {"type": "boolean"},
        "reason":     {"type": "string"},
    },
    "required": ["same_story"],
}

_SCHEMA_FIRST_CHAPTER = {
    "type": "object",
    "properties": {
        "first_chapter_url": {"type": "string", "nullable": True},
    },
}

_SCHEMA_CLASSIFY = {
    "type": "object",
    "properties": {
        "page_type":         {"type": "string", "enum": ["chapter", "index", "other"]},
        "next_url":          {"type": "string", "nullable": True},
        "first_chapter_url": {"type": "string", "nullable": True},
    },
    "required": ["page_type"],
}

_SCHEMA_TITLE = {
    "type": "object",
    "properties": {
        "valid": {"type": "boolean"},
        "title": {"type": "string", "nullable": True},
    },
    "required": ["valid"],
}

_SCHEMA_ADS = {
    "type": "object",
    "properties": {
        "found":         {"type": "boolean"},
        "keywords":      {"type": "array", "items": {"type": "string"}},
        "patterns":      {"type": "array", "items": {"type": "string"}},
        "example_lines": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["found"],
}


# ── Agent functions ───────────────────────────────────────────────────────────

async def ask_ai_build_profile(
    html: str,
    url: str,
    ai_limiter: AIRateLimiter,
) -> dict | None:
    """Phân tích HTML để xây dựng CSS selector profile cho site mới."""
    snippet = await asyncio.to_thread(_sync_get_profile_snippet, html)
    prompt  = PromptTemplates.build_profile(snippet, url)

    try:
        result = await _generate_structured(prompt, ai_limiter, _SCHEMA_PROFILE)
        if isinstance(result, dict):
            return result
    except Exception as e:
        print(f"  [AI] ⚠ ask_ai_build_profile thất bại: {e}", flush=True)
    return None


async def ask_ai_for_story_id(
    urls: list[str],
    ai_limiter: AIRateLimiter,
) -> dict | None:
    """Học pattern story_id từ danh sách URL đã cào."""
    if len(urls) < 3:
        return None

    prompt = PromptTemplates.story_id("\n".join(urls[:20]))

    try:
        result = await _generate_structured(prompt, ai_limiter, _SCHEMA_STORY_ID)
        if isinstance(result, dict) and result.get("story_id"):
            return result
    except Exception as e:
        print(f"  [AI] ⚠ ask_ai_for_story_id thất bại: {e}", flush=True)
    return None


async def ask_ai_confirm_same_story(
    title1: str,
    url1: str,
    title2: str,
    url2: str,
    ai_limiter: AIRateLimiter,
) -> bool:
    """So sánh title + URL để phát hiện khi nút Next dẫn sang truyện khác."""
    prompt = PromptTemplates.confirm_same_story(title1, url1, title2, url2)

    try:
        result = await _generate_structured(prompt, ai_limiter, _SCHEMA_SAME_STORY)
        if isinstance(result, dict):
            return bool(result.get("same_story", True))
    except Exception as e:
        print(f"  [AI] ⚠ ask_ai_confirm_same_story thất bại: {e}", flush=True)
    return True


async def ai_find_first_chapter_url(
    html: str,
    base_url: str,
    ai_limiter: AIRateLimiter,
) -> str | None:
    """Tìm URL chương đầu tiên từ trang mục lục / trang truyện."""
    links = await asyncio.to_thread(_sync_get_chapter_links, html, base_url)

    if not links:
        return None
    if len(links) == 1:
        return links[0]

    candidates = "\n".join(links[:15])
    prompt     = PromptTemplates.find_first_chapter(candidates, base_url)

    try:
        result = await _generate_structured(prompt, ai_limiter, _SCHEMA_FIRST_CHAPTER)
        if isinstance(result, dict) and result.get("first_chapter_url"):
            return result["first_chapter_url"]
    except Exception as e:
        print(f"  [AI] ⚠ ai_find_first_chapter_url thất bại: {e}", flush=True)

    return links[0]


async def ai_classify_and_find(
    html: str,
    base_url: str,
    ai_limiter: AIRateLimiter,
) -> dict | None:
    """Phân loại trang và tìm URL next chapter / first chapter."""
    hint_block, snippet = await asyncio.to_thread(
        _sync_get_nav_hints_and_snippet, html, base_url
    )
    prompt = PromptTemplates.classify_and_find(hint_block, snippet, base_url)

    try:
        result = await _generate_structured(prompt, ai_limiter, _SCHEMA_CLASSIFY)
        if isinstance(result, dict):
            return result
    except Exception as e:
        print(f"  [AI] ⚠ ai_classify_and_find thất bại: {e}", flush=True)
    return None


async def ai_validate_title(
    candidate: str,
    chapter_url: str,
    content_snippet: str,
    ai_limiter: AIRateLimiter,
) -> str | None:
    """Xác nhận / làm sạch tiêu đề chương khi TitleExtractor cho kết quả hòa."""
    prompt = PromptTemplates.validate_title(candidate, chapter_url, content_snippet)

    try:
        result = await _generate_structured(prompt, ai_limiter, _SCHEMA_TITLE)
        if isinstance(result, dict) and result.get("valid"):
            return result.get("title") or candidate
    except Exception as e:
        print(f"  [AI] ⚠ ai_validate_title thất bại: {e}", flush=True)
    return None


async def ai_detect_ads_content(
    text: str,
    ai_limiter: AIRateLimiter,
) -> str | None:
    """
    Xác nhận danh sách câu nghi ngờ có phải ads/watermark không.

    Trả về raw JSON string (caller tự parse qua update_from_ai_result).
    Dùng _generate_with_retry thay vì structured vì AdsFilter cần raw string.
    """
    prompt = PromptTemplates.detect_ads(text)

    try:
        result = await _generate_structured(prompt, ai_limiter, _SCHEMA_ADS)
        if result is not None:
            return json.dumps(result)
    except Exception as e:
        print(f"  [AI] ⚠ ai_detect_ads_content thất bại: {e}", flush=True)
    return None