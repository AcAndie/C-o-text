# ROADMAP.md — Cào Text v1.0 Execution Plan

> **File này là lộ trình thực thi cụ thể.** CLAUDE.md nói **HOW + WHY**, BLUEPRINT.md nói **WHAT trong tổng thể**, file này nói **WHAT theo thứ tự + ACCEPTANCE per step**.
>
> Vibe coder dùng file này như checklist. Claude Code dùng file này để biết đang ở step nào, step kế là gì.

---

## 0. Cách dùng file này

1. Step được đánh số `P{phase}.{step}` — ví dụ `P1.3` = Phase 1, Step 3
2. Mỗi step có: **Mục tiêu**, **Files động vào**, **Acceptance**, **Rủi ro**, **Phụ thuộc**
3. KHÔNG skip step. KHÔNG đảo thứ tự trừ khi có lý do mạnh + user confirm
4. Mỗi step xong → commit conventional + check off → next step
5. Step fail → STOP, không "fix forward", revert + diagnose
6. **Phase có dependency** (vd Phase 2 cần RunConfig từ Phase 1) — KHÔNG bắt đầu cho đến khi dependency phase done

**Tracking:** mark `[x]` khi step done, ghi note bên cạnh nếu có deviation.

**Quan trọng — thay đổi v1.1 so với v1.0:**
- **Phase 1 = Output Abstraction** (cũ là Phase 2). **Phase 2 = Image Support** (cũ là Phase 1). Lý do: image policy per-mode cần RunConfig trước.
- **P0.0 mới** — baseline snapshot trước Batch A/B
- **P5 narrowed** — VN + EN only, có exit ramp
- **README maintained xuyên suốt**, không defer cuối

---

## Phase 0 — Cleanup + Foundation

