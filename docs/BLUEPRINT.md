# Cào Text — Project Blueprint v1.2

> **Status (2026-11-09):** ✅ **v1.2.1 SHIPPED.** All 8 phases of v1.0 done (Phase 0 cleanup → Phase 1 output abstraction → Phase 2 image support → Phase 3 EPUB adapter → Phase 4 translation/raw writers → Phase 5 TXT adapter → Phase 6 final cleanup + docs), plus v1.0.13–v1.2.1 production hardening (`ApiKeyPool`, `CalibrationPhase`, `DomainSessionPool` per-host semaphore, `_discover_content_selector`, `MAX_EMPTY_STREAK` restore, RoyalRoad `slug_increment` loop guard). See [ROADMAP.md](ROADMAP.md) for phase summary, [V1_1_BACKLOG.md](V1_1_BACKLOG.md) for open issues, and [CHANGELOG.md](CHANGELOG.md) for release notes.
>
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
├── src/
│   ├── config.py                 # Constants, env, regex, Vault paths
│   ├── ai/
│   │   ├── client.py             # AIRateLimiter, ApiKeyPool, Gemini wrapper
│   │   ├── prompts.py            # All AI prompts centralized
│   │   └── agents.py             # AI utility functions + validation guards
│   ├── pipeline/                 # Core pipeline (Lego blocks)
│   │   ├── base.py               # BlockResult, PipelineContext, ScraperBlock, ImageRef
│   │   ├── executor.py           # PipelineRunner, ChainExecutor
│   │   ├── fetcher.py            # Curl/Playwright/Hybrid fetch blocks
│   │   ├── extractor.py          # Selector/JsonLd/Density/XPath/Fallback/AI extract
│   │   ├── title_extractor.py    # Selector/H1/Title/Og/UrlSlug title blocks + _title_from_url
│   │   ├── navigator.py          # Next URL finding
│   │   └── validator.py          # ProseRichness, junk detection
│   ├── core/
│   │   ├── scraper.py            # run_novel_task orchestrator
│   │   ├── orchestrator.py       # Input-type routing orchestrator (EPUB / TXT)
│   │   ├── session_pool.py       # DomainSessionPool (per-host Semaphore), PlaywrightPool
│   │   ├── html_filter.py        # prepare_soup (3-layer defense)
│   │   ├── formatter.py          # MarkdownFormatter (with img handling)
│   │   └── image_pipeline/       # Image fetch strategies
│   │       ├── base.py           # ImageFetchStrategy ABC
│   │       ├── web_fetcher.py    # WebImageFetcher (HTTP qua DomainSessionPool)
│   │       └── epub_extractor.py # EpubImageExtractor (binary từ zip)
│   ├── learning/
│   │   ├── phase.py              # Learning phase + CalibrationPhase + _discover_content_selector
│   │   ├── phase_ai.py           # 8 AI calls sequenced
│   │   ├── profile_manager.py    # SiteProfile load/save
│   │   └── naming.py             # Story name + chapter pattern detection
│   ├── ingest/                   # Input adapters
│   │   ├── types.py              # RawDocument DTO
│   │   ├── epub.py               # ebooklib parser + structure plan
│   │   ├── epub_structure.py     # TOC / spine / divider merge heuristics
│   │   ├── txt.py                # Chapter boundary detection (VN+EN)
│   │   └── router.py             # Detect input type, dispatch
│   ├── writers/                  # Output writer implementations
│   │   ├── base.py               # ChapterWriter ABC
│   │   ├── factory.py            # build_writer() central dispatch
│   │   ├── obsidian.py           # ObsidianWriter
│   │   ├── translation.py        # TranslationWriter
│   │   ├── raw.py                # RawWriter
│   │   └── nav_injector.py       # 0000_Index.md + prev/next link injection
│   └── utils/
│       ├── types.py              # SiteProfile, ProgressDict, FormattingRules TypedDicts
│       ├── string_helpers.py     # normalize, slugify, strip_site_suffix
│       ├── ads_filter.py         # AdsFilter with atomic save
│       ├── content_cleaner.py    # 5-pass post-extraction cleaning
│       ├── image_url.py          # resolve_image_url helper
│       ├── file_io.py            # load/save profiles, ensure dirs
│       └── issue_reporter.py     # Session issue log
├── tools/
│   ├── snapshot_baseline.py      # Capture baseline output for regression diff
│   └── bulk_relearn.py           # Bulk delete profiles
├── data/
│   ├── site_profiles.json
│   ├── ads_keywords.json
│   ├── txt_cases.json
│   └── baselines/
├── Vault/                        # In-repo Obsidian Vault output & _Scraper runtime
└── docs/
    ├── BLUEPRINT.md              # Architecture & design reference (this file)
    ├── ROADMAP.md                # Summary of completed Phases 0–6 & releases
    ├── V1_1_BACKLOG.md           # Open bugs & deferred features
    ├── TROUBLESHOOTING.md        # User runbook
    └── CHANGELOG.md              # Version history
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
    download_images      : bool          # v1.0: site có ảnh đáng tải không
    image_selector       : str | None    # v1.0: nếu site có wrapper riêng cho illustration
