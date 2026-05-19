# v1.1+ Backlog

> Consolidated list of features deferred from v1.0 and now v1.1.0. Each item has a rationale (why not now) and a trigger condition (when to revisit).
>
> **Source**: CLAUDE.md §3 DEFERRED list + ROADMAP.md Phase 7+ + per-phase retrospective deferrals + v1.0 smoke test bugs + v1.1 session output.
>
> **Updated**: 2026-05-18 (post v1.1.0 ship — see status table below)

---

## Status After v1.1.0 (2026-05-18)

| Item | Status | Notes |
|---|---|---|
| P1 Baseline capture infrastructure   | ⏳ deferred | Still blocks behavioral refactors |
| P2 EPUB Bug 1 (title path fallback)  | ✅ done v1.0.13 | `_title_from_url` rejects file paths |
| P2 EPUB Bug 2 (image href relative)  | ✅ done v1.0.13 | 4-strategy fallback + basename match |
| P2 EPUB Bug 3 (over-split)           | ✅ done v1.1.0  | `_merge_dividers` Part/Level/Book |
| P2 Web --output-dir CLI ignored      | ✅ done v1.1.0  | `_output_dir(url, base=None)` |
| P3 Multi-key Gemini rotation         | ✅ done v1.1.0  | `ApiKeyPool` + cooldown |
| P4 FlowSpec orchestrator unify       | ⏳ deferred | Blocked by P1 baseline |
| P5 Cross-platform smoke              | ⏳ deferred | Windows-only verified so far |
| P6 DomainSessionPool per-host cap    | ✅ done v1.2.0  | `PER_HOST_MAX_CONCURRENCY=3` default, `--per-host-concurrency N` CLI override |
| 2.2 Calibration phase                | ✅ done v1.1.0  | 3-dim probe post-Master-Synthesis |

---

## 0. Priority Order (top 5 = v1.2 critical path)

| Rank | Item | Section | Rationale |
|------|------|---------|-----------|
| **P1** | Baseline capture infrastructure | new §0.1 | Unlocks every other behavioral refactor. Currently blocking 5-10% LOC reduction target. |
| **P2** | EPUB extraction bug fixes (title path fallback + image href + over-aggressive splitting) | new §0.2 | User-visible regression from v1.0 smoke. EPUB users see ugly filenames + broken images. |
| **P3** | Multi-key Gemini rotation | new §0.3 | 503 / 429 spikes hit real during smoke. Single-key SPOF. |
| **P4** | FlowSpec orchestrator unify | §1.1 | 80 LOC dead weight. Blocked by P1. |
| **P5** | Cross-platform smoke (Linux + macOS) | new §0.5 | Project Windows-first by accident. Need verification. |
| **P6** | DomainSessionPool per-host concurrency cap (safety-by-default) | new §0.6 | Dangerous default: no semaphore → burst 100 concurrent → IP ban likely. Not perf — safety. |

Everything below P6 is "nice to have when motivated" — none blocking.

### 0.1 — P1: Baseline capture infrastructure

**Why**: `tools/snapshot_baseline.py` exists but never run. `data/baselines/` only has `.gitkeep`. Every behavioral refactor (FlowSpec §1.1, image stage extract §1.2) blocked.

**Trigger**: First v1.1 session. Mandatory before any refactor.

**Spec**: Capture 3 web sites (after learning) + 2 EPUBs + 2 TXTs. Commit to `data/baselines/`. Diff against v1.1 refactor branches.

**Effort**: 1 session (~2-3 hours with API quota available).

### 0.2 — P2: Smoke-surfaced bugs (EPUB + Web)

#### 2.0 Web `--output-dir` CLI flag ignored (NEW — found 2026-05-17 web smoke)

**Symptom**: `python main.py --output-dir foo/bar links.txt` writes to `output/{slug}/` not `foo/bar/{slug}/`.

**Cause**: `main.py::_output_dir(url)` hard-codes `config.OUTPUT_DIR` constant. Web flow uses `_output_dir()` directly; `RunConfig.output_dir` (from CLI parse) only flows to EPUB/TXT orchestrator paths.

