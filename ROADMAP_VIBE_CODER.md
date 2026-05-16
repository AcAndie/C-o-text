# ROADMAP_VIBE_CODER.md — Cào Text v1.0

> **Đây là roadmap "execution per-step", không phải "high-level"** — dùng đi đôi với `ROADMAP.md` (chi tiết acceptance/dependency) và `BLUEPRINT.md` (vision/architecture).
> Mỗi STEP có copy-paste block để bạn dán vào Claude Code.
>
> **Base:** Cào Text hiện tại (~7,240 dòng, Python async, đã có 80% backend logic + Learning Phase).
> **Target:** v1.0 = cleanup 780 dòng + 3 input adapter (web/EPUB/TXT) × 3 output mode (Obsidian/Translate/Raw) + image support + i18n baseline.
> **Timeline thực tế:** 10-14 tuần solo dev part-time. (ROADMAP.md ước tính 7-9 tuần — đó là kịch bản tốt nhất, KHÔNG phải kịch bản thực tế của solo dev mới làm refactor cấp này lần đầu.)

---

## Cách dùng file này

Đi tuần tự PHASE → STEP. Mỗi STEP có 4 phần:

- 🎯 **Mục tiêu** — step xong sẽ có gì
- 🗣️ **Bạn nói với Claude Code** — copy block dán vào Claude Code, đã viết sẵn ADD/MODIFY/DELETE rõ ràng
- 🙋 **Bạn cần làm tay** — việc con người không automate được
- ✅ **Kiểm tra** — verify xong trước khi sang step kế

### Quy tắc vàng (KHÔNG skip):

1. **Mỗi step xong → commit ngay.** Bảo Claude Code commit conventional nếu nó quên.
2. **Smoke test pass + baseline diff zero (nếu refactor lớn) = mới được sang step kế.** Fail → STOP, debug, không "fix forward".
3. **Khi nghi ngờ scope** → Claude Code phải đọc CLAUDE.md §3 + `docs/V1_1_BACKLOG.md`.
4. **Khi đụng shared logic** (`pipeline/base.py`, `pipeline/executor.py`, `core/scraper.py`, `core/formatter.py`) → STOP, hỏi user trước (CLAUDE.md §10).
5. **Phase ordering NGHIÊM NGẶT** — Phase 1 (Output) trước Phase 2 (Image), KHÔNG đảo (CLAUDE.md §5 "Phase ordering rationale").

---

## 📋 Pre-flight Checklist (1 lần, trước Phase 0)

- [ ] Có folder Cào Text local (ví dụ `C:\Users\FPT MONG CAI\Desktop\Small Project\Cào text`)
- [ ] `cd "Cào text"` thấy `main.py`, `pipeline/`, `learning/`, `core/`, `data/`
- [ ] `python main.py links.txt` smoke test 1 URL ngắn PASS — baseline trước khi đụng vào
- [ ] Git working tree clean (`git status` không có thay đổi pending)
- [ ] Python 3.11+ (`python --version`)
- [ ] `data/site_profiles.json` có ít nhất 2 profile đã learn (FFN + RR) — để baseline snapshot có ý nghĩa
- [ ] `.env` có `GEMINI_API_KEY` work (smoke test ra kết quả ổn)
- [ ] Claude Code mở được trong terminal tại folder dự án
- [ ] **Đọc CLAUDE.md v1.1** (file governance đã chốt) ít nhất 1 lần — đặc biệt §3 Scope Lock, §10 STOP rules, §18 Anti-patterns

**Nếu smoke test fail từ baseline** → STOP, fix bug Cào Text hiện tại trước. Không kéo bug sang phase refactor.

---

## 🌱 PHASE 0 — Cleanup + Foundation (4 ngày)

> **Mục tiêu cuối Phase 0:** Codebase giảm ~780 dòng dead code, có baseline snapshot tool cho regression diff, README skeleton, bulk-relearn UX. Foundation sạch trước khi build mới.

### STEP 0.1 — Confirm governance docs + đọc context

🎯 **Mục tiêu:** Claude Code đã đọc CLAUDE.md/BLUEPRINT.md/ROADMAP.md, hiểu Scope Lock, STOP rules, và Phase ordering trước khi code dòng đầu.

🙋 **Bạn cần làm tay:**

Verify 3 file đã có trong repo:
```bash
ls CLAUDE.md BLUEPRINT.md ROADMAP.md
```

Nếu thiếu file nào → paste vào trước khi tiếp tục.

🗣️ **Bạn nói với Claude Code:**

```
Tôi đang bắt đầu Phase 0 của v1.0 evolution cho Cào Text.

Hãy:
1. Đọc CẢ 3 file: CLAUDE.md, BLUEPRINT.md, ROADMAP.md
2. Tóm tắt cho tôi 6 bullets:
   - Vision v1.0 (1 dòng)
   - 11 features MUST-HAVE đã có trong codebase + 10 features NEW cần build
   - Phase ordering rationale (tại sao Output trước Image)
   - Top 3 STOP rules
   - 3 anti-pattern đắt giá nhất (M4, ADS-B, image-before-RunConfig)
   - Baseline snapshot protocol là gì (Decision #18)

3. Confirm hiểu đúng bằng cách trả lời 3 câu:
   - "Khi user yêu cầu thêm calibration phase vào v1.0, tôi sẽ làm gì?"
   - "Khi tôi cần sửa core/scraper.py, tôi cần làm gì trước?"
   - "Trước khi xóa learning/optimizer.py (Batch A), tôi cần làm gì?"

KHÔNG tạo code ở step này, chỉ đọc + tóm tắt + confirm.
```

✅ **Kiểm tra:**

Claude Code trả lời đúng 3 câu confirm:
- Câu 1: "STOP — calibration phase trong DEFERRED list (§3). Hỏi user a/b/c, không tự ý code"
- Câu 2: "Đọc CLAUDE.md §10 STOP rules, plan theo template §8.1, hỏi user confirm trước khi code"
- Câu 3: "Chạy `python tools/snapshot_baseline.py` trước để có baseline regression diff. Nếu chưa có tool, build tool trước"

🙋 **Sau khi confirm OK:**

```bash
git add CLAUDE.md BLUEPRINT.md ROADMAP.md
git commit -m "docs(governance): freeze v1.1 governance docs before Phase 0"
```

---

### STEP 0.2 — Baseline snapshot tool + capture 2 site

🎯 **Mục tiêu:** Có `tools/snapshot_baseline.py` work + 2 baseline label (`phase0_ffn`, `phase0_rr`) committed vào `data/baselines/`. Đây là regression guard cứng cho mọi refactor lớn từ giờ trở đi.

🗣️ **Bạn nói với Claude Code:**

```
Task: Build baseline snapshot tool + capture 2 site.

⚠️ ĐỌC CLAUDE.md §8.5 (regression-aware refactor) + Decision #18.
⚠️ Tool này CHƯA TỒN TẠI, build mới.

ADD:
1. tools/__init__.py (empty)
2. tools/snapshot_baseline.py (~80 dòng):
   - Args: --profile <domain> --chapters <N> --label <name> --url <chapter_1_url>
   - Logic:
     - Load SiteProfile cho domain từ data/site_profiles.json
     - Chạy scrape giống main.py NHƯNG output vào data/baselines/{label}/
     - Save metadata vào data/baselines/{label}/_meta.json:
       {url, domain, chapter_range, profile_hash, timestamp}
     - Read-only: KHÔNG update progress JSON, KHÔNG update site_profiles
     - Idempotent: nếu label đã tồn tại → log warning + overwrite (không silent)
3. data/baselines/.gitkeep
4. .gitignore UPDATE — whitelist data/baselines/:
   data/*.json
   !data/baselines/
   data/baselines/**

Verify:
- python tools/snapshot_baseline.py --help → in usage
- Chạy thực:
  python tools/snapshot_baseline.py --profile fanfiction.net --chapters 5 --label phase0_ffn --url <URL chapter 1 FFN bạn chọn>
  python tools/snapshot_baseline.py --profile royalroad.com --chapters 5 --label phase0_rr --url <URL chapter 1 RR bạn chọn>
- ls data/baselines/phase0_ffn/ → 5 file .md + _meta.json
- ls data/baselines/phase0_rr/ → 5 file .md + _meta.json
- Mở 1 file .md trong mỗi label → content sạch, không corrupted

Commit: chore(tools): add baseline snapshot script for regression diff

Báo cáo:
- Output 2 lần chạy (terminal log)
- Liệt kê 10 file .md đã tạo
```

🙋 **Bạn cần làm tay:**

Pick 2 URL chapter 1 thật (1 FFN, 1 RR) — paste vào command. Sau khi tool chạy xong, mở 1-2 file .md xem có giống output bình thường không.

✅ **Kiểm tra:**
- 2 thư mục `data/baselines/phase0_ffn/`, `data/baselines/phase0_rr/` có đủ 5 file + meta
- Content sạch (không tag HTML rác)
- Git commit `chore(tools): add baseline snapshot script` ở HEAD

---

### STEP 0.3 — Branch + safety tag

🎯 **Mục tiêu:** Có branch `cleanup-batch-ab` + tag `pre-cleanup-v0.x` để safety net trước khi cắt code lớn.

🗣️ **Bạn nói với Claude Code:**

```
Task: Branch + tag trước khi cleanup.

⚠️ Verify working tree clean trước (git status).

Bước:
1. git status — verify clean
2. git checkout -b cleanup-batch-ab
3. git tag pre-cleanup-v0.x -m "Snapshot before Batch A/B reduction"

KHÔNG push remote nếu chưa setup (single-user local OK).

Verify:
- git branch → thấy cleanup-batch-ab có *
- git tag -l → thấy pre-cleanup-v0.x

Báo cáo output.
```

🙋 **Bạn cần làm tay:** Confirm output git rõ ràng.

✅ **Kiểm tra:** Branch + tag tồn tại.

---

### STEP 0.4 — Batch A: xóa `learning/optimizer.py`

🎯 **Mục tiêu:** Xóa ~450 dòng dead code (optimizer "AI scoring AI"). Baseline diff zero — output không đổi vì optimizer chỉ ảnh hưởng learning, không ảnh hưởng scrape trên profile đã có.

🗣️ **Bạn nói với Claude Code:**

```
Task: Batch A — xóa learning/optimizer.py.

⚠️ ĐỌC CLAUDE.md §3 item 12 (Batch A scope) + §18 anti-pattern #9 (Optimizer rationale).
⚠️ ĐỌC ROADMAP.md P0.2 cho acceptance criteria.

Bước trước khi delete:
1. grep -rn "optimizer" --include="*.py" .
   → Liệt kê MỌI import + call site
2. View từng call site, plan removal (paste cho tôi xem plan)
3. HỎI tôi confirm plan TRƯỚC khi code

Sau khi tôi confirm:
DELETE:
- learning/optimizer.py (xóa hẳn)

MODIFY:
- learning/phase.py — remove import + call site
- learning/phase_ai.py — verify đã clean (Batch A nửa đường rồi, có thể đã xóa AI#8/9 nav_stress/full_simulation)
- config.py — remove constants OPTIMIZER_* nếu còn
- main.py — flag --fast-learning: KEEP nhưng đổi semantic. Update help text từ:
    "Bỏ qua optimizer, chỉ dùng AI selectors"
  thành:
    "Skip ProseRichness validation trong learning phase (nhanh hơn ~20%)"

Verify (BẮT BUỘC theo CLAUDE.md §9.1):
1. python -c "import learning.phase; import learning.phase_ai" → không ImportError
2. python -m py_compile $(git ls-files '*.py') → 0 lỗi
3. Smoke test: python main.py links.txt với 1 URL FFN test → scrape >=3 chapter
4. BASELINE DIFF (critical):
   python tools/snapshot_baseline.py --profile fanfiction.net --chapters 5 --label phase0_ffn_post_batchA --url <SAME URL như phase0_ffn>
   diff -r data/baselines/phase0_ffn/ data/baselines/phase0_ffn_post_batchA/
   → Phải ZERO diff (trừ _meta.json timestamp khác)

Nếu diff KHÔNG zero (ngoài timestamp):
   STOP — KHÔNG commit. Báo tôi output diff, debug root cause.

Commit (chỉ khi diff zero): refactor(learning): xóa optimizer.py (Batch A) — 450 dòng dead code

Báo cáo:
- Số dòng xóa thực tế (git diff --stat)
- Output baseline diff
- Smoke test output (3 chapter đầu)
```

