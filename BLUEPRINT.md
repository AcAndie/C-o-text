# Cào Text — Project Blueprint v1.1

> **Một công cụ chuẩn hóa nội dung tiểu thuyết cá nhân, đa dụng, đa ngôn ngữ** — ném input nào vào (URL truyện đa site / EPUB / TXT) cũng ra được một bộ chapter sạch, không noise, đọc được trên Obsidian hoặc đem đi dịch.
>
> Site mới chỉ cần học 1 lần (~8 AI calls), lần sau xài lại profile đã lưu. Free khi không cần re-learn.

---

## 1. Vision

Build a **single-user, offline-first novel normalizer** that:
- Accepts 3 input types: **web URL (chain of chapters)**, **EPUB file**, **TXT file**
- Outputs 3 modes (chọn theo run): **Obsidian-ready Markdown**, **Translation-ready plain text**, **Raw cleaned text**
- Supports **multi-site, multi-language web sources** (English, Vietnamese, EN-translated CN/KR/JP)
- Supports inline images in chapter (light novel illustration, manhua-trong-novel) cho Obsidian mode
- Learns site structure once via AI (8 calls + Naming Phase), persists as `SiteProfile`, reuses cho lần sau
- Filters noise (ads, watermark, comment section, footer) qua 3-layer defense
- **Decompose** file nén (EPUB/TXT) thành 1 file Markdown/text per chapter — không còn cuộn vô tận
- Single user, single machine, không cần network sau khi đã learn

**i18n scope v1.0:** UTF-8 baseline. Site EN/VN + EN-translated content work full. Site native CJK (Trung/Nhật/Hàn raw) defer hardening đến v1.1 — nhưng UTF-8 read/write của content chứa CJK characters vẫn work (BeautifulSoup, regex Unicode-safe).

**Inspiration:**
- **FanFicFare** — scope rộng + maintenance lâu năm + per-site adapter pattern
- **gallery-dl** — extractor plugin architecture (per-site Python class)
- **Trafilatura** — extraction heuristics (density scoring, JSON-LD fallback) — *học pattern, không integrate*
- **QuickTranslator** — output consistency through dictionary layer (apply pattern cho ads keyword)

---

## 2. The Core Insight (Why This Architecture)

Most generic scrapers do this:
```
URL → fetch → parse → output
```
Result: phải viết per-site logic, hoặc dùng generic heuristic (Trafilatura) mất chính xác.

Hand-written per-site adapter (FanFicFare):
```
URL → site-specific class → extract → output
```
Result: tốt nhất nếu có dev time, nhưng scale linear theo số site.

**Cào Text does this** (two-phase pattern):
```
NEW SITE:    URL → fetch 10 chapters → 8 AI calls + Naming → SiteProfile (one-time, ~$0.02)
KNOWN SITE:  URL → load SiteProfile → composable blocks → output (free, fast)
```
Result:
- **AI cost khấu hao** — học 1 lần, dùng vô hạn lần
- **Profile durable** — site không đổi structure thì profile sống mãi
- **Composable** — block độc lập, swap dễ (curl → playwright fallback chẳng hạn)
- **Generic-enough** — site mới chỉ cần AI hiểu HTML, không cần dev viết adapter
- **Adapter-agnostic core** — EPUB/TXT reuse cùng pipeline core

Đây là điểm khác biệt cốt lõi so với FanFicFare (per-site hand-written), Trafilatura (generic heuristic không learn), và Newspaper3k (one-shot extraction).

---

## 3. Input Strategy

```
┌────────────────────────────────────────────────────────────┐
│ MODE A — WEB SCRAPER (default, currently working)          │
│   Input: links.txt với list URL chapter 1 của mỗi truyện   │
│   Adapter: pipeline FetchChain (curl_cffi + Playwright)    │
│   Navigation: NavChain follow next_url qua N chapter       │
│   Learning: 8 AI calls/domain + Naming Phase (one-time)    │
│   Languages: EN, VN, EN-translated CN/KR/JP                │
└────────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────┐
│ MODE B — EPUB INGEST (v1.0 new)                            │
│   Input: file .epub                                         │
│   Adapter: ebooklib unzip + parse OPF spine                │
│   Each spine item → HTML → feed vào ExtractChain (reuse)   │
│   No learning needed — EPUB structure standardized          │
│   Image: EpubImageExtractor pull binary từ zip → save local │
│   Naming: EPUB Dublin Core metadata → AI fallback           │
└────────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────┐
│ MODE C — TXT INGEST (v1.0 new, narrowed scope)             │
│   Input: file .txt (1 truyện, đã có chapter break)         │
│   Adapter: detect chapter boundary (regex + AI verify)     │
│   Languages v1.0: Vietnamese ("Chương N") + English        │
│                   ("Chapter N"). CJK defer v1.1.            │
│   Each chunk → wrap as HTML <p> → feed vào ExtractChain    │
│   Pattern lưu vào "TXT case database" (case-based valid)   │
│   Failure: nếu pattern không detect được → surface error   │
│   Exit ramp: nếu sau 1 tuần test < 50% pass → defer v1.1   │
└────────────────────────────────────────────────────────────┘
```

