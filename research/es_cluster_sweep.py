"""Sweep ES ownership-band clustering settings against MarketRecorder snapshots.

Research-only. This reuses LevelLedger's Python ownership replay and reports
band width plus implied sponsor-failure geometry for candidate ES settings.
"""

from __future__ import annotations

import argparse
import csv
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from statistics import mean


ROOT = Path(__file__).resolve().parents[1]
LL_RESEARCH = ROOT / "LevelLedger" / "research"
sys.path.insert(0, str(LL_RESEARCH))

from ownership_bands_probe import OwnershipProbe  # noqa: E402
from replay_levelledger import (  # noqa: E402
    BOOK_LOOKBACK_SEC,
    EVENT_Z_THRESHOLD,
    build_sample,
    load_snapshots,
    parse_ny,
)


@dataclass(frozen=True)
class Setting:
    cluster_ticks: int
    cluster_sec: int


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = int(round((len(ordered) - 1) * pct))
    return ordered[max(0, min(index, len(ordered) - 1))]


def duration_seconds(start: datetime, end: datetime | None, fallback: datetime) -> float:
    return ((end or fallback) - start).total_seconds()


def replay_setting(
    samples,
    window_start: datetime,
    window_end: datetime,
    setting: Setting,
    args,
) -> dict:
    probe = OwnershipProbe(
        event_z=args.event_z,
        cluster_min_events=args.cluster_min_events,
        cluster_ticks=setting.cluster_ticks,
        cluster_sec=setting.cluster_sec,
        cluster_min_score=args.cluster_min_score,
        confirm_ticks=args.confirm_ticks,
        confirm_sec=args.confirm_sec,
        test_buffer_ticks=args.test_buffer_ticks,
        fail_buffer_ticks=args.fail_buffer_ticks,
        fail_confirm_ticks=args.fail_confirm_ticks,
        fail_sec=args.fail_sec,
        hold_confirm_ticks=args.hold_confirm_ticks,
        book_lookback_sec=args.book_lookback_sec,
    )
    for sample in samples:
        probe.on_sample(sample)

    owned = [
        band for band in probe.bands
        if window_start <= band.owned_ts <= window_end
    ]
    widths = [band.max_tick - band.min_tick for band in owned]
    risks = [width + args.fail_confirm_ticks for width in widths]
    durations = [
        duration_seconds(band.owned_ts, band.failed_ts, window_end)
        for band in owned
    ]
    consumed = [band for band in owned if band.source == "supply_consumed" or band.source == "demand_consumed"]
    lean = [band for band in owned if band.source.endswith("_lean")]
    failed = [band for band in owned if band.failed_ts is not None]
    fail_fast = [
        band for band in failed
        if duration_seconds(band.owned_ts, band.failed_ts, window_end) <= 60
    ]
    fail_5m = [
        band for band in failed
        if duration_seconds(band.owned_ts, band.failed_ts, window_end) <= 300
    ]
    transitions = [
        tr for tr in probe.transitions
        if window_start <= tr.ts <= window_end
    ]

    return {
        "cluster_ticks": setting.cluster_ticks,
        "cluster_sec": setting.cluster_sec,
        "owned": len(owned),
        "consumed": len(consumed),
        "lean": len(lean),
        "transitions": len(transitions),
        "avg_width_ticks": mean(widths) if widths else 0.0,
        "p50_width_ticks": percentile(widths, 0.50),
        "p75_width_ticks": percentile(widths, 0.75),
        "p90_width_ticks": percentile(widths, 0.90),
        "p95_width_ticks": percentile(widths, 0.95),
        "max_width_ticks": max(widths) if widths else 0,
        "avg_risk_pts": (mean(risks) if risks else 0.0) * 0.25,
        "p90_risk_pts": percentile(risks, 0.90) * 0.25,
        "p95_risk_pts": percentile(risks, 0.95) * 0.25,
        "max_risk_pts": (max(risks) if risks else 0) * 0.25,
        "wide_gt_12t": sum(1 for width in widths if width > 12),
        "wide_gt_20t": sum(1 for width in widths if width > 20),
        "wide_gt_32t": sum(1 for width in widths if width > 32),
        "failed": len(failed),
        "fail_le_1m": len(fail_fast),
        "fail_le_5m": len(fail_5m),
        "avg_life_sec": mean(durations) if durations else 0.0,
        "p50_life_sec": percentile(durations, 0.50),
    }


