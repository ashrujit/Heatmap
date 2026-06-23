"""Exploratory snapshot-pressure probe for LevelLedger/EAR research.

This is deliberately *not* event-level OFI. MarketRecorder currently stores
periodic canonical DOM snapshots, so intermediate additions, cancellations,
and executions are aliased. The probe asks a narrower gating question:

    Does a Cont-style best-book change proxy contain enough directional
    information at LL displacement/confirmation anchors to justify collecting
    faithful event-level data?

The probe replays LL candidates with the existing 1-second grammar, samples a
snapshot OFI proxy, queue imbalance, and aggressor-tape imbalance, and measures
their separation of confirmed versus reset displacement episodes. Confirmed
episodes are also checked for subsequent directional continuation. Optional
EAR order-submit anchors provide an execution-day audit without being used as
the statistical population.

A positive result is evidence to pursue better capture. A negative result does
not rule out event-level OFI because the source data discard intermediate book
events.
"""

from __future__ import annotations

import argparse
import bisect
import csv
import glob
import json
import math
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import median
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import polars as pl

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "research"))

from candidate_timing_probe import (  # noqa: E402
    DisplacementEpisode,
    load_filtered_snapshots,
    replay_session,
)
from capture_loader import (  # noqa: E402
    MARKET_RECORDER_ROOT,
    snapshot_columns,
    tick_columns,
    us,
)


NY = ZoneInfo("America/New_York")
TICK_SIZE = 0.25
PRESSURE_WINDOWS = (3, 5, 10, 20)
QUEUE_LEVELS = (5, 10, 20)
EVALUATION_LEADS = (0, 3, 5)
FUTURE_HORIZONS = (10, 30, 60)


@dataclass(frozen=True)
class SessionSpec:
    date: str
    symbol: str
    window: str

    @property
    def label(self) -> str:
        return f"{self.date}:{self.symbol}"


@dataclass
class SnapshotSeries:
    times_us: list[int]
    mid_ticks: list[float]
    bid_ticks: list[int]
    ask_ticks: list[int]
    bid_sizes: list[float]
    ask_sizes: list[float]
    depths: list[float]
    step_ofi: list[float | None]
    step_static_ofi: list[float | None]
    queue_imbalance: dict[int, list[float]]
    gap_threshold_us: int

    def index_at(self, ts: datetime) -> int | None:
        idx = bisect.bisect_right(self.times_us, us(ts)) - 1
        return idx if idx >= 0 else None

    def sample_age_sec(self, ts: datetime, idx: int) -> float:
        return max(0.0, (us(ts) - self.times_us[idx]) / 1_000_000)

    def rolling_ofi(
        self,
        ts: datetime,
        seconds: int,
        *,
        static_only: bool = False,
    ) -> float | None:
        hi = self.index_at(ts)
        if hi is None or self.sample_age_sec(ts, hi) > 2.5:
            return None
        cutoff = us(ts) - seconds * 1_000_000
        lo = bisect.bisect_left(self.times_us, cutoff)
        if hi - lo < 1:
            return None
        # Require reasonable coverage and reject any known sampling gap. The
        # source normally arrives around 1 Hz, but OnUpdate is not a hard clock.
        if self.times_us[lo] > cutoff + 2_500_000:
            return None
        values: list[float] = []
        depths: list[float] = []
        for idx in range(max(1, lo), hi + 1):
            value = self.step_static_ofi[idx] if static_only else self.step_ofi[idx]
            if value is None:
                return None
            values.append(value)
            depths.append(self.depths[idx])
        if not values or not depths:
            return None
        normalizer = sum(depths) / len(depths)
        if not math.isfinite(normalizer) or normalizer <= 0:
            return None
        return sum(values) / normalizer

    def directional_past(self, ts: datetime, side_sign: int, seconds: int) -> float | None:
        end_idx = self.index_at(ts)
        if end_idx is None or self.sample_age_sec(ts, end_idx) > 2.5:
            return None
        prior_target = ts - timedelta(seconds=seconds)
        start_idx = self.index_at(prior_target)
        if start_idx is None:
            return None
        target_age = (us(prior_target) - self.times_us[start_idx]) / 1_000_000
        if target_age > 2.5:
            return None
        return side_sign * (self.mid_ticks[end_idx] - self.mid_ticks[start_idx])

    def latest_queue_imbalance(self, ts: datetime, levels: int) -> float | None:
        idx = self.index_at(ts)
        if idx is None or self.sample_age_sec(ts, idx) > 2.5:
            return None
        return self.queue_imbalance[levels][idx]

    def directional_future(self, ts: datetime, side_sign: int, seconds: int) -> float | None:
        start_idx = self.index_at(ts)
        if start_idx is None or self.sample_age_sec(ts, start_idx) > 2.5:
            return None
        target = ts + timedelta(seconds=seconds)
        end_idx = self.index_at(target)
        if end_idx is None:
            return None
        target_age = (us(target) - self.times_us[end_idx]) / 1_000_000
        if target_age > 2.5:
            return None
        return side_sign * (self.mid_ticks[end_idx] - self.mid_ticks[start_idx])


