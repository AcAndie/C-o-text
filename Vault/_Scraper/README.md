# 📖 Cào Text — Hướng Dẫn Sử Dụng

Tool tự động tải truyện từ web (Royal Road, fanfiction.net, ScribbleHub, NovelFire, 69shuba...) hoặc bóc file `.epub` thành chương Markdown đọc được trong **Obsidian**.

> Bạn đang đứng trong **Vault** — nơi đọc truyện. Code thật + API key ở thư mục cha (`Cào text/`).

---

## 🚀 Lần Đầu Setup (làm 1 lần)

### Bước 1 — Cài Python

1. Tải Python 3.11+ từ https://www.python.org/downloads/
2. Lúc cài tick "**Add Python to PATH**"
3. Mở terminal mới, gõ `py --version` → ra `Python 3.11.x` là OK

### Bước 2 — Cài thư viện

Mở terminal (Windows Terminal hoặc PowerShell), gõ:

```bash
cd "C:\Users\FPT MONG CAI\Desktop\Small Project\Cào text"
py -m pip install -r requirements.txt
py -m playwright install chromium
```

Chờ vài phút. Lần đầu Playwright tải Chromium ~150MB.

### Bước 3 — Thêm API key Gemini

1. Lấy key miễn phí: https://aistudio.google.com/apikey
2. Mở file `Cào text/.env` bằng Notepad (nếu chưa có → tạo mới)
3. Thêm dòng:
   ```
   GEMINI_API_KEY=AIzaSy...your_key_here
   ```
4. Lưu, đóng

### Bước 4 — Mở Vault trong Obsidian

1. Tải Obsidian: https://obsidian.md
2. Mở Obsidian → "**Open folder as vault**"
3. Chọn thư mục `C:\Users\FPT MONG CAI\Desktop\Small Project\Cào text\Vault\`
4. Done — bạn đang ở Vault này

---

## 📥 Cào Truyện Từ Web

### Bước 1 — Thêm URL vào `links.md`

Mở file `_Scraper/links.md` ngay trong Obsidian (sidebar bên trái). Format:

```
# Truyện đang cào (1 URL/dòng, bắt đầu bằng https://)
https://www.royalroad.com/fiction/55418/rock-falls-everyone-dies
https://www.scribblehub.com/series/1539267/the-quantum-wanderer/

# Bỏ qua dòng có dấu # đầu
# https://...

# Bắt AI học lại 1 site (xóa cache cũ)
!relearn royalroad.com
```

**Tips:**
- Paste link trang giới thiệu (index) hoặc chương 1 — tool tự nhận
- Comment bằng `#` ở đầu dòng
- `!relearn <domain>` để bắt học lại nếu site đổi cấu trúc

### Bước 2 — Chạy

Mở terminal, gõ:

```bash
cd "C:\Users\FPT MONG CAI\Desktop\Small Project\Cào text"
py main.py
```

Truyện sẽ tự cào vào `Vault/Novels/{tên_truyện}/`. Mỗi chương 1 file `.md`. Mở trong Obsidian xem ngay.

**Lần đầu cào site mới** mất ~3 phút để AI học cấu trúc. Lần sau cào lập tức.

**Dừng giữa chừng:** `Ctrl+C` trong terminal. Lần chạy sau tự resume từ chương đang dở.

---

## 📚 Bóc EPUB

1. Kéo file `.epub` vào thư mục `_Scraper/epub_inbox/` (ngay trong Obsidian sidebar)
2. Chạy `py main.py` (cùng lệnh)
3. Tool tự bóc EPUB → ghi vào `Vault/Novels/{tên_sách}/`

File đã bóc xong → skip lần sau (nhận diện qua hash, không bóc lại).

---

## 🎛️ Chạy Từ Obsidian (Không Cần Terminal)

Setup 1 lần để có hotkey `Ctrl+Shift+S` chạy scrape ngay trong Obsidian:

1. Obsidian → Settings → **Community plugins** → "Turn on community plugins"
2. **Browse** → search "**Shell commands**" → Install + Enable
3. Settings → **Shell commands** → "**New shell command**":
   - **Shell command:**
     ```
     py "C:\Users\FPT MONG CAI\Desktop\Small Project\Cào text\main.py"
     ```
   - **Alias:** `Cào Text Run`
   - **Output channels** → stdout: `Notification`, stderr: `Notification`
4. Settings → **Hotkeys** → search "shell commands: cào text" → bind `Ctrl+Shift+S`

Giờ bấm `Ctrl+Shift+S` trong Obsidian → scrape chạy nền, popup khi xong.

**Lưu ý:** Output dài bị truncate trong popup. Muốn xem log đầy đủ thì mở terminal.

---

## 📁 Layout Vault

```
Vault/                              ← bạn đang ở đây
├── Novels/                         ← truyện đã cào (1 folder/truyện)
│   ├── Rock_falls,_everyone_dies/
│   │   ├── 0001_Prologue.md
│   │   ├── 0002_Chapter_1.md
│   │   └── _Index.md               ← mục lục tự sinh
│   └── ...
└── _Scraper/
    ├── links.md                    ← danh sách URL cào
    ├── issues.md                   ← log lỗi/cảnh báo per session
    ├── epub_inbox/                 ← bỏ file .epub vào đây
    └── README.md                   ← file này
```

---

## ⚙️ Tinh Chỉnh (Optional)

Mở `Cào text/config.toml` để chỉnh:

| Setting | Default | Ghi chú |
|---|---|---|
| `[output] mode` | `obsidian` | Đổi `translate` (plain text dịch) hoặc `raw` |
| `[scraper] playwright_concurrency` | `2` | Giảm xuống `1` nếu RAM yếu (<8GB) |
| `[ai] max_rpm` | `10` | Gemini free tier ~10 req/min, đừng tăng |
| `[scraper] max_chapters` | `5000` | Safety cap, tránh infinite loop |

---

## 🆘 Gặp Lỗi?

**1. `[ERR] Không tìm thấy GEMINI_API_KEY trong .env`**
→ Quay lại Bước 3 setup, thêm key vào `Cào text/.env`

**2. `playwright install failed` / browser không tải được**
→ Chạy lại `py -m playwright install chromium` với mạng ổn định

**3. Truyện cào chỉ ra vài chương rồi dừng**
→ Mở `_Scraper/issues.md` xem log. Thường site đổi cấu trúc → thêm `!relearn <domain>` vào `links.md` rồi chạy lại

**4. 69shuba / site Trung báo 403 hoài**
→ IP bị rate-limit. Đợi vài giờ hoặc dùng VPN

**5. Obsidian không thấy file mới**
→ Settings → Files & Links → "Detect all file extensions" = ON

---

## 📌 Cheat Sheet 1 Phút

```bash
# Cào web
1. Sửa Vault/_Scraper/links.md (thêm URL)
2. cd "C:\Users\FPT MONG CAI\Desktop\Small Project\Cào text"
3. py main.py

# Bóc EPUB
1. Kéo .epub vào Vault/_Scraper/epub_inbox/
2. py main.py

# Đọc
Mở Obsidian → vault này → Novels/ → click truyện
```
