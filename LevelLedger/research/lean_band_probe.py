"""Replay Skurry-style Lean against LL/EAR ownership outcomes.

This is a Thesis 1 probe for the Skurry Now Lens research note. It does not
measure "price after N seconds" as the primary outcome. It attaches top-of-book
Lean to the current synthetic LevelLedger ownership lifecycle and asks whether
Lean helps classify:

- baseline candidates that become same-side bands, consumed bands, or unresolved
- consumed/direct-conversion observations
- normal and consumed band tests that hold or fail
- relaxed near-miss candidates that current gates skipped
- current x-ticks / y-seconds qualification stability
"""

from __future__ import annotations

import argparse
import bisect
import csv
import glob
import math
import os
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Iterable

import polars as pl


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
RESEARCH = ROOT / "research"
MR_RESEARCH = ROOT / "MarketRecorder" / "research"
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(RESEARCH))
sys.path.insert(0, str(MR_RESEARCH))

from candidate_timing_probe import (  # noqa: E402
    CandidateTimingProbe,
    ExplicitConversionObservation,
    PERSISTENCE_THRESHOLDS,
    ReclaimCandidateObservation,
    load_filtered_snapshots,
)
from capture_loader import MARKET_RECORDER_ROOT, us  # noqa: E402
from ownership_bands_probe import CandidateBand, OwnershipBand, Transition, opposite  # noqa: E402
from replay_levelledger import (  # noqa: E402
    BOOK_LOOKBACK_SEC,
    EVENT_Z_THRESHOLD,
    build_sample,
    ny_hms,
    parse_ny,
    snapshot_timing_summary,
)
from validate_book_events import (  # noqa: E402
    DELTA,
    GAP,
    RESET_BEGIN,
    BookReplay,
    event_files_with_carry,
)


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
CHUNK_PART_RE = re.compile(r"-p\d+(?=\.parquet$)")
TICK_SIZE = 0.25
DEFAULT_OUTPUT_DIR = ROOT / "research" / "out"


@dataclass(frozen=True)
class SessionSpec:
    date: str
    symbol: str
    window: str

    @property
    def label(self) -> str:
        return f"{self.date}:{self.symbol}"


@dataclass(frozen=True)
class LeanSample:
    ts_us: int
    raw: float
    smooth: float
    bid_tick: int
    bid_size: float
    ask_tick: int
    ask_size: float
    age_sec: float

    @property
    def spread_ticks(self) -> int:
        return self.ask_tick - self.bid_tick


@dataclass
class LeanHealth:
    files: int = 0
    carry_days: int = 0
    rows: int = 0
    valid_points: int = 0
    gaps: int = 0
    resets: int = 0
    crossed_levels_evicted: int = 0
    crossed_quotes_evicted: int = 0


@dataclass
class LeanSeries:
    points: list[LeanSample]
    times: list[int]
    health: LeanHealth
    max_age_sec: float

    def sample(self, ts: datetime) -> LeanSample | None:
        if not self.points:
            return None
        target = us(ts)
        index = bisect.bisect_right(self.times, target) - 1
        if index < 0:
            return None
        point = self.points[index]
        age = max(0.0, (target - point.ts_us) / 1_000_000)
        if age > self.max_age_sec:
            return None
        return LeanSample(
            ts_us=point.ts_us,
            raw=point.raw,
            smooth=point.smooth,
            bid_tick=point.bid_tick,
            bid_size=point.bid_size,
            ask_tick=point.ask_tick,
            ask_size=point.ask_size,
            age_sec=age,
        )


@dataclass
class ProbeRun:
    name: str
    spec: SessionSpec
    window_start: datetime
    window_end: datetime
    probe: CandidateTimingProbe
    candidates: list[CandidateBand]
    bands_by_id: dict[int, OwnershipBand]
    episodes_by_key: dict[tuple[int, datetime], object]
    gap_count: int


def side_sign(side: str) -> int:
    return 1 if side == "demand" else -1


def range_distance(left_min: int, left_max: int, right_min: int, right_max: int) -> int:
    if left_max < right_min:
        return right_min - left_max
    if right_max < left_min:
        return left_min - right_max
    return 0


def aligned_bin(value: float | None, threshold: float) -> str:
    if value is None or not math.isfinite(value):
        return "missing"
    if value >= threshold:
        return "aligned"
    if value <= -threshold:
        return "opposed"
    return "neutral"


def parse_session(value: str, default_window: str) -> SessionSpec:
    parts = value.split(":", 2)
    if len(parts) < 2:
        raise argparse.ArgumentTypeError("session must be YYYY-MM-DD:SYMBOL[:HH:MM-HH:MM]")
    window = parts[2] if len(parts) > 2 else default_window
    start, end = parse_window(parts[0], window)
    if end <= start:
        raise argparse.ArgumentTypeError("session window end must be after start")
    return SessionSpec(date=parts[0], symbol=parts[1], window=window)


