"""Build a synthetic LL direct-conversion lifecycle dataset.

This is a broad research table, not an execution rule. It replays the existing
LevelLedger ownership probe from MarketRecorder snapshots, extracts every
`CONSUMED` transition as a synthetic direct-conversion event, and attaches
before/during/after features from LL transitions, snapshots, and tape.
"""

from __future__ import annotations

import argparse
import bisect
import csv
import math
import statistics
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterable

import polars as pl

from _paths import OUTPUT_ROOT, REPO_ROOT as ROOT

LL_RESEARCH = ROOT / "LevelLedger" / "research"
sys.path.insert(0, str(LL_RESEARCH))

from capture_loader import load_capture_window, tick_columns, us  # noqa: E402
from ownership_bands_probe import OwnershipProbe, Transition, opposite  # noqa: E402
from replay_levelledger import (  # noqa: E402
    BOOK_LOOKBACK_SEC,
    BROAD_LEVELS,
    EVENT_Z_THRESHOLD,
    NY,
    TICK_SIZE,
    build_sample,
    load_snapshots,
    parse_ny,
    snapshot_timing_summary,
)


HORIZONS = (120, 300, 600)
BOOK_WINDOWS = (2, 5, 10)


@dataclass
class ReplayData:
    date: str
    window_start: datetime
    window_end: datetime
    replay_start: datetime
    replay_end: datetime
    probe: OwnershipProbe
    snapshots: pl.DataFrame
    snapshot_rows: list[dict[str, Any]]
    snapshot_times: list[int]
    ticks: pl.DataFrame
    tick_times: list[int]
    tick_prices: list[float]
    tick_sizes: list[float]
    tick_signs: list[int]
    bands_by_id: dict[int, Any]
    gap_count: int
    duplicate_timestamps: int


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dates", required=True, help="Comma-separated ET dates, e.g. 2026-07-23,2026-07-24")
    parser.add_argument("--symbol-dir", default="NQU6")
    parser.add_argument("--window", default="09:30-16:00")
    parser.add_argument("--warmup-min", type=int, default=90)
    parser.add_argument("--lookahead-min", type=int, default=20)
    parser.add_argument(
        "--out-dir", default=str(OUTPUT_ROOT / "direct_conversion_lifecycle")
    )
    parser.add_argument("--event-z", type=float, default=EVENT_Z_THRESHOLD)
    parser.add_argument("--book-lookback-sec", type=int, default=BOOK_LOOKBACK_SEC)
    parser.add_argument("--cluster-min-events", type=int, default=3)
    parser.add_argument("--cluster-ticks", type=int, default=10)
    parser.add_argument("--cluster-sec", type=int, default=90)
    parser.add_argument("--cluster-min-score", type=float, default=8.0)
    parser.add_argument("--confirm-ticks", type=int, default=8)
    parser.add_argument("--confirm-sec", type=int, default=10)
    parser.add_argument("--test-buffer-ticks", type=int, default=4)
    parser.add_argument("--fail-buffer-ticks", type=int, default=2)
    parser.add_argument("--fail-confirm-ticks", type=int, default=8)
    parser.add_argument("--fail-sec", type=int, default=10)
    parser.add_argument("--hold-confirm-ticks", type=int, default=10)
    parser.add_argument("--gap-threshold-sec", type=float, default=5.0)
    parser.add_argument("--pre-field-sec", type=int, default=5 * 60)
    parser.add_argument("--pre-long-sec", type=int, default=10 * 60)
    parser.add_argument("--near-ticks", type=int, default=80)
    parser.add_argument("--edge-ticks", type=int, default=20)
    parser.add_argument("--depth-pad-ticks", type=int, default=20)
    parser.add_argument("--tick-band-pad", type=int, default=1)
    return parser.parse_args()


def et(ts: datetime | None, *, ms: bool = False) -> str:
    if ts is None:
        return ""
    fmt = "%Y-%m-%d %H:%M:%S.%f" if ms else "%Y-%m-%d %H:%M:%S"
    text = ts.astimezone(NY).strftime(fmt)
    return text[:-3] if ms else text


def price(tick: int | float | None) -> float | None:
    if tick is None:
        return None
    return float(tick) * TICK_SIZE


def fmt(value: Any, digits: int = 3) -> str | float | int:
    if value is None:
        return ""
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            return ""
        return round(value, digits)
    return value


def side_sign(side: str) -> int:
    return 1 if side == "demand" else -1


def side_book_name(side: str) -> str:
    return "bid" if side == "demand" else "ask"


def owner_hostile_sign(side: str) -> int:
    return -side_sign(side)