🙋 **Bạn cần làm tay:**

Review plan removal của Claude Code TRƯỚC khi cho phép delete. Đặc biệt check:
- `learning/optimizer.py` có import từ module khác không? (nếu có → xử lý trước)
- `--fast-learning` semantic đổi → có user nào của bạn (chính bạn 1 tháng nữa) sẽ confuse không?

✅ **Kiểm tra:**
- File `learning/optimizer.py` không còn (`ls learning/optimizer.py` → No such file)
- Baseline diff ZERO ngoài timestamp
- Commit `refactor(learning): xóa optimizer.py (Batch A)` ở HEAD
- `git diff --stat HEAD~1 HEAD` show ~450 dòng deletion

---

### STEP 0.5 — Batch B: xóa StepConfig serialization + migrator

🎯 **Mục tiêu:** Xóa ~330 dòng — root cause bug M4 (nested params lost roundtrip). Profile cũ có `pipeline` field sẽ phải re-learn (KHÔNG auto-migrate).

🗣️ **Bạn nói với Claude Code:**

```
Task: Batch B — xóa StepConfig serialization + migrator.

⚠️ ĐỌC CLAUDE.md §18 anti-pattern #3 (M4 bug rationale) + §17 Decision #9.
⚠️ ĐỌC ROADMAP.md P0.3 cho acceptance criteria.
⚠️ STOP RULE: đây là refactor shared logic (pipeline/base.py, pipeline/executor.py).
   Đụng = phá toàn bộ scraper. Plan kỹ trước.

Bước trước:
1. grep -rn "StepConfig\|ChainConfig\|PipelineConfig" --include="*.py" .
   → Verify state hiện tại — có thể đã xóa nửa đường rồi
2. grep -rn "migrator\|migrate_profile\|needs_migration" --include="*.py" .
   → List mọi usage
3. grep -rn "from_legacy_dict" --include="*.py" .
   → Check còn dùng không
4. HỎI tôi confirm plan TRƯỚC khi xóa.

Sau khi tôi confirm:

DELETE:
- learning/migrator.py (~150 dòng)

MODIFY:
- pipeline/base.py — remove StepConfig/ChainConfig/PipelineConfig classes nếu còn
- pipeline/executor.py — remove _make_block, ensure from_profile() đọc thẳng SiteProfile flat fields (Batch B đã làm 1 phần)
- learning/profile_manager.py — remove migration call (needs_migration / migrate_profile)
- utils/types.py — verify SiteProfile không còn 'pipeline' field

GIỮ (đừng đụng):
- pipeline/executor.py từ_profile() flat-field reading logic (đã work)
- Atomic write trong ProfileManager
- AdsFilter threading.Lock

⚠️ QUAN TRỌNG: Trước khi xóa migrator, thêm 1 safety net:
   Trong learning/profile_manager.py load_profile():
     Nếu detect legacy field 'pipeline' trong profile → fail-loud:
       raise ValueError(
         f"Profile {domain} ở v1 format (có 'pipeline' field). "
         f"Cần re-learn. Chạy: python main.py --bulk-relearn --pattern {domain}"
       )
   Mục đích: user không bị crash bí ẩn ở chỗ khác, có message rõ.

Verify:
1. python -c "from pipeline.base import *; from pipeline.executor import *; from learning.profile_manager import *" → 0 ImportError
2. python -m py_compile $(git ls-files '*.py') → 0 lỗi
3. Smoke test 2 site: FFN + RR (cả 2 đã learn), scrape 5 chapter mỗi cái
4. BASELINE DIFF cho cả 2 label:
   python tools/snapshot_baseline.py ... --label phase0_ffn_post_batchB ...
   python tools/snapshot_baseline.py ... --label phase0_rr_post_batchB ...
   diff -r data/baselines/phase0_ffn/ data/baselines/phase0_ffn_post_batchB/
   diff -r data/baselines/phase0_rr/ data/baselines/phase0_rr_post_batchB/
   → Phải ZERO diff (trừ _meta.json timestamp)
5. Test legacy guard: tạm thêm dummy profile có "pipeline" field vào data/site_profiles.json, chạy main.py với domain đó → phải fail với message rõ. Sau test, xóa dummy.

Nếu baseline diff KHÔNG zero:
   STOP — possible migrator đã silently fix profile khi load. Debug.

Commit: refactor(pipeline): xóa StepConfig serialization (Batch B) — 330 dòng

Báo cáo:
- Số dòng xóa thực tế
- Output baseline diff cả 2 site
- Output test legacy guard
```

🙋 **Bạn cần làm tay:**

Review plan removal trước khi confirm. Đặc biệt check:
- `from_legacy_dict` còn được dùng ở đâu không? Có thể có code ngầm dựa vào nó.
- Profile cũ trong `data/site_profiles.json` có `pipeline` field không? Backup file này trước (`cp data/site_profiles.json data/site_profiles.bak.json`).

✅ **Kiểm tra:**
- File `learning/migrator.py` không còn
- Baseline diff ZERO cho cả 2 site
- Legacy profile guard work (fail-loud với message rõ)
- Commit `refactor(pipeline): xóa StepConfig serialization (Batch B)` ở HEAD

---

### STEP 0.6 — README skeleton

🎯 **Mục tiêu:** README.md user-facing, 5 phút clone repo → chạy được.

🗣️ **Bạn nói với Claude Code:**

```
Task: README skeleton.

⚠️ ĐỌC CLAUDE.md §17 Decision #25 (README maintained throughout).

ADD: README.md (~100 dòng) ở root, nội dung tối thiểu:

# Cào Text

> Universal novel content normalizer — ném input nào vào (URL truyện đa site / EPUB / TXT) cũng ra được bộ chapter sạch, đọc được trên Obsidian hoặc đem đi dịch.

## Features (v1.0 WIP)

- 3 input types: web URL list, EPUB file, TXT file
- 3 output modes: Obsidian Markdown, Translation plain text, Raw text
- Multi-site web: learning AI 1 lần per domain, reuse profile vô hạn lần
- Image support cho web novel (Obsidian mode)
- i18n: UTF-8 baseline, work với content EN/VN/EN-translated CN/KR/JP

## Quick Start (5 phút)

### Prerequisites
- Python 3.11+
- Gemini API key (free tier OK)

### Install

```bash
git clone <repo>
cd "Cào text"
pip install -r requirements.txt
# Hoặc nếu dùng uv:
uv sync
```

### Setup
1. Tạo `.env` với:
```
GEMINI_API_KEY=AIza...
```

2. Tạo `links.txt` với URL chapter 1 của truyện:
```
https://www.fanfiction.net/s/12345/1/Story-Title
```

3. Chạy:
```bash
python main.py links.txt
```

Lần đầu cào 1 domain mới: AI sẽ learn cấu trúc (~10 calls, ~$0.02), lưu profile vào `data/site_profiles.json`. Lần sau xài lại, không tốn AI call nữa.

## CLI Flags

| Flag | Mô tả |
|---|---|
| `--output-mode {obsidian,translate,raw}` | Output format. Default: obsidian |
| `--max-pw N` | Số Playwright instances song song (default 2) |
| `--fast-learning` | Skip ProseRichness validation trong learning phase |
| `--no-validation` | Skip ProseRichnessBlock khi scrape |
| `--bulk-relearn [--pattern <regex>]` | Bulk delete profile cũ + re-learn |

## links.txt syntax

```
https://royalroad.com/fiction/...   # URL to scrape
!relearn royalroad.com              # Force re-learn domain (single)
# comment                           # Ignored
```

## Folder structure

```
input/  → links.txt, novel.epub, novel.txt
output/ → 1 folder per story, chapter files inside
data/   → site_profiles.json, ads_keywords.json, baselines/
progress/ → resume state per story
```

## Limitations v1.0

- TXT chapter pattern: chỉ VN ("Chương N") + EN ("Chapter N"). CJK ("第N章") defer v1.1.
- Site CJK native (raw Trung/Nhật/Hàn) chưa hardened — basic UTF-8 work nhưng có thể có encoding edge case.
- Manhua thuần (image-primary) không phải scope — dùng gallery-dl.

## Troubleshooting

- **Profile cũ crash sau update**: chạy `python main.py --bulk-relearn`
- **CloudFlare block**: tự động fallback Playwright (cần Chromium cài)
- **Gemini rate limit**: token bucket có sẵn, chờ tự nhả

Verify:
- README render OK trên VS Code preview
- Mọi CLI flag hiện hữu đều có

Commit: docs: add README.md with quick start guide
```

🙋 **Bạn cần làm tay:**

Đọc qua README, nếu thấy chỗ nào lạ với codebase thực tế (vd flag không tồn tại), bảo Claude Code fix.

✅ **Kiểm tra:** `README.md` ở root, render đẹp.

---

### STEP 0.7 — Bulk relearn script + MIGRATION_NOTES

🎯 **Mục tiêu:** Có `python main.py --bulk-relearn [--pattern <regex>]` work với dry-run default. UX an toàn — không silent delete profile.

🗣️ **Bạn nói với Claude Code:**

```
Task: Bulk relearn flag + migration notes.

⚠️ ĐỌC CLAUDE.md §17 Decision #24.
⚠️ UX QUAN TRỌNG: regex pattern có thể greedy hơn user nghĩ.
   Vd --pattern "net" match cả "fanfiction.net" và "novelfire.net".
   Default phải dry-run, user explicit --apply mới thực delete.

MODIFY:
- main.py — add args:
  --bulk-relearn (action store_true)
  --pattern <regex> (optional, default match-all)
  --apply (action store_true, default False → dry-run)

Logic bulk-relearn:
1. Load data/site_profiles.json
2. Filter domain theo --pattern (regex.search, default match all)
3. Print danh sách domain MATCH dạng:
     "Sẽ xóa N profile:"
     "  - fanfiction.net (5 sample URLs, last_learned 2026-04-10)"
     "  - royalroad.com (10 sample URLs, last_learned 2026-04-15)"
4. NẾU không có --apply:
   Print "DRY RUN — không xóa gì. Thêm --apply để thực hiện."
   Exit 0
5. NẾU có --apply:
   Confirm prompt typed input:
     "To proceed, type: delete <N> profiles"
   Nếu user gõ đúng exact string → proceed
   Nếu sai → "Cancelled." exit 0
6. Atomic delete: load JSON, pop matched keys, save atomic (.tmp + rename)
7. Print "Deleted N profile. Run main.py links.txt để re-learn."

ADD:
- docs/MIGRATION_NOTES.md (~50 dòng):

# Migration Notes

## v0.x → v1.0 (Batch A/B)

### Breaking changes
1. **Profile schema v1 → v2** (Batch B): profile có 'pipeline' field flat dict không còn được auto-migrate. Phải re-learn.
2. **--fast-learning semantic đổi** (Batch A): trước là "skip optimizer", giờ là "skip ProseRichness validation in learning phase".

### Cách migrate profile cũ

#### Option A: bulk re-learn (recommended nếu có nhiều profile cũ)
```bash
# Preview xem profile nào sẽ bị xóa (dry-run mặc định):
python main.py --bulk-relearn

