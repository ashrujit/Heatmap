"""Research-only extension response probe.

This asks what happens after a long campaign encounters supply. It deliberately
uses ownership bands as event sources, not as the primary object being judged:
the row is the supply encounter and the measured object is the extension
response after that encounter.
"""

from __future__ import annotations

import argparse
import bisect
import csv
import math
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "research"))
sys.path.insert(0, str(ROOT / "LevelLedger" / "research"))

from capture_loader import load_capture_window, snapshot_columns, tick_columns, us  # noqa: E402
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


def tick_to_price(tick: int | None) -> str:
    if tick is None:
        return ""
    return f"{tick * TICK_SIZE:.2f}"


def seconds_between(start: datetime, end: datetime | None) -> str:
    if end is None:
        return ""
    return f"{(end - start).total_seconds():.3f}"


def fmt_float(value: float | None, digits: int = 3) -> str:
    if value is None or not math.isfinite(value):
        return ""
    return f"{value:.{digits}f}"


def relation_tick(mid_tick: int, lo_tick: int, hi_tick: int) -> str:
    if mid_tick > hi_tick:
        return "beyond"
    if mid_tick < lo_tick:
        return "old"
    return "inside"


def overlap_or_near(a_lo: int, a_hi: int, b_lo: int, b_hi: int, ticks: int) -> bool:
    return not (a_hi < b_lo - ticks or b_hi < a_lo - ticks)


def midpoint_tick(row: dict[str, Any]) -> int:
    return int(row["ref_tick"])


def snapshot_at(snapshots: list[dict[str, Any]], snap_us: list[int], target_us: int) -> dict[str, Any] | None:
    idx = bisect.bisect_left(snap_us, target_us)
    if idx >= len(snapshots):
        return None
    return snapshots[idx]


def depth_in_range(snapshot: dict[str, Any] | None, book_side: str, lo_tick: int, hi_tick: int) -> float | None:
    if snapshot is None:
        return None
    ref = int(snapshot["ref_tick"])
    total = 0.0
    prefix = "ask" if book_side == "ask" else "bid"
    for i in range(DEPTH_LEVELS):
        off = snapshot.get(f"{prefix}_offset_{i}")
        size = snapshot.get(f"{prefix}_size_{i}")
        if off is None or size is None:
            continue
        try:
            value = float(size)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(value) or value <= 0:
            continue
        tick = ref + int(off)
        if lo_tick <= tick <= hi_tick:
            total += value
    return total


def state_summary(
    snapshots: list[dict[str, Any]],
    snap_us: list[int],
    start_us: int,
    end_us: int,
    lo_tick: int,
    hi_tick: int,
) -> dict[str, Any]:
    idx = bisect.bisect_left(snap_us, start_us)
    totals = {"beyond_sec": 0.0, "inside_sec": 0.0, "old_sec": 0.0, "samples": 0}
    max_beyond = -10**9
    max_old = -10**9
    first_beyond: int | None = None
    first_old_after_beyond: int | None = None
    close_tick: int | None = None
    saw_beyond = False
    while idx < len(snapshots):
        row = snapshots[idx]
        row_us = int(row["timestamp_us"])
        if row_us >= end_us:
            break
        next_us = end_us
        if idx + 1 < len(snapshots):
            next_us = min(end_us, int(snapshots[idx + 1]["timestamp_us"]))
        dt = max(0, next_us - max(row_us, start_us)) / 1_000_000.0
        mid = midpoint_tick(row)
        rel = relation_tick(mid, lo_tick, hi_tick)
        totals[f"{rel}_sec"] += dt
        totals["samples"] += 1
        max_beyond = max(max_beyond, mid - hi_tick)
        max_old = max(max_old, lo_tick - mid)
        close_tick = mid
        if rel == "beyond":
            saw_beyond = True
            if first_beyond is None:
                first_beyond = row_us
        if saw_beyond and rel == "old" and first_old_after_beyond is None:
            first_old_after_beyond = row_us
        idx += 1

    total_sec = totals["beyond_sec"] + totals["inside_sec"] + totals["old_sec"]
    if total_sec > 0:
        totals["beyond_ratio"] = totals["beyond_sec"] / total_sec
        totals["inside_ratio"] = totals["inside_sec"] / total_sec
        totals["old_ratio"] = totals["old_sec"] / total_sec
    else:
        totals["beyond_ratio"] = 0.0
        totals["inside_ratio"] = 0.0
        totals["old_ratio"] = 0.0
    totals["max_beyond_ticks"] = max_beyond if max_beyond != -10**9 else 0
    totals["max_old_ticks"] = max_old if max_old != -10**9 else 0
    totals["first_beyond_us"] = first_beyond
    totals["first_old_after_beyond_us"] = first_old_after_beyond
    totals["close_tick"] = close_tick
    return totals


