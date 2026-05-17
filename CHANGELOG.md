# Changelog

All notable changes to Cào Text. Format based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), versioning per [Semantic Versioning](https://semver.org/).

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
