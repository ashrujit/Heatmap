"""Liquidity-event extractor for context-reading alongside the chart.

Same posture as the Absorption_Exhaustion indicator: surface
microstructure transitions as a time-ordered stream, let the trader
read them in context. NO sequence pattern-mining, NO ranked-by-
significance views, NO claim that any one event "means" anything on
its own. Single-day correlation hunting is statistically maddening at
best and self-deceiving at worst.

Output is the time-ordered events CSV. The trader reads it the same
way they read A/E paints — as timing/color for what they're already
seeing in price. Cross-correlogram is at the bottom as a long-term
diagnostic (population property, only meaningful across many sessions).

Reads one day's L2 snapshot + tick capture, derives:
  - inner_depth     : sum of top-10 sizes each side (closest to mid)
  - centroid_dist   : size-weighted mean |offset| (where mass sits)
  - vod             : rolling-30s stdev of d/dt(inner_depth)  ≈ σ(ΔLiq)
  - rv              : rolling-30s bipower variation (jump-robust RV)

Detects events at |z| > 2.5 with sign disambiguation (LIQ_BUILD/PULL,
DEPTH_OUT/IN, VOL_OF_DEPTH_SPIKE), filters to RTH only.
"""
import polars as pl
import numpy as np
import datetime as dt
import os, sys
from zoneinfo import ZoneInfo
# Force UTF-8 stdout so Polars tables (unicode box-draw) don't crash on cp1252
try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

LIVE = r"C:\Quantower\Settings\Scripts\Indicators\L2_Heatmap\captures\NQM6"
COPY = r"C:\Users\j\AppData\Local\Temp\cap_copy"  # used while live writer holds lock
SESSION = "2026-05-05"
INNER_LEVELS = 10
BROAD_LEVELS = 30
ROLL_S = 30                   # rolling-window seconds for baselines
EVENT_Z = 2.5                 # |z-score| threshold for events
RTH_ONLY = True               # filter to NY 09:30-16:00 before any rolling math.
                              # ETH books are thinner & algo-dominated; including
                              # them contaminates rolling baselines and produces
                              # provider-σ-belief inferences from a fundamentally
                              # different participant mix.
RTH_START = (9, 30)
RTH_END   = (16, 0)
OUT_DIR = r"C:\Heatmap\research\out"

ny = ZoneInfo("America/New_York")

def load(name):
    for root in (LIVE, COPY):
        p = os.path.join(root, f"{name}-{SESSION}.parquet")
        if os.path.exists(p):
            try:
                return pl.read_parquet(p)
            except OSError:
                continue   # file locked, try next location
    raise FileNotFoundError(f"no readable {name}-{SESSION}.parquet")

def utc_to_ny(us): return dt.datetime.fromtimestamp(us / 1e6, tz=ny)
def ny_str(us): return utc_to_ny(us).strftime("%H:%M:%S")

def filter_rth(df):
    """Keep only rows whose NY-local time is within RTH (09:30-16:00 NY)."""
    if not RTH_ONLY: return df
    # Convert UTC timestamp to NY-local hour/minute, filter.
    return df.with_columns(
        pl.from_epoch(pl.col("timestamp_us"), time_unit="us")
          .dt.replace_time_zone("UTC")
          .dt.convert_time_zone("America/New_York")
          .alias("_ny")
    ).filter(
        ((pl.col("_ny").dt.hour() == RTH_START[0]) & (pl.col("_ny").dt.minute() >= RTH_START[1]))
        | ((pl.col("_ny").dt.hour() > RTH_START[0]) & (pl.col("_ny").dt.hour() < RTH_END[0]))
        | ((pl.col("_ny").dt.hour() == RTH_END[0]) & (pl.col("_ny").dt.minute() < RTH_END[1]))
    ).drop("_ny")

