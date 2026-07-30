"""Curated ES segment probe for synthetic LevelLedger bands.

This is a research-only bridge between the broad ES band-contact artifact and
the direct-conversion phase work. It keeps the user's selected trade windows
separate and reports price path, RTH VWAP/VPOC-at-decision, aligned rail
contacts, and opposing rail failures.
"""

from __future__ import annotations

import csv
import datetime as dt
import math
import sys
from dataclasses import dataclass
from pathlib import Path
from statistics import median
from zoneinfo import ZoneInfo

import polars as pl


ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "research" / "out" / "es_segment_probe_20260728_20260729"
BAND_DIR = ROOT / "research" / "out" / "es_band_contact_20260728_20260729"
sys.path.insert(0, str(ROOT / "research"))

from capture_loader import add_ny_ts, load_capture_window  # noqa: E402


NY = ZoneInfo("America/New_York")
TICK = 0.25


@dataclass(frozen=True)
class Segment:
    key: str
    date: str
    side: str
    context_start: str
    decision_start: str
    end: str
    target: float | None = None
    note: str = ""


SEGMENTS = [
    Segment(
        "20260729_short_1000",
        "2026-07-29",
        "short",
        "09:45:00",
        "10:00:00",
        "10:45:00",
        note="Directive short; context starts 09:45, expected end around 10:40-10:45.",
    ),
    Segment(
        "20260729_short_1045",
        "2026-07-29",
        "short",
        "10:45:00",
        "10:45:00",
        "11:30:00",
        note="Possible second short during VPOC-formation phase.",
    ),
    Segment(
        "20260729_long_1205_repair",
        "2026-07-29",
        "long",
        "12:05:00",
        "12:05:00",
        "12:45:00",
        target=7412.0,
        note="Repair long idea after 12:05, target around VWAP.",
    ),
    Segment(
        "20260729_long_1430_fomc",
        "2026-07-29",
        "long",
        "14:20:00",
        "14:30:00",
        "15:05:00",
        target=7485.5,
        note="Post-FOMC long; user confirmed direct conversion around 7419-7425.",
    ),
    Segment(
        "20260729_short_1510",
        "2026-07-29",
        "short",
        "15:10:00",
        "15:10:00",
        "16:00:00",
        target=7371.0,
        note="Research-only short assumption after the long exit; target day's low area.",
    ),
    Segment(
        "20260728_long_1000",
        "2026-07-28",
        "long",
        "10:00:00",
        "10:00:00",
        "10:50:00",
        note="Post-10:00 long; initial drive short assumed not issued.",
    ),
    Segment(
        "20260728_long_1100",
        "2026-07-28",
        "long",
        "11:00:00",
        "11:00:00",
        "11:45:00",
        note="Second post-11:00 long.",
    ),
]


def parse_ts(day: str, clock: str) -> dt.datetime:
    h, m, s = (int(part) for part in clock.split(":"))
    d = dt.date.fromisoformat(day)
    return dt.datetime(d.year, d.month, d.day, h, m, s, tzinfo=NY)


def parse_csv_ts(value: str) -> dt.datetime | None:
    if not value:
        return None
    return dt.datetime.strptime(value, "%Y-%m-%d %H:%M:%S").replace(tzinfo=NY)


def parse_float(value: str) -> float | None:
    if value == "" or value is None:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def fmt_num(value: float | None, places: int = 2) -> str:
    if value is None or not math.isfinite(value):
        return ""
    return f"{value:.{places}f}"


def fmt_ts(value: dt.datetime | None) -> str:
    if value is None:
        return ""
    return value.strftime("%H:%M:%S")


def load_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def side_name(segment_side: str) -> str:
    return "demand" if segment_side == "long" else "supply"


def favorable_predicate(side: str, price_col: str, target: float) -> pl.Expr:
    if side == "long":
        return pl.col(price_col) >= target
    return pl.col(price_col) <= target


def first_price_row(df: pl.DataFrame, *, at_or_after: dt.datetime) -> dict | None:
    ts_us = int(at_or_after.timestamp() * 1_000_000)
    rows = df.filter(pl.col("timestamp_us") >= ts_us).head(1).to_dicts()
    return rows[0] if rows else None


