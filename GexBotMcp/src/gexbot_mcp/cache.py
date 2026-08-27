"""SQLite-backed cache for GexBot chain snapshots."""

from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .context import snapshot_summary


PACKAGE_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CACHE_PATH = PACKAGE_ROOT / "out" / "gexbot.sqlite"
SCHEMA_VERSION = 1


@dataclass(frozen=True)
class SnapshotRecord:
    row_id: int
    recorded_at_utc: str
    api_timestamp: float | None
    api_as_of_utc: str | None
    ticker: str
    package: str
    category: str
    view: str
    ok: bool
    spot: float | None
    zero_gamma: float | None
    call_wall: float | None
    put_wall: float | None
    oi_call_wall: float | None
    oi_put_wall: float | None
    sum_gex_vol: float | None
    sum_gex_oi: float | None
    raw: Any
    context: dict[str, Any] | None
    error: str | None
    status: int | None

    def age_seconds(self, now: datetime | None = None) -> float | None:
        recorded = parse_utc(self.recorded_at_utc)
        if recorded is None:
            return None
        current = now or datetime.now(timezone.utc)
        return max(0.0, (current - recorded).total_seconds())

    def to_dict(self, *, include_raw: bool = False, include_context: bool = False) -> dict[str, Any]:
        result: dict[str, Any] = {
            "id": self.row_id,
            "recorded_at_utc": self.recorded_at_utc,
            "api_timestamp": self.api_timestamp,
            "api_as_of_utc": self.api_as_of_utc,
            "ticker": self.ticker,
            "package": self.package,
            "category": self.category,
            "view": self.view,
            "ok": self.ok,
            "spot": self.spot,
            "zero_gamma": self.zero_gamma,
            "call_wall": self.call_wall,
            "put_wall": self.put_wall,
            "oi_call_wall": self.oi_call_wall,
            "oi_put_wall": self.oi_put_wall,
            "sum_gex_vol": self.sum_gex_vol,
            "sum_gex_oi": self.sum_gex_oi,
            "error": self.error,
            "status": self.status,
        }
        if include_raw:
            result["raw"] = self.raw
        if include_context:
            result["context"] = self.context
        return result