def range_distance(a_min: int, a_max: int, b_min: int, b_max: int) -> int:
    if a_max < b_min:
        return b_min - a_max
    if b_max < a_min:
        return a_min - b_max
    return 0


def ranges_overlap_or_near(a_min: int, a_max: int, b_min: int, b_max: int, pad_ticks: int) -> bool:
    return range_distance(a_min, a_max, b_min, b_max) <= pad_ticks


def make_probe(args: argparse.Namespace, date: str) -> ReplayData:
    start_s, end_s = args.window.split("-", 1)
    window_start = parse_ny(date, start_s)
    window_end = parse_ny(date, end_s)
    replay_start = window_start - timedelta(minutes=args.warmup_min)
    replay_end = window_end + timedelta(minutes=args.lookahead_min)

    snapshots = load_snapshots(args.symbol_dir, replay_start, replay_end)
    first_snap, _last_snap, duplicate_count, gaps = snapshot_timing_summary(
        snapshots,
        args.gap_threshold_sec,
    )
    if first_snap > window_start:
        raise ValueError(f"{date} snapshots start after RTH window: {et(first_snap)}")

    probe = OwnershipProbe(
        event_z=args.event_z,
        cluster_min_events=args.cluster_min_events,
        cluster_ticks=args.cluster_ticks,
        cluster_sec=args.cluster_sec,
        cluster_min_score=args.cluster_min_score,
        confirm_ticks=args.confirm_ticks,
        confirm_sec=args.confirm_sec,
        test_buffer_ticks=args.test_buffer_ticks,
        fail_buffer_ticks=args.fail_buffer_ticks,
        fail_confirm_ticks=args.fail_confirm_ticks,
        fail_sec=args.fail_sec,
        hold_confirm_ticks=args.hold_confirm_ticks,
        book_lookback_sec=args.book_lookback_sec,
    )
    snapshot_rows = snapshots.to_dicts()
    for row in snapshot_rows:
        probe.on_sample(build_sample(row))

    ticks = load_capture_window(
        "ticks",
        args.symbol_dir,
        replay_start,
        replay_end,
        tick_columns(),
        inclusive_end=True,
    )

    return ReplayData(
        date=date,
        window_start=window_start,
        window_end=window_end,
        replay_start=replay_start,
        replay_end=replay_end,
        probe=probe,
        snapshots=snapshots,
        snapshot_rows=snapshot_rows,
        snapshot_times=[int(row["timestamp_us"]) for row in snapshot_rows],
        ticks=ticks,
        tick_times=[int(v) for v in ticks.get_column("timestamp_us").to_list()],
        tick_prices=[float(v) for v in ticks.get_column("price").to_list()],
        tick_sizes=[float(v) for v in ticks.get_column("size").to_list()],
        tick_signs=[int(v) for v in ticks.get_column("aggressor_sign").to_list()],
        bands_by_id={band.id: band for band in probe.bands},
        gap_count=len(gaps),
        duplicate_timestamps=duplicate_count,
    )


def snapshot_at_or_before(data: ReplayData, ts_us: int, max_age_sec: float = 2.5) -> dict[str, Any] | None:
    idx = bisect.bisect_right(data.snapshot_times, ts_us) - 1
    if idx < 0:
        return None
    age = (ts_us - data.snapshot_times[idx]) / 1_000_000.0
    if age < 0 or age > max_age_sec:
        return None
    return data.snapshot_rows[idx]


def snapshot_range_depth(row: dict[str, Any] | None, lo_tick: int, hi_tick: int, side: str) -> float | None:
    if row is None:
        return None
    prefix = "bid" if side == "bid" else "ask"
    ref = int(row["ref_tick"])
    total = 0.0
    for idx in range(BROAD_LEVELS):
        size = float(row[f"{prefix}_size_{idx}"])
        if not math.isfinite(size) or size <= 0:
            continue
        tick = ref + int(row[f"{prefix}_offset_{idx}"])
        if lo_tick <= tick <= hi_tick:
            total += size
    return total


def snapshot_top_depth(row: dict[str, Any] | None, side: str, levels: int = 20) -> float | None:
    if row is None:
        return None
    prefix = "bid" if side == "bid" else "ask"
    total = 0.0
    for idx in range(min(levels, BROAD_LEVELS)):
        size = float(row[f"{prefix}_size_{idx}"])
        if math.isfinite(size) and size > 0:
            total += size
    return total


def tick_window_indices(data: ReplayData, start_us: int, end_us: int) -> tuple[int, int]:
    return (
        bisect.bisect_left(data.tick_times, start_us),
        bisect.bisect_right(data.tick_times, end_us),
    )


