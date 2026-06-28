# Skurry Lean Thesis 1 Findings - 2026-06-27

## Scope

This is the first runnable Thesis 1 pass from `SKURRY_NOW_LENS_RESEARCH_NOTE_2026-06-27.md`.

Inputs:

- MarketRecorder `NQU6` only.
- Sessions: `2026-06-23`, `2026-06-24`, `2026-06-25`, `2026-06-26`.
- Window: `09:30-16:00` ET.
- Synthetic LL/EAR ownership grammar from current `candidate_timing_probe.py` / `ownership_bands_probe.py`.
- No live EAR logs from the mixed MNQ/NQ period.

Output files:

- `research/out/lean_band_probe_nqu6_20260623_20260626.csv`
- `research/out/lean_band_probe_nqu6_20260623_20260626.md`

Important limitation:

- This first pass uses snapshot-derived best bid/ask Lean at roughly 1 Hz, not raw event-level Lean. It is good enough to test whether the idea is directionally promising against LL/EAR ownership outcomes. It is not the final word on Udit's 400 ms event-stream Lean.

## Data Health

Lean rows loaded cleanly from snapshots:

- `2026-06-23`: 23,727 Lean points.
- `2026-06-24`: 21,342 Lean points.
- `2026-06-25`: 23,101 Lean points.
- `2026-06-26`: 22,193 Lean points.

Ownership replay did report snapshot timing gaps:

- `2026-06-23`: 15 gaps.
- `2026-06-24`: 5 gaps.
- `2026-06-25`: 45 gaps.
- `2026-06-26`: 27 gaps.

The probe excludes gap-contaminated displacement rows where the current timing harness marks them, but these gaps still mean this should be treated as first-pass research, not a runtime decision.

## Question A - Are We Missing Bands Because Gates Are Too Strict?

Baseline candidates:

| Lean at formation | n | same-side | consumed |
| --- | ---: | ---: | ---: |
| aligned | 150 | 59.3% | 40.7% |
| neutral | 259 | 48.6% | 51.4% |
| opposed | 89 | 50.6% | 49.4% |

Relaxed near-miss candidates, using lower `|z|` / cluster gates:

| Lean at formation | n | same-side | consumed | unresolved |
| --- | ---: | ---: | ---: | ---: |
| aligned | 602 | 52.3% | 47.5% | 0.2% |
| neutral | 995 | 49.6% | 50.3% | 0.1% |
| opposed | 262 | 50.0% | 50.0% | 0.0% |

Read:

- Lean at formation has a mild same-side tilt for already-valid baseline candidates.
- Relaxed near-miss candidates are basically 50/50. Snapshot Lean does not identify a clean population of skipped bands we should have classified.
- Current conclusion: do not loosen `|z|`, cluster score, or persistence gates based on Lean at formation alone.

## Question B - Does Lean Help Consumed-Band Classification?

Explicit opposite-candidate conversions are the most interesting cut:

| Lean aligned to resulting side | n | confirmed | failed |
| --- | ---: | ---: | ---: |
| aligned | 13 | 53.8% | 46.2% |
| neutral | 40 | 27.5% | 72.5% |
| opposed | 18 | 22.2% | 77.8% |

Read:

- This is the strongest positive Thesis 1 clue.
- When a direct conversion was happening and snapshot Lean aligned with the resulting side, confirmation roughly doubled versus neutral/opposed.
- Sample size is small, so this should not become a rule yet.
- This deserves the next pass with event-level Lean sampled at approach, touch, pierce, and conversion time.

## Question C - Does Lean Help Normal Band Test Survival?

All band tests:

| Lean at test | n | held | failed |
| --- | ---: | ---: | ---: |
| aligned | 110 | 70.0% | 30.0% |
| neutral | 250 | 73.2% | 26.8% |
| opposed | 77 | 54.5% | 45.5% |

Normal bands only:

| Lean at test | held | failed |
| --- | ---: | ---: |
| aligned | 43 | 17 |
| neutral | 92 | 37 |
| opposed | 22 | 17 |

Consumed bands only:

| Lean at test | held | failed |
| --- | ---: | ---: |
| aligned | 34 | 16 |
| neutral | 91 | 30 |
| opposed | 20 | 18 |

Read:

- Lean opposed to the band side at test is a real warning in this first pass.
- Lean aligned to the band side is not materially better than neutral.
- Practical interpretation: Lean may be a test-quality veto when it is clearly against the claimed owner. It is not yet a positive survival proof.

## Question D - Does Lean Affect X Ticks / Y Seconds Qualification?

The qualification grid was run for `6`, `8`, and `10` confirm ticks and `0,1,2,3,4,5,10` seconds persistence.

Representative current 8-tick / 5-second cut:

| Direction | Lean | confirmed/reset | stability |
| --- | --- | ---: | ---: |
| favor | aligned | 68/86 | 79.1% |
| favor | neutral | 143/210 | 68.1% |
| favor | opposed | 48/68 | 70.6% |
| adverse | aligned | 52/73 | 71.2% |
| adverse | neutral | 131/205 | 63.9% |
| adverse | opposed | 55/72 | 76.4% |

Read:

- Neutral Lean is often weaker than non-neutral Lean, but the sign is not clean enough.
- Opposed Lean is not consistently bad in the displacement grid, especially on adverse/direct-conversion episodes.
- Therefore Lean should not adjust the `x ticks / y seconds` qualification thresholds yet.
- The safer hypothesis is narrower: Lean at touch/pierce may qualify the test itself, not the whole displacement clock.

## Working Conclusion

Snapshot Lean should not become an ownership primitive.

What survives this pass:

- For missed-band detection, Lean at formation is not enough.
- For consumed/direct-conversion classification, Lean aligned to the resulting side is promising.
- For normal and consumed band tests, Lean opposed to the claimed owner is a useful failure warning.
- For `x ticks / y seconds`, Lean may become a veto or quality bucket, but not a threshold replacement.

## Next Pass

The next script change should make raw event-level Lean practical by sampling only around candidate/transition anchor windows instead of replaying full-day quote-id state for every session.

Sampling points to add:

- candidate formation
- approach to band
- first touch
- pierce through band
- reversal away from band
- explicit conversion / opposing structure failure

Primary labels should remain ownership labels:

- same-side ownership
- consumed ownership
- test held
- test failed
- explicit conversion confirmed/failed
- opposing structure destroyed

Fixed-horizon price excursion should remain secondary context only.