# Nếu chỉ muốn xóa một subset:
python main.py --bulk-relearn --pattern "fanfiction|royalroad"

# Sau khi review, thực hiện:
python main.py --bulk-relearn --pattern "fanfiction|royalroad" --apply
# Typed confirmation required: "delete 2 profiles"
```

#### Option B: per-site re-learn
Thêm vào `links.txt`:
```
!relearn fanfiction.net
!relearn royalroad.com
https://royalroad.com/fiction/xxx/chapter-1
```

#### Option C: nuke và re-learn từ đầu
```bash
rm data/site_profiles.json
python main.py links.txt
```

### Verify migration thành công
Sau re-learn, mở `data/site_profiles.json`, profile mới phải có:
- `"profile_version": 2`
- KHÔNG có key `"pipeline"`
- KHÔNG có key `"optimizer_score"`

Verify:
- python main.py --bulk-relearn → dry-run, list profile, không xóa gì
- python main.py --bulk-relearn --pattern "nonexistent" → list rỗng + exit OK
- python main.py --bulk-relearn --pattern "test" --apply (sau tạo dummy profile "test.com")
  → typed confirm prompt → gõ đúng → delete → verify file
- Manual: kiểm tra MIGRATION_NOTES.md render đẹp

Commit: feat(cli): add --bulk-relearn flag with dry-run + typed confirmation
```

🙋 **Bạn cần làm tay:**

Test thực: tạo dummy profile `test.example.com` trong `data/site_profiles.json`, chạy `--bulk-relearn --pattern test --apply`, gõ confirm string, verify dummy bị xóa.

✅ **Kiểm tra:**
- Dry-run mặc định, không silent delete
- Typed confirmation work
- `docs/MIGRATION_NOTES.md` tồn tại

---

### STEP 0.8 — Sync docs + merge cleanup branch

🎯 **Mục tiêu:** 3 governance docs đồng bộ với state sau Batch A/B. Merge `cleanup-batch-ab` vào `main`.

🗣️ **Bạn nói với Claude Code:**

```
Task: Sync docs + merge cleanup branch.

MODIFY:
- CLAUDE.md §17 Decision Log — add row Batch A done + Batch B done (date)
- BLUEPRINT.md §10 Phase 0 — mark all checkboxes done
- ROADMAP.md Phase 0 — mark P0.0 → P0.7 done

Verify:
- 3 file không nhắc StepConfig/optimizer như tính năng hiện hữu
- README quick start chạy được sạch (test mentally)

Commit: docs: sync governance after Batch A/B cleanup

Sau commit, bước merge:
1. git status — verify clean
2. git log cleanup-batch-ab --oneline → verify 6-7 commits conventional
3. Full regression test:
   - python tools/snapshot_baseline.py --label final_phase0_ffn ... (same URL)
   - diff -r data/baselines/phase0_ffn/ data/baselines/final_phase0_ffn/
   - Phải ZERO ngoài timestamp
4. Smoke test 1 site mới (chưa có profile) → learning phase work end-to-end
   - Pick 1 URL test, ví dụ novelfire.net
   - python main.py links.txt → learn → scrape 5 chapter
5. git checkout main
6. git merge cleanup-batch-ab --no-ff -m "merge: Phase 0 cleanup (Batch A/B) complete"
7. git tag v0.x-post-cleanup -m "Phase 0 complete: 780 lines removed"

Báo cáo:
- Output git log final
- Output baseline diff
- Output learning phase test site mới
```

🙋 **Bạn cần làm tay:**

Verify branch merged OK trên `main`, tag tạo.

✅ **Kiểm tra:** Phase 0 done. Tag `v0.x-post-cleanup` ở `main`.

---

## ⚙️ PHASE 1 — Output Mode Abstraction (1.5 tuần)

> **Mục tiêu cuối Phase 1:** RunConfig + CleanedChapter DTO + ChapterWriter interface có. ObsidianWriter (port từ chapter_writer.py) work. Pipeline produce DTO thay vì ghi file trực tiếp. Baseline diff vs Phase 0: body identical, chỉ thêm frontmatter YAML.
>
> **TẠI SAO PHASE 1 (KHÔNG PHẢI PHASE 2 CŨ):** Image policy là per-mode → cần RunConfig trước → cần CleanedChapter trước. Đảo thứ tự = technical debt cố ý.

### STEP 1.1 — Define `RunConfig` + CLI flag

🎯 **Mục tiêu:** Có `RunConfig` dataclass + CLI flag `--output-mode`. Default behavior (no flag) = obsidian = behavior hiện tại.

🗣️ **Bạn nói với Claude Code:**

```
Task: RunConfig + CLI flag.

⚠️ ĐỌC BLUEPRINT.md §8 (RunConfig schema).
⚠️ KHÔNG sửa pipeline yet — chỉ thêm config + CLI.

ADD:
1. utils/types.py — thêm RunConfig dataclass (~40 dòng):

   from __future__ import annotations
   from dataclasses import dataclass
   from typing import Literal

   @dataclass
   class RunConfig:
       output_mode      : Literal["obsidian", "translate", "raw"]
       download_images  : bool
       image_placeholder: bool
       fetch_metadata   : bool
       output_dir       : str
       max_pw_instances : int = 2
       fast_learning    : bool = False
       no_validation    : bool = False

       @classmethod
       def from_cli(cls, args) -> "RunConfig":
           mode = args.output_mode
           defaults = {
               "obsidian":  {"dl": True,  "ph": False, "meta": True},
               "translate": {"dl": False, "ph": True,  "meta": False},
               "raw":       {"dl": False, "ph": False, "meta": False},
           }[mode]
           return cls(
               output_mode       = mode,
               download_images   = defaults["dl"],
               image_placeholder = defaults["ph"],
               fetch_metadata    = defaults["meta"],
               output_dir        = args.output_dir,
               max_pw_instances  = args.max_pw_instances or 2,
               fast_learning     = args.fast_learning,
               no_validation     = args.no_validation,
           )

MODIFY:
2. main.py — thêm CLI flag:
   --output-mode {obsidian,translate,raw} (default obsidian)
   --output-dir <path> (default "output")

   Trong main():
     run_config = RunConfig.from_cli(args)
     # Pass tiếp run_config xuống flow (chưa dùng yet)

Verify:
- python main.py --help → thấy --output-mode + --output-dir
- python -c "from utils.types import RunConfig; rc = RunConfig.from_cli(type('A',(),{'output_mode':'obsidian','output_dir':'output','max_pw_instances':None,'fast_learning':False,'no_validation':False})()); print(rc)"
  → RunConfig in ra đúng default
- Smoke test: python main.py links.txt (không có --output-mode) → behavior CŨ KHÔNG ĐỔI
- Baseline diff: chạy snapshot label `phase1_pre`, diff với `phase0_ffn` → zero

Commit: feat(config): add RunConfig dataclass + CLI flag for output mode

Báo cáo: CLI help output + smoke test output.
```

🙋 **Bạn cần làm tay:** Verify CLI help hiển thị flag mới.

✅ **Kiểm tra:** Flag work, behavior cũ không đổi.

---

### STEP 1.2 — Define `CleanedChapter` + `ImageRef` + `FormattingRules` DTOs

🎯 **Mục tiêu:** DTO importable, type-safe. FormattingRules có `image_alt_strategy` enum thay cho boolean cũ.

🗣️ **Bạn nói với Claude Code:**

```
Task: Define CleanedChapter, ImageRef, FormattingRules DTOs.

⚠️ ĐỌC BLUEPRINT.md §8 cho schema chi tiết.

ADD:
1. pipeline/base.py — thêm cuối file (sau PipelineContext):

   from dataclasses import field
   from typing import Literal

   @dataclass
   class ImageRef:
       original_url    : str
       local_path      : str | None
       alt_text        : str
       position_marker : str
       source_type     : Literal["web", "epub"]

   @dataclass
   class CleanedChapter:
       index           : int
       title           : str
       body_markdown   : str
       images          : list[ImageRef] = field(default_factory=list)
       source_url      : str | None     = None
       source_path     : str | None     = None
       metadata        : dict           = field(default_factory=dict)

MODIFY:
2. utils/types.py — UPDATE FormattingRules TypedDict (explicit schema):

   class FormattingRules(TypedDict, total=False):
       headings_as_h2       : bool
       preserve_bold        : bool
       preserve_italic      : bool
       preserve_blockquote  : bool
       paragraph_separator  : str
       list_style           : Literal["dash", "asterisk"]
       image_alt_strategy   : Literal["preserve", "skip", "fallback_to_filename"]
       strip_inline_links   : bool
       strip_html_comments  : bool
       text_encoding        : str

⚠️ Decision #23: image_alt_strategy thay cho boolean image_alt_text cũ.

3. ai/agents.py / learning/phase_ai.py — verify chỗ nào set `image_alt_text` boolean:
   - Convert thành: image_alt_strategy = "preserve" if image_alt_text else "skip"
   - Add migration code trong _build_final_profile: nếu AI#6 trả image_alt_text (legacy), convert sang image_alt_strategy

Verify:
- python -c "from pipeline.base import CleanedChapter, ImageRef; from utils.types import FormattingRules; print('OK')"
- Smoke test: python main.py links.txt → 0 crash, output không đổi (chưa dùng DTO)
- Baseline diff vs phase0_ffn → zero

Commit: feat(types): add CleanedChapter, ImageRef, FormattingRules DTOs
```

🙋 **Bạn cần làm tay:** Verify import OK.

✅ **Kiểm tra:** DTO importable, behavior không đổi.

---

### STEP 1.3 — `output/base.py` ChapterWriter ABC

🎯 **Mục tiêu:** ABC `ChapterWriter` với `write()` + `filename_for()` abstract method.

🗣️ **Bạn nói với Claude Code:**

```
Task: ChapterWriter ABC.

ADD:
1. output/__init__.py (empty)
2. output/base.py (~60 dòng):

   from __future__ import annotations
   import os
   from abc import ABC, abstractmethod
   from pathlib import Path
   from pipeline.base import CleanedChapter
   from utils.types import RunConfig

   class ChapterWriter(ABC):
       def __init__(self, output_dir: str, run_config: RunConfig) -> None:
           self.output_dir = output_dir
           self.run_config = run_config

       @abstractmethod
       async def write(self, chapter: CleanedChapter) -> Path:
           """Write CleanedChapter to file, return path."""

       @abstractmethod
       def filename_for(self, chapter: CleanedChapter) -> str:
           """Return filename (relative to output_dir) for chapter."""

       def _ensure_dir(self, path: Path) -> None:
           path.parent.mkdir(parents=True, exist_ok=True)

       def _atomic_write_text(self, path: Path, content: str) -> None:
           tmp = path.with_suffix(path.suffix + ".tmp")
           tmp.write_text(content, encoding="utf-8")
           os.replace(tmp, path)

Verify:
- python -c "from output.base import ChapterWriter; print('OK')"
- python -c "from output.base import ChapterWriter; ChapterWriter('out', None)" → TypeError (abstract)

Commit: feat(output): add ChapterWriter ABC
```

✅ **Kiểm tra:** ABC importable, không instantiate được trực tiếp.

