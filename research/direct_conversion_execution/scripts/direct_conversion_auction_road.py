"""Measure whether normal auction establishes beyond a direct conversion.

The conversion itself proves only that one local ownership band was consumed.
This probe asks the next question at fixed prices:

1. Did favorable aggression transact through newly available opposing liquidity?
2. Did same-side passive liquidity form behind that trade?
3. On the first meaningful return, was that backing retained/replenished or
   erased before price could readvance?

The lifecycle is deliberately split into BUILD and RETURN phases. BUILD metrics
are knowable when the first return begins and can inform entry quality. RETURN
metrics are later evidence for keep/exit. Outcomes remain sponsor-lineage
outcomes, not fixed-horizon P&L.
"""

from __future__ import annotations

import argparse
import bisect
import csv
import math
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from statistics import median
from typing import Any
from zoneinfo import ZoneInfo

import polars as pl

from _paths import OUTPUT_ROOT, REPO_ROOT as ROOT

sys.path.insert(0, str(ROOT / "MarketRecorder" / "research"))

from capture_loader import load_capture_window, market_recorder_files, tick_columns  # noqa: E402
from conversion_provision_probe import (  # noqa: E402
    ASK,
    BID,
    C_CLOSED,
    C_EPOCH,
    C_ITEMS,
    C_KIND,
    C_QID,
    C_SIDE,
    C_SIZE,
    C_TICK,
    C_TS,
    DELTA,
    EVENT_COLUMNS,
    Conversion,
    price_to_tick,
    resolve_attack_window,
    to_us,
)
from validate_book_events import BookReplay  # noqa: E402

NY = ZoneInfo("America/New_York")
UTC = ZoneInfo("UTC")
TICK_SIZE = 0.25

DEFAULT_LINEAGE = OUTPUT_ROOT / "direct_conversion_sponsor_lineage" / "lineage.csv"
DEFAULT_START = "2026-07-23"
DEFAULT_END = "2026-07-24"
CHECKPOINT_MS = (500, 1_000, 2_000, 5_000)


