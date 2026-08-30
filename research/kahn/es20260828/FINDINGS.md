# ES 2026-08-28 PM short — scale-in and harvest study

Provenance: Claude-authored exploratory research. This is evidence for review,
not accepted Kahn policy or live execution permission.

Campaign as declared: **short the 7780 region, issued after 11:20 ET, harvest
target 7740, invalidated by extension above 7782.**

Status: in-sample construction on one trade. Nothing here is validated. The
ladder-depth parameter in particular is fitted to this session and is the thing
a holdout has to test.

## 0. Data corrections found while building this

Two defects had to be fixed before any number below could be trusted. Both
affect other work in this repo, not just this study.

### Clock domains: book events and ticks are ~895 ms apart

`book_events.receipt_timestamp_us` runs a median **895 ms behind**
`exchange_timestamp_us` (p05 824 ms, p95 924 ms). The tick tape's
`timestamp_us` is on exchange time.

Joining book events to trades on receipt time misaligns them by nearly a
second. Measured attribution of traded volume to a matching order removal:

| join key | bucket | traded volume attributed |
| --- | --- | --- |
| `receipt_timestamp_us` | 100 ms | 0.20 |
| `receipt_timestamp_us` | 500 ms | 0.50 |
| `exchange_timestamp_us` | 5 ms | **0.993** |

At 5 ms buckets on exchange time, with zero residual lag, **99.3%** of traded
volume attributes to a specific size removal at the same price and side. Fill
versus cancel is therefore cleanly separable. On receipt time it is not.

Anything in this repo that joins `book_events` to `ticks` should be rechecked
for this.

### Queue depth cannot be reconstructed from the event stream

About 1.5% of quotes never emit a close row, so a running open-minus-close
reconstruction accumulates phantom size without bound. At ESU6 7777.00 on
11:21:00 the replay reported **186 lots** resting where the 1 Hz snapshot
showed **59**. Over a 75-minute replay, 97 of 98 "resting" quotes at that level
never resolved.

Queue depth must come from the `snapshots` parquet. The event stream is correct
for *flow* (adds, fills, pulls) and wrong for *stock* (resting depth).

## 1. What the L2 layer does and does not do

A predictive test over 8/28 RTH (819 buckets of 30 s, mid-relative book
features within 20 ticks) found **nothing**:

| signal | corr with fwd 60 s | R² alone | ΔR² over delta |
| --- | --- | --- | --- |
| aggressor delta (baseline) | −0.036 | 0.0013 | — |
| add imbalance | −0.020 | 0.0004 | +0.0000 |
| resting-add imbalance | −0.058 | 0.0034 | +0.0021 |
| pull imbalance | +0.032 | 0.0010 | +0.0006 |
| fill imbalance | +0.007 | 0.0001 | +0.0021 |

Same picture at 180 s and 300 s. Aggressor delta does not predict either.

**Conclusion: none of this is an entry signal, and it should not be wired into
one.** Its job is to answer sizing and fill-feasibility questions *given* a
directional thesis the trader supplies. That is consistent with Kahn's existing
"evidence is not permission" posture.

There was also **no large resting seller** at 7777–7782 during the entry
window. Across 16 minutes and 9 points, the largest durable quote (≥10 lots,
≥3 s) was 25 lots; total durable size was 423 lots against 32,511 traded;
mean resting lot size ~1.6 contracts. The level did not hold because of visible
book size. It held on failed-buy effort and on the GEX call wall.

## 2. GEX read (ES_SPX `gex_zero`, cache is 1/min)

| time | spot | zero_gamma | call_wall | put_wall | sum_gex_vol |
| --- | --- | --- | --- | --- | --- |
| 11:31 | 7776.4 | 7751.8 | **7781.3** | 7731.3 | +262,425 |
| 11:44 | 7758.5 | 7754.7 | 7781.3 | 7731.3 | +60,426 |
| 11:48 | 7752.9 | 7756.2 | 7781.2 | 7731.2 | +2,014 |
| 11:56 | 7740.6 | 7755.7 | 7761.3 | 7731.2 | −110,609 |
| 12:17 | 7733.5 | 7753.3 | 7760.8 | 7730.8 | −175,575 |

Three things fall out:

1. **The declared 7782 invalidation is the call wall (7781.3).** The user's
   level and the GEX level agree to within a point, independently derived.
2. **The regime flipped mid-campaign.** Price above `zero_gamma` (~7752) is
   positive gamma — dealers dampen, the decline should be grindy, which is what
   11:34–11:48 was. Losing 7752 flipped `sum_gex_vol` negative, and 11:51–11:52
   is where the move accelerated (delta −862, −831).
3. **`put_wall` sat at ~7731 for the entire campaign**, drifting only 0.5 pt.
   That is 9 points *beyond* the declared 7740 target, and it is where the
   harvest ladder's deepest rungs actually filled.

## 3. Entry ladder — queue-aware fills

Offers rested from 11:21:00, TTL 14 min, conservative model (only fills ahead
of us count; assumes nobody ahead cancels).

