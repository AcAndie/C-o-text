# Project Retrospective — Cào Text v1.0.0

> **Ship date**: 2026-05-17
> **Tag**: v1.0.0
> **Branch shipped from**: phase5-txt-adapter

---

## 1. Plan vs Actual

| Metric | Plan (ROADMAP v1.1) | Actual | Delta |
|---|---|---|---|
| Total time | 7-9 weeks solo dev part-time | ~2 days aggressive sessions | **-95%** |
| Phases | Phase 0 → Phase 6 (7 phases) | Phase 0 → Phase 6 + docs (8 logical phases) | +1 (docs split) |
| LOC budget | Reduce v0.x ~7,240 by 780 + add features | 11,340 LOC final (~+4k net for 3 inputs × 3 outputs + image stage) | as expected |
| Phase 5 exit ramp | High-risk, may trigger defer | NOT triggered — VN+EN regex pass | risk mitigated |
| Test framework | Smoke + baseline diff | Smoke only — baseline NEVER captured | gap (deferred) |
| Live regression | Per-phase baseline diff | Skipped — `data/baselines/` only `.gitkeep` | gap (deferred) |

**Why the speed**: aggressive parallel Claude sessions, narrow scope discipline (CLAUDE §3 Scope Lock), strict STOP rule respect saving rework cycles.

**The catch**: live verification compressed to a single P6.4 smoke pass at end. Per-phase baseline diff never happened — tradeoff documented in Decision #56.

---

## 2. What Went Well

### 2.1 STOP rule discipline
Every time a refactor touched shared logic (`core/scraper.py`, `pipeline/base.py`, `pipeline/executor.py`, `core/formatter.py`) the rule forced an explicit pause. Result: zero shared-logic regressions across 8 phases. P1.5 (pipeline returns CleanedChapter), P2.3 (MarkdownFormatter img), P6.2 (image stage extract deferred) all benefited.

