# Changelog

All notable changes to Cào Text. Format based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), versioning per [Semantic Versioning](https://semver.org/).

---

## [1.0.16] — 2026-05-17

EPUB analyzer Tier 1 + Tier 2 (config-selectable). Default Tier 2 (AI), fallback Tier 1 on AI failure.

### Tier 1 enhancements (rule-based, no AI)
- **`src/ingest/epub_structure.py::SKIP_KEYWORDS`** (NEW): `extract from`, `excerpt from`, `also by`, `praise for`, `advert`, `out now`, etc. Promo/excerpt cho TRUYỆN KHÁC → kind=`skip`, KHÔNG ghi file.
- **`SKIP_FILENAME_PATTERNS`**: `advert`, `ads_`, `promo`, `excerpt`. Catch promo files khi TOC missing.
- **`smart_title_from_toc(toc_title, idx)`**: convert TOC label thông minh:
  - `"0000"` → `"Prologue"`
  - `"0001"`..`"0099"` (numeric) → `"Chapter N"` (strip leading zeros)
  - Non-numeric → keep as-is
- **`ChapterPlan.kind`** thêm `"skip"` value (chưa yield, không ghi file).
- **Test RPO**: 43 chapters + 9 matter + 4 skipped (ads_front, advert, advert_text, ads_back). Trước: 47KB Front Matter chứa Armada excerpt. Sau: 4 promo docs gone, Front Matter chỉ ~17KB Contents+About+Dedication+Acknowledgments+Copyright.

### Tier 2 — AI analyzer
- **`src/ai/prompts.py::analyze_epub_structure(docs_meta_json)`**: prompt cho AI classify mỗi spine doc (chapter/frontmatter/backmatter/divider/skip) + suggest title + detect merge continuation.
- **`src/ai/agents.py::ai_analyze_epub_structure(docs_meta, limiter)`**: 1 call/EPUB, validate output covers all input doc_ids.
- **`src/ai/agents.py::_S_EPUB_STRUCTURE`**: response schema.
- **`src/ingest/epub_structure.py::build_chapter_plan_with_ai(book, path, ai_limiter)`**: cache lookup → AI call → apply decisions → cache write. SHA256 of EPUB file = cache key.
- **Cache**: `data/epub_analyses.json` — re-process cùng file = 0 AI cost.
- **Doc metadata gathered**: doc_id, name, spine_pos, toc_title, size_bytes, first_300_chars, first_h1, first_h2 (BS4 parse per doc).

### Config (selectable)
- **`config.toml.example`** thêm:
  ```toml
  [epub]
  analyzer = "ai"     # "ai" (default) | "rules"
  ```
- **`src/core/orchestrator.py::run_epub_flow`** đọc `_cfg._get("epub", "analyzer", "ai")` dispatch:
  - `"ai"` + có ai_limiter → `build_chapter_plan_with_ai` (Tier 2)
  - `"rules"` hoặc Tier 2 fail → `build_chapter_plan` (Tier 1)
- **`src/ingest/epub.py::ingest_epub(path, plan=None)`**: accept optional pre-built plan. Backward-compat default = Tier 1.

### Fallback chain
```
Tier 2 (AI)
  ├─ Cache hit → use cached decisions
  ├─ AI call success → cache + apply
  └─ AI fail → log warn → Tier 1
       └─ Always works (deterministic rules)
```

### Verified
- Compile clean: ai/prompts, ai/agents, ingest/epub_structure, ingest/epub, core/orchestrator.
- Tier 1 plan on RPO: 43 chapters + 9 matter + 4 skipped (Armada excerpt gone). Titles: Prologue, Level One, Chapter 1-39, Level Two, Chapter 17-27, Level Three, Chapter 28-39.
- Doc metadata gather: 56 docs from RPO with proper h1/h2/text snippets.

---

## [1.0.15] — 2026-05-17

EPUB matter merge fix — body inner extraction. Previous v1.0.14 merged full HTML docs with `<hr/>`, producing multiple `<body>` tags. `soup.find('body')` returned only first (often empty) → formatter output 0 bytes → cleaned content empty → italic emphasis appeared split (text leak from prior runs).

### Fix
- **`src/ingest/epub.py::ingest_epub`**: parse each doc's `<body>`, extract inner children only, then wrap merged inner content in single `<html><body>...</body></html>`. Single body tag → formatter sees all content.
- Empty body chunks (e.g. titlepage with only whitespace) skipped.

### Verified
- RPO matter merged HTML: 1 `<body>` tag (was 13).
- Formatter output: 29KB / 220 newlines (was 0 bytes).
- Italic `*not*` preserved inline (was split across lines).
- Cleaned newlines stable end-to-end.

---

## [1.0.14] — 2026-05-17

EPUB chapter planner — TOC-driven structure analysis (Step 1, no AI). Front + back matter docs merge into `0000_Front_Matter.md`. Real chapters use TOC title hint.

### Added
- **`src/ingest/epub_structure.py`** (NEW): `build_chapter_plan(book)` reads EPUB TOC (`book.toc`) recursive, normalizes hrefs, classifies each spine doc:
  - TOC entry matches FRONT_MATTER_KEYWORDS (`contents`, `cover`, `dedication`, `about`, `title page`, ...) → matter bucket.
  - TOC entry matches BACK_MATTER_KEYWORDS (`acknowledg`, `copyright`, `excerpt`, `advert`, ...) → matter bucket.
  - Filename matches MATTER_FILENAME_PATTERNS → matter bucket (covers EPUBs missing TOC).
  - TOC chapter entry → new chapter, use TOC title as hint.
  - Spine doc NOT in TOC, current chapter open → continuation (merge with prev chapter).
- **`src/ingest/epub.py`** rewrite: yields `RawDocument` per `ChapterPlan` entry. Multi-doc chapters concat with `<hr/>` separator. `metadata['kind']` = `"chapter"` or `"matter"`. `metadata['toc_title']` set if TOC matched.
- **`src/core/orchestrator.py::_build_chapter_from_epub_doc`** title resolution priority:
  1. `kind == matter` → "Front Matter" (deterministic)
  2. Non-numeric TOC title → use directly (handles "Prologue", "Level One", etc)
  3. Title chain (H1/H2)
  4. Numeric TOC ("0001") → `Chapter N` with TOC label stripped of leading zeros
  5. Default `Chapter N`

### Result (Ready Player One test)
**Before (v1.0.13)**: 39 spine docs each as separate "chapter" file, front matter (Contents, About, Dedication) mixed in with real chapters, garbage titles.

**After (v1.0.14)**:
```
output/Ready_Player_One/
├── 0000_Front_Matter.md   ← 13 front+back matter docs merged
├── 0001_Chapter1.md        ← Prologue (TOC label "0000" stripped, fallback Chapter 1)
├── 0002_Level_One.md       ← Part divider
├── 0003_Chapter1.md        ← Chapter 1 (TOC "0001")
...
└── 0043_Chapter39.md       ← Chapter 39 (TOC "0039")
```
44 entries total (1 matter + 43 real). Down from 50+ confused entries.

### Verified
- Planner correctly classifies 13 matter docs (Contents, About×2, Title Page, Dedication, Acknowledgments, Copyright, Extract from ARMADA, etc) into single bucket.
- Real chapters preserve original spine order including part dividers.
- TOC parse handles recursive sections (`Level One` → children `0001`..`0016`).
- Filename: index=0 + "Front Matter" → `0000_Front_Matter.md` ✓.

### Not yet (Step 2, defer)
- AI to clean ambiguous TOC entries.
- Numeric TOC label → smart title extraction from chapter h1.
- Separate front vs back matter files (user wanted gộp 1 file, kept simple).
- EPUB progress/resume (Ctrl+C still loses work).

---

## [1.0.13] — 2026-05-17

EPUB scrape — 3 critical bugs fixed.

### Bug 1: Title = full Windows file path
**Symptom**: EPUB chapter file `0005_UsersFpt_Mong_CaiDesktopSmall_ProjectCào_TextInputEpubReady_Player_One.Epub.md` — title was full file path slugified.
**Cause**: orchestrator sets `ctx.url = doc.source_path` (file path). Title chain falls through all blocks. `UrlSlugTitleBlock._title_from_url()` doesn't validate URL scheme → treats Windows path as URL → extracts whole path as title.
**Fix**: `src/pipeline/title_extractor.py::_title_from_url` validates `urlparse(url).scheme in ("http", "https")` — returns None for file paths. Title chain falls through to orchestrator's `f"Chapter {doc.chapter_index}"` default.

### Bug 2: All paragraphs joined into one giant line
**Symptom**: EPUB chapter body = 5KB+ single line, no paragraph breaks. Obsidian renders as wall of text.
**Cause**: `src/utils/content_cleaner.py::_strip_unicode_blank_lines` drops ALL whitespace-only lines via `_UNICODE_BLANK_LINE_RE` (matches both Unicode blanks AND empty `""` ASCII lines). Markdown paragraph break = blank line between paragraphs. Stripping = collapses `\n\n` → `\n` everywhere.
**Fix**: skip strip if line is empty (`""`). Only drop lines with ≥1 char (true Unicode blank like U+2800 braille). Verified: 112 newlines preserved end-to-end (was 56).

### Bug 3: EPUB image relative path not resolved
**Symptom**: `[EpubImageExtractor] href not found: ../images/img19.jpg`. Images fall to fallback URL → broken in Obsidian.
**Cause**: `EpubImageExtractor.fetch` tries `OEBPS/` prefix variants but EPUB uses `OPS/` (RPO case). No path normalization for `..`. No basename fallback.
**Fix**: added `OPS/` variants + `posixpath.normpath()` + basename fallback (scan all `ITEM_IMAGE` for matching filename). Verified: `../images/img19.jpg` → 6190 bytes fetched.

### Verified
- `_title_from_url` rejects Windows path → no more garbage titles.
- Prologue chapter: 112 newlines preserved (was 56). Paragraph breaks intact.
- Image extractor handles `../images/foo.jpg` reliably.

---

## [1.0.12] — 2026-05-17

Obsidian TOC + top/bottom nav. Each story folder gets `0000_Index.md` listing all chapters. Each chapter file gets nav at top AND bottom: `[← Prev] | [🏠 Index] | [Next →]`.

### Added
- **`src/writers/nav_injector.py::build_index_content`**: generate TOC file at `output/{story}/0000_Index.md`. Format:
  ```markdown
  # {story_name}

  > [!abstract] Story Info
  > - **Chapters**: 15
  > - **Source**: royalroad.com
  > - **Last updated**: 2026-05-17

  ## Chapters

  1. [Chapter 2 – Gathering moss](0001_Gathering_moss.md)
  ...
  ```
  Naming `0000_` ensures Index sorts FIRST in folder (before any `0001_..0999_` chapter). User opens story folder → sees Index → clicks chapter.
- **`inject_nav_and_index(output_dir, story_name)`**: replaces `inject_nav_links` (kept as alias for back-compat). Returns `(chapters_updated, index_written)`. Reads chapter titles + source URL from frontmatter for TOC.
- Each chapter nav now has 3 links: `[← Prev]`, `[🏠 Index](0000_Index.md)`, `[Next → ]`. First chapter omits Prev. Last chapter omits Next.

### Changed
- Nav now injected at BOTH top (after frontmatter) AND bottom (after content + `---` HR). Reader can navigate from start or end of chapter without scrolling.
- Wire updated in `src/core/scraper.py` + `src/core/orchestrator.py`: pass `story_name` from progress / DC metadata.

### Robustness
- `_inject_chapter_nav` rewrites file deterministically: strip all nav blocks → extract FM → reassemble in canonical layout. Recovers from corrupt prior state (missing newlines, nav at wrong position from earlier bugs).
- Idempotent: 2nd+ run on stable file returns `(0, False)` — no churn.
- Stale legacy v1.0.11 `<!-- nav-links -->` markers stripped on migration.

### Reading flow
```
Mở folder → 0000_Index.md (TOC)
         ↓ click chapter
    đọc chapter
    ┌─────────────────┐
    ↓                 ↓
Next chapter    🏠 Back to Index
```

### Verified
- Live test 15-chapter RR story: Index generated, all 15 chapters get top + bottom nav, mid chapter has 3 links (Prev + Index + Next), first/last have 2 links.
- Recovery: previously corrupt file with `---# Chapter` (missing newline) auto-fixed to canonical format.
- Idempotent: Run A applies fix, Run B stabilizes, Run C+ unchanged.

---

## [1.0.11] — 2026-05-17

Obsidian reader polish — status box callout, broken bold fix, prev/next chapter nav links.

### Added
- **`src/utils/content_cleaner.py::_wrap_status_blocks`** (Pass 7): detect 3+ consecutive LitRPG status lines (`**HP**: 144/144`, `**Level**: 11`, etc) and wrap in Obsidian callout `> [!info]+ Status`. Three patterns covered: `**X:**value` (colon inside), `**X**: value` (colon outside), `**X**` (label only). Max line length 160 to avoid false positive on prose. Blank lines inside cluster tolerated.
- **`src/utils/content_cleaner.py::_fix_broken_bold`** (Pass 6): repair `**X: **Y` (trailing whitespace inside bold span — invalid CommonMark, renders as raw asterisks in Obsidian) → `**X:** Y`. Uses `[ \t]+` not `\s+` to avoid cross-line greedy match.
- **`src/writers/nav_injector.py`** (NEW): post-process output dir, append prev/next chapter footer to each `.md` file. Markers `<!-- nav-links -->...<!-- /nav-links -->` enable idempotent regenerate. First chapter: only Next →. Last chapter: only ← Prev. Mid chapters: both.
- **`src/core/scraper.py::run_novel_task`**: call `inject_nav_links` after pm.flush() (Obsidian writer only).
- **`src/core/orchestrator.py::run_epub_flow`**: same call after EPUB scrape done.

### Examples
**Before** (raw RR status box bleeding bold markers):
```
**HP**: 144/144
**Mana**: 0/0
**Level**: 11
**Energy Level (E): **10 000 MW
```

**After**:
```markdown
> [!info]+ Status
> **HP:** 144/144
> **Mana:** 0/0
> **Level:** 11
> **Energy Level (E):** 10 000 MW
```

**Nav footer appended to each chapter**:
```markdown
---
<!-- nav-links -->
[← 0004_Stone_Cold_Killer](0004_Stone_Cold_Killer.md) | [0006_Yes_Hard_Feelings →](0006_Yes_Hard_Feelings.md)
<!-- /nav-links -->
```

### Verified
- Status block detection: cluster size ≥3, false-positive guard via 160-char line length cap.
- Broken bold regex: line-bounded (`[ \t]` not `\s`) — fixed cross-line greedy bug discovered smoke test.
- Nav injector idempotent: run twice → 2nd run returns 0 updated (no churn).
- Live test on existing `output/Rock_falls,_everyone_dies/` (15 chapters): 15 files linked correctly, first/last chapter directional, mid chapters bidirectional.

---

## [1.0.10] — 2026-05-17

Root tidy — internal-only docs moved to `docs/`, user inputs consolidated under `input/`.

### Layout
```
Cào text/
├── main.py                ← entry
├── .env                   ← API keys
├── config.toml            ← user knobs (optional)
├── config.toml.example    ← template
├── README.md              ← stays root (GitHub convention)
├── CHANGELOG.md           ← stays root (convention)
├── CLAUDE.md              ← stays root (Claude Code auto-load)
├── issues.md              ← runtime log (gitignored)
├── requirements.txt
├── input/                 ← all user inputs (NEW)
│   ├── links.txt          ← web URLs
│   └── epub/              ← drop .epub here
├── data/ output/ progress/  ← runtime state
├── docs/                  ← all internal docs
│   ├── BLUEPRINT.md       ← moved from root
│   ├── ROADMAP.md         ← moved from root
│   └── ... (existing)
└── src/                   ← code (v1.0.8)
```

### Changed
- `git mv BLUEPRINT.md ROADMAP.md docs/` — repo organization.
- `mv links.txt → input/links.txt`, `mv input_epub/ → input/epub/` (untracked, gitignored).
- **`src/utils/epub_inbox.py`**: `INBOX_DIR = os.path.join("input", "epub")`.
- **`main.py`**: argparse `links_file` default `"links.txt"` → `os.path.join("input", "links.txt")`.
- **`.gitignore`**: `input_epub/` → `input/epub/`, `links.txt` → `input/links.txt`.

### Kept at root (convention)
- `README.md` — GitHub renders on repo page.
- `CHANGELOG.md` — Keep-a-Changelog convention.
- `CLAUDE.md` — Claude Code auto-loads from root; moving = lose auto-context.

### Migration note
- Old `links.txt` at root → move to `input/links.txt`.
- Old `input_epub/*.epub` → move to `input/epub/`.
- Manifest `data/processed_epubs.json` unchanged (hash-keyed, location-agnostic).

### Verified
- `python main.py --version` → 1.0.10.
- `INBOX_DIR` resolves `input/epub`, exists=True.
- `scan_inbox()` works post-move.

---

## [1.0.9] — 2026-05-17

Fix html_filter cascade crash — Layer 1b/1c watermark filters silently bypassed since v1.0.4. RR (+ other sites with nested obfuscated-class wrappers) watermarks leaked into output.

### Root cause
`_strip_obfuscated_class_elements` iterates `soup.find_all(True)` snapshot. When ancestor `<span class="cjBiZWI1...">` decomposed, descendants in snapshot list lose `attrs` (BS4 4.12+ clears them). Next iteration: `el.get("class")` → `self.attrs.get(...)` → `'NoneType' object has no attribute 'get'`. Exception propagates to `prepare_soup`, caught by executor's `except Exception` → `[Executor] html_filter thất bại, dùng raw parse` → ALL layers (1b/1c/2/3) silently skipped → watermarks leak to content.

Observed in v1.0.5 RR scrape: every chapter logged `html_filter thất bại`, then watermark variants ("Unauthorized reproduction...", "this story has been taken without approval...") leaked despite Layer 1c being designed to catch them.

### Fix
- **`src/core/html_filter.py::_is_alive(el)`** (NEW helper): returns False if `el is None`, `el.attrs is None`, OR `el.parent is None` (excluding soup root). Used as defensive guard before any `.get()`/`.has_attr()`/`.decompose()` call.
- **Layer 1b** `_strip_obfuscated_class_elements`: snapshot via `list(...)` + `_is_alive` guard per iteration.
- **Layer 1c** `_strip_invisible_elements`: existing `parent is None` guard replaced with `_is_alive` (catches edge cases where parent linked but attrs cleared).
- **Layer 2** KNOWN_NOISE selector loop: `_is_alive` guard before decompose (skip double-strip cascade).
- **Layer 3** profile remove_selectors loop: `_is_alive` guard before protected check (skip already-stripped descendants).

### Verified
- Repro test (nested obfuscated `<span>` wrapping `display:none` + `.sr-only`): SUCCESS, no crash, watermarks stripped, real prose preserved.
- Compile pass.

### Impact
v1.0.4 visibility filter + v1.0.3 obfuscated-class filter now **actually run** in production. Profile remove_selectors finally take effect on sites that triggered cascade (every RR scrape since v1.0.4 was running unfiltered).

---

## [1.0.8] — 2026-05-17

Code consolidation — all source moved into `src/`. User-editable folders (`data/`, `output/`, `progress/`, `input_epub/`, `docs/`) + entry (`main.py`) + user files (`.env`, `config.toml`, `links.txt`) stay at root. Goal: user touches root only; never touches `src/`.

### Layout
```
Cào text/
├── main.py              ← entry (thin sys.path shim → src/)
├── .env                 ← API keys (user)
├── config.toml          ← user behavior knobs (optional, copy from .example)
├── config.toml.example  ← template (committed)
├── links.txt            ← user URLs (web mode)
├── input_epub/          ← drop .epub here
├── data/                ← profiles, ads, cache, manifests (auto-managed)
├── output/              ← scraped chapters (user reads)
├── progress/            ← resume state (auto-managed)
├── docs/                ← docs
├── CHANGELOG.md, README.md, CLAUDE.md, BLUEPRINT.md, ROADMAP.md
└── src/                 ← ALL CODE — KHÔNG động vào
    ├── config.py
    ├── ai/ core/ ingest/ learning/ pipeline/ utils/ writers/ tools/
```

### Changed
- `git mv ai/ core/ ingest/ learning/ pipeline/ utils/ writers/ tools/ config.py src/` — history preserved.
- **`main.py`**: prepend `sys.path.insert(0, ".../src")` BEFORE any internal import. Existing `from config import ...`, `from ai.client import ...` resolve transparently — zero import-string changes in `main.py` or any moved module.
- **`src/config.py`**: `_PROJECT_ROOT = Path(__file__).resolve().parent.parent` — `.env` + `config.toml` resolve from root (one level above `src/`).
- **`src/ingest/txt.py`**: `_TXT_CASES_PATH` uses `.parent.parent.parent` (src/ingest/.. = src, .. = root).
- **`src/tools/snapshot_baseline.py`**: existing `sys.path.insert(0, parent.parent)` still correct (parent.parent = src/ post-move).

### Verified
- Compile + import: all 9 subpackages + `config.py` import clean.
- `_TXT_CASES_PATH` resolves to root/data/txt_cases.json (exists=True).
- `_TOML_PATH` resolves to root/config.toml.
- `ObsidianWriter` factory + `scan_inbox()` work post-move.
- `python main.py --version` → 1.0.8.
- `python main.py --help` lists all flags.

### Migration note
No user action needed if running `python main.py` from project root (which is the only documented invocation). Hardcoded paths to internal modules in external tooling would break — none known.

---

## [1.0.7] — 2026-05-17

User config file — `config.toml` cho tuning behavior không cần sửa code. Python 3.11+ stdlib `tomllib`, không thêm dep.

### Added
- **`config.toml.example`** (NEW, committed): template với comments giải thích từng knob. User copy → `config.toml`, chỉnh thoải mái.
- **`config.py`**: load `config.toml` ở top via `tomllib`. Tunable constants (`MAX_CHAPTERS`, `LEARNING_CHAPTERS`, `AI_MAX_RPM`, `JS_CONTENT_RATIO`, paths, ...) đọc qua helper `_get(section, key, default)`.
- **`main.py::_build_arg_parser`**: `--output-mode` + `--output-dir` defaults pull từ `[output]` section của TOML (CLI flag vẫn override).
- **`.gitignore`**: `config.toml` (per-user, không commit).

### Priority order
```
CLI flag (--output-mode, --max-pw-instances, ...) > config.toml > code default
```
`.env` vẫn giữ API key/secret riêng. `config.toml` chỉ chứa behavior knobs.

### TOML sections
- `[output]` — mode, dir, download_images
- `[scraper]` — max_chapters, errors/timeouts, playwright_concurrency, init_stagger, backoff
- `[learning]` — chapters, profile_max_age_days, ai_calls, thresholds
- `[ai]` — max_rpm, jitter
- `[http]` — request_timeout
- `[js_detection]` — content_ratio, min_diff_chars
- `[paths]` — data_dir, output_dir, progress_dir

### Verified
- Missing `config.toml` → silent fallback, behavior unchanged.
- Malformed TOML → warn + use defaults (no crash).
- Compile pass.

---

## [1.0.6] — 2026-05-17

EPUB inbox — drop-folder UX for batch EPUB processing. User drops `.epub` files in `input_epub/`, runs `python main.py` (no flags), program auto-processes new files + skips already-done. No CLI changes needed.

### Added
- **`utils/epub_inbox.py`** (NEW): `scan_inbox()` walks `input_epub/*.epub`, compares against SHA256 manifest (`data/processed_epubs.json`). Returns `(todo, skipped)`. `mark_processed()` writes manifest entry after successful run.
- **`main.py::_run_epub_inbox()`**: helper invoked before web flow. Silent no-op if inbox empty. Process each new EPUB via `run_epub_flow`. Mark hash → manifest only AFTER successful flow (fail mid-process = retry next run).
- **`core/orchestrator.py::run_epub_flow`**: return type `None → int` (chapter count). Backward-compatible additive change; only caller (`main.py`) consumes new return.
- **`.gitignore`**: `input_epub/` added.

### Skip semantics
- Same hash → skip (rename file = idempotent — hash unchanged)
- Different hash, same name → process (file edited / replaced)
- Hash missing from manifest → process

### Verified
- Empty inbox + valid `links.txt` → web flow unchanged, no inbox print.
- Empty inbox + missing `links.txt` → exits with error (existing behavior preserved).
- Compile check passes: `main.py`, `utils/epub_inbox.py`, `core/orchestrator.py`.

### UX
```bash
mkdir input_epub  # auto-created lần đầu chạy
mv ~/Downloads/*.epub input_epub/
python main.py    # processes new + skips done
```

---

## [1.0.5] — 2026-05-17

Phase 0 — Upfront URL classifier. User paste any URL (index page, story root, chapter), scraper auto-classifies + redirects to chapter 1 if needed. Detects language for multi-language support hook (en/vi/zh/ja/ko/ru/other).

### Added
- **`ai/agents.py::ai_classify_input_url`** + **`_S_INPUT_CLASSIFY`** schema: 1 AI call classifies user URL into `chapter`/`index`/`story_root`/`unknown`. Returns `page_type`, `language`, `language_iso`, `first_chapter_url`, `story_name`, `chapter_keyword`, `chapter_count_estimate`, `confidence`.
- **`ai/prompts.py::classify_input_url`**: prompt instructs detection of page type + language + chapter keyword in target language ("Chapter"/"Chương"/"第N章"/"Глава"/"제N장"/...). Passes REAL extracted chapter link candidates to AI.
- **`utils/url_classifier.py`** (NEW): cache + AI dispatch + `resolve_to_chapter_url()` helper. Cache file `data/url_classifications.json`. Cache hit policy: skip AI if confidence ≥ 0.7.
- **`main.py` Phase 0**: classifies all input URLs upfront, redirects index/story_root → first_chapter_url before passing to learning + scrape phases.

### Anti-hallucination guard
First test revealed AI invented fake chapter URL (`chapter/929457/...` for "Rock falls" → 404 → redirected to different story "Obscurity"). Fix: `_chapter_links()` extracts REAL `<a href>` chapter links from HTML and passes top 30 as candidates in prompt. AI must pick from list, can't invent. If AI returns URL not in candidates → fallback to first extracted link.

### Multi-language support
Classifier detects `language` + `chapter_keyword` for any language Gemini understands (en/vi/zh/ja/ko/ru/other). Profile/Naming phase can consume these fields in future v1.1 work for filename / regex localization. v1.0.5 ships detection only — downstream regex/filename uses still EN/VN as before.

### Verified
- Index URL `https://www.royalroad.com/fiction/55418/rock-falls-everyone-dies` → AI classified `page_type="index"`, `language="en"`, redirected to real chapter 1 (`chapter/1083016/...`), 18 chapters scraped successfully.
- Cache hit on second run: 0 AI calls, instant redirect from cached data.
- Story name correct ("Rock falls, everyone dies"), not hallucinated wrong story.

### CLI behavior change
New Phase 0 stage prints `🧭 Phase 0: Classify N URL...` before Phase 1 learning. ~5-10s per new URL (1 fetch + 1 AI call). Subsequent runs use cache → no overhead.

### Bumped
- `VERSION = "1.0.5"`.

---

## [1.0.4] — 2026-05-17

Generalized hidden-element strip. Implements user-stated principle: "only scrape what visible to normal users".

### Discovery
v1.0.3 missed ch.9 of RR Rock falls: watermark variant "Unauthorized reproduction: this story has been taken without approval. Report sightings." — contained no "amazon" or "royal road" keywords (text-level regex misses) AND wasn't wrapped in 40+ char obfuscated class (Layer 1b misses). Likely wrapped in `display:none` / `aria-hidden` / `sr-only` instead.

### Fixed
- **VISIBILITY-FILTER** (`core/html_filter.py::_strip_invisible_elements`, new Layer 1c in `prepare_soup()`): Strips elements not visible to normal users. 4 detection techniques:
  1. `hidden` HTML5 boolean attribute → strip
  2. `aria-hidden="true"` attribute → strip
  3. Inline style: `display:none`, `visibility:hidden`, `opacity:0(.0)`, `font-size:0`, off-screen position (`left/right/top/bottom: -9999px+`), `clip:rect(0,0,0,0)`, `transform:scale(0)` → strip
  4. Semantic hidden class names (exact match, lowercased): `sr-only`, `visually-hidden`, `screen-reader-only`, `screen-reader-text`, `d-none`, `hidden`, `invisible`, `hide`, `is-hidden`, `u-hidden`, `js-hidden`, `hidden-text`, `hide-text`, `off-screen`, `offscreen`, `no-display`, `nodisplay`, `aria-hidden` → strip

### Why generalized over per-site
Catches anti-piracy watermarks across ALL sites using ANY of these standard hiding techniques. Site-agnostic. Per-site enumeration would never finish.

### Limitation
CSS-rule-defined `.foo { display:none }` requires browser computed style → needs Playwright (out of scope for HTML-only filter). Cross-chapter learning (AdsFilter) is fallback for rule-based hidden content.

### Verified
- Synthetic adversarial test: 14/14 hidden elements stripped (all 4 techniques), 8/8 visible elements preserved including `aria-hidden="false"`, `opacity:0.9`, `font-size:14px`, `left:10px`, partial-match `hidden-menu` class (only exact class names hit).
- Live RR re-scrape: 19/19 chapters clean. ch.9 line 49 watermark GONE. Full sweep across all chapters for `amazon|stolen|pilfered|unauthor|misappropriat|reproduction|sightings|approval` returned 0 hits.
- Performance impact: negligible (single soup.find_all pass, in-memory only).

### Defense-in-depth layer stack
- Layer 1: `_ALWAYS_REMOVE` (script/style/noscript/iframe)
- Layer 1b: Obfuscated-class strip (40+ random alphanumeric class)
- **Layer 1c: Visibility filter** (display:none, aria-hidden, off-screen, sr-only class) ← NEW
- Layer 2: `KNOWN_NOISE_SELECTORS` global
- Layer 3: Profile `remove_selectors` per-domain
- Post-extraction: `content_cleaner` 5-pass + `AdsFilter` substring/regex

### Bumped
- `VERSION = "1.0.4"`.

---

## [1.0.3] — 2026-05-17

Hotfix release. Filter RR anti-piracy watermarks at HTML source layer instead of post-extraction text — eliminates entire FP risk class.

### Discovery
Inspected RR raw HTML for `Rock falls everyone dies` ch.8: watermark wrapped in `<span class="cjBiZWI1ZTRlZTQzODQ0ODRhMjEzNmE0MjdjNzY0MTY4">` — a **44-char random alphanumeric class** that rotates per-render. Can't hardcode the class name, but the obfuscated signature is statistically incompatible with framework classes (Bootstrap 8-15 chars readable; Tailwind utility names; CSS-in-JS hashes typically 6-12 chars).

### Fixed
- **OBFUSCATED-CLASS** (`core/html_filter.py::_strip_obfuscated_class_elements`, new Layer 1b in `prepare_soup()`): Strips any element whose ONLY class matches `^[A-Za-z0-9]{40,}$`. Catches RR anti-piracy watermarks at HTML source before text extraction — eliminates entire false-positive class because matched text never reaches `content_cleaner` / `AdsFilter`.

### Why Layer 1b (not text-level filter)
- v1.0.2 used substring + regex on extracted text → MEDIUM FP risk (e.g. "Stolen from the Amazon basin" stripped wrongly)
- Layer 1b strips at HTML source → 0 FP risk on text content
- Conservative: requires SOLE class match (`len(classes) == 1`) → real prose elements never have a 40+ char alphanumeric solo class

### Verified
- Unit test 11/11 PASS: 3 RR random classes stripped, 8 framework/short-hash classes preserved (col-md-3, container, sc-jSdvCN-abc, css-1q2x3y4z, chapter-content, etc.)
- Synthetic HTML test: watermark span stripped, prose paragraphs + framework div + short-hash div all preserved
- Live RR re-scrape: 19/19 chapters, 0 watermark leaks across content sweep, 0 FP

### Side effect
- v1.0.2 substring/regex layer still active as second-defense if HTML strip misses (e.g. site uses different obfuscation technique like inline `style="display:none"`).

### Bumped
- `VERSION = "1.0.3"`.

---

## [1.0.2] — 2026-05-17

Hotfix release. RoyalRoad anti-piracy watermark leaks + Unicode braille blank lines in extracted chapters.

### Fixed
- **ADS-RR-BUILTIN**: `AdsFilter` now pre-seeds known site-specific watermark phrases on load (per-domain `_BUILTIN_DOMAIN_WATERMARKS` dict). Strips RR boilerplate from chapter 1 without waiting for cross-chapter frequency learning.
- **ADS-RR-REGEX**: RR rotates anti-piracy watermark through ~20 phrase variants ("If you stumble upon this narrative on Amazon...", "Unlawfully taken from Royal Road...", "Pilfered from Royal Road...", etc). Whack-a-mole via substring enumeration replaced by 3 regex patterns matching `amazon` ↔ attribution-verb co-location within 80 chars (also `royal road` ↔ verb).
- **UNICODE-BLANK**: `content_cleaner.py` new Pass 0b strips lines containing only Unicode whitespace/blank chars (U+2800 braille blank used by RR for vertical spacing, NBSP, zero-width chars, U+3000 ideographic space, etc.). Inline blanks within prose preserved.

### Verified
- RR Rock falls everyone dies re-scrape: 19/19 chapters, 0 watermark leaks (`grep amazon|stolen|pilfered|unauthori[sz]ed` returned 0), 0 braille lines, all content preserved.
- Regex false-positive sanity: "The stone rolled down the mountain", "Amazon rainforest is huge", "She typed the report and sent it" — all KEPT (3/3 pass).

### Bumped
- `VERSION = "1.0.2"`.

---

## [1.0.1] — 2026-05-17

Hotfix release. Title extraction container-leak bug found in v1.0.0 post-ship via user inspection of FFN output.

### Fixed
- **TITLE-D**: `SelectorTitleBlock` rejects selectors resolving to container elements (`<select>`, `<option>`, `<nav>`, `<ul>`, `<ol>`, `<table>`, `<tbody>`). These concat ALL child text → garbled titles like `"1. Chapter 12. Chapter 23. Chapter 34..."` (entire FFN chapter dropdown).
- **TITLE-C**: All title blocks (`SelectorTitleBlock`, `H1TitleBlock`, `TitleTagBlock`, `OgTitleBlock`) reject titles >200 chars and fall through chain. Defense-in-depth against container leaks past Fix D.
- **FILENAME-F**: `format_chapter_filename()` clamps `raw_title` to 200 chars before pattern parsing. Belt-and-suspenders for cases where title chain is bypassed (progress fallback path).
- **AI prompts** (AI#1 / AI#2 / AI#5 title): explicit forbidden-element list. AI now instructed to never pick `<select>`, `<option>`, `<nav>`, `<ul>`, `<ol>`, `<table>`, `<tbody>` for `chapter_title_selector`. Return `null` if no clean element exists — fallback chain (H1/title/og/url_slug) safer than container leak.

### Verified
- FFN (`Monster? No, I'm a Cultivator!`) re-learn after fix: AI picked `title_selector: 'b'` (NOT `<select>`). 75 chapters scraped, all filenames clean (`0001_Chapter1.md` through `0075_*.md`). Titles: `"Monster? No, I'm a Cultivator! Chapter N"` — readable, bounded.

### Discovered (logged v1.1 backlog)
- AI sometimes picks bare tag selector (`'b'`) — works but fragile. Future: prompt should prefer ID/class selectors with high specificity.

---

## [1.0.0] — 2026-05-17

First production release. Universal novel content normalizer supporting 3 input sources × 3 output modes.

### Added — Phase 1: Output Mode Abstraction (2026-05-16)
- `RunConfig` dataclass + CLI flag `--output-mode {obsidian,translate,raw}`
- `CleanedChapter` DTO — contract between pipeline and writer
- `ImageRef` DTO — image reference with `position_marker` placeholder
- `FormattingRules` explicit schema with `image_alt_strategy` enum (`"preserve" | "skip" | "fallback_to_filename"`)
- `writers/base.py` — `ChapterWriter` ABC with async atomic write + cancel cleanup
- `writers/obsidian.py` — Markdown writer with YAML frontmatter + image embed
- `pipeline/executor.py::build_cleaned_chapter()` standalone helper
- Writer instance per task (built in `run_novel_task`, reused across chapters)

### Added — Phase 2: Image Support (2026-05-16)
- `utils/image_url.py` — relative URL → absolute resolver
- `core/image_pipeline/base.py` — `ImageFetchStrategy` ABC (Strategy pattern)
- `core/image_pipeline/web_fetcher.py` — HTTP fetch via `DomainSessionPool.fetch_bytes()` (reuses TLS fingerprint)
- `MarkdownFormatter` handles `<img>` tags → inserts `IMG_PLACEHOLDER_N` markers
- `PipelineContext.image_refs` field
- Mode-aware image stage in `core/scraper.py`:
  - `obsidian`: download local → `output/{slug}/images/ch_NNNN_idx.ext` + body link rewrite
  - `translate`: `[IMAGE: alt]` placeholder, no download
  - `raw`: strip placeholder entirely
- `AI#image` dedicated call — detects `has_inline_images` + `image_selector` per domain
- Image fetch failure → body falls back to external URL link (clickable)

### Added — Phase 3: EPUB Adapter (2026-05-16)
- `ingest/router.py` — input type detection (`web` / `epub` / `txt`)
- `ingest/epub.py` — `ebooklib` spine iteration, skip pirate front-matter (toc/cover/copyright/title/nav)
- `ingest/types.py` — `RawDocument` DTO (moved here in Phase 6 cleanup)
- `core/image_pipeline/epub_extractor.py` — `EpubImageExtractor` (binary from zip, reuses Strategy interface)
- `core/orchestrator.py` — `run_epub_flow` with body fallback (DensityHeuristic 0% hit on flat `<body><h1><p>` EPUBs)
- Dublin Core metadata → `story_name` (AI fallback if missing)
- AdsFilter `epub:{slug}` namespace — per-EPUB watermark learning, single-pass auto-only (threshold ≥10)
- `main.py` additive branch — EPUB → orchestrator, web flow unchanged

### Added — Phase 4: Translation + Raw Writers (2026-05-17)
- `writers/translation.py` — plain text, paragraph-per-line, no frontmatter, `[IMAGE: alt]` defensive strip
- `writers/raw.py` — text only, title as first plain line, no formatting
- `writers/factory.py::build_writer()` — central dispatch (`output_mode → ChapterWriter`), fail-loud on unknown mode
- `core/orchestrator.py::_apply_epub_image_stage` — mode-aware mirror of scraper's image stage for EPUB

### Added — Phase 5: TXT Adapter (2026-05-17)
- `data/txt_cases.json` — shipped with 6 cases (4 VN "Chương N" variants + 2 EN "Chapter N" variants)
- `ingest/txt.py`:
  - `_read_utf8` — fail-loud non-UTF-8 (Decision: predictable behavior > convenience)
  - `detect_pattern_regex` — score each case in first 100 lines, ≥1 match wins
  - `detect_pattern` — regex first → AI fallback if 0 matches
  - `_ai_verify_pattern` — 3 random middle chunks must each contain ≥1 boundary (catches header-only false positives)
  - `_persist_new_case` — atomic append-or-skip with threading lock
  - `split_into_chapters` — boundary list → `[(idx, title, body)]`
  - `_build_chapter_html` — wrap as `<article>` for pipeline downstream
- `core/orchestrator.py::run_txt_flow` — mirror of `run_epub_flow`
- AdsFilter `txt:{slug}` namespace
- TXT exit ramp at P5.5 NOT triggered — VN + EN regex passed > 50% threshold

### Added — Phase 6: Final Cleanup + Polish (2026-05-17)
- `docs/AUDIT_PHASE6.md` — codebase audit (LOC, unused imports, merge candidates, duplicate logic)
- `docs/V1_1_BACKLOG.md` — consolidated deferred features with rationale
- `docs/TROUBLESHOOTING.md` — 10 common issues + fix
- `CHANGELOG.md` — this file
- README.md full rewrite (was 1-line placeholder)

### Added — Foundation (Phase 0, 2026-05-16)
- `tools/snapshot_baseline.py` — regression baseline capture script
- `data/baselines/` directory (committed via `.gitkeep`)
- `main.py --bulk-relearn [--pattern <regex>] [--apply]` — bulk profile deletion with safety dry-run

### Changed
- `--fast-learning` CLI flag semantic: now means "skip ProseRichness validation in learning phase" (was: skip optimizer)
- `core/orchestrator.py` is now the routing entry for EPUB + TXT (web still goes direct via `main.py` → `run_novel_task`)
- `pipeline/title_extractor.py` inlined `_title_from_url` (was in `core/extractor.py`)
- `RawDocument` DTO moved from `ingest/epub.py` → `ingest/types.py` (shared)
- All `__init__.py`, hot `print()` strings, and library code use `encoding="utf-8"` explicit

### Removed (Phase 0 cleanups, ~780 LOC)
- `learning/optimizer.py` — "AI scoring AI" anti-pattern (Decision #26 / Batch A)
- `StepConfig`, `ChainConfig`, `PipelineConfig` serialization roundtrip (Decision #27 / Batch B)
- `learning/migrator.py` — v1 profile auto-migration (replaced by fail-loud + bulk-relearn UX)
- `ProfileManager.get()` returns `ValueError` for v1 profiles (was: silent migrate)

### Removed (Phase 6 Batch C, ~69 LOC)
- 17 unused imports across 13 files (autoflake)
- 22 stale `f"..."` prefixes on placeholder-less strings
- `ingest/web.py` — symbolic re-export added in Phase 3 (Decision #38) as forward placeholder, never called
- `core/extractor.py` — 1-caller helper inlined into `pipeline/title_extractor.py`

### Fixed
- See CLAUDE.md §12 "Critical Bugs Fixed" for full list. Highlights:
  - **M4 serialization** — nested params lost on JSON roundtrip (root cause of selector amnesia)
  - **ADS-KW** — AI returns HTML/script as ads keyword → validation guard in `utils/string_helpers.is_valid_ads_keyword`
  - **FINGERPRINT-COMMIT-ORDER** — fingerprint added before write → exception left "done" without count increment → false loop detection
  - **NAV-PROTECT** — `prepare_soup()` now protects `next_selector` from removal
  - **CONTAINS-SELECTOR** — `:contains()` pseudo-selectors now functional (cssselect doesn't natively support)
  - **CANCEL handling** — `asyncio.shield(save_progress())`, `CancelledError` re-raise discipline throughout

### Codebase Stats
- ~11,340 LOC across 52 Python files
- 8 phases shipped (Phase 0 → Phase 6 + docs finalization)
- ~2 days vibe-coded with Claude (vs 7-9 weeks estimate — accelerated by aggressive sessions)
- Version constant `VERSION = "1.0.0"` exposed in `config.py`, CLI `--version` flag added

### Ship Smoke Test Results (2026-05-17)
- **EPUB** (Ready Player One.epub): 52 chapters × 3 output modes (obsidian/translate/raw) = **156 files, all exit 0**
- **TXT** (synthetic 3-chapter test): 3 chapters × 3 output modes = **9 files, all exit 0**
- **Web** (Royal Road `Rock falls, everyone dies` — fresh learn + scrape): 19 chapters obsidian mode, exit 0 (9:13 elapsed). Title + frontmatter + body all clean. Translate + raw modes for this story blocked by `--output-dir` CLI bug (new V1_1 P2.0); writer code itself validated via EPUB + TXT smokes.
- **Web** (FFN + 69shuba): deferred to user — needs API + fresh learns per site (~10 min each).
- Bugs surfaced during smoke (deferred v1.1): EPUB title-path-fallback, EPUB image href relative-path miss, EPUB over-aggressive splitting (52 vs ~40 real chapters), AI 503 spikes (single-key SPOF), **web `--output-dir` CLI flag ignored** (writes to `output/` regardless).

### Known Tech Debt (deferred v1.1)
Priority order in [docs/V1_1_BACKLOG.md §0](docs/V1_1_BACKLOG.md):
1. **Baseline capture infrastructure** — unblocks behavioral refactors
2. **EPUB extraction bug fixes** — title/image/splitting from smoke
3. **Multi-key Gemini rotation** — 503 SPOF
4. **FlowSpec orchestrator unify** (~80 LOC) — blocked by #1
5. **Cross-platform smoke (Linux + macOS)** — Windows-only dev

Behavioral refactors:
- FlowSpec orchestrator unify (~80 LOC) — needs baseline capture first
- `_apply_image_stage` extract to shared helper (~60 LOC) — STOP §10 (shared logic) + baseline first
- See [docs/V1_1_BACKLOG.md](docs/V1_1_BACKLOG.md) for full list (18 items categorized)

---

## [Pre-1.0] — earlier history

See git log + per-phase retrospectives in `docs/PHASE_{1,2,3,4}_RETRO.md` for the journey from v0.x consolidation to v1.0 ship.

Notable pre-v1.0 milestones:
- v0.x consolidation — 5-chain pipeline architecture (Fetch / Extract / Title / Nav / Validate)
- Naming Phase (story name + chapter pattern detection)
- AdsFilter 2-tier (auto-add ≥10 + AI verify 3-9)
- HybridFetchBlock (curl_cffi + Playwright fallback)
- IssueReporter with session headers
