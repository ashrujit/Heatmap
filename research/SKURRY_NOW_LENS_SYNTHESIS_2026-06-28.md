# Skurry Now Lens Synthesis - 2026-06-28

## Scope

This note synthesizes the first pass across:

- T1 Lean
- T2 Driver
- T3 Road / Terrain and episode lifecycle
- T4 Brick contact response
- T5 Horizon
- T6 Pressure field
- T7 Refill after sweep
- T8 Book thinning
- T9 Hidden liquidity
- sponsor failure renewal
- band lifecycle fixture taxonomy

Primary evidence is the clean MarketRecorder `NQU6` replay from `2026-06-23` through `2026-06-26`. Old live EAR logs from the mixed MNQ/NQ period are not used as evidence.

## High-Level Read

The worthwhile path is not better band discovery. It is better lifecycle classification after a band is approached, touched, pierced, failed, consumed, or renewed.

The repeated pattern across notes:

- static readings at the exact anchor are usually too blunt;
- failure timestamps are often too late;
- broad consumed-conversion rows are noisy;
- open road / thinning / Horizon are context, not ownership;
- the next owner after the interaction matters more than local price movement;
- episode type matters: directional initiative, balance/distribution, no-build, and repair should not be pooled.

## Threads Worth Discussing In Depth

### 1. Direct Conversion As Ownership Relocation

This remains the cleanest positive thread.

Supporting notes:

- T1 Lean: explicit opposite-candidate/direct conversions with Lean aligned to the resulting side were the strongest Lean cut.
- T2 Driver: direct conversions did not require active Driver, so this is not just tape-speed continuation.
- T4/T7/T8/T9: broad Brick/refill/thinning/hidden-liquidity did not explain direct conversion.

Working interpretation:

- Direct conversion may be a relocation event: one side offered supply/demand, that area was consumed, and the resulting owner absorbed enough that price has little reason to revisit immediately.
- The value is not "more speed now." The value is that ownership moved.

Best next episode targets:

- `20260625_1215_1230_supply_burst`, especially the `12:20:51` direct conversion area.
- `20260624_1055_1110_supply_transition`, as a compact contrast where some consumed rows churned.
- Stress later on `20260623_1000_1130_supply_claims` and `20260623_1330_1600_supply_resolution`.

### 2. Sponsor Failure Renewal / Renewal Watch

This is the most practical EAR/LL thread.

Supporting notes:

- T3 episode pass: a material minority of mechanical failures were fake failures or no-follow-through, not terminal.
- Sponsor renewal pass: same-side bands beyond failure appeared in `54 / 479` sponsor failures, with median worse location around `49.5` ticks.
- T2 Driver: aligned Driver on failure mostly confirms break-side effort, but fake-failure renewal still exists inside those rows.
- T4 Brick: failure rows are too late for contact response, so the precursor test/contact must be inspected.

Working interpretation:

- A sponsor can mechanically fail and still be the relevant side if same-side ownership renews nearby or just beyond failure before the opposite side proves control.
- This does not argue against flattening on sponsor failure yet.
- It argues for a post-failure `renewal-watch` research state so retry logic does not blindly wait for a much worse fresh seed.

Best next episode targets:

- `20260624_1055_1110_supply_transition`, especially the `11:01:01` fake-failure renewal area.
- `20260625_1215_1230_supply_burst`, especially the `12:28:18` fake-failure / same-side continuation area.
- Holdouts: `20260625_1055_1110_supply_burst`, `20260626_1305_1310_supply_test_survived`.

### 3. Good Tests Look Like Absorbed Aggression, Not Quietness

This is the strongest conceptual refinement from T2.

Supporting notes:

- T2 Driver: on band tests, `opposed_active` and `weak_opposed` Driver had high owner-defended rates. That means aggression into the band failed to take ownership.
- T4 Brick: held/refilled and display survival are meaningful only at the touch/test anchor, not later failure anchor.
- T7 Refill: delayed refill leans defensive, but no-refill does not mean failure.
- T9 Hidden liquidity: hidden proxy is sparse, but opposed hidden can warn that visible ownership may be misleading.

Working interpretation:

- A good test may be: opponent attacks the band, visible/passive owner survives or reloads, and then the owner moves away with consequence.
- Quiet tests can hold too, but they prove less.
- The research target should be "opponent tried and failed" versus "no one cared."

Best next episode targets:

- `20260625_1215_1230_supply_burst` because it is compact and has multiple weak/continued hold rows.
- `20260624_1055_1110_supply_transition` for first credible supply transition behavior.
- Balance counters such as `20260624_1110_1210_repair` after the primary examples are understood.

