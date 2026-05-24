"""L2_Surface effectiveness simulator.

Replays one session of captured snapshots+ticks through the same per-layer
trigger logic the live SurfaceEngine implements, then prints what each
layer would have surfaced. Matches SurfaceEngine.cs defaults; thresholds
overridable via env vars (kept minimal — same posture as `liq_events.py`).

Output (per session): for each of the four layers
  Inflection / Climax / Build Bands / Flow Band
print
  - count of fires
  - time + price + bias (where applicable)
  - persistence: still active at session end vs cleared on price-through
  - rough behavioral note (e.g. "all bull" / "5 cleared by midday")

Use:
  SESSION=2026-05-08 SYMBOL_DIR=NQ python surface_walk.py

Why retro simulation matters: the live indicator just shipped 2026-05-08;
we need a population view of how often each layer fires per session,
across regime types, to know if any layer is mis-calibrated for the
NQ-RTH order-flow distribution. The engine math is portable — captures
were always written by L2_Heatmap independently of L2_Surface.

Single forward pass through the time-ordered z-scored sample stream.
Same bias map, same z-thresholds, same proximity/cooldown rules as
SurfaceEngine.cs. Where defaults differ from research/liq_events.py
(EVENT_Z=2.5 there, =3.0 here), this script uses the engine value so
the simulation matches what the indicator paints.
"""
import polars as pl
import numpy as np
import datetime as dt
import os, sys
from zoneinfo import ZoneInfo
from capture_loader import load_capture_day, snapshot_columns, tick_columns
try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

SESSION    = os.environ.get("SESSION", "2026-05-08")
SYMBOL_DIR = os.environ.get("SYMBOL_DIR", "NQ")

OUT_DIR = r"C:\Heatmap\research\out"
os.makedirs(OUT_DIR, exist_ok=True)

# ── Engine defaults (mirror SurfaceEngine.cs) ────────────────────────────
INNER_LEVELS = 10
BROAD_LEVELS = 30
LOOKBACK_S   = 30
EVENT_Z      = 3.0          # SurfaceEngine.EventZThreshold
TRIGGER_BUILD_Z = 4.0        # SurfaceEngine.TriggerBuildZ
CUM_THRESHOLD   = 7.0
ROC_THRESHOLD   = 5.0
CONFIRM_WIN_S   = 60
ROC_WIN_S       = 60
CUM_WIN_S       = 300
CLIMAX_VOD_Z    = 5.0
CLIMAX_BUILD_Z  = 4.0
CLIMAX_DEDUP_S  = 30
BAND_WIN_S      = 30
BAND_EVENT_N    = 5
BAND_RV_THRESH  = 1e-7
BAND_INNER_THIN_Z = 1.0
BAND_SUSTAIN_S  = 10
BAND_COOLDOWN_S = 30
BUILD_CLUSTER_N      = 3
BUILD_CLUSTER_TICKS  = 8
BUILD_CLUSTER_SEC    = 90
PRICE_THROUGH_BUFFER_TICKS = 4    # "Render: PriceThroughBufferTicks" default in L2_Surface.cs
TICK_SIZE = 0.25

RTH_START = (9, 30)
RTH_END   = (16, 0)
ny = ZoneInfo("America/New_York")

# ── Load + RTH filter ────────────────────────────────────────────────────
def load(name):
    cols = snapshot_columns(BROAD_LEVELS) if name == "snapshots" else tick_columns()
    return load_capture_day(name, SYMBOL_DIR, SESSION, cols)

def filter_rth(df):
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

print(f"surface_walk: SESSION={SESSION}  SYMBOL_DIR={SYMBOL_DIR}")
snap = filter_rth(load("snapshots")).sort("timestamp_us")
ticks = filter_rth(load("ticks")).sort("timestamp_us")
print(f"  {snap.height:,} snapshot rows / {ticks.height:,} ticks (RTH)")

# ── Per-sample metrics + z-scores (mirrors engine ComputeSample + MeanStd) ─
bid_inner = [f"bid_size_{i}" for i in range(INNER_LEVELS)]
ask_inner = [f"ask_size_{i}" for i in range(INNER_LEVELS)]
bid_broad = [f"bid_size_{i}" for i in range(BROAD_LEVELS)]
ask_broad = [f"ask_size_{i}" for i in range(BROAD_LEVELS)]
bid_off   = [f"bid_offset_{i}" for i in range(BROAD_LEVELS)]
ask_off   = [f"ask_offset_{i}" for i in range(BROAD_LEVELS)]

