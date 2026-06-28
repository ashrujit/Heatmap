# Band Lifecycle Fixture Pack - 2026-06-23 To 2026-06-26

## Purpose

This is the curated working map for upcoming band lifecycle / Skurry Now Lens hypothesis tests. It starts from user-memory windows, then uses synthetic LL/EAR replay from MarketRecorder NQ data to decide where each hypothesis should be developed, stressed, or held out.

Do not treat the replay auto-label as canonical truth. It is a first-pass objective summary of synthetic band transitions. In long directional initiatives, the current count-based classifier often calls the episode `balance_distribution` because both sides keep testing, holding, and failing while price still moves directionally. That behavior is part of the research problem.

## Provenance

- Sessions verified: `2026-06-23:NQU6` through `2026-06-26:NQU6`.
- Source: MarketRecorder NQ captures.
- Band stream: synthetic LL/EAR-style replay.
- Excluded for now: `2026-06-22:NQU6`, because the archived mapped Google Drive copy is not locally reliable yet.
- No live EAR logs from the mixed MNQ/NQ period were used.

Supporting artifacts:

- `research/out/band_lifecycle_verified_episode_chunks_20260623_20260626.csv`
- `research/out/band_lifecycle_verified_episode_chunks_20260623_20260626.md`
- `research/band_lifecycle_fixture_specs_2026-06-23_2026-06-26.json`
- `LevelLedger/research/verify_episode_fixtures.py`

## Primary Development Fixtures

Use these first when testing a narrow thesis. They are the cleanest replay-confirmed supply initiative windows.

| id | why it belongs here |
| --- | --- |
| `20260624_1055_1110_supply_transition` | Memory expected supply transition and replay labels `directional_supply`. Good seed for first credible sponsor, renewal, and approach/away behavior. |
| `20260625_1215_1230_supply_burst` | Memory expected short supply episode and replay labels `directional_supply` with supply-side dominance. Good compact fixture for controlled tests. |

Initial thesis uses:

- How same-side renewal appears beyond a sponsor failure.
- Whether approach-side book pull/reload helps separate weak hold from terminal failure.
- Whether move-away intensity differs after real failure versus fake failure / renewal.
- Whether direct conversion remains the strongest consumed-band signal inside clean initiative windows.

## Directional With Churn Stress Fixtures

Use these after a rule or label works on the primary fixtures. They are useful because memory and net price action point directionally, but synthetic lifecycle counts show heavy two-sided testing.

| id | expected use |
| --- | --- |
| `20260623_1000_1130_supply_claims` | Supply-memory window with net lower move, but replay sees two-sided churn and demand-dominant counts. Stress test for not discarding directional ownership just because both sides were active. |
| `20260623_1330_1600_supply_resolution` | PM lower resolution with supply-dominant replay but balance auto-label. Good stress case for initiative continuing through many test/failure events. |
| `20260624_1210_1600_supply_owned` | Long supply-owned memory window, large net lower move, huge two-sided lifecycle count. Good stress case for episode segmentation; probably too broad for first-pass rules. |
| `20260626_1310_1500_supply_directional` | PM lower initiative after the 13:05/13:10 test area. Good stress case once the supply-test-survived window is reviewed manually. |

These should be segmented into smaller micro-auctions before deriving rule changes. Broad-window counts will tend to wash out the lifecycle sequence.

## Balance / Distribution Counter Fixtures

Use these to make sure a proposed signal does not simply find activity in every busy auction.

| id | expected use |
| --- | --- |
| `20260624_0930_1055_rotational` | Clean early rotational / contested case; replay agrees on balance distribution. |
| `20260624_1110_1210_repair` | Repair inside broader supply day. Useful for fake failure vs balance repair semantics. |
| `20260625_1000_1055_repair_balance` | Repair after no-build liquidation; supply attempts failed but price also did not build durable lower demand. |
| `20260623_1130_1330_repair_balance_dcs` | Repair into PM balance with possible DCS support. Useful for consumed-band hold classification, but not a clean initiative fixture. |
| `20260626_0930_1145_no_build_up_contested_supply` | Long early up move with contested supply attempts and many snapshot gaps. Good stress case for no-build / contested-up behavior. |

## No-Build / Data-Quality Caution Fixtures

These are useful, but should not be the first place to judge a lifecycle thesis.

| id | caution |
| --- | --- |
| `20260625_0930_1000_no_build_liquidation` | Memory expects no-build liquidation and net price confirms large liquidation, but replay has many gaps and odd modulo display around contract price. Use only as a no-build stress case. |
| `20260626_1145_1150_supply_build` | Memory expects supply build, but the 5-minute replay window has zero synthetic transitions. Widen to roughly `11:40-12:00` before judging. |
| `20260623_0930_1000_no_build_up` | Memory expects no-build up, but replay sees many band events. Useful as an open-drive counter, not a clean no-build proof. |

## Review / Holdout Fixtures

These conflict enough with memory or the coarse replay label that they should be manually inspected before becoming training fixtures. They are valuable holdouts because they will expose overfit lifecycle rules.

| id | conflict |
| --- | --- |
| `20260625_1425_1545_supply_into_close` | Memory says supply into close; replay labels `directional_demand` despite net lower price. Could be hidden demand absorbing while price moves lower, or the broad window is mixing regimes. |
| `20260626_1305_1310_supply_test_survived` | Memory says supply test survived; replay excerpt shows a supply test/failure at `656.50`. This likely needs exact band identification and a wider before/after window. |
| `20260625_1055_1110_supply_burst` | Memory says short supply ownership; replay says contested/repair. Good review case for whether supply renewed beyond failure instead of cleanly holding. |

## Working Takeaways

1. Keep 6/22 out until the local archive is reliable.
2. Start new hypothesis work on the two compact primary supply fixtures.
3. Validate against balance/distribution fixtures before trusting any signal.
4. Stress against long directional-with-churn windows only after micro-auction boundaries are defined.
5. Treat conflicting fixtures as holdouts. They are likely the best tests for whether the new lifecycle semantics are real or just recoding hindsight.

