"""Replay every material step-back in a direct-conversion root lifecycle.

The entry-level auction-road probe showed that one snapshot cannot represent a
campaign: an early return can readvance while a later return through the same
root fails. This probe makes the return episode the measurement atom.

Each step begins when price retraces a fixed number of ticks from the current
favorable peak. It resolves when price readvances to that peak, a favorable
sponsor forms, or the consumed root fails. While the step is still active, the
book underneath current price is sampled at fixed causal checkpoints.
"""

from __future__ import annotations

import argparse
import bisect
import csv
import math
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from statistics import median
from typing import Any

from _paths import OUTPUT_ROOT
from capture_loader import load_capture_window, tick_columns
from direct_conversion_auction_road import (
    ASK,
    BID,
    CHECKPOINT_MS,
    NY,
    TICK_SIZE,
    Phase,
    Study,
    aggregate_phase,
    auc,
    fnum,
    fmt,
    load_studies,
    parse_et,
    phase_valid,
    replay_day,
    resolve_attack_window,
    signed_ticks,
    to_us,
    write_csv,
)

DEFAULT_LINEAGE = (
    OUTPUT_ROOT / "direct_conversion_sponsor_lineage" / "lineage.csv"
)


@dataclass
class Step:
    idx: int
    root: Study
    ordinal: int
    peak_tick: int
    peak_us: int
    start_tick: int
    start_us: int
    resolution_tick: int
    resolution_us: int
    resolution: str
    relation: str
    prior_depths: tuple[int, ...]
    entry_tick: int | None = None
    checkpoint_ticks: dict[int, int] = field(default_factory=dict)
    phases: dict[str, Phase] = field(default_factory=dict)

    @property
    def direction(self) -> int:
        return self.root.direction

    @property
    def success(self) -> bool:
        return self.resolution != "ROOT_FAILED"


def terminal_event(root: Study) -> tuple[int | None, str]:
    row = root.row
    if row.get("entry_structural_outcome") == "ADVANCED_AFTER_ENTRY":
        value = (
            row.get("post_entry_successor_owned_et")
            or row.get("favorable_successor_owned_et")
        )
        return (
            to_us(parse_et(value).astimezone(root.conversion.ts_utc.tzinfo))
            if value
            else None,
            "SPONSOR_ADVANCED",
        )
    if row.get("entry_structural_outcome") == "ROOT_FAILED_AFTER_ENTRY":
        return root.root_failed_us, "ROOT_FAILED"
    return None, "UNRESOLVED"


def relation_to_entry(
    entry_us: int | None,
    start_us: int,
    resolution_us: int,
) -> str:
    if entry_us is None:
        return "NO_ENTRY"
    if resolution_us <= entry_us:
        return "PRE_ENTRY"
    if start_us <= entry_us <= resolution_us:
        return "ENTRY_STEP"
    return "POST_ENTRY"


def populate_phase_tape(
    root: Study,
    phase: Phase,
    times: list[int],
    ticks: list[int],
    sizes: list[float],
    signs: list[int],
) -> None:
    lo = bisect.bisect_left(times, phase.start_us)
    hi = bisect.bisect_right(times, phase.end_us)
    for i in range(lo, hi):
        level = phase.levels.get(ticks[i])
        if level is None:
            continue
        qty = sizes[i]
        if signs[i] == root.direction:
            level.favorable_trade_qty += qty
            if level.first_favorable_trade_us is None:
                level.first_favorable_trade_us = times[i]
        elif signs[i] == -root.direction:
            level.adverse_trade_qty += qty


