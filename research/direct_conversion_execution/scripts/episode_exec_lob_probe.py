"""Episode-scoped EAR + MarketRecorder LOB investigation.

This is a reusable narrow-window probe for execution questions. It keeps live
EAR runtime evidence separate from MarketRecorder market evidence:

- EAR JSONL answers what the runtime accepted, attempted, filled, promoted,
  paused, or flattened.
- MarketRecorder NQU6 ticks/snapshots/book events answer what the market and
  book did around those anchors.

The output is research-only. It is not a backtest and it does not propose
runtime changes by itself.
"""

from __future__ import annotations

import argparse
import bisect
import csv
import glob
import json
import math
import os
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import polars as pl

from _paths import OUTPUT_ROOT, REPO_ROOT as ROOT

MR_RESEARCH = ROOT / "MarketRecorder" / "research"
sys.path.insert(0, str(MR_RESEARCH))

from capture_loader import (  # noqa: E402
    MARKET_RECORDER_ROOT,
    load_capture_window,
    snapshot_columns,
    tick_columns,
    us,
)
from validate_book_events import (  # noqa: E402
    DELTA,
    GAP,
    RESET_BEGIN,
    BookReplay,
    event_files_with_carry,
)


NY = ZoneInfo("America/New_York")
TICK_SIZE = 0.25
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
BOOK_WINDOWS = (0.25, 2.0, 5.0, 10.0)
KEEP_EVENTS = {
    "directive_accepted",
    "directive_rejected",
    "control_accepted",
    "runtime_state",
    "entry_paused",
    "order_submit",
    "order_submit_result",
    "intent_result",
    "trade_fill",
    "fill_quality",
    "target_place",
    "target_modify",
    "flatten_result",
    "position_reconciled",
    "sponsor_promoted",
    "sponsor_failed",
    "sponsor_cleared",
    "sponsor_failure_context",
    "sponsor_failure_no_rebuild",
    "book_unusable_started",
    "book_usable_recovered",
    "failure_parent_invalidated",
}
EVIDENCE_KINDS = {
    "RailOwned",
    "RailTested",
    "RailHeld",
    "RailFailed",
    "FailurePromoted",
    "FailureInvalidated",
    "GreyUpdated",
    "CandidateFormed",
    "CandidateDisplacementStarted",
    "CandidateDisplacementReset",
}


@dataclass(frozen=True)
class Episode:
    episode_id: str
    label: str
    start: datetime
    end: datetime
    price_lo: float | None = None
    price_hi: float | None = None
    side: str | None = None
    note: str = ""

    @property
    def start_us(self) -> int:
        return us(self.start)

    @property
    def end_us(self) -> int:
        return us(self.end)

    @property
    def price_text(self) -> str:
        if self.price_lo is None or self.price_hi is None:
            return ""
        return f"{self.price_lo:.2f}-{self.price_hi:.2f}"


