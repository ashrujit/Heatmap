"""Research-only post-event refill overlay for LevelLedger replay output.

This does not change the live indicator. It replays the existing LevelLedger
research engine, then asks whether the book refilled on the same side or the
opposite side after each panel-row or ownership-band mutation.
"""

from __future__ import annotations

import argparse
import bisect
import statistics
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from replay_levelledger import (  # noqa: E402
    Engine,
    TICK_SIZE,
    abbrev,
    band_range,
    build_sample,
    load_snapshots,
    ny_hms,
    parse_ny,
)


REFILL_BAND_TICKS = 8
PRE_WINDOW_SEC = 20
IMPACT_WINDOW_SEC = 5
POST_START_SEC = 5
POST_END_SEC = 24


@dataclass
class DepthSample:
    ts: datetime
    ref_tick: int
    bids: list[tuple[int, float]]
    asks: list[tuple[int, float]]


@dataclass
class RefillAssessment:
    anchor_kind: str
    action: str
    ts: datetime
    side: str
    min_tick: int
    max_tick: int
    label: str
    impact: str
    pre_same: float
    low_same: float
    post_same: float
    pre_opp: float
    low_opp: float
    post_opp: float
    current_tick: int
    text: str
    score: float


def side_name(direction: int) -> str:
    return "demand" if direction > 0 else "supply"


def opposite(side: str) -> str:
    return "supply" if side == "demand" else "demand"


def build_depth_samples(snap) -> list[DepthSample]:
    samples: list[DepthSample] = []
    for row in snap.iter_rows(named=True):
        ref_tick = int(row["ref_tick"])
        bids: list[tuple[int, float]] = []
        asks: list[tuple[int, float]] = []
        i = 0
        while f"bid_offset_{i}" in row:
            bs = float(row[f"bid_size_{i}"])
            if bs > 0:
                bids.append((ref_tick + int(row[f"bid_offset_{i}"]), bs))
            az = float(row[f"ask_size_{i}"])
            if az > 0:
                asks.append((ref_tick + int(row[f"ask_offset_{i}"]), az))
            i += 1
        samples.append(
            DepthSample(
                ts=build_sample(row).ts,
                ref_tick=ref_tick,
                bids=bids,
                asks=asks,
            )
        )
    return samples


def depth_in_band(sample: DepthSample, side: str, min_tick: int, max_tick: int) -> float:
    levels = sample.bids if side == "demand" else sample.asks
    return sum(size for tick, size in levels if min_tick <= tick <= max_tick)


def window_values(
    samples: list[DepthSample],
    times: list[datetime],
    start: datetime,
    end: datetime,
    side: str,
    min_tick: int,
    max_tick: int,
) -> list[float]:
    lo = bisect.bisect_left(times, start)
    hi = bisect.bisect_left(times, end)
    return [depth_in_band(samples[i], side, min_tick, max_tick) for i in range(lo, hi)]


def median_or_zero(values: list[float]) -> float:
    return statistics.median(values) if values else 0.0


def max_or_zero(values: list[float]) -> float:
    return max(values) if values else 0.0


def min_or_zero(values: list[float]) -> float:
    return min(values) if values else 0.0


def assess_refill(
    samples: list[DepthSample],
    times: list[datetime],
    *,
    anchor_kind: str,
    action: str,
    ts: datetime,
    side: str,
    min_tick: int,
    max_tick: int,
    current_tick: int,
    text: str,
) -> RefillAssessment | None:
    pre_start = ts - timedelta(seconds=PRE_WINDOW_SEC)
    pre_end = ts
    impact_start = ts
    impact_end = ts + timedelta(seconds=IMPACT_WINDOW_SEC)
    post_start = ts + timedelta(seconds=POST_START_SEC)
    post_end = ts + timedelta(seconds=POST_END_SEC)

    opp = opposite(side)
    pre_same_vals = window_values(samples, times, pre_start, pre_end, side, min_tick, max_tick)
    post_same_vals = window_values(samples, times, post_start, post_end, side, min_tick, max_tick)
    if not pre_same_vals or not post_same_vals:
        return None

    impact_same_vals = window_values(samples, times, impact_start, impact_end, side, min_tick, max_tick)
    pre_opp_vals = window_values(samples, times, pre_start, pre_end, opp, min_tick, max_tick)
    impact_opp_vals = window_values(samples, times, impact_start, impact_end, opp, min_tick, max_tick)
    post_opp_vals = window_values(samples, times, post_start, post_end, opp, min_tick, max_tick)

    pre_same = median_or_zero(pre_same_vals)
    low_same = min_or_zero(impact_same_vals)
    post_same = max_or_zero(post_same_vals)
    pre_opp = median_or_zero(pre_opp_vals)
    low_opp = min_or_zero(impact_opp_vals)
    post_opp = max_or_zero(post_opp_vals)

    same_recovery = post_same - low_same
    opp_recovery = post_opp - low_opp
    same_ratio = post_same / max(1.0, pre_same)
    opp_ratio = post_opp / max(1.0, pre_opp)

    same_strong = (
        post_same >= max(18.0, pre_same * 0.75)
        and same_recovery >= max(8.0, pre_same * 0.25)
        and post_same >= post_opp * 1.15
    )
    opp_strong = (
        post_opp >= max(18.0, pre_opp * 0.75)
        and opp_recovery >= max(8.0, pre_opp * 0.25)
        and post_opp >= post_same * 1.15
    )
    same_missing = post_same < max(8.0, pre_same * 0.35)

    if action == "BREACH":
        if same_strong:
            label = "BREACH_REPAIR"
            impact = "would soften failed-band read"
            score = same_recovery + post_same - post_opp
        elif opp_strong or same_missing:
            label = "BREACH_CONFIRMED"
            impact = "supports failed-band read"
            score = opp_recovery + post_opp - post_same
        else:
            label = "BREACH_NEUTRAL"
            impact = "no clear refill change"
            score = abs(post_same - post_opp)
    else:
        if same_strong:
            label = "CONFIRM"
            impact = "would strengthen current read"
            score = same_recovery + post_same - post_opp
        elif opp_strong or same_missing:
            label = "CONFLICT"
            impact = "would weaken or question current read"
            score = opp_recovery + post_opp - post_same
        else:
            label = "NEUTRAL"
            impact = "no clear refill change"
            score = max(same_ratio, opp_ratio) * abs(post_same - post_opp)

    return RefillAssessment(
        anchor_kind=anchor_kind,
        action=action,
        ts=ts,
        side=side,
        min_tick=min_tick,
        max_tick=max_tick,
        label=label,
        impact=impact,
        pre_same=pre_same,
        low_same=low_same,
        post_same=post_same,
        pre_opp=pre_opp,
        low_opp=low_opp,
        post_opp=post_opp,
        current_tick=current_tick,
        text=text,
        score=score,
    )


