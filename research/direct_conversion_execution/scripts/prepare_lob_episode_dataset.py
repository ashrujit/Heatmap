"""Prepare LL-derived episode candidates for LOB response research.

This does not test a new signal. It turns the existing synthetic ownership
replay into a reproducible fixture table so later book-evolution metrics can be
reviewed against curated auction windows instead of whole-day noise.
"""

from __future__ import annotations

import argparse
import bisect
import csv
import json
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from _paths import OUTPUT_ROOT, REPO_ROOT as ROOT

LL_RESEARCH = ROOT / "LevelLedger" / "research"
sys.path.insert(0, str(LL_RESEARCH))

from ownership_bands_probe import OwnershipProbe  # noqa: E402
from replay_levelledger import (  # noqa: E402
    BOOK_LOOKBACK_SEC,
    EVENT_Z_THRESHOLD,
    NY,
    TICK_SIZE,
    build_sample,
    load_snapshots,
    parse_ny,
    snapshot_timing_summary,
)


@dataclass
class ChurnCluster:
    start_ts: datetime
    end_ts: datetime
    min_tick: int
    max_tick: int
    demand_fails: int = 0
    supply_fails: int = 0
    score: float = 0.0

    @property
    def total_fails(self) -> int:
        return self.demand_fails + self.supply_fails


class PriceIndex:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        ordered = sorted(rows, key=lambda row: int(row["timestamp_us"]))
        self.times = [int(row["timestamp_us"]) for row in ordered]
        self.ticks = [int(row["ref_tick"]) for row in ordered]

    def tick_at(self, ts: datetime) -> int | None:
        if not self.times:
            return None
        target = int(ts.timestamp() * 1_000_000)
        idx = bisect.bisect_left(self.times, target)
        if idx >= len(self.times):
            idx = len(self.times) - 1
        return self.ticks[idx]

    def aligned_move_points(self, ts: datetime, side: str, horizon_sec: int) -> float | None:
        start = self.tick_at(ts)
        end = self.tick_at(ts + timedelta(seconds=horizon_sec))
        if start is None or end is None:
            return None
        sign = 1 if side == "demand" else -1
        return (end - start) * sign * TICK_SIZE


def et(ts: datetime | None) -> str:
    if ts is None:
        return ""
    return ts.astimezone(NY).strftime("%Y-%m-%d %H:%M:%S")


def price(tick: int | None) -> float | None:
    return None if tick is None else tick * TICK_SIZE


def fmt_price(tick: int | None) -> str:
    value = price(tick)
    return "" if value is None else f"{value:.2f}"


def side_label(side: str | None) -> str:
    if side == "demand":
        return "DEMAND"
    if side == "supply":
        return "SUPPLY"
    return "TWO_SIDED"


def seconds_label(value: float | int | None) -> str:
    if value is None:
        return ""
    return str(int(round(float(value))))


def points_label(value: float | None) -> str:
    return "" if value is None else f"{value:.2f}"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dates", required=True, help="Comma-separated RTH dates")
    parser.add_argument("--symbol-dir", default="NQU6")
    parser.add_argument("--window", default="09:30-16:00")
    parser.add_argument("--warmup-min", type=int, default=90)
    parser.add_argument(
        "--out-dir",
        default=str(OUTPUT_ROOT / "lob_episode_prep_20260723_20260724"),
    )
    parser.add_argument("--event-z", type=float, default=EVENT_Z_THRESHOLD)
    parser.add_argument("--book-lookback-sec", type=int, default=BOOK_LOOKBACK_SEC)
    parser.add_argument("--cluster-min-events", type=int, default=3)
    parser.add_argument("--cluster-ticks", type=int, default=10)
    parser.add_argument("--cluster-sec", type=int, default=90)
    parser.add_argument("--cluster-min-score", type=float, default=8.0)
    parser.add_argument("--confirm-ticks", type=int, default=8)
    parser.add_argument("--confirm-sec", type=int, default=10)
    parser.add_argument("--test-buffer-ticks", type=int, default=4)
    parser.add_argument("--fail-buffer-ticks", type=int, default=2)
    parser.add_argument("--fail-confirm-ticks", type=int, default=8)
    parser.add_argument("--fail-sec", type=int, default=10)
    parser.add_argument("--hold-confirm-ticks", type=int, default=10)
    parser.add_argument("--gap-threshold-sec", type=float, default=5.0)
    parser.add_argument("--contested-sec", type=int, default=20 * 60)
    parser.add_argument("--contested-proximity-ticks", type=int, default=80)
    parser.add_argument("--contested-span-ticks", type=int, default=240)
    parser.add_argument("--contested-min-fails", type=int, default=4)
    parser.add_argument("--context-points", type=float, default=40.0)
    parser.add_argument("--survivor-min-sec", type=int, default=10 * 60)
    parser.add_argument("--repair-lookahead-min", type=int, default=30)
    parser.add_argument("--repair-min-sec", type=int, default=5 * 60)
    parser.add_argument("--top-survivors-per-day", type=int, default=18)
    return parser.parse_args()


