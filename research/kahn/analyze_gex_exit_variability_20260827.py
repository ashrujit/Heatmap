"""Inspect whether GEX reduced exit variability on 2026-08-27 ES campaigns.

The goal is narrower than the prior broad join:

- ES PM short: did the 7728/7729 harvest have GEX evidence beyond the planned
  destination, and should a passive limit have been staged into demand?
- ES late-morning long: if Kahn had still been managing the long, would GEX
  have offered a more objective exit near the 7743 harvest zone before LL/BT
  auction-failure evidence appeared?
"""

from __future__ import annotations

import argparse
import csv
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

import polars as pl


ET = timezone(timedelta(hours=-4), "America/New_York")
FIELDS = (
    "zero_gamma",
    "call_wall",
    "put_wall",
    "oi_call_wall",
    "oi_put_wall",
)


@dataclass
class Window:
    name: str
    start_et: str
    end_et: str
    target_low: float
    target_high: float

    @property
    def start_utc(self) -> datetime:
        return et_to_utc("2026-08-27", self.start_et)

    @property
    def end_utc(self) -> datetime:
        return et_to_utc("2026-08-27", self.end_et)


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


def et_to_utc(date: str, hhmmss: str) -> datetime:
    local = datetime.fromisoformat(f"{date}T{hhmmss}").replace(tzinfo=ET)
    return local.astimezone(timezone.utc)


