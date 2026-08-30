"""What is a LevelLedger BID_PULL actually made of?

LevelLedger fires BID_PULL / ASK_PULL from a z-score on aggregate inner-10
depth, sampled at 1Hz (LevelLedgerEngine.ComputeSample + TryFire; defaults
InnerLevels=10, BookLookbackSeconds=30, EventZThreshold=2.5).

That statistic is a LEVEL, not a flow. Inner bid depth falls for two reasons
that mean opposite things:

  * sell aggressors CONSUMED the bids   -> someone paid to hit that support
  * bid makers CANCELLED               -> support withdrew without a trade

The indicator cannot tell them apart, and the ledger vocabulary ("pull")
asserts the second. With order-level identity plus exchange-time alignment we
can finally measure the mix.

This script replicates the detector exactly on captured snapshots, then
decomposes each firing window with MBO attribution.
"""
from __future__ import annotations

import argparse
import statistics

import polars as pl

from mbo_level_features import (
    FILL_BUCKET_US, Window, attribute_removals, load_book, load_ticks,
    ny_str, signed_depth_deltas, snapshot_depth,
)

INNER_LEVELS = 10
LOOKBACK_SEC = 30
Z_THRESHOLD = 2.5


def inner_depth_series(w: Window, levels: int = INNER_LEVELS) -> pl.DataFrame:
    """Per-second BidInner / AskInner, exactly as ComputeSample builds them."""
    d = snapshot_depth(w, levels=levels)
    if not d.height:
        return pl.DataFrame()
    # snapshot_depth already emits one row per (t, price, side) for `levels`
    # levels a side, so summing per (t, side) reproduces BidInner / AskInner.
    wide = (
        d.group_by("t", "side").agg(pl.col("depth").sum().alias("inner"))
        .sort("t")
    )
    bid = wide.filter(pl.col("side") == 1).select("t", pl.col("inner").alias("bid_inner"))
    ask = wide.filter(pl.col("side") == -1).select("t", pl.col("inner").alias("ask_inner"))
    return bid.join(ask, on="t", how="inner").sort("t")


def detector_events(w: Window, z_threshold: float = Z_THRESHOLD,
                    lookback: int = LOOKBACK_SEC) -> pl.DataFrame:
    """Replicate TryFire on BidInner / AskInner: z beyond threshold fires."""
    s = inner_depth_series(w)
    if not s.height:
        return pl.DataFrame()
    out = s.with_columns(
        pl.col("bid_inner").rolling_mean(lookback).alias("bm"),
        pl.col("bid_inner").rolling_std(lookback).alias("bs"),
        pl.col("ask_inner").rolling_mean(lookback).alias("am"),
        pl.col("ask_inner").rolling_std(lookback).alias("as_"),
    ).with_columns(
        ((pl.col("bid_inner") - pl.col("bm")) / pl.max_horizontal(pl.col("bs"), pl.lit(1.0))).alias("zb"),
        ((pl.col("ask_inner") - pl.col("am")) / pl.max_horizontal(pl.col("as_"), pl.lit(1.0))).alias("za"),
    ).drop_nulls(["zb", "za"])

    ev = []
    for side, zc, pos, neg in ((1, "zb", "BID_BUILD", "BID_PULL"),
                               (-1, "za", "ASK_BUILD", "ASK_PULL")):
        f = out.filter(pl.col(zc).abs() > z_threshold)
        ev.append(f.select(
            "t", pl.lit(side, dtype=pl.Int32).alias("side"), pl.col(zc).alias("z"),
            pl.when(pl.col(zc) > 0).then(pl.lit(pos)).otherwise(pl.lit(neg)).alias("event"),
        ))
    return pl.concat(ev).sort("t") if ev else pl.DataFrame()


