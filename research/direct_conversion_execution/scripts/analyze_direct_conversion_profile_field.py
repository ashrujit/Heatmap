"""Outcome analysis for point-in-time direct-conversion profile location."""

from __future__ import annotations

import argparse
import csv
import math
from collections import defaultdict
from pathlib import Path
from statistics import median
from typing import Any, Callable, Iterable

from _paths import OUTPUT_ROOT

DEFAULT_LOCATIONS = (
    OUTPUT_ROOT
    / "direct_conversion_profile_field_20260716_20260724"
    / "profile_locations.csv"
)
DEFAULT_LINEAGE = (
    OUTPUT_ROOT / "direct_conversion_sponsor_lineage" / "lineage.csv"
)
DEFAULT_STEPS = (
    OUTPUT_ROOT
    / "direct_conversion_road_steps_20260717_20260724"
    / "steps.csv"
)
DEFAULT_OUT = DEFAULT_LOCATIONS.parent
PROFILE_FEATURES = (
    "volume_percentile",
    "volume_to_vpoc_ratio",
    "local_volume_ratio",
    "valley_ratio",
    "vpoc_signed_distance_pts",
    "favorable_edge_distance_pts",
    "adverse_edge_distance_pts",
    "current_favorable_displacement_pts",
    "current_vpoc_signed_distance_pts",
    "current_hvn_escape_margin_pts",
    "current_next_hvn_signed_gap_pts",
)
LOCATION_FIELDS = (
    "profile_valid",
    "invalid_reason",
    "topology",
    "profile_age_s",
    "capture_complete",
    "profile_tick_rows",
    "profile_low",
    "profile_high",
    "profile_range_pts",
    "profile_bins",
    "touched_bins",
    "profile_total_volume",
    "anchor_bin_low",
    "anchor_bin_volume",
    "anchor_smooth_volume",
    *PROFILE_FEATURES,
    "hvn_threshold",
    "lvn_threshold",
    "vpoc_price",
    "left_hvn_price",
    "left_hvn_distance_pts",
    "right_hvn_price",
    "right_hvn_distance_pts",
    "between_hvns",
    "hvn_region_low",
    "hvn_region_high",
    "current_price",
    "current_beyond_favorable_hvn_edge",
    "field_state",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--locations", type=Path, default=DEFAULT_LOCATIONS)
    parser.add_argument("--lineage", type=Path, default=DEFAULT_LINEAGE)
    parser.add_argument("--steps", type=Path, default=DEFAULT_STEPS)
    parser.add_argument("--start-date", default="2026-07-16")
    parser.add_argument("--end-date", default="2026-07-24")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    return parser.parse_args()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def in_range(day: str, start: str, end: str) -> bool:
    return start <= day <= end


def number(row: dict[str, Any], key: str) -> float | None:
    value = row.get(key)
    if value in (None, ""):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def truth(value: Any) -> bool:
    return value is True or value == "True"


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


def fmt(value: Any, digits: int = 3) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:.{digits}f}" if math.isfinite(value) else ""
    return str(value)


def config_key(row: dict[str, Any]) -> tuple[str, str]:
    return str(row["scope"]), str(row["bin_points"])


def location_key(
    *,
    source: str,
    date: str,
    root_id: str,
    step_ordinal: str,
    query_kind: str,
    scope: str,
    bin_points: str,
) -> tuple[str, str, str, str, str, str, str]:
    return (
        source,
        date,
        root_id,
        step_ordinal,
        query_kind,
        scope,
        bin_points,
    )


def location_index(
    rows: list[dict[str, str]],
) -> tuple[
    dict[tuple[str, str, str, str, str, str, str], dict[str, str]],
    list[tuple[str, str]],
]:
    index: dict[
        tuple[str, str, str, str, str, str, str], dict[str, str]
    ] = {}
    configs: set[tuple[str, str]] = set()
    for row in rows:
        key = location_key(
            source=row["source"],
            date=row["date"],
            root_id=row["root_id"],
            step_ordinal=row.get("step_ordinal", ""),
            query_kind=row["query_kind"],
            scope=row["scope"],
            bin_points=row["bin_points"],
        )
        index[key] = row
        configs.add(config_key(row))
    return index, sorted(configs, key=lambda item: (item[0], float(item[1])))