**Fix**: `_output_dir(url, base=None)` accepts override → `base or OUTPUT_DIR`. Caller in `main()` passes `run_config.output_dir`. Same for `_progress_path` (currently keys on `_output_dir`, so progress collides across modes when --output-dir not respected).

**Effort**: 30 min + smoke re-test.

#### 2.1 EPUB extraction bugs (original P2 content)

**Why**: Live smoke (Ready Player One.epub) surfaced 3 bugs:

**Bug 1 — Title fallback returns source path**:
- Symptom: `0004_Users<user>DesktopSmall_ProjectCào_TextReady_Player_One_(Ernest_Cline)1_(Z.md`
- Cause: Title chain falls through to `_title_from_url` which treats file path like URL
- Fix: Skip `_title_from_url` if input is local file path (no `://` scheme)

**Bug 2 — Image href relative-path miss**:
- Symptom: `[EpubImageExtractor] href not found: ../images/img19.jpg`
- Cause: EPUBs use various conventions (`../images/`, `OEBPS/images/`, absolute zip paths)
- Fix: Resolve href against chapter HTML's location inside zip + try common fallback paths

**Bug 3 — Over-aggressive chapter splitting**:
- Symptom: 52 "chapters" from Ready Player One (real chapter count ~40)
- Cause: SKIP_PATTERNS misses pirate-Z EPUB front matter (dedication, epigraph, acknowledgments)
- Fix: Expand SKIP_PATTERNS + add structural heuristic (file size threshold)

**Effort**: 1-2 days.

### 0.3 — P3: Multi-key Gemini rotation

**Why**: 503 UNAVAILABLE hit several times during EPUB AI image extract. Single `GEMINI_API_KEY` = SPOF.

**Spec sketch**:
```python
_KEY_RE = re.compile(r"^GEMINI_API_KEY(?:_\d+)?$")
ALL_KEYS = [v for k, v in os.environ.items() if _KEY_RE.match(k) and v]
# In AIRateLimiter: round-robin on retry
```

**Effort**: 1 day.

### 0.6 — P6: DomainSessionPool per-host concurrency cap (safety-by-default)

**Source**: V1.1 test session 2026-05-19 — review of original §7.2 surfaced this is NOT perf concern but a safety-by-default violation.

**Why**: Current `DomainSessionPool` reuses curl_cffi session per domain but has NO semaphore limiting concurrent in-flight requests per host. If batch run has 50 URLs same domain → 50 concurrent fetches → trivial trip into rate-limit / IP ban. Default behavior is dangerous; user must self-discover.

**Reframe**: Promote from §7.2 perf-deferred → P6 critical path because:
- Damage (IP ban a domain user relies on) is reactive trigger = too late
- Implement-once + default-ON has zero downside (`Semaphore(N=3)` is conservative enough not to slow learn phase)
- Aligns with project principle "fail-safe, not fail-silent" — current default is fail-silent dangerous

**Spec**: `DomainSessionPool.acquire(domain)` wraps `asyncio.Semaphore(N=3)` per-domain. Config `PER_HOST_MAX_CONCURRENCY=3` in `config.py`. CLI override `--per-host-concurrency N`.

**Trigger**: NOT reactive — implement proactively as v1.2 default. No "wait until ban" gate.

**Effort**: 2 hours + smoke test that learning phase 8-AI-calls still completes within timeout (concurrency limit may slow but not block).

### 0.5 — P5: Cross-platform smoke

**Why**: All dev on Windows. `_silence_transport_errors` (`main.py:471`) is Windows-specific hack. Path separators, line endings, asyncio event loop differences untested elsewhere.

**Spec**: Run full 3-mode smoke on Ubuntu 22.04 + macOS Sonoma. Document any divergence.

**Effort**: 1 day per platform.

---

---

## How to use this file

When a deferred item becomes urgent:
1. Find it below
2. Re-read the **Rationale** — is the original blocker still valid?
3. If trigger condition met → spec it out, add to a fresh `ROADMAP_v1.1.md`
4. **Do not** add to v1.0 codebase without explicit scope review

When user proposes "wouldn't it be cool if..." feature:
1. Cross-check against this list — likely already considered
2. If new, add row here with **Rationale: not in v1.0 scope** before any code

---

## 1. Behavioral Refactors (Phase 6 deferred)

### 1.1 FlowSpec — unify `run_epub_flow` + `run_txt_flow`

