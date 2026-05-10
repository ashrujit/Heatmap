"""Replay L2 event CSVs as spatial dominance zones.

This is intentionally a small research harness, not production code. It reads
the existing research/out/liq_events_YYYY-MM-DD.csv files, sorts events by New
York time, and asks: if events are journal entries, what does the balance sheet
by price zone say?

Example:
    python LevelLedger/research/spatial_dominance_replay.py --date 2026-05-07
"""

from __future__ import annotations

import argparse
import csv
import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path


TICK_SIZE = 0.25
LOOKBACK_SEC = 20 * 60
HALF_LIFE_SEC = 8 * 60
KERNEL_TICKS = 12
NMS_TICKS = 24
EVAL_STEP_SEC = 30
MIN_DENSITY = 12.0
MIN_RATIO = 2.2


FIXTURES = {
    "2026-05-05": [("10:10", "10:25"), ("12:40", "12:55")],
    "2026-05-07": [("11:20", "11:55"), ("12:25", "12:50")],
}


DEMAND_EVENTS = {
    "BID_BUILD",
    "BID_IN",
    "ASK_OUT",
    "ASK_PULL",
}

SUPPLY_EVENTS = {
    "ASK_BUILD",
    "ASK_IN",
    "BID_OUT",
    "BID_PULL",
}


@dataclass(frozen=True)
class Event:
    time: datetime
    kind: str
    z: float
    tick: int
    price: float


@dataclass(frozen=True)
class Zone:
    tick: int
    price: float
    direction: int
    demand: float
    supply: float
    count: int

    @property
    def dominant(self) -> float:
        return max(self.demand, self.supply)

    @property
    def opposing(self) -> float:
        return min(self.demand, self.supply)

    @property
    def ratio(self) -> float:
        return self.dominant / max(1.0, self.opposing)


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def parse_time(day: str, hhmm: str) -> datetime:
    value = f"{day} {hhmm}"
    fmt = "%Y-%m-%d %H:%M:%S" if hhmm.count(":") == 2 else "%Y-%m-%d %H:%M"
    return datetime.strptime(value, fmt)


def event_bias(kind: str) -> int:
    if kind in DEMAND_EVENTS:
        return 1
    if kind in SUPPLY_EVENTS:
        return -1
    return 0


def load_events(day: str) -> list[Event]:
    path = repo_root() / "research" / "out" / f"liq_events_{day}.csv"
    events: list[Event] = []
    with path.open("r", newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            kind = row["event"].strip()
            if event_bias(kind) == 0:
                continue
            price = float(row["price"])
            events.append(
                Event(
                    time=parse_time(day, row["ny"].strip()),
                    kind=kind,
                    z=abs(float(row["z"])),
                    tick=round(price / TICK_SIZE),
                    price=price,
                )
            )
    return sorted(events, key=lambda e: e.time)


def density_at(now: datetime, center_tick: int, events: list[Event]) -> Zone | None:
    demand = 0.0
    supply = 0.0
    count = 0
    cutoff = now - timedelta(seconds=LOOKBACK_SEC)

    for event in events:
        if event.time < cutoff or event.time > now:
            continue

        dist = abs(event.tick - center_tick)
        if dist > KERNEL_TICKS * 3:
            continue

        age_sec = (now - event.time).total_seconds()
        time_weight = 0.5 ** (age_sec / HALF_LIFE_SEC)
        x = dist / KERNEL_TICKS
        price_weight = math.exp(-0.5 * x * x)
        contribution = event.z * time_weight * price_weight

        if event_bias(event.kind) > 0:
            demand += contribution
        else:
            supply += contribution
        count += 1

    if count == 0:
        return None

    direction = 1 if demand > supply else -1
    return Zone(
        tick=center_tick,
        price=center_tick * TICK_SIZE,
        direction=direction,
        demand=demand,
        supply=supply,
        count=count,
    )


def round_to_grid(tick: int) -> int:
    return int(round(tick / 4.0) * 4)


def zones_at(now: datetime, events: list[Event]) -> list[Zone]:
    cutoff = now - timedelta(seconds=LOOKBACK_SEC)
    candidates = sorted(
        {
            round_to_grid(event.tick)
            for event in events
            if cutoff <= event.time <= now
        }
    )

    raw: list[Zone] = []
    for tick in candidates:
        zone = density_at(now, tick, events)
        if zone is None:
            continue
        if zone.dominant < MIN_DENSITY or zone.ratio < MIN_RATIO:
            continue
        raw.append(zone)

    accepted: list[Zone] = []
    for zone in sorted(raw, key=lambda z: z.dominant, reverse=True):
        if any(abs(zone.tick - other.tick) <= NMS_TICKS for other in accepted):
            continue
        accepted.append(zone)
        if len(accepted) >= 3:
            break

    return sorted(accepted, key=lambda z: z.price)


def abbrev(price: float) -> str:
    whole = math.floor(price)
    last = whole % 1000
    frac = price - whole
    if abs(frac) < 0.0001:
        return f"{last:03d}"
    return f"{last:03d}{frac:.2f}".replace("0.", ".")


def replay(day: str, windows: list[tuple[str, str]]) -> None:
    events = load_events(day)
    last_key: dict[tuple[int, int], datetime] = {}
    print(f"\n{day}: {len(events)} directional L2 events")

    for start_s, end_s in windows:
        start = parse_time(day, start_s)
        end = parse_time(day, end_s)
        print(f"\nWindow {start_s}-{end_s}")
        now = start
        while now <= end:
            zones = zones_at(now, events)
            for zone in zones:
                direction = "UP" if zone.direction > 0 else "DOWN"
                label = "demand dom" if zone.direction > 0 else "supply dom"
                key = (zone.direction, round(zone.tick / NMS_TICKS))
                prev = last_key.get(key)
                if prev is not None and (now - prev).total_seconds() < 120:
                    continue
                last_key[key] = now
                print(
                    f"{now:%H:%M} {abbrev(zone.price):>7} {direction:<4} "
                    f"{zone.ratio:>3.1f}x {label:<10} "
                    f"D={zone.demand:>5.1f} S={zone.supply:>5.1f} n={zone.count}"
                )
            now += timedelta(seconds=EVAL_STEP_SEC)


def parse_windows(values: list[str] | None, day: str) -> list[tuple[str, str]]:
    if not values:
        return FIXTURES.get(day, [("09:30", "16:00")])
    windows: list[tuple[str, str]] = []
    for value in values:
        start, end = value.split("-", 1)
        windows.append((start, end))
    return windows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default="2026-05-07")
    parser.add_argument(
        "--window",
        action="append",
        help="NY time window as HH:MM-HH:MM. May be repeated.",
    )
    args = parser.parse_args()
    replay(args.date, parse_windows(args.window, args.date))


if __name__ == "__main__":
    main()