@dataclass
class TickSeries:
    times_us: list[int]
    signed_prefix: list[float]
    volume_prefix: list[float]

    def imbalance(self, ts: datetime, seconds: int) -> float | None:
        hi = bisect.bisect_right(self.times_us, us(ts))
        lo = bisect.bisect_left(self.times_us, us(ts) - seconds * 1_000_000)
        if hi <= lo:
            return 0.0
        signed = self.signed_prefix[hi] - self.signed_prefix[lo]
        volume = self.volume_prefix[hi] - self.volume_prefix[lo]
        return signed / volume if volume > 0 else 0.0


def parse_session(value: str, default_window: str) -> SessionSpec:
    parts = value.split(":", 2)
    if len(parts) < 2:
        raise argparse.ArgumentTypeError(
            "session must be YYYY-MM-DD:SYMBOL or YYYY-MM-DD:SYMBOL:HH:MM-HH:MM"
        )
    date, symbol = parts[0], parts[1]
    window = parts[2] if len(parts) == 3 else default_window
    try:
        datetime.fromisoformat(date)
        parse_window(date, window)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc
    return SessionSpec(date=date, symbol=symbol, window=window)


def parse_window(date: str, window: str) -> tuple[datetime, datetime]:
    start_s, end_s = window.split("-", 1)
    start = datetime.strptime(f"{date} {start_s}", "%Y-%m-%d %H:%M").replace(tzinfo=NY)
    end = datetime.strptime(f"{date} {end_s}", "%Y-%m-%d %H:%M").replace(tzinfo=NY)
    if end <= start:
        raise ValueError("session window end must be after start")
    return start, end


def finite_positive(value) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return 0.0
    return result if math.isfinite(result) and result > 0 else 0.0


def ofi_step(
    prior_bid_tick: int,
    prior_bid_size: float,
    prior_ask_tick: int,
    prior_ask_size: float,
    bid_tick: int,
    bid_size: float,
    ask_tick: int,
    ask_size: float,
) -> float:
    """Cont-style best-book event contribution between two snapshots."""
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


def static_size_ofi_step(
    prior_bid_tick: int,
    prior_bid_size: float,
    prior_ask_tick: int,
    prior_ask_size: float,
    bid_tick: int,
    bid_size: float,
    ask_tick: int,
    ask_size: float,
) -> float:
    """Queue-size changes only when the corresponding best price is unchanged."""
    value = 0.0
    if bid_tick == prior_bid_tick:
        value += bid_size - prior_bid_size
    if ask_tick == prior_ask_tick:
        value -= ask_size - prior_ask_size
    return value


def self_test() -> None:
    base = dict(
        prior_bid_tick=100,
        prior_bid_size=10.0,
        prior_ask_tick=102,
        prior_ask_size=12.0,
    )
    assert ofi_step(**base, bid_tick=100, bid_size=15, ask_tick=102, ask_size=12) == 5
    assert ofi_step(**base, bid_tick=100, bid_size=10, ask_tick=102, ask_size=18) == -6
    assert ofi_step(**base, bid_tick=101, bid_size=7, ask_tick=102, ask_size=12) == 7
    assert ofi_step(**base, bid_tick=100, bid_size=10, ask_tick=101, ask_size=9) == -9
    assert static_size_ofi_step(**base, bid_tick=100, bid_size=15, ask_tick=102, ask_size=12) == 5
    assert static_size_ofi_step(**base, bid_tick=101, bid_size=20, ask_tick=102, ask_size=12) == 0


