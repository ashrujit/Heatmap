# L2_Surface

Single Quantower indicator that paints four toggleable structural layers on top of the live L2 book. Sister to `LiquidityMeter` (aggregate cum/ROC) and reads L2 captures from `L2_Heatmap`'s parquet writer for retrospective validation. All four layers share one sample loop, one event vocabulary, one z-scoring baseline — they're different views of the same underlying microstructure stream, not independent indicators.

Shipped 2026-05-08, consolidating what was originally planned as four separate indicators (L2_Events, L2_Inflection, L2_Flow, L2_Supply_Layer). Refactored 2026-05-09 (Option-A) to read the canonical book directly from `Symbol.DepthOfMarket` instead of maintaining a delta-merged `BookState` — eliminates the orphaned-level corruption class entirely (see RESEARCH_LOG 2026-05-08 follow-up).

## What it shows — four layers, z-ordered back to front

| # | Layer | Surface element | Render | Trigger |
|---|---|---|---|---|
| 1 | **Flow** band | Vertical translucent strip across full chart height during active flow regimes | orange (bear) / blue (bull) | sustained vacuum-event density + elevated RV + inner-depth thinning |
| 2 | **Build Bands** | Horizontal translucent rectangles at supply/demand zones | orange (supply) / blue (demand) | N same-side BUILDs within R ticks within T sec |
| 3 | **Climax** lines | Thin horizontal lines (full width to right) at provider-thrash levels | amber | VOD ≥ ClimaxVodZ AND any BUILD ≥ ClimaxBuildZ same sample, same tick |
| 4 | **Inflection** lines | Thin horizontal lines (trigger time → right edge) at cum-joins-ROC confirmations | blue (bull) / orange (bear) | BUILD ≥ TriggerBuildZ then cum AND ROC both flip ≥ thresholds within ConfirmationWindow |
| 5 | **Events** dots | Small additive-alpha squares at (time, mid-price) for every BUILD/PULL/IN/OUT/VOD event | blue (bull) / orange (bear) / amber (VOD) | event z-score above EventZThreshold |

Layers 4 and 5 are foreground: they sit on top so the trader's eye picks them up first. Layers 1–3 are translucent backdrops giving structural context.

## Layer details

### Events layer (the dot painter)

Three colors only:
- **Blue** = bull-leaning event (`BID_BUILD`, `BID_IN`, `ASK_OUT`, `ASK_PULL`)
- **Orange** = bear-leaning event (`ASK_BUILD`, `ASK_IN`, `BID_OUT`, `BID_PULL`)
- **Amber** = `VOL_OF_DEPTH` spike (neutral / fragility)

Side is meaningful (you do need to know "supply stacking" vs "demand stepping in"); event-type-within-side is not.

Density via additive alpha: each dot drawn at low alpha (default 70/255). Default Windows `Graphics` composition is `SourceOver` blending — single dot tints pixel ~27% toward color; 5 overlapping dots reach ~80% saturation. **Cluster intensity emerges from rendering, not from cluster-detection code.** No labels, no halos, no count badges. Intensity alone communicates.

### Inflection layer (cum-joins-ROC labels)

Encodes the 2026-05-05 win/loss-trade design rule: *"ROC alone is a warning shot; cum starting to follow ROC is the confirmation."*

State machine:
1. BUILD with `|z| ≥ TriggerBuildZ` (default 4.0) fires → register pending candidate at (time, mid-price, bias, cum-baseline-excluding-this-build).
2. On each subsequent sample for `ConfirmationWindowSec` (default 60s):
   - `delta_cum = current_cum_5m − candidate.cum_baseline`
   - If `sign(delta_cum) == bias AND |delta_cum| ≥ CumThreshold AND sign(roc_60s) == bias AND |roc_60s| ≥ RocThreshold` → **confirmed inflection** at the trigger price.
3. Pending candidate that doesn't confirm in the window is dropped.
4. Confirmed inflection paints as a horizontal line at the trigger price, from the trigger time to the right edge. Cleared on price-through (bear inflection clears when price closes above + buffer; bull inflection clears below − buffer).