def tick_summary(
    tick_us: list[int],
    prices: list[float],
    sizes: list[float],
    signs: list[int],
    start_us: int,
    end_us: int,
    lo_tick: int,
    hi_tick: int,
) -> dict[str, float]:
    out = {
        "vol_beyond": 0.0,
        "vol_inside": 0.0,
        "vol_old": 0.0,
        "delta_beyond": 0.0,
        "delta_inside": 0.0,
        "delta_old": 0.0,
        "buy_beyond": 0.0,
        "sell_beyond": 0.0,
        "vol_total": 0.0,
        "trades": 0.0,
    }
    start = bisect.bisect_left(tick_us, start_us)
    end = bisect.bisect_left(tick_us, end_us)
    for i in range(start, end):
        price_tick = int(round(float(prices[i]) / TICK_SIZE))
        size = float(sizes[i])
        sign = int(signs[i] or 0)
        rel = relation_tick(price_tick, lo_tick, hi_tick)
        out[f"vol_{rel}"] += size
        out[f"delta_{rel}"] += size * sign
        if rel == "beyond" and sign > 0:
            out["buy_beyond"] += size
        elif rel == "beyond" and sign < 0:
            out["sell_beyond"] += size
        out["vol_total"] += size
        out["trades"] += 1
    return out


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


def classify(row: dict[str, Any]) -> str:
    failed = row["supply_failed"] == "true"
    high_count = int(row["higher_demand_count"])
    high_failed = int(row["higher_demand_failed_count"])
    top_down = int(row["top_down_demand_fail_count"])
    old_ratio = float(row["old_ratio_after_encounter"] or 0.0)
    beyond_ratio = float(row["beyond_ratio_after_encounter"] or 0.0)
    max_beyond = int(row["max_beyond_ticks"])
    repeated = int(row["same_zone_supply_test_hold_count"])
    older_live = int(row["older_demand_live_count"])

    if failed and high_failed >= 2 and top_down >= 2:
        return "thin_sweep_node_failed"
    if failed and repeated >= 2 and high_count > 0 and high_failed == 0 and beyond_ratio >= 0.35:
        return "repair_confirmed_continuation"
    if failed and high_count > 0 and high_failed == 0 and beyond_ratio >= 0.45 and old_ratio <= 0.20:
        return "supply_encounter_escape"
    if failed and high_count == 0 and max_beyond >= 8:
        return "thin_sweep_unconfirmed"
    if failed and (old_ratio >= 0.30 or max_beyond < 8):
        return "supply_encounter_no_escape"
    if older_live > 0 and high_failed > 0:
        return "core_alive_tactical_failed"
    if not failed and repeated >= 2:
        return "supply_still_holding"
    return "unclassified_extension_response"


