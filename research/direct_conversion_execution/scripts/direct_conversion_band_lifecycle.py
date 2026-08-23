"""Measure the post-formation lifecycle inside a direct-conversion band.

The direct-conversion event says that one local side was consumed. This probe
does not relabel that event. It asks what happened next:

1. Did meaningful two-sided tape continue inside the consumed band?
2. If price breached the adverse edge, could it re-enter the band and then
   reclaim the favorable edge before the root structurally resolved?
3. After a full reclaim and extension, did the favorable edge act as support?
4. Does this phase context explain the weak, day-dependent book signal seen at
   the previously measured escape-return execution event?

All price coordinates are side-normalized. Positive is favorable to the owner,
negative is adverse. Fixed checkpoints are causal: roots that resolved before a
checkpoint are excluded from that checkpoint's feature comparison.
"""

from __future__ import annotations

import argparse
import bisect
import csv
import math
import random
import statistics
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Iterable
from zoneinfo import ZoneInfo

from _paths import OUTPUT_ROOT

from capture_loader import load_capture_window, tick_columns, us  # noqa: E402


NY = ZoneInfo("America/New_York")
TICK_SIZE = 0.25
ADVANCED = "ADVANCED_TO_FAVORABLE_SUCCESSOR"
FAILED = "ROOT_FAILED_FIRST"
CHECKPOINTS_S = (2, 5, 10, 20, 30)
BREACH_DEPTHS = (1, 2, 4)
POST_FAILURE_HORIZONS_S = (30, 60, 120, 300)
EDGE_CLEARANCE_TICKS = 4
APPROACH_POLICY = "cv_escape_return_book_capture_70"
APPROACH_HORIZON_S = 60.0
APPROACH_CHALLENGE_TICKS = 8

DEFAULT_PROXIMITY = (
    OUTPUT_ROOT
    / "direct_conversion_proximity_book_20260717_20260724"
)
DEFAULT_LINEAGE = (
    OUTPUT_ROOT / "direct_conversion_sponsor_lineage" / "lineage.csv"
)
DEFAULT_APPROACH = (
    OUTPUT_ROOT
    / "direct_conversion_competing_passage_20260717_20260724"
    / "policy_decisions.csv"
)
DEFAULT_OUT = (
    OUTPUT_ROOT / "direct_conversion_band_lifecycle_20260717_20260724"
)


@dataclass
class RootEpisode:
    session_id: str
    date: str
    root_id: str
    side: str
    lo_tick: int
    hi_tick: int
    owned_us: int
    proximity_us: int
    structural_end_us: int
    structural_outcome: str
    first_test_verdict: str
    failed_us: int | None
    successor_id: str
    successor_source: str
    successor_us: int | None
    later_successor_id: str
    later_successor_source: str
    later_successor_us: int | None

    @property
    def direction(self) -> int:
        return 1 if self.side == "Demand" else -1

    @property
    def favorable_edge(self) -> int:
        return self.hi_tick if self.direction > 0 else self.lo_tick

    @property
    def adverse_edge(self) -> int:
        return self.lo_tick if self.direction > 0 else self.hi_tick

    @property
    def key(self) -> tuple[str, str, str]:
        return self.session_id, self.date, self.root_id