**Common output shape sau adapter:** `RawDocument` chứa `{chapter_index, html_or_text, source_url_or_path, metadata}` — pipeline core không biết source.

---

## 4. Output Strategy

User chọn 1 mode tại runtime qua CLI flag:

```bash
python main.py --output-mode obsidian   links.txt
python main.py --output-mode translate  novel.epub
python main.py --output-mode raw        novel.txt
```

```
┌──────────────────────────────────────────────────────────────┐
│ MODE: OBSIDIAN                                                │
│   Format: Markdown chuẩn                                      │
│   Frontmatter: title, source, chapter_index (minimal)         │
│   Image: download local → ![](images/ch_NNNN_idx.jpg)         │
│   Filename: 0042_Chapter_Title.md                             │
│   Folder: output/{story_slug}/ + output/{story_slug}/images/  │
│   Use: đọc trong Obsidian vault                                │
└──────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────┐
│ MODE: TRANSLATION                                             │
│   Format: plain text, một paragraph một dòng                  │
│   No frontmatter (translator AI confuse)                      │
│   Image: skip download, INSERT `[IMAGE: alt]` placeholder     │
│           (translator có context không bị mất sentence flow)  │
│   Filename: 0042.txt (simple, dễ batch process)               │
│   Use: paste vào tool dịch (ChatGPT, Gemini, TriLex, ...)     │
└──────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────┐
│ MODE: RAW                                                     │
│   Format: text only, không Markdown formatting                │
│   No frontmatter, no image (no placeholder), no heading       │
│   Filename: 0042.txt                                          │
│   Use: backup, archive, hoặc input cho tool khác              │
└──────────────────────────────────────────────────────────────┘
```

### Mode-aware decisions trong pipeline

`RunConfig` được pass xuống `PipelineContext`:

```python
@dataclass
class RunConfig:
    output_mode      : Literal["obsidian", "translate", "raw"]
    download_images  : bool   # default: True cho obsidian, False cho khác
    image_placeholder: bool   # True cho translate (insert [IMAGE: alt]), False cho raw
    fetch_metadata   : bool   # default: True cho obsidian, False cho khác
    output_dir       : str
```

Block đọc `ctx.run_config.download_images` để skip image extraction nếu False. Tránh wasted work.

### Input × Output matrix

| Input \\ Output | Obsidian | Translate | Raw |
|---|---|---|---|
| **Web** (URL list) | ✅ default, full feature | ✅ no image download | ✅ no image, no MD |
| **EPUB** | ✅ extract embedded image | ✅ skip image, placeholder | ✅ text only |
| **TXT** | ✅ no image possible | ✅ optimized for paste | ✅ closest to original |

Mọi cell trong matrix đều phải work — pipeline core agnostic, writer mode-specific.

---

## 5. System Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  USER FACING                                                     │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │  CLI (main.py)                                           │    │
│  │   python main.py [--output-mode X] [--max-pw N]          │    │
│  │                  [--fast-learning] [--no-validation]     │    │
│  │                  [--bulk-relearn] [--snapshot-baseline]  │    │
│  │                  <input_file>                            │    │
│  └─────────────────────────────────────────────────────────┘    │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│  INPUT ROUTER (ingest/router.py)                                 │
│   Detect input type (URL list / .epub / .txt content) → adapter │
└────────────────────────────┬────────────────────────────────────┘
                             │
        ┌────────────────────┼────────────────────┐
        ▼                    ▼                    ▼
┌──────────────┐    ┌────────────────┐    ┌──────────────┐
│ Web Adapter   │    │ EPUB Adapter   │    │ TXT Adapter  │
│ (existing)    │    │ (Phase 3)      │    │ (Phase 5)    │
└──────┬───────┘    └────────┬───────┘    └──────┬───────┘
       │                     │                    │
       └─────────────────────┼────────────────────┘
                             ▼
                    ┌─────────────────┐
                    │  RawDocument    │
                    │  (HTML or text  │
                    │   with chunks)  │
                    └────────┬────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│  CORE PIPELINE (per chapter, reuse across all inputs)            │
