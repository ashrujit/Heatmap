"""Replay LevelLedger spatial dominance from captured L2 snapshots.

This mirrors the live C# book-event and spatial-dominance path closely enough
to debug timestamp/price provenance issues from a captured session.
"""

from __future__ import annotations

import argparse
import math
import os
import sys
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import polars as pl

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "research"))
from capture_loader import load_capture_window, snapshot_columns


TICK_SIZE = 0.25
INNER_LEVELS = 10
BROAD_LEVELS = 30
BOOK_LOOKBACK_SEC = 30
EVENT_Z_THRESHOLD = 2.5
BUILD_BAND_BUILD_Z = 3.0
BUILD_BAND_CLUSTER_N = 3
BUILD_BAND_CLUSTER_TICKS = 8
BUILD_BAND_CLUSTER_SEC = 90
BUILD_BAND_PRICE_THROUGH_BUFFER_TICKS = 1
ROW_MERGE_SECONDS = 75
ROW_MERGE_TICKS = 18
DOMINANCE_WINDOW_SEC = 20 * 60
DOMINANCE_HALF_LIFE_SEC = 8 * 60
DOMINANCE_KERNEL_TICKS = 12
DOMINANCE_ZONE_MERGE_TICKS = 24
DOMINANCE_CURRENT_RELEVANCE_TICKS = DOMINANCE_KERNEL_TICKS * 3
DOMINANCE_FRESH_CAUSE_SEC = 90
DOMINANCE_EVAL_COOLDOWN_SEC = 20
DOMINANCE_MAX_ZONES_PER_EVAL = 2
SPATIAL_ROW_UPDATE_PRICE_TICKS = 8
SPATIAL_ROW_UPDATE_FORCE_SECONDS = 180
SPATIAL_ROW_UPDATE_RATIO_DELTA = 0.7
SPATIAL_ROW_UPDATE_RATIO_RELATIVE = 0.35
DOMINANCE_MIN_DENSITY = 12.0
DOMINANCE_RATIO_THRESHOLD = 2.2
ROW_RETENTION_SEC = 40 * 60
SUPERSEDED_KEEP_SECONDS = 150


NY = ZoneInfo("America/New_York")


@dataclass
class BookSample:
    ts: datetime
    mid_tick: int
    bid_inner: float
    ask_inner: float
    bid_centroid: float
    ask_centroid: float


@dataclass
class BookEvent:
    ts: datetime
    price_tick: int
    bias: int
    abs_z: float
    kind: str


@dataclass
class Row:
    id: int
    ts: datetime
    price_tick: int
    direction: int
    text: str
    strength: float
    last_update_ts: datetime
    signal_ratio: float = 0.0
    superseded: bool = False
    superseded_ts: datetime | None = None
    updates: int = 1


@dataclass
class Mutation:
    action: str
    action_ts: datetime
    row_ts: datetime
    price_tick: int
    direction: int
    text: str
    updates: int
    old: str
    current_mid_tick: int


@dataclass
class BuildBandEvent:
    ts: datetime
    price_tick: int
    side: str
    abs_z: float


@dataclass
class BuildBand:
    id: int
    side: str
    min_tick: int
    max_tick: int
    start_ts: datetime
    formed_ts: datetime
    last_update_ts: datetime
    event_count: int
    max_abs_z: float
    breached_ts: datetime | None = None
    breach_price_tick: int | None = None


@dataclass
class BuildBandMutation:
    action: str
    action_ts: datetime
    band_id: int
    side: str
    min_tick: int
    max_tick: int
    event_count: int
    max_abs_z: float
    current_mid_tick: int
    old: str = ""


