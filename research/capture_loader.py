"""Shared capture loader for legacy L2_Heatmap files and MarketRecorder chunks."""

from __future__ import annotations

import datetime as dt
import glob
import os
from zoneinfo import ZoneInfo

import polars as pl


NY = ZoneInfo("America/New_York")
LEGACY_CAPTURE_ROOT = os.environ.get(
    "LEGACY_CAPTURE_ROOT",
    r"C:\Quantower\Settings\Scripts\Indicators\L2_Heatmap\captures",
)
MARKET_RECORDER_ROOT = os.environ.get(
    "MARKET_RECORDER_ROOT",
    r"C:\Quantower\Settings\Scripts\Indicators\MarketRecorder\captures",
)
CAPTURE_COPY_ROOT = os.environ.get(
    "CAPTURE_COPY_ROOT",
    r"C:\Users\j\AppData\Local\Temp\cap_copy",
)


def snapshot_columns(levels: int = 30) -> list[str]:
    cols = ["timestamp_us", "ref_tick"]
    for i in range(levels):
        cols.extend([f"bid_offset_{i}", f"bid_size_{i}", f"ask_offset_{i}", f"ask_size_{i}"])
    return cols


def tick_columns() -> list[str]:
    return ["timestamp_us", "price", "size", "aggressor_sign"]


def us(ts: dt.datetime) -> int:
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=NY)
    return int(ts.timestamp() * 1_000_000)


def ny_day_range(start: dt.datetime, end: dt.datetime, *, inclusive_end: bool = False) -> list[dt.date]:
    start_ny = start.astimezone(NY) if start.tzinfo else start.replace(tzinfo=NY)
    end_ny = end.astimezone(NY) if end.tzinfo else end.replace(tzinfo=NY)
    day = start_ny.date()
    last = end_ny.date()
    if (
        not inclusive_end
        and end_ny.timetz().hour == 0
        and end_ny.timetz().minute == 0
        and end_ny.timetz().second == 0
        and end_ny.timetz().microsecond == 0
    ):
        last -= dt.timedelta(days=1)
    out: list[dt.date] = []
    while day <= last:
        out.append(day)
        day += dt.timedelta(days=1)
    return out


def market_recorder_files(symbol_dir: str, kind: str, day: dt.date, root: str = MARKET_RECORDER_ROOT) -> list[str]:
    pattern = os.path.join(root, symbol_dir, day.isoformat(), kind, "*.parquet")
    return sorted(glob.glob(pattern))


def legacy_file(symbol_dir: str, kind: str, day: dt.date, root: str = LEGACY_CAPTURE_ROOT) -> str:
    return os.path.join(root, symbol_dir, f"{kind}-{day.isoformat()}.parquet")


def copy_file(symbol_dir: str, kind: str, day: dt.date, root: str = CAPTURE_COPY_ROOT) -> str:
    nested = os.path.join(root, symbol_dir, f"{kind}-{day.isoformat()}.parquet")
    if os.path.exists(nested):
        return nested
    return os.path.join(root, f"{kind}-{day.isoformat()}.parquet")


def load_capture_window(
    kind: str,
    symbol_dir: str,
    start: dt.datetime,
    end: dt.datetime,
    columns: list[str] | None = None,
    *,
    inclusive_end: bool = False,
) -> pl.DataFrame:
    """Load snapshots or ticks over a datetime window.

    MarketRecorder chunk files are preferred per day. If no chunks exist for a
    day, the legacy L2_Heatmap daily file is used. A temp copy root remains as a
    final fallback for older scripts that copied locked files during live use.
    """

    if kind not in ("snapshots", "ticks"):
        raise ValueError("kind must be 'snapshots' or 'ticks'")
    cols = columns or (snapshot_columns() if kind == "snapshots" else tick_columns())
    lo = us(start)
    hi = us(end)
    hi_filter = pl.col("timestamp_us") <= hi if inclusive_end else pl.col("timestamp_us") < hi
    scans: list[pl.LazyFrame] = []
    missing: list[str] = []

    for day in ny_day_range(start, end, inclusive_end=inclusive_end):
        chunk_files = market_recorder_files(symbol_dir, kind, day)
        if chunk_files:
            scans.append(
                pl.scan_parquet(chunk_files)
                .select(cols)
                .filter((pl.col("timestamp_us") >= lo) & hi_filter)
            )
            continue

        path = legacy_file(symbol_dir, kind, day)
        if os.path.exists(path):
            scans.append(
                pl.scan_parquet(path)
                .select(cols)
                .filter((pl.col("timestamp_us") >= lo) & hi_filter)
            )
            continue

        copied = copy_file(symbol_dir, kind, day)
        if os.path.exists(copied):
            scans.append(
                pl.scan_parquet(copied)
                .select(cols)
                .filter((pl.col("timestamp_us") >= lo) & hi_filter)
            )
            continue

        missing.append(day.isoformat())

    if not scans:
        raise FileNotFoundError(f"no {kind} captures for {symbol_dir} days={','.join(missing)}")
    return pl.concat(scans, how="diagonal").collect().sort("timestamp_us")


def load_capture_day(
    kind: str,
    symbol_dir: str,
    day: str | dt.date,
    columns: list[str] | None = None,
) -> pl.DataFrame:
    d = dt.date.fromisoformat(day) if isinstance(day, str) else day
    start = dt.datetime(d.year, d.month, d.day, 0, 0, 0, tzinfo=NY)
    end = start + dt.timedelta(days=1)
    return load_capture_window(kind, symbol_dir, start, end, columns)


def add_ny_ts(df: pl.DataFrame) -> pl.DataFrame:
    return df.with_columns(
        pl.from_epoch("timestamp_us", time_unit="us")
        .dt.replace_time_zone("UTC")
        .dt.convert_time_zone("America/New_York")
        .alias("ts")
    )


def add_utc_ts(df: pl.DataFrame) -> pl.DataFrame:
    return df.with_columns(
        pl.from_epoch("timestamp_us", time_unit="us")
        .dt.replace_time_zone("UTC")
        .alias("ts")
    )
