"""
writers/nav_injector.py — Index TOC + top/bottom prev/next nav (v1.0.12).

Post-process output directory after scrape done:
  1. Build `0000_Index.md` TOC (sorts first in folder, user opens to navigate)
  2. Inject nav header AFTER frontmatter (before content) on each chapter
  3. Inject nav footer at chapter end

Each nav row: `[← Prev] | [🏠 Index] | [Next →]`. First/last chapter
omit corresponding side.

All injects idempotent — markers `<!-- nav-top -->...<!-- /nav-top -->`
and `<!-- nav-bottom -->...<!-- /nav-bottom -->` consumed + regenerated
each run. Index file fully overwritten each run.

Scope: `.md` only (Obsidian mode). Translate/raw modes use `.txt`,
nav skipped.
"""
from __future__ import annotations

import logging
import os
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


# ── Markers ────────────────────────────────────────────────────────────────────

_NAV_TOP_BEGIN = "<!-- nav-top -->"
_NAV_TOP_END   = "<!-- /nav-top -->"

_NAV_BOT_BEGIN = "<!-- nav-bottom -->"
_NAV_BOT_END   = "<!-- /nav-bottom -->"

_NAV_TOP_RE = re.compile(
    rf"\n*{re.escape(_NAV_TOP_BEGIN)}.*?{re.escape(_NAV_TOP_END)}\n*",
    re.DOTALL,
)

_NAV_BOT_RE = re.compile(
    rf"\n*(?:---\s*\n)?{re.escape(_NAV_BOT_BEGIN)}.*?{re.escape(_NAV_BOT_END)}\n*$",
    re.DOTALL,
)

# Legacy v1.0.11 marker (single bottom-only block) — strip on migration.
_LEGACY_NAV_RE = re.compile(
    r"\n*(?:---\s*\n)?<!-- nav-links -->.*?<!-- /nav-links -->\n*",
    re.DOTALL,
)

# Match leading NNNN_ prefix (4-digit chapter index).
_INDEX_PREFIX_RE = re.compile(r"^(\d{4})_")

# YAML frontmatter block at file start.
_FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)

# Simple YAML key:value line parser.
_YAML_LINE_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\s*:\s*(.*)$")

# TOC index filename — `0000_` sorts before any `0001_..0999_` chapter file.
INDEX_FILENAME = "0000_Index.md"


# ── Chapter discovery + metadata read ─────────────────────────────────────────

def _list_chapter_files(output_dir: str | Path, extension: str = ".md") -> list[Path]:
    """Return sorted list of chapter files by NNNN prefix, excluding Index."""
    d = Path(output_dir)
    if not d.is_dir():
        return []
    files = [
        p for p in d.iterdir()
        if p.is_file()
        and p.suffix == extension
        and p.name != INDEX_FILENAME
        and _INDEX_PREFIX_RE.match(p.name)
    ]
    files.sort(key=lambda p: int(_INDEX_PREFIX_RE.match(p.name).group(1)))
    return files


def _read_frontmatter(path: Path) -> dict:
    """Parse minimal YAML frontmatter. Returns dict (empty if no FM)."""
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


# ── Nav line build ─────────────────────────────────────────────────────────────

def _md_link(label: str, target: str) -> str:
    """INDEX-LINK-SAFE: escape `[` `]` `\\` in label, wrap target in `<...>` để
    chấp nhận special chars (`[`, `]`, space, parentheses)."""
    safe_label = label.replace("\\", r"\\").replace("[", r"\[").replace("]", r"\]")
    safe_target = target.replace("<", "%3C").replace(">", "%3E")
    return f"[{safe_label}](<{safe_target}>)"


def _nav_block(prev: Path | None, nxt: Path | None) -> str:
    """v1.1.2: Build 3-line nav stack (prev / index / next). Skip None sides.
    Each line standalone Markdown line — trailing 2 spaces force line break
    in Obsidian render so the 3 links stack vertically instead of word-wrap.
    """
    lines: list[str] = []
    if prev:
        lines.append(_md_link(f"← {prev.stem}", prev.name))
    lines.append(_md_link("🏠 Index", INDEX_FILENAME))
    if nxt:
        lines.append(_md_link(f"{nxt.stem} →", nxt.name))
    # Trailing `  ` (2 spaces) = Markdown hard line break. Last line no break.
    return "  \n".join(lines)


# ── Chapter inject ─────────────────────────────────────────────────────────────

