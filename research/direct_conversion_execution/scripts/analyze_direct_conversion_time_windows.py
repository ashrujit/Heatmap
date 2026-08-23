"""Audit direct-conversion behavior and execution policies by RTH daypart.

The lifecycle population includes every tested synthetic consumed rail. The
execution-policy population remains the separate HELD_FIRST_TEST conditional
sample produced by direct_conversion_terrain_execution_policy.py.
"""

from __future__ import annotations

import argparse
import bisect
import csv
import math
import random
import statistics
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterable
from zoneinfo import ZoneInfo

from _paths import OUTPUT_ROOT

from direct_conversion_terrain_execution_policy import (  # noqa: E402
    ADVANCED,
    FAILED,
    fmt,
    number,
    parse_et,
    quantile,
    read_csv,
    terrain_class,
    truth,
    write_csv,
)
from capture_loader import load_capture_window, tick_columns  # noqa: E402


NY = ZoneInfo("America/New_York")
DEFAULT_LINEAGE = (
    OUTPUT_ROOT / "direct_conversion_sponsor_lineage" / "lineage.csv"
)
DEFAULT_PROFILES = (
    OUTPUT_ROOT / "direct_conversion_profile_field_20260716_20260724"
    / "profile_locations.csv"
)
DEFAULT_DECISIONS = (
    OUTPUT_ROOT / "direct_conversion_terrain_execution_20260716_20260724"
    / "policy_decisions.csv"
)
DEFAULT_OUT = (
    OUTPUT_ROOT / "direct_conversion_time_windows_20260716_20260724"
)
PRIMARY_CONFIG = "60m:2pt"
FOCUS_POLICIES = {
    "market_now",
    "vpoc_gate",
    "hvn_escape_touch",
    "hvn_escape_two_sided",
    "combined_terrain_gate",
    "passive_band_30s",
}
DAYPART_ORDER = {
    "full_rth": 0,
    "morning_0930_1130": 1,
    "midday_1130_1330": 2,
    "afternoon_1330_1530": 3,
    "late_1530_1600": 4,
    "non_midday_all": 5,
    "core_non_midday": 6,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lineage-csv", type=Path, default=DEFAULT_LINEAGE)
    parser.add_argument("--profile-csv", type=Path, default=DEFAULT_PROFILES)
    parser.add_argument("--decisions-csv", type=Path, default=DEFAULT_DECISIONS)
    parser.add_argument("--start-date", default="2026-07-16")
    parser.add_argument("--end-date", default="2026-07-24")
    parser.add_argument("--symbol-dir", default="NQU6")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--bootstrap-samples", type=int, default=10_000)
    return parser.parse_args()


def minute_of_day(value: datetime) -> float:
    return (
        value.hour * 60
        + value.minute
        + value.second / 60
        + value.microsecond / 60_000_000
    )


def daypart(value: datetime) -> str:
    minute = minute_of_day(value.astimezone(NY))
    if 570 <= minute < 690:
        return "morning_0930_1130"
    if 690 <= minute < 810:
        return "midday_1130_1330"
    if 810 <= minute < 930:
        return "afternoon_1330_1530"
    if 930 <= minute < 960:
        return "late_1530_1600"
    return "outside_rth"


def cohorts(part: str) -> tuple[str, ...]:
    if part == "outside_rth":
        return ()
    output = ["full_rth", part]
    if part != "midday_1130_1330":
        output.append("non_midday_all")
    if part in {"morning_0930_1130", "afternoon_1330_1530"}:
        output.append("core_non_midday")
    return tuple(output)


def median(rows: Iterable[dict[str, Any]], key: str) -> float | None:
    values = [
        value
        for row in rows
        if (value := number(row.get(key))) is not None
    ]
    return statistics.median(values) if values else None


def profile_index(path: Path) -> dict[tuple[str, str, str], dict[str, str]]:
    output: dict[tuple[str, str, str], dict[str, str]] = {}
    for row in read_csv(path):
        if (
            row.get("source") == "lineage"
            and row.get("query_kind") == "first_test"
            and row.get("scope") == "60m"
            and abs((number(row.get("bin_points")) or 0.0) - 2.0) < 1e-9
        ):
            output[
                (row.get("session_id", ""), row["date"], row["root_id"])
            ] = row
    return output


def lifecycle_rows(
    lineage_path: Path,
    profiles: dict[tuple[str, str, str], dict[str, str]],
    start_date: str,
    end_date: str,
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for row in read_csv(lineage_path):
        if not start_date <= row.get("date", "") <= end_date:
            continue
        tested_text = row.get("root_first_tested_et", "")
        verdict = row.get("root_first_test_verdict", "")
        if not tested_text or verdict not in {"HELD_FIRST_TEST", "FAILED_FIRST_TEST"}:
            continue
        tested = parse_et(tested_text)
        part = daypart(tested)
        if part == "outside_rth":
            continue
        held = verdict == "HELD_FIRST_TEST"
        hold_outcome = row.get("hold_structural_outcome", "")
        post_hold_resolved = hold_outcome in {ADVANCED, FAILED}
        clean_advance = held and hold_outcome == ADVANCED
        questionable = verdict == "FAILED_FIRST_TEST" or (
            held and hold_outcome == FAILED
        )
        structural_resolved = verdict == "FAILED_FIRST_TEST" or (
            held and post_hold_resolved
        )
        owned = parse_et(row["root_owned_et"])
        resolved_text = row.get("root_first_test_resolved_et", "")
        resolved = parse_et(resolved_text) if resolved_text else None
        session_id = row.get("session_id", "")
        profile = profiles.get((session_id, row["date"], row["root_id"]))
        profile_valid = bool(profile and truth(profile.get("profile_valid")))
        test_failures = sum(
            number(row.get(key)) or 0.0
            for key in (
                "test_pre_10m_50pts_same_failed",
                "test_pre_10m_50pts_opposite_failed",
            )
        )
        rec: dict[str, Any] = {
            "session_id": session_id,
            "date": row["date"],
            "root_id": row["root_id"],
            "side": row["side"],
            "tested_et": tested_text,
            "daypart": part,
            "verdict": verdict,
            "held": held,
            "failed_first_test": verdict == "FAILED_FIRST_TEST",
            "hold_outcome": hold_outcome,
            "post_hold_resolved": post_hold_resolved,
            "post_hold_advanced": clean_advance,
            "post_hold_failed": held and hold_outcome == FAILED,
            "structural_resolved": structural_resolved,
            "clean_advance": clean_advance,
            "questionable": questionable,
            "two_sided_churn_10m_50pts": truth(
                row.get("test_pre_10m_50pts_two_sided_fail")
            ),
            "local_failed_rails_10m_50pts": test_failures,
            "local_owned_rails_10m_50pts": sum(
                number(row.get(key)) or 0.0
                for key in (
                    "test_pre_10m_50pts_same_owned",
                    "test_pre_10m_50pts_opposite_owned",
                )
            ),
            "owned_to_test_s": (tested - owned).total_seconds(),
            "test_to_verdict_s": (
                (resolved - tested).total_seconds() if resolved else None
            ),
            "profile_valid": profile_valid,
            "terrain_class": terrain_class(profile or {})
            if profile_valid
            else "invalid",
            "topology": profile.get("topology", "") if profile else "",
            "vpoc_signed_distance_pts": number(
                profile.get("current_vpoc_signed_distance_pts")
            )
            if profile
            else None,
        }
        output.append(rec)
    return output


def rate(rows: Iterable[dict[str, Any]], numerator: str, denominator: str) -> float | None:
    eligible = [row for row in rows if bool(row.get(denominator))]
    if not eligible:
        return None
    return sum(bool(row.get(numerator)) for row in eligible) / len(eligible)


def lifecycle_summary(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    expanded: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        for cohort in cohorts(str(row["daypart"])):
            expanded[cohort].append(row)
    output: list[dict[str, Any]] = []
    for cohort, group in expanded.items():
        held = sum(bool(row["held"]) for row in group)
        failed_first = sum(bool(row["failed_first_test"]) for row in group)
        held_resolved = [
            row for row in group if row["held"] and row["post_hold_resolved"]
        ]
        structurally_resolved = [
            row for row in group if row["structural_resolved"]
        ]
        profile_valid = [row for row in group if row["profile_valid"]]
        output.append(
            {
                "cohort": cohort,
                "tested_roots": len(group),
                "held_first_test": held,
                "failed_first_test": failed_first,
                "first_test_hold_rate": held / (held + failed_first)
                if held + failed_first
                else None,
                "held_resolved": len(held_resolved),
                "post_hold_advanced": sum(
                    bool(row["post_hold_advanced"]) for row in held_resolved
                ),
                "post_hold_failed": sum(
                    bool(row["post_hold_failed"]) for row in held_resolved
                ),
                "post_hold_advance_rate": rate(
                    held_resolved, "post_hold_advanced", "post_hold_resolved"
                ),
                "structurally_resolved": len(structurally_resolved),
                "clean_advance_rate": rate(
                    structurally_resolved, "clean_advance", "structural_resolved"
                ),
                "questionable_rate": rate(
                    structurally_resolved, "questionable", "structural_resolved"
                ),
                "two_sided_churn_rate": sum(
                    bool(row["two_sided_churn_10m_50pts"]) for row in group
                )
                / len(group),
                "median_local_failed_rails": median(
                    group, "local_failed_rails_10m_50pts"
                ),
                "median_local_owned_rails": median(
                    group, "local_owned_rails_10m_50pts"
                ),
                "profile_valid_roots": len(profile_valid),
                "hvn_unescaped_rate": (
                    sum(
                        row["terrain_class"] == "hvn_unescaped"
                        for row in profile_valid
                    )
                    / len(profile_valid)
                    if profile_valid
                    else None
                ),
                "median_abs_vpoc_distance_pts": median(
                    [
                        {
                            "value": abs(value)
                            if (
                                value := number(
                                    row.get("vpoc_signed_distance_pts")
                                )
                            )
                            is not None
                            else None
                        }
                        for row in profile_valid
                    ],
                    "value",
                ),
                "median_owned_to_test_s": median(group, "owned_to_test_s"),
                "median_test_to_verdict_s": median(group, "test_to_verdict_s"),
            }
        )
    return sorted(output, key=lambda row: DAYPART_ORDER[row["cohort"]])


Metric = tuple[str, Callable[[list[dict[str, Any]]], float | None]]


def lifecycle_metrics() -> tuple[Metric, ...]:
    return (
        (
            "first_test_hold_rate",
            lambda rows: (
                sum(bool(row["held"]) for row in rows) / len(rows)
                if rows
                else None
            ),
        ),
        (
            "post_hold_advance_rate",
            lambda rows: (
                sum(bool(row["post_hold_advanced"]) for row in rows)
                / len(rows)
                if (
                    rows := [
                        row
                        for row in rows
                        if row["held"] and row["post_hold_resolved"]
                    ]
                )
                else None
            ),
        ),
        (
            "clean_advance_rate",
            lambda rows: (
                sum(bool(row["clean_advance"]) for row in rows) / len(rows)
                if (
                    rows := [row for row in rows if row["structural_resolved"]]
                )
                else None
            ),
        ),
        (
            "questionable_rate",
            lambda rows: (
                sum(bool(row["questionable"]) for row in rows) / len(rows)
                if (
                    rows := [row for row in rows if row["structural_resolved"]]
                )
                else None
            ),
        ),
        (
            "two_sided_churn_rate",
            lambda rows: (
                sum(bool(row["two_sided_churn_10m_50pts"]) for row in rows)
                / len(rows)
                if rows
                else None
            ),
        ),
        (
            "hvn_unescaped_rate",
            lambda rows: (
                sum(row["terrain_class"] == "hvn_unescaped" for row in rows)
                / len(rows)
                if (rows := [row for row in rows if row["profile_valid"]])
                else None
            ),
        ),
    )


def morning_midday_comparison(
    rows: list[dict[str, Any]],
    samples: int,
) -> list[dict[str, Any]]:
    dates = sorted({row["date"] for row in rows})
    by_date_part = {
        (day, part): [
            row
            for row in rows
            if row["date"] == day and row["daypart"] == part
        ]
        for day in dates
        for part in ("morning_0930_1130", "midday_1130_1330")
    }
    rng = random.Random(20260726)
    output: list[dict[str, Any]] = []
    for name, metric in lifecycle_metrics():
        morning = metric(
            [
                row
                for row in rows
                if row["daypart"] == "morning_0930_1130"
            ]
        )
        midday = metric(
            [
                row
                for row in rows
                if row["daypart"] == "midday_1130_1330"
            ]
        )
        bootstrap: list[float] = []
        for _ in range(samples):
            morning_sample: list[dict[str, Any]] = []
            midday_sample: list[dict[str, Any]] = []
            for _ in dates:
                day = rng.choice(dates)
                morning_sample.extend(by_date_part[(day, "morning_0930_1130")])
                midday_sample.extend(by_date_part[(day, "midday_1130_1330")])
            left = metric(morning_sample)
            right = metric(midday_sample)
            if left is not None and right is not None:
                bootstrap.append(right - left)
        paired: list[float] = []
        for day in dates:
            left = metric(by_date_part[(day, "morning_0930_1130")])
            right = metric(by_date_part[(day, "midday_1130_1330")])
            if left is not None and right is not None:
                paired.append(right - left)
        output.append(
            {
                "metric": name,
                "morning": morning,
                "midday": midday,
                "midday_minus_morning": (
                    midday - morning
                    if midday is not None and morning is not None
                    else None
                ),
                "date_bootstrap_low_95": quantile(bootstrap, 0.025),
                "date_bootstrap_high_95": quantile(bootstrap, 0.975),
                "midday_higher_days": sum(value > 0 for value in paired),
                "midday_lower_days": sum(value < 0 for value in paired),
                "equal_days": sum(abs(value) < 1e-12 for value in paired),
                "eligible_days": len(paired),
                "median_paired_difference": statistics.median(paired)
                if paired
                else None,
            }
        )
    return output


def decision_rows(
    path: Path,
    start_date: str,
    end_date: str,
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for row in read_csv(path):
        if (
            row.get("decision_stage") != "first_test"
            or row.get("config") != PRIMARY_CONFIG
            or row.get("policy") not in FOCUS_POLICIES
            or not start_date <= row.get("date", "") <= end_date
        ):
            continue
        decision = parse_et(row["decision_et"])
        part = daypart(decision)
        if part == "outside_rth":
            continue
        rec: dict[str, Any] = dict(row)
        for key in (
            "advanced",
            "filled",
            "advance_captured",
            "advance_missed",
            "failure_exposed",
            "failure_avoided",
        ):
            rec[key] = truth(row.get(key))
        rec["daypart"] = part
        output.append(rec)
    return output


def policy_stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    advanced = [row for row in rows if row["advanced"]]
    failed = [row for row in rows if not row["advanced"]]
    captured = sum(row["advance_captured"] for row in advanced)
    exposed = sum(row["failure_exposed"] for row in failed)
    capture_rate = captured / len(advanced) if advanced else None
    exposure_rate = exposed / len(failed) if failed else None
    return {
        "roots": len(rows),
        "advanced": len(advanced),
        "failed": len(failed),
        "advance_captured": captured,
        "failure_exposed": exposed,
        "advance_capture_rate": capture_rate,
        "failure_exposure_rate": exposure_rate,
        "selectivity_advantage": (
            capture_rate - exposure_rate
            if capture_rate is not None and exposure_rate is not None
            else None
        ),
        "advance_missed": len(advanced) - captured,
        "failure_avoided": len(failed) - exposed,
        "avoided_minus_missed": (
            (len(failed) - exposed) - (len(advanced) - captured)
        ),
        "advanced_median_entry_improvement_pts": median(
            [row for row in advanced if row["advance_captured"]],
            "entry_improvement_vs_market_pts",
        ),
        "advanced_median_mae_pts": median(
            [row for row in advanced if row["advance_captured"]],
            "mae_pts",
        ),
    }


def policy_window_summary(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        for cohort in cohorts(str(row["daypart"])):
            groups[(cohort, "all", row["policy"])].append(row)
            if row["terrain_class"] == "hvn_unescaped":
                groups[(cohort, "hvn_unescaped", row["policy"])].append(row)
    output = [
        {
            "cohort": cohort,
            "terrain_scope": terrain_scope,
            "policy": policy,
            **policy_stats(group),
        }
        for (cohort, terrain_scope, policy), group in groups.items()
    ]
    return sorted(
        output,
        key=lambda row: (
            DAYPART_ORDER[row["cohort"]],
            row["terrain_scope"],
            row["policy"],
        ),
    )


def policy_cluster_robustness(
    rows: list[dict[str, Any]],
    samples: int,
) -> list[dict[str, Any]]:
    specs = (
        ("full_rth", "all", "vpoc_gate"),
        ("non_midday_all", "all", "vpoc_gate"),
        ("core_non_midday", "all", "vpoc_gate"),
        ("morning_0930_1130", "all", "vpoc_gate"),
        ("midday_1130_1330", "all", "vpoc_gate"),
        ("afternoon_1330_1530", "all", "vpoc_gate"),
        ("full_rth", "hvn_unescaped", "hvn_escape_touch"),
        ("non_midday_all", "hvn_unescaped", "hvn_escape_touch"),
        ("core_non_midday", "hvn_unescaped", "hvn_escape_touch"),
        ("morning_0930_1130", "hvn_unescaped", "hvn_escape_touch"),
        ("midday_1130_1330", "hvn_unescaped", "hvn_escape_touch"),
        ("afternoon_1330_1530", "hvn_unescaped", "hvn_escape_touch"),
        ("full_rth", "hvn_unescaped", "hvn_escape_two_sided"),
        ("non_midday_all", "hvn_unescaped", "hvn_escape_two_sided"),
        ("core_non_midday", "hvn_unescaped", "hvn_escape_two_sided"),
        ("morning_0930_1130", "hvn_unescaped", "hvn_escape_two_sided"),
        ("midday_1130_1330", "hvn_unescaped", "hvn_escape_two_sided"),
        ("afternoon_1330_1530", "hvn_unescaped", "hvn_escape_two_sided"),
        ("full_rth", "hvn_unescaped", "passive_band_30s"),
        ("non_midday_all", "hvn_unescaped", "passive_band_30s"),
        ("midday_1130_1330", "hvn_unescaped", "passive_band_30s"),
    )
    dates = sorted({row["date"] for row in rows})
    rng = random.Random(20260726)
    output: list[dict[str, Any]] = []
    for cohort, terrain_scope, policy in specs:
        selected = [
            row
            for row in rows
            if cohort in cohorts(str(row["daypart"]))
            and row["policy"] == policy
            and (
                terrain_scope == "all"
                or row["terrain_class"] == terrain_scope
            )
        ]
        observed = policy_stats(selected)
        by_date = {
            day: [row for row in selected if row["date"] == day]
            for day in dates
        }
        bootstrap: list[float] = []
        for _ in range(samples):
            sample: list[dict[str, Any]] = []
            for _ in dates:
                sample.extend(by_date[rng.choice(dates)])
            value = policy_stats(sample)["selectivity_advantage"]
            if value is not None:
                bootstrap.append(value)
        day_values = [
            value
            for day in dates
            if (
                value := policy_stats(by_date[day])["selectivity_advantage"]
            )
            is not None
        ]
        leave_one_out = [
            value
            for omitted in dates
            if (
                value := policy_stats(
                    [
                        row
                        for day in dates
                        if day != omitted
                        for row in by_date[day]
                    ]
                )["selectivity_advantage"]
            )
            is not None
        ]
        output.append(
            {
                "cohort": cohort,
                "terrain_scope": terrain_scope,
                "policy": policy,
                **observed,
                "date_bootstrap_low_95": quantile(bootstrap, 0.025),
                "date_bootstrap_high_95": quantile(bootstrap, 0.975),
                "positive_days": sum(value > 0 for value in day_values),
                "negative_days": sum(value < 0 for value in day_values),
                "zero_days": sum(abs(value) < 1e-12 for value in day_values),
                "eligible_days": len(day_values),
                "leave_one_day_out_min": min(leave_one_out)
                if leave_one_out
                else None,
                "leave_one_day_out_max": max(leave_one_out)
                if leave_one_out
                else None,
            }
        )
    return output


def terrain_composition(
    lifecycle: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in lifecycle:
        if not row["profile_valid"]:
            continue
        for cohort in cohorts(str(row["daypart"])):
            groups[(cohort, row["terrain_class"])].append(row)
    output: list[dict[str, Any]] = []
    for (cohort, terrain), rows in groups.items():
        resolved = [row for row in rows if row["structural_resolved"]]
        output.append(
            {
                "cohort": cohort,
                "terrain_class": terrain,
                "roots": len(rows),
                "share": None,
                "first_test_hold_rate": sum(row["held"] for row in rows)
                / len(rows),
                "clean_advance_rate": (
                    sum(row["clean_advance"] for row in resolved) / len(resolved)
                    if resolved
                    else None
                ),
                "two_sided_churn_rate": sum(
                    row["two_sided_churn_10m_50pts"] for row in rows
                )
                / len(rows),
            }
        )
    totals = defaultdict(int)
    for row in output:
        totals[row["cohort"]] += int(row["roots"])
    for row in output:
        row["share"] = int(row["roots"]) / totals[row["cohort"]]
    return sorted(
        output,
        key=lambda row: (
            DAYPART_ORDER[row["cohort"]],
            row["terrain_class"],
        ),
    )


def et_timestamp_us(day: str, hour: int, minute: int) -> int:
    value = datetime.strptime(day, "%Y-%m-%d").replace(
        hour=hour,
        minute=minute,
        second=0,
        microsecond=0,
        tzinfo=NY,
    )
    return int(value.timestamp() * 1_000_000)


def price_windows(
    dates: list[str],
    symbol_dir: str,
) -> list[dict[str, Any]]:
    bounds = {
        "morning_0930_1130": ((9, 30), (11, 30)),
        "midday_1130_1330": ((11, 30), (13, 30)),
        "afternoon_1330_1530": ((13, 30), (15, 30)),
        "late_1530_1600": ((15, 30), (16, 0)),
    }
    output: list[dict[str, Any]] = []
    for day in dates:
        start = datetime.strptime(day, "%Y-%m-%d").replace(
            hour=9, minute=30, tzinfo=NY
        )
        end = datetime.strptime(day, "%Y-%m-%d").replace(
            hour=16, minute=0, tzinfo=NY
        )
        frame = load_capture_window(
            "ticks",
            symbol_dir,
            start,
            end,
            tick_columns(),
        )
        times = [int(value) for value in frame["timestamp_us"].to_list()]
        prices = [float(value) for value in frame["price"].to_list()]
        for part, (left, right) in bounds.items():
            lo = bisect.bisect_left(
                times, et_timestamp_us(day, left[0], left[1])
            )
            hi = bisect.bisect_left(
                times, et_timestamp_us(day, right[0], right[1])
            )
            window = prices[lo:hi]
            if not window:
                continue
            price_range = max(window) - min(window)
            net = window[-1] - window[0]
            output.append(
                {
                    "date": day,
                    "daypart": part,
                    "trade_rows": len(window),
                    "start_price": window[0],
                    "end_price": window[-1],
                    "high_price": max(window),
                    "low_price": min(window),
                    "range_pts": price_range,
                    "net_move_pts": net,
                    "path_efficiency": abs(net) / price_range
                    if price_range > 0
                    else None,
                    "direction": (
                        "Demand" if net > 0 else "Supply" if net < 0 else "Flat"
                    ),
                }
            )
    return output


def daily_window_rows(
    lifecycle: list[dict[str, Any]],
    prices: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    by_date_part: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in lifecycle:
        by_date_part[(row["date"], row["daypart"])].append(row)
    price_index = {
        (row["date"], row["daypart"]): row for row in prices
    }
    output: list[dict[str, Any]] = []
    for key, price_row in sorted(price_index.items()):
        group = by_date_part.get(key, [])
        held = [row for row in group if row["held"]]
        held_resolved = [
            row for row in held if row["post_hold_resolved"]
        ]
        structurally_resolved = [
            row for row in group if row["structural_resolved"]
        ]
        output.append(
            {
                **price_row,
                "tested_roots": len(group),
                "first_test_hold_rate": (
                    sum(row["held"] for row in group) / len(group)
                    if group
                    else None
                ),
                "post_hold_advance_rate": (
                    sum(row["post_hold_advanced"] for row in held_resolved)
                    / len(held_resolved)
                    if held_resolved
                    else None
                ),
                "clean_advance_rate": (
                    sum(row["clean_advance"] for row in structurally_resolved)
                    / len(structurally_resolved)
                    if structurally_resolved
                    else None
                ),
                "two_sided_churn_rate": (
                    sum(row["two_sided_churn_10m_50pts"] for row in group)
                    / len(group)
                    if group
                    else None
                ),
                "clean_demand": sum(
                    row["clean_advance"] and row["side"] == "Demand"
                    for row in group
                ),
                "clean_supply": sum(
                    row["clean_advance"] and row["side"] == "Supply"
                    for row in group
                ),
            }
        )
    return output


def midday_afternoon_rows(
    daily: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    index = {(row["date"], row["daypart"]): row for row in daily}
    output: list[dict[str, Any]] = []
    for day in sorted({row["date"] for row in daily}):
        midday = index.get((day, "midday_1130_1330"))
        afternoon = index.get((day, "afternoon_1330_1530"))
        if midday is None or afternoon is None:
            continue
        midday_net = number(midday.get("net_move_pts")) or 0.0
        afternoon_net = number(afternoon.get("net_move_pts")) or 0.0
        relation = (
            "flat"
            if abs(midday_net) < 1e-9 or abs(afternoon_net) < 1e-9
            else "continuation"
            if midday_net * afternoon_net > 0
            else "counter"
        )
        output.append(
            {
                "date": day,
                "midday_net_pts": midday_net,
                "midday_range_pts": midday["range_pts"],
                "midday_efficiency": midday["path_efficiency"],
                "midday_churn_rate": midday["two_sided_churn_rate"],
                "midday_clean_advance_rate": midday["clean_advance_rate"],
                "midday_clean_demand": midday["clean_demand"],
                "midday_clean_supply": midday["clean_supply"],
                "afternoon_net_pts": afternoon_net,
                "afternoon_range_pts": afternoon["range_pts"],
                "afternoon_efficiency": afternoon["path_efficiency"],
                "afternoon_churn_rate": afternoon["two_sided_churn_rate"],
                "afternoon_clean_advance_rate": afternoon[
                    "clean_advance_rate"
                ],
                "afternoon_clean_demand": afternoon["clean_demand"],
                "afternoon_clean_supply": afternoon["clean_supply"],
                "price_direction_relation": relation,
            }
        )
    return output


def afternoon_relation_policy(
    decisions: list[dict[str, Any]],
    transitions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    relation = {row["date"]: row["price_direction_relation"] for row in transitions}
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in decisions:
        if row["daypart"] != "afternoon_1330_1530":
            continue
        day_relation = relation.get(row["date"], "")
        if not day_relation:
            continue
        groups[(day_relation, "all", row["policy"])].append(row)
        if row["terrain_class"] == "hvn_unescaped":
            groups[(day_relation, "hvn_unescaped", row["policy"])].append(row)
    return sorted(
        (
            {
                "price_direction_relation": relation_name,
                "terrain_scope": terrain_scope,
                "policy": policy,
                **policy_stats(rows),
                "dates": "|".join(sorted({row["date"] for row in rows})),
            }
            for (relation_name, terrain_scope, policy), rows in groups.items()
        ),
        key=lambda row: (
            row["price_direction_relation"],
            row["terrain_scope"],
            row["policy"],
        ),
    )


def afternoon_midday_role_policy(
    decisions: list[dict[str, Any]],
    transitions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    midday_side = {
        row["date"]: (
            "Demand" if row["midday_net_pts"] > 0 else "Supply"
        )
        for row in transitions
        if abs(number(row.get("midday_net_pts")) or 0.0) > 1e-9
    }
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in decisions:
        if row["daypart"] != "afternoon_1330_1530":
            continue
        side = midday_side.get(row["date"])
        if side is None:
            continue
        role = "with_midday" if row["side"] == side else "against_midday"
        groups[(role, "all", row["policy"])].append(row)
        if row["terrain_class"] == "hvn_unescaped":
            groups[(role, "hvn_unescaped", row["policy"])].append(row)
    return sorted(
        (
            {
                "midday_role": role,
                "terrain_scope": terrain_scope,
                "policy": policy,
                **policy_stats(rows),
                "dates": "|".join(sorted({row["date"] for row in rows})),
            }
            for (role, terrain_scope, policy), rows in groups.items()
        ),
        key=lambda row: (
            row["midday_role"],
            row["terrain_scope"],
            row["policy"],
        ),
    )


def build_report(
    lifecycle_summary_rows: list[dict[str, Any]],
    morning_midday: list[dict[str, Any]],
    policy_summary_rows: list[dict[str, Any]],
    robustness: list[dict[str, Any]],
    transitions: list[dict[str, Any]],
    afternoon_relation: list[dict[str, Any]],
    afternoon_midday_role: list[dict[str, Any]],
) -> str:
    life = {row["cohort"]: row for row in lifecycle_summary_rows}
    comparison = {row["metric"]: row for row in morning_midday}
    policy = {
        (row["cohort"], row["terrain_scope"], row["policy"]): row
        for row in policy_summary_rows
    }
    lines = [
        "# Direct-Conversion Time-Window Audit",
        "",
        "Windows are classified by first-test timestamp. Lifecycle statistics include every tested consumed rail; policy statistics include only roots that later held their first test.",
        "",
        "## Lifecycle By Window",
        "",
        "| cohort | tested | first-test hold | post-hold advance | clean advance | questionable | two-sided churn | unescaped HVN |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for cohort in (
        "morning_0930_1130",
        "midday_1130_1330",
        "afternoon_1330_1530",
        "late_1530_1600",
        "full_rth",
        "non_midday_all",
        "core_non_midday",
    ):
        row = life.get(cohort)
        if row is None:
            continue
        lines.append(
            f"| {cohort} | {row['tested_roots']} | "
            f"{fmt(row['first_test_hold_rate'])} | "
            f"{fmt(row['post_hold_advance_rate'])} | "
            f"{fmt(row['clean_advance_rate'])} | "
            f"{fmt(row['questionable_rate'])} | "
            f"{fmt(row['two_sided_churn_rate'])} | "
            f"{fmt(row['hvn_unescaped_rate'])} |"
        )

    lines.extend(
        [
            "",
            "## Midday Minus Morning",
            "",
            "| metric | morning | midday | difference | date-bootstrap 95% | paired day signs |",
            "|---|---:|---:|---:|---:|---:|",
        ]
    )
    for name in (
        "first_test_hold_rate",
        "post_hold_advance_rate",
        "clean_advance_rate",
        "questionable_rate",
        "two_sided_churn_rate",
        "hvn_unescaped_rate",
    ):
        row = comparison[name]
        lines.append(
            f"| {name} | {fmt(row['morning'])} | {fmt(row['midday'])} | "
            f"{fmt(row['midday_minus_morning'])} | "
            f"{fmt(row['date_bootstrap_low_95'])} to "
            f"{fmt(row['date_bootstrap_high_95'])} | "
            f"+{row['midday_higher_days']}/-{row['midday_lower_days']}/"
            f"0={row['equal_days']} |"
        )

    lines.extend(
        [
            "",
            "## Held-Test Execution Policies",
            "",
            "| cohort | terrain | policy | roots | advance capture | failure exposure | selectivity | success price improvement |",
            "|---|---|---|---:|---:|---:|---:|---:|",
        ]
    )
    for cohort, terrain_scope, policy_name in (
        ("full_rth", "hvn_unescaped", "hvn_escape_touch"),
        ("non_midday_all", "hvn_unescaped", "hvn_escape_touch"),
        ("core_non_midday", "hvn_unescaped", "hvn_escape_touch"),
        ("morning_0930_1130", "hvn_unescaped", "hvn_escape_touch"),
        ("midday_1130_1330", "hvn_unescaped", "hvn_escape_touch"),
        ("afternoon_1330_1530", "hvn_unescaped", "hvn_escape_touch"),
        ("full_rth", "hvn_unescaped", "hvn_escape_two_sided"),
        ("non_midday_all", "hvn_unescaped", "hvn_escape_two_sided"),
        ("morning_0930_1130", "hvn_unescaped", "hvn_escape_two_sided"),
        ("midday_1130_1330", "hvn_unescaped", "hvn_escape_two_sided"),
        ("afternoon_1330_1530", "hvn_unescaped", "hvn_escape_two_sided"),
        ("full_rth", "all", "vpoc_gate"),
        ("non_midday_all", "all", "vpoc_gate"),
        ("morning_0930_1130", "all", "vpoc_gate"),
        ("midday_1130_1330", "all", "vpoc_gate"),
        ("afternoon_1330_1530", "all", "vpoc_gate"),
        ("full_rth", "hvn_unescaped", "passive_band_30s"),
        ("non_midday_all", "hvn_unescaped", "passive_band_30s"),
        ("midday_1130_1330", "hvn_unescaped", "passive_band_30s"),
    ):
        row = policy.get((cohort, terrain_scope, policy_name))
        if row is None:
            continue
        lines.append(
            f"| {cohort} | {terrain_scope} | {policy_name} | "
            f"{row['roots']} | {fmt(row['advance_capture_rate'])} | "
            f"{fmt(row['failure_exposure_rate'])} | "
            f"{fmt(row['selectivity_advantage'])} | "
            f"{fmt(row['advanced_median_entry_improvement_pts'])} |"
        )

    robust = {
        (row["cohort"], row["terrain_scope"], row["policy"]): row
        for row in robustness
    }
    lines.extend(
        [
            "",
            "## Exclusion Robustness",
            "",
            "| cohort | terrain | policy | selectivity | date-bootstrap 95% | day signs | leave-one-day-out |",
            "|---|---|---|---:|---:|---:|---:|",
        ]
    )
    for key in (
        ("full_rth", "hvn_unescaped", "hvn_escape_touch"),
        ("non_midday_all", "hvn_unescaped", "hvn_escape_touch"),
        ("core_non_midday", "hvn_unescaped", "hvn_escape_touch"),
        ("morning_0930_1130", "hvn_unescaped", "hvn_escape_touch"),
        ("midday_1130_1330", "hvn_unescaped", "hvn_escape_touch"),
        ("afternoon_1330_1530", "hvn_unescaped", "hvn_escape_touch"),
        ("full_rth", "hvn_unescaped", "hvn_escape_two_sided"),
        ("non_midday_all", "hvn_unescaped", "hvn_escape_two_sided"),
        ("full_rth", "all", "vpoc_gate"),
        ("non_midday_all", "all", "vpoc_gate"),
    ):
        row = robust[key]
        lines.append(
            f"| {row['cohort']} | {row['terrain_scope']} | "
            f"{row['policy']} | {fmt(row['selectivity_advantage'])} | "
            f"{fmt(row['date_bootstrap_low_95'])} to "
            f"{fmt(row['date_bootstrap_high_95'])} | "
            f"+{row['positive_days']}/-{row['negative_days']}/"
            f"0={row['zero_days']} | "
            f"{fmt(row['leave_one_day_out_min'])} to "
            f"{fmt(row['leave_one_day_out_max'])} |"
        )

    lines.extend(
        [
            "",
            "## Midday To Afternoon",
            "",
            "| date | midday net/eff | midday churn | midday clean D/S | afternoon net/eff | afternoon churn | afternoon clean D/S | relation |",
            "|---|---:|---:|---:|---:|---:|---:|---|",
        ]
    )
    for row in transitions:
        lines.append(
            f"| {row['date']} | {fmt(row['midday_net_pts'], 1)} / "
            f"{fmt(row['midday_efficiency'])} | "
            f"{fmt(row['midday_churn_rate'])} | "
            f"{row['midday_clean_demand']}/{row['midday_clean_supply']} | "
            f"{fmt(row['afternoon_net_pts'], 1)} / "
            f"{fmt(row['afternoon_efficiency'])} | "
            f"{fmt(row['afternoon_churn_rate'])} | "
            f"{row['afternoon_clean_demand']}/"
            f"{row['afternoon_clean_supply']} | "
            f"{row['price_direction_relation']} |"
        )

    lines.extend(
        [
            "",
            "## Afternoon Conditional On Midday Direction",
            "",
            "| relation | terrain | policy | roots | advance capture | failure exposure | selectivity | dates |",
            "|---|---|---|---:|---:|---:|---:|---|",
        ]
    )
    for row in afternoon_relation:
        if (
            row["policy"]
            not in {"hvn_escape_touch", "hvn_escape_two_sided", "vpoc_gate"}
            or (
                row["policy"].startswith("hvn_")
                and row["terrain_scope"] != "hvn_unescaped"
            )
            or (
                row["policy"] == "vpoc_gate"
                and row["terrain_scope"] != "all"
            )
        ):
            continue
        lines.append(
            f"| {row['price_direction_relation']} | "
            f"{row['terrain_scope']} | {row['policy']} | {row['roots']} | "
            f"{fmt(row['advance_capture_rate'])} | "
            f"{fmt(row['failure_exposure_rate'])} | "
            f"{fmt(row['selectivity_advantage'])} | {row['dates']} |"
        )

    lines.extend(
        [
            "",
            "## Afternoon Role Known At 13:30",
            "",
            "Role is defined only by whether the conversion side agrees with the completed midday net move.",
            "",
            "| role | terrain | policy | roots | advance capture | failure exposure | selectivity | dates |",
            "|---|---|---|---:|---:|---:|---:|---|",
        ]
    )
    for row in afternoon_midday_role:
        if (
            row["policy"]
            not in {"hvn_escape_touch", "hvn_escape_two_sided", "vpoc_gate"}
            or (
                row["policy"].startswith("hvn_")
                and row["terrain_scope"] != "hvn_unescaped"
            )
            or (
                row["policy"] == "vpoc_gate"
                and row["terrain_scope"] != "all"
            )
        ):
            continue
        lines.append(
            f"| {row['midday_role']} | {row['terrain_scope']} | "
            f"{row['policy']} | {row['roots']} | "
            f"{fmt(row['advance_capture_rate'])} | "
            f"{fmt(row['failure_exposure_rate'])} | "
            f"{fmt(row['selectivity_advantage'])} | {row['dates']} |"
        )

    lines.extend(
        [
            "",
            "## Interpretation Boundary",
            "",
            "- `Questionable` means failed first test or held first test followed by root failure before a favorable successor. It is intentionally structural, not a fixed-tick outcome.",
            "- Two-sided churn is synthetic LL evidence: both demand and supply rails failed within 50 points during the ten minutes before first test.",
            "- Window exclusion is evaluated both pooled and within unescaped HVNs so a changed terrain mix cannot manufacture the result.",
            "- Seven sessions remain discovery. Date-bootstrap intervals are sensitivity bounds, not held-out validation.",
            "- No EAR or LevelLedger runtime behavior changed.",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> None:
    args = parse_args()
    profiles = profile_index(args.profile_csv)
    lifecycle = lifecycle_rows(
        args.lineage_csv,
        profiles,
        args.start_date,
        args.end_date,
    )
    decisions = decision_rows(
        args.decisions_csv,
        args.start_date,
        args.end_date,
    )
    if not lifecycle or not decisions:
        raise SystemExit("no lifecycle or policy rows matched")

    lifecycle_summary_rows = lifecycle_summary(lifecycle)
    morning_midday = morning_midday_comparison(
        lifecycle, args.bootstrap_samples
    )
    policy_summary_rows = policy_window_summary(decisions)
    robustness = policy_cluster_robustness(
        decisions, args.bootstrap_samples
    )
    composition = terrain_composition(lifecycle)
    prices = price_windows(
        sorted({row["date"] for row in lifecycle}),
        args.symbol_dir,
    )
    daily = daily_window_rows(lifecycle, prices)
    transitions = midday_afternoon_rows(daily)
    afternoon_relation = afternoon_relation_policy(decisions, transitions)
    afternoon_midday_role = afternoon_midday_role_policy(
        decisions, transitions
    )

    args.out_dir.mkdir(parents=True, exist_ok=True)
    write_csv(args.out_dir / "lifecycle_rows.csv", lifecycle)
    write_csv(args.out_dir / "lifecycle_window_summary.csv", lifecycle_summary_rows)
    write_csv(args.out_dir / "morning_midday_comparison.csv", morning_midday)
    write_csv(args.out_dir / "terrain_composition.csv", composition)
    write_csv(args.out_dir / "policy_window_summary.csv", policy_summary_rows)
    write_csv(args.out_dir / "policy_cluster_robustness.csv", robustness)
    write_csv(args.out_dir / "daily_window_summary.csv", daily)
    write_csv(args.out_dir / "midday_afternoon_transition.csv", transitions)
    write_csv(
        args.out_dir / "afternoon_relation_policy_summary.csv",
        afternoon_relation,
    )
    write_csv(
        args.out_dir / "afternoon_midday_role_policy_summary.csv",
        afternoon_midday_role,
    )
    report = build_report(
        lifecycle_summary_rows,
        morning_midday,
        policy_summary_rows,
        robustness,
        transitions,
        afternoon_relation,
        afternoon_midday_role,
    )
    (args.out_dir / "findings.md").write_text(report, encoding="utf-8")
    print(report, end="")
    print(
        f"\nwrote {args.out_dir} lifecycle={len(lifecycle)} "
        f"policy_rows={len(decisions)}"
    )


if __name__ == "__main__":
    main()
