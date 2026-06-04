"""Research probe for failure zones outside grey/no-owner envelopes.

This is not indicator code. It layers a trade-review object on top of
ownership-band transitions:

- grey zones come from nearby two-sided ownership failures
- failure zones come from demand/supply ownership appearing at fresh extremes
  outside those grey zones
- optional reversal-failure output finds consumed continuation-side evidence at
  extremes, including repairs back into grey

The output is deliberately structural. It says where continuation failed; it
does not decide whether a given position should flatten, add, or ignore it.
"""

from __future__ import annotations

import argparse
from collections import Counter, deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from ownership_bands_probe import (
    FailureCluster,
    OwnershipProbe,
    Transition,
    range_label,
    side_label,
)
from replay_levelledger import (
    EVENT_Z_THRESHOLD,
    abbrev,
    build_sample,
    load_snapshots,
    ny_hms,
    parse_ny,
    snapshot_timing_summary,
)


@dataclass
class GreyEnvelope(FailureCluster):
    id: int = 0

    @property
    def is_two_sided(self) -> bool:
        return self.demand_fails > 0 and self.supply_fails > 0


@dataclass
class PricePoint:
    ts: datetime
    mid_tick: int


@dataclass
class FailureZone:
    id: int
    direction: str
    owner_side: str
    min_tick: int
    max_tick: int
    formed_ts: datetime
    last_update_ts: datetime
    current_mid_tick: int
    rolling_extreme_tick: int
    grey_id: int | None
    grey_min_tick: int | None
    grey_max_tick: int | None
    triggers: int = 1
    consumed_triggers: int = 0
    lean_triggers: int = 0
    score: float = 0.0
    event_count: int = 0
    max_abs_z: float = 0.0
    notes: list[str] = field(default_factory=list)
    left_ts: datetime | None = None
    first_retest_ts: datetime | None = None
    last_retest_ts: datetime | None = None
    retests: int = 0
    held_ts: datetime | None = None
    invalidated_ts: datetime | None = None
    invalidated_tick: int | None = None
    nearest_after_left_tick: int | None = None

    @property
    def is_low_fail(self) -> bool:
        return self.direction == "LOW_FAIL"

    @property
    def status(self) -> str:
        if self.invalidated_ts is not None:
            if self.held_ts is not None and self.held_ts < self.invalidated_ts:
                return "held_then_invalid"
            if self.left_ts is not None and self.left_ts < self.invalidated_ts:
                return "left_then_invalid"
            return "invalidated"
        if self.held_ts is not None:
            return "held"
        if self.retests > 0:
            return "retested"
        if self.left_ts is not None:
            return "left_unretested"
        return "forming"


@dataclass
class ReversalFail:
    id: int
    direction: str
    owner_side: str
    continuation_side: str
    min_tick: int
    max_tick: int
    repair_tick: int
    formed_ts: datetime
    rolling_extreme_tick: int
    grey_id: int | None
    grey_min_tick: int | None
    grey_max_tick: int | None
    grey_relation: str
    score: float
    event_count: int
    max_abs_z: float
    note: str
    first_retest_ts: datetime | None = None
    last_retest_ts: datetime | None = None
    retests: int = 0
    held_ts: datetime | None = None
    invalidated_ts: datetime | None = None
    invalidated_tick: int | None = None

    @property
    def is_low_fail(self) -> bool:
        return self.direction == "LOW_REV_FAIL"

    @property
    def status(self) -> str:
        if self.invalidated_ts is not None:
            if self.held_ts is not None and self.held_ts < self.invalidated_ts:
                return "repair_then_invalid"
            return "invalidated"
        if self.held_ts is not None:
            return "held"
        if self.retests > 0:
            return "retested"
        return "repaired"


class RollingExtremes:
    def __init__(
        self,
        points: list[PricePoint],
        lookback_sec: int,
        reset_ts: datetime | None,
    ) -> None:
        self.points = points
        self.lookback = timedelta(seconds=lookback_sec)
        self.reset_ts = reset_ts
        self.index = 0
        self.window: deque[PricePoint] = deque()

    def advance_to(self, ts: datetime) -> None:
        while self.index < len(self.points) and self.points[self.index].ts <= ts:
            if self.reset_ts is None or self.points[self.index].ts >= self.reset_ts:
                self.window.append(self.points[self.index])
            self.index += 1

        cutoff = ts - self.lookback
        while self.window and self.window[0].ts < cutoff:
            self.window.popleft()

    def low(self) -> int | None:
        if not self.window:
            return None
        return min(point.mid_tick for point in self.window)

    def high(self) -> int | None:
        if not self.window:
            return None
        return max(point.mid_tick for point in self.window)


