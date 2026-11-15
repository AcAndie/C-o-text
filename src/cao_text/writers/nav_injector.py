"""nav_injector.py — Tạo mục lục 0000_Index.md và chèn điều hướng chương cho Obsidian.

Chức năng:
  1. Quét các file chương trong thư mục (theo mẫu `NNNN_*.md`).
  2. Tạo hoặc cập nhật file mục lục `0000_Index.md`.
  3. Chèn điều hướng cuối mỗi chương dạng 3-line nav stack:
       [← 0001_Prev](<0001_Prev.md>)
       [🏠 Index](<0000_Index.md>)
       [0003_Next →](<0003_Next.md>)
  4. Cơ chế idempotent: có thể chạy lại nhiều lần mà không làm nhân đôi hay hỏng nội dung.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from cao_text.storage import atomic_write_text

logger = logging.getLogger(__name__)

# Markers
_NAV_TOP_BEGIN = "<!-- nav-top -->"
_NAV_TOP_END = "<!-- /nav-top -->"
_NAV_BOT_BEGIN = "<!-- nav-bottom -->"
_NAV_BOT_END = "<!-- /nav-bottom -->"

_NAV_TOP_RE = re.compile(
    rf"\n*{re.escape(_NAV_TOP_BEGIN)}.*?{re.escape(_NAV_TOP_END)}\n*",
    re.DOTALL,
)

_NAV_BOT_RE = re.compile(
    rf"\n*(?:---\s*\n)?{re.escape(_NAV_BOT_BEGIN)}.*?{re.escape(_NAV_BOT_END)}\n*$",
    re.DOTALL,
)

_LEGACY_NAV_RE = re.compile(
    r"\n*(?:---\s*\n)?<!-- nav-links -->.*?<!-- /nav-links -->\n*",
    re.DOTALL,
)

_INDEX_PREFIX_RE = re.compile(r"^(\d{4})_")
_FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)
_YAML_LINE_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\s*:\s*(.*)$")

INDEX_FILENAME = "0000_Index.md"


def _list_chapter_files(output_dir: str | Path, extension: str = ".md") -> list[Path]:
    """Lấy danh sách các file chương đã sắp xếp theo số thứ tự 4 số đầu."""
    d = Path(output_dir)
    if not d.is_dir():
        return []
    files = [
        p
        for p in d.iterdir()
        if p.is_file()
        and p.suffix == extension
        and p.name != INDEX_FILENAME
        and _INDEX_PREFIX_RE.match(p.name)
    ]
    files.sort(key=lambda p: int(_INDEX_PREFIX_RE.match(p.name).group(1)))  # type: ignore[union-attr]
    return files


def _read_frontmatter(path: Path) -> dict[str, str]:
    """Đọc và bóc tách các trường trong YAML frontmatter đơn giản."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return {}
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return {}
    meta: dict[str, str] = {}
    for line in m.group(1).splitlines():
        kv = _YAML_LINE_RE.match(line)
        if kv:
            key = kv.group(1)
            val = kv.group(2).strip().strip("'\"")
            meta[key] = val
    return meta


def _md_link(label: str, target: str) -> str:
    """Tạo link Markdown an toàn cho Obsidian (escape [, ], wrap target trong <...>)."""
    safe_label = label.replace("\\", r"\\").replace("[", r"\[").replace("]", r"\]")
    safe_target = target.replace("<", "%3C").replace(">", "%3E")
    return f"[{safe_label}](<{safe_target}>)"


def _nav_block(prev: Path | None, nxt: Path | None) -> str:
    """Tạo khối điều hướng 3 dòng ngăn cách bởi hard line break (2 dấu cách cuối dòng)."""
    lines: list[str] = []
    if prev:
        lines.append(_md_link(f"← {prev.stem}", prev.name))
    lines.append(_md_link("🏠 Index", INDEX_FILENAME))
    if nxt:
        lines.append(_md_link(f"{nxt.stem} →", nxt.name))
    return "  \n".join(lines)


