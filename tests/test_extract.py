"""Unit tests cho cao_text.extract (content, title, nav, validate, page.process_page).

Chạy hoàn toàn OFFLINE 100% bằng dữ liệu HTML mẫu.
"""
from __future__ import annotations

from bs4 import BeautifulSoup

from cao_text.extract import (
    PageResult,
    detect_page_type,
    extract_content,
    extract_title,
    find_next_url,
    process_page,
    validate_content,
)
from cao_text.models import SiteProfile

# ── Content Extraction Tests ──────────────────────────────────────────────────

def test_extract_content_via_selector() -> None:
    body_text = "<p>Real chapter content paragraph that is long enough to satisfy minimum characters threshold.</p>" * 5
    html = f"""
    <div>
      <div id="noise">Sidebar ads</div>
      <div class="chap-body">{body_text}</div>
    </div>
    """
    soup = BeautifulSoup(html, "html.parser")
    profile = SiteProfile(domain="example.com", content_selector="div.chap-body")

    content, method, images, sel = extract_content(soup, "https://example.com/ch1", profile)
    assert content is not None
    assert method == "selector:div.chap-body"
    assert sel == "div.chap-body"
    assert "Real chapter content" in content


def test_extract_content_via_json_ld() -> None:
    article_text = "This is the complete article body retrieved from schema.org JSON-LD structure." * 5
    html = f"""
    <html>
      <head>
        <script type="application/ld+json">
        {{
          "@context": "https://schema.org",
          "@type": "Article",
          "articleBody": "{article_text}"
        }}
        </script>
      </head>
      <body><div>Short body</div></body>
    </html>
    """
    soup = BeautifulSoup(html, "html.parser")
    content, method, _, _ = extract_content(soup, "https://example.com/ch1")
    assert content is not None
    assert "json_ld" in (method or "")
    assert "retrieved from schema.org" in content


def test_extract_content_density_heuristic_wrapper_preference() -> None:
    # Heuristic phải ưu tiên wrapper chứa nhiều đoạn (≥5 paragraphs) thay vì 1 đoạn đơn lẻ
    paragraphs = "\n".join([f"<p>Paragraph {i} of epic adventure prose.</p>" for i in range(15)])
    html = f"""
    <div>
      <div class="unrelated-short"><p>A lonely paragraph that has some text.</p></div>
      <article class="novel-container">
        {paragraphs}
      </article>
    </div>
    """
    soup = BeautifulSoup(html, "html.parser")
    content, method, _, _ = extract_content(soup, "https://example.com/ch1")

    assert content is not None
    assert method == "density_heuristic"
    assert "Paragraph 0" in content
    assert "Paragraph 14" in content


# ── Title Extraction Tests ────────────────────────────────────────────────────

def test_extract_title_first_wins_priority() -> None:
    html = """
    <html>
      <head>
        <title>Chapter 1: The Beginning | Royal Road</title>
        <meta property="og:title" content="OG Title | Royal Road" />
      </head>
      <body>
        <h1>H1: Chapter 1: The Beginning [ 1,200 words ]</h1>
        <div class="custom-title">Profile: Chapter 1: Real Title</div>
      </body>
    </html>
    """
    soup = BeautifulSoup(html, "html.parser")

    # 1. Profile selector wins (0.95)
    profile = SiteProfile(domain="example.com", title_selector=".custom-title")
    title1, method1 = extract_title(soup, "https://example.com/ch1", profile)
    assert title1 == "Profile: Chapter 1: Real Title"
    assert "selector" in method1

    # 2. Without profile selector, H1 wins (0.80) and strips word count artifact
    title2, method2 = extract_title(soup, "https://example.com/ch1", None)
    assert title2 == "H1: Chapter 1: The Beginning"
    assert method2 == "h1"

    # 3. Without H1, <title> wins (0.65) and strips site suffix
    soup_no_h1 = BeautifulSoup("<html><head><title>Chapter 1 | Royal Road</title></head></html>", "html.parser")
    title3, method3 = extract_title(soup_no_h1, "https://example.com/ch1", None)
    assert title3 == "Chapter 1"
    assert method3 == "title_tag"


