"""Measure the execution value of shortening LL's ownership confirmation delay.

LevelLedger already requires a researched event cluster before a candidate
forms. This probe keeps that cluster and the existing displacement threshold,
then measures how often an 8-tick directional displacement survives for 0, 1,
2, 3, 4, 5, or 10 seconds. It does not propose entries or calculate PnL.
"""

from __future__ import annotations

import argparse
import glob
import math
import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from statistics import median

import polars as pl

from ownership_bands_probe import CandidateBand, OwnershipProbe
from replay_levelledger import (
    BOOK_LOOKBACK_SEC,
    EVENT_Z_THRESHOLD,
    build_sample,
    load_snapshots,
    ny_hms,
    parse_ny,
    snapshot_timing_summary,
)
from capture_loader import MARKET_RECORDER_ROOT, snapshot_columns, us


PERSISTENCE_THRESHOLDS = (0, 1, 2, 3, 4, 5, 10)
CHUNK_RE = re.compile(r"^snapshots-(\d{6})-(\d{6})(?:-p\d+)?\.parquet$")


@dataclass
class DisplacementEpisode:
    session: str
    candidate_id: int
    evidence_side: str
    direction: str
    formed_ts: datetime
    start_ts: datetime
    end_ts: datetime | None
    outcome: str
    min_tick: int
    max_tick: int
    current_mid_tick: int
    event_count: int
    score: float
    kind_count: int
    gap_contaminated: bool = False

    @property
    def duration_sec(self) -> float:
        if self.end_ts is None:
            return 0.0
        return max(0.0, (self.end_ts - self.start_ts).total_seconds())

    @property
    def form_age_sec(self) -> float:
        return max(0.0, (self.start_ts - self.formed_ts).total_seconds())


@dataclass
class ReclaimCandidateObservation:
    session: str
    ts: datetime
    failed_band_id: int
    failed_side: str
    candidate_id: int
    evidence_side: str
    episode_start: datetime
    distance_ticks: int
    displacement_persistence_sec: float
    event_count: int
    score: float
    kind_count: int
    gap_contaminated: bool
    episode_duration_sec: float = 0.0
    episode_outcome: str = "open"


@dataclass
class ExplicitConversionObservation:
    session: str
    ts: datetime
    original_candidate_id: int
    support_candidate_id: int
    resulting_side: str
    distance_ticks: int
    original_episode_start: datetime
    support_episode_start: datetime
    original_duration_sec: float = 0.0
    support_duration_sec: float = 0.0
    original_outcome: str = "open"
    support_outcome: str = "open"
    gap_contaminated: bool = False


