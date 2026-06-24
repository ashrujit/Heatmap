"""Exploratory event-level OFI probe for LL displacement confirmation.

The probe reuses the snapshot-defined LevelLedger episode population from
``snapshot_ofi_proxy_probe.py`` but reconstructs the raw MarketRecorder quote-id
stream between anchors. It reports both wall-clock and event-count horizons.

Rithmic-via-Quantower can omit closure callbacks for quote ids. The shared book
replay therefore removes mechanically impossible crossed levels, exactly as the
validated live BookState precedent does. OFI is reported both with those repair
events included and with their contribution zeroed so repair sensitivity is
visible rather than silently folded into the result.
"""

from __future__ import annotations

import argparse
import math
import os
import random
import re
import sys
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

import polars as pl

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "research"))
sys.path.insert(0, str(ROOT / "MarketRecorder" / "research"))

from candidate_timing_probe import load_filtered_snapshots, replay_session  # noqa: E402
from capture_loader import MARKET_RECORDER_ROOT, us  # noqa: E402
from snapshot_ofi_proxy_probe import (  # noqa: E402
    EVALUATION_LEADS,
    FUTURE_HORIZONS,
    NY,
    PRESSURE_WINDOWS,
    QUEUE_LEVELS,
    SessionSpec,
    add_metrics,
    build_snapshot_series,
    build_tick_series,
    conditional_auc,
    fmt,
    load_ticks,
    parse_session,
    parse_window,
    pct,
    replay_args,
    residual_auc,
    rank_auc,
    resolution_sign,
    session_auc,
    summarize_binary,
    write_csv,
)
from validate_book_events import (  # noqa: E402
    DELTA,
    GAP,
    RESET_BEGIN,
    BookReplay,
    event_files_with_carry,
)


TIME_WINDOWS = (3, 5, 10, 20)
EVENT_WINDOWS = (250, 500, 1000, 2000)
EVENT_COLUMNS = [
    "receipt_timestamp_us",
    "sequence",
    "subsequence",
    "reset_epoch",
    "event_kind",
    "side",
    "price_tick",
    "size",
    "closed",
    "quote_id_hash",
    "reset_item_count",
]


@dataclass(frozen=True)
class EventPoint:
    timestamp_us: int
    ofi: float
    clean_ofi: float
    depth: float
    repaired: bool


@dataclass
class EventReplayHealth:
    files: int = 0
    carry_days: int = 0
    rows_processed: int = 0
    valid_deltas: int = 0
    metric_events: int = 0
    repair_events: int = 0
    anchors: int = 0
    anchors_with_5s: int = 0
    anchors_with_1000e: int = 0
    completed_resets: int = 0
    incomplete_resets: int = 0
    gaps: int = 0
    crossed_levels_evicted: int = 0
    crossed_quotes_evicted: int = 0


def best_state(replay: BookReplay) -> tuple[int, float, int, float] | None:
    bid_tick = replay._best_tick(1)
    ask_tick = replay._best_tick(-1)
    if bid_tick is None or ask_tick is None or bid_tick >= ask_tick:
        return None
    bid_size = float(replay.bid_levels.get(bid_tick, 0.0))
    ask_size = float(replay.ask_levels.get(ask_tick, 0.0))
    if bid_size <= 0 or ask_size <= 0:
        return None
    return bid_tick, bid_size, ask_tick, ask_size


def cont_ofi(
    prior: tuple[int, float, int, float],
    current: tuple[int, float, int, float],
) -> float:
    prior_bid_tick, prior_bid_size, prior_ask_tick, prior_ask_size = prior
    bid_tick, bid_size, ask_tick, ask_size = current
    value = 0.0
    if bid_tick >= prior_bid_tick:
        value += bid_size
    if bid_tick <= prior_bid_tick:
        value -= prior_bid_size
    if ask_tick <= prior_ask_tick:
        value -= ask_size
    if ask_tick >= prior_ask_tick:
        value += prior_ask_size
    return value


