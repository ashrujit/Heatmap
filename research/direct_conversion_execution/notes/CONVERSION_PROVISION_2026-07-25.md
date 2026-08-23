# Direct-Conversion Provision Findings — 2026-07-25

Research note. No runtime change proposed yet.

Question: EAR treats every LevelLedger `CONSUMED` transition as the same event —
one side overwhelmed the other, so trade with the winner. The thesis under test
is that this is wrong, because a conversion can also happen while the losing
side is perfectly happy to keep providing passive liquidity. Displacement after
the event proves nothing; what the book does is the discriminator.

- Probe: `research/direct_conversion_execution/scripts/conversion_provision_probe.py`
- Output: `research/direct_conversion_execution/out/conversion_provision/`
- Population: 167 synthetic conversions, 2026-07-23 (72) + 2026-07-24 (95),
  from `direct_conversion_lifecycle_dataset.py` over MarketRecorder captures.
- Replay: `MarketRecorder/research/validate_book_events.py` `BookReplay`,
  20.7M / 19.0M raw book events per day, 1 completed reset each, 0 gaps.
  Independently validated on both days: 22,736/22,736 (07-23) and 20,877/20,877
  (07-24) snapshots matched at best bid/ask and top-5, 100.00%, 0 gaps, 0
  incomplete resets.

## Method

Per conversion, the *losing* side's band is measured over the engagement window
— from when price last arrived at the band edge to when it broke through — using
the conservation identity from Skurry's `LevelStackTracker`:

```
size_end = size_start - eaten - cancelled + added
replenishment = added - cancelled = (size_end - size_start) + eaten
```

`eaten` is tape volume at the band's ticks with an aggressor hitting the losing
side. Band size is read directly off the reconstructed book, not integrated from
deltas. Classification is normalised by `max(size_start, eaten, 5)`.

Two measurement decisions were forced by the data and are worth carrying
forward:

1. **Accounting must be net, not gross.** A first pass integrating raw adds and
   removes found ~150 contracts of gross removal in a 2-second window over a
   band displaying 12, across 653 delta events. On NQ, gross level flow is
   cancel/replace flicker and says nothing about whether anyone was overwhelmed.
   That pass reported 87.5% "withdrawn" and was measuring noise.
2. **Normalising by starting size alone is degenerate.** 38 of 167 bands display
   *nothing* when price arrives — an LL band marks where L2 events clustered
   earlier, not resting size at attack time — which sends the ratio to infinity
   and auto-classifies them as defending.

Also note that dissolution (eaten vs pulled) and replenishment sign are **not**
independent axes. When replenishment is positive, `pull_uneaten` is zero and
absorb-fraction is mechanically 1.0. Reporting them as a 2x2 is circular, so
they are collapsed into one ordered class.

## What the losing side actually did

| class | n | share | 07-23 | 07-24 | meaning |
|---|---:|---:|---:|---:|---|
| defending | 68 | 40.7% | 35 | 33 | supplied *more* than was taken from them |
| drained_pulled | 39 | 23.4% | 15 | 24 | left without being hit |
| replaced | 35 | 21.0% | 13 | 22 | replaced almost exactly what was consumed |
| drained_eaten | 23 | 13.8% | 9 | 14 | eaten out and did not come back |
| unknown | 2 | 1.2% | 0 | 2 | no book read |

The headline is the population decomposition itself, which is a measurement
rather than an inference: **only ~14% of direct conversions are cases where the
losing side was genuinely eaten out and stayed gone.** In 40.7% the loser was a
net *supplier* through the whole engagement — the 500-lot seller who is happy to
keep providing. EAR currently treats all four classes identically.

Class shares are stable across the two days, unlike the feature ranking in the
2026-07-24 bucket pass, which was dominated by a date interaction.

## Link to outcome

Restricted to retested conversions (n=146). No-retest events are excluded as
immaterial — that is just the drive, and it is not tradeable. This restriction
also removes the leak in the earlier pass, where an untested band mechanically
could not fail inside the outcome window.

| class | n | held on retest | 07-23 | 07-24 | median life |
|---|---:|---:|---:|---:|---:|
| drained_pulled | 33 | 0.667 | 0.600 | 0.722 | 142s |
| replaced | 30 | 0.567 | 0.417 | 0.667 | 219s |
| defending | 60 | 0.550 | 0.567 | 0.533 | 68s |
| drained_eaten | 21 | 0.286 | 0.375 | 0.231 | 61s |

