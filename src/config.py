"""
config.py — Hằng số, regex và helpers thuần túy.
Không import từ module nội bộ nào.

v2: Thêm PW_MAX_CONCURRENCY, EMPTY_BACKOFF_SCHEDULE cho pipeline architecture.
v3: P1-B — thêm JS_CONTENT_RATIO, JS_MIN_DIFF_CHARS để tránh DRY violation.
    Hai nơi dùng cùng threshold: fetcher.py, phase.py.
    Đặt ở đây để thay đổi threshold chỉ cần sửa 1 file.
v4: VERSION constant — first explicit version tag for v1.0.0 ship.
v5 (1.0.7): User-facing config.toml override. Tunable constants now read
    from optional config.toml (Python 3.11+ stdlib tomllib). Priority:
    CLI flag > config.toml > code default. .env still owns API secrets.
v6 (1.0.8): Code moved into src/. .env + config.toml resolve from project root
    (one level above src/).
"""
import os
import re
import random
import tomllib
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv

# Project root = parent of src/ (this file lives at src/config.py since v1.0.8).
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(dotenv_path=_PROJECT_ROOT / ".env")
# Legacy fallback for nested-project setups where .env lives one level above.
load_dotenv(dotenv_path=_PROJECT_ROOT.parent / ".env")

# ── User config.toml (optional) ───────────────────────────────────────────────
# User-facing override file. Drop a config.toml next to main.py at project
# root and tune behavior without editing this file. See config.toml.example
# for template. Missing file or section → falls back to code default below.
_TOML_PATH = _PROJECT_ROOT / "config.toml"
_user_cfg: dict = {}
if _TOML_PATH.exists():
    try:
        with open(_TOML_PATH, "rb") as _f:
            _user_cfg = tomllib.load(_f) or {}
    except (tomllib.TOMLDecodeError, OSError) as _e:
        print(f"[WARN] config.toml load failed: {_e} — dùng code defaults", flush=True)
        _user_cfg = {}


def _get(section: str, key: str, default):
    """Read `[section] key` từ config.toml, fallback default nếu thiếu."""
    return _user_cfg.get(section, {}).get(key, default)


# ── Project version ───────────────────────────────────────────────────────────
# Bump on tagged release. See CHANGELOG.md for history.
VERSION = "1.0.25"


# ── API ───────────────────────────────────────────────────────────────────────
GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
if not GEMINI_API_KEY:
    raise SystemExit("[ERR] Không tìm thấy GEMINI_API_KEY trong .env")

GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")

# ── Fallback model khi model chính bị 503 kéo dài ────────────────────────────
# Nếu không set, tự tính: flash-lite nếu model chính là flash/pro, không đổi nếu đã là flash-lite.
def _derive_fallback(primary: str) -> str:
    _p = primary.lower()
    if "flash-lite" in _p:
        return primary  # đã là lite rồi, giữ nguyên
    if "flash" in _p or "pro" in _p:
        return "gemini-2.0-flash-lite"
    return "gemini-2.0-flash-lite"

GEMINI_FALLBACK_MODEL: str = os.getenv("GEMINI_FALLBACK_MODEL", _derive_fallback(GEMINI_MODEL))

# ── Giới hạn scraper ──────────────────────────────────────────────────────────
MAX_CHAPTERS             = _get("scraper", "max_chapters",             5000)
MAX_CONSECUTIVE_ERRORS   = _get("scraper", "max_consecutive_errors",   5)
MAX_CONSECUTIVE_TIMEOUTS = _get("scraper", "max_consecutive_timeouts", 3)
TIMEOUT_BACKOFF_BASE     = _get("scraper", "timeout_backoff_base",     30)   # seconds

# ── Paths ─────────────────────────────────────────────────────────────────────
DATA_DIR      = _get("paths", "data_dir",     "data")
OUTPUT_DIR    = _get("paths", "output_dir",   "output")
PROGRESS_DIR  = _get("paths", "progress_dir", "progress")
PROFILES_FILE = os.path.join(DATA_DIR, "site_profiles.json")
ADS_DB_FILE   = os.path.join(DATA_DIR, "ads_keywords.json")

