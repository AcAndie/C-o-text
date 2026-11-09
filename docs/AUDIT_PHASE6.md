# Phase 6 Codebase Audit — Summary (Resolved)

> **Ngày audit**: 2026-05-17 | **Cập nhật**: 2026-11-09
> Toàn bộ các mục dọn dẹp an toàn (Batch C safe subset, `Decision #55`) đã hoàn thành trong Phase 6. Hai mục refactor hành vi cần baseline được chuyển sang [`docs/V1_1_BACKLOG.md`](V1_1_BACKLOG.md).

| # | Hạng mục Audit | Trạng thái | Ghi chú giải quyết |
|---|---|---|---|
| **1** | **Unused imports (19 hits) & stale f-prefixes (22 hits)** | ✅ Đã xoá (P6.2) | Chạy `autoflake` xoá 19 unused imports và bỏ 22 tiền tố `f` không có placeholder. (Còn 2 cảnh báo mới phát sinh ở v1.1 được ghi tại `V1_1_BACKLOG.md` §7.2). |
| **2** | **Chuyển `RawDocument` sang `src/ingest/types.py`** | ✅ Đã chuyển (P6.2) | Tách `RawDocument` khỏi `ingest/epub.py` sang `ingest/types.py` để dùng chung sạch sẽ cho cả EPUB và TXT. |
| **3** | **Gộp `_title_from_url` và xoá `src/core/extractor.py`** | ✅ Đã xoá (P6.2) | Inline `_title_from_url()` vào `src/pipeline/title_extractor.py` và xoá file `src/core/extractor.py` (56 LOC). |
| **4** | **Unify `run_epub_flow` + `run_txt_flow` qua `FlowSpec` (`core/orchestrator.py`)** | ⏳ Deferred | Chuyển sang [`docs/V1_1_BACKLOG.md`](V1_1_BACKLOG.md) **§1.1 (P4)** — chờ chụp baseline P1 trước khi sửa. |
| **5** | **Tách `_apply_image_stage` dùng chung (`scraper.py` vs `orchestrator.py`)** | ⏳ Deferred | Chuyển sang [`docs/V1_1_BACKLOG.md`](V1_1_BACKLOG.md) **§1.2** — chạm shared logic `core/scraper.py`, chờ baseline P1. |
| **6** | **Xoá wrapper thừa `src/ingest/web.py` (62 LOC)** | ✅ Đã xoá (P6.2) | Xoá `src/ingest/web.py` do không có caller thực tế; `main.py` gọi trực tiếp `core.scraper.run_novel_task`. |
