"""Codex-authored holdroot scale management research.

This script studies where Kahn could add while preserving the original root
risk anchor. It does not propose a live policy change. The intent is to make
the scale-up question reproducible across the ES 2026-08-27/28 case set.
"""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import polars as pl

from mbo_level_features import (
    FILL_BUCKET_US,
    Window,
    attribute_removals,
    load_book,
    load_ticks,
    ny_us,
    signed_depth_deltas,
)


REPO = Path(__file__).resolve().parents[2]
LL_SCRIPT = REPO / "skills" / "dost" / "scripts" / "ll_bands.py"
KAHN_0827_OUT = REPO / "research" / "kahn" / "out" / "2026-08-27-gex-kahn"
REPLENISH_THRESHOLD = 1.012
FEATURE_SEC = 60
OPPOSITE_FAIL_LOOKBACK_SEC = 180
TARGET_PROXIMITY_POINTS = 6.0
MIN_PRESS_RUNWAY_POINTS = 8.0
REDUCE_SIZE_AFTER_PATH_FRACTION = 0.45
SUPPRESS_AFTER_PATH_FRACTION = 0.65


@dataclass(frozen=True)
class Case:
    case_id: str
    day: str
    symbol_dir: str
    side: str
    entry_time: str
    entry_ref: float
    window: str
    focus_lo: float
    focus_hi: float
    target_lo: float
    target_hi: float
    notes: str


CASES: tuple[Case, ...] = (
    Case(
        case_id="es_20260827_1130_long_7728",
        day="2026-08-27",
        symbol_dir="ESU6",
        side="long",
        entry_time="11:40:17",
        entry_ref=7728.0,
        window="11:30-12:45",
        focus_lo=7719.0,
        focus_hi=7736.0,
        target_lo=7743.0,
        target_hi=7743.0,
        notes="Later 7728 long: scale question after root/probe exists.",
    ),
    Case(
        case_id="es_20260827_1330_short_7748",
        day="2026-08-27",
        symbol_dir="ESU6",
        side="short",
        entry_time="13:39:03",
        entry_ref=7748.75,
        window="13:30-14:40",
        focus_lo=7728.0,
        focus_hi=7756.0,
        target_lo=7728.0,
        target_hi=7729.5,
        notes="Actual Kahn short: inspect missed scale while HoldRoot governed.",
    ),
    Case(
        case_id="es_20260828_1120_short_7780",
        day="2026-08-28",
        symbol_dir="ESU6",
        side="short",
        entry_time="11:20:00",
        entry_ref=7780.0,
        window="11:15-12:25",
        focus_lo=7740.0,
        focus_hi=7783.0,
        target_lo=7740.0,
        target_hi=7740.0,
        notes="Hypothetical short: high rail scale-in and target harvest.",
    ),
)


def parse_hms_us(day: str, hms: str) -> int:
    parts = hms.split(":")
    if len(parts) == 2:
        hhmm = hms
        sec = 0
    else:
        hhmm = f"{parts[0]}:{parts[1]}"
        sec = int(parts[2])
    return ny_us(day, hhmm) + sec * 1_000_000


def hms_from_us(us: int | None) -> str:
    if us is None:
        return "-"
    import datetime as dt
    from zoneinfo import ZoneInfo

    return dt.datetime.fromtimestamp(us / 1_000_000, ZoneInfo("America/New_York")).strftime(
        "%H:%M:%S"
    )


def range_intersects(lo: float, hi: float, focus_lo: float, focus_hi: float) -> bool:
    return hi >= focus_lo and lo <= focus_hi


def same_side(case: Case, side: str) -> bool:
    return side == ("demand" if case.side == "long" else "supply")


def opposite_side(case: Case, side: str) -> bool:
    return side == ("supply" if case.side == "long" else "demand")


def book_side_for_owner(side: str) -> int:
    return 1 if side == "demand" else -1


def target_floor(case: Case) -> float:
    return case.target_lo if case.side == "long" else case.target_hi


