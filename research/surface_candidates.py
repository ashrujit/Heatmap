"""Replay candidate L2_Surface computations from parquet captures.

This is a research harness, not indicator code.  It intentionally starts
with one candidate at a time so each idea can earn its keep beside the chart.

Current candidate:
  vod-build  -- same-sample VOD + BID/ASK BUILD fingerprint from L2_Surface.
  inflection -- BUILD trigger followed by signed cum/ROC confirmation.
  flow       -- directional event density + RV + inner-depth thinning regime.
  build-bands -- clustered BID/ASK BUILD events promoted into supply/demand zones.
"""

from __future__ import annotations

import argparse
import csv
import math
import os
from collections import deque
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import polars as pl

from capture_loader import load_capture_window, snapshot_columns


TICK_SIZE = 0.25
INNER_LEVELS = 10
BROAD_LEVELS = 30
NY = ZoneInfo("America/New_York")


@dataclass(frozen=True)
class Sample:
    ts: datetime
    mid_tick: int
    bid_inner: float
    ask_inner: float
    bid_centroid: float
    ask_centroid: float


@dataclass(frozen=True)
class VodBuildEvent:
    ts: datetime
    price: float
    mid_tick: int
    side: str
    chaos_side: str
    vod_z: float
    bid_build_z: float
    ask_build_z: float
    inner_total: float
    note: str

    @property
    def strength(self) -> float:
        return max(self.vod_z, 0.0) + max(self.bid_build_z, self.ask_build_z, 0.0)


@dataclass(frozen=True)
class L2Event:
    ts: datetime
    price_tick: int
    kind: str
    bias: int
    abs_z: float


@dataclass
class PendingInflection:
    trigger_ts: datetime
    price_tick: int
    bias: int
    trigger_kind: str
    trigger_z: float
    cum_baseline: float
    best_aligned_cum: float
    best_aligned_roc: float
    best_ts: datetime


@dataclass(frozen=True)
class InflectionResult:
    status: str
    trigger_ts: datetime
    decision_ts: datetime
    price: float
    price_tick: int
    direction: str
    trigger_kind: str
    trigger_z: float
    seconds_to_decision: float
    cum_delta: float
    roc: float
    best_aligned_cum: float
    best_aligned_roc: float


@dataclass(frozen=True)
class FlowMatch:
    ts: datetime
    price: float
    price_tick: int
    direction: str
    bull_count: int
    bear_count: int
    rv: float
    thin_z: float
    inner_total: float


@dataclass(frozen=True)
class FlowSampleMetric:
    ts: datetime
    price: float
    price_tick: int
    bull_count: int
    bear_count: int
    rv: float
    thin_z: float
    inner_total: float
    count_direction: str
    count_ok: bool
    rv_ok: bool
    thin_ok: bool


@dataclass(frozen=True)
class FlowBandResult:
    direction: str
    start_ts: datetime
    end_ts: datetime
    start_price: float
    end_price: float
    duration_sec: float
    match_samples: int
    max_bull_count: int
    max_bear_count: int
    max_rv: float
    min_thin_z: float


@dataclass
class BuildBandState:
    band_id: int
    side: str
    min_tick: int
    max_tick: int
    start_ts: datetime
    formed_ts: datetime
    last_update_ts: datetime
    event_count: int
    max_z: float
    active: bool = True
    clear_ts: datetime | None = None
    clear_price_tick: int | None = None
    clear_reason: str = ""

    @property
    def min_price(self) -> float:
        return self.min_tick * TICK_SIZE

    @property
    def max_price(self) -> float:
        return self.max_tick * TICK_SIZE


@dataclass(frozen=True)
class BuildBandTrace:
    ts: datetime
    price: float
    price_tick: int
    side: str
    action: str
    band_id: int
    z: float
    min_price: float
    max_price: float
    event_count: int
    note: str


def event_side(kind: str) -> str:
    if kind in ("BID_BUILD", "BID_IN", "ASK_OUT", "ASK_PULL"):
        return "D"
    if kind in ("ASK_BUILD", "ASK_IN", "BID_OUT", "BID_PULL"):
        return "S"
    return "."


def ny_dt(day: str, hhmm: str) -> datetime:
    fmt = "%Y-%m-%d %H:%M:%S" if hhmm.count(":") == 2 else "%Y-%m-%d %H:%M"
    return datetime.strptime(f"{day} {hhmm}", fmt).replace(tzinfo=NY)


def parse_window(day: str, window: str | None, rth_only: bool) -> tuple[datetime, datetime]:
    if window:
        start_s, end_s = window.split("-", 1)
        return ny_dt(day, start_s).astimezone(timezone.utc), ny_dt(day, end_s).astimezone(timezone.utc)

    if rth_only:
        start = datetime.combine(datetime.fromisoformat(day).date(), time(9, 30), NY)
        end = datetime.combine(datetime.fromisoformat(day).date(), time(16, 0), NY)
        return start.astimezone(timezone.utc), end.astimezone(timezone.utc)

    start = datetime.combine(datetime.fromisoformat(day).date(), time(0, 0), NY)
    end = start + timedelta(days=1)
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc)


def ny_hms(ts: datetime) -> str:
    return ts.astimezone(NY).strftime("%H:%M:%S")


def mean_std(values: list[float]) -> tuple[float, float]:
    if len(values) < 2:
        return 0.0, 0.0
    mean = sum(values) / len(values)
    var = sum(v * v for v in values) / len(values) - mean * mean
    return mean, math.sqrt(var) if var > 0 else 0.0


def evict_timed(items: deque, now: datetime, seconds: int) -> None:
    cutoff = now - timedelta(seconds=seconds)
    while items and items[0][0] < cutoff:
        items.popleft()


def evict_samples(items: deque[Sample], now: datetime, seconds: int) -> None:
    cutoff = now - timedelta(seconds=seconds)
    while items and items[0].ts < cutoff:
        items.popleft()


def chaos_side(sample: Sample, prev_bid_inner: float | None, prev_ask_inner: float | None) -> str:
    if prev_bid_inner is None or prev_ask_inner is None:
        return "MIXED"
    bid_move = abs(sample.bid_inner - prev_bid_inner)
    ask_move = abs(sample.ask_inner - prev_ask_inner)
    if bid_move <= 0 and ask_move <= 0:
        return "MIXED"
    if bid_move >= ask_move * 1.25:
        return "BID"
    if ask_move >= bid_move * 1.25:
        return "ASK"
    return "MIXED"


def load_snapshots(day: str, symbol_dir: str, start: datetime, end: datetime, warmup_min: int) -> pl.DataFrame:
    load_start = start - timedelta(minutes=max(0, warmup_min))
    return load_capture_window(
        "snapshots",
        symbol_dir,
        load_start,
        end,
        snapshot_columns(BROAD_LEVELS),
        inclusive_end=True,
    )


def build_sample(row: dict) -> Sample:
    bid_inner = 0.0
    ask_inner = 0.0
    for i in range(INNER_LEVELS):
        bs = float(row[f"bid_size_{i}"])
        az = float(row[f"ask_size_{i}"])
        if math.isfinite(bs) and bs > 0:
            bid_inner += bs
        if math.isfinite(az) and az > 0:
            ask_inner += az

    b_wsum = 0.0
    b_size = 0.0
    a_wsum = 0.0
    a_size = 0.0
    for i in range(BROAD_LEVELS):
        bs = float(row[f"bid_size_{i}"])
        az = float(row[f"ask_size_{i}"])
        if math.isfinite(bs) and bs > 0:
            b_wsum += abs(int(row[f"bid_offset_{i}"])) * bs
            b_size += bs
        if math.isfinite(az) and az > 0:
            a_wsum += abs(int(row[f"ask_offset_{i}"])) * az
            a_size += az

    ts = datetime.fromtimestamp(int(row["timestamp_us"]) / 1_000_000, tz=timezone.utc)
    return Sample(
        ts=ts,
        mid_tick=int(row["ref_tick"]),
        bid_inner=bid_inner,
        ask_inner=ask_inner,
        bid_centroid=b_wsum / b_size if b_size > 0 else 0.0,
        ask_centroid=a_wsum / a_size if a_size > 0 else 0.0,
    )


