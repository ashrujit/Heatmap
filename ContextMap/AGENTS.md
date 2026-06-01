# ContextMap - Rail Stack and Auction Quality

## Intent

ContextMap is the successor experiment to `ON_ContextMap`. It keeps the useful
part of that tool - overnight/preopen supply and demand rails - but changes the
live question from "which message fired?" to:

- what prepared rails sit above and below the auction;
- when a rail is resolved, whether the move beyond it is building accepted
  business or only traversing thin/contested space;
- whether a later scale-up is edge inventory, accepted-pullback inventory, or
  open-auction extension inventory.

This is still context, not execution. LevelLedger and the ladder own entries,
adds, and exits.

## Design Decisions

- This is a new indicator instead of an overwrite of `ON_ContextMap` so both
  tools can be compared live without losing the prior implementation.
- The panel shows rail stacks, not a scrolling event log. Resolved/stale history
  should not consume the visible rows during the open.
- Rails are 4-point buckets by default. This intentionally matches the research
  harness and NQ profile granularity used in review notes.
- Strength glyphs are relative and local to the session: `+++`, `++`, `+`.
  They mean book-memory strength, not trade direction.
- "Resolved" and "accepted" are separate. Price trading through a rail starts a
  leg; acceptance requires volume/time/business left behind the rail.
- Day-type labels are secondary. The code may show a frame line, but the primary
  signal is the leg-quality phrase: `thin`, `capped`, `fast/no-build`,
  `building`, or `accepted`.

## Current V0 Constraints

- Like `ON_ContextMap`, live L2 events are inferred from sampled aggregate DOM
  shape and anchored near the current mid. This is good enough to test the
  workflow, but less precise than true per-price L2 deltas.
- There is no historical backfill. The indicator must run through ETH/preopen to
  build useful rails.
- `NewLevel2` is a liveness heartbeat only; ignore Quantower's synthetic
  `generated_from_level1` / NaN pseudo-L2 events so L1 changes cannot falsely
  keep the book marked fresh.
- The live tick callback queue is capped at 50k prints. Overflow drops newest
  prints with throttled error logging; this preserves process health but is not
  an auction filter.
- Rail selection and leg-quality thresholds are intentionally fixed until the
  Python replay harness has more fixtures.
