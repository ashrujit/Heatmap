"""Research-only add policy probe.

This simulates a conservative continuation/add rule for a long directive:
record new demand bands, but only allow an add after the band's first retest
survives. It does not emulate EAR order management or account state.
"""

from __future__ import annotations

import argparse
import bisect
import csv
import math
import sys
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "research"))
sys.path.insert(0, str(ROOT / "LevelLedger" / "research"))

from capture_loader import load_capture_window, snapshot_columns, us  # noqa: E402
from ownership_bands_probe import OwnershipBand, OwnershipProbe, Transition  # noqa: E402
from replay_levelledger import build_sample  # noqa: E402

NY = ZoneInfo("America/New_York")
TICK_SIZE = 0.25
DEPTH_LEVELS = 30


def ny_dt(day: str, value: str) -> datetime:
    fmt = "%Y-%m-%d %H:%M:%S" if value.count(":") == 2 else "%Y-%m-%d %H:%M"
    return datetime.strptime(f"{day} {value}", fmt).replace(tzinfo=NY)


def ny_hms(ts: datetime | None) -> str:
    if ts is None:
        return ""
    return ts.astimezone(NY).strftime("%H:%M:%S")


def price(tick: int | None) -> str:
    if tick is None:
        return ""
    return f"{tick * TICK_SIZE:.2f}"


def default_probe() -> OwnershipProbe:
    return OwnershipProbe(
        event_z=2.5,
        cluster_min_events=3,
        cluster_ticks=10,
        cluster_sec=90,
        cluster_min_score=8.0,
        confirm_ticks=8,
        confirm_sec=10,
        test_buffer_ticks=4,
        fail_buffer_ticks=2,
        fail_confirm_ticks=8,
        fail_sec=10,
        hold_confirm_ticks=10,
    )


def snapshot_ticks(
    snapshots: list[dict[str, Any]],
    snap_us: list[int],
    start_us: int,
    end_us: int,
) -> list[int]:
    start = bisect.bisect_left(snap_us, start_us)
    end = bisect.bisect_left(snap_us, end_us)
    return [int(row["ref_tick"]) for row in snapshots[start:end]]


def first_after(items: list[Transition], ts: datetime, actions: set[str]) -> Transition | None:
    for item in items:
        if item.ts > ts and item.action in actions:
            return item
    return None


def row_status(first_test: Transition | None, first_after_test: Transition | None) -> str:
    if first_test is None:
        return "no_retest_before_end"
    if first_after_test is None:
        return "tested_unresolved"
    if first_after_test.action == "HOLD":
        return "first_retest_survived"
    if first_after_test.action == "FAIL":
        return "first_retest_failed"
    return "tested_unresolved"


def analyze_symbol_window(args: argparse.Namespace, symbol: str, window: str) -> list[dict[str, Any]]:
    start_s, end_s = window.split("-", 1)
    start_ny = ny_dt(args.date, start_s)
    end_ny = ny_dt(args.date, end_s)
    replay_start = start_ny - timedelta(minutes=args.warmup_min)

    snapshots_df = load_capture_window(
        "snapshots",
        symbol,
        replay_start,
        end_ny,
        snapshot_columns(DEPTH_LEVELS),
        inclusive_end=True,
    )
    snapshots = list(snapshots_df.iter_rows(named=True))
    snap_us = [int(row["timestamp_us"]) for row in snapshots]

    probe = default_probe()
    for row in snapshots:
        probe.on_sample(build_sample(row))

    start_us = us(start_ny)
    end_us = us(end_ny)
    transitions = [tr for tr in probe.transitions if start_ny <= tr.ts.astimezone(NY) <= end_ny]
    by_band: dict[int, list[Transition]] = {}
    for tr in transitions:
        by_band.setdefault(tr.band_id, []).append(tr)
    bands_by_id: dict[int, OwnershipBand] = {band.id: band for band in probe.bands}

    rows: list[dict[str, Any]] = []
    for tr in transitions:
        if tr.side != "demand" or tr.action not in {"OWNED", "CONSUMED"}:
            continue
        band = bands_by_id.get(tr.band_id)
        if band is None:
            continue
        if tr.current_mid_tick <= tr.max_tick:
            continue

        band_events = by_band.get(tr.band_id, [])
        first_test = first_after(band_events, tr.ts, {"TEST"})
        first_post_test = first_after(band_events, first_test.ts, {"HOLD", "FAIL"}) if first_test else None
        status = row_status(first_test, first_post_test)
        add_ts = first_post_test.ts if first_post_test is not None and first_post_test.action == "HOLD" else None
        add_tick = first_post_test.current_mid_tick if first_post_test is not None and first_post_test.action == "HOLD" else None

        mfe = ""
        mae = ""
        if add_ts is not None and add_tick is not None:
            ticks = snapshot_ticks(snapshots, snap_us, int(add_ts.timestamp() * 1_000_000), end_us)
            if ticks:
                mfe = max(ticks) - add_tick
                mae = add_tick - min(ticks)

        create_dist = tr.current_mid_tick - tr.max_tick
        hold_dist = add_tick - tr.max_tick if add_tick is not None else ""
        immediate_eligible = 0 <= create_dist <= args.immediate_max_ticks
        failed_before_hold = band.failed_ts is not None and (add_ts is None or band.failed_ts <= add_ts)

        rows.append(
            {
                "date": args.date,
                "symbol": symbol,
                "window": window,
                "band_id": tr.band_id,
                "owned_et": ny_hms(tr.ts),
                "source": band.source,
                "action": tr.action,
                "range": f"{price(tr.min_tick)}-{price(tr.max_tick)}",
                "create_mid": price(tr.current_mid_tick),
                "create_distance_ticks": create_dist,
                "immediate_eligible": "true" if immediate_eligible else "false",
                "first_test_et": ny_hms(first_test.ts if first_test else None),
                "first_test_mid": price(first_test.current_mid_tick if first_test else None),
                "first_resolution": first_post_test.action if first_post_test else "",
                "first_resolution_et": ny_hms(first_post_test.ts if first_post_test else None),
                "hold_entry_mid": price(add_tick),
                "hold_entry_distance_ticks": hold_dist,
                "status": status,
                "failed_before_hold": "true" if failed_before_hold else "false",
                "formal_fail_et": ny_hms(band.failed_ts),
                "mfe_ticks_to_end": mfe,
                "mae_ticks_to_end": mae,
                "score": f"{tr.score:.3f}",
                "kinds": tr.note,
            }
        )
    return rows


