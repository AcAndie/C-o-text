"""
core/image_pipeline/ — Image fetch strategy implementations (P2.2+).

Strategy pattern cho image fetch (Decision #19):
  WebImageFetcher    — HTTP via DomainSessionPool (P2.2)
  EpubImageExtractor — binary từ EPUB zip (P3.5)

Cùng interface ImageFetchStrategy.fetch(ref) → bytes | None. Pipeline
image stage chọn strategy theo ImageRef.source_type.
"""
