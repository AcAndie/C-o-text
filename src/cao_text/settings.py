"""Settings (dataclass): nạp cấu hình từ .env + config.toml + CLI (không side effect khi import).

Thứ tự ưu tiên nguồn cấu hình:
    CLI flag > Biến môi trường (.env/os.environ) > config.toml > Mặc định trong code.
"""
from __future__ import annotations

import logging
import os
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from dotenv import dotenv_values

logger = logging.getLogger(__name__)

_GEMINI_KEY_PATTERN = re.compile(r"^GEMINI_API_KEY(?:_\d+)?$")


def _find_project_root() -> Path:
    """Xác định thư mục gốc của dự án (thư mục chứa pyproject.toml hoặc .git)."""
    current = Path(__file__).resolve().parent
    for parent in [current, *current.parents]:
        if (parent / "pyproject.toml").exists() or (parent / ".git").exists():
            return parent
    # Fallback nếu không thấy marker: src/cao_text/settings.py -> project root là 3 cấp cha
    return Path(__file__).resolve().parent.parent.parent


def _derive_fallback_model(primary: str) -> str:
    """Tự suy ra fallback model nếu model chính là flash/pro và chưa cấu hình fallback.

    Quy tắc: Không dùng biến thể 'lite' cho structured output (§3.1).
    """
    p = primary.lower()
    if "2.5-flash" in p:
        return "gemini-3.8-flash"
    return "gemini-2.5-flash"


def _extract_gemini_keys(source: dict[str, str | None]) -> list[str]:
    """Trích xuất và sắp xếp danh sách API keys từ nguồn biến môi trường.

    Thứ tự sắp xếp:
        1. GEMINI_API_KEY (không số) đứng đầu.
        2. GEMINI_API_KEY_<số> theo thứ tự số nguyên tăng dần.
    Khóa trùng lặp giá trị sẽ được giữ duy nhất theo thứ tự xuất hiện đầu tiên.
    """
    matched: list[tuple[int, str]] = []
    for k, v in source.items():
        if not v or not isinstance(v, str):
            continue
        val = v.strip()
        if not val:
            continue
        if k == "GEMINI_API_KEY":
            matched.append((0, val))
        elif k.startswith("GEMINI_API_KEY_"):
            suffix = k[len("GEMINI_API_KEY_") :]
            if suffix.isdigit():
                matched.append((int(suffix), val))

    matched.sort(key=lambda item: item[0])

    seen: set[str] = set()
    result: list[str] = []
    for _, val in matched:
        if val not in seen:
            seen.add(val)
            result.append(val)
    return result


@dataclass
class OutputSettings:
    """Cấu hình định dạng và thư mục đầu ra ([output])."""

    mode: str = "obsidian"  # obsidian | translate | raw
    dir: str = "output"
    download_images: bool = True


@dataclass
class PathsSettings:
    """Cấu hình đường dẫn tập tin và thư mục dữ liệu ([paths])."""

    data_dir: str = "data"
    output_dir: str = "output"
    progress_dir: str = "progress"
    issues_file: str = "issues.md"
    links_file: str = "input/links.txt"
    epub_inbox_dir: str = "input/epub"


@dataclass
class ScraperSettings:
    """Cấu hình giới hạn an toàn và vòng lặp cào ([scraper])."""

    max_chapters: int = 5000
    max_consecutive_errors: int = 5
    max_consecutive_timeouts: int = 3
    timeout_backoff_base: float = 30.0
    playwright_concurrency: int = 2
    per_host_concurrency: int = 3
    init_stagger: float = 2.0
    empty_backoff_schedule: list[int] = field(default_factory=lambda: [60, 120, 300])


@dataclass
class LearningSettings:
    """Cấu hình chu kỳ học cấu trúc site mới ([learning])."""

    chapters: int = 10
    min_content: int = 300
    profile_max_age_days: int = 30
    ai_calls: int = 10
    conflict_threshold: int = 3


@dataclass
class AISettings:
    """Cấu hình tương tác AI Gemini ([ai])."""

    api_keys: list[str] = field(default_factory=list)
    model: str = "gemini-3.8-flash"
    fallback_model: str = "gemini-2.5-flash"
    max_rpm: int = 10
    jitter: tuple[float, float] = (0.5, 2.0)


@dataclass
class HttpSettings:
    """Cấu hình kết nối HTTP ([http])."""

    request_timeout: float = 60.0


@dataclass
class JsDetectionSettings:
    """Ngưỡng nhận diện site cần Playwright ([js_detection])."""

    content_ratio: float = 1.5
    min_diff_chars: int = 500


