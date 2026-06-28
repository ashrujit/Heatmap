# Skurry Refill Thesis 7 Findings - 2026-06-27

## Scope

This is the first runnable Thesis 7 pass from `SKURRY_NOW_LENS_RESEARCH_NOTE_2026-06-27.md`.

Inputs:

- MarketRecorder `NQU6` only.
- Sessions: `2026-06-23`, `2026-06-24`, `2026-06-25`, `2026-06-26`.
- T3 lifecycle anchors plus T4 Brick contact metrics.
- Fixture windows from `research/band_lifecycle_fixture_specs_2026-06-23_2026-06-26.json`.
- No live EAR logs from the mixed MNQ/NQ period.
- `2026-06-22` excluded until the archived Google Drive copy is locally reliable.

Outputs:

- `LevelLedger/research/refill_after_sweep_probe.py`
- `research/out/refill_after_sweep_probe_20260623_20260626.csv`
- `research/out/refill_after_sweep_probe_20260623_20260626.md`
- `research/out/refill_after_sweep_probe_primary_dev_20260623_20260626.csv`
- `research/out/refill_after_sweep_probe_primary_dev_20260623_20260626.md`

## Method

This pass does not rediscover bands. It reads the T4 Brick output and relabels contact aftermath:

- `displayed_sweep`: displayed size existed and attack/remove/consumed evidence was material.
- `thin_refill_after_trace`: little/no displayed size existed, but same-side depth appeared after a contact trace.
- `consumed_synthetic_no_visible_sweep`: synthetic consumed-conversion rows where broad snapshot mode did not see a visible same-price sweep.
- refill labels: `delayed_refill`, `thin_delayed_refill`, `depleted_no_refill`, `mixed_no_refill`, `survived_no_refill`, `no_visible_refill`.

The broad pass still inherits T4's snapshot limitation. It can describe 2s refill/reappearance, but it cannot validate the 250ms bucket well.

I attempted a narrow `--book-events` replay for the primary-development bucket to sanity-check the fast bucket. It was still running after several minutes without output, so I stopped it. The fast-refill question remains open for selected quote-event windows.

## Coverage

Full fixture pass:

- source rows after filters: `1158`;
- clean source rows: `1156`;
- sweep/refill aftermath rows: `841`;
- displayed sweeps: `600`;
- thin refill-after-trace rows: `52`;
- consumed synthetic/no-visible-sweep rows: `188`;
- consumed displayed sweeps: `1`.

Primary-development bucket:

- source rows after filters: `38`;
- clean source rows: `37`;
- sweep/refill aftermath rows: `30`.

## Finding 1 - Delayed Refill Leans Toward Defense, But Is Not A Rule

Full-set delayed refill:

- `delayed_refill`: `118` rows; `59.3%` refill-supported defense, `24.6%` refill failed to hold, `16.1%` refill but contested.
- `thin_delayed_refill`: `60` rows; `55.0%` refill-supported defense, `35.0%` refill failed to hold, `10.0%` contested.

Displayed sweeps only:

| refill label | n | owner defended | terminal failure | no structural follow-through | contested/balance |
| --- | ---: | ---: | ---: | ---: | ---: |
| delayed refill | 101 | 66.3% | 12.9% | 2.0% | 18.8% |
| depleted/no refill | 250 | 48.8% | 24.8% | 15.2% | 11.2% |
| mixed/no refill | 76 | 72.4% | 9.2% | 3.9% | 14.5% |
| survived/no refill | 173 | 57.2% | 22.5% | 5.8% | 14.5% |

Read:

- Same-side 2s refill after a sweep is directionally useful context.
- It is not enough to declare a fake failure or sponsor renewal by itself.
- It becomes interesting only when paired with the auction consequence: price rejects/repairs and then destroys opposing structure.

## Finding 2 - No Refill Does Not Mean The Band Failed

The strongest caution is the no-refill side:

- `depleted_no_refill`: `265` rows; `42.6%` continuation/failed repair, but `46.8%` defense without visible refill.
- `survived_no_refill`: `215` rows; `47.4%` display-survived defense, `40.9%` display survived but later failed, `11.6%` contested.

Read:

- A band can defend because displayed size simply survives, not because it visibly refills.
- A band can also show surviving display and still fail later.
- So T7 cannot support an if/else rule like "no refill means continuation through the level."

This ties back to the current lifecycle theme: tests and failures need consequence semantics, not only local DOM aftermath.

## Finding 3 - Direct Conversions Are Not A Refill Story In This Broad Pass

Consumed-conversion rows:

| refill label | n | conversion churn | direct conversion |
| --- | ---: | ---: | ---: |
| delayed refill | 17 | 82.4% | 17.6% |
| depleted/no refill | 15 | 86.7% | 13.3% |
| mixed/no refill | 11 | 90.9% | 9.1% |
| no visible refill | 91 | 80.2% | 19.8% |
| survived/no refill | 42 | 92.9% | 7.1% |
| thin delayed refill | 13 | 100.0% | 0.0% |

Read:

- Most direct conversions still had no visible refill in this broad snapshot pass: `18 / 27` were `no_visible_refill`.
- This does not weaken the T1 direct-conversion takeaway. It says the broad T7 refill lens is not the reason direct conversion worked.
- The direct-conversion edge looks more like auction relocation/no-revisit behavior than same-price passive refill.

## Primary Bucket Check

Primary-development rows were small but useful:

- `delayed_refill`: `7` rows; `5` refill-supported defense, `2` contested, `0` failed.
- `thin_delayed_refill`: `5` rows; `3` supported defense, `1` failed, `1` contested.
- `depleted_no_refill`: `9` rows; `4` continuation/failed repair, `5` defense without visible refill.

Read:

- The primary bucket is more favorable to delayed refill than the full set.
- The same warning remains: depletion/no-refill splits almost evenly between failed repair and defended zones.
- These rows are good manual review candidates, not a rule.

## Working Conclusion

Parked T7 takeaway:

- Delayed same-side refill after a sweep/contact is worth carrying forward as a descriptive aftermath marker.
- It should not classify a test/failure alone.
- No-refill/depletion is especially dangerous as a standalone read because many zones defend without visible new adds.
- The 250ms fast-refill bucket is unresolved in the broad pass because MarketRecorder snapshots are too coarse; selected quote-event replay is needed.
- For EAR/LL purposes, T7 reinforces the idea that fake failure, true failure, and successful test need local lifecycle semantics: contact, refill/survival, repair, and destruction of opposing structure.

This is not an EAR/LL policy recommendation. It is another thesis note to carry into the later synthesis.

## Next Thesis Step

T7 is not the last thesis in the source list.

Remaining source-list items:

- Thesis 8: Book Thinning.
- Thesis 9: Hidden Liquidity.
- Thesis 2: Driver, if we circle back to the item we skipped when choosing T3 earlier.
