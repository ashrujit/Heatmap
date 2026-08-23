"""Join decision-time book evidence to sponsor-lineage outcomes.

This analysis deliberately avoids fixed price-horizon labels. Stage 1 asks
whether a traded consumed root established favorable ownership before failing.
Stage 2 asks whether a failed favorable child was contained/repaired before the
consumed root failed.
"""

from __future__ import annotations

import argparse
import csv
import math
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from _paths import OUTPUT_ROOT

DEFAULT_PROVISION = (
    OUTPUT_ROOT
    / "direct_conversion_entry_provision_20260724"
    / "entry_provision.csv"
)
DEFAULT_LINEAGE = (
    OUTPUT_ROOT / "direct_conversion_sponsor_lineage" / "lineage.csv"
)
DEFAULT_OUT = (
    OUTPUT_ROOT / "direct_conversion_lineage_features_20260724"
)

STAGE1_POSITIVE = "ADVANCED_AFTER_ENTRY"
STAGE1_NEGATIVE = "ROOT_FAILED_AFTER_ENTRY"
STAGE2_POSITIVE = {
    "CONTAINED_BY_EXISTING_FAVORABLE_SPONSOR",
    "REESTABLISHED_BEFORE_ROOT_FAILURE",
}
STAGE2_NEGATIVE = "ROOT_FAILED_BEFORE_REESTABLISHMENT"

FEATURES = (
    "rail_age_at_decision_s",
    "entry_distance_from_band_pts",
    "width_pts",
    "attack_span_s",
    "attack_delta_events",
    "seed_loser_size",
    "eaten",
    "material_magnitude",
    "attack_replenishment",
    "attack_repl_ratio",
    "decision_span_s",
    "decision_delta_events",
    "decision_loser_added",
    "decision_loser_removed",
    "decision_gross_return_ratio",
    "decision_owner_seed",
    "decision_owner_end",
    "decision_owner_added",
    "decision_owner_removed",
    "decision_owner_depth_delta",
    "attack_event_rate",
    "decision_event_rate",
    "decision_owner_turnover",
    "decision_owner_turnover_rate",
    "decision_owner_turnover_to_seed",
    "decision_loser_turnover",
    "decision_loser_turnover_rate",
    "decision_loser_added_to_magnitude",
)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def as_float(value: Any) -> float | None:
    if value in ("", None):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def fmt(value: float | None) -> str:
    if value is None:
        return ""
    if abs(value) >= 100:
        return f"{value:.0f}"
    if abs(value) >= 10:
        return f"{value:.1f}"
    return f"{value:.3f}"


def ratio(num: float | None, den: float | None) -> float | None:
    if num is None or den is None or abs(den) < 1e-9:
        return None
    return num / den


def add_derived_features(row: dict[str, str]) -> None:
    attack_span = as_float(row.get("attack_span_s"))
    attack_events = as_float(row.get("attack_delta_events"))
    decision_span = as_float(row.get("decision_span_s"))
    decision_events = as_float(row.get("decision_delta_events"))
    owner_seed = as_float(row.get("decision_owner_seed"))
    owner_added = as_float(row.get("decision_owner_added"))
    owner_removed = as_float(row.get("decision_owner_removed"))
    loser_added = as_float(row.get("decision_loser_added"))
    loser_removed = as_float(row.get("decision_loser_removed"))
    magnitude = as_float(row.get("material_magnitude"))
    owner_turnover = (
        owner_added + owner_removed
        if owner_added is not None and owner_removed is not None
        else None
    )
    loser_turnover = (
        loser_added + loser_removed
        if loser_added is not None and loser_removed is not None
        else None
    )
    derived = {
        "attack_event_rate": ratio(attack_events, attack_span),
        "decision_event_rate": ratio(decision_events, decision_span),
        "decision_owner_turnover": owner_turnover,
        "decision_owner_turnover_rate": ratio(owner_turnover, decision_span),
        "decision_owner_turnover_to_seed": ratio(owner_turnover, owner_seed),
        "decision_loser_turnover": loser_turnover,
        "decision_loser_turnover_rate": ratio(loser_turnover, decision_span),
        "decision_loser_added_to_magnitude": ratio(loser_added, magnitude),
    }
    for key, value in derived.items():
        row[key] = "" if value is None else repr(value)


def median(values: list[float]) -> float | None:
    return statistics.median(values) if values else None


