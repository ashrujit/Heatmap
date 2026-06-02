"""Replay Skurry BookThinningDetector against MarketRecorder captures.

This is research-only code. It mirrors the Skurry source detector's auction
recipe closely enough for fixture review:

- aggregate top-N book size on one side;
- compare current aggregate to the earliest retained sample in a 2x window;
- require a percentage drop;
- require same-side aggressive tape in the current window to be too small to
  explain the disappeared size;
- apply the Skurry phase gate and per-side cooldown.

The purpose is to find chart areas worth discussing before any LevelLedger UI
grammar is designed.
"""

from __future__ import annotations

import argparse
import bisect
import math
import os
import sys
from collections import deque
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import polars as pl

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "research"))
from capture_loader import load_capture_window, snapshot_columns, tick_columns


TICK_SIZE = 0.25
MAX_LEVELS = 30
NY = ZoneInfo("America/New_York")


@dataclass(frozen=True)
class Sample:
    ts: datetime
    us: int
    mid_tick: int
    bid_agg: float
    ask_agg: float
    bid_inner: float
    ask_inner: float
    bid_centroid: float
    ask_centroid: float
    bid_low: float
    bid_high: float
    bid_count: int
    ask_low: float
    ask_high: float
    ask_count: int

    @property
    def price(self) -> float:
        return self.mid_tick * TICK_SIZE


@dataclass(frozen=True)
class SizeSample:
    ts: datetime
    us: int
    aggregate: float


@dataclass
class ThinningEvent:
    ts: datetime
    us: int
    side: str
    direction: str
    price: float
    aggregate_before: float
    aggregate_after: float
    drop_pct: float
    size_dropped: float
    tape_volume: float
    allowed_tape: float
    affected_low: float
    affected_high: float
    affected_count: int
    phase: str
    pre60_same_ticks: int = 0
    pre60_opp_ticks: int = 0
    follow_ticks: int = 0
    adverse_ticks: int = 0
    vod_max_z_5s: float = 0.0
    vod_hit_5s: bool = False
    first_lean_delay_sec: float = -1.0
    first_lean_bias: str = "NONE"
    first_lean_kind: str = ""
    first_lean_z: float = 0.0
    first_lean_aligned: str = "NONE"
    post30_demand: float = 0.0
    post30_supply: float = 0.0
    post30_lean: str = "NONE"
    post30_aligned: str = "NONE"
    post60_demand: float = 0.0
    post60_supply: float = 0.0
    post60_lean: str = "NONE"
    post60_aligned: str = "NONE"

    @property
    def tape_ratio(self) -> float:
        return self.tape_volume / max(1.0, self.size_dropped)


@dataclass(frozen=True)
class LeanEvent:
    ts: datetime
    us: int
    bias: str
    kind: str
    z: float


class TapeIndex:
    def __init__(self, ticks: pl.DataFrame) -> None:
        self.times: list[int] = []
        self.buy_prefix: list[float] = [0.0]
        self.sell_prefix: list[float] = [0.0]
        buy = 0.0
        sell = 0.0
        for row in ticks.sort("timestamp_us").iter_rows(named=True):
            us = int(row["timestamp_us"])
            size = float(row["size"])
            sign = int(row["aggressor_sign"])
            if not math.isfinite(size) or size <= 0:
                continue
            self.times.append(us)
            if sign > 0:
                buy += size
            elif sign < 0:
                sell += size
            self.buy_prefix.append(buy)
            self.sell_prefix.append(sell)

    def volume(self, start_us: int, end_us: int, *, side: str) -> float:
        lo = bisect.bisect_left(self.times, start_us)
        hi = bisect.bisect_right(self.times, end_us)
        prefix = self.buy_prefix if side == "ask" else self.sell_prefix
        return prefix[hi] - prefix[lo]


def ny_dt(day: str, hhmm: str) -> datetime:
    fmt = "%Y-%m-%d %H:%M:%S" if hhmm.count(":") == 2 else "%Y-%m-%d %H:%M"
    return datetime.strptime(f"{day} {hhmm}", fmt).replace(tzinfo=NY)


def parse_window(day: str, window: str | None) -> tuple[datetime, datetime]:
    if window:
        start_s, end_s = window.split("-", 1)
        return ny_dt(day, start_s).astimezone(timezone.utc), ny_dt(day, end_s).astimezone(timezone.utc)
    d = datetime.fromisoformat(day).date()
    start = datetime.combine(d, time(9, 30), NY)
    end = datetime.combine(d, time(16, 0), NY)
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc)


