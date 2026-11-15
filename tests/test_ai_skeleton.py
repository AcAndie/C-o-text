from __future__ import annotations

from pathlib import Path

from cao_text.ai.skeleton import compress_dom_to_skeleton


def test_compress_dom_empty() -> None:
    """Chuỗi HTML rỗng trả về chuỗi rỗng."""
    assert compress_dom_to_skeleton("") == ""
    assert compress_dom_to_skeleton("   ") == ""


def test_compress_dom_discard_tags_and_comments() -> None:
    """Loại bỏ sạch các thẻ script, style, svg, noscript, iframe và comment."""
    raw_html = """
    <html>
      <head>
        <title>Tiêu Đề Truyện</title>
        <style>body { color: red; }</style>
        <script>console.log("tracker");</script>
      </head>
      <body>
        <!-- Đây là comment cần xóa -->
        <div id="content">
          <h1>Chương 1</h1>
          <svg><path d="M0 0"/></svg>
          <noscript>Vui lòng bật javascript</noscript>
          <iframe src="https://ads.com"></iframe>
          <p>Nội dung chính của chương truyện.</p>
        </div>
      </body>
    </html>
    """
    skeleton = compress_dom_to_skeleton(raw_html)
    assert "console.log" not in skeleton
    assert "color: red" not in skeleton
    assert "<script" not in skeleton
    assert "<style" not in skeleton
    assert "<svg" not in skeleton
    assert "<noscript" not in skeleton
    assert "<iframe" not in skeleton
    assert "Đây là comment" not in skeleton
    assert "Chương 1" in skeleton
    assert "Nội dung chính" in skeleton
    assert "Tiêu Đề Truyện" in skeleton


def test_compress_dom_attribute_filtering() -> None:
    """Chỉ giữ lại id, class, role, rel, aria-*, href của <a> và value/selected của <option>."""
    raw_html = """
    <div id="main-wrap" class="container fluid" style="padding: 10px;" onclick="doTrack()" data-id="123">
      <nav role="navigation" aria-label="Pagination" data-tracker="nav">
        <a href="/chapter/2" rel="next" style="color: blue;" onclick="return false;">Next Chapter</a>
        <button type="submit" disabled="disabled">Click</button>
      </nav>
      <select class="nav-select">
        <option value="/chap-1" data-val="1">Ch 1</option>
        <option value="/chap-2" selected="selected">Ch 2</option>
      </select>
    </div>
    """
    skeleton = compress_dom_to_skeleton(raw_html)
    assert 'id="main-wrap"' in skeleton
    assert 'class="container fluid"' in skeleton
    assert 'role="navigation"' in skeleton
    assert 'aria-label="Pagination"' in skeleton
    assert 'href="/chapter/2"' in skeleton
    assert 'rel="next"' in skeleton
    assert 'value="/chap-1"' in skeleton
    assert 'selected="selected"' in skeleton

    # Các thuộc tính rác bị loại bỏ
    assert "style=" not in skeleton
    assert "onclick=" not in skeleton
    assert "data-id=" not in skeleton
    assert "data-tracker=" not in skeleton
    assert "disabled=" not in skeleton


def test_compress_dom_text_truncation() -> None:
    """Văn bản của node dài > 80 ký tự được cắt ngắn kèm '...'."""
    long_text = "Đây là một đoạn văn bản rất dài được tạo ra nhằm mục đích kiểm tra khả năng cắt ngắn chuỗi văn bản của từng node đơn lẻ trong cây DOM skeleton để tiết kiệm token cho AI."
    assert len(long_text) > 80

    raw_html = f'<div id="story"><p class="para">{long_text}</p></div>'
    skeleton = compress_dom_to_skeleton(raw_html, max_node_text=50)

    assert "..." in skeleton
    assert len(skeleton) < len(long_text)
    assert "Đây là một đoạn văn bản" in skeleton


def test_compress_dom_collapse_repeating_children() -> None:
    """Nhiều thẻ con lặp lại liên tiếp (>= 4) được gộp lại, chỉ giữ 2 đầu, 1 cuối và 1 placeholder."""
    paragraphs = "".join([f'<p class="text-body">Đoạn văn thứ {i}.</p>' for i in range(1, 21)])
    raw_html = f'<div id="chapter-content">{paragraphs}</div>'

    skeleton = compress_dom_to_skeleton(raw_html, repeat_threshold=4)

    assert "Đoạn văn thứ 1." in skeleton
    assert "Đoạn văn thứ 2." in skeleton
    assert "Đoạn văn thứ 20." in skeleton
    assert "tương tự được gộp" in skeleton
    assert "skeleton-collapsed" in skeleton
    # Các đoạn ở giữa không còn xuất hiện
    assert "Đoạn văn thứ 10." not in skeleton
    assert "Đoạn văn thứ 15." not in skeleton