def parse_window(date: str, window: str) -> tuple[datetime, datetime]:
    start_s, end_s = window.split("-", 1)
    return parse_ny(date, start_s), parse_ny(date, end_s)


def parse_int_list(value: str) -> list[int]:
    out: list[int] = []
    for part in value.split(","):
        part = part.strip()
        if part:
            out.append(int(part))
    if not out:
        raise argparse.ArgumentTypeError("list must contain at least one integer")
    return out


def chunk_groups(files: list[str]) -> list[list[str]]:
    groups: dict[str, list[str]] = {}
    order: list[str] = []
    for path in files:
        key = os.path.join(os.path.dirname(path), CHUNK_PART_RE.sub("", os.path.basename(path)))
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(path)
    return [groups[key] for key in order]


def chunk_time(path: str, prefix: str) -> tuple[str, str] | None:
    name = CHUNK_PART_RE.sub("", os.path.basename(path))
    match = re.match(rf"^{re.escape(prefix)}-(\d{{6}})-(\d{{6}})\.parquet$", name)
    if match is None:
        return None
    return match.group(1), match.group(2)


def hms_to_time(value: str) -> str:
    return f"{value[0:2]}:{value[2:4]}:{value[4:6]}"


def target_event_files(
    capture_root: str,
    spec: SessionSpec,
    *,
    start: datetime,
    end: datetime,
    max_carry_days: int,
) -> tuple[list[str], int]:
    pattern = os.path.join(capture_root, spec.symbol, spec.date, "book_events", "*.parquet")
    target_files = sorted(glob.glob(pattern))
    if not target_files:
        raise FileNotFoundError(pattern)

    selected: list[str] = []
    for path in target_files:
        times = chunk_time(path, "book-events")
        if times is None:
            continue
        chunk_start = parse_ny(spec.date, hms_to_time(times[0]))
        chunk_end = parse_ny(spec.date, hms_to_time(times[1]))
        if chunk_start <= end and chunk_end >= parse_ny(spec.date, "00:00:00"):
            selected.append(path)

    start_us = us(start)
    has_target_seed = (
        pl.scan_parquet(selected)
        .filter(
            (pl.col("event_kind") == RESET_BEGIN)
            & (pl.col("receipt_timestamp_us") <= start_us)
        )
        .select("event_kind")
        .limit(1)
        .collect()
        .height
        > 0
        if selected
        else False
    )
    if has_target_seed:
        return selected, 0

    carry_files, carry_days = event_files_with_carry(
        capture_root,
        spec.symbol,
        spec.date,
        max_carry_days,
    )
    carry_only = [path for path in carry_files if path not in target_files]
    return carry_only + selected, carry_days


def best_state(replay: BookReplay) -> tuple[int, float, int, float] | None:
    bid_tick = replay._best_tick(1)
    ask_tick = replay._best_tick(-1)
    if bid_tick is None or ask_tick is None or bid_tick >= ask_tick:
        return None
    bid_size = float(replay.bid_levels.get(bid_tick, 0.0))
    ask_size = float(replay.ask_levels.get(ask_tick, 0.0))
    if bid_size <= 0.0 or ask_size <= 0.0:
        return None
    return bid_tick, bid_size, ask_tick, ask_size


def load_lean_series(
    capture_root: str,
    spec: SessionSpec,
    *,
    start: datetime,
    end: datetime,
    half_life_ms: float,
    max_age_sec: float,
    max_carry_days: int,
) -> LeanSeries:
    files, carry_days = target_event_files(
        capture_root,
        spec,
        start=start,
        end=end,
        max_carry_days=max_carry_days,
    )
    health = LeanHealth(files=len(files), carry_days=carry_days)
    replay = BookReplay()
    points: list[LeanSample] = []
    smooth: float | None = None
    last_us: int | None = None
    start_us = us(start)
    end_us = us(end)
    half_life_us = max(1.0, half_life_ms * 1000.0)

    for group in chunk_groups(files):
        df = (
            pl.read_parquet(group, columns=EVENT_COLUMNS)
            .filter(pl.col("receipt_timestamp_us") <= end_us)
            .sort(["receipt_timestamp_us", "sequence", "subsequence"])
        )
        for row in df.iter_rows(named=True):
            event_us = int(row["receipt_timestamp_us"])
            if event_us > end_us:
                break
            kind = int(row["event_kind"])
            crossed_before = replay.crossed_levels_evicted
            replay.apply(row)
            health.rows += 1
            if kind == RESET_BEGIN:
                smooth = None
                last_us = None
                health.resets += 1
            elif kind == GAP:
                smooth = None
                last_us = None
                health.gaps += 1
            if replay.crossed_levels_evicted > crossed_before:
                health.crossed_levels_evicted = replay.crossed_levels_evicted
                health.crossed_quotes_evicted = replay.crossed_quotes_evicted
            if kind != DELTA or not replay.valid:
                continue

            state = best_state(replay)
            if state is None:
                continue
            bid_tick, bid_size, ask_tick, ask_size = state
            raw = (bid_size - ask_size) / max(1.0, bid_size + ask_size)
            if smooth is None or last_us is None:
                smooth = raw
            else:
                dt_us = max(0, event_us - last_us)
                alpha = 1.0 - math.exp(-math.log(2.0) * dt_us / half_life_us)
                smooth = smooth + alpha * (raw - smooth)
            last_us = event_us
            if event_us >= start_us:
                points.append(
                    LeanSample(
                        ts_us=event_us,
                        raw=raw,
                        smooth=smooth,
                        bid_tick=bid_tick,
                        bid_size=bid_size,
                        ask_tick=ask_tick,
                        ask_size=ask_size,
                        age_sec=0.0,
                    )
                )
                health.valid_points += 1

    return LeanSeries(
        points=points,
        times=[point.ts_us for point in points],
        health=health,
        max_age_sec=max_age_sec,
    )


