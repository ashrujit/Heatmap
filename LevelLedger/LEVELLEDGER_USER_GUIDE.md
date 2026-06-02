# LevelLedger User Guide

## Acknowledgement

LevelLedger grew out of a long process of replaying market data and trying to
make order-flow context easier to read in real time. The Skurry work helped
make that process possible. This guide is written partly as a give-back to
Udit, whose code and research direction helped improve this tool.

## What LevelLedger Is

LevelLedger is a market-structure aid for reading live auction context. It
does not tell you to buy or sell. It watches traded flow and L2 book behavior,
then reduces repeated evidence into price zones.

The useful question is not "what event just fired?" The useful question is:

- who appears to own this area;
- where that ownership is wrong;
- where nobody owns the area anymore;
- whether price is accepting above, below, or inside prior evidence.

The chart bands are the primary read. The panel is an audit layer.

## Band Language

Use the bands as a visual shorthand for auction state.

### Demand Band

A demand band means demand-side evidence has accumulated around that area.
Examples include bids building, bids leaning in, offers pulling, or offers
moving away in a way that supports demand.

Do not read it as "go long here." Read it as:

```text
Demand has made a claim here. If my larger context is bullish, this area can be
a place to test whether the claim holds.
```

### Supply Band

A supply band means supply-side evidence has accumulated around that area.
Examples include offers building, offers leaning in, bids pulling, or bids
moving away in a way that supports supply.

Do not read it as "go short here." Read it as:

```text
Supply has made a claim here. If my larger context is bearish, this area can be
a place to test whether the claim holds.
```

### Grey Or No-Owner Area

Grey is one of the most important states. It means prior claims became
contested, failed, or overlapped enough that clean ownership should no longer be
inferred.

Grey does not mean nothing happened. It means too much conflicting ownership
happened.

Read grey as:

```text
This area is not clean. Do not infer continuation just because price moves
through it.
```

If a fresh demand or supply band appears inside a grey area, that is useful
information. It tells you where the auction is trying to resolve, but it still
needs confirmation from price, profile, VWAP, prior levels, and the ladder.

### Consumed Or Failed Band

A prior band can change meaning. Supply can fail and become demand. Demand can
fail and become supply. This is often more useful than the original band,
because it tells you where a previous claim was tested and rejected.

Read a consumed band as:

```text
The old owner was challenged. The opposite side has either accepted through it
or forced that area to change meaning.
```

This is especially useful for add-on decisions after a probe has already
started working.

### VOD / Chaos Marks

VOD marks are neutral. They show instability in the book, not direction.

Read them as:

```text
The book is unstable here. Something is changing quickly, but direction must
come from price, bands, tape, and context.
```

## Panel Language

The panel exists so you can inspect the evidence behind the visual bands. It is
not intended to be the main thing you stare at while making decisions.

Panel rows answer questions like:

- what price did the evidence cluster around;
- when did it become visible;
- how strong was it;
- did it appear as demand, supply, VOD chaos, trade impulse, or node movement;
- did the row update, weaken, or get superseded.

Use the panel when you need to verify strength or ferocity. Use the bands when
you need to make a fast structural read.

Good workflow:

```text
Read structure from the bands.
Check the panel only when the strength or cause matters.
Return attention to price, ladder, profile, and risk.
```

If you have to constantly parse panel text to understand the trade, the chart
language is not doing enough work.

## Practical Workflow

LevelLedger works best as a context reducer.

1. Start with larger context: open type, VWAP, prior day high/low, IB, profile,
   TPO, value, and major reference levels.
2. Use grey/no-owner areas to avoid forcing directional bias.
3. Use fresh bands inside grey areas to see where the auction is trying to
   resolve.
4. Treat first contact with a meaningful area as a test, not proof.
5. Wait for ownership to resolve beyond the contested area before assuming the
   trade idea is working.
6. If price reaches a major objective and opposing ownership appears, ask
   whether same-side ownership can consume it cleanly. If not, the thesis has
   reached a structural decision point.

## Example: NQM6, 2026-06-02

This example uses the June 2 NQM6 morning session. The point is not to describe
a mechanical setup. The point is to show how the bands and panel helped reduce
order-flow complexity into readable auction structure.

### Context

The trader was away during IB and returned after price was already above the
open and trying to continue higher.