def runway_points(case: Case, price: float) -> float:
    if case.side == "long":
        return target_floor(case) - price
    return price - target_floor(case)


def path_consumed_fraction(case: Case, price: float) -> float:
    total = abs(case.entry_ref - target_floor(case))
    if total <= 0:
        return 0.0
    progressed = price - case.entry_ref if case.side == "long" else case.entry_ref - price
    return max(0.0, min(1.0, progressed / total))


def mfe_mae(case: Case, ticks: pl.DataFrame, start_us: int, end_us: int, ref: float) -> dict[str, Any]:
    sub = ticks.filter((pl.col("timestamp_us") >= start_us) & (pl.col("timestamp_us") <= end_us))
    if not sub.height:
        return {
            "high": None,
            "low": None,
            "mfe": None,
            "mae": None,
            "target_time": None,
        }
    high = float(sub["price"].max())
    low = float(sub["price"].min())
    if case.side == "long":
        hit = sub.filter(pl.col("price") >= target_floor(case))
        mfe = max(0.0, high - ref)
        mae = max(0.0, ref - low)
    else:
        hit = sub.filter(pl.col("price") <= target_floor(case))
        mfe = max(0.0, ref - low)
        mae = max(0.0, high - ref)
    return {
        "high": high,
        "low": low,
        "mfe": mfe,
        "mae": mae,
        "target_time": int(hit["timestamp_us"][0]) if hit.height else None,
    }


def ll_transitions(case: Case, warmup_min: int = 90) -> list[dict[str, Any]]:
    result = subprocess.run(
        [
            sys.executable,
            str(LL_SCRIPT),
            "--date",
            case.day,
            "--symbol-dir",
            case.symbol_dir,
            "--window",
            case.window,
            "--warmup-min",
            str(warmup_min),
            "--max-transitions",
            "10000",
            "--format",
            "json",
        ],
        capture_output=True,
        text=True,
        cwd=str(REPO),
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr[-1000:] or result.stdout[-1000:])
    return json.loads(result.stdout).get("transitions", [])


def hour_flow_table(symbol_dir: str, day: str, hour: int) -> pl.DataFrame:
    window = Window(symbol_dir, day, f"{hour:02d}:00", f"{hour + 1:02d}:00")
    book = load_book(window)
    ticks = load_ticks(window)
    removals = (
        attribute_removals(book, ticks)
        .with_columns((pl.col("b") * FILL_BUCKET_US).alias("t"))
        .select("t", "price", "side", "fill_size", "pull_size")
    )
    adds = (
        signed_depth_deltas(book)
        .filter(pl.col("size_delta") > 0)
        .select("t", "price", "side", pl.col("size_delta").alias("add_size"))
    )
    return pl.concat(
        [
            removals.with_columns(pl.lit(0.0).alias("add_size")),
            adds.with_columns(
                pl.lit(0.0).alias("fill_size"),
                pl.lit(0.0).alias("pull_size"),
            ).select("t", "price", "side", "fill_size", "pull_size", "add_size"),
        ],
        how="vertical_relaxed",
    )


def band_flow(
    table: pl.DataFrame,
    lo: float,
    hi: float,
    owner_side: str,
    start_us: int,
    end_us: int,
) -> dict[str, float | None]:
    side = book_side_for_owner(owner_side)
    frame = table.filter(
        (pl.col("t") > start_us)
        & (pl.col("t") <= end_us)
        & (pl.col("side") == side)
        & (pl.col("price") >= lo)
        & (pl.col("price") <= hi)
    )
    if not frame.height:
        return {
            "consumed": 0.0,
            "pulled": 0.0,
            "added": 0.0,
            "replenish": None,
            "paid_share": None,
        }
    consumed = float(frame["fill_size"].sum())
    pulled = float(frame["pull_size"].sum())
    added = float(frame["add_size"].sum())
    removed = consumed + pulled
    return {
        "consumed": consumed,
        "pulled": pulled,
        "added": added,
        "replenish": added / removed if removed > 0 else None,
        "paid_share": consumed / removed if removed > 0 else None,
    }


