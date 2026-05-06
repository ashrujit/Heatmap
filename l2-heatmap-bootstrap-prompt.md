# L2 Heatmap Indicator — Bootstrap Prompt

**Paste this entire file as the first message to a fresh Claude Code session running in an empty directory. Use Auto / Plan / Default mode — your choice. The session will ask you a few setup questions, then create a Quantower indicator project from scratch and build it. Toolchain required on your machine: .NET 8 SDK and Quantower. No Visual Studio / Rider / any IDE is needed — `dotnet build` from the terminal is the entire build step; the project files (`.csproj`, `.cs`) are plain text Claude writes for you.**

---

## What you're building

A Quantower indicator DLL that displays a Bookmap-style **L2 liquidity heatmap** as a chart backdrop and nothing else. Live `NewLevel2` deltas feed a mutable in-memory book; rolling N-minute snapshots of that book are sampled at ~2 Hz; each snapshot becomes a column of bid (blue) and ask (orange) cells whose alpha scales with size. A two-regime alpha curve lifts cells past the saturation point with a brighter "ignition" tone so the top tail of the size distribution unfolds into a visible gradient instead of clamping flat.

This is a port of the heatmap subsystem from a larger Quantower indicator project (Skurry_Scribe). Only the heatmap layer — none of the detectors, event log, SQLite, or aftermath tracking. Display-only.

## Out of scope (do NOT build)

- Event log / JSONL / SQLite / any persistence layer
- Detectors (sweep, walls, hidden liquidity, iceberg, reload zones, etc.)
- Bootstrap probing / capability gates / graceful-degradation logging
- Tick recording / replay / backfill
- Aftermath or magnet registries
- Backtest harness or test projects

## Architectural invariants (copied from the parent project)

1. **No blocking on UI thread.** `Symbol.NewLevel2` callback enqueues into a `ConcurrentQueue<Level2Quote>`. Drain happens on the UI thread inside `OnUpdate`. `OnPaintChart` is also UI-thread.
2. **`BookState` keys are LONG ticks, not doubles.** Use `PriceToTicks(double price)` / `TicksToPrice(long ticks)`. Float-equality across independently-computed prices breaks dictionary lookup otherwise.
3. **Quantower synthesizes pseudo-L2 events** from L1 best-bid/ask changes with `id="generated_from_level1"` and NaN price/size. `BookState.Apply` must skip them.
4. **Forward-only.** No historical L2. Heatmap fills as live data arrives — expect a ~10-second warmup before the backdrop appears.
5. **Unsafe code is scoped to ONE method** (`ChartPainter.RebuildHeatmapBitmap`). LockBits + raw `int*` pixel writes give a ~10× speedup vs per-cell `FillRectangle`. Don't extend the unsafe scope.
6. **Per-frame bitmap cache.** Cache invalidates on snapshot count change (every 500 ms), pan/zoom (firstX/lastX drift > 1 px), or rect resize. Cache hits are a single `g.DrawImage` blit (~1 ms); misses do the LockBits rebuild (~8 ms for 200k cells).

## Step 0 — Discover the environment

Before writing any files, ask the user (the human running this Claude session) for the following. Use `AskUserQuestion` if available, otherwise plain prompts.

### Q1 — Quantower install root

Default: `C:\Quantower`. The directory containing `TradingPlatform\v<version>\bin\TradingPlatform.BusinessLayer.dll`.

After the user answers, verify and resolve the version subdir:

```pwsh
$qtRoot = "<user-supplied-path>"
$tpDir = Get-ChildItem "$qtRoot\TradingPlatform" -Directory | Where-Object { $_.Name -like "v*" } | Select-Object -First 1
if (-not $tpDir) { throw "No TradingPlatform\v* subdir under $qtRoot" }
$qtVersion = $tpDir.Name           # e.g. "v1.145.13"
$qtBlDll = "$qtRoot\TradingPlatform\$qtVersion\bin\TradingPlatform.BusinessLayer.dll"
if (-not (Test-Path $qtBlDll)) { throw "BusinessLayer DLL not at $qtBlDll" }
$qtIndicatorsDir = "$qtRoot\Settings\Scripts\Indicators"
if (-not (Test-Path $qtIndicatorsDir)) { throw "Quantower indicators dir not at $qtIndicatorsDir" }
```

### Q2 — api-recon folder

Default: `<parent-of-current-cwd>\api-recon`. The directory containing `REPORT.md` and `src/` with Quantower API reference materials. Verify with `Test-Path "$apiReconDir\REPORT.md"`. **You don't need to read the api-recon contents to build this indicator** — every Quantower API used here is reproduced verbatim below. The path is captured only so it's available if you (Claude) need to look up an unrelated API later.

### Q3 — Project / indicator name

Default: `L2_Heatmap`. Used for the assembly name, the deploy folder under Quantower's `Indicators\`, and the indicator name shown in the right-click menu. C# identifier: same string with non-ASCII / spaces replaced by underscores. Default works as-is.

### Q4 — Verify .NET 8 SDK

```pwsh
dotnet --version
```

Must return `8.x.x`. If not installed, instruct the user to install the .NET 8 SDK from https://dotnet.microsoft.com/download/dotnet/8.0 and retry. Do not proceed otherwise.

---

## Step 1 — Write the project file

Filename: `<ProjectName>.csproj` in the empty project directory. Substitute `__QT_ROOT__`, `__QT_VERSION__`, `__PROJECT_NAME__` from the answers above.

