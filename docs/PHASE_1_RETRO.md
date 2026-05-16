# Phase 1 Retrospective — Output Mode Abstraction

> Phase 1 = `RunConfig` + `CleanedChapter` DTO + `ChapterWriter` ABC + `ObsidianWriter` port + pipeline refactor (produce DTO thay vì ghi file trực tiếp).

---

## Plan vs Actual

| Step | Plan estimate | Actual | Note |
|---|---|---|---|
| P1.1 RunConfig + CLI flag | ~0.5 ngày | 1 session | Clean, theo BLUEPRINT §8 exact |
| P1.2 DTOs (CleanedChapter/ImageRef/FormattingRules) | ~0.5 ngày | 1 session | Schema replace FormattingRules — flag breaking change |
| P1.3 ChapterWriter ABC | ~0.5 ngày | 1 session | STOP — name conflict `output/` runtime dir → rename `writers/` |
| P1.4 ObsidianWriter port | ~1 ngày | 1 session | Reuse `format_chapter_filename`, không re-implement |
| P1.5 Pipeline refactor (CleanedChapter contract) | ~2 ngày | 1 session | STOP rule respected, plan reviewed + confirm trước code |
| P1.6 + P1.7 retro + verify | ~0.5 ngày | 1 session | Live verify defer cho user |
| **Phase 1 tổng** | **1 tuần plan** | **6 session AI** | Code-only thời gian; live verify chưa chạy |

---

## Cái gì làm tốt

