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

Trade impulse and VOD rows show a compact `zN` badge from the already-computed absolute z-score. This is intentionally a measurement hint, not a new event type or interpretation: the trader can notice abnormality, then decide from chart/profile/tape context whether it was exhaustion, absorption, continuation fuel, or failed aggression.

## Visual Priority

Color/saturation carries row class:

- Spatial dominance rows are highest-priority and use the strongest side colors.
- A leading `+` is reserved for a first-print spatial dominance row that has not yet merged into a same-side update. It is deliberately not shown on updates, VOD chaos, node rows, or trade impulse rows; those rows are already isolated event observations. The marker exists only to answer, "did a new side just take a stance here?"
- Trade impulse rows (`buyers lift` / `sellers hit`) use separate, quieter side colors so tape bursts do not visually masquerade as zone control.
- `VOD chaos` is amber/neutral and intentionally not side-colored. It is a warning/fragility marker, not a directional claim.
- The chart VOD+BUILD overlay is different from the ledger `VOD chaos` row on purpose. Dots require stricter same-sample `VOD + BID/ASK_BUILD` confirmation, paint as amber circles, and use a bid/ask/mixed rim only to show which side of the book thrashed. The rim is a side-of-chaos hint, not a buy/sell signal.
- Node rows are muted because they are contextual structure rather than an immediate warning.

## Quantower Settings Behavior

- Override `OnSettingsUpdated` and do not call the base implementation. Base
  `Indicator.OnSettingsUpdated` calls `Refresh()`, which destroys the
  forward-only ledger state that cannot be rebuilt from chart history.
- Settings are applied in place to the existing engine and painter. Visual
  moves like panel offsets and font size should redraw without clearing rows,
  ownership rails, VOD dots, or VOD stacks. Detection setting changes affect
  future samples only; they do not reinterpret already accumulated evidence.

## Chart Overlay Fold-In

LevelLedger is now the migration target for L2_Surface ideas that survive research. The goal is not to copy every L2_Surface layer; each candidate earns its place independently from parquet review and live use.

Overlays must stay independently toggleable from the ledger panel. This lets the same indicator run on charts where the panel is useful and on charts where only the researched chart paint is wanted.

The first folded overlay is VOD+BUILD dots:

- Ledger row: `VOD chaos` remains broader, neutral, merged, and row-oriented.
- Chart dot: same-sample `VOD` plus `BID_BUILD` or `ASK_BUILD`, defaulting to the stricter surface thresholds.
- Visual grammar: amber fill for chaos, side-colored rim for bid/ask/mixed book-side turbulence.

The second folded overlay is ownership rails:

- The old raw `BID_BUILD`/`ASK_BUILD` build-band layer was retired after 2026-05-28 and 2026-05-29 replay. It was either too sparse at default settings or too noisy when relaxed; the useful object was not a raw cluster, but a rail that answers who owns the current leg and where that ownership is wrong.
- Ownership candidates use the same side-aware L2 event grammar as the panel (`BID_BUILD`, `BID_IN`, `ASK_OUT`, `ASK_PULL` for demand; opposite events for supply). A candidate becomes a rail only after price accepts away from the area. If price moves through the evidence in the opposite direction, the rail side becomes the consumer of that evidence.
- Rails can be owned, tested, failed, or part of a contested envelope. A consumed rail is promoted only after follow-on business appears in the direction of consumption; otherwise repeated two-sided failures collapse visually into an amber contested zone.
- Thesis rails are the nearest accepted rails backed by a same-side stack. They are not signals; they are falsification points. Their visual job is to make "belief should increase here" or "belief should collapse here" obvious without adding panel text or hardcoded trade instructions.
- `OWNERSHIP_RAILS.md` captures the 2026-05-28 and 2026-05-29 reasoning that led to this grammar. Keep future tuning notes there when they are about trader cognition, fixture reads, or visual semantics rather than code invariants.

The third folded overlay is VOD stacks:

- VOD stack centers use the broader `VOD chaos` cluster, not only the stricter VOD+BUILD dot. The design reason is that instability often appears before an extreme breaks or fails, while VOD+BUILD dots are intentionally sparse.
- Visual grammar is deliberately separate from dominance rows and ownership rails: yellow dotted center line for the unstable auction, blue dotted confirmed demand lines, orange dotted confirmed supply lines.
- Directional stack lines are not emitted on the first directional event. A post-VOD supply/demand candidate must be followed by price moving away by the configured tick distance before it becomes visible. This prevents a low-break VOD from immediately painting a misleading demand line unless the auction actually rejects away from that area.
- A distinct new VOD cluster fades the prior stack. The current stack remains the center of attention; older stacks can stay faintly visible for review until the retention setting removes them.

Parked candidates:

