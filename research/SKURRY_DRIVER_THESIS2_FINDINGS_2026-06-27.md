# Skurry Driver Thesis 2 Findings - 2026-06-27

## Scope

This is the first runnable Thesis 2 pass from `SKURRY_NOW_LENS_RESEARCH_NOTE_2026-06-27.md`.

Inputs:

- MarketRecorder `NQU6` only.
- Sessions: `2026-06-23`, `2026-06-24`, `2026-06-25`, `2026-06-26`.
- T3 lifecycle anchors.
- Fixture windows from `research/band_lifecycle_fixture_specs_2026-06-23_2026-06-26.json`.
- No live EAR logs from the mixed MNQ/NQ period.
- `2026-06-22` excluded until the archived Google Drive copy is locally reliable.

Outputs:

- `LevelLedger/research/driver_lifecycle_probe.py`
- `research/out/driver_lifecycle_probe_20260623_20260626.csv`
- `research/out/driver_lifecycle_probe_20260623_20260626.md`
- `research/out/driver_lifecycle_probe_primary_dev_20260623_20260626.csv`
- `research/out/driver_lifecycle_probe_primary_dev_20260623_20260626.md`

## Method

The probe builds a signed aggressor-tape impulse:

- buy aggressor volume is positive;
- sell aggressor volume is negative;
- state decays with a `3s` half-life;
- absolute impulse is normalized against a rolling `1800s` session-local history;
- the current impulse is sampled at each lifecycle anchor;
- prior effort/exhaustion is measured from the previous `10s`.

Driver labels:

- `aligned_active`: current unusual impulse points in the expected auction direction;
- `weak_aligned`: current smaller impulse points in the expected auction direction;
- `aligned_exhausted`: aligned impulse was present in the prior `10s`, but has faded by the anchor;
- `opposed_active`: current unusual impulse points against the expected auction direction;
- `weak_opposed`: current smaller impulse points against the expected auction direction;
- `opposed_exhausted`: opposed impulse was present in the prior `10s`, but has faded by the anchor;
- `quiet`: no unusual current or recently exhausted impulse.

Expected direction is anchor-class aware:

- band test: the side that should carry price away if the tested owner survives;
- band failure: the break side;
- consumed conversion: the new/converted side.

That definition is useful, but it makes one thing clear: the meaning of Driver flips by phase. Opposed Driver into a tested band can be a good thing if the owner absorbs it. Aligned Driver through a failure can be confirmation of a real break.

## Coverage

Main pass:

- anchor rows: `1530`;
- band tests: `968`;
- band failures: `372`;
- consumed conversions: `190`;
- direct conversions with followthrough: `27`.

Primary-development bucket:

- anchor rows: `44`;
- band tests: `31`;
- band failures: `6`;
- consumed conversions: `7`;
- direct conversions with followthrough: `2`.

## Finding 1 - Pooled Driver Is Misleading

All anchors pooled:

| driver label | n | owner defended | failed/no-follow | contested/balance |
| --- | ---: | ---: | ---: | ---: |
| aligned active | 228 | 14.9% | 82.9% | 2.2% |
| weak aligned | 107 | 18.7% | 81.3% | 0.0% |
| aligned exhausted | 124 | 30.6% | 64.5% | 4.8% |
| quiet | 854 | 49.1% | 39.8% | 11.1% |
| opposed active | 104 | 68.3% | 9.6% | 22.1% |
| weak opposed | 62 | 82.3% | 1.6% | 16.1% |
| opposed exhausted | 51 | 56.9% | 23.5% | 19.6% |

Read:

- A naive "aligned Driver is good" rule is wrong.
- The pooled result is dominated by anchor-class semantics.
- Aligned Driver often appears on failure rows, where it confirms the break side rather than forecasting a good band.
- Opposed Driver often appears on test rows, where active aggression into the owner gets absorbed.

## Finding 2 - Band Failures: Aligned Driver Confirms Real Breaks

Band-failure rows:

| driver label | n | failed/no-follow | owner defended |
| --- | ---: | ---: | ---: |
| aligned active | 153 | 86.9% | 11.8% |
| weak aligned | 52 | 88.5% | 11.5% |
| aligned exhausted | 21 | 76.2% | 19.0% |
| quiet | 139 | 81.3% | 15.8% |

Read:

- Once the mechanical failure row exists, aligned Driver mostly confirms the break side.
- This is probably not an early sponsor-failure predictor by itself. It is closer to execution timing after failure has already printed.
- Fake-failure renewal still exists inside aligned Driver rows, so sponsor lifecycle nuance remains necessary.