def build_snapshot_series(snapshots: pl.DataFrame, gap_threshold_sec: float) -> SnapshotSeries:
    times: list[int] = []
    mids: list[float] = []
    bid_ticks: list[int] = []
    ask_ticks: list[int] = []
    bid_sizes: list[float] = []
    ask_sizes: list[float] = []
    depths: list[float] = []
    steps: list[float | None] = []
    static_steps: list[float | None] = []
    qi: dict[int, list[float]] = {levels: [] for levels in QUEUE_LEVELS}
    gap_us = int(gap_threshold_sec * 1_000_000)

    for row in snapshots.iter_rows(named=True):
        ref_tick = int(row["ref_tick"])
        bid_tick = ref_tick + int(row["bid_offset_0"])
        ask_tick = ref_tick + int(row["ask_offset_0"])
        bid_size = finite_positive(row["bid_size_0"])
        ask_size = finite_positive(row["ask_size_0"])
        if bid_size <= 0 or ask_size <= 0 or bid_tick >= ask_tick:
            continue

        now_us = int(row["timestamp_us"])
        times.append(now_us)
        mids.append((bid_tick + ask_tick) / 2.0)
        bid_ticks.append(bid_tick)
        ask_ticks.append(ask_tick)
        bid_sizes.append(bid_size)
        ask_sizes.append(ask_size)
        depths.append(bid_size + ask_size)

        for levels in QUEUE_LEVELS:
            bid_depth = sum(finite_positive(row[f"bid_size_{idx}"]) for idx in range(levels))
            ask_depth = sum(finite_positive(row[f"ask_size_{idx}"]) for idx in range(levels))
            denom = bid_depth + ask_depth
            qi[levels].append((bid_depth - ask_depth) / denom if denom > 0 else 0.0)

        idx = len(times) - 1
        if idx == 0 or times[idx] - times[idx - 1] > gap_us:
            steps.append(None)
            static_steps.append(None)
        else:
            steps.append(
                ofi_step(
                    bid_ticks[idx - 1],
                    bid_sizes[idx - 1],
                    ask_ticks[idx - 1],
                    ask_sizes[idx - 1],
                    bid_tick,
                    bid_size,
                    ask_tick,
                    ask_size,
                )
            )
            static_steps.append(
                static_size_ofi_step(
                    bid_ticks[idx - 1],
                    bid_sizes[idx - 1],
                    ask_ticks[idx - 1],
                    ask_sizes[idx - 1],
                    bid_tick,
                    bid_size,
                    ask_tick,
                    ask_size,
                )
            )

    if len(times) < 2:
        raise ValueError("insufficient valid snapshot rows")
    return SnapshotSeries(
        times_us=times,
        mid_ticks=mids,
        bid_ticks=bid_ticks,
        ask_ticks=ask_ticks,
        bid_sizes=bid_sizes,
        ask_sizes=ask_sizes,
        depths=depths,
        step_ofi=steps,
        step_static_ofi=static_steps,
        queue_imbalance=qi,
        gap_threshold_us=gap_us,
    )


def load_ticks(
    capture_root: str,
    spec: SessionSpec,
    start: datetime,
    end: datetime,
) -> pl.DataFrame:
    pattern = os.path.join(capture_root, spec.symbol, spec.date, "ticks", "*.parquet")
    files = sorted(glob.glob(pattern))
    if not files:
        raise FileNotFoundError(f"no tick chunks for {spec.label}")
    return (
        pl.scan_parquet(files)
        .select(tick_columns())
        .filter((pl.col("timestamp_us") >= us(start)) & (pl.col("timestamp_us") <= us(end)))
        .collect()
        .sort("timestamp_us")
    )


