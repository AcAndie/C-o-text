"""txt.py — Đọc file văn bản TXT thành luồng RawDocument với regex & AI pattern (Task 6.3).

Quy trình nhận diện:
  1. Đọc UTF-8 nghiêm ngặt. Nếu lỗi bảng mã → báo lỗi rõ ràng kèm hướng dẫn chuyển đổi (§6.6).
  2. Khớp regex với các mẫu trong txt_cases.json trên 100 dòng đầu. Mẫu có điểm số cao nhất (>= 1) thắng.
  3. Nếu không khớp regex nào: kích hoạt AI fallback (TxtPatternOutput) trên mẫu 50 dòng đầu.
  4. Kiểm chứng AI pattern: chọn 3 đoạn ngẫu nhiên (mỗi đoạn 80 dòng) ở phần giữa file;
     mỗi đoạn phải chứa ít nhất 1 dòng khớp ranh giới chương. Đạt kiểm chứng → lưu atomic vào DB.
  5. Chia file theo mẫu và đóng gói thành RawDocument HTML.
"""
from __future__ import annotations

import json
import logging
import random
import re
import threading
from collections.abc import AsyncIterator
from pathlib import Path
from typing import TYPE_CHECKING, Any

from cao_text.ai.prompts import prompt_txt_pattern
from cao_text.ai.schemas import TxtPatternOutput
from cao_text.models import RawDocument
from cao_text.storage import atomic_write_json

if TYPE_CHECKING:
    from cao_text.ai.provider import LLMProvider

logger = logging.getLogger(__name__)

# Cấu hình cửa sổ nhận diện và kiểm chứng (§6.3)
_SAMPLE_LINES = 100  # Quét 100 dòng đầu cho regex detection
_AI_SAMPLE_LINES = 50  # 50 dòng đầu gửi cho AI fallback
_AI_VERIFY_CHUNKS = 3  # Số đoạn ngẫu nhiên ở giữa file để kiểm chứng
_AI_VERIFY_CHUNK_SIZE = 80  # Kích thước mỗi đoạn kiểm chứng (dòng)
_AI_LEARNED_CONF = 0.7  # Độ tin cậy mặc định cho pattern AI học

_DB_LOCK = threading.Lock()
_HTML_ESCAPE = str.maketrans({"&": "&amp;", "<": "&lt;", ">": "&gt;"})


# ── 1. DB Pattern (txt_cases.json) ────────────────────────────────────────────

def get_cases_path() -> Path:
    """Xác định đường dẫn file txt_cases.json trong package hoặc data directory."""
    pkg_path = Path(__file__).resolve().parent / "txt_cases.json"
    if pkg_path.exists():
        return pkg_path

    # Fallback kiểm tra data/txt_cases.json
    root_data = Path(__file__).resolve().parents[3] / "data" / "txt_cases.json"
    if root_data.exists():
        return root_data

    return pkg_path


def load_cases(cases_path: Path | None = None) -> list[dict[str, Any]]:
    """Đọc danh sách các mẫu ranh giới chương TXT từ cơ sở dữ liệu."""
    target_path = cases_path or get_cases_path()
    if not target_path.exists():
        logger.warning("[TXT] Không tìm thấy DB pattern tại %s", target_path)
        return []

    with open(target_path, encoding="utf-8") as f:
        data = json.load(f)
    return data.get("cases", [])


def _persist_new_case(
    case: dict[str, Any],
    cases_path: Path | None = None,
) -> None:
    """Lưu mẫu mới do AI học được vào cơ sở dữ liệu txt_cases.json (atomic write)."""
    target_path = cases_path or get_cases_path()
    with _DB_LOCK:
        data: dict[str, Any] = {"version": 1, "cases": []}
        if target_path.exists():
            try:
                with open(target_path, encoding="utf-8") as f:
                    data = json.load(f)
            except Exception as e:
                logger.warning("[TXT] Đọc %s thất bại trước khi append: %s", target_path, e)

        cases = data.setdefault("cases", [])
        if any(c.get("id") == case.get("id") for c in cases):
            logger.info("[TXT] Case id %r đã tồn tại trong DB → bỏ qua ghi", case.get("id"))
            return

        cases.append(case)
        atomic_write_json(target_path, data)
        logger.info("[TXT] Đã lưu mẫu TXT mới %r vào %s", case.get("id"), target_path)


