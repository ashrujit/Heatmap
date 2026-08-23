"""Measure LOB stacking/pulling from conversion break to entry decision.

This is a cheap broad-book companion to ``direct_conversion_entry_provision``.
The raw replay measures exact-band event flow; this probe measures the nearest
30 levels per side from MarketRecorder's 1 Hz snapshots. Every feature ends at
the accepted order-submit decision and is labeled by sponsor-lineage outcome,
not by fixed price excursion.
"""

from __future__ import annotations

import argparse
import bisect
import csv
import math
import statistics
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from _paths import OUTPUT_ROOT

from capture_loader import load_capture_window, snapshot_columns  # noqa: E402


NY = ZoneInfo("America/New_York")
TICK_SIZE = 0.25
ADVANCED = "ADVANCED_AFTER_ENTRY"
FAILED = "ROOT_FAILED_AFTER_ENTRY"
DEFAULT_PROVISION = (
    OUTPUT_ROOT
    / "direct_conversion_entry_provision_20260717_20260724"
    / "entry_provision.csv"
)
DEFAULT_LINEAGE = (
    OUTPUT_ROOT / "direct_conversion_sponsor_lineage" / "lineage.csv"
)
DEFAULT_OUT = (
    OUTPUT_ROOT / "direct_conversion_decision_snapshot_20260717_20260724"
)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def parse_et(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%d %H:%M:%S.%f").replace(tzinfo=NY)


def parse_time(day: str, value: str) -> datetime:
    return parse_et(f"{day} {value}")


def as_float(value: Any) -> float | None:
    if value in ("", None):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def safe_ratio(num: float | None, den: float | None) -> float | None:
    if num is None or den is None or abs(den) < 1e-9:
        return None
    return num / den


def set_value(row: dict[str, Any], key: str, value: float | None) -> None:
    row[key] = "" if value is None else round(value, 6)


def price_tick(price: float) -> int:
    return int(round(price / TICK_SIZE))


def side_levels(row: dict[str, Any], side: str) -> list[tuple[int, float]]:
    prefix = "bid" if side == "bid" else "ask"
    ref = int(row["ref_tick"])
    levels: list[tuple[int, float]] = []
    for idx in range(30):
        size = float(row[f"{prefix}_size_{idx}"])
        if not math.isfinite(size) or size <= 0:
            continue
        levels.append((ref + int(row[f"{prefix}_offset_{idx}"]), size))
    return levels


def top_depth(row: dict[str, Any], side: str, count: int) -> float:
    return sum(size for _, size in side_levels(row, side)[:count])


def range_depth(
    row: dict[str, Any],
    side: str,
    lo_tick: int,
    hi_tick: int,
    *,
    require_coverage: bool,
) -> float | None:
    levels = side_levels(row, side)
    if not levels:
        return None
    ticks = [tick for tick, _ in levels]
    if require_coverage and (min(ticks) > lo_tick or max(ticks) < hi_tick):
        return None
    return sum(size for tick, size in levels if lo_tick <= tick <= hi_tick)


def prior_snapshot(
    rows: list[dict[str, Any]],
    times: list[int],
    target_us: int,
) -> tuple[dict[str, Any] | None, float | None]:
    idx = bisect.bisect_right(times, target_us) - 1
    if idx < 0:
        return None, None
    age_s = (target_us - times[idx]) / 1_000_000
    if age_s > 2.5:
        return None, age_s
    return rows[idx], age_s


def snapshot_metrics(
    snapshot: dict[str, Any],
    owner_book: str,
    root_lo: int,
    root_hi: int,
) -> dict[str, float | None]:
    opponent_book = "ask" if owner_book == "bid" else "bid"
    output: dict[str, float | None] = {
        "ref_tick": float(snapshot["ref_tick"]),
    }
    for levels in (5, 10, 20, 30):
        owner = top_depth(snapshot, owner_book, levels)
        opponent = top_depth(snapshot, opponent_book, levels)
        output[f"owner_top{levels}"] = owner
        output[f"opponent_top{levels}"] = opponent
        output[f"owner_share_top{levels}"] = safe_ratio(
            owner, owner + opponent
        )
        output[f"owner_concentration_top{levels}"] = safe_ratio(
            owner, top_depth(snapshot, owner_book, 30)
        )
    output["root_owner_depth"] = range_depth(
        snapshot,
        owner_book,
        root_lo,
        root_hi,
        require_coverage=True,
    )
    output["root_opponent_depth"] = range_depth(
        snapshot,
        opponent_book,
        root_lo,
        root_hi,
        require_coverage=True,
    )
    if owner_book == "bid":
        behind_lo, behind_hi = root_lo - 80, root_lo - 1
        favorable_lo, favorable_hi = root_hi + 1, root_hi + 80
        road_lo, road_hi = root_hi + 1, int(snapshot["ref_tick"])
    else:
        behind_lo, behind_hi = root_hi + 1, root_hi + 80
        favorable_lo, favorable_hi = root_lo - 80, root_lo - 1
        road_lo, road_hi = int(snapshot["ref_tick"]), root_lo - 1
    output["owner_behind_20pts_captured"] = range_depth(
        snapshot,
        owner_book,
        min(behind_lo, behind_hi),
        max(behind_lo, behind_hi),
        require_coverage=False,
    )
    output["owner_favorable_20pts_captured"] = range_depth(
        snapshot,
        owner_book,
        min(favorable_lo, favorable_hi),
        max(favorable_lo, favorable_hi),
        require_coverage=False,
    )
    output["owner_road_depth"] = (
        range_depth(
            snapshot,
            owner_book,
            min(road_lo, road_hi),
            max(road_lo, road_hi),
            require_coverage=True,
        )
        if road_lo <= road_hi
        else None
    )
    output["road_ticks"] = max(0.0, float(abs(road_hi - road_lo)))
    return output


def enrich_day(rows: list[dict[str, Any]], symbol_dir: str) -> int:
    start = min(row["_break"] for row in rows) - timedelta(seconds=3)
    end = max(row["_decision"] for row in rows) + timedelta(seconds=2)
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
        break_us = int(rec["_break"].timestamp() * 1_000_000)
        decision_us = int(rec["_decision"].timestamp() * 1_000_000)
        break_snapshot, break_age = prior_snapshot(snapshot_rows, times, break_us)
        decision_snapshot, decision_age = prior_snapshot(
            snapshot_rows, times, decision_us
        )
        set_value(rec, "break_snapshot_age_s", break_age)
        set_value(rec, "decision_snapshot_age_s", decision_age)
        if break_snapshot is None or decision_snapshot is None:
            continue
        owner_book = "bid" if rec["side"] == "Long" else "ask"
        root_lo = price_tick(float(rec["price_lo"]))
        root_hi = price_tick(float(rec["price_hi"]))
        break_metrics = snapshot_metrics(
            break_snapshot, owner_book, root_lo, root_hi
        )
        decision_metrics = snapshot_metrics(
            decision_snapshot, owner_book, root_lo, root_hi
        )
        for key, value in break_metrics.items():
            set_value(rec, f"break_{key}", value)
        for key, value in decision_metrics.items():
            set_value(rec, f"decision_{key}", value)
        span_s = max(
            (rec["_decision"] - rec["_break"]).total_seconds(),
            0.001,
        )
        for key in decision_metrics:
            if key == "ref_tick":
                continue
            before = break_metrics.get(key)
            after = decision_metrics.get(key)
            if before is None or after is None:
                continue
            delta = after - before
            set_value(rec, f"change_{key}", delta)
            set_value(rec, f"rate_{key}", delta / span_s)
        owner_delta = as_float(rec.get("change_owner_top20"))
        opponent_delta = as_float(rec.get("change_opponent_top20"))
        set_value(
            rec,
            "change_top20_stack_advantage",
            (
                owner_delta - opponent_delta
                if owner_delta is not None and opponent_delta is not None
                else None
            ),
        )
        set_value(
            rec,
            "decision_owner_to_opponent_top20",
            safe_ratio(
                as_float(rec.get("decision_owner_top20")),
                as_float(rec.get("decision_opponent_top20")),
            ),
        )
    return snapshots.height


def auc(positive: list[float], negative: list[float]) -> float:
    wins = 0.0
    for pos in positive:
        for neg in negative:
            wins += 1.0 if pos > neg else 0.5 if pos == neg else 0.0
    return wins / (len(positive) * len(negative))


def numeric_features(rows: list[dict[str, Any]]) -> list[str]:
    prefixes = (
        "break_owner_",
        "break_opponent_",
        "break_root_",
        "break_road_",
        "decision_owner_",
        "decision_opponent_",
        "decision_root_",
        "decision_road_",
        "change_",
        "rate_",
        "pre_",
        "live_",
    )
    excluded = {
        "break_snapshot_age_s",
        "decision_snapshot_age_s",
    }
    return sorted(
        key
        for key in rows[0]
        if key.startswith(prefixes) and key not in excluded
    )


def rank_features(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ranked: list[dict[str, Any]] = []
    for feature in numeric_features(rows):
        positive = [
            value
            for row in rows
            if row["entry_structural_outcome"] == ADVANCED
            and (value := as_float(row.get(feature))) is not None
        ]
        negative = [
            value
            for row in rows
            if row["entry_structural_outcome"] == FAILED
            and (value := as_float(row.get(feature))) is not None
        ]
        if len(positive) < 10 or len(negative) < 10:
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


def categorical_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for feature in (
        "date",
        "role",
        "side",
        "attack_provision_class",
        "pre_5m_20pts_two_sided_fail",
        "pre_10m_50pts_two_sided_fail",
    ):
        groups: dict[str, Counter[str]] = defaultdict(Counter)
        for row in rows:
            outcome = row["entry_structural_outcome"]
            if outcome not in {ADVANCED, FAILED}:
                continue
            groups[str(row.get(feature, "") or "missing")][outcome] += 1
        for value, counts in sorted(groups.items()):
            total = counts[ADVANCED] + counts[FAILED]
            output.append(
                {
                    "feature": feature,
                    "value": value,
                    "advanced": counts[ADVANCED],
                    "failed": counts[FAILED],
                    "advanced_rate": counts[ADVANCED] / total if total else None,
                }
            )
    return output


def stacking_audit_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for split in (
        "overall",
        "side",
        "role",
        "date",
        "pre_5m_20pts_two_sided_fail",
    ):
        groups: dict[tuple[str, str], Counter[str]] = defaultdict(Counter)
        for row in rows:
            outcome = row["entry_structural_outcome"]
            change = as_float(row.get("change_owner_top5"))
            if outcome not in {ADVANCED, FAILED} or change is None:
                continue
            population = "all" if split == "overall" else str(row.get(split, ""))
            state = "stacked" if change > 0 else "flat_or_pulled"
            groups[(population, state)][outcome] += 1
        for (population, state), counts in sorted(groups.items()):
            total = counts[ADVANCED] + counts[FAILED]
            output.append(
                {
                    "split": split,
                    "population": population,
                    "state": state,
                    "advanced": counts[ADVANCED],
                    "failed": counts[FAILED],
                    "advanced_rate": counts[ADVANCED] / total if total else None,
                }
            )
    return output


def auction_context_audit_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for row in rows:
        two_sided = (
            str(row.get("pre_10m_50pts_two_sided_fail", "")).lower() == "true"
        )
        edge_gap = as_float(row.get("pre_10m_50pts_favorable_edge_gap_pts"))
        row["decision_auction_context"] = (
            "inside_two_sided_churn"
            if two_sided and (edge_gap is None or edge_gap <= 0)
            else "clean_or_escaped_field"
        )
        row["near_touch_stacking_state"] = (
            "stacked"
            if (as_float(row.get("change_owner_top5")) or 0.0) > 0
            else "flat_or_pulled"
        )

    for split in ("overall", "side", "role", "date"):
        groups: dict[tuple[str, str, str], Counter[str]] = defaultdict(Counter)
        for row in rows:
            outcome = row["entry_structural_outcome"]
            if outcome not in {ADVANCED, FAILED}:
                continue
            population = "all" if split == "overall" else str(row.get(split, ""))
            key = (
                population,
                str(row["decision_auction_context"]),
                str(row["near_touch_stacking_state"]),
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


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    fields: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for key in row:
            if key.startswith("_") or key in seen:
                continue
            seen.add(key)
            fields.append(key)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def fmt(value: Any) -> str:
    number = as_float(value)
    if number is None:
        return ""
    if abs(number) >= 100:
        return f"{number:.0f}"
    if abs(number) >= 10:
        return f"{number:.1f}"
    return f"{number:.3f}"


def build_report(
    rows: list[dict[str, Any]],
    ranking: list[dict[str, Any]],
    categories: list[dict[str, Any]],
    stacking_audit: list[dict[str, Any]],
    auction_context_audit: list[dict[str, Any]],
    health: list[str],
) -> str:
    counts = Counter(row["entry_structural_outcome"] for row in rows)
    lines = [
        "# Direct-Conversion Decision Snapshot",
        "",
        "Snapshot predictors end at order decision; outcome is sponsor progression versus root failure.",
        "",
        "## Population",
        "",
        f"- rows={len(rows)}",
        f"- advanced after entry={counts[ADVANCED]}",
        f"- root failed after entry={counts[FAILED]}",
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
            "## Near-Touch Stacking Audit",
            "",
            "`stacked` means nearest-five-level owner depth increased from conversion break to decision.",
            "",
            "| split | population | state | advanced | failed | advanced rate |",
            "|---|---|---|---:|---:|---:|",
        ]
    )
    for row in stacking_audit:
        lines.append(
            f"| {row['split']} | {row['population']} | {row['state']} | "
            f"{row['advanced']} | {row['failed']} | {row['advanced_rate']:.3f} |"
        )
    lines.extend(
        [
            "",
            "## Auction Context Interaction",
            "",
            "`inside_two_sided_churn` means both ownership sides failed within 50 points in the prior 10 minutes and the conversion is not beyond that failed field's favorable edge.",
            "",
            "| split | population | context | stacking | advanced | failed | advanced rate |",
            "|---|---|---|---|---:|---:|---:|",
        ]
    )
    for row in auction_context_audit:
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
            "## Population Audit",
            "",
            "| feature | value | advanced | failed | advanced rate |",
            "|---|---|---:|---:|---:|",
        ]
    )
    for row in categories:
        lines.append(
            f"| {row['feature']} | {row['value']} | {row['advanced']} | "
            f"{row['failed']} | {row['advanced_rate']:.3f} |"
        )
    lines.extend(
        [
            "",
            "## Interpretation Boundary",
            "",
            "- Snapshot deltas are net stacking/pulling over the decision interval, not raw quote-event turnover.",
            "- Snapshots are 1 Hz and retain the nearest 30 levels per side. The 20-point root zones are captured portions, not guaranteed full-depth envelopes.",
            "- Ranking is descriptive and campaign-correlated. A weak top AUC is evidence against adding a standalone snapshot heuristic.",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--provision-csv", type=Path, default=DEFAULT_PROVISION)
    parser.add_argument("--lineage-csv", type=Path, default=DEFAULT_LINEAGE)
    parser.add_argument("--symbol-dir", default="NQU6")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()

    lineage_by_key = {
        (row["date"], row["first_entry_et"], row["root_id"]): row
        for row in read_csv(args.lineage_csv)
        if row.get("traded", "").lower() == "true"
    }
    rows: list[dict[str, Any]] = []
    for provision in read_csv(args.provision_csv):
        key = (
            provision["date"],
            provision["decision_et"],
            provision["band_id"],
        )
        lineage = lineage_by_key.get(key)
        if lineage is None:
            continue
        rec: dict[str, Any] = dict(provision)
        rec["session_id"] = lineage["session_id"]
        rec["entry_structural_outcome"] = lineage["entry_structural_outcome"]
        for field, value in lineage.items():
            if field.startswith(("pre_", "live_")):
                rec[field] = value
        rec["_decision"] = parse_et(provision["decision_et"])
        rec["_break"] = parse_time(provision["date"], provision["break_et"])
        rows.append(rec)
    if not rows:
        raise SystemExit("no provision rows matched lineage rows")

    by_date: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_date[row["date"]].append(row)
    health: list[str] = []
    for day, day_rows in sorted(by_date.items()):
        snapshot_count = enrich_day(day_rows, args.symbol_dir)
        health.append(
            f"- {day}: decisions={len(day_rows)} snapshots={snapshot_count}"
        )
        print(health[-1], flush=True)

    ranking = rank_features(rows)
    categories = categorical_rows(rows)
    stacking_audit = stacking_audit_rows(rows)
    auction_context_audit = auction_context_audit_rows(rows)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    write_csv(args.out_dir / "decision_snapshot.csv", rows)
    write_csv(args.out_dir / "numeric_ranking.csv", ranking)
    write_csv(args.out_dir / "categorical_audit.csv", categories)
    write_csv(args.out_dir / "near_touch_stacking_audit.csv", stacking_audit)
    write_csv(args.out_dir / "auction_context_audit.csv", auction_context_audit)
    report = build_report(
        rows,
        ranking,
        categories,
        stacking_audit,
        auction_context_audit,
        health,
    )
    (args.out_dir / "findings.md").write_text(report, encoding="utf-8")
    print(report, end="")
    print(f"\nwrote {args.out_dir} rows={len(rows)}")


if __name__ == "__main__":
    main()