def build_tick_series(ticks: pl.DataFrame) -> TickSeries:
    times: list[int] = []
    signed_prefix = [0.0]
    volume_prefix = [0.0]
    for row in ticks.iter_rows(named=True):
        size = finite_positive(row["size"])
        sign = int(row["aggressor_sign"] or 0)
        times.append(int(row["timestamp_us"]))
        signed_prefix.append(signed_prefix[-1] + (size * sign if sign else 0.0))
        volume_prefix.append(volume_prefix[-1] + (size if sign else 0.0))
    return TickSeries(times_us=times, signed_prefix=signed_prefix, volume_prefix=volume_prefix)


def replay_args(args, spec: SessionSpec) -> SimpleNamespace:
    return SimpleNamespace(
        window=spec.window,
        warmup_min=args.warmup_min,
        capture_root=args.capture_root,
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
    )


def resolution_sign(episode: DisplacementEpisode) -> int:
    evidence_sign = 1 if episode.evidence_side == "demand" else -1
    return evidence_sign if episode.direction == "favor" else -evidence_sign


def add_metrics(
    row: dict,
    ts: datetime,
    side_sign: int,
    snapshots: SnapshotSeries,
    ticks: TickSeries,
) -> None:
    for seconds in PRESSURE_WINDOWS:
        raw_ofi = snapshots.rolling_ofi(ts, seconds)
        row[f"ofi_{seconds}s"] = raw_ofi
        row[f"aligned_ofi_{seconds}s"] = side_sign * raw_ofi if raw_ofi is not None else None
        raw_static = snapshots.rolling_ofi(ts, seconds, static_only=True)
        row[f"static_ofi_{seconds}s"] = raw_static
        row[f"aligned_static_ofi_{seconds}s"] = (
            side_sign * raw_static if raw_static is not None else None
        )
        row[f"aligned_price_{seconds}s_ticks"] = snapshots.directional_past(
            ts,
            side_sign,
            seconds,
        )
        raw_tfi = ticks.imbalance(ts, seconds)
        row[f"tfi_{seconds}s"] = raw_tfi
        row[f"aligned_tfi_{seconds}s"] = side_sign * raw_tfi if raw_tfi is not None else None
    for levels in QUEUE_LEVELS:
        raw_qi = snapshots.latest_queue_imbalance(ts, levels)
        row[f"qi_{levels}"] = raw_qi
        row[f"aligned_qi_{levels}"] = side_sign * raw_qi if raw_qi is not None else None
    for seconds in FUTURE_HORIZONS:
        row[f"future_net_{seconds}s_ticks"] = snapshots.directional_future(ts, side_sign, seconds)


def episode_rows(
    spec: SessionSpec,
    episodes: list[DisplacementEpisode],
    snapshots: SnapshotSeries,
    ticks: TickSeries,
) -> tuple[list[dict], list[dict]]:
    early: list[dict] = []
    confirmations: list[dict] = []
    for episode in episodes:
        if episode.gap_contaminated or episode.outcome not in ("confirmed", "reset"):
            continue
        side_sign = resolution_sign(episode)
        result_side = "demand" if side_sign > 0 else "supply"
        for lead in EVALUATION_LEADS:
            if episode.duration_sec < lead:
                continue
            anchor = episode.start_ts + timedelta(seconds=lead)
            row = {
                "session": spec.label,
                "phase": "displacement",
                "candidate_id": episode.candidate_id,
                "anchor_et": anchor.astimezone(NY).isoformat(),
                "lead_sec": lead,
                "evidence_side": episode.evidence_side,
                "direction": episode.direction,
                "result_side": result_side,
                "outcome": episode.outcome,
                "duration_sec": episode.duration_sec,
                "event_count": episode.event_count,
                "score": episode.score,
                "kind_count": episode.kind_count,
            }
            add_metrics(row, anchor, side_sign, snapshots, ticks)
            early.append(row)

        if episode.outcome == "confirmed" and episode.end_ts is not None:
            row = {
                "session": spec.label,
                "phase": "confirmation",
                "candidate_id": episode.candidate_id,
                "anchor_et": episode.end_ts.astimezone(NY).isoformat(),
                "lead_sec": episode.duration_sec,
                "evidence_side": episode.evidence_side,
                "direction": episode.direction,
                "result_side": result_side,
                "outcome": episode.outcome,
                "duration_sec": episode.duration_sec,
                "event_count": episode.event_count,
                "score": episode.score,
                "kind_count": episode.kind_count,
            }
            add_metrics(row, episode.end_ts, side_sign, snapshots, ticks)
            confirmations.append(row)
    return early, confirmations


