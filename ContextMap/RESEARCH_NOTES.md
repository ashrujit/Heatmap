# ContextMap Research Notes

## Why This Exists

`ON_ContextMap` proved that ETH/preopen book memory can mark useful opening
rails, but the live panel created too many resolved messages. The problem was
not that the rails were useless. On 2026-05-21 they were unusually precise:

```text
29202-29206 demand
29262-29266 supply
```

RTH danced around those exact areas in the first 15 minutes. The missing layer
was what happened *after* a rail was resolved:

```text
Did price build accepted business beyond the rail,
or did it only traverse empty/contested space?
```

This indicator is the first C# attempt at that answer.

## Current Responsibility Split

```text
ContextMap   = prepared rails + move/leg quality
LevelLedger  = current-auction execution evidence
Ladder       = timing, risk, and actual interaction
```

ContextMap should not become a buy/sell signal. It should help decide whether a
move has legs under it, whether extension adds are structurally different from
edge inventory, and whether a resolved rail has actually been accepted.

## 2026-05-21 Design Fixture

The session looked like an open auction after both sides failed to establish
acceptance.

Important sequence:

```text
PREP     29202-206 D / 29262-266 S
09:50    Up through 264, but move above 280/290 was thin/mixed
10:10    320s capped; 10:10 candle showed no durable support above 264
10:15    Fast liquidation lower, not systematic step-by-step lower acceptance
10:35    Reclaim back through lower rail/open/VWAP region
11:30    Long from lower side made sense
11:40+   Adds above open/VWAP were extension inventory, not edge inventory
```

The practical lesson:

```text
Hold/scale edge inventory differently from extension inventory.
```

The desired live cue was not "do not be long"; it was:

```text
UP leg above 264 = thin/mixed, resolved not accepted
DOWN leg = fast/no-build, lower acceptance failed
OPEN AUCTION / upper extension add risk
```

## 2026-05-20 Contrast Fixture

The replay harness gives a different signature on 2026-05-20. It initially
finds two-sided attempts, but the 10:15-10:25 upside leg starts building and
then becomes accepted higher:

```text
10:15 up leg 29108 -> 29234 building
10:25 accepted higher
```

That contrast is important. The goal is not to label every day as open auction;
the useful distinction is between:

```text
resolved but thin/failed
resolved and building
resolved and accepted
```

## Math Shape

The Python harness and C# V0 use the same rough concepts:

- 4-point rail bins by default (`16` NQ ticks).
- Side-aware L2 grammar:
  - demand-positive: `BID_BUILD`, `BID_IN`, `ASK_OUT`, `ASK_PULL`
  - supply-positive: `ASK_BUILD`, `ASK_IN`, `BID_OUT`, `BID_PULL`
- Rails qualify by dominant weight and dominance ratio.
- When price breaks an active rail, a leg starts.
- A leg tracks volume bins, L2 evidence, distance moved, retrace, and accepted
  bin count.
- `resolved` means price traded through a rail.
- `accepted` requires business left beyond the rail. A quick break is not enough.

Current quality labels:

```text
probing
thin/mixed
fast/no-build
building
accepted
```

## Current C# V0

Files:

```text
ContextMap/ContextMap.cs
ContextMap/ContextEngine.cs
ContextMap/ContextPainter.cs
ContextMap/ContextMap.csproj
```

Build output:

```text
C:\Quantower\Settings\Scripts\Indicators\ContextMap\ContextMap.dll
```

Panel rows:

```text
FRAME  current broad read and RTH O/H/L
BRKT   active low/high rails
LEG    current leg and quality
BELOW  rail stack below current trade
ABOVE  rail stack above current trade
msgs   sparse break/quality/failure/add-risk notes
```

Rail tokens:

```text
204 D3f  = demand rail near 204, strength 3, fresh
264 S1o  = supply rail near 264, strength 1, old
```

## Known Limitations

- Live C# still infers L2 events from aggregate DOM sampling and anchors them
  near current mid. This is less precise than true per-price L2 deltas.
- No historical backfill. It needs to run through ETH/preopen.
- Rail selection is primitive. The next improvement is showing richer rail
  stacks from both fresh preopen and older full-ETH memory, rather than relying
  on a single active bracket.
- The frame/day-type text is intentionally secondary. If it mislabels, focus on
  rail stack and leg-quality behavior first.
- The Python harness currently has more explicit data-gap protection than the
  C# live version, because live capture gaps should present as stale data rather
  than replay discontinuities.

## Tomorrow Review Checklist

Observe whether ContextMap helps answer these questions live:

1. Did the rail stack identify the areas price actually cared about?
2. Did the active bracket choose the right low/high rails, or should selection
   be more trader-driven / profile-aware?
3. When a rail broke, did the leg quality match tape feel: thin, fast/no-build,
   building, or accepted?
4. Did `ADD_RISK` appear in the right place, especially on open-auction
   extension adds?
5. Did the panel remain quiet enough during IB, or did it become another feed?
6. Which rail tokens were useful only because of trader profile context
   (HVN/LVN/VWAP/ONH/ONL/PD references)?

## Research Harness

Use this before changing C# thresholds:

```powershell
uv run --with polars --with numpy --with tzdata python .\research\auction_quality.py --date 2026-05-21 --symbol-dir NQM6 --analysis-end 12:30
uv run --with polars --with numpy --with tzdata python .\research\auction_quality.py --date 2026-05-20 --symbol-dir NQM6 --analysis-end 12:30
```

Outputs:

```text
research/out/auction_quality_YYYY-MM-DD.txt
research/out/auction_quality_YYYY-MM-DD.signals.csv
```
