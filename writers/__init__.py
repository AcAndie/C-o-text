"""
writers/ — output writer implementations (P1.3+).

ChapterWriter ABC + concrete implementations (ObsidianWriter at P1.4,
TranslationWriter + RawWriter at P4).

Note: package tên `writers/` thay vì `output/` (BLUEPRINT §7) — tránh
conflict với runtime output dir `output/` (gitignored, chứa scrape result).
"""