```

### FormattingRules (explicit schema)

```python
class FormattingRules(TypedDict, total=False):
    headings_as_h2       : bool     # h1/h2/h3 trong content → "##" thay vì cấu trúc gốc
    preserve_bold        : bool     # <b>/<strong> → "**text**"
    preserve_italic      : bool     # <i>/<em> → "*text*"
    preserve_blockquote  : bool     # <blockquote> → "> text"
    paragraph_separator  : str      # "\n\n" default
    list_style           : Literal["dash", "asterisk"]  # "- " hoặc "* "
    image_alt_strategy   : Literal["preserve", "skip", "fallback_to_filename"]
    strip_inline_links   : bool     # <a> → text only (novel rare meaningful link)
    strip_html_comments  : bool     # luôn True
    text_encoding        : str      # "utf-8" default
```

### RunConfig (per-run, transient)

```python
@dataclass
class RunConfig:
    output_mode      : Literal["obsidian", "translate", "raw"]
    download_images  : bool
    image_placeholder: bool
    fetch_metadata   : bool
    output_dir       : str
    max_pw_instances : int = 2
    fast_learning    : bool = False
    no_validation    : bool = False
```

### CleanedChapter & ImageRef (pipeline → writer contract)

```python
@dataclass
class CleanedChapter:
    index           : int
    title           : str
    body_markdown   : str
    images          : list[ImageRef]
    source_url      : str | None
    source_path     : str | None
    metadata        : dict

@dataclass
class ImageRef:
    original_url    : str
    local_path      : str | None
    alt_text        : str
    position_marker : str
    source_type     : Literal["web", "epub"]
```

---

## 9. Learning Phase (8 AI Calls + Naming + Calibration)

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
  AI#7 — Ch.8:   Ads & watermark deep scan + detect image policy

Phase 4 — Synthesis & Calibration:
  AI#8 — Master profile synthesis from all previous results
  Calibration — 3-dim probe on sample HTML; auto fallback to _discover_content_selector if AI selector misses

POST-LEARNING:
  Naming Phase: Story name extraction, chapter pattern regex, language detection
```

---

## 10. Roadmap Summary (All v1.0 Phases Shipped)

Toàn bộ 7 Phase của v1.0 (Phase 0 Cleanup → Phase 1 Output Abstraction → Phase 2 Image Support → Phase 3 EPUB Adapter → Phase 4 Translation/Raw Writers → Phase 5 TXT Adapter → Phase 6 Final Cleanup & Docs) và các bản vá đến v1.2.1 đã hoàn thành.
- Xem bảng tóm tắt kết quả từng Phase tại **[`docs/ROADMAP.md`](ROADMAP.md)**.
- Xem danh sách các vấn đề còn mở (§7.3 Large EPUB, §7.4 Webnovel UI noise, §7.5 RoyalRoad `<style>`-hidden watermark, P1 Baseline, P4 FlowSpec) tại **[`docs/V1_1_BACKLOG.md`](V1_1_BACKLOG.md)**.