# ────────────────────────────────────────────────────────────────────────
# 1. Snapshots → depth metrics
# ────────────────────────────────────────────────────────────────────────
print("loading snapshots ...")
snap = load("snapshots")
n_raw = snap.height
snap = filter_rth(snap)
print(f"  {snap.height:,} rows  (filtered from {n_raw:,}; RTH={RTH_ONLY})")

bid_inner = [f"bid_size_{i}" for i in range(INNER_LEVELS)]
ask_inner = [f"ask_size_{i}" for i in range(INNER_LEVELS)]
bid_broad = [f"bid_size_{i}" for i in range(BROAD_LEVELS)]
ask_broad = [f"ask_size_{i}" for i in range(BROAD_LEVELS)]
bid_off   = [f"bid_offset_{i}" for i in range(BROAD_LEVELS)]
ask_off   = [f"ask_offset_{i}" for i in range(BROAD_LEVELS)]

# Side-aware metrics. The unified inner_depth / centroid_dist hide whether
# bid-side or ask-side is doing the work — see CLAUDE.md / loss-trade
# narrative 12:39-12:44 for why this disambiguation matters for level reads.
bid_dist_terms = [pl.col(o).abs() * pl.col(s) for o, s in zip(bid_off, bid_broad)]
ask_dist_terms = [pl.col(o).abs() * pl.col(s) for o, s in zip(ask_off, ask_broad)]

snap = snap.with_columns(
    pl.sum_horizontal(bid_inner).alias("bid_inner"),
    pl.sum_horizontal(ask_inner).alias("ask_inner"),
    pl.sum_horizontal(bid_broad).alias("bid_broad"),
    pl.sum_horizontal(ask_broad).alias("ask_broad"),
    pl.sum_horizontal(bid_dist_terms).alias("_b_wsum"),
    pl.sum_horizontal(ask_dist_terms).alias("_a_wsum"),
).with_columns(
    (pl.col("_b_wsum") / pl.col("bid_broad").clip(1)).alias("bid_centroid"),
    (pl.col("_a_wsum") / pl.col("ask_broad").clip(1)).alias("ask_centroid"),
    (pl.col("bid_inner") + pl.col("ask_inner")).alias("inner_depth"),  # kept for vod
).drop("_b_wsum", "_a_wsum")

snap = snap.with_columns(
    pl.from_epoch(pl.col("timestamp_us"), time_unit="us").alias("ts")
).sort("ts")

# Rolling stats per side metric. σ(ΔLiq) (vod) stays unified — it's the
# "providers thrashing" chaos signal regardless of which side is involved.
snap = snap.with_columns(
    pl.col("inner_depth").diff().alias("d_inner"),
).with_columns(
    pl.col("bid_inner").rolling_mean_by("ts", window_size=f"{ROLL_S}s").alias("bi_mean"),
    pl.col("bid_inner").rolling_std_by("ts", window_size=f"{ROLL_S}s").alias("bi_std"),
    pl.col("ask_inner").rolling_mean_by("ts", window_size=f"{ROLL_S}s").alias("ai_mean"),
    pl.col("ask_inner").rolling_std_by("ts", window_size=f"{ROLL_S}s").alias("ai_std"),
    pl.col("bid_centroid").rolling_mean_by("ts", window_size=f"{ROLL_S}s").alias("bc_mean"),
    pl.col("bid_centroid").rolling_std_by("ts", window_size=f"{ROLL_S}s").alias("bc_std"),
    pl.col("ask_centroid").rolling_mean_by("ts", window_size=f"{ROLL_S}s").alias("ac_mean"),
    pl.col("ask_centroid").rolling_std_by("ts", window_size=f"{ROLL_S}s").alias("ac_std"),
    pl.col("d_inner").rolling_std_by("ts", window_size=f"{ROLL_S}s").alias("vod"),
)
snap = snap.with_columns(
    ((pl.col("bid_inner")    - pl.col("bi_mean")) / pl.col("bi_std").clip(1.0)).alias("z_bi"),
    ((pl.col("ask_inner")    - pl.col("ai_mean")) / pl.col("ai_std").clip(1.0)).alias("z_ai"),
    ((pl.col("bid_centroid") - pl.col("bc_mean")) / pl.col("bc_std").clip(0.01)).alias("z_bc"),
    ((pl.col("ask_centroid") - pl.col("ac_mean")) / pl.col("ac_std").clip(0.01)).alias("z_ac"),
)
# vod z-score against its own longer baseline
snap = snap.with_columns(
    pl.col("vod").rolling_mean_by("ts", window_size=f"{ROLL_S * 4}s").alias("vod_mean"),
    pl.col("vod").rolling_std_by("ts", window_size=f"{ROLL_S * 4}s").alias("vod_std"),
).with_columns(
    ((pl.col("vod") - pl.col("vod_mean")) / pl.col("vod_std").clip(0.1)).alias("z_vod"),
)

