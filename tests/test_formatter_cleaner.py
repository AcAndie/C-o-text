"""Unit tests cho cao_text.html.formatter và cao_text.html.cleaner.

Kiểm tra:
  - MarkdownFormatter (headings, bold/italic, tables, dl, images, escape)
  - extract_plain_text
  - clean_extracted_content (8 pass + trần an toàn 60%)
  - strip_nav_edges
  - strip_duplicate_title_header
"""
from __future__ import annotations

from bs4 import BeautifulSoup

from cao_text.html.cleaner import (
    clean_extracted_content,
    strip_duplicate_title_header,
    strip_nav_edges,
)
from cao_text.html.formatter import (
    MarkdownFormatter,
    extract_plain_text,
    resolve_image_url,
)
from cao_text.models import FormattingRules

# ── MarkdownFormatter Tests ───────────────────────────────────────────────────

def test_formatter_paragraphs_and_headings() -> None:
    html = """
    <div>
      <h1>Chapter 1: Awaken</h1>
      <p>The dawn was breaking across the shattered horizon.</p>
      <p>He stood up slowly.</p>
    </div>
    """
    soup = BeautifulSoup(html, "html.parser").find("div")
    formatter = MarkdownFormatter()
    md, images = formatter.format(soup)

    assert "# Chapter 1: Awaken" in md
    assert "The dawn was breaking across the shattered horizon." in md
    assert "He stood up slowly." in md
    assert len(images) == 0


def test_formatter_bold_italic_and_escape() -> None:
    # Test CommonMark emphasis whitespace push & literal character escaping
    html = """
    <div>
      <p>He saw <strong>strong power </strong> and <em>faint light </em> in the distance.</p>
      <p>System message: [Lv 5] Goblin King appeared! Censor: *****</p>
    </div>
    """
    soup = BeautifulSoup(html, "html.parser").find("div")
    formatter = MarkdownFormatter()
    md, _ = formatter.format(soup)

    # Whitespace pushed outside markers
    assert "**strong power** " in md
    assert "*faint light* " in md

    # Literal brackets and asterisks escaped
    assert r"\[Lv 5\]" in md
    assert r"\*\*\*\*\*" in md


def test_formatter_table_and_dl() -> None:
    html = """
    <div>
      <table>
        <tr><th>Attr</th><th>Value</th></tr>
        <tr><td>Strength</td><td>18</td></tr>
        <tr><td>Agility</td><td>15</td></tr>
      </table>
      <dl>
        <dt>HP</dt><dd>150/150</dd>
        <dt>MP</dt><dd>80/80</dd>
      </dl>
    </div>
    """
    soup = BeautifulSoup(html, "html.parser").find("div")
    formatter = MarkdownFormatter()
    md, _ = formatter.format(soup)

    # Table format
    assert "| Attr | Value |" in md
    assert "| Strength | 18 |" in md

    # DL converted to 2-col table
    assert "| HP | 150/150 |" in md
    assert "| MP | 80/80 |" in md


def test_formatter_images() -> None:
    html = """
    <div>
      <p>Before illustration.</p>
      <img src="/images/map.png" alt="World Map" />
      <p>After illustration.</p>
    </div>
    """
    soup = BeautifulSoup(html, "html.parser").find("div")
    formatter = MarkdownFormatter()
    md, images = formatter.format(soup, base_url="https://novel.org/ch1")

    assert len(images) == 1
    assert images[0].original_url == "https://novel.org/images/map.png"
    assert images[0].alt_text == "World Map"
    assert images[0].position_marker == "IMG_PLACEHOLDER_0"

    assert "![World Map](IMG_PLACEHOLDER_0)" in md
    assert '<div align="center">' in md


def test_formatter_rules_safety_and_pydantic() -> None:
    # Không crash khi truyền None hoặc Pydantic FormattingRules
    rules = FormattingRules(bold_italic=False, hr_dividers=False)
    formatter = MarkdownFormatter(rules)

    html = "<div><p><b>Bold text</b></p><hr/></div>"
    soup = BeautifulSoup(html, "html.parser").find("div")
    md, _ = formatter.format(soup)

    # bold_italic=False -> không wrap **
    assert "**" not in md
    assert "Bold text" in md


def test_extract_plain_text() -> None:
    html = """
    <div class="content">
      <h2>Section</h2>
      <p>First paragraph.</p>
      <br/>
      <p>Second paragraph.</p>
    </div>
    """
    soup = BeautifulSoup(html, "html.parser").find("div")
    text = extract_plain_text(soup)

    assert "Section" in text
    assert "First paragraph." in text
    assert "Second paragraph." in text


