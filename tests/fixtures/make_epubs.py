"""
tests/fixtures/make_epubs.py — Tạo 2 file EPUB nhỏ phục vụ test offline:
  1. sample_with_toc.epub: có TOC đầy đủ, có trang divider "Part 1" trước Chapter 2
     (để kiểm tra logic gộp divider vào chương sau).
  2. sample_no_toc_part_divider.epub: không có TOC (book.toc rỗng), có trang
     divider "Part 1" + nội dung chứa ≥5 chương dạng "Chapter N: ..." để
     kiểm tra nhánh no-TOC pattern split.
"""
from __future__ import annotations

from pathlib import Path

from ebooklib import epub

OUT_DIR = Path(__file__).resolve().parent / "epub"


def _make_html(title: str, paragraphs: list[str]) -> bytes:
    body = "\n".join(f"<p>{p}</p>" for p in paragraphs)
    html = (
        "<?xml version='1.0' encoding='utf-8'?>\n"
        "<html xmlns='http://www.w3.org/1999/xhtml'>\n"
        f"<head><title>{title}</title></head>\n"
        f"<body><h1>{title}</h1>\n{body}\n</body>\n"
        "</html>"
    )
    return html.encode("utf-8")


def build_sample_with_toc(out_path: Path) -> None:
    book = epub.EpubBook()
    book.set_identifier("cao-text-fixture-toc-001")
    book.set_title("Chronicles of the Glass Spire")
    book.set_language("en")
    book.add_author("Test Author")

    intro = epub.EpubHtml(title="Introduction", file_name="intro.xhtml", lang="en")
    intro.set_content(
        _make_html(
            "Introduction",
            [
                "This short introduction belongs to the front matter bucket of the novel.",
                "Readers who open the archive will find the history of the Glass Spire recorded here.",
            ],
        )
    )

    ch1 = epub.EpubHtml(
        title="Chapter 1: The First Shard", file_name="chap_01.xhtml", lang="en"
    )
    ch1.set_content(
        _make_html(
            "Chapter 1: The First Shard",
            [
                "High above the salt plains, the Glass Spire caught the first crimson ray of dawn.",
                "Elena knelt beside the fractured mosaic, tracing the silver seam that ran across the stone floor.",
                '"We are not too late," she whispered to the wind, lifting the prism into the light.',
            ],
        )
    )

    part1 = epub.EpubHtml(title="Part 1", file_name="part_01.xhtml", lang="en")
    part1.set_content(_make_html("Part 1", ["Part 1: The Ascent Begins."]))

    ch2 = epub.EpubHtml(
        title="Chapter 2: Beyond the Cloud Gate", file_name="chap_02.xhtml", lang="en"
    )
    ch2.set_content(
        _make_html(
            "Chapter 2: Beyond the Cloud Gate",
            [
                "The spiral staircase wound upward through seven hundred steps of polished obsidian.",
                "At the landing of the Cloud Gate, two stone sentinels stood with their halberds crossed.",
                "Elena pressed the prism against the keystone, and the ancient lock released with a low chime.",
            ],
        )
    )

    ch3 = epub.EpubHtml(
        title="Chapter 3: The Mirror Chamber", file_name="chap_03.xhtml", lang="en"
    )
    ch3.set_content(
        _make_html(
            "Chapter 3: The Mirror Chamber",
            [
                "Inside the chamber, twelve tall mirrors reflected not the room itself, but skies from distant ages.",
                "Each glass panel hummed with a quiet resonance as Elena stepped toward the central dais.",
                "There, resting upon a velvet cushion, lay the compass that pointed toward the lost star.",
            ],
        )
    )

    for item in (intro, ch1, part1, ch2, ch3):
        book.add_item(item)

    book.toc = (
        epub.Link("intro.xhtml", "Introduction", "intro"),
        epub.Link("chap_01.xhtml", "Chapter 1: The First Shard", "ch1"),
        epub.Link("part_01.xhtml", "Part 1", "p1"),
        epub.Link("chap_02.xhtml", "Chapter 2: Beyond the Cloud Gate", "ch2"),
        epub.Link("chap_03.xhtml", "Chapter 3: The Mirror Chamber", "ch3"),
    )
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ["nav", intro, ch1, part1, ch2, ch3]

    out_path.parent.mkdir(parents=True, exist_ok=True)
    epub.write_epub(str(out_path), book)


