"""Structured LevelLedger ownership-band adapter for Dost.

This script deliberately reuses LevelLedger's research replay instead of
re-implementing band logic. Its job is only to expose the replay result as
stable JSON that a Codex skill or an MCP tool can consume.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


REPO_ROOT = Path(__file__).resolve().parents[3]
LL_RESEARCH = REPO_ROOT / "LevelLedger" / "research"
if str(LL_RESEARCH) not in sys.path:
    sys.path.insert(0, str(LL_RESEARCH))

import ownership_bands_probe as ob  # noqa: E402


TICK_SIZE = 0.25
NY = ZoneInfo("America/New_York")


@dataclass(frozen=True)
class Query:
    date: str
    symbol_dir: str = "NQM6"
    window: str = "09:30-10:30"
    warmup_min: int = 90
    event_z: float = ob.EVENT_Z_THRESHOLD
    book_lookback_sec: int = ob.BOOK_LOOKBACK_SEC
    cluster_min_events: int = 3
    cluster_ticks: int = 10
    cluster_sec: int = 90
    cluster_min_score: float = 8.0
    confirm_ticks: int = 8
    confirm_sec: int = 10
    test_buffer_ticks: int = 4
    fail_buffer_ticks: int = 2
    fail_confirm_ticks: int = 8
    fail_sec: int = 10
    hold_confirm_ticks: int = 10
    gap_threshold_sec: float = 5.0
    bucket_min: int = 30
    contested_sec: int = 1200
    contested_proximity_ticks: int = 80
    contested_span_ticks: int = 240
    contested_min_fails: int = 4
    topn: int = 10
    max_transitions: int = 120


def price(tick: int | None) -> float | None:
    if tick is None:
        return None
    return round(tick * TICK_SIZE, 2)


def iso_ny(ts: datetime | None) -> str | None:
    if ts is None:
        return None
    return ts.astimezone(NY).isoformat(timespec="seconds")


def hms(ts: datetime | None) -> str | None:
    if ts is None:
        return None
    return ob.ny_hms(ts)


def duration_sec(start: datetime, end: datetime) -> float:
    return max(0.0, (end - start).total_seconds())


def transition_to_dict(tr: ob.Transition) -> dict[str, Any]:
    return {
        "time": hms(tr.ts),
        "time_ny": iso_ny(tr.ts),
        "action": tr.action,
        "band_id": tr.band_id,
        "side": tr.side,
        "source": tr.source,
        "state": tr.state,
        "range": ob.range_label(tr.min_tick, tr.max_tick),
        "min_price": price(tr.min_tick),
        "max_price": price(tr.max_tick),
        "current_price": price(tr.current_mid_tick),
        "current": ob.abbrev(tr.current_mid_tick),
        "events": tr.event_count,
        "score": round(tr.score, 3),
        "max_abs_z": round(tr.max_abs_z, 3),
        "kinds": [item for item in tr.note.split(",") if item],
    }


def band_to_dict(band: ob.OwnershipBand, window_end: datetime) -> dict[str, Any]:
    end_ts = band.failed_ts or window_end
    life = duration_sec(band.owned_ts, end_ts)
    return {
        "band_id": band.id,
        "side": band.side,
        "source": band.source,
        "state": band.state,
        "range": ob.range_label(band.min_tick, band.max_tick),
        "min_price": price(band.min_tick),
        "max_price": price(band.max_tick),
        "evidence_start": hms(band.evidence_start_ts),
        "formed": hms(band.formed_ts),
        "owned": hms(band.owned_ts),
        "last_event": hms(band.last_event_ts),
        "tested": hms(band.tested_ts),
        "held": hms(band.held_ts),
        "failed": hms(band.failed_ts),
        "fail_price": price(band.fail_price_tick),
        "life_sec": round(life, 1),
        "life": ob.duration_label(life),
        "events": band.event_count,
        "score": round(band.score, 3),
        "max_abs_z": round(band.max_abs_z, 3),
        "kinds": sorted(band.kinds),
    }


def outcome_bucket(band: ob.OwnershipBand) -> str:
    if band.failed_ts is None:
        return "active"
    life = duration_sec(band.owned_ts, band.failed_ts)
    if life <= 60:
        return "fail<=1m"
    if life <= 300:
        return "fail<=5m"
    return "fail>5m"


def outcome_counts(bands: list[ob.OwnershipBand]) -> dict[str, dict[str, int]]:
    buckets = ("active", "fail<=1m", "fail<=5m", "fail>5m")
    out = {side: {bucket: 0 for bucket in buckets} for side in ("demand", "supply")}
    for band in bands:
        out[band.side][outcome_bucket(band)] += 1
    for side in out:
        out[side]["total"] = sum(out[side][bucket] for bucket in buckets)
    return out


def bucket_summary(
    transitions: list[ob.Transition],
    window_start: datetime,
    window_end: datetime,
    bucket_min: int,
) -> list[dict[str, Any]]:
    if bucket_min <= 0:
        return []
    rows: list[dict[str, Any]] = []
    start = window_start
    delta = timedelta(minutes=bucket_min)
    while start < window_end:
        end = min(start + delta, window_end)
        row = {
            "start": hms(start),
            "end": hms(end),
            "claim": {"demand": 0, "supply": 0},
            "consumed": {"demand": 0, "supply": 0},
            "fail": {"demand": 0, "supply": 0},
        }
        for tr in transitions:
            if tr.ts < start or tr.ts >= end:
                continue
            if tr.action in ("OWNED", "CONSUMED"):
                row["claim"][tr.side] += 1
                if tr.action == "CONSUMED":
                    row["consumed"][tr.side] += 1
            elif tr.action == "FAIL":
                row["fail"][tr.side] += 1
        rows.append(row)
        start = end
    return rows


def failure_clusters(
    transitions: list[ob.Transition],
    window_start: datetime,
    window_end: datetime,
    contested_sec: int,
    proximity_ticks: int,
    span_ticks: int,
    min_fails: int,
) -> list[dict[str, Any]]:
    fails = [
        tr for tr in transitions
        if window_start <= tr.ts <= window_end and tr.action == "FAIL"
    ]
    clusters: list[ob.FailureCluster] = []
    for tr in fails:
        matched: ob.FailureCluster | None = None
        for cluster in clusters:
            if (tr.ts - cluster.end_ts).total_seconds() > contested_sec:
                continue
            if tr.max_tick < cluster.min_tick - proximity_ticks:
                continue
            if tr.min_tick > cluster.max_tick + proximity_ticks:
                continue
            if max(cluster.max_tick, tr.max_tick) - min(cluster.min_tick, tr.min_tick) > span_ticks:
                continue
            matched = cluster
            break

        if matched is None:
            matched = ob.FailureCluster(
                start_ts=tr.ts,
                end_ts=tr.ts,
                min_tick=tr.min_tick,
                max_tick=tr.max_tick,
            )
            clusters.append(matched)
        else:
            matched.end_ts = tr.ts
            matched.min_tick = min(matched.min_tick, tr.min_tick)
            matched.max_tick = max(matched.max_tick, tr.max_tick)

        if tr.side == "demand":
            matched.demand_fails += 1
        else:
            matched.supply_fails += 1
        matched.score += tr.score

    out = []
    for cluster in clusters:
        if cluster.demand_fails == 0 or cluster.supply_fails == 0:
            continue
        if cluster.total_fails < min_fails:
            continue
        out.append(
            {
                "start": hms(cluster.start_ts),
                "end": hms(cluster.end_ts),
                "range": ob.range_label(cluster.min_tick, cluster.max_tick),
                "min_price": price(cluster.min_tick),
                "max_price": price(cluster.max_tick),
                "demand_fails": cluster.demand_fails,
                "supply_fails": cluster.supply_fails,
                "total_fails": cluster.total_fails,
                "score": round(cluster.score, 3),
            }
        )
    return out


def run_query(query: Query) -> dict[str, Any]:
    start_s, end_s = query.window.split("-", 1)
    window_start = ob.parse_ny(query.date, start_s)
    window_end = ob.parse_ny(query.date, end_s)
    replay_start = window_start - timedelta(minutes=query.warmup_min)

    snap = ob.load_snapshots(query.symbol_dir, replay_start, window_end)
    first_snap, last_snap, duplicate_count, gaps = ob.snapshot_timing_summary(
        snap,
        query.gap_threshold_sec,
    )

    probe = ob.OwnershipProbe(
        event_z=query.event_z,
        book_lookback_sec=query.book_lookback_sec,
        cluster_min_events=query.cluster_min_events,
        cluster_ticks=query.cluster_ticks,
        cluster_sec=query.cluster_sec,
        cluster_min_score=query.cluster_min_score,
        confirm_ticks=query.confirm_ticks,
        confirm_sec=query.confirm_sec,
        test_buffer_ticks=query.test_buffer_ticks,
        fail_buffer_ticks=query.fail_buffer_ticks,
        fail_confirm_ticks=query.fail_confirm_ticks,
        fail_sec=query.fail_sec,
        hold_confirm_ticks=query.hold_confirm_ticks,
    )

    for row in snap.iter_rows(named=True):
        probe.on_sample(ob.build_sample(row))

    window_transitions = [
        tr for tr in probe.transitions
        if window_start <= tr.ts <= window_end
    ]
    owned = [
        band for band in probe.bands
        if window_start <= band.owned_ts <= window_end
    ]
    durable = sorted(
        owned,
        key=lambda band: (
            duration_sec(band.owned_ts, band.failed_ts or window_end),
            band.score,
        ),
        reverse=True,
    )[:query.topn]
    active = probe.active_bands(window_end, probe.current_mid_tick, query.topn)
    transitions = sorted(window_transitions, key=lambda tr: tr.ts)
    if query.max_transitions > 0:
        transitions = transitions[-query.max_transitions:]

    gap_rows = [
        {
            "start": hms(start),
            "end": hms(end),
            "seconds": round(seconds, 3),
        }
        for start, end, seconds in gaps[:20]
    ]

    return {
        "query": asdict(query),
        "data_health": {
            "rows": snap.height,
            "snapshot_span": {
                "start": hms(first_snap),
                "end": hms(last_snap),
                "start_ny": iso_ny(first_snap),
                "end_ny": iso_ny(last_snap),
            },
            "duplicate_timestamps": duplicate_count,
            "gap_threshold_sec": query.gap_threshold_sec,
            "gap_count": len(gaps),
            "max_gap_sec": round(max((gap[2] for gap in gaps), default=0.0), 3),
            "gaps": gap_rows,
            "gaps_truncated": max(0, len(gaps) - len(gap_rows)),
        },
        "counts": {
            "candidates": len(probe.candidates),
            "owned_total": len(probe.bands),
            "transitions_in_window": len(window_transitions),
            "owned_in_window": len(owned),
        },
        "current": {
            "as_of": hms(window_end),
            "mid_price": price(probe.current_mid_tick),
            "mid": ob.abbrev(probe.current_mid_tick),
        },
        "bucket_summary": bucket_summary(
            window_transitions,
            window_start,
            window_end,
            query.bucket_min,
        ),
        "outcome_counts": outcome_counts(owned),
        "active_bands": [band_to_dict(band, window_end) for band in active],
        "durable_owned_in_window": [band_to_dict(band, window_end) for band in durable],
        "contested_failure_clusters": failure_clusters(
            window_transitions,
            window_start,
            window_end,
            query.contested_sec,
            query.contested_proximity_ticks,
            query.contested_span_ticks,
            query.contested_min_fails,
        ),
        "transitions": [transition_to_dict(tr) for tr in transitions],
    }


def format_text(result: dict[str, Any]) -> str:
    health = result["data_health"]
    counts = result["counts"]
    current = result["current"]
    lines = [
        f"{result['query']['date']} {result['query']['window']} {result['query']['symbol_dir']}",
        (
            f"rows={health['rows']:,} span={health['snapshot_span']['start']}-"
            f"{health['snapshot_span']['end']} gaps>{health['gap_threshold_sec']}s="
            f"{health['gap_count']} max_gap={health['max_gap_sec']}s"
        ),
        (
            f"current={current['mid']} ({current['mid_price']}) "
            f"owned_in_window={counts['owned_in_window']} "
            f"transitions={counts['transitions_in_window']}"
        ),
        "",
        "Durable owned-in-window:",
    ]
    if result["durable_owned_in_window"]:
        for band in result["durable_owned_in_window"]:
            state = "active" if not band["failed"] else f"failed@{band['failed']}"
            lines.append(
                f"- {band['owned']} {band['side']} {band['range']} "
                f"{band['source']} life={band['life']} score={band['score']} {state}"
            )
    else:
        lines.append("- none")

    lines.append("")
    lines.append("Active bands:")
    if result["active_bands"]:
        for band in result["active_bands"]:
            lines.append(
                f"- {band['owned']} {band['side']} {band['range']} "
                f"{band['source']} state={band['state']} score={band['score']}"
            )
    else:
        lines.append("- none")

    if result["contested_failure_clusters"]:
        lines.append("")
        lines.append("Contested failure clusters:")
        for cluster in result["contested_failure_clusters"]:
            lines.append(
                f"- {cluster['start']}-{cluster['end']} {cluster['range']} "
                f"fails D/S={cluster['demand_fails']}/{cluster['supply_fails']}"
            )
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", required=True)
    parser.add_argument("--symbol-dir", default="NQM6")
    parser.add_argument("--window", default="09:30-10:30")
    parser.add_argument("--warmup-min", type=int, default=90)
    parser.add_argument("--event-z", type=float, default=ob.EVENT_Z_THRESHOLD)
    parser.add_argument("--book-lookback-sec", type=int, default=ob.BOOK_LOOKBACK_SEC)
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
    parser.add_argument("--bucket-min", type=int, default=30)
    parser.add_argument("--contested-sec", type=int, default=1200)
    parser.add_argument("--contested-proximity-ticks", type=int, default=80)
    parser.add_argument("--contested-span-ticks", type=int, default=240)
    parser.add_argument("--contested-min-fails", type=int, default=4)
    parser.add_argument("--topn", type=int, default=10)
    parser.add_argument("--max-transitions", type=int, default=120)
    parser.add_argument("--format", choices=("json", "text"), default="json")
    return parser.parse_args()


def query_from_args(args: argparse.Namespace) -> Query:
    return Query(
        date=args.date,
        symbol_dir=args.symbol_dir,
        window=args.window,
        warmup_min=args.warmup_min,
        event_z=args.event_z,
        book_lookback_sec=args.book_lookback_sec,
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
        gap_threshold_sec=args.gap_threshold_sec,
        bucket_min=args.bucket_min,
        contested_sec=args.contested_sec,
        contested_proximity_ticks=args.contested_proximity_ticks,
        contested_span_ticks=args.contested_span_ticks,
        contested_min_fails=args.contested_min_fails,
        topn=args.topn,
        max_transitions=args.max_transitions,
    )


def main() -> None:
    args = parse_args()
    result = run_query(query_from_args(args))
    if args.format == "text":
        print(format_text(result))
    else:
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
