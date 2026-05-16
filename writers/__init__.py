"""
writers/ — output writer implementations (P1.3+).

ChapterWriter ABC + concrete implementations:
  - ObsidianWriter     (P1.4) — Markdown + frontmatter + image embed
  - TranslationWriter  (P4.1) — plain text, markdown stripped, [IMAGE: alt]
  - RawWriter          (P4.2) — plain text, image dropped entirely

Note: package tên `writers/` thay vì `output/` (BLUEPRINT §7) — tránh
conflict với runtime output dir `output/` (gitignored, chứa scrape result).
"""
from writers.base        import ChapterWriter
from writers.obsidian    import ObsidianWriter
from writers.raw         import RawWriter
from writers.translation import TranslationWriter

__all__ = ["ChapterWriter", "ObsidianWriter", "RawWriter", "TranslationWriter"]