**Source**: docs/AUDIT_PHASE6.md §4.1, CLAUDE Decision #55

**Savings**: ~80 LOC

**Rationale defer**:
- 80% duplicate code between two flows in `core/orchestrator.py:90-314`
- Behavioral refactor → needs `tools/snapshot_baseline.py` capture first
- `data/baselines/` empty (only `.gitkeep`) — never captured

**Trigger**:
- User captures baseline for at least one EPUB + one TXT
- Adds 3rd file-based adapter (vd MOBI, PDF) → 3 flows = 240% duplicate, refactor mandatory

**Spec sketch**:
```python
@dataclass
class FlowSpec:
    adapter_iter: AsyncIterator[RawDocument]  # ingest_epub | ingest_txt
    namespace: str                            # "epub" | "txt"
    banner_emoji: str                         # "📖" | "📄"
    post_chapter_hook: Callable | None        # image stage (epub) or lang tag (txt)

async def _run_file_flow(spec: FlowSpec, run_config, ai_limiter): ...
```

### 1.2 `_apply_image_stage` extract to shared helper

**Source**: docs/AUDIT_PHASE6.md §5.3, CLAUDE Decision #49

**Savings**: ~60 LOC

**Rationale defer**:
- Touches `core/scraper.py` — shared logic, STOP §10
- Same 3-branch mode dispatch between `core/scraper.py::_apply_image_stage` and `core/orchestrator.py::_apply_epub_image_stage` — only fetcher class differs
- Decision #49 explicit: defer to P6, accepted short-term duplication

**Trigger**:
- Adding 3rd image source (vd MOBI, web archive) → 3 copies = mandatory extract
- User OKs touching `core/scraper.py` + has baseline

**Spec sketch**: `core/image_pipeline/stage.py::apply_image_stage(content, image_refs, run_config, fetcher: ImageFetchStrategy, ...) -> str`

---

## 2. Web Learning Enhancements

### 2.1 Case-based learning cho web (similar to TXT case DB)

**Source**: CLAUDE Decision #15

**Rationale defer**: Premature design. Need 10+ profile in `data/site_profiles.json` to see real pattern. Currently ~5 — sample size too small to abstract.

**Trigger**: 10+ committed profiles + observable pattern recurrence across them.

### 2.2 Calibration Phase — re-probe 10 chapters to verify profile

**Source**: CLAUDE §16

**Rationale defer**: Plan exists but defer v1.1 — adds ~5min AI cost per re-learn. Optional QC step, not required for v1.0 ship.

**Trigger**: User reports profile rot after site update with no `!relearn` triggered.

---

## 3. i18n Expansion

### 3.1 Site CJK hardening (Trung / Nhật / Hàn raw)

**Source**: BLUEPRINT §1, CLAUDE Decision #20, §3 DEFERRED

**Scope**:
- Encoding heuristic (charset-normalizer integration)
- Font deobfuscation (some Chinese pirate sites)
- Slugify pinyin / katakana
- Chapter regex: `第N章` / `第N話` / `제N장`

**Rationale defer**: i18n hardening = separate engineering subproject. v1.0 UTF-8 baseline + Latin chapter pattern enough for primary use case (EN + VN + EN-translated content).

**Trigger**: User starts scraping native CJK source regularly.

### 3.2 TXT v1.1 — expanded language cases

**Source**: BLUEPRINT §3 MODE C, ROADMAP Phase 7+

**Scope**: CJK chapter pattern support in `data/txt_cases.json` (currently 6 VN/EN cases).