# ────────────────────────────────────────────────────────────────────────
# 2. Ticks → mid-price-proxy returns → bipower realized vol
# ────────────────────────────────────────────────────────────────────────
print("loading ticks ...")
ticks = load("ticks")
n_raw = ticks.height
ticks = filter_rth(ticks)
print(f"  {ticks.height:,} rows  (filtered from {n_raw:,}; RTH={RTH_ONLY})")

# Use trade price as a mid proxy (we don't carry NBBO here). For NQ with tight
# spreads this is good enough for RV at 1-sec aggregation.
ticks = ticks.with_columns(
    pl.from_epoch(pl.col("timestamp_us"), time_unit="us").alias("ts")
).sort("ts")

# 1-sec bars: last price per second
bars1s = ticks.group_by_dynamic("ts", every="1s", closed="right").agg(
    pl.col("price").last().alias("close"),
    pl.col("size").sum().alias("vol"),
).filter(pl.col("close").is_not_null())
bars1s = bars1s.with_columns(
    pl.col("close").log().diff().alias("ret"),
).with_columns(
    pl.col("ret").abs().alias("absret"),
)
# Bipower variation: sum_{i} |r_i| * |r_{i-1}| * (π/2)
bars1s = bars1s.with_columns(
    (pl.col("absret") * pl.col("absret").shift(1) * (np.pi / 2)).alias("bp_term"),
)
# RV at each second: rolling sum of bp_term over ROLL_S seconds.
bars1s = bars1s.with_columns(
    pl.col("bp_term").rolling_sum_by("ts", window_size=f"{ROLL_S}s").alias("rv"),
)

# ────────────────────────────────────────────────────────────────────────
# 3. Detect events (sorted by absolute z-score)
# ────────────────────────────────────────────────────────────────────────
def detect(df, col, label_pos, label_neg=None):
    """Filter rows where |z| > threshold; tag by sign of z if both labels given."""
    base = df.filter(pl.col(col).abs() > EVENT_Z).select(
        pl.col("ts"),
        pl.col("timestamp_us"),
        pl.col("ref_tick"),
        pl.col("inner_depth"),
        pl.col(col).alias("z"),
    )
    if label_neg is None:
        return base.with_columns(pl.lit(label_pos).alias("event"))
    return base.with_columns(
        pl.when(pl.col("z") > 0).then(pl.lit(label_pos))
          .otherwise(pl.lit(label_neg)).alias("event")
    )

