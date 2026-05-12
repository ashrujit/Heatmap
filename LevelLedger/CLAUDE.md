# LevelLedger

Activated spatial evidence ledger for bid/ask traded flow plus L2 book response.

## Why it exists

The trader does not need another always-on signal. Existing tools already cover continuous context:

- `Absorption_Exhaustion`: traded-volume anomaly zones.
- `L2_Surface`: spatial memory of L2 provider events.
- `LiquidityMeter`: compressed cumulative/ROC book pressure.

LevelLedger is the missing "what now?" workbench. It stays visually quiet until clicked, then shows a short, non-scrollable list of meaningful evidence rows from the recent auction.

## Core Design Shift

Do not think of this as an event tape.

The raw L2 rows are journal entries. Meaning emerges when those entries are accumulated by price zone. If price spends 15-20 minutes in a range and emits many events, the useful output is not twenty lines. The useful output is the dominant balance around the prices where participants repeatedly leaned.

The current live engine and replay harness therefore use a decaying 1D spatial field:

- every directional L2 event contributes demand or supply weight;
- nearby prices share weight through a price kernel;
- older evidence decays by half-life;
- rows appear only when one side dominates the zone by enough ratio and density.

Example ledger output:

`11:33  882  down  5.0x supply dom`

## Interaction

- Before activation: panel shell only.
- Left-click inside panel: activate or re-anchor at current timestamp.
- Right-click inside panel: deactivate.
- Activation pulls in rows from the last `Activation Lookback Minutes` and continues forward.

The click is timestamp-based. It does not try to infer a chart price from the click location.

## Row Format

Rows are intentionally terse:

`HH:mm  price  arrow  shorthand`

Price is abbreviated to the last three integer digits plus fractional tick when needed.

Paint priority is by row kind: spatial dominance uses the strongest side colors, trade impulses use separate quieter side colors, VOD uses amber, and node rows stay muted.

## Current Math

Trade side:

- `Symbol.NewLast` is drained through a queue on `OnUpdate`.
- Trades are bucketed into configurable bars, default 5 seconds.
- Strong impulse row requires volume z-score and absolute delta/volume ratio thresholds.
- Rolling price-volume POC over 5 minutes emits `node builds` and material POC migration emits `accepts higher/lower`.

L2 side:

- Polls `Symbol.DepthOfMarket.GetDepthOfMarketAggregatedCollections` at 1 Hz.
- Uses top 10 levels for inner depth and top 30 for centroid distance, mirroring LiquidityMeter/L2_Surface.
- Z-scores bid inner, ask inner, bid centroid, ask centroid against rolling baseline.
- Applies the established side-aware bias map:
  - `BID_BUILD`, `BID_IN`, `ASK_OUT`, `ASK_PULL` are demand-positive.
  - `ASK_BUILD`, `ASK_IN`, `BID_OUT`, `BID_PULL` are supply-positive.
- Every 20 seconds, computes spatial dominance zones over the last 20 minutes, but visible rows are gated to the current auction.
- Dominance uses an 8-minute half-life and a 12-tick price kernel.
- Nearby candidates are merged inside 24 ticks, and at most two spatial rows are considered per evaluation.
- A visible spatial row requires the candidate zone to be within 36 ticks of the current mid and to have same-side dominant evidence within the last 90 seconds. This prevents stale rolling-window decay from printing as fresh demand/supply.

## Research Harness

Run from repo root:

```powershell
python LevelLedger\research\spatial_dominance_replay.py --date 2026-05-07
python LevelLedger\research\spatial_dominance_replay.py --date 2026-05-05
uv run --with polars --with tzdata python LevelLedger\research\replay_levelledger.py --date 2026-05-11 --symbol-dir NQM6 --window 14:45-15:05 --warmup-min 330
```

Current fixture reads:

- `2026-05-07 11:31-11:43`: supply dominance appears around `870-883`, matching the failed higher push / reversal area.
- `2026-05-07 12:38-12:40`: supply dominance appears near `756`, matching the reload-bounce idea.
- `2026-05-05 10:17-10:24`: demand dominance appears around `055-056`, matching the normal-continuation add area.

## Superseding

Rows are merged when the same evidence type repeats near the same price. Spatial dominance rows keep the original emergence timestamp while updating price/text/strength, because the timestamp should mark when the zone first became ledger-worthy, not every refresh.

Opposite directional evidence near the same price supersedes the older row, which paints dimmed/struck while still recent. This preserves the auction narrative without turning the panel into a scrolling tape.

## Validation Notes

First live validation should check:

- Does the shell stay unobtrusive when inactive?
- Are spatial rows sparse enough during normal chop?
- Does `supply dom` show when the trader expected continuation but the book keeps leaning against it?
- Does `demand dom` show near defended continuation add areas?
- Does the 2.2x ratio need to be higher for NQ RTH?

Do not tune this toward entry prediction. Tune it toward better evidence compression after the trader has decided a level matters.
