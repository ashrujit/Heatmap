"""Build causal LOB states from direct-conversion execution proximity onward.

The rail supplies direction, location, and structural resolution.  This probe
starts when the executable DOM quote first comes within EAR's 20-tick direct-
conversion envelope and observes the book until structural resolution or the
configured research horizon.  Profile terrain is deliberately absent.

Raw quote-id deltas provide additions/removals.  Trade tape separately measures
aggressive consumption; ``removal - consumption`` is only a cancellation
proxy, not an exact event attribution.  Capture resets terminate episodes so
the probe never invents flow across a discontinuity.
"""

from __future__ import annotations

import argparse
import bisect
import csv
import gc
import heapq
import math
import sys
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo

import polars as pl

from _paths import OUTPUT_ROOT, REPO_ROOT as ROOT

sys.path.insert(0, str(ROOT / "MarketRecorder" / "research"))

from capture_loader import (  # noqa: E402
    MARKET_RECORDER_ROOT,
    load_capture_window,
    market_recorder_files,
    tick_columns,
)
from validate_book_events import (  # noqa: E402
    BookReplay,
    DELTA,
    EVENT_COLUMNS,
    GAP,
    RESET_BEGIN,
    RESET_END,
)
from direct_conversion_sponsor_lineage import (  # noqa: E402
    DEFAULT_EVENTS,
    Rail as RuntimeRail,
    favorable_of,
    load_runtime,
)


NY = ZoneInfo("America/New_York")
TICK_SIZE = 0.25
BID = 1
ASK = -1
PROXIMITY_TICKS = 20
FIELD_BEHIND_TICKS = 8
FIELD_BEYOND_TICKS = 8
ROAD_LEVELS = 8
PRE_FLOW_S = 5.0
BUCKET_US = 250_000
FLOW_WINDOWS_S = (0.5, 2.0, 5.0)
DEFAULT_LINEAGE = (
    OUTPUT_ROOT / "direct_conversion_sponsor_lineage" / "lineage.csv"
)
DEFAULT_OUT = (
    OUTPUT_ROOT / "direct_conversion_proximity_book_20260717_20260724"
)

ADVANCED = "ADVANCED_TO_FAVORABLE_SUCCESSOR"
FAILED = "ROOT_FAILED_FIRST"

C_TS = EVENT_COLUMNS.index("receipt_timestamp_us")
C_KIND = EVENT_COLUMNS.index("event_kind")
C_SIDE = EVENT_COLUMNS.index("side")
C_TICK = EVENT_COLUMNS.index("price_tick")
C_SIZE = EVENT_COLUMNS.index("size")
C_CLOSED = EVENT_COLUMNS.index("closed")
C_QID = EVENT_COLUMNS.index("quote_id_hash")
C_EPOCH = EVENT_COLUMNS.index("reset_epoch")
C_ITEMS = EVENT_COLUMNS.index("reset_item_count")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lineage-csv", type=Path, default=DEFAULT_LINEAGE)
    parser.add_argument("--events", type=Path, default=DEFAULT_EVENTS)
    parser.add_argument("--lineage-start-date", default="2026-06-22")
    parser.add_argument("--start-date", default="2026-07-17")
    parser.add_argument("--end-date", default="2026-07-24")
    parser.add_argument("--symbol-dir", default="NQU6")
    parser.add_argument("--capture-root", default=MARKET_RECORDER_ROOT)
    parser.add_argument("--max-decision-seconds", type=float, default=300.0)
    parser.add_argument("--batch-files", type=int, default=40)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    return parser.parse_args()


def parse_et(day: str, value: str) -> datetime:
    text = value.strip()
    if "T" in text:
        parsed = datetime.fromisoformat(text)
    else:
        parsed = datetime.fromisoformat(f"{day}T{text.split()[-1]}")
    return parsed.replace(tzinfo=NY) if parsed.tzinfo is None else parsed.astimezone(NY)


def to_us(value: datetime) -> int:
    return int(value.timestamp() * 1_000_000)


def et_text(value_us: int | None) -> str:
    if value_us is None:
        return ""
    return datetime.fromtimestamp(value_us / 1_000_000, NY).strftime(
        "%Y-%m-%d %H:%M:%S.%f"
    )[:-3]