Early attempts around `30613` and `30601` were given up around breakeven because
the area quickly became contested and the high break did not continue cleanly.

Replay later confirmed that this was good process. Around B period, roughly
10:10-10:15, the broad `30572-30628` area had become no-man's land. The replay
showed a larger two-sided failure cluster:

```text
10:01:50-11:06:37  30578.75-30635.25  fails D/S=19/17
```

The useful read was:

```text
Price is above the open, but the current area is not owned. If the auction is
going higher, it may first need to break lower out of this grey area and prove
support below.
```

### Probe Area: 30534-30540

Below the grey area, the trader was watching:

```text
30552-30556  prior supply area, still important
30534-30540  untouched demand area near VWAP
```

The initial `30538` entry was a probe at a meaningful structural test. It was
not the full trade idea. The mental condition was:

```text
This probe is only valid if 30534-30540 holds and price can later find footing
above 30556-30558. If sustained volume accepts into 30534-30540, the day read
must change.
```

At about 10:30, price had pulled back close to VWAP:

```text
10:30 last=30559.50  VWAP=30548.43  distance=+11.07
```

That made the lower demand test meaningful. It was no longer just chasing an
auction far above VWAP.

### Confirmation Gate: 30556-30558

The confirmation was not the probe holding for a few seconds. The confirmation
was the auction moving back above the prior supply area and proving it could
hold there.

Replay sequence:

```text
10:28:31  30537.50-30538.50 demand tested and held
10:28:55  30545-30548 demand owned
10:29:13  30557.75-30559.75 supply failed
10:29:53  30556.25-30557.50 became demand via supply consumption
10:31:44  30577.50-30578.50 became demand via supply consumption
```

This is the essential read:

```text
The probe area held. The old supply around 30556-30558 failed. New demand
established above it. The auction started resolving upward from below the grey
area instead of simply pausing at VWAP.
```

### Entry Points In Structure

The useful structural points were:

```text
30538  probe at VWAP / lower demand test
30558  confirmation after 30556-30558 supply failed and converted
30578  continuation after the next consumed-demand step
30607  later continuation as demand climbed through the prior grey area
30614  continuation while the auction kept accepting higher
```

The important detail is sequence. The later points made sense because ownership
had stepped upward. Without the `30534-30540` hold and the `30556-30558`
conversion, the same prices would have been much less meaningful.

### Objective Area: Prior-Day High Around 30693-30694

The prior day's RTH high was:

```text
2026-06-01 RTH high: 30693.00
```

That made the `30694` region a natural objective and a structural question:

```text
Can demand consume prior-day-high supply and drive accepted business higher?
```

Replay into the area showed mixed ownership:

```text
11:54:35  30687.50-30689.50 supply owned
11:56:19  that supply failed as price pushed into 30693.75
11:57:04  30692.50-30695.75 flipped back to supply via demand consumption
11:59:33  30696-30697 supply owned
12:00:23  30692.25-30696.50 supply owned
12:06:27  30688-30689 demand owned
12:07:53  30692.75-30698 demand via supply consumption
12:08:53  30708.25-30709.75 supply via demand consumption
12:09:12  30704.25-30705.75 supply owned
```

Demand did appear after supply, but it did not cleanly consume everything and
drive higher with authority. The objective had been reached, and the answer was
not clean continuation.

### What Worked

The bands reduced the active decision-making burden. The trader did not need to
constantly read panel text and mentally process who did what at each price.
The bands carried most of that context visually.

The panel still mattered. It was useful for checking strength, timing, and
ferocity when a band or transition needed verification. But it was not the main
decision surface.

## Common Mistakes

Do not treat every colored band as an instruction.

Do not keep long bias inside grey just because price is moving upward.

Do not short every supply band or buy every demand band. Ask what larger
structure the band is testing.

Do not ignore failed bands. A failed band often contains more information than a
fresh untouched band.

Do not use the panel as a scrolling signal feed. Use it to audit what the chart
has already made visually obvious.

## Short Version

Use the chart bands to see ownership.

Use grey areas to avoid false certainty.

Use fresh bands inside grey to see attempted resolution.

Use the panel to audit strength and cause.

Use profile, VWAP, prior levels, and the ladder to decide whether the visual
evidence matters.