class GreyTracker:
    def __init__(
        self,
        contested_sec: int,
        proximity_ticks: int,
        span_ticks: int,
        min_fails: int,
        ttl_sec: int,
    ) -> None:
        self.contested_sec = contested_sec
        self.proximity_ticks = proximity_ticks
        self.span_ticks = span_ticks
        self.min_fails = min_fails
        self.ttl_sec = ttl_sec
        self.next_id = 1
        self.envelopes: list[GreyEnvelope] = []

    def add_fail(self, tr: Transition) -> None:
        matched: GreyEnvelope | None = None
        for envelope in self.envelopes:
            if (tr.ts - envelope.end_ts).total_seconds() > self.contested_sec:
                continue
            if tr.max_tick < envelope.min_tick - self.proximity_ticks:
                continue
            if tr.min_tick > envelope.max_tick + self.proximity_ticks:
                continue
            next_min = min(envelope.min_tick, tr.min_tick)
            next_max = max(envelope.max_tick, tr.max_tick)
            if next_max - next_min > self.span_ticks:
                continue
            matched = envelope
            break

        if matched is None:
            matched = GreyEnvelope(
                id=self.next_id,
                start_ts=tr.ts,
                end_ts=tr.ts,
                min_tick=tr.min_tick,
                max_tick=tr.max_tick,
            )
            self.next_id += 1
            self.envelopes.append(matched)
        else:
            matched.end_ts = tr.ts
            matched.min_tick = min(matched.min_tick, tr.min_tick)
            matched.max_tick = max(matched.max_tick, tr.max_tick)

        if tr.side == "demand":
            matched.demand_fails += 1
        else:
            matched.supply_fails += 1
        matched.score += tr.score

    def active(self, ts: datetime) -> list[GreyEnvelope]:
        active: list[GreyEnvelope] = []
        for envelope in self.envelopes:
            if not envelope.is_two_sided:
                continue
            if envelope.total_fails < self.min_fails:
                continue
            if (ts - envelope.end_ts).total_seconds() > self.ttl_sec:
                continue
            active.append(envelope)
        return active

def transition_direction(tr: Transition, include_lean: bool) -> str | None:
    if tr.action == "CONSUMED":
        if tr.side == "demand" and tr.source == "supply_consumed":
            return "LOW_FAIL"
        if tr.side == "supply" and tr.source == "demand_consumed":
            return "HIGH_FAIL"
        return None

    if include_lean and tr.action == "OWNED":
        if tr.side == "demand" and tr.source == "demand_lean":
            return "LOW_FAIL"
        if tr.side == "supply" and tr.source == "supply_lean":
            return "HIGH_FAIL"
    return None


def reversal_direction(tr: Transition) -> str | None:
    if tr.action != "CONSUMED":
        return None
    if tr.side == "demand" and tr.source == "supply_consumed":
        return "LOW_REV_FAIL"
    if tr.side == "supply" and tr.source == "demand_consumed":
        return "HIGH_REV_FAIL"
    return None


def fail_direction(direction: str) -> str:
    if direction in ("LOW_FAIL", "LOW_REV_FAIL"):
        return "LOW_FAIL"
    return "HIGH_FAIL"


def consumed_repair_confirmed(direction: str, tr: Transition, repair_ticks: int) -> bool:
    if direction == "LOW_REV_FAIL":
        return tr.current_mid_tick >= tr.max_tick + repair_ticks
    return tr.current_mid_tick <= tr.min_tick - repair_ticks


def grey_relation(
    direction: str,
    min_tick: int,
    max_tick: int,
    grey: GreyEnvelope | None,
) -> str:
    if grey is None:
        return "none"
    if max_tick >= grey.min_tick and min_tick <= grey.max_tick:
        return "into_grey"
    if direction in ("LOW_FAIL", "LOW_REV_FAIL") and max_tick < grey.min_tick:
        return "below_grey"
    if direction in ("HIGH_FAIL", "HIGH_REV_FAIL") and min_tick > grey.max_tick:
        return "above_grey"
    return "near_grey"


def is_near_fresh_extreme(
    direction: str,
    tr: Transition,
    rolling_low: int | None,
    rolling_high: int | None,
    buffer_ticks: int,
) -> tuple[bool, int | None]:
    if direction == "LOW_FAIL":
        if rolling_low is None:
            return False, None
        return tr.min_tick <= rolling_low + buffer_ticks, rolling_low
    if rolling_high is None:
        return False, None
    return tr.max_tick >= rolling_high - buffer_ticks, rolling_high


