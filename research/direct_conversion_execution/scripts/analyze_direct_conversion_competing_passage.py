"""Audit event-time execution paths after direct-conversion proximity.

The first executable quote inside EAR's 20-tick envelope starts a competing
passage process.  Price can escape favorably beyond the envelope, challenge
back toward the consumed rail, or remain unresolved.  Entries are evaluated
only on subsequent observable return/recovery events and use structural
successor ownership versus root failure as the outcome.
"""

from __future__ import annotations

import argparse
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from _paths import OUTPUT_ROOT
from analyze_direct_conversion_proximity_policy import (
    ADVANCED,
    FAILED,
    WAITABILITY_FEATURES,
    auc,
    bootstrap_policy,
    delayed_price_improvement,
    episode_key,
    fmt,
    load_population,
    median,
    number,
    quantile,
    summarize_decisions,
    truth,
    waitability_feature_value,
    write_csv,
)


DEFAULT_INPUT = (
    OUTPUT_ROOT
    / "direct_conversion_proximity_book_20260717_20260724"
)
DEFAULT_OUT = (
    OUTPUT_ROOT
    / "direct_conversion_competing_passage_20260717_20260724"
)
CHALLENGE_TICKS = (4, 8, 12)
HORIZONS_S = (5.0, 15.0, 30.0, 60.0, 300.0)
ESCAPE_TICKS = 1
RECOVERY_PROGRESS_TICKS = -2


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    return parser.parse_args()


def first_passage(
    rows: list[dict[str, str]],
    challenge_ticks: int,
    horizon_s: float,
) -> tuple[str, dict[str, str] | None]:
    for row in rows[1:]:
        elapsed = number(row.get("elapsed_s"))
        if elapsed > horizon_s:
            break
        progress = number(row.get("quote_progress_ticks"))
        if progress >= ESCAPE_TICKS:
            return "escape_first", row
        if progress <= -challenge_ticks:
            return "challenge_first", row
    return "unresolved", None


def first_return_inside(
    rows: list[dict[str, str]],
    after_elapsed_s: float,
    horizon_s: float,
) -> dict[str, str] | None:
    left_envelope = False
    for row in rows:
        elapsed = number(row.get("elapsed_s"))
        if elapsed < after_elapsed_s:
            continue
        if elapsed > horizon_s:
            break
        if not truth(row.get("inside_20_ticks")):
            left_envelope = True
            continue
        if left_envelope:
            return row
    return None


def first_challenge_recovery(
    rows: list[dict[str, str]],
    after_elapsed_s: float,
    horizon_s: float,
) -> dict[str, str] | None:
    for row in rows:
        elapsed = number(row.get("elapsed_s"))
        if elapsed <= after_elapsed_s:
            continue
        if elapsed > horizon_s:
            break
        progress = number(row.get("quote_progress_ticks"))
        if (
            progress >= RECOVERY_PROGRESS_TICKS
            and progress <= 0
            and truth(row.get("inside_20_ticks"))
        ):
            return row
    return None


def path_events(
    rows: list[dict[str, str]],
    challenge_ticks: int,
    horizon_s: float,
) -> dict[str, Any]:
    passage, passage_row = first_passage(rows, challenge_ticks, horizon_s)
    escape_return = None
    challenge_recovery = None
    if passage_row is not None and passage == "escape_first":
        escape_return = first_return_inside(
            rows,
            number(passage_row.get("elapsed_s")),
            horizon_s,
        )
    elif passage_row is not None and passage == "challenge_first":
        challenge_recovery = first_challenge_recovery(
            rows,
            number(passage_row.get("elapsed_s")),
            horizon_s,
        )
    return {
        "passage": passage,
        "passage_row": passage_row,
        "escape_return": escape_return,
        "challenge_recovery": challenge_recovery,
        "retest": escape_return or challenge_recovery,
    }


