from __future__ import annotations

import argparse
import csv
import json
import math
import re
import sys
from bisect import bisect_left
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import polars as pl

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "research"))

from capture_loader import load_capture_window, snapshot_columns, tick_columns, us

NY = ZoneInfo("America/New_York")
TICK_SIZE = 0.25
DEPTH_LEVELS = 30
POST_WINDOWS = (60, 180)

RUNTIME = {
    "ES": {
        "symbol_dir": "ESU6",
        "events": Path(r"C:\Users\j\Documents\ExecAssistantRuntime\ES\events.jsonl"),
    },
    "NQ": {
        "symbol_dir": "NQU6",
        "events": Path(r"C:\Users\j\Documents\ExecAssistantRuntime\NQ\events.jsonl"),
    },
}

TS_RE = re.compile(r"^(.*T\d\d:\d\d:\d\d)(?:\.(\d+))?(Z|[+-]\d\d:\d\d)$")


def parse_utc(text: str) -> datetime:
    m = TS_RE.match(text)
    if not m:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(timezone.utc)
    head, frac, zone = m.groups()
    frac = (frac or "")[:6].ljust(6, "0")
    zone = "+00:00" if zone == "Z" else zone
    return datetime.fromisoformat(f"{head}.{frac}{zone}").astimezone(timezone.utc)


def et_text(value: datetime | None) -> str:
    if value is None:
        return ""
    return value.astimezone(NY).strftime("%H:%M:%S")


def iso_et(day: str, hhmm: str) -> datetime:
    return datetime.fromisoformat(f"{day}T{hhmm}:00").replace(tzinfo=NY)


def price_to_tick(price: float) -> int:
    return int(round(price / TICK_SIZE))


def tick_to_price(tick: int) -> float:
    return tick * TICK_SIZE


def side_sign(side: str) -> int:
    return 1 if side.lower() == "demand" else -1


def relation(price: float, side: str, lo: float, hi: float) -> str:
    if side.lower() == "demand":
        if price > hi:
            return "beyond"
        if price < lo:
            return "old"
        return "inside"
    if price < lo:
        return "beyond"
    if price > hi:
        return "old"
    return "inside"


def load_runtime(symbol: str, start_utc: datetime, end_utc: datetime) -> dict[str, list[dict]]:
    path = RUNTIME[symbol]["events"]
    wanted = {
        "directive_accepted",
        "order_submit",
        "fill_quality",
        "sponsor_promoted",
        "sponsor_cleared",
        "sponsor_failed",
        "sponsor_failure_context",
        "reference_break_tactical_child",
    }
    out = {key: [] for key in wanted}
    loose_start = start_utc - timedelta(minutes=10)
    loose_end = end_utc + timedelta(minutes=10)
    date_prefix = start_utc.strftime("%Y-%m-%dT")
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if date_prefix not in line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            event = obj.get("event")
            if event not in wanted:
                continue
            ts = parse_utc(obj["ts_utc"])
            if loose_start <= ts <= loose_end:
                obj["_ts"] = ts
                out[event].append(obj)
    return out


def nearest_snapshot(snapshots: list[dict], snap_us: list[int], target_us: int) -> dict | None:
    i = bisect_left(snap_us, target_us)
    if i >= len(snapshots):
        return None
    return snapshots[i]


def mid_price(snapshot: dict) -> float:
    return float(snapshot["ref_tick"]) * TICK_SIZE


def depth_in_band(snapshot: dict | None, side: str, lo_tick: int, hi_tick: int) -> float | None:
    if snapshot is None:
        return None
    total = 0.0
    owner = side_sign(side)
    ref = int(snapshot["ref_tick"])
    for i in range(DEPTH_LEVELS):
        if owner > 0:
            off = snapshot.get(f"bid_offset_{i}")
            size = snapshot.get(f"bid_size_{i}")
        else:
            off = snapshot.get(f"ask_offset_{i}")
            size = snapshot.get(f"ask_size_{i}")
        if off is None or size is None:
            continue
        tick = ref + int(off)
        if lo_tick <= tick <= hi_tick:
            total += float(size)
    return total