def add_step_phases(
    step: Step,
    times: list[int],
    ticks: list[int],
    sizes: list[float],
    signs: list[int],
    zone_ticks: int,
) -> None:
    root = step.root

    def add_phase(name: str, start_us: int, end_us: int, ref_tick: int) -> None:
        if end_us <= start_us:
            return
        adverse_tick = ref_tick - root.direction * zone_ticks
        phase = Phase(
            study_idx=step.idx,
            name=name,
            start_us=start_us,
            end_us=end_us,
            lo_tick=min(ref_tick, adverse_tick),
            hi_tick=max(ref_tick, adverse_tick),
            winner_side=root.conversion.winner_side,
            loser_side=root.conversion.loser_side,
        )
        populate_phase_tape(root, phase, times, ticks, sizes, signs)
        step.phases[name] = phase

    add_phase("onset", step.peak_us, step.start_us, step.start_tick)
    add_phase(
        "resolution",
        step.start_us,
        step.resolution_us,
        step.resolution_tick,
    )
    if (
        step.relation == "ENTRY_STEP"
        and step.root.first_entry_us is not None
    ):
        entry_i = bisect.bisect_right(times, step.root.first_entry_us) - 1
        if entry_i >= 0:
            step.entry_tick = ticks[entry_i]
            add_phase(
                "entry_state",
                step.start_us,
                step.root.first_entry_us,
                step.entry_tick,
            )
    for checkpoint_ms in CHECKPOINT_MS:
        checkpoint_us = step.start_us + checkpoint_ms * 1_000
        if checkpoint_us >= step.resolution_us:
            continue
        checkpoint_i = bisect.bisect_right(times, checkpoint_us) - 1
        if checkpoint_i < 0:
            continue
        checkpoint_tick = ticks[checkpoint_i]
        step.checkpoint_ticks[checkpoint_ms] = checkpoint_tick
        add_phase(
            f"checkpoint_{checkpoint_ms}ms",
            step.start_us,
            checkpoint_us,
            checkpoint_tick,
        )


def segment_steps(
    root: Study,
    times: list[int],
    ticks: list[int],
    sizes: list[float],
    signs: list[int],
    step_ticks: int,
    zone_ticks: int,
    next_idx: int,
) -> list[Step]:
    resolve_attack_window(
        root.conversion,
        times,
        [tick * TICK_SIZE for tick in ticks],
    )
    terminal_us, terminal_label = terminal_event(root)
    if terminal_us is None:
        return []

    lo = bisect.bisect_left(times, root.conversion.break_us)
    hi = bisect.bisect_right(times, terminal_us)
    peak_tick: int | None = None
    peak_us: int | None = None
    return_peak: int | None = None
    return_peak_us: int | None = None
    start_tick: int | None = None
    start_us: int | None = None
    trough_tick: int | None = None
    in_return = False
    prior_depths: list[int] = []
    steps: list[Step] = []

    def emit(
        resolution_tick: int,
        resolution_us: int,
        resolution: str,
    ) -> None:
        nonlocal next_idx
        if (
            return_peak is None
            or return_peak_us is None
            or start_tick is None
            or start_us is None
            or trough_tick is None
        ):
            return
        relation = relation_to_entry(
            root.first_entry_us,
            start_us,
            resolution_us,
        )
        step = Step(
            idx=next_idx,
            root=root,
            ordinal=len(steps) + 1,
            peak_tick=return_peak,
            peak_us=return_peak_us,
            start_tick=start_tick,
            start_us=start_us,
            resolution_tick=resolution_tick,
            resolution_us=resolution_us,
            resolution=resolution,
            relation=relation,
            prior_depths=tuple(prior_depths),
        )
        next_idx += 1
        add_step_phases(
            step,
            times,
            ticks,
            sizes,
            signs,
            zone_ticks,
        )
        steps.append(step)
        prior_depths.append(
            root.direction * (return_peak - trough_tick)
        )

    last_tick = ticks[max(lo, hi - 1)] if times else root.edge_tick
    for i in range(lo, hi):
        ts_us = times[i]
        tick = ticks[i]
        if ts_us > terminal_us:
            break
        if peak_tick is None:
            if signed_ticks(root, tick) <= 0:
                continue
            peak_tick = tick
            peak_us = ts_us
            continue

        if in_return:
            if root.direction * (trough_tick - tick) > 0:
                trough_tick = tick
            if root.direction * (tick - return_peak) >= 0:
                emit(tick, ts_us, "READVANCED")
                in_return = False
                peak_tick = tick
                peak_us = ts_us
                return_peak = None
                return_peak_us = None
                start_tick = None
                start_us = None
                trough_tick = None
            continue

        if root.direction * (tick - peak_tick) >= 0:
            peak_tick = tick
            peak_us = ts_us
            continue
        if root.direction * (peak_tick - tick) >= step_ticks:
            in_return = True
            return_peak = peak_tick
            return_peak_us = peak_us
            start_tick = tick
            start_us = ts_us
            trough_tick = tick

    terminal_i = bisect.bisect_right(times, terminal_us) - 1
    if terminal_i >= 0:
        last_tick = ticks[terminal_i]
    if in_return:
        if root.direction * (trough_tick - last_tick) > 0:
            trough_tick = last_tick
        emit(last_tick, terminal_us, terminal_label)
    return steps