def passage_rows(
    episodes: list[dict[str, str]],
    samples: dict[tuple[str, str, str], list[dict[str, str]]],
) -> list[dict[str, Any]]:
    counts: dict[tuple[float, int, str, str], int] = Counter()
    denominators = Counter(row["structural_outcome"] for row in episodes)
    for horizon in HORIZONS_S:
        for challenge in CHALLENGE_TICKS:
            for episode in episodes:
                event = path_events(
                    samples[episode_key(episode)],
                    challenge,
                    horizon,
                )
                counts[
                    (
                        horizon,
                        challenge,
                        event["passage"],
                        episode["structural_outcome"],
                    )
                ] += 1
    output: list[dict[str, Any]] = []
    for horizon in HORIZONS_S:
        for challenge in CHALLENGE_TICKS:
            for passage in ("escape_first", "challenge_first", "unresolved"):
                advanced = counts[(horizon, challenge, passage, ADVANCED)]
                failed = counts[(horizon, challenge, passage, FAILED)]
                advanced_share = advanced / denominators[ADVANCED]
                failed_share = failed / denominators[FAILED]
                output.append(
                    {
                        "horizon_s": horizon,
                        "challenge_ticks": challenge,
                        "passage": passage,
                        "advanced_roots": advanced,
                        "failed_roots": failed,
                        "advanced_share": advanced_share,
                        "failed_share": failed_share,
                        "selectivity": advanced_share - failed_share,
                    }
                )
    return output


def make_decision(
    episode: dict[str, str],
    states: list[dict[str, str]],
    policy: str,
    horizon_s: float,
    challenge_ticks: int,
    entry: dict[str, str] | None,
    passage: str,
) -> dict[str, Any]:
    filled = entry is not None
    outcome = episode["structural_outcome"]
    improvement = delayed_price_improvement(episode, states[0], entry)
    return {
        "session_id": episode["session_id"],
        "date": episode["date"],
        "root_id": episode["root_id"],
        "side": episode["side"],
        "root_lo": episode.get("root_lo", ""),
        "root_hi": episode.get("root_hi", ""),
        "proximity_et": episode.get("proximity_et", ""),
        "structural_outcome": outcome,
        "structural_end_et": episode.get("structural_end_et", ""),
        "post_proximity_successor_id": episode.get(
            "post_proximity_successor_id",
            "",
        ),
        "post_proximity_successor_source": episode.get(
            "post_proximity_successor_source",
            "",
        ),
        "policy": policy,
        "horizon_s": horizon_s,
        "challenge_ticks": challenge_ticks,
        "first_passage": passage,
        "filled": filled,
        "entry_et": entry.get("sample_et", "") if entry else "",
        "delay_s": number(entry.get("elapsed_s")) if entry else "",
        "entry_price": number(entry.get("executable_price")) if entry else "",
        "entry_improvement_pts": round(improvement, 3) if filled else "",
        "advance_captured": filled and outcome == ADVANCED,
        "advance_missed": not filled and outcome == ADVANCED,
        "failure_exposed": filled and outcome == FAILED,
        "failure_avoided": not filled and outcome == FAILED,
    }


