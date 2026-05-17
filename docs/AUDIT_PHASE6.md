# Phase 6 Codebase Audit

> **Date**: 2026-05-17
> **Scope**: Pre-Phase 6 cleanup baseline. Identify dead code, unused imports, redundant files, duplicate logic across `ingest/` adapters.
> **Total LOC**: ~11,409 across 53 Python files (excluding `__pycache__`, `data/`, `output/`, `progress/`).

---

## 1. LOC Distribution

### Top 10 hot files
| LOC   | File                                |
|------:|-------------------------------------|
| 1,046 | `ai/agents.py`                      |
| 1,013 | `core/scraper.py`                   |
|   803 | `ai/prompts.py`                     |
|   488 | `main.py`                           |
|   455 | `core/orchestrator.py`              |
|   438 | `pipeline/extractor.py`             |
|   364 | `pipeline/executor.py`              |
|   363 | `ingest/txt.py`                     |
|   357 | `learning/phase_ai.py`              |
|   343 | `utils/content_cleaner.py`          |

### Small files (<30 LOC, excluding `__init__.py` markers)
None — every non-init file ≥38 LOC. All `__init__.py` are package markers (0 LOC for most, 10-21 for re-export hubs).

---

## 2. Merge / Delete Candidates

### 2.1 `ingest/web.py` (62 LOC) — **DELETE candidate**
- **Reason**: Symbolic re-export only. `scrape_web()` wrapper never called. Greppable callers = 0.
- Was Decision #38: "thin façade for Phase 6". Phase 6 = now. Time to act:
  - Option A — **delete the wrapper**, keep `main.py` calling `core.scraper.run_novel_task` directly.
  - Option B — **wire `main.py` web branch through `core/orchestrator.run()`**, then `scrape_web()` becomes the canonical entry.
- **Recommendation**: Option B (matches orchestrator pattern already set up for EPUB/TXT). Requires `orchestrator.run()` to drop its "web not handled here" `RuntimeError` and route to `scrape_web()`.

### 2.2 `core/extractor.py` (56 LOC) — **MERGE candidate**
- **Reason**: Single function `_title_from_url()` with exactly 1 caller (`pipeline/title_extractor.py:218`, lazy import).
- **Suggested move**: Inline into `pipeline/title_extractor.py` as private helper, or into `utils/string_helpers.py` next to `slugify_filename` family.
- **Risk**: low — pure function, no shared state.

### 2.3 `core/fetch.py` (56 LOC) — **KEEP**
- 3 callers (`scraper.py` ×2, `learning/naming.py`, `learning/phase.py`).
- Public API surface justifies file.

### 2.4 `writers/factory.py` (38 LOC) — **KEEP**
- 2 callers (`core/orchestrator.py` ×2 sites, `core/scraper.py`). Decision #48 chốt central dispatch.

### 2.5 `ai/client.py` (68 LOC) — **KEEP**
- 4 importers (`ingest/web.py`, `ingest/txt.py`, `learning/naming.py`, `learning/phase.py`, `tools/snapshot_baseline.py`). Module-level `ai_client` singleton — không inline được.

### 2.6 `core/image_pipeline/base.py` (66 LOC) & `writers/base.py` (67 LOC) — **KEEP**
ABCs, đa subclass — không phải merge candidate.

---

## 3. Unused Imports (pyflakes scan)

19 hits — pure deletion, zero risk:

| File                          | Line | Symbol                                       |
|-------------------------------|-----:|----------------------------------------------|
| `core/fetch.py`               |   18 | `utils.string_helpers.is_junk_page`          |
| `core/formatter.py`           |   31 | `bs4.BeautifulSoup`                          |
| `core/navigator.py`           |   13 | `bs4.Tag`                                    |
| `core/navigator.py`           |   15 | `config.RE_CHAP_HREF`                        |
| `core/orchestrator.py`        |   32 | `sys`                                        |
| `core/scraper.py`             |   77 | `writers.obsidian.ObsidianWriter`            |
| `ingest/txt.py`               |   28 | `asyncio`                                    |
| `learning/phase_ai.py`        |   18 | `asyncio`                                    |
| `learning/phase_ai.py`        |   20 | `datetime.datetime`, `datetime.timezone`     |
| `pipeline/extractor.py`       |   21 | `typing.Any`                                 |
| `pipeline/extractor.py`       |   23 | `bs4.BeautifulSoup`                          |
| `pipeline/navigator.py`       |   22 | `bs4.BeautifulSoup`, `bs4.Tag`               |
| `utils/ads_filter.py`         |    6 | `re`                                         |
| `utils/ads_filter.py`         |    9 | `pathlib.Path`                               |
| `utils/file_io.py`            |   18 | `pathlib.Path`                               |
| `utils/issue_reporter.py`     |   14 | `os`                                         |
| `utils/types.py`              |   17 | `typing.Any`                                 |

**Action**: `py -m autoflake --in-place --remove-all-unused-imports --recursive ai core ingest learning pipeline tools utils writers main.py config.py` in P6 cleanup commit.

### Secondary: stale f-strings (cosmetic)
22 occurrences of `f"..."` without placeholders (mostly `learning/phase_ai.py` print banners). Drop the `f` prefix in same cleanup pass — zero behavior change.

---

## 4. Duplicate Logic — `ingest/` Adapters & Orchestrator

### 4.1 `core/orchestrator.run_epub_flow` vs `run_txt_flow` — **80% duplicate** (HIGH PRIORITY)

