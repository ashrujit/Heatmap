"""Analyze actual DirectConversion order decisions in their evolving field."""

from __future__ import annotations

import argparse
import csv
import glob
import math
from collections import defaultdict
from pathlib import Path
from statistics import median
from typing import Any

from _paths import OUTPUT_ROOT

DEFAULT_ENTRY_GLOB = str(
    OUTPUT_ROOT
    / "direct_conversion_entry_field_202607*"
    / "entry_provision.csv"
)
DEFAULT_LOCATIONS = (
    OUTPUT_ROOT
    / "direct_conversion_profile_field_20260716_20260724"
    / "profile_locations.csv"
)
DEFAULT_LINEAGE = (
    OUTPUT_ROOT / "direct_conversion_sponsor_lineage" / "lineage.csv"
)
DEFAULT_OUT = (
    OUTPUT_ROOT / "direct_conversion_entry_field_20260717_20260724"
)
TRAILING_MS = (500, 1_000, 2_000, 5_000)
TRAILING_SUFFIXES = (
    "owner_net_provision",
    "owner_added",
    "owner_removed",
    "opposite_net_provision",
    "opposite_added",
    "opposite_removed",
)
LOCATION_FIELDS = (
    "profile_valid",
    "invalid_reason",
    "topology",
    "field_state",
    "profile_age_s",
    "profile_total_volume",
    "anchor_bin_volume",
    "anchor_smooth_volume",
    "volume_percentile",
    "volume_to_vpoc_ratio",
    "local_volume_ratio",
    "valley_ratio",
    "vpoc_signed_distance_pts",
    "current_price",
    "current_favorable_displacement_pts",
    "current_vpoc_signed_distance_pts",
    "current_hvn_escape_margin_pts",
    "current_beyond_favorable_hvn_edge",
    "current_next_hvn_signed_gap_pts",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--entry-glob", default=DEFAULT_ENTRY_GLOB)
    parser.add_argument("--locations", type=Path, default=DEFAULT_LOCATIONS)
    parser.add_argument("--lineage", type=Path, default=DEFAULT_LINEAGE)
    parser.add_argument("--start-date", default="2026-07-17")
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


def outcome(value: str, positive: str, negative: str) -> bool | None:
    if value == positive:
        return True
    if value == negative:
        return False
    return None


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


def load_entries(pattern: str, start: str, end: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for raw_path in sorted(glob.glob(pattern)):
        for row in read_csv(Path(raw_path)):
            if in_range(row["date"], start, end):
                rows.append(row)
    deduped = {row["intent_id"]: row for row in rows}
    return sorted(
        deduped.values(), key=lambda row: (row["date"], row["decision_et"])
    )


def lineage_index(
    rows: list[dict[str, str]], start: str, end: str
) -> dict[tuple[str, str], dict[str, str]]:
    return {
        (row["date"], row["root_id"]): row
        for row in rows
        if in_range(row["date"], start, end)
    }


def location_index(
    rows: list[dict[str, str]],
) -> tuple[
    dict[tuple[str, str, str, str, str], dict[str, str]],
    list[tuple[str, str]],
]:
    index: dict[tuple[str, str, str, str, str], dict[str, str]] = {}
    configs: set[tuple[str, str]] = set()
    for row in rows:
        if row.get("source") != "entries":
            continue
        key = (
            row["date"],
            row["root_id"],
            row.get("step_ordinal", ""),
            row["scope"],
            row["bin_points"],
        )
        index[key] = row
        configs.add((row["scope"], row["bin_points"]))
    return index, sorted(configs, key=lambda item: (item[0], float(item[1])))


def enrich_entries(
    entries: list[dict[str, str]],
    lineage: dict[tuple[str, str], dict[str, str]],
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for raw in entries:
        row: dict[str, Any] = dict(raw)
        root = lineage.get((raw["date"], raw["band_id"]))
        root_outcome = (
            outcome(
                root.get("entry_structural_outcome", ""),
                "ADVANCED_AFTER_ENTRY",
                "ROOT_FAILED_AFTER_ENTRY",
            )
            if root
            else None
        )
        touch = raw.get("first_10pt_touch", "")
        first10 = (
            True
            if touch == "favorable_10"
            else False if touch == "adverse_10" else None
        )
        row.update(
            {
                "root_entry_advanced": root_outcome,
                "first10_favorable": first10,
                "root_id": raw["band_id"],
                "lineage_matched": root is not None,
                "root_first_test_verdict": (
                    root.get("root_first_test_verdict", "") if root else ""
                ),
                "root_hold_outcome": (
                    root.get("hold_structural_outcome", "") if root else ""
                ),
                "pre_10m_50pts_two_sided_fail": (
                    root.get("pre_10m_50pts_two_sided_fail", "")
                    if root
                    else ""
                ),
                "pre_10m_50pts_favorable_position": (
                    root.get("pre_10m_50pts_favorable_position", "")
                    if root
                    else ""
                ),
            }
        )
        if not root:
            row["ownership_field_state"] = ""
        elif root.get("pre_10m_50pts_two_sided_fail") != "True":
            row["ownership_field_state"] = "clean"
        elif (
            root.get("pre_10m_50pts_favorable_position")
            == "beyond_favorable_edge"
        ):
            row["ownership_field_state"] = "escaped"
        else:
            row["ownership_field_state"] = "inside_two_sided_churn"
        for trailing_ms in TRAILING_MS:
            prefix = f"trailing_{trailing_ms}ms"
            owner_added = number(row, f"{prefix}_owner_added")
            owner_removed = number(row, f"{prefix}_owner_removed")
            opposite_added = number(row, f"{prefix}_opposite_added")
            opposite_removed = number(row, f"{prefix}_opposite_removed")
            row[f"{prefix}_owner_observed_flow"] = (
                owner_added - owner_removed
                if owner_added is not None and owner_removed is not None
                else ""
            )
            row[f"{prefix}_opposite_observed_flow"] = (
                opposite_added - opposite_removed
                if opposite_added is not None
                and opposite_removed is not None
                else ""
            )
        output.append(row)
    return output


def join_locations(
    entries: list[dict[str, Any]],
    index: dict[tuple[str, str, str, str, str], dict[str, str]],
    configs: list[tuple[str, str]],
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for entry in entries:
        for scope, bin_points in configs:
            location = index.get(
                (
                    str(entry["date"]),
                    str(entry["band_id"]),
                    str(entry["intent_id"]),
                    scope,
                    bin_points,
                )
            )
            row = {
                key: value
                for key, value in entry.items()
                if key
                in {
                    "date",
                    "decision_et",
                    "intent_id",
                    "directive_id",
                    "role",
                    "side",
                    "band_id",
                    "price_lo",
                    "price_hi",
                    "root_entry_advanced",
                    "first10_favorable",
                    "lineage_matched",
                    "root_first_test_verdict",
                    "root_hold_outcome",
                    "pre_10m_50pts_two_sided_fail",
                    "pre_10m_50pts_favorable_position",
                    "ownership_field_state",
                }
            }
            row.update({"scope": scope, "bin_points": bin_points})
            for trailing_ms in TRAILING_MS:
                prefix = f"trailing_{trailing_ms}ms"
                for suffix in (
                    "opened",
                    *TRAILING_SUFFIXES,
                    "owner_observed_flow",
                    "opposite_observed_flow",
                ):
                    row[f"{prefix}_{suffix}"] = entry.get(
                        f"{prefix}_{suffix}", ""
                    )
            for field in LOCATION_FIELDS:
                row[field] = location.get(field, "") if location else ""
            output.append(row)
    return output


def numeric_rankings(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    features = []
    for trailing_ms in TRAILING_MS:
        prefix = f"trailing_{trailing_ms}ms"
        features.extend(
            (
                f"{prefix}_owner_net_provision",
                f"{prefix}_owner_observed_flow",
                f"{prefix}_owner_added",
                f"{prefix}_owner_removed",
                f"{prefix}_opposite_net_provision",
                f"{prefix}_opposite_observed_flow",
            )
        )
    for outcome_key in ("root_entry_advanced", "first10_favorable"):
        for role in ("ALL", "EnterBase", "Add"):
            group = [
                row
                for row in entries
                if row.get(outcome_key) is not None
                and (role == "ALL" or row.get("role") == role)
            ]
            for feature in features:
                positive = [
                    value
                    for row in group
                    if row[outcome_key] is True
                    and (value := number(row, feature)) is not None
                ]
                negative = [
                    value
                    for row in group
                    if row[outcome_key] is False
                    and (value := number(row, feature)) is not None
                ]
                score = auc(positive, negative)
                if score is None:
                    continue
                output.append(
                    {
                        "outcome": outcome_key,
                        "role": role,
                        "feature": feature,
                        "n": len(positive) + len(negative),
                        "positive_median": median(positive),
                        "negative_median": median(negative),
                        "auc": score,
                        "effect_auc": max(score, 1.0 - score),
                    }
                )
    return output


def day_auc(
    entries: list[dict[str, Any]],
    feature: str,
    outcome_key: str,
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for day in sorted({str(row["date"]) for row in entries}):
        group = [
            row
            for row in entries
            if row["date"] == day and row.get(outcome_key) is not None
        ]
        positive = [
            value
            for row in group
            if row[outcome_key] is True
            and (value := number(row, feature)) is not None
        ]
        negative = [
            value
            for row in group
            if row[outcome_key] is False
            and (value := number(row, feature)) is not None
        ]
        score = auc(positive, negative)
        output.append(
            {
                "date": day,
                "outcome": outcome_key,
                "feature": feature,
                "positive": len(positive),
                "negative": len(negative),
                "auc": score if score is not None else "",
            }
        )
    return output


def categorical_summary(
    rows: list[dict[str, Any]],
    *,
    outcome_key: str,
    category_key: str,
) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if row.get(outcome_key) is None or not truth(row.get("profile_valid")):
            continue
        category = str(row.get(category_key) or "")
        if not category or category == "invalid":
            continue
        groups[(str(row["scope"]), str(row["bin_points"]), category)].append(
            row
        )
    output: list[dict[str, Any]] = []
    for (scope, bin_points, category), group in sorted(groups.items()):
        positive = sum(row[outcome_key] is True for row in group)
        output.append(
            {
                "outcome": outcome_key,
                "category_key": category_key,
                "scope": scope,
                "bin_points": bin_points,
                "category": category,
                "n": len(group),
                "positive": positive,
                "negative": len(group) - positive,
                "positive_rate": positive / len(group),
                "days": len({str(row["date"]) for row in group}),
                "directives": len(
                    {str(row["directive_id"]) for row in group}
                ),
            }
        )
    return output


def location_rankings(
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    features = (
        "current_vpoc_signed_distance_pts",
        "vpoc_signed_distance_pts",
        "volume_percentile",
        "volume_to_vpoc_ratio",
        "local_volume_ratio",
        "valley_ratio",
        "current_hvn_escape_margin_pts",
    )
    output: list[dict[str, Any]] = []
    configs = sorted(
        {(str(row["scope"]), str(row["bin_points"])) for row in rows}
    )
    for outcome_key in ("root_entry_advanced", "first10_favorable"):
        for role in ("ALL", "EnterBase", "Add"):
            for scope, bin_points in configs:
                group = [
                    row
                    for row in rows
                    if str(row["scope"]) == scope
                    and str(row["bin_points"]) == bin_points
                    and row.get(outcome_key) is not None
                    and truth(row.get("profile_valid"))
                    and (role == "ALL" or row.get("role") == role)
                ]
                for feature in features:
                    positive = [
                        value
                        for row in group
                        if row[outcome_key] is True
                        and (value := number(row, feature)) is not None
                    ]
                    negative = [
                        value
                        for row in group
                        if row[outcome_key] is False
                        and (value := number(row, feature)) is not None
                    ]
                    score = auc(positive, negative)
                    if score is None:
                        continue
                    output.append(
                        {
                            "outcome": outcome_key,
                            "role": role,
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


def context_activity_summary(
    rows: list[dict[str, Any]],
    *,
    outcome_key: str,
    scope: str,
    bin_points: str,
) -> list[dict[str, Any]]:
    group = [
        row
        for row in rows
        if str(row["scope"]) == scope
        and str(row["bin_points"]) == bin_points
        and row.get(outcome_key) is not None
        and truth(row.get("profile_valid"))
        and number(row, "current_vpoc_signed_distance_pts") is not None
        and number(row, "trailing_500ms_owner_added") is not None
    ]
    medians: dict[tuple[str, str], float] = {}
    by_day_role: dict[tuple[str, str], list[float]] = defaultdict(list)
    for row in group:
        value = number(row, "trailing_500ms_owner_added")
        if value is not None:
            by_day_role[(str(row["date"]), str(row["role"]))].append(value)
    for key, values in by_day_role.items():
        medians[key] = median(values)

    buckets: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in group:
        vpoc_distance = number(row, "current_vpoc_signed_distance_pts")
        owner_added = number(row, "trailing_500ms_owner_added")
        reference = medians[(str(row["date"]), str(row["role"]))]
        location_state = (
            "favorable_of_60m_vpoc"
            if vpoc_distance is not None and vpoc_distance > 0
            else "adverse_of_60m_vpoc"
        )
        activity_state = (
            "high_owner_add_activity"
            if owner_added is not None and owner_added > reference
            else "low_owner_add_activity"
        )
        buckets[(str(row["role"]), location_state, activity_state)].append(row)

    output: list[dict[str, Any]] = []
    for (role, location_state, activity_state), rows_in_bucket in sorted(
        buckets.items()
    ):
        positive = sum(row[outcome_key] is True for row in rows_in_bucket)
        output.append(
            {
                "outcome": outcome_key,
                "scope": scope,
                "bin_points": bin_points,
                "role": role,
                "location_state": location_state,
                "activity_state": activity_state,
                "n": len(rows_in_bucket),
                "positive": positive,
                "negative": len(rows_in_bucket) - positive,
                "positive_rate": positive / len(rows_in_bucket),
                "days": len({str(row["date"]) for row in rows_in_bucket}),
                "directives": len(
                    {str(row["directive_id"]) for row in rows_in_bucket}
                ),
            }
        )
    return output


def ownership_profile_summary(
    rows: list[dict[str, Any]],
    *,
    outcome_key: str,
    scope: str,
    bin_points: str,
) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if (
            str(row["scope"]) != scope
            or str(row["bin_points"]) != bin_points
            or row.get(outcome_key) is None
            or not truth(row.get("profile_valid"))
        ):
            continue
        distance = number(row, "current_vpoc_signed_distance_pts")
        ownership_state = str(row.get("ownership_field_state") or "")
        if distance is None or not ownership_state:
            continue
        vpoc_state = (
            "favorable_of_60m_vpoc"
            if distance > 0
            else "adverse_of_60m_vpoc"
        )
        groups[(str(row["role"]), ownership_state, vpoc_state)].append(row)
    output: list[dict[str, Any]] = []
    for (role, ownership_state, vpoc_state), group in sorted(groups.items()):
        positive = sum(row[outcome_key] is True for row in group)
        output.append(
            {
                "outcome": outcome_key,
                "scope": scope,
                "bin_points": bin_points,
                "role": role,
                "ownership_field_state": ownership_state,
                "vpoc_state": vpoc_state,
                "n": len(group),
                "positive": positive,
                "negative": len(group) - positive,
                "positive_rate": positive / len(group),
                "days": len({str(row["date"]) for row in group}),
                "directives": len(
                    {str(row["directive_id"]) for row in group}
                ),
            }
        )
    return output


def interaction_summary(
    rows: list[dict[str, Any]],
    *,
    outcome_key: str,
    scope: str,
    bin_points: str,
) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    feature = "trailing_1000ms_owner_net_provision"
    for row in rows:
        if (
            str(row["scope"]) != scope
            or str(row["bin_points"]) != bin_points
            or row.get(outcome_key) is None
            or not truth(row.get("profile_valid"))
        ):
            continue
        provision = number(row, feature)
        if provision is None:
            continue
        state = str(row.get("field_state") or "")
        provision_state = "provisioning" if provision > 0 else "draining"
        groups[(state, provision_state)].append(row)
    output: list[dict[str, Any]] = []
    for (state, provision_state), group in sorted(groups.items()):
        positive = sum(row[outcome_key] is True for row in group)
        output.append(
            {
                "outcome": outcome_key,
                "scope": scope,
                "bin_points": bin_points,
                "field_state": state,
                "provision_state": provision_state,
                "n": len(group),
                "positive": positive,
                "negative": len(group) - positive,
                "positive_rate": positive / len(group),
                "days": len({str(row["date"]) for row in group}),
                "directives": len(
                    {str(row["directive_id"]) for row in group}
                ),
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


def fmt(value: Any, digits: int = 3) -> str:
    if value in (None, ""):
        return ""
    if isinstance(value, float):
        return f"{value:.{digits}f}" if math.isfinite(value) else ""
    return str(value)


def markdown_table(
    rows: list[dict[str, Any]], fields: tuple[str, ...]
) -> list[str]:
    output = [
        "| " + " | ".join(fields) + " |",
        "|" + "|".join("---" for _ in fields) + "|",
    ]
    for row in rows:
        output.append(
            "| " + " | ".join(fmt(row.get(field, "")) for field in fields) + " |"
        )
    return output


def build_report(
    entries: list[dict[str, Any]],
    joined: list[dict[str, Any]],
    rankings: list[dict[str, Any]],
    daily: list[dict[str, Any]],
    categorical: list[dict[str, Any]],
    interactions: list[dict[str, Any]],
    location_numeric: list[dict[str, Any]],
    context_activity: list[dict[str, Any]],
    ownership_profile: list[dict[str, Any]],
) -> str:
    resolved = [
        row for row in entries if row.get("root_entry_advanced") is not None
    ]
    positive = sum(row["root_entry_advanced"] is True for row in resolved)
    primary_categorical = [
        row
        for row in categorical
        if row["scope"] == "60m"
        and str(row["bin_points"]) == "2.0"
        and row["outcome"] == "root_entry_advanced"
    ]
    primary_interactions = [
        row
        for row in interactions
        if row["outcome"] == "root_entry_advanced"
    ]
    ranked = sorted(
        [
            row
            for row in rankings
            if row["outcome"] == "root_entry_advanced"
        ],
        key=lambda row: (-float(row["effect_auc"]), -int(row["n"])),
    )
    ranked_location = sorted(
        [
            row
            for row in location_numeric
            if row["outcome"] == "root_entry_advanced"
            and int(row["n"]) >= 20
        ],
        key=lambda row: (-float(row["effect_auc"]), -int(row["n"])),
    )
    named = [
        row
        for row in joined
        if row["scope"] == "60m"
        and str(row["bin_points"]) == "2.0"
        and (
            (row["date"] == "2026-07-24" and any(
                marker in row["decision_et"]
                for marker in ("10:21:", "11:50:", "11:55:", "12:10:")
            ))
            or (
                row["date"] == "2026-07-23"
                and any(
                    marker in row["decision_et"]
                    for marker in ("12:19:", "14:35:")
                )
            )
        )
    ]
    lines = [
        "# Direct Conversion Actual-Entry Field",
        "",
        "Research status: hypothesis generation. No EAR rule has changed.",
        "",
        "## Population",
        "",
        f"- Accepted entries with valid raw-book windows: {len(entries)}",
        f"- Root outcome resolved: {len(resolved)}",
        f"- Advanced before root failure: {positive}",
        f"- Root failed first: {len(resolved) - positive}",
        f"- Directives: {len({row['directive_id'] for row in entries})}",
        "",
        "## Trailing Book Rankings",
        "",
        *markdown_table(
            ranked[:30],
            (
                "role",
                "feature",
                "n",
                "positive_median",
                "negative_median",
                "auc",
            ),
        ),
        "",
        "## One-Second Owner Provision By Day",
        "",
        *markdown_table(
            [
                row
                for row in daily
                if row["outcome"] == "root_entry_advanced"
                and row["feature"]
                == "trailing_1000ms_owner_net_provision"
            ],
            ("date", "positive", "negative", "auc"),
        ),
        "",
        "## Sixty-Minute VPOC Distance By Day",
        "",
        *markdown_table(
            [
                row
                for row in daily
                if row["outcome"] == "root_entry_advanced"
                and row["feature"] == "current_vpoc_signed_distance_pts"
            ],
            ("date", "positive", "negative", "auc"),
        ),
        "",
        "## Sixty-Minute Location At Decision",
        "",
        *markdown_table(
            primary_categorical,
            (
                "category_key",
                "category",
                "n",
                "positive",
                "negative",
                "positive_rate",
                "days",
                "directives",
            ),
        ),
        "",
        "## Numeric Location Rankings",
        "",
        *markdown_table(
            ranked_location[:24],
            (
                "role",
                "scope",
                "bin_points",
                "feature",
                "n",
                "positive_median",
                "negative_median",
                "auc",
            ),
        ),
        "",
        "## Location And One-Second Provision",
        "",
        *markdown_table(
            primary_interactions,
            (
                "field_state",
                "provision_state",
                "n",
                "positive",
                "negative",
                "positive_rate",
                "days",
                "directives",
            ),
        ),
        "",
        "## Location And Gross Owner Activity",
        "",
        "High/low activity is split at the same-date, same-role median. It is "
        "a rank audit, not a proposed threshold.",
        "",
        *markdown_table(
            [
                row
                for row in context_activity
                if row["outcome"] == "root_entry_advanced"
            ],
            (
                "role",
                "location_state",
                "activity_state",
                "n",
                "positive",
                "negative",
                "positive_rate",
                "days",
                "directives",
            ),
        ),
        "",
        "## Ownership Field And Rolling Profile",
        "",
        *markdown_table(
            [
                row
                for row in ownership_profile
                if row["outcome"] == "root_entry_advanced"
            ],
            (
                "role",
                "ownership_field_state",
                "vpoc_state",
                "n",
                "positive",
                "negative",
                "positive_rate",
                "days",
                "directives",
            ),
        ),
        "",
        "## Named Decisions",
        "",
        *markdown_table(
            named,
            (
                "date",
                "decision_et",
                "role",
                "side",
                "band_id",
                "root_entry_advanced",
                "topology",
                "field_state",
                "current_vpoc_signed_distance_pts",
                "trailing_1000ms_owner_net_provision",
            ),
        ),
        "",
        "## Guardrails",
        "",
        "- Outcomes are sponsor-lineage outcomes, not fixed P&L labels.",
        "- Repeated entries inside one directive/root are correlated.",
        "- The trailing zone is eight ticks behind current price at decision.",
        "- July 16 is excluded because its reconstructed windows were unopened.",
        "- Location is point-in-time and uses no later session volume.",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    args = parse_args()
    raw_entries = load_entries(
        args.entry_glob, args.start_date, args.end_date
    )
    # All retained dates must have a seeded/opened one-second book window.
    raw_entries = [
        row for row in raw_entries if truth(row.get("trailing_1000ms_opened"))
    ]
    lineage = lineage_index(
        read_csv(args.lineage), args.start_date, args.end_date
    )
    entries = enrich_entries(raw_entries, lineage)
    locations, configs = location_index(read_csv(args.locations))
    joined = join_locations(entries, locations, configs)
    rankings = numeric_rankings(entries)
    daily: list[dict[str, Any]] = []
    for outcome_key in ("root_entry_advanced", "first10_favorable"):
        for trailing_ms in TRAILING_MS:
            daily.extend(
                day_auc(
                    entries,
                    f"trailing_{trailing_ms}ms_owner_net_provision",
                    outcome_key,
                )
            )
    primary_joined = [
        row
        for row in joined
        if row["scope"] == "60m"
        and str(row["bin_points"]) == "2.0"
        and truth(row.get("profile_valid"))
    ]
    for outcome_key in ("root_entry_advanced", "first10_favorable"):
        daily.extend(
            day_auc(
                primary_joined,
                "current_vpoc_signed_distance_pts",
                outcome_key,
            )
        )
    categorical: list[dict[str, Any]] = []
    for outcome_key in ("root_entry_advanced", "first10_favorable"):
        for category_key in ("topology", "field_state"):
            categorical.extend(
                categorical_summary(
                    joined,
                    outcome_key=outcome_key,
                    category_key=category_key,
                )
            )
    interactions: list[dict[str, Any]] = []
    for outcome_key in ("root_entry_advanced", "first10_favorable"):
        interactions.extend(
            interaction_summary(
                joined,
                outcome_key=outcome_key,
                scope="60m",
                bin_points="2.0",
            )
        )
    location_numeric = location_rankings(joined)
    context_activity: list[dict[str, Any]] = []
    ownership_profile: list[dict[str, Any]] = []
    for outcome_key in ("root_entry_advanced", "first10_favorable"):
        context_activity.extend(
            context_activity_summary(
                joined,
                outcome_key=outcome_key,
                scope="60m",
                bin_points="2.0",
            )
        )
        ownership_profile.extend(
            ownership_profile_summary(
                joined,
                outcome_key=outcome_key,
                scope="60m",
                bin_points="2.0",
            )
        )

    args.out_dir.mkdir(parents=True, exist_ok=True)
    write_csv(args.out_dir / "entries.csv", entries)
    write_csv(args.out_dir / "entry_field_joined.csv", joined)
    write_csv(args.out_dir / "numeric_rankings.csv", rankings)
    write_csv(args.out_dir / "day_auc.csv", daily)
    write_csv(args.out_dir / "categorical_outcomes.csv", categorical)
    write_csv(args.out_dir / "field_book_interactions.csv", interactions)
    write_csv(args.out_dir / "location_numeric_rankings.csv", location_numeric)
    write_csv(args.out_dir / "context_activity.csv", context_activity)
    write_csv(args.out_dir / "ownership_profile_context.csv", ownership_profile)
    report = build_report(
        entries,
        joined,
        rankings,
        daily,
        categorical,
        interactions,
        location_numeric,
        context_activity,
        ownership_profile,
    )
    (args.out_dir / "findings.md").write_text(report, encoding="utf-8")
    print(
        f"wrote {args.out_dir / 'findings.md'} entries={len(entries)} "
        f"joined={len(joined)}"
    )


if __name__ == "__main__":
    main()
