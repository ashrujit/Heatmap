# Heatmap — Quantower Indicator Suite

This repo hosts a suite of Quantower indicators built as standalone .NET 8 DLLs. Each indicator lives in its own subfolder, has its own `.csproj`, and deploys to `<QT_ROOT>\Settings\Scripts\Indicators\<Name>\` via the project file's `OutputPath`.

## Documentation policy

- Every sub-project gets its own `AGENTS.md` with design decisions, architectural invariants, and the *why* behind non-obvious choices.
- This root `AGENTS.md` covers cross-cutting conventions only — toolchain, Quantower invariants that apply everywhere, build flow.
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

- [`L2_Heatmap/`](L2_Heatmap/AGENTS.md) — Bookmap-style L2 liquidity heatmap as a chart backdrop. Display-only. Ported from Skurry_Scribe parent project.
- [`Absorption_Exhaustion/`](Absorption_Exhaustion/AGENTS.md) — Microstructure anomaly visibility layer. Four primitives (stacked imbalance, balanced absorbing, single-print, weak-delta extreme) detected on 5-sec bars from the trade tape. Renders as a self-clearing price-band accumulator, not a label-classified event stream — the user's context (reference levels, regime) does the interpretation.
- [`LiquidityMeter/`](LiquidityMeter/AGENTS.md) — Live left-center "fuel-gauge + needle" reading the order-book regime. Side-aware (BID/ASK split) event detection from L2 snapshots at 1Hz. Cum tracks slow lean since anchor (rolling 30min default), ROC tracks 60s pressure. Designed as a sizing/exit aid (does the lean still confirm leverage?) rather than an entry signal. Validated conceptually against one win + one loss design fixture; live verification across session types pending.
- [`LevelLedger/`](LevelLedger/AGENTS.md) — User-activated spatial evidence ledger. Quietly observes traded bid/ask flow and L2 book response, but shows no evidence rows until the trader clicks its panel. Once activated, displays sparse shorthand rows where accumulated L2 evidence shows demand/supply dominance by price zone, plus secondary trade/node rows, to support sizing/hold/trim reasoning without becoming a buy/sell signal.
- [`ON_ContextMap/`](ON_ContextMap/AGENTS.md) — Pre-open / IB scenario filter. Builds ETH/ON supply-demand rails and sparse state rows for whether RTH is accepting above, into, or below those rails. Intended to reduce open-type framing delay; execution remains ladder + LevelLedger.