def detect_vod_build(
    rows: pl.DataFrame,
    start: datetime,
    end: datetime,
    lookback_sec: int,
    event_z: float,
    vod_z_threshold: float,
    build_z_threshold: float,
) -> list[VodBuildEvent]:
    samples: deque[Sample] = deque()
    inner_deltas: deque[tuple[datetime, float]] = deque()
    vod_values: deque[tuple[datetime, float]] = deque()
    prev_inner: float | None = None
    prev_bid_inner: float | None = None
    prev_ask_inner: float | None = None
    out: list[VodBuildEvent] = []

    for row in rows.iter_rows(named=True):
        sample = build_sample(row)
        now = sample.ts
        samples.append(sample)
        evict_samples(samples, now, lookback_sec * 2)

        if len(samples) < 5:
            prev_inner = sample.bid_inner + sample.ask_inner
            prev_bid_inner = sample.bid_inner
            prev_ask_inner = sample.ask_inner
            continue

        def z_of(selector, floor: float) -> float:
            vals = [selector(s) for s in samples if s.ts >= now - timedelta(seconds=lookback_sec)]
            mean, std = mean_std(vals)
            return (selector(sample) - mean) / max(floor, std)

        z_bi = z_of(lambda s: s.bid_inner, 1.0)
        z_ai = z_of(lambda s: s.ask_inner, 1.0)

        this_builds: list[tuple[str, float]] = []
        if z_bi > max(event_z, build_z_threshold):
            this_builds.append(("BID_BUILD", z_bi))
        if z_ai > max(event_z, build_z_threshold):
            this_builds.append(("ASK_BUILD", z_ai))

        curr_inner = sample.bid_inner + sample.ask_inner
        z_vod = float("nan")
        if prev_inner is not None:
            inner_deltas.append((now, curr_inner - prev_inner))
            evict_timed(inner_deltas, now, lookback_sec * 2)
            if len(inner_deltas) >= 4:
                recent = [v for t, v in inner_deltas if t >= now - timedelta(seconds=lookback_sec)]
                _, vod = mean_std(recent)
                vod_values.append((now, vod))
                evict_timed(vod_values, now, lookback_sec * 8)
                if len(vod_values) >= 8:
                    baseline = [v for t, v in vod_values if t >= now - timedelta(seconds=lookback_sec * 4)]
                    m, s = mean_std(baseline)
                    z_vod = (vod - m) / max(0.1, s)

        side_hint = chaos_side(sample, prev_bid_inner, prev_ask_inner)
        prev_inner = curr_inner
        prev_bid_inner = sample.bid_inner
        prev_ask_inner = sample.ask_inner

        if now < start or now > end:
            continue
        if not this_builds or not math.isfinite(z_vod) or z_vod < max(event_z, vod_z_threshold):
            continue

        bid_z = max((z for kind, z in this_builds if kind == "BID_BUILD"), default=0.0)
        ask_z = max((z for kind, z in this_builds if kind == "ASK_BUILD"), default=0.0)
        if bid_z > 0 and ask_z > 0:
            side = "MIXED"
        elif bid_z > 0:
            side = "BID_BUILD"
        else:
            side = "ASK_BUILD"

        note = " + ".join([f"{kind} z={z:.2f}" for kind, z in this_builds])
        out.append(
            VodBuildEvent(
                ts=now,
                price=sample.mid_tick * TICK_SIZE,
                mid_tick=sample.mid_tick,
                side=side,
                chaos_side=side_hint,
                vod_z=z_vod,
                bid_build_z=bid_z,
                ask_build_z=ask_z,
                inner_total=curr_inner,
                note=f"VOD z={z_vod:.2f} + {note}",
            )
        )

    return out


def fire_l2_event(ts: datetime, price_tick: int, z: float, bias_pos: int, pos_kind: str, neg_kind: str, event_z: float) -> L2Event | None:
    if abs(z) <= event_z:
        return None
    bias = bias_pos if z > 0 else -bias_pos
    kind = pos_kind if z > 0 else neg_kind
    return L2Event(ts=ts, price_tick=price_tick, kind=kind, bias=bias, abs_z=abs(z))


def sum_weights_over(events: deque[L2Event], now: datetime, seconds: int) -> float:
    cutoff = now - timedelta(seconds=seconds)
    return sum(ev.bias * ev.abs_z for ev in events if ev.ts >= cutoff)


