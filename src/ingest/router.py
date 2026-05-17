"""
ingest/router.py — Input type detection (P3.2).

Detect input file type → dispatch to correct adapter.

Detection rules:
  *.epub                          → "epub"
  *.txt + line đầu match URL      → "web" (legacy links.txt)
  *.txt + line đầu KHÔNG URL      → "txt"
  Anything else                   → "web" (default — backward compat)

Edge case: `.txt` mix URL + text → ưu tiên web nếu line đầu là URL.
Quyết định này pragmatic — links.txt convention nói URL ở đầu file.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Literal

# Match http:// hoặc https:// ở đầu line (case-insensitive)
URL_PATTERN = re.compile(r"^https?://", re.IGNORECASE)


def detect_input_type(path_or_file: str) -> Literal["web", "epub", "txt"]:
    """
    Detect input type từ file path.

    Returns:
        "epub" — file .epub
        "web"  — file .txt với URL ở line đầu (legacy links.txt)
        "txt"  — file .txt với text content (novel raw text)
        "web"  — default fallback cho extension khác (.json ?, no ext)
    """
    p      = Path(path_or_file)
    suffix = p.suffix.lower()

    if suffix == ".epub":
        return "epub"

    if suffix == ".txt":
        # Distinguish web (links.txt) vs txt (raw novel text)
        # Logic: scan tối đa 5 non-comment non-empty lines.
        # Nếu ≥1 line là URL hợp lệ → "web".
        # Nếu tất cả là text → "txt".
        try:
            with open(p, "r", encoding="utf-8") as f:
                for _ in range(5):
                    line = f.readline()
                    if not line:
                        break
                    line = line.strip()
                    if not line or line.startswith("#") or line.lower().startswith("!relearn"):
                        continue
                    if URL_PATTERN.match(line):
                        return "web"
                    # First non-comment line không phải URL → text content
                    return "txt"
        except Exception:
            return "txt"
        # File rỗng hoặc all comment → treat as "txt" (safer)
        return "txt"

    # Default fallback — backward compat
    return "web"
