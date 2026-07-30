"""Mechanism probe for ES rail interactions.

This complements ``es_segment_probe.py`` by looking beneath the contact
outcome: aggressor volume in and around the rail, simple footprint imbalance,
and net support-side reload/pull from canonical snapshots.

It deliberately does not replay raw book-event deltas. MarketRecorder raw L2
events require validity handling against snapshots; this first pass uses the
snapshot stream as the conservative book truth.
"""

from __future__ import annotations

import csv
import datetime as dt
import math
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from statistics import median
from zoneinfo import ZoneInfo

import polars as pl


ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "research" / "out" / "es_rail_mechanism_20260728_20260729"
BAND_DIR = ROOT / "research" / "out" / "es_band_contact_20260728_20260729"
sys.path.insert(0, str(ROOT / "research"))

from capture_loader import add_ny_ts, load_capture_window, snapshot_columns  # noqa: E402


NY = ZoneInfo("America/New_York")
TICK = 0.25
LEVELS = 30


@dataclass
class DayData:
    ticks: pl.DataFrame
    snapshots: pl.DataFrame


def parse_ts(value: str) -> dt.datetime | None:
    if not value:
        return None
    return dt.datetime.strptime(value, "%Y-%m-%d %H:%M:%S").replace(tzinfo=NY)


def parse_float(value: str) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except ValueError:
        return None


def tick_key(price: float) -> int:
    return int(round(price / TICK))


def us(ts: dt.datetime) -> int:
    return int(ts.timestamp() * 1_000_000)


def fmt(value: float | int | None, places: int = 2) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and not math.isfinite(value):
        return ""
    return f"{value:.{places}f}" if isinstance(value, float) else str(value)


def fmt_ts(value: dt.datetime | None) -> str:
    return "" if value is None else value.strftime("%H:%M:%S")


def read_contacts() -> list[dict[str, str]]:
    with (BAND_DIR / "contacts.csv").open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def load_day(day: str) -> DayData:
    d = dt.date.fromisoformat(day)
    start = dt.datetime(d.year, d.month, d.day, 9, 30, tzinfo=NY)
    end = dt.datetime(d.year, d.month, d.day, 16, 5, tzinfo=NY)
    ticks = add_ny_ts(
        load_capture_window(
            "ticks",
            "ESU6",
            start,
            end,
            ["timestamp_us", "price", "size", "aggressor_sign"],
        )
    ).with_columns(((pl.col("price") / TICK).round().cast(pl.Int64)).alias("price_tick"))
    snapshots = add_ny_ts(
        load_capture_window("snapshots", "ESU6", start, end, snapshot_columns(LEVELS))
    )
    return DayData(ticks=ticks, snapshots=snapshots)


def side_params(side: str) -> tuple[int, str, str]:
    if side == "demand":
        return -1, "bid", "ask"
    if side == "supply":
        return 1, "ask", "bid"
    raise ValueError(f"unknown side {side}")


def tick_window(side: str, low_tick: int, high_tick: int, buffer_ticks: int = 2) -> tuple[int, int]:
    if side == "demand":
        return low_tick - buffer_ticks, high_tick
    return low_tick, high_tick + buffer_ticks


def filter_ticks(
    ticks: pl.DataFrame,
    start: dt.datetime,
    end: dt.datetime,
    low_tick: int,
    high_tick: int,
) -> pl.DataFrame:
    return ticks.filter(
        (pl.col("timestamp_us") >= us(start))
        & (pl.col("timestamp_us") < us(end))
        & (pl.col("price_tick") >= low_tick)
        & (pl.col("price_tick") <= high_tick)
    )