@dataclass
class EpubSettings:
    """Cấu hình phân tích tài liệu EPUB ([epub])."""

    analyzer: str = "ai"  # ai | rules


@dataclass
class Settings:
    """Tổng hợp cấu hình toàn bộ ứng dụng Cào Text."""

    output: OutputSettings = field(default_factory=OutputSettings)
    paths: PathsSettings = field(default_factory=PathsSettings)
    scraper: ScraperSettings = field(default_factory=ScraperSettings)
    learning: LearningSettings = field(default_factory=LearningSettings)
    ai: AISettings = field(default_factory=AISettings)
    http: HttpSettings = field(default_factory=HttpSettings)
    js_detection: JsDetectionSettings = field(default_factory=JsDetectionSettings)
    epub: EpubSettings = field(default_factory=EpubSettings)

    # CLI runtime flags
    fast_learning: bool = False
    no_validation: bool = False
    bulk_relearn: bool = False
    pattern: str | None = None
    apply: bool = False

    # ── Convenience properties ───────────────────────────────────────────────

    @property
    def output_mode(self) -> str:
        return self.output.mode

    @property
    def output_dir(self) -> str:
        return self.paths.output_dir

    @property
    def download_images(self) -> bool:
        return self.output.download_images

    @property
    def profiles_file(self) -> str:
        return str(Path(self.paths.data_dir) / "site_profiles.json")

    @property
    def ads_db_file(self) -> str:
        return str(Path(self.paths.data_dir) / "ads_keywords.json")

    @property
    def url_classifications_file(self) -> str:
        return str(Path(self.paths.data_dir) / "url_classifications.json")

    # ── AI Key Accessors (chỉ raise lỗi khi gọi, không raise khi import) ──────

    def get_primary_api_key(self) -> str:
        """Trả về API key đầu tiên. Chỉ báo lỗi khi thật sự cần gọi AI."""
        if not self.ai.api_keys:
            raise ValueError(
                "Không tìm thấy GEMINI_API_KEY (hoặc GEMINI_API_KEY_1, _2...) trong biến môi trường hoặc .env"
            )
        return self.ai.api_keys[0]

    def require_api_keys(self) -> list[str]:
        """Trả về toàn bộ danh sách API key, raise lỗi nếu danh sách rỗng."""
        if not self.ai.api_keys:
            raise ValueError(
                "Không tìm thấy GEMINI_API_KEY (hoặc GEMINI_API_KEY_1, _2...) trong biến môi trường hoặc .env"
            )
        return list(self.ai.api_keys)

    # ── Factory Loader ────────────────────────────────────────────────────────

    @classmethod
    def load(
        cls,
        cli_args: dict[str, Any] | Any | None = None,
        *,
        config_path: Path | str | None = None,
        env_path: Path | str | None = None,
        env_dict: dict[str, str] | None = None,
        project_root: Path | str | None = None,
    ) -> Settings:
        """Khởi tạo Settings theo thứ tự ưu tiên: CLI > env > config.toml > default.

        Args:
            cli_args: Dictionary hoặc argparse.Namespace từ CLI parser.
            config_path: Đường dẫn tường minh tới config.toml.
            env_path: Đường dẫn tường minh tới file .env.
            env_dict: Dictionary biến môi trường giả lập (phục vụ test).
            project_root: Thư mục gốc dự án để định vị config.toml / .env.
        """
        root = Path(project_root) if project_root else _find_project_root()

        # 1. Bắt đầu từ giá trị mặc định
        cfg = cls()

        # 2. Đọc config.toml (nếu có)
        toml_file = Path(config_path) if config_path else (root / "config.toml")
        toml_data: dict[str, Any] = {}
        if toml_file.exists():
            try:
                with open(toml_file, "rb") as f:
                    toml_data = tomllib.load(f) or {}
            except (tomllib.TOMLDecodeError, OSError) as e:
                logger.warning("Không thể đọc file config.toml (%s): %s — dùng mặc định.", toml_file, e)

        if toml_data:
            _apply_toml(cfg, toml_data)

        # 3. Nạp biến môi trường (env)
        # Merge .env file (nếu có) và os.environ (hoặc env_dict)
        merged_env: dict[str, str | None] = {}

        actual_env_file = Path(env_path) if env_path else (root / ".env")
        if actual_env_file.exists():
            try:
                dotenv_vals = dotenv_values(dotenv_path=actual_env_file)
                merged_env.update(dotenv_vals)
            except Exception as e:
                logger.warning("Không thể đọc .env (%s): %s", actual_env_file, e)

        if env_dict is not None:
            merged_env.update(env_dict)
        else:
            merged_env.update(os.environ)

        _apply_env(cfg, merged_env)

        # 4. Ghi đè bằng CLI arguments
        if cli_args is not None:
            _apply_cli(cfg, cli_args)

        return cfg