# Side-aware events. Directional bias map for downstream level_read:
#   BID_BUILD  bullish  (support stacking)
#   BID_PULL   bearish  (support evaporating)
#   ASK_BUILD  bearish  (resistance stacking)
#   ASK_PULL   bullish  (sellers retreating)
#   BID_IN     bullish  (bid mass leaning toward mid — committing closer)
#   BID_OUT    bearish  (bid mass retreating outward — defense thinning)
#   ASK_IN     bearish  (ask mass leaning toward mid — sellers committing closer)
#   ASK_OUT    bullish  (ask mass retreating — sellers backing off)
#   VOD_SPIKE  neutral  (chaos / repositioning regardless of side)
events = pl.concat([
    detect(snap, "z_bi",  "BID_BUILD", "BID_PULL"),
    detect(snap, "z_ai",  "ASK_BUILD", "ASK_PULL"),
    detect(snap, "z_bc",  "BID_OUT",   "BID_IN"),
    detect(snap, "z_ac",  "ASK_OUT",   "ASK_IN"),
    detect(snap, "z_vod", "VOL_OF_DEPTH_SPIKE"),
])

# Directional bias lookup, used by level_read aggregation.
EVENT_BIAS = {
    "BID_BUILD": +1, "BID_PULL": -1,
    "ASK_BUILD": -1, "ASK_PULL": +1,
    "BID_IN":    +1, "BID_OUT":  -1,
    "ASK_IN":    -1, "ASK_OUT":  +1,
    "VOL_OF_DEPTH_SPIKE": 0,
}

# Suppress duplicates within 5 sec at the same metric — we want event onsets,
# not every snapshot inside a sustained excursion.
events = events.sort("ts").with_columns(
    (pl.col("ts").diff().dt.total_seconds().over("event") < 5).fill_null(False).alias("_dup"),
).filter(~pl.col("_dup")).drop("_dup")

print(f"\n{events.height} event onsets detected")

# Bring in the price (ref_tick * 0.25) and current RV at event time
rv_lookup = bars1s.select(
    pl.col("ts").dt.truncate("1s").alias("ts_s"),
    pl.col("rv"),
)
events = events.with_columns(
    pl.col("ts").dt.truncate("1s").alias("ts_s"),
    (pl.col("ref_tick") * 0.25).alias("price"),
    pl.col("z").abs().alias("abs_z"),
).join(rv_lookup, on="ts_s", how="left").drop("ts_s")

# RV in NEXT 30s after event — does the event lead vol expansion?
events = events.with_columns(
    pl.col("ts").dt.offset_by(f"{ROLL_S}s").alias("ts_fut"),
)
rv_fut = bars1s.select(
    pl.col("ts").dt.truncate("1s").alias("ts_fut"),
    pl.col("rv").alias("rv_fut"),
)
events = events.with_columns(pl.col("ts_fut").dt.truncate("1s")).join(
    rv_fut, on="ts_fut", how="left"
).drop("ts_fut")

events = events.sort("abs_z", descending=True)
events_pretty = events.with_columns(
    pl.col("ts").dt.convert_time_zone("America/New_York").dt.strftime("%H:%M:%S").alias("ny"),
    pl.col("z").round(2),
    pl.col("price").round(2),
    pl.col("rv").round(7),
    pl.col("rv_fut").round(7),
).select("ny", "event", "z", "price", "inner_depth", "rv", "rv_fut")

# ────────────────────────────────────────────────────────────────────────
# 4. Cross-correlogram σ(ΔLiq) vs RV at lags
# ────────────────────────────────────────────────────────────────────────
# Resample both to a common 1-sec grid, drop NaNs, compute corr at lags.
snap_1s = snap.group_by_dynamic("ts", every="1s", closed="right").agg(
    pl.col("vod").last(),
).filter(pl.col("vod").is_not_null())
combined = snap_1s.join(
    bars1s.select("ts", "rv"), on="ts", how="inner"
).drop_nulls()

vod_arr = combined["vod"].to_numpy()
rv_arr  = combined["rv"].to_numpy()
def corr_at(k):
    if k > 0:
        a, b = vod_arr[:-k], rv_arr[k:]
    elif k < 0:
        a, b = vod_arr[-k:], rv_arr[:k]
    else:
        a, b = vod_arr, rv_arr
    mask = np.isfinite(a) & np.isfinite(b)
    if mask.sum() < 100: return float("nan")
    return float(np.corrcoef(a[mask], b[mask])[0, 1])

