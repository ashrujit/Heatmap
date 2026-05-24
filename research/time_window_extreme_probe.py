"""Tick-only probe for late-morning/lunch extreme quality.

This is the Q6/Q7 companion to the break and retracement-zone probes. It asks:
when a watched time window makes or retests a RTH extreme, is the extreme being
accepted, locally exhausted, or repaired into a new shelf?

It deliberately avoids L2 and avoids calling a reversal. The useful artifact is
the sequence: extreme -> reaction -> next shelf.
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

from capture_loader import add_ny_ts, load_capture_window
from retracement_zone_probe import build_zones, profile


try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


NY = ZoneInfo("America/New_York")
TICK_SIZE = 0.25
OUT_DIR = os.path.join(os.path.dirname(__file__), "out")


@dataclass(frozen=True)
class TapeSummary:
    open: float
    high: float
    low: float
    close: float
    vol: float
    delta: float
    trades: int
    vwap: float


@dataclass(frozen=True)
class Candidate:
    side: str
    kind: str
    level: float
    extreme: float
    ts: dt.datetime


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--date", required=True)
    p.add_argument("--symbol-dir", default="NQM6")
    p.add_argument("--rth-start", default="09:30")
    p.add_argument("--rth-end", default="16:00")
    p.add_argument(
        "--windows",
        nargs="*",
        default=["11:15-12:15", "12:15-13:15"],
        help="NY watch windows to inspect",
    )
    p.add_argument("--lookback-min", type=int, default=45)
    p.add_argument("--post-minutes", default="5,15,30")
    p.add_argument("--cap-points", type=float, default=8.0)
    p.add_argument("--test-points", type=float, default=8.0)
    p.add_argument("--bin-points", type=float, default=4.0)
    p.add_argument("--min-zone-vol", type=float, default=1200.0)
    p.add_argument("--min-zone-sec", type=int, default=35)
    p.add_argument("--top-zones", type=int, default=3)
    p.add_argument("--out-dir", default=OUT_DIR)
    return p.parse_args()


def ny_dt(day: dt.date, hhmm: str) -> dt.datetime:
    hour, minute = [int(x) for x in hhmm.split(":", 1)]
    return dt.datetime(day.year, day.month, day.day, hour, minute, tzinfo=NY)


def parse_window(day: dt.date, text: str) -> tuple[dt.datetime, dt.datetime]:
    start_s, end_s = text.split("-", 1)
    return ny_dt(day, start_s), ny_dt(day, end_s)


def ny_label(ts: dt.datetime | None) -> str:
    return "-" if ts is None else ts.astimezone(NY).strftime("%H:%M:%S")


def safe_float(value: object) -> float:
    try:
        return float(value)
    except Exception:
        return math.nan


def filter_window(ticks: pl.DataFrame, start: dt.datetime, end: dt.datetime) -> pl.DataFrame:
    return ticks.filter((pl.col("ts") >= start) & (pl.col("ts") < end))


def summarize(ticks: pl.DataFrame) -> TapeSummary:
    if ticks.height == 0:
        return TapeSummary(math.nan, math.nan, math.nan, math.nan, 0.0, 0.0, 0, math.nan)
    row = ticks.select(
        pl.col("price").first().alias("open"),
        pl.col("price").max().alias("high"),
        pl.col("price").min().alias("low"),
        pl.col("price").last().alias("close"),
        pl.col("size").sum().alias("vol"),
        (pl.col("size") * pl.col("aggressor_sign")).sum().alias("delta"),
        (pl.col("price") * pl.col("size")).sum().alias("pv"),
        pl.len().alias("trades"),
    ).row(0, named=True)
    vol = safe_float(row["vol"])
    return TapeSummary(
        open=safe_float(row["open"]),
        high=safe_float(row["high"]),
        low=safe_float(row["low"]),
        close=safe_float(row["close"]),
        vol=vol,
        delta=safe_float(row["delta"]),
        trades=int(row["trades"]),
        vwap=safe_float(row["pv"]) / vol if vol > 0 else math.nan,
    )


def first_ts_at_price(ticks: pl.DataFrame, price: float) -> dt.datetime | None:
    rows = ticks.filter(pl.col("price") == price)
    if rows.height == 0:
        return None
    return rows.row(0, named=True)["ts"]


def fmt_price(value: float) -> str:
    return "-" if not math.isfinite(value) else f"{value:.2f}"


def fmt_summary(s: TapeSummary) -> str:
    return (
        f"O={fmt_price(s.open)} H={fmt_price(s.high)} L={fmt_price(s.low)} "
        f"C={fmt_price(s.close)} vol={s.vol:.0f} delta={s.delta:+.0f} "
        f"vwap={fmt_price(s.vwap)}"
    )


def between_price(ticks: pl.DataFrame, lo: float, hi: float) -> pl.DataFrame:
    return ticks.filter((pl.col("price") >= lo) & (pl.col("price") <= hi))


def cap_band(side: str, extreme: float, cap_points: float) -> tuple[float, float]:
    if side == "HIGH":
        return extreme - cap_points, extreme
    return extreme, extreme + cap_points


def move_toward_extreme(side: str, s: TapeSummary, extreme: float) -> float:
    if side == "HIGH":
        return max(0.0, s.high - extreme)
    return max(0.0, extreme - s.low)


def retrace_from_extreme(side: str, s: TapeSummary, extreme: float) -> float:
    if side == "HIGH":
        return max(0.0, extreme - s.low)
    return max(0.0, s.high - extreme)


def close_toward_extreme(side: str, s: TapeSummary) -> float:
    span = max(TICK_SIZE, s.high - s.low)
    if side == "HIGH":
        return max(0.0, min(1.0, (s.close - s.low) / span))
    return max(0.0, min(1.0, (s.high - s.close) / span))


def aligned_delta(side: str, delta: float) -> float:
    return delta if side == "HIGH" else -delta


def side_word(side: str) -> str:
    return "up" if side == "HIGH" else "down"


def find_candidates(
    win: pl.DataFrame,
    prior: pl.DataFrame,
    test_points: float,
) -> list[Candidate]:
    out: list[Candidate] = []
    if win.height == 0 or prior.height == 0:
        return out
    ws = summarize(win)
    ps = summarize(prior)

    if ws.high > ps.high:
        ts = first_ts_at_price(win, ws.high)
        if ts is not None:
            out.append(Candidate("HIGH", "new_rth_high", ps.high, ws.high, ts))
    elif ws.high >= ps.high - test_points:
        ts = first_ts_at_price(win, ws.high)
        if ts is not None:
            out.append(Candidate("HIGH", "test_rth_high", ps.high, ws.high, ts))

    if ws.low < ps.low:
        ts = first_ts_at_price(win, ws.low)
        if ts is not None:
            out.append(Candidate("LOW", "new_rth_low", ps.low, ws.low, ts))
    elif ws.low <= ps.low + test_points:
        ts = first_ts_at_price(win, ws.low)
        if ts is not None:
            out.append(Candidate("LOW", "test_rth_low", ps.low, ws.low, ts))

    return sorted(out, key=lambda c: c.ts)


def zone_lines(
    ticks: pl.DataFrame,
    side: str,
    extreme: float,
    cap_lo: float,
    cap_hi: float,
    bin_points: float,
    min_zone_vol: float,
    min_zone_sec: int,
    top: int,
) -> list[str]:
    rows = profile(ticks, bin_points)
    zones = build_zones(rows, bin_points, 2, min_zone_vol, min_zone_sec)
    if side == "HIGH":
        repair = [z for z in zones if z.hi < cap_lo]
        cap = [z for z in zones if z.hi >= cap_lo and z.lo <= cap_hi]
    else:
        repair = [z for z in zones if z.lo > cap_hi]
        cap = [z for z in zones if z.hi >= cap_lo and z.lo <= cap_hi]

    lines: list[str] = []
    if cap:
        lines.append("    cap zones: " + "; ".join(format_zone(z) for z in cap[:top]))
    if repair:
        lines.append("    repair shelves: " + "; ".join(format_zone(z) for z in repair[:top]))
    return lines


def format_zone(z: object) -> str:
    return (
        f"{z.lo:.2f}-{z.hi:.2f} vol={z.vol:.0f} "
        f"delta={z.delta:+.0f} secs={z.secs}"
    )


def reaction_tag(
    side: str,
    approach_move: float,
    post_s: TapeSummary,
    extreme: float,
    cap_share: float,
    cap_aligned_ratio: float,
    cap_zone_count: int,
) -> str:
    retrace = retrace_from_extreme(side, post_s, extreme)
    extend = move_toward_extreme(side, post_s, extreme)
    close_extreme = close_toward_extreme(side, post_s)
    meaningful_retrace = max(16.0, approach_move * 0.30)

    if retrace >= meaningful_retrace and close_extreme <= 0.35 and cap_share <= 0.30:
        return "rejecting-extreme"
    if retrace >= meaningful_retrace and close_extreme <= 0.45 and cap_aligned_ratio <= 0.12:
        return "exhaustion-risk"
    if cap_share >= 0.40 and close_extreme >= 0.60 and cap_zone_count > 0:
        return "accepting-extreme"
    if extend >= 8.0 and close_extreme >= 0.55:
        return "continuing"
    return "contested"


def analyze_candidate(
    ticks: pl.DataFrame,
    rth_start: dt.datetime,
    rth_end: dt.datetime,
    c: Candidate,
    lookback_min: int,
    post_minutes: list[int],
    cap_points: float,
    bin_points: float,
    min_zone_vol: float,
    min_zone_sec: int,
    top_zones: int,
) -> list[str]:
    cap_lo, cap_hi = cap_band(c.side, c.extreme, cap_points)
    lookback_start = max(rth_start, c.ts - dt.timedelta(minutes=lookback_min))
    approach = filter_window(ticks, lookback_start, c.ts + dt.timedelta(microseconds=1))
    approach_s = summarize(approach)
    cap_approach = between_price(approach, cap_lo, cap_hi)
    cap_approach_s = summarize(cap_approach)
    approach_move = (
        max(0.0, c.extreme - approach_s.open)
        if c.side == "HIGH"
        else max(0.0, approach_s.open - c.extreme)
    )
    cap_share = cap_approach_s.vol / max(1.0, approach_s.vol)
    cap_aligned_ratio = aligned_delta(c.side, cap_approach_s.delta) / max(1.0, cap_approach_s.vol)
    extension = abs(c.extreme - c.level)

    lines = [
        (
            f"  {c.kind} {side_word(c.side)} level={c.level:.2f} extreme={c.extreme:.2f} "
            f"at {ny_label(c.ts)} extension={extension:.2f}"
        ),
        (
            f"    approach {ny_label(lookback_start)}-{ny_label(c.ts)} move={approach_move:.2f} "
            f"vol={approach_s.vol:.0f} delta={approach_s.delta:+.0f} "
            f"cap{cap_points:.0f}={cap_lo:.2f}-{cap_hi:.2f} "
            f"cap_vol={cap_approach_s.vol:.0f} share={cap_share:.0%} "
            f"cap_delta={cap_approach_s.delta:+.0f} aligned/vol={cap_aligned_ratio:+.2f}"
        ),
    ]

    max_post = max(post_minutes)
    post_all = filter_window(ticks, c.ts, min(rth_end, c.ts + dt.timedelta(minutes=max_post)))
    cap_rows = profile(between_price(post_all, cap_lo, cap_hi), bin_points)
    cap_zones = build_zones(cap_rows, bin_points, 2, min_zone_vol, min_zone_sec)

    lines.append("    post reaction")
    lines.append("      end       retrace extend close_ext cap_share vol    delta   tag")
    for minute in post_minutes:
        post = filter_window(ticks, c.ts, min(rth_end, c.ts + dt.timedelta(minutes=minute)))
        post_s = summarize(post)
        post_cap_s = summarize(between_price(post, cap_lo, cap_hi))
        post_cap_share = post_cap_s.vol / max(1.0, post_s.vol)
        cap_ratio = aligned_delta(c.side, post_cap_s.delta) / max(1.0, post_cap_s.vol)
        tag = reaction_tag(
            c.side,
            approach_move,
            post_s,
            c.extreme,
            post_cap_share,
            cap_ratio,
            len(cap_zones),
        )
        lines.append(
            f"      +{minute:<2d}m {retrace_from_extreme(c.side, post_s, c.extreme):7.2f} "
            f"{move_toward_extreme(c.side, post_s, c.extreme):6.2f} "
            f"{close_toward_extreme(c.side, post_s):8.2f} "
            f"{post_cap_share:8.0%} {post_s.vol:6.0f} {post_s.delta:+8.0f} {tag}"
        )

    lines.extend(
        zone_lines(
            post_all,
            c.side,
            c.extreme,
            cap_lo,
            cap_hi,
            bin_points,
            min_zone_vol,
            min_zone_sec,
            top_zones,
        )
    )
    return lines


def main() -> None:
    args = parse_args()
    os.makedirs(args.out_dir, exist_ok=True)
    day = dt.date.fromisoformat(args.date)
    rth_start = ny_dt(day, args.rth_start)
    rth_end = ny_dt(day, args.rth_end)
    post_minutes = [int(x) for x in args.post_minutes.split(",") if x.strip()]

    ticks = add_ny_ts(load_capture_window("ticks", args.symbol_dir, rth_start, rth_end))
    rth = summarize(ticks)

    lines: list[str] = []
    lines.append(f"Time-window extreme probe {args.date} {args.symbol_dir}")
    lines.append("source: trade tape only, no L2 snapshots")
    lines.append(f"RTH {ny_label(rth_start)}-{ny_label(rth_end)} ticks={ticks.height:,} {fmt_summary(rth)}")
    lines.append("")

    for text in args.windows:
        start, end = parse_window(day, text)
        prior = filter_window(ticks, rth_start, start)
        win = filter_window(ticks, start, end)
        ps = summarize(prior)
        ws = summarize(win)
        lines.append(f"Window {text}")
        lines.append(f"  prior {fmt_summary(ps)}")
        lines.append(f"  watch {fmt_summary(ws)}")
        candidates = find_candidates(win, prior, args.test_points)
        if not candidates:
            lines.append("  no RTH extreme test in this window")
        for c in candidates:
            lines.extend(
                analyze_candidate(
                    ticks,
                    rth_start,
                    rth_end,
                    c,
                    args.lookback_min,
                    post_minutes,
                    args.cap_points,
                    args.bin_points,
                    args.min_zone_vol,
                    args.min_zone_sec,
                    args.top_zones,
                )
            )
        lines.append("")

    out_path = os.path.join(args.out_dir, f"time_window_extremes_{args.date}.txt")
    text = "\n".join(lines)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(text + "\n")
    print(text)
    print(f"written: {out_path}")


if __name__ == "__main__":
    main()