Primary bucket example:

- `20260624_1055_1110_supply_transition` had an `aligned_active` band failure at `11:01:01` that became `fake_failure_same_side_renewal`.
- That is exactly the practical case we discussed: a strict if/else sponsor failure rule can be too hard when same-side sponsorship renews nearby.

## Finding 3 - Band Tests: Opposed Driver Often Means Absorbed Aggression

Band-test rows:

| driver label | n | owner defended | failed/no-follow | contested/balance |
| --- | ---: | ---: | ---: | ---: |
| opposed active | 98 | 72.4% | 4.1% | 23.5% |
| weak opposed | 61 | 83.6% | 0.0% | 16.4% |
| opposed exhausted | 46 | 60.9% | 17.4% | 21.7% |
| quiet | 617 | 61.9% | 23.3% | 14.7% |
| aligned active | 55 | 21.8% | 72.7% | 5.5% |
| weak aligned | 39 | 30.8% | 69.2% | 0.0% |
| aligned exhausted | 52 | 53.8% | 36.5% | 9.6% |

Read:

- At contact, opposed Driver is not automatically bad for the owner.
- It can mean the aggressor side arrived with effort and still failed to take ownership.
- This is a better "test quality" read than aligned Driver at the exact anchor.
- Aligned Driver on a band test frequently looks late: the test is no longer proving passive ownership; the auction is already moving in the break/move-away direction and many of those rows later fail.

This supports Udit's point from the chat: the approach and move-away micro-auction matter more than a single pressure reading at the resting price.

## Finding 4 - Consumed Conversions Are Not Strongly Explained By Driver

Consumed-conversion rows:

| driver label | n | direct conversion | failed/churn | conversion no-follow |
| --- | ---: | ---: | ---: | ---: |
| aligned active | 20 | 20.0% | 70.0% | 10.0% |
| aligned exhausted | 51 | 11.8% | 80.4% | 7.8% |
| quiet | 98 | 15.3% | 75.5% | 9.2% |
| weak aligned | 16 | 12.5% | 81.2% | 6.2% |
| opposed active | 4 | 0.0% | 100.0% | 0.0% |

Direct conversions with followthrough:

- `15` quiet;
- `6` aligned exhausted;
- `4` aligned active;
- `2` weak aligned;
- `0` opposed.

Read:

- Driver does not explain the T1 direct-conversion takeaway as cleanly as Lean did.
- Direct conversions do not require a large current Driver reading.
- Opposed Driver at conversion is not encouraging, but sample is tiny.
- Direct conversion still looks more like ownership relocation/no-revisit behavior than raw tape speed.

## Finding 5 - Primary Bucket Is Useful But Not Representative

Primary-development bucket:

- `aligned_active`: `4` rows, all owner-defended;
- `quiet`: `22` rows, `63.6%` owner-defended;
- `weak_aligned`: `3` rows, all terminal failure;
- direct conversions: one `aligned_exhausted`, one `quiet`.

Read:

- The main examples contain the fake-failure/renewal behavior we care about.
- They should not be pooled blindly with every full-day anchor.
- The full set says Driver must be interpreted by anchor class and phase; the primary bucket says there are practical cases where a failure row plus renewed Driver could keep us from giving up too early.

## Working Conclusion

Parked T2 takeaway:

- Driver is useful, but not as "aligned good / opposed bad."
- On failures, aligned Driver is mostly confirmation that the break side has active effort.
- On tests, opposed Driver can be evidence that the owner absorbed a real test.
- Quiet Driver is not automatically bad; many quiet tests still hold.
- Consumed direct conversion remains a T1/ownership-relocation story more than a Driver story.
- For EAR/LL, Driver belongs in a phase-aware micro-auction model: approach pressure, contact pressure, and move-away pressure should be separated.

This is not an EAR/LL policy recommendation. It is the last single-thesis note before synthesis.

## Next Research Step

The thesis list from the Now Lens note is now exhausted for the first pass:

- T1 Lean;
- T2 Driver;
- T3 Road/Terrain;
- T4 Brick;
- T5 Horizon;
- T6 Pressure Field;
- T7 Refill;
- T8 Book Thinning;
- T9 Hidden Liquidity.

The next pass should synthesize the notes into a smaller LL/EAR research map, likely centered on phase-aware lifecycle classification rather than new standalone bands.