def policy_rows(
    episodes: list[dict[str, str]],
    samples: dict[tuple[str, str, str], list[dict[str, str]]],
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for horizon in HORIZONS_S:
        for challenge in CHALLENGE_TICKS:
            for episode in episodes:
                states = samples[episode_key(episode)]
                events = path_events(states, challenge, horizon)
                passage_row = events["passage_row"]
                challenge_entry = (
                    passage_row
                    if events["passage"] == "challenge_first"
                    and passage_row is not None
                    and truth(passage_row.get("inside_20_ticks"))
                    else None
                )
                entries = {
                    "challenge_entry": challenge_entry,
                    "challenge_recovery": events["challenge_recovery"],
                    "escape_return": events["escape_return"],
                    "competing_retest": events["retest"],
                }
                for policy, entry in entries.items():
                    output.append(
                        make_decision(
                            episode,
                            states,
                            policy,
                            horizon,
                            challenge,
                            entry,
                            events["passage"],
                        )
                    )
    return output


def retest_feature_rows(
    episodes: list[dict[str, str]],
    samples: dict[tuple[str, str, str], list[dict[str, str]]],
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for challenge in CHALLENGE_TICKS:
        events_by_type: dict[
            str,
            list[tuple[dict[str, str], dict[str, str]]],
        ] = defaultdict(list)
        for episode in episodes:
            events = path_events(
                samples[episode_key(episode)],
                challenge,
                300.0,
            )
            if events["escape_return"] is not None:
                events_by_type["escape_return"].append(
                    (episode, events["escape_return"])
                )
            if events["challenge_recovery"] is not None:
                events_by_type["challenge_recovery"].append(
                    (episode, events["challenge_recovery"])
                )
        for event_type, rows in events_by_type.items():
            for feature in WAITABILITY_FEATURES:
                advanced = [
                    waitability_feature_value(event, feature)
                    for episode, event in rows
                    if episode["structural_outcome"] == ADVANCED
                ]
                failed = [
                    waitability_feature_value(event, feature)
                    for episode, event in rows
                    if episode["structural_outcome"] == FAILED
                ]
                raw_auc = auc(advanced, failed)
                output.append(
                    {
                        "challenge_ticks": challenge,
                        "event_type": event_type,
                        "feature": feature,
                        "advanced_n": len(advanced),
                        "failed_n": len(failed),
                        "raw_auc_advanced_high": raw_auc,
                        "separability_auc": (
                            max(raw_auc, 1.0 - raw_auc)
                            if raw_auc is not None
                            else math.nan
                        ),
                        "advanced_when": (
                            "high"
                            if raw_auc is not None and raw_auc >= 0.5
                            else "low"
                            if raw_auc is not None
                            else ""
                        ),
                        "advanced_median": median(advanced),
                        "failed_median": median(failed),
                    }
                )
    return output


def retest_opportunity(
    episode: dict[str, str],
    samples: dict[tuple[str, str, str], list[dict[str, str]]],
    event_type: str,
) -> dict[str, str] | None:
    events = path_events(samples[episode_key(episode)], 8, 60.0)
    return events[event_type]


def train_retest_rule(
    episodes: list[dict[str, str]],
    samples: dict[tuple[str, str, str], list[dict[str, str]]],
    event_type: str,
    target_advance_capture: float,
) -> dict[str, Any] | None:
    opportunities = [
        (episode, retest_opportunity(episode, samples, event_type))
        for episode in episodes
    ]
    opportunities = [
        (episode, event)
        for episode, event in opportunities
        if event is not None
    ]
    advanced = [
        (episode, event)
        for episode, event in opportunities
        if episode["structural_outcome"] == ADVANCED
    ]
    failed = [
        (episode, event)
        for episode, event in opportunities
        if episode["structural_outcome"] == FAILED
    ]
    if not advanced or not failed:
        return None
    candidates: list[dict[str, Any]] = []
    for feature in WAITABILITY_FEATURES:
        values = [
            waitability_feature_value(event, feature)
            for _, event in opportunities
        ]
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
                def accepted(event: dict[str, str]) -> bool:
                    return (
                        waitability_feature_value(event, feature) * direction
                        >= threshold
                    )

                advance_capture = (
                    sum(accepted(event) for _, event in advanced)
                    / len(advanced)
                )
                failure_exposure = (
                    sum(accepted(event) for _, event in failed) / len(failed)
                )
                candidates.append(
                    {
                        "feature": feature,
                        "direction": direction,
                        "threshold": threshold,
                        "conditional_advance_capture": advance_capture,
                        "conditional_failure_exposure": failure_exposure,
                        "conditional_selectivity": (
                            advance_capture - failure_exposure
                        ),
                        "advanced_opportunities": len(advanced),
                        "failed_opportunities": len(failed),
                    }
                )
    eligible = [
        row
        for row in candidates
        if row["conditional_advance_capture"] >= target_advance_capture
    ]
    if not eligible:
        eligible = candidates
    return max(
        eligible,
        key=lambda row: (
            row["conditional_selectivity"],
            -row["conditional_failure_exposure"],
            row["conditional_advance_capture"],
        ),
    )


def cv_retest_policy_rows(
    episodes: list[dict[str, str]],
    samples: dict[tuple[str, str, str], list[dict[str, str]]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    dates = sorted({row["date"] for row in episodes})
    decisions: list[dict[str, Any]] = []
    models: list[dict[str, Any]] = []
    for held_out in dates:
        training = [row for row in episodes if row["date"] != held_out]
        testing = [row for row in episodes if row["date"] == held_out]
        for event_type in ("escape_return", "challenge_recovery"):
            model = train_retest_rule(
                training,
                samples,
                event_type,
                0.7,
            )
            if model is None:
                continue
            models.append(
                {
                    "held_out_date": held_out,
                    "event_type": event_type,
                    "target_advance_capture": 0.7,
                    **model,
                }
            )
            for episode in testing:
                states = samples[episode_key(episode)]
                events = path_events(states, 8, 60.0)
                opportunity = events[event_type]
                accepted = (
                    opportunity is not None
                    and waitability_feature_value(
                        opportunity,
                        model["feature"],
                    )
                    * model["direction"]
                    >= model["threshold"]
                )
                entry = opportunity if accepted else None
                decision = make_decision(
                    episode,
                    states,
                    f"cv_{event_type}_book_capture_70",
                    60.0,
                    8,
                    entry,
                    events["passage"],
                )
                decision.update(
                    {
                        "retest_opportunity": opportunity is not None,
                        "retest_et": (
                            opportunity.get("sample_et", "")
                            if opportunity is not None
                            else ""
                        ),
                        "retest_elapsed_s": (
                            number(opportunity.get("elapsed_s"))
                            if opportunity is not None
                            else ""
                        ),
                        "retest_price": (
                            number(opportunity.get("executable_price"))
                            if opportunity is not None
                            else ""
                        ),
                        "retest_distance_ticks": (
                            number(opportunity.get("distance_ticks"))
                            if opportunity is not None
                            else ""
                        ),
                        "retest_owner_field_add_2s": (
                            number(
                                opportunity.get(
                                    "book_owner_field_add_2p0s",
                                )
                            )
                            if opportunity is not None
                            else ""
                        ),
                        "retest_owner_field_remove_2s": (
                            number(
                                opportunity.get(
                                    "book_owner_field_remove_2p0s",
                                )
                            )
                            if opportunity is not None
                            else ""
                        ),
                        "retest_support_net_norm_2s": (
                            number(
                                opportunity.get(
                                    "support_net_norm_2p0s",
                                )
                            )
                            if opportunity is not None
                            else ""
                        ),
                        "cv_feature": model["feature"],
                        "cv_direction": model["direction"],
                        "cv_threshold": round(model["threshold"], 6),
                        "retest_feature_value": (
                            round(
                                waitability_feature_value(
                                    opportunity,
                                    model["feature"],
                                ),
                                6,
                            )
                            if opportunity is not None
                            else ""
                        ),
                        "train_conditional_advance_capture": round(
                            model["conditional_advance_capture"],
                            6,
                        ),
                        "train_conditional_failure_exposure": round(
                            model["conditional_failure_exposure"],
                            6,
                        ),
                        "train_conditional_selectivity": round(
                            model["conditional_selectivity"],
                            6,
                        ),
                    }
                )
                decisions.append(decision)
    return decisions, models


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
        and row["challenge_ticks"] == 8
    ]


def report(
    episodes: list[dict[str, str]],
    passages: list[dict[str, Any]],
    policies: list[dict[str, Any]],
    feature_rows: list[dict[str, Any]],
    cv_uncertainty: list[dict[str, Any]],
) -> str:
    policy_summary = summarize_decisions(
        policies,
        ("horizon_s", "challenge_ticks", "policy"),
    )
    focus_passages = [
        row
        for row in passages
        if row["horizon_s"] == 60.0 and row["challenge_ticks"] == 8
    ]
    focus_policies = [
        row
        for row in policy_summary
        if row["horizon_s"] == 60.0 and row["challenge_ticks"] == 8
    ]
    best_features: list[dict[str, Any]] = []
    for event_type in ("escape_return", "challenge_recovery"):
        candidates = [
            row
            for row in feature_rows
            if row["challenge_ticks"] == 8
            and row["event_type"] == event_type
            and math.isfinite(number(row["separability_auc"], math.nan))
        ]
        best_features.extend(
            sorted(
                candidates,
                key=lambda row: row["separability_auc"],
                reverse=True,
            )[:5]
        )
    lines = [
        "# Direct-Conversion Competing Passage",
        "",
        "This audit uses event-time price passage and contemporaneous L2 only. Profile terrain and clock time are absent.",
        "",
        "## Population",
        "",
        f"- Complete proximity/book episodes: {len(episodes)}.",
        f"- Advanced: {sum(row['structural_outcome'] == ADVANCED for row in episodes)}; failed: {sum(row['structural_outcome'] == FAILED for row in episodes)}.",
        "",
        "## First Passage At 60 Seconds",
        "",
        "Escape means the executable quote moved favorable of the 20-tick envelope. Challenge means it moved eight ticks back toward the rail.",
        "",
        "| first event | advances | failures | advance share | failure share | selectivity |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for row in focus_passages:
        lines.append(
            f"| {row['passage']} | {row['advanced_roots']} | "
            f"{row['failed_roots']} | {fmt(row['advanced_share'])} | "
            f"{fmt(row['failed_share'])} | {fmt(row['selectivity'])} |"
        )
    lines.extend(
        [
            "",
            "## Event-Time Entry Policies",
            "",
            "| policy | advance capture | failure exposure | selectivity | success improvement | delay |",
            "|---|---:|---:|---:|---:|---:|",
        ]
    )
    for row in focus_policies:
        lines.append(
            f"| {row['policy']} | {fmt(row['advance_capture'])} | "
            f"{fmt(row['failure_exposure'])} | {fmt(row['selectivity'])} | "
            f"{fmt(row['success_entry_improvement_pts'])} | "
            f"{fmt(row['success_delay_s'])} |"
        )
    lines.extend(
        [
            "",
            "Held-out policy date-cluster uncertainty:",
            "",
            "| policy | bootstrap 95% | leave-one-date-out |",
            "|---|---:|---:|",
        ]
    )
    for row in cv_uncertainty:
        lines.append(
            f"| {row['policy']} | {fmt(row['bootstrap_low'])} to "
            f"{fmt(row['bootstrap_high'])} | "
            f"{fmt(row['leave_one_date_out_low'])} to "
            f"{fmt(row['leave_one_date_out_high'])} |"
        )
    lines.extend(
        [
            "",
            "## Book At The Retest",
            "",
            "| retest | feature | advanced/failed | separability AUC | advanced when | medians advanced / failed |",
            "|---|---|---:|---:|---|---:|",
        ]
    )
    for row in best_features:
        lines.append(
            f"| {row['event_type']} | {row['feature']} | "
            f"{row['advanced_n']}/{row['failed_n']} | "
            f"{fmt(row['separability_auc'])} | {row['advanced_when']} | "
            f"{fmt(row['advanced_median'])} / {fmt(row['failed_median'])} |"
        )
    lines.extend(
        [
            "",
            "## Boundary",
            "",
            "- First-passage thresholds are reported at 4, 8, and 12 ticks; no single threshold is promoted from this sample.",
            "- Escape-return and challenge-recovery are observable execution events, not claims that the future structural outcome is known.",
            "- Book feature rankings are in-sample diagnostics; the cv policies train on five dates and act only on the held-out sixth date.",
            "- No EAR or LevelLedger runtime behavior changed.",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> None:
    args = parse_args()
    episodes, samples = load_population(args.input_dir)
    passages = passage_rows(episodes, samples)
    decisions = policy_rows(episodes, samples)
    cv_decisions, cv_models = cv_retest_policy_rows(episodes, samples)
    decisions.extend(cv_decisions)
    policy_summary = summarize_decisions(
        decisions,
        ("horizon_s", "challenge_ticks", "policy"),
    )
    daily_summary = summarize_decisions(
        decisions,
        ("date", "horizon_s", "challenge_ticks", "policy"),
    )
    features = retest_feature_rows(episodes, samples)
    cv_uncertainty = bootstrap_policy(cv_decisions, 10_000)
    fixtures = fixture_rows(decisions)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    write_csv(args.out_dir / "first_passage_summary.csv", passages)
    write_csv(args.out_dir / "policy_decisions.csv", decisions)
    write_csv(args.out_dir / "policy_summary.csv", policy_summary)
    write_csv(args.out_dir / "daily_policy_summary.csv", daily_summary)
    write_csv(args.out_dir / "retest_feature_audit.csv", features)
    write_csv(args.out_dir / "retest_cv_models.csv", cv_models)
    write_csv(args.out_dir / "retest_cv_uncertainty.csv", cv_uncertainty)
    write_csv(args.out_dir / "fixture_paths.csv", fixtures)
    findings = report(
        episodes,
        passages,
        decisions,
        features,
        cv_uncertainty,
    )
    (args.out_dir / "findings.md").write_text(findings, encoding="utf-8")
    print(findings)
    print(
        f"wrote {args.out_dir} episodes={len(episodes)} "
        f"decisions={len(decisions)}"
    )


if __name__ == "__main__":
    main()