def price_path(data: ReplayData, start_us: int, end_us: int, side: str, fallback_price: float) -> dict[str, Any]:
    lo, hi = tick_window_indices(data, start_us, end_us)
    if hi <= lo:
        start = fallback_price
        return {
            "start_price": start,
            "close_price": start,
            "high": start,
            "low": start,
            "favorable": 0.0,
            "adverse": 0.0,
            "volume": 0.0,
            "delta": 0.0,
            "trades": 0,
        }
    prices = data.tick_prices[lo:hi]
    sizes = data.tick_sizes[lo:hi]
    signs = data.tick_signs[lo:hi]
    start = prices[0]
    high = max(prices)
    low = min(prices)
    sign = side_sign(side)
    favorable = high - start if sign > 0 else start - low
    adverse = start - low if sign > 0 else high - start
    return {
        "start_price": start,
        "close_price": prices[-1],
        "high": high,
        "low": low,
        "favorable": favorable,
        "adverse": adverse,
        "volume": sum(sizes),
        "delta": sum(size * sign_ for size, sign_ in zip(sizes, signs)),
        "trades": hi - lo,
    }


def prior_tick_field(data: ReplayData, tr: Transition, seconds: int) -> dict[str, Any]:
    end_us = us(tr.ts)
    start_us = us(tr.ts - timedelta(seconds=seconds))
    lo, hi = tick_window_indices(data, start_us, end_us)
    if hi <= lo:
        return {
            "low_tick": tr.min_tick,
            "high_tick": tr.max_tick,
            "width_pts": price(tr.max_tick - tr.min_tick),
            "position_pct": 0.5,
            "side_edge_distance_pts": 0.0,
            "volume": 0.0,
            "delta": 0.0,
        }
    prices = data.tick_prices[lo:hi]
    sizes = data.tick_sizes[lo:hi]
    signs = data.tick_signs[lo:hi]
    low_tick = min(round(p / TICK_SIZE) for p in prices)
    high_tick = max(round(p / TICK_SIZE) for p in prices)
    width = max(1, high_tick - low_tick)
    center = (tr.min_tick + tr.max_tick) / 2.0
    pct = (center - low_tick) / width
    if tr.side == "demand":
        edge_distance = high_tick - tr.max_tick
        side_edge_pct = pct
    else:
        edge_distance = tr.min_tick - low_tick
        side_edge_pct = 1.0 - pct
    return {
        "low_tick": low_tick,
        "high_tick": high_tick,
        "width_pts": width * TICK_SIZE,
        "position_pct": pct,
        "side_edge_pct": side_edge_pct,
        "side_edge_distance_pts": edge_distance * TICK_SIZE,
        "volume": sum(sizes),
        "delta": sum(size * sign for size, sign in zip(sizes, signs)),
    }


def transition_counts(
    transitions: list[Transition],
    origin: Transition,
    seconds: int,
    pad_ticks: int,
) -> Counter[str]:
    start = origin.ts - timedelta(seconds=seconds)
    counts: Counter[str] = Counter()
    for tr in transitions:
        if tr.ts >= origin.ts or tr.ts < start:
            continue
        if not ranges_overlap_or_near(origin.min_tick, origin.max_tick, tr.min_tick, tr.max_tick, pad_ticks):
            continue
        side_key = "same" if tr.side == origin.side else "opp"
        counts[f"{side_key}_{tr.action.lower()}"] += 1
        counts[f"all_{tr.action.lower()}"] += 1
        if tr.action == "FAIL":
            counts[f"{side_key}_fail_score"] += int(round(tr.score))
    counts["two_sided_fail"] = int(counts["same_fail"] > 0 and counts["opp_fail"] > 0)
    return counts


def first_same_band_after(transitions: list[Transition], origin: Transition, action: str) -> Transition | None:
    for tr in sorted(transitions, key=lambda item: item.ts):
        if tr.band_id == origin.band_id and tr.ts > origin.ts and tr.action == action:
            return tr
    return None


def same_band_outcome(transitions: list[Transition], origin: Transition) -> tuple[str, Transition | None, Transition | None, Transition | None]:
    same = [
        tr for tr in sorted(transitions, key=lambda item: item.ts)
        if tr.band_id == origin.band_id and tr.ts > origin.ts
    ]
    first_test = next((tr for tr in same if tr.action == "TEST"), None)
    first_hold = next((tr for tr in same if tr.action == "HOLD"), None)
    first_fail = next((tr for tr in same if tr.action == "FAIL"), None)
    if first_test is None:
        if first_fail is not None:
            return "failed_without_retest", None, None, first_fail
        return "no_retest_seen", None, None, None
    if first_fail is not None and first_fail.ts < first_test.ts:
        return "failed_before_retest", first_test, first_hold, first_fail
    if first_hold is not None and (first_fail is None or first_hold.ts < first_fail.ts):
        return "retest_held", first_test, first_hold, first_fail
    if first_fail is not None:
        return "retest_failed", first_test, first_hold, first_fail
    return "retest_unresolved", first_test, first_hold, first_fail


