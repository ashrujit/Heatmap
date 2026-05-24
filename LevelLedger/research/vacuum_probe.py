"""Research probe for fast-auction / vacuum conditions.

This is not indicator logic. It compares candidate flush windows by binning
trade tape and live-style L2 events into short slices.
"""

from __future__ import annotations

import argparse
import math
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import polars as pl

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "research"))
from capture_loader import load_capture_window, snapshot_columns, tick_columns


TICK_SIZE = 0.25
INNER_LEVELS = 10
BROAD_LEVELS = 30
LOOKBACK_SEC = 30
EVENT_Z = 2.5
NY = ZoneInfo("America/New_York")


@dataclass(frozen=True)
class L2Event:
    ts: datetime
    price: float
    kind: str
    bias: int
    abs_z: float


def parse_ny(day: str, value: str) -> datetime:
    fmt = "%Y-%m-%d %H:%M:%S" if value.count(":") == 2 else "%Y-%m-%d %H:%M"
    return datetime.strptime(f"{day} {value}", fmt).replace(tzinfo=NY).astimezone(timezone.utc)


def ny_hms(ts: datetime) -> str:
    return ts.astimezone(NY).strftime("%H:%M:%S")


def as_utc(value) -> datetime:
    ts = value.to_pydatetime() if hasattr(value, "to_pydatetime") else value
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc)


def load_captures(day: str, symbol_dir: str, start: datetime, end: datetime) -> tuple[pl.DataFrame, pl.DataFrame]:
    start_us = int(start.timestamp() * 1_000_000)
    end_us = int(end.timestamp() * 1_000_000)

    snap = (
        load_capture_window("snapshots", symbol_dir, start, end, snapshot_columns(BROAD_LEVELS), inclusive_end=True)
        .filter((pl.col("timestamp_us") >= start_us) & (pl.col("timestamp_us") <= end_us))
        .sort("timestamp_us")
    )
    ticks = (
        load_capture_window("ticks", symbol_dir, start, end, tick_columns(), inclusive_end=True)
        .filter((pl.col("timestamp_us") >= start_us) & (pl.col("timestamp_us") <= end_us))
        .sort("timestamp_us")
    )
    return snap, ticks


def add_snapshot_metrics(snap: pl.DataFrame) -> pl.DataFrame:
    bid_inner = [f"bid_size_{i}" for i in range(INNER_LEVELS)]
    ask_inner = [f"ask_size_{i}" for i in range(INNER_LEVELS)]
    bid_broad = [f"bid_size_{i}" for i in range(BROAD_LEVELS)]
    ask_broad = [f"ask_size_{i}" for i in range(BROAD_LEVELS)]
    bid_off = [f"bid_offset_{i}" for i in range(BROAD_LEVELS)]
    ask_off = [f"ask_offset_{i}" for i in range(BROAD_LEVELS)]
    bid_dist_terms = [pl.col(o).abs() * pl.col(s) for o, s in zip(bid_off, bid_broad)]
    ask_dist_terms = [pl.col(o).abs() * pl.col(s) for o, s in zip(ask_off, ask_broad)]

    return (
        snap.with_columns(
            pl.from_epoch("timestamp_us", time_unit="us").dt.replace_time_zone("UTC").alias("ts"),
            (pl.col("ref_tick") * TICK_SIZE).alias("mid"),
            pl.sum_horizontal(bid_inner).alias("bid_inner"),
            pl.sum_horizontal(ask_inner).alias("ask_inner"),
            pl.sum_horizontal(bid_broad).alias("bid_broad"),
            pl.sum_horizontal(ask_broad).alias("ask_broad"),
            pl.sum_horizontal(bid_dist_terms).alias("_bw"),
            pl.sum_horizontal(ask_dist_terms).alias("_aw"),
        )
        .with_columns(
            (pl.col("_bw") / pl.col("bid_broad").clip(1)).alias("bid_centroid"),
            (pl.col("_aw") / pl.col("ask_broad").clip(1)).alias("ask_centroid"),
            (pl.col("bid_inner") + pl.col("ask_inner")).alias("inner_total"),
        )
        .drop("_bw", "_aw")
    )


def mean_std(values: list[float]) -> tuple[float, float]:
    if len(values) < 2:
        return 0.0, 0.0
    mean = sum(values) / len(values)
    var = sum(v * v for v in values) / len(values) - mean * mean
    return mean, math.sqrt(var) if var > 0 else 0.0


