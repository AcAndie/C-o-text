# CLAUDE.md

> **File này là context BẮT BUỘC Claude Code đọc TỰ ĐỘNG mỗi khi mở project.**
> ĐỪNG xóa. ĐỪNG sửa trừ khi update vision/scope ở mức kiến trúc.
> File này quyết định MỌI hành vi code của Claude Code.
>
> **Tham khảo:** Anthropic engineering blog, CLAUDE.md tốt của open-source (shadcn/ui, Vercel AI SDK), bài học đắt từ các session refactor trước (M4 serialization bug, ADS keyword corruption, cancel handling, image-before-RunConfig sequencing error).

---

## 0. Cách dùng file này

Mỗi session mới, Claude Code:
1. Đọc TOÀN BỘ file này TRƯỚC khi làm bất cứ gì
2. Đọc tiếp `docs/BLUEPRINT.md` (vision + architecture chi tiết) nếu task >5 dòng code hoặc đụng kiến trúc
3. Đọc `docs/ROADMAP.md` và `docs/V1_1_BACKLOG.md` nếu task liên quan lộ trình / lỗi đang chờ xử lý
4. Mọi quyết định code phải tuân thủ rules ở đây
5. User request conflict với rules → STOP, hỏi user, KHÔNG tự ý làm
6. File này conflict với BLUEPRINT/ROADMAP → CLAUDE.md thắng (CLAUDE = **HOW + WHY**, BLUEPRINT = **WHAT trong tổng thể**, ROADMAP = **WHAT theo lộ trình**)

**Quan trọng:** Đọc file này một lần đủ. KHÔNG đọc lại trong cùng session trừ khi user yêu cầu. Reference bằng số section (vd: "theo §6.2") thay vì quote lại nội dung.

---

## 1. Project Identity

| Field | Value |
|---|---|
| **Tên codename** | Cào Text |
| **Loại** | Single-user CLI tool — universal novel content normalizer |
| **Stage** | **v1.2.1 shipped** — Toàn bộ Phases 0–6 đã hoàn thành; đang ở giai đoạn bảo trì & xử lý backlog thực tế (`docs/V1_1_BACKLOG.md`) |
| **Owner** | Solo dev — vibe coder, không rành code chi tiết, dùng Claude Code, giao tiếp tiếng Việt |
| **Inspiration** | FanFicFare (scope rộng + maintenance lâu năm), gallery-dl (extractor plugin pattern), Trafilatura (extraction heuristics), QuickTranslator (consistency through dictionary layer) |
| **Platform** | Windows desktop (`C:\Users\<user>\Desktop\Small Project\Cào text`) |
| **Runtime** | Python 3.11+ async (`asyncio`) |

---

## 2. Vision (1 dòng)

**"Ném input nào vào (URL truyện đa site đa ngôn ngữ / EPUB / TXT) cũng ra được một bộ chapter sạch, không noise, đọc được trên Obsidian hoặc đem đi dịch — site mới chỉ cần học 1 lần, lần sau xài lại."**

Chi tiết vision + architecture: xem `docs/BLUEPRINT.md`.

---

## 3. Scope Lock (NGHIÊM NGẶT)

### ✅ ĐÃ CÓ TRONG CODEBASE (v1.0 → v1.2.1 — CẦN GIỮ VỮNG):

1. **Pipeline architecture** (5 chain: Fetch/Extract/Title/Nav/Validate) — `src/pipeline/`
2. **Learning phase + Calibration** (8 AI calls + Naming Phase + 3-dim Calibration + `_discover_content_selector`) — `src/learning/`
3. **HybridFetchBlock & Per-host Semaphore** (`curl_cffi` + Playwright fallback + `DomainSessionPool` semaphore) — `src/pipeline/fetcher.py`, `src/core/session_pool.py`
4. **HTML Filter & Content Cleaning** (Layer 1/1b/1c/2/3 `html_filter.py` + 7-pass `content_cleaner.py` + `AdsFilter`) — `src/core/`, `src/utils/`
5. **Output Mode Abstraction** (`RunConfig`, `CleanedChapter`, `ChapterWriter` ABC, `ObsidianWriter`, `TranslationWriter`, `RawWriter`, `nav_injector.py`) — `src/writers/`
6. **Image Pipeline (Strategy Pattern)** (`WebImageFetcher` + `EpubImageExtractor`, mode-aware `_apply_image_stage`) — `src/core/image_pipeline/`
7. **Unified Ingest** (`ingest/router.py`, `ingest/epub.py` + `epub_structure.py`, `ingest/txt.py` + `data/txt_cases.json`) — `src/ingest/`
8. **Multi-key Gemini Client** (`ApiKeyPool` round-robin + cooldown + token-bucket rate limiter) — `src/ai/client.py`
9. **In-repo Obsidian Vault Layout** (`Vault/Novels/` + `Vault/_Scraper/{links.md, issues.md, epub_inbox/}`) — `src/config.py`