def detect_inflections(
    rows: pl.DataFrame,
    start: datetime,
    end: datetime,
    lookback_sec: int,
    event_z: float,
    trigger_build_z: float,
    cum_threshold: float,
    roc_threshold: float,
    confirmation_window_sec: int,
    roc_window_sec: int,
    cum_window_sec: int,
) -> tuple[list[InflectionResult], list[InflectionResult], list[L2Event]]:
    samples: deque[Sample] = deque()
    events: deque[L2Event] = deque()
    pending: list[PendingInflection] = []
    confirmed: list[InflectionResult] = []
    decisions: list[InflectionResult] = []
    visible_events: list[L2Event] = []

    for row in rows.iter_rows(named=True):
        sample = build_sample(row)
        now = sample.ts
        samples.append(sample)
        evict_samples(samples, now, lookback_sec * 2)
        while events and events[0].ts < now - timedelta(seconds=cum_window_sec * 2):
            events.popleft()

        if len(samples) < 5:
            continue

        def z_of(selector, floor: float) -> float:
            vals = [selector(s) for s in samples if s.ts >= now - timedelta(seconds=lookback_sec)]
            mean, std = mean_std(vals)
            return (selector(sample) - mean) / max(floor, std)

        z_bi = z_of(lambda s: s.bid_inner, 1.0)
        z_ai = z_of(lambda s: s.ask_inner, 1.0)
        z_bc = z_of(lambda s: s.bid_centroid, 0.01)
        z_ac = z_of(lambda s: s.ask_centroid, 0.01)

        this_sample: list[L2Event] = []
        for ev in (
            fire_l2_event(now, sample.mid_tick, z_bi, +1, "BID_BUILD", "BID_PULL", event_z),
            fire_l2_event(now, sample.mid_tick, z_ai, -1, "ASK_BUILD", "ASK_PULL", event_z),
            fire_l2_event(now, sample.mid_tick, z_bc, -1, "BID_OUT", "BID_IN", event_z),
            fire_l2_event(now, sample.mid_tick, z_ac, +1, "ASK_OUT", "ASK_IN", event_z),
        ):
            if ev is None:
                continue
            events.append(ev)
            this_sample.append(ev)
            if start <= now <= end:
                visible_events.append(ev)

        current_cum = sum_weights_over(events, now, cum_window_sec)
        current_roc = sum_weights_over(events, now, roc_window_sec)

        for ev in this_sample:
            if ev.kind not in ("BID_BUILD", "ASK_BUILD"):
                continue
            if ev.abs_z < trigger_build_z:
                continue
            pending.append(
                PendingInflection(
                    trigger_ts=now,
                    price_tick=sample.mid_tick,
                    bias=ev.bias,
                    trigger_kind=ev.kind,
                    trigger_z=ev.abs_z,
                    cum_baseline=current_cum - (ev.bias * ev.abs_z),
                    best_aligned_cum=0.0,
                    best_aligned_roc=ev.bias * current_roc,
                    best_ts=now,
                )
            )

        for idx in range(len(pending) - 1, -1, -1):
            p = pending[idx]
            delta_cum = current_cum - p.cum_baseline
            aligned_cum = p.bias * delta_cum
            aligned_roc = p.bias * current_roc
            if aligned_cum + aligned_roc > p.best_aligned_cum + p.best_aligned_roc:
                p.best_aligned_cum = aligned_cum
                p.best_aligned_roc = aligned_roc
                p.best_ts = now

            age = (now - p.trigger_ts).total_seconds()
            if age > confirmation_window_sec:
                if start <= p.trigger_ts <= end:
                    decisions.append(
                        InflectionResult(
                            status="DROPPED",
                            trigger_ts=p.trigger_ts,
                            decision_ts=now,
                            price=p.price_tick * TICK_SIZE,
                            price_tick=p.price_tick,
                            direction="UP" if p.bias > 0 else "DOWN",
                            trigger_kind=p.trigger_kind,
                            trigger_z=p.trigger_z,
                            seconds_to_decision=age,
                            cum_delta=delta_cum,
                            roc=current_roc,
                            best_aligned_cum=p.best_aligned_cum,
                            best_aligned_roc=p.best_aligned_roc,
                        )
                    )
                pending.pop(idx)
                continue

            cum_ok = aligned_cum >= cum_threshold
            roc_ok = aligned_roc >= roc_threshold
            if cum_ok and roc_ok:
                result = InflectionResult(
                    status="CONFIRMED",
                    trigger_ts=p.trigger_ts,
                    decision_ts=now,
                    price=p.price_tick * TICK_SIZE,
                    price_tick=p.price_tick,
                    direction="UP" if p.bias > 0 else "DOWN",
                    trigger_kind=p.trigger_kind,
                    trigger_z=p.trigger_z,
                    seconds_to_decision=age,
                    cum_delta=delta_cum,
                    roc=current_roc,
                    best_aligned_cum=max(p.best_aligned_cum, aligned_cum),
                    best_aligned_roc=max(p.best_aligned_roc, aligned_roc),
                )
                if start <= p.trigger_ts <= end:
                    confirmed.append(result)
                    decisions.append(result)
                pending.pop(idx)

    for p in pending:
        if start <= p.trigger_ts <= end:
            decisions.append(
                InflectionResult(
                    status="OPEN",
                    trigger_ts=p.trigger_ts,
                    decision_ts=end,
                    price=p.price_tick * TICK_SIZE,
                    price_tick=p.price_tick,
                    direction="UP" if p.bias > 0 else "DOWN",
                    trigger_kind=p.trigger_kind,
                    trigger_z=p.trigger_z,
                    seconds_to_decision=(end - p.trigger_ts).total_seconds(),
                    cum_delta=0.0,
                    roc=0.0,
                    best_aligned_cum=p.best_aligned_cum,
                    best_aligned_roc=p.best_aligned_roc,
                )
            )

    confirmed.sort(key=lambda r: (r.trigger_ts, r.decision_ts))
    decisions.sort(key=lambda r: (r.trigger_ts, r.decision_ts))
    return confirmed, decisions, visible_events


def sum_values_over(values: deque[tuple[datetime, float]], now: datetime, seconds: int) -> float:
    cutoff = now - timedelta(seconds=seconds)
    return sum(v for t, v in values if t >= cutoff)


def detect_flow(
    rows: pl.DataFrame,
    start: datetime,
    end: datetime,
    lookback_sec: int,
    event_z: float,
    band_window_sec: int,
    band_event_count: int,
    band_rv_threshold: float,
    band_inner_thin_z: float,
    band_sustain_sec: int,
    band_cooldown_sec: int,
) -> tuple[list[FlowBandResult], list[FlowMatch], list[FlowSampleMetric], list[L2Event]]:
    samples: deque[Sample] = deque()
    events: deque[L2Event] = deque()
    mid_rets2: deque[tuple[datetime, float]] = deque()
    visible_events: list[L2Event] = []
    matches: list[FlowMatch] = []
    sample_metrics: list[FlowSampleMetric] = []
    bands: list[FlowBandResult] = []

    prev_mid_price: float | None = None
    state = "NONE"
    match_start: datetime | None = None
    match_start_price: float | None = None
    last_match_time: datetime | None = None
    open_band: dict | None = None

    def close_band(close_time: datetime | None) -> None:
        nonlocal open_band
        if open_band is None:
            return
        end_ts = close_time or open_band["last_ts"]
        duration = max(0.0, (end_ts - open_band["start_ts"]).total_seconds())
        bands.append(
            FlowBandResult(
                direction=open_band["direction"],
                start_ts=open_band["start_ts"],
                end_ts=end_ts,
                start_price=open_band["start_price"],
                end_price=open_band["last_price"],
                duration_sec=duration,
                match_samples=open_band["match_samples"],
                max_bull_count=open_band["max_bull_count"],
                max_bear_count=open_band["max_bear_count"],
                max_rv=open_band["max_rv"],
                min_thin_z=open_band["min_thin_z"],
            )
        )
        open_band = None

    for row in rows.iter_rows(named=True):
        sample = build_sample(row)
        now = sample.ts
        mid_price = sample.mid_tick * TICK_SIZE
        samples.append(sample)
        evict_samples(samples, now, lookback_sec * 2)
        while events and events[0].ts < now - timedelta(seconds=max(lookback_sec * 2, band_window_sec * 2)):
            events.popleft()
        evict_timed(mid_rets2, now, max(90, band_window_sec * 3))

        if prev_mid_price is not None and prev_mid_price > 0 and mid_price > 0:
            r = math.log(mid_price / prev_mid_price)
            mid_rets2.append((now, r * r))
        prev_mid_price = mid_price

        if len(samples) < 5:
            continue

        def z_of(selector, floor: float) -> float:
            vals = [selector(s) for s in samples if s.ts >= now - timedelta(seconds=lookback_sec)]
            mean, std = mean_std(vals)
            return (selector(sample) - mean) / max(floor, std)

        z_bi = z_of(lambda s: s.bid_inner, 1.0)
        z_ai = z_of(lambda s: s.ask_inner, 1.0)
        z_bc = z_of(lambda s: s.bid_centroid, 0.01)
        z_ac = z_of(lambda s: s.ask_centroid, 0.01)

        for ev in (
            fire_l2_event(now, sample.mid_tick, z_bi, +1, "BID_BUILD", "BID_PULL", event_z),
            fire_l2_event(now, sample.mid_tick, z_ai, -1, "ASK_BUILD", "ASK_PULL", event_z),
            fire_l2_event(now, sample.mid_tick, z_bc, -1, "BID_OUT", "BID_IN", event_z),
            fire_l2_event(now, sample.mid_tick, z_ac, +1, "ASK_OUT", "ASK_IN", event_z),
        ):
            if ev is None:
                continue
            events.append(ev)
            if start <= now <= end:
                visible_events.append(ev)

        cutoff = now - timedelta(seconds=band_window_sec)
        bull_count = 0
        bear_count = 0
        for ev in events:
            if ev.ts < cutoff or ev.abs_z < event_z:
                continue
            if ev.bias > 0:
                bull_count += 1
            elif ev.bias < 0:
                bear_count += 1

        rv = sum_values_over(mid_rets2, now, band_window_sec)
        inner_vals = [s.bid_inner + s.ask_inner for s in samples if s.ts >= now - timedelta(seconds=lookback_sec)]
        mean_inner, std_inner = mean_std(inner_vals)
        inner_total = sample.bid_inner + sample.ask_inner
        thin_z = (inner_total - mean_inner) / std_inner if std_inner > 0 else 0.0

        bear_match = bear_count >= band_event_count and rv >= band_rv_threshold and thin_z <= -band_inner_thin_z
        bull_match = bull_count >= band_event_count and rv >= band_rv_threshold and thin_z <= -band_inner_thin_z
        if bear_match and bull_match:
            if bear_count >= bull_count:
                bull_match = False
            else:
                bear_match = False
        match = "BEAR" if bear_match else ("BULL" if bull_match else "NONE")

        count_direction = "BEAR" if bear_count >= bull_count else "BULL"
        count_ok = max(bull_count, bear_count) >= band_event_count
        rv_ok = rv >= band_rv_threshold
        thin_ok = thin_z <= -band_inner_thin_z
        if start <= now <= end:
            sample_metrics.append(
                FlowSampleMetric(
                    ts=now,
                    price=mid_price,
                    price_tick=sample.mid_tick,
                    bull_count=bull_count,
                    bear_count=bear_count,
                    rv=rv,
                    thin_z=thin_z,
                    inner_total=inner_total,
                    count_direction=count_direction,
                    count_ok=count_ok,
                    rv_ok=rv_ok,
                    thin_ok=thin_ok,
                )
            )

        if match != "NONE" and start <= now <= end:
            matches.append(
                FlowMatch(
                    ts=now,
                    price=mid_price,
                    price_tick=sample.mid_tick,
                    direction=match,
                    bull_count=bull_count,
                    bear_count=bear_count,
                    rv=rv,
                    thin_z=thin_z,
                    inner_total=inner_total,
                )
            )

        if state == "NONE":
            if match != "NONE":
                if match_start is None:
                    match_start = now
                    match_start_price = mid_price
                last_match_time = now
                if (now - match_start).total_seconds() >= band_sustain_sec:
                    state = match
                    open_band = {
                        "direction": match,
                        "start_ts": match_start,
                        "last_ts": now,
                        "start_price": match_start_price if match_start_price is not None else mid_price,
                        "last_price": mid_price,
                        "match_samples": 1,
                        "max_bull_count": bull_count,
                        "max_bear_count": bear_count,
                        "max_rv": rv,
                        "min_thin_z": thin_z,
                    }
            else:
                match_start = None
                match_start_price = None
        else:
            if match == state:
                last_match_time = now
                if open_band is not None:
                    open_band["last_ts"] = now
                    open_band["last_price"] = mid_price
                    open_band["match_samples"] += 1
                    open_band["max_bull_count"] = max(open_band["max_bull_count"], bull_count)
                    open_band["max_bear_count"] = max(open_band["max_bear_count"], bear_count)
                    open_band["max_rv"] = max(open_band["max_rv"], rv)
                    open_band["min_thin_z"] = min(open_band["min_thin_z"], thin_z)
            else:
                if last_match_time is not None and (now - last_match_time).total_seconds() >= band_cooldown_sec:
                    close_band(last_match_time)
                    state = "NONE"
                    match_start = None
                    match_start_price = None

    if open_band is not None:
        close_band(open_band["last_ts"])

    bands = [b for b in bands if b.end_ts >= start and b.start_ts <= end]
    return bands, matches, sample_metrics, visible_events


