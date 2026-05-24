"""Forward-only probe for VOD-anchored auction stacks.

The goal is to test a discretionary idea, not to optimize a signal:

    VOD marks an unstable/indecisive auction.
    Subsequent directional L2 events can establish upper/lower stack edges.
    A later retest of an old edge matters when fresh same-side pressure appears
    inside the stack.

This script deliberately walks the capture chronologically. Edges are only
"confirmed" after price moves away from the event zone in the expected
direction. Fresh pressure is only recorded after the relevant edge has already
been confirmed. No future price is used to create a marker at the event time.
"""

from __future__ import annotations

import argparse
import math
import os
from collections import deque
from dataclasses import dataclass, field
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
class DirEvent:
    ts: datetime
    price_tick: int
    kind: str
    bias: int
    abs_z: float

    @property
    def side(self) -> str:
        return "DEMAND" if self.bias > 0 else "SUPPLY"


@dataclass
class EdgeZone:
    side: str
    min_tick: int
    max_tick: int
    first_ts: datetime
    last_ts: datetime
    score: float
    max_z: float
    event_count: int
    kinds: set[str] = field(default_factory=set)
    confirmed_ts: datetime | None = None
    confirm_price_tick: int | None = None

    @property
    def center_tick(self) -> int:
        return int(round((self.min_tick + self.max_tick) / 2))

    def absorb(self, ev: DirEvent) -> None:
        self.min_tick = min(self.min_tick, ev.price_tick)
        self.max_tick = max(self.max_tick, ev.price_tick)
        self.last_ts = ev.ts
        self.score += ev.abs_z
        self.max_z = max(self.max_z, ev.abs_z)
        self.event_count += 1
        self.kinds.add(ev.kind)


@dataclass
class FreshPress:
    ts: datetime
    price_tick: int
    side: str
    kind: str
    abs_z: float
    note: str


@dataclass
class VodStack:
    stack_id: int
    start_ts: datetime
    last_vod_ts: datetime
    anchor_min_tick: int
    anchor_max_tick: int
    max_vod_z: float
    edges: list[EdgeZone] = field(default_factory=list)
    fresh: list[FreshPress] = field(default_factory=list)

    def merge_vod(self, ts: datetime, tick: int, vod_z: float) -> None:
        self.last_vod_ts = ts
        self.anchor_min_tick = min(self.anchor_min_tick, tick)
        self.anchor_max_tick = max(self.anchor_max_tick, tick)
        self.max_vod_z = max(self.max_vod_z, vod_z)

    @property
    def anchor_center_tick(self) -> int:
        return int(round((self.anchor_min_tick + self.anchor_max_tick) / 2))

    def upper_supply(self) -> EdgeZone | None:
        supply = [e for e in self.edges if e.side == "SUPPLY" and e.confirmed_ts is not None]
        return max(supply, key=lambda e: (e.max_tick, e.score), default=None)

    def lower_demand(self) -> EdgeZone | None:
        demand = [e for e in self.edges if e.side == "DEMAND" and e.confirmed_ts is not None]
        return min(demand, key=lambda e: (e.min_tick, -e.score), default=None)


def ny_dt(day: str, hhmm: str) -> datetime:
    fmt = "%Y-%m-%d %H:%M:%S" if hhmm.count(":") == 2 else "%Y-%m-%d %H:%M"
    return datetime.strptime(f"{day} {hhmm}", fmt).replace(tzinfo=NY)


def parse_window(day: str, window: str | None) -> tuple[datetime, datetime]:
    if window:
        start_s, end_s = window.split("-", 1)
        return ny_dt(day, start_s).astimezone(timezone.utc), ny_dt(day, end_s).astimezone(timezone.utc)
    start = datetime.combine(datetime.fromisoformat(day).date(), time(9, 30), NY)
    end = datetime.combine(datetime.fromisoformat(day).date(), time(16, 0), NY)
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc)


def ny_hms(ts: datetime) -> str:
    return ts.astimezone(NY).strftime("%H:%M:%S")


def px(tick: int) -> float:
    return tick * TICK_SIZE


def abbrev_zone(lo: int, hi: int) -> str:
    if lo == hi:
        return f"{px(lo):.2f}"
    return f"{px(lo):.2f}-{px(hi):.2f}"


def mean_std(vals: list[float]) -> tuple[float, float]:
    if len(vals) < 2:
        return 0.0, 0.0
    mean = sum(vals) / len(vals)
    var = sum(v * v for v in vals) / len(vals) - mean * mean
    return mean, math.sqrt(var) if var > 0 else 0.0


