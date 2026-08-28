# 2026-08-27 Kahn Counterfactual Adds And Entry Mode

This pass treats Kahn's logged actions as a baseline and asks where different add or entry mechanics could have mattered.

## Add Candidates

| Symbol | ET | Side | Candidate | Logged | Price | 30m MFE | 30m MAE | GEX nearest | GEX dist |
|---|---:|---|---|---|---:|---:|---:|---|---:|
| ES | 09:54:03 | Long | suppressed_same_side_no_add_zone | no_add_zone/inside_no_add_zone | 7723.75 | 3.75 | 16.5 | oi_put_wall | -5.06 |
| ES | 09:54:44 | Long | suppressed_same_side_no_add_zone | no_add_zone/inside_no_add_zone | 7724 | 3.5 | 16.75 | oi_put_wall | -4.81 |
| ES | 10:23:18 | Long | suppressed_same_side_no_add_zone | no_add_zone/inside_no_add_zone | 7725.25 | 10.75 | 3.5 | oi_put_wall | -2.87 |
| ES | 10:35:36 | Long | suppressed_same_side_no_add_zone | no_add_zone/inside_no_add_zone | 7727.5 | 11 | 3 | oi_put_wall | -0.54 |
| ES | 13:44:34 | Short | holdroot_shadowed_add | build_trial/build_trial_alive | 7749.5 | 18.75 | 0.25 | call_wall | -4.44 |
| ES | 13:44:39 | Short | holdroot_shadowed_add | build_trial/build_trial_alive | 7748.25 | 17.5 | 0.5 | call_wall | -5.69 |
| ES | 13:44:57 | Short | holdroot_shadowed_add | build_trial/build_trial_alive | 7747.75 | 17 | 0.5 | call_wall | -6.19 |
| ES | 14:01:28 | Short | holdroot_shadowed_add | build_trial/build_trial_alive | 7741.5 | 17.75 | 0.25 | zero_gamma | 7.14 |
| ES | 14:10:55 | Short | suppressed_same_side_evaluate_zone | evaluate_zone/inside_evaluate_zone | 7734.25 | 10.5 | 2 | zero_gamma | -0.48 |
| ES | 14:12:14 | Short | suppressed_same_side_evaluate_zone | evaluate_zone/inside_evaluate_zone | 7734.5 | 10.75 | 1.75 | zero_gamma | -1.08 |
| ES | 14:14:12 | Short | suppressed_same_side_no_add_zone | no_add_zone/inside_no_add_zone | 7731.5 | 7.75 | 4.75 | oi_put_wall | 2.97 |
| ES | 14:19:35 | Short | suppressed_same_side_evaluate_zone | evaluate_zone/inside_evaluate_zone | 7734.5 | 10.75 | 1.25 | zero_gamma | -0.95 |
| ES | 14:24:04 | Short | suppressed_same_side_no_add_zone | no_add_zone/inside_no_add_zone | 7731.75 | 8 | 1 | oi_put_wall | 3.8 |
| ES | 14:25:25 | Short | suppressed_same_side_no_add_zone | no_add_zone/inside_no_add_zone | 7731.25 | 8.5 | 1.25 | oi_put_wall | 3.3 |
| NQ | 10:12:51 | Long | holdroot_shadowed_add | build_trial/build_trial_alive | 29569 | 54.5 | 26.75 | oi_call_wall | -4.62 |
| NQ | 10:12:51 | Long | holdroot_shadowed_add | build_trial/build_trial_alive | 29569 | 54.5 | 26.75 | oi_call_wall | -4.62 |
| NQ | 10:12:56 | Long | holdroot_shadowed_add | build_trial/build_trial_alive | 29568.5 | 55 | 26.25 | oi_call_wall | -5.12 |
| NQ | 10:13:49 | Long | holdroot_shadowed_add | build_trial/build_trial_alive | 29581.5 | 42 | 40.5 | oi_call_wall | 7.88 |
| NQ | 10:13:58 | Long | holdroot_shadowed_add | build_trial/build_trial_alive | 29583.75 | 39.75 | 43.75 | call_wall | -9.87 |
| NQ | 11:00:03 | Long | suppressed_same_side_no_add_zone | no_add_zone/inside_no_add_zone | 29597.5 | 37.5 | 24.5 | oi_call_wall | 25.38 |
| NQ | 11:26:30 | Long | suppressed_same_side_no_add_zone | no_add_zone/inside_no_add_zone | 29589.75 | 20.25 | 78.25 | oi_call_wall | 15.19 |

## Probe Entries

| Symbol | ET | Side | Fill | Exit | Actual pts | 5m MFE | 5m MAE | 30m MFE | 30m MAE | Limit 1t fill | Limit 2t fill |
|---|---:|---|---:|---|---:|---:|---:|---:|---:|---:|---:|
| ES | 09:54:03 | Long | 7724 | Flatten 09:55:45 | -6 | 1.25 | 16.75 | 3.5 | 16.75 | 0.075 | 3.057 |
| NQ | 10:01:16 | Long | 29515.75 | Flatten 10:07:03 | -7.25 | 41.75 | 16.75 | 107.75 | 16.75 | 0.017 | 0.189 |
| ES | 10:01:25 | Long | 7717.75 | Flatten 10:07:10 | -4.75 | 4.5 | 2.25 | 12.5 | 5.75 | 0.008 | 0.008 |
| NQ | 10:07:08 | Long | 29518.5 | Flatten 10:14:41 | 50.75 | 53.5 | 10.25 | 105 | 10.25 | 0.075 | 0.075 |
| ES | 10:07:53 | Long | 7718 | none_in_log | - | 3 | 4.5 | 14.25 | 4.5 | 0.262 | 0.289 |
| NQ | 10:57:18 | Long | 29585.25 | Reduce 11:03:42 | 8.5 | 30.25 | 10.25 | 49.75 | 10.25 | 0.002 | 0.002 |
| NQ | 11:25:59 | Long | 29590.75 | Flatten 11:29:34 | -13.75 | 7.5 | 24.75 | 19.25 | 79.25 | 0.445 | 0.574 |
| ES | 13:39:03 | Short | 7748.75 | Retire 14:31:48 | 19.5 | 0.5 | 2.5 | 13 | 2.5 | 0.103 | 14.783 |

## Files

- `research\kahn\out\2026-08-27-gex-kahn\counterfactual_add_candidates.csv`
- `research\kahn\out\2026-08-27-gex-kahn\probe_entry_mode.csv`