def rank_auc(scores: list[float], labels: list[bool]) -> float | None:
    pairs = sorted(zip(scores, labels), key=lambda item: item[0])
    positives = sum(labels)
    negatives = len(labels) - positives
    if positives == 0 or negatives == 0:
        return None
    rank_sum = 0.0
    index = 0
    while index < len(pairs):
        end = index + 1
        while end < len(pairs) and pairs[end][0] == pairs[index][0]:
            end += 1
        average_rank = ((index + 1) + end) / 2.0
        rank_sum += average_rank * sum(1 for _, label in pairs[index:end] if label)
        index = end
    return (rank_sum - positives * (positives + 1) / 2.0) / (positives * negatives)


def pct(numerator: int, denominator: int) -> float:
    return 100.0 * numerator / denominator if denominator else math.nan


def summarize_binary(rows: list[dict], feature: str, label_fn) -> dict | None:
    usable = [(float(row[feature]), bool(label_fn(row))) for row in rows if row.get(feature) is not None]
    if not usable:
        return None
    scores = [score for score, _ in usable]
    labels = [label for _, label in usable]
    positives = [score for score, label in usable if label]
    negatives = [score for score, label in usable if not label]
    if not positives or not negatives:
        return None
    aligned = [label for score, label in usable if score > 0]
    opposed = [label for score, label in usable if score <= 0]
    aligned_rate = pct(sum(aligned), len(aligned))
    opposed_rate = pct(sum(opposed), len(opposed))
    return {
        "n": len(usable),
        "positive_n": len(positives),
        "negative_n": len(negatives),
        "auc": rank_auc(scores, labels),
        "positive_median": median(positives),
        "negative_median": median(negatives),
        "aligned_n": len(aligned),
        "opposed_n": len(opposed),
        "aligned_rate": aligned_rate,
        "opposed_rate": opposed_rate,
        "lift_pp": aligned_rate - opposed_rate,
    }


def conditional_auc(
    rows: list[dict],
    feature: str,
    control: str,
    label_fn,
    bin_width: float,
) -> tuple[float | None, int, int]:
    """Pairwise AUC only within similar control-value buckets."""
    buckets: dict[int, list[tuple[float, bool]]] = {}
    for row in rows:
        if row.get(feature) is None or row.get(control) is None:
            continue
        bucket = math.floor(float(row[control]) / bin_width)
        buckets.setdefault(bucket, []).append((float(row[feature]), bool(label_fn(row))))
    concordance = 0.0
    pairs = 0
    useful_buckets = 0
    for values in buckets.values():
        positives = [score for score, label in values if label]
        negatives = [score for score, label in values if not label]
        if not positives or not negatives:
            continue
        useful_buckets += 1
        for positive in positives:
            for negative in negatives:
                pairs += 1
                if positive > negative:
                    concordance += 1.0
                elif positive == negative:
                    concordance += 0.5
    return (concordance / pairs if pairs else None), pairs, useful_buckets


def residual_auc(rows: list[dict], feature: str, control: str, label_fn) -> float | None:
    """Remove the feature's linear relation to price before ranking outcomes."""
    values = [
        (float(row[control]), float(row[feature]), bool(label_fn(row)))
        for row in rows
        if row.get(feature) is not None and row.get(control) is not None
    ]
    if len(values) < 3:
        return None
    mean_x = sum(value[0] for value in values) / len(values)
    mean_y = sum(value[1] for value in values) / len(values)
    variance_x = sum((value[0] - mean_x) ** 2 for value in values)
    slope = (
        sum((value[0] - mean_x) * (value[1] - mean_y) for value in values) / variance_x
        if variance_x > 0
        else 0.0
    )
    intercept = mean_y - slope * mean_x
    scores = [value[1] - (intercept + slope * value[0]) for value in values]
    labels = [value[2] for value in values]
    return rank_auc(scores, labels)