def tick_stats(df: pl.DataFrame, side: str) -> dict[str, float]:
    adverse_sign, _, _ = side_params(side)
    favorable_sign = -adverse_sign
    if df.is_empty():
        return {
            "vol": 0.0,
            "signed_delta": 0.0,
            "aligned_delta": 0.0,
            "adverse_vol": 0.0,
            "favorable_vol": 0.0,
            "adverse_share": 0.0,
            "favorable_share": 0.0,
            "adverse_imbalance_max": 0.0,
            "favorable_imbalance_max": 0.0,
        }

    vol = float(df["size"].sum())
    signed_delta = float((df["size"] * df["aggressor_sign"]).sum())
    aligned_delta = signed_delta if side == "demand" else -signed_delta
    adverse_vol = float(df.filter(pl.col("aggressor_sign") == adverse_sign)["size"].sum())
    favorable_vol = float(df.filter(pl.col("aggressor_sign") == favorable_sign)["size"].sum())
    denom = adverse_vol + favorable_vol

    by_price = (
        df.group_by(["price_tick", "aggressor_sign"])
        .agg(pl.col("size").sum().alias("vol"))
        .to_dicts()
    )
    volumes: dict[int, dict[int, float]] = defaultdict(lambda: {adverse_sign: 0.0, favorable_sign: 0.0})
    for row in by_price:
        volumes[int(row["price_tick"])][int(row["aggressor_sign"])] = float(row["vol"])
    adverse_imbalance = 0.0
    favorable_imbalance = 0.0
    for bucket in volumes.values():
        adverse_imbalance = max(adverse_imbalance, bucket[adverse_sign] / (bucket[favorable_sign] + 1.0))
        favorable_imbalance = max(favorable_imbalance, bucket[favorable_sign] / (bucket[adverse_sign] + 1.0))

    return {
        "vol": vol,
        "signed_delta": signed_delta,
        "aligned_delta": aligned_delta,
        "adverse_vol": adverse_vol,
        "favorable_vol": favorable_vol,
        "adverse_share": adverse_vol / denom if denom else 0.0,
        "favorable_share": favorable_vol / denom if denom else 0.0,
        "adverse_imbalance_max": adverse_imbalance,
        "favorable_imbalance_max": favorable_imbalance,
    }


def nearest_snapshot(snapshots: pl.DataFrame, ts: dt.datetime) -> dict | None:
    rows = snapshots.filter(pl.col("timestamp_us") <= us(ts)).tail(1).to_dicts()
    return rows[0] if rows else None


def side_size(row: dict | None, book_side: str, low_tick: int, high_tick: int) -> float | None:
    if row is None:
        return None
    total = 0.0
    ref_tick = int(row["ref_tick"])
    observed_ticks: list[int] = []
    for i in range(LEVELS):
        offset = row.get(f"{book_side}_offset_{i}")
        size = row.get(f"{book_side}_size_{i}")
        if offset is None or size is None:
            continue
        level_tick = ref_tick + int(offset)
        observed_ticks.append(level_tick)
        if low_tick <= level_tick <= high_tick:
            total += float(size)
    if not observed_ticks:
        return None
    if high_tick < min(observed_ticks) or low_tick > max(observed_ticks):
        return None
    return total


def mechanism_hint(row: dict[str, float | str | int | None]) -> str:
    resolution = str(row["resolution"])
    support_post_change = row.get("support_change_post")
    support_entry_change = row.get("support_change_entry")
    support_post_change = None if support_post_change is None else float(support_post_change)
    support_entry_change = None if support_entry_change is None else float(support_entry_change)
    post_fav_share = float(row.get("escape_favorable_share") or row.get("post_favorable_share") or 0.0)
    entry_adv_share = float(row.get("approach_adverse_share") or row.get("entry_adverse_share") or 0.0)
    failed_reentry = row.get("cohort") == "FAILED_REENTRY"

    if resolution == "HOLD" and post_fav_share >= 0.58 and support_post_change is not None and support_post_change >= 0:
        return "reload_plus_favorable_escape"
    if resolution == "HOLD" and post_fav_share >= 0.58:
        return "favorable_escape_after_test"
    if (
        resolution == "HOLD"
        and entry_adv_share >= 0.60
        and support_entry_change is not None
        and support_entry_change >= -10
    ):
        return "absorbed_test_no_net_pull"
    if resolution == "FAIL" and failed_reentry:
        return "reentry_without_reclaim"
    if resolution == "FAIL" and support_post_change is not None and support_post_change < 0 and post_fav_share < 0.45:
        return "support_depletion_or_no_repair"
    return "mixed"