def evict_l2_events(items: deque[L2Event], now: datetime, seconds: int) -> None:
    cutoff = now - timedelta(seconds=seconds)
    while items and items[0].ts < cutoff:
        items.popleft()


def detect_build_bands(
    rows: pl.DataFrame,
    start: datetime,
    end: datetime,
    lookback_sec: int,
    event_z: float,
    build_cluster_n: int,
    build_cluster_ticks: int,
    build_cluster_sec: int,
    price_through_buffer_ticks: int,
) -> tuple[list[BuildBandState], list[BuildBandTrace], list[L2Event]]:
    samples: deque[Sample] = deque()
    pending: deque[L2Event] = deque()
    active: list[BuildBandState] = []
    all_bands: list[BuildBandState] = []
    traces: list[BuildBandTrace] = []
    visible_build_events: list[L2Event] = []
    next_band_id = 1

    def trace(
        ts: datetime,
        price_tick: int,
        side: str,
        action: str,
        band_id: int,
        z: float,
        min_tick: int,
        max_tick: int,
        event_count: int,
        note: str,
    ) -> None:
        if ts < start or ts > end:
            return
        traces.append(
            BuildBandTrace(
                ts=ts,
                price=price_tick * TICK_SIZE,
                price_tick=price_tick,
                side=side,
                action=action,
                band_id=band_id,
                z=z,
                min_price=min_tick * TICK_SIZE,
                max_price=max_tick * TICK_SIZE,
                event_count=event_count,
                note=note,
            )
        )

    def update_build_band(ev: L2Event) -> None:
        nonlocal next_band_id
        side = "SUPPLY" if ev.kind == "ASK_BUILD" else "DEMAND"

        for band in active:
            if band.side != side:
                continue
            if (ev.ts - band.last_update_ts).total_seconds() > build_cluster_sec:
                continue
            lo = band.min_tick - build_cluster_ticks
            hi = band.max_tick + build_cluster_ticks
            if lo <= ev.price_tick <= hi:
                band.min_tick = min(band.min_tick, ev.price_tick)
                band.max_tick = max(band.max_tick, ev.price_tick)
                band.last_update_ts = ev.ts
                band.event_count += 1
                band.max_z = max(band.max_z, ev.abs_z)
                trace(
                    ev.ts,
                    ev.price_tick,
                    side,
                    "EXTEND",
                    band.band_id,
                    ev.abs_z,
                    band.min_tick,
                    band.max_tick,
                    band.event_count,
                    ev.kind,
                )
                return

        members = [ev]
        for p in pending:
            if side == "SUPPLY" and p.kind != "ASK_BUILD":
                continue
            if side == "DEMAND" and p.kind != "BID_BUILD":
                continue
            if abs(p.price_tick - ev.price_tick) > build_cluster_ticks:
                continue
            if (ev.ts - p.ts).total_seconds() > build_cluster_sec:
                continue
            members.append(p)

        if len(members) >= build_cluster_n:
            min_tick = min(m.price_tick for m in members)
            max_tick = max(m.price_tick for m in members)
            first_ts = min(m.ts for m in members)
            last_ts = max(m.ts for m in members)
            max_z = max(m.abs_z for m in members)
            band = BuildBandState(
                band_id=next_band_id,
                side=side,
                min_tick=min_tick,
                max_tick=max_tick,
                start_ts=first_ts,
                formed_ts=ev.ts,
                last_update_ts=last_ts,
                event_count=len(members),
                max_z=max_z,
            )
            next_band_id += 1
            active.append(band)
            all_bands.append(band)
            consumed = set((m.ts, m.price_tick, m.kind, m.abs_z) for m in members)
            pending_keep = deque(
                p for p in pending if (p.ts, p.price_tick, p.kind, p.abs_z) not in consumed
            )
            pending.clear()
            pending.extend(pending_keep)
            trace(
                ev.ts,
                ev.price_tick,
                side,
                "FORM",
                band.band_id,
                ev.abs_z,
                band.min_tick,
                band.max_tick,
                band.event_count,
                f"{len(members)} builds in {build_cluster_sec}s/{build_cluster_ticks}t",
            )
        else:
            pending.append(ev)
            trace(
                ev.ts,
                ev.price_tick,
                side,
                "PENDING",
                0,
                ev.abs_z,
                ev.price_tick,
                ev.price_tick,
                len(members),
                f"{len(members)}/{build_cluster_n}",
            )

    def apply_price_through(now: datetime, mid_tick: int) -> None:
        still_active: list[BuildBandState] = []
        for band in active:
            clear = False
            reason = ""
            if band.side == "SUPPLY" and mid_tick > band.max_tick + price_through_buffer_ticks:
                clear = True
                reason = "PRICE_THROUGH_UP"
            elif band.side == "DEMAND" and mid_tick < band.min_tick - price_through_buffer_ticks:
                clear = True
                reason = "PRICE_THROUGH_DOWN"

            if clear:
                band.active = False
                band.clear_ts = now
                band.clear_price_tick = mid_tick
                band.clear_reason = reason
                trace(
                    now,
                    mid_tick,
                    band.side,
                    "CLEAR",
                    band.band_id,
                    0.0,
                    band.min_tick,
                    band.max_tick,
                    band.event_count,
                    reason,
                )
            else:
                still_active.append(band)

        active[:] = still_active

    for row in rows.iter_rows(named=True):
        sample = build_sample(row)
        now = sample.ts
        samples.append(sample)
        evict_samples(samples, now, lookback_sec * 2)
        evict_l2_events(pending, now, build_cluster_sec)

        if len(samples) < 5:
            apply_price_through(now, sample.mid_tick)
            continue

        def z_of(selector, floor: float) -> float:
            vals = [selector(s) for s in samples if s.ts >= now - timedelta(seconds=lookback_sec)]
            mean, std = mean_std(vals)
            return (selector(sample) - mean) / max(floor, std)

        z_bi = z_of(lambda s: s.bid_inner, 1.0)
        z_ai = z_of(lambda s: s.ask_inner, 1.0)

        build_events: list[L2Event] = []
        if z_bi > event_z:
            build_events.append(L2Event(ts=now, price_tick=sample.mid_tick, kind="BID_BUILD", bias=+1, abs_z=z_bi))
        if z_ai > event_z:
            build_events.append(L2Event(ts=now, price_tick=sample.mid_tick, kind="ASK_BUILD", bias=-1, abs_z=z_ai))

        for ev in build_events:
            if start <= now <= end:
                visible_build_events.append(ev)
            update_build_band(ev)

        apply_price_through(now, sample.mid_tick)

    visible_bands: list[BuildBandState] = []
    for band in all_bands:
        band_end = band.clear_ts or end
        if band_end >= start and band.start_ts <= end:
            visible_bands.append(band)
    visible_bands.sort(key=lambda b: (b.start_ts, b.formed_ts, b.band_id))
    traces.sort(key=lambda t: (t.ts, t.action, t.band_id))
    return visible_bands, traces, visible_build_events