def fmt(value, digits: int = 3) -> str:
    if value is None or not math.isfinite(float(value)):
        return "n/a"
    return f"{float(value):.{digits}f}"


def session_auc(rows: list[dict], feature: str, label_fn) -> str:
    cells: list[str] = []
    for session in sorted({row["session"] for row in rows}):
        summary = summarize_binary(
            [row for row in rows if row["session"] == session],
            feature,
            label_fn,
        )
        cells.append(f"{session}={fmt(summary['auc']) if summary else 'n/a'}")
    return ", ".join(cells)


def build_summary(
    specs: list[SessionSpec],
    session_counts: dict[str, tuple[int, int]],
    early: list[dict],
    confirmations: list[dict],
    ear_rows: list[dict],
) -> str:
    lines: list[str] = []
    lines.append("Snapshot OFI proxy exploratory report")
    lines.append("NOT event-level OFI: source is periodic canonical DOM snapshots.")
    lines.append("")
    lines.append("Coverage")
    for spec in specs:
        episodes, confirmed = session_counts[spec.label]
        lines.append(
            f"  {spec.label} {spec.window}: clean resolved displacement episodes={episodes}, "
            f"confirmed={confirmed}"
        )

    lines.append("")
    lines.append("Early confirmation discrimination")
    lines.append(
        "Score is aligned to the episode's eventual resolution side. AUC > 0.5 and positive "
        "lift favor pressure-conditioned confirmation."
    )
    features = [f"aligned_ofi_{window}s" for window in PRESSURE_WINDOWS]
    features += [
        "aligned_static_ofi_5s",
        "aligned_static_ofi_10s",
        "aligned_price_3s_ticks",
        "aligned_price_5s_ticks",
        "aligned_qi_5",
        "aligned_qi_10",
        "aligned_tfi_5s",
        "aligned_tfi_10s",
    ]
    for lead in EVALUATION_LEADS:
        subset = [row for row in early if row["lead_sec"] == lead]
        lines.append(f"  after {lead}s persistence: n={len(subset)}")
        for feature in features:
            summary = summarize_binary(subset, feature, lambda row: row["outcome"] == "confirmed")
            if summary is None:
                continue
            lines.append(
                f"    {feature:<18} auc={fmt(summary['auc'])} "
                f"med confirmed/reset={fmt(summary['positive_median'])}/{fmt(summary['negative_median'])} "
                f"sign lift={fmt(summary['lift_pp'], 1)}pp "
                f"({session_auc(subset, feature, lambda row: row['outcome'] == 'confirmed')})"
            )

    lead_five = [row for row in early if row["lead_sec"] == 5]
    lines.append("")
    lines.append("Increment beyond five-second price progress")
    lines.append(
        "Conditional AUC compares confirmed/reset episodes only within four-tick price-progress "
        "buckets; residual AUC removes a pooled linear price relation."
    )
    for feature in (
        "aligned_ofi_3s",
        "aligned_ofi_5s",
        "aligned_static_ofi_5s",
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
            f"  {feature:<24} conditional_auc={fmt(cond_auc)} pairs={pairs} "
            f"buckets={buckets} residual_auc={fmt(resid_auc)}"
        )

    lines.append("")
    lines.append("Post-confirmation 30-second continuation")
    continuation = [row for row in confirmations if row.get("future_net_30s_ticks") is not None]
    positive = sum(float(row["future_net_30s_ticks"]) > 0 for row in continuation)
    lines.append(
        f"  confirmations with labels={len(continuation)}, directionally positive={positive} "
        f"({pct(positive, len(continuation)):.1f}%)"
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
            f"    {feature:<18} auc={fmt(summary['auc'])} "
            f"med continue/not={fmt(summary['positive_median'])}/{fmt(summary['negative_median'])} "
            f"sign lift={fmt(summary['lift_pp'], 1)}pp "
            f"({session_auc(continuation, feature, lambda row: float(row['future_net_30s_ticks']) > 0)})"
        )

    if ear_rows:
        lines.append("")
        lines.append("June 22 EAR order-submit anchors (descriptive only)")
        for row in ear_rows:
            lines.append(
                f"  {row['time_et']} {row['role']:<9} {row['side']:<5} "
                f"px={row['trigger_price']:.2f} "
                f"aOFI5={fmt(row.get('aligned_ofi_5s'))} "
                f"aOFI10={fmt(row.get('aligned_ofi_10s'))} "
                f"aQI5={fmt(row.get('aligned_qi_5'))} "
                f"aTFI10={fmt(row.get('aligned_tfi_10s'))} "
                f"net30={fmt(row.get('future_net_30s_ticks'), 1)}t"
            )
    return "\n".join(lines) + "\n"


