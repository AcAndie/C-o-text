"""
pipeline/base.py — Core types và abstract interfaces cho Lego Blocks Pipeline.

Mọi block trong hệ thống đều implement ScraperBlock.
Mọi kết quả đều là BlockResult.
Trạng thái chia sẻ giữa các blocks là PipelineContext.
Cấu hình pipeline được lưu trong profile là PipelineConfig (Option B: Strategy Chain).

Design principles:
  - BlockResult mang đủ thông tin để PipelineEvaluator chấm điểm
  - PipelineContext là mutable, flow xuyên suốt pipeline
  - ChainConfig là pure data (serializable JSON), không phụ thuộc class names
  - ScraperBlock.execute() luôn trả về BlockResult, KHÔNG raise exception
"""
from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


# ── Enums ─────────────────────────────────────────────────────────────────────

class BlockType(str, Enum):
    """Loại block trong pipeline."""
    FETCH    = "fetch"
    EXTRACT  = "extract"
    NAVIGATE = "navigate"
    VALIDATE = "validate"
    TITLE    = "title"


class BlockStatus(str, Enum):
    """Trạng thái kết quả của một block execution."""
    SUCCESS  = "success"   # Block chạy thành công, có kết quả
    FALLBACK = "fallback"  # Block thành công nhưng dùng fallback strategy
    SKIPPED  = "skipped"   # Block bị skip (không applicable)
    FAILED   = "failed"    # Block thất bại hoàn toàn


# ── Core data types ───────────────────────────────────────────────────────────

@dataclass
class BlockResult:
    """
    Kết quả của một block execution.
    
    Mọi block PHẢI trả về BlockResult — không được raise exception.
    Exception nên được bắt bên trong block và chuyển thành FAILED result.
    
    Fields:
        status:      Trạng thái thực thi (xem BlockStatus)
        data:        Output của block (nội dung, URL, v.v.)
        method_used: Tên strategy đã dùng (VD: "rel_next", "selector", "ai")
        confidence:  0.0-1.0 — mức độ tin cậy của kết quả
        duration_ms: Thời gian thực thi (ms) — dùng để tính resource score
        char_count:  Số ký tự (cho extract blocks) — dùng để tính quality score
        error:       Mô tả lỗi (chỉ khi status == FAILED)
        metadata:    Dict tự do cho extra info (selector đã dùng, v.v.)
    """
    status:      BlockStatus
    data:        Any           = None
    method_used: str           = ""
    confidence:  float         = 1.0
    duration_ms: float         = 0.0
    char_count:  int           = 0
    error:       str | None    = None
    metadata:    dict          = field(default_factory=dict)

    @classmethod
    def success(
        cls,
        data       : Any,
        method_used: str   = "",
        confidence : float = 1.0,
        char_count : int   = 0,
        **metadata,
    ) -> "BlockResult":
        """Factory method cho kết quả thành công."""
        return cls(
            status      = BlockStatus.SUCCESS,
            data        = data,
            method_used = method_used,
            confidence  = confidence,
            char_count  = char_count or (len(data) if isinstance(data, str) else 0),
            metadata    = metadata,
        )

    @classmethod
    def fallback(
        cls,
        data       : Any,
        method_used: str   = "fallback",
        confidence : float = 0.6,
        **metadata,
    ) -> "BlockResult":
        """Factory method khi dùng fallback strategy."""
        return cls(
            status      = BlockStatus.FALLBACK,
            data        = data,
            method_used = method_used,
            confidence  = confidence,
            char_count  = len(data) if isinstance(data, str) else 0,
            metadata    = metadata,
        )

    @classmethod
    def failed(cls, error: str, method_used: str = "") -> "BlockResult":
        """Factory method cho kết quả thất bại."""
        return cls(
            status      = BlockStatus.FAILED,
            error       = error,
            method_used = method_used,
            confidence  = 0.0,
        )

    @classmethod
    def skipped(cls, reason: str = "") -> "BlockResult":
        """Factory method khi block bị skip."""
        return cls(
            status   = BlockStatus.SKIPPED,
            metadata = {"reason": reason},
        )

    @property
    def ok(self) -> bool:
        """True nếu block có kết quả sử dụng được (SUCCESS hoặc FALLBACK)."""
        return self.status in (BlockStatus.SUCCESS, BlockStatus.FALLBACK)

    @property
    def is_primary(self) -> bool:
        """True nếu dùng primary strategy (không phải fallback)."""
        return self.status == BlockStatus.SUCCESS


