"""Evaluate offline GEX overlay hypotheses for 2026-08-27 Kahn research.

This script is intentionally descriptive. It consumes previously generated
Kahn/GEX research CSVs and emits candidate overlay decisions for discussion.
It does not modify KahnRuntime, campaign JSON, or runtime logs.
"""

from __future__ import annotations

import argparse
import csv
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import polars as pl

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from capture_loader import load_capture_window, tick_columns  # noqa: E402


DATE = "2026-08-27"
NY = ZoneInfo("America/New_York")
SYMBOL_DIR = {"ES": "ESU6", "NQ": "NQU6"}
TICK_SIZE = {"ES": 0.25, "NQ": 0.25}
HARD_TARGET_FIELDS = {
    "Long": ("call_wall", "oi_call_wall"),
    "Short": ("put_wall", "oi_put_wall"),
}
SOURCE_FIELDS = {
    "Long": ("zero_gamma", "put_wall", "oi_put_wall"),
    "Short": ("zero_gamma", "call_wall", "oi_call_wall"),
}
THRESHOLDS = {
    "ES": {
        "mfe_min": 8.0,
        "mae_max": 4.0,
        "runway_min": 8.0,
        "terminal_distance": 4.0,
        "source_near": 7.0,
        "zero_watch": 8.0,
    },
    "NQ": {
        "mfe_min": 30.0,
        "mae_max": 20.0,
        "runway_min": 30.0,
        "terminal_distance": 18.0,
        "source_near": 24.0,
        "zero_watch": 24.0,
    },
}


