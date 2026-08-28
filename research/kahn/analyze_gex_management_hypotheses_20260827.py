"""Research GEX-management hypotheses across 2026-08-27 ES/NQ auction maps.

This script is intentionally offline and descriptive. It does not propose or
modify Kahn policies. It looks for recurring evidence around:

- harvest / exit discipline near GEX-derived terminal levels;
- add quality around same-side Kahn evidence;
- root probe defensiveness via limit-first touched-price checks.

Outputs stay under research/kahn/out so raw logs/captures remain untouched.
"""

from __future__ import annotations

import argparse
import csv
import json
import sqlite3
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import median
from typing import Any

import polars as pl


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from capture_loader import load_capture_window, tick_columns  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from analyze_gexbot_kahn_20260827 import (  # noqa: E402
    as_float,
    fmt,
    latest_gex,
    parse_utc,
)


NY = timezone(timedelta(hours=-4), "America/New_York")
DATE = "2026-08-27"
SYMBOL_DIR = {"ES": "ESU6", "NQ": "NQU6"}
TICKER = {"ES": "ES_SPX", "NQ": "NQ_NDX"}
POINT_TOLERANCE = {"ES": 1.25, "NQ": 5.0}
TICK_SIZE = {"ES": 0.25, "NQ": 0.25}
GEX_FIELDS = ("zero_gamma", "call_wall", "oi_call_wall", "put_wall", "oi_put_wall")
UPPER_FIELDS = {"call_wall", "oi_call_wall"}
LOWER_FIELDS = {"put_wall", "oi_put_wall"}
KEY_POLICY_ACTIONS = {"AllowProbe", "AllowAdd", "Reduce", "Flatten", "Retire"}


@dataclass
class Touch:
    symbol: str
    ticker: str
    field: str
    minute_utc: datetime
    et: str
    level: float
    distance: float
    side_hint: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    delta: float
    volume_pct: float
    sum_gex_vol: float | None
    zero_gamma: float | None
    call_wall: float | None
    oi_call_wall: float | None
    put_wall: float | None
    oi_put_wall: float | None


def et_dt(hhmmss: str) -> datetime:
    return datetime.fromisoformat(f"{DATE}T{hhmmss}").replace(tzinfo=NY)


