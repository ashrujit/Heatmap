"""Age-resolved liquidity: is the market eating patient orders or fresh quotes?

LevelLedger's BID_PULL / ASK_PULL grammar is inferred from aggregate size
deltas, so it cannot distinguish two very different events that look identical
in depth terms:

  * a 90-second-old resting order giving up and cancelling  (patient liquidity
    withdrawing -- a participant changing their mind)
  * a 20-millisecond quote flickering off                   (HFT churn -- noise)

Nor can it distinguish aggressors running over patient size from aggressors
skimming fresh quotes. With order-level identity and the exchange-time
alignment, both become measurable for the first time.

Hypotheses under test:
  H1  volume-weighted AGE of consumed liquidity carries information that
      aggressor delta does not.
  H2  pulls of OLD orders (patient withdrawal) are informative, while pulls of
      young orders are noise -- so splitting them beats the aggregate pull
      imbalance LevelLedger currently approximates.

Both are tested the same way as everything else: incremental R^2 over delta on
forward returns. A null result is a real result and should be reported as one.
"""
from __future__ import annotations

import argparse
import statistics

import polars as pl

from mbo_level_features import (
    FILL_BUCKET_US, Window, attribute_removals, load_book, load_ticks,
    signed_depth_deltas,
)
from mbo_flow_series import mid_by_second
from mbo_predictive_test import ols_r2

OLD_MS = 5_000.0


