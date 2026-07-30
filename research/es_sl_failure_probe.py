"""Probe tighter ES rail stop triggers after first rail interaction.

The hypothesis is that materially failed ES rails usually either:
- puncture and fail without a favorable escape attempt; or
- escape/repair first, then fail when price returns through the rail and does
  not re-enter the rail promptly.

This script tests adverse-breach + no-reentry stop candidates against the
synthetic ES contact table. It is research-only and uses trade prints as the
price path; contact timestamps in the source table are second resolution.
"""

from __future__ import annotations

import argparse
import bisect
import csv
import math
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from statistics import median
from zoneinfo import ZoneInfo

import polars as pl


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "research"))

from capture_loader import add_ny_ts, load_capture_window, tick_columns, us  # noqa: E402


NY = ZoneInfo("America/New_York")
TICK_SIZE = 0.25
BREACH_TICKS = (2, 4, 6, 8, 10)
HOLD_SECONDS = (0, 2, 5, 10)


@dataclass(frozen=True)
class TickTape:
    times: list[int]
    ticks: list[int]
    prices: list[float]

    def row_at_or_after(self, ts_us: int) -> tuple[int, int, float] | None:
        idx = bisect.bisect_left(self.times, ts_us)
        if idx >= len(self.times):
            return None
        return self.times[idx], self.ticks[idx], self.prices[idx]

    def slice_indices(self, start_us: int, end_us: int) -> tuple[int, int]:
        return bisect.bisect_left(self.times, start_us), bisect.bisect_right(self.times, end_us)


def parse_ts(value: str) -> datetime | None:
    if not value:
        return None
    return datetime.strptime(value, "%Y-%m-%d %H:%M:%S").replace(tzinfo=NY)


def parse_float(value: object) -> float | None:
    if value is None or value == "":
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def tick_key(price: float | str) -> int:
    return int(round(float(price) / TICK_SIZE))


def price(tick: int) -> float:
    return tick * TICK_SIZE


def side_sign(side: str) -> int:
    if side == "demand":
        return 1
    if side == "supply":
        return -1
    raise ValueError(f"unknown side {side}")


def adverse(tick: int, side: str, low_tick: int, high_tick: int, breach_ticks: int) -> bool:
    if side == "demand":
        return tick <= low_tick - breach_ticks
    return tick >= high_tick + breach_ticks


def favorable(tick: int, side: str, low_tick: int, high_tick: int, escape_ticks: int) -> bool:
    if side == "demand":
        return tick >= high_tick + escape_ticks
    return tick <= low_tick - escape_ticks


def inside(tick: int, low_tick: int, high_tick: int) -> bool:
    return low_tick <= tick <= high_tick


