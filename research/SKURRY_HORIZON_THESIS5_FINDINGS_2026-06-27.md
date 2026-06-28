# Skurry Horizon Thesis 5 Findings - 2026-06-27

## Scope

This is the first runnable Thesis 5 pass from `SKURRY_NOW_LENS_RESEARCH_NOTE_2026-06-27.md`.

Inputs:

- MarketRecorder `NQU6` only.
- Sessions: `2026-06-23`, `2026-06-24`, `2026-06-25`, `2026-06-26`.
- Anchors from the T3 lifecycle probe.
- Fixture windows from `research/band_lifecycle_fixture_specs_2026-06-23_2026-06-26.json`.
- No live EAR logs from the mixed MNQ/NQ period.
- `2026-06-22` excluded until the archived Google Drive copy is locally reliable.

Outputs:

- `LevelLedger/research/horizon_lifecycle_probe.py`
- `research/out/horizon_lifecycle_probe_20260623_20260626.csv`
- `research/out/horizon_lifecycle_probe_20260623_20260626.md`
- `research/out/horizon_lifecycle_probe_primary_dev_20260623_20260626.csv`
- `research/out/horizon_lifecycle_probe_primary_dev_20260623_20260626.md`

## Measurement Boundary

The original T5 target was `21-64` ticks beyond the band.

Current MarketRecorder snapshots are 30 levels per side. That makes broad snapshot Horizon incomplete:

- full `21-64` coverage at the `0.80` threshold: `21 / 1528` rows;
- band tests: `12 / 967` full-covered rows;
- band failures: `8 / 372` full-covered rows;
- consumed conversions: `0 / 189` full-covered rows.

So this broad pass cannot validate true extended Horizon.

The usable broad-pass object is narrower:

- front Horizon: `21-30` ticks beyond the band;
- front coverage at the `0.80` threshold: `779 / 1528` rows;
- band tests: `620 / 967` front-covered rows;
- band failures: `110 / 372` front-covered rows;
- consumed conversions: `49 / 189` front-covered rows.

Read:

- Horizon is most observable at the actual test/contact phase.
- It is much less observable at later failure/conversion anchors because the relevant far side is often outside the 30-level snapshot.
- Full `21-64` Horizon needs raw book-event reconstruction on selected windows or a deeper MarketRecorder snapshot setting.

## Label Semantics

The probe labels the front Horizon after each anchor:

- `far_wall_near`: observed wall of at least `7` contracts within the front Horizon.
- `open_horizon`: high air fraction and low mean displayed size in the observed front Horizon.
- `mixed_horizon`: observed, but neither open nor wall-dominated.
- `truncated`: less than `80%` of the requested range was covered by the snapshot.

These are book-context labels, not ownership labels.

## Finding 1 - Front Far Walls Are Not Ownership

Band-test rows:

| front Horizon | n | weak-hold family | terminal failure | fake failure | no structural follow-through |
| --- | ---: | ---: | ---: | ---: | ---: |
| far wall near | 156 | 47.4% | 26.9% | 8.3% | 13.5% |
| mixed horizon | 453 | 70.9% | 14.1% | 3.1% | 5.5% |
| open horizon | 11 | 72.7% | 27.3% | 0.0% | 0.0% |
| truncated | 347 | 66.9% | 19.0% | 5.2% | 6.1% |

Read:

- A front far wall does not prove the tested band will hold or fail.
- It does line up with more complicated test outcomes: terminal failure, fake failure, and no-follow-through are all higher in `far_wall_near` than in `mixed_horizon`.
- The simplest interpretation is contextual: visible opposition ahead makes the next auction more contested. It is not an ownership primitive.

## Finding 2 - Open Front Horizon Is Too Rare

Open front Horizon rows:

- all anchors: `15`;
- band tests: `11`;
- band failures: `4`;
- consumed conversions: `0`.

Move-away sketch:

- `open_horizon`: median aligned move-away `57` ticks, median adverse `51` ticks.
- `far_wall_near`: median aligned move-away `18` ticks, median adverse `42` ticks.
- `mixed_horizon`: median aligned move-away `6` ticks, median adverse `49` ticks.
- `truncated`: median aligned move-away `4` ticks, median adverse `52` ticks.

Read:

- The open-Horizon sample is too small for a conclusion.
- It does not contradict the intuition that open space can allow movement, but the adverse medians also show this is not a clean "open road means easy continuation" read.
- Keep move-away distance as secondary context only.

## Finding 3 - Consumed Conversions Remain Noisy

Consumed-conversion rows by front Horizon:

| front Horizon | n | direct conversion with follow-through | failed/churn conversion | no follow-through |
| --- | ---: | ---: | ---: | ---: |
| far wall near | 9 | 22.2% | 77.8% | 0.0% |
| mixed horizon | 40 | 5.0% | 92.5% | 2.5% |
| truncated | 140 | 16.4% | 72.9% | 10.7% |

Read:

- Front Horizon does not explain broad consumed-conversion quality in this pass.
- This should not be used against the T1 direct-conversion takeaway because the T5 population is every broad synthetic consumed row, not only explicit/direct conversions.

## Primary Bucket Check

Primary-development fixtures:

- anchor rows: `44`;
- clean Horizon rows: `43`;
- full `21-64` coverage at threshold: `0`;
- front coverage at threshold: `18 / 43`.

Band tests in the primary bucket:

- `far_wall_near`: `4` rows, all weak-hold family.
- `mixed_horizon`: `12` rows, mostly weak-hold family but includes `2` terminal failures and `1` no-follow-through.
- `open_horizon`: `1` row, terminal failure.
- `truncated`: `14` band-test rows.

Read:

- The primary bucket does not produce a stronger T5 conclusion.
- It mostly reinforces the measurement boundary: full Horizon is unavailable in broad snapshots, and front Horizon is a context label.

## Working Conclusion

Parked T5 takeaway:

- True `21-64` Horizon cannot be evaluated broadly from current 30-level snapshots.
- The usable broad-pass proxy is front Horizon, `21-30` ticks beyond the band.
- Front far walls are associated with more contested test outcomes, but they do not classify ownership.
- Open front Horizon is too rare to treat as a continuation qualifier.
- Consumed conversions need the narrower explicit-conversion population before Horizon can say anything useful.

This is not an EAR/LL policy recommendation. It is another thesis note to carry into the later synthesis.

## Next Thesis Step

Continue the thesis list rather than synthesizing yet.

The next item is Thesis 6, Side-Aware Pressure Field.