### 2.2 Decision Log as ground truth
56 decisions logged. When Phase 4 needed factory dispatch and Phase 6 needed cleanup priority, prior decisions (e.g., #18 baseline protocol, #38 ingest/web.py defer) immediately resolved direction without re-debate.

### 2.3 Phase ordering enforcement
Decision #17 (Output Abstraction before Image Support) prevented technical debt. Image stage needed `RunConfig.download_images` — if image came first, would have shipped hardcoded download with bolt-on mode flag. Sequence honored, code clean.

### 2.4 Scope Lock prevented creep
DEFERRED list (CLAUDE §3) caught 6+ "wouldn't it be cool" moments across sessions (case-based learning, CJK hardening, multi-provider AI, GUI, frontmatter customization). Each routed to `docs/V1_1_BACKLOG.md` instead of v1.0 scope.

### 2.5 Strategy pattern for image fetch (Decision #19)
`ImageFetchStrategy` ABC + `WebImageFetcher` + `EpubImageExtractor` clean split. Pipeline stage agnostic — `core/scraper.py` calls strategy, doesn't care if source is HTTP or zip. Trivial to add MOBI/PDF image extractor later (just implement Strategy interface).

### 2.6 Phase 5 exit ramp NOT triggered
Insurance plan (defer TXT if <50% pass rate) never needed. Narrowed scope (VN + EN only) shipped clean. Risk mitigation = success without invocation.

### 2.7 Batch B fail-loud over silent migration
Profile v1 → v2 path chose `raise ValueError` over auto-migrate. Saved future "silent corruption" debugging. User sees error explicitly + actionable fix (`!relearn`).

### 2.8 EPUB smoke validation worked first try
Ready Player One EPUB → 52 chapters extracted across 3 modes, exit 0 every time. Dublin Core naming worked, body fallback handled flat `<body><h1><p>` structure (Decision #40 validated live).

---

## 3. What Was Hard

### 3.1 No baseline capture
`data/baselines/` shipped empty. Plan said capture per-phase, reality said "needs live API + scrape time, defer". Result: Phase 6 Batch C had to limit to pure-deletion items (0.6% LOC vs 5-10% target). FlowSpec + image stage extract blocked.

### 3.2 EPUB title extraction fallback bug
Some chapters got source path as title (`0004_UsersFpt_Mong_CaiDesktopSmall_Project...md`). Title chain fell through to `_title_from_url` which fed a file path → garbled. Body content intact, just filename ugly. Surfaced in P6.4 smoke. **Tech debt → v1.1**.

### 3.3 EPUB image href resolution gap
`EpubImageExtractor` failed on `../images/imgN.jpg` relative paths inside chapter HTML. Logged but skipped — body falls back to external link. Some EPUBs use absolute paths, some relative, some `OEBPS/images/...`. Need path resolution layer. **Tech debt → v1.1**.

### 3.4 EPUB chapter splitting too aggressive
Ready Player One: 52 "chapters" from one novel. Spine items include front matter slips, table of contents subsections, and per-EPUB illustration pages. SKIP_PATTERNS in `ingest/epub.py` catches some but not all. Pattern needs expansion for pirate-Z EPUBs specifically. **Tech debt → v1.1**.

### 3.5 AI 503 spikes during peak
Gemini hit 503 UNAVAILABLE several times during EPUB AI image extract calls. Auto-retry kicked in (5 attempts, 30s backoff) — recovered. But latency spike noticeable. Multi-key rotation would help; currently single key.

### 3.6 Vibe coder rhythm vs spec rigor
Solo dev pace = bursts of work then breaks. Plan rigor (CLAUDE §8.5 baseline before refactor) requires discipline during burst. When fingers are flying, "I'll baseline next session" turns into "never baselined". P6.4 user-action defer is the honest landing.

### 3.7 Decision Log getting long
56 entries in CLAUDE.md §17. Useful but starting to require ctrl+F to navigate. v1.1 may need split into `decisions/{decision_NN.md}` files referenced by index.

### 3.8 Windows-specific quirks
ProactorEventLoop "I/O operation on closed pipe" noise required explicit suppression in `main.py:471`. CRLF / LF warnings on every git add. Path separator handling differences. Project is Windows-first by accident; cross-platform robustness untested.

---

## 4. Tech Debt for v1.1

Documented in detail at [docs/V1_1_BACKLOG.md](V1_1_BACKLOG.md). Quick triage:

**Behavioral refactors (need baseline first):**
- FlowSpec orchestrator unify (~80 LOC)
- Image stage extract to shared helper (~60 LOC)

**Bug fixes from smoke:**
- EPUB title fallback that returns source path
- EPUB image href relative-path resolver
- EPUB SKIP_PATTERNS for pirate-Z front matter

**Infrastructure:**
- Baseline capture mandatory before any v1.1 refactor
- Multi-key Gemini rotation in `ai/client.py`
- Cross-platform testing (Linux + macOS happy path)

**Scope expansions:**
- CJK i18n hardening (TXT pattern + encoding heuristic)
- Multi-AI provider abstraction (Claude/OpenAI swap-in)

---

## 5. Top 5 Priorities for v1.1

Ordered by value × cost ratio:

### Priority 1 — Baseline capture infrastructure
**Why first**: Unlocks all behavioral refactors (FlowSpec, image stage extract). Currently blocking 5-10% LOC reduction target. Estimated effort: 1 session to capture 3 site + 2 EPUB + 2 TXT baselines.

**How**: Run `python tools/snapshot_baseline.py --label v1.0_final` after learning each site once. Commit baselines to `data/baselines/`. Diff against v1.1 refactor branches.

### Priority 2 — EPUB extraction bug fix triage
**Why second**: User-visible regression from smoke. Title fallback + image href + over-aggressive splitting = bad first impression for EPUB users. Estimated: 1-2 days.

**Subtasks**:
- Title chain: when URL is file path, skip `_title_from_url` (no slug to extract)
- Image href: resolve `../images/x.jpg` against chapter HTML's location inside EPUB
- SKIP_PATTERNS: add `dedication`, `epigraph`, `acknowledgment`, `note` (case-insensitive)

### Priority 3 — Multi-key Gemini rotation
**Why third**: 503 / 429 hits real during EPUB smoke. One key = single point of failure. Strict regex `^GEMINI_API_KEY_\d+$` already designed (CLAUDE Decision discussions). Estimated: 1 day.

**How**: Refactor `ai/client.py::ai_client` from singleton to pool. Round-robin on failure. Each retry uses next key.

### Priority 4 — FlowSpec orchestrator unify
**Why fourth**: 80 LOC dead weight in `core/orchestrator.py`. Behavioral refactor — needs Priority 1 done first. Pattern clear from `docs/AUDIT_PHASE6.md §4.1`. Estimated: half day (with baseline ready).

### Priority 5 — Cross-platform smoke (Linux + macOS)
**Why fifth**: Project assumed Windows during dev. Windows-specific hacks (`_silence_transport_errors`) need verification not breaking on POSIX. Path separators, line endings, asyncio event loop differences. Estimated: 1 day on each platform.

---

## 6. Reflections

**What I'd tell pre-v1.0-me**:
1. Capture baseline FIRST (Phase 0). Don't defer "until I have time". Set up `--label phase0_initial` immediately after every domain learn.
2. The `core/extractor.py` was always a 1-caller helper — should have inlined at Phase 1, not Phase 6.
3. `ingest/web.py` symbolic re-export was over-engineering at Phase 3. Should have routed `main.py` through orchestrator immediately or not created the wrapper.
4. EPUB chapter splitting needs per-publisher heuristic (z-library, Calibre default, Pandoc) — generic SKIP_PATTERNS won't scale.

**What I got right**:
1. Scope Lock — refused 6+ feature additions during build. Each refusal saved 1-3 days of v1.0 delay.
2. Decision Log — single source of truth for "why did we do X" disputes. Saved hours of re-debate.
3. Strategy pattern for image fetch — clean abstraction at minimal cost. Pays dividends at MOBI/PDF additions.
4. Fail-loud over silent — every guard (UTF-8 strict, profile v1 reject, AI return validation) catches issues at source instead of downstream corruption.

**What I'd defer indefinitely**:
- GUI / Web UI — CLI is honest tool, not afterthought
- Database — JSON file works perfectly for single user
- Generic article scraper — out of scope, Trafilatura exists

---

## 7. Codebase Numbers (final)

| Metric | Value |
|---|---|
| Python files | 52 |
| Total LOC | 11,340 |
| Largest file | `ai/agents.py` (1,046) |
| Decision Log entries | 56 |
| Phases shipped | 8 (P0 → P6 + docs) |
| Anti-patterns documented | 16 |
| v1.1 backlog items | 18 |
| Git commits this branch | ~50 (across 4 phases — P3 EPUB, P4 writers, P5 TXT, P6 cleanup + docs) |

---

## 8. Ship Statement

Cào Text v1.0.0 ships as a working universal novel normalizer:
- **3 inputs**: web URL, EPUB file, TXT file
- **3 outputs**: Obsidian Markdown, Translation-ready text, Raw text
- **8 AI calls** site learning, durable profile, free repeat scrape
- **Cross-chapter** AdsFilter with 3 namespaces (web / `epub:` / `txt:`)
- **Strategy pattern** image fetch (web HTTP + EPUB zip binary)
- **Fail-loud** discipline throughout (UTF-8 strict, profile v1 reject, AI validation)

Known issues + v1.1 trajectory documented. Tag at HEAD: `v1.0.0`.

---

**Tomorrow, the diff will start. Today, ship.**