def aged_removals(w: Window) -> pl.DataFrame:
    """Every size removal, tagged with the age of the order it came from."""
    book = load_book(w)
    ticks = load_ticks(w)
    opens = book.group_by("quote_id_hash").agg(pl.col("t").min().alias("t_open"))

    rem = (
        signed_depth_deltas(book)
        .filter(pl.col("size_delta") < 0)
        .select("t", "price", "side", "quote_id_hash",
                (-pl.col("size_delta")).alias("removed"))
        .join(opens, on="quote_id_hash", how="left")
        .with_columns(((pl.col("t") - pl.col("t_open")) / 1000.0).alias("age_ms"))
        .drop_nulls("age_ms")
    )
    # per (5ms bucket, price, side) fill share, to split each removal
    attributed = attribute_removals(book, ticks).select(
        "b", "price", "side",
        pl.when(pl.col("removed_size") > 0)
        .then(pl.col("fill_size") / pl.col("removed_size"))
        .otherwise(0.0).alias("fill_share"),
    )
    return (
        rem.with_columns((pl.col("t") // FILL_BUCKET_US).alias("b"))
        .join(attributed, on=["b", "price", "side"], how="left")
        .with_columns(pl.col("fill_share").fill_null(0.0))
        .with_columns(
            (pl.col("removed") * pl.col("fill_share")).alias("filled"),
            (pl.col("removed") * (1 - pl.col("fill_share"))).alias("pulled"),
            (pl.col("age_ms") >= OLD_MS).alias("old"),
        )
    )


def age_series(w: Window, interval_s: int, band_ticks: int) -> pl.DataFrame:
    rem = aged_removals(w)
    mid = mid_by_second(w)
    sec = 1_000_000
    j = (
        rem.with_columns((pl.col("t") // sec).cast(pl.Int64).alias("s"))
        .join(mid.select("s", "mid"), on="s", how="inner")
        .with_columns(
            (((pl.col("price") - pl.col("mid")) / w.tick_size).round()
             * -pl.col("side")).alias("depth_ticks")
        )
        .filter((pl.col("depth_ticks") >= 0) & (pl.col("depth_ticks") <= band_ticks))
        .with_columns((pl.col("s") // interval_s * interval_s).cast(pl.Int64).alias("bkt"))
    )

    def side_agg(side: int, tag: str) -> pl.DataFrame:
        return (
            j.filter(pl.col("side") == side)
            .group_by("bkt")
            .agg(
                pl.col("filled").sum().alias(f"{tag}_fill"),
                pl.col("pulled").sum().alias(f"{tag}_pull"),
                pl.col("pulled").filter(pl.col("old")).sum().alias(f"{tag}_pull_old"),
                pl.col("pulled").filter(~pl.col("old")).sum().alias(f"{tag}_pull_young"),
                pl.col("filled").filter(pl.col("old")).sum().alias(f"{tag}_fill_old"),
                ((pl.col("age_ms") * pl.col("filled")).sum()
                 / pl.col("filled").sum().clip(lower_bound=1e-9)).alias(f"{tag}_fill_age"),
            )
        )

    tape = (
        mid.with_columns((pl.col("s") // interval_s * interval_s).cast(pl.Int64).alias("bkt"))
        .group_by("bkt")
        .agg(pl.col("mid").last().alias("close"), pl.col("vol").sum().alias("vol"),
             pl.col("delta").sum().alias("delta"))
    )
    return (
        side_agg(1, "bid")
        .join(side_agg(-1, "ask"), on="bkt", how="full", coalesce=True)
        .join(tape, on="bkt", how="left")
        .fill_null(0.0)
        .sort("bkt")
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", nargs="+", default=["2026-08-28"])
    ap.add_argument("--symbol-dir", default="ESU6")
    ap.add_argument("--interval", type=int, default=30)
    ap.add_argument("--band-ticks", type=int, default=20)
    ap.add_argument("--start-hour", type=int, default=9)
    ap.add_argument("--end-hour", type=int, default=16)
    ap.add_argument("--horizons", nargs="+", type=int, default=[60, 180, 300])
    a = ap.parse_args()

    frames = []
    for day in a.days:
        for h in range(a.start_hour, a.end_hour):
            w = Window(a.symbol_dir, day, f"{h:02d}:00", f"{h + 1:02d}:00")
            try:
                frames.append(age_series(w, a.interval, a.band_ticks))
            except Exception as exc:
                print(f"  ! {day} {h:02d}:00 skipped: {type(exc).__name__}")
        print(f"# built {day}")
    df = pl.concat(frames, how="vertical_relaxed").sort("bkt")

    def imb(x: str, y: str) -> pl.Expr:
        return (pl.col(x) - pl.col(y)) / (pl.col(x) + pl.col(y) + 1e-9)

    df = df.with_columns(
        # H1: are aggressors eating older bids than offers, or vice versa?
        (pl.col("bid_fill_age") - pl.col("ask_fill_age")).alias("fill_age_gap"),
        ((pl.col("bid_fill_age") + pl.col("ask_fill_age")) / 2).alias("fill_age_mean"),
        # H2: patient withdrawal, split from churn
        imb("ask_pull_old", "bid_pull_old").alias("pull_old_imb"),
        imb("ask_pull_young", "bid_pull_young").alias("pull_young_imb"),
        imb("ask_pull", "bid_pull").alias("pull_all_imb"),
        # share of consumption that ate patient size
        ((pl.col("bid_fill_old") + pl.col("ask_fill_old"))
         / (pl.col("bid_fill") + pl.col("ask_fill") + 1e-9)).alias("old_fill_share"),
        (pl.col("delta") / (pl.col("vol") + 1e-9)).alias("delta_n"),
    )
    for h in a.horizons:
        k = max(1, h // a.interval)
        df = df.with_columns((pl.col("close").shift(-k) - pl.col("close")).alias(f"fwd_{h}s"))

    sigs = ["fill_age_gap", "fill_age_mean", "old_fill_share",
            "pull_old_imb", "pull_young_imb", "pull_all_imb"]
    df = df.drop_nulls(subset=sigs + [f"fwd_{h}s" for h in a.horizons])
    print(f"\n# buckets={df.height}  old threshold={OLD_MS:.0f}ms")

    print("\n## what the age split actually looks like")
    for c in ["bid_fill_age", "ask_fill_age", "old_fill_share"]:
        v = df[c].to_list()
        print(f"  {c:>15}: median={statistics.median(v):10.1f}  "
              f"mean={statistics.fmean(v):10.1f}")
    tot_old = df["bid_pull_old"].sum() + df["ask_pull_old"].sum()
    tot_young = df["bid_pull_young"].sum() + df["ask_pull_young"].sum()
    print(f"  pulled size: old={tot_old:,.0f}  young={tot_young:,.0f}  "
          f"old share={tot_old / (tot_old + tot_young):.3f}")

    for h in a.horizons:
        y = df[f"fwd_{h}s"].to_list()
        dn = df["delta_n"].to_list()
        base = ols_r2([dn], y)
        print(f"\n## forward {h}s   sd(y)={statistics.pstdev(y):.2f}   "
              f"R2(delta alone)={base:.4f}")
        print(f"  {'signal':>16} {'corr':>8} {'R2_alone':>9} {'dR2_over_delta':>15}")
        for s in sigs:
            xs = df[s].to_list()
            c = df.select(pl.corr(s, f"fwd_{h}s")).item()
            print(f"  {s:>16} {c:+8.3f} {ols_r2([xs], y):9.4f} "
                  f"{ols_r2([dn, xs], y) - base:+15.4f}")


if __name__ == "__main__":
    main()
