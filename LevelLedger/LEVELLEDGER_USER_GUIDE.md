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

For a shorter pre-market reminder page, open
[`LEVELLEDGER_CHEATSHEET.html`](LEVELLEDGER_CHEATSHEET.html).

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

### Failure Zone

An `LF` or `HF` badge marks an auction failure zone outside grey/no-owner
business.

Read it as:

```text
Continuation may have failed outside the messy area. If this zone holds, it can
become exit or thesis-quality structure.
```

The first paint is intentionally muted. It becomes stronger only after price
leaves and holds away from the zone. If price invalidates through it, the band
is removed. Failure zones use a separate purple visual language because they
are auction-state objects, not normal demand/supply ownership bands.

### Reversal Failure

An `RF` badge marks consumed continuation-side evidence at an extreme. It is
quieter than a failure zone and should be read only as an extreme repair object.

Read it as:

```text
Continuation-side supply or demand appeared at an extreme and was consumed into
the opposite side.
```

Inside normal accepted business, the same mechanical conversion is just a
consumed band, not a reversal failure. Reversal failures use a quiet
magenta-violet visual language to keep them distinct from ordinary ownership.

### Consumed Or Failed Band

A prior band can change meaning. Supply can fail and become demand. Demand can
fail and become supply. This is often more useful than the original band,
because it tells you where a previous claim was tested and rejected.

Read a consumed band as:

```text
The old owner was challenged. The opposite side has either accepted through it
or forced that area to change meaning.
```

The rail color also carries this distinction. Fresh/lean rails use a separate
blue/orange palette. Consumed rails keep the stronger green/red side colors and
the `C` badge. The point is to make "new claim" versus "old owner lost here"
visible without decoding small text under stress.

This is especially useful for add-on decisions after a probe has already
started working.

### Repair, Reaffirmation, And Failure

A fresh band is a claim, not proof. A new demand band above a low does not
automatically confirm the low, and a new supply band below a high does not
automatically confirm the high. The fresh band can still be consumed and used
against the idea.

The stronger read comes from the sequence around the band:

```text
old area is tested
one side tries to repair the auction
that repair is tested
the repair either holds, fails, or is consumed
```

If demand forms under an old supply test and then fails, the seller case gains
credibility. Buyers tried to create support for the test and could not defend
it. You do not need a brand-new supply band afterward to know that sellers have
evidence.

If demand holds at a low and supply above it fails, the buyer case gains
credibility. Sellers had a chance to defend higher prices and could not. That
is stronger confirmation than simply seeing another green band appear higher,
because a fresh higher demand band can still be converted into supply.

Useful shorthand:

```text
new demand above       = buyers appeared, still unproven
new demand above fails = lower demand is vulnerable
supply above fails     = sellers lost a defense point
last buyer repair fails under old supply = sellers can press
```

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

## Example: NQM6, 2026-06-03

This example uses the June 3 NQM6 session. Prices below use the trader's
shortened last-three-digits shorthand.

The day was different from June 2. June 2 was a cleaner post-IB extension after
the auction failed lower, rotated through the open/VWAP area, and rejected
sustained trade back below. June 3 was an open-drive liquidation day with a
large IB, no early IB extension, and repeated failures to continue at extremes.

The important lesson was not entry. The early short near `724` after the open
drive had already shown intent was valid, and the later leverage around `713`
and `596` was also structurally sound. The harder problem was exit recognition:
on a large drive day, if the auction reaches a fragile lower area and the first
opposite-side evidence does not get consumed immediately, that fragility is
information.

### IB Short: Exit Into First Real Fragility

The early short worked because supply appeared after the drive and price kept
accepting lower. The trade became vulnerable when the lower area stopped
behaving like clean continuation.

The relevant failure region was roughly:

```text
545-568
```

The point was not that this was a magic target. The point was that outside the
messy grey/no-owner area, lower continuation stopped proving itself. When
demand/supply confusion appears at a fresh extreme and same-side continuation
does not immediately consume it, an IB drive trade should become easier to
flatten.

