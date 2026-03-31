# ai/agents.py
"""
ai/agents.py — Toàn bộ hàm gọi Gemini API.

Pattern chung:
  1. _generate_with_retry() → gọi AI async, tự retry khi gặp 429
  2. _parse_json_response()  → parse JSON từ response text
  3. Mỗi agent function chỉ build prompt + gọi helper trên

Tối ưu: BeautifulSoup parsing bên trong agent được đẩy xuống thread pool
qua asyncio.to_thread() để tránh block Event Loop.

Retry policy:
  - acquire() gọi MỘT LẦN duy nhất trước vòng lặp retry → không tiêu
    thêm RPM slot khi retry.
  - Tối đa 3 lần attempt, backoff 30s / 60s khi gặp 429 (lần thứ 3 raise).
  - generate_content dùng async API (client.aio) → không block event loop.
"""
from __future__ import annotations

import asyncio
import json
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from config import GEMINI_MODEL, RE_CHAP_HINT, RE_NEXT_PREV
from ai.client import ai_client, AIRateLimiter


# ── Retry helpers ─────────────────────────────────────────────────────────────

_MAX_RETRIES   = 3
# Backoff cho _MAX_RETRIES - 1 = 2 lần retry đầu.
# Lần thứ 3 (attempt == 2) sẽ raise ngay — không cần index thứ 3.
_RETRY_BACKOFF = [30, 60]


def _is_rate_limit_error(e: Exception) -> bool:
    """Phát hiện 429 / quota exceeded từ bất kỳ exception type nào."""
    code = getattr(e, "status_code", None) or getattr(e, "code", None)
    if code == 429:
        return True
    msg = str(e).lower()
    return "429" in msg or "quota" in msg or "resource_exhausted" in msg


async def _generate_with_retry(prompt: str, ai_limiter: AIRateLimiter) -> str:
    """
    Gọi Gemini async với retry tự động khi gặp 429 RateLimitError.

    FIX-1: Dùng `ai_client.aio.models.generate_content` (async) thay vì
           phiên bản sync — không còn block event loop trong lúc chờ API.

    FIX-2: `ai_limiter.acquire()` gọi MỘT LẦN trước vòng for.
           Phiên bản cũ acquire mỗi lần retry → tiêu thêm RPM slot sau
           mỗi lần thất bại, có thể cạn kiệt toàn bộ quota trong 1 burst.

    FIX-3: `_RETRY_BACKOFF` giảm xuống còn 2 phần tử [30, 60].
           Phiên bản cũ có [30, 60, 120] nhưng index 2 không bao giờ được
           dùng vì điều kiện `attempt < _MAX_RETRIES - 1` chỉ cho phép
           backoff ở attempt 0 và 1.

    Args:
        prompt:     Chuỗi prompt gửi Gemini.
        ai_limiter: Shared rate limiter (1 instance toàn app).

    Returns:
        Response text từ Gemini.

    Raises:
        Exception: Lỗi không phải 429, hoặc vẫn 429 sau khi hết retry.
    """
    # Acquire slot TRƯỚC vòng lặp — retry không tiêu thêm quota.
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

    # Unreachable — loop luôn return hoặc raise — nhưng cần cho mypy
    raise RuntimeError("_generate_with_retry: hết retry không mong đợi")


def _parse_json_response(text: str) -> dict | list | None:
    """Parse JSON từ response AI, chịu được ```json ... ``` fence."""
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$",          "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


# ── Sync HTML helpers (chạy trong thread pool) ────────────────────────────────

def _sync_get_profile_snippet(html: str) -> str:
    """Lấy HTML snippet (8KB) để build profile — CPU-bound."""
    soup = BeautifulSoup(html, "html.parser")
    return str(soup)[:8000]


def _sync_get_chapter_links(html: str, base_url: str) -> list[str]:
    """Tìm tất cả link có pattern chương trong HTML — CPU-bound."""
    soup = BeautifulSoup(html, "html.parser")
    return [
        urljoin(base_url, a["href"])
        for a in soup.find_all("a", href=True)
        if RE_CHAP_HINT.search(a["href"])
    ]


def _sync_get_nav_hints_and_snippet(html: str, base_url: str) -> tuple[str, str]:
    """
    Tìm nav hints (Next/Prev links) và HTML snippet cho ai_classify_and_find.
    CPU-bound — chạy qua asyncio.to_thread().
    Trả về (hint_block, snippet).
    """
    soup = BeautifulSoup(html, "html.parser")
    nav_hints = [
        f"{a.get_text(strip=True)!r} → {urljoin(base_url, a['href'])}"
        for a in soup.find_all("a", href=True)
        if RE_NEXT_PREV.search(a.get_text(strip=True))
    ]
    hint_block = "\n".join(nav_hints[:10]) if nav_hints else "(không có)"
    snippet    = str(soup)[:6000]
    return hint_block, snippet


# ── Agent functions ───────────────────────────────────────────────────────────

async def ask_ai_build_profile(
    html: str,
    url: str,
    ai_limiter: AIRateLimiter,
) -> dict | None:
    """Phân tích HTML để xây dựng CSS selector profile cho site mới."""
    snippet = await asyncio.to_thread(_sync_get_profile_snippet, html)

    prompt = f"""Phân tích HTML trang chương truyện sau và trả về JSON.
URL: {url}

HTML (rút gọn):
{snippet}

Yêu cầu JSON (CHỈ JSON, không có text khác):
{{
  "next_selector": "CSS selector tìm nút/link sang chương tiếp theo",
  "title_selector": "CSS selector tìm tiêu đề chương",
  "content_selector": "CSS selector vùng nội dung chính"
}}

Quy tắc:
- Selector phải hoạt động với BeautifulSoup find() hoặc select()
- Ưu tiên id > class cụ thể > tag + attribute
- Trả về null cho field nào không tìm được
"""
    try:
        text   = await _generate_with_retry(prompt, ai_limiter)
        result = _parse_json_response(text)
        if isinstance(result, dict):
            return result
    except Exception as e:
        print(f"  [AI] ⚠ ask_ai_build_profile thất bại: {e}", flush=True)
    return None