def flow_grade(flow: dict[str, float | None]) -> str:
    replenish = flow.get("replenish")
    if replenish is None:
        return "no-flow"
    if replenish >= REPLENISH_THRESHOLD:
        return "replenished"
    return "depleted"


def transition_time_us(case: Case, transition: dict[str, Any]) -> int:
    return parse_hms_us(case.day, transition["time"])


def transition_price(transition: dict[str, Any]) -> float:
    current = transition.get("current_price")
    if current is not None:
        return float(current)
    return (float(transition["min_price"]) + float(transition["max_price"])) / 2.0


def load_case_ticks(case: Case) -> pl.DataFrame:
    start, end = case.window.split("-", 1)
    return load_ticks(Window(case.symbol_dir, case.day, start, end), banded=False)


def case_summary(case: Case, ticks: pl.DataFrame) -> dict[str, Any]:
    start, end = case.window.split("-", 1)
    path = mfe_mae(case, ticks, parse_hms_us(case.day, case.entry_time), ny_us(case.day, end), case.entry_ref)
    return {
        "case_id": case.case_id,
        "day": case.day,
        "side": case.side,
        "entry_time": case.entry_time,
        "entry_ref": case.entry_ref,
        "target_floor": target_floor(case),
        "window": case.window,
        "high": path["high"],
        "low": path["low"],
        "mfe": path["mfe"],
        "mae": path["mae"],
        "target_time": hms_from_us(path["target_time"]),
        "notes": case.notes,
    }


def recent_opposing_failure(
    case: Case,
    transitions: list[dict[str, Any]],
    now_us: int,
) -> tuple[int, float, str]:
    rows = []
    for tr in transitions:
        tr_us = transition_time_us(case, tr)
        if tr_us >= now_us:
            continue
        if now_us - tr_us > OPPOSITE_FAIL_LOOKBACK_SEC * 1_000_000:
            continue
        if tr.get("action") == "FAIL" and opposite_side(case, tr.get("side", "")):
            rows.append(tr)
    count = len(rows)
    score = sum(float(row.get("score") or 0.0) for row in rows)
    label = ",".join(f"{row['time']} {row['range']}" for row in rows[-3:])
    return count, score, label


def recent_opposing_weak_contacts(
    case: Case,
    contacts: list[dict[str, Any]],
    now_us: int,
) -> tuple[int, str]:
    rows = []
    for contact in contacts:
        contact_us = int(contact["t_us"])
        if contact_us > now_us + 1_000_000:
            continue
        if now_us - contact_us > OPPOSITE_FAIL_LOOKBACK_SEC * 1_000_000:
            continue
        if not opposite_side(case, str(contact["side"])):
            continue
        if contact["grade"] == "depleted":
            rows.append(contact)
    label = ",".join(f"{row['time']} {row['range']}" for row in rows[-3:])
    return len(rows), label


def add_call(
    action: str,
    kahn_add_eligible: bool,
    flow: dict[str, float | None],
    runway: float,
    path_consumed: float,
    opposing_fail_count: int,
    opposing_weak_count: int,
) -> str:
    if runway < TARGET_PROXIMITY_POINTS:
        return "scale_out_zone"
    if not kahn_add_eligible:
        return "watch_contact"
    if flow_grade(flow) != "replenished":
        return "reject_depleted"
    if runway < MIN_PRESS_RUNWAY_POINTS:
        return "reject_low_runway"
    if path_consumed >= SUPPRESS_AFTER_PATH_FRACTION:
        return "mature_path_hold_only"
    if opposing_fail_count > 0 or opposing_weak_count > 0:
        if path_consumed >= REDUCE_SIZE_AFTER_PATH_FRACTION:
            return "add_preserve_root_reduced"
        return "add_preserve_root"
    if action in {"OWNED", "CONSUMED"}:
        return "add_review_no_recent_opp_fail"
    return "add_review"


