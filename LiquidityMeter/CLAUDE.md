# LiquidityMeter

Quantower indicator that paints a left-center "fuel-gauge + needle" reading the live order-book regime. Sister to `L2_Heatmap` and `Absorption_Exhaustion` — same posture: surface microstructure structure, don't predict, let the trader's context decide. Designed as a sizing/exit aid, not an entry signal.

## What it shows

Three visual elements at left-center of the chart pane:

- **Fuel gauge — CUM (slow, vertical bar)**: grows from a horizontal centerline. Up (green) = cumulative bull lean since anchor; down (red) = cumulative bear. "Where the lean is right now in this trade arc / time window."
- **Oscillating dial — ROC (fast, horizontal bar)**: separate horizontal bar below the cum gauge. Grows from a vertical centerline. Right (green) = bull pressure; left (red) = bear pressure. Triangle pointer at leading edge for unambiguous direction. "What's the immediate pressure right now." *Designed as horizontal so the eye can't mistake it for the cum bar — different shape, different axis.*
- **VOD flicker (small amber box)**: brightens when a VOL_OF_DEPTH spike fires (high z on rolling stdev of inner-depth deltas), fades over ~6 sec. Neutral on bias; tells you "providers are thrashing." Sustained flicker = repositioning chaos; quiet box = orderly tape.

Read them together. Sustained green cum + green ROC = bull thesis intact and immediate pressure aligned (size-up supported). Long green cum + red ROC = lean intact but pressure shifting (warning shot — *attention*, not action). Persistent sign mismatch = lean about to flip. Mirror reading for bear. The VOD flicker tells you whether the dance is happening on a steady tape (signal) or a chaotic one (provider repositioning that may resolve either way).

The 12:47:00 inflection on 2026-05-05 (loss-trade narrative): cumulative had been deeply negative (bear lean confirming the short), then BID_BUILD z=+4.37 + BID_IN at 28119.50 fired and ROC popped from -5.2 to +3.8 to +6.9 in about 20 seconds while cum *also* started climbing. **Cum starting to follow ROC against the existing lean is the unambiguous "this is it"** — at least on the one design-fixture trade we have.

## Architecture

- **Live source**: `Symbol.NewLevel2` deltas feed an in-process `BookState` (mirror of L2_Heatmap's, kept in sync). Drains in `OnUpdate`.
- **Sample cadence**: a 1-second timer (driven from `OnUpdate` elapsed-time check) samples `BookState` → derives `bid_inner`, `ask_inner`, `bid_centroid`, `ask_centroid` (top-10 sums + size-weighted |offset| over top-30).
- **Rolling baseline**: 30-second mean/std per metric, recomputed each sample. Z-scores derived. |z| > 2.5 fires a directionally-tagged event.
- **Event vocabulary** (matches `research/liq_events.py` exactly):

| Event | Bias | Meaning |
|---|---|---|
| `BID_BUILD` | +1 (bull) | bid stack growing — support thickening |
| `BID_PULL` | -1 (bear) | bid stack thinning — support evaporating |
| `ASK_BUILD` | -1 (bear) | offer stack growing — resistance thickening |
| `ASK_PULL` | +1 (bull) | offers being pulled — sellers retreating |
| `BID_IN` | +1 (bull) | bid mass migrating toward mid — committing closer |
| `BID_OUT` | -1 (bear) | bid mass migrating outward — bids retreating |
| `ASK_IN` | -1 (bear) | offer mass migrating toward mid — sellers leaning in |
| `ASK_OUT` | +1 (bull) | offer mass migrating outward — sellers backing off |

**VOL_OF_DEPTH events** are detected (separate buffers: rolling 30s stdev of Δinner_depth → "vod" series → 120s baseline → z-score → fire at |z| > threshold). Neutral on bias, so they do *not* contribute to cum or ROC. They feed the flicker indicator only. Cut/keep decision pending live observation across multiple sessions.

- **Cumulative**: `Σ (bias × |z|)` over events newer than the anchor.
- **ROC**: `Σ (bias × |z|)` over events in the last `ROCWindowSeconds` (default 60).

## File map

- `LiquidityMeter.csproj` — net8-windows, AnyCPU. **No nuget deps**, no unsafe code.
- `LiquidityMeter.cs` — entry point, settings (sortIndex 900-915 in two groups), L2 subscription, drain + sample loop, paint dispatch.
- `BookState.cs` — mirror of L2_Heatmap/BookState.cs. Same NaN-filter, tick-keying, closed-quote handling.
- `MeterEngine.cs` — sample buffer, rolling stats, side-aware event detection, cum/ROC math. Internal classes `Sample` + `MeterEvent` use a private `ITimestamped` interface for shared eviction logic.
- `MeterPainter.cs` — left-center vertical strip rendering. Anti-aliased `FillRectangle` for the cum bar + `FillPolygon` for the needle. Tick marks at quarter scale points. Numeric `cum` and `roc` labels below the strip; event count above.

## Anchor modes

- **Rolling Window** (default, 30 min): cum continually re-anchored to `now - window`. Always-on, no user input. Best for "running through the day, eyeing the meter."
- **Indicator Load**: anchor fixed at the moment the indicator was added. Cum accumulates from there. Resets if indicator is removed/re-added.
- **Session Start (NY 09:30)**: anchor at today's RTH open. Cum = full session lean.

A manual click-anchor (mark anchor at trade entry) is the natural next addition but deferred to v0.2 — we want to validate the math first against several sessions before adding interaction surface.

## Architectural invariants

1. **No blocking on UI thread.** `Symbol.NewLevel2` callback only enqueues. Drain + sample + paint all run on UI thread.
2. **Tick-keyed book.** `(long)Math.Round(price / tickSize)` everywhere.
3. **Filter pseudo-L2.** `BookState.Apply` skips `id="generated_from_level1"` (NaN price/size).
4. **Forward-only.** No history; meter warms up over the configured lookback (default 30s) before z-scores stabilize.
5. **VOD events deliberately omitted.** Neutral-bias events would just inflate event count without affecting cum/ROC.

## Build & deploy

```
dotnet build
```

DLL drops at `C:\Quantower\Settings\Scripts\Indicators\LiquidityMeter\LiquidityMeter.dll`. Restart Quantower → right-click chart → Indicators → "Liquidity Meter".

## Tuning posture

Defaults derived from the research-side analysis of 2026-05-05 captures (one win + one loss trade walked through). They are **not** optimized — same posture as A/E. The user planned to observe across many session types (trend, balance, news, OPEX) before drawing conclusions.

If the meter feels mis-tuned in live use, in priority order:
1. Adjust `Cum Scale` / `ROC Scale` if the bar/needle pegs out or stays small
2. Adjust `Event Z Threshold` (raise → fewer events, lower → noisier)
3. Adjust `Lookback Seconds` (shorter = more reactive, more false positives in slow tape)
4. Switch `Anchor Mode` if the rolling-30-min default doesn't fit how you read

## Verification flow

This indicator's value is unproven; treat the first weeks as data-collection. After each session:
1. Eyeball whether the meter's cum/needle behavior at moments-of-interest in real time matches the trader's intuitive read of those moments
2. Cross-check against `liq_events.py` output (the meter is just a live render of those same events) — they should agree
3. Note divergences: when the meter screamed and price went the other way, when nothing fired but a clean structural turn happened. Both kinds of failure inform iteration.