```xml
<?xml version="1.0" encoding="utf-8"?>
<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup>
    <TargetFramework>net8-windows</TargetFramework>
    <UseWindowsForms>true</UseWindowsForms>
    <LangVersion>latest</LangVersion>
    <AppendTargetFrameworkToOutputPath>false</AppendTargetFrameworkToOutputPath>
    <Platforms>AnyCPU</Platforms>
    <AlgoType>Indicator</AlgoType>
    <AssemblyName>__PROJECT_NAME__</AssemblyName>
    <RootNamespace>__PROJECT_NAME__</RootNamespace>
    <!-- Scoped to ChartPainter.RebuildHeatmapBitmap (LockBits + int* pixel writes). -->
    <AllowUnsafeBlocks>true</AllowUnsafeBlocks>
  </PropertyGroup>
  <PropertyGroup Condition="'$(Configuration)|$(Platform)'=='Debug|AnyCPU'">
    <OutputPath>__QT_ROOT__\Settings\Scripts\Indicators\__PROJECT_NAME__</OutputPath>
  </PropertyGroup>
  <PropertyGroup Condition="'$(Configuration)|$(Platform)'=='Release|AnyCPU'">
    <OutputPath>__QT_ROOT__\Settings\Scripts\Indicators\__PROJECT_NAME__</OutputPath>
  </PropertyGroup>
  <ItemGroup>
    <Reference Include="TradingPlatform.BusinessLayer">
      <HintPath>__QT_ROOT__\TradingPlatform\__QT_VERSION__\bin\TradingPlatform.BusinessLayer.dll</HintPath>
      <Private>False</Private>
    </Reference>
  </ItemGroup>
</Project>
```

After substitution, paths look like:
- `OutputPath` → `C:\Quantower\Settings\Scripts\Indicators\L2_Heatmap`
- `HintPath` → `C:\Quantower\TradingPlatform\v1.145.13\bin\TradingPlatform.BusinessLayer.dll`

---

## Step 2 — Write the source files

All files share the namespace `__PROJECT_NAME__` (e.g. `L2_Heatmap`). Substitute consistently.

### File `BookState.cs`

Mutable in-memory book maintained by consuming `NewLevel2` deltas. Tick-keyed dictionaries (long, not double — fixes float-equality bugs). Bids sorted descending (best bid first); asks sorted ascending (best ask first). Aggregated and MBO feeds both go through the same code path because `lvl.Ids` is a `HashSet<string>` — MBO has unique order Ids per order; aggregated reuses Ids per price level.

```csharp
using System;
using System.Collections.Generic;
using TradingPlatform.BusinessLayer;

namespace __PROJECT_NAME__
{
    public sealed class BookState
    {
        private readonly double _tickSize;
        private readonly Dictionary<string, OrderEntry> _orders = new();
        private readonly SortedDictionary<long, PriceLevel> _bids =
            new(Comparer<long>.Create((a, b) => b.CompareTo(a))); // descending: best bid first
        private readonly SortedDictionary<long, PriceLevel> _asks = new(); // ascending: best ask first

        public BookState(double tickSize)
        {
            _tickSize = tickSize > 0 ? tickSize : 0.25;
        }

        public double TickSize => _tickSize;
        public IReadOnlyDictionary<long, PriceLevel> BidsByTick => _bids;
        public IReadOnlyDictionary<long, PriceLevel> AsksByTick => _asks;

        public long PriceToTicks(double price) => (long)Math.Round(price / _tickSize);
        public double TicksToPrice(long ticks) => ticks * _tickSize;

        public void Clear()
        {
            _orders.Clear();
            _bids.Clear();
            _asks.Clear();
        }

        public void Apply(Level2Quote q)
        {
            if (q == null || string.IsNullOrEmpty(q.Id)) return;
            // Skip Quantower's pseudo-L2 events synthesized from L1 best-bid/ask changes
            // (id="generated_from_level1", NaN price/size).
            if (double.IsNaN(q.Price) || double.IsNaN(q.Size)) return;

            bool isBid = q.PriceType == QuotePriceType.Bid;
            var side = isBid ? _bids : _asks;
            _orders.TryGetValue(q.Id, out var prior);

            // Closed → remove the prior contribution at the prior price.
            if (q.Closed)
            {
                if (prior.Size > 0)
                {
                    long priorTicks = PriceToTicks(prior.Price);
                    if (side.TryGetValue(priorTicks, out var lvl))
                    {
                        lvl.TotalSize -= prior.Size;
                        lvl.Ids.Remove(q.Id);
                        if (lvl.TotalSize <= 0 || lvl.Ids.Count == 0) side.Remove(priorTicks);
                    }
                }
                _orders.Remove(q.Id);
                return;
            }

            // Update _orders BEFORE mutating the side map (re-entrant defense).
            long newTicks = PriceToTicks(q.Price);
            if (q.Size > 0)
                _orders[q.Id] = new OrderEntry { Price = q.Price, Size = q.Size, IsBid = isBid };
            else
                _orders.Remove(q.Id);

            // Remove prior contribution (same price = modify-in-place, different = move).
            if (prior.Size > 0)
            {
                long priorTicks = PriceToTicks(prior.Price);
                if (side.TryGetValue(priorTicks, out var priorLvl))
                {
                    priorLvl.TotalSize -= prior.Size;
                    if (priorTicks != newTicks)
                    {
                        priorLvl.Ids.Remove(q.Id);
                        if (priorLvl.TotalSize <= 0 || priorLvl.Ids.Count == 0)
                            side.Remove(priorTicks);
                    }
                    else if (priorLvl.TotalSize < 0)
                    {
                        // Defensive clamp — feed-delivery edge case (two removes before an add).
                        priorLvl.TotalSize = 0;
                    }
                }
            }

            if (q.Size > 0)
            {
                if (!side.TryGetValue(newTicks, out var newLvl))
                {
                    newLvl = new PriceLevel { Price = q.Price };
                    side[newTicks] = newLvl;
                }
                newLvl.TotalSize += q.Size;
                newLvl.Ids.Add(q.Id);
            }
        }

        public sealed class PriceLevel
        {
            public double Price;
            public double TotalSize;
            public HashSet<string> Ids = new();
        }

        public struct OrderEntry
        {
            public double Price;
            public double Size;
            public bool IsBid;
        }
    }
}
```

