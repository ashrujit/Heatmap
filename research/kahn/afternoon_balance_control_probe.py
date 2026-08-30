"""Codex-authored control probe for late-day value-churn shorts.

This script checks the 2026-08-28 ES short around 7725/7726 as a negative
control for the HoldRoot scale research. The point is not whether the root
short could eventually pay. The point is whether Kahn should press leverage
while price is accepted around a high-volume/value-center node.

The output is research only. It is not accepted Kahn policy.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import polars as pl

from holdroot_scale_probe import (
    Case,
    REPO,
    collect_scale_candidates,
    hms_from_us,
    ll_transitions,
    load_case_ticks,
    mfe_mae,
    ny_us,
    parse_hms_us,
    range_intersects,
    target_floor,
    transition_price,
    transition_time_us,
)
from local_lvn_separator_probe import profile_map
from sponsor_stack_scale_probe import collect_sponsor_stack_candidates
from tail_reclaim_sequence_probe import collect_tail_reclaim_sequences


CONTROL_CASE = Case(
    case_id="es_20260828_1345_short_7726_control",
    day="2026-08-28",
    symbol_dir="ESU6",
    side="short",
    entry_time="13:49:34",
    entry_ref=7726.0,
    window="13:15-15:15",
    focus_lo=7712.0,
    focus_hi=7734.0,
    target_lo=7713.25,
    target_hi=7716.5,
    notes=(
        "Late-day control case: short near value-center/HVN, testing root-only "
        "versus leverage/BE behavior."
    ),
)

BALANCE_START = "13:45:00"
BALANCE_END = "14:30:00"
LATE_EXTENSION_START = "14:45:00"
STRUCTURAL_BREAK_LEVEL = 7720.0
FIRST_EXTENSION_LEVEL = 7716.5
FULL_ADD_CALLS = {
    "add_preserve_root",
    "add_preserve_root_reduced",
    "sponsor_stack_add",
    "sponsor_stack_add_reduced",
    "tail_reclaim_add",
    "tail_reclaim_add_reduced",
}
ADD_REVIEW_CALLS = {
    "add_review",
    "add_review_no_recent_opp_fail",
}
HARVEST_CALLS = {
    "mature_path_hold_only",
    "tail_reclaim_mature_path_harvest",
    "tail_reclaim_harvest_not_add",
}


@dataclass(frozen=True)
class RootScenario:
    scenario_id: str
    time: str
    ref: float
    notes: str


ROOT_SCENARIOS = (
    RootScenario(
        "first_supply_test_7726",
        "13:49:34",
        7726.0,
        "First 7726 repair/test against upper value supply.",
    ),
    RootScenario(
        "supply_hold_7724_50",
        "13:50:09",
        7724.5,
        "Hold confirmation after the first 7726 test.",
    ),
    RootScenario(
        "balance_retest_7726",
        "14:02:48",
        7726.0,
        "Second value-center retest near the same short area.",
    ),
)


def write_csv_union(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
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

    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def ticks_between(ticks: pl.DataFrame, start_us: int, end_us: int) -> pl.DataFrame:
    return ticks.filter((pl.col("timestamp_us") >= start_us) & (pl.col("timestamp_us") <= end_us))


def first_price_time(
    case: Case,
    ticks: pl.DataFrame,
    start_us: int,
    end_us: int,
    level: float,
) -> int | None:
    sub = ticks_between(ticks, start_us, end_us)
    if case.side == "short":
        hit = sub.filter(pl.col("price") <= level)
    else:
        hit = sub.filter(pl.col("price") >= level)
    if not hit.height:
        return None
    return int(hit["timestamp_us"][0])


def five_min_bars(ticks: pl.DataFrame, start_us: int, end_us: int) -> list[dict[str, Any]]:
    sub = ticks_between(ticks, start_us, end_us)
    if not sub.height:
        return []

    bars = (
        sub.with_columns(((pl.col("timestamp_us") - start_us) // 300_000_000).alias("bar_idx"))
        .sort("timestamp_us")
        .group_by("bar_idx", maintain_order=True)
        .agg(
            pl.col("timestamp_us").first().alias("first_us"),
            pl.col("timestamp_us").last().alias("last_us"),
            pl.col("price").first().alias("open"),
            pl.col("price").max().alias("high"),
            pl.col("price").min().alias("low"),
            pl.col("price").last().alias("close"),
            pl.col("size").sum().alias("volume"),
            (pl.col("size") * pl.col("aggressor_sign")).sum().alias("delta"),
        )
    )
    return [
        {
            "bar_start": hms_from_us(start_us + int(row["bar_idx"]) * 300_000_000),
            "open": float(row["open"]),
            "high": float(row["high"]),
            "low": float(row["low"]),
            "close": float(row["close"]),
            "volume": round(float(row["volume"]), 1),
            "delta": round(float(row["delta"]), 1),
        }
        for row in bars.iter_rows(named=True)
    ]


def first_n_closes_below(
    bars: list[dict[str, Any]],
    level: float,
    count: int,
    earliest_bar_start: str,
) -> str:
    consecutive = 0
    for bar in bars:
        if str(bar["bar_start"]) < earliest_bar_start:
            continue
        below = float(bar["close"]) < level
        consecutive = consecutive + 1 if below else 0
        if consecutive >= count:
            return str(bar["bar_start"])
    return "-"


def next_close_above_after(bars: list[dict[str, Any]], level: float, after_hms: str) -> str:
    if after_hms == "-":
        return "-"
    for bar in bars:
        if str(bar["bar_start"]) <= after_hms:
            continue
        if float(bar["close"]) > level:
            return str(bar["bar_start"])
    return "-"


def be_return_after_favorable(
    case: Case,
    ticks: pl.DataFrame,
    start_us: int,
    end_us: int,
    ref: float,
    favorable_points: float,
    tolerance_points: float = 0.25,
) -> dict[str, Any]:
    sub = ticks_between(ticks, start_us, end_us).sort("timestamp_us")
    if not sub.height:
        return {
            "favorable_points": favorable_points,
            "favorable_time": "-",
            "be_return_time": "-",
            "be_return_after_min": "",
        }

    if case.side == "short":
        favored = sub.filter(pl.col("price") <= ref - favorable_points)
    else:
        favored = sub.filter(pl.col("price") >= ref + favorable_points)
    if not favored.height:
        return {
            "favorable_points": favorable_points,
            "favorable_time": "-",
            "be_return_time": "-",
            "be_return_after_min": "",
        }

    favored_us = int(favored["timestamp_us"][0])
    after = sub.filter(pl.col("timestamp_us") >= favored_us)
    if case.side == "short":
        returned = after.filter(pl.col("price") >= ref - tolerance_points)
    else:
        returned = after.filter(pl.col("price") <= ref + tolerance_points)

    if not returned.height:
        return {
            "favorable_points": favorable_points,
            "favorable_time": hms_from_us(favored_us),
            "be_return_time": "-",
            "be_return_after_min": "",
        }

    returned_us = int(returned["timestamp_us"][0])
    return {
        "favorable_points": favorable_points,
        "favorable_time": hms_from_us(favored_us),
        "be_return_time": hms_from_us(returned_us),
        "be_return_after_min": round((returned_us - favored_us) / 60_000_000, 1),
    }


def root_outcomes(case: Case, ticks: pl.DataFrame) -> list[dict[str, Any]]:
    end_us = ny_us(case.day, case.window.split("-", 1)[1])
    rows: list[dict[str, Any]] = []
    for scenario in ROOT_SCENARIOS:
        start_us = parse_hms_us(case.day, scenario.time)
        full = mfe_mae(case, ticks, start_us, end_us, scenario.ref)
        first_30 = mfe_mae(case, ticks, start_us, min(end_us, start_us + 30 * 60_000_000), scenario.ref)
        first_60 = mfe_mae(case, ticks, start_us, min(end_us, start_us + 60 * 60_000_000), scenario.ref)
        be2 = be_return_after_favorable(case, ticks, start_us, end_us, scenario.ref, 2.0)
        be4 = be_return_after_favorable(case, ticks, start_us, end_us, scenario.ref, 4.0)
        rows.append(
            {
                "case_id": case.case_id,
                "scenario_id": scenario.scenario_id,
                "time": scenario.time,
                "ref": scenario.ref,
                "target_floor": target_floor(case),
                "full_mfe": round(float(full["mfe"] or 0.0), 2),
                "full_mae": round(float(full["mae"] or 0.0), 2),
                "full_target_time": hms_from_us(full["target_time"]),
                "mfe_30m": round(float(first_30["mfe"] or 0.0), 2),
                "mae_30m": round(float(first_30["mae"] or 0.0), 2),
                "mfe_60m": round(float(first_60["mfe"] or 0.0), 2),
                "mae_60m": round(float(first_60["mae"] or 0.0), 2),
                "first_below_7720": hms_from_us(first_price_time(case, ticks, start_us, end_us, 7720.0)),
                "first_below_7716_50": hms_from_us(
                    first_price_time(case, ticks, start_us, end_us, FIRST_EXTENSION_LEVEL)
                ),
                "be2_favorable_time": be2["favorable_time"],
                "be2_return_time": be2["be_return_time"],
                "be2_return_after_min": be2["be_return_after_min"],
                "be4_favorable_time": be4["favorable_time"],
                "be4_return_time": be4["be_return_time"],
                "be4_return_after_min": be4["be_return_after_min"],
                "notes": scenario.notes,
            }
        )
    return rows


def profile_rows(case: Case, ticks: pl.DataFrame, start_hms: str, end_hms: str) -> list[dict[str, Any]]:
    start_us = parse_hms_us(case.day, start_hms)
    end_us = parse_hms_us(case.day, end_hms)
    profile = profile_map(ticks, start_us, end_us, case.focus_lo, case.focus_hi, bin_points=0.5)
    total = sum(float(row["vol"]) for row in profile.values())
    rows = []
    for bin_price, row in sorted(profile.items()):
        vol = float(row["vol"])
        rows.append(
            {
                "case_id": case.case_id,
                "window": f"{start_hms}-{end_hms}",
                "bin": bin_price,
                "volume": round(vol, 1),
                "volume_pct": round((vol / total) * 100.0, 2) if total > 0 else 0.0,
                "delta": round(float(row["delta"]), 1),
                "trades": int(row["trades"]),
                "seconds": int(row["seconds"]),
            }
        )
    return rows


def profile_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    active = [row for row in rows if float(row["volume"]) > 0]
    if not active:
        return {
            "poc_bin": "",
            "poc_volume": "",
            "top_bins": "",
            "hvn_band": "",
            "volume_center_share_pct": "",
        }

    ranked = sorted(active, key=lambda row: (-float(row["volume"]), float(row["bin"])))
    poc = ranked[0]
    top_bins = ranked[:8]
    hvn_bins = [float(row["bin"]) for row in top_bins[:5]]
    center_share = sum(
        float(row["volume"]) for row in active if 7721.0 <= float(row["bin"]) <= 7727.0
    ) / sum(float(row["volume"]) for row in active)
    return {
        "poc_bin": float(poc["bin"]),
        "poc_volume": float(poc["volume"]),
        "top_bins": ";".join(
            f"{float(row['bin']):g}:{float(row['volume']):.0f}/{int(row['seconds'])}s"
            for row in top_bins
        ),
        "hvn_band": f"{min(hvn_bins):g}-{max(hvn_bins) + 0.5:g}",
        "volume_center_share_pct": round(center_share * 100.0, 1),
    }


def claim_churn(
    case: Case,
    transitions: list[dict[str, Any]],
    start_hms: str,
    end_hms: str,
    lo: float = 7719.0,
    hi: float = 7729.0,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    start_us = parse_hms_us(case.day, start_hms)
    end_us = parse_hms_us(case.day, end_hms)
    rows: list[dict[str, Any]] = []
    previous_claim_side = ""
    side_switches = 0
    for transition in sorted(transitions, key=lambda item: transition_time_us(case, item)):
        t_us = transition_time_us(case, transition)
        if not (start_us <= t_us <= end_us):
            continue
        tr_lo = float(transition["min_price"])
        tr_hi = float(transition["max_price"])
        if not range_intersects(tr_lo, tr_hi, lo, hi):
            continue
        side = str(transition.get("side", ""))
        action = str(transition.get("action", ""))
        row = {
            "case_id": case.case_id,
            "time": transition["time"],
            "side": side,
            "action": action,
            "source": transition.get("source", ""),
            "range": transition.get("range", ""),
            "current_price": transition_price(transition),
            "score": round(float(transition.get("score") or 0.0), 3),
        }
        rows.append(row)
        if action in {"HOLD", "OWNED", "CONSUMED"}:
            if previous_claim_side and previous_claim_side != side:
                side_switches += 1
            previous_claim_side = side

    summary = {
        "case_id": case.case_id,
        "window": f"{start_hms}-{end_hms}",
        "rows": len(rows),
        "supply_claims": sum(
            1
            for row in rows
            if row["side"] == "supply" and row["action"] in {"HOLD", "OWNED", "CONSUMED"}
        ),
        "demand_claims": sum(
            1
            for row in rows
            if row["side"] == "demand" and row["action"] in {"HOLD", "OWNED", "CONSUMED"}
        ),
        "supply_fails": sum(1 for row in rows if row["side"] == "supply" and row["action"] == "FAIL"),
        "demand_fails": sum(1 for row in rows if row["side"] == "demand" and row["action"] == "FAIL"),
        "claim_side_switches": side_switches,
    }
    return rows, summary


def bars_summary(case: Case, ticks: pl.DataFrame) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    start_us = parse_hms_us(case.day, "13:15:00")
    end_us = parse_hms_us(case.day, "15:15:00")
    bars = five_min_bars(ticks, start_us, end_us)
    if not bars:
        return [], {}

    balance_bars = [bar for bar in bars if BALANCE_START <= str(bar["bar_start"]) < BALANCE_END]
    two_below_7720 = first_n_closes_below(bars, STRUCTURAL_BREAK_LEVEL, 2, BALANCE_START)
    three_below_7720 = first_n_closes_below(bars, STRUCTURAL_BREAK_LEVEL, 3, BALANCE_START)
    balance_summary = {
        "case_id": case.case_id,
        "balance_window": f"{BALANCE_START}-{BALANCE_END}",
        "balance_high": max(float(bar["high"]) for bar in balance_bars),
        "balance_low": min(float(bar["low"]) for bar in balance_bars),
        "balance_close_min": min(float(bar["close"]) for bar in balance_bars),
        "balance_close_max": max(float(bar["close"]) for bar in balance_bars),
        "balance_volume": round(sum(float(bar["volume"]) for bar in balance_bars), 1),
        "balance_delta": round(sum(float(bar["delta"]) for bar in balance_bars), 1),
        "first_two_closes_below_7720_after_balance": two_below_7720,
        "next_close_back_above_7720_after_two_below": next_close_above_after(
            bars,
            STRUCTURAL_BREAK_LEVEL,
            two_below_7720,
        ),
        "first_three_closes_below_7720_after_balance": three_below_7720,
        "first_two_closes_below_7716_50_after_balance": first_n_closes_below(
            bars,
            FIRST_EXTENSION_LEVEL,
            2,
            BALANCE_START,
        ),
    }
    return bars, balance_summary


def balance_overlay_call(
    case: Case,
    row: dict[str, Any],
    profile: dict[str, Any],
    churn: dict[str, Any],
) -> str:
    t_us = parse_hms_us(case.day, str(row["time"]))
    balance_start = parse_hms_us(case.day, BALANCE_START)
    balance_end = parse_hms_us(case.day, BALANCE_END)
    late_extension = parse_hms_us(case.day, LATE_EXTENSION_START)
    supply_claims = int(churn.get("supply_claims") or 0)
    demand_claims = int(churn.get("demand_claims") or 0)
    center_share = float(profile.get("volume_center_share_pct") or 0.0)
    in_balance = balance_start <= t_us <= balance_end
    two_sided = supply_claims >= 3 and demand_claims >= 3
    accepted_center = center_share >= 55.0

    if in_balance and two_sided and accepted_center:
        return "suppress_add_value_churn_root_only"
    if t_us >= late_extension:
        return "late_extension_no_new_leverage"
    return "allow_probe_policy_to_decide"


def probe_candidates(
    case: Case,
    transitions: list[dict[str, Any]],
    ticks: pl.DataFrame,
    profile: dict[str, Any],
    churn: dict[str, Any],
) -> list[dict[str, Any]]:
    holdroot_rows = collect_scale_candidates(case, transitions, ticks)
    _, sponsor_rows = collect_sponsor_stack_candidates(case, transitions, ticks)
    tail_rows, _ = collect_tail_reclaim_sequences(case, transitions, ticks)
    combined: list[dict[str, Any]] = []

    for source, rows in (
        ("holdroot_basic", holdroot_rows),
        ("sponsor_stack", sponsor_rows),
        ("tail_reclaim", tail_rows),
    ):
        for row in rows:
            call = str(row.get("call", ""))
            if call not in FULL_ADD_CALLS and call not in ADD_REVIEW_CALLS and call not in HARVEST_CALLS:
                continue
            combined.append(
                {
                    "case_id": case.case_id,
                    "probe": source,
                    "time": row.get("time", ""),
                    "action": row.get("action", ""),
                    "range": row.get("range", ""),
                    "current_price": row.get("current_price", ""),
                    "flow_grade": row.get("flow_grade", ""),
                    "replenish": row.get("replenish", ""),
                    "runway_points": row.get("runway_points", ""),
                    "path_consumed_pct": row.get("path_consumed_pct", ""),
                    "future_mfe": row.get("future_mfe", ""),
                    "future_mae": row.get("future_mae", ""),
                    "future_target_time": row.get("future_target_time", ""),
                    "raw_call": call,
                    "balance_overlay_call": balance_overlay_call(case, row, profile, churn),
                }
            )

    overlay_order = {
        "suppress_add_value_churn_root_only": 0,
        "late_extension_no_new_leverage": 1,
        "allow_probe_policy_to_decide": 2,
    }
    probe_order = {
        "sponsor_stack": 0,
        "holdroot_basic": 1,
        "tail_reclaim": 2,
    }

    return sorted(
        combined,
        key=lambda row: (
            overlay_order.get(str(row["balance_overlay_call"]), 99),
            0 if str(row["raw_call"]) in FULL_ADD_CALLS else 1,
            probe_order.get(str(row["probe"]), 99),
            str(row["time"]),
        ),
    )


def report_markdown(
    case: Case,
    outcomes: list[dict[str, Any]],
    profile: dict[str, Any],
    churn: dict[str, Any],
    bars: list[dict[str, Any]],
    bar_summary: dict[str, Any],
    candidates: list[dict[str, Any]],
) -> str:
    add_rows = [row for row in candidates if str(row["raw_call"]) in FULL_ADD_CALLS]
    review_rows = [row for row in candidates if str(row["raw_call"]) in ADD_REVIEW_CALLS]
    suppressed = [
        row
        for row in add_rows
        if row["balance_overlay_call"] == "suppress_add_value_churn_root_only"
    ]
    suppressed_review = [
        row
        for row in review_rows
        if row["balance_overlay_call"] == "suppress_add_value_churn_root_only"
    ]
    late = [row for row in add_rows if row["balance_overlay_call"] == "late_extension_no_new_leverage"]
    first = outcomes[0]
    two_closes_7720 = str(bar_summary.get("first_two_closes_below_7720_after_balance", "-"))
    two_closes_7720_repair = str(bar_summary.get("next_close_back_above_7720_after_two_below", "-"))
    three_closes_7720 = str(bar_summary.get("first_three_closes_below_7720_after_balance", "-"))
    two_closes_7716 = str(bar_summary.get("first_two_closes_below_7716_50_after_balance", "-"))

    lines = [
        "# Afternoon Balance Control Probe",
        "",
        "Codex-authored research artifact. This is not accepted Kahn policy.",
        "",
        "Objective: use the 2026-08-28 ES short around 7725/7726 as a control "
        "case for scale-up logic. The question is not whether a root short could "
        "eventually work; it is whether Kahn should add size while price is "
        "accepted around value/HVN late in the session.",
        "",
        "## Root Outcomes",
        "",
        "| scenario | time | ref | 30m MFE/MAE | 60m MFE/MAE | full MFE/MAE | target | BE after +2 | BE after +4 |",
        "| --- | --- | ---: | ---: | ---: | ---: | --- | --- | --- |",
    ]
    for row in outcomes:
        lines.append(
            f"| {row['scenario_id']} | {row['time']} | {row['ref']} | "
            f"{row['mfe_30m']}/{row['mae_30m']} | {row['mfe_60m']}/{row['mae_60m']} | "
            f"{row['full_mfe']}/{row['full_mae']} | {row['full_target_time']} | "
            f"{row['be2_return_time']} | {row['be4_return_time']} |"
        )

    lines.extend(
        [
            "",
            "## Value-Churn Evidence",
            "",
            f"- Balance window `{BALANCE_START}-{BALANCE_END}` traded "
            f"{bar_summary.get('balance_low')}-{bar_summary.get('balance_high')} with "
            f"closes contained between {bar_summary.get('balance_close_min')}-"
            f"{bar_summary.get('balance_close_max')}.",
            f"- Local profile POC was `{profile['poc_bin']}` and the top local HVN band was "
            f"`{profile['hvn_band']}`; {profile['volume_center_share_pct']}% of local volume "
            "printed inside 7721-7727.",
            f"- Top local bins: {profile['top_bins']}.",
            f"- LL churn in 7719-7729 had {churn['supply_claims']} supply claims, "
            f"{churn['demand_claims']} demand claims, {churn['supply_fails']} supply fails, "
            f"{churn['demand_fails']} demand fails, and {churn['claim_side_switches']} "
            "claim-side switches.",
            f"- First two post-balance 5-minute closes below 7720 arrived at `{two_closes_7720}`, "
            f"but the next close back above 7720 arrived at `{two_closes_7720_repair}`.",
            f"- First three post-balance closes below 7720 arrived at `{three_closes_7720}`; "
            f"first two closes below 7716.50 arrived at `{two_closes_7716}`.",
            "",
            "## Candidate Probe Rows",
            "",
        ]
    )
    display_rows = candidates[:18]
    if display_rows:
        lines.extend(
            [
                "| probe | time | range | raw call | overlay call | runway | path% | future MFE/MAE |",
                "| --- | --- | --- | --- | --- | ---: | ---: | ---: |",
            ]
        )
        for row in display_rows:
            lines.append(
                f"| {row['probe']} | {row['time']} | {row['range']} | {row['raw_call']} | "
                f"{row['balance_overlay_call']} | {row['runway_points']} | "
                f"{row['path_consumed_pct']} | {row['future_mfe']}/{row['future_mae']} |"
            )
    else:
        lines.append("- no add-like rows emitted by the scale probes")

    lines.extend(
        [
            "",
            "## Read",
            "",
            f"A root-only short from {first['time']} at {first['ref']} eventually had "
            f"{first['full_mfe']} points of MFE and only {first['full_mae']} points "
            f"of MAE, reaching the {target_floor(case)} floor at {first['full_target_time']}. "
            "So the root thesis was not absurd.",
            "",
            "That is not the same as add permission. The trade spent the core "
            "13:45-14:30 window rotating inside a local HVN/value-center band, with "
            "two-sided LL ownership claims and repeated returns toward the short "
            "area. The extension signal did not become structurally cleaner until "
            "after acceptance below 7720, and by then the session had shifted into "
            "late-day harvest/no-new-leverage territory.",
            "",
            f"The control result: {len(suppressed)} add-permission rows and "
            f"{len(suppressed_review)} add-review rows were suppressed by "
            f"value-churn context; {len(late)} add-permission rows occurred only "
            "after the late extension gate. The policy implication is `root_only` or "
            "`max_adds=0` inside this state. If a trader chooses leverage anyway, "
            "a BE scratch after the market repairs back into the HVN is an acceptable "
            "outcome, not evidence that Kahn should keep pressing.",
        ]
    )

    if bars:
        lines.extend(["", "## Five-Minute Bars", ""])
        for bar in bars:
            lines.append(
                f"- {bar['bar_start']} O {bar['open']} H {bar['high']} L {bar['low']} "
                f"C {bar['close']} vol {bar['volume']} delta {bar['delta']}"
            )

    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--out-dir",
        default=str(REPO / "research" / "kahn" / "out" / "afternoon-balance-control-20260830"),
    )
    args = parser.parse_args()
    out_dir = Path(args.out_dir)

    print(f"# {CONTROL_CASE.case_id}")
    transitions = ll_transitions(CONTROL_CASE)
    ticks = load_case_ticks(CONTROL_CASE)
    outcomes = root_outcomes(CONTROL_CASE, ticks)
    prof_rows = profile_rows(CONTROL_CASE, ticks, BALANCE_START, BALANCE_END)
    prof_summary = profile_summary(prof_rows)
    churn_rows, churn_summary = claim_churn(CONTROL_CASE, transitions, BALANCE_START, BALANCE_END)
    bars, bar_summary = bars_summary(CONTROL_CASE, ticks)
    candidates = probe_candidates(CONTROL_CASE, transitions, ticks, prof_summary, churn_summary)

    write_csv_union(out_dir / "root_outcomes.csv", outcomes)
    write_csv_union(out_dir / "local_profile_1345_1430.csv", prof_rows)
    write_csv_union(out_dir / "claim_churn_1345_1430.csv", churn_rows)
    write_csv_union(out_dir / "bars_1315_1515.csv", bars)
    write_csv_union(out_dir / "balance_summary.csv", [{**prof_summary, **churn_summary, **bar_summary}])
    write_csv_union(out_dir / "candidate_overlay_rows.csv", candidates)

    report = report_markdown(
        CONTROL_CASE,
        outcomes,
        prof_summary,
        churn_summary,
        bars,
        bar_summary,
        candidates,
    )
    (out_dir / "report.md").write_text(report, encoding="utf-8")
    print(report)


if __name__ == "__main__":
    main()
