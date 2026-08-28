"""Counterfactual add and entry-mode study for 2026-08-27 Kahn decisions."""

from __future__ import annotations

import argparse
import csv
import json
import sqlite3
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from capture_loader import load_capture_window, tick_columns

sys.path.insert(0, str(Path(__file__).resolve().parent))
from analyze_gexbot_kahn_20260827 import (
    as_float,
    attach_next_state,
    compressed_policy_runs,
    fmt,
    latest_gex,
    nearest_field,
    parse_utc,
    price_from_decision,
    read_log,
)


TICK_SIZE = 0.25
BROKER_ACTIONS = {"AllowProbe", "AllowAdd", "Reduce", "Flatten", "Retire"}
EXIT_ACTIONS = {"Reduce", "Flatten", "Retire"}
SYMBOL_DIR = {"ES": "ESU6", "NQ": "NQU6"}
TICKER = {"ES": "ES_SPX", "NQ": "NQ_NDX"}
SIDE_TO_EVIDENCE = {"Long": "Demand", "Short": "Supply"}
OPPOSITE_FILL_SIDE = {"Long": "Short", "Short": "Long"}
EDT = timezone(timedelta(hours=-4), "America/New_York")


@dataclass
class Row:
    symbol: str
    line: int
    payload: dict[str, Any]

    @property
    def ts(self) -> datetime | None:
        return parse_utc(self.payload.get("ts_utc"))

    @property
    def et(self) -> str:
        return et(self.ts)


def iso_z(dt: datetime | None) -> str:
    if dt is None:
        return ""
    return dt.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def et(dt: datetime | None) -> str:
    if dt is None:
        return ""
    return dt.astimezone(EDT).strftime("%H:%M:%S")


def side_sign(side: str) -> int:
    return 1 if side == "Long" else -1


def parse_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


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


def load_rows(runtime_dir: Path, session_date: str) -> list[Row]:
    rows = []
    for symbol in ("ES", "NQ"):
        for log_row in read_log(runtime_dir / symbol / "decisions.jsonl", symbol, session_date):
            rows.append(Row(log_row.symbol, log_row.line, log_row.payload))
    rows.sort(key=lambda row: (row.ts or datetime.min.replace(tzinfo=timezone.utc), row.symbol, row.line))
    return rows


def campaign_meta(rows: list[Row]) -> dict[tuple[str, str], dict[str, Any]]:
    meta: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        if row.payload.get("event") != "campaign_loaded":
            continue
        cid = row.payload.get("campaign_id")
        if not cid:
            continue
        meta[(row.symbol, cid)] = {
            "side": row.payload.get("side"),
            "probe_quantity": row.payload.get("probe_quantity"),
            "add_quantity": row.payload.get("add_quantity"),
            "max_position": row.payload.get("campaign_max_position_quantity"),
            "status": row.payload.get("status"),
            "notes": row.payload.get("notes"),
            "loaded_ts": row.payload.get("ts_utc"),
        }
    return meta


def same_side(meta: dict[str, Any], evidence_side: Any) -> bool:
    side = meta.get("side")
    expected = SIDE_TO_EVIDENCE.get(str(side))
    return expected is not None and evidence_side == expected


def tick_window_stats(symbol: str,
    start: datetime,
    minutes: float,
    price: float,
    side: str) -> dict[str, Any]:
    end = start + timedelta(minutes=minutes)
    try:
        df = load_capture_window("ticks", SYMBOL_DIR[symbol], start, end, tick_columns())
    except Exception as exc:
        return {f"{int(minutes)}m_error": str(exc)}
    if df.is_empty():
        return {
            f"{int(minutes)}m_high": "",
            f"{int(minutes)}m_low": "",
            f"{int(minutes)}m_last": "",
            f"{int(minutes)}m_mfe": "",
            f"{int(minutes)}m_mae": "",
            f"{int(minutes)}m_end": "",
        }
    df = df.sort("timestamp_us")
    high = float(df["price"].max())
    low = float(df["price"].min())
    last = float(df["price"].tail(1)[0])
    if side == "Long":
        mfe = high - price
        mae = price - low
        end_move = last - price
    else:
        mfe = price - low
        mae = high - price
        end_move = price - last
    prefix = f"{int(minutes)}m"
    return {
        f"{prefix}_high": high,
        f"{prefix}_low": low,
        f"{prefix}_last": last,
        f"{prefix}_mfe": mfe,
        f"{prefix}_mae": mae,
        f"{prefix}_end": end_move,
    }