### File `LiquidityHeatmapBuffer.cs`

Bookmap-inspired rolling N-minute history of order-book snapshots, sampled at ~`SnapshotIntervalMs` cadence. Fed from the L2 drain right after `BookState.Apply`. Adaptive saturation point recomputes every 60 s from the buffer's own size distribution at the configured percentile (default p99). Single-threaded — same drain thread that mutates `BookState`.

Memory budget at default 600 s × 2 Hz = 1200 snapshots × ~200 entries/side × 2 sides × ~16 bytes ≈ 7.7 MB peak.

```csharp
using System;
using System.Collections.Generic;

namespace __PROJECT_NAME__
{
    public sealed class LiquidityHeatmapBuffer
    {
        public readonly struct BookSnapshot
        {
            public readonly DateTime T;
            public readonly long RefTick;
            public readonly Dictionary<long, double> BidsByTick;
            public readonly Dictionary<long, double> AsksByTick;

            public BookSnapshot(DateTime t, long refTick,
                Dictionary<long, double> bids, Dictionary<long, double> asks)
            {
                T = t; RefTick = refTick;
                BidsByTick = bids; AsksByTick = asks;
            }
        }

        public const int AdaptiveRecomputeIntervalSec = 60;
        // Floor for adaptive saturation so a sparse book can't push it absurdly low.
        public const double MinAdaptiveSaturation = 5.0;

        private readonly double _tickSize;
        private readonly int _retentionSec;
        private readonly int _snapshotIntervalMs;
        private readonly int _alphaMax;
        private readonly double _sizeFloor;
        private readonly double _levelsWindowPoints;
        // > 0 → use directly. = 0 → adaptive from buffer's own size distribution.
        private readonly double _sizeAtSaturationOverride;
        private readonly double _adaptivePercentile;

        private readonly Queue<BookSnapshot> _snapshots = new();
        private DateTime _lastSnapshotUtc = DateTime.MinValue;
        private DateTime _lastRecomputeUtc = DateTime.MinValue;
        private double _effectiveSaturation;

        public LiquidityHeatmapBuffer(
            double tickSize, int retentionSec, int snapshotIntervalMs,
            int alphaMax, double sizeFloor, double levelsWindowPoints,
            double sizeAtSaturationOverride, double adaptivePercentile)
        {
            _tickSize = tickSize > 0 ? tickSize : 0.25;
            _retentionSec = retentionSec > 0 ? retentionSec : 600;
            _snapshotIntervalMs = snapshotIntervalMs > 0 ? snapshotIntervalMs : 500;
            _alphaMax = alphaMax > 0 ? Math.Min(255, alphaMax) : 70;
            _sizeFloor = sizeFloor >= 0 ? sizeFloor : 1.0;
            _levelsWindowPoints = levelsWindowPoints > 0 ? levelsWindowPoints : 50.0;
            _sizeAtSaturationOverride = sizeAtSaturationOverride >= 0 ? sizeAtSaturationOverride : 0;
            _adaptivePercentile = adaptivePercentile > 0
                ? Math.Min(0.999, Math.Max(0.5, adaptivePercentile))
                : 0.99;
            _effectiveSaturation = _sizeAtSaturationOverride > 0
                ? _sizeAtSaturationOverride
                : 25.0; // sensible fallback until first adaptive recompute
        }

        public double TickSize => _tickSize;
        public int AlphaMax => _alphaMax;
        public double SizeFloor => _sizeFloor;
        public double LevelsWindowPoints => _levelsWindowPoints;
        public bool IsAdaptive => _sizeAtSaturationOverride <= 0;
        public double EffectiveSaturation => _effectiveSaturation;
        public IReadOnlyCollection<BookSnapshot> Snapshots => _snapshots;

        // NQ/ES (tick 0.25) at 50 points → 200 ticks each side.
        public int LevelsWindowTicks => (int)Math.Round(_levelsWindowPoints / _tickSize);

        // Throttled book-snapshot capture. Called from the L2 drain right after BookState.Apply.
        public void OnPostApply(BookState book, DateTime nowUtc)
        {
            if (book == null) return;
            if (_lastSnapshotUtc != DateTime.MinValue
                && (nowUtc - _lastSnapshotUtc).TotalMilliseconds < _snapshotIntervalMs) return;
            _lastSnapshotUtc = nowUtc;

            // Mid-of-book reference tick (or whichever side exists).
            long bestBid = long.MinValue, bestAsk = long.MaxValue;
            foreach (var kv in book.BidsByTick) { bestBid = kv.Key; break; }
            foreach (var kv in book.AsksByTick) { bestAsk = kv.Key; break; }
            long refTick;
            if (bestBid != long.MinValue && bestAsk != long.MaxValue) refTick = (bestBid + bestAsk) / 2;
            else if (bestBid != long.MinValue) refTick = bestBid;
            else if (bestAsk != long.MaxValue) refTick = bestAsk;
            else return;

            // Clone size-by-tick views so the snapshot is independent of further BookState mutation.
            var bids = new Dictionary<long, double>(book.BidsByTick.Count);
            foreach (var kv in book.BidsByTick) bids[kv.Key] = kv.Value.TotalSize;
            var asks = new Dictionary<long, double>(book.AsksByTick.Count);
            foreach (var kv in book.AsksByTick) asks[kv.Key] = kv.Value.TotalSize;

            _snapshots.Enqueue(new BookSnapshot(nowUtc, refTick, bids, asks));

            DateTime cutoff = nowUtc.AddSeconds(-_retentionSec);
            while (_snapshots.Count > 0 && _snapshots.Peek().T < cutoff)
                _snapshots.Dequeue();

            if (_lastRecomputeUtc == DateTime.MinValue)
            {
                _lastRecomputeUtc = nowUtc;
            }
            else if ((nowUtc - _lastRecomputeUtc).TotalSeconds >= AdaptiveRecomputeIntervalSec)
            {
                UpdateAdaptiveSaturation();
                _lastRecomputeUtc = nowUtc;
            }
        }

        public void Clear()
        {
            _snapshots.Clear();
            _lastSnapshotUtc = DateTime.MinValue;
            _lastRecomputeUtc = DateTime.MinValue;
            _effectiveSaturation = _sizeAtSaturationOverride > 0
                ? _sizeAtSaturationOverride
                : 25.0;
        }

        // Recompute adaptive saturation from the buffer's own size distribution at the
        // configured percentile. Filtered to cells that would actually paint (within
        // window, above floor). Floored at MinAdaptiveSaturation.
        private void UpdateAdaptiveSaturation()
        {
            if (_sizeAtSaturationOverride > 0)
            {
                _effectiveSaturation = _sizeAtSaturationOverride;
                return;
            }
            if (_snapshots.Count == 0) return;

            int windowTicks = LevelsWindowTicks;
            var sizes = new List<double>(_snapshots.Count * 200);

            foreach (var snap in _snapshots)
            {
                long refTick = snap.RefTick;
                foreach (var kv in snap.BidsByTick)
                {
                    if (kv.Value < _sizeFloor) continue;
                    if (Math.Abs(kv.Key - refTick) > windowTicks) continue;
                    sizes.Add(kv.Value);
                }
                foreach (var kv in snap.AsksByTick)
                {
                    if (kv.Value < _sizeFloor) continue;
                    if (Math.Abs(kv.Key - refTick) > windowTicks) continue;
                    sizes.Add(kv.Value);
                }
            }

            if (sizes.Count < 100) return; // not enough data to trust the percentile

            sizes.Sort();
            int idx = (int)Math.Floor(_adaptivePercentile * (sizes.Count - 1));
            if (idx < 0) idx = 0;
            if (idx >= sizes.Count) idx = sizes.Count - 1;
            _effectiveSaturation = Math.Max(MinAdaptiveSaturation, sizes[idx]);
        }
    }
}
```

