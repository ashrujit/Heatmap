"""Shared capture loader for legacy L2_Heatmap files and MarketRecorder chunks."""

from __future__ import annotations

import datetime as dt
import glob
import os
from zoneinfo import ZoneInfo

import polars as pl


NY = ZoneInfo("America/New_York")
PARQUET_SCHEMA_DRIFT_OPTIONS = {
    "missing_columns": "insert",
    "extra_columns": "ignore",
}
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


def book_event_columns() -> list[str]:
    return [
        "receipt_timestamp_us",
        "exchange_timestamp_us",
        "sequence",
        "subsequence",
        "reset_epoch",
        "event_kind",
        "side",
        "price_tick",
        "size",
        "closed",
        "quote_id_hash",
        "implied_size",
        "priority",
        "number_orders",
        "reset_item_count",
        "gap_start_sequence",
        "gap_end_sequence",
    ]


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


def market_recorder_window_files(
    symbol_dir: str,
    kind: str,
    day: dt.date,
    start: dt.datetime,
    end: dt.datetime,
    root: str = MARKET_RECORDER_ROOT,
    *,
    inclusive_end: bool = False,
) -> list[str]:
    return [
        path
        for path in market_recorder_files(symbol_dir, kind, day, root)
        if chunk_file_overlaps(path, day, start, end, inclusive_end=inclusive_end)
    ]


def chunk_file_overlaps(
    path: str,
    day: dt.date,
    start: dt.datetime,
    end: dt.datetime,
    *,
    inclusive_end: bool = False,
) -> bool:
    name = os.path.splitext(os.path.basename(path))[0]
    parts = name.rsplit(chr(45), 2)
    if len(parts) != 3 or len(parts[1]) != 6 or len(parts[2]) != 6:
        return True
    if not parts[1].isdigit() or not parts[2].isdigit():
        return True

    chunk_start = parse_chunk_time(day, parts[1])
    chunk_end = parse_chunk_time(day, parts[2])
    if chunk_end < chunk_start:
        chunk_end += dt.timedelta(days=1)

    start_ny = start.astimezone(NY) if start.tzinfo else start.replace(tzinfo=NY)
    end_ny = end.astimezone(NY) if end.tzinfo else end.replace(tzinfo=NY)
    if inclusive_end:
        return chunk_start <= end_ny and chunk_end >= start_ny
    return chunk_start < end_ny and chunk_end >= start_ny


def parse_chunk_time(day: dt.date, value: str) -> dt.datetime:
    return dt.datetime(
        day.year,
        day.month,
        day.day,
        int(value[0:2]),
        int(value[2:4]),
        int(value[4:6]),
        tzinfo=NY,
    )


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

    if kind not in ("snapshots", "ticks", "book_events"):
        raise ValueError("kind must be 'snapshots', 'ticks', or 'book_events'")
    if columns is not None:
        cols = columns
    elif kind == "snapshots":
        cols = snapshot_columns()
    elif kind == "book_events":
        cols = book_event_columns()
    else:
        cols = tick_columns()
    lo = us(start)
    hi = us(end)
    time_col = "receipt_timestamp_us" if kind == "book_events" else "timestamp_us"
    hi_filter = pl.col(time_col) <= hi if inclusive_end else pl.col(time_col) < hi
    scans: list[pl.LazyFrame] = []
    missing: list[str] = []

    for day in ny_day_range(start, end, inclusive_end=inclusive_end):
        chunk_files = market_recorder_window_files(
            symbol_dir,
            kind,
            day,
            start,
            end,
            inclusive_end=inclusive_end,
        )
        if chunk_files:
            scans.append(
                pl.scan_parquet(chunk_files, **PARQUET_SCHEMA_DRIFT_OPTIONS)
                .select(cols)
                .filter(pl.all_horizontal(pl.col(time_col) >= lo, hi_filter))
            )
            continue

        path = legacy_file(symbol_dir, kind, day)
        if os.path.exists(path):
            scans.append(
                pl.scan_parquet(path, **PARQUET_SCHEMA_DRIFT_OPTIONS)
                .select(cols)
                .filter(pl.all_horizontal(pl.col(time_col) >= lo, hi_filter))
            )
            continue

        copied = copy_file(symbol_dir, kind, day)
        if os.path.exists(copied):
            scans.append(
                pl.scan_parquet(copied, **PARQUET_SCHEMA_DRIFT_OPTIONS)
                .select(cols)
                .filter(pl.all_horizontal(pl.col(time_col) >= lo, hi_filter))
            )
            continue

        missing.append(day.isoformat())

    if not scans:
        raise FileNotFoundError(f"no {kind} captures for {symbol_dir} days={','.join(missing)}")
    return pl.concat(scans, how="diagonal").collect().sort(time_col)


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
