from __future__ import annotations

import pytest

import cao_text
from cao_text.cli import main


def test_smoke_setup() -> None:
    """Kiểm tra package cao_text có thể import và có __version__."""
    assert cao_text.__version__ == "2.0.0"


def test_cli_help(capsys: pytest.CaptureFixture[str]) -> None:
    """Kiểm tra `cao_text.cli.main(['--help'])` in ra hướng dẫn sử dụng."""
    with pytest.raises(SystemExit) as exc_info:
        main(["--help"])
    assert exc_info.value.code == 0
    captured = capsys.readouterr()
    assert "cao-text" in captured.out
    assert "--output-mode" in captured.out