@dataclass
class DayTape:
    times: list[int]
    ticks: list[int]
    sizes: list[float]
    signs: list[int]

    def indices(self, start_us: int, end_us: int) -> tuple[int, int]:
        return (
            bisect.bisect_left(self.times, start_us),
            bisect.bisect_right(self.times, end_us),
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--proximity-dir", type=Path, default=DEFAULT_PROXIMITY)
    parser.add_argument("--lineage", type=Path, default=DEFAULT_LINEAGE)
    parser.add_argument("--approach-decisions", type=Path, default=DEFAULT_APPROACH)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--symbol-dir", default="NQU6")
    parser.add_argument("--start-date", default="2026-07-17")
    parser.add_argument("--end-date", default="2026-07-24")
    parser.add_argument("--bootstrap-samples", type=int, default=5_000)
    return parser.parse_args()


def parse_et(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%d %H:%M:%S.%f").replace(tzinfo=NY)


def to_us(value: str) -> int:
    return us(parse_et(value))


def et_text(ts_us: int | None) -> str:
    if ts_us is None:
        return ""
    return datetime.fromtimestamp(ts_us / 1_000_000, NY).strftime(
        "%Y-%m-%d %H:%M:%S.%f"
    )[:-3]


def number(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def truth(value: Any) -> bool:
    return str(value).lower() in {"1", "true", "yes"}


def time_window(ts_us: int) -> str:
    ts = datetime.fromtimestamp(ts_us / 1_000_000, NY)
    minute = ts.hour * 60 + ts.minute
    if minute < 690:
        return "09:30-11:30"
    if minute < 810:
        return "11:30-13:30"
    return "13:30-16:00"


def fmt(value: Any, digits: int = 3) -> Any:
    if value is None:
        return ""
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            return ""
        return round(value, digits)
    return value


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    keys: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for key in row:
            if key not in seen:
                seen.add(key)
                keys.append(key)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=keys)
        writer.writeheader()
        writer.writerows(rows)


def lineage_map(path: Path) -> dict[tuple[str, str, str], dict[str, str]]:
    return {
        (row["session_id"], row["date"], row["root_id"]): row
        for row in read_csv(path)
    }


def load_episodes(
    proximity_dir: Path,
    lineage_path: Path,
    start_date: str,
    end_date: str,
) -> list[RootEpisode]:
    lineages = lineage_map(lineage_path)
    output: list[RootEpisode] = []
    days_dir = proximity_dir / "days"
    for day_dir in sorted(days_dir.iterdir()):
        if not day_dir.is_dir() or not (start_date <= day_dir.name <= end_date):
            continue
        path = day_dir / "episode_summary.csv"
        for row in read_csv(path):
            if row.get("capture_status") != "complete":
                continue
            if row.get("structural_outcome") not in {ADVANCED, FAILED}:
                continue
            key = (row["session_id"], row["date"], row["root_id"])
            lineage = lineages.get(key)
            if lineage is None:
                raise ValueError(f"missing lineage row for {key}")
            later_successor_text = lineage.get("favorable_successor_owned_et", "")
            failed_text = row.get("root_failed_et", "")
            successor_text = row.get("structural_end_et", "") if row["structural_outcome"] == ADVANCED else ""
            output.append(
                RootEpisode(
                    session_id=row["session_id"],
                    date=row["date"],
                    root_id=row["root_id"],
                    side=row["side"],
                    lo_tick=round(float(row["root_lo"]) / TICK_SIZE),
                    hi_tick=round(float(row["root_hi"]) / TICK_SIZE),
                    owned_us=to_us(row["root_owned_et"]),
                    proximity_us=to_us(row["proximity_et"]),
                    structural_end_us=to_us(row["structural_end_et"]),
                    structural_outcome=row["structural_outcome"],
                    first_test_verdict=row.get("first_test_verdict", ""),
                    failed_us=to_us(failed_text) if failed_text else None,
                    successor_id=row.get("post_proximity_successor_id", ""),
                    successor_source=row.get("post_proximity_successor_source", ""),
                    successor_us=to_us(successor_text) if successor_text else None,
                    later_successor_id=lineage.get("favorable_successor_id", ""),
                    later_successor_source=lineage.get("favorable_successor_source", ""),
                    later_successor_us=to_us(later_successor_text)
                    if later_successor_text
                    else None,
                )
            )
    return sorted(output, key=lambda row: (row.date, row.owned_us, row.session_id))


def load_day_tape(symbol_dir: str, day: str) -> DayTape:
    date = datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=NY)
    start = date.replace(hour=9, minute=25)
    end = date.replace(hour=16, minute=10)
    frame = load_capture_window(
        "ticks",
        symbol_dir,
        start,
        end,
        tick_columns(),
        inclusive_end=True,
    )
    return DayTape(
        times=[int(value) for value in frame.get_column("timestamp_us").to_list()],
        ticks=[
            round(float(value) / TICK_SIZE)
            for value in frame.get_column("price").to_list()
        ],
        sizes=[float(value) for value in frame.get_column("size").to_list()],
        signs=[
            int(value) for value in frame.get_column("aggressor_sign").to_list()
        ],
    )


def signed_from_edge(root: RootEpisode, tick: int, favorable: bool) -> int:
    edge = root.favorable_edge if favorable else root.adverse_edge
    return root.direction * (tick - edge)


def region(root: RootEpisode, tick: int) -> int:
    if signed_from_edge(root, tick, favorable=True) > 0:
        return 1
    if signed_from_edge(root, tick, favorable=False) < 0:
        return -1
    return 0


def first_index(
    tape: DayTape,
    start_i: int,
    end_i: int,
    predicate: Callable[[int], bool],
) -> int | None:
    for idx in range(start_i, end_i):
        if predicate(tape.ticks[idx]):
            return idx
    return None


def first_breach_index(
    root: RootEpisode,
    tape: DayTape,
    start_i: int,
    end_i: int,
    depth_ticks: int,
) -> int | None:
    return first_index(
        tape,
        start_i,
        end_i,
        lambda tick: signed_from_edge(root, tick, favorable=False) <= -depth_ticks,
    )


def first_reentry_index(
    root: RootEpisode,
    tape: DayTape,
    start_i: int,
    end_i: int,
) -> int | None:
    return first_index(
        tape,
        start_i,
        end_i,
        lambda tick: signed_from_edge(root, tick, favorable=False) >= 0,
    )


def first_reclaim_index(
    root: RootEpisode,
    tape: DayTape,
    start_i: int,
    end_i: int,
) -> int | None:
    return first_index(
        tape,
        start_i,
        end_i,
        lambda tick: signed_from_edge(root, tick, favorable=True) >= 1,
    )


def first_clearance_index(
    root: RootEpisode,
    tape: DayTape,
    start_i: int,
    end_i: int,
    clearance_ticks: int = EDGE_CLEARANCE_TICKS,
) -> int | None:
    return first_index(
        tape,
        start_i,
        end_i,
        lambda tick: signed_from_edge(root, tick, favorable=True)
        >= clearance_ticks,
    )


def band_tape(
    root: RootEpisode,
    tape: DayTape,
    start_i: int,
    end_i: int,
) -> dict[str, Any]:
    favorable_qty = 0.0
    adverse_qty = 0.0
    unknown_qty = 0.0
    trade_count = 0
    favorable_trades = 0
    adverse_trades = 0
    alternations = 0
    last_nonzero: int | None = None
    first_us: int | None = None
    last_us: int | None = None
    for idx in range(start_i, end_i):
        tick = tape.ticks[idx]
        if tick < root.lo_tick or tick > root.hi_tick:
            continue
        trade_count += 1
        first_us = tape.times[idx] if first_us is None else first_us
        last_us = tape.times[idx]
        signed_aggressor = tape.signs[idx] * root.direction
        if signed_aggressor > 0:
            favorable_qty += tape.sizes[idx]
            favorable_trades += 1
            current = 1
        elif signed_aggressor < 0:
            adverse_qty += tape.sizes[idx]
            adverse_trades += 1
            current = -1
        else:
            unknown_qty += tape.sizes[idx]
            continue
        if last_nonzero is not None and current != last_nonzero:
            alternations += 1
        last_nonzero = current
    signed_qty = favorable_qty + adverse_qty
    total_qty = signed_qty + unknown_qty
    min_side_qty = min(favorable_qty, adverse_qty)
    balance = (
        2.0 * min_side_qty / signed_qty if signed_qty > 0 else None
    )
    dwell_span_s = (
        (last_us - first_us) / 1_000_000
        if first_us is not None and last_us is not None
        else 0.0
    )
    return {
        "band_trade_count": trade_count,
        "band_favorable_trade_count": favorable_trades,
        "band_adverse_trade_count": adverse_trades,
        "band_total_qty": total_qty,
        "band_signed_qty": signed_qty,
        "band_favorable_qty": favorable_qty,
        "band_adverse_qty": adverse_qty,
        "band_min_side_qty": min_side_qty,
        "band_balance": balance,
        "band_alternations": alternations,
        "band_dwell_span_s": dwell_span_s,
    }


def prefixed(prefix: str, values: dict[str, Any]) -> dict[str, Any]:
    return {f"{prefix}_{key}": fmt(value) for key, value in values.items()}


def state_before(
    root: RootEpisode,
    tape: DayTape,
    end_us: int,
) -> tuple[str, dict[str, Any]]:
    start_i, end_i = tape.indices(root.owned_us, end_us)
    breach_i = first_breach_index(root, tape, start_i, end_i, 1)
    reentry_i = (
        first_reentry_index(root, tape, breach_i + 1, end_i)
        if breach_i is not None
        else None
    )
    reclaim_i = (
        first_reclaim_index(root, tape, reentry_i + 1, end_i)
        if reentry_i is not None
        else None
    )
    if breach_i is None:
        state = "NO_ADVERSE_BREACH"
    elif reentry_i is None:
        state = "BREACHED_NO_REENTRY"
    elif reclaim_i is None:
        state = "REENTERED_BAND_NO_RECLAIM"
    else:
        state = "FULL_FAVORABLE_RECLAIM"
    metrics = band_tape(root, tape, start_i, end_i)
    metrics.update(
        {
            "state": state,
            "adverse_breach_et": et_text(tape.times[breach_i])
            if breach_i is not None
            else "",
            "band_reentry_et": et_text(tape.times[reentry_i])
            if reentry_i is not None
            else "",
            "favorable_reclaim_et": et_text(tape.times[reclaim_i])
            if reclaim_i is not None
            else "",
        }
    )
    return state, metrics


def edge_support_test(
    root: RootEpisode,
    tape: DayTape,
    reclaim_i: int | None,
    structural_end_i: int,
) -> dict[str, Any]:
    empty = {
        "edge_clearance_et": "",
        "edge_test_et": "",
        "edge_test_resolution": "NO_ELIGIBLE_TEST",
        "edge_test_resolution_et": "",
        "edge_test_penetration_ticks": "",
        "band_test_resolution": "NO_ELIGIBLE_TEST",
        "band_test_resolution_et": "",
    }
    if reclaim_i is None:
        return empty
    clearance_i = first_clearance_index(
        root, tape, reclaim_i, structural_end_i
    )
    if clearance_i is None:
        return empty
    test_i = first_index(
        tape,
        clearance_i + 1,
        structural_end_i,
        lambda tick: signed_from_edge(root, tick, favorable=True) <= 0,
    )
    if test_i is None:
        result = dict(empty)
        result["edge_clearance_et"] = et_text(tape.times[clearance_i])
        result["edge_test_resolution"] = "NO_RETURN"
        result["band_test_resolution"] = "NO_RETURN"
        return result

    adverse_extreme = 0
    resolution = "STRUCTURAL_END"
    resolution_i = structural_end_i - 1
    for idx in range(test_i, structural_end_i):
        favorable_coord = signed_from_edge(root, tape.ticks[idx], favorable=True)
        adverse_extreme = min(adverse_extreme, favorable_coord)
        if favorable_coord >= EDGE_CLEARANCE_TICKS:
            resolution = "READVANCED"
            resolution_i = idx
            break
        if favorable_coord <= -EDGE_CLEARANCE_TICKS:
            resolution = "LOST_FAVORABLE_EDGE"
            resolution_i = idx
            break
    band_resolution = "STRUCTURAL_END"
    band_resolution_i = structural_end_i - 1
    for idx in range(test_i, structural_end_i):
        favorable_coord = signed_from_edge(root, tape.ticks[idx], favorable=True)
        if favorable_coord >= EDGE_CLEARANCE_TICKS:
            band_resolution = "READVANCED"
            band_resolution_i = idx
            break
        if signed_from_edge(root, tape.ticks[idx], favorable=False) <= -1:
            band_resolution = "LOST_ADVERSE_EDGE"
            band_resolution_i = idx
            break
    return {
        "edge_clearance_et": et_text(tape.times[clearance_i]),
        "edge_test_et": et_text(tape.times[test_i]),
        "edge_test_resolution": resolution,
        "edge_test_resolution_et": et_text(tape.times[resolution_i]),
        "edge_test_penetration_ticks": adverse_extreme,
        "band_test_resolution": band_resolution,
        "band_test_resolution_et": et_text(tape.times[band_resolution_i]),
    }


def build_event(root: RootEpisode, tape: DayTape) -> dict[str, Any]:
    start_i, structural_end_i = tape.indices(
        root.owned_us, root.structural_end_us
    )
    if structural_end_i <= start_i:
        raise ValueError(f"no tape inside structural lifecycle for {root.key}")

    breach_indices = {
        depth: first_breach_index(root, tape, start_i, structural_end_i, depth)
        for depth in BREACH_DEPTHS
    }
    breach_i = breach_indices[1]
    reentry_i = (
        first_reentry_index(root, tape, breach_i + 1, structural_end_i)
        if breach_i is not None
        else None
    )
    reclaim_i = (
        first_reclaim_index(root, tape, reentry_i + 1, structural_end_i)
        if reentry_i is not None
        else None
    )
    if breach_i is None:
        path_class = "NO_ADVERSE_BREACH"
    elif reentry_i is None:
        path_class = "BREACHED_NO_REENTRY"
    elif reclaim_i is None:
        path_class = "REENTERED_BAND_NO_RECLAIM"
    else:
        path_class = "FULL_FAVORABLE_RECLAIM"

    result: dict[str, Any] = {
        "session_id": root.session_id,
        "date": root.date,
        "root_id": root.root_id,
        "side": root.side,
        "root_lo": root.lo_tick * TICK_SIZE,
        "root_hi": root.hi_tick * TICK_SIZE,
        "root_width_ticks": root.hi_tick - root.lo_tick + 1,
        "root_owned_et": et_text(root.owned_us),
        "time_window": time_window(root.owned_us),
        "proximity_et": et_text(root.proximity_us),
        "structural_outcome": root.structural_outcome,
        "advanced": root.structural_outcome == ADVANCED,
        "structural_end_et": et_text(root.structural_end_us),
        "lifecycle_s": fmt((root.structural_end_us - root.owned_us) / 1_000_000),
        "first_test_verdict": root.first_test_verdict,
        "root_failed_et": et_text(root.failed_us),
        "successor_id": root.successor_id,
        "successor_source": root.successor_source,
        "later_successor_id": root.later_successor_id,
        "later_successor_source": root.later_successor_source,
        "later_successor_et": et_text(root.later_successor_us),
        "path_class": path_class,
        "band_reentry_et": et_text(tape.times[reentry_i])
        if reentry_i is not None
        else "",
        "full_reclaim_et": et_text(tape.times[reclaim_i])
        if reclaim_i is not None
        else "",
        "breach_to_reentry_s": fmt(
            (tape.times[reentry_i] - tape.times[breach_i]) / 1_000_000
            if breach_i is not None and reentry_i is not None
            else None
        ),
        "breach_to_full_reclaim_s": fmt(
            (tape.times[reclaim_i] - tape.times[breach_i]) / 1_000_000
            if breach_i is not None and reclaim_i is not None
            else None
        ),
    }
    for depth, idx in breach_indices.items():
        result[f"adverse_breach_{depth}t_et"] = (
            et_text(tape.times[idx]) if idx is not None else ""
        )

    result.update(prefixed("whole_lifecycle", band_tape(
        root, tape, start_i, structural_end_i
    )))
    if breach_i is not None:
        pre_breach = band_tape(root, tape, start_i, breach_i)
        adverse_phase_end = (
            reclaim_i
            if reclaim_i is not None
            else structural_end_i
        )
        after_breach = band_tape(
            root, tape, breach_i, adverse_phase_end
        )
        result.update(prefixed("pre_breach", pre_breach))
        result.update(prefixed("breach_to_reclaim_or_end", after_breach))
        if reclaim_i is not None:
            transit_s = (
                tape.times[reclaim_i] - tape.times[breach_i]
            ) / 1_000_000
            min_side_qty = number(
                result.get("breach_to_reclaim_or_end_band_min_side_qty")
            )
            total_qty = number(
                result.get("breach_to_reclaim_or_end_band_total_qty")
            )
            result["breach_reclaim_min_side_qty_per_s"] = fmt(
                min_side_qty / transit_s
                if min_side_qty is not None and transit_s > 0
                else None
            )
            result["breach_reclaim_total_qty_per_s"] = fmt(
                total_qty / transit_s
                if total_qty is not None and transit_s > 0
                else None
            )
            result["breach_reclaim_min_side_qty_per_band_tick"] = fmt(
                min_side_qty / (root.hi_tick - root.lo_tick + 1)
                if min_side_qty is not None
                else None
            )
        else:
            result["breach_reclaim_min_side_qty_per_s"] = ""
            result["breach_reclaim_total_qty_per_s"] = ""
            result["breach_reclaim_min_side_qty_per_band_tick"] = ""
    else:
        result.update(prefixed("pre_breach", band_tape(
            root, tape, start_i, structural_end_i
        )))
        result.update(prefixed("breach_to_reclaim_or_end", band_tape(
            root, tape, start_i, start_i
        )))
        result["breach_reclaim_min_side_qty_per_s"] = ""
        result["breach_reclaim_total_qty_per_s"] = ""
        result["breach_reclaim_min_side_qty_per_band_tick"] = ""

    for checkpoint_s in CHECKPOINTS_S:
        checkpoint_us = root.owned_us + checkpoint_s * 1_000_000
        prefix = f"cp_{checkpoint_s}s"
        live = root.structural_end_us > checkpoint_us
        result[f"{prefix}_eligible"] = live
        if live:
            _, checkpoint_i = tape.indices(root.owned_us, checkpoint_us)
            result.update(prefixed(
                prefix, band_tape(root, tape, start_i, checkpoint_i)
            ))
            state, _ = state_before(root, tape, checkpoint_us)
            result[f"{prefix}_state"] = state
        else:
            for key in band_tape(root, tape, start_i, start_i):
                result[f"{prefix}_{key}"] = ""
            result[f"{prefix}_state"] = "RESOLVED"

    proximity_state, proximity_metrics = state_before(
        root, tape, root.proximity_us
    )
    result["proximity_state"] = proximity_state
    result.update(prefixed("to_proximity", proximity_metrics))
    result.update(edge_support_test(
        root, tape, reclaim_i, structural_end_i
    ))

    if root.structural_outcome == FAILED and root.failed_us is not None:
        fail_i = bisect.bisect_left(tape.times, root.failed_us)
        post_end_us = root.failed_us + max(POST_FAILURE_HORIZONS_S) * 1_000_000
        post_end_i = bisect.bisect_right(tape.times, post_end_us)
        post_reentry_i = first_reentry_index(
            root, tape, fail_i, post_end_i
        )
        post_reclaim_i = first_reclaim_index(
            root,
            tape,
            post_reentry_i if post_reentry_i is not None else fail_i,
            post_end_i,
        )
        result["postfail_band_reentry_et"] = (
            et_text(tape.times[post_reentry_i])
            if post_reentry_i is not None
            else ""
        )
        result["postfail_full_reclaim_et"] = (
            et_text(tape.times[post_reclaim_i])
            if post_reclaim_i is not None
            else ""
        )
        result["postfail_full_reclaim_s"] = fmt(
            (tape.times[post_reclaim_i] - root.failed_us) / 1_000_000
            if post_reclaim_i is not None
            else None
        )
        successor_delay = (
            (root.later_successor_us - root.failed_us) / 1_000_000
            if root.later_successor_us is not None
            and root.later_successor_us > root.failed_us
            else None
        )
        result["postfail_successor_s"] = fmt(successor_delay)
        transit_end_i = (
            post_reclaim_i + 1
            if post_reclaim_i is not None
            and tape.times[post_reclaim_i] <= root.failed_us + 120_000_000
            else bisect.bisect_right(tape.times, root.failed_us + 120_000_000)
        )
        result.update(prefixed(
            "postfail_to_reclaim_or_120s",
            band_tape(root, tape, fail_i, transit_end_i),
        ))
        transit_300_end_i = (
            post_reclaim_i + 1
            if post_reclaim_i is not None
            else bisect.bisect_right(tape.times, root.failed_us + 300_000_000)
        )
        result.update(prefixed(
            "postfail_to_reclaim_or_300s",
            band_tape(root, tape, fail_i, transit_300_end_i),
        ))
        for horizon_s in POST_FAILURE_HORIZONS_S:
            reclaim_within = (
                post_reclaim_i is not None
                and tape.times[post_reclaim_i]
                <= root.failed_us + horizon_s * 1_000_000
            )
            successor_within = (
                successor_delay is not None and successor_delay <= horizon_s
            )
            result[f"postfail_reclaim_{horizon_s}s"] = reclaim_within
            result[f"postfail_reestablished_{horizon_s}s"] = successor_within
        if truth(result["postfail_reestablished_120s"]):
            result["postfail_class_120s"] = "SPONSOR_REESTABLISHED"
        elif truth(result["postfail_reclaim_120s"]):
            result["postfail_class_120s"] = "PRICE_RECLAIM_ONLY"
        else:
            result["postfail_class_120s"] = "NO_FULL_RECLAIM"
        if truth(result["postfail_reestablished_300s"]):
            result["postfail_class_300s"] = "SPONSOR_REESTABLISHED"
        elif truth(result["postfail_reclaim_300s"]):
            result["postfail_class_300s"] = "PRICE_RECLAIM_ONLY"
        else:
            result["postfail_class_300s"] = "NO_FULL_RECLAIM"
    else:
        result["postfail_band_reentry_et"] = ""
        result["postfail_full_reclaim_et"] = ""
        result["postfail_full_reclaim_s"] = ""
        result["postfail_successor_s"] = ""
        for key in band_tape(root, tape, start_i, start_i):
            result[f"postfail_to_reclaim_or_120s_{key}"] = ""
            result[f"postfail_to_reclaim_or_300s_{key}"] = ""
        for horizon_s in POST_FAILURE_HORIZONS_S:
            result[f"postfail_reclaim_{horizon_s}s"] = ""
            result[f"postfail_reestablished_{horizon_s}s"] = ""
        result["postfail_class_120s"] = ""
        result["postfail_class_300s"] = ""
    return result


def median(values: Iterable[float | None]) -> float | None:
    clean = [value for value in values if value is not None and math.isfinite(value)]
    return statistics.median(clean) if clean else None


def auc(positive: list[float], negative: list[float]) -> float | None:
    if not positive or not negative:
        return None
    wins = 0.0
    for pos in positive:
        for neg in negative:
            if pos > neg:
                wins += 1.0
            elif pos == neg:
                wins += 0.5
    return wins / (len(positive) * len(negative))


def outcome_rate(rows: list[dict[str, Any]]) -> float:
    return (
        sum(truth(row.get("advanced")) for row in rows) / len(rows)
        if rows
        else math.nan
    )


def group_summary(
    rows: list[dict[str, Any]],
    field: str,
    *,
    section: str,
) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[str(row.get(field, ""))].append(row)
    output: list[dict[str, Any]] = []
    for value, items in sorted(groups.items(), key=lambda item: (-len(item[1]), item[0])):
        output.append(
            {
                "section": section,
                "field": field,
                "value": value,
                "n": len(items),
                "advanced": sum(truth(row.get("advanced")) for row in items),
                "failed": sum(not truth(row.get("advanced")) for row in items),
                "advance_rate": fmt(outcome_rate(items)),
            }
        )
    return output


def checkpoint_summary(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    metrics = (
        "band_min_side_qty",
        "band_balance",
        "band_alternations",
        "band_total_qty",
        "band_dwell_span_s",
    )
    for checkpoint_s in CHECKPOINTS_S:
        prefix = f"cp_{checkpoint_s}s"
        eligible = [row for row in rows if truth(row.get(f"{prefix}_eligible"))]
        advanced = [row for row in eligible if truth(row["advanced"])]
        failed = [row for row in eligible if not truth(row["advanced"])]
        for metric in metrics:
            key = f"{prefix}_{metric}"
            pos = [
                number(row.get(key))
                for row in failed
                if number(row.get(key)) is not None
            ]
            neg = [
                number(row.get(key))
                for row in advanced
                if number(row.get(key)) is not None
            ]
            output.append(
                {
                    "checkpoint_s": checkpoint_s,
                    "metric": metric,
                    "eligible": len(eligible),
                    "metric_n": len(pos) + len(neg),
                    "advanced_n": len(advanced),
                    "failed_n": len(failed),
                    "advanced_median": fmt(median(neg)),
                    "failed_median": fmt(median(pos)),
                    "auc_toward_failure": fmt(auc(pos, neg)),
                }
            )

        min_values = sorted(
            number(row.get(f"{prefix}_band_min_side_qty"))
            for row in eligible
            if number(row.get(f"{prefix}_band_min_side_qty")) is not None
        )
        if not min_values:
            continue
        for bucket_name, predicate in (
            ("NO_TWO_SIDED_QTY", lambda value: value == 0.0),
            ("TWO_SIDED_QTY", lambda value: value > 0.0),
        ):
            bucket = [
                row
                for row in eligible
                if (
                    number(row.get(f"{prefix}_band_min_side_qty")) is not None
                    and predicate(number(row.get(
                        f"{prefix}_band_min_side_qty"
                    )))
                )
            ]
            output.append(
                {
                    "checkpoint_s": checkpoint_s,
                    "metric": bucket_name,
                    "eligible": len(bucket),
                    "metric_n": len(bucket),
                    "advanced_n": sum(truth(row["advanced"]) for row in bucket),
                    "failed_n": sum(not truth(row["advanced"]) for row in bucket),
                    "advanced_median": "",
                    "failed_median": "",
                    "auc_toward_failure": "",
                    "failure_rate": fmt(
                        1.0 - outcome_rate(bucket) if bucket else None
                    ),
                }
            )
    return output


def checkpoint_context_summary(
    rows: list[dict[str, Any]], checkpoint_s: int = 10
) -> list[dict[str, Any]]:
    prefix = f"cp_{checkpoint_s}s"
    eligible = [row for row in rows if truth(row.get(f"{prefix}_eligible"))]
    output: list[dict[str, Any]] = []
    for field in ("date", "side", "time_window"):
        groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in eligible:
            groups[str(row.get(field, ""))].append(row)
        for value, items in sorted(groups.items()):
            two_sided = [
                row
                for row in items
                if (number(row.get(
                    f"{prefix}_band_min_side_qty"
                )) or 0.0) > 0.0
            ]
            no_two_sided = [row for row in items if row not in two_sided]
            output.append(
                {
                    "checkpoint_s": checkpoint_s,
                    "field": field,
                    "value": value,
                    "n": len(items),
                    "two_sided_n": len(two_sided),
                    "two_sided_share": fmt(
                        len(two_sided) / len(items) if items else None
                    ),
                    "two_sided_failure_rate": fmt(
                        1.0 - outcome_rate(two_sided)
                        if two_sided
                        else None
                    ),
                    "no_two_sided_n": len(no_two_sided),
                    "no_two_sided_failure_rate": fmt(
                        1.0 - outcome_rate(no_two_sided)
                        if no_two_sided
                        else None
                    ),
                    "failure_rate_delta": fmt(
                        (1.0 - outcome_rate(two_sided))
                        - (1.0 - outcome_rate(no_two_sided))
                        if two_sided and no_two_sided
                        else None
                    ),
                }
            )
    return output


def reclaim_support_summary(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    eligible = [
        row
        for row in rows
        if row.get("edge_test_resolution") in {
            "READVANCED",
            "LOST_FAVORABLE_EDGE",
        }
    ]
    held = [
        row for row in eligible if row["edge_test_resolution"] == "READVANCED"
    ]
    lost = [
        row
        for row in eligible
        if row["edge_test_resolution"] == "LOST_FAVORABLE_EDGE"
    ]
    metrics = (
        ("band_min_side_qty", "breach_to_reclaim_or_end_band_min_side_qty"),
        ("band_balance", "breach_to_reclaim_or_end_band_balance"),
        ("band_alternations", "breach_to_reclaim_or_end_band_alternations"),
        ("band_total_qty", "breach_to_reclaim_or_end_band_total_qty"),
        ("band_dwell_span_s", "breach_to_reclaim_or_end_band_dwell_span_s"),
        ("transit_s", "breach_to_full_reclaim_s"),
        ("min_side_qty_per_s", "breach_reclaim_min_side_qty_per_s"),
        ("total_qty_per_s", "breach_reclaim_total_qty_per_s"),
        (
            "min_side_qty_per_band_tick",
            "breach_reclaim_min_side_qty_per_band_tick",
        ),
        ("root_width_ticks", "root_width_ticks"),
    )
    output: list[dict[str, Any]] = []
    for metric, key in metrics:
        held_values = [
            number(row.get(key))
            for row in held
            if number(row.get(key)) is not None
        ]
        lost_values = [
            number(row.get(key))
            for row in lost
            if number(row.get(key)) is not None
        ]
        output.append(
            {
                "section": "metric",
                "metric": metric,
                "n": len(eligible),
                "readvanced": len(held),
                "lost_favorable_edge": len(lost),
                "readvanced_median": fmt(median(held_values)),
                "lost_median": fmt(median(lost_values)),
                "auc_toward_edge_loss": fmt(auc(lost_values, held_values)),
            }
        )

    clean = [
        row
        for row in eligible
        if (number(row.get(
            "breach_to_reclaim_or_end_band_min_side_qty"
        )) or 0.0) == 0.0
    ]
    two_sided = [row for row in eligible if row not in clean]
    for label, items in (("NO_TWO_SIDED_QTY", clean), ("TWO_SIDED_QTY", two_sided)):
        readvanced = sum(
            row["edge_test_resolution"] == "READVANCED" for row in items
        )
        output.append(
            {
                "section": "presence",
                "metric": label,
                "n": len(items),
                "readvanced": readvanced,
                "lost_favorable_edge": len(items) - readvanced,
                "readvance_rate": fmt(
                    readvanced / len(items) if items else None
                ),
            }
        )
    for resolution, items in (
        ("READVANCED", held),
        ("LOST_FAVORABLE_EDGE", lost),
    ):
        advanced = sum(truth(row["advanced"]) for row in items)
        output.append(
            {
                "section": "structural_after_edge",
                "metric": resolution,
                "n": len(items),
                "readvanced": "",
                "lost_favorable_edge": "",
                "structural_advanced": advanced,
                "structural_failed": len(items) - advanced,
                "structural_advance_rate": fmt(
                    advanced / len(items) if items else None
                ),
            }
        )
    for stratum_field in ("date", "side", "time_window"):
        strata: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in eligible:
            strata[str(row.get(stratum_field, ""))].append(row)
        for stratum, items in sorted(strata.items()):
            no_two_sided = [
                row
                for row in items
                if (number(row.get(
                    "breach_to_reclaim_or_end_band_min_side_qty"
                )) or 0.0) == 0.0
            ]
            has_two_sided = [row for row in items if row not in no_two_sided]
            held_no = sum(
                row["edge_test_resolution"] == "READVANCED"
                for row in no_two_sided
            )
            held_yes = sum(
                row["edge_test_resolution"] == "READVANCED"
                for row in has_two_sided
            )
            no_rate = held_no / len(no_two_sided) if no_two_sided else None
            yes_rate = held_yes / len(has_two_sided) if has_two_sided else None
            output.append(
                {
                    "section": "stratum",
                    "metric": stratum_field,
                    "stratum": stratum,
                    "n": len(items),
                    "no_two_sided_n": len(no_two_sided),
                    "no_two_sided_readvance_rate": fmt(no_rate),
                    "two_sided_n": len(has_two_sided),
                    "two_sided_readvance_rate": fmt(yes_rate),
                    "two_sided_rate_delta": fmt(
                        yes_rate - no_rate
                        if yes_rate is not None and no_rate is not None
                        else None
                    ),
                }
            )
    return output


def date_cluster_interval(
    rows: list[dict[str, Any]],
    predicate: Callable[[dict[str, Any]], bool],
    samples: int,
) -> tuple[float | None, float | None, float | None]:
    dates = sorted({row["date"] for row in rows})
    if not dates:
        return None, None, None
    by_date = {
        day: [row for row in rows if row["date"] == day]
        for day in dates
    }
    rng = random.Random(20260726)
    values: list[float] = []
    for _ in range(samples):
        sampled: list[dict[str, Any]] = []
        for _ in dates:
            sampled.extend(by_date[rng.choice(dates)])
        selected = [row for row in sampled if predicate(row)]
        rejected = [row for row in sampled if not predicate(row)]
        if not selected or not rejected:
            continue
        selected_failure = 1.0 - outcome_rate(selected)
        rejected_failure = 1.0 - outcome_rate(rejected)
        values.append(selected_failure - rejected_failure)
    if not values:
        return None, None, None
    values.sort()
    return (
        statistics.median(values),
        values[math.floor(0.025 * (len(values) - 1))],
        values[math.floor(0.975 * (len(values) - 1))],
    )


def date_cluster_success_interval(
    rows: list[dict[str, Any]],
    selected: Callable[[dict[str, Any]], bool],
    success: Callable[[dict[str, Any]], bool],
    samples: int,
) -> tuple[float | None, float | None, float | None]:
    dates = sorted({row["date"] for row in rows})
    by_date = {
        day: [row for row in rows if row["date"] == day]
        for day in dates
    }
    rng = random.Random(20260726)
    values: list[float] = []
    for _ in range(samples):
        sampled: list[dict[str, Any]] = []
        for _ in dates:
            sampled.extend(by_date[rng.choice(dates)])
        yes = [row for row in sampled if selected(row)]
        no = [row for row in sampled if not selected(row)]
        if not yes or not no:
            continue
        yes_rate = sum(success(row) for row in yes) / len(yes)
        no_rate = sum(success(row) for row in no) / len(no)
        values.append(yes_rate - no_rate)
    if not values:
        return None, None, None
    values.sort()
    return (
        statistics.median(values),
        values[math.floor(0.025 * (len(values) - 1))],
        values[math.floor(0.975 * (len(values) - 1))],
    )


def date_cluster_auc_interval(
    rows: list[dict[str, Any]],
    feature: str,
    positive: Callable[[dict[str, Any]], bool],
    samples: int,
) -> tuple[float | None, float | None, float | None]:
    dates = sorted({row["date"] for row in rows})
    by_date = {
        day: [row for row in rows if row["date"] == day]
        for day in dates
    }
    rng = random.Random(20260726)
    values: list[float] = []
    for _ in range(samples):
        sampled: list[dict[str, Any]] = []
        for _ in dates:
            sampled.extend(by_date[rng.choice(dates)])
        pos = [
            number(row.get(feature))
            for row in sampled
            if positive(row) and number(row.get(feature)) is not None
        ]
        neg = [
            number(row.get(feature))
            for row in sampled
            if not positive(row) and number(row.get(feature)) is not None
        ]
        score = auc(pos, neg)
        if score is not None:
            values.append(score)
    if not values:
        return None, None, None
    values.sort()
    return (
        statistics.median(values),
        values[math.floor(0.025 * (len(values) - 1))],
        values[math.floor(0.975 * (len(values) - 1))],
    )


def load_approach_rows(path: Path) -> dict[tuple[str, str, str], dict[str, str]]:
    output: dict[tuple[str, str, str], dict[str, str]] = {}
    for row in read_csv(path):
        if row.get("policy") != APPROACH_POLICY:
            continue
        if number(row.get("horizon_s")) != APPROACH_HORIZON_S:
            continue
        if number(row.get("challenge_ticks")) != APPROACH_CHALLENGE_TICKS:
            continue
        output[(row["session_id"], row["date"], row["root_id"])] = row
    return output


def attach_approach(
    events: list[dict[str, Any]],
    roots: dict[tuple[str, str, str], RootEpisode],
    tapes: dict[str, DayTape],
    approach_rows: dict[tuple[str, str, str], dict[str, str]],
) -> None:
    for event in events:
        key = (event["session_id"], event["date"], event["root_id"])
        approach = approach_rows.get(key)
        if approach is None or not approach.get("retest_et"):
            event["approach_retest_opportunity"] = False
            event["approach_gate_filled"] = ""
            event["approach_retest_et"] = ""
            event["approach_support_net_norm_2s"] = ""
            event["approach_state"] = ""
            continue
        root = roots[key]
        tape = tapes[root.date]
        retest_us = to_us(approach["retest_et"])
        state, metrics = state_before(root, tape, retest_us)
        event["approach_retest_opportunity"] = truth(
            approach.get("retest_opportunity")
        )
        event["approach_gate_filled"] = truth(approach.get("filled"))
        event["approach_retest_et"] = approach["retest_et"]
        event["approach_support_net_norm_2s"] = fmt(
            number(approach.get("retest_support_net_norm_2s"))
        )
        event["approach_state"] = state
        event.update(prefixed("to_approach", metrics))


def attach_edge_book(
    events: list[dict[str, Any]],
    proximity_dir: Path,
) -> None:
    targets: dict[tuple[str, str, str], int] = {
        (row["session_id"], row["date"], row["root_id"]): to_us(
            row["edge_test_et"]
        )
        for row in events
        if row.get("edge_test_resolution") in {
            "READVANCED",
            "LOST_FAVORABLE_EDGE",
        }
        and row.get("edge_test_et")
    }
    best: dict[tuple[str, str, str], dict[str, str]] = {}
    best_us: dict[tuple[str, str, str], int] = {}
    for day in sorted({key[1] for key in targets}):
        path = proximity_dir / "days" / day / "state_samples.csv"
        with path.open("r", encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                key = (row["session_id"], row["date"], row["root_id"])
                target_us = targets.get(key)
                if target_us is None:
                    continue
                sample_us = to_us(row["sample_et"])
                if sample_us > target_us:
                    continue
                if sample_us > best_us.get(key, -1):
                    best[key] = row
                    best_us[key] = sample_us

    fields = (
        "support_net_norm_0p5s",
        "support_net_norm_2p0s",
        "support_net_norm_5p0s",
        "under_net_norm_2p0s",
        "road_clear_norm_2p0s",
        "owner_under_depth_ratio",
        "opponent_road_depth_ratio",
        "owner_top5_depth",
        "opponent_top5_depth",
        "owner_field_depth",
        "opponent_field_depth",
    )
    for event in events:
        key = (event["session_id"], event["date"], event["root_id"])
        sample = best.get(key)
        if sample is None:
            event["edge_book_sample_et"] = ""
            event["edge_book_lag_s"] = ""
            for field in fields:
                event[f"edge_book_{field}"] = ""
            continue
        target_us = targets[key]
        sample_us = best_us[key]
        event["edge_book_sample_et"] = sample["sample_et"]
        event["edge_book_lag_s"] = fmt((target_us - sample_us) / 1_000_000)
        for field in fields:
            event[f"edge_book_{field}"] = fmt(number(sample.get(field)))


def edge_book_summary(
    rows: list[dict[str, Any]], bootstrap_samples: int
) -> list[dict[str, Any]]:
    eligible = [
        row
        for row in rows
        if row.get("edge_test_resolution") in {
            "READVANCED",
            "LOST_FAVORABLE_EDGE",
        }
        and number(row.get("edge_book_lag_s")) is not None
        and number(row.get("edge_book_lag_s")) <= 0.5
    ]
    held = [
        row for row in eligible if row["edge_test_resolution"] == "READVANCED"
    ]
    lost = [
        row
        for row in eligible
        if row["edge_test_resolution"] == "LOST_FAVORABLE_EDGE"
    ]
    fields = (
        "support_net_norm_0p5s",
        "support_net_norm_2p0s",
        "support_net_norm_5p0s",
        "under_net_norm_2p0s",
        "road_clear_norm_2p0s",
        "owner_under_depth_ratio",
        "opponent_road_depth_ratio",
    )
    output: list[dict[str, Any]] = []
    for field in fields:
        key = f"edge_book_{field}"
        held_values = [
            number(row.get(key))
            for row in held
            if number(row.get(key)) is not None
        ]
        lost_values = [
            number(row.get(key))
            for row in lost
            if number(row.get(key)) is not None
        ]
        cluster_med, cluster_lo, cluster_hi = date_cluster_auc_interval(
            eligible,
            key,
            lambda row: row["edge_test_resolution"] == "READVANCED",
            bootstrap_samples,
        )
        output.append(
            {
                "feature": field,
                "eligible": len(eligible),
                "metric_n": len(held_values) + len(lost_values),
                "readvanced_n": len(held_values),
                "edge_lost_n": len(lost_values),
                "readvanced_median": fmt(median(held_values)),
                "edge_lost_median": fmt(median(lost_values)),
                "auc_toward_readvance": fmt(auc(held_values, lost_values)),
                "date_cluster_auc_median": fmt(cluster_med),
                "date_cluster_auc_lo": fmt(cluster_lo),
                "date_cluster_auc_hi": fmt(cluster_hi),
            }
        )
    return output


def quantile(values: list[float], q: float) -> float:
    if not values:
        raise ValueError("quantile requires values")
    ordered = sorted(values)
    position = q * (len(ordered) - 1)
    lo = math.floor(position)
    hi = math.ceil(position)
    if lo == hi:
        return ordered[lo]
    weight = position - lo
    return ordered[lo] * (1.0 - weight) + ordered[hi] * weight


def bootstrap_gate_selectivity(
    rows: list[dict[str, Any]],
    samples: int,
) -> tuple[float | None, float | None, float | None]:
    dates = sorted({row["date"] for row in rows})
    by_date = {
        day: [row for row in rows if row["date"] == day]
        for day in dates
    }
    rng = random.Random(20260726)
    values: list[float] = []
    for _ in range(samples):
        sampled: list[dict[str, Any]] = []
        for _ in dates:
            sampled.extend(by_date[rng.choice(dates)])
        held = [
            row for row in sampled if row["edge_test_resolution"] == "READVANCED"
        ]
        lost = [
            row
            for row in sampled
            if row["edge_test_resolution"] == "LOST_FAVORABLE_EDGE"
        ]
        if not held or not lost:
            continue
        capture = sum(truth(row["selected"]) for row in held) / len(held)
        exposure = sum(truth(row["selected"]) for row in lost) / len(lost)
        values.append(capture - exposure)
    if not values:
        return None, None, None
    values.sort()
    return (
        statistics.median(values),
        values[math.floor(0.025 * (len(values) - 1))],
        values[math.floor(0.975 * (len(values) - 1))],
    )


def bootstrap_gate_structural_selectivity(
    rows: list[dict[str, Any]],
    samples: int,
) -> tuple[float | None, float | None, float | None]:
    dates = sorted({row["date"] for row in rows})
    by_date = {
        day: [row for row in rows if row["date"] == day]
        for day in dates
    }
    rng = random.Random(20260726)
    values: list[float] = []
    for _ in range(samples):
        sampled: list[dict[str, Any]] = []
        for _ in dates:
            sampled.extend(by_date[rng.choice(dates)])
        advanced = [
            row for row in sampled if row["structural_outcome"] == ADVANCED
        ]
        failed = [
            row for row in sampled if row["structural_outcome"] == FAILED
        ]
        if not advanced or not failed:
            continue
        capture = sum(truth(row["selected"]) for row in advanced) / len(advanced)
        exposure = sum(truth(row["selected"]) for row in failed) / len(failed)
        values.append(capture - exposure)
    if not values:
        return None, None, None
    values.sort()
    return (
        statistics.median(values),
        values[math.floor(0.025 * (len(values) - 1))],
        values[math.floor(0.975 * (len(values) - 1))],
    )


def edge_book_cv_policy(
    rows: list[dict[str, Any]],
    bootstrap_samples: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    eligible = [
        row
        for row in rows
        if row.get("edge_test_resolution") in {
            "READVANCED",
            "LOST_FAVORABLE_EDGE",
        }
        and number(row.get("edge_book_lag_s")) is not None
        and number(row.get("edge_book_lag_s")) <= 0.5
    ]
    features = (
        "edge_book_support_net_norm_2p0s",
        "edge_book_support_net_norm_5p0s",
        "edge_book_under_net_norm_2p0s",
        "edge_book_owner_under_depth_ratio",
    )
    dates = sorted({row["date"] for row in eligible})
    decisions: list[dict[str, Any]] = []
    summary: list[dict[str, Any]] = []
    for feature in features:
        feature_decisions: list[dict[str, Any]] = []
        for holdout in dates:
            train_positive = [
                number(row.get(feature))
                for row in eligible
                if row["date"] != holdout
                and row["edge_test_resolution"] == "READVANCED"
                and number(row.get(feature)) is not None
            ]
            if not train_positive:
                continue
            threshold = quantile(train_positive, 0.30)
            for row in eligible:
                if row["date"] != holdout:
                    continue
                value = number(row.get(feature))
                if value is None:
                    continue
                feature_decisions.append(
                    {
                        "feature": feature,
                        "date": row["date"],
                        "session_id": row["session_id"],
                        "root_id": row["root_id"],
                        "side": row["side"],
                        "edge_test_et": row["edge_test_et"],
                        "edge_test_resolution": row["edge_test_resolution"],
                        "structural_outcome": row["structural_outcome"],
                        "feature_value": fmt(value),
                        "heldout_threshold": fmt(threshold),
                        "selected": value >= threshold,
                    }
                )
        decisions.extend(feature_decisions)
        held = [
            row
            for row in feature_decisions
            if row["edge_test_resolution"] == "READVANCED"
        ]
        lost = [
            row
            for row in feature_decisions
            if row["edge_test_resolution"] == "LOST_FAVORABLE_EDGE"
        ]
        capture = (
            sum(truth(row["selected"]) for row in held) / len(held)
            if held
            else None
        )
        exposure = (
            sum(truth(row["selected"]) for row in lost) / len(lost)
            if lost
            else None
        )
        med, lo, hi = bootstrap_gate_selectivity(
            feature_decisions, bootstrap_samples
        )
        structural_advanced = [
            row
            for row in feature_decisions
            if row["structural_outcome"] == ADVANCED
        ]
        structural_failed = [
            row
            for row in feature_decisions
            if row["structural_outcome"] == FAILED
        ]
        structural_capture = (
            sum(truth(row["selected"]) for row in structural_advanced)
            / len(structural_advanced)
            if structural_advanced
            else None
        )
        structural_exposure = (
            sum(truth(row["selected"]) for row in structural_failed)
            / len(structural_failed)
            if structural_failed
            else None
        )
        structural_med, structural_lo, structural_hi = (
            bootstrap_gate_structural_selectivity(
                feature_decisions, bootstrap_samples
            )
        )
        summary.append(
            {
                "feature": feature.removeprefix("edge_book_"),
                "n": len(feature_decisions),
                "readvanced_n": len(held),
                "edge_lost_n": len(lost),
                "readvance_capture": fmt(capture),
                "edge_loss_exposure": fmt(exposure),
                "selectivity": fmt(
                    capture - exposure
                    if capture is not None and exposure is not None
                    else None
                ),
                "date_cluster_median": fmt(med),
                "date_cluster_lo": fmt(lo),
                "date_cluster_hi": fmt(hi),
                "structural_advance_n": len(structural_advanced),
                "structural_failure_n": len(structural_failed),
                "structural_advance_capture": fmt(structural_capture),
                "structural_failure_exposure": fmt(structural_exposure),
                "structural_selectivity": fmt(
                    structural_capture - structural_exposure
                    if structural_capture is not None
                    and structural_exposure is not None
                    else None
                ),
                "structural_date_cluster_median": fmt(structural_med),
                "structural_date_cluster_lo": fmt(structural_lo),
                "structural_date_cluster_hi": fmt(structural_hi),
            }
        )
    return summary, decisions


def approach_summary(
    rows: list[dict[str, Any]], bootstrap_samples: int
) -> list[dict[str, Any]]:
    opportunities = [
        row for row in rows if truth(row.get("approach_retest_opportunity"))
    ]
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in opportunities:
        groups[str(row.get("approach_state", ""))].append(row)
    output: list[dict[str, Any]] = []
    for state, items in sorted(groups.items(), key=lambda item: (-len(item[1]), item[0])):
        advanced = [row for row in items if truth(row["advanced"])]
        failed = [row for row in items if not truth(row["advanced"])]
        advanced_support = [
            number(row.get("approach_support_net_norm_2s"))
            for row in advanced
            if number(row.get("approach_support_net_norm_2s")) is not None
        ]
        failed_support = [
            number(row.get("approach_support_net_norm_2s"))
            for row in failed
            if number(row.get("approach_support_net_norm_2s")) is not None
        ]
        filled = [row for row in items if truth(row.get("approach_gate_filled"))]
        not_filled = [
            row for row in items if not truth(row.get("approach_gate_filled"))
        ]
        cluster_med, cluster_lo, cluster_hi = date_cluster_success_interval(
            items,
            lambda row: truth(row.get("approach_gate_filled")),
            lambda row: truth(row.get("advanced")),
            bootstrap_samples,
        )
        output.append(
            {
                "approach_state": state,
                "n": len(items),
                "advanced": len(advanced),
                "failed": len(failed),
                "advance_rate": fmt(outcome_rate(items)),
                "support_auc_toward_advance": fmt(
                    auc(advanced_support, failed_support)
                ),
                "advanced_support_median": fmt(median(advanced_support)),
                "failed_support_median": fmt(median(failed_support)),
                "gate_filled_n": len(filled),
                "gate_filled_advance_rate": fmt(
                    outcome_rate(filled) if filled else None
                ),
                "gate_rejected_n": len(not_filled),
                "gate_rejected_advance_rate": fmt(
                    outcome_rate(not_filled) if not_filled else None
                ),
                "gate_selectivity": fmt(
                    outcome_rate(filled) - outcome_rate(not_filled)
                    if filled and not_filled
                    else None
                ),
                "gate_date_cluster_median": fmt(cluster_med),
                "gate_date_cluster_lo": fmt(cluster_lo),
                "gate_date_cluster_hi": fmt(cluster_hi),
            }
        )
    return output


def failure_repair_summary(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    failed = [row for row in rows if not truth(row["advanced"])]
    output: list[dict[str, Any]] = []
    for horizon_s in (120, 300):
        output.extend(group_summary(
            failed,
            f"postfail_class_{horizon_s}s",
            section=f"postfail_class_{horizon_s}s",
        ))
    for horizon_s in POST_FAILURE_HORIZONS_S:
        reclaim = [
            row for row in failed if truth(row.get(f"postfail_reclaim_{horizon_s}s"))
        ]
        rebuilt = [
            row
            for row in failed
            if truth(row.get(f"postfail_reestablished_{horizon_s}s"))
        ]
        output.append(
            {
                "section": "postfail_horizon",
                "field": f"{horizon_s}s",
                "value": "full_reclaim",
                "n": len(reclaim),
                "advanced": "",
                "failed": len(failed) - len(reclaim),
                "advance_rate": fmt(len(reclaim) / len(failed)),
            }
        )
        output.append(
            {
                "section": "postfail_horizon",
                "field": f"{horizon_s}s",
                "value": "sponsor_reestablished",
                "n": len(rebuilt),
                "advanced": "",
                "failed": len(failed) - len(rebuilt),
                "advance_rate": fmt(len(rebuilt) / len(failed)),
            }
        )

    for horizon_s in (120, 300):
        classes: dict[str, list[dict[str, Any]]] = defaultdict(list)
        class_key = f"postfail_class_{horizon_s}s"
        prefix = f"postfail_to_reclaim_or_{horizon_s}s"
        for row in failed:
            classes[str(row.get(class_key, ""))].append(row)
        for label, items in classes.items():
            output.append(
                {
                    "section": f"postfail_transit_tape_{horizon_s}s",
                    "field": class_key,
                    "value": label,
                    "n": len(items),
                    "advanced": "",
                    "failed": "",
                    "advance_rate": "",
                    "median_min_side_qty": fmt(median(
                        number(row.get(f"{prefix}_band_min_side_qty"))
                        for row in items
                    )),
                    "median_balance": fmt(median(
                        number(row.get(f"{prefix}_band_balance"))
                        for row in items
                    )),
                    "median_alternations": fmt(median(
                        number(row.get(f"{prefix}_band_alternations"))
                        for row in items
                    )),
                    "median_dwell_span_s": fmt(median(
                        number(row.get(f"{prefix}_band_dwell_span_s"))
                        for row in items
                    )),
                }
            )
    return output


def select_counterexamples(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []

    def add(bucket: str, items: list[dict[str, Any]], limit: int = 8) -> None:
        for row in items[:limit]:
            output.append(
                {
                    "review_bucket": bucket,
                    "date": row["date"],
                    "root_id": row["root_id"],
                    "side": row["side"],
                    "root_lo": row["root_lo"],
                    "root_hi": row["root_hi"],
                    "root_owned_et": row["root_owned_et"],
                    "structural_outcome": row["structural_outcome"],
                    "structural_end_et": row["structural_end_et"],
                    "path_class": row["path_class"],
                    "cp_10s_min_side_qty": row.get(
                        "cp_10s_band_min_side_qty", ""
                    ),
                    "cp_10s_balance": row.get("cp_10s_band_balance", ""),
                    "cp_10s_alternations": row.get(
                        "cp_10s_band_alternations", ""
                    ),
                    "band_reentry_et": row.get("band_reentry_et", ""),
                    "full_reclaim_et": row.get("full_reclaim_et", ""),
                    "edge_test_resolution": row.get(
                        "edge_test_resolution", ""
                    ),
                    "breach_reclaim_min_side_qty": row.get(
                        "breach_to_reclaim_or_end_band_min_side_qty", ""
                    ),
                    "breach_reclaim_balance": row.get(
                        "breach_to_reclaim_or_end_band_balance", ""
                    ),
                    "postfail_class_120s": row.get(
                        "postfail_class_120s", ""
                    ),
                    "postfail_class_300s": row.get(
                        "postfail_class_300s", ""
                    ),
                    "later_successor_et": row.get("later_successor_et", ""),
                    "approach_retest_et": row.get("approach_retest_et", ""),
                    "approach_state": row.get("approach_state", ""),
                    "approach_gate_filled": row.get(
                        "approach_gate_filled", ""
                    ),
                    "approach_support_net_norm_2s": row.get(
                        "approach_support_net_norm_2s", ""
                    ),
                }
            )

    eligible_10s = [
        row for row in rows if truth(row.get("cp_10s_eligible"))
    ]
    advanced_churn = sorted(
        [row for row in eligible_10s if truth(row["advanced"])],
        key=lambda row: number(row.get("cp_10s_band_min_side_qty")) or 0.0,
        reverse=True,
    )
    failed_clean = sorted(
        [row for row in eligible_10s if not truth(row["advanced"])],
        key=lambda row: number(row.get("cp_10s_band_min_side_qty")) or 0.0,
    )
    add("HIGH_EARLY_TWO_SIDED_BUT_ADVANCED", advanced_churn)
    add("LOW_EARLY_TWO_SIDED_BUT_FAILED", failed_clean)
    add(
        "FULL_RECLAIM_BUT_ROOT_FAILED",
        [
            row
            for row in rows
            if row["path_class"] == "FULL_FAVORABLE_RECLAIM"
            and not truth(row["advanced"])
        ],
    )
    add(
        "REENTERED_NO_RECLAIM_BUT_ADVANCED",
        [
            row
            for row in rows
            if row["path_class"] == "REENTERED_BAND_NO_RECLAIM"
            and truth(row["advanced"])
        ],
    )
    add(
        "FAILED_THEN_SPONSOR_REESTABLISHED_120S",
        [
            row
            for row in rows
            if row.get("postfail_class_120s") == "SPONSOR_REESTABLISHED"
        ],
    )
    add(
        "CLEAN_RECLAIM_THEN_EDGE_LOSS",
        sorted(
            [
                row
                for row in rows
                if row.get("edge_test_resolution") == "LOST_FAVORABLE_EDGE"
            ],
            key=lambda row: number(row.get(
                "breach_to_reclaim_or_end_band_min_side_qty"
            )) or 0.0,
        ),
    )
    add(
        "TWO_SIDED_RECLAIM_THEN_READVANCE",
        sorted(
            [
                row
                for row in rows
                if row.get("edge_test_resolution") == "READVANCED"
            ],
            key=lambda row: number(row.get(
                "breach_to_reclaim_or_end_band_min_side_qty"
            )) or 0.0,
            reverse=True,
        ),
    )
    return output


def markdown_table(
    rows: list[dict[str, Any]],
    columns: list[tuple[str, str]],
) -> list[str]:
    headers = [label for _, label in columns]
    output = [
        "| " + " | ".join(headers) + " |",
        "|" + "|".join("---" for _ in headers) + "|",
    ]
    for row in rows:
        output.append(
            "| "
            + " | ".join(str(row.get(key, "")) for key, _ in columns)
            + " |"
        )
    return output


def write_findings(
    path: Path,
    events: list[dict[str, Any]],
    checkpoints: list[dict[str, Any]],
    checkpoint_context: list[dict[str, Any]],
    paths: list[dict[str, Any]],
    reclaim_support: list[dict[str, Any]],
    edge_book: list[dict[str, Any]],
    edge_book_policy: list[dict[str, Any]],
    repairs: list[dict[str, Any]],
    approaches: list[dict[str, Any]],
    bootstrap_samples: int,
) -> None:
    advanced = [row for row in events if truth(row["advanced"])]
    failed = [row for row in events if not truth(row["advanced"])]
    cp10_auc = next(
        (
            row
            for row in checkpoints
            if row["checkpoint_s"] == 10
            and row["metric"] == "band_min_side_qty"
        ),
        {},
    )
    cp10_eligible = [
        row for row in events if truth(row.get("cp_10s_eligible"))
    ]
    heavy_predicate = lambda row: (
        (number(row.get("cp_10s_band_min_side_qty")) or 0.0) > 0.0
    )
    heavy_selected = [row for row in cp10_eligible if heavy_predicate(row)]
    heavy_rejected = [row for row in cp10_eligible if not heavy_predicate(row)]
    cluster_med, cluster_lo, cluster_hi = date_cluster_interval(
        cp10_eligible, heavy_predicate, bootstrap_samples
    )
    edge_tests = [
        row
        for row in events
        if row.get("edge_test_resolution") not in {
            "",
            "NO_ELIGIBLE_TEST",
            "NO_RETURN",
        }
    ]
    edge_counts = Counter(row["edge_test_resolution"] for row in edge_tests)
    edge_cluster_med, edge_cluster_lo, edge_cluster_hi = (
        date_cluster_success_interval(
            [
                row
                for row in edge_tests
                if row["edge_test_resolution"] in {
                    "READVANCED",
                    "LOST_FAVORABLE_EDGE",
                }
            ],
            lambda row: (
                number(row.get(
                    "breach_to_reclaim_or_end_band_min_side_qty"
                )) or 0.0
            ) > 0.0,
            lambda row: row["edge_test_resolution"] == "READVANCED",
            bootstrap_samples,
        )
    )
    postfail = [row for row in events if not truth(row["advanced"])]
    postfail_counts = Counter(row["postfail_class_120s"] for row in postfail)
    postfail_300_counts = Counter(
        row["postfail_class_300s"] for row in postfail
    )

    lines = [
        "# Direct Conversion Band Lifecycle",
        "",
        "This is a tape and lineage research pass. It does not change EAR or LevelLedger.",
        "",
        "## Population",
        "",
        f"- Complete roots: {len(events)}; advanced={len(advanced)}; root failed first={len(failed)}.",
        "- Two-sided business is measured from aggressor tape inside the exact consumed band. "
        "`min_side_qty=min(favorable_qty, adverse_qty)` requires both sides to trade; "
        "`balance=2*min_side_qty/(favorable_qty+adverse_qty)` measures equivalence.",
        "- Fixed checkpoints exclude roots that had already structurally resolved.",
        "",
        "## Fixed-Checkpoint Test",
        "",
        "Larger AUC means more of the named metric was present in roots that later failed.",
        "",
    ]
    metric_rows = [
        row
        for row in checkpoints
        if row["metric"] in {
            "band_min_side_qty",
            "band_balance",
            "band_alternations",
        }
    ]
    lines.extend(markdown_table(
        metric_rows,
        [
            ("checkpoint_s", "checkpoint"),
            ("metric", "metric"),
            ("eligible", "eligible"),
            ("metric_n", "metric n"),
            ("advanced_median", "advanced median"),
            ("failed_median", "failed median"),
            ("auc_toward_failure", "AUC to failure"),
        ],
    ))
    lines.extend([
        "",
        f"- At 10 seconds, min-side quantity AUC toward failure was "
        f"{cp10_auc.get('auc_toward_failure', '')}.",
        f"- Any nonzero two-sided quantity by 10 seconds: "
        f"n={len(heavy_selected)}, failure rate="
        f"{fmt(1.0 - outcome_rate(heavy_selected) if heavy_selected else None)} versus "
        f"{fmt(1.0 - outcome_rate(heavy_rejected) if heavy_rejected else None)} outside it.",
        f"- Date-cluster bootstrap difference in failure rate for that descriptive split: "
        f"median={fmt(cluster_med)}, 95%={fmt(cluster_lo)} to {fmt(cluster_hi)}.",
        "",
        "Ten-second two-sided presence by session window:",
        "",
    ])
    lines.extend(markdown_table(
        [
            row
            for row in checkpoint_context
            if row["field"] == "time_window"
        ],
        [
            ("value", "window"),
            ("n", "n"),
            ("two_sided_n", "two-sided n"),
            ("two_sided_failure_rate", "two-sided failure"),
            ("no_two_sided_failure_rate", "no-two-sided failure"),
            ("failure_rate_delta", "difference"),
        ],
    ))
    lines.extend([
        "",
        "## Adverse Traversal And Reclaim",
        "",
    ])
    lines.extend(markdown_table(
        paths,
        [
            ("value", "path before structural resolution"),
            ("n", "n"),
            ("advanced", "advanced"),
            ("failed", "failed"),
            ("advance_rate", "advance rate"),
        ],
    ))
    lines.extend([
        "",
        f"- Eligible post-reclaim edge tests: {len(edge_tests)}; "
        f"readvanced={edge_counts['READVANCED']}, "
        f"lost favorable-edge support={edge_counts['LOST_FAVORABLE_EDGE']}, "
        f"structural endpoint first={edge_counts['STRUCTURAL_END']}.",
        "",
        "Two-sided tape during the adverse-breach to full-reclaim traversal:",
        "",
    ])
    reclaim_metrics = [
        row for row in reclaim_support if row["section"] == "metric"
    ]
    lines.extend(markdown_table(
        reclaim_metrics,
        [
            ("metric", "transit metric"),
            ("n", "n"),
            ("readvanced_median", "readvanced median"),
            ("lost_median", "edge-loss median"),
            ("auc_toward_edge_loss", "AUC to edge loss"),
        ],
    ))
    reclaim_presence = [
        row for row in reclaim_support if row["section"] == "presence"
    ]
    lines.extend([
        "",
    ])
    lines.extend(markdown_table(
        reclaim_presence,
        [
            ("metric", "transit class"),
            ("n", "n"),
            ("readvanced", "readvanced"),
            ("lost_favorable_edge", "lost edge"),
            ("readvance_rate", "readvance rate"),
        ],
    ))
    structural_after_edge = [
        row
        for row in reclaim_support
        if row["section"] == "structural_after_edge"
    ]
    lines.extend([
        "",
        "Local edge-test resolution versus eventual sponsor-lineage outcome:",
        "",
    ])
    lines.extend(markdown_table(
        structural_after_edge,
        [
            ("metric", "edge-test resolution"),
            ("n", "n"),
            ("structural_advanced", "eventually advanced"),
            ("structural_failed", "eventually failed"),
            ("structural_advance_rate", "advance rate"),
        ],
    ))
    lines.extend([
        "",
        f"- Date-cluster bootstrap readvance-rate difference for two-sided versus "
        f"zero-min-side reclaim transit: median={fmt(edge_cluster_med)}, "
        f"95%={fmt(edge_cluster_lo)} to {fmt(edge_cluster_hi)}.",
        "",
        "- Reclaim is state evidence, but it is not an entry-time predictor when it occurs "
        "after the original proximity decision. Its natural use is campaign keep, rearm, "
        "or promotion.",
        "",
        "Book state sampled causally at the actual favorable-edge test:",
        "",
    ])
    lines.extend(markdown_table(
        edge_book,
        [
            ("feature", "feature"),
            ("metric_n", "n"),
            ("readvanced_median", "readvanced median"),
            ("edge_lost_median", "edge-loss median"),
            ("auc_toward_readvance", "AUC to readvance"),
            ("date_cluster_auc_lo", "cluster 2.5%"),
            ("date_cluster_auc_hi", "cluster 97.5%"),
        ],
    ))
    lines.extend([
        "",
        "Leave-one-date-out gates target 70% readvance capture in the five training dates:",
        "",
    ])
    lines.extend(markdown_table(
        edge_book_policy,
        [
            ("feature", "feature"),
            ("n", "n"),
            ("readvance_capture", "readvance capture"),
            ("edge_loss_exposure", "edge-loss exposure"),
            ("selectivity", "selectivity"),
            ("date_cluster_lo", "cluster 2.5%"),
            ("date_cluster_hi", "cluster 97.5%"),
        ],
    ))
    lines.extend([
        "",
        "The same held-out decisions against eventual sponsor-lineage outcome:",
        "",
    ])
    lines.extend(markdown_table(
        edge_book_policy,
        [
            ("feature", "feature"),
            ("structural_advance_capture", "advance capture"),
            ("structural_failure_exposure", "failure exposure"),
            ("structural_selectivity", "selectivity"),
            ("structural_date_cluster_lo", "cluster 2.5%"),
            ("structural_date_cluster_hi", "cluster 97.5%"),
        ],
    ))
    lines.extend([
        "",
        "## Strict Failure Versus Repair-Like Rebuild",
        "",
        f"- Within 120 seconds after strict root failure: "
        f"sponsor re-established={postfail_counts['SPONSOR_REESTABLISHED']}, "
        f"price reclaimed without recorded sponsor={postfail_counts['PRICE_RECLAIM_ONLY']}, "
        f"no full reclaim={postfail_counts['NO_FULL_RECLAIM']}.",
        f"- Within 300 seconds: sponsor re-established="
        f"{postfail_300_counts['SPONSOR_REESTABLISHED']}, "
        f"price reclaim only={postfail_300_counts['PRICE_RECLAIM_ONLY']}, "
        f"no full reclaim={postfail_300_counts['NO_FULL_RECLAIM']}.",
        "",
    ])
    transit_rows = [
        row
        for row in repairs
        if row["section"] == "postfail_transit_tape_120s"
    ]
    lines.extend(markdown_table(
        transit_rows,
        [
            ("value", "post-failure class"),
            ("n", "n"),
            ("median_min_side_qty", "median min-side qty"),
            ("median_balance", "median balance"),
            ("median_alternations", "median alternations"),
            ("median_dwell_span_s", "median dwell span"),
        ],
    ))
    lines.extend([
        "",
        "## Tie To Escape-Return Book Claim",
        "",
        "The prior 2-second owner-support measurement is now stratified by the band "
        "lifecycle already observed when the escape-return event occurred.",
        "",
    ])
    lines.extend(markdown_table(
        approaches,
        [
            ("approach_state", "state at escape-return"),
            ("n", "n"),
            ("advance_rate", "advance rate"),
            ("support_auc_toward_advance", "support AUC"),
            ("gate_filled_n", "gate fills"),
            ("gate_filled_advance_rate", "filled advance"),
            ("gate_rejected_advance_rate", "rejected advance"),
            ("gate_selectivity", "gate selectivity"),
            ("gate_date_cluster_lo", "cluster 2.5%"),
            ("gate_date_cluster_hi", "cluster 97.5%"),
        ],
    ))
    lines.extend([
        "",
        "## Interpretation",
        "",
        "- The fixed checkpoints answer whether early continued two-sided business has "
        "predictive content without giving longer-lived roots extra observation time.",
        "- The path categories are state diagnostics, not independent predictors: LL root "
        "failure itself requires adverse acceptance, so inability to reclaim before the "
        "failure declaration is partly the mechanism being measured.",
        "- A strict failure followed by favorable successor ownership is called "
        "repair-like re-establishment, not a false failure. The original sponsor still "
        "failed and EAR's risk exit can remain correct.",
        "- Thresholds and presence splits in this report are descriptive. No runtime heuristic "
        "is promoted from six dates.",
    ])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    args = parse_args()
    roots = load_episodes(
        args.proximity_dir,
        args.lineage,
        args.start_date,
        args.end_date,
    )
    dates = sorted({root.date for root in roots})
    tapes = {
        day: load_day_tape(args.symbol_dir, day)
        for day in dates
    }
    events = [build_event(root, tapes[root.date]) for root in roots]
    root_map = {root.key: root for root in roots}
    attach_approach(
        events,
        root_map,
        tapes,
        load_approach_rows(args.approach_decisions),
    )
    attach_edge_book(events, args.proximity_dir)

    checkpoints = checkpoint_summary(events)
    checkpoint_context = checkpoint_context_summary(events)
    paths = group_summary(events, "path_class", section="structural_path")
    reclaim_support = reclaim_support_summary(events)
    edge_book = edge_book_summary(events, args.bootstrap_samples)
    edge_book_policy, edge_book_decisions = edge_book_cv_policy(
        events, args.bootstrap_samples
    )
    repairs = failure_repair_summary(events)
    approaches = approach_summary(events, args.bootstrap_samples)
    counterexamples = select_counterexamples(events)

    write_csv(args.out_dir / "events.csv", events)
    write_csv(args.out_dir / "checkpoint_summary.csv", checkpoints)
    write_csv(
        args.out_dir / "checkpoint_context_summary.csv",
        checkpoint_context,
    )
    write_csv(args.out_dir / "path_summary.csv", paths)
    write_csv(args.out_dir / "reclaim_support_summary.csv", reclaim_support)
    write_csv(args.out_dir / "edge_book_summary.csv", edge_book)
    write_csv(
        args.out_dir / "edge_book_policy_summary.csv",
        edge_book_policy,
    )
    write_csv(
        args.out_dir / "edge_book_policy_decisions.csv",
        edge_book_decisions,
    )
    write_csv(args.out_dir / "failure_repair_summary.csv", repairs)
    write_csv(args.out_dir / "approach_context_summary.csv", approaches)
    write_csv(args.out_dir / "counterexamples.csv", counterexamples)
    write_findings(
        args.out_dir / "findings.md",
        events,
        checkpoints,
        checkpoint_context,
        paths,
        reclaim_support,
        edge_book,
        edge_book_policy,
        repairs,
        approaches,
        args.bootstrap_samples,
    )
    print(
        f"wrote {args.out_dir} events={len(events)} "
        f"advanced={sum(truth(row['advanced']) for row in events)} "
        f"failed={sum(not truth(row['advanced']) for row in events)}"
    )


if __name__ == "__main__":
    main()