def make_episodes(events: list[VodBuildEvent], gap_sec: int, merge_ticks: int) -> list[VodBuildEvent]:
    episodes: list[VodBuildEvent] = []
    current: list[VodBuildEvent] = []

    def close_current() -> None:
        if not current:
            return
        best = max(current, key=lambda e: e.strength)
        episodes.append(best)
        current.clear()

    for ev in events:
        if not current:
            current.append(ev)
            continue
        last = current[-1]
        same_cluster = (
            (ev.ts - last.ts).total_seconds() <= gap_sec
            and abs(ev.mid_tick - last.mid_tick) <= merge_ticks
            and (ev.side == last.side or "MIXED" in (ev.side, last.side))
        )
        if same_cluster:
            current.append(ev)
        else:
            close_current()
            current.append(ev)
    close_current()
    return episodes


def write_csv(path: Path, rows: list[VodBuildEvent]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "ny_time",
                "utc_time",
                "price",
                "mid_tick",
                "side",
                "chaos_side",
                "vod_z",
                "bid_build_z",
                "ask_build_z",
                "inner_total",
                "note",
            ]
        )
        for ev in rows:
            w.writerow(
                [
                    ny_hms(ev.ts),
                    ev.ts.isoformat(),
                    f"{ev.price:.2f}",
                    ev.mid_tick,
                    ev.side,
                    ev.chaos_side,
                    f"{ev.vod_z:.3f}",
                    f"{ev.bid_build_z:.3f}",
                    f"{ev.ask_build_z:.3f}",
                    f"{ev.inner_total:.1f}",
                    ev.note,
                ]
            )


def write_txt(path: Path, day: str, raw: list[VodBuildEvent], episodes: list[VodBuildEvent], args) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        f.write(
            f"{day} {args.symbol_dir} candidate=vod-build "
            f"lookback={args.lookback_sec}s event_z={args.event_z} "
            f"vod_z={args.vod_z} build_z={args.build_z}\n"
        )
        f.write(f"raw_matches={len(raw)} episodes={len(episodes)}\n\n")
        f.write("Episodes, clustered for chart review:\n")
        f.write("time      price     build_side chaos  vod_z  bid_z  ask_z  note\n")
        for ev in episodes:
            f.write(
                f"{ny_hms(ev.ts)} {ev.price:8.2f} {ev.side:<10} {ev.chaos_side:<5} "
                f"{ev.vod_z:5.2f} {ev.bid_build_z:6.2f} {ev.ask_build_z:6.2f}  {ev.note}\n"
            )
        f.write("\nRaw time-ordered matches:\n")
        f.write("time      price     build_side chaos  vod_z  bid_z  ask_z  note\n")
        for ev in raw:
            f.write(
                f"{ny_hms(ev.ts)} {ev.price:8.2f} {ev.side:<10} {ev.chaos_side:<5} "
                f"{ev.vod_z:5.2f} {ev.bid_build_z:6.2f} {ev.ask_build_z:6.2f}  {ev.note}\n"
            )


def write_inflection_csv(path: Path, rows: list[InflectionResult]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "status",
                "trigger_ny",
                "decision_ny",
                "trigger_utc",
                "decision_utc",
                "price",
                "price_tick",
                "direction",
                "trigger_kind",
                "trigger_z",
                "seconds_to_decision",
                "cum_delta",
                "roc",
                "best_aligned_cum",
                "best_aligned_roc",
            ]
        )
        for r in rows:
            w.writerow(
                [
                    r.status,
                    ny_hms(r.trigger_ts),
                    ny_hms(r.decision_ts),
                    r.trigger_ts.isoformat(),
                    r.decision_ts.isoformat(),
                    f"{r.price:.2f}",
                    r.price_tick,
                    r.direction,
                    r.trigger_kind,
                    f"{r.trigger_z:.3f}",
                    f"{r.seconds_to_decision:.1f}",
                    f"{r.cum_delta:.3f}",
                    f"{r.roc:.3f}",
                    f"{r.best_aligned_cum:.3f}",
                    f"{r.best_aligned_roc:.3f}",
                ]
            )


def write_l2_events_csv(path: Path, rows: list[L2Event]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["ny_time", "utc_time", "price", "price_tick", "side", "kind", "bias", "abs_z"])
        for ev in rows:
            w.writerow(
                [
                    ny_hms(ev.ts),
                    ev.ts.isoformat(),
                    f"{ev.price_tick * TICK_SIZE:.2f}",
                    ev.price_tick,
                    event_side(ev.kind),
                    ev.kind,
                    ev.bias,
                    f"{ev.abs_z:.3f}",
                ]
            )