def snap_state_seconds(snapshots: list[dict], start_us: int, end_us: int, side: str, lo: float, hi: float) -> dict[str, float]:
    idx = bisect_left([r["timestamp_us"] for r in snapshots], start_us)
    totals = {"beyond": 0.0, "inside": 0.0, "old": 0.0, "samples": 0.0}
    while idx < len(snapshots):
        row = snapshots[idx]
        row_us = int(row["timestamp_us"])
        if row_us >= end_us:
            break
        next_us = end_us
        if idx + 1 < len(snapshots):
            next_us = min(int(snapshots[idx + 1]["timestamp_us"]), end_us)
        dt = max(0, next_us - max(row_us, start_us)) / 1_000_000.0
        rel = relation(mid_price(row), side, lo, hi)
        totals[rel] += dt
        totals["samples"] += 1
        idx += 1
    return totals


def ticks_between(ticks: list[dict], tick_us: list[int], start_us: int, end_us: int) -> list[dict]:
    a = bisect_left(tick_us, start_us)
    b = bisect_left(tick_us, end_us)
    return ticks[a:b]


def summarize_ticks(rows: list[dict], side: str, lo: float, hi: float) -> dict[str, float]:
    out = defaultdict(float)
    for row in rows:
        price = float(row["price"])
        size = float(row["size"])
        sign = int(row.get("aggressor_sign") or 0)
        rel = relation(price, side, lo, hi)
        out[f"vol_{rel}"] += size
        out[f"delta_{rel}"] += size * sign
        if sign > 0:
            out[f"buy_{rel}"] += size
        elif sign < 0:
            out[f"sell_{rel}"] += size
    out["vol_total"] = sum(float(row["size"]) for row in rows)
    return dict(out)


def first_tick_time(rows: list[dict], predicate) -> int | None:
    for row in rows:
        if predicate(float(row["price"])):
            return int(row["timestamp_us"])
    return None


def cross_count(snapshots: list[dict], start_us: int, end_us: int, side: str, lo: float, hi: float) -> int:
    states = []
    for row in snapshots:
        ts = int(row["timestamp_us"])
        if ts < start_us:
            continue
        if ts >= end_us:
            break
        states.append(relation(mid_price(row), side, lo, hi))
    count = 0
    prev = None
    for state in states:
        if prev is not None and state != prev:
            count += 1
        prev = state
    return count


def map_order_for_sponsor(sponsor: dict, submits: list[dict], fills: dict[str, dict]) -> tuple[dict | None, dict | None]:
    sid = sponsor.get("sponsor_id")
    directive = sponsor.get("directive_id")
    st = sponsor["_ts"]
    best = None
    best_dt = 999.0
    for submit in submits:
        if submit.get("directive_id") != directive:
            continue
        if submit.get("root_object_id") != sid and submit.get("support_object_id") != sid:
            continue
        dt = abs((submit["_ts"] - st).total_seconds())
        if dt < best_dt and dt <= 3.0:
            best = submit
            best_dt = dt
    if best is None:
        return None, None
    return best, fills.get(best.get("intent_id"))


def classify(row: dict) -> tuple[str, str]:
    prior_vol = row["prior_vol_in_band_300s"]
    prior_cross = row["prior_cross_count_300s"]
    old_reopen = row["old_price_reopened_60s"]
    next_delay = row["next_same_side_sponsor_delay_sec"]
    restack = row["same_depth_change_after_touch_5s"]
    old60 = float(row["old_time_ratio_60s"])
    old180 = float(row["old_time_ratio_180s"])
    beyond60 = float(row["beyond_time_ratio_60s"])
    beyond180 = float(row["beyond_time_ratio_180s"])
    first_old = float(row["first_old_price_sec"]) if row["first_old_price_sec"] != "" else None
    pass_speed = float(row["pass_through_speed_ticks_per_sec"]) if row["pass_through_speed_ticks_per_sec"] != "" else None
    restack_value = float(restack) if restack != "" else None
    next_value = float(next_delay) if next_delay != "" else None

    if prior_vol >= row["memory_volume_threshold"] * 3 and prior_cross >= 4:
        origin = "fought_sponsor"
    elif prior_vol >= row["memory_volume_threshold"] and prior_cross >= 2:
        origin = "prior_memory_sponsor"
    else:
        origin = "fresh_sponsor"
    if next_value is not None and next_value <= 90 and not old_reopen:
        origin = "fresh_sponsor_chained" if origin == "fresh_sponsor" else origin
    hard_pass = (
        old_reopen
        and restack_value is not None
        and restack_value <= 0
        and (
            old60 >= 0.10
            or old180 >= 0.10
            or (first_old is not None and first_old <= 5 and pass_speed is not None and pass_speed >= 2.0)
        )
    )
    if hard_pass:
        origin = "fresh_sponsor_passed_through" if origin == "fresh_sponsor" else origin

    if hard_pass:
        consequence = "passed_through_no_restack"
    elif next_value is not None and next_value <= 90 and beyond60 >= 0.65 and old60 <= 0.05:
        consequence = "chained_extension"
    elif beyond60 >= 0.85 and old60 <= 0.05:
        consequence = "accepted_beyond"
    elif beyond180 >= 0.75 and old180 <= 0.05:
        consequence = "accepted_after_minor_retest"
    elif row["first_touch_sec"] != "" and old60 <= 0.05:
        consequence = "repair_survived"
    elif next_value is not None and next_value <= 90:
        consequence = "chained_extension"
    else:
        consequence = "fragile_or_unresolved"
    return origin, consequence
