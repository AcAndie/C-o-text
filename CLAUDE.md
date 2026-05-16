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
2. Đọc tiếp `BLUEPRINT.md` (vision + architecture chi tiết) nếu task >5 dòng code hoặc đụng kiến trúc
3. Đọc `ROADMAP.md` nếu task liên quan thứ tự execution (phase nào, step nào)
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
| **Stage** | **v0.x consolidation** — ~7,240 dòng, kiến trúc ổn, đang ở giai đoạn reduction (Batch A/B/C) trước khi mở rộng |
| **Owner** | Solo dev — vibe coder, không rành code chi tiết, dùng Claude Code, giao tiếp tiếng Việt |
| **Inspiration** | FanFicFare (scope rộng + maintenance lâu năm), gallery-dl (extractor plugin pattern), Trafilatura (extraction heuristics), QuickTranslator (consistency through dictionary layer) |
| **Platform** | Windows desktop (`C:\Users\FPT MONG CAI\Desktop\Small Project\Cào text`) |
| **Runtime** | Python 3.11+ async (`asyncio`) |

---

## 2. Vision (1 dòng)

**"Ném input nào vào (URL truyện đa site đa ngôn ngữ / EPUB / TXT) cũng ra được một bộ chapter sạch, không noise, đọc được trên Obsidian hoặc đem đi dịch — site mới chỉ cần học 1 lần, lần sau xài lại."**

Chi tiết vision + architecture: xem `BLUEPRINT.md`.

---

## 3. Scope Lock v1.0 (NGHIÊM NGẶT)

> **Quan trọng:** Cào Text hiện đã có ~70% logic apply được cho vision rộng. v1.0 = (1) cleanup di sản từ scope cũ, (2) thêm input adapter + output mode, (3) image support cho web, (4) i18n baseline. KHÔNG mở rộng thêm.

### ✅ MUST HAVE v1.0 — ĐÃ CÓ trong codebase, cần GIỮ + cleanup:

1. **Pipeline architecture** (5 chain: Fetch/Extract/Title/Nav/Validate) — `pipeline/`
2. **Learning phase** (8 AI calls + naming phase) — `learning/`
3. **HybridFetchBlock** (curl_cffi + Playwright fallback) — `pipeline/fetcher.py`
4. **Content cleaning 5-pass** — `utils/content_cleaner.py`
5. **AdsFilter** (auto-add + AI verify, cross-chapter frequency) — `utils/ads_filter.py`
6. **ProfileManager** + SiteProfile schema — `learning/profile_manager.py`
7. **Naming Phase** (story name + chapter pattern detection) — `learning/naming.py`
8. **Chapter writer** (filename normalization, garbage subtitle guard) — `core/chapter_writer.py`
9. **MarkdownFormatter** (đang text-only, sẽ extend cho image) — `core/formatter.py`
10. **AI client** với token-bucket rate limiting — `ai/client.py`
11. **IssueReporter** + session header — `utils/issue_reporter.py`

### ✅ MUST HAVE v1.0 — NEW, cần BUILD (theo thứ tự ROADMAP):

12. **Batch A/B reduction** — xóa ~780 dòng (optimizer + StepConfig serialization)
13. **Baseline snapshot protocol** — `tools/snapshot_baseline.py` + `data/baselines/` cho regression diff trước MỌI refactor lớn
14. **Output Mode Abstraction** — `RunConfig` + `CleanedChapter` DTO + `ChapterWriter` interface với 3 implementations:
    - `ObsidianWriter` (Markdown + image embed) — port từ `chapter_writer.py`
    - `TranslationWriter` (plain text, paragraph-per-line, no image)
    - `RawWriter` (text only, không format)
15. **Image support cho web novel** — `MarkdownFormatter` xử lý `<img>`, `WebImageFetcher`, output `images/` folder. **Phụ thuộc:** RunConfig phải có TRƯỚC (item 14).
16. **EPUB input adapter** — `ingest/epub.py` (ebooklib parse spine) + `EpubImageExtractor` (extract embedded image từ zip, riêng biệt với `WebImageFetcher`)
17. **TXT input adapter** — `ingest/txt.py` — AI-assisted chapter boundary detection. **Scope v1.0:** Vietnamese + English only. CJK chapter pattern (Trung "第N章", Nhật "第N話") defer v1.1.
18. **i18n baseline** — UTF-8 read/write đúng cho mọi adapter, không có encoding assumption. Site đa ngôn ngữ (EN, VN, EN-translated CN/KR) work qua existing pipeline.
19. **Mode-aware pipeline** — skip image download cho translate/raw mode, skip metadata fetch cho raw mode
20. **Bulk relearn script** — `main.py --bulk-relearn` để re-learn tất cả profile cũ sau breaking schema change
21. **README + Quick Start** — viết từ Phase 0, không defer cuối

### 🚫 DEFERRED (v1.1+, KHÔNG ĐỘNG TỚI trong v1.0):

- ❌ **Case-based learning** — chỉ làm sau khi có 10+ domain profile để thấy pattern thật. Premature design = over-engineering tinh vi.
- ❌ **Truyện tranh thuần (manhua/manga)** — đó là image-primary pipeline, project khác. Gallery-dl đã giải tốt, fork repo riêng nếu cần.
- ❌ **Site Trung/Nhật CJK hardening** — i18n hardening nâng cao (encoding heuristic, font deobfuscation, slugify pinyin, chapter pattern "第N章"/"第N話") defer v1.1. **v1.0 chỉ cần UTF-8 baseline work — đọc/ghi UTF-8 đúng, content có CJK characters không crash.**
- ❌ **Calibration phase** (re-probe 10 chapter để verify profile) — plan có rồi nhưng defer cho v1.1.
- ❌ **Arc memory / Bible / Scout** — đây là feature của translation tool, không phải scraper.
- ❌ **Web UI / Streamlit / FastAPI** — CLI là đủ cho v1.0.
- ❌ **TypedDict refactor `utils/types.py` (P3-D)** — high-risk, defer.
- ❌ **Frontmatter YAML tag generation từ category metadata** — Obsidian-specific over-engineering cho novel use case.
- ❌ **Wikilink generation, attachments folder convention nâng cao** — basic embed đủ cho v1.0.
- ❌ **Inline link preservation** — novel chapter hiếm khi có meaningful link.
- ❌ **Generic article scraper / blog scraper** — Trafilatura làm tốt hơn, không reinvent.

