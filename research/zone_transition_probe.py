"""Probe whether a prior zone was accepted through or rejected.

Research-only helper. It compares:
  - live-style 5s trade impulses (`buyers lift` / `sellers hit`)
  - 30s / 60s / 120s volume-away after crossing a zone
  - reclaim/failure back through the old zone

This is deliberately not a signal script. It is a microscope for testing the
"old zone as context, new evidence after the probe" hypothesis.
"""

from __future__ import annotations

import argparse
import datetime as dt
import math
import os
import sys
from dataclasses import dataclass
from zoneinfo import ZoneInfo

import polars as pl

from capture_loader import add_ny_ts, load_capture_window, tick_columns


try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


NY = ZoneInfo("America/New_York")
TICK_SIZE = 0.25
TRADE_BAR_SEC = 5
IMPULSE_LOOKBACK_SEC = 120
IMPULSE_VOL_Z = 1.5
IMPULSE_DELTA_RATIO = 0.25


@dataclass(frozen=True)
class Case:
    label: str
    date: str
    symbol_dir: str
    start: str
    end: str
    zone: float
    direction: str


PRESET_CASES = [
    Case(
        label="false_poke_090",
        date="2026-05-12",
        symbol_dir="NQM6",
        start="10:38:00",
        end="10:45:30",
        zone=29090.0,
        direction="up",
    ),
    Case(
        label="supply_bought_through_886",
        date="2026-05-12",
        symbol_dir="NQM6",
        start="13:48:00",
        end="14:00:00",
        zone=28890.0,
        direction="up",
    ),
]


def parse_ny(day: str, value: str) -> dt.datetime:
    h, m, *rest = value.split(":")
    sec = int(rest[0]) if rest else 0
    y, mo, d = map(int, day.split("-"))
    return dt.datetime(y, mo, d, int(h), int(m), sec, tzinfo=NY)


def ny_str(ts: dt.datetime) -> str:
    return ts.astimezone(NY).strftime("%H:%M:%S")


def load_ticks(case: Case, context_sec: int) -> pl.DataFrame:
    start = parse_ny(case.date, case.start) - dt.timedelta(seconds=context_sec)
    end = parse_ny(case.date, case.end)

    return (
        add_ny_ts(load_capture_window("ticks", case.symbol_dir, start, end, tick_columns(), inclusive_end=True))
        .sort("ts")
    )


def session_bars(ticks: pl.DataFrame) -> pl.DataFrame:
    return (
        ticks.group_by_dynamic("ts", every=f"{TRADE_BAR_SEC}s", closed="right")
        .agg(
            pl.col("price").first().alias("open"),
            pl.col("price").max().alias("high"),
            pl.col("price").min().alias("low"),
            pl.col("price").last().alias("close"),
            pl.col("size").sum().alias("vol"),
            pl.when(pl.col("aggressor_sign") > 0)
            .then(pl.col("size"))
            .otherwise(0)
            .sum()
            .alias("buy"),
            pl.when(pl.col("aggressor_sign") < 0)
            .then(pl.col("size"))
            .otherwise(0)
            .sum()
            .alias("sell"),
        )
        .filter(pl.col("vol") > 0)
        .with_columns(
            (pl.col("buy") - pl.col("sell")).alias("delta"),
            pl.col("ts").dt.strftime("%H:%M:%S").alias("ny"),
        )
        .select("ts", "ny", "open", "high", "low", "close", "vol", "buy", "sell", "delta")
        .sort("ts")
    )


def find_cross(
    ticks: pl.DataFrame,
    case: Case,
    cross_ticks: int,
) -> dt.datetime | None:
    start = parse_ny(case.date, case.start)
    threshold = case.zone + cross_ticks * TICK_SIZE if case.direction == "up" else case.zone - cross_ticks * TICK_SIZE
    if case.direction == "up":
        crossed = ticks.filter((pl.col("ts") >= start) & (pl.col("price") >= threshold))
    else:
        crossed = ticks.filter((pl.col("ts") >= start) & (pl.col("price") <= threshold))
    if crossed.height == 0:
        return None
    return crossed["ts"][0]


