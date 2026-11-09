# Project Retrospective — Cào Text (v1.0.0 → v1.2.1)

> **Ship v1.0.0**: 2026-05-17 | **Cập nhật v1.2.1**: 2026-11-09

Tài liệu này tóm tắt ngắn gọn kết quả đạt được, các bài học thiết kế quan trọng và trạng thái giải quyết các nợ kỹ thuật (tech debt) từ v1.0.0 đến v1.2.1.

---

## 1. Kết Quả Đạt Được

- **3 nguồn đầu vào × 3 chế độ đầu ra**: Web URL, EPUB, TXT → Obsidian Markdown (kèm ảnh), Translation plain text (`[IMAGE: alt]`), Raw text.
- **Kỷ luật kiến trúc**: Tuân thủ nghiêm ngặt STOP rules (`CLAUDE.md` §10), Scope Lock (§3) và thứ tự Phase (`Decision #17`: làm Output Abstraction ở Phase 1 trước khi làm Image Support ở Phase 2).
- **Chi phí AI khấu hao**: Chỉ tốn ~8 lần gọi AI khi học site mới (`SiteProfile`), các lần cào sau chạy hoàn toàn bằng selector đã lưu.

---

## 2. Trạng Thái Giải Quyết Các Vấn Đề Sau v1.0.0

Toàn bộ các lỗi phát sinh khi smoke test v1.0.0 và vận hành thực tế đến v1.2.1 đã được giải quyết:

| Vấn đề phát hiện ở v1.0 / v1.1 | Giải pháp đã áp dụng | Trạng thái |
|---|---|---|
| **EPUB Bug 1: Tên file chương bị dính đường dẫn ổ đĩa** | `_title_from_url` từ chối chuỗi đường dẫn file nội bộ không có `://`. | ✅ Đã sửa (v1.0.13) |
| **EPUB Bug 2: Không tìm thấy ảnh có đường dẫn tương đối `../images/`** | Thêm 4-strategy path resolution + fallback basename trong `EpubImageExtractor`. | ✅ Đã sửa (v1.0.13) |
| **EPUB Bug 3: Tách chương quá vụn ở các trang Part/Book divider** | Thêm `_merge_dividers` gộp các trang tiêu đề Part/Level/Book vào chương liền sau. | ✅ Đã sửa (v1.1.0, `70e4386`) |
| **Web flow bỏ qua cờ `--output-dir`** | Truyền `run_config.output_dir` vào `_output_dir()` và `_progress_path()` trong `main.py`. | ✅ Đã sửa (v1.1.0, `5588e33`) |
| **1 API key Gemini dễ nghẽn `503` / `429`** | Xây dựng `ApiKeyPool` xoay vòng nhiều key kèm cooldown thông minh. | ✅ Đã sửa (v1.1.0, `2d36253`) |
| **AI sinh selector không khớp HTML thật** | Thêm `CalibrationPhase` (`7aa8f57`) + `_discover_content_selector` (`ce6d6e0`) tự dò wrapper chứa văn bản. | ✅ Đã sửa (v1.1.0 / v1.2.1) |
| **Không giới hạn số kết nối đồng thời trên cùng 1 domain** | Thêm `asyncio.Semaphore(PER_HOST_MAX_CONCURRENCY=3)` trong `DomainSessionPool`. | ✅ Đã sửa (v1.2.0, `c54ed58`) |
| **Mất `MAX_EMPTY_STREAK` guard & lặp vô tận chương cuối RoyalRoad** | Khôi phục `empty_streak` trong `core/scraper.py`; chặn `slug_increment` khi URL có dạng `/chapter/<id>/<slug>`; sửa false-positive `TITLE_FALLBACK`. | ✅ Đã sửa (v1.2.1, `bad058c`, `b74eabf`) |

---

## 3. Các Vấn Đề Còn Mở (Theo Dõi Tại `docs/V1_1_BACKLOG.md`)

Các vấn đề mới phát hiện ngày 2026-11-09 và các hạng mục refactor còn lại được ghi chi tiết tại **[`docs/V1_1_BACKLOG.md`](V1_1_BACKLOG.md)**:
1. **§7.3**: EPUB dài tập (>300 spine docs) bị cắt cụt JSON ở `ai_analyze_epub_structure` (~doc #830) làm gộp chương 831–1500, và `AdsFilter` xoá nhầm câu thoại ngắn lặp lại ≥10 lần.
2. **§7.4**: `www.webnovel.com` dùng selector rộng `div.cha-page` làm dính chữ UI cuối chương, thông tin sách ở Chương 1 và số đếm comment cuối đoạn.
3. **§7.5**: `www.royalroad.com` chèn đoạn văn `<p>` chống cào ẩn bằng thẻ `<style>` động (cần quét rule CSS ẩn trong `src/core/html_filter.py` trước khi decompose `<style>`).
4. **P1 & P4 (§0.1, §1.1, §1.2)**: Chụp baseline vào `data/baselines/` trước khi gộp `FlowSpec` và `_apply_image_stage`.