class Engine:
    def __init__(
        self,
        band_build_z: float = BUILD_BAND_BUILD_Z,
        band_cluster_n: int = BUILD_BAND_CLUSTER_N,
        band_cluster_ticks: int = BUILD_BAND_CLUSTER_TICKS,
        band_cluster_sec: int = BUILD_BAND_CLUSTER_SEC,
        band_price_through_buffer_ticks: int = BUILD_BAND_PRICE_THROUGH_BUFFER_TICKS,
    ) -> None:
        self.book_samples: deque[BookSample] = deque()
        self.book_events: deque[BookEvent] = deque()
        self.all_book_events: list[BookEvent] = []
        self.build_bands: list[BuildBand] = []
        self.build_band_pending: deque[BuildBandEvent] = deque()
        self.build_band_mutations: list[BuildBandMutation] = []
        self.inner_deltas: deque[tuple[datetime, float]] = deque()
        self.vod_values: deque[tuple[datetime, float]] = deque()
        self.rows: list[Row] = []
        self.next_row_id = 1
        self.next_build_band_id = 1
        self.last_dominance_eval: datetime | None = None
        self.current_mid_tick = 0
        self.prev_inner_depth: float | None = None
        self.mutations: list[Mutation] = []
        self.band_build_z = max(1.0, band_build_z)
        self.band_cluster_n = max(2, band_cluster_n)
        self.band_cluster_ticks = max(1, band_cluster_ticks)
        self.band_cluster_sec = max(1, band_cluster_sec)
        self.band_price_through_buffer_ticks = max(0, band_price_through_buffer_ticks)

    def on_sample(self, sample: BookSample) -> None:
        now = sample.ts
        self.current_mid_tick = sample.mid_tick
        self.book_samples.append(sample)
        self.evict_samples(now, BOOK_LOOKBACK_SEC * 2)
        if len(self.book_samples) < 5:
            return

        mbi, sbi = self.mean_std(now, lambda s: s.bid_inner)
        mai, sai = self.mean_std(now, lambda s: s.ask_inner)
        mbc, sbc = self.mean_std(now, lambda s: s.bid_centroid)
        mac, sac = self.mean_std(now, lambda s: s.ask_centroid)

        zbi = (sample.bid_inner - mbi) / max(1.0, sbi)
        zai = (sample.ask_inner - mai) / max(1.0, sai)
        zbc = (sample.bid_centroid - mbc) / max(0.01, sbc)
        zac = (sample.ask_centroid - mac) / max(0.01, sac)

        self.try_fire(now, sample.mid_tick, zbi, +1, "BID_BUILD", "BID_PULL")
        self.try_fire(now, sample.mid_tick, zai, -1, "ASK_BUILD", "ASK_PULL")
        self.try_fire(now, sample.mid_tick, zbc, -1, "BID_OUT", "BID_IN")
        self.try_fire(now, sample.mid_tick, zac, +1, "ASK_OUT", "ASK_IN")

        self.update_build_bands(now, sample.mid_tick, zbi, zai)
        self.apply_build_band_price_through(now, sample.mid_tick)
        self.update_vod(now, sample)
        self.evaluate_spatial_dominance(now)
        self.evict_events(now, DOMINANCE_WINDOW_SEC)
        self.prune_rows(now)

    def evict_samples(self, now: datetime, seconds: int) -> None:
        cutoff = now - timedelta(seconds=seconds)
        while self.book_samples and self.book_samples[0].ts < cutoff:
            self.book_samples.popleft()

    def evict_events(self, now: datetime, seconds: int) -> None:
        cutoff = now - timedelta(seconds=seconds)
        while self.book_events and self.book_events[0].ts < cutoff:
            self.book_events.popleft()

    def prune_rows(self, now: datetime) -> None:
        cutoff = now - timedelta(seconds=ROW_RETENTION_SEC)
        self.rows = [row for row in self.rows if row.ts >= cutoff]

    @staticmethod
    def evict_timed(values: deque[tuple[datetime, float]], now: datetime, seconds: int) -> None:
        cutoff = now - timedelta(seconds=seconds)
        while values and values[0][0] < cutoff:
            values.popleft()

    def mean_std(self, now: datetime, selector) -> tuple[float, float]:
        cutoff = now - timedelta(seconds=BOOK_LOOKBACK_SEC)
        vals = [selector(s) for s in self.book_samples if s.ts >= cutoff]
        if len(vals) < 2:
            return 0.0, 0.0
        mean = sum(vals) / len(vals)
        var = sum(v * v for v in vals) / len(vals) - mean * mean
        return mean, math.sqrt(var) if var > 0 else 0.0

    @staticmethod
    def std_over(values: deque[tuple[datetime, float]], now: datetime, seconds: int) -> float:
        cutoff = now - timedelta(seconds=seconds)
        vals = [value for ts, value in values if ts >= cutoff]
        if len(vals) < 2:
            return 0.0
        mean = sum(vals) / len(vals)
        var = sum(v * v for v in vals) / len(vals) - mean * mean
        return math.sqrt(var) if var > 0 else 0.0

    @staticmethod
    def mean_std_of(values: deque[tuple[datetime, float]], now: datetime, seconds: int) -> tuple[float, float]:
        cutoff = now - timedelta(seconds=seconds)
        vals = [value for ts, value in values if ts >= cutoff]
        if len(vals) < 2:
            return 0.0, 0.0
        mean = sum(vals) / len(vals)
        var = sum(v * v for v in vals) / len(vals) - mean * mean
        return mean, math.sqrt(var) if var > 0 else 0.0

    def update_vod(self, now: datetime, sample: BookSample) -> None:
        curr = sample.bid_inner + sample.ask_inner
        if self.prev_inner_depth is not None:
            self.inner_deltas.append((now, curr - self.prev_inner_depth))
            self.evict_timed(self.inner_deltas, now, BOOK_LOOKBACK_SEC * 2)
            if len(self.inner_deltas) >= 4:
                vod = self.std_over(self.inner_deltas, now, BOOK_LOOKBACK_SEC)
                self.vod_values.append((now, vod))
                self.evict_timed(self.vod_values, now, BOOK_LOOKBACK_SEC * 8)
                if len(self.vod_values) >= 8:
                    mean, std = self.mean_std_of(self.vod_values, now, BOOK_LOOKBACK_SEC * 4)
                    z = (vod - mean) / max(0.1, std)
                    if abs(z) >= max(4.0, EVENT_Z_THRESHOLD + 1.0):
                        self.add_or_update_chaos(now, sample.mid_tick, abs(z))
        self.prev_inner_depth = curr

    def try_fire(
        self,
        ts: datetime,
        price_tick: int,
        z: float,
        bias_pos: int,
        pos_label: str,
        neg_label: str,
    ) -> None:
        if abs(z) <= EVENT_Z_THRESHOLD:
            return
        event = BookEvent(
            ts=ts,
            price_tick=price_tick,
            bias=bias_pos if z > 0 else -bias_pos,
            abs_z=abs(z),
            kind=pos_label if z > 0 else neg_label,
        )
        self.book_events.append(event)
        self.all_book_events.append(event)

    def update_build_bands(
        self,
        ts: datetime,
        price_tick: int,
        z_bid_inner: float,
        z_ask_inner: float,
    ) -> None:
        self.prune_build_band_pending(ts)
        threshold = self.band_build_z
        if z_bid_inner > threshold:
            self.add_build_band_event(
                BuildBandEvent(ts, price_tick, "demand", z_bid_inner),
            )
        if z_ask_inner > threshold:
            self.add_build_band_event(
                BuildBandEvent(ts, price_tick, "supply", z_ask_inner),
            )

    def add_build_band_event(self, ev: BuildBandEvent) -> None:
        cluster_ticks = self.band_cluster_ticks
        cluster_sec = self.band_cluster_sec

        for band in self.build_bands:
            if band.breached_ts is not None:
                continue
            if band.side != ev.side:
                continue
            if (ev.ts - band.last_update_ts).total_seconds() > cluster_sec:
                continue
            lo = band.min_tick - cluster_ticks
            hi = band.max_tick + cluster_ticks
            if ev.price_tick < lo or ev.price_tick > hi:
                continue

            old = band_range(band.min_tick, band.max_tick)
            band.min_tick = min(band.min_tick, ev.price_tick)
            band.max_tick = max(band.max_tick, ev.price_tick)
            band.last_update_ts = ev.ts
            band.event_count += 1
            band.max_abs_z = max(band.max_abs_z, ev.abs_z)
            self.build_band_mutations.append(
                BuildBandMutation(
                    action="UPDATE",
                    action_ts=ev.ts,
                    band_id=band.id,
                    side=band.side,
                    min_tick=band.min_tick,
                    max_tick=band.max_tick,
                    event_count=band.event_count,
                    max_abs_z=band.max_abs_z,
                    current_mid_tick=self.current_mid_tick,
                    old=old,
                )
            )
            return

        members = [ev]
        for pending in self.build_band_pending:
            if pending.side != ev.side:
                continue
            if abs(pending.price_tick - ev.price_tick) > cluster_ticks:
                continue
            if (ev.ts - pending.ts).total_seconds() > cluster_sec:
                continue
            members.append(pending)

        if len(members) >= self.band_cluster_n:
            band = BuildBand(
                id=self.next_build_band_id,
                side=ev.side,
                min_tick=min(m.price_tick for m in members),
                max_tick=max(m.price_tick for m in members),
                start_ts=min(m.ts for m in members),
                formed_ts=ev.ts,
                last_update_ts=max(m.ts for m in members),
                event_count=len(members),
                max_abs_z=max(m.abs_z for m in members),
            )
            self.next_build_band_id += 1
            self.build_bands.append(band)
            self.build_band_mutations.append(
                BuildBandMutation(
                    action="FORM",
                    action_ts=ev.ts,
                    band_id=band.id,
                    side=band.side,
                    min_tick=band.min_tick,
                    max_tick=band.max_tick,
                    event_count=band.event_count,
                    max_abs_z=band.max_abs_z,
                    current_mid_tick=self.current_mid_tick,
                )
            )

            member_ids = {id(member) for member in members}
            self.build_band_pending = deque(
                pending for pending in self.build_band_pending
                if id(pending) not in member_ids
            )
        else:
            self.build_band_pending.append(ev)

    def apply_build_band_price_through(self, ts: datetime, current_mid_tick: int) -> None:
        buffer_ticks = self.band_price_through_buffer_ticks
        for band in self.build_bands:
            if band.breached_ts is not None:
                continue
            breached = (
                band.side == "supply"
                and current_mid_tick > band.max_tick + buffer_ticks
            ) or (
                band.side == "demand"
                and current_mid_tick < band.min_tick - buffer_ticks
            )
            if not breached:
                continue

            band.breached_ts = ts
            band.breach_price_tick = current_mid_tick
            self.build_band_mutations.append(
                BuildBandMutation(
                    action="BREACH",
                    action_ts=ts,
                    band_id=band.id,
                    side=band.side,
                    min_tick=band.min_tick,
                    max_tick=band.max_tick,
                    event_count=band.event_count,
                    max_abs_z=band.max_abs_z,
                    current_mid_tick=current_mid_tick,
                )
            )

    def prune_build_band_pending(self, ts: datetime) -> None:
        cutoff = ts - timedelta(seconds=self.band_cluster_sec)
        while self.build_band_pending and self.build_band_pending[0].ts < cutoff:
            self.build_band_pending.popleft()

    def evaluate_spatial_dominance(self, now: datetime) -> None:
        if (
            self.last_dominance_eval is not None
            and (now - self.last_dominance_eval).total_seconds()
            < DOMINANCE_EVAL_COOLDOWN_SEC
        ):
            return
        self.last_dominance_eval = now

        cutoff = now - timedelta(seconds=DOMINANCE_WINDOW_SEC)
        centers = {
            round_to_grid(ev.price_tick, 4)
            for ev in self.book_events
            if ev.ts >= cutoff
            and abs(round_to_grid(ev.price_tick, 4) - self.current_mid_tick)
            <= DOMINANCE_CURRENT_RELEVANCE_TICKS
        }
        candidates = []
        for center in centers:
            candidate = self.compute_dominance(now, center)
            if candidate is None:
                continue
            if candidate["dominant"] < DOMINANCE_MIN_DENSITY:
                continue
            if candidate["ratio"] < DOMINANCE_RATIO_THRESHOLD:
                continue
            latest_dom = candidate["latest_dom"]
            if latest_dom is None:
                continue
            if (now - latest_dom).total_seconds() > DOMINANCE_FRESH_CAUSE_SEC:
                continue
            candidates.append(candidate)

        accepted = []
        for candidate in sorted(candidates, key=lambda c: c["dominant"], reverse=True):
            if any(
                abs(candidate["price_tick"] - other["price_tick"])
                <= DOMINANCE_ZONE_MERGE_TICKS
                for other in accepted
            ):
                continue
            accepted.append(candidate)
            if len(accepted) >= DOMINANCE_MAX_ZONES_PER_EVAL:
                break

        for candidate in sorted(accepted, key=lambda c: c["price_tick"]):
            side = "demand dom" if candidate["direction"] > 0 else "supply dom"
            text = f"{candidate['ratio']:.1f}x {side}"
            self.add_or_update_row(
                now,
                candidate["price_tick"],
                candidate["direction"],
                text,
                candidate["dominant"],
                candidate["ratio"],
            )

    def compute_dominance(self, now: datetime, center_tick: int) -> dict | None:
        demand = 0.0
        supply = 0.0
        count = 0
        cutoff = now - timedelta(seconds=DOMINANCE_WINDOW_SEC)
        latest_dom: datetime | None = None
        latest_any: datetime | None = None
        events: list[BookEvent] = []

        for ev in self.book_events:
            if ev.ts < cutoff or ev.ts > now:
                continue
            dist = abs(ev.price_tick - center_tick)
            if dist > DOMINANCE_KERNEL_TICKS * 3:
                continue

            age_sec = (now - ev.ts).total_seconds()
            time_weight = 0.5 ** (age_sec / DOMINANCE_HALF_LIFE_SEC)
            x = dist / DOMINANCE_KERNEL_TICKS
            price_weight = math.exp(-0.5 * x * x)
            contribution = ev.abs_z * time_weight * price_weight

            if ev.bias > 0:
                demand += contribution
            else:
                supply += contribution
            count += 1
            events.append(ev)
            latest_any = ev.ts if latest_any is None or ev.ts > latest_any else latest_any

        if count == 0:
            return None

        direction = +1 if demand >= supply else -1
        for ev in events:
            if ev.bias == direction:
                latest_dom = ev.ts if latest_dom is None or ev.ts > latest_dom else latest_dom

        dominant = max(demand, supply)
        opposing = min(demand, supply)
        return {
            "price_tick": center_tick,
            "direction": direction,
            "demand": demand,
            "supply": supply,
            "count": count,
            "ratio": dominant / max(1.0, opposing),
            "dominant": dominant,
            "latest_dom": latest_dom,
            "latest_any": latest_any,
        }

    def add_or_update_row(
        self,
        ts: datetime,
        price_tick: int,
        direction: int,
        text: str,
        strength: float,
        signal_ratio: float,
    ) -> None:
        for r in reversed(self.rows):
            if r.superseded:
                continue
            if r.direction != direction:
                continue
            if abs(r.price_tick - price_tick) > DOMINANCE_ZONE_MERGE_TICKS:
                continue
            if (ts - r.ts).total_seconds() > DOMINANCE_WINDOW_SEC:
                continue
            if not self.should_update_spatial_row(r, ts, price_tick, text, signal_ratio):
                r.strength = max(r.strength, strength)
                return
            old = f"{abbrev(r.price_tick)} {r.text}"
            r.price_tick = price_tick
            r.text = text
            r.strength = max(r.strength, strength)
            r.signal_ratio = signal_ratio
            r.last_update_ts = ts
            r.updates += 1
            self.mutations.append(
                Mutation(
                    action="UPDATE",
                    action_ts=ts,
                    row_ts=r.ts,
                    price_tick=r.price_tick,
                    direction=r.direction,
                    text=r.text,
                    updates=r.updates,
                    old=old,
                    current_mid_tick=self.current_mid_tick,
                )
            )
            return

        for r in self.rows:
            if r.superseded:
                continue
            if r.direction == direction:
                continue
            if (
                abs(r.price_tick - price_tick) <= DOMINANCE_ZONE_MERGE_TICKS
                and (ts - r.ts).total_seconds() <= DOMINANCE_WINDOW_SEC
            ):
                r.superseded = True
                r.superseded_ts = ts

        row = Row(
            id=self.next_row_id,
            ts=ts,
            price_tick=price_tick,
            direction=direction,
            text=text,
            strength=strength,
            last_update_ts=ts,
            signal_ratio=signal_ratio,
        )
        self.next_row_id += 1
        self.rows.append(row)
        self.mutations.append(
            Mutation(
                action="NEW",
                action_ts=ts,
                row_ts=row.ts,
                price_tick=row.price_tick,
                direction=row.direction,
                text=row.text,
                updates=row.updates,
                old="",
                current_mid_tick=self.current_mid_tick,
            )
        )

    @staticmethod
    def should_update_spatial_row(
        row: Row,
        ts: datetime,
        price_tick: int,
        text: str,
        signal_ratio: float,
    ) -> bool:
        if abs(row.price_tick - price_tick) >= SPATIAL_ROW_UPDATE_PRICE_TICKS:
            return True

        if row.signal_ratio > 0 and signal_ratio > 0:
            ratio_delta = abs(signal_ratio - row.signal_ratio)
            if ratio_delta >= SPATIAL_ROW_UPDATE_RATIO_DELTA:
                return True
            if ratio_delta / max(1.0, abs(row.signal_ratio)) >= SPATIAL_ROW_UPDATE_RATIO_RELATIVE:
                return True

        return (
            text != row.text
            and (ts - row.last_update_ts).total_seconds()
            >= SPATIAL_ROW_UPDATE_FORCE_SECONDS
        )

    def add_or_update_chaos(self, ts: datetime, price_tick: int, strength: float) -> None:
        for r in reversed(self.rows):
            if r.superseded:
                continue
            if r.direction != 0 or r.text != "VOD chaos":
                continue
            if abs(r.price_tick - price_tick) > ROW_MERGE_TICKS:
                continue
            if (ts - r.ts).total_seconds() > ROW_MERGE_SECONDS:
                continue
            old = f"{abbrev(r.price_tick)} {r.text}"
            r.ts = ts
            r.price_tick = price_tick
            r.strength = max(r.strength, strength)
            r.updates += 1
            self.mutations.append(
                Mutation(
                    action="UPDATE",
                    action_ts=ts,
                    row_ts=r.ts,
                    price_tick=r.price_tick,
                    direction=r.direction,
                    text=r.text,
                    updates=r.updates,
                    old=old,
                    current_mid_tick=self.current_mid_tick,
                )
            )
            return

        row = Row(
            id=self.next_row_id,
            ts=ts,
            price_tick=price_tick,
            direction=0,
            text="VOD chaos",
            strength=strength,
            last_update_ts=ts,
        )
        self.next_row_id += 1
        self.rows.append(row)
        self.mutations.append(
            Mutation(
                action="NEW",
                action_ts=ts,
                row_ts=row.ts,
                price_tick=row.price_tick,
                direction=row.direction,
                text=row.text,
                updates=row.updates,
                old="",
                current_mid_tick=self.current_mid_tick,
            )
        )

    def dominance_breakdown(self, now: datetime, center_tick: int) -> dict:
        demand = 0.0
        supply = 0.0
        cutoff = now - timedelta(seconds=DOMINANCE_WINDOW_SEC)
        parts = []
        for ev in self.all_book_events:
            if ev.ts < cutoff or ev.ts > now:
                continue
            dist = abs(ev.price_tick - center_tick)
            if dist > DOMINANCE_KERNEL_TICKS * 3:
                continue
            age_sec = (now - ev.ts).total_seconds()
            time_weight = 0.5 ** (age_sec / DOMINANCE_HALF_LIFE_SEC)
            x = dist / DOMINANCE_KERNEL_TICKS
            price_weight = math.exp(-0.5 * x * x)
            contribution = ev.abs_z * time_weight * price_weight
            if ev.bias > 0:
                demand += contribution
            else:
                supply += contribution
            parts.append((contribution, ev, age_sec, dist))
        dominant = max(demand, supply)
        opposing = min(demand, supply)
        return {
            "demand": demand,
            "supply": supply,
            "ratio": dominant / max(1.0, opposing),
            "direction": +1 if demand >= supply else -1,
            "parts": sorted(parts, key=lambda p: p[0], reverse=True),
        }


