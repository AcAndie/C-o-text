# AGENTS.md — Hướng dẫn DUY NHẤT cho AI làm việc trên Cào Text

> **Đây là file hướng dẫn duy nhất của dự án.** Mọi AI (Antigravity, Claude Code, Codex, Cursor…) PHẢI đọc toàn bộ file này trước khi làm bất cứ việc gì.
> Các tài liệu cũ (`CLAUDE.md` bản dài, `BLUEPRINT`, `ROADMAP`, `V1_1_BACKLOG`, `TROUBLESHOOTING`, các `PHASE_*_RETRO`…) đã bị xóa và gộp vào đây (xem lại bằng git nếu cần: commit `970dc16`).
> Tài liệu cho người dùng: `README.md`, `Vault/_Scraper/README.md`. Lịch sử phiên bản: `docs/CHANGELOG.md`.

---

## 0. Cách dùng file này

### 0.1 Với AI
1. Đọc hết file này một lần mỗi phiên. Không đọc lại trong cùng phiên trừ khi file vừa bị sửa.
2. Xem **§2 Trạng thái** để biết đang ở phase nào, task nào kế tiếp.
3. Làm đúng task trong **§5** theo thứ tự. Không nhảy phase. Không tự thêm tính năng ngoài kế hoạch.
4. Xong mỗi task: chạy kiểm tra (§3.3) → commit → **cập nhật ô checkbox trong §5 và bảng §2** → ghi quyết định mới (nếu có) vào **§10**.
5. File này mâu thuẫn với code cũ → file này thắng. User yêu cầu mâu thuẫn với file này → DỪNG, hỏi user.
6. Khi kết thúc phiên: báo lại ngắn gọn bằng tiếng Việt: đã làm gì, test ra sao, user cần làm gì bằng tay.

### 0.2 Với user (câu lệnh mẫu để giao việc)
- *"Đọc AGENTS.md, làm task tiếp theo chưa xong trong phase hiện tại."*
- *"Đọc AGENTS.md, làm hết Phase 2, dừng lại cho tôi duyệt trước khi sang Phase 3."*
- *"Đọc AGENTS.md, golden test báo khác ở đâu? Giải thích cho tôi trước khi cập nhật."*

---

## 1. Dự án là gì

| | |
|---|---|
| **Tên** | Cào Text — công cụ chuẩn hóa nội dung tiểu thuyết, dùng cá nhân |
| **Owner** | Một người, vibe coder, không rành code chi tiết. **Luôn giao tiếp bằng tiếng Việt**, giải thích ngắn gọn, dễ hiểu |
| **Nền tảng** | Windows 10/11 (chính), Python 3.11+, `asyncio` |
| **Tầm nhìn** | Ném input nào vào (URL truyện web / `.epub` / `.txt`) cũng ra một bộ chương sạch, không rác, đọc được trên Obsidian hoặc đem đi dịch. Site mới chỉ cần AI học 1 lần, lần sau dùng lại profile. |

**3 input × 3 output:**

| Input | Cách xử lý |
|---|---|
| URL web | Học cấu trúc site 1 lần (AI) → lưu profile → cào từng chương theo nút "Next", resume được khi Ctrl+C |
| EPUB | Đọc spine + TOC → gộp/tách chương → trích ảnh nhúng |
| TXT | Regex tìm ranh giới chương (VN "Chương N", EN "Chapter N"), AI fallback khi pattern lạ |

| Output (`--output-mode`) | File | Ảnh |
|---|---|---|
| `obsidian` (mặc định) | `0042_Ten_Chuong.md` + YAML frontmatter, `0000_Index.md` mục lục, nav trước/sau | Tải về `images/` |
| `translate` | `0042.txt`, tiêu đề ở dòng 1, mỗi đoạn một dòng | Thay bằng `[IMAGE: alt]` |
| `raw` | `0042.txt` chỉ text | Xóa |

**Vị trí runtime (cấu hình trong `config.toml`):** output `Vault/Novels/`, danh sách link `Vault/_Scraper/links.md`, log lỗi `Vault/_Scraper/issues.md`, EPUB inbox `Vault/_Scraper/epub_inbox/`, profile `data/site_profiles.json`, tiến độ `progress/`.

---

## 2. Trạng thái hiện tại

**Dự án đang ở giai đoạn: VIẾT LẠI CÓ CHỌN LỌC (v1.2.1 → v2.0.0).**
Code cũ (v1.2.1, ~13k dòng trong `src/`) vẫn chạy được và vẫn là bản user đang dùng cho đến khi xong Phase 7.

| Phase | Tên | Trạng thái |
|---|---|---|
| 0 | Lưới an toàn: fixtures + golden test + sửa 2 chỗ hỏng | ✅ Xong |
| 1 | Bộ khung package mới (`src/cao_text/`) | ✅ Xong |
| 2 | Port phần lõi xác định (HTML, extract, writers, net) | ✅ Xong |
| 3 | Lớp AI mới (provider, structured output, retry) | 🟨 |
| 4 | Learning mới (1–3 AI call + kiểm chứng bằng code) | ⬜ |
| 5 | Vòng lặp cào web mới + lưu tiến độ mới | ⬜ |
| 6 | EPUB/TXT flow hợp nhất + sửa lỗi EPUB lớn | ⬜ |
| 7 | CLI mới + chuyển hẳn sang code mới + xóa code cũ | ⬜ |
| 8 | Backlog sau khi chuyển (tùy chọn) | ⬜ |

Ký hiệu: ⬜ chưa làm · 🟨 đang làm · ✅ xong. **AI phải cập nhật bảng này.**

**Nhánh git:** làm toàn bộ trên nhánh `rewrite-v2`. Chỉ merge vào `main` khi xong Phase 7 và user đồng ý.

---

## 3. Quy tắc làm việc

### 3.1 Luôn luôn
- Giao tiếp tiếng Việt, ngắn gọn, có link file.
- `from __future__ import annotations`, type hints cho mọi hàm mới, `X | None`.
- Mở file luôn có `encoding="utf-8"` (Windows mặc định cp1252 → lỗi tiếng Việt).
- Ghi file quan trọng (profile, progress, chương) bằng **atomic write**: ghi `.tmp` → `os.replace`; xóa `.tmp` nếu bị cancel.
- I/O mạng dùng `async/await`. Xử lý HTML nặng (BeautifulSoup) chạy qua `asyncio.to_thread` khi gọi từ vòng lặp async.
- Dùng `logging` (không dùng `print` trong code mới, trừ `cli.py` khi in tiến độ cho user).
- Commit nhỏ, mỗi task một commit, dạng conventional: `feat(learn): ...`, `fix(html): ...`, `refactor(...)`, `test(...)`, `docs(...)`, `chore(...)`.

### 3.2 Không bao giờ
- Nuốt `asyncio.CancelledError` (luôn `except asyncio.CancelledError: raise` trước `except Exception`). Nuốt nó làm Ctrl+C bị treo.
- `except:` trần, hoặc `except Exception: pass` không log.
- Hardcode API key; commit `.env`, `config.toml`, `Vault/Novels/`, `progress/`, file `.epub` (bản quyền), `data/*` (trừ file được whitelist trong `.gitignore`).
- Gọi mạng thật trong `pytest` (test phải chạy offline 100%).
- Sửa file golden để test "xanh" mà không giải thích diff cho user (§3.5).
- Dùng `requests` / `httpx` / `aiohttp` trực tiếp (đã có `curl_cffi`), `selenium` (đã có Playwright), `scrapy`, `trafilatura`, database, web framework.

