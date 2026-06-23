"""Validate MarketRecorder raw L2 event replay against canonical snapshots.

The event stream is trustworthy for OFI only after a complete DOM reset and
while no explicit continuity gap is active. This tool reconstructs quote-id
state, aggregates it by price, and compares the reconstructed top levels with
the existing periodic snapshot stream.

Receipt timestamps are used for alignment because Quantower mutates its
canonical DepthOfMarket before invoking NewLevel2. Boundary races can still
create an occasional one-sample mismatch; the report exposes rates and examples
instead of silently repairing them.
"""

from __future__ import annotations

import argparse
import glob
import math
import os
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import polars as pl


NY = ZoneInfo("America/New_York")
TICK_SIZE = 0.25
DELTA = 1
RESET_BEGIN = 2
RESET_ITEM = 3
RESET_END = 4
GAP = 5

EVENT_COLUMNS = [
    "receipt_timestamp_us",
    "exchange_timestamp_us",
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
    "gap_start_sequence",
    "gap_end_sequence",
]


@dataclass(frozen=True)
class QuoteState:
    side: int
    price_tick: int
    size: float


class BookReplay:
    def __init__(self) -> None:
        self.quotes: dict[int, QuoteState] = {}
        self.bid_levels: dict[int, float] = defaultdict(float)
        self.ask_levels: dict[int, float] = defaultdict(float)
        self.seeded = False
        self.valid = False
        self.reset_epoch = 0
        self.pending_reset_items = 0
        self.expected_reset_items = 0
        self.completed_resets = 0
        self.incomplete_resets = 0
        self.gaps = 0
        self.deltas = 0
        self.preseed_deltas = 0

    def apply(self, row: dict) -> None:
        kind = int(row["event_kind"])
        if kind == GAP:
            self.valid = False
            self.gaps += 1
            return
        if kind == RESET_BEGIN:
            self.quotes.clear()
            self.bid_levels.clear()
            self.ask_levels.clear()
            self.seeded = False
            self.valid = False
            self.reset_epoch = int(row["reset_epoch"])
            self.pending_reset_items = 0
            self.expected_reset_items = int(row["reset_item_count"])
            return
        if kind == RESET_ITEM:
            self._set_quote(row)
            self.pending_reset_items += 1
            return
        if kind == RESET_END:
            complete = self.pending_reset_items == self.expected_reset_items
            if complete:
                self.seeded = True
                self.valid = True
                self.completed_resets += 1
            else:
                self.incomplete_resets += 1
                self.valid = False
            return
        if kind != DELTA:
            return
        self.deltas += 1
        if not self.seeded:
            self.preseed_deltas += 1
            return
        if not self.valid:
            return
        quote_id = int(row["quote_id_hash"])
        if bool(row["closed"]):
            self._remove_quote(quote_id)
        else:
            self._set_quote(row)

    def _set_quote(self, row: dict) -> None:
        quote_id = int(row["quote_id_hash"])
        if bool(row["closed"]):
            self._remove_quote(quote_id)
            return
        side = int(row["side"])
        price_tick = int(row["price_tick"])
        size = float(row["size"])
        if quote_id == 0 or side not in (-1, 1) or price_tick == -(2**63):
            return
        if not math.isfinite(size) or size < 0:
            return
        self._remove_quote(quote_id)
        state = QuoteState(side=side, price_tick=price_tick, size=size)
        self.quotes[quote_id] = state
        levels = self.bid_levels if side > 0 else self.ask_levels
        levels[price_tick] += size

    def _remove_quote(self, quote_id: int) -> None:
        prior = self.quotes.pop(quote_id, None)
        if prior is None:
            return
        levels = self.bid_levels if prior.side > 0 else self.ask_levels
        remaining = levels.get(prior.price_tick, 0.0) - prior.size
        if remaining > 1e-9:
            levels[prior.price_tick] = remaining
        else:
            levels.pop(prior.price_tick, None)

    def top(self, levels: int) -> tuple[list[tuple[int, float]], list[tuple[int, float]]]:
        bids = sorted(self.bid_levels.items(), reverse=True)[:levels]
        asks = sorted(self.ask_levels.items())[:levels]
        return bids, asks


def load_parquet(pattern: str, columns: list[str]) -> pl.DataFrame:
    files = sorted(glob.glob(pattern))
    if not files:
        raise FileNotFoundError(pattern)
    return pl.scan_parquet(files).select(columns).collect()


def snapshot_columns(levels: int) -> list[str]:
    columns = ["timestamp_us", "ref_tick"]
    for index in range(levels):
        columns.extend(
            [
                f"bid_offset_{index}",
                f"bid_size_{index}",
                f"ask_offset_{index}",
                f"ask_size_{index}",
            ]
        )
    return columns


def snapshot_levels(row: dict, levels: int) -> tuple[list[tuple[int, float]], list[tuple[int, float]]]:
    ref = int(row["ref_tick"])
    bids: list[tuple[int, float]] = []
    asks: list[tuple[int, float]] = []
    for index in range(levels):
        bid_size = float(row[f"bid_size_{index}"])
        ask_size = float(row[f"ask_size_{index}"])
        if math.isfinite(bid_size) and bid_size > 0:
            bids.append((ref + int(row[f"bid_offset_{index}"]), bid_size))
        if math.isfinite(ask_size) and ask_size > 0:
            asks.append((ref + int(row[f"ask_offset_{index}"]), ask_size))
    return bids, asks