- `drained_eaten` vs `drained_pulled`: Fisher p = 0.011, odds 0.20.
- `drained_eaten` vs all others (73/125): Fisher p = 0.017.
- 95% CIs do not overlap: eaten [0.13, 0.50], pulled [0.50, 0.81].
- Direction replicates on both days independently.
- Median-life differences are **not** significant (eaten vs pulled p = 0.35;
  defending vs replaced p = 0.057). The effect is on hold/fail, not duration.

**The sign is the opposite of the naive reading.** Conversions where the losing
side was genuinely eaten out and did not return are the ones that *fail* most
(0.286). Conversions where the loser simply pulled hold best (0.667).

A hypothesis consistent with this, not yet tested: when the loser is truly
eaten, the aggressor spent real size to do it and nobody is left committed at
that price — the responsive counter-side then arrives against an exhausted
aggressor. When the loser merely pulls, the aggressor spent nothing.

`defending` conversions show the shortest median life (68s) alongside
`drained_eaten`, which is directionally consistent with the thesis that a loser
who keeps providing comes back to kill the conversion — but its hold rate is
mid-pack, so this is suggestive only.

## Did the loser come back?

The probe also measures the losing side's replenishment in the 30 seconds
*after* the break. This is not the full re-approach test — price has not
returned to the level yet — but it is the first read of "were they done, or were
they just repositioning."

| post-break loser | n | held on retest | 07-23 | 07-24 |
|---|---:|---:|---:|---:|
| gone (no return) | 105 | 0.600 | 0.612 | 0.589 |
| returns | 41 | 0.390 | 0.250 | 0.480 |

Crossing this with what they did during the attack gives the sharpest cell in
the study:

| provision class | post-break | n | held |
|---|---|---:|---:|
| drained_pulled | gone | 22 | **0.864** |
| defending | gone | 46 | 0.587 |
| replaced | gone | 22 | 0.545 |
| defending | returns | 14 | 0.429 |
| drained_eaten | gone | 13 | 0.308 |
| drained_pulled | returns | 11 | 0.273 |
| drained_eaten | returns | 8 | 0.250 |

`drained_pulled + gone` — the loser cancelled without being hit and did not come
back — holds 19/22 = 0.864 against 0.484 for everything else. Fisher p = 0.0009,
odds 6.76, 95% CI [0.68, 0.96], and it splits 0.818 (n=11) / 0.909 (n=11) across
the two days.

The same class with a post-break return collapses to 0.273. Whether the loser
comes back is doing real work here, independent of how they left.

Winner-side establishment does **not** help, and if anything inverts: splitting
on net winner size added during the attack gives 0.479 held for the high half
versus 0.603 for the low half. Whatever separates these conversions, it is not
the winning side showing up to build.

## Fixture check

E1021 (7/24 10:21:10 short, `direct_conversion_retest`, flattened 14s later on
`sponsor_failed:34`). The overlapping synthetic conversion at 10:18:30, demand
band 28352.50-28357.25, classifies **drained_eaten**, outcome `retest_failed`,
life 165s. It lands in the class that fails most, and the trade failed. This is
consistent, but it is one fixture and the class is the *modal failure* class,
not a unique explanation.

## Fixture-derived finding: magnitude x return (added 2026-07-25, later pass)

The trader named 2026-07-24 as a contrast set: bands churning 11:15-11:50 during
VPOC formation that should not be traded, versus the 11:50:22 long that
survived. EAR ground truth confirms it paused three times in the churn window
(adverse failures 64, 69, 71) and took no entry, then entered Long 2 at
28515.00/28515.25 at 11:50:22 on `direct_conversion_retest`, sponsor 84
Demand/Consumed 28502.75-28511.75.

The synthetic conversion 10s before that entry, band 28503.00-28507.00, reads:
seed 63, eaten 21, replenishment -42, `drained_pulled`, post-break return 0.
Thick book, meaningfully eaten, decisively withdrawn, never came back.

The churn-window conversions read the opposite: seed 0-9 and eaten 1-12 for most
of them, and where size existed (11:22:47, seed 49 / eaten 54) the loser came
straight back (+34).

