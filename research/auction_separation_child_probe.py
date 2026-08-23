from __future__ import annotations

import argparse
import csv
import math
import sys
from bisect import bisect_left
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import polars as pl

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "research"))

import sponsor_consequence_probe as scp
from capture_loader import load_capture_window, snapshot_columns, tick_columns

NY = ZoneInfo("America/New_York")
TICK_SIZE = 0.25
DEPTH_LEVELS = 30


def ny_hms(ts: datetime | None) -> str:
    if ts is None:
        return ""
    return ts.astimezone(NY).strftime("%H:%M:%S")


def ny_dt(day: str, value: str) -> datetime:
    return datetime.fromisoformat(f"{day}T{value}:00").replace(tzinfo=NY)


def price_to_tick(price: float) -> int:
    return int(round(price / TICK_SIZE))


def tick_to_price(tick: int) -> float:
    return tick * TICK_SIZE


def parse_float(value: object) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).lower() == "true"


def us(ts: datetime) -> int:
    return int(ts.timestamp() * 1_000_000)


def parse_window(day: str, window: str) -> tuple[datetime, datetime]:
    start, end = window.split("-", 1)
    return ny_dt(day, start), ny_dt(day, end)


def tick_rows_between(rows: list[dict], row_us: list[int], start_us: int, end_us: int) -> list[dict]:
    a = bisect_left(row_us, start_us)
    b = bisect_left(row_us, end_us)
    return rows[a:b]


def volume_in_ticks(rows: list[dict], lo_tick: int, hi_tick: int) -> tuple[float, int, float, float]:
    if hi_tick < lo_tick:
        return 0.0, 0, 0.0, 0.0
    vol = 0.0
    trades = 0
    buy = 0.0
    sell = 0.0
    for row in rows:
        tick = price_to_tick(float(row["price"]))
        if lo_tick <= tick <= hi_tick:
            size = float(row["size"])
            sign = int(row.get("aggressor_sign") or 0)
            vol += size
            trades += 1
            if sign > 0:
                buy += size
            elif sign < 0:
                sell += size
    return vol, trades, buy, sell


def mid_tick(snapshot: dict) -> int:
    return int(snapshot["ref_tick"])


def mid_time_in_ticks(snapshots: list[dict], start_us: int, end_us: int, lo_tick: int, hi_tick: int) -> float:
    if hi_tick < lo_tick:
        return 0.0
    idx = bisect_left([int(r["timestamp_us"]) for r in snapshots], start_us)
    seconds = 0.0
    while idx < len(snapshots):
        row = snapshots[idx]
        ts = int(row["timestamp_us"])
        if ts >= end_us:
            break
        next_us = end_us
        if idx + 1 < len(snapshots):
            next_us = min(int(snapshots[idx + 1]["timestamp_us"]), end_us)
        if lo_tick <= mid_tick(row) <= hi_tick:
            seconds += max(0, next_us - max(ts, start_us)) / 1_000_000.0
        idx += 1
    return seconds


def range_ticks(row: dict) -> tuple[int, int]:
    if "range" in row:
        lo, hi = str(row["range"]).split("-", 1)
        return price_to_tick(float(lo)), price_to_tick(float(hi))
    return price_to_tick(float(row["lower"])), price_to_tick(float(row["upper"]))


def sponsor_key(sponsor: dict) -> tuple[str, int]:
    return sponsor.get("directive_id"), int(sponsor.get("sponsor_id"))


def row_key(row: dict) -> tuple[str, int]:
    return row.get("directive_id"), int(row.get("sponsor_id"))


def directive_parent(sponsor: dict, sponsors_by_key: dict[tuple[str, int], dict]) -> dict | None:
    prior = sponsor.get("prior_sponsor_id")
    if prior is None:
        return None
    return sponsors_by_key.get((sponsor.get("directive_id"), int(prior)))


