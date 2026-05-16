# Phase 2 Retrospective — Image Support cho Web Novel

> Phase 2 = inline image trong chapter content. Resolve URL → fetch (web) → save local → rewrite placeholder → embed Markdown. Mode-aware (obsidian download, translate placeholder, raw strip). AI#image detect site policy.

---

## Plan vs Actual

| Step | Plan estimate | Actual | Note |
|---|---|---|---|
| P2.1 image_url resolver | ~0.5 ngày | 1 session | Pure utility, 6 spec + 3 extras cases |
| P2.2 ImageFetchStrategy + WebImageFetcher | ~1 ngày | 1 session | Deviation — pool.fetch trả text; thêm fetch_bytes() method mới |
| P2.3 MarkdownFormatter handle img | ~1 ngày | 1 session | STOP rule respected. Tangential fix `_format_element` `is not None` |
| P2.4 PipelineContext.image_refs + run_config | ~0.3 ngày | 1 session | TYPE_CHECKING import tránh circular |
| P2.5 Pipeline image stage | ~1 ngày | 1 session | STOP placement decision — scraper not executor |
| P2.6 AI#image detect | ~0.5 ngày | 1 session | Picked Option B (dedicated call, not extend AI#7) |
| **Phase 2 tổng** | **1-2 tuần plan** | **6 session AI** | Code-only thời gian; live verify deferred |

---

## Cái gì làm tốt

1. **STOP rules respected 2 lần** (P2.3 return type change, P2.5 placement decision). Plan + risk + behavior checklist + user confirm trước code. Zero rollback.
2. **Strategy pattern** đúng cho image fetch — `ImageFetchStrategy` ABC + `WebImageFetcher` impl. P3 sẽ add `EpubImageExtractor` cùng interface — pipeline image stage không cần biết source.
3. **Failure UX fallback** rõ ràng — image fetch fail không break chapter. Body có external URL link (clickable), frontmatter `failed_images` list URL fail. User aware nhưng không broken.
4. **Tangential bug fix P2.4** — `_format_element` truthy check `if formatting_rules:` → `is not None`. Empty dict `{}` was silently falling to plain_text path (drop img + bold/italic). Fix while integrating.
5. **Image stage placement scraper not executor** — đúng theo CLAUDE separation. PipelineRunner stays pure (HTML → ctx pieces). Scraper has writer + run_config + chapter_num + pool — natural place.
6. **AI#image Option B** — dedicated call thay vì extend AI#7. Single responsibility. AI#7 prompt (tested) không mutate → no regression risk. Cost +$0.0025/learn negligible.
7. **MockPool testing** — unit test image stage 3 modes + 4 failure cases (OK / 404 / oversize / network error) qua mock không cần network. Code paths verified.

---

## Cái gì khó / mất nhiều thời gian

1. **Pool API mismatch P2.2** — Task spec assume `pool.fetch(url, method, timeout)` trả `resp.status_code + resp.content`. Reality: `pool.fetch(url, timeout)` trả `(status, html_text)`. Phải add `fetch_bytes()` riêng. Deviation documented.
2. **P2.3 truthy bug** — Test fail lần đầu vì `if formatting_rules:` falsy cho `{}`. Debug 1 round trace. Lesson: `is not None` cho dict default check, không truthy.
3. **`run_config` propagation chain** — main → run_novel_task → _run_scrape_loop → scrape_one_chapter → writer.run_config. 4 hop. Wired qua writer instance (writer.run_config) thay vì pass param riêng — đỡ signature bloat.
4. **`asyncio.to_thread` cancel race** — `_atomic_write_text` cleanup best-effort, thread không thực sự cancel. Inherited từ P1.5. Image fetch async không có vấn đề tương đương vì HTTP cancel-aware.
5. **Verify capability gap** — không có RR illustration baseline + network blocked → live verify hoàn toàn defer cho user. Phase 2 = high-risk untested live (image fetch CDN, atomic write image binary, Obsidian render).

---

## Tech debt accumulate