def collect_scale_candidates(
    case: Case,
    transitions: list[dict[str, Any]],
    ticks: pl.DataFrame,
) -> list[dict[str, Any]]:
    entry_us = parse_hms_us(case.day, case.entry_time)
    end_us = ny_us(case.day, case.window.split("-", 1)[1])
    flow_cache: dict[int, pl.DataFrame] = {}
    latest_test_flow: dict[int, dict[str, float | None]] = {}
    latest_test_time: dict[int, int] = {}
    contacts: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    ordered = sorted(transitions, key=lambda item: transition_time_us(case, item))

    def table_for(hour: int) -> pl.DataFrame:
        if hour not in flow_cache:
            flow_cache[hour] = hour_flow_table(case.symbol_dir, case.day, hour)
        return flow_cache[hour]

    test_contact_by_key: dict[tuple[int, int], dict[str, float | None]] = {}
    for transition in ordered:
        t_us = transition_time_us(case, transition)
        hour = int(transition["time"][:2])
        lo = float(transition["min_price"])
        hi = float(transition["max_price"])
        owner_side = transition.get("side", "")
        action = transition.get("action", "")
        if action == "TEST":
            contact_flow = band_flow(
                table_for(hour),
                lo,
                hi,
                owner_side,
                t_us,
                t_us + FEATURE_SEC * 1_000_000,
            )
            band_id = int(transition["band_id"])
            test_contact_by_key[(band_id, t_us)] = contact_flow
            contacts.append(
                {
                    "t_us": t_us,
                    "time": transition["time"],
                    "band_id": band_id,
                    "side": owner_side,
                    "range": transition.get("range", ""),
                    "grade": flow_grade(contact_flow),
                }
            )

    for transition in ordered:
        t_us = transition_time_us(case, transition)
        hour = int(transition["time"][:2])
        lo = float(transition["min_price"])
        hi = float(transition["max_price"])
        owner_side = transition.get("side", "")
        action = transition.get("action", "")
        band_id = int(transition["band_id"])
        if action == "TEST":
            latest_test_flow[band_id] = test_contact_by_key[(band_id, t_us)]
            latest_test_time[band_id] = t_us

        if t_us < entry_us:
            continue
        if not same_side(case, owner_side):
            continue
        if action not in {"TEST", "HOLD", "OWNED", "CONSUMED"}:
            continue
        if not range_intersects(lo, hi, case.focus_lo, case.focus_hi):
            continue

        own_flow = latest_test_flow.get(band_id)
        source = "latest_test"
        if own_flow is None or t_us - latest_test_time.get(band_id, -10**18) > 240_000_000:
            own_flow = band_flow(
                table_for(hour),
                lo,
                hi,
                owner_side,
                t_us,
                t_us + FEATURE_SEC * 1_000_000,
            )
            source = "event_forward"

        price = transition_price(transition)
        runway = runway_points(case, price)
        path_consumed = path_consumed_fraction(case, price)
        path = mfe_mae(case, ticks, t_us, end_us, price)
        opp_count, opp_score, opp_label = recent_opposing_failure(case, transitions, t_us)
        opp_weak_count, opp_weak_label = recent_opposing_weak_contacts(case, contacts, t_us)
        kahn_add_eligible = action in {"HOLD", "OWNED", "CONSUMED"}
        rows.append(
            {
                "case_id": case.case_id,
                "time": transition["time"],
                "action": action,
                "band_id": band_id,
                "side": owner_side,
                "source": transition.get("source", ""),
                "range": transition.get("range", ""),
                "min_price": lo,
                "max_price": hi,
                "current_price": price,
                "score": round(float(transition.get("score") or 0.0), 3),
                "flow_source": source,
                "consumed": round(float(own_flow["consumed"] or 0.0), 1),
                "pulled": round(float(own_flow["pulled"] or 0.0), 1),
                "added": round(float(own_flow["added"] or 0.0), 1),
                "paid_share": round(float(own_flow["paid_share"]), 3)
                if own_flow["paid_share"] is not None
                else "",
                "replenish": round(float(own_flow["replenish"]), 3)
                if own_flow["replenish"] is not None
                else "",
                "flow_grade": flow_grade(own_flow),
                "runway_points": round(runway, 2),
                "path_consumed_pct": round(path_consumed * 100.0, 1),
                "opposing_fail_count_3m": opp_count,
                "opposing_fail_score_3m": round(opp_score, 2),
                "opposing_fail_recent": opp_label,
                "opposing_weak_contact_count_3m": opp_weak_count,
                "opposing_weak_contact_recent": opp_weak_label,
                "future_mfe": round(float(path["mfe"] or 0.0), 2),
                "future_mae": round(float(path["mae"] or 0.0), 2),
                "future_target_time": hms_from_us(path["target_time"]),
                "call": add_call(
                    action,
                    kahn_add_eligible,
                    own_flow,
                    runway,
                    path_consumed,
                    opp_count,
                    opp_weak_count,
                ),
            }
        )
    return rows


