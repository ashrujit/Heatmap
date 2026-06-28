# Skurry Terrain Thesis 3 Episode Findings - 2026-06-27

## Scope

This is the second Thesis 3 pass. The first pass looked across full sessions. This pass uses the curated fixture chunks and asks a narrower question:

- What does a good test look like?
- What is a true failure?
- What is a fake failure / same-side renewal?
- Does Road/Terrain help distinguish those lifecycle labels?

Inputs:

- MarketRecorder `NQU6` only.
- Sessions: `2026-06-23` through `2026-06-26`.
- Fixture windows from `research/band_lifecycle_fixture_specs_2026-06-23_2026-06-26.json`.
- Synthetic LL/EAR ownership grammar.
- No live EAR logs from the mixed MNQ/NQ period.
- `2026-06-22` excluded until the archived Google Drive copy is locally reliable.

Outputs:

- `LevelLedger/research/episode_terrain_lifecycle_probe.py`
- `research/out/episode_terrain_lifecycle_probe_20260623_20260626.csv`
- `research/out/episode_terrain_lifecycle_probe_20260623_20260626.md`

## Label Semantics

This pass deliberately uses stricter labels than the first T3 run.

- `clean_hold`: a test/pierce holds and the band side later destroys opposing structure nearby.
- `weak_hold`: the band locally holds, but there is no opposing-structure destruction.
- `weak_hold_opposition_renewed`: the band holds locally, but the opposing side renews next.
- `terminal_failure`: the band fails and the break side gets structural consequence.
- `fake_failure_same_side_renewal`: the band mechanically fails, but the failed side renews nearby/beyond before the break side proves control.
- `no_structural_followthrough`: the failure/test does not produce nearby ownership consequence.
- `direct_conversion_with_followthrough`: consumed conversion followed by resulting-side consequence.

The target is ownership consequence, not price after N seconds.

## Main Counts

Anchor rows:

- tests: `968`
- failures: `372`
- consumed conversions: `190`

Test outcomes:

- `weak_hold`: `454` (`46.9%`)
- `weak_hold_opposition_renewed`: `135` (`13.9%`)
- `weak_hold_same_side_continued`: `47` (`4.9%`)
- `terminal_failure`: `175` (`18.1%`)
- `fake_failure_same_side_renewal`: `45` (`4.6%`)
- `clean_hold`: `38` (`3.9%`)

Read:

- A local hold is common.
- A strict good test, where the test ultimately destroys opposing structure, is rare.
- This supports tightening the mental grammar: "tested and held" is not the same as "survived with consequence."

Failure outcomes:

- `terminal_failure`: `216` (`58.1%`)
- `no_structural_followthrough`: `98` (`26.3%`)
- `fake_failure_same_side_renewal`: `51` (`13.7%`)
- `failure_into_balance`: `7` (`1.9%`)

Read:

- Most mechanical failures are real enough to get consequence, but a material minority are either fake or inconclusive.
- This directly supports the working point: not all failures are alike.

## Episode Context Matters More Than Road Alone

Failure labels by fixture bucket:

- Directional-with-churn stress windows:
  - terminal failures: `63.3%`
  - fake failures: `18.1%`
  - no structural follow-through: `16.7%`
- Balance counters:
  - terminal failures: `51.7%`
  - fake failures: `6.8%`
  - no structural follow-through: `39.8%`
- No-build caution windows:
  - terminal failures: `41.2%`
  - fake failures: `0.0%`
  - no structural follow-through: `58.8%`

Read:

- The same mechanical `FAIL` means different things by episode type.
- Directional/churn windows produce more fake same-side renewal than balance counters.
- Balance/no-build windows produce much more "nothing followed through."

Practical implication:

- EAR/LL should not eventually reason about failure as a hard binary only.
- The first improvement path is a post-failure lifecycle state, not a new entry signal.

## Terrain Findings

Open road remains too common to be a rule.

- Open-road failures: `358 / 372` (`96.2%`)
- Inside open-road failures:
  - terminal failure: `207`
  - no structural follow-through: `96`
  - fake same-side renewal: `48`
  - failure into balance: `7`

Read:

- Open road is the normal state around NQ failures in this snapshot-derived terrain view.
- Open road does not tell us whether failure will matter.

Opposing book building beyond the break is still interesting, but small-sample:

- Failure rows with opposing book `building`: `18`
- terminal failure: `8` (`44.4%`)
- non-terminal / fake / no-follow-through: `10` (`55.6%`)

Read:

- This leans in the intuitive direction: rebuilding against the break is a warning.
- It is not strong enough as a standalone runtime condition.

## Approach And Move-Away

Approach tape did not separate labels well.

Median approach aligned tape share:

- clean hold: `0.47`
- weak hold: `0.51`
- terminal failure: `0.52`
- fake failure: `0.52`

Move-away speed was more promising.

Median move-away aligned speed:

- clean hold: `0.65` ticks/sec
- terminal failure: `0.26` ticks/sec
- weak hold: `-0.03` ticks/sec
- fake failure: `-0.06` ticks/sec

Read:

- Fixed-window approach delta/volume is probably too blunt.
- Move-away quality better matches Udit's intuition: weak/fake outcomes do not keep moving away with consequence.
- This should be retested with true micro-auction boundaries instead of a fixed `120s` window before becoming a heuristic.

## Consumed Conversion Caveat

Broad consumed rows are noisy in this lifecycle pass:

- direct conversion with follow-through: `27 / 190` (`14.2%`)
- failed/churn conversion: `147 / 190` (`77.4%`)

This does not invalidate the Thesis 1 direct-conversion takeaway.

Reason:

- T1 isolated explicit direct conversion more carefully.
- This T3 pass includes every synthetic `CONSUMED` row and then requires strict nearby ownership follow-through.

Keep the earlier takeaway:

- Explicit/direct conversion remains the best T1 candidate.
- Broad consumed rows should not be treated as equivalent.

## Review Fixture: 2026-06-26 13:05-13:10

The narrow synthetic read does not confirm the memory label "supply tested and survived."

Rows inside the fixture:

- `13:07:35` demand test at `639` -> `clean_hold`, because supply `656.50` fails at `13:08:35`.
- `13:08:06` supply test at `656.50` -> `no_structural_followthrough`.
- `13:08:35` supply failure at `656.50` -> `no_structural_followthrough`.

Read:

- Under current synthetic grammar, this is not a clean supply-survived test.
- It may be the wrong band, too narrow a window, or a case where the visual chart memory was tracking a larger supply area.
- Keep this as a review/holdout, not a development fixture.

## Working Conclusion

T3 should not become an "open road" rule.

The useful T3 finding is lifecycle nuance:

- good tests require consequence, not just local hold;
- true failures and fake failures separate by what ownership appears next;
- same-side renewal after failure is a real enough pattern to keep studying;
- episode context separates failure meaning better than snapshot road alone;
- move-away quality is more promising than approach tape, but needs micro-auction boundaries.

## Next T3 Step

Focus the next pass only on failure rows:

- terminal failure;
- fake failure / same-side renewal;
- no structural follow-through.

Use directional-churn windows first, especially where fake failures appear. Then manually review a smaller set of rows with exact chart context before proposing any EAR/LL heuristic.

Potential future runtime concept:

- not a rule change yet;
- a `renewal-watch` state after sponsor failure, where same-side renewal nearby/beyond the failed area downgrades the certainty of "true sponsor failure."

