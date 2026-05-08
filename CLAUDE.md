# Heatmap — Quantower Indicator Suite

This repo hosts a suite of Quantower indicators built as standalone .NET 8 DLLs. Each indicator lives in its own subfolder, has its own `.csproj`, and deploys to `<QT_ROOT>\Settings\Scripts\Indicators\<Name>\` via the project file's `OutputPath`.

## Documentation policy

- Every sub-project gets its own `CLAUDE.md` with design decisions, architectural invariants, and the *why* behind non-obvious choices.
- This root `CLAUDE.md` covers cross-cutting conventions only — toolchain, Quantower invariants that apply everywhere, build flow.
- Don't write what-the-code-does prose. Capture *why*, surprises, and constraints that aren't obvious from the code.

## Toolchain

- **OS:** Windows 11. Bash + PowerShell available; prefer Bash for file ops, PowerShell for `dotnet`/build.
- **.NET SDK:** 10.0.203 installed at `C:\Users\j\AppData\Local\Microsoft\dotnet\dotnet.exe` (user-profile install, not machine-wide). SDK 10 builds `net8-windows` TFM fine. .NET 8 runtime (8.0.26) also installed at `C:\Program Files\dotnet\`.
- **Quantower:** `C:\Quantower`, version `v1.145.9`. BusinessLayer reference DLL at `C:\Quantower\TradingPlatform\v1.145.9\bin\TradingPlatform.BusinessLayer.dll`.
- **No IDE.** `dotnet build` from each project dir is the entire build step. Project files are plain text.

### NuGet source (one-time setup, already done)

The user-profile SDK install came with **no NuGet sources configured**, so first build failed with `NU1100: Unable to resolve 'Microsoft.NETCore.App.Ref (= 8.0.26)'`. SDK 10 needs to download .NET 8 reference packs from NuGet to build a `net8-windows` project. Fixed once with:

```
dotnet nuget add source https://api.nuget.org/v3/index.json -n nuget.org
```

Already configured — only mentioned here because if a fresh dev env is set up later (or a different user profile), this needs to be redone before the first build.

## Known Quantower API quirks

- **`QuotePriceType` lives in `TradingPlatform.BusinessLayer.Integration`**, not the root `TradingPlatform.BusinessLayer` namespace. Any file that touches `Level2Quote.PriceType` needs `using TradingPlatform.BusinessLayer.Integration;` on top of the standard `using TradingPlatform.BusinessLayer;`. The bootstrap prompt's API reference omitted this and the first build failed with `CS0103: 'QuotePriceType' does not exist`. Verified at `api-recon\api-recon\src\TradingPlatform.BusinessLayer\TradingPlatform.BusinessLayer.Integration\QuotePriceType.cs`.
- Other types like `Level2Quote`, `Symbol`, `Indicator`, `DOMQuote`, `Core`, `LoggingLevel`, `Level2Item`, `UpdateArgs`, `PaintChartEventArgs`, `SettingItem`, `SettingItemSeparatorGroup`, `InputParameter` all live in the root namespace. `IChart`, `IChartWindowCoordinatesConverter` live in `TradingPlatform.BusinessLayer.Chart`.

## Build flow

From any sub-project directory:

```
dotnet build
```

Output DLL lands directly in Quantower's indicators path (set via `OutputPath` in the `.csproj`). Restart Quantower to pick up new DLLs — Quantower caches indicator assemblies on startup.

## Cross-cutting Quantower invariants

These apply to any indicator in this suite that touches L2 / market data / chart paint:

1. **No blocking on UI thread.** L2/L1 callbacks fire on broker thread — enqueue into a `ConcurrentQueue<T>`, drain on UI thread inside `OnUpdate`. `OnPaintChart` is also UI-thread.
2. **Tick-keyed dictionaries, not double-keyed.** Float-equality across independently computed prices breaks `Dictionary` lookup. Use `(long)Math.Round(price / tickSize)` as the key.
3. **Quantower synthesizes pseudo-L2 events** from L1 best-bid/ask changes (`id="generated_from_level1"`, NaN price/size). Filter these in any `Level2Quote` consumer.
4. **Forward-only L2.** No historical book — indicators that need history accumulate it from live data and warm up over time.
5. **Unsafe pixel writes are scoped narrowly.** `LockBits` + raw `int*` writes are ~10× faster than per-cell `FillRectangle`, but only worth it for the heaviest paint paths. Don't extend the unsafe scope beyond the rebuild method that needs it.
6. **Per-frame bitmap caching** for chart-backdrop renders. Rebuild only on data-change, pan/zoom, or rect resize. Cache hit = single `g.DrawImage` blit.

## API reference

`api-recon\api-recon\` (REPORT.md, src/, dlls/) contains Quantower API reference materials extracted from the BusinessLayer DLL. Use it when an indicator needs an API not already covered by the in-hand bootstrap doc / parent project. Don't read it speculatively — bootstrap prompts include the surface they need.

## Sub-projects

- [`L2_Heatmap/`](L2_Heatmap/CLAUDE.md) — Bookmap-style L2 liquidity heatmap as a chart backdrop, **plus** the capture infrastructure (parquet writer for L2 snapshots + ticks) that the entire suite reads from for retro analysis. Cloud display demoted 2026-05-07 (toggleable via `Show Heatmap Painting`); capture path stays the data foundation.
- [`L2_Surface/`](L2_Surface/CLAUDE.md) — Single indicator, four toggleable structural layers on the chart price track: per-tick events as additive-alpha dots; cum-joins-ROC inflection lines (encodes the 05-05 win/loss rule); flow band + climax line fingerprint at provider-thrash levels; supply/demand zones from BUILD clustering. All layers share one BookState, one sample loop, one event vocabulary. Replaces the cloud-overlay role L2_Heatmap had previously occupied. Originally planned as four separate indicators, consolidated 2026-05-08 — see L2_Surface/CLAUDE.md "Why one indicator, not four."
- [`Absorption_Exhaustion/`](Absorption_Exhaustion/CLAUDE.md) — Microstructure anomaly visibility layer. Four primitives (stacked imbalance, balanced absorbing, single-print, weak-delta extreme) detected on 5-sec bars from the trade tape. Renders as a self-clearing price-band accumulator, not a label-classified event stream — the user's context (reference levels, regime) does the interpretation.
- [`LiquidityMeter/`](LiquidityMeter/CLAUDE.md) — Live left-center "fuel-gauge + needle" reading the order-book regime. Side-aware (BID/ASK split) event detection from L2 snapshots at 1Hz. Cum tracks slow lean since anchor (rolling 30min default), ROC tracks 60s pressure. Designed as a sizing/exit aid (does the lean still confirm leverage?) rather than an entry signal. Validated conceptually against one win + one loss design fixture; live verification across session types pending. v0.2 adds left-click-on-meter manual anchor (right-click to clear).
- [`SinglePrints/`](SinglePrints/CLAUDE.md) — Standalone RTH TPO single-print indicator. Marks prices traded in exactly one 30-min bracket per session as horizontal zones extending to the chart right edge until later trade fills them. Bar-history-driven (no L2 / tape dependency); no shared code with the order-flow suite. Same "surface structure, don't classify" posture: single hue, alpha fade by session age, no labels.