| Item | Severity | Note |
|---|---|---|
| Live verify chưa chạy | **HIGH** | 6 commits chưa được test với real RR illustration. P2.6 AI#image chưa được verify với real learn. |
| `core/chapter_writer.py` chưa delete (cũ từ P1) | Low | Defer P6 |
| `ai/agents.py` dead code (`ai_nav_stress`, `ai_full_simulation`) | Low | Defer P6 |
| `FormattingRules` schema mismatch (cũ từ P1) | Medium | Migration consumers ở P6 hoặc khi đụng MarkdownFormatter |
| Pre-existing FILENAME-E bug (cũ từ P1) | Low | Defer P6 |
| `_apply_image_stage` fallback (network down) chưa retry | Low | Single attempt + log warning. Defer v1.1 nếu thấy nhiều fail thực tế. |
| Obsidian frontmatter `failed_images` chỉ list URL, không có chapter context | Low | Defer |

---

## Risks cho Phase 3 (EPUB Adapter)

1. **`EpubImageExtractor` cần implement** — cùng `ImageFetchStrategy` interface. Strategy pattern ABC sẵn sàng, chỉ cần concrete subclass đọc binary từ EPUB zip thay vì HTTP fetch.
2. **Pipeline image stage chọn strategy dynamic** — hiện hardcode `WebImageFetcher` trong `_apply_image_stage`. P3 cần switch theo `ImageRef.source_type` (web vs epub). Refactor nhẹ.
3. **EPUB image href resolution** — relative path trong EPUB zip (`Images/cover.jpg`) khác URL HTTP. `_handle_img` trong MarkdownFormatter dùng `resolve_image_url` với base_url — P3 cần adapter set base_url phù hợp (hoặc skip).
4. **EPUB chapter index numbering** — `chapter_num` từ `progress.chapter_count + 1` — EPUB adapter cần track tương đương. Naming `ch_NNNN_idx` consistent giữa web + epub OK.
5. **Naming context cho EPUB** — `chapter_keyword` + `story_prefix_strip` từ progress (set bởi Naming Phase). EPUB cần riêng adapter cho Dublin Core metadata (Decision #23 BLUEPRINT).

---

## Decisions accumulated trong Phase 2

| # | Decision | Tóm tắt |
|---|---|---|
| 33 | `DomainSessionPool.fetch_bytes` method (P2.2) | Tách binary fetch khỏi text fetch — không refactor existing `fetch()`. Reuse session để giữ TLS fingerprint + cookie consistent. |
| 34 | `_format_element` `is not None` check (P2.4 tangential) | Empty dict `{}` valid "use defaults" — không nên fall sang plain text path. Tangential fix while wiring. |
| 35 | Image stage placement = `core/scraper.py` not `pipeline/executor.py` (P2.5) | Scraper has writer (→ run_config, output_dir) + chapter_num + pool. PipelineRunner stays pure. |
| 36 | AI#image dedicated call (NOT extend AI#7) — Option B (P2.6) | Single responsibility (ads ≠ image). AI#7 prompt no-mutate. Cost +$0.0025/learn negligible. |
| 37 | Image fetch failure UX: fallback external URL link (P2.5) | `local_path=None` → body `![alt](original_url)`. Clickable, not broken. `failed_images` frontmatter list URL fail. |

Add vào CLAUDE.md §17 trong commit này.

---

## Verify required từ user TRƯỚC Phase 3

Critical (chưa test live):
- [ ] Re-learn RR illustration novel: `py main.py --bulk-relearn --pattern "royalroad" --apply` + scrape 1 URL → profile mới có `download_images=True`, `image_selector=<X>`
- [ ] Re-learn FFN text-only → profile có `download_images=False`
- [ ] 1 RR chapter có ảnh × 3 modes:
  - obsidian: `output/{story}/images/ch_NNNN_idx.jpg` exists + Markdown link đúng
  - translate: `[IMAGE: alt]` placeholder trong body
  - raw: no img trace
- [ ] Open obsidian chapter trong Obsidian vault → ảnh render
- [ ] Network block test: hosts block 1 CDN → verify external URL fallback trong body + `failed_images` frontmatter
- [ ] Baseline diff text-only chapter (FFN) vs phase1_ffn → MUST be ZERO (no behavior change cho img-free)