### 3.3 Kiểm tra sau MỌI thay đổi (bắt buộc, báo kết quả thật)
```powershell
python -m pytest -q            # tất cả test offline, kể cả golden
python -m ruff check src tests # lint
```
- Task đụng tới mạng/AI: chạy thêm 1 smoke test thật (ví dụ cào 3 chương RoyalRoad vào thư mục tạm) và dán log rút gọn.
- **Không được báo "đã xong/đã fix" khi chưa chạy kiểm tra.**

### 3.4 Phải hỏi user trước khi
| Việc | Lý do |
|---|---|
| Xóa/sửa dữ liệu user: `Vault/Novels/`, `progress/`, `data/site_profiles.json`, `data/ads_keywords.json` | Mất dữ liệu |
| Đổi định dạng tên file output (`0042_Title.md`, `0000_Index.md`) hoặc frontmatter | Vỡ thư viện truyện đã cào |
| Thêm thư viện ngoài danh sách §3.6 | Phình dependency |
| Cập nhật golden khi diff làm **thay đổi nội dung chương** | Có thể mất chữ thật |
| Merge `rewrite-v2` vào `main`, xóa code cũ (Phase 7) | Không quay lại dễ |
| `git push --force`, `git reset --hard`, `rm -rf` | Hủy dữ liệu |

Cách hỏi: *"Tôi định [X]. Lý do: [Y]. Ảnh hưởng: [Z]. OK không?"*

### 3.5 Quy trình golden diff
1. Golden test fail → in ra **tóm tắt diff** (chương nào, mất/thêm dòng nào).
2. Phân loại: (a) lỗi port → sửa code; (b) cải tiến có chủ đích (ví dụ đã fix watermark RoyalRoad) → hỏi user, được đồng ý mới chạy `pytest --update-golden` và ghi vào §10.

### 3.6 Thư viện được phép
Runtime: `curl_cffi`, `beautifulsoup4`, `lxml`, `playwright`, `playwright-stealth`, `google-genai`, `ebooklib`, `python-dotenv`, `pydantic>=2`.
Dev: `pytest`, `pytest-asyncio`, `ruff`.
Muốn thêm (ví dụ `openai` cho provider thứ 2, `charset-normalizer`) → hỏi user.

### 3.7 Nguyên tắc thiết kế
- **Root cause > chữa cháy:** lỗi rác nội dung → sửa selector / bộ lọc DOM / prompt, không đắp thêm regex xóa chữ.
- **AI đề xuất, code kiểm chứng:** mọi thứ AI trả về (selector, regex, quyết định gộp chương) phải được kiểm tra bằng code trên dữ liệu thật trước khi dùng.
- **Hàm thuần dễ test:** phần xử lý HTML → Markdown không được gọi mạng, không gọi AI, không ghi file. Mạng/AI/ghi file nằm ở lớp ngoài.
- **Không over-engineer:** không làm tính năng "phòng khi cần".

---

## 4. Kiến trúc đích (v2)

### 4.1 Cấu trúc thư mục
```
pyproject.toml                 # thay requirements.txt; cài bằng: pip install -e .[dev]
main.py                        # shim 3 dòng: from cao_text.cli import main; main()
src/cao_text/
  __init__.py                  # __version__ = "2.0.0"
  __main__.py                  # python -m cao_text
  cli.py                       # argparse, đọc links.md, dispatch web/epub/txt, epub inbox, heal index
  settings.py                  # Settings (dataclass): .env + config.toml + CLI. KHÔNG side effect khi import
  log.py                       # setup logging console + issues.md reporter
  models.py                    # SiteProfile (pydantic, persist), StoryState, RunConfig, CleanedChapter, ImageRef
  storage.py                   # atomic_write_json/text, ProfileStore, ProgressStore
  net/
    http.py                    # DomainSessionPool: curl_cffi, impersonate Chrome, per-host semaphore, delay, CF detect
    browser.py                 # PlaywrightPool (+ stealth best-effort)
  html/
    filter.py                  # prepare_soup (port core/html_filter.py) + fix style-hidden (§7.5)
    formatter.py               # MarkdownFormatter (port core/formatter.py)
    cleaner.py                 # clean_extracted_content (port utils/content_cleaner.py)
    ads.py                     # AdsFilter (port utils/ads_filter.py) + ngưỡng mới (§7.3)
  extract/
    content.py title.py nav.py validate.py   # các block, gộp core/navigator + pipeline/navigator
    page.py                    # process_page(html, url, profile) -> PageResult  ← HÀM THUẦN, sync
  ai/
    provider.py                # Protocol LLMProvider + lỗi chuẩn hóa (RateLimited, Transient, Fatal)
    gemini.py                  # GeminiProvider: key pool, rate limiter, retry, fallback model
    schemas.py                 # pydantic models cho output AI
    prompts.py                 # prompt ngắn, mỗi prompt một hàm
    skeleton.py                # nén HTML thành "DOM skeleton" gửi cho AI
  learn/
    candidates.py              # tìm ứng viên content/title/next bằng heuristic (không AI)
    verify.py                  # kiểm chứng profile trên các chương mẫu
    learner.py                 # learn_site(): fetch mẫu → AI phân tích → verify → AI sửa → lưu
  web/
    start.py                   # phân loại URL (index/chapter), tìm chương 1 (gồm fast-path Webnovel)
    session.py                 # ScrapeSession: vòng lặp cào, các guard, resume
  files/
    epub_plan.py               # lập kế hoạch chương EPUB (rule + AI-rule)
    epub.py txt.py             # đọc EPUB/TXT → RawDocument
    txt_cases.json             # DB pattern TXT (commit vào repo)
    flow.py                    # run_file_flow(spec) dùng chung EPUB/TXT
  images/
    stage.py                   # apply_image_stage dùng chung web/epub
    web.py epub.py             # ImageFetchStrategy
  writers/                     # obsidian.py translation.py raw.py nav_injector.py factory.py (port)
tests/
  conftest.py                  # option --update-golden, helper so sánh
  fixtures/                    # dữ liệu tổng hợp nhỏ, COMMIT được (txt mẫu, epub tự tạo, html mẫu tự viết)
  fixtures_local/              # HTML/EPUB thật, GITIGNORE (bản quyền); test tự skip nếu thiếu
  golden/                      # output kỳ vọng (cho fixtures commit được) — commit
  golden_local/                # output kỳ vọng cho fixtures_local — gitignore
tools/
  record_fixtures.py           # tải HTML N chương liên tiếp của 1 truyện → fixtures_local
  make_golden_v1.py            # chạy CODE CŨ offline trên fixtures → golden (chỉ dùng ở Phase 0)
```

