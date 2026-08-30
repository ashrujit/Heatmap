"""ES 2026-08-28 short campaign: was the 7777-7782 offer a real defender?

Campaign as declared by the user: short from the 7780 region, issued after
11:20 ET, harvest target 7740, invalidated by extension above 7782.

The scale-in question is whether the ask side above 7777 was durable enough to
justify building size inside a 4-point band, or whether it was quote churn that
happened to hold. Aggregate depth cannot answer that. MBO can.
"""
from __future__ import annotations

import argparse
import sys
import os

import polars as pl

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mbo_level_features import (  # noqa: E402
    Window, coverage_summary, level_second_features, load_ticks, quote_lifecycle, load_book,
)


def minute_tape(w: Window) -> pl.DataFrame:
    tk = load_ticks(w)
    return (
        tk.with_columns((pl.col("timestamp_us") // 60_000_000).alias("m"))
        .group_by("m")
        .agg(
            pl.col("price").max().alias("h"),
            pl.col("price").min().alias("l"),
            pl.col("price").last().alias("c"),
            pl.col("size").sum().alias("vol"),
            (pl.col("size") * pl.col("aggressor_sign")).sum().alias("delta"),
        )
        .sort("m")
    )


def band_profile(w: Window, side: int, label: str, resting_ms: float) -> None:
    """Per-price summary of add / fill / pull and resting-quote share."""
    feats = level_second_features(w, resting_ms=resting_ms)
    b = (
        feats.filter(pl.col("side") == side)
        .group_by("price")
        .agg(
            pl.col("add_size").sum(),
            pl.col("add_size_resting").sum(),
            pl.col("add_orders").sum(),
            pl.col("add_orders_resting").sum(),
            pl.col("fill_size").sum(),
            pl.col("pull_size").sum(),
        )
        .sort("price")
        .with_columns(
            (pl.col("add_size_resting") / pl.col("add_size")).alias("resting_share"),
            (pl.col("add_size") / (pl.col("fill_size") + pl.col("pull_size")))
            .alias("replenish"),
            (pl.col("fill_size") / (pl.col("fill_size") + pl.col("pull_size")))
            .alias("fill_share"),
            (pl.col("add_size_resting") / pl.col("add_orders_resting"))
            .alias("resting_lot"),
        )
    )
    print(f"\n## {label} (side={side:+d}, resting >= {resting_ms:.0f}ms)")
    print(f"{'price':>9} {'add':>9} {'rest_add':>9} {'rest_sh':>8} {'fill':>8} "
          f"{'pull':>9} {'fill_sh':>8} {'replen':>7} {'rest_lot':>8}")
    for r in b.to_dicts():
        print(f"{r['price']:9.2f} {r['add_size']:9.0f} {r['add_size_resting']:9.0f} "
              f"{(r['resting_share'] or 0):8.3f} {r['fill_size']:8.0f} {r['pull_size']:9.0f} "
              f"{(r['fill_share'] or 0):8.3f} {(r['replenish'] or 0):7.2f} "
              f"{(r['resting_lot'] or 0):8.1f}")


def resting_orders(w: Window, side: int, min_size: float, min_life_ms: float) -> None:
    """The individual durable quotes -- who was actually standing there."""
    book = load_book(w)
    life = quote_lifecycle(book).filter(
        (pl.col("side") == side)
        & (pl.col("size") >= min_size)
        & (pl.col("life_ms") >= min_life_ms)
    )
    from mbo_level_features import ny_str
    print(f"\n## durable quotes side={side:+d} size>={min_size:.0f} life>={min_life_ms:.0f}ms "
          f"(n={life.height}, total size={life['size'].sum():.0f})")
    for r in life.sort("t_open").head(40).to_dicts():
        print(f"  {ny_str(r['t_open'])} -> {ny_str(r['t_close'])} "
              f"{r['price']:9.2f} size={r['size']:6.0f} life={r['life_ms']/1000:8.1f}s")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--day", default="2026-08-28")
    ap.add_argument("--symbol-dir", default="ESU6")
    ap.add_argument("--start", default="11:20")
    ap.add_argument("--end", default="11:36")
    ap.add_argument("--lo", type=float, default=7775.0)
    ap.add_argument("--hi", type=float, default=7784.0)
    ap.add_argument("--side", type=int, default=-1, help="-1 ask (supply), +1 bid (demand)")
    ap.add_argument("--resting-ms", type=float, default=1000.0)
    ap.add_argument("--durable-size", type=float, default=15.0)
    ap.add_argument("--durable-life-ms", type=float, default=5000.0)
    ap.add_argument("--tape", action="store_true")
    a = ap.parse_args()

    w = Window(a.symbol_dir, a.day, a.start, a.end, price_lo=a.lo, price_hi=a.hi)
    print(f"# {a.symbol_dir} {a.day} {a.start}-{a.end} ET  band {a.lo}-{a.hi}")
    cov = coverage_summary(w)
    for k, v in cov.items():
        print(f"  {k:>16}: {v:,.3f}" if isinstance(v, float) else f"  {k:>16}: {v:,}")

    if a.tape:
        print("\n## tape")
        from mbo_level_features import ny_str
        for r in minute_tape(w).to_dicts():
            print(f"  {ny_str(r['m']*60_000_000)}  H{r['h']:8.2f} L{r['l']:8.2f} "
                  f"C{r['c']:8.2f} v{r['vol']:6.0f} d{r['delta']:+6.0f}")

    band_profile(w, a.side, f"band {a.lo}-{a.hi}", a.resting_ms)
    resting_orders(w, a.side, a.durable_size, a.durable_life_ms)


if __name__ == "__main__":
    main()