def analyze_symbol(symbol: str, day: str, start_et: datetime, end_et: datetime) -> list[dict]:
    start_utc = start_et.astimezone(timezone.utc)
    end_utc = end_et.astimezone(timezone.utc)
    runtime = load_runtime(symbol, start_utc, end_utc)
    submits = runtime["order_submit"]
    fills = {f.get("intent_id"): f for f in runtime["fill_quality"]}
    clears = {(c.get("directive_id"), c.get("sponsor_id")): c for c in runtime["sponsor_cleared"]}
    failures = {(f.get("directive_id"), f.get("sponsor_id")): f for f in runtime["sponsor_failed"]}
    tactical_ids = {(r.get("directive_id"), r.get("child_id")) for r in runtime["reference_break_tactical_child"]}
    sponsors = [s for s in runtime["sponsor_promoted"] if s.get("side") == "Demand" and start_utc <= s["_ts"] <= end_utc]
    sponsors.sort(key=lambda s: s["_ts"])

    load_start = start_et - timedelta(minutes=10)
    load_end = end_et + timedelta(minutes=10)
    symbol_dir = RUNTIME[symbol]["symbol_dir"]
    ticks_df = load_capture_window("ticks", symbol_dir, load_start, load_end, tick_columns(), inclusive_end=True)
    snaps_df = load_capture_window("snapshots", symbol_dir, load_start, load_end, snapshot_columns(DEPTH_LEVELS), inclusive_end=True)
    ticks = ticks_df.to_dicts()
    snapshots = snaps_df.to_dicts()
    tick_us = [int(r["timestamp_us"]) for r in ticks]
    snap_us = [int(r["timestamp_us"]) for r in snapshots]

    rows = []
    for i, sponsor in enumerate(sponsors):
        side = sponsor.get("side")
        lo = float(sponsor["lower"])
        hi = float(sponsor["upper"])
        lo_tick = price_to_tick(lo)
        hi_tick = price_to_tick(hi)
        t0 = sponsor["_ts"]
        t0_us = int(t0.timestamp() * 1_000_000)
        submit, fill = map_order_for_sponsor(sponsor, submits, fills)
        clear = clears.get((sponsor.get("directive_id"), sponsor.get("sponsor_id")))
        failure = failures.get((sponsor.get("directive_id"), sponsor.get("sponsor_id")))

        after_180 = ticks_between(ticks, tick_us, t0_us, t0_us + 180_000_000)
        after_60 = ticks_between(ticks, tick_us, t0_us, t0_us + 60_000_000)
        prior_300 = ticks_between(ticks, tick_us, t0_us - 300_000_000, t0_us)
        prior_band = [r for r in prior_300 if lo <= float(r["price"]) <= hi]
        prior_buy = sum(float(r["size"]) for r in prior_band if int(r.get("aggressor_sign") or 0) > 0)
        prior_sell = sum(float(r["size"]) for r in prior_band if int(r.get("aggressor_sign") or 0) < 0)
        prior_cross = cross_count(snapshots, t0_us - 300_000_000, t0_us, side, lo, hi)

        if side == "Demand":
            first_touch_us = first_tick_time(after_180, lambda p: p <= hi)
            first_old_us = first_tick_time(after_180, lambda p: p < lo)
        else:
            first_touch_us = first_tick_time(after_180, lambda p: p >= lo)
            first_old_us = first_tick_time(after_180, lambda p: p > hi)

        snap0 = nearest_snapshot(snapshots, snap_us, t0_us)
        same0 = depth_in_band(snap0, side, lo_tick, hi_tick)
        touch_same = ""
        restack_2s = ""
        restack_5s = ""
        if first_touch_us is not None:
            touch_snap = nearest_snapshot(snapshots, snap_us, first_touch_us)
            same_touch = depth_in_band(touch_snap, side, lo_tick, hi_tick)
            touch_same = "" if same_touch is None else round(same_touch, 3)
            for sec, name in [(2, "restack_2s"), (5, "restack_5s")]:
                later = nearest_snapshot(snapshots, snap_us, first_touch_us + sec * 1_000_000)
                same_later = depth_in_band(later, side, lo_tick, hi_tick)
                if same_touch is not None and same_later is not None:
                    if name == "restack_2s":
                        restack_2s = round(same_later - same_touch, 3)
                    else:
                        restack_5s = round(same_later - same_touch, 3)

        states60 = snap_state_seconds(snapshots, t0_us, t0_us + 60_000_000, side, lo, hi)
        states180 = snap_state_seconds(snapshots, t0_us, t0_us + 180_000_000, side, lo, hi)
        sum60 = summarize_ticks(after_60, side, lo, hi)
        sum180 = summarize_ticks(after_180, side, lo, hi)

        next_same = ""
        next_worse = ""
        for nxt in sponsors[i + 1 :]:
            delay = (nxt["_ts"] - t0).total_seconds()
            if delay < 0:
                continue
            worse = float(nxt["lower"]) > lo if side == "Demand" else float(nxt["upper"]) < hi
            if worse:
                next_same = round(delay, 3)
                next_worse = f"{float(nxt['lower']):.2f}-{float(nxt['upper']):.2f}"
                break

        role = submit.get("role") if submit else ""
        resolution = submit.get("resolution") if submit else ""
        fill_price = fill.get("fill_price") if fill else ""
        root_distance = fill.get("root_distance_ticks") if fill else ""
        first_touch_sec = "" if first_touch_us is None else round((first_touch_us - t0_us) / 1_000_000, 3)
        first_old_sec = "" if first_old_us is None else round((first_old_us - t0_us) / 1_000_000, 3)
        pass_speed = ""
        if first_touch_us is not None and first_old_us is not None and first_old_us > first_touch_us:
            width_ticks = max(1, hi_tick - lo_tick + 1)
            pass_speed = round(width_ticks / ((first_old_us - first_touch_us) / 1_000_000), 3)

        memory_threshold = 200.0 if symbol == "NQ" else 1000.0
        row = {
            "symbol": symbol,
            "time_et": et_text(t0),
            "directive_id": sponsor.get("directive_id"),
            "sponsor_id": sponsor.get("sponsor_id"),
            "side": side,
            "range": f"{lo:.2f}-{hi:.2f}",
            "source": sponsor.get("source"),
            "promotion_reason": sponsor.get("reason"),
            "order_role": role,
            "entry_resolution": resolution,
            "fill_price": fill_price,
            "root_distance_ticks": root_distance,
            "prior_sponsor_id": sponsor.get("prior_sponsor_id"),
            "tactical_child_tagged": (sponsor.get("directive_id"), sponsor.get("sponsor_id")) in tactical_ids,
            "clear_reason": clear.get("flatten_reason") if clear else "",
            "failed_formally": bool(failure),
            "prior_vol_in_band_300s": round(sum(float(r["size"]) for r in prior_band), 3),
            "prior_buy_in_band_300s": round(prior_buy, 3),
            "prior_sell_in_band_300s": round(prior_sell, 3),
            "prior_cross_count_300s": prior_cross,
            "memory_volume_threshold": memory_threshold,
            "first_touch_sec": first_touch_sec,
            "first_old_price_sec": first_old_sec,
            "old_price_reopened_60s": first_old_us is not None and first_old_us <= t0_us + 60_000_000,
            "pass_through_speed_ticks_per_sec": pass_speed,
            "same_depth_at_promote": "" if same0 is None else round(same0, 3),
            "same_depth_at_first_touch": touch_same,
            "same_depth_change_after_touch_2s": restack_2s,
            "same_depth_change_after_touch_5s": restack_5s,
            "beyond_time_sec_60s": round(states60["beyond"], 3),
            "inside_time_sec_60s": round(states60["inside"], 3),
            "old_time_sec_60s": round(states60["old"], 3),
            "beyond_time_ratio_60s": round(states60["beyond"] / 60.0, 3),
            "old_time_ratio_60s": round(states60["old"] / 60.0, 3),
            "beyond_time_ratio_180s": round(states180["beyond"] / 180.0, 3),
            "old_time_ratio_180s": round(states180["old"] / 180.0, 3),
            "vol_beyond_60s": round(sum60.get("vol_beyond", 0.0), 3),
            "vol_inside_60s": round(sum60.get("vol_inside", 0.0), 3),
            "vol_old_60s": round(sum60.get("vol_old", 0.0), 3),
            "delta_beyond_60s": round(sum60.get("delta_beyond", 0.0), 3),
            "delta_inside_60s": round(sum60.get("delta_inside", 0.0), 3),
            "delta_old_60s": round(sum60.get("delta_old", 0.0), 3),
            "vol_beyond_180s": round(sum180.get("vol_beyond", 0.0), 3),
            "vol_inside_180s": round(sum180.get("vol_inside", 0.0), 3),
            "vol_old_180s": round(sum180.get("vol_old", 0.0), 3),
            "next_same_side_sponsor_delay_sec": next_same,
            "next_same_side_sponsor_worse_price": next_worse,
        }
        origin, consequence = classify(row)
        row["sponsor_origin_label"] = origin
        row["post_sponsor_consequence"] = consequence
        rows.append(row)
    return rows