def ny_hms(ts: datetime) -> str:
    return ts.astimezone(NY).strftime("%H:%M:%S")


def phase_name(ts: datetime) -> str:
    local = ts.astimezone(NY)
    hm = local.hour * 100 + local.minute
    if hm < 930:
        return "premarket"
    if hm < 945:
        return "open"
    if hm < 1030:
        return "ib"
    if hm < 1130:
        return "post_ib"
    if hm < 1400:
        return "lunch"
    if hm < 1500:
        return "afternoon"
    if hm < 1600:
        return "close"
    return "after_hours"


def load_data(day: str, symbol_dir: str, start: datetime, end: datetime, warmup_min: int) -> tuple[pl.DataFrame, pl.DataFrame]:
    load_start = start - timedelta(minutes=max(0, warmup_min))
    snap = load_capture_window(
        "snapshots",
        symbol_dir,
        load_start,
        end,
        snapshot_columns(MAX_LEVELS),
        inclusive_end=True,
    )
    ticks = load_capture_window(
        "ticks",
        symbol_dir,
        load_start,
        end,
        tick_columns(),
        inclusive_end=True,
    )
    return snap, ticks


def build_sample(row: dict, top_n: int) -> Sample:
    us = int(row["timestamp_us"])
    ref_tick = int(row["ref_tick"])

    bid_sum = 0.0
    ask_sum = 0.0
    bid_inner = 0.0
    ask_inner = 0.0
    bid_total = 0.0
    ask_total = 0.0
    bid_weighted_offset = 0.0
    ask_weighted_offset = 0.0
    bid_low = math.inf
    bid_high = -math.inf
    ask_low = math.inf
    ask_high = -math.inf
    bid_count = 0
    ask_count = 0

    top_n = min(top_n, MAX_LEVELS)
    for i in range(MAX_LEVELS):
        bs = float(row[f"bid_size_{i}"])
        if math.isfinite(bs) and bs > 0:
            offset = int(row[f"bid_offset_{i}"])
            tick = ref_tick + offset
            price = tick * TICK_SIZE
            if i < top_n:
                bid_sum += bs
                bid_low = min(bid_low, price)
                bid_high = max(bid_high, price)
                bid_count += 1
            if i < 10:
                bid_inner += bs
            bid_total += bs
            bid_weighted_offset += abs(offset) * bs

        az = float(row[f"ask_size_{i}"])
        if math.isfinite(az) and az > 0:
            offset = int(row[f"ask_offset_{i}"])
            tick = ref_tick + offset
            price = tick * TICK_SIZE
            if i < top_n:
                ask_sum += az
                ask_low = min(ask_low, price)
                ask_high = max(ask_high, price)
                ask_count += 1
            if i < 10:
                ask_inner += az
            ask_total += az
            ask_weighted_offset += abs(offset) * az

    return Sample(
        ts=datetime.fromtimestamp(us / 1_000_000, tz=timezone.utc),
        us=us,
        mid_tick=ref_tick,
        bid_agg=bid_sum,
        ask_agg=ask_sum,
        bid_inner=bid_inner,
        ask_inner=ask_inner,
        bid_centroid=bid_weighted_offset / bid_total if bid_total > 0 else 0.0,
        ask_centroid=ask_weighted_offset / ask_total if ask_total > 0 else 0.0,
        bid_low=0.0 if bid_count == 0 else bid_low,
        bid_high=0.0 if bid_count == 0 else bid_high,
        bid_count=bid_count,
        ask_low=0.0 if ask_count == 0 else ask_low,
        ask_high=0.0 if ask_count == 0 else ask_high,
        ask_count=ask_count,
    )


