# Code Review

Read-only review performed from the repository state on 2026-05-06. This file focuses on concrete implementation and documentation findings, not broad design commentary.

## Findings

### 1. LiquidityMeter cumulative window is much shorter than the documented anchor modes

`LiquidityMeter/MeterEngine.cs` recomputes cumulative from `_events`, but then evicts events older than `_rocWindowSec * 6`.

With defaults, `_rocWindowSec = 60`, so the engine keeps roughly 6 minutes of events. That conflicts with the documented anchor modes:

- Rolling Window default: 30 minutes
- Indicator Load: from load time
- Session Start: from NY 09:30

Relevant code:

- `LiquidityMeter/MeterEngine.cs`: `RecomputeCumulative()`
- `LiquidityMeter/MeterEngine.cs`: `EvictOlderThan(_events, nowUtc, _rocWindowSec * 6)`
- `LiquidityMeter/CLAUDE.md`: Anchor modes and cumulative definition

Impact: the visual `cum` value can look like an anchored slow-regime read while actually behaving like a short rolling measure. This matters because the core trading read is "ROC warning shot; cum following ROC confirms."

Possible fix direction: keep events at least as long as the active anchor horizon. For rolling mode, retain `RollingAnchorWindow + margin`; for session/load modes, either retain since anchor or store cumulative buckets so old events can be compacted without losing anchor semantics.

### 2. Live LiquidityMeter does not fully mirror `research/liq_events.py`

The docs say the live `MeterEngine` mirrors the research event detector. The research script suppresses duplicate event onsets within 5 seconds per event label; the live engine fires every sample while a metric remains beyond threshold.

Relevant code:

- `research/liq_events.py`: duplicate suppression using `ts.diff().over("event") < 5`
- `LiquidityMeter/MeterEngine.cs`: `TryFire(...)` appends every threshold-crossing sample

Impact: live `cum`, `ROC`, and event count can run hotter than the research CSV during sustained excursions. That can make live behavior diverge from the fixtures used to justify the meter.

Possible fix direction: add per-event-label cooldown/onset gating in `MeterEngine`, or explicitly document that live meter intentionally measures sustained pressure rather than event onsets.

### 3. Shared `BookState` may mishandle some L2 removal/update semantics

Both `L2_Heatmap/BookState.cs` and `LiquidityMeter/BookState.cs` store `OrderEntry.IsBid`, but removals use the incoming quote side to choose the map to mutate. If a close/update for an existing ID arrives with side metadata that differs from the original order side, the prior contribution may be removed from the wrong side.

Also, for a non-closed quote with `Size <= 0`, `_orders` removes the ID and subtracts prior size, but if the price did not change, the ID is not removed from `PriceLevel.Ids`. This can leave an empty ID shell with `TotalSize == 0` in the level.

Relevant code:

- `L2_Heatmap/BookState.cs`: `Apply(Level2Quote q)`
- `LiquidityMeter/BookState.cs`: mirrored `Apply(Level2Quote q)`

Impact: if Quantower always sends true removals as `Closed`, this may never matter. If the feed sends zero-size active updates or side-inconsistent closes, stale or wrong-side book state can distort heatmap cells and, more importantly, LiquidityMeter best-level metrics.

Possible fix direction: when `prior.Size > 0`, remove prior contribution from `prior.IsBid ? _bids : _asks`. For any zero-size update, remove the ID from the prior level and remove the level if size/ID count reaches zero.

### 4. L2 heatmap incremental cache ignores adaptive saturation changes

The heatmap cache invalidates on snapshot count, oldest/newest timestamp, and chart geometry. It does not include `heatmap.EffectiveSaturation` in the cache signature.

Adaptive saturation recomputes every 60 seconds. If saturation changes and the next paint qualifies for the append-only incremental path, old pixels remain colored with the old saturation scale while the newest extend-zone is painted with the new scale.

Relevant code:

- `L2_Heatmap/LiquidityHeatmapBuffer.cs`: `UpdateAdaptiveSaturation()`
- `L2_Heatmap/ChartPainter.cs`: cache invalidation in `DrawLiquidityHeatmapCached(...)`
- `L2_Heatmap/ChartPainter.cs`: `TryAppendIncremental(...)`

Impact: visual color/alpha scale can be internally inconsistent after adaptive recompute. It is probably subtle, but the whole point of adaptive saturation is visual comparability.

Possible fix direction: include effective saturation, alpha max, size floor, and levels window in the cache signature. When any scale-affecting setting changes, force full rebuild.

### 5. A/E unknown aggressor handling differs between total bar volume and per-price primitive volume

The docs say `AggressorFlag.None` and `NotSet` contribute to total volume but neither buy nor sell. That is true for bar-level `Volume`, but primitive per-price volume uses only `buy + sell`.

Relevant code:

- `Absorption_Exhaustion/TradeBuffer.cs`: total volume increments for every print
- `Absorption_Exhaustion/PrimitiveDetector.cs`: A1/E1 level volume uses `v.buy + v.sell`
- `Absorption_Exhaustion/CLAUDE.md`: unknown aggressor gotcha

Impact: on feeds with many unknown aggressor flags, A2/E2 bar-level delta behavior and A1/E1 per-level volume floors can diverge. Since captured NQ data had populated aggressor flags, this is likely low-risk right now.

Possible fix direction: either document that A1/E1 intentionally ignore unknown-side level volume, or track unknown per price and include it in volume-floor checks while excluding it from imbalance numerator.

### 6. Documentation naming drift: `AGENTS.md` vs `CLAUDE.md`

Root `AGENTS.md` says every subproject gets its own `AGENTS.md` and links to subproject `AGENTS.md` files. The repository currently uses subproject `CLAUDE.md` files, and README points to those.

Relevant files:

- `AGENTS.md`
- `README.md`
- `L2_Heatmap/CLAUDE.md`
- `Absorption_Exhaustion/CLAUDE.md`
- `LiquidityMeter/CLAUDE.md`

Impact: future agents may follow broken links or miss the actual design docs.

Possible fix direction: standardize on one name, or keep both with one as a thin pointer. Since this environment provided root `AGENTS.md` as active instructions, `AGENTS.md` may be the better long-term convention for Codex compatibility.

## Positive Notes

- The project philosophy is coherent across docs, research, and code: show structure, avoid false certainty.
- The Quantower threading pattern is consistently respected: callbacks enqueue, UI-thread update drains.
- Tick-keyed price handling is used where it matters.
- L2 heatmap rendering is performance-conscious without spreading unsafe code widely.
- A/E's self-clearing price bands are a strong design choice: they prevent stale "signal graffiti" during trends.
- LiquidityMeter has a compact visual grammar: slow cum, fast ROC, neutral VOD chaos. The separated axes are a good attention-design decision.