---

## 11. Decision Log (Core Architectural Decisions)

| # | Decision | Choice | Rationale |
|---|---|---|---|
| 1 | Scope v1.0 | Universal novel normalizer (web đa site / EPUB / TXT), 3 output modes | Đa dụng + decompose file nén |
| 2 | Architecture | 2-phase learning (per domain) + Lego blocks | Khấu hao AI cost, composable |
| 6 | Output strategy | 3 mode chọn tại runtime (`obsidian`, `translate`, `raw`) | Mỗi mode có constraint riêng |
| 7 | Image policy | Per-mode (`obsidian`: download, `translate`: placeholder, `raw`: strip) | Tiết kiệm bandwidth + thời gian |
| 8 | Input adapter shape | Mọi adapter produce `RawDocument` (`ingest/types.py`) | Decoupling input từ pipeline core |
| 17 | Phase ordering | Output Abstraction (Phase 1) TRƯỚC Image Support (Phase 2) | Image policy cần `RunConfig` và `CleanedChapter` trước |
| 18 | Baseline regression | `tools/snapshot_baseline.py` + `data/baselines/` | Regression guard trước khi refactor hành vi |
| 19 | Image fetch strategy | Strategy pattern: `WebImageFetcher` vs `EpubImageExtractor` | Cùng interface `ImageFetchStrategy.fetch()` |
| 20 | TXT scope v1.0 | Vietnamese + English chapter pattern only | CJK defer sang `V1_1_BACKLOG.md` §3.1–3.2 |
| 22 | EPUB naming source | Dublin Core metadata first, AI fallback nếu trống | Tiết kiệm AI call |
| 57 | Per-host concurrency cap | `PER_HOST_MAX_CONCURRENCY=3` semaphore trong `DomainSessionPool` | Safety-by-default chống bị ban IP |

*(Full 57-entry Decision Log maintained in [`CLAUDE.md`](../CLAUDE.md) §17).*

---

## 12. Open Questions (Resolved in Phases 1–5)

Toàn bộ các câu hỏi thiết kế ban đầu đã được chốt và triển khai:
- **TXT case database schema**: Lưu raw regex kèm metadata trong `data/txt_cases.json` (`Decision #51–52`).
- **Image download retry policy**: 2 lần retry, backoff 1s/3s, fail-soft giữ placeholder (`Decision #34`).
- **Obsidian frontmatter**: Giữ minimal (`title`, `source`, `chapter_index`, `source_url`, `failed_images` khi có lỗi — `Decision #32`).
- **Chunking trong `TranslationWriter`**: Mặc định tắt (`CHUNK_THRESHOLD = 0`), giữ 1 file/chương vì LLM hiện đại có context lớn (`Decision #45`).
- **EPUB không có TOC / cấu trúc phẳng**: Đã xử lý bằng body fallback (`Decision #40`) và tách theo TXT pattern khi thiếu TOC (`b4944d2`).

---

## 13. Versioning

| Version | Date | Change |
|---|---|---|
| 1.0 | 2026-05-15 | Initial vision + architecture |
| 1.1 | 2026-05-16 | Phase ordering fix, Strategy pattern cho image fetch, explicit schemas |
| 1.2 | 2026-05-17 | v1.0.0 SHIPPED (all Phases 0–6 complete) |
| **1.2.1** | **2026-11-09** | **Production hardening (v1.0.13 → v1.2.1): Multi-key Gemini pool, Calibration phase, per-host concurrency cap, anti-hallucination selector discovery, `MAX_EMPTY_STREAK` restore, RoyalRoad `slug_increment` loop fix.** |

---

**END BLUEPRINT v1.2.1**