def band_tick_volume(
    data: ReplayData,
    start_us: int,
    end_us: int,
    side: str,
    lo_tick: int,
    hi_tick: int,
    pad_ticks: int,
) -> tuple[float, float]:
    lo, hi = tick_window_indices(data, start_us, end_us)
    hostile = 0.0
    aligned = 0.0
    hostile_sign = owner_hostile_sign(side)
    aligned_sign = side_sign(side)
    band_lo = lo_tick - pad_ticks
    band_hi = hi_tick + pad_ticks
    for idx in range(lo, hi):
        tick = round(data.tick_prices[idx] / TICK_SIZE)
        if tick < band_lo or tick > band_hi:
            continue
        sign = data.tick_signs[idx]
        size = data.tick_sizes[idx]
        if sign == hostile_sign:
            hostile += size
        elif sign == aligned_sign:
            aligned += size
    return hostile, aligned


def book_features_at(
    data: ReplayData,
    tr: Transition,
    prefix: str,
    *,
    pad_ticks: int,
    tick_band_pad: int,
) -> dict[str, Any]:
    out: dict[str, Any] = {}
    base_us = us(tr.ts)
    owner_book = side_book_name(tr.side)
    opp_book = side_book_name(opposite(tr.side))
    start_row = snapshot_at_or_before(data, base_us)
    same_start = snapshot_range_depth(start_row, tr.min_tick, tr.max_tick, owner_book)
    opp_start = snapshot_range_depth(start_row, tr.min_tick, tr.max_tick, opp_book)
    out[f"{prefix}_same_depth"] = fmt(same_start)
    out[f"{prefix}_opp_depth"] = fmt(opp_start)
    out[f"{prefix}_top20_bid"] = fmt(snapshot_top_depth(start_row, "bid"))
    out[f"{prefix}_top20_ask"] = fmt(snapshot_top_depth(start_row, "ask"))

    below_lo = tr.min_tick - pad_ticks
    below_hi = tr.min_tick - 1
    above_lo = tr.max_tick + 1
    above_hi = tr.max_tick + pad_ticks
    out[f"{prefix}_same_depth_below"] = fmt(snapshot_range_depth(start_row, below_lo, below_hi, owner_book))
    out[f"{prefix}_same_depth_above"] = fmt(snapshot_range_depth(start_row, above_lo, above_hi, owner_book))
    out[f"{prefix}_opp_depth_below"] = fmt(snapshot_range_depth(start_row, below_lo, below_hi, opp_book))
    out[f"{prefix}_opp_depth_above"] = fmt(snapshot_range_depth(start_row, above_lo, above_hi, opp_book))

    for seconds in BOOK_WINDOWS:
        row = snapshot_at_or_before(data, base_us + seconds * 1_000_000)
        same_end = snapshot_range_depth(row, tr.min_tick, tr.max_tick, owner_book)
        opp_end = snapshot_range_depth(row, tr.min_tick, tr.max_tick, opp_book)
        hostile, aligned = band_tick_volume(
            data,
            base_us,
            base_us + seconds * 1_000_000,
            tr.side,
            tr.min_tick,
            tr.max_tick,
            tick_band_pad,
        )
        repl = None
        rr = None
        if same_start is not None and same_end is not None:
            repl = hostile + (same_end - same_start)
            rr = repl / max(hostile, 1.0)
        out[f"{prefix}_same_depth_{seconds}s"] = fmt(same_end)
        out[f"{prefix}_opp_depth_{seconds}s"] = fmt(opp_end)
        out[f"{prefix}_hostile_vol_{seconds}s"] = fmt(hostile)
        out[f"{prefix}_aligned_vol_{seconds}s"] = fmt(aligned)
        out[f"{prefix}_replenishment_{seconds}s"] = fmt(repl)
        out[f"{prefix}_reload_ratio_{seconds}s"] = fmt(rr)
    return out