### 🚫 DEFERRED (Theo dõi tại `docs/V1_1_BACKLOG.md` — KHÔNG TỰ Ý LÀM KHI CHƯA ĐƯỢC YÊU CẦU):

- ❌ **Case-based learning cho web** — chỉ làm sau khi có 10+ domain profile ổn định (`V1_1_BACKLOG.md` §2.1).
- ❌ **Truyện tranh thuần (manhua/manga)** — image-primary pipeline khác hẳn, dùng `gallery-dl`.
- ❌ **Site Trung/Nhật/Hàn CJK hardening nâng cao** — encoding heuristic, font deobfuscation, chapter pattern `第N章`/`第N話` defer cho đến khi cào nguồn CJK gốc (`V1_1_BACKLOG.md` §3.1–3.2).
- ❌ **Arc memory / Bible / Scout** — thuộc tool dịch, không phải scraper.
- ❌ **Web UI / Streamlit / FastAPI / Database (SQLite)** — CLI + JSON atomic write là đủ cho single-user.
- ❌ **TypedDict refactor `utils/types.py`** — high-risk, defer.
- ❌ **Generic article / blog scraper** — ngoài phạm vi novel chain.

### HARD RULE về scope

**Khi user request tính năng trong DEFERRED list:**
1. STOP — không code
2. Trả lời:
   > *"Tính năng [X] trong DEFERRED list của Scope Lock (CLAUDE.md §3). Lý do defer: [trích lý do]. Anh muốn:*
   > - *(a) Làm ngay bây giờ?*
   > - *(b) Ghi vào `docs/V1_1_BACKLOG.md` để làm sau?*
   > - *(c) Bỏ qua?"*
3. Chờ user quyết.

---

## 4. Tech Stack (LOCKED)

| Layer | Tech | Trạng thái |
|---|---|---|
| Language | Python 3.11+ (`asyncio`) | ✅ Đã có |
| HTTP fetch | `curl_cffi` (Chrome TLS) + `playwright` (JS fallback) | ✅ Đã có |
| HTML parsing | `beautifulsoup4` + `lxml` | ✅ Đã có |
| AI SDK | `google-genai` (Gemini API + `ApiKeyPool`) | ✅ Đã có — KHÔNG dùng `google.generativeai` cũ |
| Config | `python-dotenv` (`.env`) + `tomllib` (`config.toml`) | ✅ Đã có |
| EPUB parsing | `ebooklib` (`src/ingest/epub.py`, `epub_structure.py`) | ✅ Đã có |
| Chapter boundary (TXT) | Regex (`data/txt_cases.json`) + AI verify (`src/ingest/txt.py`) | ✅ Đã có |
| Image fetch | `WebImageFetcher` (`DomainSessionPool`) + `EpubImageExtractor` (zip) | ✅ Đã có |

### FORBIDDEN technologies

- ❌ `requests` / `httpx` / `aiohttp` — đã có `curl_cffi`
- ❌ `selenium` — đã có Playwright
- ❌ `pandas` / `scrapy` / `trafilatura` — không phù hợp scope
- ❌ Database (SQLite, ...) / Web framework — CLI tool dùng JSON atomic write

---

## 5. Architecture Pillars

```
[Input Adapters: Web / EPUB / TXT]
        │  produce RawDocument (ingest/types.py)
        ▼
[Core Pipeline: Filter HTML → Extract → Title → Nav → Validate → Clean → AdsFilter → Image Stage]
        │  produce CleanedChapter DTO
        ▼
[Output Writers: ObsidianWriter / TranslationWriter / RawWriter]
        │
        ▼
Vault/Novels/{story_slug}/
```

### Layering rules — BẤT BIẾN

1. **Input adapter** chỉ produce `RawDocument`. KHÔNG xử lý content.
2. **Pipeline core** chỉ làm việc với `PipelineContext` — không biết source là web/epub/txt.
3. **Pipeline output** là `CleanedChapter` DTO — KHÔNG ghi file trực tiếp.
4. **Output writer** consume `CleanedChapter` → file. Mode-specific logic gói gọn trong writer.
5. **Mode propagation:** `RunConfig` được pass xuống `PipelineContext.run_config`.
6. **Shared logic** trong `src/pipeline/`, `src/core/`, `src/learning/`, `src/utils/`, `src/ai/` — KHÔNG copy logic vào adapter hay writer.
7. **Image fetch strategy pattern:** `WebImageFetcher` và `EpubImageExtractor` implement chung interface `ImageFetchStrategy.fetch(ref) -> bytes | None`.