def test_resolve_image_url() -> None:
    soup = BeautifulSoup('<img data-src="/cover.jpg" />', "html.parser").find("img")
    assert resolve_image_url(soup, "https://example.com") == "https://example.com/cover.jpg"

    soup_base64 = BeautifulSoup('<img src="data:image/png;base64,123" />', "html.parser").find("img")
    assert resolve_image_url(soup_base64, "https://example.com") is None


# ── Cleaner Tests ─────────────────────────────────────────────────────────────

def test_cleaner_raw_script_and_unicode_blanks() -> None:
    long_prose = ("This is a long chapter paragraph filled with interesting novel story.\n" * 10)
    text = f"""
    <script type="text/javascript">window.ad = 123;</script>
    ⠀
    {long_prose}
    """
    cleaned = clean_extracted_content(text)
    assert "<script" not in cleaned
    assert "⠀" not in cleaned  # U+2800 removed
    assert "This is a long chapter paragraph" in cleaned


def test_cleaner_settings_and_ui_navigation() -> None:
    long_prose = ("The sword sliced cleanly through the monstrous armor of the beast.\n" * 12)
    text = f"""
    Reading Settings
    Font Size
    Theme (Dark)
    Line Spacing
    {long_prose}
    Report Chapter
    Vote for this chapter
    """
    cleaned = clean_extracted_content(text)
    assert "Reading Settings" not in cleaned
    assert "Font Size" not in cleaned
    assert "Report Chapter" not in cleaned
    assert "Vote for this chapter" not in cleaned
    assert "The sword sliced cleanly" in cleaned


def test_cleaner_status_blocks() -> None:
    long_prose = ("He examined his newly acquired attributes in the quiet room.\n" * 8)
    text = f"""
    {long_prose}
    **Strength:** 25
    **Agility:** 19
    **Intelligence:** 30
    **Health:** 350/350
    """
    cleaned = clean_extracted_content(text)
    assert "> [!info]+ Status" in cleaned
    assert "> **Strength:** 25" in cleaned
    assert "> **Health:** 350/350" in cleaned


def test_cleaner_broken_bold() -> None:
    text = "The system announced **Level Up: ** and gave 5 stat points." + ("\nLong prose sentence here." * 10)
    cleaned = clean_extracted_content(text)
    assert "**Level Up:** " in cleaned


def test_cleaner_safety_ceiling() -> None:
    # Nếu cắt quá 60% -> giữ nguyên bản gốc để tránh mất chữ thật (§6.4)
    original = "Short introductory text that might trigger some aggressive strip." + ("\nNormal prose." * 10)
    # Tạo văn bản mà phần bị strip chiếm hơn 65%
    huge_noise = "\n".join(["Report Chapter", "Vote for this chapter"] * 30)
    text = original + "\n" + huge_noise

    cleaned = clean_extracted_content(text)
    # Phải trả về text hoặc candidate đáp ứng trần an toàn
    assert len(cleaned) >= len(text) * 0.40


def test_strip_nav_edges() -> None:
    # Tạo text có lặp lại navigation header và footer
    top_nav = [
        "Prev Chapter",
        "Next Chapter",
        "[ 1,520 words ]",
        "",
    ]
    prose = [f"Paragraph line {i} of the chapter story narrative text." for i in range(20)]
    bot_nav = [
        "",
        "Prev Chapter",
        "Next Chapter",
        "[ 1,520 words ]",
    ]
    text = "\n".join(top_nav + prose + bot_nav)

    stripped = strip_nav_edges(text)
    assert "Prev Chapter" not in stripped
    assert "[ 1,520 words ]" not in stripped
    assert "Paragraph line 0" in stripped
    assert "Paragraph line 19" in stripped


def test_strip_duplicate_title_header() -> None:
    content = "Chapter 42: The Awakening\n\nHe opened his eyes."
    title = "Chapter 42: The Awakening"
    cleaned = strip_duplicate_title_header(content, title)
    assert cleaned.startswith("He opened his eyes.")

    # Với title có markdown heading
    content_md = "### Chapter 42: The Awakening\n\nHe opened his eyes."
    cleaned_md = strip_duplicate_title_header(content_md, title)
    assert cleaned_md.startswith("He opened his eyes.")