def analyze_contact(contact: dict[str, str], data: DayData) -> dict[str, object] | None:
    contact_ts = parse_ts(contact["contact_ts"])
    resolution_ts = parse_ts(contact["resolution_ts"])
    if contact_ts is None or resolution_ts is None:
        return None

    side = contact["side"]
    low = parse_float(contact["band_low"])
    high = parse_float(contact["band_high"])
    if low is None or high is None:
        return None

    low_tick = tick_key(low)
    high_tick = tick_key(high)
    near_low_tick, near_high_tick = tick_window(side, low_tick, high_tick, 2)
    adverse_sign, support_side, opposing_side = side_params(side)

    prox_ts = parse_ts(contact.get("prox_ts", ""))
    capped_approach_start = contact_ts - dt.timedelta(seconds=120)
    if prox_ts is not None:
        entry_start = max(prox_ts, capped_approach_start)
    else:
        entry_start = capped_approach_start
    near_start = contact_ts - dt.timedelta(seconds=30)
    post_end = min(resolution_ts, contact_ts + dt.timedelta(seconds=30))
    if post_end <= contact_ts:
        post_end = contact_ts + dt.timedelta(seconds=1)

    corridor_prices = [
        value
        for value in (
            low,
            high,
            parse_float(contact.get("prox_quote", "")),
            parse_float(contact.get("best_contact_quote", "")),
        )
        if value is not None
    ]
    approach_low_tick = min(tick_key(value) for value in corridor_prices) - 2
    approach_high_tick = max(tick_key(value) for value in corridor_prices) + 2
    escape_prices = [
        value
        for value in (
            low,
            high,
            parse_float(contact.get("best_contact_quote", "")),
            parse_float(contact.get("extreme_quote", "")),
        )
        if value is not None
    ]
    escape_low_tick = min(tick_key(value) for value in escape_prices) - 2
    escape_high_tick = max(tick_key(value) for value in escape_prices) + 2

    approach = filter_ticks(data.ticks, entry_start, contact_ts, approach_low_tick, approach_high_tick)
    escape = filter_ticks(data.ticks, contact_ts, post_end, escape_low_tick, escape_high_tick)
    entry_near = filter_ticks(data.ticks, near_start, contact_ts, near_low_tick, near_high_tick)
    entry_core = filter_ticks(data.ticks, near_start, contact_ts, low_tick, high_tick)
    post_near = filter_ticks(data.ticks, contact_ts, post_end, near_low_tick, near_high_tick)
    post_core = filter_ticks(data.ticks, contact_ts, post_end, low_tick, high_tick)

    approach_stats = tick_stats(approach, side)
    escape_stats = tick_stats(escape, side)
    entry_near_stats = tick_stats(entry_near, side)
    entry_core_stats = tick_stats(entry_core, side)
    post_near_stats = tick_stats(post_near, side)
    post_core_stats = tick_stats(post_core, side)

    snap_pre = nearest_snapshot(data.snapshots, contact_ts - dt.timedelta(seconds=10))
    snap_contact = nearest_snapshot(data.snapshots, contact_ts)
    snap_post = nearest_snapshot(data.snapshots, post_end)

    support_pre = side_size(snap_pre, support_side, near_low_tick, near_high_tick)
    support_contact = side_size(snap_contact, support_side, near_low_tick, near_high_tick)
    support_post = side_size(snap_post, support_side, near_low_tick, near_high_tick)
    opposing_contact = side_size(snap_contact, opposing_side, near_low_tick, near_high_tick)
    opposing_post = side_size(snap_post, opposing_side, near_low_tick, near_high_tick)

    support_change_entry = None
    support_change_post = None
    if support_pre is not None and support_contact is not None:
        support_change_entry = support_contact - support_pre
    if support_contact is not None and support_post is not None:
        support_change_post = support_post - support_contact

    contact_tilt = None
    post_tilt = None
    if support_contact is not None and opposing_contact is not None and support_contact + opposing_contact > 0:
        contact_tilt = support_contact / (support_contact + opposing_contact)
    if support_post is not None and opposing_post is not None and support_post + opposing_post > 0:
        post_tilt = support_post / (support_post + opposing_post)

    row: dict[str, object] = {
        "date": contact["date"],
        "contact_ts": contact["contact_ts"],
        "band_id": contact["band_id"],
        "side": side,
        "source": contact["source"],
        "source_kind": "consumed" if "consumed" in contact["source"] else "lean",
        "cohort": contact["cohort"],
        "resolution": contact["resolution"],
        "band_low": low,
        "band_high": high,
        "prox_ts": contact["prox_ts"],
        "proximity_cost_ticks": parse_float(contact["proximity_cost_ticks"]),
        "puncture_ticks": parse_float(contact["puncture_ticks"]),
        "entry_speed_ticks_sec": parse_float(contact["entry_speed_ticks_sec"]),
        "exit_speed_ticks_sec": parse_float(contact["exit_speed_ticks_sec"]),
        "exit_entry_speed_ratio": parse_float(contact["exit_entry_speed_ratio"]),
        "approach_sec": (contact_ts - entry_start).total_seconds(),
        "approach_low": approach_low_tick * TICK,
        "approach_high": approach_high_tick * TICK,
        "approach_vol": approach_stats["vol"],
        "approach_adverse_vol": approach_stats["adverse_vol"],
        "approach_favorable_vol": approach_stats["favorable_vol"],
        "approach_adverse_share": approach_stats["adverse_share"],
        "approach_favorable_share": approach_stats["favorable_share"],
        "escape_sec": (post_end - contact_ts).total_seconds(),
        "escape_low": escape_low_tick * TICK,
        "escape_high": escape_high_tick * TICK,
        "escape_vol": escape_stats["vol"],
        "escape_adverse_vol": escape_stats["adverse_vol"],
        "escape_favorable_vol": escape_stats["favorable_vol"],
        "escape_adverse_share": escape_stats["adverse_share"],
        "escape_favorable_share": escape_stats["favorable_share"],
        "escape_fav_over_approach_adv": escape_stats["favorable_vol"] / (approach_stats["adverse_vol"] + 1.0),
        "entry_near_vol": entry_near_stats["vol"],
        "entry_near_adverse_vol": entry_near_stats["adverse_vol"],
        "entry_near_favorable_vol": entry_near_stats["favorable_vol"],
        "entry_adverse_share": entry_near_stats["adverse_share"],
        "entry_core_adverse_imbalance_max": entry_core_stats["adverse_imbalance_max"],
        "post_near_vol": post_near_stats["vol"],
        "post_near_adverse_vol": post_near_stats["adverse_vol"],
        "post_near_favorable_vol": post_near_stats["favorable_vol"],
        "post_favorable_share": post_near_stats["favorable_share"],
        "post_core_favorable_imbalance_max": post_core_stats["favorable_imbalance_max"],
        "post_fav_over_entry_adv": post_near_stats["favorable_vol"] / (entry_near_stats["adverse_vol"] + 1.0),
        "support_pre10": support_pre,
        "support_contact": support_contact,
        "support_post": support_post,
        "support_change_entry": support_change_entry,
        "support_change_post": support_change_post,
        "opposing_contact": opposing_contact,
        "opposing_post": opposing_post,
        "contact_tilt": contact_tilt,
        "post_tilt": post_tilt,
        "adverse_sign": adverse_sign,
    }
    row["mechanism_hint"] = mechanism_hint(row)
    return row