def encounter_type(band: OwnershipBand) -> str:
    if band.source == "supply_lean":
        return "supply_lean"
    if band.source == "demand_consumed":
        return "demand_consumed_supply"
    return band.source


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
    ticks_df = load_capture_window(
        "ticks",
        symbol,
        replay_start,
        end_ny,
        tick_columns(),
        inclusive_end=True,
    )

    snapshots = list(snapshots_df.iter_rows(named=True))
    snap_us = [int(row["timestamp_us"]) for row in snapshots]
    tick_us = [int(v) for v in ticks_df["timestamp_us"].to_list()]
    prices = [float(v) for v in ticks_df["price"].to_list()]
    sizes = [float(v) for v in ticks_df["size"].to_list()]
    signs = [int(v or 0) for v in ticks_df["aggressor_sign"].to_list()]

    probe = default_probe()
    for row in snapshots:
        probe.on_sample(build_sample(row))

    start_us = us(start_ny)
    end_us = us(end_ny)
    transitions = [t for t in probe.transitions if start_ny <= t.ts.astimezone(NY) <= end_ny]
    bands_by_id = {band.id: band for band in probe.bands}

    rows: list[dict[str, Any]] = []
    seen: set[int] = set()
    for tr in transitions:
        if tr.side != "supply" or tr.action not in {"OWNED", "CONSUMED"}:
            continue
        if tr.band_id in seen:
            continue
        seen.add(tr.band_id)
        band = bands_by_id.get(tr.band_id)
        if band is None:
            continue

        encounter_us = int(tr.ts.timestamp() * 1_000_000)
        response_end_us = min(end_us, encounter_us + int(args.response_sec * 1_000_000))
        response_end_ts = datetime.fromtimestamp(response_end_us / 1_000_000, tz=timezone.utc)
        lo_tick = tr.min_tick
        hi_tick = tr.max_tick
        stats = state_summary(snapshots, snap_us, encounter_us, response_end_us, lo_tick, hi_tick)
        tape = tick_summary(tick_us, prices, sizes, signs, encounter_us, response_end_us, lo_tick, hi_tick)

        same_zone_supply = [
            item
            for item in transitions
            if item.ts > tr.ts
            and int(item.ts.timestamp() * 1_000_000) <= response_end_us
            and item.side == "supply"
            and overlap_or_near(lo_tick, hi_tick, item.min_tick, item.max_tick, args.same_zone_ticks)
        ]
        same_zone_test_hold = [item for item in same_zone_supply if item.action in {"TEST", "HOLD"}]
        same_zone_fail = [item for item in same_zone_supply if item.action == "FAIL"]

        older_demand = [
            item
            for item in probe.bands
            if item.side == "demand"
            and item.owned_ts < tr.ts
            and item.max_tick < hi_tick
            and (item.failed_ts is None or item.failed_ts > tr.ts)
        ]
        older_demand_survived = [
            item for item in older_demand if item.failed_ts is None or int(item.failed_ts.timestamp() * 1_000_000) > response_end_us
        ]

        higher_demand = [
            item
            for item in probe.bands
            if item.side == "demand"
            and item.owned_ts > tr.ts
            and int(item.owned_ts.timestamp() * 1_000_000) <= response_end_us
            and item.max_tick >= lo_tick - args.child_near_ticks
        ]
        higher_demand_failed = [
            item
            for item in higher_demand
            if item.failed_ts is not None and int(item.failed_ts.timestamp() * 1_000_000) <= response_end_us
        ]
        top_down_failed = [item for item in higher_demand_failed if item.max_tick >= lo_tick - args.child_near_ticks]

        snap_enc = snapshot_at(snapshots, snap_us, encounter_us)
        snap_5 = snapshot_at(snapshots, snap_us, encounter_us + 5_000_000)
        snap_20 = snapshot_at(snapshots, snap_us, encounter_us + 20_000_000)
        snap_60 = snapshot_at(snapshots, snap_us, encounter_us + 60_000_000)
        fail_us = int(band.failed_ts.timestamp() * 1_000_000) if band.failed_ts is not None else None
        snap_fail = snapshot_at(snapshots, snap_us, fail_us) if fail_us is not None else None
        above_lo = hi_tick + 1
        above_hi = hi_tick + args.above_depth_ticks

        row: dict[str, Any] = {
            "date": args.date,
            "symbol": symbol,
            "window": window,
            "encounter_et": ny_hms(tr.ts),
            "band_id": tr.band_id,
            "encounter_type": encounter_type(band),
            "supply_range": f"{tick_to_price(lo_tick)}-{tick_to_price(hi_tick)}",
            "supply_min": tick_to_price(lo_tick),
            "supply_max": tick_to_price(hi_tick),
            "supply_action": tr.action,
            "supply_owned_et": ny_hms(band.owned_ts),
            "supply_failed": "true" if band.failed_ts is not None and fail_us is not None and fail_us <= response_end_us else "false",
            "supply_failed_et": ny_hms(band.failed_ts) if band.failed_ts is not None and fail_us is not None and fail_us <= response_end_us else "",
            "fail_delay_sec": seconds_between(tr.ts, band.failed_ts) if band.failed_ts is not None and fail_us is not None and fail_us <= response_end_us else "",
            "response_end_et": ny_hms(response_end_ts),
            "max_beyond_ticks": stats["max_beyond_ticks"],
            "max_old_ticks": stats["max_old_ticks"],
            "beyond_ratio_after_encounter": fmt_float(float(stats["beyond_ratio"]), 4),
            "old_ratio_after_encounter": fmt_float(float(stats["old_ratio"]), 4),
            "inside_ratio_after_encounter": fmt_float(float(stats["inside_ratio"]), 4),
            "first_beyond_delay_sec": fmt_float((stats["first_beyond_us"] - encounter_us) / 1_000_000.0, 3)
            if stats["first_beyond_us"] is not None
            else "",
            "first_old_after_beyond_delay_sec": fmt_float(
                (stats["first_old_after_beyond_us"] - encounter_us) / 1_000_000.0, 3
            )
            if stats["first_old_after_beyond_us"] is not None
            else "",
            "close_mid": tick_to_price(stats["close_tick"]),
            "same_zone_supply_test_hold_count": len(same_zone_test_hold),
            "same_zone_supply_fail_count": len(same_zone_fail),
            "older_demand_live_count": len(older_demand),
            "older_demand_survived_count": len(older_demand_survived),
            "nearest_older_demand": f"{tick_to_price(max(item.min_tick for item in older_demand))}-{tick_to_price(max(item.max_tick for item in older_demand))}"
            if older_demand
            else "",
            "higher_demand_count": len(higher_demand),
            "higher_demand_failed_count": len(higher_demand_failed),
            "top_down_demand_fail_count": len(top_down_failed),
            "first_higher_demand_et": ny_hms(min((item.owned_ts for item in higher_demand), default=None)),
            "first_higher_demand_range": (
                f"{tick_to_price(min(higher_demand, key=lambda item: item.owned_ts).min_tick)}-"
                f"{tick_to_price(min(higher_demand, key=lambda item: item.owned_ts).max_tick)}"
                if higher_demand
                else ""
            ),
            "first_failed_higher_demand_et": ny_hms(min((item.failed_ts for item in higher_demand_failed if item.failed_ts), default=None)),
            "supply_depth_at_encounter": fmt_float(depth_in_range(snap_enc, "ask", lo_tick, hi_tick), 2),
            "supply_depth_at_fail": fmt_float(depth_in_range(snap_fail, "ask", lo_tick, hi_tick), 2),
            "supply_depth_5s": fmt_float(depth_in_range(snap_5, "ask", lo_tick, hi_tick), 2),
            "supply_depth_20s": fmt_float(depth_in_range(snap_20, "ask", lo_tick, hi_tick), 2),
            "supply_depth_60s": fmt_float(depth_in_range(snap_60, "ask", lo_tick, hi_tick), 2),
            "ask_depth_above_at_encounter": fmt_float(depth_in_range(snap_enc, "ask", above_lo, above_hi), 2),
            "ask_depth_above_20s": fmt_float(depth_in_range(snap_20, "ask", above_lo, above_hi), 2),
            "ask_depth_above_60s": fmt_float(depth_in_range(snap_60, "ask", above_lo, above_hi), 2),
            "vol_beyond": fmt_float(tape["vol_beyond"], 1),
            "delta_beyond": fmt_float(tape["delta_beyond"], 1),
            "buy_beyond": fmt_float(tape["buy_beyond"], 1),
            "sell_beyond": fmt_float(tape["sell_beyond"], 1),
            "vol_inside": fmt_float(tape["vol_inside"], 1),
            "delta_inside": fmt_float(tape["delta_inside"], 1),
            "vol_old": fmt_float(tape["vol_old"], 1),
            "delta_old": fmt_float(tape["delta_old"], 1),
            "transition_score": fmt_float(tr.score, 3),
            "transition_kinds": ",".join(sorted(tr.kinds)) if hasattr(tr, "kinds") else "",
        }
        row["label"] = classify(row)
        rows.append(row)
    return rows


