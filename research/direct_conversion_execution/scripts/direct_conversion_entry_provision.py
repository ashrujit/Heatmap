"""Measure direct-conversion provision at the EAR entry decision.

This is the decision-aligned companion to ``conversion_provision_probe.py``.
The population is accepted and filled EAR orders whose resolution was
``DirectConversion``.  Each order is joined to the consumed rail it referenced,
then raw MarketRecorder book events are replayed in two causal windows:

1. attack: first engagement with the losing side through the conversion break;
2. decision: conversion break through the order-submit timestamp.

The second window ends at the decision.  It therefore measures whether the
losing side re-provisioned the band before EAR committed, without using
time-to-retest or leaking quote events after the order.

Outcomes are deliberately dual:

* realized fill-to-next-opposite-fill P&L, which includes EAR exit policy;
* fixed five-minute path and first +/-10 point touch, which assess entry quality
  independently of sponsor promotion and flatten policy.
"""

from __future__ import annotations

import argparse
import bisect
import csv
import json
import math
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import polars as pl

from _paths import OUTPUT_ROOT

from capture_loader import load_capture_window, snapshot_columns, tick_columns  # noqa: E402
from conversion_provision_probe import (  # noqa: E402
    ASK,
    BID,
    NY,
    UTC,
    Conversion,
    Window,
    classify_provision,
    nearest_snapshot,
    provision_scale,
    resolve_attack_window,
    safe_div,
    snapshot_band_size,
    stream_day,
)

DEFAULT_EVENTS = Path.home() / "Documents" / "ExecAssistantRuntime" / "events.jsonl"
ENTRY_REASONS = {"direct_conversion", "direct_conversion_retest"}
TICK_SIZE = 0.25
PATH_HORIZON_S = 300
PATH_TOUCH_PTS = 10.0
TRAILING_MS = (500, 1_000, 2_000, 5_000)
TRAILING_ZONE_TICKS = 8


def parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def et_date(ts: datetime) -> str:
    return ts.astimezone(NY).date().isoformat()


def et_text(ts: datetime) -> str:
    return ts.astimezone(NY).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]