│                                                                  │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  1. Filter HTML (html_filter.prepare_soup)               │   │
│  │     • Layer 1: script/style/iframe always                │   │
│  │     • Layer 2: KNOWN_NOISE_SELECTORS                     │   │
│  │     • Layer 3: profile.remove_selectors (learned)        │   │
│  │                                                          │   │
│  │  2. Extract Chain (first-wins)                           │   │
│  │     SelectorExtract → JsonLdExtract → DensityHeuristic   │   │
│  │     → XPathExtract → FallbackList → AIExtract            │   │
│  │     (+ collect <img> tags nếu run_config.download_images)│   │
│  │                                                          │   │
│  │  3. Title Chain (first-wins by priority)                 │   │
│  │     SelectorTitle(0.95) → H1(0.80) → TitleTag(0.65)      │   │
│  │     → OgTitle(0.65) → UrlSlug(0.40)                      │   │
│  │                                                          │   │
│  │  4. Nav Chain (only web mode, skip cho EPUB/TXT)         │   │
│  │     find_next_url(soup, profile.next_selector)           │   │
│  │     → fallback: ai_classify_and_find                     │   │
│  │                                                          │   │
│  │  5. Validate Chain                                       │   │
│  │     ProseRichnessBlock (char count, prose density)       │   │
│  │     Junk page check, end-of-story detection              │   │
│  │                                                          │   │
│  │  6. Post-extraction Cleaning (utils/content_cleaner)     │   │
│  │     5-pass strip với MAX_STRIP_RATIO 60% safety cap       │   │
│  │                                                          │   │
│  │  7. AdsFilter (cross-chapter frequency)                  │   │
│  │     Auto-add (freq >=10) + AI verify (3-9) → save        │   │
│  │                                                          │   │
│  │  8. Image Stage (mode-aware)                             │   │
│  │     If run_config.download_images:                       │   │
│  │       strategy = WebImageFetcher | EpubImageExtractor    │   │
│  │       fetch → save local → rewrite placeholder in body   │   │
│  │     Elif run_config.image_placeholder (translate):       │   │
│  │       replace ![alt](url) → [IMAGE: alt]                 │   │
│  │     Else (raw): strip image entirely                     │   │
│  └─────────────────────────────────────────────────────────┘   │
│                             │                                    │
│                             ▼                                    │
│                  ┌────────────────────┐                          │
│                  │  CleanedChapter    │  (DTO)                   │
│                  └─────────┬──────────┘                          │
└────────────────────────────┼────────────────────────────────────┘
                             │
        ┌────────────────────┼────────────────────┐
        ▼                    ▼                    ▼
┌──────────────┐    ┌────────────────┐    ┌──────────────┐
│ObsidianWriter│    │TranslationWriter│   │ RawWriter    │
└──────┬───────┘    └────────┬───────┘    └──────┬───────┘
       │                     │                    │
       └─────────────────────┼────────────────────┘
                             ▼
                   output/{story_slug}/
                   ├── 0001_*.md (or .txt)
                   ├── 0002_*.md
                   └── images/ (chỉ obsidian mode)
                             ▲
                             │
┌────────────────────────────┴────────────────────────────────────┐
│  PERSISTENCE                                                     │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  data/site_profiles.json    — per-domain learned profile  │   │
│  │  data/ads_keywords.json      — per-domain ads keywords    │   │
│  │  data/txt_cases.json         — TXT pattern (Phase 5)      │   │
│  │  data/baselines/{name}/      — regression baseline output │   │
│  │  progress/{...}.json          — per-story progress        │   │
│  │  issues.md                    — session issue log         │   │
│  └──────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

---

## 6. Pipeline Detail (Per Chapter)

### Route: Web URL → Obsidian Markdown

```
INPUT: Chapter URL
   │
   ▼
[Stage 1: Fetch]
   • HybridFetchBlock (curl_cffi → Playwright fallback nếu Cloudflare)
   • Output: raw HTML + status_code
   │
   ▼
[Stage 2: Filter & build soup]
   • Strip script/style/iframe (always)
   • Apply profile.remove_selectors (with content/title/next ancestor protection)
   • Apply KNOWN_NOISE_SELECTORS
   • Output: BeautifulSoup ready for extract
   │
   ▼
[Stage 3: Extract content]
   • SelectorExtractBlock (try profile.content_selector first)
   • If fail → JsonLdExtract → DensityHeuristic → XPath → FallbackList → AIExtract
   • _format_element() with profile.formatting_rules → Markdown
   • If run_config.download_images: collect <img> tags → ctx.image_refs
   │
   ▼
[Stage 4: Extract title]
   • TitleChain first-wins:
     SelectorTitle → H1 → TitleTag → OgTitle → UrlSlug
   • strip_site_suffix() applied
   │
   ▼
[Stage 5: Navigate] (web only)
   • find_next_url(soup, profile.next_selector, nav_type)
   • Fallback: ai_classify_and_find() (1 AI call, only if heuristic fail)
   │
   ▼
[Stage 6: Validate]
   • ProseRichnessBlock (skip if --no-validation)
   • Junk page check (status, content length, error markers)
   • End-of-story detection (is_error_content + length gating)
   │
   ▼
[Stage 7: Post-extraction Clean]
   • 5-pass: raw_script → comment → settings → postfix → metadata → ui_nav
   • MAX_STRIP_RATIO 60% safety cap
   │
   ▼
[Stage 8: AdsFilter]
   • Cross-chapter frequency analysis
   • Auto-add lines appearing >=10 times across chapters
   • AI verify lines appearing 3-9 times
   • Apply confirmed filters → strip from current chapter
   │
   ▼
[Stage 9: Image stage] (mode-aware)
   • If obsidian: WebImageFetcher.fetch_batch(image_refs) → save local
                  → rewrite placeholder thành relative path
   • If translate: replace ![alt](url) → [IMAGE: alt] inline
   • If raw: strip image entirely
   • Failure mode: keep ![image-failed](url) placeholder, continue
   │
   ▼
[Stage 10: Build CleanedChapter DTO]
   • index, title, body_markdown, images, source_url, metadata
   │
   ▼
[Stage 11: Writer]
   • ObsidianWriter / TranslationWriter / RawWriter theo run_config
   • Filename: {story}/0042_Chapter_Title.md (hoặc 0042.txt)
   │
   ▼
[Stage 12: Persist]
   • Update progress JSON (current chapter, next_url, naming)
   • Update ads_filter (save() atomic with threading.Lock)
   • Update SiteProfile if requires_playwright changed
```

