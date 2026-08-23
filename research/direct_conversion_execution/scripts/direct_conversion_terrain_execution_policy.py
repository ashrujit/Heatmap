"""Counterfactual execution policies after a direct conversion's first test holds.

The population is synthetic LL consumed rails with a causally known
HELD_FIRST_TEST verdict. Profile features are frozen at that verdict timestamp.
Subsequent tape is used only to infer hypothetical entry opportunities and
measure the path until the root either establishes a favorable successor or
fails.

This is an execution-policy study, not a PnL backtest. Passive fills are
opportunities inferred from opposite-aggressor trades through the limit; queue
priority and slippage are unavailable.
"""

from __future__ import annotations

import argparse
import bisect
import csv
import math
import random
import statistics
import sys
from collections import Counter, defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo

from _paths import OUTPUT_ROOT

from capture_loader import load_capture_window, tick_columns  # noqa: E402


NY = ZoneInfo("America/New_York")
TICK_SIZE = 0.25
ADVANCED = "ADVANCED_AFTER_FIRST_HOLD"
FAILED = "ROOT_FAILED_AFTER_FIRST_HOLD"
DEFAULT_LINEAGE = (
    OUTPUT_ROOT / "direct_conversion_sponsor_lineage" / "lineage.csv"
)
DEFAULT_PROFILES = (
    OUTPUT_ROOT / "direct_conversion_profile_field_20260716_20260724"
    / "profile_locations.csv"
)
DEFAULT_OUT = (
    OUTPUT_ROOT / "direct_conversion_terrain_execution_20260716_20260724"
)
PRIMARY_SCOPE = "60m"
PRIMARY_BIN_POINTS = 2.0


@dataclass(frozen=True)
class Root:
    session_id: str
    date: str
    root_id: str
    side: str
    direction: int
    lo: float
    hi: float
    owned: datetime
    first_test: datetime
    hold: datetime
    resolution: datetime
    outcome: str
    successor_id: str
    observed_roles: str
    role_context: str


@dataclass(frozen=True)
class Tape:
    times: list[int]
    prices: list[float]
    sizes: list[float]
    signs: list[int]


@dataclass(frozen=True)
class Fill:
    timestamp_us: int
    price: float
    mode: str
    trigger: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lineage-csv", type=Path, default=DEFAULT_LINEAGE)
    parser.add_argument("--profile-csv", type=Path, default=DEFAULT_PROFILES)
    parser.add_argument("--start-date", default="2026-07-16")
    parser.add_argument("--end-date", default="2026-07-24")
    parser.add_argument("--symbol-dir", default="NQU6")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    parser.add_argument(
        "--passive-timeouts",
        default="15,30,60",
        help="Comma-separated passive-only lifetimes in seconds.",
    )
    parser.add_argument(
        "--acceptance-window-s",
        type=float,
        default=2.0,
        help="Trailing window for the two-sided HVN escape sensitivity.",
    )
    parser.add_argument(
        "--acceptance-min-trades",
        type=int,
        default=4,
        help="Minimum beyond-edge prints in the two-sided escape window.",
    )
    return parser.parse_args()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    columns: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for key in row:
            if key not in seen:
                seen.add(key)
                columns.append(key)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: csv_value(row.get(key)) for key in columns})


def csv_value(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, float):
        if not math.isfinite(value):
            return ""
        return round(value, 6)
    return value


