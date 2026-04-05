"""
utils/string_helpers.py — Pure utility functions, không import từ module nội bộ nào.

Functions:
    domain_tag()            — short display tag cho logging (move từ core/scraper._dtag)
    normalize_title()       — chuẩn hóa chapter title
    strip_site_suffix()     — bóc "| Royal Road", "- FanFiction.net", v.v.
    slugify_filename()      — tạo tên file an toàn từ title
    truncate()              — cắt string với ellipsis
    make_fingerprint()      — MD5 hash cho dedup
    is_junk_page()          — kiểm tra HTML có phải junk/error page không
    is_cloudflare_challenge() — kiểm tra có phải CF challenge không
"""
from __future__ import annotations

import hashlib
import re
import unicodedata
from urllib.parse import urlparse


# ── domain_tag ─────────────────────────────────────────────────────────────────

def domain_tag(url_or_domain: str) -> str:
    """
    Short display tag cho console logging.

    Được move từ core/scraper._dtag() để tránh circular import
    khi learning/ modules cần gọi nó.

    Examples:
        domain_tag("https://www.royalroad.com/fiction/123") → "royalroad   "
        domain_tag("www.fanfiction.net")                    → "fanfiction  "
        domain_tag("novelfire.net")                         → "novelfire   "
    """
    if url_or_domain.startswith("http"):
        netloc = urlparse(url_or_domain).netloc.lower()
    else:
        netloc = url_or_domain.lower()
    name = netloc.replace("www.", "").split(".")[0]
    return f"{name[:12]:<12}"


# ── normalize_title ────────────────────────────────────────────────────────────

# Ký tự không được phép trong tên file Windows/Linux
_UNSAFE_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

# Dấu phân cách phổ biến trong title
_TITLE_SEP = re.compile(r"\s*[–—]\s*|\s{2,}")

# Site suffixes cần bóc: "| Royal Road", "- FanFiction.Net", v.v.
_SITE_SUFFIX = re.compile(
    r"\s*[\|–—\-]\s*(?:royal\s*road|scribblehub|wattpad|fanfiction\.net"
    r"|archiveofourown\.org|ao3|webnovel|novelfire|novelupdates"
    r"|lightnovelreader|novelfull|wuxiaworld|readlightnovel"
    r"|[a-z0-9\-]+\.(?:com|net|org|io))\s*$",
    re.IGNORECASE,
)


def normalize_title(text: str) -> str:
    """
    Chuẩn hóa chapter/story title:
        - Strip whitespace đầu cuối
        - Chuẩn hóa khoảng trắng bên trong
        - Loại bỏ ký tự control (U+0000 - U+001F)

    Không strip site suffix — dùng strip_site_suffix() riêng nếu cần.

    Examples:
        normalize_title("  Chapter  5  –  The Rise  ") → "Chapter 5 – The Rise"
        normalize_title("Prologue\x00") → "Prologue"
    """
    if not text:
        return ""
    # Loại bỏ control characters
    text = re.sub(r"[\x00-\x1f\x7f]", "", text)
    # Chuẩn hóa khoảng trắng
    text = re.sub(r"[ \t]+", " ", text).strip()
    return text


def strip_site_suffix(text: str) -> str:
    """
    Bóc site suffix từ title.

    Dùng bởi TitleTagBlock và OgTitleBlock để làm sạch <title> tag.

    Examples:
        strip_site_suffix("Chapter 5 | Royal Road")  → "Chapter 5"
        strip_site_suffix("Prologue - FanFiction.net") → "Prologue"
        strip_site_suffix("Chapter 5 – The Rise")    → "Chapter 5 – The Rise"
    """
    text = _SITE_SUFFIX.sub("", text).strip()
    return text


# ── slugify_filename ───────────────────────────────────────────────────────────

_SLUG_REPLACE = {
    "–": "-", "—": "-", "…": "...", "'": "'", "'": "'",
    """: '"', """: '"', "«": '"', "»": '"',
    "×": "x", "÷": "-", "©": "", "®": "", "™": "",
    "→": "-", "←": "-", "↑": "", "↓": "",
    "★": "", "☆": "", "♥": "", "♦": "", "♠": "", "♣": "",
    "•": "-", "·": "-", "。": ".", "，": ",",
}

_SLUG_UNSAFE  = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_SLUG_SPACES  = re.compile(r"[\s_]+")
_SLUG_DOTS    = re.compile(r"\.{2,}")
_SLUG_EDGES   = re.compile(r"^[\s.\-_]+|[\s.\-_]+$")
_SLUG_MULTI   = re.compile(r"-{2,}")


