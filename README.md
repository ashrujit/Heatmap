# Heatmap

A suite of Quantower indicators for NQ-futures auction-flow analysis, plus offline research scripts.

> **For full project context (design philosophy, sub-project rationale, build invariants), read [`CLAUDE.md`](CLAUDE.md). Each sub-project has its own `CLAUDE.md` capturing why-decisions.**

## Sub-projects

| Path | What it does |
|---|---|
| [`L2_Heatmap/`](L2_Heatmap/CLAUDE.md) | Bookmap-style L2 liquidity heatmap chart backdrop. Opt-in parquet capture for offline research. |
| [`Absorption_Exhaustion/`](Absorption_Exhaustion/CLAUDE.md) | Microstructure anomaly visibility layer (stacked imbalance, balanced absorbing, single-print, weak-delta extreme). Self-clearing price-band accumulator. |
| [`LiquidityMeter/`](LiquidityMeter/CLAUDE.md) | Live cum-bar + ROC-dial + VOD-flicker reading the order-book regime. Side-aware event detection; designed as sizing/exit aid. |
| [`research/`](research/RESEARCH_LOG.md) | Python (Polars) scripts for offline analysis of parquet captures. `RESEARCH_LOG.md` is the running journal of analysis sessions. |

## Prerequisites

- Windows 11
- Quantower installed at `C:\Quantower\` (this project's `OutputPath`s and `HintPath`s are hardcoded to that location — see root [`CLAUDE.md`](CLAUDE.md) for details)
- .NET SDK (8 or later — SDK 10 builds the `net8-windows` targets fine)
- Python 3.12+ with `uv` for the research scripts (Polars + numpy)

## Build & deploy

From any indicator sub-project directory:

```
dotnet build
```

The DLL deploys directly to `C:\Quantower\Settings\Scripts\Indicators\<Name>\` via the project file's `OutputPath`. Restart Quantower to pick up new builds — QT caches indicator assemblies on startup. After restart: right-click chart → Indicators → Add Indicator → search by name.

## Design philosophy in one line

**Surface microstructure shapes; never classify or "confirm" them.** The trader supplies context (reference levels, regime, value structure); the indicators surface raw structure. No state machines, no significance gates, no prediction. See [`feedback_indicator_design_philosophy.md`](https://github.com) (in user-local memory, not in repo) and the sub-project `CLAUDE.md` files for full rationale.
