# 2026-08-27 GEX Overlay Hypothesis Evaluation

This is an offline baseline-vs-overlay research pass, not a runtime policy proposal.

## Method

- Harvest cases test whether a stable GEX terminal level would have staged a passive reduce/retire before LL failure.
- Add cases start only from Kahn-observed same-side LL moments that were logged as `HoldRoot` or `SuppressAdd`.
- Probe order-mode rows are included only as a low-priority variance check.
- GEX never creates entry or add permission in this pass; it only classifies management context around existing Kahn evidence.

## Counts

- Harvest overlay rows: 7 (stage_passive_harvest=4, test_nearmiss_reduce=2, tighten_no_passive_fill=1)
- Add candidate rows: 21 (arm_wall_conversion_pending_acceptance=2, keep_suppressed_or_review=3, keep_suppressed_path_variance=4, keep_suppressed_terminal=8, review_possible_add=1, test_holdroot_to_add_conversion=3)
- Probe rows: 8 (market_or_one_tick_urgency=1, test_limit_first_loss_reduction=4, test_limit_first_variance_reduction=3)

## Harvest / Exit Overlay

| Case | Action | Trigger | Limit | Touched | Touch | Before Baseline | Wall Stability | Window |
|---|---|---:|---:|---|---:|---:|---:|---|
| es_long_terminal_nearmiss_7743 | tighten_no_passive_fill | 11:17:00 | 7743 | False | - | - | call_wall 7743.04-7743.87 | 7733.75-7742.75 |
| es_long_terminal_nearmiss_7743 | test_nearmiss_reduce | 11:17:00 | 7742.75 | True | 11:17:09 | - | call_wall 7743.04-7743.87 | 7733.75-7742.75 |
| es_long_terminal_nearmiss_7743 | test_nearmiss_reduce | 11:17:00 | 7742.5 | True | 11:17:00 | - | call_wall 7743.04-7743.87 | 7733.75-7742.75 |
| es_short_target_7728_7729_50 | stage_passive_harvest | 14:26:42 | 7729.5 | True | 14:26:48 | 4.99 | oi_put_wall 7727.95-7728.01 | 7723.75-7736.25 |
| es_short_target_7728_7729_50 | stage_passive_harvest | 14:26:42 | 7729 | True | 14:27:01 | 4.78 | oi_put_wall 7727.95-7728.01 | 7723.75-7736.25 |
| es_short_target_7728_7729_50 | stage_passive_harvest | 14:26:42 | 7728.5 | True | 14:27:11 | 4.61 | oi_put_wall 7727.95-7728.01 | 7723.75-7736.25 |
| es_short_target_7728_7729_50 | stage_passive_harvest | 14:26:42 | 7728 | True | 14:27:15 | 4.55 | oi_put_wall 7727.95-7728.01 | 7723.75-7736.25 |

Read: the short target supports passive harvest into the `7728-7729.50` zone; the long target supports a separate near-miss reduce/tighten test because the exact `7743` limit was not touched.

## Add Overlay

