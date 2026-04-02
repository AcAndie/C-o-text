# ai/agents.py
"""
ai/agents.py — Toàn bộ hàm gọi Gemini API.

CHANGES (v3):
  - ask_ai_calibration_review(): Agent mới — phân tích calibration report
    (issues từ N chương probe) và trả về suggested profile fixes.
  - _SCHEMA_CALIBRATION_FIX: JSON schema tương ứng.

CHANGES (v2):
  - _SCHEMA_PROFILE: 8 field mới (nav_type, requires_playwright,
    chapter_url_regex, story_id_pattern, domain_watermarks, ai_notes).
  - ask_ai_build_profile(): Trả về SiteProfileDict đầy đủ thay vì chỉ 3 fields.
  - ai_classify_and_find(): Nhận thêm domain_context (ai_notes từ profile).

FIXES (giữ nguyên từ v1):
  - BUG-1: CancelledError propagate trong _generate_with_retry và _generate_structured.
  - BUG-4: _is_rate_limit_error nhận diện cả 503 UNAVAILABLE.
  - BUG-5: _fmt_err dùng repr() fallback khi str() rỗng.
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
    if code in (429, 503):
        return True
    msg = str(e).lower()
    return (
        "429" in msg or "503" in msg or "quota" in msg
        or "resource_exhausted" in msg or "unavailable" in msg
        or "service unavailable" in msg
    )


def _fmt_err(e: Exception) -> str:
    return str(e).strip() or repr(e)


async def _generate_with_retry(prompt: str, ai_limiter: AIRateLimiter) -> str:
    await ai_limiter.acquire()
    for attempt in range(_MAX_RETRIES):
        try:
            resp = await ai_client.aio.models.generate_content(
                model=GEMINI_MODEL, contents=prompt,
            )
            return resp.text
        except asyncio.CancelledError:
            raise
        except Exception as e:
            is_last = attempt >= _MAX_RETRIES - 1
            if _is_rate_limit_error(e) and not is_last:
                wait = _RETRY_BACKOFF[attempt]
                print(f"  [AI] ⚠ Rate limit/503 (lần {attempt+1}/{_MAX_RETRIES}), thử lại sau {wait}s...", flush=True)
                await asyncio.sleep(wait)
            else:
                raise
    raise RuntimeError("_generate_with_retry: hết retry không mong đợi")


async def _generate_structured(
    prompt: str,
    ai_limiter: AIRateLimiter,
    response_schema: dict[str, Any],
) -> dict | list | None:
    await ai_limiter.acquire()
    for attempt in range(_MAX_RETRIES):
        try:
            from google.genai import types as genai_types
            config = genai_types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=response_schema,
            )
            resp = await ai_client.aio.models.generate_content(
                model=GEMINI_MODEL, contents=prompt, config=config,
            )
            return json.loads(resp.text)
        except json.JSONDecodeError:
            return _parse_json_response(resp.text if resp else "")
        except asyncio.CancelledError:
            raise
        except Exception as e:
            is_last = attempt >= _MAX_RETRIES - 1
            err_msg = str(e).lower()
            if "response_schema" in err_msg or "mime_type" in err_msg:
                try:
                    text = await _generate_with_retry(prompt, ai_limiter)
                    return _parse_json_response(text)
                except Exception:
                    return None
            if _is_rate_limit_error(e) and not is_last:
                wait = _RETRY_BACKOFF[attempt]
                print(f"  [AI] ⚠ Rate limit/503 (lần {attempt+1}/{_MAX_RETRIES}), thử lại sau {wait}s...", flush=True)
                await asyncio.sleep(wait)
            else:
                raise
    return None


def _parse_json_response(text: str) -> dict | list | None:
    if not text:
        return None
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    match = re.search(r"(\{[\s\S]*\}|\[[\s\S]*\])", text)
    if match:
        text = match.group(1)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


# ── Sync HTML helpers ─────────────────────────────────────────────────────────

def _sync_get_profile_snippet(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    return str(soup)[:8000]


_RE_CHAPTER_LISTING = re.compile(
    r"/(chapters|chapter-list|table-of-contents|toc|contents|chapter-index)[/?#]?$",
    re.IGNORECASE,
)

_RE_CHAP_HINT_STRICT = re.compile(
    r"(chapter|chuong|chap|/c/|/ch/|episode|ep|phần|tập)[_\-]?\d+"
    r"|/s/\d+/\d+",
    re.IGNORECASE,
)


def _sync_get_chapter_links(html: str, base_url: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    seen: set[str] = set()
    links: list[str] = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if _RE_CHAPTER_LISTING.search(href):
            continue
        if not _RE_CHAP_HINT_STRICT.search(href):
            continue
        full_url = urljoin(base_url, href)
        if full_url not in seen:
            seen.add(full_url)
            links.append(full_url)
    return links


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


# ── JSON Schemas ──────────────────────────────────────────────────────────────

_SCHEMA_PROFILE = {
    "type": "object",
    "properties": {
        "next_selector":      {"type": "string",  "nullable": True},
        "title_selector":     {"type": "string",  "nullable": True},
        "content_selector":   {"type": "string",  "nullable": True},
        "nav_type":           {"type": "string",  "nullable": True},
        "requires_playwright": {"type": "boolean"},
        "chapter_url_regex":  {"type": "string",  "nullable": True},
        "story_id_pattern":   {"type": "string",  "nullable": True},
        "domain_watermarks":  {"type": "array",   "items": {"type": "string"}},
        "ai_notes":           {"type": "string",  "nullable": True},
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

_SCHEMA_REFINE = {
    "type": "object",
    "properties": {
        "content_selector":   {"type": "string",  "nullable": True},
        "content_confidence": {"type": "number"},
        "title_selector":     {"type": "string",  "nullable": True},
        "title_confidence":   {"type": "number"},
        "next_selector":      {"type": "string",  "nullable": True},
        "next_confidence":    {"type": "number"},
        "notes":              {"type": "string",  "nullable": True},
    },
    "required": ["content_confidence", "title_confidence", "next_confidence"],
}

_SCHEMA_CALIBRATION_FIX = {
    "type": "object",
    "properties": {
        "content_selector":  {"type": "string",  "nullable": True},
        "next_selector":     {"type": "string",  "nullable": True},
        "title_selector":    {"type": "string",  "nullable": True},
        "nav_type":          {"type": "string",  "nullable": True},
        "has_nav_edges":     {"type": "boolean"},
        "domain_watermarks": {"type": "array", "items": {"type": "string"}},
        "notes":             {"type": "string",  "nullable": True},
    },
}


# ── Agent functions ───────────────────────────────────────────────────────────

async def ask_ai_build_profile(
    html: str,
    url: str,
    ai_limiter: AIRateLimiter,
) -> dict | None:
    """
    Phân tích trang và trả về SiteProfileDict đầy đủ (11 fields).

    ENHANCED (v2): Profile giờ bao gồm nav_type, requires_playwright,
    chapter_url_regex, story_id_pattern, domain_watermarks, ai_notes.
    Caller (scraper.py) dùng merge_profile() để tích hợp vào profile cũ.
    """
    snippet = await asyncio.to_thread(_sync_get_profile_snippet, html)
    prompt  = PromptTemplates.build_profile(snippet, url)
    try:
        result = await _generate_structured(prompt, ai_limiter, _SCHEMA_PROFILE)
        if isinstance(result, dict):
            for regex_field in ("chapter_url_regex", "story_id_pattern"):
                val = result.get(regex_field)
                if val:
                    try:
                        re.compile(val)
                    except re.error:
                        result[regex_field] = None

            wm = result.get("domain_watermarks")
            if not isinstance(wm, list):
                result["domain_watermarks"] = []
            else:
                result["domain_watermarks"] = [
                    kw.lower().strip() for kw in wm
                    if isinstance(kw, str) and kw.strip()
                ][:5]

            if not isinstance(result.get("requires_playwright"), bool):
                result["requires_playwright"] = False

            return result
    except asyncio.CancelledError:
        raise
    except Exception as e:
        print(f"  [AI] ⚠ ask_ai_build_profile thất bại: {_fmt_err(e)}", flush=True)
    return None


async def ask_ai_for_story_id(
    urls: list[str],
    ai_limiter: AIRateLimiter,
) -> dict | None:
    if len(urls) < 3:
        return None
    prompt = PromptTemplates.story_id("\n".join(urls[:20]))
    try:
        result = await _generate_structured(prompt, ai_limiter, _SCHEMA_STORY_ID)
        if isinstance(result, dict) and result.get("story_id"):
            return result
    except asyncio.CancelledError:
        raise
    except Exception as e:
        print(f"  [AI] ⚠ ask_ai_for_story_id thất bại: {_fmt_err(e)}", flush=True)
    return None


async def ask_ai_confirm_same_story(
    title1: str, url1: str,
    title2: str, url2: str,
    ai_limiter: AIRateLimiter,
) -> bool:
    prompt = PromptTemplates.confirm_same_story(title1, url1, title2, url2)
    try:
        result = await _generate_structured(prompt, ai_limiter, _SCHEMA_SAME_STORY)
        if isinstance(result, dict):
            return bool(result.get("same_story", True))
    except asyncio.CancelledError:
        raise
    except Exception as e:
        print(f"  [AI] ⚠ ask_ai_confirm_same_story thất bại: {_fmt_err(e)}", flush=True)
    return True


async def ai_find_first_chapter_url(
    html: str,
    base_url: str,
    ai_limiter: AIRateLimiter,
) -> str | None:
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
    except asyncio.CancelledError:
        raise
    except Exception as e:
        print(f"  [AI] ⚠ ai_find_first_chapter_url thất bại: {_fmt_err(e)}", flush=True)

    return links[0]


async def ai_classify_and_find(
    html: str,
    base_url: str,
    ai_limiter: AIRateLimiter,
    domain_context: str | None = None,
) -> dict | None:
    """
    domain_context: ai_notes từ SiteProfileDict (nếu đã có profile).
    Được prepend vào prompt để AI hiểu quirks của site trước khi phân tích.
    """
    hint_block, snippet = await asyncio.to_thread(
        _sync_get_nav_hints_and_snippet, html, base_url
    )
    prompt = PromptTemplates.classify_and_find(
        hint_block, snippet, base_url,
        domain_context=domain_context,
    )
    try:
        result = await _generate_structured(prompt, ai_limiter, _SCHEMA_CLASSIFY)
        if isinstance(result, dict):
            return result
    except asyncio.CancelledError:
        raise
    except Exception as e:
        print(f"  [AI] ⚠ ai_classify_and_find thất bại: {_fmt_err(e)}", flush=True)
    return None


async def ai_validate_title(
    candidate: str,
    chapter_url: str,
    content_snippet: str,
    ai_limiter: AIRateLimiter,
) -> str | None:
    prompt = PromptTemplates.validate_title(candidate, chapter_url, content_snippet)
    try:
        result = await _generate_structured(prompt, ai_limiter, _SCHEMA_TITLE)
        if isinstance(result, dict) and result.get("valid"):
            return result.get("title") or candidate
    except asyncio.CancelledError:
        raise
    except Exception as e:
        print(f"  [AI] ⚠ ai_validate_title thất bại: {_fmt_err(e)}", flush=True)
    return None


async def ai_detect_ads_content(
    text: str,
    ai_limiter: AIRateLimiter,
) -> str | None:
    prompt = PromptTemplates.detect_ads(text)
    try:
        result = await _generate_structured(prompt, ai_limiter, _SCHEMA_ADS)
        if result is not None:
            return json.dumps(result)
    except asyncio.CancelledError:
        raise
    except Exception as e:
        print(f"  [AI] ⚠ ai_detect_ads_content thất bại: {_fmt_err(e)}", flush=True)
    return None


async def ask_ai_refine_profile(
    observations_summary: str,
    ai_limiter: AIRateLimiter,
) -> dict | None:
    """
    Gửi tổng hợp structural observations cho AI để tinh chỉnh CSS selectors.

    Input: observations_summary từ ProfileManager.get_observations_summary()
    Output: dict với các selector và confidence score (0.0–1.0)

    Caller (scraper.py) dùng ProfileManager.merge_refined_result() để apply,
    chỉ update field nếu confidence >= OBS_CONFIDENCE_MIN.

    Chỉ được gọi 1 lần per domain (sau khi mark_refined → should_refine = False).
    """
    prompt = PromptTemplates.refine_profile(observations_summary)
    try:
        result = await _generate_structured(prompt, ai_limiter, _SCHEMA_REFINE)
        if isinstance(result, dict):
            for conf_key in ("content_confidence", "title_confidence", "next_confidence"):
                val = result.get(conf_key, 0.0)
                try:
                    result[conf_key] = max(0.0, min(1.0, float(val)))
                except (TypeError, ValueError):
                    result[conf_key] = 0.0

            for sel_key in ("content_selector", "title_selector", "next_selector"):
                if result.get(sel_key) == "":
                    result[sel_key] = None

            return result
    except asyncio.CancelledError:
        raise
    except Exception as e:
        print(f"  [AI] ⚠ ask_ai_refine_profile thất bại: {_fmt_err(e)}", flush=True)
    return None


async def ask_ai_calibration_review(
    report: str,
    ai_limiter: AIRateLimiter,
) -> dict | None:
    """
    Gửi calibration report (issues từ N chương probe) cho AI.
    AI phân tích và trả về suggested profile fixes.

    Chỉ được gọi sau mỗi round calibration thất bại.
    Caller: core/calibrator.py → run_calibration_phase().
    """
    from config import CALIBRATION_CHAPTERS
    prompt = PromptTemplates.calibration_review(report, n_chapters=CALIBRATION_CHAPTERS)
    try:
        result = await _generate_structured(prompt, ai_limiter, _SCHEMA_CALIBRATION_FIX)
        if isinstance(result, dict):
            wm = result.get("domain_watermarks")
            if not isinstance(wm, list):
                result["domain_watermarks"] = []
            else:
                result["domain_watermarks"] = [
                    kw.lower().strip() for kw in wm
                    if isinstance(kw, str) and kw.strip()
                ]
            if not isinstance(result.get("has_nav_edges"), bool):
                result["has_nav_edges"] = False
            return result
    except asyncio.CancelledError:
        raise
    except Exception as e:
        print(f"  [AI] ⚠ ask_ai_calibration_review thất bại: {_fmt_err(e)}", flush=True)
    return None