def build_event_row(args: argparse.Namespace, data: ReplayData, tr: Transition) -> dict[str, Any]:
    band = data.bands_by_id.get(tr.band_id)
    outcome, first_test, first_hold, first_fail = same_band_outcome(data.probe.transitions, tr)
    ts_us = us(tr.ts)
    fallback_px = price(tr.current_mid_tick) or 0.0
    pre_field = prior_tick_field(data, tr, args.pre_field_sec)
    pre_long_field = prior_tick_field(data, tr, args.pre_long_sec)
    pre_counts = transition_counts(data.probe.transitions, tr, args.pre_field_sec, args.near_ticks)
    pre_long_counts = transition_counts(data.probe.transitions, tr, args.pre_long_sec, args.near_ticks)
    confirm_disp_ticks = (
        tr.current_mid_tick - tr.max_tick
        if tr.side == "demand"
        else tr.min_tick - tr.current_mid_tick
    )

    row: dict[str, Any] = {
        "date": data.date,
        "symbol_dir": args.symbol_dir,
        "event_ts_et": et(tr.ts, ms=True),
        "event_ts_utc": tr.ts.isoformat(),
        "band_id": tr.band_id,
        "side": tr.side,
        "consumed_side": opposite(tr.side),
        "source": tr.source,
        "action": tr.action,
        "price_lo": fmt(price(tr.min_tick), 2),
        "price_hi": fmt(price(tr.max_tick), 2),
        "width_pts": fmt((tr.max_tick - tr.min_tick) * TICK_SIZE, 2),
        "current_mid_price": fmt(price(tr.current_mid_tick), 2),
        "confirm_displacement_pts": fmt(confirm_disp_ticks * TICK_SIZE, 2),
        "score": fmt(tr.score, 2),
        "max_abs_z": fmt(tr.max_abs_z, 2),
        "event_count": tr.event_count,
        "kinds": tr.note,
        "evidence_start_et": et(getattr(band, "evidence_start_ts", None), ms=True),
        "formed_et": et(getattr(band, "formed_ts", None), ms=True),
        "owned_et": et(getattr(band, "owned_ts", None), ms=True),
        "evidence_duration_s": fmt((band.formed_ts - band.evidence_start_ts).total_seconds() if band else None),
        "confirm_age_s": fmt((tr.ts - band.formed_ts).total_seconds() if band else None),
        "failed_et": et(getattr(band, "failed_ts", None), ms=True),
        "life_sec": fmt(((band.failed_ts or data.replay_end) - tr.ts).total_seconds() if band else None),
        "held_2m": int(not band or band.failed_ts is None or band.failed_ts > tr.ts + timedelta(seconds=120)),
        "held_5m": int(not band or band.failed_ts is None or band.failed_ts > tr.ts + timedelta(seconds=300)),
        "held_10m": int(not band or band.failed_ts is None or band.failed_ts > tr.ts + timedelta(seconds=600)),
        "failed_2m": int(bool(band and band.failed_ts is not None and band.failed_ts <= tr.ts + timedelta(seconds=120))),
        "failed_5m": int(bool(band and band.failed_ts is not None and band.failed_ts <= tr.ts + timedelta(seconds=300))),
        "failed_10m": int(bool(band and band.failed_ts is not None and band.failed_ts <= tr.ts + timedelta(seconds=600))),
        "same_band_outcome": outcome,
        "first_test_et": et(first_test.ts if first_test else None, ms=True),
        "first_hold_et": et(first_hold.ts if first_hold else None, ms=True),
        "first_fail_et": et(first_fail.ts if first_fail else None, ms=True),
        "time_to_first_test_s": fmt((first_test.ts - tr.ts).total_seconds() if first_test else None),
        "time_to_first_fail_s": fmt((first_fail.ts - tr.ts).total_seconds() if first_fail else None),
        "pre_field_low": fmt(price(pre_field["low_tick"]), 2),
        "pre_field_high": fmt(price(pre_field["high_tick"]), 2),
        "pre_field_width_pts": fmt(pre_field["width_pts"], 2),
        "pre_field_position_pct": fmt(pre_field["position_pct"], 3),
        "pre_side_edge_pct": fmt(pre_field["side_edge_pct"], 3),
        "pre_side_edge_distance_pts": fmt(pre_field["side_edge_distance_pts"], 2),
        "pre_volume_5m": fmt(pre_field["volume"], 2),
        "pre_delta_5m": fmt(pre_field["delta"], 2),
        "pre_long_field_width_pts": fmt(pre_long_field["width_pts"], 2),
        "pre_long_side_edge_pct": fmt(pre_long_field["side_edge_pct"], 3),
        "pre_long_volume_10m": fmt(pre_long_field["volume"], 2),
        "pre_long_delta_10m": fmt(pre_long_field["delta"], 2),
        "pre_same_claim_5m": pre_counts["same_owned"] + pre_counts["same_consumed"],
        "pre_opp_claim_5m": pre_counts["opp_owned"] + pre_counts["opp_consumed"],
        "pre_same_fail_5m": pre_counts["same_fail"],
        "pre_opp_fail_5m": pre_counts["opp_fail"],
        "pre_two_sided_fail_5m": pre_counts["two_sided_fail"],
        "pre_same_consumed_5m": pre_counts["same_consumed"],
        "pre_opp_consumed_5m": pre_counts["opp_consumed"],
        "pre_same_claim_10m": pre_long_counts["same_owned"] + pre_long_counts["same_consumed"],
        "pre_opp_claim_10m": pre_long_counts["opp_owned"] + pre_long_counts["opp_consumed"],
        "pre_same_fail_10m": pre_long_counts["same_fail"],
        "pre_opp_fail_10m": pre_long_counts["opp_fail"],
        "pre_two_sided_fail_10m": pre_long_counts["two_sided_fail"],
    }

    row.update(book_features_at(
        data,
        tr,
        "conv",
        pad_ticks=args.depth_pad_ticks,
        tick_band_pad=args.tick_band_pad,
    ))

    for horizon in HORIZONS:
        path = price_path(data, ts_us, ts_us + horizon * 1_000_000, tr.side, fallback_px)
        label = f"{int(horizon / 60)}m"
        row[f"fav_{label}"] = fmt(path["favorable"], 2)
        row[f"adv_{label}"] = fmt(path["adverse"], 2)
        row[f"path_score_{label}"] = fmt(path["favorable"] - path["adverse"], 2)
        row[f"close_move_{label}"] = fmt(
            (path["close_price"] - path["start_price"]) * side_sign(tr.side),
            2,
        )
        row[f"volume_{label}"] = fmt(path["volume"], 2)
        row[f"delta_{label}"] = fmt(path["delta"], 2)

    if first_test is not None:
        test_us = us(first_test.ts)
        before_test = price_path(data, ts_us, test_us, tr.side, fallback_px)
        row["fav_before_test_pts"] = fmt(before_test["favorable"], 2)
        row["adv_before_test_pts"] = fmt(before_test["adverse"], 2)
        row["approach_velocity_pts_s"] = fmt(
            before_test["adverse"] / max((first_test.ts - tr.ts).total_seconds(), 1.0),
            4,
        )
        row.update(book_features_at(
            data,
            first_test,
            "test",
            pad_ticks=args.depth_pad_ticks,
            tick_band_pad=args.tick_band_pad,
        ))
    else:
        row["fav_before_test_pts"] = ""
        row["adv_before_test_pts"] = ""
        row["approach_velocity_pts_s"] = ""
        for key in book_features_at(
            data,
            tr,
            "test",
            pad_ticks=args.depth_pad_ticks,
            tick_band_pad=args.tick_band_pad,
        ):
            row[key] = ""

    row["pre_edge_bucket"] = edge_bucket(as_float(row.get("pre_side_edge_pct")))
    row["pre_fail_bucket"] = count_bucket(int(row.get("pre_same_fail_5m", 0)) + int(row.get("pre_opp_fail_5m", 0)))
    row["conv_replenishment_2s_bucket"] = signed_bucket(as_float(row.get("conv_replenishment_2s")))
    row["conv_replenishment_5s_bucket"] = signed_bucket(as_float(row.get("conv_replenishment_5s")))
    row["test_replenishment_2s_bucket"] = signed_bucket(as_float(row.get("test_replenishment_2s")))
    row["test_replenishment_5s_bucket"] = signed_bucket(as_float(row.get("test_replenishment_5s")))
    row["time_to_test_bucket"] = time_bucket(as_float(row.get("time_to_first_test_s")))
    row["path_5m_bucket"] = path_bucket(as_float(row.get("path_score_5m")))
    row["lifecycle_bucket"] = lifecycle_bucket(row)
    return row


