"""Pydantic schemas cho structured output của AI trong Cào Text v2."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class SiteAnalysisOutput(BaseModel):
    """Kết quả phân tích DOM skeleton để tạo profile cho một site mới."""

    model_config = ConfigDict(extra="ignore")

    content_selector: str = Field(description="CSS selector cho vùng chứa nội dung chương chính")
    title_selector: str | None = Field(default=None, description="CSS selector cho tiêu đề chương")
    next_selector: str | None = Field(default=None, description="CSS selector cho nút/link chương kế tiếp")
    nav_type: str = Field(
        default="selector",
        description="Loại điều hướng: selector, rel_next, anchor_text, slug_increment, dropdown",
    )
    remove_selectors: list[str] = Field(
        default_factory=list,
        description="Danh sách CSS selector các phần tử rác (quảng cáo, comments, vote, nút chia sẻ)",
    )
    confidence: float = Field(default=0.9, ge=0.0, le=1.0, description="Độ tin cậy của phân tích")
    requires_playwright: bool = Field(default=False, description="Site có bắt buộc dùng Playwright hay không")
    notes: str | None = Field(default=None, description="Ghi chú về cấu trúc site")


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
    """Kết quả nhận diện pattern ranh giới chương cho file văn bản TXT."""

    model_config = ConfigDict(extra="ignore")

    chapter_regex: str = Field(description="Biểu thức chính quy (Python regex) khớp dòng tiêu đề chương")
    example_matches: list[str] = Field(default_factory=list, description="Các ví dụ khớp từ mẫu")
    confidence: float = Field(default=0.8, ge=0.0, le=1.0)
    notes: str | None = Field(default=None, description="Ghi chú về định dạng file")


class EpubChapterItem(BaseModel):
    """Một mục chương được gom nhóm từ các tài liệu thành phần trong EPUB."""

    model_config = ConfigDict(extra="ignore")

    title: str = Field(description="Tiêu đề chương chuẩn hóa")
    hrefs: list[str] = Field(description="Danh sách href các tài liệu thành phần tạo nên chương này")
    is_special: bool = Field(default=False, description="Đánh dấu nếu là phần đặc biệt (ngoại truyện, lời tựa)")


class EpubRulesOutput(BaseModel):
    """Kế hoạch cấu trúc chương cho tài liệu EPUB."""

    model_config = ConfigDict(extra="ignore")

    story_title: str | None = Field(default=None, description="Tên tác phẩm")
    author: str | None = Field(default=None, description="Tác giả")
    front_matter_hrefs: list[str] = Field(
        default_factory=list,
        description="Danh sách href là bìa, bản quyền, mục lục đầu sách",
    )
    chapters: list[EpubChapterItem] = Field(
        default_factory=list,
        description="Danh sách các chương truyện thực sự",
    )
    back_matter_hrefs: list[str] = Field(
        default_factory=list,
        description="Danh sách href là phụ lục, lời kết, quảng cáo cuối sách",
    )
    reasoning: str | None = Field(default=None, description="Giải thích cách phân chia")
