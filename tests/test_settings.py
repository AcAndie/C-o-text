from __future__ import annotations

from pathlib import Path

import pytest

from cao_text.settings import Settings


def test_settings_defaults() -> None:
    """Kiểm tra các giá trị mặc định chuẩn của Settings."""
    cfg = Settings()
    assert cfg.output.mode == "obsidian"
    assert cfg.output.dir == "output"
    assert cfg.output.download_images is True
    assert cfg.paths.data_dir == "data"
    assert cfg.scraper.max_chapters == 5000
    assert cfg.scraper.per_host_concurrency == 3
    assert cfg.scraper.playwright_concurrency == 2
    assert cfg.learning.chapters == 10
    assert cfg.ai.max_rpm == 10
    assert cfg.http.request_timeout == 60.0
    assert cfg.js_detection.content_ratio == 1.5
    assert cfg.epub.analyzer == "ai"

    # Properties tiện ích
    assert cfg.output_mode == "obsidian"
    assert cfg.output_dir == "output"
    assert cfg.download_images is True
    assert cfg.profiles_file.endswith("site_profiles.json")
    assert cfg.ads_db_file.endswith("ads_keywords.json")


def test_gemini_key_extraction_and_order() -> None:
    """Kiểm tra regex chặt chẽ và thứ tự sắp xếp của GEMINI_API_KEY."""
    mock_env = {
        "GEMINI_API_KEY_2": "key-2",
        "GEMINI_API_KEY_DEV": "dev-key-ignore",
        "GEMINI_API_KEY_OLD": "old-key-ignore",
        "GEMINI_API_KEY": "primary-key",
        "GEMINI_API_KEY_1": "key-1",
        "GEMINI_API_KEY_10": "key-10",
        "GEMINI_API_KEY_DUPLICATE": "ignore",
        "OTHER_VAR": "something",
    }
    cfg = Settings.load(
        env_dict=mock_env,
        config_path=Path("non_existent_config.toml"),
        env_path=Path("non_existent_env"),
    )
    # Thứ tự phải là: GEMINI_API_KEY -> _1 -> _2 -> _10
    assert cfg.ai.api_keys == ["primary-key", "key-1", "key-2", "key-10"]
    assert cfg.get_primary_api_key() == "primary-key"
    assert cfg.require_api_keys() == ["primary-key", "key-1", "key-2", "key-10"]


def test_missing_api_key_only_fails_when_called() -> None:
    """Không có API key thì load() vẫn thành công; chỉ raise lỗi khi cần gọi AI."""
    cfg = Settings.load(
        env_dict={},
        config_path=Path("non_existent_config.toml"),
        env_path=Path("non_existent_env"),
    )
    assert cfg.ai.api_keys == []

    with pytest.raises(ValueError, match="Không tìm thấy GEMINI_API_KEY"):
        cfg.get_primary_api_key()

    with pytest.raises(ValueError, match="Không tìm thấy GEMINI_API_KEY"):
        cfg.require_api_keys()


def test_priority_order_cli_over_env_over_toml_over_default(tmp_path: Path) -> None:
    """Kiểm tra thứ tự ưu tiên: CLI > env > config.toml > code default."""
    toml_content = """
[output]
mode = "translate"
dir = "toml_output"

[scraper]
per_host_concurrency = 5
playwright_concurrency = 4
"""
    toml_file = tmp_path / "config.toml"
    toml_file.write_text(toml_content, encoding="utf-8")

    # 1. Chỉ toml -> toml đè default
    cfg1 = Settings.load(
        config_path=toml_file,
        env_dict={},
        env_path=Path("non_existent_env"),
    )
    assert cfg1.output.mode == "translate"
    assert cfg1.output.dir == "toml_output"
    assert cfg1.paths.output_dir == "toml_output"
    assert cfg1.scraper.per_host_concurrency == 5
    assert cfg1.scraper.playwright_concurrency == 4

    # 2. Env đè toml
    mock_env = {
        "OUTPUT_MODE": "raw",
        "PER_HOST_CONCURRENCY": "8",
        "GEMINI_MODEL": "gemini-2.5-pro",
    }
    cfg2 = Settings.load(
        config_path=toml_file,
        env_dict=mock_env,
        env_path=Path("non_existent_env"),
    )
    assert cfg2.output.mode == "raw"  # env thắng toml
    assert cfg2.scraper.per_host_concurrency == 8  # env thắng toml
    assert cfg2.scraper.playwright_concurrency == 4  # giữ toml vì env không set
    assert cfg2.ai.model == "gemini-2.5-pro"

    # 3. CLI đè env và toml
    cli_args = {
        "output_mode": "obsidian",
        "per_host_concurrency": 1,
        "max_pw_instances": 1,
    }
    cfg3 = Settings.load(
        cli_args=cli_args,
        config_path=toml_file,
        env_dict=mock_env,
        env_path=Path("non_existent_env"),
    )
    assert cfg3.output.mode == "obsidian"  # CLI thắng env
    assert cfg3.scraper.per_host_concurrency == 1  # CLI thắng env
    assert cfg3.scraper.playwright_concurrency == 1  # CLI thắng toml