def iso_z(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def et_text(dt: datetime | None) -> str:
    return "" if dt is None else dt.astimezone(NY).strftime("%H:%M:%S")


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


def load_1m_bars(symbol: str) -> pl.DataFrame:
    start = et_dt("09:30:00")
    end = et_dt("16:00:00")
    df = load_capture_window("ticks", SYMBOL_DIR[symbol], start, end, tick_columns())
    bars = (
        df.lazy()
        .with_columns(
            (pl.col("timestamp_us") // 60_000_000 * 60_000_000).alias("minute_us"),
            pl.col("price").cast(pl.Float64),
            pl.col("size").cast(pl.Float64),
            pl.col("aggressor_sign").cast(pl.Int32),
        )
        .group_by("minute_us")
        .agg(
            pl.col("price").first().alias("open"),
            pl.col("price").max().alias("high"),
            pl.col("price").min().alias("low"),
            pl.col("price").last().alias("close"),
            pl.col("size").sum().alias("volume"),
            (pl.col("size") * pl.col("aggressor_sign")).sum().alias("delta"),
            pl.len().alias("prints"),
        )
        .sort("minute_us")
        .collect()
    )
    volumes = sorted(float(value) for value in bars["volume"].to_list())
    if not volumes:
        return bars.with_columns(pl.lit(0.0).alias("volume_pct"))

    def percentile(value: float) -> float:
        below = sum(1 for item in volumes if item <= value)
        return below / len(volumes)

    return bars.with_columns(
        pl.col("volume")
        .map_elements(percentile, return_dtype=pl.Float64)
        .alias("volume_pct")
    )


def bar_ts(row: dict[str, Any]) -> datetime:
    return datetime.fromtimestamp(int(row["minute_us"]) / 1_000_000, tz=timezone.utc)


def direction_hint(field: str, level: float, low: float, high: float, close: float) -> str:
    midpoint = (low + high) / 2.0
    if field in UPPER_FIELDS:
        return "upper"
    if field in LOWER_FIELDS:
        return "lower"
    return "upper" if level >= midpoint or close < level else "lower"


def detect_touches(con: sqlite3.Connection, symbol: str, bars: pl.DataFrame) -> list[Touch]:
    out: list[Touch] = []
    tolerance = POINT_TOLERANCE[symbol]
    for row in bars.to_dicts():
        ts = bar_ts(row)
        snap = latest_gex(con, TICKER[symbol], "gex_zero", ts + timedelta(seconds=59))
        if not snap:
            continue
        low = float(row["low"])
        high = float(row["high"])
        close = float(row["close"])
        for field in GEX_FIELDS:
            level = as_float(snap.get(field))
            if level is None:
                continue
            distance = 0.0 if low <= level <= high else min(abs(high - level), abs(low - level))
            if distance > tolerance:
                continue
            out.append(
                Touch(
                    symbol=symbol,
                    ticker=TICKER[symbol],
                    field=field,
                    minute_utc=ts,
                    et=ts.astimezone(NY).strftime("%H:%M:%S"),
                    level=level,
                    distance=distance,
                    side_hint=direction_hint(field, level, low, high, close),
                    open=float(row["open"]),
                    high=high,
                    low=low,
                    close=close,
                    volume=float(row["volume"]),
                    delta=float(row["delta"]),
                    volume_pct=float(row["volume_pct"]),
                    sum_gex_vol=as_float(snap.get("sum_gex_vol")),
                    zero_gamma=as_float(snap.get("zero_gamma")),
                    call_wall=as_float(snap.get("call_wall")),
                    oi_call_wall=as_float(snap.get("oi_call_wall")),
                    put_wall=as_float(snap.get("put_wall")),
                    oi_put_wall=as_float(snap.get("oi_put_wall")),
                )
            )
    return out


def cluster_touches(touches: list[Touch]) -> list[list[Touch]]:
    ordered = sorted(touches, key=lambda item: (item.symbol, item.field, item.minute_utc))
    clusters: list[list[Touch]] = []
    current: list[Touch] = []
    for touch in ordered:
        if not current:
            current = [touch]
            continue
        prior = current[-1]
        same_key = touch.symbol == prior.symbol and touch.field == prior.field
        close_time = touch.minute_utc - prior.minute_utc <= timedelta(minutes=3)
        close_level = abs(touch.level - prior.level) <= POINT_TOLERANCE[touch.symbol]
        if same_key and close_time and close_level:
            current.append(touch)
            continue
        clusters.append(current)
        current = [touch]
    if current:
        clusters.append(current)
    return clusters


def future_excursion(bars: pl.DataFrame, start: datetime, reference: float, minutes: int) -> dict[str, Any]:
    start_us = int(start.timestamp() * 1_000_000)
    end_us = int((start + timedelta(minutes=minutes)).timestamp() * 1_000_000)
    future = bars.filter((pl.col("minute_us") >= start_us) & (pl.col("minute_us") < end_us))
    if future.is_empty():
        return {}
    high = float(future["high"].max())
    low = float(future["low"].min())
    close = float(future["close"][-1])
    return {
        f"{minutes}m_future_high": high,
        f"{minutes}m_future_low": low,
        f"{minutes}m_future_close": close,
        f"{minutes}m_up_from_level": high - reference,
        f"{minutes}m_down_from_level": reference - low,
        f"{minutes}m_close_from_level": close - reference,
    }


def load_ll_events(runtime_dir: Path, symbol: str) -> list[dict[str, Any]]:
    path = runtime_dir / symbol / "decisions.jsonl"
    out: list[dict[str, Any]] = []
    if not path.exists():
        return out
    with path.open("r", encoding="utf-8-sig") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            ts = parse_utc(payload.get("ts_utc"))
            if ts is None or ts.date().isoformat() != DATE:
                continue
            event = payload.get("event")
            if event == "ll_transition":
                band_min = as_float(payload.get("band_min_tick"))
                band_max = as_float(payload.get("band_max_tick"))
                out.append(
                    {
                        "line": line_number,
                        "ts": ts,
                        "et": et_text(ts),
                        "event": event,
                        "kind": payload.get("kind"),
                        "reason": payload.get("reason"),
                        "side": payload.get("band_side") or payload.get("candidate_side"),
                        "band_min": band_min * TICK_SIZE[symbol] if band_min is not None else None,
                        "band_max": band_max * TICK_SIZE[symbol] if band_max is not None else None,
                        "score": payload.get("band_score") or payload.get("candidate_score"),
                    }
                )
            elif event == "policy_decision" and payload.get("action") in KEY_POLICY_ACTIONS:
                out.append(
                    {
                        "line": line_number,
                        "ts": ts,
                        "et": et_text(ts),
                        "event": event,
                        "kind": payload.get("action"),
                        "reason": payload.get("reason_code"),
                        "side": payload.get("evidence_side"),
                        "policy": payload.get("policy"),
                        "waypoint": payload.get("waypoint_id"),
                        "price": as_float(payload.get("evidence_price")),
                    }
                )
    return out


def ll_near_summary(
    events: list[dict[str, Any]],
    start: datetime,
    end: datetime,
    symbol: str,
    level: float,
) -> str:
    tolerance = POINT_TOLERANCE[symbol] * 2.0
    matches: list[str] = []
    for event in events:
        ts = event.get("ts")
        if not isinstance(ts, datetime) or ts < start - timedelta(minutes=2) or ts > end + timedelta(minutes=8):
            continue
        if event.get("event") != "ll_transition":
            continue
        kind = event.get("kind")
        if kind not in {"RailOwned", "RailHeld", "RailFailed", "RailTested", "CandidateFormed"}:
            continue
        lo = event.get("band_min")
        hi = event.get("band_max")
        if lo is None or hi is None:
            continue
        if level < lo - tolerance or level > hi + tolerance:
            continue
        matches.append(
            f"{event.get('et')} {kind} {event.get('side')} {fmt(lo)}-{fmt(hi)}"
        )
        if len(matches) >= 4:
            break
    return "; ".join(matches)


def policy_near_summary(events: list[dict[str, Any]], start: datetime, end: datetime) -> str:
    matches: list[str] = []
    for event in events:
        ts = event.get("ts")
        if not isinstance(ts, datetime) or ts < start - timedelta(minutes=2) or ts > end + timedelta(minutes=8):
            continue
        if event.get("event") != "policy_decision":
            continue
        matches.append(
            f"{event.get('et')} {event.get('kind')} {event.get('policy')}/{event.get('reason')}"
        )
        if len(matches) >= 4:
            break
    return "; ".join(matches)


def summarize_clusters(
    clusters: list[list[Touch]],
    bars_by_symbol: dict[str, pl.DataFrame],
    ll_by_symbol: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for idx, cluster in enumerate(clusters, start=1):
        first = cluster[0]
        last = cluster[-1]
        levels = [touch.level for touch in cluster]
        highs = [touch.high for touch in cluster]
        lows = [touch.low for touch in cluster]
        closes = [touch.close for touch in cluster]
        vol_pcts = [touch.volume_pct for touch in cluster]
        deltas = [touch.delta for touch in cluster]
        reference = median(levels)
        rows = bars_by_symbol[first.symbol]
        metrics = future_excursion(rows, last.minute_utc + timedelta(minutes=1), reference, 15)
        metrics.update(future_excursion(rows, last.minute_utc + timedelta(minutes=1), reference, 30))
        side_hint = first.side_hint
        if side_hint == "upper":
            response_15 = metrics.get("15m_down_from_level")
            extension_15 = metrics.get("15m_up_from_level")
            response_30 = metrics.get("30m_down_from_level")
            extension_30 = metrics.get("30m_up_from_level")
        else:
            response_15 = metrics.get("15m_up_from_level")
            extension_15 = metrics.get("15m_down_from_level")
            response_30 = metrics.get("30m_up_from_level")
            extension_30 = metrics.get("30m_down_from_level")
        gex_values = [touch.sum_gex_vol for touch in cluster if touch.sum_gex_vol is not None]
        item: dict[str, Any] = {
            "cluster_id": idx,
            "symbol": first.symbol,
            "ticker": first.ticker,
            "field": first.field,
            "side_hint": side_hint,
            "start_et": first.et,
            "end_et": last.et,
            "bars": len(cluster),
            "level_first": first.level,
            "level_last": last.level,
            "level_min": min(levels),
            "level_max": max(levels),
            "level_stability_points": max(levels) - min(levels),
            "touch_min_distance": min(touch.distance for touch in cluster),
            "price_high": max(highs),
            "price_low": min(lows),
            "close_last": closes[-1],
            "volume_pct_median": median(vol_pcts),
            "volume_pct_max": max(vol_pcts),
            "delta_sum": sum(deltas),
            "sum_gex_vol_first": gex_values[0] if gex_values else "",
            "sum_gex_vol_last": gex_values[-1] if gex_values else "",
            "sum_gex_vol_change": gex_values[-1] - gex_values[0] if len(gex_values) >= 2 else "",
            "response_15m": response_15,
            "extension_15m": extension_15,
            "response_30m": response_30,
            "extension_30m": extension_30,
            "ll_near": ll_near_summary(
                ll_by_symbol[first.symbol],
                first.minute_utc,
                last.minute_utc,
                first.symbol,
                reference,
            ),
            "policy_near": policy_near_summary(
                ll_by_symbol[first.symbol],
                first.minute_utc,
                last.minute_utc,
            ),
        }
        item.update(metrics)
        out.append(item)
    return out


def load_policy_csv(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def classify_add(row: dict[str, Any]) -> str:
    side = row.get("campaign_side")
    mfe = as_float(row.get("30m_mfe")) or 0.0
    mae = as_float(row.get("30m_mae")) or 0.0
    dist = as_float(row.get("nearest_gex_distance"))
    reason = row.get("candidate_reason") or ""
    symbol = row.get("symbol")
    if symbol == "ES" and side == "Short" and reason == "holdroot_shadowed_add" and mfe >= 12 and mae <= 1:
        return "high_quality_missed_add"
    if symbol == "ES" and side == "Long" and mfe >= 9 and mae <= 4 and dist is not None and abs(dist) <= 3:
        return "possible_wall_conversion_add"
    if symbol == "NQ" and mae >= 25:
        return "too_volatile_for_normal_add"
    if "no_add_zone" in reason and dist is not None and abs(dist) <= 4:
        return "near_destination_or_wall_keep_suppressed"
    return "review"


def add_case_rows(out_dir: Path) -> list[dict[str, Any]]:
    rows = load_policy_csv(out_dir / "counterfactual_add_candidates.csv")
    for row in rows:
        row["research_class"] = classify_add(row)
    return rows


def probe_case_rows(out_dir: Path) -> list[dict[str, Any]]:
    rows = load_policy_csv(out_dir / "probe_entry_mode.csv")
    for row in rows:
        actual = as_float(row.get("actual_points_per_contract"))
        one_tick = row.get("limit_1t_fill_delay_s")
        two_tick = row.get("limit_2t_fill_delay_s")
        if one_tick != "" and two_tick != "":
            row["limit_first_read"] = "1-2t_touched"
        elif one_tick != "":
            row["limit_first_read"] = "1t_touched_only"
        else:
            row["limit_first_read"] = "not_touched"
        if actual is not None and actual < 0:
            row["probe_outcome_class"] = "losing_probe"
        elif actual is not None and actual > 0:
            row["probe_outcome_class"] = "winning_probe"
        else:
            row["probe_outcome_class"] = "open_or_manual"
    return rows


def notable_clusters(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    for row in rows:
        response = as_float(row.get("response_30m")) or 0.0
        extension = as_float(row.get("extension_30m")) or 0.0
        stable = (as_float(row.get("level_stability_points")) or 0.0) <= POINT_TOLERANCE[row["symbol"]]
        has_policy = bool(row.get("policy_near"))
        if stable and response >= max(2.0, extension * 1.5) and response >= POINT_TOLERANCE[row["symbol"]] * 2:
            row = dict(row)
            row["research_class"] = "responsive_terminal_candidate"
            selected.append(row)
        elif has_policy and row.get("field") in GEX_FIELDS:
            row = dict(row)
            row["research_class"] = "campaign_relevant_touch"
            selected.append(row)
    selected.sort(
        key=lambda item: (
            item.get("symbol"),
            0 if item.get("research_class") == "campaign_relevant_touch" else 1,
            item.get("start_et"),
        )
    )
    return selected


def render_cluster_table(rows: list[dict[str, Any]], limit: int = 40) -> list[str]:
    lines = [
        "| Symbol | ET | Field | Side | Level | Price | Vol pct | Delta | 30m Resp/Ext | LL Near | Policy Near | Class |",
        "|---|---:|---|---|---:|---|---:|---:|---:|---|---|---|",
    ]
    for row in rows[:limit]:
        lines.append(
            f"| {row.get('symbol')} | {row.get('start_et')}-{row.get('end_et')} | "
            f"{row.get('field')} | {row.get('side_hint')} | {fmt(row.get('level_last'))} | "
            f"{fmt(row.get('price_low'))}-{fmt(row.get('price_high'))} | "
            f"{fmt(100 * float(row.get('volume_pct_median') or 0), 0)}% | "
            f"{fmt(row.get('delta_sum'), 0)} | "
            f"{fmt(row.get('response_30m'))}/{fmt(row.get('extension_30m'))} | "
            f"{row.get('ll_near') or '-'} | {row.get('policy_near') or '-'} | "
            f"{row.get('research_class')} |"
        )
    return lines


def render_add_table(rows: list[dict[str, Any]]) -> list[str]:
    lines = [
        "| Symbol | ET | Side | Class | Logged | Price | 30m MFE/MAE | Nearest GEX | Dist |",
        "|---|---:|---|---|---|---:|---:|---|---:|",
    ]
    for row in rows:
        if row.get("research_class") == "review":
            continue
        lines.append(
            f"| {row.get('symbol')} | {row.get('candidate_et')} | {row.get('campaign_side')} | "
            f"{row.get('research_class')} | {row.get('logged_policy')}/{row.get('logged_reason_code')} | "
            f"{fmt(row.get('first_price'))} | {fmt(row.get('30m_mfe'))}/{fmt(row.get('30m_mae'))} | "
            f"{row.get('nearest_gex')} | {fmt(row.get('nearest_gex_distance'))} |"
        )
    return lines


def render_probe_table(rows: list[dict[str, Any]]) -> list[str]:
    lines = [
        "| Symbol | ET | Side | Outcome | Fill | Actual | 30m MFE/MAE | GEX Nearest | Dist | Limit 1t/2t |",
        "|---|---:|---|---|---:|---:|---:|---|---:|---|",
    ]
    for row in rows:
        lines.append(
            f"| {row.get('symbol')} | {row.get('entry_et')} | {row.get('campaign_side')} | "
            f"{row.get('probe_outcome_class')} | {fmt(row.get('entry_fill_price'))} | "
            f"{fmt(row.get('actual_points_per_contract'))} | "
            f"{fmt(row.get('30m_mfe'))}/{fmt(row.get('30m_mae'))} | "
            f"{row.get('nearest_gex')} | {fmt(row.get('nearest_gex_distance'))} | "
            f"{row.get('limit_1t_fill_delay_s')}/{row.get('limit_2t_fill_delay_s')} |"
        )
    return lines


def render_summary(
    clusters: list[dict[str, Any]],
    add_rows: list[dict[str, Any]],
    probe_rows: list[dict[str, Any]],
    out_dir: Path,
) -> str:
    notable = notable_clusters(clusters)
    lines = [
        "# 2026-08-27 GEX Management Hypothesis Scan",
        "",
        "This is an evidence inventory, not a policy recommendation.",
        "",
        "## Coverage",
        "",
        "- GEX cache: ES_SPX and NQ_NDX minute-level classic `gex_zero` rows from RTH open.",
        "- Tick data: MarketRecorder ESU6/NQU6 RTH 1-minute bars.",
        "- Kahn data: ES/NQ policy decisions and LL transitions from JSONL logs.",
        "- Prior 2026-08-24/25 Kahn notes are controls for general Kahn harvest/add failure modes, not GEX proof.",
        "",
        "## GEX Wall-Touch / Near-Miss Clusters",
        "",
    ]
    lines.extend(render_cluster_table(notable))
    lines.extend(["", "## Add Candidate Classes", ""])
    lines.extend(render_add_table(add_rows))
    lines.extend(["", "## Root Probe Entry Mechanics", ""])
    lines.extend(render_probe_table(probe_rows))
    lines.extend(
        [
            "",
            "## Output Files",
            "",
            f"- `{out_dir / 'gex_wall_touch_clusters.csv'}`",
            f"- `{out_dir / 'gex_wall_touch_notable.csv'}`",
            f"- `{out_dir / 'add_candidate_classes.csv'}`",
            f"- `{out_dir / 'probe_entry_classes.csv'}`",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-dir", default=r"C:\Users\j\Documents\KahnRuntime")
    parser.add_argument("--gex-db", default=r"GexBotMcp\out\gexbot.sqlite")
    parser.add_argument("--out-dir", default=r"research\kahn\out\2026-08-27-gex-kahn")
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    con = sqlite3.connect(args.gex_db)
    con.row_factory = sqlite3.Row

    bars_by_symbol = {symbol: load_1m_bars(symbol) for symbol in ("ES", "NQ")}
    touches: list[Touch] = []
    for symbol, bars in bars_by_symbol.items():
        touches.extend(detect_touches(con, symbol, bars))
    clusters = cluster_touches(touches)
    ll_by_symbol = {
        symbol: load_ll_events(Path(args.runtime_dir), symbol)
        for symbol in ("ES", "NQ")
    }
    cluster_rows = summarize_clusters(clusters, bars_by_symbol, ll_by_symbol)
    notable = notable_clusters(cluster_rows)
    adds = add_case_rows(out_dir)
    probes = probe_case_rows(out_dir)

    write_csv(out_dir / "gex_wall_touch_clusters.csv", cluster_rows)
    write_csv(out_dir / "gex_wall_touch_notable.csv", notable)
    write_csv(out_dir / "add_candidate_classes.csv", adds)
    write_csv(out_dir / "probe_entry_classes.csv", probes)
    (out_dir / "gex_management_hypothesis_scan.md").write_text(
        render_summary(cluster_rows, adds, probes, out_dir),
        encoding="utf-8",
    )

    print(
        f"bars={sum(len(df) for df in bars_by_symbol.values())} "
        f"touches={len(touches)} clusters={len(cluster_rows)} notable={len(notable)} "
        f"adds={len(adds)} probes={len(probes)} out={out_dir}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