@dataclass
class PipelineContext:
    """
    Shared mutable state flowing through the entire pipeline for ONE chapter.
    
    Được tạo mới cho mỗi chapter scrape.
    Mỗi block đọc từ context và ghi kết quả của mình vào context.
    
    Lifecycle:
        1. Fetch block  → ghi html, status
        2. Extract block → ghi content, title_raw
        3. Title block   → ghi title_clean
        4. Navigate block → ghi next_url
        5. Validate block → ghi is_valid, validation_score
    """
    # ── Input ─────────────────────────────────────────────────────────────────
    url:     str
    profile: dict = field(default_factory=dict)   # SiteProfile
    progress: dict = field(default_factory=dict)  # ProgressDict

    # ── Fetch results ─────────────────────────────────────────────────────────
    html:           str | None = None
    status_code:    int        = 0
    fetch_method:   str        = ""   # "curl", "playwright", "hybrid"

    # ── Parsed DOM ────────────────────────────────────────────────────────────
    # soup được set bởi executor sau fetch, trước khi pass vào extract blocks
    soup:           Any        = None   # BeautifulSoup | None

    # ── Extract results ───────────────────────────────────────────────────────
    content:        str | None = None
    title_raw:      str | None = None
    title_clean:    str | None = None
    selector_used:  str | None = None   # CSS selector đã extract được content

    # ── Navigation results ────────────────────────────────────────────────────
    next_url:       str | None = None
    nav_method:     str        = ""

    # ── Validation ────────────────────────────────────────────────────────────
    is_valid:         bool  = False
    validation_score: float = 0.0
    validation_notes: list  = field(default_factory=list)

    # ── Execution tracking ────────────────────────────────────────────────────
    block_results:    dict  = field(default_factory=dict)  # block_name → BlockResult
    total_duration_ms: float = 0.0
    errors:           list  = field(default_factory=list)

    def record(self, block_name: str, result: BlockResult) -> None:
        """Lưu kết quả của một block vào context."""
        self.block_results[block_name] = result
        self.total_duration_ms += result.duration_ms
        if result.status == BlockStatus.FAILED and result.error:
            self.errors.append(f"{block_name}: {result.error}")

    def get_pipeline_score(self) -> dict[str, float]:
        """
        Tính pipeline score từ tất cả block results.
        Dùng bởi PipelineEvaluator.
        
        Returns dict với các dimension:
            quality:    Chất lượng nội dung (0-1)
            speed:      Tốc độ thực thi (0-1, cao = nhanh)
            resource:   Tài nguyên sử dụng (0-1, cao = ít dùng)
            confidence: Độ tin cậy tổng thể (0-1)
            total:      Score tổng = 0.4*quality + 0.3*speed + 0.2*resource + 0.1*confidence
        """
        quality    = self.validation_score
        
        # Speed score: < 500ms = 1.0, > 5000ms = 0.0
        speed_ms   = max(self.total_duration_ms, 1)
        speed      = min(1.0, max(0.0, 1.0 - (speed_ms - 500) / 4500))

        # Resource score: penalize nặng Playwright (tốn RAM)
        used_pw    = self.fetch_method == "playwright"
        resource   = 0.5 if used_pw else 1.0

        # Confidence: average của các block results có data
        confs = [
            r.confidence for r in self.block_results.values()
            if r.ok and r.confidence > 0
        ]
        confidence = sum(confs) / len(confs) if confs else 0.0

        total = (
            0.4 * quality
            + 0.3 * speed
            + 0.2 * resource
            + 0.1 * confidence
        )
        return {
            "quality":    round(quality,    3),
            "speed":      round(speed,      3),
            "resource":   round(resource,   3),
            "confidence": round(confidence, 3),
            "total":      round(total,      3),
        }


# ── Abstract base class ───────────────────────────────────────────────────────