def build_transition_row(args: argparse.Namespace, data: ReplayData, tr: Transition) -> dict[str, Any]:
    band = data.bands_by_id.get(tr.band_id)
    return {
        "date": data.date,
        "symbol_dir": args.symbol_dir,
        "event_ts_et": et(tr.ts, ms=True),
        "event_ts_utc": tr.ts.isoformat(),
        "band_id": tr.band_id,
        "side": tr.side,
        "opposite_side": opposite(tr.side),
        "source": tr.source,
        "action": tr.action,
        "price_lo": fmt(price(tr.min_tick), 2),
        "price_hi": fmt(price(tr.max_tick), 2),
        "width_pts": fmt((tr.max_tick - tr.min_tick) * TICK_SIZE, 2),
        "current_mid_price": fmt(price(tr.current_mid_tick), 2),
        "score": fmt(tr.score, 2),
        "max_abs_z": fmt(tr.max_abs_z, 2),
        "event_count": tr.event_count,
        "kinds": tr.note,
        "evidence_start_et": et(getattr(band, "evidence_start_ts", None), ms=True),
        "formed_et": et(getattr(band, "formed_ts", None), ms=True),
        "owned_et": et(getattr(band, "owned_ts", None), ms=True),
        "failed_et": et(getattr(band, "failed_ts", None), ms=True),
    }