### 4. Move-Away Quality Is More Promising Than Approach Tape As Currently Measured

Supporting notes:

- T3 episode pass: fixed-window approach tape did not separate labels well.
- T3 episode pass: move-away speed separated cleaner outcomes better than approach.
- T6 Pressure: static pressure at the band did not classify tests/failures.
- User/Udit discussion: moving away may be less intense/more controlled when intention is to fail; raw speed alone may not be the right dimension.

Working interpretation:

- We should not use fixed `x seconds after touch` as the outcome.
- But the move-away phase probably carries useful information if measured inside a defined micro-auction:
  - controlled rejection;
  - emotional burst with no follow-on ownership;
  - slow balance rotation;
  - break-side effort that destroys the next opposite structure.

Best next episode targets:

- Same as the primary fixtures, then directional-with-churn stress fixtures.
- Do not use broad full-day windows until micro-auction boundaries are defined.

### 5. Episode Type Is A Required Gate

Supporting notes:

- Fixture pack: primary directional fixtures differ materially from churn, balance, no-build, and holdout fixtures.
- T3: failure labels vary by fixture bucket.
- T8: thinning needs phase stratification.
- T5: far walls and open space are context, not ownership.

Working interpretation:

- A lifecycle signal should first prove itself inside directional initiative episodes.
- It then needs to fail gracefully in balance/distribution counters.
- Long directional-with-churn windows must be segmented before judging rules; otherwise everything becomes a 55/45 bucket.

## What Looks Less Worth Pursuing Alone

These are not useless, but they should not be standalone rule candidates:

- Lean at formation for missed-band discovery.
- Lean as an `x ticks / y seconds` threshold modifier.
- Static side-aware pressure at the anchor.
- Open road / front Horizon as a continuation rule.
- Book thinning as ownership.
- Hidden-liquidity proxy as a primary classifier.
- No-refill as failure.
- Broad consumed-conversion rows as equivalent to explicit direct conversion.

## Thinning / Reloading Answer

The micro-level thinning/reloading concept is partially covered, but not fully.

Covered pieces:

- T4 Brick covers contact response at the touched band: survived, depleted, pulled, refilled, no initial brick.
- T7 Refill covers 2-second same-side refill/reappearance after sweep/contact.
- T8 Book thinning covers broader top-of-book depth disappearing ahead of travel.
- T3 Terrain covers opposing book rebuilding beyond a break.
- T6 Pressure tries to summarize adds/pulls spatially, but the static broad pass was too blunt.

What is not yet covered:

- A continuous micro-auction view as price bounces around a band.
- Pull/reload behavior at the upper and lower extremes of the local range, not only at the resting band price.
- Repeated touch/pierce/reload sequences before a lifecycle label prints.
- Whether liquidity thins ahead while same-side support reloads behind.
- Whether opposing liquidity reloads just beyond failure before the break side proves control.
- Whether same-side renewal appears beyond a failed sponsor and then remains untested.

Conclusion:

- This should not be treated as a totally new thesis, but it is not solved by any one thesis.
- It is the integration layer across T3/T4/T6/T7/T8.
- Call it `micro-auction pull/reload` or `range-extreme reload`.

## Proposed Micro-Auction Pull/Reload Table

For each selected test/failure/conversion episode:

- episode id and fixture id;
- band id, band side, source type;
- micro-auction high/low boundary;
- approach edge and target band;
- approach Driver and tape volume;
- approach-side thinning ahead of travel;
- owner-side display at contact;
- contact attack size, pulled estimate, survived size;
- 250ms and 2s reload/refill;
- pierce depth and time beyond band;
- same-side renewal beyond failure, if any;
- opposing renewal beyond failure, if any;
- move-away Driver, tape, and speed;
- next ownership consequence: owner destroys opposite, opposite renews, balance, or no follow-through.

This table should be event-level and small at first. The primary fixtures are enough.

## Suggested Next Work Order

1. Manually/event-level review `20260624_1055_1110_supply_transition`.
2. Manually/event-level review `20260625_1215_1230_supply_burst`.
3. Build the micro-auction pull/reload table for only those two fixtures.
4. Test against balance counters:
   - `20260624_1110_1210_repair`
   - `20260625_1000_1055_repair_balance`
5. Stress against directional-with-churn:
   - `20260623_1000_1130_supply_claims`
   - `20260623_1330_1600_supply_resolution`