1. **STOP rule respected** — P1.3 conflict (`output/` package vs `output/` runtime dir) caught TRƯỚC khi tạo file. User confirmed rename `writers/` → tránh được loop debug sau này.
2. **STOP rule P1.5** — refactor shared logic được plan + confirm trước code. Plan có behavior checklist + risk + exit ramp. Không có surprise sau commit.
3. **Backward compat tốt** — `run_novel_task(run_config=None)` default ObsidianWriter → callers cũ chưa migrate vẫn work. `scrape_one_chapter` writer là required keyword nhưng `_run_scrape_loop` luôn build writer → không break thực tế.
4. **Helper `build_cleaned_chapter` standalone** — không method trên `PipelineRunner` → giữ `runner.run()` return type ổn định, caller có flexibility build DTO.
5. **Cancel handler best-effort** — `_atomic_write_text` async + `.tmp` cleanup trong CancelledError handler. Race window nhỏ do `asyncio.to_thread` không thực sự cancel thread — accepted với note.
6. **Migration legacy `image_alt_text`** — convert tại 3 boundary (default, AI#6 consumption, sanitizer) + defensive guard trong `_build_final_profile` → không phụ thuộc 1 path duy nhất.

---

## Cái gì khó / mất nhiều thời gian

1. **P1.3 name conflict** — `output/` đụng runtime dir. Solution rename `writers/` — đơn giản nhưng đáng lẽ BLUEPRINT §7 nên catch trước. Cosmetic fix BLUEPRINT đã apply.
2. **P1.2 FormattingRules schema replace** — 10 fields mới khác hoàn toàn 10 fields cũ. Runtime dict vẫn carry legacy keys (MarkdownFormatter, profile_manager summary, prompts.py vẫn dùng `.get("tables")` etc.), nhưng IDE hints lose. Risk: tương lai dev sẽ confused về schema. Mitigation: migration consumers sẽ làm ở P1.5+ scope khi đụng MarkdownFormatter (Phase 2 image stage).
3. **P1.4 pre-existing bug `format_chapter_filename`** — line 122 `.strip(" ,-–—:[]().")` consume `]` TRƯỚC khi `strip_site_suffix` chạy → `_WORD_COUNT_ARTIFACT` regex không match. Doc comment hứa `0025_Enjoying_life.md` nhưng actual `0025_Enjoying_life[_1500_words.md`. Out of P1.4 scope — port preserve exact behavior. Bug đáng fix ở P6 cleanup.
4. **P1.5 plan template** — viết plan đầy đủ trước code chiếm ~40% session time. Trade-off đáng giá: zero surprise sau commit, không cần rollback. Solo dev nên giữ plan template cho refactor lớn.
5. **Verify capability limited** — không có FFN/RR baseline + không có network/API → tất cả live test defer. Code path verify (py_compile, import, signature inspect, inline DTO test) only.

---

## Tech debt accumulate

| Item | Severity | Note |
|---|---|---|
| `core/chapter_writer.py` chưa delete | Low | ObsidianWriter delegate `format_chapter_filename`; `strip_nav_edges` còn dùng trong scraper. Defer P6 cleanup. |
| FormattingRules schema mismatch | Medium | TypedDict 10 fields writer-facing, runtime dict carry 10+ fields AI extraction. IDE/type checker confusion. Migration consumers ở P2 image stage hoặc P6. |
| Pre-existing `format_chapter_filename` bug (FILENAME-E word count strip) | Low | Doc claims fix but actual code wrong. Document trong P6. |
| Cancel race trong `_atomic_write_text` | Low | `asyncio.to_thread` không cancel thread. Best-effort cleanup. Production flow await complete giữa chapters → race window thực tế hẹp. |
| Live verify chưa chạy | Medium | Smoke 3 modes + baseline FFN/RR + resume/cancel test deferred. User phải chạy tay trước Phase 2 baseline-dependent steps. |
| P0.4 README skeleton vẫn deferred | Low | "Sẽ cập nhật lại sau!!!" placeholder. CLI flag tăng (--output-mode, --output-dir, --bulk-relearn) — README outdated risk tăng. |

---

## Risks cho Phase 2 (Image Support)

1. **Baseline absence blocking** — P2.3 (MarkdownFormatter handle `<img>`) là refactor lớn STOP rule, return type change `_format_element` → tuple. Cần baseline TRƯỚC để verify text-only chapter identical sau refactor. Live snapshot FFN + RR cần chạy trước P2.3.
2. **FormattingRules `image_alt_strategy` chưa wire** — MarkdownFormatter vẫn đọc `image_alt_text` legacy. P2 phải migrate khi handle `<img>` element.
3. **Image fetch strategy ABC chưa có** — P2.2 mới build. Pipeline image stage phải chọn strategy theo `ImageRef.source_type` — chỉ có "web" cho P2, "epub" defer P3.
4. **Writer output_dir hiện = actual_output_dir** — P2.5 image stage save vào `{output_dir}/images/`. Cần đảm bảo writer + image stage thống nhất base dir.
5. **CleanedChapter.images chưa được populate** — P1.5 `build_cleaned_chapter` set `images=[]` hardcode. P2 pipeline image stage populate trước khi writer.write.

---

## Decisions accumulated trong Phase 1

| # | Decision | Tóm tắt |
|---|---|---|
| 28 | `writers/` package (rename từ `output/`) | Tránh conflict runtime `output/` dir gitignored |
| 29 | Writer per task (1 instance, không per chapter) | Stateless, no expensive init, future state accumulate dễ |
| 30 | `build_cleaned_chapter` standalone helper | Giữ `PipelineRunner.run()` return `PipelineContext` unchanged; caller flexibility build DTO sau body cleanup |
| 31 | `_atomic_write_text` async + best-effort cancel cleanup | `asyncio.to_thread` không cancel thread → race window nhỏ accepted |
| 32 | `run_config=None` default trong `run_novel_task` | Backward compat callers cũ (vd run_learning_only không cần writer) |

Add vào CLAUDE.md §17 trong commit này.

---

## Verify required từ user TRƯỚC Phase 2

Critical (block P2.3 refactor):
- [ ] Smoke test 3 modes × 1 URL FFN → 3 output dir, content shape đúng
- [ ] Resume test: scrape 5 chương, Ctrl+C, re-run → tiếp đúng chương kế
- [ ] Cancel test: Ctrl+C mid-write → no `.tmp` leak trong output dir
- [ ] Baseline capture: `py tools/snapshot_baseline.py --label phase1_ffn ...` cho FFN + RR

Sau khi verify xong, có thể bắt đầu Phase 2.
