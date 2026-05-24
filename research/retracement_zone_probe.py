"""Rank retracement interest zones from tick-only traded business.

This is the Q5 companion to tape_auction_probe: after a move is judged worth
respecting, it asks what shelves the move left behind. It deliberately outputs
zones, not single prices.
"""

from __future__ import annotations

import argparse
import datetime as dt
import math
import sys
from dataclasses import dataclass
from zoneinfo import ZoneInfo

import polars as pl

from capture_loader import add_ny_ts, load_capture_window


try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


NY = ZoneInfo("America/New_York")
TICK_SIZE = 0.25


@dataclass(frozen=True)
class BinRow:
    bin: float
    lo: float
    hi: float
    vol: float
    delta: float
    secs: int
    trades: int
    first: dt.datetime
    last: dt.datetime


@dataclass(frozen=True)
class Zone:
    lo: float
    hi: float
    bins: int
    vol: float
    delta: float
    secs: int
    trades: int
    first: dt.datetime
    last: dt.datetime
    score: float


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--date", required=True)
    p.add_argument("--symbol-dir", default="NQM6")
    p.add_argument("--window", required=True, help="NY build window HH:MM-HH:MM")
    p.add_argument("--retest", default="", help="Optional NY retest window HH:MM-HH:MM")
    p.add_argument("--stages", nargs="*", default=[], help="Additional NY windows HH:MM-HH:MM to rank sequentially")
    p.add_argument("--direction", choices=["UP", "DOWN"], required=True)
    p.add_argument("--price-lo", type=float, default=None)
    p.add_argument("--price-hi", type=float, default=None)
    p.add_argument("--anchor-price", type=float, default=None)
    p.add_argument("--side", choices=["all", "above", "below", "at"], default="all")
    p.add_argument("--bin-points", type=float, default=4.0)
    p.add_argument("--min-zone-bins", type=int, default=2)
    p.add_argument("--min-zone-vol", type=float, default=1200.0)
    p.add_argument("--min-zone-sec", type=int, default=35)
    p.add_argument("--top", type=int, default=8)
    return p.parse_args()


def ny_dt(day: dt.date, hhmm: str) -> dt.datetime:
    hour, minute = [int(x) for x in hhmm.split(":", 1)]
    return dt.datetime(day.year, day.month, day.day, hour, minute, tzinfo=NY)


def parse_window(day: dt.date, text: str) -> tuple[dt.datetime, dt.datetime]:
    start_s, end_s = text.split("-", 1)
    return ny_dt(day, start_s), ny_dt(day, end_s)


def ny_label(ts: dt.datetime | None) -> str:
    return "-" if ts is None else ts.astimezone(NY).strftime("%H:%M:%S")


def price_bin_expr(bin_points: float) -> pl.Expr:
    return ((pl.col("price") / bin_points).floor() * bin_points).round(2)


def filter_price(ticks: pl.DataFrame, lo: float | None, hi: float | None) -> pl.DataFrame:
    out = ticks
    if lo is not None:
        out = out.filter(pl.col("price") >= lo)
    if hi is not None:
        out = out.filter(pl.col("price") <= hi)
    return out