def write_inflection_txt(path: Path, day: str, confirmed: list[InflectionResult], decisions: list[InflectionResult], args) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        f.write(
            f"{day} {args.symbol_dir} candidate=inflection "
            f"lookback={args.lookback_sec}s event_z={args.event_z} "
            f"trigger_build_z={args.trigger_build_z} cum_threshold={args.cum_threshold} "
            f"roc_threshold={args.roc_threshold} confirm_window={args.confirmation_window_sec}s "
            f"roc_window={args.roc_window_sec}s cum_window={args.cum_window_sec}s\n"
        )
        f.write(f"confirmed={len(confirmed)} triggers={len(decisions)}\n\n")

        f.write("Confirmed inflections:\n")
        f.write("trigger   confirm   lag  price     dir  kind       z     cum    roc   bestCum bestRoc\n")
        for r in confirmed:
            f.write(
                f"{ny_hms(r.trigger_ts)} {ny_hms(r.decision_ts)} "
                f"{r.seconds_to_decision:4.0f}s {r.price:8.2f} {r.direction:<4} "
                f"{r.trigger_kind:<9} {r.trigger_z:4.2f} "
                f"{r.cum_delta:7.2f} {r.roc:6.2f} {r.best_aligned_cum:7.2f} {r.best_aligned_roc:7.2f}\n"
            )

        f.write("\nAll BUILD triggers:\n")
        f.write("status    trigger   decision  lag  price     dir  kind       z     cum    roc   bestCum bestRoc\n")
        for r in decisions:
            f.write(
                f"{r.status:<9} {ny_hms(r.trigger_ts)} {ny_hms(r.decision_ts)} "
                f"{r.seconds_to_decision:4.0f}s {r.price:8.2f} {r.direction:<4} "
                f"{r.trigger_kind:<9} {r.trigger_z:4.2f} "
                f"{r.cum_delta:7.2f} {r.roc:6.2f} {r.best_aligned_cum:7.2f} {r.best_aligned_roc:7.2f}\n"
            )


def write_flow_bands_csv(path: Path, rows: list[FlowBandResult]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "direction",
                "start_ny",
                "end_ny",
                "start_utc",
                "end_utc",
                "start_price",
                "end_price",
                "duration_sec",
                "match_samples",
                "max_bull_count",
                "max_bear_count",
                "max_rv",
                "min_thin_z",
            ]
        )
        for b in rows:
            w.writerow(
                [
                    b.direction,
                    ny_hms(b.start_ts),
                    ny_hms(b.end_ts),
                    b.start_ts.isoformat(),
                    b.end_ts.isoformat(),
                    f"{b.start_price:.2f}",
                    f"{b.end_price:.2f}",
                    f"{b.duration_sec:.1f}",
                    b.match_samples,
                    b.max_bull_count,
                    b.max_bear_count,
                    f"{b.max_rv:.10f}",
                    f"{b.min_thin_z:.3f}",
                ]
            )


def write_flow_matches_csv(path: Path, rows: list[FlowMatch]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "ny_time",
                "utc_time",
                "price",
                "price_tick",
                "direction",
                "bull_count",
                "bear_count",
                "rv",
                "thin_z",
                "inner_total",
            ]
        )
        for m in rows:
            w.writerow(
                [
                    ny_hms(m.ts),
                    m.ts.isoformat(),
                    f"{m.price:.2f}",
                    m.price_tick,
                    m.direction,
                    m.bull_count,
                    m.bear_count,
                    f"{m.rv:.10f}",
                    f"{m.thin_z:.3f}",
                    f"{m.inner_total:.1f}",
                ]
            )


def write_flow_samples_csv(path: Path, rows: list[FlowSampleMetric]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "ny_time",
                "utc_time",
                "price",
                "price_tick",
                "bull_count",
                "bear_count",
                "rv",
                "thin_z",
                "inner_total",
                "count_direction",
                "count_ok",
                "rv_ok",
                "thin_ok",
            ]
        )
        for s in rows:
            w.writerow(
                [
                    ny_hms(s.ts),
                    s.ts.isoformat(),
                    f"{s.price:.2f}",
                    s.price_tick,
                    s.bull_count,
                    s.bear_count,
                    f"{s.rv:.10f}",
                    f"{s.thin_z:.3f}",
                    f"{s.inner_total:.1f}",
                    s.count_direction,
                    int(s.count_ok),
                    int(s.rv_ok),
                    int(s.thin_ok),
                ]
            )


def write_flow_txt(path: Path, day: str, bands: list[FlowBandResult], matches: list[FlowMatch], metrics: list[FlowSampleMetric], args) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    total = len(metrics)
    count_ok = sum(1 for m in metrics if m.count_ok)
    rv_ok = sum(1 for m in metrics if m.rv_ok)
    thin_ok = sum(1 for m in metrics if m.thin_ok)
    count_rv = sum(1 for m in metrics if m.count_ok and m.rv_ok)
    count_thin = sum(1 for m in metrics if m.count_ok and m.thin_ok)
    rv_thin = sum(1 for m in metrics if m.rv_ok and m.thin_ok)
    all_three = sum(1 for m in metrics if m.count_ok and m.rv_ok and m.thin_ok)
    near = sorted(
        (m for m in metrics if m.count_ok or m.thin_ok or m.rv_ok),
        key=lambda m: (
            int(m.count_ok) + int(m.rv_ok) + int(m.thin_ok),
            max(m.bull_count, m.bear_count),
            m.rv / 1e-7,
            -m.thin_z,
        ),
        reverse=True,
    )[:40]

    with path.open("w", encoding="utf-8") as f:
        f.write(
            f"{day} {args.symbol_dir} candidate=flow "
            f"lookback={args.lookback_sec}s event_z={args.event_z} "
            f"band_window={args.band_window_sec}s min_events={args.band_event_count} "
            f"rv_threshold={args.band_rv_scaled}e-7 inner_thin_z={args.band_inner_thin_z} "
            f"sustain={args.band_sustain_sec}s cooldown={args.band_cooldown_sec}s\n"
        )
        f.write(f"bands={len(bands)} matches={len(matches)}\n\n")

        f.write("Condition diagnostics:\n")
        f.write(f"samples={total}\n")
        f.write(f"count_ok={count_ok}  rv_ok={rv_ok}  thin_ok={thin_ok}\n")
        f.write(f"count+rv={count_rv}  count+thin={count_thin}  rv+thin={rv_thin}  all_three={all_three}\n\n")

        f.write("Flow bands:\n")
        f.write("dir  start    end      dur   startPx  endPx    samples maxBull maxBear maxRV(e-7) minThinZ\n")
        for b in bands:
            f.write(
                f"{b.direction:<4} {ny_hms(b.start_ts)} {ny_hms(b.end_ts)} "
                f"{b.duration_sec:5.0f}s {b.start_price:8.2f} {b.end_price:8.2f} "
                f"{b.match_samples:7d} {b.max_bull_count:7d} {b.max_bear_count:7d} "
                f"{b.max_rv / 1e-7:9.2f} {b.min_thin_z:8.2f}\n"
            )

        f.write("\nUnderlying flow-match samples:\n")
        f.write("time      price     dir  bull bear  rv(e-7) thinZ  inner\n")
        for m in matches:
            f.write(
                f"{ny_hms(m.ts)} {m.price:8.2f} {m.direction:<4} "
                f"{m.bull_count:4d} {m.bear_count:4d} {m.rv / 1e-7:8.2f} "
                f"{m.thin_z:6.2f} {m.inner_total:6.1f}\n"
            )

        f.write("\nTop near-miss / condition samples:\n")
        f.write("time      price     dir  bull bear  rv(e-7) thinZ  count rv thin inner\n")
        for m in near:
            f.write(
                f"{ny_hms(m.ts)} {m.price:8.2f} {m.count_direction:<4} "
                f"{m.bull_count:4d} {m.bear_count:4d} {m.rv / 1e-7:8.2f} "
                f"{m.thin_z:6.2f} {int(m.count_ok):5d} {int(m.rv_ok):2d} {int(m.thin_ok):4d} "
                f"{m.inner_total:6.1f}\n"
            )