def summarize_ticks(
    ticks: pl.DataFrame,
    start: dt.datetime,
    end: dt.datetime,
) -> dict[str, float | dt.datetime | None]:
    sub = ticks.filter((pl.col("ts") >= start) & (pl.col("ts") <= end))
    if sub.height == 0:
        return {"n": 0}
    row = (
        sub.select(
            pl.col("price").first().alias("open"),
            pl.col("price").max().alias("high"),
            pl.col("price").min().alias("low"),
            pl.col("price").last().alias("close"),
            pl.col("size").sum().alias("vol"),
            pl.when(pl.col("aggressor_sign") > 0)
            .then(pl.col("size"))
            .otherwise(0)
            .sum()
            .alias("buy"),
            pl.when(pl.col("aggressor_sign") < 0)
            .then(pl.col("size"))
            .otherwise(0)
            .sum()
            .alias("sell"),
        )
        .with_columns((pl.col("buy") - pl.col("sell")).alias("delta"))
        .row(0, named=True)
    )
    row["n"] = sub.height
    return row


def impulse_rows(bars: pl.DataFrame, display_start: dt.datetime, display_end: dt.datetime) -> list[dict]:
    rows = list(bars.iter_rows(named=True))
    out: list[dict] = []
    for i, row in enumerate(rows):
        ts = row["ts"]
        prior = [
            r for r in rows[:i]
            if r["ts"] >= ts - dt.timedelta(seconds=IMPULSE_LOOKBACK_SEC)
        ]
        if len(prior) < 8 or row["vol"] < 50:
            continue
        vols = [float(r["vol"]) for r in prior]
        mean = sum(vols) / len(vols)
        var = sum(v * v for v in vols) / len(vols) - mean * mean
        std = math.sqrt(var) if var > 0 else 0.0
        vol_z = (float(row["vol"]) - mean) / max(1.0, std)
        delta_ratio = abs(float(row["delta"])) / max(1.0, float(row["vol"]))
        if vol_z < IMPULSE_VOL_Z or delta_ratio < IMPULSE_DELTA_RATIO:
            continue
        if ts < display_start or ts > display_end:
            continue
        item = dict(row)
        item["vol_z"] = vol_z
        item["delta_ratio"] = delta_ratio
        item["label"] = "buyers lift" if row["delta"] > 0 else "sellers hit"
        out.append(item)
    return out


def fmt_bar(row: dict) -> str:
    return (
        f"{row['ny']:<9} {row.get('label', ''):<12} "
        f"{row['open']:>8.2f} {row['high']:>8.2f} {row['low']:>8.2f} {row['close']:>8.2f} "
        f"{row['vol']:>6.0f} {row['delta']:>+7.0f}"
    )


