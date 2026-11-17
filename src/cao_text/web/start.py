"""start.py — Phân loại URL (index/chapter) và tìm URL chương 1 (Task 4.4).

Chức năng:
1. Phân loại URL:
   - Cache tại `data/url_classifications.json`. Nếu cache hit với confidence >= 0.7 -> dùng ngay, 0 tốn AI/mạng.
   - Fast-path Webnovel: trích book_id, ID chương nhỏ nhất = chương 1 (confidence=0.99, bỏ qua AI).
   - Heuristic code-first: phát hiện nhanh chapter hoặc tìm nút "Start Reading" / "Chapter 1" trên trang index.
   - AI classify: skeleton + danh sách link -> PageClassificationOutput.
2. Tìm chương 1:
   - `resolve_start_url(url)`: nếu là index -> trả về first_chapter_url, nếu là chapter -> giữ nguyên.
3. Metadata helpers:
   - `extract_story_title`: trích tên truyện sạch từ raw <title>.
   - `build_story_id_regex`: tạo regex lock ID truyện để tránh drift sang truyện khác.
   - `is_chapter_url`: kiểm tra xem URL có phải chương không (theo profile pattern hoặc RE_CHAP_URL).
   - `story_id_ok`: kiểm tra URL có thuộc đúng story_id đã lock không.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from cao_text.ai.prompts import prompt_classify_page
from cao_text.ai.provider import LLMProvider
from cao_text.ai.schemas import PageClassificationOutput
from cao_text.ai.skeleton import compress_dom_to_skeleton
from cao_text.extract.nav import RE_CHAP_KW, RE_CHAP_URL, detect_page_type
from cao_text.models import SiteProfile
from cao_text.net.http import DomainSessionPool, fetch_page
from cao_text.settings import get_settings
from cao_text.storage import atomic_write_json

logger = logging.getLogger(__name__)

# Ngưỡng tin cậy tối thiểu để sử dụng kết quả đã cache
MIN_CACHE_CONFIDENCE = 0.7

# Fast-path Webnovel: book ID có >= 10 chữ số, chapter ID cũng >= 10 chữ số
_WEBNOVEL_BOOK_RE = re.compile(r"^/book/(\d{10,})(?:/(\d{10,}))?/?$")

# Tên các website truyện phổ biến (dùng để lọc bỏ khi trích xuất story title)
_KNOWN_SITES = frozenset({
    "royalroad", "royal road", "scribblehub", "wattpad", "fanfiction",
    "fanfiction.net", "archiveofourown", "ao3", "webnovel", "novelfire",
    "novelupdates", "lightnovelreader", "novelfull", "wuxiaworld",
    "truyenfull", "truyenfull.vn", "tangthuvien", "metruyenchu",
})

# Pattern nhận dạng tiêu đề chương trong title tag
_CHAPTER_TITLE_RE = re.compile(
    r"^\s*(?:chapter|chap|ch|episode|ep|part|chuong|chương|phan|phần)\b[\s.\-:]*\d*",
    re.IGNORECASE | re.UNICODE,
)

# Pattern nút đọc chương đầu trên trang mục lục
_START_READING_BTN_RE = re.compile(
    r"^(?:start reading|read from (?:the )?beginning|read now|read first|chương 1\b|chapter 1\b|đọc từ đầu)",
    re.IGNORECASE | re.UNICODE,
)


# ── Story Metadata Helpers ───────────────────────────────────────────────────

def extract_story_title(raw_page_title: str) -> str | None:
    """Lấy tên truyện từ thẻ <title> của trang bằng heuristic cắt delimiter (| - —).

    Loại bỏ:
    - Phần quá ngắn (< 3 ký tự).
    - Các mẫu tiêu đề chương ("Chapter 5", "Chương 12", v.v.).
    - Tên trang web đã biết ("Royal Road", "Webnovel", v.v.).
    Chọn ứng viên dài nhất còn lại.
    """
    if not raw_page_title:
        return None

    parts = re.split(r"\s*[\|–—\-]\s*", raw_page_title)
    candidates: list[str] = []
    for part in parts:
        cleaned = part.strip()
        if len(cleaned) < 3:
            continue
        if _CHAPTER_TITLE_RE.match(cleaned):
            continue
        if cleaned.lower() in _KNOWN_SITES:
            continue
        candidates.append(cleaned)

    return max(candidates, key=len) if candidates else None


def build_story_id_regex(url: str) -> str | None:
    """Tạo regex pattern để khóa (guard) story ID, chống scraper nhảy sang truyện khác.

    Logic:
    - fanfiction.net: `/s/{story_id}/`
    - ScribbleHub: `/read/{id}-{slug}/` -> khóa tới `/read/{id}`
    - RoyalRoad / generic: segment số đầu tiên trong path -> `/prefix/{id}/`
    """
    try:
        path = urlparse(url).path
        segments = [s for s in path.split("/") if s]
        if not segments:
            return None

        # Fanfiction.net pattern: /s/{id}/{chapter_num}/{slug}
        if len(segments) >= 3 and segments[0] == "s" and segments[1].isdigit():
            return re.escape(f"/s/{segments[1]}/")

        # Generic pattern: duyệt qua các segment
        for i, seg in enumerate(segments):
            if i == 0:
                continue

            # Ưu tiên 1: {id}-{slug} (vd: ScribbleHub 1539267-the-quantum-wanderer)
            m = re.match(r"^(\d+)-", seg)
            if m:
                story_path = "/" + "/".join(segments[:i]) + "/" + m.group(1)
                return re.escape(story_path)

            # Ưu tiên 2: segment thuần số (vd: RoyalRoad /fiction/55418/)
            if seg.isdigit():
                story_path = "/" + "/".join(segments[: i + 1]) + "/"
                return re.escape(story_path)
    except Exception as e:
        logger.debug("Không thể tạo story_id_regex cho %s: %s", url, e)

    return None


def is_chapter_url(url: str, profile: SiteProfile | None = None) -> bool:
    """Kiểm tra URL có phải là URL chương truyện không.

    Ưu tiên chapter_url_pattern từ profile nếu có, fallback về RE_CHAP_URL heuristic.
    """
    if profile and profile.chapter_url_pattern:
        try:
            if re.search(profile.chapter_url_pattern, url, re.IGNORECASE):
                return True
        except re.error:
            pass

    return bool(RE_CHAP_URL.search(url))


def story_id_ok(url: str, story_id_regex: str | None) -> bool:
    """Kiểm tra URL có thuộc đúng bộ truyện đang cào không theo regex đã khóa."""
    if not story_id_regex:
        return True
    try:
        return bool(re.search(story_id_regex, url))
    except re.error:
        return True


# ── Classification Cache Store ────────────────────────────────────────────────

class ClassificationStore:
    """Quản lý đọc/ghi bộ nhớ đệm phân loại URL từ file data/url_classifications.json."""

    def __init__(self, cache_file: Path | str | None = None) -> None:
        self.cache_file = (
            Path(cache_file)
            if cache_file
            else Path(get_settings().url_classifications_file)
        )
        self._lock = asyncio.Lock()
        self._cache: dict[str, dict[str, Any]] | None = None

    async def get(self, url: str) -> PageClassificationOutput | None:
        """Lấy kết quả phân loại đã cache nếu có và confidence >= MIN_CACHE_CONFIDENCE."""
        async with self._lock:
            cache = await self._ensure_cache()
            raw = cache.get(url)
            if not raw:
                return None
            conf = raw.get("confidence", 0.0)
            if conf >= MIN_CACHE_CONFIDENCE:
                try:
                    return PageClassificationOutput.model_validate(raw)
                except Exception as e:
                    logger.debug("Parse cached classification thất bại: %s", e)
                    return None
            return None

    async def set(self, url: str, result: PageClassificationOutput) -> None:
        """Ghi nhận kết quả phân loại vào cache và lưu đĩa."""
        async with self._lock:
            cache = await self._ensure_cache()
            data = result.model_dump()
            data["classified_at"] = datetime.now(UTC).isoformat()
            cache[url] = data
            await asyncio.to_thread(atomic_write_json, self.cache_file, cache)

    async def _ensure_cache(self) -> dict[str, dict[str, Any]]:
        if self._cache is not None:
            return self._cache
        if not self.cache_file.exists():
            self._cache = {}
            return self._cache

        def _read() -> dict[str, dict[str, Any]]:
            try:
                raw_text = self.cache_file.read_text(encoding="utf-8")
                loaded = json.loads(raw_text)
                return loaded if isinstance(loaded, dict) else {}
            except Exception as e:
                logger.warning("Không thể đọc cache phân loại URL %s: %s", self.cache_file, e)
                return {}

        self._cache = await asyncio.to_thread(_read)
        return self._cache


# ── Fetch Helper & Webnovel Fast-Path ────────────────────────────────────────

async def _fetch_html(
    url: str,
    pool: Any,
    pw_pool: Any = None,
) -> tuple[int, str]:
    """Tải HTML qua fetch_page (hỗ trợ Cloudflare fallback sang pw_pool) hoặc pool.fetch."""
    if hasattr(pool, "is_cf_domain"):
        return await fetch_page(url, pool, pw_pool=pw_pool)
    res = await pool.fetch(url)
    if isinstance(res, tuple) and len(res) == 2:
        return int(res[0]), str(res[1] or "")
    status = getattr(res, "status_code", 200)
    text = getattr(res, "text", "") or ""
    return int(status), str(text)


async def _resolve_webnovel_fastpath(
    url: str,
    pool: DomainSessionPool | None,
    pw_pool: Any = None,
    prefetched_html: str | None = None,
) -> PageClassificationOutput | None:
    """Fast-path cho Webnovel.com: ID chương là số nguyên tăng dần -> ID nhỏ nhất là chương 1.

    Hoạt động với cả URL mục lục truyện (/book/N) và URL chương bất kỳ (/book/N/M).
    Bỏ qua AI call, độ tin cậy 0.99.
    """
    parsed = urlparse(url)
    if "webnovel.com" not in parsed.netloc.lower():
        return None

    m = _WEBNOVEL_BOOK_RE.match(parsed.path)
    if not m:
        return None

    book_id = m.group(1)
    is_chapter_path = bool(m.group(2))
    book_url = f"https://www.webnovel.com/book/{book_id}"

    html: str | None = prefetched_html
    ids: list[str] = []
    if html:
        ids = re.findall(rf"/book/{book_id}/(\d{{10,}})", html)

    # Nếu chưa có HTML hoặc HTML prefetched không có IDs -> fetch trang book_url
    if not ids and pool is not None:
        try:
            status, fetched_html = await _fetch_html(book_url, pool, pw_pool=pw_pool)
            if status < 400 and fetched_html:
                html = fetched_html
                ids = re.findall(rf"/book/{book_id}/(\d{{10,}})", html)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning("[Webnovel] Fetch book index %s thất bại: %s", book_url, e)

    if not ids or not html:
        return None

    smallest = min(int(x) for x in ids)
    first_chapter_url = f"https://www.webnovel.com/book/{book_id}/{smallest}"

    # Lấy story title nếu có
    soup = BeautifulSoup(html, "lxml")
    story_title = extract_story_title(soup.title.string if soup.title else "")

    return PageClassificationOutput(
        page_type="chapter" if is_chapter_path else "index",
        story_title=story_title,
        first_chapter_url=first_chapter_url,
        confidence=0.99,
        reasoning="Webnovel fast-path: numeric chapter ID sort (smallest ID = chapter 1)",
    )


# ── Code-First Heuristic Classifier ──────────────────────────────────────────

def _classify_heuristic(
    url: str,
    soup: BeautifulSoup,
) -> PageClassificationOutput | None:
    """Heuristic phân loại trang bằng code thuần trước khi quyết định gọi AI.

    Trả về PageClassificationOutput nếu nhận diện chắc chắn, hoặc None nếu cần AI.
    """
    p_type = detect_page_type(soup, url)

    # 1. Nếu chắc chắn là chapter:
    if p_type == "chapter":
        # Trích xuất tiêu đề
        h1 = soup.find("h1")
        ch_title = h1.get_text(strip=True) if h1 else None
        st_title = extract_story_title(soup.title.string if soup.title else "")
        return PageClassificationOutput(
            page_type="chapter",
            story_title=st_title,
            chapter_title=ch_title,
            confidence=0.85,
            reasoning="Code heuristic: URL match RE_CHAP_URL or chapter heading detected",
        )

    # 2. Nếu là trang index / mục lục: tìm link chương 1
    if p_type == "index":
        first_url: str | None = None

        # Tìm nút "Start Reading", "Read Now", "Chapter 1"
        for a in soup.find_all("a", href=True):
            text = a.get_text(strip=True)
            if _START_READING_BTN_RE.search(text):
                first_url = urljoin(url, a["href"])
                break

        # Nếu không có nút cụ thể, tìm link chương đầu tiên trong bảng/danh sách
        if not first_url:
            for a in soup.find_all("a", href=True):
                href = a["href"]
                full_href = urljoin(url, href)
                text = a.get_text(strip=True)
                if RE_CHAP_URL.search(href) or RE_CHAP_KW.search(text):
                    first_url = full_href
                    break

        st_title = extract_story_title(soup.title.string if soup.title else "")
        if first_url:
            return PageClassificationOutput(
                page_type="index",
                story_title=st_title,
                first_chapter_url=first_url,
                confidence=0.85,
                reasoning="Code heuristic: index page detected with start reading link",
            )

    return None


# ── Public API ───────────────────────────────────────────────────────────────

async def classify_url(
    url: str,
    *,
    pool: DomainSessionPool | None = None,
    pw_pool: Any = None,
    ai_provider: LLMProvider | None = None,
    prefetched_html: str | None = None,
    cache_store: ClassificationStore | None = None,
    force: bool = False,
) -> PageClassificationOutput:
    """Phân loại URL (index/chapter/unknown) và tìm URL chương 1.

    Quy trình:
    1. Kiểm tra cache (nếu không force và confidence >= 0.7) -> trả về ngay.
    2. Fast-path Webnovel (sort ID chương) -> trả về với confidence=0.99.
    3. Lấy HTML (từ prefetched_html hoặc pool).
    4. Heuristic code-first (detect_page_type + tìm nút đọc).
    5. Nếu chưa rõ và có ai_provider -> AI classification (skeleton + link candidates).
    6. Lưu cache và trả về kết quả.
    """
    store = cache_store or ClassificationStore()

    # 1. Cache hit
    if not force:
        cached = await store.get(url)
        if cached:
            logger.info("[URLClassifier] Cache hit: %s (page_type=%s, conf=%.2f)", url, cached.page_type, cached.confidence)
            return cached

    # 2. Fast-path Webnovel
    wn_res = await _resolve_webnovel_fastpath(
        url,
        pool,
        pw_pool=pw_pool,
        prefetched_html=prefetched_html,
    )
    if wn_res:
        logger.info("[URLClassifier] Webnovel fast-path: %s -> ch1=%s", url, wn_res.first_chapter_url)
        await store.set(url, wn_res)
        return wn_res

    # 3. Lấy HTML
    html = prefetched_html
    if html is None and pool is not None:
        try:
            status, fetched_html = await _fetch_html(url, pool, pw_pool=pw_pool)
            if status < 400 and fetched_html:
                html = fetched_html
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning("[URLClassifier] Fetch HTML thất bại cho %s: %s", url, e)

    if not html:
        # Không có HTML để phân tích
        res = PageClassificationOutput(
            page_type="unknown",
            confidence=0.0,
            reasoning="Could not fetch HTML or no content received",
        )
        return res

    soup = BeautifulSoup(html, "lxml")

    # 4. Code-first Heuristic
    heuristic_res = _classify_heuristic(url, soup)
    if heuristic_res and heuristic_res.confidence >= MIN_CACHE_CONFIDENCE:
        logger.info("[URLClassifier] Heuristic classified: %s -> %s", url, heuristic_res.page_type)
        await store.set(url, heuristic_res)
        return heuristic_res

    # 5. AI Classification
    if ai_provider is not None:
        try:
            skeleton = compress_dom_to_skeleton(html)
            # Thu thập tối đa 30 link ứng viên có text liên quan
            candidates: list[str] = []
            for a in soup.find_all("a", href=True):
                text = a.get_text(strip=True)
                full_href = urljoin(url, a["href"])
                if RE_CHAP_URL.search(full_href) or RE_CHAP_KW.search(text) or _START_READING_BTN_RE.search(text):
                    candidates.append(f"{text} -> {full_href}")

            prompt = prompt_classify_page(skeleton, url, candidates[:30])
            ai_out = await ai_provider.generate(prompt, PageClassificationOutput)

            # Chuẩn hóa link first_chapter_url và next_chapter_url
            if ai_out.first_chapter_url:
                ai_out.first_chapter_url = urljoin(url, ai_out.first_chapter_url)
            if ai_out.next_chapter_url:
                ai_out.next_chapter_url = urljoin(url, ai_out.next_chapter_url)

            logger.info("[URLClassifier] AI classified: %s -> %s (conf=%.2f)", url, ai_out.page_type, ai_out.confidence)
            if ai_out.confidence >= MIN_CACHE_CONFIDENCE:
                await store.set(url, ai_out)
            return ai_out
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning("[URLClassifier] AI classify thất bại cho %s: %s", url, e)

    # 6. Fallback nếu không có AI hoặc AI lỗi
    fallback_res = heuristic_res or PageClassificationOutput(
        page_type="unknown",
        confidence=0.4,
        reasoning="Fallback after classification failed",
    )
    return fallback_res


async def resolve_start_url(
    url: str,
    *,
    pool: DomainSessionPool | None = None,
    pw_pool: Any = None,
    ai_provider: LLMProvider | None = None,
    prefetched_html: str | None = None,
    cache_store: ClassificationStore | None = None,
    force: bool = False,
) -> tuple[str, PageClassificationOutput]:
    """Tìm URL khởi đầu chính xác để bắt đầu cào truyện.

    Nếu URL đưa vào là trang index/mục lục và tìm thấy URL chương 1:
        -> Trả về (first_chapter_url, classification).
    Nếu là trang chương hoặc không xác định được:
        -> Trả về (url, classification).
    """
    classification = await classify_url(
        url,
        pool=pool,
        pw_pool=pw_pool,
        ai_provider=ai_provider,
        prefetched_html=prefetched_html,
        cache_store=cache_store,
        force=force,
    )

    if (
        classification.page_type == "index"
        and classification.first_chapter_url
        and classification.first_chapter_url != url
    ):
        logger.info(
            "Phát hiện trang index, chuyển hướng bắt đầu cào từ chương 1: %s",
            classification.first_chapter_url,
        )
        return classification.first_chapter_url, classification

    return url, classification


__all__ = [
    "ClassificationStore",
    "MIN_CACHE_CONFIDENCE",
    "build_story_id_regex",
    "classify_url",
    "extract_story_title",
    "is_chapter_url",
    "resolve_start_url",
    "story_id_ok",
]