---

### STEP 1.4 — ObsidianWriter (port từ `core/chapter_writer.py`)

🎯 **Mục tiêu:** ObsidianWriter implement đầy đủ behavior của `chapter_writer.py` hiện tại + thêm YAML frontmatter.

🗣️ **Bạn nói với Claude Code:**

```
Task: ObsidianWriter — port từ core/chapter_writer.py.

⚠️ ĐỌC core/chapter_writer.py kỹ — phải preserve EXACT behavior:
- Filename generation (0042_Chapter_Title.md)
- Garbage subtitle detection
- Site suffix stripping
- Slugify Vietnamese

ADD: output/obsidian.py (~200 dòng):

   from __future__ import annotations
   from pathlib import Path
   from pipeline.base import CleanedChapter
   from output.base import ChapterWriter
   # Reuse helpers từ core/chapter_writer.py:
   from core.chapter_writer import (
       _slugify_title,
       _strip_site_suffix,
       _is_garbage_subtitle,
       _format_index,  # 0042 padding
   )

   class ObsidianWriter(ChapterWriter):
       async def write(self, chapter: CleanedChapter) -> Path:
           filename = self.filename_for(chapter)
           path = Path(self.output_dir) / filename
           self._ensure_dir(path)
           content = self._build_content(chapter)
           self._atomic_write_text(path, content)
           return path

       def filename_for(self, chapter: CleanedChapter) -> str:
           # Reuse logic chapter_writer.py
           idx_str = _format_index(chapter.index)
           title_clean = _strip_site_suffix(chapter.title)
           if _is_garbage_subtitle(title_clean):
               return f"{idx_str}.md"
           slug = _slugify_title(title_clean)
           return f"{idx_str}_{slug}.md"

       def _build_content(self, chapter: CleanedChapter) -> str:
           lines = ["---"]
           lines.append(f"title: {chapter.title!r}")
           lines.append(f"chapter_index: {chapter.index}")
           if chapter.source_url:
               lines.append(f"source_url: {chapter.source_url}")
           if chapter.source_path:
               lines.append(f"source_path: {chapter.source_path}")
           for k, v in chapter.metadata.items():
               if k in {"story_name", "language", "author"}:
                   lines.append(f"{k}: {v!r}")
           # Failed image log
           failed_imgs = [
               img.original_url for img in chapter.images
               if img.local_path is None and img.source_type == "web"
           ]
           if failed_imgs:
               lines.append(f"failed_images: {failed_imgs}")
           lines.append("---")
           lines.append("")
           lines.append(chapter.body_markdown)
           if chapter.source_url and self.run_config.output_mode == "obsidian":
               lines.append("")
               lines.append(f"> Source: {chapter.source_url}")
           return "\n".join(lines)

KEEP:
- core/chapter_writer.py — sẽ delete ở P1.5, hiện giữ vì callers chưa migrate

Verify:
- python -c "from output.obsidian import ObsidianWriter; print('OK')"
- Unit test inline:
   from pipeline.base import CleanedChapter
   from utils.types import RunConfig
   c = CleanedChapter(index=42, title="Test Chapter", body_markdown="hello world",
                      source_url="http://x.com/c/42")
   w = ObsidianWriter("test_out", RunConfig(output_mode="obsidian", download_images=True,
                       image_placeholder=False, fetch_metadata=True, output_dir="test_out"))
   import asyncio; p = asyncio.run(w.write(c))
   print(open(p).read())
   → Verify YAML frontmatter + body + source footer

Commit: feat(output): add ObsidianWriter with YAML frontmatter
```

🙋 **Bạn cần làm tay:** Verify output test file có frontmatter format đúng.

✅ **Kiểm tra:** ObsidianWriter standalone work.

---

### STEP 1.5 — Pipeline produce `CleanedChapter` (🛑 REFACTOR LỚN — STOP)

🎯 **Mục tiêu:** PipelineRunner.run() return CleanedChapter, caller gọi writer.write(). Output Markdown vs Phase 0 baseline: body identical, chỉ thêm frontmatter YAML.

> **⚠️ EXIT RAMP:** Nếu sau 3 attempt baseline diff không pass (ngoài frontmatter), rollback branch + reassess. Đừng "fix forward" 5 ngày.

🗣️ **Bạn nói với Claude Code:**

```
Task: REFACTOR LỚN — pipeline produce CleanedChapter DTO.

🛑 STOP RULE: ĐỌC CLAUDE.md §10 — đụng shared logic (core/scraper.py, pipeline/executor.py).
   Phải plan kỹ + tôi confirm TRƯỚC khi code.

⚠️ ĐỌC:
- core/scraper.py (run_novel_task + _scrape_loop) — flow hiện tại
- pipeline/executor.py (PipelineRunner.run)
- core/chapter_writer.py — sẽ delete

Plan template (CLAUDE.md §8.1) — paste cho tôi xem trước khi code:

**Tôi hiểu task:** [...]
**Tôi sẽ làm:** [bullets]
**Files động vào:** [list]
**Phụ thuộc:** Phase 0 done, ObsidianWriter ready
**Rủi ro:**
- Behavior change nhỏ trong filename generation
- Cancel handling mid-write
- Progress JSON update timing
**Behavior phải preserve (checklist):**
- [ ] Filename generation pattern không đổi
- [ ] Resume từ progress JSON work
- [ ] Cancel handling (Ctrl+C) clean
- [ ] Update progress sau write thành công
- [ ] Update SiteProfile nếu requires_playwright change
- [ ] AdsFilter save atomic
- [ ] Error recovery mid-chapter
**Kết quả dự kiến:** Baseline diff body identical, chỉ thêm frontmatter.

⚠️ TÔI SẼ REVIEW PLAN. KHÔNG code trước khi tôi confirm.

Sau khi tôi confirm:

MODIFY:
1. pipeline/executor.py — PipelineRunner.run() return CleanedChapter
   (build từ ctx.content, ctx.title_clean, ctx.next_url, ctx.url)
2. core/scraper.py — _scrape_loop:
   - Nhận run_config + writer instance
   - Loop: chapter = await runner.run() → await writer.write(chapter)
   - Image stage: stub no-op (P2 sẽ add)

DELETE:
3. core/chapter_writer.py — chỉ delete SAU KHI verify ObsidianWriter cover hết:
   - Filename pattern identical
   - Garbage subtitle handling identical
   - Slugify identical

Verify (CRITICAL):
1. Smoke test 3 mode × 1 URL FFN:
   python main.py links.txt --output-mode obsidian
   python main.py links.txt --output-mode translate
   python main.py links.txt --output-mode raw
   (translate/raw mode dùng tạm ObsidianWriter — P4 hoàn thiện)

2. BASELINE DIFF:
   python tools/snapshot_baseline.py --label phase1_ffn ... (same URL như phase0_ffn)
   diff -r data/baselines/phase0_ffn/ data/baselines/phase1_ffn/
   → Expected diff: chỉ frontmatter YAML thêm vào, body text identical.

3. Behavior preservation:
   - Resume test: kill mid-scrape, resume → tiếp tục đúng chapter kế
   - Cancel test: Ctrl+C → clean shutdown, không corrupt file
   - Progress JSON: update đúng sau mỗi chapter

🛑 EXIT RAMP:
Nếu diff KHÔNG fit pattern "frontmatter added, body identical":
   Attempt 1: debug, identify cause
   Attempt 2: fix, re-verify
   Attempt 3: nếu vẫn fail → STOP, rollback branch cleanup-batch-ab, báo tôi.
   KHÔNG fix forward 5 ngày.

Commit (chỉ khi diff acceptable): refactor(pipeline): introduce CleanedChapter DTO + writer abstraction

Báo cáo:
- Plan trước khi code
- Baseline diff output (frontmatter vs body)
- Behavior preservation checklist
```

🙋 **Bạn cần làm tay:**

Đây là step rủi ro nhất Phase 1. Review plan của Claude Code KỸ. Đặc biệt:
- Hỏi rõ nó hiểu interface giữa `_scrape_loop` và writer như nào
- Trade-off: writer instance tạo 1 lần per task hay per chapter? (recommend: 1 lần per task)
- Cancel mid-write: writer phải handle CancelledError → cleanup tmp file

Nếu attempt 3 vẫn fail → bạn cần ngồi nghĩ liệu CleanedChapter abstraction có quá ambitious cho codebase này không.

✅ **Kiểm tra:**
- Baseline diff: body identical, chỉ frontmatter thêm
- Behavior preservation 7/7 pass
- Commit ở HEAD

---

### STEP 1.6 — Smoke test Phase 1 + Phase 1 Retro

🎯 **Mục tiêu:** Phase 1 done. Documented retrospective.

🗣️ **Bạn nói với Claude Code:**

```
Phase 1 retrospective:

1. Full smoke test:
   - 1 URL × 3 mode (obsidian/translate/raw) → 3 output dir
   - Resume test sau kill
   - Cancel test
   - Bulk relearn test
2. Baseline snapshot label phase1_final cho FFN + RR
3. Tổng kết docs/PHASE_1_RETRO.md:
   - Plan vs Actual (ngày)
   - Cái gì làm tốt
   - Cái gì khó / mất nhiều thời gian
   - Tech debt accumulate (nếu có)
   - Risks cho Phase 2

4. Update:
   - CLAUDE.md §17 — add decision rows mới nếu có
   - ROADMAP.md — mark Phase 1 done
   - README.md — update CLI flag list nếu có thêm

5. Tag: git tag v0.x-phase1 -m "Phase 1: Output abstraction complete"

Commit: chore: phase 1 retrospective + tag
```

✅ **Kiểm tra:** Phase 1 closed, tag tạo.

---

## 🖼️ PHASE 2 — Image Support cho Web (2 tuần)

> **Mục tiêu cuối Phase 2:** Royal Road novel có illustration → output Obsidian có `images/` folder + Markdown embed đúng vị trí + Obsidian render OK. 3 mode handling image khác nhau.

### STEP 2.1 — `utils/image_url.py` resolver

🎯 **Mục tiêu:** Function `resolve_image_url(tag, base_url)` handle 6+ case (lazy-load, srcset, protocol-relative, data URI).

🗣️ **Bạn nói với Claude Code:**

