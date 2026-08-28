# 2026-08-27 GEX Management Hypothesis Scan

This is an evidence inventory, not a policy recommendation.

## Coverage

- GEX cache: ES_SPX and NQ_NDX minute-level classic `gex_zero` rows from RTH open.
- Tick data: MarketRecorder ESU6/NQU6 RTH 1-minute bars.
- Kahn data: ES/NQ policy decisions and LL transitions from JSONL logs.
- Prior 2026-08-24/25 Kahn notes are controls for general Kahn harvest/add failure modes, not GEX proof.

## GEX Wall-Touch / Near-Miss Clusters

| Symbol | ET | Field | Side | Level | Price | Vol pct | Delta | 30m Resp/Ext | LL Near | Policy Near | Class |
|---|---:|---|---|---:|---|---:|---:|---:|---|---|---|
| ES | 09:47:00-09:50:00 | zero_gamma | lower | 7712.61 | 7708.25-7721.75 | 96% | -33 | 13.77/4.73 | 09:47:24 RailTested Demand 7713.5-7714; 09:47:25 RailTested Demand 7712.5-7713; 09:47:35 RailTested Demand 7710.75-7711; 09:47:51 RailHeld Demand 7710.75-7711 | 09:54:03 AllowProbe trap_probe/same_side_lean_at_trap_probe; 09:55:45 Flatten build_trial/risk_anchor_failed | campaign_relevant_touch |
| ES | 09:56:00-10:00:00 | zero_gamma | upper | 7712.98 | 7707.25-7720 | 93% | -391 | 1.3/16.95 | 09:56:54 RailTested Demand 7712.25-7713.75; 09:57:58 RailOwned Supply 7711.75-7713.5; 09:57:58 RailFailed Demand 7712.25-7713.75; 09:58:27 RailTested Supply 7711.75-7713.5 | 09:54:03 AllowProbe trap_probe/same_side_lean_at_trap_probe; 09:55:45 Flatten build_trial/risk_anchor_failed; 10:01:25 AllowProbe trap_probe/same_side_lean_at_trap_probe; 10:07:10 Flatten build_trial/risk_anchor_failed | campaign_relevant_touch |
| ES | 14:27:00-14:38:00 | oi_put_wall | lower | 7728.01 | 7724.25-7731.25 | 65% | 2019 | 5.24/5.26 | 14:27:52 RailOwned Supply 7729.75-7730.75; 14:31:40 RailTested Supply 7729.75-7730.75; 14:31:48 RailOwned Demand 7725.75-7726.5; 14:33:49 RailTested Demand 7725.75-7726.5 | 14:31:48 Retire target_zone/opposite_ownership_at_target | campaign_relevant_touch |
| ES | 10:06:00-10:08:00 | zero_gamma | lower | 7712.67 | 7712-7721.25 | 84% | 134 | 19.58/-1.58 | 10:06:34 RailTested Demand 7712-7714.75; 10:07:53 RailHeld Demand 7712-7714.75; 10:08:11 RailTested Demand 7712-7714.75; 10:10:11 RailHeld Demand 7712-7714.75 | 10:07:10 Flatten build_trial/risk_anchor_failed; 10:07:53 AllowProbe trap_probe/same_side_lean_at_trap_probe | responsive_terminal_candidate |
| ES | 10:23:00-10:48:00 | oi_put_wall | lower | 7728.55 | 7721.75-7732.25 | 69% | 713 | 14.71/-0.71 | 10:27:13 RailOwned Demand 7725.25-7726; 10:27:19 RailOwned Demand 7725.75-7726.75; 10:28:35 RailTested Demand 7725.75-7726.75; 10:28:49 RailTested Demand 7725.25-7726 | - | responsive_terminal_candidate |
| ES | 10:55:00-10:57:00 | oi_put_wall | lower | 7728.55 | 7728.75-7733.5 | 67% | -1096 | 14.2/-1.95 | 10:53:42 RailTested Demand 7730.25-7730.5; 10:54:51 RailHeld Demand 7730.25-7730.5; 10:55:31 RailTested Demand 7730.25-7730.5; 10:58:46 RailHeld Demand 7730.25-7730.5 | - | responsive_terminal_candidate |
| ES | 11:17:00-11:19:00 | call_wall | upper | 7743.84 | 7740.25-7742.75 | 44% | -313 | 18.59/-1.34 | - | - | responsive_terminal_candidate |
| ES | 11:39:00-11:50:00 | oi_put_wall | lower | 7728.87 | 7725.25-7732.25 | 78% | -43 | 12.63/-2.38 | - | - | responsive_terminal_candidate |
| ES | 12:59:00-13:03:00 | call_wall | upper | 7754.05 | 7750.25-7753.5 | 28% | -207 | 5.55/1.45 | 13:06:49 RailOwned Supply 7752-7753.25; 13:08:04 RailTested Supply 7752-7753.25; 13:09:40 RailFailed Supply 7752-7753.25; 13:10:30 RailOwned Demand 7749.5-7752.5 | - | responsive_terminal_candidate |
| ES | 13:00:00-13:03:00 | oi_call_wall | upper | 7754.05 | 7751.5-7753.5 | 28% | -395 | 5.55/1.45 | 13:06:49 RailOwned Supply 7752-7753.25; 13:08:04 RailTested Supply 7752-7753.25; 13:09:40 RailFailed Supply 7752-7753.25; 13:10:30 RailOwned Demand 7749.5-7752.5 | - | responsive_terminal_candidate |
| ES | 13:08:00-13:25:00 | call_wall | upper | 7753.98 | 7749.75-7755.5 | 9% | -3549 | 10.48/-1.48 | 13:06:49 RailOwned Supply 7752-7753.25; 13:08:04 RailTested Supply 7752-7753.25; 13:09:40 RailFailed Supply 7752-7753.25; 13:10:30 RailOwned Demand 7749.5-7752.5 | - | responsive_terminal_candidate |
| ES | 13:08:00-13:25:00 | oi_call_wall | upper | 7753.98 | 7749.75-7755.5 | 9% | -3549 | 10.48/-1.48 | 13:06:49 RailOwned Supply 7752-7753.25; 13:08:04 RailTested Supply 7752-7753.25; 13:09:40 RailFailed Supply 7752-7753.25; 13:10:30 RailOwned Demand 7749.5-7752.5 | - | responsive_terminal_candidate |
| ES | 14:41:00-14:41:00 | zero_gamma | upper | 7733.09 | 7730-7732.5 | 37% | 24 | 10.34/0.41 | 14:41:14 RailFailed Supply 7729.75-7730.75 | - | responsive_terminal_candidate |
| ES | 14:48:00-14:48:00 | zero_gamma | upper | 7733.2 | 7729.5-7732.25 | 26% | -116 | 10.45/0.55 | 14:49:56 RailOwned Supply 7729.75-7731.75 | - | responsive_terminal_candidate |
| ES | 14:57:00-15:06:00 | oi_put_wall | lower | 7727.87 | 7725-7731.75 | 52% | 1876 | 9.63/-1.13 | 14:55:18 RailOwned Supply 7726-7726.25; 14:55:43 RailTested Supply 7726-7726.25; 14:58:44 RailTested Supply 7728.75-7728.75; 14:59:01 RailFailed Supply 7726-7726.25 | - | responsive_terminal_candidate |
| ES | 15:08:00-15:08:00 | zero_gamma | lower | 7729.07 | 7729.75-7732 | 32% | -62 | 8.68/0.07 | 15:07:15 RailOwned Demand 7729.25-7729.25; 15:08:19 RailTested Demand 7729.25-7729.25; 15:08:56 RailHeld Demand 7729.25-7729.25; 15:09:28 RailFailed Supply 7729.75-7731.75 | - | responsive_terminal_candidate |
| ES | 15:14:00-15:19:00 | zero_gamma | lower | 7729.77 | 7730-7733.75 | 33% | -99 | 9.98/0.77 | 15:14:55 RailTested Demand 7729.25-7729.25; 15:15:44 RailHeld Demand 7729.25-7729.25; 15:25:13 RailTested Demand 7729.25-7729.25; 15:26:24 RailHeld Demand 7729.25-7729.25 | - | responsive_terminal_candidate |
| ES | 15:25:00-15:25:00 | zero_gamma | lower | 7728.55 | 7729.25-7731.5 | 54% | -102 | 15.95/-0.45 | 15:25:13 RailTested Demand 7729.25-7729.25; 15:26:24 RailHeld Demand 7729.25-7729.25; 15:27:17 RailTested Demand 7729.25-7729.25; 15:30:36 RailHeld Demand 7729.25-7729.25 | - | responsive_terminal_candidate |
| ES | 15:26:00-15:26:00 | zero_gamma | lower | 7730.22 | 7730.5-7732 | 1% | 124 | 14.28/1.22 | 15:25:13 RailTested Demand 7729.25-7729.25; 15:26:24 RailHeld Demand 7729.25-7729.25; 15:27:17 RailTested Demand 7729.25-7729.25; 15:30:36 RailHeld Demand 7729.25-7729.25 | - | responsive_terminal_candidate |
| ES | 15:27:00-15:27:00 | zero_gamma | lower | 7728.92 | 7729-7731.5 | 22% | -94 | 15.58/-0.08 | 15:25:13 RailTested Demand 7729.25-7729.25; 15:26:24 RailHeld Demand 7729.25-7729.25; 15:27:17 RailTested Demand 7729.25-7729.25; 15:30:36 RailHeld Demand 7729.25-7729.25 | - | responsive_terminal_candidate |
| NQ | 09:56:00-09:56:00 | put_wall | lower | 29494.88 | 29463.75-29522 | 92% | -231 | 106.62/71.13 | - | 10:01:16 AllowProbe trap_probe/counter_claim_failed_at_trap_probe | campaign_relevant_touch |
| NQ | 09:56:00-09:56:00 | zero_gamma | upper | 29509.88 | 29463.75-29522 | 92% | -231 | 86.13/91.62 | 09:56:44 RailOwned Supply 29508-29509; 10:00:55 RailTested Supply 29508-29509; 10:00:59 RailHeld Supply 29508-29509; 10:01:13 RailTested Supply 29508-29509 | 10:01:16 AllowProbe trap_probe/counter_claim_failed_at_trap_probe | campaign_relevant_touch |
| NQ | 10:11:00-10:25:00 | oi_call_wall | upper | 29575.31 | 29554.25-29601.5 | 79% | -191 | 43.31/48.19 | 10:12:51 RailOwned Demand 29565.25-29566; 10:12:53 RailTested Demand 29565.25-29566; 10:12:56 RailHeld Demand 29565.25-29566; 10:13:17 RailTested Demand 29565.25-29566 | 10:14:41 Flatten build_trial/risk_anchor_failed | campaign_relevant_touch |
| NQ | 10:48:00-10:58:00 | oi_call_wall | upper | 29572.12 | 29541.75-29605.25 | 79% | 459 | -9.63/62.88 | 10:55:42 RailOwned Supply 29574-29578.75; 10:57:05 RailTested Supply 29574-29578.75; 10:57:06 RailHeld Supply 29574-29578.75; 10:57:13 RailTested Supply 29574-29578.75 | 10:57:18 AllowProbe trap_probe/counter_claim_failed_at_trap_probe; 11:03:42 Reduce evaluate_zone/evaluate_opposite_ownership | campaign_relevant_touch |
| NQ | 11:29:00-11:36:00 | oi_call_wall | upper | 29574.2 | 29562.25-29592.5 | 58% | -2 | 62.7/49.55 | 11:27:59 RailTested Demand 29583.5-29584.25; 11:28:10 RailHeld Demand 29583.5-29584.25; 11:28:20 RailTested Demand 29583.5-29584.25; 11:28:39 RailHeld Demand 29583.5-29584.25 | 11:29:34 Flatten build_trial/risk_anchor_failed | campaign_relevant_touch |
| NQ | 09:30:00-09:30:00 | oi_call_wall | upper | 29578.81 | 29502.25-29586.25 | 1% | 229 | 155.06/26.19 | - | - | responsive_terminal_candidate |
| NQ | 09:31:00-09:31:00 | call_wall | upper | 29568.81 | 29480.75-29588.75 | 99% | -47 | 145.06/36.19 | 09:30:42 RailTested Supply 29560-29560.5; 09:30:44 RailHeld Supply 29560-29560.5; 09:30:46 RailFailed Supply 29560-29560.5 | - | responsive_terminal_candidate |
| NQ | 09:31:00-09:31:00 | oi_call_wall | upper | 29568.97 | 29480.75-29588.75 | 99% | -47 | 145.22/36.03 | 09:30:42 RailTested Supply 29560-29560.5; 09:30:44 RailHeld Supply 29560-29560.5; 09:30:46 RailFailed Supply 29560-29560.5 | - | responsive_terminal_candidate |
| NQ | 09:38:00-09:38:00 | zero_gamma | lower | 29448.81 | 29449.75-29478.75 | 91% | -52 | 156.19/25.06 | 09:37:17 RailTested Demand 29450.75-29452.5; 09:37:23 RailHeld Demand 29450.75-29452.5; 09:37:24 RailTested Demand 29450.75-29452.5; 09:37:26 RailHeld Demand 29450.75-29452.5 | - | responsive_terminal_candidate |
| NQ | 09:44:00-09:46:00 | oi_call_wall | upper | 29574.88 | 29534.5-29605 | 98% | 499 | 151.13/13.62 | 09:45:55 RailOwned Demand 29574.5-29575.5; 09:46:51 RailFailed Demand 29574.5-29575.5 | - | responsive_terminal_candidate |
| NQ | 09:45:00-09:46:00 | call_wall | upper | 29594.88 | 29553.25-29605 | 98% | -194 | 171.13/-6.38 | 09:46:49 RailOwned Supply 29595.25-29597.75; 09:46:50 RailOwned Supply 29587.5-29592.75 | - | responsive_terminal_candidate |
| NQ | 09:57:00-09:57:00 | zero_gamma | lower | 29425.05 | 29423.75-29466 | 99% | -225 | 198.45/-8.45 | - | 10:01:16 AllowProbe trap_probe/counter_claim_failed_at_trap_probe | responsive_terminal_candidate |
| NQ | 09:59:00-09:59:00 | zero_gamma | lower | 29460.78 | 29459-29488.75 | 91% | 22 | 162.72/-17.72 | 09:57:08 RailTested Demand 29450.75-29452.5; 09:57:12 RailHeld Demand 29450.75-29452.5; 09:57:18 RailFailed Demand 29450.75-29452.5; 09:57:42 RailOwned Supply 29461.5-29462.75 | 10:01:16 AllowProbe trap_probe/counter_claim_failed_at_trap_probe | responsive_terminal_candidate |
| NQ | 10:18:00-10:37:00 | call_wall | upper | 29594.37 | 29563.5-29623.5 | 73% | 6 | 63.31/30.44 | 10:16:07 RailHeld Supply 29587.5-29592.75; 10:16:12 RailTested Supply 29587.5-29592.75; 10:16:14 RailHeld Supply 29587.5-29592.75; 10:18:00 RailTested Supply 29587.5-29592.75 | - | responsive_terminal_candidate |
| NQ | 11:00:00-11:04:00 | call_wall | upper | 29613.03 | 29588.25-29615.5 | 65% | 1 | 48.53/21.97 | 11:01:22 RailTested Supply 29608.5-29609.25; 11:01:24 RailHeld Supply 29608.5-29609.25; 11:01:35 RailTested Supply 29608.5-29609.25; 11:01:36 RailHeld Supply 29608.5-29609.25 | 11:03:42 Reduce evaluate_zone/evaluate_opposite_ownership | responsive_terminal_candidate |
| NQ | 11:38:00-11:38:00 | zero_gamma | lower | 29552.53 | 29551-29562.25 | 48% | 15 | 71.22/41.03 | 11:41:11 RailOwned Demand 29552.25-29554.75; 11:42:35 RailTested Demand 29552.25-29554.75; 11:42:39 RailHeld Demand 29552.25-29554.75 | - | responsive_terminal_candidate |
| NQ | 11:39:00-11:39:00 | zero_gamma | lower | 29547.39 | 29547.75-29559 | 48% | -2 | 76.36/35.89 | 11:41:11 RailOwned Demand 29552.25-29554.75; 11:42:35 RailTested Demand 29552.25-29554.75; 11:42:39 RailHeld Demand 29552.25-29554.75 | - | responsive_terminal_candidate |
| NQ | 11:43:00-11:45:00 | zero_gamma | lower | 29531.94 | 29515-29557.75 | 85% | -339 | 91.17/21.08 | - | - | responsive_terminal_candidate |
| NQ | 11:51:00-11:51:00 | zero_gamma | lower | 29543.47 | 29546.25-29572.25 | 79% | 69 | 80.28/-20.28 | - | - | responsive_terminal_candidate |
| NQ | 11:54:00-11:55:00 | call_wall | upper | 29613.56 | 29586.75-29610 | 83% | 55 | 43.56/10.19 | - | - | responsive_terminal_candidate |