### Route: EPUB → Translation plain text

```
INPUT: novel.epub
   │
   ▼
[Stage 1: EPUB parse]
   • ebooklib.epub.read_epub()
   • Iterate spine, get each EpubHtml item
   • Each item → BeautifulSoup → wrap as RawDocument
   • Naming: book.get_metadata('DC', 'title') → AI fallback nếu None
   │
   ▼
[Stage 2-7: Reuse web pipeline]
   • Skip Stage 5 (Navigate — không có next URL)
   • Skip image download (translate mode = run_config.download_images=False)
   • Cleaning passes apply như cũ (EPUB pirate cũng có watermark)
   │
   ▼
[Stage 8: AdsFilter]
   • Per-file frequency analysis (treat filename slug as "domain")
   │
   ▼
[Stage 9: Image stage — translate mode]
   • Skip extraction (no download)
   • Replace ![alt](src) → [IMAGE: alt] inline
   │
   ▼
[Stage 10-11: CleanedChapter → TranslationWriter]
   • Plain text, paragraph-per-line
   • Filename: 0042.txt
   • Optional: split chapter thành chunks N ký tự để fit context window
```

### Route: EPUB → Obsidian Markdown (image embedded)

```
[Stage 9: Image stage — obsidian mode + EPUB source]
   • strategy = EpubImageExtractor(book)
   • For each image_ref:
       binary = book.get_item_with_href(ref.original_url).get_content()
       save to output/{story}/images/ch_NNNN_idx.{ext}
   • Rewrite placeholder
```

`EpubImageExtractor.fetch()` không gọi HTTP — đọc binary trực tiếp từ zip in-memory. Cùng interface với `WebImageFetcher` nên pipeline không cần biết.

### Route: TXT → Raw

```
INPUT: novel.txt
   │
   ▼
[Stage 1: TXT chapter boundary detection]
   • Sample 100 dòng đầu → match từng case trong data/txt_cases.json
   • Best match → return case (VN "Chương N", EN "Chapter N", ...)
   • No match → fallback AI: gửi 50 dòng + ask pattern
   • AI verify với 3 chapter ngẫu nhiên
   • AI verify pass → add vào data/txt_cases.json (new case learned)
   • Apply pattern → split file thành list[(idx, title, body)]
   │
   ▼
[Stage 2: Wrap each chunk as HTML]
   • text → <article><p>...</p>...</article>
   • Feed vào ExtractChain (SelectorExtract skip, DensityHeuristic accept)
   │
   ▼
[Stage 3-8: Reuse pipeline]
   • Cleaning passes apply (TXT từ pirated source cũng có watermark text)
   • AdsFilter apply (per-file domain key)
   │
   ▼
[Stage 9: Image stage — no-op for TXT]
   • TXT không có image, skip
   │
   ▼
[Stage 10-11: CleanedChapter → RawWriter]
   • Text only, no Markdown
   • Filename: 0042.txt
```

---

## 7. File Structure