def collect_scale_out_events(
    case: Case,
    transitions: list[dict[str, Any]],
    ticks: pl.DataFrame,
) -> list[dict[str, Any]]:
    entry_us = parse_hms_us(case.day, case.entry_time)
    end_us = ny_us(case.day, case.window.split("-", 1)[1])
    path = mfe_mae(case, ticks, entry_us, end_us, case.entry_ref)
    target_us = path["target_time"]
    if target_us is None:
        return []

    rows = [
        {
            "case_id": case.case_id,
            "time": hms_from_us(target_us),
            "event": "target_floor_touch",
            "side": case.side,
            "range": f"{case.target_lo:g}-{case.target_hi:g}",
            "price": target_floor(case),
            "score": "",
            "call": "start_or_continue_passive_harvest",
        }
    ]
    for transition in transitions:
        t_us = transition_time_us(case, transition)
        if t_us < target_us or t_us > target_us + 10 * 60_000_000:
            continue
        price = transition_price(transition)
        target_band = abs(price - target_floor(case)) <= 8.0
        if not target_band:
            continue
        action = transition.get("action", "")
        side = transition.get("side", "")
        if opposite_side(case, side) and action in {"OWNED", "CONSUMED", "HOLD"}:
            call = "increase_harvest_or_retire"
        elif same_side(case, side) and action == "FAIL":
            call = "same_side_failed_near_target_harvest"
        else:
            continue
        rows.append(
            {
                "case_id": case.case_id,
                "time": transition["time"],
                "event": action,
                "side": side,
                "range": transition.get("range", ""),
                "price": price,
                "score": round(float(transition.get("score") or 0.0), 3),
                "call": call,
            }
        )
    return rows


def timestamp_sanity(case: Case) -> dict[str, Any]:
    start, end = case.window.split("-", 1)
    window = Window(case.symbol_dir, case.day, start, end, price_lo=case.focus_lo, price_hi=case.focus_hi)
    book = load_book(window)
    if not book.height:
        return {"case_id": case.case_id, "rows": 0}
    offset_ms = ((book["receipt_timestamp_us"] - book["t"]) / 1000.0).drop_nulls()
    return {
        "case_id": case.case_id,
        "rows": book.height,
        "receipt_minus_exchange_ms_median": round(float(offset_ms.median()), 1),
        "receipt_minus_exchange_ms_p05": round(float(offset_ms.quantile(0.05)), 1),
        "receipt_minus_exchange_ms_p95": round(float(offset_ms.quantile(0.95)), 1),
    }