snap = snap.with_columns(
    pl.sum_horizontal(bid_inner).alias("bid_inner"),
    pl.sum_horizontal(ask_inner).alias("ask_inner"),
    pl.sum_horizontal(bid_broad).alias("bid_broad"),
    pl.sum_horizontal(ask_broad).alias("ask_broad"),
    pl.sum_horizontal([pl.col(o).abs() * pl.col(s) for o, s in zip(bid_off, bid_broad)]).alias("_bw"),
    pl.sum_horizontal([pl.col(o).abs() * pl.col(s) for o, s in zip(ask_off, ask_broad)]).alias("_aw"),
).with_columns(
    (pl.col("_bw") / pl.col("bid_broad").clip(1)).alias("bid_centroid"),
    (pl.col("_aw") / pl.col("ask_broad").clip(1)).alias("ask_centroid"),
    (pl.col("bid_inner") + pl.col("ask_inner")).alias("inner_total"),
    pl.from_epoch(pl.col("timestamp_us"), time_unit="us")
      .dt.replace_time_zone("UTC").alias("ts"),
).drop("_bw", "_aw")

# Rolling baselines (matches engine LookbackSec=30s)
snap = snap.with_columns(
    pl.col("bid_inner").rolling_mean_by("ts", window_size=f"{LOOKBACK_S}s").alias("bi_mean"),
    pl.col("bid_inner").rolling_std_by("ts",  window_size=f"{LOOKBACK_S}s").alias("bi_std"),
    pl.col("ask_inner").rolling_mean_by("ts", window_size=f"{LOOKBACK_S}s").alias("ai_mean"),
    pl.col("ask_inner").rolling_std_by("ts",  window_size=f"{LOOKBACK_S}s").alias("ai_std"),
    pl.col("bid_centroid").rolling_mean_by("ts", window_size=f"{LOOKBACK_S}s").alias("bc_mean"),
    pl.col("bid_centroid").rolling_std_by("ts",  window_size=f"{LOOKBACK_S}s").alias("bc_std"),
    pl.col("ask_centroid").rolling_mean_by("ts", window_size=f"{LOOKBACK_S}s").alias("ac_mean"),
    pl.col("ask_centroid").rolling_std_by("ts",  window_size=f"{LOOKBACK_S}s").alias("ac_std"),
    pl.col("inner_total").rolling_mean_by("ts", window_size=f"{LOOKBACK_S}s").alias("it_mean"),
    pl.col("inner_total").rolling_std_by("ts",  window_size=f"{LOOKBACK_S}s").alias("it_std"),
    pl.col("inner_total").diff().alias("d_inner"),
)
# vod = rolling stdev of d/dt(inner_total); z_vod = vod against its 4× baseline
snap = snap.with_columns(
    pl.col("d_inner").rolling_std_by("ts", window_size=f"{LOOKBACK_S}s").alias("vod"),
).with_columns(
    pl.col("vod").rolling_mean_by("ts", window_size=f"{LOOKBACK_S * 4}s").alias("vod_mean"),
    pl.col("vod").rolling_std_by("ts",  window_size=f"{LOOKBACK_S * 4}s").alias("vod_std"),
).with_columns(
    ((pl.col("bid_inner")    - pl.col("bi_mean")) / pl.col("bi_std").clip(1.0)).alias("z_bi"),
    ((pl.col("ask_inner")    - pl.col("ai_mean")) / pl.col("ai_std").clip(1.0)).alias("z_ai"),
    ((pl.col("bid_centroid") - pl.col("bc_mean")) / pl.col("bc_std").clip(0.01)).alias("z_bc"),
    ((pl.col("ask_centroid") - pl.col("ac_mean")) / pl.col("ac_std").clip(0.01)).alias("z_ac"),
    ((pl.col("vod")          - pl.col("vod_mean")) / pl.col("vod_std").clip(0.1)).alias("z_vod"),
    ((pl.col("inner_total")  - pl.col("it_mean")) / pl.col("it_std").clip(1.0)).alias("z_it"),
)