### 4.2 Luồng dữ liệu
```
links.md / file ──► cli.py ──┬─► web/start.py ─► learn/learner.py (nếu chưa có profile) ─► web/session.py
                             │        mỗi chương: net/http fetch ─► extract/page.process_page (thuần)
                             │                    ─► html/ads ─► images/stage ─► writers ─► ProgressStore
                             └─► files/flow.py (epub|txt) ─► extract/page.process_page ─► images/stage ─► writers
```

### 4.3 Hợp đồng chính (phác thảo — giữ đúng tinh thần, chi tiết tùy chỉnh)
```python
# extract/page.py — KHÔNG mạng, KHÔNG AI, KHÔNG ghi file
@dataclass
class PageResult:
    content_md: str | None        # đã qua formatter + cleaner
    title: str | None
    title_method: str             # "selector" | "h1" | "title_tag" | "og" | "url_slug"
    next_url: str | None
    nav_method: str               # "rel_next" | "selector" | "anchor_text" | "slug_increment" | "fanfic" | "dropdown"
    images: list[ImageRef]
    selector_used: str | None
    is_index_page: bool
    diagnostics: dict             # độ dài, link density, các block đã thử

def process_page(html: str, url: str, profile: SiteProfile | None, *, source: Literal["web","epub","txt"]) -> PageResult: ...

# ai/provider.py
class LLMProvider(Protocol):
    async def generate(self, prompt: str, schema: type[T]) -> T: ...   # T là pydantic BaseModel; lỗi → raise AIError
```
AI fallback (AI trích nội dung, AI tìm next) **không** nằm trong `process_page`; `web/session.py` gọi tường minh khi `PageResult` rỗng.

### 4.4 Bảng ánh xạ code cũ → mới
| Cũ (`src/`) | Mới (`src/cao_text/`) | Cách làm |
|---|---|---|
| `config.py` | `settings.py` + hằng số trong module dùng nó | Viết lại (bỏ `SystemExit` khi import) |
| `utils/types.py`, `pipeline/base.py` (DTO) | `models.py` | Viết lại bằng pydantic/dataclass |
| `utils/file_io.py`, `learning/profile_manager.py` | `storage.py` | Viết lại |
| `core/session_pool.py`, `core/fetch.py`, `pipeline/fetcher.py` | `net/http.py`, `net/browser.py` | Port + gộp |
| `core/html_filter.py` | `html/filter.py` | Port + fix §7.5 |
| `core/formatter.py` | `html/formatter.py` | Port gần nguyên |
| `utils/content_cleaner.py`, `core/chapter_writer.py::strip_nav_edges` | `html/cleaner.py` | Port |
| `utils/ads_filter.py` | `html/ads.py` | Port + fix §7.3 |
| `pipeline/extractor.py`, `title_extractor.py`, `navigator.py`, `validator.py`, `executor.py`, `core/navigator.py` | `extract/*` | Port logic, bỏ lớp ScraperBlock/Chain nặng nề nếu không cần; gộp 2 navigator |
| `ai/client.py`, `ai/agents.py`, `ai/prompts.py` (~2.100 dòng) | `ai/*` (~600 dòng mục tiêu) | **Viết lại** |
| `learning/phase.py`, `phase_ai.py`, `naming.py` | `learn/*` | **Viết lại** (giữ ý tưởng calibration + auto-discover) |
| `core/scraper.py` (1.100 dòng) | `web/session.py` | **Viết lại** (giữ mọi guard §6) |
| `utils/url_classifier.py`, `core/story_meta.py` | `web/start.py` | Port |
| `core/orchestrator.py`, `ingest/*` | `files/*` | Port + hợp nhất flow + fix §7.3 |
| `core/image_pipeline/*` + 2 hàm `_apply_*image_stage` | `images/*` | Port + gộp |
| `writers/*` | `writers/*` | Port gần nguyên |
| `utils/issue_reporter.py`, `utils/string_helpers.py`, `utils/epub_inbox.py` | `log.py`, rải vào module dùng, `cli.py` | Port |
| `main.py` | `cli.py` | Viết lại, giữ nguyên hành vi CLI |
| `src/tools/snapshot_baseline.py` | `tools/record_fixtures.py` + `tools/make_golden_v1.py` | Thay thế (bản cũ đang hỏng, §7.6) |

---

## 5. Kế hoạch chi tiết từng phase

> Mỗi task: làm → kiểm tra §3.3 → commit → tick ô. Mỗi phase có **Tiêu chí xong (DoD)**; chưa đạt DoD không sang phase sau.

### Phase 0 — Lưới an toàn (BẮT BUỘC làm trước)
Mục tiêu: chụp lại hành vi code cũ thành golden test chạy offline, để mọi bước viết lại đều so được.

- [x] **0.1** Tạo nhánh `rewrite-v2`. Thêm `pyproject.toml` tối thiểu (metadata, deps §3.6, `[project.optional-dependencies] dev`, cấu hình `ruff` và `pytest`), giữ `requirements.txt` đến Phase 7.
- [x] **0.2** Khôi phục `data/txt_cases.json` (bị xóa nhầm ở commit `e3d9152`, làm TXT flow crash): `git checkout e3d9152^ -- data/txt_cases.json`. Xác nhận `.gitignore` cho phép commit file này.
- [x] **0.3** Viết `tools/record_fixtures.py`: dùng `DomainSessionPool` cũ, đi theo next-link, lưu HTML thô của N chương liên tiếp vào `tests/fixtures_local/web/<domain>/<story>/0001.html…` + `meta.json` (danh sách URL theo thứ tự, ngày ghi, bản sao profile hiện tại của domain).
- [x] **0.4** Ghi fixtures (user chạy, cần mạng): RoyalRoad "Rock falls, everyone dies" 6 chương; Webnovel 2 truyện × 6 chương (các truyện trong `progress/`). Thêm vài trang index/trang chương cuối nếu có.
- [x] **0.5** Fixtures commit được: `tests/fixtures/txt/` (2 file tự viết: VN "Chương N", EN "Chapter N"), `tests/fixtures/epub/` (2 EPUB nhỏ tự tạo bằng `ebooklib` trong script `tests/fixtures/make_epubs.py`: một có TOC, một không TOC + có trang divider "Part 1"), `tests/fixtures/html/` (vài trang HTML tự viết cho các ca: watermark ẩn bằng `<style>`, nút next dạng dropdown, fanfic `/s/ID/N/`).
- [x] **0.6** Fixtures EPUB thật (local, gitignore): chép 2–3 EPUB nhỏ từ `Vault/_Scraper/epub_inbox/` (ví dụ `Ready_Player_One.epub`) + 1 EPUB lớn >1000 chương để tái hiện lỗi §7.3.
- [x] **0.7** Viết `tools/make_golden_v1.py`: chạy **code cũ** offline:
  - Web: với mỗi HTML fixture gọi `PipelineRunner.run(..., prefetched_html=html, ai_limiter=None)` với profile trong `meta.json`, rồi áp `strip_nav_edges` + bỏ dòng tiêu đề trùng như `scrape_one_chapter`. Lưu `{title, content, next_url, nav_method, selector_used}` thành JSON.
  - EPUB/TXT: chạy `run_epub_flow` / `run_txt_flow` với `ai_limiter=None` cho cả 3 output mode vào thư mục tạm, chép kết quả vào `tests/golden[_local]/`.
