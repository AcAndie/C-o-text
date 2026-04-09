"""
utils/issue_reporter.py — Issue tracking và session reporting.

Public API:
    write_session_header(total_stories)    → None
    IssueReporter(domain).report(...)      → None
    IssueReporter.mark_chapter_ok()        → None
    IssueReporter.summarize(total)         → None
    IssueReporter.set_story_label(label)   → None
"""
from __future__ import annotations

import logging
import os
from datetime import datetime

logger = logging.getLogger(__name__)

_ISSUES_FILE = "issues.md"

# Issue types
ISSUE_TYPES = {
    "LEARNING_FAILED"    : "❌ Learning Phase thất bại",
    "CONTENT_SUSPICIOUS" : "⚠ Content đáng ngờ (0 chars hoặc quá ngắn)",
    "NEXT_URL_MISSING"   : "🔗 Không tìm được next URL",
    "TITLE_FALLBACK"     : "🏷 Title có thể là URL slug fallback",
    "BLOCKED"            : "🚫 Bị block (403/CF/captcha)",
    "EMPTY_STREAK"       : "📭 Nhiều chapter liên tiếp rỗng",
}


def write_session_header(total_stories: int) -> None:
    """Ghi header cho session mới vào issues.md."""
    try:
        ts      = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        header  = f"\n\n## Session {ts} — {total_stories} stories\n\n"
        with open(_ISSUES_FILE, "a", encoding="utf-8") as f:
            f.write(header)
    except Exception as e:
        logger.debug("[Issues] write_session_header failed: %s", e)


class IssueReporter:
    """
    Per-story issue collector. Reports được ghi vào issues.md cuối story.
    """

    def __init__(self, domain: str) -> None:
        self._domain      = domain
        self._story_label = domain
        self._issues      : list[dict] = []
        self._ok_count    = 0

    def set_story_label(self, label: str) -> None:
        self._story_label = label

    def report(
        self,
        issue_type : str,
        url        : str,
        detail     : str = "",
        chapter_num: int = 0,
    ) -> None:
        """Ghi nhận một issue."""
        self._issues.append({
            "type"       : issue_type,
            "url"        : url,
            "detail"     : detail,
            "chapter_num": chapter_num,
            "ts"         : datetime.now().strftime("%H:%M:%S"),
        })
        label = ISSUE_TYPES.get(issue_type, issue_type)
        logger.debug("[Issues] %s ch#%d %s", label, chapter_num, url[:55])

    def mark_chapter_ok(self) -> None:
        self._ok_count += 1

    def summarize(self, total_chapters: int) -> None:
        """Ghi summary ra issues.md nếu có issues."""
        if not self._issues:
            return

        try:
            lines = [
                f"### {self._story_label} — {total_chapters} chapters\n",
            ]
            for issue in self._issues:
                label  = ISSUE_TYPES.get(issue["type"], issue["type"])
                ch_str = f"Ch.{issue['chapter_num']} " if issue["chapter_num"] else ""
                detail = f" — {issue['detail']}" if issue["detail"] else ""
                lines.append(
                    f"- {label} | {ch_str}[{issue['ts']}]"
                    f" `{issue['url'][:70]}`{detail}\n"
                )
            lines.append("\n")

            with open(_ISSUES_FILE, "a", encoding="utf-8") as f:
                f.writelines(lines)

        except Exception as e:
            logger.debug("[Issues] summarize failed: %s", e)