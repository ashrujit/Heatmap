# LevelLedger Ownership Rails

## Purpose

Ownership rails replace the old raw build-band overlay.

The problem is not missing information. The LevelLedger panel already shows the
right evidence. The problem is that, in real time, the trader has to parse panel
rows, profile, ladder, and recent auction structure quickly enough to act before
the clean decision point passes.

Rails are a belief-conditioning layer. They make the current thesis, its
falsification area, and the quality of follow-on business visible without adding
panel text or turning LevelLedger into a buy/sell signal.

## Core Distinction

Raw book events are evidence. They are not rails.

A rail appears only when an evidence cluster gets accepted by price:

- Demand leaning in and price moving higher can become a demand rail.
- Supply leaning in and price moving lower can become a supply rail.
- Supply leaning in and then getting overrun can become demand through supply
  consumption.
- Demand leaning in and then getting overrun can become supply through demand
  consumption.

The strongest confirmation is follow-on business in the direction of
consumption. Consumption without follow-on business remains provisional.

## States

- `owned`: price accepted away from the evidence area.
- `tested`: price came back to the rail.
- `failed`: price accepted through the wrong side of the rail.
- `contested`: both demand and supply rails fail repeatedly inside the same
  broad envelope.
- `no-owner`: multiple nearby rails failed in the same area, so the area no
  longer deserves directional interpretation. These are not supply or demand.
  They are churn / stop-run interaction zones where price moving through
  quickly argues against latching onto continuation.

Failed rails should stay visible briefly because their failure often matters
more than their formation. Failed rails that join a nearby failure stack are the
exception: they collapse into neutral no-owner context so they stop competing as
false precision.

## Thesis Rail

A thesis rail is the nearest accepted rail backed by prior same-side rails.

It is not a trade instruction. It is a falsification point.

The intended read is:

- If the trader already believes the sequence, this is where size can be
  defended because the wrong-location is close.
- If this rail fails, belief in the active sequence should drop sharply.

The rail should look more important, not describe itself with text.

## Contested Envelopes

When both sides fail inside the same area, internal rails should not keep asking
for attention. They should collapse visually into an amber contested envelope.

This preserves useful information while avoiding the false precision of many
short-lived middle bands.

The practical read is:

- extremes may still be tradable;
- the middle is a lower-confidence environment;
- size and patience should adjust unless a new thesis rail appears.

## 2026-05-28 Fixture

The important handoff was not just that demand appeared. It was that supply got
consumed and price kept leaving higher accepted demand behind it.

Key rails:

- `950.50-952` demand held from `09:51`.
- `960.50-964` supply consumed into demand at `09:56`.
- `006.25-007` supply consumed into demand at `10:07`.
- `077.75-084.50` supply consumed into demand at `10:24`.
- `137.50-139.50` and `145.25-149.50` converted into demand around
  `10:50-10:52`.
- The cleaner confirmation came when `175-176.75` supply failed upward around
  `10:59`, then `184.25-186.50` and `222.50-224.75` became accepted demand.

The `222.50-224.75` rail was psychologically important: if it failed, the
breakout through `175` and the earlier `140` conversion would be questionable.
It offered tight falsification and therefore a more defensible place to press
size.

## 2026-05-29 Fixture

This was the inverted lesson.

Early fragility near the high mattered:

- VOD chaos around `525.50`.
- Supply around `520-526`.
- A p-shaped top with negative delta from profile context.

But the decisive point was later:

- Demand appeared around `499.50` and `500-502.25`.
- Supply around `501.75-502.50` was briefly consumed into demand.
- Then `501-502`, `499.50`, and `491-493` demand failed.

Once the `491-499` demand stack failed, the long thesis was broken. If the
trader was not flat or short by then, the clean decision point had passed.

This is exactly why the overlay must show sequence, not rules:

- upper fragility;
- provisional demand stack;
- thesis rail;
- rail failure;
- long-side belief collapse.

## 2026-06-04 Fixture

This session clarified the difference between failure evidence, leverage
permission, and the actual place to press size.

The open was a double-distribution ETH / open-auction problem. The important
early object was the `277-278` low-failure area. It did not mean "add here" by
itself. It meant the downside auction had failed in the wrong location and the
long thesis now had a clear falsification line. The cleaner leverage point came
after follow-on ownership: `291-293` supply failed, `297-304` converted, and
`308-310` established as accepted demand.

The same distinction appeared after the first responsive selloff. The
`365-376` repair was the first place where the short auction failed, but it was
not proof that the full upside auction had resumed. The `391-398` repair attempt
was noisy and failed quickly. The stronger confirmation came when `415-417`
supply failed upward, then `419-424` and the `437-443` / `444` area rebuilt as
demand. In review language:

- `LF` / `HF` / `RF` gives permission and defines risk.
- The next accepted shelf is the better size point.
- If the first repair cannot reclaim the reversal origin, the reversal case
  strengthens.
- If the repair rebuilds above the first opposing shelf, the reversal case is
  probably only a temporary auction failure.

The `468-469` rotation is the useful reversal template from this day. Supply
appeared near the high, buyers briefly consumed it, and then top demand failed:
`457-458` demand failed, `455` demand failed, and `458.75-462.50` flipped into
supply. The first sequence still had to be managed tightly because that supply
failed upward at `11:24:51`. The cleaner seller control came later as
`447.75-453.50` and `442-445.75` flipped into supply. The correct short target
was not open or IBL by default; it was the first lower `LF` / repair, which
appeared around `364.75-366.25` repairing to `376.50`.

The planned exit near the prior-day-low area was also clarified. The
`494-500` region was a target and a contested continuation area, not a reason to
manage an original long indefinitely. Later upward resolution through that area
was a fresh auction question, not proof that exiting the planned long was wrong.
Once local supply resolved higher, new longs still had to be judged against the
next prior-day value/supply context.

## Visual Grammar

- Active demand/supply rails: side-colored bands.
- Tested rails: slightly stronger, because the wrong-location is in play.
- Thesis rails: stronger edge/right-side cap.
- Failed rails: faded and dotted.
- Contested envelopes: amber, broad, and visually behind rails.
- No-owner envelopes from adjacent failed rails: light grey, low-priority, and
  visually behind rails.
- Consumed rails get a small `C` badge before any refill badge. `C R+` means
  opposite-side evidence was consumed and same-side depth refilled behind the
  conversion. The rail color still carries the resulting side.

No text belongs inside the panel for this layer. At most, tiny right-edge labels
can be considered later if the bands alone are not readable enough.

## Non-Goals

- Do not classify trades as long/short/exit.
- Do not couple to ContextMap or TapeLedger.
- Do not duplicate the panel rows.
- Do not show every true internal rail when a broader contested envelope is the
  better decision object.

## Open Tuning Questions

- How many rails should survive on screen during a strong trend day?
- How aggressively should failed non-thesis rails fade?
- Should contested envelopes require VOD or high event density, or is repeated
  two-sided rail failure enough?
- Should a thesis rail require consumed evidence specifically, or can a clean
  same-side lean qualify when backed by prior accepted rails?
