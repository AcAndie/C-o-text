# Phase 4 Retrospective — TranslationWriter + RawWriter + Writer Factory

> Phase 4 = complete 3-output-mode promise. Add `TranslationWriter` (plain text + `[IMAGE: alt]` placeholder) and `RawWriter` (image dropped). Wire `build_writer()` factory dispatch theo `run_config.output_mode` cho cả scraper (web) và orchestrator (EPUB). Extend orchestrator EPUB image stage mode-aware (mirror scraper).

---

## Plan vs Actual

| Step | Plan estimate | Actual | Note |
|---|---|---|---|
| P4.1 TranslationWriter | ~1 ngày | 1 session | 13/13 strip checks pass. Nested fmt fix (non-greedy bold regex). |
| P4.2 RawWriter | ~0.3 ngày | 1 session | 16/16 checks pass. Sizes raw < translate < obsidian confirmed. |
| P4.3 wire factory + EPUB mode-aware image stage | ~0.5 ngày | 1 session | `_apply_epub_image_stage` mirror scraper; remove NotImplementedError guard. |
| P4.4 Phase 4 smoke + retro | ~0.5 ngày | 1 session | EPUB × 3 modes verified (text-only + image-bearing synthetic). |
| **Phase 4 tổng** | **~2.3 ngày plan** | **4 session AI** | All code-only; live web verify defer to user. |

---

## Cái gì làm tốt

1. **STOP rules respected 1 lần** (P4.1 — 3 decision points pre-implementation: chunking option, orchestrator wire timing, title placement). All recommended/accepted, zero rollback.
2. **Factory pattern paid off** — `build_writer()` 1-line dispatch. Future writer (`EpubWriter` for export-to-epub?) just register vào `_WRITER_REGISTRY`. Single source of truth — scraper + orchestrator both use same function. Fail-loud for unknown mode (CLAUDE §11).
3. **Strip rule ordering correct** — image trước link (image regex preceded by `!`, link explicitly excludes). Bold trước italic (avoid `**x**` bị italic regex ăn). Non-greedy bold handles nested `**bold *italic* mixed**` → `bold italic mixed`.
4. **Edge case coverage** — `***triple***`, empty alt `![](url)`, `5 * 3 = 15` preserved, `code_name` preserved (italic regex excludes whitespace boundary).
5. **EPUB image stage parity với scraper** — `_apply_epub_image_stage` mirror `core.scraper._apply_image_stage`. Same 3 branches (download/placeholder/strip), different strategy (`EpubImageExtractor` vs `WebImageFetcher`). Pipeline output identical between web/EPUB cho cùng mode.
6. **Image-bearing synthetic test** — synth EPUB with 1-pixel PNG verified all 3 modes produce distinct sizes (obsidian 250b > translate 70b > raw 54b) + correct image handling (extracted to `images/`, `[IMAGE: alt]` placeholder, dropped entirely).
7. **Title placement decision** — kept as plain first line (no `# ` prefix) cho translate/raw. Translator wants context. Verified output starts với plain title text.

---

## Cái gì khó / mất nhiều thời gian

1. **Bold regex initial fail** — `\*\*([^*\n]+)\*\*` blocks `*` inside → `**bold *italic* mixed**` not stripped. Fix non-greedy `.+?` with `re.DOTALL`. **Lesson**: nested Markdown needs non-greedy with explicit ordering, not greedy with character class exclusion.
2. **Italic regex whitespace edge** — first attempt matched `5 * 3` as italic. Fix: `(?<!\*)\*([^*\s]...)\*(?!\*)` — non-whitespace boundary. **Lesson**: real prose has bare asterisks; italic regex must require word-boundary content.
3. **`_apply_image_stage` duplication scraper vs orchestrator** — same 3-branch logic, different strategy. Considered Strategy injection refactor; deferred P6. Accept small duplication for now.
4. **No translate-mode AI verify path** — translation pipeline downstream tools may want different cleaning. Current writer applies markdown strip but doesn't know what target LLM accepts. Acceptable — writer's job is mode boundary, not consumer-aware tuning.
5. **No image EPUB available** — same as P3. Synthetic test covers extract path + 3-mode handling. Light novel illustrated EPUB combo not tested live.

---

## Tech debt accumulate