def extrema(df: pl.DataFrame, price_col: str) -> tuple[float | None, dt.datetime | None, float | None, dt.datetime | None]:
    if df.is_empty():
        return None, None, None, None
    low_row = df.sort(price_col).head(1).to_dicts()[0]
    high_row = df.sort(price_col, descending=True).head(1).to_dicts()[0]
    return low_row[price_col], low_row["ts"], high_row[price_col], high_row["ts"]


def volume_profile(df: pl.DataFrame) -> tuple[float | None, float | None]:
    if df.is_empty():
        return None, None
    valid = df.filter((pl.col("size") > 0) & pl.col("price").is_not_null())
    if valid.is_empty():
        return None, None
    total_vol = valid["size"].sum()
    vwap = (valid["price"] * valid["size"]).sum() / total_vol if total_vol else None
    grouped = (
        valid.with_columns(((pl.col("price") / TICK).round() * TICK).alias("tick_price"))
        .group_by("tick_price")
        .agg(pl.col("size").sum().alias("vol"))
        .sort(["vol", "tick_price"], descending=[True, False])
    )
    vpoc = grouped.head(1)["tick_price"][0] if grouped.height else None
    return float(vwap) if vwap is not None else None, float(vpoc) if vpoc is not None else None


def summarize_tick_window(segment: Segment) -> dict[str, object]:
    context_start = parse_ts(segment.date, segment.context_start)
    decision_start = parse_ts(segment.date, segment.decision_start)
    end = parse_ts(segment.date, segment.end)
    rth_start = parse_ts(segment.date, "09:30:00")

    ticks = add_ny_ts(
        load_capture_window(
            "ticks",
            "ESU6",
            context_start,
            end,
            ["timestamp_us", "price", "size", "aggressor_sign"],
        )
    )
    decision_ticks = ticks.filter(
        (pl.col("ts") >= decision_start) & (pl.col("ts") < end)
    )
    pre_decision_ticks = add_ny_ts(
        load_capture_window(
            "ticks",
            "ESU6",
            rth_start,
            decision_start,
            ["timestamp_us", "price", "size", "aggressor_sign"],
        )
    )
    pre_end_ticks = add_ny_ts(
        load_capture_window(
            "ticks",
            "ESU6",
            rth_start,
            end,
            ["timestamp_us", "price", "size", "aggressor_sign"],
        )
    )

    first = first_price_row(ticks, at_or_after=decision_start)
    last = decision_ticks.tail(1).to_dicts()[0] if not decision_ticks.is_empty() else None
    entry = float(first["price"]) if first else None
    close = float(last["price"]) if last else None
    low, low_ts, high, high_ts = extrema(decision_ticks, "price")
    volume = float(decision_ticks["size"].sum()) if not decision_ticks.is_empty() else 0.0
    signed_delta = float((decision_ticks["size"] * decision_ticks["aggressor_sign"]).sum()) if not decision_ticks.is_empty() else 0.0

    mfe_ticks = mae_ticks = None
    if entry is not None and low is not None and high is not None:
        if segment.side == "long":
            mfe_ticks = (high - entry) / TICK
            mae_ticks = (entry - low) / TICK
        else:
            mfe_ticks = (entry - low) / TICK
            mae_ticks = (high - entry) / TICK

    target_ts = None
    if segment.target is not None and not decision_ticks.is_empty():
        hit = decision_ticks.filter(favorable_predicate(segment.side, "price", segment.target)).head(1)
        if not hit.is_empty():
            target_ts = hit["ts"][0]

    vwap_start, vpoc_start = volume_profile(pre_decision_ticks)
    vwap_end, vpoc_end = volume_profile(pre_end_ticks)
    window_vwap, window_vpoc = volume_profile(decision_ticks)

    return {
        "key": segment.key,
        "entry_ref": entry,
        "close": close,
        "low": low,
        "low_ts": low_ts,
        "high": high,
        "high_ts": high_ts,
        "mfe_ticks": mfe_ticks,
        "mae_ticks": mae_ticks,
        "target": segment.target,
        "target_ts": target_ts,
        "volume": volume,
        "signed_delta": signed_delta,
        "rth_vwap_at_decision": vwap_start,
        "rth_vpoc_at_decision": vpoc_start,
        "rth_vwap_at_end": vwap_end,
        "rth_vpoc_at_end": vpoc_end,
        "window_vwap": window_vwap,
        "window_vpoc": window_vpoc,
    }