### Critical invariant

- `src/pipeline/base.py` KHÔNG import `src/pipeline/executor.py` (tránh circular import).
- `StepConfig`/`ChainConfig`/`PipelineConfig` đã xóa ở Batch B — không tái sinh. `PipelineRunner` đọc trực tiếp từ `SiteProfile` flat fields.

---

## 6. READ-FIRST Rules — Đọc Thông Minh

### 6.1 Thứ tự đọc khi nhận task
1. `CLAUDE.md` (file này) — luôn luôn, một lần per session
2. `docs/BLUEPRINT.md` — nếu task >5 dòng hoặc đụng kiến trúc
3. `docs/V1_1_BACKLOG.md` / `docs/ROADMAP.md` — nếu cần biết các vấn đề đang mở và lịch sử giải quyết
4. File ĐÍCH (file user muốn sửa) — đọc phần liên quan hoặc full nếu ngắn
5. File ĐỘ PHỤ THUỘC TRỰC TIẾP — đọc PHẦN LIÊN QUAN bằng `view_range`

### 6.2 Search-first, view-second
- ✅ Dùng `grep` / `glob` TRƯỚC khi đọc full file
- ❌ Đừng đọc cả file chỉ để tìm 1 hàm

### 6.3 View range thay vì full file
- File <200 dòng: đọc full OK
- File >500 dòng: BẮT BUỘC dùng `view_range` với function/class cụ thể

### 6.4 KHÔNG đọc lại
- Trong cùng session, KHÔNG đọc lại file đã đọc trừ khi file vừa bị sửa hoặc user yêu cầu.

### 6.5 Stop reading khi đã đủ
- Sau khi đọc 3-4 file đã rõ task → bắt đầu lập plan / code; nếu chưa rõ → hỏi user.

### 6.6 Khi user paste error/traceback
- Đọc traceback xác định file + line, chỉ view quanh line đó (±20 dòng) trước.

---

## 7. CONTEXT-BUDGET Rules — Tiết Kiệm Token

- **7.1 KHÔNG paste lại nội dung user vừa gửi** (chỉ mô tả ngắn).
- **7.2 KHÔNG đọc lại file vừa tạo/sửa** nếu tool đã báo thành công.
- **7.3 Output ngắn gọn**: trả lời hội thoại <10 dòng; plan trước code 3-7 bullets; sau code 1-3 dòng tóm tắt + việc tay của user.
- **7.4 KHÔNG overwrite cả file lớn khi diff nhỏ** (dùng `edit_file`).
- **7.5 Batch các tool call liên quan** trong cùng lượt.
- **7.6 Khi context gần hết**: chủ động đề xuất commit + tóm tắt để chuyển session.

---

## 8. THINK-FIRST Rules (CRITICAL)

### 8.1 Template Plan-Before-Code (BẮT BUỘC cho task >50 dòng code)

```markdown
**Tôi hiểu task:** [1-2 câu tiếng Việt]
**Tôi sẽ làm:** [3-7 bullets]
**Files động vào:** `path/to/file.py`
**Rủi ro:** [ít nhất 1 thứ có thể vỡ]
**Kết quả dự kiến:** [Z]
```
Chờ user confirm → mới code.

### 8.2 Khi nghi ngờ — LUÔN hỏi, KHÔNG đoán
- *"Một câu hỏi clarify giờ tiết kiệm 30 phút sửa code sau."*

### 8.3 KHÔNG được khi không chắc
- ❌ Đoán selector pattern khi chưa thấy HTML
- ❌ Tự thêm thư viện ngoài tech stack §4
- ❌ Sửa shared logic (`pipeline/base.py`, `pipeline/executor.py`, `core/scraper.py`, `core/formatter.py`) mà không hỏi user

### 8.4 Root cause > Firefighting
- Khi gặp bug: tìm nguyên nhân gốc ở selector / DOM filter / prompt thay vì đắp thêm regex chữa cháy.

### 8.5 Regression-aware refactor
- Trước mọi refactor hành vi lớn (như FlowSpec §1.1, image stage §1.2): chụp baseline bằng `tools/snapshot_baseline.py` và diff kết quả sau khi sửa.