def _apply_toml(cfg: Settings, data: dict[str, Any]) -> None:
    """Ghi đè cấu hình từ dữ liệu config.toml."""
    # [output]
    out_sec = data.get("output", {})
    if "mode" in out_sec:
        cfg.output.mode = str(out_sec["mode"])
    if "dir" in out_sec:
        cfg.output.dir = str(out_sec["dir"])
        cfg.paths.output_dir = str(out_sec["dir"])
    if "download_images" in out_sec:
        cfg.output.download_images = bool(out_sec["download_images"])

    # [paths]
    paths_sec = data.get("paths", {})
    if "data_dir" in paths_sec:
        cfg.paths.data_dir = str(paths_sec["data_dir"])
    if "output_dir" in paths_sec:
        cfg.paths.output_dir = str(paths_sec["output_dir"])
        cfg.output.dir = str(paths_sec["output_dir"])
    if "progress_dir" in paths_sec:
        cfg.paths.progress_dir = str(paths_sec["progress_dir"])
    if "issues_file" in paths_sec:
        cfg.paths.issues_file = str(paths_sec["issues_file"])
    if "links_file" in paths_sec:
        cfg.paths.links_file = str(paths_sec["links_file"])
    if "epub_inbox_dir" in paths_sec:
        cfg.paths.epub_inbox_dir = str(paths_sec["epub_inbox_dir"])

    # [scraper]
    scr_sec = data.get("scraper", {})
    if "max_chapters" in scr_sec:
        cfg.scraper.max_chapters = int(scr_sec["max_chapters"])
    if "max_consecutive_errors" in scr_sec:
        cfg.scraper.max_consecutive_errors = int(scr_sec["max_consecutive_errors"])
    if "max_consecutive_timeouts" in scr_sec:
        cfg.scraper.max_consecutive_timeouts = int(scr_sec["max_consecutive_timeouts"])
    if "timeout_backoff_base" in scr_sec:
        cfg.scraper.timeout_backoff_base = float(scr_sec["timeout_backoff_base"])
    if "playwright_concurrency" in scr_sec:
        cfg.scraper.playwright_concurrency = int(scr_sec["playwright_concurrency"])
    if "per_host_concurrency" in scr_sec:
        cfg.scraper.per_host_concurrency = int(scr_sec["per_host_concurrency"])
    if "init_stagger" in scr_sec:
        cfg.scraper.init_stagger = float(scr_sec["init_stagger"])
    if "empty_backoff_schedule" in scr_sec:
        cfg.scraper.empty_backoff_schedule = [int(x) for x in scr_sec["empty_backoff_schedule"]]

    # [learning]
    learn_sec = data.get("learning", {})
    if "chapters" in learn_sec:
        cfg.learning.chapters = int(learn_sec["chapters"])
    if "min_content" in learn_sec:
        cfg.learning.min_content = int(learn_sec["min_content"])
    if "profile_max_age_days" in learn_sec:
        cfg.learning.profile_max_age_days = int(learn_sec["profile_max_age_days"])
    if "ai_calls" in learn_sec:
        cfg.learning.ai_calls = int(learn_sec["ai_calls"])
    if "conflict_threshold" in learn_sec:
        cfg.learning.conflict_threshold = int(learn_sec["conflict_threshold"])

    # [ai]
    ai_sec = data.get("ai", {})
    if "model" in ai_sec:
        cfg.ai.model = str(ai_sec["model"])
        cfg.ai.fallback_model = _derive_fallback_model(cfg.ai.model)
    if "fallback_model" in ai_sec:
        cfg.ai.fallback_model = str(ai_sec["fallback_model"])
    if "max_rpm" in ai_sec:
        cfg.ai.max_rpm = int(ai_sec["max_rpm"])
    if "jitter" in ai_sec:
        j = ai_sec["jitter"]
        cfg.ai.jitter = (float(j[0]), float(j[1]))

    # [http]
    http_sec = data.get("http", {})
    if "request_timeout" in http_sec:
        cfg.http.request_timeout = float(http_sec["request_timeout"])

    # [js_detection]
    js_sec = data.get("js_detection", {})
    if "content_ratio" in js_sec:
        cfg.js_detection.content_ratio = float(js_sec["content_ratio"])
    if "min_diff_chars" in js_sec:
        cfg.js_detection.min_diff_chars = int(js_sec["min_diff_chars"])

    # [epub]
    epub_sec = data.get("epub", {})
    if "analyzer" in epub_sec:
        cfg.epub.analyzer = str(epub_sec["analyzer"])