class RollingEventOfi:
    def __init__(self) -> None:
        self.points: deque[EventPoint] = deque()
        self.last_timestamp_us = 0

    def clear(self) -> None:
        self.points.clear()
        self.last_timestamp_us = 0

    def add(self, point: EventPoint) -> None:
        self.points.append(point)
        self.last_timestamp_us = point.timestamp_us
        time_cutoff = point.timestamp_us - max(TIME_WINDOWS) * 1_000_000
        max_events = max(EVENT_WINDOWS)
        while (
            self.points
            and self.points[0].timestamp_us < time_cutoff
            and len(self.points) > max_events
        ):
            self.points.popleft()

    @staticmethod
    def normalized(points: list[EventPoint], *, clean: bool) -> float | None:
        if not points:
            return None
        depths = [point.depth for point in points if math.isfinite(point.depth) and point.depth > 0]
        if not depths:
            return None
        values = [point.clean_ofi if clean else point.ofi for point in points]
        return sum(values) / (sum(depths) / len(depths))

    def sample(self, anchor_us: int) -> dict[str, float | None]:
        result: dict[str, float | None] = {}
        if not self.points or anchor_us - self.last_timestamp_us > 500_000:
            for seconds in TIME_WINDOWS:
                result[f"event_ofi_{seconds}s"] = None
                result[f"clean_event_ofi_{seconds}s"] = None
                result[f"repair_share_{seconds}s"] = None
            for count in EVENT_WINDOWS:
                result[f"event_ofi_{count}e"] = None
                result[f"clean_event_ofi_{count}e"] = None
                result[f"repair_share_{count}e"] = None
                result[f"event_span_{count}e_sec"] = None
            return result

        values = list(self.points)
        for seconds in TIME_WINDOWS:
            cutoff = anchor_us - seconds * 1_000_000
            subset = [point for point in values if point.timestamp_us >= cutoff]
            covered = bool(subset) and subset[0].timestamp_us <= cutoff + 500_000
            if not covered:
                subset = []
            result[f"event_ofi_{seconds}s"] = self.normalized(subset, clean=False)
            result[f"clean_event_ofi_{seconds}s"] = self.normalized(subset, clean=True)
            result[f"repair_share_{seconds}s"] = (
                sum(point.repaired for point in subset) / len(subset) if subset else None
            )
        for count in EVENT_WINDOWS:
            subset = values[-count:] if len(values) >= count else []
            result[f"event_ofi_{count}e"] = self.normalized(subset, clean=False)
            result[f"clean_event_ofi_{count}e"] = self.normalized(subset, clean=True)
            result[f"repair_share_{count}e"] = (
                sum(point.repaired for point in subset) / len(subset) if subset else None
            )
            result[f"event_span_{count}e_sec"] = (
                (subset[-1].timestamp_us - subset[0].timestamp_us) / 1_000_000
                if subset
                else None
            )
        return result


def add_aligned_event_metrics(row: dict, metrics: dict[str, float | None]) -> None:
    side_sign = int(row["_side_sign"])
    for key, value in metrics.items():
        row[key] = value
        if key.startswith("event_ofi_") or key.startswith("clean_event_ofi_"):
            row[f"aligned_{key}"] = side_sign * value if value is not None else None


def chunk_groups(files: list[str]) -> list[list[str]]:
    groups: dict[str, list[str]] = {}
    order: list[str] = []
    for path in files:
        name = re.sub(r"-p\d+(?=\.parquet$)", "", os.path.basename(path))
        key = os.path.join(os.path.dirname(path), name)
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(path)
    return [groups[key] for key in order]