class GexBotCache:
    def __init__(self, path: Path | str = DEFAULT_CACHE_PATH, *, ttl_days: int = 30) -> None:
        self.path = Path(path)
        self.ttl_days = max(1, int(ttl_days))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.path, timeout=30.0, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._initialize()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def store_success(
        self,
        *,
        ticker: str,
        package: str,
        category: str,
        payload: dict[str, Any],
        context: dict[str, Any],
        recorded_at_utc: str | None = None,
        view: str = "chain",
    ) -> SnapshotRecord:
        recorded_at_utc = recorded_at_utc or utc_now_iso()
        summary = snapshot_summary(payload)
        walls = context.get("wall_context") or {}
        aggregates = context.get("aggregates") or {}
        values = {
            "recorded_at_utc": recorded_at_utc,
            "api_timestamp": _number(payload.get("timestamp")),
            "api_as_of_utc": context.get("as_of_utc") or summary.get("as_of_utc"),
            "ticker": _ticker(ticker),
            "package": _package(package),
            "category": _category(category),
            "view": _view(view),
            "ok": 1,
            "spot": _number(summary.get("spot")),
            "zero_gamma": _number(payload.get("zero_gamma")),
            "call_wall": _wall_price(walls, "call_wall"),
            "put_wall": _wall_price(walls, "put_wall"),
            "oi_call_wall": _wall_price(walls, "oi_call_wall"),
            "oi_put_wall": _wall_price(walls, "oi_put_wall"),
            "sum_gex_vol": _number(aggregates.get("sum_gex_vol")),
            "sum_gex_oi": _number(aggregates.get("sum_gex_oi")),
            "raw_json": _json_dumps(payload),
            "context_json": _json_dumps(context),
            "error": None,
            "status": None,
        }
        row_id = self._insert(values)
        record = self.latest(
            ticker=ticker,
            package=package,
            category=category,
            view=view,
            ok_only=False,
            row_id=row_id,
        )
        if record is None:
            raise RuntimeError("stored GexBot snapshot could not be reloaded")
        return record

    def store_error(
        self,
        *,
        ticker: str,
        package: str,
        category: str,
        error: str,
        status: int | None = None,
        recorded_at_utc: str | None = None,
        view: str = "chain",
    ) -> SnapshotRecord:
        values = {
            "recorded_at_utc": recorded_at_utc or utc_now_iso(),
            "api_timestamp": None,
            "api_as_of_utc": None,
            "ticker": _ticker(ticker),
            "package": _package(package),
            "category": _category(category),
            "view": _view(view),
            "ok": 0,
            "spot": None,
            "zero_gamma": None,
            "call_wall": None,
            "put_wall": None,
            "oi_call_wall": None,
            "oi_put_wall": None,
            "sum_gex_vol": None,
            "sum_gex_oi": None,
            "raw_json": None,
            "context_json": None,
            "error": error,
            "status": status,
        }
        row_id = self._insert(values)
        record = self.latest(
            ticker=ticker,
            package=package,
            category=category,
            view=view,
            ok_only=False,
            row_id=row_id,
        )
        if record is None:
            raise RuntimeError("stored GexBot error snapshot could not be reloaded")
        return record

    def latest(
        self,
        *,
        ticker: str,
        package: str,
        category: str,
        view: str = "chain",
        ok_only: bool = True,
        row_id: int | None = None,
    ) -> SnapshotRecord | None:
        clauses = ["ticker = ?", "package = ?", "category = ?", "view = ?"]
        params: list[Any] = [_ticker(ticker), _package(package), _category(category), _view(view)]
        if ok_only:
            clauses.append("ok = 1")
        if row_id is not None:
            clauses.append("id = ?")
            params.append(row_id)
        sql = f"SELECT * FROM snapshots WHERE {' AND '.join(clauses)} ORDER BY recorded_at_utc DESC, id DESC LIMIT 1"
        with self._lock:
            row = self._conn.execute(sql, params).fetchone()
        return _record_from_row(row) if row is not None else None

    def history(
        self,
        *,
        ticker: str,
        package: str,
        category: str,
        view: str = "chain",
        since_utc: str | None = None,
        until_utc: str | None = None,
        limit: int = 500,
        ok_only: bool = True,
    ) -> list[SnapshotRecord]:
        clauses = ["ticker = ?", "package = ?", "category = ?", "view = ?"]
        params: list[Any] = [_ticker(ticker), _package(package), _category(category), _view(view)]
        if ok_only:
            clauses.append("ok = 1")
        if since_utc:
            clauses.append("recorded_at_utc >= ?")
            params.append(since_utc)
        if until_utc:
            clauses.append("recorded_at_utc <= ?")
            params.append(until_utc)
        params.append(max(1, min(int(limit), 5000)))
        sql = f"SELECT * FROM snapshots WHERE {' AND '.join(clauses)} ORDER BY recorded_at_utc DESC, id DESC LIMIT ?"
        with self._lock:
            rows = list(self._conn.execute(sql, params).fetchall())
        return [_record_from_row(row) for row in reversed(rows)]

    def prune(self, *, ttl_days: int | None = None) -> int:
        days = self.ttl_days if ttl_days is None else max(1, int(ttl_days))
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat().replace("+00:00", "Z")
        with self._lock:
            cursor = self._conn.execute("DELETE FROM snapshots WHERE recorded_at_utc < ?", (cutoff,))
            self._conn.commit()
            return int(cursor.rowcount or 0)

    def stats(self) -> dict[str, Any]:
        with self._lock:
            total = self._conn.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0]
            ok_total = self._conn.execute("SELECT COUNT(*) FROM snapshots WHERE ok = 1").fetchone()[0]
            latest = self._conn.execute("SELECT MAX(recorded_at_utc) FROM snapshots").fetchone()[0]
            groups = self._conn.execute(
                """
                SELECT ticker, package, category, view, COUNT(*) AS rows, MAX(recorded_at_utc) AS latest_recorded_at_utc
                FROM snapshots
                GROUP BY ticker, package, category, view
                ORDER BY ticker, package, category, view
                """
            ).fetchall()
        return {
            "path": str(self.path),
            "ttl_days": self.ttl_days,
            "schema_version": SCHEMA_VERSION,
            "rows": int(total),
            "ok_rows": int(ok_total),
            "latest_recorded_at_utc": latest,
            "groups": [dict(row) for row in groups],
        }

    def _initialize(self) -> None:
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._conn.execute("PRAGMA busy_timeout=30000")
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    recorded_at_utc TEXT NOT NULL,
                    api_timestamp REAL,
                    api_as_of_utc TEXT,
                    ticker TEXT NOT NULL,
                    package TEXT NOT NULL,
                    category TEXT NOT NULL,
                    view TEXT NOT NULL,
                    ok INTEGER NOT NULL,
                    spot REAL,
                    zero_gamma REAL,
                    call_wall REAL,
                    put_wall REAL,
                    oi_call_wall REAL,
                    oi_put_wall REAL,
                    sum_gex_vol REAL,
                    sum_gex_oi REAL,
                    raw_json TEXT,
                    context_json TEXT,
                    error TEXT,
                    status INTEGER
                )
                """
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_snapshots_key_time ON snapshots(ticker, package, category, view, recorded_at_utc DESC)"
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_snapshots_api_time ON snapshots(ticker, package, category, view, api_as_of_utc DESC)"
            )
            self._conn.execute(
                "INSERT OR REPLACE INTO metadata(key, value) VALUES('schema_version', ?)",
                (str(SCHEMA_VERSION),),
            )
            self._conn.commit()

    def _insert(self, values: dict[str, Any]) -> int:
        columns = list(values.keys())
        placeholders = ", ".join("?" for _ in columns)
        sql = f"INSERT INTO snapshots({', '.join(columns)}) VALUES({placeholders})"
        with self._lock:
            cursor = self._conn.execute(sql, [values[column] for column in columns])
            self._conn.commit()
            return int(cursor.lastrowid)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_utc(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _record_from_row(row: sqlite3.Row) -> SnapshotRecord:
    return SnapshotRecord(
        row_id=int(row["id"]),
        recorded_at_utc=str(row["recorded_at_utc"]),
        api_timestamp=_number(row["api_timestamp"]),
        api_as_of_utc=row["api_as_of_utc"],
        ticker=str(row["ticker"]),
        package=str(row["package"]),
        category=str(row["category"]),
        view=str(row["view"]),
        ok=bool(row["ok"]),
        spot=_number(row["spot"]),
        zero_gamma=_number(row["zero_gamma"]),
        call_wall=_number(row["call_wall"]),
        put_wall=_number(row["put_wall"]),
        oi_call_wall=_number(row["oi_call_wall"]),
        oi_put_wall=_number(row["oi_put_wall"]),
        sum_gex_vol=_number(row["sum_gex_vol"]),
        sum_gex_oi=_number(row["sum_gex_oi"]),
        raw=_json_loads(row["raw_json"]),
        context=_json_loads(row["context_json"]),
        error=row["error"],
        status=row["status"],
    )


def _json_dumps(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"), sort_keys=True)


def _json_loads(value: str | None) -> Any:
    if value is None:
        return None
    return json.loads(value)


def _wall_price(walls: dict[str, Any], key: str) -> float | None:
    value = walls.get(key)
    if not isinstance(value, dict):
        return None
    return _number(value.get("price"))


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _ticker(value: str) -> str:
    return value.strip().upper()


def _package(value: str) -> str:
    return value.strip().lower()


def _category(value: str) -> str:
    return value.strip().lower()


def _view(value: str) -> str:
    return value.strip().lower()
