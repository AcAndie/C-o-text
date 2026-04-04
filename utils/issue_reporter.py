"""
utils/issue_reporter.py — Ghi nhận và báo cáo vấn đề ra issues.md (real-time).

IssueReporter được khởi tạo 1 lần per scrape session (trong run_novel_task).
Mỗi khi phát hiện vấn đề, gọi .report() → append ngay vào issues.md.
Cuối session, gọi .summarize() → ghi session summary.

Issue types:
  NEXT_URL_MISSING   — Không tìm được link chương tiếp theo
  CONTENT_SUSPICIOUS — Nội dung trông không phải truyện / quá ngắn
  BLOCKED            — 403, captcha, Cloudflare không bypass được
  TITLE_FALLBACK     — Tên chương dùng URL slug thay vì title thật
  EMPTY_STREAK       — N chương liên tiếp không có nội dung → tạm dừng
  LEARNING_FAILED    — AI Learning Phase thất bại
"""
from __future__ import annotations

import os
import threading
from datetime import datetime, timezone
from typing import Literal

# ── Constants ─────────────────────────────────────────────────────────────────

ISSUES_FILE = "issues.md"

IssueType = Literal[
    "NEXT_URL_MISSING",
    "CONTENT_SUSPICIOUS",
    "BLOCKED",
    "TITLE_FALLBACK",
    "EMPTY_STREAK",
    "LEARNING_FAILED",
]

# Gợi ý fix cho từng loại issue
_FIX_HINTS: dict[str, str] = {
    "NEXT_URL_MISSING": (
        "1. Check if the site changed its navigation structure.\n"
        "2. Re-run learning: remove the domain entry from `data/site_profiles.json`.\n"
        "3. Or add `!relearn <domain>` to `links.txt` before the URL."
    ),
    "CONTENT_SUSPICIOUS": (
        "1. The `content_selector` in the site profile may be wrong.\n"
        "2. Re-run learning to refresh the selector.\n"
        "3. Check the URL manually in a browser to confirm content exists."
    ),
    "BLOCKED": (
        "1. The site may have updated its anti-bot measures.\n"
        "2. Try increasing delay in `config.py` → `_DELAY_PROFILES`.\n"
        "3. If Cloudflare: Playwright is already attempted automatically.\n"
        "4. If still blocked: wait a few hours before retrying."
    ),
    "TITLE_FALLBACK": (
        "1. The `title_selector` in the site profile may be missing or wrong.\n"
        "2. Re-run learning to refresh the selector.\n"
        "3. This is cosmetic — content is still saved correctly."
    ),
    "EMPTY_STREAK": (
        "1. The author may not have published new chapters yet.\n"
        "2. Re-run the scraper later to resume from this point.\n"
        "3. Progress is saved — no chapters will be re-downloaded."
    ),
    "LEARNING_FAILED": (
        "1. Check your GEMINI_API_KEY and API quota.\n"
        "2. The site may require special handling (e.g. login, JS-heavy).\n"
        "3. Try again later — Gemini 503 errors are usually transient."
    ),
}

# Global write lock — tránh race condition khi nhiều task ghi cùng lúc
_WRITE_LOCK = threading.Lock()


# ── IssueReporter ─────────────────────────────────────────────────────────────

