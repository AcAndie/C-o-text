# Cào Text

Công cụ cào nội dung truyện từ các trang web novel (RoyalRoad, ScribbleHub, Wattpad, v.v.)
và lưu từng chương thành file `.md`. Hỗ trợ resume, lọc watermark bằng AI, và chống
Cloudflare tự động.

---

## Mục lục

- [Yêu cầu](#yêu-cầu)
- [Cài đặt](#cài-đặt)
- [Cấu hình](#cấu-hình)
- [Cách dùng](#cách-dùng)
- [Cấu trúc dự án](#cấu-trúc-dự-án)
- [Pipeline hoạt động](#pipeline-hoạt-động)
- [Các tính năng chính](#các-tính-năng-chính)
- [Bugs đã sửa](#bugs-đã-sửa)
- [Lưu ý & giới hạn](#lưu-ý--giới-hạn)

---

## Yêu cầu

- Python 3.11+
- Gemini API key (free tier đủ dùng — 15 RPM, config mặc định dùng 3 RPM)

---

## Cài đặt

```bash
# 1. Clone hoặc giải nén project
cd "Cào Text"

# 2. Tạo virtual environment (khuyến nghị)
python -m venv .venv
source .venv/bin/activate   # Linux/macOS
.venv\Scripts\activate      # Windows

# 3. Cài dependencies
pip install curl_cffi beautifulsoup4 google-genai python-dotenv

# 4. (Tuỳ chọn) Cài Playwright để bypass Cloudflare
pip install playwright playwright-stealth
playwright install chromium

# 5. Tạo file .env ở thư mục cha (cùng cấp với folder "Cào Text")
echo "GEMINI_API_KEY=your_api_key_here" > ../.env
# Hoặc đặt thêm model (mặc định: gemini-2.0-flash):
echo "GEMINI_MODEL=gemini-2.0-flash" >> ../.env
```

---

## Cấu hình

### `.env`

```env
GEMINI_API_KEY=your_api_key_here
GEMINI_MODEL=gemini-2.0-flash        # tuỳ chọn
```

### `links.txt`

Mỗi dòng một URL — có thể là trang chương hoặc trang mục lục (index):

```
# Dòng bắt đầu bằng # bị bỏ qua
https://www.royalroad.com/fiction/55418/the-wandering-inn
https://www.scribblehub.com/series/123456/my-novel/
https://www.royalroad.com/fiction/99999/chapter-1
```

### `config.py` — các tham số quan trọng

| Tham số | Mặc định | Ý nghĩa |
|---|---|---|
| `MAX_CHAPTERS` | 1000 | Giới hạn số chương mỗi truyện |
| `AI_MAX_RPM` | 3 | Số lần gọi Gemini tối đa / phút |
| `STORY_ID_LEARN_AFTER` | 12 | Sau bao nhiêu chương thì AI học story ID |
| `DELAY_PROFILES` | xem file | Delay giữa chương theo domain |

---

## Cách dùng

```bash
# Chạy với links.txt mặc định
python main.py

# Hoặc chỉ định file links khác
python main.py my_links.txt
```

Output được lưu trong `output/<domain>_<slug>/`:
```
output/
  royalroad_com_fiction_55418/
    0001_Chapter One - The Beginning.md
    0002_Chapter Two - Into the Dark.md
    ...
```

File progress được lưu ở thư mục gốc:
```
progress_www_royalroad_com_royalroad_com_fiction_55418_<hash>.json
```

**Resume tự động:** Nếu chương trình bị ngắt, chạy lại cùng lệnh — sẽ tiếp tục
từ chương chưa xong, không cào lại từ đầu.

---

## Cấu trúc dự án

```
Cào Text/
├── main.py                  # Entry point, AppState, task scheduler
├── config.py                # Hằng số, regex compile, delay profiles
├── links.txt                # Danh sách URL cần cào
├── ADs_keyword.json         # DB keyword/regex lọc watermark (tự cập nhật)
├── .env                     # (không commit) API key
│
├── core/
│   ├── scraper.py           # Logic cào chính: fetch → parse → lưu → next
│   ├── extractors.py        # TitleExtractor: 8 nguồn + majority vote
│   └── session_pool.py      # DomainSessionPool (curl_cffi) + PlaywrightPool
│
├── ai/
│   ├── client.py            # Gemini client + AIRateLimiter (token bucket)
│   └── agents.py            # Tất cả hàm gọi Gemini API
│
└── utils/
    ├── ads_filter.py        # AdsFilter: lọc watermark, học pattern qua AI
    ├── file_io.py           # Atomic I/O cho progress JSON và file .md
    └── string_helpers.py    # Fingerprint, clean text, CF detection
```

---

## Pipeline hoạt động

```
links.txt
    │
    ▼
[Startup] Khởi tạo AIRateLimiter, DomainSessionPool, PlaywrightPool, AdsFilter
    │
    ▼ (mỗi URL, chạy song song với asyncio.gather)
[Tìm chương bắt đầu]
    ├─ Resume từ progress JSON nếu có
    └─ Nếu không: fetch trang → detect_page_type → AI tìm ch.1 nếu là index
    │
    ▼ ──────────────────── vòng lặp per-chapter ────────────────────────
[Domain delay]  (2–45s ngẫu nhiên theo DELAY_PROFILES)
    │
    ▼
[Fetch HTML]
    ├─ curl_cffi (Chrome TLS fingerprint)
    └─ Playwright headless nếu gặp Cloudflare challenge
    │
    ▼
[Xây profile domain nếu mới]  ← AI: ask_ai_build_profile  (FIX #3)
    │
    ▼
[Remove hidden elements]  (strip CSS watermark, aria-hidden)
    │
    ▼
[Trích xuất nội dung]
    ├─ CSS selectors (9 selector ưu tiên)
    └─ AI fallback: ai_classify_and_find
    │
    ▼
[Lọc ads] ← AdsKeywordDB.is_match (keyword + regex)
    │
    ▼
[Fingerprint check]  MD5 → set lookup O(1)  (FIX #5)
    │
    ▼
[Trích tiêu đề]  8 nguồn → majority vote → AI nếu hòa
    │
    ▼
[Lưu file .md]  atomic write
    │
    ▼
[AdsFilter học pattern mới]  mỗi 10 chương → AI scan
    │
    ▼
[Story ID guard]  AI học regex sau 12 chương
    │
    ▼
[Tìm URL tiếp theo]  ← clean_html (FIX #2)
    ├─ CSS selector profile
    ├─ rel=next
    ├─ slug +1
    └─ AI fallback
    │
    ▼
[Xác nhận cùng truyện]  ← AI: ask_ai_confirm_same_story  (FIX #4)
    │
    ▼
[Lưu next_url vào progress]  (FIX #1)  ← QUAN TRỌNG: lưu URL tiếp theo, không phải URL vừa xong
    │
    └─ lặp lại ────────────────────────────────────────────────────────
    │
    ▼
[Flush AdsFilter + đóng pool + in tổng kết]
```

---

## Các tính năng chính

### Chống Cloudflare tự động
Mặc định dùng `curl_cffi` với TLS fingerprint Chrome. Khi gặp CF challenge,
tự động fallback sang Playwright headless và chờ tối đa 20 giây để CF tự giải.
Playwright được giữ sống suốt phiên (không launch lại mỗi lần) — chỉ mở page
mới (~50ms) thay vì cả browser (~2s).

### Resume an toàn
Progress được lưu dưới dạng JSON với atomic write (`.tmp` + `os.replace()`).
Tên file progress bao gồm hash URL 8 ký tự để tránh collision giữa các URL
cùng domain (VD: trang index và trang chapter đầu của cùng truyện).

### AI-powered (Gemini)
Tất cả AI call đều có rate limiting (token bucket) và jitter để không vượt
quota free tier. Các tình huống AI được gọi:

| Tình huống | Hàm AI |
|---|---|
| Domain mới, chưa có CSS profile | `ask_ai_build_profile` |
| Trang index, tìm chương đầu | `ai_find_first_chapter_url` |
| Không tìm được next URL | `ai_classify_and_find` |
| Nội dung rỗng | `ai_classify_and_find` |
| Vote tiêu đề hòa nhau | `ai_validate_title` |
| Học story ID (sau 12 chương) | `ask_ai_for_story_id` |
| Xác nhận next URL cùng truyện | `ask_ai_confirm_same_story` |
| Scan watermark mới (mỗi 10 ch) | `ai_detect_ads_content` |

### Lọc watermark / ads
`AdsKeywordDB` chứa keyword và regex phát hiện watermark nhúng bởi aggregator
site (VD: "stolen content", "read at royalroad"). Danh sách seed được nạp khi
khởi động; AI tự học pattern mới từ nội dung thực tế mỗi 10 chương.

---

## Bugs đã sửa

| # | File | Mô tả | Mức độ |
|---|---|---|---|
| **#1** | `core/scraper.py` | `progress["current_url"]` lưu `url` thay vì `next_url` → resume bị thoát ngay | 🔴 Critical |
| **#2** | `core/scraper.py` | `find_next_url_heuristic` nhận `html` thô thay vì `clean_html` → có thể chọn nhầm hidden link | 🟠 High |
| **#3** | `core/scraper.py` | `ask_ai_build_profile` + `save_new_profile` định nghĩa nhưng không gọi → domain lạ không học được selector | 🟠 High |
| **#4** | `core/scraper.py` | `ask_ai_confirm_same_story` định nghĩa nhưng không gọi → không phát hiện khi nhảy sang truyện khác | 🟠 High |
| **#5** | `core/scraper.py` | `fingerprints` dùng `list` + cắt 50 → O(n) lookup, bỏ sót loop sau ch.50 | 🟢 Medium |
| **#6** | `main.py` | `_make_progress_path` collision khi URL index và URL chapter cùng truyện | 🟢 Medium |
| **#7** | `main.py` | `AI_MAX_RPM` import từ `ai.client` thay vì `config` (nguồn gốc) | ⚪ Low |

---

## Lưu ý & giới hạn

- **Chỉ dùng cho mục đích cá nhân.** Luôn kiểm tra ToS của trang web trước khi cào.
- **RoyalRoad** và một số site có rate limit nghiêm → delay mặc định 15–45s.
  Giảm delay có thể bị IP ban.
- **Playwright** cần cài riêng (`playwright install chromium`) và chỉ khởi động
  khi thực sự gặp Cloudflare — không tốn tài nguyên nếu không cần.
- **Gemini free tier** cho phép 15 RPM. Config mặc định dùng 3 RPM để an toàn
  khi chạy nhiều truyện song song. Tăng `AI_MAX_RPM` nếu dùng paid tier.
- File `ADs_keyword.json` tự cập nhật theo thời gian — có thể commit để chia sẻ
  với người dùng khác.