Validation against design fixtures:
- **2026-05-07 12:31:42 28744** — ASK_BUILD z=4.19, cum delta ≈ −10 in 30s, ROC reaches −10 → fires bear inflection at 28744. ✓
- **2026-05-05 12:47:00 28119** — BID_BUILD z=4.37, cum delta ≈ +7.5, ROC reaches +6.9 → fires bull inflection at 28119. ✓
- **2026-05-07 12:15:48 28651** — BID_BUILD z=5.19 + VOD z=10.26, but cum continued bear → does NOT fire. ✓ (Different fingerprint — that's a Flow climax line, layer 3, not an inflection.)

### Flow layer (band + climax line)

Two render elements with two different triggers:

**Climax line** — point-in-time fingerprint of provider thrash at a price.
- Trigger: `VOD ≥ ClimaxVodZ` (default 5.0) AND any `BUILD ≥ ClimaxBuildZ` (default 4.0) at the same sample, at the same mid tick.
- Both events fire from the same sample by construction (z-scoring runs once per sample), so "same tick" ≡ both reference `sample.MidTick`.
- Paints as horizontal amber line at the climax price extending to the right edge. Cleared on price-through (either direction — line marks "level was contested," neutral on direction).
- 30-second debounce to avoid painting duplicate lines for contiguous same-tick climax samples.

Validation:
- **2026-05-07 13:29:24 28619** — VOD z=8.19 + ASK_BUILD z=5.13 at mid 28619.50 → climax line. ✓
- **2026-05-05 12:11:03 28147** — VOD z=6.98 + BID_BUILD z=4.30 + ASK_BUILD z=4.22 → climax line. ✓ (On a +444 trend day; line eventually traded through upward, which clears it. Indicator behaves correctly: lines persist on respected levels, vanish on broken ones.)
- **2026-05-07 12:31:42 28744** — VOD only z=3.21 (below threshold) → does NOT fire climax. ✓ (28744 was a cascade-start, not a thrash-climax. Naturally handled by Inflection lines + Events dots + Build Bands instead.)

**Flow band** — sustained-window state machine for active flow regimes.
- Bear flow: `bear_event_count ≥ BandEventCount` (default 5) in `BandWindowSec` (default 30s) AND `RV ≥ BandRvThreshold` AND `inner_depth_z ≤ -BandInnerThinZ`. Symmetric for bull.
- Sustained match for `BandSustainSec` (default 10s) opens a band starting at the first match time.
- Match break for `BandCooldownSec` (default 30s) closes the band at the last match time.
- Open band's end time updates each sample; the painter sees the latest end time on every frame.
- RV computed from rolling sum of squared log-returns of mid price over the band window. 1 Hz sampling is coarser than tick-by-tick but adequate for "is volatility elevated right now" — avoids subscribing to NewLast just for RV.

### Build Bands layer (supply/demand clusters)

Clusters same-side BUILD events into horizontal price-range zones.

Algorithm:
- Each new ASK_BUILD or BID_BUILD checks existing same-side bands for proximity (within `BuildClusterTicks` of band's range, within `BuildClusterSec` of last update). If matches, extend the band (update min/max ticks, last-update time, increment count).
- If no existing band extended, count same-side recent BUILDs (within `BuildClusterTicks` and `BuildClusterSec` of this event). If count ≥ `BuildClusterN` (including this event), promote to a new band; otherwise add to pending.
- Pending events evicted by age past `BuildClusterSec`.
- Bands persist until price-through:
  - **Supply band** (ask side, above price): clears when mid > MaxTick + buffer
  - **Demand band** (bid side, below price): clears when mid < MinTick − buffer

Validation:
- **2026-05-07 12:31:42 → 12:47:45** — ASK_BUILDs at 28744, 28737, 28734, 28727, 28732, 28720 over ~16 minutes within 24-tick range → forms a single supply band 28720–28744 that persists as a structural reference until price closes above 28744 + buffer. ✓
- **2026-05-07 down-leg add zones** — ASK_BUILDs at 28859, 28831, 28812, 28786, 28722 are spread > 8 ticks apart — they form **separate** bands (or join existing ones if proximity allows). Trader sees discrete zones, not one mushy "supply everywhere" blob. ✓

## Why one indicator, not four

We considered four separate indicators (one per layer) and discarded that. Reasoning:

1. **Shared state.** Every layer reads the same DOM sample, same z-scored sample stream, same event vocabulary, same RV/inner-depth metrics. Four separate indicators meant four DOM polls, four sample loops — substantial duplication of compute for no functional gain.

2. **Composition.** Layers compose visually: Flow band gives context, Build Bands give level structure, Climax/Inflection lines mark moments, Events dots add fine-grained texture. Toggling layers via one indicator's settings dialog is more ergonomic than juggling four chart instances.

3. **Z-order matters.** A composite painter explicitly orders layers (background → foreground) so translucent backdrops don't obscure foreground markers. Four indicators paint independently; QT's render order is implicit and not controllable.

4. **One on/off.** "Turn the whole thing off temporarily" is one toggle. Four indicators = four toggles.

The cost: this single project is larger (~1500 lines vs ~700 each) and the engine has more responsibility surface. Trade-off is worth it for a tightly-coupled visualization suite.

## File map

- `L2_Surface.csproj` — net8-windows, AnyCPU, no nuget deps, no unsafe code.
- `L2_Surface.cs` — entry point, ~50 InputParameters across six groups (Common 800, Events 810, Inflection 820, Flow 830, Build Bands 840, Render 850), DOM polling + sample + paint dispatch. Pushes config into engine + painter on each sample so settings-dialog changes take effect without restart. Subscribes to `NewLevel2` only as a freshness heartbeat (not for delta processing).
- `SurfaceEngine.cs` — single engine, ~600 lines. Shared sample/baseline/z-score infrastructure, plus per-layer detection and state:
  - Events: `_events` linked list (every emitted event with bias/z/price/type)
  - Inflection: `_pending` + `_inflections` + cum/ROC running totals
  - Flow climax: `_climaxLines` with 30s same-tick debounce
  - Flow band: `_flowBands` + state machine fields (`_state`, `_matchStart`, `_lastMatchTime`)
  - Build Bands: `_buildBands` + `_buildPending`
- `SurfacePainter.cs` — composite painter, ~200 lines. Z-ordered render: Flow → Build Bands → Climax → Inflection → Events. Each sub-render gated by its own enabled flag. Off-screen culling via `cv.GetTime(rect.Left/Right)` for the Events dot loop.

## Architectural invariants (do not break without thinking hard)

1. **No blocking on UI thread.** `Symbol.NewLevel2` heartbeat handler does only a timestamp write; sample + paint run on UI thread.
2. **Read DOM, don't maintain state.** `OnSample` calls `Symbol.DepthOfMarket.GetDepthOfMarketAggregatedCollections(...)` to get `Level2Item[]` for each side. QT maintains the canonical book; orphan-level corruption is structurally impossible (see RESEARCH_LOG 2026-05-08).
3. **Tick-keyed math.** Convert `Level2Item.Price` → `long` ticks via `(long)Math.Round(price / tickSize)` whenever you key by price. Float-equality across independently computed prices breaks `Dictionary` lookup.
4. **Forward-only.** No history; engine warms up over the configured lookback (default 30s) before z-scores stabilize. After ~5 samples the baselines have enough data to fire.
5. **Engine computes all layers regardless of enabled flags.** Toggle gates rendering only. Flipping a layer on mid-session shows accumulated state immediately, not an empty warmup.
6. **One sample loop.** Don't add a second sample timer for any layer's "extra" computation. Cost of the unified loop is O(events_in_5min) ≈ few µs/sample.
7. **Persistence is a feature.** Default no auto-clear on Events dots (the 2026-05-07 28744 cascade story). Auto-Clear is opt-in via `Events: Auto-Clear After (min)`. Build Bands, Climax lines, and Inflection lines clear on price-through which IS the right semantics for them.
8. **No labels, no halos, no count badges anywhere.** Density-via-alpha and color-coding-by-side carry the entire information load. Adding visual annotations breaks the eyes-on-the-road posture.

## Performance

- Sample loop: O(events_in_5min) per sample, ~few hundred events/day. Linked-list ops, no allocations beyond `L2Event` objects (~80 bytes each).
- Paint: O(visible events) per frame after off-screen cull. ~1k events/day × 36 px = 36k pixel writes; negligible.
- Memory: ~80 KB / 1000 events. Session-long persistence has zero practical cost.

## Settings dialog grouping

Six groups (sortIndex ranges):
- 800–809 — Common (lookback, z threshold, sample interval, price-through buffer)
- 810–819 — Events Layer (enabled, dot size/alpha, auto-clear)
- 820–829 — Inflection Layer (enabled, trigger z, cum/ROC thresholds, windows)
- 830–839 — Flow Layer (enabled, climax thresholds, band parameters, alpha)
- 840–849 — Build Bands Layer (enabled, cluster N/ticks/seconds, alpha)
- 850–859 — Render misc (line thickness, alpha)

`SettingItemSeparatorGroup` wrapping in the `Settings` override on the indicator class.

## Build & deploy

```
dotnet build
```

DLL drops at `C:\Quantower\Settings\Scripts\Indicators\L2_Surface\L2_Surface.dll`. Restart Quantower → right-click chart → Indicators → "L2 Surface".

## Verification flow

The events this indicator emits should match (within ±1 sec, ±1 tick) what `research/liq_events.py` produces from the captured parquet for the same session. After a session:

1. Eyeball moments of interest — do dots/lines/bands align with structural events the trader's intuition flagged?
2. Spot-check: for a visible cluster, look up that time in `liq_events_<DATE>.csv` and confirm the same set of events fired.
3. Cross-check Inflection lines against the cum/ROC dynamic in `meter_walk.py` for the same window. Confirmed inflections should land at moments where cum and ROC both flipped/aligned within seconds of a heavy BUILD.
4. Note divergences. Live render uses live book (1 Hz, 30s rolling baseline) which warms up over time; research scripts process full-day parquet at once and are statistically more stable. Small drift is expected; major signals should agree.

## Tuning posture

Defaults derived from the 2026-05-05 / 2026-05-07 retro analyses (Inflection thresholds tuned to the 28744 + 28119 fixtures; Flow climax thresholds to 28619 + 28147; Build Bands tuned so 28720–28744 forms one band, 28859 / 28831 / 28812 stay separate).

Same posture as the rest of the suite: defaults are starting points, not optimized. Iterate from live use. Order to tune in if the indicator feels off:

1. **Layer enables** — turn off any layer that's adding noise rather than signal until you've evaluated each one alone.
2. **Per-layer thresholds** — raise z-thresholds first if too noisy, lower if too sparse.
3. **Persistence behavior** — Events auto-clear, price-through buffer if levels feel too sticky.
4. **Render alphas** — band/dot/line opacity to taste; doesn't change semantics.

## Open questions

These will only be answered through live use across multiple session types:

- **Inflection precision.** Today's design fires on (cum_delta ≥ 7) AND (ROC ≥ 5). Are these thresholds catching the right moments and not over-firing in chop? Need 5–10 sessions of mixed regime to evaluate.
- **Flow band false positives.** Will trend-day swings (without forced flow) trigger flow bands? The inner-thinning requirement should filter most, but worth tracking.
- **Build Bands proximity tuning.** Default 8-tick cluster range (~2 NQ points). Tighter (e.g. 4) gives more bands; looser (16+) gives fewer, broader zones. Right answer depends on how the trader reads "supply zone" granularity.
- **Climax debounce window.** 30 seconds same-tick. May need adjustment if a regime produces clusters of climaxes at the same level over short periods.
- **Render order on cluttered charts.** When all four layers fire densely (a forced-flow day with many supply layers), does the visual decode cleanly, or does one layer obscure another? Will know after first few live sessions.
