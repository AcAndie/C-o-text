"""tests/test_writers.py — Unit test cho package cao_text.writers.

Kiểm tra:
  - ObsidianWriter: định dạng tên file, frontmatter, paragraph indentation, failed_images.
  - TranslationWriter: NNNN.txt, title dòng 1, strip markdown, [IMAGE: alt].
  - RawWriter: NNNN.txt, title dòng 1, strip markdown, xóa sạch ảnh.
  - build_writer: factory dispatch theo output_mode và xử lý lỗi mode lạ.
  - nav_injector: tạo 0000_Index.md, chèn nav footer, tính idempotent.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from cao_text.models import CleanedChapter, ImageRef, RunConfig
from cao_text.writers import (
    INDEX_FILENAME,
    ObsidianWriter,
    RawWriter,
    TranslationWriter,
    build_writer,
    format_chapter_filename,
    inject_nav_and_index,
    slugify_filename,
)


def test_slugify_filename() -> None:
    assert slugify_filename("Chapter 1: The Beginning") == "Chapter_1_The_Beginning"
    assert slugify_filename("Chương 1: Khởi đầu mới") == "Chương_1_Khởi_đầu_mới"
    assert slugify_filename("CON", max_len=20) == "CON_file"
    assert slugify_filename("Special / ? < > : | * chars") == "Special_chars"


def test_format_chapter_filename() -> None:
    # 1. Có subtitle
    assert format_chapter_filename(23, "Chapter 23: Interlude 1") == "0023_Interlude_1.md"
    # 2. Subtitle có word count artifact
    assert format_chapter_filename(25, "Chapter 25: Enjoying life[ ... words ]") == "0025_Enjoying_life.md"
    # 3. Subtitle là rác (fanfic descriptor) -> fallback chapter keyword + số
    assert format_chapter_filename(1, "Chapter 1, a percy jackson fanfic") == "0001_Chapter1.md"
    # 4. Không có subtitle
    assert format_chapter_filename(23, "Chapter 23") == "0023_Chapter23.md"
    # 5. Tiêu đề không có keyword
    assert format_chapter_filename(1, "Prologue: The Beginning") == "0001_Prologue_The_Beginning.md"
    # 6. Bóc story prefix
    progress = {"story_prefix_strip": "My Novel -", "chapter_keyword": "Chapter"}
    assert format_chapter_filename(5, "My Novel - Chapter 5: Great Battle", progress) == "0005_Great_Battle.md"


@pytest.mark.asyncio
async def test_obsidian_writer_full_flow(tmp_path: Path) -> None:
    cfg = RunConfig(output_mode="obsidian")
    writer = build_writer(tmp_path, cfg)
    assert isinstance(writer, ObsidianWriter)

    chapter = CleanedChapter(
        index=42,
        title="Chapter 42: The Calm",
        body_markdown=(
            "# Header inside body\n\n"
            "This is the first paragraph that should be indented.\n\n"
            "> A blockquote note that should not be indented.\n\n"
            "Second paragraph with **bold** and *italic* text.\n\n"
            "```python\nprint('code block without indent')\n```\n\n"
            "Third paragraph after code."
        ),
        images=[
            ImageRef(original_url="https://site.org/img1.png", local_path="images/0042_01.png", source_type="web"),
            ImageRef(original_url="https://site.org/failed.png", local_path=None, source_type="web"),
        ],
        source_url="https://site.org/ch42",
        metadata={"story_name": "Hero Story", "author": "John Doe", "chapter_keyword": "Chapter"},
    )

    out_file = await writer.write(chapter)
    assert out_file.exists()
    assert out_file.name == "0042_The_Calm.md"

    text = out_file.read_text(encoding="utf-8")
    # Frontmatter
    assert "title: 'Chapter 42: The Calm'" in text
    assert "chapter_index: 42" in text
    assert "source_url: https://site.org/ch42" in text
    assert "story_name: 'Hero Story'" in text
    assert "failed_images: ['https://site.org/failed.png']" in text

    # Indentation: U+2003 em-space trước paragraph thường
    assert "\n This is the first paragraph" in text
    assert "\n Second paragraph" in text
    assert "\n Third paragraph after code" in text
    # Không indent blockquote hoặc code
    assert "\n > A blockquote" not in text
    assert "\n> A blockquote" in text
    assert "\n print('code" not in text


@pytest.mark.asyncio
async def test_translation_writer(tmp_path: Path) -> None:
    cfg = RunConfig(output_mode="translate")
    writer = build_writer(tmp_path, cfg)
    assert isinstance(writer, TranslationWriter)

    chapter = CleanedChapter(
        index=7,
        title="Chapter 7: Dragon's Lair",
        body_markdown=(
            "# Chapter 7: Dragon's Lair\n\n"
            "The **fierce dragon** roared in the cavern!\n\n"
            "![Dragon illustration](images/0007_01.png)\n\n"
            "Click [here](https://site.org) to read *more details*."
        ),
    )

    out_file = await writer.write(chapter)
    assert out_file.name == "0007.txt"

    text = out_file.read_text(encoding="utf-8")
    lines = text.split("\n")
    # Dòng 1: plain title, dòng 2: trống
    assert lines[0] == "Chapter 7: Dragon's Lair"
    assert lines[1] == ""
    # Bỏ Markdown syntax
    assert "The fierce dragon roared in the cavern!" in text
    assert "**fierce dragon**" not in text
    # Ảnh đổi thành [IMAGE: alt]
    assert "[IMAGE: Dragon illustration]" in text
    # Link đổi thành text thuần
    assert "Click here to read more details." in text


@pytest.mark.asyncio
async def test_raw_writer(tmp_path: Path) -> None:
    cfg = RunConfig(output_mode="raw")
    writer = build_writer(tmp_path, cfg)
    assert isinstance(writer, RawWriter)

    chapter = CleanedChapter(
        index=7,
        title="Chapter 7: Dragon's Lair",
        body_markdown=(
            "# Chapter 7: Dragon's Lair\n\n"
            "The **fierce dragon** roared in the cavern!\n\n"
            "![Dragon illustration](images/0007_01.png)\n\n"
            "Click [here](https://site.org) to read *more details*."
        ),
    )

    out_file = await writer.write(chapter)
    assert out_file.name == "0007.txt"

    text = out_file.read_text(encoding="utf-8")
    lines = text.split("\n")
    assert lines[0] == "Chapter 7: Dragon's Lair"
    assert lines[1] == ""
    # Raw mode: ảnh bị xóa hoàn toàn, không có placeholder
    assert "[IMAGE:" not in text
    assert "images/0007_01.png" not in text
    assert "The fierce dragon roared in the cavern!" in text
    assert "Click here to read more details." in text


def test_build_writer_invalid_mode(tmp_path: Path) -> None:
    cfg = RunConfig(output_mode="invalid_mode")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="Unknown output_mode"):
        build_writer(tmp_path, cfg)


def test_nav_injector_and_index(tmp_path: Path) -> None:
    # Chuẩn bị 3 file chương giả lập
    ch1 = tmp_path / "0001_Chapter_1.md"
    ch1.write_text(
        "---\ntitle: 'Chapter 1'\nchapter_index: 1\nstory_name: 'Epic Quest'\nsource_url: https://novel.org/ch1\n---\n\nContent of chapter 1.",
        encoding="utf-8",
    )

    ch2 = tmp_path / "0002_Chapter_2.md"
    ch2.write_text(
        "---\ntitle: 'Chapter 2'\nchapter_index: 2\n---\n\nContent of chapter 2.",
        encoding="utf-8",
    )

    ch3 = tmp_path / "0003_Chapter_3.md"
    ch3.write_text(
        "---\ntitle: 'Chapter 3'\nchapter_index: 3\n---\n\nContent of chapter 3.",
        encoding="utf-8",
    )

    updated_count, index_created = inject_nav_and_index(tmp_path)
    assert updated_count == 3
    assert index_created is True

    # 1. Kiểm tra 0000_Index.md
    index_file = tmp_path / INDEX_FILENAME
    assert index_file.exists()
    index_text = index_file.read_text(encoding="utf-8")
    assert "# Epic Quest" in index_text
    assert "**Chapters**: 3" in index_text
    assert "**Source**: novel.org" in index_text
    assert "1. [Chapter 1](<0001_Chapter_1.md>)" in index_text
    assert "2. [Chapter 2](<0002_Chapter_2.md>)" in index_text
    assert "3. [Chapter 3](<0003_Chapter_3.md>)" in index_text

    # 2. Kiểm tra điều hướng từng chương
    ch1_text = ch1.read_text(encoding="utf-8")
    assert "<!-- nav-bottom -->" in ch1_text
    assert "[🏠 Index](<0000_Index.md>)" in ch1_text
    assert "[0002_Chapter_2 →](<0002_Chapter_2.md>)" in ch1_text
    assert "←" not in ch1_text  # Chương 1 không có nút Prev

    ch2_text = ch2.read_text(encoding="utf-8")
    assert "[← 0001_Chapter_1](<0001_Chapter_1.md>)" in ch2_text
    assert "[🏠 Index](<0000_Index.md>)" in ch2_text
    assert "[0003_Chapter_3 →](<0003_Chapter_3.md>)" in ch2_text

    ch3_text = ch3.read_text(encoding="utf-8")
    assert "[← 0002_Chapter_2](<0002_Chapter_2.md>)" in ch3_text
    assert "[🏠 Index](<0000_Index.md>)" in ch3_text
    assert "→" not in ch3_text  # Chương 3 (cuối) không có nút Next

    # 3. Kiểm tra tính Idempotent (chạy lại không thay đổi gì)
    updated_again, index_again = inject_nav_and_index(tmp_path)
    assert updated_again == 0
    assert index_again is False
