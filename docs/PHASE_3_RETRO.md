# Phase 3 Retrospective — EPUB Adapter (Archived Summary)

> **Trạng thái**: ✅ Hoàn thành (2026-05-16) + Đã vá các lỗi phát sinh ở v1.0.13 & v1.1.0.

- **Những gì đã giải quyết (P3.1 → P3.4)**:
  - Tạo `ingest/router.py` tự nhận diện URL list, `.epub`, `.txt`, hoặc thư mục inbox (`Decision #38`).
  - Tạo `ingest/epub.py` đọc spine bằng `ebooklib`, lấy tên truyện từ Dublin Core metadata (`Decision #22`), fallback trích xuất thẳng từ `<body>` cho EPUB phẳng (`Decision #40`).
  - Tạo `EpubImageExtractor` đọc binary ảnh trực tiếp từ file zip EPUB (`Decision #19`).
  - Tạo `core/orchestrator.py::run_epub_flow` tái sử dụng bộ cleaner + `AdsFilter` với namespace `epub:{slug}` (`Decision #41–#44`).
- **Các lỗi EPUB phát hiện sau Phase 3 đã được giải quyết**:
  - ✅ Lỗi tên chương dính đường dẫn file & lỗi đường dẫn ảnh tương đối `../images/`: Đã sửa ở v1.0.13.
  - ✅ Lỗi tách chương quá vụn ở trang Part/Book divider & EPUB thiếu TOC: Đã sửa ở v1.1.0 (`70e4386`, `b4944d2`).
  - 📋 Vấn đề EPUB dài tập (>300 spine docs) chạm trần token AI & `AdsFilter` xoá nhầm câu thoại ngắn: Đang theo dõi tại [`docs/V1_1_BACKLOG.md`](V1_1_BACKLOG.md) **§7.3**.
