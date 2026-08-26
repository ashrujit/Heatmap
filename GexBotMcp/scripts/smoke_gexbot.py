#!/usr/bin/env python3
"""Live smoke helper for the GexBot MCP prototype."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from gexbot_mcp.client import GexBotApiError, GexBotClient  # noqa: E402
from gexbot_mcp.context import build_decision_context, snapshot_summary  # noqa: E402


def command_health(args: argparse.Namespace) -> dict[str, Any]:
    return GexBotClient().health(network_check=args.network_check)


def command_tickers(args: argparse.Namespace) -> dict[str, Any]:
    return GexBotClient().tickers()


def command_categories(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "package": args.package,
        "categories": GexBotClient().categories(args.package),
    }


def command_snapshot(args: argparse.Namespace) -> dict[str, Any]:
    client = GexBotClient()
    if args.view == "chain":
        payload = client.chart(args.ticker, args.package, args.category)
    elif args.view == "majors":
        payload = client.majors(args.ticker, args.package, args.category)
    elif args.view == "maxchange":
        payload = client.maxchange(args.ticker, args.package, args.category)
    elif args.view == "orderflow":
        payload = client.orderflow(args.ticker)
    else:
        raise ValueError("unsupported view")
    return {"summary": snapshot_summary(payload), "raw": payload if args.raw else None}


def command_decision_context(args: argparse.Namespace) -> dict[str, Any]:
    payload = GexBotClient().chart(args.ticker, args.package, args.category)
    return build_decision_context(
        payload,
        package=args.package,
        category=args.category,
        center_price=args.center_price,
        radius_points=args.radius_points,
        max_strikes=args.max_strikes,
        tick_size=args.tick_size,
        zone_ticks=args.zone_ticks,
    )


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)

    health = sub.add_parser("health")
    health.add_argument("--network-check", action="store_true")
    health.set_defaults(func=command_health)

    tickers = sub.add_parser("tickers")
    tickers.set_defaults(func=command_tickers)

    categories = sub.add_parser("categories")
    categories.add_argument("--package", default="classic", choices=["classic", "state", "orderflow"])
    categories.set_defaults(func=command_categories)

    snapshot = sub.add_parser("snapshot")
    add_common(snapshot)
    snapshot.add_argument("--view", default="chain", choices=["chain", "majors", "maxchange", "orderflow"])
    snapshot.add_argument("--raw", action="store_true")
    snapshot.set_defaults(func=command_snapshot)

    context = sub.add_parser("decision-context")
    add_common(context)
    context.add_argument("--center-price", type=float, default=None)
    context.add_argument("--radius-points", type=float, default=None)
    context.add_argument("--max-strikes", type=int, default=16)
    context.add_argument("--tick-size", type=float, default=0.25)
    context.add_argument("--zone-ticks", type=int, default=8)
    context.set_defaults(func=command_decision_context)
    return p


def add_common(p: argparse.ArgumentParser) -> None:
    p.add_argument("--ticker", default="ES_SPX")
    p.add_argument("--package", default="classic", choices=["classic", "state", "orderflow"])
    p.add_argument("--category", default="gex_full")


def main() -> int:
    args = parser().parse_args()
    try:
        result = args.func(args)
    except (GexBotApiError, ValueError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2), file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