def build_sample(row: dict) -> BookSample:
    bid_inner = sum(
        float(row[f"bid_size_{i}"])
        for i in range(INNER_LEVELS)
        if float(row[f"bid_size_{i}"]) > 0
    )
    ask_inner = sum(
        float(row[f"ask_size_{i}"])
        for i in range(INNER_LEVELS)
        if float(row[f"ask_size_{i}"]) > 0
    )

    b_wsum = 0.0
    b_size = 0.0
    a_wsum = 0.0
    a_size = 0.0
    for i in range(BROAD_LEVELS):
        bs = float(row[f"bid_size_{i}"])
        if bs > 0:
            b_wsum += abs(int(row[f"bid_offset_{i}"])) * bs
            b_size += bs
        az = float(row[f"ask_size_{i}"])
        if az > 0:
            a_wsum += abs(int(row[f"ask_offset_{i}"])) * az
            a_size += az

    ts = datetime.fromtimestamp(int(row["timestamp_us"]) / 1_000_000, tz=timezone.utc)
    return BookSample(
        ts=ts,
        mid_tick=int(row["ref_tick"]),
        bid_inner=bid_inner,
        ask_inner=ask_inner,
        bid_centroid=b_wsum / b_size if b_size > 0 else 0.0,
        ask_centroid=a_wsum / a_size if a_size > 0 else 0.0,
    )