---

## 9. VERIFY Rules

- **9.1 Sau MỌI thay đổi code**: chạy `py_compile`, import check, và smoke test thật; báo cáo kết quả terminal thực tế.
- **9.2 KHÔNG được**: báo "đã fix" khi chưa chạy test, dùng bare `except:` không log, hoặc swallow `asyncio.CancelledError`.

---

## 10. STOP Rules (PHẢI hỏi user trước)

| Action | Lý do |
|---|---|
| Delete file/folder hoặc rename module chính | Mất data / gãy import |
| Sửa shared logic (`pipeline/base.py`, `pipeline/executor.py`, `core/scraper.py`, `core/formatter.py`) | Ảnh hưởng toàn bộ luồng cào |
| Thay đổi `SiteProfile` schema (`utils/types.py`, `data/site_profiles.json`) | Phá các profile đã học |
| Thay đổi return type của hàm nhiều nơi gọi | Gãy caller |
| Refactor >2 module cùng lúc hoặc thêm tính năng ngoài Scope Lock §3 | Scope creep |
| Chỉnh AI prompt > 30% nội dung | Thay đổi hành vi AI |
| `git push --force` / `rm -rf` | Huỷ dữ liệu |

**Format hỏi:** *"Tôi định [X]. Lý do: [Y]. Ảnh hưởng: [Z]. OK không?"*

---

## 11. NEVER Rules & 12. ALWAYS Rules

- **NEVER**: silent failure, bare `except:`, swallow `asyncio.CancelledError`, dùng model flash-lite cho structured output, hardcode API key, commit `.env`/`Vault/Novels/`/`progress/`, dùng `requests`/`httpx`, hoặc mở file thiếu `encoding="utf-8"`.
- **ALWAYS**: commit conventional sau mỗi bước xong, smoke test trước commit, giao tiếp tiếng Việt, có type hints cho hàm mới, ghi file quan trọng bằng atomic write (`.tmp` + `os.replace`), dùng `async/await` cho I/O.

---

## 13. Git Discipline & 14. Definition of Done

- **Conventional commits**: `<type>(<scope>): <subject>` (`feat`, `fix`, `refactor`, `docs`, `chore`).
- **Definition of Done**: Compile/import pass + smoke test pass + edge case checked + type hints đầy đủ + git committed + cập nhật `docs/V1_1_BACKLOG.md` / `CHANGELOG.md` nếu liên quan.

---

## 15. Communication Style & 16. Tech Conventions

- Giao tiếp tiếng Việt ngắn gọn, rõ ràng, đính kèm link file.
- Python 3.11+: `from __future__ import annotations`, `X | None`, `@dataclass` cho DTO, mọi `ScraperBlock` phải `except asyncio.CancelledError: raise` và dùng `self._timed(result, start)`.

---

## 17. Decision Log (Summary — #1 to #58)

Các quyết định kiến trúc đã khóa (rút gọn 1 dòng/mục để tra cứu nhanh):

