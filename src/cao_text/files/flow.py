"""flow.py — Luồng xử lý file hợp nhất dùng chung cho cả EPUB và TXT (Task 6.1)."""
from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Callable, Coroutine
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from ebooklib import epub

from cao_text.files.epub import extract_story_name_from_epub, read_epub_documents
from cao_text.files.txt import extract_story_name_from_txt, read_txt_documents
from cao_text.html.ads import AdsFilter, compute_auto_threshold
from cao_text.images.epub import EpubImageExtractor
from cao_text.images.stage import apply_image_stage
from cao_text.models import CleanedChapter, FileSpec, RawDocument, RunConfig
from cao_text.writers.factory import build_writer
from cao_text.writers.nav_injector import inject_nav_and_index
from cao_text.writers.obsidian import ObsidianWriter, slugify_filename

if TYPE_CHECKING:
    from cao_text.ai.provider import LLMProvider

logger = logging.getLogger(__name__)

URL_PATTERN = re.compile(r"^https?://", re.IGNORECASE)


def detect_input_type(path_or_file: str | Path) -> Literal["web", "epub", "txt"]:
    """Nhận diện loại input từ đường dẫn file.

    Quy tắc:
      *.epub                     → "epub"
      *.txt có dòng đầu là URL   → "web" (file links.txt)
      *.txt nội dung văn bản     → "txt"
      khác                       → "web" (backward compat)
    """
    p = Path(path_or_file)
    suffix = p.suffix.lower()

    if suffix == ".epub":
        return "epub"

    if suffix == ".txt":
        try:
            with open(p, encoding="utf-8") as f:
                for _ in range(5):
                    line = f.readline()
                    if not line:
                        break
                    line = line.strip()
                    if not line or line.startswith("#") or line.lower().startswith("!relearn"):
                        continue
                    if URL_PATTERN.match(line):
                        return "web"
                    return "txt"
        except Exception:
            return "txt"
        return "txt"

    return "web"


def _build_chapter_from_file_doc(
    doc: RawDocument,
    run_config: RunConfig,
    story_name: str,
    ads_filter: AdsFilter | None = None,
    source: Literal["epub", "txt"] = "epub",
) -> CleanedChapter | None:
    """Chuyển đổi RawDocument thành CleanedChapter hoàn chỉnh.

    Trích xuất trực tiếp từ thẻ body theo kiến trúc v1.0.17 (§6.6), giải quyết
    tiêu đề theo thứ tự ưu tiên (matter -> non-numeric TOC -> h1/extract -> numeric -> fallback),
    lọc quảng cáo Pass 1 và loại bỏ dòng đầu nếu trùng lặp tiêu đề.
    """
    from cao_text.extract.title import extract_title
    from cao_text.html.cleaner import clean_extracted_content
    from cao_text.html.filter import prepare_soup
    from cao_text.html.formatter import MarkdownFormatter

    soup = prepare_soup(doc.html, remove_selectors=[])
    body_tag = soup.find("body") or soup
    content, images = MarkdownFormatter({}).format(body_tag, base_url="")
    if not content or not content.strip():
        return None

    content = clean_extracted_content(content)

    # Pass 1 AdsFilter: lọc các từ khóa quảng cáo đã biết
    if ads_filter is not None:
        content = ads_filter.filter(content, chapter_url="")

    # Thứ tự ưu tiên giải quyết tiêu đề (§6.6 & v1.0.14):
    #   1. doc_kind == "matter" → "Front Matter"
    #   2. TOC entry title (không phải thuần số) → dùng trực tiếp
    #   3. Tiêu đề trích xuất từ HTML (thường là thẻ <h1>)
    #   4. TOC entry title thuần số → "Chapter N"
    #   5. Mặc định → "Chapter {chapter_index}"
    doc_meta = dict(doc.metadata or {})
    doc_kind = doc_meta.get("kind", "chapter")
    toc_title = (doc_meta.get("toc_title") or "").strip()

    if doc_kind == "matter":
        title = "Front Matter"
    elif toc_title and not toc_title.isdigit():
        title = toc_title
    else:
        extracted_title, _ = extract_title(soup, doc.source_path or "")
        if extracted_title:
            title = extracted_title
        elif toc_title:
            title = f"Chapter {toc_title.lstrip('0') or '0'}"
        else:
            title = f"Chapter {doc.chapter_index}"

    # Bỏ dòng đầu nội dung nếu trùng lặp tiêu đề
    content_lines = content.split("\n")
    if content_lines:
        first = content_lines[0].strip().lstrip("#").strip()
        if first and title and first.lower() == title.lower():
            content = "\n".join(content_lines[1:]).lstrip("\n")

    body = f"# {title}\n\n{content}\n"

    metadata: dict[str, Any] = {
        "story_name": story_name,
        "chapter_keyword": "Chapter",
        **doc_meta,
    }

    return CleanedChapter(
        index=doc.chapter_index,
        title=title,
        body_markdown=body,
        images=list(images),
        source_path=doc.source_path,
        metadata=metadata,
    )


