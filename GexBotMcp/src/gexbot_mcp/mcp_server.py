r"""MCP wrapper for cached GexBot options context.

Launch from `C:\Heatmap\GexBotMcp` with:

    uv run python -m gexbot_mcp.mcp_server
"""

from __future__ import annotations

import logging
import os
import sys
from typing import Any

from mcp.server.fastmcp import FastMCP

from .client import GexBotApiError
from .service import GexBotSnapshotService


MCP_HOST = os.getenv("MCP_HOST", "127.0.0.1")
MCP_PORT = int(os.getenv("MCP_PORT", "8789"))
MCP_TRANSPORT = os.getenv("MCP_TRANSPORT", "streamable-http")

mcp = FastMCP("gexbot-context", host=MCP_HOST, port=MCP_PORT)
logger = logging.getLogger("gexbot_mcp")
_service_instance: GexBotSnapshotService | None = None


@mcp.tool()
def gexbot_health(network_check: bool = False) -> dict[str, Any]:
    """Report local GexBot MCP, cache, poller, and optional network status."""

    return _call(lambda service: service.health(network_check=network_check))


@mcp.tool()
def gexbot_cache_status() -> dict[str, Any]:
    """Return SQLite cache stats and latest cached groups."""

    return _call(lambda service: service.cache_status())


@mcp.tool()
def gexbot_tickers() -> dict[str, Any]:
    """Return public GexBot ticker groups."""

    return _call(lambda service: service.client.tickers())


@mcp.tool()
def gexbot_categories(package: str = "classic") -> dict[str, Any]:
    """Return category names for a GexBot package."""

    return _call(lambda service: {"package": package, "categories": service.client.categories(package)})


@mcp.tool()
def gexbot_refresh(
    tickers: str = "",
    categories: str = "",
) -> dict[str, Any]:
    """Force one poll into the SQLite cache for configured or supplied tickers/categories."""

    def run(service: GexBotSnapshotService) -> dict[str, Any]:
        result = service.poll_once(
            tickers=tuple(_split_csv(tickers)) or None,
            categories=tuple(_split_csv(categories)) or None,
        )
        return {"ok": True, "count": len(result), "results": result, "cache": service.cache.stats()}

    return _call(run)


@mcp.tool()
def gexbot_snapshot(
    ticker: str = "ES_SPX",
    package: str = "classic",
    category: str = "gex_full",
    view: str = "chain",
    max_age_sec: float | None = None,
    force_refresh: bool = False,
) -> dict[str, Any]:
    """Fetch a raw GexBot snapshot, using the local cache for chain views."""

    return _call(
        lambda service: service.snapshot(
            ticker=ticker,
            package=package,
            category=category,
            view=view,
            max_age_sec=max_age_sec,
            force_refresh=force_refresh,
        )
    )


@mcp.tool()
def gexbot_decision_context(
    ticker: str = "ES_SPX",
    package: str = "classic",
    category: str = "gex_full",
    center_price: float | None = None,
    radius_points: float | None = None,
    max_strikes: int | None = None,
    tick_size: float | None = None,
    zone_ticks: int | None = None,
    max_age_sec: float | None = None,
    force_refresh: bool = False,
) -> dict[str, Any]:
    """Return normalized GexBot context for Prep, Saavik, or Kahn waypoint review."""

    return _call(
        lambda service: service.decision_context(
            ticker=ticker,
            package=package,
            category=category,
            center_price=center_price,
            radius_points=radius_points,
            max_strikes=max_strikes,
            tick_size=tick_size,
            zone_ticks=zone_ticks,
            max_age_sec=max_age_sec,
            force_refresh=force_refresh,
        )
    )


@mcp.tool()
def gexbot_wall_history(
    ticker: str = "ES_SPX",
    package: str = "classic",
    category: str = "gex_zero",
    since: str | None = None,
    until: str | None = None,
    session_date: str | None = None,
    since_minutes: float | None = None,
    limit: int = 500,
    refresh: bool = True,
    force_refresh: bool = False,
) -> dict[str, Any]:
    """Return cached wall history and wall-change events for a ticker/category."""

    return _call(
        lambda service: service.wall_history(
            ticker=ticker,
            package=package,
            category=category,
            since=since,
            until=until,
            session_date=session_date,
            since_minutes=since_minutes,
            limit=limit,
            refresh=refresh,
            force_refresh=force_refresh,
        )
    )


def run_server() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s:%(name)s:%(message)s",
        stream=sys.stderr,
        force=True,
    )
    service = _get_service()
    service.start_background_poller()
    url = f"http://{MCP_HOST}:{MCP_PORT}/mcp" if MCP_TRANSPORT == "streamable-http" else "stdio"
    logger.info(
        "MCP up and running and is healthy (server=gexbot-context transport=%s url=%s cache=%s)",
        MCP_TRANSPORT,
        url,
        service.cache.path,
    )
    try:
        mcp.run(transport=MCP_TRANSPORT)
    finally:
        service.stop_background_poller()


def _call(func: Any) -> dict[str, Any]:
    try:
        return func(_get_service())
    except (GexBotApiError, ValueError) as exc:
        status = getattr(exc, "status", None)
        return {"ok": False, "error": str(exc), "status": status}


def _get_service() -> GexBotSnapshotService:
    global _service_instance
    if _service_instance is None:
        _service_instance = GexBotSnapshotService()
    return _service_instance


def _split_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


if __name__ == "__main__":
    run_server()
