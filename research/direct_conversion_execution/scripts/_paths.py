"""Stable filesystem roots for the direct-conversion research package."""

from __future__ import annotations

import sys
from pathlib import Path


SCRIPT_ROOT = Path(__file__).resolve().parent
PACKAGE_ROOT = SCRIPT_ROOT.parent
RESEARCH_ROOT = PACKAGE_ROOT.parent
REPO_ROOT = RESEARCH_ROOT.parent
OUTPUT_ROOT = PACKAGE_ROOT / "out"

for import_root in (SCRIPT_ROOT, RESEARCH_ROOT):
    value = str(import_root)
    if value not in sys.path:
        sys.path.insert(0, value)
