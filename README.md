# Cào Text — Universal Novel Content Normalizer

> **Một công cụ chuẩn hóa nội dung tiểu thuyết cá nhân, đa dụng, đa ngôn ngữ** — ném input nào vào (URL truyện web / file `.epub` / file `.txt`) cũng ra được một bộ chapter sạch, không noise, đọc được trên Obsidian hoặc đem đi dịch.
>
> Site mới chỉ cần học **1 lần** (1–3 AI calls kèm kiểm chứng bằng code), lần sau xài lại profile đã lưu — hoàn toàn miễn phí khi không cần re-learn.

**Version**: v2.0.0 (2026-11-18) — [CHANGELOG](docs/CHANGELOG.md)
**License**: Personal use
**Platform**: Windows 10/11 (tested), Linux/macOS (supported)
**Runtime**: Python 3.11+

---

## Quick Start

```bash
# 1. Cài đặt package ở chế độ editable (kèm dev tools) + Chromium cho Playwright
python -m pip install -e .[dev]
python -m playwright install chromium

# 2. Tạo .env với Gemini API key (free tier OK, multi-key OK)
echo GEMINI_API_KEY=your_key_here > .env
# Hoặc nhiều key: GEMINI_API_KEY_1=..., GEMINI_API_KEY_2=...

# 3. Scrape web novel — bỏ URL vào Vault/_Scraper/links.md (hoặc truyền file links riêng)
python main.py
# Hoặc:
python main.py path/to/links.txt

# 4. Hoặc convert EPUB (file đơn lẻ hoặc bỏ vào Vault/_Scraper/epub_inbox/)
python main.py path/to/novel.epub

# 5. Hoặc parse TXT
python main.py path/to/novel.txt
```

Output → `Vault/Novels/{story_slug}/0001_Chapter_Title.md`, `0002_*.md`, `0000_Index.md`...

---

## Features

### 3 Input Sources

| Input | Module | Note |
|-------|--------|------|
| **Web URL** | `cao_text/web/` | Học cấu trúc site 1 lần qua 1–3 AI calls + kiểm chứng tự động (V1–V6), sau đó cào hoàn toàn bằng code. Hỗ trợ resume mượt mà sau Ctrl+C. |
| **EPUB file** | `cao_text/files/epub.py` & `epub_plan.py` | Phân tích cấu trúc bằng rule (TOC + gộp trang divider Part/Book) hoặc AI sinh quy tắc regex (xử lý mượt EPUB lớn >1.500 chương), trích xuất ảnh nhúng. |
| **TXT file** | `cao_text/files/txt.py` | Tách chương theo DB regex (`txt_cases.json`: VN "Chương N", EN "Chapter N"...). AI fallback tự sinh regex và kiểm chứng trên 3 đoạn giữa file trước khi lưu. |

### 3 Output Modes (chọn qua `--output-mode`)

| Mode | Filename | Format | Image |
|------|----------|--------|-------|
| `obsidian` (default) | `0042_Chapter_Title.md` | Markdown + YAML frontmatter + `0000_Index.md` + thanh điều hướng | Download local → `images/ch_0042_0.jpg` |
| `translate` | `0042.txt` | Plain text, tiêu đề dòng 1, mỗi đoạn một dòng | `[IMAGE: alt]` placeholder, không download |
| `raw` | `0042.txt` | Text thuần túy, không định dạng | Xóa hoàn toàn |

```bash
python main.py --output-mode translate links.txt    # cho batch translate
python main.py --output-mode raw novel.epub         # lưu trữ text thô
python main.py --output-mode obsidian novel.txt     # đọc trong Obsidian vault
```

### Site Learning v2 (Web mode)