def iso_z(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def et_text(value: Any) -> str:
    parsed = parse_utc(value)
    return "-" if parsed is None else parsed.astimezone(ET).strftime("%H:%M:%S")


def f(value: Any, digits: int = 2) -> str:
    number = as_float(value)
    if number is None:
        return "-"
    return f"{number:.{digits}f}".rstrip("0").rstrip(".")


def as_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or number in (float("inf"), float("-inf")):
        return None
    return number


def nearest_gex(snapshot: dict[str, Any], price: float) -> tuple[str, float | None]:
    nearest = "-"
    best: float | None = None
    for field in FIELDS:
        level = as_float(snapshot.get(field))
        if level is None:
            continue
        dist = price - level
        if best is None or abs(dist) < abs(best):
            nearest = field
            best = dist
    return nearest, best


def read_jsonl(path: Path) -> Iterable[tuple[int, dict[str, Any]]]:
    if not path.exists():
        return
    with path.open("r", encoding="utf-8-sig") as handle:
        for line_no, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                yield line_no, json.loads(line)
            except json.JSONDecodeError:
                continue


def price_from_policy(payload: dict[str, Any]) -> float | None:
    price = as_float(payload.get("evidence_price"))
    if price is not None:
        return price
    rng = payload.get("evidence_range")
    if isinstance(rng, dict):
        low = as_float(rng.get("lower"))
        high = as_float(rng.get("upper"))
        if low is not None and high is not None:
            return (low + high) / 2.0
    return None


def load_kahn_events(path: Path, windows: list[Window]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_no, payload in read_jsonl(path):
        ts = parse_utc(payload.get("ts_utc"))
        if ts is None:
            continue
        if not any(window.start_utc <= ts <= window.end_utc for window in windows):
            continue
        event = payload.get("event")
        if event not in {"policy_decision", "ll_transition", "order_event", "fill_event", "campaign_state"}:
            continue
        row: dict[str, Any] = {
            "source": "kahn",
            "line": line_no,
            "utc": iso_z(ts),
            "et": ts.astimezone(ET).strftime("%H:%M:%S"),
            "event": event,
            "campaign_id": payload.get("campaign_id"),
        }
        if event == "policy_decision":
            row.update(
                {
                    "action": payload.get("action"),
                    "policy": payload.get("policy"),
                    "reason": payload.get("reason_code"),
                    "waypoint": payload.get("waypoint_id"),
                    "phase": payload.get("phase_before"),
                    "pos_before": payload.get("simulated_position_before"),
                    "price": price_from_policy(payload),
                    "evidence_kind": payload.get("evidence_kind"),
                    "evidence_side": payload.get("evidence_side"),
                    "evidence_range": payload.get("evidence_range"),
                }
            )
        elif event == "ll_transition":
            row.update(
                {
                    "kind": payload.get("kind"),
                    "reason": payload.get("reason"),
                    "mid_price": as_float(payload.get("mid_tick")) * 0.25
                    if as_float(payload.get("mid_tick")) is not None
                    else None,
                    "band_side": payload.get("band_side"),
                    "band_state": payload.get("band_state"),
                    "band_min": as_float(payload.get("band_min_tick")) * 0.25
                    if as_float(payload.get("band_min_tick")) is not None
                    else None,
                    "band_max": as_float(payload.get("band_max_tick")) * 0.25
                    if as_float(payload.get("band_max_tick")) is not None
                    else None,
                    "band_score": payload.get("band_score"),
                    "candidate_side": payload.get("candidate_side"),
                    "candidate_min": as_float(payload.get("candidate_min_tick")) * 0.25
                    if as_float(payload.get("candidate_min_tick")) is not None
                    else None,
                    "candidate_max": as_float(payload.get("candidate_max_tick")) * 0.25
                    if as_float(payload.get("candidate_max_tick")) is not None
                    else None,
                    "candidate_score": payload.get("candidate_score"),
                }
            )
        else:
            row.update(payload)
        rows.append(row)
    return rows


def load_gex(con: sqlite3.Connection, window: Window) -> list[dict[str, Any]]:
    rows = con.execute(
        """
        SELECT recorded_at_utc, api_as_of_utc, ticker, category, spot,
               zero_gamma, call_wall, put_wall, oi_call_wall, oi_put_wall,
               sum_gex_vol, sum_gex_oi
        FROM snapshots
        WHERE ok = 1
          AND package = 'classic'
          AND view = 'chain'
          AND ticker = 'ES_SPX'
          AND category IN ('gex_zero', 'gex_full')
          AND recorded_at_utc >= ?
          AND recorded_at_utc <= ?
        ORDER BY recorded_at_utc ASC, category ASC
        """,
        (iso_z(window.start_utc), iso_z(window.end_utc)),
    ).fetchall()
    out: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        item["recorded_et"] = et_text(item.get("recorded_at_utc"))
        for price in (window.target_low, window.target_high, (window.target_low + window.target_high) / 2):
            name, dist = nearest_gex(item, price)
            item[f"nearest_to_{f(price)}"] = name
            item[f"dist_to_{f(price)}"] = dist
        out.append(item)
    return out


def load_bubbles(path: Path, window: Window) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for raw in reader:
            start = parse_utc(raw.get("start_utc"))
            end = parse_utc(raw.get("end_utc")) or start
            if start is None:
                continue
            if end < window.start_utc or start > window.end_utc:
                continue
            item = dict(raw)
            item["start_et"] = start.astimezone(ET).strftime("%H:%M:%S")
            item["end_et"] = end.astimezone(ET).strftime("%H:%M:%S")
            rows.append(item)
    return rows


def load_tick_bars(capture_root: Path, symbol: str, date: str) -> pl.DataFrame:
    tick_dir = capture_root / symbol / date / "ticks"
    files = sorted(str(path) for path in tick_dir.glob("*.parquet"))
    if not files:
        return pl.DataFrame()
    ticks = (
        pl.scan_parquet(files)
        .select(
            pl.from_epoch("timestamp_us", time_unit="us").dt.replace_time_zone("UTC").alias("ts"),
            pl.col("price").cast(pl.Float64),
            pl.col("size").cast(pl.Float64),
            pl.col("aggressor_sign").cast(pl.Int32),
        )
        .filter(pl.col("price").is_finite() & pl.col("size").is_finite())
        .sort("ts")
    )
    bars = (
        ticks.group_by_dynamic("ts", every="1m", period="1m", closed="left")
        .agg(
            pl.col("price").first().alias("open"),
            pl.col("price").max().alias("high"),
            pl.col("price").min().alias("low"),
            pl.col("price").last().alias("close"),
            pl.col("size").sum().alias("volume"),
            (pl.col("size") * pl.when(pl.col("aggressor_sign") > 0).then(1).otherwise(0)).sum().alias("buy_volume"),
            (pl.col("size") * pl.when(pl.col("aggressor_sign") < 0).then(1).otherwise(0)).sum().alias("sell_volume"),
            (pl.col("size") * pl.col("aggressor_sign")).sum().alias("delta"),
            pl.len().alias("prints"),
        )
        .sort("ts")
        .collect()
    )
    rth = bars.filter(
        (pl.col("ts") >= et_to_utc(date, "09:30:00"))
        & (pl.col("ts") <= et_to_utc(date, "16:00:00"))
    )
    volumes = sorted(float(value) for value in rth["volume"].to_list() if value is not None)
    if not volumes:
        return bars

    def percentile(value: float) -> float:
        below = sum(1 for item in volumes if item <= value)
        return below / len(volumes)

    return bars.with_columns(
        pl.col("volume")
        .map_elements(percentile, return_dtype=pl.Float64)
        .alias("rth_volume_percentile")
    )


def bars_for_window(bars: pl.DataFrame, window: Window) -> list[dict[str, Any]]:
    if bars.is_empty():
        return []
    sliced = bars.filter((pl.col("ts") >= window.start_utc) & (pl.col("ts") <= window.end_utc))
    rows: list[dict[str, Any]] = []
    for row in sliced.to_dicts():
        ts = row["ts"]
        rows.append(
            {
                "et": ts.astimezone(ET).strftime("%H:%M:%S"),
                "open": row.get("open"),
                "high": row.get("high"),
                "low": row.get("low"),
                "close": row.get("close"),
                "volume": row.get("volume"),
                "buy_volume": row.get("buy_volume"),
                "sell_volume": row.get("sell_volume"),
                "delta": row.get("delta"),
                "prints": row.get("prints"),
                "rth_volume_percentile": row.get("rth_volume_percentile"),
                "hit_target_low": row.get("high", 0) >= window.target_low
                and row.get("low", 0) <= window.target_low,
                "hit_target_high": row.get("high", 0) >= window.target_high
                and row.get("low", 0) <= window.target_high,
            }
        )
    return rows


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


def render_summary(
    short_gex: list[dict[str, Any]],
    long_gex: list[dict[str, Any]],
    short_events: list[dict[str, Any]],
    long_events: list[dict[str, Any]],
    short_bubbles: list[dict[str, Any]],
    long_bubbles: list[dict[str, Any]],
    short_bars: list[dict[str, Any]],
    long_bars: list[dict[str, Any]],
) -> str:
    lines = [
        "# 2026-08-27 ES Exit Variability And GEX",
        "",
        "## PM Short Into 7728/7729",
        "",
    ]
    lines.extend(render_gex_table(short_gex, 7729.0))
    lines.extend(["", "Kahn/LL events near target:", ""])
    lines.extend(render_event_table(short_events))
    lines.extend(["", "Tick bars:", ""])
    lines.extend(render_bar_table(short_bars))
    lines.extend(["", "BubbleTape:", ""])
    lines.extend(render_bubble_table(short_bubbles))
    lines.extend(["", "## Late-Morning Long Near 7743", ""])
    lines.extend(render_gex_table(long_gex, 7743.0))
    lines.extend(["", "Kahn/LL events near 7740-7743:", ""])
    lines.extend(render_event_table(long_events))
    lines.extend(["", "Tick bars:", ""])
    lines.extend(render_bar_table(long_bars))
    lines.extend(["", "BubbleTape:", ""])
    lines.extend(render_bubble_table(long_bubbles))
    return "\n".join(lines) + "\n"


def render_gex_table(rows: list[dict[str, Any]], reference: float) -> list[str]:
    out = [
        f"GEX snapshots against `{f(reference)}`:",
        "",
        "| ET | Cat | Spot | Zero | Call | OI Call | Put | OI Put | Sum Vol | Sum OI | Nearest/Dist |",
        "|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for row in rows:
        name, dist = nearest_gex(row, reference)
        out.append(
            f"| {row.get('recorded_et')} | {row.get('category')} | {f(row.get('spot'))} | "
            f"{f(row.get('zero_gamma'))} | {f(row.get('call_wall'))} | {f(row.get('oi_call_wall'))} | "
            f"{f(row.get('put_wall'))} | {f(row.get('oi_put_wall'))} | "
            f"{f(row.get('sum_gex_vol'), 0)} | {f(row.get('sum_gex_oi'), 0)} | {name} {f(dist)} |"
        )
    return out


def render_event_table(rows: list[dict[str, Any]]) -> list[str]:
    out = [
        "| ET | Event | Action/Kind | Side | Price/Range | Policy/Reason |",
        "|---:|---|---|---|---|---|",
    ]
    for row in rows:
        if row.get("event") == "policy_decision":
            rng = row.get("evidence_range")
            if isinstance(rng, dict):
                price = f"{f(rng.get('lower'))}-{f(rng.get('upper'))}"
            else:
                price = f(row.get("price"))
            out.append(
                f"| {row.get('et')} | policy | {row.get('action')} | {row.get('evidence_side')} | "
                f"{price} | {row.get('policy')}/{row.get('reason')} |"
            )
        elif row.get("event") == "ll_transition":
            band = "-"
            if row.get("band_min") is not None:
                band = f"{f(row.get('band_min'))}-{f(row.get('band_max'))}"
            elif row.get("candidate_min") is not None:
                band = f"{f(row.get('candidate_min'))}-{f(row.get('candidate_max'))}"
            side = row.get("band_side") or row.get("candidate_side") or "-"
            out.append(
                f"| {row.get('et')} | ll | {row.get('kind')} | {side} | "
                f"mid {f(row.get('mid_price'))}; {band} | {row.get('reason') or '-'} |"
            )
    return out


def render_bubble_table(rows: list[dict[str, Any]]) -> list[str]:
    if not rows:
        return ["- No replay rows in this window."]
    out = [
        "| ET | Side | Type | Price | Delta | Volume |",
        "|---:|---|---|---:|---:|---:|",
    ]
    for row in rows:
        out.append(
            f"| {row.get('start_et')}-{row.get('end_et')} | {row.get('side')} | {row.get('kind') or row.get('type')} | "
            f"{row.get('price_low') or row.get('low_price')}-{row.get('price_high') or row.get('high_price')} | "
            f"{row.get('delta') or row.get('net_delta')} | {row.get('volume')} |"
        )
    return out


def render_bar_table(rows: list[dict[str, Any]]) -> list[str]:
    if not rows:
        return ["- No tick bars in this window."]
    out = [
        "| ET | O | H | L | C | Vol | Delta | Vol pct |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        out.append(
            f"| {row.get('et')} | {f(row.get('open'))} | {f(row.get('high'))} | "
            f"{f(row.get('low'))} | {f(row.get('close'))} | {f(row.get('volume'), 0)} | "
            f"{f(row.get('delta'), 0)} | {f(100 * float(row.get('rth_volume_percentile') or 0), 0)}% |"
        )
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-es-log", default=r"C:\Users\j\Documents\KahnRuntime\ES\decisions.jsonl")
    parser.add_argument("--gex-db", default=r"GexBotMcp\out\gexbot.sqlite")
    parser.add_argument("--out-dir", default=r"research\kahn\out\2026-08-27-gex-kahn")
    parser.add_argument(
        "--capture-root",
        default=r"C:\Quantower\Settings\Scripts\Indicators\MarketRecorder\captures",
    )
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    windows = [
        Window("es_short_harvest_7728", "14:18:00", "14:34:00", 7728.0, 7729.5),
        Window("es_long_near_harvest_7743", "10:35:00", "11:45:00", 7740.0, 7743.0),
    ]
    short_window, long_window = windows

    con = sqlite3.connect(args.gex_db)
    con.row_factory = sqlite3.Row

    short_gex = load_gex(con, short_window)
    long_gex = load_gex(con, long_window)
    all_events = load_kahn_events(Path(args.runtime_es_log), windows)
    short_events = [
        row
        for row in all_events
        if short_window.start_utc <= parse_utc(row["utc"]) <= short_window.end_utc
    ]
    long_events = [
        row
        for row in all_events
        if long_window.start_utc <= parse_utc(row["utc"]) <= long_window.end_utc
    ]
    short_bubbles = load_bubbles(out_dir / "bubble_es_1330_1432.csv", short_window)
    long_bubbles = load_bubbles(out_dir / "bubble_es_0954_1008.csv", long_window)
    bars = load_tick_bars(Path(args.capture_root), "ESU6", "2026-08-27")
    short_bars = bars_for_window(bars, short_window)
    long_bars = bars_for_window(bars, long_window)

    write_csv(out_dir / "exit_short_harvest_gex.csv", short_gex)
    write_csv(out_dir / "exit_long_near_harvest_gex.csv", long_gex)
    write_csv(out_dir / "exit_short_harvest_events.csv", short_events)
    write_csv(out_dir / "exit_long_near_harvest_events.csv", long_events)
    write_csv(out_dir / "exit_short_harvest_1m_bars.csv", short_bars)
    write_csv(out_dir / "exit_long_near_harvest_1m_bars.csv", long_bars)
    summary = render_summary(
        short_gex,
        long_gex,
        short_events,
        long_events,
        short_bubbles,
        long_bubbles,
        short_bars,
        long_bars,
    )
    (out_dir / "exit_variability_summary.md").write_text(summary, encoding="utf-8")

    print(
        f"short_gex={len(short_gex)} long_gex={len(long_gex)} "
        f"short_events={len(short_events)} long_events={len(long_events)} "
        f"short_bars={len(short_bars)} long_bars={len(long_bars)} "
        f"out={out_dir / 'exit_variability_summary.md'}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
