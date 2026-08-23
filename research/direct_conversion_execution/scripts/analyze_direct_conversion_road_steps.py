"""Stratified analysis for `direct_conversion_road_steps.py` output."""

from __future__ import annotations

import argparse
import csv
import math
from collections import defaultdict
from pathlib import Path
from statistics import median
from typing import Any

from _paths import OUTPUT_ROOT

CHECKPOINT_MS = (500, 1_000, 2_000, 5_000)
DEFAULT_STEPS = (
    OUTPUT_ROOT
    / "direct_conversion_road_steps_20260717_20260724"
    / "steps.csv"
)


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
        if not math.isfinite(value):
            return ""
        return f"{value:.{digits}f}"
    return str(value)


def read_rows(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8", newline="") as handle:
        for raw in csv.DictReader(handle):
            row: dict[str, Any] = dict(raw)
            for key in (
                "step_success",
                "entry_state_book_valid",
                *(f"checkpoint_{ms}ms_active" for ms in CHECKPOINT_MS),
                *(f"checkpoint_{ms}ms_book_valid" for ms in CHECKPOINT_MS),
            ):
                if key in row:
                    row[key] = row[key] == "True"
            rows.append(row)
    return rows


def number(row: dict[str, Any], key: str) -> float | None:
    value = row.get(key)
    if value in (None, ""):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def feature_summary(
    rows: list[dict[str, Any]],
    feature: str,
) -> tuple[int, float, float, float] | None:
    success = [
        number(row, feature)
        for row in rows
        if row["step_success"] is True
    ]
    failure = [
        number(row, feature)
        for row in rows
        if row["step_success"] is False
    ]
    success = [value for value in success if value is not None]
    failure = [value for value in failure if value is not None]
    score = auc(success, failure)
    if score is None:
        return None
    return len(success) + len(failure), median(success), median(failure), score


def checkpoint_rows(
    rows: list[dict[str, Any]],
    checkpoint_ms: int,
) -> list[dict[str, Any]]:
    prefix = f"checkpoint_{checkpoint_ms}ms"
    return [
        row
        for row in rows
        if row.get(f"{prefix}_active") is True
        and row.get(f"{prefix}_book_valid") is True
    ]


def checkpoint_state(row: dict[str, Any], checkpoint_ms: int) -> str:
    prefix = f"checkpoint_{checkpoint_ms}ms"
    road = number(row, f"{prefix}_road_remaining_ticks")
    displacement = number(
        row, f"{prefix}_favorable_displacement_ticks"
    )
    provision = number(row, f"{prefix}_winner_net_provision_qty")
    if road is None or displacement is None or provision is None:
        return "UNKNOWN"
    if road <= 0:
        return "ROAD_LOST"
    if displacement >= 0 and provision > 0:
        return "RECOVERING_RELOADING"
    if displacement >= 0:
        return "RECOVERING_DRAINING"
    if provision > 0:
        return "DEEPENING_SUPPORTED"
    return "DEEPENING_DRAINING"


def within_directive_auc(
    rows: list[dict[str, Any]],
    feature: str,
) -> tuple[int, float] | None:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        directive = str(row.get("directive_ids") or "")
        if directive:
            groups[directive].append(row)
    scores: list[float] = []
    for group in groups.values():
        success = [
            number(row, feature)
            for row in group
            if row["step_success"] is True
        ]
        failure = [
            number(row, feature)
            for row in group
            if row["step_success"] is False
        ]
        success = [value for value in success if value is not None]
        failure = [value for value in failure if value is not None]
        score = auc(success, failure)
        if score is not None:
            scores.append(score)
    return (len(scores), median(scores)) if scores else None


def build_report(rows: list[dict[str, Any]], source: Path) -> str:
    entry = [
        row
        for row in rows
        if row["relation"] == "ENTRY_STEP"
        and row["entry_state_book_valid"] is True
    ]
    terminal = [
        row for row in rows if row["resolution"] != "READVANCED"
    ]
    lines = [
        "# Direct Conversion Road-Step Strata",
        "",
        f"Source: `{source}`",
        "",
        "## Entry Step By Role",
        "",
        "| role | feature | n | held/advanced median | failed median | AUC |",
        "|---|---|---:|---:|---:|---:|",
    ]
    entry_features = (
        "entry_step_age_s",
        "entry_step_favorable_displacement_ticks",
        "entry_step_depth_ticks",
        "entry_road_remaining_ticks",
        "entry_depth_vs_prior_max",
        "entry_state_winner_net_provision_qty",
        "entry_state_winner_end_qty",
    )
    for role in ("EnterBase", "Add"):
        group = [row for row in entry if row["entry_roles"] == role]
        for feature in entry_features:
            summary = feature_summary(group, feature)
            if summary is None:
                continue
            count, pos_med, neg_med, score = summary
            lines.append(
                f"| {role} | {feature} | {count} | {fmt(pos_med)} | "
                f"{fmt(neg_med)} | {fmt(score)} |"
            )

    lines.extend(
        [
            "",
            "## Checkpoint Populations",
            "",
            "| population | checkpoint | feature | n | success median | failure median | AUC |",
            "|---|---|---|---:|---:|---:|---:|",
        ]
    )
    populations = {
        "all steps": rows,
        "terminal steps": terminal,
        "entry steps": [
            row for row in rows if row["relation"] == "ENTRY_STEP"
        ],
        "post-entry steps": [
            row for row in rows if row["relation"] == "POST_ENTRY"
        ],
    }
    checkpoint_features = (
        "favorable_displacement_ticks",
        "step_depth_ticks",
        "road_remaining_ticks",
        "depth_vs_prior_max",
        "winner_net_provision_qty",
    )
    for population, population_rows in populations.items():
        for checkpoint_ms in CHECKPOINT_MS:
            eligible = checkpoint_rows(population_rows, checkpoint_ms)
            prefix = f"checkpoint_{checkpoint_ms}ms"
            for suffix in checkpoint_features:
                summary = feature_summary(
                    eligible, f"{prefix}_{suffix}"
                )
                if summary is None:
                    continue
                count, pos_med, neg_med, score = summary
                lines.append(
                    f"| {population} | {checkpoint_ms / 1000:g}s | "
                    f"{suffix} | {count} | {fmt(pos_med)} | "
                    f"{fmt(neg_med)} | {fmt(score)} |"
                )

    lines.extend(
        [
            "",
            "## Terminal-Step States",
            "",
            "| checkpoint | state | n | advanced | failure rate |",
            "|---|---|---:|---:|---:|",
        ]
    )
    for checkpoint_ms in CHECKPOINT_MS:
        eligible = checkpoint_rows(terminal, checkpoint_ms)
        groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in eligible:
            groups[checkpoint_state(row, checkpoint_ms)].append(row)
        for state, group in sorted(groups.items()):
            advanced = sum(row["step_success"] is True for row in group)
            failure_rate = 1.0 - advanced / len(group)
            lines.append(
                f"| {checkpoint_ms / 1000:g}s | {state} | "
                f"{len(group)} | {advanced} | {fmt(failure_rate)} |"
            )

    lines.extend(
        [
            "",
            "## Within-Directive Check",
            "",
            "Median AUC is calculated only across directives containing both successful and failed active steps.",
            "",
            "| checkpoint | feature | eligible directives | median within-directive AUC |",
            "|---|---|---:|---:|",
        ]
    )
    for checkpoint_ms in CHECKPOINT_MS:
        eligible = checkpoint_rows(rows, checkpoint_ms)
        prefix = f"checkpoint_{checkpoint_ms}ms"
        for suffix in checkpoint_features:
            feature = f"{prefix}_{suffix}"
            result = within_directive_auc(eligible, feature)
            if result is None:
                continue
            count, score = result
            lines.append(
                f"| {checkpoint_ms / 1000:g}s | {suffix} | "
                f"{count} | {fmt(score)} |"
            )

    lines.extend(
        [
            "",
            "## Day-Level Local Steps",
            "",
            "| date | active valid n | success | failure | 1s provision success median | failure median | AUC |",
            "|---|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for day in sorted({str(row["date"]) for row in rows}):
        eligible = checkpoint_rows(
            [row for row in rows if row["date"] == day],
            1_000,
        )
        summary = feature_summary(
            eligible, "checkpoint_1000ms_winner_net_provision_qty"
        )
        if summary is None:
            continue
        count, pos_med, neg_med, score = summary
        lines.append(
            f"| {day} | {count} | "
            f"{sum(row['step_success'] is True for row in eligible)} | "
            f"{sum(row['step_success'] is False for row in eligible)} | "
            f"{fmt(pos_med)} | {fmt(neg_med)} | {fmt(score)} |"
        )

    lines.extend(
        [
            "",
            "## Day-Level Terminal Steps",
            "",
            "| date | advanced | failed | 1s provision advanced median | 1s provision failed median |",
            "|---|---:|---:|---:|---:|",
        ]
    )
    for day in sorted({str(row["date"]) for row in terminal}):
        group = [row for row in terminal if row["date"] == day]
        eligible = checkpoint_rows(group, 1_000)
        success_values = [
            number(row, "checkpoint_1000ms_winner_net_provision_qty")
            for row in eligible
            if row["step_success"] is True
        ]
        failure_values = [
            number(row, "checkpoint_1000ms_winner_net_provision_qty")
            for row in eligible
            if row["step_success"] is False
        ]
        success_values = [
            value for value in success_values if value is not None
        ]
        failure_values = [
            value for value in failure_values if value is not None
        ]
        lines.append(
            f"| {day} | "
            f"{sum(row['step_success'] is True for row in group)} | "
            f"{sum(row['step_success'] is False for row in group)} | "
            f"{fmt(median(success_values) if success_values else None)} | "
            f"{fmt(median(failure_values) if failure_values else None)} |"
        )

    lines.extend(
        [
            "",
            "## Limits",
            "",
            "- Entry steps are one per mapped entry, but multiple roots can belong to one directive.",
            "- Checkpoint rows remain correlated within roots and directives; the within-directive table is a falsification check, not a clustered model.",
            "- Terminal-step checkpoints exclude steps that resolved before the checkpoint.",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--steps", type=Path, default=DEFAULT_STEPS)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    output = args.output or args.steps.with_name("strata.md")
    rows = read_rows(args.steps)
    output.write_text(build_report(rows, args.steps), encoding="utf-8")
    print(f"wrote stratified analysis for {len(rows)} steps to {output}")


if __name__ == "__main__":
    main()