> **Mục tiêu phase:** giảm ~780 dòng dead code + setup regression guard + UX hỗ trợ migration. Foundation sạch trước khi build mới.
>
> **Thời gian ước tính:** 3-4 ngày
>
> **Tiền điều kiện:** codebase ở trạng thái "Batch A/B plan đã chốt" (xem CLAUDE.md §17 Decision #9).

### P0.0 — Baseline Snapshot Tool + Capture — ⚠️ PARTIAL (2026-05-16)

> Tool + structure created. Live capture (FFN + RR baselines) deferred — chưa có profile thật trong repo. User phải `python main.py links.txt` learn FFN+RR trước, sau đó chạy snapshot script. Refactor Phase 1.5 sẽ buộc tạo baseline trước.

- [x] **Mục tiêu:** regression guard cứng cho mọi refactor lớn từ Phase 0 trở đi
- [ ] **Files động vào:**
  - `tools/__init__.py` (create)
  - `tools/snapshot_baseline.py` (create ~80 dòng)
  - `data/baselines/` (create dir, KHÔNG gitignore — committed)
  - `data/baselines/.gitkeep`
  - `.gitignore` (whitelist `data/baselines/`)
- [ ] **Logic `snapshot_baseline.py`:**
  - Args: `--profile <domain> --chapters <N> --label <name>`
  - Chạy scrape giống `main.py` nhưng output vào `data/baselines/{label}/`
  - Lưu config snapshot vào `data/baselines/{label}/_meta.json` (URL, chapter range, profile hash, timestamp)
  - Không upload progress JSON, không update site_profiles (read-only run)
- [ ] **Bước:**
  1. Code script
  2. Run: `python tools/snapshot_baseline.py --profile fanfiction.net --chapters 5 --label phase0_ffn`
  3. Run: `python tools/snapshot_baseline.py --profile royalroad.com --chapters 5 --label phase0_rr`
  4. Verify `data/baselines/phase0_ffn/` có 5 file Markdown + `_meta.json`
- [ ] **Acceptance:**
  - 2 baseline label tồn tại với 5 chapter mỗi cái
  - Script chạy lại idempotent (overwrite + log)
  - `_meta.json` ghi đủ context để reproduce
- [ ] **Rủi ro:**
  - Profile FFN/RR có thể đã drift — snapshot bây giờ phản ánh state hiện tại, đó là intended baseline
  - Tool dùng full pipeline → bug trong pipeline cũng được snapshot. Đó cũng là intended (baseline = current behavior).
- [ ] **Commit:** `chore(tools): add baseline snapshot script for regression diff`
- [ ] **Phụ thuộc:** none

### P0.1 — Branch + Tag — ✅ DONE 2026-05-16

> Branch `cleanup-batch-ab` + tag `pre-cleanup-v0.x` tồn tại.

- [x] **Mục tiêu:** safety net trước khi cắt code lớn
- [ ] **Bước:**
  1. `git status` — verify clean working tree
  2. `git checkout -b cleanup-batch-ab`
  3. Tag current state: `git tag pre-cleanup-v0.x`
  4. Push tag: `git push origin pre-cleanup-v0.x` (nếu có remote)
- [ ] **Acceptance:** branch mới tạo, tag hiện trong `git tag -l`
- [ ] **Rủi ro:** none

### P0.2 — Batch A: Xóa `learning/optimizer.py` — ✅ DONE 2026-05-16

> Commit `07ecec4`. Optimizer + stale refs đi. `--fast-learning` đổi semantic sang "skip ProseRichness validation" (CLAUDE §17 Decision #26). Baseline diff deferred cùng với P0.0 capture.

- [x] **Mục tiêu:** xóa ~450 dòng — optimizer "AI scoring AI" không add signal
- [ ] **Files động vào:**
  - `learning/optimizer.py` (delete)
  - `learning/phase.py` (remove import + call site)
  - `learning/phase_ai.py` (đã từng có ref tới AI#8/AI#9 — verify đã clean)
  - `config.py` (remove constants liên quan: `OPTIMIZER_*`)
  - `main.py` (`--fast-learning` flag: keep, semantic change — giờ skip ProseRichness validation thay vì optimizer; document trong help text)
- [ ] **Bước:**
  1. `grep -rn "optimizer" --include="*.py"` — list mọi import
  2. View từng call site, plan removal
  3. Delete file
  4. Remove import statements
  5. Smoke test: `python main.py links.txt` với 1 URL FFN test
  6. **Baseline diff:** chạy lại snapshot label `phase0_ffn` (5 chapter), `diff -r data/baselines/phase0_ffn/ output/<ffn_story>/` — phải identical (vì optimizer chỉ ảnh hưởng learning, không ảnh hưởng scrape output trên profile đã có)
- [ ] **Acceptance:**
  - File `learning/optimizer.py` không còn
  - Không có ImportError khi import bất kỳ module nào
  - Smoke test chạy thành công, scrape được ít nhất 3 chapter
  - **Baseline diff ZERO difference** (cùng profile, cùng URL → cùng output)
  - Profile mới learn được không có field `optimizer_score`
- [ ] **Rủi ro:**
  - Profile cũ có thể có `optimizer_score` field — phải tolerate (TypedDict total=False đã handle)
  - `--fast-learning` semantic đổi — document rõ trong CLAUDE.md §17 + help text
- [ ] **Commit:** `refactor(learning): xóa optimizer.py (Batch A) — xoá 450 dòng dead code`
- [ ] **Phụ thuộc:** P0.0 (baseline), P0.1 (branch)

### P0.3 — Batch B: Xóa `StepConfig/ChainConfig/PipelineConfig` serialization — ✅ DONE 2026-05-16

> Commit `ce72f3a`. `learning/migrator.py` xóa (81 dòng). `core/scraper.py` migration block xóa. `ProfileManager.get()` raise `ValueError` cho profile v1 (có `pipeline` field) — fail-loud thay vì auto-migrate silent. CLAUDE §17 Decision #27.

- [x] **Mục tiêu:** xóa ~330 dòng — root cause bug M4 (nested params lost roundtrip)
- [ ] **Files động vào:**
  - `pipeline/base.py` (remove `StepConfig`, `ChainConfig`, `PipelineConfig` classes nếu còn — verify clean)
  - `pipeline/executor.py` (remove `_make_block`, ensure `from_profile` đọc thẳng SiteProfile)
  - `learning/migrator.py` (delete — ~150 dòng, không còn cần migrate v1→v2 vì v1 đã chết)
  - `utils/types.py` (verify `SiteProfile` không còn `pipeline` field)
  - `learning/profile_manager.py` (remove migration call)
- [ ] **Bước:**
  1. `grep -rn "StepConfig\|ChainConfig\|PipelineConfig" --include="*.py"` — verify state
  2. `grep -rn "migrator\|migrate" --include="*.py"` — list usage
  3. Delete `learning/migrator.py`
  4. Remove call site trong `profile_manager.py`
  5. Smoke test với 2 site khác nhau (FFN + RR), verify both work với profile cũ
  6. **Baseline diff:** chạy lại snapshot cho cả 2 label, diff phải zero
- [ ] **Acceptance:**
  - File `learning/migrator.py` không còn
  - Profile mới không có `pipeline` flat dict, không có `requires_relearn`
  - Smoke test: 2 site, scrape 5 chapter mỗi site, 0 error
  - **Baseline diff ZERO** cho cả 2 label
  - `data/site_profiles.json` không có legacy field sau khi xóa migrator
- [ ] **Rủi ro:**
  - Profile cũ có `pipeline` field — đã quyết định: dùng `--bulk-relearn` thủ công. Không auto-migrate.
  - Nếu baseline diff KHÔNG zero → STOP, debug. Có thể migrator đang silently fix profile khi load.
- [ ] **Commit:** `refactor(pipeline): xóa StepConfig serialization (Batch B) — xoá 330 dòng`
- [ ] **Phụ thuộc:** P0.2 done + baseline diff pass

### P0.4 — README.md skeleton — ⏸ DEFERRED

> README.md hiện là placeholder ("Sẽ cập nhật lại sau!!!"). Skeleton chưa viết. CLI flag stable sau P0.5, có thể làm bất kỳ lúc nào trước Phase 1 ship. Defer không block phase tiếp.

- [ ] **Mục tiêu:** user-facing quick start, maintain throughout
- [ ] **Files động vào:**
  - `README.md` (create ~100 dòng)
- [ ] **Nội dung tối thiểu:**
  - 1 dòng tagline
  - Install: `pip install -r requirements.txt` (hoặc `uv sync`)
  - Quick start: tạo `.env` với GEMINI_API_KEY, tạo `links.txt`, chạy `python main.py links.txt`
  - CLI flag chính: `--output-mode`, `--max-pw`, `--fast-learning`, `--no-validation`, `--bulk-relearn`
  - `!relearn <domain>` syntax trong links.txt
  - Folder structure overview (input/output/data/progress)
  - Limitations: chỉ Latin chapter pattern v1.0, CJK defer
- [ ] **Acceptance:**
  - Reader mới clone repo + đọc README có thể chạy được sau 5 phút
  - Mọi CLI flag hiện hữu được liệt kê
- [ ] **Rủi ro:** none — pure documentation
- [ ] **Commit:** `docs: add README.md with quick start guide`
- [ ] **Phụ thuộc:** P0.2 + P0.3 (CLI flag state stable)

### P0.5 — Bulk Relearn Script + MIGRATION_NOTES — ✅ DONE 2026-05-16

> Commit `d483a1e`. `main.py --bulk-relearn [--pattern <regex>] [--apply]`. UX an toàn: dry-run default, typed confirm `"delete N profiles"` khi apply. `docs/MIGRATION_NOTES.md` hướng dẫn 3 option. Tangential fix: escape `%%` trong `--fast-learning` help (Python 3.14 strict).

- [x] **Mục tiêu:** UX cho user có profile cũ sau breaking schema
- [ ] **Files động vào:**
  - `tools/bulk_relearn.py` (create ~50 dòng) HOẶC inline trong `main.py` với flag `--bulk-relearn`
  - `main.py` (parse `--bulk-relearn [--pattern <regex>]`)
  - `docs/MIGRATION_NOTES.md` (create)
- [ ] **Logic `--bulk-relearn`:**
  - Không cần `links.txt` (or accept empty list)
  - Load `data/site_profiles.json`
  - Filter theo `--pattern` nếu có (vd `--pattern "fanfiction|royalroad"`)
  - Print danh sách domain sẽ xóa
  - Confirm prompt (Y/N)
  - Delete keys, save atomic
- [ ] **MIGRATION_NOTES.md:**
  - "Breaking changes ở Batch A/B"
  - "Profile cũ có thể có `optimizer_score` (Batch A) hoặc `pipeline` flat dict (Batch B) — không tự động migrate"
  - "Cách re-learn: `python main.py --bulk-relearn` hoặc `!relearn <domain>` per-site trong links.txt"
- [ ] **Acceptance:**
  - `python main.py --bulk-relearn --pattern "test"` xóa đúng profile match pattern
  - Confirm prompt rõ ràng, không silent
  - MIGRATION_NOTES.md cho user biết phải làm gì
- [ ] **Rủi ro:**
  - Bulk delete sai pattern → mất profile thật. Confirm prompt + dry-run mode default
- [ ] **Commit:** `feat(cli): add --bulk-relearn flag + migration docs`
- [ ] **Phụ thuộc:** P0.3 done

### P0.6 — Sync docs sau cleanup — ✅ DONE 2026-05-16

> CLAUDE.md §17 thêm Decision #26 (Batch A) + #27 (Batch B). BLUEPRINT.md §10 Phase 0 checkboxes marked. ROADMAP.md (file này) — status header mỗi P0.x.

- [x] **Mục tiêu:** CLAUDE.md / BLUEPRINT.md / ROADMAP.md đồng bộ với code reality
- [ ] **Files động vào:**
  - `CLAUDE.md` (verify §17 Decision Log có entry Batch A/B)
  - `BLUEPRINT.md` (verify §10 Phase 0 marked done)
  - `ROADMAP.md` (file này, mark P0 checkboxes)
- [ ] **Acceptance:**
  - 3 docs đồng bộ, không nhắc StepConfig/optimizer như tính năng hiện hữu
- [ ] **Rủi ro:** none
- [ ] **Commit:** `docs: sync governance after Batch A/B cleanup`
- [ ] **Phụ thuộc:** P0.2, P0.3 done

### P0.7 — Merge + full smoke test — ⚠️ PARTIAL 2026-05-16

> Merge `cleanup-batch-ab` → `main` + tag `v0.x-post-cleanup`. Baseline regression diff + live learn smoke test SKIP (lý do: chưa có FFN/RR profile + baseline trong repo, cần API key + network — user phải làm tay sau).

- [ ] **Bước:**
  1. `git status` — verify clean
  2. `git log cleanup-batch-ab --oneline` — verify commits conventional
  3. **Full regression test:** chạy lại 2 baseline snapshot, diff phải zero
  4. Smoke test với 1 site mới (chưa có profile) → verify learning phase work end-to-end
  5. `git checkout main && git merge cleanup-batch-ab --no-ff`
  6. Tag: `git tag v0.x-post-cleanup`
- [ ] **Acceptance:**
  - Main branch có commits từ cleanup
  - Tag mới ở HEAD của main
  - Full smoke test pass
  - 2 baseline diff zero
- [ ] **Phụ thuộc:** P0.0 → P0.6 all done

---

## Phase 1 — Output Mode Abstraction

> **Mục tiêu phase:** introduce `RunConfig` + `CleanedChapter` DTO + `ChapterWriter` interface. `ObsidianWriter` implement đầu tiên (port từ `chapter_writer.py`).
>
> **Thời gian ước tính:** 1 tuần.
>
> **Tiền điều kiện:** Phase 0 done. Baseline snapshot tồn tại.
>
> **Tại sao Phase 1 (không phải Phase 2 cũ):** Image policy là per-mode → cần RunConfig trước. Đảo thứ tự = technical debt cố ý (Decision #17).

### P1.1 — Define `RunConfig` + CLI flag

- [ ] **Files động vào:**
  - `config.py` HOẶC `utils/types.py` (add `RunConfig` dataclass ~30 dòng)
  - `main.py` (add `--output-mode`, `--download-images / --no-download-images`, etc. flag)
- [ ] **Logic:**
  - Flag `--output-mode {obsidian,translate,raw}`, default `obsidian`
  - Default derivation: obsidian → download_images=True, image_placeholder=False, fetch_metadata=True
  - translate → download_images=False, image_placeholder=True, fetch_metadata=False
  - raw → download_images=False, image_placeholder=False, fetch_metadata=False
  - Override individual: `--download-images / --no-download-images`
  - Classmethod `RunConfig.from_cli(args)` (xem BLUEPRINT §8)
- [ ] **Acceptance:**
  - `python main.py --help` show new flags
  - RunConfig instance created đúng từ CLI args trong 3 mode
  - Default behavior không đổi (no flag = obsidian = behavior hiện tại)
- [ ] **Rủi ro:** none
- [ ] **Commit:** `feat(config): add RunConfig dataclass + CLI flag for output mode`
- [ ] **Phụ thuộc:** Phase 0 done

### P1.2 — Define `CleanedChapter` + `ImageRef` + `FormattingRules` DTOs

- [ ] **Files động vào:**
  - `pipeline/base.py` (add `ImageRef` dataclass + `CleanedChapter` dataclass, ~50 dòng)
  - `utils/types.py` (add `FormattingRules` TypedDict — explicit schema, xem BLUEPRINT §8)
- [ ] **Decision point:** đặt `CleanedChapter` ở `pipeline/base.py` (gần `PipelineContext`) hay `utils/types.py` (gần `SiteProfile`)?
  - **Quyết định mặc định:** `pipeline/base.py` vì nó là pipeline output contract. **Vẫn hỏi user khi code.**
- [ ] **Logic:**
  - Dataclass `CleanedChapter` theo BLUEPRINT §8
  - `source_url` và `source_path` mutually exclusive (one is None)
  - `ImageRef` có `source_type: Literal["web", "epub"]`
  - `FormattingRules.image_alt_strategy: Literal["preserve", "skip", "fallback_to_filename"]` thay cho boolean cũ
- [ ] **Acceptance:**
  - DTO importable, all fields có type hint
  - `FormattingRules` không còn `image_alt_text` boolean (Decision #23)
- [ ] **Rủi ro:**
  - Schema change `FormattingRules` → profile cũ có thể có `image_alt_text` field, cần tolerate (TypedDict total=False) + migration code đọc legacy field → map sang `image_alt_strategy`
- [ ] **Commit:** `feat(types): add CleanedChapter, ImageRef, FormattingRules DTOs`
- [ ] **Phụ thuộc:** P1.1

### P1.3 — `output/base.py`: ChapterWriter ABC

- [ ] **Files động vào:**
  - `output/__init__.py` (create)
  - `output/base.py` (create ~60 dòng)
- [ ] **Logic:**
  - ABC `ChapterWriter` với:
    - `def __init__(self, output_dir: str, run_config: RunConfig)`
    - `@abstractmethod async def write(self, chapter: CleanedChapter) -> Path`
    - `@abstractmethod def filename_for(self, chapter: CleanedChapter) -> str`
  - Helper methods chung: `_ensure_dir`, `_atomic_write_text` (encoding=utf-8 explicit)
- [ ] **Acceptance:**
  - Import OK, type checks pass
  - Không có concrete logic ở ABC
- [ ] **Rủi ro:** none
- [ ] **Commit:** `feat(output): add ChapterWriter ABC`
- [ ] **Phụ thuộc:** P1.2

### P1.4 — `ObsidianWriter` (port from `chapter_writer.py`)

- [ ] **Files động vào:**
  - `output/obsidian.py` (create ~180 dòng)
  - `core/chapter_writer.py` (KEEP cho đến P1.5 — sẽ delete sau khi pipeline refactor)
- [ ] **Logic:**
  - Port logic filename generation từ `chapter_writer.py` (giữ exact behavior)
  - Frontmatter YAML: `title`, `chapter_index`, `source_url` (nếu có), `source_path` (nếu EPUB), `story_name`, `language` (nếu metadata có)
  - Body: Markdown content (giữ y nguyên từ `CleanedChapter.body_markdown`)
  - Footer optional: `> Source: {url}` cho web mode
  - Image embed: nếu `chapter.images` có local_path, link relative path
- [ ] **Acceptance:**
  - Output file giống output hiện tại + frontmatter
  - Filename generation pattern không đổi (`0042_Chapter_Title.md`)
  - **Baseline diff:** sau khi refactor xong P1.5, output Markdown khớp baseline (chỉ thêm frontmatter — diff phải predictable)
- [ ] **Rủi ro:**
  - Breaking change cho user có Obsidian vault setup — document trong MIGRATION_NOTES.md (frontmatter mới)
  - User có thể không muốn frontmatter — add flag `--no-frontmatter` v1.1
- [ ] **Commit:** `feat(output): add ObsidianWriter with YAML frontmatter`
- [ ] **Phụ thuộc:** P1.3

### P1.5 — Pipeline produce `CleanedChapter` (REFACTOR LỚN — STOP)

- [ ] **🛑 STOP:** Đây là refactor shared logic theo CLAUDE.md §10. Hỏi user TRƯỚC khi code.
- [ ] **Mục tiêu:** refactor `core/scraper.py` để pipeline output là `CleanedChapter` thay vì ghi file trực tiếp
- [ ] **Files động vào:**
  - `core/scraper.py` (refactor `_scrape_loop` hoặc tương đương — return `CleanedChapter` thay vì write file)
  - `pipeline/executor.py` (verify `PipelineRunner.run()` return path)
  - `core/chapter_writer.py` (delete sau khi confirm ObsidianWriter cover hết feature)
- [ ] **Logic:**
  - PipelineRunner.run() return `CleanedChapter`
  - Caller (`run_novel_task`) nhận DTO, gọi `writer.write(chapter)`
  - Writer instance được tạo 1 lần per task, chọn theo `run_config.output_mode`
  - Image stage trong pipeline KHÔNG có ở P1.5 — chỉ stub (P2 sẽ add)
- [ ] **Bước:**
  1. Plan với template §8.1
  2. **HỎI USER** confirm trước khi code
  3. Code refactor
  4. **Baseline diff:** chạy snapshot 2 label, output Obsidian = baseline + frontmatter (diff phải có content giống hệt nhau, chỉ khác frontmatter YAML)
  5. Smoke test: 1 URL × 3 mode → 3 mode đều produce file
- [ ] **Acceptance:**
  - 5 chapter, output Markdown khớp với baseline (body identical)
  - Diff với baseline: chỉ thêm frontmatter, body không đổi
  - Translation mode + Raw mode produce file (placeholder Writer OK, P4 sẽ hoàn thiện)
- [ ] **Rủi ro:**
  - Refactor lớn — đụng `core/scraper.py` shared logic. STOP rule.
  - Phase 4 chưa làm → translate/raw mode dùng `ObsidianWriter` tạm OK, hoặc dùng stub writer trả về plain text
- [ ] **Commit:** `refactor(pipeline): introduce CleanedChapter DTO + writer abstraction`
- [ ] **Phụ thuộc:** P1.4 + user confirm

### P1.6 — Smoke test Phase 1 + baseline diff

- [ ] **Bước:**
  1. Chạy `python main.py --output-mode obsidian links.txt` với 1 URL
  2. Verify output có frontmatter + body đúng
  3. **Baseline diff:** `diff -u data/baselines/phase0_ffn/0001_*.md output/<ffn>/0001_*.md`
     - Expected: chỉ thêm phần frontmatter ở đầu, body identical
  4. Repeat cho RR baseline
- [ ] **Acceptance:**
  - Output Markdown khớp baseline + predictable frontmatter diff
- [ ] **Commit:** `test(phase1): baseline diff verified, Phase 1 done`
- [ ] **Phụ thuộc:** P1.5

---

## Phase 2 — Image Support cho Web Novel

> **Mục tiêu phase:** light novel với inline illustration scrape được, ảnh download local, Markdown embed đúng vị trí.
>
> **Thời gian ước tính:** 1-2 tuần
>
> **Tiền điều kiện:** Phase 1 done. RunConfig + CleanedChapter + ObsidianWriter đã hoạt động.

### P2.1 — `utils/image_url.py` resolver

- [ ] **Mục tiêu:** chuẩn hóa `<img>` URL về absolute, handle các case lazy-load
- [ ] **Files động vào:**
  - `utils/image_url.py` (create, ~80 dòng)
- [ ] **Logic:**
  - Input: `Tag` (BeautifulSoup img element) + `base_url`
  - Output: `str | None` (absolute URL hoặc None nếu data URI/invalid)
  - Cases: `src`, `data-src`, `data-original`, `data-lazy-src`, `srcset` (pick highest res), protocol-relative `//cdn.../`, relative `/img/`, data URI `data:image/...` (skip), absolute `https://...`
- [ ] **Bước:**
  1. Plan template §8.1
  2. Code function `resolve_image_url(tag, base_url) -> str | None`
  3. Test với 6 case khác nhau trong script test riêng
- [ ] **Acceptance:**
  - Function handle 6+ case, test pass
  - Data URI return None (không download blob inline)
  - Relative URL → absolute đúng với `urljoin`
  - `srcset` parsing chọn URL có largest descriptor
- [ ] **Rủi ro:** một số site dùng attribute non-standard — chấp nhận miss, log warning
- [ ] **Commit:** `feat(utils): add image_url resolver`
- [ ] **Phụ thuộc:** Phase 1 done

### P2.2 — `core/image_pipeline/` strategy infrastructure

- [ ] **Mục tiêu:** Strategy pattern cho image fetch — web HTTP vs EPUB binary cùng interface
- [ ] **Files động vào:**
  - `core/image_pipeline/__init__.py` (create)
  - `core/image_pipeline/base.py` (create ~50 dòng — `ImageFetchStrategy` ABC + `download_batch` helper)
  - `core/image_pipeline/web_fetcher.py` (create ~150 dòng — `WebImageFetcher`)
- [ ] **Logic `WebImageFetcher`:**
  - Class nhận `DomainSessionPool` + `output_dir`
  - Method `async def fetch(ref: ImageRef) -> bytes | None`
  - Helper `async def fetch_batch(refs: list[ImageRef]) -> list[ImageRef]` (modifies local_path field)
  - Concurrent qua `asyncio.gather` (limit ~5 concurrent per chapter)
  - Save vào `{output_dir}/images/ch_{NNNN}_{idx}.{ext}`
  - Extension detect từ Content-Type header (fallback .jpg, check magic bytes for top 4 common types)
  - Failure (404/timeout) → `local_path = None`, log warning, continue
  - Atomic write qua `.tmp` + rename
  - Size limit: skip nếu Content-Length > 5MB
- [ ] **Bước:**
  1. Plan
  2. Code ABC + WebImageFetcher
  3. Test với 4 ảnh thật (1 OK, 1 redirect, 1 404, 1 large >5MB)
- [ ] **Acceptance:**
  - 4 case test: OK download, redirect follow, 404 graceful, large skip
  - File save đúng pattern naming
  - Failed image không crash batch
- [ ] **Rủi ro:**
  - Content-Type lừa (server trả `text/html` thay vì `image/jpeg`) — check magic bytes (4 byte signature)
  - EPUB image strategy chưa code — defer P3.5
- [ ] **Commit:** `feat(image): add WebImageFetcher with Strategy pattern`
- [ ] **Phụ thuộc:** P2.1

### P2.3 — `MarkdownFormatter` handle `<img>` (STOP — shared logic)

- [ ] **🛑 STOP:** Đổi return type của `_format_element` từ `str` → `tuple[str, list[ImageRef]]`. Break mọi caller. Hỏi user.
- [ ] **Mục tiêu:** `<img>` trong content → `![alt](placeholder)` đúng vị trí, return list image refs
- [ ] **Files động vào:**
  - `core/formatter.py` (edit ~80 dòng thêm)
- [ ] **Logic:**
  - `MarkdownFormatter.format()` collect `<img>` nodes
  - Mỗi img → emit `![alt](IMG_PLACEHOLDER_{idx})` trong output Markdown
  - Method mới `extract_images(el, base_url) -> list[ImageRef]` return list với `original_url`, `alt_text`, `position_marker`, `source_type="web"`
  - `_format_element` return `(text, images)` thay vì chỉ `text` — **caller phải update**
  - Update caller: `SelectorExtractBlock`, `DensityHeuristicBlock`, etc. để pass images vào `BlockResult` metadata hoặc `ctx.image_refs`
- [ ] **Bước:**
  1. Plan + grep caller (`grep -rn "_format_element\|MarkdownFormatter" --include="*.py"`)
  2. **HỎI USER** với danh sách caller được tìm thấy
  3. Code edit
  4. Smoke test text-only chapter (FFN không có ảnh) → flow vẫn work, images list rỗng
  5. **Baseline diff** với phase1 baseline → text-only chapter output IDENTICAL
- [ ] **Acceptance:**
  - Output Markdown text-only chapter: identical với phase1 baseline (zero diff)
  - Chapter có image: output có `![alt](IMG_PLACEHOLDER_0)` đúng vị trí
  - `extract_images` return list với position marker khớp placeholder
  - Caller flow không break
- [ ] **Rủi ro:**
  - Image embed trong nested div phức tạp → position drift. Chấp nhận, document edge case.
  - Return type change break caller → grep + update tất cả
- [ ] **Commit:** `refactor(formatter): handle inline img tag, return (text, images) tuple`
- [ ] **Phụ thuộc:** P2.2 + user confirm

### P2.4 — `PipelineContext` extension cho images

- [ ] **Files động vào:**
  - `pipeline/base.py` (add `image_refs: list[ImageRef]` vào `PipelineContext`)
- [ ] **Acceptance:**
  - `PipelineContext.image_refs` default empty list
  - Extract blocks populate `ctx.image_refs` khi tìm thấy `<img>`
- [ ] **Commit:** `feat(pipeline): add image_refs to PipelineContext`
- [ ] **Phụ thuộc:** P2.3

### P2.5 — Pipeline image stage (mode-aware)

- [ ] **Mục tiêu:** sau khi extract xong, download images theo run_config, rewrite placeholder
- [ ] **Files động vào:**
  - `pipeline/executor.py` (add image stage trong `run` method, ~50 dòng)
  - HOẶC `core/scraper.py` (nếu logic này thuộc về orchestrator)
- [ ] **Decision point:** logic này thuộc PipelineRunner hay Scraper orchestrator? **Hỏi user.**
- [ ] **Logic:**
  - Sau ExtractChain, kiểm tra `ctx.run_config`:
    - Obsidian + has image_refs: gọi `WebImageFetcher.fetch_batch(image_refs)`, rewrite placeholder thành relative path trong `ctx.content`
    - Translate: replace `![alt](IMG_PLACEHOLDER_N)` → `[IMAGE: alt]` (sync, no fetch)
    - Raw: strip image placeholder entirely (empty string)
- [ ] **Acceptance:**
  - Chapter có ảnh + obsidian mode → Markdown output có `![](images/ch_NNNN_0.jpg)` link đúng, file ảnh tồn tại
  - Same chapter + translate mode → `[IMAGE: alt text]` inline
  - Same chapter + raw mode → không có image trace
- [ ] **Rủi ro:**
  - Logic phức tạp → bug placement. Test 3 mode kỹ.
- [ ] **Commit:** `feat(pipeline): add mode-aware image stage`
- [ ] **Phụ thuộc:** P2.4 + user confirm về placement

### P2.6 — AI#7 prompt update: detect image policy

- [ ] **Mục tiêu:** AI#7 (ads & watermark) thêm task: detect site có ảnh đáng tải không
- [ ] **Files động vào:**
  - `ai/prompts.py` (`learning_7_ads_deepscan` edit, +30% nội dung — **STOP** vì §10 "prompt > 30%". Hỏi user.)
  - `ai/agents.py` (`ai_ads_deepscan` parse thêm field)
  - `learning/phase_ai.py` (consume new field)
  - `utils/types.py` (`SiteProfile.download_images`, `SiteProfile.image_selector` — verify đã có từ P1.2)
  - `learning/phase.py` (`_build_final_profile` populate fields mới)
- [ ] **Logic prompt:**
  - Thêm task: "Trang này có ảnh minh họa trong chapter không? Nếu có, ảnh nằm trong selector nào?"
  - Response field mới: `has_inline_images: bool`, `image_selector: str | null`
- [ ] **Acceptance:**
  - Profile mới có `download_images` field (default True nếu AI bảo có)
  - Re-learn 1 site biết có ảnh (RR illustration) + 1 site không (FFN) → field set đúng
- [ ] **Rủi ro:**
  - AI có thể nhầm — vẫn cho user override qua manual edit profile JSON
  - Prompt change >30% → user confirm
- [ ] **Commit:** `feat(learning): AI#7 detect image policy`
- [ ] **Phụ thuộc:** P2.5 + user confirm

### P2.7 — Smoke test toàn diện Phase 2

- [ ] **Bước:**
  1. Pick 1 Royal Road novel có art (vd Beware of Chicken có illustration)
  2. `!relearn royalroad.com` → re-learn với prompt mới
  3. Scrape 10 chapter
  4. Verify: `output/{story}/images/` có files, Markdown link đúng
  5. Mở 1 chapter trong Obsidian → ảnh hiển thị
  6. **3-mode test:** cùng 1 URL × 3 mode → 3 output thư mục khác nhau, image handling đúng từng mode
- [ ] **Acceptance:**
  - 10 chapter Markdown đầy đủ
  - Tất cả ảnh download thành công (hoặc fail rõ ràng nếu có)
  - Obsidian render ảnh đúng vị trí
  - Translate output có `[IMAGE: ...]` placeholder
  - Raw output không có image trace
- [ ] **Commit:** `feat(image): inline image support complete (Phase 2 done)`
- [ ] **Phụ thuộc:** P2.6

---

## Phase 3 — EPUB Adapter

> **Mục tiêu phase:** ném file `.epub` vào main.py → output Obsidian Markdown sạch (đã clean watermark, ads). EPUB embedded image cũng extract.
>
> **Thời gian ước tính:** 1-1.5 tuần.
>
> **Tiền điều kiện:** Phase 2 done.

### P3.1 — Add `ebooklib` dependency

- [ ] **Files động vào:**
  - `pyproject.toml` (hoặc `requirements.txt`)
- [ ] **Bước:**
  1. `pip install ebooklib` (hoặc `uv add ebooklib`)
  2. Update dependency file
- [ ] **Acceptance:**
  - `python -c "import ebooklib"` không error
- [ ] **Commit:** `chore(deps): add ebooklib for EPUB parsing`
- [ ] **Phụ thuộc:** Phase 2 done

### P3.2 — `ingest/router.py`: input type detection

- [ ] **Files động vào:**
  - `ingest/__init__.py` (create)
  - `ingest/router.py` (create ~80 dòng)
- [ ] **Logic:**
  - Function `detect_input_type(path_or_file) -> Literal["web", "epub", "txt"]`
  - File extension `.epub` → epub
  - File `.txt` chứa URL ở line đầu → web (legacy `links.txt`)
  - File `.txt` chứa text content → txt
  - Distinguish: line đầu match URL pattern → web; else → txt
- [ ] **Acceptance:**
  - 3 case test pass: `links.txt` → web, `novel.epub` → epub, `novel.txt` (toàn text) → txt
- [ ] **Rủi ro:** edge case `.txt` mix URL + text → ambiguous. **Quyết định:** ưu tiên web nếu có >=1 URL hợp lệ.
- [ ] **Commit:** `feat(ingest): add router for input type detection`
- [ ] **Phụ thuộc:** P3.1

### P3.3 — `ingest/web.py`: wrap existing scraper

- [ ] **Mục tiêu:** existing scraper logic giờ là một adapter trong nhiều
- [ ] **Files động vào:**
  - `ingest/web.py` (create ~80 dòng)
- [ ] **Decision point:** wrap thật sự (refactor caller) hay symbolic re-export? **Hỏi user.** Recommend: symbolic re-export Phase 3, refactor caller Phase 6.
- [ ] **Logic:**
  - Thin wrapper gọi `core/scraper.py` logic hiện tại
  - Trả về iterator/generator yield `RawDocument`
  - HOẶC pass-through, re-export `scrape_web` function
- [ ] **Acceptance:**
  - Web scraping vẫn work y như cũ
  - Import path mới: `from ingest.web import scrape_web`
- [ ] **Commit:** `feat(ingest): add web adapter wrapper`
- [ ] **Phụ thuộc:** P3.2

### P3.4 — `ingest/epub.py`: EPUB parser

- [ ] **Files động vào:**
  - `ingest/epub.py` (create ~200 dòng)
- [ ] **Logic:**
  - Function `async def ingest_epub(path: str) -> AsyncIterator[RawDocument]`
  - Open EPUB qua `ebooklib.epub.read_epub(path)`
  - Naming: `book.get_metadata('DC', 'title')` first → AI fallback nếu trống (Decision #22)
  - Iterate `book.spine`, get each `EpubHtml` item
  - Each item → `RawDocument(chapter_index=N, html=content, source_path=path)`
  - Skip TOC, cover, copyright pages (filter by guide type hoặc filename pattern)
  - **Image:** chỉ collect `<img>` references → `ImageRef.original_url = href`, `source_type = "epub"`. Extract binary để ở P3.5.
- [ ] **Acceptance:**
  - 1 EPUB test → output 50 chapter Markdown (Obsidian mode)
  - Cover/TOC/copyright không xuất hiện trong output chapters
  - Naming dùng metadata khi có
- [ ] **Rủi ro:**
  - EPUB structure đa dạng — một số dùng OEBPS, một số khác. ebooklib handle, nhưng có thể có edge case.
  - Embedded font/CSS không cần — verify skip
  - EPUB 3 navigation document (nav.xhtml) — có thể bị nhầm chapter. Filter.
- [ ] **Commit:** `feat(ingest): add EPUB adapter with ebooklib`
- [ ] **Phụ thuộc:** P3.3

### P3.5 — `EpubImageExtractor` (strategy implementation)

- [ ] **Mục tiêu:** extract embedded image từ EPUB zip, cùng interface với `WebImageFetcher`
- [ ] **Files động vào:**
  - `core/image_pipeline/epub_extractor.py` (create ~80 dòng)
- [ ] **Logic:**
  - Class `EpubImageExtractor(ImageFetchStrategy)`
  - `__init__(self, book: epub.EpubBook, output_dir: str)` — store ref tới book
  - `async def fetch(self, ref: ImageRef) -> bytes | None`:
    - `item = book.get_item_with_href(ref.original_url)`
    - return `item.get_content()` nếu found, None nếu không
  - `fetch_batch`: same interface với WebImageFetcher
  - Save binary to `output/{story}/images/ch_NNNN_idx.{ext}` — ext detect từ `item.media_type`
- [ ] **Bước:**
  1. Pipeline image stage P2.5 cần update: chọn strategy theo `ImageRef.source_type`
- [ ] **Acceptance:**
  - EPUB có embedded image → extract đúng, save local, Markdown link đúng
  - Image not found trong zip (ref dangling) → log warning, local_path=None
- [ ] **Rủi ro:**
  - href relative vs absolute trong EPUB — `get_item_with_href` handle cả 2 nhưng có thể edge case
- [ ] **Commit:** `feat(image): add EpubImageExtractor strategy`
- [ ] **Phụ thuộc:** P3.4

### P3.6 — `core/orchestrator.py`: route theo input type

- [ ] **Mục tiêu:** main.py giờ route theo input type
- [ ] **Files động vào:**
  - `core/orchestrator.py` (create ~150 dòng)
  - `main.py` (use `detect_input_type` + orchestrator)
  - `core/scraper.py` (vẫn còn, giờ là web-specific orchestrator)
- [ ] **Decision point:** create file mới `orchestrator.py` hay edit `scraper.py`? **Hỏi user.** Recommend: tạo mới, `scraper.py` giữ vai trò "web-specific orchestrator".
- [ ] **Logic:**
  - `Orchestrator.run(input_path, run_config)`:
    - input_type = detect_input_type(input_path)
    - adapter = web | epub | txt
    - foreach `RawDocument` từ adapter:
      - context = build context (RunConfig + RawDocument)
      - chapter = await PipelineRunner.run(context)
      - await writer.write(chapter)
  - EPUB không có Navigation chain — skip NavChain
  - EPUB không cần Learning phase — bypass
  - Image strategy chọn theo source: `WebImageFetcher` cho web, `EpubImageExtractor` cho EPUB
- [ ] **Acceptance:**
  - EPUB → Obsidian output: 1 file Markdown per chapter
  - No AI call cho EPUB (trừ Naming fallback nếu metadata trống)
  - Web flow không break
- [ ] **Rủi ro:**
  - Pipeline blocks assume `ctx.html` is web HTML — EPUB HTML có thể có inline CSS, namespace XML. Verify `prepare_soup` handle được.
- [ ] **Commit:** `feat(core): add orchestrator for input-type routing`
- [ ] **Phụ thuộc:** P3.5 + user confirm

### P3.7 — AdsFilter cho EPUB

- [ ] **Mục tiêu:** EPUB pirate có watermark — cross-chapter frequency analysis vẫn apply
- [ ] **Files động vào:**
  - `utils/ads_filter.py` (verify domain key handling — string key OK cho filename slug)
  - `core/orchestrator.py` (set domain = filename slug cho EPUB)
- [ ] **Acceptance:**
  - EPUB pirate test → watermark detect + strip
  - `data/ads_keywords.json` có entry với key là filename slug (vd `epub:my_novel_slug`)
- [ ] **Commit:** `feat(ads): support EPUB watermark filtering`
- [ ] **Phụ thuộc:** P3.6

### P3.8 — Smoke test Phase 3

- [ ] **Bước:**
  1. Pick 1 EPUB pirate có watermark rõ ràng
  2. `python main.py --output-mode obsidian novel.epub`
  3. Verify 50 chapter clean, ảnh embed đúng, watermark stripped
  4. Pick 1 EPUB clean (Project Gutenberg) → verify không over-strip
- [ ] **Acceptance:**
  - EPUB pirate: output clean, image embedded preserved
  - EPUB clean: output không bị strip nhầm
- [ ] **Commit:** `feat(ingest): EPUB adapter complete (Phase 3 done)`
- [ ] **Phụ thuộc:** P3.7

---

## Phase 4 — TranslationWriter + RawWriter

> **Mục tiêu phase:** hoàn thiện 3 output modes.
>
> **Thời gian ước tính:** 3 ngày.
>
> **Tiền điều kiện:** Phase 3 done.

### P4.1 — `output/translation.py`

- [ ] **Files động vào:**
  - `output/translation.py` (create ~120 dòng)
- [ ] **Logic:**
  - Strip Markdown formatting: heading, bold, italic, link → plain
  - Image: replace `![alt](url)` bằng `[IMAGE: alt]` placeholder (Decision #13)
  - Paragraph: một paragraph một dòng, double newline giữa các paragraph
  - Filename: `0042.txt`
  - No frontmatter
  - Optional chunking: nếu `len(text) > CHUNK_THRESHOLD` → split thành `0042_part1.txt`, `0042_part2.txt`
- [ ] **Decision point:** chunking threshold? Default 30000 chars (~10K tokens cho Gemini). **Hỏi user.**
- [ ] **Acceptance:**
  - Output paste vào Gemini → dịch ra tiếng Việt sạch
  - Không có Markdown noise (`**bold**`, `[link](url)`)
  - Image placeholder `[IMAGE: alt]` rõ ràng
  - Chunk file có suffix `_partN` nếu chia
- [ ] **Commit:** `feat(output): add TranslationWriter with image placeholder`
- [ ] **Phụ thuộc:** Phase 3 done

### P4.2 — `output/raw.py`

- [ ] **Files động vào:**
  - `output/raw.py` (create ~60 dòng)
- [ ] **Logic:**
  - Plain text, không Markdown
  - Image stripped entirely (không placeholder)
  - Không paragraph spacing đặc biệt (giữ y nguyên paragraph trong body)
  - Filename: `0042.txt`
  - No frontmatter
- [ ] **Acceptance:**
  - Output đọc được trên Notepad
  - File size nhỏ nhất trong 3 mode
- [ ] **Commit:** `feat(output): add RawWriter (text only)`
- [ ] **Phụ thuộc:** P4.1

### P4.3 — Smoke test 3 mode × 2 input source

- [ ] **Bước:**
  1. Cùng 1 URL → 3 mode → 3 output dir
  2. Cùng 1 EPUB → 3 mode → 3 output dir
  3. Verify content matrix § BLUEPRINT §4
- [ ] **Acceptance:**
  - 6 output dir khác nhau, đều correct
  - Translation mode paste vào Gemini dịch thử → ra tiếng Việt sạch
- [ ] **Commit:** `test(phase4): 3-mode × 2-source matrix verified`
- [ ] **Phụ thuộc:** P4.2

---

## Phase 5 — TXT Adapter (HIGHEST RISK — narrowed scope)

> **Mục tiêu phase:** ném file `.txt` chứa novel (có chapter break) → output Obsidian sạch.
>
> **Thời gian ước tính:** 2 tuần (có exit ramp ở giữa).
>
> **Tiền điều kiện:** Phase 4 done.
>
> **Scope v1.0:** Vietnamese ("Chương N") + English ("Chapter N") chapter pattern only. CJK ("第N章", "第N話") defer v1.1.
>
> **Exit ramp:** Sau P5.5 (smoke test 3 file), nếu < 50% pass (< 2/3 file detect đúng) → STOP Phase 5, mark feature defer v1.1, ship v1.0 without TXT. Quyết định này cứu được 1 tuần debug.

### P5.1 — TXT case database design

- [ ] **Files động vào:**
  - `data/txt_cases.json` (create với 5 case ban đầu, **chỉ VN + EN**)
  - `utils/types.py` (`TxtCase` TypedDict)
- [ ] **Schema:**
  ```json
  {
    "cases": [
      {
        "id": "vn_chuong_colon",
        "language": "vi",
        "pattern": "^Chương\\s+(\\d+)\\s*[:\\-—]?\\s*(.*)$",
        "samples": ["Chương 1: Bắt đầu", "Chương 2 - Khám phá", "Chương 3"],
        "confidence": 0.9
      },
      {
        "id": "vn_chuong_number_only",
        "language": "vi",
        "pattern": "^Chương\\s+(\\d+)\\s*$",
        "samples": ["Chương 1", "Chương 42"],
        "confidence": 0.85
      },
      {
        "id": "en_chapter_colon",
        "language": "en",
        "pattern": "^Chapter\\s+(\\d+)\\s*[:\\-—]?\\s*(.*)$",
        "samples": ["Chapter 1: The Beginning", "Chapter 2 - Discovery"],
        "confidence": 0.9
      },
      {
        "id": "en_chapter_number_only",
        "language": "en",
        "pattern": "^Chapter\\s+(\\d+)\\s*$",
        "samples": ["Chapter 1", "Chapter 42"],
        "confidence": 0.85
      },
      {
        "id": "numeric_section",
        "language": "any",
        "pattern": "^(\\d+)\\.\\s+(.+)$",
        "samples": ["1. First", "42. Forty-two"],
        "confidence": 0.5
      }
    ]
  }
  ```
- [ ] **Acceptance:**
  - 5 case ban đầu cover: VN colon/number-only, EN colon/number-only, numeric prefix
  - **KHÔNG có CJK case** trong v1.0
- [ ] **Commit:** `feat(data): add TXT case database (VN+EN)`
- [ ] **Phụ thuộc:** Phase 4 done

### P5.2 — TXT chapter boundary detection

- [ ] **Files động vào:**
  - `ingest/txt.py` (create ~300 dòng)
- [ ] **Logic:**
  - Read full file (`encoding="utf-8"` explicit, fail-loud nếu không phải UTF-8 — không tự detect encoding v1.0)
  - Sample first 100 dòng → match từng case
  - Best match (most lines matching) → return case
  - No match → fallback AI: gửi 50 dòng + ask "what's the chapter pattern?"
  - AI return regex → verify với 5 line đầu của 3 chapter ngẫu nhiên (cross-check)
  - AI verify pass → add vào `data/txt_cases.json` (new case learned)
  - Apply pattern → split file thành `list[(idx, title, body)]`
- [ ] **Acceptance:**
  - 3 TXT file với pattern khác nhau → detect đúng, split đúng
  - 1 TXT file không có pattern → error message rõ ràng (KHÔNG silent fail)
  - UTF-8 only — file non-UTF-8 fail-loud
- [ ] **Commit:** `feat(ingest): TXT chapter boundary detection`
- [ ] **Phụ thuộc:** P5.1

### P5.3 — TXT → RawDocument

- [ ] **Files động vào:**
  - `ingest/txt.py` (extend)
- [ ] **Logic:**
  - Each chunk → wrap as HTML `<article><p>...</p>...</article>` (đoạn văn ngăn cách bằng newline → `<p>` riêng)
  - Yield `RawDocument(chapter_index=N, html=..., source_path=...)`
- [ ] **Acceptance:**
  - Pipeline ăn được TXT chunk như HTML
  - SelectorExtract skip (no selector), DensityHeuristic accept
- [ ] **Commit:** `feat(ingest): TXT to RawDocument conversion`
- [ ] **Phụ thuộc:** P5.2

### P5.4 — Orchestrator route TXT

- [ ] **Files động vào:**
  - `core/orchestrator.py` (add TXT branch)
- [ ] **Logic:**
  - TXT không có Navigation chain
  - TXT không có Learning phase
  - TXT có thể có AdsFilter (pirate watermark)
  - TXT không có image — image stage no-op
- [ ] **Acceptance:**
  - TXT → Obsidian: 1 Markdown per chapter
- [ ] **Commit:** `feat(core): orchestrator TXT routing`
- [ ] **Phụ thuộc:** P5.3

### P5.5 — Smoke test TXT (DECISION POINT — exit ramp)

- [ ] **Bước:**
  1. Pick 3 TXT đa dạng:
     - VN novel từ tangthuvien hoặc tương tự ("Chương N" pattern)
     - EN novel từ Project Gutenberg ("Chapter N" pattern)
     - VN novel với pattern lạ (vd "Phần N", "Quyển I Chương X")
  2. Run 3, verify output
- [ ] **Acceptance:**
  - >= 2/3 case work, accept 1/3 fail-loud nếu pattern lạ
  - **EXIT RAMP:** Nếu < 2/3 work → STOP Phase 5, mark "TXT defer v1.1" trong CLAUDE.md §3 DEFERRED, ship v1.0 without TXT
- [ ] **Commit (nếu pass):** `feat(ingest): TXT adapter complete (Phase 5 done)`
- [ ] **Phụ thuộc:** P5.4

---

## Phase 6 — Final Cleanup + Polish

> **Mục tiêu phase:** miscellaneous cleanup — merge small files, remove boilerplate, final docs polish.
>
> **Thời gian ước tính:** 3-5 ngày.

### P6.1 — Audit codebase post-Phase-5

- [ ] **Bước:**
  1. `wc -l **/*.py` — count current
  2. Identify files < 50 dòng → candidate cho merge
  3. Identify unused imports, dead code
  4. Identify duplicate logic across `ingest/` adapters
- [ ] **Acceptance:** list candidate files for merge/delete
- [ ] **Phụ thuộc:** Phase 5 done (hoặc Phase 4 done nếu Phase 5 exit ramp)

### P6.2 — Execute Batch C

- [ ] **Files động vào:** TBD theo audit
- [ ] **Acceptance:**
  - Total LOC giảm thêm 5-10%
  - All smoke test still pass
  - Baseline diff: chỉ frontmatter-level change (predictable)
- [ ] **Commit:** `refactor: Batch C miscellaneous cleanup`
- [ ] **Phụ thuộc:** P6.1

### P6.3 — Final docs polish

- [ ] **Files động vào:**
  - `CLAUDE.md` (Decision Log update, final state)
  - `BLUEPRINT.md` (phase status update)
  - `ROADMAP.md` (file này, mark all done)
  - `README.md` (final polish — full feature list, troubleshooting, FAQ)
  - `docs/V1_1_BACKLOG.md` (consolidate defer features)
- [ ] **Acceptance:**
  - README có quick start, install, usage 3 modes, troubleshooting
  - All 3 governance docs đồng bộ
  - V1_1_BACKLOG.md có rationale cho mỗi defer item
- [ ] **Commit:** `docs: finalize v1.0 documentation`
- [ ] **Phụ thuộc:** P6.2

### P6.4 — v1.0 tag + retrospective

- [ ] **Bước:**
  1. Full smoke test: 3 site web + 1 EPUB + 1 TXT (nếu Phase 5 done) × 3 mode
  2. Final baseline snapshot: `tools/snapshot_baseline.py --label v1.0_final ...`
  3. `git tag v1.0`
  4. Update CHANGELOG nếu có
- [ ] **Acceptance:**
  - Tag v1.0 ở HEAD main
  - Full test pass
- [ ] **Phụ thuộc:** P6.3

---

## Phase 7+ — Deferred (v1.1+)

Không làm trong v1.0. Ghi nhận để track:

- **Case-based learning cho web** — chờ 10+ profile để thấy pattern
- **Calibration phase** — re-probe 10 chapter verify profile
- **Site Trung/Nhật/Hàn CJK hardening** — encoding heuristic, font deob, slugify pinyin, "第N章"/"第N話" chapter pattern
- **TypedDict refactor `utils/types.py`** (P3-D từ session cũ)
- **Manhua adapter** — fork project riêng, dùng gallery-dl pattern
- **GUI** — Streamlit hoặc native, nếu CLI không đủ
- **Concurrent multi-domain** — hiện đã có nhưng có thể tối ưu
- **Frontmatter customization** — `--no-frontmatter`, custom YAML fields
- **TXT v1.1**: nếu Phase 5 exit ramp trigger, work lại với expanded case + CJK support

---

## Tracking Summary

| Phase | Status | Risk | Note |
|---|---|---|---|
| P0 — Cleanup + Foundation | ✅ DONE 2026-05-16 | Low | ~780 dòng đi. P0.0 baseline capture + P0.7 live smoke test defer cho user (cần API key + network). P0.4 README deferred (placeholder) |
| P1 — Output Abstraction | ⬜ Not started | Medium | Refactor shared logic — STOP rules |
| P2 — Image Support | ⬜ Not started | Medium | Phase 1 dependency |
| P3 — EPUB Adapter | ⬜ Not started | Low | Lib mature, structure standard |
| P4 — Translation+Raw writers | ⬜ Not started | Low | Pure writer logic |
| P5 — TXT adapter | ⬜ Not started | **HIGH** | **Has exit ramp at P5.5** |
| P6 — Final cleanup | ⬜ Not started | Low | Polish |

**Total estimate:** 7-9 tuần solo dev part-time. Exit ramp Phase 5 có thể cắt 1.5 tuần.

**Update tracking sau mỗi step done. Visual progress là motivation thật cho solo dev.**

---

## Sequencing Diagram (visual)

```
P0 Cleanup        ━━━━━━━━━━ (3-4d)
                            │
                            ▼ baseline + foundation ready
P1 Output Abstract          ━━━━━━━ (1w)  [RunConfig + CleanedChapter + ObsidianWriter]
                                  │
                                  ▼ RunConfig available
P2 Image Support                  ━━━━━━━━━━━━━ (1-2w)  [mode-aware download]
                                                │
                                                ▼ Image strategy + Writer ready
P3 EPUB Adapter                                 ━━━━━━━━━━━ (1-1.5w)  [reuse strategy]
                                                          │
                                                          ▼
P4 Translation+Raw                                        ━━━ (3d)
                                                              │
                                                              ▼
P5 TXT (HIGH RISK, exit ramp)                                 ━━━━━━━━━━━━━ (2w)
                                                                            │
                                                                            ▼
P6 Final cleanup                                                            ━━━━━ (3-5d)
                                                                                  │
                                                                                  ▼
                                                                                  v1.0 ship
```

---

**END ROADMAP v1.1**

*Generated 2026-05-16. v1.1 = Phase ordering fix + baseline snapshot protocol + narrowed Phase 5 scope + exit ramp. Update khi step done hoặc khi user pivot.*