def contact_in_window(row: dict[str, str], segment: Segment, field: str = "contact_ts") -> bool:
    ts = parse_csv_ts(row.get(field, ""))
    if ts is None:
        return False
    return parse_ts(segment.date, segment.context_start) <= ts <= parse_ts(segment.date, segment.end)


def transition_in_window(row: dict[str, str], segment: Segment) -> bool:
    ts = parse_csv_ts(row.get("ts", ""))
    if ts is None:
        return False
    return parse_ts(segment.date, segment.context_start) <= ts <= parse_ts(segment.date, segment.end)


def row_side_aligned(row: dict[str, str], segment: Segment) -> bool:
    return row.get("side") == side_name(segment.side)


def row_side_opposing(row: dict[str, str], segment: Segment) -> bool:
    return row.get("side") and row.get("side") != side_name(segment.side)


def summarize_contacts(segment: Segment, contacts: list[dict[str, str]], transitions: list[dict[str, str]]) -> dict[str, object]:
    window_contacts = [
        row
        for row in contacts
        if row["date"] == segment.date and contact_in_window(row, segment)
    ]
    aligned = [row for row in window_contacts if row_side_aligned(row, segment)]
    opposing = [row for row in window_contacts if row_side_opposing(row, segment)]
    opposing_fails = [row for row in opposing if row.get("resolution") == "FAIL"]

    window_transitions = [
        row
        for row in transitions
        if row["date"] == segment.date and transition_in_window(row, segment)
    ]
    conversions = [
        row
        for row in window_transitions
        if row.get("action") == "CONSUMED" and row_side_aligned(row, segment)
    ]
    aligned_owns = [
        row
        for row in window_transitions
        if row.get("action") in ("OWNED", "CONSUMED") and row_side_aligned(row, segment)
    ]
    aligned_fails = [
        row
        for row in window_transitions
        if row.get("action") == "FAIL" and row_side_aligned(row, segment)
    ]
    opposing_fail_transitions = [
        row
        for row in window_transitions
        if row.get("action") == "FAIL" and row_side_opposing(row, segment)
    ]

    def contact_sort_key(row: dict[str, str]) -> dt.datetime:
        return parse_csv_ts(row.get("contact_ts", "")) or dt.datetime.max.replace(tzinfo=NY)

    def transition_sort_key(row: dict[str, str]) -> dt.datetime:
        return parse_csv_ts(row.get("ts", "")) or dt.datetime.max.replace(tzinfo=NY)

    aligned.sort(key=contact_sort_key)
    opposing_fails.sort(key=contact_sort_key)
    conversions.sort(key=transition_sort_key)
    aligned_owns.sort(key=transition_sort_key)
    aligned_fails.sort(key=transition_sort_key)
    opposing_fail_transitions.sort(key=transition_sort_key)

    ratios = [
        parse_float(row.get("exit_entry_speed_ratio", ""))
        for row in aligned
        if parse_float(row.get("exit_entry_speed_ratio", "")) is not None
    ]
    punctures = [
        parse_float(row.get("puncture_ticks", ""))
        for row in aligned
        if parse_float(row.get("puncture_ticks", "")) is not None
    ]
    prox_costs = [
        parse_float(row.get("proximity_cost_ticks", ""))
        for row in aligned
        if parse_float(row.get("proximity_cost_ticks", "")) is not None
    ]

    return {
        "contacts": window_contacts,
        "aligned_contacts": aligned,
        "opposing_fail_contacts": opposing_fails,
        "aligned_conversions": conversions,
        "aligned_owns": aligned_owns,
        "aligned_fails": aligned_fails,
        "opposing_fail_transitions": opposing_fail_transitions,
        "aligned_contact_count": len(aligned),
        "aligned_holds": sum(1 for row in aligned if row.get("resolution") == "HOLD"),
        "aligned_fails_count": sum(1 for row in aligned if row.get("resolution") == "FAIL"),
        "aligned_median_speed_ratio": median(ratios) if ratios else None,
        "aligned_median_puncture_ticks": median(punctures) if punctures else None,
        "aligned_median_proximity_cost_ticks": median(prox_costs) if prox_costs else None,
    }


