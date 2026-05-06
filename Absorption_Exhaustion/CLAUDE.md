# Absorption_Exhaustion

Quantower indicator that surfaces microstructure anomaly shapes (absorption / exhaustion variants) from the trade tape and renders them as a price-band accumulator across the chart. Display-only, no persistence, no event log.

## Why this shape, not labels

Absorption and exhaustion as commonly named are not unambiguous events — the same microstructure shape ("one side aggressed, didn't extend") means *reversal* at a true extreme and *continuation pause* inside a sustained move. The indicator does not classify or label; it surfaces the raw shape and lets the trader's existing context (reference levels, value structure, regime) interpret it. See conversation history for the design rationale; the short version is:

- 4 primitives detect *shapes*, not *events with meaning*
- Per-fire faint glyphs at (price, time) for live awareness
- Persistent visual is the **price-band accumulator**: horizontal tinted lines per (price, direction), intensity scaled by count + recency
- Bands **self-clear** when price trades K ticks past them in the invalidating direction (mirrors QT cluster-chart imbalance clearing)
- No state machine, no "confirmed" tier, no claim of significance

## The four primitives

All evaluated at 5-second bar close against the prior `LookbackSeconds` of bars (default 60s).

| ID | Name | Fires when |
|---|---|---|
| **A1** | Stacked one-sided imbalance, no extension | Bar prints new local high/low AND ≥`A1StackedN` consecutive levels at the extreme have one-sided aggressor imbalance > `A1Imb` AND each level has ≥ `A1MinVolPerLevel` volume |
| **A2** | Balanced absorbing bar | Bar prints new local high/low AND vol z-score > `A2VolZ` AND `\|delta\|/vol < A2DeltaRatio` (high-vol balanced fight at the extreme) |
| **E1** | Single-print at extreme | Bar's extreme price has ≤ `E1ThinMaxVol` contracts AND a level within 2 ticks inside has ≥ `E1NeighborMinVol` with imbalance > `E1NeighborMinImb` (thin tail at the very extreme, heavy aggression just inside) |
| **E2** | Weak-delta extreme bar | Bar prints new local extreme on `\|delta\|/vol < E2WeakDelta` (extreme made on no conviction) |

Direction:
- New high → `Bear` (the failure of further upside is the signal)
- New low → `Bull` (the failure of further downside is the signal)

The volume-per-level floor on A1 is the primary filter against the "every 5-sec bar fires A1" failure mode found in the Python dry-run; without it, levels with 5 contracts at +1.0 imbalance counted the same as levels with 80 contracts at +0.5.

## Self-clearing rule