def _apply_env(cfg: Settings, env: dict[str, str | None]) -> None:
    """Ghi đè cấu hình từ biến môi trường."""
    # API keys
    keys = _extract_gemini_keys(env)
    if keys:
        cfg.ai.api_keys = keys

    # AI Model & fallback
    if env.get("GEMINI_MODEL"):
        cfg.ai.model = str(env["GEMINI_MODEL"]).strip()
        cfg.ai.fallback_model = _derive_fallback_model(cfg.ai.model)
    if env.get("GEMINI_FALLBACK_MODEL"):
        cfg.ai.fallback_model = str(env["GEMINI_FALLBACK_MODEL"]).strip()
    if env.get("AI_MAX_RPM"):
        try:
            cfg.ai.max_rpm = int(str(env["AI_MAX_RPM"]).strip())
        except ValueError:
            pass

    # Concurrency
    pw_env = env.get("PW_MAX_CONCURRENCY") or env.get("PLAYWRIGHT_CONCURRENCY")
    if pw_env:
        try:
            cfg.scraper.playwright_concurrency = int(str(pw_env).strip())
        except ValueError:
            pass

    ph_env = env.get("PER_HOST_MAX_CONCURRENCY") or env.get("PER_HOST_CONCURRENCY")
    if ph_env:
        try:
            cfg.scraper.per_host_concurrency = int(str(ph_env).strip())
        except ValueError:
            pass

    # Output & Paths
    if env.get("OUTPUT_MODE"):
        cfg.output.mode = str(env["OUTPUT_MODE"]).strip()
    out_dir_env = env.get("OUTPUT_DIR")
    if out_dir_env:
        d = str(out_dir_env).strip()
        cfg.output.dir = d
        cfg.paths.output_dir = d
    if env.get("LINKS_FILE"):
        cfg.paths.links_file = str(env["LINKS_FILE"]).strip()
    if env.get("ISSUES_FILE"):
        cfg.paths.issues_file = str(env["ISSUES_FILE"]).strip()


def _apply_cli(cfg: Settings, args: dict[str, Any] | Any) -> None:
    """Ghi đè cấu hình từ tham số dòng lệnh (CLI)."""
    arg_dict = args if isinstance(args, dict) else vars(args)

    if arg_dict.get("output_mode"):
        cfg.output.mode = str(arg_dict["output_mode"])
    if arg_dict.get("output_dir"):
        d = str(arg_dict["output_dir"])
        cfg.output.dir = d
        cfg.paths.output_dir = d
    if arg_dict.get("max_pw_instances") is not None:
        cfg.scraper.playwright_concurrency = int(arg_dict["max_pw_instances"])
    if arg_dict.get("per_host_concurrency") is not None:
        cfg.scraper.per_host_concurrency = int(arg_dict["per_host_concurrency"])
    if arg_dict.get("fast_learning") is not None:
        cfg.fast_learning = bool(arg_dict["fast_learning"])
    if arg_dict.get("no_validation") is not None:
        cfg.no_validation = bool(arg_dict["no_validation"])
    if arg_dict.get("bulk_relearn") is not None:
        cfg.bulk_relearn = bool(arg_dict["bulk_relearn"])
    if arg_dict.get("pattern") is not None:
        cfg.pattern = str(arg_dict["pattern"])
    if arg_dict.get("apply") is not None:
        cfg.apply = bool(arg_dict["apply"])


# Global singleton access
_ACTIVE_SETTINGS: Settings | None = None


def get_settings() -> Settings:
    """Lấy hoặc khởi tạo cấu hình singleton cho ứng dụng."""
    global _ACTIVE_SETTINGS
    if _ACTIVE_SETTINGS is None:
        _ACTIVE_SETTINGS = Settings.load()
    return _ACTIVE_SETTINGS


def set_settings(settings: Settings | None) -> None:
    """Gán cấu hình singleton (thường dùng cho test hoặc sau khi parse CLI)."""
    global _ACTIVE_SETTINGS
    _ACTIVE_SETTINGS = settings