@dataclass
class BookAnchor:
    episode_id: str
    anchor_id: str
    source: str
    ts: datetime
    side: str
    min_tick: int
    max_tick: int
    directive_id: str = ""
    event: str = ""
    reason: str = ""
    valid_book: bool = False
    invalidated_by_gap: bool = False
    side_start: float | None = None
    opp_start: float | None = None
    side_add: dict[str, float] = field(default_factory=dict)
    side_remove: dict[str, float] = field(default_factory=dict)
    opp_add: dict[str, float] = field(default_factory=dict)
    opp_remove: dict[str, float] = field(default_factory=dict)
    side_end: dict[str, float | None] = field(default_factory=dict)
    opp_end: dict[str, float | None] = field(default_factory=dict)
    attack_vol: dict[str, float] = field(default_factory=dict)
    aligned_vol: dict[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for window in BOOK_WINDOWS:
            label = window_label(window)
            self.side_add.setdefault(label, 0.0)
            self.side_remove.setdefault(label, 0.0)
            self.opp_add.setdefault(label, 0.0)
            self.opp_remove.setdefault(label, 0.0)
            self.side_end.setdefault(label, None)
            self.opp_end.setdefault(label, None)
            self.attack_vol.setdefault(label, 0.0)
            self.aligned_vol.setdefault(label, 0.0)

    @property
    def ts_us(self) -> int:
        return us(self.ts)

    @property
    def side_sign(self) -> int:
        return 1 if self.side.lower() == "demand" else -1

    @property
    def max_end_us(self) -> int:
        return self.ts_us + int(max(BOOK_WINDOWS) * 1_000_000)

    def in_band(self, price_tick: int) -> bool:
        return self.min_tick <= price_tick <= self.max_tick

    def side_depth(self, replay: BookReplay, side: int) -> float:
        levels = replay.bid_levels if side > 0 else replay.ask_levels
        return sum(size for tick, size in levels.items() if self.in_band(tick))

    def sample_start(self, replay: BookReplay) -> None:
        if not replay.valid:
            self.valid_book = False
            return
        self.side_start = self.side_depth(replay, self.side_sign)
        self.opp_start = self.side_depth(replay, -self.side_sign)
        self.valid_book = True

    def sample_end(self, replay: BookReplay, label: str) -> None:
        if not replay.valid:
            self.invalidated_by_gap = True
            return
        self.side_end[label] = self.side_depth(replay, self.side_sign)
        self.opp_end[label] = self.side_depth(replay, -self.side_sign)

    def observe_delta(self, side: int, price_tick: int, delta_size: float, event_us: int) -> None:
        if not self.in_band(price_tick) or delta_size == 0.0:
            return
        age = (event_us - self.ts_us) / 1_000_000
        if age < 0:
            return
        for window in BOOK_WINDOWS:
            if age > window:
                continue
            label = window_label(window)
            if side == self.side_sign:
                if delta_size > 0:
                    self.side_add[label] += delta_size
                else:
                    self.side_remove[label] += -delta_size
            else:
                if delta_size > 0:
                    self.opp_add[label] += delta_size
                else:
                    self.opp_remove[label] += -delta_size


@dataclass
class BookHealth:
    files: int = 0
    carry_days: int = 0
    rows_processed: int = 0
    gaps: int = 0
    resets: int = 0
    crossed_levels_evicted: int = 0
    crossed_quotes_evicted: int = 0


def window_label(value: float) -> str:
    return "250ms" if abs(value - 0.25) < 1e-9 else f"{int(value)}s"


def price_to_tick(price: float) -> int:
    return int(round(price / TICK_SIZE))


def tick_price(tick: int) -> float:
    return tick * TICK_SIZE


def parse_ts_utc(value: str) -> datetime:
    text = value.strip().replace("Z", "+00:00")
    if "." in text:
        head, tail = text.split(".", 1)
        sign_pos = max(tail.rfind("+"), tail.rfind("-"))
        if sign_pos >= 0:
            frac = tail[:sign_pos]
            off = tail[sign_pos:]
            text = f"{head}.{frac[:6]}{off}"
        else:
            text = f"{head}.{tail[:6]}"
    return datetime.fromisoformat(text).astimezone(NY)


def parse_ny(date: str, hm: str) -> datetime:
    parts = hm.split(":")
    if len(parts) == 2:
        fmt = "%Y-%m-%d %H:%M"
    elif len(parts) == 3:
        fmt = "%Y-%m-%d %H:%M:%S"
    else:
        raise ValueError(f"bad time {hm!r}")
    return datetime.strptime(f"{date} {hm}", fmt).replace(tzinfo=NY)


def parse_episode_spec(value: str, default_date: str) -> Episode:
    parts = value.split("|")
    if len(parts) < 3:
        raise argparse.ArgumentTypeError(
            "episode must be id|HH:MM-HH:MM|label[|price_lo-price_hi][|side][|note]"
        )
    episode_id, window, label = parts[:3]
    start_s, end_s = window.split("-", 1)
    start = parse_ny(default_date, start_s)
    end = parse_ny(default_date, end_s)
    price_lo = price_hi = None
    side = None
    note = ""
    if len(parts) >= 4 and parts[3]:
        lo_s, hi_s = parts[3].split("-", 1)
        price_lo, price_hi = sorted((float(lo_s), float(hi_s)))
    if len(parts) >= 5 and parts[4]:
        side = parts[4]
    if len(parts) >= 6:
        note = parts[5]
    if end <= start:
        raise argparse.ArgumentTypeError(f"episode {episode_id} end <= start")
    return Episode(episode_id, label, start, end, price_lo, price_hi, side, note)


def default_episodes(date: str) -> list[Episode]:
    specs = [
        "E1021|10:18-10:24|10:21 conversion short|28345-28370|supply|reported short 354-365",
        "E1055|10:45-11:15|10:55-11:15 long directive/no attempt|28270-28480|demand|active directive versus no trade attempt",
        "E1115|11:15-11:50|VPOC/HVN churn stand aside|28470-28540||no new long directives preferred",
        "E1150|11:48-12:05|11:50 long exit versus campaign|28500-28630|demand|entry 515-524, exit 11:53, later 556-623 campaign",
        "E1215|12:10-12:35|12:15-12:30 repair or fresh buying|28525-28630|demand|classify repair against selling leg",
    ]
    return [parse_episode_spec(spec, date) for spec in specs]


def event_deltas(replay: BookReplay, row: dict[str, Any]) -> list[tuple[int, int, float]]:
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


def read_ear_events(path: Path, episodes: list[Episode]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    lo = min(ep.start for ep in episodes)
    hi = max(ep.end for ep in episodes)
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            raw_ts = row.get("ts_utc")
            if not raw_ts:
                continue
            ts = parse_ts_utc(raw_ts)
            if ts < lo or ts > hi:
                continue
            event = row.get("event", "")
            if event not in KEEP_EVENTS and not (
                event == "evidence_transition" and row.get("kind") in EVIDENCE_KINDS
            ):
                continue
            episode_ids = [ep.episode_id for ep in episodes if ep.start <= ts <= ep.end]
            if not episode_ids:
                continue
            slim = dict(row)
            slim["ts_et"] = ts
            slim["episode_ids"] = episode_ids
            out.append(slim)
    return out


def slim_event_row(event: dict[str, Any], episode_id: str) -> dict[str, Any]:
    keys = [
        "directive_id",
        "event",
        "kind",
        "reason",
        "side",
        "role",
        "quantity",
        "accepted",
        "order_id",
        "price",
        "average_fill_price",
        "fill_price",
        "target_price",
        "trigger_executable",
        "total_implementation_cost_points",
        "resolution",
        "root_object_id",
        "support_object_id",
        "root_min_price",
        "root_max_price",
        "support_min_price",
        "support_max_price",
        "sponsor_id",
        "prior_sponsor_id",
        "lower",
        "upper",
        "band_id",
        "band_role",
        "band_side",
        "band_source",
        "band_state",
        "band_min_tick",
        "band_max_tick",
        "candidate_id",
        "candidate_side",
        "candidate_min_tick",
        "candidate_max_tick",
        "candidate_direction",
        "actionable",
        "message",
    ]
    row: dict[str, Any] = {
        "episode_id": episode_id,
        "ts_et": event["ts_et"].strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
    }
    for key in keys:
        if key in event:
            row[key] = event[key]
    return row


def build_book_anchors(events: list[dict[str, Any]]) -> list[BookAnchor]:
    anchors: list[BookAnchor] = []
    seen: set[tuple[str, str, int, int, int]] = set()
    for event in events:
        ts = event["ts_et"]
        episode_ids = event["episode_ids"]
        event_name = str(event.get("event", ""))
        source = ""
        side = ""
        min_price: float | None = None
        max_price: float | None = None
        if event_name == "order_submit":
            source = f"order_submit:{event.get('role', '')}"
            side = "demand" if str(event.get("side", "")).lower() == "long" else "supply"
            min_price = as_float(event.get("support_min_price"))
            max_price = as_float(event.get("support_max_price"))
        elif event_name in {"sponsor_promoted", "sponsor_failed"}:
            source = event_name
            side = str(event.get("side", "")).lower()
            min_price = as_float(event.get("lower"))
            max_price = as_float(event.get("upper"))
        elif event_name == "evidence_transition" and event.get("kind") in {"RailOwned", "RailFailed", "RailTested", "RailHeld"}:
            source = f"evidence:{event.get('kind', '')}"
            side = str(event.get("band_side", "")).lower()
            min_tick = as_int(event.get("band_min_tick"))
            max_tick = as_int(event.get("band_max_tick"))
            if side not in {"demand", "supply"} or min_tick is None or max_tick is None:
                continue
            min_price = tick_price(min_tick)
            max_price = tick_price(max_tick)
        else:
            continue
        if side not in {"demand", "supply"} or min_price is None or max_price is None:
            continue
        min_tick = price_to_tick(min(min_price, max_price))
        max_tick = price_to_tick(max(min_price, max_price))
        for episode_id in episode_ids:
            key = (episode_id, source, int(ts.timestamp() * 1_000_000), min_tick, max_tick)
            if key in seen:
                continue
            seen.add(key)
            anchors.append(
                BookAnchor(
                    episode_id=episode_id,
                    anchor_id=f"A{len(anchors) + 1:04d}",
                    source=source,
                    ts=ts,
                    side=side,
                    min_tick=min_tick,
                    max_tick=max_tick,
                    directive_id=str(event.get("directive_id", "")),
                    event=event_name if event_name != "evidence_transition" else str(event.get("kind", "")),
                    reason=str(event.get("reason", "")),
                )
            )
    return sorted(anchors, key=lambda anchor: anchor.ts_us)


def as_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def as_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def load_ticks_for_episodes(symbol_dir: str, episodes: list[Episode]) -> pl.DataFrame:
    start = min(ep.start for ep in episodes) - timedelta(seconds=5)
    end = max(ep.end for ep in episodes) + timedelta(seconds=65)
    return load_capture_window("ticks", symbol_dir, start, end, tick_columns(), inclusive_end=True)


def load_snapshots_for_episodes(symbol_dir: str, episodes: list[Episode]) -> pl.DataFrame:
    start = min(ep.start for ep in episodes) - timedelta(seconds=20)
    end = max(ep.end for ep in episodes) + timedelta(seconds=65)
    return load_capture_window("snapshots", symbol_dir, start, end, snapshot_columns(30), inclusive_end=True)


def add_ts(df: pl.DataFrame) -> pl.DataFrame:
    return df.with_columns(
        pl.from_epoch("timestamp_us", time_unit="us")
        .dt.replace_time_zone("UTC")
        .dt.convert_time_zone("America/New_York")
        .alias("ts")
    )


def tape_bars(ticks: pl.DataFrame, episodes: list[Episode], every: str) -> list[dict[str, Any]]:
    if ticks.is_empty():
        return []
    bars = (
        add_ts(ticks)
        .group_by_dynamic("ts", every=every, closed="left")
        .agg(
            [
                pl.col("price").first().alias("open"),
                pl.col("price").max().alias("high"),
                pl.col("price").min().alias("low"),
                pl.col("price").last().alias("close"),
                pl.col("size").sum().alias("volume"),
                (pl.col("size") * pl.col("aggressor_sign")).sum().alias("delta"),
                pl.len().alias("trades"),
            ]
        )
        .sort("ts")
    )
    out: list[dict[str, Any]] = []
    for row in bars.iter_rows(named=True):
        ts = row["ts"]
        for ep in episodes:
            if ep.start <= ts < ep.end:
                rec = {
                    "episode_id": ep.episode_id,
                    "bar_start_et": ts.strftime("%Y-%m-%d %H:%M:%S"),
                    "bar_size": every,
                    "open": round(float(row["open"]), 2),
                    "high": round(float(row["high"]), 2),
                    "low": round(float(row["low"]), 2),
                    "close": round(float(row["close"]), 2),
                    "volume": round(float(row["volume"]), 2),
                    "delta": round(float(row["delta"]), 2),
                    "trades": int(row["trades"]),
                }
                out.append(rec)
    return out


def episode_tape_summary(ticks: pl.DataFrame, episodes: list[Episode]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if ticks.is_empty():
        return out
    for ep in episodes:
        rows = ticks.filter((pl.col("timestamp_us") >= ep.start_us) & (pl.col("timestamp_us") <= ep.end_us))
        if rows.is_empty():
            continue
        prices = rows["price"]
        sizes = rows["size"]
        signs = rows["aggressor_sign"]
        signed = (sizes * signs).sum()
        out.append(
            {
                "episode_id": ep.episode_id,
                "label": ep.label,
                "window": f"{ep.start.strftime('%H:%M:%S')}-{ep.end.strftime('%H:%M:%S')}",
                "open": round(float(prices[0]), 2),
                "high": round(float(prices.max()), 2),
                "low": round(float(prices.min()), 2),
                "close": round(float(prices[-1]), 2),
                "range_pts": round(float(prices.max() - prices.min()), 2),
                "volume": round(float(sizes.sum()), 2),
                "delta": round(float(signed), 2),
                "trades": rows.height,
            }
        )
    return out


def snapshot_top_depth(row: dict[str, Any], levels: int, side: str) -> float:
    prefix = "bid" if side == "bid" else "ask"
    total = 0.0
    for idx in range(levels):
        value = float(row[f"{prefix}_size_{idx}"])
        if math.isfinite(value) and value > 0:
            total += value
    return total


def snapshot_range_depth(row: dict[str, Any], lo_tick: int, hi_tick: int, side: str) -> float:
    prefix = "bid" if side == "bid" else "ask"
    ref = int(row["ref_tick"])
    total = 0.0
    for idx in range(30):
        size = float(row[f"{prefix}_size_{idx}"])
        if not math.isfinite(size) or size <= 0:
            continue
        tick = ref + int(row[f"{prefix}_offset_{idx}"])
        if lo_tick <= tick <= hi_tick:
            total += size
    return total


def episode_snapshot_summary(snapshots: pl.DataFrame, episodes: list[Episode]) -> list[dict[str, Any]]:
    rows = snapshots.to_dicts()
    out: list[dict[str, Any]] = []
    for ep in episodes:
        ep_rows = [row for row in rows if ep.start_us <= int(row["timestamp_us"]) <= ep.end_us]
        if not ep_rows:
            continue
        start_row = ep_rows[0]
        end_row = ep_rows[-1]
        rec: dict[str, Any] = {
            "episode_id": ep.episode_id,
            "snapshots": len(ep_rows),
            "mid_start": round(tick_price(int(start_row["ref_tick"])), 2),
            "mid_end": round(tick_price(int(end_row["ref_tick"])), 2),
            "top20_bid_start": round(snapshot_top_depth(start_row, 20, "bid"), 2),
            "top20_bid_end": round(snapshot_top_depth(end_row, 20, "bid"), 2),
            "top20_ask_start": round(snapshot_top_depth(start_row, 20, "ask"), 2),
            "top20_ask_end": round(snapshot_top_depth(end_row, 20, "ask"), 2),
        }
        rec["top20_bid_change"] = round(rec["top20_bid_end"] - rec["top20_bid_start"], 2)
        rec["top20_ask_change"] = round(rec["top20_ask_end"] - rec["top20_ask_start"], 2)
        if ep.price_lo is not None and ep.price_hi is not None:
            lo = price_to_tick(ep.price_lo)
            hi = price_to_tick(ep.price_hi)
            rec["range_bid_start"] = round(snapshot_range_depth(start_row, lo, hi, "bid"), 2)
            rec["range_bid_end"] = round(snapshot_range_depth(end_row, lo, hi, "bid"), 2)
            rec["range_ask_start"] = round(snapshot_range_depth(start_row, lo, hi, "ask"), 2)
            rec["range_ask_end"] = round(snapshot_range_depth(end_row, lo, hi, "ask"), 2)
            rec["range_bid_change"] = round(rec["range_bid_end"] - rec["range_bid_start"], 2)
            rec["range_ask_change"] = round(rec["range_ask_end"] - rec["range_ask_start"], 2)
        out.append(rec)
    return out


def add_tick_metrics_to_anchors(ticks: pl.DataFrame, anchors: list[BookAnchor]) -> None:
    if ticks.is_empty() or not anchors:
        return
    times = ticks["timestamp_us"].to_list()
    prices = ticks["price"].to_list()
    sizes = ticks["size"].to_list()
    signs = ticks["aggressor_sign"].to_list()
    for anchor in anchors:
        lo = bisect.bisect_left(times, anchor.ts_us)
        for window in BOOK_WINDOWS:
            hi = bisect.bisect_right(times, anchor.ts_us + int(window * 1_000_000))
            attack = 0.0
            aligned = 0.0
            for idx in range(lo, hi):
                tick = price_to_tick(float(prices[idx]))
                if not anchor.in_band(tick):
                    continue
                size = float(sizes[idx])
                sign = int(signs[idx])
                if sign == -anchor.side_sign:
                    attack += size
                elif sign == anchor.side_sign:
                    aligned += size
            label = window_label(window)
            anchor.attack_vol[label] = attack
            anchor.aligned_vol[label] = aligned


def add_snapshot_metrics_to_anchors(snapshots: pl.DataFrame, anchors: list[BookAnchor]) -> None:
    if snapshots.is_empty() or not anchors:
        return
    rows = snapshots.to_dicts()
    times = [int(row["timestamp_us"]) for row in rows]

    def row_at(target_us: int) -> tuple[dict[str, Any] | None, float]:
        idx = bisect.bisect_right(times, target_us) - 1
        if idx < 0:
            return None, math.inf
        age = max(0.0, (target_us - times[idx]) / 1_000_000)
        return rows[idx], age

    def depth(row: dict[str, Any], anchor: BookAnchor, side: int) -> float:
        return snapshot_range_depth(row, anchor.min_tick, anchor.max_tick, "bid" if side > 0 else "ask")

    for anchor in anchors:
        start_row, start_age = row_at(anchor.ts_us)
        if start_row is None or start_age > 2.5:
            continue
        anchor.side_start = depth(start_row, anchor, anchor.side_sign)
        anchor.opp_start = depth(start_row, anchor, -anchor.side_sign)
        anchor.valid_book = True
        for window in BOOK_WINDOWS:
            label = window_label(window)
            end_row, end_age = row_at(anchor.ts_us + int(window * 1_000_000))
            if end_row is None or end_age > 2.5:
                anchor.invalidated_by_gap = True
                continue
            anchor.side_end[label] = depth(end_row, anchor, anchor.side_sign)
            anchor.opp_end[label] = depth(end_row, anchor, -anchor.side_sign)


def stream_book_anchors(
    capture_root: str,
    symbol_dir: str,
    date: str,
    anchors: list[BookAnchor],
    stop_us: int,
    max_carry_days: int,
) -> BookHealth:
    health = BookHealth()
    if not anchors:
        return health
    files, carry_days = event_files_with_carry(capture_root, symbol_dir, date, max_carry_days)
    health.files = len(files)
    health.carry_days = carry_days
    ordered = sorted(anchors, key=lambda a: a.ts_us)
    next_anchor = 0
    active: list[BookAnchor] = []
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
            for window in BOOK_WINDOWS:
                label = window_label(window)
                if anchor.side_end[label] is None and anchor.ts_us + int(window * 1_000_000) <= event_us:
                    anchor.sample_end(replay, label)

    def prune(event_us: int) -> None:
        active[:] = [anchor for anchor in active if anchor.max_end_us > event_us]

    for group in chunk_groups(files):
        df = (
            pl.read_parquet(group, columns=EVENT_COLUMNS)
            .filter(pl.col("receipt_timestamp_us") <= stop_us)
            .sort(["receipt_timestamp_us", "sequence", "subsequence"])
        )
        for row in df.iter_rows(named=True):
            event_us = int(row["receipt_timestamp_us"])
            sample_due(event_us)
            prune(event_us)
            activate_until(event_us)
            if event_us > stop_us:
                break
            kind = int(row["event_kind"])
            if kind in (GAP, RESET_BEGIN):
                for anchor in active:
                    anchor.invalidated_by_gap = True
            deltas = event_deltas(replay, row)
            for anchor in active:
                if not anchor.valid_book:
                    continue
                for side, tick, delta in deltas:
                    anchor.observe_delta(side, tick, delta, event_us)
            crossed_before = replay.crossed_levels_evicted
            replay.apply(row)
            health.rows_processed += 1
            if kind == GAP:
                health.gaps += 1
            elif kind == RESET_BEGIN:
                health.resets += 1
            if replay.crossed_levels_evicted > crossed_before:
                health.crossed_levels_evicted = replay.crossed_levels_evicted
                health.crossed_quotes_evicted = replay.crossed_quotes_evicted
        if df.height and int(df[-1, "receipt_timestamp_us"]) > stop_us:
            break
    sample_due(stop_us + int(max(BOOK_WINDOWS) * 1_000_000))
    return health


def anchor_rows(anchors: list[BookAnchor]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for anchor in anchors:
        row: dict[str, Any] = {
            "episode_id": anchor.episode_id,
            "anchor_id": anchor.anchor_id,
            "ts_et": anchor.ts.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
            "source": anchor.source,
            "event": anchor.event,
            "reason": anchor.reason,
            "directive_id": anchor.directive_id,
            "side": anchor.side,
            "price_lo": round(tick_price(anchor.min_tick), 2),
            "price_hi": round(tick_price(anchor.max_tick), 2),
            "valid_book": anchor.valid_book,
            "invalidated_by_gap": anchor.invalidated_by_gap,
            "side_start": round_or_blank(anchor.side_start),
            "opp_start": round_or_blank(anchor.opp_start),
        }
        for window in BOOK_WINDOWS:
            label = window_label(window)
            start = anchor.side_start if anchor.side_start is not None else math.nan
            side_end = anchor.side_end[label]
            opp_end = anchor.opp_end[label]
            replenishment = None
            if side_end is not None and math.isfinite(start):
                replenishment = anchor.attack_vol[label] + (side_end - start)
            row.update(
                {
                    f"side_add_{label}": round(anchor.side_add[label], 2),
                    f"side_remove_{label}": round(anchor.side_remove[label], 2),
                    f"opp_add_{label}": round(anchor.opp_add[label], 2),
                    f"opp_remove_{label}": round(anchor.opp_remove[label], 2),
                    f"side_end_{label}": round_or_blank(side_end),
                    f"opp_end_{label}": round_or_blank(opp_end),
                    f"attack_vol_{label}": round(anchor.attack_vol[label], 2),
                    f"aligned_vol_{label}": round(anchor.aligned_vol[label], 2),
                    f"side_depth_change_{label}": (
                        round(side_end - start, 2) if side_end is not None and math.isfinite(start) else ""
                    ),
                    f"replenishment_{label}": round_or_blank(replenishment),
                    f"reload_ratio_{label}": (
                        round(replenishment / max(anchor.attack_vol[label], 1.0), 3)
                        if replenishment is not None
                        else ""
                    ),
                }
            )
        out.append(row)
    return out


def parse_output_ts(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    text = str(value)
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=NY)
        except ValueError:
            continue
    return None


def ts_us_from_row(row: dict[str, Any]) -> int | None:
    ts = parse_output_ts(row.get("ts_et"))
    return None if ts is None else us(ts)


def side_sign_from_label(value: Any) -> int:
    text = str(value or "").lower()
    if text in {"demand", "long", "buy"}:
        return 1
    if text in {"supply", "short", "sell"}:
        return -1
    return 0


def row_float(row: dict[str, Any] | None, key: str) -> float | str:
    if row is None:
        return ""
    value = as_float(row.get(key))
    return "" if value is None else round(value, 3)


def row_text(row: dict[str, Any] | None, key: str) -> str:
    if row is None:
        return ""
    value = row.get(key, "")
    return "" if value is None else str(value)


def sponsor_anchor_for(
    anchor_rows_: list[dict[str, Any]],
    event_row: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if event_row is None:
        return None
    ts = row_text(event_row, "ts_et")
    lo = as_float(event_row.get("lower"))
    hi = as_float(event_row.get("upper"))
    side = str(event_row.get("side", "")).lower()
    if not ts or lo is None or hi is None or side not in {"demand", "supply"}:
        return None
    for anchor in anchor_rows_:
        if anchor.get("episode_id") != event_row.get("episode_id"):
            continue
        if anchor.get("event") != event_row.get("event"):
            continue
        if row_text(anchor, "ts_et") != ts:
            continue
        if str(anchor.get("side", "")).lower() != side:
            continue
        anchor_lo = as_float(anchor.get("price_lo"))
        anchor_hi = as_float(anchor.get("price_hi"))
        if anchor_lo is None or anchor_hi is None:
            continue
        if abs(anchor_lo - lo) <= 0.01 and abs(anchor_hi - hi) <= 0.01:
            return anchor
    return None


def event_after(
    rows: list[dict[str, Any]],
    start_us: int,
    *,
    event_name: str,
    directive_id: str = "",
    sponsor_id: str = "",
    role: str = "",
) -> dict[str, Any] | None:
    best: tuple[int, dict[str, Any]] | None = None
    for row in rows:
        if row.get("event") != event_name:
            continue
        if directive_id and row.get("directive_id") != directive_id:
            continue
        if sponsor_id and str(row.get("sponsor_id", "")) != sponsor_id:
            continue
        if role and row.get("role") != role:
            continue
        row_us = ts_us_from_row(row)
        if row_us is None or row_us <= start_us:
            continue
        if best is None or row_us < best[0]:
            best = (row_us, row)
    return None if best is None else best[1]


def latest_prior_sponsor_promotion(
    rows: list[dict[str, Any]],
    before_us: int,
    directive_id: str,
    sponsor_id: str,
) -> dict[str, Any] | None:
    best: tuple[int, dict[str, Any]] | None = None
    for row in rows:
        if row.get("event") != "sponsor_promoted":
            continue
        if row.get("directive_id") != directive_id:
            continue
        if str(row.get("sponsor_id", "")) != sponsor_id:
            continue
        row_us = ts_us_from_row(row)
        if row_us is None or row_us >= before_us:
            continue
        if best is None or row_us > best[0]:
            best = (row_us, row)
    return None if best is None else best[1]


def first_trade_stats_after(
    ticks: pl.DataFrame,
    start_us: int | None,
    end_us: int,
    side_label_: str,
) -> dict[str, float | str]:
    out: dict[str, float | str] = {
        "post_failure_start_price": "",
        "post_failure_close": "",
        "post_failure_favorable_pts": "",
        "post_failure_adverse_pts": "",
        "post_failure_volume": "",
        "post_failure_delta": "",
    }
    if start_us is None or ticks.is_empty():
        return out
    rows = ticks.filter((pl.col("timestamp_us") >= start_us) & (pl.col("timestamp_us") <= end_us))
    if rows.is_empty():
        return out
    prices = rows["price"]
    sizes = rows["size"]
    signs = rows["aggressor_sign"]
    start = float(prices[0])
    close = float(prices[-1])
    high = float(prices.max())
    low = float(prices.min())
    sign = side_sign_from_label(side_label_)
    if sign > 0:
        favorable = high - start
        adverse = start - low
    elif sign < 0:
        favorable = start - low
        adverse = high - start
    else:
        favorable = high - start
        adverse = start - low
    out.update(
        {
            "post_failure_start_price": round(start, 2),
            "post_failure_close": round(close, 2),
            "post_failure_favorable_pts": round(float(favorable), 2),
            "post_failure_adverse_pts": round(float(adverse), 2),
            "post_failure_volume": round(float(sizes.sum()), 2),
            "post_failure_delta": round(float((sizes * signs).sum()), 2),
        }
    )
    return out


def build_sponsor_promotion_audit(
    event_rows: list[dict[str, Any]],
    anchor_rows_: list[dict[str, Any]],
    ticks: pl.DataFrame,
    episodes: list[Episode],
) -> list[dict[str, Any]]:
    episodes_by_id = {ep.episode_id: ep for ep in episodes}
    by_episode: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in event_rows:
        by_episode[row["episode_id"]].append(row)
    for rows in by_episode.values():
        rows.sort(key=lambda row: ts_us_from_row(row) or 0)

    out: list[dict[str, Any]] = []
    for episode_id, rows in by_episode.items():
        ep = episodes_by_id.get(episode_id)
        if ep is None:
            continue
        for child in rows:
            if child.get("event") != "sponsor_promoted":
                continue
            prior_id = str(child.get("prior_sponsor_id", "") or "")
            if not prior_id:
                continue
            child_us = ts_us_from_row(child)
            if child_us is None:
                continue
            directive_id = str(child.get("directive_id", "") or "")
            child_id = str(child.get("sponsor_id", "") or "")
            parent = latest_prior_sponsor_promotion(rows, child_us, directive_id, prior_id)
            failure = event_after(
                rows,
                child_us,
                event_name="sponsor_failed",
                directive_id=directive_id,
                sponsor_id=child_id,
            )
            failure_us = ts_us_from_row(failure) if failure else None
            next_entry = event_after(
                rows,
                failure_us or child_us,
                event_name="order_submit",
                directive_id=directive_id,
            )
            parent_failure = event_after(
                rows,
                child_us,
                event_name="sponsor_failed",
                directive_id=directive_id,
                sponsor_id=prior_id,
            )
            child_anchor = sponsor_anchor_for(anchor_rows_, child)
            parent_anchor = sponsor_anchor_for(anchor_rows_, parent)
            failure_anchor = sponsor_anchor_for(anchor_rows_, failure)
            rec: dict[str, Any] = {
                "episode_id": episode_id,
                "directive_id": directive_id,
                "side": child.get("side", ""),
                "child_promoted_et": child.get("ts_et", ""),
                "child_sponsor_id": child_id,
                "child_price_lo": child.get("lower", ""),
                "child_price_hi": child.get("upper", ""),
                "child_reason": child.get("reason", ""),
                "prior_sponsor_id": prior_id,
                "parent_promoted_et": row_text(parent, "ts_et"),
                "parent_price_lo": row_text(parent, "lower"),
                "parent_price_hi": row_text(parent, "upper"),
                "parent_reason": row_text(parent, "reason"),
                "child_failed_et": row_text(failure, "ts_et"),
                "child_failure_reason": row_text(failure, "reason"),
                "parent_failed_after_child_et": row_text(parent_failure, "ts_et"),
                "next_same_directive_order_et": row_text(next_entry, "ts_et"),
                "next_same_directive_order_role": row_text(next_entry, "role"),
                "next_same_directive_order_reason": row_text(next_entry, "reason"),
            }
            for prefix, anchor in (
                ("parent", parent_anchor),
                ("child", child_anchor),
                ("failure", failure_anchor),
            ):
                rec.update(
                    {
                        f"{prefix}_same_start": row_float(anchor, "side_start"),
                        f"{prefix}_same_end_2s": row_float(anchor, "side_end_2s"),
                        f"{prefix}_same_end_5s": row_float(anchor, "side_end_5s"),
                        f"{prefix}_same_end_10s": row_float(anchor, "side_end_10s"),
                        f"{prefix}_opp_start": row_float(anchor, "opp_start"),
                        f"{prefix}_opp_end_2s": row_float(anchor, "opp_end_2s"),
                        f"{prefix}_attack_2s": row_float(anchor, "attack_vol_2s"),
                        f"{prefix}_attack_5s": row_float(anchor, "attack_vol_5s"),
                        f"{prefix}_repl_2s": row_float(anchor, "replenishment_2s"),
                        f"{prefix}_repl_5s": row_float(anchor, "replenishment_5s"),
                        f"{prefix}_rr_2s": row_float(anchor, "reload_ratio_2s"),
                        f"{prefix}_rr_5s": row_float(anchor, "reload_ratio_5s"),
                    }
                )
            rec.update(first_trade_stats_after(ticks, failure_us, ep.end_us, str(child.get("side", ""))))
            child_end_5 = as_float(rec.get("child_same_end_5s"))
            child_end_10 = as_float(rec.get("child_same_end_10s"))
            child_start = as_float(rec.get("child_same_start"))
            child_repl_2 = as_float(rec.get("child_repl_2s"))
            child_repl_5 = as_float(rec.get("child_repl_5s"))
            if child_start is None:
                quality = "unknown"
            elif (child_end_5 is not None and child_end_5 <= 0) or (child_end_10 is not None and child_end_10 <= 0):
                quality = "transient"
            elif (
                child_repl_2 is not None
                and child_repl_5 is not None
                and child_repl_2 < 0
                and child_repl_5 < 0
            ):
                quality = "draining"
            elif child_end_5 is not None and child_end_10 is not None and child_end_5 > 0 and child_end_10 > 0:
                quality = "durable_snapshot"
            else:
                quality = "mixed"
            rec["child_snapshot_quality"] = quality
            out.append(rec)
    return out


def intersects(lo_a: int, hi_a: int, lo_b: int, hi_b: int) -> bool:
    return max(lo_a, lo_b) <= min(hi_a, hi_b)


def churn_label(score: float, two_sided: bool, net_move: float, envelope_width: float) -> str:
    if score >= 6.0 and two_sided:
        return "HIGH_CHURN"
    if score >= 4.0 and two_sided:
        return "MIXED_CHURN"
    if abs(net_move) >= max(40.0, envelope_width * 0.75):
        return "DIRECTIONAL"
    return "LOW_CHURN"


def churn_subtype(
    score: float,
    two_sided: bool,
    two_sided_fail: bool,
    volume_share: float,
    net_move: float,
    envelope_width: float,
    episode_side: str | None,
    bid_change: float,
    ask_change: float,
) -> str:
    low_displacement = abs(net_move) <= max(20.0, envelope_width * 0.30)
    if (
        score >= 5.5
        and two_sided
        and two_sided_fail
        and volume_share >= 0.65
        and low_displacement
        and bid_change >= 0
        and ask_change >= 0
    ):
        return "HVN_CHURN"

    side_sign = side_sign_from_label(episode_side)
    if score >= 4.0 and side_sign and net_move * side_sign <= -max(20.0, envelope_width * 0.35):
        return "REPAIR_CHURN"

    if score >= 4.0 and abs(net_move) >= max(40.0, envelope_width * 0.50):
        return "DIRECTIONAL_CHURN"

    if score >= 4.0 and two_sided:
        return "MIXED_CHURN"

    if abs(net_move) >= max(40.0, envelope_width * 0.75):
        return "DIRECTIONAL"

    return "LOW_CHURN"


def build_churn_envelope_audit(
    event_rows: list[dict[str, Any]],
    ticks: pl.DataFrame,
    snapshots: pl.DataFrame,
    episodes: list[Episode],
    snapshot_summary: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    snap_by_ep = {row["episode_id"]: row for row in snapshot_summary}
    out: list[dict[str, Any]] = []
    for ep in episodes:
        if ep.price_lo is None or ep.price_hi is None:
            continue
        lo_tick = price_to_tick(ep.price_lo)
        hi_tick = price_to_tick(ep.price_hi)
        mins = max((ep.end - ep.start).total_seconds() / 60.0, 1.0)
        counts = Counter()
        for row in event_rows:
            if row.get("episode_id") != ep.episode_id:
                continue
            if row.get("event") != "evidence_transition":
                continue
            band_lo = as_int(row.get("band_min_tick"))
            band_hi = as_int(row.get("band_max_tick"))
            if band_lo is None or band_hi is None:
                continue
            if not intersects(lo_tick, hi_tick, min(band_lo, band_hi), max(band_lo, band_hi)):
                continue
            side = str(row.get("band_side", "")).lower()
            kind = str(row.get("kind", ""))
            if side in {"demand", "supply"}:
                counts[f"{side}_{kind}"] += 1
                counts[f"{side}_total"] += 1
            counts[kind] += 1
            counts["evidence_total"] += 1

        ep_ticks = ticks.filter((pl.col("timestamp_us") >= ep.start_us) & (pl.col("timestamp_us") <= ep.end_us))
        in_range = ep_ticks.filter((pl.col("price") >= ep.price_lo) & (pl.col("price") <= ep.price_hi))
        total_vol = float(ep_ticks["size"].sum()) if not ep_ticks.is_empty() else 0.0
        in_vol = float(in_range["size"].sum()) if not in_range.is_empty() else 0.0
        in_delta = float((in_range["size"] * in_range["aggressor_sign"]).sum()) if not in_range.is_empty() else 0.0
        if ep_ticks.is_empty():
            open_px = close_px = high_px = low_px = math.nan
            net_move = range_pts = 0.0
        else:
            prices = ep_ticks["price"]
            open_px = float(prices[0])
            close_px = float(prices[-1])
            high_px = float(prices.max())
            low_px = float(prices.min())
            net_move = close_px - open_px
            range_pts = high_px - low_px
        snap = snap_by_ep.get(ep.episode_id, {})
        bid_change = as_float(snap.get("range_bid_change")) or 0.0
        ask_change = as_float(snap.get("range_ask_change")) or 0.0
        transition_density = counts["evidence_total"] / mins
        two_sided = counts["demand_total"] > 0 and counts["supply_total"] > 0
        two_sided_fail = counts["demand_RailFailed"] > 0 and counts["supply_RailFailed"] > 0
        vol_share = in_vol / total_vol if total_vol > 0 else 0.0
        envelope_width = max(0.25, ep.price_hi - ep.price_lo)
        score = 0.0
        score += min(2.0, transition_density / 4.0)
        score += 1.5 if two_sided else 0.0
        score += 1.5 if two_sided_fail else 0.0
        score += min(2.0, vol_share * 3.0)
        score += 1.0 if abs(net_move) <= max(20.0, envelope_width * 0.5) else 0.0
        score += 1.0 if bid_change > 0 and ask_change > 0 else 0.0
        out.append(
            {
                "episode_id": ep.episode_id,
                "label": ep.label,
                "window": f"{ep.start.strftime('%H:%M:%S')}-{ep.end.strftime('%H:%M:%S')}",
                "price_lo": round(ep.price_lo, 2),
                "price_hi": round(ep.price_hi, 2),
                "envelope_width_pts": round(envelope_width, 2),
                "evidence_total": counts["evidence_total"],
                "evidence_per_min": round(transition_density, 2),
                "demand_transitions": counts["demand_total"],
                "supply_transitions": counts["supply_total"],
                "demand_owned": counts["demand_RailOwned"],
                "supply_owned": counts["supply_RailOwned"],
                "demand_tested": counts["demand_RailTested"],
                "supply_tested": counts["supply_RailTested"],
                "demand_held": counts["demand_RailHeld"],
                "supply_held": counts["supply_RailHeld"],
                "demand_failed": counts["demand_RailFailed"],
                "supply_failed": counts["supply_RailFailed"],
                "two_sided": two_sided,
                "two_sided_fail": two_sided_fail,
                "open": round_or_blank(open_px),
                "high": round_or_blank(high_px),
                "low": round_or_blank(low_px),
                "close": round_or_blank(close_px),
                "net_move_pts": round(net_move, 2),
                "range_pts": round(range_pts, 2),
                "volume": round(total_vol, 2),
                "volume_in_envelope": round(in_vol, 2),
                "volume_share_in_envelope": round(vol_share, 3),
                "delta_in_envelope": round(in_delta, 2),
                "range_bid_start": snap.get("range_bid_start", ""),
                "range_bid_end": snap.get("range_bid_end", ""),
                "range_bid_change": snap.get("range_bid_change", ""),
                "range_ask_start": snap.get("range_ask_start", ""),
                "range_ask_end": snap.get("range_ask_end", ""),
                "range_ask_change": snap.get("range_ask_change", ""),
                "churn_score": round(score, 2),
                "churn_label": churn_label(score, two_sided, net_move, envelope_width),
                "churn_subtype": churn_subtype(
                    score,
                    two_sided,
                    two_sided_fail,
                    vol_share,
                    net_move,
                    envelope_width,
                    ep.side,
                    bid_change,
                    ask_change,
                ),
            }
        )
    return out


def classify_anchor_quality(anchor: dict[str, Any]) -> str:
    start = as_float(anchor.get("side_start"))
    end_2 = as_float(anchor.get("side_end_2s"))
    end_5 = as_float(anchor.get("side_end_5s"))
    end_10 = as_float(anchor.get("side_end_10s"))
    repl_2 = as_float(anchor.get("replenishment_2s"))
    repl_5 = as_float(anchor.get("replenishment_5s"))
    if start is None:
        return "unknown"
    if (end_5 is not None and end_5 <= 0) or (end_10 is not None and end_10 <= 0):
        return "transient"
    if repl_2 is not None and repl_5 is not None and repl_2 < 0 and repl_5 < 0:
        return "draining"
    if end_2 is not None and end_5 is not None and repl_2 is not None and end_2 > 0 and end_5 > 0 and repl_2 >= 0:
        return "survived_first_contact"
    return "mixed"


def anchor_forward_stats(
    ticks: pl.DataFrame,
    anchor: dict[str, Any],
    end_us: int,
    horizon_sec: int,
) -> dict[str, float | str]:
    suffix = f"{horizon_sec // 60}m" if horizon_sec % 60 == 0 else f"{horizon_sec}s"
    result: dict[str, float | str] = {
        f"favorable_{suffix}": "",
        f"adverse_{suffix}": "",
        f"close_move_{suffix}": "",
    }
    start_us = ts_us_from_row(anchor)
    side_sign = side_sign_from_label(anchor.get("side"))
    if start_us is None or side_sign == 0 or ticks.is_empty():
        return result
    stop_us = min(end_us, start_us + horizon_sec * 1_000_000)
    rows = ticks.filter((pl.col("timestamp_us") >= start_us) & (pl.col("timestamp_us") <= stop_us))
    if rows.is_empty():
        return result
    prices = rows["price"]
    start = float(prices[0])
    high = float(prices.max())
    low = float(prices.min())
    close = float(prices[-1])
    if side_sign > 0:
        favorable = high - start
        adverse = start - low
        close_move = close - start
    else:
        favorable = start - low
        adverse = high - start
        close_move = start - close
    result.update(
        {
            f"favorable_{suffix}": round(favorable, 2),
            f"adverse_{suffix}": round(adverse, 2),
            f"close_move_{suffix}": round(close_move, 2),
        }
    )
    return result


def build_anchor_outcome_audit(
    anchor_rows_: list[dict[str, Any]],
    ticks: pl.DataFrame,
    episodes: list[Episode],
) -> list[dict[str, Any]]:
    episodes_by_id = {ep.episode_id: ep for ep in episodes}
    out: list[dict[str, Any]] = []
    for anchor in anchor_rows_:
        ep = episodes_by_id.get(str(anchor.get("episode_id", "")))
        if ep is None:
            continue
        rec: dict[str, Any] = {
            "episode_id": anchor.get("episode_id", ""),
            "anchor_id": anchor.get("anchor_id", ""),
            "ts_et": anchor.get("ts_et", ""),
            "source": anchor.get("source", ""),
            "event": anchor.get("event", ""),
            "reason": anchor.get("reason", ""),
            "side": anchor.get("side", ""),
            "price_lo": anchor.get("price_lo", ""),
            "price_hi": anchor.get("price_hi", ""),
            "side_start": anchor.get("side_start", ""),
            "side_end_2s": anchor.get("side_end_2s", ""),
            "side_end_5s": anchor.get("side_end_5s", ""),
            "side_end_10s": anchor.get("side_end_10s", ""),
            "opp_start": anchor.get("opp_start", ""),
            "opp_end_2s": anchor.get("opp_end_2s", ""),
            "attack_2s": anchor.get("attack_vol_2s", ""),
            "attack_5s": anchor.get("attack_vol_5s", ""),
            "repl_2s": anchor.get("replenishment_2s", ""),
            "repl_5s": anchor.get("replenishment_5s", ""),
            "rr_2s": anchor.get("reload_ratio_2s", ""),
            "rr_5s": anchor.get("reload_ratio_5s", ""),
            "anchor_quality": classify_anchor_quality(anchor),
        }
        for horizon in (120, 300, 600, 1200):
            rec.update(anchor_forward_stats(ticks, anchor, ep.end_us, horizon))
        out.append(rec)
    return out


def round_or_blank(value: float | None, places: int = 2) -> float | str:
    if value is None or not math.isfinite(value):
        return ""
    return round(value, places)


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def write_report(
    path: Path,
    date: str,
    symbol_dir: str,
    episodes: list[Episode],
    event_rows: list[dict[str, Any]],
    tape_summary: list[dict[str, Any]],
    snapshot_summary: list[dict[str, Any]],
    anchors: list[dict[str, Any]],
    health: BookHealth,
    out_files: dict[str, Path],
) -> None:
    events_by_ep: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in event_rows:
        events_by_ep[row["episode_id"]].append(row)
    tape_by_ep = {row["episode_id"]: row for row in tape_summary}
    snap_by_ep = {row["episode_id"]: row for row in snapshot_summary}
    anchor_by_ep: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in anchors:
        anchor_by_ep[row["episode_id"]].append(row)

    lines = [
        f"# Episode Execution LOB Probe - {date}",
        "",
        "Research-only running findings. EAR events are live runtime evidence; MarketRecorder is independent NQU6 market/book evidence.",
        "",
        "## Outputs",
    ]
    for label, file_path in out_files.items():
        lines.append(f"- {label}: `{file_path}`")
    lines.extend(
        [
            "",
            "## Book Replay Health",
            f"- symbol: `{symbol_dir}`",
            f"- book_event_files: {health.files}",
            f"- carry_days: {health.carry_days}",
            f"- rows_processed: {health.rows_processed:,}",
            f"- gaps: {health.gaps}",
            f"- resets: {health.resets}",
            f"- crossed_repairs: {health.crossed_levels_evicted} levels / {health.crossed_quotes_evicted} quotes",
            "",
            "## Episode Reads",
        ]
    )

    for ep in episodes:
        lines.extend(
            [
                "",
                f"### {ep.episode_id} - {ep.label}",
                "",
                f"- Window: {ep.start.strftime('%H:%M:%S')}-{ep.end.strftime('%H:%M:%S')} ET.",
                f"- Price focus: {ep.price_text or 'not specified'}.",
            ]
        )
        if ep.note:
            lines.append(f"- Note: {ep.note}.")
        tape = tape_by_ep.get(ep.episode_id)
        if tape:
            lines.append(
                "- Tape: "
                f"O={tape['open']:.2f} H={tape['high']:.2f} L={tape['low']:.2f} "
                f"C={tape['close']:.2f}, range={tape['range_pts']:.2f}, "
                f"vol={tape['volume']:.0f}, delta={tape['delta']:+.0f}, trades={tape['trades']}."
            )
        snap = snap_by_ep.get(ep.episode_id)
        if snap:
            lines.append(
                "- Snapshot book: "
                f"top20 bid {snap['top20_bid_start']:.0f}->{snap['top20_bid_end']:.0f} "
                f"({snap['top20_bid_change']:+.0f}), top20 ask "
                f"{snap['top20_ask_start']:.0f}->{snap['top20_ask_end']:.0f} "
                f"({snap['top20_ask_change']:+.0f})."
            )
            if "range_bid_start" in snap:
                lines.append(
                    "- Focus range book: "
                    f"bid {snap['range_bid_start']:.0f}->{snap['range_bid_end']:.0f} "
                    f"({snap['range_bid_change']:+.0f}), ask "
                    f"{snap['range_ask_start']:.0f}->{snap['range_ask_end']:.0f} "
                    f"({snap['range_ask_change']:+.0f})."
                )

        ep_events = events_by_ep.get(ep.episode_id, [])
        event_counts = Counter(str(row.get("event", "")) for row in ep_events)
        if event_counts:
            count_text = ", ".join(f"{k}={v}" for k, v in event_counts.most_common(8))
            lines.append(f"- EAR event counts: {count_text}.")
        directives = [
            row for row in ep_events
            if row.get("event") in {"directive_accepted", "order_submit", "trade_fill", "flatten_result", "sponsor_promoted", "sponsor_failed", "entry_paused"}
        ]
        if directives:
            lines.append("")
            lines.append("Key EAR timeline:")
            for row in directives[:18]:
                lines.append(f"- {timeline_text(row)}")
            if len(directives) > 18:
                lines.append(f"- ... {len(directives) - 18} more rows in CSV.")

        ep_anchors = anchor_by_ep.get(ep.episode_id, [])
        if ep_anchors:
            lines.append("")
            lines.append("Book/contact anchors:")
            for row in ep_anchors[:14]:
                lines.append(f"- {anchor_text(row)}")
            if len(ep_anchors) > 14:
                lines.append(f"- ... {len(ep_anchors) - 14} more anchors in CSV.")
    lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def timeline_text(row: dict[str, Any]) -> str:
    ts = str(row.get("ts_et", ""))[11:]
    event = row.get("event", "")
    if event == "directive_accepted":
        return f"{ts} directive accepted {row.get('side')} id={row.get('directive_id')} target={row.get('target_price', '')}"
    if event == "order_submit":
        band = f"{row.get('support_min_price', '')}-{row.get('support_max_price', '')}"
        return f"{ts} submit {row.get('role')} {row.get('side')} qty={row.get('quantity')} reason={row.get('reason')} band={band}"
    if event == "trade_fill":
        return f"{ts} fill {row.get('side')} qty={row.get('quantity')} px={row.get('price', row.get('fill_price', ''))}"
    if event == "flatten_result":
        return f"{ts} flatten qty={row.get('quantity')} reason={row.get('reason')} accepted={row.get('accepted')}"
    if event == "sponsor_promoted":
        return f"{ts} sponsor promoted {row.get('side')} id={row.get('sponsor_id')} {row.get('lower')}-{row.get('upper')} reason={row.get('reason')}"
    if event == "sponsor_failed":
        return f"{ts} sponsor failed {row.get('side')} id={row.get('sponsor_id')} {row.get('lower')}-{row.get('upper')}"
    if event == "entry_paused":
        return f"{ts} entry paused directive={row.get('directive_id')}"
    return f"{ts} {event}"


def anchor_text(row: dict[str, Any]) -> str:
    price = f"{row['price_lo']:.2f}-{row['price_hi']:.2f}"
    s2 = row.get("side_start", "")
    e2 = row.get("side_end_2s", "")
    atk = row.get("attack_vol_2s", "")
    rep = row.get("replenishment_2s", "")
    rr = row.get("reload_ratio_2s", "")
    return (
        f"{row['ts_et'][11:]} {row['source']} {row['side']} {price}: "
        f"side depth {s2}->{e2}, attack2s={atk}, repl2s={rep}, rr2s={rr}"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default="2026-07-24")
    parser.add_argument("--symbol-dir", default="NQU6")
    parser.add_argument("--capture-root", default=MARKET_RECORDER_ROOT)
    parser.add_argument("--ear-events", default=r"C:\Users\j\Documents\ExecAssistantRuntime\events.jsonl")
    parser.add_argument("--episode", action="append", help="id|HH:MM-HH:MM|label[|price_lo-price_hi][|side][|note]")
    parser.add_argument(
        "--out-dir",
        default=str(OUTPUT_ROOT / "episode_exec_lob_probe_20260724"),
    )
    parser.add_argument("--max-carry-days", type=int, default=7)
    parser.add_argument(
        "--book-events",
        action="store_true",
        help="Stream raw quote events for add/remove deltas. Slower; snapshot/tape metrics always run.",
    )
    args = parser.parse_args()

    episodes = (
        [parse_episode_spec(value, args.date) for value in args.episode]
        if args.episode
        else default_episodes(args.date)
    )
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    ear_events = read_ear_events(Path(args.ear_events), episodes)
    event_rows = [
        slim_event_row(event, episode_id)
        for event in ear_events
        for episode_id in event["episode_ids"]
    ]
    anchors = build_book_anchors(ear_events)

    ticks = load_ticks_for_episodes(args.symbol_dir, episodes)
    snapshots = load_snapshots_for_episodes(args.symbol_dir, episodes)
    add_tick_metrics_to_anchors(ticks, anchors)
    add_snapshot_metrics_to_anchors(snapshots, anchors)
    stop_us = max(ep.end_us for ep in episodes) + int((max(BOOK_WINDOWS) + 2) * 1_000_000)
    if args.book_events:
        health = stream_book_anchors(args.capture_root, args.symbol_dir, args.date, anchors, stop_us, args.max_carry_days)
    else:
        health = BookHealth()

    tape_summary = episode_tape_summary(ticks, episodes)
    snap_summary = episode_snapshot_summary(snapshots, episodes)
    bar_1m = tape_bars(ticks, episodes, "1m")
    bar_5s = tape_bars(ticks, episodes, "5s")
    book_rows = anchor_rows(anchors)
    sponsor_audit = build_sponsor_promotion_audit(event_rows, book_rows, ticks, episodes)
    churn_audit = build_churn_envelope_audit(event_rows, ticks, snapshots, episodes, snap_summary)
    anchor_outcome = build_anchor_outcome_audit(book_rows, ticks, episodes)

    files = {
        "events": out_dir / "ear_events.csv",
        "tape_summary": out_dir / "tape_summary.csv",
        "snapshot_summary": out_dir / "snapshot_summary.csv",
        "book_anchors": out_dir / "book_anchors.csv",
        "bars_1m": out_dir / "bars_1m.csv",
        "bars_5s": out_dir / "bars_5s.csv",
        "sponsor_promotion_audit": out_dir / "sponsor_promotion_audit.csv",
        "churn_envelope_audit": out_dir / "churn_envelope_audit.csv",
        "anchor_outcome_audit": out_dir / "anchor_outcome_audit.csv",
    }
    write_csv(files["events"], event_rows)
    write_csv(files["tape_summary"], tape_summary)
    write_csv(files["snapshot_summary"], snap_summary)
    write_csv(files["book_anchors"], book_rows)
    write_csv(files["bars_1m"], bar_1m)
    write_csv(files["bars_5s"], bar_5s)
    write_csv(files["sponsor_promotion_audit"], sponsor_audit)
    write_csv(files["churn_envelope_audit"], churn_audit)
    write_csv(files["anchor_outcome_audit"], anchor_outcome)
    report = out_dir / "findings.md"
    write_report(
        report,
        args.date,
        args.symbol_dir,
        episodes,
        event_rows,
        tape_summary,
        snap_summary,
        book_rows,
        health,
        files,
    )
    print(f"wrote {report}")
    for label, path in files.items():
        print(f"wrote {label}: {path}")


if __name__ == "__main__":
    main()