def load_kahn_decisions(case: Case) -> list[dict[str, str]]:
    path = KAHN_0827_OUT / "key_decisions_gex_join.csv"
    if case.day != "2026-08-27" or not path.exists():
        return []
    start, end = case.window.split("-", 1)
    start_us = ny_us(case.day, start)
    end_us = ny_us(case.day, end)
    rows: list[dict[str, str]] = []
    seen: set[tuple[str, str, str, str]] = set()
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if row.get("symbol") != "ES":
                continue
            t_us = parse_hms_us(case.day, row["decision_et"])
            if not (start_us <= t_us <= end_us):
                continue
            key = (
                row["decision_et"],
                row["campaign_id"],
                row["action"],
                row.get("reason_code", ""),
            )
            if key in seen:
                continue
            seen.add(key)
            rows.append(
                {
                    "case_id": case.case_id,
                    "time": row["decision_et"],
                    "action": row["action"],
                    "policy": row["policy"],
                    "reason_code": row["reason_code"],
                    "pos": f"{row['pos_before']}->{row['pos_after']}",
                    "price": row["price"],
                    "phase": f"{row['phase_before']}->{row['phase_after']}",
                }
            )
    return rows


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def top_rows(rows: list[dict[str, Any]], case_id: str, limit: int = 10) -> list[dict[str, Any]]:
    selected = [row for row in rows if row["case_id"] == case_id]
    order = {
        "add_preserve_root": 0,
        "add_preserve_root_reduced": 1,
        "add_review_no_recent_opp_fail": 2,
        "add_review": 3,
        "watch_contact": 4,
        "mature_path_hold_only": 5,
        "reject_depleted": 6,
        "reject_low_runway": 7,
        "scale_out_zone": 8,
    }
    return sorted(
        selected,
        key=lambda row: (
            order.get(str(row["call"]), 99),
            -float(row["runway_points"]),
            float(row["future_mae"]),
            row["time"],
        ),
    )[:limit]


