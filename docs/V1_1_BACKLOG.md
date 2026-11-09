# v1.1+ Backlog — Open Issues & Deferred Features

> **Updated**: 2026-11-09 (post v1.2.1 fixes & live Webnovel / RoyalRoad / EPUB audits)
> Các hạng mục đã hoàn thành được tóm tắt ngắn gọn ở bảng **Đã Giải Quyết** bên dưới (đã xoá phần spec dài dòng). Phần thân tài liệu chỉ giữ lại các vấn đề **đang chờ xử lý** hoặc **deferred**.

---

## ✅ Đã Giải Quyết (Resolved Summary — v1.0.13 → v1.2.1)

| Hạng mục | Phiên bản / Commit | Vấn đề & Giải pháp đã áp dụng (ngắn gọn) |
|---|---|---|
| **P2 — EPUB Bug 1 (Title path fallback)** | v1.0.13 | `_title_from_url` bỏ qua local file path (không có `://`) để tránh lấy đường dẫn ổ đĩa làm tên file chương. |
| **P2 — EPUB Bug 2 (Image href relative)** | v1.0.13 | `EpubImageExtractor` thêm 4-strategy path resolution + basename fallback cho `../images/...`. |
| **P2 — EPUB Bug 3 (Over-split chapters)** | v1.1.0 (`70e4386`, `b4944d2`) | `_merge_dividers` gộp các trang ngăn cách Part/Level/Book vào chương kế tiếp + fallback tách theo TXT pattern khi EPUB thiếu TOC. |
| **P2 — Web `--output-dir` CLI bị bỏ qua** | v1.1.0 (`5588e33`) | `main.py` truyền `run_config.output_dir` / `config.toml [output] dir` vào luồng Web thay vì hardcode `OUTPUT_DIR`. |
| **P3 — Multi-key Gemini rotation** | v1.1.0 (`2d36253`, `820f432`) | `ApiKeyPool` xoay vòng nhiều key (`GEMINI_API_KEY_*`) kèm cooldown khi gặp `429`/`503`, bỏ qua sleep nếu còn key rảnh. |
| **§2.2 — Calibration Phase** | v1.1.0 (`7aa8f57`) | Probe 3 chiều sau Master Synthesis để verify `content_selector` / `title_selector` / `next_selector` trên mẫu thực tế. |
| **P6 / §0.6 — Per-host concurrency cap** | v1.2.0 (`c54ed58`) | `DomainSessionPool` dùng `asyncio.Semaphore(PER_HOST_MAX_CONCURRENCY=3)` mỗi domain + cờ `--per-host-concurrency N` (`Decision #57`). |
| **Webnovel AI selector hallucination & Ctrl+C Index** | v1.2.1 (`ce6d6e0`, `dd288bc`) | `_discover_content_selector` tự tìm wrapper khi AI bịa selector; `DensityHeuristic` ưu tiên wrapper; `_heal_missing_indexes` tự phục hồi `0000_Index.md` khi Ctrl+C. |
| **Restore `MAX_EMPTY_STREAK` guard** | v1.2.1 (`bad058c`) | Khôi phục bộ đếm `empty_streak` trong `src/core/scraper.py`: dừng cào sau `MAX_EMPTY_STREAK` (5) chương rỗng liên tiếp, reset về 0 khi có chương hợp lệ. |
| **Fix RoyalRoad `slug_increment` lặp vô tận chương cuối** | v1.2.1 (`bad058c`) | Chặn `slug_increment` trong `src/pipeline/navigator.py` & `src/core/navigator.py` khi URL có dạng `/chapter/<id>/<slug>` (ID riêng mỗi chương). |
| **Fix `TITLE_FALLBACK` false-positive & `nav_method` log** | v1.2.1 (`b74eabf`) | Check `ctx.block_results.get("title:url_slug")` trước khi báo `TITLE_FALLBACK`; ghi `ctx.nav_method` thực tế vào log tiến độ (`src/core/scraper.py`). |
| **Sync `VERSION` & `data/baselines/.gitkeep`** | v1.2.1 (`bad058c`) | Đồng bộ `VERSION = "1.2.1"` trong `src/config.py` và khôi phục `data/baselines/.gitkeep`. |

---

## 🎯 Priority Queue Đang Chờ Xử Lý (Open Issues)

