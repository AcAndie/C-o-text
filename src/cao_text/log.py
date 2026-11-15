"""log.py — Thiết lập logging console gọn gàng và IssueReporter ghi issues.md.

Quy tắc:
  - Console logging gọn, dễ đọc, giữ nguyên các tiền tố emoji / domain thân thiện.
  - IssueReporter lưu vết sự cố theo từng truyện, ghi ra issues.md với thứ tự NEWEST ON TOP
    (phiên mới nhất và truyện mới nhất nằm ở trên cùng) để người dùng mở file là thấy ngay.
  - Sử dụng ghi nguyên tử (atomic write) và threading lock để an toàn khi nhiều tác vụ chạy đồng thời.
"""
from __future__ import annotations

import logging
import os
import sys
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from cao_text.settings import get_settings

logger = logging.getLogger(__name__)

# Khóa luồng đồng bộ khi ghi file issues.md
_ISSUES_WRITE_LOCK = threading.Lock()

# Các mã sự cố chuẩn hóa
ISSUE_TYPES: dict[str, str] = {
    "BLOCKED": "🚫 Bị chặn (403/CF/captcha)",
    "CONTENT_SUSPICIOUS": "⚠ Nội dung đáng ngờ (0 ký tự hoặc quá ngắn)",
    "TITLE_FALLBACK": "🏷 Tiêu đề dùng URL slug fallback",
    "NEXT_URL_MISSING": "🔗 Không tìm thấy URL chương tiếp theo",
    "LEARNING_FAILED": "❌ Học cấu trúc site (Learning Phase) thất bại",
    "EMPTY_STREAK": "📭 Nhiều chương liên tiếp rỗng",
    "RATE_LIMITED": "⏳ Bị giới hạn tốc độ (Rate Limited 429)",
    "ERROR": "💥 Lỗi ngoại lệ trong quá trình xử lý",
}


@dataclass
class IssueRecord:
    """Bản ghi chi tiết một sự cố gặp phải."""

    issue_type: str
    url: str
    detail: str = ""
    chapter_num: int = 0
    timestamp: str = field(default_factory=lambda: datetime.now().strftime("%H:%M:%S"))

    def to_markdown_line(self) -> str:
        """Định dạng bản ghi thành một dòng danh sách Markdown."""
        label = ISSUE_TYPES.get(self.issue_type, self.issue_type)
        ch_str = f"Ch.{self.chapter_num} " if self.chapter_num else ""
        detail_str = f" — {self.detail}" if self.detail else ""
        # Rút ngắn URL dài nếu vượt quá 80 ký tự để dễ đọc
        display_url = self.url if len(self.url) <= 80 else f"{self.url[:77]}..."
        return f"- {label} | {ch_str}[{self.timestamp}] `{display_url}`{detail_str}\n"


def _atomic_prepend_to_markdown(file_path: Path, new_content: str) -> None:
    """Chèn new_content lên đầu file Markdown (sau tiêu đề tài liệu nếu có), sử dụng atomic write."""
    file_path.parent.mkdir(parents=True, exist_ok=True)
    with _ISSUES_WRITE_LOCK:
        existing_text = ""
        if file_path.exists():
            try:
                existing_text = file_path.read_text(encoding="utf-8")
            except OSError as e:
                logger.warning("Không thể đọc %s để prepend: %s", file_path, e)
                existing_text = ""

        # Chuẩn bị nội dung hợp nhất
        if not existing_text.strip():
            final_content = f"# Issue Log — Cào Text\n\n{new_content.strip()}\n"
        else:
            lines = existing_text.splitlines(keepends=True)
            # Nếu có header cấp 1 "# ...", giữ lại header ở đầu rồi chèn nội dung mới
            if lines and lines[0].startswith("# "):
                doc_title = lines[0]
                rest = "".join(lines[1:]).lstrip("\n")
                final_content = f"{doc_title}\n{new_content.strip()}\n\n{rest}"
            else:
                final_content = f"{new_content.strip()}\n\n{existing_text.lstrip()}"

        # Ghi nguyên tử qua file tạm
        tmp_path = file_path.with_suffix(file_path.suffix + ".tmp")
        try:
            tmp_path.write_text(final_content, encoding="utf-8")
            os.replace(tmp_path, file_path)
        except BaseException:
            if tmp_path.exists():
                try:
                    tmp_path.unlink()
                except OSError:
                    pass
            raise


def write_session_header(total_stories: int, issues_file: str | Path | None = None) -> None:
    """Ghi nhận phiên chạy mới lên đầu issues.md (Newest on top)."""
    target_path = Path(issues_file) if issues_file else Path(get_settings().paths.issues_file)
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    header_block = f"## Session {ts} — {total_stories} truyện\n"
    try:
        _atomic_prepend_to_markdown(target_path, header_block)
    except Exception as e:
        logger.warning("[Issues] Ghi session header thất bại: %s", e)


class IssueReporter:
    """Bộ thu thập và báo cáo sự cố theo từng truyện."""

    def __init__(
        self,
        domain: str,
        story_label: str | None = None,
        issues_file: str | Path | None = None,
    ) -> None:
        self._domain = domain
        self._story_label = story_label or domain
        self._issues_file = Path(issues_file) if issues_file else None
        self._issues: list[IssueRecord] = []
        self._ok_count: int = 0

    @property
    def issues(self) -> list[IssueRecord]:
        return list(self._issues)

    def set_story_label(self, label: str) -> None:
        self._story_label = label

    def mark_chapter_ok(self) -> None:
        self._ok_count += 1

    def report(
        self,
        issue_type: str,
        url: str,
        detail: str = "",
        chapter_num: int = 0,
    ) -> None:
        """Ghi nhận một sự cố vào bộ đệm của truyện."""
        record = IssueRecord(
            issue_type=issue_type,
            url=url,
            detail=detail,
            chapter_num=chapter_num,
        )
        self._issues.append(record)
        label = ISSUE_TYPES.get(issue_type, issue_type)
        logger.debug("[Issues] %s ch#%d %s", label, chapter_num, url[:55])

    def summarize(self, total_chapters: int, issues_file: str | Path | None = None) -> bool:
        """Ghi tóm tắt sự cố của truyện lên đầu issues.md nếu có sự cố.

        Returns:
            True nếu có sự cố được ghi, False nếu không có sự cố nào.
        """
        if not self._issues:
            return False

        target_path = (
            Path(issues_file)
            if issues_file
            else (self._issues_file or Path(get_settings().paths.issues_file))
        )

        lines: list[str] = [
            f"### {self._story_label} — {total_chapters} chapters\n",
        ]
        for issue in self._issues:
            lines.append(issue.to_markdown_line())

        block = "".join(lines)
        try:
            _atomic_prepend_to_markdown(target_path, block)
            return True
        except Exception as e:
            logger.warning("[Issues] Ghi summarize thất bại: %s", e)
            return False


def setup_logging(
    level: int = logging.INFO,
    *,
    verbose: bool = False,
    stream: Any = None,
) -> None:
    """Thiết lập cấu hình logging console tinh gọn cho Cào Text."""
    target_level = logging.DEBUG if verbose else level
    out_stream = stream or sys.stdout

    formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    handler = logging.StreamHandler(out_stream)
    handler.setFormatter(formatter)
    handler.setLevel(target_level)

    root = logging.getLogger()
    # Gỡ bỏ các StreamHandler cũ nếu có để tránh in trùng lặp
    for h in list(root.handlers):
        if isinstance(h, logging.StreamHandler):
            root.removeHandler(h)

    root.addHandler(handler)
    root.setLevel(target_level)