def round_to_grid(tick: int, grid_ticks: int) -> int:
    return int(round(tick / max(1, grid_ticks)) * max(1, grid_ticks))


def abbrev(tick: int) -> str:
    price = tick * TICK_SIZE
    whole = math.floor(price)
    last = whole % 1000
    frac = price - whole
    if abs(frac) < 0.0001:
        return f"{last:03d}"
    return f"{last:03d}{frac:.2f}".replace("0.", ".")


def band_range(min_tick: int, max_tick: int) -> str:
    if min_tick == max_tick:
        return abbrev(min_tick)
    return f"{abbrev(min_tick)}-{abbrev(max_tick)}"


def parse_ny(day: str, value: str) -> datetime:
    fmt = "%Y-%m-%d %H:%M:%S" if value.count(":") == 2 else "%Y-%m-%d %H:%M"
    return datetime.strptime(f"{day} {value}", fmt).replace(tzinfo=NY).astimezone(timezone.utc)


def ny_hms(ts: datetime) -> str:
    return ts.astimezone(NY).strftime("%H:%M:%S")


def snapshot_timing_summary(
    snap: pl.DataFrame,
    gap_threshold_sec: float,
) -> tuple[datetime, datetime, int, list[tuple[datetime, datetime, float]]]:
    timestamps = snap.get_column("timestamp_us").to_list()
    if not timestamps:
        raise ValueError("snapshot capture loaded zero rows")

    duplicate_count = len(timestamps) - len(set(timestamps))
    gaps: list[tuple[datetime, datetime, float]] = []
    prev = int(timestamps[0])
    for value in timestamps[1:]:
        curr = int(value)
        delta_sec = (curr - prev) / 1_000_000.0
        if delta_sec > gap_threshold_sec:
            gaps.append(
                (
                    datetime.fromtimestamp(prev / 1_000_000, tz=timezone.utc),
                    datetime.fromtimestamp(curr / 1_000_000, tz=timezone.utc),
                    delta_sec,
                )
            )
        prev = curr

    first = datetime.fromtimestamp(int(timestamps[0]) / 1_000_000, tz=timezone.utc)
    last = datetime.fromtimestamp(int(timestamps[-1]) / 1_000_000, tz=timezone.utc)
    return first, last, duplicate_count, gaps