def as_float(value: Any) -> float | None:
    if value in ("", None):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def edge_bucket(value: float | None) -> str:
    if value is None:
        return "unknown"
    if value >= 0.8:
        return "favorable_edge"
    if value <= 0.2:
        return "adverse_edge"
    return "interior"


def count_bucket(value: int) -> str:
    if value <= 0:
        return "0"
    if value <= 2:
        return "1-2"
    if value <= 5:
        return "3-5"
    return "6+"


def signed_bucket(value: float | None) -> str:
    if value is None:
        return "unknown"
    if value >= 20:
        return "strong_reload"
    if value > 0:
        return "reload"
    if value == 0:
        return "flat"
    if value > -20:
        return "drain"
    return "strong_drain"


def time_bucket(value: float | None) -> str:
    if value is None:
        return "no_retest"
    if value <= 30:
        return "0-30s"
    if value <= 120:
        return "30-120s"
    if value <= 300:
        return "2-5m"
    return "5m+"


def path_bucket(value: float | None) -> str:
    if value is None:
        return "unknown"
    if value >= 20:
        return "strong_favorable"
    if value > 0:
        return "favorable"
    if value > -20:
        return "adverse"
    return "strong_adverse"


def lifecycle_bucket(row: dict[str, Any]) -> str:
    outcome = str(row.get("same_band_outcome", ""))
    held_5m = str(row.get("held_5m", "")) == "1" or row.get("held_5m") == 1
    two_sided = str(row.get("pre_two_sided_fail_5m", "")) == "1"
    path = as_float(row.get("path_score_5m")) or 0.0
    if outcome in {"retest_held", "no_retest_seen"} and held_5m and path > 0:
        if row.get("pre_edge_bucket") == "favorable_edge":
            return "edge_escape_or_hold"
        return "held_interior_or_transition"
    if outcome in {"retest_failed", "failed_without_retest", "failed_before_retest"}:
        if two_sided:
            return "failed_in_two_sided_field"
        return "failed_after_conversion"
    if two_sided:
        return "contested_unresolved"
    return "unresolved"


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if fieldnames is None:
        keys: list[str] = []
        seen = set()
        for row in rows:
            for key in row:
                if key not in seen:
                    seen.add(key)
                    keys.append(key)
        fieldnames = keys
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def summarize_dimension(rows: list[dict[str, Any]], dimension: str) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[str(row.get(dimension, ""))].append(row)
    out: list[dict[str, Any]] = []
    for bucket, items in sorted(groups.items(), key=lambda item: (-len(item[1]), item[0])):
        held_5m = [as_float(row.get("held_5m")) or 0.0 for row in items]
        failed_5m = [as_float(row.get("failed_5m")) or 0.0 for row in items]
        path_scores = [as_float(row.get("path_score_5m")) for row in items]
        favs = [as_float(row.get("fav_5m")) for row in items]
        advs = [as_float(row.get("adv_5m")) for row in items]
        retest_held = [1.0 if row.get("same_band_outcome") == "retest_held" else 0.0 for row in items]
        retest_failed = [
            1.0
            if row.get("same_band_outcome") in {"retest_failed", "failed_without_retest", "failed_before_retest"}
            else 0.0
            for row in items
        ]
        out.append(
            {
                "dimension": dimension,
                "bucket": bucket,
                "n": len(items),
                "held_5m_rate": round(sum(held_5m) / len(items), 3),
                "failed_5m_rate": round(sum(failed_5m) / len(items), 3),
                "retest_held_rate": round(sum(retest_held) / len(items), 3),
                "retest_failed_any_rate": round(sum(retest_failed) / len(items), 3),
                "median_path_score_5m": median_or_blank(path_scores),
                "median_fav_5m": median_or_blank(favs),
                "median_adv_5m": median_or_blank(advs),
            }
        )
    return out


def median_or_blank(values: Iterable[float | None]) -> float | str:
    clean = [value for value in values if value is not None and math.isfinite(value)]
    return "" if not clean else round(statistics.median(clean), 3)


