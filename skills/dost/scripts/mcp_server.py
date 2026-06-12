r"""Optional MCP wrapper for Dost's LevelLedger band adapter.

Run directly with:

    uv run --with polars --with tzdata --with mcp python skills\dost\scripts\mcp_server.py

Canonical package launch from `C:\Heatmap\skills\dost`:

    uv run python -m dost.mcp_server

Default transport is streamable-http at `http://127.0.0.1:8788/mcp`.

The server exposes one tool, `ll_ownership_bands`, and returns the same JSON
shape as `ll_bands.py`.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from ll_bands import Query, run_query  # noqa: E402


MCP_HOST = os.getenv("MCP_HOST", "127.0.0.1")
MCP_PORT = int(os.getenv("MCP_PORT", "8788"))
MCP_TRANSPORT = os.getenv("MCP_TRANSPORT", "streamable-http")

mcp = FastMCP("dost-levelledger", host=MCP_HOST, port=MCP_PORT)
logger = logging.getLogger("dost.mcp")


@mcp.tool()
def ll_ownership_bands(
    date: str,
    symbol_dir: str = "NQM6",
    window: str = "09:30-10:30",
    warmup_min: int = 90,
    topn: int = 10,
    max_transitions: int = 120,
) -> dict[str, Any]:
    """Replay LevelLedger ownership bands and return structured band state."""

    return run_query(
        Query(
            date=date,
            symbol_dir=symbol_dir,
            window=window,
            warmup_min=warmup_min,
            topn=topn,
            max_transitions=max_transitions,
        )
    )


def run_server() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s:%(name)s:%(message)s",
        stream=sys.stderr,
        force=True,
    )
    url = f"http://{MCP_HOST}:{MCP_PORT}/mcp" if MCP_TRANSPORT == "streamable-http" else "stdio"
    logger.info(
        "MCP up and running and is healthy (server=dost-levelledger transport=%s url=%s)",
        MCP_TRANSPORT,
        url,
    )
    mcp.run(transport=MCP_TRANSPORT)


if __name__ == "__main__":
    run_server()
