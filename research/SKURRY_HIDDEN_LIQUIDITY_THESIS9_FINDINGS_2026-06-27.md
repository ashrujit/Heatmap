# Skurry Hidden Liquidity Thesis 9 Findings - 2026-06-27

## Scope

This is the first runnable Thesis 9 pass from `SKURRY_NOW_LENS_RESEARCH_NOTE_2026-06-27.md`.

Inputs:

- MarketRecorder `NQU6` only.
- Sessions: `2026-06-23`, `2026-06-24`, `2026-06-25`, `2026-06-26`.
- T3 lifecycle anchors, joined through the T4 Brick contact response rows.
- Fixture windows from `research/band_lifecycle_fixture_specs_2026-06-23_2026-06-26.json`.
- No live EAR logs from the mixed MNQ/NQ period.
- `2026-06-22` excluded until the archived Google Drive copy is locally reliable.

Outputs:

- `LevelLedger/research/hidden_liquidity_lifecycle_probe.py`
- `research/out/hidden_liquidity_lifecycle_probe_20260623_20260626.csv`
- `research/out/hidden_liquidity_lifecycle_probe_20260623_20260626.md`
- `research/out/hidden_liquidity_lifecycle_probe_primary_dev_20260623_20260626.csv`
- `research/out/hidden_liquidity_lifecycle_probe_primary_dev_20260623_20260626.md`

## Method

The probe looks for a broad hidden-liquidity proxy near lifecycle anchors. This is not exchange-native hidden-size attribution.

For each anchor it checks:

- same-price traded volume inside the band, expanded by `1` tick;
- aggressor majority in the `1s before / 5s after` contact window;
- maximum visible passive display at that price in nearby 30-level snapshots;
- trade/display ratio.

The qualified proxy requires:

- at least `20` contracts traded;
- at least `65%` one-sided aggressor majority;
- max passive displayed size at or below `6`;
- trade/display ratio at least `4.0`.

Aggressor majority defines the passive hidden side:

- buy-majority trade into low displayed ask => hidden/passive supply proxy;
- sell-majority trade into low displayed bid => hidden/passive demand proxy.

That passive hidden side is then compared with the anchor owner side:

- `aligned_hidden`: hidden/passive side matches the band owner;
- `opposed_hidden`: hidden/passive side opposes the band owner;
- `no_hidden`: no qualified proxy.

## Coverage

Main pass:

- analyzed rows: `1528`;
- hidden-proxy rows: `26`;
- hidden-proxy rows with passive display observed in snapshots: `22`;
- band tests: `967`;
- band failures: `372`;
- consumed conversions: `189`.

Primary-development bucket:

- `43` rows;
- `0` hidden-proxy rows.

Read:

- This proxy is sparse under conservative thresholds.
- It is not present in the two primary examples we have been using most heavily.

## Finding 1 - Aligned Hidden Is Mildly Defensive, Not Decisive

Outcome by hidden alignment:

| hidden alignment | n | owner defended | failed/no-follow | contested/balance |
| --- | ---: | ---: | ---: | ---: |
| aligned hidden | 16 | 50.0% | 31.2% | 18.8% |
| no hidden | 1502 | 43.3% | 47.1% | 9.6% |
| opposed hidden | 10 | 20.0% | 60.0% | 20.0% |

Read:

- Aligned hidden proxy had better defense odds than the no-hidden baseline, but only across `16` rows.
- Opposed hidden proxy was more often bad for the current owner, but only across `10` rows.
- This is a contextual clue, not a classifier.

## Finding 2 - Band Tests Remain Mixed

Band-test rows only:

| hidden alignment | n | weak hold | terminal failure | fake failure renewal | weak hold opposition renewed |
| --- | ---: | ---: | ---: | ---: | ---: |
| aligned hidden | 15 | 33.3% | 20.0% | 13.3% | 20.0% |
| no hidden | 942 | 47.3% | 17.8% | 4.6% | 13.8% |
| opposed hidden | 10 | 20.0% | 40.0% | 0.0% | 20.0% |

Read:

- Aligned hidden does not reliably identify "good tests."
- Opposed hidden has a more concerning failure skew, but the sample is too small for a rule.
- The useful manual interpretation may be: if the current owner is being opposed by a low-display/high-trade passive side, do not over-trust the owner label without subsequent renewal.

## Finding 3 - It Does Not Explain Direct Conversion

Consumed-conversion rows:

- `189` consumed conversions;
- `0` qualified hidden-proxy rows;
- direct conversion with followthrough remains entirely in `no_hidden`.

Read:

- This does not explain the T1 direct-conversion takeaway.
- Direct conversion still looks more like ownership relocation/no-revisit behavior than hidden passive defense.

## Finding 4 - Brick Overlap Is Not Clean

Aligned hidden rows:

- `31.2%` `gave_depleted`;
- `18.8%` `held_refilled`;
- `18.8%` `no_initial_brick`;
- `18.8%` `no_initial_brick_refilled`;
- `12.5%` `held_no_refill`.

Opposed hidden rows:

- `50.0%` `held_refilled`;
- `20.0%` `gave_depleted`;
- remaining rows split across ambiguous/no-initial/held-no-refill.

Read:

- Hidden proxy and Brick contact behavior are not redundant, but they also do not combine into a clean rule.
- A high trade/display ratio can mean genuine passive absorption, but it can also mean thin support getting attacked through snapshots that missed refresh.

## Working Conclusion

Parked T9 takeaway:

- Hidden-liquidity proxy is a sparse contextual clue.
- Aligned hidden can modestly support an owner-holding interpretation, but does not confirm a good test.
- Opposed hidden can be a caution flag that the visible owner may not actually control the contact.
- It should not be used to reclassify consumed conversions, and it does not explain direct conversion.
- For EAR/LL, this belongs as a lower-confidence annotation around contact quality, best revisited inside the later micro-auction approach/contact/move-away pass.

This is not an EAR/LL policy recommendation. It is another thesis note to carry into the later synthesis.

## Next Thesis Step

Finish the remaining skipped source-list item:

- Thesis 2: Driver.
