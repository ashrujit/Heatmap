# ON_ContextMap - Scenario Filter

## Intent

ON_ContextMap is a separate chart indicator for pre-open scenario filtering.
It is not an execution tool and should not compete with LevelLedger.

The problem it addresses is earlier than LevelLedger's current-auction read:

- where did ETH/ON build supply and demand memory;
- which rails are being resolved during the first RTH minutes;
- whether the open is accepting at/above the upper ON distribution, accepting
  into the hole, or still unresolved.

The user still executes from ladder and LevelLedger. This indicator should
reduce hesitation caused by the wrong open-type frame, not tell the trader where
to click.

## Design Invariants

- Run on a separate chart from LevelLedger.
- Keep visual priority low: passive bands plus a sparse panel.
- Do not paint an all-day accepted/unaccepted heatmap.
- `NewLevel2` is a liveness heartbeat only; ignore Quantower's synthetic
  `generated_from_level1` / NaN pseudo-L2 events so L1 changes cannot falsely
  keep the book marked fresh.
- The live tick callback queue is capped at 50k prints. Overflow drops newest
  prints with throttled error logging; this is overload protection only.
- New zone creation is intended for ON and early IB only. Existing zones may
  update/fade after the creation cutoff.
- Zone state changes are sparse. Do not emit rows for every L2 event.
- Use the same side-aware L2 grammar as LiquidityMeter / LevelLedger:
  `BID_BUILD`, `BID_IN`, `ASK_OUT`, `ASK_PULL` are demand-positive;
  `ASK_BUILD`, `ASK_IN`, `BID_OUT`, `BID_PULL` are supply-positive.
- The indicator must not weaken or duplicate LevelLedger's current-auction gate.

## Current V0 Behavior

The engine accumulates L2 event zones from the live DOM stream:

- ON phase creates overnight rails.
- RTH before the new-zone cutoff can create early business zones.
- After the cutoff, the engine updates existing zone states but does not try to
  become an all-day market-structure map.

Band states are intentionally coarse:

- `unresolved`: qualified zone has not been meaningfully tested.
- `tested`: RTH has traded into the zone's test band.
- `held` / `rebuilt`: same-side evidence reappears after test.
- `resolved up` / `resolved down`: price moves through and fresh business
  appears beyond the rail.
- `contested`: opposite-side evidence appears before resolution.
- `swept`: price pokes through a demand rail without immediately creating a
  clear accepted-below state.

The panel uses short rows such as:

```text
060 D ON T3 rebuilt
108 S ON resolved up
123 D RTH accepted
```

These are scenario-filter rows, not execution instructions.

## Settings Rationale

Font size and panel offsets are user-facing because the indicator may live on a
4K side monitor. Do not hard-code a small panel font or fixed placement.

The default `New Zone Cutoff HHmm = 1030` is deliberate: the target use case is
IB/open-type framing. Existing rows can keep updating until the later update
cutoff, but the indicator should not keep inventing fresh structure all day.

## Validation Target

The 2026-05-20 fixture is the first design case:

- ON had old demand memory at `060`, `030`, and `000`.
- First RTH minutes tested both lower (`060`) and upper (`107/108`,
  `123/130`) rails.
- The useful scenario-filter read was that new business kept forming above
  `060`, while pokes below it did not create fresh accepted-below structure.
- The later `123` and `188` entries were LevelLedger execution reads, not this
  indicator's job.

Future validation should ask whether this indicator would have reduced the
delay before treating the day as accepting at/above the upper pre-market
distribution, rather than into the hole toward prior-day VPOC.