def sample_anchor_rows(
    capture_root: str,
    spec: SessionSpec,
    rows: list[dict],
    stop: datetime,
    max_carry_days: int,
) -> EventReplayHealth:
    files, carry_days = event_files_with_carry(
        capture_root,
        spec.symbol,
        spec.date,
        max_carry_days,
    )
    health = EventReplayHealth(files=len(files), carry_days=carry_days, anchors=len(rows))
    ordered_rows = sorted(rows, key=lambda row: int(row["_anchor_us"]))
    anchor_index = 0
    stop_us = us(stop)
    replay = BookReplay()
    rolling = RollingEventOfi()

    def sample_until(before_us: int) -> None:
        nonlocal anchor_index
        while (
            anchor_index < len(ordered_rows)
            and int(ordered_rows[anchor_index]["_anchor_us"]) < before_us
        ):
            row = ordered_rows[anchor_index]
            metrics = rolling.sample(int(row["_anchor_us"]))
            add_aligned_event_metrics(row, metrics)
            health.anchors_with_5s += int(metrics.get("event_ofi_5s") is not None)
            health.anchors_with_1000e += int(metrics.get("event_ofi_1000e") is not None)
            anchor_index += 1

    done = False
    for group in chunk_groups(files):
        frame = (
            pl.scan_parquet(group)
            .select(EVENT_COLUMNS)
            .filter(pl.col("receipt_timestamp_us") <= stop_us)
            .collect()
            .sort(["receipt_timestamp_us", "sequence", "subsequence"])
        )
        for row in frame.iter_rows(named=True):
            event_us = int(row["receipt_timestamp_us"])
            sample_until(event_us)
            if event_us > stop_us:
                done = True
                break
            kind = int(row["event_kind"])
            if kind in (GAP, RESET_BEGIN):
                rolling.clear()
            prior = best_state(replay) if replay.valid and kind == DELTA else None
            prior_evictions = replay.crossed_levels_evicted
            replay.apply(row)
            health.rows_processed += 1
            if kind != DELTA or prior is None or not replay.valid:
                continue
            health.valid_deltas += 1
            current = best_state(replay)
            if current is None:
                continue
            repaired = replay.crossed_levels_evicted > prior_evictions
            value = cont_ofi(prior, current)
            depth = current[1] + current[3]
            rolling.add(
                EventPoint(
                    timestamp_us=event_us,
                    ofi=value,
                    clean_ofi=0.0 if repaired else value,
                    depth=depth,
                    repaired=repaired,
                )
            )
            health.metric_events += 1
            health.repair_events += int(repaired)
        if done:
            break

    sample_until(stop_us + 1)
    health.completed_resets = replay.completed_resets
    health.incomplete_resets = replay.incomplete_resets
    health.gaps = replay.gaps
    health.crossed_levels_evicted = replay.crossed_levels_evicted
    health.crossed_quotes_evicted = replay.crossed_quotes_evicted
    return health


def build_rows(spec, episodes, snapshots, ticks) -> tuple[list[dict], list[dict]]:
    early: list[dict] = []
    confirmations: list[dict] = []
    for episode in episodes:
        if episode.gap_contaminated or episode.outcome not in ("confirmed", "reset"):
            continue
        side_sign = resolution_sign(episode)
        result_side = "demand" if side_sign > 0 else "supply"
        base = {
            "session": spec.label,
            "candidate_id": episode.candidate_id,
            "evidence_side": episode.evidence_side,
            "direction": episode.direction,
            "result_side": result_side,
            "outcome": episode.outcome,
            "duration_sec": episode.duration_sec,
            "event_count": episode.event_count,
            "score": episode.score,
            "kind_count": episode.kind_count,
            "_side_sign": side_sign,
        }
        for lead in EVALUATION_LEADS:
            if episode.duration_sec < lead:
                continue
            anchor = episode.start_ts + timedelta(seconds=lead)
            row = dict(base)
            row.update(
                phase="displacement",
                anchor_et=anchor.astimezone(NY).isoformat(),
                lead_sec=lead,
                _anchor_us=us(anchor),
            )
            add_metrics(row, anchor, side_sign, snapshots, ticks)
            early.append(row)
        if episode.outcome == "confirmed" and episode.end_ts is not None:
            anchor = episode.end_ts
            row = dict(base)
            row.update(
                phase="confirmation",
                anchor_et=anchor.astimezone(NY).isoformat(),
                lead_sec=episode.duration_sec,
                _anchor_us=us(anchor),
            )
            add_metrics(row, anchor, side_sign, snapshots, ticks)
            confirmations.append(row)
    return early, confirmations


def clean_internal_fields(rows: list[dict]) -> None:
    for row in rows:
        row.pop("_side_sign", None)
        row.pop("_anchor_us", None)