### File `Palette.cs`

```csharp
using System.Drawing;

namespace __PROJECT_NAME__
{
    public static class Palette
    {
        // Bid = blue family; ask = orange family. Base tone for sub-saturation cells;
        // ignition tone for cells that exceed the saturation point (lifted alpha).
        public static readonly Color HeatmapBidBase     = Color.FromArgb(255,  80, 170, 230);
        public static readonly Color HeatmapAskBase     = Color.FromArgb(255, 230, 130,  90);
        public static readonly Color HeatmapBidIgnition = Color.FromArgb(255, 160, 220, 255);
        public static readonly Color HeatmapAskIgnition = Color.FromArgb(255, 255, 200, 130);
    }
}
```

### File `ChartPainter.cs`

The render pass. Persistent off-screen `Bitmap` cached across frames; rebuilt on snapshot adds, pan/zoom, or rect resize. Rebuild uses `LockBits` + raw `int*` writes for ~10× speedup. Two-regime alpha curve described inline.

```csharp
using System;
using System.Collections.Generic;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Drawing.Imaging;
using TradingPlatform.BusinessLayer;
using TradingPlatform.BusinessLayer.Chart;

namespace __PROJECT_NAME__
{
    public sealed class ChartPainter : IDisposable
    {
        // ── Heatmap bitmap caching ─────────────────────────────────────────
        // Persistent off-screen Bitmap matching the current chart rect dims.
        // Most paint frames are cache hits (single g.DrawImage blit, ~1ms).
        // Cache misses (snapshot adds, pan/zoom) trigger RebuildHeatmapBitmap
        // which uses LockBits + raw int* pixel writes for ~10× speedup over
        // per-cell FillRectangle. Net: paint p50 ~1.5ms (was 75ms).
        private Bitmap _heatmapBitmap;
        private int _heatmapBitmapW, _heatmapBitmapH;
        private int _heatmapCachedSnapCount;
        private DateTime _heatmapCachedNewestT;
        private DateTime _heatmapCachedOldestT;
        private double _heatmapCachedFirstX;
        private double _heatmapCachedLastX;
        private bool _disposed;

        // Two-regime alpha lift constants. Sub-saturation regime is the
        // original linear curve. Above-saturation regime lifts alpha by
        // IgnitionGain per t-unit, capped at IgnitionAlphaCap, with the
        // color swapped to the brighter ignition tone.
        private const double IgnitionGain = 130.0;
        private const int IgnitionAlphaCap = 200;

        public LiquidityHeatmapBuffer Heatmap { get; set; }

        public void Dispose()
        {
            if (_disposed) return;
            _disposed = true;
            _heatmapBitmap?.Dispose();
            _heatmapBitmap = null;
        }

        public void Paint(PaintChartEventArgs args, IChart currentChart)
        {
            if (currentChart == null || Heatmap == null) return;
            var g = args.Graphics;
            var converter = currentChart.MainWindow.CoordinatesConverter;
            var rect = args.Rectangle;
            g.SmoothingMode = SmoothingMode.AntiAlias;
            DrawLiquidityHeatmapCached(g, converter, rect, Heatmap);
        }

        // Bookmap-inspired liquidity heatmap. Painted as the chart backdrop.
        // Each retained book snapshot is one column; each (tick, size) entry
        // is one cell whose alpha scales with size (capped). Bid cells use
        // HeatmapBidBase RGB (blue), ask uses HeatmapAskBase (orange).
        private void DrawLiquidityHeatmapCached(Graphics g,
            IChartWindowCoordinatesConverter cv, Rectangle rect,
            LiquidityHeatmapBuffer heatmap)
        {
            var snapshots = heatmap.Snapshots;
            if (snapshots.Count == 0 || rect.Width <= 0 || rect.Height <= 0) return;

            // Recreate bitmap if rect dimensions changed (chart resize).
            if (_heatmapBitmap == null
                || _heatmapBitmapW != rect.Width
                || _heatmapBitmapH != rect.Height)
            {
                _heatmapBitmap?.Dispose();
                _heatmapBitmap = new Bitmap(rect.Width, rect.Height, PixelFormat.Format32bppArgb);
                _heatmapBitmapW = rect.Width;
                _heatmapBitmapH = rect.Height;
                _heatmapCachedSnapCount = -1; // force rebuild
            }

            // Identify cache-invalidating state. Walk the queue once for
            // count + oldest T (head) + newest T (tail).
            DateTime newestT = default, oldestT = default;
            int snapCount = 0;
            foreach (var s in snapshots)
            {
                if (snapCount == 0) oldestT = s.T;
                newestT = s.T;
                snapCount++;
            }

            // Geometry signature: pixel-X of oldest and newest snapshot. If
            // chart auto-scrolls, pans, or zooms, these drift, indicating the
            // cached bitmap's pixel positions no longer match chart coords.
            double firstX = cv.GetChartX(oldestT) - rect.Left;
            double lastX = cv.GetChartX(newestT) - rect.Left;

            bool needsRebuild =
                _heatmapCachedSnapCount != snapCount
                || _heatmapCachedNewestT != newestT
                || _heatmapCachedOldestT != oldestT
                || Math.Abs(firstX - _heatmapCachedFirstX) > 1
                || Math.Abs(lastX - _heatmapCachedLastX) > 1;

            if (needsRebuild)
            {
                RebuildHeatmapBitmap(cv, rect, heatmap, snapshots, snapCount);
                _heatmapCachedSnapCount = snapCount;
                _heatmapCachedNewestT = newestT;
                _heatmapCachedOldestT = oldestT;
                _heatmapCachedFirstX = firstX;
                _heatmapCachedLastX = lastX;
            }

            g.DrawImage(_heatmapBitmap, rect.Left, rect.Top);
        }

        // Rebuild the cached bitmap via LockBits + raw pointer writes. Skips
        // GDI+ FillRectangle entirely — direct memory writes per cell pixel,
        // ~30ns/pixel vs ~300ns/FillRectangle call.
        private unsafe void RebuildHeatmapBitmap(
            IChartWindowCoordinatesConverter cv, Rectangle rect,
            LiquidityHeatmapBuffer heatmap,
            IReadOnlyCollection<LiquidityHeatmapBuffer.BookSnapshot> snapshots,
            int snapCount)
        {
            int W = _heatmapBitmapW;
            int H = _heatmapBitmapH;
            double tickSize = heatmap.TickSize;
            int window = heatmap.LevelsWindowTicks;
            int alphaMax = heatmap.AlphaMax;
            double sizeAtSat = heatmap.EffectiveSaturation;
            double sizeFloor = heatmap.SizeFloor;
            Color bidBase = Palette.HeatmapBidBase;
            Color askBase = Palette.HeatmapAskBase;
            Color bidIgn = Palette.HeatmapBidIgnition;
            Color askIgn = Palette.HeatmapAskIgnition;

            // Materialize so we can peek next-T to compute column widths.
            var arr = new LiquidityHeatmapBuffer.BookSnapshot[snapCount];
            int n = 0;
            foreach (var s in snapshots) { if (n >= snapCount) break; arr[n++] = s; }

            var bmpRect = new Rectangle(0, 0, W, H);
            BitmapData data = _heatmapBitmap.LockBits(
                bmpRect, ImageLockMode.WriteOnly, PixelFormat.Format32bppArgb);
            try
            {
                byte* scan0 = (byte*)data.Scan0;
                int stride = data.Stride;

                // Clear to transparent — we OVERWRITE per cell, no alpha-composite,
                // so the previous frame's pixels would otherwise leak through.
                for (int y = 0; y < H; y++)
                {
                    int* row = (int*)(scan0 + y * stride);
                    for (int x = 0; x < W; x++) row[x] = 0;
                }

                int bidR = bidBase.R, bidG = bidBase.G, bidB = bidBase.B;
                int askR = askBase.R, askG = askBase.G, askB = askBase.B;
                int bidIgnR = bidIgn.R, bidIgnG = bidIgn.G, bidIgnB = bidIgn.B;
                int askIgnR = askIgn.R, askIgnG = askIgn.G, askIgnB = askIgn.B;

                for (int idx = 0; idx < n; idx++)
                {
                    var snap = arr[idx];
                    int x = (int)cv.GetChartX(snap.T) - rect.Left;
                    int xNext = (idx + 1 < n)
                        ? ((int)cv.GetChartX(arr[idx + 1].T) - rect.Left)
                        : x + 3;

                    // Column X-cull (in bitmap-relative coords).
                    if (xNext < 0 || x >= W) continue;
                    int colX = x < 0 ? 0 : x;
                    int colRight = xNext > W ? W : xNext;
                    if (colRight <= colX) continue;

                    long refTick = snap.RefTick;

                    foreach (var kv in snap.BidsByTick)
                    {
                        if (Math.Abs(kv.Key - refTick) > window) continue;
                        WriteHeatmapCellPixels(scan0, stride, W, H,
                            kv.Key, kv.Value, tickSize, colX, colRight,
                            bidR, bidG, bidB, bidIgnR, bidIgnG, bidIgnB,
                            alphaMax, sizeAtSat, sizeFloor, cv, rect);
                    }
                    foreach (var kv in snap.AsksByTick)
                    {
                        if (Math.Abs(kv.Key - refTick) > window) continue;
                        WriteHeatmapCellPixels(scan0, stride, W, H,
                            kv.Key, kv.Value, tickSize, colX, colRight,
                            askR, askG, askB, askIgnR, askIgnG, askIgnB,
                            alphaMax, sizeAtSat, sizeFloor, cv, rect);
                    }
                }
            }
            finally
            {
                _heatmapBitmap.UnlockBits(data);
            }
        }

        // Write one cell's pixels directly into the bitmap's locked memory.
        // Two-regime curve:
        //   t = size / sizeAtSat
        //   t ≤ 1.0  → alpha = t × alphaMax,             color = base RGB
        //   t > 1.0  → alpha = alphaMax + (t−1) × IgnitionGain (capped at IgnitionAlphaCap),
        //              color = ignition RGB
        // Sub-saturation regime is pixel-identical to a plain linear curve. The
        // above-saturation regime lifts alpha and swaps to the brighter tone so
        // the top tail of the size distribution unfolds into a visible gradient
        // instead of clamping flat.
        //
        // Cells overlap with last-write-wins semantics. In practice cells from a
        // single snapshot don't overlap (different prices = different Y), and
        // cross-snapshot overlap is limited to adjacent column edges.
        private static unsafe void WriteHeatmapCellPixels(
            byte* scan0, int stride, int W, int H,
            long tick, double size, double tickSize,
            int colX, int colRight,
            int r, int g, int b, int ignR, int ignG, int ignB,
            int alphaMax, double sizeAtSat, double sizeFloor,
            IChartWindowCoordinatesConverter cv, Rectangle rect)
        {
            if (size < sizeFloor) return;

            double price = tick * tickSize;
            int yMid = (int)cv.GetChartY(price) - rect.Top;
            int yPrev = (int)cv.GetChartY(price - tickSize) - rect.Top;
            int cellH = Math.Max(1, Math.Abs(yPrev - yMid));
            int yTop = yMid - cellH / 2;
            int yBot = yTop + cellH;

            // Y-axis cull + clip to bitmap bounds.
            if (yBot <= 0 || yTop >= H) return;
            if (yTop < 0) yTop = 0;
            if (yBot > H) yBot = H;

            int alpha;
            int rUse, gUse, bUse;
            double t = size / sizeAtSat;
            if (t <= 1.0 || alphaMax >= IgnitionAlphaCap)
            {
                // Sub-saturation regime: original linear curve, base color.
                alpha = (int)(t * alphaMax);
                if (alpha > alphaMax) alpha = alphaMax;
                rUse = r; gUse = g; bUse = b;
            }
            else
            {
                // Above-saturation lift: alpha climbs from alphaMax toward
                // IgnitionAlphaCap; color swaps to the brighter ignition tone.
                alpha = alphaMax + (int)((t - 1.0) * IgnitionGain);
                if (alpha > IgnitionAlphaCap) alpha = IgnitionAlphaCap;
                rUse = ignR; gUse = ignG; bUse = ignB;
            }
            if (alpha <= 0) return;

            // ARGB32 packed: 0xAARRGGBB (alpha in MSB, then R, G, B).
            int pixel = (alpha << 24) | (rUse << 16) | (gUse << 8) | bUse;

            for (int y = yTop; y < yBot; y++)
            {
                int* row = (int*)(scan0 + y * stride);
                for (int x = colX; x < colRight; x++) row[x] = pixel;
            }
        }
    }
}
```

