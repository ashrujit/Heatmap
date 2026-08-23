"""Rank synthetic direct-conversion lifecycle buckets.

Input is `direct_conversion_events.csv` from
`direct_conversion_lifecycle_dataset.py`. This pass intentionally separates
predictor fields from outcome fields so we can see which dimensions are useful
at conversion time and which only become useful at retest time.
"""

from __future__ import annotations

import argparse
import csv
import math
import statistics
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable

from _paths import OUTPUT_ROOT


BAD_OUTCOMES = {"retest_failed", "failed_without_retest", "failed_before_retest"}
GOOD_OUTCOMES = {"retest_held", "no_retest_seen"}


@dataclass(frozen=True)
class FeatureSpec:
    name: str
    family: str
    kind: str
    getter: Callable[[dict[str, str]], str | float | None]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--events-csv",
        default=str(
            OUTPUT_ROOT
            / "direct_conversion_lifecycle_20260723_20260724"
            / "direct_conversion_events.csv"
        ),
    )
    parser.add_argument(
        "--out-dir",
        default=str(
            OUTPUT_ROOT
            / "direct_conversion_lifecycle_20260723_20260724"
            / "bucket_analysis"
        ),
    )
    parser.add_argument("--min-n", type=int, default=5)
    parser.add_argument("--combo-min-n", type=int, default=4)
    parser.add_argument("--top-features", type=int, default=0, help="0 means use all ranked features")
    parser.add_argument("--max-combo-rows", type=int, default=0, help="0 means write all combo rows")
    parser.add_argument("--durable-path-threshold", type=float, default=10.0)
    parser.add_argument("--bad-path-threshold", type=float, default=-10.0)
    return parser.parse_args()


def as_float(value: Any) -> float | None:
    if value in ("", None):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def as_int(value: Any) -> int:
    number = as_float(value)
    return int(number) if number is not None else 0


def side_sign(row: dict[str, str]) -> int:
    return 1 if row.get("side") == "demand" else -1


def owner_delta(row: dict[str, str], key: str) -> float | None:
    value = as_float(row.get(key))
    return None if value is None else value * side_sign(row)


def ratio(num: float | None, den: float | None) -> float | None:
    if num is None or den is None:
        return None
    if abs(den) < 1e-9:
        return None if abs(num) < 1e-9 else 99.0
    return num / den


def diff(a: float | None, b: float | None) -> float | None:
    if a is None or b is None:
        return None
    return a - b


def owner_side_depth(row: dict[str, str], prefix: str, suffix: str) -> float | None:
    return as_float(row.get(f"{prefix}_{suffix}"))


def owner_behind_depth(row: dict[str, str], prefix: str) -> float | None:
    if row.get("side") == "demand":
        return as_float(row.get(f"{prefix}_same_depth_below"))
    return as_float(row.get(f"{prefix}_same_depth_above"))


def owner_ahead_depth(row: dict[str, str], prefix: str) -> float | None:
    if row.get("side") == "demand":
        return as_float(row.get(f"{prefix}_same_depth_above"))
    return as_float(row.get(f"{prefix}_same_depth_below"))


def opp_behind_depth(row: dict[str, str], prefix: str) -> float | None:
    if row.get("side") == "demand":
        return as_float(row.get(f"{prefix}_opp_depth_below"))
    return as_float(row.get(f"{prefix}_opp_depth_above"))


def owner_top20_delta(row: dict[str, str], prefix: str) -> float | None:
    bid = as_float(row.get(f"{prefix}_top20_bid"))
    ask = as_float(row.get(f"{prefix}_top20_ask"))
    if bid is None or ask is None:
        return None
    return (bid - ask) * side_sign(row)


def owner_flow(row: dict[str, str], prefix: str, seconds: int) -> float | None:
    aligned = as_float(row.get(f"{prefix}_aligned_vol_{seconds}s"))
    hostile = as_float(row.get(f"{prefix}_hostile_vol_{seconds}s"))
    return diff(aligned, hostile)


