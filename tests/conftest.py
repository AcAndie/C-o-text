"""
tests/conftest.py — Cấu hình pytest, custom options và helpers so sánh golden test.
"""
from __future__ import annotations

import difflib
import json
import re
import shutil
from pathlib import Path
from typing import Any

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent

_INDEX_DATE_RE = re.compile(r"(> - \*\*Last updated\*\*: )\d{4}-\d{2}-\d{2}")


def _normalize_index_date(text: str) -> str:
    """Chuẩn hóa ngày động YYYY-MM-DD trong 0000_Index.md để test không phụ thuộc ngày chạy."""
    return _INDEX_DATE_RE.sub(r"\1<DATE>", text)


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--update-golden",
        action="store_true",
        default=False,
        help="Cập nhật golden files khi có diff được phê duyệt.",
    )
    parser.addoption(
        "--run-slow",
        action="store_true",
        default=False,
        help="Chạy cả các test tốn nhiều thời gian (ví dụ EPUB >1000 chương).",
    )


@pytest.fixture
def update_golden(request: pytest.FixtureRequest) -> bool:
    return bool(request.config.getoption("--update-golden"))


@pytest.fixture
def run_slow(request: pytest.FixtureRequest) -> bool:
    return bool(request.config.getoption("--run-slow"))


@pytest.fixture(autouse=True)
def _isolate_ads_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Cô lập data/ads_keywords.json trong mọi bài test:
    chép bản sao sang tmp_path để AdsFilter đọc đúng dữ liệu gốc nhưng mọi
    lệnh save() trong lúc test chỉ ghi vào file tạm, không làm bẩn dữ liệu user.
    """
    from cao_text.settings import Settings

    real_ads = PROJECT_ROOT / "data" / "ads_keywords.json"
    tmp_ads = tmp_path / "ads_keywords.json"
    if real_ads.exists():
        shutil.copy2(real_ads, tmp_ads)
    else:
        tmp_ads.write_text("{}\n", encoding="utf-8")

    monkeypatch.setattr(Settings, "ads_db_file", property(lambda self: str(tmp_ads)))


def format_diff(actual: str, expected: str, fromfile: str = "actual", tofile: str = "expected", max_lines: int = 40) -> str:
    """Tạo unified diff ngắn gọn giữa actual và expected."""
    diff = list(
        difflib.unified_diff(
            expected.splitlines(keepends=True),
            actual.splitlines(keepends=True),
            fromfile=tofile,
            tofile=fromfile,
            n=3,
        )
    )
    if not diff:
        return ""
    if len(diff) > max_lines:
        return "".join(diff[:max_lines]) + f"\n... (diff truncated, còn {len(diff) - max_lines} dòng nữa)"
    return "".join(diff)


def assert_text_exact(actual: str, expected: str, context: str = "") -> None:
    """So sánh chuỗi khớp tuyệt đối 100%. Nếu khác nhau, in diff ngắn gọn."""
    if actual != expected:
        diff_text = format_diff(actual, expected)
        msg = f"Nội dung không khớp tuyệt đối{' (' + context + ')' if context else ''}:\n{diff_text}"
        raise AssertionError(msg)


def assert_text_similar(
    actual: str,
    expected: str,
    min_ratio: float = 0.99,
    context: str = "",
) -> None:
    """
    So sánh chuỗi dùng difflib.SequenceMatcher.
    Yêu cầu ratio >= min_ratio (mặc định 0.99 cho fixtures thật).
    """
    if actual == expected:
        return
    matcher = difflib.SequenceMatcher(None, actual, expected)
    ratio = matcher.ratio()
    if ratio < min_ratio:
        diff_text = format_diff(actual, expected)
        msg = (
            f"Độ tương đồng nội dung quá thấp: {ratio:.4f} < {min_ratio:.4f}"
            f"{' (' + context + ')' if context else ''}\n{diff_text}"
        )
        raise AssertionError(msg)


def assert_json_extract_match(
    actual: dict[str, Any],
    expected: dict[str, Any],
    min_content_ratio: float = 0.99,
    context: str = "",
) -> None:
    """
    So sánh kết quả trích xuất Web:
    - title, next_url, nav_method, selector_used khớp tuyệt đối
    - content: so sánh similarity ratio >= min_content_ratio
    """
    for field in ("title", "next_url", "nav_method", "selector_used"):
        act_val = actual.get(field)
        exp_val = expected.get(field)
        assert act_val == exp_val, (
            f"Trường '{field}' không khớp{' (' + context + ')' if context else ''}:\n"
            f"  Actual  : {act_val!r}\n"
            f"  Expected: {exp_val!r}"
        )

    act_content = actual.get("content") or ""
    exp_content = expected.get("content") or ""
    assert_text_similar(act_content, exp_content, min_ratio=min_content_ratio, context=f"{context} content")


def assert_dir_contents_match(
    actual_dir: Path,
    expected_dir: Path,
    *,
    is_synthetic: bool = True,
    min_ratio: float = 0.99,
    update_golden: bool = False,
) -> None:
    """
    So sánh toàn bộ nội dung của hai thư mục:
    - Nếu update_golden=True: ghi đè expected_dir bằng actual_dir.
    - Danh sách file tương đối phải khớp nhau.
    - Từng file text được so sánh theo exact (synthetic) hoặc similarity ratio (real).
    """
    if update_golden:
        if expected_dir.exists():
            shutil.rmtree(expected_dir)
        shutil.copytree(actual_dir, expected_dir)
        return

    actual_files = sorted(p.relative_to(actual_dir) for p in actual_dir.rglob("*") if p.is_file())
    expected_files = sorted(p.relative_to(expected_dir) for p in expected_dir.rglob("*") if p.is_file())

    assert actual_files == expected_files, (
        f"Danh sách file không khớp giữa actual và expected:\n"
        f"  Actual files  : {[str(f) for f in actual_files]}\n"
        f"  Expected files: {[str(f) for f in expected_files]}"
    )

    BINARY_SUFFIXES = frozenset({".jpg", ".jpeg", ".png", ".webp", ".gif", ".ico", ".epub"})

    for rel_file in actual_files:
        act_path = actual_dir / rel_file
        exp_path = expected_dir / rel_file
        ctx = str(rel_file)

        if rel_file.suffix.lower() in BINARY_SUFFIXES:
            act_bytes = act_path.read_bytes()
            exp_bytes = exp_path.read_bytes()
            assert act_bytes == exp_bytes, f"Nội dung file nhị phân không khớp: {ctx}"
            continue

        act_text = act_path.read_text(encoding="utf-8")
        exp_text = exp_path.read_text(encoding="utf-8")

        if rel_file.name == "0000_Index.md":
            act_text = _normalize_index_date(act_text)
            exp_text = _normalize_index_date(exp_text)

        if is_synthetic:
            assert_text_exact(act_text, exp_text, context=ctx)
        else:
            # Fixture thật: nếu là json thì dùng assert_json_extract_match
            if rel_file.suffix == ".json":
                act_json = json.loads(act_text)
                exp_json = json.loads(exp_text)
                assert_json_extract_match(act_json, exp_json, min_content_ratio=min_ratio, context=ctx)
            else:
                assert_text_similar(act_text, exp_text, min_ratio=min_ratio, context=ctx)
