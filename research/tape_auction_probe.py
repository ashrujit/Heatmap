"""Tick-only auction replay for OR5, IB, and time-of-day decision windows.

This is research code. It intentionally ignores L2 snapshots and asks whether
the trade tape alone can describe the auction questions the user actually asks:
did a break build business, did it reclaim, where did shelves form, and what did
late-morning / PM watch windows do at extremes?
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import math
import os
import sys
from dataclasses import dataclass, replace
from zoneinfo import ZoneInfo

import polars as pl

from capture_loader import add_ny_ts, load_capture_window


try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


NY = ZoneInfo("America/New_York")
TICK_SIZE = 0.25
VPOC_BIN_POINTS = 0.50
SHELF_BIN_POINTS = 4.0
OUT_DIR = os.path.join(os.path.dirname(__file__), "out")


@dataclass(frozen=True)
class TapeSummary:
    open: float
    high: float
    low: float
    close: float
    vol: float
    buy: float
    sell: float
    delta: float
    trades: int
    vwap: float
    vpoc: float


@dataclass(frozen=True)
class BreakAudit:
    scope: str
    direction: str
    level: float
    start: dt.datetime
    end: dt.datetime
    cross_ts: dt.datetime | None
    reclaim_ts: dt.datetime | None
    cross_row: int | None
    reclaim_row: int | None
    first_cross_ts: dt.datetime | None
    attempts: int
    label: str
    excursion: float
    outside_sec: float
    outside_vol: float
    outside_delta: float
    aligned_delta: float
    outside_trades: int
    accepted_bins: int
    close_5m: float
    close_15m: float
    close_30m: float
    max_gap_sec: float


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--date", required=True, help="RTH date, e.g. 2026-05-22")
    p.add_argument("--symbol-dir", default="NQM6")
    p.add_argument("--rth-start", default="09:30")
    p.add_argument("--rth-end", default="16:00")
    p.add_argument("--preopen-start", default="00:00")
    p.add_argument("--or-min", type=int, default=5)
    p.add_argument("--ib-min", type=int, default=60)
    p.add_argument("--ib-break-end", default="12:30")
    p.add_argument("--gap-sec", type=float, default=5.0)
    p.add_argument("--shelf-bin-points", type=float, default=SHELF_BIN_POINTS)
    p.add_argument("--min-shelf-vol", type=float, default=450.0)
    p.add_argument("--min-shelf-sec", type=int, default=20)
    p.add_argument("--min-break-excursion", type=float, default=4.0)
    p.add_argument("--reclaim-buffer-points", type=float, default=2.0)
    p.add_argument("--episode-merge-sec", type=float, default=30.0)
    p.add_argument("--cap-points", type=float, default=8.0)
    p.add_argument("--out-dir", default=OUT_DIR)
    return p.parse_args()


def ny_dt(day: dt.date, hhmm: str) -> dt.datetime:
    hour, minute = [int(part) for part in hhmm.split(":", 1)]
    return dt.datetime(day.year, day.month, day.day, hour, minute, tzinfo=NY)


def ny_label(ts: dt.datetime | None, with_date: bool = False) -> str:
    if ts is None:
        return "-"
    local = ts.astimezone(NY)
    fmt = "%Y-%m-%d %H:%M:%S" if with_date else "%H:%M:%S"
    return local.strftime(fmt)


def safe_float(value: object) -> float:
    try:
        return float(value)
    except Exception:
        return math.nan


def filter_window(ticks: pl.DataFrame, start: dt.datetime, end: dt.datetime) -> pl.DataFrame:
    return ticks.filter((pl.col("ts") >= start) & (pl.col("ts") < end))


def empty_summary() -> TapeSummary:
    return TapeSummary(
        open=math.nan,
        high=math.nan,
        low=math.nan,
        close=math.nan,
        vol=0.0,
        buy=0.0,
        sell=0.0,
        delta=0.0,
        trades=0,
        vwap=math.nan,
        vpoc=math.nan,
    )


def price_bin_expr(bin_points: float) -> pl.Expr:
    return ((pl.col("price") / bin_points).floor() * bin_points).round(2)


def vpoc(ticks: pl.DataFrame, bin_points: float = VPOC_BIN_POINTS) -> float:
    if ticks.height == 0:
        return math.nan
    prof = (
        ticks.with_columns(price_bin_expr(bin_points).alias("bin"))
        .group_by("bin")
        .agg(pl.col("size").sum().alias("vol"))
        .sort(["vol", "bin"], descending=[True, False])
    )
    if prof.height == 0:
        return math.nan
    return float(prof.row(0, named=True)["bin"])


def summarize(ticks: pl.DataFrame) -> TapeSummary:
    if ticks.height == 0:
        return empty_summary()
    row = ticks.select(
        pl.col("price").first().alias("open"),
        pl.col("price").max().alias("high"),
        pl.col("price").min().alias("low"),
        pl.col("price").last().alias("close"),
        pl.col("size").sum().alias("vol"),
        pl.when(pl.col("aggressor_sign") > 0).then(pl.col("size")).otherwise(0.0).sum().alias("buy"),
        pl.when(pl.col("aggressor_sign") < 0).then(pl.col("size")).otherwise(0.0).sum().alias("sell"),
        (pl.col("price") * pl.col("size")).sum().alias("pv"),
        (pl.col("size") * pl.col("aggressor_sign")).sum().alias("delta"),
        pl.len().alias("trades"),
    ).row(0, named=True)
    vol = safe_float(row["vol"])
    return TapeSummary(
        open=safe_float(row["open"]),
        high=safe_float(row["high"]),
        low=safe_float(row["low"]),
        close=safe_float(row["close"]),
        vol=vol,
        buy=safe_float(row["buy"]),
        sell=safe_float(row["sell"]),
        delta=safe_float(row["delta"]),
        trades=int(row["trades"]),
        vwap=safe_float(row["pv"]) / vol if vol > 0 else math.nan,
        vpoc=vpoc(ticks),
    )


def signed_dir(direction: str) -> int:
    return 1 if direction.upper() == "UP" else -1


def outside_filter(direction: str, level: float) -> pl.Expr:
    if direction.upper() == "UP":
        return pl.col("price") > level
    return pl.col("price") < level


def reclaim_filter(direction: str, level: float) -> pl.Expr:
    if direction.upper() == "UP":
        return pl.col("price") <= level
    return pl.col("price") >= level


def reclaim_bool(direction: str, price: float, level: float, buffer_points: float) -> bool:
    if direction == "UP":
        return price <= level - buffer_points
    return price >= level + buffer_points


def max_gap_seconds(ticks: pl.DataFrame) -> float:
    if ticks.height < 2:
        return 0.0
    row = ticks.select((pl.col("timestamp_us").diff().max() / 1_000_000.0).alias("gap")).row(0, named=True)
    return safe_float(row["gap"])


def data_gaps(ticks: pl.DataFrame, min_gap_sec: float) -> list[tuple[dt.datetime, dt.datetime, float]]:
    if ticks.height < 2:
        return []
    gaps = (
        ticks.select(
            pl.col("ts").shift(1).alias("prev_ts"),
            pl.col("ts").alias("ts"),
            (pl.col("timestamp_us").diff() / 1_000_000.0).alias("gap_sec"),
        )
        .drop_nulls()
        .filter(pl.col("gap_sec") >= min_gap_sec)
    )
    return [(r["prev_ts"], r["ts"], float(r["gap_sec"])) for r in gaps.iter_rows(named=True)]


def shelf_profile(ticks: pl.DataFrame, bin_points: float) -> list[dict]:
    if ticks.height == 0:
        return []
    prof = (
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
            pl.len().alias("trades"),
            pl.col("sec").n_unique().alias("seconds"),
            pl.col("ts").min().alias("first_ts"),
            pl.col("ts").max().alias("last_ts"),
        )
        .sort(["vol", "seconds"], descending=[True, True])
    )
    return list(prof.iter_rows(named=True))


def classify_break(
    reclaimed: bool,
    excursion: float,
    outside_sec: float,
    accepted_bins: int,
    aligned_delta: float,
    close_15m: float,
    close_30m: float,
    direction: str,
    level: float,
) -> str:
    if outside_sec <= 0:
        return "quick-reject" if excursion > 0 else "no-break"
    if reclaimed and outside_sec < 180:
        return "quick-reject"
    if reclaimed and accepted_bins == 0:
        return "rejected"

    held_15 = close_15m > level if direction == "UP" else close_15m < level
    held_30 = close_30m > level if direction == "UP" else close_30m < level
    speed = excursion / max(1.0, outside_sec / 60.0)
    if accepted_bins == 0 and speed >= 8.0:
        return "fast/no-build"
    if reclaimed and accepted_bins >= 1 and not held_15:
        return "built-failed"
    if accepted_bins >= 2 and aligned_delta > 0 and held_15:
        if not held_30:
            return "accepted-fail"
        return "accepted"
    if accepted_bins >= 1:
        return "building"
    return "thin/suspect"


def close_after(ticks: pl.DataFrame, cross_ts: dt.datetime | None, end: dt.datetime, minutes: int) -> float:
    if cross_ts is None:
        return math.nan
    sub = filter_window(ticks, cross_ts, min(end, cross_ts + dt.timedelta(minutes=minutes)))
    if sub.height == 0:
        return math.nan
    return float(sub.select(pl.col("price").last().alias("close")).row(0, named=True)["close"])


def outside_bool(direction: str, price: float, level: float) -> bool:
    return price > level if direction == "UP" else price < level


def episode_bounds(
    window: pl.DataFrame,
    direction: str,
    level: float,
    reclaim_buffer_points: float,
) -> list[tuple[int, int | None, dt.datetime, dt.datetime | None]]:
    episodes: list[tuple[int, int | None, dt.datetime, dt.datetime | None]] = []
    active = False
    cross_row: int | None = None
    cross_ts: dt.datetime | None = None

    for row in window.select("_row", "ts", "price").iter_rows(named=True):
        row_id = int(row["_row"])
        ts = row["ts"]
        price = float(row["price"])
        if not active:
            if outside_bool(direction, price, level):
                active = True
                cross_row = row_id
                cross_ts = ts
            continue

        if reclaim_bool(direction, price, level, reclaim_buffer_points):
            if cross_row is not None and cross_ts is not None:
                episodes.append((cross_row, row_id, cross_ts, ts))
            active = False
            cross_row = None
            cross_ts = None

    if active and cross_row is not None and cross_ts is not None:
        episodes.append((cross_row, None, cross_ts, None))
    return episodes


def merge_episode_bounds(
    episodes: list[tuple[int, int | None, dt.datetime, dt.datetime | None]],
    merge_gap_sec: float,
) -> list[tuple[int, int | None, dt.datetime, dt.datetime | None]]:
    if not episodes:
        return []

    merged: list[tuple[int, int | None, dt.datetime, dt.datetime | None]] = [episodes[0]]
    for cross_row, reclaim_row, cross_ts, reclaim_ts in episodes[1:]:
        last_cross_row, last_reclaim_row, last_cross_ts, last_reclaim_ts = merged[-1]
        if last_reclaim_ts is not None and (cross_ts - last_reclaim_ts).total_seconds() <= merge_gap_sec:
            merged[-1] = (last_cross_row, reclaim_row, last_cross_ts, reclaim_ts)
        else:
            merged.append((cross_row, reclaim_row, cross_ts, reclaim_ts))
    return merged


def build_break_audit(
    ticks: pl.DataFrame,
    scope: str,
    direction: str,
    level: float,
    start: dt.datetime,
    end: dt.datetime,
    cross_row: int,
    reclaim_row: int | None,
    cross_ts: dt.datetime,
    reclaim_ts: dt.datetime | None,
    shelf_bin_points: float,
    min_shelf_vol: float,
    min_shelf_sec: int,
) -> BreakAudit:
    side = signed_dir(direction)
    post = ticks.filter((pl.col("_row") >= cross_row) & (pl.col("ts") < end))
    leg = post.filter(pl.col("_row") < reclaim_row) if reclaim_row is not None else post
    outside_leg = leg.filter(outside_filter(direction, level))
    leg_summary = summarize(outside_leg)
    if direction == "UP":
        excursion = max(0.0, leg_summary.high - level)
    else:
        excursion = max(0.0, level - leg_summary.low)

    shelves = shelf_profile(outside_leg, shelf_bin_points)
    accepted_bins = sum(
        1 for row in shelves if float(row["vol"]) >= min_shelf_vol and int(row["seconds"]) >= min_shelf_sec
    )
    leg_end = reclaim_ts if reclaim_ts is not None else end
    outside_sec = max(0.0, (leg_end - cross_ts).total_seconds())
    aligned_delta = side * leg_summary.delta
    close_5m = close_after(ticks, cross_ts, end, 5)
    close_15m = close_after(ticks, cross_ts, end, 15)
    close_30m = close_after(ticks, cross_ts, end, 30)
    label = classify_break(
        reclaimed=reclaim_ts is not None,
        excursion=excursion,
        outside_sec=outside_sec,
        accepted_bins=accepted_bins,
        aligned_delta=aligned_delta,
        close_15m=close_15m,
        close_30m=close_30m,
        direction=direction,
        level=level,
    )

    return BreakAudit(
        scope=scope,
        direction=direction,
        level=level,
        start=start,
        end=end,
        cross_ts=cross_ts,
        reclaim_ts=reclaim_ts,
        cross_row=cross_row,
        reclaim_row=reclaim_row,
        first_cross_ts=cross_ts,
        attempts=1,
        label=label,
        excursion=excursion,
        outside_sec=outside_sec,
        outside_vol=leg_summary.vol,
        outside_delta=leg_summary.delta,
        aligned_delta=aligned_delta,
        outside_trades=leg_summary.trades,
        accepted_bins=accepted_bins,
        close_5m=close_5m,
        close_15m=close_15m,
        close_30m=close_30m,
        max_gap_sec=max_gap_seconds(outside_leg),
    )


def audit_break(
    ticks: pl.DataFrame,
    scope: str,
    direction: str,
    level: float,
    start: dt.datetime,
    end: dt.datetime,
    shelf_bin_points: float,
    min_shelf_vol: float,
    min_shelf_sec: int,
    min_break_excursion: float,
    reclaim_buffer_points: float,
    episode_merge_sec: float,
) -> BreakAudit:
    window = filter_window(ticks, start, end)
    raw_episodes = episode_bounds(window, direction, level, reclaim_buffer_points)
    episodes = merge_episode_bounds(raw_episodes, episode_merge_sec)
    if not raw_episodes:
        touch_excursion = 0.0
        if window.height:
            s = summarize(window)
            touch_excursion = max(0.0, s.high - level) if direction == "UP" else max(0.0, level - s.low)
        return BreakAudit(
            scope=scope,
            direction=direction,
            level=level,
            start=start,
            end=end,
            cross_ts=None,
            reclaim_ts=None,
            cross_row=None,
            reclaim_row=None,
            first_cross_ts=None,
            attempts=0,
            label="no-break",
            excursion=touch_excursion,
            outside_sec=0.0,
            outside_vol=0.0,
            outside_delta=0.0,
            aligned_delta=0.0,
            outside_trades=0,
            accepted_bins=0,
            close_5m=math.nan,
            close_15m=math.nan,
            close_30m=math.nan,
            max_gap_sec=max_gap_seconds(window),
        )

    audits = [
        build_break_audit(
            ticks,
            scope,
            direction,
            level,
            start,
            end,
            cross_row,
            reclaim_row,
            cross_ts,
            reclaim_ts,
            shelf_bin_points,
            min_shelf_vol,
            min_shelf_sec,
        )
        for cross_row, reclaim_row, cross_ts, reclaim_ts in episodes
    ]
    meaningful = [
        a
        for a in audits
        if (
            a.accepted_bins > 0
            or a.outside_vol >= min_shelf_vol
            or a.outside_sec >= min_shelf_sec
            or (a.excursion >= min_break_excursion * 2.0 and a.outside_vol >= min_shelf_vol * 0.5)
        )
    ]
    selected = meaningful[0] if meaningful else max(audits, key=lambda a: (a.excursion, a.outside_vol))
    return replace(
        selected,
        first_cross_ts=episodes[0][2],
        attempts=len(raw_episodes),
    )


def audit_outside_ticks(ticks: pl.DataFrame, audit: BreakAudit) -> pl.DataFrame:
    if audit.cross_row is None:
        return ticks.clear()
    if audit.reclaim_row is not None:
        scoped = ticks.filter((pl.col("_row") >= audit.cross_row) & (pl.col("_row") < audit.reclaim_row))
    else:
        scoped = ticks.filter((pl.col("_row") >= audit.cross_row) & (pl.col("ts") < audit.end))
    return scoped.filter(outside_filter(audit.direction, audit.level))


def bar_rows(ticks: pl.DataFrame, start: dt.datetime, end: dt.datetime, minutes: int) -> list[tuple[dt.datetime, TapeSummary]]:
    rows: list[tuple[dt.datetime, TapeSummary]] = []
    cur = start
    while cur < end:
        nxt = min(end, cur + dt.timedelta(minutes=minutes))
        rows.append((cur, summarize(filter_window(ticks, cur, nxt))))
        cur = nxt
    return rows


def fmt_price(value: float) -> str:
    if not math.isfinite(value):
        return "-"
    return f"{value:.2f}"


def fmt_summary(s: TapeSummary) -> str:
    return (
        f"O={fmt_price(s.open)} H={fmt_price(s.high)} L={fmt_price(s.low)} C={fmt_price(s.close)} "
        f"vol={s.vol:.0f} delta={s.delta:+.0f} trades={s.trades:,} "
        f"vwap={fmt_price(s.vwap)} vpoc={fmt_price(s.vpoc)}"
    )


def fmt_audit(a: BreakAudit) -> str:
    attempt_note = f" first={ny_label(a.first_cross_ts)} n={a.attempts}" if a.attempts > 1 else f" n={a.attempts}"
    return (
        f"{a.scope:<10} {a.direction:<4} level={a.level:.2f} cross={ny_label(a.cross_ts):<8} "
        f"reclaim={ny_label(a.reclaim_ts):<8} label={a.label:<13} moved={a.excursion:5.2f} "
        f"outside={a.outside_sec:6.0f}s vol={a.outside_vol:7.0f} "
        f"delta={a.outside_delta:+7.0f} aligned={a.aligned_delta:+7.0f} "
        f"bins={a.accepted_bins:2d} c5={fmt_price(a.close_5m):>8} "
        f"c15={fmt_price(a.close_15m):>8} c30={fmt_price(a.close_30m):>8}{attempt_note}"
    )


def write_break_csv(path: str, audits: list[BreakAudit]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "scope",
                "direction",
                "level",
                "start",
                "end",
                "cross",
                "reclaim",
                "first_cross",
                "attempts",
                "cross_row",
                "reclaim_row",
                "label",
                "excursion",
                "outside_sec",
                "outside_vol",
                "outside_delta",
                "aligned_delta",
                "outside_trades",
                "accepted_bins",
                "close_5m",
                "close_15m",
                "close_30m",
                "max_gap_sec",
            ]
        )
        for a in audits:
            w.writerow(
                [
                    a.scope,
                    a.direction,
                    f"{a.level:.2f}",
                    a.start.isoformat(),
                    a.end.isoformat(),
                    a.cross_ts.isoformat() if a.cross_ts else "",
                    a.reclaim_ts.isoformat() if a.reclaim_ts else "",
                    a.first_cross_ts.isoformat() if a.first_cross_ts else "",
                    a.attempts,
                    a.cross_row if a.cross_row is not None else "",
                    a.reclaim_row if a.reclaim_row is not None else "",
                    a.label,
                    f"{a.excursion:.2f}",
                    f"{a.outside_sec:.1f}",
                    f"{a.outside_vol:.0f}",
                    f"{a.outside_delta:.0f}",
                    f"{a.aligned_delta:.0f}",
                    a.outside_trades,
                    a.accepted_bins,
                    f"{a.close_5m:.2f}" if math.isfinite(a.close_5m) else "",
                    f"{a.close_15m:.2f}" if math.isfinite(a.close_15m) else "",
                    f"{a.close_30m:.2f}" if math.isfinite(a.close_30m) else "",
                    f"{a.max_gap_sec:.3f}",
                ]
            )


def add_shelf_lines(
    lines: list[str],
    title: str,
    ticks: pl.DataFrame,
    bin_points: float,
    min_shelf_vol: float,
    min_shelf_sec: int,
    max_rows: int = 6,
) -> None:
    lines.append(title)
    rows = shelf_profile(ticks, bin_points)
    rows = [r for r in rows if float(r["vol"]) >= min_shelf_vol or int(r["seconds"]) >= min_shelf_sec]
    if not rows:
        lines.append("  none")
        return
    lines.append("  bin        span          vol    delta  sec first    last")
    for row in rows[:max_rows]:
        lines.append(
            f"  {float(row['bin']):8.2f} {float(row['lo']):8.2f}-{float(row['hi']):<8.2f} "
            f"{float(row['vol']):7.0f} {float(row['delta']):+8.0f} {int(row['seconds']):4d} "
            f"{ny_label(row['first_ts']):<8} {ny_label(row['last_ts']):<8}"
        )


def profile_rows(ticks: pl.DataFrame, bin_points: float) -> list[dict]:
    if ticks.height == 0:
        return []
    prof = (
        ticks.with_columns(price_bin_expr(bin_points).alias("bin"))
        .group_by("bin")
        .agg(
            pl.col("price").min().alias("lo"),
            pl.col("price").max().alias("hi"),
            pl.col("size").sum().alias("vol"),
            (pl.col("size") * pl.col("aggressor_sign")).sum().alias("delta"),
            pl.len().alias("trades"),
        )
        .sort("bin")
    )
    return list(prof.iter_rows(named=True))


def preopen_shelf_lines(ticks: pl.DataFrame, bin_points: float = SHELF_BIN_POINTS) -> list[str]:
    lines: list[str] = []
    rows = profile_rows(ticks, bin_points)
    if not rows:
        lines.append("Pre-RTH tick shelves: none")
        return lines

    max_vol = max(float(r["vol"]) for r in rows)
    threshold = max(1500.0, max_vol * 0.50)
    shelves: list[list[dict]] = []
    current: list[dict] = []
    for row in rows:
        qualifies = float(row["vol"]) >= threshold
        adjacent = current and abs(float(row["bin"]) - float(current[-1]["bin"]) - bin_points) < 0.01
        if qualifies and (not current or adjacent):
            current.append(row)
        else:
            if current:
                shelves.append(current)
            current = [row] if qualifies else []
    if current:
        shelves.append(current)

    shelves = [s for s in shelves if len(s) >= 2]
    shelves.sort(key=lambda s: sum(float(r["vol"]) for r in s), reverse=True)

    lines.append("Pre-RTH tick shelves")
    lines.append(f"  threshold={threshold:.0f} contracts per {bin_points:.0f}-point bin")
    if not shelves:
        lines.append("  none")
        return lines
    lines.append("  zone                 bins      vol    delta")
    for shelf in shelves[:5]:
        lo = min(float(r["lo"]) for r in shelf)
        hi = max(float(r["hi"]) for r in shelf)
        vol = sum(float(r["vol"]) for r in shelf)
        delta = sum(float(r["delta"]) for r in shelf)
        lines.append(f"  {lo:8.2f}-{hi:<8.2f} {len(shelf):4d} {vol:8.0f} {delta:+8.0f}")
    return lines


def unique_seconds(ticks: pl.DataFrame) -> int:
    if ticks.height == 0:
        return 0
    return int(ticks.select((pl.col("timestamp_us") // 1_000_000).n_unique().alias("secs")).item())


def progress_tags(
    direction: str,
    age_sec: int,
    move: float,
    vol: float,
    aligned_delta: float,
    vol_per_point: float,
    cap_pct: float,
    close_loc: float,
    accepted_bins: int,
) -> str:
    if move <= 0 or vol <= 0:
        return "no-outside"

    tags: list[str] = []
    speed = move / max(0.25, age_sec / 60.0)
    delta_ratio = aligned_delta / max(1.0, vol)
    if speed >= 60.0 and vol_per_point <= 90.0 and delta_ratio >= 0.20:
        tags.append("aggressive-flush")
    elif speed >= 25.0 and vol_per_point <= 110.0:
        tags.append("thin-fast")
    if age_sec >= 60 and move >= 20.0 and cap_pct <= 0.12:
        tags.append("cap-empty")
    if move >= 20.0 and close_loc < 0.50:
        tags.append("off-extreme")
    if age_sec >= 60 and move >= 12.0 and accepted_bins == 0:
        tags.append("no-shelf")
    if accepted_bins >= 2 and close_loc >= 0.65 and cap_pct > 0.12:
        tags.append("building")
    return ",".join(tags) if tags else "watch"


def break_progress_lines(
    ticks: pl.DataFrame,
    audit: BreakAudit,
    shelf_bin_points: float,
    min_shelf_vol: float,
    min_shelf_sec: int,
    cap_points: float,
    windows: list[int] | None = None,
) -> list[str]:
    if windows is None:
        windows = [15, 30, 60, 90, 120, 180, 240, 300]
    lines: list[str] = []
    if audit.cross_row is None or audit.cross_ts is None:
        lines.append(f"{audit.scope} {audit.direction} early verdict: no cross")
        return lines

    side = signed_dir(audit.direction)
    lines.append(f"{audit.scope} {audit.direction} early verdict from {ny_label(audit.cross_ts)}")
    lines.append("  age  end      move   close  loc    vol   delta  v/pt cap8v cap% bins tags")
    for sec in windows:
        end = min(audit.end, audit.cross_ts + dt.timedelta(seconds=sec))
        scoped = ticks.filter((pl.col("_row") >= audit.cross_row) & (pl.col("ts") < end))
        outside = scoped.filter(outside_filter(audit.direction, audit.level))
        s = summarize(outside)
        if outside.height == 0:
            lines.append(f"  {sec:3d} {ny_label(end):<8} no outside prints")
            continue

        if audit.direction == "UP":
            move = max(0.0, s.high - audit.level)
            extreme = s.high
            close_loc = (s.close - audit.level) / max(TICK_SIZE, move)
            cap_lo = max(audit.level, extreme - cap_points)
            cap_hi = extreme
        else:
            move = max(0.0, audit.level - s.low)
            extreme = s.low
            close_loc = (audit.level - s.close) / max(TICK_SIZE, move)
            cap_lo = extreme
            cap_hi = min(audit.level, extreme + cap_points)

        cap = outside.filter((pl.col("price") >= cap_lo) & (pl.col("price") <= cap_hi))
        cap_s = summarize(cap)
        cap_pct = cap_s.vol / max(1.0, s.vol)
        shelves = shelf_profile(outside, shelf_bin_points)
        accepted_bins = sum(
            1 for row in shelves if float(row["vol"]) >= min_shelf_vol and int(row["seconds"]) >= min_shelf_sec
        )
        aligned = side * s.delta
        vol_per_point = s.vol / max(1.0, move)
        tags = progress_tags(
            audit.direction,
            sec,
            move,
            s.vol,
            aligned,
            vol_per_point,
            cap_pct,
            close_loc,
            accepted_bins,
        )
        lines.append(
            f"  {sec:3d} {ny_label(end):<8} {move:6.2f} {s.close:7.2f} {close_loc:5.2f} "
            f"{s.vol:6.0f} {s.delta:+7.0f} {vol_per_point:5.0f} "
            f"{cap_s.vol:5.0f} {cap_pct:4.0%} {accepted_bins:4d} {tags}"
        )
    return lines


def band_summary_line(
    label: str,
    ticks: pl.DataFrame,
    lo: float,
    hi: float,
    total_vol: float,
) -> str:
    band = ticks.filter((pl.col("price") >= lo) & (pl.col("price") < hi))
    s = summarize(band)
    pct = s.vol / max(1.0, total_vol)
    lo_text = "-inf" if math.isinf(lo) and lo < 0 else f"{lo:.2f}"
    hi_text = "+inf" if math.isinf(hi) and hi > 0 else f"{hi:.2f}"
    return (
        f"{label:<12} {lo_text:>8}-{hi_text:<8} vol={s.vol:7.0f} "
        f"pct={pct:5.1%} delta={s.delta:+7.0f} secs={unique_seconds(band):4d}"
    )


def lower_followup_lines(
    ticks: pl.DataFrame,
    audit: BreakAudit,
    open_price: float,
    or_low: float,
) -> list[str]:
    lines: list[str] = []
    if audit.cross_ts is None:
        return lines

    lower_accept = math.floor(or_low / 20.0) * 20.0
    shelf_lo = lower_accept
    shelf_hi = max(open_price, or_low)
    start = audit.cross_ts + dt.timedelta(minutes=2)
    windows = [3, 5, 7, 10, 15]

    lines.append("Lower auction follow-up after first 2 minutes")
    lines.append(
        f"  lower_accept<{lower_accept:.2f}; shelf band {shelf_lo:.2f}-{shelf_hi:.2f}; "
        "watch for lower volume share shrinking while shelf absorbs bounces"
    )
    lines.append("  end      all_vol  all_delta close    below_accept              shelf_band")
    for minute in windows:
        end = audit.cross_ts + dt.timedelta(minutes=minute)
        scoped = filter_window(ticks, start, end)
        s = summarize(scoped)
        below = band_summary_line("below", scoped, -math.inf, lower_accept, s.vol)
        shelf = band_summary_line("shelf", scoped, shelf_lo, shelf_hi + TICK_SIZE, s.vol)
        tag = ""
        below_vol = summarize(scoped.filter(pl.col("price") < lower_accept)).vol
        if minute >= 7 and below_vol / max(1.0, s.vol) <= 0.30 and s.close >= or_low:
            tag = " no-lower-followup"
        lines.append(
            f"  +{minute:<2d}m {s.vol:8.0f} {s.delta:+9.0f} {fmt_price(s.close):>7}  "
            f"{below}  {shelf}{tag}"
        )
    return lines


def first_ts_at_price(ticks: pl.DataFrame, price: float) -> dt.datetime | None:
    if not math.isfinite(price):
        return None
    rows = ticks.filter(pl.col("price") == price)
    if rows.height == 0:
        return None
    return rows.row(0, named=True)["ts"]


def watch_window_lines(
    ticks: pl.DataFrame,
    rth_start: dt.datetime,
    start: dt.datetime,
    end: dt.datetime,
    name: str,
) -> list[str]:
    lines: list[str] = []
    win = filter_window(ticks, start, end)
    before = filter_window(ticks, rth_start, start)
    ws = summarize(win)
    bs = summarize(before)
    lines.append(f"{name:<12} {ny_label(start)}-{ny_label(end)} {fmt_summary(ws)}")
    if win.height == 0 or before.height == 0:
        return lines

    new_high = ws.high > bs.high
    new_low = ws.low < bs.low
    for side, is_new, extreme in (("HIGH", new_high, ws.high), ("LOW", new_low, ws.low)):
        if not is_new:
            continue
        extreme_ts = first_ts_at_price(win, extreme)
        if extreme_ts is None:
            continue
        post = filter_window(ticks, extreme_ts, min(end, extreme_ts + dt.timedelta(minutes=15)))
        cap_lo = extreme - 8.0 if side == "HIGH" else extreme
        cap_hi = extreme if side == "HIGH" else extreme + 8.0
        cap = win.filter((pl.col("price") >= cap_lo) & (pl.col("price") <= cap_hi))
        cap_s = summarize(cap)
        post_s = summarize(post)
        retrace = max(0.0, extreme - post_s.low) if side == "HIGH" else max(0.0, post_s.high - extreme)
        lines.append(
            f"  new_rth_{side.lower()}={extreme:.2f} at {ny_label(extreme_ts)} "
            f"cap8 vol={cap_s.vol:.0f} delta={cap_s.delta:+.0f} "
            f"15m_retrace={retrace:.2f}"
        )
    return lines


def main() -> None:
    args = parse_args()
    os.makedirs(args.out_dir, exist_ok=True)

    rth_day = dt.date.fromisoformat(args.date)
    preopen_start = ny_dt(rth_day, args.preopen_start)
    rth_start = ny_dt(rth_day, args.rth_start)
    rth_end = ny_dt(rth_day, args.rth_end)
    or_end = rth_start + dt.timedelta(minutes=args.or_min)
    ib_end = rth_start + dt.timedelta(minutes=args.ib_min)
    ib_break_end = ny_dt(rth_day, args.ib_break_end)

    load_start = min(preopen_start, rth_start)
    ticks = add_ny_ts(load_capture_window("ticks", args.symbol_dir, load_start, rth_end)).with_row_index("_row")
    preopen_ticks = filter_window(ticks, preopen_start, rth_start)
    rth_ticks = filter_window(ticks, rth_start, rth_end)
    or_ticks = filter_window(ticks, rth_start, or_end)
    ib_ticks = filter_window(ticks, rth_start, ib_end)

    rth = summarize(rth_ticks)
    or5 = summarize(or_ticks)
    ib = summarize(ib_ticks)

    audits = [
        audit_break(
            ticks,
            "OR5",
            "UP",
            or5.high,
            or_end,
            ib_end,
            args.shelf_bin_points,
            args.min_shelf_vol,
            args.min_shelf_sec,
            args.min_break_excursion,
            args.reclaim_buffer_points,
            args.episode_merge_sec,
        ),
        audit_break(
            ticks,
            "OR5",
            "DOWN",
            or5.low,
            or_end,
            ib_end,
            args.shelf_bin_points,
            args.min_shelf_vol,
            args.min_shelf_sec,
            args.min_break_excursion,
            args.reclaim_buffer_points,
            args.episode_merge_sec,
        ),
        audit_break(
            ticks,
            "IB",
            "UP",
            ib.high,
            ib_end,
            ib_break_end,
            args.shelf_bin_points,
            args.min_shelf_vol,
            args.min_shelf_sec,
            args.min_break_excursion,
            args.reclaim_buffer_points,
            args.episode_merge_sec,
        ),
        audit_break(
            ticks,
            "IB",
            "DOWN",
            ib.low,
            ib_end,
            ib_break_end,
            args.shelf_bin_points,
            args.min_shelf_vol,
            args.min_shelf_sec,
            args.min_break_excursion,
            args.reclaim_buffer_points,
            args.episode_merge_sec,
        ),
    ]
    open_down_audit = audit_break(
        ticks,
        "OPEN",
        "DOWN",
        rth.open,
        rth_start + dt.timedelta(minutes=30),
        ib_end,
        args.shelf_bin_points,
        args.min_shelf_vol,
        args.min_shelf_sec,
        args.min_break_excursion,
        args.reclaim_buffer_points,
        args.episode_merge_sec,
    )

    base = os.path.join(args.out_dir, f"tape_auction_{args.date}")
    txt_path = base + ".txt"
    csv_path = base + ".breaks.csv"
    write_break_csv(csv_path, [*audits, open_down_audit])

    gaps = data_gaps(rth_ticks, args.gap_sec)
    lines: list[str] = []
    lines.append(f"Tick-only auction probe for {args.date} {args.symbol_dir}")
    lines.append(f"RTH NY: {ny_label(rth_start, True)} to {ny_label(rth_end, True)}")
    lines.append(f"Ticks loaded: {rth_ticks.height:,}; source: trade tape only, no L2 snapshots")
    lines.append(f"Data gaps >= {args.gap_sec:.1f}s: {len(gaps)}")
    for prev_ts, ts, sec in gaps[:8]:
        lines.append(f"  {ny_label(prev_ts)} -> {ny_label(ts)} gap={sec:.1f}s")
    if len(gaps) > 8:
        lines.append(f"  ... {len(gaps) - 8} more")
    lines.append("")
    lines.append(f"RTH : {fmt_summary(rth)}")
    lines.append(f"OR{args.or_min:<2}: {fmt_summary(or5)} range={or5.high - or5.low:.2f}")
    lines.append(f"IB  : {fmt_summary(ib)} range={ib.high - ib.low:.2f}")
    lines.append("")
    lines.extend(preopen_shelf_lines(preopen_ticks, args.shelf_bin_points))
    lines.append("")
    lines.append("Break/reclaim audits")
    lines.append("scope      dir  level      cross    reclaim  label         moved outside  vol    delta aligned bins c5      c15     c30 attempts")
    for audit in audits:
        lines.append(fmt_audit(audit))
    lines.append("")
    lines.append("Early decision diagnostics")
    lines.extend(
        break_progress_lines(
            ticks,
            audits[0],
            args.shelf_bin_points,
            args.min_shelf_vol,
            args.min_shelf_sec,
            args.cap_points,
        )
    )
    lines.append("")
    lines.append("10:00 downside test diagnostics")
    lines.append(fmt_audit(open_down_audit))
    lines.extend(
        break_progress_lines(
            ticks,
            open_down_audit,
            args.shelf_bin_points,
            args.min_shelf_vol,
            args.min_shelf_sec,
            args.cap_points,
            windows=[15, 30, 60, 90, 120, 180, 240, 300, 600, 900],
        )
    )
    lines.append("")
    lines.extend(
        break_progress_lines(
            ticks,
            audits[1],
            args.shelf_bin_points,
            args.min_shelf_vol,
            args.min_shelf_sec,
            args.cap_points,
            windows=[15, 30, 60, 90, 120, 180, 240, 300, 600, 900],
        )
    )
    lines.extend(lower_followup_lines(ticks, audits[1], rth.open, or5.low))
    lines.append("")
    lines.append(f"Opening sequence: {args.or_min}m OR, 5m bars through IB")
    lines.append("time          O        H        L        C       vol    delta    vwap    vpoc")
    cum_start = rth_start
    for ts, summary in bar_rows(ticks, rth_start, ib_end, 5):
        cum = summarize(filter_window(ticks, cum_start, ts + dt.timedelta(minutes=5)))
        lines.append(
            f"{ny_label(ts):<8} {summary.open:8.2f} {summary.high:8.2f} {summary.low:8.2f} "
            f"{summary.close:8.2f} {summary.vol:8.0f} {summary.delta:+8.0f} "
            f"{cum.vwap:8.2f} {cum.vpoc:8.2f}"
        )
    lines.append("")
    for audit in audits:
        outside_ticks = audit_outside_ticks(ticks, audit)
        add_shelf_lines(
            lines,
            f"{audit.scope} {audit.direction} outside-business bins",
            outside_ticks,
            args.shelf_bin_points,
            args.min_shelf_vol,
            args.min_shelf_sec,
        )
    lines.append("")
    lines.append("Time-of-day watch windows")
    for line in watch_window_lines(
        ticks,
        rth_start,
        ny_dt(rth_day, "11:15"),
        ny_dt(rth_day, "12:45"),
        "late-morning",
    ):
        lines.append(line)
    for line in watch_window_lines(
        ticks,
        rth_start,
        ny_dt(rth_day, "12:45"),
        ny_dt(rth_day, "14:15"),
        "lunch-ext",
    ):
        lines.append(line)
    for line in watch_window_lines(
        ticks,
        rth_start,
        ny_dt(rth_day, "14:15"),
        ny_dt(rth_day, "15:00"),
        "PM-watch",
    ):
        lines.append(line)
    lines.append("")
    lines.append("30-minute tape profile")
    lines.append("time          O        H        L        C       vol    delta    vwap    vpoc")
    for ts, summary in bar_rows(ticks, rth_start, rth_end, 30):
        lines.append(
            f"{ny_label(ts):<8} {summary.open:8.2f} {summary.high:8.2f} {summary.low:8.2f} "
            f"{summary.close:8.2f} {summary.vol:8.0f} {summary.delta:+8.0f} "
            f"{summary.vwap:8.2f} {summary.vpoc:8.2f}"
        )
    lines.append("")
    lines.append(f"break_csv={csv_path}")

    text = "\n".join(lines)
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write(text + "\n")
    print(text)
    print(f"\nwritten: {txt_path}")


if __name__ == "__main__":
    main()
