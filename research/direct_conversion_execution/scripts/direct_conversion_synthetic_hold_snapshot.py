"""Validate direct-consumption quality after every synthetic first-test hold.

Unlike the traded-entry probe, this population includes every EAR/LL-equivalent
consumed rail whose first test held while the latest accepted directive was
active and side-compatible, whether or not EAR entered. Snapshot predictors use
only the 10 seconds ending at held confirmation. The outcome is whether a
favorable sponsor formed after the hold before the consumed root failed.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from _paths import OUTPUT_ROOT

from capture_loader import load_capture_window, snapshot_columns  # noqa: E402
from direct_conversion_decision_snapshot import (  # noqa: E402
    as_float,
    auc,
    fmt,
    parse_et,
    price_tick,
    prior_snapshot,
    read_csv,
    set_value,
    snapshot_metrics,
    write_csv,
)


ADVANCED = "ADVANCED_AFTER_FIRST_HOLD"
FAILED = "ROOT_FAILED_AFTER_FIRST_HOLD"
UTC = ZoneInfo("UTC")
DEFAULT_EVENTS = Path.home() / "Documents" / "ExecAssistantRuntime" / "events.jsonl"
DEFAULT_LINEAGE = (
    OUTPUT_ROOT / "direct_conversion_sponsor_lineage" / "lineage.csv"
)
DEFAULT_ACTIVE_OUT = (
    OUTPUT_ROOT / "direct_conversion_active_hold_snapshot_20260716_20260724"
)
DEFAULT_ALL_OUT = (
    OUTPUT_ROOT / "direct_conversion_synthetic_hold_snapshot_20260716_20260724"
)
OFFSETS = (-10, -5, -2, 0)


def parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def load_directives(path: Path) -> list[dict[str, Any]]:
    directives: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if '"event":"directive_accepted"' not in line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not event.get("not_before") or not event.get("expires_at"):
                continue
            directives.append(
                {
                    "directive_id": str(event.get("directive_id") or ""),
                    "accepted": parse_iso(str(event["ts_utc"])),
                    "start": parse_iso(str(event["not_before"])),
                    "end": parse_iso(str(event["expires_at"])),
                    "side": (
                        "Demand"
                        if str(event.get("side")) == "Long"
                        else "Supply"
                    ),
                }
            )
    return sorted(directives, key=lambda row: row["accepted"])


def active_directive(
    directives: list[dict[str, Any]],
    anchor: datetime,
) -> dict[str, Any] | None:
    active = [
        directive
        for directive in directives
        if directive["accepted"] <= anchor
        and directive["start"] <= anchor <= directive["end"]
    ]
    return active[-1] if active else None


def enrich_day(rows: list[dict[str, Any]], symbol_dir: str) -> int:
    start = min(row["_hold"] for row in rows) - timedelta(seconds=12)
    end = max(row["_hold"] for row in rows) + timedelta(seconds=2)
    snapshots = load_capture_window(
        "snapshots",
        symbol_dir,
        start,
        end,
        snapshot_columns(30),
        inclusive_end=True,
    ).sort("timestamp_us")
    snapshot_rows = snapshots.to_dicts()
    times = [int(row["timestamp_us"]) for row in snapshot_rows]

    for rec in rows:
        owner_book = "bid" if rec["side"] == "Demand" else "ask"
        root_lo = price_tick(float(rec["root_lo"]))
        root_hi = price_tick(float(rec["root_hi"]))
        hold_us = int(rec["_hold"].timestamp() * 1_000_000)
        offset_metrics: dict[int, dict[str, float | None]] = {}
        for offset in OFFSETS:
            snapshot, age = prior_snapshot(
                snapshot_rows,
                times,
                hold_us + offset * 1_000_000,
            )
            suffix = f"m{abs(offset)}s" if offset < 0 else "0s"
            set_value(rec, f"hold_{suffix}_snapshot_age_s", age)
            if snapshot is None:
                continue
            metrics = snapshot_metrics(snapshot, owner_book, root_lo, root_hi)
            offset_metrics[offset] = metrics
            for key, value in metrics.items():
                set_value(rec, f"hold_{suffix}_{key}", value)

        current = offset_metrics.get(0)
        if current is None:
            continue
        for seconds in (2, 5, 10):
            before = offset_metrics.get(-seconds)
            if before is None:
                continue
            for key in current:
                if key == "ref_tick":
                    continue
                start_value = before.get(key)
                end_value = current.get(key)
                if start_value is None or end_value is None:
                    continue
                delta = end_value - start_value
                set_value(rec, f"hold_change_{seconds}s_{key}", delta)
                set_value(rec, f"hold_rate_{seconds}s_{key}", delta / seconds)

        two_sided = (
            str(rec.get("hold_pre_10m_50pts_two_sided_fail", "")).lower()
            == "true"
        )
        edge_gap = as_float(
            rec.get("hold_pre_10m_50pts_favorable_edge_gap_pts")
        )
        rec["hold_auction_context"] = (
            "inside_two_sided_churn"
            if two_sided and (edge_gap is None or edge_gap <= 0)
            else "clean_or_escaped_field"
        )
        rec["hold_near_touch_stacking_state"] = (
            "stacked"
            if (as_float(rec.get("hold_change_5s_owner_top5")) or 0.0) > 0
            else "flat_or_pulled"
        )
    return snapshots.height


def feature_names(rows: list[dict[str, Any]]) -> list[str]:
    return sorted(
        key
        for key in rows[0]
        if (
            key.startswith(("hold_change_", "hold_rate_"))
            or key.startswith("hold_pre_")
            or key.startswith("hold_live_")
        )
        and "snapshot_age" not in key
    )


def rank_features(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ranked: list[dict[str, Any]] = []
    for feature in feature_names(rows):
        positive = [
            value
            for row in rows
            if row["hold_structural_outcome"] == ADVANCED
            and (value := as_float(row.get(feature))) is not None
        ]
        negative = [
            value
            for row in rows
            if row["hold_structural_outcome"] == FAILED
            and (value := as_float(row.get(feature))) is not None
        ]
        if len(positive) < 20 or len(negative) < 20:
            continue
        rank_auc = auc(positive, negative)
        ranked.append(
            {
                "feature": feature,
                "advanced_n": len(positive),
                "failed_n": len(negative),
                "advanced_median": statistics.median(positive),
                "failed_median": statistics.median(negative),
                "auc_advanced_higher": rank_auc,
                "separation": abs(rank_auc - 0.5),
                "direction": "higher" if rank_auc >= 0.5 else "lower",
            }
        )
    return sorted(ranked, key=lambda row: row["separation"], reverse=True)


def interaction_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for split in ("overall", "side", "date"):
        groups: dict[tuple[str, str, str], Counter[str]] = defaultdict(Counter)
        for row in rows:
            outcome = row["hold_structural_outcome"]
            if outcome not in {ADVANCED, FAILED}:
                continue
            if not row.get("hold_auction_context") or not row.get(
                "hold_near_touch_stacking_state"
            ):
                continue
            population = "all" if split == "overall" else str(row.get(split, ""))
            key = (
                population,
                str(row.get("hold_auction_context", "")),
                str(row.get("hold_near_touch_stacking_state", "")),
            )
            groups[key][outcome] += 1
        for (population, context, stacking), counts in sorted(groups.items()):
            total = counts[ADVANCED] + counts[FAILED]
            output.append(
                {
                    "split": split,
                    "population": population,
                    "context": context,
                    "stacking": stacking,
                    "advanced": counts[ADVANCED],
                    "failed": counts[FAILED],
                    "advanced_rate": counts[ADVANCED] / total if total else None,
                }
            )
    return output


def build_report(
    rows: list[dict[str, Any]],
    ranking: list[dict[str, Any]],
    interactions: list[dict[str, Any]],
    health: list[str],
    population_description: str,
) -> str:
    counts = Counter(row["hold_structural_outcome"] for row in rows)
    lines = [
        "# Synthetic Direct-Conversion First-Hold Snapshot",
        "",
        population_description,
        "",
        "## Population",
        "",
        f"- rows={len(rows)}",
        f"- advanced after first hold={counts[ADVANCED]}",
        f"- root failed after first hold={counts[FAILED]}",
        "",
        "## Capture Health",
        "",
        *health,
        "",
        "## Numeric Ranking",
        "",
        "| feature | advanced median | failed median | AUC if higher predicts advance | direction | n |",
        "|---|---:|---:|---:|---|---:|",
    ]
    for row in ranking[:20]:
        lines.append(
            f"| {row['feature']} | {fmt(row['advanced_median'])} | "
            f"{fmt(row['failed_median'])} | {row['auc_advanced_higher']:.3f} | "
            f"{row['direction']} | {row['advanced_n']}+{row['failed_n']} |"
        )
    lines.extend(
        [
            "",
            "## Auction Context Interaction",
            "",
            "Stacking is nearest-five-level owner depth change during the five seconds ending at first-test held confirmation.",
            "",
            "| split | population | context | stacking | advanced | failed | advanced rate |",
            "|---|---|---|---|---:|---:|---:|",
        ]
    )
    for row in interactions:
        if row["split"] == "date":
            continue
        lines.append(
            f"| {row['split']} | {row['population']} | {row['context']} | "
            f"{row['stacking']} | {row['advanced']} | {row['failed']} | "
            f"{row['advanced_rate']:.3f} |"
        )
    lines.extend(
        [
            "",
            "## Interpretation Boundary",
            "",
            "- Predictors stop at the first RailHeld timestamp. Later RailFailed resolution is not used as a feature.",
            "- The structural outcome begins at first hold, so a successor formed before confirmation is not credited.",
            "- Snapshot depth is 1 Hz over the nearest 30 levels per side.",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lineage-csv", type=Path, default=DEFAULT_LINEAGE)
    parser.add_argument("--events", type=Path, default=DEFAULT_EVENTS)
    parser.add_argument("--start-date", default="2026-07-16")
    parser.add_argument("--end-date", default="2026-07-24")
    parser.add_argument("--symbol-dir", default="NQU6")
    parser.add_argument("--out-dir", type=Path)
    parser.add_argument(
        "--all-held",
        action="store_true",
        help="Include held rails without a compatible active directive.",
    )
    args = parser.parse_args()
    out_dir = args.out_dir or (
        DEFAULT_ALL_OUT if args.all_held else DEFAULT_ACTIVE_OUT
    )

    directives = load_directives(args.events)
    rows: list[dict[str, Any]] = []
    for source in read_csv(args.lineage_csv):
        if not args.start_date <= source["date"] <= args.end_date:
            continue
        if source.get("hold_structural_outcome") not in {ADVANCED, FAILED}:
            continue
        if source.get("root_first_test_verdict") != "HELD_FIRST_TEST":
            continue
        rec: dict[str, Any] = dict(source)
        rec["_hold"] = parse_et(source["root_first_test_resolved_et"])
        directive = active_directive(directives, rec["_hold"].astimezone(UTC))
        rec["active_directive_id"] = (
            directive["directive_id"] if directive is not None else ""
        )
        rec["active_directive_side"] = (
            directive["side"] if directive is not None else ""
        )
        rec["compatible_active_directive"] = (
            directive is not None and directive["side"] == source["side"]
        )
        if not args.all_held and not rec["compatible_active_directive"]:
            continue
        rows.append(rec)
    if not rows:
        raise SystemExit("no synthetic first-hold rows matched")

    by_date: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_date[row["date"]].append(row)
    health: list[str] = []
    for day, day_rows in sorted(by_date.items()):
        snapshot_count = enrich_day(day_rows, args.symbol_dir)
        health.append(
            f"- {day}: holds={len(day_rows)} snapshots={snapshot_count}"
        )
        print(health[-1], flush=True)

    ranking = rank_features(rows)
    interactions = interaction_rows(rows)
    out_dir.mkdir(parents=True, exist_ok=True)
    write_csv(out_dir / "synthetic_hold_snapshot.csv", rows)
    write_csv(out_dir / "numeric_ranking.csv", ranking)
    write_csv(out_dir / "auction_context_audit.csv", interactions)
    population_description = (
        "Population is every consumed rail whose first test held, independent of directive/order selection."
        if args.all_held
        else "Population is every consumed rail whose first test held under a compatible active directive, independent of whether EAR entered."
    )
    report = build_report(
        rows,
        ranking,
        interactions,
        health,
        population_description,
    )
    (out_dir / "findings.md").write_text(report, encoding="utf-8")
    print(report, end="")
    print(f"\nwrote {out_dir} rows={len(rows)}")


if __name__ == "__main__":
    main()