lags = [-60, -30, -15, -5, 0, 5, 15, 30, 60]
correlogram = {k: corr_at(k) for k in lags}

# ────────────────────────────────────────────────────────────────────────
# 5. Output
# ────────────────────────────────────────────────────────────────────────
os.makedirs(OUT_DIR, exist_ok=True)
out_csv = os.path.join(OUT_DIR, f"liq_events_{SESSION}.csv")
events_pretty.write_csv(out_csv)
print(f"\nevents written to {out_csv}")

print(f"\n=== Event count by type ===")
counts = events.group_by("event").agg(pl.len().alias("n")).sort("n", descending=True)
for r in counts.iter_rows(named=True):
    print(f"  {r['event']:<22} {r['n']:>4}")

print(f"\n=== Top 20 events by |z| ===")
print(f"{'time':<10} {'event':<22} {'z':>7} {'price':>10} {'inner':>7} {'rv':>10} {'rv+30s':>10}  {'Δrv':>6}")
for r in events_pretty.head(20).iter_rows(named=True):
    rv = float(r["rv"]) if r["rv"] is not None else float("nan")
    rvf = float(r["rv_fut"]) if r["rv_fut"] is not None else float("nan")
    # Show rv × 1e8 (log-return² × 1e8 ≈ "vol intensity" units; relative magnitude is what matters)
    rv_s = f"{rv*1e8:>10.1f}" if np.isfinite(rv) else "        --"
    rvf_s = f"{rvf*1e8:>10.1f}" if np.isfinite(rvf) else "        --"
    delta = (rvf/rv if (np.isfinite(rv) and rv > 0 and np.isfinite(rvf)) else float("nan"))
    delta_s = f"{delta:>5.1f}x" if np.isfinite(delta) else "    --"
    print(f"{r['ny']:<10} {r['event']:<22} {r['z']:>+7.2f} {r['price']:>10.2f} "
          f"{r['inner_depth']:>7.0f} {rv_s} {rvf_s}  {delta_s}")

print(f"\n=== Cross-correlogram σ(ΔLiq) vs RV(t+k) ===")
print("(negative k = liquidity leads vol; positive k = vol leads liquidity)")
print(f"{'lag (s)':<10} {'corr':>8}")
for k in lags:
    bar = "#" * int(abs(correlogram[k]) * 40) if not np.isnan(correlogram[k]) else ""
    sign = "+" if correlogram[k] > 0 else "-" if correlogram[k] < 0 else " "
    print(f"{k:>+5} s     {correlogram[k]:+.4f}  {sign}{bar}")

peak = max(lags, key=lambda k: abs(correlogram[k]) if not np.isnan(correlogram[k]) else 0)
print(f"\npeak |corr| at lag {peak:+d}s: {correlogram[peak]:+.4f}")
print("(reminder: 1 day of data — this peak is not informative on its own)")

# ────────────────────────────────────────────────────────────────────────
# 6. After-session level_read helper.
#    Given (price, time, lookback, band), print the side-aware events that
#    fired in that price band over the lookback window, plus a recency-and-
#    magnitude-weighted bias breakdown by side. NOT a signal. NOT a verdict.
#    A *codified read* of what providers were doing at the level the trader
#    was contemplating clicking.
#
#    Design fixture validated against:
#      - Win trade 2026-05-05 (10:14 vs 10:19 at 28050-28054)
#      - Loss trade 2026-05-05 (12:30-12:45 at 28100-28107)
#    Both should read clean with side-aware events.
# ────────────────────────────────────────────────────────────────────────

def _parse_hhmm(s):
    parts = s.split(":")
    h = int(parts[0]); m = int(parts[1])
    sec = int(parts[2]) if len(parts) > 2 else 0
    return h * 3600 + m * 60 + sec