### File `__PROJECT_NAME__.cs` (the indicator class)

The Quantower entry point. Class name MUST match the assembly name with C#-identifier rules. Indicator subscribes to `Symbol.NewLevel2` in `OnInit`, drains in `OnUpdate`, paints in `OnPaintChart`, unsubscribes in `OnClear`.

```csharp
using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using TradingPlatform.BusinessLayer;

namespace __PROJECT_NAME__
{
    public class __PROJECT_NAME__ : Indicator
    {
        private const string IndicatorVersion = "0.1.0";

        // ── Liquidity Heatmap (sortIndex 700-707) ───────────────────────────
        [InputParameter("Liquidity Heatmap Enabled", sortIndex: 700)]
        public bool LiquidityHeatmapEnabled = true;

        [InputParameter("Retention (sec)", sortIndex: 701,
            minimum: 60, maximum: 3600, increment: 60, decimalPlaces: 0)]
        public int LiquidityHeatmapRetentionSec = 600;

        [InputParameter("Snapshot Interval (ms)", sortIndex: 702,
            minimum: 100, maximum: 5000, increment: 100, decimalPlaces: 0)]
        public int LiquidityHeatmapSnapshotIntervalMs = 500;

        [InputParameter("Levels Window (price points each side)", sortIndex: 703,
            minimum: 1, maximum: 1000, increment: 1, decimalPlaces: 1)]
        public double LiquidityHeatmapLevelsWindowPoints = 50.0;

        [InputParameter("Size Floor (skip cells below this)", sortIndex: 704,
            minimum: 0, maximum: 100, increment: 1, decimalPlaces: 1)]
        public double LiquidityHeatmapSizeFloor = 1.0;

        [InputParameter("Alpha Max (cell saturation cap, 0-255)", sortIndex: 705,
            minimum: 10, maximum: 255, increment: 5, decimalPlaces: 0)]
        public int LiquidityHeatmapAlphaMax = 70;

        [InputParameter("Saturation Lot Count (0 = adaptive)", sortIndex: 706,
            minimum: 0, maximum: 10000, increment: 5, decimalPlaces: 1)]
        public double LiquidityHeatmapSizeAtSaturation = 0.0;

        [InputParameter("Adaptive Percentile (when saturation = 0)", sortIndex: 707,
            minimum: 0.5, maximum: 0.999, increment: 0.005, decimalPlaces: 3)]
        public double LiquidityHeatmapAdaptivePercentile = 0.99;

        private BookState _bookState;
        private LiquidityHeatmapBuffer _heatmap;
        private ChartPainter _painter;
        private ConcurrentQueue<Level2Quote> _l2Queue;
        private bool _l2Subscribed;

        public __PROJECT_NAME__() : base()
        {
            this.Name = "L2 Heatmap";
            this.SeparateWindow = false;
        }

        // Native settings-dialog grouping. Quantower renders the section header
        // from SettingItemSeparatorGroup; without it the inputs render
        // ungrouped at the top of the dialog.
        public override IList<SettingItem> Settings
        {
            get
            {
                var settings = base.Settings;
                if (settings != null)
                {
                    var heatmapGroup = new SettingItemSeparatorGroup(
                        "Liquidity Heatmap", 700);
                    foreach (var item in settings)
                    {
                        if (item == null) continue;
                        if (item.SortIndex >= 700 && item.SortIndex <= 707)
                            item.SeparatorGroup = heatmapGroup;
                    }
                }
                return settings;
            }
            set => base.Settings = value;
        }

        protected override void OnInit()
        {
            try
            {
                if (this.Symbol == null) return;
                double tickSize = this.Symbol.TickSize > 0 ? this.Symbol.TickSize : 0.25;

                _bookState = new BookState(tickSize);

                if (LiquidityHeatmapEnabled)
                {
                    _heatmap = new LiquidityHeatmapBuffer(
                        tickSize,
                        LiquidityHeatmapRetentionSec,
                        LiquidityHeatmapSnapshotIntervalMs,
                        LiquidityHeatmapAlphaMax,
                        LiquidityHeatmapSizeFloor,
                        LiquidityHeatmapLevelsWindowPoints,
                        LiquidityHeatmapSizeAtSaturation,
                        LiquidityHeatmapAdaptivePercentile);
                }

                _painter = new ChartPainter { Heatmap = _heatmap };
                _l2Queue = new ConcurrentQueue<Level2Quote>();

                this.Symbol.NewLevel2 += Symbol_NewLevel2;
                _l2Subscribed = true;
            }
            catch (Exception ex)
            {
                Core.Instance.Loggers.Log(
                    $"[{nameof(__PROJECT_NAME__)}] OnInit failed: {ex.Message}",
                    LoggingLevel.Error);
            }
        }

        private void Symbol_NewLevel2(Symbol symbol, Level2Quote l2, DOMQuote dom)
        {
            if (l2 == null) return;
            _l2Queue?.Enqueue(l2);
        }

        protected override void OnUpdate(UpdateArgs args)
        {
            DrainLevel2();
        }

        private void DrainLevel2()
        {
            if (_l2Queue == null || _bookState == null) return;
            while (_l2Queue.TryDequeue(out var q))
            {
                try
                {
                    _bookState.Apply(q);
                    _heatmap?.OnPostApply(_bookState, DateTime.UtcNow);
                }
                catch
                {
                    // Single bad quote shouldn't kill the drain. Skip and continue.
                }
            }
        }

        public override void OnPaintChart(PaintChartEventArgs args)
        {
            try
            {
                if (_painter != null && this.CurrentChart != null)
                    _painter.Paint(args, this.CurrentChart);
            }
            catch (Exception ex)
            {
                try
                {
                    Core.Instance.Loggers.Log(
                        $"[{nameof(__PROJECT_NAME__)}] paint failed: {ex.Message}",
                        LoggingLevel.Error);
                }
                catch { }
            }
        }

        protected override void OnClear()
        {
            try
            {
                if (_l2Subscribed && this.Symbol != null)
                {
                    try { this.Symbol.NewLevel2 -= Symbol_NewLevel2; } catch { }
                    _l2Subscribed = false;
                }
                _painter?.Dispose();
                _painter = null;
                _heatmap?.Clear();
                _heatmap = null;
                _bookState?.Clear();
                _bookState = null;
                _l2Queue = null;
            }
            catch { }
        }
    }
}
```

