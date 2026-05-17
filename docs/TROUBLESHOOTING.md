# Troubleshooting — Cào Text v1.0

> 10 most common issues + concrete fix. Ordered by likelihood, not severity.
>
> If your issue isn't listed: check `issues.md` (per-session log), then `progress/{...}.json` (per-story state), then re-run with `--no-validation --fast-learning` to isolate.

---

## 1. `[ERR] Không tìm thấy GEMINI_API_KEY trong .env`

**Symptom**: Crash at startup, before any scrape.

**Cause**: Missing or empty `.env` file in project root.

**Fix**:
```bash
# In project root
echo GEMINI_API_KEY=your_gemini_key_here > .env

# Get a free key at https://aistudio.google.com/apikey
```

`.env` must be in the same folder as `main.py`. Also auto-loaded from parent folder (Small Project workspace setup).

---

## 2. HTTP 429 — Gemini rate limit

**Symptom**: `[AI] ⏳ Rate limit: chờ Ns...` repeating, scrape grinds slow.

**Cause**: Free tier Gemini = 15 RPM. `AIRateLimiter` enforces `AI_MAX_RPM=10` (safety margin).

**Fix (auto)**: Code parses Gemini's `retry_delay { seconds: N }` and waits. No action needed.

**Fix (manual)**:
- Wait for rate window to reset (60s)
- Add second key: `GEMINI_API_KEY_2=...` in `.env` (round-robin support)
- Reduce `AI_MAX_RPM` in `config.py:61` if hitting 429 repeatedly despite limiter

---

## 3. Story stops after 5 consecutive errors

**Symptom**: `[ERR] Quá nhiều lỗi liên tiếp, dừng story`, low chapter count in output.

**Cause**: `MAX_CONSECUTIVE_ERRORS=5` safety circuit. Triggered by:
- Site changed structure → cached profile out of date
- Cloudflare hardened → curl_cffi fingerprint expired
- 5xx server errors persisting

**Fix**:
```bash
# Force re-learn the domain
echo "!relearn fanfiction.net" >> links.txt
python main.py links.txt

# Or bulk re-learn
python main.py --bulk-relearn --pattern "fanfiction\.net" --apply
```