class CandidateTimingProbe(OwnershipProbe):
    def __init__(self, session: str, gap_threshold_sec: float, **kwargs) -> None:
        super().__init__(**kwargs)
        self.session = session
        self.gap_threshold_sec = max(0.1, gap_threshold_sec)
        self.episodes: list[DisplacementEpisode] = []
        self.reclaim_observations: list[ReclaimCandidateObservation] = []
        self.explicit_conversion_observations: list[ExplicitConversionObservation] = []
        self._active_episodes: dict[int, DisplacementEpisode] = {}
        self._observed_conversion_episodes: set[tuple[int, datetime]] = set()
        self._last_sample_ts: datetime | None = None
        self._current_sample_after_gap = False

    def on_sample(self, sample) -> None:
        self._current_sample_after_gap = False
        if self._last_sample_ts is not None:
            gap_sec = (sample.ts - self._last_sample_ts).total_seconds()
            if gap_sec > self.gap_threshold_sec:
                self._current_sample_after_gap = True
                for episode in self._active_episodes.values():
                    episode.gap_contaminated = True
        transition_count = len(self.transitions)
        super().on_sample(sample)
        self._observe_reclaim_candidates(
            sample.ts,
            self.transitions[transition_count:],
        )
        self._last_sample_ts = sample.ts

    def update_candidates(self, now: datetime, current_mid_tick: int) -> None:
        active_before = [
            candidate
            for candidate in self.candidates
            if candidate.state == "candidate"
        ]

        for candidate in active_before:
            direction = self._direction(candidate, current_mid_tick)
            episode = self._active_episodes.get(candidate.id)

            if episode is not None and direction != episode.direction:
                self._close_episode(candidate.id, now, "reset")
                episode = None

            if direction is not None and episode is None:
                self._active_episodes[candidate.id] = DisplacementEpisode(
                    session=self.session,
                    candidate_id=candidate.id,
                    evidence_side=candidate.evidence_side,
                    direction=direction,
                    formed_ts=candidate.formed_ts,
                    start_ts=now,
                    end_ts=None,
                    outcome="open",
                    min_tick=candidate.min_tick,
                    max_tick=candidate.max_tick,
                    current_mid_tick=current_mid_tick,
                    event_count=candidate.event_count,
                    score=candidate.score,
                    kind_count=len(candidate.kinds),
                    gap_contaminated=self._current_sample_after_gap,
                )

        super().update_candidates(now, current_mid_tick)

        self._observe_explicit_conversions(now)

        for candidate in active_before:
            if candidate.state == "confirmed" and candidate.id in self._active_episodes:
                self._close_episode(candidate.id, now, "confirmed")

    def finish(self, end_ts: datetime) -> None:
        for candidate_id in list(self._active_episodes):
            self._close_episode(candidate_id, end_ts, "open")

    def _direction(self, candidate: CandidateBand, current_mid_tick: int) -> str | None:
        if self.moved_with_evidence(candidate, current_mid_tick):
            return "favor"
        if self.moved_against_evidence(candidate, current_mid_tick):
            return "adverse"
        return None

    def _close_episode(self, candidate_id: int, ts: datetime, outcome: str) -> None:
        episode = self._active_episodes.pop(candidate_id)
        episode.end_ts = ts
        episode.outcome = outcome
        self.episodes.append(episode)

    def _observe_reclaim_candidates(self, now: datetime, transitions) -> None:
        for transition in transitions:
            if transition.action != "FAIL":
                continue

            expected_side = "demand" if transition.side == "supply" else "supply"
            eligible: list[tuple[int, CandidateBand, DisplacementEpisode]] = []
            failed_center = (transition.min_tick + transition.max_tick) / 2.0
            for candidate in self.candidates:
                if candidate.state != "candidate":
                    continue
                if candidate.evidence_side != expected_side:
                    continue
                if candidate.pending_confirm != "favor":
                    continue
                episode = self._active_episodes.get(candidate.id)
                if episode is None or episode.direction != "favor":
                    continue

                candidate_center = (candidate.min_tick + candidate.max_tick) / 2.0
                if expected_side == "demand" and candidate_center > failed_center:
                    continue
                if expected_side == "supply" and candidate_center < failed_center:
                    continue

                distance = self._range_distance(
                    candidate.min_tick,
                    candidate.max_tick,
                    transition.min_tick,
                    transition.max_tick,
                )
                eligible.append((distance, candidate, episode))

            if not eligible:
                continue

            distance, candidate, episode = min(eligible, key=lambda item: item[0])
            pending_ts = candidate.pending_confirm_ts or now
            self.reclaim_observations.append(
                ReclaimCandidateObservation(
                    session=self.session,
                    ts=now,
                    failed_band_id=transition.band_id,
                    failed_side=transition.side,
                    candidate_id=candidate.id,
                    evidence_side=candidate.evidence_side,
                    episode_start=episode.start_ts,
                    distance_ticks=distance,
                    displacement_persistence_sec=max(
                        0.0,
                        (now - pending_ts).total_seconds(),
                    ),
                    event_count=candidate.event_count,
                    score=candidate.score,
                    kind_count=len(candidate.kinds),
                    gap_contaminated=(
                        self._current_sample_after_gap
                        or episode.gap_contaminated
                    ),
                )
            )

    def _observe_explicit_conversions(self, now: datetime) -> None:
        candidates_by_id = {candidate.id: candidate for candidate in self.candidates}
        for original_id, original_episode in list(self._active_episodes.items()):
            if original_episode.direction != "adverse":
                continue
            key = (original_id, original_episode.start_ts)
            if key in self._observed_conversion_episodes:
                continue

            original = candidates_by_id.get(original_id)
            if original is None or original.state != "candidate":
                continue
            resulting_side = "supply" if original.evidence_side == "demand" else "demand"

            supports: list[tuple[int, CandidateBand, DisplacementEpisode]] = []
            for support_id, support_episode in self._active_episodes.items():
                if support_id == original_id or support_episode.direction != "favor":
                    continue
                support = candidates_by_id.get(support_id)
                if support is None or support.state != "candidate":
                    continue
                if support.evidence_side != resulting_side:
                    continue
                distance = self._range_distance(
                    original.min_tick,
                    original.max_tick,
                    support.min_tick,
                    support.max_tick,
                )
                supports.append((distance, support, support_episode))

            if not supports:
                continue

            distance, support, support_episode = min(supports, key=lambda item: item[0])
            self._observed_conversion_episodes.add(key)
            self.explicit_conversion_observations.append(
                ExplicitConversionObservation(
                    session=self.session,
                    ts=now,
                    original_candidate_id=original.id,
                    support_candidate_id=support.id,
                    resulting_side=resulting_side,
                    distance_ticks=distance,
                    original_episode_start=original_episode.start_ts,
                    support_episode_start=support_episode.start_ts,
                    gap_contaminated=(
                        original_episode.gap_contaminated
                        or support_episode.gap_contaminated
                    ),
                )
            )

    @staticmethod
    def _range_distance(
        left_min: int,
        left_max: int,
        right_min: int,
        right_max: int,
    ) -> int:
        if left_max < right_min:
            return right_min - left_max
        if right_max < left_min:
            return left_min - right_max
        return 0