def report_markdown(
    summaries: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
    scale_out: list[dict[str, Any]],
    kahn: list[dict[str, Any]],
    sanity: list[dict[str, Any]],
) -> str:
    lines: list[str] = [
        "# HoldRoot Scale Management Probe",
        "",
        "Codex-authored research artifact. This is not accepted Kahn policy.",
        "",
        "Objective: find where Kahn could scale up while preserving the root risk "
        "anchor, then note where passive scale-out should start or accelerate.",
        "",
        "Scale-up call grammar:",
        "",
        "- `add_preserve_root`: same-side LL ownership/hold, replenished contact, "
        "target runway, and recent opposing rail failure or depleted opposing "
        "contact.",
        "- `add_preserve_root_reduced`: same condition, but enough target path "
        "is consumed that size should be smaller or capped.",
        "- `add_review_no_recent_opp_fail`: same-side owned/consumed rail and "
        "replenished contact, but no recent opposing failure.",
        "- `watch_contact`: TEST/contact quality only; not direct Kahn add evidence.",
        "- `reject_depleted`: same-side contact was being consumed/pulled faster "
        "than it replenished.",
        "- `scale_out_zone`: target proximity says harvest, not press.",
        "- `mature_path_hold_only`: rail quality is constructive but too much "
        "of the planned path has already paid.",
        "",
        "Timestamp note: MarketRecorder live storage carries both receipt and "
        "exchange timestamps. This script aligns book events to trades on "
        "`exchange_timestamp_us`; receipt time is treated as a capture-arrival "
        "diagnostic only.",
        "",
        "## Cases",
        "",
    ]
    for summary in summaries:
        lines.append(
            f"- `{summary['case_id']}`: {summary['side']} from "
            f"{summary['entry_time']} ref {summary['entry_ref']}, target floor "
            f"{summary['target_floor']}, MFE {summary['mfe']}, MAE {summary['mae']}, "
            f"target {summary['target_time']}."
        )

    lines.extend(["", "## Timestamp Sanity", ""])
    for row in sanity:
        lines.append(
            f"- `{row['case_id']}`: rows={row.get('rows', 0)}, "
            f"receipt-exchange median={row.get('receipt_minus_exchange_ms_median', '-')}"
            f"ms, p05={row.get('receipt_minus_exchange_ms_p05', '-')}ms, "
            f"p95={row.get('receipt_minus_exchange_ms_p95', '-')}ms."
        )

    lines.extend(["", "## Kahn Decisions In Actual 8/27 Windows", ""])
    if kahn:
        for row in kahn:
            lines.append(
                f"- `{row['case_id']}` {row['time']} {row['action']} "
                f"{row['pos']} {row['policy']}/{row['reason_code']} "
                f"price={row['price']} phase={row['phase']}."
            )
    else:
        lines.append("- none")

    lines.extend(["", "## Scale-Up Candidates", ""])
    for case in CASES:
        lines.append(f"### {case.case_id}")
        rows = top_rows(candidates, case.case_id, limit=12)
        if not rows:
            lines.append("")
            lines.append("- none")
            lines.append("")
            continue
        lines.append("")
        lines.append(
            "| time | action | band | range | replen | paid | oppFail/weak | runway | "
            "path% | future MFE/MAE | target | call |"
        )
        lines.append(
            "| --- | --- | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |"
        )
        for row in rows:
            lines.append(
                f"| {row['time']} | {row['action']} | {row['band_id']} | "
                f"{row['range']} | {row['replenish']} | {row['paid_share']} | "
                f"{row['opposing_fail_count_3m']}/"
                f"{row['opposing_weak_contact_count_3m']} | {row['runway_points']} | "
                f"{row['path_consumed_pct']} | "
                f"{row['future_mfe']}/{row['future_mae']} | "
                f"{row['future_target_time']} | {row['call']} |"
            )
        lines.append("")

    lines.extend(["## Scale-Out Notes", ""])
    if scale_out:
        for row in scale_out:
            lines.append(
                f"- `{row['case_id']}` {row['time']} {row['event']} "
                f"{row['side']} {row['range']} price={row['price']} "
                f"score={row['score']} -> {row['call']}."
            )
    else:
        lines.append("- no target floor touch inside tested windows")
    lines.append("")
    lines.append("## Initial Read")
    lines.append("")
    lines.append(
        "The promising policy shape is not to lower HoldRoot priority. It is to "
        "admit a narrower press decision whose risk anchor is explicitly the "
        "root anchor. That keeps the campaign falsifier stable while allowing "
        "one or more controlled adds when the rail being challenged is still "
        "replenishing and the opposing side has just failed or is being "
        "depleted. Late-path versions should reduce size or stop adding."
    )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--out-dir",
        default=str(REPO / "research" / "kahn" / "out" / "holdroot-scale-20260830"),
    )
    args = parser.parse_args()
    out_dir = Path(args.out_dir)

    summaries: list[dict[str, Any]] = []
    candidates: list[dict[str, Any]] = []
    scale_out: list[dict[str, Any]] = []
    kahn: list[dict[str, Any]] = []
    sanity: list[dict[str, Any]] = []

    for case in CASES:
        print(f"# {case.case_id}")
        transitions = ll_transitions(case)
        ticks = load_case_ticks(case)
        summaries.append(case_summary(case, ticks))
        candidates.extend(collect_scale_candidates(case, transitions, ticks))
        scale_out.extend(collect_scale_out_events(case, transitions, ticks))
        kahn.extend(load_kahn_decisions(case))
        sanity.append(timestamp_sanity(case))

    write_csv(out_dir / "case_summary.csv", summaries)
    write_csv(out_dir / "scale_candidates.csv", candidates)
    write_csv(out_dir / "scale_out_events.csv", scale_out)
    write_csv(out_dir / "kahn_decisions.csv", kahn)
    write_csv(out_dir / "timestamp_sanity.csv", sanity)
    report = report_markdown(summaries, candidates, scale_out, kahn, sanity)
    (out_dir / "report.md").write_text(report, encoding="utf-8")
    print(report)


if __name__ == "__main__":
    main()