def auc(positive: list[float], negative: list[float]) -> float | None:
    """Probability that a random positive value exceeds a negative value."""
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


def key_for_provision(row: dict[str, str]) -> tuple[str, str, str]:
    return row["date"], row["decision_et"], row["band_id"]


def key_for_lineage(row: dict[str, str]) -> tuple[str, str, str]:
    return row["date"], row["first_entry_et"], row["root_id"]


def join_rows(
    provision: list[dict[str, str]],
    lineage: list[dict[str, str]],
) -> tuple[list[dict[str, str]], list[tuple[str, str, str]]]:
    lineage_by_key = {
        key_for_lineage(row): row
        for row in lineage
        if row.get("traded", "").lower() == "true"
    }
    joined: list[dict[str, str]] = []
    unmatched: list[tuple[str, str, str]] = []
    lineage_fields = (
        "session_id",
        "root_first_test_verdict",
        "root_failed_et",
        "post_entry_successor_id",
        "post_entry_successor_source",
        "post_entry_successor_distance_pts",
        "post_entry_successor_owned_et",
        "post_entry_successor_first_test_verdict",
        "post_entry_successor_failed_et",
        "entry_structural_outcome",
        "successor_failure_propagation",
        "existing_live_favorable_id_at_successor_failure",
        "post_child_reestablishment_id",
        "post_child_reestablishment_owned_et",
    )
    for row in provision:
        key = key_for_provision(row)
        match = lineage_by_key.get(key)
        if match is None:
            unmatched.append(key)
            continue
        merged = dict(row)
        for field in lineage_fields:
            merged[field] = match.get(field, "")
        add_derived_features(merged)
        joined.append(merged)
    return joined, unmatched


def numeric_ranking(
    rows: list[dict[str, str]],
    label_key: str,
    positive_labels: set[str],
    negative_labels: set[str],
) -> list[dict[str, Any]]:
    ranked: list[dict[str, Any]] = []
    for feature in FEATURES:
        positive = [
            value
            for row in rows
            if row.get(label_key) in positive_labels
            and (value := as_float(row.get(feature))) is not None
        ]
        negative = [
            value
            for row in rows
            if row.get(label_key) in negative_labels
            and (value := as_float(row.get(feature))) is not None
        ]
        raw_auc = auc(positive, negative)
        if raw_auc is None:
            continue
        ranked.append(
            {
                "feature": feature,
                "positive_n": len(positive),
                "negative_n": len(negative),
                "positive_median": median(positive),
                "negative_median": median(negative),
                "auc_positive_higher": raw_auc,
                "separation": abs(raw_auc - 0.5),
                "direction": "higher" if raw_auc >= 0.5 else "lower",
            }
        )
    return sorted(ranked, key=lambda row: row["separation"], reverse=True)