def _inject_chapter_nav(content: str, prev: Path | None, nxt: Path | None) -> str:
    """
    v1.1.2 redesign: bottom-only nav, 3-line stack format. No nav-top.

    Deterministic re-assembly:
      1. Strip all nav blocks (top + bottom + legacy v1.0.11) wherever they sit
      2. Extract frontmatter (if any) and remaining body
      3. Reassemble: FM + body + '---' + bottom_nav (no top nav)

    Recovers from corrupt prior states.
    """
    nav = _nav_block(prev, nxt)

    # 1. Strip all nav blocks (anywhere) — also strips v1.1.1 top nav from
    # existing files so re-run cleans them up.
    stripped = _NAV_TOP_RE.sub("", content)
    stripped = _NAV_BOT_RE.sub("", stripped)
    stripped = _LEGACY_NAV_RE.sub("", stripped)

    # 2. Extract frontmatter. Strict first, looser fallback for corrupt state.
    fm_text  : str = ""
    body_text: str = stripped.lstrip()
    fm_match = _FRONTMATTER_RE.match(body_text)
    if not fm_match:
        loose = re.match(r"^---\n(.*?)\n---", body_text, re.DOTALL)
        if loose:
            fm_text   = body_text[:loose.end()]
            body_text = body_text[loose.end():].lstrip()
    else:
        fm_text   = body_text[:fm_match.end()].rstrip()
        body_text = body_text[fm_match.end():].lstrip()

    # 3. Reassemble deterministic — NO top nav, only bottom
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


# ── Index (TOC) file build ────────────────────────────────────────────────────

def _build_index_content(
    story_name: str,
    chapters  : list[tuple[Path, str]],
    source    : str | None,
) -> str:
    """
    Build `0000_Index.md` content. `chapters` list of (path, display_title).
    """
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


def _atomic_write(path: Path, content: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    os.replace(tmp, path)


# ── Public entry ───────────────────────────────────────────────────────────────

def inject_nav_and_index(
    output_dir : str | Path,
    story_name : str | None = None,
    extension  : str = ".md",
) -> tuple[int, bool]:
    """
    Build `0000_Index.md` + inject top/bottom nav for each chapter.

    Args:
        output_dir: chapter folder (e.g. output/{story_slug}/)
        story_name: display name for index header. Fallback to dir name.
        extension : chapter file extension (default `.md`).

    Returns:
        (chapters_updated, index_written) — 0 means no changes / no chapters.
    """
    out = Path(output_dir)
    files = _list_chapter_files(out, extension)
    if not files:
        return 0, False

    # Gather metadata for TOC + nav
    titles : list[str] = []
    source : str | None = None
    for f in files:
        meta = _read_frontmatter(f)
        titles.append(meta.get("title") or f.stem)
        if source is None and meta.get("source_url"):
            try:
                source = urlparse(meta["source_url"]).netloc or None
            except Exception:
                pass
        if source is None and meta.get("story_name") and story_name is None:
            story_name = meta["story_name"]

    if not story_name:
        story_name = out.name.replace("_", " ")

    # ── Write Index ───────────────────────────────────────────────────────────
    index_path    = out / INDEX_FILENAME
    index_content = _build_index_content(
        story_name = story_name,
        chapters   = list(zip(files, titles)),
        source     = source,
    )
    try:
        existing = index_path.read_text(encoding="utf-8") if index_path.exists() else ""
        index_written = (existing != index_content)
        if index_written:
            _atomic_write(index_path, index_content)
    except OSError as e:
        logger.warning("[NavInjector] index write failed: %s", e)
        index_written = False

    # ── Inject per-chapter nav ────────────────────────────────────────────────
    updated = 0
    for i, f in enumerate(files):
        prev = files[i - 1] if i > 0 else None
        nxt  = files[i + 1] if i < len(files) - 1 else None

        try:
            original = f.read_text(encoding="utf-8")
        except OSError as e:
            logger.warning("[NavInjector] read %s failed: %s", f.name, e)
            continue

        new_content = _inject_chapter_nav(original, prev, nxt)
        if new_content == original:
            continue

        try:
            _atomic_write(f, new_content)
            updated += 1
        except OSError as e:
            logger.warning("[NavInjector] write %s failed: %s", f.name, e)

    return updated, index_written


# Back-compat alias for v1.0.11 callers
inject_nav_links = inject_nav_and_index


__all__ = ["inject_nav_and_index", "inject_nav_links", "INDEX_FILENAME"]