**This exposed a defect in the method above.** Normalising by
`max(seed, eaten, 5)` puts a 2-contract event and a 54-contract event on the
same ratio scale. That was needed to stabilise `repl_ratio`, but it deletes the
dimension that separates churn from real consumption. The pooled analysis could
not see it.

Restoring absolute magnitude — `mag = max(seed_loser_size, eaten)` — against
whether the loser replenished within 30s of the break:

| | loser gone | loser returns |
|---|---:|---:|
| **thick** (mag >= 25) | **0.791** (n=43) | **0.250** (n=16) |
| **thin** (mag < 25) | 0.468 (n=62) | 0.480 (n=25) |

- thick stratum: Fisher p = 0.0002, odds 11.33, thick+gone 95% CI [0.65, 0.89]
- thin stratum: Fisher p = 1.0000, odds 0.95 — a clean null
- logistic interaction term: coef -2.48, z = -2.96, **p = 0.003**
- day-split in the thick stratum is near identical: gone 0.789 (07-23, n=19) /
  0.792 (07-24, n=24); returns 0.300 (n=10) / 0.167 (n=6)

Sensitivity: the thick-stratum split is significant at every magnitude cut from
10 to 40 and strengthens monotonically (gone 0.646 -> 0.880, returns 0.314 ->
0.200), while the thin stratum stays null at every cut. The return threshold is
significant from 0.10 to 0.75. Neither choice is knife-edge, and the
dose-response is stronger evidence than any single cut.

Reading: whether the losing side comes back matters enormously **when there was
something real to consume**. Below roughly 25 contracts of engagement nothing
predicts anything, because nobody was overwhelmed either way. That is the VPOC
churn regime, and its untradeability shows up as a predicted null rather than a
merely low-scoring bucket.

**This supersedes the `drained_pulled + gone` cell reported earlier.** That cell
was found by crossing two variables the analyst chose, and its p-value did not
price in the search. This one was specified by the trader's fixture before the
features were examined, has larger cells, a predicted null, and a dose-response.

## The outcome proxy is demonstrably wrong

Working the 12:10 fixture surfaced a defect that limits everything above.

EAR trade, directive `2026-07-24-directive-long-114851-9e773f`: Add Long 2 at
28623.75 (12:10:42.93, `direct_conversion_retest`, sponsor 102 Demand/Consumed
28617.75-28619.50), flattened 6 at 28614.75 (12:11:35) on `sponsor_failed:103`.
A 9-point loss.

This probe scores the matching conversion `retest_held`, life 59.5s.

The label contradicts the trader's verdict on the case. Every statistic in this
note is fitted against that proxy, including the interaction above. More
sessions would not fix it.

Two further notes from that fixture:

- LL synthetic and EAR agree closely — synthetic event 12:10:35.489 band
  28618.00-28618.50 vs EAR sponsor 102 at 12:10:35.42 band 28617.75-28619.50.
  70ms and half a point. Seeding differences are not a material concern.
