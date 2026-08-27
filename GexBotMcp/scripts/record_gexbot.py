from __future__ import annotations

import argparse
import logging
import sys
import time
from dataclasses import replace
from pathlib import Path


SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from gexbot_mcp.service import (  # noqa: E402
    DEFAULT_CATEGORIES,
    DEFAULT_TICKERS,
    GexBotServiceConfig,
    GexBotSnapshotService,
    format_poll_result,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Debug wrapper for the GexBot SQLite cache poller.")
    parser.add_argument("--tickers", default=",".join(DEFAULT_TICKERS), help="Comma-separated tickers")
    parser.add_argument("--categories", default=",".join(DEFAULT_CATEGORIES), help="Comma-separated Classic categories")
    parser.add_argument("--interval-sec", type=float, default=60.0, help="Seconds between polls")
    parser.add_argument("--duration-min", type=float, default=0.0, help="Stop after this many minutes; 0 runs until Ctrl+C")
    parser.add_argument("--once", action="store_true", help="Capture one poll and exit")
    parser.add_argument("--cache-path", default=None, help="Override SQLite cache path")
    args = parser.parse_args()

    logging.basicConfig(level=logging.WARNING)
    config = GexBotServiceConfig.from_env()
    updates = {
        "poll_enabled": False,
        "poll_tickers": tuple(_split_csv(args.tickers)),
        "poll_categories": tuple(_split_csv(args.categories)),
        "poll_interval_sec": max(5.0, args.interval_sec),
    }
    if args.cache_path:
        updates["cache_path"] = Path(args.cache_path)
    service = GexBotSnapshotService(config=replace(config, **updates))

    print(
        "INFO: polling GexBot SQLite cache "
        f"tickers={','.join(service.config.poll_tickers)} "
        f"categories={','.join(service.config.poll_categories)} "
        f"interval_sec={service.config.poll_interval_sec:g} db={service.cache.path}"
    )
    deadline = None if args.once or args.duration_min <= 0 else time.monotonic() + args.duration_min * 60.0
    try:
        while True:
            started = time.monotonic()
            for result in service.poll_once():
                print(format_poll_result(result))
            if args.once:
                return 0
            if deadline is not None and time.monotonic() >= deadline:
                return 0
            time.sleep(max(1.0, service.config.poll_interval_sec - (time.monotonic() - started)))
    except KeyboardInterrupt:
        print("INFO: stopped by user")
        return 0
    finally:
        service.stop_background_poller()
        service.cache.close()


def _split_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


if __name__ == "__main__":
    raise SystemExit(main())