def find_location(
    index: dict[
        tuple[str, str, str, str, str, str, str], dict[str, str]
    ],
    *,
    source: str,
    date: str,
    root_id: str,
    step_ordinal: str = "",
    query_kind: str,
    scope: str,
    bin_points: str,
) -> dict[str, str] | None:
    return index.get(
        location_key(
            source=source,
            date=date,
            root_id=root_id,
            step_ordinal=step_ordinal,
            query_kind=query_kind,
            scope=scope,
            bin_points=bin_points,
        )
    )


def prefixed_location(
    prefix: str, location: dict[str, str] | None
) -> dict[str, Any]:
    if location is None:
        return {f"{prefix}_{field}": "" for field in LOCATION_FIELDS}
    return {
        f"{prefix}_{field}": location.get(field, "")
        for field in LOCATION_FIELDS
    }


def tested_outcome(row: dict[str, str]) -> bool | None:
    verdict = row.get("root_first_test_verdict")
    if verdict == "HELD_FIRST_TEST":
        return True
    if verdict == "FAILED_FIRST_TEST":
        return False
    return None


def hold_outcome(row: dict[str, str]) -> bool | None:
    outcome = row.get("hold_structural_outcome")
    if outcome == "ADVANCED_AFTER_FIRST_HOLD":
        return True
    if outcome == "ROOT_FAILED_AFTER_FIRST_HOLD":
        return False
    return None


def entry_outcome(row: dict[str, str]) -> bool | None:
    outcome = row.get("entry_structural_outcome")
    if outcome == "ADVANCED_AFTER_ENTRY":
        return True
    if outcome == "ROOT_FAILED_AFTER_ENTRY":
        return False
    return None


