"""ETH/ON context map and RTH edge-audit research harness.

This is intentionally separate from liq_events.py. That script filters to RTH
before rolling baselines because LiquidityMeter and current-auction reads should
not be normalized against thinner overnight books. This script studies the
opposite question: what book memory exists before the open, and how did RTH
interact with it?
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import math
import os
import sys
from collections import defaultdict
from dataclasses import dataclass
from zoneinfo import ZoneInfo

import numpy as np
import polars as pl

from capture_loader import load_capture_window, snapshot_columns


try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


NY = ZoneInfo("America/New_York")
TICK_SIZE = 0.25
OUT_DIR = r"C:\Heatmap\research\out"

INNER_LEVELS = 10
BROAD_LEVELS = 30
ROLL_SEC = 30
EVENT_Z = 2.5
ZONE_GRID_TICKS = 16
ZONE_KERNEL_TICKS = 16
ZONE_MAX_DIST_TICKS = ZONE_KERNEL_TICKS * 3
ZONE_MIN_DOMINANT = 12.0
ZONE_MIN_RATIO = 1.25
EDGE_LOOKBACK_MIN = 30


EVENT_BIAS = {
    "BID_BUILD": +1,
    "BID_PULL": -1,
    "ASK_BUILD": -1,
    "ASK_PULL": +1,
    "BID_IN": +1,
    "BID_OUT": -1,
    "ASK_IN": -1,
    "ASK_OUT": +1,
}


@dataclass(frozen=True)
class Event:
    ts: dt.datetime
    price: float
    price_tick: int
    kind: str
    bias: int
    abs_z: float


@dataclass(frozen=True)
class Zone:
    scope: str
    side: str
    lo: float
    hi: float
    center: float
    score: float
    dominant: float
    opposing: float
    ratio: float
    net: float
    demand: float
    supply: float
    d_events: int
    s_events: int
    first: dt.datetime | None
    last: dt.datetime | None
    vol: float
    delta: float
    trades: int
    kinds: str


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--date", required=True, help="RTH date, e.g. 2026-05-20")
    p.add_argument("--symbol-dir", default="NQM6")
    p.add_argument("--eth-start", default="18:00")
    p.add_argument("--rth-start", default="09:30")
    p.add_argument("--rth-end", default="16:00")
    p.add_argument("--out-dir", default=OUT_DIR)
    p.add_argument(
        "--edge",
        action="append",
        default=[],
        help="Edge spec label:price:start-end, e.g. lower_060:29060:09:30-10:15",
    )
    return p.parse_args()


def ny_dt(day: dt.date, hhmm: str) -> dt.datetime:
    h, m, *rest = hhmm.split(":")
    s = int(rest[0]) if rest else 0
    return dt.datetime(day.year, day.month, day.day, int(h), int(m), s, tzinfo=NY)


def us(ts: dt.datetime) -> int:
    return int(ts.timestamp() * 1_000_000)


def ny_label(ts: dt.datetime | None, with_date: bool = False) -> str:
    if ts is None:
        return ""
    fmt = "%m-%d %H:%M" if with_date else "%H:%M:%S"
    return ts.astimezone(NY).strftime(fmt)


def load_window(kind: str, symbol_dir: str, start: dt.datetime, end: dt.datetime) -> pl.DataFrame:
    if kind == "snapshots":
        cols = snapshot_columns(BROAD_LEVELS)
    else:
        cols = ["timestamp_us", "price", "size", "aggressor_sign"]
    return load_capture_window(kind, symbol_dir, start, end, cols)


def add_ny_ts(df: pl.DataFrame) -> pl.DataFrame:
    return df.with_columns(
        pl.from_epoch("timestamp_us", time_unit="us")
        .dt.replace_time_zone("UTC")
        .dt.convert_time_zone("America/New_York")
        .alias("ts")
    )


def price_profile(ticks: pl.DataFrame, bin_points: float = 4.0) -> pl.DataFrame:
    bin_ticks = int(round(bin_points / TICK_SIZE))
    return (
        ticks.with_columns(
            ((pl.col("price") / TICK_SIZE).round().cast(pl.Int64)).alias("tick"),
            pl.when(pl.col("aggressor_sign") > 0)
            .then(pl.col("size"))
            .otherwise(0.0)
            .alias("buy"),
            pl.when(pl.col("aggressor_sign") < 0)
            .then(pl.col("size"))
            .otherwise(0.0)
            .alias("sell"),
        )
        .with_columns(((pl.col("tick") // bin_ticks) * bin_ticks).alias("bin_tick"))
        .group_by("bin_tick")
        .agg(
            pl.col("size").sum().alias("vol"),
            pl.col("buy").sum().alias("buy"),
            pl.col("sell").sum().alias("sell"),
            pl.len().alias("trades"),
        )
        .with_columns(
            (pl.col("bin_tick") * TICK_SIZE).alias("price"),
            (pl.col("buy") - pl.col("sell")).alias("delta"),
        )
        .sort("price")
    )


def top_profile_nodes(profile: pl.DataFrame, n: int = 14) -> list[dict]:
    return list(profile.sort("vol", descending=True).head(n).iter_rows(named=True))


def local_min_holes(profile: pl.DataFrame, top_n: int = 6) -> list[dict]:
    rows = list(profile.iter_rows(named=True))
    holes: list[dict] = []
    for i in range(1, len(rows) - 1):
        v = float(rows[i]["vol"])
        left = float(rows[i - 1]["vol"])
        right = float(rows[i + 1]["vol"])
        if v < left * 0.72 and v < right * 0.72:
            item = dict(rows[i])
            item["neighbor_ratio"] = v / max(1.0, (left + right) / 2)
            holes.append(item)
    return sorted(holes, key=lambda r: r["neighbor_ratio"])[:top_n]


def build_snapshot_metrics(snap: pl.DataFrame) -> pl.DataFrame:
    bid_inner = [f"bid_size_{i}" for i in range(INNER_LEVELS)]
    ask_inner = [f"ask_size_{i}" for i in range(INNER_LEVELS)]
    bid_broad = [f"bid_size_{i}" for i in range(BROAD_LEVELS)]
    ask_broad = [f"ask_size_{i}" for i in range(BROAD_LEVELS)]
    bid_off = [f"bid_offset_{i}" for i in range(BROAD_LEVELS)]
    ask_off = [f"ask_offset_{i}" for i in range(BROAD_LEVELS)]

    bid_dist_terms = [pl.col(o).abs() * pl.col(s) for o, s in zip(bid_off, bid_broad)]
    ask_dist_terms = [pl.col(o).abs() * pl.col(s) for o, s in zip(ask_off, ask_broad)]

    return (
        add_ny_ts(snap)
        .with_columns(
            pl.sum_horizontal(bid_inner).alias("bid_inner"),
            pl.sum_horizontal(ask_inner).alias("ask_inner"),
            pl.sum_horizontal(bid_broad).alias("bid_broad"),
            pl.sum_horizontal(ask_broad).alias("ask_broad"),
            pl.sum_horizontal(bid_dist_terms).alias("_b_wsum"),
            pl.sum_horizontal(ask_dist_terms).alias("_a_wsum"),
        )
        .with_columns(
            (pl.col("_b_wsum") / pl.col("bid_broad").clip(1)).alias("bid_centroid"),
            (pl.col("_a_wsum") / pl.col("ask_broad").clip(1)).alias("ask_centroid"),
        )
        .drop("_b_wsum", "_a_wsum")
        .sort("ts")
        .with_columns(
            pl.col("bid_inner").rolling_mean_by("ts", f"{ROLL_SEC}s").alias("bi_mean"),
            pl.col("bid_inner").rolling_std_by("ts", f"{ROLL_SEC}s").alias("bi_std"),
            pl.col("ask_inner").rolling_mean_by("ts", f"{ROLL_SEC}s").alias("ai_mean"),
            pl.col("ask_inner").rolling_std_by("ts", f"{ROLL_SEC}s").alias("ai_std"),
            pl.col("bid_centroid").rolling_mean_by("ts", f"{ROLL_SEC}s").alias("bc_mean"),
            pl.col("bid_centroid").rolling_std_by("ts", f"{ROLL_SEC}s").alias("bc_std"),
            pl.col("ask_centroid").rolling_mean_by("ts", f"{ROLL_SEC}s").alias("ac_mean"),
            pl.col("ask_centroid").rolling_std_by("ts", f"{ROLL_SEC}s").alias("ac_std"),
        )
        .with_columns(
            ((pl.col("bid_inner") - pl.col("bi_mean")) / pl.col("bi_std").clip(1.0)).alias("z_bi"),
            ((pl.col("ask_inner") - pl.col("ai_mean")) / pl.col("ai_std").clip(1.0)).alias("z_ai"),
            ((pl.col("bid_centroid") - pl.col("bc_mean")) / pl.col("bc_std").clip(0.01)).alias("z_bc"),
            ((pl.col("ask_centroid") - pl.col("ac_mean")) / pl.col("ac_std").clip(0.01)).alias("z_ac"),
        )
    )


def detect_events(snap: pl.DataFrame) -> list[Event]:
    specs = [
        ("z_bi", "BID_BUILD", "BID_PULL", +1),
        ("z_ai", "ASK_BUILD", "ASK_PULL", -1),
        ("z_bc", "BID_OUT", "BID_IN", -1),
        ("z_ac", "ASK_OUT", "ASK_IN", +1),
    ]
    events: list[Event] = []
    last_by_kind: dict[tuple[str, int], dt.datetime] = {}
    for row in snap.select("ts", "ref_tick", *(s[0] for s in specs)).iter_rows(named=True):
        for col, pos_kind, neg_kind, pos_bias in specs:
            z = row[col]
            if z is None or not math.isfinite(float(z)) or abs(float(z)) <= EVENT_Z:
                continue
            kind = pos_kind if z > 0 else neg_kind
            bias = pos_bias if z > 0 else -pos_bias
            price_tick = int(row["ref_tick"])
            key = (kind, price_tick)
            ts = row["ts"]
            prev = last_by_kind.get(key)
            if prev is not None and (ts - prev).total_seconds() < 5:
                continue
            last_by_kind[key] = ts
            events.append(
                Event(
                    ts=ts,
                    price=price_tick * TICK_SIZE,
                    price_tick=price_tick,
                    kind=kind,
                    bias=bias,
                    abs_z=abs(float(z)),
                )
            )
    return events


def tick_window(ticks: pl.DataFrame, lo: float, hi: float, start: dt.datetime | None = None, end: dt.datetime | None = None) -> tuple[float, float, int]:
    sub = ticks.filter((pl.col("price") >= lo) & (pl.col("price") <= hi))
    if start is not None:
        sub = sub.filter(pl.col("ts") >= start)
    if end is not None:
        sub = sub.filter(pl.col("ts") < end)
    if sub.height == 0:
        return 0.0, 0.0, 0
    row = (
        sub.select(
            pl.col("size").sum().alias("vol"),
            (
                pl.when(pl.col("aggressor_sign") > 0)
                .then(pl.col("size"))
                .when(pl.col("aggressor_sign") < 0)
                .then(-pl.col("size"))
                .otherwise(0.0)
                .sum()
            ).alias("delta"),
            pl.len().alias("trades"),
        )
        .row(0, named=True)
    )
    return float(row["vol"]), float(row["delta"]), int(row["trades"])


def compute_zones(scope: str, events: list[Event], ticks: pl.DataFrame, start: dt.datetime, end: dt.datetime) -> list[Zone]:
    if not events:
        return []
    min_tick = min(ev.price_tick for ev in events)
    max_tick = max(ev.price_tick for ev in events)
    centers = range(
        (min_tick // ZONE_GRID_TICKS) * ZONE_GRID_TICKS,
        ((max_tick // ZONE_GRID_TICKS) + 1) * ZONE_GRID_TICKS + 1,
        ZONE_GRID_TICKS,
    )
    candidates: list[Zone] = []
    for center_tick in centers:
        demand = 0.0
        supply = 0.0
        d_events = 0
        s_events = 0
        involved: list[Event] = []
        kinds: dict[str, int] = defaultdict(int)
        for ev in events:
            dist = abs(ev.price_tick - center_tick)
            if dist > ZONE_MAX_DIST_TICKS:
                continue
            x = dist / ZONE_KERNEL_TICKS
            weight = ev.abs_z * math.exp(-0.5 * x * x)
            involved.append(ev)
            kinds[ev.kind] += 1
            if ev.bias > 0:
                demand += weight
                d_events += 1
            else:
                supply += weight
                s_events += 1
        if not involved:
            continue
        dominant = max(demand, supply)
        opposing = min(demand, supply)
        ratio = dominant / max(1.0, opposing)
        if dominant < ZONE_MIN_DOMINANT or ratio < ZONE_MIN_RATIO:
            continue
        side = "DEMAND" if demand >= supply else "SUPPLY"
        center = center_tick * TICK_SIZE
        lo = center - (ZONE_GRID_TICKS / 2) * TICK_SIZE
        hi = center + (ZONE_GRID_TICKS / 2) * TICK_SIZE
        vol, delta, trades = tick_window(ticks, lo, hi, start, end)
        score = dominant * math.log1p(len(involved)) * ratio
        first = min(ev.ts for ev in involved)
        last = max(ev.ts for ev in involved)
        candidates.append(
            Zone(
                scope=scope,
                side=side,
                lo=lo,
                hi=hi,
                center=center,
                score=score,
                dominant=dominant,
                opposing=opposing,
                ratio=ratio,
                net=demand - supply,
                demand=demand,
                supply=supply,
                d_events=d_events,
                s_events=s_events,
                first=first,
                last=last,
                vol=vol,
                delta=delta,
                trades=trades,
                kinds=" ".join(f"{k}:{v}" for k, v in sorted(kinds.items())),
            )
        )
    return merge_zones(candidates)


def merge_zones(candidates: list[Zone]) -> list[Zone]:
    out: list[Zone] = []
    for z in sorted(candidates, key=lambda x: x.score, reverse=True):
        if any(z.side == prior.side and abs(z.center - prior.center) <= 8.0 for prior in out):
            continue
        out.append(z)
    return sorted(out, key=lambda x: (x.side, -x.score))


def events_in(events: list[Event], start: dt.datetime, end: dt.datetime) -> list[Event]:
    return [ev for ev in events if start <= ev.ts < end]


def profile_summary(ticks: pl.DataFrame) -> dict[str, float]:
    if ticks.height == 0:
        return {"open": math.nan, "high": math.nan, "low": math.nan, "close": math.nan, "vol": 0.0, "delta": 0.0, "trades": 0}
    row = ticks.select(
        pl.col("price").first().alias("open"),
        pl.col("price").max().alias("high"),
        pl.col("price").min().alias("low"),
        pl.col("price").last().alias("close"),
        pl.col("size").sum().alias("vol"),
        (
            pl.when(pl.col("aggressor_sign") > 0)
            .then(pl.col("size"))
            .when(pl.col("aggressor_sign") < 0)
            .then(-pl.col("size"))
            .otherwise(0.0)
            .sum()
        ).alias("delta"),
        pl.len().alias("trades"),
    ).row(0, named=True)
    return {k: float(v) if k != "trades" else int(v) for k, v in row.items()}


def rth_bars(ticks: pl.DataFrame, every: str = "5m") -> pl.DataFrame:
    return (
        ticks.group_by_dynamic("ts", every=every, closed="left")
        .agg(
            pl.col("price").first().alias("open"),
            pl.col("price").max().alias("high"),
            pl.col("price").min().alias("low"),
            pl.col("price").last().alias("close"),
            pl.col("size").sum().alias("vol"),
            (
                pl.when(pl.col("aggressor_sign") > 0)
                .then(pl.col("size"))
                .when(pl.col("aggressor_sign") < 0)
                .then(-pl.col("size"))
                .otherwise(0.0)
                .sum()
            ).alias("delta"),
        )
        .filter(pl.col("vol") > 0)
        .sort("ts")
    )


def edge_audit(
    label: str,
    price: float,
    start: dt.datetime,
    end: dt.datetime,
    ticks: pl.DataFrame,
    rth_events: list[Event],
    eth_events: list[Event],
) -> list[str]:
    lines: list[str] = []
    lo = price - 5.0
    hi = price + 5.0
    sub_ticks = ticks.filter((pl.col("ts") >= start) & (pl.col("ts") < end))
    row = profile_summary(sub_ticks)
    lines.append(f"{label} around {price:.2f} ({ny_label(start)}-{ny_label(end)})")
    lines.append(
        f"  tape: O={row['open']:.2f} H={row['high']:.2f} L={row['low']:.2f} "
        f"C={row['close']:.2f} vol={row['vol']:.0f} delta={row['delta']:+.0f}"
    )
    local = [ev for ev in rth_events if start <= ev.ts < end and lo <= ev.price <= hi]
    pre = [
        ev for ev in rth_events
        if start - dt.timedelta(minutes=EDGE_LOOKBACK_MIN) <= ev.ts < start
        and lo <= ev.price <= hi
    ]
    on_memory = [ev for ev in eth_events if lo <= ev.price <= hi]
    for title, bucket in (
        ("ON memory in band", on_memory),
        (f"RTH prior {EDGE_LOOKBACK_MIN}m", pre),
        ("window events", local),
    ):
        bull = sum(ev.abs_z for ev in bucket if ev.bias > 0)
        bear = sum(ev.abs_z for ev in bucket if ev.bias < 0)
        counts = defaultdict(int)
        for ev in bucket:
            counts[ev.kind] += 1
        lines.append(
            f"  {title}: n={len(bucket)} bull={bull:.1f} bear={bear:.1f} "
            f"net={bull - bear:+.1f} kinds="
            + (" ".join(f"{k}:{v}" for k, v in sorted(counts.items())) if counts else "-")
        )
    if local:
        lines.append("  events:")
        for ev in local[:24]:
            side = "D" if ev.bias > 0 else "S"
            lines.append(f"    {ny_label(ev.ts)} {side} {ev.kind:<9} {ev.price:8.2f} z={ev.abs_z:.2f}")
        if len(local) > 24:
            lines.append(f"    ... {len(local) - 24} more")
    return lines


def parse_edge_specs(specs: list[str], rth_day: dt.date) -> list[tuple[str, float, dt.datetime, dt.datetime]]:
    if specs:
        out = []
        for spec in specs:
            label_price, window = spec.split(":", 2)[0:2], spec.split(":", 2)[2]
            label, price_s = label_price
            start_s, end_s = window.split("-", 1)
            out.append((label, float(price_s), ny_dt(rth_day, start_s), ny_dt(rth_day, end_s)))
        return out
    return [
        ("lower_probe_060", 29060.0, ny_dt(rth_day, "09:30"), ny_dt(rth_day, "10:05")),
        ("lower_probe_030", 29030.0, ny_dt(rth_day, "09:45"), ny_dt(rth_day, "10:40")),
        ("washout_008", 29008.0, ny_dt(rth_day, "10:00"), ny_dt(rth_day, "11:15")),
        ("long_accept_123", 29123.0, ny_dt(rth_day, "10:15"), ny_dt(rth_day, "10:30")),
        ("long_accept_128", 29128.0, ny_dt(rth_day, "10:15"), ny_dt(rth_day, "10:30")),
    ]


def write_events_csv(path: str, events: list[Event]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["ny_time", "utc_time", "price", "price_tick", "side", "kind", "bias", "abs_z"])
        for ev in events:
            writer.writerow(
                [
                    ny_label(ev.ts, with_date=True),
                    ev.ts.astimezone(dt.timezone.utc).isoformat(),
                    f"{ev.price:.2f}",
                    ev.price_tick,
                    "DEMAND" if ev.bias > 0 else "SUPPLY",
                    ev.kind,
                    ev.bias,
                    f"{ev.abs_z:.3f}",
                ]
            )


def write_zones_csv(path: str, zones: list[Zone]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "scope",
                "side",
                "lo",
                "hi",
                "center",
                "score",
                "dominant",
                "opposing",
                "ratio",
                "net",
                "demand",
                "supply",
                "d_events",
                "s_events",
                "first",
                "last",
                "vol",
                "delta",
                "trades",
                "kinds",
            ]
        )
        for z in zones:
            writer.writerow(
                [
                    z.scope,
                    z.side,
                    f"{z.lo:.2f}",
                    f"{z.hi:.2f}",
                    f"{z.center:.2f}",
                    f"{z.score:.2f}",
                    f"{z.dominant:.2f}",
                    f"{z.opposing:.2f}",
                    f"{z.ratio:.2f}",
                    f"{z.net:.2f}",
                    f"{z.demand:.2f}",
                    f"{z.supply:.2f}",
                    z.d_events,
                    z.s_events,
                    ny_label(z.first, with_date=True),
                    ny_label(z.last, with_date=True),
                    f"{z.vol:.2f}",
                    f"{z.delta:.2f}",
                    z.trades,
                    z.kinds,
                ]
            )


def fmt_zone(z: Zone) -> str:
    return (
        f"{z.side:<6} {z.lo:8.2f}-{z.hi:<8.2f} {z.center:8.2f} "
        f"{z.score:7.1f} {z.dominant:5.1f}/{z.opposing:<5.1f} "
        f"{z.ratio:4.1f} {z.net:+6.1f} {z.d_events:2d}/{z.s_events:<2d} "
        f"{ny_label(z.last, True):<11} {z.vol:7.0f} {z.delta:+7.0f}  {z.kinds}"
    )


def main() -> None:
    args = parse_args()
    os.makedirs(args.out_dir, exist_ok=True)
    rth_day = dt.date.fromisoformat(args.date)
    eth_start = ny_dt(rth_day - dt.timedelta(days=1), args.eth_start)
    rth_start = ny_dt(rth_day, args.rth_start)
    rth_end = ny_dt(rth_day, args.rth_end)

    snap = load_window("snapshots", args.symbol_dir, eth_start, rth_end)
    ticks = add_ny_ts(load_window("ticks", args.symbol_dir, eth_start, rth_end))

    eth_ticks = ticks.filter((pl.col("ts") >= eth_start) & (pl.col("ts") < rth_start))
    rth_ticks = ticks.filter((pl.col("ts") >= rth_start) & (pl.col("ts") < rth_end))
    snap_metrics = build_snapshot_metrics(snap)
    all_events = detect_events(snap_metrics)
    eth_events = events_in(all_events, eth_start, rth_start)
    preopen_start = ny_dt(rth_day, "08:00")
    preopen_events = events_in(all_events, preopen_start, rth_start)
    rth_events = events_in(all_events, rth_start, rth_end)
    ib_end = ny_dt(rth_day, "10:30")
    ib_events = events_in(all_events, rth_start, ib_end)

    eth_summary = profile_summary(eth_ticks)
    rth_summary = profile_summary(rth_ticks)
    ib_summary = profile_summary(rth_ticks.filter(pl.col("ts") < ib_end))

    eth_profile = price_profile(eth_ticks)
    rth_profile = price_profile(rth_ticks)
    eth_nodes = top_profile_nodes(eth_profile)
    eth_holes = local_min_holes(eth_profile)

    eth_zones = compute_zones("ETH_FULL", eth_events, eth_ticks, eth_start, rth_start)
    preopen_zones = compute_zones("PREOPEN_0800", preopen_events, eth_ticks, preopen_start, rth_start)
    ib_zones = compute_zones("RTH_IB", ib_events, rth_ticks, rth_start, ib_end)
    all_zones = eth_zones + preopen_zones + ib_zones

    base = os.path.join(args.out_dir, f"eth_on_context_{args.date}")
    events_csv = base + ".events.csv"
    zones_csv = base + ".zones.csv"
    txt = base + ".txt"
    write_events_csv(events_csv, all_events)
    write_zones_csv(zones_csv, all_zones)

    lines: list[str] = []
    lines.append(f"ETH/ON context for {args.date} {args.symbol_dir}")
    lines.append(f"Window NY: {ny_label(eth_start, True)} to {ny_label(rth_end, True)}")
    lines.append(f"Snapshots loaded: {snap.height:,}; ticks loaded: {ticks.height:,}; events: {len(all_events):,}")
    lines.append("")
    lines.append(
        f"ETH tape: O={eth_summary['open']:.2f} H={eth_summary['high']:.2f} L={eth_summary['low']:.2f} "
        f"C={eth_summary['close']:.2f} vol={eth_summary['vol']:.0f} delta={eth_summary['delta']:+.0f} trades={eth_summary['trades']:,}"
    )
    lines.append(
        f"RTH tape: O={rth_summary['open']:.2f} H={rth_summary['high']:.2f} L={rth_summary['low']:.2f} "
        f"C={rth_summary['close']:.2f} vol={rth_summary['vol']:.0f} delta={rth_summary['delta']:+.0f} trades={rth_summary['trades']:,}"
    )
    lines.append(
        f"IB tape : O={ib_summary['open']:.2f} H={ib_summary['high']:.2f} L={ib_summary['low']:.2f} "
        f"C={ib_summary['close']:.2f} vol={ib_summary['vol']:.0f} delta={ib_summary['delta']:+.0f} trades={ib_summary['trades']:,}"
    )
    lines.append("")
    lines.append("Top ETH 4-point volume nodes")
    lines.append("price       vol    delta  trades")
    for row in eth_nodes:
        lines.append(f"{row['price']:8.2f} {row['vol']:8.0f} {row['delta']:+8.0f} {row['trades']:7d}")
    lines.append("")
    lines.append("ETH local low-volume holes between neighboring 4-point bins")
    lines.append("price       vol    delta  neighbor_ratio")
    for row in eth_holes:
        lines.append(f"{row['price']:8.2f} {row['vol']:8.0f} {row['delta']:+8.0f} {row['neighbor_ratio']:6.2f}")
    lines.append("")
    lines.append("ETH_FULL ranked book-memory zones")
    lines.append("side   zone                  center   score  dom/opp ratio    net evD/S last         vol   delta  kinds")
    for side in ("DEMAND", "SUPPLY"):
        for z in [x for x in eth_zones if x.side == side][:12]:
            lines.append(fmt_zone(z))
    lines.append("")
    lines.append("PREOPEN_0800 ranked book-memory zones")
    lines.append("side   zone                  center   score  dom/opp ratio    net evD/S last         vol   delta  kinds")
    for side in ("DEMAND", "SUPPLY"):
        for z in [x for x in preopen_zones if x.side == side][:12]:
            lines.append(fmt_zone(z))
    lines.append("")
    lines.append("RTH_IB ranked book zones")
    lines.append("side   zone                  center   score  dom/opp ratio    net evD/S last         vol   delta  kinds")
    for side in ("DEMAND", "SUPPLY"):
        for z in [x for x in ib_zones if x.side == side][:12]:
            lines.append(fmt_zone(z))
    lines.append("")
    lines.append("RTH 5-minute bars through noon")
    lines.append("time          O        H        L        C       vol    delta")
    for row in rth_bars(rth_ticks.filter(pl.col("ts") < ny_dt(rth_day, "12:00"))).iter_rows(named=True):
        lines.append(
            f"{ny_label(row['ts']):<8} {row['open']:8.2f} {row['high']:8.2f} {row['low']:8.2f} "
            f"{row['close']:8.2f} {row['vol']:8.0f} {row['delta']:+8.0f}"
        )
    lines.append("")
    lines.append("Named edge audits")
    for label, price, start, end in parse_edge_specs(args.edge, rth_day):
        lines.extend(edge_audit(label, price, start, end, rth_ticks, rth_events, eth_events))
        lines.append("")
    lines.append(f"events_csv={events_csv}")
    lines.append(f"zones_csv={zones_csv}")

    text = "\n".join(lines)
    with open(txt, "w", encoding="utf-8") as f:
        f.write(text + "\n")
    print(text)
    print(f"\nwritten: {txt}")


if __name__ == "__main__":
    main()