def replay(date: str, symbol_dir: str, window: str, warmup_min: int):
    start_s, end_s = window.split("-", 1)
    window_start = parse_ny(date, start_s)
    window_end = parse_ny(date, end_s)
    replay_start = window_start - timedelta(minutes=warmup_min)
    snap = load_snapshots(symbol_dir, replay_start, window_end)
    engine = Engine()
    depth_samples = build_depth_samples(snap)
    for row in snap.iter_rows(named=True):
        engine.on_sample(build_sample(row))
    return window_start, window_end, engine, depth_samples


def assess_day(date: str, symbol_dir: str, window: str, warmup_min: int) -> list[RefillAssessment]:
    window_start, window_end, engine, samples = replay(date, symbol_dir, window, warmup_min)
    times = [s.ts for s in samples]
    assessments: list[RefillAssessment] = []

    for mutation in engine.mutations:
        if mutation.action_ts < window_start or mutation.action_ts > window_end:
            continue
        if mutation.direction == 0:
            continue
        center = mutation.price_tick
        min_tick = center - REFILL_BAND_TICKS
        max_tick = center + REFILL_BAND_TICKS
        side = side_name(mutation.direction)
        if side == "demand" and mutation.current_mid_tick < min_tick - 2:
            continue
        if side == "supply" and mutation.current_mid_tick > max_tick + 2:
            continue
        found = assess_refill(
            samples,
            times,
            anchor_kind="PANEL",
            action=mutation.action,
            ts=mutation.action_ts,
            side=side,
            min_tick=min_tick,
            max_tick=max_tick,
            current_tick=mutation.current_mid_tick,
            text=mutation.text,
        )
        if found is not None:
            assessments.append(found)

    for mutation in engine.build_band_mutations:
        if mutation.action_ts < window_start or mutation.action_ts > window_end:
            continue
        found = assess_refill(
            samples,
            times,
            anchor_kind="BAND",
            action=mutation.action,
            ts=mutation.action_ts,
            side=mutation.side,
            min_tick=mutation.min_tick - 2,
            max_tick=mutation.max_tick + 2,
            current_tick=mutation.current_mid_tick,
            text=f"band#{mutation.band_id} {band_range(mutation.min_tick, mutation.max_tick)}",
        )
        if found is not None:
            assessments.append(found)

    return assessments


def price_label(a: RefillAssessment) -> str:
    if a.min_tick == a.max_tick:
        return abbrev(a.min_tick)
    return band_range(a.min_tick, a.max_tick)


def print_assessments(
    date: str,
    assessments: list[RefillAssessment],
    limit: int,
    source: str | None,
) -> None:
    material = [
        a for a in assessments
        if a.label in {"CONFIRM", "CONFLICT", "BREACH_REPAIR", "BREACH_CONFIRMED"}
    ]
    if source:
        material = [a for a in material if a.anchor_kind == source]
    material.sort(key=lambda a: a.score, reverse=True)
    print(f"\n{date} material refill differences: {len(material)}")
    print("time     src    action   side    label             price/band       same pre->low->post   opp pre->low->post    note")
    for a in material[:limit]:
        print(
            f"{ny_hms(a.ts):<8} {a.anchor_kind:<6} {a.action:<7} {a.side:<6} "
            f"{a.label:<17} {price_label(a):>14} "
            f"{a.pre_same:5.0f}->{a.low_same:5.0f}->{a.post_same:<5.0f} "
            f"{a.pre_opp:5.0f}->{a.low_opp:5.0f}->{a.post_opp:<5.0f} "
            f"{a.impact}; {a.text}; current={abbrev(a.current_tick)}"
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dates", nargs="+", required=True)
    parser.add_argument("--symbol-dir", default="NQM6")
    parser.add_argument("--window", default="09:30-16:00")
    parser.add_argument("--warmup-min", type=int, default=60)
    parser.add_argument("--limit", type=int, default=30)
    parser.add_argument("--source", choices=["PANEL", "BAND"])
    args = parser.parse_args()

    for date in args.dates:
        assessments = assess_day(date, args.symbol_dir, args.window, args.warmup_min)
        print_assessments(date, assessments, args.limit, args.source)


if __name__ == "__main__":
    main()
