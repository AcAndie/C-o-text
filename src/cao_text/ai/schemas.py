"""Pydantic schemas cho structured output của AI trong Cào Text v2."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from cao_text.models import FormattingRules


class FormattingRulesSchema(BaseModel):
    """Cấu hình định dạng văn bản do AI đề xuất (tương thích строг với Gemini response_schema)."""

    model_config = ConfigDict(extra="ignore")

    tables: bool = Field(default=False, description="Giữ bảng HTML dưới dạng bảng Markdown (ví dụ bảng trạng thái LitRPG)")
    math_support: bool = Field(default=False, description="Giữ công thức toán học LaTeX/MathML")
    bold_italic: bool = Field(default=True, description="Giữ định dạng in đậm / in nghiêng")
    hr_dividers: bool = Field(default=True, description="Giữ đường kẻ ngang phân cảnh (<hr>)")
    image_alt_strategy: str = Field(
        default="skip",
        description="Chiến lược xử lý alt text của ảnh: skip, preserve, fallback_to_filename",
    )
    system_box_selector: str | None = Field(
        default=None,
        description="CSS selector cho hộp hệ thống / bảng thông báo kỹ năng nếu có",
    )
    author_note_selector: str | None = Field(
        default=None,
        description="CSS selector cho phần lời tác giả (author note) nếu cần đóng khung riêng",
    )

    def to_formatting_rules(self) -> FormattingRules:
        """Chuyển đổi sang FormattingRules đầy đủ khóa mặc định an toàn (§6.4)."""
        rules = FormattingRules(
            tables=self.tables,
            math_support=self.math_support,
            bold_italic=self.bold_italic,
            hr_dividers=self.hr_dividers,
            image_alt_strategy=self.image_alt_strategy,
        )
        if self.system_box_selector:
            rules.system_box = {
                "found": True,
                "selectors": [self.system_box_selector],
            }
        if self.author_note_selector:
            rules.author_note = {
                "found": True,
                "selectors": [self.author_note_selector],
            }
        return rules


class SiteAnalysisOutput(BaseModel):
    """Kết quả phân tích DOM skeleton để tạo profile và đặt tên cho một site mới (Phase 4)."""

    model_config = ConfigDict(extra="ignore")

    content_selector: str = Field(description="CSS selector cho vùng chứa nội dung chương chính")
    title_selector: str | None = Field(default=None, description="CSS selector cho tiêu đề chương")
    next_selector: str | None = Field(default=None, description="CSS selector cho nút/link chương kế tiếp")
    nav_type: str = Field(
        default="selector",
        description="Loại điều hướng: selector, rel_next, anchor_text, slug_increment, fanfic, dropdown",
    )
    remove_selectors: list[str] = Field(
        default_factory=list,
        description="Danh sách CSS selector các phần tử rác (quảng cáo, comments, vote, nút chia sẻ)",
    )
    watermark_selectors: list[str] = Field(
        default_factory=list,
        description="Danh sách CSS selector của câu watermark/chống copy chèn giữa nội dung",
    )
    ads_keywords: list[str] = Field(
        default_factory=list,
        description="Các câu rác/quảng cáo/watermark văn bản thuần lặp lại cần lọc bỏ",
    )
    download_images: bool = Field(
        default=False,
        description="Truyện có ảnh minh họa nội dung chương cần tải về hay không",
    )
    image_selector: str | None = Field(
        default=None,
        description="CSS selector cho thẻ ảnh minh họa trong chương (nếu có)",
    )
    story_name_clean: str | None = Field(
        default=None,
        description="Tên bộ truyện đã làm sạch (bỏ hậu tố tên web, 'Read online', 'Free'...) để đặt tên thư mục",
    )
    chapter_keyword: str = Field(
        default="Chapter",
        description="Từ khóa chương dùng thống nhất (ví dụ: 'Chương' cho truyện Việt, 'Chapter' cho truyện Anh)",
    )
    has_chapter_subtitle: bool = Field(
        default=False,
        description="Tiêu đề chương có tên phụ (subtitle) đi kèm số chương hay không",
    )
    story_prefix_strip: str | None = Field(
        default=None,
        description="Tiền tố tên truyện lặp lại ở đầu mỗi tiêu đề chương cần cắt bỏ",
    )
    formatting_rules: FormattingRulesSchema = Field(
        default_factory=FormattingRulesSchema,
        description="Quy tắc định dạng nội dung (bảng biểu, in đậm/nghiêng, hộp hệ thống)",
    )
    confidence: float = Field(default=0.9, ge=0.0, le=1.0, description="Độ tin cậy của phân tích")
    requires_playwright: bool = Field(default=False, description="Site có bắt buộc dùng Playwright hay không")
    notes: str | None = Field(default=None, description="Ghi chú về cấu trúc site")

    def build_formatting_rules(self) -> FormattingRules:
        """Trả về FormattingRules có đầy đủ khóa mặc định trước khi ghi đè (§6.4)."""
        return self.formatting_rules.to_formatting_rules()


class SiteRepairOutput(BaseModel):
    """Kết quả hiệu chỉnh profile khi kiểm chứng trên các chương mẫu bị lỗi."""

    model_config = ConfigDict(extra="ignore")

    content_selector: str | None = Field(default=None, description="CSS selector nội dung sau khi sửa")
    title_selector: str | None = Field(default=None, description="CSS selector tiêu đề sau khi sửa")
    next_selector: str | None = Field(default=None, description="CSS selector next link sau khi sửa")
    nav_type: str | None = Field(default=None, description="Loại điều hướng sau khi sửa")
    remove_selectors_to_add: list[str] = Field(
        default_factory=list,
        description="Các selector rác mới cần thêm vào danh sách remove",
    )
    remove_selectors_to_remove: list[str] = Field(
        default_factory=list,
        description="Các selector xóa nhầm cần gỡ khỏi danh sách remove",
    )
    confidence: float = Field(default=0.8, ge=0.0, le=1.0)
    reasoning: str = Field(description="Giải thích nguyên nhân và phương án sửa đổi")


class PageClassificationOutput(BaseModel):
    """Kết quả phân loại trang web và tìm kiếm liên kết khởi đầu / kế tiếp."""

    model_config = ConfigDict(extra="ignore")

    page_type: Literal["index", "chapter", "unknown"] = Field(
        description="Loại trang: index (mục lục/giới thiệu), chapter (nội dung đọc), unknown",
    )
    story_title: str | None = Field(default=None, description="Tên tác phẩm nếu phát hiện được")
    chapter_title: str | None = Field(default=None, description="Tên chương nếu là trang chapter")
    first_chapter_url: str | None = Field(
        default=None,
        description="URL chương 1 (khi trang là index hoặc có mục lục)",
    )
    next_chapter_url: str | None = Field(
        default=None,
        description="URL chương kế tiếp (khi trang là chapter)",
    )
    confidence: float = Field(default=0.8, ge=0.0, le=1.0)
    reasoning: str | None = Field(default=None, description="Lý do phân loại")


class ExtractedContentOutput(BaseModel):
    """Kết quả trích xuất nội dung văn bản thuần khi dùng AI fallback."""

    model_config = ConfigDict(extra="ignore")

    title: str | None = Field(default=None, description="Tiêu đề chương")
    content_text: str = Field(description="Nội dung văn bản sạch của chương, mỗi đoạn cách nhau 2 dòng trống")
    next_url: str | None = Field(default=None, description="URL chương tiếp theo nếu tìm thấy trong trang")


class VerifyAdsOutput(BaseModel):
    """Kết quả phân loại các dòng văn bản lặp lại thành quảng cáo hoặc văn bản an toàn."""

    model_config = ConfigDict(extra="ignore")

    ad_lines: list[str] = Field(
        default_factory=list,
        description="Các dòng THỰC SỰ là quảng cáo / watermark / kêu gọi donate cần bị xóa",
    )
    safe_lines: list[str] = Field(
        default_factory=list,
        description="Các dòng là nội dung truyện thật (lời thoại, miêu tả) TUYỆT ĐỐI KHÔNG ĐƯỢC XÓA",
    )
    reasoning: str | None = Field(default=None, description="Giải thích lý do phân loại")


class TxtPatternOutput(BaseModel):
    """Kết quả nhận diện pattern ranh giới chương cho file văn bản TXT (Phase 6.1)."""

    model_config = ConfigDict(extra="ignore")

    pattern_id: str | None = Field(
        default=None,
        description="Định danh ngắn gọn dạng snake_case cho pattern (ví dụ: vn_hoi_tiet, en_act_scene)",
    )
    language: str = Field(
        default="other",
        description="Ngôn ngữ chính của file: 'vi', 'en', 'zh', hoặc 'other'",
    )
    chapter_regex: str = Field(description="Biểu thức chính quy (Python regex) khớp dòng tiêu đề chương")
    example_matches: list[str] = Field(default_factory=list, description="Các ví dụ khớp từ mẫu")
    confidence: float = Field(default=0.8, ge=0.0, le=1.0)
    notes: str | None = Field(default=None, description="Ghi chú về định dạng file")


class EpubChapterItem(BaseModel):
    """Một mục chương đã được lập kế hoạch từ các tài liệu thành phần trong EPUB."""

    model_config = ConfigDict(extra="ignore")

    title: str = Field(description="Tiêu đề chương chuẩn hóa")
    hrefs: list[str] = Field(description="Danh sách href các tài liệu thành phần tạo nên chương này")
    is_special: bool = Field(default=False, description="Đánh dấu nếu là phần đặc biệt (ngoại truyện, lời tựa)")


class EpubRulesOutput(BaseModel):
    """Bộ quy tắc phân loại và gộp/tách chương cho EPUB (Phase 6.2 & §7.3 — KHÔNG liệt kê từng doc)."""

    model_config = ConfigDict(extra="ignore")

    story_title: str | None = Field(default=None, description="Tên tác phẩm")
    author: str | None = Field(default=None, description="Tác giả")
    chapter_title_regex: str | None = Field(
        default=None,
        description="Python regex nhận diện tiêu đề chương chính (ví dụ: '^(?:Chapter|Chương)\\s+\\d+')",
    )
    divider_title_regex: str | None = Field(
        default=None,
        description="Python regex nhận diện trang divider Phần/Quyển (ví dụ: '^(?:Part|Book|Volume|Quyển)\\s+[\\w\\d]+') để gộp vào chương sau",
    )
    front_matter_keywords: list[str] = Field(
        default_factory=list,
        description="Danh sách từ khóa tiêu đề hoặc tên file thuộc đầu sách cần bỏ qua (cover, copyright, toc, preface...)",
    )
    back_matter_keywords: list[str] = Field(
        default_factory=list,
        description="Danh sách từ khóa tiêu đề hoặc tên file thuộc cuối sách cần bỏ qua (afterword, appendix, license...)",
    )
    front_matter_hrefs: list[str] = Field(
        default_factory=list,
        description="Danh sách href cụ thể ở đầu sách chắc chắn là bìa, bản quyền, mục lục cần bỏ",
    )
    back_matter_hrefs: list[str] = Field(
        default_factory=list,
        description="Danh sách href cụ thể ở cuối sách chắc chắn là phụ lục, quảng cáo cuối sách cần bỏ",
    )
    merge_unnamed_into_previous: bool = Field(
        default=True,
        description="Nếu True, các tài liệu con không có tiêu đề TOC sẽ được gộp nối tiếp vào chương liền trước",
    )
    confidence: float = Field(default=0.85, ge=0.0, le=1.0, description="Độ tin cậy của bộ quy tắc")
    reasoning: str | None = Field(default=None, description="Giải thích ngắn gọn quy tắc phân chia")