| Mục | Nội dung | Phân loại | Khi nào làm |
|---|---|---|---|
| **§7.3** | **Large EPUB (>300 docs) AI token limit & missing `doc_ids` guard + `AdsFilter` xoá nhầm câu thoại ngắn** | EPUB / Bug | **Phiên tới** (đã gặp trên bộ 1300–1600 chương) |
| **§7.4** | **`www.webnovel.com` dính chữ UI (`div.cha-page` rộng, footer Vote/Power, header Ch.1, số comment cuối đoạn)** | Web / Profile | **Phiên tới** (đã gặp khi cào 20 chương Webnovel) |
| **§7.5** | **`www.royalroad.com` lọt câu cảnh báo chống trộm ẩn bằng `<style>` động trong `html_filter.py`** | Web / Filter | **Phiên tới** (đã gặp khi cào 21 chương RoyalRoad) |
| **P1 (§0.1)** | **Baseline capture (`tools/snapshot_baseline.py` → `data/baselines/`)** | Test / Infra | Trước khi làm refactor §1.1 & §1.2 |
| **P4 (§1.1)** | **FlowSpec — gộp `run_epub_flow` + `run_txt_flow` trong `core/orchestrator.py`** | Refactor | Sau khi có baseline P1 hoặc thêm adapter thứ 3 |
| **§1.2** | **Tách `_apply_image_stage` dùng chung giữa `scraper.py` và `orchestrator.py`** | Refactor | Làm cùng P4 sau khi có baseline P1 |
| **P5 (§0.5)** | **Cross-platform smoke test (Linux + macOS)** | Infra | Khi cần chạy ngoài Windows |
| **§7.2** | **Pyflakes linting cleanup (2 chỗ nhỏ)** | Code health | Tiện tay gom vào commit kế tiếp |

---

## 0. Các Hạng Mục P1 & P5 Còn Mở

### 0.1 — P1: Baseline capture infrastructure
- **Lý do**: `tools/snapshot_baseline.py` đã có nhưng `data/baselines/` mới chỉ có `.gitkeep`. Mọi refactor hành vi (§1.1 FlowSpec, §1.2 image stage extract) đều cần baseline để diff.
- **Việc cần làm**: Chạy `tools/snapshot_baseline.py` chụp 3 site web + 2 EPUB + 2 TXT lưu vào `data/baselines/`.

### 0.5 — P5: Cross-platform smoke
- **Lý do**: Dev hoàn toàn trên Windows (`_silence_transport_errors` trong `main.py`). Cần chạy thử 3 output modes trên Ubuntu + macOS.

---

## 1. Behavioral Refactors (Deferred từ Phase 6)

### 1.1 — P4: FlowSpec — unify `run_epub_flow` + `run_txt_flow`
- **Nguồn**: `docs/AUDIT_PHASE6.md` §4.1, `CLAUDE.md` Decision #55 (~80 LOC trùng lặp trong `src/core/orchestrator.py:90-314`).
- **Hướng làm**: Gom vào `_run_file_flow(spec: FlowSpec, run_config, ai_limiter)` khi đã chụp baseline P1.

### 1.2 — `_apply_image_stage` extract to shared helper
- **Nguồn**: `docs/AUDIT_PHASE6.md` §5.3, `CLAUDE.md` Decision #49 (~60 LOC trùng lặp giữa `core/scraper.py::_apply_image_stage` và `core/orchestrator.py::_apply_epub_image_stage`).
- **Hướng làm**: Đưa về `core/image_pipeline/stage.py::apply_image_stage(...)` nhận `ImageFetchStrategy`.

---

## 2. Web Learning Enhancements (Deferred)

- **§2.1 — Case-based learning cho web (`Decision #15`)**: Chờ khi `data/site_profiles.json` có 10+ profiles ổn định để rút trích quy luật chung.

---

## 3. i18n Expansion (Deferred)

- **§3.1 — Site CJK hardening (Trung / Nhật / Hàn raw)**: Encoding heuristic (`charset-normalizer`), font deobfuscation, slugify pinyin/katakana, chapter regex `第N章` / `第N話` / `제N장`.
- **§3.2 — TXT v1.1 expanded language cases**: Bổ sung pattern CJK vào `data/txt_cases.json` sau khi xong §3.1.

---

## 4. Output Format Extensions (Deferred)

- **§4.1 — Frontmatter customization**: Cờ `--no-frontmatter`, `--frontmatter-fields`.
- **§4.2 — TranslationWriter chunking (`Decision #45`)**: Expose `RunConfig.chunk_threshold` ra CLI nếu dùng LLM context nhỏ (<50K).
- **§4.3 — Inline link preservation**: Giữ lại thẻ `<a>` trong bài khi user cần cào fiction dạng blog có cross-link.

---

## 5. Infrastructure / DX & 6. Web / DB (Deferred)