def evict_samples(items: deque[Sample], now: datetime, seconds: int) -> None:
    cutoff = now - timedelta(seconds=seconds)
    while items and items[0].ts < cutoff:
        items.popleft()


def evict_timed(items: deque[tuple[datetime, float]], now: datetime, seconds: int) -> None:
    cutoff = now - timedelta(seconds=seconds)
    while items and items[0][0] < cutoff:
        items.popleft()


def std_over(items: deque[tuple[datetime, float]], now: datetime, seconds: int) -> float:
    cutoff = now - timedelta(seconds=seconds)
    vals = [v for t, v in items if t >= cutoff]
    return mean_std(vals)[1]


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

    b_wsum = b_size = a_wsum = a_size = 0.0
    for i in range(BROAD_LEVELS):
        bs = float(row[f"bid_size_{i}"])
        az = float(row[f"ask_size_{i}"])
        if math.isfinite(bs) and bs > 0:
            b_wsum += abs(int(row[f"bid_offset_{i}"])) * bs
            b_size += bs
        if math.isfinite(az) and az > 0:
            a_wsum += abs(int(row[f"ask_offset_{i}"])) * az
            a_size += az

    return Sample(
        ts=datetime.fromtimestamp(int(row["timestamp_us"]) / 1_000_000, tz=timezone.utc),
        mid_tick=int(row["ref_tick"]),
        bid_inner=bid_inner,
        ask_inner=ask_inner,
        bid_centroid=b_wsum / b_size if b_size > 0 else 0.0,
        ask_centroid=a_wsum / a_size if a_size > 0 else 0.0,
    )


def fire_event(ts: datetime, tick: int, z: float, bias_pos: int, pos_kind: str, neg_kind: str, event_z: float) -> DirEvent | None:
    if abs(z) <= event_z:
        return None
    return DirEvent(
        ts=ts,
        price_tick=tick,
        kind=pos_kind if z > 0 else neg_kind,
        bias=bias_pos if z > 0 else -bias_pos,
        abs_z=abs(z),
    )


def add_edge(stack: VodStack, ev: DirEvent, zone_merge_ticks: int) -> None:
    for edge in stack.edges:
        if edge.side != ev.side:
            continue
        if abs(ev.price_tick - edge.center_tick) > zone_merge_ticks:
            continue
        edge.absorb(ev)
        return

    stack.edges.append(
        EdgeZone(
            side=ev.side,
            min_tick=ev.price_tick,
            max_tick=ev.price_tick,
            first_ts=ev.ts,
            last_ts=ev.ts,
            score=ev.abs_z,
            max_z=ev.abs_z,
            event_count=1,
            kinds={ev.kind},
        )
    )


def update_edge_confirmations(stack: VodStack, sample: Sample, confirm_move_ticks: int) -> None:
    for edge in stack.edges:
        if edge.confirmed_ts is not None:
            continue
        if edge.side == "SUPPLY" and sample.mid_tick <= edge.min_tick - confirm_move_ticks:
            edge.confirmed_ts = sample.ts
            edge.confirm_price_tick = sample.mid_tick
        elif edge.side == "DEMAND" and sample.mid_tick >= edge.max_tick + confirm_move_ticks:
            edge.confirmed_ts = sample.ts
            edge.confirm_price_tick = sample.mid_tick


def maybe_record_fresh(stack: VodStack, ev: DirEvent, now: datetime) -> None:
    upper = stack.upper_supply()
    lower = stack.lower_demand()
    if upper is None and lower is None:
        return

    lo = lower.min_tick if lower else min(stack.anchor_min_tick, ev.price_tick)
    hi = upper.max_tick if upper else max(stack.anchor_max_tick, ev.price_tick)
    inside_stack = lo <= ev.price_tick <= hi
    if not inside_stack:
        return

    if ev.side == "SUPPLY" and upper and upper.confirmed_ts and ev.ts > upper.confirmed_ts:
        note = "fresh supply inside stack"
    elif ev.side == "DEMAND" and lower and lower.confirmed_ts and ev.ts > lower.confirmed_ts:
        note = "fresh demand inside stack"
    else:
        return

    if stack.fresh and stack.fresh[-1].side == ev.side and abs(stack.fresh[-1].price_tick - ev.price_tick) <= 8 and (now - stack.fresh[-1].ts).total_seconds() <= 10:
        return

    stack.fresh.append(
        FreshPress(
            ts=ev.ts,
            price_tick=ev.price_tick,
            side=ev.side,
            kind=ev.kind,
            abs_z=ev.abs_z,
            note=note,
        )
    )