def kind_flag(kind: str) -> Callable[[dict[str, str]], str]:
    def get(row: dict[str, str]) -> str:
        values = {part.strip() for part in row.get("kinds", "").split(",") if part.strip()}
        return "yes" if kind in values else "no"

    return get


def cat(column: str, family: str) -> FeatureSpec:
    return FeatureSpec(column, family, "cat", lambda row, col=column: row.get(col, "") or "missing")


def num(name: str, family: str, getter: Callable[[dict[str, str]], float | None]) -> FeatureSpec:
    return FeatureSpec(name, family, "num", getter)


def features() -> list[FeatureSpec]:
    specs: list[FeatureSpec] = [
        cat("date", "session"),
        cat("side", "event"),
        cat("source", "event"),
        num("width_pts", "event", lambda row: as_float(row.get("width_pts"))),
        num("score", "event", lambda row: as_float(row.get("score"))),
        num("max_abs_z", "event", lambda row: as_float(row.get("max_abs_z"))),
        num("event_count", "event", lambda row: as_float(row.get("event_count"))),
        num("confirm_displacement_pts", "event", lambda row: as_float(row.get("confirm_displacement_pts"))),
        num("confirm_age_s", "event", lambda row: as_float(row.get("confirm_age_s"))),
        num("evidence_duration_s", "event", lambda row: as_float(row.get("evidence_duration_s"))),
        FeatureSpec("kind_ASK_BUILD", "event", "cat", kind_flag("ASK_BUILD")),
        FeatureSpec("kind_ASK_IN", "event", "cat", kind_flag("ASK_IN")),
        FeatureSpec("kind_ASK_OUT", "event", "cat", kind_flag("ASK_OUT")),
        FeatureSpec("kind_BID_BUILD", "event", "cat", kind_flag("BID_BUILD")),
        FeatureSpec("kind_BID_IN", "event", "cat", kind_flag("BID_IN")),
        FeatureSpec("kind_BID_OUT", "event", "cat", kind_flag("BID_OUT")),
        cat("pre_edge_bucket", "prior"),
        cat("pre_fail_bucket", "prior"),
        cat("pre_two_sided_fail_5m", "prior"),
        cat("pre_two_sided_fail_10m", "prior"),
        num("pre_field_width_pts", "prior", lambda row: as_float(row.get("pre_field_width_pts"))),
        num("pre_long_field_width_pts", "prior", lambda row: as_float(row.get("pre_long_field_width_pts"))),
        num("pre_side_edge_pct", "prior", lambda row: as_float(row.get("pre_side_edge_pct"))),
        num("pre_side_edge_distance_pts", "prior", lambda row: as_float(row.get("pre_side_edge_distance_pts"))),
        num("pre_owner_delta_5m", "prior", lambda row: owner_delta(row, "pre_delta_5m")),
        num("pre_owner_delta_10m", "prior", lambda row: owner_delta(row, "pre_long_delta_10m")),
        num("pre_same_claim_5m", "prior", lambda row: as_float(row.get("pre_same_claim_5m"))),
        num("pre_opp_claim_5m", "prior", lambda row: as_float(row.get("pre_opp_claim_5m"))),
        num("pre_same_fail_5m", "prior", lambda row: as_float(row.get("pre_same_fail_5m"))),
        num("pre_opp_fail_5m", "prior", lambda row: as_float(row.get("pre_opp_fail_5m"))),
        num("pre_same_consumed_5m", "prior", lambda row: as_float(row.get("pre_same_consumed_5m"))),
        num("pre_opp_consumed_5m", "prior", lambda row: as_float(row.get("pre_opp_consumed_5m"))),
    ]

    for prefix, family in (("conv", "conversion_book"), ("test", "retest_book")):
        specs.extend(
            [
                cat(f"{prefix}_replenishment_2s_bucket", family),
                cat(f"{prefix}_replenishment_5s_bucket", family),
                num(f"{prefix}_same_depth", family, lambda row, p=prefix: owner_side_depth(row, p, "same_depth")),
                num(f"{prefix}_opp_depth", family, lambda row, p=prefix: owner_side_depth(row, p, "opp_depth")),
                num(
                    f"{prefix}_same_to_opp_depth_ratio",
                    family,
                    lambda row, p=prefix: ratio(as_float(row.get(f"{p}_same_depth")), as_float(row.get(f"{p}_opp_depth"))),
                ),
                num(
                    f"{prefix}_owner_depth_delta",
                    family,
                    lambda row, p=prefix: diff(as_float(row.get(f"{p}_same_depth")), as_float(row.get(f"{p}_opp_depth"))),
                ),
                num(f"{prefix}_owner_behind_depth", family, lambda row, p=prefix: owner_behind_depth(row, p)),
                num(f"{prefix}_owner_ahead_depth", family, lambda row, p=prefix: owner_ahead_depth(row, p)),
                num(
                    f"{prefix}_behind_minus_ahead_owner_depth",
                    family,
                    lambda row, p=prefix: diff(owner_behind_depth(row, p), owner_ahead_depth(row, p)),
                ),
                num(
                    f"{prefix}_behind_owner_minus_opp_depth",
                    family,
                    lambda row, p=prefix: diff(owner_behind_depth(row, p), opp_behind_depth(row, p)),
                ),
                num(f"{prefix}_top20_owner_delta", family, lambda row, p=prefix: owner_top20_delta(row, p)),
                num(f"{prefix}_hostile_vol_2s", family, lambda row, p=prefix: as_float(row.get(f"{p}_hostile_vol_2s"))),
                num(f"{prefix}_aligned_vol_2s", family, lambda row, p=prefix: as_float(row.get(f"{p}_aligned_vol_2s"))),
                num(f"{prefix}_owner_flow_2s", family, lambda row, p=prefix: owner_flow(row, p, 2)),
                num(f"{prefix}_reload_ratio_2s", family, lambda row, p=prefix: as_float(row.get(f"{p}_reload_ratio_2s"))),
                num(f"{prefix}_hostile_vol_5s", family, lambda row, p=prefix: as_float(row.get(f"{p}_hostile_vol_5s"))),
                num(f"{prefix}_aligned_vol_5s", family, lambda row, p=prefix: as_float(row.get(f"{p}_aligned_vol_5s"))),
                num(f"{prefix}_owner_flow_5s", family, lambda row, p=prefix: owner_flow(row, p, 5)),
                num(f"{prefix}_reload_ratio_5s", family, lambda row, p=prefix: as_float(row.get(f"{p}_reload_ratio_5s"))),
            ]
        )

    specs.extend(
        [
            cat("time_to_test_bucket", "retest_approach"),
            num("time_to_first_test_s", "retest_approach", lambda row: as_float(row.get("time_to_first_test_s"))),
            num("fav_before_test_pts", "retest_approach", lambda row: as_float(row.get("fav_before_test_pts"))),
            num("adv_before_test_pts", "retest_approach", lambda row: as_float(row.get("adv_before_test_pts"))),
            num("approach_velocity_pts_s", "retest_approach", lambda row: as_float(row.get("approach_velocity_pts_s"))),
        ]
    )
    return specs