def auction_parent(
    sponsor: dict,
    earlier: list[dict],
    max_age_sec: float,
) -> dict | None:
    side = sponsor.get("side")
    lo_tick, hi_tick = range_ticks(sponsor)
    candidates = []
    for prior in earlier:
        if prior.get("side") != side:
            continue
        age = (sponsor["_ts"] - prior["_ts"]).total_seconds()
        if age < 0 or age > max_age_sec:
            continue
        prior_lo, prior_hi = range_ticks(prior)
        if side == "Demand" and prior_hi < lo_tick:
            candidates.append(prior)
        elif side == "Supply" and prior_lo > hi_tick:
            candidates.append(prior)
    if not candidates:
        return None
    return max(candidates, key=lambda item: item["_ts"])


def load_extension_rows(path: Path | None, day: str) -> list[dict]:
    if path is None or not path.exists():
        return []
    rows = []
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            if row.get("date") != day:
                continue
            ts = row.get("encounter_et")
            if not ts:
                continue
            row["_ts"] = datetime.fromisoformat(f"{day}T{ts}").replace(tzinfo=NY)
            rows.append(row)
    rows.sort(key=lambda row: row["_ts"])
    return rows


def nearest_supply_after(
    extension_rows: list[dict],
    symbol_dir: str,
    start: datetime,
    horizon_sec: float,
) -> dict | None:
    end = start + timedelta(seconds=horizon_sec)
    for row in extension_rows:
        if row.get("symbol") != symbol_dir:
            continue
        ts = row["_ts"]
        if start <= ts <= end:
            return row
    return None


def failure_maps(runtime: dict[str, list[dict]]) -> tuple[dict[tuple[str, int], dict], dict[tuple[str, int], dict]]:
    failed = {}
    context = {}
    for row in runtime["sponsor_failed"]:
        failed[(row.get("directive_id"), int(row.get("sponsor_id")))] = row
    for row in runtime["sponsor_failure_context"]:
        context[(row.get("directive_id"), int(row.get("sponsor_id")))] = row
    return failed, context


def capture_health(symbol: str, day: str, start_et: datetime, end_et: datetime) -> tuple[pl.DataFrame, pl.DataFrame]:
    symbol_dir = scp.RUNTIME[symbol]["symbol_dir"]
    load_start = start_et - timedelta(minutes=10)
    load_end = end_et + timedelta(minutes=10)
    ticks_df = load_capture_window("ticks", symbol_dir, load_start, load_end, tick_columns(), inclusive_end=True)
    snaps_df = load_capture_window("snapshots", symbol_dir, load_start, load_end, snapshot_columns(DEPTH_LEVELS), inclusive_end=True)
    return ticks_df, snaps_df


