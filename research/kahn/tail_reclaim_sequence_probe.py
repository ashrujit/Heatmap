"""Codex-authored tail-reclaim sequence scale research.

This probe searches for the specific sequence discussed after the initial
HoldRoot and sponsor-stack passes:

1. Root A remains the risk anchor.
2. Same-side favorable rails extend away from A toward B/C/D.
3. Price repairs; D/C fail or are at least challenged.
4. An opposing ZZ claim appears inside the earned path.
5. ZZ fails, or is implicitly invalidated by price trading back through the
   prior favorable tail.
6. Same-side C/D reclaims with reload quality and continuation runway.

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
    opposite_side,
    parse_hms_us,
    path_consumed_fraction,
    range_intersects,
    runway_points,
    same_side,
    target_floor,
    transition_price,
    transition_time_us,
    write_csv,
)
from sponsor_stack_scale_probe import (
    StackMember,
    favorable_family,
    relevant_stack_members,
    root_cushion_points,
    stack_summary,
    update_stack_member,
)


TICK_SIZE = 0.25
ZZ_AFTER_FAIL_LOOKBACK_SEC = 8 * 60
ZZ_TTL_SEC = 12 * 60
ZZ_PROXIMITY_POINTS = 3.0
TAIL_BREAK_LOOKAHEAD_SEC = 4 * 60
MIN_ZZ_HOLD_SEC = 20
MIN_REPAIR_FROM_TAIL_POINTS = 1.5
MIN_SEQUENCE_STACK_DEPTH = 1


@dataclass
class SameSideFailure:
    time_us: int
    time: str
    band_id: int
    side: str
    source: str
    action: str
    lo: float
    hi: float
    current_price: float
    score: float
    tail_price: float
    tail_time: str
    tail_range: str


@dataclass
class ZzClaim:
    time_us: int
    last_seen_us: int
    time: str
    band_id: int
    side: str
    source: str
    lo: float
    hi: float
    current_price: float
    score: float
    sponsor_failure: SameSideFailure
    pre_zz_tail_price: float
    pre_zz_tail_time: str
    pre_zz_tail_range: str
    last_action: str


def range_gap(a_lo: float, a_hi: float, b_lo: float, b_hi: float) -> float:
    if a_hi < b_lo:
        return b_lo - a_hi
    if b_hi < a_lo:
        return a_lo - b_hi
    return 0.0


def favorable_value(case: Case, price: float) -> float:
    return price if case.side == "long" else -price


def favorable_extension(case: Case, from_price: float, to_price: float) -> float:
    return to_price - from_price if case.side == "long" else from_price - to_price


def adverse_repair_from_tail(case: Case, tail_price: float, price: float) -> float:
    return tail_price - price if case.side == "long" else price - tail_price


def fav_side(case: Case) -> str:
    return "demand" if case.side == "long" else "supply"


def in_earned_corridor(case: Case, lo: float, hi: float, tail_price: float) -> bool:
    low = min(case.entry_ref, tail_price)
    high = max(case.entry_ref, tail_price)
    mid = (lo + hi) / 2.0
    return low - ZZ_PROXIMITY_POINTS <= mid <= high + ZZ_PROXIMITY_POINTS


def invalidates_zz_by_price(case: Case, price: float, zz: ZzClaim) -> bool:
    if case.side == "long":
        return price >= zz.hi + TICK_SIZE
    return price <= zz.lo - TICK_SIZE


def crosses_tail(case: Case, price: float, tail_price: float) -> bool:
    if case.side == "long":
        return price >= tail_price + TICK_SIZE
    return price <= tail_price - TICK_SIZE


def tail_break_time(
    case: Case,
    ticks: pl.DataFrame,
    start_us: int,
    end_us: int,
    tail_price: float,
) -> int | None:
    if case.side == "long":
        frame = ticks.filter(
            (pl.col("timestamp_us") >= start_us)
            & (pl.col("timestamp_us") <= end_us)
            & (pl.col("price") >= tail_price + TICK_SIZE)
        )
    else:
        frame = ticks.filter(
            (pl.col("timestamp_us") >= start_us)
            & (pl.col("timestamp_us") <= end_us)
            & (pl.col("price") <= tail_price - TICK_SIZE)
        )
    if not frame.height:
        return None
    return int(frame["timestamp_us"][0])


def find_recent_same_failure(
    failures: list[SameSideFailure],
    now_us: int,
) -> SameSideFailure | None:
    for failure in reversed(failures):
        age_sec = (now_us - failure.time_us) / 1_000_000
        if 0 <= age_sec <= ZZ_AFTER_FAIL_LOOKBACK_SEC:
            return failure
    return None


def implicit_tail_challenge(
    case: Case,
    now_us: int,
    now_time: str,
    price: float,
    tail_price: float,
    tail_time: str,
    tail_range: str,
) -> SameSideFailure | None:
    if tail_price == case.entry_ref:
        return None
    repair = adverse_repair_from_tail(case, tail_price, price)
    if repair < MIN_REPAIR_FROM_TAIL_POINTS:
        return None
    return SameSideFailure(
        time_us=now_us,
        time=now_time,
        band_id=-1,
        side=fav_side(case),
        source="implicit_tail_challenge",
        action="CHALLENGE",
        lo=min(price, tail_price),
        hi=max(price, tail_price),
        current_price=price,
        score=0.0,
        tail_price=tail_price,
        tail_time=tail_time,
        tail_range=tail_range,
    )


def matches_zz_failure(transition: dict[str, Any], zz: ZzClaim) -> bool:
    lo = float(transition["min_price"])
    hi = float(transition["max_price"])
    band_id = int(transition["band_id"])
    return band_id == zz.band_id or range_gap(lo, hi, zz.lo, zz.hi) <= ZZ_PROXIMITY_POINTS


def sequence_call(
    flow: dict[str, float | None],
    root_cushion: float,
    runway: float,
    path_consumed: float,
    stack: dict[str, Any],
    tail_break_us: int | None,
    now_us: int,
) -> str:
    if runway < TARGET_PROXIMITY_POINTS:
        return "tail_reclaim_harvest_not_add"
    if path_consumed >= SUPPRESS_AFTER_PATH_FRACTION:
        return "tail_reclaim_mature_path_harvest"
    if root_cushion < 0.5:
        return "tail_reclaim_watch_before_root_cushion"
    if flow_grade(flow) != "replenished":
        return "tail_reclaim_reject_depleted"
    if int(stack["stack_depth"]) < MIN_SEQUENCE_STACK_DEPTH:
        return "tail_reclaim_watch_shallow_stack"
    if runway < MIN_PRESS_RUNWAY_POINTS:
        return "tail_reclaim_reject_low_runway"
    if tail_break_us is None:
        return "tail_reclaim_watch_no_tail_break"
    if path_consumed >= REDUCE_SIZE_AFTER_PATH_FRACTION:
        return "tail_reclaim_add_reduced"
    delay_sec = max(0.0, (tail_break_us - now_us) / 1_000_000)
    if delay_sec > TAIL_BREAK_LOOKAHEAD_SEC:
        return "tail_reclaim_watch_delayed_break"
    return "tail_reclaim_add"


def collect_tail_reclaim_sequences(
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
    active_stack: dict[int, StackMember] = {}
    same_failures: list[SameSideFailure] = []
    active_zz: ZzClaim | None = None
    failed_zzs: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []

    tail_price = case.entry_ref
    tail_time = case.entry_time
    tail_range = "root"

    def table_for(hour: int) -> pl.DataFrame:
        if hour not in flow_cache:
            flow_cache[hour] = hour_flow_table(case.symbol_dir, case.day, hour)
        return flow_cache[hour]

    test_contact_by_key: dict[tuple[int, int], dict[str, float | None]] = {}
    for transition in ordered:
        if transition.get("action") != "TEST":
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
        test_contact_by_key[(int(transition["band_id"]), t_us)] = flow

    for transition in ordered:
        t_us = transition_time_us(case, transition)
        if t_us < entry_us:
            continue

        hour = int(transition["time"][:2])
        band_id = int(transition["band_id"])
        action = str(transition.get("action", ""))
        side = str(transition.get("side", ""))
        lo = float(transition["min_price"])
        hi = float(transition["max_price"])
        price = transition_price(transition)
        in_focus = range_intersects(lo, hi, case.focus_lo, case.focus_hi)

        if action == "TEST":
            latest_test_flow[band_id] = test_contact_by_key[(band_id, t_us)]
            latest_test_time[band_id] = t_us

        flow = latest_test_flow.get(band_id)
        flow_source = "latest_test"
        if flow is None or t_us - latest_test_time.get(band_id, -10**18) > 240_000_000:
            flow = band_flow(
                table_for(hour),
                lo,
                hi,
                side,
                t_us,
                t_us + FEATURE_SEC * 1_000_000,
            )
            flow_source = "event_forward"

        if same_side(case, side) and in_focus and action in {"TEST", "HOLD", "OWNED", "CONSUMED"}:
            update_stack_member(active_stack, transition, t_us, flow, favorable_family(case, transition))
            if favorable_value(case, price) > favorable_value(case, tail_price):
                tail_price = price
                tail_time = transition["time"]
                tail_range = str(transition.get("range", ""))

        if same_side(case, side) and in_focus and action == "FAIL":
            same_failures.append(
                SameSideFailure(
                    time_us=t_us,
                    time=transition["time"],
                    band_id=band_id,
                    side=side,
                    source=str(transition.get("source", "")),
                    action=action,
                    lo=lo,
                    hi=hi,
                    current_price=price,
                    score=float(transition.get("score") or 0.0),
                    tail_price=tail_price,
                    tail_time=tail_time,
                    tail_range=tail_range,
                )
            )
            active_stack.pop(band_id, None)

        if opposite_side(case, side) and in_focus and action in {"HOLD", "OWNED", "CONSUMED"}:
            sponsor_failure = find_recent_same_failure(same_failures, t_us)
            if sponsor_failure is None:
                sponsor_failure = implicit_tail_challenge(
                    case,
                    t_us,
                    transition["time"],
                    price,
                    tail_price,
                    tail_time,
                    tail_range,
                )
            if sponsor_failure and in_earned_corridor(case, lo, hi, sponsor_failure.tail_price):
                if active_zz is None or t_us - active_zz.last_seen_us > ZZ_TTL_SEC * 1_000_000:
                    active_zz = ZzClaim(
                        time_us=t_us,
                        last_seen_us=t_us,
                        time=transition["time"],
                        band_id=band_id,
                        side=side,
                        source=str(transition.get("source", "")),
                        lo=lo,
                        hi=hi,
                        current_price=price,
                        score=float(transition.get("score") or 0.0),
                        sponsor_failure=sponsor_failure,
                        pre_zz_tail_price=sponsor_failure.tail_price,
                        pre_zz_tail_time=sponsor_failure.tail_time,
                        pre_zz_tail_range=sponsor_failure.tail_range,
                        last_action=action,
                    )
                else:
                    active_zz.last_seen_us = t_us
                    active_zz.last_action = action
                    if float(transition.get("score") or 0.0) > active_zz.score:
                        active_zz.band_id = band_id
                        active_zz.source = str(transition.get("source", ""))
                        active_zz.lo = lo
                        active_zz.hi = hi
                        active_zz.current_price = price
                        active_zz.score = float(transition.get("score") or 0.0)

        zz_failure_kind = ""
        zz_failed_now: ZzClaim | None = None
        if active_zz is not None and t_us - active_zz.last_seen_us <= ZZ_TTL_SEC * 1_000_000:
            if opposite_side(case, side) and action == "FAIL" and matches_zz_failure(transition, active_zz):
                zz_failure_kind = "formal_zz_fail"
                zz_failed_now = active_zz
            elif same_side(case, side) and action in {"HOLD", "OWNED", "CONSUMED"}:
                if invalidates_zz_by_price(case, price, active_zz) or crosses_tail(
                    case,
                    price,
                    active_zz.pre_zz_tail_price,
                ):
                    zz_failure_kind = "implicit_zz_fail_by_reclaim"
                    zz_failed_now = active_zz

        if zz_failed_now is not None:
            failed_zzs.append(
                {
                    "t_us": t_us,
                    "time": transition["time"],
                    "failure_kind": zz_failure_kind,
                    "zz": zz_failed_now,
                    "trigger_transition": transition,
                }
            )
            active_zz = None

        pending = failed_zzs[-1] if failed_zzs else None
        if (
            pending is not None
            and same_side(case, side)
            and in_focus
            and action in {"HOLD", "OWNED", "CONSUMED"}
            and t_us >= int(pending["t_us"])
            and t_us - int(pending["t_us"]) <= ZZ_TTL_SEC * 1_000_000
        ):
            zz: ZzClaim = pending["zz"]
            members = relevant_stack_members(case, active_stack, t_us, price)
            stack = stack_summary(members)
            tail_us = tail_break_time(
                case,
                ticks,
                t_us,
                min(end_us, t_us + TAIL_BREAK_LOOKAHEAD_SEC * 1_000_000),
                zz.pre_zz_tail_price,
            )
            runway = runway_points(case, price)
            path_consumed = path_consumed_fraction(case, price)
            path = mfe_mae(case, ticks, t_us, end_us, price)
            root_cushion = root_cushion_points(case, ticks, entry_us, t_us)
            hold_sec = max(0.0, (int(pending["t_us"]) - zz.time_us) / 1_000_000)
            if hold_sec < MIN_ZZ_HOLD_SEC and pending["failure_kind"] == "formal_zz_fail":
                hold_label = "brief"
            else:
                hold_label = "held"
            call = sequence_call(flow, root_cushion, runway, path_consumed, stack, tail_us, t_us)
            rows.append(
                {
                    "case_id": case.case_id,
                    "time": transition["time"],
                    "action": action,
                    "band_id": band_id,
                    "side": side,
                    "source": transition.get("source", ""),
                    "family": favorable_family(case, transition),
                    "range": transition.get("range", ""),
                    "current_price": price,
                    "flow_source": flow_source,
                    "flow_grade": flow_grade(flow),
                    "replenish": round(float(flow["replenish"]), 3)
                    if flow["replenish"] is not None
                    else "",
                    "paid_share": round(float(flow["paid_share"]), 3)
                    if flow["paid_share"] is not None
                    else "",
                    "root_cushion_points": round(root_cushion, 2),
                    "runway_points": round(runway, 2),
                    "path_consumed_pct": round(path_consumed * 100.0, 1),
                    "stack_depth": stack["stack_depth"],
                    "stack_direct": stack["stack_direct"],
                    "stack_lean": stack["stack_lean"],
                    "zz_time": zz.time,
                    "zz_range": f"{zz.lo:g}-{zz.hi:g}",
                    "zz_side": zz.side,
                    "zz_source": zz.source,
                    "zz_hold_sec": round(hold_sec, 1),
                    "zz_hold_label": hold_label,
                    "zz_failure_time": hms_from_us(int(pending["t_us"])),
                    "zz_failure_kind": pending["failure_kind"],
                    "sponsor_fail_time": zz.sponsor_failure.time,
                    "sponsor_fail_range": f"{zz.sponsor_failure.lo:g}-{zz.sponsor_failure.hi:g}",
                    "pre_zz_tail_time": zz.pre_zz_tail_time,
                    "pre_zz_tail_price": zz.pre_zz_tail_price,
                    "pre_zz_tail_range": zz.pre_zz_tail_range,
                    "tail_break_time": hms_from_us(tail_us),
                    "tail_break_delay_sec": round((tail_us - t_us) / 1_000_000, 1)
                    if tail_us is not None
                    else "",
                    "future_mfe": round(float(path["mfe"] or 0.0), 2),
                    "future_mae": round(float(path["mae"] or 0.0), 2),
                    "future_target_time": hms_from_us(path["target_time"]),
                    "call": call,
                }
            )

    return rows, [
        {
            "case_id": case.case_id,
            "time": failure.time,
            "range": f"{failure.lo:g}-{failure.hi:g}",
            "source": failure.source,
            "tail_time": failure.tail_time,
            "tail_price": failure.tail_price,
            "tail_range": failure.tail_range,
        }
        for failure in same_failures
    ]


def top_rows(rows: list[dict[str, Any]], case_id: str, limit: int = 14) -> list[dict[str, Any]]:
    order = {
        "tail_reclaim_add": 0,
        "tail_reclaim_add_reduced": 1,
        "tail_reclaim_watch_no_tail_break": 2,
        "tail_reclaim_watch_delayed_break": 3,
        "tail_reclaim_watch_shallow_stack": 4,
        "tail_reclaim_reject_depleted": 5,
        "tail_reclaim_reject_low_runway": 6,
        "tail_reclaim_harvest_not_add": 7,
        "tail_reclaim_mature_path_harvest": 8,
    }
    selected = [row for row in rows if row["case_id"] == case_id]
    return sorted(
        selected,
        key=lambda row: (
            order.get(str(row["call"]), 99),
            row["time"],
        ),
    )[:limit]


def report_markdown(
    summaries: list[dict[str, Any]],
    sequences: list[dict[str, Any]],
) -> str:
    lines = [
        "# Tail Reclaim Sequence Probe",
        "",
        "Codex-authored research artifact. This is not accepted Kahn policy.",
        "",
        "Hypothesis: a root-preserving add may be justified after A-B-C-D extension, "
        "C/D repair failure, opposing ZZ claim, ZZ invalidation, and same-side "
        "reclaim back through the prior tail. This is stricter than adding during "
        "the first favorable extension.",
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

    lines.extend(["", "## Sequence Rows", ""])
    for case in CASES:
        rows = top_rows(sequences, case.case_id)
        lines.append(f"### {case.case_id}")
        if not rows:
            lines.extend(["", "- none", ""])
            continue
        lines.append("")
        lines.append(
            "| time | action | range | ZZ | fail | prior D | break | stack | replen | runway | path% | future MFE/MAE | call |"
        )
        lines.append(
            "| --- | --- | --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | --- |"
        )
        for row in rows:
            lines.append(
                f"| {row['time']} | {row['action']} | {row['range']} | "
                f"{row['zz_time']} {row['zz_range']} | {row['zz_failure_kind']} "
                f"{row['zz_failure_time']} | {row['pre_zz_tail_time']} "
                f"{row['pre_zz_tail_price']} | {row['tail_break_time']} | "
                f"{row['stack_depth']}/{row['stack_direct']}/{row['stack_lean']} | "
                f"{row['replenish']} | {row['runway_points']} | "
                f"{row['path_consumed_pct']} | {row['future_mfe']}/"
                f"{row['future_mae']} | {row['call']} |"
            )
        lines.append("")

    counts: dict[tuple[str, str], int] = {}
    for row in sequences:
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
            "This sequence is a candidate for a higher-priority add path than "
            "HoldRoot because it waits for a failed repair cycle instead of "
            "scaling the first impulse. The live trigger should probably be two "
            "stage: mark `ReclaimWatch` when ZZ is invalidated and same-side C "
            "reloads, then allow `TailReclaimAdd` only as price accepts through "
            "the prior D/tail with root risk still preserved. Near target, the "
            "same sequence should strengthen hold/harvest rather than add.",
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
        default=str(REPO / "research" / "kahn" / "out" / "tail-reclaim-sequence-20260830"),
    )
    args = parser.parse_args()
    out_dir = Path(args.out_dir)

    summaries: list[dict[str, Any]] = []
    sequences: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []

    for case in CASES:
        print(f"# {case.case_id}")
        transitions = ll_transitions(case)
        ticks = load_case_ticks(case)
        summaries.append(case_summary(case, ticks))
        case_sequences, case_failures = collect_tail_reclaim_sequences(case, transitions, ticks)
        sequences.extend(case_sequences)
        failures.extend(case_failures)

    write_csv(out_dir / "case_summary.csv", summaries)
    write_csv(out_dir / "tail_reclaim_sequences.csv", sequences)
    write_csv(out_dir / "same_side_failures.csv", failures)
    write_counts(out_dir / "call_counts.csv", sequences)
    report = report_markdown(summaries, sequences)
    (out_dir / "report.md").write_text(report, encoding="utf-8")
    print(report)


if __name__ == "__main__":
    main()