## Add Candidate Classes

| Symbol | ET | Side | Class | Logged | Price | 30m MFE/MAE | Nearest GEX | Dist |
|---|---:|---|---|---|---:|---:|---|---:|
| ES | 10:23:18 | Long | possible_wall_conversion_add | no_add_zone/inside_no_add_zone | 7725.25 | 10.75/3.5 | oi_put_wall | -2.87 |
| ES | 10:35:36 | Long | possible_wall_conversion_add | no_add_zone/inside_no_add_zone | 7727.5 | 11/3 | oi_put_wall | -0.54 |
| ES | 13:44:34 | Short | high_quality_missed_add | build_trial/build_trial_alive | 7749.5 | 18.75/0.25 | call_wall | -4.44 |
| ES | 13:44:39 | Short | high_quality_missed_add | build_trial/build_trial_alive | 7748.25 | 17.5/0.5 | call_wall | -5.69 |
| ES | 13:44:57 | Short | high_quality_missed_add | build_trial/build_trial_alive | 7747.75 | 17/0.5 | call_wall | -6.19 |
| ES | 14:01:28 | Short | high_quality_missed_add | build_trial/build_trial_alive | 7741.5 | 17.75/0.25 | zero_gamma | 7.14 |
| ES | 14:14:12 | Short | near_destination_or_wall_keep_suppressed | no_add_zone/inside_no_add_zone | 7731.5 | 7.75/4.75 | oi_put_wall | 2.97 |
| ES | 14:24:04 | Short | near_destination_or_wall_keep_suppressed | no_add_zone/inside_no_add_zone | 7731.75 | 8/1 | oi_put_wall | 3.8 |
| ES | 14:25:25 | Short | near_destination_or_wall_keep_suppressed | no_add_zone/inside_no_add_zone | 7731.25 | 8.5/1.25 | oi_put_wall | 3.3 |
| NQ | 10:12:51 | Long | too_volatile_for_normal_add | build_trial/build_trial_alive | 29569 | 54.5/26.75 | oi_call_wall | -4.62 |
| NQ | 10:12:51 | Long | too_volatile_for_normal_add | build_trial/build_trial_alive | 29569 | 54.5/26.75 | oi_call_wall | -4.62 |
| NQ | 10:12:56 | Long | too_volatile_for_normal_add | build_trial/build_trial_alive | 29568.5 | 55/26.25 | oi_call_wall | -5.12 |
| NQ | 10:13:49 | Long | too_volatile_for_normal_add | build_trial/build_trial_alive | 29581.5 | 42/40.5 | oi_call_wall | 7.88 |
| NQ | 10:13:58 | Long | too_volatile_for_normal_add | build_trial/build_trial_alive | 29583.75 | 39.75/43.75 | call_wall | -9.87 |
| NQ | 11:26:30 | Long | too_volatile_for_normal_add | no_add_zone/inside_no_add_zone | 29589.75 | 20.25/78.25 | oi_call_wall | 15.19 |

