# L2_Heatmap

Quantower indicator that paints a Bookmap-style L2 liquidity heatmap as a chart backdrop. Display-first; an opt-in capture path writes top-200 L2 snapshots (50 NQ price points each side at tickSize 0.25) and trade ticks to parquet for offline research (depth-σ / liquidity-pull work). Capture is off by default and decoupled from the display path. Ported from the heatmap layer of a larger parent indicator (Skurry_Scribe).

## What it does

Each sample tick (~2 Hz), the indicator reads QT's canonical book via `Symbol.DepthOfMarket.GetDepthOfMarketAggregatedCollections(...)` — top-200 levels each side, returned as `Level2Item[]`. That snapshot becomes one column on the chart; each `(price, size)` entry is one cell whose alpha scales with size. Bid cells are blue, ask cells orange. A two-regime alpha curve lifts cells past the saturation point with a brighter "ignition" tone so the top tail of the size distribution unfolds into a visible gradient instead of clamping flat.

The indicator also writes captured snapshot rows + tick rows to parquet (independent cadence, see Capture below) — this is the data foundation the rest of the suite reads from for retro analysis.

## File map

- `L2_Heatmap.csproj` — net8-windows, AnyCPU, `AllowUnsafeBlocks=true`, `OutputPath` deploys directly to `C:\Quantower\Settings\Scripts\Indicators\L2_Heatmap\`. References `TradingPlatform.BusinessLayer.dll` from the resolved Quantower install.
- `LiquidityHeatmapBuffer.cs` — rolling snapshot queue. `OnSample(dom, nowUtc)` accepts QT's `DepthOfMarketAggregatedCollections` directly. Adaptive saturation recomputes every 60 s from the buffer's own size distribution at the configured percentile (default p99).
- `Palette.cs` — bid base (blue), ask base (orange), and the two ignition tones used by the above-saturation regime.
- `ChartPainter.cs` — the render pass. Persistent off-screen `Bitmap` cached across frames. Cache rebuild uses `LockBits` + raw `int*` writes; this is the *only* `unsafe` scope in the project.
- `L2_Heatmap.cs` — indicator entry point. Polls `Symbol.DepthOfMarket` each `OnUpdate` tick, feeds the buffer + capture writer. Subscribes to `Symbol.NewLevel2` only as a freshness heartbeat; subscribes to `Symbol.NewLast` for trade-tick capture. `[InputParameter]` fields surface in Quantower's settings dialog grouped via `SettingItemSeparatorGroup` — sortIndex 700-707 under "Liquidity Heatmap" and 720-724 under "Capture (L2 + Ticks → parquet)".
- `L2Capture.cs` — opt-in writer for L2 snapshots (top-200 each side, 1 Hz) and trade ticks. Both feed background flush task (10 s cadence) writing snappy-compressed parquet under `<OutputPath>/captures/<SYMBOL>/`. Decoupled from heatmap display path: separate snapshot cadence, no shared buffer. See [Capture](#capture-l2--ticks--parquet) below.

## Architectural invariants (do not break without thinking hard)

1. **No blocking on UI thread.** `Symbol_NewLevel2` heartbeat handler does only a timestamp write; sample + paint run on UI thread.
2. **Heartbeat ignores pseudo-L2.** Quantower can emit `generated_from_level1` / NaN pseudo-L2 events from L1 best-bid/ask changes. These do not prove the book stream is fresh and must not reset the stale timer.
3. **Read DOM, don't maintain state.** `Symbol.DepthOfMarket` is the canonical book — eats every L2 delta and every `DOMQuote` full-snapshot itself. Reading from it makes orphan-level corruption (the 2026-05-08 ref_tick bug class) structurally impossible. See RESEARCH_LOG 2026-05-08 follow-up for the migration narrative.
4. **Tick-keyed math.** Convert `Level2Item.Price` → `long` ticks via `(long)Math.Round(price / tickSize)` whenever you key by price. Float-equality across independently-computed prices breaks dictionary lookup otherwise.
5. **Forward-only.** No historical L2 — heatmap warms up over ~10 s as live data accumulates.
6. **Unsafe scope is exactly one method:** `ChartPainter.RebuildHeatmapBitmap`. LockBits + raw `int*` pixel writes give ~10× speedup vs per-cell `FillRectangle` (~30 ns/pixel vs ~300 ns/call). Don't extend unsafe further.
7. **Per-frame bitmap cache.** Cache invalidates on snapshot count change (every 500 ms in steady state), pan/zoom (firstX/lastX drift > 1 px), or rect resize. Cache hits are a single `g.DrawImage` blit (~1 ms); misses do the LockBits rebuild (~8 ms for ~200k cells).

## Two-regime alpha curve

Lives in `ChartPainter.WriteHeatmapCellPixels`. Given `t = size / sizeAtSat`:

- `t ≤ 1.0` → linear regime: `alpha = t × alphaMax`, color = base RGB (blue or orange).
- `t > 1.0` → ignition lift: `alpha = alphaMax + (t − 1) × IgnitionGain`, capped at `IgnitionAlphaCap`. Color swaps to the brighter ignition RGB.

Constants: `IgnitionGain = 130.0`, `IgnitionAlphaCap = 200`. Sub-saturation regime is pixel-identical to a plain linear curve. The `alphaMax >= IgnitionAlphaCap` short-circuit avoids the lift path when the user has already cranked alpha past the cap (no headroom to lift into).

## Adaptive saturation

When `Saturation Lot Count = 0` (default), the saturation point is recomputed every 60 s from the buffer's own distribution at `Adaptive Percentile` (default 0.99), filtered to cells that would actually paint (within window, above floor). Floored at `MinAdaptiveSaturation = 5.0` so a sparse book can't push it absurdly low. Needs ≥100 sampled cells before the first compute fires — quiet symbols can take a minute to warm up. Set `Saturation Lot Count` to a fixed positive value to bypass adaptive entirely.

## Right-edge extension

The newest snapshot's column is painted from its timestamp X all the way to the right edge of the chart paint rect (`xNext = W` in `RebuildHeatmapBitmap` when `idx == n - 1`). This makes the current resting book persist visually across the empty future area, matching Bookmap behavior. Cache invalidation already triggers on `lastX` drift > 1 px, so chart auto-scroll automatically redraws the rightmost column to the new edge.

## Cache update strategy: incremental-on-append

The cache-miss path branches on what kind of delta caused the invalidation:

- **Append-only delta** (`TryAppendIncremental` in `ChartPainter`): triggered when exactly one new snapshot was appended (and possibly one rolled off retention) AND the chart hasn't panned/zoomed. Only the leftmost rolloff slice and the rightmost extend-zone are cleared and the new last column is painted on top. Interior pixels are content-identical to the previous frame and skipped. Cost is independent of total snapshot count — proportional to the extend-zone width × H.
- **Full rebuild** (`RebuildHeatmapBitmap`): falls back here for pan, zoom, multi-snap deltas, rect resize, or anything else. Clears the whole bitmap and repaints every snapshot.

Why this matters: at 1-2 sec snapshot interval and 600 sec retention, the steady state is ~600 cache misses per 10 minutes. Almost all of them are pure "snap appended" events between bar boundaries (chart doesn't pan within a bar). Pre-incremental, every miss did O(snapCount) work; post-incremental, those misses do O(extend-zone-width × H) work — typically 20-50× cheaper. Full rebuilds still happen on pan/zoom and on new-bar boundaries (rare relative to snapshot ticks).

### Conditions for the incremental path (all must hold)

1. Previous frame state is cached (not first paint, not post-bitmap-recreation).
2. Snap count delta is `+1` with same `oldestT` (pure append) OR `0` with different `oldestT` AND different `newestT` (append + retention rolloff).
3. Snap count ≥ 2 (need a "previous last" to anchor the no-pan check).
4. The new second-to-last snap's `T` matches cached `newestT` — sanity that the OLD last is now at index `n-2`.
5. The OLD last snap's current X matches cached `lastX` within 1 px — no pan/zoom happened.
6. Pure-append additionally requires the oldest snap's X to match cached `firstX` within 1 px.
7. New last snap's X is on-screen (`0 < newLastX < W`).

Any failure → fall back to full rebuild. The cache state is updated identically in both paths so subsequent frames see consistent state.

### Why the interior region is safe to skip

In the previous frame, the OLD last snap painted from its X (call it `L_old`) to the chart right edge `W`. In the new frame, with no pan, the OLD last snap is still at `L_old` and the NEW last snap is to its right at `L_new`. The interior region `[L_old, L_new)` should now display the OLD last snap at its native column width. The pixels currently in that range are the OLD last snap's cells from when it was extended — *bit-identical* to what they should be at the narrower width (same cells, same Y positions, same colors). No paint needed. Only the area `[L_new, W)` changes (was OLD last extended → should be NEW last extended), so that's the only area we clear and repaint.

## Memory budget

Default 600 s × 2 Hz = 1200 snapshots × ~50 entries/side × 2 sides × ~16 bytes ≈ **~2 MB peak** for the snapshot buffer. Each snapshot is a `BookSnapshot` struct holding `(DateTime, refTick, Dictionary<long, double> bids, Dictionary<long, double> asks)`. Snapshots are independent dict clones — they don't share state with QT's DOM after capture.

## Settings dialog grouping

The `Settings` override on the indicator class wraps the eight `[InputParameter]` fields (sortIndex 700-707) in a `SettingItemSeparatorGroup("Liquidity Heatmap", 700)`. Without this override, Quantower renders the inputs ungrouped at the top of the dialog. `IList<SettingItem>` requires `using System.Collections.Generic;`.

## Display vs capture decoupling (post-2026-05-07)

The `Show Heatmap Painting` toggle (sortIndex 700, `LiquidityHeatmapEnabled` field) controls only the cloud overlay. **Capture is fully independent**: it consumes the `DepthOfMarket` snapshot directly each sample, not the heatmap buffer. So the standard deployment is:

- **Main trading chart**: `Show Heatmap Painting = false`. No clouds. Capture writes silently.
- **Spare chart** (optional, separate chart instance): `Show Heatmap Painting = true`. Visual study only.

When the toggle is false: `_heatmap` buffer is never created, `_painter.Heatmap` is null, and `ChartPainter.Paint` early-returns on the null check. Zero render cost, no snapshot-buffer memory (~7.7 MB peak savings), capture path untouched. Toggling to true via settings dialog triggers QT's standard re-init and the buffer rebuilds from live data.

Why the demotion: through three sessions of live use (2026-05-05 to 2026-05-07), the cloud overlay never drove a single decision. The events stream + LiquidityMeter cum/ROC carried the entire decision load. The new indicator suite (L2_Events, L2_Inflection, L2_Flow, L2_Supply_Layer) replaces the cloud's "where is supply/demand parked" intuition with discrete, timestamped, self-clearing markers. The capture path remains the data foundation for everything else; the cloud is now opt-in.

## Capture (L2 + Ticks → parquet)

Opt-in via `Capture Enabled`. When on, every `NewLevel2` drain pass also evaluates whether `CaptureSnapshotIntervalMs` has elapsed since the last capture; if so, the current `BookState` is sampled to a `SnapshotRow` and enqueued. `NewLast` events are subscribed only when capture is on, and each tick enqueues a `TickRow`. A background `Task` (kicked off in `OnInit`) wakes every 10 s and flushes the queues — appending a row group to the day's parquet file, snappy compression, day-partitioned files per symbol.

The capture queues are capped at 200k rows per stream. If the background writer falls behind, newest rows are dropped and a throttled log entry records the cumulative drop count. For primary research capture prefer `MarketRecorder`, which exposes drop counters in its on-chart status panel.

### File layout

```
<OutputPath>/captures/<SYMBOL>/
    snapshots-YYYY-MM-DD.parquet
    ticks-YYYY-MM-DD.parquet