# ── 2. Đọc file UTF-8 với thông báo thân thiện (§6.6) ─────────────────────────

def read_txt_utf8(path: str | Path) -> str:
    """Đọc file TXT với mã hóa UTF-8 nghiêm ngặt.

    Nếu file có bảng mã khác (ANSI, Windows-1258, GBK...), ném lỗi rõ ràng
    kèm hướng dẫn người dùng chuyển đổi.
    """
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except UnicodeDecodeError as e:
        msg = (
            f"File {str(path)!r} không phải định dạng UTF-8 — Cào Text chỉ hỗ trợ UTF-8.\n"
            f"Hướng dẫn chuyển đổi sang UTF-8:\n"
            f"  1. Dùng Notepad mở file, chọn 'Save As' -> Encoding: 'UTF-8' -> Lưu đè.\n"
            f"  2. Hoặc chạy lệnh PowerShell: Get-Content '{path}' | Set-Content '{path}.utf8.txt' -Encoding utf8\n"
            f"  3. Hoặc dùng iconv: iconv -f <encoding-goc> -t utf-8 '{path}' > '{path}.utf8.txt'\n"
            f"Chi tiết kỹ thuật: {e.reason} tại vị trí byte {e.start}-{e.end}."
        )
        raise UnicodeDecodeError(e.encoding, e.object, e.start, e.end, msg) from e


def extract_story_name_from_txt(path: str | Path) -> str:
    """Đọc tiêu đề tác phẩm từ tên file TXT (§6.6)."""
    return Path(path).stem


# ── 3. Nhận diện mẫu bằng Regex ───────────────────────────────────────────────

def _score_case(lines: list[str], pattern: str) -> int:
    """Đếm số dòng ở đầu file khớp với biểu thức chính quy."""
    try:
        rx = re.compile(pattern)
    except re.error as e:
        logger.warning("[TXT] Regex không hợp lệ %r: %s", pattern, e)
        return 0
    return sum(1 for ln in lines if rx.match(ln.strip()))


def detect_pattern_regex(
    text: str,
    cases: list[dict[str, Any]] | None = None,
    sample_lines: int = _SAMPLE_LINES,
) -> dict[str, Any] | None:
    """Chấm điểm các mẫu regex có sẵn trên các dòng đầu file.

    Trả về case có điểm khớp cao nhất (yêu cầu >= 1). Trả về None nếu không khớp.
    """
    if cases is None:
        cases = load_cases()
    if not cases:
        return None

    lines = text.splitlines()[:sample_lines]
    scored = [(case, _score_case(lines, case.get("pattern", ""))) for case in cases]
    scored.sort(key=lambda x: x[1], reverse=True)

    best_case, best_score = scored[0]
    if best_score >= 1:
        logger.debug("[TXT] Khớp regex case %r với điểm số %d", best_case.get("id"), best_score)
        return best_case

    return None


# ── 4. Kiểm chứng AI Pattern (§6.3) ───────────────────────────────────────────