## Root Probe Entry Mechanics

| Symbol | ET | Side | Outcome | Fill | Actual | 30m MFE/MAE | GEX Nearest | Dist | Limit 1t/2t |
|---|---:|---|---|---:|---:|---:|---|---:|---|
| ES | 09:54:03 | Long | losing_probe | 7724 | -6 | 3.5/16.75 | oi_put_wall | -4.81 | 0.075/3.057 |
| NQ | 10:01:16 | Long | losing_probe | 29515.75 | -7.25 | 107.75/16.75 | zero_gamma | 54.53 | 0.017/0.189 |
| ES | 10:01:25 | Long | losing_probe | 7717.75 | -4.75 | 12.5/5.75 | zero_gamma | 5.45 | 0.008/0.008 |
| NQ | 10:07:08 | Long | winning_probe | 29518.5 | 50.75 | 105/10.25 | oi_call_wall | -55.12 | 0.075/0.075 |
| ES | 10:07:53 | Long | open_or_manual | 7718 | - | 14.25/4.5 | zero_gamma | 5.01 | 0.262/0.289 |
| NQ | 10:57:18 | Long | winning_probe | 29585.25 | 8.5 | 49.75/10.25 | oi_call_wall | 13.13 | 0.002/0.002 |
| NQ | 11:25:59 | Long | losing_probe | 29590.75 | -13.75 | 19.25/79.25 | oi_call_wall | 16.19 | 0.445/0.574 |
| ES | 13:39:03 | Short | winning_probe | 7748.75 | 19.5 | 13/2.5 | call_wall | -5.19 | 0.103/14.783 |

## Output Files

- `research\kahn\out\2026-08-27-gex-kahn\gex_wall_touch_clusters.csv`
- `research\kahn\out\2026-08-27-gex-kahn\gex_wall_touch_notable.csv`
- `research\kahn\out\2026-08-27-gex-kahn\add_candidate_classes.csv`
- `research\kahn\out\2026-08-27-gex-kahn\probe_entry_classes.csv`
