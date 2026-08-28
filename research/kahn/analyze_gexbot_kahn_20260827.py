"""Join 2026-08-27 Kahn decisions with cached GexBot context.

This is a read-only research helper for runtime logs. It writes compact output
under research/kahn/out so the raw multi-megabyte JSONL logs do not need to be
read manually.
"""

from __future__ import annotations

import argparse
import csv
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


EDT = timezone(timedelta(hours=-4), "America/New_York")
BROKER_ACTIONS = {"AllowProbe", "AllowAdd", "Reduce", "Flatten", "Retire"}
GEX_CATEGORIES = ("gex_zero", "gex_full", "gex_one")
GEX_FIELDS = (
    "zero_gamma",
    "call_wall",
    "put_wall",
    "oi_call_wall",
    "oi_put_wall",
)


@dataclass
class LogRow:
    symbol: str
    line: int
    payload: dict[str, Any]

    @property
    def ts(self) -> datetime | None:
        return parse_utc(self.payload.get("ts_utc"))

    @property
    def et(self) -> str:
        ts = self.ts
        return "-" if ts is None else ts.astimezone(EDT).strftime("%H:%M:%S")


def parse_utc(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        text = value.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def iso_z(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def price_from_decision(payload: dict[str, Any]) -> float | None:
    price = as_float(payload.get("evidence_price"))
    if price is not None:
        return price
    rng = payload.get("evidence_range")
    if isinstance(rng, dict):
        lower = as_float(rng.get("lower"))
        upper = as_float(rng.get("upper"))
        if lower is not None and upper is not None:
            return (lower + upper) / 2.0
    return None


def as_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number and number not in (float("inf"), float("-inf")) else None


def fmt(value: Any, digits: int = 2) -> str:
    number = as_float(value)
    if number is None:
        return "-"
    return f"{number:.{digits}f}".rstrip("0").rstrip(".")


def read_log(path: Path, symbol: str, session_date: str) -> list[LogRow]:
    rows: list[LogRow] = []
    if not path.exists():
        return rows
    with path.open("r", encoding="utf-8-sig") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            ts = parse_utc(payload.get("ts_utc"))
            if ts is None or ts.date().isoformat() != session_date:
                continue
            rows.append(LogRow(symbol=symbol, line=line_number, payload=payload))
    return rows


def attach_next_state(policy_rows: list[LogRow], all_rows: list[LogRow]) -> None:
    state_by_symbol: dict[str, list[LogRow]] = {}
    for row in all_rows:
        if row.payload.get("event") == "campaign_state":
            state_by_symbol.setdefault(row.symbol, []).append(row)

    indexes = {symbol: 0 for symbol in state_by_symbol}
    for policy in policy_rows:
        state_rows = state_by_symbol.get(policy.symbol, [])
        state_index = indexes.get(policy.symbol, 0)
        while state_index < len(state_rows) and state_rows[state_index].line <= policy.line:
            state_index += 1
        indexes[policy.symbol] = state_index

        match = None
        for candidate in state_rows[state_index : state_index + 8]:
            if (
                candidate.payload.get("campaign_id") == policy.payload.get("campaign_id")
                and candidate.line > policy.line
            ):
                match = candidate
                break
        if match is None:
            continue
        policy.payload["_phase_after"] = match.payload.get("phase")
        policy.payload["_sim_position_after"] = match.payload.get("simulated_position_quantity")


def compressed_policy_runs(policy_rows: list[LogRow]) -> list[dict[str, Any]]:
    runs: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None

    for row in sorted(policy_rows, key=lambda item: (item.symbol, item.line)):
        p = row.payload
        key = (
            row.symbol,
            p.get("campaign_id"),
            p.get("phase_before"),
            p.get("action"),
            p.get("policy"),
            p.get("reason_code"),
            p.get("waypoint_id"),
            p.get("evidence_source"),
            p.get("evidence_kind"),
            p.get("evidence_side"),
        )
        price = price_from_decision(p)
        if current is None or current["key"] != key:
            current = {
                "key": key,
                "symbol": row.symbol,
                "first_line": row.line,
                "last_line": row.line,
                "first_utc": iso_z(row.ts) if row.ts else "-",
                "last_utc": iso_z(row.ts) if row.ts else "-",
                "first_et": row.et,
                "last_et": row.et,
                "count": 1,
                "campaign_id": p.get("campaign_id"),
                "phase_before": p.get("phase_before"),
                "phase_after": p.get("_phase_after"),
                "action": p.get("action"),
                "policy": p.get("policy"),
                "reason_code": p.get("reason_code"),
                "waypoint_id": p.get("waypoint_id"),
                "evidence_source": p.get("evidence_source"),
                "evidence_kind": p.get("evidence_kind"),
                "evidence_side": p.get("evidence_side"),
                "first_price": price,
                "min_price": price,
                "max_price": price,
                "first_pos_before": p.get("simulated_position_before"),
                "last_pos_after": p.get("_sim_position_after"),
                "first_evidence_id": p.get("evidence_id"),
                "last_evidence_id": p.get("evidence_id"),
            }
            runs.append(current)
            continue

        current["last_line"] = row.line
        current["last_utc"] = iso_z(row.ts) if row.ts else "-"
        current["last_et"] = row.et
        current["count"] += 1
        current["phase_after"] = p.get("_phase_after") or current["phase_after"]
        current["last_pos_after"] = p.get("_sim_position_after")
        current["last_evidence_id"] = p.get("evidence_id")
        if price is not None:
            current["min_price"] = (
                price
                if current["min_price"] is None
                else min(current["min_price"], price)
            )
            current["max_price"] = (
                price
                if current["max_price"] is None
                else max(current["max_price"], price)
            )

    for run in runs:
        run.pop("key", None)
    return runs


def latest_gex(
    con: sqlite3.Connection,
    ticker: str,
    category: str,
    at_utc: datetime,
) -> dict[str, Any] | None:
    row = con.execute(
        """
        SELECT id, recorded_at_utc, api_as_of_utc, ticker, category, spot,
               zero_gamma, call_wall, put_wall, oi_call_wall, oi_put_wall,
               sum_gex_vol, sum_gex_oi
        FROM snapshots
        WHERE ok = 1
          AND ticker = ?
          AND package = 'classic'
          AND category = ?
          AND view = 'chain'
          AND recorded_at_utc <= ?
        ORDER BY recorded_at_utc DESC, id DESC
        LIMIT 1
        """,
        (ticker, category, iso_z(at_utc)),
    ).fetchone()
    return dict(row) if row is not None else None


def gex_history(
    con: sqlite3.Connection,
    ticker: str,
    category: str,
    session_date: str,
) -> list[dict[str, Any]]:
    start = f"{session_date}T00:00:00Z"
    day = datetime.fromisoformat(session_date).date()
    until = (datetime(day.year, day.month, day.day, tzinfo=timezone.utc) + timedelta(days=1))
    rows = con.execute(
        """
        SELECT id, recorded_at_utc, api_as_of_utc, ticker, category, spot,
               zero_gamma, call_wall, put_wall, oi_call_wall, oi_put_wall,
               sum_gex_vol, sum_gex_oi
        FROM snapshots
        WHERE ok = 1
          AND ticker = ?
          AND package = 'classic'
          AND category = ?
          AND view = 'chain'
          AND recorded_at_utc >= ?
          AND recorded_at_utc < ?
        ORDER BY recorded_at_utc ASC, id ASC
        """,
        (ticker, category, start, iso_z(until)),
    ).fetchall()
    return [dict(row) for row in rows]


def wall_changes(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    changes: list[dict[str, Any]] = []
    previous: dict[str, Any] | None = None
    for row in rows:
        if previous is None:
            previous = row
            continue
        changed: dict[str, str] = {}
        for field in GEX_FIELDS:
            if row.get(field) != previous.get(field):
                changed[field] = f"{fmt(previous.get(field))}->{fmt(row.get(field))}"
        if changed:
            item = {
                "recorded_utc": row.get("recorded_at_utc"),
                "recorded_et": et_text(row.get("recorded_at_utc")),
                "api_as_of_utc": row.get("api_as_of_utc"),
                "ticker": row.get("ticker"),
                "category": row.get("category"),
                "spot": row.get("spot"),
            }
            item.update(changed)
            changes.append(item)
        previous = row
    return changes


def et_text(value: Any) -> str:
    ts = parse_utc(value)
    return "-" if ts is None else ts.astimezone(EDT).strftime("%H:%M:%S")


def nearest_field(snapshot: dict[str, Any] | None, price: float | None) -> tuple[str, float | None]:
    if snapshot is None or price is None:
        return "-", None
    best_name = "-"
    best_distance: float | None = None
    for field in GEX_FIELDS:
        level = as_float(snapshot.get(field))
        if level is None:
            continue
        distance = price - level
        if best_distance is None or abs(distance) < abs(best_distance):
            best_name = field
            best_distance = distance
    return best_name, best_distance


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
    out_dir: Path,
    campaigns: list[LogRow],
    key_decisions: list[LogRow],
    joined: list[dict[str, Any]],
    changes: list[dict[str, Any]],
) -> str:
    lines = [
        "# 2026-08-27 Kahn / GexBot Join",
        "",
        "Generated from local Kahn JSONL decision logs and `GexBotMcp/out/gexbot.sqlite`.",
        "",
        "## Campaign Loads",
        "",
        "| Symbol | ET | Campaign | Status | Side | Probe/Add/Max | Notes |",
        "|---|---:|---|---|---|---:|---|",
    ]
    for row in campaigns:
        p = row.payload
        notes = str(p.get("notes") or "").replace("|", "\\|")
        if len(notes) > 180:
            notes = notes[:177] + "..."
        sizing = f"{p.get('probe_quantity', '-')}/{p.get('add_quantity', '-')}/{p.get('campaign_max_position_quantity', '-')}"
        lines.append(
            f"| {row.symbol} | {row.et} | `{p.get('campaign_id')}` | {p.get('status')} | "
            f"{p.get('side')} | {sizing} | {notes} |"
        )

    lines.extend(
        [
            "",
            "## Broker-Affecting Decisions",
            "",
            "| Symbol | ET | Action | Pos | Campaign | Policy/Reason | Waypoint | Price | GEX category | Nearest GEX | Dist | Snapshot ET |",
            "|---|---:|---:|---:|---|---|---|---:|---|---|---:|---:|",
        ]
    )
    for item in joined:
        if item.get("category") != "gex_zero":
            continue
        lines.append(
            f"| {item['symbol']} | {item['decision_et']} | {item['action']} | "
            f"{item.get('pos_before', '-')}->{item.get('pos_after', '-')} | "
            f"`{item['campaign_id']}` | {item['policy']}/{item['reason_code']} | "
            f"{item.get('waypoint_id') or '-'} | {fmt(item.get('price'))} | "
            f"{item.get('category')} | {item.get('nearest_gex')} | "
            f"{fmt(item.get('nearest_gex_distance'))} | {item.get('gex_recorded_et', '-')} |"
        )

    lines.extend(
        [
            "",
            "## GEX Wall Changes",
            "",
            "| ET | Ticker | Category | Spot | Changed Fields |",
            "|---:|---|---|---:|---|",
        ]
    )
    for change in changes[:80]:
        changed = ", ".join(
            f"{field}:{value}"
            for field, value in change.items()
            if field in GEX_FIELDS and value
        )
        lines.append(
            f"| {change.get('recorded_et')} | {change.get('ticker')} | {change.get('category')} | "
            f"{fmt(change.get('spot'))} | {changed} |"
        )
    if len(changes) > 80:
        lines.append(f"| ... | ... | ... | ... | truncated; see CSV for {len(changes)} changes |")

    lines.extend(
        [
            "",
            "## Output Files",
            "",
            f"- `{out_dir / 'campaign_loads.csv'}`",
            f"- `{out_dir / 'policy_runs.csv'}`",
            f"- `{out_dir / 'key_decisions_gex_join.csv'}`",
            f"- `{out_dir / 'gex_wall_changes.csv'}`",
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

    runtime_dir = Path(args.runtime_dir)
    out_dir = Path(args.out_dir)
    all_rows = (
        read_log(runtime_dir / "ES" / "decisions.jsonl", "ES", args.session_date)
        + read_log(runtime_dir / "NQ" / "decisions.jsonl", "NQ", args.session_date)
    )
    all_rows.sort(key=lambda row: (row.ts or datetime.min.replace(tzinfo=timezone.utc), row.symbol, row.line))
    campaigns = [row for row in all_rows if row.payload.get("event") == "campaign_loaded"]
    policy = [row for row in all_rows if row.payload.get("event") == "policy_decision"]
    attach_next_state(policy, all_rows)
    runs = compressed_policy_runs(policy)
    key_decisions = [row for row in policy if row.payload.get("action") in BROKER_ACTIONS]

    con = sqlite3.connect(args.gex_db)
    con.row_factory = sqlite3.Row

    joined: list[dict[str, Any]] = []
    for row in key_decisions:
        p = row.payload
        ticker = "ES_SPX" if row.symbol == "ES" else "NQ_NDX"
        price = price_from_decision(p)
        for category in GEX_CATEGORIES:
            snap = latest_gex(con, ticker, category, row.ts or datetime.now(timezone.utc))
            nearest, distance = nearest_field(snap, price)
            joined.append(
                {
                    "symbol": row.symbol,
                    "ticker": ticker,
                    "decision_utc": iso_z(row.ts) if row.ts else "-",
                    "decision_et": row.et,
                    "campaign_id": p.get("campaign_id"),
                    "action": p.get("action"),
                    "policy": p.get("policy"),
                    "reason_code": p.get("reason_code"),
                    "waypoint_id": p.get("waypoint_id"),
                    "phase_before": p.get("phase_before"),
                    "phase_after": p.get("_phase_after"),
                    "pos_before": p.get("simulated_position_before"),
                    "pos_after": p.get("_sim_position_after"),
                    "evidence_source": p.get("evidence_source"),
                    "evidence_kind": p.get("evidence_kind"),
                    "evidence_side": p.get("evidence_side"),
                    "price": price,
                    "category": category,
                    "gex_record_id": snap.get("id") if snap else None,
                    "gex_recorded_utc": snap.get("recorded_at_utc") if snap else None,
                    "gex_recorded_et": et_text(snap.get("recorded_at_utc")) if snap else None,
                    "gex_api_as_of_utc": snap.get("api_as_of_utc") if snap else None,
                    "gex_spot": snap.get("spot") if snap else None,
                    "zero_gamma": snap.get("zero_gamma") if snap else None,
                    "call_wall": snap.get("call_wall") if snap else None,
                    "put_wall": snap.get("put_wall") if snap else None,
                    "oi_call_wall": snap.get("oi_call_wall") if snap else None,
                    "oi_put_wall": snap.get("oi_put_wall") if snap else None,
                    "sum_gex_vol": snap.get("sum_gex_vol") if snap else None,
                    "sum_gex_oi": snap.get("sum_gex_oi") if snap else None,
                    "nearest_gex": nearest,
                    "nearest_gex_distance": distance,
                }
            )

    changes: list[dict[str, Any]] = []
    for ticker in ("ES_SPX", "NQ_NDX"):
        for category in GEX_CATEGORIES:
            changes.extend(wall_changes(gex_history(con, ticker, category, args.session_date)))
    changes.sort(key=lambda row: row.get("recorded_utc") or "")

    write_csv(
        out_dir / "campaign_loads.csv",
        [
            {
                "symbol": row.symbol,
                "line": row.line,
                "ts_utc": iso_z(row.ts) if row.ts else "-",
                "et": row.et,
                **row.payload,
            }
            for row in campaigns
        ],
    )
    write_csv(out_dir / "policy_runs.csv", runs)
    write_csv(out_dir / "key_decisions_gex_join.csv", joined)
    write_csv(out_dir / "gex_wall_changes.csv", changes)
    summary = render_summary(out_dir, campaigns, key_decisions, joined, changes)
    (out_dir / "summary.md").write_text(summary, encoding="utf-8")

    print(
        f"rows={len(all_rows)} campaigns={len(campaigns)} "
        f"policy={len(policy)} key_decisions={len(key_decisions)} "
        f"runs={len(runs)} gex_changes={len(changes)} out={out_dir}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