async def run_file_flow(
    spec: FileSpec | str | Path,
    run_config: RunConfig | None = None,
    *,
    input_type: Literal["epub", "txt"] | None = None,
    ai_provider: LLMProvider | None = None,
    story_name: str | None = None,
    output_dir: str | Path | None = None,
    on_chapter_done: Callable[[int, str], None | Coroutine[Any, Any, None]] | None = None,
) -> int:
    """Luồng xử lý file hợp nhất cho cả EPUB và TXT (Task 6.1).

    Các bước:
      1. Chuẩn hóa spec và nhận diện input_type (epub | txt).
      2. Lấy tên truyện (Dublin Core cho EPUB, stem cho TXT) và tạo thư mục đích.
      3. Khởi tạo Writer và AdsFilter theo namespace `epub:<slug>` hoặc `txt:<slug>`.
      4. Đọc luồng tài liệu (RawDocument) và xử lý từng chương qua process_page.
      5. Áp dụng ImageStage (Obsidian tải ảnh zip cho EPUB, translate/raw xử lý placeholder).
      6. Quét suspects cạnh chương cho AdsFilter.
      7. Cuối file: tự động học từ khóa quảng cáo vượt ngưỡng và hậu xử lý làm sạch file.
      8. Chèn Index & navigation cho Obsidian nếu cần.
    """
    if isinstance(spec, (str, Path)):
        resolved_cfg = run_config or RunConfig.create_for_mode()
        spec = FileSpec(
            input_path=spec,
            run_config=resolved_cfg,
            input_type=input_type,
            story_name=story_name,
            output_dir=output_dir,
            ai_provider=ai_provider,
        )

    resolved_type = spec.input_type or detect_input_type(spec.input_path)
    if resolved_type not in ("epub", "txt"):
        raise ValueError(
            f"Không hỗ trợ xử lý file với định dạng '{resolved_type}': {spec.input_path}"
        )

    # 1. Đặt tên truyện & thư mục đầu ra
    if spec.story_name:
        final_story_name = spec.story_name
    elif resolved_type == "epub":
        final_story_name = extract_story_name_from_epub(spec.input_path)
    else:
        final_story_name = extract_story_name_from_txt(spec.input_path)

    story_slug = slugify_filename(final_story_name)
    base_out_dir = Path(spec.output_dir or spec.run_config.output_dir)
    out_dir = base_out_dir / story_slug
    out_dir.mkdir(parents=True, exist_ok=True)

    writer = build_writer(str(out_dir), spec.run_config)

    # 2. AdsFilter theo namespace epub:<slug> hoặc txt:<slug> (§6.1)
    domain_key = f"{resolved_type}:{story_slug}"
    ads_filter = AdsFilter.load(domain=domain_key, story_title=final_story_name)

    logger.info(
        "📄 [%s] %r → %s (mode=%s, download_images=%s, ads_domain=%r, %s)",
        resolved_type.upper(),
        final_story_name,
        out_dir,
        spec.run_config.output_mode,
        spec.run_config.download_images,
        domain_key,
        ads_filter.stats,
    )

    # 3. Chuẩn bị tài nguyên đọc tài liệu
    book: epub.EpubBook | None = None
    if resolved_type == "epub":
        book = epub.read_epub(str(spec.input_path))
        doc_stream = read_epub_documents(spec.input_path, ai_provider=spec.ai_provider)
    else:
        doc_stream = read_txt_documents(
            spec.input_path, pattern=spec.pattern, ai_provider=spec.ai_provider
        )

    # 4. Vòng lặp xử lý từng chương
    n_ok = 0
    n_skipped = 0

    async for doc in doc_stream:
        try:
            chapter = _build_chapter_from_file_doc(
                doc=doc,
                run_config=spec.run_config,
                story_name=final_story_name,
                ads_filter=ads_filter,
                source=resolved_type,
            )
        except Exception as e:
            logger.warning(
                "[%s] Lỗi tạo chương %d: %s",
                resolved_type.upper(),
                doc.chapter_index,
                e,
            )
            n_skipped += 1
            continue

        if chapter is None:
            n_skipped += 1
            continue

        # 5. Image stage (EPUB / TXT)
        if chapter.images:
            strategy = (
                EpubImageExtractor(book, chapter.index)
                if (book is not None and resolved_type == "epub")
                else None
            )
            chapter.body_markdown = await apply_image_stage(
                content=chapter.body_markdown,
                image_refs=chapter.images,
                strategy=strategy,
                run_config=spec.run_config,
                out_dir=str(out_dir),
                chapter_num=chapter.index,
            )

        # 6. Ghi file chương
        written_path = await writer.write(chapter)
        n_ok += 1

        # 7. Quét suspects cạnh chương cho AdsFilter
        ads_filter.scan_edges_for_suspects(
            chapter.body_markdown,
            chapter_url="",
            chapter_file=str(written_path),
        )

        if on_chapter_done is not None:
            try:
                cb_res = on_chapter_done(n_ok, chapter.title)
                if asyncio.iscoroutine(cb_res):
                    await cb_res
            except Exception as cb_err:
                logger.debug("on_chapter_done callback failed: %s", cb_err)

        if n_ok % 25 == 0:
            logger.info("   ... %d chapters written", n_ok)

    # 8. Hậu xử lý AdsFilter cuối file (§6.4 & §7.3)
    auto_threshold = compute_auto_threshold(total_chapters=n_ok)
    candidates, _ = ads_filter.get_candidates_by_frequency(
        auto_threshold=auto_threshold,
        min_count=auto_threshold,
        max_results=50,
        total_chapters=n_ok,
    )
    if candidates:
        added = ads_filter.apply_verified(candidates, is_auto=True)
        ads_filter.save()
        removed = AdsFilter.post_process_directory(candidates, str(out_dir))
        logger.info(
            "   🧹 AdsFilter: +%d kws (ngưỡng ≥%d), đã xóa %d dòng từ các file đã ghi",
            added,
            auto_threshold,
            removed,
        )
    else:
        ads_filter.save()

    # 9. Index TOC + Navigation cho Obsidian
    if isinstance(writer, ObsidianWriter):
        should_inject = (
            spec.inject_nav if spec.inject_nav is not None else (resolved_type == "epub")
        )
        if should_inject:
            try:
                n_nav, idx_written = await asyncio.to_thread(
                    inject_nav_and_index, str(out_dir), final_story_name
                )
                idx_msg = " + index" if idx_written else ""
                if n_nav or idx_written:
                    logger.info("   🔗 Nav: %d chapters%s", n_nav, idx_msg)
            except Exception as e:
                logger.warning("[%s] nav_injector failed: %s", resolved_type.upper(), e)

    logger.info(
        "✔ [%s] Hoàn thành: %d chương thành công, %d bỏ qua → %s",
        resolved_type.upper(),
        n_ok,
        n_skipped,
        out_dir,
    )
    return n_ok


__all__ = [
    "FileSpec",
    "RawDocument",
    "detect_input_type",
    "run_file_flow",
]
