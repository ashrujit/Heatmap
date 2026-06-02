"""Replay Skurry QI/TFI pressure grammar against MarketRecorder captures.

Research-only. This mirrors the Skurry PressureAccumulator definitions closely
enough for auction review:

- QI: top-N depth-weighted queue imbalance, per-level clipped by an adaptive
  saturation estimate;
- TFI: signed tape-flow EWMA with time decay;
- divergence: visible book pressure and recent aggressive flow point in
  opposite directions.

The script collapses samples into intervals so we can discuss chart areas
instead of rendering a historical HUD.
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
class BookFrame:
    ts: datetime
    us: int
    mid_tick: int
    qi: float
    saturation: float


@dataclass(frozen=True)
class PressureSample:
    ts: datetime
    us: int
    mid_tick: int
    qi: float
    tfi: float
    gap: float
    state: str


@dataclass
class PressureInterval:
    day: str
    state: str
    start_ts: datetime
    end_ts: datetime
    start_us: int
    end_us: int
    start_tick: int
    end_tick: int
    q_sign: int
    t_sign: int
    max_gap: float
    avg_qi: float
    avg_tfi: float
    samples: int
    pre60_q_ticks: int = 0
    pre60_t_ticks: int = 0
    q_follow_ticks: int = 0
    q_adverse_ticks: int = 0
    t_follow_ticks: int = 0
    t_adverse_ticks: int = 0

    @property
    def duration_sec(self) -> float:
        return max(0.0, (self.end_us - self.start_us) / 1_000_000)

    @property
    def q_label(self) -> str:
        return direction_label(self.q_sign)

    @property
    def t_label(self) -> str:
        return direction_label(self.t_sign)


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


def direction_label(sign: int) -> str:
    if sign > 0:
        return "DEMAND"
    if sign < 0:
        return "SUPPLY"
    return "NONE"


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


def replay(day: str, args) -> tuple[list[PressureInterval], list[PressureSample]]:
    start, end = parse_window(day, args.window)
    snap, ticks = load_data(day, args.symbol_dir, start, end, args.warmup_min)

    weights = [math.exp(-args.qi_decay_lambda * i) for i in range(args.qi_depth_levels)]
    frames = build_book_frames(snap, weights, args)
    samples = sample_pressure(frames, ticks, start, end, args)
    intervals = collapse_intervals(day, samples, args)
    add_movement_context(intervals, samples, args.follow_sec)
    return intervals, samples


def build_book_frames(snap: pl.DataFrame, weights: list[float], args) -> list[BookFrame]:
    frames: list[BookFrame] = []
    sat_values: list[float] = []
    sat_window: deque[tuple[int, list[float]]] = deque()

    for row in snap.iter_rows(named=True):
        us = int(row["timestamp_us"])
        sizes = positive_sizes(row)
        if sizes:
            sat_window.append((us, sizes))
            for size in sizes:
                bisect.insort(sat_values, size)
        evict_saturation(sat_window, sat_values, us, args.saturation_window_sec)

        saturation = percentile_sorted(sat_values, args.saturation_percentile) if sat_values else args.fallback_saturation
        saturation = max(1.0, saturation)
        qi = compute_qi(row, weights, saturation)
        frames.append(
            BookFrame(
                ts=datetime.fromtimestamp(us / 1_000_000, tz=timezone.utc),
                us=us,
                mid_tick=int(row["ref_tick"]),
                qi=qi,
                saturation=saturation,
            )
        )

    return frames


def positive_sizes(row: dict) -> list[float]:
    sizes: list[float] = []
    for i in range(MAX_LEVELS):
        bid = float(row[f"bid_size_{i}"])
        ask = float(row[f"ask_size_{i}"])
        if math.isfinite(bid) and bid > 0:
            sizes.append(bid)
        if math.isfinite(ask) and ask > 0:
            sizes.append(ask)
    return sizes


def evict_saturation(window: deque[tuple[int, list[float]]], values: list[float], now_us: int, seconds: int) -> None:
    cutoff = now_us - seconds * 1_000_000
    while window and window[0][0] < cutoff:
        _, sizes = window.popleft()
        for size in sizes:
            idx = bisect.bisect_left(values, size)
            if idx < len(values):
                values.pop(idx)


def percentile_sorted(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    pct = min(1.0, max(0.0, pct))
    idx = min(len(values) - 1, max(0, int(math.ceil(pct * len(values)) - 1)))
    return values[idx]


def compute_qi(row: dict, weights: list[float], saturation: float) -> float:
    bid_sum = 0.0
    ask_sum = 0.0
    for i, weight in enumerate(weights[:MAX_LEVELS]):
        bid = float(row[f"bid_size_{i}"])
        ask = float(row[f"ask_size_{i}"])
        if math.isfinite(bid) and bid > 0:
            bid_sum += weight * min(bid, saturation)
        if math.isfinite(ask) and ask > 0:
            ask_sum += weight * min(ask, saturation)
    denom = bid_sum + ask_sum
    return 0.0 if denom <= 0 else (bid_sum - ask_sum) / denom


def sample_pressure(
    frames: list[BookFrame],
    ticks: pl.DataFrame,
    start: datetime,
    end: datetime,
    args,
) -> list[PressureSample]:
    if not frames:
        return []

    start_us = int(start.timestamp() * 1_000_000)
    end_us = int(end.timestamp() * 1_000_000)
    first_us = frames[0].us
    sample_step_us = args.sample_ms * 1_000
    half_life_tau = args.tfi_half_life_sec / math.log(2)

    frame_times = [frame.us for frame in frames]
    tick_rows = ticks.sort("timestamp_us").iter_rows(named=True)
    tick_iter = iter(tick_rows)
    current_tick = next(tick_iter, None)

    tfi = 0.0
    last_sample_us: int | None = None
    samples: list[PressureSample] = []
    sample_us = first_us

    while sample_us <= end_us:
        buy_vol = 0.0
        sell_vol = 0.0
        while current_tick is not None and int(current_tick["timestamp_us"]) <= sample_us:
            size = float(current_tick["size"])
            sign = int(current_tick["aggressor_sign"])
            if math.isfinite(size) and size > 0:
                if sign > 0:
                    buy_vol += size
                elif sign < 0:
                    sell_vol += size
            current_tick = next(tick_iter, None)

        if last_sample_us is None:
            if buy_vol + sell_vol > 0:
                tfi = (buy_vol - sell_vol) / (buy_vol + sell_vol)
        else:
            dt = max(0.0, (sample_us - last_sample_us) / 1_000_000)
            decay = math.exp(-dt / half_life_tau) if dt > 0 else 1.0
            if buy_vol + sell_vol > 0:
                sample = (buy_vol - sell_vol) / (buy_vol + sell_vol)
                tfi = decay * tfi + (1.0 - decay) * sample
            else:
                tfi = decay * tfi
        last_sample_us = sample_us

        frame_idx = bisect.bisect_right(frame_times, sample_us) - 1
        if frame_idx >= 0 and sample_us >= start_us:
            frame = frames[frame_idx]
            warmed = sample_us - first_us >= int(2.0 * args.tfi_half_life_sec * 1_000_000)
            if warmed:
                state = classify_state(frame.qi, tfi, args)
                samples.append(
                    PressureSample(
                        ts=datetime.fromtimestamp(sample_us / 1_000_000, tz=timezone.utc),
                        us=sample_us,
                        mid_tick=frame.mid_tick,
                        qi=frame.qi,
                        tfi=tfi,
                        gap=abs(frame.qi - tfi),
                        state=state,
                    )
                )

        sample_us += sample_step_us

    return samples


def classify_state(qi: float, tfi: float, args) -> str:
    q_active = abs(qi) >= args.neutral_threshold
    t_active = abs(tfi) >= args.neutral_threshold
    q_sign = sign(qi)
    t_sign = sign(tfi)

    if q_active and t_active and q_sign == t_sign:
        return "ALIGN_DEMAND" if q_sign > 0 else "ALIGN_SUPPLY"
    if q_active and t_active and q_sign != t_sign:
        prefix = "DIVERGE" if abs(qi - tfi) >= args.divergence_gap else "OPPOSE"
        if q_sign > 0:
            return f"{prefix}_QI_DEMAND_TFI_SUPPLY"
        return f"{prefix}_QI_SUPPLY_TFI_DEMAND"
    if q_active:
        return "BOOK_DEMAND" if q_sign > 0 else "BOOK_SUPPLY"
    if t_active:
        return "TAPE_DEMAND" if t_sign > 0 else "TAPE_SUPPLY"
    return "NEUTRAL"


def collapse_intervals(day: str, samples: list[PressureSample], args) -> list[PressureInterval]:
    intervals: list[PressureInterval] = []
    if not samples:
        return intervals

    start = samples[0]
    bucket: list[PressureSample] = [start]
    for sample in samples[1:]:
        if sample.state == start.state:
            bucket.append(sample)
            continue
        maybe_add_interval(day, intervals, start, bucket[-1], bucket, args)
        start = sample
        bucket = [sample]
    maybe_add_interval(day, intervals, start, bucket[-1], bucket, args)
    return intervals


def maybe_add_interval(
    day: str,
    intervals: list[PressureInterval],
    start: PressureSample,
    end: PressureSample,
    bucket: list[PressureSample],
    args,
) -> None:
    duration = (end.us - start.us) / 1_000_000
    if duration < args.min_state_sec:
        return
    if args.only_material and not (start.state.startswith("DIVERGE") or start.state.startswith("ALIGN")):
        return

    avg_qi = sum(s.qi for s in bucket) / len(bucket)
    avg_tfi = sum(s.tfi for s in bucket) / len(bucket)
    intervals.append(
        PressureInterval(
            day=day,
            state=start.state,
            start_ts=start.ts,
            end_ts=end.ts,
            start_us=start.us,
            end_us=end.us,
            start_tick=start.mid_tick,
            end_tick=end.mid_tick,
            q_sign=sign(avg_qi),
            t_sign=sign(avg_tfi),
            max_gap=max(s.gap for s in bucket),
            avg_qi=avg_qi,
            avg_tfi=avg_tfi,
            samples=len(bucket),
        )
    )


def add_movement_context(intervals: list[PressureInterval], samples: list[PressureSample], follow_sec: int) -> None:
    times = [s.us for s in samples]
    for interval in intervals:
        start_idx = bisect.bisect_left(times, interval.start_us)
        follow_idx = bisect.bisect_right(times, interval.start_us + follow_sec * 1_000_000)
        pre_idx = bisect.bisect_left(times, interval.start_us - follow_sec * 1_000_000)
        pre_window = samples[pre_idx:start_idx + 1]
        follow_window = samples[start_idx:follow_idx]
        if pre_window:
            interval.pre60_q_ticks = move_in_direction(pre_window, interval.start_tick, interval.q_sign)
            interval.pre60_t_ticks = move_in_direction(pre_window, interval.start_tick, interval.t_sign)
        if follow_window:
            interval.q_follow_ticks = move_in_direction(follow_window, interval.start_tick, interval.q_sign)
            interval.q_adverse_ticks = move_against_direction(follow_window, interval.start_tick, interval.q_sign)
            interval.t_follow_ticks = move_in_direction(follow_window, interval.start_tick, interval.t_sign)
            interval.t_adverse_ticks = move_against_direction(follow_window, interval.start_tick, interval.t_sign)


def move_in_direction(samples: list[PressureSample], anchor: int, direction: int) -> int:
    if direction > 0:
        return max(s.mid_tick for s in samples) - anchor
    if direction < 0:
        return anchor - min(s.mid_tick for s in samples)
    return 0


def move_against_direction(samples: list[PressureSample], anchor: int, direction: int) -> int:
    if direction > 0:
        return anchor - min(s.mid_tick for s in samples)
    if direction < 0:
        return max(s.mid_tick for s in samples) - anchor
    return 0


def sign(value: float) -> int:
    if value > 0:
        return 1
    if value < 0:
        return -1
    return 0


def write_outputs(day: str, intervals: list[PressureInterval], samples: list[PressureSample], args) -> tuple[Path, Path]:
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    suffix = (
        f"{day}_qitfi"
        f"_n{args.qi_depth_levels}"
        f"_lambda{str(args.qi_decay_lambda).replace('.', 'p')}"
        f"_hl{str(args.tfi_half_life_sec).replace('.', 'p')}"
        f"_gap{str(args.divergence_gap).replace('.', 'p')}"
    )
    if args.window:
        suffix += "_" + args.window.replace(":", "").replace("-", "_")

    txt = out_dir / f"{suffix}.txt"
    csv = out_dir / f"{suffix}.csv"

    divergences = [iv for iv in intervals if iv.state.startswith("DIVERGE")]
    aligns = [iv for iv in intervals if iv.state.startswith("ALIGN")]
    ranked_divergences = sorted(divergences, key=lambda iv: (iv.duration_sec, iv.max_gap), reverse=True)
    ranked_aligns = sorted(aligns, key=lambda iv: (iv.duration_sec, abs(iv.avg_qi) + abs(iv.avg_tfi)), reverse=True)

    with txt.open("w", encoding="utf-8") as f:
        f.write(
            f"{day} {args.symbol_dir} candidate=qitfi-divergence "
            f"sample_ms={args.sample_ms} qi_n={args.qi_depth_levels} "
            f"lambda={args.qi_decay_lambda} tfi_half_life={args.tfi_half_life_sec}s "
            f"neutral={args.neutral_threshold} divergence_gap={args.divergence_gap} "
            f"min_state={args.min_state_sec}s\n"
        )
        f.write(
            f"samples={len(samples)} intervals={len(intervals)} "
            f"divergence_intervals={len(divergences)} align_intervals={len(aligns)}\n\n"
        )
        write_sample_summary(f, samples, args)
        f.write("\n")
        f.write("DIVERGENCE intervals\n")
        write_interval_table(f, ranked_divergences[: args.top])
        f.write("\nALIGN intervals\n")
        write_interval_table(f, ranked_aligns[: args.top])

    with csv.open("w", encoding="utf-8") as f:
        f.write(
            "date,start,end,phase,state,duration_sec,start_price,end_price,"
            "q_label,t_label,avg_qi,avg_tfi,max_gap,pre60_q_ticks,pre60_t_ticks,"
            "q_follow_ticks,q_adverse_ticks,t_follow_ticks,t_adverse_ticks,samples\n"
        )
        for iv in intervals:
            f.write(
                f"{iv.day},{ny_hms(iv.start_ts)},{ny_hms(iv.end_ts)},{phase_name(iv.start_ts)},"
                f"{iv.state},{iv.duration_sec:.1f},{iv.start_tick * TICK_SIZE:.2f},"
                f"{iv.end_tick * TICK_SIZE:.2f},{iv.q_label},{iv.t_label},"
                f"{iv.avg_qi:.3f},{iv.avg_tfi:.3f},{iv.max_gap:.3f},"
                f"{iv.pre60_q_ticks},{iv.pre60_t_ticks},{iv.q_follow_ticks},"
                f"{iv.q_adverse_ticks},{iv.t_follow_ticks},{iv.t_adverse_ticks},{iv.samples}\n"
            )

    return txt, csv


def write_sample_summary(f, samples: list[PressureSample], args) -> None:
    if not samples:
        f.write("sample summary: none\n")
        return
    abs_qi = sorted(abs(s.qi) for s in samples)
    abs_tfi = sorted(abs(s.tfi) for s in samples)
    gaps = sorted(s.gap for s in samples)
    active_q = sum(1 for s in samples if abs(s.qi) >= args.neutral_threshold)
    active_t = sum(1 for s in samples if abs(s.tfi) >= args.neutral_threshold)
    both_active = sum(1 for s in samples if abs(s.qi) >= args.neutral_threshold and abs(s.tfi) >= args.neutral_threshold)
    opposite = sum(
        1
        for s in samples
        if abs(s.qi) >= args.neutral_threshold
        and abs(s.tfi) >= args.neutral_threshold
        and sign(s.qi) != sign(s.tfi)
    )
    wide = sum(1 for s in samples if s.gap >= args.divergence_gap)
    f.write(
        "sample summary:\n"
        f"  |QI|  p50={pct(abs_qi, 0.50):.3f} p75={pct(abs_qi, 0.75):.3f} "
        f"p90={pct(abs_qi, 0.90):.3f} p95={pct(abs_qi, 0.95):.3f} p99={pct(abs_qi, 0.99):.3f}\n"
        f"  |TFI| p50={pct(abs_tfi, 0.50):.3f} p75={pct(abs_tfi, 0.75):.3f} "
        f"p90={pct(abs_tfi, 0.90):.3f} p95={pct(abs_tfi, 0.95):.3f} p99={pct(abs_tfi, 0.99):.3f}\n"
        f"  gap   p50={pct(gaps, 0.50):.3f} p75={pct(gaps, 0.75):.3f} "
        f"p90={pct(gaps, 0.90):.3f} p95={pct(gaps, 0.95):.3f} p99={pct(gaps, 0.99):.3f}\n"
        f"  active_q={active_q} active_t={active_t} both_active={both_active} "
        f"opposite={opposite} wide_gap={wide}\n"
    )


def pct(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    idx = min(len(values) - 1, max(0, int(math.ceil(q * len(values)) - 1)))
    return values[idx]


def write_interval_table(f, intervals: list[PressureInterval]) -> None:
    f.write(
        "start    end      phase      state                         dur  price    "
        "qi     tfi    gap   preQ preT  qF/qA  tF/tA\n"
    )
    for iv in intervals:
        f.write(
            f"{ny_hms(iv.start_ts)} {ny_hms(iv.end_ts)} {phase_name(iv.start_ts):<10} "
            f"{iv.state:<29} {iv.duration_sec:4.1f} {iv.start_tick * TICK_SIZE:8.2f} "
            f"{iv.avg_qi:6.3f} {iv.avg_tfi:6.3f} {iv.max_gap:5.3f} "
            f"{iv.pre60_q_ticks:4d} {iv.pre60_t_ticks:4d} "
            f"{iv.q_follow_ticks:3d}/{iv.q_adverse_ticks:<3d} "
            f"{iv.t_follow_ticks:3d}/{iv.t_adverse_ticks:<3d}\n"
        )


def run_day(day: str, args) -> None:
    intervals, samples = replay(day, args)
    txt, csv = write_outputs(day, intervals, samples, args)
    divergences = sum(1 for iv in intervals if iv.state.startswith("DIVERGE"))
    aligns = sum(1 for iv in intervals if iv.state.startswith("ALIGN"))
    print(f"{day}: samples={len(samples)} intervals={len(intervals)} divergences={divergences} aligns={aligns}")
    print(f"  {txt}")
    print(f"  {csv}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", action="append", required=True)
    parser.add_argument("--symbol-dir", default=os.environ.get("SYMBOL_DIR", "NQM6"))
    parser.add_argument("--window", help="NY time window, e.g. 10:30-15:00")
    parser.add_argument("--warmup-min", type=int, default=5)
    parser.add_argument("--sample-ms", type=int, default=200)
    parser.add_argument("--qi-depth-levels", type=int, default=20)
    parser.add_argument("--qi-decay-lambda", type=float, default=0.3)
    parser.add_argument("--tfi-half-life-sec", type=float, default=20.0)
    parser.add_argument("--neutral-threshold", type=float, default=0.20)
    parser.add_argument("--divergence-gap", type=float, default=0.60)
    parser.add_argument("--min-state-sec", type=float, default=2.0)
    parser.add_argument("--only-material", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--saturation-window-sec", type=int, default=300)
    parser.add_argument("--saturation-percentile", type=float, default=0.99)
    parser.add_argument("--fallback-saturation", type=float, default=25.0)
    parser.add_argument("--follow-sec", type=int, default=60)
    parser.add_argument("--top", type=int, default=80)
    parser.add_argument("--out-dir", default=r"C:\Heatmap\research\out")
    args = parser.parse_args()

    for day in args.date:
        run_day(day, args)


if __name__ == "__main__":
    main()