def parse_et(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%d %H:%M:%S.%f").replace(tzinfo=NY)


def timestamp_us(value: datetime) -> int:
    return int(value.timestamp() * 1_000_000)


def number(value: Any) -> float | None:
    if value in ("", None):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def truth(value: Any) -> bool:
    return str(value).strip().lower() == "true"


def role_context(row: dict[str, str]) -> str:
    same_behind = number(row.get("hold_live_50pts_same_behind")) or 0.0
    return "add_like_parent_live" if same_behind > 0 else "base_like_no_parent"


def age_bucket(seconds: float) -> str:
    if seconds <= 30:
        return "prompt_le_30s"
    if seconds <= 300:
        return "developing_30s_to_5m"
    return "late_gt_5m"


def load_roots(
    path: Path,
    start_date: str,
    end_date: str,
) -> dict[tuple[str, str, str], Root]:
    output: dict[tuple[str, str, str], Root] = {}
    for row in read_csv(path):
        if not start_date <= row.get("date", "") <= end_date:
            continue
        if row.get("root_first_test_verdict") != "HELD_FIRST_TEST":
            continue
        outcome = row.get("hold_structural_outcome", "")
        if outcome not in {ADVANCED, FAILED}:
            continue
        hold_text = row.get("root_first_test_resolved_et", "")
        owned_text = row.get("root_owned_et", "")
        test_text = row.get("root_first_tested_et", "")
        resolution_text = (
            row.get("post_hold_successor_owned_et", "")
            if outcome == ADVANCED
            else row.get("root_failed_et", "")
        )
        lo = number(row.get("root_lo"))
        hi = number(row.get("root_hi"))
        if (
            not owned_text
            or not test_text
            or not hold_text
            or not resolution_text
            or lo is None
            or hi is None
        ):
            continue
        owned = parse_et(owned_text)
        first_test = parse_et(test_text)
        hold = parse_et(hold_text)
        resolution = parse_et(resolution_text)
        if resolution <= hold:
            continue
        side = row["side"]
        root = Root(
            session_id=row.get("session_id", ""),
            date=row["date"],
            root_id=row["root_id"],
            side=side,
            direction=1 if side == "Demand" else -1,
            lo=lo,
            hi=hi,
            owned=owned,
            first_test=first_test,
            hold=hold,
            resolution=resolution,
            outcome=outcome,
            successor_id=row.get("post_hold_successor_id", ""),
            observed_roles=row.get("entry_roles", ""),
            role_context=role_context(row),
        )
        output[(root.session_id, root.date, root.root_id)] = root
    return output


def load_profiles(
    path: Path,
    roots: dict[tuple[str, str, str], Root],
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for row in read_csv(path):
        if row.get("source") != "lineage" or row.get("query_kind") not in {
            "first_test",
            "first_hold",
        }:
            continue
        root = roots.get(
            (
                row.get("session_id", ""),
                row.get("date", ""),
                row.get("root_id", ""),
            )
        )
        if root is None:
            continue
        bin_points = number(row.get("bin_points"))
        if bin_points is None:
            continue
        rec: dict[str, Any] = dict(row)
        rec["bin_points"] = bin_points
        rec["profile_valid"] = truth(row.get("profile_valid"))
        rec["decision_stage"] = row["query_kind"]
        rec["config"] = f"{row.get('scope')}:{bin_points:g}pt"
        rec["terrain_class"] = terrain_class(row)
        output.append(rec)
    return output


def terrain_class(row: dict[str, Any]) -> str:
    field_state = str(row.get("field_state") or "")
    topology = str(row.get("topology") or "")
    if field_state == "hvn_anchor_not_escaped":
        return "hvn_unescaped"
    if field_state == "hvn_anchor_escaped":
        return "hvn_escaped"
    if "lvn" in topology:
        return "lvn"
    if topology == "transition":
        return "transition"
    return "other"


def load_tape(roots: Iterable[Root], symbol_dir: str) -> Tape:
    root_list = list(roots)
    start = min(root.first_test for root in root_list) - timedelta(seconds=1)
    end = max(root.resolution for root in root_list) + timedelta(seconds=1)
    frame = load_capture_window(
        "ticks",
        symbol_dir,
        start,
        end,
        tick_columns(),
        inclusive_end=True,
    )
    return Tape(
        times=[int(value) for value in frame["timestamp_us"].to_list()],
        prices=[float(value) for value in frame["price"].to_list()],
        sizes=[float(value) for value in frame["size"].to_list()],
        signs=[int(value) for value in frame["aggressor_sign"].to_list()],
    )


def decision_time(root: Root, stage: str) -> datetime:
    if stage == "first_test":
        return root.first_test
    if stage == "first_hold":
        return root.hold
    raise ValueError(f"unknown decision stage: {stage}")


def root_bounds(root: Root, stage: str, tape: Tape) -> tuple[int, int]:
    decision = decision_time(root, stage)
    return (
        bisect.bisect_left(tape.times, timestamp_us(decision)),
        bisect.bisect_left(tape.times, timestamp_us(root.resolution)),
    )


def market_fill(tape: Tape, start: int, end: int, trigger: str) -> Fill | None:
    if start >= end:
        return None
    return Fill(tape.times[start], tape.prices[start], "market", trigger)


def first_market_at_or_after(
    tape: Tape,
    start: int,
    end: int,
    target_us: int,
    trigger: str,
) -> Fill | None:
    index = max(start, bisect.bisect_left(tape.times, target_us, start, end))
    return market_fill(tape, index, end, trigger)


def first_favorable_cross(
    root: Root,
    tape: Tape,
    start: int,
    end: int,
    threshold: float,
    trigger: str,
) -> Fill | None:
    for index in range(start, end):
        if root.direction * (tape.prices[index] - threshold) >= -1e-9:
            return Fill(
                tape.times[index],
                tape.prices[index],
                "market",
                trigger,
            )
    return None


def first_two_sided_acceptance(
    root: Root,
    tape: Tape,
    start: int,
    end: int,
    threshold: float,
    window_s: float,
    min_trades: int,
) -> Fill | None:
    eligible: deque[int] = deque()
    window_us = int(window_s * 1_000_000)
    positive = 0
    negative = 0
    for index in range(start, end):
        if root.direction * (tape.prices[index] - threshold) < -1e-9:
            continue
        eligible.append(index)
        if tape.signs[index] > 0:
            positive += 1
        elif tape.signs[index] < 0:
            negative += 1
        cutoff = tape.times[index] - window_us
        while eligible and tape.times[eligible[0]] < cutoff:
            old = eligible.popleft()
            if tape.signs[old] > 0:
                positive -= 1
            elif tape.signs[old] < 0:
                negative -= 1
        if len(eligible) >= min_trades and positive > 0 and negative > 0:
            return Fill(
                tape.times[index],
                tape.prices[index],
                "market",
                "two_sided_hvn_escape",
            )
    return None


def first_passive_fill(
    root: Root,
    tape: Tape,
    start: int,
    end: int,
    limit: float,
    expiry_us: int | None,
    trigger: str,
) -> Fill | None:
    for index in range(start, end):
        if expiry_us is not None and tape.times[index] > expiry_us:
            break
        adverse_aggressor = (
            tape.signs[index] < 0 if root.direction > 0 else tape.signs[index] > 0
        )
        trades_through = (
            tape.prices[index] <= limit + 1e-9
            if root.direction > 0
            else tape.prices[index] >= limit - 1e-9
        )
        if adverse_aggressor and trades_through:
            return Fill(tape.times[index], limit, "passive_opportunity", trigger)
    return None


def earlier(left: Fill | None, right: Fill | None) -> Fill | None:
    if left is None:
        return right
    if right is None:
        return left
    return left if left.timestamp_us <= right.timestamp_us else right


def hvn_threshold(root: Root, profile: dict[str, Any]) -> float | None:
    if profile.get("terrain_class") != "hvn_unescaped":
        return None
    lo = number(profile.get("hvn_region_low"))
    hi = number(profile.get("hvn_region_high"))
    if lo is None or hi is None:
        return None
    return hi if root.direction > 0 else lo - TICK_SIZE


def vpoc_threshold(root: Root, profile: dict[str, Any]) -> float | None:
    vpoc = number(profile.get("vpoc_price"))
    current_distance = number(profile.get("current_vpoc_signed_distance_pts"))
    if vpoc is None or current_distance is None or current_distance >= 0:
        return None
    return vpoc


def gate_fill(
    root: Root,
    tape: Tape,
    start: int,
    end: int,
    thresholds: list[float],
    trigger: str,
) -> Fill | None:
    if not thresholds:
        return market_fill(tape, start, end, f"{trigger}_already_satisfied")
    target = max(thresholds) if root.direction > 0 else min(thresholds)
    return first_favorable_cross(root, tape, start, end, target, trigger)


def policy_fills(
    root: Root,
    decision: datetime,
    profile: dict[str, Any],
    tape: Tape,
    start: int,
    end: int,
    passive_timeouts: list[int],
    acceptance_window_s: float,
    acceptance_min_trades: int,
) -> dict[str, Fill | None]:
    market = market_fill(tape, start, end, "first_trade_after_hold")
    hvn = hvn_threshold(root, profile)
    vpoc = vpoc_threshold(root, profile)
    root_edge = root.hi if root.direction > 0 else root.lo
    decision_us = timestamp_us(decision)

    fills: dict[str, Fill | None] = {
        "market_now": market,
        "vpoc_gate": gate_fill(
            root, tape, start, end, [vpoc] if vpoc is not None else [], "vpoc_gate"
        ),
        "hvn_escape_touch": gate_fill(
            root, tape, start, end, [hvn] if hvn is not None else [], "hvn_escape"
        ),
        "combined_terrain_gate": gate_fill(
            root,
            tape,
            start,
            end,
            [value for value in (hvn, vpoc) if value is not None],
            "combined_terrain_gate",
        ),
    }
    fills["hvn_escape_two_sided"] = (
        first_two_sided_acceptance(
            root,
            tape,
            start,
            end,
            hvn,
            acceptance_window_s,
            acceptance_min_trades,
        )
        if hvn is not None
        else market
    )

    escape = (
        first_favorable_cross(
            root, tape, start, end, hvn, "terrain_hvn_escape"
        )
        if hvn is not None
        else None
    )
    if hvn is None:
        for seconds in passive_timeouts:
            fills[f"terrain_escape_retest_{seconds}s"] = market
        fills["terrain_escape_retest_until_resolution"] = market
    elif escape is None:
        for seconds in passive_timeouts:
            fills[f"terrain_escape_retest_{seconds}s"] = None
        fills["terrain_escape_retest_until_resolution"] = None
    else:
        escape_start = bisect.bisect_right(tape.times, escape.timestamp_us, start, end)
        for seconds in passive_timeouts:
            fills[f"terrain_escape_retest_{seconds}s"] = first_passive_fill(
                root,
                tape,
                escape_start,
                end,
                hvn,
                escape.timestamp_us + seconds * 1_000_000,
                f"hvn_edge_retest_after_escape_{seconds}s",
            )
        fills["terrain_escape_retest_until_resolution"] = first_passive_fill(
            root,
            tape,
            escape_start,
            end,
            hvn,
            None,
            "hvn_edge_retest_after_escape",
        )

    passive_until_resolution = first_passive_fill(
        root,
        tape,
        start,
        end,
        root_edge,
        None,
        "consumed_band_edge",
    )
    fills["passive_band_until_resolution"] = passive_until_resolution
    for seconds in passive_timeouts:
        expiry = decision_us + seconds * 1_000_000
        passive = first_passive_fill(
            root,
            tape,
            start,
            end,
            root_edge,
            expiry,
            f"consumed_band_edge_{seconds}s",
        )
        fills[f"passive_band_{seconds}s"] = passive
        fallback = (
            passive
            if passive is not None
            else first_market_at_or_after(
                tape,
                start,
                end,
                expiry,
                f"market_after_passive_{seconds}s",
            )
        )
        fills[f"passive_{seconds}s_then_market"] = fallback

    passive_30 = first_passive_fill(
        root,
        tape,
        start,
        end,
        root_edge,
        decision_us + 30 * 1_000_000,
        "terrain_hvn_passive_30s",
    )
    fills["terrain_passive_30s"] = (
        passive_30 if hvn is not None else market
    )
    fills["terrain_passive_or_escape"] = (
        earlier(passive_until_resolution, escape) if hvn is not None else market
    )
    return fills


def path_metrics(
    root: Root,
    decision: datetime,
    tape: Tape,
    fill: Fill | None,
    end: int,
) -> dict[str, Any]:
    if fill is None:
        return {
            "filled": False,
            "entry_et": "",
            "entry_price": None,
            "fill_mode": "",
            "fill_trigger": "",
            "delay_s": None,
            "mfe_pts": None,
            "mae_pts": None,
            "end_move_pts": None,
        }
    start = bisect.bisect_left(tape.times, fill.timestamp_us)
    prices = tape.prices[start:end]
    if not prices:
        prices = [fill.price]
    signed = [root.direction * (price - fill.price) for price in prices]
    entry_et = datetime.fromtimestamp(fill.timestamp_us / 1_000_000, tz=NY)
    return {
        "filled": True,
        "entry_et": entry_et.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
        "entry_price": fill.price,
        "fill_mode": fill.mode,
        "fill_trigger": fill.trigger,
        "delay_s": (fill.timestamp_us - timestamp_us(decision)) / 1_000_000,
        "mfe_pts": max(0.0, max(signed)),
        "mae_pts": max(0.0, -min(signed)),
        "end_move_pts": signed[-1],
    }


def decision_rows(
    roots: dict[tuple[str, str, str], Root],
    profiles: list[dict[str, Any]],
    tapes: dict[str, Tape],
    passive_timeouts: list[int],
    acceptance_window_s: float,
    acceptance_min_trades: int,
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for profile in profiles:
        if not profile["profile_valid"]:
            continue
        root = roots[
            (profile["session_id"], profile["date"], profile["root_id"])
        ]
        stage = str(profile["decision_stage"])
        decision = decision_time(root, stage)
        tape = tapes[root.date]
        start, end = root_bounds(root, stage, tape)
        fills = policy_fills(
            root,
            decision,
            profile,
            tape,
            start,
            end,
            passive_timeouts,
            acceptance_window_s,
            acceptance_min_trades,
        )
        market = fills["market_now"]
        market_price = market.price if market is not None else None
        for policy, fill in fills.items():
            metrics = path_metrics(root, decision, tape, fill, end)
            filled = bool(metrics["filled"])
            advanced = root.outcome == ADVANCED
            entry_price = number(metrics.get("entry_price"))
            cost = (
                root.direction * (entry_price - market_price)
                if entry_price is not None and market_price is not None
                else None
            )
            owned_to_decision_s = (decision - root.owned).total_seconds()
            output.append(
                {
                    "session_id": root.session_id,
                    "date": root.date,
                    "root_id": root.root_id,
                    "side": root.side,
                    "root_lo": root.lo,
                    "root_hi": root.hi,
                    "root_owned_et": root.owned.strftime(
                        "%Y-%m-%d %H:%M:%S.%f"
                    )[:-3],
                    "first_test_et": root.first_test.strftime(
                        "%Y-%m-%d %H:%M:%S.%f"
                    )[:-3],
                    "hold_et": root.hold.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
                    "decision_stage": stage,
                    "decision_et": decision.strftime(
                        "%Y-%m-%d %H:%M:%S.%f"
                    )[:-3],
                    "owned_to_decision_s": owned_to_decision_s,
                    "decision_age_bucket": age_bucket(owned_to_decision_s),
                    "test_to_hold_s": (root.hold - root.first_test).total_seconds(),
                    "resolution_et": root.resolution.strftime(
                        "%Y-%m-%d %H:%M:%S.%f"
                    )[:-3],
                    "held_to_resolution_s": (
                        root.resolution - root.hold
                    ).total_seconds(),
                    "structural_outcome": root.outcome,
                    "advanced": advanced,
                    "successor_id": root.successor_id,
                    "observed_entry_roles": root.observed_roles,
                    "role_context": root.role_context,
                    "scope": profile["scope"],
                    "bin_points": profile["bin_points"],
                    "config": profile["config"],
                    "topology": profile.get("topology", ""),
                    "field_state": profile.get("field_state", ""),
                    "terrain_class": profile["terrain_class"],
                    "current_price": number(profile.get("current_price")),
                    "vpoc_price": number(profile.get("vpoc_price")),
                    "current_vpoc_signed_distance_pts": number(
                        profile.get("current_vpoc_signed_distance_pts")
                    ),
                    "hvn_region_low": number(profile.get("hvn_region_low")),
                    "hvn_region_high": number(profile.get("hvn_region_high")),
                    "current_hvn_escape_margin_pts": number(
                        profile.get("current_hvn_escape_margin_pts")
                    ),
                    "policy": policy,
                    **metrics,
                    "market_reference_price": market_price,
                    "entry_cost_vs_market_pts": cost,
                    "entry_improvement_vs_market_pts": (
                        -cost if cost is not None else None
                    ),
                    "advance_captured": advanced and filled,
                    "advance_missed": advanced and not filled,
                    "failure_exposed": (not advanced) and filled,
                    "failure_avoided": (not advanced) and not filled,
                }
            )
    return output


def median(rows: list[dict[str, Any]], key: str) -> float | None:
    values = [
        value
        for row in rows
        if (value := number(row.get(key))) is not None
    ]
    return statistics.median(values) if values else None


def summarize(rows: list[dict[str, Any]], keys: tuple[str, ...]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[tuple(str(row.get(key, "")) for key in keys)].append(row)
    output: list[dict[str, Any]] = []
    for group_key, group in sorted(groups.items()):
        advanced = sum(bool(row["advanced"]) for row in group)
        failed = len(group) - advanced
        advance_captured = sum(bool(row["advance_captured"]) for row in group)
        failure_exposed = sum(bool(row["failure_exposed"]) for row in group)
        filled = advance_captured + failure_exposed
        output.append(
            {
                **dict(zip(keys, group_key)),
                "roots": len(group),
                "advanced": advanced,
                "failed": failed,
                "filled": filled,
                "fill_rate": filled / len(group) if group else None,
                "filled_success_rate": (
                    advance_captured / filled if filled else None
                ),
                "advance_capture_rate": (
                    advance_captured / advanced if advanced else None
                ),
                "failure_exposure_rate": (
                    failure_exposed / failed if failed else None
                ),
                "selectivity_advantage": (
                    (advance_captured / advanced if advanced else 0.0)
                    - (failure_exposed / failed if failed else 0.0)
                ),
                "advance_captured": advance_captured,
                "advance_missed": advanced - advance_captured,
                "failure_exposed": failure_exposed,
                "failure_avoided": failed - failure_exposed,
                "avoided_minus_missed": (
                    (failed - failure_exposed) - (advanced - advance_captured)
                ),
                "median_delay_s": median(
                    [row for row in group if row["filled"]], "delay_s"
                ),
                "median_entry_improvement_pts": median(
                    [row for row in group if row["filled"]],
                    "entry_improvement_vs_market_pts",
                ),
                "advanced_median_entry_improvement_pts": median(
                    [
                        row
                        for row in group
                        if row["advance_captured"]
                    ],
                    "entry_improvement_vs_market_pts",
                ),
                "advanced_median_mae_pts": median(
                    [row for row in group if row["advance_captured"]],
                    "mae_pts",
                ),
                "failed_median_mae_pts": median(
                    [row for row in group if row["failure_exposed"]],
                    "mae_pts",
                ),
            }
        )
    return output


def selectivity_counts(rows: list[dict[str, Any]]) -> tuple[float | None, int, int]:
    advanced = [row for row in rows if bool(row["advanced"])]
    failed = [row for row in rows if not bool(row["advanced"])]
    if not advanced or not failed:
        return None, len(advanced), len(failed)
    captured = sum(bool(row["advance_captured"]) for row in advanced)
    exposed = sum(bool(row["failure_exposed"]) for row in failed)
    return captured / len(advanced) - exposed / len(failed), len(advanced), len(failed)


def quantile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * q
    low = int(math.floor(position))
    high = int(math.ceil(position))
    if low == high:
        return ordered[low]
    weight = position - low
    return ordered[low] * (1 - weight) + ordered[high] * weight


def cluster_uncertainty(decisions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    specs = (
        ("first_test", "all", "vpoc_gate"),
        ("first_test", "all", "combined_terrain_gate"),
        ("first_test", "hvn_unescaped", "hvn_escape_touch"),
        ("first_test", "hvn_unescaped", "hvn_escape_two_sided"),
        ("first_test", "hvn_unescaped", "vpoc_gate"),
        ("first_test", "hvn_unescaped", "passive_band_30s"),
        ("first_test", "transition", "vpoc_gate"),
        ("first_test", "lvn", "vpoc_gate"),
        ("first_test", "hvn_escaped", "vpoc_gate"),
        ("first_hold", "hvn_unescaped", "hvn_escape_touch"),
        ("first_hold", "hvn_unescaped", "hvn_escape_two_sided"),
    )
    primary_rows = primary(decisions)
    output: list[dict[str, Any]] = []
    rng = random.Random(20260726)
    for stage, terrain, policy in specs:
        rows = [
            row
            for row in primary_rows
            if row["decision_stage"] == stage
            and row["policy"] == policy
            and (terrain == "all" or row["terrain_class"] == terrain)
        ]
        estimate, advanced, failed = selectivity_counts(rows)
        dates = sorted({str(row["date"]) for row in rows})
        by_date = {
            day: [row for row in rows if row["date"] == day]
            for day in dates
        }
        day_values = [
            value
            for day in dates
            if (value := selectivity_counts(by_date[day])[0]) is not None
        ]
        boot: list[float] = []
        if len(dates) >= 2:
            for _ in range(10_000):
                sample: list[dict[str, Any]] = []
                for _ in dates:
                    sample.extend(by_date[rng.choice(dates)])
                value = selectivity_counts(sample)[0]
                if value is not None:
                    boot.append(value)
        leave_one_out = [
            value
            for omitted in dates
            if (
                value := selectivity_counts(
                    [
                        row
                        for day in dates
                        if day != omitted
                        for row in by_date[day]
                    ]
                )[0]
            )
            is not None
        ]
        output.append(
            {
                "decision_stage": stage,
                "terrain_class": terrain,
                "policy": policy,
                "roots": len(rows),
                "advanced": advanced,
                "failed": failed,
                "selectivity_advantage": estimate,
                "cluster_bootstrap_low_95": quantile(boot, 0.025),
                "cluster_bootstrap_high_95": quantile(boot, 0.975),
                "positive_days": sum(value > 0 for value in day_values),
                "negative_days": sum(value < 0 for value in day_values),
                "zero_days": sum(abs(value) < 1e-12 for value in day_values),
                "eligible_days": len(day_values),
                "leave_one_day_out_min": min(leave_one_out)
                if leave_one_out
                else None,
                "leave_one_day_out_max": max(leave_one_out)
                if leave_one_out
                else None,
            }
        )
    return output


def fmt(value: Any, digits: int = 3) -> str:
    numeric = number(value)
    if numeric is None:
        return ""
    return f"{numeric:.{digits}f}"


def primary(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        row
        for row in rows
        if row["scope"] == PRIMARY_SCOPE
        and abs(float(row["bin_points"]) - PRIMARY_BIN_POINTS) < 1e-9
    ]


def build_report(
    decisions: list[dict[str, Any]],
    policy_summary: list[dict[str, Any]],
    terrain_summary: list[dict[str, Any]],
    daily_summary: list[dict[str, Any]],
    uncertainty: list[dict[str, Any]],
    roots: dict[tuple[str, str, str], Root],
    profiles: list[dict[str, Any]],
    args: argparse.Namespace,
) -> str:
    primary_config = f"{PRIMARY_SCOPE}:{PRIMARY_BIN_POINTS:g}pt"
    focus_policies = (
        "market_now",
        "vpoc_gate",
        "hvn_escape_touch",
        "hvn_escape_two_sided",
        "combined_terrain_gate",
        "terrain_escape_retest_30s",
        "terrain_escape_retest_until_resolution",
        "terrain_passive_30s",
        "terrain_passive_or_escape",
        "passive_band_30s",
        "passive_30s_then_market",
    )
    lines = [
        "# Direct-Conversion Terrain Execution Counterfactual",
        "",
        "Population: synthetic consumed rails that eventually resolved `HELD_FIRST_TEST`. Each decision stage uses only the point-in-time profile frozen at its own timestamp.",
        "",
        "## Primary Population",
        "",
        f"- primary profile: `{PRIMARY_SCOPE}`, `{PRIMARY_BIN_POINTS:g}` points per bin",
    ]
    for stage in ("first_test", "first_hold"):
        valid_primary = {
            (row["session_id"], row["date"], row["root_id"])
            for row in profiles
            if row["profile_valid"]
            and row["decision_stage"] == stage
            and row["scope"] == PRIMARY_SCOPE
            and abs(float(row["bin_points"]) - PRIMARY_BIN_POINTS) < 1e-9
        }
        outcome_counts = Counter(
            roots[key].outcome for key in valid_primary if key in roots
        )
        lines.extend(
            [
                f"- `{stage}` valid roots: {len(valid_primary)}; "
                f"advanced={outcome_counts[ADVANCED]}; "
                f"failed={outcome_counts[FAILED]}",
            ]
        )

    for stage, title in (
        ("first_test", "Conditional At First Test"),
        ("first_hold", "Causal After Hold Confirmation"),
    ):
        main = [
            row
            for row in policy_summary
            if row["decision_stage"] == stage
            and row["config"] == primary_config
        ]
        main_by_policy = {row["policy"]: row for row in main}
        lines.extend(
            [
                "",
                f"## {title}",
                "",
                "| policy | fill rate | advance captured | failures exposed | selectivity | avoided - missed | entry improvement | delay |",
                "|---|---:|---:|---:|---:|---:|---:|---:|",
            ]
        )
        for policy in focus_policies:
            row = main_by_policy.get(policy)
            if row is None:
                continue
            lines.append(
                f"| {policy} | {fmt(row['fill_rate'])} | "
                f"{row['advance_captured']}/{row['advanced']} "
                f"({fmt(row['advance_capture_rate'])}) | "
                f"{row['failure_exposed']}/{row['failed']} "
                f"({fmt(row['failure_exposure_rate'])}) | "
                f"{fmt(row['selectivity_advantage'])} | "
                f"{row['avoided_minus_missed']} | "
                f"{fmt(row['median_entry_improvement_pts'])} | "
                f"{fmt(row['median_delay_s'], 1)}s |"
            )

    terrain_focus = [
        row
        for row in terrain_summary
        if row["decision_stage"] == "first_test"
        and row["config"] == primary_config
        and row["policy"]
        in {
            "market_now",
            "vpoc_gate",
            "hvn_escape_touch",
            "terrain_escape_retest_30s",
            "terrain_passive_30s",
            "passive_band_30s",
        }
    ]
    lines.extend(
        [
            "",
            "## First-Test Terrain Strata",
            "",
            "| terrain | policy | roots | advance rate | advance captured | failure exposed | selectivity | entry improvement |",
            "|---|---|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for row in terrain_focus:
        base_rate = (
            int(row["advanced"]) / int(row["roots"])
            if int(row["roots"])
            else 0.0
        )
        lines.append(
            f"| {row['terrain_class']} | {row['policy']} | {row['roots']} | "
            f"{base_rate:.3f} | {fmt(row['advance_capture_rate'])} | "
            f"{fmt(row['failure_exposure_rate'])} | "
            f"{fmt(row['selectivity_advantage'])} | "
            f"{fmt(row['median_entry_improvement_pts'])} |"
        )

    day_focus = [
        row
        for row in daily_summary
        if row["decision_stage"] == "first_test"
        and row["config"] == primary_config
        and row["policy"]
        in {
            "vpoc_gate",
            "hvn_escape_touch",
            "hvn_escape_two_sided",
            "terrain_escape_retest_30s",
            "terrain_passive_30s",
        }
    ]
    lines.extend(
        [
            "",
            "## First-Test Day Stability",
            "",
            "| date | policy | roots | advance captured | failure exposed | selectivity |",
            "|---|---|---:|---:|---:|---:|",
        ]
    )
    for row in day_focus:
        lines.append(
            f"| {row['date']} | {row['policy']} | {row['roots']} | "
            f"{fmt(row['advance_capture_rate'])} | "
            f"{fmt(row['failure_exposure_rate'])} | "
            f"{fmt(row['selectivity_advantage'])} |"
        )

    lines.extend(
        [
            "",
            "## Clustered Robustness",
            "",
            "The interval resamples whole dates. With seven sessions it is an uncertainty warning, not a validation set.",
            "",
            "| stage | terrain | policy | roots | selectivity | date-bootstrap 95% | day signs | leave-one-day-out |",
            "|---|---|---|---:|---:|---:|---:|---:|",
        ]
    )
    for row in uncertainty:
        lines.append(
            f"| {row['decision_stage']} | {row['terrain_class']} | "
            f"{row['policy']} | {row['roots']} | "
            f"{fmt(row['selectivity_advantage'])} | "
            f"{fmt(row['cluster_bootstrap_low_95'])} to "
            f"{fmt(row['cluster_bootstrap_high_95'])} | "
            f"+{row['positive_days']}/-{row['negative_days']}/"
            f"0={row['zero_days']} | "
            f"{fmt(row['leave_one_day_out_min'])} to "
            f"{fmt(row['leave_one_day_out_max'])} |"
        )

    named = {
        ("2026-07-23", "111"),
        ("2026-07-23", "208"),
        ("2026-07-24", "34"),
        ("2026-07-24", "84"),
        ("2026-07-24", "89"),
        ("2026-07-24", "102"),
    }
    named_rows = [
        row
        for row in primary(decisions)
        if (row["date"], row["root_id"]) in named
        and row["decision_stage"] == "first_test"
        and row["policy"]
        in {
            "market_now",
            "vpoc_gate",
            "hvn_escape_touch",
            "terrain_escape_retest_30s",
            "terrain_passive_30s",
        }
    ]
    lines.extend(
        [
            "",
            "## Named Fixture Audit",
            "",
            "| date/root | owned to test | side | terrain | VPOC distance | outcome | policy | fill | delay | improvement |",
            "|---|---:|---|---|---:|---|---|---|---:|---:|",
        ]
    )
    for row in named_rows:
        lines.append(
            f"| {row['date']}/{row['root_id']} | "
            f"{fmt(row['owned_to_decision_s'], 1)}s | {row['side']} | "
            f"{row['terrain_class']} | "
            f"{fmt(row['current_vpoc_signed_distance_pts'])} | "
            f"{row['structural_outcome']} | {row['policy']} | "
            f"{row['filled']} | {fmt(row['delay_s'], 1)} | "
            f"{fmt(row['entry_improvement_vs_market_pts'])} |"
        )

    lines.extend(
        [
            "",
            "## Policy Definitions",
            "",
            "- `market_now`: first recorded trade at or after the named decision stage.",
            "- `vpoc_gate`: wait only when current price is adverse of the frozen profile VPOC.",
            "- `hvn_escape_touch`: wait only when the consumed band's containing HVN had not been escaped; enter on the first trade outside its favorable edge.",
            f"- `hvn_escape_two_sided`: same gate, but require both aggressor signs and at least {args.acceptance_min_trades} beyond-edge prints in a trailing {args.acceptance_window_s:g}-second window.",
            "- `combined_terrain_gate`: require every currently-unsatisfied VPOC and containing-HVN boundary.",
            "- `terrain_escape_retest_30s`: inside an unescaped HVN, first require favorable-edge escape, then infer a passive opportunity only if opposite aggression retests that profile edge within 30 seconds; otherwise do not chase.",
            "- `terrain_passive_30s`: use a 30-second passive opportunity at the consumed band's favorable edge only inside an unescaped HVN; otherwise enter immediately.",
            "- `terrain_passive_or_escape`: inside an unescaped HVN, take whichever comes first: an opposite-aggressor trade through the consumed-band edge or favorable HVN escape.",
            "- Passive opportunity does not prove a real queue fill. Queue position and slippage are not in MarketRecorder.",
            "",
            "## Interpretation Boundary",
            "",
            "- `first_test` directly answers the conditional execution question, but membership uses the later hold verdict. It is not a causal classifier available at test touch.",
            "- `first_hold` is fully causal, but a late first retest can make it campaign management rather than initial entry.",
            "- Structural success is a favorable successor owned before root failure. Fixed-tick profit targets are not used.",
            "- A policy can improve selectivity by avoiding failures, but that must be weighed against missed advances and confirmation cost.",
            "- This is research output only; no EAR or LevelLedger runtime behavior changed.",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> None:
    args = parse_args()
    passive_timeouts = sorted(
        {
            int(value.strip())
            for value in args.passive_timeouts.split(",")
            if value.strip()
        }
    )
    roots = load_roots(args.lineage_csv, args.start_date, args.end_date)
    profiles = load_profiles(args.profile_csv, roots)
    if not roots or not profiles:
        raise SystemExit("no resolved first-hold roots or matching profiles")

    by_date: dict[str, list[Root]] = defaultdict(list)
    for root in roots.values():
        by_date[root.date].append(root)
    tapes: dict[str, Tape] = {}
    for day, day_roots in sorted(by_date.items()):
        tapes[day] = load_tape(day_roots, args.symbol_dir)
        print(
            f"{day}: roots={len(day_roots)} ticks={len(tapes[day].times)}",
            flush=True,
        )

    decisions = decision_rows(
        roots,
        profiles,
        tapes,
        passive_timeouts,
        args.acceptance_window_s,
        args.acceptance_min_trades,
    )
    policy_summary = summarize(
        decisions, ("decision_stage", "config", "policy")
    )
    terrain_summary = summarize(
        decisions, ("decision_stage", "config", "terrain_class", "policy")
    )
    role_summary = summarize(
        decisions, ("decision_stage", "config", "role_context", "policy")
    )
    daily_summary = summarize(
        decisions, ("decision_stage", "config", "date", "policy")
    )
    age_summary = summarize(
        decisions,
        (
            "decision_stage",
            "config",
            "decision_age_bucket",
            "terrain_class",
            "policy",
        ),
    )
    uncertainty = cluster_uncertainty(decisions)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    write_csv(args.out_dir / "policy_decisions.csv", decisions)
    write_csv(args.out_dir / "policy_summary.csv", policy_summary)
    write_csv(args.out_dir / "terrain_policy_summary.csv", terrain_summary)
    write_csv(args.out_dir / "role_policy_summary.csv", role_summary)
    write_csv(args.out_dir / "daily_policy_summary.csv", daily_summary)
    write_csv(args.out_dir / "age_policy_summary.csv", age_summary)
    write_csv(args.out_dir / "cluster_uncertainty.csv", uncertainty)
    report = build_report(
        decisions,
        policy_summary,
        terrain_summary,
        daily_summary,
        uncertainty,
        roots,
        profiles,
        args,
    )
    (args.out_dir / "findings.md").write_text(report, encoding="utf-8")
    print(report, end="")
    print(f"\nwrote {args.out_dir} decisions={len(decisions)}")


if __name__ == "__main__":
    main()
