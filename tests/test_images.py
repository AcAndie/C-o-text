"""tests/test_images.py — Unit test cho package cao_text.images.

Kiểm tra:
  - detect_image_extension: Content-Type và magic bytes signature.
  - WebImageFetcher: tải ảnh qua mock pool, giới hạn dung lượng, atomic save.
  - EpubImageExtractor: 4 chiến lược giải quyết href và basename fallback.
  - apply_image_stage: obsidian (link nội bộ / fallback link gốc), translate ([IMAGE: alt]), raw (xóa bỏ).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from cao_text.images import (
    EpubImageExtractor,
    WebImageFetcher,
    apply_image_stage,
    detect_image_extension,
)
from cao_text.models import ImageRef, RunConfig

# ── Helper Classes / Mocks ───────────────────────────────────────────────────

class MockSessionPool:
    """Mock DomainSessionPool cho WebImageFetcher."""

    def __init__(self, responses: dict[str, tuple[int, bytes, str | None]]) -> None:
        self.responses = responses

    async def fetch_bytes(
        self, url: str, timeout: int = 30
    ) -> tuple[int, bytes, str | None]:
        if url in self.responses:
            return self.responses[url]
        return 404, b"", None


class MockEpubItem:
    """Mock EpubItem."""

    def __init__(self, name: str, content: bytes) -> None:
        self.name = name
        self.content = content

    def get_name(self) -> str:
        return self.name

    def get_content(self) -> bytes:
        return self.content


class MockEpubBook:
    """Mock EpubBook cho EpubImageExtractor."""

    def __init__(self, items: dict[str, MockEpubItem]) -> None:
        self.items = items

    def get_item_with_href(self, href: str) -> MockEpubItem | None:
        return self.items.get(href)

    def get_items_of_type(self, item_type: Any) -> list[MockEpubItem]:
        return list(self.items.values())


# ── Tests ────────────────────────────────────────────────────────────────────

def test_detect_image_extension() -> None:
    # 1. Từ Content-Type
    assert detect_image_extension("image/png", b"") == ".png"
    assert detect_image_extension("image/jpeg; charset=utf-8", b"") == ".jpg"
    assert detect_image_extension("image/webp", b"") == ".webp"
    assert detect_image_extension("image/gif", b"") == ".gif"

    # 2. Từ Magic Bytes
    assert detect_image_extension(None, b"\xff\xd8\xff\xe0") == ".jpg"
    assert detect_image_extension(None, b"\x89PNG\r\n\x1a\n") == ".png"
    assert detect_image_extension(None, b"RIFF\x00\x00\x00\x00WEBPVP8 ") == ".webp"
    assert detect_image_extension(None, b"GIF89a\x01\x00") == ".gif"

    # 3. Fallback mặc định
    assert detect_image_extension(None, b"unknown binary data") == ".jpg"


@pytest.mark.asyncio
async def test_web_image_fetcher(tmp_path: Path) -> None:
    png_data = b"\x89PNG\r\n\x1a\n" + b"fake png data"
    oversize_data = b"x" * (6 * 1024 * 1024)  # 6MB > 5MB

    pool = MockSessionPool({
        "https://site.org/ok.png": (200, png_data, "image/png"),
        "https://site.org/fail_404.jpg": (404, b"", None),
        "https://site.org/oversize.jpg": (200, oversize_data, "image/jpeg"),
    })

    fetcher = WebImageFetcher(pool, chapter_index=1)
    refs = [
        ImageRef(original_url="https://site.org/ok.png", position_marker="IMG_PLACEHOLDER_0"),
        ImageRef(original_url="https://site.org/fail_404.jpg", position_marker="IMG_PLACEHOLDER_1"),
        ImageRef(original_url="https://site.org/oversize.jpg", position_marker="IMG_PLACEHOLDER_2"),
    ]

    res = await fetcher.fetch_batch(refs, tmp_path)
    # Ảnh 1: thành công
    assert res[0].local_path == "images/ch_0001_0.png"
    saved_file = tmp_path / "images" / "ch_0001_0.png"
    assert saved_file.exists()
    assert saved_file.read_bytes() == png_data

    # Ảnh 2: 404 -> None
    assert res[1].local_path is None

    # Ảnh 3: Quá dung lượng 5MB -> None
    assert res[2].local_path is None


@pytest.mark.asyncio
async def test_epub_image_extractor(tmp_path: Path) -> None:
    jpg_data = b"\xff\xd8\xff\xe0" + b"fake jpg data"

    # Sách có 2 ảnh: một có đường dẫn OEBPS/Images/pic1.jpg, một có cover.jpg
    book = MockEpubBook({
        "OEBPS/Images/pic1.jpg": MockEpubItem("OEBPS/Images/pic1.jpg", jpg_data),
        "OPS/cover.jpg": MockEpubItem("OPS/cover.jpg", jpg_data),
    })

    extractor = EpubImageExtractor(book, chapter_index=5)

    refs = [
        # Strategy 2: Prefix OEBPS/
        ImageRef(original_url="Images/pic1.jpg", position_marker="IMG_PLACEHOLDER_0"),
        # Strategy 3 & 4: Basename fallback cover.jpg từ ../OPS/cover.jpg
        ImageRef(original_url="../other_dir/cover.jpg", position_marker="IMG_PLACEHOLDER_1"),
        # Không tồn tại
        ImageRef(original_url="missing.jpg", position_marker="IMG_PLACEHOLDER_2"),
    ]

    res = await extractor.fetch_batch(refs, tmp_path)
    assert res[0].local_path == "images/ch_0005_0.jpg"
    assert (tmp_path / "images" / "ch_0005_0.jpg").exists()

    assert res[1].local_path == "images/ch_0005_1.jpg"
    assert (tmp_path / "images" / "ch_0005_1.jpg").exists()

    assert res[2].local_path is None


@pytest.mark.asyncio
async def test_apply_image_stage_obsidian_mode(tmp_path: Path) -> None:
    content = (
        "Paragraph 1\n\n"
        "![Image 1](IMG_PLACEHOLDER_0)\n\n"
        "Paragraph 2\n\n"
        "![Image 2](IMG_PLACEHOLDER_1)"
    )

    refs = [
        ImageRef(
            original_url="https://site.org/img1.png",
            alt_text="Image 1",
            position_marker="IMG_PLACEHOLDER_0",
        ),
        ImageRef(
            original_url="https://site.org/img2_failed.png",
            alt_text="Image 2",
            position_marker="IMG_PLACEHOLDER_1",
        ),
    ]

    # Giả lập strategy tải thành công ảnh 1, ảnh 2 thất bại
    class FakeStrategy:
        async def fetch_batch(self, batch_refs: list[ImageRef], out: Any) -> list[ImageRef]:
            batch_refs[0].local_path = "images/ch_0001_0.png"
            batch_refs[1].local_path = None
            return batch_refs

    cfg = RunConfig(output_mode="obsidian", download_images=True)
    res = await apply_image_stage(
        content,
        refs,
        strategy=FakeStrategy(),  # type: ignore[arg-type]
        run_config=cfg,
        out_dir=tmp_path,
        chapter_num=1,
    )

    # Ảnh 1 thành công -> thay bằng local_path
    assert "![Image 1](images/ch_0001_0.png)" in res
    # Ảnh 2 thất bại -> fallback giữ original_url
    assert "![Image 2](https://site.org/img2_failed.png)" in res


@pytest.mark.asyncio
async def test_apply_image_stage_translate_mode(tmp_path: Path) -> None:
    content = (
        "Paragraph 1\n\n"
        "![Illustration](IMG_PLACEHOLDER_0)\n\n"
        "Paragraph 2"
    )
    refs = [
        ImageRef(
            original_url="https://site.org/img.png",
            alt_text="Illustration",
            position_marker="IMG_PLACEHOLDER_0",
        )
    ]

    cfg = RunConfig(output_mode="translate", download_images=False, image_placeholder=True)
    res = await apply_image_stage(content, refs, strategy=None, run_config=cfg, out_dir=tmp_path, chapter_num=1)

    assert "[IMAGE: Illustration]" in res
    assert "IMG_PLACEHOLDER_0" not in res


@pytest.mark.asyncio
async def test_apply_image_stage_raw_mode(tmp_path: Path) -> None:
    content = (
        "Paragraph 1\n\n"
        "![Illustration](IMG_PLACEHOLDER_0)\n\n"
        "Paragraph 2"
    )
    refs = [
        ImageRef(
            original_url="https://site.org/img.png",
            alt_text="Illustration",
            position_marker="IMG_PLACEHOLDER_0",
        )
    ]

    cfg = RunConfig(output_mode="raw", download_images=False, image_placeholder=False)
    res = await apply_image_stage(content, refs, strategy=None, run_config=cfg, out_dir=tmp_path, chapter_num=1)

    assert "[IMAGE:" not in res
    assert "Illustration" not in res
    assert "IMG_PLACEHOLDER_0" not in res
    assert "Paragraph 1\n\n\n\nParagraph 2" in res or "Paragraph 1\n\n" in res
