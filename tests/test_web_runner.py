"""tests/test_web_runner.py — Unit test cho điều phối cào web song song, khóa learning, init_stagger và bảo vệ Ctrl+C (Task 5.5 + 5.6)."""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from cao_text.ai.schemas import PageClassificationOutput
from cao_text.models import RunConfig, SiteProfile, StoryState
from cao_text.storage import ProfileStore, ProgressStore
from cao_text.web.runner import (
    DomainLockManager,
    apply_relearn,
    close_pools,
    is_valid_url,
    normalize_domain,
    parse_links,
    run_novel_task,
    run_web_tasks,
    silence_windows_transport_errors,
)
from cao_text.web.session import ScrapeSession
from cao_text.writers.nav_injector import heal_missing_indexes


def test_normalize_domain() -> None:
    assert normalize_domain("royalroad.com") == "royalroad.com"
    assert normalize_domain("www.royalroad.com") == "royalroad.com"
    assert normalize_domain("https://www.webnovel.com/book/123") == "webnovel.com"
    assert normalize_domain("http://novelfire.net:8080/story") == "novelfire.net"
    assert normalize_domain("   WWW.EXAMPLE.ORG/PATH  ") == "example.org"


def test_is_valid_url() -> None:
    assert is_valid_url("https://www.royalroad.com/fiction/123/chapter/1") is True
    assert is_valid_url("http://example.com") is True
    assert is_valid_url("ftp://example.com/file") is False
    assert is_valid_url("not a url") is False
    assert is_valid_url("") is False


def test_parse_links_text_and_file(tmp_path: Path) -> None:
    content = """
    # Danh sách truyện cào
    https://www.royalroad.com/fiction/1/chapter/1

    # Cần học lại domain này
    !relearn webnovel.com
    !RELEARN https://www.novelfire.net/

    https://www.webnovel.com/book/2/chapter/1
    invalid_url_here
    ftp://invalid-scheme.com/novel
    https://example.org/ch1 # có inline comment phía sau vẫn hợp lệ
    """
    urls, relearn = parse_links(content)
    assert urls == [
        "https://www.royalroad.com/fiction/1/chapter/1",
        "https://www.webnovel.com/book/2/chapter/1",
        "https://example.org/ch1",
    ]
    assert relearn == ["webnovel.com", "novelfire.net"]

    # Test đọc từ file
    links_file = tmp_path / "links.md"
    links_file.write_text(content, encoding="utf-8")
    urls_f, relearn_f = parse_links(links_file)
    assert urls_f == urls
    assert relearn_f == relearn


@pytest.mark.asyncio
async def test_apply_relearn(tmp_path: Path) -> None:
    profiles_file = tmp_path / "site_profiles.json"
    store = ProfileStore(profiles_file)

    p1 = SiteProfile(domain="royalroad.com", profile_version=3, content_selector="div.content")
    p2 = SiteProfile(domain="www.webnovel.com", profile_version=3, content_selector="div.content")
    p3 = SiteProfile(domain="novelfire.net", profile_version=3, content_selector="div.content")
    await store.save(p1)
    await store.save(p2)
    await store.save(p3)

    removed = await apply_relearn(["royalroad.com", "webnovel.com"], store)
    assert removed >= 2

    assert await store.get("royalroad.com") is None
    assert await store.get("webnovel.com") is None
    assert await store.get("novelfire.net") is not None


def test_domain_lock_manager() -> None:
    mgr = DomainLockManager()
    lock1 = mgr.get_lock("royalroad.com")
    lock2 = mgr.get_lock("www.royalroad.com")
    lock3 = mgr.get_lock("https://royalroad.com/fiction/1")
    lock_other = mgr.get_lock("webnovel.com")

    # Cùng domain -> cùng 1 Lock instance
    assert lock1 is lock2
    assert lock2 is lock3
    # Khác domain -> khác Lock instance
    assert lock1 is not lock_other


@pytest.mark.asyncio
async def test_init_stagger_scheduling(tmp_path: Path) -> None:
    delays: list[float] = []

    async def fake_sleep(d: float) -> None:
        delays.append(d)

    urls = [
        "https://example.com/story1/ch1",
        "https://example.com/story2/ch1",
        "https://example.com/story3/ch1",
    ]

    profile = SiteProfile(
        domain="example.com",
        profile_version=3,
        content_selector="div.chapter-content",
        title_selector="h1.title",
    )
    prof_store = ProfileStore(tmp_path / "site_profiles.json")
    await prof_store.save(profile)
    prog_store = ProgressStore(tmp_path / "progress")

    class FakeSession:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        async def run(self) -> StoryState:
            return StoryState(story_key="test", completed=True)

    with patch("cao_text.web.runner.ScrapeSession", FakeSession), \
         patch("cao_text.web.runner.resolve_start_url", AsyncMock(side_effect=lambda u, **kw: (u, PageClassificationOutput(page_type="chapter")))):
        results = await run_web_tasks(
            urls,
            pool=object(),
            profile_store=prof_store,
            progress_store=prog_store,
            init_stagger=1.5,
            sleep_fn=fake_sleep,
        )

    assert len(results) == 3
    # delays ghi nhận: task 0 không sleep, task 1 sleep 1.5, task 2 sleep 3.0
    assert delays == [1.5, 3.0]


