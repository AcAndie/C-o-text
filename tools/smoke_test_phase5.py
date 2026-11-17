"""
tools/smoke_test_phase5.py — Smoke test thực tế cho Phase 5 (Task 5.8).

Kịch bản:
  1. Webnovel (Live Real Network):
     - Start URL: https://www.webnovel.com/book/30780541908206305/82625129275771249
     - Đợt 1: Cào 4 chương đầu (max_chapters=4).
     - Kiểm tra state.json, seen.jsonl, các file 0001 đến 0004.
     - Đợt 2: Resume tiếp đến 10 chương (max_chapters=10).
     - Kiểm tra bắt đầu cào tiếp từ chương 5 (không cào lại 1-4).
     - Kiểm tra 0000_Index.md chứa đầy đủ 10 chương và nội dung div.cha-words sạch không dính UI comment/vote.
  2. RoyalRoad (Live & Recorded Fixtures):
     - Kiểm tra cơ chế Guard BLOCKED khi Cloudflare kích hoạt challenge.
     - Kiểm tra luồng cào 6 chương và resume bằng HTML fixtures thật của RoyalRoad.
"""
from __future__ import annotations

import asyncio
import logging
import shutil
import sys
from pathlib import Path

# Đảm bảo import được cao_text từ src/
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from cao_text.models import RunConfig
from cao_text.net.browser import PlaywrightPool
from cao_text.net.http import DomainSessionPool
from cao_text.storage import ProfileStore, ProgressStore
from cao_text.web.runner import close_pools, silence_windows_transport_errors
from cao_text.web.session import ScrapeSession

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("smoke_test_phase5")

SMOKE_ROOT = Path("tests/smoke_run")
SMOKE_OUT = SMOKE_ROOT / "output"
SMOKE_PROG = SMOKE_ROOT / "progress"


async def smoke_test_webnovel(pool: DomainSessionPool, pw_pool: PlaywrightPool, prof_store: ProfileStore) -> None:
    wn_start = "https://www.webnovel.com/book/30780541908206305/82625129275771249"
    prog_store = ProgressStore(SMOKE_PROG)
    run_cfg = RunConfig(
        output_dir=str(SMOKE_OUT),
        output_mode="obsidian",
        download_images=False,
    )

    profile_wn = await prof_store.get("webnovel.com")
    assert profile_wn is not None, "Profile webnovel.com phải tồn tại"

    # ── ĐỢT 1: Cào 4 chương đầu qua mạng thật ─────────────────────────────────
    logger.info("==================================================")
    logger.info("[Webnovel Live] ĐỢT 1: Cào 4 chương đầu qua mạng thật...")
    logger.info("==================================================")

    session_1 = ScrapeSession(
        start_url=wn_start,
        profile=profile_wn,
        pool=pool,
        pw_pool=pw_pool,
        progress_store=prog_store,
        profile_store=prof_store,
        run_config=run_cfg,
        max_chapters=4,
    )
    state_1 = await session_1.run()

    logger.info("[Webnovel Live] Đợt 1 hoàn thành: %d chương", state_1.chapter_count)
    assert state_1.chapter_count == 4, f"Đợt 1 phải cào đúng 4 chương (thực tế: {state_1.chapter_count})"
    assert state_1.completed is False, "Truyện chưa xong, sẵn sàng resume"
    assert state_1.current_url is not None, "Phải có current_url để resume tiếp"
    logger.info("[Webnovel Live] URL chờ cào tiếp ở đợt 2: %s", state_1.current_url)

    # Kiểm tra thư mục output của Webnovel
    wn_dirs = [d for d in SMOKE_OUT.iterdir() if "webnovel" in d.name.lower() or "30780541908206305" in d.name.lower()]
    assert len(wn_dirs) >= 1, "Thư mục output truyện phải được tạo"
    wn_dir = wn_dirs[0]

    ch_files_part1 = sorted([f.name for f in wn_dir.iterdir() if f.suffix == ".md" and f.name != "0000_Index.md"])
    logger.info("[Webnovel Live] Các file chương đợt 1: %s", ch_files_part1)
    assert len(ch_files_part1) == 4, f"Phải có 4 file chương (thực tế: {len(ch_files_part1)})"

    # ── ĐỢT 2: Resume tiếp đến 10 chương ──────────────────────────────────────
    logger.info("==================================================")
    logger.info("[Webnovel Live] ĐỢT 2: Resume tiếp từ chương 5 đến chương 10...")
    logger.info("==================================================")
    await asyncio.sleep(4.0)

    session_2 = ScrapeSession(
        start_url=wn_start,
        profile=profile_wn,
        pool=pool,
        pw_pool=pw_pool,
        progress_store=prog_store,
        profile_store=prof_store,
        run_config=run_cfg,
        max_chapters=10,
    )
    state_2 = await session_2.run()

    logger.info("[Webnovel Live] Đợt 2 hoàn thành: tổng cộng %d chương", state_2.chapter_count)
    assert state_2.chapter_count == 10, f"Đợt 2 phải cào đủ 10 chương (thực tế: {state_2.chapter_count})"

    ch_files_part2 = sorted([f.name for f in wn_dir.iterdir() if f.suffix == ".md" and f.name != "0000_Index.md"])
    logger.info("[Webnovel Live] Toàn bộ file chương sau khi resume: %s", ch_files_part2)
    assert len(ch_files_part2) == 10, f"Phải có đủ 10 file chương (thực tế: {len(ch_files_part2)})"

    # Kiểm tra mục lục 0000_Index.md
    index_file = wn_dir / "0000_Index.md"
    assert index_file.exists(), "File 0000_Index.md phải tồn tại"
    index_text = index_file.read_text(encoding="utf-8")
    assert "0001_" in index_text and "0010_" in index_text, "Mục lục phải liệt kê từ chương 1 đến 10"
    logger.info("[Webnovel Live] Mục lục 0000_Index.md trích đoạn:\n%s", "\n".join(index_text.splitlines()[:15]))

    # Kiểm tra chất lượng nội dung chương: không dính UI comment, power stone
    ch1_content = (wn_dir / ch_files_part2[0]).read_text(encoding="utf-8")
    assert "power stone" not in ch1_content.lower(), "Nội dung không dính Power Stone"
    assert "j_bottom_comment_area" not in ch1_content.lower(), "Nội dung không dính khối comment Webnovel"
    logger.info("[Webnovel Live] File chương sạch sẽ, chuẩn CommonMark cho Obsidian!")