def parse_utc(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def et_dt(hhmmss: str) -> datetime:
    return datetime.fromisoformat(f"{DATE}T{hhmmss}").replace(tzinfo=NY)


def et_text(value: datetime | None) -> str:
    return "" if value is None else value.astimezone(NY).strftime("%H:%M:%S")


def as_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number and number not in (float("inf"), float("-inf")) else None


def fmt(value: Any, digits: int = 2) -> str:
    number = as_float(value)
    if number is None:
        return "-"
    return f"{number:.{digits}f}".rstrip("0").rstrip(".")


def read_csv(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    keys: list[str] = []
    seen = set()
    for row in rows:
        for key in row:
            if key not in seen:
                keys.append(key)
                seen.add(key)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=keys)
        writer.writeheader()
        writer.writerows(rows)


def first_touch(symbol: str,
    start: datetime,
    end: datetime,
    position_side: str,
    limit_price: float,
) -> tuple[datetime | None, float | None]:
    df = load_capture_window("ticks", SYMBOL_DIR[symbol], start, end, tick_columns())
    if df.is_empty():
        return None, None
    if position_side == "Long":
        hits = df.filter(pl.col("price") >= limit_price).sort("timestamp_us")
    else:
        hits = df.filter(pl.col("price") <= limit_price).sort("timestamp_us")
    if hits.is_empty():
        return None, None
    ts = datetime.fromtimestamp(int(hits["timestamp_us"][0]) / 1_000_000, tz=timezone.utc)
    return ts, float(hits["price"][0])


def window_extremes(symbol: str, start: datetime, end: datetime) -> dict[str, Any]:
    df = load_capture_window("ticks", SYMBOL_DIR[symbol], start, end, tick_columns())
    if df.is_empty():
        return {}
    return {
        "window_high": float(df["price"].max()),
        "window_low": float(df["price"].min()),
        "window_first": float(df["price"][0]),
        "window_last": float(df["price"][-1]),
    }


def directional_level(row: dict[str, Any],
    side: str,
    fields: tuple[str, ...],
    price: float,
) -> tuple[str, float | None, float | None]:
    best_field = ""
    best_level: float | None = None
    best_distance: float | None = None
    for field in fields:
        level = as_float(row.get(field))
        if level is None:
            continue
        if side == "Long" and level <= price:
            continue
        if side == "Short" and level >= price:
            continue
        distance = level - price if side == "Long" else price - level
        if best_distance is None or distance < best_distance:
            best_field = field
            best_level = level
            best_distance = distance
    return best_field, best_level, best_distance


def nearest_source(row: dict[str, Any],
    side: str,
    fields: tuple[str, ...],
    price: float,
) -> tuple[str, float | None, float | None, float | None]:
    best_field = ""
    best_level: float | None = None
    best_abs: float | None = None
    best_signed: float | None = None
    for field in fields:
        level = as_float(row.get(field))
        if level is None:
            continue
        signed = price - level
        distance = abs(signed)
        if best_abs is None or distance < best_abs:
            best_field = field
            best_level = level
            best_abs = distance
            best_signed = signed
    return best_field, best_level, best_abs, best_signed


def zero_ahead(row: dict[str, Any], side: str, price: float) -> float | None:
    zero = as_float(row.get("zero_gamma"))
    if zero is None:
        return None
    if side == "Long" and zero > price:
        return zero - price
    if side == "Short" and zero < price:
        return price - zero
    return None


def classify_add(row: dict[str, Any]) -> dict[str, Any]:
    symbol = str(row.get("symbol") or "")
    side = str(row.get("campaign_side") or "")
    price = as_float(row.get("first_price"))
    mfe = as_float(row.get("30m_mfe")) or 0.0
    mae = as_float(row.get("30m_mae")) or 0.0
    reason = str(row.get("candidate_reason") or "")
    thresholds = THRESHOLDS.get(symbol, THRESHOLDS["ES"])
    if side not in HARD_TARGET_FIELDS or price is None:
        return {"overlay_action": "review_missing_context"}

    target_field, target_level, target_runway = directional_level(
        row,
        side,
        HARD_TARGET_FIELDS[side],
        price,
    )
    source_field, source_level, source_abs, source_signed = nearest_source(
        row,
        side,
        SOURCE_FIELDS[side],
        price,
    )
    zero_distance = zero_ahead(row, side, price)
    good_excursion = (
        mfe >= thresholds["mfe_min"]
        and mae <= thresholds["mae_max"]
        and mfe >= max(1.0, mae * 2.0)
    )
    runway_ok = target_runway is not None and target_runway >= thresholds["runway_min"]
    near_terminal = target_runway is not None and target_runway <= thresholds["terminal_distance"]
    source_near = source_abs is not None and source_abs <= thresholds["source_near"]
    zero_watch = zero_distance is not None and zero_distance <= thresholds["zero_watch"]

    action = "keep_suppressed_or_review"
    evidence = "insufficient overlay separation"
    if near_terminal:
        action = "keep_suppressed_terminal"
        evidence = "same-side evidence is too close to a directional GEX destination"
    elif mae > thresholds["mae_max"]:
        action = "keep_suppressed_path_variance"
        evidence = "future adverse excursion is too large for normal add risk"
    elif "holdroot_shadowed_add" in reason and good_excursion and runway_ok and source_near:
        if zero_watch:
            action = "test_holdroot_add_zero_limited"
            evidence = "root/build is alive with runway, but zero-gamma is an interim review point"
        else:
            action = "test_holdroot_to_add_conversion"
            evidence = "root/build evidence had source context, runway, and low adverse excursion"
    elif "no_add_zone" in reason and good_excursion and runway_ok and source_near:
        if side == "Long" and source_signed is not None and source_signed < 0:
            action = "arm_wall_conversion_pending_acceptance"
            evidence = "support wall is nearby but price has not clearly accepted beyond it"
        else:
            action = "test_wall_conversion_add"
            evidence = "former wall/support area plus same-side LL evidence had enough runway"
    elif good_excursion and runway_ok:
        action = "review_possible_add"
        evidence = "good excursion profile, but source conversion is not clean"

    return {
        "target_field": target_field,
        "target_level": target_level if target_level is not None else "",
        "target_runway": target_runway if target_runway is not None else "",
        "source_field": source_field,
        "source_level": source_level if source_level is not None else "",
        "source_distance_abs": source_abs if source_abs is not None else "",
        "source_signed_price_minus_level": source_signed if source_signed is not None else "",
        "zero_ahead_distance": zero_distance if zero_distance is not None else "",
        "good_excursion": good_excursion,
        "runway_ok": runway_ok,
        "near_terminal": near_terminal,
        "source_near": source_near,
        "overlay_action": action,
        "overlay_evidence": evidence,
    }


def evaluate_adds(out_dir: Path) -> list[dict[str, Any]]:
    rows = read_csv(out_dir / "add_candidate_classes.csv")
    out: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        item.update(classify_add(row))
        out.append(item)
    return out


def first_negative_sum_gex(rows: list[dict[str, Any]]) -> datetime | None:
    for row in rows:
        if row.get("category") != "gex_zero":
            continue
        value = as_float(row.get("sum_gex_vol"))
        ts = parse_utc(row.get("recorded_at_utc"))
        if value is not None and value < 0 and ts is not None:
            return ts
    return None


def summarize_gex_field(rows: list[dict[str, Any]], field: str) -> dict[str, Any]:
    zero_rows = [row for row in rows if row.get("category") == "gex_zero"]
    levels = [as_float(row.get(field)) for row in zero_rows]
    levels = [level for level in levels if level is not None]
    sums = [as_float(row.get("sum_gex_vol")) for row in zero_rows]
    sums = [value for value in sums if value is not None]
    return {
        "gex_field": field,
        "gex_level_first": levels[0] if levels else "",
        "gex_level_last": levels[-1] if levels else "",
        "gex_level_min": min(levels) if levels else "",
        "gex_level_max": max(levels) if levels else "",
        "gex_level_stability_points": (max(levels) - min(levels)) if levels else "",
        "sum_gex_vol_first": sums[0] if sums else "",
        "sum_gex_vol_last": sums[-1] if sums else "",
        "sum_gex_vol_min": min(sums) if sums else "",
        "sum_gex_vol_max": max(sums) if sums else "",
        "sum_gex_vol_crossed_zero": bool(sums and min(sums) < 0 < max(sums)),
    }


def evaluate_harvests(out_dir: Path) -> list[dict[str, Any]]:
    cases = [
        {
            "case_id": "es_long_terminal_nearmiss_7743",
            "symbol": "ES",
            "position_side": "Long",
            "start": et_dt("11:15:00"),
            "end": et_dt("11:30:00"),
            "gex_file": out_dir / "exit_long_near_harvest_gex.csv",
            "gex_field": "call_wall",
            "baseline": "no_logged_exit_expiry_bug_context",
            "baseline_et": "",
            "overlay_trigger": et_dt("11:17:00"),
            "trigger_basis": "stable call wall near predeclared 7743 target; high reached 7742.75 without LL failure",
            "limits": [7743.0, 7742.75, 7742.5],
        },
        {
            "case_id": "es_short_target_7728_7729_50",
            "symbol": "ES",
            "position_side": "Short",
            "start": et_dt("14:18:00"),
            "end": et_dt("14:34:00"),
            "gex_file": out_dir / "exit_short_harvest_gex.csv",
            "gex_field": "oi_put_wall",
            "baseline": "Kahn Retire target_zone/opposite_ownership_at_target",
            "baseline_et": "14:31:48",
            "overlay_trigger": None,
            "trigger_basis": "target overlapped stable OI put wall; net GEX flipped negative as price traded into target",
            "limits": [7729.5, 7729.0, 7728.5, 7728.0],
        },
    ]
    out: list[dict[str, Any]] = []
    for case in cases:
        gex_rows = read_csv(case["gex_file"])
        trigger = case["overlay_trigger"] or first_negative_sum_gex(gex_rows) or case["start"]
        extremes = window_extremes(case["symbol"], case["start"], case["end"])
        gex_summary = summarize_gex_field(gex_rows, case["gex_field"])
        baseline_ts = parse_baseline_et(case["baseline_et"])
        for limit in case["limits"]:
            touch_ts, touch_price = first_touch(case["symbol"], trigger, case["end"], case["position_side"], limit)
            minutes_before = ""
            if touch_ts is not None and baseline_ts is not None:
                minutes_before = round((baseline_ts - touch_ts).total_seconds() / 60.0, 2)
            action = "stage_passive_harvest" if touch_ts is not None else "tighten_no_passive_fill"
            if case["case_id"] == "es_long_terminal_nearmiss_7743" and limit < 7743.0:
                action = "test_nearmiss_reduce"
            out.append(
                {
                    "case_id": case["case_id"],
                    "symbol": case["symbol"],
                    "position_side": case["position_side"],
                    "overlay_action": action,
                    "trigger_et": et_text(trigger),
                    "trigger_basis": case["trigger_basis"],
                    "baseline": case["baseline"],
                    "baseline_et": case["baseline_et"],
                    "limit_price": limit,
                    "limit_touched": touch_ts is not None,
                    "touch_et": et_text(touch_ts),
                    "touch_price": touch_price if touch_price is not None else "",
                    "minutes_before_baseline": minutes_before,
                    **gex_summary,
                    **extremes,
                }
            )
    return out


def parse_baseline_et(value: str) -> datetime | None:
    if not value:
        return None
    return et_dt(value)


def evaluate_probes(out_dir: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in read_csv(out_dir / "probe_entry_classes.csv"):
        actual = as_float(row.get("actual_points_per_contract"))
        one_tick = as_float(row.get("limit_1t_fill_delay_s"))
        two_tick = as_float(row.get("limit_2t_fill_delay_s"))
        action = "review"
        evidence = "limit-first belongs behind harvest/add research"
        if one_tick is not None and two_tick is not None:
            if actual is not None and actual < 0:
                action = "test_limit_first_loss_reduction"
                evidence = "better limit was touched, but selection still failed"
            elif two_tick > 5:
                action = "market_or_one_tick_urgency"
                evidence = "two-tick concession took long enough to risk missing the move"
            else:
                action = "test_limit_first_variance_reduction"
                evidence = "better limit was touched quickly on a winning probe"
        item = dict(row)
        item["overlay_action"] = action
        item["overlay_evidence"] = evidence
        out.append(item)
    return out


def render_harvest_table(rows: list[dict[str, Any]]) -> list[str]:
    lines = [
        "| Case | Action | Trigger | Limit | Touched | Touch | Before Baseline | Wall Stability | Window |",
        "|---|---|---:|---:|---|---:|---:|---:|---|",
    ]
    for row in rows:
        lines.append(
            f"| {row['case_id']} | {row['overlay_action']} | {row['trigger_et']} | "
            f"{fmt(row['limit_price'])} | {row['limit_touched']} | {row['touch_et'] or '-'} | "
            f"{fmt(row['minutes_before_baseline'])} | "
            f"{row['gex_field']} {fmt(row['gex_level_min'])}-{fmt(row['gex_level_max'])} | "
            f"{fmt(row.get('window_low'))}-{fmt(row.get('window_high'))} |"
        )
    return lines


def render_add_table(rows: list[dict[str, Any]]) -> list[str]:
    lines = [
        "| Symbol | ET | Side | Overlay | Logged | Price | 30m MFE/MAE | Source | Target Runway | Zero Ahead |",
        "|---|---:|---|---|---|---:|---:|---|---:|---:|",
    ]
    selected = [
        row for row in rows
        if row.get("overlay_action") != "keep_suppressed_or_review"
    ]
    for row in selected:
        lines.append(
            f"| {row['symbol']} | {row['candidate_et']} | {row['campaign_side']} | "
            f"{row['overlay_action']} | {row['logged_policy']}/{row['logged_reason_code']} | "
            f"{fmt(row['first_price'])} | {fmt(row.get('30m_mfe'))}/{fmt(row.get('30m_mae'))} | "
            f"{row.get('source_field') or '-'} {fmt(row.get('source_level'))} "
            f"({fmt(row.get('source_signed_price_minus_level'))}) | "
            f"{row.get('target_field') or '-'} {fmt(row.get('target_runway'))} | "
            f"{fmt(row.get('zero_ahead_distance'))} |"
        )
    return lines


def render_probe_table(rows: list[dict[str, Any]]) -> list[str]:
    lines = [
        "| Symbol | ET | Side | Overlay | Outcome | Actual | 1t/2t Delay |",
        "|---|---:|---|---|---|---:|---:|",
    ]
    for row in rows:
        lines.append(
            f"| {row['symbol']} | {row['entry_et']} | {row['campaign_side']} | "
            f"{row['overlay_action']} | {row['probe_outcome_class']} | "
            f"{fmt(row.get('actual_points_per_contract'))} | "
            f"{row.get('limit_1t_fill_delay_s')}/{row.get('limit_2t_fill_delay_s')} |"
        )
    return lines


def render_report(out_dir: Path,
    harvests: list[dict[str, Any]],
    adds: list[dict[str, Any]],
    probes: list[dict[str, Any]],
) -> str:
    add_counts = Counter(row.get("overlay_action") for row in adds)
    harvest_counts = Counter(row.get("overlay_action") for row in harvests)
    probe_counts = Counter(row.get("overlay_action") for row in probes)
    lines = [
        "# 2026-08-27 GEX Overlay Hypothesis Evaluation",
        "",
        "This is an offline baseline-vs-overlay research pass, not a runtime policy proposal.",
        "",
        "## Method",
        "",
        "- Harvest cases test whether a stable GEX terminal level would have staged a passive reduce/retire before LL failure.",
        "- Add cases start only from Kahn-observed same-side LL moments that were logged as `HoldRoot` or `SuppressAdd`.",
        "- Probe order-mode rows are included only as a low-priority variance check.",
        "- GEX never creates entry or add permission in this pass; it only classifies management context around existing Kahn evidence.",
        "",
        "## Counts",
        "",
        f"- Harvest overlay rows: {len(harvests)} ({format_counts(harvest_counts)})",
        f"- Add candidate rows: {len(adds)} ({format_counts(add_counts)})",
        f"- Probe rows: {len(probes)} ({format_counts(probe_counts)})",
        "",
        "## Harvest / Exit Overlay",
        "",
    ]
    lines.extend(render_harvest_table(harvests))
    lines.extend(
        [
            "",
            "Read: the short target supports passive harvest into the `7728-7729.50` zone; the long target supports a separate near-miss reduce/tighten test because the exact `7743` limit was not touched.",
            "",
            "## Add Overlay",
            "",
        ]
    )
    lines.extend(render_add_table(adds))
    lines.extend(
        [
            "",
            "Read: ES has testable add-conversion candidates. NQ mostly remains suppression/path-variance evidence, not add evidence.",
            "",
            "## Probe Order Mode Appendix",
            "",
        ]
    )
    lines.extend(render_probe_table(probes))
    lines.extend(
        [
            "",
            "## Output Files",
            "",
            f"- `{out_dir / 'gex_overlay_harvest_decisions.csv'}`",
            f"- `{out_dir / 'gex_overlay_add_decisions.csv'}`",
            f"- `{out_dir / 'gex_overlay_probe_order_mode.csv'}`",
        ]
    )
    return "\n".join(lines) + "\n"


def format_counts(counts: Counter[str]) -> str:
    return ", ".join(f"{key}={value}" for key, value in sorted(counts.items()))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", default=r"research\kahn\out\2026-08-27-gex-kahn")
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    harvests = evaluate_harvests(out_dir)
    adds = evaluate_adds(out_dir)
    probes = evaluate_probes(out_dir)

    write_csv(out_dir / "gex_overlay_harvest_decisions.csv", harvests)
    write_csv(out_dir / "gex_overlay_add_decisions.csv", adds)
    write_csv(out_dir / "gex_overlay_probe_order_mode.csv", probes)
    report = render_report(out_dir, harvests, adds, probes)
    (out_dir / "gex_overlay_hypothesis_report.md").write_text(report, encoding="utf-8")

    print(
        f"harvests={len(harvests)} adds={len(adds)} probes={len(probes)} "
        f"out={out_dir / 'gex_overlay_hypothesis_report.md'}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
