"""Audit direct-conversion execution at proximity, rail arrival, and reclaim.

The input is the already-replayed six-day proximity state collection plus the
band-lifecycle output.  This script intentionally keeps three information sets
separate:

1. state available when EAR first enters the 20-tick envelope;
2. the path and book visible only after waiting for the favorable rail edge;
3. the later reclaimed-edge test after an adverse traversal.

Outcomes are sponsor-lineage advancement or root failure.  A quote crossing the
rail is evidence that a resting edge order was marketable, not proof of queue
fill.  No P&L label or later fixed excursion is used.
"""

from __future__ import annotations

import argparse
import csv
import math
import random
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

from _paths import OUTPUT_ROOT

DEFAULT_PROXIMITY = (
    OUTPUT_ROOT
    / "direct_conversion_proximity_book_20260717_20260724"
)
DEFAULT_LIFECYCLE = (
    OUTPUT_ROOT
    / "direct_conversion_band_lifecycle_20260717_20260724"
)
DEFAULT_OUT = (
    OUTPUT_ROOT
    / "direct_conversion_execution_phase_policy_20260717_20260724"
)
ADVANCED = "ADVANCED_TO_FAVORABLE_SUCCESSOR"
FAILED = "ROOT_FAILED_FIRST"
TICK_SIZE = 0.25


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--proximity-dir", type=Path, default=DEFAULT_PROXIMITY)
    parser.add_argument("--lifecycle-dir", type=Path, default=DEFAULT_LIFECYCLE)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--bootstrap-samples", type=int, default=10_000)
    return parser.parse_args()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def input_rows(input_dir: Path, name: str) -> list[dict[str, str]]:
    direct = input_dir / name
    paths = (
        [direct]
        if direct.exists()
        else sorted((input_dir / "days").glob(f"*/{name}"))
    )
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
        for field in row:
            if field not in seen:
                fields.append(field)
                seen.add(field)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def number(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def truth(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes"}


def fmt(value: Any, digits: int = 3) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        if not math.isfinite(value):
            return ""
        return f"{value:.{digits}f}"
    return str(value)


def median(values: Iterable[float | None]) -> float | None:
    clean = [value for value in values if value is not None and math.isfinite(value)]
    return statistics.median(clean) if clean else None


def quantile(values: list[float], probability: float) -> float:
    ordered = sorted(values)
    if not ordered:
        raise ValueError("quantile requires at least one value")
    position = (len(ordered) - 1) * probability
    lo = math.floor(position)
    hi = math.ceil(position)
    if lo == hi:
        return ordered[lo]
    weight = position - lo
    return ordered[lo] * (1.0 - weight) + ordered[hi] * weight


def auc(positive: list[float], negative: list[float]) -> float | None:
    if not positive or not negative:
        return None
    combined = [(value, 1) for value in positive]
    combined.extend((value, 0) for value in negative)
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


def key(row: dict[str, Any]) -> tuple[str, str, str]:
    return str(row["session_id"]), str(row["date"]), str(row["root_id"])


def time_scope(value: str) -> str:
    clock = value.split(" ")[-1][:5]
    if clock < "11:30":
        return "09:30-11:30"
    if clock < "13:30":
        return "11:30-13:30"
    return "13:30-16:00"


def favorable_coord(side: str, exec_tick: int, lo_tick: int, hi_tick: int) -> int:
    return exec_tick - hi_tick if side == "Demand" else lo_tick - exec_tick


def nearest_state(
    states: list[dict[str, str]], target_elapsed: float
) -> dict[str, str]:
    return min(
        states,
        key=lambda row: abs((number(row.get("elapsed_s")) or 0.0) - target_elapsed),
    )


def trailing_value(row: dict[str, str], field: str) -> float:
    return number(row.get(field)) or 0.0


def load_population(
    proximity_dir: Path,
) -> tuple[
    list[dict[str, str]],
    dict[tuple[str, str, str], list[dict[str, str]]],
]:
    episodes = [
        row
        for row in input_rows(proximity_dir, "episode_summary.csv")
        if row.get("capture_status") == "complete"
        and row.get("structural_outcome") in {ADVANCED, FAILED}
    ]
    valid = {key(row) for row in episodes}
    samples: dict[tuple[str, str, str], list[dict[str, str]]] = defaultdict(list)
    for row in input_rows(proximity_dir, "state_samples.csv"):
        if key(row) in valid:
            samples[key(row)].append(row)
    for rows in samples.values():
        rows.sort(key=lambda row: number(row.get("elapsed_s")) or 0.0)
    return [row for row in episodes if samples.get(key(row))], samples


def build_root_rows(
    episodes: list[dict[str, str]],
    samples: dict[tuple[str, str, str], list[dict[str, str]]],
    lifecycle_dir: Path,
) -> list[dict[str, Any]]:
    lifecycle = {
        key(row): row for row in read_csv(lifecycle_dir / "events.csv")
    }
    output: list[dict[str, Any]] = []
    for episode in episodes:
        states = samples[key(episode)]
        initial = states[0]
        side = episode["side"]
        lo_tick = round(float(episode["root_lo"]) / TICK_SIZE)
        hi_tick = round(float(episode["root_hi"]) / TICK_SIZE)
        crossed: dict[str, str] | None = None
        crossing_coord: int | None = None
        for state in states:
            exec_tick_value = number(state.get("executable_tick"))
            if exec_tick_value is None:
                continue
            coord = favorable_coord(
                side, int(exec_tick_value), lo_tick, hi_tick
            )
            if coord <= 0:
                crossed = state
                crossing_coord = coord
                break

        initial_price = number(initial.get("executable_price"))
        favorable_sign = 1 if side == "Demand" else -1
        row: dict[str, Any] = {
            "session_id": episode["session_id"],
            "date": episode["date"],
            "root_id": episode["root_id"],
            "side": side,
            "root_lo": episode["root_lo"],
            "root_hi": episode["root_hi"],
            "root_owned_et": episode["root_owned_et"],
            "proximity_et": episode["proximity_et"],
            "time_window": time_scope(episode["proximity_et"]),
            "structural_outcome": episode["structural_outcome"],
            "advanced": episode["structural_outcome"] == ADVANCED,
            "proximity_price": fmt(initial_price),
            "proximity_distance_ticks": initial.get("distance_ticks", ""),
            "rail_crossed": crossed is not None,
            "rail_cross_et": crossed.get("sample_et", "") if crossed else "",
            "rail_cross_delay_s": crossed.get("elapsed_s", "") if crossed else "",
            "rail_cross_coord_ticks": crossing_coord
            if crossing_coord is not None
            else "",
            "rail_cross_penetration_ticks": max(0, -crossing_coord)
            if crossing_coord is not None
            else "",
        }
        for suffix in ("0p5s", "2p0s", "5p0s"):
            for field in (
                "support_net_norm",
                "under_net_norm",
                "road_clear_norm",
                "tape_owner_field_consume",
                "tape_opponent_field_consume",
                "tape_owner_rail_consume",
                "tape_opponent_rail_consume",
            ):
                row[f"proximity_{field}_{suffix}"] = initial.get(
                    f"{field}_{suffix}", ""
                )

        if crossed is not None and initial_price is not None:
            cross_price = number(crossed.get("executable_price"))
            edge_price = (hi_tick if side == "Demand" else lo_tick) * TICK_SIZE
            row["rail_cross_price"] = fmt(cross_price)
            row["rail_market_improvement_pts"] = fmt(
                (initial_price - cross_price) * favorable_sign
                if cross_price is not None
                else None
            )
            row["edge_limit_improvement_pts"] = fmt(
                (initial_price - edge_price) * favorable_sign
            )
            row["exact_band_quote_observed"] = (
                crossing_coord is not None
                and -(hi_tick - lo_tick) <= crossing_coord <= 0
            )
            elapsed = number(crossed.get("elapsed_s")) or 0.0
            start = nearest_state(states, max(0.0, elapsed - 5.0))
            start_tick = int(number(start.get("executable_tick")) or 0)
            end_tick = int(number(crossed.get("executable_tick")) or 0)
            start_coord = favorable_coord(side, start_tick, lo_tick, hi_tick)
            end_coord = favorable_coord(side, end_tick, lo_tick, hi_tick)
            adverse_progress = max(0, start_coord - end_coord)
            adverse_qty = trailing_value(
                crossed, "tape_owner_field_consume_5p0s"
            )
            favorable_qty = trailing_value(
                crossed, "tape_opponent_field_consume_5p0s"
            )
            rail_owner_qty = trailing_value(
                crossed, "tape_owner_rail_consume_5p0s"
            )
            rail_opponent_qty = trailing_value(
                crossed, "tape_opponent_rail_consume_5p0s"
            )
            row.update(
                {
                    "arrival_5s_adverse_progress_ticks": adverse_progress,
                    "arrival_5s_adverse_qty": fmt(adverse_qty),
                    "arrival_5s_favorable_qty": fmt(favorable_qty),
                    "arrival_5s_adverse_ticks_per_10_qty": fmt(
                        adverse_progress * 10.0 / adverse_qty
                        if adverse_qty > 0
                        else None
                    ),
                    "rail_5s_owner_aggressor_qty": fmt(rail_owner_qty),
                    "rail_5s_opponent_aggressor_qty": fmt(rail_opponent_qty),
                    "rail_5s_min_side_qty": fmt(
                        min(rail_owner_qty, rail_opponent_qty)
                    ),
                    "rail_2s_min_side_qty": fmt(
                        min(
                            trailing_value(
                                crossed, "tape_owner_rail_consume_2p0s"
                            ),
                            trailing_value(
                                crossed, "tape_opponent_rail_consume_2p0s"
                            ),
                        )
                    ),
                    "rail_support_net_norm_2p0s": crossed.get(
                        "support_net_norm_2p0s", ""
                    ),
                    "rail_support_net_norm_5p0s": crossed.get(
                        "support_net_norm_5p0s", ""
                    ),
                    "rail_under_net_norm_2p0s": crossed.get(
                        "under_net_norm_2p0s", ""
                    ),
                    "rail_owner_under_depth_ratio": crossed.get(
                        "owner_under_depth_ratio", ""
                    ),
                }
            )
        else:
            for field in (
                "rail_cross_price",
                "rail_market_improvement_pts",
                "edge_limit_improvement_pts",
                "exact_band_quote_observed",
                "arrival_5s_adverse_progress_ticks",
                "arrival_5s_adverse_qty",
                "arrival_5s_favorable_qty",
                "arrival_5s_adverse_ticks_per_10_qty",
                "rail_5s_owner_aggressor_qty",
                "rail_5s_opponent_aggressor_qty",
                "rail_5s_min_side_qty",
                "rail_2s_min_side_qty",
                "rail_support_net_norm_2p0s",
                "rail_support_net_norm_5p0s",
                "rail_under_net_norm_2p0s",
                "rail_owner_under_depth_ratio",
            ):
                row[field] = ""

        event = lifecycle.get(key(episode), {})
        for field in (
            "cp_10s_band_min_side_qty",
            "cp_10s_band_balance",
            "to_proximity_band_min_side_qty",
            "to_proximity_band_balance",
            "approach_retest_opportunity",
            "approach_gate_filled",
            "approach_retest_et",
            "approach_support_net_norm_2s",
            "to_approach_band_min_side_qty",
            "breach_to_reclaim_or_end_band_min_side_qty",
            "breach_to_reclaim_or_end_band_balance",
            "edge_test_et",
            "edge_test_resolution",
        ):
            row[field] = event.get(field, "")
        output.append(row)
    return output


def add_heldout_support_gate(rows: list[dict[str, Any]]) -> None:
    touched = [row for row in rows if truth(row["rail_crossed"])]
    dates = sorted({row["date"] for row in touched})
    for held_out in dates:
        advancing_support = [
            number(row.get("rail_support_net_norm_5p0s"))
            for row in touched
            if row["date"] != held_out
            and truth(row["advanced"])
            and number(row.get("rail_support_net_norm_5p0s")) is not None
        ]
        clean = [value for value in advancing_support if value is not None]
        threshold = quantile(clean, 0.30)
        for row in touched:
            if row["date"] != held_out:
                continue
            value = number(row.get("rail_support_net_norm_5p0s"))
            row["rail_support_heldout_threshold"] = fmt(threshold)
            row["rail_support_gate"] = (
                "PASS" if value is not None and value >= threshold else "FAIL"
            )


def add_heldout_proximity_support_gate(rows: list[dict[str, Any]]) -> None:
    dates = sorted({row["date"] for row in rows})
    for held_out in dates:
        advancing_support = [
            number(row.get("proximity_support_net_norm_5p0s"))
            for row in rows
            if row["date"] != held_out
            and truth(row["advanced"])
            and number(row.get("proximity_support_net_norm_5p0s")) is not None
        ]
        clean = [value for value in advancing_support if value is not None]
        threshold = quantile(clean, 0.30)
        for row in rows:
            if row["date"] != held_out:
                continue
            value = number(row.get("proximity_support_net_norm_5p0s"))
            row["proximity_support_heldout_threshold"] = fmt(threshold)
            row["proximity_support_gate"] = (
                "PASS" if value is not None and value >= threshold else "FAIL"
            )


def add_heldout_arrival_bucket(rows: list[dict[str, Any]]) -> None:
    touched = [row for row in rows if truth(row["rail_crossed"])]
    dates = sorted({row["date"] for row in touched})
    for held_out in dates:
        training = [row for row in touched if row["date"] != held_out]
        quantities = [
            number(row.get("arrival_5s_adverse_qty"))
            for row in training
            if number(row.get("arrival_5s_adverse_qty")) is not None
        ]
        efficiencies = [
            number(row.get("arrival_5s_adverse_ticks_per_10_qty"))
            for row in training
            if number(row.get("arrival_5s_adverse_ticks_per_10_qty")) is not None
        ]
        qty_cut = statistics.median(value for value in quantities if value is not None)
        efficiency_cut = statistics.median(
            value for value in efficiencies if value is not None
        )
        for row in touched:
            if row["date"] != held_out:
                continue
            qty = number(row.get("arrival_5s_adverse_qty")) or 0.0
            efficiency = number(row.get("arrival_5s_adverse_ticks_per_10_qty"))
            if efficiency is None:
                bucket = "NO_MEASURED_ADVERSE_TAPE"
            elif qty >= qty_cut and efficiency >= efficiency_cut:
                bucket = "HEAVY_EFFICIENT"
            elif qty >= qty_cut:
                bucket = "HEAVY_ABSORBED"
            elif efficiency >= efficiency_cut:
                bucket = "THIN_EFFICIENT"
            else:
                bucket = "LIGHT_SLOW"
            row["arrival_qty_heldout_median"] = fmt(qty_cut)
            row["arrival_efficiency_heldout_median"] = fmt(efficiency_cut)
            row["arrival_bucket"] = bucket


def rate(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def scope_rows(
    rows: list[dict[str, Any]], scope: str
) -> list[dict[str, Any]]:
    if scope == "ALL":
        return rows
    return [row for row in rows if row["time_window"] == scope]


def wait_policy_summary(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for scope in ("ALL", "09:30-11:30", "11:30-13:30", "13:30-16:00"):
        selected = scope_rows(rows, scope)
        advanced = [row for row in selected if truth(row["advanced"])]
        failed = [row for row in selected if not truth(row["advanced"])]
        touched_advanced = [row for row in advanced if truth(row["rail_crossed"])]
        touched_failed = [row for row in failed if truth(row["rail_crossed"])]
        gated_advanced = [
            row for row in touched_advanced if row.get("rail_support_gate") == "PASS"
        ]
        gated_failed = [
            row for row in touched_failed if row.get("rail_support_gate") == "PASS"
        ]
        contest_gate_advanced = [
            row
            for row in advanced
            if (number(row.get("to_proximity_band_min_side_qty")) or 0.0) <= 0
            or row.get("proximity_support_gate") == "PASS"
        ]
        contest_gate_failed = [
            row
            for row in failed
            if (number(row.get("to_proximity_band_min_side_qty")) or 0.0) <= 0
            or row.get("proximity_support_gate") == "PASS"
        ]
        output.append(
            {
                "scope": scope,
                "roots": len(selected),
                "advanced": len(advanced),
                "failed": len(failed),
                "rail_crossed_advanced": len(touched_advanced),
                "rail_crossed_failed": len(touched_failed),
                "wait_rail_advance_capture": fmt(
                    rate(len(touched_advanced), len(advanced))
                ),
                "wait_rail_failure_exposure": fmt(
                    rate(len(touched_failed), len(failed))
                ),
                "wait_rail_selectivity": fmt(
                    (
                        len(touched_advanced) / len(advanced)
                        - len(touched_failed) / len(failed)
                    )
                    if advanced and failed
                    else None
                ),
                "support_gate_advance_capture": fmt(
                    rate(len(gated_advanced), len(advanced))
                ),
                "support_gate_failure_exposure": fmt(
                    rate(len(gated_failed), len(failed))
                ),
                "support_gate_selectivity": fmt(
                    (
                        len(gated_advanced) / len(advanced)
                        - len(gated_failed) / len(failed)
                    )
                    if advanced and failed
                    else None
                ),
                "initial_contest_gate_advance_capture": fmt(
                    rate(len(contest_gate_advanced), len(advanced))
                ),
                "initial_contest_gate_failure_exposure": fmt(
                    rate(len(contest_gate_failed), len(failed))
                ),
                "initial_contest_gate_selectivity": fmt(
                    (
                        len(contest_gate_advanced) / len(advanced)
                        - len(contest_gate_failed) / len(failed)
                    )
                    if advanced and failed
                    else None
                ),
                "advanced_market_improvement_median_pts": fmt(
                    median(
                        number(row.get("rail_market_improvement_pts"))
                        for row in touched_advanced
                    )
                ),
                "advanced_edge_limit_improvement_median_pts": fmt(
                    median(
                        number(row.get("edge_limit_improvement_pts"))
                        for row in touched_advanced
                    )
                ),
                "advanced_delay_median_s": fmt(
                    median(
                        number(row.get("rail_cross_delay_s"))
                        for row in touched_advanced
                    )
                ),
            }
        )
    return output


def initial_joint_summary(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for scope in ("ALL", "09:30-11:30", "11:30-13:30", "13:30-16:00"):
        scoped = scope_rows(rows, scope)
        for interaction in ("ZERO", "TWO_SIDED"):
            for support in ("PASS", "FAIL"):
                group = [
                    row
                    for row in scoped
                    if (
                        "TWO_SIDED"
                        if (
                            number(row.get("to_proximity_band_min_side_qty"))
                            or 0.0
                        )
                        > 0
                        else "ZERO"
                    )
                    == interaction
                    and row.get("proximity_support_gate") == support
                ]
                advanced = sum(truth(row["advanced"]) for row in group)
                output.append(
                    {
                        "scope": scope,
                        "known_interaction_at_proximity": interaction,
                        "proximity_support_gate": support,
                        "n": len(group),
                        "advanced": advanced,
                        "failed": len(group) - advanced,
                        "advance_rate": fmt(rate(advanced, len(group))),
                        "days": len({row["date"] for row in group}),
                    }
                )
    return output


def approach_joint_summary(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for scope in ("ALL", "09:30-11:30", "11:30-13:30", "13:30-16:00"):
        eligible = [
            row
            for row in scope_rows(rows, scope)
            if truth(row.get("approach_retest_opportunity"))
        ]
        for interaction in ("ZERO", "TWO_SIDED"):
            for support in ("PASS", "FAIL"):
                group = [
                    row
                    for row in eligible
                    if (
                        "TWO_SIDED"
                        if (number(row.get("to_approach_band_min_side_qty")) or 0.0)
                        > 0
                        else "ZERO"
                    )
                    == interaction
                    and (
                        "PASS"
                        if truth(row.get("approach_gate_filled"))
                        else "FAIL"
                    )
                    == support
                ]
                advanced = sum(truth(row["advanced"]) for row in group)
                output.append(
                    {
                        "scope": scope,
                        "interaction_by_reapproach": interaction,
                        "heldout_approach_support_gate": support,
                        "n": len(group),
                        "advanced": advanced,
                        "failed": len(group) - advanced,
                        "advance_rate": fmt(rate(advanced, len(group))),
                        "days": len({row["date"] for row in group}),
                    }
                )
    return output


def joint_summary(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    dimensions = (
        ("rail_5s", "rail_5s_min_side_qty"),
        ("formation_10s", "cp_10s_band_min_side_qty"),
    )
    for scope in ("ALL", "09:30-11:30", "11:30-13:30", "13:30-16:00"):
        touched = [
            row for row in scope_rows(rows, scope) if truth(row["rail_crossed"])
        ]
        for dimension, field in dimensions:
            for interaction in ("ZERO", "TWO_SIDED"):
                for support in ("PASS", "FAIL"):
                    group = [
                        row
                        for row in touched
                        if (
                            "TWO_SIDED"
                            if (number(row.get(field)) or 0.0) > 0
                            else "ZERO"
                        )
                        == interaction
                        and row.get("rail_support_gate") == support
                    ]
                    advanced = sum(truth(row["advanced"]) for row in group)
                    output.append(
                        {
                            "scope": scope,
                            "interaction_phase": dimension,
                            "interaction": interaction,
                            "support_gate": support,
                            "n": len(group),
                            "advanced": advanced,
                            "failed": len(group) - advanced,
                            "advance_rate": fmt(rate(advanced, len(group))),
                            "days": len({row["date"] for row in group}),
                        }
                    )
    return output


def arrival_summary(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for scope in ("ALL", "09:30-11:30", "11:30-13:30", "13:30-16:00"):
        touched = [
            row for row in scope_rows(rows, scope) if truth(row["rail_crossed"])
        ]
        for bucket in sorted({row.get("arrival_bucket", "") for row in touched}):
            group = [row for row in touched if row.get("arrival_bucket") == bucket]
            advanced = sum(truth(row["advanced"]) for row in group)
            exact = sum(truth(row["exact_band_quote_observed"]) for row in group)
            support_pass = sum(row.get("rail_support_gate") == "PASS" for row in group)
            output.append(
                {
                    "scope": scope,
                    "arrival_bucket": bucket,
                    "n": len(group),
                    "advanced": advanced,
                    "failed": len(group) - advanced,
                    "advance_rate": fmt(rate(advanced, len(group))),
                    "support_pass_rate": fmt(rate(support_pass, len(group))),
                    "exact_band_quote_rate": fmt(rate(exact, len(group))),
                    "market_improvement_median_pts": fmt(
                        median(
                            number(row.get("rail_market_improvement_pts"))
                            for row in group
                        )
                    ),
                    "cross_penetration_median_ticks": fmt(
                        median(
                            number(row.get("rail_cross_penetration_ticks"))
                            for row in group
                        )
                    ),
                    "days": len({row["date"] for row in group}),
                }
            )
    return output


def arrival_support_summary(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for scope in ("ALL", "09:30-11:30", "11:30-13:30", "13:30-16:00"):
        touched = [
            row for row in scope_rows(rows, scope) if truth(row["rail_crossed"])
        ]
        for bucket in sorted({row.get("arrival_bucket", "") for row in touched}):
            for support in ("PASS", "FAIL"):
                group = [
                    row
                    for row in touched
                    if row.get("arrival_bucket") == bucket
                    and row.get("rail_support_gate") == support
                ]
                advanced = sum(truth(row["advanced"]) for row in group)
                output.append(
                    {
                        "scope": scope,
                        "arrival_bucket": bucket,
                        "support_gate": support,
                        "n": len(group),
                        "advanced": advanced,
                        "failed": len(group) - advanced,
                        "advance_rate": fmt(rate(advanced, len(group))),
                        "rail_two_sided_rate": fmt(
                            rate(
                                sum(
                                    (number(row.get("rail_5s_min_side_qty")) or 0.0)
                                    > 0
                                    for row in group
                                ),
                                len(group),
                            )
                        ),
                        "days": len({row["date"] for row in group}),
                    }
                )
    return output


T0_FEATURES = (
    "proximity_support_net_norm_0p5s",
    "proximity_support_net_norm_2p0s",
    "proximity_support_net_norm_5p0s",
    "proximity_road_clear_norm_2p0s",
    "proximity_road_clear_norm_5p0s",
    "proximity_tape_owner_field_consume_2p0s",
    "proximity_tape_owner_field_consume_5p0s",
    "proximity_tape_opponent_field_consume_2p0s",
    "proximity_tape_opponent_field_consume_5p0s",
)


def t0_waitability_audit(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for scope in ("ALL", "09:30-11:30", "11:30-13:30", "13:30-16:00"):
        advanced = [
            row for row in scope_rows(rows, scope) if truth(row["advanced"])
        ]
        waitable = [row for row in advanced if truth(row["rail_crossed"])]
        flyaway = [row for row in advanced if not truth(row["rail_crossed"])]
        for feature in T0_FEATURES:
            positive = [
                number(row.get(feature))
                for row in waitable
                if number(row.get(feature)) is not None
            ]
            negative = [
                number(row.get(feature))
                for row in flyaway
                if number(row.get(feature)) is not None
            ]
            score = auc(
                [value for value in positive if value is not None],
                [value for value in negative if value is not None],
            )
            output.append(
                {
                    "scope": scope,
                    "feature": feature.removeprefix("proximity_"),
                    "waitable_n": len(positive),
                    "flyaway_n": len(negative),
                    "auc_waitable_high": fmt(score),
                    "separability_auc": fmt(
                        max(score, 1.0 - score) if score is not None else None
                    ),
                    "waitable_when": (
                        "high"
                        if score is not None and score >= 0.5
                        else "low"
                        if score is not None
                        else ""
                    ),
                    "waitable_median": fmt(median(positive)),
                    "flyaway_median": fmt(median(negative)),
                }
            )
    return output


def edge_reclaim_joint(
    lifecycle_dir: Path,
) -> list[dict[str, Any]]:
    events = {key(row): row for row in read_csv(lifecycle_dir / "events.csv")}
    decisions = [
        row
        for row in read_csv(lifecycle_dir / "edge_book_policy_decisions.csv")
        if row.get("feature") == "edge_book_support_net_norm_5p0s"
    ]
    output: list[dict[str, Any]] = []
    for decision in decisions:
        event = events.get(key(decision), {})
        output.append(
            {
                **decision,
                "time_window": event.get(
                    "time_window", time_scope(decision["edge_test_et"])
                ),
                "formation_10s_min_side_qty": event.get(
                    "cp_10s_band_min_side_qty", ""
                ),
                "reclaim_transit_min_side_qty": event.get(
                    "breach_to_reclaim_or_end_band_min_side_qty", ""
                ),
            }
        )
    return output


def edge_reclaim_summary(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for scope in ("ALL", "09:30-11:30", "11:30-13:30", "13:30-16:00"):
        scoped = (
            rows
            if scope == "ALL"
            else [row for row in rows if row["time_window"] == scope]
        )
        for label, field in (
            ("formation_10s", "formation_10s_min_side_qty"),
            ("reclaim_transit", "reclaim_transit_min_side_qty"),
        ):
            for interaction in ("ZERO", "TWO_SIDED"):
                for support in ("PASS", "FAIL"):
                    group = [
                        row
                        for row in scoped
                        if (
                            "TWO_SIDED"
                            if (number(row.get(field)) or 0.0) > 0
                            else "ZERO"
                        )
                        == interaction
                        and ("PASS" if truth(row.get("selected")) else "FAIL")
                        == support
                    ]
                    advanced = sum(
                        row["structural_outcome"] == ADVANCED for row in group
                    )
                    readvanced = sum(
                        row["edge_test_resolution"] == "READVANCED"
                        for row in group
                    )
                    output.append(
                        {
                            "scope": scope,
                            "interaction_phase": label,
                            "interaction": interaction,
                            "support_gate": support,
                            "n": len(group),
                            "advanced": advanced,
                            "failed": len(group) - advanced,
                            "advance_rate": fmt(rate(advanced, len(group))),
                            "readvance_rate": fmt(rate(readvanced, len(group))),
                            "days": len({row["date"] for row in group}),
                        }
                    )
    return output


def cluster_rate_difference(
    rows: list[dict[str, Any]],
    selected: callable,
    success: callable,
    samples: int,
    seed: int,
) -> tuple[float | None, float | None, float | None]:
    dates = sorted({row["date"] for row in rows})
    by_date = {
        day: [row for row in rows if row["date"] == day] for day in dates
    }
    rng = random.Random(seed)
    values: list[float] = []
    for _ in range(samples):
        sample: list[dict[str, Any]] = []
        for _ in dates:
            sample.extend(by_date[rng.choice(dates)])
        accepted = [row for row in sample if selected(row)]
        rejected = [row for row in sample if not selected(row)]
        if not accepted or not rejected:
            continue
        accepted_rate = sum(success(row) for row in accepted) / len(accepted)
        rejected_rate = sum(success(row) for row in rejected) / len(rejected)
        values.append(accepted_rate - rejected_rate)
    if not values:
        return None, None, None
    values.sort()
    return (
        statistics.median(values),
        values[math.floor(0.025 * (len(values) - 1))],
        values[math.floor(0.975 * (len(values) - 1))],
    )


def support_interaction_effects(
    roots: list[dict[str, Any]],
    edge_rows: list[dict[str, Any]],
    bootstrap_samples: int,
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for population, rows, support_field, success in (
        (
            "first_rail_cross",
            [row for row in roots if truth(row["rail_crossed"])],
            "rail_support_gate",
            lambda row: truth(row["advanced"]),
        ),
        (
            "reclaimed_edge",
            edge_rows,
            "selected",
            lambda row: row["structural_outcome"] == ADVANCED,
        ),
        (
            "reclaimed_edge_local",
            edge_rows,
            "selected",
            lambda row: row["edge_test_resolution"] == "READVANCED",
        ),
    ):
        for scope in ("ALL", "09:30-11:30"):
            scoped = (
                rows
                if scope == "ALL"
                else [row for row in rows if row["time_window"] == scope]
            )
            interaction_fields = (
                (
                    "formation_10s",
                    "cp_10s_band_min_side_qty"
                    if population == "first_rail_cross"
                    else "formation_10s_min_side_qty",
                ),
                (
                    "current_phase",
                    "rail_5s_min_side_qty"
                    if population == "first_rail_cross"
                    else "reclaim_transit_min_side_qty",
                ),
            )
            for interaction_name, interaction_field in interaction_fields:
                for interaction in ("ZERO", "TWO_SIDED"):
                    group = [
                        row
                        for row in scoped
                        if (
                            "TWO_SIDED"
                            if (number(row.get(interaction_field)) or 0.0) > 0
                            else "ZERO"
                        )
                        == interaction
                    ]
                    if support_field == "selected":
                        passed = lambda row: truth(row.get(support_field))
                    else:
                        passed = lambda row: row.get(support_field) == "PASS"
                    accepted = [row for row in group if passed(row)]
                    rejected = [row for row in group if not passed(row)]
                    median_diff, lo, hi = cluster_rate_difference(
                        group,
                        passed,
                        success,
                        bootstrap_samples,
                        seed=20260726 + len(output),
                    )
                    output.append(
                        {
                            "population": population,
                            "scope": scope,
                            "interaction_phase": interaction_name,
                            "interaction": interaction,
                            "n": len(group),
                            "support_pass_n": len(accepted),
                            "support_fail_n": len(rejected),
                            "support_pass_success_rate": fmt(
                                rate(sum(success(row) for row in accepted), len(accepted))
                            ),
                            "support_fail_success_rate": fmt(
                                rate(sum(success(row) for row in rejected), len(rejected))
                            ),
                            "raw_rate_difference": fmt(
                                (
                                    sum(success(row) for row in accepted) / len(accepted)
                                    - sum(success(row) for row in rejected) / len(rejected)
                                )
                                if accepted and rejected
                                else None
                            ),
                            "date_cluster_median": fmt(median_diff),
                            "date_cluster_lo": fmt(lo),
                            "date_cluster_hi": fmt(hi),
                        }
                    )
    for scope in ("ALL", "09:30-11:30"):
        scoped = (
            roots
            if scope == "ALL"
            else [row for row in roots if row["time_window"] == scope]
        )
        for interaction in ("ZERO", "TWO_SIDED"):
            group = [
                row
                for row in scoped
                if (
                    "TWO_SIDED"
                    if (number(row.get("to_proximity_band_min_side_qty")) or 0.0)
                    > 0
                    else "ZERO"
                )
                == interaction
            ]
            passed = lambda row: row.get("proximity_support_gate") == "PASS"
            success = lambda row: truth(row["advanced"])
            accepted = [row for row in group if passed(row)]
            rejected = [row for row in group if not passed(row)]
            median_diff, lo, hi = cluster_rate_difference(
                group,
                passed,
                success,
                bootstrap_samples,
                seed=20260789 + len(output),
            )
            output.append(
                {
                    "population": "initial_proximity",
                    "scope": scope,
                    "interaction_phase": "known_to_proximity",
                    "interaction": interaction,
                    "n": len(group),
                    "support_pass_n": len(accepted),
                    "support_fail_n": len(rejected),
                    "support_pass_success_rate": fmt(
                        rate(sum(success(row) for row in accepted), len(accepted))
                    ),
                    "support_fail_success_rate": fmt(
                        rate(sum(success(row) for row in rejected), len(rejected))
                    ),
                    "raw_rate_difference": fmt(
                        (
                            sum(success(row) for row in accepted) / len(accepted)
                            - sum(success(row) for row in rejected) / len(rejected)
                        )
                        if accepted and rejected
                        else None
                    ),
                    "date_cluster_median": fmt(median_diff),
                    "date_cluster_lo": fmt(lo),
                    "date_cluster_hi": fmt(hi),
                }
            )
    approach_rows = [
        row for row in roots if truth(row.get("approach_retest_opportunity"))
    ]
    for scope in ("ALL", "09:30-11:30"):
        scoped = (
            approach_rows
            if scope == "ALL"
            else [row for row in approach_rows if row["time_window"] == scope]
        )
        for interaction in ("ZERO", "TWO_SIDED"):
            group = [
                row
                for row in scoped
                if (
                    "TWO_SIDED"
                    if (number(row.get("to_approach_band_min_side_qty")) or 0.0)
                    > 0
                    else "ZERO"
                )
                == interaction
            ]
            passed = lambda row: truth(row.get("approach_gate_filled"))
            success = lambda row: truth(row["advanced"])
            accepted = [row for row in group if passed(row)]
            rejected = [row for row in group if not passed(row)]
            median_diff, lo, hi = cluster_rate_difference(
                group,
                passed,
                success,
                bootstrap_samples,
                seed=20260823 + len(output),
            )
            output.append(
                {
                    "population": "prior_reapproach",
                    "scope": scope,
                    "interaction_phase": "known_to_reapproach",
                    "interaction": interaction,
                    "n": len(group),
                    "support_pass_n": len(accepted),
                    "support_fail_n": len(rejected),
                    "support_pass_success_rate": fmt(
                        rate(sum(success(row) for row in accepted), len(accepted))
                    ),
                    "support_fail_success_rate": fmt(
                        rate(sum(success(row) for row in rejected), len(rejected))
                    ),
                    "raw_rate_difference": fmt(
                        (
                            sum(success(row) for row in accepted) / len(accepted)
                            - sum(success(row) for row in rejected) / len(rejected)
                        )
                        if accepted and rejected
                        else None
                    ),
                    "date_cluster_median": fmt(median_diff),
                    "date_cluster_lo": fmt(lo),
                    "date_cluster_hi": fmt(hi),
                }
            )
    return output


def manual_cases(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    pre = [row for row in rows if row["time_window"] == "09:30-11:30"]
    groups: list[tuple[str, list[dict[str, Any]]]] = [
        (
            "WAIT_FOR_RAIL_MISSES_ADVANCE",
            [
                row
                for row in pre
                if truth(row["advanced"]) and not truth(row["rail_crossed"])
            ],
        ),
        (
            "TWO_SIDED_SUPPORT_PASS_ADVANCE",
            [
                row
                for row in pre
                if truth(row["advanced"])
                and truth(row["rail_crossed"])
                and (number(row.get("rail_5s_min_side_qty")) or 0.0) > 0
                and row.get("rail_support_gate") == "PASS"
            ],
        ),
        (
            "TWO_SIDED_SUPPORT_PASS_FAILURE",
            [
                row
                for row in pre
                if not truth(row["advanced"])
                and truth(row["rail_crossed"])
                and (number(row.get("rail_5s_min_side_qty")) or 0.0) > 0
                and row.get("rail_support_gate") == "PASS"
            ],
        ),
        (
            "HEAVY_EFFICIENT_FAILURE",
            [
                row
                for row in pre
                if not truth(row["advanced"])
                and row.get("arrival_bucket") == "HEAVY_EFFICIENT"
            ],
        ),
        (
            "REAPPROACH_TWO_SIDED_SUPPORT_PASS_ADVANCE",
            [
                row
                for row in rows
                if truth(row["advanced"])
                and truth(row.get("approach_retest_opportunity"))
                and (number(row.get("to_approach_band_min_side_qty")) or 0.0) > 0
                and truth(row.get("approach_gate_filled"))
            ],
        ),
        (
            "REAPPROACH_TWO_SIDED_SUPPORT_FAIL",
            [
                row
                for row in rows
                if truth(row.get("approach_retest_opportunity"))
                and (number(row.get("to_approach_band_min_side_qty")) or 0.0) > 0
                and not truth(row.get("approach_gate_filled"))
            ],
        ),
    ]
    output: list[dict[str, Any]] = []
    for case_type, candidates in groups:
        if case_type == "WAIT_FOR_RAIL_MISSES_ADVANCE":
            selected = sorted(candidates, key=lambda row: row["proximity_et"])[:10]
        elif case_type == "TWO_SIDED_SUPPORT_PASS_ADVANCE":
            selected = sorted(
                candidates,
                key=lambda row: number(row.get("rail_5s_min_side_qty")) or 0.0,
                reverse=True,
            )[:10]
        elif case_type == "TWO_SIDED_SUPPORT_PASS_FAILURE":
            selected = sorted(
                candidates,
                key=lambda row: number(row.get("rail_support_net_norm_5p0s"))
                or -math.inf,
                reverse=True,
            )[:10]
        else:
            selected = sorted(
                candidates,
                key=lambda row: number(
                    row.get("arrival_5s_adverse_ticks_per_10_qty")
                )
                or 0.0,
                reverse=True,
            )[:10]
        for row in selected:
            output.append(
                {
                    "case_type": case_type,
                    "date": row["date"],
                    "root_id": row["root_id"],
                    "side": row["side"],
                    "root_lo": row["root_lo"],
                    "root_hi": row["root_hi"],
                    "proximity_et": row["proximity_et"],
                    "rail_cross_et": row.get("rail_cross_et", ""),
                    "structural_outcome": row["structural_outcome"],
                    "rail_5s_min_side_qty": row.get("rail_5s_min_side_qty", ""),
                    "rail_support_net_norm_5p0s": row.get(
                        "rail_support_net_norm_5p0s", ""
                    ),
                    "rail_support_gate": row.get("rail_support_gate", ""),
                    "arrival_bucket": row.get("arrival_bucket", ""),
                    "arrival_5s_adverse_qty": row.get(
                        "arrival_5s_adverse_qty", ""
                    ),
                    "arrival_5s_adverse_ticks_per_10_qty": row.get(
                        "arrival_5s_adverse_ticks_per_10_qty", ""
                    ),
                    "approach_retest_et": row.get("approach_retest_et", ""),
                    "to_approach_band_min_side_qty": row.get(
                        "to_approach_band_min_side_qty", ""
                    ),
                    "approach_support_net_norm_2s": row.get(
                        "approach_support_net_norm_2s", ""
                    ),
                    "approach_gate_filled": row.get(
                        "approach_gate_filled", ""
                    ),
                }
            )
    return output


def markdown_table(
    rows: list[dict[str, Any]],
    fields: tuple[tuple[str, str], ...],
) -> list[str]:
    header = "| " + " | ".join(label for _, label in fields) + " |"
    separator = "|" + "|".join("---" for _ in fields) + "|"
    body = [
        "| "
        + " | ".join(str(row.get(field, "")) for field, _ in fields)
        + " |"
        for row in rows
    ]
    return [header, separator, *body]


def write_findings(
    path: Path,
    roots: list[dict[str, Any]],
    wait_summary: list[dict[str, Any]],
    initial_joint: list[dict[str, Any]],
    approach_joint: list[dict[str, Any]],
    joint: list[dict[str, Any]],
    arrivals: list[dict[str, Any]],
    arrival_support: list[dict[str, Any]],
    t0_audit: list[dict[str, Any]],
    edge_summary: list[dict[str, Any]],
    effects: list[dict[str, Any]],
    cases: list[dict[str, Any]],
) -> None:
    complete = len(roots)
    advanced = sum(truth(row["advanced"]) for row in roots)
    touched = sum(truth(row["rail_crossed"]) for row in roots)
    all_wait = next(row for row in wait_summary if row["scope"] == "ALL")
    pre_wait = next(
        row for row in wait_summary if row["scope"] == "09:30-11:30"
    )
    strongest_t0 = sorted(
        [row for row in t0_audit if row["scope"] == "ALL"],
        key=lambda row: number(row.get("separability_auc")) or 0.0,
        reverse=True,
    )[:5]
    lines = [
        "# Direct-Conversion Execution Phase Policy",
        "",
        "Research status: hypothesis generation. No EAR or LevelLedger rule changed.",
        "",
        "## Population And Definitions",
        "",
        f"- Complete roots: {complete}; advanced: {advanced}; failed: {complete - advanced}.",
        f"- An executable quote reached or crossed the favorable rail edge in {touched} roots.",
        "- `market at 20` uses the first state in EAR's envelope.",
        "- `wait for rail` enters when the executable quote first reaches or crosses the favorable edge.",
        "- `edge limit` is only a marketability counterfactual. A crossed quote does not prove queue fill.",
        "- Rail two-sided quantity is the minimum of owner-side and opponent-side aggressive quantity traded at the exact rail over the trailing five seconds.",
        "- The owner-support gate is leave-one-date-out. Its threshold is the 30th percentile of advancing rail tests on the other five dates.",
        "- Arrival efficiency is adverse quote progress per ten adverse aggressor contracts over the last up-to-five seconds. It is not available at the initial 20-tick decision.",
        "",
        "## Market At 20 Versus Wait For Rail",
        "",
        *markdown_table(
            wait_summary,
            (
                ("scope", "scope"),
                ("advanced", "adv"),
                ("failed", "fail"),
                ("wait_rail_advance_capture", "rail adv capture"),
                ("wait_rail_failure_exposure", "rail fail exposure"),
                ("support_gate_advance_capture", "rail+support adv"),
                ("support_gate_failure_exposure", "rail+support fail"),
                (
                    "initial_contest_gate_advance_capture",
                    "fresh/contested+support adv",
                ),
                (
                    "initial_contest_gate_failure_exposure",
                    "fresh/contested+support fail",
                ),
                ("advanced_market_improvement_median_pts", "winner market improvement"),
                ("advanced_delay_median_s", "winner delay s"),
            ),
        ),
        "",
        (
            "Waiting all the way to the rail changes the population materially: "
            f"overall advance capture is {all_wait['wait_rail_advance_capture']} "
            f"while failure exposure is {all_wait['wait_rail_failure_exposure']}. "
            f"Before 11:30 those rates are {pre_wait['wait_rail_advance_capture']} "
            f"and {pre_wait['wait_rail_failure_exposure']}."
        ),
        "",
        "A strictly causal initial-proximity cross:",
        "",
        *markdown_table(
            [
                row
                for row in initial_joint
                if row["scope"] in {"ALL", "09:30-11:30"}
            ],
            (
                ("scope", "scope"),
                ("known_interaction_at_proximity", "known interaction"),
                ("proximity_support_gate", "support"),
                ("n", "n"),
                ("advanced", "adv"),
                ("failed", "fail"),
                ("advance_rate", "advance rate"),
                ("days", "days"),
            ),
        ),
        "",
        "The `fresh/contested+support` policy keeps fresh roots eligible and suppresses only roots that had already printed two-sided exact-band business by proximity while contemporaneous owner support failed its held-out threshold.",
        "Only one root had such interaction by initial proximity, so this is not an actionable entry rule.",
        "",
        "## Can Initial Proximity State Identify Rail-Waitable Winners?",
        "",
        "The table is restricted to roots that eventually advanced. AUC measures whether information already present at 20 ticks separates winners that later reach the rail from winners that leave without doing so.",
        "",
        *markdown_table(
            strongest_t0,
            (
                ("feature", "feature"),
                ("waitable_n", "rail-touch winners"),
                ("flyaway_n", "no-touch winners"),
                ("separability_auc", "separability AUC"),
                ("waitable_when", "rail touch when"),
                ("waitable_median", "touch median"),
                ("flyaway_median", "no-touch median"),
            ),
        ),
        "",
        "## Arrival Shape At The Rail",
        "",
        *markdown_table(
            [row for row in arrivals if row["scope"] in {"ALL", "09:30-11:30"}],
            (
                ("scope", "scope"),
                ("arrival_bucket", "arrival"),
                ("n", "n"),
                ("advance_rate", "advance rate"),
                ("support_pass_rate", "support pass"),
                ("exact_band_quote_rate", "exact quote"),
                ("market_improvement_median_pts", "market improvement"),
                ("cross_penetration_median_ticks", "penetration ticks"),
            ),
        ),
        "",
        "These arrival buckets are descriptive. `THIN_EFFICIENT` means high adverse displacement efficiency with below-median adverse quantity; `HEAVY_ABSORBED` means above-median adverse quantity with low displacement efficiency.",
        "",
        "Arrival shape crossed with owner support:",
        "",
        *markdown_table(
            [
                row
                for row in arrival_support
                if row["scope"] in {"ALL", "09:30-11:30"}
                and row["arrival_bucket"]
                in {"HEAVY_ABSORBED", "HEAVY_EFFICIENT", "THIN_EFFICIENT"}
            ],
            (
                ("scope", "scope"),
                ("arrival_bucket", "arrival"),
                ("support_gate", "support"),
                ("n", "n"),
                ("advance_rate", "advance rate"),
                ("rail_two_sided_rate", "two-sided rate"),
                ("days", "days"),
            ),
        ),
        "",
        "## Interaction Plus Owner Support",
        "",
        "The prior eight-tick escape-return re-approach, where the earlier ownership result was measured:",
        "",
        *markdown_table(
            [
                row
                for row in approach_joint
                if row["scope"] in {"ALL", "09:30-11:30"}
            ],
            (
                ("scope", "scope"),
                ("interaction_by_reapproach", "interaction"),
                ("heldout_approach_support_gate", "support"),
                ("n", "n"),
                ("advanced", "adv"),
                ("failed", "fail"),
                ("advance_rate", "advance rate"),
                ("days", "days"),
            ),
        ),
        "",
        "First rail crossing:",
        "",
        *markdown_table(
            [
                row
                for row in joint
                if row["scope"] in {"ALL", "09:30-11:30"}
                and row["interaction_phase"] == "rail_5s"
            ],
            (
                ("scope", "scope"),
                ("interaction", "rail interaction"),
                ("support_gate", "support"),
                ("n", "n"),
                ("advanced", "adv"),
                ("failed", "fail"),
                ("advance_rate", "advance rate"),
                ("days", "days"),
            ),
        ),
        "",
        "Later reclaimed-edge test:",
        "",
        *markdown_table(
            [
                row
                for row in edge_summary
                if row["scope"] in {"ALL", "09:30-11:30"}
                and row["interaction_phase"] == "reclaim_transit"
            ],
            (
                ("scope", "scope"),
                ("interaction", "reclaim interaction"),
                ("support_gate", "support"),
                ("n", "n"),
                ("advance_rate", "advance rate"),
                ("readvance_rate", "local readvance"),
                ("days", "days"),
            ),
        ),
        "",
        "Date-cluster support effects within interaction strata:",
        "",
        *markdown_table(
            [
                row
                for row in effects
                if row["scope"] == "09:30-11:30"
                and row["interaction_phase"] == "current_phase"
            ],
            (
                ("population", "phase"),
                ("interaction", "interaction"),
                ("n", "n"),
                ("support_pass_success_rate", "support pass success"),
                ("support_fail_success_rate", "support fail success"),
                ("raw_rate_difference", "raw difference"),
                ("date_cluster_lo", "cluster 2.5%"),
                ("date_cluster_hi", "cluster 97.5%"),
            ),
        ),
        "",
        "Initial proximity support conditioned on interaction already known at that instant:",
        "",
        *markdown_table(
            [
                row
                for row in effects
                if row["population"] == "initial_proximity"
            ],
            (
                ("scope", "scope"),
                ("interaction", "known interaction"),
                ("n", "n"),
                ("support_pass_success_rate", "support pass success"),
                ("support_fail_success_rate", "support fail success"),
                ("raw_rate_difference", "raw difference"),
                ("date_cluster_lo", "cluster 2.5%"),
                ("date_cluster_hi", "cluster 97.5%"),
            ),
        ),
        "",
        "Prior re-approach support conditioned on interaction accumulated by that re-approach:",
        "",
        *markdown_table(
            [
                row
                for row in effects
                if row["population"] == "prior_reapproach"
            ],
            (
                ("scope", "scope"),
                ("interaction", "interaction"),
                ("n", "n"),
                ("support_pass_success_rate", "support pass success"),
                ("support_fail_success_rate", "support fail success"),
                ("raw_rate_difference", "raw difference"),
                ("date_cluster_lo", "cluster 2.5%"),
                ("date_cluster_hi", "cluster 97.5%"),
            ),
        ),
        "",
        "The corresponding all-day reclaimed-edge local-readvance effects are:",
        "",
        *markdown_table(
            [
                row
                for row in effects
                if row["scope"] == "ALL"
                and row["interaction_phase"] == "current_phase"
                and row["population"] == "reclaimed_edge_local"
            ],
            (
                ("interaction", "interaction"),
                ("n", "n"),
                ("support_pass_success_rate", "support pass readvance"),
                ("support_fail_success_rate", "support fail readvance"),
                ("raw_rate_difference", "raw difference"),
                ("date_cluster_lo", "cluster 2.5%"),
                ("date_cluster_hi", "cluster 97.5%"),
            ),
        ),
        "",
        "## Decision Boundary",
        "",
        "1. Approach efficiency measured on the road from 20 ticks to the rail cannot justify the initial market-at-20 decision because it does not exist yet.",
        "2. The initial proximity fields are audited above specifically for the narrower question of which successful roots are safe to wait on. Weak separation means a universal wait-for-rail rule would knowingly miss successful campaigns.",
        "3. At the actual rail, arrival shape should not choose `limit versus market` by itself. The defensible interaction is arrival plus owner support. A thin/effective adverse approach with absent support is evidence to withhold, not merely to switch from market to a passive order.",
        "4. A passive edge order has queue and fill uncertainty that this recorder cannot resolve. The data can compare price opportunity and quote crossing; it cannot certify limit fills.",
        "5. The later reclaimed-edge support result is a different policy surface: hold, rearm, or promotion after repair. It must not be back-projected into the first proximity entry.",
        "",
        "## Files",
        "",
        "- `root_phase_rows.csv`: one row per complete root.",
        "- `wait_policy_summary.csv`: market-at-20 versus rail-wait counterfactual.",
        "- `initial_proximity_joint_summary.csv`: only interaction and support known by the first 20-tick decision.",
        "- `approach_joint_summary.csv`: earlier escape-return support crossed with interaction known by that re-approach.",
        "- `joint_state_summary.csv`: rail interaction crossed with held-out owner support.",
        "- `arrival_shape_summary.csv`: thin/heavy and efficient/absorbed arrival buckets.",
        "- `t0_waitability_feature_audit.csv`: only information available at initial proximity.",
        "- `reclaimed_edge_joint_summary.csv`: later repair/reclaim interaction.",
        "- `support_interaction_effects.csv`: date-cluster uncertainty.",
        "- `manual_cases.csv`: pre-11:30 examples and counterexamples for chart review.",
        "",
        "## Manual Review Surface",
        "",
        *markdown_table(
            cases,
            (
                ("case_type", "case"),
                ("date", "date"),
                ("root_id", "root"),
                ("side", "side"),
                ("root_lo", "lo"),
                ("root_hi", "hi"),
                ("proximity_et", "proximity"),
                ("rail_cross_et", "rail cross"),
            ),
        ),
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    args = parse_args()
    episodes, samples = load_population(args.proximity_dir)
    roots = build_root_rows(episodes, samples, args.lifecycle_dir)
    add_heldout_proximity_support_gate(roots)
    add_heldout_support_gate(roots)
    add_heldout_arrival_bucket(roots)
    wait_summary = wait_policy_summary(roots)
    initial_joint = initial_joint_summary(roots)
    approach_joint = approach_joint_summary(roots)
    joint = joint_summary(roots)
    arrivals = arrival_summary(roots)
    arrival_support = arrival_support_summary(roots)
    t0_audit = t0_waitability_audit(roots)
    edge_rows = edge_reclaim_joint(args.lifecycle_dir)
    edge_summary = edge_reclaim_summary(edge_rows)
    effects = support_interaction_effects(
        roots, edge_rows, args.bootstrap_samples
    )
    cases = manual_cases(roots)

    write_csv(args.out_dir / "root_phase_rows.csv", roots)
    write_csv(args.out_dir / "wait_policy_summary.csv", wait_summary)
    write_csv(
        args.out_dir / "initial_proximity_joint_summary.csv", initial_joint
    )
    write_csv(args.out_dir / "approach_joint_summary.csv", approach_joint)
    write_csv(args.out_dir / "joint_state_summary.csv", joint)
    write_csv(args.out_dir / "arrival_shape_summary.csv", arrivals)
    write_csv(
        args.out_dir / "arrival_support_summary.csv", arrival_support
    )
    write_csv(args.out_dir / "t0_waitability_feature_audit.csv", t0_audit)
    write_csv(args.out_dir / "reclaimed_edge_rows.csv", edge_rows)
    write_csv(args.out_dir / "reclaimed_edge_joint_summary.csv", edge_summary)
    write_csv(args.out_dir / "support_interaction_effects.csv", effects)
    write_csv(args.out_dir / "manual_cases.csv", cases)
    write_findings(
        args.out_dir / "findings.md",
        roots,
        wait_summary,
        initial_joint,
        approach_joint,
        joint,
        arrivals,
        arrival_support,
        t0_audit,
        edge_summary,
        effects,
        cases,
    )


if __name__ == "__main__":
    main()
