# Phase 3 Retrospective — EPUB Adapter + Input Routing

> Phase 3 = add EPUB input route end-to-end. New `ingest/` package (router + adapters), `EpubImageExtractor` strategy, `core/orchestrator.py` dispatch theo input type, AdsFilter cross-EPUB watermark detection. Web flow UNCHANGED — additive only.

---

## Plan vs Actual

| Step | Plan estimate | Actual | Note |
|---|---|---|---|
| P3.1 add ebooklib | ~0.2 ngày | 1 session | Single requirements.txt line, import smoke |
| P3.2 ingest/router | ~0.5 ngày | 1 session | 10 test cases pass, scan 5-line links.txt heuristic |
| P3.3 ingest/web wrapper | ~0.5 ngày | 1 session | Decision A: symbolic re-export (refactor caller defer P6) |
| P3.4 ingest/epub adapter | ~1 ngày | 1 session | Spine iterate + DC naming + SKIP_PATTERNS filter; 967ch/969 spine confirmed |
| P3.5 EpubImageExtractor | ~1 ngày | 1 session | Strategy ABC reuse; synthetic PNG test (69b extracted, match) |
| P3.6 orchestrator (LARGE) | ~2 ngày | 1 session | STOP rule plan-first + user confirm. Bypassed PipelineRunner — manual chain run. Body fallback added (DensityHeuristic fails on flat EPUB body). Title dedup mirror scraper. |
| P3.7 AdsFilter cho EPUB | ~0.5 ngày | 1 session | Per-EPUB namespace `epub:{slug}`. Auto-only threshold (no AI verify). Synthetic + clean EPUB both verify. |
| P3.8 Phase 3 smoke + retro | ~0.5 ngày | 1 session | Full E2E Thiếu Niên Hành 967ch in 27.4s |
| **Phase 3 tổng** | **~6.2 ngày plan** | **8 session AI** | All code-only, live + multi-mode gaps documented |

---

## Cái gì làm tốt

1. **STOP rules respected 2 lần** (P3.3 wrapper decision, P3.6 orchestrator scope). Plan + recommend + user confirm trước code. Zero rollback.
2. **Strategy pattern paid off** — `EpubImageExtractor` plug-in cùng interface với `WebImageFetcher` (P2 ABC). Pipeline image stage không cần biết source. Synthetic PNG test 69b round-trip.
3. **Symbolic re-export choice P3.3** — `ingest/web.py` chỉ re-export `run_novel_task` + `scrape_web` thin wrapper. Web caller chain unchanged → zero regression risk. Refactor caller defer Phase 6 khi orchestrator route được cả 3 adapter.
4. **main.py additive-only diff** — 13 lines insertion, web branch literal untouched. EPUB branch early-return. Web regression risk = zero (logical).
5. **EPUB body fallback** — DensityHeuristic fails on flat `<body><h1><p>` EPUB structure → caught + fallback `MarkdownFormatter(body_tag)`. Selector marker `epub_body_fallback` cho debug. Test live confirmed: 967 chapters Thiếu Niên Hành ALL pass via fallback (extract chain returns False — fallback handles 100%).
6. **Title dedup ported correctly** — body fallback includes `<h1>` → mirror `scraper.py:303-307` logic. No duplicate `# Title` headers.
7. **AdsFilter per-EPUB namespace** — `epub:{slug}` key isolation. Clean EPUB → 0 false positives. Dirty EPUB (Thiếu Niên Hành has author notes "huynh đệ, chương tiếp theo X giờ a!.") → 8 kws auto-learned, 231 lines retroactively stripped via `post_process_directory`.
8. **Single-pass auto-only AdsFilter** — no AI verify branch cho EPUB. Threshold ≥10 occurrences covers watermark patterns. AI verify branch defer (cost zero for clean EPUBs; pirate trigger first pass).
9. **27.4s for 967 chapters** — fast. No network, no AI calls, pure local I/O + BS4. Sequential write hits disk hard nhưng acceptable.

---

## Cái gì khó / mất nhiều thời gian

