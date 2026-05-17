"""
tools/snapshot_baseline.py — Capture baseline scrape output for regression diff.

Read-only w.r.t. site_profiles.json: uses _ReadOnlyProfileManager.
Uses temp progress file inside label dir (auto-deleted after run).
Stops after --chapters via on_chapter_done hook.

Run from project root:
    python tools/snapshot_baseline.py \\
        --profile fanfiction.net --chapters 5 \\
        --label phase0_ffn \\
        --url https://www.fanfiction.net/s/14213710/1/

Requires existing profile (run main.py first to learn domain).
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import AI_MAX_RPM, PROFILES_FILE
from ai.client import AIRateLimiter
from core.session_pool import DomainSessionPool, PlaywrightPool
from core.scraper import run_novel_task
from learning.profile_manager import ProfileManager
from utils.file_io import load_profiles
from utils.types import SiteProfile

logger = logging.getLogger(__name__)

BASELINES_DIR = os.path.join("data", "baselines")


# ── Read-only PM: prevents writes to site_profiles.json ─────────────────────

class _ReadOnlyProfileManager(ProfileManager):
    async def flush(self) -> None:
        pass

    async def save_profile(self, domain: str, profile: SiteProfile) -> None:  # type: ignore[override]
        pass

    async def add_ads_to_profile(self, domain: str, keywords: list[str]) -> int:
        return 0


# ── CLI ──────────────────────────────────────────────────────────────────────

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Capture baseline scrape output for regression diff.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python tools/snapshot_baseline.py \\
      --profile fanfiction.net --chapters 5 \\
      --label phase0_ffn \\
      --url https://www.fanfiction.net/s/14213710/1/

  python tools/snapshot_baseline.py \\
      --profile royalroad.com --chapters 5 \\
      --label phase0_rr \\
      --url https://www.royalroad.com/fiction/xxx/chapter/1

NOTE: Profile for the domain must exist first.
Run:  python main.py links.txt   (with the site URL) to learn it.
        """,
    )
    p.add_argument("--profile",  required=True, help="Domain (e.g. fanfiction.net)")
    p.add_argument("--chapters", type=int, default=5, help="Chapters to capture (default: 5)")
    p.add_argument("--label",    required=True, help="Baseline label (e.g. phase0_ffn)")
    p.add_argument("--url",      required=True, help="Chapter 1 URL to start from")
    p.add_argument("--verbose",  action="store_true", help="Debug logging")
    return p.parse_args()


def _profile_hash(profiles: dict, domain: str) -> str:
    raw = json.dumps(profiles.get(domain, {}), sort_keys=True, ensure_ascii=False)
    return hashlib.md5(raw.encode()).hexdigest()[:12]


# ── Main async run ────────────────────────────────────────────────────────────

async def _run(args: argparse.Namespace) -> None:
    domain     = args.profile.lower().strip()
    label      = args.label.strip()
    n_chapters = args.chapters
    start_url  = args.url

    if not os.path.exists("config.py"):
        print("[ERR] Run from project root (directory containing config.py).", file=sys.stderr)
        sys.exit(1)

    # ── Label dir ─────────────────────────────────────────────────────────────
    label_dir   = os.path.abspath(os.path.join(BASELINES_DIR, label))
    existing_md = [f for f in os.listdir(label_dir) if f.endswith(".md")] if os.path.isdir(label_dir) else []
    if existing_md:
        print(f"[WARN] '{label}' has {len(existing_md)} existing .md files — overwriting.", flush=True)
    os.makedirs(label_dir, exist_ok=True)

    # ── Validate profile ──────────────────────────────────────────────────────
    if not os.path.exists(PROFILES_FILE):
        print(
            f"[ERR] No profiles file at {PROFILES_FILE}.\n"
            f"      Learn domain first: add URL to links.txt → python main.py links.txt",
            file=sys.stderr,
        )
        sys.exit(1)
    profiles = await load_profiles()
    if domain not in profiles:
        print(
            f"[ERR] No profile for '{domain}'.\n"
            f"      Learn domain first: add URL to links.txt → python main.py links.txt",
            file=sys.stderr,
        )
        sys.exit(1)

    p_hash = _profile_hash(profiles, domain)
    print(f"[snapshot] Profile '{domain}' found (hash: {p_hash})", flush=True)
    print(f"[snapshot] Capturing {n_chapters} chapters → {label_dir}", flush=True)
    print(f"[snapshot] Start URL: {start_url}", flush=True)

    # ── Runtime objects ───────────────────────────────────────────────────────
    profiles_lock = asyncio.Lock()
    pm            = _ReadOnlyProfileManager(profiles, profiles_lock)
    ai_limiter    = AIRateLimiter(AI_MAX_RPM)
    pool          = DomainSessionPool()
    pw_pool       = PlaywrightPool()

    # ── Pre-seed temp progress: lock output to label_dir, skip naming AI call ─
    progress_path = os.path.join(label_dir, "_snapshot_progress_temp.json")
    with open(progress_path, "w", encoding="utf-8") as f:
        json.dump({
            "naming_done":        True,
            "output_dir_final":   label_dir,
            "story_name_clean":   label,
            "chapter_keyword":    "Chapter",
            "has_chapter_subtitle": True,
            "story_prefix_strip": "",
        }, f, ensure_ascii=False, indent=2)

    # ── Chapter counter → cancel after N ─────────────────────────────────────
    chapter_count = 0

    async def on_chapter_done() -> None:
        nonlocal chapter_count
        chapter_count += 1
        print(f"[snapshot] {chapter_count}/{n_chapters} chapters captured.", flush=True)
        if chapter_count >= n_chapters:
            raise asyncio.CancelledError("Snapshot: chapter limit reached")

    # ── Run ───────────────────────────────────────────────────────────────────
    try:
        await run_novel_task(
            start_url       = start_url,
            output_dir      = label_dir,
            progress_path   = progress_path,
            pool            = pool,
            pw_pool         = pw_pool,
            pm              = pm,
            ai_limiter      = ai_limiter,
            on_chapter_done = on_chapter_done,
        )
    except asyncio.CancelledError:
        pass  # expected after N chapters
    finally:
        await pw_pool.close()
        if os.path.exists(progress_path):
            os.remove(progress_path)

    # ── Save _meta.json ───────────────────────────────────────────────────────
    captured = sorted(f for f in os.listdir(label_dir) if f.endswith(".md"))
    meta = {
        "label":              label,
        "domain":             domain,
        "url":                start_url,
        "chapters_requested": n_chapters,
        "chapters_captured":  len(captured),
        "profile_hash":       p_hash,
        "timestamp":          datetime.now(timezone.utc).isoformat(),
    }
    with open(os.path.join(label_dir, "_meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    print(f"\n[snapshot] Done. {len(captured)} file(s) in {label_dir}:", flush=True)
    for name in captured:
        print(f"  {name}", flush=True)
    if len(captured) < n_chapters:
        print(f"[WARN] Expected {n_chapters} but got {len(captured)} — story may have ended early.", flush=True)


def main() -> None:
    args = _parse_args()
    logging.basicConfig(
        level  = logging.DEBUG if args.verbose else logging.WARNING,
        format = "%(levelname)s %(name)s: %(message)s",
    )
    asyncio.run(_run(args))


if __name__ == "__main__":
    main()