| Item | Severity | Note |
|---|---|---|
| `_apply_image_stage` / `_apply_epub_image_stage` duplication | Medium | Same 3-branch logic. Strategy-injected unified helper defer P6. |
| RawWriter / TranslationWriter strip regex duplication | Low | RawWriter copies most rules from TranslationWriter. Could inherit + override `_strip_markdown`. Defer P6 cleanup. |
| `CHUNK_THRESHOLD = 0` constant unused | Low | Configurable chunking deferred per Decision P4.1 Option A. Re-enable nếu user needs. |
| No `EpubWriter` (export → EPUB) | Out of scope | Decompose-only scope per BLUEPRINT. Different project. |
| Live web × 3-mode verify | Medium | Web flow uses factory now; verified code-path import + dispatch. Live test (network/API) defer user. |
| Image MD strip doesn't handle reference-style `[alt][ref]` + `[ref]: url` | Low | Pipeline output uses inline `![alt](url)` only — reference style not generated. Defer until needed. |
| No regression baseline diff cho web after factory swap | Medium | scraper.py:914 single-line replacement, factory returns same `ObsidianWriter` for default config — logically zero diff. User confirm with baseline tool. |

---

## Risks cho Phase 5 (TXT adapter)

1. **TXT chapter boundary detection** — fundamentally different from EPUB (no structure) and web (no anchor). Need AI-assisted pattern learning per Decision #21 (VN + EN only).
2. **`data/txt_cases.json` case database** — new persistence file. Format + lock pattern (similar to ads_keywords.json).
3. **TXT writer dispatch** — already works via factory. No changes needed to writer layer.
4. **Orchestrator TXT branch** — currently raises NotImplementedError. P5 wire `run_txt_flow()` analogous to `run_epub_flow`.
5. **TXT-specific image handling** — text files have no inline image syntax. RawWriter handles cleanly. TranslationWriter `[IMAGE: alt]` placeholder won't trigger (no image refs). All 3 writers work for text-only by default.

---

## Decisions accumulated trong Phase 4

| # | Decision | Tóm tắt |
|---|---|---|
| 45 | TranslationWriter chunking OFF default (P4.1 Option A) | `CHUNK_THRESHOLD = 0`. Modern LLMs 128K-1M context fit chapter fine. Future configurable via `RunConfig.chunk_threshold` nếu need. |
| 46 | TranslationWriter/RawWriter title plain first line (P4.1) | Keep title as first line text (no `# ` prefix). Translator wants context. Drop in TW would lose chapter ordering signal. |
| 47 | TranslationWriter image → `[IMAGE: alt]` defensive strip (P4.1) | Web scraper pre-rewrites for translate mode; EPUB orchestrator now does too (P4.3). Writer fallback handles edge cases where placeholder leaks through. |
| 48 | `writers/factory.py` `build_writer()` central dispatch (P4.3) | Single source of truth. Replace hardcoded `ObsidianWriter` in scraper + orchestrator. Fail-loud on unknown mode (CLAUDE §11). |
| 49 | `_apply_epub_image_stage` mirror scraper's image_stage (P4.3) | Same 3-branch logic (obsidian/translate/raw), different strategy (`EpubImageExtractor` vs `WebImageFetcher`). Duplication accepted; unification defer P6. |

Add vào CLAUDE.md §17 trong commit này.

---

## Phase 4 verification snapshot — Input × Output matrix

BLUEPRINT §4 promises 3 input types × 3 output modes = 9 combinations. Phase 3 + 4 status:

| Input | obsidian | translate | raw |
|---|---|---|---|
| **web** | ✅ (P1.5 + P2) | ⚠️ code-path only (live defer user) | ⚠️ code-path only (live defer user) |
| **epub** | ✅ P3 | ✅ P4.3 (5ch + img synth) | ✅ P4.3 (5ch + img synth) |
| **txt** | ❌ Phase 5 | ❌ Phase 5 | ❌ Phase 5 |

**Verified live**: 5 of 9 combinations (web obsidian, all 3 EPUB modes, plus EPUB image-bearing synthetic for all 3 modes).
**Code-path only**: web translate + web raw (factory dispatch verified, live needs network/API + RR illustration novel).
**Pending**: TXT × 3 modes blocked by Phase 5.

---

## Verify required từ user TRƯỚC Phase 5

- [ ] Web flow regression: `py main.py links.txt` — should produce identical obsidian output as v0.x-phase3 (factory returns same `ObsidianWriter` for default config — logical zero diff)
- [ ] Web × translate live: `py main.py links.txt --output-mode translate` → verify `.txt` files, no markdown noise, image placeholder if RR
- [ ] Web × raw live: `py main.py links.txt --output-mode raw` → verify image dropped
- [ ] Translation output paste-to-Gemini test: take any `.txt` from translate mode → paste vào Gemini "dịch sang tiếng Việt" → verify clean Vietnamese, no formatting noise
- [ ] (Optional) Image-bearing EPUB if found in real-world library → all 3 modes