def contact_line(row: dict[str, str]) -> str:
    return (
        f"| {row.get('contact_ts', '')[-8:]} | {row.get('band_id', '')} | "
        f"{row.get('side', '')} | {row.get('source', '')} | "
        f"{row.get('band_low', '')}-{row.get('band_high', '')} | "
        f"{row.get('cohort', '')} | {row.get('resolution', '')} | "
        f"{row.get('proximity_cost_ticks', '')} | {row.get('puncture_ticks', '')} | "
        f"{row.get('entry_speed_ticks_sec', '')} | {row.get('exit_speed_ticks_sec', '')} | "
        f"{row.get('exit_entry_speed_ratio', '')} |"
    )


def transition_line(row: dict[str, str]) -> str:
    return (
        f"| {row.get('ts', '')[-8:]} | {row.get('action', '')} | {row.get('band_id', '')} | "
        f"{row.get('side', '')} | {row.get('source', '')} | "
        f"{row.get('band_low', '')}-{row.get('band_high', '')} | "
        f"{row.get('current_mid', '')} | {row.get('note', '')} |"
    )


def write_segment_csv(path: Path, segment: Segment, contacts_summary: dict[str, object]) -> None:
    rows = contacts_summary["aligned_contacts"] + contacts_summary["opposing_fail_contacts"]
    fieldnames = [
        "segment",
        "role",
        "contact_ts",
        "band_id",
        "side",
        "source",
        "cohort",
        "resolution",
        "band_low",
        "band_high",
        "prox_ts",
        "proximity_cost_ticks",
        "puncture_ticks",
        "entry_speed_ticks_sec",
        "exit_speed_ticks_sec",
        "exit_entry_speed_ratio",
        "reentry_ts",
    ]
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            role = "aligned" if row_side_aligned(row, segment) else "opposing_fail"
            writer.writerow(
                {
                    "segment": segment.key,
                    "role": role,
                    **{name: row.get(name, "") for name in fieldnames if name not in ("segment", "role")},
                }
            )


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    contacts = load_rows(BAND_DIR / "contacts.csv")
    transitions = load_rows(BAND_DIR / "transitions.csv")

    lines = [
        "# ES Curated Segment Probe",
        "",
        "Inputs: ESU6 MarketRecorder ticks plus synthetic LevelLedger band/contact artifacts.",
        "Times are America/New_York. Proximity cost is ticks from first proximity to contact in the existing band probe.",
        "",
    ]

    summary_rows: list[dict[str, object]] = []

    for segment in SEGMENTS:
        tick_summary = summarize_tick_window(segment)
        contact_summary = summarize_contacts(segment, contacts, transitions)

        summary_rows.append(
            {
                "segment": segment.key,
                "date": segment.date,
                "side": segment.side,
                "context_start": segment.context_start,
                "decision_start": segment.decision_start,
                "end": segment.end,
                **tick_summary,
                **{
                    k: v
                    for k, v in contact_summary.items()
                    if k
                    in (
                        "aligned_contact_count",
                        "aligned_holds",
                        "aligned_fails_count",
                        "aligned_median_speed_ratio",
                        "aligned_median_puncture_ticks",
                        "aligned_median_proximity_cost_ticks",
                    )
                },
            }
        )

        lines.extend(
            [
                f"## {segment.key}",
                "",
                f"- Directive side: {segment.side}; context {segment.context_start}-{segment.end}, decision {segment.decision_start}.",
                f"- Note: {segment.note}",
                (
                    f"- Price path from decision: entry_ref {fmt_num(tick_summary['entry_ref'])}, "
                    f"low {fmt_num(tick_summary['low'])} at {fmt_ts(tick_summary['low_ts'])}, "
                    f"high {fmt_num(tick_summary['high'])} at {fmt_ts(tick_summary['high_ts'])}, "
                    f"close {fmt_num(tick_summary['close'])}."
                ),
                (
                    f"- MFE/MAE from entry_ref: {fmt_num(tick_summary['mfe_ticks'], 1)} / "
                    f"{fmt_num(tick_summary['mae_ticks'], 1)} ticks."
                ),
                (
                    f"- RTH VWAP/VPOC at decision: {fmt_num(tick_summary['rth_vwap_at_decision'])} / "
                    f"{fmt_num(tick_summary['rth_vpoc_at_decision'])}; "
                    f"at end: {fmt_num(tick_summary['rth_vwap_at_end'])} / {fmt_num(tick_summary['rth_vpoc_at_end'])}."
                ),
                (
                    f"- Window VWAP/VPOC and tape: {fmt_num(tick_summary['window_vwap'])} / "
                    f"{fmt_num(tick_summary['window_vpoc'])}; volume {fmt_num(tick_summary['volume'], 0)}, "
                    f"signed delta {fmt_num(tick_summary['signed_delta'], 0)}."
                ),
            ]
        )

        if segment.target is not None:
            target_status = fmt_ts(tick_summary["target_ts"]) or "not hit"
            lines.append(f"- Target {fmt_num(segment.target)}: {target_status}.")

        lines.extend(
            [
                (
                    f"- Aligned contacts: {contact_summary['aligned_contact_count']} "
                    f"({contact_summary['aligned_holds']} hold, {contact_summary['aligned_fails_count']} fail); "
                    f"median proximity cost {fmt_num(contact_summary['aligned_median_proximity_cost_ticks'], 1)}t, "
                    f"median puncture {fmt_num(contact_summary['aligned_median_puncture_ticks'], 1)}t, "
                    f"median exit/entry speed {fmt_num(contact_summary['aligned_median_speed_ratio'], 2)}."
                ),
                "",
            ]
        )

        if contact_summary["aligned_conversions"]:
            lines.extend(
                [
                    "Aligned direct-conversion/consumed transitions:",
                    "",
                    "| time | action | band | side | source | band | mid | note |",
                    "|---:|---|---:|---|---|---:|---:|---|",
                ]
            )
            for row in contact_summary["aligned_conversions"][:8]:
                lines.append(transition_line(row))
            lines.append("")

        if contact_summary["aligned_contacts"]:
            lines.extend(
                [
                    "Aligned rail contacts:",
                    "",
                    "| contact | band | side | source | band | cohort | res | prox_cost_t | puncture_t | entry_tps | exit_tps | speed_ratio |",
                    "|---:|---:|---|---|---:|---|---|---:|---:|---:|---:|---:|",
                ]
            )
            for row in contact_summary["aligned_contacts"][:12]:
                lines.append(contact_line(row))
            lines.append("")

        if contact_summary["opposing_fail_transitions"]:
            lines.extend(
                [
                    "Opposing rail failures in window:",
                    "",
                    "| time | action | band | side | source | band | mid | note |",
                    "|---:|---|---:|---|---|---:|---:|---|",
                ]
            )
            for row in contact_summary["opposing_fail_transitions"][:10]:
                lines.append(transition_line(row))
            lines.append("")

        write_segment_csv(OUT_DIR / f"{segment.key}_contacts.csv", segment, contact_summary)

    summary_path = OUT_DIR / "summary.csv"
    with summary_path.open("w", newline="", encoding="utf-8") as f:
        fieldnames = list(summary_rows[0].keys())
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in summary_rows:
            out = {}
            for key, value in row.items():
                if isinstance(value, dt.datetime):
                    out[key] = value.strftime("%Y-%m-%d %H:%M:%S")
                else:
                    out[key] = value
            writer.writerow(out)

    report_path = OUT_DIR / "findings.md"
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {report_path}")
    print(f"Wrote {summary_path}")


if __name__ == "__main__":
    main()