def test_extract_title_forbidden_container_rejected() -> None:
    # Selector trỏ nhầm vào <select> dropdown của danh sách chương phải bị từ chối
    html = """
    <div>
      <select id="chap-select">
        <option>Chapter 1</option>
        <option>Chapter 2</option>
      </select>
      <h1>Real Chapter 1 Title</h1>
    </div>
    """
    soup = BeautifulSoup(html, "html.parser")
    profile = SiteProfile(domain="example.com", title_selector="select#chap-select")
    title, method = extract_title(soup, "https://example.com/ch1", profile)

    assert title == "Real Chapter 1 Title"
    assert method == "h1"


# ── Navigation & Page Type Tests ──────────────────────────────────────────────

def test_find_next_url_priority() -> None:
    html = """
    <div>
      <link rel="next" href="/chapter-2-rel" />
      <a class="btn-next" href="/chapter-2-sel">Next</a>
      <a href="/chapter-2-anchor">Next Chapter</a>
    </div>
    """
    soup = BeautifulSoup(html, "html.parser")
    profile = SiteProfile(domain="example.com", next_selector=".btn-next")

    # rel="next" có độ ưu tiên cao nhất
    next_url, method = find_next_url(soup, "https://example.com/chapter-1", profile)
    assert next_url == "https://example.com/chapter-2-rel"
    assert method == "rel_next"


def test_find_next_url_slug_increment_and_guard() -> None:
    soup = BeautifulSoup("<div><p>No buttons</p></div>", "html.parser")

    # Regular slug increment: /chapter-5 -> /chapter-6
    url1, m1 = find_next_url(soup, "https://novel.org/novel-name/chapter-5", None)
    assert url1 == "https://novel.org/novel-name/chapter-6"
    assert m1 == "slug_increment"

    # RoyalRoad numeric chapter ID guard: /chapter/12345/some-title -> KHÔNG được tăng slug
    url2, m2 = find_next_url(soup, "https://royalroad.com/fiction/11205/rock-falls/chapter/12345/some-title", None)
    assert url2 is None
    assert m2 == "none"


def test_detect_page_type() -> None:
    soup = BeautifulSoup("<html><head><title>Table of Contents</title></head></html>", "html.parser")

    # URL có chứa chapter -> luôn là chapter (kể cả có chứa /fiction/)
    assert detect_page_type(soup, "https://royalroad.com/fiction/11205/story/chapter/123") == "chapter"

    # URL mục lục
    assert detect_page_type(soup, "https://royalroad.com/fiction/11205/story") == "index"
    assert detect_page_type(soup, "https://site.org/novel/my-story/chapters") == "index"


# ── Validation Tests ──────────────────────────────────────────────────────────

def test_validate_content() -> None:
    # Quá ngắn -> fail
    res_short = validate_content("Too short text")
    assert not res_short.is_valid

    # Văn xuôi bình thường -> pass
    prose = "The wizard stepped forward cautiously. Darkness enveloped the cavern as distant whispers echoed." * 10
    res_good = validate_content(prose)
    assert res_good.is_valid
    assert res_good.score >= 0.5


# ── process_page Integration Tests ────────────────────────────────────────────

def test_process_page_full_flow() -> None:
    content_body = "<p>He looked at the sky and wondered when the battle would end.</p>" * 8
    html = f"""
    <html>
      <head>
        <title>Chapter 10: The Calm | Royal Road</title>
        <link rel="next" href="/chapter-11" />
      </head>
      <body>
        <div id="author-note" class="author-note-portlet">Please donate to my patreon!</div>
        <h1 class="chapter-title">Chapter 10: The Calm</h1>
        <div class="entry-content">
          <p>Prev Chapter</p>
          [ 1,500 words ]
          {content_body}
          <p>Prev Chapter</p>
          [ 1,500 words ]
        </div>
      </body>
    </html>
    """
    profile = SiteProfile(
        domain="royalroad.com",
        content_selector="div.entry-content",
        title_selector="h1.chapter-title",
        next_selector=None,
    )

    res: PageResult = process_page(html, "https://royalroad.com/fiction/1/ch/10", profile)

    assert res.title == "Chapter 10: The Calm"
    assert "selector" in res.title_method
    assert res.next_url == "https://royalroad.com/chapter-11"
    assert res.nav_method == "rel_next"
    assert res.content_md is not None
    # strip_nav_edges loại bỏ Prev Chapter và word count
    assert "[ 1,500 words ]" not in res.content_md
    assert "He looked at the sky" in res.content_md
    assert not res.is_index_page
    assert res.diagnostics["is_valid"] is True