def quantile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = (len(ordered) - 1) * q
    lo = math.floor(idx)
    hi = math.ceil(idx)
    if lo == hi:
        return ordered[int(idx)]
    return ordered[lo] * (hi - idx) + ordered[hi] * (idx - lo)


def fmt_num(value: float) -> str:
    if abs(value) >= 100:
        return f"{value:.0f}"
    if abs(value) >= 10:
        return f"{value:.1f}"
    return f"{value:.2f}"


def numeric_bucket(value: float | None, cuts: tuple[float, float] | None) -> str:
    if value is None:
        return "0_missing"
    if cuts is None:
        return f"1_value={fmt_num(value)}"
    lo, hi = cuts
    if value <= lo:
        return f"1_low<={fmt_num(lo)}"
    if value <= hi:
        return f"2_mid<={fmt_num(hi)}"
    return f"3_high>{fmt_num(hi)}"


def bucket_values(rows: list[dict[str, str]], specs: list[FeatureSpec]) -> tuple[dict[str, list[str]], dict[str, str]]:
    raw: dict[str, list[str | float | None]] = {}
    families: dict[str, str] = {}
    for spec in specs:
        raw[spec.name] = [spec.getter(row) for row in rows]
        families[spec.name] = spec.family

    buckets: dict[str, list[str]] = {}
    for spec in specs:
        values = raw[spec.name]
        if spec.kind == "cat":
            buckets[spec.name] = [str(value or "missing") for value in values]
            continue
        numeric = [value for value in values if isinstance(value, float) and math.isfinite(value)]
        unique = sorted(set(numeric))
        cuts: tuple[float, float] | None
        if len(unique) <= 3:
            cuts = None
        else:
            q1 = quantile(numeric, 1.0 / 3.0)
            q2 = quantile(numeric, 2.0 / 3.0)
            cuts = None if abs(q2 - q1) < 1e-9 else (q1, q2)
        buckets[spec.name] = [
            numeric_bucket(value if isinstance(value, float) else None, cuts)
            for value in values
        ]
    return buckets, families