def test_toml_sections_full_compatibility(tmp_path: Path) -> None:
    """Kiểm tra nạp đầy đủ các sections từ config.toml."""
    toml_content = """
[output]
mode = "translate"
dir = "Vault/Novels"
download_images = false

[paths]
data_dir = "custom_data"
output_dir = "Vault/Novels"
progress_dir = "custom_progress"
issues_file = "custom_issues.md"
links_file = "custom_links.txt"
epub_inbox_dir = "custom_epub_inbox"

[scraper]
max_chapters = 2000
max_consecutive_errors = 8
max_consecutive_timeouts = 4
timeout_backoff_base = 45.0
playwright_concurrency = 3
per_host_concurrency = 2
init_stagger = 3.5
empty_backoff_schedule = [30, 90, 180]

[learning]
chapters = 15
min_content = 500
profile_max_age_days = 60
ai_calls = 12
conflict_threshold = 4

[ai]
model = "gemini-2.5-flash"
fallback_model = "gemini-2.0-flash-lite"
max_rpm = 15
jitter = [1.0, 3.0]

[http]
request_timeout = 90.0

[js_detection]
content_ratio = 2.0
min_diff_chars = 600

[epub]
analyzer = "rules"
"""
    toml_file = tmp_path / "config.toml"
    toml_file.write_text(toml_content, encoding="utf-8")

    cfg = Settings.load(
        config_path=toml_file,
        env_dict={},
        env_path=Path("non_existent_env"),
    )

    assert cfg.output.mode == "translate"
    assert cfg.output.dir == "Vault/Novels"
    assert cfg.output.download_images is False

    assert cfg.paths.data_dir == "custom_data"
    assert cfg.paths.output_dir == "Vault/Novels"
    assert cfg.paths.progress_dir == "custom_progress"
    assert cfg.paths.issues_file == "custom_issues.md"
    assert cfg.paths.links_file == "custom_links.txt"
    assert cfg.paths.epub_inbox_dir == "custom_epub_inbox"

    assert cfg.scraper.max_chapters == 2000
    assert cfg.scraper.max_consecutive_errors == 8
    assert cfg.scraper.max_consecutive_timeouts == 4
    assert cfg.scraper.timeout_backoff_base == 45.0
    assert cfg.scraper.playwright_concurrency == 3
    assert cfg.scraper.per_host_concurrency == 2
    assert cfg.scraper.init_stagger == 3.5
    assert cfg.scraper.empty_backoff_schedule == [30, 90, 180]

    assert cfg.learning.chapters == 15
    assert cfg.learning.min_content == 500
    assert cfg.learning.profile_max_age_days == 60
    assert cfg.learning.ai_calls == 12
    assert cfg.learning.conflict_threshold == 4

    assert cfg.ai.model == "gemini-2.5-flash"
    assert cfg.ai.fallback_model == "gemini-2.0-flash-lite"
    assert cfg.ai.max_rpm == 15
    assert cfg.ai.jitter == (1.0, 3.0)

    assert cfg.http.request_timeout == 90.0
    assert cfg.js_detection.content_ratio == 2.0
    assert cfg.js_detection.min_diff_chars == 600
    assert cfg.epub.analyzer == "rules"


def test_corrupt_toml_fallback_to_default_without_crash(tmp_path: Path) -> None:
    """Khi config.toml bị lỗi cú pháp, Settings.load không crash mà dùng mặc định."""
    bad_toml = tmp_path / "bad_config.toml"
    bad_toml.write_text("this is invalid toml = = = [", encoding="utf-8")

    cfg = Settings.load(
        config_path=bad_toml,
        env_dict={},
        env_path=Path("non_existent_env"),
    )
    assert cfg.output.mode == "obsidian"
    assert cfg.scraper.max_chapters == 5000