def classify_authority(
    *,
    symbol: str,
    has_parent: bool,
    is_directive_child: bool,
    gap_ticks: int,
    low_interaction_ratio: float | None,
    pocket_flow_per_tick_sec: float | None,
    pocket_mid_ratio: float | None,
    post_consequence: str,
    old60: float,
    old180: float,
    next_same_delay: float | None,
    formal_failed: bool,
    root_distance: float | None,
    failure_prior_live: bool | None,
) -> tuple[str, str, str]:
    accepted = post_consequence in {
        "accepted_beyond",
        "accepted_after_minor_retest",
        "chained_extension",
        "repair_survived",
    }
    chained = next_same_delay is not None and next_same_delay <= 120.0
    flow_threshold = 0.60 if symbol == "ES" else 0.15
    low_pocket = (
        gap_ticks >= 4
        and (
            (low_interaction_ratio is not None and low_interaction_ratio <= 0.45)
            or (pocket_flow_per_tick_sec is not None and pocket_flow_per_tick_sec <= flow_threshold)
        )
    )
    fast_or_add = is_directive_child or (root_distance is not None and root_distance >= 20)
    reopened = old60 >= 0.10 or old180 >= 0.15

    if not has_parent:
        return "campaign_base", "base_or_reissue", "No lower same-side parent was found inside the auction-parent window."

    if low_pocket and (accepted or chained) and old60 <= 0.05:
        if formal_failed or reopened:
            return (
                "auction_separated_child_failed",
                "all_flat_reasonable",
                "Low-interaction pocket plus accepted/chained worse-price business later reopened or failed.",
            )
        return (
            "auction_separated_child",
            "promotion_valid_if_current",
            "Low-interaction pocket plus accepted/chained worse-price business made the child a plausible campaign authority.",
        )

    if accepted and old60 <= 0.05 and gap_ticks >= 4:
        if formal_failed and failure_prior_live:
            return (
                "accepted_child_prior_live",
                "fifo_flat_may_be_too_blunt",
                "Post-child acceptance was clean, but failure context still had older same-side sponsorship alive.",
            )
        return (
            "accepted_child_no_clear_pocket",
            "promotion_partly_supported",
            "Post-child acceptance was clean, but the parent-child pocket was not clearly low-interaction.",
        )

    if reopened and post_consequence == "passed_through_no_restack":
        if formal_failed and failure_prior_live:
            return (
                "provisional_child_failed_prior_live",
                "campaign_failure_not_proven",
                "Upper attempt reopened old prices and failed while older same-side sponsorship was still alive.",
            )
        return (
            "upper_attempt_reopened",
            "avoid_or_flatten_attempt",
            "Upper attempt spent meaningful time back in old prices before proving separated acceptance.",
        )

    if fast_or_add and reopened:
        if formal_failed and failure_prior_live:
            return (
                "provisional_child_failed_prior_live",
                "campaign_failure_not_proven",
                "Fresh/add child reopened old prices and failed while older same-side sponsorship was still alive.",
            )
        return (
            "provisional_child_reopened",
            "repair_expected",
            "Fresh/add child made old prices available again before proving separated acceptance.",
        )

    if fast_or_add:
        return (
            "provisional_child_unresolved",
            "promotion_unproven",
            "Add/fast child did not show enough pocket separation and acceptance to become campaign authority.",
        )

    return (
        "ordinary_promoted_sponsor",
        "not_child_focus",
        "Promoted sponsor is not clearly an add/fast-child object under this probe.",
    )


