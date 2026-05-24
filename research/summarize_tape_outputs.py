"""Compact summary for tape_auction_probe output files."""

from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path


DEFAULT_DATES = [
    "2026-05-05",
    "2026-05-06",
    "2026-05-07",
    "2026-05-08",
    "2026-05-10",
    "2026-05-11",
    "2026-05-12",
    "2026-05-13",
    "2026-05-14",
    "2026-05-15",
    "2026-05-18",
    "2026-05-19",
    "2026-05-20",
    "2026-05-21",
    "2026-05-22",
]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--out-dir", default=str(Path(__file__).with_name("out")))
    p.add_argument("--dates", nargs="*", default=DEFAULT_DATES)
    return p.parse_args()


def load_breaks(path: Path) -> dict[tuple[str, str], dict[str, str]]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    return {(r["scope"], r["direction"]): r for r in rows}


def field_time(value: str) -> str:
    return value[11:19] if value else "-"


def main() -> None:
    args = parse_args()
    out_dir = Path(args.out_dir)
    for day in args.dates:
        txt_path = out_dir / f"tape_auction_{day}.txt"
        csv_path = out_dir / f"tape_auction_{day}.breaks.csv"
        if not txt_path.exists():
            print(f"\n{day} missing")
            continue
        text = txt_path.read_text(encoding="utf-8")
        rth = re.search(r"RTH : .*vol=([0-9]+)", text)
        gaps = re.search(r"Data gaps >= 5.0s: (\d+)", text)
        breaks = load_breaks(csv_path)

        print(f"\n{day} vol={rth.group(1) if rth else '?'} gaps={gaps.group(1) if gaps else '?'}")
        for key in [("OR5", "UP"), ("OR5", "DOWN"), ("IB", "UP"), ("IB", "DOWN")]:
            row = breaks.get(key)
            if not row:
                continue
            print(
                f"  {key[0]:<3} {key[1]:<4} {row['label']:<12} "
                f"cross={field_time(row['cross']):<8} moved={row['excursion']:>7} "
                f"vol={row['outside_vol']:>8} delta={row['outside_delta']:>8} "
                f"bins={row['accepted_bins']:>2} c15={row['close_15m'] or '-'}"
            )

        tags = []
        for tag in [
            "aggressive-flush",
            "thin-fast",
            "cap-empty",
            "no-lower-followup",
            "new_rth_high",
            "new_rth_low",
        ]:
            count = text.count(tag)
            if count:
                tags.append(f"{tag}:{count}")
        print("  tags " + (", ".join(tags) if tags else "-"))


if __name__ == "__main__":
    main()
