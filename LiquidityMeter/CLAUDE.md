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

- **Live source**: `Symbol.DepthOfMarket.GetDepthOfMarketAggregatedCollections(...)` — QT's canonical book, polled once per sample. We don't maintain a delta-merged BookState (refactored 2026-05-09 — see RESEARCH_LOG 2026-05-08 follow-up: orphan-level corruption is structurally impossible reading from QT's book). `Symbol.NewLevel2` is subscribed only as a freshness heartbeat for the STALE-badge logic.
- **Sample cadence**: a 1-second timer (driven from `OnUpdate` elapsed-time check) reads top-30 levels each side from DOM → derives `bid_inner`, `ask_inner`, `bid_centroid`, `ask_centroid` (top-10 sums + size-weighted |offset| over top-30).
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
- `LiquidityMeter.cs` — entry point, settings (sortIndex 900-915 in two groups), DOM polling at sample cadence, paint dispatch. Subscribes to `NewLevel2` only as a freshness heartbeat.
- `MeterEngine.cs` — sample buffer, rolling stats, side-aware event detection, cum/ROC math. Internal classes `Sample` + `MeterEvent` use a private `ITimestamped` interface for shared eviction logic.
- `MeterPainter.cs` — left-center vertical strip rendering. Anti-aliased `FillRectangle` for the cum bar + `FillPolygon` for the needle. Tick marks at quarter scale points. Numeric `cum` and `roc` labels below the strip; event count above.

## Anchor modes

- **Rolling Window** (default, 30 min): cum continually re-anchored to `now - window`. Always-on, no user input. Best for "running through the day, eyeing the meter."
- **Indicator Load**: anchor fixed at the moment the indicator was added. Cum accumulates from there. Resets if indicator is removed/re-added.
- **Session Start (NY 09:30)**: anchor at today's RTH open. Cum = full session lean.

### Manual click-anchor (v0.2, override)

Left-click anywhere inside the meter strip (ROC dial, VOD strip, cum bar, or labels block) → sets anchor at *now*. Right-click inside the strip → clears, reverts to whichever mode is configured above.

Deliberately implemented as an **override**, not a fourth mode, so the existing dropdown semantics stay intact and a click always works regardless of the configured default. While active: `cum` label shows `cum*` and a `@HH:MM:SS` line (NY time) appears below the labels showing the anchor instant.

Click target is restricted to the meter region — clicks elsewhere on the chart are unaffected (won't conflict with crosshair, drawing tools, or pan).

In-memory only: clears on indicator unload. Same posture as Indicator Load mode.

The anchor is set at the click instant, not at a clicked-bar timestamp. Backdating would have required converting click X to chart time and risks anchoring off-by-one if the click lands between bars; "anchor at now" matches the actual trader question ("I just entered, start counting from now").

## Architectural invariants

1. **No blocking on UI thread.** `Symbol.NewLevel2` heartbeat handler does only a timestamp write; sample + paint run on UI thread.
2. **Heartbeat ignores pseudo-L2.** Quantower can emit `generated_from_level1` / NaN pseudo-L2 events from L1 best-bid/ask changes. These do not prove the book stream is fresh and must not reset the stale timer.
3. **Read DOM, don't maintain state.** Each sample calls `Symbol.DepthOfMarket.GetDepthOfMarketAggregatedCollections(...)`. QT maintains the canonical book; we don't. See RESEARCH_LOG 2026-05-08.
4. **Tick-keyed math.** `(long)Math.Round(price / tickSize)` for any price-keyed dictionary.
5. **Forward-only.** No history; meter warms up over the configured lookback (default 30s) before z-scores stabilize.
6. **VOD events deliberately omitted.** Neutral-bias events would just inflate event count without affecting cum/ROC.

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