def load_snapshots(symbol_dir: str, start: datetime, end: datetime) -> pl.DataFrame:
    return load_capture_window(
        "snapshots",
        symbol_dir,
        start,
        end,
        snapshot_columns(BROAD_LEVELS),
        inclusive_end=True,
    )


def print_build_bands(engine: Engine, window_start: datetime, window_end: datetime) -> None:
    print("\nBuild band mutations in window:")
    touched_ids: set[int] = set()
    count = 0
    for mutation in engine.build_band_mutations:
        if mutation.action_ts < window_start or mutation.action_ts > window_end:
            continue
        touched_ids.add(mutation.band_id)
        count += 1
        side = "DEMAND" if mutation.side == "demand" else "SUPPLY"
        extra = f"  from {mutation.old}" if mutation.action == "UPDATE" and mutation.old else ""
        print(
            f"{ny_hms(mutation.action_ts)} {mutation.action:<6} "
            f"band#{mutation.band_id:<3} {side:<6} "
            f"{band_range(mutation.min_tick, mutation.max_tick):>13} "
            f"events={mutation.event_count:<2} "
            f"maxz={mutation.max_abs_z:4.1f} "
            f"current={abbrev(mutation.current_mid_tick):>7}{extra}"
        )
    if count == 0:
        print("(none)")

    if not touched_ids:
        return

    print("\nFinal state for touched build bands:")
    for band in engine.build_bands:
        if band.id not in touched_ids:
            continue
        status = (
            f"breached@{ny_hms(band.breached_ts)} {abbrev(band.breach_price_tick)}"
            if band.breached_ts is not None and band.breach_price_tick is not None
            else "active"
        )
        side = "DEMAND" if band.side == "demand" else "SUPPLY"
        print(
            f"band#{band.id:<3} {side:<6} "
            f"{band_range(band.min_tick, band.max_tick):>13} "
            f"formed={ny_hms(band.formed_ts)} "
            f"last={ny_hms(band.last_update_ts)} "
            f"events={band.event_count:<2} "
            f"maxz={band.max_abs_z:4.1f} "
            f"{status}"
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", required=True)
    parser.add_argument("--symbol-dir", default="NQM6")
    parser.add_argument("--window", default="14:45-15:05")
    parser.add_argument("--warmup-min", type=int, default=30)
    parser.add_argument("--inspect-time")
    parser.add_argument("--inspect-price", type=float)
    parser.add_argument("--print-events", action="store_true")
    parser.add_argument("--event-price-lt", type=float)
    parser.add_argument("--event-price-gt", type=float)
    parser.add_argument("--gap-threshold-sec", type=float, default=5.0)
    parser.add_argument("--print-bands", action="store_true")
    parser.add_argument("--bands-only", action="store_true")
    parser.add_argument("--band-build-z", type=float, default=BUILD_BAND_BUILD_Z)
    parser.add_argument("--band-cluster-n", type=int, default=BUILD_BAND_CLUSTER_N)
    parser.add_argument("--band-cluster-ticks", type=int, default=BUILD_BAND_CLUSTER_TICKS)
    parser.add_argument("--band-cluster-sec", type=int, default=BUILD_BAND_CLUSTER_SEC)
    parser.add_argument(
        "--band-price-through-buffer-ticks",
        type=int,
        default=BUILD_BAND_PRICE_THROUGH_BUFFER_TICKS,
    )
    parser.add_argument("--summary-only", action="store_true")
    args = parser.parse_args()

    start_s, end_s = args.window.split("-", 1)
    window_start = parse_ny(args.date, start_s)
    window_end = parse_ny(args.date, end_s)
    replay_start = window_start - timedelta(minutes=args.warmup_min)

    snap = load_snapshots(args.symbol_dir, replay_start, window_end)
    first_snap, last_snap, duplicate_count, gaps = snapshot_timing_summary(
        snap,
        args.gap_threshold_sec,
    )

    engine = Engine(
        band_build_z=args.band_build_z,
        band_cluster_n=args.band_cluster_n,
        band_cluster_ticks=args.band_cluster_ticks,
        band_cluster_sec=args.band_cluster_sec,
        band_price_through_buffer_ticks=args.band_price_through_buffer_ticks,
    )
    for row in snap.iter_rows(named=True):
        engine.on_sample(build_sample(row))

    print(
        f"{args.date} {args.window}  rows={snap.height:,}  "
        f"events_total={len(engine.all_book_events):,}  "
        f"events_retained={len(engine.book_events):,}"
    )
    if args.print_bands or args.bands_only:
        print(
            "band_params="
            f"z>{engine.band_build_z:g}, "
            f"n={engine.band_cluster_n}, "
            f"ticks={engine.band_cluster_ticks}, "
            f"sec={engine.band_cluster_sec}, "
            f"through={engine.band_price_through_buffer_ticks}"
        )
    print(
        f"snapshot_span={ny_hms(first_snap)}-{ny_hms(last_snap)}  "
        f"duplicate_timestamps={duplicate_count:,}"
    )
    if gaps:
        print(f"\nSnapshot gaps > {args.gap_threshold_sec:.1f}s:")
        for prev, curr, delta_sec in gaps[:12]:
            print(f"{ny_hms(prev)} -> {ny_hms(curr)}  {delta_sec:.1f}s")
        if len(gaps) > 12:
            print(f"... {len(gaps) - 12} more")
    else:
        print(f"\nSnapshot gaps > {args.gap_threshold_sec:.1f}s: none")

    if args.summary_only:
        return

    if args.print_bands or args.bands_only:
        print_build_bands(engine, window_start, window_end)
        if args.bands_only:
            return

    print("\nLedger row mutations in window:")
    for mutation in engine.mutations:
        if mutation.action_ts < window_start or mutation.action_ts > window_end:
            continue
        arrow = "UP  " if mutation.direction > 0 else "DOWN" if mutation.direction < 0 else "DOT "
        extra = f"  from {mutation.old}" if mutation.action == "UPDATE" and mutation.old else ""
        print(
            f"{ny_hms(mutation.action_ts)} {mutation.action:<6} "
            f"row@{ny_hms(mutation.row_ts)} "
            f"{abbrev(mutation.price_tick):>7} {arrow} {mutation.text:<16} "
            f"current={abbrev(mutation.current_mid_tick):>7} "
            f"updates={mutation.updates}{extra}"
        )

    print("\nFinal non-superseded rows:")
    for row in engine.rows[-20:]:
        if row.superseded:
            continue
        arrow = "UP  " if row.direction > 0 else "DOWN" if row.direction < 0 else "DOT "
        print(
            f"{ny_hms(row.ts)} {abbrev(row.price_tick):>7} {arrow} "
            f"{row.text:<16} updates={row.updates}"
        )

    if args.print_events:
        print("\nBook events in window:")
        count = 0
        for ev in engine.all_book_events:
            if ev.ts < window_start or ev.ts > window_end:
                continue
            price = ev.price_tick * TICK_SIZE
            if args.event_price_lt is not None and price >= args.event_price_lt:
                continue
            if args.event_price_gt is not None and price <= args.event_price_gt:
                continue
            bias = "D" if ev.bias > 0 else "S"
            print(f"{ny_hms(ev.ts)} {bias} {ev.kind:<9} {price:8.2f} z={ev.abs_z:4.2f}")
            count += 1
        if count == 0:
            print("(none)")

    if args.inspect_time and args.inspect_price is not None:
        inspect_ts = parse_ny(args.date, args.inspect_time)
        center_tick = int(round(args.inspect_price / TICK_SIZE))
        center_tick = round_to_grid(center_tick, 4)
        info = engine.dominance_breakdown(inspect_ts, center_tick)
        label = "demand" if info["direction"] > 0 else "supply"
        print(
            f"\nBreakdown at {args.inspect_time} for {center_tick * TICK_SIZE:.2f} "
            f"({abbrev(center_tick)}): {label} "
            f"D={info['demand']:.2f} S={info['supply']:.2f} "
            f"ratio={info['ratio']:.2f} n={len(info['parts'])}"
        )
        print("Top contributors:")
        for contribution, ev, age_sec, dist in info["parts"][:20]:
            bias = "D" if ev.bias > 0 else "S"
            print(
                f"{ny_hms(ev.ts)} {bias} {ev.kind:<9} "
                f"px={ev.price_tick * TICK_SIZE:8.2f} "
                f"z={ev.abs_z:4.2f} age={age_sec:6.1f}s "
                f"dist={dist:2d} contrib={contribution:5.2f}"
            )


if __name__ == "__main__":
    main()