def step_row(step: Step) -> dict[str, Any]:
    root = step.root
    row = root.row
    onset = aggregate_phase(step.phases.get("onset"))
    resolution = aggregate_phase(step.phases.get("resolution"))
    entry_state = aggregate_phase(step.phases.get("entry_state"))
    prior_max = max(step.prior_depths) if step.prior_depths else None
    resolution_depth = root.direction * (
        step.peak_tick - step.resolution_tick
    )
    result: dict[str, Any] = {
        "session_id": row.get("session_id", ""),
        "date": root.date,
        "root_id": root.root_id,
        "side": root.side,
        "entry_roles": row.get("entry_roles", ""),
        "directive_ids": row.get("directive_ids", ""),
        "root_outcome": row.get("entry_structural_outcome", ""),
        "clean_or_escaped_context": (
            row.get("pre_10m_50pts_two_sided_fail") != "True"
            or row.get("pre_10m_50pts_favorable_position")
            == "beyond_favorable_edge"
        ),
        "step_ordinal": step.ordinal,
        "relation": step.relation,
        "step_success": step.success,
        "resolution": step.resolution,
        "peak_et": datetime.fromtimestamp(
            step.peak_us / 1_000_000, NY
        ).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
        "start_et": datetime.fromtimestamp(
            step.start_us / 1_000_000, NY
        ).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
        "resolution_et": datetime.fromtimestamp(
            step.resolution_us / 1_000_000, NY
        ).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
        "peak_price": step.peak_tick * TICK_SIZE,
        "start_price": step.start_tick * TICK_SIZE,
        "resolution_price": step.resolution_tick * TICK_SIZE,
        "road_extension_at_peak_ticks": signed_ticks(
            root, step.peak_tick
        ),
        "start_depth_ticks": root.direction
        * (step.peak_tick - step.start_tick),
        "resolution_depth_ticks": resolution_depth,
        "resolution_road_remaining_ticks": signed_ticks(
            root, step.resolution_tick
        ),
        "duration_s": (
            step.resolution_us - step.start_us
        )
        / 1_000_000,
        "prior_step_count": len(step.prior_depths),
        "prior_depth_max_ticks": prior_max,
        "prior_depth_last_ticks": (
            step.prior_depths[-1] if step.prior_depths else None
        ),
        "resolution_depth_vs_prior_max": (
            resolution_depth / prior_max
            if prior_max is not None and prior_max > 0
            else None
        ),
        "entry_et": row.get("first_entry_et", ""),
        "entry_step_age_s": (
            (root.first_entry_us - step.start_us) / 1_000_000
            if step.relation == "ENTRY_STEP"
            and root.first_entry_us is not None
            else None
        ),
        "entry_step_price": (
            step.entry_tick * TICK_SIZE
            if step.entry_tick is not None
            else None
        ),
        "entry_step_depth_ticks": (
            root.direction * (step.peak_tick - step.entry_tick)
            if step.entry_tick is not None
            else None
        ),
        "entry_step_favorable_displacement_ticks": (
            root.direction * (step.entry_tick - step.start_tick)
            if step.entry_tick is not None
            else None
        ),
        "entry_road_remaining_ticks": (
            signed_ticks(root, step.entry_tick)
            if step.entry_tick is not None
            else None
        ),
        "entry_depth_vs_prior_max": (
            root.direction * (step.peak_tick - step.entry_tick)
            / prior_max
            if step.entry_tick is not None
            and prior_max is not None
            and prior_max > 0
            else None
        ),
        "entry_state_book_valid": phase_valid(
            step.phases.get("entry_state")
        ),
        "onset_book_valid": phase_valid(step.phases.get("onset")),
        "resolution_book_valid": phase_valid(
            step.phases.get("resolution")
        ),
    }
    result.update({f"onset_{key}": value for key, value in onset.items()})
    result.update(
        {f"resolution_{key}": value for key, value in resolution.items()}
    )
    result.update(
        {f"entry_state_{key}": value for key, value in entry_state.items()}
    )

    for checkpoint_ms in CHECKPOINT_MS:
        prefix = f"checkpoint_{checkpoint_ms}ms"
        phase = step.phases.get(prefix)
        values = aggregate_phase(phase)
        tick = step.checkpoint_ticks.get(checkpoint_ms)
        result.update(
            {f"{prefix}_{key}": value for key, value in values.items()}
        )
        result.update(
            {
                f"{prefix}_active": phase is not None,
                f"{prefix}_book_valid": phase_valid(phase),
                f"{prefix}_price": (
                    tick * TICK_SIZE if tick is not None else None
                ),
                f"{prefix}_favorable_displacement_ticks": (
                    root.direction * (tick - step.start_tick)
                    if tick is not None
                    else None
                ),
                f"{prefix}_step_depth_ticks": (
                    root.direction * (step.peak_tick - tick)
                    if tick is not None
                    else None
                ),
                f"{prefix}_road_remaining_ticks": (
                    signed_ticks(root, tick)
                    if tick is not None
                    else None
                ),
                f"{prefix}_depth_vs_prior_max": (
                    root.direction * (step.peak_tick - tick) / prior_max
                    if tick is not None
                    and prior_max is not None
                    and prior_max > 0
                    else None
                ),
            }
        )
    return result