def score_row(row: dict, baseline_owned: int, baseline_consumed: int) -> float:
    """Lower is better. Penalize wide-risk tail, loss of signal, and noise."""
    owned_ratio = row["owned"] / baseline_owned if baseline_owned else 0.0
    consumed_ratio = row["consumed"] / baseline_consumed if baseline_consumed else 0.0
    too_sparse = max(0.0, 0.65 - owned_ratio) * 20.0
    consumed_loss = max(0.0, 0.70 - consumed_ratio) * 20.0
    over_fragment = max(0.0, owned_ratio - 1.35) * 8.0
    fast_fail_rate = row["fail_le_1m"] / row["owned"] if row["owned"] else 1.0
    wide_rate = row["wide_gt_20t"] / row["owned"] if row["owned"] else 1.0
    return (
        row["p90_risk_pts"]
        + row["p95_risk_pts"] * 0.50
        + row["max_risk_pts"] * 0.10
        + wide_rate * 10.0
        + fast_fail_rate * 4.0
        + too_sparse
        + consumed_loss
        + over_fragment
    )


def format_row(row: dict) -> str:
    return (
        f"{row['cluster_ticks']:>2}t/{row['cluster_sec']:>2}s "
        f"owned={row['owned']:>4} consumed={row['consumed']:>3} "
        f"avgW={row['avg_width_ticks']:>5.1f}t "
        f"p90W={row['p90_width_ticks']:>4.0f}t "
        f"p95W={row['p95_width_ticks']:>4.0f}t "
        f"maxW={row['max_width_ticks']:>4.0f}t "
        f"p90Risk={row['p90_risk_pts']:>5.2f} "
        f"p95Risk={row['p95_risk_pts']:>5.2f} "
        f"wide>20t={row['wide_gt_20t']:>3} "
        f"fail<=1m={row['fail_le_1m']:>3} "
        f"score={row['score']:>6.2f}"
    )


