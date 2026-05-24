"""Quick sanity check for L2 + tick captures.

Reads MarketRecorder chunks when present and falls back to legacy L2_Heatmap
daily files. Use SESSION=YYYY-MM-DD SYMBOL_DIR=NQM6 LEVELS=30 to override.
"""

import datetime as dt
import os
from zoneinfo import ZoneInfo

import polars as pl

from capture_loader import load_capture_day, snapshot_columns, tick_columns


SESSION = os.environ.get("SESSION", "2026-05-22")
SYMBOL_DIR = os.environ.get("SYMBOL_DIR", "NQM6")
LEVELS = int(os.environ.get("LEVELS", "30"))
ny = ZoneInfo("America/New_York")


def utc_to_ny(us):
    return dt.datetime.fromtimestamp(us / 1e6, tz=ny)


print(f"capture peek: SESSION={SESSION} SYMBOL_DIR={SYMBOL_DIR} LEVELS={LEVELS}")

# ---- Snapshots ----
print("=== SNAPSHOTS ===")
try:
    snap = load_capture_day("snapshots", SYMBOL_DIR, SESSION, snapshot_columns(LEVELS))
    print(f"rows: {snap.height:,}  cols: {snap.width}")
    print(f"size: {snap.estimated_size('mb'):.1f} MB in memory")

    ts_min, ts_max = snap.select(pl.col("timestamp_us").min().alias("lo"), pl.col("timestamp_us").max().alias("hi")).row(0)
    print(f"time range (NY): {utc_to_ny(ts_min):%H:%M:%S}  ->  {utc_to_ny(ts_max):%H:%M:%S}")
    print(f"span: {(ts_max - ts_min) / 1e6 / 3600:.2f} hours")

    deltas = snap.select(pl.col("timestamp_us").diff().alias("d")).drop_nulls()
    print(f"snapshot interval (median): {deltas['d'].median()/1000:.0f} ms"
          f"  (p95: {deltas['d'].quantile(0.95)/1000:.0f} ms)")

    rt_min, rt_max = snap.select(pl.col("ref_tick").min().alias("lo"), pl.col("ref_tick").max().alias("hi")).row(0)
    print(f"ref_tick range: {rt_min} -> {rt_max}  (price: {rt_min*0.25:.2f} -> {rt_max*0.25:.2f})")

    bid_cols = [f"bid_size_{i}" for i in range(LEVELS)]
    ask_cols = [f"ask_size_{i}" for i in range(LEVELS)]
    non_empty_bids = snap.select(pl.sum_horizontal([pl.col(c) > 0 for c in bid_cols]).alias("n"))["n"]
    non_empty_asks = snap.select(pl.sum_horizontal([pl.col(c) > 0 for c in ask_cols]).alias("n"))["n"]
    print(f"non-empty bid levels per snap: median={non_empty_bids.median():.0f}  "
          f"p25={non_empty_bids.quantile(0.25):.0f}  p99={non_empty_bids.quantile(0.99):.0f}")
    print(f"non-empty ask levels per snap: median={non_empty_asks.median():.0f}  "
          f"p25={non_empty_asks.quantile(0.25):.0f}  p99={non_empty_asks.quantile(0.99):.0f}")

    total_bid = snap.select(pl.sum_horizontal(bid_cols).alias("s"))["s"]
    total_ask = snap.select(pl.sum_horizontal(ask_cols).alias("s"))["s"]
    print(f"total bid depth: median={total_bid.median():.0f}  p25={total_bid.quantile(0.25):.0f}  p99={total_bid.quantile(0.99):.0f}")
    print(f"total ask depth: median={total_ask.median():.0f}  p25={total_ask.quantile(0.25):.0f}  p99={total_ask.quantile(0.99):.0f}")

    print("\nSample row (first):")
    r = snap.row(0, named=True)
    print(f"  ts: {utc_to_ny(r['timestamp_us']):%H:%M:%S.%f} ref_tick: {r['ref_tick']} (~{r['ref_tick']*0.25:.2f})")
    print("  best 5 bids: " + ", ".join(f"({r[f'bid_offset_{i}']}, {r[f'bid_size_{i}']:.0f})" for i in range(min(5, LEVELS))))
    print("  best 5 asks: " + ", ".join(f"({r[f'ask_offset_{i}']}, {r[f'ask_size_{i}']:.0f})" for i in range(min(5, LEVELS))))
except Exception as ex:
    print(f"unreadable: {type(ex).__name__}: {ex}")

# ---- Ticks ----
print("\n=== TICKS ===")
ticks = load_capture_day("ticks", SYMBOL_DIR, SESSION, tick_columns())
print(f"rows: {ticks.height:,}  cols: {ticks.width}")
ts_min, ts_max = ticks.select(pl.col("timestamp_us").min().alias("lo"), pl.col("timestamp_us").max().alias("hi")).row(0)
print(f"time range (NY): {utc_to_ny(ts_min):%H:%M:%S}  ->  {utc_to_ny(ts_max):%H:%M:%S}")
print(f"price range: {ticks['price'].min():.2f} -> {ticks['price'].max():.2f}")
print(f"total volume: {ticks['size'].sum():,.0f}")
ag_counts = ticks.group_by("aggressor_sign").agg(pl.len().alias("n"), pl.col("size").sum().alias("vol"))
print("aggressor breakdown:")
for r in ag_counts.iter_rows(named=True):
    label = {1: "Buy", -1: "Sell", 0: "None/NotSet"}.get(r["aggressor_sign"], "?")
    print(f"  {r['aggressor_sign']:+d} ({label}): {r['n']:,} prints, vol {r['vol']:,.0f}")

deltas = ticks.select(pl.col("timestamp_us").diff().alias("d")).drop_nulls()
print(f"inter-tick interval: median={deltas['d'].median()/1000:.1f} ms  "
      f"p95={deltas['d'].quantile(0.95)/1000:.0f} ms")