def level_read(price, target_hhmmss, lookback_min=3, band_ticks=5,
               include_neutral_vod=True):
    """Print side-aware events at price ± band_ticks ticks within ±lookback.

    Returns a Polars DataFrame of the events shown, sorted by time.
    Aggregation: each event contributes |z| × (1 - age/window) × bias to a
    side-bucketed running total. Bias is +1 for bullish, -1 for bearish, 0
    for neutral. Bullish/bearish are bucketed separately so the trader sees
    *both forces* at the level, not just the net.
    """
    target_sec = _parse_hhmm(target_hhmmss)
    lo_sec = target_sec - lookback_min * 60
    hi_sec = target_sec + 1   # inclusive of target
    band = band_ticks * 0.25
    p_lo = price - band
    p_hi = price + band

    def in_window_and_band(row):
        sec = _parse_hhmm(row["ny"])
        return lo_sec <= sec <= hi_sec and p_lo <= row["price"] <= p_hi

    sub = events_pretty.filter(
        pl.struct(["ny", "price"]).map_elements(
            lambda r: in_window_and_band(r), return_dtype=pl.Boolean
        )
    ).sort("ny")

    if not include_neutral_vod:
        sub = sub.filter(pl.col("event") != "VOL_OF_DEPTH_SPIKE")

    print(f"\n=== LEVEL READ — {price:.2f} ± {band_ticks}t @ {target_hhmmss} "
          f"(lookback {lookback_min}min) ===")
    if sub.height == 0:
        print("  (no events in window)")
        return sub

    print(f"  {'time':<10} {'event':<22} {'z':>7} {'price':>9} bias")
    for r in sub.iter_rows(named=True):
        bias = EVENT_BIAS.get(r["event"], 0)
        bias_s = "+bull" if bias > 0 else ("-bear" if bias < 0 else " neut")
        print(f"  {r['ny']:<10} {r['event']:<22} {r['z']:>+7.2f} {r['price']:>9.2f} {bias_s}")

    # Recency × magnitude weighted by-side aggregation
    bull_acc = 0.0; bear_acc = 0.0; neut_acc = 0.0
    bull_n = 0; bear_n = 0; neut_n = 0
    for r in sub.iter_rows(named=True):
        sec = _parse_hhmm(r["ny"])
        age_sec = max(0, target_sec - sec)
        recency = max(0.0, 1.0 - age_sec / (lookback_min * 60))
        weight = abs(r["z"]) * recency
        bias = EVENT_BIAS.get(r["event"], 0)
        if bias > 0:   bull_acc += weight; bull_n += 1
        elif bias < 0: bear_acc += weight; bear_n += 1
        else:          neut_acc += weight; neut_n += 1

    print(f"\n  bullish actions  (BID_BUILD/BID_IN/ASK_PULL/ASK_OUT) : "
          f"{bull_n:>2} events,  weight {bull_acc:>5.1f}")
    print(f"  bearish actions  (BID_PULL/BID_OUT/ASK_BUILD/ASK_IN) : "
          f"{bear_n:>2} events,  weight {bear_acc:>5.1f}")
    if neut_n:
        print(f"  neutral (VOD chaos)                                 : "
              f"{neut_n:>2} events,  weight {neut_acc:>5.1f}")
    net = bull_acc - bear_acc
    print(f"  net (bull - bear): {net:+.1f}    "
          f"({'BULL-leaning' if net > 1 else 'BEAR-leaning' if net < -1 else 'CONTESTED'})")
    return sub

# Skip explicit demo runs by default; uncomment to run automatically.
# Or load this script at REPL: `python -i liq_events.py` then call:
#   level_read(28054, "10:14:30")    # win trade — should be bear-leaning
#   level_read(28050.75, "10:19:30") # win trade — should be bull-leaning
#   level_read(28102, "12:43:00", lookback_min=5)  # loss trade
import sys as _sys
_sys.exit(0)