def load_snapshot_lean_series(
    capture_root: str,
    spec: SessionSpec,
    *,
    start: datetime,
    end: datetime,
    half_life_ms: float,
    max_age_sec: float,
) -> LeanSeries:
    snapshots = load_filtered_snapshots(
        capture_root,
        spec.symbol,
        spec.date,
        start,
        end,
    )
    points: list[LeanSample] = []
    health = LeanHealth(rows=snapshots.height)
    smooth: float | None = None
    last_us: int | None = None
    half_life_us = max(1.0, half_life_ms * 1000.0)
    for row in snapshots.iter_rows(named=True):
        ts_us = int(row["timestamp_us"])
        ref_tick = int(row["ref_tick"])
        bid_size = float(row["bid_size_0"])
        ask_size = float(row["ask_size_0"])
        if bid_size <= 0.0 or ask_size <= 0.0:
            continue
        bid_tick = ref_tick + int(row["bid_offset_0"])
        ask_tick = ref_tick + int(row["ask_offset_0"])
        if bid_tick >= ask_tick:
            continue
        raw = (bid_size - ask_size) / max(1.0, bid_size + ask_size)
        if smooth is None or last_us is None:
            smooth = raw
        else:
            dt_us = max(0, ts_us - last_us)
            alpha = 1.0 - math.exp(-math.log(2.0) * dt_us / half_life_us)
            smooth = smooth + alpha * (raw - smooth)
        last_us = ts_us
        points.append(
            LeanSample(
                ts_us=ts_us,
                raw=raw,
                smooth=smooth,
                bid_tick=bid_tick,
                bid_size=bid_size,
                ask_tick=ask_tick,
                ask_size=ask_size,
                age_sec=0.0,
            )
        )
    health.valid_points = len(points)
    return LeanSeries(
        points=points,
        times=[point.ts_us for point in points],
        health=health,
        max_age_sec=max_age_sec,
    )