```
Cào text/
│
├── main.py                       # Entry point CLI
├── config.py                     # Constants, env, regex
├── .env                          # GEMINI_API_KEY (gitignored)
├── .gitignore
├── README.md                     # 🆕 Quick start, install, usage (maintained throughout)
├── CLAUDE.md                     # Governance
├── BLUEPRINT.md                  # This file
├── ROADMAP.md                    # Execution order
│
├── ai/
│   ├── client.py                 # AIRateLimiter, Gemini wrapper
│   ├── prompts.py                # All AI prompts centralized
│   └── agents.py                 # AI utility functions + validation guards
│
├── pipeline/                     # Core pipeline (Lego blocks)
│   ├── base.py                   # BlockResult, PipelineContext, ScraperBlock, ImageRef
│   ├── executor.py               # PipelineRunner, ChainExecutor
│   ├── fetcher.py                # Curl/Playwright/Hybrid fetch blocks
│   ├── extractor.py              # Selector/JsonLd/Density/XPath/Fallback/AI extract
│   ├── title_extractor.py        # Selector/H1/Title/Og/UrlSlug title blocks
│   ├── navigator.py              # Next URL finding
│   └── validator.py              # ProseRichness, junk detection
│
├── core/
│   ├── scraper.py                # run_novel_task orchestrator
│   ├── orchestrator.py           # 🆕 v1.0 input-type routing orchestrator
│   ├── session_pool.py           # DomainSessionPool, PlaywrightPool
│   ├── html_filter.py            # prepare_soup (3-layer defense)
│   ├── formatter.py              # MarkdownFormatter (extend cho img)
│   └── image_pipeline/           # 🆕 v1.0 — image fetch strategies
│       ├── __init__.py
│       ├── base.py               # ImageFetchStrategy ABC
│       ├── web_fetcher.py        # WebImageFetcher (HTTP qua DomainSessionPool)
│       └── epub_extractor.py     # EpubImageExtractor (binary từ zip)
│
├── learning/
│   ├── phase.py                  # Learning phase orchestrator
│   ├── phase_ai.py               # 8 AI calls sequenced
│   ├── profile_manager.py        # SiteProfile load/save
│   └── naming.py                 # Story name + chapter pattern detection
│
├── ingest/                       # 🆕 v1.0 — input adapters
│   ├── __init__.py
│   ├── web.py                    # 🆕 wrap existing scraper as adapter
│   ├── epub.py                   # 🆕 ebooklib parser
│   ├── txt.py                    # 🆕 chapter boundary detection (VN+EN)
│   └── router.py                 # 🆕 detect input type, dispatch
│
├── writers/                      # 🆕 v1.0 — output writer implementations
│   ├── __init__.py               # (renamed từ output/ ở P1.3 — tránh
│   ├── base.py                   #  conflict với runtime output/ dir gitignored)
│   ├── obsidian.py               # 🆕 ObsidianWriter
│   ├── translation.py            # 🆕 TranslationWriter
│   └── raw.py                    # 🆕 RawWriter
│
├── utils/
│   ├── types.py                  # SiteProfile, ProgressDict, FormattingRules TypedDicts
│   ├── string_helpers.py         # normalize, slugify, strip_site_suffix
│   ├── ads_filter.py             # AdsFilter with atomic save
│   ├── content_cleaner.py        # 5-pass post-extraction cleaning
│   ├── image_url.py              # 🆕 v1.0 — resolve_image_url helper
│   ├── file_io.py                # load/save profiles, ensure dirs
│   └── issue_reporter.py         # Session issue log
│
├── tools/                        # 🆕 v1.0 — dev tools (committed)
│   ├── snapshot_baseline.py      # 🆕 capture baseline output for regression diff
│   └── bulk_relearn.py           # 🆕 bulk delete profiles (or call via --bulk-relearn flag)
│
├── data/                         # gitignored (except baselines)
│   ├── site_profiles.json
│   ├── ads_keywords.json
│   ├── txt_cases.json            # 🆕 v1.0 — TXT pattern database
│   └── baselines/                # 🆕 v1.0 — committed reference output
│       └── {snapshot_name}/
│           └── {chapter_files}
│
├── progress/                     # gitignored
│   └── {domain}_{slug}_{hash8}.json
│
├── output/                       # gitignored
│   └── {story_slug}/
│       ├── 0001_*.md
│       └── images/
│
├── links.txt                     # User input (gitignored)
├── issues.md                     # Session log (gitignored)
│
└── docs/
    ├── V1_1_BACKLOG.md           # Deferred features
    └── MIGRATION_NOTES.md        # Breaking changes
```

---

## 8. Data Models (Key Schemas)

### SiteProfile (per-domain, persistent)

```python
class SiteProfile(TypedDict, total=False):
    # Core identity
    domain               : str
    last_learned         : str
    confidence           : float
    profile_version      : int   # bump khi schema change

    # Learned selectors
    content_selector     : str | None
    next_selector        : str | None
    title_selector       : str | None
    remove_selectors     : list[str]
    nav_type             : str | None
    chapter_url_pattern  : str | None
    requires_playwright  : bool

    # Content rules
    formatting_rules     : FormattingRules
    download_images      : bool          # 🆕 v1.0: site có ảnh đáng tải không
    image_selector       : str | None    # 🆕 v1.0: nếu site có wrapper riêng cho illustration
```

### FormattingRules (explicit schema — fix gap từ v1.0 draft)

```python
class FormattingRules(TypedDict, total=False):
    # Tag → Markdown mapping decisions
    headings_as_h2       : bool     # h1/h2/h3 trong content → "##" thay vì cấu trúc gốc
    preserve_bold        : bool     # <b>/<strong> → "**text**"
    preserve_italic      : bool     # <i>/<em> → "*text*"
    preserve_blockquote  : bool     # <blockquote> → "> text"
    paragraph_separator  : str      # "\n\n" default
    list_style           : Literal["dash", "asterisk"]  # "- " hoặc "* "

    # Image handling (single source of truth — không có image_alt_text duplicate)
    image_alt_strategy   : Literal["preserve", "skip", "fallback_to_filename"]

    # Stripping
    strip_inline_links   : bool     # <a> → text only (novel rare meaningful link)
    strip_html_comments  : bool     # luôn True

    # Language/encoding
    text_encoding        : str      # "utf-8" default, không change trừ user override
```

**Decision:** `image_alt_strategy` thay cho boolean `image_alt_text` cũ — explicit về behavior (preserve / skip / fallback). Mặc định `"preserve"`.

### RunConfig (per-run, transient)

```python
@dataclass
class RunConfig:
    output_mode      : Literal["obsidian", "translate", "raw"]
    download_images  : bool          # derive từ output_mode default, override được
    image_placeholder: bool          # translate mode: True (insert [IMAGE: alt])
    fetch_metadata   : bool          # derive từ output_mode
    output_dir       : str
    max_pw_instances : int = 2
    fast_learning    : bool = False
    no_validation    : bool = False

    @classmethod
    def from_cli(cls, args) -> RunConfig:
        mode = args.output_mode
        defaults = {
            "obsidian":  {"dl": True,  "ph": False, "meta": True},
            "translate": {"dl": False, "ph": True,  "meta": False},
            "raw":       {"dl": False, "ph": False, "meta": False},
        }[mode]
        return cls(
            output_mode       = mode,
            download_images   = args.download_images   or defaults["dl"],
            image_placeholder = args.image_placeholder or defaults["ph"],
            fetch_metadata    = args.fetch_metadata    or defaults["meta"],
            output_dir        = args.output_dir,
            ...
        )
```