```
Task: image_url resolver helper.

ADD: utils/image_url.py (~100 dòng):

   from __future__ import annotations
   from urllib.parse import urljoin
   from bs4 import Tag

   def resolve_image_url(tag: Tag, base_url: str) -> str | None:
       """
       Resolve <img> tag's URL to absolute form.
       Return None for data URIs or invalid sources.
       """
       # Order of preference for src attributes (lazy-load variants)
       attrs = ["src", "data-src", "data-original", "data-lazy-src", "data-actual-src"]
       url = None
       for attr in attrs:
           val = tag.get(attr)
           if val and not val.startswith("data:"):
               url = val
               break

       # srcset (pick highest resolution)
       if not url:
           srcset = tag.get("srcset")
           if srcset:
               # "url1 1x, url2 2x" → pick last (highest descriptor)
               parts = [p.strip() for p in srcset.split(",")]
               if parts:
                   url = parts[-1].split()[0]

       if not url:
           return None
       if url.startswith("data:"):
           return None

       # Protocol-relative
       if url.startswith("//"):
           return "https:" + url
       # Already absolute
       if url.startswith(("http://", "https://")):
           return url
       # Relative
       return urljoin(base_url, url)

   def detect_image_extension(content_type: str | None, magic_bytes: bytes) -> str:
       """Detect file extension from Content-Type or magic bytes."""
       if content_type:
           ct = content_type.lower().split(";")[0].strip()
           ct_map = {
               "image/jpeg": ".jpg", "image/jpg": ".jpg",
               "image/png": ".png", "image/webp": ".webp",
               "image/gif": ".gif",
           }
           if ct in ct_map:
               return ct_map[ct]
       # Magic bytes fallback
       if magic_bytes.startswith(b"\xff\xd8\xff"):
           return ".jpg"
       if magic_bytes.startswith(b"\x89PNG"):
           return ".png"
       if magic_bytes.startswith(b"RIFF") and b"WEBP" in magic_bytes[:12]:
           return ".webp"
       if magic_bytes.startswith(b"GIF8"):
           return ".gif"
       return ".jpg"  # safe fallback

Test inline:
   from bs4 import BeautifulSoup
   from utils.image_url import resolve_image_url

   cases = [
       ('<img src="https://cdn.com/a.jpg">', "https://x.com/", "https://cdn.com/a.jpg"),
       ('<img data-src="/img/b.jpg">', "https://x.com/", "https://x.com/img/b.jpg"),
       ('<img src="//cdn.com/c.jpg">', "https://x.com/", "https://cdn.com/c.jpg"),
       ('<img src="data:image/png;base64,xx">', "https://x.com/", None),
       ('<img srcset="a.jpg 1x, b.jpg 2x">', "https://x.com/", "https://x.com/b.jpg"),
       ('<img src="">', "https://x.com/", None),
   ]
   for html, base, expected in cases:
       soup = BeautifulSoup(html, "html.parser")
       got = resolve_image_url(soup.img, base)
       assert got == expected, f"FAIL: {html} → {got} (expected {expected})"
   print("All 6 cases pass")

Commit: feat(utils): add image_url resolver
```

✅ **Kiểm tra:** 6 case pass inline test.

---

### STEP 2.2 — `core/image_pipeline/` strategy infrastructure

🎯 **Mục tiêu:** `ImageFetchStrategy` ABC + `WebImageFetcher` work với HTTP fetch.

🗣️ **Bạn nói với Claude Code:**

```
Task: Image fetch strategy infrastructure.

⚠️ ĐỌC BLUEPRINT.md §6 (Image stage) + Decision #19.

ADD:
1. core/image_pipeline/__init__.py (empty)
2. core/image_pipeline/base.py (~50 dòng):

   from abc import ABC, abstractmethod
   from pipeline.base import ImageRef

   class ImageFetchStrategy(ABC):
       @abstractmethod
       async def fetch(self, ref: ImageRef) -> bytes | None:
           """Fetch image bytes. Return None on failure."""

       async def fetch_batch(self, refs: list[ImageRef], output_dir: str) -> list[ImageRef]:
           """Fetch list of refs, populate local_path field, save to output_dir/images/."""
           # Default impl: sequential. Subclass override để concurrent.
           import os
           os.makedirs(os.path.join(output_dir, "images"), exist_ok=True)
           for ref in refs:
               try:
                   data = await self.fetch(ref)
                   if data:
                       # save logic in subclass-specific helper
                       ref.local_path = self._save(ref, data, output_dir)
                   else:
                       ref.local_path = None
               except Exception as e:
                   import logging
                   logging.getLogger(__name__).warning(
                       "Image fetch failed: %s — %s", ref.original_url, e
                   )
                   ref.local_path = None
           return refs

       def _save(self, ref: ImageRef, data: bytes, output_dir: str) -> str:
           # default impl
           ...

3. core/image_pipeline/web_fetcher.py (~150 dòng):

   import asyncio
   from pipeline.base import ImageRef
   from core.image_pipeline.base import ImageFetchStrategy
   from core.session_pool import DomainSessionPool
   from utils.image_url import detect_image_extension

   MAX_IMAGE_SIZE = 5 * 1024 * 1024  # 5MB
   IMAGE_FETCH_CONCURRENCY = 5

   class WebImageFetcher(ImageFetchStrategy):
       def __init__(self, pool: DomainSessionPool, chapter_index: int) -> None:
           self.pool = pool
           self.chapter_index = chapter_index

       async def fetch(self, ref: ImageRef) -> bytes | None:
           url = ref.original_url
           # HEAD check size first
           # (or use Content-Length from GET, simpler)
           try:
               resp = await self.pool.fetch(url, method="GET", timeout=30)
               if resp.status_code != 200:
                   return None
               if len(resp.content) > MAX_IMAGE_SIZE:
                   return None
               return resp.content
           except Exception:
               return None

       async def fetch_batch(self, refs: list[ImageRef], output_dir: str) -> list[ImageRef]:
           import os
           os.makedirs(os.path.join(output_dir, "images"), exist_ok=True)
           sem = asyncio.Semaphore(IMAGE_FETCH_CONCURRENCY)

           async def _one(idx: int, ref: ImageRef) -> None:
               async with sem:
                   data = await self.fetch(ref)
                   if data:
                       # Detect extension
                       ext = detect_image_extension(None, data[:16])
                       filename = f"ch_{self.chapter_index:04d}_{idx}{ext}"
                       path = os.path.join(output_dir, "images", filename)
                       # Atomic write
                       tmp = path + ".tmp"
                       with open(tmp, "wb") as f:
                           f.write(data)
                       os.replace(tmp, path)
                       ref.local_path = f"images/{filename}"
                   else:
                       ref.local_path = None

           await asyncio.gather(*(_one(i, r) for i, r in enumerate(refs)))
           return refs

Verify:
- python -c "from core.image_pipeline.web_fetcher import WebImageFetcher; print('OK')"
- Manual test inline (1 URL ảnh thật từ RR):
   import asyncio
   from core.session_pool import DomainSessionPool
   from core.image_pipeline.web_fetcher import WebImageFetcher
   from pipeline.base import ImageRef

   async def test():
       pool = DomainSessionPool()
       fetcher = WebImageFetcher(pool, chapter_index=1)
       ref = ImageRef(original_url="<URL ảnh thật>", local_path=None,
                      alt_text="test", position_marker="IMG_0", source_type="web")
       result = await fetcher.fetch_batch([ref], "test_out")
       print(result[0].local_path)
   asyncio.run(test())
   → File ảnh xuất hiện ở test_out/images/

Commit: feat(image): add ImageFetchStrategy ABC + WebImageFetcher
```

✅ **Kiểm tra:** 1 ảnh thật download được, save đúng path naming.

---

### STEP 2.3 — `MarkdownFormatter` handle `<img>` (🛑 STOP)

🎯 **Mục tiêu:** `<img>` trong content → `![alt](IMG_PLACEHOLDER_N)` đúng vị trí, return `(text, images_list)` tuple.

🗣️ **Bạn nói với Claude Code:**

```
Task: MarkdownFormatter extend cho <img>.

🛑 STOP RULE: ĐỌC CLAUDE.md §10 — đổi return type _format_element từ str → tuple[str, list].
   Break MỌI caller. Plan + tôi confirm trước.

Bước trước:
1. grep -rn "_format_element\|MarkdownFormatter\|format()" --include="*.py" core/ pipeline/
   → List MỌI caller, paste cho tôi xem
2. Plan migration tất cả caller — update để consume tuple
3. HỎI tôi confirm

⚠️ ĐỌC core/formatter.py kỹ trước khi đổi.

Sau khi tôi confirm:

MODIFY: core/formatter.py
- Thêm method extract_images(el, base_url) -> list[ImageRef]
- _format_element return (text: str, images: list[ImageRef]) thay vì chỉ str
- Image trong content → emit `![alt](IMG_PLACEHOLDER_{idx})` ở vị trí đúng
- Position marker tăng dần khi gặp <img>

Update tất cả caller:
- pipeline/extractor.py — SelectorExtractBlock, DensityHeuristicBlock, etc.
- Bất cứ đâu gọi MarkdownFormatter.format() — update để unpack tuple

Verify:
1. Test text-only chapter (FFN không có ảnh):
   - python main.py links.txt với URL FFN test → output Markdown
   - BASELINE DIFF vs phase1_ffn → ZERO diff (text-only nên images list rỗng)
2. Test chapter có ảnh (Royal Road có illustration):
   - Output Markdown chứa `![alt](IMG_PLACEHOLDER_0)` đúng vị trí

🛑 EXIT RAMP: 3 attempt baseline diff fail (text-only) → rollback, reassess.

Commit: refactor(formatter): handle inline img, return (text, images) tuple

Báo cáo:
- Danh sách caller đã update
- Baseline diff text-only chapter
- Sample output có image (manual inspect)
```

🙋 **Bạn cần làm tay:** Review plan caller migration kỹ. Đây là chỗ rất dễ break silent.

✅ **Kiểm tra:** Text-only chapter baseline diff zero. Chapter có ảnh có placeholder đúng vị trí.

---

### STEP 2.4 — `PipelineContext` extension cho images

🎯 **Mục tiêu:** `PipelineContext.image_refs: list[ImageRef]` default empty, populate ở Extract block.

🗣️ **Bạn nói với Claude Code:**

```
Task: Thêm image_refs vào PipelineContext.

MODIFY: pipeline/base.py
- PipelineContext thêm field:
   image_refs: list[ImageRef] = field(default_factory=list)
- Thêm run_config field:
   run_config: RunConfig | None = None

MODIFY: pipeline/extractor.py
- Sau khi format content, append ctx.image_refs.extend(images_from_formatter)

Verify:
- Smoke test text-only → image_refs rỗng, output không đổi
- Smoke test có ảnh → image_refs có N items (log để debug)

Commit: feat(pipeline): add image_refs + run_config to PipelineContext
```

✅ **Kiểm tra:** `image_refs` populate đúng số ảnh trong chapter test.

---

### STEP 2.5 — Pipeline image stage (mode-aware)

🎯 **Mục tiêu:** Sau ExtractChain, image stage chạy theo `run_config.output_mode`:
- obsidian: download local, rewrite placeholder thành relative path
- translate: replace placeholder thành `[IMAGE: alt]`
- raw: strip placeholder

🗣️ **Bạn nói với Claude Code:**

```
Task: Pipeline image stage.

⚠️ DECISION POINT: Logic này thuộc PipelineRunner hay core/scraper.py orchestrator?
   Tôi đề nghị: core/scraper.py (cao hơn pipeline, biết writer instance).
   HỎI tôi confirm trước khi code.

⚠️ FAILURE UX: BLUEPRINT specs nói "log + continue", nhưng cụ thể:
   - Image fail (local_path = None) trong obsidian mode → KEEP placeholder hoặc?
   - Khuyến nghị: replace placeholder thành `![alt](original_url)` — external link fallback
     User click vẫn được, không broken link.
   - ObsidianWriter đã có "failed_images" trong frontmatter (đã add P1.4).

Sau khi tôi confirm placement:

MODIFY: core/scraper.py (hoặc pipeline/executor.py nếu pick option B)
- Sau khi PipelineRunner.run() return ctx (có image_refs):
  if not ctx.image_refs:
      pass  # text-only chapter
  elif ctx.run_config.download_images:
      # Obsidian mode
      strategy = WebImageFetcher(pool, ctx.chapter_index)
      await strategy.fetch_batch(ctx.image_refs, ctx.output_dir)
      # Rewrite placeholders in ctx.content
      for ref in ctx.image_refs:
          if ref.local_path:
              new = f"![{ref.alt_text}]({ref.local_path})"
          else:
              # Failure fallback: external URL link
              new = f"![{ref.alt_text}]({ref.original_url})"
          ctx.content = ctx.content.replace(
              f"![{ref.alt_text}]({ref.position_marker})", new, 1
          )
  elif ctx.run_config.image_placeholder:
      # Translate mode
      for ref in ctx.image_refs:
          ctx.content = ctx.content.replace(
              f"![{ref.alt_text}]({ref.position_marker})",
              f"[IMAGE: {ref.alt_text}]", 1
          )
  else:
      # Raw mode — strip image entirely
      import re
      ctx.content = re.sub(r'!\[[^\]]*\]\(IMG_PLACEHOLDER_\d+\)', '', ctx.content)

Verify:
1. Test 1 chapter Royal Road có illustration:
   - obsidian mode: output Markdown có ![](images/ch_NNNN_0.jpg) + file ảnh tồn tại
   - translate mode: output có [IMAGE: alt text]
   - raw mode: không có trace image
2. Test failure: cố tình block 1 URL ảnh (sửa local hosts) → mode obsidian fallback URL link
3. Open file Markdown trong Obsidian → ảnh render

Commit: feat(pipeline): add mode-aware image stage with failure fallback

Báo cáo: 3 output Markdown (3 mode) cho cùng 1 chapter có ảnh.
```