def candidate_cluster_auc(
    rows: list[dict],
    feature: str,
    *,
    reps: int = 2000,
    seed: int = 623,
) -> tuple[float | None, float | None, float | None, int]:
    grouped: dict[tuple[str, str], list[tuple[float, bool]]] = {}
    for row in rows:
        value = row.get(feature)
        if value is None:
            continue
        key = (str(row["session"]), str(row["candidate_id"]))
        grouped.setdefault(key, []).append((float(value), row["outcome"] == "confirmed"))
    keys = list(grouped)
    observed = [item for key in keys for item in grouped[key]]
    point = rank_auc([item[0] for item in observed], [item[1] for item in observed])
    if len(keys) < 2 or point is None:
        return point, None, None, len(keys)
    rng = random.Random(seed)
    estimates: list[float] = []
    for _ in range(reps):
        sample = [rng.choice(keys) for _ in keys]
        values = [item for key in sample for item in grouped[key]]
        estimate = rank_auc([item[0] for item in values], [item[1] for item in values])
        if estimate is not None:
            estimates.append(estimate)
    if not estimates:
        return point, None, None, len(keys)
    estimates.sort()
    lo = estimates[int(0.025 * (len(estimates) - 1))]
    hi = estimates[int(0.975 * (len(estimates) - 1))]
    return point, lo, hi, len(keys)


def candidate_cluster_auc_delta(
    rows: list[dict],
    left_feature: str,
    right_feature: str,
    *,
    reps: int = 2000,
    seed: int = 623,
) -> tuple[float | None, float | None, float | None, int]:
    grouped: dict[tuple[str, str], list[tuple[float, float, bool]]] = {}
    for row in rows:
        left = row.get(left_feature)
        right = row.get(right_feature)
        if left is None or right is None:
            continue
        key = (str(row["session"]), str(row["candidate_id"]))
        grouped.setdefault(key, []).append(
            (float(left), float(right), row["outcome"] == "confirmed")
        )
    keys = list(grouped)

    def difference(values: list[tuple[float, float, bool]]) -> float | None:
        labels = [item[2] for item in values]
        left_auc = rank_auc([item[0] for item in values], labels)
        right_auc = rank_auc([item[1] for item in values], labels)
        if left_auc is None or right_auc is None:
            return None
        return left_auc - right_auc

    observed = [item for key in keys for item in grouped[key]]
    point = difference(observed)
    if len(keys) < 2 or point is None:
        return point, None, None, len(keys)
    rng = random.Random(seed)
    estimates: list[float] = []
    for _ in range(reps):
        sample = [rng.choice(keys) for _ in keys]
        estimate = difference([item for key in sample for item in grouped[key]])
        if estimate is not None:
            estimates.append(estimate)
    if not estimates:
        return point, None, None, len(keys)
    estimates.sort()
    lo = estimates[int(0.025 * (len(estimates) - 1))]
    hi = estimates[int(0.975 * (len(estimates) - 1))]
    return point, lo, hi, len(keys)