def analyze_case(
    case: Case,
    cross_ticks: int,
    reclaim_ticks: int,
    windows: list[int],
    hold_sec: int,
) -> str:
    context_sec = max(IMPULSE_LOOKBACK_SEC + 30, 180)
    ticks = load_ticks(case, context_sec)
    bars = session_bars(ticks)
    display_start = parse_ny(case.date, case.start)
    display_end = parse_ny(case.date, case.end)
    cross_ts = find_cross(ticks, case, cross_ticks)

    lines: list[str] = []
    lines.append(f"=== {case.label} ===")
    lines.append(
        f"{case.date} {case.start}-{case.end}  zone={case.zone:.2f} "
        f"direction={case.direction}  cross_ticks={cross_ticks}"
    )
    if cross_ts is None:
        lines.append("No cross found.")
        return "\n".join(lines)

    threshold = case.zone + cross_ticks * TICK_SIZE if case.direction == "up" else case.zone - cross_ticks * TICK_SIZE
    reclaim = case.zone - reclaim_ticks * TICK_SIZE if case.direction == "up" else case.zone + reclaim_ticks * TICK_SIZE
    lines.append(f"cross: {ny_str(cross_ts)} at threshold {threshold:.2f}; reclaim line {reclaim:.2f}")

    hold_end = min(cross_ts + dt.timedelta(seconds=hold_sec), display_end)
    if case.direction == "up":
        reclaim_hits = ticks.filter(
            (pl.col("ts") > cross_ts)
            & (pl.col("ts") <= hold_end)
            & (pl.col("price") <= reclaim)
        )
    else:
        reclaim_hits = ticks.filter(
            (pl.col("ts") > cross_ts)
            & (pl.col("ts") <= hold_end)
            & (pl.col("price") >= reclaim)
        )
    if reclaim_hits.height:
        lines.append(f"reclaim: YES at {ny_str(reclaim_hits['ts'][0])}")
    else:
        lines.append(f"reclaim: no reclaim through {ny_str(hold_end)}")

    lines.append("")
    lines.append("volume-away windows from cross")
    lines.append(f"{'win':>5} {'O':>8} {'H':>8} {'L':>8} {'C':>8} {'vol':>7} {'delta':>8} {'d/vol':>7} {'rng/100v':>9}")
    for sec in windows:
        end = min(cross_ts + dt.timedelta(seconds=sec), display_end)
        row = summarize_ticks(ticks, cross_ts, end)
        if row.get("n", 0) == 0:
            continue
        vol = float(row["vol"])
        delta = float(row["delta"])
        rng = float(row["high"]) - float(row["low"])
        lines.append(
            f"{sec:>5}s {row['open']:>8.2f} {row['high']:>8.2f} {row['low']:>8.2f} "
            f"{row['close']:>8.2f} {vol:>7.0f} {delta:>+8.0f} "
            f"{delta / max(1.0, vol):>7.2f} {rng / max(1.0, vol / 100.0):>9.2f}"
        )

    lines.append("")
    lines.append("live-style 5s impulses")
    impulses = impulse_rows(bars, display_start, display_end)
    if impulses:
        lines.append(f"{'time':<9} {'label':<12} {'O':>8} {'H':>8} {'L':>8} {'C':>8} {'vol':>6} {'delta':>7} {'volZ':>6} {'d/vol':>6}")
        for row in impulses:
            lines.append(
                fmt_bar(row)
                + f" {row['vol_z']:>6.2f} {row['delta_ratio']:>6.2f}"
            )
    else:
        lines.append("(none)")

    lines.append("")
    lines.append("notable 5s bars: vol >= 150 or abs(delta)/vol >= 0.25")
    lines.append(f"{'time':<9} {'O':>8} {'H':>8} {'L':>8} {'C':>8} {'vol':>6} {'delta':>7} {'d/vol':>6}")
    show = bars.filter((pl.col("ts") >= display_start) & (pl.col("ts") <= display_end))
    for row in show.iter_rows(named=True):
        ratio = abs(float(row["delta"])) / max(1.0, float(row["vol"]))
        if float(row["vol"]) >= 150 or ratio >= 0.25:
            lines.append(fmt_bar(row) + f" {ratio:>6.2f}")

    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--date", default="2026-05-12")
    p.add_argument("--symbol-dir", default="NQM6")
    p.add_argument("--start")
    p.add_argument("--end")
    p.add_argument("--zone", type=float)
    p.add_argument("--direction", choices=["up", "down"])
    p.add_argument("--label", default="custom")
    p.add_argument("--preset", choices=["may12", "custom"], default="may12")
    p.add_argument("--cross-ticks", type=int, default=8)
    p.add_argument("--reclaim-ticks", type=int, default=4)
    p.add_argument("--hold-sec", type=int, default=180)
    p.add_argument("--windows", default="5,30,60,120")
    p.add_argument("--out-dir", default=r"C:\Heatmap\research\out")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    windows = [int(x) for x in args.windows.split(",") if x.strip()]
    if args.preset == "custom":
        missing = [
            name for name in ("start", "end", "zone", "direction")
            if getattr(args, name) is None
        ]
        if missing:
            raise SystemExit(f"missing required custom args: {', '.join(missing)}")
        cases = [
            Case(
                label=args.label,
                date=args.date,
                symbol_dir=args.symbol_dir,
                start=args.start,
                end=args.end,
                zone=args.zone,
                direction=args.direction,
            )
        ]
    else:
        cases = PRESET_CASES

    os.makedirs(args.out_dir, exist_ok=True)
    parts = [
        analyze_case(c, args.cross_ticks, args.reclaim_ticks, windows, args.hold_sec)
        for c in cases
    ]
    text = "\n\n".join(parts)
    print(text)

    label = args.label if args.preset == "custom" else "may12"
    out = os.path.join(args.out_dir, f"zone_transition_probe_{args.date}_{label}.txt")
    with open(out, "w", encoding="utf-8") as f:
        f.write(text + "\n")
    print(f"\nwritten: {out}")


if __name__ == "__main__":
    main()