def replay(day: str, args) -> tuple[list[ThinningEvent], list[Sample]]:
    start, end = parse_window(day, args.window)
    snap, ticks = load_data(day, args.symbol_dir, start, end, args.warmup_min)
    samples = [build_sample(row, args.top_n_levels) for row in snap.iter_rows(named=True)]
    tape = TapeIndex(ticks)

    bid_hist: deque[SizeSample] = deque()
    ask_hist: deque[SizeSample] = deque()
    last_bid_fire: datetime | None = None
    last_ask_fire: datetime | None = None
    events: list[ThinningEvent] = []

    start_us = int(start.timestamp() * 1_000_000)
    end_us = int(end.timestamp() * 1_000_000)

    for sample in samples:
        bid_hist.append(SizeSample(sample.ts, sample.us, sample.bid_agg))
        ask_hist.append(SizeSample(sample.ts, sample.us, sample.ask_agg))
        prune_size_history(bid_hist, sample.ts, args.window_sec)
        prune_size_history(ask_hist, sample.ts, args.window_sec)

        if sample.us < start_us or sample.us > end_us:
            continue

        ev = evaluate_side(
            sample=sample,
            history=bid_hist,
            side="bid",
            last_fire=last_bid_fire,
            tape=tape,
            args=args,
        )
        if ev is not None:
            events.append(ev)
            last_bid_fire = sample.ts

        ev = evaluate_side(
            sample=sample,
            history=ask_hist,
            side="ask",
            last_fire=last_ask_fire,
            tape=tape,
            args=args,
        )
        if ev is not None:
            events.append(ev)
            last_ask_fire = sample.ts

    add_follow_through(events, samples, args.follow_sec)
    add_context(events, samples, args)
    events.sort(key=lambda e: e.us)
    return events, samples


def prune_size_history(history: deque[SizeSample], now: datetime, window_sec: int) -> None:
    cutoff = now - timedelta(seconds=window_sec * 2)
    while history and history[0].ts < cutoff:
        history.popleft()


def evaluate_side(
    sample: Sample,
    history: deque[SizeSample],
    side: str,
    last_fire: datetime | None,
    tape: TapeIndex,
    args,
) -> ThinningEvent | None:
    if last_fire is not None and (sample.ts - last_fire).total_seconds() < args.cooldown_sec:
        return None

    phase = phase_name(sample.ts)
    if args.phase_gate and phase in {"open", "ib", "close", "premarket", "after_hours"}:
        return None

    if len(history) < 2:
        return None
    earliest = history[0]
    if (sample.ts - earliest.ts).total_seconds() < args.window_sec * 0.8:
        return None

    before = earliest.aggregate
    after = sample.bid_agg if side == "bid" else sample.ask_agg
    if before <= 0:
        return None

    size_dropped = before - after
    if size_dropped <= 0:
        return None
    drop_pct = 1.0 - (after / before)
    if drop_pct < args.thinning_percent:
        return None

    tape_volume = tape.volume(sample.us - args.window_sec * 1_000_000, sample.us, side=side)
    allowed_tape = args.tape_volume_floor * size_dropped
    if tape_volume >= allowed_tape:
        return None

    if side == "bid":
        direction = "DOWN"
        affected_low = sample.bid_low
        affected_high = sample.bid_high
        affected_count = sample.bid_count
    else:
        direction = "UP"
        affected_low = sample.ask_low
        affected_high = sample.ask_high
        affected_count = sample.ask_count

    return ThinningEvent(
        ts=sample.ts,
        us=sample.us,
        side=side,
        direction=direction,
        price=sample.price,
        aggregate_before=before,
        aggregate_after=after,
        drop_pct=drop_pct,
        size_dropped=size_dropped,
        tape_volume=tape_volume,
        allowed_tape=allowed_tape,
        affected_low=affected_low,
        affected_high=affected_high,
        affected_count=affected_count,
        phase=phase,
    )


def add_follow_through(events: list[ThinningEvent], samples: list[Sample], follow_sec: int) -> None:
    times = [s.us for s in samples]
    for ev in events:
        start_i = bisect.bisect_left(times, ev.us)
        end_i = bisect.bisect_right(times, ev.us + follow_sec * 1_000_000)
        window = samples[start_i:end_i]
        anchor = round(ev.price / TICK_SIZE)

        pre_start_i = bisect.bisect_left(times, ev.us - follow_sec * 1_000_000)
        pre_end_i = bisect.bisect_right(times, ev.us)
        pre_window = samples[pre_start_i:pre_end_i]
        if pre_window:
            if ev.direction == "UP":
                ev.pre60_same_ticks = anchor - min(s.mid_tick for s in pre_window)
                ev.pre60_opp_ticks = max(s.mid_tick for s in pre_window) - anchor
            else:
                ev.pre60_same_ticks = max(s.mid_tick for s in pre_window) - anchor
                ev.pre60_opp_ticks = anchor - min(s.mid_tick for s in pre_window)

        if not window:
            continue
        if ev.direction == "UP":
            ev.follow_ticks = max(s.mid_tick for s in window) - anchor
            ev.adverse_ticks = anchor - min(s.mid_tick for s in window)
        else:
            ev.follow_ticks = anchor - min(s.mid_tick for s in window)
            ev.adverse_ticks = max(s.mid_tick for s in window) - anchor