| price | qty | queue ahead | level fill vol | cleared | filled |
| --- | --- | --- | --- | --- | --- |
| 7777.00 | 2 | 42 | 1037 | 11:23:25 | 2 |
| 7777.50 | 2 | 74 | 1230 | 11:23:29 | 2 |
| 7778.00 | 2 | 92 | 1528 | 11:24:08 | 2 |
| 7778.50 | 2 | 73 | 721 | 11:25:44 | 2 |
| 7779.00 | 3 | 70 | 501 | 11:25:48 | 3 |
| 7779.50 | 3 | 69 | 329 | 11:26:36 | 3 |
| 7780.00 | 3 | 91 | 339 | 11:26:00 | 3 |
| 7780.50 | 3 | 66 | 146 | 11:26:04 | 3 |
| 7781.00 | 4 | 62 | 322 | 11:26:08 | 4 |
| 7781.50 | 4 | 62 | 12 | — | 0 |

**24 of 28 contracts fill, average short 7779.29**, all inside about five
minutes. Optimistic bound: 28 at 7779.61.

Risk to the 7782 invalidation is **2.71 pts on 24 lots = $3,250** against a
39-point objective. The 7781.50 rung failing to fill is the model behaving
correctly: only 12 lots ever traded there against 62 ahead.

This is the concrete answer to "can I build 10–20 passively at better prices":
here, yes — and the average beats the nominated 7780.

## 4. Harvest ladder — comparison

Cover 24 lots, all ladders rested 11:56:00 (first print at/below 7740 was
11:56:40), TTL 24 min, which spans the 12:09 counter-rally to 7745.25.

| plan | covered | avg cover | pts/lot | realised $ | open at 12:01 | open at 12:09 | open at 12:18 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| flat at target (24 @ 7740) | 24 | 7740.00 | 39.29 | 47,150 | 0 | 0 | 0 |
| tight ladder (7740→7737) | 24 | 7738.50 | 40.79 | 48,950 | 6 | 0 | 0 |
| wide ladder (7740→7735) | 24 | 7737.50 | 41.79 | 50,150 | 12 | 0 | 0 |
| greedy ladder (7740→7728) | 24 | 7733.50 | 45.79 | **54,950** | 18 | **12** | 12 |
| Kahn BBO clip (today) | **3** | 7739.75 | 39.54 | 5,931 | 21 | 21 | 21 |

Reading this honestly:

- **Laddering beat the flat target limit**, by $1,800 (tight) to $7,800
  (greedy) on 24 lots.
- **The greedy ladder's edge is not free.** Its deepest rungs (7732/7730/7728)
  only cleared at 12:18:00–12:18:53, so it carried 12 uncovered lots through
  the 12:09 rally to 7745.25 — 5.25 points back above its own target. It won
  because price came back down. On a session where 12:09 kept going, that tail
  is where the give-back lives. One sample cannot distinguish skill from luck
  here.
- **Kahn's current harvest is the real problem.** `HarvestLimitPrice` joins the
  passive BBO with `max_working_quantity` typically 1, so it covered 3 of 24
  and left 21 lots open indefinitely. That is not a harvest; it is a token clip.
- The wide ladder is the risk-adjusted pick from this sample: +$3,000 over flat,
  fully covered before the counter-rally.

## 5. The conditioning rule this suggests

Ladder depth should not be a fixed tick count. The candidate rule:

- **floor** = declared target (7740).
- **stretch** = nearest stable GEX support beyond target — here `put_wall`
  7731.3, stable to 0.5 pt across the whole campaign.
- **depth allowed** is gated by local gamma sign at the target: positive gamma
  (dealers dampen, expect a pin) → tight ladder, take the fill; negative gamma
  (dealers amplify, expect overshoot) → extend toward the stretch level.

At 11:56 this campaign was in negative gamma (`sum_gex_vol` −110,609) with
`put_wall` 9 pts beyond target — the rule says extend, and extending paid.

The symmetric entry rule: **invalidation = the call wall**, which is what the
user chose by eye.

Both rules are one observation each. That is the holdout's job.

## 6. Caveats

- **In-sample.** Ladder spacing and depth were chosen after seeing the path.
- **Our own order is assumed not to change others' behaviour.** Fine at 2–24
  lots against levels turning over thousands, but it flatters the fills.
- **Fill model is a bracket, not a certainty.** Conservative assumes nobody
  ahead cancels; optimistic assumes all cancels were ahead. Here the two agreed
  on the harvest ladders and differed by 4 lots on entry.
- **GEX history starts 2026-08-27.** Only 8/27 and 8/28 exist, so the GEX half
  of this cannot be tested on anything earlier.
- **One trade, one direction, one session type.** No claim of generality.

## 7. Reproduce

```bash
uv run --with polars --with tzdata python research/kahn/es20260828/campaign_sim.py
uv run --with polars --with tzdata python research/kahn/es20260828/entry_band.py
uv run --with polars --with tzdata python research/kahn/es20260828/flow_report.py
uv run --with tzdata python research/kahn/es20260828/gex_window.py --category gex_zero
uv run --with polars --with tzdata python research/kahn/mbo_predictive_test.py
```
