# Skurry Terrain Thesis 3 Findings - 2026-06-27

## Scope

This is the first runnable Thesis 3 pass from `SKURRY_NOW_LENS_RESEARCH_NOTE_2026-06-27.md`.

Question:

- After an apparent ownership failure or consumed conversion, does the terrain just beyond the break explain whether the auction continues, stalls, or repairs?

Inputs:

- MarketRecorder `NQU6` only.
- Sessions: `2026-06-23`, `2026-06-24`, `2026-06-25`, `2026-06-26`.
- Window: `09:30-16:00` ET.
- Synthetic LL/EAR ownership grammar from current `candidate_timing_probe.py` / `ownership_bands_probe.py`.
- No live EAR logs from the mixed MNQ/NQ period.

Output files:

- `research/out/terrain_band_probe_nqu6_20260623_20260626.csv`
- `research/out/terrain_band_probe_nqu6_20260623_20260626.md`

Important limitation:

- This first pass uses 1 Hz snapshot terrain, not raw event-level book deltas.
- It measures displayed road/walls around the break, not true aggressor interest. "No aggressor interest beyond it" probably needs Driver/tape or contact-response metrics layered on top.

## Data Health

Rows emitted:

- `2026-06-23`: 202 terrain event rows, 15 snapshot gaps.
- `2026-06-24`: 196 terrain event rows, 5 snapshot gaps.
- `2026-06-25`: 133 terrain event rows, 45 snapshot gaps.
- `2026-06-26`: 185 terrain event rows, 27 snapshot gaps.

The snapshot gaps mean this is directional research only.

## Outcome Labels

For each `FAIL` or `CONSUMED` transition, the probe classifies the next nearby structural event within 10 minutes:

- `drive_destroyed_opposite`: break side later forced failure of opposite-side structure.
- `drive_owned_next`: break side formed the next nearby owned/consumed structure.
- `opposition_renewed`: opposite side formed/held nearby structure after the break.
- `drive_failed`: break side itself failed.
- `no_structural_followthrough`: no nearby structural continuation/repair found.

The first two are grouped mentally as "drive continues." The next two are grouped mentally as "repair or failed drive."

## Apparent Failures

All apparent failures:

| bucket | n | share |
| --- | ---: | ---: |
| drive continues | 183 | 38.2% |
| repair or failed drive | 155 | 32.4% |
| no structural follow-through | 141 | 29.4% |

Read:

- This matches the user's observation: an apparent fail is not enough.
- Roughly two thirds of apparent failures either repair/fail or produce no nearby structural follow-through.
- There is potential value here, but terrain alone is not yet decisive.

## Open Road

Most rows classified as `open_road`, which is itself an important NQ finding: the nearby book is often thin enough that "open road" is common, not special.

Apparent failures with open road:

| bucket | n | share |
| --- | ---: | ---: |
| drive continues | 174 | 37.7% |
| repair or failed drive | 149 | 32.3% |
| no structural follow-through | 139 | 30.1% |

Read:

- Open road does not imply continuation.
- A failed level with open road often still has no structural follow-through or sees the opposite side renew.
- Therefore Road/Terrain should not become "if vacuum then go."

## Opposing Book Renewing Beyond The Break

The more interesting cut is opposing book building just beyond the break.

Apparent failures where opposing book was building:

| bucket | n | share |
| --- | ---: | ---: |
| drive continues | 13 | 31.0% |
| repair or failed drive | 17 | 40.5% |
| no structural follow-through | 12 | 28.6% |

Consumed conversions where opposing book was building:

| bucket | n | share |
| --- | ---: | ---: |
| drive continues | 3 | 12.5% |
| repair or failed drive | 21 | 87.5% |

Read:

- This supports the intuition more than the open-road bucket does.
- When the book beyond the break is actively rebuilding against the break, the drive is more likely to repair/fail than continue.
- Sample size is not large enough to make this a runtime rule yet, but this is the T3 thread worth tightening.

## Same-Side Support Behind The Break

Same-side support building behind the break did not separate outcomes well in this first pass.

Read:

- Snapshot same-side support is probably too blunt.
- If "aggressor interest beyond it" matters, the better measurement is likely Driver/tape or event-level pressure, not 1 Hz same-side displayed depth.

## Consumed Conversion Caveat

The broad `CONSUMED` population in this Terrain probe is not the same as the cleaner explicit direct-conversion population from the Lean probe.

In this broad population, consumed conversions were often followed by `drive_failed`. That does not invalidate the Lean direct-conversion finding; it says the current terrain population includes a lot of local/churn consumed rows that should be filtered before drawing direct-conversion conclusions.

## Working Conclusion

T3 is valuable, but not as a standalone Road rule.

Current takeaway:

- Apparent failure needs an aftermath classifier.
- Open road is too common to be sufficient.
- Opposing book renewal just beyond the break is the promising warning condition.
- Same-side support from snapshots is not enough to prove continuation interest.
- The next useful version should focus on apparent failures and explicit direct conversions, not every consumed row.

## Next Pass

Refine T3 with raw event-level context around anchors instead of full-session snapshot buckets:

- Anchor on apparent `FAIL`, explicit conversion, and direct conversion rows only.
- Sample terrain at approach, break, +250 ms, +1 s, +2 s.
- Use raw L2 deltas to distinguish pre-existing wall from renewed opposing add.
- Add Driver/tape to measure whether the break side keeps attacking beyond the failed level.
- Preserve ownership outcomes: drive destroys opposite structure, drive owns next structure, opposition renews, drive fails, or no structural follow-through.

The likely EAR/LL hook is not "open road entry." It is a post-failure quality check:

- If a level fails but no break-side commitment appears beyond it, treat the failure as lower quality.
- If the opposing side rebuilds just beyond the break, treat the failure as repair-prone.
- If break-side Driver plus open road plus no opposing rebuild align, then the failure may be worth more consequence.