def level_match(left: list[tuple[int, float]], right: list[tuple[int, float]], levels: int) -> bool:
    if len(left) < levels or len(right) < levels:
        return False
    for (left_tick, left_size), (right_tick, right_size) in zip(left[:levels], right[:levels]):
        if left_tick != right_tick or abs(left_size - right_size) > 1e-6:
            return False
    return True


def ny_time(timestamp_us: int) -> str:
    return datetime.fromtimestamp(timestamp_us / 1_000_000, timezone.utc).astimezone(NY).isoformat()


def self_test() -> None:
    replay = BookReplay()

    def row(kind: int, **values) -> dict:
        base = {
            "event_kind": kind,
            "reset_epoch": 1,
            "reset_item_count": 0,
            "quote_id_hash": 0,
            "side": 0,
            "price_tick": -(2**63),
            "size": math.nan,
            "closed": False,
        }
        base.update(values)
        return base

    replay.apply(row(RESET_BEGIN, reset_item_count=2))
    replay.apply(row(RESET_ITEM, quote_id_hash=1, side=1, price_tick=100, size=10.0))
    replay.apply(row(RESET_ITEM, quote_id_hash=2, side=-1, price_tick=102, size=12.0))
    replay.apply(row(RESET_END, reset_item_count=2))
    assert replay.valid and replay.top(1) == ([(100, 10.0)], [(102, 12.0)])
    replay.apply(row(DELTA, quote_id_hash=1, side=1, price_tick=100, size=15.0))
    replay.apply(row(DELTA, quote_id_hash=3, side=1, price_tick=101, size=5.0))
    assert replay.top(1)[0] == [(101, 5.0)]
    replay.apply(row(DELTA, quote_id_hash=3, side=1, price_tick=101, size=0.0, closed=True))
    assert replay.top(1)[0] == [(100, 15.0)]
    replay.apply(row(GAP))
    assert not replay.valid


def validate(args) -> None:
    day_root = Path(args.capture_root) / args.symbol_dir / args.date
    # Sequence numbers are process-local and restart at one. Receipt time is
    # the session-wide ordering key; sequence/subsequence resolve ties.
    events = load_parquet(str(day_root / "book_events" / "*.parquet"), EVENT_COLUMNS).sort(
        ["receipt_timestamp_us", "sequence", "subsequence"]
    )
    snapshots = load_parquet(
        str(day_root / "snapshots" / "*.parquet"),
        snapshot_columns(args.levels),
    ).sort("timestamp_us")

    event_rows = events.iter_rows(named=True)
    event = next(event_rows, None)
    replay = BookReplay()
    compared = 0
    skipped_unseeded = 0
    skipped_invalid = 0
    best_matches = 0
    top_matches = 0
    examples: list[str] = []

    for snapshot in snapshots.iter_rows(named=True):
        snapshot_us = int(snapshot["timestamp_us"])
        while event is not None and int(event["receipt_timestamp_us"]) <= snapshot_us:
            replay.apply(event)
            event = next(event_rows, None)
        if not replay.seeded:
            skipped_unseeded += 1
            continue
        if not replay.valid:
            skipped_invalid += 1
            continue
        actual_bids, actual_asks = snapshot_levels(snapshot, args.levels)
        replay_bids, replay_asks = replay.top(args.levels)
        compared += 1
        best_ok = level_match(actual_bids, replay_bids, 1) and level_match(actual_asks, replay_asks, 1)
        top_ok = level_match(actual_bids, replay_bids, args.levels) and level_match(
            actual_asks, replay_asks, args.levels
        )
        best_matches += int(best_ok)
        top_matches += int(top_ok)
        if not top_ok and len(examples) < args.examples:
            examples.append(
                f"{ny_time(snapshot_us)} best_ok={best_ok} "
                f"snap_bid={actual_bids[:2]} replay_bid={replay_bids[:2]} "
                f"snap_ask={actual_asks[:2]} replay_ask={replay_asks[:2]}"
            )

    print(f"{args.date} {args.symbol_dir} raw book-event validation")
    print(
        f"event_rows={events.height} deltas={replay.deltas} resets={replay.completed_resets} "
        f"incomplete_resets={replay.incomplete_resets} gaps={replay.gaps} "
        f"preseed_deltas={replay.preseed_deltas}"
    )
    print(
        f"snapshots={snapshots.height} compared={compared} skipped_unseeded={skipped_unseeded} "
        f"skipped_invalid={skipped_invalid}"
    )
    if compared:
        print(
            f"best_match={best_matches}/{compared} ({100.0 * best_matches / compared:.2f}%) "
            f"top{args.levels}_match={top_matches}/{compared} ({100.0 * top_matches / compared:.2f}%)"
        )
    for example in examples:
        print("  " + example)


def main() -> None:
    self_test()
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", required=True)
    parser.add_argument("--symbol-dir", default="NQU6")
    parser.add_argument(
        "--capture-root",
        default=r"C:\Quantower\Settings\Scripts\Indicators\MarketRecorder\captures",
    )
    parser.add_argument("--levels", type=int, default=5)
    parser.add_argument("--examples", type=int, default=10)
    args = parser.parse_args()
    validate(args)


if __name__ == "__main__":
    main()
