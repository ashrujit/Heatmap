# Afternoon Balance Control Probe

Codex-authored research artifact. This is not accepted Kahn policy.

Objective: use the 2026-08-28 ES short around 7725/7726 as a control case for scale-up logic. The question is not whether a root short could eventually work; it is whether Kahn should add size while price is accepted around value/HVN late in the session.

## Root Outcomes

| scenario | time | ref | 30m MFE/MAE | 60m MFE/MAE | full MFE/MAE | target | BE after +2 | BE after +4 |
| --- | --- | ---: | ---: | ---: | ---: | --- | --- | --- |
| first_supply_test_7726 | 13:49:34 | 7726.0 | 6.5/1.25 | 9.5/1.25 | 13.75/1.25 | 14:48:56 | 13:52:37 | 14:00:43 |
| supply_hold_7724_50 | 13:50:09 | 7724.5 | 5.0/2.75 | 9.25/2.75 | 12.25/2.75 | 14:48:56 | 13:59:17 | 13:59:17 |
| balance_retest_7726 | 14:02:48 | 7726.0 | 8.25/1.25 | 13.75/1.25 | 13.75/1.25 | 14:48:56 | 14:05:13 | - |

## Value-Churn Evidence

- Balance window `13:45:00-14:30:00` traded 7717.75-7727.25 with closes contained between 7719.5-7725.5.
- Local profile POC was `7723.5` and the top local HVN band was `7723-7726.5`; 81.3% of local volume printed inside 7721-7727.
- Top local bins: 7723.5:7449/372s;7724.5:6997/336s;7724:6125/338s;7723:6069/330s;7726:4440/175s;7725.5:4356/190s;7725:4248/214s;7722.5:3622/184s.
- LL churn in 7719-7729 had 48 supply claims, 23 demand claims, 5 supply fails, 5 demand fails, and 17 claim-side switches.
- First two post-balance 5-minute closes below 7720 arrived at `14:25:00`, but the next close back above 7720 arrived at `14:30:00`.
- First three post-balance closes below 7720 arrived at `14:55:00`; first two closes below 7716.50 arrived at `14:55:00`.

## Candidate Probe Rows

| probe | time | range | raw call | overlay call | runway | path% | future MFE/MAE |
| --- | --- | --- | --- | --- | ---: | ---: | ---: |
| sponsor_stack | 13:50:09 | 727-729.25 | sponsor_stack_add | suppress_add_value_churn_root_only | 8.0 | 15.8 | 12.25/2.75 |
| sponsor_stack | 14:04:44 | 727-729.25 | sponsor_stack_add | suppress_add_value_churn_root_only | 8.0 | 15.8 | 12.25/2.25 |
| sponsor_stack | 14:05:53 | 727-729.25 | sponsor_stack_add | suppress_add_value_churn_root_only | 8.0 | 15.8 | 12.25/2.25 |
| sponsor_stack | 14:13:15 | 727-729.25 | sponsor_stack_add | suppress_add_value_churn_root_only | 8.0 | 15.8 | 12.25/0.75 |
| holdroot_basic | 13:50:09 | 727-729.25 | add_preserve_root | suppress_add_value_churn_root_only | 8.0 | 15.8 | 12.25/2.75 |
| holdroot_basic | 14:04:44 | 727-729.25 | add_preserve_root | suppress_add_value_churn_root_only | 8.0 | 15.8 | 12.25/2.25 |
| holdroot_basic | 14:05:53 | 727-729.25 | add_preserve_root | suppress_add_value_churn_root_only | 8.0 | 15.8 | 12.25/2.25 |
| holdroot_basic | 14:13:15 | 727-729.25 | add_preserve_root | suppress_add_value_churn_root_only | 8.0 | 15.8 | 12.25/0.75 |
| holdroot_basic | 13:52:57 | 727-729.25 | add_review | suppress_add_value_churn_root_only | 8.0 | 15.8 | 12.25/2.75 |
| holdroot_basic | 14:11:30 | 727-729.25 | add_review | suppress_add_value_churn_root_only | 8.0 | 15.8 | 12.25/2.25 |
| tail_reclaim | 14:23:34 | 723-724.50 | tail_reclaim_harvest_not_add | suppress_add_value_churn_root_only | 2.75 | 71.1 | 7.0/5.5 |
| tail_reclaim | 14:23:35 | 721.75-725 | tail_reclaim_harvest_not_add | suppress_add_value_churn_root_only | 2.75 | 71.1 | 7.0/5.5 |
| tail_reclaim | 14:23:35 | 722-724 | tail_reclaim_harvest_not_add | suppress_add_value_churn_root_only | 2.75 | 71.1 | 7.0/5.5 |
| tail_reclaim | 14:23:35 | 721.50-723.25 | tail_reclaim_harvest_not_add | suppress_add_value_churn_root_only | 2.75 | 71.1 | 7.0/5.5 |
| tail_reclaim | 14:27:47 | 723-724.50 | tail_reclaim_harvest_not_add | suppress_add_value_churn_root_only | 4.0 | 57.9 | 8.25/4.25 |
| tail_reclaim | 14:29:37 | 722.25-729.25 | tail_reclaim_harvest_not_add | suppress_add_value_churn_root_only | 3.25 | 65.8 | 7.5/5.0 |
| tail_reclaim | 14:29:38 | 721.75-725 | tail_reclaim_harvest_not_add | suppress_add_value_churn_root_only | 2.75 | 71.1 | 7.0/5.5 |
| tail_reclaim | 14:29:38 | 722-724 | tail_reclaim_harvest_not_add | suppress_add_value_churn_root_only | 2.75 | 71.1 | 7.0/5.5 |