class ScraperBlock(ABC):
    """
    Abstract base class cho mọi block trong pipeline.
    
    Mọi block PHẢI:
      1. Implement execute() và trả về BlockResult (không raise)
      2. Có thuộc tính `block_type` và `name`
      3. Implement to_config() để serialize thành dict (cho profile)
      4. Implement classmethod from_config() để deserialize từ profile
    
    Pattern thực thi:
        result = BlockResult.failed("...")   # default
        try:
            ... logic ...
            result = BlockResult.success(data)
        except asyncio.CancelledError:
            raise   # PHẢI re-raise CancelledError
        except Exception as e:
            result = BlockResult.failed(str(e) or repr(e))
        return result
    """

    # Subclasses PHẢI định nghĩa hai thuộc tính này
    block_type: BlockType = BlockType.FETCH
    name:       str       = "base_block"

    @abstractmethod
    async def execute(self, ctx: PipelineContext) -> BlockResult:
        """
        Thực thi block logic.
        
        Args:
            ctx: Shared pipeline context (mutable)
            
        Returns:
            BlockResult — KHÔNG ĐƯỢC raise exception (trừ CancelledError)
        """
        ...

    @abstractmethod
    def to_config(self) -> dict:
        """
        Serialize block thành dict để lưu vào profile.
        
        Returns:
            {"type": self.name, ...params...}
        """
        ...

    @classmethod
    @abstractmethod
    def from_config(cls, config: dict) -> "ScraperBlock":
        """
        Deserialize block từ dict (đọc từ profile).
        
        Args:
            config: {"type": "...", ...params...}
        """
        ...

    def _timed(self, result: BlockResult, start: float) -> BlockResult:
        """Helper: gán duration_ms từ start time."""
        result.duration_ms = (time.monotonic() - start) * 1000
        return result


# ── Chain config (stored in profile) ─────────────────────────────────────────

@dataclass
class StepConfig:
    """
    Cấu hình cho một bước trong chain.
    Đây là pure data — serializable to/from JSON.
    
    Ví dụ:
        {"type": "selector", "selector": "div.chapter-content", "min_chars": 200}
        {"type": "rel_next"}
        {"type": "ai_extract"}
        {"type": "density_heuristic"}
    """
    type:   str
    params: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = {"type": self.type}
        d.update(self.params)
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "StepConfig":
        t = d.get("type", "unknown")
        params = {k: v for k, v in d.items() if k != "type"}
        return cls(type=t, params=params)


@dataclass
class ChainConfig:
    """
    Cấu hình cho một chain (ordered list of strategies).
    
    Chain sẽ thử từng step theo thứ tự.
    Dừng tại step đầu tiên thành công (status SUCCESS hoặc FALLBACK).
    
    chain_type: "fetch" | "extract" | "title" | "navigate" | "validate"
    steps:      List các strategy theo thứ tự ưu tiên (primary first)
    
    Ví dụ extract chain:
        {
            "chain_type": "extract",
            "steps": [
                {"type": "selector", "selector": "div.chapter-content"},
                {"type": "json_ld"},
                {"type": "density_heuristic"},
                {"type": "fallback_list"},
                {"type": "ai_extract"}
            ]
        }
    """
    chain_type: str
    steps:      list[StepConfig] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "chain_type": self.chain_type,
            "steps":      [s.to_dict() for s in self.steps],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ChainConfig":
        return cls(
            chain_type = d.get("chain_type", ""),
            steps      = [StepConfig.from_dict(s) for s in d.get("steps", [])],
        )


