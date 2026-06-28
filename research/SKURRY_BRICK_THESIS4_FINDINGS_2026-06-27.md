# Skurry Brick Thesis 4 Findings - 2026-06-27

## Scope

This is the first runnable Thesis 4 pass from `SKURRY_NOW_LENS_RESEARCH_NOTE_2026-06-27.md`.

Inputs:

- MarketRecorder `NQU6` only.
- Sessions: `2026-06-23`, `2026-06-24`, `2026-06-25`, `2026-06-26`.
- Fixture windows from `research/band_lifecycle_fixture_specs_2026-06-23_2026-06-26.json`.
- Anchors from the T3 lifecycle probe, not live EAR logs.
- No live EAR logs from the mixed MNQ/NQ period.
- `2026-06-22` excluded until the archived Google Drive copy is locally reliable.

Outputs:

- `LevelLedger/research/brick_contact_response_probe.py`
- `research/out/brick_contact_response_probe_20260623_20260626.csv`
- `research/out/brick_contact_response_probe_20260623_20260626.md`
- `research/out/brick_contact_response_probe_primary_dev_20260623_20260626.csv`
- `research/out/brick_contact_response_probe_primary_dev_20260623_20260626.md`

Important limitation:

- This first broad pass uses MarketRecorder snapshots plus tape, not raw quote-event ordering.
- Same-band add/remove/pull estimates are net depth changes between samples.
- `250ms` refill is sample-cadence limited in this mode. The `2s` window is the main descriptive cut.
- Raw `--book-events` replay exists in the script but should be used on selected anchors/windows, not treated as completed broad evidence yet.

## Label Semantics

The probe attaches descriptive Brick labels to each lifecycle anchor:

- `held_refilled`: owner-side displayed depth survived and refilled inside `2s`.
- `held_no_refill`: owner-side displayed depth survived, but refill was weak.
- `gave_depleted`: owner-side displayed depth was materially depleted with little refill.
- `gave_pulled`: displayed size disappeared more than same-band attack tape explains.
- `no_initial_brick`: no meaningful displayed size was present at the anchor.
- `no_initial_brick_refilled`: no initial displayed brick, but owner-side depth appeared after the anchor.
- `ambiguous`: mixed or weak evidence.

These are contact-response labels, not trade outcome labels.

## Coverage

Full fixture pass:

- anchor rows: `1530`
- clean book rows: `1528`
- band tests: `967` clean rows
- band failures: `372` clean rows
- consumed conversions: `189` clean rows

Primary-development bucket:

- anchor rows: `44`
- clean book rows: `43`

## Finding 1 - Failure Timestamps Are Too Late For Brick

Band failure anchors were almost always `no_initial_brick`:

| failure label | n | no initial brick |
| --- | ---: | ---: |
| terminal failure | 216 | 216 |
| no structural follow-through | 98 | 97 |
| fake failure same-side renewal | 51 | 51 |
| failure into balance | 7 | 7 |

Read:

- The mechanical failure timestamp usually arrives after displayed depth at the failed area is already gone.
- Brick contact response should be judged at the preceding test/touch/pierce anchor, not at the later failure row.
- This is a measurement-placement finding, not a rule change.

## Finding 2 - Band Tests Separate Some Failure Modes

For band-test rows only, grouping `held_refilled`, `held_no_refill`, and `no_initial_brick_refilled` as held-like, and grouping `gave_depleted` plus `gave_pulled` as gave-like:

| lifecycle label | n | held-like | gave-like | no initial |
| --- | ---: | ---: | ---: | ---: |
| clean hold | 38 | 19 (50.0%) | 11 (28.9%) | 3 |
| fake failure same-side renewal | 45 | 24 (53.3%) | 11 (24.4%) | 4 |
| no structural follow-through | 67 | 18 (26.9%) | 40 (59.7%) | 6 |
| terminal failure | 175 | 77 (44.0%) | 68 (38.9%) | 25 |
| weak hold | 453 | 254 (56.1%) | 109 (24.1%) | 35 |
| weak hold opposition renewed | 135 | 81 (60.0%) | 29 (21.5%) | 7 |
| weak hold same-side continued | 47 | 32 (68.1%) | 10 (21.3%) | 3 |