## Read

A root-only short from 13:49:34 at 7726.0 eventually had 13.75 points of MFE and only 1.25 points of MAE, reaching the 7716.5 floor at 14:48:56. So the root thesis was not absurd.

That is not the same as add permission. The trade spent the core 13:45-14:30 window rotating inside a local HVN/value-center band, with two-sided LL ownership claims and repeated returns toward the short area. The extension signal did not become structurally cleaner until after acceptance below 7720, and by then the session had shifted into late-day harvest/no-new-leverage territory.

The control result: 8 add-permission rows and 2 add-review rows were suppressed by value-churn context; 0 add-permission rows occurred only after the late extension gate. The policy implication is `root_only` or `max_adds=0` inside this state. If a trader chooses leverage anyway, a BE scratch after the market repairs back into the HVN is an acceptable outcome, not evidence that Kahn should keep pressing.

## Five-Minute Bars

- 13:15:00 O 7722.5 H 7723.25 L 7718.25 C 7720.0 vol 10137.0 delta 189.0
- 13:20:00 O 7720.0 H 7721.0 L 7714.5 C 7718.5 vol 11288.0 delta 280.0
- 13:25:00 O 7718.5 H 7722.25 L 7716.25 C 7717.0 vol 8381.0 delta -63.0
- 13:30:00 O 7717.25 H 7723.5 L 7716.0 C 7722.0 vol 8498.0 delta 680.0
- 13:35:00 O 7722.25 H 7724.0 L 7714.75 C 7715.25 vol 10129.0 delta -585.0
- 13:40:00 O 7715.25 H 7720.5 L 7715.25 C 7719.5 vol 8723.0 delta 577.0
- 13:45:00 O 7719.5 H 7726.25 L 7717.75 C 7725.5 vol 8537.0 delta 759.0
- 13:50:00 O 7725.5 H 7726.5 L 7723.0 C 7723.75 vol 6112.0 delta -30.0
- 13:55:00 O 7723.75 H 7724.75 L 7719.5 C 7724.25 vol 7427.0 delta -119.0
- 14:00:00 O 7724.25 H 7727.25 L 7722.25 C 7724.0 vol 9488.0 delta 598.0
- 14:05:00 O 7724.0 H 7726.75 L 7722.25 C 7724.75 vol 6930.0 delta -106.0
- 14:10:00 O 7724.75 H 7726.75 L 7720.75 C 7721.0 vol 6809.0 delta 27.0
- 14:15:00 O 7721.0 H 7724.25 L 7720.25 C 7723.0 vol 6673.0 delta 265.0
- 14:20:00 O 7723.0 H 7724.75 L 7718.0 C 7719.5 vol 6347.0 delta -155.0
- 14:25:00 O 7719.5 H 7722.25 L 7717.75 C 7719.5 vol 7514.0 delta 278.0
- 14:30:00 O 7719.5 H 7724.0 L 7719.0 C 7722.75 vol 6304.0 delta 90.0
- 14:35:00 O 7723.0 H 7724.75 L 7719.75 C 7720.0 vol 5886.0 delta -136.0
- 14:40:00 O 7720.25 H 7723.0 L 7719.5 C 7721.75 vol 4832.0 delta 132.0
- 14:45:00 O 7721.75 H 7722.25 L 7716.5 C 7717.0 vol 6458.0 delta -420.0
- 14:50:00 O 7717.0 H 7717.0 L 7712.25 C 7714.75 vol 10835.0 delta -277.0
- 14:55:00 O 7714.75 H 7717.25 L 7712.75 C 7716.0 vol 8711.0 delta 699.0
- 15:00:00 O 7716.0 H 7718.75 L 7713.75 C 7717.0 vol 8617.0 delta -79.0
- 15:05:00 O 7717.0 H 7723.0 L 7716.5 C 7722.75 vol 9689.0 delta 73.0
- 15:10:00 O 7722.75 H 7723.25 L 7719.0 C 7721.75 vol 6651.0 delta -51.0