✅ **Kiểm tra:** 3 mode handling ảnh khác nhau, đúng spec.

---

### STEP 2.6 — AI#7 prompt update: detect image policy (🛑 STOP prompt >30%)

🎯 **Mục tiêu:** AI#7 (ads & watermark) thêm field detect site có inline image đáng tải không.

> **Lưu ý cá nhân:** Tôi recommend tạo AI#9 riêng cho image policy thay vì extend AI#7 (mixing concerns). Nếu bạn agree, bảo Claude Code làm AI#9 mới. Nếu giữ extend AI#7, follow plan dưới.

🗣️ **Bạn nói với Claude Code:**

```
Task: AI#7 prompt extend (HOẶC tạo AI#9 mới — hỏi tôi).

🛑 STOP RULE: ĐỌC CLAUDE.md §10 — prompt change > 30% nội dung.
   Plan + tôi confirm trước.

Option A (Plan gốc): Extend AI#7
- ai/prompts.py — learning_7_ads_deepscan thêm task:
   "Trang này có ảnh minh họa trong chapter không? Nếu có, ảnh nằm trong selector nào?"
- Response field mới: has_inline_images: bool, image_selector: str | null

Option B (Tôi recommend): Tạo AI#9 riêng
- Đỡ mixing concerns. Ads là post-clean, image là pipeline structural.
- Tăng 1 AI call (~$0.0025) — không đáng lo.

HỎI tôi chọn Option A hay B trước khi code.

Sau khi tôi confirm:

MODIFY:
- ai/prompts.py (option A) HOẶC thêm prompt mới (option B)
- ai/agents.py — parse field mới
- learning/phase_ai.py — consume field
- utils/types.py — SiteProfile.download_images: bool, image_selector: str | None
- learning/phase.py — _build_final_profile populate field

Verify:
- Re-learn 1 site biết có ảnh (RR illustration novel):
  python main.py --bulk-relearn --pattern "royalroad" --apply
  python main.py links.txt với URL RR
  → profile mới có download_images=True, image_selector=<X>
- Re-learn 1 site không có ảnh (FFN):
  → profile mới có download_images=False (hoặc None)

Commit: feat(learning): AI#7 (or AI#9) detect image policy
```

🙋 **Bạn cần làm tay:** Pick Option A hay B. Tôi nghiêng B.

✅ **Kiểm tra:** Profile mới có field image-related.

---

### STEP 2.7 — Smoke test Phase 2 + Retro

🎯 **Mục tiêu:** Royal Road novel có art, scrape 10 chapter, ảnh + Markdown đúng trong Obsidian.

🗣️ **Bạn nói với Claude Code:**

```
Phase 2 retrospective:

1. Pick 1 RR novel có illustration (Beware of Chicken hoặc tương tự)
2. Re-learn site:
   python main.py --bulk-relearn --pattern "royalroad" --apply
3. Scrape 10 chapter (3 mode):
   python main.py links.txt --output-mode obsidian --output-dir out/obsidian
   python main.py links.txt --output-mode translate --output-dir out/translate
   python main.py links.txt --output-mode raw --output-dir out/raw
4. Verify:
   - out/obsidian/{story}/images/ có files
   - out/obsidian/{story}/*.md link đúng images/...
   - Mở 1 chapter trong Obsidian → ảnh hiển thị
   - Translate output có [IMAGE: ...] placeholder
   - Raw output không có image trace

5. docs/PHASE_2_RETRO.md
6. Update CLAUDE.md/ROADMAP.md mark Phase 2 done
7. Tag: git tag v0.x-phase2

Commit: chore: phase 2 retro + image support complete
```

✅ **Kiểm tra:** Obsidian render ảnh OK. 3 mode khác nhau.

---

## 📚 PHASE 3 — EPUB Adapter (1.5-2 tuần)

> **Mục tiêu cuối Phase 3:** `python main.py novel.epub` → output 50 chapter Markdown sạch + embedded image extracted.

### STEP 3.1 — Add `ebooklib` dependency

🎯 **Mục tiêu:** ebooklib cài + importable.

🗣️ **Bạn nói với Claude Code:**

```
Task: Add ebooklib.

⚠️ ĐỌC CLAUDE.md §4 (FORBIDDEN tech) — ebooklib không trong forbidden list, OK.

MODIFY:
- requirements.txt (hoặc pyproject.toml) — add: ebooklib>=0.18

Bước:
1. pip install ebooklib (hoặc uv add ebooklib)
2. python -c "import ebooklib; print(ebooklib.__version__)"

Commit: chore(deps): add ebooklib for EPUB parsing
```

✅ **Kiểm tra:** Import OK.

---

### STEP 3.2 — `ingest/router.py` input type detection

🎯 **Mục tiêu:** `detect_input_type(path)` → `"web" | "epub" | "txt"`.

🗣️ **Bạn nói với Claude Code:**

```
Task: Input router.

ADD:
1. ingest/__init__.py (empty)
2. ingest/router.py (~80 dòng):

   from __future__ import annotations
   from pathlib import Path
   from typing import Literal
   import re

   URL_PATTERN = re.compile(r"^https?://", re.IGNORECASE)

   def detect_input_type(path_or_file: str) -> Literal["web", "epub", "txt"]:
       p = Path(path_or_file)
       suffix = p.suffix.lower()
       if suffix == ".epub":
           return "epub"
       if suffix == ".txt":
           # Distinguish: line đầu match URL → web (legacy links.txt)
           try:
               with open(p, "r", encoding="utf-8") as f:
                   first_line = f.readline().strip()
               if URL_PATTERN.match(first_line):
                   return "web"
               # All non-comment non-empty lines must look like URLs for "web"
               return "txt"
           except Exception:
               return "txt"
       # Default fallback
       return "web"

Verify inline:
   from ingest.router import detect_input_type
   assert detect_input_type("links.txt") == "web"
   assert detect_input_type("novel.epub") == "epub"
   # Create test files
   ...

Commit: feat(ingest): add router for input type detection
```

✅ **Kiểm tra:** 3 case test pass.

---

### STEP 3.3 — `ingest/web.py` wrap existing scraper

🎯 **Mục tiêu:** Thin wrapper exposing existing scraper logic qua adapter interface.

🗣️ **Bạn nói với Claude Code:**

```
Task: ingest/web.py wrapper.

⚠️ DECISION POINT: Symbolic re-export hay refactor caller? HỎI tôi.
   Recommend: symbolic re-export Phase 3, refactor caller Phase 6.

Sau khi tôi confirm:

ADD: ingest/web.py (~80 dòng)
- Thin wrapper re-export functions từ core/scraper.py
- Hoặc nếu refactor: pass-through call

Verify: web scraping vẫn work y như cũ.

Commit: feat(ingest): add web adapter wrapper
```

✅ **Kiểm tra:** Web flow không break.

---

### STEP 3.4 — `ingest/epub.py` EPUB parser

🎯 **Mục tiêu:** EPUB → iterator yield `RawDocument` per chapter.

🗣️ **Bạn nói với Claude Code:**

```
Task: EPUB parser.

⚠️ ĐỌC BLUEPRINT.md §6 (Route: EPUB → Translation) + Decision #22 (Dublin Core naming).
⚠️ EPUB có nhiều variant — test với ít nhất 2 EPUB khác structure.

ADD: ingest/epub.py (~200 dòng):

   from __future__ import annotations
   from typing import AsyncIterator
   from pathlib import Path
   from ebooklib import epub, ITEM_DOCUMENT
   from bs4 import BeautifulSoup
   from dataclasses import dataclass

   @dataclass
   class RawDocument:
       chapter_index: int
       html: str
       source_url: str | None = None
       source_path: str | None = None
       metadata: dict = None

   # Filenames thường là TOC/cover/copyright — skip
   SKIP_PATTERNS = ("toc", "cover", "copyright", "title", "nav", "front")

   async def ingest_epub(path: str) -> AsyncIterator[RawDocument]:
       book = epub.read_epub(path)
       
       # Naming via Dublin Core
       title_meta = book.get_metadata("DC", "title")
       story_name = title_meta[0][0] if title_meta else None  # AI fallback if None
       
       idx = 1
       for item in book.spine:
           item_id = item[0] if isinstance(item, tuple) else item
           ebook_item = book.get_item_with_id(item_id)
           if ebook_item is None or ebook_item.get_type() != ITEM_DOCUMENT:
               continue
           filename = (ebook_item.file_name or "").lower()
           if any(p in filename for p in SKIP_PATTERNS):
               continue
           html = ebook_item.get_content().decode("utf-8", errors="replace")
           yield RawDocument(
               chapter_index=idx,
               html=html,
               source_path=str(Path(path).resolve()),
               metadata={"story_name": story_name} if story_name else {},
           )
           idx += 1

Verify:
- Pick 1 EPUB test (Project Gutenberg, free)
- Inline test:
   import asyncio
   from ingest.epub import ingest_epub
   async def t():
       async for doc in ingest_epub("test.epub"):
           print(doc.chapter_index, len(doc.html))
   asyncio.run(t())
   → 50+ chapters iterate, không có TOC/cover

Commit: feat(ingest): add EPUB adapter with ebooklib
```

🙋 **Bạn cần làm tay:** Download 1 EPUB Project Gutenberg để test.

✅ **Kiểm tra:** 50+ chapter iterate, skip TOC/cover.

---

### STEP 3.5 — `EpubImageExtractor` strategy

🎯 **Mục tiêu:** Extract image binary từ EPUB zip, cùng interface với `WebImageFetcher`.

🗣️ **Bạn nói với Claude Code:**