If still failing: site needs Playwright (see #4) or has anti-bot upgrade.

---

## 4. Cloudflare challenge / curl can't fetch

**Symptom**: Empty HTML, "CF challenge detected", or 403.

**Cause**: Site behind Cloudflare bot protection. `curl_cffi` alone insufficient — needs full browser.

**Fix**:
```bash
# 1. Install Playwright
python -m pip install playwright playwright-stealth
python -m playwright install chromium

# 2. Re-run — code auto-detects CF and switches to Playwright per-domain
python main.py links.txt
```

Once a domain is flagged CF, future runs use Playwright by default. Stored in `DomainSessionPool._cf_domains` (in-memory) and via `requires_playwright=True` in `site_profiles.json` after learning.

---

## 5. `UnicodeDecodeError` on TXT input

**Symptom**:
```
UnicodeDecodeError: 'utf-8' codec can't decode byte 0xff ...
File 'path/to/file.txt' không phải UTF-8 — Cào Text v1.0 chỉ hỗ trợ UTF-8.
```

**Cause**: TXT file in non-UTF-8 encoding (Windows-1252, GBK, Shift-JIS, ...). v1.0 has no auto-detect (Decision: predictable behavior > convenience).

**Fix**:
```bash
# Linux/macOS
iconv -f cp1252 -t utf-8 input.txt > input_utf8.txt

# Windows PowerShell
Get-Content input.txt -Encoding Default | Set-Content input_utf8.txt -Encoding UTF8

# Or open in VS Code / Notepad++ → Save with UTF-8 encoding
```

CJK file? Specify source encoding:
- Chinese GB18030 → `iconv -f gb18030 -t utf-8 ...`
- Japanese Shift-JIS → `iconv -f shift-jis -t utf-8 ...`
- Korean EUC-KR → `iconv -f euc-kr -t utf-8 ...`

---

## 6. TXT pattern detection fails

**Symptom**:
```
ValueError: TXT pattern detection failed. AI fallback không tìm thấy pattern ...
```

**Cause**:
- File has no clear chapter boundary (one giant blob)
- Chapter heading format not in 6 built-in cases (VN "Chương N" 4 variants + EN "Chapter N" 2 variants)
- AI fallback regex matched header text only (caught by `_ai_verify_pattern`)

**Fix options**:

**(a) Manual case add** — edit `data/txt_cases.json`:
```json
{
  "id": "my_custom_pattern",
  "language": "en",
  "pattern": "^### Episode \\d+",
  "samples": ["### Episode 1", "### Episode 2"],
  "confidence": 0.9
}
```

**(b) Reformat file** to use a known pattern (VN: `Chương N` / EN: `Chapter N` at line start).

**(c) Run again with `ai_limiter` (passed by default in orchestrator)** — AI fallback may now succeed if first attempt timed out.

---

## 7. Image download fails

**Symptom**: `failed_images` list in chapter frontmatter, body shows `![alt](https://original_url)` external link instead of local path.

**Cause** (web mode):
- 404 / image moved
- Image >max size (`_MAX_IMAGE_BYTES` in `core/image_pipeline/web_fetcher.py`)
- Cloudflare blocks image fetch (different from chapter fetch)
- Timeout

**Fix**:
- Body fallback to external link is intentional — chapter still readable. Open the URL in browser to verify.
- For chronic failure: increase timeout in `core/image_pipeline/web_fetcher.py`, or add image domain to CF-aware path.

EPUB image fail: less common (binary in zip). If happens — likely corrupt EPUB. Re-download.

---

## 8. `Profile v1 detected — please !relearn`

**Symptom**:
```
ValueError: Profile 'domain.com' is v1 (legacy `pipeline` field present).
Run `!relearn domain.com` or `--bulk-relearn` to re-learn under v2 schema.
```

**Cause**: Profile created before Batch B (StepConfig serialization removed). Fail-loud chosen over silent auto-migrate to prevent data loss.

**Fix**:
```bash
# Single domain
echo "!relearn domain.com" >> links.txt
python main.py links.txt

# Bulk
python main.py --bulk-relearn --apply
```

See [docs/MIGRATION_NOTES.md](MIGRATION_NOTES.md) for details.

---

## 9. Ctrl+C doesn't kill the program

**Symptom**: First Ctrl+C → "Nhận tín hiệu dừng, progress đã lưu" but doesn't exit. Second Ctrl+C eventually works.

**Cause**: Async task chain has to unwind. `asyncio.shield(save_progress())` ensures progress write completes before cancel propagates.

**Fix**: Wait ~3-5s after first Ctrl+C. If still hung after 10s, second Ctrl+C is safe (progress already saved).

Windows-specific: harmless "I/O operation on closed pipe" messages during exit are suppressed by `_silence_transport_errors` in `main.py:471`.

---

## 10. AdsFilter strips real content

**Symptom**: Chapter looks truncated. Compare `output/{slug}/0042_*.md` with the original URL — sentences missing.

**Cause**:
- AdsFilter learned a false keyword (vd story-specific phrase that recurred 10+ times)
- Pass 1+2 strip ran too aggressive

**Fix**:
1. Inspect `data/ads_keywords.json` → find domain → review keyword list
2. Delete the false-positive keyword
3. Re-scrape (already-written files: `python tools/snapshot_baseline.py` won't help here — manual delete output + re-run)

**Prevention**:
- `_is_valid_ads_keyword()` in `utils/string_helpers.py` rejects: short words (<8 chars), HTML/URLs, story name (post-learning), nav phrases ("next chapter")
- `_GENERIC_SINGLE_WORDS` blocklist guards against generic terms ("login", "title", ...)
- MAX_STRIP_RATIO 60% safety cap in `utils/content_cleaner.py` prevents nuke

**Nuclear option** — disable AdsFilter for a domain:
- Set `ads_keywords_learned: []` in `data/site_profiles.json` for that domain
- Delete domain entry in `data/ads_keywords.json`

---

## Bonus — Debugging workflow

When something's weird:

1. **Check session log**: `issues.md` (newest at top) — per-chapter error context
2. **Check progress**: `progress/{domain}_{slug}_{hash}.json` — last URL, fingerprints, chapter_count
3. **Re-run with verbosity**: enable `logger` DEBUG in module of interest
4. **Isolate**: `python main.py --no-validation --fast-learning links.txt` — skip ProseRichness + skip ProseRichness validation in learning
5. **Compare**: diff output before/after change using `tools/snapshot_baseline.py`
6. **Test 1 chapter**: temporarily set `MAX_CHAPTERS=1` in `config.py`, re-run, inspect

If stuck: read [CLAUDE.md §10 STOP rules](../CLAUDE.md) before applying invasive fixes.
