# LevelLedger - Activated Spatial Evidence Ledger

## Intent

LevelLedger is not an always-on signal. It is a quiet, user-activated evidence ledger.

The indicator observes bid/ask traded volume and the L2 book continuously, but it only shows shorthand rows after the trader clicks the ledger panel. The click means: "I care about the current auction context; show me the meaningful evidence from the last N minutes and keep updating from here."

The first design emitted mostly temporal evidence. The current design treats those events as journal entries and asks what the balance sheet says by price zone. Events are inputs. Zones are output.

## Design Invariants

- Silent before activation: no evidence rows are shown before a panel click.
- Left-click activates or re-anchors at the current timestamp; right-click deactivates.
- Activation is timestamp-based, not chart-price based.
- Rows are sparse. Inconclusive events are ignored.
- The panel is not scrollable. It shows at most the configured visible row count.
- Rows are shorthand: time, abbreviated price, arrow, phrase.
- Superseding matters. If newer opposite evidence appears near the same price, the older row is dimmed/struck instead of allowed to accumulate as stale conviction.

## Spatial Dominance Philosophy

The useful question is usually not "what event just printed?" It is:

- Who has been leaning into this area?
- Which side keeps reappearing around the same prices?
- Did attempted continuation build support, or did supply/demand dominate the zone?
- Is price acceptance being confirmed by the book, or only by fleeting trade aggression?

LevelLedger therefore accumulates directional L2 events into a decaying one-dimensional price field. Nearby prices share weight through a Gaussian-like kernel, and older events decay by half-life. A row appears only when one side dominates a zone by enough ratio and density.

Example row shape:

`11:33  882  down  5.0x supply dom`

The timestamp is when the zone became ledger-worthy, not a claim that the individual event at that exact second was the trade.

## Evidence Grammar

Directional L2 event signs:

- Demand-positive: `BID_BUILD`, `BID_IN`, `ASK_OUT`, `ASK_PULL`
- Supply-positive: `ASK_BUILD`, `ASK_IN`, `BID_OUT`, `BID_PULL`
- `VOL_OF_DEPTH_SPIKE` stays neutral as a fragility/chaos marker

Trade tape rows still exist, but they are secondary:

- `buyers lift` / `sellers hit`: high-volume, high-delta 5-second traded impulse.
- `node builds`: traded volume has concentrated into a local POC over the rolling node window.
- `accepts higher` / `accepts lower`: the rolling traded POC migrates materially.
- `VOD chaos`: inner-depth volatility spikes, useful as a regime/fragility marker, neutral by itself.

## Current Spatial Defaults

- Book events retained for 20 minutes.
- Dominance half-life is 8 minutes.
- Price kernel width is 12 ticks, with candidates merged inside 24 ticks.
- The visible setting `Spatial Dominance Ratio` defaults to 2.2x.
- The internal minimum dominant density is intentionally fixed for now. It should be tuned from replay/live notes before becoming another user-facing knob.

These are research defaults, not final truths.

## Research Harness

`research/spatial_dominance_replay.py` replays existing `research/out/liq_events_YYYY-MM-DD.csv` files and prints the same style of zone dominance rows for known fixture windows.

Useful commands from repo root:

```powershell
python LevelLedger\research\spatial_dominance_replay.py --date 2026-05-07
python LevelLedger\research\spatial_dominance_replay.py --date 2026-05-05
```

Early sanity checks:

- 2026-05-07 around 11:31-11:43 shows supply dominance around the `870-883` area, matching the failed higher plan / reversal read.
- 2026-05-07 around 12:38-12:40 shows supply dominance near `756`, matching the bounce/reload area.
- 2026-05-05 around 10:17-10:24 shows demand dominance around `055-056`, matching the normal continuation add zone after the first lucky edge entry.

## Why This Is Separate From L2_Surface

L2_Surface paints spatial memory all day. LevelLedger is a temporary workbench once the trader asks "what now?" around a context they already care about. It should not replace L2_Surface, LiquidityMeter, Absorption_Exhaustion, profile, TPO, or the ladder.

## Known Limits

- The indicator does not know manually marked profile levels. It activates around the current time and recent auction context only.
- It does not read other indicator objects directly. It uses the same underlying streams rather than coupling to their runtime internals.
- The spatial replay harness currently uses L2 event CSVs only. Full tick/L1 replay would need the separate SQLite/MCP project or a dump from Quantower.
- There is no after-market dump yet. If research needs it, add an optional CSV/parquet dump with a retention/TTL policy rather than making runtime display scrollable.
