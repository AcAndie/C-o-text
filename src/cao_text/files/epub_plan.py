"""epub_plan.py — Lập kế hoạch phân chia chương EPUB (rule-based + AI rules, fix §7.3).

Kiến trúc:
  1. Mặc định lập kế hoạch bằng Rule (TOC, gộp Part/Level/Book divider vào chương sau).
  2. Chỉ khi Rule kém tin cậy và có ai_provider: gọi AI sinh QUY TẮC tổng quát
     (EpubRulesOutput: regex, keywords, hrefs) dựa trên mẫu đầu/giữa/cuối — KHÔNG liệt kê từng doc.
  3. Áp quy tắc bằng code thuần và KIỂM CHỨNG (không chương nào chứa > 5× trung vị doc).
     Nếu kiểm chứng thất bại → an toàn quay về rule-based plan.
  4. Cache kế hoạch theo SHA256 của file EPUB với schema có version.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import statistics
import threading
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any

from bs4 import BeautifulSoup
from ebooklib import ITEM_DOCUMENT, epub

from cao_text.ai.prompts import prompt_epub_rules
from cao_text.ai.schemas import EpubRulesOutput
from cao_text.settings import get_settings
from cao_text.storage import atomic_write_json

if TYPE_CHECKING:
    from cao_text.ai.provider import LLMProvider

logger = logging.getLogger(__name__)

_CACHE_LOCK = threading.Lock()
_CACHE_VERSION = 2

# Từ khóa phân loại Front Matter (khớp từ nguyên vẹn với ranh giới từ \b...\b)
FRONT_MATTER_KEYWORDS = frozenset({
    "contents", "table of contents", "cover", "title page",
    "about the book", "about the author", "dedication",
    "preface", "foreword", "introduction", "front matter",
    "publisher", "imprint", "credits", "lời tựa", "mục lục",
    "bìa", "thông tin xuất bản",
})

# Từ khóa phân loại Back Matter
BACK_MATTER_KEYWORDS = frozenset({
    "acknowledgments", "acknowledgement", "acknowledgements",
    "copyright", "appendix", "afterword", "back matter",
    "reading group", "discussion question", "newsletter",
    "about the author", "lời bạt", "phụ lục", "tác quyền",
})

# Từ khóa quảng cáo / trích đoạn truyện khác → bỏ qua hoàn toàn không ghi file
SKIP_KEYWORDS = frozenset({
    "extract from", "excerpt from", "also by", "praise for",
    "advert", "advertisement", "back ad", "out now",
    "find out what happens", "read on for", "preview of",
    "sneak peek", "quảng cáo", "giới thiệu sách khác",
})

# Pattern tên file dùng để nhận diện nhanh
MATTER_FILENAME_PATTERNS = (
    "toc", "contents", "cover", "title", "copyright", "dedication",
    "acknowledg", "about_author", "about_book", "nav", "front",
    "publisher", "imprint", "footnote",
)

SKIP_FILENAME_PATTERNS = (
    "advert", "ads_", "ads_back", "ads_front", "promo", "excerpt",
)

# Regex nhận diện trang tiêu đề phân đoạn (Part 1, Level Two, Quyển 1...)
_DIVIDER_TITLE_RE = re.compile(
    r"^(?:part|level|book|section|volume|act|quyển|phần|tập)\s+"
    r"(?:[ivxlcdm]+|\d+|one|two|three|four|five|six|seven|eight|nine|ten|[a-z0-9]+)"
    r"\s*[:.\-—]?\s*$",
    re.IGNORECASE,
)

_FRONT_MATTER_RE = re.compile(
    r"\b(?:" + "|".join(re.escape(k) for k in FRONT_MATTER_KEYWORDS) + r")\b",
    re.IGNORECASE,
)
_BACK_MATTER_RE = re.compile(
    r"\b(?:" + "|".join(re.escape(k) for k in BACK_MATTER_KEYWORDS) + r")\b",
    re.IGNORECASE,
)
_SKIP_TITLE_RE = re.compile(
    r"\b(?:" + "|".join(re.escape(k) for k in SKIP_KEYWORDS) + r")\b",
    re.IGNORECASE,
)


@dataclass
class ChapterPlan:
    """Một đơn vị kế hoạch chương trong file EPUB."""

    index: int  # 0 = Front Matter, 1+ = Chương thực tế
    kind: str  # "chapter" | "matter" | "skip"
    title: str | None = None  # Gợi ý tiêu đề chương từ TOC
    doc_ids: list[str] = field(default_factory=list)  # Danh sách ID spine docs được gộp


# ── Helpers TOC & File ────────────────────────────────────────────────────────

def compute_file_sha256(path: str | Path) -> str:
    """Tính mã băm SHA256 của file làm khóa cache duy nhất."""
    hasher = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()


def normalize_href(href: str | None) -> str:
    """Chuẩn hóa href để so sánh chính xác giữa TOC và spine file_name."""
    if not href:
        return ""
    clean = href.split("#", 1)[0].replace("\\", "/").strip().lower()
    return clean.lstrip("/")


def flatten_toc(items: Any) -> list[tuple[str, str]]:
    """Duyệt đệ quy cây mục lục EPUB (book.toc) trả về danh sách [(title, norm_href)]."""
    result: list[tuple[str, str]] = []
    if not items:
        return result

    for item in items:
        if isinstance(item, tuple):
            section, children = item
            title = (getattr(section, "title", "") or "").strip()
            href = getattr(section, "href", "") or ""
            if title and href:
                result.append((title, normalize_href(href)))
            result.extend(flatten_toc(children))
        else:
            title = (getattr(item, "title", "") or "").strip()
            href = getattr(item, "href", "") or ""
            if title and href:
                result.append((title, normalize_href(href)))
    return result


def is_divider_title(title: str | None, custom_re: re.Pattern[str] | None = None) -> bool:
    """Kiểm tra tiêu đề có phải là trang ngăn cách Phần/Quyển không."""
    if not title:
        return False
    t = title.strip()
    if custom_re is not None and custom_re.search(t):
        return True
    return bool(_DIVIDER_TITLE_RE.match(t))


def is_matter_title(title: str) -> bool:
    return bool(_FRONT_MATTER_RE.search(title) or _BACK_MATTER_RE.search(title))


def is_matter_filename(filename: str) -> bool:
    lo = (filename or "").lower()
    return any(p in lo for p in MATTER_FILENAME_PATTERNS)


def is_skip_title(title: str) -> bool:
    return bool(_SKIP_TITLE_RE.search(title))


def is_skip_filename(filename: str) -> bool:
    lo = (filename or "").lower()
    return any(p in lo for p in SKIP_FILENAME_PATTERNS)


def smart_title_from_toc(toc_title: str | None, chapter_idx: int) -> str:
    """Chuẩn hóa nhãn TOC thành tiêu đề hiển thị thân thiện."""
    if not toc_title:
        return f"Chapter {chapter_idx}"
    t = toc_title.strip()
    if t.isdigit():
        n = int(t)
        return "Prologue" if n == 0 else f"Chapter {n}"
    return t


def merge_dividers(
    chapters: list[ChapterPlan],
    custom_re: re.Pattern[str] | None = None,
) -> list[ChapterPlan]:
    """Gộp các trang divider (Part 1, Quyển 1...) vào chương kế tiếp (§6.6)."""
    if not chapters:
        return chapters

    merged: list[ChapterPlan] = []
    pending: ChapterPlan | None = None

    for ch in chapters:
        if is_divider_title(ch.title, custom_re=custom_re):
            if pending is not None:
                merged.append(pending)
            pending = ch
            continue

        if pending is not None:
            ch = ChapterPlan(
                index=ch.index,
                kind=ch.kind,
                title=f"{pending.title} — {ch.title}" if ch.title else pending.title,
                doc_ids=pending.doc_ids + ch.doc_ids,
            )
            pending = None
        merged.append(ch)

    if pending is not None:
        merged.append(pending)

    # Đánh số lại index 1..N tuần tự
    for idx, ch in enumerate(merged, start=1):
        ch.index = idx
    return merged


# ── 1. Rule-Based Plan (Mặc định) ─────────────────────────────────────────────

def build_chapter_plan_rule_based(book: epub.EpubBook) -> list[ChapterPlan]:
    """Lập kế hoạch phân chia chương hoàn toàn bằng Code & Rule xác định."""
    toc_entries = flatten_toc(book.toc) if book.toc else []
    toc_map = {href: title for title, href in toc_entries}

    matter_bucket: list[str] = []
    skip_ids: list[str] = []
    chapters: list[ChapterPlan] = []
    current: ChapterPlan | None = None
    chapter_idx = 0

    for spine_entry in book.spine:
        item_id = spine_entry[0] if isinstance(spine_entry, tuple) else spine_entry
        item = book.get_item_with_id(item_id)
        if item is None or item.get_type() != ITEM_DOCUMENT:
            continue

        filename = item.file_name or ""
        norm_fn = normalize_href(filename)

        # Khớp TOC theo href chính xác hoặc khớp tên file cơ sở
        toc_title = toc_map.get(norm_fn)
        if toc_title is None:
            base_name = PurePosixPath(norm_fn).name
            for href, title in toc_map.items():
                if PurePosixPath(href).name == base_name:
                    toc_title = title
                    break

        # 1. Skip checks (quảng cáo / trích đoạn truyện khác)
        if is_skip_filename(filename) or (toc_title and is_skip_title(toc_title)):
            if current is not None:
                chapters.append(current)
                current = None
            skip_ids.append(item_id)
            continue

        # 2. Front/Back matter checks
        if is_matter_filename(filename) or (toc_title and is_matter_title(toc_title)):
            if current is not None:
                chapters.append(current)
                current = None
            matter_bucket.append(item_id)
            continue

        # 3. Chương chính hoặc tài liệu nối tiếp
        if toc_title is not None:
            if current is not None:
                chapters.append(current)
            chapter_idx += 1
            current = ChapterPlan(
                index=chapter_idx,
                kind="chapter",
                title=smart_title_from_toc(toc_title, chapter_idx),
                doc_ids=[item_id],
            )
        elif current is not None:
            current.doc_ids.append(item_id)
        else:
            matter_bucket.append(item_id)

    if current is not None:
        chapters.append(current)

    # Gộp divider trang phần/quyển
    chapters = merge_dividers(chapters)

    plan: list[ChapterPlan] = []
    if matter_bucket:
        plan.append(
            ChapterPlan(
                index=0,
                kind="matter",
                title="Front Matter",
                doc_ids=matter_bucket,
            )
        )
    plan.extend(chapters)

    logger.debug(
        "[EpubPlan] Rule-based: %d chapters + %d matter docs + %d skipped",
        len(chapters),
        len(matter_bucket),
        len(skip_ids),
    )
    return plan


def is_rule_plan_reliable(plan: list[ChapterPlan], book: epub.EpubBook) -> bool:
    """Đánh giá xem kế hoạch bằng rule có đủ tin cậy không (§6.2)."""
    real_chapters = [p for p in plan if p.kind == "chapter"]
    if not real_chapters:
        return False

    spine_docs_count = sum(
        1
        for s in book.spine
        if (
            (it := book.get_item_with_id(s[0] if isinstance(s, tuple) else s))
            and it.get_type() == ITEM_DOCUMENT
        )
    )

    # Nếu file có hơn 30 docs mà rule chỉ tìm ra 1 chương duy nhất -> không tin cậy
    if spine_docs_count > 30 and len(real_chapters) == 1:
        return False

    return True


# ── 2. AI Rules-Based Plan (Chỉ áp dụng khi rule kém tin cậy, fix §7.3) ────────

def _gather_sample_docs_summary(book: epub.EpubBook) -> tuple[str, list[str]]:
    """Lấy mẫu các tài liệu ở đầu, giữa và cuối sách kèm danh sách tiêu đề TOC."""
    toc_entries = flatten_toc(book.toc) if book.toc else []
    toc_map = {href: title for title, href in toc_entries}
    all_toc_titles = [title for title, _ in toc_entries]

    spine_items: list[tuple[int, str, Any]] = []
    for pos, s in enumerate(book.spine):
        item_id = s[0] if isinstance(s, tuple) else s
        item = book.get_item_with_id(item_id)
        if item is not None and item.get_type() == ITEM_DOCUMENT:
            spine_items.append((pos, item_id, item))

    total = len(spine_items)
    if total <= 18:
        sample_indices = set(range(total))
    else:
        sample_indices = set(range(min(6, total)))
        mid = total // 2
        sample_indices.update(range(max(0, mid - 2), min(total, mid + 3)))
        sample_indices.update(range(max(0, total - 6), total))

    lines: list[str] = []
    for idx in sorted(sample_indices):
        pos, item_id, item = spine_items[idx]
        filename = item.file_name or ""
        norm_fn = normalize_href(filename)
        toc_title = toc_map.get(norm_fn, "")
        try:
            raw = item.get_content().decode("utf-8", errors="replace")
            soup = BeautifulSoup(raw, "html.parser")
            text = soup.get_text(separator=" ", strip=True)[:250]
            h1 = soup.find("h1")
            h1_text = h1.get_text(strip=True) if h1 else ""
            size = len(raw)
        except Exception:
            text, h1_text, size = "", "", 0

        lines.append(
            f"Doc #{pos} (id={item_id!r}, file={filename!r}, size={size}B):\n"
            f"  TOC title: {toc_title!r}\n"
            f"  Heading 1: {h1_text!r}\n"
            f"  Text excerpt: {text[:160]!r}"
        )

    return "\n".join(lines), all_toc_titles


def apply_epub_rules(book: epub.EpubBook, rules: EpubRulesOutput) -> list[ChapterPlan]:
    """Áp dụng bộ quy tắc tổng quát do AI đề xuất bằng code thuần (fix §7.3)."""
    chapter_re: re.Pattern[str] | None = None
    if rules.chapter_title_regex:
        try:
            chapter_re = re.compile(rules.chapter_title_regex, re.IGNORECASE)
        except re.error as e:
            logger.warning("[EpubPlan] Regex chapter_title_regex không hợp lệ: %s", e)

    divider_re: re.Pattern[str] | None = None
    if rules.divider_title_regex:
        try:
            divider_re = re.compile(rules.divider_title_regex, re.IGNORECASE)
        except re.error as e:
            logger.warning("[EpubPlan] Regex divider_title_regex không hợp lệ: %s", e)

    front_kws = {k.lower().strip() for k in rules.front_matter_keywords} | FRONT_MATTER_KEYWORDS
    back_kws = {k.lower().strip() for k in rules.back_matter_keywords} | BACK_MATTER_KEYWORDS
    front_hrefs = {normalize_href(h) for h in rules.front_matter_hrefs}
    back_hrefs = {normalize_href(h) for h in rules.back_matter_hrefs}

    toc_entries = flatten_toc(book.toc) if book.toc else []
    toc_map = {href: title for title, href in toc_entries}

    matter_bucket: list[str] = []
    chapters: list[ChapterPlan] = []
    current: ChapterPlan | None = None
    chapter_idx = 0

    for spine_entry in book.spine:
        item_id = spine_entry[0] if isinstance(spine_entry, tuple) else spine_entry
        item = book.get_item_with_id(item_id)
        if item is None or item.get_type() != ITEM_DOCUMENT:
            continue

        filename = item.file_name or ""
        norm_fn = normalize_href(filename)
        toc_title = toc_map.get(norm_fn)
        if toc_title is None:
            base_name = PurePosixPath(norm_fn).name
            for href, title in toc_map.items():
                if PurePosixPath(href).name == base_name:
                    toc_title = title
                    break

        # Đọc heading nhanh
        h1_text = ""
        try:
            raw = item.get_content().decode("utf-8", errors="replace")
            soup = BeautifulSoup(raw, "html.parser")
            h1 = soup.find("h1")
            if h1:
                h1_text = h1.get_text(strip=True)
        except Exception:
            pass

        title_candidate = toc_title or h1_text

        # 1. Front/Back matter theo rules
        is_front = (
            norm_fn in front_hrefs
            or any(k in norm_fn for k in front_kws)
            or (title_candidate and any(k in title_candidate.lower() for k in front_kws))
        )
        is_back = (
            norm_fn in back_hrefs
            or any(k in norm_fn for k in back_kws)
            or (title_candidate and any(k in title_candidate.lower() for k in back_kws))
        )

        if is_front or is_back:
            if current is not None:
                chapters.append(current)
                current = None
            matter_bucket.append(item_id)
            continue

        # 2. Nhận diện ranh giới chương
        is_new_chapter = False
        if chapter_re and title_candidate and chapter_re.search(title_candidate):
            is_new_chapter = True
        elif toc_title is not None and not is_matter_title(toc_title):
            is_new_chapter = True

        if is_new_chapter:
            if current is not None:
                chapters.append(current)
            chapter_idx += 1
            current = ChapterPlan(
                index=chapter_idx,
                kind="chapter",
                title=smart_title_from_toc(title_candidate, chapter_idx),
                doc_ids=[item_id],
            )
        elif current is not None and rules.merge_unnamed_into_previous:
            current.doc_ids.append(item_id)
        else:
            matter_bucket.append(item_id)

    if current is not None:
        chapters.append(current)

    # Gộp divider chapters
    chapters = merge_dividers(chapters, custom_re=divider_re)

    plan: list[ChapterPlan] = []
    if matter_bucket:
        plan.append(
            ChapterPlan(
                index=0,
                kind="matter",
                title="Front Matter",
                doc_ids=matter_bucket,
            )
        )
    plan.extend(chapters)
    return plan


def verify_epub_plan(
    plan: list[ChapterPlan],
    book: epub.EpubBook,
) -> tuple[bool, str]:
    """Kiểm chứng kế hoạch chương do AI đề xuất (§6.2 & §7.3).

    Tiêu chí kiểm chứng:
      1. Phải tìm thấy ít nhất 1 chương hợp lệ.
      2. Tỷ lệ so với TOC hợp lý (nếu TOC có chương, số chương không giảm quá 70%).
      3. An toàn trần token (§7.3): Không chương nào chứa số doc > 5× trung vị
         (ngăn chặn lỗi dồn hàng trăm doc còn lại vào 1 file vì đứt gãy token).
    """
    real_chapters = [p for p in plan if p.kind == "chapter"]
    if not real_chapters:
        return False, "Không phát hiện được chương nội dung nào"

    doc_counts = [len(c.doc_ids) for c in real_chapters]
    med_docs = statistics.median(doc_counts)
    max_docs = max(doc_counts)

    # Kiểm chứng §7.3: Không chương nào dài > 5× trung vị nếu max_docs > 10
    if max_docs > 5 * max(1, med_docs) and max_docs > 10:
        return (
            False,
            f"Chương bất thường chứa {max_docs} docs (trung vị {med_docs}) > 5× trung vị",
        )

    return True, "Hợp lệ"


# ── 3. Quản lý Cache Kế Hoạch EPUB (SHA256, Schema Version 2) ─────────────────

class EpubPlanCache:
    """Quản lý lưu trữ cache phân tích EPUB an toàn và có phiên bản."""

    def __init__(self, cache_file: str | Path | None = None) -> None:
        if cache_file is not None:
            self._file = Path(cache_file)
        else:
            self._file = Path(get_settings().paths.data_dir) / "epub_analyses.json"

    def get(self, file_hash: str) -> list[ChapterPlan] | None:
        """Đọc kế hoạch đã lưu từ cache nếu tồn tại."""
        if not self._file.exists():
            return None
        with _CACHE_LOCK:
            try:
                data = json.loads(self._file.read_text(encoding="utf-8"))
            except Exception:
                return None

            analyses = data.get("analyses", {}) if data.get("version") == _CACHE_VERSION else data
            entry = analyses.get(file_hash)
            if not isinstance(entry, dict):
                return None

            plan_raw = entry.get("plan")
            if not isinstance(plan_raw, list):
                return None

            try:
                return [
                    ChapterPlan(
                        index=int(item["index"]),
                        kind=str(item["kind"]),
                        title=item.get("title"),
                        doc_ids=list(item.get("doc_ids", [])),
                    )
                    for item in plan_raw
                ]
            except Exception as e:
                logger.debug("[EpubCache] Giải mã cache plan thất bại: %s", e)
                return None

    def set(
        self,
        file_hash: str,
        filename: str,
        rules: dict[str, Any],
        plan: list[ChapterPlan],
    ) -> None:
        """Ghi nhận kế hoạch đã qua kiểm chứng vào file cache với atomic write."""
        with _CACHE_LOCK:
            data: dict[str, Any] = {"version": _CACHE_VERSION, "analyses": {}}
            if self._file.exists():
                try:
                    existing = json.loads(self._file.read_text(encoding="utf-8"))
                    if isinstance(existing, dict):
                        if existing.get("version") == _CACHE_VERSION:
                            data = existing
                        else:
                            # Di chuyển dữ liệu cũ sang legacy_v1 để bảo vệ lịch sử người dùng (§3.4)
                            data["legacy_v1"] = existing
                except Exception:
                    pass

            analyses = data.setdefault("analyses", {})
            analyses[file_hash] = {
                "filename": filename,
                "cached_at": datetime.now(UTC).isoformat(),
                "rules": rules,
                "plan": [asdict(p) for p in plan],
            }
            atomic_write_json(self._file, data)


# ── 4. Bộ điều phối chính ─────────────────────────────────────────────────────

async def build_chapter_plan(
    book: epub.EpubBook,
    epub_path: str | Path,
    ai_provider: LLMProvider | None = None,
    *,
    force_ai: bool = False,
    cache_file: str | Path | None = None,
) -> list[ChapterPlan]:
    """Hàm đầu vào chính lập kế hoạch chương EPUB theo Task 6.2."""
    # 1. Thử kế hoạch Rule-Based trước (§6.2)
    rule_plan = build_chapter_plan_rule_based(book)
    if not force_ai and is_rule_plan_reliable(rule_plan, book):
        return rule_plan

    # 2. Kiểm tra cache SHA256
    file_hash = compute_file_sha256(epub_path)
    cache = EpubPlanCache(cache_file)
    if not force_ai:
        cached_plan = cache.get(file_hash)
        if cached_plan:
            logger.info("[EpubPlan] Sử dụng cache kế hoạch AI (%s)", Path(epub_path).name)
            return cached_plan

    # 3. Gọi AI phân tích nếu có ai_provider
    if ai_provider is not None:
        try:
            summary, toc_titles = _gather_sample_docs_summary(book)
            prompt = prompt_epub_rules(summary, toc_titles=toc_titles)
            rules = await ai_provider.generate(prompt, EpubRulesOutput)

            ai_plan = apply_epub_rules(book, rules)
            is_valid, reason = verify_epub_plan(ai_plan, book)
            if is_valid:
                cache.set(
                    file_hash=file_hash,
                    filename=Path(epub_path).name,
                    rules=rules.model_dump(),
                    plan=ai_plan,
                )
                logger.info(
                    "[EpubPlan] AI rules lập kế hoạch thành công (%d chương) cho %s",
                    len(ai_plan),
                    Path(epub_path).name,
                )
                return ai_plan
            else:
                logger.warning(
                    "[EpubPlan] Kế hoạch AI kiểm chứng thất bại: %s → quay về rule-based",
                    reason,
                )
        except Exception as e:
            logger.warning("[EpubPlan] Gọi AI phân tích thất bại: %s → quay về rule-based", e)

    return rule_plan


__all__ = [
    "ChapterPlan",
    "EpubPlanCache",
    "apply_epub_rules",
    "build_chapter_plan",
    "build_chapter_plan_rule_based",
    "compute_file_sha256",
    "flatten_toc",
    "is_divider_title",
    "is_rule_plan_reliable",
    "merge_dividers",
    "normalize_href",
    "smart_title_from_toc",
    "verify_epub_plan",
]