Lần đầu gặp domain mới → chỉ tốn **1–3 AI calls** kèm kiểm chứng tự động bằng code:
1. **Fetch mẫu**: Tải các chương đầu tiên của truyện.
2. **Heuristic Candidates** (`learn/candidates.py`): Tìm ứng viên `content_selector`, `title_selector`, `next_selector` bằng code thuần; phạt nặng các wrapper bao cả giao diện/comment.
3. **DOM Skeleton + AI Analyze** (`ai/skeleton.py`, `learn/learner.py`): Nén HTML thành bộ khung DOM gọn nhẹ gửi cho Gemini trả về Pydantic schema `SiteAnalysisOutput`.
4. **Code Verification V1–V6** (`learn/verify.py`): Kiểm chứng selector trên dữ liệu thật (độ dài văn xuôi, tỷ lệ nhiễu UI, tiêu đề không trùng nhau, chuỗi `next_url` liên tục, an toàn của `remove_selectors` và `ads_keywords`).
5. **Auto-Repair**: Nếu trượt quy tắc nào, gửi báo cáo lỗi cụ thể cho AI sửa tối đa 2 vòng trước khi lưu `SiteProfile` (v3) vào `data/site_profiles.json`.

Lần sau gặp cùng domain → dùng ngay profile đã lưu, không tốn AI call.

```bash
# Force re-learn nếu site đổi cấu trúc
echo "!relearn fanfiction.net" >> Vault/_Scraper/links.md
python main.py

# Bulk delete profile cũ (mặc định dry-run, thêm --apply để xóa thật)
python main.py --bulk-relearn --pattern ".*\.com" --apply
```

### Defense in Depth — Content Cleaning

- **Layer 1 (HTML Filter)**: Luôn xóa `script/style/iframe`, nhưng **quét CSS trong `<style>` trước khi xóa** để tìm và diệt mọi phần tử ẩn (`display:none`, `visibility:hidden`, `opacity:0`, `font-size:0`, `speak:never` — loại bỏ 100% watermark chống trộm của RoyalRoad).
- **Layer 2 (`KNOWN_NOISE_SELECTORS`)**: Bộ lọc sẵn cho các site phổ biến (Webnovel `.cha-hd`, `.cha-foot`, `.para-comment`, FFN profile box, RR comments/warnings...).
- **Layer 3 (Profile `remove_selectors` + NAV-PROTECT)**: Xóa phần tử rác theo domain nhưng luôn bảo vệ tổ tiên của content/title/next selector.
- **Post-extract Cleaner**: Làm sạch cạnh điều hướng (`strip_nav_edges`), xóa tiêu đề lặp dòng đầu, có trần an toàn không bao giờ xóa quá 60% nội dung.
- **AdsFilter 2-Pass & Dynamic Threshold**: Quét cạnh nghi vấn xuyên chương; ngưỡng tự động scale theo quy mô truyện `max(10, ceil(0.03 * số chương))` kèm chốt chặn bảo vệ câu thoại ngắn / chuyển cảnh; AI xác minh nhóm xuất hiện 3–9 lần.

### Resume + Multi-key Support

- **Progress Store v2**: Lưu trạng thái gọn nhẹ tại `progress/<story_key>/state.json` và lịch sử chương append-only tại `progress/<story_key>/seen.jsonl` (tự động chuyển đổi từ file progress `.json` của v1).
- **Ctrl+C an toàn**: Bấm Ctrl+C 1 lần → lưu tiến độ trong `asyncio.shield`, đóng kết nối sạch sẽ trong vài giây. Lần chạy sau tự động sửa `0000_Index.md` nếu phiên trước bị ngắt giữa chừng.
- **Multi-key Gemini**: Khai báo `GEMINI_API_KEY`, `GEMINI_API_KEY_1`, `GEMINI_API_KEY_2`... trong `.env` (tự động xoay vòng round-robin + cooldown 60s khi gặp 429/503, tự chuyển sang `fallback_model` khi cần).

---

## CLI Reference

```bash
python main.py [OPTIONS] [INPUT]
# Hoặc:
python -m cao_text [OPTIONS] [INPUT]
```

