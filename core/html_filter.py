# core/html_filter.py
"""
core/html_filter.py — Loại bỏ element ẩn / watermark / script khỏi BeautifulSoup tree.

THAY ĐỔI (v2):
  - Thêm strip_noise_tags(): xóa <script>, <style>, <noscript>, <iframe>,
    <svg>, <figure> trước khi extract text.
    → Fix lỗi fanfiction.net: content div chứa <script> inline bị lẫn vào .md.

  - remove_hidden_elements() gọi strip_noise_tags() ở bước đầu tiên,
    đảm bảo pipeline luôn sạch mà không cần caller gọi riêng.

External-CSS limitation (known):
  _extract_css_hidden_classes() chỉ parse <style> inline, không fetch
  file .css ngoại tuyến. Với trường hợp đó, SimpleAdsFilter (AI) là
  chốt chặn cuối cùng.
"""
import logging
import re

from bs4 import BeautifulSoup, Tag

logger = logging.getLogger(__name__)


# ── Tags cần xóa hoàn toàn (không phải ẩn — là noise) ────────────────────────

_NOISE_TAGS = frozenset({
    "script",
    "style",       # CSS inline (đã parse xong, không cần nữa)
    "noscript",
    "iframe",
    "svg",
    "canvas",
    "figure",      # thường chứa ảnh, không phải text truyện
    "picture",
    "source",
    "video",
    "audio",
    "form",        # login/comment form không phải nội dung
})


# ── Compiled regexes ──────────────────────────────────────────────────────────

_HIDDEN_STYLE_RE = re.compile(
    r"display\s*:\s*none"
    r"|visibility\s*:\s*hidden"
    r"|opacity\s*:\s*0(?:\.0+)?\b"
    r"|font-size\s*:\s*0"
    r"|color\s*:\s*transparent"
    r"|width\s*:\s*0"
    r"|height\s*:\s*0",
    re.IGNORECASE,
)

_HIDDEN_CLASS_RE = re.compile(
    r"\b(?:"
    r"hidden|invisible|sr-only|visually-hidden|"
    r"d-none|display-none|hide|offscreen|"
    r"watermark|wm-text|"
    r"noshow|no-show|"
    r"rr-hidden|rr-copyright|sh-notice|"
    r"theft-notice|stolen-notice|copyright-notice"
    r")\b",
    re.IGNORECASE,
)

_CSS_HIDDEN_RULE_RE = re.compile(
    r"\.([\w-]{4,})"
    r"\s*\{[^}]*"
    r"(?:"
    r"display\s*:\s*none"
    r"|speak\s*:\s*never"
    r"|visibility\s*:\s*hidden"
    r")"
    r"[^}]*\}",
    re.IGNORECASE | re.DOTALL,
)


# ── Public API ────────────────────────────────────────────────────────────────

def strip_noise_tags(soup: BeautifulSoup) -> BeautifulSoup:
    """
    Xóa các thẻ không chứa nội dung truyện: script, style, noscript, iframe, svg...

    Gọi TRƯỚC khi extract text để tránh JS/CSS bị lẫn vào nội dung.

    Trường hợp thực tế đã gặp:
      - fanfiction.net: <div id="storytext"> chứa <script> inline (jQuery loader,
        logout handler...) → extract_text_blocks() trả về JS code thay vì story text.
      - Nhiều site khác nhúng Google Analytics, ads JS bên trong content div.

    Mutate in-place, trả về soup để tiện chain.
    """
    removed = 0
    for tag_name in _NOISE_TAGS:
        for el in list(soup.find_all(tag_name)):
            el.decompose()
            removed += 1

    if removed:
        logger.debug("[NoiseFilter] Đã xóa %d noise tag (%s)", removed, ", ".join(_NOISE_TAGS))

    return soup


def remove_hidden_elements(soup: BeautifulSoup) -> BeautifulSoup:
    """
    Pipeline làm sạch DOM:
      Bước 0: strip_noise_tags() — xóa script/style/noscript/...  ← MỚI
      Bước 1: Thu thập dynamic hidden classes từ <style> blocks
      Bước 2: Xóa tất cả element bị ẩn (hidden attr, aria-hidden, inline CSS, class)

    Trả về cùng đối tượng soup (mutate in-place).
    """
    # ── Bước 0: Xóa noise tags trước ─────────────────────────────────────────
    # Phải làm TRƯỚC bước 1 để <style> blocks đã bị xóa không ảnh hưởng.
    # Nhưng _extract_css_hidden_classes đọc <style> nên cần đổi thứ tự:
    # → Thu thập dynamic classes TRƯỚC khi xóa <style>.
    dynamic_hidden = _extract_css_hidden_classes(soup)

    if dynamic_hidden:
        logger.debug(
            "[HiddenFilter] Tìm thấy %d dynamic hidden class: %s",
            len(dynamic_hidden),
            sorted(dynamic_hidden)[:5],
        )

    # Xóa noise tags (bao gồm <style> vì đã extract xong)
    strip_noise_tags(soup)

    # ── Bước 2: Xóa hidden elements ───────────────────────────────────────────
    removed = 0
    for el in list(soup.find_all(True)):
        if not isinstance(el, Tag):
            continue
        if not isinstance(el.attrs, dict):
            continue
        if _is_hidden(el) or _has_dynamic_hidden_class(el, dynamic_hidden):
            el.decompose()
            removed += 1

    if removed:
        logger.debug("[HiddenFilter] Đã xóa %d element ẩn", removed)

    return soup


# ── Private helpers ───────────────────────────────────────────────────────────

def _extract_css_hidden_classes(soup: BeautifulSoup) -> frozenset[str]:
    """
    Parse tất cả thẻ <style> trong trang.
    Trả về frozenset các class name bị khai báo hidden.

    Gọi TRƯỚC khi strip_noise_tags() để còn thấy <style> blocks.
    """
    hidden_classes: set[str] = set()

    for style_tag in soup.find_all("style"):
        css_text = style_tag.get_text()
        if not css_text:
            continue
        for match in _CSS_HIDDEN_RULE_RE.finditer(css_text):
            hidden_classes.add(match.group(1))

    return frozenset(hidden_classes)


def _has_dynamic_hidden_class(el: Tag, dynamic_hidden: frozenset[str]) -> bool:
    if not dynamic_hidden:
        return False
    el_classes: list[str] = el.get("class") or []
    return any(cls in dynamic_hidden for cls in el_classes)


def _is_hidden(el: Tag) -> bool:
    """Kiểm tra element có đang bị ẩn không (static rules)."""
    if el.has_attr("hidden"):
        return True
    if el.get("aria-hidden") == "true":
        return True

    style = el.get("style", "")
    if style and _HIDDEN_STYLE_RE.search(style):
        return True

    classes = " ".join(el.get("class", []))
    if classes and _HIDDEN_CLASS_RE.search(classes):
        return True

    return False