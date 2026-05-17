# Cào Text — Universal Novel Content Normalizer

> **Một công cụ chuẩn hóa nội dung tiểu thuyết cá nhân, đa dụng, đa ngôn ngữ** — ném input nào vào (URL truyện web / file `.epub` / file `.txt`) cũng ra được một bộ chapter sạch, không noise, đọc được trên Obsidian hoặc đem đi dịch.
>
> Site mới chỉ cần học **1 lần** (~8 AI calls), lần sau xài lại profile đã lưu — free khi không cần re-learn.

**Version**: v1.0 (2026-05-17) — [CHANGELOG](CHANGELOG.md)
**License**: Personal use
**Platform**: Windows 10/11 (tested), Linux/macOS (should work)
**Runtime**: Python 3.11+

---

## Quick Start

```bash
# 1. Cài dependencies
python -m pip install -r requirements.txt

# 2. Tạo .env với Gemini API key (free tier OK)
echo GEMINI_API_KEY=your_key_here > .env

# 3. (Optional) Cài Playwright cho site JS-heavy / Cloudflare
python -m pip install playwright playwright-stealth
python -m playwright install chromium

# 4. Scrape web novel — bỏ URL chapter 1 vào links.txt
echo https://www.royalroad.com/fiction/12345/my-novel/chapter/1 > links.txt
python main.py links.txt

# 5. Hoặc convert EPUB
python main.py path/to/novel.epub

# 6. Hoặc parse TXT
python main.py path/to/novel.txt
```

Output → `output/{story_slug}/0001_Chapter_Title.md`, `0002_*.md`, ...

---

## Features

### 3 Input Sources

| Input | Adapter | Note |
|-------|---------|------|
| **Web URL** | `core/scraper.py` (default) | Learn site cấu trúc 1 lần qua 8 AI calls, sau đó scrape free. Hỗ trợ resume sau Ctrl+C. |
| **EPUB file** | `ingest/epub.py` | Parse spine qua `ebooklib`, naming từ Dublin Core metadata, extract embedded image. |
| **TXT file** | `ingest/txt.py` | Regex case-based chapter boundary detection (VN "Chương N" / EN "Chapter N"). AI fallback nếu pattern lạ. |

### 3 Output Modes (chọn qua `--output-mode`)

| Mode | Filename | Format | Image |
|------|----------|--------|-------|
| `obsidian` (default) | `0042_Chapter_Title.md` | Markdown + YAML frontmatter | Download local → `images/ch_0042_0.jpg` |
| `translate` | `0042.txt` | Plain text, một paragraph một dòng | `[IMAGE: alt]` placeholder, không download |
| `raw` | `0042.txt` | Text only, no formatting | Strip entirely |

```bash
python main.py --output-mode translate links.txt    # cho batch translate
python main.py --output-mode raw novel.epub         # archive
python main.py --output-mode obsidian novel.txt     # đọc trong vault
```

### Site Learning (Web mode)

Lần đầu gặp domain mới → 8 AI calls + Naming Phase tự động:
- AI#1–AI#3: Discover DOM structure (content/title/next selectors)
- AI#4–AI#5: Conflict resolution + title deep-dive
- AI#6–AI#7: Special content + ads/watermark scan
- AI#image: Inline image policy detection
- AI#8: Master synthesis → persist `data/site_profiles.json`
- Naming: Story name + chapter pattern detection

Lần sau cùng domain → load profile, scrape ngay, không AI.

```bash
# Force re-learn nếu site đổi cấu trúc
echo "!relearn fanfiction.net" >> links.txt
python main.py links.txt

# Bulk delete profile cũ
python main.py --bulk-relearn --pattern ".*\.com" --apply
```

### Defense in Depth — Content Cleaning

- **Layer 1**: Always strip `script/style/iframe`
- **Layer 2**: `KNOWN_NOISE_SELECTORS` (FFN profile box, RR comments, ...)
- **Layer 3**: Per-domain `remove_selectors` (learned)
- **Post-extract 5-pass cleaner**: comment section, settings panel, postfix, metadata header, UI nav — với 60% safety cap
- **AdsFilter**: Cross-chapter frequency tracking (auto-add ≥10 occurrences, AI verify 3–9)

### Resume + Multi-key Support

- Ctrl+C giữa chừng → progress saved trong `progress/{domain}_{slug}_{hash}.json`
- Chạy lại cùng URL → tiếp tục đúng chapter cuối, không scrape lại
- Multi-key Gemini: Set `GEMINI_API_KEY_1`, `GEMINI_API_KEY_2`, ... trong `.env` (round-robin nếu key chính fail)

---

## CLI Reference

```bash
python main.py [OPTIONS] INPUT
```

| Flag | Default | Description |
|------|---------|-------------|
| `INPUT` | `links.txt` | URL list `.txt` HOẶC file `.epub` / `.txt` đơn |
| `--output-mode {obsidian,translate,raw}` | `obsidian` | Output format |
| `--output-dir DIR` | `output/` | Base directory |
| `--max-pw-instances N` | `2` | Số Playwright concurrent (CF sites) |
| `--fast-learning` | off | Skip ProseRichness validation trong learning (~20% faster) |
| `--no-validation` | off | Bỏ qua ProseRichnessBlock toàn bộ (ít filter, nhanh nhẹ) |
| `--bulk-relearn` | off | Bulk delete profile (mặc định dry-run) |
| `--pattern REGEX` | match all | Regex filter cho `--bulk-relearn` |
| `--apply` | off | Confirm `--bulk-relearn` thực thi |