| Symbol | ET | Side | Overlay | Logged | Price | 30m MFE/MAE | Source | Target Runway | Zero Ahead |
|---|---:|---|---|---|---:|---:|---|---:|---:|
| ES | 09:54:03 | Long | keep_suppressed_path_variance | no_add_zone/inside_no_add_zone | 7723.75 | 3.75/16.5 | oi_put_wall 7728.81 (-5.06) | call_wall 19.8 | - |
| ES | 09:54:44 | Long | keep_suppressed_path_variance | no_add_zone/inside_no_add_zone | 7724 | 3.5/16.75 | oi_put_wall 7728.81 (-4.81) | call_wall 19.55 | - |
| ES | 10:23:18 | Long | arm_wall_conversion_pending_acceptance | no_add_zone/inside_no_add_zone | 7725.25 | 10.75/3.5 | oi_put_wall 7728.12 (-2.87) | call_wall 17.87 | - |
| ES | 10:35:36 | Long | arm_wall_conversion_pending_acceptance | no_add_zone/inside_no_add_zone | 7727.5 | 11/3 | oi_put_wall 7728.04 (-0.54) | call_wall 15.54 | - |
| ES | 13:44:34 | Short | test_holdroot_to_add_conversion | build_trial/build_trial_alive | 7749.5 | 18.75/0.25 | call_wall 7753.94 (-4.44) | oi_put_wall 20.56 | 15.48 |
| ES | 13:44:39 | Short | test_holdroot_to_add_conversion | build_trial/build_trial_alive | 7748.25 | 17.5/0.5 | call_wall 7753.94 (-5.69) | oi_put_wall 19.31 | 14.23 |
| ES | 13:44:57 | Short | test_holdroot_to_add_conversion | build_trial/build_trial_alive | 7747.75 | 17/0.5 | call_wall 7753.94 (-6.19) | oi_put_wall 18.81 | 13.73 |
| ES | 14:01:28 | Short | review_possible_add | build_trial/build_trial_alive | 7741.5 | 17.75/0.25 | zero_gamma 7734.36 (7.14) | oi_put_wall 12.97 | 7.14 |
| ES | 14:14:12 | Short | keep_suppressed_terminal | no_add_zone/inside_no_add_zone | 7731.5 | 7.75/4.75 | zero_gamma 7736.03 (-4.53) | oi_put_wall 2.97 | - |
| ES | 14:24:04 | Short | keep_suppressed_terminal | no_add_zone/inside_no_add_zone | 7731.75 | 8/1 | zero_gamma 7736.75 (-5) | oi_put_wall 3.8 | - |
| ES | 14:25:25 | Short | keep_suppressed_terminal | no_add_zone/inside_no_add_zone | 7731.25 | 8.5/1.25 | zero_gamma 7735.45 (-4.2) | oi_put_wall 3.3 | - |
| NQ | 10:12:51 | Long | keep_suppressed_terminal | build_trial/build_trial_alive | 29569 | 54.5/26.75 | zero_gamma 29423.78 (145.22) | oi_call_wall 4.62 | - |
| NQ | 10:12:51 | Long | keep_suppressed_terminal | build_trial/build_trial_alive | 29569 | 54.5/26.75 | zero_gamma 29423.78 (145.22) | oi_call_wall 4.62 | - |
| NQ | 10:12:56 | Long | keep_suppressed_terminal | build_trial/build_trial_alive | 29568.5 | 55/26.25 | zero_gamma 29423.78 (144.72) | oi_call_wall 5.12 | - |
| NQ | 10:13:49 | Long | keep_suppressed_terminal | build_trial/build_trial_alive | 29581.5 | 42/40.5 | zero_gamma 29509.52 (71.98) | call_wall 12.12 | - |
| NQ | 10:13:58 | Long | keep_suppressed_terminal | build_trial/build_trial_alive | 29583.75 | 39.75/43.75 | zero_gamma 29509.52 (74.23) | call_wall 9.87 | - |
| NQ | 11:00:03 | Long | keep_suppressed_path_variance | no_add_zone/inside_no_add_zone | 29597.5 | 37.5/24.5 | zero_gamma 29508.9 (88.6) | call_wall 64.62 | - |
| NQ | 11:26:30 | Long | keep_suppressed_path_variance | no_add_zone/inside_no_add_zone | 29589.75 | 20.25/78.25 | zero_gamma 29529.59 (60.16) | call_wall 24.81 | - |

Read: ES has testable add-conversion candidates. NQ mostly remains suppression/path-variance evidence, not add evidence.

## Probe Order Mode Appendix

| Symbol | ET | Side | Overlay | Outcome | Actual | 1t/2t Delay |
|---|---:|---|---|---|---:|---:|
| ES | 09:54:03 | Long | test_limit_first_loss_reduction | losing_probe | -6 | 0.075/3.057 |
| NQ | 10:01:16 | Long | test_limit_first_loss_reduction | losing_probe | -7.25 | 0.017/0.189 |
| ES | 10:01:25 | Long | test_limit_first_loss_reduction | losing_probe | -4.75 | 0.008/0.008 |
| NQ | 10:07:08 | Long | test_limit_first_variance_reduction | winning_probe | 50.75 | 0.075/0.075 |
| ES | 10:07:53 | Long | test_limit_first_variance_reduction | open_or_manual | - | 0.262/0.289 |
| NQ | 10:57:18 | Long | test_limit_first_variance_reduction | winning_probe | 8.5 | 0.002/0.002 |
| NQ | 11:25:59 | Long | test_limit_first_loss_reduction | losing_probe | -13.75 | 0.445/0.574 |
| ES | 13:39:03 | Short | market_or_one_tick_urgency | winning_probe | 19.5 | 0.103/14.783 |

## Output Files

- `research\kahn\out\2026-08-27-gex-kahn\gex_overlay_harvest_decisions.csv`
- `research\kahn\out\2026-08-27-gex-kahn\gex_overlay_add_decisions.csv`
- `research\kahn\out\2026-08-27-gex-kahn\gex_overlay_probe_order_mode.csv`