Lines `90-203` (EPUB) vs `208-314` (TXT). Structure identical:
```
1. story_name + slugify → out_dir mkdir
2. build_writer(out_dir, run_config)
3. PipelineRunner.default()
4. AdsFilter.load(domain=f"{ns}:{slug}")  # ns = "epub" | "txt"
5. print intro banner
6. async for doc in ingest_X(input):
   - _build_chapter_from_epub_doc(doc, ...)  # already shared
   - mode-aware metadata carry (EPUB: image stage / TXT: language tag)
   - writer.write(chapter)
   - ads_filter.scan_edges_for_suspects(...)
   - progress print every 25
7. End-of-run AdsFilter auto-apply + post_process_directory
8. Final done banner
```

**Suggested refactor**: Extract shared `_run_file_flow(adapter_iter, namespace, ai_limiter, ...)` helper. Differences are exactly 3:
- adapter coroutine call (`ingest_epub(path)` vs `ingest_txt(path, ai_limiter=...)`)
- post-chapter hook (EPUB image stage vs TXT language tag passthrough)
- emoji + label in banner (`📖 EPUB:` vs `📄 TXT:`)

Encode differences as a small `FlowSpec` dataclass passed to the helper. **Savings: ~80 LOC, eliminates copy-paste drift risk.**

### 4.2 Naming logic — partial duplicate
Both flows do `slugify_filename(story_name)` + `Path(run_config.output_dir) / story_slug` + `mkdir(parents=True, exist_ok=True)`. Lift into helper `_prepare_output_dir(story_name, run_config) -> Path`.

### 4.3 AdsFilter end-of-run block — **identical**
Lines `186-202` (EPUB) and `297-313` (TXT) byte-for-byte same except for branch label. Lift into `_finalize_ads_filter(ads_filter, out_dir)`.

### 4.4 `_build_chapter_from_epub_doc` — already shared ✅
Both `run_epub_flow` and `run_txt_flow` already call this single helper. Misnomer (TXT uses it too) — rename to `_build_chapter_from_raw_doc` in cleanup pass.

### 4.5 `ingest/epub.py` vs `ingest/txt.py` — **low duplication**
Both define `RawDocument` flow but `ingest/txt.py` imports `RawDocument` from `ingest/epub.py` (line 38) — no class duplication. Adapter logic genuinely different (spine iteration vs regex chapter split).

**Action item**: Move `RawDocument` dataclass to `ingest/__init__.py` or `ingest/types.py` — currently lives in `epub.py` by historical accident.

---

## 5. Other Observations

### 5.1 `core/orchestrator.py` size growth
455 LOC, up from spec-estimate ~250. Reason: `run_epub_flow` + `run_txt_flow` copy-paste. Refactor in §4.1 brings it back down ~290-320.

### 5.2 `import re as _re` (line 402)
Cosmetic — alias collision avoidance no longer needed (no top-level `re` import in file). Drop alias.

### 5.3 `core/orchestrator._apply_epub_image_stage` vs `core/scraper._apply_image_stage`
Decision #49 accepted short-term duplication. Strategy-injected unified helper deferred Phase 6 — **now is the time**. Both mirror the 3-branch (obsidian / translate / raw) mode dispatch with only the fetcher class differing. Lift into `core/image_pipeline/stage.py` taking `ImageFetchStrategy` as parameter.

---

## 6. Recommended Phase 6 Cleanup Commits (Ordered)

| # | Commit                                                                        | Risk |
|---|-------------------------------------------------------------------------------|------|
| 1 | `chore: autoflake remove 19 unused imports + drop stale f-prefixes`           | low  |
| 2 | `refactor(ingest): move RawDocument to ingest/types.py`                       | low  |
| 3 | `refactor(core): extract _title_from_url into title_extractor; delete core/extractor.py` | low  |
| 4 | `refactor(core/orchestrator): unify run_epub_flow + run_txt_flow via FlowSpec helper (~80 LOC saved)` | med  |
| 5 | `refactor(image_pipeline): extract _apply_image_stage to image_pipeline/stage.py (Strategy-injected)` | med  |
| 6 | `feat(ingest/web): wire main.py web branch through orchestrator.run(); delete ingest/web.py stub` OR `chore: delete unused ingest/web.py wrapper` | low–med |

Each commit must:
1. Run smoke test (1 URL web + 1 EPUB + 1 TXT)
2. Baseline diff vs `data/baselines/` (Decision #19) for commits 4 & 5.

---

## 7. Estimated LOC Reduction

| Source                                        | LOC saved |
|-----------------------------------------------|----------:|
| Unused imports + stale f-prefixes             |       ~25 |
| `core/extractor.py` merge                     |       ~50 |
| `ingest/web.py` delete (if Option A)          |       ~60 |
| Orchestrator `run_epub_flow` / `run_txt_flow` unify | ~80 |
| Image stage unify (orchestrator + scraper)    |       ~60 |
| **Total estimate**                            |  **~275** |

Brings codebase ~11,409 → ~11,135 LOC. Modest but removes 2 files + 1 anti-pattern (mirror flows that drift).

---

## 8. Out of Scope (Defer)

- **`ai/agents.py` 1,046 LOC split** — split by AI call number (AI#1-5 discovery vs AI#6-8 synthesis) defer v1.1 (already noted in CLAUDE.md anti-pattern #10).
- **`core/scraper.py` 1,013 LOC** — orchestration hub, splitting it risks blast radius. Defer.
- **TypedDict refactor (`utils/types.py`)** — Decision #16, defer v1.1+.
- **`main.py` CLI restructure** — works; rewriting argparse not in P6 scope.