- [x] **0.8** Viết `tests/conftest.py` (option `--update-golden`, helper so sánh: khớp tuyệt đối cho fixtures tổng hợp; với fixtures thật: khớp danh sách file + tiêu đề, nội dung `difflib` ratio ≥ 0.99, khác thì in diff gọn) và `tests/test_golden_v1.py` chạy code cũ so với golden (phải xanh ngay).
- [x] **0.9** Ghi vào §10 danh sách **lỗi đã biết đang nằm trong golden** (watermark RoyalRoad §7.5, rác UI Webnovel §7.4) để sau này diff ở đó là "cải tiến có chủ đích".

**DoD Phase 0:** `pytest -q` xanh offline; có golden cho ≥2 site web, ≥2 EPUB, ≥2 TXT × 3 output mode; TXT flow cũ chạy lại được.

### Phase 1 — Bộ khung package mới
- [x] **1.1** Tạo `src/cao_text/` theo §4.1 (file rỗng/khung), `pip install -e .[dev]` chạy được, `python -m cao_text --help` in được.
- [x] **1.2** `settings.py`: dataclass `Settings` load theo thứ tự ưu tiên **CLI > env > config.toml > mặc định**; đọc nhiều key `GEMINI_API_KEY` và `GEMINI_API_KEY_<số>` (regex chặt `^GEMINI_API_KEY(?:_\d+)?$`); thiếu key chỉ báo lỗi **khi thật sự cần gọi AI**, không phải lúc import. Giữ tương thích mọi khóa `config.toml` hiện có (`[output]`, `[paths]`, `[scraper]`, `[learning]`, `[ai]`, `[http]`, `[js_detection]`).
- [x] **1.3** `log.py`: logging console gọn (giữ emoji/tiền tố domain như cũ cho dễ đọc) + `IssueReporter` ghi `issues.md` (newest on top, các loại: `BLOCKED`, `CONTENT_SUSPICIOUS`, `TITLE_FALLBACK`, `NEXT_URL_MISSING`…).
- [x] **1.4** `models.py`: `SiteProfile` (pydantic, `profile_version=3`), `StoryState`, `RunConfig` (mặc định theo mode như §1), `CleanedChapter`, `ImageRef`.
- [x] **1.5** `storage.py`: `atomic_write_text/json` (dọn `.tmp` khi cancel), `ProfileStore` (load/save/delete, lock async), `ProgressStore` (thiết kế §5 Phase 5, làm khung trước).
- [x] **1.6** Test đơn vị cho settings (ưu tiên nguồn), atomic write, model round-trip.

**DoD:** package cài được, test mới xanh, code cũ không bị ảnh hưởng (golden v1 vẫn xanh).

### Phase 2 — Port phần lõi xác định
Nguyên tắc: **copy logic sang rồi dọn**, không thiết kế lại thuật toán. So với golden sau mỗi task.
- [x] **2.1** `net/http.py` + `net/browser.py`: port `DomainSessionPool` (impersonate Chrome xoay vòng, header + referer, per-host semaphore mặc định 3, delay theo domain, nhận diện Cloudflare → đánh dấu domain dùng Playwright, `fetch_bytes` cho ảnh) và `PlaywrightPool` (giới hạn instance, stealth best-effort). Giữ quy tắc "HTTP 429 với HTML rỗng → raise, không coi là hết truyện".
- [x] **2.2** `html/filter.py`: port `prepare_soup` đủ các layer (luôn xóa script/style/iframe; `KNOWN_NOISE_SELECTORS`; `remove_selectors` của profile; **bảo vệ tổ tiên** của content/title/next selector; phần tử bị ẩn qua inline style/class ẩn; class bị làm rối nhưng **không đụng `<p>`**).
- [x] **2.3** `html/formatter.py`, `html/cleaner.py` (gồm `strip_nav_edges`, 5–7 pass, trần an toàn xóa tối đa 60%).
- [x] **2.4** `extract/*` + `extract/page.py::process_page`: chain content (selector → JSON-LD → density heuristic ưu tiên wrapper → fallback list), title first-wins (selector 0.95 → h1 0.80 → `<title>` 0.65 → og:title 0.65 → url slug 0.40), nav (rel=next → selector → anchor text → slug increment → fanfic → dropdown), nhận diện trang index, validate độ dài/độ "văn xuôi". Gộp hai navigator cũ thành một.
- [x] **2.5** `tests/test_golden_web.py`: chạy `process_page` mới trên fixtures web, so với golden v1 (profile v2 → v3 qua hàm chuyển đổi trong test). **Phải khớp.**
- [x] **2.6** `writers/*` + `nav_injector`: port, giữ nguyên tên file, frontmatter, index, nav; escape `*` và backtick trong text thường.
- [x] **2.7** `images/*`: một `apply_image_stage(content, refs, strategy, run_config, out_dir, chapter_num)` dùng chung; giữ link gốc khi tải lỗi + ghi `failed_images` vào frontmatter; EPUB resolver 4 chiến lược + fallback basename.
- [x] **2.8** Fix §7.5 (watermark RoyalRoad ẩn bằng `<style>`): trước khi xóa `<style>`, quét CSS tìm selector class/id có `display:none | visibility:hidden | opacity:0 | font-size:0 | speak:never` → xóa phần tử khớp. Thêm test với `tests/fixtures/html/`. Golden RoyalRoad sẽ đổi (mất câu watermark) → quy trình §3.5.
- [x] **2.9** Fix một phần §7.4: thêm selector UI Webnovel (`.cha-hd`, `.cha-foot`, `.j_bottom_comment_area`, `.para-comment`, `.g_ad`…) vào `KNOWN_NOISE_SELECTORS`; bỏ số đếm comment dính cuối đoạn. Golden Webnovel đổi → §3.5.

**DoD:** golden web khớp (trừ diff đã duyệt ở 2.8/2.9), test writers/images xanh.