def limit_fill_delay(symbol: str,
    start: datetime,
    seconds: int,
    limit_price: float,
    side: str) -> tuple[float | None, float | None]:
    end = start + timedelta(seconds=seconds)
    try:
        df = load_capture_window("ticks", SYMBOL_DIR[symbol], start, end, tick_columns())
    except Exception:
        return None, None
    if df.is_empty():
        return None, None
    if side == "Long":
        hits = df.filter(df["price"] <= limit_price).sort("timestamp_us")
    else:
        hits = df.filter(df["price"] >= limit_price).sort("timestamp_us")
    if hits.is_empty():
        return None, None
    first_us = int(hits["timestamp_us"][0])
    return limit_price, (first_us / 1_000_000.0) - start.timestamp()


def add_future_metrics(row: dict[str, Any], symbol: str, ts: datetime, price: float, side: str) -> None:
    for minutes in (5, 15, 30, 60):
        row.update(tick_window_stats(symbol, ts, minutes, price, side))
    for offset_ticks in (1, 2, 4):
        limit_price = price - offset_ticks * TICK_SIZE if side == "Long" else price + offset_ticks * TICK_SIZE
        filled, delay = limit_fill_delay(symbol, ts, 120, limit_price, side)
        row[f"limit_{offset_ticks}t_price"] = limit_price
        row[f"limit_{offset_ticks}t_fill_delay_s"] = "" if delay is None else round(delay, 3)
        if filled is None:
            row[f"limit_{offset_ticks}t_30m_mfe"] = ""
            row[f"limit_{offset_ticks}t_30m_mae"] = ""
            row[f"limit_{offset_ticks}t_30m_end"] = ""
        else:
            stats = tick_window_stats(symbol, ts + timedelta(seconds=max(delay or 0, 0)), 30, filled, side)
            row[f"limit_{offset_ticks}t_30m_mfe"] = stats.get("30m_mfe", "")
            row[f"limit_{offset_ticks}t_30m_mae"] = stats.get("30m_mae", "")
            row[f"limit_{offset_ticks}t_30m_end"] = stats.get("30m_end", "")


def nearest_gex_summary(con: sqlite3.Connection, symbol: str, ts: datetime, price: float) -> dict[str, Any]:
    snap = latest_gex(con, TICKER[symbol], "gex_zero", ts)
    nearest, distance = nearest_field(snap, price)
    return {
        "gex_snapshot_et": et(parse_utc(snap.get("recorded_at_utc"))) if snap else "",
        "zero_gamma": snap.get("zero_gamma") if snap else "",
        "call_wall": snap.get("call_wall") if snap else "",
        "put_wall": snap.get("put_wall") if snap else "",
        "oi_call_wall": snap.get("oi_call_wall") if snap else "",
        "oi_put_wall": snap.get("oi_put_wall") if snap else "",
        "sum_gex_vol": snap.get("sum_gex_vol") if snap else "",
        "nearest_gex": nearest,
        "nearest_gex_distance": distance if distance is not None else "",
    }