def overlaps_grey(
    direction: str,
    min_tick: int,
    max_tick: int,
    active_greys: list[GreyEnvelope],
    outside_ticks: int,
) -> tuple[bool, GreyEnvelope | None]:
    if not active_greys:
        return False, None

    containing = [
        env for env in active_greys
        if max_tick >= env.min_tick - outside_ticks
        and min_tick <= env.max_tick + outside_ticks
    ]
    if containing:
        return True, min(containing, key=lambda env: abs(env.max_tick - env.min_tick))

    if direction == "LOW_FAIL":
        lower_refs = [env for env in active_greys if max_tick < env.min_tick - outside_ticks]
        if lower_refs:
            return False, min(lower_refs, key=lambda env: env.min_tick - max_tick)
    else:
        upper_refs = [env for env in active_greys if min_tick > env.max_tick + outside_ticks]
        if upper_refs:
            return False, min(upper_refs, key=lambda env: min_tick - env.max_tick)

    return False, min(
        active_greys,
        key=lambda env: min(
            abs(min_tick - env.max_tick),
            abs(max_tick - env.min_tick),
        ),
    )


def zone_bounds(direction: str, tr: Transition) -> tuple[int, int]:
    if tr.action != "CONSUMED":
        return tr.min_tick, tr.max_tick
    if direction == "LOW_FAIL":
        return tr.min_tick, max(tr.max_tick, tr.current_mid_tick)
    return min(tr.min_tick, tr.current_mid_tick), tr.max_tick


def merge_target(
    zones: list[FailureZone],
    direction: str,
    tr: Transition,
    min_tick: int,
    max_tick: int,
    merge_sec: int,
    merge_ticks: int,
    split_extension_ticks: int,
) -> FailureZone | None:
    for zone in reversed(zones):
        if zone.direction != direction:
            continue
        if direction == "LOW_FAIL" and min_tick < zone.min_tick - split_extension_ticks:
            continue
        if direction == "HIGH_FAIL" and max_tick > zone.max_tick + split_extension_ticks:
            continue
        if (max_tick < zone.min_tick - merge_ticks) or (min_tick > zone.max_tick + merge_ticks):
            continue
        if (tr.ts - zone.last_update_ts).total_seconds() > merge_sec:
            continue
        return zone
    return None


def add_trigger(zone: FailureZone, tr: Transition, min_tick: int, max_tick: int) -> None:
    zone.min_tick = min(zone.min_tick, min_tick)
    zone.max_tick = max(zone.max_tick, max_tick)
    zone.last_update_ts = tr.ts
    zone.current_mid_tick = tr.current_mid_tick
    zone.triggers += 1
    zone.score += tr.score
    zone.event_count += tr.event_count
    zone.max_abs_z = max(zone.max_abs_z, tr.max_abs_z)
    if tr.action == "CONSUMED":
        zone.consumed_triggers += 1
    else:
        zone.lean_triggers += 1
    zone.notes.append(trigger_note(tr))


def trigger_note(tr: Transition) -> str:
    return (
        f"{ny_hms(tr.ts)} {tr.action}:{tr.source} "
        f"{range_label(tr.min_tick, tr.max_tick)} "
        f"cur={abbrev(tr.current_mid_tick)}"
    )