```

`<OutputPath>` is the indicator deploy dir (`C:\Quantower\Settings\Scripts\Indicators\L2_Heatmap\`). `<SYMBOL>` is `Symbol.Name`, sanitized for path use.

### Schemas

**Snapshots** — flat columns, 800 cols + ts + ref_tick = 802 cols total.

| Column | Type | Notes |
|---|---|---|
| `timestamp_us` | int64 | Microseconds since Unix epoch (UTC) |
| `ref_tick` | int64 | Mid-tick: `(best_bid_tick + best_ask_tick) / 2` |
| `bid_offset_0..199` | int32 | Signed tick offset from `ref_tick` (negative for bids) |
| `bid_size_0..199` | double | Resting size at that level |
| `ask_offset_0..199` | int32 | Signed tick offset from `ref_tick` (positive for asks) |
| `ask_size_0..199` | double | Resting size at that level |

Empty levels store `offset=0, size=0`. Filter `size > 0` on read to recover real levels.

Schema bumped 2026-05-09 from 50→200 levels each side (50 NQ price points). Captures from 2026-05-04 → 2026-05-08 use the prior 50-level schema; per-file readable but not concat-able with new files. Those days are early experimental data and intentionally not preserved under the new schema.

**Ticks** — 4 columns.

| Column | Type | Notes |
|---|---|---|
| `timestamp_us` | int64 | Microseconds since Unix epoch (UTC) |
| `price` | double | Trade price |
| `size` | double | Trade size |
| `aggressor_sign` | int32 | `+1` Buy, `-1` Sell, `0` Unknown/NotSet |

### Why flat over list-typed columns

800-column flat schema is fatter on schema definition but trivially ergonomic on read in Polars/pandas — direct column access for distance-distribution analysis (e.g. distance-weighted depth aggregates), no list-API gymnastics. Snappy compression flattens the cost difference at rest (most far-from-mid columns will be empty most of the time and compress near-trivially).

### Retention

`CleanupOldFiles` runs at `OnInit` when capture is on: any `*.parquet` under the symbol's capture dir whose last-write time is older than `CaptureRetentionDays` is deleted. Default 30 days.

### Throughput sanity

NQ during RTH: ~3000 L2 events/sec ceiling, drain processes them on UI thread; capturing one snapshot/sec is one row enqueued per second. Tick rate similar order. Buffered queue + 10 s flush cadence means the writer task does ~10 snapshot rows + a few hundred tick rows per write — well under any IO concern. Disk: ~150–300 KB/hour/symbol for snapshots after Snappy compression; ticks similar. 30 days × ~7 RTH hours/day ≈ 60 MB per symbol total.

### Why decoupled from display snapshot path

The heatmap's `LiquidityHeatmapBuffer` snapshots at 2 Hz tied to display retention (default 600 s) — sampling rate optimized for visual smoothness, not analytical stability. Research wants stable wall-clock-aligned cadence regardless of display config. Two snapshot rate gates, both reading the same `DepthOfMarket` source.

### Deployed package DLLs

`<CopyLocalLockFileAssemblies>true</CopyLocalLockFileAssemblies>` in the csproj copies Parquet.Net + transitives (`Parquet.dll`, `IronCompress.dll`, `Snappier.dll`, `ZstdSharp.dll`, `Microsoft.IO.RecyclableMemoryStream.dll`) plus the `runtimes/` folder for native compression bits. ~10 MB total deploy. The non-Windows runtime folders are unused but harmless.

## Build & deploy

```
dotnet build
```

DLL drops at `C:\Quantower\Settings\Scripts\Indicators\L2_Heatmap\L2_Heatmap.dll`. Restart Quantower (it caches indicator DLLs on startup) → right-click chart → Indicators → Add Indicator → search "L2 Heatmap".

### Known build gotcha

Since the 2026-05-09 Option-A refactor we no longer touch `Level2Quote.PriceType` directly — QT's `DepthOfMarket` handles that internally. The `using TradingPlatform.BusinessLayer.Integration;` quirk noted in root CLAUDE.md is no longer needed in this project's source files.

## Verification

Symbol must have L2 access (NQ, ES, MNQ, MES, CL — futures with confirmed L2). Within ~10 s of adding the indicator the heatmap appears. If it stays empty after a minute on a quiet symbol, set `Saturation Lot Count` to a fixed value (e.g. 25) to bypass adaptive warmup.
