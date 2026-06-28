"""Episode-scoped T3 lifecycle probe.

This is the second Terrain/Road pass from the Skurry Now Lens research thread.
The first pass asked, broadly, what sits beyond every synthetic LL/EAR failure
or consumed row. This pass anchors only inside curated fixture windows and
labels the lifecycle first:

- good/weak tests;
- true failures;
- fake failures / same-side renewal;
- failure into balance;
- consumed conversion quality.

Terrain, approach tape, and move-away tape are explanatory features. They are
not the target.
"""

from __future__ import annotations

import argparse
import bisect
import csv
import glob
import json
import math
import os
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from statistics import median
from typing import Any, Iterable

import polars as pl


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
RESEARCH = ROOT / "research"
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(RESEARCH))

from candidate_timing_probe import CandidateTimingProbe, load_filtered_snapshots  # noqa: E402
from capture_loader import MARKET_RECORDER_ROOT, load_capture_window, tick_columns, us  # noqa: E402
from ownership_bands_probe import Transition, opposite  # noqa: E402
from replay_levelledger import (  # noqa: E402
    BOOK_LOOKBACK_SEC,
    EVENT_Z_THRESHOLD,
    abbrev,
    build_sample,
    ny_hms,
    parse_ny,
    snapshot_timing_summary,
)
from terrain_band_probe import SnapshotSeries, delta_bin, metric_set, road_bin  # noqa: E402


DEFAULT_SPEC = RESEARCH / "band_lifecycle_fixture_specs_2026-06-23_2026-06-26.json"
DEFAULT_VERIFIED = RESEARCH / "out" / "band_lifecycle_verified_episode_chunks_20260623_20260626.csv"
DEFAULT_OUTPUT_DIR = RESEARCH / "out"
TICK_CHUNK_RE = re.compile(r"^ticks-(\d{6})-(\d{6})(?:-p\d+)?\.parquet$")


PRIMARY_DEV = {
    "20260624_1055_1110_supply_transition",
    "20260625_1215_1230_supply_burst",
}
DIR_CHURN = {
    "20260623_1000_1130_supply_claims",
    "20260623_1330_1600_supply_resolution",
    "20260624_1210_1600_supply_owned",
    "20260626_1310_1500_supply_directional",
}
BALANCE_COUNTER = {
    "20260624_0930_1055_rotational",
    "20260624_1110_1210_repair",
    "20260625_1000_1055_repair_balance",
    "20260623_1130_1330_repair_balance_dcs",
    "20260626_0930_1145_no_build_up_contested_supply",
}
NO_BUILD_CAUTION = {
    "20260625_0930_1000_no_build_liquidation",
    "20260626_1145_1150_supply_build",
    "20260623_0930_1000_no_build_up",
}
REVIEW_HOLDOUT = {
    "20260625_1425_1545_supply_into_close",
    "20260626_1305_1310_supply_test_survived",
    "20260625_1055_1110_supply_burst",
}


@dataclass(frozen=True)
class FixtureSpec:
    id: str
    date: str
    symbol: str
    window: str
    capture_root: str
    memory_label: str
    expected_type: str
    expected_side: str
    notes: str

    @property
    def session(self) -> str:
        return f"{self.date}:{self.symbol}"


@dataclass(frozen=True)
class FixtureMeta:
    verified_label: str = ""
    recommended_use: str = ""
    confidence: str = ""
    dominant_side: str = ""
    snapshot_gaps: str = ""


@dataclass
class ReplayRun:
    spec: FixtureSpec
    meta: FixtureMeta
    curated_bucket: str
    window_start: datetime
    window_end: datetime
    replay_end: datetime
    probe: CandidateTimingProbe
    snapshots: pl.DataFrame
    ticks: pl.DataFrame
    snapshot_gaps: int


