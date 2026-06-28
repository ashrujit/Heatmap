# Band Lifecycle Episode Taxonomy - 2026-06-27

## Purpose

This note captures the next research framing after the Skurry Lean/Terrain passes:

- The goal is not necessarily better band discovery.
- The likely value is better interpretation of what happens when bands are approached, tested, held, failed, consumed, or renewed.
- The unit of analysis should move from an isolated band row to a local auction episode.

The initial user-memory fixture seeds live in `research/BAND_LIFECYCLE_FIXTURE_SEEDS_2026-06-22_2026-06-26.md`. Treat those as hypotheses until MarketRecorder replay verifies them.

## Episode Split

### Directional initiative episodes

These are sequences where one side continuously proves ownership.

Possible signs:

- same-side bands form in sequence;
- opposite-side bands are tested, consumed, or destroyed;
- failures produce same-side renewal nearby rather than two-way chop;
- pull/reload behavior supports the initiative side across the approach range;
- the auction moves away from tests in a controlled but persistent way;
- follow-on structure forms in the direction of initiative.

These episodes are the right population for EAR/LL continuation, add, and hold logic.

### Balance / distribution episodes

These are sequences where bands on both sides get tested, failed, or consumed, but neither side gains durable consequence.

Possible signs:

- demand and supply bands alternate;
- both sides fail near the same area;
- price revisits failed areas repeatedly;
- VPOC/distribution builds;
- ownership transitions do not produce follow-on structure;
- apparent breaks return to the local range rather than migrate value.

These episodes should be analyzed separately. They may be useful for "do less" logic, not continuation logic.

## Micro-Auction Boundary

Udit's point is that pull/reload behavior should not be measured only at the exact price of interest.

The more relevant object is the local micro-auction:

- the range price is rotating through before it tests the band;
- the upper/lower extremes where visible commitment changes;
- how the book behaves at the approach edge, touch, pierce, and move-away;
- whether commitment appears at the extreme or only at a resting price after the fact.

Working boundary candidates:

- last local swing high/low before touch;
- nearest active LL/EAR opposing bands around the test;
- rolling local high/low since the prior ownership transition;
- local value/distribution window if VPOC has stabilized;
- price range covered by the approach leg from opposite edge to target band.

This should be treated as a research choice, not assumed.

## Approach Metrics

For each band test, sample the micro-auction during approach:

- speed toward the band;
- signed tape / delta toward the band;
- volume on approach;
- whether approach pressure is building, fading, or bursty;
- pull/reload at the approach-side extreme;
- opposing wall renewal just beyond the tested band;
- same-side support/reload behind the approach.

The point is not simply "fast is good" or "slow is bad." The question is whether the approach shows real initiative or only a thin auction drifting into the level.

## Move-Away Metrics

After touch/pierce/reversal, sample the move away:

- speed leaving the band;
- signed tape / delta leaving the band;
- volume leaving the band;
- whether book support follows the move;
- whether the move away is controlled versus emotional/exhaustive;
- whether the opposite extreme of the micro-auction is destroyed;
- whether value migrates or the auction falls back into the local range.

Udit's intuition worth testing:

- If the intent is to fail the band and reverse, the move away may be less intense and more controlled.
- If the move away is only an emotional burst without follow-on ownership, it may be less durable.

## Test/Failure Labels

Research labels should become more granular than `held` / `failed`:

- `clean_hold`: touch/pierce, controlled rejection, same-side ownership continues.
- `weak_hold`: price rejects but no follow-on structure appears.
- `terminal_failure`: band fails and opposite side owns/destroys nearby structure.
- `fake_failure`: band fails mechanically, but same side renews nearby before opposite ownership takes control.
- `failure_into_balance`: band fails, but both sides continue to churn without consequence.
- `direct_conversion`: opposite evidence is consumed and the resulting side owns the area.
- `tested_not_disproved`: test/pierce occurs, but micro-auction context does not prove terminal failure.

These are research labels, not runtime rules.

## Implication For T4/T5

T4 Brick/contact response should be measured over the micro-auction boundary:

- not only the exact level touched;
- include the approach range, edge behavior, pull/reload around the extreme, and post-touch move away.

T5 Horizon/Road should be contextual:

- not "open road means go";
- instead, ask whether the local auction has room for consequence after a valid test/failure;
- separate open road with initiative from open road with no sponsor follow-through.

## Next Probe Shape

Build an episode-level table around band tests/failures:

- episode id;
- session/time;
- candidate/band id;
- band side and source;
- micro-auction high/low boundary;
- approach duration, range, speed, delta, volume;
- touch/pierce details;
- pull/reload across approach boundary;
- move-away duration, speed, delta, volume;
- opposing structure destroyed or not;
- value migrated or balance built;
- final label: directional initiative, fake failure, terminal failure, balance/distribution.

This should sit above the existing band probes rather than replace them.
