# ETH / Overnight Research

## Purpose

This note tracks the new overnight research thread. In this project, **ETH** and
**ON** are used interchangeably: the extended / overnight trading session that
sets up the RTH open.

The working problem is not the same as LevelLedger's current-auction problem.
LevelLedger answers: **what evidence is forming where price is auctioning now?**
This research asks: **what long-memory supply / demand context exists above and
below price before the open drive gets there?**

## Motivation

Morning planning currently uses market-profile context: overnight HVNs/LVNs,
where ON volume printed relative to the prior day, ETH profile shape, ONH/ONL,
VWAP, and open-type scenarios.

The missing layer is live book memory. During IB, price often drives through
thin areas so quickly that ladder-reading becomes an attention bottleneck. By
the time LevelLedger prints a confirmed local row, the actionable location may
already be gone.

The desired research output is a pre-open / IB context map, not a signal:

```text
Above
29040-29064  resting / rebuilt supply candidate
28997-29005  thin contested cap

Below
28940-28955  demand memory
28820-28850  low response / demand memory
```

## Hypothesis

Complete ETH L2 capture may reveal useful zones before RTH price tests them:

- Persistent resting liquidity by price zone.
- Resting liquidity that rebuilds after being pulled or consumed.
- Incipient supply/demand that is too thin for LevelLedger's spatial dominance
  threshold, but still useful during fast IB drives.
- Zone-state transitions: untouched, tested, held, consumed, rebuilt, flipped,
  stale.

This should be researched separately from LevelLedger. It may share math and
event vocabulary, but the job is different enough to justify a separate
research harness and, if it earns its keep, a separate indicator.

## Important Distinction

LevelLedger intentionally has a current-auction gate so it does not print stale
away-from-price rows as fresh evidence. That invariant should remain intact.

The ETH map would do the opposite on purpose: preserve long-distance context
above and below current price, with clear age/state labels so old context is not
mistaken for fresh local confirmation.

## 2026-05-19 Seed Observation

The available 2026-05-19 data was incomplete because the machine was off during
most of ETH. Captured gaps included roughly:

- 2026-05-18 21:49 to 23:51 NY.
- 2026-05-19 00:40 to 08:12 NY.

Despite the gap, the RTH open sequence showed the research problem clearly:

- First 5 minutes were a drive, not an auction.
- Buying the 28940-28980 VWAP region was structurally poor because the open had
  not been tested after the failed ON-high clearing attempt.
- Waiting for a conclusive open break was mechanically correct but operationally
  late, because the move then drove quickly with little contest.
- Around 28997-29005 there was raw supply evidence, but not enough for a
  LevelLedger spatial row:
  - 09:54:40 `ASK_BUILD` 28997.25 z=4.44
  - 09:54:41 `ASK_BUILD` 28997.75 z=3.76
  - 09:54:49 `BID_BUILD` 29004.75 z=3.69
- This looked like a thin / contested cap, not confirmed LL supply dominance.

That is the exact category the ETH map should preserve: **candidate overhead
context that current LL properly ignores**.

## Data Collection Plan

Leave Quantower / the capture indicator running overnight for several complete
ETH sessions. L2_Heatmap painting can stay off; capture is what matters.

For each day, preserve:

- Full ETH L2 snapshots parquet.
- Full ETH tick parquet.
- Morning prep notes: expected open type, key HVNs/LVNs, ONH/ONL, VWAP, value
  references, and planned if/then scenarios.
- Post-open notes: what was anticipated, what was wrong, what ladder/LL evidence
  was missed, and where entry/exit was operationally hard.

## Research Questions

1. Did persistent resting liquidity identify useful overhead/underfoot zones
   before price touched them?
2. Did rebuilt liquidity after pull/consume events matter more than static
   resting size?
3. Did thin candidate caps/floors appear before fast IB reversals even when
   they failed LevelLedger's confirmed spatial-row thresholds?
4. Does ETH book memory add anything beyond HVN/LVN/ONH/ONL/VWAP context?
5. How often do apparent resting zones get consumed cleanly, making them traps
   rather than useful reaction locations?
6. What labels are honest enough for live use: resting, rebuilt, tested, held,
   consumed, flipped, stale, contested?

## Guardrails

- Do not turn this into a buy/sell classifier.
- Do not treat one session as evidence.
- Do not weaken LevelLedger's current-auction gate to solve this problem.
- Do not confuse visible heatmap liquidity with proven supply/demand. The
  research must distinguish resting size, event-based book response, and actual
  price interaction.

## 2026-05-20 Full ETH Session - Design Outcome

The first complete ETH/ON + RTH review shifted the target from "book-memory
indicator" to **scenario filter**.

The useful question is not "where should I enter?" LevelLedger and the ladder
already answer execution. The useful question is:

```text
Is RTH accepting at/above the upper ON distribution, accepting into the ETH
hole, or still unresolved?
```

Session fixture:

- ON had lower demand-memory candidates around `060`, `030`, and `000`.
- ON also had upper rails around the pre-market HVNs / supply-memory areas
  near `107/108` and `123/130`.
- The first RTH minutes tested both sides, so the open was not a clean open
  drive and not an immediate selloff into prior-day VPOC.
- The key tell was that new business kept forming above `060`, while repeated
  pokes below `060` did not create meaningful fresh dominance below it.
- The later `123` and `188` long executions were LevelLedger reads: supply
  pressed, failed to create lower continuation, and demand rebuilt. The new
  ON tool should not claim those entries as its own.

Design decision:

- Build a separate `ON_ContextMap` indicator for passive ON rails plus sparse
  scenario-state rows.
- Run it on a separate chart from LevelLedger.
- Paint low-priority bands for unresolved / tested / held / rebuilt / resolved
  rails.
- Stop creating new zones after early IB by default (`10:30`), but let existing
  rows update/fade until the later cutoff (`12:00`).
- Include font size and panel offsets because the tool may live on a 4K monitor.

This keeps the responsibility split clean:

```text
ON_ContextMap = scenario filtering / open-type frame
LevelLedger   = current-auction execution evidence
Ladder        = final timing and risk interaction
```