class PriceIndex:
    def __init__(self, snapshots: pl.DataFrame) -> None:
        rows = snapshots.sort("timestamp_us").select(["timestamp_us", "ref_tick"])
        self.times = [int(row["timestamp_us"]) for row in rows.iter_rows(named=True)]
        self.ticks = [int(row["ref_tick"]) for row in rows.iter_rows(named=True)]

    def stats(self, start: datetime, end: datetime, side: str) -> dict[str, float | int | None]:
        lo = bisect.bisect_left(self.times, us(start))
        hi = bisect.bisect_right(self.times, us(end))
        values = self.ticks[lo:hi]
        if not values:
            return {
                "start_tick": None,
                "end_tick": None,
                "range_ticks": 0,
                "net_aligned_ticks": 0,
                "max_aligned_ticks": 0,
                "max_adverse_ticks": 0,
                "speed_ticks_per_sec": 0.0,
            }
        sign = 1 if side == "demand" else -1
        start_tick = values[0]
        end_tick = values[-1]
        aligned = [(value - start_tick) * sign for value in values]
        duration = max(0.001, (end - start).total_seconds())
        return {
            "start_tick": start_tick,
            "end_tick": end_tick,
            "range_ticks": max(values) - min(values),
            "net_aligned_ticks": (end_tick - start_tick) * sign,
            "max_aligned_ticks": max(aligned),
            "max_adverse_ticks": max(-value for value in aligned),
            "speed_ticks_per_sec": ((end_tick - start_tick) * sign) / duration,
        }


class TapeIndex:
    def __init__(self, ticks: pl.DataFrame) -> None:
        self.times: list[int] = []
        self.buy_prefix: list[float] = [0.0]
        self.sell_prefix: list[float] = [0.0]
        buy = 0.0
        sell = 0.0
        for row in ticks.sort("timestamp_us").iter_rows(named=True):
            ts_us = int(row["timestamp_us"])
            size = float(row["size"])
            sign = int(row["aggressor_sign"])
            if not math.isfinite(size) or size <= 0:
                continue
            self.times.append(ts_us)
            if sign > 0:
                buy += size
            elif sign < 0:
                sell += size
            self.buy_prefix.append(buy)
            self.sell_prefix.append(sell)

    def stats(self, start: datetime, end: datetime, side: str) -> dict[str, float]:
        lo = bisect.bisect_left(self.times, us(start))
        hi = bisect.bisect_right(self.times, us(end))
        buy = self.buy_prefix[hi] - self.buy_prefix[lo]
        sell = self.sell_prefix[hi] - self.sell_prefix[lo]
        aligned = buy if side == "demand" else sell
        opposed = sell if side == "demand" else buy
        total = buy + sell
        duration = max(0.001, (end - start).total_seconds())
        return {
            "buy_vol": buy,
            "sell_vol": sell,
            "total_vol": total,
            "aligned_vol": aligned,
            "opposed_vol": opposed,
            "aligned_share": aligned / total if total > 0 else 0.0,
            "delta": buy - sell,
            "aligned_delta": (buy - sell) if side == "demand" else (sell - buy),
            "volume_per_sec": total / duration,
        }


def parse_window(date: str, window: str) -> tuple[datetime, datetime]:
    start_s, end_s = window.split("-", 1)
    return parse_ny(date, start_s), parse_ny(date, end_s)


def _hms(value: str) -> str:
    return f"{value[0:2]}:{value[2:4]}:{value[4:6]}"


def load_filtered_ticks(
    capture_root: str,
    symbol: str,
    date: str,
    start: datetime,
    end: datetime,
) -> pl.DataFrame:
    pattern = os.path.join(capture_root, symbol, date, "ticks", "*.parquet")
    selected: list[str] = []
    for path in sorted(glob.glob(pattern)):
        match = TICK_CHUNK_RE.match(os.path.basename(path))
        if match is None:
            continue
        chunk_start = parse_ny(date, _hms(match.group(1)))
        chunk_end = parse_ny(date, _hms(match.group(2)))
        if chunk_end < start or chunk_start > end:
            continue
        selected.append(path)

    if not selected and capture_root == MARKET_RECORDER_ROOT:
        return load_capture_window(
            "ticks",
            symbol,
            start,
            end,
            tick_columns(),
            inclusive_end=True,
        )
    if not selected:
        raise FileNotFoundError(f"no tick chunks for {symbol} {date} under {capture_root}")

    lo = us(start)
    hi = us(end)
    return (
        pl.scan_parquet(selected)
        .select(tick_columns())
        .filter((pl.col("timestamp_us") >= lo) & (pl.col("timestamp_us") <= hi))
        .collect()
        .sort("timestamp_us")
    )


def load_specs(path: Path) -> list[FixtureSpec]:
    return [FixtureSpec(**item) for item in json.loads(path.read_text(encoding="utf-8"))]