def truth(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes"}


def number(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fields: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for key in row:
            if key not in seen:
                fields.append(key)
                seen.add(key)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def sample_offsets_us(max_seconds: float) -> tuple[int, ...]:
    values = {0}
    stop_us = int(max_seconds * 1_000_000)
    value = BUCKET_US
    while value <= min(stop_us, 10_000_000):
        values.add(value)
        value += BUCKET_US
    value = 11_000_000
    while value <= min(stop_us, 60_000_000):
        values.add(value)
        value += 1_000_000
    value = 65_000_000
    while value <= stop_us:
        values.add(value)
        value += 5_000_000
    return tuple(sorted(values))


@dataclass
class Root:
    session_id: str
    date: str
    root_id: str
    side: str
    lo_tick: int
    hi_tick: int
    owned_us: int
    failed_us: int | None
    original_structural_outcome: str
    first_test_verdict: str
    first_tested_et: str
    first_test_resolved_et: str

    @property
    def key(self) -> tuple[str, str, str]:
        return self.session_id, self.date, self.root_id

    @property
    def favorable_sign(self) -> int:
        return 1 if self.side == "Demand" else -1

    @property
    def owner_book_side(self) -> int:
        return BID if self.side == "Demand" else ASK


@dataclass
class Episode:
    root: Root
    proximity_us: int
    proximity_exec_tick: int
    proximity_distance_ticks: int
    structural_end_us: int
    structural_outcome: str
    successor_id: int | None
    successor_source: str
    stop_us: int
    structural_after_horizon: bool
    offsets_us: tuple[int, ...]
    status: str = "started"
    status_reason: str = ""
    sample_index: int = 0
    samples: list[dict[str, Any]] = field(default_factory=list)
    book_bins: dict[int, dict[str, float]] = field(
        default_factory=lambda: defaultdict(lambda: defaultdict(float))
    )
    tape_bins: dict[int, dict[str, float]] = field(
        default_factory=lambda: defaultdict(lambda: defaultdict(float))
    )

    @property
    def key(self) -> tuple[str, str, str]:
        return self.root.key


@dataclass(frozen=True)
class DeltaRecord:
    ts_us: int
    side: int
    tick: int
    diff: float
    best_bid: int | None
    best_ask: int | None


def load_roots(path: Path, start_date: str, end_date: str) -> list[Root]:
    output: list[Root] = []
    with path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            day = row["date"]
            if not (start_date <= day <= end_date):
                continue
            if row.get("root_source") != "Consumed":
                continue
            outcome = row.get("structural_outcome", "")
            if outcome not in {ADVANCED, FAILED}:
                continue
            owned = parse_et(day, row["root_owned_et"])
            failed_text = row.get("root_failed_et", "")
            failed_us = to_us(parse_et(day, failed_text)) if failed_text else None
            minute = owned.hour * 60 + owned.minute
            if minute < 570 or minute >= 960:
                continue
            output.append(
                Root(
                    session_id=row.get("session_id", ""),
                    date=day,
                    root_id=row["root_id"],
                    side=row["side"],
                    lo_tick=round(float(row["root_lo"]) / TICK_SIZE),
                    hi_tick=round(float(row["root_hi"]) / TICK_SIZE),
                    owned_us=to_us(owned),
                    failed_us=failed_us,
                    original_structural_outcome=outcome,
                    first_test_verdict=row.get("root_first_test_verdict", ""),
                    first_tested_et=row.get("root_first_tested_et", ""),
                    first_test_resolved_et=row.get("root_first_test_resolved_et", ""),
                )
            )
    return sorted(output, key=lambda root: (root.date, root.owned_us, root.session_id))


def resolve_after_proximity(
    root: Root,
    proximity_us: int,
    runtime_by_key: dict[tuple[str, str], RuntimeRail],
    runtime_by_session: dict[str, list[RuntimeRail]],
) -> tuple[str, int, RuntimeRail | None] | None:
    runtime_root = runtime_by_key.get((root.session_id, root.root_id))
    if runtime_root is None:
        return None
    successor = next(
        (
            candidate
            for candidate in runtime_by_session.get(root.session_id, [])
            if to_us(candidate.owned_utc.astimezone(NY)) > proximity_us
            and favorable_of(runtime_root, candidate)
        ),
        None,
    )
    successor_us = (
        to_us(successor.owned_utc.astimezone(NY)) if successor is not None else None
    )
    failure_us = root.failed_us
    if successor_us is not None and (
        failure_us is None or successor_us < failure_us
    ):
        return ADVANCED, successor_us, successor
    if failure_us is not None and failure_us > proximity_us:
        return FAILED, failure_us, None
    return None


def best_ticks(replay: BookReplay) -> tuple[int | None, int | None]:
    return replay._best_tick(BID), replay._best_tick(ASK)


def executable_tick(root: Root, best_bid: int | None, best_ask: int | None) -> int | None:
    return best_ask if root.side == "Demand" else best_bid


def range_distance(tick: int, lo_tick: int, hi_tick: int) -> int:
    if tick < lo_tick:
        return lo_tick - tick
    if tick > hi_tick:
        return tick - hi_tick
    return 0


def signed_coord(root: Root, tick: int) -> int:
    if root.side == "Demand":
        if tick < root.lo_tick:
            return tick - root.lo_tick
        if tick > root.hi_tick:
            return tick - root.hi_tick
        return 0
    if tick > root.hi_tick:
        return root.hi_tick - tick
    if tick < root.lo_tick:
        return root.lo_tick - tick
    return 0


def fixed_region(coord: int) -> str | None:
    if -FIELD_BEHIND_TICKS <= coord < 0:
        return "behind"
    if coord == 0:
        return "rail"
    if 0 < coord <= PROXIMITY_TICKS:
        return "bridge"
    if PROXIMITY_TICKS < coord <= PROXIMITY_TICKS + FIELD_BEYOND_TICKS:
        return "beyond"
    return None


def episode_tick_range(root: Root) -> range:
    if root.side == "Demand":
        return range(
            root.lo_tick - FIELD_BEHIND_TICKS,
            root.hi_tick + PROXIMITY_TICKS + FIELD_BEYOND_TICKS + 1,
        )
    return range(
        root.lo_tick - PROXIMITY_TICKS - FIELD_BEYOND_TICKS,
        root.hi_tick + FIELD_BEHIND_TICKS + 1,
    )


def flow_bucket(episode: Episode, ts_us: int) -> int:
    return math.floor((ts_us - episode.proximity_us) / BUCKET_US)


def add_flow(
    episode: Episode,
    target: dict[str, float],
    side: int,
    tick: int,
    diff: float,
    best_bid: int | None,
    best_ask: int | None,
) -> None:
    if abs(diff) <= 1e-9:
        return
    root = episode.root
    coord = signed_coord(root, tick)
    region = fixed_region(coord)
    role = "owner" if side == root.owner_book_side else "opponent"
    kind = "add" if diff > 0 else "remove"
    amount = abs(diff)
    if region is not None:
        target[f"{role}_{region}_{kind}"] += amount
        target[f"{role}_{region}_{kind}_events"] += 1.0
        target[f"{role}_field_{kind}"] += amount
        target[f"{role}_field_{kind}_events"] += 1.0

    exec_tick = executable_tick(root, best_bid, best_ask)
    if role == "opponent" and exec_tick is not None:
        exec_coord = signed_coord(root, exec_tick)
        if exec_coord <= coord < exec_coord + ROAD_LEVELS:
            target[f"opponent_road_{kind}"] += amount
            target[f"opponent_road_{kind}_events"] += 1.0
    if role == "owner" and -FIELD_BEHIND_TICKS <= coord <= 0:
        target[f"owner_under_{kind}"] += amount
        target[f"owner_under_{kind}_events"] += 1.0


def decompose_delta(row: tuple[Any, ...], replay: BookReplay) -> tuple[tuple[int, int, float], ...]:
    quote_id = int(row[C_QID])
    prior = replay.quotes.get(quote_id)
    if bool(row[C_CLOSED]):
        if prior is None:
            return ()
        return ((prior.side, prior.price_tick, -prior.size),)

    side = int(row[C_SIDE])
    tick = int(row[C_TICK])
    size = float(row[C_SIZE])
    if (
        quote_id == 0
        or side not in (BID, ASK)
        or tick == -(2**63)
        or not math.isfinite(size)
        or size < 0
    ):
        return ()
    if prior is None:
        return ((side, tick, size),) if size > 0 else ()
    if prior.side == side and prior.price_tick == tick:
        diff = size - prior.size
        return ((side, tick, diff),) if abs(diff) > 1e-9 else ()
    output = [(prior.side, prior.price_tick, -prior.size)]
    if size > 0:
        output.append((side, tick, size))
    return tuple(output)


def range_depth(levels: dict[int, float], ticks: Iterable[int]) -> float:
    return sum(levels.get(tick, 0.0) for tick in ticks)


def top_depth(levels: dict[int, float], side: int, count: int) -> float:
    ordered = sorted(levels, reverse=side == BID)
    return sum(levels[tick] for tick in ordered[:count])


def depth_state(
    episode: Episode,
    replay: BookReplay,
    sample_us: int,
) -> dict[str, Any] | None:
    best_bid, best_ask = best_ticks(replay)
    exec_tick = executable_tick(episode.root, best_bid, best_ask)
    if exec_tick is None:
        return None
    root = episode.root
    owner = replay.bid_levels if root.owner_book_side == BID else replay.ask_levels
    opponent = replay.ask_levels if root.owner_book_side == BID else replay.bid_levels
    if root.side == "Demand":
        behind_ticks = range(root.lo_tick - FIELD_BEHIND_TICKS, root.lo_tick)
        bridge_ticks = range(root.hi_tick + 1, exec_tick + 1)
        road_ticks = range(exec_tick, exec_tick + ROAD_LEVELS)
        field_ticks = range(
            root.lo_tick - FIELD_BEHIND_TICKS,
            root.hi_tick + PROXIMITY_TICKS + FIELD_BEYOND_TICKS + 1,
        )
    else:
        behind_ticks = range(root.hi_tick + 1, root.hi_tick + FIELD_BEHIND_TICKS + 1)
        bridge_ticks = range(exec_tick, root.lo_tick)
        road_ticks = range(exec_tick - ROAD_LEVELS + 1, exec_tick + 1)
        field_ticks = range(
            root.lo_tick - PROXIMITY_TICKS - FIELD_BEYOND_TICKS,
            root.hi_tick + FIELD_BEHIND_TICKS + 1,
        )
    rail_ticks = range(root.lo_tick, root.hi_tick + 1)
    distance = range_distance(exec_tick, root.lo_tick, root.hi_tick)
    return {
        "sample_et": et_text(sample_us),
        "elapsed_s": round((sample_us - episode.proximity_us) / 1_000_000, 3),
        "executable_tick": exec_tick,
        "executable_price": round(exec_tick * TICK_SIZE, 2),
        "distance_ticks": distance,
        "inside_20_ticks": distance <= PROXIMITY_TICKS,
        "quote_progress_ticks": (exec_tick - episode.proximity_exec_tick)
        * root.favorable_sign,
        "best_bid_tick": best_bid,
        "best_ask_tick": best_ask,
        "owner_top5_depth": round(top_depth(owner, root.owner_book_side, 5), 6),
        "opponent_top5_depth": round(
            top_depth(opponent, -root.owner_book_side, 5), 6
        ),
        "owner_rail_depth": round(range_depth(owner, rail_ticks), 6),
        "opponent_rail_depth": round(range_depth(opponent, rail_ticks), 6),
        "owner_behind_depth": round(range_depth(owner, behind_ticks), 6),
        "opponent_behind_depth": round(range_depth(opponent, behind_ticks), 6),
        "owner_bridge_depth": round(range_depth(owner, bridge_ticks), 6),
        "opponent_bridge_depth": round(range_depth(opponent, bridge_ticks), 6),
        "opponent_road_depth": round(range_depth(opponent, road_ticks), 6),
        "opponent_road_levels": sum(
            1 for tick in road_ticks if opponent.get(tick, 0.0) > 0
        ),
        "owner_field_depth": round(range_depth(owner, field_ticks), 6),
        "opponent_field_depth": round(range_depth(opponent, field_ticks), 6),
    }


def flow_sum(
    bins: dict[int, dict[str, float]],
    end_bin: int,
    seconds: float,
) -> dict[str, float]:
    count = max(1, math.ceil(seconds * 1_000_000 / BUCKET_US))
    output: dict[str, float] = defaultdict(float)
    for index in range(end_bin - count + 1, end_bin + 1):
        for key, value in bins.get(index, {}).items():
            output[key] += value
    return output


def tape_region_metrics(
    episode: Episode,
    times: list[int],
    prices: list[float],
    sizes: list[float],
    signs: list[int],
) -> None:
    lo_us = episode.proximity_us - int(PRE_FLOW_S * 1_000_000)
    hi_us = episode.stop_us
    start = bisect.bisect_left(times, lo_us)
    end = bisect.bisect_right(times, hi_us)
    root = episode.root
    for index in range(start, end):
        sign = int(signs[index])
        if sign not in (-1, 1):
            continue
        tick = round(float(prices[index]) / TICK_SIZE)
        coord = signed_coord(root, tick)
        region = fixed_region(coord)
        role = "opponent" if sign == root.favorable_sign else "owner"
        amount = float(sizes[index])
        bucket = flow_bucket(episode, times[index])
        target = episode.tape_bins[bucket]
        target[f"{role}_consume"] += amount
        target[f"{role}_consume_events"] += 1.0
        if region is not None:
            target[f"{role}_{region}_consume"] += amount
            target[f"{role}_{region}_consume_events"] += 1.0
            target[f"{role}_field_consume"] += amount
            target[f"{role}_field_consume_events"] += 1.0


def enrich_sample_flows(episode: Episode) -> None:
    initial = episode.samples[0] if episode.samples else {}
    initial_owner_under = max(
        (number(initial.get("owner_rail_depth")) or 0.0)
        + (number(initial.get("owner_behind_depth")) or 0.0),
        1.0,
    )
    initial_road = max(number(initial.get("opponent_road_depth")) or 0.0, 1.0)
    initial_owner_field = max(number(initial.get("owner_field_depth")) or 0.0, 1.0)
    for sample in episode.samples:
        end_bin = flow_bucket(episode, to_us(parse_et(episode.root.date, sample["sample_et"])))
        for seconds in FLOW_WINDOWS_S:
            suffix = str(seconds).replace(".", "p") + "s"
            book = flow_sum(episode.book_bins, end_bin, seconds)
            tape = flow_sum(episode.tape_bins, end_bin, seconds)
            for source, values in (("book", book), ("tape", tape)):
                for key, value in values.items():
                    sample[f"{source}_{key}_{suffix}"] = round(value, 6)

            owner_add = book.get("owner_field_add", 0.0)
            owner_remove = book.get("owner_field_remove", 0.0)
            under_add = book.get("owner_under_add", 0.0)
            under_remove = book.get("owner_under_remove", 0.0)
            road_add = book.get("opponent_road_add", 0.0)
            road_remove = book.get("opponent_road_remove", 0.0)
            owner_consume = tape.get("owner_field_consume", 0.0)
            opponent_consume = tape.get("opponent_field_consume", 0.0)
            sample[f"support_net_norm_{suffix}"] = round(
                (owner_add - owner_remove) / initial_owner_field, 6
            )
            sample[f"under_net_norm_{suffix}"] = round(
                (under_add - under_remove) / initial_owner_under, 6
            )
            sample[f"road_clear_norm_{suffix}"] = round(
                (road_remove - road_add) / initial_road, 6
            )
            sample[f"owner_remove_consumed_share_{suffix}"] = round(
                min(owner_consume, owner_remove) / owner_remove
                if owner_remove > 1e-9
                else 0.0,
                6,
            )
            sample[f"road_remove_consumed_share_{suffix}"] = round(
                min(opponent_consume, road_remove) / road_remove
                if road_remove > 1e-9
                else 0.0,
                6,
            )
            sample[f"owner_pull_proxy_{suffix}"] = round(
                max(owner_remove - owner_consume, 0.0), 6
            )
            sample[f"road_pull_proxy_{suffix}"] = round(
                max(road_remove - opponent_consume, 0.0), 6
            )

        sample["owner_under_depth_ratio"] = round(
            (
                (number(sample.get("owner_rail_depth")) or 0.0)
                + (number(sample.get("owner_behind_depth")) or 0.0)
            )
            / initial_owner_under,
            6,
        )
        sample["opponent_road_depth_ratio"] = round(
            (number(sample.get("opponent_road_depth")) or 0.0) / initial_road,
            6,
        )


def state_row_prefix(episode: Episode) -> dict[str, Any]:
    root = episode.root
    return {
        "session_id": root.session_id,
        "date": root.date,
        "root_id": root.root_id,
        "side": root.side,
        "root_lo": round(root.lo_tick * TICK_SIZE, 2),
        "root_hi": round(root.hi_tick * TICK_SIZE, 2),
        "root_owned_et": et_text(root.owned_us),
        "proximity_et": et_text(episode.proximity_us),
        "structural_outcome": episode.structural_outcome,
        "structural_end_et": et_text(episode.structural_end_us),
        "post_proximity_successor_id": episode.successor_id or "",
        "post_proximity_successor_source": episode.successor_source,
        "first_test_verdict": root.first_test_verdict,
    }


def process_day(
    day: str,
    roots: list[Root],
    runtime_by_key: dict[tuple[str, str], RuntimeRail],
    runtime_by_session: dict[str, list[RuntimeRail]],
    symbol_dir: str,
    capture_root: str,
    max_decision_seconds: float,
    batch_files: int,
) -> tuple[list[Episode], list[dict[str, Any]], dict[str, Any]]:
    files = market_recorder_files(symbol_dir, "book_events", datetime.fromisoformat(day).date(), capture_root)
    stats: dict[str, Any] = {
        "date": day,
        "roots": len(roots),
        "book_files": len(files),
        "book_rows": 0,
        "deltas": 0,
        "resets": 0,
        "gaps": 0,
        "episodes": 0,
    }
    if not files:
        return [], [], stats
    day_close_us = to_us(
        datetime.fromisoformat(day).replace(
            hour=16, minute=0, second=0, microsecond=0, tzinfo=NY
        )
    )
    reset_times = (
        pl.scan_parquet(files)
        .filter(
            (pl.col("event_kind") == RESET_BEGIN)
            & (pl.col("receipt_timestamp_us") <= day_close_us)
        )
        .select("receipt_timestamp_us")
        .collect()["receipt_timestamp_us"]
        .to_list()
    )
    if not reset_times:
        rows = [
            {
                "session_id": root.session_id,
                "date": root.date,
                "root_id": root.root_id,
                "side": root.side,
                "capture_status": "excluded",
                "capture_reason": "no_complete_day_reset",
            }
            for root in roots
        ]
        stats["excluded_rows"] = len(rows)
        stats["completed_episode_rows"] = 0
        return [], rows, stats
    earliest_owned = min(root.owned_us for root in roots)
    resets_before = [value for value in reset_times if value <= earliest_owned]
    replay_start_us = (
        max(resets_before)
        if resets_before
        else min(value for value in reset_times if value > earliest_owned)
    )
    stats["replay_start_et"] = et_text(replay_start_us)

    replay = BookReplay()
    offsets = sample_offsets_us(max_decision_seconds)
    roots_by_owned = sorted(roots, key=lambda item: item.owned_us)
    root_index = 0
    pending: dict[tuple[str, str, str], Root] = {}
    pending_by_side: dict[str, set[tuple[str, str, str]]] = {
        "Demand": set(),
        "Supply": set(),
    }
    started: dict[tuple[str, str, str], Episode] = {}
    completed: list[Episode] = []
    root_status: dict[tuple[str, str, str], dict[str, Any]] = {}
    price_index: dict[int, set[tuple[str, str, str]]] = defaultdict(set)
    sample_heap: list[tuple[int, tuple[str, str, str]]] = []
    stop_heap: list[tuple[int, tuple[str, str, str]]] = []
    delta_ring: deque[DeltaRecord] = deque()
    valid_since_us: int | None = None

    def set_root_status(root: Root, status: str, reason: str) -> None:
        root_status[root.key] = {
            "session_id": root.session_id,
            "date": root.date,
            "root_id": root.root_id,
            "side": root.side,
            "root_lo": round(root.lo_tick * TICK_SIZE, 2),
            "root_hi": round(root.hi_tick * TICK_SIZE, 2),
            "root_owned_et": et_text(root.owned_us),
            "original_structural_outcome": root.original_structural_outcome,
            "root_failed_et": et_text(root.failed_us),
            "first_test_verdict": root.first_test_verdict,
            "capture_status": status,
            "capture_reason": reason,
        }

    def unindex_episode(episode: Episode) -> None:
        for tick in episode_tick_range(episode.root):
            keys = price_index.get(tick)
            if keys is None:
                continue
            keys.discard(episode.key)
            if not keys:
                price_index.pop(tick, None)

    def finish_episode(key: tuple[str, str, str], status: str, reason: str) -> None:
        episode = started.pop(key, None)
        if episode is None:
            return
        unindex_episode(episode)
        episode.status = status
        episode.status_reason = reason
        completed.append(episode)

    def emit_sample(episode: Episode, sample_us: int) -> None:
        state = depth_state(episode, replay, sample_us)
        if state is None:
            return
        state.update(state_row_prefix(episode))
        episode.samples.append(state)

    def emit_due_samples(through_us: int) -> None:
        while sample_heap and sample_heap[0][0] <= through_us:
            sample_us, key = heapq.heappop(sample_heap)
            episode = started.get(key)
            if episode is None:
                continue
            expected = (
                episode.proximity_us + episode.offsets_us[episode.sample_index]
                if episode.sample_index < len(episode.offsets_us)
                else None
            )
            if expected != sample_us or sample_us > episode.stop_us:
                continue
            emit_sample(episode, sample_us)
            episode.sample_index += 1
            if episode.sample_index < len(episode.offsets_us):
                next_us = episode.proximity_us + episode.offsets_us[episode.sample_index]
                if next_us <= episode.stop_us:
                    heapq.heappush(sample_heap, (next_us, key))

    def finish_due(through_us: int) -> None:
        while stop_heap and stop_heap[0][0] <= through_us:
            stop_us, key = heapq.heappop(stop_heap)
            episode = started.get(key)
            if episode is None or episode.stop_us != stop_us:
                continue
            reason = (
                "structural_resolution"
                if episode.structural_end_us <= stop_us
                else "decision_horizon"
            )
            finish_episode(key, "complete", reason)

    def abandon_pending(reason: str) -> None:
        for root in list(pending.values()):
            set_root_status(root, "excluded", reason)
        pending.clear()
        pending_by_side["Demand"].clear()
        pending_by_side["Supply"].clear()

    def start_episode(root: Root, ts_us: int, best_bid: int | None, best_ask: int | None) -> None:
        exec_tick = executable_tick(root, best_bid, best_ask)
        if exec_tick is None:
            return
        distance = range_distance(exec_tick, root.lo_tick, root.hi_tick)
        if distance > PROXIMITY_TICKS:
            return
        if valid_since_us is None or ts_us - valid_since_us < int(PRE_FLOW_S * 1_000_000):
            set_root_status(root, "excluded", "insufficient_valid_preflow")
            pending.pop(root.key, None)
            pending_by_side[root.side].discard(root.key)
            return
        resolution = resolve_after_proximity(
            root,
            ts_us,
            runtime_by_key,
            runtime_by_session,
        )
        if resolution is None:
            set_root_status(root, "excluded", "unresolved_after_proximity")
            pending.pop(root.key, None)
            pending_by_side[root.side].discard(root.key)
            return
        structural_outcome, structural_end_us, successor = resolution
        stop_us = min(
            structural_end_us,
            ts_us + int(max_decision_seconds * 1_000_000),
            day_close_us,
        )
        if stop_us <= ts_us:
            set_root_status(root, "excluded", "resolution_before_proximity")
            pending.pop(root.key, None)
            pending_by_side[root.side].discard(root.key)
            return
        episode = Episode(
            root=root,
            proximity_us=ts_us,
            proximity_exec_tick=exec_tick,
            proximity_distance_ticks=distance,
            structural_end_us=structural_end_us,
            structural_outcome=structural_outcome,
            successor_id=successor.band_id if successor is not None else None,
            successor_source=successor.source if successor is not None else "",
            stop_us=stop_us,
            structural_after_horizon=structural_end_us > stop_us,
            offsets_us=offsets,
        )
        started[root.key] = episode
        pending.pop(root.key, None)
        pending_by_side[root.side].discard(root.key)
        for tick in episode_tick_range(root):
            price_index[tick].add(root.key)
        for record in delta_ring:
            if record.ts_us < ts_us - int(PRE_FLOW_S * 1_000_000):
                continue
            add_flow(
                episode,
                episode.book_bins[flow_bucket(episode, record.ts_us)],
                record.side,
                record.tick,
                record.diff,
                record.best_bid,
                record.best_ask,
            )
        heapq.heappush(sample_heap, (ts_us, root.key))
        heapq.heappush(stop_heap, (stop_us, root.key))
        stats["episodes"] += 1

    def activate_roots(ts_us: int) -> list[Root]:
        nonlocal root_index
        activated: list[Root] = []
        while root_index < len(roots_by_owned) and roots_by_owned[root_index].owned_us <= ts_us:
            root = roots_by_owned[root_index]
            root_index += 1
            if root.failed_us is not None and root.failed_us <= ts_us:
                set_root_status(root, "excluded", "resolved_before_observable_activation")
                continue
            if not replay.valid:
                set_root_status(root, "excluded", "book_invalid_at_ownership")
                continue
            pending[root.key] = root
            pending_by_side[root.side].add(root.key)
            activated.append(root)
        return activated

    last_best_bid: int | None = None
    last_best_ask: int | None = None
    for base in range(0, len(files), batch_files):
        frame = (
            pl.scan_parquet(files[base : base + batch_files])
            .select(EVENT_COLUMNS)
            .filter(
                (pl.col("receipt_timestamp_us") >= replay_start_us)
                & (pl.col("receipt_timestamp_us") <= day_close_us)
            )
            .collect()
            .sort(["sequence", "subsequence"])
        )
        stats["book_rows"] += frame.height
        for row in frame.iter_rows():
            ts_us = int(row[C_TS])
            kind = int(row[C_KIND])
            finish_due(ts_us - 1)
            emit_due_samples(ts_us - 1)

            if kind == RESET_BEGIN:
                stats["resets"] += 1
                for key in list(started):
                    finish_episode(key, "excluded", "capture_reset_during_decision")
                abandon_pending("capture_reset_before_proximity")
                delta_ring.clear()
                valid_since_us = None
            elif kind == GAP:
                stats["gaps"] += 1
                for key in list(started):
                    finish_episode(key, "excluded", "capture_gap_during_decision")
                abandon_pending("capture_gap_before_proximity")
                delta_ring.clear()
                valid_since_us = None

            event = {
                "event_kind": kind,
                "side": row[C_SIDE],
                "price_tick": row[C_TICK],
                "size": row[C_SIZE],
                "closed": row[C_CLOSED],
                "quote_id_hash": row[C_QID],
                "reset_epoch": row[C_EPOCH],
                "reset_item_count": row[C_ITEMS],
            }
            if kind != DELTA:
                replay.apply(event)
                if kind == RESET_END and replay.valid:
                    valid_since_us = ts_us
                    last_best_bid, last_best_ask = best_ticks(replay)
                activate_roots(ts_us)
                emit_due_samples(ts_us)
                continue

            stats["deltas"] += 1
            activated = activate_roots(ts_us)
            if not replay.valid:
                replay.apply(event)
                continue

            deltas = decompose_delta(row, replay)
            before_bid, before_ask = best_ticks(replay)
            replay.apply(event)
            after_bid, after_ask = best_ticks(replay)

            check_keys: set[tuple[str, str, str]] = {root.key for root in activated}
            if after_ask != before_ask:
                check_keys.update(pending_by_side["Demand"])
            if after_bid != before_bid:
                check_keys.update(pending_by_side["Supply"])
            for key in tuple(check_keys):
                root = pending.get(key)
                if root is None:
                    continue
                if root.failed_us is not None and root.failed_us <= ts_us:
                    set_root_status(root, "excluded", "resolved_before_proximity")
                    pending.pop(key, None)
                    pending_by_side[root.side].discard(key)
                    continue
                start_episode(root, ts_us, after_bid, after_ask)

            for side, tick, diff in deltas:
                record = DeltaRecord(ts_us, side, tick, diff, after_bid, after_ask)
                for key in tuple(price_index.get(tick, ())):
                    episode = started.get(key)
                    if episode is None or ts_us > episode.stop_us:
                        continue
                    add_flow(
                        episode,
                        episode.book_bins[flow_bucket(episode, ts_us)],
                        side,
                        tick,
                        diff,
                        after_bid,
                        after_ask,
                    )
                delta_ring.append(record)
            cutoff = ts_us - int(PRE_FLOW_S * 1_000_000)
            while delta_ring and delta_ring[0].ts_us < cutoff:
                delta_ring.popleft()

            last_best_bid, last_best_ask = after_bid, after_ask
            emit_due_samples(ts_us)

    final_us = max(
        [episode.stop_us for episode in started.values()]
        + [root.failed_us or 0 for root in pending.values()]
        + [0]
    )
    emit_due_samples(final_us)
    finish_due(final_us)
    for key in list(started):
        finish_episode(key, "complete", "end_of_capture")
    for root in pending.values():
        set_root_status(root, "excluded", "never_entered_20_ticks")
    for root in roots_by_owned[root_index:]:
        set_root_status(root, "excluded", "ownership_after_capture")

    ticks = load_capture_window(
        "ticks",
        symbol_dir,
        datetime.fromisoformat(day).replace(tzinfo=NY),
        datetime.fromisoformat(day).replace(tzinfo=NY) + timedelta(days=1),
        tick_columns(),
    )
    tick_times = ticks["timestamp_us"].to_list()
    tick_prices = ticks["price"].to_list()
    tick_sizes = ticks["size"].to_list()
    tick_signs = ticks["aggressor_sign"].to_list()
    for episode in completed:
        if not episode.samples:
            continue
        tape_region_metrics(
            episode,
            tick_times,
            tick_prices,
            tick_sizes,
            tick_signs,
        )
        enrich_sample_flows(episode)
        set_root_status(episode.root, episode.status, episode.status_reason)
        status = root_status[episode.key]
        status.update(
            {
                "proximity_et": et_text(episode.proximity_us),
                "proximity_delay_s": round(
                    (episode.proximity_us - episode.root.owned_us) / 1_000_000, 3
                ),
                "proximity_exec_price": round(
                    episode.proximity_exec_tick * TICK_SIZE, 2
                ),
                "proximity_distance_ticks": episode.proximity_distance_ticks,
                "decision_stop_et": et_text(episode.stop_us),
                "structural_outcome": episode.structural_outcome,
                "structural_end_et": et_text(episode.structural_end_us),
                "post_proximity_successor_id": episode.successor_id or "",
                "post_proximity_successor_source": episode.successor_source,
                "structural_after_horizon": episode.structural_after_horizon,
                "sample_count": len(episode.samples),
            }
        )

    status_rows = [
        root_status.get(
            root.key,
            {
                "session_id": root.session_id,
                "date": root.date,
                "root_id": root.root_id,
                "side": root.side,
                "capture_status": "excluded",
                "capture_reason": "unclassified",
            },
        )
        for root in roots
    ]
    stats["completed_episode_rows"] = sum(
        row.get("capture_status") == "complete" for row in status_rows
    )
    stats["excluded_rows"] = len(status_rows) - stats["completed_episode_rows"]
    return completed, status_rows, stats


def main() -> None:
    args = parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    roots = load_roots(args.lineage_csv, args.start_date, args.end_date)
    runtime_rails, _, _, _ = load_runtime(
        args.events,
        args.lineage_start_date,
        args.end_date,
    )
    runtime_by_key = {
        (str(rail.session_id), str(rail.band_id)): rail for rail in runtime_rails
    }
    runtime_by_session: dict[str, list[RuntimeRail]] = defaultdict(list)
    for rail in runtime_rails:
        runtime_by_session[str(rail.session_id)].append(rail)
    for group in runtime_by_session.values():
        group.sort(key=lambda rail: rail.owned_utc)
    by_day: dict[str, list[Root]] = defaultdict(list)
    for root in roots:
        by_day[root.date].append(root)

    stats_rows: list[dict[str, Any]] = []
    total_roots = 0
    total_complete = 0
    total_states = 0
    for day in sorted(by_day):
        day_episodes, day_rows, stats = process_day(
            day,
            by_day[day],
            runtime_by_key,
            runtime_by_session,
            args.symbol_dir,
            args.capture_root,
            args.max_decision_seconds,
            args.batch_files,
        )
        stats_rows.append(stats)
        day_dir = args.out_dir / "days" / day
        day_state_rows = [
            sample
            for episode in day_episodes
            if episode.status == "complete"
            for sample in episode.samples
        ]
        write_csv(day_dir / "episode_summary.csv", day_rows)
        write_csv(day_dir / "state_samples.csv", day_state_rows)
        write_csv(day_dir / "capture_stats.csv", [stats])
        total_roots += len(day_rows)
        total_complete += stats["completed_episode_rows"]
        total_states += len(day_state_rows)
        print(
            f"{day}: roots={stats['roots']} book_rows={stats['book_rows']} "
            f"started={stats['episodes']} complete={stats['completed_episode_rows']} "
            f"excluded={stats['excluded_rows']}",
            flush=True,
        )
        del day_episodes, day_rows, day_state_rows
        gc.collect()
    write_csv(args.out_dir / "capture_stats.csv", stats_rows)
    write_csv(
        args.out_dir / "run_summary.csv",
        [
            {
                "start_date": args.start_date,
                "end_date": args.end_date,
                "roots": total_roots,
                "complete": total_complete,
                "states": total_states,
            }
        ],
    )
    print(
        f"wrote {args.out_dir} episodes={total_roots} "
        f"complete={total_complete} states={total_states}"
    )


if __name__ == "__main__":
    main()
