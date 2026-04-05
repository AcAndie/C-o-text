"""
pipeline/base.py — Core types và abstract interfaces cho Lego Blocks Pipeline.

v2 changes:
  ARCH-1: RuntimeContext tách biệt hoàn toàn live objects (pool, pw_pool,
          ai_limiter) ra khỏi SiteProfile dict.
          - SiteProfile = configuration data, serializable, lưu disk.
          - RuntimeContext = live runtime objects, KHÔNG serialize.
          Trước đây: ctx.profile["_pool"] = pool  ← anti-pattern
          Bây giờ:   ctx.runtime.pool             ← clean separation.

  ARCH-2: PipelineContext thêm:
          - runtime: RuntimeContext (injected by PipelineRunner)
          - detected_js_heavy: bool (signal từ HybridFetchBlock → caller)

  ARCH-3: Blocks KHÔNG được mutate ctx.profile. Side effects phải được
          báo cáo qua BlockResult.metadata để executor xử lý tập trung.
"""
from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


# ── Enums ─────────────────────────────────────────────────────────────────────

class BlockType(str, Enum):
    FETCH    = "fetch"
    EXTRACT  = "extract"
    NAVIGATE = "navigate"
    VALIDATE = "validate"
    TITLE    = "title"


class BlockStatus(str, Enum):
    SUCCESS  = "success"
    FALLBACK = "fallback"
    SKIPPED  = "skipped"
    FAILED   = "failed"


# ── RuntimeContext ─────────────────────────────────────────────────────────────

@dataclass
class RuntimeContext:
    """
    Live runtime objects — inject một lần mỗi pipeline execution.

    KHÔNG serialize, KHÔNG lưu disk, KHÔNG put vào SiteProfile.

    Tất cả blocks truy cập shared resources qua ctx.runtime thay vì
    ctx.profile["_pool"] (anti-pattern cũ).

    Được tạo bởi PipelineRunner.run() và gán vào ctx.runtime trước khi
    bất kỳ block nào được chạy.
    """
    pool:       Any = None   # DomainSessionPool — curl_cffi sessions
    pw_pool:    Any = None   # PlaywrightPool    — full browser instances
    ai_limiter: Any = None   # AIRateLimiter     — rate limiter cho Gemini

    @classmethod
    def create(cls, pool: Any, pw_pool: Any, ai_limiter: Any) -> "RuntimeContext":
        """Factory để tạo RuntimeContext từ các dependency đã có sẵn."""
        return cls(pool=pool, pw_pool=pw_pool, ai_limiter=ai_limiter)

    @classmethod
    def empty(cls) -> "RuntimeContext":
        """RuntimeContext trống — dùng cho testing hoặc offline mode."""
        return cls()

    @property
    def has_pool(self) -> bool:
        return self.pool is not None

    @property
    def has_pw_pool(self) -> bool:
        return self.pw_pool is not None

    @property
    def has_ai(self) -> bool:
        return self.ai_limiter is not None