async def ask_ai_for_story_id(
    urls: list[str],
    ai_limiter: AIRateLimiter,
) -> dict | None:
    """
    Học pattern story_id từ danh sách URL đã cào.

    Sau STORY_ID_LEARN_AFTER chương, AI tìm phần cố định trong URL
    để xây regex kiểm tra URL tiếp theo có đúng truyện không.
    """
    if len(urls) < 3:
        return None

    sample = "\n".join(urls[:20])

    prompt = f"""Phân tích các URL chương truyện sau và tìm story ID.

URLs:
{sample}

Tìm phần CỐ ĐỊNH trong URL (story_id) và phần THAY ĐỔI (số chương).
Trả về JSON (CHỈ JSON):
{{
  "story_id": "phần cố định nhận dạng truyện này",
  "story_id_regex": "regex Python để match URL hợp lệ của truyện này"
}}
"""
    try:
        text   = await _generate_with_retry(prompt, ai_limiter)
        result = _parse_json_response(text)
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
    prompt = f"""Hai chương này có thuộc cùng một truyện không?

Chương 1: Tiêu đề: {title1} | URL: {url1}
Chương 2: Tiêu đề: {title2} | URL: {url2}

Trả về JSON (CHỈ JSON):
{{"same_story": true/false, "reason": "lý do ngắn gọn"}}
"""
    try:
        text   = await _generate_with_retry(prompt, ai_limiter)
        result = _parse_json_response(text)
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
    prompt = f"""Đây là các URL candidate cho chương đầu tiên của truyện:
{candidates}

Trang nguồn: {base_url}

Trả về JSON (CHỈ JSON):
{{"first_chapter_url": "URL chương đầu tiên"}}
"""
    try:
        text   = await _generate_with_retry(prompt, ai_limiter)
        result = _parse_json_response(text)
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
    """
    Phân loại trang và tìm URL next chapter / first chapter.

    Trả về: page_type (chapter|index|other), next_url, first_chapter_url.
    Nhận html đã được làm sạch (remove_hidden_elements) từ scraper.
    """
    hint_block, snippet = await asyncio.to_thread(
        _sync_get_nav_hints_and_snippet, html, base_url
    )

    prompt = f"""Phân loại trang web và tìm URL chương tiếp theo.

URL hiện tại: {base_url}

Link điều hướng tìm thấy:
{hint_block}

HTML (rút gọn):
{snippet}

Trả về JSON (CHỈ JSON):
{{
  "page_type": "chapter|index|other",
  "next_url": "URL chương tiếp theo hoặc null",
  "first_chapter_url": "URL chương đầu tiên (chỉ khi page_type=index) hoặc null"
}}
"""
    try:
        text   = await _generate_with_retry(prompt, ai_limiter)
        result = _parse_json_response(text)
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
    prompt = f"""Xác nhận tiêu đề chương truyện.

URL: {chapter_url}
Tiêu đề đề xuất: {candidate!r}
Đoạn đầu nội dung trang: {content_snippet[:300]!r}

Tiêu đề trên có hợp lệ không? Nếu có, trả về tiêu đề đã làm sạch.
Trả về JSON (CHỈ JSON):
{{"valid": true/false, "title": "tiêu đề làm sạch hoặc null"}}
"""
    try:
        text   = await _generate_with_retry(prompt, ai_limiter)
        result = _parse_json_response(text)
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
    Xác nhận danh sách câu nghi ngờ có phải ads/watermark thật sự không.

    Input : block text có context (xây bởi AdsFilter._ask_ai_and_update).
    Output: JSON thô — caller tự parse.
    """
    prompt = f"""You are a text filter assistant for web novel scrapers.

Below are suspicious lines found in novel chapters. Each entry shows:
- 10 lines of context BEFORE the suspicious line
- The suspicious line itself (marked with >>> <<<)
- 10 lines of context AFTER the suspicious line

Use the surrounding context to judge whether the marked line is truly
an injected watermark/ad, or just normal story content that happened
to match a keyword.

IMPORTANT: A line is only ads/watermark if it is clearly injected by an
aggregator site and does NOT belong to the story's narrative. If the
surrounding context shows it is part of the story (e.g. a character
mentions Amazon, a site name, or copyright as part of the plot, skill name,...),
mark it as NOT ads.

SUSPICIOUS LINES WITH CONTEXT:
{text}

Return ONLY a JSON object, no markdown, no extra text:
{{
  "found": true/false,
  "keywords": ["short phrases to add to keyword list, lowercase, max 8"],
  "patterns": ["python regex patterns, case-insensitive, max 5"],
  "example_lines": ["exact text of the >>> marked lines <<< that ARE ads, verbatim, max 5"]
}}

If none of the marked lines are ads, return: {{"found": false, "keywords": [], "patterns": [], "example_lines": []}}"""

    try:
        return await _generate_with_retry(prompt, ai_limiter)
    except Exception as e:
        print(f"  [AI] ⚠ ai_detect_ads_content thất bại: {e}", flush=True)
    return None