"""Entrypoint shim for Cào Text v2."""
from __future__ import annotations

import os
import sys

# Ensure src/ is on sys.path if invoked as a plain script without editable install
_SRC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "src")
if _SRC_DIR not in sys.path:
    sys.path.insert(0, _SRC_DIR)

from cao_text.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