def decompose(w: Window, events: pl.DataFrame, window_sec: int = 5) -> pl.DataFrame:
    """For each event, split the preceding window's removals into fill vs pull."""
    book = load_book(w)
    ticks = load_ticks(w)
    adds = (
        signed_depth_deltas(book)
        .filter(pl.col("size_delta") > 0)
        .select("t", "price", "side", pl.col("size_delta").alias("add_size"))
    )
    attributed = (
        attribute_removals(book, ticks)
        .with_columns((pl.col("b") * FILL_BUCKET_US).alias("t"))
        .select("t", "price", "side", "fill_size", "pull_size")
    )
    mid = (
        ticks.with_columns((pl.col("timestamp_us") // 1_000_000).cast(pl.Int64).alias("s"))
        .group_by("s").agg(pl.col("price").last().alias("mid"))
    )
    flow = (
        attributed.with_columns((pl.col("t") // 1_000_000).cast(pl.Int64).alias("s"))
        .join(mid, on="s", how="inner")
        .with_columns(
            (((pl.col("price") - pl.col("mid")) / w.tick_size).round()
             * -pl.col("side")).alias("depth_ticks")
        )
        # inner-10 levels of that side
        .filter((pl.col("depth_ticks") >= 0) & (pl.col("depth_ticks") < INNER_LEVELS))
        .group_by("s", "side")
        .agg(pl.col("fill_size").sum(), pl.col("pull_size").sum())
    )
    addflow = (
        adds.with_columns((pl.col("t") // 1_000_000).cast(pl.Int64).alias("s"))
        .join(mid, on="s", how="inner")
        .with_columns(
            (((pl.col("price") - pl.col("mid")) / w.tick_size).round()
             * -pl.col("side")).alias("depth_ticks")
        )
        .filter((pl.col("depth_ticks") >= 0) & (pl.col("depth_ticks") < INNER_LEVELS))
        .group_by("s", "side")
        .agg(pl.col("add_size").sum())
    )

    rows = []
    for e in events.iter_rows(named=True):
        s1 = e["t"] // 1_000_000
        s0 = s1 - window_sec
        f = flow.filter(
            (pl.col("side") == e["side"]) & (pl.col("s") > s0) & (pl.col("s") <= s1)
        )
        g = addflow.filter(
            (pl.col("side") == e["side"]) & (pl.col("s") > s0) & (pl.col("s") <= s1)
        )
        fill = float(f["fill_size"].sum()) if f.height else 0.0
        pull = float(f["pull_size"].sum()) if f.height else 0.0
        add = float(g["add_size"].sum()) if g.height else 0.0
        tot = fill + pull
        m = mid.filter((pl.col("s") > s0) & (pl.col("s") <= s1)).sort("s")
        dmid = float(m["mid"][-1] - m["mid"][0]) if m.height > 1 else 0.0
        rows.append({
            "t": e["t"], "event": e["event"], "z": e["z"],
            "fill": fill, "pull": pull, "add": add,
            "consumed_share": fill / tot if tot > 0 else None,
            "add_over_removal": add / tot if tot > 0 else None,
            "dmid": dmid,
        })
    return pl.DataFrame(rows) if rows else pl.DataFrame()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", nargs="+", default=["2026-08-27", "2026-08-28"])
    ap.add_argument("--symbol-dir", default="ESU6")
    ap.add_argument("--start-hour", type=int, default=9)
    ap.add_argument("--end-hour", type=int, default=16)
    ap.add_argument("--window-sec", type=int, default=5)
    ap.add_argument("--z", type=float, default=Z_THRESHOLD)
    a = ap.parse_args()

    frames = []
    for day in a.days:
        for h in range(a.start_hour, a.end_hour):
            w = Window(a.symbol_dir, day, f"{h:02d}:00", f"{h + 1:02d}:00")
            try:
                ev = detector_events(w, a.z)
                if ev.height:
                    frames.append(decompose(w, ev, a.window_sec))
            except Exception as exc:
                print(f"  ! {day} {h:02d}:00 {type(exc).__name__}: {str(exc)[:60]}")
        print(f"# built {day}")
    df = pl.concat(frames, how="vertical_relaxed").drop_nulls("consumed_share")
    print(f"\n# LevelLedger-equivalent events: {df.height} "
          f"(InnerLevels={INNER_LEVELS}, lookback={LOOKBACK_SEC}s, z>{a.z}, "
          f"decomposition window={a.window_sec}s)")

    print(f"\n{'event':>11} {'n':>5} {'consumed_share':>15} {'add/rem':>9} "
          f"{'add/ev':>9} {'fill/ev':>9} {'pull/ev':>9} {'med_dmid':>9} {'med|dmid|':>9}")
    for name in ["BID_PULL", "ASK_PULL", "BID_BUILD", "ASK_BUILD"]:
        g = df.filter(pl.col("event") == name)
        if not g.height:
            continue
        cs = g["consumed_share"].to_list()
        n = g.height
        print(f"{name:>11} {n:5d} {statistics.median(cs):15.3f} "
              f"{g['add_over_removal'].median():12.3f} "
              f"{g['add'].sum() / n:9,.0f} {g['fill'].sum() / n:9,.0f} "
              f"{g['pull'].sum() / n:9,.0f} {g['dmid'].median():+9.2f} "
              f"{g['dmid'].abs().median():9.2f}")

    for name in ["BID_PULL", "ASK_PULL"]:
        g = df.filter(pl.col("event") == name)
        if not g.height:
            continue
        mostly_consumed = g.filter(pl.col("consumed_share") > 0.5).height
        print(f"\n{name}: {mostly_consumed}/{g.height} "
              f"({mostly_consumed / g.height:.1%}) of firings were MOSTLY CONSUMPTION, "
              f"not withdrawal.")


if __name__ == "__main__":
    main()
