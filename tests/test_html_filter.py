"""Unit tests cho cao_text.html.filter (prepare_soup).

Kiểm tra đầy đủ các layer lọc DOM:
  - Layer 1: Xóa script, style, noscript, iframe
  - Layer 1b: Xóa obfuscated class (không đụng <p>, không xóa text dài)
  - Layer 1c: Xóa phần tử ẩn (hidden, aria-hidden, inline style, semantic class)
  - Layer 2: KNOWN_NOISE_SELECTORS
  - Layer 3: remove_selectors có bảo vệ tổ tiên (NAV-PROTECT)
"""
from __future__ import annotations

from cao_text.html.filter import KNOWN_NOISE_SELECTORS, prepare_soup


def test_prepare_soup_empty_html() -> None:
    soup = prepare_soup("")
    assert soup.get_text() == ""

    soup_spaces = prepare_soup("   \n\t  ")
    assert soup_spaces.get_text() == ""


def test_prepare_soup_always_removed_tags() -> None:
    html = """
    <html>
      <head>
        <script>alert('noise');</script>
        <style>.body { color: red; }</style>
      </head>
      <body>
        <noscript>Please enable JS</noscript>
        <iframe src="https://ads.com"></iframe>
        <p>Real chapter content</p>
      </body>
    </html>
    """
    soup = prepare_soup(html)
    assert soup.find("script") is None
    assert soup.find("style") is None
    assert soup.find("noscript") is None
    assert soup.find("iframe") is None
    assert "Real chapter content" in soup.get_text()


def test_prepare_soup_obfuscated_class() -> None:
    long_hash = "a" * 45  # 45 ký tự alphanumeric
    html = f"""
    <div>
      <span class="{long_hash}">Stolen from RoyalRoad</span>
      <p class="{long_hash}">Real paragraph of the novel that must be kept.</p>
      <div class="{long_hash}">This is a very long real text that exceeds forty characters and should not be stripped.</div>
      <p>Normal text.</p>
    </div>
    """
    soup = prepare_soup(html)

    # Thẻ span chứa watermark ngắn bị xóa
    assert "Stolen from RoyalRoad" not in soup.get_text()

    # Thẻ <p> có class dài KHÔNG bị xóa (quy tắc §6.4 cho RoyalRoad)
    assert "Real paragraph of the novel that must be kept." in soup.get_text()

    # Thẻ có text dài > 40 ký tự KHÔNG bị xóa
    assert "This is a very long real text" in soup.get_text()


def test_prepare_soup_invisible_elements() -> None:
    html = """
    <div>
      <p hidden>Hidden via HTML5 attr</p>
      <div aria-hidden="true">Hidden via aria-hidden</div>
      <span style="display: none;">Hidden via display:none</span>
      <span style="visibility:hidden;">Hidden via visibility:hidden</span>
      <span style="opacity: 0;">Hidden via opacity:0</span>
      <span style="font-size: 0px;">Hidden via font-size:0</span>
      <span style="left: -99999px;">Hidden off-screen</span>
      <p class="sr-only">Screen reader only text</p>
      <div class="d-none">Bootstrap d-none</div>
      <span class="hidden">Tailwind hidden</span>
      <p>Visible chapter text.</p>
    </div>
    """
    soup = prepare_soup(html)
    text = soup.get_text()

    assert "Hidden via HTML5 attr" not in text
    assert "Hidden via aria-hidden" not in text
    assert "Hidden via display:none" not in text
    assert "Hidden via visibility:hidden" not in text
    assert "Hidden via opacity:0" not in text
    assert "Hidden via font-size:0" not in text
    assert "Hidden off-screen" not in text
    assert "Screen reader only text" not in text
    assert "Bootstrap d-none" not in text
    assert "Tailwind hidden" not in text
    assert "Visible chapter text." in text


def test_prepare_soup_known_noise_selectors() -> None:
    assert len(KNOWN_NOISE_SELECTORS) > 0
    assert "#profile_top" in KNOWN_NOISE_SELECTORS

    html = """
    <div>
      <div class="author-note-portlet">Author note sidebar widget</div>
      <div class="comment-container">Comments section</div>
      <div id="profile_top">FFN story metadata</div>
      <div class="reading-settings">Reading settings</div>
      <div class="chapter-content">
        <p>Chapter body</p>
      </div>
    </div>
    """
    soup = prepare_soup(html)
    text = soup.get_text()

    assert "Author note sidebar widget" not in text
    assert "Comments section" not in text
    assert "FFN story metadata" not in text
    assert "Reading settings" not in text
    assert "Chapter body" in text


def test_prepare_soup_contains_pseudo_selector() -> None:
    html = """
    <div class="content">
      <p class="notice">Unauthorized usage: please read at official site.</p>
      <p>Actual story narrative.</p>
    </div>
    """
    soup = prepare_soup(
        html,
        remove_selectors=["p.notice:contains('Unauthorized usage')"],
    )
    text = soup.get_text()

    assert "Unauthorized usage" not in text
    assert "Actual story narrative." in text


def test_prepare_soup_ancestor_protection() -> None:
    html = """
    <div id="wrapper" class="site-main">
      <div class="sidebar">Ads sidebar</div>
      <div class="article-body">
        <h1 class="chapter-title">Chapter 1: The Beginning</h1>
        <div class="chapter-content">
          <p>Paragraph 1.</p>
          <p>Paragraph 2.</p>
        </div>
        <a class="next-btn" href="/ch2">Next Chapter</a>
      </div>
    </div>
    """
    # Profile có remove_selectors xóa "div.site-main" (chứa toàn bộ trang) và ".sidebar"
    # Nhờ bảo vệ tổ tiên (NAV-PROTECT), "div.site-main" và "div.article-body" KHÔNG bị xóa
    # vì là cha của content/title/next selector.
    soup = prepare_soup(
        html,
        remove_selectors=["div.site-main", ".sidebar"],
        content_selector=".chapter-content",
        title_selector="h1.chapter-title",
        next_selector="a.next-btn",
    )
    text = soup.get_text()

    assert "Ads sidebar" not in text
    assert "Chapter 1: The Beginning" in text
    assert "Paragraph 1." in text
    assert "Paragraph 2." in text
    assert soup.select_one("a.next-btn") is not None


def test_prepare_soup_invalid_selector_handled() -> None:
    html = "<div><p>Valid text</p></div>"
    # Selector syntax sai không làm crash prepare_soup
    soup = prepare_soup(html, remove_selectors=["div:invalid[[[selector"])
    assert "Valid text" in soup.get_text()
