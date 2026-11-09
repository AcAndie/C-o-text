# Phase 4 Retrospective — Translation & Raw Writers (Archived Summary)

> **Trạng thái**: ✅ Hoàn thành (2026-05-17).

- **Những gì đã giải quyết (P4.1 → P4.3)**:
  - Tạo `writers/translation.py::TranslationWriter` xuất `.txt` (mỗi đoạn 1 dòng, tiêu đề ở dòng đầu, giữ ngữ cảnh ảnh bằng `[IMAGE: alt]`, mặc định tắt chunking `CHUNK_THRESHOLD = 0` — `Decision #45–#47`).
  - Tạo `writers/raw.py::RawWriter` xuất `.txt` thuần (bỏ toàn bộ cú pháp Markdown và ảnh).
  - Tạo `writers/factory.py::build_writer()` làm điểm điều phối duy nhất cho cả Web, EPUB và TXT (`Decision #48`) + thêm `_apply_epub_image_stage` trong `core/orchestrator.py` (`Decision #49`).
- **Hạng mục còn chờ**:
  - Việc gộp `_apply_epub_image_stage` (`core/orchestrator.py`) và `_apply_image_stage` (`core/scraper.py`) về 1 hàm dùng chung được theo dõi tại [`docs/V1_1_BACKLOG.md`](V1_1_BACKLOG.md) **§1.2**.