For an IB trade, the useful exit instruction is:

```text
If the first meaningful failure or opposite-side demand appears outside grey,
take it seriously. The IB drive has already paid; do not require a perfect
reversal signal.
```

This is the use case for `LF` / `HF` failure-zone visibility. The badge is not
a trade signal. It is a warning that continuation has reached a burden-of-proof
point outside the contested area.

### Post-IB Short: Add Only After Supply Survives A Retest

The later short sequence was cleaner after the auction had time to advertise
ownership transfer.

Around `718`, price tested into a prior demand-consumed-supply area from the
open-drive sequence. That was not a clean, held `HF`. The research harness saw
an upper failure candidate around `713.75-723`, but that object was later
invalidated, which is correct: the first poke was still part of a broad
contested upper area.

The better add-on clue came afterward:

```text
grey zone forming
demand consumed as price travels lower
new supply appears overhead
overhead supply survives the next test
```

That pattern changed the risk quality of the add. The add was no longer just
"price is lower, sell more." It was:

```text
The auction is repeatedly proving that attempts to rebuild demand are being
converted into overhead supply.
```

Research replay supported that read. After the upper poke, supply kept
appearing lower and demand attempts kept failing:

```text
10:34  711-713 demand converted into supply, repaired lower
10:49  687 supply appeared after demand was consumed
10:55  681-682 supply appeared and repaired lower
11:14  696-697 supply held and was still active into 11:30
11:17  687-692 supply held and was still active into 11:30
```

Temporary demand did appear during the sequence, but it did not survive enough
to reverse the auction. The useful read was that the surviving structure into
the break below `680` was supply, not demand.

### Why Retested Adds Matter

This is the main execution improvement from the bands.

The NQ ladder can show pause, sweep, hesitation, refill, absorption, and panic,
but it is often too fast to answer who actually owns the price. The bands slow
that down into a structural object:

```text
where inventory changed hands
whether the first owner survived a retest
whether demand became supply or supply became demand
where the next add is wrong
```

Adds taken only after a supply band retests and survives have independent risk.
They are not just blended average-price risk. Each add has its own reason to
exist and its own nearby failure condition.

That is the practical solution LevelLedger is meant to provide. It is not an
entry machine. It is an execution-confidence layer that helps prevent one good
trade idea from becoming one oversized blended position.

## Example: NQM6, 2026-06-09

This example uses the June 9 NQM6 session. Prices use the trader's shortened
last-three-digits shorthand.

The day was a fast pre-news positioning auction. After the open was reclaimed
by sellers, the auction often traveled through thin prints without building
normal value. Many local bands formed and failed quickly. The lesson was not to
tune the detector faster. The lesson was to distinguish structure that offers
location from flow that only describes momentum.

### Fast Short: Last Buyer Repair Fails

Around `490`, the short was not based on a fresh supply band alone. The useful
object was the last buyer repair underneath an old supply test.

Replay sequence:

```text
10:13:44  511.75-513.50 demand candidate
10:14:00  511.75-513.50 consumed into supply as price moved to 505
10:14:06  511.75-513.50 supply tested
10:14:08  held
10:15:34  tested again
10:15:35  held

10:25:05  489.25-490.50 supply candidate
10:25:23  489.25-491 consumed into demand as price moved to 500.75
10:25:47  511.75-513.50 supply tested
10:25:50  511.75-513.50 supply failed
10:26:10  489.25-491 demand tested
10:26:11  held
10:26:40  tested again
10:26:43  held
10:26:46  489.25-491 demand failed
```

The important read was not simply that price pushed above old supply. The
important read was:

```text
buyers created a repair under the old supply test, then sellers broke that
repair.
```

That failure was enough seller commitment. If the trade was short near `490`,
the nearby failure condition was a reclaim and rebuild above the failed repair,
not the appearance of another supply band. The target logic was the next
downside objective, then look for actual auction failure or durable new demand
underneath.