# ── Learning phase ────────────────────────────────────────────────────────────
LEARNING_CHAPTERS           = _get("learning", "chapters",            10)
LEARNING_MIN_CONTENT        = _get("learning", "min_content",         300)
PROFILE_MAX_AGE_DAYS        = _get("learning", "profile_max_age_days", 30)
LEARNING_AI_CALLS           = _get("learning", "ai_calls",            10)
LEARNING_CONFLICT_THRESHOLD = _get("learning", "conflict_threshold",   3)

# ── AI ────────────────────────────────────────────────────────────────────────
AI_MAX_RPM = _get("ai", "max_rpm", 10)
AI_JITTER  = tuple(_get("ai", "jitter", [0.5, 2.0]))

# ── HTTP ──────────────────────────────────────────────────────────────────────
REQUEST_TIMEOUT = _get("http", "request_timeout", 60)

# ── Playwright concurrency ────────────────────────────────────────────────────
# Priority: env PW_MAX_CONCURRENCY > config.toml > default 2.
PW_MAX_CONCURRENCY: int = int(
    os.getenv("PW_MAX_CONCURRENCY", str(_get("scraper", "playwright_concurrency", 2)))
)

# ── JS-heavy detection thresholds (P1-B) ─────────────────────────────────────
# Playwright/curl content ratio threshold để classify site là JS-heavy.
# Nếu pw_text_len > curl_text_len * JS_CONTENT_RATIO AND diff > JS_MIN_DIFF_CHARS
# → site cần Playwright để render content đầy đủ.
JS_CONTENT_RATIO  : float = _get("js_detection", "content_ratio",  1.5)
JS_MIN_DIFF_CHARS : int   = _get("js_detection", "min_diff_chars", 500)

# ── Empty streak backoff schedule ─────────────────────────────────────────────
EMPTY_BACKOFF_SCHEDULE: list[int] = _get("scraper", "empty_backoff_schedule", [60, 120, 300])

# ── Misc ──────────────────────────────────────────────────────────────────────
INIT_STAGGER = _get("scraper", "init_stagger", 2.0)  # seconds giữa task khởi động

# ── Chrome fingerprint rotation ───────────────────────────────────────────────
CHROME_VERSIONS: list[str] = ["chrome119", "chrome120", "chrome123", "chrome124", "chrome131"]
CHROME_UA: dict[str, str] = {
    "chrome119": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "chrome120": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "chrome123": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "chrome124": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "chrome131": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
}

def pick_chrome_version() -> str:
    return random.choice(CHROME_VERSIONS)

def make_headers(version: str, referer: str | None = None) -> dict[str, str]:
    """v1.0.24: optional referer cho sites reject direct chapter access
    (Chinese sites như 69shuba thường check Referer)."""
    h = {
        "User-Agent"               : CHROME_UA.get(version, CHROME_UA["chrome124"]),
        "Accept"                   : "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language"          : "en-US,en;q=0.9",
        "Accept-Encoding"          : "gzip, deflate, br",
        "Connection"               : "keep-alive",
        "Upgrade-Insecure-Requests": "1",
    }
    if referer:
        h["Referer"] = referer
    return h

# ── Delay profiles theo domain ────────────────────────────────────────────────
_DELAY_PROFILES: dict[str, tuple[float, float]] = {
    "royalroad.com"       : (6.0, 14.0),
    "www.royalroad.com"   : (6.0, 14.0),
    "scribblehub.com"     : (4.0, 10.0),
    "www.scribblehub.com" : (4.0, 10.0),
    "wattpad.com"         : (3.0,  8.0),
    "www.wattpad.com"     : (3.0,  8.0),
    "fanfiction.net"      : (2.0,  6.0),
    "www.fanfiction.net"  : (2.0,  6.0),
    "archiveofourown.org" : (2.0,  5.0),
    "www.webnovel.com"    : (3.0,  7.0),
}
_DEFAULT_DELAY = (1.0, 3.0)