- L2_Surface inflection lines/dots were researched against 2026-05-14 and 2026-05-15 parquet via `research/surface_candidates.py --candidate inflection` and should not be folded in for now. The signal is a derived state machine over the same side-aware L2 event stream that LiquidityMeter already renders as cum/ROC. LiquidityMeter is not numerically identical under all defaults: its ROC is the same signed rolling-sum operator, while its cumulative leg is anchored/rolling by meter settings rather than L2_Surface's fixed 5-minute cum plus trigger-baseline delta. Still, the practical information is redundant for live use: by the time inflection confirms, ladder, price, LevelLedger, and LiquidityMeter usually already expose the same pressure shift.
- L2_Surface flow bands were researched against 2026-05-14 and 2026-05-15 parquet via `research/surface_candidates.py --candidate flow`. The default band recipe produced zero bands on both days. A relaxed probe (`--band-event-count 3 --band-sustain-sec 3`) produced only one band per day: a 2026-05-14 RTH-open artifact and a short 2026-05-15 10:00 bear patch. The VOD+BUILD climax component is already represented by the folded chart dots; the sustained flow-band state machine does not yet justify LevelLedger integration.

## Current Spatial Defaults

- Book events retained for 20 minutes.
- Dominance half-life is 8 minutes.
- Price kernel width is 12 ticks, with candidates merged inside 24 ticks.
- Visible dominance rows are current-auction gated: the candidate zone must be within 36 ticks of the current mid.
- Visible dominance rows are freshness gated: the dominant side must have a same-zone event within 90 seconds. The rolling field may remember older zones, but stale decay/window crossings do not create new ledger rows.
- The visible setting `Spatial Dominance Ratio` defaults to 2.2x.
- The internal minimum dominant density is intentionally fixed for now. It should be tuned from replay/live notes before becoming another user-facing knob.
- Spatial dominance rows use display hysteresis. The raw dominance field is still
  evaluated every 20 seconds, but an existing same-side row only rewrites when
  the zone center moves materially, the dominance ratio changes materially, or
  enough time passes that a rounded text change is worth showing. This keeps the
  ledger from behaving like a flickering meter while preserving fresh opposite
  evidence and new-zone rows.

The 2026-05-11 live review exposed why both gates matter. A 444 demand-dominance row printed near 15:00 while price was already near 388 because older opposing supply aged out of the rolling window. The demand evidence near 444 was real, but the visible row was not caused by fresh/current-auction demand. Dominance memory can be rolling; row emission cannot be driven by passive decay alone.

These are research defaults, not final truths.

## Research Harness

`research/spatial_dominance_replay.py` replays existing `research/out/liq_events_YYYY-MM-DD.csv` files and prints the same style of zone dominance rows for known fixture windows.

`research/replay_levelledger.py` is the closer live-engine replay. It reads captured L2 parquet snapshots and mirrors the C# sample loop, event detection, current-auction gate, and freshness gate. Use it when debugging whether a live row should or should not have printed.

`research/ownership_bands_probe.py` is the replay mirror for ownership rails.
The problem it explores is trade-management paralysis, not missing detection:
can the existing LL event stream produce sparse chart rails that answer who owns
the current leg, where that ownership is wrong, and whether the wrong-location
is being tested or has failed? Keep this separate from panel rows; the live
fold-in paints chart rails only.
Its summary options bucket ownership/failure churn and list durable bands
because print count alone is misleading on two-sided range days; the useful
question is which rails survived, not how often a candidate appeared.

Useful commands from repo root:

```powershell
python LevelLedger\research\spatial_dominance_replay.py --date 2026-05-07
python LevelLedger\research\spatial_dominance_replay.py --date 2026-05-05
uv run --with polars --with tzdata python LevelLedger\research\replay_levelledger.py --date 2026-05-11 --symbol-dir NQM6 --window 14:45-15:05 --warmup-min 330
uv run --with polars --with tzdata python LevelLedger\research\ownership_bands_probe.py --date 2026-05-29 --symbol-dir NQM6 --window 09:30-10:05 --warmup-min 90
```

Early sanity checks:

- 2026-05-07 around 11:31-11:43 shows supply dominance around the `870-883` area, matching the failed higher plan / reversal read.
- 2026-05-07 around 12:38-12:40 shows supply dominance near `756`, matching the bounce/reload area.
- 2026-05-05 around 10:17-10:24 shows demand dominance around `055-056`, matching the normal continuation add zone after the first lucky edge entry.

## Relationship To L2_Surface

L2_Surface was the original always-on L2 paint surface. LevelLedger remains the decision workbench, but it is also the long-term home for researched L2_Surface computations that prove useful in live reads. Do not change L2_Surface while migrating candidates unless explicitly requested; preserve it as a reference implementation until the LevelLedger replacement path is mature.

## Known Limits

- The indicator does not know manually marked profile levels. It activates around the current time and recent auction context only.
- It does not read other indicator objects directly. It uses the same underlying streams rather than coupling to their runtime internals.
- The spatial replay harness currently uses L2 event CSVs only. Full tick/L1 replay would need the separate SQLite/MCP project or a dump from Quantower.
- There is no after-market dump yet. If research needs it, add an optional CSV/parquet dump with a retention/TTL policy rather than making runtime display scrollable.