@pytest.mark.asyncio
async def test_sequential_learning_lock_same_domain(tmp_path: Path) -> None:
    """Xác nhận 2 truyện cùng domain chưa có profile: chỉ học 1 lần duy nhất."""
    prof_store = ProfileStore(tmp_path / "site_profiles.json")
    prog_store = ProgressStore(tmp_path / "progress")
    learn_calls = 0

    class FakeLearningResult:
        def __init__(self) -> None:
            self.profile = SiteProfile(
                domain="example.org",
                profile_version=3,
                content_selector="div.chapter-content",
                title_selector="h1",
            )
            self.verification = None

    async def fake_learn_site(*args: Any, **kwargs: Any) -> FakeLearningResult:
        nonlocal learn_calls
        learn_calls += 1
        # Giả lập học mất 0.05s
        await asyncio.sleep(0.05)
        res = FakeLearningResult()
        # Lưu vào store
        await prof_store.save(res.profile)
        return res

    class FakeSession:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        async def run(self) -> StoryState:
            return StoryState(story_key="test", completed=True)

    urls = [
        "https://example.org/novel1/1",
        "https://example.org/novel2/1",
    ]

    with patch("cao_text.web.runner.learn_site", side_effect=fake_learn_site), \
         patch("cao_text.web.runner.ScrapeSession", FakeSession), \
         patch("cao_text.web.runner.resolve_start_url", AsyncMock(side_effect=lambda u, **kw: (u, PageClassificationOutput(page_type="chapter")))):
        results = await run_web_tasks(
            urls,
            pool=object(),
            profile_store=prof_store,
            progress_store=prog_store,
            ai_provider=object(),  # Fake LLMProvider
            init_stagger=0.0,
        )

    assert len(results) == 2
    # Chỉ gọi learn_site ĐÚNG 1 LẦN cho cả 2 truyện cùng domain!
    assert learn_calls == 1


@pytest.mark.asyncio
async def test_run_novel_task_full_flow(tmp_path: Path) -> None:
    prof_store = ProfileStore(tmp_path / "site_profiles.json")
    profile = SiteProfile(
        domain="royalroad.com",
        profile_version=3,
        content_selector="div.chapter-inner",
        title_selector="h1.font-white",
    )
    await prof_store.save(profile)
    prog_store = ProgressStore(tmp_path / "progress")

    # Đoạn văn phong phú > 300 ký tự để process_page nhận diện là văn xuôi hợp lệ
    html = """
    <html><body>
      <h1 class="font-white">Chapter 1: The Beginning</h1>
      <div class="chapter-inner">
        <p>The dawn broke over the silent valley, casting long shadows across the ancient stone ruins that had stood for centuries.</p>
        <p>Arthur adjusted his heavy leather travel cloak against the bitter morning wind, watching the horizon with careful vigilance.</p>
        <p>Every step forward carried the weight of destiny, a path forged through countless trials and whispered prophecies of old.</p>
        <p>He drew his weathered sword and breathed in the cold mountain air, ready to face whatever perils lay ahead in the deep wilderness.</p>
      </div>
    </body></html>
    """
    url = "https://royalroad.com/fiction/1/ch1"
    prefetched = [(url, html)]
    run_cfg = RunConfig(output_dir=str(tmp_path / "output"))

    done_chapters = 0

    def on_done() -> None:
        nonlocal done_chapters
        done_chapters += 1

    state = await run_novel_task(
        url,
        index=0,
        pool=object(),
        profile_store=prof_store,
        progress_store=prog_store,
        run_config=run_cfg,
        prefetched_chapters=prefetched,
        on_chapter_done=on_done,
    )

    assert state.chapter_count == 1
    assert done_chapters == 1


@pytest.mark.asyncio
async def test_run_web_tasks_cancelled(tmp_path: Path) -> None:
    prof_store = ProfileStore(tmp_path / "site_profiles.json")

    async def fake_sleep(d: float) -> None:
        raise asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        await run_web_tasks(
            ["https://example.com/1", "https://example.com/2"],
            pool=object(),
            profile_store=prof_store,
            init_stagger=1.0,
            sleep_fn=fake_sleep,
        )


# ── Task 5.6: Test bộ lọc Windows, đóng pool và Index Auto-Heal ───────────────


def test_silence_windows_transport_errors() -> None:
    """Kiểm tra handler bắt lỗi transport/pipe trên Windows mà không làm crash."""
    loop = asyncio.new_event_loop()
    try:
        delegated = []

        def custom_handler(_l: Any, context: dict[str, Any]) -> None:
            delegated.append(context)

        loop.set_exception_handler(custom_handler)
        silence_windows_transport_errors(loop)

        active_handler = loop.get_exception_handler()
        assert active_handler is not None

        # 1. Lỗi transport/pipe -> bị lọc bỏ (không delegate)
        pipe_context = {
            "message": "Fatal write error on pipe transport",
            "exception": RuntimeError("I/O operation on closed pipe"),
        }
        active_handler(loop, pipe_context)
        assert len(delegated) == 0

        # 2. Lỗi thực sự -> được delegate bình thường
        real_context = {
            "message": "Real unhandled error",
            "exception": ValueError("critical failure"),
        }
        active_handler(loop, real_context)
        assert len(delegated) == 1
        assert delegated[0]["exception"].args[0] == "critical failure"
    finally:
        loop.close()