def add_context(events: list[ThinningEvent], samples: list[Sample], args) -> None:
    if not events or not samples:
        return

    vod = compute_vod_z(samples, args.book_lookback_sec)
    lean_events = compute_lean_events(samples, args.book_lookback_sec, args.event_z_threshold)

    vod_times = [us for us, _ in vod]
    lean_times = [ev.us for ev in lean_events]
    vod_threshold = max(4.0, args.event_z_threshold + 1.0)

    for ev in events:
        lo = bisect.bisect_left(vod_times, ev.us - args.context_overlap_sec * 1_000_000)
        hi = bisect.bisect_right(vod_times, ev.us + args.context_overlap_sec * 1_000_000)
        if lo < hi:
            ev.vod_max_z_5s = max(abs(z) for _, z in vod[lo:hi])
            ev.vod_hit_5s = ev.vod_max_z_5s >= vod_threshold

        apply_first_lean(ev, lean_events, lean_times, args.first_lean_max_sec)
        apply_post_lean(ev, lean_events, lean_times, 30)
        apply_post_lean(ev, lean_events, lean_times, 60)


def compute_vod_z(samples: list[Sample], lookback_sec: int) -> list[tuple[int, float]]:
    inner_deltas: deque[tuple[int, float]] = deque()
    vod_values: deque[tuple[int, float]] = deque()
    vod_z: list[tuple[int, float]] = []
    prev_inner: float | None = None

    for sample in samples:
        curr_inner = sample.bid_inner + sample.ask_inner
        if prev_inner is not None:
            inner_deltas.append((sample.us, curr_inner - prev_inner))
            evict_tuples(inner_deltas, sample.us, lookback_sec * 2)
            if len(inner_deltas) >= 4:
                vod = std_over(inner_deltas, sample.us, lookback_sec)
                vod_values.append((sample.us, vod))
                evict_tuples(vod_values, sample.us, lookback_sec * 8)
                if len(vod_values) >= 8:
                    mean, std = mean_std_over(vod_values, sample.us, lookback_sec * 4)
                    vod_z.append((sample.us, (vod - mean) / max(0.1, std)))
        prev_inner = curr_inner

    return vod_z


def compute_lean_events(samples: list[Sample], lookback_sec: int, z_threshold: float) -> list[LeanEvent]:
    history: deque[Sample] = deque()
    events: list[LeanEvent] = []

    for sample in samples:
        history.append(sample)
        cutoff = sample.us - lookback_sec * 2 * 1_000_000
        while history and history[0].us < cutoff:
            history.popleft()

        if len(history) < 5:
            continue

        window = [s for s in history if s.us >= sample.us - lookback_sec * 1_000_000]
        if len(window) < 5:
            continue

        z_bid_inner = zscore(sample.bid_inner, [s.bid_inner for s in window], 1.0)
        z_ask_inner = zscore(sample.ask_inner, [s.ask_inner for s in window], 1.0)
        z_bid_centroid = zscore(sample.bid_centroid, [s.bid_centroid for s in window], 0.01)
        z_ask_centroid = zscore(sample.ask_centroid, [s.ask_centroid for s in window], 0.01)

        append_lean(events, sample, z_bid_inner, +1, "BID_BUILD", "BID_PULL", z_threshold)
        append_lean(events, sample, z_ask_inner, -1, "ASK_BUILD", "ASK_PULL", z_threshold)
        append_lean(events, sample, z_bid_centroid, -1, "BID_OUT", "BID_IN", z_threshold)
        append_lean(events, sample, z_ask_centroid, +1, "ASK_OUT", "ASK_IN", z_threshold)

    return events


def append_lean(
    events: list[LeanEvent],
    sample: Sample,
    z: float,
    bias_pos: int,
    pos_label: str,
    neg_label: str,
    z_threshold: float,
) -> None:
    abs_z = abs(z)
    if abs_z <= z_threshold:
        return
    bias = bias_pos if z > 0 else -bias_pos
    label = pos_label if z > 0 else neg_label
    events.append(
        LeanEvent(
            ts=sample.ts,
            us=sample.us,
            bias="DEMAND" if bias > 0 else "SUPPLY",
            kind=label,
            z=abs_z,
        )
    )


