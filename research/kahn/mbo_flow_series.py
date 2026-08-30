"""Mid-relative MBO flow series: who is adding, being consumed, and leaving.

Aggregate depth can tell you bid size fell. It cannot tell you whether that
size was *consumed* (aggressors paid for it) or *withdrawn* (makers cancelled
ahead of a move). Those two have opposite meanings for a campaign:

  * consumed  - the level is being paid for; absorption is happening.
  * withdrawn - the level is evaporating; the next aggressor gets a gap.

MBO separates them. This module produces a per-interval, mid-relative series
of add / fill / pull per side inside a band around the market, which is the
input a scale-in or harvest decision actually needs.
"""
from __future__ import annotations

import polars as pl

from mbo_level_features import Window, level_second_features, load_ticks


def mid_by_second(w: Window) -> pl.DataFrame:
    """Per-second reference price from the tape (last trade in that second)."""
    return (
        load_ticks(w, banded=False)
        .with_columns((pl.col("timestamp_us") // 1_000_000).alias("s"))
        .group_by("s")
        .agg(
            pl.col("price").last().alias("mid"),
            pl.col("price").max().alias("hi"),
            pl.col("price").min().alias("lo"),
            pl.col("size").sum().alias("vol"),
            (pl.col("size") * pl.col("aggressor_sign")).sum().alias("delta"),
        )
        .sort("s")
    )


def flow_series(w: Window, interval_s: int = 60, band_ticks: int = 20,
                resting_ms: float = 1000.0) -> pl.DataFrame:
    """Per-interval add/fill/pull by side, restricted to `band_ticks` of mid.

    Levels far from the market churn constantly and would swamp the signal, so
    the band is measured from the running mid rather than a fixed price range.
    """
    feats = level_second_features(w, resting_ms=resting_ms)
    mid = mid_by_second(w)
    joined = (
        feats.join(mid.select("s", "mid"), on="s", how="inner")
        .with_columns(
            ((pl.col("price") - pl.col("mid")) / w.tick_size).round().alias("off_ticks")
        )
        # side=+1 is bid (below mid), side=-1 is ask (above mid)
        .with_columns((pl.col("off_ticks") * -pl.col("side")).alias("depth_ticks"))
        .filter((pl.col("depth_ticks") >= 0) & (pl.col("depth_ticks") <= band_ticks))
        .with_columns((pl.col("s") // interval_s * interval_s).cast(pl.Int64).alias("bkt"))
    )
    agg = (
        joined.group_by("bkt", "side")
        .agg(
            pl.col("add_size").sum(),
            pl.col("add_size_resting").sum(),
            pl.col("fill_size").sum(),
            pl.col("pull_size").sum(),
        )
        .sort("bkt", "side")
    )
    bid = agg.filter(pl.col("side") == 1).drop("side")
    ask = agg.filter(pl.col("side") == -1).drop("side")
    out = (
        bid.join(ask, on="bkt", how="full", coalesce=True, suffix="_ask")
        .rename({
            "add_size": "bid_add", "add_size_resting": "bid_add_rest",
            "fill_size": "bid_fill", "pull_size": "bid_pull",
            "add_size_ask": "ask_add", "add_size_resting_ask": "ask_add_rest",
            "fill_size_ask": "ask_fill", "pull_size_ask": "ask_pull",
        })
        .fill_null(0.0)
        .with_columns(pl.col("bkt").cast(pl.Int64))
        .sort("bkt")
    )
    tape = (
        mid_by_second(w)
        .with_columns((pl.col("s") // interval_s * interval_s).cast(pl.Int64).alias("bkt"))
        .group_by("bkt")
        .agg(
            pl.col("mid").last().alias("close"),
            pl.col("hi").max().alias("high"),
            pl.col("lo").min().alias("low"),
            pl.col("vol").sum().alias("vol"),
            pl.col("delta").sum().alias("delta"),
        )
    )
    return (
        out.join(tape, on="bkt", how="left")
        .with_columns(
            # net book pressure: what left each side without being paid for
            (pl.col("bid_pull") - pl.col("ask_pull")).alias("pull_imbalance"),
            (pl.col("bid_add_rest") - pl.col("ask_add_rest")).alias("rest_add_imbalance"),
            # share of each side's disappearance that was paid for
            pl.when(pl.col("bid_fill") + pl.col("bid_pull") > 0)
            .then(pl.col("bid_fill") / (pl.col("bid_fill") + pl.col("bid_pull")))
            .otherwise(None).alias("bid_paid_share"),
            pl.when(pl.col("ask_fill") + pl.col("ask_pull") > 0)
            .then(pl.col("ask_fill") / (pl.col("ask_fill") + pl.col("ask_pull")))
            .otherwise(None).alias("ask_paid_share"),
        )
        .sort("bkt")
    )