def analyze_symbol_window(
    args: argparse.Namespace,
    symbol: str,
    window: str,
    extension_rows: list[dict],
) -> tuple[list[dict], dict]:
    start_et, end_et = parse_window(args.date, window)
    start_utc = start_et.astimezone(timezone.utc)
    end_utc = end_et.astimezone(timezone.utc)
    symbol_dir = scp.RUNTIME[symbol]["symbol_dir"]

    ticks_df, snaps_df = capture_health(symbol, args.date, start_et, end_et)
    health = {
        "symbol": symbol,
        "symbol_dir": symbol_dir,
        "window": window,
        "tick_rows": ticks_df.height,
        "snapshot_rows": snaps_df.height,
        "capture_status": "ok" if ticks_df.height and snaps_df.height else "missing_capture",
    }
    if ticks_df.height == 0 or snaps_df.height == 0:
        return [], health

    base_rows = scp.analyze_symbol(symbol, args.date, start_et, end_et)
    base_by_key = {row_key(row): row for row in base_rows}

    runtime = scp.load_runtime(symbol, start_utc, end_utc)
    all_sponsors = [
        row
        for row in runtime["sponsor_promoted"]
        if row.get("side") == "Demand"
        and start_et - timedelta(minutes=args.auction_parent_minutes) <= row["_ts"].astimezone(NY) <= end_et
    ]
    all_sponsors.sort(key=lambda row: row["_ts"])
    sponsors_in_window = [row for row in all_sponsors if start_utc <= row["_ts"] <= end_utc]
    sponsors_by_key = {sponsor_key(row): row for row in all_sponsors}
    failed_map, context_map = failure_maps(runtime)
    tactical_ids = {(row.get("directive_id"), int(row.get("child_id"))) for row in runtime["reference_break_tactical_child"]}

    ticks = ticks_df.to_dicts()
    snapshots = snaps_df.to_dicts()
    tick_us = [int(row["timestamp_us"]) for row in ticks]

    rows = []
    earlier: list[dict] = []
    for sponsor in all_sponsors:
        if sponsor in sponsors_in_window:
            key = sponsor_key(sponsor)
            base = base_by_key.get(key)
            if base is None:
                earlier.append(sponsor)
                continue
            dparent = directive_parent(sponsor, sponsors_by_key)
            aparent = auction_parent(sponsor, earlier, args.auction_parent_minutes * 60.0)
            parent = dparent or aparent
            parent_scope = "directive" if dparent is not None else ("auction" if aparent is not None else "")
            sponsor_lo_tick, sponsor_hi_tick = range_ticks(sponsor)

            gap_ticks = 0
            travel_sec = ""
            pocket_range = ""
            pocket_volume = ""
            pocket_trades = ""
            pocket_density = ""
            pocket_flow = None
            parent_density = ""
            pocket_density_ratio = None
            pocket_mid_sec = ""
            pocket_mid_ratio = None
            parent_time = ""
            parent_range = ""

            if parent is not None:
                parent_lo_tick, parent_hi_tick = range_ticks(parent)
                parent_time = ny_hms(parent["_ts"])
                parent_range = f"{tick_to_price(parent_lo_tick):.2f}-{tick_to_price(parent_hi_tick):.2f}"
                gap_lo = parent_hi_tick + 1
                gap_hi = sponsor_lo_tick - 1
                gap_ticks = max(0, gap_hi - gap_lo + 1)
                if gap_ticks > 0:
                    pocket_range = f"{tick_to_price(gap_lo):.2f}-{tick_to_price(gap_hi):.2f}"
                parent_us = us(parent["_ts"])
                child_us = us(sponsor["_ts"])
                travel = max(0.0, (child_us - parent_us) / 1_000_000.0)
                travel_sec = round(travel, 3)
                between = tick_rows_between(ticks, tick_us, parent_us, child_us)
                pvol, ptrades, _, _ = volume_in_ticks(between, gap_lo, gap_hi)
                par_vol, _, _, _ = volume_in_ticks(between, parent_lo_tick, parent_hi_tick)
                pden = pvol / max(1, gap_ticks)
                par_width = max(1, parent_hi_tick - parent_lo_tick + 1)
                parden = par_vol / par_width
                pocket_flow = pden / max(1.0, travel)
                pocket_volume = round(pvol, 3)
                pocket_trades = ptrades
                pocket_density = round(pden, 3)
                parent_density = round(parden, 3)
                if parden > 0:
                    pocket_density_ratio = pden / parden
                mid_sec = mid_time_in_ticks(snapshots, parent_us, child_us, gap_lo, gap_hi)
                pocket_mid_sec = round(mid_sec, 3)
                if travel > 0:
                    pocket_mid_ratio = mid_sec / travel

            failure = failed_map.get(key)
            context = context_map.get(key)
            formal_failed = failure is not None or parse_bool(base.get("failed_formally"))
            failure_delay = ""
            failure_et = ""
            if failure is not None:
                failure["_ts"] = scp.parse_utc(failure["ts_utc"]) if "_ts" not in failure else failure["_ts"]
                failure_et = ny_hms(failure["_ts"])
                failure_delay = round((failure["_ts"] - sponsor["_ts"]).total_seconds(), 3)
            failure_prior_live = None
            same_side_protection = ""
            adverse_ahead = ""
            if context is not None:
                failure_prior_live = parse_bool(context.get("prior_sponsor_live"))
                same_side_protection = context.get("live_same_side_protection_count", "")
                adverse_ahead = context.get("live_adverse_ahead_count", "")

            root_distance = parse_float(base.get("root_distance_ticks"))
            old60 = parse_float(base.get("old_time_ratio_60s")) or 0.0
            old180 = parse_float(base.get("old_time_ratio_180s")) or 0.0
            beyond60 = parse_float(base.get("beyond_time_ratio_60s")) or 0.0
            next_same = parse_float(base.get("next_same_side_sponsor_delay_sec"))
            is_directive_child = (
                dparent is not None
                or base.get("order_role") == "Add"
                or base.get("promotion_reason") == "accepted_same_side_ownership"
                or key in tactical_ids
            )
            authority, action_read, reason = classify_authority(
                symbol=symbol,
                has_parent=parent is not None,
                is_directive_child=is_directive_child,
                gap_ticks=gap_ticks,
                low_interaction_ratio=pocket_density_ratio,
                pocket_flow_per_tick_sec=pocket_flow,
                pocket_mid_ratio=pocket_mid_ratio,
                post_consequence=str(base.get("post_sponsor_consequence") or ""),
                old60=old60,
                old180=old180,
                next_same_delay=next_same,
                formal_failed=formal_failed,
                root_distance=root_distance,
                failure_prior_live=failure_prior_live,
            )

            supply = nearest_supply_after(extension_rows, symbol_dir, sponsor["_ts"].astimezone(NY), args.supply_horizon_sec)
            rows.append(
                {
                    "date": args.date,
                    "window": window,
                    "symbol": symbol,
                    "time_et": ny_hms(sponsor["_ts"]),
                    "sponsor_id": sponsor.get("sponsor_id"),
                    "directive_id": sponsor.get("directive_id"),
                    "sponsor_range": base.get("range"),
                    "role": base.get("order_role") or base.get("promotion_reason"),
                    "root_distance_ticks": base.get("root_distance_ticks"),
                    "parent_scope": parent_scope,
                    "parent_time_et": parent_time,
                    "parent_range": parent_range,
                    "gap_ticks": gap_ticks,
                    "pocket_range": pocket_range,
                    "travel_sec": travel_sec,
                    "pocket_volume": pocket_volume,
                    "pocket_trades": pocket_trades,
                    "pocket_density_per_tick": pocket_density,
                    "pocket_flow_per_tick_sec": "" if pocket_flow is None else round(pocket_flow, 3),
                    "parent_density_per_tick": parent_density,
                    "pocket_density_ratio": "" if pocket_density_ratio is None else round(pocket_density_ratio, 3),
                    "pocket_mid_time_sec": pocket_mid_sec,
                    "pocket_mid_time_ratio": "" if pocket_mid_ratio is None else round(pocket_mid_ratio, 3),
                    "beyond_time_ratio_60s": base.get("beyond_time_ratio_60s"),
                    "old_time_ratio_60s": base.get("old_time_ratio_60s"),
                    "old_time_ratio_180s": base.get("old_time_ratio_180s"),
                    "first_old_price_sec": base.get("first_old_price_sec"),
                    "same_depth_change_after_touch_5s": base.get("same_depth_change_after_touch_5s"),
                    "next_same_side_sponsor_delay_sec": base.get("next_same_side_sponsor_delay_sec"),
                    "post_sponsor_consequence": base.get("post_sponsor_consequence"),
                    "failed_formally": formal_failed,
                    "failure_et": failure_et,
                    "failure_delay_sec": failure_delay,
                    "failure_prior_sponsor_live": "" if failure_prior_live is None else failure_prior_live,
                    "failure_same_side_protection_count": same_side_protection,
                    "failure_adverse_ahead_count": adverse_ahead,
                    "post_supply_et": ny_hms(supply["_ts"]) if supply else "",
                    "post_supply_range": supply.get("supply_range") if supply else "",
                    "post_supply_label": supply.get("label") if supply else "",
                    "authority_label": authority,
                    "action_read": action_read,
                    "reason": reason,
                }
            )
        earlier.append(sponsor)

    return rows, health