def detect_failure_zones(
    probe: OwnershipProbe,
    points: list[PricePoint],
    window_start: datetime,
    window_end: datetime,
    *,
    include_lean: bool,
    extreme_lookback_sec: int,
    extreme_reset_ts: datetime | None,
    extreme_buffer_ticks: int,
    outside_ticks: int,
    merge_sec: int,
    merge_ticks: int,
    split_extension_ticks: int,
    contested_sec: int,
    contested_proximity_ticks: int,
    contested_span_ticks: int,
    contested_min_fails: int,
    grey_ttl_sec: int,
    debug_candidates: bool,
) -> tuple[list[FailureZone], Counter[str]]:
    tracker = GreyTracker(
        contested_sec=contested_sec,
        proximity_ticks=contested_proximity_ticks,
        span_ticks=contested_span_ticks,
        min_fails=contested_min_fails,
        ttl_sec=grey_ttl_sec,
    )
    extremes = RollingExtremes(
        points,
        lookback_sec=extreme_lookback_sec,
        reset_ts=extreme_reset_ts,
    )
    zones: list[FailureZone] = []
    reject_counts: Counter[str] = Counter()

    transitions = sorted(probe.transitions, key=lambda tr: tr.ts)
    for tr in transitions:
        extremes.advance_to(tr.ts)

        if tr.action == "FAIL":
            tracker.add_fail(tr)
            continue

        direction = transition_direction(tr, include_lean)
        if direction is None:
            continue

        rolling_low = extremes.low()
        rolling_high = extremes.high()
        is_extreme, rolling_extreme = is_near_fresh_extreme(
            direction,
            tr,
            rolling_low,
            rolling_high,
            extreme_buffer_ticks,
        )
        if not is_extreme or rolling_extreme is None:
            reject_counts["not_fresh_extreme"] += 1
            if debug_candidates and window_start <= tr.ts <= window_end:
                print(
                    "DEBUG reject not_fresh "
                    f"{ny_hms(tr.ts)} {direction} {tr.action}:{tr.source} "
                    f"{range_label(tr.min_tick, tr.max_tick)} "
                    f"cur={abbrev(tr.current_mid_tick)} "
                    f"low={abbrev(rolling_low) if rolling_low is not None else '-'} "
                    f"high={abbrev(rolling_high) if rolling_high is not None else '-'}"
                )
            continue

        min_tick, max_tick = zone_bounds(direction, tr)
        active_greys = tracker.active(tr.ts)
        in_grey, grey = overlaps_grey(
            direction,
            min_tick,
            max_tick,
            active_greys,
            outside_ticks,
        )
        if in_grey:
            reject_counts["inside_active_grey"] += 1
            if debug_candidates and window_start <= tr.ts <= window_end:
                print(
                    "DEBUG reject in_grey "
                    f"{ny_hms(tr.ts)} {direction} {tr.action}:{tr.source} "
                    f"{range_label(tr.min_tick, tr.max_tick)} "
                    f"grey={range_label(grey.min_tick, grey.max_tick) if grey else '-'}"
                )
            continue

        target = merge_target(
            zones,
            direction,
            tr,
            min_tick,
            max_tick,
            merge_sec,
            merge_ticks,
            split_extension_ticks,
        )
        if target is not None:
            add_trigger(target, tr, min_tick, max_tick)
            if debug_candidates and window_start <= tr.ts <= window_end:
                print(
                    "DEBUG merge "
                    f"{ny_hms(tr.ts)} {direction} {tr.action}:{tr.source} "
                    f"{range_label(tr.min_tick, tr.max_tick)} "
                    f"into zone#{target.id}"
                )
            continue

        zone = FailureZone(
            id=len(zones) + 1,
            direction=direction,
            owner_side=tr.side,
            min_tick=min_tick,
            max_tick=max_tick,
            formed_ts=tr.ts,
            last_update_ts=tr.ts,
            current_mid_tick=tr.current_mid_tick,
            rolling_extreme_tick=rolling_extreme,
            grey_id=grey.id if grey is not None else None,
            grey_min_tick=grey.min_tick if grey is not None else None,
            grey_max_tick=grey.max_tick if grey is not None else None,
            consumed_triggers=1 if tr.action == "CONSUMED" else 0,
            lean_triggers=1 if tr.action == "OWNED" else 0,
            score=tr.score,
            event_count=tr.event_count,
            max_abs_z=tr.max_abs_z,
            notes=[trigger_note(tr)],
        )
        if window_start <= zone.formed_ts <= window_end:
            zones.append(zone)
            if debug_candidates:
                print(
                    "DEBUG accept "
                    f"{ny_hms(tr.ts)} {direction} {tr.action}:{tr.source} "
                    f"{range_label(tr.min_tick, tr.max_tick)} "
                    f"low={abbrev(rolling_low) if rolling_low is not None else '-'} "
                    f"high={abbrev(rolling_high) if rolling_high is not None else '-'}"
                )
        else:
            reject_counts["outside_print_window"] += 1

    return zones, reject_counts