> **Note on the `Settings` override**: that property requires `using System.Collections.Generic;` (for `IList<SettingItem>`) on top of the existing imports. Add it. If a Quantower API quirk surfaces (signature mismatch on the override), check `<api-recon>\REPORT.md` or the Skurry parent project — the `SettingItemSeparatorGroup` constructor takes `(string name, int sortIndex)` in the verified versions.

---

## Step 3 — Build

From the project directory, run:

```pwsh
dotnet build
```

Expected outcome:
- Zero warnings, zero errors.
- DLL produced at `<QT_ROOT>\Settings\Scripts\Indicators\<ProjectName>\<ProjectName>.dll` (the `OutputPath` set in the .csproj).

If the build complains about missing `TradingPlatform.BusinessLayer`, re-verify the `HintPath` in the .csproj and that the version subdir resolved correctly in Step 0.

If the build complains about `unsafe`, verify `<AllowUnsafeBlocks>true</AllowUnsafeBlocks>` is set.

If the build complains about `IList<SettingItem>` or `SettingItem` not found, the `Settings` override probably needs `using System.Collections.Generic;` added to the indicator file.

---

## Step 4 — Verify in Quantower

1. **Restart Quantower** (it caches indicator DLLs on startup; a running instance won't pick up the new build).
2. Open a futures chart with L2 access (NQ, ES, MNQ, MES, CL, etc.).
3. Right-click the chart → **Indicators** → **Add Indicator** → search for the project name (e.g. "L2 Heatmap").
4. Add it. The settings dialog opens — the **Liquidity Heatmap** section shows all eight inputs. Defaults are fine for a first run.
5. Within ~10 seconds (snapshot cadence × initial buffer fill) the bid (blue) / ask (orange) heatmap appears as a chart backdrop. Thicker resting orders show as brighter cells; cells past the saturation point lift into the lighter ignition tone.

### If the heatmap stays empty

- **No L2 events arriving.** Verify the broker delivers L2 (some demo / sim accounts don't). Quantower's status bar shows the L2 feed state.
- **Wrong symbol.** A symbol without L2 (some indices, FX retail feeds) won't ever populate the heatmap. Try a futures contract with confirmed L2.
- **Adaptive saturation hasn't warmed up.** With `Saturation Lot Count = 0` the buffer needs ≥100 sampled cells before the first percentile compute. On a quiet symbol this can take a minute. Set `Saturation Lot Count` to a fixed positive value (e.g. `25`) to bypass adaptive warmup.
- **Cell sizes too small.** Lower `Size Floor` or `Alpha Max` if the backdrop is barely visible.

### If the chart is sluggish

- `Levels Window` too wide for the chart's price range — drop from 50 to 25 points.
- `Snapshot Interval` too aggressive — bump from 500 ms to 1000 ms.

---

## Reference: Quantower API surface used

Everything below is the complete API surface this indicator touches. None of these need to be looked up beyond what's already coded above; the list is for future-edit context.

- `Indicator` base class — override `OnInit()`, `OnUpdate(UpdateArgs)`, `OnPaintChart(PaintChartEventArgs)`, `OnClear()`. Property `Settings` overridable for grouping.
- `Symbol.NewLevel2` event — signature `(Symbol, Level2Quote, DOMQuote)`. Subscribe in `OnInit`, unsubscribe in `OnClear`. Fires on broker thread; do not block.
- `Level2Quote` — fields `Id` (string), `Price` (double, can be NaN on synthesized events), `Size` (double, can be NaN), `PriceType` (`QuotePriceType.Bid` or `.Ask`), `Closed` (bool), `Time` (DateTime, unreliable on Rithmic — wall-clock is safer).
- `Symbol.TickSize` — double; tick grid for the symbol. Fall back to 0.25 if unset (NQ-family default).
- `IChart` (from `this.CurrentChart`) and `IChartWindowCoordinatesConverter` (from `currentChart.MainWindow.CoordinatesConverter`):
  - `GetChartX(DateTime)` → double (px from chart left edge).
  - `GetChartY(double price)` → double (px from chart top edge).
- `PaintChartEventArgs` — `Graphics`, `Rectangle` (chart paint region).
- `[InputParameter]` attribute — surfaced in Quantower's settings dialog. Numeric params take `minimum`, `maximum`, `increment`, `decimalPlaces`.
- `SettingItemSeparatorGroup(string name, int sortIndex)` — groups consecutive InputParameters under a labeled section in the settings dialog.
- `Core.Instance.Loggers.Log(string, LoggingLevel)` — writes to Quantower's log pane. Use sparingly; this indicator should be near-silent.

If you hit an API surface this list doesn't cover (e.g. a different chart hook, alternate subscription path), check `<api-recon>\REPORT.md` first — that's what the file is for.

---

## Done

If you got this far and the heatmap is rendering on the chart, you have feature parity with the parent project's Bookmap-style L2 layer. Iteration ideas, in order of effort:

- Per-symbol saturation override presets (NQ vs ES vs CL — different lot regimes).
- Add a horizontal line at the current best-bid and best-ask for orientation.
- Show a small in-corner readout of `EffectiveSaturation` so the user can see the adaptive saturation drift over the session.
- Wire up a "freeze" hotkey that stops snapshotting so the user can study a moment.

But at this point you have the reproducible base. The painter, book, and buffer are independent — any new feature plugs into one of those three without touching the others.