For each surviving band at price tick `T` with direction `D`:
- `Bear` band clears when current price > `T + ClearKTicks`  (level reclaimed → bears didn't actually fail)
- `Bull` band clears when current price < `T − ClearKTicks`  (level broke → bulls didn't actually defend)

Cleared bands move to a recently-cleared list and render as a fading dashed grey line for `ClearedFadeSec`, so the user *sees the break event*. After the fade window, they're dropped.

This is why the indicator stays truthful in trends: in the Python dry-run, the 27932 zone fired 7 bull primitives across 5 minutes, but when price broke below 27932 at 10:53 those would all clear in this implementation, leaving only the genuinely unbroken bear marks at the prior swing high. The visual stops lying about a level mattering the moment the level stops mattering.

## File map

- `Absorption_Exhaustion.csproj` — net8-windows, AnyCPU. **No `AllowUnsafeBlocks`** — band painting is sparse compared to L2 heatmap and per-element `FillRectangle` is fine here. References `TradingPlatform.BusinessLayer.dll` from the resolved Quantower install. `OutputPath` deploys directly to `C:\Quantower\Settings\Scripts\Indicators\Absorption_Exhaustion\`.
- `Absorption_Exhaustion.cs` — indicator entry point. Subscribes to `Symbol.NewLast` in `OnInit`, drains queue + closes stale bars in `OnUpdate`, paints in `OnPaintChart`, unsubscribes in `OnClear`. Settings dialog grouped via `SettingItemSeparatorGroup` (sortIndex 800-859, six groups).
- `TradeBuffer.cs` — 5-second bar aggregation + rolling lookback. Bars hold OHLCV, signed delta, and a tick-keyed volume-by-price dictionary with separate buy/sell sums. `OnTrade` returns the bar that just closed (or null). `TryCloseStaleBar(now)` forces close on quiet stretches so detectors run even if no trades arrive.
- `PrimitiveDetector.cs` — pure detection logic. `EvaluateClosedBar(bar)` yields a sequence of `PrimitiveFire` for the four primitives. Baseline computed from history *excluding* the bar itself.
- `PriceBandRegistry.cs` — the persistent visual state. Bands keyed by `(priceTick, direction)`, with `Count`, `LastFireTime`, and `RecentFires` for glyph fade. `OnPriceUpdate(currentTick, now)` runs the self-clearing pass and evicts cleared/glyph entries past their fade windows.
- `ChartPainter.cs` — the render pass. Three layers: horizontal bands (alpha = f(count, recency); both-direction → amber blend), faded glyphs at `(price, time)` of recent fires, and dashed-grey fade-out for recently cleared bands.

## Architectural invariants

1. **No blocking on UI thread.** `Symbol.NewLast` callback enqueues only. Drain + detection + registry update run on the UI thread inside `OnUpdate`. `OnPaintChart` is also UI-thread.
2. **Tick-keyed price registry.** `(long)Math.Round(price / tickSize)` everywhere; never `double` keys. Float-equality across independently computed prices breaks `Dictionary` lookup.
3. **Forward-only.** No historical replay, no warmup data. Detectors silently no-op until `LookbackSeconds`-worth of bars have accumulated.
4. **Detection is bar-close, not per-tick.** Per-tick detection would be 50–100× more work for marginal real-time gain. The 5-second cadence is a deliberate compromise; the bar boundary is wall-clock-floored, not tick-count-aligned, so the detector evaluates on consistent windows regardless of trade rate.
5. **Clearing runs on every price update, not on a timer.** Cleared bands are reactive to the auction, not to time. Quiet markets simply don't trigger clearings.
6. **No bitmap caching.** Band layer is sparse (10s of bands, not 100k cells), so per-frame `FillRectangle` is fine. If band count ever blows up — would need to be hundreds of simultaneous unbroken bands, which would itself be a sign the clearing rule is too lenient — revisit then.

## Build & deploy

```
dotnet build
```

DLL drops at `C:\Quantower\Settings\Scripts\Indicators\Absorption_Exhaustion\Absorption_Exhaustion.dll`. Restart Quantower → right-click chart → Indicators → Add Indicator → "Absorption / Exhaustion".

## Verification

Add to a tick chart (e.g. 5000-tick NQ) during active hours. Within the first lookback window (default 60 s) detectors are silent; after that, glyphs and bands begin to appear at price levels where the four primitives fire. As price trades through bands they should clear, leaving a brief dashed-grey trace and then disappearing.

## Tuning posture

Defaults are derived from inspecting four real cases (10:46 HOD absorption, 14:45 swing-low absorbing bar, 12:12 weak-delta exhaustion, 04/30 stacked-imb absorption). They are not optimized. Tuning is intentionally **eyeball-based**: run live, observe what fires too often or too rarely, adjust thresholds. Parameter sweeps over historical data would require an L2/tick replay harness we deliberately have not built — see conversation history (skip-tuning rationale).

If a primitive feels hopelessly noisy, the right responses in priority order:
1. Raise its volume floor (A1 `MinVolPerLevel`, A2 `VolZ`, E1 `NeighborMinVol`)
2. Tighten its imbalance/delta threshold
3. *Disable it entirely* — primitives are independent. Removing E2 if it's hopeless doesn't compromise the others.

## Known gotchas

- `AggressorFlag` enum has 4 values (`None`, `Buy`, `Sell`, `NotSet`). Both `None` and `NotSet` map to aggressor sign 0 and contribute to total volume but neither buy nor sell — these prints don't move delta. Some venues / replay paths leave aggressor as `NotSet`; if delta is consistently zero on live data, suspect this.
- `Last.Time` may be `default(DateTime)` on synthetic prints (e.g. backfill). Indicator falls back to `DateTime.UtcNow` in that case.