def add_candidates(
    rows: list[Row],
    meta_by_campaign: dict[tuple[str, str], dict[str, Any]],
    con: sqlite3.Connection,
) -> list[dict[str, Any]]:
    policy = [row for row in rows if row.payload.get("event") == "policy_decision"]
    attach_next_state(policy, rows)  # type: ignore[arg-type]
    runs = compressed_policy_runs(policy)  # type: ignore[arg-type]
    out: list[dict[str, Any]] = []
    for run in runs:
        cid = run.get("campaign_id")
        symbol = run.get("symbol")
        meta = meta_by_campaign.get((symbol, cid), {})
        side = meta.get("side")
        if side not in ("Long", "Short"):
            continue
        pos = parse_int(run.get("first_pos_before"))
        max_pos = parse_int(meta.get("max_position"))
        if pos <= 0 or (max_pos and pos >= max_pos):
            continue
        if not same_side(meta, run.get("evidence_side")):
            continue
        kind = run.get("evidence_kind")
        if kind not in ("RailOwned", "RailHeld"):
            continue

        action = run.get("action")
        reason = ""
        if action == "HoldRoot":
            reason = "holdroot_shadowed_add"
        elif action == "SuppressAdd":
            reason = f"suppressed_same_side_{run.get('policy')}"
        else:
            continue

        ts = parse_utc(run.get("first_utc"))
        price = as_float(run.get("first_price"))
        if ts is None or price is None:
            continue

        item = {
            "symbol": symbol,
            "candidate_et": et(ts),
            "candidate_utc": iso_z(ts),
            "campaign_id": cid,
            "campaign_side": side,
            "candidate_reason": reason,
            "logged_action": action,
            "logged_policy": run.get("policy"),
            "logged_reason_code": run.get("reason_code"),
            "waypoint_id": run.get("waypoint_id"),
            "evidence_kind": kind,
            "evidence_side": run.get("evidence_side"),
            "first_price": price,
            "run_count": run.get("count"),
            "run_last_et": run.get("last_et"),
            "run_min_price": run.get("min_price"),
            "run_max_price": run.get("max_price"),
            "pos_before": pos,
            "max_position": max_pos,
        }
        item.update(nearest_gex_summary(con, symbol, ts, price))
        add_future_metrics(item, symbol, ts, price, side)
        out.append(item)
    return out


def trade_fill_rows(rows: list[Row]) -> list[Row]:
    return [row for row in rows if row.payload.get("event") == "trade_fill"]


def first_fill_after(rows: list[Row],
    symbol: str,
    line: int,
    side: str,
    max_line_gap: int = 80) -> Row | None:
    for row in rows:
        if row.symbol != symbol or row.line <= line or row.line > line + max_line_gap:
            continue
        if row.payload.get("event") != "trade_fill":
            continue
        if row.payload.get("side") == side:
            return row
    return None


def next_exit_policy(policy: list[Row], entry: Row) -> Row | None:
    cid = entry.payload.get("campaign_id")
    for row in policy:
        if row.symbol != entry.symbol or row.line <= entry.line:
            continue
        if row.payload.get("campaign_id") != cid:
            continue
        if row.payload.get("action") in EXIT_ACTIONS:
            return row
    return None


def probe_rows(
    rows: list[Row],
    meta_by_campaign: dict[tuple[str, str], dict[str, Any]],
    con: sqlite3.Connection,
) -> list[dict[str, Any]]:
    policy = [row for row in rows if row.payload.get("event") == "policy_decision"]
    out: list[dict[str, Any]] = []
    for row in policy:
        if row.payload.get("action") != "AllowProbe":
            continue
        cid = row.payload.get("campaign_id")
        meta = meta_by_campaign.get((row.symbol, cid), {})
        side = meta.get("side")
        if side not in ("Long", "Short"):
            continue
        ts = row.ts
        decision_price = price_from_decision(row.payload)
        entry_fill = first_fill_after(rows, row.symbol, row.line, side)
        entry_price = as_float(entry_fill.payload.get("price")) if entry_fill else decision_price
        exit_policy = next_exit_policy(policy, row)
        exit_fill = None
        actual_points = ""
        exit_action = ""
        exit_et = ""
        exit_price = ""
        if exit_policy is not None:
            exit_action = exit_policy.payload.get("action") or ""
            exit_et = et(exit_policy.ts)
            exit_fill = first_fill_after(rows, row.symbol, exit_policy.line, OPPOSITE_FILL_SIDE[side])
            exit_price_number = as_float(exit_fill.payload.get("price")) if exit_fill else price_from_decision(exit_policy.payload)
            if exit_price_number is not None and entry_price is not None:
                actual_points = (
                    exit_price_number - entry_price
                    if side == "Long"
                    else entry_price - exit_price_number
                )
                exit_price = exit_price_number
        if ts is None or entry_price is None:
            continue
        item = {
            "symbol": row.symbol,
            "entry_et": et(ts),
            "entry_utc": iso_z(ts),
            "campaign_id": cid,
            "campaign_side": side,
            "entry_decision_price": decision_price,
            "entry_fill_price": entry_price,
            "entry_fill_et": et(entry_fill.ts) if entry_fill else "",
            "exit_action": exit_action or "none_in_log",
            "exit_et": exit_et,
            "exit_fill_price": exit_price,
            "actual_points_per_contract": actual_points,
            "policy": row.payload.get("policy"),
            "reason_code": row.payload.get("reason_code"),
            "waypoint_id": row.payload.get("waypoint_id"),
            "evidence_kind": row.payload.get("evidence_kind"),
            "evidence_side": row.payload.get("evidence_side"),
        }
        item.update(nearest_gex_summary(con, row.symbol, ts, entry_price))
        add_future_metrics(item, row.symbol, ts, entry_price, side)
        out.append(item)
    return out