def aggregate(rows: list[dict]) -> list[dict]:
    grouped: dict[tuple[int, int], list[dict]] = {}
    for row in rows:
        grouped.setdefault((row["cluster_ticks"], row["cluster_sec"]), []).append(row)

    result = []
    for (cluster_ticks, cluster_sec), parts in grouped.items():
        owned = sum(p["owned"] for p in parts)
        consumed = sum(p["consumed"] for p in parts)
        width_weight = owned or 1
        agg = {
            "cluster_ticks": cluster_ticks,
            "cluster_sec": cluster_sec,
            "days": len(parts),
            "owned": owned,
            "consumed": consumed,
            "lean": sum(p["lean"] for p in parts),
            "transitions": sum(p["transitions"] for p in parts),
            "avg_width_ticks": sum(p["avg_width_ticks"] * p["owned"] for p in parts) / width_weight,
            "p50_width_ticks": mean(p["p50_width_ticks"] for p in parts),
            "p75_width_ticks": mean(p["p75_width_ticks"] for p in parts),
            "p90_width_ticks": max(p["p90_width_ticks"] for p in parts),
            "p95_width_ticks": max(p["p95_width_ticks"] for p in parts),
            "max_width_ticks": max(p["max_width_ticks"] for p in parts),
            "avg_risk_pts": sum(p["avg_risk_pts"] * p["owned"] for p in parts) / width_weight,
            "p90_risk_pts": max(p["p90_risk_pts"] for p in parts),
            "p95_risk_pts": max(p["p95_risk_pts"] for p in parts),
            "max_risk_pts": max(p["max_risk_pts"] for p in parts),
            "wide_gt_12t": sum(p["wide_gt_12t"] for p in parts),
            "wide_gt_20t": sum(p["wide_gt_20t"] for p in parts),
            "wide_gt_32t": sum(p["wide_gt_32t"] for p in parts),
            "failed": sum(p["failed"] for p in parts),
            "fail_le_1m": sum(p["fail_le_1m"] for p in parts),
            "fail_le_5m": sum(p["fail_le_5m"] for p in parts),
            "avg_life_sec": mean(p["avg_life_sec"] for p in parts),
            "p50_life_sec": mean(p["p50_life_sec"] for p in parts),
        }
        result.append(agg)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dates", nargs="+", required=True)
    parser.add_argument("--symbol-dir", default="ESU6")
    parser.add_argument("--window", default="09:30-16:00")
    parser.add_argument("--warmup-min", type=int, default=90)
    parser.add_argument("--cluster-ticks-grid", default="2,3,4,5,6,8,10")
    parser.add_argument("--cluster-sec-grid", default="30,45,60,90")
    parser.add_argument("--event-z", type=float, default=EVENT_Z_THRESHOLD)
    parser.add_argument("--book-lookback-sec", type=int, default=BOOK_LOOKBACK_SEC)
    parser.add_argument("--cluster-min-events", type=int, default=3)
    parser.add_argument("--cluster-min-score", type=float, default=8.0)
    parser.add_argument("--confirm-ticks", type=int, default=8)
    parser.add_argument("--confirm-sec", type=int, default=10)
    parser.add_argument("--test-buffer-ticks", type=int, default=4)
    parser.add_argument("--fail-buffer-ticks", type=int, default=2)
    parser.add_argument("--fail-confirm-ticks", type=int, default=24)
    parser.add_argument("--fail-sec", type=int, default=20)
    parser.add_argument("--hold-confirm-ticks", type=int, default=10)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()

    ticks_grid = [int(x) for x in args.cluster_ticks_grid.split(",") if x.strip()]
    sec_grid = [int(x) for x in args.cluster_sec_grid.split(",") if x.strip()]
    settings = [Setting(ticks, sec) for ticks in ticks_grid for sec in sec_grid]

    all_rows: list[dict] = []
    for date in args.dates:
        start_s, end_s = args.window.split("-", 1)
        window_start = parse_ny(date, start_s)
        window_end = parse_ny(date, end_s)
        replay_start = window_start - timedelta(minutes=args.warmup_min)
        snap = load_snapshots(args.symbol_dir, replay_start, window_end)
        samples = [build_sample(row) for row in snap.iter_rows(named=True)]
        print(
            f"Loaded {args.symbol_dir} {date} {args.window}: "
            f"{len(samples):,} snapshots"
        )
        for setting in settings:
            row = replay_setting(samples, window_start, window_end, setting, args)
            row["date"] = date
            all_rows.append(row)

    agg_rows = aggregate(all_rows)
    baseline = next(
        row for row in agg_rows
        if row["cluster_ticks"] == 10 and row["cluster_sec"] == 90
    )
    for row in agg_rows:
        row["score"] = score_row(row, baseline["owned"], baseline["consumed"])
        row["owned_ratio"] = row["owned"] / baseline["owned"] if baseline["owned"] else 0.0
        row["consumed_ratio"] = row["consumed"] / baseline["consumed"] if baseline["consumed"] else 0.0

    print("\nAggregate results, sorted by score:")
    for row in sorted(agg_rows, key=lambda item: item["score"]):
        print(format_row(row))

    print("\nBaseline:")
    print(format_row(next(row for row in agg_rows if row["cluster_ticks"] == 10 and row["cluster_sec"] == 90)))

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        fieldnames = sorted(set().union(*(row.keys() for row in all_rows + agg_rows)))
        with args.out.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=fieldnames)
            writer.writeheader()
            for row in all_rows:
                writer.writerow(row)
            for row in agg_rows:
                out = dict(row)
                out["date"] = "AGG"
                writer.writerow(out)
        print(f"\nWrote {args.out}")


if __name__ == "__main__":
    main()
