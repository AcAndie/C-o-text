# v1.1+ Backlog

> Consolidated list of features deferred from v1.0. Each item has a rationale (why not v1.0) and a trigger condition (when to revisit).
>
> **Source**: CLAUDE.md §3 DEFERRED list + ROADMAP.md Phase 7+ + per-phase retrospective deferrals.
>
> **Updated**: 2026-05-17 (v1.0 ship)

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