def ear_anchor_rows(
    event_path: str | None,
    series_by_date: dict[str, tuple[SnapshotSeries, TickSeries]],
) -> list[dict]:
    if not event_path or not os.path.exists(event_path):
        return []
    rows: list[dict] = []
    with open(event_path, "r", encoding="utf-8") as stream:
        for line in stream:
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get("event") != "order_submit":
                continue
            trigger = datetime.fromisoformat(event["trigger_utc"].replace("Z", "+00:00"))
            date = trigger.astimezone(NY).date().isoformat()
            series = series_by_date.get(date)
            if series is None:
                continue
            side = event.get("side", "")
            side_sign = 1 if side.lower() == "long" else -1
            trigger_price = float(event["trigger_ask"] if side_sign > 0 else event["trigger_bid"])
            row = {
                "time_et": trigger.astimezone(NY).strftime("%H:%M:%S"),
                "directive_id": event.get("directive_id"),
                "role": event.get("role"),
                "side": side,
                "trigger_price": trigger_price,
                "resolution": event.get("resolution"),
                "root_object_id": event.get("root_object_id"),
            }
            add_metrics(row, trigger, side_sign, series[0], series[1])
            rows.append(row)
    return rows


def write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fields: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for key in row:
            if key not in seen:
                seen.add(key)
                fields.append(key)
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    self_test()
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
    parser.add_argument("--ear-events")
    parser.add_argument("--out-dir", default=str(ROOT / "research" / "out"))
    parser.add_argument("--gap-threshold-sec", type=float, default=5.0)

    # Keep replay defaults explicit so the population matches the live copied
    # LL evidence grammar rather than whatever a future probe happens to use.
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
    session_counts: dict[str, tuple[int, int]] = {}
    series_by_date: dict[str, tuple[SnapshotSeries, TickSeries]] = {}

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
        early, confirmations = episode_rows(spec, replay.episodes, snapshots, ticks)
        all_early.extend(early)
        all_confirmations.extend(confirmations)
        clean_resolved = [
            episode
            for episode in replay.episodes
            if not episode.gap_contaminated and episode.outcome in ("confirmed", "reset")
        ]
        session_counts[spec.label] = (
            len(clean_resolved),
            sum(episode.outcome == "confirmed" for episode in clean_resolved),
        )
        series_by_date[spec.date] = (snapshots, ticks)

    ear_rows = ear_anchor_rows(args.ear_events, series_by_date)
    summary = build_summary(specs, session_counts, all_early, all_confirmations, ear_rows)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    dates = "_".join(spec.date for spec in specs)
    prefix = out_dir / f"snapshot_ofi_proxy_{dates}"
    summary_path = prefix.with_suffix(".txt")
    episodes_path = Path(str(prefix) + "_episodes.csv")
    confirmations_path = Path(str(prefix) + "_confirmations.csv")
    ear_path = Path(str(prefix) + "_ear.csv")
    summary_path.write_text(summary, encoding="utf-8")
    write_csv(episodes_path, all_early)
    write_csv(confirmations_path, all_confirmations)
    write_csv(ear_path, ear_rows)

    print(summary, end="")
    print(f"outputs:\n  {summary_path}\n  {episodes_path}\n  {confirmations_path}\n  {ear_path}")


if __name__ == "__main__":
    main()
