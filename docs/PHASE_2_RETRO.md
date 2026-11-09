# Phase 2 Retrospective — Image Support (Archived Summary)

> **Trạng thái**: ✅ Hoàn thành (2026-05-16).

- **Những gì đã giải quyết (P2.1 → P2.6)**:
  - Tạo `utils/image_url.py::resolve_image_url` xử lý lazy-load (`data-src`, `data-original`, `srcset`), protocol-relative URL, và bỏ qua `data:` URI (`Decision #34`).
  - Tạo `ImageFetchStrategy` ABC (`core/image_pipeline/base.py`) và `WebImageFetcher` (`core/image_pipeline/web_fetcher.py`) tải ảnh qua `DomainSessionPool`.
  - Mở rộng `MarkdownFormatter` trích xuất thẻ `<img>` kèm vị trí placeholder (`Decision #35`).
  - Thêm bước `_apply_image_stage` mode-aware trong `core/scraper.py` (tải ảnh cho `obsidian`, chèn `[IMAGE: alt]` cho `translate`, xoá ảnh cho `raw` — `Decision #36`) và prompt AI#image (`Decision #37`).