def load_contacts(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as f:
        return [
            row
            for row in csv.DictReader(f)
            if row.get("resolution") in ("HOLD", "FAIL") and row.get("resolution_ts")
        ]


def load_transitions(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def load_day_tape(symbol_dir: str, day: str) -> TickTape:
    d = datetime.fromisoformat(day).date()
    start = datetime(d.year, d.month, d.day, 9, 30, tzinfo=NY)
    end = datetime(d.year, d.month, d.day, 16, 5, tzinfo=NY)
    df = add_ny_ts(
        load_capture_window("ticks", symbol_dir, start, end, tick_columns())
    ).with_columns(((pl.col("price") / TICK_SIZE).round().cast(pl.Int64)).alias("price_tick"))
    return TickTape(
        times=[int(v) for v in df["timestamp_us"].to_list()],
        ticks=[int(v) for v in df["price_tick"].to_list()],
        prices=[float(v) for v in df["price"].to_list()],
    )


def first_favorable_escape(
    tape: TickTape,
    start_us: int,
    end_us: int,
    side: str,
    low_tick: int,
    high_tick: int,
    escape_ticks: int,
) -> tuple[int, int, float] | None:
    lo, hi = tape.slice_indices(start_us, end_us)
    for idx in range(lo, hi):
        if favorable(tape.ticks[idx], side, low_tick, high_tick, escape_ticks):
            return tape.times[idx], tape.ticks[idx], tape.prices[idx]
    return None


def first_adverse_no_reentry(
    tape: TickTape,
    start_us: int,
    end_us: int,
    side: str,
    low_tick: int,
    high_tick: int,
    breach_ticks: int,
    hold_sec: float,
) -> tuple[int, int, float, int, float] | None:
    lo, hi = tape.slice_indices(start_us, end_us)
    inside_times = [
        tape.times[idx]
        for idx in range(lo, hi)
        if inside(tape.ticks[idx], low_tick, high_tick)
    ]
    hold_us = int(hold_sec * 1_000_000)
    for idx in range(lo, hi):
        tick = tape.ticks[idx]
        if not adverse(tick, side, low_tick, high_tick, breach_ticks):
            continue
        breach_us = tape.times[idx]
        if hold_us > 0:
            j = bisect.bisect_right(inside_times, breach_us)
            if j < len(inside_times) and inside_times[j] <= breach_us + hold_us:
                continue
        trigger_us = breach_us + hold_us
        trigger_row = tape.row_at_or_after(trigger_us)
        if trigger_row is None:
            return breach_us, tick, tape.prices[idx], trigger_us, tape.prices[idx]
        _, _, trigger_price = trigger_row
        return breach_us, tick, tape.prices[idx], trigger_us, trigger_price
    return None


def any_reentry_after(
    tape: TickTape,
    start_us: int,
    end_us: int,
    low_tick: int,
    high_tick: int,
) -> bool:
    lo, hi = tape.slice_indices(start_us, end_us)
    return any(inside(tape.ticks[idx], low_tick, high_tick) for idx in range(lo, hi))


def transition_side(row: dict[str, str]) -> str:
    return row.get("side", "")


def unfavorable_rebuild(
    transitions: list[dict[str, str]],
    contact: dict[str, str],
    start_us: int,
    end_us: int,
    location_buffer_ticks: int,
) -> tuple[str, str] | tuple[None, None]:
    side = contact["side"]
    opposite = "supply" if side == "demand" else "demand"
    low_tick = tick_key(contact["band_low"])
    high_tick = tick_key(contact["band_high"])
    for row in transitions:
        ts = parse_ts(row.get("ts", ""))
        if ts is None:
            continue
        ts_us = us(ts)
        if ts_us < start_us or ts_us > end_us:
            continue
        if transition_side(row) != opposite:
            continue
        action = row.get("action", "")
        if action not in ("FORM", "OWNED", "CONSUMED", "HOLD", "TEST"):
            continue
        tr_low = tick_key(row["band_low"])
        tr_high = tick_key(row["band_high"])
        current_mid = parse_float(row.get("current_mid"))
        current_tick = tick_key(current_mid) if current_mid is not None else None
        if side == "demand":
            beyond = tr_high <= low_tick + location_buffer_ticks or (
                current_tick is not None and current_tick <= low_tick
            )
        else:
            beyond = tr_low >= high_tick - location_buffer_ticks or (
                current_tick is not None and current_tick >= high_tick
            )
        if beyond:
            return row.get("ts", ""), f"{action}:{row.get('band_id', '')}:{row.get('side', '')}:{row.get('band_low', '')}-{row.get('band_high', '')}"
    return None, None


def analyze_contact(
    contact: dict[str, str],
    tape: TickTape,
    transitions: list[dict[str, str]],
    escape_ticks: int,
    rebuild_buffer_ticks: int,
) -> dict[str, object]:
    contact_ts = parse_ts(contact["contact_ts"])
    resolution_ts = parse_ts(contact["resolution_ts"])
    if contact_ts is None or resolution_ts is None:
        raise ValueError("contact/resolution timestamp required")
    contact_us = us(contact_ts)
    resolution_us = us(resolution_ts)
    low_tick = tick_key(contact["band_low"])
    high_tick = tick_key(contact["band_high"])
    side = contact["side"]
    resolution_row = tape.row_at_or_after(resolution_us)
    official_price = resolution_row[2] if resolution_row else None
    escape = first_favorable_escape(
        tape, contact_us, resolution_us, side, low_tick, high_tick, escape_ticks
    )

    out: dict[str, object] = {
        "date": contact["date"],
        "contact_ts": contact["contact_ts"],
        "band_id": contact["band_id"],
        "side": side,
        "source": contact["source"],
        "cohort": contact["cohort"],
        "resolution": contact["resolution"],
        "resolution_ts": contact["resolution_ts"],
        "band_low": contact["band_low"],
        "band_high": contact["band_high"],
        "puncture_ticks": contact["puncture_ticks"],
        "official_price": official_price,
        "escape_ticks": escape_ticks,
        "first_escape_ts": ts_text(escape[0]) if escape else "",
        "first_escape_price": escape[2] if escape else None,
        "reentry_ts": contact.get("reentry_ts", ""),
        "reentry_band_id": contact.get("reentry_band_id", ""),
    }

    for breach_ticks in BREACH_TICKS:
        for hold_sec in HOLD_SECONDS:
            suffix = f"{breach_ticks}t_{int(hold_sec)}s"
            breach = first_adverse_no_reentry(
                tape,
                contact_us,
                resolution_us,
                side,
                low_tick,
                high_tick,
                breach_ticks,
                hold_sec,
            )
            if breach is None:
                out[f"trigger_ts_{suffix}"] = ""
                out[f"breach_ts_{suffix}"] = ""
                out[f"trigger_price_{suffix}"] = None
                out[f"trigger_before_resolution_{suffix}"] = False
                out[f"lead_sec_{suffix}"] = None
                out[f"saved_points_{suffix}"] = None
                out[f"repair_attempt_before_trigger_{suffix}"] = bool(escape)
                out[f"reentered_after_breach_{suffix}"] = None
                out[f"unfav_rebuild_ts_{suffix}"] = ""
                out[f"unfav_rebuild_{suffix}"] = ""
                continue

            breach_us, _, breach_price, trigger_us, trigger_price = breach
            before_resolution = trigger_us <= resolution_us
            lead_sec = (resolution_us - trigger_us) / 1_000_000 if before_resolution else None
            saved_points = None
            if before_resolution and official_price is not None:
                if side == "demand":
                    saved_points = trigger_price - official_price
                else:
                    saved_points = official_price - trigger_price
            had_escape_before = bool(escape and escape[0] < breach_us)
            reentered = any_reentry_after(tape, breach_us, resolution_us, low_tick, high_tick)
            rebuild_ts, rebuild_desc = unfavorable_rebuild(
                transitions,
                contact,
                breach_us,
                resolution_us + 60_000_000,
                rebuild_buffer_ticks,
            )

            out[f"trigger_ts_{suffix}"] = ts_text(trigger_us)
            out[f"breach_ts_{suffix}"] = ts_text(breach_us)
            out[f"breach_price_{suffix}"] = breach_price
            out[f"trigger_price_{suffix}"] = trigger_price
            out[f"trigger_before_resolution_{suffix}"] = before_resolution
            out[f"lead_sec_{suffix}"] = lead_sec
            out[f"saved_points_{suffix}"] = saved_points
            out[f"repair_attempt_before_trigger_{suffix}"] = had_escape_before
            out[f"reentered_after_breach_{suffix}"] = reentered
            out[f"unfav_rebuild_ts_{suffix}"] = rebuild_ts or ""
            out[f"unfav_rebuild_{suffix}"] = rebuild_desc or ""
    return out


def ts_text(ts_us: int) -> str:
    return datetime.fromtimestamp(ts_us / 1_000_000, tz=NY).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]


def num(value: object) -> float | None:
    if value is None or value == "":
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def med(rows: list[dict[str, object]], key: str) -> float | None:
    values = [v for row in rows if (v := num(row.get(key))) is not None]
    return median(values) if values else None


def pct(n: int, d: int) -> float | None:
    return n / d * 100.0 if d else None


def summarize_policy(rows: list[dict[str, object]], breach_ticks: int, hold_sec: int) -> dict[str, object]:
    suffix = f"{breach_ticks}t_{hold_sec}s"
    failed = [row for row in rows if row["resolution"] == "FAIL"]
    held = [row for row in rows if row["resolution"] == "HOLD"]
    held_puncture = [row for row in held if row["cohort"] == "HELD_PUNCTURE"]
    captured = [row for row in failed if row.get(f"trigger_before_resolution_{suffix}") is True]
    false_held = [row for row in held if row.get(f"trigger_before_resolution_{suffix}") is True]
    false_held_puncture = [
        row for row in held_puncture if row.get(f"trigger_before_resolution_{suffix}") is True
    ]
    no_escape = [row for row in captured if row.get(f"repair_attempt_before_trigger_{suffix}") is False]
    repair_failed = [row for row in captured if row.get(f"repair_attempt_before_trigger_{suffix}") is True]
    no_reentry = [row for row in captured if row.get(f"reentered_after_breach_{suffix}") is False]
    rebuild = [row for row in captured if row.get(f"unfav_rebuild_{suffix}")]
    return {
        "breach_ticks": breach_ticks,
        "hold_sec": hold_sec,
        "failed_n": len(failed),
        "captured": len(captured),
        "capture_pct": pct(len(captured), len(failed)),
        "no_escape_captured": len(no_escape),
        "repair_failed_captured": len(repair_failed),
        "no_reentry_to_resolution": len(no_reentry),
        "unfav_rebuild_seen": len(rebuild),
        "held_n": len(held),
        "false_held": len(false_held),
        "false_held_pct": pct(len(false_held), len(held)),
        "held_puncture_n": len(held_puncture),
        "false_held_puncture": len(false_held_puncture),
        "false_held_puncture_pct": pct(len(false_held_puncture), len(held_puncture)),
        "median_lead_sec": med(captured, f"lead_sec_{suffix}"),
        "median_saved_points": med(captured, f"saved_points_{suffix}"),
    }


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def fmt(value: object, places: int = 2) -> str:
    f = num(value)
    if f is None:
        return "n/a"
    return f"{f:.{places}f}"


def md_table(rows: list[dict[str, object]], fields: list[str]) -> list[str]:
    lines = [
        "| " + " | ".join(fields) + " |",
        "| " + " | ".join("---" for _ in fields) + " |",
    ]
    for row in rows:
        cells = []
        for field in fields:
            value = row.get(field)
            cells.append(fmt(value) if isinstance(value, float) else str(value))
        lines.append("| " + " | ".join(cells) + " |")
    return lines


def selected_rows(rows: list[dict[str, object]], suffix: str) -> list[dict[str, object]]:
    selected = []
    for row in rows:
        if row["resolution"] != "FAIL":
            continue
        ts = str(row["contact_ts"])
        if (
            ts.startswith("2026-07-29 14:")
            or ts.startswith("2026-07-29 15:")
            or ts.startswith("2026-07-28 10:")
            or ts.startswith("2026-07-28 11:")
        ):
            selected.append(
                {
                    "contact_ts": row["contact_ts"],
                    "band_id": row["band_id"],
                    "side": row["side"],
                    "cohort": row["cohort"],
                    "band": f"{row['band_low']}-{row['band_high']}",
                    "resolution_ts": row["resolution_ts"],
                    "first_escape_ts": row["first_escape_ts"],
                    "breach_ts": row.get(f"breach_ts_{suffix}", ""),
                    "trigger_ts": row.get(f"trigger_ts_{suffix}", ""),
                    "lead_sec": row.get(f"lead_sec_{suffix}"),
                    "saved_points": row.get(f"saved_points_{suffix}"),
                    "repair_before_trigger": row.get(f"repair_attempt_before_trigger_{suffix}"),
                    "reentered_after_breach": row.get(f"reentered_after_breach_{suffix}"),
                    "unfav_rebuild": row.get(f"unfav_rebuild_{suffix}", ""),
                }
            )
    return selected[:28]


def write_findings(path: Path, rows: list[dict[str, object]], summary: list[dict[str, object]], default_suffix: str) -> None:
    failed = [row for row in rows if row["resolution"] == "FAIL"]
    fields = [
        "breach_ticks",
        "hold_sec",
        "captured",
        "capture_pct",
        "no_escape_captured",
        "repair_failed_captured",
        "false_held",
        "false_held_pct",
        "false_held_puncture",
        "false_held_puncture_pct",
        "median_lead_sec",
        "median_saved_points",
        "unfav_rebuild_seen",
    ]
    top = [
        row
        for row in summary
        if row["hold_sec"] in (2, 5, 10) and row["breach_ticks"] in (2, 4, 6, 8)
    ]
    top.sort(
        key=lambda row: (
            float(row["false_held_pct"] or 0.0),
            -float(row["capture_pct"] or 0.0),
            row["hold_sec"],
            row["breach_ticks"],
        )
    )
    lines = [
        "# ES SL Failure Probe",
        "",
        "Research-only stop candidates using ES synthetic rail contacts and MarketRecorder trade prints.",
        "A trigger is adverse breach beyond the rail followed by no trade re-entry into the rail for the confirmation window.",
        "",
        f"- Contacts analyzed: {len(rows)} total, {len(failed)} failed.",
        f"- Default row shown below: `{default_suffix}` means adverse breach ticks plus no-reentry seconds.",
        "",
        "## Policy Grid",
    ]
    lines.extend(md_table(top, fields))
    default_row = next((row for row in summary if f"{row['breach_ticks']}t_{row['hold_sec']}s" == default_suffix), None)
    if default_row:
        lines.extend(
            [
                "",
                "## Default Read",
                (
                    f"- `{default_suffix}` captured {default_row['captured']}/{default_row['failed_n']} failures "
                    f"({fmt(default_row['capture_pct'])}%) with median lead {fmt(default_row['median_lead_sec'])}s "
                    f"and median saved adverse movement {fmt(default_row['median_saved_points'])} points."
                ),
                (
                    f"- It false-triggered {default_row['false_held']}/{default_row['held_n']} held contacts "
                    f"({fmt(default_row['false_held_pct'])}%), including "
                    f"{default_row['false_held_puncture']}/{default_row['held_puncture_n']} held-puncture contacts "
                    f"({fmt(default_row['false_held_puncture_pct'])}%)."
                ),
                (
                    f"- Captured failures split into {default_row['no_escape_captured']} no-escape cases and "
                    f"{default_row['repair_failed_captured']} repair-before-trigger cases."
                ),
                "",
                "This supports a tighter semantic stop only after an adverse breach holds outside the rail. It does not support a resting stop at the rail edge because held punctures are common.",
            ]
        )
    lines.extend(["", "## Selected Failed Rows"])
    lines.extend(
        md_table(
            selected_rows(rows, default_suffix),
            [
                "contact_ts",
                "band_id",
                "side",
                "cohort",
                "band",
                "resolution_ts",
                "first_escape_ts",
                "breach_ts",
                "trigger_ts",
                "lead_sec",
                "saved_points",
                "repair_before_trigger",
                "reentered_after_breach",
                "unfav_rebuild",
            ],
        )
    )
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--contacts",
        type=Path,
        default=ROOT / "research" / "out" / "es_band_contact_20260728_20260729" / "contacts.csv",
    )
    parser.add_argument(
        "--transitions",
        type=Path,
        default=ROOT / "research" / "out" / "es_band_contact_20260728_20260729" / "transitions.csv",
    )
    parser.add_argument("--symbol-dir", default="ESU6")
    parser.add_argument("--escape-ticks", type=int, default=4)
    parser.add_argument("--rebuild-buffer-ticks", type=int, default=2)
    parser.add_argument("--default-breach-ticks", type=int, default=4)
    parser.add_argument("--default-hold-sec", type=int, default=5)
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=ROOT / "research" / "out" / "es_sl_failure_20260728_20260729",
    )
    args = parser.parse_args()

    contacts = load_contacts(args.contacts)
    transitions_all = load_transitions(args.transitions)
    by_day_transitions: dict[str, list[dict[str, str]]] = defaultdict(list)
    for tr in transitions_all:
        by_day_transitions[tr["date"]].append(tr)

    tapes = {day: load_day_tape(args.symbol_dir, day) for day in sorted({row["date"] for row in contacts})}
    rows = [
        analyze_contact(
            contact,
            tapes[contact["date"]],
            by_day_transitions[contact["date"]],
            args.escape_ticks,
            args.rebuild_buffer_ticks,
        )
        for contact in contacts
    ]
    summary = [
        summarize_policy(rows, breach_ticks, hold_sec)
        for breach_ticks in BREACH_TICKS
        for hold_sec in HOLD_SECONDS
    ]

    args.out_dir.mkdir(parents=True, exist_ok=True)
    write_csv(args.out_dir / "sl_contact_triggers.csv", rows)
    write_csv(args.out_dir / "sl_policy_grid.csv", summary)
    default_suffix = f"{args.default_breach_ticks}t_{args.default_hold_sec}s"
    write_findings(args.out_dir / "findings.md", rows, summary, default_suffix)
    print(f"wrote {len(rows)} contact rows and {len(summary)} policies to {args.out_dir}")


if __name__ == "__main__":
    main()
