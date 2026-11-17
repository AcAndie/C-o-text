"""tests/test_txt.py — Kiểm thử toàn diện module txt.py (Task 6.3)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from cao_text.ai.schemas import TxtPatternOutput
from cao_text.files.txt import (
    _build_chapter_html,
    detect_pattern,
    detect_pattern_regex,
    extract_story_name_from_txt,
    load_cases,
    read_txt_documents,
    read_txt_utf8,
    split_into_chapters,
    verify_ai_pattern,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
FIXTURES_TXT_ROOT = PROJECT_ROOT / "tests" / "fixtures" / "txt"


# ── 1. UTF-8 Reading & Friendly Error (§6.6) ──────────────────────────────────

def test_read_txt_utf8_valid(tmp_path: Path) -> None:
    f = tmp_path / "story.txt"
    content = "Chương 1: Tiêu đề tiếng Việt có dấu — Trực tiếp UTF-8."
    f.write_text(content, encoding="utf-8")

    result = read_txt_utf8(f)
    assert result == content


def test_read_txt_utf8_invalid_loud_error(tmp_path: Path) -> None:
    f = tmp_path / "bad_encoding.txt"
    # Byte 0xFF 0xFE hoặc 0x80..0xFF không hợp lệ trong UTF-8
    f.write_bytes(b"\xfe\xff\x00C\x00h\x00u\x00o\x00n\x00g\x80\x81")

    with pytest.raises(UnicodeDecodeError) as exc_info:
        read_txt_utf8(f)

    msg = str(exc_info.value)
    assert "không phải định dạng UTF-8" in msg
    assert "Notepad" in msg
    assert "PowerShell" in msg


def test_extract_story_name_from_txt() -> None:
    assert extract_story_name_from_txt("path/to/Tien_Nghich.txt") == "Tien_Nghich"
    assert extract_story_name_from_txt(Path("Linh_Vu_Thien_Ha.txt")) == "Linh_Vu_Thien_Ha"


# ── 2. Regex Pattern Matching ─────────────────────────────────────────────────

def test_detect_pattern_regex_vn_sample() -> None:
    vn_file = FIXTURES_TXT_ROOT / "vn_chuong_sample.txt"
    assert vn_file.exists()
    text = read_txt_utf8(vn_file)

    case = detect_pattern_regex(text)
    assert case is not None
    assert "vn_chuong" in case.get("id", "")
    assert case.get("language") == "vi"


def test_detect_pattern_regex_en_sample() -> None:
    en_file = FIXTURES_TXT_ROOT / "en_chapter_sample.txt"
    assert en_file.exists()
    text = read_txt_utf8(en_file)

    case = detect_pattern_regex(text)
    assert case is not None
    assert "en_chapter" in case.get("id", "")
    assert case.get("language") == "en"


def test_detect_pattern_regex_unknown() -> None:
    random_text = "Dòng 1: Một buổi sáng bình thường\nDòng 2: Không có ranh giới chương rõ ràng."
    case = detect_pattern_regex(random_text)
    assert case is None


# ── 3. AI Pattern Verification (§6.3) ─────────────────────────────────────────

def test_verify_ai_pattern_short_file() -> None:
    # File ngắn (< 240 dòng)
    short_text = "\n".join([f"Dòng {i}" for i in range(50)]) + "\nHồi 1: Khởi đầu\nNội dung..."
    ok, reason = verify_ai_pattern(short_text, r"^Hồi\s+\d+")
    assert ok is True
    assert "File ngắn" in reason

    # File ngắn không khớp mẫu
    ok_fail, _ = verify_ai_pattern(short_text, r"^Tiết\s+\d+")
    assert ok_fail is False


def test_verify_ai_pattern_long_file_success() -> None:
    # Tạo file dài 400 dòng, mỗi 50 dòng có 1 ranh giới "Hồi N:"
    lines: list[str] = []
    chapter_num = 1
    for i in range(400):
        if i % 40 == 0:
            lines.append(f"Hồi {chapter_num}: Tiêu đề")
            chapter_num += 1
        else:
            lines.append(f"Nội dung dòng văn xuôi thứ {i}...")

    long_text = "\n".join(lines)
    ok, reason = verify_ai_pattern(long_text, r"^Hồi\s+\d+")
    assert ok is True
    assert "Vượt qua kiểm chứng" in reason


def test_verify_ai_pattern_long_file_greedy_fail() -> None:
    # File dài 400 dòng nhưng "Hồi 1" chỉ xuất hiện duy nhất ở dòng đầu, còn lại không có
    lines = ["Hồi 1: Tiêu đề duy nhất"] + [f"Nội dung dòng {i}..." for i in range(1, 400)]
    long_text = "\n".join(lines)

    ok, reason = verify_ai_pattern(long_text, r"^Hồi\s+\d+")
    assert ok is False
    assert "không chứa ranh giới chương nào" in reason


# ── 4. AI Fallback & DB Persistence ───────────────────────────────────────────

class MockAiProvider:
    def __init__(self, output: Any) -> None:
        self.output = output
        self.called = 0

    async def generate(self, prompt: str, schema: Any) -> Any:
        self.called += 1
        if isinstance(self.output, Exception):
            raise self.output
        return self.output


@pytest.mark.asyncio
async def test_detect_pattern_custom_override() -> None:
    case = await detect_pattern(
        text="Bất kỳ văn bản nào",
        custom_pattern=r"^Phần\s+\d+",
    )
    assert case["id"] == "custom_user_pattern"
    assert case["pattern"] == r"^Phần\s+\d+"


@pytest.mark.asyncio
async def test_detect_pattern_no_ai_raises_value_error() -> None:
    with pytest.raises(ValueError) as exc:
        await detect_pattern("Văn bản lạ không match regex", ai_provider=None)
    assert "không khớp mẫu nào" in str(exc.value)


@pytest.mark.asyncio
async def test_detect_pattern_ai_success_and_persist(tmp_path: Path) -> None:
    cases_file = tmp_path / "txt_cases.json"
    cases_file.write_text(json.dumps({"version": 1, "cases": []}), encoding="utf-8")

    text = "Hồi 1: Đầu mối câu chuyện\nNội dung hồi 1...\nHồi 2: Tiếp diễn biến cố\nNội dung hồi 2..."
    ai_output = TxtPatternOutput(
        pattern_id="vn_hoi_so",
        language="vi",
        chapter_regex=r"^Hồi\s+\d+",
        example_matches=["Hồi 1", "Hồi 2"],
        confidence=0.85,
    )
    provider = MockAiProvider(ai_output)

    case = await detect_pattern(
        text=text,
        ai_provider=provider,  # type: ignore[arg-type]
        cases_path=cases_file,
    )

    assert provider.called == 1
    assert case["id"] == "vn_hoi_so"
    assert case["pattern"] == r"^Hồi\s+\d+"

    # Kiểm tra DB file đã được cập nhật
    saved_cases = load_cases(cases_file)
    assert any(c["id"] == "vn_hoi_so" for c in saved_cases)


@pytest.mark.asyncio
async def test_detect_pattern_ai_verify_fail_raises(tmp_path: Path) -> None:
    cases_file = tmp_path / "txt_cases.json"
    cases_file.write_text(json.dumps({"version": 1, "cases": []}), encoding="utf-8")

    # File dài nhưng chỉ có 1 dòng match ở đầu
    lines = ["Dòng đầu lạ"] + [f"Nội dung dòng {i}" for i in range(1, 350)]
    text = "\n".join(lines)

    ai_output = TxtPatternOutput(
        pattern_id="fake_pattern",
        chapter_regex=r"^Dòng đầu lạ",
    )
    provider = MockAiProvider(ai_output)

    with pytest.raises(ValueError) as exc:
        await detect_pattern(
            text=text,
            ai_provider=provider,  # type: ignore[arg-type]
            cases_path=cases_file,
        )

    assert "không vượt qua kiểm chứng" in str(exc.value)


# ── 5. Split & HTML Wrapping ──────────────────────────────────────────────────

def test_split_into_chapters() -> None:
    text = (
        "Lời tựa sách bỏ qua\n"
        "Chương 1: Bình minh\n"
        "Mặt trời mọc.\n\n"
        "Lâm Phong tỉnh giấc.\n"
        "Chương 2: Hoàng hôn\n"
        "Mặt trời lặn."
    )
    case = {"pattern": r"^Chương\s+\d+.*$"}
    chapters = split_into_chapters(text, case)

    assert len(chapters) == 2
    assert chapters[0][0] == 1
    assert chapters[0][1] == "Chương 1: Bình minh"
    assert "Mặt trời mọc." in chapters[0][2]

    assert chapters[1][0] == 2
    assert chapters[1][1] == "Chương 2: Hoàng hôn"
    assert "Mặt trời lặn." in chapters[1][2]


def test_build_chapter_html() -> None:
    title = "Chương 1 <Khởi đầu> & Thử thách"
    body = "Đoạn 1 dòng 1\nĐoạn 1 dòng 2 nối tiếp\n\nĐoạn 2 mới."

    html = _build_chapter_html(title, body)
    assert "<h1>Chương 1 &lt;Khởi đầu&gt; &amp; Thử thách</h1>" in html
    assert "<p>Đoạn 1 dòng 1<br/>Đoạn 1 dòng 2 nối tiếp</p>" in html
    assert "<p>Đoạn 2 mới.</p>" in html


# ── 6. Full Stream read_txt_documents ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_read_txt_documents_stream() -> None:
    vn_file = FIXTURES_TXT_ROOT / "vn_chuong_sample.txt"
    docs = []
    async for doc in read_txt_documents(vn_file):
        docs.append(doc)

    assert len(docs) == 3
    assert docs[0].chapter_index == 1
    assert "Khởi đầu nơi sơn thôn" in docs[0].html
    assert docs[0].metadata["story_name"] == "vn_chuong_sample"
    assert docs[0].metadata["kind"] == "chapter"
    assert docs[2].chapter_index == 3