### HARD RULE về scope

**Khi user request tính năng trong DEFERRED list:**

1. STOP — không code
2. Trả lời:
   > *"Tính năng [X] trong DEFERRED list của Scope Lock v1.0 (CLAUDE.md §3). Lý do defer: [trích lý do từ list]. Anh muốn:*
   > - *(a) Vẫn add vào v1.0, hiểu MVP sẽ chậm thêm?*
   > - *(b) Ghi vào `docs/V1_1_BACKLOG.md` để làm sau?*
   > - *(c) Bỏ qua?"*
3. Chờ user quyết.

**Request KHÔNG có trong cả 2 list:** hỏi rõ — có thể feature mới chưa bàn.

---

## 4. Tech Stack (LOCKED)

| Layer | Tech | Trạng thái |
|---|---|---|
| Language | Python 3.11+ | ✅ đã có |
| Async runtime | `asyncio` | ✅ đã có |
| HTTP fetch (default) | `curl_cffi` (Chrome TLS fingerprint) | ✅ đã có |
| HTTP fetch (JS sites) | `playwright` (Chromium) | ✅ đã có |
| HTML parsing | `beautifulsoup4` + `lxml` parser | ✅ đã có |
| AI SDK | `google-genai` (Gemini API) | ✅ đã có — KHÔNG dùng deprecated `google.generativeai` |
| Config | `python-dotenv` | ✅ đã có |
| EPUB parsing | `ebooklib` | 🆕 ADD trong v1.0 (Phase 3) |
| Chapter boundary (TXT) | regex + AI verify | 🆕 ADD trong v1.0 (Phase 5) |
| Image fetch (web) | reuse `curl_cffi` qua `DomainSessionPool` | 🆕 ADD trong v1.0 (Phase 2) |
| Image extract (EPUB) | `ebooklib` get_content() từ zip | 🆕 ADD trong v1.0 (Phase 3) |
| Encoding detect (defer) | `charset-normalizer` | ⚠️ chỉ add nếu user gặp non-UTF-8 file thật |
| Testing (tương lai) | `pytest` + `pytest-asyncio` | ⚠️ chưa có, defer |
| Lint/format | None hiện tại | ⚠️ chưa có, defer |

### FORBIDDEN technologies

