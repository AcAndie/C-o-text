# Changelog

All notable changes to Cào Text. Format based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), versioning per [Semantic Versioning](https://semver.org/).

---

## [1.2.1] — 2026-05-19 → 2026-11-09

AI hallucination hardening, Ctrl+C resilience, and scrape loop / navigation termination fixes.

### Added
- **Auto-discover content selector** (`src/learning/phase.py:_discover_content_selector`) — Fallback khi calibration M0 fail: quét HTML tìm `<div/section/article/main>` có ≥2 text-bearing children, xếp hạng theo `(hit_count, avg_len)`.
- **Startup index auto-heal** (`main.py:_heal_missing_indexes`) — Tự tạo lại `0000_Index.md` cho các thư mục truyện có chương `.md` nhưng bị thiếu index (do Ctrl+C giữa chừng).
- **AI prompt anti-hallucination constraints** (`src/ai/prompts.py`, `src/ai/agents.py`) — Bắt buộc trường `evidence_title/content/next` trích dẫn 50–150 ký tự HTML thực tế; gộp cờ `suspected_js_render` vào `requires_playwright`.

### Fixed
- **Restore `MAX_EMPTY_STREAK` guard** (`src/core/scraper.py:_run_scrape_loop`, `bad058c`) — Khôi phục bộ đếm `empty_streak` dừng cào sau `MAX_EMPTY_STREAK` (5) chương rỗng liên tiếp, reset về 0 khi có chương hợp lệ.
- **RoyalRoad `slug_increment` infinite loop fix** (`src/pipeline/navigator.py`, `src/core/navigator.py`, `bad058c`) — Chặn đoán URL chương kế bằng `slug_increment` khi URL có dạng `/chapter/<id>/<slug>` (ID riêng mỗi chương), dừng chuẩn xác `🏁 Hết truyện` ở chương cuối.
- **`TITLE_FALLBACK` false-positive & `nav_method` log** (`src/core/scraper.py`, `b74eabf`) — Kiểm tra `ctx.block_results.get("title:url_slug")` trước khi báo `TITLE_FALLBACK` và ghi nhận đúng `ctx.nav_method` vào log tiến độ.
- **DensityHeuristic prefer wrapper over leaf** (`src/pipeline/extractor.py:_score_element`) — Cộng wrapper bonus 1.5x khi text ≥1000c + ≥5 đoạn văn để không chọn nhầm 1 thẻ `<p>` lẻ.
- **Ctrl+C cleanup order** (`src/core/scraper.py:run_novel_task`) — Chạy `nav_injector` tạo `0000_Index.md` trước `finalize_ads` và `pm.flush` trong khối `finally`.
- **Naming merge fail-loud guard** (`src/core/scraper.py:_setup_story`) — Kiểm tra `story_name_clean`/`output_dir_final` đã lưu xuống đĩa sau khi merge naming.
- **Index link `[ ]` escape** (`src/writers/nav_injector.py:_md_link`) — Escape `\[`, `\]`, `\\` trong tên chương và bọc URL bằng `<...>`.

### Changed
- Đồng bộ `VERSION = "1.2.1"` trong `src/config.py` và khôi phục `data/baselines/.gitkeep` (`bad058c`).
- Đưa `lxml`, `playwright`, `playwright-stealth` thành dependencies chính thức trong `requirements.txt`; cập nhật `.gitignore` bỏ qua toàn bộ `Vault/.obsidian/`.

---

## [1.2.0] — 2026-05-19

### Added
- **DomainSessionPool per-host concurrency cap** (`c54ed58`) — Giới hạn mặc định `asyncio.Semaphore(PER_HOST_MAX_CONCURRENCY=3)` trên mỗi domain cho cả `fetch()` và `fetch_bytes()`, cấu hình qua `PER_HOST_MAX_CONCURRENCY` hoặc `--per-host-concurrency N` (`Decision #57`).

### Changed
- Rà soát `docs/V1_1_BACKLOG.md` §7: chuyển các giả thuyết tối ưu chưa có số đo thực tế xuống §7.99; xoá thông tin username Windows khỏi các tài liệu (`7ec1413`).

---

## [1.1.1] — 2026-05-19

- **Batch fix 6 lỗi thực tế** (`f9d90bc`, `b4944d2`, `820f432`):
  - EPUB không có TOC tự động fallback sang bộ tách chương theo regex TXT (`b4944d2`).
  - `ApiKeyPool` bỏ qua thời gian chờ backoff nếu trong pool còn key khác sẵn sàng (`820f432`).
  - Kiểm tra chương mới cho các truyện đã `completed=True` (Branch 136).

---

## [1.1.0] — 2026-05-18

### Added
- **In-repo Obsidian Vault layout** (`0e7b6f9`) — Chuyển đầu ra vào `Vault/Novels/` và hộp thư đầu vào tại `Vault/_Scraper/{links.md, issues.md, epub_inbox/}`.
- **Webnovel.com fast-path chapter 1** (`8fb7c31`) — Tự động chọn chương 1 trên `webnovel.com` bằng cách sort chapter ID nhỏ nhất từ trang mục lục (không tốn AI call).
- **Multi-key Gemini pool** (`2d36253`) — `ApiKeyPool` đọc `GEMINI_API_KEY` + `GEMINI_API_KEY_\d+`, xoay vòng round-robin kèm cooldown 60s khi gặp lỗi `429`/`503`.
- **Post-learning Calibration Phase** (`7aa8f57`, `a769ec8`) — Hậu kiểm 3 chiều (`content_selector`, `title_selector`, `remove_selectors`) trên 5 chương mẫu sau Master Synthesis.

### Fixed
- **Markdown escape** (`748c58c`) — Escape ký tự `*` và `` ` `` nguyên bản trong văn bản HTML để chuỗi `*****` không làm hỏng định dạng in nghiêng/đậm của Obsidian.
- **ConnectError retry** (`987ca86`) — Mở rộng nhận diện lỗi mạng tạm thời (`ConnectError`, `ConnectTimeout`) để tự động retry.
- **EPUB divider merge** (`70e4386`) — Gộp các trang ngăn cách Part/Level/Book/Volume vào chương liền sau trong `src/ingest/epub_structure.py`.
- **`--output-dir` CLI cho Web** (`5588e33`) — Truyền `run_config.output_dir` vào `_output_dir()` và `_progress_path()` trong `main.py`.

---

## [1.0.1] — [1.0.28] — 2026-05-17 → 2026-05-18 (Consolidated Summary)

Chuỗi bản vá liên tục ngay sau khi phát hành `v1.0.0`, giải quyết các vấn đề thực tế trên RoyalRoad, ScribbleHub, FanFiction.Net và EPUB:

- **v1.0.18–v1.0.28**: Chống watermark RoyalRoad & khoảng trắng braille `U+2800`; sửa chọn nhầm Story ID và `h2.comments-title` trên ScribbleHub; bảo vệ `inject_nav_and_index` bằng `asyncio.shield` khi Ctrl+C; làm sạch hậu tố tên trang trên tiêu đề chương.
- **v1.0.17**: Sửa lỗi chương EPUB bị cắt cụt ở ~8KB do rơi vào `AIExtract` (`snippet(8000)`) — chuyển sang đọc thẳng toàn bộ `<body>` bằng `MarkdownFormatter`.
- **v1.0.14–v1.0.16**: Xây dựng `src/ingest/epub_structure.py` (Tier 1 rule-based + Tier 2 AI analyzer có cache `data/epub_analyses.json`), gộp Front/Back Matter vào `0000_Front_Matter.md`, lọc bỏ trang quảng cáo sách khác (`SKIP_KEYWORDS`), và sửa lỗi gộp nhiều thẻ `<body>` làm rỗng nội dung.
- **v1.0.13**: Sửa 3 lỗi EPUB: (1) `_title_from_url` từ chối đường dẫn file Windows không có scheme `http/https`, (2) giữ nguyên dòng trống `\n\n` giữa các đoạn văn trong `_strip_unicode_blank_lines`, (3) thêm `OPS/` + `posixpath.normpath` + basename fallback cho `EpubImageExtractor`.
- **v1.0.11–v1.0.12**: Tạo `src/writers/nav_injector.py` sinh mục lục `0000_Index.md` và thanh điều hướng `[← Prev] | [🏠 Index] | [Next →]` ở đầu/cuối mỗi chương; tự gom bảng chỉ số LitRPG thành callout `> [!info]+ Status` và sửa lỗi bold `**X: **Y`.
- **v1.0.6–v1.0.10**: Chuyển toàn bộ mã nguồn vào `src/`, tài liệu nội bộ vào `docs/`; thêm cấu hình `config.toml`; thêm cơ chế quét tự động thư mục `epub_inbox` kèm lưu vết SHA256 trong `data/processed_epubs.json`; sửa lỗi crash dây chuyền trong `html_filter.py` bằng helper `_is_alive(el)`.
- **v1.0.1–v1.0.5**: Thêm Phase 0 `url_classifier.py` tự động chuyển URL trang mục lục về chương 1; thêm Layer 1b (`_strip_obfuscated_class_elements`) và Layer 1c (`_strip_invisible_elements`) trong `html_filter.py`; chặn `SelectorTitleBlock` chọn nhầm các thẻ danh sách (`<select>`, `<nav>`, `<ul>`, `<table>`).

---

## [1.0.0] — 2026-05-17

Phiên bản hoàn chỉnh đầu tiên hỗ trợ 3 nguồn đầu vào (`web`, `epub`, `txt`) × 3 chế độ đầu ra (`obsidian`, `translate`, `raw`):
- **Phase 0 (Foundation)**: Tạo `tools/snapshot_baseline.py`, `--bulk-relearn`, xoá ~780 LOC dead code (`learning/optimizer.py`, `learning/migrator.py`, `StepConfig`).
- **Phase 1 (Output Mode Abstraction)**: Tạo `RunConfig`, `CleanedChapter`, `ImageRef`, `FormattingRules`, `ChapterWriter` ABC và `ObsidianWriter`.
- **Phase 2 (Image Support)**: Tạo `resolve_image_url`, `ImageFetchStrategy` (`WebImageFetcher`), mở rộng `MarkdownFormatter` cho thẻ `<img>` và bước `_apply_image_stage` theo từng output mode.
- **Phase 3 (EPUB Adapter)**: Tạo `ingest/router.py`, `ingest/epub.py`, `EpubImageExtractor`, `core/orchestrator.py::run_epub_flow` và namespace `epub:{slug}` cho `AdsFilter`.
- **Phase 4 (Translation + Raw Writers)**: Tạo `TranslationWriter`, `RawWriter` và `writers/factory.py::build_writer()`.
- **Phase 5 (TXT Adapter)**: Tạo `data/txt_cases.json`, `ingest/txt.py` (regex VN+EN + AI fallback kèm verify 3 đoạn giữa file) và `run_txt_flow`.
- **Phase 6 (Final Cleanup + Docs)**: Thực hiện Batch C safe subset (`docs/AUDIT_PHASE6.md`) và hoàn thiện bộ tài liệu `README.md`, `TROUBLESHOOTING.md`, `V1_1_BACKLOG.md`.
