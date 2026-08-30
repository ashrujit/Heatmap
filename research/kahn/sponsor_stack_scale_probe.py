"""Codex-authored sponsor-stack renewal scale research.

This probe tests a stricter add idea than the basic HoldRoot scale pass:
after a root position is onside, keep a same-side stack of favorable LL
events, then look for retests/re-establishment with replenished MBO flow.

The output is research only. It is not accepted Kahn policy.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import polars as pl

from holdroot_scale_probe import (
    CASES,
    FEATURE_SEC,
    MIN_PRESS_RUNWAY_POINTS,
    REDUCE_SIZE_AFTER_PATH_FRACTION,
    REPO,
    SUPPRESS_AFTER_PATH_FRACTION,
    TARGET_PROXIMITY_POINTS,
    Case,
    band_flow,
    case_summary,
    flow_grade,
    hms_from_us,
    hour_flow_table,
    ll_transitions,
    load_case_ticks,
    mfe_mae,
    ny_us,
    parse_hms_us,
    path_consumed_fraction,
    range_intersects,
    recent_opposing_failure,
    recent_opposing_weak_contacts,
    runway_points,
    same_side,
    target_floor,
    transition_price,
    transition_time_us,
    write_csv,
)


STACK_TTL_SEC = 15 * 60
STACK_DISTANCE_POINTS = 12.0
CHALLENGE_LOOKBACK_SEC = 180
FAIL_REESTABLISH_LOOKBACK_SEC = 180
FAIL_REESTABLISH_PROXIMITY_POINTS = 2.0
MIN_STACK_DEPTH = 2
MIN_ROOT_CUSHION_POINTS = 0.5


@dataclass
class StackMember:
    band_id: int
    side: str
    source: str
    family: str
    action: str
    lo: float
    hi: float
    first_seen_us: int
    last_seen_us: int
    score: float
    replenish: float | None
    paid_share: float | None
    grade: str
    touches: int = 0
    holds: int = 0
    owned: int = 0
    consumed: int = 0


def range_gap(a_lo: float, a_hi: float, b_lo: float, b_hi: float) -> float:
    if a_hi < b_lo:
        return b_lo - a_hi
    if b_hi < a_lo:
        return a_lo - b_hi
    return 0.0


def favorable_family(case: Case, transition: dict[str, Any]) -> str:
    source = str(transition.get("source", ""))
    action = str(transition.get("action", ""))
    direct_source = "supply_consumed" if case.side == "long" else "demand_consumed"
    lean_source = "demand_lean" if case.side == "long" else "supply_lean"
    if action == "CONSUMED" or direct_source in source:
        return "direct_consumption"
    if lean_source in source:
        return "same_side_lean"
    if "consumed" in source:
        return "other_consumption"
    if "lean" in source:
        return "other_lean"
    return "other"


def root_cushion_points(case: Case, ticks: pl.DataFrame, entry_us: int, now_us: int) -> float:
    end_us = now_us - 1_000_000
    if end_us <= entry_us:
        return 0.0
    sub = ticks.filter((pl.col("timestamp_us") >= entry_us) & (pl.col("timestamp_us") <= end_us))
    if not sub.height:
        return 0.0
    if case.side == "long":
        return max(0.0, float(sub["price"].max()) - case.entry_ref)
    return max(0.0, case.entry_ref - float(sub["price"].min()))


def price_is_onside(case: Case, price: float) -> bool:
    if case.side == "long":
        return price >= case.entry_ref
    return price <= case.entry_ref


def relevant_stack_members(
    case: Case,
    active: dict[int, StackMember],
    now_us: int,
    price: float,
) -> list[StackMember]:
    members: list[StackMember] = []
    for member in active.values():
        if now_us - member.last_seen_us > STACK_TTL_SEC * 1_000_000:
            continue
        if not range_intersects(member.lo, member.hi, case.focus_lo, case.focus_hi):
            continue
        if case.side == "long":
            if member.lo > price + FAIL_REESTABLISH_PROXIMITY_POINTS:
                continue
            distance = max(0.0, price - member.hi)
        else:
            if member.hi < price - FAIL_REESTABLISH_PROXIMITY_POINTS:
                continue
            distance = max(0.0, member.lo - price)
        if distance <= STACK_DISTANCE_POINTS:
            members.append(member)
    return members


def stack_summary(members: list[StackMember]) -> dict[str, Any]:
    direct = sum(1 for member in members if member.family == "direct_consumption")
    lean = sum(1 for member in members if member.family == "same_side_lean")
    replenished = sum(1 for member in members if member.grade == "replenished")
    score = sum(member.score for member in members)
    labels = [
        f"{member.band_id}:{member.family}:{member.action}:{member.lo:g}-{member.hi:g}"
        for member in sorted(members, key=lambda item: item.last_seen_us)[-5:]
    ]
    return {
        "stack_depth": len(members),
        "stack_direct": direct,
        "stack_lean": lean,
        "stack_replenished": replenished,
        "stack_score": round(score, 2),
        "stack_recent": ";".join(labels),
    }


def recent_same_side_reestablish(
    case: Case,
    failures: list[dict[str, Any]],
    now_us: int,
    lo: float,
    hi: float,
) -> str:
    matches = []
    for failure in failures:
        failure_us = int(failure["t_us"])
        if now_us - failure_us > FAIL_REESTABLISH_LOOKBACK_SEC * 1_000_000:
            continue
        if not same_side(case, str(failure["side"])):
            continue
        gap = range_gap(lo, hi, float(failure["min_price"]), float(failure["max_price"]))
        if gap <= FAIL_REESTABLISH_PROXIMITY_POINTS:
            matches.append(f"{failure['time']} {failure['range']}")
    return ",".join(matches[-3:])


def renewal_kind(
    action: str,
    t_us: int,
    band_id: int,
    latest_test_time: dict[int, int],
    same_side_reestablish: str,
    opposing_fail_count: int,
    opposing_weak_count: int,
) -> str:
    held_after_test = (
        action == "HOLD"
        and band_id in latest_test_time
        and 0 <= t_us - latest_test_time[band_id] <= CHALLENGE_LOOKBACK_SEC * 1_000_000
    )
    if same_side_reestablish:
        return "reestablished_after_same_side_fail"
    if held_after_test and (opposing_fail_count > 0 or opposing_weak_count > 0):
        return "held_after_test_and_opposition_failed"
    if held_after_test:
        return "held_after_test"
    if opposing_fail_count > 0:
        return "opposition_failed"
    if opposing_weak_count > 0:
        return "opposition_depleted"
    return "none"


def sponsor_stack_call(
    action: str,
    current_grade: str,
    runway: float,
    path_consumed: float,
    onside: bool,
    root_cushion: float,
    summary: dict[str, Any],
    renewal: str,
) -> str:
    if runway < TARGET_PROXIMITY_POINTS:
        return "scale_out_zone"
    if action not in {"HOLD", "OWNED", "CONSUMED"}:
        return "watch_contact"
    if not onside:
        return "holdroot_no_add_root_not_onside"
    if root_cushion < MIN_ROOT_CUSHION_POINTS:
        return "watch_stack_before_root_cushion"
    if current_grade != "replenished":
        return "reject_depleted_contact"
    if runway < MIN_PRESS_RUNWAY_POINTS:
        return "reject_low_runway"
    if path_consumed >= SUPPRESS_AFTER_PATH_FRACTION:
        return "mature_path_hold_only"
    if int(summary["stack_depth"]) < MIN_STACK_DEPTH:
        return "holdroot_no_add_shallow_stack"
    if int(summary["stack_direct"]) == 0 and int(summary["stack_lean"]) == 0:
        return "holdroot_no_add_untyped_stack"
    if renewal == "none":
        return "stack_watch_no_renewal"
    if renewal == "held_after_test":
        return "stack_watch_retest_only"
    if path_consumed >= REDUCE_SIZE_AFTER_PATH_FRACTION:
        return "sponsor_stack_add_reduced"
    return "sponsor_stack_add"


def update_stack_member(
    active: dict[int, StackMember],
    transition: dict[str, Any],
    t_us: int,
    flow: dict[str, float | None],
    family: str,
) -> StackMember:
    band_id = int(transition["band_id"])
    action = str(transition.get("action", ""))
    member = active.get(band_id)
    if member is None:
        member = StackMember(
            band_id=band_id,
            side=str(transition.get("side", "")),
            source=str(transition.get("source", "")),
            family=family,
            action=action,
            lo=float(transition["min_price"]),
            hi=float(transition["max_price"]),
            first_seen_us=t_us,
            last_seen_us=t_us,
            score=float(transition.get("score") or 0.0),
            replenish=flow["replenish"],
            paid_share=flow["paid_share"],
            grade=flow_grade(flow),
        )
        active[band_id] = member
    else:
        member.source = str(transition.get("source", ""))
        member.family = family
        member.action = action
        member.lo = float(transition["min_price"])
        member.hi = float(transition["max_price"])
        member.last_seen_us = t_us
        member.score = float(transition.get("score") or member.score)
        member.replenish = flow["replenish"]
        member.paid_share = flow["paid_share"]
        member.grade = flow_grade(flow)

    if action == "TEST":
        member.touches += 1
    elif action == "HOLD":
        member.holds += 1
    elif action == "OWNED":
        member.owned += 1
    elif action == "CONSUMED":
        member.consumed += 1
    return member


def collect_sponsor_stack_candidates(
    case: Case,
    transitions: list[dict[str, Any]],
    ticks: pl.DataFrame,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    entry_us = parse_hms_us(case.day, case.entry_time)
    end_us = ny_us(case.day, case.window.split("-", 1)[1])
    ordered = sorted(transitions, key=lambda item: transition_time_us(case, item))
    flow_cache: dict[int, pl.DataFrame] = {}
    latest_test_flow: dict[int, dict[str, float | None]] = {}
    latest_test_time: dict[int, int] = {}
    contacts: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    active: dict[int, StackMember] = {}
    events: list[dict[str, Any]] = []
    candidates: list[dict[str, Any]] = []

    def table_for(hour: int) -> pl.DataFrame:
        if hour not in flow_cache:
            flow_cache[hour] = hour_flow_table(case.symbol_dir, case.day, hour)
        return flow_cache[hour]

    test_contact_by_key: dict[tuple[int, int], dict[str, float | None]] = {}
    for transition in ordered:
        action = str(transition.get("action", ""))
        if action != "TEST":
            continue
        t_us = transition_time_us(case, transition)
        hour = int(transition["time"][:2])
        flow = band_flow(
            table_for(hour),
            float(transition["min_price"]),
            float(transition["max_price"]),
            str(transition.get("side", "")),
            t_us,
            t_us + FEATURE_SEC * 1_000_000,
        )
        band_id = int(transition["band_id"])
        test_contact_by_key[(band_id, t_us)] = flow
        contacts.append(
            {
                "t_us": t_us,
                "time": transition["time"],
                "band_id": band_id,
                "side": transition.get("side", ""),
                "range": transition.get("range", ""),
                "grade": flow_grade(flow),
            }
        )

    for transition in ordered:
        t_us = transition_time_us(case, transition)
        hour = int(transition["time"][:2])
        band_id = int(transition["band_id"])
        action = str(transition.get("action", ""))
        owner_side = str(transition.get("side", ""))
        lo = float(transition["min_price"])
        hi = float(transition["max_price"])
        in_focus = range_intersects(lo, hi, case.focus_lo, case.focus_hi)

        if action == "TEST":
            latest_test_flow[band_id] = test_contact_by_key[(band_id, t_us)]
            latest_test_time[band_id] = t_us

        if action == "FAIL":
            failures.append(
                {
                    "t_us": t_us,
                    "time": transition["time"],
                    "band_id": band_id,
                    "side": owner_side,
                    "range": transition.get("range", ""),
                    "min_price": lo,
                    "max_price": hi,
                }
            )
            if same_side(case, owner_side):
                active.pop(band_id, None)

        if not same_side(case, owner_side) or not in_focus:
            continue

        if action not in {"TEST", "HOLD", "OWNED", "CONSUMED", "FAIL"}:
            continue

        flow = latest_test_flow.get(band_id)
        flow_source = "latest_test"
        if flow is None or t_us - latest_test_time.get(band_id, -10**18) > 240_000_000:
            flow = band_flow(
                table_for(hour),
                lo,
                hi,
                owner_side,
                t_us,
                t_us + FEATURE_SEC * 1_000_000,
            )
            flow_source = "event_forward"

        if action in {"TEST", "HOLD", "OWNED", "CONSUMED"}:
            update_stack_member(active, transition, t_us, flow, favorable_family(case, transition))

        price = transition_price(transition)
        members = relevant_stack_members(case, active, t_us, price)
        summary = stack_summary(members)
        same_reestablish = recent_same_side_reestablish(case, failures, t_us, lo, hi)
        opp_fail_count, opp_fail_score, opp_fail_label = recent_opposing_failure(case, transitions, t_us)
        opp_weak_count, opp_weak_label = recent_opposing_weak_contacts(case, contacts, t_us)
        renewal = renewal_kind(
            action,
            t_us,
            band_id,
            latest_test_time,
            same_reestablish,
            opp_fail_count,
            opp_weak_count,
        )
        runway = runway_points(case, price)
        consumed_fraction = path_consumed_fraction(case, price)
        root_cushion = root_cushion_points(case, ticks, entry_us, t_us)
        path = mfe_mae(case, ticks, t_us, end_us, price)
        call = sponsor_stack_call(
            action,
            flow_grade(flow),
            runway,
            consumed_fraction,
            price_is_onside(case, price),
            root_cushion,
            summary,
            renewal,
        )
        row = {
            "case_id": case.case_id,
            "time": transition["time"],
            "action": action,
            "band_id": band_id,
            "side": owner_side,
            "source": transition.get("source", ""),
            "family": favorable_family(case, transition),
            "range": transition.get("range", ""),
            "current_price": price,
            "score": round(float(transition.get("score") or 0.0), 3),
            "flow_source": flow_source,
            "flow_grade": flow_grade(flow),
            "replenish": round(float(flow["replenish"]), 3)
            if flow["replenish"] is not None
            else "",
            "paid_share": round(float(flow["paid_share"]), 3)
            if flow["paid_share"] is not None
            else "",
            "root_cushion_points": round(root_cushion, 2),
            "onside": price_is_onside(case, price),
            "runway_points": round(runway, 2),
            "path_consumed_pct": round(consumed_fraction * 100.0, 1),
            "stack_depth": summary["stack_depth"],
            "stack_direct": summary["stack_direct"],
            "stack_lean": summary["stack_lean"],
            "stack_replenished": summary["stack_replenished"],
            "stack_score": summary["stack_score"],
            "stack_recent": summary["stack_recent"],
            "renewal_kind": renewal,
            "same_side_reestablish_recent": same_reestablish,
            "opposing_fail_count_3m": opp_fail_count,
            "opposing_fail_score_3m": round(opp_fail_score, 2),
            "opposing_fail_recent": opp_fail_label,
            "opposing_weak_contact_count_3m": opp_weak_count,
            "opposing_weak_contact_recent": opp_weak_label,
            "future_mfe": round(float(path["mfe"] or 0.0), 2),
            "future_mae": round(float(path["mae"] or 0.0), 2),
            "future_target_time": hms_from_us(path["target_time"]),
            "call": call,
        }
        if t_us >= entry_us:
            events.append(row)
            if action in {"HOLD", "OWNED", "CONSUMED"}:
                candidates.append(row)

    return events, candidates


def top_rows(rows: list[dict[str, Any]], case_id: str, limit: int = 14) -> list[dict[str, Any]]:
    order = {
        "sponsor_stack_add": 0,
        "sponsor_stack_add_reduced": 1,
        "stack_watch_no_renewal": 2,
        "stack_watch_retest_only": 3,
        "watch_stack_before_root_cushion": 4,
        "holdroot_no_add_shallow_stack": 5,
        "holdroot_no_add_root_not_onside": 6,
        "reject_depleted_contact": 7,
        "reject_low_runway": 8,
        "mature_path_hold_only": 9,
        "scale_out_zone": 10,
    }
    selected = [row for row in rows if row["case_id"] == case_id]
    return sorted(
        selected,
        key=lambda row: (
            order.get(str(row["call"]), 99),
            -float(row["runway_points"]),
            float(row["future_mae"]),
            row["time"],
        ),
    )[:limit]


def report_markdown(
    summaries: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
) -> str:
    lines = [
        "# Sponsor Stack Renewal Scale Probe",
        "",
        "Codex-authored research artifact. This is not accepted Kahn policy.",
        "",
        "Hypothesis: HoldRoot should still suppress ordinary onside pressing, but a "
        "root-preserving add can outrank HoldRoot when the campaign has built a "
        "same-side sponsor stack and that stack renews after a challenge.",
        "",
        "Candidate grammar:",
        "",
        "- Root position exists, current price is onside, and the root has already "
        f"earned at least {MIN_ROOT_CUSHION_POINTS:g} points of cushion before the event.",
        f"- Same-side stack depth is at least {MIN_STACK_DEPTH}, built from direct "
        "consumption and/or same-side lean LL rails near current price.",
        "- Current same-side event is HOLD/OWNED/CONSUMED with replenished MBO flow.",
        "- Full add priority requires renewal stronger than a plain held retest: "
        "held retest plus failed/depleted opposition, re-establishment after "
        "same-side fail, or direct failed/depleted opposition preceding the event.",
        "- Plain held retests become `stack_watch_retest_only`.",
        "- Target runway remains open; late-path adds reduce or stop.",
        "- Any live implementation must preserve the root risk anchor on add.",
        "",
        "## Cases",
        "",
    ]
    for summary in summaries:
        lines.append(
            f"- `{summary['case_id']}`: {summary['side']} from {summary['entry_time']} "
            f"ref {summary['entry_ref']}, target floor {summary['target_floor']}, "
            f"MFE {summary['mfe']}, MAE {summary['mae']}, target {summary['target_time']}."
        )

    lines.extend(["", "## Candidate Rows", ""])
    for case in CASES:
        lines.append(f"### {case.case_id}")
        rows = top_rows(candidates, case.case_id)
        if not rows:
            lines.extend(["", "- none", ""])
            continue
        lines.append("")
        lines.append(
            "| time | action | band | family | range | renewal | stack d/l | rootC | "
            "replen | runway | path% | future MFE/MAE | call |"
        )
        lines.append(
            "| --- | --- | ---: | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |"
        )
        for row in rows:
            lines.append(
                f"| {row['time']} | {row['action']} | {row['band_id']} | {row['family']} | "
                f"{row['range']} | {row['renewal_kind']} | "
                f"{row['stack_depth']}/{row['stack_direct']}/{row['stack_lean']} | "
                f"{row['root_cushion_points']} | {row['replenish']} | "
                f"{row['runway_points']} | {row['path_consumed_pct']} | "
                f"{row['future_mfe']}/{row['future_mae']} | {row['call']} |"
            )
        lines.append("")

    counts: dict[tuple[str, str], int] = {}
    for row in candidates:
        key = (str(row["case_id"]), str(row["call"]))
        counts[key] = counts.get(key, 0) + 1

    lines.extend(["## Call Counts", ""])
    for case in CASES:
        lines.append(f"### {case.case_id}")
        for (case_id, call), count in sorted(counts.items()):
            if case_id == case.case_id:
                lines.append(f"- `{call}`: {count}")
        lines.append("")

    lines.extend(
        [
            "## Policy Read",
            "",
            "This supports a separate `SponsorStackRenewed` add path rather than "
            "weakening HoldRoot. Its priority should sit above HoldRoot because the "
            "decision is no longer a generic press; it is a renewed, replenished "
            "sponsor-stack event after root cushion exists. It should remain below "
            "`SuppressAdd`, `PassiveHarvest`, `Reduce`, `Flatten`, and `Retire`, and "
            "the add must use `preserve_risk_anchor_on_add` so the child rail never "
            "becomes the campaign sponsor.",
        ]
    )
    return "\n".join(lines)


def write_counts(path: Path, rows: list[dict[str, Any]]) -> None:
    counts: dict[tuple[str, str], int] = {}
    for row in rows:
        key = (str(row["case_id"]), str(row["call"]))
        counts[key] = counts.get(key, 0) + 1
    out = [
        {"case_id": case_id, "call": call, "count": count}
        for (case_id, call), count in sorted(counts.items())
    ]
    write_csv(path, out)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--out-dir",
        default=str(REPO / "research" / "kahn" / "out" / "sponsor-stack-scale-20260830"),
    )
    args = parser.parse_args()
    out_dir = Path(args.out_dir)

    summaries: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    candidates: list[dict[str, Any]] = []

    for case in CASES:
        print(f"# {case.case_id}")
        transitions = ll_transitions(case)
        ticks = load_case_ticks(case)
        summaries.append(case_summary(case, ticks))
        case_events, case_candidates = collect_sponsor_stack_candidates(case, transitions, ticks)
        events.extend(case_events)
        candidates.extend(case_candidates)

    write_csv(out_dir / "case_summary.csv", summaries)
    write_csv(out_dir / "stack_events.csv", events)
    write_csv(out_dir / "stack_candidates.csv", candidates)
    write_counts(out_dir / "call_counts.csv", candidates)
    report = report_markdown(summaries, candidates)
    (out_dir / "report.md").write_text(report, encoding="utf-8")
    print(report)


if __name__ == "__main__":
    main()