def live_style_events(snap: pl.DataFrame) -> list[L2Event]:
    rows = snap.iter_rows(named=True)
    window = []
    events: list[L2Event] = []
    prev_inner = None
    inner_deltas: list[tuple[datetime, float]] = []
    vod_values: list[tuple[datetime, float]] = []

    for row in rows:
        ts = as_utc(row["ts"])
        sample = {
            "ts": ts,
            "mid": float(row["mid"]),
            "bid_inner": float(row["bid_inner"]),
            "ask_inner": float(row["ask_inner"]),
            "bid_centroid": float(row["bid_centroid"]),
            "ask_centroid": float(row["ask_centroid"]),
            "inner_total": float(row["inner_total"]),
        }
        window.append(sample)
        cutoff = ts - timedelta(seconds=LOOKBACK_SEC)
        window = [s for s in window if s["ts"] >= cutoff]
        if len(window) >= 5:
            def z_of(name: str, floor: float) -> float:
                vals = [s[name] for s in window]
                mean, std = mean_std(vals)
                return (sample[name] - mean) / max(floor, std)

            zbi = z_of("bid_inner", 1.0)
            zai = z_of("ask_inner", 1.0)
            zbc = z_of("bid_centroid", 0.01)
            zac = z_of("ask_centroid", 0.01)

            fire(events, ts, sample["mid"], zbi, +1, "BID_BUILD", "BID_PULL")
            fire(events, ts, sample["mid"], zai, -1, "ASK_BUILD", "ASK_PULL")
            fire(events, ts, sample["mid"], zbc, -1, "BID_OUT", "BID_IN")
            fire(events, ts, sample["mid"], zac, +1, "ASK_OUT", "ASK_IN")

        if prev_inner is not None:
            inner_deltas.append((ts, sample["inner_total"] - prev_inner))
            inner_deltas = [(t, v) for t, v in inner_deltas if t >= ts - timedelta(seconds=LOOKBACK_SEC * 2)]
            recent = [v for t, v in inner_deltas if t >= ts - timedelta(seconds=LOOKBACK_SEC)]
            if len(recent) >= 4:
                _, vod = mean_std(recent)
                vod_values.append((ts, vod))
                vod_values = [(t, v) for t, v in vod_values if t >= ts - timedelta(seconds=LOOKBACK_SEC * 8)]
                baseline = [v for t, v in vod_values if t >= ts - timedelta(seconds=LOOKBACK_SEC * 4)]
                if len(baseline) >= 8:
                    m, s = mean_std(baseline)
                    z = (vod - m) / max(0.1, s)
                    if abs(z) >= max(4.0, EVENT_Z + 1.0):
                        events.append(L2Event(ts, sample["mid"], "VOD", 0, abs(z)))
        prev_inner = sample["inner_total"]

    return events


def fire(events: list[L2Event], ts: datetime, price: float, z: float, bias_pos: int, pos: str, neg: str) -> None:
    if abs(z) <= EVENT_Z:
        return
    events.append(L2Event(ts, price, pos if z > 0 else neg, bias_pos if z > 0 else -bias_pos, abs(z)))


def tape_bins(ticks: pl.DataFrame, bin_sec: int) -> pl.DataFrame:
    return (
        ticks.with_columns(
            pl.from_epoch("timestamp_us", time_unit="us").dt.replace_time_zone("UTC").alias("ts"),
            (pl.col("size") * pl.col("aggressor_sign")).alias("signed_size"),
        )
        .group_by_dynamic("ts", every=f"{bin_sec}s", closed="left")
        .agg(
            pl.col("price").first().alias("open"),
            pl.col("price").max().alias("high"),
            pl.col("price").min().alias("low"),
            pl.col("price").last().alias("close"),
            pl.col("size").sum().alias("vol"),
            pl.col("signed_size").sum().alias("delta"),
            pl.len().alias("prints"),
        )
        .filter(pl.col("close").is_not_null())
        .with_columns(
            (pl.col("high") - pl.col("low")).alias("range"),
            (pl.col("close") - pl.col("open")).alias("net"),
            (pl.col("high") - pl.col("low")).truediv(pl.col("vol").clip(1)).alias("range_per_vol"),
            (pl.col("delta").abs() / pl.col("vol").clip(1)).alias("abs_delta_ratio"),
        )
        .sort("ts")
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default="2026-05-11")
    parser.add_argument("--symbol-dir", default="NQM6")
    parser.add_argument("--window", required=True)
    parser.add_argument("--context-min", type=int, default=5)
    parser.add_argument("--bin-sec", type=int, default=30)
    args = parser.parse_args()

    start_s, end_s = args.window.split("-", 1)
    display_start = parse_ny(args.date, start_s)
    display_end = parse_ny(args.date, end_s)
    load_start = display_start - timedelta(minutes=args.context_min)
    snap, ticks = load_captures(args.date, args.symbol_dir, load_start, display_end)
    snap = add_snapshot_metrics(snap)
    events = [ev for ev in live_style_events(snap) if display_start <= ev.ts <= display_end]
    bins = tape_bins(ticks, args.bin_sec).filter((pl.col("ts") >= display_start) & (pl.col("ts") <= display_end))

    print(f"\n{args.date} {args.window}  bin={args.bin_sec}s")
    print("time      net    range   vol   delta  |d|/v  rng/vol  L2 summary")
    for row in bins.iter_rows(named=True):
        ts = as_utc(row["ts"])
        bucket_end = ts + timedelta(seconds=args.bin_sec)
        bucket_events = [ev for ev in events if ts <= ev.ts < bucket_end]
        summary = summarize_events(bucket_events)
        print(
            f"{ny_hms(ts)} {row['net']:>7.2f} {row['range']:>7.2f} "
            f"{row['vol']:>6.0f} {row['delta']:>7.0f} "
            f"{row['abs_delta_ratio']:>5.2f} {row['range_per_vol']:>8.4f}  {summary}"
        )

    print("\nEvents:")
    for ev in events:
        bias = "D" if ev.bias > 0 else "S" if ev.bias < 0 else "."
        print(f"{ny_hms(ev.ts)} {bias} {ev.kind:<9} {ev.price:8.2f} z={ev.abs_z:4.2f}")


def summarize_events(events: list[L2Event]) -> str:
    if not events:
        return ""
    parts = []
    for kind in ["BID_PULL", "BID_OUT", "ASK_BUILD", "ASK_IN", "ASK_OUT", "ASK_PULL", "BID_BUILD", "BID_IN", "VOD"]:
        xs = [ev for ev in events if ev.kind == kind]
        if xs:
            parts.append(f"{kind}:{len(xs)}")
    return " ".join(parts)


if __name__ == "__main__":
    main()