- **§5.1 — Multi-AI provider (Claude / OpenAI)**: Chỉ làm nếu Gemini bỏ free tier hoặc cần đổi model.
- **§5.2 — TypedDict refactor `utils/types.py` (`Decision #16`)**: Chỉ làm khi mở rộng nhiều contributor.
- **§5.3 — GUI (Streamlit / native)**: Chỉ làm khi chia sẻ cho người không dùng CLI.
- **§5.4 — Multi-domain concurrent optimization**: Đã có `asyncio.gather` + `DomainSessionPool` semaphore; chưa cần tối ưu thêm.
- **§5.5 — Manhua adapter**: Ngoài phạm vi (dùng `gallery-dl`).
- **§5.6 — Formal pytest suite & §5.7 — Lint toolchain (`ruff`/`black`)**: Chỉ làm khi nhiều người cùng phát triển.
- **§6.1 — Web UI / FastAPI & §6.2 — SQLite Database**: Không cần cho công cụ CLI cá nhân 1 người dùng.

---

## 7. Findings Thực Tế Cần Xử Lý Tiếp (2026-05-19 → 2026-11-09)

### 7.1 — Branch 136: `--check-new` flag + age skip
- **Triệu chứng**: Mỗi lần chạy đều gửi 1 HTTP request kiểm tra lại các truyện đã `completed=True`. Nếu có 50+ truyện đã hoàn thành sẽ tốn 20–60s lúc khởi động.
- **Hướng sửa**: Thêm cờ `--check-new` (mặc định ON), `--skip-check-after-days 90`, lệnh `!recheck` trong `links.txt`, và trường `completed_at` trong `ProgressDict`.

### 7.2 — Linting cleanup (pyflakes)
- `src/learning/phase.py:29` — `fetch_page` import không dùng.
- `src/ai/agents.py:1183` — f-string không có placeholder.

### 7.3 — Large EPUB (>300 docs) AI analyzer token limit & missing `doc_ids` guard (+ `AdsFilter` xoá nhầm câu ngắn)

**Nguồn**: Phát hiện ngày 2026-11-09 khi xử lý 4 bộ EPUB dài tập trong `Vault/_Scraper/epub_inbox/` (`Thả Nữ Phù Thủy Kia Ra` 1500 spine docs, `Đỉnh Cấp Khí Vận` 1626 chương, `Cultivation Chat Group` 1348 chương).

**Triệu chứng & Nguyên nhân**:
1. **Đứt chương ở doc #830 trên EPUB 1500 chương**:
   - `ai_analyze_epub_structure` gửi toàn bộ 1500 `docs_meta` trong 1 lần gọi Gemini. Output JSON của Gemini chạm trần token ở khoảng doc #831 (`page-0925.html`), làm thiếu 669 `doc_ids`.
   - `ai_analyze_epub_structure` (`src/ai/agents.py:1136-1144`) chỉ in warning rồi trả về danh sách bị cụt; `_apply_decisions` (`src/ingest/epub_structure.py:521-527`) coi toàn bộ 669 `doc_ids` bị thiếu là phần nối tiếp của chương 830 → gộp toàn bộ chương 831–1500 vào 1 file khổng lồ `0830_*.md`.
   - Trong khi đó, nhánh không có TOC (`b4944d2`) đã dùng cơ chế học quy luật theo mẫu — nhưng nhánh `build_chapter_plan_with_ai` lại bắt AI liệt kê từng `doc_id` một.
2. **`AdsFilter` tự động xoá nhầm câu thoại/chuyển cảnh ngắn trong EPUB >1000 chương**:
   - Với `auto_threshold = 10` cố định (không qua AI verify), trong bộ 1300–1600 chương các câu ngắn xuất hiện ≥10 lần ở đầu/cuối chương (ví dụ: `"Hàn Tuyệt nói:"`, `"Một ngày nọ."`, `"Cùng lúc đó."`, `"Song Shuhang: \"...\""`) bị đánh dấu nhầm là quảng cáo và xoá tự động.

**Kế hoạch sửa cho phiên tới**:
1. Trong `src/ingest/epub_structure.py:build_chapter_plan_with_ai`: nếu `len(meta) > 250` (hoặc ngưỡng cấu hình), không bắt AI liệt kê JSON toàn bộ từng spine item mà dùng thẳng `build_chapter_plan(book)` theo quy luật (hoặc chỉ gửi mẫu đầu/giữa/cuối để AI học rule).
2. Trong `src/ai/agents.py:ai_analyze_epub_structure`: nếu `len(missing) > max(5, int(len(input_ids) * 0.05))`, trả về `None` để caller fallback an toàn về `build_chapter_plan(book)`.
3. Trong `src/utils/ads_filter.py`: scale `auto_threshold` theo tổng số chương (ví dụ `max(10, int(n_chapters * 0.03))`) hoặc yêu cầu độ dài tối thiểu / tín hiệu URL-watermark trước khi auto-strip không qua AI verify.