def build_bucket_summary(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    dimensions = [
        "date",
        "side",
        "source",
        "same_band_outcome",
        "lifecycle_bucket",
        "pre_edge_bucket",
        "pre_fail_bucket",
        "pre_two_sided_fail_5m",
        "conv_replenishment_2s_bucket",
        "conv_replenishment_5s_bucket",
        "test_replenishment_2s_bucket",
        "test_replenishment_5s_bucket",
        "time_to_test_bucket",
        "path_5m_bucket",
    ]
    out: list[dict[str, Any]] = []
    for dimension in dimensions:
        out.extend(summarize_dimension(rows, dimension))
    return out


def write_markdown(path: Path, rows: list[dict[str, Any]], bucket_rows: list[dict[str, Any]], manifests: list[dict[str, Any]]) -> None:
    lines: list[str] = [
        "# DirectConversion Lifecycle Dataset",
        "",
        "Synthetic LL `CONSUMED` transitions from MarketRecorder snapshots.",
        "",
        "## Manifest",
        "",
    ]
    for manifest in manifests:
        lines.append(
            f"- {manifest['date']}: rows={manifest['snapshot_rows']} snapshots, "
            f"ticks={manifest['tick_rows']}, conversions={manifest['conversions']}, "
            f"gaps={manifest['gap_count']}"
        )
    lines.extend(["", "## Outcome Counts", ""])
    counts = Counter(str(row.get("same_band_outcome", "")) for row in rows)
    for key, count in counts.most_common():
        lines.append(f"- {key}: {count}")
    lines.extend(["", "## Lifecycle Buckets", ""])
    life_counts = Counter(str(row.get("lifecycle_bucket", "")) for row in rows)
    for key, count in life_counts.most_common():
        lines.append(f"- {key}: {count}")
    lines.extend(["", "## Strongest Bucket Separations", ""])
    notable = [
        row for row in bucket_rows
        if int(row["n"]) >= 3 and row["dimension"] not in {"date"}
    ]
    notable.sort(
        key=lambda row: (
            abs(float(row["held_5m_rate"]) - overall_rate(rows, "held_5m")),
            int(row["n"]),
        ),
        reverse=True,
    )
    for row in notable[:20]:
        lines.append(
            f"- {row['dimension']}={row['bucket']}: n={row['n']}, "
            f"held5={row['held_5m_rate']}, failed5={row['failed_5m_rate']}, "
            f"retest_fail_any={row['retest_failed_any_rate']}, "
            f"median_path5={row['median_path_score_5m']}"
        )
    lines.extend([
        "",
        "## Notes",
        "",
        "- This is broad snapshot/tape evidence. Raw quote-event replay should validate selected buckets.",
        "- HVN/LVN is not used as an input label; churn/escape proxies come from lifecycle fields.",
    ])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def overall_rate(rows: list[dict[str, Any]], key: str) -> float:
    if not rows:
        return 0.0
    return sum((as_float(row.get(key)) or 0.0) for row in rows) / len(rows)


def main() -> None:
    args = parse_args()
    out_dir = Path(args.out_dir)
    all_rows: list[dict[str, Any]] = []
    all_transition_rows: list[dict[str, Any]] = []
    manifests: list[dict[str, Any]] = []

    for date in [part.strip() for part in args.dates.split(",") if part.strip()]:
        data = make_probe(args, date)
        transitions = [
            tr for tr in data.probe.transitions
            if data.window_start <= tr.ts <= data.window_end
        ]
        conversions = [
            tr for tr in transitions
            if tr.action == "CONSUMED"
        ]
        date_rows = [build_event_row(args, data, tr) for tr in conversions]
        all_rows.extend(date_rows)
        all_transition_rows.extend(build_transition_row(args, data, tr) for tr in transitions)
        manifests.append(
            {
                "date": date,
                "snapshot_rows": data.snapshots.height,
                "tick_rows": data.ticks.height,
                "conversions": len(date_rows),
                "gap_count": data.gap_count,
                "duplicate_timestamps": data.duplicate_timestamps,
            }
        )

    all_rows.sort(key=lambda row: (str(row.get("date", "")), str(row.get("event_ts_et", ""))))
    all_transition_rows.sort(key=lambda row: (str(row.get("date", "")), str(row.get("event_ts_et", ""))))
    bucket_rows = build_bucket_summary(all_rows)
    write_csv(out_dir / "direct_conversion_events.csv", all_rows)
    write_csv(out_dir / "rail_transitions.csv", all_transition_rows)
    write_csv(out_dir / "bucket_summary.csv", bucket_rows)
    write_csv(out_dir / "manifest.csv", manifests)
    write_markdown(out_dir / "findings.md", all_rows, bucket_rows, manifests)

    print(f"wrote {out_dir / 'direct_conversion_events.csv'} rows={len(all_rows)}")
    print(f"wrote {out_dir / 'rail_transitions.csv'} rows={len(all_transition_rows)}")
    print(f"wrote {out_dir / 'bucket_summary.csv'} rows={len(bucket_rows)}")
    print(f"wrote {out_dir / 'findings.md'}")


if __name__ == "__main__":
    main()
