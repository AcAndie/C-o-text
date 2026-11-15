"""Lọc DOM, định dạng Markdown, làm sạch nội dung và lọc quảng cáo."""
from __future__ import annotations

from cao_text.html.filter import (
    KNOWN_NOISE_SELECTORS,
    prepare_soup,
)

__all__ = [
    "KNOWN_NOISE_SELECTORS",
    "prepare_soup",
]
