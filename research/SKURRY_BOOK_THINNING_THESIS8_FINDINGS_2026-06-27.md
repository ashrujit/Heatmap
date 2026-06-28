# Skurry Book Thinning Thesis 8 Findings - 2026-06-27

## Scope

This is the first runnable Thesis 8 pass from `SKURRY_NOW_LENS_RESEARCH_NOTE_2026-06-27.md`.

Inputs:

- MarketRecorder `NQU6` only.
- Sessions: `2026-06-23`, `2026-06-24`, `2026-06-25`, `2026-06-26`.
- T3 lifecycle anchors.
- Existing Skurry-style `LevelLedger/research/book_thinning_probe.py` detector.
- Fixture windows from `research/band_lifecycle_fixture_specs_2026-06-23_2026-06-26.json`.
- No live EAR logs from the mixed MNQ/NQ period.
- `2026-06-22` excluded until the archived Google Drive copy is locally reliable.

Outputs:

- `LevelLedger/research/book_thinning_lifecycle_probe.py`
- `research/out/book_thinning_lifecycle_probe_20260623_20260626.csv`
- `research/out/book_thinning_lifecycle_probe_20260623_20260626.md`
- `research/out/book_thinning_lifecycle_probe_primary_dev_20260623_20260626.csv`
- `research/out/book_thinning_lifecycle_probe_primary_dev_20260623_20260626.md`
- `research/out/book_thinning_lifecycle_probe_phase_gated_20260623_20260626.csv`
- `research/out/book_thinning_lifecycle_probe_phase_gated_20260623_20260626.md`

## Method

The probe reuses the day-level Book Thinning detector:

- aggregate top `20` levels on one side;
- compare current depth with the retained 5-second window baseline;
- require at least `25%` aggregate depth drop;
- require same-side aggressive tape to be less than `20%` of disappeared size;
- attach nearby thinning events to lifecycle anchors inside a `60s` before / `30s` after anchor window.

For each anchor, expected thinning direction is the expected travel direction:

- expected up/demand travel => ask-side thinning ahead;
- expected down/supply travel => bid-side thinning ahead.

Two broad passes were run:

- no detector phase gate, to see open/IB/close behavior;
- detector phase gate enabled, to match the source caution that open/IB/close thinning is different.

## Coverage

No-gate detector pass:

- anchor rows: `1530`;
- thinning events: `151` across four sessions;
- events by session: `49`, `23`, `34`, `45`;
- close/IB events were present.

Phase-gated detector pass:

- anchor rows: `1530`;
- thinning events: `119` across four sessions;
- events by session: `42`, `18`, `22`, `37`;
- open/IB/close thinning was suppressed.

Most anchors had no nearby thinning:

- no-gate: `1275 / 1530` no-near-thinning rows;
- phase-gated: `1327 / 1530` no-near-thinning rows.

## Finding 1 - Aligned Thinning Skews Toward Failure, But Weakly

Cleaner phase-gated pass:

| thinning label | n | failed/no-follow | owner defended | contested/balance |
| --- | ---: | ---: | ---: | ---: |
| aligned before | 55 | 58.2% | 36.4% | 5.5% |
| aligned after | 22 | 50.0% | 45.5% | 4.5% |
| no near thinning | 1327 | 47.4% | 43.3% | 9.3% |
| opposed only | 111 | 41.4% | 43.2% | 15.3% |

Read:

- Aligned thinning before the anchor has a mild failure/no-followthrough skew.
- The separation is not large enough to classify a test or failure.
- Aligned thinning after the anchor is even less decisive; it may simply describe the auction already moving through thinner road.

## Finding 2 - Failure Rows Show The Strongest Association

Phase-gated band-failure rows:

- `aligned_before`: `16` rows; `75.0%` terminal failure.
- `no_near_thinning`: `328` rows; `56.7%` terminal failure.
- `opposed_only`: `22` rows; `72.7%` terminal failure.

Read:

- When a mechanical failure row has nearby thinning, terminal failure is more common.
- This is still mostly a road/vacuum context read, not ownership.
- As with Brick, failure rows can be late. By the time a failure row prints, the book may already have stepped away.

## Finding 3 - Band Tests Stay Mixed

Phase-gated band-test rows:

- `aligned_before`: `31` rows; `25.8%` terminal failure, `41.9%` weak hold, `12.9%` clean hold.
- `aligned_after`: `15` rows; `40.0%` terminal failure, `20.0%` fake failure same-side renewal, `20.0%` weak hold.
- `no_near_thinning`: `834` rows; `17.7%` terminal failure, `47.1%` weak hold, `3.5%` clean hold.

Read:

- Thinning does not identify a good test or bad test cleanly.
- A test can hold even when liquidity thinned, and a test can fail without any nearby thinning event.
- The useful interpretation is likely: "road may be easier if the owner already fails," not "the owner has failed."

## Finding 4 - Direct Conversion Is Not Explained By Book Thinning

Phase-gated consumed-conversion rows:

- `aligned_before_after`: `1` row, direct conversion.
- `no_near_thinning`: `165` rows; `26` direct conversions and `125` failed/churn conversions.
- `aligned_before`: `8` rows; `0` direct conversions.
- `aligned_after`: `2` rows; `0` direct conversions.

Read:

- T8 does not explain the T1 direct-conversion takeaway.
- Direct conversion still looks more like ownership relocation/no-revisit behavior than top-book thinning.

## Finding 5 - Phase Gate Matters Operationally

No-gate replay found extra close/IB events:

- no-gate events: `151`;
- phase-gated events: `119`;
- the removed rows were mainly close and IB.

Open anchors still mostly had no nearby thinning even without the gate, but the close rows created additional aligned/mixed labels. That is consistent with the source warning: thinning should be phase-stratified and should not become a generic signal.

## Primary Bucket Check

Primary-development bucket:

- `44` anchor rows;
- `37` no-near-thinning rows;
- `2` aligned-after rows, both fake-failure same-side renewal in the `20260624_1055_1110_supply_transition` fixture;
- `5` opposed-only rows, mostly weak-hold opposition renewed in the `20260625_1215_1230_supply_burst` fixture.

Read:

- Primary examples are useful for manual chart review.
- They are too sparse to support a rule.
- The fake-failure cases may be worth revisiting when we do a micro-auction pass, but thinning alone is not the reason.

## Working Conclusion

Parked T8 takeaway:

- Book thinning is valid as road/vacuum context.
- It should not be treated as ownership, sponsor failure, or a standalone continuation signal.
- Aligned thinning before/around failures modestly supports the idea that price can travel because liquidity left, but it does not tell us who owns the move.
- The detector should remain phase-aware; open/IB/close behavior should not be pooled with lunch/afternoon.
- For EAR/LL, this belongs closer to a caution/no-chase/road-quality annotation than to band classification.

This is not an EAR/LL policy recommendation. It is another thesis note to carry into the later synthesis.

## Next Thesis Step

Continue the thesis list rather than synthesizing yet.

Remaining source-list items:

- Thesis 9: Hidden Liquidity.
- Thesis 2: Driver, if we circle back to the item we skipped when choosing T3 earlier.