def summarize_stack(stack: VodStack, start: datetime, end: datetime) -> list[str]:
    if stack.start_ts > end or stack.last_vod_ts < start:
        return []

    upper = stack.upper_supply()
    lower = stack.lower_demand()
    confirmed = [e for e in stack.edges if e.confirmed_ts is not None]
    if upper is None and lower is None and not stack.fresh:
        return []

    lines: list[str] = []
    anchor = abbrev_zone(stack.anchor_min_tick, stack.anchor_max_tick)
    lines.append(
        f"Stack {stack.stack_id:02d}  VOD {ny_hms(stack.start_ts)}-{ny_hms(stack.last_vod_ts)} "
        f"anchor={anchor} maxVodZ={stack.max_vod_z:.2f}"
    )
    if upper:
        kinds = "/".join(sorted(upper.kinds))
        lines.append(
            f"  upper supply edge {abbrev_zone(upper.min_tick, upper.max_tick)} "
            f"events={upper.event_count} score={upper.score:.1f} maxZ={upper.max_z:.2f} "
            f"event@{ny_hms(upper.first_ts)} confirm@{ny_hms(upper.confirmed_ts)} "
            f"via {kinds}"
        )
    if lower:
        kinds = "/".join(sorted(lower.kinds))
        lines.append(
            f"  lower demand edge {abbrev_zone(lower.min_tick, lower.max_tick)} "
            f"events={lower.event_count} score={lower.score:.1f} maxZ={lower.max_z:.2f} "
            f"event@{ny_hms(lower.first_ts)} confirm@{ny_hms(lower.confirmed_ts)} "
            f"via {kinds}"
        )

    other_edges = [
        e for e in confirmed
        if e is not upper and e is not lower and e.score >= 4.0
    ]
    other_edges.sort(key=lambda e: (e.side, e.first_ts, e.min_tick))
    if other_edges:
        lines.append("  other confirmed zones:")
        for e in other_edges[:8]:
            lines.append(
                f"    {ny_hms(e.first_ts)} {e.side:<6} {abbrev_zone(e.min_tick, e.max_tick)} "
                f"score={e.score:.1f} confirm={ny_hms(e.confirmed_ts)} "
                f"{'/'.join(sorted(e.kinds))}"
            )

    if stack.fresh:
        lines.append("  fresh pressure after edge confirmation:")
        for f in stack.fresh[:12]:
            lines.append(
                f"    {ny_hms(f.ts)} {f.side:<6} {f.kind:<9} {px(f.price_tick):8.2f} "
                f"z={f.abs_z:.2f}  {f.note}"
            )
        if len(stack.fresh) > 12:
            lines.append(f"    ... {len(stack.fresh) - 12} more")
    lines.append("")
    return lines