### Phase 3 — Lớp AI mới
- [x] **3.1** Đầu phase: **tra tài liệu chính thức** (https://ai.google.dev/gemini-api/docs/models) để chọn model Flash ổn định mới nhất làm mặc định + model fallback. Model chỉ khai báo ở `settings.py` / `config.toml` (`[ai] model`, `[ai] fallback_model`), không rải khắp nơi. Ghi lựa chọn vào §10. Không dùng biến thể "lite" cho structured output.
- [ ] **3.2** `ai/provider.py`: `LLMProvider` Protocol, lỗi chuẩn hóa `AIRateLimited`, `AITransient`, `AIFatal`, `AIInvalidOutput`.
- [ ] **3.3** `ai/gemini.py`: `google-genai` async; structured output bằng `response_schema=<PydanticModel>` và đọc `response.parsed`; phân loại lỗi theo **mã lỗi của SDK** (`google.genai.errors.APIError.code`: 429/503 → rate limit, 5xx/timeout/connect → transient), **không** dò chữ trong message. Key pool xoay vòng + cooldown 60s khi 429/503, bỏ chờ nếu còn key rảnh; rate limiter token-bucket (`[ai] max_rpm`, rollback slot khi bị cancel); backoff có giới hạn; hết retry thì thử fallback model một lần. Output sai schema → 1 lần gọi lại kèm lỗi validate.
- [ ] **3.4** `ai/skeleton.py`: nén HTML thành DOM skeleton (bỏ script/style/svg/noscript/comment; chỉ giữ thuộc tính `id`, `class`, `rel`, `href` của link điều hướng, `role`, `aria-*`; text cắt ≤80 ký tự/nút; gộp con lặp lại; giới hạn tổng ký tự cấu hình được). Test với fixtures.
- [ ] **3.5** `ai/prompts.py` + `ai/schemas.py`: prompt ngắn, mỗi prompt ràng buộc output bằng schema. Các prompt cần: `analyze_site`, `repair_site`, `classify_page` (index/chapter + next/first chapter), `extract_content` (fallback), `verify_ads_lines`, `txt_pattern`, `epub_rules`.
- [ ] **3.6** `FakeProvider` cho test (trả output định sẵn theo tên schema) — mọi test học/cào dùng fake, không gọi AI thật.
- [ ] **3.7** (Tùy chọn, chỉ khi user yêu cầu) provider OpenAI-compatible (OpenAI/OpenRouter/local) — cần thêm dep `openai` → hỏi trước.

**DoD:** test provider (retry, xoay key, cancel, schema lỗi) xanh bằng mock; 1 smoke call thật thành công.

### Phase 4 — Learning mới (thay 8+ AI call bằng 1–3)
Luồng `learn_site(start_url)`:
1. **Lấy mẫu:** fetch 5 chương liên tiếp bằng nav heuristic (port `_fetch_chapters`); < 3 chương → thất bại rõ ràng. Phát hiện JS-heavy: text Playwright > 1.5× curl và chênh > 500 ký tự → `requires_playwright=True`.
2. **Ứng viên bằng code** (`learn/candidates.py`): container có mật độ text cao, ổn định qua các mẫu (port `_discover_content_selector`: chỉ chọn selector có class/id **thật sự tồn tại** trong HTML, khớp ≥3/5 mẫu với ≥300 ký tự); ứng viên next-link; ứng viên title; các dòng lặp lại giữa nhiều chương (nghi rác/quảng cáo).
3. **AI call #1 `analyze_site`:** gửi skeleton 2 chương + danh sách ứng viên + dòng lặp → nhận `SiteAnalysis` (content/title/next selector, nav_type, remove_selectors, gợi ý watermark, chính sách ảnh, tên truyện, từ khóa chương, dòng rác). Gộp luôn phần đặt tên (naming) vào call này.
4. **Kiểm chứng bằng code** (`learn/verify.py`) trên cả 5 mẫu:
   - V1 content_selector khớp trong mọi mẫu; V2 độ dài ≥300 ký tự và ≥60% khối text dày nhất (không quá hẹp), link density thấp + không chứa chữ UI (không quá rộng — đúng lỗi `div.cha-page` của Webnovel);
   - V3 title tìm thấy ≥80% mẫu và khác nhau giữa các chương; V4 next dẫn đúng URL chương mẫu kế tiếp; V5 remove_selectors không làm mất >20% nội dung; V6 mỗi dòng rác xuất hiện nguyên văn ở ≥2 mẫu.
5. **Sai → AI call #2/#3 `repair_site`** kèm báo cáo lỗi cụ thể (tối đa 2 vòng). Vẫn sai → dùng ứng viên tốt nhất từ bước 2 (hoặc để trống selector cho heuristic), `confidence ≤ 0.3`, ghi `issues.md`.
6. Lưu profile v3. Profile v2 cũ (chỉ có 2: webnovel, royalroad) → học lại; hỏi user trước khi ghi đè `data/site_profiles.json` lần đầu.

- [ ] **4.1** `learn/candidates.py` + test trên fixtures.
- [ ] **4.2** `learn/verify.py` (V1–V6) + test: profile cũ của Webnovel (`div.cha-page`) phải bị V2 đánh fail.
- [ ] **4.3** `learn/learner.py` với `FakeProvider` + test luồng sửa lỗi.
- [ ] **4.4** `web/start.py`: phân loại URL index/chapter, tìm chương 1 (giữ fast-path Webnovel: ID chương nhỏ nhất = chương 1), cache kết quả.
- [ ] **4.5** Smoke thật: học lại RoyalRoad + Webnovel bằng Gemini, so số AI call (mục tiêu ≤3) và kết quả `process_page` với golden đã duyệt.

**DoD:** học được 2 site thật với ≤3 AI call, profile qua V1–V6; Webnovel ra `div.cha-words`/`div.cha-content` hoặc tương đương không dính UI.

### Phase 5 — Vòng lặp cào web mới
- [ ] **5.1** `ProgressStore` mới mỗi truyện: `progress/<story_key>/state.json` (nhỏ: start_url, current_url, chapter_count, story meta, completed, completed_at…) + `progress/<story_key>/seen.jsonl` (append-only `{url, fp, ch}`), **không** ghi lại toàn bộ danh sách URL mỗi chương. Tự chuyển đổi file progress cũ `progress/<domain>_<slug>_<hash>.json` khi gặp (giữ file cũ làm backup `.v1.json`). Giữ nguyên thư mục output đã có để resume viết tiếp đúng chỗ.
- [ ] **5.2** `web/session.py::ScrapeSession`: state gói trong object (thay 13 tham số), mỗi chương trả về `Outcome` enum (`WROTE`, `EMPTY`, `DUPLICATE`, `END`, `BLOCKED`, `RATE_LIMITED`, `ERROR`). Port **đủ mọi guard trong §6.2**.
- [ ] **5.3** AI fallback tường minh: chỉ khi `PageResult` không có nội dung → `extract_content`; không có next → `classify_page`. Ghi `issues.md`.
- [ ] **5.4** AdsFilter tích hợp: 2 pass (trước/sau `strip_nav_edges`), quét cạnh nghi vấn, cuối truyện xác minh bằng AI các dòng tần suất 3–9, tự thêm ≥ ngưỡng (§7.3), hậu xử lý file đã ghi.
- [ ] **5.5** Chạy song song: mỗi URL trong `links.md` là một task; **learning tuần tự** (khóa theo domain, tránh học trùng), cào song song; giãn cách khởi động `init_stagger`.
- [ ] **5.6** Ctrl+C: lưu tiến độ trong `asyncio.shield`, đóng pool, không treo; Windows: lọc lỗi "I/O operation on closed pipe" khi thoát.
- [ ] **5.7** Test `ScrapeSession` offline bằng fake fetcher phục vụ HTML fixtures (vòng lặp chương cuối RoyalRoad, trùng nội dung, story-id lệch, trang index, 5 chương rỗng liên tiếp, 429).
- [ ] **5.8** Smoke thật: cào 10 chương RoyalRoad + Webnovel, Ctrl+C giữa chừng, chạy lại → resume đúng chương.

**DoD:** test session xanh; smoke thật đạt; output đọc được trong Obsidian như bản cũ.

### Phase 6 — EPUB/TXT hợp nhất
- [ ] **6.1** `files/flow.py::run_file_flow(spec)` dùng chung cho EPUB và TXT (gộp `run_epub_flow` + `run_txt_flow`, ~80 dòng trùng lặp). AdsFilter namespace `epub:<slug>` / `txt:<slug>`.
- [ ] **6.2** `files/epub_plan.py` — fix §7.3:
  - Mặc định lập kế hoạch bằng rule (TOC; gộp trang divider Part/Level/Book vào chương sau; không TOC → tách theo pattern TXT).
  - AI chỉ khi rule kém tin cậy, và AI **trả về quy tắc** (regex tiêu đề chương, loại trang cần bỏ, mẫu divider) dựa trên mẫu đầu/giữa/cuối + toàn bộ tiêu đề TOC — **không** bắt AI liệt kê từng doc.
  - Áp quy tắc bằng code; kiểm chứng (số chương hợp lý so với TOC, không chương nào dài > 5× trung vị); sai → về rule-based.
  - Cache theo SHA256 file (định dạng cache mới, có version).
- [ ] **6.3** `files/txt.py`: chỉ đọc UTF-8 (báo lỗi rõ ràng, hướng dẫn convert); DB pattern ở `files/txt_cases.json`; AI fallback kiểm chứng trên 3 đoạn 80 dòng giữa file trước khi lưu pattern mới.
- [ ] **6.4** AdsFilter cho file lớn (§7.3): ngưỡng tự xóa = `max(10, ceil(0.03 × số chương))`; không tự xóa dòng ngắn kiểu thoại/chuyển cảnh (bắt đầu bằng dấu ngoặc kép, kết thúc bằng `:`, < 25 ký tự) trừ khi có dấu hiệu URL/watermark.
- [ ] **6.5** Golden EPUB/TXT so với v1 (diff có chủ đích ở EPUB lớn → §3.5) + test EPUB lớn không còn dồn chương vào một file.

**DoD:** golden file-flow khớp/đã duyệt; EPUB 1500 chương tách đúng.

### Phase 7 — CLI mới & chuyển hẳn
- [ ] **7.1** `cli.py` giữ nguyên hành vi: input mặc định là `links_file` trong config; đọc `links.md`/`.txt` (comment `#`, dòng trống, `!relearn <domain>`); input là `.epub`/`.txt` đơn lẻ; tự xử lý EPUB inbox (manifest SHA256 `data/processed_epubs.json`); tự sửa `0000_Index.md` bị thiếu khi khởi động.
- [ ] **7.2** Đủ cờ CLI cũ: `--output-mode`, `--output-dir`, `--max-pw-instances`, `--per-host-concurrency`, `--fast-learning`, `--no-validation`, `--bulk-relearn`, `--pattern`, `--apply` (bulk-relearn mặc định dry-run, cần gõ xác nhận).
- [ ] **7.3** `main.py` thành shim gọi `cao_text.cli`. Chạy đầy đủ: 1 site web, 1 EPUB inbox, 1 TXT, cả 3 output mode.
- [ ] **7.4** Hỏi user → xóa code cũ (`src/ai`, `src/core`, `src/ingest`, `src/learning`, `src/pipeline`, `src/utils`, `src/writers`, `src/tools`, `src/config.py`), `requirements.txt`, `tools/make_golden_v1.py`, `tests/test_golden_v1.py`. Golden giữ lại làm regression test cho v2.
- [ ] **7.5** Cập nhật `README.md`, `Vault/_Scraper/README.md`, `config.toml.example`, `docs/CHANGELOG.md` (v2.0.0). Cập nhật §2/§4 của file này cho trạng thái mới.
- [ ] **7.6** Hỏi user → merge `rewrite-v2` vào `main`.

**DoD:** user dùng bản mới hằng ngày không cần code cũ; dòng code `src/` giảm còn khoảng 7–8k.

### Phase 8 — Backlog sau chuyển (chỉ làm khi user yêu cầu)
- §7.1 cờ `--check-new` + bỏ qua kiểm tra truyện đã hoàn thành lâu ngày.
- Provider AI thứ 2 (Phase 3.7).
- Mục trong §8 (deferred).

---

## 6. Kiến thức xương máu PHẢI giữ khi viết lại

Mỗi dòng dưới đây là một lỗi đã từng xảy ra trong thực tế. Khi port module tương ứng, AI phải đảm bảo hành vi còn nguyên (tốt nhất có test).

### 6.1 Async / file / Windows
- Không nuốt `CancelledError`; Ctrl+C lần 1 lưu tiến độ trong `asyncio.shield`, chờ 3–5s là thoát.
- Rate limiter AI phải trả lại slot nếu bị cancel trong lúc ngủ jitter.
- Atomic write + dọn `.tmp` khi cancel. Mọi `open()` có `encoding="utf-8"`.
- Windows: lọc lỗi transport "I/O operation on closed pipe" khi thoát (`main.py::_silence_transport_errors`).
- Ctrl+C trong lúc dọn dẹp làm thiếu `0000_Index.md` → lần chạy sau tự heal (`main.py::_heal_missing_indexes`).

### 6.2 Các guard của vòng lặp cào (nguồn: `src/core/scraper.py`, `src/core/navigator.py`, `src/pipeline/navigator.py`)
- `MAX_EMPTY_STREAK = 5`: 5 chương rỗng liên tiếp → dừng; reset khi có chương hợp lệ.
- `MAX_CONSECUTIVE_ERRORS = 5`, `MAX_CONSECUTIVE_TIMEOUTS = 3` với backoff `TIMEOUT_BACKOFF_BASE = 30s`; `EMPTY_BACKOFF_SCHEDULE = [60, 120, 300]`; `MAX_CHAPTERS = 5000`.
- **Chặn `slug_increment`** khi URL dạng `/chapter/<id>/<slug>` (RoyalRoad, mỗi chương có ID riêng) → nếu không sẽ lặp vô tận ở chương cuối.
- Gặp nội dung trùng fingerprint (chương bị khóa/lỗi): đánh dấu đã thăm, tìm next **không dùng** slug_increment, không tìm được thì dừng.
- Story-ID guard: next URL phải thuộc cùng truyện (`core/story_meta.py::build_story_id_regex`, `story_id_ok`).
- Trang index guard: URL không giống URL chương + trang có dạng mục lục → dừng, đánh dấu hoàn thành.
- `next_url` đã thăm → dừng. URL đã thăm khi bắt đầu → tìm next thay vì cào lại.
- HTTP 429 → raise (thử lại sau), không coi là hết truyện; 403/captcha/cloudflare → báo `BLOCKED`.
- Chỉ thêm fingerprint / tăng `chapter_count` **sau khi** ghi file thành công.
- Bỏ dòng đầu nội dung nếu trùng tiêu đề (NovelFire). `TITLE_FALLBACK` chỉ báo khi tiêu đề thật sự lấy từ URL slug hoặc là "Unknown Title".
- Truyện đã `completed` vẫn được kiểm tra chương mới khi chạy lại (tốn 1 request/truyện — xem §7.1).

### 6.3 Mạng
- `curl_cffi` impersonate Chrome, xoay vòng phiên bản; có `Referer` cho site chặn truy cập thẳng (site Trung Quốc).
- Per-host semaphore mặc định 3 (áp cho cả HTML và ảnh); site nhạy cảm dùng `--per-host-concurrency 1`.
- Delay ngẫu nhiên theo domain (RoyalRoad 6–14s, Webnovel 3–7s, 69shuba 12–25s, mặc định 1–3s).
- Nhận diện trang thử thách Cloudflare → chuyển domain đó sang Playwright. Playwright giới hạn instance (mặc định 2).

### 6.4 HTML / nội dung
- Bảo vệ tổ tiên của content/title/next selector khỏi bị `remove_selectors` xóa (NAV-PROTECT).
- RoyalRoad gắn class ngẫu nhiên dài 40+ ký tự cho **mọi** `<p>` → bộ lọc class bị làm rối không được xóa `<p>`.
- Density heuristic phải ưu tiên **wrapper** (≥2 con có text) thay vì một `<p>` đơn lẻ, nếu không chỉ ra một đoạn ~300 ký tự.
- AI hay **bịa selector** không tồn tại trong HTML → luôn kiểm selector có thật trong HTML literal; sai thì tự tìm wrapper, không được thì để trống cho heuristic.
- Cleaner có trần an toàn: không bao giờ xóa quá 60% nội dung.
- Formatter phải escape `*` và backtick có sẵn trong văn bản.
- `formatting_rules` phải có đủ khóa mặc định trước khi AI ghi đè (thiếu khóa → formatter crash).

### 6.5 AdsFilter
- Từ khóa hợp lệ: ≥8 ký tự, không phải HTML/URL, không phải tên truyện, không phải cụm điều hướng ("next chapter"), không nằm trong danh sách từ chung chung ("login", "title"…).
- Web: tự thêm khi lặp ≥10 lần, AI xác minh nhóm 3–9 lần. File (EPUB/TXT): chỉ nhánh tự động — **ngưỡng phải scale theo số chương** (§7.3).
- AI không được trả về HTML/markdown làm từ khóa (từng xảy ra: AI trả nội dung `<script>`).

### 6.6 EPUB / TXT
- Tên truyện/tác giả lấy từ Dublin Core metadata; không dùng đường dẫn file local làm tiêu đề chương.
- Gộp trang divider "Part/Level/Book N" vào chương kế tiếp; EPUB không có TOC → tách theo pattern TXT.
- Ảnh EPUB có `href` tương đối (`../images/x.jpg`) → resolver 4 chiến lược + fallback theo basename.
- EPUB đã xử lý → bỏ qua lần sau (manifest SHA256). Cache kế hoạch AI theo SHA256.
- Không chạy validate độ dài cho chương EPUB (chương ngắn hợp lệ vẫn có).
- TXT chỉ UTF-8, báo lỗi rõ ràng kèm cách convert.

### 6.7 AI
- Nhiều key: chỉ nhận `GEMINI_API_KEY` và `GEMINI_API_KEY_<số>` (không nhặt `_DEV`, `_OLD`…). Xoay key khi 429/503; lỗi mạng không làm key bị cooldown.
- Prompt nào cũng phải ràng buộc định dạng output (schema), nếu không AI trả rác.
- Gemini free tier ~10 request/phút → mặc định `max_rpm = 10`.
- Webnovel: AI chọn nhầm chương giữa truyện làm "chương 1" → dùng fast-path ID nhỏ nhất (`utils/url_classifier.py`).

---

## 7. Lỗi đang mở (gộp từ backlog cũ) — xử lý trong rewrite

| # | Lỗi | Xử lý ở |
|---|---|---|
| 7.1 | Mỗi lần chạy đều gửi request kiểm tra lại mọi truyện đã hoàn thành (50 truyện → chậm 20–60s). Hướng: `--check-new`, `--skip-check-after-days 90`, `!recheck`, trường `completed_at` | Phase 8 |
| 7.2 | Lint nhỏ: import thừa `learning/phase.py`, f-string không placeholder `ai/agents.py` | Tự hết khi xóa code cũ (Phase 7) |
| 7.3 | **EPUB lớn (>300 doc):** AI liệt kê từng doc → chạm trần token ở ~doc 830 → 669 doc còn lại dồn vào một file `0830_*.md`. **AdsFilter** tự xóa nhầm câu thoại ngắn ("Hàn Tuyệt nói:", "Cùng lúc đó.") trong bộ 1300–1600 chương vì ngưỡng cố định 10 | Phase 6.2, 6.4 |
| 7.4 | **Webnovel dính UI:** AI học `div.cha-page` (quá rộng) → dính Notes/Vote/Power Ranking cuối chương, khối thông tin sách ở chương 1, số comment dính cuối đoạn. Đúng phải là `div.cha-words`/`div.cha-content` | Phase 2.9 + Phase 4 (V2) |
| 7.5 | **RoyalRoad lọt câu chống trộm** (câu chữ đổi mỗi chương) ẩn bằng CSS trong thẻ `<style>`; code cũ xóa `<style>` trước khi đọc CSS | Phase 2.8 |
| 7.6 | `src/tools/snapshot_baseline.py` hỏng (kiểm `config.py` ở root trong khi file nằm ở `src/`) và cào live nên không tái lập được | Thay bằng Phase 0.3/0.7 |
| 7.7 | `data/txt_cases.json` bị xóa nhầm ở commit `e3d9152` → TXT flow crash `FileNotFoundError` | Phase 0.2 |
| 7.8 | Model mặc định `gemini-2.0-flash` / fallback `gemini-2.0-flash-lite` đã lỗi thời | Phase 3.1 |

---

## 8. Ngoài phạm vi (KHÔNG làm nếu user chưa yêu cầu rõ)
- Truyện tranh (manga/manhua) — dùng `gallery-dl`.
- Tăng cường site gốc Trung/Nhật/Hàn (đoán encoding, giải mã font, pattern `第N章`, slug pinyin).
- Web UI / GUI / FastAPI / Streamlit / database.
- Bộ cào bài viết/blog chung chung.
- Công cụ dịch (arc memory, từ điển nhân vật…).
- Học kiểu case-based cho web (chỉ cân nhắc khi có ≥10 profile ổn định).
- Tùy biến frontmatter (`--no-frontmatter`), chunking cho TranslationWriter, giữ link `<a>` trong bài.

User yêu cầu một mục ở đây → trả lời: *"Mục [X] đang nằm ngoài phạm vi (AGENTS.md §8). Anh muốn (a) làm ngay, (b) ghi vào Phase 8, hay (c) bỏ qua?"*

---

## 9. Mẹo debug nhanh
1. Xem `Vault/_Scraper/issues.md` (mới nhất ở trên).
2. Xem tiến độ trong `progress/` (URL cuối, số chương).
3. Xem profile: `data/site_profiles.json` → `content_selector`, `confidence` (≤0.3 = học thất bại).
4. Chương chỉ ra 1 đoạn ngắn → selector sai/trống → học lại (`!relearn <domain>` trong `links.md`).
5. Nghi AdsFilter xóa nhầm → xem `data/ads_keywords.json` theo domain, xóa từ khóa sai.
6. Bị chặn IP (503/429 liên tục) → `--per-host-concurrency 1`, chờ 24–72h nếu đã bị ban.
7. Tái hiện lỗi: ghi HTML trang lỗi vào `tests/fixtures_local/` bằng `tools/record_fixtures.py`, viết test, rồi mới sửa.

---

## 10. Nhật ký quyết định (append-only, mỗi dòng một quyết định)

| Ngày | Quyết định | Lý do |
|---|---|---|
| 2026-11-09 | Viết lại có chọn lọc thay vì viết lại toàn bộ: giữ & port lõi HTML/EPUB/writers/net; viết lại AI, learning, vòng lặp cào, CLI | Lõi xác định chứa nhiều kinh nghiệm thực tế; phần lỗi thời tập trung ở lớp AI |
| 2026-11-09 | Phase 0 (golden test offline) là điều kiện bắt buộc trước mọi thay đổi hành vi | Trước đây không có test, không chứng minh được viết lại đúng |
| 2026-11-09 | Package mới `src/cao_text/` song song với code cũ đến Phase 7, làm trên nhánh `rewrite-v2` | User vẫn dùng được tool trong lúc viết lại; dễ so sánh cũ/mới |
| 2026-11-09 | Gemini vẫn là provider mặc định, nhưng qua interface `LLMProvider` | Free tier + đã có multi-key; đổi provider sau không phải viết lại |
| 2026-11-09 | Thêm `pydantic>=2`, `pytest`, `pytest-asyncio`, `ruff`; bỏ lệnh cấm test/lint cũ | Cần schema cho structured output và lưới test |
| 2026-11-09 | Gộp toàn bộ tài liệu hướng dẫn AI vào `AGENTS.md`; `CLAUDE.md` chỉ còn trỏ tới file này | Gọn docs, một nguồn sự thật |
| 2026-11-11 | Ghi nhận lỗi đã biết trong golden baseline v1: (1) RoyalRoad lọt watermark ẩn bằng `<style>` (§7.5); (2) Webnovel dính UI (Notes/Vote/Comments) do selector `div.cha-page` (§7.4); (3) AdsFilter xóa nhầm thoại ngắn ("Hàn Tuyệt nói:") ở EPUB lớn >1000 chaps do ngưỡng cố định 10 (§7.3) | Để khi sửa ở Phase 2 (Task 2.8, 2.9) và Phase 6 (Task 6.4), các diff này được phê duyệt là "cải tiến có chủ đích" theo §3.5 |
| 2026-11-15 | Port hoàn chỉnh net layer (`DomainSessionPool`, `PlaywrightPool`, `fetch_page`): per-host semaphore, delay profile, nhận diện CF + Playwright fallback, `fetch_bytes`, raise `RateLimitedError` khi HTTP 429 rỗng | Hoàn thành Task 2.1, đáp ứng §6.2 và §6.3, code sạch và 100% offline testable |
| 2026-11-15 | Port hoàn chỉnh DOM filter (`prepare_soup`): 4 layer lọc, hỗ trợ `:contains()`, bảo vệ tổ tiên NAV-PROTECT, bỏ qua `<p>` cho obfuscated class và lọc phần tử ẩn | Hoàn thành Task 2.2, đáp ứng quy tắc an toàn §6.4 |
| 2026-11-15 | Port hoàn chỉnh `MarkdownFormatter` & cleaner (`clean_extracted_content`, `strip_nav_edges`, `strip_duplicate_title_header`): xử lý ranh giới CommonMark, trần an toàn xóa tối đa 60%, xử lý status callout và tables | Hoàn thành Task 2.3, đáp ứng quy tắc an toàn §6.4 |
| 2026-11-15 | Port hoàn chỉnh `extract/*` và hàm thuần `process_page`: chain content (selector, JSON-LD, density heuristic ưu tiên wrapper, fallback list), title first-wins (selector 0.95 > h1 0.80 > title_tag 0.65 > og 0.65 > url_slug 0.40), gộp navigator (rel_next > selector > anchor > slug_increment > fanfic > dropdown), validate độ dài và văn xuôi | Hoàn thành Task 2.4, đáp ứng §4.3 và §6.2 |
| 2026-11-15 | Tạo `tests/test_golden_web.py` và căn chỉnh trích xuất: tinh chỉnh dropdown navigation chỉ kích hoạt khi profile chỉ định (tránh nhặt nhầm select comment/theme), áp dụng `_TITLE_TAG_SEP_RE` trước khi strip site suffix cho `<title>`/`og:title`; `process_page` mới khớp 100% với golden baseline v1 trên toàn bộ fixtures web | Hoàn thành Task 2.5, toàn bộ web fixtures vượt qua so sánh với v1 |
| 2026-11-15 | Port hoàn chỉnh `writers/*` (`ObsidianWriter`, `TranslationWriter`, `RawWriter`, `build_writer`) và `nav_injector`: định dạng tên file `0042_Title.md`, `slugify_filename` an toàn Windows, YAML frontmatter, paragraph indent em-space, strip markdown/placeholder cho translate/raw, tạo `0000_Index.md` và chèn 3-line nav footer | Hoàn thành Task 2.6 |
| 2026-11-15 | Port hoàn chỉnh `images/*` (`WebImageFetcher`, `EpubImageExtractor`, `apply_image_stage`): hợp nhất `apply_image_stage` dùng chung cho cả Web và EPUB, hỗ trợ 3 output mode (obsidian/translate/raw), giữ link gốc khi tải lỗi, 4 chiến lược giải quyết href cho EPUB kèm fallback basename | Hoàn thành Task 2.7 |
| 2026-11-16 | Fix §7.5: Quét CSS rules trong thẻ `<style>` tìm selector class/id có `display:none/visibility:hidden/opacity:0/font-size:0/speak:never` để loại bỏ phần tử ẩn trước khi xóa thẻ `<style>`; kiểm thử thành công trên `fixtures/html/` và làm sạch 100% watermark chống trộm trên RoyalRoad; cập nhật golden baseline RoyalRoad theo quy trình §3.5 | Hoàn thành Task 2.8 |
| 2026-11-16 | Fix một phần §7.4: Bổ sung selector UI Webnovel (`.cha-hd`, `.cha-foot`, `.cha-page-ft`, `.cha-info`, `.cha-bts`, `.j_bottom_comment_area`, `.j_power_rank_wrap`, `.para-comment`, `anno > sup`...) vào `KNOWN_NOISE_SELECTORS`; loại bỏ khối bìa sách ở ch1, footer vote/power stone và số đếm comment; cập nhật golden baseline Webnovel theo quy trình §3.5 | Hoàn thành Task 2.9, đạt DoD và hoàn tất toàn bộ Phase 2 |
| 2026-11-16 | Tra cứu tài liệu chính thức https://ai.google.dev/gemini-api/docs/models và cấu hình model AI cho Phase 3 (§3.1): chọn `gemini-3.8-flash` làm model chính (Flash ổn định mới nhất, tối ưu agentic & coding workflow) và `gemini-2.5-flash` làm model fallback. Loại bỏ biến thể lite (`gemini-2.0-flash-lite`) vì thiếu ổn định cho structured output. Khai báo tập trung duy nhất ở `settings.py` và `config.toml` | Hoàn thành Task 3.1, xử lý dứt điểm mục §7.8 |