def mean(values: Iterable[float]) -> float:
    values = list(values)
    return sum(values) / len(values) if values else 0.0


def median(values: Iterable[float | None]) -> str:
    clean = [value for value in values if value is not None and math.isfinite(value)]
    if not clean:
        return ""
    return str(round(statistics.median(clean), 3))


def targets(row: dict[str, str], durable_path_threshold: float, bad_path_threshold: float) -> dict[str, float]:
    outcome = row.get("same_band_outcome", "")
    held_5m = float(as_int(row.get("held_5m")))
    failed_5m = float(as_int(row.get("failed_5m")))
    path_5m = as_float(row.get("path_score_5m")) or 0.0
    return {
        "held_5m": held_5m,
        "failed_5m": failed_5m,
        "retest_failed_any": 1.0 if outcome in BAD_OUTCOMES else 0.0,
        "durable_success": 1.0
        if outcome in GOOD_OUTCOMES and held_5m > 0.0 and path_5m >= durable_path_threshold
        else 0.0,
        "early_bad": 1.0 if failed_5m > 0.0 or path_5m <= bad_path_threshold else 0.0,
    }


def stat_row(
    rows: list[dict[str, str]],
    idxs: list[int],
    feature: str,
    bucket: str,
    family: str,
    overall: dict[str, float],
) -> dict[str, Any]:
    target_rows = [rows[idx] for idx in idxs]
    target_values = [row["_targets"] for row in target_rows]  # type: ignore[index]
    path_scores = [as_float(row.get("path_score_5m")) for row in target_rows]
    times = [as_float(row.get("time_to_first_test_s")) for row in target_rows]
    failed_rate = mean(target["failed_5m"] for target in target_values)
    durable_rate = mean(target["durable_success"] for target in target_values)
    examples = "; ".join(
        f"{row.get('event_ts_et')} {row.get('side')} {row.get('price_lo')}-{row.get('price_hi')}"
        for row in sorted(
            target_rows,
            key=lambda item: (
                -as_int(item.get("failed_5m")),
                -(as_float(item.get("path_score_5m")) or 0.0),
            ),
        )[:3]
    )
    return {
        "family": family,
        "feature": feature,
        "bucket": bucket,
        "n": len(idxs),
        "sample_pct": round(len(idxs) / len(rows), 3) if rows else 0.0,
        "held_5m_rate": round(mean(target["held_5m"] for target in target_values), 3),
        "failed_5m_rate": round(failed_rate, 3),
        "retest_failed_any_rate": round(mean(target["retest_failed_any"] for target in target_values), 3),
        "durable_success_rate": round(durable_rate, 3),
        "early_bad_rate": round(mean(target["early_bad"] for target in target_values), 3),
        "failed_5m_lift": round(failed_rate - overall["failed_5m"], 3),
        "durable_success_lift": round(durable_rate - overall["durable_success"], 3),
        "median_path_score_5m": median(path_scores),
        "median_time_to_test_s": median(times),
        "examples": examples,
    }