def replay_run(args: argparse.Namespace, spec: SessionSpec, *, name: str, confirm_ticks: int, relaxed: bool) -> ProbeRun:
    window_start, window_end = parse_window(spec.date, spec.window)
    replay_start = window_start - timedelta(minutes=args.warmup_min)
    snapshots = load_filtered_snapshots(
        args.capture_root,
        spec.symbol,
        spec.date,
        replay_start,
        window_end,
    )
    _, _, _, gaps = snapshot_timing_summary(snapshots, args.gap_threshold_sec)
    event_z = args.relaxed_event_z if relaxed else args.event_z
    cluster_min_score = args.relaxed_cluster_min_score if relaxed else args.cluster_min_score
    cluster_min_events = args.relaxed_cluster_min_events if relaxed else args.cluster_min_events

    probe = CandidateTimingProbe(
        session=spec.label,
        gap_threshold_sec=args.gap_threshold_sec,
        event_z=event_z,
        cluster_min_events=cluster_min_events,
        cluster_ticks=args.cluster_ticks,
        cluster_sec=args.cluster_sec,
        cluster_min_score=cluster_min_score,
        confirm_ticks=confirm_ticks,
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
    probe.finish(window_end)

    candidates = [
        candidate
        for candidate in probe.candidates
        if window_start <= candidate.formed_ts <= window_end
    ]
    candidate_ids = {candidate.id for candidate in candidates}
    episodes = [
        episode
        for episode in probe.episodes
        if episode.candidate_id in candidate_ids
    ]
    episodes_by_key = {
        (episode.candidate_id, episode.start_ts): episode
        for episode in episodes
    }

    for observation in probe.reclaim_observations:
        if observation.candidate_id not in candidate_ids:
            continue
        episode = episodes_by_key.get((observation.candidate_id, observation.episode_start))
        if episode is not None:
            observation.episode_duration_sec = episode.duration_sec
            observation.episode_outcome = episode.outcome
            observation.gap_contaminated |= episode.gap_contaminated

    for observation in probe.explicit_conversion_observations:
        if (
            observation.original_candidate_id not in candidate_ids
            or observation.support_candidate_id not in candidate_ids
        ):
            continue
        original = episodes_by_key.get(
            (observation.original_candidate_id, observation.original_episode_start)
        )
        support = episodes_by_key.get(
            (observation.support_candidate_id, observation.support_episode_start)
        )
        if original is not None:
            observation.original_duration_sec = original.duration_sec
            observation.original_outcome = original.outcome
            observation.gap_contaminated |= original.gap_contaminated
        if support is not None:
            observation.support_duration_sec = support.duration_sec
            observation.support_outcome = support.outcome
            observation.gap_contaminated |= support.gap_contaminated

    return ProbeRun(
        name=name,
        spec=spec,
        window_start=window_start,
        window_end=window_end,
        probe=probe,
        candidates=candidates,
        bands_by_id={band.id: band for band in probe.bands},
        episodes_by_key=episodes_by_key,
        gap_count=len(gaps),
    )


def transition_map(transitions: Iterable[Transition]) -> dict[int, list[Transition]]:
    out: dict[int, list[Transition]] = defaultdict(list)
    for tr in transitions:
        out[tr.band_id].append(tr)
    for values in out.values():
        values.sort(key=lambda tr: tr.ts)
    return out


def band_test_outcome(band: OwnershipBand, transitions_by_id: dict[int, list[Transition]]) -> tuple[str, datetime | None]:
    transitions = transitions_by_id.get(band.id, [])
    test = next((tr for tr in transitions if tr.action == "TEST"), None)
    if test is None:
        return ("failed_untested" if band.failed_ts is not None else "no_test"), None
    after = [tr for tr in transitions if tr.ts >= test.ts and tr.action in ("HOLD", "FAIL")]
    if not after:
        return "test_open", test.ts
    first = after[0]
    if first.action == "HOLD":
        return "test_held", test.ts
    return "test_failed", test.ts


def destroyed_opposing_structure(
    band: OwnershipBand,
    transitions: list[Transition],
    *,
    after: datetime,
    max_sec: int,
    max_distance_ticks: int,
) -> bool:
    until = after + timedelta(seconds=max_sec)
    for tr in transitions:
        if tr.ts <= after or tr.ts > until:
            continue
        if tr.action != "FAIL" or tr.side == band.side:
            continue
        if range_distance(band.min_tick, band.max_tick, tr.min_tick, tr.max_tick) <= max_distance_ticks:
            return True
    return False


def append_lean_fields(
    row: dict[str, object],
    lean: LeanSeries,
    ts: datetime,
    align_side: str,
    threshold: float,
    prefix: str = "lean",
) -> None:
    sample = lean.sample(ts)
    if sample is None:
        row.update(
            {
                f"{prefix}_raw": None,
                f"{prefix}_smooth": None,
                f"{prefix}_aligned": None,
                f"{prefix}_bin": "missing",
                f"{prefix}_age_sec": None,
                f"{prefix}_bid_size": None,
                f"{prefix}_ask_size": None,
                f"{prefix}_spread_ticks": None,
            }
        )
        return
    aligned = sample.smooth * side_sign(align_side)
    row.update(
        {
            f"{prefix}_raw": sample.raw,
            f"{prefix}_smooth": sample.smooth,
            f"{prefix}_aligned": aligned,
            f"{prefix}_bin": aligned_bin(aligned, threshold),
            f"{prefix}_age_sec": sample.age_sec,
            f"{prefix}_bid_size": sample.bid_size,
            f"{prefix}_ask_size": sample.ask_size,
            f"{prefix}_spread_ticks": sample.spread_ticks,
        }
    )


def candidate_outcome(candidate: CandidateBand, bands_by_id: dict[int, OwnershipBand]) -> tuple[str, str, str]:
    band = bands_by_id.get(candidate.id)
    if band is None:
        return "unresolved", "", ""
    if band.side == candidate.evidence_side:
        return "same_side", band.side, band.source
    return "consumed", band.side, band.source


def candidate_rows(
    run: ProbeRun,
    lean: LeanSeries,
    args: argparse.Namespace,
    *,
    row_type: str,
    base_candidates: list[CandidateBand] | None = None,
) -> list[dict[str, object]]:
    transitions_by_id = transition_map(run.probe.transitions)
    base_candidates = base_candidates or []
    rows: list[dict[str, object]] = []
    for candidate in run.candidates:
        if row_type == "near_miss_candidate" and overlaps_any(candidate, base_candidates, args.near_miss_ticks, args.near_miss_sec):
            continue
        outcome, final_side, source = candidate_outcome(candidate, run.bands_by_id)
        band = run.bands_by_id.get(candidate.id)
        test_outcome = ""
        test_ts = None
        destroyed = False
        if band is not None:
            test_outcome, test_ts = band_test_outcome(band, transitions_by_id)
            after = test_ts or band.owned_ts
            destroyed = destroyed_opposing_structure(
                band,
                run.probe.transitions,
                after=after,
                max_sec=args.destroy_sec,
                max_distance_ticks=args.destroy_distance_ticks,
            )
        row: dict[str, object] = {
            "row_type": row_type,
            "run": run.name,
            "session": run.spec.label,
            "ts": candidate.formed_ts.isoformat(),
            "ny_time": ny_hms(candidate.formed_ts),
            "candidate_id": candidate.id,
            "side": candidate.evidence_side,
            "align_side": candidate.evidence_side,
            "min_tick": candidate.min_tick,
            "max_tick": candidate.max_tick,
            "event_count": candidate.event_count,
            "score": candidate.score,
            "kind_count": len(candidate.kinds),
            "outcome": outcome,
            "final_side": final_side,
            "source": source,
            "test_outcome": test_outcome,
            "destroys_opposite": destroyed,
            "gap_contaminated": False,
        }
        append_lean_fields(row, lean, candidate.formed_ts, candidate.evidence_side, args.lean_threshold)
        rows.append(row)
    return rows


def episode_rows(run: ProbeRun, lean: LeanSeries, args: argparse.Namespace) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    candidate_ids = {candidate.id for candidate in run.candidates}
    for episode in run.probe.episodes:
        if episode.candidate_id not in candidate_ids:
            continue
        align_side = episode.evidence_side if episode.direction == "favor" else opposite(episode.evidence_side)
        row: dict[str, object] = {
            "row_type": "displacement_episode",
            "run": run.name,
            "session": run.spec.label,
            "ts": episode.start_ts.isoformat(),
            "ny_time": ny_hms(episode.start_ts),
            "candidate_id": episode.candidate_id,
            "side": episode.evidence_side,
            "align_side": align_side,
            "direction": episode.direction,
            "min_tick": episode.min_tick,
            "max_tick": episode.max_tick,
            "event_count": episode.event_count,
            "score": episode.score,
            "kind_count": episode.kind_count,
            "duration_sec": episode.duration_sec,
            "form_age_sec": episode.form_age_sec,
            "outcome": episode.outcome,
            "gap_contaminated": episode.gap_contaminated,
        }
        append_lean_fields(row, lean, episode.start_ts, align_side, args.lean_threshold)
        rows.append(row)
    return rows


def band_test_rows(run: ProbeRun, lean: LeanSeries, args: argparse.Namespace) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    transitions_by_id = transition_map(run.probe.transitions)
    for band in run.bands_by_id.values():
        if not (run.window_start <= band.owned_ts <= run.window_end):
            continue
        test_outcome, test_ts = band_test_outcome(band, transitions_by_id)
        if test_ts is None:
            continue
        row: dict[str, object] = {
            "row_type": "band_test",
            "run": run.name,
            "session": run.spec.label,
            "ts": test_ts.isoformat(),
            "ny_time": ny_hms(test_ts),
            "candidate_id": band.id,
            "side": band.side,
            "align_side": band.side,
            "min_tick": band.min_tick,
            "max_tick": band.max_tick,
            "event_count": band.event_count,
            "score": band.score,
            "kind_count": len(band.kinds),
            "outcome": test_outcome,
            "source": band.source,
            "band_class": "consumed" if "consumed" in band.source else "normal",
            "destroys_opposite": destroyed_opposing_structure(
                band,
                run.probe.transitions,
                after=test_ts,
                max_sec=args.destroy_sec,
                max_distance_ticks=args.destroy_distance_ticks,
            ),
            "gap_contaminated": False,
        }
        append_lean_fields(row, lean, test_ts, band.side, args.lean_threshold)
        rows.append(row)
    return rows


def reclaim_rows(run: ProbeRun, lean: LeanSeries, args: argparse.Namespace) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    candidate_ids = {candidate.id for candidate in run.candidates}
    for obs in run.probe.reclaim_observations:
        if obs.candidate_id not in candidate_ids or not (run.window_start <= obs.ts <= run.window_end):
            continue
        row: dict[str, object] = {
            "row_type": "supported_reclaim",
            "run": run.name,
            "session": run.spec.label,
            "ts": obs.ts.isoformat(),
            "ny_time": ny_hms(obs.ts),
            "candidate_id": obs.candidate_id,
            "failed_band_id": obs.failed_band_id,
            "failed_side": obs.failed_side,
            "side": obs.evidence_side,
            "align_side": obs.evidence_side,
            "distance_ticks": obs.distance_ticks,
            "duration_sec": obs.episode_duration_sec,
            "outcome": obs.episode_outcome,
            "event_count": obs.event_count,
            "score": obs.score,
            "kind_count": obs.kind_count,
            "gap_contaminated": obs.gap_contaminated,
        }
        append_lean_fields(row, lean, obs.ts, obs.evidence_side, args.lean_threshold)
        rows.append(row)
    return rows


def explicit_conversion_rows(run: ProbeRun, lean: LeanSeries, args: argparse.Namespace) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    candidate_ids = {candidate.id for candidate in run.candidates}
    for obs in run.probe.explicit_conversion_observations:
        if (
            obs.original_candidate_id not in candidate_ids
            or obs.support_candidate_id not in candidate_ids
            or not (run.window_start <= obs.ts <= run.window_end)
        ):
            continue
        if obs.original_outcome == "confirmed" and obs.support_outcome == "confirmed":
            outcome = "confirmed"
        elif obs.original_outcome == "reset" or obs.support_outcome == "reset":
            outcome = "failed"
        else:
            outcome = "open"
        row: dict[str, object] = {
            "row_type": "explicit_conversion",
            "run": run.name,
            "session": run.spec.label,
            "ts": obs.ts.isoformat(),
            "ny_time": ny_hms(obs.ts),
            "candidate_id": obs.original_candidate_id,
            "support_candidate_id": obs.support_candidate_id,
            "side": obs.resulting_side,
            "align_side": obs.resulting_side,
            "distance_ticks": obs.distance_ticks,
            "original_duration_sec": obs.original_duration_sec,
            "support_duration_sec": obs.support_duration_sec,
            "outcome": outcome,
            "original_outcome": obs.original_outcome,
            "support_outcome": obs.support_outcome,
            "gap_contaminated": obs.gap_contaminated,
        }
        append_lean_fields(row, lean, obs.ts, obs.resulting_side, args.lean_threshold)
        rows.append(row)
    return rows


def qualification_rows(run: ProbeRun, lean: LeanSeries, args: argparse.Namespace, tick_value: int) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    candidate_ids = {candidate.id for candidate in run.candidates}
    for episode in run.probe.episodes:
        if episode.candidate_id not in candidate_ids or episode.gap_contaminated:
            continue
        align_side = episode.evidence_side if episode.direction == "favor" else opposite(episode.evidence_side)
        sample = lean.sample(episode.start_ts)
        aligned = sample.smooth * side_sign(align_side) if sample is not None else None
        lean_bin = aligned_bin(aligned, args.lean_threshold)
        for persistence in args.persistence_grid:
            if episode.duration_sec < persistence:
                continue
            rows.append(
                {
                    "row_type": "qualification",
                    "run": run.name,
                    "session": run.spec.label,
                    "ts": episode.start_ts.isoformat(),
                    "ny_time": ny_hms(episode.start_ts),
                    "candidate_id": episode.candidate_id,
                    "side": episode.evidence_side,
                    "align_side": align_side,
                    "direction": episode.direction,
                    "confirm_ticks": tick_value,
                    "persistence_sec": persistence,
                    "duration_sec": episode.duration_sec,
                    "outcome": episode.outcome,
                    "lean_aligned": aligned,
                    "lean_bin": lean_bin,
                    "gap_contaminated": False,
                }
            )
    return rows


def overlaps_any(candidate: CandidateBand, baseline: list[CandidateBand], max_ticks: int, max_sec: int) -> bool:
    for other in baseline:
        if other.evidence_side != candidate.evidence_side:
            continue
        if abs((candidate.formed_ts - other.formed_ts).total_seconds()) > max_sec:
            continue
        if range_distance(candidate.min_tick, candidate.max_tick, other.min_tick, other.max_tick) <= max_ticks:
            return True
    return False


def collect_rows(
    args: argparse.Namespace,
    spec: SessionSpec,
    lean: LeanSeries,
) -> tuple[list[dict[str, object]], list[ProbeRun]]:
    baseline = replay_run(
        args,
        spec,
        name=f"base_{args.confirm_ticks}t",
        confirm_ticks=args.confirm_ticks,
        relaxed=False,
    )
    rows: list[dict[str, object]] = []
    rows.extend(candidate_rows(baseline, lean, args, row_type="candidate"))
    rows.extend(episode_rows(baseline, lean, args))
    rows.extend(band_test_rows(baseline, lean, args))
    rows.extend(reclaim_rows(baseline, lean, args))
    rows.extend(explicit_conversion_rows(baseline, lean, args))

    runs = [baseline]

    relaxed = replay_run(
        args,
        spec,
        name=f"relaxed_{args.confirm_ticks}t",
        confirm_ticks=args.confirm_ticks,
        relaxed=True,
    )
    runs.append(relaxed)
    rows.extend(
        candidate_rows(
            relaxed,
            lean,
            args,
            row_type="near_miss_candidate",
            base_candidates=baseline.candidates,
        )
    )

    tick_values = sorted(set(args.confirm_ticks_grid))
    for tick_value in tick_values:
        if tick_value == args.confirm_ticks:
            run = baseline
        else:
            run = replay_run(
                args,
                spec,
                name=f"qual_{tick_value}t",
                confirm_ticks=tick_value,
                relaxed=False,
            )
            runs.append(run)
        rows.extend(qualification_rows(run, lean, args, tick_value))

    return rows, runs


def pct(value: int, denominator: int) -> str:
    if denominator <= 0:
        return "n/a"
    return f"{100.0 * value / denominator:.1f}%"


def summarize_by(rows: list[dict[str, object]], row_type: str, group_field: str, outcome_field: str = "outcome") -> list[str]:
    selected = [
        row for row in rows
        if row.get("row_type") == row_type and not row.get("gap_contaminated")
    ]
    lines: list[str] = []
    if not selected:
        lines.append(f"No clean `{row_type}` rows.")
        return lines
    groups: dict[str, Counter[str]] = defaultdict(Counter)
    for row in selected:
        groups[str(row.get(group_field, ""))][str(row.get(outcome_field, ""))] += 1
    outcomes = sorted({outcome for counter in groups.values() for outcome in counter})
    header = "| group | n | " + " | ".join(outcomes) + " |"
    lines.append(header)
    lines.append("| --- | ---: | " + " | ".join("---:" for _ in outcomes) + " |")
    for group in sorted(groups):
        counter = groups[group]
        total = sum(counter.values())
        values = [f"{counter[outcome]} ({pct(counter[outcome], total)})" for outcome in outcomes]
        lines.append(f"| {group} | {total} | " + " | ".join(values) + " |")
    return lines


def summarize_qualification(rows: list[dict[str, object]]) -> list[str]:
    selected = [
        row for row in rows
        if row.get("row_type") == "qualification" and row.get("outcome") in ("confirmed", "reset")
    ]
    if not selected:
        return ["No clean qualification rows."]
    groups: dict[tuple[int, int, str, str], Counter[str]] = defaultdict(Counter)
    for row in selected:
        key = (
            int(row.get("confirm_ticks", 0)),
            int(row.get("persistence_sec", 0)),
            str(row.get("direction", "")),
            str(row.get("lean_bin", "")),
        )
        groups[key][str(row.get("outcome", ""))] += 1
    lines = [
        "| ticks | sec | direction | lean | confirmed/reset | stability |",
        "| ---: | ---: | --- | --- | ---: | ---: |",
    ]
    for key in sorted(groups):
        ticks, sec, direction, lean_bin = key
        counter = groups[key]
        confirmed = counter["confirmed"]
        reset = counter["reset"]
        denom = confirmed + reset
        lines.append(
            f"| {ticks} | {sec} | {direction} | {lean_bin} | "
            f"{confirmed}/{denom} | {pct(confirmed, denom)} |"
        )
    return lines


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = sorted({key for row in rows for key in row})
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def write_report(
    path: Path,
    specs: list[SessionSpec],
    rows: list[dict[str, object]],
    lean_health: dict[str, LeanHealth],
    runs: list[ProbeRun],
    args: argparse.Namespace,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = [
        "# Lean Band Probe",
        "",
        "Primary outcome is ownership classification, not fixed-horizon price excursion.",
        "",
        "## Sessions",
        "",
    ]
    for spec in specs:
        health = lean_health.get(spec.label)
        if health is None:
            continue
        lines.append(
            f"- `{spec.label}` `{spec.window}` lean_points={health.valid_points} "
            f"source_rows={health.rows} gaps={health.gaps} resets={health.resets} "
            f"carry_days={health.carry_days}"
        )

    lines.extend(
        [
            "",
            "## Replay Runs",
            "",
        ]
    )
    for run in runs:
        lines.append(
            f"- `{run.spec.label}` `{run.name}` candidates={len(run.candidates)} "
            f"bands={len(run.bands_by_id)} snapshot_gaps={run.gap_count}"
        )

    sections = [
        ("Baseline Candidate Outcomes By Lean At Formation", "candidate", "lean_bin"),
        ("Relaxed Near-Miss Candidate Outcomes By Lean At Formation", "near_miss_candidate", "lean_bin"),
        ("Displacement Episode Outcomes By Lean At Start", "displacement_episode", "lean_bin"),
        ("Band Test Outcomes By Lean At Test", "band_test", "lean_bin"),
        ("Supported Reclaim Outcomes By Lean At Failure", "supported_reclaim", "lean_bin"),
        ("Explicit Conversion Outcomes By Lean At Conversion", "explicit_conversion", "lean_bin"),
    ]
    for title, row_type, group_field in sections:
        lines.extend(["", f"## {title}", ""])
        lines.extend(summarize_by(rows, row_type, group_field))

    lines.extend(["", "## Qualification Grid", ""])
    lines.extend(summarize_qualification(rows))

    lines.extend(
        [
            "",
            "## Parameters",
            "",
            f"- Lean source: `{args.lean_source}`",
            f"- Lean half-life: `{args.lean_half_life_ms}` ms",
            f"- Lean bin threshold: `abs(aligned) >= {args.lean_threshold}`",
            f"- Baseline event z: `{args.event_z}`",
            f"- Relaxed event z: `{args.relaxed_event_z}`",
            f"- Baseline cluster score: `{args.cluster_min_score}`",
            f"- Relaxed cluster score: `{args.relaxed_cluster_min_score}`",
            f"- Confirm ticks grid: `{','.join(str(v) for v in args.confirm_ticks_grid)}`",
            f"- Persistence grid: `{','.join(str(v) for v in args.persistence_grid)}`",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--session", action="append", required=True, help="YYYY-MM-DD:SYMBOL[:HH:MM-HH:MM]")
    parser.add_argument("--window", default="09:30-16:00")
    parser.add_argument("--capture-root", default=MARKET_RECORDER_ROOT)
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
    parser.add_argument("--lean-half-life-ms", type=float, default=400.0)
    parser.add_argument("--lean-source", choices=("snapshots", "events"), default="snapshots")
    parser.add_argument("--lean-threshold", type=float, default=0.25)
    parser.add_argument("--lean-max-age-sec", type=float, default=2.0)
    parser.add_argument("--max-carry-days", type=int, default=3)
    parser.add_argument("--relaxed-event-z", type=float, default=2.0)
    parser.add_argument("--relaxed-cluster-min-events", type=int, default=2)
    parser.add_argument("--relaxed-cluster-min-score", type=float, default=6.0)
    parser.add_argument("--near-miss-ticks", type=int, default=12)
    parser.add_argument("--near-miss-sec", type=int, default=120)
    parser.add_argument("--destroy-sec", type=int, default=600)
    parser.add_argument("--destroy-distance-ticks", type=int, default=80)
    parser.add_argument("--confirm-ticks-grid", type=parse_int_list, default=parse_int_list("6,8,10"))
    parser.add_argument("--persistence-grid", type=parse_int_list, default=list(PERSISTENCE_THRESHOLDS))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--tag", default="")
    args = parser.parse_args()

    specs = [parse_session(value, args.window) for value in args.session]
    tag = args.tag or "_".join(f"{spec.date}_{spec.symbol}" for spec in specs)
    out_dir = Path(args.output_dir)
    csv_path = out_dir / f"lean_band_probe_{tag}.csv"
    report_path = out_dir / f"lean_band_probe_{tag}.md"

    all_rows: list[dict[str, object]] = []
    all_runs: list[ProbeRun] = []
    lean_health: dict[str, LeanHealth] = {}
    for spec in specs:
        window_start, window_end = parse_window(spec.date, spec.window)
        lean_start = window_start - timedelta(minutes=args.warmup_min)
        lean_end = window_end + timedelta(seconds=max(args.persistence_grid) + 5)
        if args.lean_source == "events":
            lean = load_lean_series(
                args.capture_root,
                spec,
                start=lean_start,
                end=lean_end,
                half_life_ms=args.lean_half_life_ms,
                max_age_sec=args.lean_max_age_sec,
                max_carry_days=args.max_carry_days,
            )
        else:
            lean = load_snapshot_lean_series(
                args.capture_root,
                spec,
                start=lean_start,
                end=lean_end,
                half_life_ms=args.lean_half_life_ms,
                max_age_sec=args.lean_max_age_sec,
            )
        lean_health[spec.label] = lean.health
        rows, runs = collect_rows(args, spec, lean)
        all_rows.extend(rows)
        all_runs.extend(runs)

    write_csv(csv_path, all_rows)
    write_report(report_path, specs, all_rows, lean_health, all_runs, args)
    print(f"wrote {csv_path}")
    print(f"wrote {report_path}")


if __name__ == "__main__":
    main()