def build_sample_no_toc_with_divider(out_path: Path) -> None:
    book = epub.EpubBook()
    book.set_identifier("cao-text-fixture-notoc-002")
    book.set_title("Tales of the Iron Valley")
    book.set_language("en")
    book.add_author("Test Author")

    divider = epub.EpubHtml(title="Part 1", file_name="part1_divider.xhtml", lang="en")
    divider.set_content(_make_html("Part 1", ["Part 1"]))

    chapters_text = [
        (
            "Chapter 1: The Forge Awakes",
            [
                "Sparks rose from the great anvil as Master Corvin struck the glowing billet of meteoric iron.",
                "Throughout the valley, the sound of the hammer echoed like a steady winter heartbeat.",
                "Young Rowan watched from the doorway, memorizing every turn of the tongs.",
            ],
        ),
        (
            "Chapter 2: Cold River Crossing",
            [
                "Before noon, the courier arrived with a sealed cylinder ofstamped brass from the border keep.",
                "Rowan strapped the leather satchel across his shoulders and led the grey mare down to the ford.",
                "The river ran swift and dark between banks crusted with early frost.",
            ],
        ),
        (
            "Chapter 3: Watchtower on the Ridge",
            [
                "By dusk, the stone watchtower appeared against the violet sky like a solitary spear.",
                "Captain Vance met him at the timber gate, his cloak dusted with sleet from the northern pass.",
                '"If Master Corvin forged the seal," Vance said, "then the old treaty still holds."',
            ],
        ),
        (
            "Chapter 4: Signals in the Fog",
            [
                "Three blue lanterns were hoisted to the highest parapet as the valley fog rolled over the pines.",
                "Across the gorge, an answering flare flickered twice before vanishing into the mist.",
                "Rowan kept his hand on the hilt of the newly tempered blade at his belt.",
            ],
        ),
        (
            "Chapter 5: Return to the Anvil",
            [
                "When the sun broke over the eastern crest, the riders were already descending the switchback trail.",
                "Back in the smithy, the coals still glowed beneath a blanket of white ash, waiting for the next work.",
                "Rowan set the empty brass cylinder on the bench and reached for the bellows.",
            ],
        ),
    ]

    body_lines: list[str] = []
    for ch_title, paras in chapters_text:
        body_lines.append(f"<p>{ch_title}</p>")
        for p in paras:
            body_lines.append(f"<p>{p}</p>")

    main_doc = epub.EpubHtml(title="Body", file_name="body_all.xhtml", lang="en")
    main_doc.set_content(
        (
            "<?xml version='1.0' encoding='utf-8'?>\n"
            "<html xmlns='http://www.w3.org/1999/xhtml'>\n"
            "<head><title>Tales of the Iron Valley</title></head>\n"
            "<body>\n" + "\n".join(body_lines) + "\n</body>\n</html>"
        ).encode("utf-8")
    )

    book.add_item(divider)
    book.add_item(main_doc)
    # Không tạo TOC (book.toc rỗng) để kiểm tra nhánh no-TOC fallback
    book.toc = ()
    book.spine = [divider, main_doc]

    out_path.parent.mkdir(parents=True, exist_ok=True)
    epub.write_epub(str(out_path), book)


def main() -> None:
    p1 = OUT_DIR / "sample_with_toc.epub"
    p2 = OUT_DIR / "sample_no_toc_part_divider.epub"
    build_sample_with_toc(p1)
    build_sample_no_toc_with_divider(p2)
    print(f"Created: {p1} ({p1.stat().st_size} bytes)")
    print(f"Created: {p2} ({p2.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
