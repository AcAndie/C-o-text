# Phase 1 Retrospective — Output Mode Abstraction (Archived Summary)

> **Trạng thái**: ✅ Hoàn thành (2026-05-16).

- **Những gì đã giải quyết (P1.1 → P1.6)**:
  - Tạo `RunConfig` + CLI `--output-mode` (`obsidian`, `translate`, `raw`).
  - Định nghĩa `CleanedChapter`, `ImageRef`, `FormattingRules` (dùng enum `image_alt_strategy` thay cho boolean cũ).
  - Tạo `writers/base.py::ChapterWriter` (đổi tên từ `output/` sang `writers/` để không đụng thư mục `output/` runtime — `Decision #30`).
  - Port `ObsidianWriter` sang `writers/obsidian.py` và refactor pipeline trả về `CleanedChapter` DTO thay vì ghi file trực tiếp (`Decision #31–#33`).
- **Xử lý nợ kỹ thuật sau Phase 1**:
  - Tài liệu `README.md` (P0.4) đã được viết đầy đủ ở Phase 6.
  - Luồng truyền `--output-dir` cho Web đã được đồng bộ hoàn chỉnh ở v1.1.0 (`5588e33`).