def write_markdown(path: Path, rows: list[dict[str, Any]], args: argparse.Namespace) -> None:
    counts = Counter(row["status"] for row in rows)
    by_symbol = Counter((row["symbol"], row["status"]) for row in rows)
    immediate_counts = Counter(row["status"] for row in rows if row["immediate_eligible"] == "true")
    lines = [
        f"# Retest Survival Add Probe - {args.date}",
        "",
        "Research output only. This is a hypothetical long-side add filter, not an EAR rule.",
        "",
        f"- windows: `{args.windows}`",
        f"- symbols: `{args.symbols}`",
        f"- immediate eligibility proxy: creation distance `0-{args.immediate_max_ticks}` ticks beyond band",
        f"- demand extension rows: `{len(rows)}`",
        "",
        "## Status Counts",
        "",
    ]
    for label, count in counts.most_common():
        lines.append(f"- `{label}`: {count}")
    lines.extend(["", "## Symbol / Status Counts", ""])
    for (symbol, label), count in sorted(by_symbol.items()):
        lines.append(f"- `{symbol}` `{label}`: {count}")
    lines.extend(["", "## Immediate-Eligible Rows By Retest Outcome", ""])
    for label, count in immediate_counts.most_common():
        lines.append(f"- `{label}`: {count}")
    lines.extend(
        [
            "",
            "## Rows",
            "",
            "| Symbol | Owned | Demand | Src | Create Dist | Immediate | Test | Resolution | Hold Dist | Status | MFE | MAE |",
            "|---|---:|---|---|---:|---|---:|---|---:|---|---:|---:|",
        ]
    )
    for row in rows:
        lines.append(
            "| {symbol} | {owned_et} | {range} | {source} | {create_distance_ticks} | "
            "{immediate_eligible} | {first_test_et} | {first_resolution_et} {first_resolution} | "
            "{hold_entry_distance_ticks} | {status} | {mfe_ticks_to_end} | {mae_ticks_to_end} |".format(**row)
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default="2026-08-21")
    parser.add_argument("--symbols", default="NQU6,ESU6")
    parser.add_argument("--windows", default="10:20-12:00")
    parser.add_argument("--warmup-min", type=int, default=60)
    parser.add_argument("--immediate-max-ticks", type=int, default=20)
    parser.add_argument("--out-dir", default="research/out/retest_survival_add_2026-08-21")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    for symbol in [item.strip() for item in args.symbols.split(",") if item.strip()]:
        for window in [item.strip() for item in args.windows.split(",") if item.strip()]:
            print(f"retest survival replay {args.date}:{symbol}:{window}", flush=True)
            rows.extend(analyze_symbol_window(args, symbol, window))
    rows.sort(key=lambda row: (row["symbol"], row["owned_et"], row["band_id"]))

    csv_path = out_dir / "retest_survival_add_rows.csv"
    fields = list(rows[0].keys()) if rows else []
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    write_markdown(out_dir / "summary.md", rows, args)
    print(f"wrote {csv_path}")
    print(f"wrote {out_dir / 'summary.md'}")


if __name__ == "__main__":
    main()