def detect_reversal_fails(
    probe: OwnershipProbe,
    points: list[PricePoint],
    window_start: datetime,
    window_end: datetime,
    *,
    extreme_lookback_sec: int,
    extreme_reset_ts: datetime | None,
    extreme_buffer_ticks: int,
    repair_ticks: int,
    require_grey: bool,
    contested_sec: int,
    contested_proximity_ticks: int,
    contested_span_ticks: int,
    contested_min_fails: int,
    grey_ttl_sec: int,
    debug_candidates: bool,
) -> tuple[list[ReversalFail], Counter[str]]:
    tracker = GreyTracker(
        contested_sec=contested_sec,
        proximity_ticks=contested_proximity_ticks,
        span_ticks=contested_span_ticks,
        min_fails=contested_min_fails,
        ttl_sec=grey_ttl_sec,
    )
    extremes = RollingExtremes(
        points,
        lookback_sec=extreme_lookback_sec,
        reset_ts=extreme_reset_ts,
    )
    rev_fails: list[ReversalFail] = []
    reject_counts: Counter[str] = Counter()

    transitions = sorted(probe.transitions, key=lambda tr: tr.ts)
    for tr in transitions:
        extremes.advance_to(tr.ts)

        if tr.action == "FAIL":
            tracker.add_fail(tr)
            continue

        direction = reversal_direction(tr)
        if direction is None:
            continue

        if not consumed_repair_confirmed(direction, tr, repair_ticks):
            reject_counts["weak_repair_move"] += 1
            if debug_candidates and window_start <= tr.ts <= window_end:
                print(
                    "DEBUG rev reject weak_repair "
                    f"{ny_hms(tr.ts)} {direction} {tr.action}:{tr.source} "
                    f"{range_label(tr.min_tick, tr.max_tick)} "
                    f"cur={abbrev(tr.current_mid_tick)}"
                )
            continue

        rolling_low = extremes.low()
        rolling_high = extremes.high()
        is_extreme, rolling_extreme = is_near_fresh_extreme(
            fail_direction(direction),
            tr,
            rolling_low,
            rolling_high,
            extreme_buffer_ticks,
        )
        if not is_extreme or rolling_extreme is None:
            reject_counts["not_fresh_extreme"] += 1
            if debug_candidates and window_start <= tr.ts <= window_end:
                print(
                    "DEBUG rev reject not_fresh "
                    f"{ny_hms(tr.ts)} {direction} {tr.action}:{tr.source} "
                    f"{range_label(tr.min_tick, tr.max_tick)} "
                    f"cur={abbrev(tr.current_mid_tick)} "
                    f"low={abbrev(rolling_low) if rolling_low is not None else '-'} "
                    f"high={abbrev(rolling_high) if rolling_high is not None else '-'}"
                )
            continue

        repair_min_tick, repair_max_tick = zone_bounds(fail_direction(direction), tr)
        active_greys = tracker.active(tr.ts)
        _, grey = overlaps_grey(
            fail_direction(direction),
            repair_min_tick,
            repair_max_tick,
            active_greys,
            outside_ticks=0,
        )
        relation = grey_relation(direction, repair_min_tick, repair_max_tick, grey)
        if require_grey and grey is None:
            reject_counts["no_active_grey"] += 1
            continue

        if tr.ts < window_start or tr.ts > window_end:
            reject_counts["outside_print_window"] += 1
            continue

        rev_fails.append(
            ReversalFail(
                id=len(rev_fails) + 1,
                direction=direction,
                owner_side=tr.side,
                continuation_side="supply" if direction == "LOW_REV_FAIL" else "demand",
                min_tick=tr.min_tick,
                max_tick=tr.max_tick,
                repair_tick=tr.current_mid_tick,
                formed_ts=tr.ts,
                rolling_extreme_tick=rolling_extreme,
                grey_id=grey.id if grey is not None else None,
                grey_min_tick=grey.min_tick if grey is not None else None,
                grey_max_tick=grey.max_tick if grey is not None else None,
                grey_relation=relation,
                score=tr.score,
                event_count=tr.event_count,
                max_abs_z=tr.max_abs_z,
                note=trigger_note(tr),
            )
        )
        if debug_candidates:
            print(
                "DEBUG rev accept "
                f"{ny_hms(tr.ts)} {direction} {tr.action}:{tr.source} "
                f"{range_label(tr.min_tick, tr.max_tick)} "
                f"repair={abbrev(tr.current_mid_tick)} "
                f"relation={relation}"
            )

    return rev_fails, reject_counts


def classify_revisits(
    zones: list[FailureZone],
    points: list[PricePoint],
    *,
    away_ticks: int,
    invalidate_ticks: int,
    near_ticks: int,
) -> None:
    for zone in zones:
        in_retest = False
        for point in points:
            if point.ts <= zone.last_update_ts:
                continue

            mid = point.mid_tick
            if zone.invalidated_ts is None:
                if zone.is_low_fail and mid <= zone.min_tick - invalidate_ticks:
                    zone.invalidated_ts = point.ts
                    zone.invalidated_tick = mid
                elif not zone.is_low_fail and mid >= zone.max_tick + invalidate_ticks:
                    zone.invalidated_ts = point.ts
                    zone.invalidated_tick = mid

            if zone.left_ts is None:
                if zone.is_low_fail and mid >= zone.max_tick + away_ticks:
                    zone.left_ts = point.ts
                elif not zone.is_low_fail and mid <= zone.min_tick - away_ticks:
                    zone.left_ts = point.ts
                continue

            if zone.is_low_fail:
                if zone.nearest_after_left_tick is None or mid < zone.nearest_after_left_tick:
                    zone.nearest_after_left_tick = mid
                inside = zone.min_tick <= mid <= zone.max_tick
                moved_away = mid >= zone.max_tick + away_ticks
                near = mid <= zone.max_tick + near_ticks
            else:
                if zone.nearest_after_left_tick is None or mid > zone.nearest_after_left_tick:
                    zone.nearest_after_left_tick = mid
                inside = zone.min_tick <= mid <= zone.max_tick
                moved_away = mid <= zone.min_tick - away_ticks
                near = mid >= zone.min_tick - near_ticks

            if inside and not in_retest:
                zone.retests += 1
                zone.first_retest_ts = zone.first_retest_ts or point.ts
                zone.last_retest_ts = point.ts
                in_retest = True
                continue

            if in_retest and moved_away and zone.invalidated_ts is None:
                zone.held_ts = zone.held_ts or point.ts
                in_retest = False
                continue

            if not inside and not near:
                in_retest = False


