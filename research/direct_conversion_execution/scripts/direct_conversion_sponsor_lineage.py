"""Classify direct conversions by sponsor-lineage progression.

The target is structural rather than a fixed favorable/adverse price horizon.
For every EAR ``Consumed`` rail, this probe asks which ownership event occurs
first:

* a new same-side rail owns fully beyond it in the favorable direction;
* the conversion rail itself fails;
* the nearest older same-side protection behind it fails.

It also isolates the mixed case that matters to campaign management: a
favorable successor is promoted, then that child fails while the consumed
parent remains live.  That is a child-quality/promotion problem, not necessarily
failure of the direct conversion that established the parent campaign.

The population includes every consumed rail in the runtime log and marks the
subset referenced by accepted EAR DirectConversion orders.
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from _paths import OUTPUT_ROOT

NY = ZoneInfo("America/New_York")
UTC = ZoneInfo("UTC")
TICK_SIZE = 0.25
DEFAULT_EVENTS = Path.home() / "Documents" / "ExecAssistantRuntime" / "events.jsonl"
ENTRY_REASONS = {"direct_conversion", "direct_conversion_retest"}


def parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def et_text(ts: datetime | None) -> str:
    return ts.astimezone(NY).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3] if ts else ""


def elapsed_s(start: datetime | None, end: datetime | None) -> float | str:
    if start is None or end is None or end < start:
        return ""
    return round((end - start).total_seconds(), 3)


def as_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


@dataclass
class Rail:
    session_id: int
    band_id: int
    owned_utc: datetime
    side: str
    source: str
    lo_tick: int
    hi_tick: int
    score: float | None = None
    history: list[tuple[datetime, str]] = field(default_factory=list)

    @property
    def date(self) -> str:
        return self.owned_utc.astimezone(NY).date().isoformat()

    @property
    def lo_price(self) -> float:
        return self.lo_tick * TICK_SIZE

    @property
    def hi_price(self) -> float:
        return self.hi_tick * TICK_SIZE

    @property
    def failed_utc(self) -> datetime | None:
        failures = [ts for ts, kind in self.history if kind == "RailFailed"]
        return failures[0] if failures else None

    @property
    def first_tested_utc(self) -> datetime | None:
        tests = [ts for ts, kind in self.history if kind == "RailTested"]
        return tests[0] if tests else None

    def first_test_verdict(self) -> tuple[str, datetime | None]:
        tested = False
        for ts, kind in sorted(self.history):
            if kind == "RailTested":
                tested = True
            elif kind == "RailHeld" and tested:
                return "HELD_FIRST_TEST", ts
            elif kind == "RailFailed":
                return ("FAILED_FIRST_TEST" if tested else "FAILED_UNTESTED"), ts
        return ("TEST_UNRESOLVED" if tested else "NEVER_TESTED"), None


@dataclass
class OrderAttempt:
    session_id: int
    ts_utc: datetime
    intent_id: str
    directive_id: str
    role: str
    side: str
    reason: str
    root_id: int
    accepted: bool = False


@dataclass
class SponsorEvent:
    session_id: int
    ts_utc: datetime
    event: str
    directive_id: str
    sponsor_id: int
    prior_sponsor_id: int | None
    side: str
    source: str
    lo_tick: int | None
    hi_tick: int | None
    reason: str
    prior_sponsor_live: bool | None = None


def favorable_of(root: Rail, candidate: Rail) -> bool:
    if candidate.side != root.side:
        return False
    if root.side == "Demand":
        return candidate.lo_tick > root.hi_tick
    return candidate.hi_tick < root.lo_tick


def behind_root(root: Rail, candidate: Rail) -> bool:
    if candidate.side != root.side:
        return False
    if root.side == "Demand":
        return candidate.hi_tick < root.lo_tick
    return candidate.lo_tick > root.hi_tick


def favorable_distance(root: Rail, candidate: Rail) -> int:
    if root.side == "Demand":
        return candidate.lo_tick - root.hi_tick
    return root.lo_tick - candidate.hi_tick


def band_gap_ticks(left: Rail, right: Rail) -> int:
    if left.hi_tick < right.lo_tick:
        return right.lo_tick - left.hi_tick
    if right.hi_tick < left.lo_tick:
        return left.lo_tick - right.hi_tick
    return 0


def entry_context(
    root: Rail,
    session_rails: list[Rail],
    entry_anchor: datetime | None,
) -> dict[str, int | float | bool]:
    if entry_anchor is None:
        return {}
    output: dict[str, int | float | bool] = {}
    peers = [rail for rail in session_rails if rail.band_id != root.band_id]
    for minutes in (5, 10):
        start = entry_anchor.timestamp() - minutes * 60
        for radius_pts in (20, 50):
            radius_ticks = int(round(radius_pts / TICK_SIZE))
            local = [
                rail
                for rail in peers
                if band_gap_ticks(root, rail) <= radius_ticks
            ]
            owned = [
                rail
                for rail in local
                if start <= rail.owned_utc.timestamp() < entry_anchor.timestamp()
            ]
            failed = [
                rail
                for rail in local
                if rail.failed_utc is not None
                and start <= rail.failed_utc.timestamp() < entry_anchor.timestamp()
            ]
            prefix = f"pre_{minutes}m_{radius_pts}pts"
            output[f"{prefix}_same_owned"] = sum(
                rail.side == root.side for rail in owned
            )
            output[f"{prefix}_opposite_owned"] = sum(
                rail.side != root.side for rail in owned
            )
            output[f"{prefix}_same_failed"] = sum(
                rail.side == root.side for rail in failed
            )
            output[f"{prefix}_opposite_failed"] = sum(
                rail.side != root.side for rail in failed
            )
            output[f"{prefix}_consumed_owned"] = sum(
                rail.source == "Consumed" for rail in owned
            )
            output[f"{prefix}_two_sided_fail"] = (
                any(rail.side == "Demand" for rail in failed)
                and any(rail.side == "Supply" for rail in failed)
            )
            if failed:
                field_lo = min(rail.lo_tick for rail in failed)
                field_hi = max(rail.hi_tick for rail in failed)
                field_width = max(field_hi - field_lo, 1)
                root_mid = (root.lo_tick + root.hi_tick) / 2
                if root.side == "Demand":
                    favorable_gap = root.lo_tick - field_hi
                    favorable_position = (root_mid - field_lo) / field_width
                else:
                    favorable_gap = field_lo - root.hi_tick
                    favorable_position = (field_hi - root_mid) / field_width
                output[f"{prefix}_failed_field_width_pts"] = round(
                    field_width * TICK_SIZE, 2
                )
                output[f"{prefix}_favorable_edge_gap_pts"] = round(
                    favorable_gap * TICK_SIZE, 2
                )
                output[f"{prefix}_favorable_position"] = round(
                    favorable_position, 4
                )

    live = [
        rail
        for rail in peers
        if rail.owned_utc < entry_anchor
        and (rail.failed_utc is None or rail.failed_utc > entry_anchor)
    ]
    for radius_pts in (20, 50):
        radius_ticks = int(round(radius_pts / TICK_SIZE))
        local_live = [
            rail for rail in live if band_gap_ticks(root, rail) <= radius_ticks
        ]
        prefix = f"live_{radius_pts}pts"
        output[f"{prefix}_same"] = sum(
            rail.side == root.side for rail in local_live
        )
        output[f"{prefix}_opposite"] = sum(
            rail.side != root.side for rail in local_live
        )
        output[f"{prefix}_same_behind"] = sum(
            behind_root(root, rail) for rail in local_live
        )
        output[f"{prefix}_same_favorable"] = sum(
            favorable_of(root, rail) for rail in local_live
        )
    return output


def behind_distance(root: Rail, candidate: Rail) -> int:
    if root.side == "Demand":
        return root.lo_tick - candidate.hi_tick
    return candidate.lo_tick - root.hi_tick


def load_runtime(
    path: Path,
    start_date: str,
    end_date: str,
) -> tuple[
    list[Rail],
    list[OrderAttempt],
    list[SponsorEvent],
    dict[int, datetime],
]:
    session_id = 0
    session_starts: dict[int, datetime] = {}
    rails_by_key: dict[tuple[int, int], Rail] = {}
    pending_history: dict[tuple[int, int], list[tuple[datetime, str]]] = defaultdict(list)
    orders_by_intent: dict[str, OrderAttempt] = {}
    sponsor_events: list[SponsorEvent] = []

    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            raw_ts = event.get("ts_utc")
            if not raw_ts:
                continue
            ts = parse_ts(str(raw_ts))
            day = ts.astimezone(NY).date().isoformat()
            if day < start_date or day > end_date:
                continue
            name = event.get("event")

            if name == "runtime_started":
                session_id += 1
                session_starts[session_id] = ts
                continue

            if name == "evidence_transition":
                kind = str(event.get("kind") or "")
                band_id = as_int(event.get("band_id"))
                if band_id is None or kind not in {
                    "RailOwned",
                    "RailTested",
                    "RailHeld",
                    "RailFailed",
                }:
                    continue
                event_ts = parse_ts(str(event.get("event_utc") or raw_ts))
                key = (session_id, band_id)
                if kind == "RailOwned":
                    lo_tick = as_int(event.get("band_min_tick"))
                    hi_tick = as_int(event.get("band_max_tick"))
                    if lo_tick is None or hi_tick is None:
                        continue
                    rail = Rail(
                        session_id=session_id,
                        band_id=band_id,
                        owned_utc=event_ts,
                        side=str(event.get("band_side") or ""),
                        source=str(event.get("band_source") or ""),
                        lo_tick=lo_tick,
                        hi_tick=hi_tick,
                        score=float(event["score"]) if event.get("score") is not None else None,
                    )
                    rail.history.extend(pending_history.pop(key, []))
                    rails_by_key[key] = rail
                else:
                    rail = rails_by_key.get(key)
                    if rail is None:
                        pending_history[key].append((event_ts, kind))
                    elif event_ts >= rail.owned_utc:
                        rail.history.append((event_ts, kind))
                continue

            if (
                name == "order_submit"
                and event.get("resolution") == "DirectConversion"
                and event.get("reason") in ENTRY_REASONS
            ):
                intent_id = str(event.get("intent_id") or "")
                root_id = as_int(event.get("root_object_id"))
                if intent_id and root_id is not None:
                    orders_by_intent[intent_id] = OrderAttempt(
                        session_id=session_id,
                        ts_utc=ts,
                        intent_id=intent_id,
                        directive_id=str(event.get("directive_id") or ""),
                        role=str(event.get("role") or ""),
                        side=str(event.get("side") or ""),
                        reason=str(event.get("reason") or ""),
                        root_id=root_id,
                    )
                continue

            if name in {"order_submit_result", "intent_result"}:
                intent_id = str(event.get("intent_id") or "")
                order = orders_by_intent.get(intent_id)
                if order is not None and event.get("accepted") is True:
                    order.accepted = True
                continue

            if name in {
                "sponsor_promoted",
                "sponsor_failed",
                "sponsor_failure_context",
                "sponsor_cleared",
            }:
                sponsor_id = as_int(event.get("sponsor_id"))
                if sponsor_id is None:
                    continue
                lo = event.get("lower")
                hi = event.get("upper")
                prior_live = event.get("prior_sponsor_live")
                sponsor_events.append(
                    SponsorEvent(
                        session_id=session_id,
                        ts_utc=parse_ts(str(event.get("failure_utc") or event.get("promoted_utc") or raw_ts)),
                        event=str(name),
                        directive_id=str(event.get("directive_id") or ""),
                        sponsor_id=sponsor_id,
                        prior_sponsor_id=as_int(event.get("prior_sponsor_id")),
                        side=str(event.get("side") or ""),
                        source=str(event.get("source") or ""),
                        lo_tick=round(float(lo) / TICK_SIZE) if lo is not None else None,
                        hi_tick=round(float(hi) / TICK_SIZE) if hi is not None else None,
                        reason=str(
                            event.get("reason")
                            or event.get("failure_reason")
                            or event.get("promotion_reason")
                            or ""
                        ),
                        prior_sponsor_live=bool(prior_live) if prior_live is not None else None,
                    )
                )

    rails = sorted(rails_by_key.values(), key=lambda rail: rail.owned_utc)
    orders = sorted(
        (order for order in orders_by_intent.values() if order.accepted),
        key=lambda order: order.ts_utc,
    )
    sponsor_events.sort(key=lambda item: item.ts_utc)
    return rails, orders, sponsor_events, session_starts


def first_after(
    values: list[Any],
    start: datetime,
    predicate,
) -> Any | None:
    return next((value for value in values if value.ts_utc > start and predicate(value)), None)


def classify_rows(
    rails: list[Rail],
    orders: list[OrderAttempt],
    sponsor_events: list[SponsorEvent],
) -> list[dict[str, Any]]:
    by_session: dict[int, list[Rail]] = defaultdict(list)
    by_key: dict[tuple[int, int], Rail] = {}
    for rail in rails:
        by_session[rail.session_id].append(rail)
        by_key[(rail.session_id, rail.band_id)] = rail

    orders_by_root: dict[tuple[int, int], list[OrderAttempt]] = defaultdict(list)
    for order in orders:
        orders_by_root[(order.session_id, order.root_id)].append(order)

    sponsors_by_session: dict[int, list[SponsorEvent]] = defaultdict(list)
    for event in sponsor_events:
        sponsors_by_session[event.session_id].append(event)

    rows: list[dict[str, Any]] = []
    for root in rails:
        if root.source != "Consumed":
            continue
        session_rails = by_session[root.session_id]
        later_same_side = [
            rail
            for rail in session_rails
            if rail.owned_utc > root.owned_utc and rail.side == root.side
        ]
        successor = next(
            (rail for rail in later_same_side if favorable_of(root, rail)),
            None,
        )
        prior_live = [
            rail
            for rail in session_rails
            if rail.owned_utc < root.owned_utc
            and behind_root(root, rail)
            and (rail.failed_utc is None or rail.failed_utc > root.owned_utc)
        ]
        prior = min(prior_live, key=lambda rail: behind_distance(root, rail), default=None)

        root_fail = root.failed_utc
        successor_ts = successor.owned_utc if successor else None
        prior_fail = prior.failed_utc if prior else None
        structural_events = [
            (successor_ts, "ADVANCED_TO_FAVORABLE_SUCCESSOR"),
            (root_fail, "ROOT_FAILED_FIRST"),
            (prior_fail, "PRIOR_PROTECTION_FAILED_FIRST"),
        ]
        ordered = sorted(
            ((ts, label) for ts, label in structural_events if ts is not None),
            key=lambda item: item[0],
        )
        outcome = ordered[0][1] if ordered else "UNRESOLVED"

        root_verdict, root_verdict_ts = root.first_test_verdict()
        successor_verdict = ""
        successor_verdict_ts = None
        successor_failed_parent_live = False
        if successor is not None:
            successor_verdict, successor_verdict_ts = successor.first_test_verdict()
            successor_failed_parent_live = (
                successor.failed_utc is not None
                and (root_fail is None or successor.failed_utc < root_fail)
            )

        root_orders = orders_by_root.get((root.session_id, root.band_id), [])
        entry_anchor = root_orders[0].ts_utc if root_orders else None
        post_entry_successor = (
            next(
                (
                    rail
                    for rail in later_same_side
                    if entry_anchor is not None
                    and rail.owned_utc > entry_anchor
                    and (root_fail is None or rail.owned_utc < root_fail)
                    and favorable_of(root, rail)
                ),
                None,
            )
            if entry_anchor is not None
            else None
        )
        entry_events = (
            sorted(
                (
                    (ts, label)
                    for ts, label in (
                        (
                            post_entry_successor.owned_utc
                            if post_entry_successor is not None
                            else None,
                            "ADVANCED_AFTER_ENTRY",
                        ),
                        (
                            root_fail
                            if root_fail is not None and root_fail > entry_anchor
                            else None,
                            "ROOT_FAILED_AFTER_ENTRY",
                        ),
                        (
                            prior_fail
                            if prior_fail is not None and prior_fail > entry_anchor
                            else None,
                            "PRIOR_PROTECTION_FAILED_AFTER_ENTRY",
                        ),
                    )
                    if ts is not None
                ),
                key=lambda item: item[0],
            )
            if entry_anchor is not None
            else []
        )
        entry_outcome = entry_events[0][1] if entry_events else (
            "UNRESOLVED_AFTER_ENTRY" if entry_anchor is not None else ""
        )

        test_anchor = root.first_tested_utc
        post_test_successor = (
            next(
                (
                    rail
                    for rail in later_same_side
                    if test_anchor is not None
                    and rail.owned_utc > test_anchor
                    and (root_fail is None or rail.owned_utc < root_fail)
                    and favorable_of(root, rail)
                ),
                None,
            )
            if test_anchor is not None
            else None
        )
        test_events = (
            sorted(
                (
                    (ts, label)
                    for ts, label in (
                        (
                            post_test_successor.owned_utc
                            if post_test_successor is not None
                            else None,
                            "ADVANCED_AFTER_FIRST_TEST",
                        ),
                        (
                            root_fail
                            if root_fail is not None and root_fail > test_anchor
                            else None,
                            "ROOT_FAILED_AFTER_FIRST_TEST",
                        ),
                    )
                    if ts is not None
                ),
                key=lambda item: item[0],
            )
            if test_anchor is not None
            else []
        )
        test_outcome = test_events[0][1] if test_events else (
            "UNRESOLVED_AFTER_FIRST_TEST" if test_anchor is not None else ""
        )
        test_context = {
            f"test_{key}": value
            for key, value in entry_context(root, session_rails, test_anchor).items()
        }
        hold_anchor = (
            root_verdict_ts if root_verdict == "HELD_FIRST_TEST" else None
        )
        post_hold_successor = (
            next(
                (
                    rail
                    for rail in later_same_side
                    if hold_anchor is not None
                    and rail.owned_utc > hold_anchor
                    and (root_fail is None or rail.owned_utc < root_fail)
                    and favorable_of(root, rail)
                ),
                None,
            )
            if hold_anchor is not None
            else None
        )
        hold_events = (
            sorted(
                (
                    (ts, label)
                    for ts, label in (
                        (
                            post_hold_successor.owned_utc
                            if post_hold_successor is not None
                            else None,
                            "ADVANCED_AFTER_FIRST_HOLD",
                        ),
                        (
                            root_fail
                            if root_fail is not None and root_fail > hold_anchor
                            else None,
                            "ROOT_FAILED_AFTER_FIRST_HOLD",
                        ),
                    )
                    if ts is not None
                ),
                key=lambda item: item[0],
            )
            if hold_anchor is not None
            else []
        )
        hold_outcome = hold_events[0][1] if hold_events else (
            "UNRESOLVED_AFTER_FIRST_HOLD" if hold_anchor is not None else ""
        )
        hold_context = {
            f"hold_{key}": value
            for key, value in entry_context(root, session_rails, hold_anchor).items()
        }

        post_entry_successor_verdict = ""
        post_entry_successor_verdict_ts = None
        failure_propagation = ""
        post_child_reestablishment = None
        existing_live_favorable = None
        if post_entry_successor is not None:
            (
                post_entry_successor_verdict,
                post_entry_successor_verdict_ts,
            ) = post_entry_successor.first_test_verdict()
            child_fail = post_entry_successor.failed_utc
            if child_fail is None:
                failure_propagation = "SUCCESSOR_DID_NOT_FAIL"
            else:
                existing_live_favorable = next(
                    (
                        rail
                        for rail in session_rails
                        if rail.band_id != post_entry_successor.band_id
                        and rail.owned_utc <= child_fail
                        and favorable_of(root, rail)
                        and (rail.failed_utc is None or rail.failed_utc > child_fail)
                    ),
                    None,
                )
                post_child_reestablishment = next(
                    (
                        rail
                        for rail in session_rails
                        if rail.owned_utc > child_fail and favorable_of(root, rail)
                    ),
                    None,
                )
                candidates = sorted(
                    (
                        (ts, label)
                        for ts, label in (
                            (
                                existing_live_favorable.owned_utc
                                if existing_live_favorable is not None
                                else None,
                                "CONTAINED_BY_EXISTING_FAVORABLE_SPONSOR",
                            ),
                            (
                                post_child_reestablishment.owned_utc
                                if post_child_reestablishment is not None
                                else None,
                                "REESTABLISHED_BEFORE_ROOT_FAILURE",
                            ),
                            (
                                root_fail
                                if root_fail is not None and root_fail >= child_fail
                                else None,
                                "ROOT_FAILED_BEFORE_REESTABLISHMENT",
                            ),
                        )
                        if ts is not None
                    ),
                    key=lambda item: item[0],
                )
                failure_propagation = (
                    candidates[0][1]
                    if candidates
                    else "NO_ROOT_FAILURE_OR_REESTABLISHMENT_SEEN"
                )

        session_sponsors = sponsors_by_session[root.session_id]
        root_promotions = [
            event
            for event in session_sponsors
            if event.event == "sponsor_promoted"
            and event.sponsor_id == root.band_id
            and event.ts_utc >= root.owned_utc
        ]
        root_promotion = root_promotions[0] if root_promotions else None
        explicit_child = first_after(
            session_sponsors,
            root.owned_utc,
            lambda event: (
                event.event == "sponsor_promoted"
                and event.prior_sponsor_id == root.band_id
                and event.side == root.side
            ),
        )
        child_rail = (
            by_key.get((root.session_id, explicit_child.sponsor_id))
            if explicit_child is not None
            else None
        )
        child_failure = (
            first_after(
                session_sponsors,
                explicit_child.ts_utc,
                lambda event: (
                    event.event == "sponsor_failed"
                    and event.directive_id == explicit_child.directive_id
                    and event.sponsor_id == explicit_child.sponsor_id
                ),
            )
            if explicit_child is not None
            else None
        )
        child_failure_context = (
            first_after(
                session_sponsors,
                explicit_child.ts_utc,
                lambda event: (
                    event.event == "sponsor_failure_context"
                    and event.directive_id == explicit_child.directive_id
                    and event.sponsor_id == explicit_child.sponsor_id
                ),
            )
            if explicit_child is not None
            else None
        )

        explicit_prior = (
            by_key.get((root.session_id, root_promotion.prior_sponsor_id))
            if root_promotion is not None and root_promotion.prior_sponsor_id is not None
            else None
        )
        rows.append(
            {
                "session_id": root.session_id,
                "date": root.date,
                "root_owned_et": et_text(root.owned_utc),
                "root_id": root.band_id,
                "side": root.side,
                "root_source": root.source,
                "root_lo": root.lo_price,
                "root_hi": root.hi_price,
                "root_width_pts": round(root.hi_price - root.lo_price, 2),
                "root_first_test_verdict": root_verdict,
                "root_first_tested_et": et_text(test_anchor),
                "root_first_test_resolved_et": et_text(root_verdict_ts),
                "root_failed_et": et_text(root_fail),
                "test_structural_outcome": test_outcome,
                "post_test_successor_id": (
                    post_test_successor.band_id if post_test_successor else ""
                ),
                "post_test_successor_owned_et": (
                    et_text(post_test_successor.owned_utc)
                    if post_test_successor
                    else ""
                ),
                **test_context,
                "hold_structural_outcome": hold_outcome,
                "post_hold_successor_id": (
                    post_hold_successor.band_id if post_hold_successor else ""
                ),
                "post_hold_successor_owned_et": (
                    et_text(post_hold_successor.owned_utc)
                    if post_hold_successor
                    else ""
                ),
                **hold_context,
                "traded": bool(root_orders),
                "entry_count": len(root_orders),
                "entry_roles": "|".join(sorted({order.role for order in root_orders})),
                "entry_reasons": "|".join(sorted({order.reason for order in root_orders})),
                "directive_ids": "|".join(sorted({order.directive_id for order in root_orders})),
                "first_entry_et": et_text(root_orders[0].ts_utc) if root_orders else "",
                **entry_context(root, session_rails, entry_anchor),
                "post_entry_successor_id": (
                    post_entry_successor.band_id if post_entry_successor else ""
                ),
                "post_entry_successor_source": (
                    post_entry_successor.source if post_entry_successor else ""
                ),
                "post_entry_successor_lo": (
                    post_entry_successor.lo_price if post_entry_successor else ""
                ),
                "post_entry_successor_hi": (
                    post_entry_successor.hi_price if post_entry_successor else ""
                ),
                "post_entry_successor_distance_pts": (
                    round(favorable_distance(root, post_entry_successor) * TICK_SIZE, 2)
                    if post_entry_successor
                    else ""
                ),
                "post_entry_successor_owned_et": (
                    et_text(post_entry_successor.owned_utc)
                    if post_entry_successor
                    else ""
                ),
                "entry_to_successor_s": (
                    elapsed_s(entry_anchor, post_entry_successor.owned_utc)
                    if post_entry_successor
                    else ""
                ),
                "post_entry_successor_first_test_verdict": post_entry_successor_verdict,
                "post_entry_successor_first_test_resolved_et": et_text(
                    post_entry_successor_verdict_ts
                ),
                "post_entry_successor_failed_et": (
                    et_text(post_entry_successor.failed_utc)
                    if post_entry_successor
                    else ""
                ),
                "post_entry_successor_failed_while_root_live": (
                    post_entry_successor is not None
                    and post_entry_successor.failed_utc is not None
                    and (root_fail is None or post_entry_successor.failed_utc < root_fail)
                ),
                "successor_failure_to_root_failure_s": (
                    elapsed_s(post_entry_successor.failed_utc, root_fail)
                    if post_entry_successor
                    else ""
                ),
                "entry_structural_outcome": entry_outcome,
                "successor_failure_propagation": failure_propagation,
                "existing_live_favorable_id_at_successor_failure": (
                    existing_live_favorable.band_id
                    if existing_live_favorable is not None
                    else ""
                ),
                "post_child_reestablishment_id": (
                    post_child_reestablishment.band_id
                    if post_child_reestablishment is not None
                    else ""
                ),
                "post_child_reestablishment_owned_et": (
                    et_text(post_child_reestablishment.owned_utc)
                    if post_child_reestablishment is not None
                    else ""
                ),
                "successor_failure_to_reestablishment_s": (
                    elapsed_s(
                        post_entry_successor.failed_utc,
                        post_child_reestablishment.owned_utc,
                    )
                    if post_entry_successor is not None
                    and post_child_reestablishment is not None
                    else ""
                ),
                "prior_protection_id": prior.band_id if prior else "",
                "prior_protection_source": prior.source if prior else "",
                "prior_protection_distance_pts": (
                    round(behind_distance(root, prior) * TICK_SIZE, 2) if prior else ""
                ),
                "prior_protection_failed_et": et_text(prior_fail),
                "favorable_successor_id": successor.band_id if successor else "",
                "favorable_successor_source": successor.source if successor else "",
                "favorable_successor_distance_pts": (
                    round(favorable_distance(root, successor) * TICK_SIZE, 2)
                    if successor
                    else ""
                ),
                "favorable_successor_owned_et": et_text(successor_ts),
                "favorable_successor_first_test_verdict": successor_verdict,
                "favorable_successor_first_test_resolved_et": et_text(successor_verdict_ts),
                "favorable_successor_failed_et": (
                    et_text(successor.failed_utc) if successor else ""
                ),
                "successor_failed_while_root_live": successor_failed_parent_live,
                "structural_outcome": outcome,
                "explicit_root_promoted": root_promotion is not None,
                "explicit_prior_sponsor_id": (
                    root_promotion.prior_sponsor_id if root_promotion else ""
                ),
                "explicit_prior_relation": (
                    "behind"
                    if explicit_prior is not None and behind_root(root, explicit_prior)
                    else (
                        "favorable"
                        if explicit_prior is not None and favorable_of(root, explicit_prior)
                        else ("overlap_or_unknown" if explicit_prior is not None else "")
                    )
                ),
                "explicit_child_id": explicit_child.sponsor_id if explicit_child else "",
                "explicit_child_source": explicit_child.source if explicit_child else "",
                "explicit_child_promoted_et": (
                    et_text(explicit_child.ts_utc) if explicit_child else ""
                ),
                "explicit_child_favorable": (
                    favorable_of(root, child_rail)
                    if explicit_child is not None and child_rail is not None
                    else ""
                ),
                "explicit_child_failed_et": (
                    et_text(child_failure.ts_utc) if child_failure else ""
                ),
                "explicit_child_failed_parent_live": (
                    child_failure_context.prior_sponsor_live
                    if child_failure_context is not None
                    else ""
                ),
            }
        )
    return rows


CONTEXT_FIELDS: list[str] = []
for _minutes in (5, 10):
    for _radius in (20, 50):
        _prefix = f"pre_{_minutes}m_{_radius}pts"
        CONTEXT_FIELDS.extend(
            [
                f"{_prefix}_same_owned",
                f"{_prefix}_opposite_owned",
                f"{_prefix}_same_failed",
                f"{_prefix}_opposite_failed",
                f"{_prefix}_consumed_owned",
                f"{_prefix}_two_sided_fail",
                f"{_prefix}_failed_field_width_pts",
                f"{_prefix}_favorable_edge_gap_pts",
                f"{_prefix}_favorable_position",
            ]
        )
for _radius in (20, 50):
    _prefix = f"live_{_radius}pts"
    CONTEXT_FIELDS.extend(
        [
            f"{_prefix}_same",
            f"{_prefix}_opposite",
            f"{_prefix}_same_behind",
            f"{_prefix}_same_favorable",
        ]
    )
TEST_CONTEXT_FIELDS = [f"test_{field}" for field in CONTEXT_FIELDS]
HOLD_CONTEXT_FIELDS = [f"hold_{field}" for field in CONTEXT_FIELDS]


FIELDS = [
    "session_id",
    "date",
    "root_owned_et",
    "root_id",
    "side",
    "root_source",
    "root_lo",
    "root_hi",
    "root_width_pts",
    "root_first_test_verdict",
    "root_first_tested_et",
    "root_first_test_resolved_et",
    "root_failed_et",
    "test_structural_outcome",
    "post_test_successor_id",
    "post_test_successor_owned_et",
    *TEST_CONTEXT_FIELDS,
    "hold_structural_outcome",
    "post_hold_successor_id",
    "post_hold_successor_owned_et",
    *HOLD_CONTEXT_FIELDS,
    "traded",
    "entry_count",
    "entry_roles",
    "entry_reasons",
    "directive_ids",
    "first_entry_et",
    *CONTEXT_FIELDS,
    "post_entry_successor_id",
    "post_entry_successor_source",
    "post_entry_successor_lo",
    "post_entry_successor_hi",
    "post_entry_successor_distance_pts",
    "post_entry_successor_owned_et",
    "entry_to_successor_s",
    "post_entry_successor_first_test_verdict",
    "post_entry_successor_first_test_resolved_et",
    "post_entry_successor_failed_et",
    "post_entry_successor_failed_while_root_live",
    "successor_failure_to_root_failure_s",
    "entry_structural_outcome",
    "successor_failure_propagation",
    "existing_live_favorable_id_at_successor_failure",
    "post_child_reestablishment_id",
    "post_child_reestablishment_owned_et",
    "successor_failure_to_reestablishment_s",
    "prior_protection_id",
    "prior_protection_source",
    "prior_protection_distance_pts",
    "prior_protection_failed_et",
    "favorable_successor_id",
    "favorable_successor_source",
    "favorable_successor_distance_pts",
    "favorable_successor_owned_et",
    "favorable_successor_first_test_verdict",
    "favorable_successor_first_test_resolved_et",
    "favorable_successor_failed_et",
    "successor_failed_while_root_live",
    "structural_outcome",
    "explicit_root_promoted",
    "explicit_prior_sponsor_id",
    "explicit_prior_relation",
    "explicit_child_id",
    "explicit_child_source",
    "explicit_child_promoted_et",
    "explicit_child_favorable",
    "explicit_child_failed_et",
    "explicit_child_failed_parent_live",
]


def rate(num: int, den: int) -> str:
    return f"{num / den:.3f}" if den else ""


def median_field(rows: list[dict[str, Any]], key: str) -> str:
    values = [
        float(row[key])
        for row in rows
        if row.get(key) not in ("", None)
    ]
    return f"{statistics.median(values):.3f}" if values else ""


def summarize_group(
    name: str,
    rows: list[dict[str, Any]],
    *,
    outcome_key: str = "structural_outcome",
) -> list[str]:
    counts = Counter(str(row[outcome_key]) for row in rows)
    if outcome_key == "entry_structural_outcome":
        advanced_label = "ADVANCED_AFTER_ENTRY"
        self_failed_label = "ROOT_FAILED_AFTER_ENTRY"
        regressed_label = "PRIOR_PROTECTION_FAILED_AFTER_ENTRY"
        unresolved_label = "UNRESOLVED_AFTER_ENTRY"
    else:
        advanced_label = "ADVANCED_TO_FAVORABLE_SUCCESSOR"
        self_failed_label = "ROOT_FAILED_FIRST"
        regressed_label = "PRIOR_PROTECTION_FAILED_FIRST"
        unresolved_label = "UNRESOLVED"
    advanced = counts[advanced_label]
    self_failed = counts[self_failed_label]
    regressed = counts[regressed_label]
    propagation = Counter(
        str(row["successor_failure_propagation"])
        for row in rows
        if row.get("successor_failure_propagation")
    )
    if outcome_key == "entry_structural_outcome":
        successor_rows = [row for row in rows if row["post_entry_successor_id"] != ""]
        child_failed_live = sum(
            bool(row["post_entry_successor_failed_while_root_live"])
            for row in successor_rows
        )
    else:
        successor_rows = [row for row in rows if row["favorable_successor_id"] != ""]
        child_failed_live = sum(
            bool(row["successor_failed_while_root_live"]) for row in successor_rows
        )
    explicit_children = [row for row in rows if row["explicit_child_id"] != ""]
    explicit_failed_parent_live = sum(
        row["explicit_child_failed_parent_live"] is True for row in explicit_children
    )
    lines = [
        f"### {name}",
        "",
        f"- roots={len(rows)}",
        f"- advanced first={advanced} ({rate(advanced, len(rows))})",
        f"- root failed first={self_failed} ({rate(self_failed, len(rows))})",
        f"- older protection failed first={regressed} ({rate(regressed, len(rows))})",
        f"- unresolved={counts[unresolved_label]} ({rate(counts[unresolved_label], len(rows))})",
        f"- favorable successor later failed while root was live={child_failed_live}/{len(successor_rows)} ({rate(child_failed_live, len(successor_rows))})",
        f"- explicit promoted child failed with prior sponsor reported live={explicit_failed_parent_live}/{len(explicit_children)} ({rate(explicit_failed_parent_live, len(explicit_children))})",
    ]
    if outcome_key == "entry_structural_outcome":
        contained = [
            row
            for row in rows
            if row["successor_failure_propagation"]
            == "CONTAINED_BY_EXISTING_FAVORABLE_SPONSOR"
        ]
        reestablished = [
            row
            for row in rows
            if row["successor_failure_propagation"]
            == "REESTABLISHED_BEFORE_ROOT_FAILURE"
        ]
        root_failed = [
            row
            for row in rows
            if row["successor_failure_propagation"]
            == "ROOT_FAILED_BEFORE_REESTABLISHMENT"
        ]
        lines.extend(
            [
                f"- successor failure contained by already-live favorable sponsor={propagation['CONTAINED_BY_EXISTING_FAVORABLE_SPONSOR']}",
                f"- same-side sponsorship re-established before root failure={len(reestablished)}; median child-failure-to-reestablishment={median_field(reestablished, 'successor_failure_to_reestablishment_s')}s",
                f"- root failed before same-side re-establishment={len(root_failed)}; median child-failure-to-root-failure={median_field(root_failed, 'successor_failure_to_root_failure_s')}s",
                f"- contained cases with later root failure observed={sum(row.get('successor_failure_to_root_failure_s') not in ('', None) for row in contained)}",
            ]
        )
    return lines


def build_report(rows: list[dict[str, Any]], start_date: str, end_date: str) -> str:
    traded = [row for row in rows if row["traded"]]
    base = [row for row in traded if "EnterBase" in str(row["entry_roles"])]
    adds = [row for row in traded if "Add" in str(row["entry_roles"])]
    lines = [
        "# Direct-Conversion Sponsor Lineage",
        "",
        f"Window: {start_date} through {end_date} ET.",
        "",
        "Outcome is event-ordered, not time-to-retest or fixed price excursion.",
        "",
        "## Population",
        "",
        *summarize_group("All consumed rails", rows),
        "",
        *summarize_group(
            "Accepted DirectConversion order roots",
            traded,
            outcome_key="entry_structural_outcome",
        ),
        "",
        *summarize_group(
            "Traded base roots",
            base,
            outcome_key="entry_structural_outcome",
        ),
        "",
        *summarize_group(
            "Traded add roots",
            adds,
            outcome_key="entry_structural_outcome",
        ),
        "",
        "## July 24 fixtures",
        "",
    ]
    for root_id in (34, 84, 89, 102):
        fixture = next(
            (
                row
                for row in rows
                if row["date"] == "2026-07-24" and row["root_id"] == root_id
            ),
            None,
        )
        if fixture is None:
            lines.append(f"- root {root_id}: not found")
            continue
        lines.append(
            f"- root {root_id}: {fixture['side']} {fixture['root_lo']}-{fixture['root_hi']}; "
            f"entry_outcome={fixture['entry_structural_outcome']}; first_test={fixture['root_first_test_verdict']}; "
            f"post_entry_successor={fixture['post_entry_successor_id']} {fixture['post_entry_successor_source']}; "
            f"propagation={fixture['successor_failure_propagation']}; "
            f"explicit_child={fixture['explicit_child_id']} {fixture['explicit_child_source']}; "
            f"explicit_child_failed_parent_live={fixture['explicit_child_failed_parent_live']}"
        )
    lines.extend(
        [
            "",
            "## Interpretation boundary",
            "",
            "- `ADVANCED_TO_FAVORABLE_SUCCESSOR` says the conversion generated new same-side ownership before local regression. It does not say the child deserved sole flatten authority.",
            "- For traded roots, the practical progression clock starts at the entry decision. A successor that formed and failed before entry is stale context, not sponsorship produced by the tradeable retest.",
            "- `ROOT_FAILED_FIRST` is direct evidence that the conversion did not establish durable sponsorship.",
            "- `PRIOR_PROTECTION_FAILED_FIRST` is the stronger regression hypothesis: ownership moved through the conversion far enough to damage an older, worse-located same-side sponsor before a favorable successor appeared.",
            "- After a post-entry child fails, the event-order question is whether another favorable same-side sponsor is already live or re-establishes before the consumed root fails. Root failure first means the child failure propagated backward into the conversion.",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--events", type=Path, default=DEFAULT_EVENTS)
    parser.add_argument("--start-date", default="2026-06-22")
    parser.add_argument("--end-date", default="2026-07-24")
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=OUTPUT_ROOT / "direct_conversion_sponsor_lineage",
    )
    args = parser.parse_args()

    rails, orders, sponsors, _ = load_runtime(
        args.events, args.start_date, args.end_date
    )
    rows = classify_rows(rails, orders, sponsors)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = args.out_dir / "lineage.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    report = build_report(rows, args.start_date, args.end_date)
    report_path = args.out_dir / "findings.md"
    report_path.write_text(report, encoding="utf-8")
    print(report)
    print(f"wrote {csv_path} rows={len(rows)}")


if __name__ == "__main__":
    main()
