"""Trích xuất nội dung chương (selector, JSON-LD, density heuristic, fallback list)."""
from __future__ import annotations

import json
import logging
import math
from typing import Any

from bs4 import BeautifulSoup, Tag

from cao_text.html.formatter import MarkdownFormatter
from cao_text.models import FormattingRules, ImageRef, SiteProfile

logger = logging.getLogger(__name__)

_MIN_CONTENT_CHARS: int = 150

# Fallback content selectors phổ biến cho các trang web tiểu thuyết
FALLBACK_CONTENT_SELECTORS: list[str] = [
    "#chapter-c",
    "#chr-content",
    "div.chapter-content",
    ".chapter-content",
    "article",
    "[itemprop='articleBody']",
    "#storytext",
    "div.text-left",
    "div.entry-content",
]

_CANDIDATE_TAGS = frozenset({"article", "main", "section", "div", "td"})
_SKIP_TAGS = frozenset({
    "script",
    "style",
    "nav",
    "header",
    "footer",
    "aside",
    "form",
    "noscript",
    "iframe",
})


def _get_formatting_rules(profile: Any) -> FormattingRules | dict[str, Any] | None:
    if profile is None:
        return None
    if hasattr(profile, "formatting_rules"):
        return profile.formatting_rules
    if isinstance(profile, dict):
        return profile.get("formatting_rules")
    return None


def _format_node(
    el: Tag,
    profile: Any,
    base_url: str = "",
) -> tuple[str, list[ImageRef]]:
    rules = _get_formatting_rules(profile)
    return MarkdownFormatter(rules).format(el, base_url=base_url)


def _score_density_element(el: Tag) -> tuple[float, int]:
    """Tính điểm mật độ văn bản cho element theo phong cách Trafilatura với wrapper-preference."""
    full_html = str(el)
    html_len = max(len(full_html), 1)
    text = el.get_text(separator=" ", strip=True)
    text_len = len(text)
    if text_len < 50:
        return 0.0, 0

    link_text = "".join(a.get_text(separator=" ", strip=True) for a in el.find_all("a"))
    link_density = len(link_text) / max(text_len, 1)
    if link_density > 0.6:
        return 0.0, 0

    text_density = text_len / html_len

    # PARA-BONUS: đếm số đoạn con mang văn bản (hỗ trợ div.cha-paragraph của Webnovel)
    para_count = len(el.find_all("p"))
    if para_count < 2:
        direct_text_children = sum(
            1
            for child in el.find_all(recursive=False)
            if isinstance(child, Tag) and len(child.get_text(strip=True)) >= 30
        )
        para_count = max(para_count, direct_text_children)
    p_bonus = min(para_count * 0.05, 0.5)

    # WRAPPER-PREFERENCE (§6.4): ưu tiên container lớn nhiều đoạn thay vì một thẻ <p> đơn lẻ
    wrapper_bonus = 1.5 if (text_len >= 1000 and para_count >= 5) else 1.0

    score = (
        text_density
        * (1.0 - link_density)
        * math.log(text_len + 1)
        * (1.0 + p_bonus)
        * wrapper_bonus
    )
    return score, text_len


def extract_content(
    soup: BeautifulSoup,
    url: str,
    profile: SiteProfile | dict[str, Any] | None = None,
    *,
    min_chars: int = _MIN_CONTENT_CHARS,
) -> tuple[str | None, str | None, list[ImageRef], str | None]:
    """Trích xuất nội dung chương theo chuỗi chiến lược xác định (không AI):

    1. CSS Selector từ profile (nhanh nhất, độ tin cậy cao nhất).
    2. JSON-LD schema (Article / BlogPosting).
    3. Density Heuristic (tính toán mật độ text, ưu tiên khối wrapper).
    4. Danh sách fallback selectors phổ biến.

    Trả về: (formatted_markdown, method_used, images, selector_used)
    """
    if soup is None:
        return None, None, [], None

    content_selector: str | None = None
    if profile is not None:
        if hasattr(profile, "content_selector"):
            content_selector = profile.content_selector
        elif isinstance(profile, dict):
            content_selector = profile.get("content_selector")

    # 1. Selector từ Profile
    if content_selector:
        try:
            el = soup.select_one(content_selector)
            if el is not None:
                text, images = _format_node(el, profile, base_url=url)
                if len(text.strip()) >= min_chars:
                    return text, f"selector:{content_selector}", images, content_selector
        except Exception as e:
            logger.debug("[Extract] selector %r failed: %s", content_selector, e)

    # 2. JSON-LD
    try:
        for script in soup.find_all("script", type="application/ld+json"):
            raw = script.get_text(strip=True)
            if not raw:
                continue
            try:
                data = json.loads(raw)
            except Exception:
                continue
            items = data if isinstance(data, list) else [data]
            for item in items:
                if not isinstance(item, dict):
                    continue
                body = item.get("articleBody") or item.get("text") or item.get("description")
                schema_type = item.get("@type", "")
                if (
                    body
                    and isinstance(body, str)
                    and len(body.strip()) >= min_chars
                    and schema_type in ("Article", "BlogPosting", "NewsArticle", "WebPage", "")
                ):
                    return body.strip(), f"json_ld:{schema_type or 'unknown'}", [], None
    except Exception as e:
        logger.debug("[Extract] JSON-LD check failed: %s", e)

    # 3. Density Heuristic (ưu tiên wrapper)
    best_el: Tag | None = None
    best_score: float = 0.0

    for el in soup.find_all(True):
        if not isinstance(el, Tag):
            continue
        tag = el.name.lower() if el.name else ""
        if tag in _SKIP_TAGS or tag not in _CANDIDATE_TAGS:
            continue

        score, text_len = _score_density_element(el)
        if score > best_score and text_len >= min_chars:
            best_score = score
            best_el = el

    if best_el is not None and best_score > 0:
        text, images = _format_node(best_el, profile, base_url=url)
        if len(text.strip()) >= min_chars:
            return text, "density_heuristic", images, None

    # 4. Fallback List
    for sel in FALLBACK_CONTENT_SELECTORS:
        try:
            el = soup.select_one(sel)
            if el is None:
                continue
            text, images = _format_node(el, profile, base_url=url)
            if len(text.strip()) >= min_chars:
                return text, f"fallback_list:{sel}", images, sel
        except Exception:
            continue

    return None, None, [], None