def categorical_counts(
    rows: list[dict[str, str]],
    label_key: str,
    positive_labels: set[str],
    negative_labels: set[str],
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for feature in ("role", "side", "attack_provision_class"):
        groups: dict[str, Counter[str]] = defaultdict(Counter)
        for row in rows:
            label = row.get(label_key, "")
            if label in positive_labels:
                groups[row.get(feature, "") or "missing"]["positive"] += 1
            elif label in negative_labels:
                groups[row.get(feature, "") or "missing"]["negative"] += 1
        for value, counts in sorted(groups.items()):
            total = counts["positive"] + counts["negative"]
            output.append(
                {
                    "feature": feature,
                    "value": value,
                    "positive": counts["positive"],
                    "negative": counts["negative"],
                    "positive_rate": counts["positive"] / total if total else None,
                }
            )
    return output


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def report_table(ranking: list[dict[str, Any]], limit: int = 10) -> list[str]:
    lines = [
        "| feature | positive median | negative median | AUC if higher predicts positive | direction |",
        "|---|---:|---:|---:|---|",
    ]
    for row in ranking[:limit]:
        lines.append(
            f"| {row['feature']} | {fmt(row['positive_median'])} | "
            f"{fmt(row['negative_median'])} | {row['auc_positive_higher']:.3f} | "
            f"{row['direction']} |"
        )
    return lines


def build_report(
    joined: list[dict[str, str]],
    unmatched: list[tuple[str, str, str]],
    stage1: list[dict[str, Any]],
    stage2: list[dict[str, Any]],
    stage1_categories: list[dict[str, Any]],
    stage2_categories: list[dict[str, Any]],
) -> str:
    stage1_counts = Counter(row["entry_structural_outcome"] for row in joined)
    stage2_rows = [
        row
        for row in joined
        if row["successor_failure_propagation"] in STAGE2_POSITIVE | {STAGE2_NEGATIVE}
    ]
    stage2_counts = Counter(row["successor_failure_propagation"] for row in stage2_rows)
    lines = [
        "# Direct-Conversion Lineage Features",
        "",
        "The target is sponsor survival, not a fixed favorable/adverse price horizon.",
        "",
        "## Population",
        "",
        f"- joined decisions={len(joined)}",
        f"- unmatched decisions={len(unmatched)}",
        f"- stage 1 advanced before root failure={stage1_counts[STAGE1_POSITIVE]}",
        f"- stage 1 root failed before advance={stage1_counts[STAGE1_NEGATIVE]}",
        f"- stage 2 contained or re-established={sum(stage2_counts[label] for label in STAGE2_POSITIVE)}",
        f"- stage 2 root failed before re-establishment={stage2_counts[STAGE2_NEGATIVE]}",
        "",
        "## Stage 1: Entry Establishes New Sponsorship",
        "",
        "Positive means a favorable sponsor formed after the entry decision and before the consumed root failed.",
        "",
        *report_table(stage1),
        "",
        "## Stage 2: Failed Child Is Contained Or Repaired",
        "",
        "This subset includes advanced roots whose favorable child later failed. Positive means an already-live favorable sponsor contained the failure or same-side sponsorship re-established before root failure.",
        "",
        *report_table(stage2),
        "",
        "## Categorical Audits",
        "",
        "| stage | feature | value | positive | negative | positive rate |",
        "|---|---|---|---:|---:|---:|",
    ]
    for stage, rows in (("stage1", stage1_categories), ("stage2", stage2_categories)):
        for row in rows:
            lines.append(
                f"| {stage} | {row['feature']} | {row['value']} | "
                f"{row['positive']} | {row['negative']} | "
                f"{row['positive_rate']:.3f} |"
            )
    lines.extend(
        [
            "",
            "## Interpretation Boundary",
            "",
            "- AUC is descriptive rank separation in this captured decision sample, not a validated threshold.",
            "- Stage 1 predictors are observable at entry. Stage 2 currently reuses entry-time features only as a falsification check; a real keep/exit rule needs book state at child promotion and child test/failure.",
            "- Rows from one directive campaign are policy-correlated and are not independent trials.",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--provision-csv",
        type=Path,
        action="append",
        help="May be repeated. Defaults to the July 24 fixture.",
    )
    parser.add_argument("--lineage-csv", type=Path, default=DEFAULT_LINEAGE)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()

    provision_paths = args.provision_csv or [DEFAULT_PROVISION]
    provision = [
        row
        for provision_path in provision_paths
        for row in read_csv(provision_path)
    ]
    lineage = read_csv(args.lineage_csv)
    joined, unmatched = join_rows(provision, lineage)
    if not joined:
        raise SystemExit("no provision rows matched lineage rows")

    stage1 = numeric_ranking(
        joined,
        "entry_structural_outcome",
        {STAGE1_POSITIVE},
        {STAGE1_NEGATIVE},
    )
    stage2 = numeric_ranking(
        joined,
        "successor_failure_propagation",
        STAGE2_POSITIVE,
        {STAGE2_NEGATIVE},
    )
    stage1_categories = categorical_counts(
        joined,
        "entry_structural_outcome",
        {STAGE1_POSITIVE},
        {STAGE1_NEGATIVE},
    )
    stage2_categories = categorical_counts(
        joined,
        "successor_failure_propagation",
        STAGE2_POSITIVE,
        {STAGE2_NEGATIVE},
    )

    write_csv(args.out_dir / "joined.csv", joined)
    write_csv(args.out_dir / "stage1_numeric_ranking.csv", stage1)
    write_csv(args.out_dir / "stage2_numeric_ranking.csv", stage2)
    write_csv(args.out_dir / "stage1_categorical.csv", stage1_categories)
    write_csv(args.out_dir / "stage2_categorical.csv", stage2_categories)
    report = build_report(
        joined,
        unmatched,
        stage1,
        stage2,
        stage1_categories,
        stage2_categories,
    )
    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "findings.md").write_text(report, encoding="utf-8")
    print(report, end="")
    print(f"\nwrote {args.out_dir} rows={len(joined)}")


if __name__ == "__main__":
    main()
