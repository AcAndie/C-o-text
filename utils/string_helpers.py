"""
utils/string_helpers.py — Hàm tiện ích xử lý chuỗi, không có side-effect.

  • CF_CHALLENGE_TITLES      — set tiêu đề trang Cloudflare challenge (public)
  • is_cloudflare_challenge  — phát hiện CF challenge qua <title>
  • is_junk_page             — phát hiện trang lỗi / hết truyện / không tìm thấy
  • make_fingerprint         — MD5 nội dung để phát hiện vòng lặp
  • clean_chapter_text       — làm sạch text trích từ HTML
  • normalize_title          — chuẩn hóa tiêu đề: xóa suffix site, ký tự lạ
  • slugify_filename         — tên file an toàn trên mọi OS
  • truncate                 — cắt chuỗi với ellipsis
"""
import hashlib
import re
import unicodedata

from bs4 import BeautifulSoup


# ── Cloudflare challenge detection ────────────────────────────────────────────

# Public (không có dấu _) để session_pool.py import trực tiếp mà không
# phụ thuộc vào tên private.
CF_CHALLENGE_TITLES = frozenset({
    "just a moment...",
    "just a moment",
    "checking your browser before accessing",
    "please wait...",
    "please wait",
    "attention required!",
    "attention required",
    "one more step",
    "security check",
    "ddos-guard",
    "enable javascript and cookies to continue",
})


def is_cloudflare_challenge(html: str) -> bool:
    soup      = BeautifulSoup(html, "html.parser")
    title_tag = soup.find("title")
    if not title_tag:
        return False
    return title_tag.get_text(strip=True).lower() in CF_CHALLENGE_TITLES


# ── Junk / error page detection ───────────────────────────────────────────────

_JUNK_TITLE_RE = re.compile(
    r"\b(404|403|page\s*not\s*found|not\s*found|access\s*denied"
    r"|chapter\s*not\s*found|chapter\s*unavailable"
    r"|no\s*chapter|end\s*of\s*(story|novel|book)"
    r"|story\s*(not\s*found|removed|deleted|unavailable)"
    r"|trang\s*kh[oô]ng\s*t[oồ]n\s*t[aạ]i|kh[oô]ng\s*t[iì]m\s*th[aấ]y"
    r"|ch[uư][oơ]ng\s*kh[oô]ng\s*t[oồ]n\s*t[aạ]i)\b",
    re.IGNORECASE | re.UNICODE,
)

_ERROR_HTTP_STATUSES = frozenset({400, 401, 403, 404, 410, 429, 500, 502, 503})
_MIN_BODY_CHARS      = 150


def is_junk_page(html: str, status_code: int = 200) -> bool:
    if status_code in _ERROR_HTTP_STATUSES:
        return True

    soup = BeautifulSoup(html, "html.parser")

    title_tag = soup.find("title")
    if title_tag and _JUNK_TITLE_RE.search(title_tag.get_text(strip=True)):
        return True

    body = soup.find("body")
    if body and len(body.get_text(separator=" ", strip=True)) < _MIN_BODY_CHARS:
        return True

    return False


# ── Content fingerprint ───────────────────────────────────────────────────────

def make_fingerprint(text: str) -> str:
    """MD5 của nội dung đã normalize — phát hiện chương lặp lại."""
    normalized = " ".join(text.lower().split())
    return hashlib.md5(normalized.encode("utf-8", errors="replace")).hexdigest()


# ── Text cleaning ─────────────────────────────────────────────────────────────

_RE_MULTI_BLANK = re.compile(r"\n{3,}")


def clean_chapter_text(raw: str) -> str:
    """Xóa whitespace thừa cuối dòng, gộp nhiều dòng trắng thành tối đa 2."""
    lines  = [line.rstrip() for line in raw.splitlines()]
    joined = "\n".join(lines)
    return _RE_MULTI_BLANK.sub("\n\n", joined).strip()


# ── Title normalization ───────────────────────────────────────────────────────

_RE_SITE_SUFFIX = re.compile(
    r"\s*[\|–\-—]\s*[A-Za-z0-9][A-Za-z0-9 .]{2,40}$",
    re.UNICODE,
)
_RE_LEADING_NUM = re.compile(r"^\d+[\.\)]\s+")
_RE_CTRL_CHARS  = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def normalize_title(raw: str) -> str:
    t = raw.strip()
    t = _RE_SITE_SUFFIX.sub("", t).strip()
    t = _RE_CTRL_CHARS.sub("", t)
    t = _RE_LEADING_NUM.sub("", t)
    t = unicodedata.normalize("NFC", t)
    t = re.sub(r"\s+", " ", t).strip()
    t = t.strip('"').strip("'").strip()
    return t or "Không rõ tiêu đề"


# ── Safe filename ─────────────────────────────────────────────────────────────

_RE_UNSAFE_CHARS = re.compile(r'[\\/:*?"<>|\x00-\x1f]')

_WINDOWS_RESERVED = frozenset({
    "CON", "PRN", "AUX", "NUL",
    "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9",
    "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9",
})


def slugify_filename(name: str, max_len: int = 80) -> str:
    safe = _RE_UNSAFE_CHARS.sub("_", name)
    safe = re.sub(r"_+", "_", safe)
    safe = re.sub(r"\s+", " ", safe).strip()
    safe = safe.strip(".")
    if safe.split(".")[0].upper() in _WINDOWS_RESERVED:
        safe = f"_{safe}"
    return safe[:max_len] or "_"


# ── Truncate ──────────────────────────────────────────────────────────────────

def truncate(text: str, max_len: int, ellipsis: str = "…") -> str:
    if len(text) <= max_len:
        return text
    return text[: max_len - len(ellipsis)] + ellipsis