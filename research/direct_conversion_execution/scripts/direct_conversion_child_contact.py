"""Test child-contact book state against sponsor-failure propagation.

Population: traded direct-consumption roots that advanced to a favorable child
and whose child later failed. The outcome is structural:

* contained/repaired: another favorable sponsor was already live, or same-side
  sponsorship re-established before the consumed root failed;
* propagated: the consumed root failed before same-side re-establishment.

Features stop at child failure. No fixed post-event price horizon is used.
Snapshot features are a broad first pass; MarketRecorder snapshots contain the
nearest 30 levels per side, so a missing distant parent band is not zero depth.
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

import polars as pl

from _paths import OUTPUT_ROOT

from capture_loader import load_capture_window, snapshot_columns, tick_columns  # noqa: E402


NY = ZoneInfo("America/New_York")
TICK_SIZE = 0.25
POSITIVE = {
    "CONTAINED_BY_EXISTING_FAVORABLE_SPONSOR",
    "REESTABLISHED_BEFORE_ROOT_FAILURE",
}
NEGATIVE = "ROOT_FAILED_BEFORE_REESTABLISHMENT"
DEFAULT_LINEAGE = (
    OUTPUT_ROOT / "direct_conversion_sponsor_lineage" / "lineage.csv"
)
DEFAULT_OUT = (
    OUTPUT_ROOT / "direct_conversion_child_contact_20260716_20260724"
)

FORMATION_OFFSETS = (0, 2, 5, 10)
PREFAIL_OFFSETS = (-10, -5, -2, -1, 0)
TAPE_WINDOWS = (2, 5, 10)


def parse_et(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%d %H:%M:%S.%f").replace(tzinfo=NY)


def as_float(value: Any) -> float | None:
    if value in ("", None):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def price_tick(value: float) -> int:
    return int(round(value / TICK_SIZE))


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def snapshot_range_depth(
    row: dict[str, Any],
    lo_tick: int,
    hi_tick: int,
    book_side: str,
) -> float:
    prefix = "bid" if book_side == "bid" else "ask"
    ref = int(row["ref_tick"])
    total = 0.0
    for idx in range(30):
        size = float(row[f"{prefix}_size_{idx}"])
        if not math.isfinite(size) or size <= 0:
            continue
        tick = ref + int(row[f"{prefix}_offset_{idx}"])
        if lo_tick <= tick <= hi_tick:
            total += size
    return total


def snapshot_range_depth_if_covered(
    row: dict[str, Any],
    lo_tick: int,
    hi_tick: int,
    book_side: str,
) -> float | None:
    prefix = "bid" if book_side == "bid" else "ask"
    ref = int(row["ref_tick"])
    captured_ticks = [
        ref + int(row[f"{prefix}_offset_{idx}"])
        for idx in range(30)
        if math.isfinite(size := float(row[f"{prefix}_size_{idx}"])) and size > 0
    ]
    if not captured_ticks or min(captured_ticks) > lo_tick or max(captured_ticks) < hi_tick:
        return None
    return snapshot_range_depth(row, lo_tick, hi_tick, book_side)


def snapshot_top_depth(row: dict[str, Any], book_side: str, levels: int = 20) -> float:
    prefix = "bid" if book_side == "bid" else "ask"
    return sum(
        size
        for idx in range(levels)
        if math.isfinite(size := float(row[f"{prefix}_size_{idx}"])) and size > 0
    )


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


def tick_flow(
    times: list[int],
    prices: list[float],
    sizes: list[float],
    signs: list[int],
    start_us: int,
    end_us: int,
    lo_tick: int,
    hi_tick: int,
    owner_sign: int,
) -> tuple[float, float, int]:
    lo = bisect.bisect_left(times, start_us)
    hi = bisect.bisect_right(times, end_us)
    hostile = 0.0
    aligned = 0.0
    trades = 0
    for idx in range(lo, hi):
        tick = price_tick(float(prices[idx]))
        if not lo_tick <= tick <= hi_tick:
            continue
        trades += 1
        size = float(sizes[idx])
        sign = int(signs[idx])
        if sign == -owner_sign:
            hostile += size
        elif sign == owner_sign:
            aligned += size
    return hostile, aligned, trades


def safe_ratio(num: float | None, den: float | None) -> float | None:
    if num is None or den is None or abs(den) < 1e-9:
        return None
    return num / den


def set_value(row: dict[str, Any], key: str, value: float | None) -> None:
    row[key] = "" if value is None else round(value, 6)


def enrich_day(
    rows: list[dict[str, Any]],
    symbol_dir: str,
) -> tuple[int, int]:
    start = min(row["_child_owned"] for row in rows) - timedelta(seconds=15)
    end = max(row["_child_failed"] for row in rows) + timedelta(seconds=3)
    snapshots = load_capture_window(
        "snapshots",
        symbol_dir,
        start,
        end,
        snapshot_columns(30),
        inclusive_end=True,
    )
    ticks = load_capture_window(
        "ticks",
        symbol_dir,
        start,
        end,
        tick_columns(),
        inclusive_end=True,
    )
    snapshot_rows = snapshots.sort("timestamp_us").to_dicts()
    snapshot_times = [int(row["timestamp_us"]) for row in snapshot_rows]
    ticks = ticks.sort("timestamp_us")
    tick_times = [int(value) for value in ticks["timestamp_us"].to_list()]
    tick_prices = [float(value) for value in ticks["price"].to_list()]
    tick_sizes = [float(value) for value in ticks["size"].to_list()]
    tick_signs = [int(value) for value in ticks["aggressor_sign"].to_list()]

    for rec in rows:
        owner_book = "bid" if rec["side"] == "Demand" else "ask"
        opposite_book = "ask" if owner_book == "bid" else "bid"
        owner_sign = 1 if owner_book == "bid" else -1
        child_lo = price_tick(float(rec["post_entry_successor_lo"]))
        child_hi = price_tick(float(rec["post_entry_successor_hi"]))
        root_lo = price_tick(float(rec["root_lo"]))
        root_hi = price_tick(float(rec["root_hi"]))
        child_owned_us = int(rec["_child_owned"].timestamp() * 1_000_000)
        child_failed_us = int(rec["_child_failed"].timestamp() * 1_000_000)

        for offset in FORMATION_OFFSETS:
            label = f"formation_{offset}s"
            snapshot, age = prior_snapshot(
                snapshot_rows,
                snapshot_times,
                child_owned_us + offset * 1_000_000,
            )
            if snapshot is None:
                continue
            set_value(
                rec,
                f"{label}_owner_depth",
                snapshot_range_depth(snapshot, child_lo, child_hi, owner_book),
            )
            set_value(
                rec,
                f"{label}_opposite_depth",
                snapshot_range_depth(snapshot, child_lo, child_hi, opposite_book),
            )
            set_value(rec, f"{label}_snapshot_age_s", age)

        for offset in PREFAIL_OFFSETS:
            suffix = f"m{abs(offset)}s" if offset < 0 else "0s"
            label = f"prefail_{suffix}"
            snapshot, age = prior_snapshot(
                snapshot_rows,
                snapshot_times,
                child_failed_us + offset * 1_000_000,
            )
            if snapshot is None:
                continue
            child_owner = snapshot_range_depth(
                snapshot, child_lo, child_hi, owner_book
            )
            child_opposite = snapshot_range_depth(
                snapshot, child_lo, child_hi, opposite_book
            )
            set_value(rec, f"{label}_owner_depth", child_owner)
            set_value(rec, f"{label}_opposite_depth", child_opposite)
            set_value(
                rec,
                f"{label}_root_owner_depth",
                snapshot_range_depth_if_covered(
                    snapshot, root_lo, root_hi, owner_book
                ),
            )
            top_owner = snapshot_top_depth(snapshot, owner_book)
            top_opposite = snapshot_top_depth(snapshot, opposite_book)
            set_value(rec, f"{label}_top20_owner", top_owner)
            set_value(rec, f"{label}_top20_opposite", top_opposite)
            set_value(
                rec,
                f"{label}_top20_owner_share",
                safe_ratio(top_owner, top_owner + top_opposite),
            )
            set_value(rec, f"{label}_snapshot_age_s", age)

        for window in TAPE_WINDOWS:
            hostile, aligned, trades = tick_flow(
                tick_times,
                tick_prices,
                tick_sizes,
                tick_signs,
                child_owned_us,
                child_owned_us + window * 1_000_000,
                child_lo,
                child_hi,
                owner_sign,
            )
            set_value(rec, f"formation_hostile_{window}s", hostile)
            set_value(rec, f"formation_aligned_{window}s", aligned)
            rec[f"formation_trades_{window}s"] = trades
            hostile, aligned, trades = tick_flow(
                tick_times,
                tick_prices,
                tick_sizes,
                tick_signs,
                child_failed_us - window * 1_000_000,
                child_failed_us,
                child_lo,
                child_hi,
                owner_sign,
            )
            set_value(rec, f"prefail_hostile_{window}s", hostile)
            set_value(rec, f"prefail_aligned_{window}s", aligned)
            rec[f"prefail_trades_{window}s"] = trades

        formation_start = as_float(rec.get("formation_0s_owner_depth"))
        formation_5 = as_float(rec.get("formation_5s_owner_depth"))
        prefail_5 = as_float(rec.get("prefail_m5s_owner_depth"))
        hostile_5 = as_float(rec.get("prefail_hostile_5s"))
        set_value(
            rec,
            "formation_owner_retention_5s",
            safe_ratio(formation_5, formation_start),
        )
        set_value(
            rec,
            "prefail_hostile_to_owner_depth_5s",
            safe_ratio(hostile_5, max(prefail_5 or 0.0, 1.0)),
        )
    return snapshots.height, ticks.height


def auc(positive: list[float], negative: list[float]) -> float:
    wins = 0.0
    for pos in positive:
        for neg in negative:
            wins += 1.0 if pos > neg else 0.5 if pos == neg else 0.0
    return wins / (len(positive) * len(negative))


def feature_names(rows: list[dict[str, Any]]) -> list[str]:
    prefixes = (
        "formation_",
        "prefail_",
        "entry_to_successor_s",
        "post_entry_successor_distance_pts",
        "post_entry_successor_width_pts",
        "successor_distance_to_",
        "child_lifetime_s",
        "successor_failure_to_",
        "root_width_pts",
    )
    excluded = {
        "formation_0s_snapshot_age_s",
        "formation_2s_snapshot_age_s",
        "formation_5s_snapshot_age_s",
        "formation_10s_snapshot_age_s",
        "prefail_m10s_snapshot_age_s",
        "prefail_m5s_snapshot_age_s",
        "prefail_m2s_snapshot_age_s",
        "prefail_m1s_snapshot_age_s",
        "prefail_0s_snapshot_age_s",
        "successor_failure_to_root_failure_s",
        "successor_failure_to_reestablishment_s",
    }
    return sorted(
        key
        for key in rows[0]
        if key.startswith(prefixes) and key not in excluded
    )


def rank_features(
    rows: list[dict[str, Any]],
    positive_labels: set[str],
) -> list[dict[str, Any]]:
    ranked: list[dict[str, Any]] = []
    for feature in feature_names(rows):
        positive = [
            value
            for row in rows
            if row["successor_failure_propagation"] in positive_labels
            and (value := as_float(row.get(feature))) is not None
        ]
        negative = [
            value
            for row in rows
            if row["successor_failure_propagation"] == NEGATIVE
            and (value := as_float(row.get(feature))) is not None
        ]
        if len(positive) < 3 or len(negative) < 3:
            continue
        rank_auc = auc(positive, negative)
        ranked.append(
            {
                "feature": feature,
                "positive_n": len(positive),
                "negative_n": len(negative),
                "positive_median": statistics.median(positive),
                "negative_median": statistics.median(negative),
                "auc_positive_higher": rank_auc,
                "separation": abs(rank_auc - 0.5),
                "direction": "higher" if rank_auc >= 0.5 else "lower",
            }
        )
    return sorted(ranked, key=lambda row: row["separation"], reverse=True)


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


def distance_bucket(value: float) -> str:
    if value <= 2:
        return "<=2 child widths"
    if value <= 5:
        return "2-5 child widths"
    if value <= 10:
        return "5-10 child widths"
    return ">10 child widths"


def recovery_bucket_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, Counter[str]] = defaultdict(Counter)
    for row in rows:
        label = row["successor_failure_propagation"]
        if label == "CONTAINED_BY_EXISTING_FAVORABLE_SPONSOR":
            continue
        value = as_float(row.get("successor_distance_to_child_width"))
        if value is None:
            continue
        bucket = distance_bucket(value)
        grouped[bucket]["rows"] += 1
        grouped[bucket]["recovered"] += label == "REESTABLISHED_BEFORE_ROOT_FAILURE"
        grouped[bucket]["propagated"] += label == NEGATIVE
    order = (
        "<=2 child widths",
        "2-5 child widths",
        "5-10 child widths",
        ">10 child widths",
    )
    return [
        {
            "bucket": bucket,
            "rows": grouped[bucket]["rows"],
            "recovered": grouped[bucket]["recovered"],
            "propagated": grouped[bucket]["propagated"],
            "recovery_rate": safe_ratio(
                grouped[bucket]["recovered"], grouped[bucket]["rows"]
            ),
        }
        for bucket in order
        if grouped[bucket]["rows"]
    ]


def build_report(
    rows: list[dict[str, Any]],
    survival_ranking: list[dict[str, Any]],
    recovery_ranking: list[dict[str, Any]],
    recovery_buckets: list[dict[str, Any]],
    health: list[str],
) -> str:
    counts = Counter(row["successor_failure_propagation"] for row in rows)
    lines = [
        "# Direct-Conversion Child Contact",
        "",
        "Outcome is whether child failure was contained/repaired before the consumed root failed.",
        "",
        "## Population",
        "",
        f"- rows={len(rows)}",
        f"- contained by existing favorable sponsor={counts['CONTAINED_BY_EXISTING_FAVORABLE_SPONSOR']}",
        f"- re-established before root failure={counts['REESTABLISHED_BEFORE_ROOT_FAILURE']}",
        f"- root failed before re-establishment={counts[NEGATIVE]}",
        "",
        "## Capture Health",
        "",
        *health,
        "",
        "## All Survival",
        "",
        "Positive combines immediate containment and later re-establishment.",
        "",
        "| feature | survived median | propagated median | AUC if higher predicts survival | direction | n |",
        "|---|---:|---:|---:|---|---:|",
    ]
    for row in survival_ranking[:15]:
        lines.append(
            f"| {row['feature']} | {fmt(row['positive_median'])} | "
            f"{fmt(row['negative_median'])} | {row['auc_positive_higher']:.3f} | "
            f"{row['direction']} | {row['positive_n']}+{row['negative_n']} |"
        )
    lines.extend(
        [
            "",
            "## Recovery Without Existing Containment",
            "",
            "Immediate-contained rows are excluded. Positive means a new same-side sponsor re-established before root failure.",
            "",
            "| feature | re-established median | propagated median | AUC if higher predicts recovery | direction | n |",
            "|---|---:|---:|---:|---|---:|",
        ]
    )
    for row in recovery_ranking[:15]:
        lines.append(
            f"| {row['feature']} | {fmt(row['positive_median'])} | "
            f"{fmt(row['negative_median'])} | {row['auc_positive_higher']:.3f} | "
            f"{row['direction']} | {row['positive_n']}+{row['negative_n']} |"
        )
    lines.extend(
        [
            "",
            "## Spatial Discovery Audit",
            "",
            "Immediate-contained rows are excluded. Distance is the gap from consumed-root edge to child edge divided by child width.",
            "",
            "| root-child separation | rows | re-established | propagated | recovery rate |",
            "|---|---:|---:|---:|---:|",
        ]
    )
    for row in recovery_buckets:
        lines.append(
            f"| {row['bucket']} | {row['rows']} | {row['recovered']} | "
            f"{row['propagated']} | {row['recovery_rate']:.3f} |"
        )
    lines.extend(
        [
            "",
            "## Interpretation Boundary",
            "",
            "- All predictors stop at child failure; no fixed post-failure price outcome is used.",
            "- Snapshot depth is sampled at 1 Hz and covers 30 nearest levels per side. Missing distant root depth is unknown, not zero.",
            "- This is descriptive ranking. Side, date, campaign, and repeated-directive clustering still need audits before any implementation threshold.",
            "- The two-child-width boundary was selected after inspecting this sample. Its repeat across dates and sides is hypothesis support, not out-of-sample validation.",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lineage-csv", type=Path, default=DEFAULT_LINEAGE)
    parser.add_argument("--start-date", default="2026-07-16")
    parser.add_argument("--end-date", default="2026-07-24")
    parser.add_argument("--symbol-dir", default="NQU6")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()

    rows: list[dict[str, Any]] = []
    for row in read_csv(args.lineage_csv):
        if not args.start_date <= row["date"] <= args.end_date:
            continue
        if row.get("successor_failure_propagation") not in POSITIVE | {NEGATIVE}:
            continue
        if not row.get("post_entry_successor_failed_et"):
            continue
        rec: dict[str, Any] = dict(row)
        rec["_child_owned"] = parse_et(row["post_entry_successor_owned_et"])
        rec["_child_failed"] = parse_et(row["post_entry_successor_failed_et"])
        distance = as_float(row.get("post_entry_successor_distance_pts"))
        root_width = as_float(row.get("root_width_pts"))
        child_lo = as_float(row.get("post_entry_successor_lo"))
        child_hi = as_float(row.get("post_entry_successor_hi"))
        child_width = (
            child_hi - child_lo
            if child_lo is not None and child_hi is not None
            else None
        )
        set_value(rec, "post_entry_successor_width_pts", child_width)
        set_value(
            rec,
            "successor_distance_to_root_width",
            safe_ratio(distance, max(root_width or 0.0, TICK_SIZE)),
        )
        set_value(
            rec,
            "successor_distance_to_child_width",
            safe_ratio(distance, max(child_width or 0.0, TICK_SIZE)),
        )
        set_value(
            rec,
            "child_lifetime_s",
            (rec["_child_failed"] - rec["_child_owned"]).total_seconds(),
        )
        rows.append(rec)
    if not rows:
        raise SystemExit("no failed child rows matched")

    by_date: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_date[row["date"]].append(row)
    health: list[str] = []
    for day, day_rows in sorted(by_date.items()):
        snapshot_count, tick_count = enrich_day(day_rows, args.symbol_dir)
        health.append(
            f"- {day}: rows={len(day_rows)} snapshots={snapshot_count} ticks={tick_count}"
        )
        print(health[-1], flush=True)

    survival_ranking = rank_features(rows, POSITIVE)
    recovery_ranking = rank_features(rows, {"REESTABLISHED_BEFORE_ROOT_FAILURE"})
    recovery_buckets = recovery_bucket_rows(rows)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    write_csv(args.out_dir / "child_contact.csv", rows)
    write_csv(args.out_dir / "survival_numeric_ranking.csv", survival_ranking)
    write_csv(args.out_dir / "recovery_numeric_ranking.csv", recovery_ranking)
    write_csv(args.out_dir / "recovery_distance_buckets.csv", recovery_buckets)
    report = build_report(
        rows,
        survival_ranking,
        recovery_ranking,
        recovery_buckets,
        health,
    )
    (args.out_dir / "findings.md").write_text(report, encoding="utf-8")
    print(report, end="")
    print(f"\nwrote {args.out_dir} rows={len(rows)}")


if __name__ == "__main__":
    main()