def classify_reversal_fails(
    rev_fails: list[ReversalFail],
    points: list[PricePoint],
    *,
    away_ticks: int,
    invalidate_ticks: int,
    near_ticks: int,
) -> None:
    for rev in rev_fails:
        in_retest = False
        for point in points:
            if point.ts <= rev.formed_ts:
                continue

            mid = point.mid_tick
            if rev.invalidated_ts is None:
                if rev.is_low_fail and mid <= rev.min_tick - invalidate_ticks:
                    rev.invalidated_ts = point.ts
                    rev.invalidated_tick = mid
                elif not rev.is_low_fail and mid >= rev.max_tick + invalidate_ticks:
                    rev.invalidated_ts = point.ts
                    rev.invalidated_tick = mid

            if rev.is_low_fail:
                inside = rev.min_tick <= mid <= rev.max_tick
                moved_away = mid >= rev.max_tick + away_ticks
                near = mid <= rev.max_tick + near_ticks
            else:
                inside = rev.min_tick <= mid <= rev.max_tick
                moved_away = mid <= rev.min_tick - away_ticks
                near = mid >= rev.min_tick - near_ticks

            if inside and not in_retest:
                rev.retests += 1
                rev.first_retest_ts = rev.first_retest_ts or point.ts
                rev.last_retest_ts = point.ts
                in_retest = True
                continue

            if in_retest and moved_away and rev.invalidated_ts is None:
                rev.held_ts = rev.held_ts or point.ts
                in_retest = False
                continue

            if not inside and not near:
                in_retest = False


def make_probe(args: argparse.Namespace, date: str, window_start: datetime, window_end: datetime) -> tuple[OwnershipProbe, list[PricePoint], str]:
    replay_start = window_start - timedelta(minutes=args.warmup_min)
    snap = load_snapshots(args.symbol_dir, replay_start, window_end)
    first_snap, last_snap, duplicate_count, gaps = snapshot_timing_summary(
        snap,
        args.gap_threshold_sec,
    )

    probe = OwnershipProbe(
        event_z=args.event_z,
        cluster_min_events=args.cluster_min_events,
        cluster_ticks=args.cluster_ticks,
        cluster_sec=args.cluster_sec,
        cluster_min_score=args.cluster_min_score,
        confirm_ticks=args.confirm_ticks,
        confirm_sec=args.confirm_sec,
        test_buffer_ticks=args.test_buffer_ticks,
        fail_buffer_ticks=args.fail_buffer_ticks,
        fail_confirm_ticks=args.fail_confirm_ticks,
        fail_sec=args.fail_sec,
        hold_confirm_ticks=args.hold_confirm_ticks,
    )

    points: list[PricePoint] = []
    for row in snap.iter_rows(named=True):
        sample = build_sample(row)
        probe.on_sample(sample)
        points.append(PricePoint(sample.ts, sample.mid_tick))

    gap_text = f"{len(gaps)} gaps>{args.gap_threshold_sec:g}s" if gaps else f"0 gaps>{args.gap_threshold_sec:g}s"
    summary = (
        f"{date} {args.window} rows={snap.height:,} "
        f"snap={ny_hms(first_snap)}-{ny_hms(last_snap)} "
        f"dups={duplicate_count:,} {gap_text} "
        f"bands={len(probe.bands):,} transitions={len(probe.transitions):,}"
    )
    return probe, points, summary


def grey_label(zone: FailureZone | ReversalFail) -> str:
    if zone.grey_id is None:
        return "none"
    assert zone.grey_min_tick is not None
    assert zone.grey_max_tick is not None
    return f"grey#{zone.grey_id}:{range_label(zone.grey_min_tick, zone.grey_max_tick)}"


def near_label(zone: FailureZone) -> str:
    if zone.nearest_after_left_tick is None:
        return "-"
    return abbrev(zone.nearest_after_left_tick)


def ts_or_dash(ts: datetime | None) -> str:
    return ny_hms(ts) if ts is not None else "-"