def write_outputs(rows: list[dict], health: list[dict], out_dir: Path, args: argparse.Namespace) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    fields = list(rows[0].keys()) if rows else [
        "date",
        "window",
        "symbol",
        "time_et",
        "authority_label",
        "action_read",
    ]
    with (out_dir / "auction_separation_child_rows.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    with (out_dir / "capture_health.csv").open("w", encoding="utf-8", newline="") as handle:
        fields_health = ["symbol", "symbol_dir", "window", "tick_rows", "snapshot_rows", "capture_status"]
        writer = csv.DictWriter(handle, fieldnames=fields_health)
        writer.writeheader()
        writer.writerows(health)

    counts = Counter(row["authority_label"] for row in rows)
    action_counts = Counter(row["action_read"] for row in rows)
    md = [
        f"# Auction Separation Child Probe - {args.date}",
        "",
        "Research-only generated output. This does not change EAR or LevelLedger behavior.",
        "",
        "## Configuration",
        "",
        f"- windows: `{','.join(args.windows)}`",
        f"- symbols: `{','.join(args.symbols)}`",
        f"- auction parent lookback: `{args.auction_parent_minutes}` minutes",
        "- low-pocket flow heuristic: ES `<=0.60`, NQ `<=0.15` contracts/tick/second",
        f"- supply join horizon: `{args.supply_horizon_sec}` seconds",
        "",
        "## Capture Health",
        "",
        "| Symbol | Window | Ticks | Snapshots | Status |",
        "|---|---:|---:|---:|---|",
    ]
    for row in health:
        md.append(
            f"| {row['symbol']} | {row['window']} | {row['tick_rows']} | {row['snapshot_rows']} | {row['capture_status']} |"
        )
    md.extend(["", "## Label Counts", ""])
    for label, count in counts.most_common():
        md.append(f"- `{label}`: {count}")
    md.extend(["", "## Action Reads", ""])
    for label, count in action_counts.most_common():
        md.append(f"- `{label}`: {count}")

    md.extend(
        [
            "",
            "## Rows",
            "",
            "| Symbol | Time | Sponsor | Role | Root Dist | Parent | Gap | Pocket Ratio | Beyond60 | Old60 | Next Same | Failed | Supply Label | Authority | Action |",
            "|---|---:|---|---|---:|---|---:|---:|---:|---:|---:|---|---|---|---|",
        ]
    )
    for row in rows:
        parent = row["parent_range"] if row["parent_range"] else ""
        md.append(
            f"| {row['symbol']} | {row['time_et']} | {row['sponsor_range']} | {row['role']} | "
            f"{row['root_distance_ticks']} | {parent} | {row['gap_ticks']} | {row['pocket_density_ratio']} | "
            f"{row['beyond_time_ratio_60s']} | {row['old_time_ratio_60s']} | {row['next_same_side_sponsor_delay_sec']} | "
            f"{row['failed_formally']} | {row['post_supply_label']} | {row['authority_label']} | {row['action_read']} |"
        )

    md.extend(
        [
            "",
            "## Read Notes",
            "",
            "- `auction_separated_child` means a child had a measurable parent-child gap, low pocket interaction, and then accepted or chained business at worse prices.",
            "- `auction_separated_child_failed` means that separated upper business later failed or reopened old prices; FIFO all-flat is structurally more defensible here.",
            "- `provisional_child_failed_prior_live` means the child failed while an older same-side sponsor was still live in EAR failure context; that is the clearest case where all-flat may abandon a still-valid thesis.",
            "- `accepted_child_no_clear_pocket` means post-event acceptance looked good, but the parent-child area was not sparse enough to prove auction separation.",
            "- Missing capture rows are skipped rather than treated as fragile sponsors.",
        ]
    )
    (out_dir / "summary.md").write_text("\n".join(md) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default="2026-08-21")
    parser.add_argument("--windows", nargs="+", default=["10:20-12:00"])
    parser.add_argument("--symbols", default="ES,NQ")
    parser.add_argument("--auction-parent-minutes", type=float, default=45.0)
    parser.add_argument("--supply-horizon-sec", type=float, default=360.0)
    parser.add_argument("--extension-csv", type=Path)
    parser.add_argument("--out-dir", type=Path, default=Path("research/out/auction_separation_child"))
    args = parser.parse_args()
    args.symbols = [item.strip() for item in args.symbols.split(",") if item.strip()]

    extension_rows = load_extension_rows(args.extension_csv, args.date)
    rows: list[dict] = []
    health: list[dict] = []
    for window in args.windows:
        for symbol in args.symbols:
            symbol_rows, symbol_health = analyze_symbol_window(args, symbol, window, extension_rows)
            rows.extend(symbol_rows)
            health.append(symbol_health)
    rows.sort(key=lambda row: (row["date"], row["window"], row["symbol"], row["time_et"], int(row["sponsor_id"])))
    write_outputs(rows, health, args.out_dir, args)
    print(f"wrote {len(rows)} rows to {args.out_dir}")


if __name__ == "__main__":
    main()