### CleanedChapter (pipeline → writer contract)

```python
@dataclass
class CleanedChapter:
    index           : int
    title           : str
    body_markdown   : str             # Markdown chuẩn, image refs đã resolve hoặc placeholder
    images          : list[ImageRef]  # URL/path + position (rỗng nếu mode không download)
    source_url      : str | None      # None nếu input là EPUB/TXT
    source_path     : str | None      # None nếu input là web
    metadata        : dict            # author, story_name, language, ...


@dataclass
class ImageRef:
    original_url    : str             # URL gốc (web) hoặc href trong EPUB (vd "Images/cover.jpg")
    local_path      : str | None      # None nếu chưa download (translate/raw mode) hoặc fetch failed
    alt_text        : str
    position_marker : str             # placeholder trong body_markdown (vd "IMG_PLACEHOLDER_0")
    source_type     : Literal["web", "epub"]  # cho strategy router biết dùng fetcher nào
```

### ProgressDict (per-story, persistent)

```python
class ProgressDict(TypedDict, total=False):
    story_url          : str
    next_url           : str | None
    chapter_count      : int
    last_chapter_idx   : int
    last_updated       : str
    naming             : NamingRules
    completed          : bool
    end_of_story_seen  : bool
```

### NamingRules (per-story)

```python
class NamingRules(TypedDict, total=False):
    story_name_clean   : str    # slug, dùng cho folder
    story_name_display : str    # human-readable, dùng cho frontmatter
    chapter_pattern    : str    # regex extract số chapter từ title
    title_strip_suffix : list[str]  # site suffix cần strip
    language           : str    # ISO code, vd "vi", "en", "zh-Hans"
```

---

## 9. Learning Phase (8 AI Calls + Naming)

Chỉ chạy 1 lần per domain mới. Profile lưu vào `data/site_profiles.json`.

```
Phase 1 — Structure Discovery (Ch.1-4):
  AI#1 — Ch.1+2: Initial DOM structure mapping
  AI#2 — Ch.1+2: Independent cross-check (same data, independent prompt)
  AI#3 — Ch.3+4: Selector stability validation

Phase 2 — Conflict Resolution (Ch.5-6):
  AI#4 — Ch.5:   Remove selectors audit (safe vs dangerous)
  AI#5 — Ch.6:   Title extraction deep-dive + author contamination check

Phase 3 — Content Intelligence (Ch.7-8):
  AI#6 — Ch.7:   Special content detection
                 (tables, math, system box, hidden text, author note)
  AI#7 — Ch.8:   Ads & watermark deep scan
                 + 🆕 v1.0: detect image policy (site có ảnh đáng tải không)

Phase 4 — Synthesis:
  AI#8 — Master profile synthesis from all previous results

POST-LEARNING:
  Naming Phase (separate, not counted as AI#N):
    - Story name extraction (from title page or AI on titles)
    - Chapter pattern detection (regex generated từ sample titles)
    - Language detection (heuristic + AI verify)
```

**Conventions:**
- Learning agents (`phase_ai.py`) receive pre-trimmed HTML via `snippet()`
- Utility agents (`agents.py`) call `snippet()` themselves
- `_default_formatting_rules()` initializes full structure TRƯỚC khi AI#6 chạy — nếu AI#6 fail, defaults vẫn đúng
- Validation guards ở `agents.py` là layer 2 — layer 1 là prompt constraint ("PLAIN TEXT ONLY")

**Cost ước tính per site:** ~$0.02 với Gemini Flash. Một site novel scrape 1000 chapter → AI cost gần như zero sau learning phase.

**EPUB:** không cần Learning Phase. Naming dùng `book.get_metadata('DC', 'title')` từ Dublin Core, AI fallback chỉ khi metadata trống.

**TXT:** không cần Learning Phase. Boundary detection có riêng — case database + AI verify (xem §3 Mode C).

---

## 10. Roadmap (high-level — chi tiết xem ROADMAP.md)

### Phase 0: Cleanup + Foundation (3 ngày) — ✅ DONE 2026-05-16

- [x] Baseline snapshot tool (`tools/snapshot_baseline.py`) — capture deferred (chưa có profile FFN/RR thật trong repo)
- [x] **Batch A** (P0.2): Xóa `learning/optimizer.py` + stale refs — ~450 dòng
- [x] **Batch B** (P0.3): Xóa `StepConfig/ChainConfig/PipelineConfig` serialization + `learning/migrator.py` + legacy guard trong `ProfileManager.get()` — ~330 dòng
- [ ] README.md skeleton (P0.4 — DEFERRED, README hiện là placeholder)
- [x] MIGRATION_NOTES.md (`docs/MIGRATION_NOTES.md`) + bulk-relearn (`main.py --bulk-relearn`) — P0.5
- [x] Docs sync (CLAUDE.md §17, BLUEPRINT.md §10, ROADMAP.md Phase 0) — P0.6