def apply_post_lean(ev: ThinningEvent, lean_events: list[LeanEvent], lean_times: list[int], seconds: int) -> None:
    lo = bisect.bisect_right(lean_times, ev.us)
    hi = bisect.bisect_right(lean_times, ev.us + seconds * 1_000_000)
    demand = sum(item.z for item in lean_events[lo:hi] if item.bias == "DEMAND")
    supply = sum(item.z for item in lean_events[lo:hi] if item.bias == "SUPPLY")
    lean = classify_lean(demand, supply)
    aligned = classify_alignment(ev.direction, lean)

    if seconds == 30:
        ev.post30_demand = demand
        ev.post30_supply = supply
        ev.post30_lean = lean
        ev.post30_aligned = aligned
    elif seconds == 60:
        ev.post60_demand = demand
        ev.post60_supply = supply
        ev.post60_lean = lean
        ev.post60_aligned = aligned


def apply_first_lean(ev: ThinningEvent, lean_events: list[LeanEvent], lean_times: list[int], seconds: int) -> None:
    lo = bisect.bisect_right(lean_times, ev.us)
    hi = bisect.bisect_right(lean_times, ev.us + seconds * 1_000_000)
    if lo >= hi:
        return

    first = lean_events[lo]
    ev.first_lean_delay_sec = (first.us - ev.us) / 1_000_000
    ev.first_lean_bias = first.bias
    ev.first_lean_kind = first.kind
    ev.first_lean_z = first.z
    ev.first_lean_aligned = classify_alignment(ev.direction, first.bias)


def classify_lean(demand: float, supply: float) -> str:
    stronger = max(demand, supply)
    weaker = min(demand, supply)
    if stronger < 2.5:
        return "NONE"
    if stronger < weaker * 1.15 + 2.5:
        return "MIXED"
    return "DEMAND" if demand > supply else "SUPPLY"


def classify_alignment(direction: str, lean: str) -> str:
    if lean not in {"DEMAND", "SUPPLY"}:
        return lean
    expected = "DEMAND" if direction == "UP" else "SUPPLY"
    return "YES" if lean == expected else "NO"


def zscore(current: float, values: list[float], std_floor: float) -> float:
    mean, std = mean_std(values)
    return (current - mean) / max(std_floor, std)


def mean_std(values: list[float]) -> tuple[float, float]:
    if not values:
        return 0.0, 0.0
    mean = sum(values) / len(values)
    variance = sum((v - mean) * (v - mean) for v in values) / len(values)
    return mean, math.sqrt(max(0.0, variance))


def std_over(values: deque[tuple[int, float]], now_us: int, seconds: int) -> float:
    _, std = mean_std([value for us, value in values if us >= now_us - seconds * 1_000_000])
    return std


def mean_std_over(values: deque[tuple[int, float]], now_us: int, seconds: int) -> tuple[float, float]:
    return mean_std([value for us, value in values if us >= now_us - seconds * 1_000_000])


def evict_tuples(values: deque[tuple[int, float]], now_us: int, seconds: int) -> None:
    cutoff = now_us - seconds * 1_000_000
    while values and values[0][0] < cutoff:
        values.popleft()


