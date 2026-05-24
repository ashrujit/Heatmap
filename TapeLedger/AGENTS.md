# TapeLedger - Tick-Only Auction Shelf Ledger

## Intent

TapeLedger is the L1/tape counterpart to ContextMap and LevelLedger. It answers
the user's recurring auction questions from traded bid/ask flow only:

- did the OR5 / IB break leave accepted business or only travel on fumes;
- where did the move leave shelves that later retracements should respect;
- when late-morning or lunch makes/tests a RTH extreme, did it locally reject
  and where did the repair shelf form afterward.

It does not attempt to decide full-day reversal, day type, or trade direction.
Those depend on profile context, reference levels, ES alignment, and ladder
execution. The indicator paints local evidence aggressively so it is not missed
on the mostly-empty 5-minute chart.

## Visual Grammar

- Bands are the primary artifact. Traded shelves are spatial and sequential, so
  they belong at price.
- Banners are allowed and intentionally obvious. Break quality can be missed if
  buried in panel text.
- The panel is a compact sequence ledger, not a scrolling footprint clone.
- Colors are saturated enough for weaker monitors because this chart is expected
  to run with no other paint-heavy indicator.

## Current Constraints

- Tick stream only. No L2 snapshots and no book-derived evidence.
- No historical backfill. The indicator must be running during the session.
- RTH/OR5/IB times are NY-time configurable but default to NQ RTH.
- Shelf zones use 4-point bins by default, matching the research harness.
- The first version favors readable visual behavior over perfectly matching the
  offline Python probes. It should be tuned from live chart screenshots.