- ❌ `requests` / `httpx` — đã có `curl_cffi`, không add HTTP library thứ 3
- ❌ `selenium` — đã có Playwright
- ❌ `aiohttp` — `curl_cffi` đã async
- ❌ `pandas` — overkill cho text processing
- ❌ `scrapy` — kiến trúc khác, không integrate được
- ❌ `trafilatura` — đã quyết định không dùng (xem Decision Log #5)
- ❌ Database (SQLite, ...) — JSON file đủ, không cần
- ❌ Web framework — CLI tool, không cần API

---

## 5. Architecture Pillars

```
┌──────────────────────────────────────────────────────────────────┐
│  INPUT ADAPTERS (chọn 1 per run)                                  │
│  ┌──────────────┐  ┌────────────┐  ┌────────────┐                │
│  │ Web scraper  │  │ EPUB ingest│  │ TXT ingest │                │
│  │ (URL list)   │  │ (file)     │  │ (file)     │                │
│  └──────┬───────┘  └─────┬──────┘  └──────┬─────┘                │
│         └────────────────┼────────────────┘                       │
│                          ▼                                        │
│                    ┌──────────────┐                               │
│                    │  RawDocument │  (HTML chunk hoặc text-as-    │
│                    │              │   HTML — pipeline không biết  │
│                    │              │   source là gì)               │
│                    └──────┬───────┘                               │
└─────────────────────────  │  ────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│  CORE PIPELINE (per chapter — reuse cho mọi adapter)             │
│                                                                  │
│  Filter HTML → Extract content → Title → Navigate → Validate    │
│  → Post-clean → AdsFilter → Image download (mode-aware)         │
│                                                                  │
│  Output: CleanedChapter DTO                                      │
└────────────────────────────┬─────────────────────────────────────┘
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│  OUTPUT WRITERS (chọn 1 per run, theo RunConfig)                 │
│  ┌──────────────┐  ┌────────────────┐  ┌──────────────┐         │
│  │ObsidianWriter│  │TranslationWriter│  │ RawWriter    │         │
│  └──────────────┘  └────────────────┘  └──────────────┘         │
└─────────────────────────────────────────────────────────────────┘
                            │
                            ▼
                  output/{story_slug}/
```

### Layering rules — BẤT BIẾN

1. **Input adapter** chỉ produce `RawDocument` (URL + HTML, hoặc EPUB chapter HTML, hoặc TXT chunk text-as-html). KHÔNG xử lý content.
2. **Pipeline core** chỉ làm việc với `PipelineContext` — không biết source là web/epub/txt.
3. **Pipeline output** là `CleanedChapter` DTO — KHÔNG ghi file trực tiếp.
4. **Output writer** consume `CleanedChapter` → file. Mode-specific logic gói gọn trong writer.
5. **Mode propagation:** `RunConfig` được pass xuống `PipelineContext.run_config` → block đọc để skip image download, fetch metadata, v.v.
6. **Shared logic** trong `pipeline/`, `core/`, `learning/`, `utils/`, `ai/` — KHÔNG copy logic vào adapter hay writer.
7. **Image fetch strategy pattern:** `WebImageFetcher` (HTTP qua curl_cffi) ≠ `EpubImageExtractor` (binary từ zip). Cả hai implement chung interface `ImageFetchStrategy.fetch(ref) -> bytes | None`.

### Phase ordering rationale (BẮT BUỘC tôn trọng)

**Image support phụ thuộc RunConfig — KHÔNG đảo thứ tự.**

Lý do: Image policy là per-mode (Obsidian: download, Translate/Raw: skip — Decision #13). Image logic phải đọc được `ctx.run_config.download_images`. Vậy `RunConfig` + `CleanedChapter` phải có TRƯỚC khi code image stage. Đây là lý do Phase 1 = Output Abstraction, Phase 2 = Image Support (KHÔNG phải ngược lại).

### Critical invariant

`pipeline/base.py` KHÔNG import `pipeline/executor.py` (circular import prevention).

`StepConfig`/`ChainConfig`/`PipelineConfig` đã xóa ở Batch B — đừng tái sinh chúng. `PipelineRunner` đọc trực tiếp từ `SiteProfile` flat fields.

---

## 6. READ-FIRST Rules — Đọc Thông Minh

> **Vấn đề thực tế:** Context window có hạn, đọc 5 file 1000-dòng-mỗi-cái = hết quota suy nghĩ. Đọc đúng chỗ > đọc nhiều chỗ.

### 6.1 Thứ tự đọc khi nhận task

```
1. CLAUDE.md (file này) — luôn luôn, một lần per session
2. BLUEPRINT.md — nếu task >5 dòng hoặc đụng kiến trúc
3. ROADMAP.md — nếu cần biết phase/step hiện tại
4. File ĐÍCH (file user muốn sửa) — luôn đọc full
5. File ĐỘ PHỤ THUỘC TRỰC TIẾP (import từ/đến file đích) — đọc PHẦN LIÊN QUAN bằng view_range
6. File có thể bị ảnh hưởng — chỉ đọc nếu plan ảnh hưởng đến nó
```

KHÔNG đọc theo thứ tự alphabet folder. KHÔNG đọc "tham khảo cho biết".

### 6.2 Search-first, view-second

Khi cần tìm cái gì:
- ✅ **Dùng `grep` / `glob` TRƯỚC** khi đọc full file
- ✅ Tìm function definition: `grep -rn "def function_name" src/`
- ✅ Tìm usage: `grep -rn "function_name(" src/`
- ✅ Tìm class: `grep -rn "class ClassName" src/`
- ❌ Đừng `cat` cả file để tìm 1 function
- ❌ Đừng đọc folder structure mỗi turn — tự cache vào memory session

### 6.3 View range thay vì full file

- File <200 dòng: đọc full OK
- File 200-500 dòng: đọc full nếu cần hiểu cấu trúc, view_range nếu chỉ cần 1 function
- File >500 dòng: **BẮT BUỘC** dùng view_range với function/class cụ thể
- File >1000 dòng (như `phase_ai.py`): đọc full chỉ khi task chạm vào toàn bộ flow

### 6.4 KHÔNG đọc lại

Trong cùng session, KHÔNG `view` lại file đã đọc trừ khi:
- File đã bị sửa (bởi Claude hoặc user)
- User explicit yêu cầu re-read
- Hơn 20 turn đã trôi qua và content cần verify lại

Reference: nói "ở `pipeline/base.py` line 45-60" thay vì view lại.

### 6.5 Stop reading khi đã đủ

Sau khi đọc 3-4 file mà:
- Vẫn chưa rõ task → STOP, hỏi user thêm context
- Đã rõ task → STOP, bắt đầu code

KHÔNG "đọc cho chắc" thêm file thứ 5, 6, 7. Đó là procrastination dạng đọc-thay-vì-làm.

### 6.6 Khi user paste error/traceback

- Đọc TRACEBACK trước (xác định file + line từ stack)
- View ĐÚNG line range đó (±20 dòng)
- KHÔNG view full file ngay
- Chỉ view rộng hơn khi root cause không ở đó

---

## 7. CONTEXT-BUDGET Rules — Tiết Kiệm Token

### 7.1 KHÔNG paste lại nội dung user vừa gửi

- User paste 100 dòng code → KHÔNG quote lại 100 dòng đó để "xác nhận đã hiểu"
- User paste traceback → KHÔNG quote lại traceback
- Reference bằng *mô tả ngắn*: "Lỗi `KeyError` ở `phase_ai.py:142` mà anh paste"

### 7.2 KHÔNG đọc file vừa tạo ra

- Sau `create_file` hoặc `str_replace`, KHÔNG `view` lại để "verify"
- Tool đã return success = file đã viết đúng nội dung anh gửi
- Chỉ view lại khi: bị error message lúc edit, hoặc bash test fail

### 7.3 Output ngắn gọn

- Trả lời conversational: **<10 dòng**
- Plan trước code: **3-7 bullets** (không hơn)
- Sau code: **1-3 dòng tóm tắt** + danh sách việc user cần làm tay
- KHÔNG paraphrase lại code vừa viết — file đã tự nói

### 7.4 KHÔNG full file replacement khi diff nhỏ

- Sửa 5 dòng trong file 500 dòng → `str_replace`, KHÔNG `create_file` (overwrite)
- Sửa >30% file → `create_file` OK
- Sửa toàn bộ structure → `create_file` OK

### 7.5 Batch các tool call liên quan

- View 3 file trong cùng task → gọi 3 `view` tool back-to-back, không xen kẽ text
- Edit 5 chỗ trong 1 file → 5 `str_replace` liên tiếp, không break flow

### 7.6 Khi context gần hết

Nếu thấy session đang dài (>50 turns hoặc nhiều file lớn đã đọc):
- Báo user: "Context đang nặng, anh muốn em commit + tóm tắt rồi chuyển session mới không?"
- Tóm tắt: file đã sửa, decision đã chốt, todo còn lại
- User confirm → commit + present summary file

---

## 8. THINK-FIRST Rules (CRITICAL)

### 8.1 Template Plan-Before-Code (BẮT BUỘC cho task >50 dòng code)

```markdown
**Tôi hiểu task:** [1-2 câu tiếng Việt]

**Tôi sẽ làm:**
- [bullet 1]
- [bullet 2]

**Files động vào:**
- `path/to/file.py` (edit, ~X dòng)
- `path/to/new.py` (create, ~Y dòng)

**Phụ thuộc phase nào:** [vd: cần RunConfig từ Phase 1 — đã có?]

**Rủi ro:**
- [ít nhất 1 thứ có thể vỡ]

**Kết quả dự kiến:** [Z]
```

User reply OK / confirm → mới code.

### 8.2 Khi nghi ngờ — LUÔN hỏi, KHÔNG đoán

- "Field này nullable hay required?"
- "Logic này khác chỗ kia một chút, có cần đồng bộ không?"
- "Anh muốn fail-loud (raise) hay fail-silent (log + skip)?"
- "AI prompt này có cần thêm output format constraint không?"
- "Block này thuộc Extract chain hay Validate chain?"
- "Step này phụ thuộc phase nào — đã done chưa?"

**Quy tắc:** *"Một câu hỏi clarify giờ tiết kiệm 30 phút sửa code sau."*

### 8.3 KHÔNG được khi không chắc

- ❌ Đoán selector pattern cho site mới chưa thấy HTML
- ❌ Đoán AI prompt format khi không biết AI response shape
- ❌ Tự chọn library mới chưa trong tech stack §4
- ❌ Tạo file/folder không thuộc layering §5
- ❌ Refactor code đang work để "đẹp hơn"
- ❌ Thay đổi `SiteProfile` schema mà không hỏi
- ❌ **Sửa shared logic (`pipeline/base.py`, `pipeline/executor.py`, `core/scraper.py`, `core/formatter.py`) không hỏi user** — đụng = phá toàn bộ scraper
- ❌ **Skip step trong ROADMAP** vì "thấy không cần" — phase có thứ tự vì lý do

### 8.4 Root cause > Firefighting

Đây là PRINCIPLE QUAN TRỌNG NHẤT của project này.

Khi gặp bug:
- ❌ KHÔNG thêm regex strip pass thứ 6 vào `content_cleaner.py` để "xử nốt" rác
- ✅ Tìm xem rác đến từ đâu — selector học sai? Remove_selectors miss? AI prompt không cấm format đó?

Khi gặp hallucination:
- ❌ KHÔNG validate harder ở consumer side
- ✅ Tìm xem prompt thiếu constraint gì → fix prompt + validate là defense layer 2

User dùng từ "biện pháp chống cháy" để gọi anti-pattern này. Tránh nó như tránh lửa.

### 8.5 Regression-aware refactor

**Trước MỌI refactor lớn (xóa file, sửa shared logic, đổi DTO):**
1. Snapshot baseline output từ `data/baselines/` — đã có chưa? Nếu chưa, **STOP, chạy `python tools/snapshot_baseline.py` trước**
2. Refactor
3. Re-run với same input, diff với baseline
4. Diff khác → identify cause TRƯỚC khi commit

Tránh ship "smoke test pass nhưng vault Obsidian của user mismatch".

---

## 9. VERIFY Rules

> Bài học từ M4 serialization bug, ADS keyword corruption: AI báo cáo sai. KHÔNG tin nửa lời, verify everything.

### 9.1 Sau MỌI thay đổi code

1. Chạy lệnh thật:
   - Smoke test: `python main.py links.txt` với 1 URL test
   - Import check: `python -c "from <module> import <thing>"`
   - Syntax check: `python -m py_compile <file>`
   - **Regression diff** (refactor lớn): `diff -r output/ data/baselines/<reference>/`
2. Báo cáo output **THẬT** — copy terminal, KHÔNG paraphrase
3. Nếu fail → quote exact error, KHÔNG đoán cause

### 9.2 Smoke test cho từng phase

- **Phase 0 (cleanup):** 2 site đã learn + 10 chapter mỗi cái, diff với baseline
- **Phase 1 (output abstraction):** 1 URL × 3 mode (obsidian/translate/raw)
- **Phase 2 (image):** 1 Royal Road novel có illustration
- **Phase 3 (EPUB):** 1 EPUB pirate có watermark + 1 EPUB clean
- **Phase 4 (writers):** cùng 1 nguồn × 3 mode
- **Phase 5 (TXT):** 1 VN file + 1 EN file. **Nếu 1 trong 2 fail → STOP phase 5, defer v1.1.**

### 9.3 KHÔNG được

- ❌ Báo "đã fix" nếu chưa chạy script test
- ❌ Comment out code thay vì fix
- ❌ Try/except bao quanh để "khỏi crash" mà không log
- ❌ Hardcode value để smoke test pass
- ❌ "Sửa cho có" mà không hiểu root cause
- ❌ Skip baseline diff cho refactor lớn

### 9.4 Khi user paste error

```markdown
**Vấn đề:** [1 dòng plain Vietnamese]
**Tại sao xảy ra:** [1-2 dòng root cause, KHÔNG đoán]
**Fix:**
1. [step 1]
2. [step 2]
**Verify:** [cách check fix work bằng smoke test]
```

---

## 10. STOP Rules (PHẢI hỏi user trước)

| Action | Lý do |
|---|---|
| Delete file/folder | Mất data |
| Xóa hoặc rename module trong `pipeline/`, `learning/`, `core/`, `ai/` | Break import chain |
| **Sửa shared logic** (`pipeline/base.py`, `pipeline/executor.py`, `core/scraper.py`, `core/formatter.py`) | Phá toàn bộ flow |
| Thay đổi `SiteProfile` schema (`utils/types.py`) | Phá tất cả profile đã learn |
| Thay đổi `data/site_profiles.json` schema | Mất profile đã có |
| Thay đổi return type của function được nhiều caller dùng (vd `_format_element` từ `str` → `tuple[str, list]`) | Break mọi caller |
| Refactor >2 module trong 1 lần | Scope creep |
| Add feature không trong Scope Lock §3 | Scope creep |
| Install package mới chưa trong tech stack §4 | Lock dependency |
| Modify CLAUDE.md / BLUEPRINT.md / ROADMAP.md | Governance change |
| Sửa file ngoài project folder | Out of scope |
| Tăng `MAX_CHAPTERS`, `LEARNING_CHAPTERS`, hằng số quan trọng | Có thể vỡ assumption |
| Chỉnh AI prompt > 30% nội dung | AI behavior thay đổi không lường được |
| **Skip baseline snapshot trước refactor lớn** | Mất khả năng phát hiện regression |
| `git push --force` | Destructive |
| `rm -rf` | Catastrophic |
| Requirement không rõ | Tránh code sai |

**Format hỏi:** *"Tôi định [X]. Lý do: [Y]. Ảnh hưởng: [Z]. OK không?"*

Chờ `yes` / `ok` / `confirmed` rõ ràng. Im lặng ≠ đồng ý.

---

## 11. NEVER Rules

- ❌ **Never** silent failure — mọi error/warning PHẢI `print` hoặc `logger.warning`
- ❌ **Never** bare `except:` không log — luôn `except Exception as e: logger.warning(...)`
- ❌ **Never** swallow `asyncio.CancelledError` — re-raise sau cleanup
- ❌ **Never** preview/flash-lite model cho structured output — chỉ full models (xem `GEMINI_MODEL`)
- ❌ **Never** hardcode API key — luôn qua `.env`
- ❌ **Never** commit `.env`, `data/*.json` (trừ `data/baselines/` placeholder), `output/`, `progress/`, `__pycache__/`, `.venv/`
- ❌ **Never** dùng `google.generativeai` (deprecated) — chỉ `google.genai`
- ❌ **Never** dùng `requests` / `httpx` — đã có `curl_cffi`
- ❌ **Never** thêm regex strip pass mới vào `content_cleaner.py` mà không tìm root cause selector
- ❌ **Never** modify file ngoài project folder
- ❌ **Never** `sudo` / admin commands
- ❌ **Never** disable validation guard ở `ai/agents.py` để "qua được" — fix prompt thay vào
- ❌ **Never** override rule chỉ vì user nói "không sao đâu" — hỏi user có muốn UPDATE CLAUDE.md không
- ❌ **Never** tái sinh `StepConfig` / `ChainConfig` / `PipelineConfig` — đã chốt xóa ở Batch B
- ❌ **Never** thêm flat-format SiteProfile field nếu nested format đang work
- ❌ **Never** mutate `ctx.profile` trong pipeline block — chỉ `PipelineRunner` được phép
- ❌ **Never** assume encoding ngoài UTF-8 — mọi `open()` phải `encoding="utf-8"` explicit
- ❌ **Never** đảo thứ tự phase trong ROADMAP để "tiện" — phase có dependency

---

## 12. ALWAYS Rules

- ✅ **Always** commit sau mỗi step thành công, conventional message
- ✅ **Always** run smoke test TRƯỚC commit (chạy với 1 URL/file thật)
- ✅ **Always** baseline diff sau refactor lớn (Phase 0 Batch A/B, Phase 1 output abstraction)
- ✅ **Always** tiếng Việt với user (mix English tech terms OK)
- ✅ **Always** type hints cho function mới (mọi `def` có param + return type)
- ✅ **Always** show output thật sau task
- ✅ **Always** liệt kê "Việc tay của user"
- ✅ **Always** atomic write cho file operation (write to `.tmp`, then rename)
- ✅ **Always** async/await cho I/O — không `time.sleep`, không sync HTTP
- ✅ **Always** test edge case: empty html, junk page, status 429, status 503, file rỗng, file binary nhầm extension
- ✅ **Always** log via `logger` (module-level), không `print` trong library code (chỉ ở `main.py`, `phase.py` user-facing output)
- ✅ **Always** `encoding="utf-8"` explicit cho mọi `open()`
- ✅ **Always** update `CLAUDE.md` Decision Log §17 khi chốt quyết định mới
- ✅ **Always** check `BLUEPRINT.md` khi task chạm vision/architecture
- ✅ **Always** check phase dependency trước khi code (vd: image cần RunConfig)

---

## 13. Git Discipline

### Conventional commits

```
<type>(<scope>): <subject>
```

**Types:** `feat` / `fix` / `refactor` / `docs` / `test` / `chore` / `style` / `perf`

**Scope ví dụ:**
- `refactor(learning): xóa optimizer.py (Batch A)`
- `refactor(pipeline): xóa StepConfig serialization (Batch B)`
- `chore(tools): add baseline snapshot script`
- `feat(output): introduce RunConfig + CleanedChapter DTO`
- `feat(output): add ObsidianWriter (port from chapter_writer)`
- `feat(formatter): handle inline img tag with mode-aware download`
- `feat(ingest): add EPUB adapter`
- `feat(ingest): add EpubImageExtractor`
- `feat(ingest): add TXT adapter (VN + EN cases)`
- `fix(ads): validation guard reject HTML keyword`
- `docs(claude): update scope lock v1.0`
- `chore(deps): add ebooklib`

### When to commit

**Sau MỖI step xong + smoke test pass.** Mỗi commit ≤ 200 lines diff lý tưởng.

Batch lớn (Batch A xóa 450 dòng) có thể >200 dòng — OK, nhưng phải là pure deletion, có message rõ lý do.

### When to revert

```bash
git log --oneline
git revert HEAD          # an toàn
git reset --hard HEAD~1  # nguy hiểm, confirm user
```

### NEVER

- ❌ `git push --force` không hỏi user
- ❌ Commit secrets (`.env`, API key trong code)
- ❌ Commit broken code (smoke test fail)
- ❌ Commit refactor lớn không kèm baseline diff result

---

## 14. Definition of Done (per step)

Step "done" khi TẤT CẢ true:

- [ ] Code chạy không crash happy path (smoke test với 1 URL/file)
- [ ] Edge case quan trọng đã test: empty html, status 429, junk page, file không tồn tại, file rỗng
- [ ] **Sửa shared logic**: test với 2+ site/file khác nhau + baseline diff
- [ ] **Refactor lớn** (Phase 0, Phase 1.5): baseline diff result attached
- [ ] Type hints đủ cho function mới
- [ ] Không có `print()` rác trong library code
- [ ] User verified bằng demo thật
- [ ] Git committed conventional format
- [ ] `BLUEPRINT.md` / `ROADMAP.md` updated nếu vision/scope đổi
- [ ] CLAUDE.md Decision Log §17 updated nếu chốt decision mới
- [ ] README.md updated nếu CLI flag thay đổi hoặc workflow thay đổi

**Fail item nào → CHƯA done. KHÔNG skip step kế.**

---

## 15. Communication Style với Vibe Coder

### DO

- ✅ Giải thích tiếng Việt
- ✅ Show output thật sau task
- ✅ Hỏi confirm trước action lớn
- ✅ Đề xuất commit message rõ
- ✅ Demo bằng real example từ codebase (path/line)
- ✅ Liệt kê "Bạn cần làm gì tay"
- ✅ Hỏi rõ context khi không hiểu code user paste

### DON'T

- ❌ Bắt user hiểu code chi tiết
- ❌ Refactor toàn bộ module không hỏi
- ❌ Cài package không giải thích
- ❌ Tạo file ngoài project
- ❌ Assume user biết debug
- ❌ Skip confirm cho destructive
- ❌ Jargon không cần thiết (đừng nói "monadic" khi nói "wrapper" đủ)

---

## 16. Tech-specific Conventions

### Python

```python
# Imports: stdlib → 3rd party → local, mỗi nhóm cách 1 dòng
from __future__ import annotations  # luôn ở đầu

import asyncio
import logging
from dataclasses import dataclass

from bs4 import BeautifulSoup
from curl_cffi import requests as curl_requests

from pipeline.base import BlockResult, PipelineContext
from utils.string_helpers import normalize_title


logger = logging.getLogger(__name__)


# Dataclass cho DTO, KHÔNG dùng dict raw
@dataclass
class CleanedChapter:
    index: int
    title: str
    body_markdown: str
    images: list[ImageRef]
    source_url: str | None
    source_path: str | None
    metadata: dict


# Type hints BẮT BUỘC, dùng X | None
async def extract(ctx: PipelineContext) -> BlockResult: ...
```

**Rules:**
- Python 3.11+ syntax (`X | None`, không `Optional[X]`)
- `from __future__ import annotations` ở đầu mọi file
- Logger module-level, không `print` trong library code
- Type hints CHO MỌI param + return
- Docstring 1-2 dòng cho public function, không cần cho private `_helper`
- `async def` cho mọi I/O (HTTP, file, sleep)
- KHÔNG `time.sleep` — dùng `asyncio.sleep`
- KHÔNG `requests.get` — dùng `pool.fetch` hoặc Playwright

### Cấu trúc block

```python
class MyBlock(ScraperBlock):
    block_type = BlockType.EXTRACT
    name       = "my_block"

    def __init__(self, ...) -> None:
        ...

    async def execute(self, ctx: PipelineContext) -> BlockResult:
        start = time.monotonic()
        try:
            # ... logic ...
            return self._timed(
                BlockResult.success(data=..., method_used=..., confidence=...),
                start,
            )
        except asyncio.CancelledError:
            raise  # LUÔN re-raise
        except Exception as e:
            return self._timed(BlockResult.failed(str(e) or repr(e)), start)
```

**Rules:**
- Mọi block extend `ScraperBlock`
- `block_type` + `name` là class attribute
- `execute` luôn `async`
- `start = time.monotonic()` ở đầu, `self._timed(result, start)` ở mọi return path
- `except asyncio.CancelledError: raise` BẮT BUỘC
- KHÔNG mutate `ctx.profile` — chỉ đọc

### File I/O

```python
# Atomic write — luôn dùng pattern này cho data file
tmp_path = path + ".tmp"
with open(tmp_path, "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=2)
os.replace(tmp_path, path)
```

**Rules:**
- `encoding="utf-8"` BẮT BUỘC (cho cả read và write)
- `ensure_ascii=False` cho JSON tiếng Việt
- Atomic write qua `.tmp` + `os.replace`
- Concurrent write → `threading.Lock` (xem `AdsFilter.save`)

### Image fetch strategy

```python
from abc import ABC, abstractmethod

class ImageFetchStrategy(ABC):
    @abstractmethod
    async def fetch(self, ref: ImageRef) -> bytes | None: ...

class WebImageFetcher(ImageFetchStrategy):
    """HTTP qua curl_cffi qua DomainSessionPool."""
    def __init__(self, pool: DomainSessionPool) -> None: ...

class EpubImageExtractor(ImageFetchStrategy):
    """Read binary từ ebooklib EpubItem."""
    def __init__(self, epub_book: epub.EpubBook) -> None: ...
```

Pipeline image stage chọn strategy theo input type, KHÔNG hardcode HTTP.

---

## 17. Decision Log (LOCKED)

| # | Decision | Choice | Rationale |
|---|---|---|---|
| 1 | Scope v1.0 | Cleanup + 3 input adapter + 3 output mode + image cho web + i18n baseline | Match codebase capability + user vision thật (đa dụng, đa ngôn ngữ, decompose) |
| 2 | Async runtime | `asyncio` | Đã có, mature, scope đủ |
| 3 | HTTP fetch | `curl_cffi` default, Playwright fallback | TLS fingerprint quan trọng cho anti-bot |
| 4 | AI provider | Google Gemini (full model, không flash-lite) | Free tier hữu ích, full model cho structured output |
| 5 | Tránh Trafilatura | Không integrate | Generic article extraction khác novel chain — scope mismatch |
| 6 | Profile storage | JSON file (`data/site_profiles.json`) | Single-user, no concurrent write across process, atomic write đủ |
| 7 | Progress storage | JSON file per story (`progress/{...}.json`) | Resume-friendly, human-readable |
| 8 | Learning AI calls | 8 calls (AI#1–AI#8) + Naming Phase riêng | Naming là post-learn task, gộp số làm rối |
| 9 | Pipeline serialization | KHÔNG dùng — đọc thẳng từ SiteProfile flat fields | Batch B fix bug M4 (roundtrip lost nested params) |
| 10 | Title voting | First-wins theo priority, KHÔNG weighted vote | Vote phức tạp, first-wins đủ với priority order tốt |
| 11 | Content cleaning | 5-pass với MAX_STRIP_RATIO 60% | Defense in depth, nhưng có safety cap |
| 12 | AdsFilter | 2-tier (auto >=10, AI verify 3-9) + cross-chapter frequency | Cân bằng tự động + AI review |
| 13 | Image policy | Per-mode (Obsidian: download local, Translate/Raw: skip) | Tiết kiệm bandwidth khi không cần |
| 14 | CleanedChapter DTO | Contract giữa pipeline và writer | Cho phép add input adapter / output writer độc lập |
| 15 | Case-based learning | DEFER v1.1+ | Premature design — chờ 10+ profile để thấy pattern thật |
| 16 | TypedDict refactor | DEFER v1.1+ | High-risk, không blocking |
| 17 | Test framework | Defer formal tests, chỉ smoke test trong v1.0 | Solo dev, ROI thấp cho unit test ở giai đoạn này |
| **18** | **Phase ordering** | **Output Abstraction (Phase 1) TRƯỚC Image Support (Phase 2)** | **Image policy là per-mode → cần RunConfig trước → cần CleanedChapter trước. Đảo thứ tự = technical debt cố ý.** |
| **19** | **Baseline snapshot** | **`tools/snapshot_baseline.py` chạy TRƯỚC mọi refactor lớn (Phase 0 Batch A/B, Phase 1.5 pipeline refactor)** | **Smoke test pass ≠ output identical. Vault Obsidian của user sẽ mismatch nếu output format silent change.** |
| **20** | **Image fetch strategy** | **Strategy pattern: `WebImageFetcher` (HTTP) vs `EpubImageExtractor` (zip binary), interface chung** | **EPUB image không reachable qua HTTP — cần code path riêng nhưng cùng interface để pipeline không quan tâm source.** |
| **21** | **TXT scope v1.0** | **Vietnamese + English chapter pattern only. CJK ("第N章", "第N話") defer v1.1.** | **Phase 5 highest risk — narrow scope tăng chance ship. CJK cần i18n hardening riêng (encoding heuristic, Han chapter regex), không fit 2 tuần.** |
| **22** | **i18n baseline v1.0** | **UTF-8 read/write đúng + Latin script chapter pattern. Site đa ngôn ngữ work qua pipeline existing.** | **Content có CJK chars vẫn pass qua pipeline (BeautifulSoup, regex content_cleaner Unicode-safe). Chỉ chapter boundary detection cần language-specific pattern — defer phần CJK.** |
| **23** | **Naming for EPUB** | **EPUB metadata first (`book.get_metadata('DC', 'title')`), AI fallback nếu metadata trống** | **EPUB chuẩn có Dublin Core metadata. Trust source trước, AI sau.** |
| **24** | **Profile migration UX** | **`main.py --bulk-relearn [--pattern <regex>]` thay vì manual `!relearn` từng cái** | **User có 5+ profile cũ sau breaking schema change — manual không scale.** |
| **25** | **README maintained throughout** | **README.md skeleton tạo ở Phase 0, update sau mỗi phase có CLI/UX change** | **Solo dev sau 2 tuần không động vào tool sẽ quên flag — cần reference cập nhật.** |
| **26** | **Batch A done (2026-05-16, P0.2)** | **`learning/optimizer.py` xóa, `--fast-learning` semantic đổi sang "skip ProseRichness validation"** | **Optimizer "AI scoring AI" không add signal — xác nhận anti-pattern #9. ~450 dòng dead code đi.** |
| **27** | **Batch B done (2026-05-16, P0.3)** | **`StepConfig`/`ChainConfig`/`PipelineConfig` + `learning/migrator.py` xóa. `PipelineRunner` đọc thẳng SiteProfile flat fields. `ProfileManager.get()` raise `ValueError` cho profile v1 (`pipeline` field)** | **Root cause bug M4 (nested params lost roundtrip) — xác nhận anti-pattern #3. Profile v1 fail-loud thay vì auto-migrate silent — user re-learn qua `!relearn` hoặc `--bulk-relearn`. ~330 dòng đi (Batch A+B tổng ~780 dòng).** |

---

## 18. Anti-patterns (bài học đắt — TRÁNH)

> Pattern đã đốt thời gian thật trong codebase này.

1. **Biện pháp chống cháy (firefighting)** — thêm regex strip vào cleaner thay vì fix selector. Cấm.
2. **Silent failure** — `except: pass` không log = bug ẩn tháng sau mới biết.
3. **Serialization roundtrip** — `to_dict → JSON → from_dict` mỗi chapter, nested params lost (bug M4). Cấm tái sinh `StepConfig`.
4. **Mutating shared state trong block** — block mutate `ctx.profile` → 5 chapter sau profile nhiễu loạn không debug được.
5. **AI prompt không có format constraint** — AI trả HTML/markdown làm keyword filter (bug ADS-B). Mọi prompt mới phải có "PLAIN TEXT ONLY" hoặc tương đương.
6. **Trust AI bug report** — AI báo "đã fix" mà chưa chạy. Cấm — luôn verify bằng smoke test.
7. **Cache singleton race** — `AdsFilter.save()` concurrent corruption (bug FIX-ADSSAVE). Dùng `threading.Lock` + atomic write.
8. **Swallow CancelledError** — `except Exception: pass` ăn luôn cancel → Ctrl+C không kill được. Luôn re-raise.
9. **Optimizer "AI scoring AI"** — AI đánh giá kết quả AI khác = circular, không add signal. Đã xóa (Batch A).
10. **One file giant** — `phase_ai.py` từng 1500+ dòng. Split theo phase (Discovery/Resolution/Intelligence/Synthesis) nếu vượt 800.
11. **Generic-first thinking** — "support any site" thay vì "support 3 site cụ thể" → over-engineering. Concrete trước, generalize sau.
12. **DEFERRED feature creep** — user nói "có thể sau này..." → KHÔNG code ngay. Ghi `docs/V1_1_BACKLOG.md`.
13. **Phase ordering ignored** — code feature trước khi foundation (vd image trước RunConfig) = technical debt cố ý. Sequencing có lý do, đừng đảo.
14. **Smoke test = regression test** — smoke test chỉ verify "không crash", không verify "output identical với baseline". Refactor lớn ép phải baseline diff.
15. **One-strategy-fits-all** — assume HTTP image fetcher dùng được cho EPUB image. Source khác = code path khác, dùng Strategy pattern.
16. **Encoding implicit** — `open(path)` thay vì `open(path, encoding="utf-8")` → Windows default cp1252 → CJK content crash hoặc mojibake. Luôn explicit.

---

## 19. When to ask Claude (chat) vs Claude Code

**Claude Code giỏi:** implement code, fix bug cụ thể, refactor file, viết test, smoke test
**Claude (chat) giỏi:** design decision, debate kiến trúc, giải thích concept, đánh giá ý tưởng

**Hỏi chat khi:**
- "Step này có nhất thiết không?"
- "Tại sao Path A mà không Path B?"
- "Anh thấy dự án mình có vấn đề gì không?"
- "Có nên làm feature X bây giờ hay defer?"
- "Tôi mất hứng, có nên pause không?"
- Bí kỹ thuật mà Code không hiểu yêu cầu

**Đừng hỏi chat:**
- "Viết code cho tôi" → việc Code
- "Tại sao file này lỗi?" → Code thấy file, chat không

---

## 20. Reference Documents

Root folder:

- `CLAUDE.md` — file này, governance
- `BLUEPRINT.md` — vision + architecture chi tiết (input adapter, output mode, pipeline detail, data model, learning phase)
- `ROADMAP.md` — lộ trình execution: Phase 0 cleanup → Phase 1 output abstraction → Phase 2 image → Phase 3 EPUB → Phase 4 writers → Phase 5 TXT → Phase 6 final cleanup → Phase 7+ (v1.1 defer)
- `README.md` — user-facing quick start (maintain từ Phase 0)
- `docs/V1_1_BACKLOG.md` — features defer
- `docs/MIGRATION_NOTES.md` — note về breaking change (nếu có)

**Runtime files (gitignored):**
- `data/site_profiles.json` — per-domain learned profiles
- `data/ads_keywords.json` — per-domain ads keywords
- `data/txt_cases.json` — TXT chapter pattern database (Phase 5+)
- `data/baselines/{snapshot_name}/` — regression baseline output
- `progress/{domain}_{slug}_{hash8}.json` — per-story progress
- `output/{story_name_clean}/` — chapter files
- `issues.md` — session issue log

**Tools (committed):**
- `tools/snapshot_baseline.py` — capture baseline output cho regression diff

**Khi user hỏi:**
- Vision/architecture → §1, §2, §5 + BLUEPRINT.md
- Step number / thứ tự execution → ROADMAP.md
- Phase dependency → §5 "Phase ordering rationale" + ROADMAP.md tiền điều kiện
- Design decision khó → hỏi Claude chat
- Bug đã fix trước đó → grep `# Fix` hoặc `# Batch` trong code

---

## 21. Self-check trước MỌI response của Claude Code

- [ ] Đã đọc CLAUDE.md TRƯỚC?
- [ ] Đã đọc BLUEPRINT.md nếu task chạm kiến trúc?
- [ ] Đã đọc ROADMAP.md để biết phase hiện tại + dependency?
- [ ] Task trong Scope Lock §3? DEFERRED → STOP §10
- [ ] Phase này phụ thuộc phase nào — đã done chưa?
- [ ] Restate task §8.1?
- [ ] Đã dùng grep/glob trước khi view full file §6.2?
- [ ] Đã view_range thay vì view full file lớn §6.3?
- [ ] KHÔNG đọc lại file đã đọc trong session §6.4?
- [ ] KHÔNG quote lại nội dung user vừa paste §7.1?
- [ ] Plan >5 file changes? STOP §10
- [ ] Sửa shared logic (`pipeline/base.py`, `executor.py`, `core/scraper.py`, `core/formatter.py`)? STOP §10 ask user
- [ ] Đổi return type function nhiều caller? STOP §10
- [ ] Refactor lớn — đã chạy `tools/snapshot_baseline.py` chưa? §8.5
- [ ] Destructive op? STOP §10
- [ ] Sau code: chạy smoke test thật §9.1? Refactor lớn = baseline diff §9.2?
- [ ] Commit conventional §13?
- [ ] Definition of Done §14 có item nào skip?
- [ ] Dùng `print` trong library code / bare except / swallow Cancel §11?
- [ ] `encoding="utf-8"` explicit cho mọi `open()` §11?
- [ ] Output có ngắn gọn không, có 1-3 dòng tóm tắt + việc tay user không §7.3?

**Fail item nào → fix trước khi send.**

---

## 22. Phiên bản

| Version | Date | Change |
|---|---|---|
| 1.0 | 2026-05-15 | Initial — adapt từ TriLex CLAUDE.md v2.1 cho Cào Text, thêm READ-FIRST (§6) + CONTEXT-BUDGET (§7) rules |
| **1.1** | **2026-05-16** | **Phase ordering fix (output trước image), baseline snapshot protocol (§8.5 + Decision #19), Strategy pattern cho image fetch (Decision #20), TXT scope narrow VN+EN (Decision #21), i18n baseline (Decision #22), bulk-relearn UX (Decision #24), README throughout (Decision #25), 4 anti-patterns mới (13-16)** |

**END CLAUDE.md v1.1**

> *"Đọc đúng chỗ giá trị hơn đọc nhiều chỗ. Hỏi sớm tiết kiệm hơn fix sau. Root cause đáng giá hơn 10 lớp band-aid. Phase ordering có lý do, đừng đảo."*