# RV from ticks (1-sec bars, rolling sum of squared log returns over BAND_WIN_S)
ticks = ticks.with_columns(
    pl.from_epoch(pl.col("timestamp_us"), time_unit="us")
      .dt.replace_time_zone("UTC").alias("ts")
)
bars1s = ticks.group_by_dynamic("ts", every="1s", closed="right").agg(
    pl.col("price").last().alias("close"),
).filter(pl.col("close").is_not_null()).with_columns(
    pl.col("close").log().diff().alias("ret"),
).with_columns(
    (pl.col("ret") ** 2).alias("ret2"),
).with_columns(
    pl.col("ret2").rolling_sum_by("ts", window_size=f"{BAND_WIN_S}s").alias("rv"),
)
# Join RV onto snapshot stream (last-value-as-of-sample)
rv_join = bars1s.select(pl.col("ts").alias("rv_ts"), pl.col("rv"))
snap = snap.join_asof(rv_join, left_on="ts", right_on="rv_ts", strategy="backward").drop("rv_ts")

# ── Forward-pass simulation ─────────────────────────────────────────────
# Bias map (matches engine):
#   z_bi: + → BID_BUILD (+1), − → BID_PULL (−1)
#   z_ai: + → ASK_BUILD (−1), − → ASK_PULL (+1)
#   z_bc: + → BID_OUT (−1),   − → BID_IN  (+1)
#   z_ac: + → ASK_OUT (+1),   − → ASK_IN  (−1)
#   z_vod| > thr → VOD (0)

class Event:
    __slots__ = ("ts","type","bias","absz","tick","mid")
    def __init__(self, ts, type, bias, absz, tick):
        self.ts=ts; self.type=type; self.bias=bias; self.absz=absz; self.tick=tick

class Inflection:
    __slots__ = ("trigger_ts","confirm_ts","tick","bias","cleared_ts")
    def __init__(self, trigger_ts, confirm_ts, tick, bias):
        self.trigger_ts=trigger_ts; self.confirm_ts=confirm_ts; self.tick=tick
        self.bias=bias; self.cleared_ts=None

class Climax:
    __slots__ = ("ts","tick","vod_z","build_z","cleared_ts")
    def __init__(self, ts, tick, vod_z, build_z):
        self.ts=ts; self.tick=tick; self.vod_z=vod_z; self.build_z=build_z; self.cleared_ts=None

class BuildBand:
    __slots__ = ("side","min_tick","max_tick","start_ts","last_ts","n","cleared_ts")
    def __init__(self, side, min_tick, max_tick, start_ts, last_ts, n):
        self.side=side; self.min_tick=min_tick; self.max_tick=max_tick
        self.start_ts=start_ts; self.last_ts=last_ts; self.n=n; self.cleared_ts=None

class FlowBand:
    __slots__ = ("dir","start_ts","end_ts")
    def __init__(self, d, s, e): self.dir=d; self.start_ts=s; self.end_ts=e

events = []           # all emitted events (forward order)
inflections = []
climaxes = []
buildbands = []
flowbands = []
pending = []          # PendingTrigger list
build_pending = []    # recent BUILDs not yet in a band

# Flow state machine
flow_state = "NONE"   # NONE / BEAR / BULL
match_start = None
last_match_ts = None
open_band = None

def fire(ts, z_col, bias_pos, label_pos, label_neg, tick, this_sample):
    if z_col is None or np.isnan(z_col): return
    if abs(z_col) <= EVENT_Z: return
    if z_col > 0: bias = bias_pos; label = label_pos
    else:        bias = -bias_pos; label = label_neg
    e = Event(ts, label, bias, abs(z_col), tick)
    events.append(e); this_sample.append(e)

# Pre-extract sample arrays for speed
ts_arr = snap["ts"].to_list()
mid_arr = snap["ref_tick"].to_list() if "ref_tick" in snap.columns else None
zbi = snap["z_bi"].to_numpy(); zai = snap["z_ai"].to_numpy()
zbc = snap["z_bc"].to_numpy(); zac = snap["z_ac"].to_numpy()
zvod = snap["z_vod"].to_numpy(); zit = snap["z_it"].to_numpy()
rv_arr = snap["rv"].to_numpy() if "rv" in snap.columns else np.zeros(len(ts_arr))