def build_summary(
    specs: list[SessionSpec],
    counts: dict[str, tuple[int, int]],
    health: dict[str, EventReplayHealth],
    early: list[dict],
    confirmations: list[dict],
) -> str:
    lines = [
        "Event-level OFI exploratory report",
        "Crossed-level repairs are explicit; clean-event OFI zeros repaired-event contributions.",
        "One session is exploratory only: no held-out session or session-clustered uncertainty is available.",
        "",
        "Coverage and replay health",
    ]
    for spec in specs:
        episodes, confirmed = counts[spec.label]
        item = health[spec.label]
        repair_rate = pct(item.repair_events, item.metric_events)
        lines.append(
            f"  {spec.label} {spec.window}: resolved={episodes}, confirmed={confirmed}; "
            f"rows={item.rows_processed}, valid_deltas={item.valid_deltas}, resets={item.completed_resets}, "
            f"gaps={item.gaps}, repaired_events={item.repair_events} ({repair_rate:.4f}%), "
            f"crossed_levels/quotes={item.crossed_levels_evicted}/{item.crossed_quotes_evicted}"
        )
        lines.append(
            f"    anchor coverage: 5s={item.anchors_with_5s}/{item.anchors}, "
            f"1000-event={item.anchors_with_1000e}/{item.anchors}; carry_days={item.carry_days}"
        )

    features = [
        "aligned_event_ofi_3s",
        "aligned_event_ofi_5s",
        "aligned_clean_event_ofi_5s",
        "aligned_event_ofi_500e",
        "aligned_event_ofi_1000e",
        "aligned_clean_event_ofi_1000e",
        "aligned_ofi_5s",
        "aligned_price_5s_ticks",
        "aligned_qi_5",
        "aligned_tfi_5s",
        "aligned_tfi_10s",
    ]
    lines.extend(
        [
            "",
            "Early confirmation discrimination",
            "Scores are aligned to eventual resolution; AUC > 0.5 favors confirmation.",
        ]
    )
    for lead in EVALUATION_LEADS:
        subset = [row for row in early if row["lead_sec"] == lead]
        lines.append(f"  after {lead}s persistence: n={len(subset)}")
        for feature in features:
            summary = summarize_binary(subset, feature, lambda row: row["outcome"] == "confirmed")
            if summary is None:
                continue
            lines.append(
                f"    {feature:<31} auc={fmt(summary['auc'])} "
                f"med confirmed/reset={fmt(summary['positive_median'])}/{fmt(summary['negative_median'])} "
                f"sign lift={fmt(summary['lift_pp'], 1)}pp "
                f"({session_auc(subset, feature, lambda row: row['outcome'] == 'confirmed')})"
            )

    lead_five = [row for row in early if row["lead_sec"] == 5]
    lines.extend(
        [
            "",
            "Increment beyond five-second price progress",
            "Conditional AUC uses four-tick price-progress buckets; residual AUC removes a pooled linear relation.",
        ]
    )
    for feature in (
        "aligned_event_ofi_3s",
        "aligned_event_ofi_5s",
        "aligned_clean_event_ofi_5s",
        "aligned_event_ofi_500e",
        "aligned_event_ofi_1000e",
        "aligned_ofi_5s",
        "aligned_tfi_5s",
        "aligned_tfi_10s",
    ):
        cond_auc, pairs, buckets = conditional_auc(
            lead_five,
            feature,
            "aligned_price_5s_ticks",
            lambda row: row["outcome"] == "confirmed",
            4.0,
        )
        resid_auc = residual_auc(
            lead_five,
            feature,
            "aligned_price_5s_ticks",
            lambda row: row["outcome"] == "confirmed",
        )
        lines.append(
            f"  {feature:<33} conditional_auc={fmt(cond_auc)} pairs={pairs} "
            f"buckets={buckets} residual_auc={fmt(resid_auc)}"
        )

    lines.extend(
        [
            "",
            "Candidate-cluster bootstrap at five seconds",
            "Intervals resample LL candidate ids within this session; they do not estimate cross-session generalization.",
        ]
    )
    for feature in (
        "aligned_event_ofi_3s",
        "aligned_event_ofi_5s",
        "aligned_event_ofi_1000e",
        "aligned_ofi_5s",
        "aligned_price_5s_ticks",
    ):
        point, lo, hi, clusters = candidate_cluster_auc(lead_five, feature)
        lines.append(
            f"  {feature:<33} auc={fmt(point)} 95% candidate-CI=[{fmt(lo)}, {fmt(hi)}] "
            f"clusters={clusters}"
        )
    for left, right in (
        ("aligned_event_ofi_5s", "aligned_ofi_5s"),
        ("aligned_event_ofi_5s", "aligned_price_5s_ticks"),
        ("aligned_event_ofi_3s", "aligned_price_5s_ticks"),
    ):
        point, lo, hi, clusters = candidate_cluster_auc_delta(lead_five, left, right)
        lines.append(
            f"  delta {left} - {right}: {fmt(point)} 95% candidate-CI=[{fmt(lo)}, {fmt(hi)}] "
            f"clusters={clusters}"
        )

    continuation = [row for row in confirmations if row.get("future_net_30s_ticks") is not None]
    positive = sum(float(row["future_net_30s_ticks"]) > 0 for row in continuation)
    lines.extend(
        [
            "",
            "Post-confirmation 30-second continuation",
            f"  labels={len(continuation)}, directionally positive={positive} ({pct(positive, len(continuation)):.1f}%)",
        ]
    )
    for feature in features:
        summary = summarize_binary(
            continuation,
            feature,
            lambda row: float(row["future_net_30s_ticks"]) > 0,
        )
        if summary is None:
            continue
        lines.append(
            f"    {feature:<31} auc={fmt(summary['auc'])} "
            f"med continue/not={fmt(summary['positive_median'])}/{fmt(summary['negative_median'])} "
            f"sign lift={fmt(summary['lift_pp'], 1)}pp"
        )
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--session",
        action="append",
        required=True,
        help="Repeatable YYYY-MM-DD:SYMBOL[:HH:MM-HH:MM]",
    )
    parser.add_argument("--window", default="09:30-16:00")
    parser.add_argument("--warmup-min", type=int, default=90)
    parser.add_argument("--capture-root", default=MARKET_RECORDER_ROOT)
    parser.add_argument("--out-dir", default=str(ROOT / "research" / "out"))
    parser.add_argument("--gap-threshold-sec", type=float, default=5.0)
    parser.add_argument("--max-carry-days", type=int, default=7)

    parser.add_argument("--event-z", type=float, default=2.5)
    parser.add_argument("--book-lookback-sec", type=int, default=30)
    parser.add_argument("--cluster-min-events", type=int, default=3)
    parser.add_argument("--cluster-ticks", type=int, default=10)
    parser.add_argument("--cluster-sec", type=int, default=90)
    parser.add_argument("--cluster-min-score", type=float, default=8.0)
    parser.add_argument("--confirm-ticks", type=int, default=8)
    parser.add_argument("--confirm-sec", type=int, default=10)
    parser.add_argument("--test-buffer-ticks", type=int, default=4)
    parser.add_argument("--fail-buffer-ticks", type=int, default=2)
    parser.add_argument("--fail-confirm-ticks", type=int, default=24)
    parser.add_argument("--fail-sec", type=int, default=20)
    parser.add_argument("--hold-confirm-ticks", type=int, default=10)
    args = parser.parse_args()

    specs = [parse_session(value, args.window) for value in args.session]
    all_early: list[dict] = []
    all_confirmations: list[dict] = []
    counts: dict[str, tuple[int, int]] = {}
    health: dict[str, EventReplayHealth] = {}

    for spec in specs:
        start, end = parse_window(spec.date, spec.window)
        replay = replay_session(replay_args(args, spec), spec.date, spec.symbol)
        metric_start = start - timedelta(seconds=max(PRESSURE_WINDOWS) + 5)
        metric_end = end + timedelta(seconds=max(FUTURE_HORIZONS) + 5)
        snapshots_df = load_filtered_snapshots(
            args.capture_root,
            spec.symbol,
            spec.date,
            metric_start,
            metric_end,
        )
        ticks_df = load_ticks(args.capture_root, spec, metric_start, metric_end)
        snapshots = build_snapshot_series(snapshots_df, args.gap_threshold_sec)
        ticks = build_tick_series(ticks_df)
        early, confirmations = build_rows(spec, replay.episodes, snapshots, ticks)
        health[spec.label] = sample_anchor_rows(
            args.capture_root,
            spec,
            early + confirmations,
            end,
            args.max_carry_days,
        )
        all_early.extend(early)
        all_confirmations.extend(confirmations)
        clean_resolved = [
            episode
            for episode in replay.episodes
            if not episode.gap_contaminated and episode.outcome in ("confirmed", "reset")
        ]
        counts[spec.label] = (
            len(clean_resolved),
            sum(episode.outcome == "confirmed" for episode in clean_resolved),
        )

    summary = build_summary(specs, counts, health, all_early, all_confirmations)
    clean_internal_fields(all_early)
    clean_internal_fields(all_confirmations)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    dates = "_".join(spec.date for spec in specs)
    prefix = out_dir / f"event_ofi_{dates}"
    summary_path = prefix.with_suffix(".txt")
    episodes_path = Path(str(prefix) + "_episodes.csv")
    confirmations_path = Path(str(prefix) + "_confirmations.csv")
    summary_path.write_text(summary, encoding="utf-8")
    write_csv(episodes_path, all_early)
    write_csv(confirmations_path, all_confirmations)

    print(summary, end="")
    print(f"outputs:\n  {summary_path}\n  {episodes_path}\n  {confirmations_path}")


if __name__ == "__main__":
    main()
