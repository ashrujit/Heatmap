"""Codex-authored local LVN separator research for Kahn scale permission.

This probe tests the user's hunch that add mode may become safer when a
point-in-time low-volume separator forms between root A and the later
participation event. The separator is intentionally local: it is measured from
ticks available between root entry and the candidate timestamp, then compared
against the same price in the broader RTH profile only as an ex-post check.

The output is research only. It is not accepted Kahn policy.
"""

from __future__ import annotations

import argparse
import csv
import statistics
from pathlib import Path
from typing import Any

import polars as pl

from holdroot_scale_probe import (
    CASES,
    REPO,
    Case,
    Window,
    case_summary,
    load_case_ticks,
    load_ticks,
    parse_hms_us,
    write_csv,
)


BIN_POINTS = 0.50
ENDPOINT_EXCLUSION_POINTS = 1.0
MIN_CORRIDOR_POINTS = 3.0
MIN_EVENT_GAP_POINTS = 1.0
LOCAL_STRONG_RATIO = 0.35
LOCAL_MEDIUM_RATIO = 0.55
DAY_VISIBLE_RATIO = 0.45


def load_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


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


def price_bin(price: float, bin_points: float = BIN_POINTS) -> float:
    return round((price // bin_points) * bin_points, 2)


def profile_map(
    ticks: pl.DataFrame,
    start_us: int,
    end_us: int,
    lo: float,
    hi: float,
    bin_points: float = BIN_POINTS,
) -> dict[float, dict[str, float | int]]:
    if end_us <= start_us or hi <= lo:
        return {}
    sub = ticks.filter(
        (pl.col("timestamp_us") >= start_us)
        & (pl.col("timestamp_us") <= end_us)
        & (pl.col("price") >= lo)
        & (pl.col("price") <= hi)
    )
    rows: dict[float, dict[str, float | int]] = {}
    if sub.height:
        prof = (
            sub.with_columns(
                ((pl.col("price") / bin_points).floor() * bin_points).round(2).alias("bin"),
                (pl.col("timestamp_us") // 1_000_000).cast(pl.Int64).alias("sec"),
            )
            .group_by("bin")
            .agg(
                pl.col("size").sum().alias("vol"),
                (pl.col("size") * pl.col("aggressor_sign")).sum().alias("delta"),
                pl.len().alias("trades"),
                pl.col("sec").n_unique().alias("seconds"),
            )
        )
        for row in prof.iter_rows(named=True):
            rows[float(row["bin"])] = {
                "vol": float(row["vol"]),
                "delta": float(row["delta"]),
                "trades": int(row["trades"]),
                "seconds": int(row["seconds"]),
            }

    first_bin = price_bin(lo, bin_points)
    last_bin = price_bin(hi, bin_points)
    value = first_bin
    while value <= last_bin + 1e-9:
        rows.setdefault(value, {"vol": 0.0, "delta": 0.0, "trades": 0, "seconds": 0})
        value = round(value + bin_points, 2)
    return dict(sorted(rows.items()))


def median_positive(values: list[float]) -> float:
    positives = [value for value in values if value > 0]
    if not positives:
        return 0.0
    return statistics.median(positives)


def percentile_le(values: list[float], value: float) -> float:
    if not values:
        return 0.0
    return sum(1 for item in values if item <= value) / len(values)


def corridor_bounds(case: Case, event_price: float) -> tuple[float, float]:
    lo = min(case.entry_ref, event_price)
    hi = max(case.entry_ref, event_price)
    return lo, hi


def expand_price_token(token: str, anchor: float) -> float:
    value = float(token)
    if value >= 1000.0:
        return value
    base = int(anchor // 1000.0) * 1000
    return base + value


def parse_display_range(text: str, anchor: float) -> tuple[float, float] | None:
    raw = text.strip()
    if not raw:
        return None
    parts = raw.split("-", 1)
    try:
        if len(parts) == 1:
            value = expand_price_token(parts[0], anchor)
            return value, value
        lo = expand_price_token(parts[0], anchor)
        hi = expand_price_token(parts[1], anchor)
    except ValueError:
        return None
    return min(lo, hi), max(lo, hi)


def gap_between_ranges(a: tuple[float, float], b: tuple[float, float]) -> tuple[float, float] | None:
    a_lo, a_hi = a
    b_lo, b_hi = b
    if a_hi < b_lo:
        return a_hi, b_lo
    if b_hi < a_lo:
        return b_hi, a_lo
    return None


def prefixed(prefix: str, values: dict[str, Any]) -> dict[str, Any]:
    return {f"{prefix}{key}": value for key, value in values.items()}


def choose_separator(
    case: Case,
    local_ticks: pl.DataFrame,
    day_ticks: pl.DataFrame,
    start_us: int,
    end_us: int,
    event_price: float,
    bounds: tuple[float, float] | None = None,
    min_corridor_points: float = MIN_CORRIDOR_POINTS,
    endpoint_exclusion_points: float = ENDPOINT_EXCLUSION_POINTS,
) -> dict[str, Any]:
    lo, hi = bounds if bounds is not None else corridor_bounds(case, event_price)
    width = hi - lo
    base = {
        "corridor_lo": round(lo, 2),
        "corridor_hi": round(hi, 2),
        "corridor_points": round(width, 2),
    }
    if width < min_corridor_points:
        return {**base, "separator_call": "no_corridor"}

    inner_lo = lo + endpoint_exclusion_points
    inner_hi = hi - endpoint_exclusion_points
    local = profile_map(local_ticks, start_us, end_us, lo, hi)
    day = profile_map(day_ticks, int(day_ticks["timestamp_us"].min()), int(day_ticks["timestamp_us"].max()), lo, hi)
    if not local:
        return {**base, "separator_call": "no_local_profile"}

    bins = list(local.keys())
    volumes = [float(local[bin_price]["vol"]) for bin_price in bins]
    med = median_positive(volumes)
    if med <= 0:
        return {**base, "separator_call": "no_local_volume"}

    candidates = [bin_price for bin_price in bins if inner_lo <= bin_price <= inner_hi]
    if not candidates:
        return {**base, "separator_call": "no_inner_bins"}

    ranked: list[dict[str, Any]] = []
    for bin_price in candidates:
        idx = bins.index(bin_price)
        left_peak = max(volumes[:idx], default=0.0)
        right_peak = max(volumes[idx + 1 :], default=0.0)
        flank = min(left_peak, right_peak)
        vol = float(local[bin_price]["vol"])
        neighbor_ratio = vol / flank if flank > 0 else 1.0
        median_ratio = vol / med if med > 0 else 1.0
        score = min(neighbor_ratio, median_ratio)
        ranked.append(
            {
                "bin": bin_price,
                "vol": vol,
                "delta": float(local[bin_price]["delta"]),
                "trades": int(local[bin_price]["trades"]),
                "seconds": int(local[bin_price]["seconds"]),
                "left_peak": left_peak,
                "right_peak": right_peak,
                "neighbor_ratio": neighbor_ratio,
                "median_ratio": median_ratio,
                "score": score,
            }
        )

    best = sorted(ranked, key=lambda item: (item["score"], item["vol"], item["bin"]))[0]
    day_vols = [float(row["vol"]) for row in day.values()]
    day_med = median_positive(day_vols)
    day_row = day.get(float(best["bin"]), {"vol": 0.0, "delta": 0.0, "trades": 0, "seconds": 0})
    day_vol = float(day_row["vol"])
    day_ratio = day_vol / day_med if day_med > 0 else 0.0
    day_percentile = percentile_le(day_vols, day_vol)

    median_ratio = float(best["median_ratio"])
    neighbor_ratio = float(best["neighbor_ratio"])
    strong_local = median_ratio <= LOCAL_STRONG_RATIO and neighbor_ratio <= LOCAL_STRONG_RATIO
    medium_local = median_ratio <= LOCAL_MEDIUM_RATIO or neighbor_ratio <= LOCAL_MEDIUM_RATIO
    if strong_local and day_ratio > DAY_VISIBLE_RATIO:
        call = "local_lvn_separator"
    elif strong_local:
        call = "day_visible_lvn_separator"
    elif medium_local:
        call = "weak_local_separator"
    else:
        call = "no_lvn_separator"

    return {
        **base,
        "separator_bin": round(float(best["bin"]), 2),
        "separator_lo": round(float(best["bin"]), 2),
        "separator_hi": round(float(best["bin"]) + BIN_POINTS, 2),
        "local_vol": round(float(best["vol"]), 1),
        "local_delta": round(float(best["delta"]), 1),
        "local_trades": int(best["trades"]),
        "local_seconds": int(best["seconds"]),
        "local_median_vol": round(med, 1),
        "local_median_ratio": round(float(best["median_ratio"]), 3),
        "local_neighbor_ratio": round(float(best["neighbor_ratio"]), 3),
        "left_peak_vol": round(float(best["left_peak"]), 1),
        "right_peak_vol": round(float(best["right_peak"]), 1),
        "day_vol": round(day_vol, 1),
        "day_median_vol": round(day_med, 1),
        "day_ratio": round(day_ratio, 3),
        "day_percentile_le": round(day_percentile, 3),
        "separator_call": call,
    }


def source_rows() -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    sponsor_path = REPO / "research" / "kahn" / "out" / "sponsor-stack-scale-20260830" / "stack_candidates.csv"
    tail_path = REPO / "research" / "kahn" / "out" / "tail-reclaim-sequence-20260830" / "tail_reclaim_sequences.csv"
    for row in load_csv(sponsor_path):
        call = row.get("call", "")
        if call.startswith("sponsor_stack") or call.startswith("stack_watch"):
            item = dict(row)
            item["source_probe"] = "sponsor_stack"
            out.append(item)
    for row in load_csv(tail_path):
        call = row.get("call", "")
        if call.startswith("tail_reclaim"):
            item = dict(row)
            item["source_probe"] = "tail_reclaim"
            out.append(item)
    return out


def collect_lvn_rows() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows = source_rows()
    by_case: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        by_case.setdefault(row["case_id"], []).append(row)

    out: list[dict[str, Any]] = []
    summaries: list[dict[str, Any]] = []
    for case in CASES:
        case_rows = by_case.get(case.case_id, [])
        if not case_rows:
            continue
        ticks = load_case_ticks(case)
        day_ticks = load_ticks(
            Window(
                case.symbol_dir,
                case.day,
                "09:30",
                "16:00",
                price_lo=case.focus_lo - 4.0,
                price_hi=case.focus_hi + 4.0,
            )
        )
        entry_us = parse_hms_us(case.day, case.entry_time)
        summaries.append(case_summary(case, ticks))
        for row in case_rows:
            event_us = parse_hms_us(case.day, row["time"])
            event_price = float(row["current_price"])
            sep = choose_separator(case, ticks, day_ticks, entry_us, event_us, event_price)
            enriched = {
                "case_id": case.case_id,
                "source_probe": row["source_probe"],
                "time": row["time"],
                "call": row.get("call", ""),
                "action": row.get("action", ""),
                "range": row.get("range", ""),
                "current_price": event_price,
                "root_price": case.entry_ref,
                "side": case.side,
                "root_to_event_points": round(abs(case.entry_ref - event_price), 2),
                "replenish": row.get("replenish", ""),
                "runway_points": row.get("runway_points", ""),
                "path_consumed_pct": row.get("path_consumed_pct", ""),
                **sep,
            }
            if row["source_probe"] == "tail_reclaim":
                zz_range = parse_display_range(row.get("zz_range", ""), event_price)
                event_range = parse_display_range(row.get("range", ""), event_price)
                if zz_range is not None and event_range is not None:
                    gap = gap_between_ranges(zz_range, event_range)
                    if gap is None:
                        event_gap = {"separator_call": "ranges_overlap"}
                    else:
                        event_gap = choose_separator(
                            case,
                            ticks,
                            day_ticks,
                            entry_us,
                            event_us,
                            event_price,
                            bounds=gap,
                            min_corridor_points=MIN_EVENT_GAP_POINTS,
                            endpoint_exclusion_points=0.0,
                        )
                    enriched.update(prefixed("event_gap_", event_gap))
                enriched.update(
                    {
                        "zz_time": row.get("zz_time", ""),
                        "zz_range": row.get("zz_range", ""),
                        "pre_zz_tail_time": row.get("pre_zz_tail_time", ""),
                        "pre_zz_tail_price": row.get("pre_zz_tail_price", ""),
                    }
                )
            out.append(enriched)
    return summaries, out


def top_rows(rows: list[dict[str, Any]], case_id: str, limit: int = 16) -> list[dict[str, Any]]:
    call_rank = {
        "local_lvn_separator": 0,
        "day_visible_lvn_separator": 1,
        "weak_local_separator": 2,
        "no_lvn_separator": 3,
        "no_corridor": 4,
    }
    source_rank = {"tail_reclaim": 0, "sponsor_stack": 1}
    selected = [row for row in rows if row["case_id"] == case_id]
    return sorted(
        selected,
        key=lambda row: (
            call_rank.get(str(row.get("separator_call", "")), 99),
            source_rank.get(str(row.get("source_probe", "")), 99),
            row["time"],
        ),
    )[:limit]


def report_markdown(summaries: list[dict[str, Any]], rows: list[dict[str, Any]]) -> str:
    lines = [
        "# Local LVN Separator Probe",
        "",
        "Codex-authored research artifact. This is not accepted Kahn policy.",
        "",
        "Hypothesis: add mode is safer when a point-in-time low-volume separator "
        "forms between root A and the later add/reclaim event. The separator is "
        "measured from root-entry ticks only; the RTH profile comparison is an "
        "ex-post check for whether the node was local rather than a visible day "
        "profile level.",
        "",
        "Separator calls:",
        "",
        "- `local_lvn_separator`: local volume is <= 35 percent of nearby/median "
        "corridor volume, while the same bin is not a strong RTH LVN.",
        "- `day_visible_lvn_separator`: locally poor volume, but also visible in "
        "the broader RTH profile.",
        "- `weak_local_separator`: local separator is present but not strong.",
        "- `no_lvn_separator`: corridor exists, but no local separator is visible.",
        "",
        "## Cases",
        "",
    ]
    for summary in summaries:
        lines.append(
            f"- `{summary['case_id']}`: {summary['side']} from {summary['entry_time']} "
            f"ref {summary['entry_ref']}, target floor {summary['target_floor']}, "
            f"MFE {summary['mfe']}, MAE {summary['mae']}, target {summary['target_time']}."
        )

    lines.extend(["", "## Candidate Separators", ""])
    for case in CASES:
        lines.append(f"### {case.case_id}")
        selected = top_rows(rows, case.case_id)
        if not selected:
            lines.extend(["", "- none", ""])
            continue
        lines.append("")
        lines.append(
            "| probe | time | root sep | event gap sep | event | sep | gap sep | root-event | path% | scale call |"
        )
        lines.append("| --- | --- | --- | --- | --- | --- | --- | ---: | ---: | --- |")
        for row in selected:
            sep = "-"
            if row.get("separator_bin", "") != "":
                sep = f"{row['separator_lo']}-{row['separator_hi']}"
            gap_sep = "-"
            if row.get("event_gap_separator_bin", "") != "":
                gap_sep = f"{row['event_gap_separator_lo']}-{row['event_gap_separator_hi']}"
            lines.append(
                f"| {row['source_probe']} | {row['time']} | {row['separator_call']} | "
                f"{row.get('event_gap_separator_call', '')} | {row['range']} | "
                f"{sep} | {gap_sep} | {row['root_to_event_points']} | "
                f"{row.get('path_consumed_pct', '')} | "
                f"{row['call']} |"
            )
        lines.append("")

    counts: dict[tuple[str, str], int] = {}
    for row in rows:
        key = (str(row["case_id"]), str(row.get("separator_call", "")))
        counts[key] = counts.get(key, 0) + 1
    lines.extend(["## Call Counts", ""])
    for case in CASES:
        lines.append(f"### {case.case_id}")
        for (case_id, call), count in sorted(counts.items()):
            if case_id == case.case_id:
                lines.append(f"- `{call}`: {count}")
        lines.append("")

    lines.extend(
        [
            "## Policy Read",
            "",
            "A local LVN should not authorize an add by itself. It is useful as an "
            "`AddModeEligible` context bit: root remains the risk anchor, the "
            "candidate must still pass stack/reclaim/reload gates, and the LVN "
            "acts as a poor-volume separator/falsifier between A and the new "
            "participation area.",
        ]
    )
    return "\n".join(lines)


def write_counts(path: Path, rows: list[dict[str, Any]]) -> None:
    counts: dict[tuple[str, str], int] = {}
    for row in rows:
        key = (str(row["case_id"]), str(row.get("separator_call", "")))
        counts[key] = counts.get(key, 0) + 1
    out = [
        {"case_id": case_id, "separator_call": call, "count": count}
        for (case_id, call), count in sorted(counts.items())
    ]
    write_csv(path, out)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--out-dir",
        default=str(REPO / "research" / "kahn" / "out" / "local-lvn-separator-20260830"),
    )
    args = parser.parse_args()
    out_dir = Path(args.out_dir)

    summaries, rows = collect_lvn_rows()
    write_csv(out_dir / "case_summary.csv", summaries)
    write_csv_union(out_dir / "local_lvn_rows.csv", rows)
    write_counts(out_dir / "call_counts.csv", rows)
    report = report_markdown(summaries, rows)
    (out_dir / "report.md").write_text(report, encoding="utf-8")
    print(report)


if __name__ == "__main__":
    main()