def parse_et(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%d %H:%M:%S.%f").replace(tzinfo=NY)


def et_text(ts_us: int | None) -> str:
    if ts_us is None:
        return ""
    return datetime.fromtimestamp(ts_us / 1_000_000, UTC).astimezone(NY).strftime(
        "%Y-%m-%d %H:%M:%S.%f"
    )[:-3]


def fnum(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def in_date_range(day: str, start: str, end: str) -> bool:
    return start <= day <= end


@dataclass
class LevelFlow:
    tick: int
    first_favorable_trade_us: int | None = None
    favorable_trade_qty: float = 0.0
    adverse_trade_qty: float = 0.0
    seed_winner: float = math.nan
    seed_loser: float = math.nan
    winner_at_passage: float = math.nan
    loser_at_passage: float = math.nan
    end_winner: float = math.nan
    end_loser: float = math.nan
    max_winner: float = 0.0
    max_loser: float = 0.0
    max_winner_after_passage: float = 0.0
    winner_adds: float = 0.0
    winner_removes: float = 0.0
    loser_adds: float = 0.0
    loser_removes: float = 0.0
    winner_adds_after_passage: float = 0.0
    passage_sampled: bool = False

    def sample(
        self,
        winner_size: float,
        loser_size: float,
        ts_us: int,
        *,
        opening: bool = False,
    ) -> None:
        if opening:
            self.seed_winner = winner_size
            self.seed_loser = loser_size
        self.end_winner = winner_size
        self.end_loser = loser_size
        self.max_winner = max(self.max_winner, winner_size)
        self.max_loser = max(self.max_loser, loser_size)
        if (
            self.first_favorable_trade_us is not None
            and ts_us >= self.first_favorable_trade_us
        ):
            self.max_winner_after_passage = max(
                self.max_winner_after_passage, winner_size
            )

    def sample_passage(self, winner_size: float, loser_size: float) -> None:
        self.winner_at_passage = winner_size
        self.loser_at_passage = loser_size
        self.passage_sampled = True
        self.max_winner_after_passage = max(
            self.max_winner_after_passage, winner_size
        )

    def observe(self, side: int, delta: float, winner_side: int, ts_us: int) -> None:
        if side == winner_side:
            if delta > 0:
                self.winner_adds += delta
                if (
                    self.first_favorable_trade_us is not None
                    and ts_us >= self.first_favorable_trade_us
                ):
                    self.winner_adds_after_passage += delta
            else:
                self.winner_removes += -delta
        else:
            if delta > 0:
                self.loser_adds += delta
            else:
                self.loser_removes += -delta


@dataclass
class Phase:
    study_idx: int
    name: str
    start_us: int
    end_us: int
    lo_tick: int
    hi_tick: int
    winner_side: int
    loser_side: int
    levels: dict[int, LevelFlow] = field(default_factory=dict)
    opened: bool = False
    closed: bool = False
    valid_at_open: bool = False
    valid_at_close: bool = False

    def __post_init__(self) -> None:
        self.levels = {
            tick: LevelFlow(tick=tick)
            for tick in range(self.lo_tick, self.hi_tick + 1)
        }


@dataclass
class Study:
    idx: int
    row: dict[str, str]
    conversion: Conversion
    direction: int
    edge_tick: int
    root_failed_us: int | None
    first_entry_us: int | None
    escape_us: int | None = None
    return_start_us: int | None = None
    resolution_us: int | None = None
    road_extreme_tick: int | None = None
    return_extreme_tick: int | None = None
    lifecycle: str = ""
    resolution: str = ""
    entry_tick: int | None = None
    entry_road_extreme_tick: int | None = None
    entry_road_extreme_us: int | None = None
    entry_test_zone_start_tick: int | None = None
    entry_test_zone_start_us: int | None = None
    entry_resolution_us: int | None = None
    entry_resolution: str = ""
    post_entry_adverse_tick: int | None = None
    prior_return_count: int = 0
    prior_return_depth_ticks: list[int] = field(default_factory=list)
    entry_return_active: bool = False
    checkpoint_ticks: dict[int, int] = field(default_factory=dict)
    phases: dict[str, Phase] = field(default_factory=dict)

    @property
    def root_id(self) -> str:
        return self.row["root_id"]

    @property
    def date(self) -> str:
        return self.row["date"]

    @property
    def side(self) -> str:
        return self.row["side"]


def make_conversion(idx: int, row: dict[str, str]) -> Conversion:
    demand = row["side"] == "Demand"
    lo = float(row["root_lo"])
    hi = float(row["root_hi"])
    loser = ASK if demand else BID
    owned = parse_et(row["root_owned_et"]).astimezone(UTC)
    return Conversion(
        idx=idx,
        date=row["date"],
        ts_utc=owned,
        ts_et=row["root_owned_et"],
        band_id=row["root_id"],
        side="demand" if demand else "supply",
        consumed_side="supply" if demand else "demand",
        lo_price=lo,
        hi_price=hi,
        lo_tick=price_to_tick(lo),
        hi_tick=price_to_tick(hi),
        loser_side=loser,
        winner_side=-loser,
        width_pts=hi - lo,
        max_abs_z=0.0,
        score=0.0,
        same_band_outcome=row.get("root_first_test_verdict", ""),
        life_sec="",
        raw=row,
    )


def load_studies(
    path: Path,
    start: str,
    end: str,
    population: str,
) -> list[Study]:
    rows: list[dict[str, str]] = []
    with path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            if not in_date_range(row["date"], start, end):
                continue
            if population == "traded" and row.get("traded") != "True":
                continue
            outcome = (
                row.get("entry_structural_outcome", "")
                if population == "traded"
                else row.get("structural_outcome", "")
            )
            if outcome not in {
                "ADVANCED_AFTER_ENTRY",
                "ROOT_FAILED_AFTER_ENTRY",
                "ADVANCED_TO_FAVORABLE_SUCCESSOR",
                "ROOT_FAILED_FIRST",
            }:
                continue
            rows.append(row)

    studies: list[Study] = []
    for idx, row in enumerate(rows):
        conv = make_conversion(idx, row)
        root_failed = row.get("root_failed_et", "")
        first_entry = row.get("first_entry_et", "")
        studies.append(
            Study(
                idx=idx,
                row=row,
                conversion=conv,
                direction=1 if row["side"] == "Demand" else -1,
                edge_tick=conv.hi_tick if row["side"] == "Demand" else conv.lo_tick,
                root_failed_us=to_us(parse_et(root_failed).astimezone(UTC))
                if root_failed
                else None,
                first_entry_us=to_us(parse_et(first_entry).astimezone(UTC))
                if first_entry
                else None,
            )
        )
    return studies


def signed_ticks(study: Study, tick: int) -> int:
    return study.direction * (tick - study.edge_tick)


def segment_lifecycle(
    study: Study,
    times: list[int],
    ticks: list[int],
    sizes: list[float],
    signs: list[int],
    extension_ticks: int,
    retrace_ticks: int,
    retrace_fraction: float,
    lifecycle_seconds: float,
    return_seconds: float,
) -> None:
    conv = study.conversion
    resolve_attack_window(
        conv,
        times,
        [tick * TICK_SIZE for tick in ticks],
    )
    # Road construction starts at the actual tape break so the escape/confirmation
    # interval is retained. A return cannot begin until LL has declared the root,
    # and must retrace a material fraction of the road built so far. This keeps
    # attack noise and one-point pullbacks from becoming false "tests."
    road_start_us = conv.break_us
    confirmation_us = to_us(conv.ts_utc)
    lifecycle_end = confirmation_us + int(lifecycle_seconds * 1_000_000)
    scan_end = min(
        lifecycle_end,
        study.root_failed_us if study.root_failed_us is not None else lifecycle_end,
    )
    lo = bisect.bisect_left(times, road_start_us)
    hi = bisect.bisect_right(times, scan_end)

    extreme_tick: int | None = None
    escape_us: int | None = None
    return_start: int | None = None

    for i in range(lo, hi):
        distance = signed_ticks(study, ticks[i])
        if distance <= 0:
            continue
        if escape_us is None:
            escape_us = times[i]
        if extreme_tick is None or study.direction * (ticks[i] - extreme_tick) > 0:
            extreme_tick = ticks[i]
        extension = (
            signed_ticks(study, extreme_tick)
            if extreme_tick is not None
            else 0
        )
        required_retrace = max(
            retrace_ticks, int(math.ceil(extension * retrace_fraction))
        )
        if (
            times[i] >= confirmation_us
            and extreme_tick is not None
            and extension >= extension_ticks
            and study.direction * (extreme_tick - ticks[i]) >= required_retrace
        ):
            return_start = times[i]
            break

    study.escape_us = escape_us
    study.road_extreme_tick = extreme_tick
    study.return_start_us = return_start

    if escape_us is None:
        study.lifecycle = "NO_FAVORABLE_ESCAPE"
        study.resolution = (
            "ROOT_FAILED"
            if study.root_failed_us is not None and study.root_failed_us <= lifecycle_end
            else "WINDOW_END"
        )
        study.resolution_us = scan_end
        return

    if extreme_tick is None or signed_ticks(study, extreme_tick) < extension_ticks:
        study.lifecycle = "NO_MEANINGFUL_EXTENSION"
        study.resolution = (
            "ROOT_FAILED"
            if study.root_failed_us is not None and study.root_failed_us <= lifecycle_end
            else "WINDOW_END"
        )
        study.resolution_us = scan_end
        return

    if return_start is None:
        study.lifecycle = "NO_MEANINGFUL_RETURN"
        study.resolution = (
            "ROOT_FAILED"
            if study.root_failed_us is not None and study.root_failed_us <= lifecycle_end
            else "WINDOW_END"
        )
        study.resolution_us = scan_end
        return

    study.lifecycle = "RETURN_OBSERVED"
    return_deadline = return_start + int(return_seconds * 1_000_000)
    if study.root_failed_us is not None:
        return_deadline = min(return_deadline, study.root_failed_us)
    return_lo = bisect.bisect_left(times, return_start)
    return_hi = bisect.bisect_right(times, return_deadline)
    adverse_extreme = extreme_tick
    resolution_us = return_deadline
    resolution = (
        "ROOT_FAILED"
        if study.root_failed_us is not None and study.root_failed_us <= return_deadline
        else "RETURN_WINDOW_END"
    )

    for i in range(return_lo, return_hi):
        tick = ticks[i]
        if study.direction * (adverse_extreme - tick) > 0:
            adverse_extreme = tick
        if study.direction * (tick - extreme_tick) >= 0:
            resolution_us = times[i]
            resolution = "READVANCED"
            break

    study.return_extreme_tick = adverse_extreme
    study.resolution_us = resolution_us
    study.resolution = resolution

    road_a = study.edge_tick + study.direction
    road_b = extreme_tick
    road_lo, road_hi = sorted((road_a, road_b))
    study.phases["build"] = Phase(
        study_idx=study.idx,
        name="build",
        start_us=road_start_us,
        end_us=return_start,
        lo_tick=road_lo,
        hi_tick=road_hi,
        winner_side=conv.winner_side,
        loser_side=conv.loser_side,
    )
    if resolution_us > return_start:
        study.phases["return"] = Phase(
            study_idx=study.idx,
            name="return",
            start_us=return_start,
            end_us=resolution_us,
            lo_tick=road_lo,
            hi_tick=road_hi,
            winner_side=conv.winner_side,
            loser_side=conv.loser_side,
        )

    for phase in study.phases.values():
        p_lo = bisect.bisect_left(times, phase.start_us)
        p_hi = bisect.bisect_right(times, phase.end_us)
        for i in range(p_lo, p_hi):
            tick = ticks[i]
            level = phase.levels.get(tick)
            if level is None:
                continue
            qty = sizes[i]
            if signs[i] == study.direction:
                level.favorable_trade_qty += qty
                if level.first_favorable_trade_us is None:
                    level.first_favorable_trade_us = times[i]
            elif signs[i] == -study.direction:
                level.adverse_trade_qty += qty


def segment_prior_returns(
    study: Study,
    times: list[int],
    ticks: list[int],
    start_us: int,
    entry_us: int,
    step_ticks: int,
) -> None:
    """Count completed material returns/readvances before the entry test."""

    lo = bisect.bisect_left(times, start_us)
    hi = bisect.bisect_right(times, entry_us)
    peak_tick: int | None = None
    return_peak: int | None = None
    return_trough: int | None = None
    in_return = False

    for i in range(lo, hi):
        tick = ticks[i]
        if signed_ticks(study, tick) <= 0:
            continue
        if peak_tick is None:
            peak_tick = tick
            continue

        if in_return:
            if study.direction * (return_trough - tick) > 0:
                return_trough = tick
            if study.direction * (tick - return_peak) >= 0:
                study.prior_return_depth_ticks.append(
                    study.direction * (return_peak - return_trough)
                )
                study.prior_return_count += 1
                in_return = False
                peak_tick = tick
                return_peak = None
                return_trough = None
            continue

        if study.direction * (tick - peak_tick) > 0:
            peak_tick = tick
            continue
        if study.direction * (peak_tick - tick) >= step_ticks:
            in_return = True
            return_peak = peak_tick
            return_trough = tick

    study.entry_return_active = in_return


def segment_entry_test(
    study: Study,
    times: list[int],
    ticks: list[int],
    sizes: list[float],
    signs: list[int],
    extension_ticks: int,
    test_zone_ticks: int,
    step_ticks: int,
    post_entry_seconds: float,
) -> None:
    """Align the road/return decomposition to EAR's actual first entry.

    The relevant return for entry quality is the approach that contains the
    decision, not necessarily the first pullback after conversion. The road
    extreme is the most favorable traded price from conversion break through
    entry; the latest print at that extreme begins the final approach.
    """

    if study.first_entry_us is None:
        return
    start_us = study.conversion.break_us
    entry_us = study.first_entry_us
    lo = bisect.bisect_left(times, start_us)
    hi = bisect.bisect_right(times, entry_us)
    if hi <= lo:
        return

    best_distance = 0
    extreme_tick: int | None = None
    extreme_us: int | None = None
    for i in range(lo, hi):
        distance = signed_ticks(study, ticks[i])
        if distance > best_distance or (
            distance == best_distance and distance > 0
        ):
            best_distance = distance
            extreme_tick = ticks[i]
            extreme_us = times[i]
    if (
        extreme_tick is None
        or extreme_us is None
        or best_distance < extension_ticks
        or extreme_us >= entry_us
    ):
        return

    entry_i = bisect.bisect_right(times, entry_us) - 1
    if entry_i < 0:
        return
    study.entry_tick = ticks[entry_i]
    study.entry_road_extreme_tick = extreme_tick
    study.entry_road_extreme_us = extreme_us
    segment_prior_returns(
        study,
        times,
        ticks,
        start_us,
        entry_us,
        step_ticks,
    )

    road_a = study.edge_tick + study.direction
    road_lo, road_hi = sorted((road_a, extreme_tick))
    study.phases["entry_build"] = Phase(
        study_idx=study.idx,
        name="entry_build",
        start_us=start_us,
        end_us=extreme_us,
        lo_tick=road_lo,
        hi_tick=road_hi,
        winner_side=study.conversion.winner_side,
        loser_side=study.conversion.loser_side,
    )
    study.phases["entry_approach"] = Phase(
        study_idx=study.idx,
        name="entry_approach",
        start_us=extreme_us,
        end_us=entry_us,
        lo_tick=road_lo,
        hi_tick=road_hi,
        winner_side=study.conversion.winner_side,
        loser_side=study.conversion.loser_side,
    )

    # The moving test front is the fixed-price strip underneath the decision:
    # bids at/below a bullish test, asks at/above a bearish test. The prior
    # version accidentally measured the already-traversed favorable side, where
    # crossed-level eviction correctly leaves little resting book.
    zone_a = study.entry_tick
    zone_b = study.entry_tick - study.direction * test_zone_ticks
    zone_lo = min(zone_a, zone_b)
    zone_hi = max(zone_a, zone_b)
    if zone_lo <= zone_hi:
        last_outside_i: int | None = None
        for i in range(hi - 1, lo - 1, -1):
            if times[i] < extreme_us:
                break
            favorable_from_entry = study.direction * (ticks[i] - study.entry_tick)
            if favorable_from_entry > test_zone_ticks:
                last_outside_i = i
                break
        zone_start_i = (
            last_outside_i + 1
            if last_outside_i is not None and last_outside_i + 1 < hi
            else bisect.bisect_left(times, extreme_us)
        )
        zone_start_us = max(times[zone_start_i], extreme_us)
        if zone_start_us < entry_us:
            study.entry_test_zone_start_tick = ticks[zone_start_i]
            study.entry_test_zone_start_us = zone_start_us
            study.phases["entry_test_zone"] = Phase(
                study_idx=study.idx,
                name="entry_test_zone",
                start_us=zone_start_us,
                end_us=entry_us,
                lo_tick=zone_lo,
                hi_tick=zone_hi,
                winner_side=study.conversion.winner_side,
                loser_side=study.conversion.loser_side,
            )

    deadline = entry_us + int(post_entry_seconds * 1_000_000)
    if study.root_failed_us is not None:
        deadline = min(deadline, study.root_failed_us)
    post_lo = bisect.bisect_left(times, entry_us)
    post_hi = bisect.bisect_right(times, deadline)
    adverse_tick = study.entry_tick
    resolution_us = deadline
    resolution = (
        "ROOT_FAILED"
        if study.root_failed_us is not None and study.root_failed_us <= deadline
        else "POST_ENTRY_WINDOW_END"
    )
    for i in range(post_lo, post_hi):
        tick = ticks[i]
        if study.direction * (adverse_tick - tick) > 0:
            adverse_tick = tick
        if study.direction * (tick - extreme_tick) >= 0:
            resolution_us = times[i]
            resolution = "READVANCED"
            break
    study.post_entry_adverse_tick = adverse_tick
    study.entry_resolution_us = resolution_us
    study.entry_resolution = resolution
    if resolution_us > entry_us:
        study.phases["post_entry"] = Phase(
            study_idx=study.idx,
            name="post_entry",
            start_us=entry_us,
            end_us=resolution_us,
            lo_tick=road_lo,
            hi_tick=road_hi,
            winner_side=study.conversion.winner_side,
            loser_side=study.conversion.loser_side,
        )

    for checkpoint_ms in CHECKPOINT_MS:
        checkpoint_us = entry_us + checkpoint_ms * 1_000
        checkpoint_i = bisect.bisect_right(times, checkpoint_us) - 1
        if checkpoint_i < entry_i:
            continue
        checkpoint_tick = ticks[checkpoint_i]
        study.checkpoint_ticks[checkpoint_ms] = checkpoint_tick
        checkpoint_zone_b = (
            checkpoint_tick - study.direction * test_zone_ticks
        )
        study.phases[f"checkpoint_{checkpoint_ms}ms"] = Phase(
            study_idx=study.idx,
            name=f"checkpoint_{checkpoint_ms}ms",
            start_us=entry_us,
            end_us=checkpoint_us,
            lo_tick=min(checkpoint_tick, checkpoint_zone_b),
            hi_tick=max(checkpoint_tick, checkpoint_zone_b),
            winner_side=study.conversion.winner_side,
            loser_side=study.conversion.loser_side,
        )

    entry_phase_names = [
        "entry_build",
        "entry_approach",
        "entry_test_zone",
        "post_entry",
        *(f"checkpoint_{checkpoint_ms}ms" for checkpoint_ms in CHECKPOINT_MS),
    ]
    for phase_name in entry_phase_names:
        phase = study.phases.get(phase_name)
        if phase is None:
            continue
        p_lo = bisect.bisect_left(times, phase.start_us)
        p_hi = bisect.bisect_right(times, phase.end_us)
        for i in range(p_lo, p_hi):
            level = phase.levels.get(ticks[i])
            if level is None:
                continue
            qty = sizes[i]
            if signs[i] == study.direction:
                level.favorable_trade_qty += qty
                if level.first_favorable_trade_us is None:
                    level.first_favorable_trade_us = times[i]
            elif signs[i] == -study.direction:
                level.adverse_trade_qty += qty


def replay_day(symbol_dir: str, day: str, phases: list[Phase], batch_files: int) -> dict[str, int]:
    files = market_recorder_files(
        symbol_dir, "book_events", datetime.fromisoformat(day).date()
    )
    stats = {
        "files": len(files),
        "rows": 0,
        "deltas": 0,
        "gaps": 0,
        "resets": 0,
        "unopened_phases": 0,
        "invalid_open": 0,
        "invalid_close": 0,
    }
    if not files or not phases:
        return stats

    phase_by_id = list(phases)
    start_order = sorted(
        range(len(phase_by_id)),
        key=lambda phase_id: phase_by_id[phase_id].start_us,
    )
    end_order = sorted(
        range(len(phase_by_id)),
        key=lambda phase_id: phase_by_id[phase_id].end_us,
    )
    passage_order = sorted(
        (
            level.first_favorable_trade_us,
            phase_id,
            level.tick,
        )
        for phase_id, phase in enumerate(phase_by_id)
        for level in phase.levels.values()
        if level.first_favorable_trade_us is not None
    )
    next_start = 0
    next_end = 0
    next_passage = 0
    active_ids: set[int] = set()
    active_by_tick: dict[int, set[int]] = defaultdict(set)
    replay = BookReplay()

    def side_size(side: int, tick: int) -> float:
        levels = replay.bid_levels if side == BID else replay.ask_levels
        return levels.get(tick, 0.0)

    def sample_level(phase: Phase, level: LevelFlow, ts_us: int, *, opening: bool = False) -> None:
        level.sample(
            side_size(phase.winner_side, level.tick),
            side_size(phase.loser_side, level.tick),
            ts_us,
            opening=opening,
        )

    def sample_phase(phase: Phase, ts_us: int, *, opening: bool = False) -> None:
        for level in phase.levels.values():
            sample_level(phase, level, ts_us, opening=opening)

    def activate(phase_id: int) -> None:
        phase = phase_by_id[phase_id]
        sample_phase(phase, phase.start_us, opening=True)
        phase.opened = True
        phase.valid_at_open = replay.valid
        active_ids.add(phase_id)
        for tick in phase.levels:
            active_by_tick[tick].add(phase_id)

    def sample_passage(phase_id: int, tick: int) -> None:
        if phase_id not in active_ids:
            return
        phase = phase_by_id[phase_id]
        level = phase.levels[tick]
        if level.passage_sampled:
            return
        level.sample_passage(
            side_size(phase.winner_side, tick),
            side_size(phase.loser_side, tick),
        )

    def close_phase(phase_id: int) -> None:
        if phase_id not in active_ids:
            return
        phase = phase_by_id[phase_id]
        sample_phase(phase, phase.end_us)
        phase.closed = True
        phase.valid_at_close = replay.valid
        active_ids.remove(phase_id)
        for tick in phase.levels:
            tick_phases = active_by_tick[tick]
            tick_phases.remove(phase_id)
            if not tick_phases:
                del active_by_tick[tick]

    for base in range(0, len(files), batch_files):
        frame = pl.read_parquet(
            files[base : base + batch_files], columns=EVENT_COLUMNS
        ).sort(["sequence", "subsequence"])
        stats["rows"] += frame.height
        for row in frame.iter_rows():
            ts_us = row[C_TS]

            while (
                next_start < len(start_order)
                and phase_by_id[start_order[next_start]].start_us <= ts_us
            ):
                phase_id = start_order[next_start]
                phase = phase_by_id[phase_id]
                next_start += 1
                if phase.end_us < ts_us:
                    continue
                activate(phase_id)

            while (
                next_passage < len(passage_order)
                and passage_order[next_passage][0] <= ts_us
            ):
                _, phase_id, tick = passage_order[next_passage]
                next_passage += 1
                sample_passage(phase_id, tick)

            while (
                next_end < len(end_order)
                and phase_by_id[end_order[next_end]].end_us < ts_us
            ):
                close_phase(end_order[next_end])
                next_end += 1

            kind = row[C_KIND]
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
                continue

            stats["deltas"] += 1
            prior = replay.quotes.get(row[C_QID]) if replay.seeded and replay.valid else None
            deltas: tuple[tuple[int, int, float], ...] = ()
            if replay.seeded and replay.valid:
                if row[C_CLOSED]:
                    if prior is not None:
                        deltas = ((prior.side, prior.price_tick, -prior.size),)
                else:
                    side = row[C_SIDE]
                    tick = row[C_TICK]
                    size = float(row[C_SIZE])
                    if (
                        row[C_QID] != 0
                        and side in (BID, ASK)
                        and math.isfinite(size)
                        and size >= 0
                    ):
                        if prior is None:
                            deltas = ((side, tick, size),) if size > 0 else ()
                        elif prior.side == side and prior.price_tick == tick:
                            diff = size - prior.size
                            deltas = (
                                ((side, tick, diff),) if abs(diff) > 1e-9 else ()
                            )
                        else:
                            deltas = ((prior.side, prior.price_tick, -prior.size),)
                            if size > 0:
                                deltas += ((side, tick, size),)

            replay.apply(event)
            if not active_ids or not deltas:
                continue
            for side, tick, delta in deltas:
                for phase_id in active_by_tick.get(tick, ()):
                    phase = phase_by_id[phase_id]
                    level = phase.levels[tick]
                    level.observe(side, delta, phase.winner_side, ts_us)
                    sample_level(phase, level, ts_us)

    while next_passage < len(passage_order):
        _, phase_id, tick = passage_order[next_passage]
        next_passage += 1
        sample_passage(phase_id, tick)
    for phase_id in tuple(active_ids):
        close_phase(phase_id)

    for phase in phase_by_id:
        if not phase.opened:
            stats["unopened_phases"] += 1
        elif not phase.valid_at_open:
            stats["invalid_open"] += 1
        if phase.closed and not phase.valid_at_close:
            stats["invalid_close"] += 1

    stats["gaps"] = replay.gaps
    stats["resets"] = replay.completed_resets
    stats["incomplete_resets"] = replay.incomplete_resets
    stats["crossed_levels_evicted"] = replay.crossed_levels_evicted
    return stats


def ratio(num: float, den: float) -> float | None:
    return num / den if den > 1e-9 else None


def total(values: list[float]) -> float:
    return sum(value for value in values if math.isfinite(value))


def aggregate_phase(phase: Phase | None) -> dict[str, Any]:
    if phase is None:
        return {}
    levels = list(phase.levels.values())
    traded = [level for level in levels if level.favorable_trade_qty > 0]
    adverse_touched = [level for level in levels if level.adverse_trade_qty > 0]
    offered = [
        level
        for level in traded
        if level.loser_at_passage > 0
        or level.max_loser > 0
        or level.loser_adds > 0
    ]
    backed = [
        level
        for level in traded
        if level.winner_at_passage > 0
        or level.max_winner_after_passage > 0
        or level.winner_adds_after_passage > 0
    ]
    loser_readded = [level for level in traded if level.loser_adds > 0]
    backed_ticks = {level.tick for level in backed}
    touched_backing = [
        level for level in adverse_touched if level.tick in backed_ticks
    ]
    retained_touched_backing = [
        level for level in touched_backing if level.end_winner > 0
    ]

    winner_seed = total([level.seed_winner for level in levels])
    winner_end = total([level.end_winner for level in levels])
    loser_seed = total([level.seed_loser for level in levels])
    loser_end = total([level.end_loser for level in levels])
    favorable_qty = sum(level.favorable_trade_qty for level in levels)
    adverse_qty = sum(level.adverse_trade_qty for level in levels)

    return {
        "duration_s": (phase.end_us - phase.start_us) / 1_000_000,
        "road_levels": len(levels),
        "favorable_trade_qty": favorable_qty,
        "adverse_trade_qty": adverse_qty,
        "favorable_traded_levels": len(traded),
        "favorable_traded_levels_frac": ratio(len(traded), len(levels)),
        "offered_and_traded_levels": len(offered),
        "offered_and_traded_levels_frac": ratio(len(offered), len(traded)),
        "loser_readded_levels": len(loser_readded),
        "loser_readded_levels_frac": ratio(len(loser_readded), len(traded)),
        "backed_after_passage_levels": len(backed),
        "backed_after_passage_levels_frac": ratio(len(backed), len(traded)),
        "backing_end_levels": sum(level.end_winner > 0 for level in levels),
        "backing_end_levels_frac": ratio(
            sum(level.end_winner > 0 for level in levels), len(levels)
        ),
        "winner_seed_qty": winner_seed,
        "winner_end_qty": winner_end,
        "winner_add_qty": sum(level.winner_adds for level in levels),
        "winner_remove_qty": sum(level.winner_removes for level in levels),
        "winner_add_after_passage_qty": sum(
            level.winner_adds_after_passage for level in levels
        ),
        "winner_net_provision_qty": winner_end - winner_seed + adverse_qty,
        "loser_seed_qty": loser_seed,
        "loser_end_qty": loser_end,
        "loser_add_qty": sum(level.loser_adds for level in levels),
        "loser_remove_qty": sum(level.loser_removes for level in levels),
        "loser_net_provision_qty": loser_end - loser_seed + favorable_qty,
        "adverse_touched_levels": len(adverse_touched),
        "touched_backing_levels": len(touched_backing),
        "touched_backing_retained_levels": len(retained_touched_backing),
        "touched_backing_retained_frac": ratio(
            len(retained_touched_backing), len(touched_backing)
        ),
        "valid_at_open": phase.valid_at_open,
        "valid_at_close": phase.valid_at_close,
    }


def prefixed(prefix: str, values: dict[str, Any]) -> dict[str, Any]:
    return {f"{prefix}_{key}": value for key, value in values.items()}


def phase_valid(phase: Phase | None) -> bool:
    return bool(
        phase is not None
        and phase.opened
        and phase.closed
        and phase.valid_at_open
        and phase.valid_at_close
    )


def cross_phase_backing(
    build_phase: Phase | None,
    test_phase: Phase | None,
) -> dict[str, Any]:
    backed_ticks: set[int] = set()
    if build_phase is not None:
        backed_ticks = {
            level.tick
            for level in build_phase.levels.values()
            if level.favorable_trade_qty > 0
            and (
                level.winner_at_passage > 0
                or level.max_winner_after_passage > 0
                or level.winner_adds_after_passage > 0
            )
        }
    touched: list[LevelFlow] = []
    if test_phase is not None:
        touched = [
            level
            for level in test_phase.levels.values()
            if level.tick in backed_ticks and level.adverse_trade_qty > 0
        ]
    retained = [level for level in touched if level.end_winner > 0]
    reloaded = [
        level
        for level in touched
        if level.winner_adds > 0
        or (
            math.isfinite(level.seed_winner)
            and math.isfinite(level.end_winner)
            and level.end_winner - level.seed_winner + level.adverse_trade_qty > 0
        )
    ]
    return {
        "build_backing_levels": len(backed_ticks),
        "build_backing_touched_levels": len(touched),
        "build_backing_retained_levels": len(retained),
        "build_backing_retained_frac": ratio(len(retained), len(touched)),
        "build_backing_reloaded_levels": len(reloaded),
        "build_backing_reloaded_frac": ratio(len(reloaded), len(touched)),
    }


def study_row(study: Study, population: str) -> dict[str, Any]:
    row = study.row
    build = aggregate_phase(study.phases.get("build"))
    ret = aggregate_phase(study.phases.get("return"))
    entry_build = aggregate_phase(study.phases.get("entry_build"))
    entry_approach = aggregate_phase(study.phases.get("entry_approach"))
    entry_test_zone = aggregate_phase(study.phases.get("entry_test_zone"))
    post_entry = aggregate_phase(study.phases.get("post_entry"))
    checkpoint_values = {
        checkpoint_ms: aggregate_phase(
            study.phases.get(f"checkpoint_{checkpoint_ms}ms")
        )
        for checkpoint_ms in CHECKPOINT_MS
    }
    outcome = (
        row.get("entry_structural_outcome", "")
        if population == "traded"
        else row.get("structural_outcome", "")
    )
    advanced = outcome in {
        "ADVANCED_AFTER_ENTRY",
        "ADVANCED_TO_FAVORABLE_SUCCESSOR",
    }
    road_ticks = (
        signed_ticks(study, study.road_extreme_tick)
        if study.road_extreme_tick is not None
        else None
    )
    adverse_ticks = (
        study.direction
        * (study.road_extreme_tick - study.return_extreme_tick)
        if study.road_extreme_tick is not None
        and study.return_extreme_tick is not None
        else None
    )
    retrace_frac = (
        ratio(float(adverse_ticks), float(road_ticks))
        if adverse_ticks is not None and road_ticks is not None
        else None
    )
    return_adverse_qty = ret.get("adverse_trade_qty")
    displacement_per_10 = (
        10.0 * adverse_ticks / return_adverse_qty
        if adverse_ticks is not None
        and return_adverse_qty is not None
        and return_adverse_qty > 0
        else None
    )
    return_cross = cross_phase_backing(
        study.phases.get("build"), study.phases.get("return")
    )
    entry_cross = cross_phase_backing(
        study.phases.get("entry_build"), study.phases.get("entry_approach")
    )
    entry_road_ticks = (
        signed_ticks(study, study.entry_road_extreme_tick)
        if study.entry_road_extreme_tick is not None
        else None
    )
    entry_adverse_ticks = (
        study.direction * (study.entry_road_extreme_tick - study.entry_tick)
        if study.entry_road_extreme_tick is not None and study.entry_tick is not None
        else None
    )
    entry_retrace_frac = (
        ratio(float(entry_adverse_ticks), float(entry_road_ticks))
        if entry_adverse_ticks is not None and entry_road_ticks is not None
        else None
    )
    entry_adverse_qty = entry_approach.get("adverse_trade_qty")
    entry_displacement_per_10 = (
        10.0 * entry_adverse_ticks / entry_adverse_qty
        if entry_adverse_ticks is not None
        and entry_adverse_qty is not None
        and entry_adverse_qty > 0
        else None
    )
    entry_test_zone_adverse_ticks = (
        study.direction * (study.entry_test_zone_start_tick - study.entry_tick)
        if study.entry_test_zone_start_tick is not None
        and study.entry_tick is not None
        else None
    )
    entry_test_zone_adverse_qty = entry_test_zone.get("adverse_trade_qty")
    entry_test_zone_displacement_per_10 = (
        10.0 * entry_test_zone_adverse_ticks / entry_test_zone_adverse_qty
        if entry_test_zone_adverse_ticks is not None
        and entry_test_zone_adverse_qty is not None
        and entry_test_zone_adverse_qty > 0
        else None
    )
    max_prior_return_depth = (
        max(study.prior_return_depth_ticks)
        if study.prior_return_depth_ticks
        else None
    )
    entry_return_vs_prior_max = (
        ratio(float(entry_adverse_ticks), float(max_prior_return_depth))
        if entry_adverse_ticks is not None
        and max_prior_return_depth is not None
        else None
    )
    post_entry_adverse_ticks = (
        study.direction * (study.entry_tick - study.post_entry_adverse_tick)
        if study.entry_tick is not None and study.post_entry_adverse_tick is not None
        else None
    )
    post_entry_adverse_qty = post_entry.get("adverse_trade_qty")
    post_entry_displacement_per_10 = (
        10.0 * post_entry_adverse_ticks / post_entry_adverse_qty
        if post_entry_adverse_ticks is not None
        and post_entry_adverse_qty is not None
        and post_entry_adverse_qty > 0
        else None
    )

    result: dict[str, Any] = {
        "date": study.date,
        "root_id": study.root_id,
        "side": study.side,
        "root_owned_et": row["root_owned_et"],
        "root_lo": row["root_lo"],
        "root_hi": row["root_hi"],
        "first_entry_et": row.get("first_entry_et", ""),
        "entry_roles": row.get("entry_roles", ""),
        "entry_reasons": row.get("entry_reasons", ""),
        "directive_ids": row.get("directive_ids", ""),
        "session_id": row.get("session_id", ""),
        "prior_protection_id": row.get("prior_protection_id", ""),
        "prior_protection_source": row.get("prior_protection_source", ""),
        "prior_protection_distance_pts": row.get(
            "prior_protection_distance_pts", ""
        ),
        "prior_protection_failed_et": row.get(
            "prior_protection_failed_et", ""
        ),
        "outcome": outcome,
        "advanced": advanced,
        "conversion_break_et": et_text(study.conversion.break_us),
        "road_start_et": et_text(study.conversion.break_us),
        "confirmation_et": study.row["root_owned_et"],
        "escape_et": et_text(study.escape_us),
        "return_start_et": et_text(study.return_start_us),
        "resolution_et": et_text(study.resolution_us),
        "lifecycle": study.lifecycle,
        "resolution": study.resolution,
        "road_extreme_price": (
            study.road_extreme_tick * TICK_SIZE
            if study.road_extreme_tick is not None
            else None
        ),
        "return_extreme_price": (
            study.return_extreme_tick * TICK_SIZE
            if study.return_extreme_tick is not None
            else None
        ),
        "road_extension_ticks": road_ticks,
        "return_adverse_ticks": adverse_ticks,
        "return_road_retrace_frac": retrace_frac,
        "return_adverse_ticks_per_10_qty": displacement_per_10,
        "entry_road_extreme_et": et_text(study.entry_road_extreme_us),
        "entry_road_extreme_price": (
            study.entry_road_extreme_tick * TICK_SIZE
            if study.entry_road_extreme_tick is not None
            else None
        ),
        "entry_decision_price": (
            study.entry_tick * TICK_SIZE if study.entry_tick is not None else None
        ),
        "entry_road_extension_ticks": entry_road_ticks,
        "entry_approach_adverse_ticks": entry_adverse_ticks,
        "entry_approach_road_retrace_frac": entry_retrace_frac,
        "entry_approach_adverse_ticks_per_10_qty": entry_displacement_per_10,
        "prior_material_return_count": study.prior_return_count,
        "prior_return_depth_max_ticks": max_prior_return_depth,
        "prior_return_depth_last_ticks": (
            study.prior_return_depth_ticks[-1]
            if study.prior_return_depth_ticks
            else None
        ),
        "entry_return_ordinal": study.prior_return_count + 1,
        "entry_return_active": study.entry_return_active,
        "entry_return_depth_vs_prior_max": entry_return_vs_prior_max,
        "entry_test_zone_start_et": et_text(study.entry_test_zone_start_us),
        "entry_test_zone_start_price": (
            study.entry_test_zone_start_tick * TICK_SIZE
            if study.entry_test_zone_start_tick is not None
            else None
        ),
        "entry_test_zone_adverse_ticks": entry_test_zone_adverse_ticks,
        "entry_test_zone_adverse_ticks_per_10_qty": (
            entry_test_zone_displacement_per_10
        ),
        "entry_resolution_et": et_text(study.entry_resolution_us),
        "entry_resolution": study.entry_resolution,
        "post_entry_adverse_ticks": post_entry_adverse_ticks,
        "post_entry_adverse_ticks_per_10_qty": post_entry_displacement_per_10,
        "root_failed_et": row.get("root_failed_et", ""),
        "post_entry_successor_id": row.get("post_entry_successor_id", ""),
        "post_entry_successor_owned_et": row.get(
            "post_entry_successor_owned_et", ""
        ),
        "successor_failure_propagation": row.get(
            "successor_failure_propagation", ""
        ),
        "clean_or_escaped_context": (
            row.get("pre_10m_50pts_two_sided_fail") != "True"
            or row.get("pre_10m_50pts_favorable_position") == "beyond_favorable_edge"
        ),
        "entry_book_valid": all(
            phase_valid(study.phases.get(phase_name))
            for phase_name in (
                "entry_build",
                "entry_approach",
                "entry_test_zone",
            )
        ),
        "post_entry_book_valid": phase_valid(
            study.phases.get("post_entry")
        ),
    }
    result.update(prefixed("build", build))
    result.update(prefixed("return", ret))
    result.update(prefixed("return", return_cross))
    result.update(prefixed("entry_build", entry_build))
    result.update(prefixed("entry_approach", entry_approach))
    result.update(prefixed("entry_approach", entry_cross))
    result.update(prefixed("entry_test_zone", entry_test_zone))
    result.update(prefixed("post_entry", post_entry))
    for checkpoint_ms, values in checkpoint_values.items():
        prefix = f"checkpoint_{checkpoint_ms}ms"
        checkpoint_tick = study.checkpoint_ticks.get(checkpoint_ms)
        checkpoint_us = (
            study.first_entry_us + checkpoint_ms * 1_000
            if study.first_entry_us is not None
            else None
        )
        result.update(prefixed(prefix, values))
        result.update(
            {
                f"{prefix}_price": (
                    checkpoint_tick * TICK_SIZE
                    if checkpoint_tick is not None
                    else None
                ),
                f"{prefix}_favorable_displacement_ticks": (
                    study.direction * (checkpoint_tick - study.entry_tick)
                    if checkpoint_tick is not None
                    and study.entry_tick is not None
                    else None
                ),
                f"{prefix}_road_remaining_ticks": (
                    signed_ticks(study, checkpoint_tick)
                    if checkpoint_tick is not None
                    else None
                ),
                f"{prefix}_root_live": (
                    checkpoint_us is not None
                    and (
                        study.root_failed_us is None
                        or study.root_failed_us > checkpoint_us
                    )
                ),
                f"{prefix}_book_valid": phase_valid(
                    study.phases.get(prefix)
                ),
            }
        )
    return result


def level_rows(studies: list[Study]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for study in studies:
        for phase_name, phase in study.phases.items():
            for level in phase.levels.values():
                rows.append(
                    {
                        "date": study.date,
                        "root_id": study.root_id,
                        "side": study.side,
                        "phase": phase_name,
                        "phase_start_et": et_text(phase.start_us),
                        "phase_end_et": et_text(phase.end_us),
                        "price": level.tick * TICK_SIZE,
                        "distance_from_root_edge_ticks": signed_ticks(
                            study, level.tick
                        ),
                        "first_favorable_trade_et": et_text(
                            level.first_favorable_trade_us
                        ),
                        "favorable_trade_qty": level.favorable_trade_qty,
                        "adverse_trade_qty": level.adverse_trade_qty,
                        "winner_seed": level.seed_winner,
                        "winner_at_passage": level.winner_at_passage,
                        "winner_end": level.end_winner,
                        "winner_max_after_passage": level.max_winner_after_passage,
                        "winner_adds": level.winner_adds,
                        "winner_removes": level.winner_removes,
                        "winner_adds_after_passage": level.winner_adds_after_passage,
                        "loser_seed": level.seed_loser,
                        "loser_at_passage": level.loser_at_passage,
                        "loser_end": level.end_loser,
                        "loser_max": level.max_loser,
                        "loser_adds": level.loser_adds,
                        "loser_removes": level.loser_removes,
                    }
                )
    return rows


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


ENTRY_FEATURES = [
    "entry_road_extension_ticks",
    "entry_build_duration_s",
    "entry_build_favorable_trade_qty",
    "entry_build_adverse_trade_qty",
    "entry_build_favorable_traded_levels_frac",
    "entry_build_loser_readded_levels_frac",
    "entry_build_backed_after_passage_levels_frac",
    "entry_build_backing_end_levels_frac",
    "entry_build_winner_add_after_passage_qty",
    "entry_build_winner_net_provision_qty",
    "entry_approach_duration_s",
    "entry_approach_adverse_trade_qty",
    "entry_approach_adverse_ticks",
    "entry_approach_road_retrace_frac",
    "entry_approach_adverse_ticks_per_10_qty",
    "prior_material_return_count",
    "prior_return_depth_max_ticks",
    "entry_return_depth_vs_prior_max",
    "entry_approach_winner_net_provision_qty",
    "entry_approach_backing_end_levels_frac",
    "entry_approach_build_backing_retained_frac",
    "entry_approach_build_backing_reloaded_frac",
    "entry_test_zone_duration_s",
    "entry_test_zone_adverse_trade_qty",
    "entry_test_zone_adverse_ticks",
    "entry_test_zone_adverse_ticks_per_10_qty",
    "entry_test_zone_winner_seed_qty",
    "entry_test_zone_winner_end_qty",
    "entry_test_zone_winner_add_qty",
    "entry_test_zone_winner_net_provision_qty",
    "entry_test_zone_backing_end_levels_frac",
]

FIRST_RETURN_FEATURES = [
    "road_extension_ticks",
    "build_duration_s",
    "build_favorable_trade_qty",
    "build_adverse_trade_qty",
    "build_favorable_traded_levels_frac",
    "build_offered_and_traded_levels_frac",
    "build_loser_readded_levels_frac",
    "build_backed_after_passage_levels_frac",
    "build_backing_end_levels_frac",
    "build_winner_add_after_passage_qty",
    "build_winner_net_provision_qty",
    "build_loser_net_provision_qty",
    "return_adverse_trade_qty",
    "return_adverse_ticks",
    "return_road_retrace_frac",
    "return_adverse_ticks_per_10_qty",
    "return_winner_net_provision_qty",
    "return_backing_end_levels_frac",
    "return_build_backing_retained_frac",
    "return_build_backing_reloaded_frac",
]

POST_ENTRY_FEATURES = [
    "post_entry_adverse_trade_qty",
    "post_entry_adverse_ticks",
    "post_entry_adverse_ticks_per_10_qty",
    "post_entry_winner_net_provision_qty",
    "post_entry_backing_end_levels_frac",
]


def fmt(value: Any, digits: int = 3) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            return ""
        return f"{value:.{digits}f}"
    return str(value)


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
                seen.add(key)
                fields.append(key)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: fmt(row.get(key)) for key in fields})


def metric_table(
    rows: list[dict[str, Any]], features: list[str]
) -> list[tuple[str, int, float, float, float]]:
    out: list[tuple[str, int, float, float, float]] = []
    for feature in features:
        positives = [
            float(row[feature])
            for row in rows
            if row.get("advanced") is True and fnum(row.get(feature)) is not None
        ]
        negatives = [
            float(row[feature])
            for row in rows
            if row.get("advanced") is False and fnum(row.get(feature)) is not None
        ]
        score = auc(positives, negatives)
        if score is None:
            continue
        out.append(
            (
                feature,
                len(positives) + len(negatives),
                median(positives),
                median(negatives),
                score,
            )
        )
    return sorted(out, key=lambda item: abs(item[4] - 0.5), reverse=True)


def median_metric(rows: list[dict[str, Any]], key: str) -> float | None:
    values = [
        float(row[key]) for row in rows if fnum(row.get(key)) is not None
    ]
    return median(values) if values else None


def build_report(
    rows: list[dict[str, Any]],
    stats: dict[str, dict[str, int]],
    start: str,
    end: str,
    population: str,
    extension_ticks: int,
    retrace_ticks: int,
    retrace_fraction: float,
) -> str:
    advanced = [row for row in rows if row["advanced"]]
    failed = [row for row in rows if not row["advanced"]]
    returns = [row for row in rows if row["lifecycle"] == "RETURN_OBSERVED"]
    entry_rows = [row for row in rows if row["entry_book_valid"]]
    post_rows = [row for row in rows if row["post_entry_book_valid"]]
    lines = [
        "# Direct Conversion Auction Road",
        "",
        f"Window: {start} through {end} ET. Population: `{population}`.",
        "",
        "## Question",
        "",
        "A direct conversion proves local consumption. This probe asks whether a normal two-sided auction established beyond the consumed band: opposing liquidity appeared and traded, same-side passive backing formed behind price, and the first adverse return failed to erase that road.",
        "",
        "BUILD starts at the tape-derived break and ends at the first causal return after LL declares the root. "
        f"The return must retrace at least `{retrace_ticks}` ticks and `{fmt(retrace_fraction)}` of the favorable road after at least `{extension_ticks}` favorable ticks. "
        "RETURN ends at readvance to the prior extreme, root failure, or the configured timeout. BUILD fields are potential entry-quality evidence; RETURN fields are keep/exit evidence.",
        "",
        "## Population",
        "",
        f"- roots={len(rows)}; advanced={len(advanced)}; root failed first={len(failed)}",
        f"- meaningful return observed={len(returns)}",
        f"- no meaningful return={sum(row['lifecycle'] == 'NO_MEANINGFUL_RETURN' for row in rows)}",
        f"- no meaningful extension={sum(row['lifecycle'] == 'NO_MEANINGFUL_EXTENSION' for row in rows)}",
        f"- no favorable escape={sum(row['lifecycle'] == 'NO_FAVORABLE_ESCAPE' for row in rows)}",
        f"- valid entry-book roots={len(entry_rows)}; invalid entry-book roots={len(rows) - len(entry_rows)}",
        "",
        "## Entry-Test Features",
        "",
        "These fields are measured no later than the first entry decision. AUC is descriptive on this selected sample. `>0.5` means larger values align with advance; `<0.5` means smaller values align with advance. It is not a fitted threshold or out-of-sample validation.",
        "The `entry_test_zone_*` fields isolate the fixed-price strip underneath the decision price: bids at/below a bullish test and asks at/above a bearish test.",
        "",
        "| feature | n | advanced median | failed median | AUC |",
        "|---|---:|---:|---:|---:|",
    ]
    for feature, count, pos_med, neg_med, score in metric_table(
        entry_rows, ENTRY_FEATURES
    ):
        lines.append(
            f"| {feature} | {count} | {fmt(pos_med)} | {fmt(neg_med)} | {fmt(score)} |"
        )

    lines.extend(
        [
            "",
            "## Context Interaction",
            "",
            "| field context | outcome | n | road retrace median | test-zone provision median | test-zone duration median |",
            "|---|---|---:|---:|---:|---:|",
        ]
    )
    for clean in (True, False):
        for is_advanced in (True, False):
            group = [
                row
                for row in entry_rows
                if row["clean_or_escaped_context"] is clean
                and row["advanced"] is is_advanced
            ]
            lines.append(
                "| "
                + " | ".join(
                    [
                        "clean/escaped" if clean else "inside two-sided churn",
                        "advanced" if is_advanced else "failed",
                        str(len(group)),
                        fmt(
                            median_metric(
                                group, "entry_approach_road_retrace_frac"
                            )
                        ),
                        fmt(
                            median_metric(
                                group,
                                "entry_test_zone_winner_net_provision_qty",
                            )
                        ),
                        fmt(
                            median_metric(group, "entry_test_zone_duration_s")
                        ),
                    ]
                )
                + " |"
            )

    lines.extend(
        [
            "",
            "## Day And Side Strata",
            "",
            "| stratum | outcome | n | road retrace median | underneath provision median | underneath end depth median | prior returns median |",
            "|---|---|---:|---:|---:|---:|---:|",
        ]
    )
    strata = [
        *(("day", day) for day in sorted({row["date"] for row in entry_rows})),
        *(("side", side) for side in ("Demand", "Supply")),
        *(("role", role) for role in ("EnterBase", "Add")),
    ]
    for kind, value in strata:
        for is_advanced in (True, False):
            group = [
                row
                for row in entry_rows
                if row["advanced"] is is_advanced
                and (
                    row["date"] == value
                    if kind == "day"
                    else (
                        row["side"] == value
                        if kind == "side"
                        else row["entry_roles"] == value
                    )
                )
            ]
            if not group:
                continue
            lines.append(
                "| "
                + " | ".join(
                    [
                        value,
                        "advanced" if is_advanced else "failed",
                        str(len(group)),
                        fmt(
                            median_metric(
                                group, "entry_approach_road_retrace_frac"
                            )
                        ),
                        fmt(
                            median_metric(
                                group,
                                "entry_test_zone_winner_net_provision_qty",
                            )
                        ),
                        fmt(
                            median_metric(
                                group, "entry_test_zone_winner_end_qty"
                            )
                        ),
                        fmt(
                            median_metric(
                                group, "prior_material_return_count"
                            )
                        ),
                    ]
                )
                + " |"
            )

    lines.extend(
        [
            "",
            "## Post-Entry Features",
            "",
            "These fields are campaign evidence after entry and must not be credited as entry predictors. The phase currently ends at readvance or root failure, so end-book separation is partly endpoint leakage; use it as a mechanism check until fixed causal checkpoints are replayed.",
            "",
            "| feature | n | advanced median | failed median | AUC |",
            "|---|---:|---:|---:|---:|",
        ]
    )
    for feature, count, pos_med, neg_med, score in metric_table(
        post_rows, POST_ENTRY_FEATURES
    ):
        lines.append(
            f"| {feature} | {count} | {fmt(pos_med)} | {fmt(neg_med)} | {fmt(score)} |"
        )

    lines.extend(
        [
            "",
            "## Fixed Causal Checkpoints",
            "",
            "Only roots still live with valid book state at each checkpoint are compared. Roots already failed are reported as terminal-before-checkpoint rather than assigned post-failure book features.",
            "",
            "| checkpoint | eligible n | terminal before | feature | advanced median | failed median | AUC |",
            "|---|---:|---:|---|---:|---:|---:|",
        ]
    )
    for checkpoint_ms in CHECKPOINT_MS:
        prefix = f"checkpoint_{checkpoint_ms}ms"
        eligible = [
            row
            for row in rows
            if row.get(f"{prefix}_root_live") is True
            and row.get(f"{prefix}_book_valid") is True
        ]
        terminal = sum(
            row.get(f"{prefix}_root_live") is False for row in rows
        )
        features = [
            f"{prefix}_favorable_displacement_ticks",
            f"{prefix}_road_remaining_ticks",
            f"{prefix}_winner_net_provision_qty",
            f"{prefix}_winner_end_qty",
            f"{prefix}_backing_end_levels_frac",
        ]
        for feature, count, pos_med, neg_med, score in metric_table(
            eligible, features
        ):
            lines.append(
                "| "
                + " | ".join(
                    [
                        f"{checkpoint_ms / 1000:g}s",
                        str(len(eligible)),
                        str(terminal),
                        feature.removeprefix(f"{prefix}_"),
                        fmt(pos_med),
                        fmt(neg_med),
                        fmt(score),
                    ]
                )
                + " |"
            )

    fixtures = {
        ("2026-07-23", "111"),
        ("2026-07-23", "208"),
        ("2026-07-24", "34"),
        ("2026-07-24", "84"),
        ("2026-07-24", "89"),
        ("2026-07-24", "102"),
    }
    lines.extend(
        [
            "",
            "## Named Fixtures",
            "",
            "| date/root | side | outcome | road retrace | test-zone adverse qty | test-zone efficiency | test-zone provision | test-zone end backing | post-entry resolution |",
            "|---|---|---|---:|---:|---:|---:|---:|---|",
        ]
    )
    for row in rows:
        if (row["date"], row["root_id"]) not in fixtures:
            continue
        lines.append(
            "| "
            + " | ".join(
                [
                    f"{row['date']}/{row['root_id']}",
                    row["side"],
                    row["outcome"],
                    fmt(row.get("entry_approach_road_retrace_frac")),
                    fmt(row.get("entry_test_zone_adverse_trade_qty")),
                    fmt(row.get("entry_test_zone_adverse_ticks_per_10_qty")),
                    fmt(row.get("entry_test_zone_winner_net_provision_qty")),
                    fmt(row.get("entry_test_zone_backing_end_levels_frac")),
                    row.get("entry_resolution", ""),
                ]
            )
            + " |"
        )

    lines.extend(
        [
            "",
            "## Replay Health",
            "",
        ]
    )
    for day, day_stats in sorted(stats.items()):
        lines.append(
            f"- {day}: "
            + ", ".join(f"{key}={value}" for key, value in day_stats.items())
        )
    lines.extend(
        [
            "",
            "## Interpretation Limits",
            "",
            "- Raw quote removals are not called cancellations one-for-one. Quote ids can replace/move, crossed levels are mechanically evicted, and visible size can be replenished within a trade. Net provision uses book conservation plus aggressor tape; gross add/remove remains descriptive.",
            "- `price extreme -> first retrace` is causal, but the chosen extension/retrace sizes are study definitions, not implementation thresholds.",
            "- Road features condition on a meaningful return. Fly-away events are retained in `events.csv` but excluded from the return-feature table.",
            "- The entry-aligned approach is the return containing EAR's actual first decision; this can differ from the conversion's first material pullback.",
            "- Entry and checkpoint tables exclude phases opened or closed while the reconstructed book was invalid.",
            "- `per_level.csv` is the audit surface for every fixed-price claim.",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lineage", type=Path, default=DEFAULT_LINEAGE)
    parser.add_argument("--symbol-dir", default="NQU6")
    parser.add_argument("--start-date", default=DEFAULT_START)
    parser.add_argument("--end-date", default=DEFAULT_END)
    parser.add_argument("--population", choices=("traded", "all"), default="traded")
    parser.add_argument("--extension-ticks", type=int, default=4)
    parser.add_argument("--retrace-ticks", type=int, default=4)
    parser.add_argument("--retrace-fraction", type=float, default=0.25)
    parser.add_argument("--test-zone-ticks", type=int, default=8)
    parser.add_argument("--step-ticks", type=int, default=8)
    parser.add_argument("--lifecycle-seconds", type=float, default=300.0)
    parser.add_argument("--return-seconds", type=float, default=120.0)
    parser.add_argument("--batch-files", type=int, default=40)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    if args.extension_ticks <= 0 or args.retrace_ticks <= 0:
        raise ValueError("extension and retrace ticks must be positive")
    if not 0 < args.retrace_fraction <= 1:
        raise ValueError("retrace fraction must be in (0, 1]")
    if args.test_zone_ticks <= 0:
        raise ValueError("test zone ticks must be positive")
    if args.step_ticks <= 0:
        raise ValueError("step ticks must be positive")
    output = args.output or (
        OUTPUT_ROOT
        / (
            "direct_conversion_auction_road_"
            f"{args.start_date.replace('-', '')}_{args.end_date.replace('-', '')}"
        )
    )

    studies = load_studies(
        args.lineage, args.start_date, args.end_date, args.population
    )
    by_day: dict[str, list[Study]] = defaultdict(list)
    for study in studies:
        by_day[study.date].append(study)

    replay_stats: dict[str, dict[str, int]] = {}
    for day, day_studies in sorted(by_day.items()):
        start = datetime.fromisoformat(day).replace(tzinfo=NY)
        end = start + timedelta(days=1)
        ticks_frame = load_capture_window(
            "ticks", args.symbol_dir, start, end, tick_columns()
        )
        times = [int(value) for value in ticks_frame["timestamp_us"].to_list()]
        ticks = [
            price_to_tick(float(value)) for value in ticks_frame["price"].to_list()
        ]
        sizes = [float(value) for value in ticks_frame["size"].to_list()]
        signs = [int(value) for value in ticks_frame["aggressor_sign"].to_list()]

        for study in day_studies:
            segment_lifecycle(
                study,
                times,
                ticks,
                sizes,
                signs,
                args.extension_ticks,
                args.retrace_ticks,
                args.retrace_fraction,
                args.lifecycle_seconds,
                args.return_seconds,
            )
            segment_entry_test(
                study,
                times,
                ticks,
                sizes,
                signs,
                args.extension_ticks,
                args.test_zone_ticks,
                args.step_ticks,
                args.return_seconds,
            )
        phases = [
            phase for study in day_studies for phase in study.phases.values()
        ]
        replay_stats[day] = replay_day(
            args.symbol_dir, day, phases, args.batch_files
        )

    rows = [study_row(study, args.population) for study in studies]
    details = level_rows(studies)
    write_csv(output / "events.csv", rows)
    write_csv(output / "per_level.csv", details)
    report = build_report(
        rows,
        replay_stats,
        args.start_date,
        args.end_date,
        args.population,
        args.extension_ticks,
        args.retrace_ticks,
        args.retrace_fraction,
    )
    output.mkdir(parents=True, exist_ok=True)
    (output / "findings.md").write_text(report, encoding="utf-8")
    print(f"wrote {len(rows)} events and {len(details)} price-phase rows to {output}")


if __name__ == "__main__":
    main()