def median_value(rows: list[dict[str, object]], key: str) -> float | None:
    values = [float(row[key]) for row in rows if row.get(key) is not None]
    return median(values) if values else None


def mean_value(rows: list[dict[str, object]], key: str) -> float | None:
    values = [float(row[key]) for row in rows if row.get(key) is not None]
    return sum(values) / len(values) if values else None


def aggregate(rows: list[dict[str, object]], keys: list[str]) -> list[dict[str, object]]:
    groups: dict[tuple[object, ...], list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        groups[tuple(row[key] for key in keys)].append(row)

    out = []
    for key_values, group in groups.items():
        holds = sum(1 for row in group if row["resolution"] == "HOLD")
        record = {key: value for key, value in zip(keys, key_values)}
        record.update(
            {
                "n": len(group),
                "holds": holds,
                "hold_pct": holds / len(group) * 100.0,
                "med_proximity_cost_ticks": median_value(group, "proximity_cost_ticks"),
                "med_puncture_ticks": median_value(group, "puncture_ticks"),
                "med_speed_ratio": median_value(group, "exit_entry_speed_ratio"),
                "med_approach_adverse_share": median_value(group, "approach_adverse_share"),
                "med_escape_favorable_share": median_value(group, "escape_favorable_share"),
                "med_escape_fav_over_approach_adv": median_value(group, "escape_fav_over_approach_adv"),
                "med_entry_adverse_share": median_value(group, "entry_adverse_share"),
                "med_post_favorable_share": median_value(group, "post_favorable_share"),
                "med_post_fav_over_entry_adv": median_value(group, "post_fav_over_entry_adv"),
                "med_support_change_entry": median_value(group, "support_change_entry"),
                "med_support_change_post": median_value(group, "support_change_post"),
                "med_contact_tilt": median_value(group, "contact_tilt"),
                "med_post_tilt": median_value(group, "post_tilt"),
                "mean_entry_core_adverse_imbalance": mean_value(group, "entry_core_adverse_imbalance_max"),
                "mean_post_core_favorable_imbalance": mean_value(group, "post_core_favorable_imbalance_max"),
            }
        )
        out.append(record)
    out.sort(key=lambda row: tuple(str(row[key]) for key in keys))
    return out


def write_csv(path: Path, rows: list[dict[str, object]], fieldnames: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field) for field in fieldnames})


