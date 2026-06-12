r"""Module wrapper for Dost's LevelLedger MCP server.

Launch from `C:\Heatmap\skills\dost` with:

    uv run python -m dost.mcp_server
"""

from __future__ import annotations

import sys
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import mcp_server as _server  # noqa: E402


mcp = _server.mcp
ll_ownership_bands = _server.ll_ownership_bands
run_server = _server.run_server


if __name__ == "__main__":
    run_server()
