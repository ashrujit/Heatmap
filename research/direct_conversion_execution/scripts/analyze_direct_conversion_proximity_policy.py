"""Evaluate market-versus-wait policies on proximity-anchored LOB states.

This is an execution-policy audit, not a direct-conversion validity classifier.
Policies may enter only while the executable quote remains within EAR's
20-tick envelope.  Outcomes are structural root advancement or root failure.
"""

from __future__ import annotations

import argparse
import csv
import math
import random
import statistics
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterable

from _paths import OUTPUT_ROOT

DEFAULT_INPUT = (
    OUTPUT_ROOT
    / "direct_conversion_proximity_book_20260717_20260724"
)
DEFAULT_OUT = (
    OUTPUT_ROOT
    / "direct_conversion_proximity_policy_waitability_20260717_20260724"
)
ADVANCED = "ADVANCED_TO_FAVORABLE_SUCCESSOR"
FAILED = "ROOT_FAILED_FIRST"
HORIZONS_S = (5.0, 15.0, 30.0, 60.0, 120.0, 300.0)
LANDMARKS_S = (0.0, 0.5, 2.0, 5.0, 10.0)
WAITABILITY_DELAYS_S = (0.5, 1.0, 2.0, 5.0)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--bootstrap-samples", type=int, default=10_000)
    return parser.parse_args()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def input_rows(input_dir: Path, name: str) -> list[dict[str, str]]:
    direct = input_dir / name
    paths = [direct] if direct.exists() else sorted((input_dir / "days").glob(f"*/{name}"))
    if not paths:
        raise FileNotFoundError(f"no {name} under {input_dir}")
    return [row for path in paths for row in read_csv(path)]


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fields: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for key in row:
            if key not in seen:
                fields.append(key)
                seen.add(key)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def number(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if math.isfinite(parsed) else default


def truth(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes"}


def median(values: Iterable[float]) -> float | None:
    clean = [value for value in values if math.isfinite(value)]
    return statistics.median(clean) if clean else None


def quantile(values: list[float], probability: float) -> float | None:
    clean = sorted(value for value in values if math.isfinite(value))
    if not clean:
        return None
    position = (len(clean) - 1) * probability
    lo = math.floor(position)
    hi = math.ceil(position)
    if lo == hi:
        return clean[lo]
    weight = position - lo
    return clean[lo] * (1 - weight) + clean[hi] * weight


def fmt(value: Any, digits: int = 3) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        if not math.isfinite(value):
            return ""
        return f"{value:.{digits}f}"
    return str(value)


def episode_key(row: dict[str, Any]) -> tuple[str, str, str]:
    return row["session_id"], row["date"], row["root_id"]


def parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value)


def auc(positive: list[float], negative: list[float]) -> float | None:
    if not positive or not negative:
        return None
    combined = [(value, 1) for value in positive] + [
        (value, 0) for value in negative
    ]
    combined.sort(key=lambda item: item[0])
    rank_sum = 0.0
    index = 0
    while index < len(combined):
        end = index + 1
        while end < len(combined) and combined[end][0] == combined[index][0]:
            end += 1
        average_rank = (index + 1 + end) / 2
        rank_sum += average_rank * sum(label for _, label in combined[index:end])
        index = end
    return (
        rank_sum - len(positive) * (len(positive) + 1) / 2
    ) / (len(positive) * len(negative))


def load_population(
    input_dir: Path,
) -> tuple[
    list[dict[str, str]],
    dict[tuple[str, str, str], list[dict[str, str]]],
]:
    episodes = input_rows(input_dir, "episode_summary.csv")
    complete = {
        episode_key(row): row
        for row in episodes
        if row.get("capture_status") == "complete"
    }
    samples: dict[tuple[str, str, str], list[dict[str, str]]] = defaultdict(list)
    for row in input_rows(input_dir, "state_samples.csv"):
        key = episode_key(row)
        if key in complete:
            samples[key].append(row)
    for group in samples.values():
        group.sort(key=lambda row: number(row.get("elapsed_s")))
    usable = [complete[key] for key in complete if samples.get(key)]
    return usable, samples


Policy = Callable[[dict[str, str]], bool]


def market_now(_: dict[str, str]) -> bool:
    return True


def support_non_eroding(row: dict[str, str]) -> bool:
    return (
        number(row.get("support_net_norm_2p0s")) >= 0.0
        and number(row.get("owner_under_depth_ratio"), 1.0) >= 0.8
    )


def road_clearing(row: dict[str, str]) -> bool:
    return (
        number(row.get("road_clear_norm_2p0s")) >= 0.0
        and number(row.get("opponent_road_depth_ratio"), 1.0) <= 1.2
    )


def joint_field(row: dict[str, str]) -> bool:
    return support_non_eroding(row) and road_clearing(row)


def three_field(row: dict[str, str]) -> bool:
    return joint_field(row) and number(row.get("under_net_norm_2p0s")) >= 0.0


def challenged_reload(row: dict[str, str]) -> bool:
    owner_consumed = number(row.get("tape_owner_field_consume_2p0s"))
    owner_removed = number(row.get("book_owner_field_remove_2p0s"))
    owner_added = number(row.get("book_owner_field_add_2p0s"))
    return (
        owner_consumed > 0.0
        and owner_removed > 0.0
        and owner_added >= 0.75 * owner_removed
        and number(row.get("owner_under_depth_ratio"), 1.0) >= 0.8
    )


def consumed_road_joint(row: dict[str, str]) -> bool:
    return (
        joint_field(row)
        and number(row.get("book_opponent_road_remove_2p0s")) > 0.0
        and number(row.get("road_remove_consumed_share_2p0s")) >= 0.25
    )


POLICIES: dict[str, tuple[Policy, float]] = {
    "market_now": (market_now, 0.0),
    "support_non_eroding": (support_non_eroding, 0.0),
    "road_clearing": (road_clearing, 0.0),
    "joint_field": (joint_field, 0.0),
    "joint_field_after_250ms": (joint_field, 0.25),
    "three_field": (three_field, 0.0),
    "challenged_reload": (challenged_reload, 0.0),
    "consumed_road_joint": (consumed_road_joint, 0.0),
}

SCORE_FEATURES = (
    ("support_net_norm_2p0s", 1.0),
    ("under_net_norm_2p0s", 1.0),
    ("road_clear_norm_2p0s", 1.0),
    ("owner_under_depth_ratio", 1.0),
    ("opponent_road_depth_ratio", -1.0),
)


def entry_for_policy(
    rows: list[dict[str, str]],
    predicate: Policy,
    minimum_elapsed_s: float,
    horizon_s: float,
) -> dict[str, str] | None:
    for row in rows:
        elapsed = number(row.get("elapsed_s"))
        if elapsed < minimum_elapsed_s or elapsed > horizon_s:
            continue
        if not truth(row.get("inside_20_ticks")):
            continue
        if predicate(row):
            return row
    return None


def decision_rows(
    episodes: list[dict[str, str]],
    samples: dict[tuple[str, str, str], list[dict[str, str]]],
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for episode in episodes:
        key = episode_key(episode)
        states = samples[key]
        baseline_price = number(states[0].get("executable_price"))
        favorable_sign = 1 if episode["side"] == "Demand" else -1
        for horizon in HORIZONS_S:
            for policy_name, (predicate, minimum_elapsed) in POLICIES.items():
                entry = entry_for_policy(
                    states,
                    predicate,
                    minimum_elapsed,
                    horizon,
                )
                filled = entry is not None
                entry_price = number(entry.get("executable_price")) if entry else math.nan
                improvement = (
                    (baseline_price - entry_price) * favorable_sign
                    if filled
                    else math.nan
                )
                outcome = episode["structural_outcome"]
                output.append(
                    {
                        "session_id": episode["session_id"],
                        "date": episode["date"],
                        "root_id": episode["root_id"],
                        "side": episode["side"],
                        "root_lo": episode.get("root_lo", ""),
                        "root_hi": episode.get("root_hi", ""),
                        "proximity_et": episode.get("proximity_et", ""),
                        "structural_outcome": outcome,
                        "policy": policy_name,
                        "horizon_s": horizon,
                        "filled": filled,
                        "entry_et": entry.get("sample_et", "") if entry else "",
                        "delay_s": number(entry.get("elapsed_s")) if entry else "",
                        "entry_price": entry_price if filled else "",
                        "entry_improvement_pts": round(improvement, 3)
                        if filled
                        else "",
                        "advance_captured": filled and outcome == ADVANCED,
                        "advance_missed": not filled and outcome == ADVANCED,
                        "failure_exposed": filled and outcome == FAILED,
                        "failure_avoided": not filled and outcome == FAILED,
                    }
                )
    return output


def delayed_entry(
    rows: list[dict[str, str]],
    delay_s: float,
    horizon_s: float,
) -> dict[str, str] | None:
    for row in rows:
        elapsed = number(row.get("elapsed_s"))
        if elapsed < delay_s:
            continue
        if elapsed > horizon_s:
            break
        if truth(row.get("inside_20_ticks")):
            return row
    return None


def delay_decision_rows(
    episodes: list[dict[str, str]],
    samples: dict[tuple[str, str, str], list[dict[str, str]]],
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for episode in episodes:
        key = episode_key(episode)
        states = samples[key]
        baseline_price = number(states[0].get("executable_price"))
        favorable_sign = 1 if episode["side"] == "Demand" else -1
        for horizon in HORIZONS_S:
            for delay in (0.5, 1.0, 2.0, 5.0):
                entry = delayed_entry(states, delay, horizon)
                filled = entry is not None
                entry_price = number(entry.get("executable_price")) if entry else math.nan
                improvement = (
                    (baseline_price - entry_price) * favorable_sign
                    if filled
                    else math.nan
                )
                outcome = episode["structural_outcome"]
                output.append(
                    {
                        "session_id": episode["session_id"],
                        "date": episode["date"],
                        "root_id": episode["root_id"],
                        "side": episode["side"],
                        "root_lo": episode.get("root_lo", ""),
                        "root_hi": episode.get("root_hi", ""),
                        "proximity_et": episode.get("proximity_et", ""),
                        "structural_outcome": outcome,
                        "policy": f"delay_{str(delay).replace('.', 'p')}s",
                        "horizon_s": horizon,
                        "filled": filled,
                        "entry_et": entry.get("sample_et", "") if entry else "",
                        "delay_s": number(entry.get("elapsed_s")) if entry else "",
                        "entry_price": entry_price if filled else "",
                        "entry_improvement_pts": round(improvement, 3)
                        if filled
                        else "",
                        "advance_captured": filled and outcome == ADVANCED,
                        "advance_missed": not filled and outcome == ADVANCED,
                        "failure_exposed": filled and outcome == FAILED,
                        "failure_avoided": not filled and outcome == FAILED,
                    }
                )
    return output


def robust_score_calibration(
    sample_groups: Iterable[list[dict[str, str]]],
) -> dict[str, tuple[float, float, float]]:
    selected = [
        row
        for rows in sample_groups
        for row in rows
        if number(row.get("elapsed_s")) <= 10.0
        and truth(row.get("inside_20_ticks"))
    ]
    output: dict[str, tuple[float, float, float]] = {}
    for feature, direction in SCORE_FEATURES:
        values = [number(row.get(feature)) * direction for row in selected]
        center = median(values) or 0.0
        low = quantile(values, 0.25)
        high = quantile(values, 0.75)
        scale = (
            (high - low)
            if low is not None and high is not None and high - low > 1e-9
            else statistics.pstdev(values)
            if len(values) > 1
            else 1.0
        )
        output[feature] = (direction, center, max(scale, 1e-6))
    return output


def urgency_entry(
    rows: list[dict[str, str]],
    t0_score: float,
    threshold: float,
    defer_s: float,
    horizon_s: float,
) -> dict[str, str] | None:
    if t0_score >= threshold:
        return rows[0] if truth(rows[0].get("inside_20_ticks")) else None
    return delayed_entry(rows, defer_s, horizon_s)


def urgency_policy_stats(
    episode_rows: list[dict[str, str]],
    samples: dict[tuple[str, str, str], list[dict[str, str]]],
    t0_scores: dict[tuple[str, str, str], float],
    threshold: float,
    defer_s: float,
    horizon_s: float,
) -> tuple[float, float, float]:
    advanced = [row for row in episode_rows if row["structural_outcome"] == ADVANCED]
    failed = [row for row in episode_rows if row["structural_outcome"] == FAILED]

    def filled(row: dict[str, str]) -> bool:
        key = episode_key(row)
        return (
            urgency_entry(
                samples[key],
                t0_scores[key],
                threshold,
                defer_s,
                horizon_s,
            )
            is not None
        )

    advance_capture = (
        sum(filled(row) for row in advanced) / len(advanced)
        if advanced
        else math.nan
    )
    failure_exposure = (
        sum(filled(row) for row in failed) / len(failed)
        if failed
        else math.nan
    )
    return advance_capture, failure_exposure, advance_capture - failure_exposure


def cv_urgency_decisions(
    episodes: list[dict[str, str]],
    samples: dict[tuple[str, str, str], list[dict[str, str]]],
) -> list[dict[str, Any]]:
    dates = sorted({row["date"] for row in episodes})
    if len(dates) < 2:
        return []
    output: list[dict[str, Any]] = []
    for held_out in dates:
        training = [row for row in episodes if row["date"] != held_out]
        testing = [row for row in episodes if row["date"] == held_out]
        calibration = robust_score_calibration(
            samples[episode_key(row)] for row in training
        )
        t0_scores = {
            episode_key(row): state_score(samples[episode_key(row)][0], calibration)
            for row in episodes
        }
        training_scores = [t0_scores[episode_key(row)] for row in training]
        thresholds = sorted(
            {
                quantile(training_scores, probability)
                for probability in (
                    0.0,
                    0.1,
                    0.2,
                    0.3,
                    0.4,
                    0.5,
                    0.6,
                    0.7,
                    0.8,
                    0.9,
                    1.0,
                )
            }
            - {None}
        )
        for horizon in HORIZONS_S:
            for defer_s in (0.5, 1.0, 2.0, 5.0):
                candidates = [
                    (
                        threshold,
                        *urgency_policy_stats(
                            training,
                            samples,
                            t0_scores,
                            threshold,
                            defer_s,
                            horizon,
                        ),
                    )
                    for threshold in thresholds
                ]
                eligible = [item for item in candidates if item[1] >= 0.9]
                if not eligible:
                    eligible = candidates
                threshold, train_capture, train_exposure, train_selectivity = max(
                    eligible,
                    key=lambda item: (
                        item[3],
                        -item[2],
                        item[0],
                    ),
                )
                policy_name = (
                    f"cv_urgency_defer_{str(defer_s).replace('.', 'p')}s_capture_90"
                )
                for episode in testing:
                    key = episode_key(episode)
                    entry = urgency_entry(
                        samples[key],
                        t0_scores[key],
                        threshold,
                        defer_s,
                        horizon,
                    )
                    filled = entry is not None
                    baseline_price = number(samples[key][0].get("executable_price"))
                    favorable_sign = 1 if episode["side"] == "Demand" else -1
                    entry_price = (
                        number(entry.get("executable_price")) if entry else math.nan
                    )
                    improvement = (
                        (baseline_price - entry_price) * favorable_sign
                        if filled
                        else math.nan
                    )
                    outcome = episode["structural_outcome"]
                    output.append(
                        {
                            "session_id": episode["session_id"],
                            "date": episode["date"],
                            "root_id": episode["root_id"],
                            "side": episode["side"],
                            "root_lo": episode.get("root_lo", ""),
                            "root_hi": episode.get("root_hi", ""),
                            "proximity_et": episode.get("proximity_et", ""),
                            "structural_outcome": outcome,
                            "policy": policy_name,
                            "horizon_s": horizon,
                            "filled": filled,
                            "entry_et": entry.get("sample_et", "") if entry else "",
                            "delay_s": number(entry.get("elapsed_s")) if entry else "",
                            "entry_price": entry_price if filled else "",
                            "entry_improvement_pts": round(improvement, 3)
                            if filled
                            else "",
                            "advance_captured": filled and outcome == ADVANCED,
                            "advance_missed": not filled and outcome == ADVANCED,
                            "failure_exposed": filled and outcome == FAILED,
                            "failure_avoided": not filled and outcome == FAILED,
                            "cv_threshold": round(threshold, 6),
                            "t0_field_score": round(t0_scores[key], 6),
                            "train_advance_capture": round(train_capture, 6),
                            "train_failure_exposure": round(train_exposure, 6),
                            "train_selectivity": round(train_selectivity, 6),
                        }
                    )
    return output


def state_score(
    row: dict[str, str],
    calibration: dict[str, tuple[float, float, float]],
) -> float:
    total = 0.0
    for feature, (direction, center, scale) in calibration.items():
        value = number(row.get(feature)) * direction
        total += max(-3.0, min(3.0, (value - center) / scale))
    return total / len(calibration)


def score_entry(
    rows: list[dict[str, str]],
    scores: list[float],
    threshold: float,
    horizon_s: float,
    minimum_elapsed_s: float = 0.0,
    persistence_s: float = 0.0,
) -> dict[str, str] | None:
    supportive_since: float | None = None
    for row, score in zip(rows, scores):
        elapsed = number(row.get("elapsed_s"))
        if elapsed < minimum_elapsed_s:
            continue
        if elapsed > horizon_s:
            break
        if not truth(row.get("inside_20_ticks")) or score < threshold:
            supportive_since = None
            continue
        if supportive_since is None:
            supportive_since = elapsed
        if elapsed - supportive_since + 1e-9 >= persistence_s:
            return row
    return None


def score_policy_stats(
    episode_rows: list[dict[str, str]],
    samples: dict[tuple[str, str, str], list[dict[str, str]]],
    scores: dict[tuple[str, str, str], list[float]],
    threshold: float,
    horizon_s: float,
    minimum_elapsed_s: float,
    persistence_s: float,
) -> tuple[float, float, float]:
    advanced = [row for row in episode_rows if row["structural_outcome"] == ADVANCED]
    failed = [row for row in episode_rows if row["structural_outcome"] == FAILED]
    advance_capture = (
        sum(
            score_entry(
                samples[episode_key(row)],
                scores[episode_key(row)],
                threshold,
                horizon_s,
                minimum_elapsed_s,
                persistence_s,
            )
            is not None
            for row in advanced
        )
        / len(advanced)
        if advanced
        else math.nan
    )
    failure_exposure = (
        sum(
            score_entry(
                samples[episode_key(row)],
                scores[episode_key(row)],
                threshold,
                horizon_s,
                minimum_elapsed_s,
                persistence_s,
            )
            is not None
            for row in failed
        )
        / len(failed)
        if failed
        else math.nan
    )
    return advance_capture, failure_exposure, advance_capture - failure_exposure


def cv_score_decisions(
    episodes: list[dict[str, str]],
    samples: dict[tuple[str, str, str], list[dict[str, str]]],
) -> list[dict[str, Any]]:
    dates = sorted({row["date"] for row in episodes})
    if len(dates) < 2:
        return []
    output: list[dict[str, Any]] = []
    for held_out in dates:
        training = [row for row in episodes if row["date"] != held_out]
        testing = [row for row in episodes if row["date"] == held_out]
        calibration = robust_score_calibration(
            samples[episode_key(row)] for row in training
        )
        scores = {
            episode_key(row): [
                state_score(sample, calibration)
                for sample in samples[episode_key(row)]
            ]
            for row in episodes
        }
        for horizon in HORIZONS_S:
            configurations = (
                ("cv_field_score_capture_70", 0.7, 0.0, 0.0, False),
                ("cv_field_score_after_2s_capture_70", 0.7, 2.0, 0.0, False),
                ("cv_field_score_persist_0p5s_capture_70", 0.7, 0.0, 0.5, False),
                ("cv_field_delta_after_2s_capture_70", 0.7, 2.0, 0.0, True),
                ("cv_field_delta_persist_0p5s_capture_70", 0.7, 0.0, 0.5, True),
            )
            for (
                policy_name,
                target,
                minimum_elapsed,
                persistence,
                use_delta,
            ) in configurations:
                configured_scores = {
                    key: (
                        [value - values[0] for value in values]
                        if use_delta
                        else values
                    )
                    for key, values in scores.items()
                }
                training_scores = [
                    score
                    for row in training
                    for sample, score in zip(
                        samples[episode_key(row)],
                        configured_scores[episode_key(row)],
                    )
                    if minimum_elapsed
                    <= number(sample.get("elapsed_s"))
                    <= min(horizon, 10.0)
                    and truth(sample.get("inside_20_ticks"))
                ]
                thresholds = sorted(
                    {
                        quantile(training_scores, probability)
                        for probability in (
                            0.0,
                            0.1,
                            0.2,
                            0.3,
                            0.4,
                            0.5,
                            0.6,
                            0.7,
                            0.8,
                            0.9,
                        )
                    }
                    - {None}
                )
                candidates = [
                    (
                        threshold,
                        *score_policy_stats(
                            training,
                            samples,
                            configured_scores,
                            threshold,
                            horizon,
                            minimum_elapsed,
                            persistence,
                        ),
                    )
                    for threshold in thresholds
                ]
                eligible = [
                    item for item in candidates if item[1] >= target
                ]
                if not eligible:
                    eligible = candidates
                threshold, train_capture, train_exposure, train_selectivity = max(
                    eligible,
                    key=lambda item: (
                        item[3],
                        -item[2],
                        item[0],
                    ),
                )
                for episode in testing:
                    key = episode_key(episode)
                    entry = score_entry(
                        samples[key],
                        scores[key],
                        threshold,
                        horizon,
                        minimum_elapsed,
                        persistence,
                    )
                    filled = entry is not None
                    baseline_price = number(samples[key][0].get("executable_price"))
                    favorable_sign = 1 if episode["side"] == "Demand" else -1
                    entry_price = (
                        number(entry.get("executable_price")) if entry else math.nan
                    )
                    improvement = (
                        (baseline_price - entry_price) * favorable_sign
                        if filled
                        else math.nan
                    )
                    outcome = episode["structural_outcome"]
                    output.append(
                        {
                            "session_id": episode["session_id"],
                            "date": episode["date"],
                            "root_id": episode["root_id"],
                            "side": episode["side"],
                            "root_lo": episode.get("root_lo", ""),
                            "root_hi": episode.get("root_hi", ""),
                            "proximity_et": episode.get("proximity_et", ""),
                            "structural_outcome": outcome,
                            "policy": policy_name,
                            "horizon_s": horizon,
                            "filled": filled,
                            "entry_et": entry.get("sample_et", "") if entry else "",
                            "delay_s": number(entry.get("elapsed_s")) if entry else "",
                            "entry_price": entry_price if filled else "",
                            "entry_improvement_pts": round(improvement, 3)
                            if filled
                            else "",
                            "advance_captured": filled and outcome == ADVANCED,
                            "advance_missed": not filled and outcome == ADVANCED,
                            "failure_exposed": filled and outcome == FAILED,
                            "failure_avoided": not filled and outcome == FAILED,
                            "cv_threshold": round(threshold, 6),
                            "train_advance_capture": round(train_capture, 6),
                            "train_failure_exposure": round(train_exposure, 6),
                            "train_selectivity": round(train_selectivity, 6),
                        }
                    )
    return output


def summarize_decisions(
    rows: list[dict[str, Any]],
    group_fields: tuple[str, ...],
) -> list[dict[str, Any]]:
    groups: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[tuple(row[field] for field in group_fields)].append(row)
    output: list[dict[str, Any]] = []
    for key, group in sorted(groups.items()):
        advanced = [row for row in group if row["structural_outcome"] == ADVANCED]
        failed = [row for row in group if row["structural_outcome"] == FAILED]
        success_entries = [row for row in advanced if row["filled"]]
        record = dict(zip(group_fields, key))
        record.update(
            {
                "roots": len(group),
                "advanced_roots": len(advanced),
                "failed_roots": len(failed),
                "filled_roots": sum(bool(row["filled"]) for row in group),
                "advance_capture": sum(bool(row["advance_captured"]) for row in group)
                / len(advanced)
                if advanced
                else math.nan,
                "failure_exposure": sum(bool(row["failure_exposed"]) for row in group)
                / len(failed)
                if failed
                else math.nan,
                "selectivity": (
                    sum(bool(row["advance_captured"]) for row in group) / len(advanced)
                    - sum(bool(row["failure_exposed"]) for row in group) / len(failed)
                )
                if advanced and failed
                else math.nan,
                "success_entry_improvement_pts": median(
                    number(row["entry_improvement_pts"], math.nan)
                    for row in success_entries
                ),
                "success_delay_s": median(
                    number(row["delay_s"], math.nan) for row in success_entries
                ),
            }
        )
        output.append(record)
    return output


def bootstrap_policy(
    rows: list[dict[str, Any]],
    samples: int,
    seed: int = 91027,
) -> list[dict[str, Any]]:
    by_policy: dict[tuple[str, float], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_policy[(row["policy"], row["horizon_s"])].append(row)
    output: list[dict[str, Any]] = []
    randomizer = random.Random(seed)
    for (policy, horizon), group in sorted(by_policy.items()):
        dates = sorted({row["date"] for row in group})
        date_counts: dict[str, Counter[str]] = defaultdict(Counter)
        for row in group:
            counts = date_counts[row["date"]]
            if row["structural_outcome"] == ADVANCED:
                counts["advanced"] += 1
                counts["advance_captured"] += bool(row["advance_captured"])
            elif row["structural_outcome"] == FAILED:
                counts["failed"] += 1
                counts["failure_exposed"] += bool(row["failure_exposed"])
        estimates: list[float] = []
        for _ in range(samples):
            draw = [randomizer.choice(dates) for _ in dates]
            advanced = sum(date_counts[day]["advanced"] for day in draw)
            failed = sum(date_counts[day]["failed"] for day in draw)
            if not advanced or not failed:
                continue
            advance_captured = sum(
                date_counts[day]["advance_captured"] for day in draw
            )
            failure_exposed = sum(
                date_counts[day]["failure_exposed"] for day in draw
            )
            estimates.append(
                advance_captured / advanced - failure_exposed / failed
            )

        leave_one_out: list[float] = []
        for held_out in dates:
            retained = [day for day in dates if day != held_out]
            advanced = sum(date_counts[day]["advanced"] for day in retained)
            failed = sum(date_counts[day]["failed"] for day in retained)
            if advanced and failed:
                advance_captured = sum(
                    date_counts[day]["advance_captured"] for day in retained
                )
                failure_exposed = sum(
                    date_counts[day]["failure_exposed"] for day in retained
                )
                leave_one_out.append(
                    advance_captured / advanced - failure_exposed / failed
                )
        output.append(
            {
                "policy": policy,
                "horizon_s": horizon,
                "bootstrap_low": quantile(estimates, 0.025),
                "bootstrap_high": quantile(estimates, 0.975),
                "leave_one_date_out_low": min(leave_one_out)
                if leave_one_out
                else math.nan,
                "leave_one_date_out_high": max(leave_one_out)
                if leave_one_out
                else math.nan,
                "dates": len(dates),
            }
        )
    return output


FEATURES = {
    "support_net_norm_2s": ("support_net_norm_2p0s", 1),
    "under_net_norm_2s": ("under_net_norm_2p0s", 1),
    "road_clear_norm_2s": ("road_clear_norm_2p0s", 1),
    "owner_under_depth_ratio": ("owner_under_depth_ratio", 1),
    "road_depth_inverse": ("opponent_road_depth_ratio", -1),
    "owner_remove_consumed_share": ("owner_remove_consumed_share_2p0s", -1),
    "road_remove_consumed_share": ("road_remove_consumed_share_2p0s", 1),
    "top5_book_balance": ("top5_book_balance", 1),
}


WAITABILITY_FEATURES = (
    "support_net_norm_0p5s",
    "support_net_norm_2p0s",
    "support_net_norm_5p0s",
    "under_net_norm_0p5s",
    "under_net_norm_2p0s",
    "under_net_norm_5p0s",
    "road_clear_norm_0p5s",
    "road_clear_norm_2p0s",
    "road_clear_norm_5p0s",
    "owner_remove_consumed_share_0p5s",
    "owner_remove_consumed_share_2p0s",
    "owner_remove_consumed_share_5p0s",
    "road_remove_consumed_share_0p5s",
    "road_remove_consumed_share_2p0s",
    "road_remove_consumed_share_5p0s",
    "owner_pull_proxy_0p5s",
    "owner_pull_proxy_2p0s",
    "owner_pull_proxy_5p0s",
    "road_pull_proxy_0p5s",
    "road_pull_proxy_2p0s",
    "road_pull_proxy_5p0s",
    "top5_book_balance",
    "field_book_balance",
    "rail_book_balance",
    "behind_book_balance",
    "bridge_book_balance",
)


def book_balance(
    row: dict[str, str],
    owner_field: str,
    opponent_field: str,
) -> float:
    owner = number(row.get(owner_field))
    opponent = number(row.get(opponent_field))
    return owner / (owner + opponent) if owner + opponent > 1e-9 else 0.5


def waitability_feature_value(row: dict[str, str], feature: str) -> float:
    balance_fields = {
        "top5_book_balance": ("owner_top5_depth", "opponent_top5_depth"),
        "field_book_balance": ("owner_field_depth", "opponent_field_depth"),
        "rail_book_balance": ("owner_rail_depth", "opponent_rail_depth"),
        "behind_book_balance": ("owner_behind_depth", "opponent_behind_depth"),
        "bridge_book_balance": ("owner_bridge_depth", "opponent_bridge_depth"),
    }
    if feature in balance_fields:
        return book_balance(row, *balance_fields[feature])
    return number(row.get(feature))


def delayed_price_improvement(
    episode: dict[str, str],
    baseline: dict[str, str],
    entry: dict[str, str] | None,
) -> float:
    if entry is None:
        return math.nan
    favorable_sign = 1 if episode["side"] == "Demand" else -1
    return (
        number(baseline.get("executable_price"))
        - number(entry.get("executable_price"))
    ) * favorable_sign


def waitability_summary_rows(
    episodes: list[dict[str, str]],
    samples: dict[tuple[str, str, str], list[dict[str, str]]],
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    advanced = [row for row in episodes if row["structural_outcome"] == ADVANCED]
    failed = [row for row in episodes if row["structural_outcome"] == FAILED]
    for delay in WAITABILITY_DELAYS_S:
        advanced_entries = {
            episode_key(row): delayed_entry(
                samples[episode_key(row)],
                delay,
                300.0,
            )
            for row in advanced
        }
        failed_entries = {
            episode_key(row): delayed_entry(
                samples[episode_key(row)],
                delay,
                300.0,
            )
            for row in failed
        }
        improvements = [
            delayed_price_improvement(
                row,
                samples[episode_key(row)][0],
                advanced_entries[episode_key(row)],
            )
            for row in advanced
            if advanced_entries[episode_key(row)] is not None
        ]
        output.append(
            {
                "delay_s": delay,
                "advanced_roots": len(advanced),
                "now_required_advanced": sum(
                    entry is None for entry in advanced_entries.values()
                ),
                "waitable_advanced": sum(
                    entry is not None for entry in advanced_entries.values()
                ),
                "advanced_waitable_rate": (
                    sum(entry is not None for entry in advanced_entries.values())
                    / len(advanced)
                    if advanced
                    else math.nan
                ),
                "failed_roots": len(failed),
                "failed_still_enterable": sum(
                    entry is not None for entry in failed_entries.values()
                ),
                "failed_still_enterable_rate": (
                    sum(entry is not None for entry in failed_entries.values())
                    / len(failed)
                    if failed
                    else math.nan
                ),
                "waitable_advanced_improvement_median_pts": median(improvements),
                "waitable_advanced_improvement_p25_pts": quantile(
                    improvements,
                    0.25,
                ),
                "waitable_advanced_improvement_p75_pts": quantile(
                    improvements,
                    0.75,
                ),
            }
        )
    return output


def waitability_feature_rows(
    episodes: list[dict[str, str]],
    samples: dict[tuple[str, str, str], list[dict[str, str]]],
) -> list[dict[str, Any]]:
    advanced = [row for row in episodes if row["structural_outcome"] == ADVANCED]
    dates = sorted({row["date"] for row in advanced})
    scopes: list[tuple[str, list[dict[str, str]]]] = [("ALL", advanced)]
    scopes.extend(
        (day, [row for row in advanced if row["date"] == day])
        for day in dates
    )
    output: list[dict[str, Any]] = []
    for scope, scope_rows in scopes:
        for delay in WAITABILITY_DELAYS_S:
            labeled = [
                (
                    row,
                    delayed_entry(
                        samples[episode_key(row)],
                        delay,
                        300.0,
                    )
                    is None,
                )
                for row in scope_rows
            ]
            for feature in WAITABILITY_FEATURES:
                now_required = [
                    waitability_feature_value(
                        samples[episode_key(row)][0],
                        feature,
                    )
                    for row, urgent in labeled
                    if urgent
                ]
                waitable = [
                    waitability_feature_value(
                        samples[episode_key(row)][0],
                        feature,
                    )
                    for row, urgent in labeled
                    if not urgent
                ]
                raw_auc = auc(now_required, waitable)
                output.append(
                    {
                        "scope": scope,
                        "delay_s": delay,
                        "feature": feature,
                        "now_required_n": len(now_required),
                        "waitable_n": len(waitable),
                        "raw_auc_now_required_high": raw_auc,
                        "separability_auc": (
                            max(raw_auc, 1.0 - raw_auc)
                            if raw_auc is not None
                            else math.nan
                        ),
                        "now_required_when": (
                            "high"
                            if raw_auc is not None and raw_auc >= 0.5
                            else "low"
                            if raw_auc is not None
                            else ""
                        ),
                        "now_required_median": median(now_required),
                        "waitable_median": median(waitable),
                    }
                )
    return output


def urgency_classifier_stats(
    rows: list[tuple[float, bool]],
    direction: float,
    threshold: float,
) -> tuple[float, float, float, float]:
    urgent = [item for item in rows if item[1]]
    waitable = [item for item in rows if not item[1]]

    def predicted(value: float) -> bool:
        return value * direction >= threshold

    recall = (
        sum(predicted(value) for value, _ in urgent) / len(urgent)
        if urgent
        else math.nan
    )
    specificity = (
        sum(not predicted(value) for value, _ in waitable) / len(waitable)
        if waitable
        else math.nan
    )
    balanced_accuracy = (
        (recall + specificity) / 2.0
        if math.isfinite(recall) and math.isfinite(specificity)
        else math.nan
    )
    predicted_urgent = sum(predicted(value) for value, _ in rows)
    precision = (
        sum(predicted(value) and urgent_label for value, urgent_label in rows)
        / predicted_urgent
        if predicted_urgent
        else math.nan
    )
    return recall, specificity, balanced_accuracy, precision


def train_waitability_rule(
    advanced: list[dict[str, str]],
    samples: dict[tuple[str, str, str], list[dict[str, str]]],
    delay_s: float,
) -> dict[str, Any] | None:
    labels = {
        episode_key(row): delayed_entry(
            samples[episode_key(row)],
            delay_s,
            300.0,
        )
        is None
        for row in advanced
    }
    if len(set(labels.values())) < 2:
        return None
    candidates: list[dict[str, Any]] = []
    for feature in WAITABILITY_FEATURES:
        feature_rows = [
            (
                waitability_feature_value(samples[episode_key(row)][0], feature),
                labels[episode_key(row)],
            )
            for row in advanced
        ]
        values = [value for value, _ in feature_rows]
        for direction in (-1.0, 1.0):
            oriented = [value * direction for value in values]
            thresholds = {
                quantile(oriented, probability)
                for probability in (
                    0.0,
                    0.05,
                    0.1,
                    0.2,
                    0.3,
                    0.4,
                    0.5,
                    0.6,
                    0.7,
                    0.8,
                    0.9,
                    0.95,
                    1.0,
                )
            } - {None}
            if oriented:
                thresholds.add(min(oriented) - 1e-9)
                thresholds.add(max(oriented) + 1e-9)
            for threshold in thresholds:
                recall, specificity, balanced_accuracy, precision = (
                    urgency_classifier_stats(
                        feature_rows,
                        direction,
                        threshold,
                    )
                )
                candidates.append(
                    {
                        "feature": feature,
                        "direction": direction,
                        "threshold": threshold,
                        "urgent_recall": recall,
                        "waitable_specificity": specificity,
                        "balanced_accuracy": balanced_accuracy,
                        "urgent_precision": precision,
                    }
                )
    return max(
        candidates,
        key=lambda row: (
            row["balanced_accuracy"],
            row["urgent_recall"],
            row["waitable_specificity"],
        ),
    )


def cv_waitability_decisions(
    episodes: list[dict[str, str]],
    samples: dict[tuple[str, str, str], list[dict[str, str]]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    dates = sorted({row["date"] for row in episodes})
    if len(dates) < 2:
        return [], []
    decisions: list[dict[str, Any]] = []
    models: list[dict[str, Any]] = []
    for held_out in dates:
        training_advanced = [
            row
            for row in episodes
            if row["date"] != held_out and row["structural_outcome"] == ADVANCED
        ]
        testing = [row for row in episodes if row["date"] == held_out]
        for delay_s in WAITABILITY_DELAYS_S:
            model = train_waitability_rule(
                training_advanced,
                samples,
                delay_s,
            )
            if model is None:
                continue
            models.append(
                {
                    "held_out_date": held_out,
                    "delay_s": delay_s,
                    **model,
                }
            )
            for episode in testing:
                key = episode_key(episode)
                states = samples[key]
                feature_value = waitability_feature_value(
                    states[0],
                    model["feature"],
                )
                predicted_urgent = (
                    feature_value * model["direction"] >= model["threshold"]
                )
                entry = (
                    states[0]
                    if predicted_urgent
                    else delayed_entry(states, delay_s, 300.0)
                )
                filled = entry is not None
                outcome = episode["structural_outcome"]
                actual_urgent = (
                    delayed_entry(states, delay_s, 300.0) is None
                    if outcome == ADVANCED
                    else ""
                )
                improvement = delayed_price_improvement(
                    episode,
                    states[0],
                    entry,
                )
                decisions.append(
                    {
                        "session_id": episode["session_id"],
                        "date": episode["date"],
                        "root_id": episode["root_id"],
                        "side": episode["side"],
                        "root_lo": episode.get("root_lo", ""),
                        "root_hi": episode.get("root_hi", ""),
                        "proximity_et": episode.get("proximity_et", ""),
                        "structural_outcome": outcome,
                        "policy": (
                            "cv_waitability_single_feature_defer_"
                            f"{str(delay_s).replace('.', 'p')}s"
                        ),
                        "horizon_s": 300.0,
                        "filled": filled,
                        "entry_et": entry.get("sample_et", "") if entry else "",
                        "delay_s": number(entry.get("elapsed_s")) if entry else "",
                        "entry_price": (
                            number(entry.get("executable_price"))
                            if entry
                            else ""
                        ),
                        "entry_improvement_pts": (
                            round(improvement, 3) if filled else ""
                        ),
                        "advance_captured": filled and outcome == ADVANCED,
                        "advance_missed": not filled and outcome == ADVANCED,
                        "failure_exposed": filled and outcome == FAILED,
                        "failure_avoided": not filled and outcome == FAILED,
                        "predicted_now_required": predicted_urgent,
                        "actual_now_required": actual_urgent,
                        "cv_feature": model["feature"],
                        "cv_direction": model["direction"],
                        "cv_threshold": round(model["threshold"], 6),
                        "t0_feature_value": round(feature_value, 6),
                        "train_urgent_recall": round(
                            model["urgent_recall"],
                            6,
                        ),
                        "train_waitable_specificity": round(
                            model["waitable_specificity"],
                            6,
                        ),
                        "train_balanced_accuracy": round(
                            model["balanced_accuracy"],
                            6,
                        ),
                    }
                )
    return decisions, models


def waitability_cv_summary_rows(
    decisions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in decisions:
        groups[row["policy"]].append(row)
    output: list[dict[str, Any]] = []
    for policy, rows in sorted(groups.items()):
        advanced = [
            row for row in rows if row["structural_outcome"] == ADVANCED
        ]
        urgent = [row for row in advanced if row["actual_now_required"] is True]
        waitable = [
            row for row in advanced if row["actual_now_required"] is False
        ]
        predicted_urgent = [
            row for row in advanced if row["predicted_now_required"]
        ]
        output.append(
            {
                "policy": policy,
                "advanced_roots": len(advanced),
                "actual_now_required": len(urgent),
                "urgent_recall": (
                    sum(row["predicted_now_required"] for row in urgent)
                    / len(urgent)
                    if urgent
                    else math.nan
                ),
                "waitable_specificity": (
                    sum(
                        not row["predicted_now_required"] for row in waitable
                    )
                    / len(waitable)
                    if waitable
                    else math.nan
                ),
                "balanced_accuracy": (
                    (
                        sum(row["predicted_now_required"] for row in urgent)
                        / len(urgent)
                        + sum(
                            not row["predicted_now_required"]
                            for row in waitable
                        )
                        / len(waitable)
                    )
                    / 2.0
                    if urgent and waitable
                    else math.nan
                ),
                "urgent_precision": (
                    sum(
                        row["actual_now_required"] is True
                        for row in predicted_urgent
                    )
                    / len(predicted_urgent)
                    if predicted_urgent
                    else math.nan
                ),
            }
        )
    return output


def feature_rows(
    episodes: list[dict[str, str]],
    samples: dict[tuple[str, str, str], list[dict[str, str]]],
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    outcomes = {episode_key(row): row["structural_outcome"] for row in episodes}
    for landmark in LANDMARKS_S:
        selected: list[dict[str, str]] = []
        for key, rows in samples.items():
            exact = min(rows, key=lambda row: abs(number(row["elapsed_s"]) - landmark))
            if abs(number(exact["elapsed_s"]) - landmark) <= 0.126:
                record = dict(exact)
                owner = number(record.get("owner_top5_depth"))
                opponent = number(record.get("opponent_top5_depth"))
                record["top5_book_balance"] = (
                    owner / (owner + opponent) if owner + opponent > 1e-9 else 0.5
                )
                selected.append(record)
        for display, (feature, direction) in FEATURES.items():
            positive = [
                number(row.get(feature)) * direction
                for row in selected
                if outcomes[episode_key(row)] == ADVANCED
            ]
            negative = [
                number(row.get(feature)) * direction
                for row in selected
                if outcomes[episode_key(row)] == FAILED
            ]
            output.append(
                {
                    "landmark_s": landmark,
                    "feature": display,
                    "advanced_n": len(positive),
                    "failed_n": len(negative),
                    "auc_supportive": auc(positive, negative),
                    "advanced_median": median(positive),
                    "failed_median": median(negative),
                }
            )
    return output


def state_component(value: float, positive: str, negative: str) -> str:
    if value >= 0.05:
        return positive
    if value <= -0.05:
        return negative
    return "balanced"


def state_code(row: dict[str, str]) -> str:
    support = state_component(
        number(row.get("support_net_norm_2p0s")),
        "stack",
        "erode",
    )
    road = state_component(
        number(row.get("road_clear_norm_2p0s")),
        "clear",
        "rebuild",
    )
    under = state_component(
        number(row.get("under_net_norm_2p0s")),
        "stack",
        "pull",
    )
    return f"S:{support}|R:{road}|U:{under}"


def transition_rows(
    episodes: list[dict[str, str]],
    samples: dict[tuple[str, str, str], list[dict[str, str]]],
) -> list[dict[str, Any]]:
    outcomes = {episode_key(row): row["structural_outcome"] for row in episodes}
    counts: dict[tuple[str, str], Counter[str]] = defaultdict(Counter)
    for key, rows in samples.items():
        early = [row for row in rows if number(row["elapsed_s"]) <= 10.0]
        for left, right in zip(early, early[1:]):
            if abs(number(right["elapsed_s"]) - number(left["elapsed_s"]) - 0.25) > 0.01:
                continue
            counts[(state_code(left), state_code(right))][outcomes[key]] += 1
    output: list[dict[str, Any]] = []
    for (source, target), result in sorted(
        counts.items(),
        key=lambda item: -sum(item[1].values()),
    ):
        total = sum(result.values())
        output.append(
            {
                "from_state": source,
                "to_state": target,
                "transitions": total,
                "advanced_path_transitions": result[ADVANCED],
                "failed_path_transitions": result[FAILED],
                "advanced_path_share": result[ADVANCED] / total if total else math.nan,
            }
        )
    return output


def state_hazard_rows(
    episodes: list[dict[str, str]],
    samples: dict[tuple[str, str, str], list[dict[str, str]]],
) -> list[dict[str, Any]]:
    episode_by_key = {episode_key(row): row for row in episodes}
    counts: dict[str, Counter[str]] = defaultdict(Counter)
    for key, rows in samples.items():
        episode = episode_by_key[key]
        end = parse_time(episode["structural_end_et"])
        outcome = episode["structural_outcome"]
        for row in rows:
            elapsed = number(row.get("elapsed_s"))
            if elapsed > 10.0:
                continue
            sample_time = parse_time(row["sample_et"])
            remaining = (end - sample_time).total_seconds()
            state = state_code(row)
            counts[state]["exposures"] += 1
            if 0.0 < remaining <= 0.25:
                counts[state][outcome] += 1
    output: list[dict[str, Any]] = []
    for state, result in sorted(
        counts.items(),
        key=lambda item: -item[1]["exposures"],
    ):
        exposure_s = result["exposures"] * 0.25
        output.append(
            {
                "state": state,
                "exposure_samples": result["exposures"],
                "exposure_s": exposure_s,
                "advance_absorptions": result[ADVANCED],
                "failure_absorptions": result[FAILED],
                "advance_hazard_per_s": result[ADVANCED] / exposure_s
                if exposure_s
                else math.nan,
                "failure_hazard_per_s": result[FAILED] / exposure_s
                if exposure_s
                else math.nan,
                "net_advance_hazard_per_s": (
                    result[ADVANCED] - result[FAILED]
                )
                / exposure_s
                if exposure_s
                else math.nan,
            }
        )
    return output


def fixture_rows(decisions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    fixtures = {
        ("2026-07-24", "34"),
        ("2026-07-24", "84"),
        ("2026-07-24", "89"),
        ("2026-07-24", "102"),
        ("2026-07-23", "111"),
        ("2026-07-23", "208"),
    }
    return [
        row
        for row in decisions
        if (row["date"], row["root_id"]) in fixtures
        and row["horizon_s"] == 60.0
    ]


def report(
    all_episodes: list[dict[str, str]],
    usable_episodes: list[dict[str, str]],
    policy_summary: list[dict[str, Any]],
    uncertainty: list[dict[str, Any]],
    features: list[dict[str, Any]],
    waitability: list[dict[str, Any]],
    waitability_features: list[dict[str, Any]],
    waitability_cv: list[dict[str, Any]],
    transitions: list[dict[str, Any]],
    hazards: list[dict[str, Any]],
) -> str:
    exclusion_counts = Counter(
        row.get("capture_reason", "")
        for row in all_episodes
        if row.get("capture_status") != "complete"
    )
    lines = [
        "# Direct-Conversion Proximity Book Policy",
        "",
        "The rail supplies location and structural resolution. Profile terrain and time-of-day are absent from all primary features.",
        "",
        "## Population",
        "",
        f"- Structurally resolved roots presented to capture audit: {len(all_episodes)}.",
        f"- Complete proximity/book episodes: {len(usable_episodes)}.",
        f"- Advanced: {sum(row['structural_outcome'] == ADVANCED for row in usable_episodes)}; failed: {sum(row['structural_outcome'] == FAILED for row in usable_episodes)}.",
        "",
        "| exclusion | roots |",
        "|---|---:|",
    ]
    for reason, count in exclusion_counts.most_common():
        lines.append(f"| {reason or 'unknown'} | {count} |")

    focus = [
        row
        for row in policy_summary
        if row["horizon_s"] in {30.0, 60.0, 120.0}
    ]
    lines.extend(
        [
            "",
            "## Market Versus Wait",
            "",
            "| horizon | policy | roots | advance capture | failure exposure | selectivity | success improvement | success delay |",
            "|---:|---|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for row in focus:
        lines.append(
            f"| {fmt(row['horizon_s'], 0)} | {row['policy']} | {row['roots']} | "
            f"{fmt(row['advance_capture'])} | {fmt(row['failure_exposure'])} | "
            f"{fmt(row['selectivity'])} | "
            f"{fmt(row['success_entry_improvement_pts'])} | "
            f"{fmt(row['success_delay_s'])} |"
        )

    robust = [
        row
        for row in uncertainty
        if row["horizon_s"] == 60.0
    ]
    lines.extend(
        [
            "",
            "## Date Robustness At 60 Seconds",
            "",
            "| policy | bootstrap 95% | leave-one-date-out |",
            "|---|---:|---:|",
        ]
    )
    for row in robust:
        lines.append(
            f"| {row['policy']} | {fmt(row['bootstrap_low'])} to "
            f"{fmt(row['bootstrap_high'])} | {fmt(row['leave_one_date_out_low'])} "
            f"to {fmt(row['leave_one_date_out_high'])} |"
        )

    lines.extend(
        [
            "",
            "## State Information",
            "",
            "AUC is oriented so values above 0.5 mean the named supportive direction was more common on advancing roots.",
            "",
            "| landmark | feature | advanced/failed | AUC | advanced median | failed median |",
            "|---:|---|---:|---:|---:|---:|",
        ]
    )
    for row in features:
        if row["landmark_s"] not in {0.0, 2.0, 5.0}:
            continue
        lines.append(
            f"| {fmt(row['landmark_s'], 1)} | {row['feature']} | "
            f"{row['advanced_n']}/{row['failed_n']} | "
            f"{fmt(row['auc_supportive'])} | {fmt(row['advanced_median'])} | "
            f"{fmt(row['failed_median'])} |"
        )

    lines.extend(
        [
            "",
            "## Immediate Versus Waitable Advances",
            "",
            "Now-required means an advancing root offered no later quote inside the 20-tick envelope after the stated delay and before structural advance.",
            "",
            "| delay | now required / advances | advanced waitable | failures still enterable | waitable improvement p25 / median / p75 |",
            "|---:|---:|---:|---:|---:|",
        ]
    )
    for row in waitability:
        lines.append(
            f"| {fmt(row['delay_s'], 1)} | "
            f"{row['now_required_advanced']} / {row['advanced_roots']} | "
            f"{fmt(row['advanced_waitable_rate'])} | "
            f"{fmt(row['failed_still_enterable_rate'])} | "
            f"{fmt(row['waitable_advanced_improvement_p25_pts'])} / "
            f"{fmt(row['waitable_advanced_improvement_median_pts'])} / "
            f"{fmt(row['waitable_advanced_improvement_p75_pts'])} |"
        )

    aggregate_waitability_features = [
        row for row in waitability_features if row["scope"] == "ALL"
    ]
    best_by_delay = []
    for delay in WAITABILITY_DELAYS_S:
        candidates = [
            row
            for row in aggregate_waitability_features
            if row["delay_s"] == delay
            and math.isfinite(number(row["separability_auc"], math.nan))
        ]
        if candidates:
            best_by_delay.append(
                max(candidates, key=lambda row: row["separability_auc"])
            )
    lines.extend(
        [
            "",
            "Best in-sample first-proximity feature for each urgency horizon:",
            "",
            "| delay | feature | urgent/waitable | separability AUC | urgent when | medians urgent / waitable |",
            "|---:|---|---:|---:|---|---:|",
        ]
    )
    for row in best_by_delay:
        lines.append(
            f"| {fmt(row['delay_s'], 1)} | {row['feature']} | "
            f"{row['now_required_n']}/{row['waitable_n']} | "
            f"{fmt(row['separability_auc'])} | {row['now_required_when']} | "
            f"{fmt(row['now_required_median'])} / "
            f"{fmt(row['waitable_median'])} |"
        )

    lines.extend(
        [
            "",
            "Leave-one-date-out urgency classification:",
            "",
            "| policy | now required | recall | waitable specificity | balanced accuracy | precision |",
            "|---|---:|---:|---:|---:|---:|",
        ]
    )
    for row in waitability_cv:
        lines.append(
            f"| {row['policy']} | {row['actual_now_required']} | "
            f"{fmt(row['urgent_recall'])} | "
            f"{fmt(row['waitable_specificity'])} | "
            f"{fmt(row['balanced_accuracy'])} | "
            f"{fmt(row['urgent_precision'])} |"
        )

    lines.extend(
        [
            "",
            "## Transition Coverage",
            "",
            f"- Early 250 ms Markov-state transitions: {sum(row['transitions'] for row in transitions)}.",
            f"- Distinct observed transitions: {len(transitions)}.",
            f"- States with measured absorbing hazards: {sum(row['advance_absorptions'] + row['failure_absorptions'] > 0 for row in hazards)}.",
            "- State transitions are descriptive. Repeated samples within roots are not independent observations.",
            "",
            "## Interpretation Boundary",
            "",
            "- Quote removals are observed exactly; removal minus tape consumption is only a pulling proxy.",
            "- Policies are counterfactual because EAR size is negligible relative to NQ and does not alter the captured book materially.",
            "- Structural advance/failure is the outcome. Fixed favorable tick excursions are not used as success labels.",
            "- The 300-second collection limit is reported through horizon sensitivity and structural-after-horizon flags.",
            "- No EAR or LevelLedger runtime behavior changed.",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> None:
    args = parse_args()
    all_episodes = input_rows(args.input_dir, "episode_summary.csv")
    episodes, samples = load_population(args.input_dir)
    decisions = decision_rows(episodes, samples)
    decisions.extend(delay_decision_rows(episodes, samples))
    decisions.extend(cv_score_decisions(episodes, samples))
    decisions.extend(cv_urgency_decisions(episodes, samples))
    waitability_decisions, waitability_models = cv_waitability_decisions(
        episodes,
        samples,
    )
    decisions.extend(waitability_decisions)
    policy_summary = summarize_decisions(decisions, ("horizon_s", "policy"))
    daily_summary = summarize_decisions(
        decisions,
        ("date", "horizon_s", "policy"),
    )
    uncertainty = bootstrap_policy(decisions, args.bootstrap_samples)
    features = feature_rows(episodes, samples)
    waitability = waitability_summary_rows(episodes, samples)
    waitability_features = waitability_feature_rows(episodes, samples)
    waitability_cv = waitability_cv_summary_rows(waitability_decisions)
    transitions = transition_rows(episodes, samples)
    hazards = state_hazard_rows(episodes, samples)
    fixtures = fixture_rows(decisions)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    write_csv(args.out_dir / "policy_decisions.csv", decisions)
    write_csv(args.out_dir / "policy_summary.csv", policy_summary)
    write_csv(args.out_dir / "daily_policy_summary.csv", daily_summary)
    write_csv(args.out_dir / "policy_uncertainty.csv", uncertainty)
    write_csv(args.out_dir / "state_feature_audit.csv", features)
    write_csv(args.out_dir / "waitability_summary.csv", waitability)
    write_csv(
        args.out_dir / "waitability_feature_audit.csv",
        waitability_features,
    )
    write_csv(args.out_dir / "waitability_cv_models.csv", waitability_models)
    write_csv(args.out_dir / "waitability_cv_summary.csv", waitability_cv)
    write_csv(args.out_dir / "markov_transitions.csv", transitions)
    write_csv(args.out_dir / "state_absorption_hazards.csv", hazards)
    write_csv(args.out_dir / "fixture_policy.csv", fixtures)
    findings = report(
        all_episodes,
        episodes,
        policy_summary,
        uncertainty,
        features,
        waitability,
        waitability_features,
        waitability_cv,
        transitions,
        hazards,
    )
    (args.out_dir / "findings.md").write_text(findings, encoding="utf-8")
    print(findings)
    print(
        f"wrote {args.out_dir} episodes={len(episodes)} "
        f"decisions={len(decisions)} transitions={len(transitions)}"
    )


if __name__ == "__main__":
    main()