def print_zones(date: str, zones: list[FailureZone], rejects: Counter[str], summary: str, print_notes: bool) -> None:
    print(f"\n{summary}")
    print(f"failure_zones={len(zones)} rejected={sum(rejects.values())}")
    if rejects:
        rejected = " ".join(f"{key}={value}" for key, value in sorted(rejects.items()))
        print(f"rejects: {rejected}")
    if not zones:
        print("(none)")
        return

    print(
        "time      type       zone          owner   src C/L  score  "
        "extreme  grey                 status             retests first/last      near"
    )
    for zone in zones:
        src = f"{zone.consumed_triggers}/{zone.lean_triggers}"
        retest = f"{ts_or_dash(zone.first_retest_ts)}/{ts_or_dash(zone.last_retest_ts)}"
        print(
            f"{ny_hms(zone.formed_ts):<8} "
            f"{zone.direction:<10} "
            f"{range_label(zone.min_tick, zone.max_tick):>12} "
            f"{side_label(zone.owner_side):<6} "
            f"{src:>5} "
            f"{zone.score:6.1f} "
            f"{abbrev(zone.rolling_extreme_tick):>7} "
            f"{grey_label(zone):<20} "
            f"{zone.status:<18} "
            f"{zone.retests:>3} "
            f"{retest:<15} "
            f"{near_label(zone):>7}"
        )
        if print_notes:
            for note in zone.notes[:8]:
                print(f"    {note}")
            if len(zone.notes) > 8:
                print(f"    ... {len(zone.notes) - 8} more triggers")


def print_reversal_fails(
    rev_fails: list[ReversalFail],
    rejects: Counter[str],
    print_notes: bool,
) -> None:
    print(f"\nreversal_fails={len(rev_fails)} rejected={sum(rejects.values())}")
    if rejects:
        rejected = " ".join(f"{key}={value}" for key, value in sorted(rejects.items()))
        print(f"rev_rejects: {rejected}")
    if not rev_fails:
        print("(none)")
        return

    print(
        "time      type          evidence      repair owner   cont    score  "
        "extreme  relation   grey                 status             retests first/last"
    )
    for rev in rev_fails:
        retest = f"{ts_or_dash(rev.first_retest_ts)}/{ts_or_dash(rev.last_retest_ts)}"
        print(
            f"{ny_hms(rev.formed_ts):<8} "
            f"{rev.direction:<13} "
            f"{range_label(rev.min_tick, rev.max_tick):>12} "
            f"{abbrev(rev.repair_tick):>7} "
            f"{side_label(rev.owner_side):<6} "
            f"{side_label(rev.continuation_side):<6} "
            f"{rev.score:6.1f} "
            f"{abbrev(rev.rolling_extreme_tick):>7} "
            f"{rev.grey_relation:<10} "
            f"{grey_label(rev):<20} "
            f"{rev.status:<18} "
            f"{rev.retests:>3} "
            f"{retest:<15}"
        )
        if print_notes:
            print(f"    {rev.note}")


