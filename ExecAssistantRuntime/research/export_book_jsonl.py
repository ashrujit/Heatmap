"""Stream MarketRecorder DOM snapshots as compact JSONL for the C# replay probe."""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path


RESEARCH_ROOT = Path(__file__).resolve().parents[2] / "LevelLedger" / "research"
sys.path.insert(0, str(RESEARCH_ROOT))

from candidate_timing_probe import load_filtered_snapshots  # noqa: E402
from replay_levelledger import parse_ny  # noqa: E402


def levels(row: dict, side: str) -> list[list[float]]:
    result: list[list[float]] = []
    ref_tick = int(row["ref_tick"])
    for index in range(30):
        offset = int(row[f"{side}_offset_{index}"])
        price = (ref_tick + offset) * 0.25
        size = float(row[f"{side}_size_{index}"])
        if math.isfinite(price) and price > 0 and math.isfinite(size) and size > 0:
            result.append([price, size])
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--capture-root", required=True)
    parser.add_argument("--date", required=True)
    parser.add_argument("--symbol-dir", required=True)
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--output")
    args = parser.parse_args()

    snapshots = load_filtered_snapshots(
        args.capture_root,
        args.symbol_dir,
        args.date,
        parse_ny(args.date, args.start),
        parse_ny(args.date, args.end),
    )
    output = open(args.output, "w", encoding="utf-8") if args.output else sys.stdout
    try:
        for row in snapshots.iter_rows(named=True):
            payload = {
                "t": int(row["timestamp_us"]),
                "b": levels(row, "bid"),
                "a": levels(row, "ask"),
            }
            output.write(json.dumps(payload, separators=(",", ":")))
            output.write("\n")
    finally:
        if output is not sys.stdout:
            output.close()


if __name__ == "__main__":
    main()