6. Keep holdouts untouched until the table has a stable interpretation:
   - `20260626_1305_1310_supply_test_survived`
   - `20260625_1425_1545_supply_into_close`
   - `20260625_1055_1110_supply_burst`

## Current Practical Takeaway

The strongest research direction is a phase-aware lifecycle classifier:

- not "find more bands";
- not "Lean/Driver says trade";
- not "open road means go";
- but "when this band was attacked, did the owner absorb, reload, renew, and then create consequence?"

That is the path most likely to improve EAR/LL detection logic without turning the Now Lens components into standalone signals.

## Discussion Addendum - Direct Conversion, Driver Phase, And Old Evidence

### Direct Conversion May Be Inventory Memory, Not Always Immediate Entry

The clean direct-conversion finding should be split into two use cases:

- immediate tradeable conversion, where the auction converts the level and trades away without needing much revisit;
- latent inventory memory, where a DCS/SCD level formed inside chop does not immediately produce a clean trade, but later becomes meaningful when the day resolves directionally.

This may explain the `2026-06-26` mid-morning chop observation:

- demand kept appearing lower and supply kept appearing higher;
- many were DCS/SCD type objects;
- inside the TPO/balance both sides appeared to fail;
- later in PM directional selling, those earlier structures were not all truly failed in the same practical sense.

Working hypothesis:

- Direct conversion inside balance may mark where inventory changed hands, but the auction has not chosen a directional sponsor yet.
- When the later directional initiative begins, those old conversion areas can become reference memory even if they were not immediately tradeable.
- Therefore direct conversion should not be one label. It may need:
  - `active_direct_conversion`: immediate ownership relocation with follow-through;
  - `latent_conversion_memory`: conversion inside balance/chop that becomes relevant only after initiative resolves;
  - `churn_conversion`: broad synthetic consumed row with no durable ownership implication.

### Driver Depends On Auction Phase

T2 should not be read as "good tests require opposing Driver."

A better split:

- **Repair test after fast move:** opposing aggression into the band is valuable evidence if the owner absorbs it. This is the clean "attacker tried and failed" case.
- **Mature directional initiative:** the market may already accept the direction, so a good test may be quiet. There may be no need for large opposing aggression because participants already see the directional auction.
- **Late/chase failure:** aligned Driver at a test can be bad if it means the auction is already traveling through the level rather than proving passive ownership.

This explains why T2 pressure appears in some successful tests and not others:

- repair continuation needs proof through absorption;
- mature initiative may need only no-opposition / controlled continuation;
- balance/chop needs even stricter context because both sides can print temporary conversions.

Possible labels:

- `absorption_test`: opposed Driver present, owner survives, then destroys opposite structure.
- `quiet_acceptance_test`: little opposing Driver, owner survives, move away is controlled, no immediate revisit.
- `late_aligned_test`: aligned Driver through/away from the band, high risk that the test is already failing or late.

### Edge Supply / Demand May Behave Differently

Supply at a day high, IB high, ETH rail, prior-day reference, or range edge may not behave like mid-range supply.

Observation to test:

- some edge supply bands that fail a demand sponsor do not get tested for a long time, or at all;
- others get retested quickly and become ordinary balance structure.

Potential causes:

- location relative to ETH/prior-day rails;
- whether the edge created excess / trapped inventory;
- number and quality of prior rotations into that edge;
- whether value migrated away after the edge response;
- whether the failed sponsor area was revisited;
- whether same-side renewal appeared beyond the failed sponsor;
- whether the auction was in directional initiative versus balance.

Research split:

- `edge_rejection_no_retest`: edge ownership appears, price accepts away, no quick test.
- `edge_failure_revisit`: edge claim fails, price revisits and clears trapped inventory.
- `edge_balance_chop`: edge supply/demand is just range boundary inventory and gets repeatedly tested.

### Old Evidence Should Probably Not Be Binary Dead/Alive

Sponsor failure renewal has the most direct design implication.

Current practical concern:

- EAR exits on sponsor failure;
- if retries remain, it waits for fresh seeded evidence;
- in fake-failure / renewal cases, that fresh seed can arrive materially worse.

Working implication:

- old evidence should not remain an active sponsor after failure;
- but it also should not become useless immediately;
- it can become an inactive reference area that participates in renewal-watch logic.

Possible state split:

