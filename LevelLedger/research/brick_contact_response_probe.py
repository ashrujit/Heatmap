"""Fixture-scoped Brick contact-response probe.

This is Thesis 4 from the Skurry Now Lens research note. It does not discover
new bands and does not consume EAR logs. It attaches contact-response metrics to
the synthetic LL/EAR lifecycle anchors emitted by the T3 episode probe:

- displayed size present at the contacted ticks;
- attack tape through the contacted ticks;
- displayed size removed near contact;
- removed size not explained by same-price tape, as a pull proxy;
- same/resulting-side refill at 250 ms, 2 s, and 5 s;
- a descriptive held/gave/ambiguous response label.
"""

from __future__ import annotations

import argparse
import bisect
import csv
import math
import os
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable

import polars as pl


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
RESEARCH = ROOT / "research"
MR_RESEARCH = ROOT / "MarketRecorder" / "research"
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(RESEARCH))
sys.path.insert(0, str(MR_RESEARCH))

from capture_loader import (  # noqa: E402
    MARKET_RECORDER_ROOT,
    load_capture_window,
    snapshot_columns,
    tick_columns,
    us,
)
from replay_levelledger import abbrev, ny_hms, parse_ny  # noqa: E402
from validate_book_events import (  # noqa: E402
    DELTA,
    GAP,
    RESET_BEGIN,
    BookReplay,
    event_files_with_carry,
)


DEFAULT_ANCHORS = RESEARCH / "out" / "episode_terrain_lifecycle_probe_20260623_20260626.csv"
DEFAULT_OUT_DIR = RESEARCH / "out"
EVENT_COLUMNS = [
    "receipt_timestamp_us",
    "sequence",
    "subsequence",
    "reset_epoch",
    "event_kind",
    "side",
    "price_tick",
    "size",
    "closed",
    "quote_id_hash",
    "reset_item_count",
]
CHUNK_PART_RE = re.compile(r"-p\d+(?=\.parquet$)")
TICK_SIZE = 0.25
WINDOWS = ((0.25, "250ms"), (2.0, "2s"), (5.0, "5s"))


@dataclass(frozen=True)
class SessionSpec:
    date: str
    symbol: str

    @property
    def label(self) -> str:
        return f"{self.date}:{self.symbol}"


@dataclass
class Health:
    files: int = 0
    carry_days: int = 0
    rows_processed: int = 0
    valid_deltas: int = 0
    resets: int = 0
    gaps: int = 0
    crossed_levels_evicted: int = 0
    crossed_quotes_evicted: int = 0