def slugify_filename(text: str, max_len: int = 80) -> str:
    """
    Tạo tên file an toàn từ title.

    Xử lý:
        - Unicode typographic chars → ASCII equivalents
        - Ký tự không an toàn cho filesystem → xóa
        - Khoảng trắng → underscore
        - Giới hạn độ dài

    Examples:
        slugify_filename("Chapter 5 – The Rise!") → "Chapter_5_-_The_Rise"
        slugify_filename("Hello: World?")          → "Hello_World"
        slugify_filename("A" * 200, max_len=80)    → "A" * 80
    """
    if not text:
        return "untitled"

    # Unicode normalization
    text = unicodedata.normalize("NFC", text)

    # Replace typographic chars
    for src, dst in _SLUG_REPLACE.items():
        text = text.replace(src, dst)

    # Loại bỏ ký tự không an toàn
    text = _SLUG_UNSAFE.sub("", text)

    # Spaces/tabs → underscore
    text = _SLUG_SPACES.sub("_", text)

    # Multiple dots → single
    text = _SLUG_DOTS.sub(".", text)

    # Strip leading/trailing unsafe chars
    text = _SLUG_EDGES.sub("", text)

    # Truncate
    if len(text) > max_len:
        text = text[:max_len]
        # Không cắt giữa chừng một "word"
        text = _SLUG_EDGES.sub("", text)

    return text or "untitled"


# ── truncate ───────────────────────────────────────────────────────────────────

def truncate(text: str, max_len: int, ellipsis: str = "…") -> str:
    """
    Cắt string, thêm ellipsis nếu bị cắt.

    Examples:
        truncate("Hello World", 8)  → "Hello W…"
        truncate("Hello", 10)       → "Hello"
    """
    if len(text) <= max_len:
        return text
    return text[:max_len - len(ellipsis)] + ellipsis


# ── make_fingerprint ───────────────────────────────────────────────────────────

def make_fingerprint(content: str) -> str:
    """
    Tạo MD5 fingerprint từ content để dedup chapters.

    Normalize whitespace trước khi hash để tránh false negative
    do trailing spaces hoặc CRLF vs LF.

    Returns:
        16-char hex string (128-bit MD5, đủ cho dedup, không cần security).
    """
    normalized = re.sub(r"\s+", " ", content.strip())
    return hashlib.md5(normalized.encode("utf-8", errors="replace")).hexdigest()[:16]


# ── is_junk_page ───────────────────────────────────────────────────────────────

_JUNK_PATTERNS = [
    re.compile(r"<title>[^<]*404[^<]*</title>",        re.IGNORECASE),
    re.compile(r"<title>[^<]*not found[^<]*</title>",  re.IGNORECASE),
    re.compile(r"<title>[^<]*error[^<]*</title>",      re.IGNORECASE),
    re.compile(r"<title>[^<]*access denied[^<]*</title>", re.IGNORECASE),
    re.compile(r"<title>[^<]*forbidden[^<]*</title>",  re.IGNORECASE),
]

_JUNK_STATUSES = frozenset({400, 401, 403, 404, 410, 429, 500, 502, 503, 504})


def is_junk_page(html: str, status: int = 200) -> bool:
    """
    Kiểm tra response có phải junk/error page không.

    Junk nếu:
        - Status code là error (4xx, 5xx)
        - HTML quá ngắn (< 200 chars) — thường là error page rỗng
        - Title tag chứa "404", "Not Found", "Error", v.v.
        - HTML là None/empty

    Args:
        html:   Response HTML string
        status: HTTP status code (default 200 nếu không biết)
    """
    if not html or len(html.strip()) < 200:
        return True
    if status in _JUNK_STATUSES:
        return True
    # Kiểm tra title
    for pattern in _JUNK_PATTERNS:
        if pattern.search(html[:2000]):
            return True
    return False


# ── is_cloudflare_challenge ────────────────────────────────────────────────────

_CF_PATTERNS = [
    re.compile(r"<title>[^<]*just a moment[^<]*</title>",    re.IGNORECASE),
    re.compile(r"<title>[^<]*cloudflare[^<]*</title>",       re.IGNORECASE),
    re.compile(r"cf-browser-verification",                    re.IGNORECASE),
    re.compile(r"checking your browser",                      re.IGNORECASE),
    re.compile(r"enable javascript and cookies",              re.IGNORECASE),
    re.compile(r"ray id.*cloudflare",                         re.IGNORECASE),
    re.compile(r'id="challenge-form"',                        re.IGNORECASE),
    re.compile(r"__cf_chl_opt",                               re.IGNORECASE),
]


def is_cloudflare_challenge(html: str) -> bool:
    """
    Kiểm tra response có phải Cloudflare challenge page không.

    Dùng bởi HybridFetchBlock để quyết định fallback sang Playwright.

    Checks:
        - Title "Just a moment" / "Cloudflare"
        - CF-specific DOM elements
        - Challenge form / JS variables
    """
    if not html or len(html) < 100:
        return False
    sample = html[:5000]
    return any(p.search(sample) for p in _CF_PATTERNS)


# ── is_junk_page overload (no status) ─────────────────────────────────────────
# Một số chỗ gọi is_junk_page(html) không có status — cần support cả 2 cách gọi.
# Python default argument đã handle việc này: status=200 → không junk by status.


# ── Convenience re-exports ─────────────────────────────────────────────────────
# Backward compatibility: một số file cũ import _dtag từ đây
# Xóa alias này sau khi tất cả callers đã update.
_dtag = domain_tag