**Mục tiêu:** giảm ~780 dòng, foundation sạch. Zero new feature. **Achieved.**

### Phase 1: Output Mode Abstraction (1 tuần) — TRƯỚC image support

- [ ] `RunConfig` dataclass + CLI flag parsing
- [ ] `CleanedChapter` + `ImageRef` DTO + `FormattingRules` explicit TypedDict
- [ ] `output/base.py`: `ChapterWriter` ABC
- [ ] `output/obsidian.py`: `ObsidianWriter` (port từ `chapter_writer.py` hiện tại)
- [ ] Pipeline refactor: produce `CleanedChapter` thay vì ghi file trực tiếp (**STOP** — shared logic, ask user)
- [ ] **Baseline diff** vs Phase 0 snapshot — output phải identical (chỉ thêm frontmatter)

**Acceptance test:** 1 URL × obsidian mode → output Markdown khớp baseline (chỉ thêm frontmatter YAML).

### Phase 2: Image support cho web (1-2 tuần)

- [ ] `utils/image_url.py`: resolve_image_url helper (lazy-load, protocol-relative, data URI skip)
- [ ] `core/image_pipeline/base.py`: `ImageFetchStrategy` ABC
- [ ] `core/image_pipeline/web_fetcher.py`: `WebImageFetcher` (HTTP qua `DomainSessionPool`)
- [ ] `MarkdownFormatter` extend cho `<img>` — **STOP** — đổi return type, ask user
- [ ] Pipeline image stage (mode-aware, đọc `run_config.download_images`)
- [ ] AI#7 prompt update: detect image policy
- [ ] Failure mode: image fail không crash chapter

**Acceptance test:** scrape 1 Royal Road novel có art → output có `images/` folder, Markdown embed đúng vị trí, Obsidian render OK.

### Phase 3: EPUB adapter (1-1.5 tuần)

- [ ] `ingest/router.py` detect input type
- [ ] `ingest/web.py` wrap existing scraper logic
- [ ] `ingest/epub.py` ebooklib parse spine + Dublin Core metadata
- [ ] `core/image_pipeline/epub_extractor.py`: `EpubImageExtractor` (binary từ zip, cùng interface với `WebImageFetcher`)
- [ ] `core/orchestrator.py` route theo input type
- [ ] Add `ebooklib` to dependencies
- [ ] AdsFilter cho EPUB (per-file domain key)

**Acceptance test:** EPUB pirate có watermark → cleaning passes strip, output sạch, image embedded extract đúng.

### Phase 4: TranslationWriter + RawWriter (3 ngày)

- [ ] `output/translation.py`: paragraph-per-line, no image (placeholder `[IMAGE: alt]`)
- [ ] `output/raw.py`: text only, image stripped
- [ ] Smoke test 3 mode × 2 input source (web + EPUB)

**Acceptance test:** cùng 1 EPUB chạy 3 mode → 3 output thư mục khác nhau, đều correct.

### Phase 5: TXT adapter (2 tuần — HIGHEST RISK)

- [ ] `data/txt_cases.json` initial cases (VN "Chương N" + EN "Chapter N", ~5 case tổng)
- [ ] `ingest/txt.py` chapter boundary detection
- [ ] AI prompt cho pattern detection (fallback khi case DB miss)
- [ ] Orchestrator route TXT
- [ ] **Exit ramp**: sau 1 tuần test với 3 file, nếu < 50% pass → STOP, defer Phase 5 sang v1.1

**Acceptance test:** 2/3 TXT (1 VN + 1 EN) detect đúng, 1/3 fail-loud nếu pattern lạ.

### Phase 6: Final cleanup + Batch C (1 tuần)

- [ ] Audit codebase post-Phase-5
- [ ] Merge small files (<50 dòng) theo plan
- [ ] Remove boilerplate abstraction
- [ ] Final docs update + README polish

### Phase 7+: Beyond v1.0 (defer to v1.1)

- Case-based learning (sau khi có 10+ profile để thấy pattern)
- Calibration phase (re-probe 10 chapter verify profile)
- **Site Trung/Nhật CJK hardening** (encoding heuristic, font deob, slugify pinyin, "第N章" pattern)
- TypedDict refactor `utils/types.py` (P3-D)
- Manhua adapter (fork project riêng)
- GUI (Streamlit nếu CLI không đủ)

---

## 11. Decision Log