- The add's own conversion sponsor never failed. It was superseded 12s later by
  sponsor 103, a Demand/**Lean** band at 28622.00-28622.25, and that is what
  failed. The conversion opened the trade; a lean band closed it. The same
  pattern appears at 11:53:01 (`sponsor_failed:86`, also a Lean band), where the
  failure renewed quickly and led to the profitable 11:55:43 re-entry.

## Caveats

- Two sessions. Cell sizes 21-60. p = 0.011 is not a result to build execution
  policy on by itself.
- The outcome is LL's own band hold/fail read, which is structural rather than a
  trade P&L. It is the closest available proxy for "did the consumption survive
  a test."
- The engagement-window boundary is tape-derived; the median span is 3.6s and
  the 90th percentile 17.4s. `corr(span, replenishment ratio) = 0.015`, so the
  classification is not a duration artifact.
- Replay fidelity is verified, with one limit. `validate_book_events.py`
  reconstructs **100.00%** of snapshots correctly on both days at best bid/ask
  and through top 5 levels. That certifies the reconstruction near the touch; it
  does **not** certify band sums that sit deeper than the top 5 levels, and this
  probe's bands sometimes do.
- This probe replays each day standalone, so 2026-07-24 shows 500,095 pre-seed
  deltas where the validator (which carries the prior day for seed continuity)
  shows zero. Confirmed benign: the day's reset completes before 09:32 and the
  earliest conversion is 09:33:10 with a valid book read. No conversion window
  falls in the pre-seed period.
- The 2 `unknown` rows are at 15:55 and 15:59 on 07-24, past the end of the
  event capture, so their windows never opened. An end-of-capture artifact, not
  a data-quality problem. They are excluded from all rates.
- The probe's own looser reconciliation (replayed band size vs the nearest 1 Hz
  snapshot within 5s of window open) shows median absolute error 4 contracts
  against a median band of 13. Given the validator result, that residual is
  attributable to 1 Hz alignment against a book churning at hundreds of events
  per second, plus depth beyond top-5 — not to replay error.

## Rebuild on EAR rails: the interaction did not replicate

Population rebuilt from EAR's own `RailOwned` / `band_source=Consumed` rails
(`research/direct_conversion_execution/scripts/ear_rails.py`), outcome = first-test verdict from EAR's
`RailHeld`/`RailFailed`, measurement = the same book probe re-pointed at EAR's
band boundaries. 306 rails over 7 sessions; 2026-07-16 discarded (no reset in
the day's files, all 15 rails unmeasurable), 22 `unknown`, leaving 273-278
tested rails across 6 sessions at a **66.6% base survival rate**.

Everything tested is null:

| test | result |
|---|---|
| magnitude x repair interaction | thick 0.725 vs 0.704, p = 0.81 |
| provision class spread | drained_pulled 0.745 -> drained_eaten 0.595, p = 0.17 |
| pulled+replaced vs defending+eaten | 0.724 vs 0.637, p = 0.15 |
| 11 continuous book features | only `eaten` (p=0.017) and `churn_ratio` (p=0.036) cross 0.05; Bonferroni threshold 0.0045 |
| trend alignment 5/15/30 min | p = 1.00 / 0.52 / 0.90 |
| excursion + return geometry (7 features) | p = 0.18 to 0.44 |

**The p = 0.0009 reported earlier does not exist on the correct foundation.** It
was fitted on a synthetic population recovering only half to three-quarters of
EAR's rails, scored against a label since shown to mislabel a real losing trade
as held. Roughly twenty features have now been tested against this outcome; the
multiple-comparison budget is spent, and any further slicing needs a fresh
pre-registered hypothesis on held-out sessions.

Instructive counter-example: in the trader-labelled 2026-07-23 10:40-11:30 trend
window, supply-side rails survived 8/8 and demand-side 0/2. No book feature and
no price-trend proxy recovers that split. The trader's structural read (gap-down
open, initial buying already failed, IB low breaking, repair unlikely) carries
information none of these measurements capture.

## Correction: band ids collide across sessions

EAR band ids restart per runtime session, so rail 102 on 07-22 and rail 102 on
07-24 are different objects. An early linkage keyed a lookup dict on `band_id`
alone across six days, silently matching orders to rails from the wrong session.
Any rail lookup MUST key on `(date, band_id)`.

Affected: the two trade-P&L analyses below. Not affected: the acceptance finding
and all book-feature nulls, which iterate rails as a per-day filtered list.

Corrected, the relationship is substantially **stronger** than the contaminated
version suggested (which read 31.2% vs 22.0%).

## Trade outcomes vs structural outcomes

147 `DirectConversion` order submits across the capture days, all linked to
fills via `root_object_id`. Exit attribution verified against the 11:50-12:11
2026-07-24 sequence (+9.13 / +58 / +14.75 / -9).

| role | n | win rate | median | mean |
|---|---:|---:|---:|---:|
| EnterBase | 97 | 26.8% | -10.50 | **-0.67** |
| Add | 50 | 30.0% | -7.88 | **+4.60** |

Adds carry the system; fresh entries are net negative. This matches the trader's
own read that these events justify leveraging an existing position rather than
initiating one, and it means pooling both roles into one population - as every
analysis above does - is questionable.

With correct `(date, band_id)` keying, 54 of 122 DirectConversion orders match a
same-session `Consumed` rail (the rest have roots that are Lean rails or
supported-reclaim objects). For those 54:

| rail first-test verdict | n | win rate | mean pts |
|---|---:|---:|---:|
| SURVIVED | 34 | 47.1% | **+17.00** |
| FAILED_FIRST_TEST | 20 | 15.0% | **-8.83** |

Mann-Whitney p = 0.0015; win-rate Fisher p = 0.021, odds 5.04.

**First-test survival is therefore a good target, not a compromise.** It tracks
real money. Exit policy still adds noise - the 2026-07-24 12:10 add lost because
sponsor 103, a Demand/*Lean* band promoted 12 seconds later, failed, with rail
102's own quality uninvolved - but that noise does not destroy the relationship.

## The timing problem: EAR commits before the evidence exists

Every one of the 54 matched orders is submitted **before** the rail's first test,
median 39.75s before it.

| reason | n | median seconds from rail ownership to order |
|---|---:|---:|
| `direct_conversion` | 17 | **0.0** |
| `direct_conversion_retest` | 33 | **20.5** (p90 86.5) |

31 of 54 orders go in within 5 seconds of rail ownership. Note also that EAR's
"retest" is a *proximity* trigger - price returning within
`DirectConversionMaxDistanceTicks` (20) of the band - which is not the same event
as the rail's `RailTested` contact.

Consequence: the acceptance feature cannot be computed at EAR's decision moment.
Truncating the value-area window at order submission leaves n=33 usable orders
and **no variance at all** (every one reads "value area away from band"), because
20 seconds after a conversion price is necessarily still displaced and the
auction has not yet had the opportunity to accept or reject the new area.

So the finding does not translate into a filter on the current decision. It says
something structural instead: **the information that discriminates accumulates
after EAR has already committed.** Using it requires deferring the entry until
the auction has had time to demonstrate acceptance - a change to decision
timing, not an added gate. That is an execution-policy question, not a research
one, and it should be the trader's call.

## RETRACTED (see the leakage section below)

The acceptance result recorded in the next section was later withdrawn. It is
kept here because the reasoning that produced it, and the tests that killed it,
are both worth preserving. Read the "Both candidate signals are functions of the
return itself" section before using anything below.

## The result: acceptance away from the fought area

Trader's framing, 2026-07-25: *"price escaping a fought area isn't proof that
price can continue in that direction. price sustaining means auction is already
successfully taking place elsewhere - why would it want to go back to where a
war was fought and won."*

Operationalised: over the interval from the conversion (`RailOwned`) to first
contact (`RailTested`), build the traded-volume profile and take the 70% value
area. Ask whether that value area still overlaps the fought band.

| | n | survived first test |
|---|---:|---:|
| value area moved **away** from the band | 128 | **0.805** |
| value area still **covers** the band | 149 | **0.557** |

Base rate 0.673. Fisher **p = 0.00001**, odds 3.28.

Reading: if the auction genuinely relocated, the return is a pullback into a
defended area and it holds. If value still includes the fought area, price never
meaningfully left - the escape was displacement without acceptance - and the
retest resolves against the conversion.

### Robustness

- **Not a duration proxy.** Holds in all three time-to-test tertiles and
  strengthens with duration: short 1.000 vs 0.704 (p=0.0025), mid 0.829 vs 0.491
  (p=0.0017), long 0.732 vs 0.238 (p=0.0001). Duration correlates with the
  feature at -0.051 and with survival at +0.071 (p=0.24).
- **Not a distance proxy.** POC-distance quartiles are non-monotone (0.644 /
  0.765 / 0.657 / 0.623). It is specifically whether value *relocated*, not how
  far price travelled.
- **Not contact-volume leakage.** Excluding the final 5s / 10s before contact:
  p = 0.00001 / 0.00007, odds ~3.22. At 30s it softens to p=0.066 through cell
  collapse (n=30), odds still 2.14.
- **Not one session.** Positive in 5 of 6 sessions (the 6th is n=3 vs 3 with no
  variance). Leave-one-day-out p ranges 0.00001 to 0.00151, odds 2.94 to 3.91.
- **Both sides.** Demand 0.829 vs 0.514; Supply 0.776 vs 0.595.
- Survives Bonferroni against the ~25 features tested in this study
  (threshold 0.002).

### Why this one and not the others

Every earlier feature measured **the fight** - what the losing side did while
being consumed. Those are all null. This one measures **what happened after**,
and specifically whether the auction accepted the new area. That matches the
trader's model: the consumption event is where a two-sided fight resolved, the
displacement afterwards is an after-effect rather than commitment, and the only
thing that indicates commitment is what the auction did with the new prices.

Still unmeasured: the book during the re-approach. That pass is running.

## Both candidate signals are functions of the return itself

Two features looked strong. Neither survives a causality test.

**Winner rebuilding at the fought area (book).** Measured over a 60s approach
window, this looked overwhelming - and the magnitude was the tell, because
order-flow features do not produce r = 0.58. Sliding the window's close away
from contact:

| lag before contact | win_net r | builds vs not | odds | end_loser_size r |
|---:|---:|---|---:|---:|
| 0s | +0.583 | 0.983 vs 0.454 | 67.95 | -0.625 |
| 15s | +0.284 | 0.755 vs 0.590 | 2.15 | -0.248 |
| 45s | +0.072 (p=0.23) | 0.659 vs 0.686 | 0.89 | +0.069 |

Monotone decay to exactly null with **balanced cells throughout**. That is
leakage: for a supply rail the band sits above price, so the loser's side only
has size there once price has arrived, and the winner's side is only consumed
once price cuts through. Both encode penetration - the resolution - rather than
predicting it. Genuine information would plateau, not vanish.

**Acceptance away from the fought area (tape).** This one fails differently.
Truncating the window early does not produce a balanced null; it makes the
feature **degenerate**. On a fixed cohort (time-to-test >= 120s), the
"still covers band" cell collapses 23 -> 17 -> 11 -> 5 -> 3 as the exclusion
grows from 0s to 90s. And in a fixed early window - 30s, 60s or 120s after the
conversion, with the test at least 60/90/150s later - only 3 to 4 rails out of
~250 ever read "still covers".

The reason is structural: immediately after a conversion price is displaced by
construction, so value is always away from the band. "Still covers" can only
become true once price has already returned and transacted at the fought area.
The feature is not forecasting the retest; it is detecting that an informal
retest is already under way before EAR's `RailTested` threshold fires.

**Conclusion.** Nothing found in this study predicts rail survival from
information available *before* price returns to the fought area. Both candidates
turned out to be measurements of the return. This is a negative result, but a
coherent one, and it agrees with the trader's own model: commitment only reveals
itself at the re-approach, and there is no earlier tell. The lever is therefore
not a predictive filter but **waiting** - deferring commitment until the
re-approach has actually happened and can be read.

## Standing conclusions

Items 1-3 of the earlier "Next" list were carried out during this session; their
results are the retractions recorded above. What remains true:

1. **The fight carries no predictive information.** Every feature measured at the
   consumption moment - provision class, magnitude, repair, churn, hidden
   liquidity, excursion and return geometry - is null against first-test
   survival on EAR's own rails.
2. **Neither surviving candidate was causally usable.** Both turned out to be
   measurements of the return rather than predictors of it.
3. **EAR commits before the discriminating evidence exists.** Median 40s before
   the rail's first test; 31 of 54 matched orders within 5s of the rail forming.
   EAR's "retest" is a 20-tick proximity trigger, not the rail's `RailTested`
   contact. This conclusion does not depend on either retracted finding.
4. **First-test survival is a sound target.** It predicts real trade P&L:
   +17.00 vs -8.83 mean points, Mann-Whitney p = 0.0015.
5. **Role matters and should not be pooled.** `EnterBase` -0.67 vs `Add` +4.60
   mean points across 147 tranches.
6. Open execution-policy question: both examined exits were triggered by a
   Demand/*Lean* sponsor failing rather than by the conversion sponsor. Whether
   lean promotion should supersede a conversion sponsor mid-trade is separable
   from the entry heuristic.

## Method notes worth reusing

Three causality failures occurred in this session and each has a cheap test:

- **Leakage** - slide the feature window away from the resolution. Real signal
  plateaus; leakage decays monotonically to null with cell sizes unchanged.
- **Degeneracy** - check cell balance as the window moves. A feature that goes
  constant is not a null result, it is an unusable feature.
- **Identity collision** - EAR band ids restart per runtime session. Always key
  rail lookups on `(date, band_id)`.
- **Decision-time availability** - before believing any result, check whether the
  feature could have been computed when the order was actually submitted.

## Related work in this repo

Codex has an independent and more extensive line on the same question, including
point-in-time profile topology (`research/direct_conversion_execution/scripts/direct_conversion_profile_field.py`),
return-episode atoms (`research/direct_conversion_execution/scripts/direct_conversion_road_steps.py`), and a
sponsor-lineage population of 2,591 consumed roots. That work converged
independently on `first_test_held` as an outcome. Nothing in this note modifies
or supersedes it; cross-read before extending either line.