def parse_dates(args: argparse.Namespace) -> list[str]:
    dates: list[str] = []
    if args.dates:
        dates.extend(part.strip() for part in args.dates.split(",") if part.strip())
    if args.date:
        dates.extend(args.date)
    if not dates:
        dates = ["2026-06-01", "2026-06-02", "2026-06-03"]
    return dates


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", action="append", help="Session date; repeatable. Overrides/extends --dates.")
    parser.add_argument("--dates", default="", help="Comma-separated session dates.")
    parser.add_argument("--symbol-dir", default="NQM6")
    parser.add_argument("--window", default="09:30-13:15")
    parser.add_argument("--warmup-min", type=int, default=180)
    parser.add_argument("--event-z", type=float, default=EVENT_Z_THRESHOLD)
    parser.add_argument("--cluster-min-events", type=int, default=3)
    parser.add_argument("--cluster-ticks", type=int, default=10)
    parser.add_argument("--cluster-sec", type=int, default=90)
    parser.add_argument("--cluster-min-score", type=float, default=8.0)
    parser.add_argument("--confirm-ticks", type=int, default=8)
    parser.add_argument("--confirm-sec", type=int, default=10)
    parser.add_argument("--test-buffer-ticks", type=int, default=4)
    parser.add_argument("--fail-buffer-ticks", type=int, default=2)
    parser.add_argument("--fail-confirm-ticks", type=int, default=8)
    parser.add_argument("--fail-sec", type=int, default=10)
    parser.add_argument("--hold-confirm-ticks", type=int, default=10)
    parser.add_argument("--gap-threshold-sec", type=float, default=5.0)
    parser.add_argument("--include-lean", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--extreme-lookback-sec", type=int, default=45 * 60)
    parser.add_argument("--include-warmup-extremes", action="store_true")
    parser.add_argument("--extreme-buffer-ticks", type=int, default=320)
    parser.add_argument("--outside-ticks", type=int, default=0)
    parser.add_argument("--merge-sec", type=int, default=12 * 60)
    parser.add_argument("--merge-ticks", type=int, default=96)
    parser.add_argument("--split-extension-ticks", type=int, default=96)
    parser.add_argument("--contested-sec", type=int, default=20 * 60)
    parser.add_argument("--contested-proximity-ticks", type=int, default=80)
    parser.add_argument("--contested-span-ticks", type=int, default=240)
    parser.add_argument("--contested-min-fails", type=int, default=4)
    parser.add_argument("--grey-ttl-sec", type=int, default=25 * 60)
    parser.add_argument("--away-ticks", type=int, default=24)
    parser.add_argument("--invalidate-ticks", type=int, default=8)
    parser.add_argument("--near-ticks", type=int, default=12)
    parser.add_argument("--show-rev-fails", action="store_true")
    parser.add_argument("--only-rev-fails", action="store_true")
    parser.add_argument("--rev-extreme-buffer-ticks", type=int, default=96)
    parser.add_argument("--rev-repair-ticks", type=int, default=24)
    parser.add_argument("--rev-require-grey", action="store_true")
    parser.add_argument("--rev-survivors-only", action="store_true")
    parser.add_argument("--print-notes", action="store_true")
    parser.add_argument("--debug-candidates", action="store_true")
    args = parser.parse_args()

    start_s, end_s = args.window.split("-", 1)
    total_counts: Counter[str] = Counter()

    for date in parse_dates(args):
        window_start = parse_ny(date, start_s)
        window_end = parse_ny(date, end_s)
        probe, points, summary = make_probe(args, date, window_start, window_end)
        if not args.only_rev_fails:
            zones, rejects = detect_failure_zones(
                probe,
                points,
                window_start,
                window_end,
                include_lean=args.include_lean,
                extreme_lookback_sec=args.extreme_lookback_sec,
                extreme_reset_ts=None if args.include_warmup_extremes else window_start,
                extreme_buffer_ticks=args.extreme_buffer_ticks,
                outside_ticks=args.outside_ticks,
                merge_sec=args.merge_sec,
                merge_ticks=args.merge_ticks,
                split_extension_ticks=args.split_extension_ticks,
                contested_sec=args.contested_sec,
                contested_proximity_ticks=args.contested_proximity_ticks,
                contested_span_ticks=args.contested_span_ticks,
                contested_min_fails=args.contested_min_fails,
                grey_ttl_sec=args.grey_ttl_sec,
                debug_candidates=args.debug_candidates,
            )
            classify_revisits(
                zones,
                points,
                away_ticks=args.away_ticks,
                invalidate_ticks=args.invalidate_ticks,
                near_ticks=args.near_ticks,
            )
            total_counts.update(zone.status for zone in zones)
            print_zones(date, zones, rejects, summary, args.print_notes)
        else:
            print(f"\n{summary}")

        if args.show_rev_fails or args.only_rev_fails:
            rev_fails, rev_rejects = detect_reversal_fails(
                probe,
                points,
                window_start,
                window_end,
                extreme_lookback_sec=args.extreme_lookback_sec,
                extreme_reset_ts=None if args.include_warmup_extremes else window_start,
                extreme_buffer_ticks=args.rev_extreme_buffer_ticks,
                repair_ticks=args.rev_repair_ticks,
                require_grey=args.rev_require_grey,
                contested_sec=args.contested_sec,
                contested_proximity_ticks=args.contested_proximity_ticks,
                contested_span_ticks=args.contested_span_ticks,
                contested_min_fails=args.contested_min_fails,
                grey_ttl_sec=args.grey_ttl_sec,
                debug_candidates=args.debug_candidates,
            )
            classify_reversal_fails(
                rev_fails,
                points,
                away_ticks=args.away_ticks,
                invalidate_ticks=args.invalidate_ticks,
                near_ticks=args.near_ticks,
            )
            if args.rev_survivors_only:
                rev_fails = [
                    rev for rev in rev_fails
                    if rev.invalidated_ts is None
                    and rev.status != "repair_then_invalid"
                ]
            total_counts.update(rev.status for rev in rev_fails)
            print_reversal_fails(rev_fails, rev_rejects, args.print_notes)

    if total_counts:
        print("\nAll dates status counts:")
        for status, count in sorted(total_counts.items()):
            print(f"{status:<15} {count}")


if __name__ == "__main__":
    main()