The later `385` VOD chaos was only instability. Replay did not show a surviving
demand repair after it. VOD at a target can justify attention or partial
management, but it is not auction failure by itself.

### Held Low: Demand Holds And Supply Above Fails

Around `330`, the first local repair did not work. That is important because it
keeps the read honest:

```text
12:47:54  346.25-347.75 supply consumed into demand
12:48:03  tested
12:48:06  held
12:48:10  tested
12:48:12  held
12:48:14  failed
```

The later low was different:

```text
12:57:07  336.75-337.75 demand candidate
12:57:16  336 demand dominance row
12:57:43  336.75-337.75 demand owned
12:58:01  tested
12:58:03  held
```

The confirmation was not just another green band above the low. The stronger
confirmation was that supply above the held low failed:

```text
12:58:37  401.75-403.50 supply tested
12:58:38  failed
13:00:00  491-493.50 supply tested
13:00:01  failed
```

That sequence says sellers had chances to defend above the low and could not.
It is different from a new higher demand band, which can still be consumed into
supply and used to retest the low.

Useful shorthand:

```text
probe the first low only if risk is tiny
believe the low only after demand holds
upgrade the read when overhead supply fails
do not upgrade merely because fresh higher demand appears
```

### Old Supply That Does Not Hold

The same day had a useful contrast after `14:15`. Price approached the old
upper supply area around `980-020`, but the approach did not have the same
structure as the `490` short.

Replay showed fast VOD arrival and no nearby failed buyer repair underneath the
old supply test:

```text
14:30:09-14:30:17  VOD chaos from 992 toward 023
14:30:22           991.50-993 demand owned while price was already 013.50
14:32:48           998.25-999 supply owned
14:33:15           that supply failed
14:34-14:37        999-013 became two-sided failure/grey
```

Later supply attempts did not hold either:

```text
14:43  967.50-969.50 supply, failed by 14:47
14:51  964.50-967.25 supply, failed by 14:51
14:59  075.50-078.50 supply, failed by 15:03
```

In a more normal auction, supply forming after an old supply test should at
least push price into a meaningful test of the leg that created the move. Here
it did not. Sellers who tried to defend the upper idea had to give up as their
supply attempts failed.

This is the mirror of the `490` short:

```text
490  buyer repair fails under old supply -> sellers can press
020  seller repair fails around old supply -> shorts lose the claim
```

## Review Discipline

The goal is not to avoid failed reads. The goal is to make each failure useful.

The daily review process should keep bringing specific execution examples into
the guide:

```text
What was the day type?
Where could the auction reasonably fail?
Which band sequence made leverage safer?
Which band sequence said to stop pressing or exit?
Did a failure zone confirm, invalidate, or merely warn?
```

After enough examples, the user should have seen normal days, open auctions,
open drives, open-test-drives, clean IB extensions, failed IB extensions, and
lunch/PM repair sequences at least once. That is how the visual language becomes
execution memory rather than another indicator to interpret under stress.

## Common Mistakes

Do not treat every colored band as an instruction.

Do not keep long bias inside grey just because price is moving upward.

Do not short every supply band or buy every demand band. Ask what larger
structure the band is testing.

Do not upgrade a low just because fresh higher demand appears. Ask whether the
low demand held and whether supply above it failed.

Do not ignore failed bands. A failed band often contains more information than a
fresh untouched band.

Do not flatten a working trade on VOD alone. VOD is instability; auction failure
requires repair, opposing ownership, or failure of same-side continuation.

Do not use the panel as a scrolling signal feed. Use it to audit what the chart
has already made visually obvious.

## Short Version

Use the chart bands to see ownership.

Use grey areas to avoid false certainty.

Use fresh bands inside grey to see attempted resolution.

Treat first LF/HF or first demand/supply as a probe only. Upgrade it after a
held test and failed opposite-side structure.

When the last repair under an old level fails, the other side may already have
enough proof to press.

Use the panel to audit strength and cause.

Use profile, VWAP, prior levels, and the ladder to decide whether the visual
evidence matters.