def write_outputs(rows: list[dict], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / "sponsor_consequence_2026-08-21.csv"
    if rows:
        fields = list(rows[0].keys())
        with csv_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
    counts_origin = Counter(r["sponsor_origin_label"] for r in rows)
    counts_conseq = Counter(r["post_sponsor_consequence"] for r in rows)
    md = ["# Sponsor Consequence Probe - 2026-08-21", "", "Research-only generated output.", "", "## Counts", ""]
    md.append("Origin labels: " + ", ".join(f"{k}={v}" for k, v in counts_origin.items()))
    md.append("Consequence labels: " + ", ".join(f"{k}={v}" for k, v in counts_conseq.items()))
    md.extend(["", "## Rows", "", "| Symbol | Time | Sponsor | Role | Root dist | Prior vol | First old | Restack 5s | Beyond 60s | Old 60s | Next same | Label | Consequence |", "|---|---:|---|---|---:|---:|---:|---:|---:|---:|---:|---|---|"])
    for r in rows:
        md.append(
            f"| {r['symbol']} | {r['time_et']} | {r['range']} | {r['order_role'] or r['promotion_reason']} | "
            f"{r['root_distance_ticks']} | {r['prior_vol_in_band_300s']} | {r['first_old_price_sec']} | "
            f"{r['same_depth_change_after_touch_5s']} | {r['beyond_time_ratio_60s']} | {r['old_time_ratio_60s']} | "
            f"{r['next_same_side_sponsor_delay_sec']} | {r['sponsor_origin_label']} | {r['post_sponsor_consequence']} |"
        )
    (out_dir / "summary.md").write_text("\n".join(md) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default="2026-08-21")
    parser.add_argument("--start", default="10:55")
    parser.add_argument("--end", default="11:40")
    parser.add_argument("--out-dir", type=Path, default=Path("research/out/sponsor_consequence_2026-08-21"))
    args = parser.parse_args()
    start = iso_et(args.date, args.start)
    end = iso_et(args.date, args.end)
    rows: list[dict] = []
    for symbol in ("ES", "NQ"):
        rows.extend(analyze_symbol(symbol, args.date, start, end))
    rows.sort(key=lambda r: (r["symbol"], r["time_et"], int(r["sponsor_id"] or 0)))
    write_outputs(rows, args.out_dir)
    print(f"wrote {len(rows)} rows to {args.out_dir}")


if __name__ == "__main__":
    main()