def root_joined_rows(
    lineage: list[dict[str, str]],
    index: dict[
        tuple[str, str, str, str, str, str, str], dict[str, str]
    ],
    configs: list[tuple[str, str]],
    start: str,
    end: str,
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for root in lineage:
        if not in_range(root["date"], start, end):
            continue
        for scope, bin_points in configs:
            base: dict[str, Any] = {
                "date": root["date"],
                "root_id": root["root_id"],
                "side": root["side"],
                "root_owned_et": root.get("root_owned_et", ""),
                "root_lo": root.get("root_lo", ""),
                "root_hi": root.get("root_hi", ""),
                "root_first_test_verdict": root.get(
                    "root_first_test_verdict", ""
                ),
                "root_first_tested_et": root.get(
                    "root_first_tested_et", ""
                ),
                "root_first_test_resolved_et": root.get(
                    "root_first_test_resolved_et", ""
                ),
                "hold_structural_outcome": root.get(
                    "hold_structural_outcome", ""
                ),
                "traded": root.get("traded", ""),
                "entry_roles": root.get("entry_roles", ""),
                "first_entry_et": root.get("first_entry_et", ""),
                "entry_structural_outcome": root.get(
                    "entry_structural_outcome", ""
                ),
                "pre_10m_50pts_two_sided_fail": root.get(
                    "pre_10m_50pts_two_sided_fail", ""
                ),
                "scope": scope,
                "bin_points": bin_points,
                "first_test_held": tested_outcome(root),
                "post_hold_advanced": hold_outcome(root),
                "entry_advanced": entry_outcome(root),
            }
            for kind, prefix in (
                ("root_owned", "owned"),
                ("first_test", "test"),
                ("first_hold", "hold"),
                ("first_entry", "entry"),
            ):
                location = find_location(
                    index,
                    source="lineage",
                    date=root["date"],
                    root_id=root["root_id"],
                    query_kind=kind,
                    scope=scope,
                    bin_points=bin_points,
                )
                base.update(prefixed_location(prefix, location))

            for later in ("test", "hold", "entry"):
                for feature in (
                    "anchor_bin_volume",
                    "anchor_smooth_volume",
                    "volume_percentile",
                    "local_volume_ratio",
                ):
                    start_value = number(base, f"owned_{feature}")
                    later_value = number(base, f"{later}_{feature}")
                    base[f"{later}_{feature}_change_from_owned"] = (
                        later_value - start_value
                        if start_value is not None and later_value is not None
                        else ""
                    )
                owned_topology = base.get("owned_topology")
                later_topology = base.get(f"{later}_topology")
                base[f"{later}_topology_changed_from_owned"] = (
                    bool(
                        owned_topology
                        and later_topology
                        and owned_topology != "invalid"
                        and later_topology != "invalid"
                        and later_topology != owned_topology
                    )
                    if later_topology
                    else ""
                )
            output.append(base)
    return output


def step_joined_rows(
    steps: list[dict[str, str]],
    index: dict[
        tuple[str, str, str, str, str, str, str], dict[str, str]
    ],
    configs: list[tuple[str, str]],
    start: str,
    end: str,
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for step in steps:
        if not in_range(step["date"], start, end):
            continue
        terminal_promotion: bool | None = None
        if step["resolution"] == "SPONSOR_ADVANCED":
            terminal_promotion = True
        elif step["resolution"] == "ROOT_FAILED":
            terminal_promotion = False
        for scope, bin_points in configs:
            base: dict[str, Any] = {
                "date": step["date"],
                "root_id": step["root_id"],
                "side": step["side"],
                "step_ordinal": step["step_ordinal"],
                "relation": step["relation"],
                "resolution": step["resolution"],
                "step_success": truth(step.get("step_success")),
                "terminal_sponsor_advanced": terminal_promotion,
                "start_et": step["start_et"],
                "start_price": step["start_price"],
                "entry_et": step.get("entry_et", ""),
                "entry_roles": step.get("entry_roles", ""),
                "root_outcome": step.get("root_outcome", ""),
                "scope": scope,
                "bin_points": bin_points,
                "checkpoint_1000ms_active": step.get(
                    "checkpoint_1000ms_active", ""
                ),
                "checkpoint_1000ms_book_valid": step.get(
                    "checkpoint_1000ms_book_valid", ""
                ),
                "checkpoint_1000ms_winner_net_provision_qty": step.get(
                    "checkpoint_1000ms_winner_net_provision_qty", ""
                ),
                "checkpoint_1000ms_winner_add_qty": step.get(
                    "checkpoint_1000ms_winner_add_qty", ""
                ),
                "checkpoint_1000ms_winner_remove_qty": step.get(
                    "checkpoint_1000ms_winner_remove_qty", ""
                ),
                "checkpoint_1000ms_favorable_displacement_ticks": step.get(
                    "checkpoint_1000ms_favorable_displacement_ticks", ""
                ),
                "checkpoint_1000ms_step_depth_ticks": step.get(
                    "checkpoint_1000ms_step_depth_ticks", ""
                ),
                "checkpoint_1000ms_road_remaining_ticks": step.get(
                    "checkpoint_1000ms_road_remaining_ticks", ""
                ),
                "entry_state_book_valid": step.get(
                    "entry_state_book_valid", ""
                ),
                "entry_state_winner_net_provision_qty": step.get(
                    "entry_state_winner_net_provision_qty", ""
                ),
                "entry_step_age_s": step.get("entry_step_age_s", ""),
                "entry_step_depth_ticks": step.get(
                    "entry_step_depth_ticks", ""
                ),
                "entry_road_remaining_ticks": step.get(
                    "entry_road_remaining_ticks", ""
                ),
            }
            for kind, prefix in (
                ("step_start", "start"),
                ("step_entry", "entry"),
            ):
                location = find_location(
                    index,
                    source="steps",
                    date=step["date"],
                    root_id=step["root_id"],
                    step_ordinal=step["step_ordinal"],
                    query_kind=kind,
                    scope=scope,
                    bin_points=bin_points,
                )
                base.update(prefixed_location(prefix, location))
            output.append(base)
    return output


def outcome_summary(
    rows: list[dict[str, Any]],
    *,
    population: str,
    outcome_key: str,
    location_prefix: str,
) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        outcome = row.get(outcome_key)
        topology = str(row.get(f"{location_prefix}_topology") or "")
        valid = truth(row.get(f"{location_prefix}_profile_valid"))
        if outcome is None or not valid or not topology:
            continue
        groups[(str(row["scope"]), str(row["bin_points"]), topology)].append(
            row
        )
    output: list[dict[str, Any]] = []
    for (scope, bin_points, topology), group in sorted(groups.items()):
        positive = sum(row[outcome_key] is True for row in group)
        negative = sum(row[outcome_key] is False for row in group)
        daily: dict[str, list[bool]] = defaultdict(list)
        for row in group:
            daily[str(row["date"])].append(bool(row[outcome_key]))
        day_rates = {
            day: sum(values) / len(values) for day, values in sorted(daily.items())
        }
        output.append(
            {
                "population": population,
                "outcome": outcome_key,
                "location_state": location_prefix,
                "scope": scope,
                "bin_points": bin_points,
                "topology": topology,
                "n": len(group),
                "positive": positive,
                "negative": negative,
                "positive_rate": positive / len(group),
                "days": len(daily),
                "median_day_rate": median(day_rates.values()),
                "day_rates": ";".join(
                    f"{day}:{rate:.3f}" for day, rate in day_rates.items()
                ),
            }
        )
    return output


def field_state_summary(
    rows: list[dict[str, Any]],
    *,
    population: str,
    outcome_key: str,
    location_prefix: str,
) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        outcome = row.get(outcome_key)
        state = str(row.get(f"{location_prefix}_field_state") or "")
        valid = truth(row.get(f"{location_prefix}_profile_valid"))
        if outcome is None or not valid or not state or state == "invalid":
            continue
        groups[(str(row["scope"]), str(row["bin_points"]), state)].append(row)
    output: list[dict[str, Any]] = []
    for (scope, bin_points, state), group in sorted(groups.items()):
        positive = sum(row[outcome_key] is True for row in group)
        daily: dict[str, list[bool]] = defaultdict(list)
        for row in group:
            daily[str(row["date"])].append(bool(row[outcome_key]))
        output.append(
            {
                "population": population,
                "outcome": outcome_key,
                "location_state": location_prefix,
                "scope": scope,
                "bin_points": bin_points,
                "field_state": state,
                "n": len(group),
                "positive": positive,
                "negative": len(group) - positive,
                "positive_rate": positive / len(group),
                "days": len(daily),
                "median_day_rate": median(
                    sum(values) / len(values) for values in daily.values()
                ),
                "day_rates": ";".join(
                    f"{day}:{sum(values) / len(values):.3f}"
                    for day, values in sorted(daily.items())
                ),
            }
        )
    return output


def numeric_summary(
    rows: list[dict[str, Any]],
    *,
    population: str,
    outcome_key: str,
    location_prefix: str,
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    configs = sorted(
        {(str(row["scope"]), str(row["bin_points"])) for row in rows}
    )
    for scope, bin_points in configs:
        group = [
            row
            for row in rows
            if str(row["scope"]) == scope
            and str(row["bin_points"]) == bin_points
            and row.get(outcome_key) is not None
            and truth(row.get(f"{location_prefix}_profile_valid"))
        ]
        for feature in PROFILE_FEATURES:
            key = f"{location_prefix}_{feature}"
            positive = [
                value
                for row in group
                if row[outcome_key] is True
                and (value := number(row, key)) is not None
            ]
            negative = [
                value
                for row in group
                if row[outcome_key] is False
                and (value := number(row, key)) is not None
            ]
            score = auc(positive, negative)
            if score is None:
                continue
            output.append(
                {
                    "population": population,
                    "outcome": outcome_key,
                    "location_state": location_prefix,
                    "scope": scope,
                    "bin_points": bin_points,
                    "feature": feature,
                    "n": len(positive) + len(negative),
                    "positive_median": median(positive),
                    "negative_median": median(negative),
                    "auc": score,
                    "effect_auc": max(score, 1.0 - score),
                }
            )
    return output


def book_interactions(
    rows: list[dict[str, Any]],
    *,
    population: str,
    outcome_key: str,
) -> list[dict[str, Any]]:
    groups: dict[
        tuple[str, str, str, str], list[dict[str, Any]]
    ] = defaultdict(list)
    for row in rows:
        if row.get(outcome_key) is None:
            continue
        if not truth(row.get("start_profile_valid")):
            continue
        if not truth(row.get("checkpoint_1000ms_active")):
            continue
        if not truth(row.get("checkpoint_1000ms_book_valid")):
            continue
        provision = number(
            row, "checkpoint_1000ms_winner_net_provision_qty"
        )
        if provision is None:
            continue
        provision_state = "provisioning" if provision > 0 else "draining"
        key = (
            str(row["scope"]),
            str(row["bin_points"]),
            str(row["start_topology"]),
            provision_state,
        )
        groups[key].append(row)

    output: list[dict[str, Any]] = []
    for (scope, bin_points, topology, provision_state), group in sorted(
        groups.items()
    ):
        positive = sum(row[outcome_key] is True for row in group)
        negative = len(group) - positive
        values_positive = [
            value
            for row in group
            if row[outcome_key] is True
            and (
                value := number(
                    row, "checkpoint_1000ms_winner_net_provision_qty"
                )
            )
            is not None
        ]
        values_negative = [
            value
            for row in group
            if row[outcome_key] is False
            and (
                value := number(
                    row, "checkpoint_1000ms_winner_net_provision_qty"
                )
            )
            is not None
        ]
        daily: dict[str, list[bool]] = defaultdict(list)
        for row in group:
            daily[str(row["date"])].append(bool(row[outcome_key]))
        output.append(
            {
                "population": population,
                "outcome": outcome_key,
                "scope": scope,
                "bin_points": bin_points,
                "topology": topology,
                "provision_state": provision_state,
                "n": len(group),
                "success": positive,
                "failure": negative,
                "success_rate": positive / len(group),
                "success_provision_median": (
                    median(values_positive) if values_positive else ""
                ),
                "failure_provision_median": (
                    median(values_negative) if values_negative else ""
                ),
                "provision_auc": (
                    auc(values_positive, values_negative)
                    if values_positive and values_negative
                    else ""
                ),
                "days": len(daily),
                "median_day_rate": median(
                    sum(values) / len(values) for values in daily.values()
                ),
            }
        )
    return output


def profile_evolution(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for row in rows:
        if row.get("first_test_held") is None:
            continue
        if not truth(row.get("owned_profile_valid")) or not truth(
            row.get("test_profile_valid")
        ):
            continue
        output.append(
            {
                "date": row["date"],
                "root_id": row["root_id"],
                "side": row["side"],
                "scope": row["scope"],
                "bin_points": row["bin_points"],
                "first_test_held": row["first_test_held"],
                "owned_topology": row["owned_topology"],
                "test_topology": row["test_topology"],
                "topology_changed": row[
                    "test_topology_changed_from_owned"
                ],
                "anchor_bin_volume_change": row[
                    "test_anchor_bin_volume_change_from_owned"
                ],
                "anchor_smooth_volume_change": row[
                    "test_anchor_smooth_volume_change_from_owned"
                ],
                "volume_percentile_change": row[
                    "test_volume_percentile_change_from_owned"
                ],
                "local_volume_ratio_change": row[
                    "test_local_volume_ratio_change_from_owned"
                ],
            }
        )
    return output


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
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
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def table(
    rows: Iterable[dict[str, Any]],
    fields: tuple[str, ...],
    formats: dict[str, Callable[[Any], str]] | None = None,
) -> list[str]:
    formats = formats or {}
    output = [
        "| " + " | ".join(fields) + " |",
        "|" + "|".join("---:" if field in {
            "n",
            "positive",
            "negative",
            "positive_rate",
            "median_day_rate",
            "success",
            "failure",
            "success_rate",
        } else "---" for field in fields) + "|",
    ]
    for row in rows:
        values = []
        for field in fields:
            value = row.get(field, "")
            values.append(formats.get(field, fmt)(value))
        output.append("| " + " | ".join(values) + " |")
    return output


def selected_config(
    rows: list[dict[str, Any]], scope: str = "rth", bin_points: str = "2.0"
) -> list[dict[str, Any]]:
    return [
        row
        for row in rows
        if str(row.get("scope")) == scope
        and str(row.get("bin_points")) == bin_points
    ]


def build_report(
    root_rows: list[dict[str, Any]],
    step_rows: list[dict[str, Any]],
    outcomes: list[dict[str, Any]],
    field_outcomes: list[dict[str, Any]],
    numeric: list[dict[str, Any]],
    interactions: list[dict[str, Any]],
    source: Path,
) -> str:
    primary_outcomes = selected_config(outcomes)
    primary_interactions = selected_config(interactions)
    primary_field_outcomes = selected_config(field_outcomes)
    lines = [
        "# Direct Conversion Profile-Field Analysis",
        "",
        f"Point-in-time source: `{source}`",
        "",
        "Research status: hypothesis generation. Event definitions are unchanged.",
        "",
        "## RTH Two-Point Topology",
        "",
        "Positive means first test held, first hold advanced, entry advanced, or "
        "material return readvanced/advanced, depending on the population.",
        "",
    ]
    for population, outcome in (
        ("all consumed roots", "first_test_held"),
        ("held consumed roots", "post_hold_advanced"),
        ("traded consumed roots", "entry_advanced"),
        ("material road steps", "step_success"),
        ("terminal road steps", "terminal_sponsor_advanced"),
    ):
        group = [
            row
            for row in primary_outcomes
            if row["population"] == population and row["outcome"] == outcome
        ]
        lines.extend(
            [
                f"### {population}: {outcome}",
                "",
                *table(
                    group,
                    (
                        "topology",
                        "n",
                        "positive",
                        "negative",
                        "positive_rate",
                        "days",
                        "median_day_rate",
                    ),
                ),
                "",
            ]
        )

    lvn_rows = [
        row
        for row in outcomes
        if row["topology"] == "between_hvns_lvn"
        and row["population"]
        in ("all consumed roots", "held consumed roots", "traded consumed roots")
    ]
    local_interactions = [
        row
        for row in primary_interactions
        if row["population"] == "material road steps"
    ]
    terminal_interactions = [
        row
        for row in primary_interactions
        if row["population"] == "terminal road steps"
    ]
    lines.extend(
        [
            "## RTH Node-Escape State",
            "",
        ]
    )
    for population, outcome in (
        ("all consumed roots", "first_test_held"),
        ("held consumed roots", "post_hold_advanced"),
        ("traded consumed roots", "entry_advanced"),
    ):
        group = [
            row
            for row in primary_field_outcomes
            if row["population"] == population and row["outcome"] == outcome
        ]
        lines.extend(
            [
                f"### {population}: {outcome}",
                "",
                *table(
                    group,
                    (
                        "field_state",
                        "n",
                        "positive",
                        "negative",
                        "positive_rate",
                        "days",
                        "median_day_rate",
                    ),
                ),
                "",
            ]
        )

    lines.extend(
        [
            "## Between-HVN LVN Sensitivity",
            "",
            *table(
                lvn_rows,
                (
                    "population",
                    "outcome",
                    "location_state",
                    "scope",
                    "bin_points",
                    "n",
                    "positive_rate",
                    "days",
                    "median_day_rate",
                ),
            ),
            "",
            "## One-Second Book Interaction By Return Location",
            "",
            *table(
                local_interactions,
                (
                    "topology",
                    "provision_state",
                    "n",
                    "success",
                    "failure",
                    "success_rate",
                    "days",
                    "median_day_rate",
                ),
            ),
            "",
            "## One-Second Book Interaction At Sponsor Decision",
            "",
            *table(
                terminal_interactions,
                (
                    "topology",
                    "provision_state",
                    "n",
                    "success",
                    "failure",
                    "success_rate",
                    "days",
                    "median_day_rate",
                ),
            ),
            "",
            "## Strongest Numeric Location Effects",
            "",
        ]
    )
    ranked = sorted(
        numeric,
        key=lambda row: (
            -float(row["effect_auc"]),
            -int(row["n"]),
        ),
    )
    lines.extend(
        table(
            ranked[:30],
            (
                "population",
                "outcome",
                "location_state",
                "scope",
                "bin_points",
                "feature",
                "n",
                "positive_median",
                "negative_median",
                "auc",
            ),
        )
    )

    named = [
        row
        for row in selected_config(root_rows)
        if (row["date"], str(row["root_id"]))
        in {
            ("2026-07-23", "111"),
            ("2026-07-23", "208"),
            ("2026-07-24", "34"),
            ("2026-07-24", "84"),
            ("2026-07-24", "89"),
            ("2026-07-24", "102"),
        }
    ]
    lines.extend(
        [
            "",
            "## Named Fixtures",
            "",
            *table(
                named,
                (
                    "date",
                    "root_id",
                    "side",
                    "first_test_held",
                    "post_hold_advanced",
                    "entry_advanced",
                    "owned_topology",
                    "test_topology",
                    "entry_topology",
                    "owned_volume_percentile",
                ),
            ),
            "",
            "## Guardrails",
            "",
            "- Profile state is point-in-time; final-session nodes are never used.",
            "- RTH location before five minutes is marked immature.",
            "- July 20 RTH profiles are invalid because capture began at 09:32:10.",
            "- Topology thresholds are descriptive and require bin/scope sensitivity.",
            "- Entries and steps within one root/directive are correlated.",
            "- ETH/prior-session profile is absent because overnight recorder coverage "
            "is not consistent across these dates.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    args = parse_args()
    location_rows = read_csv(args.locations)
    lineage = read_csv(args.lineage)
    steps = read_csv(args.steps)
    index, configs = location_index(location_rows)
    roots = root_joined_rows(
        lineage,
        index,
        configs,
        args.start_date,
        args.end_date,
    )
    road_steps = step_joined_rows(
        steps,
        index,
        configs,
        args.start_date,
        args.end_date,
    )

    outcomes: list[dict[str, Any]] = []
    field_outcomes: list[dict[str, Any]] = []
    numeric: list[dict[str, Any]] = []
    for rows, population, outcome_key, location_prefix in (
        (roots, "all consumed roots", "first_test_held", "owned"),
        (roots, "held consumed roots", "post_hold_advanced", "hold"),
        (roots, "traded consumed roots", "entry_advanced", "entry"),
        (road_steps, "material road steps", "step_success", "start"),
        (
            road_steps,
            "terminal road steps",
            "terminal_sponsor_advanced",
            "start",
        ),
    ):
        outcomes.extend(
            outcome_summary(
                rows,
                population=population,
                outcome_key=outcome_key,
                location_prefix=location_prefix,
            )
        )
        field_outcomes.extend(
            field_state_summary(
                rows,
                population=population,
                outcome_key=outcome_key,
                location_prefix=location_prefix,
            )
        )
        numeric.extend(
            numeric_summary(
                rows,
                population=population,
                outcome_key=outcome_key,
                location_prefix=location_prefix,
            )
        )
    interactions = book_interactions(
        road_steps,
        population="material road steps",
        outcome_key="step_success",
    )
    interactions.extend(
        book_interactions(
            road_steps,
            population="terminal road steps",
            outcome_key="terminal_sponsor_advanced",
        )
    )
    evolution = profile_evolution(roots)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    write_csv(args.out_dir / "root_profile_joined.csv", roots)
    write_csv(args.out_dir / "step_profile_joined.csv", road_steps)
    write_csv(args.out_dir / "topology_outcomes.csv", outcomes)
    write_csv(args.out_dir / "field_state_outcomes.csv", field_outcomes)
    write_csv(args.out_dir / "numeric_rankings.csv", numeric)
    write_csv(args.out_dir / "step_book_interactions.csv", interactions)
    write_csv(args.out_dir / "profile_evolution.csv", evolution)
    report = build_report(
        roots,
        road_steps,
        outcomes,
        field_outcomes,
        numeric,
        interactions,
        args.locations,
    )
    (args.out_dir / "findings.md").write_text(report, encoding="utf-8")
    print(
        f"wrote {args.out_dir / 'findings.md'} "
        f"roots={len(roots)} steps={len(road_steps)}"
    )


if __name__ == "__main__":
    main()