def summarize_feature(
    rows: list[dict[str, str]],
    feature: str,
    values: list[str],
    family: str,
    overall: dict[str, float],
    min_n: int,
) -> list[dict[str, Any]]:
    groups: dict[str, list[int]] = defaultdict(list)
    for idx, value in enumerate(values):
        groups[value].append(idx)
    stats: list[dict[str, Any]] = []
    for bucket, idxs in groups.items():
        if len(idxs) >= min_n:
            stats.append(stat_row(rows, idxs, feature, bucket, family, overall))
    return sorted(stats, key=lambda row: (row["feature"], row["bucket"]))


def feature_rank(feature_rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    if len(feature_rows) < 2:
        return None
    failed_rates = [float(row["failed_5m_rate"]) for row in feature_rows]
    durable_rates = [float(row["durable_success_rate"]) for row in feature_rows]
    ns = [int(row["n"]) for row in feature_rows]
    ordered_rows = sorted(feature_rows, key=lambda row: str(row["bucket"]))
    ordered_failed = [float(row["failed_5m_rate"]) for row in ordered_rows if str(row["bucket"])[0:2] in {"1_", "2_", "3_"}]
    direction = ""
    if len(ordered_failed) >= 3:
        if all(a <= b + 1e-9 for a, b in zip(ordered_failed, ordered_failed[1:])):
            direction = "failure_increases_with_bucket"
        elif all(a + 1e-9 >= b for a, b in zip(ordered_failed, ordered_failed[1:])):
            direction = "failure_decreases_with_bucket"
    sep_failed = max(failed_rates) - min(failed_rates)
    sep_durable = max(durable_rates) - min(durable_rates)
    return {
        "family": feature_rows[0]["family"],
        "feature": feature_rows[0]["feature"],
        "buckets": len(feature_rows),
        "covered_n": sum(ns),
        "failed_5m_low": round(min(failed_rates), 3),
        "failed_5m_high": round(max(failed_rates), 3),
        "failed_5m_separation": round(sep_failed, 3),
        "durable_success_low": round(min(durable_rates), 3),
        "durable_success_high": round(max(durable_rates), 3),
        "durable_success_separation": round(sep_durable, 3),
        "ordered_direction": direction,
        "rank_score": round(max(sep_failed, sep_durable) * math.log10(sum(ns) + 1), 3),
    }


def combo_rows(
    rows: list[dict[str, str]],
    buckets: dict[str, list[str]],
    families: dict[str, str],
    ranked_features: list[str],
    overall: dict[str, float],
    combo_min_n: int,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for left_idx, left in enumerate(ranked_features):
        for right in ranked_features[left_idx + 1:]:
            groups: dict[str, list[int]] = defaultdict(list)
            for idx in range(len(rows)):
                bucket = f"{left}={buckets[left][idx]} | {right}={buckets[right][idx]}"
                groups[bucket].append(idx)
            family = f"{families[left]}+{families[right]}"
            for bucket, idxs in groups.items():
                if len(idxs) < combo_min_n:
                    continue
                out.append(stat_row(rows, idxs, f"{left}+{right}", bucket, family, overall))
    out.sort(
        key=lambda row: (
            max(abs(float(row["failed_5m_lift"])), abs(float(row["durable_success_lift"]))),
            int(row["n"]),
        ),
        reverse=True,
    )
    return out


def useful_combo(row: dict[str, Any], *, min_n: int) -> bool:
    if int(row["n"]) < min_n:
        return False
    bucket = str(row["bucket"])
    return not any(token in bucket for token in ("missing", "unknown", "no_retest"))


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if fieldnames is None:
        fieldnames = []
        seen = set()
        for row in rows:
            for key in row:
                if key not in seen:
                    seen.add(key)
                    fieldnames.append(key)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def top(rows: list[dict[str, Any]], key: str, count: int = 10) -> list[dict[str, Any]]:
    return sorted(rows, key=lambda row: (float(row[key]), int(row["n"])), reverse=True)[:count]


def write_markdown(
    path: Path,
    rows: list[dict[str, str]],
    feature_stats: list[dict[str, Any]],
    rankings: list[dict[str, Any]],
    combos: list[dict[str, Any]],
    nonmissing_combos: list[dict[str, Any]],
    overall: dict[str, float],
) -> None:
    lines: list[str] = [
        "# DirectConversion Bucket Analysis",
        "",
        "Predictor-only bucket ranking from the synthetic LL direct-conversion population.",
        "",
        "## Population",
        "",
        f"- Events: {len(rows)}",
        f"- held_5m_rate: {overall['held_5m']:.3f}",
        f"- failed_5m_rate: {overall['failed_5m']:.3f}",
        f"- retest_failed_any_rate: {overall['retest_failed_any']:.3f}",
        f"- durable_success_rate: {overall['durable_success']:.3f}",
        f"- early_bad_rate: {overall['early_bad']:.3f}",
        "",
        "## Top Feature Separations",
        "",
    ]
    for row in rankings[:15]:
        lines.append(
            f"- {row['family']}:{row['feature']}: "
            f"fail5 {row['failed_5m_low']}-{row['failed_5m_high']} "
            f"durable {row['durable_success_low']}-{row['durable_success_high']} "
            f"score={row['rank_score']} {row['ordered_direction']}"
        )

    conversion_families = {"event", "prior", "conversion_book"}
    conversion_rankings = [row for row in rankings if row["family"] in conversion_families]
    retest_rankings = [row for row in rankings if row["family"] not in conversion_families]
    lines.extend(["", "## Conversion-Time Candidates", ""])
    for row in conversion_rankings[:10]:
        lines.append(
            f"- {row['family']}:{row['feature']}: fail_sep={row['failed_5m_separation']}, "
            f"durable_sep={row['durable_success_separation']}"
        )
    conversion_buckets = [
        row for row in feature_stats
        if row["family"] in conversion_families and int(row["n"]) >= 8
    ]
    lines.extend(["", "## Conversion-Time Bucket Examples", ""])
    for row in top(
        [row for row in conversion_buckets if float(row["failed_5m_lift"]) > 0],
        "failed_5m_rate",
        8,
    ):
        lines.append(
            f"- fail: {row['feature']}={row['bucket']}: n={row['n']}, "
            f"fail5={row['failed_5m_rate']}, durable={row['durable_success_rate']}, "
            f"median_path5={row['median_path_score_5m']}"
        )
    for row in top(
        [row for row in conversion_buckets if float(row["durable_success_lift"]) > 0],
        "durable_success_rate",
        8,
    ):
        lines.append(
            f"- durable: {row['feature']}={row['bucket']}: n={row['n']}, "
            f"durable={row['durable_success_rate']}, fail5={row['failed_5m_rate']}, "
            f"median_path5={row['median_path_score_5m']}"
        )
    lines.extend(["", "## Retest-Decision Candidates", ""])
    for row in retest_rankings[:10]:
        lines.append(
            f"- {row['family']}:{row['feature']}: fail_sep={row['failed_5m_separation']}, "
            f"durable_sep={row['durable_success_separation']}"
        )

    failure_buckets = [
        row for row in feature_stats
        if int(row["n"]) >= 5 and float(row["failed_5m_lift"]) > 0
    ]
    success_buckets = [
        row for row in feature_stats
        if int(row["n"]) >= 5 and float(row["durable_success_lift"]) > 0
    ]
    lines.extend(["", "## High-Failure Buckets", ""])
    for row in top(failure_buckets, "failed_5m_rate", 12):
        lines.append(
            f"- {row['feature']}={row['bucket']}: n={row['n']}, "
            f"fail5={row['failed_5m_rate']}, durable={row['durable_success_rate']} "
            f"examples: {row['examples']}"
        )
    lines.extend(["", "## High-Durable Buckets", ""])
    for row in top(success_buckets, "durable_success_rate", 12):
        lines.append(
            f"- {row['feature']}={row['bucket']}: n={row['n']}, "
            f"durable={row['durable_success_rate']}, fail5={row['failed_5m_rate']} "
            f"examples: {row['examples']}"
        )
    lines.extend(["", "## Pairwise Buckets", ""])
    for row in combos[:15]:
        lines.append(
            f"- {row['bucket']}: n={row['n']}, fail5={row['failed_5m_rate']}, "
            f"durable={row['durable_success_rate']}, lift_fail={row['failed_5m_lift']}, "
            f"lift_durable={row['durable_success_lift']}"
        )
    lines.extend(["", "## Non-Missing Pairwise Buckets", ""])
    lines.append("")
    lines.append("High failure:")
    for row in top(nonmissing_combos, "failed_5m_rate", 10):
        lines.append(
            f"- {row['bucket']}: n={row['n']}, fail5={row['failed_5m_rate']}, "
            f"durable={row['durable_success_rate']}, median_path5={row['median_path_score_5m']}"
        )
    lines.append("")
    lines.append("High durable:")
    for row in top(nonmissing_combos, "durable_success_rate", 10):
        lines.append(
            f"- {row['bucket']}: n={row['n']}, durable={row['durable_success_rate']}, "
            f"fail5={row['failed_5m_rate']}, median_path5={row['median_path_score_5m']}"
        )
    lines.extend(
        [
            "",
            "## Read",
            "",
            "- Treat this as a search/ranking pass, not a rule. Several fields are available only at the retest decision.",
            "- The useful split is likely multi-dimensional: conversion-time quality filters plus retest-time acceptance/reload behavior.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    args = parse_args()
    events_path = Path(args.events_csv)
    out_dir = Path(args.out_dir)
    with events_path.open("r", newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    specs = features()
    buckets, families = bucket_values(rows, specs)
    for row in rows:
        row["_targets"] = targets(row, args.durable_path_threshold, args.bad_path_threshold)  # type: ignore[assignment]
    overall = {
        key: mean(row["_targets"][key] for row in rows)  # type: ignore[index]
        for key in ["held_5m", "failed_5m", "retest_failed_any", "durable_success", "early_bad"]
    }

    feature_stats: list[dict[str, Any]] = []
    grouped_by_feature: dict[str, list[dict[str, Any]]] = {}
    for spec in specs:
        stats = summarize_feature(rows, spec.name, buckets[spec.name], spec.family, overall, args.min_n)
        if stats:
            feature_stats.extend(stats)
            grouped_by_feature[spec.name] = stats

    rankings = [
        ranked for ranked in (feature_rank(stats) for stats in grouped_by_feature.values())
        if ranked is not None
    ]
    rankings.sort(key=lambda row: (float(row["rank_score"]), int(row["covered_n"])), reverse=True)
    ranked_features = [row["feature"] for row in rankings]
    if args.top_features > 0:
        ranked_features = ranked_features[: args.top_features]
    combos = combo_rows(rows, buckets, families, ranked_features, overall, args.combo_min_n)
    nonmissing_combos = [row for row in combos if useful_combo(row, min_n=max(args.combo_min_n, 8))]
    combo_rows_to_write = combos if args.max_combo_rows <= 0 else combos[: args.max_combo_rows]
    nonmissing_rows_to_write = (
        nonmissing_combos
        if args.max_combo_rows <= 0
        else nonmissing_combos[: args.max_combo_rows]
    )

    write_csv(out_dir / "bucket_predictors.csv", feature_stats)
    write_csv(out_dir / "feature_rankings.csv", rankings)
    write_csv(out_dir / "combo_predictors.csv", combo_rows_to_write)
    write_csv(out_dir / "combo_predictors_nonmissing.csv", nonmissing_rows_to_write)
    write_markdown(out_dir / "analysis.md", rows, feature_stats, rankings, combos, nonmissing_combos, overall)

    print(f"wrote {out_dir / 'bucket_predictors.csv'} rows={len(feature_stats)}")
    print(f"wrote {out_dir / 'feature_rankings.csv'} rows={len(rankings)}")
    print(f"wrote {out_dir / 'combo_predictors.csv'} rows={len(combo_rows_to_write)}")
    print(f"wrote {out_dir / 'combo_predictors_nonmissing.csv'} rows={len(nonmissing_rows_to_write)}")
    print(f"wrote {out_dir / 'analysis.md'}")


if __name__ == "__main__":
    main()