### `links.txt` Format

```
# Comments OK
https://www.royalroad.com/fiction/12345/my-novel/chapter/1
https://www.fanfiction.net/s/14213710/1/My-Story
!relearn fanfiction.net          # Force re-learn this domain
# Empty lines OK
```

---

## Architecture

```
INPUT (web URL / EPUB / TXT)
        │
        ▼
┌────────────────────┐
│ ingest/router      │  detect input type
└─────────┬──────────┘
          ▼
┌────────────────────┐
│ Adapter            │  web / epub / txt → RawDocument
└─────────┬──────────┘
          ▼
┌────────────────────────────────────────────────┐
│ Core Pipeline (per chapter, reuse)             │
│   Filter HTML → Extract → Title → Nav →        │
│   Validate → Clean → AdsFilter → Image stage   │
└─────────┬──────────────────────────────────────┘
          ▼
┌────────────────────┐
│ CleanedChapter DTO │
└─────────┬──────────┘
          ▼
┌────────────────────┐
│ writers/{obsidian,translation,raw} │
└─────────┬──────────┘
          ▼
output/{story_slug}/
├── 0001_Chapter_Title.md
├── 0002_*.md
└── images/
```

Detail: [BLUEPRINT.md](BLUEPRINT.md) §5.

---

## Troubleshooting

10 common issues + fixes: see [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md).

Quick triage:
- **No `GEMINI_API_KEY` found** → Tạo `.env` với `GEMINI_API_KEY=...`
- **HTTP 429 rate limit** → Code tự backoff theo Gemini `retry_delay`, đợi
- **Story stops after 5 errors** → Site có thể đã đổi cấu trúc → `!relearn`
- **Cloudflare challenge** → Cài Playwright (`pip install playwright && playwright install chromium`)
- **Unicode error on TXT** → File phải UTF-8, convert qua `iconv -f cp1252 -t utf-8 file.txt`

---

## FAQ

**Q: Có scrape được site Trung/Nhật/Hàn raw không?**
A: v1.0 chỉ UTF-8 baseline. Content có CJK chars qua được pipeline (BeautifulSoup Unicode-safe), nhưng chapter pattern "第N章" / "第N話" chưa support. EN-translated CN/KR sites work full. Native CJK → defer v1.1.

**Q: Làm sao thêm site mới?**
A: Không cần code. Bỏ URL chapter 1 vào `links.txt`, chạy. Learning Phase tự động 8 AI calls, profile lưu vào `data/site_profiles.json`.

**Q: Profile sai sau khi site update layout?**
A: `!relearn <domain>` trong `links.txt` hoặc `python main.py --bulk-relearn --pattern <domain> --apply`.

**Q: Scrape có thể đa thread không?**
A: Đã có. Mỗi URL trong `links.txt` = 1 task. Learning sequential (tránh AI race), scrape parallel.

**Q: Có thể dùng Claude / OpenAI thay Gemini không?**
A: Không trong v1.0. Hard-coded Gemini cho cost (free tier). Đổi provider = rewrite `ai/client.py` + `ai/agents.py` — defer v1.1.

**Q: Output size lớn quá → split chunk được không?**
A: TranslationWriter có `CHUNK_THRESHOLD=0` (default off). Modern LLMs (Gemini 1M, Claude 200K) handle 30k chars OK. Nếu cần split: edit `writers/translation.py`.

**Q: AdsFilter giết content thật?**
A: Có MAX_STRIP_RATIO 60% safety cap. Nếu nghi ngờ: xem `data/ads_keywords.json` per-domain, xóa keyword sai, re-run.

**Q: Cào Text khác QuickTranslator / FanFicFare / Trafilatura ra sao?**
A: Xem [BLUEPRINT.md](BLUEPRINT.md) §1 — pattern khác (learn-once vs per-site hand-written vs generic heuristic).

---

## Project Documents

| File | Role |
|------|------|
| [README.md](README.md) | This file — quick start + user reference |
| [CHANGELOG.md](CHANGELOG.md) | Version history |
| [CLAUDE.md](CLAUDE.md) | AI agent governance (HOW + WHY) |
| [BLUEPRINT.md](BLUEPRINT.md) | Vision + architecture (WHAT in total) |
| [ROADMAP.md](ROADMAP.md) | Phase-by-phase execution (WHAT by sequence) |
| [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) | 10 common issues |
| [docs/V1_1_BACKLOG.md](docs/V1_1_BACKLOG.md) | Deferred features for v1.1+ |
| [docs/MIGRATION_NOTES.md](docs/MIGRATION_NOTES.md) | Breaking schema notes |
| [docs/PHASE_{1,2,3,4}_RETRO.md](docs/) | Phase retrospectives |
| [docs/AUDIT_PHASE6.md](docs/AUDIT_PHASE6.md) | Phase 6 codebase audit |

---

## Runtime Files (gitignored)

```
data/site_profiles.json        # per-domain learned profiles
data/ads_keywords.json         # per-domain ads keywords
data/txt_cases.json            # TXT chapter pattern DB (Phase 5 — committed)
data/baselines/{label}/        # regression baseline output
progress/{domain}_{slug}.json  # per-story resume state
output/{story_slug}/           # generated chapters
issues.md                      # session error log
.env                           # Gemini API key (NEVER commit)
```

---

## Acknowledgments

Inspired by **FanFicFare** (scope rộng), **gallery-dl** (extractor pattern), **Trafilatura** (extraction heuristics), **QuickTranslator** (consistency through dictionary layer).

Built solo, vibe-coded with Claude. Production for personal use.