def write_build_bands_csv(path: Path, rows: list[BuildBandState]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "band_id",
                "side",
                "status",
                "start_ny",
                "formed_ny",
                "last_update_ny",
                "clear_ny",
                "start_utc",
                "formed_utc",
                "last_update_utc",
                "clear_utc",
                "min_price",
                "max_price",
                "min_tick",
                "max_tick",
                "event_count",
                "max_z",
                "clear_price",
                "clear_reason",
                "active_seconds",
            ]
        )
        for b in rows:
            end_ts = b.clear_ts or b.last_update_ts
            active_seconds = (end_ts - b.start_ts).total_seconds()
            w.writerow(
                [
                    b.band_id,
                    b.side,
                    "ACTIVE" if b.active else "CLEARED",
                    ny_hms(b.start_ts),
                    ny_hms(b.formed_ts),
                    ny_hms(b.last_update_ts),
                    ny_hms(b.clear_ts) if b.clear_ts else "",
                    b.start_ts.isoformat(),
                    b.formed_ts.isoformat(),
                    b.last_update_ts.isoformat(),
                    b.clear_ts.isoformat() if b.clear_ts else "",
                    f"{b.min_price:.2f}",
                    f"{b.max_price:.2f}",
                    b.min_tick,
                    b.max_tick,
                    b.event_count,
                    f"{b.max_z:.3f}",
                    f"{b.clear_price_tick * TICK_SIZE:.2f}" if b.clear_price_tick is not None else "",
                    b.clear_reason,
                    f"{active_seconds:.1f}",
                ]
            )


def write_build_traces_csv(path: Path, rows: list[BuildBandTrace]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "ny_time",
                "utc_time",
                "price",
                "price_tick",
                "side",
                "action",
                "band_id",
                "z",
                "min_price",
                "max_price",
                "event_count",
                "note",
            ]
        )
        for r in rows:
            w.writerow(
                [
                    ny_hms(r.ts),
                    r.ts.isoformat(),
                    f"{r.price:.2f}",
                    r.price_tick,
                    r.side,
                    r.action,
                    r.band_id,
                    f"{r.z:.3f}",
                    f"{r.min_price:.2f}",
                    f"{r.max_price:.2f}",
                    r.event_count,
                    r.note,
                ]
            )


def write_build_bands_txt(path: Path, day: str, bands: list[BuildBandState], traces: list[BuildBandTrace], build_events: list[L2Event], args) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    active = [b for b in bands if b.active]
    cleared = [b for b in bands if not b.active]
    demand = [b for b in bands if b.side == "DEMAND"]
    supply = [b for b in bands if b.side == "SUPPLY"]
    forms = [t for t in traces if t.action == "FORM"]
    extends = [t for t in traces if t.action == "EXTEND"]
    clears = [t for t in traces if t.action == "CLEAR"]

    with path.open("w", encoding="utf-8") as f:
        f.write(
            f"{day} {args.symbol_dir} candidate=build-bands "
            f"lookback={args.lookback_sec}s event_z={args.event_z} "
            f"cluster_n={args.build_cluster_n} cluster_ticks={args.build_cluster_ticks} "
            f"cluster_sec={args.build_cluster_sec} price_through_buffer_ticks={args.price_through_buffer_ticks}\n"
        )
        f.write(
            f"bands={len(bands)} demand={len(demand)} supply={len(supply)} "
            f"active_at_end={len(active)} cleared={len(cleared)} "
            f"build_events={len(build_events)} forms={len(forms)} extends={len(extends)} clears={len(clears)}\n\n"
        )

        f.write("Bands intersecting review window:\n")
        f.write("id side    status  start    formed   lastUpd  clear    minPx    maxPx    ev  maxZ  activeSec reason\n")
        for b in bands:
            end_ts = b.clear_ts or b.last_update_ts
            active_seconds = (end_ts - b.start_ts).total_seconds()
            f.write(
                f"{b.band_id:2d} {b.side:<7} {'ACTIVE' if b.active else 'CLEARED':<7} "
                f"{ny_hms(b.start_ts)} {ny_hms(b.formed_ts)} {ny_hms(b.last_update_ts)} "
                f"{ny_hms(b.clear_ts) if b.clear_ts else '--:--:--':<8} "
                f"{b.min_price:8.2f} {b.max_price:8.2f} "
                f"{b.event_count:4d} {b.max_z:5.2f} {active_seconds:9.0f}s {b.clear_reason}\n"
            )

        f.write("\nFormation / extension / clear trace:\n")
        f.write("time      action  id side    price     zone              ev  z     note\n")
        for r in traces:
            if r.action == "PENDING":
                continue
            f.write(
                f"{ny_hms(r.ts)} {r.action:<7} {r.band_id:2d} {r.side:<7} "
                f"{r.price:8.2f} {r.min_price:8.2f}-{r.max_price:<8.2f} "
                f"{r.event_count:3d} {r.z:5.2f} {r.note}\n"
            )

        f.write("\nBuild events:\n")
        f.write("time      side    kind       price     z\n")
        for ev in build_events:
            side = "DEMAND" if ev.kind == "BID_BUILD" else "SUPPLY"
            f.write(f"{ny_hms(ev.ts)} {side:<7} {ev.kind:<9} {ev.price_tick * TICK_SIZE:8.2f} {ev.abs_z:5.2f}\n")