def load_verified(path: Path) -> dict[str, FixtureMeta]:
    if not path.exists():
        return {}
    out: dict[str, FixtureMeta] = {}
    with path.open("r", newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            out[row["id"]] = FixtureMeta(
                verified_label=row.get("verified_label", ""),
                recommended_use=row.get("recommended_use", ""),
                confidence=row.get("confidence", ""),
                dominant_side=row.get("dominant_side", ""),
                snapshot_gaps=row.get("snapshot_gaps", ""),
            )
    return out


def curated_bucket(fixture_id: str, meta: FixtureMeta) -> str:
    if fixture_id in PRIMARY_DEV:
        return "primary_dev"
    if fixture_id in DIR_CHURN:
        return "directional_churn_stress"
    if fixture_id in BALANCE_COUNTER:
        return "balance_counter"
    if fixture_id in NO_BUILD_CAUTION:
        return "no_build_caution"
    if fixture_id in REVIEW_HOLDOUT:
        return "review_holdout"
    return meta.recommended_use or "unclassified"


def range_distance(left_min: int, left_max: int, right_min: int, right_max: int) -> int:
    if left_max < right_min:
        return right_min - left_max
    if right_max < left_min:
        return left_min - right_max
    return 0


def center_tick(tr: Transition) -> float:
    return (tr.min_tick + tr.max_tick) / 2.0


def relevant_near(origin: Transition, candidate: Transition, max_distance_ticks: int) -> bool:
    if candidate.ts <= origin.ts:
        return False
    return range_distance(
        origin.min_tick,
        origin.max_tick,
        candidate.min_tick,
        candidate.max_tick,
    ) <= max_distance_ticks


def same_side_beyond_failure(origin: Transition, candidate: Transition, args: argparse.Namespace) -> bool:
    if candidate.side != origin.side:
        return False
    if candidate.action not in ("OWNED", "CONSUMED", "HOLD"):
        return False
    if not relevant_near(origin, candidate, args.renewal_ticks):
        return False
    if (candidate.ts - origin.ts).total_seconds() > args.renewal_sec:
        return False
    if origin.side == "supply":
        return center_tick(candidate) >= origin.max_tick
    return center_tick(candidate) <= origin.min_tick


def first_relevant_after(
    origin: Transition,
    transitions: Iterable[Transition],
    *,
    max_sec: int,
    max_distance_ticks: int,
) -> Transition | None:
    until = origin.ts + timedelta(seconds=max_sec)
    for tr in sorted(transitions, key=lambda item: item.ts):
        if tr.ts <= origin.ts or tr.ts > until:
            continue
        if relevant_near(origin, tr, max_distance_ticks):
            return tr
    return None


def structure_after(
    origin: Transition,
    transitions: Iterable[Transition],
    side: str,
    args: argparse.Namespace,
) -> tuple[str, Transition | None]:
    other = opposite(side)
    until = origin.ts + timedelta(seconds=args.structure_lookahead_sec)
    first_continuation: Transition | None = None
    for tr in sorted(transitions, key=lambda item: item.ts):
        if tr.ts <= origin.ts or tr.ts > until:
            continue
        if not relevant_near(origin, tr, args.structure_distance_ticks):
            continue
        if tr.action == "FAIL" and tr.side == other:
            return "side_destroyed_opposite", tr
        if tr.action in ("OWNED", "CONSUMED", "HOLD") and tr.side == side:
            if first_continuation is None:
                first_continuation = tr
            continue
        if tr.action in ("OWNED", "CONSUMED", "HOLD") and tr.side == other:
            return "opposition_renewed", tr
        if tr.action == "FAIL" and tr.side == side:
            return "side_failed", tr
    if first_continuation is not None:
        return "side_continued", first_continuation
    return "no_structural_followthrough", None


def classify_failure(
    fail: Transition,
    transitions: list[Transition],
    args: argparse.Namespace,
) -> tuple[str, str, Transition | None]:
    sponsor_side = fail.side
    break_side = opposite(sponsor_side)
    until = fail.ts + timedelta(seconds=args.structure_lookahead_sec)
    same_side_renewal: Transition | None = None
    break_consequence: Transition | None = None
    balance_events = 0

    for tr in sorted(transitions, key=lambda item: item.ts):
        if tr.ts <= fail.ts or tr.ts > until:
            continue
        if not relevant_near(fail, tr, args.structure_distance_ticks):
            continue
        if tr.side in (sponsor_side, break_side) and tr.action in ("OWNED", "CONSUMED", "HOLD", "FAIL"):
            balance_events += 1
        if same_side_renewal is None and same_side_beyond_failure(fail, tr, args):
            same_side_renewal = tr
        if break_consequence is None:
            if tr.action in ("OWNED", "CONSUMED") and tr.side == break_side:
                break_consequence = tr
            elif tr.action == "FAIL" and tr.side == sponsor_side:
                break_consequence = tr
        if same_side_renewal is not None and break_consequence is not None:
            break

    if same_side_renewal is not None and (
        break_consequence is None or same_side_renewal.ts <= break_consequence.ts
    ):
        return "fake_failure_same_side_renewal", "same_side_renewal", same_side_renewal
    if break_consequence is not None:
        return "terminal_failure", "break_side_consequence", break_consequence
    if balance_events >= args.balance_event_min:
        return "failure_into_balance", "two_sided_churn", first_relevant_after(
            fail,
            transitions,
            max_sec=args.structure_lookahead_sec,
            max_distance_ticks=args.structure_distance_ticks,
        )
    return "no_structural_followthrough", "none", None


def classify_test(
    test: Transition,
    transitions: list[Transition],
    args: argparse.Namespace,
) -> tuple[str, str, Transition | None]:
    same_band = [
        tr for tr in transitions
        if tr.band_id == test.band_id and tr.ts > test.ts
    ]
    until = test.ts + timedelta(seconds=args.test_outcome_sec)
    same_band = [tr for tr in same_band if tr.ts <= until]
    first_hold = next((tr for tr in same_band if tr.action == "HOLD"), None)
    first_fail = next((tr for tr in same_band if tr.action == "FAIL"), None)

    if first_fail is not None and (first_hold is None or first_fail.ts < first_hold.ts):
        label, reason, evidence = classify_failure(first_fail, transitions, args)
        return label, f"test_to_{reason}", evidence or first_fail

    if first_hold is not None:
        outcome, evidence = structure_after(first_hold, transitions, test.side, args)
        if outcome == "side_destroyed_opposite":
            return "clean_hold", outcome, evidence or first_hold
        if outcome == "side_continued":
            return "weak_hold_same_side_continued", outcome, evidence or first_hold
        if outcome == "opposition_renewed":
            return "weak_hold_opposition_renewed", outcome, evidence
        return "weak_hold", outcome, evidence or first_hold

    outcome, evidence = structure_after(test, transitions, test.side, args)
    if outcome == "side_failed":
        return "terminal_failure", outcome, evidence
    if outcome == "opposition_renewed":
        return "tested_not_disproved", outcome, evidence
    return "tested_not_disproved", outcome, evidence


def classify_consumed(
    consumed: Transition,
    transitions: list[Transition],
    args: argparse.Namespace,
) -> tuple[str, str, Transition | None]:
    outcome, evidence = structure_after(consumed, transitions, consumed.side, args)
    if outcome in ("side_destroyed_opposite", "side_continued"):
        return "direct_conversion_with_followthrough", outcome, evidence
    if outcome == "opposition_renewed":
        return "failed_or_churn_conversion", outcome, evidence
    if outcome == "side_failed":
        return "failed_or_churn_conversion", outcome, evidence
    return "conversion_no_followthrough", outcome, evidence


def anchor_sides(tr: Transition) -> tuple[str, str, str]:
    if tr.action == "TEST":
        return "band_test", opposite(tr.side), tr.side
    if tr.action == "FAIL":
        return "band_failure", opposite(tr.side), opposite(tr.side)
    if tr.action == "CONSUMED":
        return "consumed_conversion", tr.side, tr.side
    raise ValueError(f"unsupported transition action {tr.action}")


def load_replay(args: argparse.Namespace, spec: FixtureSpec, meta: FixtureMeta) -> ReplayRun:
    window_start, window_end = parse_window(spec.date, spec.window)
    replay_start = window_start - timedelta(minutes=args.warmup_min)
    replay_end = window_end + timedelta(seconds=max(args.structure_lookahead_sec, args.moveaway_sec) + args.snapshot_max_age_sec)
    snapshots = load_filtered_snapshots(
        spec.capture_root,
        spec.symbol,
        spec.date,
        replay_start,
        replay_end,
    )
    ticks = load_filtered_ticks(
        spec.capture_root,
        spec.symbol,
        spec.date,
        replay_start,
        replay_end,
    )
    _, _, _, gaps = snapshot_timing_summary(snapshots, args.gap_threshold_sec)
    probe = CandidateTimingProbe(
        session=spec.session,
        gap_threshold_sec=args.gap_threshold_sec,
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
    for row in snapshots.iter_rows(named=True):
        probe.on_sample(build_sample(row))
    probe.finish(replay_end)
    return ReplayRun(
        spec=spec,
        meta=meta,
        curated_bucket=curated_bucket(spec.id, meta),
        window_start=window_start,
        window_end=window_end,
        replay_end=replay_end,
        probe=probe,
        snapshots=snapshots,
        ticks=ticks,
        snapshot_gaps=len(gaps),
    )


def terrain_features(
    series: SnapshotSeries,
    tr: Transition,
    break_side: str,
    args: argparse.Namespace,
) -> dict[str, object]:
    before_row, before_age = series.at_or_before(tr.ts - timedelta(seconds=args.before_sec))
    after_row, after_age = series.at_or_after(tr.ts + timedelta(seconds=args.after_sec))
    if before_row is None or after_row is None:
        return {
            "terrain_available": False,
            "before_age_sec": before_age,
            "after_age_sec": after_age,
        }
    before = metric_set(before_row, break_side, tr.min_tick, tr.max_tick, args)
    after = metric_set(after_row, break_side, tr.min_tick, tr.max_tick, args)
    ahead_delta = float(after["ahead_sum"] or 0.0) - float(before["ahead_sum"] or 0.0)
    support_delta = float(after["support_sum"] or 0.0) - float(before["support_sum"] or 0.0)
    out: dict[str, object] = {
        "terrain_available": True,
        "before_age_sec": before_age,
        "after_age_sec": after_age,
        "road_bin": road_bin(after, args),
        "opposition_book_bin": delta_bin(ahead_delta, args.build_min_delta),
        "support_book_bin": delta_bin(support_delta, args.build_min_delta),
        "ahead_delta": ahead_delta,
        "support_delta": support_delta,
    }
    for prefix, values in (("before", before), ("after", after)):
        for key, value in values.items():
            out[f"{prefix}_{key}"] = value
    return out


def add_prefixed(row: dict[str, object], prefix: str, values: dict[str, object]) -> None:
    for key, value in values.items():
        row[f"{prefix}_{key}"] = value


def transition_price(tr: Transition) -> str:
    return abbrev((tr.min_tick + tr.max_tick) // 2)


def probe_rows(run: ReplayRun, args: argparse.Namespace) -> list[dict[str, object]]:
    transitions = sorted(run.probe.transitions, key=lambda item: item.ts)
    anchors = [
        tr for tr in transitions
        if run.window_start <= tr.ts <= run.window_end
        and tr.action in ("TEST", "FAIL", "CONSUMED")
    ]
    series = SnapshotSeries(run.snapshots, args.snapshot_max_age_sec)
    price = PriceIndex(run.snapshots)
    tape = TapeIndex(run.ticks)
    rows: list[dict[str, object]] = []

    for tr in anchors:
        anchor_class, break_side, moveaway_side = anchor_sides(tr)
        if tr.action == "TEST":
            lifecycle_label, lifecycle_reason, evidence = classify_test(tr, transitions, args)
            moveaway_side = tr.side if lifecycle_label in ("clean_hold", "weak_hold", "weak_hold_opposition_renewed") else break_side
        elif tr.action == "FAIL":
            lifecycle_label, lifecycle_reason, evidence = classify_failure(tr, transitions, args)
        else:
            lifecycle_label, lifecycle_reason, evidence = classify_consumed(tr, transitions, args)

        approach_start = max(run.window_start, tr.ts - timedelta(seconds=args.approach_sec))
        move_end = min(run.replay_end, tr.ts + timedelta(seconds=args.moveaway_sec))
        terrain = terrain_features(series, tr, break_side, args)

        row: dict[str, object] = {
            "fixture_id": run.spec.id,
            "session": run.spec.session,
            "date": run.spec.date,
            "symbol": run.spec.symbol,
            "window": run.spec.window,
            "curated_bucket": run.curated_bucket,
            "memory_label": run.spec.memory_label,
            "expected_type": run.spec.expected_type,
            "expected_side": run.spec.expected_side,
            "verified_label": run.meta.verified_label,
            "recommended_use": run.meta.recommended_use,
            "dominant_side": run.meta.dominant_side,
            "snapshot_gaps": run.snapshot_gaps,
            "anchor_ts": tr.ts.isoformat(),
            "anchor_ny": ny_hms(tr.ts),
            "anchor_class": anchor_class,
            "transition_action": tr.action,
            "band_id": tr.band_id,
            "band_side": tr.side,
            "break_side": break_side,
            "moveaway_side": moveaway_side,
            "source": tr.source,
            "band_price": transition_price(tr),
            "min_tick": tr.min_tick,
            "max_tick": tr.max_tick,
            "current_mid_tick": tr.current_mid_tick,
            "event_count": tr.event_count,
            "score": tr.score,
            "max_abs_z": tr.max_abs_z,
            "lifecycle_label": lifecycle_label,
            "lifecycle_reason": lifecycle_reason,
            "evidence_action": evidence.action if evidence is not None else "",
            "evidence_side": evidence.side if evidence is not None else "",
            "evidence_ny": ny_hms(evidence.ts) if evidence is not None else "",
            "evidence_delay_sec": (evidence.ts - tr.ts).total_seconds() if evidence is not None else "",
            "evidence_price": transition_price(evidence) if evidence is not None else "",
        }
        row.update(terrain)
        add_prefixed(row, "approach_price", price.stats(approach_start, tr.ts, break_side))
        add_prefixed(row, "moveaway_price", price.stats(tr.ts, move_end, moveaway_side))
        add_prefixed(row, "approach_tape", tape.stats(approach_start, tr.ts, break_side))
        add_prefixed(row, "moveaway_tape", tape.stats(tr.ts, move_end, moveaway_side))
        rows.append(row)
    return rows


def pct(value: int, total: int) -> str:
    if total <= 0:
        return "n/a"
    return f"{100.0 * value / total:.1f}%"


def summarize(rows: list[dict[str, object]], fields: list[str], outcome_field: str = "lifecycle_label") -> list[str]:
    groups: dict[tuple[str, ...], Counter[str]] = defaultdict(Counter)
    for row in rows:
        key = tuple(str(row.get(field, "")) for field in fields)
        groups[key][str(row.get(outcome_field, ""))] += 1
    if not groups:
        return ["No rows."]
    outcomes = sorted({outcome for counter in groups.values() for outcome in counter})
    lines = [
        "| " + " | ".join(fields) + " | n | " + " | ".join(outcomes) + " |",
        "| " + " | ".join("---" for _ in fields) + " | ---: | " + " | ".join("---:" for _ in outcomes) + " |",
    ]
    for key in sorted(groups):
        counter = groups[key]
        total = sum(counter.values())
        cells = [f"{counter[outcome]} ({pct(counter[outcome], total)})" for outcome in outcomes]
        lines.append("| " + " | ".join(key) + f" | {total} | " + " | ".join(cells) + " |")
    return lines


def numeric_summary(rows: list[dict[str, object]], field: str) -> str:
    values = [
        float(row[field])
        for row in rows
        if field in row and row[field] not in ("", None) and math.isfinite(float(row[field]))
    ]
    if not values:
        return "n/a"
    ordered = sorted(values)
    p25 = ordered[min(len(ordered) - 1, max(0, math.ceil(0.25 * len(ordered)) - 1))]
    p75 = ordered[min(len(ordered) - 1, math.ceil(0.75 * len(ordered)) - 1)]
    return f"n={len(values)} median={median(values):.2f} p25={p25:.2f} p75={p75:.2f}"


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = sorted({key for row in rows for key in row})
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def example_rows(rows: list[dict[str, object]], limit: int = 24) -> list[str]:
    selected = sorted(
        rows,
        key=lambda row: (
            str(row.get("curated_bucket", "")),
            str(row.get("fixture_id", "")),
            str(row.get("anchor_ny", "")),
        ),
    )[:limit]
    lines = [
        "| fixture | time | anchor | side | terrain | opp book | label | evidence |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in selected:
        evidence = ""
        if row.get("evidence_action"):
            evidence = f"{row.get('evidence_ny')} {row.get('evidence_action')} {row.get('evidence_side')}@{row.get('evidence_price')}"
        lines.append(
            f"| `{row.get('fixture_id')}` | {row.get('anchor_ny')} | "
            f"{row.get('anchor_class')}@{row.get('band_price')} | "
            f"{row.get('band_side')}->{row.get('break_side')} | "
            f"`{row.get('road_bin', '')}` | `{row.get('opposition_book_bin', '')}` | "
            f"`{row.get('lifecycle_label')}` | {evidence} |"
        )
    return lines


def write_report(path: Path, rows: list[dict[str, object]], runs: list[ReplayRun], args: argparse.Namespace) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    failures = [row for row in rows if row.get("anchor_class") == "band_failure"]
    tests = [row for row in rows if row.get("anchor_class") == "band_test"]
    conversions = [row for row in rows if row.get("anchor_class") == "consumed_conversion"]
    primary = [row for row in rows if row.get("curated_bucket") == "primary_dev"]
    lines = [
        "# Episode Terrain Lifecycle Probe",
        "",
        "Fixture-scoped T3 pass. Labels are ownership lifecycle outcomes; terrain and tape are explanatory features.",
        "",
        "## Sessions",
        "",
    ]
    for run in runs:
        lines.append(
            f"- `{run.spec.id}` `{run.spec.session}` `{run.spec.window}` bucket=`{run.curated_bucket}` "
            f"transitions={len(run.probe.transitions)} anchors={sum(1 for row in rows if row['fixture_id'] == run.spec.id)} "
            f"snapshot_gaps={run.snapshot_gaps}"
        )

    lines.extend(
        [
            "",
            "## Counts",
            "",
            f"- anchor rows: `{len(rows)}`",
            f"- tests: `{len(tests)}`",
            f"- failures: `{len(failures)}`",
            f"- consumed conversions: `{len(conversions)}`",
            "",
            "## Lifecycle By Fixture Bucket",
            "",
        ]
    )
    lines.extend(summarize(rows, ["curated_bucket", "anchor_class"]))
    lines.extend(["", "## Failure Labels By Road And Opposing Book", ""])
    lines.extend(summarize(failures, ["road_bin", "opposition_book_bin"]))
    lines.extend(["", "## Test Labels By Road And Opposing Book", ""])
    lines.extend(summarize(tests, ["road_bin", "opposition_book_bin"]))
    lines.extend(["", "## Conversion Labels By Road And Opposing Book", ""])
    lines.extend(summarize(conversions, ["road_bin", "opposition_book_bin"]))
    lines.extend(["", "## Primary Development Fixture Labels", ""])
    lines.extend(summarize(primary, ["fixture_id", "anchor_class"]))

    lines.extend(
        [
            "",
            "## Metric Sketch",
            "",
            "These summaries are descriptive only. The labels above remain structural ownership outcomes.",
            "",
            f"- clean_hold approach aligned tape share: {numeric_summary([r for r in tests if r.get('lifecycle_label') == 'clean_hold'], 'approach_tape_aligned_share')}",
            f"- weak_hold approach aligned tape share: {numeric_summary([r for r in tests if str(r.get('lifecycle_label', '')).startswith('weak_hold')], 'approach_tape_aligned_share')}",
            f"- terminal_failure approach aligned tape share: {numeric_summary([r for r in rows if r.get('lifecycle_label') == 'terminal_failure'], 'approach_tape_aligned_share')}",
            f"- fake_failure approach aligned tape share: {numeric_summary([r for r in rows if r.get('lifecycle_label') == 'fake_failure_same_side_renewal'], 'approach_tape_aligned_share')}",
            f"- clean_hold move-away speed: {numeric_summary([r for r in tests if r.get('lifecycle_label') == 'clean_hold'], 'moveaway_price_speed_ticks_per_sec')}",
            f"- weak_hold move-away speed: {numeric_summary([r for r in tests if str(r.get('lifecycle_label', '')).startswith('weak_hold')], 'moveaway_price_speed_ticks_per_sec')}",
            f"- terminal_failure move-away speed: {numeric_summary([r for r in rows if r.get('lifecycle_label') == 'terminal_failure'], 'moveaway_price_speed_ticks_per_sec')}",
            f"- fake_failure move-away speed: {numeric_summary([r for r in rows if r.get('lifecycle_label') == 'fake_failure_same_side_renewal'], 'moveaway_price_speed_ticks_per_sec')}",
            "",
            "## Example Rows",
            "",
        ]
    )
    lines.extend(example_rows(rows))
    lines.extend(
        [
            "",
            "## Parameters",
            "",
            f"- approach_sec: `{args.approach_sec}`",
            f"- moveaway_sec: `{args.moveaway_sec}`",
            f"- before_sec / after_sec: `{args.before_sec}` / `{args.after_sec}`",
            f"- ahead_ticks / support_ticks: `{args.ahead_ticks}` / `{args.support_ticks}`",
            f"- structure_lookahead_sec: `{args.structure_lookahead_sec}`",
            f"- structure_distance_ticks: `{args.structure_distance_ticks}`",
            f"- renewal_sec / renewal_ticks: `{args.renewal_sec}` / `{args.renewal_ticks}`",
            f"- test_outcome_sec: `{args.test_outcome_sec}`",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--spec", default=str(DEFAULT_SPEC))
    parser.add_argument("--verified", default=str(DEFAULT_VERIFIED))
    parser.add_argument("--fixture-id", action="append", default=[])
    parser.add_argument("--bucket", action="append", default=[])
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--tag", default="20260623_20260626")
    parser.add_argument("--warmup-min", type=int, default=90)
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
    parser.add_argument("--fail-confirm-ticks", type=int, default=24)
    parser.add_argument("--fail-sec", type=int, default=20)
    parser.add_argument("--hold-confirm-ticks", type=int, default=10)
    parser.add_argument("--gap-threshold-sec", type=float, default=5.0)
    parser.add_argument("--snapshot-max-age-sec", type=float, default=2.5)
    parser.add_argument("--before-sec", type=float, default=5.0)
    parser.add_argument("--after-sec", type=float, default=2.0)
    parser.add_argument("--approach-sec", type=int, default=120)
    parser.add_argument("--moveaway-sec", type=int, default=120)
    parser.add_argument("--ahead-ticks", type=int, default=20)
    parser.add_argument("--support-ticks", type=int, default=8)
    parser.add_argument("--wall-min-size", type=float, default=7.0)
    parser.add_argument("--vacuum-size-max", type=float, default=1.0)
    parser.add_argument("--immediate-wall-ticks", type=int, default=5)
    parser.add_argument("--open-vacuum-frac", type=float, default=0.35)
    parser.add_argument("--open-mean-max", type=float, default=2.5)
    parser.add_argument("--build-min-delta", type=float, default=8.0)
    parser.add_argument("--structure-lookahead-sec", type=int, default=600)
    parser.add_argument("--structure-distance-ticks", type=int, default=80)
    parser.add_argument("--renewal-sec", type=int, default=180)
    parser.add_argument("--renewal-ticks", type=int, default=40)
    parser.add_argument("--test-outcome-sec", type=int, default=600)
    parser.add_argument("--balance-event-min", type=int, default=4)
    args = parser.parse_args()

    verified = load_verified(Path(args.verified))
    specs = load_specs(Path(args.spec))
    selected: list[FixtureSpec] = []
    for spec in specs:
        meta = verified.get(spec.id, FixtureMeta())
        bucket = curated_bucket(spec.id, meta)
        if args.fixture_id and spec.id not in args.fixture_id:
            continue
        if args.bucket and bucket not in args.bucket:
            continue
        selected.append(spec)

    rows: list[dict[str, object]] = []
    runs: list[ReplayRun] = []
    for spec in selected:
        meta = verified.get(spec.id, FixtureMeta())
        print(f"replaying {spec.id} {spec.session} {spec.window}", flush=True)
        run = load_replay(args, spec, meta)
        runs.append(run)
        rows.extend(probe_rows(run, args))

    out_dir = Path(args.output_dir)
    csv_path = out_dir / f"episode_terrain_lifecycle_probe_{args.tag}.csv"
    report_path = out_dir / f"episode_terrain_lifecycle_probe_{args.tag}.md"
    write_csv(csv_path, rows)
    write_report(report_path, rows, runs, args)
    print(f"wrote {csv_path}")
    print(f"wrote {report_path}")


if __name__ == "__main__":
    main()