@dataclass
class SessionResult:
    label: str
    window_start: datetime
    window_end: datetime
    candidate_count: int
    same_side_count: int
    consumed_count: int
    unresolved_count: int
    episodes: list[DisplacementEpisode]
    reclaim_observations: list[ReclaimCandidateObservation]
    explicit_conversion_observations: list[ExplicitConversionObservation]
    gap_count: int


def percentile(values: list[float], quantile: float) -> float:
    if not values:
        return math.nan
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(quantile * len(ordered)) - 1))
    return ordered[index]


def replay_session(args, date: str, symbol: str) -> SessionResult:
    start_s, end_s = args.window.split("-", 1)
    window_start = parse_ny(date, start_s)
    window_end = parse_ny(date, end_s)
    replay_start = window_start - timedelta(minutes=args.warmup_min)
    snapshots = load_filtered_snapshots(
        args.capture_root,
        symbol,
        date,
        replay_start,
        window_end,
    )
    _, _, _, gaps = snapshot_timing_summary(snapshots, args.gap_threshold_sec)

    label = f"{date}:{symbol}"
    probe = CandidateTimingProbe(
        session=label,
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
    probe.finish(window_end)

    candidates = [
        candidate
        for candidate in probe.candidates
        if window_start <= candidate.formed_ts <= window_end
    ]
    candidate_ids = {candidate.id for candidate in candidates}
    bands_by_id = {band.id: band for band in probe.bands}
    same_side = 0
    consumed = 0
    unresolved = 0
    for candidate in candidates:
        band = bands_by_id.get(candidate.id)
        if band is None:
            unresolved += 1
        elif band.side == candidate.evidence_side:
            same_side += 1
        else:
            consumed += 1

    episodes = [
        episode
        for episode in probe.episodes
        if episode.candidate_id in candidate_ids
    ]
    episodes_by_key = {
        (episode.candidate_id, episode.start_ts): episode
        for episode in episodes
    }

    reclaim_observations = [
        observation
        for observation in probe.reclaim_observations
        if observation.candidate_id in candidate_ids
        and window_start <= observation.ts <= window_end
    ]
    for observation in reclaim_observations:
        episode = episodes_by_key.get(
            (observation.candidate_id, observation.episode_start)
        )
        if episode is not None:
            observation.episode_duration_sec = episode.duration_sec
            observation.episode_outcome = episode.outcome
            observation.gap_contaminated |= episode.gap_contaminated
    explicit_conversion_observations = [
        observation
        for observation in probe.explicit_conversion_observations
        if observation.original_candidate_id in candidate_ids
        and observation.support_candidate_id in candidate_ids
        and window_start <= observation.ts <= window_end
    ]
    for observation in explicit_conversion_observations:
        original_episode = episodes_by_key.get(
            (observation.original_candidate_id, observation.original_episode_start)
        )
        support_episode = episodes_by_key.get(
            (observation.support_candidate_id, observation.support_episode_start)
        )
        if original_episode is not None:
            observation.original_duration_sec = original_episode.duration_sec
            observation.original_outcome = original_episode.outcome
            observation.gap_contaminated |= original_episode.gap_contaminated
        if support_episode is not None:
            observation.support_duration_sec = support_episode.duration_sec
            observation.support_outcome = support_episode.outcome
            observation.gap_contaminated |= support_episode.gap_contaminated

    return SessionResult(
        label=label,
        window_start=window_start,
        window_end=window_end,
        candidate_count=len(candidates),
        same_side_count=same_side,
        consumed_count=consumed,
        unresolved_count=unresolved,
        episodes=episodes,
        reclaim_observations=reclaim_observations,
        explicit_conversion_observations=explicit_conversion_observations,
        gap_count=len(gaps),
    )


def load_filtered_snapshots(
    capture_root: str,
    symbol: str,
    date: str,
    start: datetime,
    end: datetime,
) -> pl.DataFrame:
    pattern = os.path.join(
        capture_root,
        symbol,
        date,
        "snapshots",
        "*.parquet",
    )
    selected: list[str] = []
    for path in sorted(glob.glob(pattern)):
        match = CHUNK_RE.match(os.path.basename(path))
        if match is None:
            continue
        chunk_start = parse_ny(date, _hms(match.group(1)))
        chunk_end = parse_ny(date, _hms(match.group(2)))
        if chunk_end < start or chunk_start > end:
            continue
        selected.append(path)

    if not selected and capture_root == MARKET_RECORDER_ROOT:
        return load_snapshots(symbol, start, end)
    if not selected:
        raise FileNotFoundError(
            f"no snapshot chunks for {symbol} {date} under {capture_root}"
        )

    lo = us(start)
    hi = us(end)
    return (
        pl.scan_parquet(selected)
        .select(snapshot_columns())
        .filter(
            (pl.col("timestamp_us") >= lo)
            & (pl.col("timestamp_us") < hi)
        )
        .collect()
        .sort("timestamp_us")
    )


def _hms(value: str) -> str:
    return f"{value[0:2]}:{value[2:4]}:{value[4:6]}"


def resolved_threshold_counts(
    episodes: list[DisplacementEpisode],
    persistence_sec: int,
    direction: str | None = None,
) -> tuple[int, int, int]:
    eligible = [
        episode
        for episode in episodes
        if not episode.gap_contaminated
        and episode.duration_sec >= persistence_sec
        and (direction is None or episode.direction == direction)
    ]
    confirmed = sum(episode.outcome == "confirmed" for episode in eligible)
    reset = sum(episode.outcome == "reset" for episode in eligible)
    open_count = sum(episode.outcome == "open" for episode in eligible)
    return confirmed, reset, open_count


def print_result(result: SessionResult) -> None:
    resolved = result.same_side_count + result.consumed_count
    same_pct = 100.0 * result.same_side_count / resolved if resolved else math.nan
    clean = [episode for episode in result.episodes if not episode.gap_contaminated]
    form_ages = [episode.form_age_sec for episode in clean]
    confirmed_durations = [
        episode.duration_sec
        for episode in clean
        if episode.outcome == "confirmed"
    ]

    print(
        f"{result.label} {ny_hms(result.window_start)}-{ny_hms(result.window_end)} "
        f"candidates={result.candidate_count} same={result.same_side_count} "
        f"consumed={result.consumed_count} unresolved={result.unresolved_count} "
        f"same_side={same_pct:.1f}% gaps>{result.gap_count}"
    )
    if form_ages:
        print(
            "  displacement age from FORM: "
            f"median={median(form_ages):.1f}s p90={percentile(form_ages, 0.90):.1f}s; "
            f"confirmed persistence median={median(confirmed_durations):.1f}s"
        )
    print("  persist  confirmed reset open  stability")
    for persistence in PERSISTENCE_THRESHOLDS:
        confirmed, reset, open_count = resolved_threshold_counts(clean, persistence)
        denominator = confirmed + reset
        stability = 100.0 * confirmed / denominator if denominator else math.nan
        print(
            f"  {persistence:>4}s {confirmed:>10} {reset:>5} {open_count:>4} "
            f"{stability:>8.1f}%"
        )
    print_reclaim_summary(result.reclaim_observations, indent="  ")
    print_explicit_conversion_summary(
        result.explicit_conversion_observations,
        indent="  ",
    )


def reclaim_threshold_counts(
    observations: list[ReclaimCandidateObservation],
    persistence_sec: int,
    max_distance_ticks: int,
) -> tuple[int, int, int]:
    eligible = [
        observation
        for observation in observations
        if not observation.gap_contaminated
        and observation.episode_duration_sec >= persistence_sec
        and observation.distance_ticks <= max_distance_ticks
    ]
    confirmed = sum(
        observation.episode_outcome == "confirmed"
        for observation in eligible
    )
    reset = sum(observation.episode_outcome == "reset" for observation in eligible)
    unresolved = len(eligible) - confirmed - reset
    return confirmed, reset, unresolved


def print_reclaim_summary(
    observations: list[ReclaimCandidateObservation],
    *,
    indent: str = "",
) -> None:
    print(f"{indent}supported-reclaim candidate observations={len(observations)}")
    print(f"{indent}persist  <=20t       <=80t       <=160t")
    for persistence in (0, 2, 3, 4, 5):
        cells: list[str] = []
        for distance in (20, 80, 160):
            confirmed, reset, unresolved = reclaim_threshold_counts(
                observations,
                persistence,
                distance,
            )
            denominator = confirmed + reset
            stability = 100.0 * confirmed / denominator if denominator else math.nan
            cells.append(f"{confirmed}/{denominator} {stability:4.0f}%")
        print(f"{indent}{persistence:>4}s  " + "  ".join(f"{cell:>10}" for cell in cells))


def explicit_conversion_counts(
    observations: list[ExplicitConversionObservation],
    persistence_sec: int,
    max_distance_ticks: int,
) -> tuple[int, int, int]:
    eligible = [
        observation
        for observation in observations
        if not observation.gap_contaminated
        and observation.distance_ticks <= max_distance_ticks
        and observation.original_duration_sec >= persistence_sec
        and observation.support_duration_sec >= persistence_sec
    ]
    confirmed = sum(
        observation.original_outcome == "confirmed"
        and observation.support_outcome == "confirmed"
        for observation in eligible
    )
    failed = sum(
        observation.original_outcome == "reset"
        or observation.support_outcome == "reset"
        for observation in eligible
    )
    unresolved = len(eligible) - confirmed - failed
    return confirmed, failed, unresolved


def print_explicit_conversion_summary(
    observations: list[ExplicitConversionObservation],
    *,
    indent: str = "",
) -> None:
    print(f"{indent}explicit opposite-candidate conversions={len(observations)}")
    print(f"{indent}persist  overlap      <=10t       <=20t")
    for persistence in (0, 2, 3, 4, 5):
        cells: list[str] = []
        for distance in (0, 10, 20):
            confirmed, failed, unresolved = explicit_conversion_counts(
                observations,
                persistence,
                distance,
            )
            denominator = confirmed + failed
            stability = 100.0 * confirmed / denominator if denominator else math.nan
            cells.append(f"{confirmed}/{denominator} {stability:4.0f}%")
        print(f"{indent}{persistence:>4}s  " + "  ".join(f"{cell:>10}" for cell in cells))


def print_aggregate(results: list[SessionResult]) -> None:
    episodes = [episode for result in results for episode in result.episodes]
    clean = [episode for episode in episodes if not episode.gap_contaminated]
    reclaim_observations = [
        observation
        for result in results
        for observation in result.reclaim_observations
    ]
    explicit_conversion_observations = [
        observation
        for result in results
        for observation in result.explicit_conversion_observations
    ]
    same = sum(result.same_side_count for result in results)
    consumed = sum(result.consumed_count for result in results)
    unresolved = sum(result.unresolved_count for result in results)
    resolved = same + consumed

    print("\nAGGREGATE")
    print(
        f"sessions={len(results)} candidates={same + consumed + unresolved} "
        f"same={same} consumed={consumed} unresolved={unresolved} "
        f"same_side={100.0 * same / resolved if resolved else math.nan:.1f}% "
        f"episodes={len(episodes)} gap_excluded={len(episodes) - len(clean)}"
    )
    print("persist  confirmed reset open  stability  lead_vs_LL")
    for persistence in PERSISTENCE_THRESHOLDS:
        confirmed, reset, open_count = resolved_threshold_counts(clean, persistence)
        denominator = confirmed + reset
        stability = 100.0 * confirmed / denominator if denominator else math.nan
        lead = max(0, 10 - persistence)
        print(
            f"{persistence:>4}s {confirmed:>10} {reset:>5} {open_count:>4} "
            f"{stability:>8.1f}% {lead:>9}s"
        )
    for direction, label in (
        ("favor", "same-side anchor displacement"),
        ("adverse", "candidate direct conversion"),
    ):
        print(label)
        print("persist  confirmed reset open  stability")
        for persistence in PERSISTENCE_THRESHOLDS:
            confirmed, reset, open_count = resolved_threshold_counts(
                clean,
                persistence,
                direction,
            )
            denominator = confirmed + reset
            stability = 100.0 * confirmed / denominator if denominator else math.nan
            print(
                f"{persistence:>4}s {confirmed:>10} {reset:>5} {open_count:>4} "
                f"{stability:>8.1f}%"
            )
    print_reclaim_summary(reclaim_observations)
    print_explicit_conversion_summary(explicit_conversion_observations)


def print_details(results: list[SessionResult], min_duration_sec: float) -> None:
    print("\nDETAILS")
    for result in results:
        for episode in result.episodes:
            if episode.duration_sec < min_duration_sec:
                continue
            print(
                f"{episode.session} {ny_hms(episode.start_ts)} "
                f"id={episode.candidate_id} {episode.evidence_side}/{episode.direction} "
                f"age={episode.form_age_sec:.1f}s dur={episode.duration_sec:.1f}s "
                f"outcome={episode.outcome} events={episode.event_count} "
                f"score={episode.score:.1f} kinds={episode.kind_count} "
                f"gap={episode.gap_contaminated}"
            )
        for observation in result.reclaim_observations:
            print(
                f"{observation.session} {ny_hms(observation.ts)} "
                f"reclaim fail={observation.failed_band_id}/{observation.failed_side} "
                f"candidate={observation.candidate_id}/{observation.evidence_side} "
                f"persist_at_fail={observation.displacement_persistence_sec:.1f}s "
                f"episode={observation.episode_duration_sec:.1f}s/"
                f"{observation.episode_outcome} "
                f"distance={observation.distance_ticks}t "
                f"events={observation.event_count} "
                f"score={observation.score:.1f} kinds={observation.kind_count} "
                f"gap={observation.gap_contaminated}"
            )
        for observation in result.explicit_conversion_observations:
            print(
                f"{observation.session} {ny_hms(observation.ts)} "
                f"conversion original={observation.original_candidate_id} "
                f"support={observation.support_candidate_id} "
                f"side={observation.resulting_side} "
                f"distance={observation.distance_ticks}t "
                f"dur={observation.original_duration_sec:.1f}/"
                f"{observation.support_duration_sec:.1f}s "
                f"outcome={observation.original_outcome}/"
                f"{observation.support_outcome} "
                f"gap={observation.gap_contaminated}"
            )


def parse_session(value: str) -> tuple[str, str]:
    try:
        date, symbol = value.split(":", 1)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("session must be YYYY-MM-DD:SYMBOL_DIR") from exc
    return date, symbol


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--session",
        action="append",
        required=True,
        type=parse_session,
        help="Repeatable YYYY-MM-DD:SYMBOL_DIR session",
    )
    parser.add_argument("--window", default="09:30-16:00")
    parser.add_argument("--warmup-min", type=int, default=90)
    parser.add_argument("--capture-root", default=MARKET_RECORDER_ROOT)
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
    parser.add_argument("--details", action="store_true")
    parser.add_argument("--detail-min-sec", type=float, default=2.0)
    parser.add_argument("--aggregate-only", action="store_true")
    args = parser.parse_args()

    results = [replay_session(args, date, symbol) for date, symbol in args.session]
    if not args.aggregate_only:
        for result in results:
            print_result(result)
    print_aggregate(results)
    if args.details:
        print_details(results, args.detail_min_sec)


if __name__ == "__main__":
    main()