**Rationale defer**: Phase 5 narrowed scope explicitly (Decision #21) — VN + EN passed exit ramp. CJK addition needs encoding heuristic (3.1) first.

**Trigger**: 3.1 done → CJK cases trivial to add.

---

## 4. Output Format Extensions

### 4.1 Frontmatter customization

**Source**: ROADMAP Phase 7+

**Scope**:
- `--no-frontmatter` flag
- `--frontmatter-fields title,source,chapter` custom field selection
- Custom YAML field injection

**Rationale defer**: Current minimal frontmatter (title, source, chapter_index, source_url, failed_images) handles 95% Obsidian use case. Customization adds API surface — wait for concrete user need.

**Trigger**: User asks for tag generation or custom Obsidian dataview integration.

### 4.2 TranslationWriter chunking

**Source**: CLAUDE Decision #45

**Scope**: `RunConfig.chunk_threshold` exposed as CLI flag. Auto-split chapter at threshold → `0042_part1.txt`, `0042_part2.txt`.

**Rationale defer**: Modern LLMs (Gemini 1M, Claude 200K, GPT-4o 128K) handle 30k chars no split. Default OFF. Currently configurable only via code edit.

**Trigger**: User uses LLM with <50K context regularly.

### 4.3 Inline link preservation

**Source**: CLAUDE.md §3 DEFERRED

**Rationale defer**: Novel chapter rarely has meaningful inline link. Cost of preservation vs noise filter trade-off favors strip in v1.0.

**Trigger**: User scrapes blog-style fiction with intentional cross-link.

---

## 5. Infrastructure / DX

### 5.1 Multi-AI provider support (Claude / OpenAI)

**Source**: README FAQ

**Rationale defer**: Hard-coded Gemini in `ai/client.py` + `ai/agents.py` (60+ call sites). Free tier covers personal use. Rewrite = full pass.

**Trigger**: Gemini deprecates free tier OR user wants Claude for quality/cost reasons.

### 5.2 TypedDict refactor `utils/types.py`

**Source**: CLAUDE Decision #16, P3-D from prior session

**Rationale defer**: High-risk, not blocking. `dict[str, Any]` works. TypedDict gains type safety but introduces strict shape requirement → migration breaks existing profiles.

**Trigger**: Adds 3rd dev / introduces test framework (5.6 below).

### 5.3 GUI (Streamlit / native)

**Source**: README FAQ, ROADMAP Phase 7+

**Rationale defer**: CLI sufficient for solo dev personal use. GUI = separate sub-project.

**Trigger**: User shares tool with non-CLI users (family, friends).

### 5.4 Bulk concurrent multi-domain optimization

**Source**: ROADMAP Phase 7+

**Rationale defer**: Already runs in parallel via `asyncio.gather` per URL. Optimization would be at fetch layer (per-domain rate limit pool) — micro-optimization, current setup OK.

### 5.5 Manhua adapter (image-primary pipeline)

**Source**: CLAUDE §3 DEFERRED

**Rationale defer**: Different project. Gallery-dl already solves manhua well. Out of Cào Text scope.

**Trigger**: Never (or fork project).

### 5.6 Formal test framework (pytest + pytest-asyncio)

**Source**: CLAUDE Decision #17

**Rationale defer**: Solo dev, ROI low. Smoke test + baseline diff is the v1.0 regression strategy.

**Trigger**: Adds 2nd dev / open-source the project.

### 5.7 Lint / format toolchain (ruff / black)

**Source**: CLAUDE §4 Tech Stack ("None currently")

**Rationale defer**: Solo dev, code style stays consistent via Claude. Mass-format = noisy diff over real changes.

**Trigger**: Multiple contributors.

---

## 6. Web framework / API

### 6.1 Web UI / Streamlit / FastAPI

**Source**: CLAUDE §3 DEFERRED

**Rationale defer**: CLI tool, local single-user. No remote use case.

**Trigger**: Multi-user scenario.

### 6.2 Database (SQLite)

**Source**: CLAUDE §4 FORBIDDEN

**Rationale defer**: JSON file + atomic write covers single-user single-process. SQLite adds dep + migration concerns for zero benefit.

**Trigger**: Concurrent multi-process write becomes a thing.

---

## 7. Test Session Findings (2026-05-19)

> Test session: syntax + import sanity + hot-path benchmark + nav_injector scaling + pyflakes lint.
> Result: code healthy. Hot paths sub-millisecond. nav_injector linear O(N). No critical bug surfaced.
>
> **Review applied 2026-05-19**: section originally had 6 items. User audit found 3/6 speculative (no observed evidence) → demoted to §7.99. 7.2 promoted to §0 critical path (safety-by-default). 7.4 kept with effort note. 7.6 trivial.

### 7.1 Branch 136 — `--check-new` flag + age skip

**Source**: V1.1 test session 2026-05-19 — observed cost of branch 136 (just fixed, HEAD `ae5b921`).

**Symptom**: Every run re-verifies completed stories — 1 HTTP request per completed story even if site dead 2 years. Batch with 100 completed stories → 100 HTTP startup cost ~30-60s.

**Spec**:
- `--check-new` CLI flag (default ON) — toggle re-verify completed
- `--skip-check-after-days N` (default 90) — skip re-verify if `completed_at` older than N days
- Manual override `!recheck domain.com` in `links.txt`
- ProgressDict schema add: `completed_at: ISO timestamp` field (set when `completed=True` is written)

**Trigger**: User has 50+ completed stories AND batch run feels sluggish at startup (measurable >20s startup before first chapter).

**Effort**: 1 day (CLI parse + ProgressDict schema migration + `!recheck` parser + backward-compat read for old progress files missing `completed_at`). Em initial estimate "4h" underestimated — schema migration + parser align với existing `!relearn` adds work.

### 7.2 Linting cleanup (pyflakes findings)

**Source**: V1.1 test session 2026-05-19 — pyflakes 3.4.0 scan.

**Items**:
- `learning/phase.py:29` — `fetch_page` import unused
- `ai/agents.py:1183` — f-string missing placeholders

**Effort**: 5 minutes. Bundle with next routine cleanup commit.

### 7.99 Speculative perf concerns (NO observed evidence — DO NOT implement without measured data)

> **Gate**: items below were added based on theoretical concern during test design, not observed pain. Per project anti-pattern #11 (premature optimization) — these are kept only as future-reference. Revisit ONLY when concrete metric breaches threshold.
>
> **Why kept**: documenting reasoning trail. Removing entirely loses context for future "why didn't we shard profiles?" questions.

| Concern | Theoretical issue | Measurement gate to revisit |
|---|---|---|
| ProfileManager per-domain shard | Full rewrite of `site_profiles.json` on every flush | Measured `flush()` latency >100ms with real N profiles (NOT "user has 50+") |
| IssueReporter stream-write | RAM accumulation 24h+ run → OOM | Real OOM report OR measured `IssueReporter.entries` >100MB RSS contribution |
| nav_injector JSON sidecar cache | End-of-session pause 13s @5000ch | User explicitly requests per-chapter nav refresh (then sidecar is the spec, not the perf workaround) |

If a gate breaches → spec it out fresh, don't resurrect this section.

---

## Summary Table

| # | Item | Category | Trigger |
|---|------|----------|---------|
| 1.1 | FlowSpec orchestrator unify | Refactor | Baseline + new adapter |
| 1.2 | Image stage shared helper | Refactor | Baseline + new image source |
| 2.1 | Case-based web learning | Learning | 10+ committed profiles |
| 2.2 | Calibration phase | Learning | Reported profile rot |
| 3.1 | CJK i18n hardening | i18n | User wants native CJK |
| 3.2 | TXT v1.1 CJK cases | i18n | After 3.1 |
| 4.1 | Frontmatter customization | Output | Dataview integration request |
| 4.2 | TranslationWriter chunking | Output | Small-context LLM use |
| 4.3 | Inline link preservation | Output | Blog-style scrape request |
| 5.1 | Multi-AI provider | Infra | Gemini deprecation / quality switch |
| 5.2 | TypedDict refactor | Infra | 2nd dev / test framework |
| 5.3 | GUI | Infra | Non-CLI user |
| 5.4 | Multi-domain concurrent | Infra | Real bottleneck observed |
| 5.5 | Manhua adapter | Infra | Never (use gallery-dl) |
| 5.6 | pytest framework | Infra | 2nd dev / open-source |
| 5.7 | Lint toolchain | Infra | Multiple contributors |
| 6.1 | Web UI / API | Infra | Multi-user scenario |
| 6.2 | Database | Infra | Multi-process concurrent write |
| 0.6 | DomainSessionPool per-host cap (P6) | Safety | ✅ done v1.2.0 |
| 7.1 | Branch 136 `--check-new` flag + age skip | Perf | Measured >20s startup with 50+ completed stories |
| 7.2 | Pyflakes cleanup | Code health | Bundle with next routine commit |
| 7.99 | Speculative perf (3 items) | Perf | Measured threshold breach (NOT theoretical "user has N") |