Read:

- The clearest split is `no_structural_followthrough`: `59.7%` gave-like, much higher than weak/fake/continued hold buckets.
- Same-side continuation is the strongest held-like bucket at `68.1%`.
- Terminal failures are mixed. A terminal structural failure can still have earlier tests that temporarily held or refilled before the eventual failure.
- Clean holds are also mixed. A strict structural hold can come after local depletion, delayed refill, or a response outside the narrow contacted ticks.

This supports Brick as a test-contact classifier, not as a standalone hold/fail label.

## Finding 3 - Refill And Depletion Metrics Behave Sensibly

Metric sketch at the `2s` label:

- `held_refilled`: `n=319`, median attack `2`, median pulled estimate `0`, median refill ratio `2.00`.
- `held_no_refill`: `n=149`, median attack `8`, median pulled estimate `0`, median refill ratio `0.00`.
- `gave_depleted`: `n=275`, median attack `7`, median pulled estimate `3`, median refill ratio `0.00`.
- `gave_pulled`: `n=20`, median attack `3`, median pulled estimate `8`, median refill ratio `0.00`.
- `no_initial_brick_refilled`: `n=81`, median attack `2`, median pulled estimate `0`, median refill ratio `3.20`.

Read:

- The descriptive labels are internally coherent in snapshot mode: refilled rows have refill, depleted/pulled rows do not.
- `gave_pulled` is rare and should not be over-read from snapshots. Pull attribution needs raw quote-event ordering around selected windows.
- `no_initial_brick_refilled` may be important later because it resembles same-side renewal after a thin/no-display contact, but this pass only labels it.

## Finding 4 - Consumed Conversions Are Not Explained By Broad Brick Yet

Consumed-conversion rows:

| lifecycle label | n | held-like | gave-like | no initial | ambiguous |
| --- | ---: | ---: | ---: | ---: | ---: |
| direct conversion with follow-through | 27 | 3 (11.1%) | 2 (7.4%) | 18 | 4 |
| conversion no follow-through | 16 | 3 (18.8%) | 1 (6.2%) | 11 | 1 |
| failed or churn conversion | 146 | 33 (22.6%) | 12 (8.2%) | 62 | 39 |

Read:

- Broad consumed-conversion anchors often do not show an initial displayed brick in snapshot mode.
- This does not contradict the T1 direct-conversion takeaway. T1 isolated direct conversion more cleanly; this T4 pass attaches Brick metrics to every broad synthetic consumed row.
- If direct conversion remains the best T1 finding, the next Brick pass for that topic should be narrower: event-level replay around explicit conversion moments only.

## Primary Bucket Check

The smaller primary-development bucket had the same broad shape:

- band failures: `6 / 6` were `no_initial_brick`.
- band tests: `13 / 31` were `held_refilled`, `9 / 31` were `gave_depleted`, and `4 / 31` were `no_initial_brick_refilled`.
- consumed conversions: `2 / 6` were `held_refilled`, `2 / 6` were `no_initial_brick`, and `1 / 6` was `no_initial_brick_refilled`.

Read:

- The primary bucket does not overturn the full-set read.
- It is useful for manual chart review because it contains fewer rows and includes the practical cases we were discussing.

## Working Conclusion

Parked T4 takeaway:

- Brick contact response is useful only when anchored to the actual test/contact moment.
- Failure rows themselves are too late for Brick.
- Depleted/no-refill contact is most associated with `no_structural_followthrough`.
- Same-side continued/weak holds are more often held/refilled, but the separation is not clean enough to become a rule.
- Broad consumed-conversion rows need a narrower event-level pass before Brick can say anything useful about direct conversion.

This is not an EAR/LL policy recommendation. It is another thesis note to carry into the later synthesis.

## Next Thesis Step

Continue the thesis list rather than synthesizing yet.

Natural next item from the original list is Thesis 5, Horizon. Thesis 7 refill overlaps with this Brick pass, but a stoprun/refill-specific T7 read should remain separate if we come back to it.