### 7.4 — `www.webnovel.com`: Dính chữ UI chrome (`div.cha-page` wrapper & thiếu `remove_selectors`)

**Nguồn**: Phát hiện ngày 2026-11-09 khi cào thử 20 chương trên `www.webnovel.com` (`In Danmachi with Plasmids (New Version)` và `Zero Fate Against the World (New Version)`).

**Triệu chứng**:
1. AI học `"content_selector": "div.cha-page"` (container bao ngoài toàn trang của Webnovel) thay vì container hẹp chỉ chứa văn bản chương (`div.cha-words` / `div.cha-content`).
2. **Cuối mỗi chương**: Dính các khối UI tương tác của Webnovel: `Notes`, `comment / N comment`, `Vote`, `Load failed, please RETRY`, `Weekly Power Status / -- / Power Ranking / -- / Power stone / Vote`.
3. **Đầu Chương 1**: Dính khối thông tin sách (`original`, tên truyện, `**Author:** ...`, `© WebNovel`, lặp `# Chapter 1: ...`, lặp ảnh bìa).
4. **Cuối mỗi đoạn văn**: Dính số lượng bình luận inline (para-comment badge) dính sát cuối câu (ví dụ: `...wanting to let it grow. 1`, `...mistake them for Skills]1`).

**Kế hoạch sửa cho phiên tới**:
- Thu hẹp `content_selector` cho `www.webnovel.com` về `div.cha-words` (hoặc `div.cha-content`) và bổ sung các selector UI của Webnovel (`.cha-hd`, `.cha-foot`, `.j_bottom_comment_area`, `.para-comment`, `.g_ad`, v.v.) vào `remove_selectors` / `KNOWN_NOISE_SELECTORS`.

### 7.5 — `www.royalroad.com`: Lọt câu cảnh báo chống trộm ẩn bằng thẻ `<style>` động

**Nguồn**: Phát hiện ngày 2026-11-09 khi cào 21 chương bộ `Rock falls, everyone dies` trên `www.royalroad.com`.

**Triệu chứng**:
- Mỗi chương bị lọt 1 đoạn văn `<p>` chống cào nằm giữa chương (hoặc trong bảng status), với câu chữ thay đổi ngẫu nhiên theo từng chương (ví dụ: *"This chapter was copied from Royal Road without the author's permission..."*, *"Who approved this copy? Not the author..."*, *"A question of provenance: the author publishes this chapter on Royal Road..."*).
- Do nội dung câu chữ đổi mới ở mỗi chương, `AdsFilter` đếm tần suất lặp xuyên chương không bắt được.

**Nguyên nhân gốc (`src/core/html_filter.py`)**:
1. RoyalRoad gắn class random dài 40+ ký tự cho **mọi** thẻ `<p>` trong `div.chapter-content`, nên `_strip_obfuscated_class_elements` (`html_filter.py:98-105`) phải bỏ qua thẻ `<p>` để không xoá nhầm nội dung truyện.
2. RoyalRoad ẩn riêng thẻ `<p>` chứa watermark bằng một thẻ `<style>` trong trang HTML (ví dụ `.cjBiZWI... { display: none; }` hoặc `speak: never`, `font-size: 0`).
3. Tuy nhiên, `prepare_soup` (`html_filter.py:270`) lại `decompose()` toàn bộ thẻ `<style>` ngay ở Layer 1 (`_ALWAYS_REMOVE`) trước khi đọc rule CSS bên trong, còn `_strip_invisible_elements` (`html_filter.py:208-228`) chỉ kiểm tra inline `style="..."` và danh sách `_HIDDEN_CLASSES` cố định.

**Kế hoạch sửa cho phiên tới**:
- Trong `src/core/html_filter.py:prepare_soup`, **trước khi** xoá thẻ `<style>`, dùng regex quét nội dung các thẻ `<style>` để tìm các class/id selector có thuộc tính khớp `_HIDDEN_STYLE_RE` (`display\s*:\s*none`, `visibility\s*:\s*hidden`, `opacity\s*:\s*0`, `font-size\s*:\s*0`, `speak\s*:\s*never`), xoá các phần tử khớp class/id đó khỏi `soup`, rồi mới decompose thẻ `<style>`.

### 7.99 — Speculative perf concerns (Chỉ làm khi có số đo thực tế vượt ngưỡng)
- Sharding `site_profiles.json` (chỉ làm nếu `flush()` > 100ms), stream-write `IssueReporter` (chỉ làm nếu RSS > 100MB), sidecar cache cho `nav_injector`.