def cum_over(now, sec):
    cutoff = now - dt.timedelta(seconds=sec)
    s = 0.0
    for ev in reversed(events):
        if ev.ts < cutoff: break
        s += ev.bias * ev.absz
    return s

def bear_bull_count(now, sec):
    cutoff = now - dt.timedelta(seconds=sec)
    bear = bull = 0
    for ev in reversed(events):
        if ev.ts < cutoff: break
        if ev.absz < EVENT_Z: continue
        if ev.bias < 0: bear += 1
        elif ev.bias > 0: bull += 1
    return bear, bull

last_unmatch_ts = None

print("running forward pass ...")
for i in range(len(ts_arr)):
    now = ts_arr[i]
    tick = mid_arr[i]
    this_sample = []

    # Fire side-aware events (require finite z & populated baseline)
    fire(now, zbi[i], +1, "BID_BUILD", "BID_PULL", tick, this_sample)
    fire(now, zai[i], -1, "ASK_BUILD", "ASK_PULL", tick, this_sample)
    fire(now, zbc[i], -1, "BID_OUT",   "BID_IN",   tick, this_sample)
    fire(now, zac[i], +1, "ASK_OUT",   "ASK_IN",   tick, this_sample)
    if not np.isnan(zvod[i]) and abs(zvod[i]) > EVENT_Z:
        e = Event(now, "VOD", 0, abs(zvod[i]), tick); events.append(e); this_sample.append(e)

    # Cum/ROC running totals
    cum5m = cum_over(now, CUM_WIN_S)
    roc60 = cum_over(now, ROC_WIN_S)

    # ── Inflection: register pending from BUILD ≥ TriggerBuildZ
    for ev in this_sample:
        if ev.absz < TRIGGER_BUILD_Z: continue
        if ev.type not in ("BID_BUILD", "ASK_BUILD"): continue
        pending.append({"ts": now, "tick": tick, "bias": ev.bias,
                        "cum_base": cum5m - ev.bias * ev.absz})
    # Walk pending; promote / drop
    new_pending = []
    for t in pending:
        age = (now - t["ts"]).total_seconds()
        if age > CONFIRM_WIN_S: continue
        d_cum = cum5m - t["cum_base"]
        cum_ok = (t["bias"] > 0 and d_cum >=  CUM_THRESHOLD) or (t["bias"] < 0 and d_cum <= -CUM_THRESHOLD)
        roc_ok = (t["bias"] > 0 and roc60 >=  ROC_THRESHOLD) or (t["bias"] < 0 and roc60 <= -ROC_THRESHOLD)
        if cum_ok and roc_ok:
            inflections.append(Inflection(t["ts"], now, t["tick"], t["bias"]))
        else:
            new_pending.append(t)
    pending = new_pending

    # ── Climax: VOD ≥ ClimaxVodZ AND BUILD ≥ ClimaxBuildZ same sample, same tick
    has_vod = False; vod_z = 0
    has_build = False; build_z = 0
    for ev in this_sample:
        if ev.type == "VOD" and ev.absz >= CLIMAX_VOD_Z:
            has_vod = True; vod_z = ev.absz
        if ev.type in ("BID_BUILD", "ASK_BUILD") and ev.absz >= CLIMAX_BUILD_Z:
            if ev.absz > build_z: has_build = True; build_z = ev.absz
    if has_vod and has_build:
        dup = any(c.tick == tick and (now - c.ts).total_seconds() < CLIMAX_DEDUP_S for c in climaxes)
        if not dup: climaxes.append(Climax(now, tick, vod_z, build_z))

    # ── Build bands
    # Evict pending BUILDs older than cluster window
    build_pending = [p for p in build_pending if (now - p.ts).total_seconds() <= BUILD_CLUSTER_SEC]
    for ev in this_sample:
        if ev.type not in ("BID_BUILD", "ASK_BUILD"): continue
        side = "supply" if ev.type == "ASK_BUILD" else "demand"
        # Try extend
        extended = False
        for bb in buildbands:
            if bb.cleared_ts is not None: continue
            if bb.side != side: continue
            if (ev.ts - bb.last_ts).total_seconds() > BUILD_CLUSTER_SEC: continue
            lo = bb.min_tick - BUILD_CLUSTER_TICKS
            hi = bb.max_tick + BUILD_CLUSTER_TICKS
            if lo <= ev.tick <= hi:
                bb.min_tick = min(bb.min_tick, ev.tick)
                bb.max_tick = max(bb.max_tick, ev.tick)
                bb.last_ts = ev.ts
                bb.n += 1
                extended = True
                break
        if extended: continue
        # Cluster from pending
        members = [ev]
        for p in build_pending:
            if side == "supply" and p.type != "ASK_BUILD": continue
            if side == "demand" and p.type != "BID_BUILD": continue
            if abs(p.tick - ev.tick) > BUILD_CLUSTER_TICKS: continue
            if (ev.ts - p.ts).total_seconds() > BUILD_CLUSTER_SEC: continue
            members.append(p)
        if len(members) >= BUILD_CLUSTER_N:
            buildbands.append(BuildBand(
                side,
                min(m.tick for m in members),
                max(m.tick for m in members),
                min(m.ts for m in members),
                max(m.ts for m in members),
                len(members),
            ))
            build_pending = [p for p in build_pending if p not in members]
        else:
            build_pending.append(ev)

    # ── Price-through clearing (apply each sample)
    buf = PRICE_THROUGH_BUFFER_TICKS
    for inf in inflections:
        if inf.cleared_ts is not None: continue
        if inf.bias < 0 and tick > inf.tick + buf:  inf.cleared_ts = now
        elif inf.bias > 0 and tick < inf.tick - buf: inf.cleared_ts = now
    for cl in climaxes:
        if cl.cleared_ts is not None: continue
        if abs(tick - cl.tick) > buf: cl.cleared_ts = now
    for bb in buildbands:
        if bb.cleared_ts is not None: continue
        if bb.side == "supply" and tick > bb.max_tick + buf:  bb.cleared_ts = now
        elif bb.side == "demand" and tick < bb.min_tick - buf: bb.cleared_ts = now

    # ── Flow band state machine
    bear_n, bull_n = bear_bull_count(now, BAND_WIN_S)
    rv = rv_arr[i] if not np.isnan(rv_arr[i]) else 0.0
    thin_z = zit[i] if not np.isnan(zit[i]) else 0.0
    bear_match = bear_n >= BAND_EVENT_N and rv >= BAND_RV_THRESH and thin_z <= -BAND_INNER_THIN_Z
    bull_match = bull_n >= BAND_EVENT_N and rv >= BAND_RV_THRESH and thin_z <= -BAND_INNER_THIN_Z
    if bear_match and bull_match:
        if bear_n >= bull_n: bull_match = False
        else: bear_match = False
    match = "BEAR" if bear_match else ("BULL" if bull_match else "NONE")

    if flow_state == "NONE":
        if match != "NONE":
            if match_start is None: match_start = now
            last_match_ts = now
            if (now - match_start).total_seconds() >= BAND_SUSTAIN_S:
                flow_state = match
                open_band = FlowBand(match, match_start, now)
                flowbands.append(open_band)
        else:
            match_start = None
    else:
        if match == flow_state:
            last_match_ts = now
            if open_band is not None: open_band.end_ts = now
            last_unmatch_ts = None
        else:
            if last_unmatch_ts is None: last_unmatch_ts = now
            if (now - last_match_ts).total_seconds() >= BAND_COOLDOWN_S:
                if open_band is not None: open_band.end_ts = last_match_ts
                open_band = None
                flow_state = "NONE"
                match_start = None
                last_unmatch_ts = None