| # | Quyết định | Lựa chọn & Lý do cốt lõi |
|---|---|---|
| **1–5** | Scope & Stack nền tảng | 3 inputs (`web`/`epub`/`txt`) × 3 outputs (`obsidian`/`translate`/`raw`); `asyncio` + `curl_cffi` + `Playwright` + `google-genai`; không dùng Trafilatura. |
| **6–12** | Lưu trữ & Làm sạch | Profile lưu ở `data/site_profiles.json`, tiến độ ở `progress/*.json`; Learning 8 AI calls + Naming riêng; đọc thẳng flat fields từ `SiteProfile`; Title first-wins; Cleaner 5-pass (cap 60%) + `AdsFilter` 2 tầng. |
| **13–17** | Output & Deferrals | Image policy theo mode (`obsidian` tải ảnh, `translate` chèn `[IMAGE: alt]`, `raw` xoá); `CleanedChapter` DTO làm hợp đồng; defer case-based web learning & TypedDict refactor sang v1.1+. |
| **18–25** | Thứ tự Phase & Chuẩn v1.0 | Làm Output Abstraction (Phase 1) trước Image Support (Phase 2); dùng Strategy pattern cho `WebImageFetcher` / `EpubImageExtractor`; TXT v1.0 hỗ trợ VN+EN; UTF-8 explicit; EPUB ưu tiên Dublin Core metadata; có `--bulk-relearn`. |
| **26–27** | Phase 0 Batch A & B | Xoá `learning/optimizer.py` (~450 LOC) và `StepConfig/ChainConfig/PipelineConfig` + `learning/migrator.py` (~330 LOC); `--fast-learning` chuyển thành bỏ qua `ProseRichness`. |
| **28–32** | Phase 1 Output Writers | Đổi tên package `output/` thành `writers/`; tạo 1 writer instance mỗi task; `build_cleaned_chapter` đặt độc lập; ghi file bằng `_atomic_write_text` có dọn `.tmp` khi cancel. |
| **33–37** | Phase 2 Image Pipeline | Thêm `DomainSessionPool.fetch_bytes`; sửa check `formatting_rules is not None`; đặt `_apply_image_stage` tại `core/scraper.py`; tách riêng call `ai_image_policy`; giữ link ảnh gốc nếu tải lỗi. |
| **38–44** | Phase 3 EPUB Adapter | `core/orchestrator.py` điều phối hàm; EPUB dùng `MarkdownFormatter` trực tiếp trên `<body>`; `AdsFilter` dùng namespace `epub:{slug}` (chỉ chạy nhánh auto `threshold >= 10`). |
| **45–49** | Phase 4 Translate & Raw | `TranslationWriter` mặc định tắt chunking (`CHUNK_THRESHOLD = 0`), giữ tiêu đề ở dòng 1, chuyển ảnh thành `[IMAGE: alt]`; điều phối qua `writers/factory.py::build_writer()`. |
| **50–54** | Phase 5 TXT Adapter | Kèm sẵn `data/txt_cases.json` (6 mẫu VN+EN); ưu tiên regex (`score >= 1`), nếu miss mới gọi AI và kiểm chứng trên 3 đoạn 80 dòng giữa file; dùng namespace `txt:{slug}`. |
| **55–56** | Phase 6 Batch C Cleanup | Xoá unused imports, bỏ f-prefix thừa, chuyển `RawDocument` sang `ingest/types.py`, inline `_title_from_url` và xoá `core/extractor.py` & `ingest/web.py`; hoãn FlowSpec/image-stage extract chờ baseline. |
| **57** | Per-host Concurrency Cap | `DomainSessionPool` giới hạn `PER_HOST_MAX_CONCURRENCY = 3` bằng `asyncio.Semaphore` per-domain để chống bị ban IP (v1.2.0). |
| **58** | Scrape Loop & Nav Guards | Khôi phục `MAX_EMPTY_STREAK` (5 chương rỗng liên tiếp thì dừng); chặn `slug_increment` khi URL có dạng `/chapter/<id>/<slug>` (RoyalRoad); check `title:url_slug` trong `ctx.block_results` và log `ctx.nav_method` thực tế (v1.2.1, 2026-11-09). |

---

## 18. Anti-patterns (TRÁNH)

1. **Biện pháp chống cháy (firefighting)** — thêm regex strip vào cleaner thay vì sửa selector / DOM filter.
2. **Silent failure** — `except: pass` không log.
3. **Serialization roundtrip** — tái sinh `StepConfig`.
4. **Mutating shared state** — sửa `ctx.profile` bên trong block.
5. **AI prompt thiếu ràng buộc định dạng** — mọi prompt phải giới hạn output rõ ràng ("PLAIN TEXT ONLY" hoặc JSON schema).
6. **Báo "đã fix" mà chưa chạy test thực tế**.
7. **Swallow `CancelledError`** — làm Ctrl+C bị treo.
8. **Over-engineering / Premature optimization** — không code tính năng dự phòng khi chưa có số đo hoặc nhu cầu thực tế.
9. **Mở file thiếu `encoding="utf-8"`** trên Windows.

---

## 19. Reference Documents

- `CLAUDE.md` — Quy tắc vận hành & Decision Log (file này)
- `README.md` — Hướng dẫn sử dụng nhanh cho người dùng
- `docs/BLUEPRINT.md` — Kiến trúc hệ thống chi tiết
- `docs/ROADMAP.md` — Tóm tắt các Phase 0–6 và các bản phát hành đã hoàn thành
- `docs/V1_1_BACKLOG.md` — Danh sách lỗi thực tế đang chờ xử lý (§7.3, §7.4, §7.5, ...) và các tính năng deferred
- `docs/CHANGELOG.md` — Lịch sử thay đổi theo phiên bản
- `docs/TROUBLESHOOTING.md` — Cẩm nang xử lý lỗi thường gặp
- `docs/MIGRATION_NOTES.md` — Ghi chú nâng cấp từ v0.x lên v1.x

---

**END CLAUDE.md v1.2.1**