def run_day(day: str, args) -> tuple[Path, Path, Path, int, int]:
    start, end = parse_window(day, args.window, not args.eth)
    rows = load_snapshots(day, args.symbol_dir, start, end, args.warmup_min)
    if args.candidate == "build-bands":
        bands, traces, build_events = detect_build_bands(
            rows=rows,
            start=start,
            end=end,
            lookback_sec=args.lookback_sec,
            event_z=args.event_z,
            build_cluster_n=args.build_cluster_n,
            build_cluster_ticks=args.build_cluster_ticks,
            build_cluster_sec=args.build_cluster_sec,
            price_through_buffer_ticks=args.price_through_buffer_ticks,
        )
        out_dir = Path(args.out_dir)
        suffix = f"{day}_build_bands"
        if (
            args.build_cluster_n != 3
            or args.build_cluster_ticks != 8
            or args.build_cluster_sec != 90
            or args.price_through_buffer_ticks != 1
        ):
            suffix += (
                f"_n{args.build_cluster_n}"
                f"_t{args.build_cluster_ticks}"
                f"_sec{args.build_cluster_sec}"
                f"_buf{args.price_through_buffer_ticks}"
            )
        if args.window:
            suffix += "_" + args.window.replace(":", "").replace("-", "_")
        txt = out_dir / f"surface_{suffix}.txt"
        bands_csv = out_dir / f"surface_{suffix}_bands.csv"
        traces_csv = out_dir / f"surface_{suffix}_trace.csv"
        events_csv = out_dir / f"surface_{suffix}_build_events.csv"
        write_build_bands_txt(txt, day, bands, traces, build_events, args)
        write_build_bands_csv(bands_csv, bands)
        write_build_traces_csv(traces_csv, traces)
        write_l2_events_csv(events_csv, build_events)
        return txt, bands_csv, traces_csv, len(bands), len(build_events)

    if args.candidate == "flow":
        bands, matches, metrics, l2_events = detect_flow(
            rows=rows,
            start=start,
            end=end,
            lookback_sec=args.lookback_sec,
            event_z=args.event_z,
            band_window_sec=args.band_window_sec,
            band_event_count=args.band_event_count,
            band_rv_threshold=args.band_rv_scaled * 1e-7,
            band_inner_thin_z=args.band_inner_thin_z,
            band_sustain_sec=args.band_sustain_sec,
            band_cooldown_sec=args.band_cooldown_sec,
        )
        out_dir = Path(args.out_dir)
        suffix = f"{day}_flow"
        if (
            args.band_event_count != 5
            or args.band_sustain_sec != 10
            or args.band_cooldown_sec != 30
            or abs(args.band_rv_scaled - 1.0) > 1e-9
            or abs(args.band_inner_thin_z - 1.0) > 1e-9
            or args.band_window_sec != 30
        ):
            suffix += (
                f"_ev{args.band_event_count}"
                f"_rv{str(args.band_rv_scaled).replace('.', 'p')}"
                f"_thin{str(args.band_inner_thin_z).replace('.', 'p')}"
                f"_sus{args.band_sustain_sec}"
            )
        if args.window:
            suffix += "_" + args.window.replace(":", "").replace("-", "_")
        txt = out_dir / f"surface_{suffix}.txt"
        bands_csv = out_dir / f"surface_{suffix}_bands.csv"
        matches_csv = out_dir / f"surface_{suffix}_matches.csv"
        samples_csv = out_dir / f"surface_{suffix}_samples.csv"
        events_csv = out_dir / f"surface_{suffix}_l2_events.csv"
        write_flow_txt(txt, day, bands, matches, metrics, args)
        write_flow_bands_csv(bands_csv, bands)
        write_flow_matches_csv(matches_csv, matches)
        write_flow_samples_csv(samples_csv, metrics)
        write_l2_events_csv(events_csv, l2_events)
        return txt, bands_csv, matches_csv, len(bands), len(matches)

    if args.candidate == "inflection":
        confirmed, decisions, l2_events = detect_inflections(
            rows=rows,
            start=start,
            end=end,
            lookback_sec=args.lookback_sec,
            event_z=args.event_z,
            trigger_build_z=args.trigger_build_z,
            cum_threshold=args.cum_threshold,
            roc_threshold=args.roc_threshold,
            confirmation_window_sec=args.confirmation_window_sec,
            roc_window_sec=args.roc_window_sec,
            cum_window_sec=args.cum_window_sec,
        )
        out_dir = Path(args.out_dir)
        suffix = f"{day}_inflection"
        if args.window:
            suffix += "_" + args.window.replace(":", "").replace("-", "_")
        txt = out_dir / f"surface_{suffix}.txt"
        confirmed_csv = out_dir / f"surface_{suffix}_confirmed.csv"
        triggers_csv = out_dir / f"surface_{suffix}_triggers.csv"
        events_csv = out_dir / f"surface_{suffix}_l2_events.csv"
        write_inflection_txt(txt, day, confirmed, decisions, args)
        write_inflection_csv(confirmed_csv, confirmed)
        write_inflection_csv(triggers_csv, decisions)
        write_l2_events_csv(events_csv, l2_events)
        return txt, confirmed_csv, triggers_csv, len(confirmed), len(decisions)

    raw = detect_vod_build(
        rows=rows,
        start=start,
        end=end,
        lookback_sec=args.lookback_sec,
        event_z=args.event_z,
        vod_z_threshold=args.vod_z,
        build_z_threshold=args.build_z,
    )
    episodes = make_episodes(raw, args.episode_gap_sec, args.episode_ticks)

    out_dir = Path(args.out_dir)
    suffix = f"{day}_vod_build"
    if args.window:
        suffix += "_" + args.window.replace(":", "").replace("-", "_")
    raw_csv = out_dir / f"surface_{suffix}_raw.csv"
    episode_csv = out_dir / f"surface_{suffix}_episodes.csv"
    txt = out_dir / f"surface_{suffix}.txt"
    write_csv(raw_csv, raw)
    write_csv(episode_csv, episodes)
    write_txt(txt, day, raw, episodes, args)
    return txt, raw_csv, episode_csv, len(raw), len(episodes)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate", default="vod-build", choices=["vod-build", "inflection", "flow", "build-bands"])
    parser.add_argument("--date", action="append", required=True, help="YYYY-MM-DD; repeat for multiple days")
    parser.add_argument("--symbol-dir", default=os.environ.get("SYMBOL_DIR", "NQM6"))
    parser.add_argument("--window", help="NY time window, e.g. 09:30-16:00 or 13:05-13:30")
    parser.add_argument("--eth", action="store_true", help="Use full NY calendar day when --window is omitted")
    parser.add_argument("--warmup-min", type=int, default=30)
    parser.add_argument("--lookback-sec", type=int, default=30)
    parser.add_argument("--event-z", type=float, default=3.0)
    parser.add_argument("--vod-z", type=float, default=5.0)
    parser.add_argument("--build-z", type=float, default=4.0)
    parser.add_argument("--trigger-build-z", type=float, default=4.0)
    parser.add_argument("--cum-threshold", type=float, default=7.0)
    parser.add_argument("--roc-threshold", type=float, default=5.0)
    parser.add_argument("--confirmation-window-sec", type=int, default=60)
    parser.add_argument("--roc-window-sec", type=int, default=60)
    parser.add_argument("--cum-window-sec", type=int, default=300)
    parser.add_argument("--band-window-sec", type=int, default=30)
    parser.add_argument("--band-event-count", type=int, default=5)
    parser.add_argument("--band-rv-scaled", type=float, default=1.0)
    parser.add_argument("--band-inner-thin-z", type=float, default=1.0)
    parser.add_argument("--band-sustain-sec", type=int, default=10)
    parser.add_argument("--band-cooldown-sec", type=int, default=30)
    parser.add_argument("--build-cluster-n", type=int, default=3)
    parser.add_argument("--build-cluster-ticks", type=int, default=8)
    parser.add_argument("--build-cluster-sec", type=int, default=90)
    parser.add_argument("--price-through-buffer-ticks", type=int, default=1)
    parser.add_argument("--episode-gap-sec", type=int, default=30)
    parser.add_argument("--episode-ticks", type=int, default=4)
    parser.add_argument("--out-dir", default=r"C:\Heatmap\research\out")
    args = parser.parse_args()

    for day in args.date:
        txt, first_csv, second_csv, first_count, second_count = run_day(day, args)
        if args.candidate == "inflection":
            events_csv = Path(str(second_csv).replace("_triggers.csv", "_l2_events.csv"))
            print(f"{day}: confirmed={first_count} triggers={second_count}")
            print(f"  {txt}")
            print(f"  {first_csv}")
            print(f"  {second_csv}")
            print(f"  {events_csv}")
        elif args.candidate == "flow":
            events_csv = Path(str(second_csv).replace("_matches.csv", "_l2_events.csv"))
            samples_csv = Path(str(second_csv).replace("_matches.csv", "_samples.csv"))
            print(f"{day}: bands={first_count} matches={second_count}")
            print(f"  {txt}")
            print(f"  {first_csv}")
            print(f"  {second_csv}")
            print(f"  {samples_csv}")
            print(f"  {events_csv}")
        elif args.candidate == "build-bands":
            events_csv = Path(str(second_csv).replace("_trace.csv", "_build_events.csv"))
            print(f"{day}: bands={first_count} build_events={second_count}")
            print(f"  {txt}")
            print(f"  {first_csv}")
            print(f"  {second_csv}")
            print(f"  {events_csv}")
        else:
            print(f"{day}: raw={first_count} episodes={second_count}")
            print(f"  {txt}")
            print(f"  {first_csv}")
            print(f"  {second_csv}")


if __name__ == "__main__":
    main()
