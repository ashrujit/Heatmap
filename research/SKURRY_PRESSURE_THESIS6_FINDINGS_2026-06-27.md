# Skurry Pressure Thesis 6 Findings - 2026-06-27

## Scope

This is the first runnable Thesis 6 pass from `SKURRY_NOW_LENS_RESEARCH_NOTE_2026-06-27.md`.

Inputs:

- MarketRecorder `NQU6` only.
- Sessions: `2026-06-23`, `2026-06-24`, `2026-06-25`, `2026-06-26`.
- Anchors from the T3 lifecycle probe.
- Fixture windows from `research/band_lifecycle_fixture_specs_2026-06-23_2026-06-26.json`.
- No live EAR logs from the mixed MNQ/NQ period.
- `2026-06-22` excluded until the archived Google Drive copy is locally reliable.

Outputs:

- `LevelLedger/research/pressure_field_lifecycle_probe.py`
- `research/out/pressure_field_lifecycle_probe_20260623_20260626.csv`
- `research/out/pressure_field_lifecycle_probe_20260623_20260626.md`
- `research/out/pressure_field_lifecycle_probe_primary_dev_20260623_20260626.csv`
- `research/out/pressure_field_lifecycle_probe_primary_dev_20260623_20260626.md`

## Method

The broad pass uses LL-style side-aware z events from MarketRecorder snapshots:

- demand-positive: `BID_BUILD`, `ASK_PULL`, `BID_IN`, `ASK_OUT`;
- supply-positive: `ASK_BUILD`, `BID_PULL`, `BID_OUT`, `ASK_IN`;
- lookback: `120s`;
- half-life: `45s`;
- spatial kernel: `12` ticks;
- local density threshold: `2.5`;
- support threshold: `2` events.

The initial raw snapshot-delta version was not useful: 1 Hz book deltas around a band were too symmetric and mostly collapsed into `mixed_pressure`. The default script now uses LL-style z events. This is still not raw quote-event replay.

## Coverage

Full fixture pass:

- anchor rows: `1530`;
- band tests: `968`;
- band failures: `372`;
- consumed conversions: `190`.

Primary-development bucket:

- anchor rows: `44`;
- band tests: `31`;
- band failures: `6`;
- consumed conversions: `7`.

## Finding 1 - Pressure Does Not Cleanly Classify Band Tests

Band-test rows:

| pressure label | n | clean hold | weak-hold family | terminal failure | fake failure | no structural follow-through |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| aligned pressure | 237 | 5.5% | 62.9% | 21.5% | 3.4% | 5.9% |
| mixed pressure | 177 | 5.1% | 66.1% | 17.5% | 6.2% | 4.5% |
| opposed pressure | 202 | 2.0% | 69.8% | 14.9% | 4.5% | 8.9% |
| sparse pressure | 348 | 3.2% | 64.9% | 18.1% | 4.9% | 7.8% |

Read:

- Owner-aligned pressure is not a hold proof.
- Opposed pressure is not a failure proof.
- The labels mostly redistribute weak/terminal outcomes inside the same broad ranges.
- `opposed_pressure` has slightly more no-structural-follow-through, but the effect is too small to treat as a classifier.

## Finding 2 - Failure Rows Are Also Not Separated

Failure rows:

- `aligned_pressure`: terminal `58.9%`, no structural follow-through `23.4%`, fake failure `15.9%`.
- `mixed_pressure`: terminal `63.6%`, no structural follow-through `21.6%`, fake failure `12.5%`.
- `opposed_pressure`: terminal `60.0%`, no structural follow-through `26.7%`, fake failure `13.3%`.
- `sparse_pressure`: terminal `51.0%`, no structural follow-through `33.3%`, fake failure `12.7%`.

Read:

- Pressure purity at the later failure timestamp does not clarify true versus fake failure.
- This matches the T4 measurement-placement issue: by the time the failure row prints, the meaningful test/contact sequence may already be behind us.

## Finding 3 - Broad Consumed Conversions Stay Noisy

Consumed-conversion rows:

| pressure label | n | direct conversion with follow-through | failed/churn conversion | no follow-through |
| --- | ---: | ---: | ---: | ---: |
| mixed pressure | 31 | 12.9% | 77.4% | 9.7% |
| opposed pressure | 157 | 14.6% | 77.1% | 8.3% |

Read:

- Most broad consumed rows are classified as opposed pressure to the resulting owner.
- That does not separate direct conversions from failed/churn conversions.
- This does not invalidate the T1 direct-conversion takeaway because this population is broad synthetic `CONSUMED`, not isolated explicit conversion.

## Primary Bucket Check

Primary-development fixtures were small but consistent with the full read:

- band tests:
  - `aligned_pressure`: `3` rows, all weak-hold family;
  - `mixed_pressure`: `8` rows, includes weak holds, fake failures, and one terminal failure;
  - `opposed_pressure`: `9` rows, mostly weak holds plus one no-follow-through;
  - `sparse_pressure`: `11` rows, includes weak holds and terminal failures.
- band failures:
  - aligned failure rows were terminal in `2 / 2`;
  - opposed failure rows were fake/no-follow-through in `2 / 2`;
  - sample is too small to generalize.

Read:

- The primary bucket gives some interesting rows for manual review.
- It does not support a broad pressure-field rule.

## Working Conclusion

Parked T6 takeaway:

- Side-aware pressure is a coherent context metric, but this broad snapshot-derived pass does not improve lifecycle classification.
- Pressure purity should not be used to reclassify tests, failures, or broad consumed conversions by itself.
- The useful future version, if any, likely needs narrower micro-auction boundaries and/or raw quote-event replay around selected anchors.
- For now, pressure field is a candidate quality score, not a new ownership layer.

This is not an EAR/LL policy recommendation. It is another thesis note to carry into the later synthesis.

## Follow-Up Pass

Static pressure at the band is probably the wrong measurement placement. A better second pass would define the local micro-auction first, then measure:

- pressure on the approach into the zone;
- pressure during the contact/pierce sequence;
- pressure as the auction moves away from the zone;
- whether the move-away pressure is controlled/less intense when the intent is to fail versus aggressive when the same side truly defends.

That would align better with the current working semantics: tests and failures should be classified by auction consequence and renewed sponsorship, not by a single pressure snapshot.

## Next Thesis Step

Continue the thesis list rather than synthesizing yet.

The next item is Thesis 7, Refill After Sweep / Stoprun. It overlaps with T4 Brick, so the next pass should keep it specifically framed around post-sweep refill behavior rather than redoing generic contact response.