class IssueReporter:
    """
    Ghi nhận vấn đề ra issues.md real-time.
    1 instance per novel task, dùng chung ISSUES_FILE.
    """

    def __init__(self, domain: str, story_label: str = "") -> None:
        self._domain       = domain
        self._story_label  = story_label or domain
        self._issues: list[dict] = []   # buffer để summarize cuối session
        self._chapter_stats = {"ok": 0, "issues": 0}

    def set_story_label(self, label: str) -> None:
        """Cập nhật story label sau khi naming phase chạy xong."""
        if label:
            self._story_label = label

    # ── Public API ────────────────────────────────────────────────────────────

    def report(
        self,
        issue_type : IssueType,
        url        : str,
        detail     : str = "",
        chapter_num: int | None = None,
    ) -> None:
        """
        Ghi 1 issue vào issues.md ngay lập tức (real-time).

        Args:
            issue_type:  Loại issue (xem IssueType)
            url:         URL đang xử lý khi xảy ra issue
            detail:      Mô tả chi tiết thêm (optional)
            chapter_num: Số chương (optional)
        """
        now     = _now_str()
        entry   = {
            "type"       : issue_type,
            "url"        : url,
            "detail"     : detail,
            "chapter_num": chapter_num,
            "time"       : now,
        }
        self._issues.append(entry)
        self._chapter_stats["issues"] += 1
        self._write_issue(entry)

    def mark_chapter_ok(self) -> None:
        """Đánh dấu 1 chương cào thành công (để tính tỉ lệ cuối session)."""
        self._chapter_stats["ok"] += 1

    def summarize(self, total_chapters: int) -> None:
        """
        Ghi session summary vào cuối issues.md.
        Chỉ ghi nếu có ít nhất 1 issue trong session này.
        """
        if not self._issues:
            return

        ok      = self._chapter_stats["ok"]
        n_issues = len(self._issues)
        label   = self._story_label

        # Đếm theo loại
        by_type: dict[str, int] = {}
        for e in self._issues:
            by_type[e["type"]] = by_type.get(e["type"], 0) + 1

        lines = [
            f"\n## Session Summary — {label} [{_now_str()}]\n",
            f"- **Domain:** `{self._domain}`\n",
            f"- **Chapters scraped:** {total_chapters} "
            f"({ok} OK / {n_issues} with issues)\n",
            "\n**Issues by type:**\n",
        ]
        for itype, count in sorted(by_type.items(), key=lambda x: -x[1]):
            lines.append(f"- `{itype}` × {count}\n")

        # Open issues checklist
        open_issues = [e for e in self._issues if e["type"] != "TITLE_FALLBACK"]
        if open_issues:
            lines.append("\n**Open issues (review recommended):**\n")
            for e in open_issues[-5:]:   # chỉ show 5 gần nhất
                ch = f" ch.{e['chapter_num']}" if e["chapter_num"] else ""
                lines.append(
                    f"- [ ] `{e['type']}`{ch} — {_short_url(e['url'])}\n"
                )

        lines.append("\n---\n")
        _append_to_file("".join(lines))

    # ── Private ───────────────────────────────────────────────────────────────

    def _write_issue(self, entry: dict) -> None:
        ch_str  = f" (Chapter {entry['chapter_num']})" if entry["chapter_num"] else ""
        hint    = _FIX_HINTS.get(entry["type"], "No fix hint available.")
        detail  = entry["detail"]

        lines = [
            f"\n## [{entry['time']}] `{entry['type']}` — {self._domain}{ch_str}\n",
            f"\n**Story:** {self._story_label}  \n",
            f"**URL:** `{entry['url']}`  \n",
        ]
        if detail:
            lines.append(f"**Detail:** {detail}  \n")

        lines += [
            f"\n**Suggested fix:**\n",
        ]
        for line in hint.splitlines():
            lines.append(f"{line}  \n")

        lines.append("\n---\n")
        _append_to_file("".join(lines))

        # In ngắn ra console để biết có issue
        ch_tag = f" ch.{entry['chapter_num']}" if entry["chapter_num"] else ""
        print(
            f"  [Issue] ⚠️  {entry['type']}{ch_tag} → xem issues.md",
            flush=True,
        )


# ── File I/O ──────────────────────────────────────────────────────────────────

def _append_to_file(text: str) -> None:
    """Thread-safe append vào issues.md."""
    with _WRITE_LOCK:
        try:
            with open(ISSUES_FILE, "a", encoding="utf-8") as f:
                f.write(text)
        except Exception as e:
            # Không để lỗi ghi file làm crash scraper
            print(f"  [IssueReporter] ⚠ Không ghi được issues.md: {e}", flush=True)


def _now_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _short_url(url: str, max_len: int = 70) -> str:
    return url if len(url) <= max_len else url[:max_len] + "…"


# ── Session header (ghi 1 lần khi bắt đầu run) ───────────────────────────────

def write_session_header(n_tasks: int) -> None:
    """
    Ghi header cho session mới vào đầu issues.md.
    Gọi 1 lần từ main.py khi bắt đầu chạy.
    """
    now  = _now_str()
    text = (
        f"\n# Scrape Session — {now}\n"
        f"**Tasks:** {n_tasks} novel(s)\n\n"
        "---\n"
    )
    _append_to_file(text)