```
Task: EpubImageExtractor.

ADD: core/image_pipeline/epub_extractor.py (~100 dòng):

   from __future__ import annotations
   import os
   from ebooklib import epub
   from pipeline.base import ImageRef
   from core.image_pipeline.base import ImageFetchStrategy
   from utils.image_url import detect_image_extension

   class EpubImageExtractor(ImageFetchStrategy):
       def __init__(self, book: epub.EpubBook, chapter_index: int) -> None:
           self.book = book
           self.chapter_index = chapter_index

       async def fetch(self, ref: ImageRef) -> bytes | None:
           # ref.original_url is href trong EPUB
           item = self.book.get_item_with_href(ref.original_url)
           if item is None:
               # Try absolute path variants
               for href_variant in [
                   ref.original_url.lstrip("/"),
                   "OEBPS/" + ref.original_url,
                   "OEBPS/" + ref.original_url.lstrip("/"),
               ]:
                   item = self.book.get_item_with_href(href_variant)
                   if item:
                       break
           if item is None:
               return None
           return item.get_content()

       async def fetch_batch(self, refs: list[ImageRef], output_dir: str) -> list[ImageRef]:
           os.makedirs(os.path.join(output_dir, "images"), exist_ok=True)
           for idx, ref in enumerate(refs):
               try:
                   data = await self.fetch(ref)
                   if data:
                       ext = detect_image_extension(None, data[:16])
                       filename = f"ch_{self.chapter_index:04d}_{idx}{ext}"
                       path = os.path.join(output_dir, "images", filename)
                       tmp = path + ".tmp"
                       with open(tmp, "wb") as f:
                           f.write(data)
                       os.replace(tmp, path)
                       ref.local_path = f"images/{filename}"
                   else:
                       ref.local_path = None
               except Exception as e:
                   import logging
                   logging.getLogger(__name__).warning(
                       "EPUB image extract failed: %s — %s", ref.original_url, e
                   )
                   ref.local_path = None
           return refs

Verify:
- Pick 1 EPUB có embedded image (light novel illustrated)
- Inline test: extract 1 image, save local, verify file size > 0

Commit: feat(image): add EpubImageExtractor strategy
```

✅ **Kiểm tra:** EPUB image extract work.

---

### STEP 3.6 — `core/orchestrator.py` route theo input type (🛑 STOP)

🎯 **Mục tiêu:** main.py route theo input type → web/EPUB adapter → pipeline → writer.

🗣️ **Bạn nói với Claude Code:**

```
Task: Orchestrator route input type.

🛑 STOP RULE: file mới `core/orchestrator.py` chạm vào main.py flow.
   Plan + tôi confirm trước.

⚠️ DECISION: tạo file mới HAY edit core/scraper.py?
   Recommend: tạo mới. core/scraper.py giữ vai trò "web-specific orchestrator".

Plan template — paste cho tôi xem.

Sau khi tôi confirm:

ADD: core/orchestrator.py (~150 dòng)
- class Orchestrator
- async def run(input_path, run_config):
    input_type = detect_input_type(input_path)
    if input_type == "web":
        # Existing flow: load links.txt, loop URLs
        await run_web_flow(input_path, run_config)
    elif input_type == "epub":
        await run_epub_flow(input_path, run_config)
    elif input_type == "txt":
        raise NotImplementedError("TXT adapter — Phase 5")

- run_epub_flow:
    book = epub.read_epub(input_path)
    writer = create_writer(run_config)
    async for doc in ingest_epub(input_path):
        # Build ctx without web fetch
        ctx = make_context(url=None, profile={})
        ctx.html = doc.html
        ctx.soup = BeautifulSoup(doc.html, "lxml")
        ctx.run_config = run_config
        # Run pipeline blocks: Filter → Extract → Title → Validate → Clean
        # Skip Navigate (no next URL)
        chapter = await runner.run_partial(ctx, skip_nav=True)
        chapter.index = doc.chapter_index
        chapter.source_path = doc.source_path
        # Image stage with EpubImageExtractor
        if chapter.images and run_config.download_images:
            extractor = EpubImageExtractor(book, chapter.index)
            await extractor.fetch_batch(chapter.images, run_config.output_dir)
            # Rewrite placeholders (same as web)
        await writer.write(chapter)

MODIFY: main.py
- Replace direct call to core.scraper với Orchestrator.run()

Verify:
1. Web flow vẫn work (regression):
   python main.py links.txt → đầy đủ 3 site, baseline diff zero
2. EPUB flow:
   python main.py novel.epub --output-mode obsidian
   → output/{story}/*.md (50 chapter)
   → output/{story}/images/* nếu có
3. EPUB clean (Project Gutenberg): không bị strip nhầm
4. EPUB pirate (có watermark): output sạch sau cleaning passes

Commit: feat(core): add orchestrator for input-type routing
```

🙋 **Bạn cần làm tay:** Review plan kỹ. Đây là step bridging giữa input adapter và pipeline core.

✅ **Kiểm tra:** Web + EPUB flow đều work, baseline diff web zero.

---

### STEP 3.7 — AdsFilter cho EPUB

🎯 **Mục tiêu:** EPUB pirate có watermark → cross-chapter frequency analysis vẫn apply (domain key = filename slug).

🗣️ **Bạn nói với Claude Code:**

```
Task: AdsFilter support EPUB domain key.

MODIFY:
- core/orchestrator.py run_epub_flow:
   domain_key = f"epub:{slugify(Path(input_path).stem)}"
   # Pass domain_key cho AdsFilter instance giống web flow

Verify:
- EPUB pirate test (nếu có): watermark "Read more at xyz.com" detect + strip cross-chapter
- data/ads_keywords.json có entry "epub:my_novel_slug"

Commit: feat(ads): support EPUB watermark filtering
```

✅ **Kiểm tra:** EPUB pirate → output sạch.

---

### STEP 3.8 — Smoke test Phase 3 + Retro

🎯 **Mục tiêu:** Phase 3 done, EPUB → Obsidian work.

🗣️ **Bạn nói với Claude Code:**

```
Phase 3 retrospective:

1. Pick 2 EPUB test:
   - 1 EPUB pirate có watermark
   - 1 EPUB clean (Project Gutenberg)
2. Scrape cả 2 × 3 mode (6 outputs)
3. Verify:
   - Pirate: output clean, image embedded preserved
   - Clean: không over-strip
4. docs/PHASE_3_RETRO.md
5. Update governance docs
6. Tag: git tag v0.x-phase3

Commit: chore: phase 3 retro + epub adapter complete
```

✅ **Kiểm tra:** Phase 3 done.

---

## ✍️ PHASE 4 — TranslationWriter + RawWriter (3 ngày)

> **Mục tiêu cuối Phase 4:** 3 output mode hoàn thiện. Translation paste vào Gemini dịch ra Việt sạch.

### STEP 4.1 — `output/translation.py`

🎯 **Mục tiêu:** Plain text, paragraph-per-line, image `[IMAGE: alt]` placeholder.

🗣️ **Bạn nói với Claude Code:**

```
Task: TranslationWriter.

⚠️ DECISION POINT: chunking threshold? Default 30000 chars. HỎI tôi.

ADD: output/translation.py (~120 dòng)
- Strip Markdown formatting (heading → plain, bold/italic → text, link → text only)
- Image: replace ![alt](url) → [IMAGE: alt]
- Paragraph: 1 paragraph 1 dòng, double newline giữa
- Filename: 0042.txt (no chapter title slug)
- No frontmatter
- Optional chunking: nếu len > CHUNK_THRESHOLD → 0042_part1.txt, 0042_part2.txt

Verify:
- Output paste vào Gemini → dịch ra Việt sạch
- Không có **bold** noise
- Image placeholder rõ ràng

Commit: feat(output): add TranslationWriter
```

✅ **Kiểm tra:** Output đẹp khi paste vào Gemini.

---

### STEP 4.2 — `output/raw.py`

🎯 **Mục tiêu:** Text only, image stripped.

🗣️ **Bạn nói với Claude Code:**

```
Task: RawWriter.

ADD: output/raw.py (~60 dòng)
- Plain text
- Image stripped entirely (không placeholder)
- Paragraph spacing giữ y nguyên
- Filename: 0042.txt
- No frontmatter

Verify:
- Output đọc được trên Notepad
- File size nhỏ nhất trong 3 mode

Commit: feat(output): add RawWriter
```

✅ **Kiểm tra:** Output tối giản.

---

### STEP 4.3 — Smoke test 3 mode × 2 source

🎯 **Mục tiêu:** Matrix Input × Output đều work.

🗣️ **Bạn nói với Claude Code:**

```
Phase 4 smoke test + retro:

1. Cùng 1 URL × 3 mode → 3 output dir
2. Cùng 1 EPUB × 3 mode → 3 output dir
3. Verify matrix BLUEPRINT.md §4 (6 combinations)
4. Translation output paste Gemini → ra Việt
5. docs/PHASE_4_RETRO.md
6. Tag: git tag v0.x-phase4

Commit: chore: phase 4 retro + writers complete
```

✅ **Kiểm tra:** 6 outputs đều correct.

---

## 📜 PHASE 5 — TXT Adapter (2 tuần, EXIT RAMP)

> **⚠️ HIGHEST RISK PHASE.** Có exit ramp ở STEP 5.5: nếu < 2/3 case pass → STOP, defer Phase 5 v1.1, ship v1.0 without TXT. Quyết định này cứu được 1 tuần debug.
>
> **Scope v1.0:** Vietnamese + English only. CJK defer v1.1.
>
> **Lưu ý cá nhân:** Tôi đã recommend defer Phase 5 hoàn toàn sang v1.1. Nếu bạn agree, skip phase này và đi thẳng Phase 6. Nếu vẫn muốn làm, follow plan dưới với mindset "exit ramp là realistic outcome".

### STEP 5.1 — TXT case database design

🎯 **Mục tiêu:** `data/txt_cases.json` với 4 case (VN + EN, không có "numeric_section" greedy).

🗣️ **Bạn nói với Claude Code:**

```
Task: TXT case database.

⚠️ Tôi đề nghị BỎ "numeric_section" case khỏi initial DB — quá greedy, dễ false positive.
   Nếu user agree → chỉ 4 case (VN colon, VN number-only, EN colon, EN number-only).

ADD:
1. data/txt_cases.json:
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
       }
     ]
   }
2. utils/types.py — TxtCase TypedDict

Commit: feat(data): add TXT case database (VN+EN)
```

✅ **Kiểm tra:** JSON valid, 4 case load được.

---

### STEP 5.2 — TXT boundary detection

🎯 **Mục tiêu:** `ingest/txt.py` detect chapter boundary qua regex + AI fallback.

🗣️ **Bạn nói với Claude Code:**

```
Task: TXT chapter detection.

ADD: ingest/txt.py (~300 dòng)
- Read file UTF-8 only (fail-loud nếu non-UTF-8)
- Sample first 100 dòng → match từng case
- Best match (most lines matching) → return case
- No match → AI fallback: gửi 50 dòng + ask pattern
- AI verify với 3 chapter random
- AI verify pass → add vào txt_cases.json
- Apply pattern → split file thành list[(idx, title, body)]

Verify:
- 3 TXT pattern khác nhau → detect đúng, split đúng
- 1 TXT không pattern → error message rõ ràng (KHÔNG silent fail)
- Non-UTF-8 file → fail-loud với message

Commit: feat(ingest): TXT chapter boundary detection
```

✅ **Kiểm tra:** 3 case test pass.

---

### STEP 5.3 — TXT → RawDocument

🎯 **Mục tiêu:** Wrap each chunk as HTML.

🗣️ **Bạn nói với Claude Code:**

```
Task: TXT → RawDocument conversion.

MODIFY: ingest/txt.py
- Each chunk → wrap as <article><p>...</p>...</article>
- Yield RawDocument(chapter_index, html, source_path)

Verify:
- Pipeline ăn được TXT chunk như HTML
- SelectorExtract skip, DensityHeuristic accept

Commit: feat(ingest): TXT to RawDocument
```

✅ **Kiểm tra:** TXT pipe through pipeline.

---

### STEP 5.4 — Orchestrator route TXT

🎯 **Mục tiêu:** main.py novel.txt → output Obsidian.

🗣️ **Bạn nói với Claude Code:**

```
Task: Orchestrator TXT branch.

MODIFY: core/orchestrator.py
- run_txt_flow: tương tự run_epub_flow
- TXT không có Navigation chain
- TXT không có Learning phase
- TXT có thể có AdsFilter (pirate watermark)
- TXT không có image — image stage no-op

Commit: feat(core): orchestrator TXT routing
```

