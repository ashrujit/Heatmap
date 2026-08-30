"""Does MBO liquidity placement predict forward price beyond aggressor delta?

The scale-in rule only earns the extra machinery if order-level book features
carry information the footprint tape does not already have. This runs the
honest version of that test:

  * build 30s buckets of mid-relative add / fill / pull by side,
  * form candidate signals,
  * regress forward returns on each signal alone, then on delta plus the
    signal, and report the incremental R^2 over delta.

Chunked hourly so a full RTH session fits in memory.
"""
from __future__ import annotations

import argparse
import statistics

import polars as pl

from mbo_level_features import Window, ny_str
from mbo_flow_series import flow_series

SIGNALS = [
    "add_imb",       # where new passive liquidity is being placed
    "rest_add_imb",  # same, restricted to quotes that actually rest >= 1s
    "pull_imb",      # which side is being withdrawn unpaid
    "fill_imb",      # which side is being consumed (delta-like, from passive view)
    "delta_n",       # aggressor delta, normalised -- the footprint baseline
]


def hourly_chunks(day: str, symbol_dir: str, start_h: int, end_h: int,
                  interval_s: int, band_ticks: int) -> pl.DataFrame:
    frames = []
    for h in range(start_h, end_h):
        w = Window(symbol_dir, day, f"{h:02d}:00", f"{h + 1:02d}:00")
        try:
            frames.append(flow_series(w, interval_s=interval_s, band_ticks=band_ticks))
        except Exception as exc:  # missing capture hour
            print(f"  ! {day} {h:02d}:00 skipped: {type(exc).__name__}: {exc}")
    return pl.concat(frames, how="vertical_relaxed") if frames else pl.DataFrame()


def build_features(df: pl.DataFrame, horizons: list[int], interval_s: int) -> pl.DataFrame:
    def imb(a: str, b: str) -> pl.Expr:
        return (pl.col(a) - pl.col(b)) / (pl.col(a) + pl.col(b))

    out = df.sort("bkt").with_columns(
        imb("bid_add", "ask_add").alias("add_imb"),
        imb("bid_add_rest", "ask_add_rest").alias("rest_add_imb"),
        imb("ask_pull", "bid_pull").alias("pull_imb"),
        imb("ask_fill", "bid_fill").alias("fill_imb"),
        (pl.col("delta") / pl.col("vol")).alias("delta_n"),
    )
    for h in horizons:
        k = max(1, h // interval_s)
        out = out.with_columns(
            (pl.col("close").shift(-k) - pl.col("close")).alias(f"fwd_{h}s")
        )
    return out


def ols_r2(xs: list[list[float]], y: list[float]) -> float:
    """R^2 of an OLS fit with intercept, via normal equations. Small p, no numpy."""
    n = len(y)
    p = len(xs)
    cols = [[1.0] * n] + xs
    m = p + 1
    ata = [[sum(cols[i][k] * cols[j][k] for k in range(n)) for j in range(m)] for i in range(m)]
    atb = [sum(cols[i][k] * y[k] for k in range(n)) for i in range(m)]
    # gaussian elimination with partial pivoting
    for i in range(m):
        piv = max(range(i, m), key=lambda r: abs(ata[r][i]))
        if abs(ata[piv][i]) < 1e-12:
            return 0.0
        ata[i], ata[piv] = ata[piv], ata[i]
        atb[i], atb[piv] = atb[piv], atb[i]
        for r in range(i + 1, m):
            f = ata[r][i] / ata[i][i]
            for c in range(i, m):
                ata[r][c] -= f * ata[i][c]
            atb[r] -= f * atb[i]
    beta = [0.0] * m
    for i in reversed(range(m)):
        beta[i] = (atb[i] - sum(ata[i][j] * beta[j] for j in range(i + 1, m))) / ata[i][i]
    ybar = sum(y) / n
    sst = sum((v - ybar) ** 2 for v in y)
    if sst <= 0:
        return 0.0
    sse = 0.0
    for k in range(n):
        pred = beta[0] + sum(beta[i + 1] * xs[i][k] for i in range(p))
        sse += (y[k] - pred) ** 2
    return 1.0 - sse / sst


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
        print(f"# building {a.symbol_dir} {day} {a.start_hour:02d}:00-{a.end_hour:02d}:00")
        d = hourly_chunks(day, a.symbol_dir, a.start_hour, a.end_hour,
                          a.interval, a.band_ticks)
        if d.height:
            frames.append(build_features(d, a.horizons, a.interval))
    if not frames:
        print("no data")
        return
    df = pl.concat(frames, how="vertical_relaxed").drop_nulls(
        subset=SIGNALS + [f"fwd_{h}s" for h in a.horizons]
    )
    print(f"\n# buckets={df.height}  interval={a.interval}s  band={a.band_ticks}t")

    print("\n## signal autocorrelation and dispersion")
    for s in SIGNALS:
        v = df[s].to_list()
        lag1 = df.select(pl.corr(pl.col(s), pl.col(s).shift(1))).item()
        print(f"  {s:>13}: sd={statistics.pstdev(v):.4f}  ac1={lag1:+.3f}")

    for h in a.horizons:
        y = df[f"fwd_{h}s"].to_list()
        dn = df["delta_n"].to_list()
        base = ols_r2([dn], y)
        print(f"\n## forward {h}s return (points)   sd(y)={statistics.pstdev(y):.2f}")
        print(f"  {'signal':>13} {'corr':>8} {'R2_alone':>9} {'R2_with_delta':>14} {'dR2':>8}")
        print(f"  {'delta_n':>13} {df.select(pl.corr('delta_n', f'fwd_{h}s')).item():+8.3f} "
              f"{base:9.4f} {'-':>14} {'-':>8}")
        for s in SIGNALS:
            if s == "delta_n":
                continue
            xs = df[s].to_list()
            c = df.select(pl.corr(s, f"fwd_{h}s")).item()
            alone = ols_r2([xs], y)
            joint = ols_r2([dn, xs], y)
            print(f"  {s:>13} {c:+8.3f} {alone:9.4f} {joint:14.4f} {joint - base:+8.4f}")


if __name__ == "__main__":
    main()