def run(args: argparse.Namespace) -> tuple[Path, list[VodStack]]:
    start, end = parse_window(args.date, args.window)
    rows = load_snapshots(args.date, args.symbol_dir, start, end, args.warmup_min)

    samples: deque[Sample] = deque()
    inner_deltas: deque[tuple[datetime, float]] = deque()
    vod_values: deque[tuple[datetime, float]] = deque()
    prev_inner: float | None = None
    stacks: list[VodStack] = []
    next_stack_id = 1

    for row in rows.iter_rows(named=True):
        sample = build_sample(row)
        now = sample.ts
        samples.append(sample)
        evict_samples(samples, now, args.lookback_sec * 2)
        if len(samples) < 5:
            prev_inner = sample.bid_inner + sample.ask_inner
            continue

        def z_of(selector, floor: float) -> float:
            vals = [selector(s) for s in samples if s.ts >= now - timedelta(seconds=args.lookback_sec)]
            mean, std = mean_std(vals)
            return (selector(sample) - mean) / max(floor, std)

        z_bi = z_of(lambda s: s.bid_inner, 1.0)
        z_ai = z_of(lambda s: s.ask_inner, 1.0)
        z_bc = z_of(lambda s: s.bid_centroid, 0.01)
        z_ac = z_of(lambda s: s.ask_centroid, 0.01)

        curr_inner = sample.bid_inner + sample.ask_inner
        z_vod = float("nan")
        if prev_inner is not None:
            inner_deltas.append((now, curr_inner - prev_inner))
            evict_timed(inner_deltas, now, args.lookback_sec * 2)
            if len(inner_deltas) >= 4:
                vod = std_over(inner_deltas, now, args.lookback_sec)
                vod_values.append((now, vod))
                evict_timed(vod_values, now, args.lookback_sec * 8)
                if len(vod_values) >= 8:
                    baseline = [v for t, v in vod_values if t >= now - timedelta(seconds=args.lookback_sec * 4)]
                    m, s = mean_std(baseline)
                    z_vod = (vod - m) / max(0.1, s)
        prev_inner = curr_inner

        active_stacks = [
            stack for stack in stacks
            if 0 <= (now - stack.start_ts).total_seconds() <= args.stack_horizon_min * 60
        ]
        for stack in active_stacks:
            update_edge_confirmations(stack, sample, args.confirm_move_ticks)

        if start <= now <= end and math.isfinite(z_vod) and z_vod >= args.vod_z:
            last = stacks[-1] if stacks else None
            merge = False
            if last is not None:
                close_in_time = (now - last.last_vod_ts).total_seconds() <= args.vod_merge_sec
                close_in_price = (
                    last.anchor_min_tick - args.vod_merge_ticks
                    <= sample.mid_tick
                    <= last.anchor_max_tick + args.vod_merge_ticks
                )
                merge = close_in_time and close_in_price
            if merge:
                last.merge_vod(now, sample.mid_tick, z_vod)
            else:
                stacks.append(
                    VodStack(
                        stack_id=next_stack_id,
                        start_ts=now,
                        last_vod_ts=now,
                        anchor_min_tick=sample.mid_tick,
                        anchor_max_tick=sample.mid_tick,
                        max_vod_z=z_vod,
                    )
                )
                next_stack_id += 1

        events = [
            fire_event(now, sample.mid_tick, z_bi, +1, "BID_BUILD", "BID_PULL", args.event_z),
            fire_event(now, sample.mid_tick, z_ai, -1, "ASK_BUILD", "ASK_PULL", args.event_z),
            fire_event(now, sample.mid_tick, z_bc, -1, "BID_OUT", "BID_IN", args.event_z),
            fire_event(now, sample.mid_tick, z_ac, +1, "ASK_OUT", "ASK_IN", args.event_z),
        ]
        for ev in [e for e in events if e is not None]:
            if not (start <= ev.ts <= end):
                continue
            for stack in active_stacks:
                if ev.ts <= stack.start_ts:
                    continue
                if ev.abs_z >= args.edge_z:
                    add_edge(stack, ev, args.edge_merge_ticks)
                maybe_record_fresh(stack, ev, now)

    out = Path(args.out_dir) / f"vod_stack_probe_{args.date}.txt"
    out.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"{args.date} {args.symbol_dir} VOD stack probe",
        (
            f"vod_z={args.vod_z} event_z={args.event_z} edge_z={args.edge_z} "
            f"merge={args.edge_merge_ticks}t confirm_move={args.confirm_move_ticks}t "
            f"horizon={args.stack_horizon_min}m"
        ),
        "Forward-only: edges confirm only after price moves away; fresh pressure records only after confirmation.",
        "",
    ]
    for stack in stacks:
        lines.extend(summarize_stack(stack, start, end))

    out.write_text("\n".join(lines), encoding="utf-8")
    return out, stacks


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", required=True)
    parser.add_argument("--symbol-dir", default=os.environ.get("SYMBOL_DIR", "NQM6"))
    parser.add_argument("--capture-root", default="", help=argparse.SUPPRESS)
    parser.add_argument("--window", help="NY time window, e.g. 09:30-16:00")
    parser.add_argument("--warmup-min", type=int, default=30)
    parser.add_argument("--lookback-sec", type=int, default=30)
    parser.add_argument("--event-z", type=float, default=2.5)
    parser.add_argument("--vod-z", type=float, default=4.0)
    parser.add_argument("--edge-z", type=float, default=3.0)
    parser.add_argument("--vod-merge-sec", type=int, default=75)
    parser.add_argument("--vod-merge-ticks", type=int, default=36)
    parser.add_argument("--edge-merge-ticks", type=int, default=32)
    parser.add_argument("--confirm-move-ticks", type=int, default=24)
    parser.add_argument("--stack-horizon-min", type=int, default=25)
    parser.add_argument("--out-dir", default=r"C:\Heatmap\research\out")
    args = parser.parse_args()

    out, stacks = run(args)
    interesting = sum(1 for s in stacks if s.upper_supply() or s.lower_demand() or s.fresh)
    print(f"{args.date}: stacks={len(stacks)} interesting={interesting}")
    print(f"  {out}")


if __name__ == "__main__":
    main()
