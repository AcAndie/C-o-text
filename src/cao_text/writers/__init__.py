"""cao_text.writers — Các bộ ghi chương đầu ra (Obsidian, Translation, Raw) và chèn điều hướng."""
from __future__ import annotations

from cao_text.writers.base import ChapterWriter
from cao_text.writers.factory import build_writer
from cao_text.writers.nav_injector import INDEX_FILENAME, inject_nav_and_index, inject_nav_links
from cao_text.writers.obsidian import ObsidianWriter, format_chapter_filename, slugify_filename
from cao_text.writers.raw import RawWriter
from cao_text.writers.translation import TranslationWriter

__all__ = [
    "ChapterWriter",
    "INDEX_FILENAME",
    "ObsidianWriter",
    "RawWriter",
    "TranslationWriter",
    "build_writer",
    "format_chapter_filename",
    "inject_nav_and_index",
    "inject_nav_links",
    "slugify_filename",
]
