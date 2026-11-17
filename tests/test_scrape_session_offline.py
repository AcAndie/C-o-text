"""tests/test_scrape_session_offline.py — Unit test toàn diện cho ScrapeSession với Fake Fetcher (Task 5.7).

Kiểm thử offline toàn diện các guards trong §6.2:
  1. Vòng lặp chương cuối RoyalRoad (chặn slug_increment, không lặp vô tận).
  2. Trùng nội dung (duplicate fingerprint guard, không ghi đè, tìm next không dùng slug_increment).
  3. Story-ID lệch (Story-ID guard, không nhảy sang truyện khác).
  4. Trang index guard (gặp trang mục lục -> dừng và đánh dấu hoàn thành).
  5. 5 chương rỗng liên tiếp (MAX_EMPTY_STREAK = 5 -> dừng; reset khi có chương hợp lệ).
  6. HTTP 429 (Rate limited guard -> không coi là hết truyện, dừng sau MAX_CONSECUTIVE_ERRORS).
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from cao_text.models import RunConfig, SiteProfile
from cao_text.storage import ProfileStore, ProgressStore
from cao_text.web.session import ScrapeSession

_SAMPLE_PROSE = """
The ancient towers of the ruined citadel reached toward the overcast sky like weathered fingers of stone.
Sir Galahad rested his hand upon the pommel of his silver sword, surveying the quiet overgrown courtyard below.
A cool autumn breeze stirred the decaying leaves, carrying with it the faint scent of rain and old memories.
There was no doubt that danger still lurked within these forgotten halls, waiting for an unwary traveler.
He drew a slow breath, steeled his resolve, and stepped forward across the shattered threshold.
"""

_SAMPLE_PROSE_2 = """
Beneath the vaulted stone arches, shadows danced in the flickering light of his newly kindled torch.
Every footstep echoed against the damp walls, breaking a silence that had lasted for over a century.
The runes carved into the granite pillars began to hum with a faint, iridescent luminescence.
He touched the cold stone, feeling the gentle pulse of ancient magic still sleeping within the deep earth.
Whatever secrets the ancients had buried here were now within his grasp, if only he could survive the night.
"""


class FakeSessionPool:
    """Fake fetcher offline mô phỏng DomainSessionPool."""

    def __init__(self, mapping: dict[str, tuple[int, str] | str | Exception]) -> None:
        self.mapping = mapping
        self.calls: dict[str, int] = {}

    async def fetch(self, url: str, **kwargs: Any) -> tuple[int, str]:
        self.calls[url] = self.calls.get(url, 0) + 1
        val = self.mapping.get(url)
        if val is None:
            return 404, "<!DOCTYPE html><html><body><h1>404 Not Found</h1></body></html>"
        if isinstance(val, tuple):
            return val[0], val[1]
        if isinstance(val, Exception):
            raise val
        return 200, str(val)

    def is_cf_domain(self, domain: str) -> bool:
        return False

    async def close_all(self) -> None:
        pass


@pytest.fixture
def base_stores(tmp_path: Path) -> tuple[ProfileStore, ProgressStore, RunConfig]:
    prof_file = tmp_path / "site_profiles.json"
    prof_store = ProfileStore(prof_file)
    prog_store = ProgressStore(tmp_path / "progress")
    run_cfg = RunConfig(output_dir=str(tmp_path / "output"))
    return prof_store, prog_store, run_cfg


# ── Ca 1: Vòng lặp chương cuối RoyalRoad (chặn slug_increment) ────────────────


@pytest.mark.asyncio
async def test_guard_royalroad_last_chapter_slug_increment_blocked(
    tmp_path: Path,
    base_stores: tuple[ProfileStore, ProgressStore, RunConfig],
) -> None:
    """RoyalRoad: URL dạng /chapter/<id>/<slug> không được dùng slug_increment ở chương cuối."""
    prof_store, prog_store, run_cfg = base_stores

    profile = SiteProfile(
        domain="royalroad.com",
        profile_version=3,
        content_selector="div.chapter-inner",
        title_selector="h1",
        next_selector="div.nav-next a.btn",
        chapter_url_pattern=r"https://www\.royalroad\.com/fiction/\d+/.*?/chapter/\d+/.*",
    )
    await prof_store.save(profile)

    last_chap_url = "https://www.royalroad.com/fiction/55418/rock-falls/chapter/1101742/epilogue-2-sisyphus"

    # Đọc HTML từ fixture local nếu có, ngược lại dùng HTML giả lập RoyalRoad
    fixture_local = (
        Path(__file__).parent
        / "fixtures_local/web/www.royalroad.com/rock_falls_last_chapter/0001.html"
    )
    if fixture_local.exists():
        html = fixture_local.read_text(encoding="utf-8")
    else:
        html = f"""
        <!DOCTYPE html><html><body>
          <h1>Epilogue 2: Sisyphus</h1>
          <div class="chapter-inner">{_SAMPLE_PROSE}</div>
          <!-- Nút next bị disabled hoặc không có href hợp lệ -->
          <div class="nav-next"><a class="btn disabled">Next Chapter</a></div>
        </body></html>
        """

    fake_pool = FakeSessionPool({last_chap_url: (200, html)})

    session = ScrapeSession(
        start_url=last_chap_url,
        profile=profile,
        pool=fake_pool,
        progress_store=prog_store,
        profile_store=prof_store,
        run_config=run_cfg,
        sleep_fn=lambda _: asyncio.sleep(0),
    )

    state = await session.run()

    # Xác nhận: cào đúng 1 chương cuối và dừng lại, KHÔNG tạo slug_increment 'epilogue-3-sisyphus'
    assert state.chapter_count == 1
    assert state.completed is True
    # Gọi fetch cho URL này (1 lần ở setup classification + 1 lần ở step)
    assert fake_pool.calls[last_chap_url] >= 1
    # Không có URL bịa slug_increment nào khác được fetch
    assert len(fake_pool.calls) == 1


# ── Ca 2: Trùng nội dung (Duplicate Fingerprint Guard) ─────────────────────────


@pytest.mark.asyncio
async def test_guard_duplicate_content_fingerprint(
    tmp_path: Path,
    base_stores: tuple[ProfileStore, ProgressStore, RunConfig],
) -> None:
    """Chương 2 có nội dung trùng lặp với Chương 1 (lỗi/khóa chương) -> đánh dấu DUPLICATE, không ghi đè, tìm next."""
    prof_store, prog_store, run_cfg = base_stores

    profile = SiteProfile(
        domain="example.com",
        profile_version=3,
        content_selector="div.content",
        title_selector="h1",
        next_selector="a.next-btn",
    )
    await prof_store.save(profile)

    u1 = "https://example.com/novel/my-novel/ch1"
    u2 = "https://example.com/novel/my-novel/ch2"  # Nội dung trùng ch1
    u3 = "https://example.com/novel/my-novel/ch3"  # Nội dung mới

    h1 = f"""
    <!DOCTYPE html><html><body>
      <h1>Chapter 1</h1>
      <div class="content">{_SAMPLE_PROSE}</div>
      <a class="next-btn" href="{u2}">Next</a>
    </body></html>
    """
    # ch2 nội dung giống y hệt ch1, next trỏ sang ch3
    h2 = f"""
    <!DOCTYPE html><html><body>
      <h1>Chapter 2 (Locked Notice)</h1>
      <div class="content">{_SAMPLE_PROSE}</div>
      <a class="next-btn" href="{u3}">Next</a>
    </body></html>
    """
    h3 = f"""
    <!DOCTYPE html><html><body>
      <h1>Chapter 3</h1>
      <div class="content">{_SAMPLE_PROSE_2}</div>
    </body></html>
    """

    fake_pool = FakeSessionPool({u1: h1, u2: h2, u3: h3})

    session = ScrapeSession(
        start_url=u1,
        profile=profile,
        pool=fake_pool,
        progress_store=prog_store,
        profile_store=prof_store,
        run_config=run_cfg,
        sleep_fn=lambda _: asyncio.sleep(0),
    )

    state = await session.run()

    # Tổng số chương hợp lệ được ghi là 2 (ch1 và ch3), ch2 bị bỏ qua vì duplicate
    assert state.chapter_count == 2
    assert u2 in session.visited_urls
    assert state.completed is True


# ── Ca 3: Story-ID lệch (Story-ID Guard) ───────────────────────────────────────


@pytest.mark.asyncio
async def test_guard_story_id_mismatch(
    tmp_path: Path,
    base_stores: tuple[ProfileStore, ProgressStore, RunConfig],
) -> None:
    """Next URL trỏ sang một truyện hoàn toàn khác -> Story-ID guard chặn dừng."""
    prof_store, prog_store, run_cfg = base_stores

    profile = SiteProfile(
        domain="royalroad.com",
        profile_version=3,
        content_selector="div.content",
        title_selector="h1",
        next_selector="a.next-btn",
    )
    await prof_store.save(profile)

    u1 = "https://www.royalroad.com/fiction/11111/story-alpha/chapter/1/intro"
    u_other = "https://www.royalroad.com/fiction/99999/story-beta/chapter/1/intro"

    h1 = f"""
    <!DOCTYPE html><html><body>
      <h1>Chapter 1: Intro</h1>
      <div class="content">{_SAMPLE_PROSE}</div>
      <a class="next-btn" href="{u_other}">Next</a>
    </body></html>
    """
    h_other = f"""
    <!DOCTYPE html><html><body>
      <h1>Beta Story</h1>
      <div class="content">{_SAMPLE_PROSE_2}</div>
    </body></html>
    """

    fake_pool = FakeSessionPool({u1: h1, u_other: h_other})

    session = ScrapeSession(
        start_url=u1,
        profile=profile,
        pool=fake_pool,
        progress_store=prog_store,
        profile_store=prof_store,
        run_config=run_cfg,
        sleep_fn=lambda _: asyncio.sleep(0),
    )

    state = await session.run()

    # Đã cào xong ch1 và dừng lại vì next URL lệch Story-ID (/fiction/99999/ != /fiction/11111/)
    assert state.chapter_count == 1
    assert u_other not in fake_pool.calls


# ── Ca 4: Trang index guard ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_guard_index_page(
    tmp_path: Path,
    base_stores: tuple[ProfileStore, ProgressStore, RunConfig],
) -> None:
    """Next URL trỏ về trang index/mục lục của truyện -> Index guard nhận diện và kết thúc."""
    prof_store, prog_store, run_cfg = base_stores

    profile = SiteProfile(
        domain="example.com",
        profile_version=3,
        content_selector="div.content",
        title_selector="h1",
        next_selector="a.next-btn",
    )
    await prof_store.save(profile)

    u1 = "https://example.com/novel/my-book/chapter-1"
    u_index = "https://example.com/novel/my-book"

    h1 = f"""
    <!DOCTYPE html><html><body>
      <h1>Chapter 1</h1>
      <div class="content">{_SAMPLE_PROSE}</div>
      <a class="next-btn" href="{u_index}">Next</a>
    </body></html>
    """
    # Trang index: danh sách chương dạng link, không có nội dung văn xuôi
    h_index = """
    <!DOCTYPE html><html><body>
      <h1>My Book - Table of Contents</h1>
      <div class="chapter-list">
        <ul>
          <li><a href="https://example.com/novel/my-book/chapter-1">Chapter 1</a></li>
          <li><a href="https://example.com/novel/my-book/chapter-2">Chapter 2</a></li>
          <li><a href="https://example.com/novel/my-book/chapter-3">Chapter 3</a></li>
        </ul>
      </div>
    </body></html>
    """

    fake_pool = FakeSessionPool({u1: h1, u_index: h_index})

    session = ScrapeSession(
        start_url=u1,
        profile=profile,
        pool=fake_pool,
        progress_store=prog_store,
        profile_store=prof_store,
        run_config=run_cfg,
        sleep_fn=lambda _: asyncio.sleep(0),
    )

    state = await session.run()

    assert state.chapter_count == 1
    assert state.completed is True


# ── Ca 5: 5 chương rỗng liên tiếp (MAX_EMPTY_STREAK = 5) ─────────────────────


@pytest.mark.asyncio
async def test_guard_max_empty_streak_and_reset(
    tmp_path: Path,
    base_stores: tuple[ProfileStore, ProgressStore, RunConfig],
) -> None:
    """5 chương rỗng liên tiếp -> dừng và ghi issues.md; nếu có chương xen kẽ -> reset streak."""
    prof_store, prog_store, run_cfg = base_stores

    profile = SiteProfile(
        domain="example.com",
        profile_version=3,
        content_selector="div.content",
        title_selector="h1",
        next_selector="a.next-btn",
    )
    await prof_store.save(profile)

    def empty_html(next_url: str | None) -> str:
        next_tag = f'<a class="next-btn" href="{next_url}">Next</a>' if next_url else ""
        return (
            "<!DOCTYPE html><html><head><title>Chapter Page</title></head><body>"
            "<header><nav>Site Navigation Bar with Menus</nav></header>"
            "<h1>Chapter</h1><div class=\"content\">Short note</div>"
            f"{next_tag}"
            "<footer>Footer content with copyright and disclaimers</footer></body></html>"
        )

    # Trường hợp A: 5 chương rỗng liên tiếp -> dừng ở chương 5
    prefix_a = "https://example.com/novel/empty-streak/ch"
    mapping_a = {
        f"{prefix_a}1": empty_html(f"{prefix_a}2"),
        f"{prefix_a}2": empty_html(f"{prefix_a}3"),
        f"{prefix_a}3": empty_html(f"{prefix_a}4"),
        f"{prefix_a}4": empty_html(f"{prefix_a}5"),
        f"{prefix_a}5": empty_html(f"{prefix_a}6"),
        f"{prefix_a}6": f'<!DOCTYPE html><html><body><h1>Good</h1><div class="content">{_SAMPLE_PROSE}</div></body></html>',
    }

    pool_a = FakeSessionPool(mapping_a)
    session_a = ScrapeSession(
        start_url=f"{prefix_a}1",
        profile=profile,
        pool=pool_a,
        progress_store=prog_store,
        profile_store=prof_store,
        run_config=run_cfg,
        max_empty_streak=5,
        sleep_fn=lambda _: asyncio.sleep(0),
    )
    state_a = await session_a.run()

    # Dừng tại ch5 (đúng 5 chương rỗng), ch6 không bao giờ được gọi
    assert state_a.chapter_count == 0
    assert f"{prefix_a}6" not in pool_a.calls

    # Trường hợp B: e1(rỗng), e2(rỗng), e3(tốt), e4(rỗng), e5(rỗng) -> không dừng ở e5
    prefix_b = "https://example.com/novel/reset-streak/ch"
    mapping_b = {
        f"{prefix_b}1": empty_html(f"{prefix_b}2"),
        f"{prefix_b}2": empty_html(f"{prefix_b}3"),
        f"{prefix_b}3": f'<!DOCTYPE html><html><body><h1>Good</h1><div class="content">{_SAMPLE_PROSE}</div><a class="next-btn" href="{prefix_b}4">Next</a></body></html>',
        f"{prefix_b}4": empty_html(f"{prefix_b}5"),
        f"{prefix_b}5": empty_html(None),
    }

    pool_b = FakeSessionPool(mapping_b)
    session_b = ScrapeSession(
        start_url=f"{prefix_b}1",
        profile=profile,
        pool=pool_b,
        progress_store=prog_store,
        profile_store=prof_store,
        run_config=run_cfg,
        max_empty_streak=5,
        sleep_fn=lambda _: asyncio.sleep(0),
    )
    state_b = await session_b.run()

    # Streak được reset tại b3, tổng số chương hợp lệ ghi được là 1
    assert state_b.chapter_count == 1
    assert pool_b.calls[f"{prefix_b}5"] == 1


# ── Ca 6: HTTP 429 Rate Limited Guard ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_guard_http_429_rate_limited(
    tmp_path: Path,
    base_stores: tuple[ProfileStore, ProgressStore, RunConfig],
) -> None:
    """HTTP 429 trả về RATE_LIMITED, không coi là hoàn thành, dừng khi chạm max_consecutive_errors."""
    prof_store, prog_store, run_cfg = base_stores

    profile = SiteProfile(
        domain="example.com",
        profile_version=3,
        content_selector="div.content",
    )
    await prof_store.save(profile)

    u1 = "https://example.com/novel/test-429/ch1"
    fake_pool = FakeSessionPool({u1: (429, "")})

    session = ScrapeSession(
        start_url=u1,
        profile=profile,
        pool=fake_pool,
        progress_store=prog_store,
        profile_store=prof_store,
        run_config=run_cfg,
        max_consecutive_errors=2,
        timeout_backoff_base=0.01,
        sleep_fn=lambda _: asyncio.sleep(0),
    )

    state = await session.run()

    # Không coi là hoàn thành, không tăng chapter_count
    assert state.chapter_count == 0
    assert state.completed is False
    # Gọi 1 lần ở setup() + 2 lần ở vòng lặp run() = 3 lần
    assert fake_pool.calls[u1] == 3