def verify_ai_pattern(
    text: str,
    pattern: str,
    verify_chunks: int = _AI_VERIFY_CHUNKS,
    chunk_size: int = _AI_VERIFY_CHUNK_SIZE,
) -> tuple[bool, str]:
    """Kiểm chứng pattern do AI đề xuất trên các đoạn văn bản ngẫu nhiên ở giữa file.

    Mỗi đoạn văn (80 dòng) phải chứa ít nhất một ranh giới chương.
    Nếu file quá ngắn (< 3 đoạn), chỉ cần kiểm tra toàn bộ file có ít nhất 1 dòng khớp.
    """
    try:
        rx = re.compile(pattern)
    except re.error as e:
        return False, f"Regex không hợp lệ: {e}"

    lines = text.splitlines()
    total_lines = len(lines)

    min_required_lines = verify_chunks * chunk_size
    if total_lines < min_required_lines:
        # File ngắn: kiểm tra xuất hiện ít nhất 1 lần trong toàn file
        matches = sum(1 for ln in lines if rx.match(ln.strip()))
        if matches >= 1:
            return True, f"File ngắn ({total_lines} dòng) chứa {matches} dòng khớp hợp lệ"
        return False, "Không tìm thấy bất kỳ dòng nào khớp mẫu trong toàn bộ file"

    # Chọn verify_chunks đoạn ngẫu nhiên trong khoảng giữa file (bỏ qua 50 dòng đầu)
    start_bound = min(50, total_lines // 4)
    end_bound = max(start_bound + 1, total_lines - chunk_size)

    # Chọn các vị trí mẫu
    available_range = list(range(start_bound, end_bound))
    sample_count = min(verify_chunks, len(available_range))
    positions = sorted(random.sample(available_range, sample_count))

    for pos in positions:
        chunk = lines[pos : pos + chunk_size]
        if not any(rx.match(ln.strip()) for ln in chunk):
            return (
                False,
                f"Đoạn văn bản từ dòng {pos} đến {pos + chunk_size} không chứa ranh giới chương nào",
            )

    return True, f"Vượt qua kiểm chứng trên {sample_count} đoạn ngẫu nhiên"


# ── 5. Bộ phát hiện tổng hợp (Regex + AI fallback) ─────────────────────────────

async def detect_pattern(
    text: str,
    ai_provider: LLMProvider | None = None,
    custom_pattern: str | None = None,
    cases_path: Path | None = None,
) -> dict[str, Any]:
    """Phát hiện mẫu ranh giới chương cho file TXT.

    Thứ tự:
      1. Pattern chỉ định trực tiếp bởi người dùng (custom_pattern).
      2. Mẫu regex có sẵn trong cơ sở dữ liệu txt_cases.json.
      3. AI fallback nếu có ai_provider.
    """
    if custom_pattern:
        return {
            "id": "custom_user_pattern",
            "language": "other",
            "pattern": custom_pattern,
            "samples": [],
            "confidence": 1.0,
        }

    cases = load_cases(cases_path)
    matched_case = detect_pattern_regex(text, cases=cases)
    if matched_case:
        return matched_case

    if ai_provider is None:
        raise ValueError(
            "File TXT không khớp mẫu nào trong txt_cases.json và không có AI provider để nhận diện tự động.\n"
            "Vui lòng thêm pattern thủ công vào txt_cases.json hoặc truyền qua cờ --pattern."
        )

    # Lấy mẫu 50 dòng đầu gửi cho AI
    sample_lines = "\n".join(text.splitlines()[:_AI_SAMPLE_LINES])
    prompt = prompt_txt_pattern(sample_lines)

    try:
        ai_res = await ai_provider.generate(prompt, TxtPatternOutput)
    except Exception as e:
        raise ValueError(f"AI nhận diện mẫu TXT thất bại: {e}") from e

    pattern = (ai_res.chapter_regex or "").strip()
    if not pattern:
        raise ValueError("AI không tìm thấy pattern ranh giới chương nào trong đoạn mẫu.")

    # Kiểm chứng mẫu trên 3 đoạn 80 dòng ở giữa file (§6.3)
    is_valid, reason = verify_ai_pattern(text, pattern)
    if not is_valid:
        raise ValueError(
            f"Mẫu do AI đề xuất {pattern!r} không vượt qua kiểm chứng: {reason}.\n"
            f"Pattern có thể quá tham lam hoặc chỉ khớp tiêu đề trang đầu."
        )

    pattern_id = ai_res.pattern_id or f"ai_learned_{abs(hash(pattern)) % 0xFFFFFFFF:08x}"
    new_case = {
        "id": pattern_id,
        "language": ai_res.language or "other",
        "pattern": pattern,
        "samples": ai_res.example_matches or [],
        "confidence": float(ai_res.confidence or _AI_LEARNED_CONF),
    }

    try:
        _persist_new_case(new_case, cases_path=cases_path)
    except Exception as e:
        logger.warning("[TXT] Lưu mẫu mới thất bại: %s — tiếp tục xử lý", e)

    return new_case


# ── 6. Tách chương và đóng gói HTML ───────────────────────────────────────────

def split_into_chapters(
    text: str,
    case: dict[str, Any],
) -> list[tuple[int, str, str]]:
    """Tách nội dung toàn file TXT thành danh sách các chương [(index, title, body), ...]."""
    pattern = case.get("pattern", "")
    rx = re.compile(pattern)
    lines = text.splitlines()

    boundaries: list[tuple[int, str]] = []
    for idx, line in enumerate(lines):
        s_line = line.strip()
        if rx.match(s_line):
            boundaries.append((idx, s_line))

    if not boundaries:
        return []

    chapters: list[tuple[int, str, str]] = []
    for ch_idx, (start_line, title) in enumerate(boundaries, start=1):
        end_line = boundaries[ch_idx][0] if ch_idx < len(boundaries) else len(lines)
        body = "\n".join(lines[start_line + 1 : end_line]).strip()
        chapters.append((ch_idx, title, body))

    return chapters


def _text_to_html_paragraphs(text: str) -> str:
    """Chuyển văn bản thuần thành các thẻ <p>...</p>, xuống dòng đơn thành <br/>."""
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    out: list[str] = []
    for p in paragraphs:
        escaped = p.translate(_HTML_ESCAPE).replace("\n", "<br/>")
        out.append(f"<p>{escaped}</p>")
    return "".join(out)


def _build_chapter_html(title: str, body: str) -> str:
    """Đóng gói chương truyện vào cấu trúc HTML chuẩn để pipeline xử lý."""
    title_esc = title.translate(_HTML_ESCAPE)
    body_html = _text_to_html_paragraphs(body)
    return f"<html><body><article><h1>{title_esc}</h1>{body_html}</article></body></html>"


# ── 7. Luồng đọc chính ────────────────────────────────────────────────────────

async def read_txt_documents(
    path: str | Path,
    pattern: str | None = None,
    ai_provider: LLMProvider | None = None,
) -> AsyncIterator[RawDocument]:
    """Đọc file TXT thành luồng tài liệu thô RawDocument.

    Args:
        path: Đường dẫn tới file .txt.
        pattern: Biểu thức chính quy ranh giới chương (nếu người dùng chỉ định qua CLI).
        ai_provider: Provider LLM hỗ trợ nhận diện tự động khi không khớp mẫu DB.
    """
    text = read_txt_utf8(path)
    case = await detect_pattern(
        text=text,
        ai_provider=ai_provider,
        custom_pattern=pattern,
    )

    chapters = split_into_chapters(text, case)
    if not chapters:
        raise ValueError(
            f"Mẫu nhận diện {case.get('id')!r} không tìm thấy bất kỳ ranh giới chương nào trong file {str(path)!r}."
        )

    source_path = str(Path(path).resolve())
    story_name = extract_story_name_from_txt(path)
    base_meta: dict[str, Any] = {
        "story_name": story_name,
        "language": case.get("language"),
        "txt_case": case.get("id"),
        "kind": "chapter",
    }

    logger.info(
        "[TXT] %s: Tách thành công %d chương qua mẫu %r (lang=%s)",
        Path(path).name,
        len(chapters),
        case.get("id"),
        case.get("language"),
    )

    for chapter_idx, title, body in chapters:
        meta = dict(base_meta)
        meta["toc_title"] = title
        yield RawDocument(
            chapter_index=chapter_idx,
            html=_build_chapter_html(title, body),
            source_path=source_path,
            metadata=meta,
        )


__all__ = [
    "RawDocument",
    "detect_pattern",
    "detect_pattern_regex",
    "extract_story_name_from_txt",
    "load_cases",
    "read_txt_documents",
    "read_txt_utf8",
    "split_into_chapters",
    "verify_ai_pattern",
]