def render_note(adds: list[dict[str, Any]], probes: list[dict[str, Any]], out_dir: Path) -> str:
    lines = [
        "# 2026-08-27 Kahn Counterfactual Adds And Entry Mode",
        "",
        "This pass treats Kahn's logged actions as a baseline and asks where different add or entry mechanics could have mattered.",
        "",
        "## Add Candidates",
        "",
        "| Symbol | ET | Side | Candidate | Logged | Price | 30m MFE | 30m MAE | GEX nearest | GEX dist |",
        "|---|---:|---|---|---|---:|---:|---:|---|---:|",
    ]
    for row in adds:
        lines.append(
            f"| {row['symbol']} | {row['candidate_et']} | {row['campaign_side']} | "
            f"{row['candidate_reason']} | {row['logged_policy']}/{row['logged_reason_code']} | "
            f"{fmt(row['first_price'])} | {fmt(row.get('30m_mfe'))} | {fmt(row.get('30m_mae'))} | "
            f"{row.get('nearest_gex')} | {fmt(row.get('nearest_gex_distance'))} |"
        )
    lines.extend(
        [
            "",
            "## Probe Entries",
            "",
            "| Symbol | ET | Side | Fill | Exit | Actual pts | 5m MFE | 5m MAE | 30m MFE | 30m MAE | Limit 1t fill | Limit 2t fill |",
            "|---|---:|---|---:|---|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for row in probes:
        exit_label = row["exit_action"]
        if row["exit_et"]:
            exit_label += f" {row['exit_et']}"
        lines.append(
            f"| {row['symbol']} | {row['entry_et']} | {row['campaign_side']} | "
            f"{fmt(row['entry_fill_price'])} | {exit_label} | {fmt(row['actual_points_per_contract'])} | "
            f"{fmt(row.get('5m_mfe'))} | {fmt(row.get('5m_mae'))} | "
            f"{fmt(row.get('30m_mfe'))} | {fmt(row.get('30m_mae'))} | "
            f"{row.get('limit_1t_fill_delay_s')} | {row.get('limit_2t_fill_delay_s')} |"
        )
    lines.extend(
        [
            "",
            "## Files",
            "",
            f"- `{out_dir / 'counterfactual_add_candidates.csv'}`",
            f"- `{out_dir / 'probe_entry_mode.csv'}`",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--session-date", default="2026-08-27")
    parser.add_argument("--runtime-dir", default=r"C:\Users\j\Documents\KahnRuntime")
    parser.add_argument("--gex-db", default=r"GexBotMcp\out\gexbot.sqlite")
    parser.add_argument("--out-dir", default=r"research\kahn\out\2026-08-27-gex-kahn")
    args = parser.parse_args()

    rows = load_rows(Path(args.runtime_dir), args.session_date)
    meta = campaign_meta(rows)
    con = sqlite3.connect(args.gex_db)
    con.row_factory = sqlite3.Row

    adds = add_candidates(rows, meta, con)
    probes = probe_rows(rows, meta, con)

    out_dir = Path(args.out_dir)
    write_csv(out_dir / "counterfactual_add_candidates.csv", adds)
    write_csv(out_dir / "probe_entry_mode.csv", probes)
    (out_dir / "counterfactual_summary.md").write_text(
        render_note(adds, probes, out_dir),
        encoding="utf-8",
    )
    print(f"rows={len(rows)} add_candidates={len(adds)} probes={len(probes)} out={out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