@dataclass
class ContactAnchor:
    row: dict[str, str]
    id: int
    ts: datetime
    min_tick: int
    max_tick: int
    owner_side: str
    contacted_side: str
    valid_book: bool = False
    invalidated_by_gap: bool = False
    contact_start: float | None = None
    owner_start: float | None = None
    opp_owner_start: float | None = None
    contact_add: dict[str, float] = field(default_factory=dict)
    contact_remove: dict[str, float] = field(default_factory=dict)
    owner_add: dict[str, float] = field(default_factory=dict)
    owner_remove: dict[str, float] = field(default_factory=dict)
    opp_owner_add: dict[str, float] = field(default_factory=dict)
    opp_owner_remove: dict[str, float] = field(default_factory=dict)
    contact_end: dict[str, float | None] = field(default_factory=dict)
    owner_end: dict[str, float | None] = field(default_factory=dict)
    opp_owner_end: dict[str, float | None] = field(default_factory=dict)
    attack_vol: dict[str, float] = field(default_factory=dict)
    owner_aggr_vol: dict[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for _, label in WINDOWS:
            self.contact_add.setdefault(label, 0.0)
            self.contact_remove.setdefault(label, 0.0)
            self.owner_add.setdefault(label, 0.0)
            self.owner_remove.setdefault(label, 0.0)
            self.opp_owner_add.setdefault(label, 0.0)
            self.opp_owner_remove.setdefault(label, 0.0)
            self.contact_end.setdefault(label, None)
            self.owner_end.setdefault(label, None)
            self.opp_owner_end.setdefault(label, None)
            self.attack_vol.setdefault(label, 0.0)
            self.owner_aggr_vol.setdefault(label, 0.0)

    @property
    def ts_us(self) -> int:
        return us(self.ts)

    @property
    def max_end_us(self) -> int:
        return self.ts_us + int(max(window for window, _ in WINDOWS) * 1_000_000)

    @property
    def contact_sign(self) -> int:
        return side_sign(self.contacted_side)

    @property
    def owner_sign(self) -> int:
        return side_sign(self.owner_side)

    @property
    def attack_trade_sign(self) -> int:
        return -self.contact_sign

    @property
    def owner_trade_sign(self) -> int:
        return self.owner_sign

    def in_band(self, price_tick: int) -> bool:
        return self.min_tick <= price_tick <= self.max_tick

    def side_depth(self, replay: BookReplay, side: int) -> float:
        levels = replay.bid_levels if side > 0 else replay.ask_levels
        return sum(size for tick, size in levels.items() if self.in_band(tick))

    def sample_start(self, replay: BookReplay) -> None:
        if not replay.valid:
            self.valid_book = False
            return
        self.contact_start = self.side_depth(replay, self.contact_sign)
        self.owner_start = self.side_depth(replay, self.owner_sign)
        self.opp_owner_start = self.side_depth(replay, -self.owner_sign)
        self.valid_book = True

    def sample_end(self, replay: BookReplay, label: str) -> None:
        if not replay.valid:
            self.invalidated_by_gap = True
            return
        self.contact_end[label] = self.side_depth(replay, self.contact_sign)
        self.owner_end[label] = self.side_depth(replay, self.owner_sign)
        self.opp_owner_end[label] = self.side_depth(replay, -self.owner_sign)

    def observe_delta(self, side: int, price_tick: int, delta_size: float, event_us: int) -> None:
        if not self.in_band(price_tick) or delta_size == 0.0:
            return
        age_sec = (event_us - self.ts_us) / 1_000_000
        if age_sec < 0:
            return
        for window_sec, label in WINDOWS:
            if age_sec > window_sec:
                continue
            if side == self.contact_sign:
                if delta_size > 0:
                    self.contact_add[label] += delta_size
                else:
                    self.contact_remove[label] += -delta_size
            if side == self.owner_sign:
                if delta_size > 0:
                    self.owner_add[label] += delta_size
                else:
                    self.owner_remove[label] += -delta_size
            if side == -self.owner_sign:
                if delta_size > 0:
                    self.opp_owner_add[label] += delta_size
                else:
                    self.opp_owner_remove[label] += -delta_size

    def response_label(self, label: str = "2s") -> str:
        owner_start = self.owner_start
        contact_start = self.contact_start
        owner_end = self.owner_end.get(label)
        if owner_start is None or contact_start is None or owner_end is None:
            return "missing_book"
        attack = self.attack_vol[label]
        contact_removed = self.contact_remove[label]
        owner_added = self.owner_add[label]
        pulled = max(0.0, contact_removed - attack)
        initial_display = max(owner_start, contact_start)
        if initial_display < 1.0:
            if owner_added >= 2.0 or owner_end >= 2.0:
                return "no_initial_brick_refilled"
            return "no_initial_brick"
        survival = owner_end / max(1.0, owner_start)
        refill_ratio = owner_added / max(1.0, max(attack, contact_removed))
        if survival >= 0.75 and refill_ratio >= 0.25:
            return "held_refilled"
        if survival >= 0.75 and attack > 0:
            return "held_no_refill"
        if survival <= 0.35:
            return "gave_depleted"
        if pulled >= max(4.0, attack) and owner_added < max(2.0, 0.25 * contact_removed):
            return "gave_pulled"
        return "ambiguous"

    def to_row(self) -> dict[str, object]:
        out: dict[str, object] = dict(self.row)
        out.update(
            {
                "contact_id": self.id,
                "contacted_side": self.contacted_side,
                "owner_side": self.owner_side,
                "contacted_price": band_label(self.min_tick, self.max_tick),
                "valid_book": self.valid_book,
                "invalidated_by_gap": self.invalidated_by_gap,
                "contact_start": self.contact_start,
                "owner_start": self.owner_start,
                "opp_owner_start": self.opp_owner_start,
                "brick_label_2s": self.response_label("2s"),
            }
        )
        for _, label in WINDOWS:
            contact_removed = self.contact_remove[label]
            attack = self.attack_vol[label]
            owner_start = self.owner_start if self.owner_start is not None else math.nan
            owner_end = self.owner_end[label]
            pulled = max(0.0, contact_removed - attack)
            consumed = min(contact_removed, attack)
            owner_survival = (
                owner_end / max(1.0, owner_start)
                if owner_end is not None and math.isfinite(owner_start)
                else None
            )
            refill_base = max(1.0, max(attack, contact_removed))
            out.update(
                {
                    f"contact_add_{label}": self.contact_add[label],
                    f"contact_remove_{label}": contact_removed,
                    f"owner_add_{label}": self.owner_add[label],
                    f"owner_remove_{label}": self.owner_remove[label],
                    f"opp_owner_add_{label}": self.opp_owner_add[label],
                    f"opp_owner_remove_{label}": self.opp_owner_remove[label],
                    f"contact_end_{label}": self.contact_end[label],
                    f"owner_end_{label}": owner_end,
                    f"opp_owner_end_{label}": self.opp_owner_end[label],
                    f"attack_vol_{label}": attack,
                    f"owner_aggr_vol_{label}": self.owner_aggr_vol[label],
                    f"consumed_estimate_{label}": consumed,
                    f"pulled_estimate_{label}": pulled,
                    f"owner_survival_{label}": owner_survival,
                    f"refill_ratio_{label}": self.owner_add[label] / refill_base,
                    f"pull_ratio_{label}": pulled / max(1.0, contact_removed),
                }
            )
        return out


def side_sign(side: str) -> int:
    return 1 if side == "demand" else -1


def opposite(side: str) -> str:
    return "supply" if side == "demand" else "demand"


def band_label(min_tick: int, max_tick: int) -> str:
    if min_tick == max_tick:
        return abbrev(min_tick)
    return f"{abbrev(min_tick)}-{abbrev(max_tick)}"


def parse_iso_ts(value: str) -> datetime:
    return datetime.fromisoformat(value)


def anchor_owner_and_contact(row: dict[str, str]) -> tuple[str, str]:
    owner = row["band_side"]
    if row.get("anchor_class") == "consumed_conversion":
        return owner, opposite(owner)
    return owner, owner


def load_anchors(path: Path, args: argparse.Namespace) -> list[ContactAnchor]:
    rows: list[ContactAnchor] = []
    with path.open("r", newline="", encoding="utf-8") as fh:
        for idx, row in enumerate(csv.DictReader(fh), start=1):
            if args.fixture_id and row.get("fixture_id") not in args.fixture_id:
                continue
            if args.bucket and row.get("curated_bucket") not in args.bucket:
                continue
            if args.anchor_class and row.get("anchor_class") not in args.anchor_class:
                continue
            if args.lifecycle_label and row.get("lifecycle_label") not in args.lifecycle_label:
                continue
            owner, contacted = anchor_owner_and_contact(row)
            rows.append(
                ContactAnchor(
                    row=row,
                    id=idx,
                    ts=parse_iso_ts(row["anchor_ts"]),
                    min_tick=int(row["min_tick"]),
                    max_tick=int(row["max_tick"]),
                    owner_side=owner,
                    contacted_side=contacted,
                )
            )
    return rows


def chunk_groups(files: list[str]) -> list[list[str]]:
    groups: dict[str, list[str]] = {}
    order: list[str] = []
    for path in files:
        key = os.path.join(os.path.dirname(path), CHUNK_PART_RE.sub("", os.path.basename(path)))
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(path)
    return [groups[key] for key in order]


def event_deltas(replay: BookReplay, row: dict) -> list[tuple[int, int, float]]:
    if int(row["event_kind"]) != DELTA or not replay.seeded or not replay.valid:
        return []
    quote_id = int(row["quote_id_hash"])
    prior = replay.quotes.get(quote_id)
    if bool(row["closed"]):
        if prior is None:
            return []
        return [(prior.side, prior.price_tick, -prior.size)]

    side = int(row["side"])
    price_tick = int(row["price_tick"])
    size = float(row["size"])
    if quote_id == 0 or side not in (-1, 1) or price_tick == -(2**63):
        return []
    if not math.isfinite(size) or size < 0:
        return []
    if prior is None:
        return [(side, price_tick, size)] if size > 0 else []
    if prior.side == side and prior.price_tick == price_tick:
        delta = size - prior.size
        return [(side, price_tick, delta)] if abs(delta) > 1e-9 else []
    result = [(prior.side, prior.price_tick, -prior.size)]
    if size > 0:
        result.append((side, price_tick, size))
    return result


def stream_book_metrics(
    capture_root: str,
    spec: SessionSpec,
    anchors: list[ContactAnchor],
    max_carry_days: int,
) -> Health:
    files, carry_days = event_files_with_carry(capture_root, spec.symbol, spec.date, max_carry_days)
    health = Health(files=len(files), carry_days=carry_days)
    ordered = sorted(anchors, key=lambda item: item.ts_us)
    if not ordered:
        return health
    stop_us = max(anchor.max_end_us for anchor in ordered) + 1_000_000
    next_anchor = 0
    active: list[ContactAnchor] = []
    replay = BookReplay()

    def activate_until(event_us: int) -> None:
        nonlocal next_anchor
        while next_anchor < len(ordered) and ordered[next_anchor].ts_us <= event_us:
            anchor = ordered[next_anchor]
            anchor.sample_start(replay)
            active.append(anchor)
            next_anchor += 1

    def sample_due(event_us: int) -> None:
        for anchor in active:
            for window_sec, label in WINDOWS:
                if anchor.owner_end[label] is None and anchor.ts_us + int(window_sec * 1_000_000) <= event_us:
                    anchor.sample_end(replay, label)

    def prune_active(event_us: int) -> None:
        active[:] = [anchor for anchor in active if anchor.max_end_us > event_us]

    for group in chunk_groups(files):
        df = (
            pl.read_parquet(group, columns=EVENT_COLUMNS)
            .filter(pl.col("receipt_timestamp_us") <= stop_us)
            .sort(["receipt_timestamp_us", "sequence", "subsequence"])
        )
        for event_row in df.iter_rows(named=True):
            event_us = int(event_row["receipt_timestamp_us"])
            sample_due(event_us)
            prune_active(event_us)
            activate_until(event_us)
            if event_us > stop_us:
                break
            kind = int(event_row["event_kind"])
            if kind in (GAP, RESET_BEGIN):
                for anchor in active:
                    anchor.invalidated_by_gap = True
            deltas = event_deltas(replay, event_row)
            for anchor in active:
                if not anchor.valid_book:
                    continue
                for side, price_tick, delta in deltas:
                    anchor.observe_delta(side, price_tick, delta, event_us)
            crossed_before = replay.crossed_levels_evicted
            replay.apply(event_row)
            health.rows_processed += 1
            if kind == DELTA and replay.valid:
                health.valid_deltas += 1
            if kind == RESET_BEGIN:
                health.resets += 1
            elif kind == GAP:
                health.gaps += 1
            if replay.crossed_levels_evicted > crossed_before:
                health.crossed_levels_evicted = replay.crossed_levels_evicted
                health.crossed_quotes_evicted = replay.crossed_quotes_evicted
    sample_due(stop_us)
    return health


def snapshot_depth(row: dict, anchor: ContactAnchor, side: int) -> float:
    total = 0.0
    ref_tick = int(row["ref_tick"])
    prefix = "bid" if side > 0 else "ask"
    for idx in range(30):
        size = float(row[f"{prefix}_size_{idx}"])
        if not math.isfinite(size) or size <= 0.0:
            continue
        tick = ref_tick + int(row[f"{prefix}_offset_{idx}"])
        if anchor.in_band(tick):
            total += size
    return total


def add_snapshot_metrics(capture_root: str, spec: SessionSpec, anchors: list[ContactAnchor]) -> None:
    if not anchors:
        return
    start = min(anchor.ts for anchor in anchors) - timedelta(seconds=3)
    end = max(anchor.ts for anchor in anchors) + timedelta(seconds=max(window for window, _ in WINDOWS) + 3)
    snapshots = load_capture_window(
        "snapshots",
        spec.symbol,
        start,
        end,
        snapshot_columns(30),
        inclusive_end=True,
    )
    times = snapshots["timestamp_us"].to_list()
    rows = snapshots.to_dicts()

    def row_at(target_us: int) -> tuple[dict | None, float]:
        idx = bisect.bisect_right(times, target_us) - 1
        if idx < 0:
            return None, math.inf
        age = max(0.0, (target_us - int(times[idx])) / 1_000_000)
        return rows[idx], age

    for anchor in anchors:
        start_row, start_age = row_at(anchor.ts_us)
        if start_row is None or start_age > 2.5:
            anchor.valid_book = False
            continue
        anchor.contact_start = snapshot_depth(start_row, anchor, anchor.contact_sign)
        anchor.owner_start = snapshot_depth(start_row, anchor, anchor.owner_sign)
        anchor.opp_owner_start = snapshot_depth(start_row, anchor, -anchor.owner_sign)
        anchor.valid_book = True
        for window_sec, label in WINDOWS:
            end_row, end_age = row_at(anchor.ts_us + int(window_sec * 1_000_000))
            if end_row is None or end_age > 2.5:
                anchor.invalidated_by_gap = True
                continue
            contact_end = snapshot_depth(end_row, anchor, anchor.contact_sign)
            owner_end = snapshot_depth(end_row, anchor, anchor.owner_sign)
            opp_owner_end = snapshot_depth(end_row, anchor, -anchor.owner_sign)
            anchor.contact_end[label] = contact_end
            anchor.owner_end[label] = owner_end
            anchor.opp_owner_end[label] = opp_owner_end
            anchor.contact_add[label] = max(0.0, contact_end - (anchor.contact_start or 0.0))
            anchor.contact_remove[label] = max(0.0, (anchor.contact_start or 0.0) - contact_end)
            anchor.owner_add[label] = max(0.0, owner_end - (anchor.owner_start or 0.0))
            anchor.owner_remove[label] = max(0.0, (anchor.owner_start or 0.0) - owner_end)
            anchor.opp_owner_add[label] = max(0.0, opp_owner_end - (anchor.opp_owner_start or 0.0))
            anchor.opp_owner_remove[label] = max(0.0, (anchor.opp_owner_start or 0.0) - opp_owner_end)


def add_tick_metrics(capture_root: str, spec: SessionSpec, anchors: list[ContactAnchor]) -> None:
    if not anchors:
        return
    start = min(anchor.ts for anchor in anchors) - timedelta(seconds=1)
    end = max(anchor.ts for anchor in anchors) + timedelta(seconds=max(window for window, _ in WINDOWS) + 1)
    ticks = load_capture_window(
        "ticks",
        spec.symbol,
        start,
        end,
        tick_columns(),
        inclusive_end=True,
    )
    times = ticks["timestamp_us"].to_list()
    prices = ticks["price"].to_list()
    sizes = ticks["size"].to_list()
    signs = ticks["aggressor_sign"].to_list()
    for anchor in anchors:
        lo = bisect.bisect_left(times, anchor.ts_us)
        for window_sec, label in WINDOWS:
            hi = bisect.bisect_right(times, anchor.ts_us + int(window_sec * 1_000_000))
            attack = 0.0
            owner = 0.0
            for idx in range(lo, hi):
                price_tick = int(round(float(prices[idx]) / TICK_SIZE))
                if not anchor.in_band(price_tick):
                    continue
                size = float(sizes[idx])
                sign = int(signs[idx])
                if sign == anchor.attack_trade_sign:
                    attack += size
                if sign == anchor.owner_trade_sign:
                    owner += size
            anchor.attack_vol[label] = attack
            anchor.owner_aggr_vol[label] = owner


def group_by_session(anchors: Iterable[ContactAnchor]) -> dict[SessionSpec, list[ContactAnchor]]:
    groups: dict[SessionSpec, list[ContactAnchor]] = defaultdict(list)
    for anchor in anchors:
        spec = SessionSpec(anchor.row["date"], anchor.row["symbol"])
        groups[spec].append(anchor)
    return groups


def pct(value: int, total: int) -> str:
    if total <= 0:
        return "n/a"
    return f"{100.0 * value / total:.1f}%"


def summarize(rows: list[dict[str, object]], fields: list[str], outcome_field: str = "brick_label_2s") -> list[str]:
    groups: dict[tuple[str, ...], Counter[str]] = defaultdict(Counter)
    for row in rows:
        key = tuple(str(row.get(field, "")) for field in fields)
        groups[key][str(row.get(outcome_field, ""))] += 1
    if not groups:
        return ["No rows."]
    outcomes = sorted({outcome for counter in groups.values() for outcome in counter})
    lines = [
        "| " + " | ".join(fields) + " | n | " + " | ".join(outcomes) + " |",
        "| " + " | ".join("---" for _ in fields) + " | ---: | " + " | ".join("---:" for _ in outcomes) + " |",
    ]
    for key in sorted(groups):
        counter = groups[key]
        total = sum(counter.values())
        cells = [f"{counter[outcome]} ({pct(counter[outcome], total)})" for outcome in outcomes]
        lines.append("| " + " | ".join(key) + f" | {total} | " + " | ".join(cells) + " |")
    return lines


def numeric_summary(rows: list[dict[str, object]], field: str) -> str:
    values: list[float] = []
    for row in rows:
        value = row.get(field)
        if value in ("", None):
            continue
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(number):
            values.append(number)
    if not values:
        return "n/a"
    values.sort()
    mid = values[len(values) // 2]
    p75 = values[min(len(values) - 1, math.ceil(len(values) * 0.75) - 1)]
    return f"n={len(values)} median={mid:.2f} p75={p75:.2f}"


def example_rows(rows: list[dict[str, object]], limit: int = 24) -> list[str]:
    lines = [
        "| fixture | time | anchor | owner/contact | lifecycle | brick | attack2s | remove2s | pull2s | refill2s |",
        "| --- | --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: |",
    ]
    for row in rows[:limit]:
        lines.append(
            f"| `{row.get('fixture_id')}` | {row.get('anchor_ny')} | "
            f"{row.get('anchor_class')}@{row.get('contacted_price')} | "
            f"{row.get('owner_side')}/{row.get('contacted_side')} | "
            f"`{row.get('lifecycle_label')}` | `{row.get('brick_label_2s')}` | "
            f"{float(row.get('attack_vol_2s') or 0):.0f} | "
            f"{float(row.get('contact_remove_2s') or 0):.0f} | "
            f"{float(row.get('pulled_estimate_2s') or 0):.0f} | "
            f"{float(row.get('owner_add_2s') or 0):.0f} |"
        )
    return lines


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = sorted({key for row in rows for key in row})
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_report(
    path: Path,
    rows: list[dict[str, object]],
    health_by_session: dict[str, Health],
    args: argparse.Namespace,
) -> None:
    clean = [
        row for row in rows
        if row.get("valid_book") is True and row.get("invalidated_by_gap") is False
    ]
    lines = [
        "# Brick Contact Response Probe",
        "",
        "Fixture-scoped Thesis 4 pass. Anchors come from the T3 lifecycle probe; Brick metrics are explanatory contact-response measurements.",
        "",
        "## Coverage",
        "",
        f"- anchor rows: `{len(rows)}`",
        f"- clean book rows: `{len(clean)}`",
            f"- anchor source: `{args.anchors}`",
            f"- depth source: `{'book_events' if args.book_events else 'snapshots'}`",
        "",
    ]
    for session, health in sorted(health_by_session.items()):
        if args.book_events:
            lines.append(
                f"- `{session}` book_files={health.files} carry_days={health.carry_days} "
                f"rows={health.rows_processed} valid_deltas={health.valid_deltas} "
                f"resets={health.resets} gaps={health.gaps} crossed_repairs={health.crossed_levels_evicted}"
            )
        else:
            lines.append(f"- `{session}` snapshot/tick mode; quote-event replay not run")
    lines.extend(["", "## Brick Label By Anchor Class And Lifecycle", ""])
    lines.extend(summarize(clean, ["anchor_class", "lifecycle_label"]))
    lines.extend(["", "## Brick Label By Fixture Bucket", ""])
    lines.extend(summarize(clean, ["curated_bucket", "anchor_class"]))
    lines.extend(["", "## Metric Sketch", ""])
    preferred_labels = [
        "held_refilled",
        "held_no_refill",
        "gave_depleted",
        "gave_pulled",
        "no_initial_brick_refilled",
        "no_initial_brick",
        "ambiguous",
        "missing_book",
    ]
    observed_labels = {str(row.get("brick_label_2s")) for row in clean}
    ordered_labels = [label for label in preferred_labels if label in observed_labels]
    ordered_labels.extend(sorted(observed_labels.difference(ordered_labels)))
    for label in ordered_labels:
        subset = [row for row in clean if row.get("brick_label_2s") == label]
        lines.append(f"- `{label}` attack 2s: {numeric_summary(subset, 'attack_vol_2s')}")
        lines.append(f"- `{label}` pulled estimate 2s: {numeric_summary(subset, 'pulled_estimate_2s')}")
        lines.append(f"- `{label}` refill ratio 2s: {numeric_summary(subset, 'refill_ratio_2s')}")
    lines.extend(["", "## Example Rows", ""])
    lines.extend(example_rows(clean))
    lines.extend(
        [
            "",
            "## Parameters",
            "",
            "- windows: `250ms`, `2s`, `5s`",
            f"- max_carry_days: `{args.max_carry_days}`",
            "",
            "## Guardrails",
            "",
            "- `consumed_estimate` is bounded by observed same-band removal and attack tape; it is not exchange-native match attribution.",
            "- In default snapshot mode, add/remove/pull estimates are net depth changes between samples, not quote-event attribution.",
            "- `no_initial_brick` means the replay did not see meaningful displayed size at the anchor, so the row is not treated as a depleted wall.",
            "- In default snapshot mode, `250ms` refill is sample-cadence limited; `2s` is the main descriptive window.",
            "- In `--book-events` mode, `pulled_estimate` is removal not explained by same-band attack tape. It is a pull proxy, not spoof proof.",
            "- The 2s Brick label is descriptive and in-sample.",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--anchors", default=str(DEFAULT_ANCHORS))
    parser.add_argument("--capture-root", default=MARKET_RECORDER_ROOT)
    parser.add_argument("--fixture-id", action="append", default=[])
    parser.add_argument("--bucket", action="append", default=[])
    parser.add_argument("--anchor-class", action="append", default=[])
    parser.add_argument("--lifecycle-label", action="append", default=[])
    parser.add_argument("--book-events", action="store_true")
    parser.add_argument("--max-carry-days", type=int, default=7)
    parser.add_argument("--output-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--tag", default="20260623_20260626")
    args = parser.parse_args()

    anchors = load_anchors(Path(args.anchors), args)
    groups = group_by_session(anchors)
    health_by_session: dict[str, Health] = {}
    for spec, session_anchors in groups.items():
        print(f"contact replay {spec.label} anchors={len(session_anchors)}", flush=True)
        if args.book_events:
            health_by_session[spec.label] = stream_book_metrics(
                args.capture_root,
                spec,
                session_anchors,
                args.max_carry_days,
            )
        else:
            health_by_session[spec.label] = Health()
            add_snapshot_metrics(args.capture_root, spec, session_anchors)
        add_tick_metrics(args.capture_root, spec, session_anchors)

    rows = [anchor.to_row() for anchor in anchors]
    out_dir = Path(args.output_dir)
    csv_path = out_dir / f"brick_contact_response_probe_{args.tag}.csv"
    report_path = out_dir / f"brick_contact_response_probe_{args.tag}.md"
    write_csv(csv_path, rows)
    write_report(report_path, rows, health_by_session, args)
    print(f"wrote {csv_path}")
    print(f"wrote {report_path}")


if __name__ == "__main__":
    main()