def table(lines: list[str], headers: list[str], rows: list[dict[str, object]]) -> None:
    lines.append("| " + " | ".join(headers) + " |")
    lines.append("|" + "|".join("---" for _ in headers) + "|")
    for row in rows:
        vals = []
        for header in headers:
            value = row.get(header)
            if isinstance(value, float):
                vals.append(fmt(value, 2))
            else:
                vals.append("" if value is None else str(value))
        lines.append("| " + " | ".join(vals) + " |")
    lines.append("")


def focus_rows(rows: list[dict[str, object]], day: str, start: str, end: str) -> list[dict[str, object]]:
    start_ts = parse_ts(f"{day} {start}")
    end_ts = parse_ts(f"{day} {end}")
    assert start_ts is not None and end_ts is not None
    out = []
    for row in rows:
        ts = parse_ts(str(row["contact_ts"]))
        if row["date"] == day and ts is not None and start_ts <= ts <= end_ts:
            out.append(row)
    out.sort(key=lambda row: str(row["contact_ts"]))
    return out


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    contacts = read_contacts()
    days = sorted({row["date"] for row in contacts})
    day_data = {day: load_day(day) for day in days}

    rows: list[dict[str, object]] = []
    for contact in contacts:
        analyzed = analyze_contact(contact, day_data[contact["date"]])
        if analyzed:
            rows.append(analyzed)

    contact_fields = [
        "date",
        "contact_ts",
        "band_id",
        "side",
        "source",
        "source_kind",
        "cohort",
        "resolution",
        "band_low",
        "band_high",
        "proximity_cost_ticks",
        "puncture_ticks",
        "exit_entry_speed_ratio",
        "approach_sec",
        "approach_low",
        "approach_high",
        "approach_vol",
        "approach_adverse_vol",
        "approach_favorable_vol",
        "approach_adverse_share",
        "escape_sec",
        "escape_low",
        "escape_high",
        "escape_vol",
        "escape_adverse_vol",
        "escape_favorable_vol",
        "escape_favorable_share",
        "escape_fav_over_approach_adv",
        "entry_near_vol",
        "entry_near_adverse_vol",
        "entry_near_favorable_vol",
        "entry_adverse_share",
        "entry_core_adverse_imbalance_max",
        "post_near_vol",
        "post_near_adverse_vol",
        "post_near_favorable_vol",
        "post_favorable_share",
        "post_core_favorable_imbalance_max",
        "post_fav_over_entry_adv",
        "support_pre10",
        "support_contact",
        "support_post",
        "support_change_entry",
        "support_change_post",
        "contact_tilt",
        "post_tilt",
        "mechanism_hint",
    ]
    write_csv(OUT_DIR / "mechanism_contacts.csv", rows, contact_fields)

    agg_specs = {
        "by_day.csv": ["date"],
        "by_source_kind.csv": ["source_kind"],
        "by_day_source_kind.csv": ["date", "source_kind"],
        "by_day_side_source_kind.csv": ["date", "side", "source_kind"],
        "by_cohort.csv": ["cohort"],
        "by_source_kind_cohort.csv": ["source_kind", "cohort"],
        "by_mechanism_hint.csv": ["mechanism_hint"],
    }
    agg_field_order = [
        "n",
        "holds",
        "hold_pct",
        "med_proximity_cost_ticks",
        "med_puncture_ticks",
        "med_speed_ratio",
        "med_approach_adverse_share",
        "med_escape_favorable_share",
        "med_escape_fav_over_approach_adv",
        "med_entry_adverse_share",
        "med_post_favorable_share",
        "med_post_fav_over_entry_adv",
        "med_support_change_entry",
        "med_support_change_post",
        "med_contact_tilt",
        "med_post_tilt",
        "mean_entry_core_adverse_imbalance",
        "mean_post_core_favorable_imbalance",
    ]
    aggregations: dict[str, list[dict[str, object]]] = {}
    for filename, keys in agg_specs.items():
        agg_rows = aggregate(rows, keys)
        aggregations[filename] = agg_rows
        write_csv(OUT_DIR / filename, agg_rows, keys + agg_field_order)

    report: list[str] = [
        "# ES Rail Mechanism Probe",
        "",
        "Inputs: ESU6 ticks, canonical 1 Hz snapshots, synthetic LevelLedger first-contact rows.",
        "Per-contact windows: approach corridor from proximity-to-contact capped at 120 seconds, plus contact-to-resolution capped at 30 seconds.",
        "For demand rails, adverse aggression is selling and support is bid size. For supply rails, adverse aggression is buying and support is ask size.",
        "",
        "## Day Summary",
        "",
    ]
    table(report, ["date"] + agg_field_order, aggregations["by_day.csv"])
    report.extend(["## Source Kind Summary", ""])
    table(report, ["source_kind"] + agg_field_order, aggregations["by_source_kind.csv"])
    report.extend(["## Day / Side / Source Kind", ""])
    table(report, ["date", "side", "source_kind"] + agg_field_order, aggregations["by_day_side_source_kind.csv"])
    report.extend(["## Cohort Summary", ""])
    table(report, ["cohort"] + agg_field_order, aggregations["by_cohort.csv"])
    report.extend(["## Mechanism Hint Summary", ""])
    table(report, ["mechanism_hint"] + agg_field_order, aggregations["by_mechanism_hint.csv"])

    focus_specs = [
        ("2026-07-29 FOMC Long Area", "2026-07-29", "14:20:00", "15:05:00"),
        ("2026-07-29 Short Reversal Area", "2026-07-29", "15:10:00", "16:00:00"),
        ("2026-07-28 Long Morning", "2026-07-28", "10:00:00", "11:45:00"),
    ]
    focus_headers = [
        "contact",
        "band",
        "side",
        "source",
        "band",
        "cohort",
        "res",
        "prox_t",
        "puncture_t",
        "speed",
        "approach_adv%",
        "escape_fav%",
        "escape/approach_adv",
        "support_entry",
        "support_post",
        "tilt_contact",
        "hint",
    ]
    for title, day, start, end in focus_specs:
        report.extend([f"## {title}", ""])
        report.append("| " + " | ".join(focus_headers) + " |")
        report.append("|" + "|".join("---" for _ in focus_headers) + "|")
        for row in focus_rows(rows, day, start, end):
            report.append(
                "| "
                + " | ".join(
                    [
                        str(row["contact_ts"])[-8:],
                        str(row["band_id"]),
                        str(row["side"]),
                        str(row["source"]),
                        f"{fmt(float(row['band_low']), 2)}-{fmt(float(row['band_high']), 2)}",
                        str(row["cohort"]),
                        str(row["resolution"]),
                        fmt(row.get("proximity_cost_ticks"), 1),
                        fmt(row.get("puncture_ticks"), 1),
                        fmt(row.get("exit_entry_speed_ratio"), 2),
                        fmt(float(row["approach_adverse_share"]) * 100.0, 0),
                        fmt(float(row["escape_favorable_share"]) * 100.0, 0),
                        fmt(row.get("escape_fav_over_approach_adv"), 2),
                        fmt(row.get("support_change_entry"), 1),
                        fmt(row.get("support_change_post"), 1),
                        fmt(row.get("contact_tilt"), 2),
                        str(row["mechanism_hint"]),
                    ]
                )
                + " |"
            )
        report.append("")

    (OUT_DIR / "findings.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    print(f"Wrote {OUT_DIR / 'findings.md'}")
    print(f"Wrote {OUT_DIR / 'mechanism_contacts.csv'}")


if __name__ == "__main__":
    main()
