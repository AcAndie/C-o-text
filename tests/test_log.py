from __future__ import annotations

import io
import logging
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from cao_text.log import (
    ISSUE_TYPES,
    IssueReporter,
    setup_logging,
    write_session_header,
)


def test_setup_logging_output() -> None:
    """Kiểm tra setup_logging định dạng console gọn gàng."""
    stream = io.StringIO()
    setup_logging(level=logging.INFO, verbose=False, stream=stream)

    test_logger = logging.getLogger("test_cao_text")
    test_logger.info("Test message [domain.com]")

    output = stream.getvalue()
    assert "[INFO] Test message [domain.com]" in output


def test_issue_reporter_no_issues_does_not_write(tmp_path: Path) -> None:
    """Khi không có issue nào, summarize trả về False và không tạo file."""
    issues_file = tmp_path / "test_issues.md"
    reporter = IssueReporter("example.com", issues_file=issues_file)
    reporter.mark_chapter_ok()

    written = reporter.summarize(total_chapters=10)
    assert written is False
    assert not issues_file.exists()


def test_issue_reporter_records_and_formats(tmp_path: Path) -> None:
    """Kiểm tra các loại issue chuẩn hóa và format Markdown."""
    issues_file = tmp_path / "test_issues.md"
    reporter = IssueReporter("royalroad.com", story_label="Test Story", issues_file=issues_file)

    for issue_type in ("BLOCKED", "CONTENT_SUSPICIOUS", "TITLE_FALLBACK", "NEXT_URL_MISSING"):
        reporter.report(
            issue_type=issue_type,
            url=f"https://royalroad.com/ch/{issue_type.lower()}",
            detail=f"Detail for {issue_type}",
            chapter_num=1,
        )

    assert len(reporter.issues) == 4

    written = reporter.summarize(total_chapters=10)
    assert written is True
    assert issues_file.exists()

    content = issues_file.read_text(encoding="utf-8")
    assert "### Test Story — 10 chapters" in content
    for issue_type in ("BLOCKED", "CONTENT_SUSPICIOUS", "TITLE_FALLBACK", "NEXT_URL_MISSING"):
        assert ISSUE_TYPES[issue_type] in content


def test_newest_on_top_prepend_order(tmp_path: Path) -> None:
    """Kiểm tra thứ tự newest on top: story mới hơn và session mới hơn nằm ở trên."""
    issues_file = tmp_path / "test_issues.md"

    # 1. Báo cáo Story 1
    rep1 = IssueReporter("domain1.com", story_label="Story 1", issues_file=issues_file)
    rep1.report("CONTENT_SUSPICIOUS", url="https://domain1.com/1", detail="too short", chapter_num=1)
    rep1.summarize(total_chapters=5)

    content_after_story1 = issues_file.read_text(encoding="utf-8")
    assert "Story 1" in content_after_story1

    # 2. Báo cáo Story 2 -> Story 2 phải xuất hiện TRƯỚC Story 1 trong file
    rep2 = IssueReporter("domain2.com", story_label="Story 2", issues_file=issues_file)
    rep2.report("BLOCKED", url="https://domain2.com/1", detail="Cloudflare 403", chapter_num=2)
    rep2.summarize(total_chapters=12)

    content_after_story2 = issues_file.read_text(encoding="utf-8")
    pos_story1 = content_after_story2.index("Story 1")
    pos_story2 = content_after_story2.index("Story 2")
    assert pos_story2 < pos_story1, "Story 2 (mới hơn) phải nằm phía trên Story 1"

    # 3. Ghi session header -> Session header phải nằm trước Story 2
    write_session_header(total_stories=2, issues_file=issues_file)
    content_after_session = issues_file.read_text(encoding="utf-8")

    pos_session = content_after_session.index("## Session")
    pos_story2_new = content_after_session.index("Story 2")
    assert pos_session < pos_story2_new, "Session header phải nằm phía trên các story"
    # Tiêu đề tài liệu chính (nếu có) phải ở dòng đầu tiên
    assert content_after_session.startswith("# Issue Log — Cào Text")


def test_concurrent_issue_writing_is_thread_safe(tmp_path: Path) -> None:
    """Kiểm tra ghi đồng thời từ nhiều luồng không làm hỏng file."""
    issues_file = tmp_path / "concurrent_issues.md"

    def write_worker(idx: int) -> None:
        rep = IssueReporter(f"site{idx}.com", story_label=f"Story {idx}", issues_file=issues_file)
        rep.report("ERROR", url=f"https://site{idx}.com/error", detail=f"Err {idx}", chapter_num=idx)
        rep.summarize(total_chapters=idx)

    with ThreadPoolExecutor(max_workers=5) as pool:
        list(pool.map(write_worker, range(1, 11)))

    content = issues_file.read_text(encoding="utf-8")
    # Đảm bảo toàn bộ 10 stories đều có mặt trong file
    for idx in range(1, 11):
        assert f"Story {idx}" in content
        assert f"Err {idx}" in content
