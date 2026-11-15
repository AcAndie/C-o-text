from __future__ import annotations

import pytest
from pydantic import ValidationError

from cao_text.ai.prompts import (
    prompt_analyze_site,
    prompt_classify_page,
    prompt_epub_rules,
    prompt_extract_content,
    prompt_repair_site,
    prompt_txt_pattern,
    prompt_verify_ads_lines,
)
from cao_text.ai.schemas import (
    EpubChapterItem,
    EpubRulesOutput,
    ExtractedContentOutput,
    PageClassificationOutput,
    SiteAnalysisOutput,
    SiteRepairOutput,
    TxtPatternOutput,
    VerifyAdsOutput,
)


def test_site_analysis_schema_valid() -> None:
    """SiteAnalysisOutput validate đúng các trường selector, naming, ảnh và formatting_rules (§6.4)."""
    valid_data = {
        "content_selector": "div.chapter-content",
        "title_selector": "h1.chapter-title",
        "next_selector": "a.next-chap",
        "nav_type": "selector",
        "remove_selectors": [".ads", ".share-box"],
        "watermark_selectors": [".hidden-wm"],
        "ads_keywords": ["Read free at novel.com"],
        "download_images": True,
        "image_selector": "div.chapter-content img",
        "story_name_clean": "Rock Falls Everyone Dies",
        "chapter_keyword": "Chapter",
        "has_chapter_subtitle": True,
        "story_prefix_strip": "RFED - ",
        "formatting_rules": {
            "tables": True,
            "system_box_selector": "div.system-alert",
        },
        "confidence": 0.95,
        "requires_playwright": False,
        "notes": "Trang chuẩn",
    }
    output = SiteAnalysisOutput.model_validate(valid_data)
    assert output.content_selector == "div.chapter-content"
    assert output.title_selector == "h1.chapter-title"
    assert output.story_name_clean == "Rock Falls Everyone Dies"
    assert output.download_images is True
    assert output.confidence == 0.95

    # Kiểm tra build_formatting_rules() trả về đủ khóa mặc định an toàn (§6.4)
    fmt = output.build_formatting_rules()
    assert fmt.tables is True
    assert fmt.bold_italic is True
    assert fmt.hr_dividers is True
    assert fmt.system_box == {"enabled": True, "selector": "div.system-alert"}

    # Thiếu content_selector -> lỗi
    with pytest.raises(ValidationError):
        SiteAnalysisOutput.model_validate({"title_selector": "h1"})

    # Confidence ngoài [0, 1] -> lỗi
    with pytest.raises(ValidationError):
        SiteAnalysisOutput.model_validate({"content_selector": "div", "confidence": 1.5})


def test_site_repair_schema() -> None:
    """SiteRepairOutput hỗ trợ cập nhật selector và lý do sửa."""
    repair_data = {
        "content_selector": "article#novel-body",
        "remove_selectors_to_add": [".watermark-hidden"],
        "remove_selectors_to_remove": [".valid-dialogue"],
        "confidence": 0.85,
        "reasoning": "Bộ chọn cũ lọt watermark ẩn bằng CSS",
    }
    output = SiteRepairOutput.model_validate(repair_data)
    assert output.content_selector == "article#novel-body"
    assert len(output.remove_selectors_to_add) == 1
    assert "watermark" in output.reasoning


def test_page_classification_schema() -> None:
    """PageClassificationOutput phân loại trang chính xác theo Enum."""
    chapter_data = {
        "page_type": "chapter",
        "story_title": "Đại Phụng Đả Canh Nhân",
        "chapter_title": "Chương 1",
        "next_chapter_url": "https://novel.com/c/2",
    }
    out1 = PageClassificationOutput.model_validate(chapter_data)
    assert out1.page_type == "chapter"
    assert out1.next_chapter_url == "https://novel.com/c/2"

    index_data = {
        "page_type": "index",
        "story_title": "Mục Thần Ký",
        "first_chapter_url": "https://novel.com/c/1",
    }
    out2 = PageClassificationOutput.model_validate(index_data)
    assert out2.page_type == "index"
    assert out2.first_chapter_url == "https://novel.com/c/1"

    # page_type không hợp lệ -> ValidationError
    with pytest.raises(ValidationError):
        PageClassificationOutput.model_validate({"page_type": "invalid_type"})


def test_extracted_content_schema() -> None:
    """ExtractedContentOutput lưu giữ tiêu đề và nội dung văn bản."""
    data = {
        "title": "Chương 42",
        "content_text": "Đoạn 1.\n\nĐoạn 2.",
        "next_url": "https://novel.com/c/43",
    }
    out = ExtractedContentOutput.model_validate(data)
    assert out.title == "Chương 42"
    assert "Đoạn 1" in out.content_text
    assert out.next_url == "https://novel.com/c/43"


