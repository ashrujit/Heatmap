"""Module wrapper for Dost's LevelLedger band CLI.

This keeps `uv run python -m dost.ll_bands` available while the canonical
implementation stays in the skill's scripts directory.
"""

from __future__ import annotations

import sys
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from ll_bands import *  # noqa: F401,F403,E402
from ll_bands import main  # noqa: E402


if __name__ == "__main__":
    main()