def test_compress_dom_max_chars_cap() -> None:
    """Tổng độ dài chuỗi skeleton không vượt quá max_chars và giữ cả phần đầu lẫn phần cuối trang."""
    paragraphs = "".join([f'<p class="para-{i}">Nội dung đoạn số {i} của tiểu thuyết.</p>' for i in range(100)])
    raw_html = f'<div id="big-box"><header id="top-nav">Đầu trang</header>{paragraphs}<footer id="bot-nav"><a href="/next">Next</a></footer></div>'

    max_budget = 400
    skeleton = compress_dom_to_skeleton(raw_html, max_chars=max_budget)

    # Đảm bảo tổng độ dài tuân thủ nghiêm ngặt ngân sách max_chars
    assert len(skeleton) <= max_budget
    assert "DOM Skeleton đã được cắt bớt" in skeleton
    assert "top-nav" in skeleton
    assert "bot-nav" in skeleton


def test_compress_dom_obfuscated_classes_and_head_rel_next() -> None:
    """Lọc bỏ class obfuscated/hash để gộp các đoạn văn và giữ lại <link rel="next"> trong <head>."""
    rr_paras = "".join(
        [
            f'<p class="cnM2ZTU1MzcyMDhiNzQ4MWQ4MjNjZDhiNTZmZTIwYz{i:02d}">Đoạn RoyalRoad {i}</p>'
            for i in range(10)
        ]
    )
    wn_paras = "".join(
        [
            f'<div class="db cha-paragraph j_paragraph j_para_63305e34d9219a014e51f7ce9c9831{i:02d}"><p>Đoạn Webnovel {i}</p></div>'
            for i in range(10)
        ]
    )
    raw_html = f"""
    <html>
      <head>
        <title>Test Novel</title>
        <link rel="next" href="/chapter-2" />
      </head>
      <body>
        <div class="chapter-inner">{rr_paras}</div>
        <div class="cha-words">{wn_paras}</div>
      </body>
    </html>
    """
    skeleton = compress_dom_to_skeleton(raw_html, repeat_threshold=4)
    assert 'rel="next"' in skeleton
    assert 'href="/chapter-2"' in skeleton
    # Các đoạn RoyalRoad và Webnovel đều được gộp mặc dù có class hash riêng biệt
    assert "tương tự được gộp" in skeleton
    assert "Đoạn RoyalRoad 5" not in skeleton
    assert "Đoạn Webnovel 5" not in skeleton


def test_compress_dom_with_fixtures_html() -> None:
    """Chạy tốt trên fixture dropdown_next.html và giữ lại các cấu trúc điều hướng cốt lõi."""
    fixture_path = Path(__file__).resolve().parent / "fixtures" / "html" / "dropdown_next.html"
    if not fixture_path.exists():
        return

    raw_html = fixture_path.read_text(encoding="utf-8")
    skeleton = compress_dom_to_skeleton(raw_html)

    assert 'id="chr-content"' in skeleton
    assert 'class="chapter-select"' in skeleton
    assert 'value="/novel/archive/chapter-4"' in skeleton
    assert "Three iron keys hung" in skeleton


def test_compress_dom_with_local_royalroad_fixture_if_exists() -> None:
    """Kiểm tra tỷ lệ nén và gộp đoạn trên fixture thật của RoyalRoad và Webnovel nếu có."""
    base_dir = Path(__file__).resolve().parent / "fixtures_local" / "web"
    rr_fixture = base_dir / "www.royalroad.com" / "rock_falls_everyone_dies" / "0001.html"
    if rr_fixture.exists():
        raw_html = rr_fixture.read_text(encoding="utf-8")
        raw_size = len(raw_html)
        skeleton = compress_dom_to_skeleton(raw_html, max_chars=15000)

        assert len(skeleton) <= 15000
        assert len(skeleton) < raw_size * 0.25
        assert "chapter-inner" in skeleton
        assert "tương tự được gộp" in skeleton

    wn_fixture = base_dir / "www.webnovel.com" / "in_danmachi_with_plasmids" / "0001.html"
    if wn_fixture.exists():
        raw_html = wn_fixture.read_text(encoding="utf-8")
        skeleton = compress_dom_to_skeleton(raw_html, max_chars=15000)

        assert len(skeleton) <= 15000
        assert "cha-words" in skeleton
        assert "tương tự được gộp" in skeleton