print("done.")

# ── Reporting ───────────────────────────────────────────────────────────
def hms(t): return t.astimezone(ny).strftime("%H:%M:%S")
def px(tick): return tick * TICK_SIZE

session_end = ts_arr[-1] if ts_arr else None

print(f"\n{'='*68}\nL2_Surface effectiveness — {SESSION}\n{'='*68}")

# 1. Inflection
print(f"\n--- INFLECTION layer ---  ({len(inflections)} confirmed)")
n_active = sum(1 for x in inflections if x.cleared_ts is None)
n_bull = sum(1 for x in inflections if x.bias > 0)
n_bear = sum(1 for x in inflections if x.bias < 0)
print(f"  bull: {n_bull}    bear: {n_bear}    still active at session end: {n_active}")
if inflections:
    print(f"  {'trig':<10} {'conf':<10} {'price':>10} {'bias':>5} {'lifetime':>10}")
    for x in inflections:
        bias_s = "BULL" if x.bias > 0 else "BEAR"
        if x.cleared_ts is None:
            life_s = "ACTIVE"
        else:
            life_s = f"{(x.cleared_ts - x.confirm_ts).total_seconds()/60:>7.1f}min"
        print(f"  {hms(x.trigger_ts):<10} {hms(x.confirm_ts):<10} "
              f"{px(x.tick):>10.2f} {bias_s:>5} {life_s:>10}")