def make_probe(args: argparse.Namespace, date: str) -> tuple[OwnershipProbe, list[dict[str, Any]], dict[str, Any]]:
    start_s, end_s = args.window.split("-", 1)
    window_start = parse_ny(date, start_s)
    window_end = parse_ny(date, end_s)
    replay_start = window_start - timedelta(minutes=args.warmup_min)
    snapshots = load_snapshots(args.symbol_dir, replay_start, window_end)
    first_snap, last_snap, duplicate_count, gaps = snapshot_timing_summary(
        snapshots,
        args.gap_threshold_sec,
    )

    probe = OwnershipProbe(
        event_z=args.event_z,
        cluster_min_events=args.cluster_min_events,
        cluster_ticks=args.cluster_ticks,
        cluster_sec=args.cluster_sec,
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
    rows = list(snapshots.iter_rows(named=True))
    for row in rows:
        probe.on_sample(build_sample(row))

    meta = {
        "date": date,
        "window_start": window_start,
        "window_end": window_end,
        "replay_start": replay_start,
        "rows": snapshots.height,
        "first_snapshot_et": et(first_snap),
        "last_snapshot_et": et(last_snap),
        "duplicate_timestamps": duplicate_count,
        "gap_count": len(gaps),
    }
    return probe, rows, meta


def build_churn_clusters(args: argparse.Namespace, probe: OwnershipProbe, start: datetime, end: datetime) -> list[ChurnCluster]:
    fails = [
        tr
        for tr in probe.transitions
        if start <= tr.ts <= end and tr.action == "FAIL"
    ]
    clusters: list[ChurnCluster] = []
    for tr in fails:
        match: ChurnCluster | None = None
        for cluster in clusters:
            if (tr.ts - cluster.end_ts).total_seconds() > args.contested_sec:
                continue
            if tr.max_tick < cluster.min_tick - args.contested_proximity_ticks:
                continue
            if tr.min_tick > cluster.max_tick + args.contested_proximity_ticks:
                continue
            span = max(cluster.max_tick, tr.max_tick) - min(cluster.min_tick, tr.min_tick)
            if span > args.contested_span_ticks:
                continue
            match = cluster
            break

        if match is None:
            match = ChurnCluster(tr.ts, tr.ts, tr.min_tick, tr.max_tick)
            clusters.append(match)
        else:
            match.end_ts = tr.ts
            match.min_tick = min(match.min_tick, tr.min_tick)
            match.max_tick = max(match.max_tick, tr.max_tick)

        if tr.side == "demand":
            match.demand_fails += 1
        else:
            match.supply_fails += 1
        match.score += tr.score

    return [
        cluster
        for cluster in clusters
        if cluster.demand_fails > 0
        and cluster.supply_fails > 0
        and cluster.total_fails >= args.contested_min_fails
    ]


def band_life_sec(band: Any, window_end: datetime) -> float:
    return ((band.failed_ts or window_end) - band.owned_ts).total_seconds()


def band_status(band: Any) -> str:
    return "ACTIVE_AT_WINDOW_END" if band.failed_ts is None else "FAILED"


def overlaps_cluster(
    band_min: int,
    band_max: int,
    ts: datetime,
    cluster: ChurnCluster,
    pad_ticks: int,
) -> bool:
    if ts < cluster.start_ts - timedelta(minutes=10):
        return False
    if ts > cluster.end_ts + timedelta(minutes=30):
        return False
    return not (
        band_max < cluster.min_tick - pad_ticks
        or band_min > cluster.max_tick + pad_ticks
    )


def cluster_id(date: str, index: int) -> str:
    return f"{date.replace('-', '')}_churn_{index:02d}"


def band_id(date: str, prefix: str, band: Any) -> str:
    return f"{date.replace('-', '')}_{prefix}_band{band.id}"


def base_row(args: argparse.Namespace, date: str, bucket: str, episode_id: str) -> dict[str, str]:
    return {
        "bucket": bucket,
        "episode_id": episode_id,
        "date": date,
        "symbol_dir": args.symbol_dir,
        "selection_status": "candidate",
        "start_et": "",
        "end_et": "",
        "focus_et": "",
        "side": "",
        "source": "",
        "band_id": "",
        "band_state": "",
        "min_price": "",
        "max_price": "",
        "context_min_price": "",
        "context_max_price": "",
        "life_sec": "",
        "score": "",
        "event_count": "",
        "max_abs_z": "",
        "demand_fails": "",
        "supply_fails": "",
        "claim_demand": "",
        "claim_supply": "",
        "consumed_demand": "",
        "consumed_supply": "",
        "fail_demand": "",
        "fail_supply": "",
        "move_5m_aligned_pts": "",
        "move_10m_aligned_pts": "",
        "move_20m_aligned_pts": "",
        "notes": "",
    }


def churn_rows(args: argparse.Namespace, date: str, clusters: list[ChurnCluster], pad_ticks: int) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for index, cluster in enumerate(clusters, 1):
        row = base_row(args, date, "churn", cluster_id(date, index))
        row.update(
            {
                "start_et": et(cluster.start_ts),
                "end_et": et(cluster.end_ts),
                "focus_et": et(cluster.end_ts),
                "side": "TWO_SIDED",
                "source": "LL_FAIL_CLUSTER",
                "min_price": fmt_price(cluster.min_tick),
                "max_price": fmt_price(cluster.max_tick),
                "context_min_price": fmt_price(cluster.min_tick - pad_ticks),
                "context_max_price": fmt_price(cluster.max_tick + pad_ticks),
                "score": f"{cluster.score:.1f}",
                "demand_fails": str(cluster.demand_fails),
                "supply_fails": str(cluster.supply_fails),
                "notes": "two-sided ownership failures; keep as contested/churn fixture, not discard",
            }
        )
        rows.append(row)
    return rows


def transition_counts(probe: OwnershipProbe, start: datetime, end: datetime, min_tick: int, max_tick: int) -> Counter[tuple[str, str]]:
    counts: Counter[tuple[str, str]] = Counter()
    for tr in probe.transitions:
        if tr.ts < start or tr.ts > end:
            continue
        if tr.max_tick < min_tick or tr.min_tick > max_tick:
            continue
        if tr.action in ("OWNED", "CONSUMED"):
            counts[("claim", tr.side)] += 1
            if tr.action == "CONSUMED":
                counts[("consumed", tr.side)] += 1
        elif tr.action == "FAIL":
            counts[("fail", tr.side)] += 1
    return counts


def survivor_rows(
    args: argparse.Namespace,
    date: str,
    probe: OwnershipProbe,
    clusters: list[ChurnCluster],
    price_index: PriceIndex,
    window_end: datetime,
    pad_ticks: int,
) -> list[dict[str, str]]:
    candidates = []
    for band in probe.bands:
        life = band_life_sec(band, window_end)
        if life < args.survivor_min_sec:
            continue
        near_churn = any(overlaps_cluster(band.min_tick, band.max_tick, band.owned_ts, cluster, pad_ticks) for cluster in clusters)
        if near_churn:
            continue
        candidates.append((life, band.score, band))

    rows: list[dict[str, str]] = []
    for _, _, band in sorted(candidates, reverse=True)[: args.top_survivors_per_day]:
        life = band_life_sec(band, window_end)
        row = base_row(args, date, "survivor_clean", band_id(date, "survivor", band))
        counts = transition_counts(
            probe,
            band.owned_ts,
            min(band.owned_ts + timedelta(minutes=20), window_end),
            band.min_tick - pad_ticks,
            band.max_tick + pad_ticks,
        )
        row.update(
            {
                "start_et": et(band.owned_ts),
                "end_et": et(band.failed_ts or window_end),
                "focus_et": et(band.owned_ts),
                "side": side_label(band.side),
                "source": band.source,
                "band_id": str(band.id),
                "band_state": band_status(band),
                "min_price": fmt_price(band.min_tick),
                "max_price": fmt_price(band.max_tick),
                "context_min_price": fmt_price(band.min_tick - pad_ticks),
                "context_max_price": fmt_price(band.max_tick + pad_ticks),
                "life_sec": seconds_label(life),
                "score": f"{band.score:.1f}",
                "event_count": str(band.event_count),
                "max_abs_z": f"{band.max_abs_z:.1f}",
                "claim_demand": str(counts[("claim", "demand")]),
                "claim_supply": str(counts[("claim", "supply")]),
                "consumed_demand": str(counts[("consumed", "demand")]),
                "consumed_supply": str(counts[("consumed", "supply")]),
                "fail_demand": str(counts[("fail", "demand")]),
                "fail_supply": str(counts[("fail", "supply")]),
                "move_5m_aligned_pts": points_label(price_index.aligned_move_points(band.owned_ts, band.side, 5 * 60)),
                "move_10m_aligned_pts": points_label(price_index.aligned_move_points(band.owned_ts, band.side, 10 * 60)),
                "move_20m_aligned_pts": points_label(price_index.aligned_move_points(band.owned_ts, band.side, 20 * 60)),
                "notes": "survived outside detected churn cluster",
            }
        )
        rows.append(row)
    return rows


def repair_after_churn_rows(
    args: argparse.Namespace,
    date: str,
    probe: OwnershipProbe,
    clusters: list[ChurnCluster],
    price_index: PriceIndex,
    window_end: datetime,
    pad_ticks: int,
) -> list[dict[str, str]]:
    bands_by_id = {band.id: band for band in probe.bands}
    rows: list[dict[str, str]] = []
    used_bands: set[int] = set()
    lookahead = timedelta(minutes=args.repair_lookahead_min)
    for index, cluster in enumerate(clusters, 1):
        candidates = []
        for tr in probe.transitions:
            if tr.action not in ("OWNED", "CONSUMED"):
                continue
            if tr.ts <= cluster.end_ts or tr.ts > cluster.end_ts + lookahead:
                continue
            if tr.max_tick < cluster.min_tick - pad_ticks or tr.min_tick > cluster.max_tick + pad_ticks:
                continue
            band = bands_by_id.get(tr.band_id)
            if band is None:
                continue
            life = band_life_sec(band, window_end)
            if life < args.repair_min_sec:
                continue
            candidates.append((tr.ts, -life, tr.band_id, tr, band, life))

        for _, _, _, tr, band, life in sorted(candidates)[:3]:
            if band.id in used_bands:
                continue
            used_bands.add(band.id)
            row = base_row(args, date, "repair_after_churn", f"{cluster_id(date, index)}_repair_band{band.id}")
            counts = transition_counts(
                probe,
                cluster.start_ts,
                min(tr.ts + timedelta(minutes=20), window_end),
                cluster.min_tick - pad_ticks,
                cluster.max_tick + pad_ticks,
            )
            row.update(
                {
                    "start_et": et(cluster.start_ts),
                    "end_et": et(band.failed_ts or window_end),
                    "focus_et": et(tr.ts),
                    "side": side_label(tr.side),
                    "source": f"{tr.action}:{band.source}",
                    "band_id": str(band.id),
                    "band_state": band_status(band),
                    "min_price": fmt_price(band.min_tick),
                    "max_price": fmt_price(band.max_tick),
                    "context_min_price": fmt_price(cluster.min_tick - pad_ticks),
                    "context_max_price": fmt_price(cluster.max_tick + pad_ticks),
                    "life_sec": seconds_label(life),
                    "score": f"{band.score:.1f}",
                    "event_count": str(band.event_count),
                    "max_abs_z": f"{band.max_abs_z:.1f}",
                    "demand_fails": str(cluster.demand_fails),
                    "supply_fails": str(cluster.supply_fails),
                    "claim_demand": str(counts[("claim", "demand")]),
                    "claim_supply": str(counts[("claim", "supply")]),
                    "consumed_demand": str(counts[("consumed", "demand")]),
                    "consumed_supply": str(counts[("consumed", "supply")]),
                    "fail_demand": str(counts[("fail", "demand")]),
                    "fail_supply": str(counts[("fail", "supply")]),
                    "move_5m_aligned_pts": points_label(price_index.aligned_move_points(tr.ts, tr.side, 5 * 60)),
                    "move_10m_aligned_pts": points_label(price_index.aligned_move_points(tr.ts, tr.side, 10 * 60)),
                    "move_20m_aligned_pts": points_label(price_index.aligned_move_points(tr.ts, tr.side, 20 * 60)),
                    "notes": "claim formed inside/near prior churn after two-sided failure cluster",
                }
            )
            rows.append(row)
    return rows


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def write_markdown(path: Path, rows: list[dict[str, str]], manifest: dict[str, Any]) -> None:
    bucket_counts = Counter(row["bucket"] for row in rows)
    lines = [
        "# LOB Episode Prep",
        "",
        "Source: MarketRecorder snapshots replayed through existing LevelLedger ownership math.",
        "Purpose: prepare candidate windows before testing Udit-style book-evolution metrics.",
        "",
        "## Run",
        "",
        f"- dates: {', '.join(manifest['dates'])}",
        f"- symbol_dir: {manifest['symbol_dir']}",
        f"- window: {manifest['window']}",
        f"- context_points: {manifest['context_points']}",
        "",
        "## Bucket Counts",
        "",
    ]
    for bucket, count in sorted(bucket_counts.items()):
        lines.append(f"- {bucket}: {count}")
    lines.extend(["", "## Episodes", ""])
    for row in rows:
        lines.append(
            f"- {row['bucket']} {row['episode_id']} {row['side']} "
            f"{row['focus_et']} {row['min_price']}-{row['max_price']} "
            f"life={row['life_sec']}s move10={row['move_10m_aligned_pts']} "
            f"{row['notes']}"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    args = parse_args()
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    pad_ticks = int(round(args.context_points / TICK_SIZE))
    all_rows: list[dict[str, str]] = []
    manifest: dict[str, Any] = {
        "dates": [part.strip() for part in args.dates.split(",") if part.strip()],
        "symbol_dir": args.symbol_dir,
        "window": args.window,
        "context_points": args.context_points,
        "parameters": vars(args),
        "sessions": [],
    }

    for date in manifest["dates"]:
        probe, snapshot_rows, meta = make_probe(args, date)
        price_index = PriceIndex(snapshot_rows)
        clusters = build_churn_clusters(args, probe, meta["window_start"], meta["window_end"])
        date_rows: list[dict[str, str]] = []
        date_rows.extend(churn_rows(args, date, clusters, pad_ticks))
        date_rows.extend(
            survivor_rows(
                args,
                date,
                probe,
                clusters,
                price_index,
                meta["window_end"],
                pad_ticks,
            )
        )
        date_rows.extend(
            repair_after_churn_rows(
                args,
                date,
                probe,
                clusters,
                price_index,
                meta["window_end"],
                pad_ticks,
            )
        )
        all_rows.extend(date_rows)
        manifest["sessions"].append(
            {
                **{key: value for key, value in meta.items() if not isinstance(value, datetime)},
                "transitions": len(probe.transitions),
                "bands": len(probe.bands),
                "churn_clusters": len(clusters),
                "episode_rows": len(date_rows),
            }
        )

    csv_path = out_dir / "lob_episode_candidates.csv"
    md_path = out_dir / "lob_episode_candidates.md"
    manifest_path = out_dir / "manifest.json"
    write_csv(csv_path, all_rows)
    write_markdown(md_path, all_rows, manifest)
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    print(f"wrote {csv_path}")
    print(f"wrote {md_path}")
    print(f"wrote {manifest_path}")
    print(f"episodes={len(all_rows)} buckets={dict(Counter(row['bucket'] for row in all_rows))}")


if __name__ == "__main__":
    main()