def get_delay(url: str) -> float:
    domain = urlparse(url).netloc.lower()
    lo, hi = _DELAY_PROFILES.get(domain, _DEFAULT_DELAY)
    return random.uniform(lo, hi)

# ── Fallback selectors (trước khi có profile) ─────────────────────────────────
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

# Known noise selectors — luôn removed trong html_filter TRƯỚC profile selectors.
# Site-agnostic safety net: catch những elements không bao giờ là chapter content.
KNOWN_NOISE_SELECTORS: list[str] = [
    # FanFiction.net
    "#profile_top",            # Story metadata box (author, stats, ratings)
    "#pre_story_links",        # Breadcrumb navigation above story
    
    # Royal Road
    ".author-note-portlet",    # Author sidebar widget
    ".portlet.blog-post",      # Author blog posts in sidebar
    ".comment-container",      # Comment section container
    ".comments-list",          # Comments list
    ".reading-settings",       # Reading settings panel (popover)
    "#settings-popover",       # Settings popover (ID variant)
    
    # ScribbleHub / generic
    ".chapter-comments",
    "#chapter-comments",
    ".author-bio-box",
    "[class='reading-options']",
]
# ── Regex compile sẵn ────────────────────────────────────────────────────────
RE_CHAP_URL = re.compile(
    r"(?:chapter|chuong|chap)[_\-/]?\d+"          # /chapter1, /chapter-1, /chapter/1
    r"|/ch?[/_-]\d+"
    r"|(?:episode|ep|part)[_\-/]?\d+"
    r"|/s/\d+/\d+"
    r"|/txt/\d+/\d+",                             # v1.0.24: 69shuba /txt/N/N.htm
    re.IGNORECASE,
)

RE_NEXT_BTN = re.compile(
    r"\b(next|tiếp|sau|next\s*chapter|chương\s*tiếp|siguiente)\b"
    # v1.0.24: CJK + KR awareness — Chinese/Japanese/Korean next-button text
    r"|下一[章页節话話节回]"        # 下一章 / 下一页 / 下一節 / 下一话 / 下一回
    r"|下章|下页|下節|下一篇"      # short forms
    r"|次[へのページ章話]"          # JP: 次へ / 次の / 次ページ / 次章 / 次話
    r"|次のページ|つぎへ|つぎのページ"  # JP hiragana
    r"|다음[\s ]*(?:화|장|편|페이지)?",  # KR: 다음 / 다음화 / 다음 화 / 다음장
    re.IGNORECASE | re.UNICODE,
)

RE_CHAP_HREF = re.compile(
    r"/(?:chapter|chuong|chap)[_\-/]?\d+"         # /chapter1, /chapter/1, /chap-1
    r"|/ch?[/_-]\d+"
    r"|/(?:episode|ep|part)[_\-/]?\d+"
    r"|/s/\d+/\d+/"
    r"|/txt/\d+/\d+",                             # v1.0.24: 69shuba
    re.IGNORECASE,
)

RE_CHAP_KW = re.compile(
    r"\b(chapter|chap|chương|episode|ep|part)\b[\s.\-:]*\d+",
    re.IGNORECASE | re.UNICODE,
)

RE_CHAP_SLUG = re.compile(
    r"(.*?(?:chapter|chuong|chap|/c|/ep|episode|part|phan|tap)[s_-]?)(\d+)(/?(?:[?#].*)?)$",
    re.IGNORECASE,
)

RE_FANFIC = re.compile(r"(/s/\d+/)(\d+)(/.+)?$")

# RE_CHAP_HINT: nhận diện chapter keyword có số theo sau (tránh false positive)
RE_CHAP_HINT = re.compile(
    r"\b(?:chapter|chap|episode|ep|part)\s+\d+",
    re.IGNORECASE,
)