| Flag | Default | Description |
|------|---------|-------------|
| `INPUT` | `links_file` trong config | Đường dẫn file `links.md`/`.txt` HOẶC file `.epub` / `.txt` đơn lẻ |
| `--output-mode {obsidian,translate,raw}` | `obsidian` | Chế độ định dạng đầu ra |
| `--output-dir DIR` | theo `config.toml` | Thư mục gốc lưu truyện |
| `--max-pw-instances N` | `2` | Số instance Playwright chạy đồng thời tối đa |
| `--per-host-concurrency N` | `3` | Giới hạn số request đồng thời trên mỗi domain |
| `--fast-learning` | off | Bỏ qua bước kiểm tra ProseRichness khi học site để tăng tốc |
| `--no-validation` | off | Bỏ qua bộ lọc kiểm chứng ProseRichness |
| `--bulk-relearn` | off | Xóa hàng loạt profile để học lại (mặc định dry-run) |
| `--pattern REGEX` | match all | Biểu thức chính quy lọc domain cho `--bulk-relearn`, hoặc pattern tách chương TXT |
| `--apply` | off | Xác nhận thực thi xóa thật khi dùng `--bulk-relearn` |

---

## Architecture (v2)

```
links.md / file ──► cli.py ──┬─► web/start.py ─► learn/learner.py (nếu chưa có profile) ─► web/session.py
                             │        mỗi chương: net/http fetch ─► extract/page.process_page (hàm thuần)
                             │                    ─► html/ads ─► images/stage ─► writers ─► ProgressStore
                             └─► files/flow.py (epub|txt) ─► extract/page.process_page ─► images/stage ─► writers
```

Chi tiết kiến trúc và quy tắc thiết kế: xem [AGENTS.md](AGENTS.md) §4 & §6.

---

## Troubleshooting

Mẹo debug chi tiết: xem [AGENTS.md](AGENTS.md) §9.

Quick triage:
- **Thiếu `GEMINI_API_KEY`** → Tạo `.env` với `GEMINI_API_KEY=...` (chỉ bắt buộc khi học site mới hoặc cần AI fallback).
- **HTTP 429 rate limit** → Hệ thống tự động retry/backoff và xoay API key.
- **Truyện dừng sớm / chỉ ra 1 đoạn ngắn** → Site có thể mới đổi giao diện → thêm `!relearn <domain>` vào `links.md`.
- **Cloudflare challenge** → Đảm bảo đã cài Chromium: `python -m playwright install chromium`.
- **HTTP 503 / IP rate-limit** → Chạy với `--per-host-concurrency 1`.
- **Lỗi bảng mã file TXT** → File TXT bắt buộc mã hóa UTF-8 (mở bằng Notepad → Save As → chọn Encoding: UTF-8).

---

## Project Documents

| File | Role |
|------|------|
| [README.md](README.md) | Tài liệu tổng quan & hướng dẫn nhanh |
| [AGENTS.md](AGENTS.md) | **Hướng dẫn duy nhất cho AI**: quy tắc, kiến trúc v2, lịch sử quyết định |
| [Vault/_Scraper/README.md](Vault/_Scraper/README.md) | Hướng dẫn sử dụng hằng ngày trong Obsidian |
| [docs/CHANGELOG.md](docs/CHANGELOG.md) | Lịch sử phiên bản |

---

## Runtime Files (gitignored)

```
data/site_profiles.json             # Profile cấu trúc site (v3)
data/ads_keywords.json              # Từ khóa quảng cáo/watermark theo domain
data/processed_epubs.json           # Manifest SHA256 các file EPUB đã bóc trong inbox
data/epub_analyses.json             # Cache kế hoạch chương EPUB (v2)
progress/<story_key>/state.json     # Trạng thái tiến độ truyện
progress/<story_key>/seen.jsonl     # Lịch sử URL & fingerprint chương (append-only)
Vault/Novels/<story_slug>/          # Các chương truyện đầu ra
Vault/_Scraper/issues.md            # Log cảnh báo/lỗi theo từng phiên chạy
.env                                # Gemini API keys (KHÔNG BAO GIỜ commit)
```