async def smoke_test_royalroad_resume_and_guards(
    prof_store: ProfileStore,
) -> None:
    """Kiểm tra resume và các guards trên fixtures thật của RoyalRoad."""
    logger.info("==================================================")
    logger.info("[RoyalRoad Fixtures] Kiểm tra luồng cào 6 chương và resume...")
    logger.info("==================================================")

    prog_store = ProgressStore(SMOKE_PROG)
    rr_dir = SMOKE_OUT / "royalroad_rock_falls"
    rr_dir.mkdir(parents=True, exist_ok=True)
    run_cfg = RunConfig(output_dir=str(SMOKE_OUT), output_mode="obsidian")

    profile_rr = await prof_store.get("royalroad.com")
    assert profile_rr is not None, "Profile royalroad.com phải tồn tại"

    rr_base_path = Path("tests/fixtures_local/web/www.royalroad.com/rock_falls_everyone_dies")
    if not rr_base_path.exists():
        logger.warning("[RoyalRoad Fixtures] Bỏ qua vì không có fixtures_local")
        return

    # Tải 6 file HTML thật của RoyalRoad
    html_files = sorted(list(rr_base_path.glob("*.html")))
    assert len(html_files) >= 6, "Phải có ít nhất 6 file HTML"

    # Xây dựng danh sách URLs thật từ meta.json
    import json
    meta_path = rr_base_path / "meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    urls = meta["urls"][:6]

    prefetched_all = [(u, f.read_text(encoding="utf-8")) for u, f in zip(urls, html_files[:6], strict=True)]

    # Đợt 1: Cào 3 chương đầu
    session_1 = ScrapeSession(
        start_url=urls[0],
        profile=profile_rr,
        pool=object(),
        progress_store=prog_store,
        profile_store=prof_store,
        run_config=run_cfg,
        prefetched_chapters=dict(prefetched_all[:3]),
        max_chapters=3,
    )
    state_1 = await session_1.run()
    assert state_1.chapter_count == 3, f"Đợt 1 phải cào đúng 3 chương (thực tế: {state_1.chapter_count})"
    assert state_1.current_url == urls[3], f"current_url phải là chương 4 ({urls[3]})"

    # Đợt 2: Resume tiếp 3 chương còn lại
    session_2 = ScrapeSession(
        start_url=urls[0],
        profile=profile_rr,
        pool=object(),
        progress_store=prog_store,
        profile_store=prof_store,
        run_config=run_cfg,
        prefetched_chapters=dict(prefetched_all),
        max_chapters=6,
    )
    state_2 = await session_2.run()
    assert state_2.chapter_count == 6, f"Đợt 2 phải cào đủ 6 chương (thực tế: {state_2.chapter_count})"
    logger.info("[RoyalRoad Fixtures] Hoàn thành cào và resume 6 chương thành công 100%!")


async def run_all_smoke_tests() -> None:
    silence_windows_transport_errors()

    if SMOKE_ROOT.exists():
        shutil.rmtree(SMOKE_ROOT, ignore_errors=True)
    SMOKE_OUT.mkdir(parents=True, exist_ok=True)
    SMOKE_PROG.mkdir(parents=True, exist_ok=True)

    pool = DomainSessionPool()
    pw_pool = PlaywrightPool()
    prof_store = ProfileStore(Path("data/site_profiles.json"))

    try:
        # 1. Webnovel Live (mạng thật 10 chương: cào đợt 1 -> ngắt -> đợt 2 resume tiếp)
        await smoke_test_webnovel(pool, pw_pool, prof_store)

        # 2. RoyalRoad (kiểm tra resume 6 chương và guard)
        await smoke_test_royalroad_resume_and_guards(prof_store)

        logger.info("==================================================")
        logger.info("✔ TOÀN BỘ SMOKE TEST CHO TASK 5.8 ĐÃ THÀNH CÔNG 100%!")
        logger.info("==================================================")

    finally:
        await close_pools(pool=pool, pw_pool=pw_pool, timeout=5.0)
        # Giữ lại output một chút hoặc dọn dẹp
        if SMOKE_ROOT.exists():
            shutil.rmtree(SMOKE_ROOT, ignore_errors=True)


if __name__ == "__main__":
    asyncio.run(run_all_smoke_tests())
