r"""MCP wrapper for GexBot options context.

Launch from `C:\Heatmap\GexBotMcp` with:

    uv run python -m gexbot_mcp.mcp_server
"""

from __future__ import annotations

import logging
import os
import sys
from typing import Any

from mcp.server.fastmcp import FastMCP

from .client import GexBotApiError, GexBotClient
from .context import build_decision_context, snapshot_summary


MCP_HOST = os.getenv("MCP_HOST", "127.0.0.1")
MCP_PORT = int(os.getenv("MCP_PORT", "8789"))
MCP_TRANSPORT = os.getenv("MCP_TRANSPORT", "streamable-http")

mcp = FastMCP("gexbot-context", host=MCP_HOST, port=MCP_PORT)
logger = logging.getLogger("gexbot_mcp")


@mcp.tool()
def gexbot_health(network_check: bool = False) -> dict[str, Any]:
    """Report local GexBot MCP configuration and optionally probe public tickers."""

    return _call(lambda client: client.health(network_check=network_check))


@mcp.tool()
def gexbot_tickers() -> dict[str, Any]:
    """Return public GexBot ticker groups."""

    return _call(lambda client: client.tickers())


@mcp.tool()
def gexbot_categories(package: str = "classic") -> dict[str, Any]:
    """Return category names for a GexBot package."""

    return _call(lambda client: {"package": package, "categories": client.categories(package)})


@mcp.tool()
def gexbot_snapshot(
    ticker: str = "ES_SPX",
    package: str = "classic",
    category: str = "gex_full",
    view: str = "chain",
) -> dict[str, Any]:
    """Fetch a raw GexBot snapshot with a small metadata summary."""

    def run(client: GexBotClient) -> dict[str, Any]:
        payload = _snapshot(client, ticker=ticker, package=package, category=category, view=view)
        return {
            "ok": True,
            "ticker": ticker.upper(),
            "package": package,
            "category": category,
            "view": view,
            "summary": snapshot_summary(payload),
            "raw": payload,
        }

    return _call(run)


@mcp.tool()
def gexbot_decision_context(
    ticker: str = "ES_SPX",
    package: str = "classic",
    category: str = "gex_full",
    center_price: float | None = None,
    radius_points: float | None = None,
    max_strikes: int = 16,
    tick_size: float = 0.25,
    zone_ticks: int = 8,
) -> dict[str, Any]:
    """Return normalized GexBot context for Prep, Saavik, or Kahn waypoint review."""

    def run(client: GexBotClient) -> dict[str, Any]:
        payload = client.chart(ticker=ticker, package=package, category=category)
        context = build_decision_context(
            payload,
            package=package,
            category=category,
            center_price=center_price,
            radius_points=radius_points,
            max_strikes=max_strikes,
            tick_size=tick_size,
            zone_ticks=zone_ticks,
        )
        return context

    return _call(run)


def run_server() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s:%(name)s:%(message)s",
        stream=sys.stderr,
        force=True,
    )
    url = f"http://{MCP_HOST}:{MCP_PORT}/mcp" if MCP_TRANSPORT == "streamable-http" else "stdio"
    logger.info(
        "MCP up and running and is healthy (server=gexbot-context transport=%s url=%s)",
        MCP_TRANSPORT,
        url,
    )
    mcp.run(transport=MCP_TRANSPORT)


def _call(func: Any) -> dict[str, Any]:
    try:
        return func(GexBotClient())
    except (GexBotApiError, ValueError) as exc:
        status = getattr(exc, "status", None)
        return {"ok": False, "error": str(exc), "status": status}


def _snapshot(
    client: GexBotClient,
    *,
    ticker: str,
    package: str,
    category: str,
    view: str,
) -> dict[str, Any]:
    normalized_view = view.lower().strip()
    if normalized_view == "chain":
        return client.chart(ticker=ticker, package=package, category=category)
    if normalized_view == "majors":
        return client.majors(ticker=ticker, package=package, category=category)
    if normalized_view == "maxchange":
        return client.maxchange(ticker=ticker, package=package, category=category)
    if normalized_view == "orderflow":
        return client.orderflow(ticker=ticker)
    raise ValueError("view must be one of chain, majors, maxchange, orderflow")


if __name__ == "__main__":
    run_server()