@pytest.mark.asyncio
async def test_close_pools_normal_and_timeout() -> None:
    """Xác nhận đóng pool an toàn và không treo khi timeout."""
    pool = AsyncMock()
    pw_pool = AsyncMock()

    # 1. Đóng bình thường
    await close_pools(pool, pw_pool, timeout=2.0)
    pool.close_all.assert_awaited_once()
    pw_pool.close.assert_awaited_once()

    # 2. Đóng bị treo (giả lập await vô tận) -> thoát an toàn sau timeout
    hanging_pool = AsyncMock()

    async def hanging_close() -> None:
        await asyncio.sleep(10.0)

    hanging_pool.close_all.side_effect = hanging_close
    await close_pools(hanging_pool, None, timeout=0.05)


@pytest.mark.asyncio
async def test_run_web_tasks_ctrl_c_and_pool_cleanup(tmp_path: Path) -> None:
    """Khi bị Ctrl+C: re-raise CancelledError và vẫn đóng pools trong finally."""
    prof_store = ProfileStore(tmp_path / "site_profiles.json")
    pool = AsyncMock()
    pool.is_cf_domain = lambda _d: False
    pw_pool = AsyncMock()

    async def cancel_sleep(d: float) -> None:
        raise asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        await run_web_tasks(
            ["https://example.com/novel/1", "https://example.com/novel/2"],
            pool=pool,
            pw_pool=pw_pool,
            profile_store=prof_store,
            init_stagger=1.0,
            sleep_fn=cancel_sleep,
            close_pools_on_finish=True,
        )

    # Đảm bảo pool được đóng ngay cả khi tác vụ bị cancel
    pool.close_all.assert_awaited_once()
    pw_pool.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_heal_missing_indexes(tmp_path: Path) -> None:
    """Khắc phục hệ quả Ctrl+C: tự động regenerate 0000_Index.md bị thiếu."""
    novels_dir = tmp_path / "Novels"
    novels_dir.mkdir()

    # Folder 1: Có chapter nhưng thiếu Index
    story1 = novels_dir / "Story_One"
    story1.mkdir()
    (story1 / "0001_Chap_1.md").write_text("---\ntitle: Chap 1\n---\nNội dung chương 1", encoding="utf-8")
    (story1 / "0002_Chap_2.md").write_text("---\ntitle: Chap 2\n---\nNội dung chương 2", encoding="utf-8")

    # Folder 2: Đã có Index
    story2 = novels_dir / "Story_Two"
    story2.mkdir()
    (story2 / "0001_Chap_1.md").write_text("---\ntitle: Chap 1\n---\nNội dung", encoding="utf-8")
    (story2 / "0000_Index.md").write_text("# Existing Index", encoding="utf-8")

    # Folder 3: Folder rỗng không có chương
    story3 = novels_dir / "Empty_Story"
    story3.mkdir()

    healed_count = await heal_missing_indexes(novels_dir)
    assert healed_count == 1

    # Story 1 đã được tạo index
    idx1 = story1 / "0000_Index.md"
    assert idx1.exists()
    content1 = idx1.read_text(encoding="utf-8")
    assert "Story One" in content1
    assert "0001_Chap_1.md" in content1
    assert "0002_Chap_2.md" in content1

    # Story 2 không bị ghi đè
    idx2 = story2 / "0000_Index.md"
    assert idx2.read_text(encoding="utf-8") == "# Existing Index"


@pytest.mark.asyncio
async def test_scrape_session_ctrl_c_saves_progress_shield(tmp_path: Path) -> None:
    """Xác nhận khi Ctrl+C giữa vòng lặp, progress_store.save_state được bảo vệ bằng shield."""
    prog_store = ProgressStore(tmp_path / "progress")
    prof_store = ProfileStore(tmp_path / "site_profiles.json")
    profile = SiteProfile(
        domain="example.org",
        profile_version=3,
        content_selector="div.content",
    )
    await prof_store.save(profile)

    session = ScrapeSession(
        start_url="https://example.org/ch1",
        profile=profile,
        pool=object(),
        progress_store=prog_store,
        profile_store=prof_store,
    )

    # Giả lập step() ném CancelledError
    with patch.object(session, "step", AsyncMock(side_effect=asyncio.CancelledError)):
        with pytest.raises(asyncio.CancelledError):
            await session.run()

    # Trạng thái đã được lưu xuống disk trong asyncio.shield
    saved_state = await prog_store.load_state(session.story_key)
    assert saved_state is not None
    assert saved_state.start_url == "https://example.org/ch1"
