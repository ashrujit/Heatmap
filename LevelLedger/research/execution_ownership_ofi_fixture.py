"""Overlay event OFI on an EAR/LevelLedger execution fixture.

This tool is intentionally fixture-oriented. It samples event-level best-book
OFI at exact EAR order/sponsor events and runtime LL ownership/failure
transitions, plus a one-second grid for finding possible OFI-only high-failure
claims. It does not change live policy or optimize a threshold.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "research"))

from candidate_timing_probe import load_filtered_snapshots  # noqa: E402
from capture_loader import MARKET_RECORDER_ROOT, us  # noqa: E402
from event_ofi_probe import SessionSpec, sample_anchor_rows  # noqa: E402
from snapshot_ofi_proxy_probe import (  # noqa: E402
    NY,
    add_metrics,
    build_snapshot_series,
    build_tick_series,
    load_ticks,
    parse_window,
    write_csv,
)


EVIDENCE_KINDS = {
    "CandidateFormed",
    "CandidateDisplacementStarted",
    "CandidateDisplacementReset",
    "RailOwned",
    "RailTested",
    "RailHeld",
    "RailFailed",
    "FailureCandidateFormed",
    "FailureHeld",
}
EAR_EVENTS = {
    "directive_accepted",
    "directive_invalidated",
    "order_submit",
    "trade_fill",
    "sponsor_promoted",
    "sponsor_failed",
    "sponsor_cleared",
    "breakeven_place",
    "flatten_result",
}


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def event_time(event: dict) -> datetime | None:
    if event.get("event") == "evidence_transition":
        return parse_iso(event.get("event_utc"))
    if event.get("event") == "order_submit":
        return parse_iso(event.get("trigger_utc"))
    return parse_iso(event.get("ts_utc"))


def band_side(event: dict) -> str | None:
    side = event.get("band_side") or event.get("side")
    if side is None and event.get("event") == "order_submit":
        side = "Demand" if str(event.get("side", "")).lower() == "long" else "Supply"
    value = str(side).lower() if side is not None else ""
    if value in ("demand", "long"):
        return "demand"
    if value in ("supply", "short"):
        return "supply"
    return None


def price_from_event(event: dict) -> float | None:
    for key in ("trigger_ask", "fill_price", "price", "ask", "bid"):
        value = event.get(key)
        try:
            result = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(result) and result > 0:
            return result
    mid_tick = event.get("mid_tick")
    try:
        return float(mid_tick) * 0.25
    except (TypeError, ValueError):
        return None


def load_ear_anchors(path: str, start: datetime, end: datetime) -> list[dict]:
    rows: list[dict] = []
    with open(path, "r", encoding="utf-8") as stream:
        for line in stream:
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            name = event.get("event")
            if name == "evidence_transition":
                if event.get("kind") not in EVIDENCE_KINDS:
                    continue
            elif name not in EAR_EVENTS:
                continue
            ts = event_time(event)
            if ts is None or ts < start or ts > end:
                continue
            side = band_side(event)
            rows.append(
                {
                    "source": "LL" if name == "evidence_transition" else "EAR",
                    "event": name,
                    "kind": event.get("kind"),
                    "reason": event.get("reason"),
                    "directive_id": event.get("directive_id"),
                    "role": event.get("role"),
                    "resolution": event.get("resolution"),
                    "candidate_id": event.get("candidate_id"),
                    "candidate_side": event.get("candidate_side"),
                    "candidate_direction": event.get("candidate_direction"),
                    "band_id": event.get("band_id") or event.get("sponsor_id") or event.get("root_object_id"),
                    "band_role": event.get("band_role"),
                    "band_side": side,
                    "band_source": event.get("band_source") or event.get("source"),
                    "band_state": event.get("band_state"),
                    "band_low": (
                        float(event["band_min_tick"]) * 0.25
                        if event.get("band_min_tick") is not None
                        else event.get("lower") or event.get("root_min_price")
                    ),
                    "band_high": (
                        float(event["band_max_tick"]) * 0.25
                        if event.get("band_max_tick") is not None
                        else event.get("upper") or event.get("root_max_price")
                    ),
                    "price": price_from_event(event),
                    "quantity": event.get("quantity"),
                    "anchor_et": ts.astimezone(NY).isoformat(),
                    "_anchor_us": us(ts),
                    "_side_sign": 1,
                }
            )
    return rows


def add_snapshot_context(rows: list[dict], snapshots, ticks) -> None:
    for row in rows:
        ts = datetime.fromtimestamp(int(row["_anchor_us"]) / 1_000_000, timezone.utc)
        add_metrics(row, ts, 1, snapshots, ticks)
        idx = snapshots.index_at(ts)
        if idx is not None:
            row["snapshot_mid"] = snapshots.mid_ticks[idx] * 0.25


def add_owner_alignment(rows: list[dict]) -> None:
    for row in rows:
        side = row.get("band_side")
        sign = 1 if side == "demand" else -1 if side == "supply" else None
        for key in (
            "event_ofi_3s",
            "event_ofi_5s",
            "event_ofi_10s",
            "event_ofi_500e",
            "event_ofi_1000e",
        ):
            value = row.get(key)
            row[f"owner_aligned_{key}"] = sign * float(value) if sign and value is not None else None
        three = row.get("owner_aligned_event_ofi_3s")
        five = row.get("owner_aligned_event_ofi_5s")
        if three is None or five is None:
            row["ofi_owner_read"] = "unknown"
        elif three > 0 and five > 0:
            row["ofi_owner_read"] = "supports"
        elif three < 0 and five < 0:
            row["ofi_owner_read"] = "opposes"
        else:
            row["ofi_owner_read"] = "mixed"


def grid_rows(start: datetime, end: datetime) -> list[dict]:
    rows: list[dict] = []
    ts = start.replace(microsecond=0)
    while ts <= end:
        rows.append(
            {
                "source": "GRID",
                "event": "one_second",
                "kind": None,
                "reason": None,
                "directive_id": None,
                "role": None,
                "resolution": None,
                "candidate_id": None,
                "candidate_side": None,
                "candidate_direction": None,
                "band_id": None,
                "band_role": None,
                "band_side": None,
                "band_source": None,
                "band_state": None,
                "band_low": None,
                "band_high": None,
                "price": None,
                "quantity": None,
                "anchor_et": ts.astimezone(NY).isoformat(),
                "_anchor_us": us(ts),
                "_side_sign": 1,
            }
        )
        ts += timedelta(seconds=1)
    return rows


def future_range(grid: list[dict], index: int, seconds: int = 30) -> tuple[float | None, float | None]:
    base = grid[index].get("snapshot_mid")
    if base is None:
        return None, None
    values = [
        float(row["snapshot_mid"])
        for row in grid[index + 1 : index + seconds + 1]
        if row.get("snapshot_mid") is not None
    ]
    if not values:
        return None, None
    return (max(values) - float(base)) / 0.25, (min(values) - float(base)) / 0.25


def find_ofi_only_high_failures(
    grid: list[dict],
    hf_times_us: list[int],
    discovery_start_us: int,
) -> list[dict]:
    values = [float(row["event_ofi_5s"]) for row in grid if row.get("event_ofi_5s") is not None]
    if not values:
        return []
    ordered = sorted(values)
    # Permissive discovery screen, not a proposed live threshold. The lower
    # quintile exposes local failures that the z-score gate may miss; future
    # response labels this fixture only.
    threshold = ordered[max(0, int(0.20 * len(ordered)) - 1)]
    candidates: list[dict] = []
    prior_prices: list[float] = []
    last_kept_us = 0
    for index, row in enumerate(grid):
        price = row.get("snapshot_mid")
        value3 = row.get("event_ofi_3s")
        value5 = row.get("event_ofi_5s")
        if price is None or value3 is None or value5 is None:
            continue
        prior_prices.append(float(price))
        prior_prices = prior_prices[-300:]
        if float(value3) >= 0 or float(value5) > threshold:
            continue
        if float(price) < max(prior_prices) - 2.0:
            continue
        anchor_us = int(row["_anchor_us"])
        if anchor_us < discovery_start_us:
            continue
        if any(abs(anchor_us - hf_us) <= 15_000_000 for hf_us in hf_times_us):
            continue
        if anchor_us - last_kept_us < 30_000_000:
            continue
        up_ticks, down_ticks = future_range(grid, index, 30)
        if down_ticks is None or down_ticks > -8:
            continue
        candidates.append(
            {
                "anchor_et": row["anchor_et"],
                "price": price,
                "event_ofi_3s": value3,
                "event_ofi_5s": value5,
                "window_q20_threshold": threshold,
                "future_up_30s_ticks": up_ticks,
                "future_down_30s_ticks": down_ticks,
            }
        )
        last_kept_us = anchor_us
    return candidates


def summarize(rows: list[dict], grid: list[dict], health, ofi_only: list[dict]) -> str:
    lines = [
        "Execution ownership + OFI fixture",
        f"event_rows={health.rows_processed} gaps={health.gaps} repairs={health.repair_events}",
        "",
        "EAR actions and ownership decisions",
    ]
    keep_events = {
        "order_submit",
        "sponsor_promoted",
        "sponsor_failed",
        "directive_invalidated",
        "breakeven_place",
        "flatten_result",
    }
    for row in rows:
        if row["event"] not in keep_events and row.get("kind") not in {
            "RailOwned",
            "RailFailed",
            "FailureHeld",
        }:
            continue
        ts = datetime.fromisoformat(row["anchor_et"]).strftime("%H:%M:%S")
        label = row.get("kind") or row.get("event")
        identity = row.get("band_id") or row.get("directive_id") or "-"
        lines.append(
            f"  {ts} {label:<22} id={str(identity):<12} side={str(row.get('band_side') or '-'):<6} "
            f"px={row.get('price') or row.get('snapshot_mid')} "
            f"ofi3/5={row.get('event_ofi_3s')!s}/{row.get('event_ofi_5s')!s} "
            f"owner={row.get('ofi_owner_read')} reason={row.get('reason') or row.get('role') or ''}"
        )
    lines.extend(["", "Exploratory OFI-only high-failure candidates (not live-qualified)"])
    if not ofi_only:
        lines.append("  (none)")
    for row in ofi_only:
        lines.append(
            f"  {datetime.fromisoformat(row['anchor_et']).strftime('%H:%M:%S')} "
            f"px={float(row['price']):.2f} ofi3/5={float(row['event_ofi_3s']):.2f}/"
            f"{float(row['event_ofi_5s']):.2f} future30 down/up="
            f"{float(row['future_down_30s_ticks']):.1f}/{float(row['future_up_30s_ticks']):.1f}t"
        )
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", required=True)
    parser.add_argument("--symbol-dir", default="NQU6")
    parser.add_argument("--window", default="11:30-12:30")
    parser.add_argument(
        "--ear-events",
        default=os.path.expandvars(r"%USERPROFILE%\Documents\ExecAssistantRuntime\events.jsonl"),
    )
    parser.add_argument("--capture-root", default=MARKET_RECORDER_ROOT)
    parser.add_argument("--out-dir", default=str(ROOT / "research" / "out"))
    parser.add_argument("--context-min", type=int, default=5)
    parser.add_argument("--max-carry-days", type=int, default=7)
    args = parser.parse_args()

    start, end = parse_window(args.date, args.window)
    context_start = start - timedelta(minutes=args.context_min)
    metric_start = context_start - timedelta(seconds=65)
    metric_end = end + timedelta(seconds=65)
    spec = SessionSpec(args.date, args.symbol_dir, f"{context_start:%H:%M}-{end:%H:%M}")

    snapshots_df = load_filtered_snapshots(
        args.capture_root,
        args.symbol_dir,
        args.date,
        metric_start,
        metric_end,
    )
    snapshots = build_snapshot_series(snapshots_df, 5.0)
    ticks = build_tick_series(load_ticks(args.capture_root, spec, metric_start, metric_end))

    event_rows = load_ear_anchors(args.ear_events, context_start, end)
    grid = grid_rows(context_start, end)
    all_rows = event_rows + grid
    add_snapshot_context(all_rows, snapshots, ticks)
    health = sample_anchor_rows(
        args.capture_root,
        spec,
        all_rows,
        end,
        args.max_carry_days,
    )
    add_owner_alignment(event_rows)

    hf_times_us = [
        int(row["_anchor_us"])
        for row in event_rows
        if row.get("kind") == "FailureHeld" and row.get("reason") == "HF"
    ]
    ofi_only = find_ofi_only_high_failures(grid, hf_times_us, us(start))
    summary = summarize(event_rows, grid, health, ofi_only)

    for row in all_rows:
        row.pop("_anchor_us", None)
        row.pop("_side_sign", None)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    prefix = out_dir / f"execution_ownership_ofi_{args.date}_{args.window.replace(':', '')}"
    summary_path = prefix.with_suffix(".txt")
    events_path = Path(str(prefix) + "_events.csv")
    grid_path = Path(str(prefix) + "_grid.csv")
    ofi_only_path = Path(str(prefix) + "_ofi_only_hf.csv")
    summary_path.write_text(summary, encoding="utf-8")
    write_csv(events_path, event_rows)
    write_csv(grid_path, grid)
    write_csv(ofi_only_path, ofi_only)
    print(summary, end="")
    print(f"outputs:\n  {summary_path}\n  {events_path}\n  {grid_path}\n  {ofi_only_path}")


if __name__ == "__main__":
    main()