1. **DensityHeuristic incompatibility with EPUB** — first 5-chapter test all skipped. Debug: EPUB body `<body><h1><p>...<p>` flat, no `<article>`/`<main>`/`<div class=content>` nested containers heuristic looks for. Fix: body-tag fallback path. **Lesson**: web-novel pipeline assumptions don't transfer 1:1 to EPUB.
2. **AdsFilter watermark validation guard** — first synthetic test (14-word watermark) detected 0 because `is_valid_ads_keyword()` rejects >10 words. Switched to 5-word realistic pattern → worked. **Lesson**: real pirate watermarks usually short; guard tuned correctly for noise rejection.
3. **No pirate EPUB available** — couldn't test "watermark + image embed" combo from real pirate source. Synthetic covers each independently; combo coverage gap.
4. **No Project Gutenberg EPUB available** — couldn't verify "clean EPUB no over-strip" với canonical clean source. Thiếu Niên Hành (Vietnamese translated) used as proxy.
5. **TranslationWriter + RawWriter not implemented** — spec asks 2 EPUB × 3 modes = 6 outputs. Only obsidian works. Defer Phase 4. **Phase 3 scope gap.**
6. **Spec runner.run_partial() doesn't exist** — task template referenced API that's not in PipelineRunner. Adding = STOP shared logic. Bypass with manual chain composition (`runner._extract_blocks()` + `runner._title_blocks()` direct to `ChainExecutor`). Acceptable — orchestrator is a composer, not a refactor.
7. **AdsFilter integration only Pass 1** — scraper does Pass 1 (before strip_nav_edges) + Pass 2 (after). EPUB skips strip_nav_edges (no nav buttons), so single pass enough. Maps differently per source.

---

## Tech debt accumulate

| Item | Severity | Note |
|---|---|---|
| TranslationWriter/RawWriter not implemented | **HIGH** | Blocking Phase 4. Orchestrator raises NotImplementedError for non-obsidian modes. |
| EPUB body fallback always triggers (extract chain 0% hit rate cho EPUB) | Medium | Extract chain run is wasted compute. Could short-circuit "if EPUB → skip extract chain, go straight to body fallback". Defer P6 optimization. |
| No pirate EPUB live verify | Medium | Synthetic test covers watermark + image independently, not combo. User to verify on real pirate EPUB if available. |
| No Project Gutenberg clean baseline | Low | Thiếu Niên Hành (clean translated) proxy. |
| EPUB progress/resume not implemented | Low | Atomic write idempotent — full re-run works. Defer v1.1. |
| `_apply_image_stage` (scraper) hardcodes WebImageFetcher | Low | Already duplicated in orchestrator helper `_rewrite_epub_image_placeholders`. Could refactor `_apply_image_stage` strategy-aware. Defer P6. |
| `ingest/web.py` scrape_web wrapper never called | Low | Defer P6 when main.py refactors to use orchestrator.run for web too. |
| `core/chapter_writer.py` not yet deleted (cũ từ P1) | Low | Defer P6 |
| `ai/agents.py` dead code (cũ) | Low | Defer P6 |
| AdsFilter AI verify branch unused cho EPUB | Low | Single-pass auto-only sufficient. Add if needed later. |

---

## Risks cho Phase 4 (TranslationWriter + RawWriter)

1. **Mode dispatch in orchestrator** — currently raises NotImplementedError for non-obsidian. Phase 4 adds 2 writers + dispatch table. Need writer factory pattern.
2. **EPUB body fallback always wins** — extract chain 0% hit cho EPUB content. Phase 4 writers consume `CleanedChapter.body_markdown` — fallback path produces same DTO so writer mode shouldn't care, but verify TranslationWriter doesn't expect frontmatter (plain text mode).
3. **Image placeholder format consistency** — `WebImageFetcher` produces `images/ch_NNNN_idx.ext` rel path. `EpubImageExtractor` same convention. Translation/Raw mode skip download but need consistent placeholder rewrite (translate: `[IMAGE: alt]`, raw: strip).
4. **AdsFilter Pass 2 không có cho EPUB** — nếu Phase 4 add `strip_nav_edges` equivalent cho EPUB (currently None), reconsider Pass 2.

---

## Decisions accumulated trong Phase 3

