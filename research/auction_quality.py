"""Auction-quality replay harness for ON rails and IB leg acceptance.

This is research code, not indicator code. It asks a narrower question than
LevelLedger: after prepared ON rails are touched or broken, did the resulting
move build accepted business behind it, or did it traverse thin/contested space?
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import math
import os
import sys
from dataclasses import dataclass
from zoneinfo import ZoneInfo

import polars as pl

from eth_on_context import (
    OUT_DIR,
    TICK_SIZE,
    Zone,
    add_ny_ts,
    build_snapshot_metrics,
    compute_zones,
    detect_events,
    events_in,
    load_window,
    ny_dt,
    ny_label,
    profile_summary,
    rth_bars,
)


try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


NY = ZoneInfo("America/New_York")
BIN_POINTS = 4.0
RAIL_BREAK_BUFFER = 1.0
CAP_BAND_POINTS = 8.0


@dataclass(frozen=True)
class Rail:
    side: str
    lo: float
    hi: float
    center: float
    score: float
    dominant: float
    opposing: float
    ratio: float
    last: dt.datetime | None
    source: str


@dataclass
class Signal:
    ts: dt.datetime
    kind: str
    frame: str
    text: str
    details: dict[str, str | float | int]


@dataclass
class LegState:
    direction: str
    rail: Rail
    start_ts: dt.datetime
    extreme: float
    extreme_ts: dt.datetime
    emitted_quality: bool = False
    emitted_building: bool = False
    emitted_accepted: bool = False


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--date", required=True, help="RTH date, e.g. 2026-05-21")
    p.add_argument("--symbol-dir", default="NQM6")
    p.add_argument("--eth-start", default="18:00")
    p.add_argument("--preopen-start", default="08:00")
    p.add_argument("--rth-start", default="09:30")
    p.add_argument("--analysis-end", default="12:30")
    p.add_argument("--out-dir", default=OUT_DIR)
    return p.parse_args()


def to_rail(z: Zone) -> Rail:
    return Rail(
        side=z.side,
        lo=z.lo,
        hi=z.hi,
        center=z.center,
        score=z.score,
        dominant=z.dominant,
        opposing=z.opposing,
        ratio=z.ratio,
        last=z.last,
        source=z.scope,
    )


def freshness(z: Rail, rth_start: dt.datetime) -> str:
    if z.last is None:
        return "unknown"
    age_min = (rth_start - z.last).total_seconds() / 60.0
    if age_min <= 90:
        return "fresh"
    return "old"


def select_bracket_rails(
    preopen_zones: list[Zone],
    rth_open: float,
    opening_low: float,
    opening_high: float,
) -> tuple[Rail | None, Rail | None]:
    demands = [to_rail(z) for z in preopen_zones if z.side == "DEMAND"]
    supplies = [to_rail(z) for z in preopen_zones if z.side == "SUPPLY"]

    lower_candidates = [
        z
        for z in demands
        if opening_low - 24.0 <= z.center <= max(opening_high + 8.0, rth_open + 32.0)
    ]
    if not lower_candidates:
        lower_candidates = [z for z in demands if z.center <= rth_open + 16.0]
    lower = None
    if lower_candidates:
        lower = sorted(
            lower_candidates,
            key=lambda z: (
                z.center <= rth_open + 12.0,
                z.score / max(1.0, 1.0 + abs(z.center - rth_open) / 32.0),
            ),
            reverse=True,
        )[0]

    upper_candidates = [
        z
        for z in supplies
        if min(opening_low - 8.0, rth_open - 32.0) <= z.center <= opening_high + 16.0
    ]
    if not upper_candidates:
        upper_candidates = [z for z in supplies if z.center >= rth_open - 16.0]
    upper = None
    if upper_candidates:
        touched = [z for z in upper_candidates if z.center <= opening_high + 8.0]
        bucket = touched if touched else upper_candidates
        upper = sorted(bucket, key=lambda z: (z.center, z.score), reverse=True)[0]

    return lower, upper


def fmt_rail(z: Rail | None, rth_start: dt.datetime) -> str:
    if z is None:
        return "-"
    side = "D" if z.side == "DEMAND" else "S"
    return (
        f"{z.lo:.0f}-{z.hi:.0f} {side} c={z.center:.0f} "
        f"{freshness(z, rth_start)} score={z.score:.0f}"
    )


def filter_ticks(
    ticks: pl.DataFrame,
    start: dt.datetime,
    end: dt.datetime,
    lo: float | None = None,
    hi: float | None = None,
) -> pl.DataFrame:
    out = ticks.filter((pl.col("ts") >= start) & (pl.col("ts") < end))
    if lo is not None:
        out = out.filter(pl.col("price") >= lo)
    if hi is not None:
        out = out.filter(pl.col("price") <= hi)
    return out


def bin_profile(
    ticks: pl.DataFrame,
    start: dt.datetime,
    end: dt.datetime,
    lo: float,
    hi: float,
) -> list[dict]:
    sub = filter_ticks(ticks, start, end, lo, hi)
    if sub.height == 0:
        return []
    prof = (
        sub.with_columns(
            ((pl.col("price") / BIN_POINTS).floor() * BIN_POINTS).alias("bin"),
            ((pl.col("timestamp_us") / 1_000_000).floor().cast(pl.Int64)).alias("sec"),
        )
        .group_by("bin")
        .agg(
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
            pl.col("sec").n_unique().alias("seconds"),
            pl.col("price").min().alias("lo"),
            pl.col("price").max().alias("hi"),
        )
        .sort("bin")
    )
    return list(prof.iter_rows(named=True))


def event_sums(events, start: dt.datetime, end: dt.datetime, lo: float, hi: float) -> tuple[float, float, int, int]:
    local = [ev for ev in events if start <= ev.ts < end and lo <= ev.price <= hi]
    demand = sum(ev.abs_z for ev in local if ev.bias > 0)
    supply = sum(ev.abs_z for ev in local if ev.bias < 0)
    d_count = sum(1 for ev in local if ev.bias > 0)
    s_count = sum(1 for ev in local if ev.bias < 0)
    return demand, supply, d_count, s_count


def quality_label(
    direction: str,
    rail: Rail,
    start: dt.datetime,
    end: dt.datetime,
    extreme: float,
    close: float,
    ticks: pl.DataFrame,
    events,
) -> dict[str, str | float | int]:
    if direction == "UP":
        ext_lo = rail.hi
        ext_hi = max(extreme, rail.hi + BIN_POINTS)
        anchor_lo = rail.lo - 16.0
        anchor_hi = rail.hi
        top_lo = max(ext_lo, extreme - CAP_BAND_POINTS)
        top_hi = extreme + 0.25
        same, opp, same_n, opp_n = event_sums(events, start, end, ext_lo, ext_hi)
        cap_same, cap_opp, cap_same_n, cap_opp_n = event_sums(events, start, end, top_lo, top_hi)
        cap_strength = cap_opp
        retraced = close <= rail.hi + 2.0
        moved = max(0.0, extreme - rail.hi)
    else:
        ext_lo = min(extreme, rail.lo - BIN_POINTS)
        ext_hi = rail.lo
        anchor_lo = rail.lo
        anchor_hi = rail.hi + 16.0
        top_lo = extreme - 0.25
        top_hi = min(ext_hi, extreme + CAP_BAND_POINTS)
        demand, supply, d_n, s_n = event_sums(events, start, end, ext_lo, ext_hi)
        same, opp, same_n, opp_n = supply, demand, s_n, d_n
        floor_demand, floor_supply, floor_d_n, floor_s_n = event_sums(events, start, end, top_lo, top_hi)
        cap_same, cap_opp, cap_same_n, cap_opp_n = floor_supply, floor_demand, floor_s_n, floor_d_n
        cap_strength = cap_opp
        retraced = close >= rail.lo - 2.0
        moved = max(0.0, rail.lo - extreme)

    ext_bins = bin_profile(ticks, start, end, ext_lo, ext_hi)
    anchor_bins = bin_profile(ticks, start, end, anchor_lo, anchor_hi)
    anchor_avg = sum(float(b["vol"]) for b in anchor_bins) / max(1, len(anchor_bins))
    if anchor_avg <= 0 and ext_bins:
        anchor_avg = sum(float(b["vol"]) for b in ext_bins) / max(1, len(ext_bins))

    accepted_threshold = max(450.0, anchor_avg * 0.65)
    air_threshold = max(175.0, anchor_avg * 0.28)
    accepted_bins = sum(1 for b in ext_bins if float(b["vol"]) >= accepted_threshold and int(b["seconds"]) >= 20)
    air_bins = sum(1 for b in ext_bins if float(b["vol"]) <= air_threshold or int(b["seconds"]) < 8)
    bin_count = len(ext_bins)
    air_ratio = air_bins / max(1, bin_count)
    duration_min = max(0.1, (end - start).total_seconds() / 60.0)
    speed = moved / duration_min
    same_ratio = same / max(1.0, opp)
    max_gap_sec = 0.0
    sub_ticks = filter_ticks(ticks, start, end, ext_lo, ext_hi)
    prev_ts = None
    for ts_us in sub_ticks["timestamp_us"].to_list():
        if prev_ts is not None:
            max_gap_sec = max(max_gap_sec, (ts_us - prev_ts) / 1_000_000.0)
        prev_ts = ts_us
    if direction == "UP":
        retrace_fraction = (extreme - close) / max(1.0, moved)
    else:
        retrace_fraction = (close - extreme) / max(1.0, moved)
    retrace_fraction = max(0.0, min(2.0, retrace_fraction))

    label = "probing"
    if moved >= 12.0 and cap_strength >= 7.0 and (same_ratio < 1.25 or retraced):
        label = "thin/capped"
    elif moved >= 16.0 and (accepted_bins <= 1 or air_ratio >= 0.45) and same_ratio < 1.35:
        label = "thin/mixed"
    elif accepted_bins >= 3 and (same_ratio >= 1.15 or cap_strength < 8.0) and not retraced:
        label = "building"
    if (
        accepted_bins >= 6
        and not retraced
        and retrace_fraction <= 0.45
        and max_gap_sec <= 90.0
        and duration_min >= 12.0
        and moved >= 24.0
    ):
        label = "accepted"
    if moved >= 24.0 and retrace_fraction >= 0.60:
        label = "fast/no-build"
    elif max_gap_sec > 90.0 and label in ("building", "accepted"):
        label = "gap/unknown"
    elif speed >= 18.0 and accepted_bins <= 1:
        label = "fast/no-build"

    return {
        "label": label,
        "moved": round(moved, 1),
        "speed": round(speed, 1),
        "max_gap_sec": round(max_gap_sec, 1),
        "retrace": round(retrace_fraction, 2),
        "bins": bin_count,
        "accepted_bins": accepted_bins,
        "air_bins": air_bins,
        "air_ratio": round(air_ratio, 2),
        "same_z": round(same, 1),
        "opp_z": round(opp, 1),
        "same_events": same_n,
        "opp_events": opp_n,
        "cap_opp_z": round(cap_strength, 1),
        "cap_opp_events": cap_opp_n,
        "anchor_avg_vol": round(anchor_avg, 1),
    }


def add_signal(
    signals: list[Signal],
    ts: dt.datetime,
    kind: str,
    frame: str,
    text: str,
    **details: str | float | int,
) -> None:
    signals.append(Signal(ts=ts, kind=kind, frame=frame, text=text, details=details))


def detect_data_gaps(ticks: pl.DataFrame, start: dt.datetime, end: dt.datetime) -> list[tuple[dt.datetime, dt.datetime, float]]:
    sub = filter_ticks(ticks, start, end)
    if sub.height < 2:
        return []
    gaps: list[tuple[dt.datetime, dt.datetime, float]] = []
    prev = None
    for ts_us in sub["timestamp_us"].to_list():
        if prev is not None:
            gap = (ts_us - prev) / 1_000_000.0
            if gap >= 30.0:
                gaps.append((
                    dt.datetime.fromtimestamp(prev / 1_000_000.0, tz=NY),
                    dt.datetime.fromtimestamp(ts_us / 1_000_000.0, tz=NY),
                    gap,
                ))
        prev = ts_us
    return gaps


def run_state_machine(
    rth_ticks: pl.DataFrame,
    rth_events,
    low_rail: Rail | None,
    high_rail: Rail | None,
    rth_open: float,
    rth_start: dt.datetime,
    eval_start: dt.datetime,
    analysis_end: dt.datetime,
) -> tuple[list[Signal], pl.DataFrame]:
    signals: list[Signal] = []
    if low_rail is None or high_rail is None:
        add_signal(signals, rth_start, "NO_BRACKET", "unknown", "Could not select both opening rails")
        return signals, pl.DataFrame()

    bars = rth_bars(rth_ticks.filter(pl.col("ts") < analysis_end))
    active: LegState | None = None
    failed_upper = False
    failed_lower = False
    frame = "building IB"
    add_risk_sent = False

    cum_vol = 0.0
    cum_pv = 0.0
    bar_rows = []

    for row in bars.iter_rows(named=True):
        ts = row["ts"]
        end_ts = ts + dt.timedelta(minutes=5)
        if ts < rth_start:
            continue
        open_p = float(row["open"])
        high_p = float(row["high"])
        low_p = float(row["low"])
        close_p = float(row["close"])
        vol = float(row["vol"])
        delta = float(row["delta"])
        sub = filter_ticks(rth_ticks, ts, end_ts)
        if sub.height:
            pv = float((sub["price"] * sub["size"]).sum())
            cum_vol += vol
            cum_pv += pv
        vwap = cum_pv / cum_vol if cum_vol > 0 else math.nan
        bar_rows.append({**row, "vwap": vwap})

        if ts < eval_start:
            continue

        broke_up = high_p > high_rail.hi + RAIL_BREAK_BUFFER
        broke_down = low_p < low_rail.lo - RAIL_BREAK_BUFFER
        if active is None:
            if broke_up and broke_down:
                add_signal(
                    signals,
                    ts,
                    "TWO_SIDE_SWEEP",
                    frame,
                    (
                        f"Both opening rails swept in one 5m bar; "
                        f"low {low_p:.2f} below {low_rail.center:.0f}D, "
                        f"high {high_p:.2f} above {high_rail.center:.0f}S"
                    ),
                    low=low_p,
                    high=high_p,
                )
            if broke_up and close_p >= high_rail.hi:
                active = LegState("UP", high_rail, ts, high_p, ts)
                add_signal(
                    signals,
                    ts,
                    "UP_BREAK",
                    frame,
                    f"Resolved above high rail {high_rail.center:.0f}S; quality not proven",
                    rail=high_rail.center,
                    high=high_p,
                    close=close_p,
                )
            elif broke_down and close_p <= low_rail.lo:
                active = LegState("DOWN", low_rail, ts, low_p, ts)
                add_signal(
                    signals,
                    ts,
                    "DOWN_BREAK",
                    frame,
                    f"Resolved below low rail {low_rail.center:.0f}D; quality not proven",
                    rail=low_rail.center,
                    low=low_p,
                    close=close_p,
                )

        if active is not None:
            if active.direction == "UP" and high_p > active.extreme:
                active.extreme = high_p
                active.extreme_ts = ts
            elif active.direction == "DOWN" and low_p < active.extreme:
                active.extreme = low_p
                active.extreme_ts = ts

            q = quality_label(
                active.direction,
                active.rail,
                active.start_ts,
                end_ts,
                active.extreme,
                close_p,
                rth_ticks,
                rth_events,
            )
            label = str(q["label"])
            if label in ("thin/capped", "thin/mixed", "fast/no-build") and not active.emitted_quality:
                add_signal(
                    signals,
                    ts,
                    f"{active.direction}_QUALITY",
                    frame,
                    (
                        f"{active.direction} leg {active.rail.center:.0f}->{active.extreme:.0f} "
                        f"is {label}; resolved is not accepted"
                    ),
                    **q,
                )
                active.emitted_quality = True
            elif label == "building" and not active.emitted_building:
                add_signal(
                    signals,
                    ts,
                    f"{active.direction}_QUALITY",
                    frame,
                    (
                        f"{active.direction} leg {active.rail.center:.0f}->{active.extreme:.0f} "
                        f"is {label}; business is forming beyond rail"
                    ),
                    **q,
                )
                active.emitted_building = True
            elif label == "accepted" and not active.emitted_accepted:
                add_signal(
                    signals,
                    ts,
                    f"{active.direction}_QUALITY",
                    frame,
                    (
                        f"{active.direction} leg {active.rail.center:.0f}->{active.extreme:.0f} "
                        f"is accepted; business is now proven beyond rail"
                    ),
                    **q,
                )
                active.emitted_accepted = True
                frame = "accepting higher" if active.direction == "UP" else "accepting lower"
                add_signal(
                    signals,
                    ts,
                    "FRAME",
                    frame,
                    f"{active.direction} leg has accepted business beyond the prepared rail",
                    **q,
                )

            if active.direction == "UP" and close_p < high_rail.lo:
                add_signal(
                    signals,
                    ts,
                    "UP_FAILED",
                    frame,
                    f"Returned back through high rail after {active.extreme:.2f}; upper acceptance failed",
                    extreme=active.extreme,
                    close=close_p,
                )
                failed_upper = True
                if broke_down:
                    active = LegState("DOWN", low_rail, ts, low_p, ts)
                    add_signal(
                        signals,
                        ts,
                        "DOWN_LEG",
                        frame,
                        "Counter-auction lower started after upper failure",
                        low=low_p,
                        close=close_p,
                    )
                else:
                    active = None
            elif active.direction == "DOWN" and close_p > low_rail.hi:
                add_signal(
                    signals,
                    ts,
                    "DOWN_FAILED",
                    frame,
                    f"Reclaimed low rail after {active.extreme:.2f}; lower acceptance failed",
                    extreme=active.extreme,
                    close=close_p,
                )
                failed_lower = True
                active = None

        if (
            ts >= rth_start + dt.timedelta(minutes=60)
            and failed_upper
            and failed_lower
            and frame not in ("open auction", "accepting higher", "accepting lower")
        ):
            frame = "open auction"
            add_signal(
                signals,
                ts,
                "FRAME",
                frame,
                "Both upper and lower extensions failed acceptance; frame is open auction/two-sided",
                open=rth_open,
                vwap=round(vwap, 2),
            )

        if frame == "open auction" and not add_risk_sent and ts >= rth_start + dt.timedelta(minutes=60):
            if high_p > high_rail.hi + 8.0 and close_p > rth_open:
                add_signal(
                    signals,
                    ts,
                    "ADD_RISK",
                    frame,
                    "Price is in upper extension of open auction; adds need fresh accepted pullback, not chase",
                    high=high_p,
                    close=close_p,
                    vwap=round(vwap, 2),
                )
                add_risk_sent = True

    return signals, pl.DataFrame(bar_rows)


def write_signals_csv(path: str, signals: list[Signal]) -> None:
    keys = sorted({k for sig in signals for k in sig.details})
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["ny_time", "utc_time", "kind", "frame", "text", *keys])
        for sig in signals:
            writer.writerow(
                [
                    ny_label(sig.ts, with_date=True),
                    sig.ts.astimezone(dt.timezone.utc).isoformat(),
                    sig.kind,
                    sig.frame,
                    sig.text,
                    *[sig.details.get(k, "") for k in keys],
                ]
            )


def main() -> None:
    args = parse_args()
    os.makedirs(args.out_dir, exist_ok=True)
    rth_day = dt.date.fromisoformat(args.date)
    eth_start = ny_dt(rth_day - dt.timedelta(days=1), args.eth_start)
    preopen_start = ny_dt(rth_day, args.preopen_start)
    rth_start = ny_dt(rth_day, args.rth_start)
    analysis_end = ny_dt(rth_day, args.analysis_end)

    snap = load_window("snapshots", args.symbol_dir, eth_start, analysis_end)
    ticks = add_ny_ts(load_window("ticks", args.symbol_dir, eth_start, analysis_end))
    snap_metrics = build_snapshot_metrics(snap)
    all_events = detect_events(snap_metrics)

    preopen_ticks = ticks.filter((pl.col("ts") >= preopen_start) & (pl.col("ts") < rth_start))
    rth_ticks = ticks.filter((pl.col("ts") >= rth_start) & (pl.col("ts") < analysis_end))
    preopen_events = events_in(all_events, preopen_start, rth_start)
    rth_events = events_in(all_events, rth_start, analysis_end)
    preopen_zones = compute_zones("PREOPEN_0800", preopen_events, preopen_ticks, preopen_start, rth_start)

    opening_end = rth_start + dt.timedelta(minutes=15)
    opening_ticks = rth_ticks.filter(pl.col("ts") < opening_end)
    rth_summary = profile_summary(rth_ticks)
    opening_summary = profile_summary(opening_ticks)
    rth_open = float(opening_summary["open"])
    low_rail, high_rail = select_bracket_rails(
        preopen_zones,
        rth_open,
        float(opening_summary["low"]),
        float(opening_summary["high"]),
    )

    signals: list[Signal] = []
    add_signal(
        signals,
        rth_start - dt.timedelta(seconds=1),
        "PREP",
        "pre-open",
        f"Prepared rails from preopen book: LOW {fmt_rail(low_rail, rth_start)} | HIGH {fmt_rail(high_rail, rth_start)}",
        open=rth_open,
    )
    add_signal(
        signals,
        opening_end,
        "OPEN_BRACKET",
        "building IB",
        (
            f"First 15m validated bracket: LOW {fmt_rail(low_rail, rth_start)} | "
            f"HIGH {fmt_rail(high_rail, rth_start)}; "
            f"opening range {opening_summary['low']:.2f}-{opening_summary['high']:.2f}"
        ),
        open=rth_open,
        first15_low=round(float(opening_summary["low"]), 2),
        first15_high=round(float(opening_summary["high"]), 2),
    )

    for a, b, seconds in detect_data_gaps(rth_ticks, rth_start, analysis_end):
        add_signal(
            signals,
            b,
            "DATA_GAP",
            "data quality",
            f"No tick prints captured from {ny_label(a)} to {ny_label(b)} ({seconds:.0f}s)",
            seconds=round(seconds, 1),
        )

    sm_signals, bars = run_state_machine(
        rth_ticks,
        rth_events,
        low_rail,
        high_rail,
        rth_open,
        rth_start,
        opening_end,
        analysis_end,
    )
    signals.extend(sm_signals)
    signals.sort(key=lambda s: s.ts)

    base = os.path.join(args.out_dir, f"auction_quality_{args.date}")
    txt_path = base + ".txt"
    csv_path = base + ".signals.csv"
    write_signals_csv(csv_path, signals)

    lines: list[str] = []
    lines.append(f"Auction quality replay for {args.date} {args.symbol_dir}")
    lines.append(f"Window NY: {ny_label(eth_start, True)} to {ny_label(analysis_end, True)}")
    lines.append(f"Snapshots loaded: {snap.height:,}; ticks loaded: {ticks.height:,}; events: {len(all_events):,}")
    lines.append(
        f"RTH tape to {args.analysis_end}: O={rth_summary['open']:.2f} H={rth_summary['high']:.2f} "
        f"L={rth_summary['low']:.2f} C={rth_summary['close']:.2f} "
        f"vol={rth_summary['vol']:.0f} delta={rth_summary['delta']:+.0f}"
    )
    lines.append("")
    lines.append("Preopen zones used as candidates")
    lines.append("side   zone          center freshness score dom/opp")
    for z in [to_rail(z) for z in preopen_zones][:16]:
        side = "D" if z.side == "DEMAND" else "S"
        lines.append(
            f"{side:<4} {z.lo:7.2f}-{z.hi:<7.2f} {z.center:7.2f} "
            f"{freshness(z, rth_start):<9} {z.score:6.0f} {z.dominant:5.1f}/{z.opposing:<5.1f}"
        )
    lines.append("")
    lines.append("Live-style stream")
    for sig in signals:
        detail = ""
        if sig.details:
            compact = []
            for key in (
                "label",
                "moved",
                "speed",
                "retrace",
                "max_gap_sec",
                "accepted_bins",
                "bins",
                "same_z",
                "opp_z",
                "cap_opp_z",
                "vwap",
            ):
                if key in sig.details:
                    compact.append(f"{key}={sig.details[key]}")
            if compact:
                detail = " [" + " ".join(compact) + "]"
        lines.append(f"{ny_label(sig.ts):<8} {sig.kind:<14} {sig.frame:<13} {sig.text}{detail}")
    lines.append("")
    lines.append("5-minute RTH bars with replay VWAP")
    lines.append("time          O        H        L        C       vol    delta    vwap")
    if bars.height:
        for row in bars.iter_rows(named=True):
            lines.append(
                f"{ny_label(row['ts']):<8} {row['open']:8.2f} {row['high']:8.2f} {row['low']:8.2f} "
                f"{row['close']:8.2f} {row['vol']:8.0f} {row['delta']:+8.0f} {row['vwap']:8.2f}"
            )
    lines.append("")
    lines.append(f"signals_csv={csv_path}")

    text = "\n".join(lines)
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write(text + "\n")
    print(text)
    print(f"\nwritten: {txt_path}")


if __name__ == "__main__":
    main()