- `active_sponsor`: current protective ownership object.
- `failed_reference`: sponsor failed mechanically; not protective, but still tracked.
- `renewal_watch`: same side renews near/beyond failed reference before opposite side proves durable ownership.
- `terminal_failure`: opposite side owns consequence, failed reference loses tradeability.
- `old_evidence_tradeable`: later context makes the old area tradeable again, but only through a new lifecycle event such as renewal, direct conversion, or accepted edge rejection.

This keeps the discipline of flattening on sponsor failure while preserving the practical information that the old evidence area may still be the best location.

## Discussion Addendum - What Problem Are We Actually Solving?

The current research/product problem is not earlier or better band detection.

Repeated conclusion:

- current LL/EAR band math is not the source of the operational problem;
- better outside math exists, but adding it does not solve the failure modes we actually see;
- loosening gates or finding more bands risks adding noise, not edge.

The runtime also does not behave like a passive DCS/SCD edge-limit strategy:

- entry/add routing is vanilla market order routing after evidence completion;
- direct conversion can route immediately once the `CONSUMED` confirmation completes and quote is close enough;
- if a converted band is too far from the quote, runtime can hold a pending retest;
- supported reclaim waits for failed opposing evidence plus same-side support/reclaim completion;
- it does not simply leave a limit at the resting DCS/SCD edge and hope the edge holds.

Therefore, better prediction of a resting DCS/SCD edge test is probably not the main product problem either.

### Primary Product Problem - Sponsor Failure Renewal

This is the problem with direct practical consequence:

- a sponsor mechanically fails;
- the runtime exits or, if flat/base-only, waits for fresh eligible evidence;
- the same side may renew quickly near or just beyond the failed sponsor;
- waiting for a fresh seed can produce a materially worse location;
- this affects both leveraged position management and base-only retry behavior.

Research question:

- What distinguishes sponsor failures that immediately renew from failures that go into deeper repair or terminal opposite ownership?

Candidate characteristics to compare:

- same-side band beyond failure within a short time/distance window;
- whether the beyond band remains untested for a while;
- failed sponsor area revisit timing;
- Brick/refill on the preceding touch/pierce, not the later failure row;
- Driver phase after failure: break-side effort continuing versus fading;
- opposing book rebuilding just beyond the failure;
- edge location: day high/low, IB high/low, ETH rail, prior-day reference;
- episode type: mature directional initiative versus balance/repair/no-build.

Potential product direction:

- keep sponsor failure flatten discipline;
- add a research/runtime concept of `failed_reference` and `renewal_watch`;
- use old evidence as context for re-entry quality, not as an active sponsor after failure;
- allow renewal-watch to preserve the old area as strategically meaningful when same-side evidence renews quickly.

### Secondary Product Problem - Directional Flip After Stacked Opposite Claims

The `2026-06-26` upper-supply case is a different problem:

- price approached upper supply with stacked SCD/demand claims below;
- visually, demand had claims;
- upper supply test held;
- DCS appeared just below it;
- the auction flipped toward selling;
- successive DCS areas then did not retest because the sell initiative was obvious;
- LF below each DCS paused EAR, then clearing the LF produced another displacement / DCS / LF sequence;
- if not positioned from the initial flip, the operator can get stuck reissuing directives while context expands and price worsens.

This may not have a clean automation solution. It may be a planning/dispatch timing problem:

- once price is at major upper supply, stacked demand below may be provisional rather than trustworthy;
- the key trade may be "upper supply test holds and demand stack fails to create acceptance," not "wait for every later DCS to retest";
- in mature selling, good tests may be quiet because everyone sees the direction and wants in.

Research question:

- Were the stacked SCD/demand claims below upper supply actually low-quality claims before the flip, or were they valid balance-memory claims that lost relevance only after upper supply held?

Candidate characteristics to compare:

- whether stacked SCDs formed inside balance/TPO rather than directional initiative;
- whether they destroyed opposing structure or only printed local conversion;
- whether they sat below a major supply/edge where demand claims should be discounted until the edge test resolves;
- whether move-away from the SCDs lacked controlled follow-through;
- whether upper supply had edge context: day high, IB high, ETH/prior-day rail, repeated rotation, excess, or no-retest behavior;
- whether the first held upper-supply test created a better sell directive than waiting for later DCS/LF sequences.

Potential product direction:

- not "ignore stacked SCD";
- instead, label them as `provisional_stack_under_edge_supply` until the edge supply test resolves;
- if edge supply holds and same-side supply/DCS appears just below, allow the operator to dispatch early around the flip rather than waiting for lower retests;
- keep LF/HF pause semantics, but study whether edge-flip directives need a different context boundary so every lower LF does not force repeated manual context expansion.
