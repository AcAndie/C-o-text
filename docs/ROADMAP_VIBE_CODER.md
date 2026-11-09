# Archived: Vibe-Coder Execution Playbook (v1.0 Phases 0–6)

> **Trạng thái**: ✅ **ĐÃ HOÀN THÀNH 100% (Archived 2026-11-09)**
> Toàn bộ 7 Phase (Phase 0 → Phase 6) trong kịch bản prompt copy-paste dài 2,415 dòng này đã được thực thi xong và phát hành từ `v1.0.0` đến `v1.2.1`. Nội dung prompt chi tiết từng bước đã được lược bỏ để giữ bộ tài liệu gọn nhẹ.

---

## Tóm Tắt Những Gì Playbook Này Đã Giải Quyết

| Phase | Nội dung đã triển khai |
|---|---|
| **Phase 0 — Cleanup + Foundation** | Tạo `tools/snapshot_baseline.py`, xoá `learning/optimizer.py` (Batch A) và `StepConfig/ChainConfig/PipelineConfig` + `learning/migrator.py` (Batch B), thêm `--bulk-relearn`. |
| **Phase 1 — Output Mode Abstraction** | Xây dựng `RunConfig`, `CleanedChapter`, `ImageRef`, `FormattingRules`, `writers/base.py::ChapterWriter`, `writers/obsidian.py::ObsidianWriter`. |
| **Phase 2 — Image Support** | Xây dựng `resolve_image_url`, `ImageFetchStrategy`, `WebImageFetcher`, mở rộng `MarkdownFormatter` cho `<img>`, và thêm `_apply_image_stage` mode-aware. |
| **Phase 3 — EPUB Adapter** | Xây dựng `ingest/router.py`, `ingest/epub.py`, `EpubImageExtractor`, và `core/orchestrator.py::run_epub_flow`. |
| **Phase 4 — Translation + Raw Writers** | Xây dựng `TranslationWriter`, `RawWriter`, và `writers/factory.py::build_writer()`. |
| **Phase 5 — TXT Adapter** | Xây dựng `data/txt_cases.json`, `ingest/txt.py` (regex VN+EN + AI fallback + 3-chunk verify), và `core/orchestrator.py::run_txt_flow`. |
| **Phase 6 — Final Cleanup + Docs** | Thực hiện Batch C safe subset (`docs/AUDIT_PHASE6.md`) và hoàn thiện bộ tài liệu `README.md`, `CHANGELOG.md`, `TROUBLESHOOTING.md`, `V1_1_BACKLOG.md`. |

- Xem tóm tắt kết quả từng phase tại [`docs/ROADMAP.md`](ROADMAP.md).
- Xem các vấn đề đang chờ xử lý tiếp theo tại [`docs/V1_1_BACKLOG.md`](V1_1_BACKLOG.md).