def profile(ticks: pl.DataFrame, bin_points: float) -> list[BinRow]:
    if ticks.height == 0:
        return []
    rows = (
        ticks.with_columns(
            price_bin_expr(bin_points).alias("bin"),
            (pl.col("timestamp_us") // 1_000_000).cast(pl.Int64).alias("sec"),
        )
        .group_by("bin")
        .agg(
            pl.col("price").min().alias("lo"),
            pl.col("price").max().alias("hi"),
            pl.col("size").sum().alias("vol"),
            (pl.col("size") * pl.col("aggressor_sign")).sum().alias("delta"),
            pl.col("sec").n_unique().alias("secs"),
            pl.len().alias("trades"),
            pl.col("ts").min().alias("first"),
            pl.col("ts").max().alias("last"),
        )
        .sort("bin")
    )
    return [
        BinRow(
            bin=float(r["bin"]),
            lo=float(r["lo"]),
            hi=float(r["hi"]),
            vol=float(r["vol"]),
            delta=float(r["delta"]),
            secs=int(r["secs"]),
            trades=int(r["trades"]),
            first=r["first"],
            last=r["last"],
        )
        for r in rows.iter_rows(named=True)
    ]


def median(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2.0


def zone_from_bins(rows: list[BinRow], max_vol: float, max_secs: int) -> Zone:
    vol = sum(r.vol for r in rows)
    secs = sum(r.secs for r in rows)
    trades = sum(r.trades for r in rows)
    delta = sum(r.delta for r in rows)
    span = max(1.0, rows[-1].hi - rows[0].lo + TICK_SIZE)
    density = vol / span
    vol_norm = vol / max(1.0, max_vol)
    sec_norm = secs / max(1.0, max_secs)
    balance_bonus = 1.0 - min(1.0, abs(delta) / max(1.0, vol))
    score = density * (0.70 + 0.20 * sec_norm + 0.10 * balance_bonus) * math.log1p(vol_norm)
    return Zone(
        lo=min(r.lo for r in rows),
        hi=max(r.hi for r in rows),
        bins=len(rows),
        vol=vol,
        delta=delta,
        secs=secs,
        trades=trades,
        first=min(r.first for r in rows),
        last=max(r.last for r in rows),
        score=score,
    )


def build_zones(
    rows: list[BinRow],
    bin_points: float,
    min_zone_bins: int,
    min_zone_vol: float,
    min_zone_sec: int,
) -> list[Zone]:
    if not rows:
        return []
    vols = [r.vol for r in rows]
    secs = [r.secs for r in rows]
    max_vol = max(vols)
    max_secs = max(secs)
    med_vol = median(vols)
    med_secs = median([float(x) for x in secs])
    vol_cut = max(min_zone_vol, med_vol * 1.35, max_vol * 0.28)
    sec_cut = max(min_zone_sec, int(med_secs * 1.10))

    zones: list[Zone] = []
    current: list[BinRow] = []
    for row in rows:
        qualifies = (
            row.vol >= vol_cut
            or (row.vol >= min_zone_vol and row.secs >= sec_cut)
            or (row.vol >= med_vol * 0.75 and row.secs >= min_zone_sec)
        )
        adjacent = current and abs(row.bin - current[-1].bin - bin_points) < 0.01
        if qualifies and (not current or adjacent):
            current.append(row)
        else:
            if current:
                zone = zone_from_bins(current, max_vol, max_secs)
                if zone.bins >= min_zone_bins or zone.vol >= min_zone_vol * 2:
                    zones.append(zone)
            current = [row] if qualifies else []
    if current:
        zone = zone_from_bins(current, max_vol, max_secs)
        if zone.bins >= min_zone_bins or zone.vol >= min_zone_vol * 2:
            zones.append(zone)
    return sorted(zones, key=lambda z: z.score, reverse=True)


def thin_corridors(rows: list[BinRow], bin_points: float) -> list[Zone]:
    if not rows:
        return []
    med_vol = median([r.vol for r in rows])
    max_vol = max(r.vol for r in rows)
    max_secs = max(r.secs for r in rows)
    cut = max(50.0, med_vol * 0.45)

    corridors: list[Zone] = []
    current: list[BinRow] = []
    for row in rows:
        qualifies = row.vol <= cut
        adjacent = current and abs(row.bin - current[-1].bin - bin_points) < 0.01
        if qualifies and (not current or adjacent):
            current.append(row)
        else:
            if len(current) >= 2:
                corridors.append(zone_from_bins(current, max_vol, max_secs))
            current = [row] if qualifies else []
    if len(current) >= 2:
        corridors.append(zone_from_bins(current, max_vol, max_secs))
    return corridors


def summarize_ticks(ticks: pl.DataFrame) -> dict[str, float]:
    if ticks.height == 0:
        return {"open": math.nan, "high": math.nan, "low": math.nan, "close": math.nan, "vol": 0.0, "delta": 0.0}
    return ticks.select(
        pl.col("price").first().alias("open"),
        pl.col("price").max().alias("high"),
        pl.col("price").min().alias("low"),
        pl.col("price").last().alias("close"),
        pl.col("size").sum().alias("vol"),
        (pl.col("size") * pl.col("aggressor_sign")).sum().alias("delta"),
    ).row(0, named=True)


def retest_metrics(ticks: pl.DataFrame, zone: Zone, direction: str) -> str:
    touches = ticks.filter((pl.col("price") >= zone.lo) & (pl.col("price") <= zone.hi))
    if touches.height == 0:
        return "retest=-"
    first = touches.row(0, named=True)["ts"]
    post = ticks.filter(pl.col("ts") >= first)
    s = summarize_ticks(post)
    if direction == "UP":
        favorable = max(0.0, float(s["high"]) - zone.hi)
        adverse = max(0.0, zone.lo - float(s["low"]))
    else:
        favorable = max(0.0, zone.lo - float(s["low"]))
        adverse = max(0.0, float(s["high"]) - zone.hi)
    accepted_through = adverse > 4.0 and favorable < adverse
    tag = "accepted-through" if accepted_through else "held/rejected"
    return (
        f"retest={ny_label(first)} fav={favorable:.2f} adverse={adverse:.2f} "
        f"postC={float(s['close']):.2f} {tag}"
    )


def zone_side(zone: Zone, anchor: float, direction: str) -> str:
    if direction == "UP":
        if zone.hi < anchor:
            return "below"
        if zone.lo > anchor:
            return "above"
        return "at"
    if zone.lo > anchor:
        return "above"
    if zone.hi < anchor:
        return "below"
    return "at"


def fmt_zone(z: Zone, anchor: float, direction: str, retest: str = "") -> str:
    return (
        f"{z.lo:8.2f}-{z.hi:<8.2f} {zone_side(z, anchor, direction):<5} "
        f"score={z.score:7.1f} bins={z.bins:2d} vol={z.vol:7.0f} "
        f"delta={z.delta:+7.0f} secs={z.secs:4d} "
        f"{ny_label(z.first)}-{ny_label(z.last)} {retest}"
    )


def filter_side(zones: list[Zone], anchor: float, direction: str, side: str) -> list[Zone]:
    if side == "all":
        return zones
    return [z for z in zones if zone_side(z, anchor, direction) == side]


def main() -> None:
    args = parse_args()
    day = dt.date.fromisoformat(args.date)
    start, end = parse_window(day, args.window)
    retest_start, retest_end = parse_window(day, args.retest) if args.retest else (end, end)
    stage_windows = [parse_window(day, text) for text in args.stages]
    load_start = min([start, retest_start, *[w[0] for w in stage_windows]])
    load_end = max([end, retest_end, *[w[1] for w in stage_windows]])

    ticks = add_ny_ts(load_capture_window("ticks", args.symbol_dir, load_start, load_end))
    build_ticks = ticks.filter((pl.col("ts") >= start) & (pl.col("ts") < end))
    build_ticks = filter_price(build_ticks, args.price_lo, args.price_hi)
    retest_ticks = ticks.filter((pl.col("ts") >= retest_start) & (pl.col("ts") < retest_end))
    retest_ticks = filter_price(retest_ticks, args.price_lo, args.price_hi)
    rows = profile(build_ticks, args.bin_points)
    zones = build_zones(rows, args.bin_points, args.min_zone_bins, args.min_zone_vol, args.min_zone_sec)
    thins = thin_corridors(rows, args.bin_points)
    summary = summarize_ticks(build_ticks)
    anchor = float(args.anchor_price) if args.anchor_price is not None else float(summary["close"])

    print(f"Retracement zone probe {args.date} {args.symbol_dir} {args.window} direction={args.direction}")
    print(
        f"Build O={summary['open']:.2f} H={summary['high']:.2f} L={summary['low']:.2f} "
        f"C={summary['close']:.2f} vol={summary['vol']:.0f} delta={summary['delta']:+.0f}"
    )
    if args.price_lo is not None or args.price_hi is not None:
        print(f"Price filter: {args.price_lo if args.price_lo is not None else '-inf'} to {args.price_hi if args.price_hi is not None else '+inf'}")
    print(f"Anchor for side labels: {anchor:.2f}; side filter: {args.side}")
    print("")
    print("Ranked interest zones")
    shown_zones = filter_side(zones, anchor, args.direction, args.side)
    if not shown_zones:
        print("  none")
    for zone in shown_zones[: args.top]:
        retest = retest_metrics(retest_ticks, zone, args.direction) if args.retest else ""
        print("  " + fmt_zone(zone, anchor, args.direction, retest))

    print("")
    print("Thin corridors")
    shown_thins = filter_side(thins, anchor, args.direction, args.side)
    if not shown_thins:
        print("  none")
    for zone in shown_thins[: args.top]:
        print("  " + fmt_zone(zone, anchor, args.direction))

    print("")
    print("All bins")
    for row in rows:
        print(
            f"  {row.bin:8.2f} {row.lo:8.2f}-{row.hi:<8.2f} "
            f"vol={row.vol:7.0f} delta={row.delta:+7.0f} secs={row.secs:4d}"
        )

    for idx, (stage_start, stage_end) in enumerate(stage_windows, start=1):
        stage_ticks = ticks.filter((pl.col("ts") >= stage_start) & (pl.col("ts") < stage_end))
        stage_ticks = filter_price(stage_ticks, args.price_lo, args.price_hi)
        stage_summary = summarize_ticks(stage_ticks)
        stage_anchor = (
            float(args.anchor_price)
            if args.anchor_price is not None
            else float(stage_summary["close"])
        )
        stage_rows = profile(stage_ticks, args.bin_points)
        stage_zones = filter_side(
            build_zones(stage_rows, args.bin_points, args.min_zone_bins, args.min_zone_vol, args.min_zone_sec),
            stage_anchor,
            args.direction,
            args.side,
        )
        stage_thins = filter_side(thin_corridors(stage_rows, args.bin_points), stage_anchor, args.direction, args.side)
        print("")
        print(f"Stage {idx}: {ny_label(stage_start)}-{ny_label(stage_end)}")
        print(
            f"  O={stage_summary['open']:.2f} H={stage_summary['high']:.2f} "
            f"L={stage_summary['low']:.2f} C={stage_summary['close']:.2f} "
            f"vol={stage_summary['vol']:.0f} delta={stage_summary['delta']:+.0f}"
        )
        print("  zones")
        if not stage_zones:
            print("    none")
        for zone in stage_zones[: args.top]:
            print("    " + fmt_zone(zone, stage_anchor, args.direction))
        print("  thin")
        if not stage_thins:
            print("    none")
        for zone in stage_thins[: args.top]:
            print("    " + fmt_zone(zone, stage_anchor, args.direction))


if __name__ == "__main__":
    main()