# 2. Climax
print(f"\n--- CLIMAX lines ---  ({len(climaxes)} fires)")
n_active = sum(1 for x in climaxes if x.cleared_ts is None)
print(f"  still active at session end: {n_active}")
if climaxes:
    print(f"  {'time':<10} {'price':>10} {'vod_z':>7} {'build_z':>8} {'lifetime':>10}")
    for x in climaxes:
        if x.cleared_ts is None: life = "ACTIVE"
        else: life = f"{(x.cleared_ts - x.ts).total_seconds()/60:>7.1f}min"
        print(f"  {hms(x.ts):<10} {px(x.tick):>10.2f} {x.vod_z:>7.2f} "
              f"{x.build_z:>8.2f} {life:>10}")

# 3. Build Bands
print(f"\n--- BUILD BANDS ---  ({len(buildbands)} bands formed)")
n_supply = sum(1 for b in buildbands if b.side == "supply")
n_demand = sum(1 for b in buildbands if b.side == "demand")
n_active = sum(1 for b in buildbands if b.cleared_ts is None)
print(f"  supply: {n_supply}    demand: {n_demand}    "
      f"still active at session end: {n_active}")
if buildbands:
    print(f"  {'side':<7} {'start':<10} {'min':>9} {'max':>9} {'n':>3} {'lifetime':>10}")
    for b in buildbands:
        if b.cleared_ts is None: life = "ACTIVE"
        else: life = f"{(b.cleared_ts - b.start_ts).total_seconds()/60:>7.1f}min"
        print(f"  {b.side:<7} {hms(b.start_ts):<10} {px(b.min_tick):>9.2f} "
              f"{px(b.max_tick):>9.2f} {b.n:>3} {life:>10}")

# 4. Flow Band
print(f"\n--- FLOW BAND ---  ({len(flowbands)} bands opened)")
total_band_sec = sum((b.end_ts - b.start_ts).total_seconds() for b in flowbands)
print(f"  total time inside flow band: {total_band_sec/60:.1f} min "
      f"({total_band_sec/(6.5*60):.1f}% of RTH)")
if flowbands:
    print(f"  {'dir':<5} {'start':<10} {'end':<10} {'duration':>9}")
    for b in flowbands:
        dur_s = (b.end_ts - b.start_ts).total_seconds()
        print(f"  {b.dir:<5} {hms(b.start_ts):<10} {hms(b.end_ts):<10} {dur_s:>6.0f}s")

# Events density summary
print(f"\n--- EVENTS LAYER ---  ({len(events)} dots painted)")
by_type = {}
for ev in events:
    by_type[ev.type] = by_type.get(ev.type, 0) + 1
for t in sorted(by_type, key=lambda k: -by_type[k]):
    print(f"  {t:<22} {by_type[t]:>5}")

# Session summary
print(f"\n--- SUMMARY ---")
print(f"  session: {SESSION}  ({snap.height:,} snapshots, {ticks.height:,} RTH ticks)")
print(f"  Events fires: {len(events)}")
print(f"  Inflection confirmations: {len(inflections)} "
      f"({n_bull} bull / {n_bear} bear)")
print(f"  Climax lines: {len(climaxes)}")
print(f"  Build Bands: {len(buildbands)} ({n_supply} supply / {n_demand} demand)")
print(f"  Flow Band time: {total_band_sec/60:.1f} min")