# ── BlockResult ────────────────────────────────────────────────────────────────

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
        duration_ms: Thời gian thực thi (ms)
        char_count:  Số ký tự (cho extract blocks)
        error:       Mô tả lỗi (chỉ khi status == FAILED)
        metadata:    Dict tự do cho extra info VÀ signals cho executor.
                     VD: {"js_heavy": True} → executor xử lý side effect
                     thay vì block tự mutate ctx.profile.
    """
    status:      BlockStatus
    data:        Any        = None
    method_used: str        = ""
    confidence:  float      = 1.0
    duration_ms: float      = 0.0
    char_count:  int        = 0
    error:       str | None = None
    metadata:    dict       = field(default_factory=dict)

    @classmethod
    def success(
        cls,
        data       : Any,
        method_used: str   = "",
        confidence : float = 1.0,
        char_count : int   = 0,
        **metadata,
    ) -> "BlockResult":
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
        return cls(
            status      = BlockStatus.FAILED,
            error       = error,
            method_used = method_used,
            confidence  = 0.0,
        )

    @classmethod
    def skipped(cls, reason: str = "") -> "BlockResult":
        return cls(
            status   = BlockStatus.SKIPPED,
            metadata = {"reason": reason},
        )

    @property
    def ok(self) -> bool:
        return self.status in (BlockStatus.SUCCESS, BlockStatus.FALLBACK)

    @property
    def is_primary(self) -> bool:
        return self.status == BlockStatus.SUCCESS


# ── PipelineContext ────────────────────────────────────────────────────────────

@dataclass
class PipelineContext:
    """
    Shared mutable state flowing through the entire pipeline for ONE chapter.

    Lifecycle:
        1. PipelineRunner tạo ctx, inject ctx.runtime
        2. Fetch block  → ctx.html, ctx.status_code, ctx.fetch_method
        3. (build_soup) → ctx.soup (cleaned)
        4. Extract block → ctx.content, ctx.selector_used
        5. Title block   → ctx.title_clean (majority vote)
        6. Navigate block → ctx.next_url
        7. Validate block → ctx.is_valid, ctx.validation_score

    Signals trả về cho caller:
        detected_js_heavy: True nếu HybridFetchBlock phát hiện site dùng JS.
                           Caller (scraper.py) sẽ persist vào profile.
    """
    # ── Input ─────────────────────────────────────────────────────────────────
    url:      str
    profile:  dict = field(default_factory=dict)   # SiteProfile (READ-ONLY cho blocks)
    progress: dict = field(default_factory=dict)   # ProgressDict

    # ── Runtime dependencies (injected, NOT serialized) ───────────────────────
    runtime: RuntimeContext = field(default_factory=RuntimeContext.empty)

    # ── Fetch results ─────────────────────────────────────────────────────────
    html:         str | None = None
    status_code:  int        = 0
    fetch_method: str        = ""

    # ── Parsed DOM ────────────────────────────────────────────────────────────
    soup: Any = None   # BeautifulSoup | None

    # ── Extract results ───────────────────────────────────────────────────────
    content:       str | None = None
    title_raw:     str | None = None
    title_clean:   str | None = None
    selector_used: str | None = None

    # ── Navigation results ────────────────────────────────────────────────────
    next_url:   str | None = None
    nav_method: str        = ""

    # ── Validation ────────────────────────────────────────────────────────────
    is_valid:         bool  = False
    validation_score: float = 0.0
    validation_notes: list  = field(default_factory=list)

    # ── Signals cho caller ────────────────────────────────────────────────────
    # Blocks KHÔNG mutate ctx.profile. Signals được set trên ctx để
    # caller (PipelineRunner / scraper.py) xử lý side effects tập trung.
    detected_js_heavy: bool = False

    # ── Execution tracking ────────────────────────────────────────────────────
    block_results:     dict  = field(default_factory=dict)
    total_duration_ms: float = 0.0
    errors:            list  = field(default_factory=list)

    def record(self, block_name: str, result: BlockResult) -> None:
        self.block_results[block_name] = result
        self.total_duration_ms += result.duration_ms
        if result.status == BlockStatus.FAILED and result.error:
            self.errors.append(f"{block_name}: {result.error}")

    def get_pipeline_score(self) -> dict[str, float]:
        """
        Tính pipeline score từ tất cả block results.

        Returns:
            quality:    Chất lượng nội dung (0-1)
            speed:      Tốc độ thực thi (0-1, cao = nhanh)
            resource:   Tài nguyên sử dụng (0-1, cao = ít dùng)
            confidence: Độ tin cậy tổng thể (0-1)
            total:      0.4*quality + 0.3*speed + 0.2*resource + 0.1*confidence
        """
        quality  = self.validation_score
        speed_ms = max(self.total_duration_ms, 1)
        speed    = min(1.0, max(0.0, 1.0 - (speed_ms - 500) / 4500))

        used_pw  = "playwright" in self.fetch_method.lower()
        resource = 0.5 if used_pw else 1.0

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

    Contract:
      - execute() KHÔNG raise exception (trừ CancelledError)
      - execute() KHÔNG mutate ctx.profile
      - Side effects → báo qua BlockResult.metadata, executor xử lý
      - Implement to_config() / from_config() để serialize/deserialize

    Pattern chuẩn:
        result = BlockResult.failed("...")
        try:
            ... logic ...
            result = BlockResult.success(data)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            result = BlockResult.failed(str(e) or repr(e))
        return result
    """

    block_type: BlockType = BlockType.FETCH
    name:       str       = "base_block"

    @abstractmethod
    async def execute(self, ctx: PipelineContext) -> BlockResult: ...

    @abstractmethod
    def to_config(self) -> dict: ...

    @classmethod
    @abstractmethod
    def from_config(cls, config: dict) -> "ScraperBlock": ...

    def _timed(self, result: BlockResult, start: float) -> BlockResult:
        result.duration_ms = (time.monotonic() - start) * 1000
        return result


# ── Chain / Pipeline config (stored in profile) ───────────────────────────────

@dataclass
class StepConfig:
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
    Full pipeline configuration cho một domain — lưu vào profile JSON.

    Thay vì:
        {"content_selector": "div.chapter-content", ...}
    Bây giờ:
        {"pipeline": {"fetch_chain": {...}, "extract_chain": {...}, ...}}

    Self-healing: primary step thất bại → chain tự fallback sang step tiếp theo.
    """
    domain:            str
    fetch_chain:       ChainConfig = field(default_factory=lambda: ChainConfig("fetch"))
    extract_chain:     ChainConfig = field(default_factory=lambda: ChainConfig("extract"))
    title_chain:       ChainConfig = field(default_factory=lambda: ChainConfig("title"))
    nav_chain:         ChainConfig = field(default_factory=lambda: ChainConfig("navigate"))
    validate_chain:    ChainConfig = field(default_factory=lambda: ChainConfig("validate"))
    score:             float = 0.0
    optimizer_version: int   = 1
    created_at:        str   = ""
    notes:             str   = ""

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
        Default pipeline (naive/safe) cho domain mới chưa có profile.
        Optimizer sẽ thay thế cái này sau khi học xong.
        """
        return cls(
            domain = domain,
            fetch_chain = ChainConfig("fetch", [
                StepConfig("hybrid"),
                StepConfig("playwright"),
            ]),
            extract_chain = ChainConfig("extract", [
                StepConfig("selector"),
                StepConfig("json_ld"),
                StepConfig("density_heuristic"),
                StepConfig("fallback_list"),
                StepConfig("ai_extract"),
            ]),
            title_chain = ChainConfig("title", [
                StepConfig("selector"),
                StepConfig("h1_tag"),
                StepConfig("title_tag"),
                StepConfig("og_title"),
                StepConfig("url_slug"),
            ]),
            nav_chain = ChainConfig("navigate", [
                StepConfig("rel_next"),
                StepConfig("selector"),
                StepConfig("anchor_text"),
                StepConfig("slug_increment"),
                StepConfig("fanfic"),
                StepConfig("ai_nav"),
            ]),
            validate_chain = ChainConfig("validate", [
                StepConfig("length",         {"min_chars": 100}),
                StepConfig("prose_richness", {"min_word_count": 20}),
            ]),
            notes = "default_pipeline",
        )