✅ **Kiểm tra:** TXT → Obsidian work.

---

### STEP 5.5 — Smoke test TXT (🛑 DECISION POINT — EXIT RAMP)

🎯 **Mục tiêu:** Test 3 TXT file đa dạng, ≥ 2/3 case work → continue. < 2/3 → STOP + defer.

🗣️ **Bạn nói với Claude Code:**

```
Task: Smoke test TXT — EXIT RAMP DECISION.

1. Pick 3 TXT đa dạng:
   - VN novel ("Chương N" pattern)
   - EN novel Project Gutenberg ("Chapter N" pattern)
   - VN novel pattern lạ ("Phần N" hoặc "Quyển I Chương X")
2. Run 3, verify output

🛑 EXIT RAMP CHECK:
- Nếu >= 2/3 case work → continue Phase 6
- Nếu < 2/3 work → STOP Phase 5
  - Mark "TXT defer v1.1" trong CLAUDE.md §3 DEFERRED
  - Update ROADMAP.md mark Phase 5 EXITED
  - Skip thẳng Phase 6
  - Save 1.5 tuần debug

Báo cáo:
- 3 case kết quả
- Decision: continue hay exit

Commit (pass): feat(ingest): TXT adapter complete (Phase 5 done)
Commit (exit): docs: defer TXT adapter to v1.1 (Phase 5 exit ramp triggered)
```

🙋 **Bạn cần làm tay:**

Đây là decision point thật. Đừng tự dụ "thêm 2 ngày là pass". Nếu < 2/3 pass, EXIT là quyết định đúng.

✅ **Kiểm tra:** Decision rõ ràng, hành động theo decision.

---

## 🧹 PHASE 6 — Final Cleanup + Polish (3-5 ngày)

> **Mục tiêu cuối Phase 6:** Codebase audit, Batch C executed (merge small files, remove boilerplate), docs polish, v1.0 tagged.

### STEP 6.1 — Audit codebase post-Phase-5

🎯 **Mục tiêu:** List candidate cho merge/delete.

🗣️ **Bạn nói với Claude Code:**

```
Task: Audit codebase.

Bước:
1. wc -l **/*.py — count current LOC
2. Identify files < 30 dòng AND chỉ 1 caller AND không complex logic → merge candidate
3. Identify unused imports (autoflake --check)
4. Identify duplicate logic across ingest/ adapters
5. Output: docs/AUDIT_PHASE6.md với list candidate + rationale

Commit: docs: phase 6 codebase audit
```

✅ **Kiểm tra:** Audit list có item cụ thể, không vague.

---

### STEP 6.2 — Execute Batch C

🎯 **Mục tiêu:** Merge small files, remove boilerplate, total LOC giảm thêm 5-10%.

🗣️ **Bạn nói với Claude Code:**

```
Task: Batch C cleanup.

⚠️ Mỗi merge cần baseline diff zero.
⚠️ STOP rule cho shared logic.

Theo list ở docs/AUDIT_PHASE6.md, execute từng item:
- Plan merge
- Apply
- Baseline diff
- Commit incremental (`refactor: merge X into Y`)

Verify:
- Total LOC giảm 5-10%
- All smoke test pass
- Baseline diff zero (hoặc predictable frontmatter-only)

Commit: refactor: Batch C miscellaneous cleanup
```

✅ **Kiểm tra:** LOC giảm đáng kể, không regress.

---

### STEP 6.3 — Final docs polish

🎯 **Mục tiêu:** README full, troubleshooting đủ.

🗣️ **Bạn nói với Claude Code:**

```
Task: Final docs.

MODIFY:
- README.md — full feature list, troubleshooting, FAQ
- CLAUDE.md §17 Decision Log update final state
- BLUEPRINT.md mark v1.0 done
- ROADMAP.md mark all phase done
- docs/V1_1_BACKLOG.md consolidate defer features với rationale

ADD:
- docs/TROUBLESHOOTING.md (nếu chưa có) — 10 common issues + fix
- CHANGELOG.md v1.0.0 entry

Commit: docs: finalize v1.0 documentation
```

✅ **Kiểm tra:** README clean clone follow được trong 5 phút.

---

### STEP 6.4 — v1.0 tag + project retrospective

🎯 **Mục tiêu:** Tag v1.0.0, retrospective documented.

🗣️ **Bạn nói với Claude Code:**

```
Task: v1.0 ship + retrospective.

1. Full smoke test:
   - 3 site web × 3 mode = 9 outputs
   - 1 EPUB × 3 mode = 3 outputs
   - 1 TXT (nếu Phase 5 done) × 3 mode = 3 outputs
   - Total: 12-15 output, all clean
2. Final baseline snapshot:
   python tools/snapshot_baseline.py --label v1.0_final ...
3. docs/PROJECT_RETROSPECTIVE.md:
   - Plan vs Actual (estimate 7-9 tuần vs thực tế)
   - Cái gì tốt
   - Cái gì khó
   - Tech debt cho v1.1
   - Top 5 priorities v1.1
4. Update docs/V1_1_BACKLOG.md với priority order

5. Bump version trong main.py / config.py (nếu có version constant)

6. Tag: git tag v1.0.0 -m "v1.0.0 — universal novel normalizer"

Commit: chore: release v1.0.0
```

🙋 **Bạn cần làm tay:**

- Dùng tool thật 1-2 tuần để feel app
- Đừng tag v1.0 trước khi thấy stable trong daily use

✅ **Kiểm tra:** Tag v1.0.0 ở HEAD main.

---

## 📊 Quy tắc vàng cho Vibe Coder

### Khi nào commit?

**Sau MỖI step xong + smoke test pass.** Nếu Claude Code không tự commit, bảo nó. Mỗi commit ≤ 200 dòng diff lý tưởng. Batch lớn (Batch A xóa 450 dòng) OK nếu pure deletion.

### Khi nào revert?

```bash
git log --oneline
git revert HEAD          # an toàn
git reset --hard HEAD~1  # nguy hiểm, confirm
```

### Cách yêu cầu Claude Code fix bug

KHÔNG nói: "Code lỗi, fix đi"

NÓI:

```
Khi tôi chạy: <lệnh chính xác>
Tôi gặp lỗi: <paste full traceback>

File liên quan: pipeline/...
Expect: <kết quả mong đợi>
Actual: <kết quả thực tế>

Debug theo CLAUDE.md §8.4 (Root cause > Firefighting) và §9 (VERIFY).
```

### Khi Claude Code suggest cái lạ

- "Cài thêm package X" → STOP, check CLAUDE.md §4 FORBIDDEN. Không trong forbidden + không trong tech stack → hỏi tại sao.
- "Refactor module Y" → STOP, hỏi tại sao trước. Scope creep nguy.
- "Xóa file Z" → CONFIRM 2 lần, có baseline + tag chưa.
- "Sửa shared logic" (`pipeline/base.py`, `pipeline/executor.py`, `core/scraper.py`, `core/formatter.py`) → STOP, đọc CLAUDE.md §10.
- "Skip baseline diff lần này thôi" → KHÔNG. Đó là regression guard duy nhất.
- "Thêm regex strip pass vào content_cleaner" → STOP, đó là biện pháp chống cháy (CLAUDE.md §18 #1). Tìm root cause selector.

### Quản lý expectation timeline

| Phase | Plan (ROADMAP.md) | Realistic | Cảm xúc |
|---|---|---|---|
| Phase 0 | 3-4 ngày | 5-7 ngày | "Xóa code thật mệt, sao lâu vậy" |
| Phase 1 | 1 tuần | 1.5-2 tuần | "Refactor lớn, P1.5 stress" |
| Phase 2 | 1-2 tuần | 2-3 tuần | "Ảnh hiện trong Obsidian. WOW" |
| Phase 3 | 1-1.5 tuần | 1.5-2 tuần | "EPUB work! Nhưng debug variant tốn time" |
| Phase 4 | 3 ngày | 3-5 ngày | "Easy step, refresh tinh thần" |
| Phase 5 | 2 tuần | 2-3 tuần (HOẶC exit ramp 3 ngày) | "Cảm xúc thật phụ thuộc exit ramp" |
| Phase 6 | 3-5 ngày | 1 tuần | "Polish + ship" |

**Total realistic:** 10-14 tuần solo dev part-time. Nếu defer Phase 5 → 8-11 tuần.

---

## 🆘 Khi nào hỏi Claude (chat)

**Hỏi chat:**

- "Step này có nhất thiết không?"
- "Tại sao Path A mà không Path B?"
- "Anh thấy dự án có vấn đề gì không?"
- "Tôi mất hứng, có nên pause không?"
- "Phase 5 exit ramp triggered — có nên revisit ở v1.1 không hay drop hẳn?"
- Bí kỹ thuật mà Code không hiểu yêu cầu

**Đừng hỏi chat:**

- "Viết code cho tôi" → việc Code
- "Tại sao file này lỗi?" → Code thấy file, chat không

---

## ✅ Definition of Done (project-level v1.0)

v1.0 "xong" khi:

- [ ] Phase 0-4 + Phase 6 done (Phase 5 done HOẶC exit ramp triggered)
- [ ] Codebase giảm ≥ 780 dòng vs baseline (Batch A + B + C)
- [ ] 3 output mode work (Obsidian/Translate/Raw)
- [ ] 2 input adapter work (Web + EPUB) — TXT optional
- [ ] Image support cho web Obsidian mode work
- [ ] Royal Road novel có art scrape được, Obsidian render OK
- [ ] EPUB pirate scrape → output sạch, image embedded extract
- [ ] EPUB clean → không over-strip
- [ ] Baseline snapshot tool work
- [ ] `--bulk-relearn` với dry-run + typed confirmation
- [ ] README đủ để clone repo → chạy được trong 5 phút
- [ ] CLAUDE.md / BLUEPRINT.md / ROADMAP.md đồng bộ với code reality
- [ ] V1_1_BACKLOG.md có priority + rationale
- [ ] Dùng tool thật 1-2 tuần không crash major
- [ ] git tag v1.0.0

---

## 🚀 Sau v1.0 — v1.1 priorities

Top từ `docs/V1_1_BACKLOG.md` (xem CLAUDE.md §3 DEFERRED):

1. **TXT adapter** (nếu Phase 5 exit ramp ở v1.0) — expanded case + CJK
2. **Case-based learning cho web** — sau khi có 10+ profile để thấy pattern thật
3. **Calibration phase** — re-probe 10 chapter verify profile
4. **Site CJK hardening** — encoding heuristic, font deob, slugify pinyin, "第N章"/"第N話" chapter pattern
5. **TypedDict refactor `utils/types.py`** (P3-D từ session cũ)
6. **Performance benchmark + budget**
7. **Frontmatter customization** — `--no-frontmatter`, custom YAML fields
8. **Manhua adapter** — fork project riêng, gallery-dl pattern
9. **GUI** — Streamlit hoặc native, nếu CLI không đủ

**KHÔNG động vào v1.1 trước khi v1.0 dùng đủ 2 tuần stable.**

---

**END ROADMAP_VIBE_CODER v1.0**

*Mỗi step là 1 win nhỏ. Mỗi commit là 1 thắng lợi. Mỗi baseline diff zero là 1 lần thoát hiểm.*

*10-14 tuần sau, bạn sẽ có universal novel normalizer thật — KHÔNG phải build lại từ đầu, mà evolve từ Cào Text hiện tại lên.*

*Khi gặp khó, quay lại file này. Khi mất hứng, đọc retro phase trước.* 🚀