def fnum(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def weighted_fill(events: list[dict[str, Any]]) -> tuple[datetime | None, float | None, float]:
    total_qty = 0.0
    total_value = 0.0
    first_ts: datetime | None = None
    for event in events:
        price = fnum(event.get("price")) or fnum(event.get("average_fill_price"))
        qty = fnum(event.get("quantity")) or fnum(event.get("filled_quantity")) or 0.0
        if price is None or qty <= 0:
            continue
        ts = parse_ts(str(event["ts_utc"]))
        first_ts = ts if first_ts is None else min(first_ts, ts)
        total_qty += qty
        total_value += price * qty
    if total_qty <= 0:
        return first_ts, None, 0.0
    return first_ts, total_value / total_qty, total_qty


@dataclass
class RailOwned:
    ts: datetime
    side: str
    source: str
    lo_tick: int
    hi_tick: int


@dataclass
class Entry:
    conversion: Conversion
    decision_utc: datetime
    intent_id: str
    directive_id: str
    role: str
    reason: str
    order_id: str
    quantity: float
    fill_utc: datetime
    fill_price: float
    fill_qty: float
    rail_match: str
    exit_utc: datetime | None = None
    exit_price: float | None = None
    exit_qty: float = 0.0
    exit_reason: str = ""
    realized_pnl_pts: float | None = None
    path: dict[str, float | str] | None = None


def read_runtime(path: Path, dates: set[str]) -> tuple[
    dict[tuple[str, int], list[RailOwned]],
    list[dict[str, Any]],
    dict[str, dict[str, Any]],
    dict[str, dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    rails: dict[tuple[str, int], list[RailOwned]] = defaultdict(list)
    submits: list[dict[str, Any]] = []
    submit_results: dict[str, dict[str, Any]] = {}
    intent_results: dict[str, dict[str, Any]] = {}
    fills: list[dict[str, Any]] = []
    flattens: list[dict[str, Any]] = []

    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            raw_ts = event.get("ts_utc")
            if not raw_ts:
                continue
            ts = parse_ts(str(raw_ts))
            day = et_date(ts)
            if day not in dates:
                continue

            name = event.get("event")
            if (
                name == "evidence_transition"
                and event.get("kind") == "RailOwned"
                and event.get("band_source") == "Consumed"
            ):
                band_id = event.get("band_id")
                if band_id is None:
                    continue
                owned_ts = parse_ts(str(event.get("event_utc") or raw_ts))
                rails[(day, int(band_id))].append(
                    RailOwned(
                        ts=owned_ts,
                        side=str(event.get("band_side") or ""),
                        source=str(event.get("band_source") or ""),
                        lo_tick=int(event["band_min_tick"]),
                        hi_tick=int(event["band_max_tick"]),
                    )
                )
            elif (
                name == "order_submit"
                and event.get("reason") in ENTRY_REASONS
                and event.get("resolution") == "DirectConversion"
            ):
                event["_ts"] = ts
                submits.append(event)
            elif name == "order_submit_result" and event.get("intent_id"):
                submit_results[str(event["intent_id"])] = event
            elif name == "intent_result" and event.get("intent_id"):
                intent_results[str(event["intent_id"])] = event
            elif name == "trade_fill":
                event["_ts"] = ts
                fills.append(event)
            elif name == "flatten_result" and event.get("accepted") is True:
                event["_ts"] = ts
                flattens.append(event)

    for owned in rails.values():
        owned.sort(key=lambda item: item.ts)
    fills.sort(key=lambda event: event["_ts"])
    flattens.sort(key=lambda event: event["_ts"])
    submits.sort(key=lambda event: event["_ts"])
    return rails, submits, submit_results, intent_results, fills, flattens


def latest_rail(
    rails: dict[tuple[str, int], list[RailOwned]],
    day: str,
    band_id: int,
    decision: datetime,
) -> RailOwned | None:
    candidates = [rail for rail in rails.get((day, band_id), []) if rail.ts <= decision]
    return candidates[-1] if candidates else None


def exit_for_entry(
    entry_side: str,
    fill_utc: datetime,
    fills: list[dict[str, Any]],
) -> tuple[datetime | None, float | None, float]:
    opposite = "Short" if entry_side == "Long" else "Long"
    first = next(
        (
            event
            for event in fills
            if event["_ts"] > fill_utc and str(event.get("side")) == opposite
        ),
        None,
    )
    if first is None:
        return None, None, 0.0
    order_id = str(first.get("order_id") or "")
    cluster = [
        event
        for event in fills
        if event["_ts"] >= first["_ts"]
        and str(event.get("side")) == opposite
        and (
            (order_id and str(event.get("order_id") or "") == order_id)
            or (not order_id and (event["_ts"] - first["_ts"]).total_seconds() <= 2.0)
        )
    ]
    return weighted_fill(cluster)


def flatten_reason(
    directive_id: str,
    fill_utc: datetime,
    exit_utc: datetime | None,
    flattens: list[dict[str, Any]],
) -> str:
    if exit_utc is None:
        return ""
    candidates = [
        event
        for event in flattens
        if event.get("directive_id") == directive_id
        and fill_utc <= event["_ts"] <= exit_utc + timedelta(seconds=5)
    ]
    return str(candidates[0].get("reason") or "") if candidates else "target_or_other_exit"


def load_entries(events_path: Path, dates: set[str]) -> tuple[list[Entry], dict[str, int]]:
    rails, submits, submit_results, intent_results, fills, flattens = read_runtime(events_path, dates)
    fills_by_order: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for fill in fills:
        order_id = str(fill.get("order_id") or "")
        if order_id:
            fills_by_order[order_id].append(fill)

    entries: list[Entry] = []
    stats = defaultdict(int)
    for submit in submits:
        stats["submitted"] += 1
        intent_id = str(submit.get("intent_id") or "")
        submit_result = submit_results.get(intent_id, {})
        intent_result = intent_results.get(intent_id, {})
        accepted = submit_result.get("accepted") is True or intent_result.get("accepted") is True
        if not accepted:
            stats["not_accepted"] += 1
            continue
        order_id = str(submit_result.get("order_id") or intent_result.get("order_id") or "")
        if not order_id:
            stats["missing_order_id"] += 1
            continue

        side = str(submit.get("side") or "")
        order_fills = [
            fill
            for fill in fills_by_order.get(order_id, [])
            if str(fill.get("side") or "") == side
            and 0 <= (fill["_ts"] - submit["_ts"]).total_seconds() <= 10
        ]
        fill_utc, fill_price, fill_qty = weighted_fill(order_fills)
        if fill_utc is None or fill_price is None or fill_qty <= 0:
            stats["unfilled"] += 1
            continue

        day = et_date(submit["_ts"])
        root_id = int(submit.get("root_object_id") or 0)
        owned = latest_rail(rails, day, root_id, submit["_ts"])
        rail_match = "owned"
        if owned is None:
            formed = submit.get("root_formed_utc")
            owned_ts = parse_ts(str(formed)) if formed else submit["_ts"]
            rail_side = "Demand" if side == "Long" else "Supply"
            lo_tick = int(submit.get("root_min_tick") or round(float(submit["root_min_price"]) / TICK_SIZE))
            hi_tick = int(submit.get("root_max_tick") or round(float(submit["root_max_price"]) / TICK_SIZE))
            owned = RailOwned(owned_ts, rail_side, "Consumed", lo_tick, hi_tick)
            rail_match = "formed_fallback"
            stats["rail_fallback"] += 1

        lo_price = float(submit.get("root_min_price") or owned.lo_tick * TICK_SIZE)
        hi_price = float(submit.get("root_max_price") or owned.hi_tick * TICK_SIZE)
        winner_is_demand = side == "Long"
        loser_side = ASK if winner_is_demand else BID
        conversion = Conversion(
            idx=len(entries),
            date=day,
            ts_utc=owned.ts,
            ts_et=et_text(owned.ts),
            band_id=str(root_id),
            side="demand" if winner_is_demand else "supply",
            consumed_side="supply" if winner_is_demand else "demand",
            lo_price=lo_price,
            hi_price=hi_price,
            lo_tick=int(round(lo_price / TICK_SIZE)),
            hi_tick=int(round(hi_price / TICK_SIZE)),
            loser_side=loser_side,
            winner_side=-loser_side,
            width_pts=hi_price - lo_price,
            max_abs_z=0.0,
            score=0.0,
            same_band_outcome="",
            life_sec="",
            raw=submit,
        )
        exit_utc, exit_price, exit_qty = exit_for_entry(side, fill_utc, fills)
        pnl = None
        if exit_price is not None:
            pnl = exit_price - fill_price if side == "Long" else fill_price - exit_price
        entry = Entry(
            conversion=conversion,
            decision_utc=submit["_ts"],
            intent_id=intent_id,
            directive_id=str(submit.get("directive_id") or ""),
            role=str(submit.get("role") or ""),
            reason=str(submit.get("reason") or ""),
            order_id=order_id,
            quantity=float(submit.get("quantity") or 0.0),
            fill_utc=fill_utc,
            fill_price=fill_price,
            fill_qty=fill_qty,
            rail_match=rail_match,
            exit_utc=exit_utc,
            exit_price=exit_price,
            exit_qty=exit_qty,
            realized_pnl_pts=pnl,
        )
        entry.exit_reason = flatten_reason(
            entry.directive_id, fill_utc, exit_utc, flattens
        )
        entries.append(entry)
        stats["filled"] += 1
        if exit_price is not None:
            stats["with_exit"] += 1
    return entries, dict(stats)


def scan_tape(
    conv: Conversion,
    times: list[int],
    prices: list[float],
    sizes: list[float],
    signs: list[int],
    start_us: int,
    end_us: int,
) -> tuple[float, float]:
    lo_price = conv.lo_tick * TICK_SIZE
    hi_price = conv.hi_tick * TICK_SIZE
    hitting = -1 if conv.loser_side == BID else 1
    start_idx = bisect.bisect_left(times, start_us)
    end_idx = bisect.bisect_right(times, end_us)
    eaten = 0.0
    total = 0.0
    for idx in range(start_idx, end_idx):
        price = prices[idx]
        if not (lo_price - 1e-9 <= price <= hi_price + 1e-9):
            continue
        total += sizes[idx]
        if signs[idx] == hitting:
            eaten += sizes[idx]
    return eaten, total


def signed_distance(side: str, origin: float, price: float) -> float:
    return price - origin if side == "Long" else origin - price


def path_metrics(
    entry: Entry,
    times: list[int],
    prices: list[float],
) -> dict[str, float | str]:
    start_us = int(entry.fill_utc.timestamp() * 1_000_000)
    end_us = start_us + PATH_HORIZON_S * 1_000_000
    lo = bisect.bisect_left(times, start_us)
    hi = bisect.bisect_right(times, end_us)
    favorable = 0.0
    adverse = 0.0
    first_touch = "neither"
    touch_s: float | str = ""
    last_price = entry.fill_price
    for idx in range(lo, hi):
        move = signed_distance(
            str(entry.conversion.raw.get("side") or ""),
            entry.fill_price,
            prices[idx],
        )
        favorable = max(favorable, move)
        adverse = max(adverse, -move)
        last_price = prices[idx]
        if first_touch == "neither":
            if move >= PATH_TOUCH_PTS:
                first_touch = "favorable_10"
                touch_s = round((times[idx] - start_us) / 1_000_000, 3)
            elif move <= -PATH_TOUCH_PTS:
                first_touch = "adverse_10"
                touch_s = round((times[idx] - start_us) / 1_000_000, 3)
    return {
        "mfe_5m": round(favorable, 2),
        "mae_5m": round(adverse, 2),
        "net_5m": round(
            signed_distance(
                str(entry.conversion.raw.get("side") or ""),
                entry.fill_price,
                last_price,
            ),
            2,
        ),
        "first_10pt_touch": first_touch,
        "first_10pt_touch_s": touch_s,
    }


def fmt(value: Any, digits: int = 3) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        if not math.isfinite(value):
            return ""
        return str(round(value, digits))
    return str(value)


FIELDS = [
    "date",
    "decision_et",
    "rail_owned_et",
    "rail_age_at_decision_s",
    "intent_id",
    "directive_id",
    "role",
    "reason",
    "side",
    "band_id",
    "price_lo",
    "price_hi",
    "width_pts",
    "rail_match",
    "entry_distance_from_band_pts",
    "fill_et",
    "fill_price",
    "fill_qty",
    "exit_et",
    "exit_price",
    "exit_qty",
    "exit_reason",
    "realized_pnl_pts",
    "touch_et",
    "break_et",
    "attack_span_s",
    "attack_delta_events",
    "seed_loser_size",
    "end_loser_size",
    "eaten",
    "material_magnitude",
    "attack_replenishment",
    "attack_repl_ratio",
    "attack_provision_class",
    "decision_span_s",
    "decision_delta_events",
    "decision_loser_seed",
    "decision_loser_end",
    "decision_loser_added",
    "decision_loser_removed",
    "decision_eaten",
    "decision_reprovision",
    "decision_reprovision_ratio",
    "decision_gross_return_ratio",
    "decision_owner_seed",
    "decision_owner_end",
    "decision_owner_added",
    "decision_owner_removed",
    "decision_owner_depth_delta",
    "recon_err",
    "mfe_5m",
    "mae_5m",
    "net_5m",
    "first_10pt_touch",
    "first_10pt_touch_s",
]
for trailing_ms in TRAILING_MS:
    prefix = f"trailing_{trailing_ms}ms"
    FIELDS.extend(
        [
            f"{prefix}_opened",
            f"{prefix}_span_s",
            f"{prefix}_delta_events",
            f"{prefix}_owner_seed",
            f"{prefix}_owner_end",
            f"{prefix}_owner_added",
            f"{prefix}_owner_removed",
            f"{prefix}_owner_net_provision",
            f"{prefix}_opposite_seed",
            f"{prefix}_opposite_end",
            f"{prefix}_opposite_added",
            f"{prefix}_opposite_removed",
            f"{prefix}_opposite_net_provision",
        ]
    )


def row_for(entry: Entry) -> dict[str, str]:
    conv = entry.conversion
    attack = conv.windows.get("attack")
    decision = conv.windows.get("decision")
    seed = attack.seed_loser_size if attack else math.nan
    attack_net = attack.cum_loser if attack else math.nan
    attack_repl = attack_net + conv.eaten if attack else math.nan
    material = max(seed, conv.eaten) if attack and not math.isnan(seed) else math.nan
    attack_pull = max(0.0, -attack_repl) if not math.isnan(attack_repl) else math.nan
    absorb = (
        safe_div(conv.eaten, conv.eaten + attack_pull)
        if not math.isnan(attack_pull) and conv.eaten + attack_pull > 0
        else math.nan
    )
    decision_net = decision.cum_loser if decision else math.nan
    decision_reprovision = (
        decision_net + conv.post_eaten if decision and not math.isnan(decision_net) else math.nan
    )
    gross_return = decision.added_loser if decision else math.nan
    owner_delta = (
        decision.end_winner_size - decision.seed_winner_size
        if decision
        and not math.isnan(decision.end_winner_size)
        and not math.isnan(decision.seed_winner_size)
        else math.nan
    )
    side = str(conv.raw.get("side") or "")
    band_edge = conv.hi_price if side == "Long" else conv.lo_price
    entry_distance = signed_distance(side, band_edge, entry.fill_price)
    path = entry.path or {}
    result = {
        "date": conv.date,
        "decision_et": et_text(entry.decision_utc),
        "rail_owned_et": et_text(conv.ts_utc),
        "rail_age_at_decision_s": fmt((entry.decision_utc - conv.ts_utc).total_seconds()),
        "intent_id": entry.intent_id,
        "directive_id": entry.directive_id,
        "role": entry.role,
        "reason": entry.reason,
        "side": side,
        "band_id": conv.band_id,
        "price_lo": fmt(conv.lo_price, 2),
        "price_hi": fmt(conv.hi_price, 2),
        "width_pts": fmt(conv.width_pts, 2),
        "rail_match": entry.rail_match,
        "entry_distance_from_band_pts": fmt(entry_distance, 2),
        "fill_et": et_text(entry.fill_utc),
        "fill_price": fmt(entry.fill_price, 2),
        "fill_qty": fmt(entry.fill_qty, 1),
        "exit_et": et_text(entry.exit_utc) if entry.exit_utc else "",
        "exit_price": fmt(entry.exit_price, 2),
        "exit_qty": fmt(entry.exit_qty, 1),
        "exit_reason": entry.exit_reason,
        "realized_pnl_pts": fmt(entry.realized_pnl_pts, 2),
        "touch_et": datetime.fromtimestamp(conv.touch_us / 1e6, UTC).astimezone(NY).strftime("%H:%M:%S.%f")[:-3],
        "break_et": datetime.fromtimestamp(conv.break_us / 1e6, UTC).astimezone(NY).strftime("%H:%M:%S.%f")[:-3],
        "attack_span_s": fmt((conv.break_us - conv.touch_us) / 1e6, 2),
        "attack_delta_events": fmt(attack.delta_events if attack else 0, 0),
        "seed_loser_size": fmt(seed, 1),
        "end_loser_size": fmt(attack.end_loser_size if attack else None, 1),
        "eaten": fmt(conv.eaten, 1),
        "material_magnitude": fmt(material, 1),
        "attack_replenishment": fmt(attack_repl, 1),
        "attack_repl_ratio": fmt(
            safe_div(attack_repl, provision_scale(seed, conv.eaten))
            if attack
            else math.nan
        ),
        "attack_provision_class": (
            classify_provision(attack_repl, seed, conv.eaten, absorb)
            if attack
            else "unknown"
        ),
        "decision_span_s": fmt(
            (int(entry.decision_utc.timestamp() * 1_000_000) - conv.break_us) / 1e6,
            2,
        ),
        "decision_delta_events": fmt(decision.delta_events if decision else 0, 0),
        "decision_loser_seed": fmt(decision.seed_loser_size if decision else None, 1),
        "decision_loser_end": fmt(decision.end_loser_size if decision else None, 1),
        "decision_loser_added": fmt(decision.added_loser if decision else None, 1),
        "decision_loser_removed": fmt(decision.removed_loser if decision else None, 1),
        "decision_eaten": fmt(conv.post_eaten, 1),
        "decision_reprovision": fmt(decision_reprovision, 1),
        "decision_reprovision_ratio": fmt(safe_div(decision_reprovision, material)),
        "decision_gross_return_ratio": fmt(safe_div(gross_return, material)),
        "decision_owner_seed": fmt(decision.seed_winner_size if decision else None, 1),
        "decision_owner_end": fmt(decision.end_winner_size if decision else None, 1),
        "decision_owner_added": fmt(decision.added_winner if decision else None, 1),
        "decision_owner_removed": fmt(decision.removed_winner if decision else None, 1),
        "decision_owner_depth_delta": fmt(owner_delta, 1),
        "recon_err": fmt(conv.recon_err, 1),
        "mfe_5m": fmt(path.get("mfe_5m"), 2),
        "mae_5m": fmt(path.get("mae_5m"), 2),
        "net_5m": fmt(path.get("net_5m"), 2),
        "first_10pt_touch": fmt(path.get("first_10pt_touch")),
        "first_10pt_touch_s": fmt(path.get("first_10pt_touch_s")),
    }
    for trailing_ms in TRAILING_MS:
        prefix = f"trailing_{trailing_ms}ms"
        window = conv.windows.get(prefix)
        owner_net = (
            window.end_winner_size - window.seed_winner_size
            if window
            and not math.isnan(window.end_winner_size)
            and not math.isnan(window.seed_winner_size)
            else math.nan
        )
        opposite_net = (
            window.end_loser_size - window.seed_loser_size
            if window
            and not math.isnan(window.end_loser_size)
            and not math.isnan(window.seed_loser_size)
            else math.nan
        )
        result.update(
            {
                f"{prefix}_opened": fmt(window.opened if window else False),
                f"{prefix}_span_s": fmt(
                    (window.end_us - window.start_us) / 1_000_000
                    if window
                    else None
                ),
                f"{prefix}_delta_events": fmt(
                    window.delta_events if window else None, 0
                ),
                f"{prefix}_owner_seed": fmt(
                    window.seed_winner_size if window else None, 1
                ),
                f"{prefix}_owner_end": fmt(
                    window.end_winner_size if window else None, 1
                ),
                f"{prefix}_owner_added": fmt(
                    window.added_winner if window else None, 1
                ),
                f"{prefix}_owner_removed": fmt(
                    window.removed_winner if window else None, 1
                ),
                f"{prefix}_owner_net_provision": fmt(owner_net, 1),
                f"{prefix}_opposite_seed": fmt(
                    window.seed_loser_size if window else None, 1
                ),
                f"{prefix}_opposite_end": fmt(
                    window.end_loser_size if window else None, 1
                ),
                f"{prefix}_opposite_added": fmt(
                    window.added_loser if window else None, 1
                ),
                f"{prefix}_opposite_removed": fmt(
                    window.removed_loser if window else None, 1
                ),
                f"{prefix}_opposite_net_provision": fmt(opposite_net, 1),
            }
        )
    return result


def median(values: list[float]) -> float | None:
    vals = sorted(values)
    if not vals:
        return None
    mid = len(vals) // 2
    return vals[mid] if len(vals) % 2 else (vals[mid - 1] + vals[mid]) / 2


def cell_summary(rows: list[dict[str, str]]) -> str:
    pnls = [float(row["realized_pnl_pts"]) for row in rows if row["realized_pnl_pts"]]
    first_good = sum(row["first_10pt_touch"] == "favorable_10" for row in rows)
    first_bad = sum(row["first_10pt_touch"] == "adverse_10" for row in rows)
    resolved = first_good + first_bad
    med_pnl = median(pnls)
    win_rate = sum(value > 0 for value in pnls) / len(pnls) if pnls else math.nan
    path_rate = first_good / resolved if resolved else math.nan
    return (
        f"n={len(rows)}, directives={len({row['directive_id'] for row in rows})}, "
        f"pnl_win={fmt(win_rate)}, med_pnl={fmt(med_pnl, 2)}, "
        f"first10_good={fmt(path_rate)} ({resolved} resolved)"
    )


def summarize(rows: list[dict[str, str]], parse_stats: dict[str, int], health: list[str]) -> str:
    lines = [
        "# Direct-Conversion Entry Provision",
        "",
        "All book features end at the order-submit decision. Time-to-retest and approach velocity are not predictors.",
        "",
        "## Population",
        "",
        "- " + ", ".join(f"{key}={value}" for key, value in sorted(parse_stats.items())),
        f"- output rows={len(rows)}, directives={len({row['directive_id'] for row in rows})}",
        "",
        "## Replay health",
        "",
        *health,
        "",
        "## Prespecified provision split",
        "",
        "Material means `max(seed displayed loser size, tape eaten) >= 25`. "
        "Returned means observed losing-side adds back into the band from conversion break through decision are at least 25% of material magnitude. "
        "Gross adds are used because mechanically crossed levels end empty even after meaningful re-entry.",
        "",
    ]
    material_cut = 25.0
    return_cut = 0.25
    cells: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        magnitude = fnum(row.get("material_magnitude"))
        return_ratio = fnum(row.get("decision_gross_return_ratio"))
        if magnitude is None or return_ratio is None:
            continue
        mag_label = "material" if magnitude >= material_cut else "thin"
        return_label = "returns" if return_ratio >= return_cut else "gone"
        cells[(mag_label, return_label)].append(row)
    for mag_label in ("material", "thin"):
        for return_label in ("gone", "returns"):
            lines.append(
                f"- {mag_label} + {return_label}: "
                f"{cell_summary(cells.get((mag_label, return_label), []))}"
            )

    lines.extend(
        [
            "",
            "## Depletion, re-entry, and campaign role",
            "",
            "`drained` combines `drained_eaten` and `drained_pulled`; "
            "`still_provisioning` combines `replaced` and `defending`. "
            "This split is reported separately for base entries and adds because late campaign adds face a different location/maturity problem.",
            "",
        ]
    )
    stage_cells: dict[tuple[str, str, str], list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        provision = row.get("attack_provision_class", "")
        stage = "drained" if provision.startswith("drained_") else "still_provisioning"
        return_ratio = fnum(row.get("decision_gross_return_ratio"))
        return_label = (
            "unknown"
            if return_ratio is None
            else ("returns" if return_ratio >= return_cut else "gone")
        )
        role = "add" if row.get("role") == "Add" else "base"
        stage_cells[(role, stage, return_label)].append(row)
    for role in ("base", "add"):
        for stage in ("drained", "still_provisioning"):
            for return_label in ("gone", "returns"):
                lines.append(
                    f"- {role} + {stage} + {return_label}: "
                    f"{cell_summary(stage_cells.get((role, stage, return_label), []))}"
                )

    lines.extend(
        [
            "",
            "## Sensitivity",
            "",
            "| magnitude cut | return cut | material gone pnl win | material returns pnl win | material gone first10 | material returns first10 |",
            "|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for mag_cut in (10.0, 20.0, 25.0, 30.0, 40.0):
        for repl_cut in (0.10, 0.25, 0.50, 0.75):
            selected: dict[str, list[dict[str, str]]] = {"gone": [], "returns": []}
            for row in rows:
                magnitude = fnum(row.get("material_magnitude"))
                return_ratio = fnum(row.get("decision_gross_return_ratio"))
                if magnitude is None or return_ratio is None or magnitude < mag_cut:
                    continue
                selected["returns" if return_ratio >= repl_cut else "gone"].append(row)

            def rates(items: list[dict[str, str]]) -> tuple[str, str]:
                pnls = [float(row["realized_pnl_pts"]) for row in items if row["realized_pnl_pts"]]
                pnl_rate = sum(value > 0 for value in pnls) / len(pnls) if pnls else math.nan
                good = sum(row["first_10pt_touch"] == "favorable_10" for row in items)
                bad = sum(row["first_10pt_touch"] == "adverse_10" for row in items)
                path_rate = good / (good + bad) if good + bad else math.nan
                return f"{fmt(pnl_rate)} (n={len(pnls)})", f"{fmt(path_rate)} (n={good + bad})"

            gone_pnl, gone_path = rates(selected["gone"])
            return_pnl, return_path = rates(selected["returns"])
            lines.append(
                f"| {fmt(mag_cut, 0)} | {fmt(repl_cut, 2)} | {gone_pnl} | "
                f"{return_pnl} | {gone_path} | {return_path} |"
            )

    lines.extend(
        [
            "",
            "## Read",
            "",
            "- Realized P&L is entry-fill to the next opposite-side fill. Multiple adds in one directive share campaign-exit policy and are not independent observations.",
            "- The fixed five-minute first-touch label is included to separate conversion-entry quality from later sponsor promotion and flatten behavior.",
            "- Net same-band re-provision is not used as a split: the reconstructed book correctly evicts crossed levels, so the band commonly ends empty. Gross observed loser adds measure whether the old side actually re-entered during the lifecycle.",
            "- Magnitude and re-provision ratios are continuous in the CSV. The table cuts are a fixture-derived audit, not implementation thresholds.",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--events", type=Path, default=DEFAULT_EVENTS)
    parser.add_argument(
        "--dates",
        default="2026-07-16,2026-07-17,2026-07-20,2026-07-21,2026-07-22,2026-07-23,2026-07-24",
    )
    parser.add_argument("--symbol-dir", default="NQU6")
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=OUTPUT_ROOT / "direct_conversion_entry_provision",
    )
    args = parser.parse_args()

    dates = {value.strip() for value in args.dates.split(",") if value.strip()}
    entries, parse_stats = load_entries(args.events, dates)
    if not entries:
        raise SystemExit("no accepted filled direct-conversion entries matched")

    health: list[str] = []
    for day in sorted(dates):
        day_entries = [entry for entry in entries if entry.conversion.date == day]
        if not day_entries:
            continue
        day_start = datetime.fromisoformat(day).replace(tzinfo=NY)
        day_end = day_start + timedelta(days=1)
        ticks = load_capture_window("ticks", args.symbol_dir, day_start, day_end, tick_columns())
        times = [int(value) for value in ticks["timestamp_us"].to_list()]
        prices = [float(value) for value in ticks["price"].to_list()]
        sizes = [float(value) for value in ticks["size"].to_list()]
        signs = [int(value) for value in ticks["aggressor_sign"].to_list()]
        snapshots = load_capture_window(
            "snapshots", args.symbol_dir, day_start, day_end, snapshot_columns()
        )
        snapshot_rows = snapshots.to_dicts()
        snapshot_times = [int(row["timestamp_us"]) for row in snapshot_rows]

        windows: list[Window] = []
        for entry in day_entries:
            conv = entry.conversion
            resolve_attack_window(conv, times, prices)
            conv.eaten, conv.tape_total = scan_tape(
                conv, times, prices, sizes, signs, conv.touch_us, conv.break_us
            )
            decision_us = int(entry.decision_utc.timestamp() * 1_000_000)
            decision_end = max(conv.break_us + 1, decision_us)
            conv.post_eaten, conv.post_tape_total = scan_tape(
                conv, times, prices, sizes, signs, conv.break_us, decision_end
            )
            attack = Window(
                event_idx=conv.idx,
                phase="attack",
                start_us=conv.touch_us,
                end_us=conv.break_us,
                lo_tick=conv.lo_tick,
                hi_tick=conv.hi_tick,
                loser_side=conv.loser_side,
                winner_side=conv.winner_side,
            )
            decision = Window(
                event_idx=conv.idx,
                phase="decision",
                start_us=conv.break_us,
                end_us=decision_end,
                lo_tick=conv.lo_tick,
                hi_tick=conv.hi_tick,
                loser_side=conv.loser_side,
                winner_side=conv.winner_side,
            )
            conv.windows["attack"] = attack
            conv.windows["decision"] = decision
            windows.extend((attack, decision))
            decision_i = bisect.bisect_right(times, decision_us) - 1
            if decision_i >= 0:
                decision_tick = int(round(prices[decision_i] / TICK_SIZE))
                direction = 1 if str(conv.raw.get("side")) == "Long" else -1
                behind_tick = (
                    decision_tick - direction * TRAILING_ZONE_TICKS
                )
                for trailing_ms in TRAILING_MS:
                    prefix = f"trailing_{trailing_ms}ms"
                    trailing = Window(
                        event_idx=conv.idx,
                        phase=prefix,
                        start_us=decision_us - trailing_ms * 1_000,
                        end_us=decision_us,
                        lo_tick=min(decision_tick, behind_tick),
                        hi_tick=max(decision_tick, behind_tick),
                        loser_side=conv.loser_side,
                        winner_side=conv.winner_side,
                    )
                    conv.windows[prefix] = trailing
                    windows.append(trailing)
            entry.path = path_metrics(entry, times, prices)

        replay_stats = stream_day(args.symbol_dir, day, windows)
        for entry in day_entries:
            conv = entry.conversion
            attack = conv.windows["attack"]
            if math.isnan(attack.seed_loser_size):
                continue
            snapshot = nearest_snapshot(snapshot_times, snapshot_rows, conv.touch_us)
            if snapshot is None:
                continue
            canonical = snapshot_band_size(
                snapshot, conv.lo_tick, conv.hi_tick, conv.loser_side
            )
            conv.recon_err = attack.seed_loser_size - canonical
        message = (
            f"- {day}: entries={len(day_entries)} book_files={replay_stats['files']} "
            f"rows={replay_stats['rows']} deltas={replay_stats['deltas']} "
            f"gaps={replay_stats['gaps']} unopened={replay_stats.get('unopened_windows', 0)}"
        )
        health.append(message)
        print(message, flush=True)

    rows = [row_for(entry) for entry in entries]
    args.out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = args.out_dir / "entry_provision.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    report = summarize(rows, parse_stats, health)
    report_path = args.out_dir / "findings.md"
    report_path.write_text(report, encoding="utf-8")
    print(report)
    print(f"wrote {csv_path}")


if __name__ == "__main__":
    main()
