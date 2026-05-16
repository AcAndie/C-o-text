"""
ingest/ — input adapter package (P3.2+).

Adapter pattern (BLUEPRINT §3 + §5):
  router.py   — detect input type, dispatch
  web.py      — wrap existing scraper (P3.3)
  epub.py     — ebooklib parse spine (P3.4)
  txt.py      — chapter boundary detection (P5.2, narrowed scope VN+EN)

Output common: RawDocument {chapter_index, html_or_text, source_url, source_path, metadata}.
Pipeline core agnostic — không biết source.
"""