def write_outputs(day: str, events: list[ThinningEvent], args) -> tuple[Path, Path]:
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    suffix = (
        f"{day}_skurry_book_thinning"
        f"_n{args.top_n_levels}"
        f"_w{args.window_sec}"
        f"_drop{str(args.thinning_percent).replace('.', 'p')}"
        f"_tape{str(args.tape_volume_floor).replace('.', 'p')}"
    )
    if not args.phase_gate:
        suffix += "_no_phase_gate"
    if args.window:
        suffix += "_" + args.window.replace(":", "").replace("-", "_")

    txt = out_dir / f"{suffix}.txt"
    csv = out_dir / f"{suffix}.csv"

    ranked = sorted(events, key=lambda e: (e.size_dropped, e.drop_pct, e.follow_ticks), reverse=True)
    with txt.open("w", encoding="utf-8") as f:
        f.write(
            f"{day} {args.symbol_dir} candidate=skurry-book-thinning "
            f"top_n={args.top_n_levels} window={args.window_sec}s "
            f"drop_pct>={args.thinning_percent} tape_floor={args.tape_volume_floor} "
            f"cooldown={args.cooldown_sec}s phase_gate={args.phase_gate}\n"
        )
        f.write(f"fires={len(events)} shown={min(args.top, len(events))}\n\n")
        f.write(
            "time      phase      dir  side price     affected_range     before after "
            "dropPct drop tape allowed ratio pre same/opp follow adverse vod5 vod? first post30 post60\n"
        )
        for ev in ranked[: args.top]:
            f.write(
                f"{ny_hms(ev.ts)} {ev.phase:<10} {ev.direction:<4} {ev.side:<4} "
                f"{ev.price:8.2f} {ev.affected_low:8.2f}-{ev.affected_high:<8.2f} "
                f"{ev.aggregate_before:6.1f} {ev.aggregate_after:5.1f} "
                f"{ev.drop_pct:7.3f} {ev.size_dropped:5.1f} {ev.tape_volume:4.0f} "
                f"{ev.allowed_tape:7.1f} {ev.tape_ratio:5.2f} "
                f"{ev.pre60_same_ticks:4d}/{ev.pre60_opp_ticks:<3d} "
                f"{ev.follow_ticks:6d} {ev.adverse_ticks:7d} "
                f"{ev.vod_max_z_5s:4.1f} {'Y' if ev.vod_hit_5s else 'n':>4} "
                f"{ev.first_lean_bias:<6}/{ev.first_lean_aligned:<5} "
                f"{ev.post30_lean:<6}/{ev.post30_aligned:<5} "
                f"{ev.post60_lean:<6}/{ev.post60_aligned:<5}\n"
            )

    with csv.open("w", encoding="utf-8") as f:
        f.write(
            "date,time,phase,direction,side,price,affected_low,affected_high,affected_count,"
            "aggregate_before,aggregate_after,drop_pct,size_dropped,tape_volume,allowed_tape,"
            "tape_ratio,pre60_same_ticks,pre60_opp_ticks,follow_ticks,adverse_ticks,"
            "vod_max_z_5s,vod_hit_5s,"
            "first_lean_delay_sec,first_lean_bias,first_lean_kind,first_lean_z,first_lean_aligned,"
            "post30_demand,post30_supply,post30_lean,post30_aligned,"
            "post60_demand,post60_supply,post60_lean,post60_aligned\n"
        )
        for ev in events:
            f.write(
                f"{day},{ny_hms(ev.ts)},{ev.phase},{ev.direction},{ev.side},{ev.price:.2f},"
                f"{ev.affected_low:.2f},{ev.affected_high:.2f},{ev.affected_count},"
                f"{ev.aggregate_before:.1f},{ev.aggregate_after:.1f},{ev.drop_pct:.3f},"
                f"{ev.size_dropped:.1f},{ev.tape_volume:.1f},{ev.allowed_tape:.1f},"
                f"{ev.tape_ratio:.3f},{ev.pre60_same_ticks},{ev.pre60_opp_ticks},"
                f"{ev.follow_ticks},{ev.adverse_ticks},"
                f"{ev.vod_max_z_5s:.3f},{1 if ev.vod_hit_5s else 0},"
                f"{ev.first_lean_delay_sec:.3f},{ev.first_lean_bias},{ev.first_lean_kind},"
                f"{ev.first_lean_z:.3f},{ev.first_lean_aligned},"
                f"{ev.post30_demand:.3f},{ev.post30_supply:.3f},{ev.post30_lean},{ev.post30_aligned},"
                f"{ev.post60_demand:.3f},{ev.post60_supply:.3f},{ev.post60_lean},{ev.post60_aligned}\n"
            )

    return txt, csv


def run_day(day: str, args) -> None:
    events, _ = replay(day, args)
    txt, csv = write_outputs(day, events, args)
    print(f"{day}: fires={len(events)}")
    print(f"  {txt}")
    print(f"  {csv}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", action="append", required=True)
    parser.add_argument("--symbol-dir", default=os.environ.get("SYMBOL_DIR", "NQM6"))
    parser.add_argument("--window", help="NY time window, e.g. 10:30-15:00")
    parser.add_argument("--warmup-min", type=int, default=5)
    parser.add_argument("--top-n-levels", type=int, default=20)
    parser.add_argument("--window-sec", type=int, default=5)
    parser.add_argument("--thinning-percent", type=float, default=0.25)
    parser.add_argument("--tape-volume-floor", type=float, default=0.20)
    parser.add_argument("--cooldown-sec", type=int, default=30)
    parser.add_argument("--phase-gate", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--follow-sec", type=int, default=60)
    parser.add_argument("--book-lookback-sec", type=int, default=30)
    parser.add_argument("--event-z-threshold", type=float, default=2.5)
    parser.add_argument("--context-overlap-sec", type=int, default=5)
    parser.add_argument("--first-lean-max-sec", type=int, default=30)
    parser.add_argument("--top", type=int, default=80)
    parser.add_argument("--out-dir", default=r"C:\Heatmap\research\out")
    args = parser.parse_args()

    for day in args.date:
        run_day(day, args)


if __name__ == "__main__":
    main()