def write_markdown(path: Path, rows: list[dict[str, Any]], args: argparse.Namespace) -> None:
    counts = Counter(row["label"] for row in rows)
    by_symbol = Counter((row["symbol"], row["label"]) for row in rows)
    lines = [
        f"# Extension Response Probe - {args.date}",
        "",
        "Research output only. Rows are supply encounters during long-side response research; labels are descriptive, not runtime rules.",
        "",
        f"- windows: `{args.windows}`",
        f"- symbols: `{args.symbols}`",
        f"- response horizon: `{args.response_sec}` seconds",
        f"- rows: `{len(rows)}`",
        "",
        "## Label Counts",
        "",
    ]
    for label, count in counts.most_common():
        lines.append(f"- `{label}`: {count}")
    lines.extend(["", "## Symbol / Label Counts", ""])
    for (symbol, label), count in sorted(by_symbol.items()):
        lines.append(f"- `{symbol}` `{label}`: {count}")
    lines.extend(
        [
            "",
            "## Encounter Rows",
            "",
            "| Symbol | Time | Supply | Type | Label | Max Beyond | Old Ratio | Higher Demand | Failed Higher | Older Live |",
            "|---|---:|---|---|---|---:|---:|---:|---:|---:|",
        ]
    )
    for row in rows:
        lines.append(
            "| {symbol} | {encounter_et} | {supply_range} | {encounter_type} | {label} | {max_beyond_ticks} | "
            "{old_ratio_after_encounter} | {higher_demand_count} | {higher_demand_failed_count} | {older_demand_live_count} |".format(
                **row
            )
        )
    lines.extend(
        [
            "",
            "## Read Notes",
            "",
            "- `supply_encounter_no_escape` means supply was crossed or failed, but the response did not leave enough auction evidence above it.",
            "- `thin_sweep_node_failed` means a higher demand/node attempt appeared after the sweep and then failed within the response window.",
            "- `repair_confirmed_continuation` means repeated supply interaction later resolved with supply failure and higher same-side ownership while older demand stayed alive.",
            "- The probe still uses time windows to summarize outcomes, but the labels are auction-sequence labels, not production timing thresholds.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", required=True)
    parser.add_argument("--symbols", default="NQU6,ESU6")
    parser.add_argument("--windows", default="09:30-12:00")
    parser.add_argument("--warmup-min", type=int, default=60)
    parser.add_argument("--response-sec", type=int, default=480)
    parser.add_argument("--same-zone-ticks", type=int, default=16)
    parser.add_argument("--child-near-ticks", type=int, default=4)
    parser.add_argument("--above-depth-ticks", type=int, default=40)
    parser.add_argument("--out-dir", default="research/out/extension_response")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    symbols = [item.strip() for item in args.symbols.split(",") if item.strip()]
    windows = [item.strip() for item in args.windows.split(",") if item.strip()]
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    rows: list[dict[str, Any]] = []
    for symbol in symbols:
        for window in windows:
            print(f"extension response replay {args.date}:{symbol}:{window}", flush=True)
            rows.extend(analyze_symbol_window(args, symbol, window))

    csv_path = out_dir / "extension_response_rows.csv"
    md_path = out_dir / "summary.md"
    fields = sorted({key for row in rows for key in row.keys()})
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    write_markdown(md_path, rows, args)
    print(f"wrote {csv_path}")
    print(f"wrote {md_path}")


if __name__ == "__main__":
    main()
