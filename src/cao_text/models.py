"""models.py — Mô hình dữ liệu cốt lõi cho Cào Text v2.

Bao gồm:
  - SiteProfile (Pydantic model, persist xuống site_profiles.json, profile_version=3).
  - StoryState (Pydantic model, lưu trạng thái tiến độ cào của truyện).
  - RunConfig (Dataclass, cấu hình chạy transient, tự suy ra theo output mode).
  - CleanedChapter (Dataclass, hợp đồng dữ liệu giữa pipeline trích xuất và writer).
  - ImageRef (Dataclass, tham chiếu ảnh minh họa trong chương).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from cao_text.settings import Settings


# ── FormattingRules & SiteProfile (Pydantic) ──────────────────────────────────

class FormattingRules(BaseModel):
    """Quy tắc định dạng trích xuất nội dung cho từng site."""

    model_config = ConfigDict(extra="allow")

    tables: bool = False
    math_support: bool = False
    math_format: str | None = None
    special_symbols: list[str] = Field(default_factory=list)
    bold_italic: bool = True
    hr_dividers: bool = True
    image_alt_strategy: str = "skip"  # skip | preserve | fallback_to_filename
    system_box: dict[str, Any] = Field(default_factory=lambda: {"found": False, "selectors": []})
    hidden_text: dict[str, Any] = Field(default_factory=lambda: {"found": False, "selectors": []})
    author_note: dict[str, Any] = Field(default_factory=lambda: {"found": False, "selectors": []})


class SiteProfile(BaseModel):
    """Hồ sơ cấu trúc bóc tách của một trang web (persist vào site_profiles.json)."""

    model_config = ConfigDict(extra="ignore")

    domain: str
    last_learned: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    confidence: float = 1.0
    profile_version: int = 3

    # Bộ chọn CSS chính
    content_selector: str | None = None
    next_selector: str | None = None
    title_selector: str | None = None
    remove_selectors: list[str] = Field(default_factory=list)

    # Điều hướng & nhận diện chương
    nav_type: str | None = "selector"  # rel_next | selector | anchor_text | slug_increment | fanfic | dropdown
    chapter_url_pattern: str | None = None
    requires_playwright: bool = False

    # Định dạng & lọc từ khóa
    formatting_rules: FormattingRules = Field(default_factory=FormattingRules)
    ads_keywords_learned: list[str] = Field(default_factory=list)
    learned_chapters: list[int] = Field(default_factory=list)
    sample_urls: list[str] = Field(default_factory=list)

    # Chính sách tải ảnh
    download_images: bool = False
    image_selector: str | None = None

    # Thông tin kiểm chứng & ghi chú
    uncertain_fields: list[str] = Field(default_factory=list)
    notes: str | None = None

    def is_usable(self, min_confidence: float = 0.3, min_version: int = 3) -> bool:
        """Kiểm tra profile có đủ tin cậy và đúng phiên bản (v3) để dùng tiếp hay cần học lại."""
        return self.profile_version >= min_version and self.confidence >= min_confidence


# ── StoryState (Pydantic) ─────────────────────────────────────────────────────

class StoryState(BaseModel):
    """Trạng thái tiến độ cào của một bộ truyện (lưu trong progress/<story_key>/state.json)."""

    model_config = ConfigDict(extra="allow")

    story_key: str
    start_url: str
    current_url: str | None = None
    chapter_count: int = 0
    story_title: str | None = None
    completed: bool = False
    completed_at: str | None = None
    completed_at_url: str | None = None

    # Khóa bảo vệ cùng truyện
    story_id: str | None = None
    story_id_regex: str | None = None
    story_id_locked: bool = False

    # Thông tin chương gần nhất
    last_title: str | None = None
    last_scraped_url: str | None = None

    # Đặt tên truyện & thư mục output
    naming_done: bool = False
    story_name_clean: str | None = None
    chapter_keyword: str = "Chapter"
    has_chapter_subtitle: bool = False
    story_prefix_strip: str | None = None
    output_dir_final: str | None = None

    def mark_completed(self, final_url: str | None = None) -> None:
        """Đánh dấu bộ truyện đã cào hoàn tất."""
        self.completed = True
        self.completed_at = datetime.now(UTC).isoformat()
        if final_url:
            self.completed_at_url = final_url


# ── ImageRef & CleanedChapter (Dataclasses) ───────────────────────────────────

@dataclass
class ImageRef:
    """Tham chiếu tới một hình ảnh minh họa trong văn bản chương."""

    original_url: str
    local_path: str | None = None
    alt_text: str = ""
    position_marker: str = ""
    source_type: Literal["web", "epub"] = "web"


@dataclass
class RawDocument:
    """Hợp đồng dữ liệu thô giữa bộ đọc file (EPUB/TXT) và luồng xử lý trích xuất."""

    chapter_index: int
    html: str
    source_url: str | None = None
    source_path: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class CleanedChapter:
    """Hợp đồng dữ liệu chương đã làm sạch từ pipeline gửi cho các writer."""

    index: int
    title: str
    body_markdown: str
    images: list[ImageRef] = field(default_factory=list)
    source_url: str | None = None
    source_path: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


# ── RunConfig (Dataclass) ─────────────────────────────────────────────────────

@dataclass
class RunConfig:
    """Cấu hình thực thi theo từng phiên chạy (transient, không persist)."""

    output_mode: Literal["obsidian", "translate", "raw"] = "obsidian"
    download_images: bool = True
    image_placeholder: bool = False
    fetch_metadata: bool = True
    output_dir: str = "output"
    max_pw_instances: int = 2
    per_host_concurrency: int = 3
    fast_learning: bool = False
    no_validation: bool = False
    bulk_relearn: bool = False
    pattern: str | None = None
    apply: bool = False

    @classmethod
    def create_for_mode(
        cls,
        output_mode: Literal["obsidian", "translate", "raw"] = "obsidian",
        output_dir: str = "output",
        *,
        download_images: bool | None = None,
        image_placeholder: bool | None = None,
        fetch_metadata: bool | None = None,
        max_pw_instances: int = 2,
        per_host_concurrency: int = 3,
        fast_learning: bool = False,
        no_validation: bool = False,
        bulk_relearn: bool = False,
        pattern: str | None = None,
        apply: bool = False,
    ) -> RunConfig:
        """Tự động suy ra cấu hình phù hợp nhất theo Output Mode (§1 AGENTS.md)."""
        mode_defaults: dict[str, dict[str, bool]] = {
            "obsidian": {"dl": True, "ph": False, "meta": True},
            "translate": {"dl": False, "ph": True, "meta": False},
            "raw": {"dl": False, "ph": False, "meta": False},
        }
        defaults = mode_defaults.get(output_mode, mode_defaults["obsidian"])

        dl = defaults["dl"] if download_images is None else download_images
        ph = defaults["ph"] if image_placeholder is None else image_placeholder
        meta = defaults["meta"] if fetch_metadata is None else fetch_metadata

        return cls(
            output_mode=output_mode,
            download_images=dl,
            image_placeholder=ph,
            fetch_metadata=meta,
            output_dir=output_dir,
            max_pw_instances=max_pw_instances,
            per_host_concurrency=per_host_concurrency,
            fast_learning=fast_learning,
            no_validation=no_validation,
            bulk_relearn=bulk_relearn,
            pattern=pattern,
            apply=apply,
        )

    @classmethod
    def from_settings(cls, settings: Settings, **overrides: Any) -> RunConfig:
        """Khởi tạo RunConfig từ đối tượng Settings toàn cục."""
        mode = overrides.get("output_mode", settings.output.mode)
        out_dir = overrides.get("output_dir", settings.paths.output_dir)

        # Nếu settings.output.download_images được user chỉ định trong toml
        user_dl = overrides.get("download_images")
        if user_dl is None and not settings.output.download_images:
            user_dl = False

        return cls.create_for_mode(
            output_mode=mode,
            output_dir=out_dir,
            download_images=user_dl,
            image_placeholder=overrides.get("image_placeholder"),
            fetch_metadata=overrides.get("fetch_metadata"),
            max_pw_instances=overrides.get("max_pw_instances", settings.scraper.playwright_concurrency),
            per_host_concurrency=overrides.get("per_host_concurrency", settings.scraper.per_host_concurrency),
            fast_learning=overrides.get("fast_learning", settings.fast_learning),
            no_validation=overrides.get("no_validation", settings.no_validation),
            bulk_relearn=overrides.get("bulk_relearn", settings.bulk_relearn),
            pattern=overrides.get("pattern", settings.pattern),
            apply=overrides.get("apply", settings.apply),
        )


@dataclass
class FileSpec:
    """Đặc tả thông số thực thi cho luồng xử lý file đơn lẻ (EPUB/TXT)."""

    input_path: str | Path
    run_config: RunConfig = field(default_factory=RunConfig.create_for_mode)
    input_type: Literal["epub", "txt"] | None = None
    story_name: str | None = None
    output_dir: str | Path | None = None
    ai_provider: Any = None
    pattern: str | None = None
    inject_nav: bool | None = None
