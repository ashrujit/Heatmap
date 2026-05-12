"""Replay LevelLedger spatial dominance from captured L2 snapshots.

This mirrors the live C# book-event and spatial-dominance path closely enough
to debug timestamp/price provenance issues from a captured session.
"""

from __future__ import annotations

import argparse
import math
import os
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import polars as pl


TICK_SIZE = 0.25
INNER_LEVELS = 10
BROAD_LEVELS = 30
BOOK_LOOKBACK_SEC = 30
EVENT_Z_THRESHOLD = 2.5
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


class Engine:
    def __init__(self) -> None:
        self.book_samples: deque[BookSample] = deque()
        self.book_events: deque[BookEvent] = deque()
        self.all_book_events: list[BookEvent] = []
        self.inner_deltas: deque[tuple[datetime, float]] = deque()
        self.vod_values: deque[tuple[datetime, float]] = deque()
        self.rows: list[Row] = []
        self.next_row_id = 1
        self.last_dominance_eval: datetime | None = None
        self.current_mid_tick = 0
        self.prev_inner_depth: float | None = None
        self.mutations: list[Mutation] = []

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
            old = f"{abbrev(r.price_tick)} {r.text}"
            r.price_tick = price_tick
            r.text = text
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


def parse_ny(day: str, value: str) -> datetime:
    fmt = "%Y-%m-%d %H:%M:%S" if value.count(":") == 2 else "%Y-%m-%d %H:%M"
    return datetime.strptime(f"{day} {value}", fmt).replace(tzinfo=NY).astimezone(timezone.utc)


def ny_hms(ts: datetime) -> str:
    return ts.astimezone(NY).strftime("%H:%M:%S")


def load_snapshots(symbol_dir: str, day: str) -> pl.DataFrame:
    root = rf"C:\Quantower\Settings\Scripts\Indicators\L2_Heatmap\captures\{symbol_dir}"
    path = os.path.join(root, f"snapshots-{day}.parquet")
    cols = ["timestamp_us", "ref_tick"]
    for i in range(BROAD_LEVELS):
        cols.extend(
            [
                f"bid_offset_{i}",
                f"bid_size_{i}",
                f"ask_offset_{i}",
                f"ask_size_{i}",
            ]
        )
    return pl.read_parquet(path, columns=cols).sort("timestamp_us")


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
    args = parser.parse_args()

    start_s, end_s = args.window.split("-", 1)
    window_start = parse_ny(args.date, start_s)
    window_end = parse_ny(args.date, end_s)
    replay_start = window_start - timedelta(minutes=args.warmup_min)

    snap = load_snapshots(args.symbol_dir, args.date).filter(
        (pl.col("timestamp_us") >= int(replay_start.timestamp() * 1_000_000))
        & (pl.col("timestamp_us") <= int(window_end.timestamp() * 1_000_000))
    )

    engine = Engine()
    for row in snap.iter_rows(named=True):
        engine.on_sample(build_sample(row))

    print(
        f"{args.date} {args.window}  rows={snap.height:,}  "
        f"events={len(engine.book_events):,}"
    )
    print("\nSpatial row mutations in window:")
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

    print("\nFinal non-superseded spatial rows:")
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