@dataclass
class PipelineConfig:
    """
    Full pipeline configuration cho một domain.
    Đây là cái được lưu vào profile JSON thay thế cho các selector thô.
    
    Thay vì:
        {"content_selector": "div.chapter-content", "next_selector": "a.next"}
    
    Bây giờ:
        {
            "pipeline": {
                "fetch_chain": {...},
                "extract_chain": {...},
                "title_chain": {...},
                "nav_chain": {...},
                "validate_chain": {...},
                "score": 0.87,
                "optimizer_version": 1
            }
        }
    
    Self-healing: nếu primary step thất bại → chain tự fallback sang step tiếp theo.
    Profile không hỏng khi site thay đổi DOM — chỉ score giảm nhẹ.
    """
    domain:            str
    fetch_chain:       ChainConfig = field(default_factory=lambda: ChainConfig("fetch"))
    extract_chain:     ChainConfig = field(default_factory=lambda: ChainConfig("extract"))
    title_chain:       ChainConfig = field(default_factory=lambda: ChainConfig("title"))
    nav_chain:         ChainConfig = field(default_factory=lambda: ChainConfig("navigate"))
    validate_chain:    ChainConfig = field(default_factory=lambda: ChainConfig("validate"))
    score:             float       = 0.0
    optimizer_version: int         = 1
    created_at:        str         = ""
    notes:             str         = ""

    def to_dict(self) -> dict:
        return {
            "domain":            self.domain,
            "fetch_chain":       self.fetch_chain.to_dict(),
            "extract_chain":     self.extract_chain.to_dict(),
            "title_chain":       self.title_chain.to_dict(),
            "nav_chain":         self.nav_chain.to_dict(),
            "validate_chain":    self.validate_chain.to_dict(),
            "score":             self.score,
            "optimizer_version": self.optimizer_version,
            "created_at":        self.created_at,
            "notes":             self.notes,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "PipelineConfig":
        return cls(
            domain            = d.get("domain", ""),
            fetch_chain       = ChainConfig.from_dict(d.get("fetch_chain", {})),
            extract_chain     = ChainConfig.from_dict(d.get("extract_chain", {})),
            title_chain       = ChainConfig.from_dict(d.get("title_chain", {})),
            nav_chain         = ChainConfig.from_dict(d.get("nav_chain", {})),
            validate_chain    = ChainConfig.from_dict(d.get("validate_chain", {})),
            score             = float(d.get("score", 0.0)),
            optimizer_version = int(d.get("optimizer_version", 1)),
            created_at        = d.get("created_at", ""),
            notes             = d.get("notes", ""),
        )

    @classmethod
    def default_for_domain(cls, domain: str) -> "PipelineConfig":
        """
        Tạo PipelineConfig mặc định (naive/safe) cho một domain mới.
        Đây là starting point trước khi Optimizer tìm ra config tốt hơn.
        
        Default chain order (từ nhanh/đơn giản đến chậm/tốn kém):
            fetch:    curl → playwright
            extract:  selector → json_ld → density_heuristic → fallback_list → ai
            title:    selector → h1 → title_tag → og_title → url_slug
            navigate: rel_next → selector → anchor_text → slug_increment → fanfic → ai
            validate: length → prose_richness
        """
        return cls(
            domain = domain,
            fetch_chain = ChainConfig("fetch", [
                StepConfig("curl"),
                StepConfig("playwright"),
            ]),
            extract_chain = ChainConfig("extract", [
                StepConfig("selector"),            # Dùng learned selector từ profile
                StepConfig("json_ld"),             # JSON-LD Article schema
                StepConfig("density_heuristic"),   # Trafilatura-style text density
                StepConfig("fallback_list"),        # Known selectors list
                StepConfig("ai_extract"),          # AI last resort
            ]),
            title_chain = ChainConfig("title", [
                StepConfig("selector"),            # Dùng title_selector từ profile
                StepConfig("h1_tag"),              # <h1>
                StepConfig("title_tag"),           # <title> stripped
                StepConfig("og_title"),            # og:title meta
                StepConfig("url_slug"),            # Slug từ URL
            ]),
            nav_chain = ChainConfig("navigate", [
                StepConfig("rel_next"),            # <link rel="next"> hoặc <a rel="next">
                StepConfig("selector"),            # Dùng next_selector từ profile
                StepConfig("anchor_text"),         # "Next", "Next Chapter", v.v.
                StepConfig("slug_increment"),      # /chapter-5 → /chapter-6
                StepConfig("fanfic"),              # fanfiction.net /s/id/num/
                StepConfig("ai_nav"),              # AI fallback
            ]),
            validate_chain = ChainConfig("validate", [
                StepConfig("length", {"min_chars": 100}),
                StepConfig("prose_richness", {"min_word_count": 20}),
            ]),
        )