def _inject_chapter_nav(content: str, prev: Path | None, nxt: Path | None) -> str:
    """Xóa bỏ các khối nav cũ và chèn khối điều hướng mới vào cuối chương."""
    nav = _nav_block(prev, nxt)

    # 1. Dọn dẹp tất cả nav markers cũ
    stripped = _NAV_TOP_RE.sub("", content)
    stripped = _NAV_BOT_RE.sub("", stripped)
    stripped = _LEGACY_NAV_RE.sub("", stripped)

    # 2. Tách frontmatter và body
    fm_text: str = ""
    body_text: str = stripped.lstrip()
    fm_match = _FRONTMATTER_RE.match(body_text)
    if not fm_match:
        loose = re.match(r"^---\n(.*?)\n---", body_text, re.DOTALL)
        if loose:
            fm_text = body_text[: loose.end()]
            body_text = body_text[loose.end() :].lstrip()
    else:
        fm_text = body_text[: fm_match.end()].rstrip()
        body_text = body_text[fm_match.end() :].lstrip()

    # 3. Ghép lại nội dung hoàn chỉnh
    parts: list[str] = []
    if fm_text:
        parts.append(fm_text.rstrip())
        parts.append("")
    parts.append(body_text.rstrip())
    parts.append("")
    parts.append("---")
    parts.append(_NAV_BOT_BEGIN)
    parts.append(nav)
    parts.append(_NAV_BOT_END)
    return "\n".join(parts) + "\n"


def _build_index_content(
    story_name: str,
    chapters: list[tuple[Path, str]],
    source: str | None,
) -> str:
    """Tạo nội dung cho 0000_Index.md."""
    today = datetime.now().strftime("%Y-%m-%d")
    parts: list[str] = []
    parts.append(f"# {story_name}\n")
    parts.append("> [!abstract] Story Info")
    parts.append(f"> - **Chapters**: {len(chapters)}")
    if source:
        parts.append(f"> - **Source**: {source}")
    parts.append(f"> - **Last updated**: {today}")
    parts.append("")
    parts.append("## Chapters")
    parts.append("")
    for i, (path, title) in enumerate(chapters, 1):
        parts.append(f"{i}. {_md_link(title, path.name)}")
    parts.append("")
    return "\n".join(parts)


def inject_nav_and_index(
    output_dir: str | Path,
    story_name: str | None = None,
    extension: str = ".md",
) -> tuple[int, bool]:
    """Tạo mục lục 0000_Index.md và chèn điều hướng đáy trang cho toàn bộ file chương."""
    out = Path(output_dir)
    files = _list_chapter_files(out, extension)
    if not files:
        return 0, False

    titles: list[str] = []
    source: str | None = None
    for f in files:
        meta = _read_frontmatter(f)
        titles.append(meta.get("title") or f.stem)
        if source is None and meta.get("source_url"):
            try:
                source = urlparse(meta["source_url"]).netloc or None
            except Exception as e:
                logger.debug("[NavInjector] urlparse failed for %r: %s", meta["source_url"], e)
        if story_name is None and meta.get("story_name"):
            story_name = meta["story_name"]

    if not story_name:
        story_name = out.name.replace("_", " ")

    # 1. Ghi Index TOC
    index_path = out / INDEX_FILENAME
    index_content = _build_index_content(
        story_name=story_name,
        chapters=list(zip(files, titles, strict=True)),
        source=source,
    )
    try:
        existing = index_path.read_text(encoding="utf-8") if index_path.exists() else ""
        index_written = existing != index_content
        if index_written:
            atomic_write_text(index_path, index_content)
    except OSError as e:
        logger.warning("[NavInjector] write index failed: %s", e)
        index_written = False

    # 2. Chèn nav cho từng chương
    updated = 0
    for i, f in enumerate(files):
        prev = files[i - 1] if i > 0 else None
        nxt = files[i + 1] if i < len(files) - 1 else None

        try:
            original = f.read_text(encoding="utf-8")
        except OSError as e:
            logger.warning("[NavInjector] read %s failed: %s", f.name, e)
            continue

        new_content = _inject_chapter_nav(original, prev, nxt)
        if new_content == original:
            continue

        try:
            atomic_write_text(f, new_content)
            updated += 1
        except OSError as e:
            logger.warning("[NavInjector] write %s failed: %s", f.name, e)

    return updated, index_written


inject_nav_links = inject_nav_and_index

__all__ = ["inject_nav_and_index", "inject_nav_links", "INDEX_FILENAME"]