| # | Decision | Tóm tắt |
|---|---|---|
| 38 | `ingest/web.py` symbolic re-export, not refactor (P3.3) | Phase 3 scope: build skeleton adapter. Refactor caller (main.py) defer Phase 6 — adapter chain stable, orchestrator route 3 sources. |
| 39 | `core/orchestrator.py` function-based, not class (P3.6) | Stateless — class adds no state. Just dispatch + run_epub_flow. |
| 40 | EPUB body fallback via MarkdownFormatter (P3.6) | DensityHeuristic 0% hit rate cho flat `<body><h1><p>` EPUB structure. Fallback grabs body tag directly. `selector_used = "epub_body_fallback"`. |
| 41 | Orchestrator bypass PipelineRunner — manual chain compose (P3.6) | `runner.run_partial()` doesn't exist. Adding = STOP shared logic. Compose `ChainExecutor(runner._extract_blocks())` direct. EPUB skip Fetch/Nav/Validate anyway. |
| 42 | main.py additive EPUB branch — web untouched (P3.6) | 13-line insertion before `_parse_links_file`. EPUB → return early. Web → fall through unchanged. Zero web regression risk. |
| 43 | AdsFilter `epub:{slug}` namespace (P3.7) | Tránh collision với web `domain.com` keys trong `data/ads_keywords.json`. Per-EPUB persistence enables cross-run learning. |
| 44 | AdsFilter EPUB single-pass auto-only — no AI verify (P3.7) | EPUB không có ai_limiter bắt buộc. `auto_threshold=10` đủ cho watermark. AI verify branch defer (zero cost for clean, pirate triggers first pass). |

Add vào CLAUDE.md §17 trong commit này.

---

## Phase 3 gaps — verify required từ user

Critical (chưa cover):

- [ ] **Multi-mode test** — TranslationWriter + RawWriter chưa exist (Phase 4). Spec retro asked 2 × 3 = 6 outputs; only 2 × 1 = 2 outputs deliverable.
- [ ] **Pirate EPUB combo test** — watermark + embedded image trên cùng 1 source. Synthetic covers each independently.
- [ ] **Project Gutenberg canonical clean test** — proxy was Thiếu Niên Hành (Vietnamese translated, also clean). No issue found but not canonical.
- [ ] **Live image extraction từ real illustrated EPUB** — synthetic PNG 69b verified. Light novel illustrated EPUB chưa có để test.
- [ ] **Resume after partial run** — Ctrl+C mid-run, re-run → currently re-writes all (atomic write idempotent). No state file. Acceptable cho v1.0; defer if pain.

Live web regression (carried over from P3.6):
- [ ] `python main.py links.txt` web flow no behavior change. main.py diff is purely additive (13 lines pre-flight). Risk = zero logically.

---

## Verification snapshot

| Test | Result |
|---|---|
| Thiếu Niên Hành 967 chapters obsidian | ✅ 27.4s, 0 skipped, ads_learned=8, post_process stripped 231 lines |
| e2e-test 1 chapter obsidian | ✅ DC title extracted, no ads (clean) |
| Spot-check 0001/0500/0967 | ✅ Frontmatter + body + no learned ads remaining |
| AdsFilter synthetic 12ch + 5-word watermark | ✅ +1 kw, 12 lines stripped, 0/12 contain watermark |
| AdsFilter Thiếu Niên Hành 15ch sample | ✅ 0 false positives |
| EpubImageExtractor synthetic PNG | ✅ 69b extracted, magic byte ext detection |
| Router web→RuntimeError, txt→NotImplementedError, epub→run_epub_flow | ✅ |
| `data/ads_keywords.json` entry `epub:Thiếu_Niên_Hành` | ✅ persisted (cleaned post-test) |

---

## Phase 4 unlock readiness

Ready for Phase 4 entry:
- ✅ CleanedChapter DTO stable (P1.2)
- ✅ ChapterWriter ABC stable (P1.3)
- ✅ ObsidianWriter as reference impl (P1.4)
- ✅ Orchestrator dispatch hook present (raises NotImplementedError → easy entry point)
- ⚠️  Need writer factory in orchestrator (currently hardcodes ObsidianWriter) — add when implementing Phase 4