def level_rows(steps: list[Step]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for step in steps:
        for phase_name, phase in step.phases.items():
            for level in phase.levels.values():
                rows.append(
                    {
                        "date": step.root.date,
                        "root_id": step.root.root_id,
                        "step_ordinal": step.ordinal,
                        "relation": step.relation,
                        "resolution": step.resolution,
                        "phase": phase_name,
                        "price": level.tick * TICK_SIZE,
                        "favorable_trade_qty": level.favorable_trade_qty,
                        "adverse_trade_qty": level.adverse_trade_qty,
                        "winner_seed": level.seed_winner,
                        "winner_end": level.end_winner,
                        "winner_adds": level.winner_adds,
                        "winner_removes": level.winner_removes,
                        "loser_seed": level.seed_loser,
                        "loser_end": level.end_loser,
                        "loser_adds": level.loser_adds,
                        "loser_removes": level.loser_removes,
                    }
                )
    return rows


def metric_summary(
    rows: list[dict[str, Any]],
    feature: str,
) -> tuple[int, float, float, float] | None:
    positive = [
        float(row[feature])
        for row in rows
        if row["step_success"] is True and fnum(row.get(feature)) is not None
    ]
    negative = [
        float(row[feature])
        for row in rows
        if row["step_success"] is False and fnum(row.get(feature)) is not None
    ]
    score = auc(positive, negative)
    if score is None:
        return None
    return len(positive) + len(negative), median(positive), median(negative), score


def checkpoint_state(row: dict[str, Any], checkpoint_ms: int) -> str:
    prefix = f"checkpoint_{checkpoint_ms}ms"
    road = float(row[f"{prefix}_road_remaining_ticks"])
    displacement = float(row[f"{prefix}_favorable_displacement_ticks"])
    provision = float(row[f"{prefix}_winner_net_provision_qty"])
    if road <= 0:
        return "ROAD_LOST"
    if displacement >= 0 and provision > 0:
        return "RECOVERING_RELOADING"
    if displacement >= 0:
        return "RECOVERING_DRAINING"
    if provision > 0:
        return "DEEPENING_SUPPORTED"
    return "DEEPENING_DRAINING"


def build_report(
    rows: list[dict[str, Any]],
    stats: dict[str, dict[str, int]],
    start: str,
    end: str,
    step_ticks: int,
    zone_ticks: int,
) -> str:
    counts = Counter(row["resolution"] for row in rows)
    roots = {
        (row["session_id"], row["date"], row["root_id"]) for row in rows
    }
    lines = [
        "# Direct Conversion Road Steps",
        "",
        f"Window: {start} through {end} ET.",
        "",
        f"A step begins after a `{step_ticks}`-tick return from the current favorable peak. Fixed checkpoints measure a `{zone_ticks}`-tick strip underneath current price while that same step is still unresolved.",
        "",
        "## Population",
        "",
        f"- roots with material steps={len(roots)}",
        f"- steps={len(rows)}; readvanced={counts['READVANCED']}; sponsor advanced during step={counts['SPONSOR_ADVANCED']}; root failed during step={counts['ROOT_FAILED']}",
        f"- pre-entry={sum(row['relation'] == 'PRE_ENTRY' for row in rows)}; entry-step={sum(row['relation'] == 'ENTRY_STEP' for row in rows)}; post-entry={sum(row['relation'] == 'POST_ENTRY' for row in rows)}",
        "",
        "## State At Actual Entry",
        "",
        "Only the material return containing EAR's actual first entry is included.",
        "",
        "| feature | n | step held/advanced median | root-failure median | AUC |",
        "|---|---:|---:|---:|---:|",
    ]
    entry_steps = [
        row
        for row in rows
        if row["relation"] == "ENTRY_STEP"
        and row["entry_state_book_valid"] is True
    ]
    for feature in (
        "entry_step_age_s",
        "entry_step_favorable_displacement_ticks",
        "entry_step_depth_ticks",
        "entry_road_remaining_ticks",
        "entry_depth_vs_prior_max",
        "entry_state_winner_net_provision_qty",
        "entry_state_winner_end_qty",
        "entry_state_backing_end_levels_frac",
    ):
        summary = metric_summary(entry_steps, feature)
        if summary is None:
            continue
        count, pos_med, neg_med, score = summary
        lines.append(
            f"| {feature} | {count} | {fmt(pos_med)} | "
            f"{fmt(neg_med)} | {fmt(score)} |"
        )
    lines.extend(
        [
            "",
        "## Causal Checkpoints",
        "",
        "Success means the active step readvanced or favorable sponsorship formed before the root failed. Each row is a step, so roots and directives are correlated.",
        "",
        "| checkpoint | active valid n | feature | success median | failure median | AUC |",
        "|---|---:|---|---:|---:|---:|",
        ]
    )
    for checkpoint_ms in CHECKPOINT_MS:
        prefix = f"checkpoint_{checkpoint_ms}ms"
        eligible = [
            row
            for row in rows
            if row.get(f"{prefix}_active") is True
            and row.get(f"{prefix}_book_valid") is True
        ]
        features = [
            f"{prefix}_favorable_displacement_ticks",
            f"{prefix}_step_depth_ticks",
            f"{prefix}_road_remaining_ticks",
            f"{prefix}_depth_vs_prior_max",
            f"{prefix}_winner_net_provision_qty",
            f"{prefix}_winner_end_qty",
            f"{prefix}_backing_end_levels_frac",
        ]
        for feature in features:
            summary = metric_summary(eligible, feature)
            if summary is None:
                continue
            count, pos_med, neg_med, score = summary
            lines.append(
                f"| {checkpoint_ms / 1000:g}s | {count} | "
                f"{feature.removeprefix(prefix + '_')} | {fmt(pos_med)} | "
                f"{fmt(neg_med)} | {fmt(score)} |"
            )

    lines.extend(
        [
            "",
            "## Auction States",
            "",
            "| checkpoint | state | n | success | success rate |",
            "|---|---|---:|---:|---:|",
        ]
    )
    for checkpoint_ms in CHECKPOINT_MS:
        prefix = f"checkpoint_{checkpoint_ms}ms"
        eligible = [
            row
            for row in rows
            if row.get(f"{prefix}_active") is True
            and row.get(f"{prefix}_book_valid") is True
        ]
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in eligible:
            grouped[checkpoint_state(row, checkpoint_ms)].append(row)
        for state, group in sorted(grouped.items()):
            success = sum(row["step_success"] is True for row in group)
            lines.append(
                f"| {checkpoint_ms / 1000:g}s | {state} | {len(group)} | "
                f"{success} | {fmt(success / len(group))} |"
            )

    lines.extend(
        [
            "",
            "## Final Step By Role",
            "",
            "| role | outcome | n | prior steps median | resolution depth median | road remaining median |",
            "|---|---|---:|---:|---:|---:|",
        ]
    )
    terminal = [
        row for row in rows if row["resolution"] != "READVANCED"
    ]
    for role in ("EnterBase", "Add"):
        for success in (True, False):
            group = [
                row
                for row in terminal
                if row["entry_roles"] == role
                and row["step_success"] is success
            ]
            if not group:
                continue
            lines.append(
                f"| {role} | {'advanced' if success else 'failed'} | "
                f"{len(group)} | {fmt(median(float(row['prior_step_count']) for row in group))} | "
                f"{fmt(median(float(row['resolution_depth_ticks']) for row in group))} | "
                f"{fmt(median(float(row['resolution_road_remaining_ticks']) for row in group))} |"
            )

    lines.extend(["", "## Replay Health", ""])
    for day, day_stats in sorted(stats.items()):
        lines.append(
            f"- {day}: "
            + ", ".join(f"{key}={value}" for key, value in day_stats.items())
        )
    lines.extend(
        [
            "",
            "## Limits",
            "",
            "- This is a step-level descriptive dataset, not independent observations; one campaign can contribute many readvances.",
            "- A fixed eight-tick step is a study definition. It is not an implementation threshold.",
            "- Resolution-book fields are endpoint diagnostics. Only fixed checkpoint fields are causal candidates.",
            "- Invalid reconstructed-book phases remain in `steps.csv` with validity flags and are excluded from checkpoint tables.",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lineage", type=Path, default=DEFAULT_LINEAGE)
    parser.add_argument("--symbol-dir", default="NQU6")
    parser.add_argument("--start-date", default="2026-07-17")
    parser.add_argument("--end-date", default="2026-07-24")
    parser.add_argument("--step-ticks", type=int, default=8)
    parser.add_argument("--zone-ticks", type=int, default=8)
    parser.add_argument("--batch-files", type=int, default=40)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    if args.step_ticks <= 0 or args.zone_ticks <= 0:
        raise ValueError("step and zone ticks must be positive")
    output = args.output or (
        OUTPUT_ROOT
        / (
            "direct_conversion_road_steps_"
            f"{args.start_date.replace('-', '')}_{args.end_date.replace('-', '')}"
        )
    )

    roots = load_studies(
        args.lineage,
        args.start_date,
        args.end_date,
        "traded",
    )
    by_day: dict[str, list[Study]] = defaultdict(list)
    for root in roots:
        by_day[root.date].append(root)

    all_steps: list[Step] = []
    replay_stats: dict[str, dict[str, int]] = {}
    next_idx = 0
    for day, day_roots in sorted(by_day.items()):
        start = datetime.fromisoformat(day).replace(tzinfo=NY)
        end = start + timedelta(days=1)
        frame = load_capture_window(
            "ticks",
            args.symbol_dir,
            start,
            end,
            tick_columns(),
        )
        times = [int(value) for value in frame["timestamp_us"].to_list()]
        ticks = [
            int(round(float(value) / TICK_SIZE))
            for value in frame["price"].to_list()
        ]
        sizes = [float(value) for value in frame["size"].to_list()]
        signs = [int(value) for value in frame["aggressor_sign"].to_list()]

        day_steps: list[Step] = []
        for root in day_roots:
            steps = segment_steps(
                root,
                times,
                ticks,
                sizes,
                signs,
                args.step_ticks,
                args.zone_ticks,
                next_idx,
            )
            day_steps.extend(steps)
            if steps:
                next_idx = max(step.idx for step in steps) + 1
        all_steps.extend(day_steps)
        phases = [
            phase for step in day_steps for phase in step.phases.values()
        ]
        replay_stats[day] = replay_day(
            args.symbol_dir,
            day,
            phases,
            args.batch_files,
        )

    rows = [step_row(step) for step in all_steps]
    details = level_rows(all_steps)
    write_csv(output / "steps.csv", rows)
    write_csv(output / "per_level.csv", details)
    output.mkdir(parents=True, exist_ok=True)
    report = build_report(
        rows,
        replay_stats,
        args.start_date,
        args.end_date,
        args.step_ticks,
        args.zone_ticks,
    )
    (output / "findings.md").write_text(report, encoding="utf-8")
    print(
        f"wrote {len(rows)} steps and {len(details)} price-phase rows to {output}"
    )


if __name__ == "__main__":
    main()
