# ROADMAP.md — Lộ Trình Thực Thi (Tóm Tắt Các Phase Đã Hoàn Thành)

> **Trạng thái hiện tại (2026-11-09):** ✅ **v1.2.1 SHIPPED.**
> Toàn bộ 7 Phase của v1.0 (Phase 0 → Phase 6) và các bản vá v1.0.13 → v1.2.1 đã hoàn thành. Các checklist chi tiết từng bước đã được rút gọn thành bảng kết quả dưới đây để tiện tra cứu.
> - Các vấn đề đang chờ xử lý tiếp: xem [`docs/V1_1_BACKLOG.md`](V1_1_BACKLOG.md)
> - Kiến trúc hệ thống: xem [`docs/BLUEPRINT.md`](BLUEPRINT.md)
> - Lịch sử phiên bản: xem [`docs/CHANGELOG.md`](CHANGELOG.md)

---

## 1. Bảng Tổng Hợp Các Phase (Phase 0 → Phase 6)

| Phase | Mục tiêu | Trạng thái | Tóm tắt vấn đề đã giải quyết |
|---|---|---|---|
| **Phase 0** | Cleanup + Foundation | ✅ DONE (2026-05-16) | Tạo `tools/snapshot_baseline.py` (`P0.0`); xoá `learning/optimizer.py` ~450 LOC (`P0.2 Batch A`, `07ecec4`); xoá `StepConfig/ChainConfig/PipelineConfig` + `learning/migrator.py` ~330 LOC (`P0.3 Batch B`); tạo `docs/MIGRATION_NOTES.md` + `--bulk-relearn` (`P0.5`). |
| **Phase 1** | Output Mode Abstraction | ✅ DONE (2026-05-16) | Tạo `RunConfig` + `--output-mode` (`P1.1`); định nghĩa `CleanedChapter`, `ImageRef`, `FormattingRules` (`P1.2`); tạo `writers/base.py::ChapterWriter` (`P1.3`) và `writers/obsidian.py::ObsidianWriter` (`P1.4`); refactor pipeline trả về `CleanedChapter` thay vì ghi file trực tiếp (`P1.5`). |
| **Phase 2** | Image Support | ✅ DONE (2026-05-16) | Thêm `utils/image_url.py::resolve_image_url` (`P2.1`); `ImageFetchStrategy` ABC + `WebImageFetcher` (`P2.2`); mở rộng `MarkdownFormatter` xử lý `<img>` (`P2.3`); thu thập `ctx.image_refs` (`P2.4`); thêm `_apply_image_stage` mode-aware trong `core/scraper.py` (`P2.5`) và AI#image detection (`P2.6`). |
| **Phase 3** | EPUB Adapter | ✅ DONE (2026-05-16) | Tạo `ingest/router.py` tự nhận diện loại input (`P3.1`); `ingest/epub.py` đọc spine + Dublin Core metadata + body fallback (`P3.2`); `EpubImageExtractor` đọc ảnh từ zip (`P3.3`); `core/orchestrator.py::run_epub_flow` + `epub:` AdsFilter namespace (`P3.4`). |
| **Phase 4** | Translation + Raw Writers | ✅ DONE (2026-05-17) | Thêm `TranslationWriter` chèn `[IMAGE: alt]` (`P4.1`), `RawWriter` chỉ giữ text thuần (`P4.2`), và `writers/factory.py::build_writer()` + `_apply_epub_image_stage` (`P4.3`). |
| **Phase 5** | TXT Adapter | ✅ DONE (2026-05-17) | Tạo `data/txt_cases.json` (`P5.1`), `ingest/txt.py` tách chương VN+EN bằng regex + AI fallback kèm verify 3 đoạn giữa file (`P5.2`), `core/orchestrator.py::run_txt_flow` + `txt:` AdsFilter namespace (`P5.3–P5.5`). |
| **Phase 6** | Final Cleanup + Docs | ✅ DONE (2026-05-17) | Audit codebase (`P6.1`); thực hiện Batch C safe subset (`P6.2`: xoá 19 unused imports, bỏ 22 f-prefix thừa, chuyển `RawDocument` sang `ingest/types.py`, inline `_title_from_url` & xoá `core/extractor.py`, xoá `ingest/web.py`); hoàn thiện `README.md`, `CHANGELOG.md`, `TROUBLESHOOTING.md` (`P6.3–P6.4`). |

---

## 2. Các Bản Cập Nhật Sau v1.0 (`v1.0.13` → `v1.2.1`)

| Phiên bản | Ngày | Những vấn đề thực tế đã giải quyết |
|---|---|---|
| **v1.0.13** | 2026-05-17 | Sửa lỗi `_title_from_url` nhận nhầm đường dẫn file EPUB; thêm 4-strategy image path resolver cho `EpubImageExtractor`; giới hạn `MAX_SPINE_CHUNKS`. |
| **v1.1.0** | 2026-05-18 | Sửa lỗi Web flow bỏ qua `--output-dir` (`5588e33`); gộp trang ngăn cách Part/Level/Book trong EPUB (`70e4386`); thêm `ApiKeyPool` xoay vòng nhiều key Gemini (`2d36253`); thêm `CalibrationPhase` hậu kiểm profile sau khi học (`7aa8f57`); hỗ trợ EPUB không có TOC qua TXT pattern (`b4944d2`). |
| **v1.1.1** | 2026-05-19 | Sửa 6 lỗi thực tế (`f9d90bc`): auto-heal `0000_Index.md`, kiểm tra truyện đã hoàn thành có chương mới (Branch 136), hỗ trợ thư mục inbox cho EPUB/TXT. |
| **v1.2.0** | 2026-05-19 | Thêm `asyncio.Semaphore(PER_HOST_MAX_CONCURRENCY=3)` trong `DomainSessionPool` chống bị ban IP khi chạy song song (`c54ed58`, `Decision #57`). |
| **v1.2.1** | 2026-05-19 → 2026-11-09 | Chống AI bịa selector (`_discover_content_selector`, `ce6d6e0`); ưu tiên tạo `0000_Index.md` khi nhấn Ctrl+C; khôi phục `MAX_EMPTY_STREAK` guard trong `src/core/scraper.py` (`bad058c`); chặn vòng lặp vô tận `slug_increment` ở chương cuối RoyalRoad (`bad058c`); sửa false-positive `TITLE_FALLBACK` và ghi nhận đúng `ctx.nav_method` (`b74eabf`). |

---

## 3. Các Hạng Mục Chuyển Tiếp (Phase 7+ / Backlog)

Mọi tính năng mở rộng và các lỗi phát hiện mới trong quá trình chạy thực tế (§7.3 Large EPUB >300 docs, §7.4 Webnovel UI noise, §7.5 RoyalRoad `<style>`-hidden watermark, P1 Baseline, P4 FlowSpec) được quản lý tập trung tại **[`docs/V1_1_BACKLOG.md`](V1_1_BACKLOG.md)**.