def test_verify_ads_schema() -> None:
    """VerifyAdsOutput phân tách ad_lines và safe_lines."""
    data = {
        "ad_lines": ["Vào nhóm telegram để đọc sớm!", "Vote 5 sao giúp nhóm nhé."],
        "safe_lines": ["Hàn Tuyệt khẽ mỉm cười.", "Hắn bước tiếp về phía trước."],
        "reasoning": "Đã lọc câu thoại hợp lệ",
    }
    out = VerifyAdsOutput.model_validate(data)
    assert len(out.ad_lines) == 2
    assert len(out.safe_lines) == 2


def test_txt_pattern_schema() -> None:
    """TxtPatternOutput chứa biểu thức chính quy hợp lệ."""
    data = {
        "chapter_regex": r"^(?:Hồi|Tiết)\s+\d+",
        "example_matches": ["Hồi 1", "Hồi 2", "Tiết 3"],
        "confidence": 0.9,
    }
    out = TxtPatternOutput.model_validate(data)
    assert out.chapter_regex.startswith("^")
    assert len(out.example_matches) == 3


def test_epub_rules_schema() -> None:
    """EpubRulesOutput trả về bộ quy tắc phân chia chương theo Phase 6.2 & §7.3 (không liệt kê từng doc)."""
    data = {
        "story_title": "Ready Player One",
        "author": "Ernest Cline",
        "chapter_title_regex": r"^(?:Chapter|Level)\s+\d+",
        "divider_title_regex": r"^Level\s+(?:One|Two|Three)",
        "front_matter_keywords": ["cover", "copyright", "toc"],
        "back_matter_keywords": ["acknowledgments", "appendix"],
        "front_matter_hrefs": ["cover.xhtml", "toc.xhtml"],
        "back_matter_hrefs": ["afterword.xhtml"],
        "merge_unnamed_into_previous": True,
        "confidence": 0.92,
    }
    out = EpubRulesOutput.model_validate(data)
    assert out.story_title == "Ready Player One"
    assert out.chapter_title_regex == r"^(?:Chapter|Level)\s+\d+"
    assert out.divider_title_regex == r"^Level\s+(?:One|Two|Three)"
    assert len(out.front_matter_hrefs) == 2
    assert out.merge_unnamed_into_previous is True
    assert out.confidence == 0.92

    item = EpubChapterItem(title="Chapter 1", hrefs=["part1.xhtml", "ch1.xhtml"])
    assert item.hrefs == ["part1.xhtml", "ch1.xhtml"]


def test_prompts_generation_strings() -> None:
    """Các hàm prompt sinh chuỗi có nội dung hướng dẫn đầy đủ."""
    # 1. analyze_site (đơn lẻ và danh sách 2 chương + ứng viên)
    p_analyze = prompt_analyze_site(
        ["<div class='main'>ch1</div>", "<div class='main'>ch2</div>"],
        ["https://site.com/c1", "https://site.com/c2"],
        candidates={"content": ["div.main"]},
        repeated_lines=["Watermark line"],
        raw_titles=["Novel - Chapter 1"],
    )
    assert "https://site.com/c1" in p_analyze
    assert "content_selector" in p_analyze
    assert "story_name_clean" in p_analyze
    assert "DOM SKELETON" in p_analyze
    assert "Watermark line" in p_analyze

    # 2. repair_site
    p_repair = prompt_repair_site(
        "<article>txt</article>",
        "https://site.com/c2",
        {"content_selector": "div.bad"},
        "Nội dung bị rỗng",
    )
    assert "Nội dung bị rỗng" in p_repair
    assert "div.bad" in p_repair

    # 3. classify_page
    p_class = prompt_classify_page(
        "<html>...</html>",
        "https://site.com/index",
        ["https://site.com/c1", "https://site.com/c2"],
    )
    assert "first_chapter_url" in p_class
    assert "https://site.com/c1" in p_class

    # 4. extract_content
    p_extract = prompt_extract_content("<p>story</p>", "https://site.com/c1")
    assert "Trích xuất TOÀN BỘ" in p_extract

    # 5. verify_ads_lines
    p_ads = prompt_verify_ads_lines(["Quảng cáo 1", "Hắn nói:"], "novel.com")
    assert "Quảng cáo 1" in p_ads
    assert "ad_lines" in p_ads
    assert "safe_lines" in p_ads

    # 6. txt_pattern
    p_txt = prompt_txt_pattern("Hồi 1: Khởi đầu\n\nNội dung...")
    assert "chapter_regex" in p_txt
    assert "Hồi 1" in p_txt

    # 7. epub_rules
    p_epub = prompt_epub_rules(
        "- doc1.xhtml (1000 words)\n- doc2.xhtml (5000 words)",
        toc_titles=["Cover", "Part 1", "Chapter 1"],
    )
    assert "chapter_title_regex" in p_epub
    assert "divider_title_regex" in p_epub
    assert "doc1.xhtml" in p_epub