| # | Decision | Choice | Rationale |
|---|---|---|---|
| 1 | Scope v1.0 | Universal novel normalizer (web đa site đa ngôn ngữ / EPUB / TXT), 3 output mode + i18n baseline | User vision thật: đa dụng + decompose file nén |
| 2 | Architecture | 2-phase learning (per domain) + Lego blocks | Khấu hao AI cost, composable, generic-enough |
| 3 | Tránh Trafilatura integration | Không integrate | Generic article extraction khác novel chain — scope mismatch |
| 4 | Tránh per-site hand-written adapter | Không adopt FanFicFare pattern | Scale linear không bền, AI learning amortize tốt hơn cho 5+ site |
| 5 | Image scope | Inline illustration trong novel (use case 1), KHÔNG manhua thuần | Manhua = pipeline khác, gallery-dl đã giải tốt |
| 6 | Output strategy | 3 mode chọn tại runtime, KHÔNG gộp | Mỗi mode có constraint khác (translate cần plain, Obsidian cần Markdown), gộp = compromise cả 2 |
| 7 | Image policy | Per-mode (Obsidian: download, Translate: placeholder, Raw: strip) | Tiết kiệm bandwidth + thời gian khi không cần ảnh |
| 8 | Input adapter shape | Mọi adapter produce `RawDocument` (HTML or text), pipeline không biết source | Decoupling input từ pipeline core |
| 9 | EPUB parsing | `ebooklib` standard library | Mature, maintain tốt, support EPUB 2/3 |
| 10 | TXT chapter boundary | Regex + AI verify, lưu pattern vào case database | TXT format hữu hạn, case-based hợp lý hơn ở đây |
| 11 | Case-based learning cho web | DEFER v1.1 | Chưa có 10+ profile để thấy pattern thật |
| 12 | Test framework | Smoke test + baseline diff trong v1.0, formal pytest defer | Solo dev, ROI thấp cho unit test ở giai đoạn này — nhưng baseline diff = regression guard cheap |
| 13 | Database | Không dùng — JSON file đủ | Single user, no concurrent process, atomic write OK |
| 14 | Web framework | Không có — CLI only | Local tool, không cần API |
| 15 | AI provider | Gemini với full model | Free tier hữu ích, full model cho structured output |
| 16 | Profile durability | Tin profile cho đến khi user `!relearn` hoặc `--bulk-relearn` | Site rarely change structure, user invalidate manual |
| **17** | **Phase ordering** | **Output Abstraction (Phase 1) TRƯỚC Image Support (Phase 2)** | **Image policy = per-mode → cần RunConfig trước → cần CleanedChapter trước. Đảo thứ tự = technical debt cố ý.** |
| **18** | **Baseline regression** | **`tools/snapshot_baseline.py` + commit baseline output vào `data/baselines/`, diff trước/sau refactor lớn** | **Smoke test pass ≠ output identical. Phase 0 và Phase 1.5 cần regression guard cứng.** |
| **19** | **Image fetch strategy** | **Strategy pattern: `WebImageFetcher` (HTTP) vs `EpubImageExtractor` (zip binary), interface `ImageFetchStrategy.fetch()`** | **Source khác, code path khác. Nhưng pipeline không quan tâm — chỉ gọi `strategy.fetch(ref)`.** |
| **20** | **TXT scope v1.0** | **Vietnamese + English chapter pattern only** | **CJK pattern cần language-specific regex + encoding heuristic — defer v1.1.** |
| **21** | **i18n baseline v1.0** | **UTF-8 read/write explicit. Site đa ngôn ngữ work qua existing pipeline.** | **Content có CJK characters pass qua BeautifulSoup + Unicode-safe regex. Chỉ TXT chapter boundary cần language-specific — phần đó defer.** |
| **22** | **EPUB naming source** | **Dublin Core metadata first (`book.get_metadata('DC', 'title')`), AI fallback nếu trống** | **Trust source khi available, tiết kiệm AI call.** |
| **23** | **`FormattingRules.image_alt_strategy`** | **Enum literal `"preserve" / "skip" / "fallback_to_filename"` thay cho boolean cũ** | **Boolean ambiguous (preserve vs strip), enum explicit về behavior.** |
| **24** | **Profile migration UX** | **`main.py --bulk-relearn [--pattern <regex>]` thay vì manual `!relearn` từng cái** | **User có 5+ profile cũ sau breaking schema — bulk script tiết kiệm 20 phút.** |
| **25** | **README maintained** | **Skeleton từ Phase 0, update sau mỗi phase có CLI/UX change** | **Solo dev sẽ quên CLI flag sau 2 tuần không dùng.** |

---

## 12. Open Questions (defer answer to per-phase work)

- TXT case database schema: pattern lưu raw regex hay AI-generated normalized form? (→ Phase 5 P5.1)
- Image download retry policy: retry mấy lần, exponential backoff? (→ Phase 2 P2.2)
- Obsidian frontmatter: minimal (title, source) hay rich (chapter, story, author, language)? (→ Phase 1 P1.4)
- Chunking trong TranslationWriter: theo character count, paragraph count, hay token count? Default value? (→ Phase 4 P4.1)
- EPUB không có spine standard (vd EPUB 3 với navigation document): fallback strategy? (→ Phase 3 P3.4)

Sẽ trả lời từng cái khi đụng vào phase tương ứng — không pre-decide.

---

## 13. Versioning

| Version | Date | Change |
|---|---|---|
| 1.0 | 2026-05-15 | Initial vision + architecture |
| **1.1** | **2026-05-16** | **Phase ordering fix (output trước image), Strategy pattern cho image fetch (Decision #19), FormattingRules explicit schema + image_alt_strategy enum (Decision #23), TXT scope narrow VN+EN (Decision #20), i18n baseline (Decision #21), EPUB Dublin Core naming (Decision #22), bulk-relearn UX (Decision #24), Input × Output matrix table, baseline regression protocol (Decision #18), tools/ folder, README maintained throughout (Decision #25)** |

---

**END BLUEPRINT v1.1**

*Living document — update khi vision/architecture đổi.*
