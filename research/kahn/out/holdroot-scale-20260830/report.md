# HoldRoot Scale Management Probe

Codex-authored research artifact. This is not accepted Kahn policy.

Objective: find where Kahn could scale up while preserving the root risk anchor, then note where passive scale-out should start or accelerate.

Scale-up call grammar:

- `add_preserve_root`: same-side LL ownership/hold, replenished contact, target runway, and recent opposing rail failure or depleted opposing contact.
- `add_preserve_root_reduced`: same condition, but enough target path is consumed that size should be smaller or capped.
- `add_review_no_recent_opp_fail`: same-side owned/consumed rail and replenished contact, but no recent opposing failure.
- `watch_contact`: TEST/contact quality only; not direct Kahn add evidence.
- `reject_depleted`: same-side contact was being consumed/pulled faster than it replenished.
- `scale_out_zone`: target proximity says harvest, not press.
- `mature_path_hold_only`: rail quality is constructive but too much of the planned path has already paid.

Timestamp note: MarketRecorder live storage carries both receipt and exchange timestamps. This script aligns book events to trades on `exchange_timestamp_us`; receipt time is treated as a capture-arrival diagnostic only.

## Cases

- `es_20260827_1130_long_7728`: long from 11:40:17 ref 7728.0, target floor 7743.0, MFE 21.75, MAE 2.75, target 12:34:28.
- `es_20260827_1330_short_7748`: short from 13:39:03 ref 7748.75, target floor 7729.5, MFE 25.0, MAE 2.5, target 14:26:35.
- `es_20260828_1120_short_7780`: short from 11:20:00 ref 7780.0, target floor 7740.0, MFE 60.0, MAE 1.5, target 11:56:40.

## Timestamp Sanity

- `es_20260827_1130_long_7728`: rows=436639, receipt-exchange median=-151.2ms, p05=-181.8ms, p95=-77.5ms.
- `es_20260827_1330_short_7748`: rows=714106, receipt-exchange median=-281.0ms, p05=-318.5ms, p95=-207.8ms.
- `es_20260828_1120_short_7780`: rows=1508012, receipt-exchange median=-928.5ms, p05=-1008.0ms, p95=-3.8ms.

## Kahn Decisions In Actual 8/27 Windows

- `es_20260827_1330_short_7748` 13:39:03 AllowProbe 0->2 trap_probe/same_side_lean_at_trap_probe price=7748.75 phase=Ready->ProbeOpen.
- `es_20260827_1330_short_7748` 14:31:48 Retire 2->0 target_zone/opposite_ownership_at_target price=7729.0 phase=BuildTrial->Retired.

## Scale-Up Candidates

### es_20260827_1130_long_7728

| time | action | band | range | replen | paid | oppFail/weak | runway | path% | future MFE/MAE | target | call |
| --- | --- | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |
| 11:47:02 | HOLD | 10 | 719-725 | 1.608 | 0.0 | 0/0 | 15.5 | 0.0 | 22.25/1.25 | 12:34:28 | add_review |
| 11:49:50 | HOLD | 11 | 723.50-725.75 | 1.102 | 0.0 | 0/0 | 14.75 | 1.7 | 21.5/0.5 | 12:34:28 | add_review |
| 11:47:42 | HOLD | 11 | 723.50-725.75 | 1.06 | 0.239 | 0/0 | 14.75 | 1.7 | 21.5/2.0 | 12:34:28 | add_review |
| 11:40:17 | HOLD | 19 | 727.50-728.50 | 1.8 | 0.0 | 0/0 | 12.0 | 20.0 | 18.75/5.75 | 12:34:28 | add_review |
| 11:45:27 | TEST | 10 | 719-725 | 1.608 | 0.0 | 0/0 | 17.0 | 0.0 | 23.75/0.75 | 12:34:28 | watch_contact |
| 11:48:30 | TEST | 11 | 723.50-725.75 | 1.102 | 0.0 | 0/0 | 16.5 | 0.0 | 23.25/0.25 | 12:34:28 | watch_contact |
| 11:45:04 | TEST | 11 | 723.50-725.75 | 1.06 | 0.239 | 0/0 | 16.5 | 0.0 | 23.25/1.25 | 12:34:28 | watch_contact |
| 11:44:03 | TEST | 16 | 724.50-727 | 1.309 | 0.0 | 0/1 | 15.5 | 0.0 | 22.25/2.25 | 12:34:28 | watch_contact |
| 11:44:03 | TEST | 21 | 725-727.50 | 1.013 | 0.134 | 0/1 | 15.5 | 0.0 | 22.25/2.25 | 12:34:28 | watch_contact |
| 11:44:02 | TEST | 23 | 725.75-727.75 | 0.997 | 0.152 | 0/1 | 14.25 | 5.0 | 21.0/3.5 | 12:34:28 | watch_contact |
| 11:43:22 | TEST | 20 | 726.25-728 | 1.002 | 0.18 | 0/1 | 14.0 | 6.7 | 20.75/3.75 | 12:34:28 | watch_contact |
| 11:43:20 | TEST | 19 | 727.50-728.50 | 0.956 | 0.207 | 0/1 | 13.5 | 10.0 | 20.25/4.25 | 12:34:28 | watch_contact |

### es_20260827_1330_short_7748

| time | action | band | range | replen | paid | oppFail/weak | runway | path% | future MFE/MAE | target | call |
| --- | --- | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |
| 13:44:39 | HOLD | 25 | 751.25-753 | 1.031 | 0.04 | 0/1 | 19.0 | 1.3 | 24.75/0.25 | 14:26:35 | add_preserve_root |
| 14:01:13 | HOLD | 29 | 745-747.25 | 1.101 | 0.237 | 0/2 | 13.0 | 32.5 | 18.75/0.25 | 14:26:35 | add_preserve_root |
| 13:58:28 | OWNED | 29 | 745-747.25 | 1.091 | 0.0 | 0/0 | 13.5 | 29.9 | 19.25/2.5 | 14:26:35 | add_review_no_recent_opp_fail |
| 13:44:35 | HOLD | 22 | 752-752.75 | 1.018 | 0.0 | 0/0 | 20.0 | 0.0 | 25.75/0.25 | 14:26:35 | add_review |
| 13:43:56 | TEST | 22 | 752-752.75 | 1.018 | 0.0 | 0/0 | 21.5 | 0.0 | 27.25/0.25 | 14:26:35 | watch_contact |
| 13:43:42 | TEST | 25 | 751.25-753 | 1.031 | 0.04 | 0/0 | 20.75 | 0.0 | 26.5/1.0 | 14:26:35 | watch_contact |
| 14:00:01 | TEST | 29 | 745-747.25 | 1.101 | 0.237 | 0/0 | 14.5 | 24.7 | 20.25/1.5 | 14:26:35 | watch_contact |
| 14:11:35 | TEST | 32 | 736.75-739.75 | 1.261 | 0.0 | 3/0 | 6.25 | 67.5 | 12.0/0.5 | 14:26:35 | watch_contact |
| 14:19:00 | TEST | 32 | 736.75-739.75 | 1.103 | 0.0 | 0/0 | 6.25 | 67.5 | 12.0/0.5 | 14:26:35 | watch_contact |
| 13:39:04 | HOLD | 25 | 751.25-753 | 0.891 | 0.0 | 0/0 | 19.25 | 0.0 | 25.0/2.5 | 14:26:35 | reject_depleted |
| 13:45:24 | CONSUMED | 19 | 749.75-754.25 | 0.901 | 0.0 | 1/1 | 17.75 | 7.8 | 23.5/0.5 | 14:26:35 | reject_depleted |
| 13:45:24 | CONSUMED | 27 | 749.75-752 | 0.863 | 0.0 | 1/1 | 17.75 | 7.8 | 23.5/0.5 | 14:26:35 | reject_depleted |

### es_20260828_1120_short_7780

| time | action | band | range | replen | paid | oppFail/weak | runway | path% | future MFE/MAE | target | call |
| --- | --- | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |
| 11:34:09 | HOLD | 40 | 778.25-781.75 | 1.135 | 0.0 | 0/2 | 35.75 | 10.6 | 55.75/1.0 | 11:56:40 | add_preserve_root |
| 11:34:09 | HOLD | 48 | 778.50-779.50 | 1.198 | 0.0 | 0/2 | 35.75 | 10.6 | 55.75/1.0 | 11:56:40 | add_preserve_root |
| 11:35:03 | CONSUMED | 49 | 776.50-777.50 | 1.015 | 0.0 | 0/2 | 33.75 | 15.6 | 53.75/1.75 | 11:56:40 | add_preserve_root |
| 11:36:16 | HOLD | 39 | 775.75-781.75 | 1.06 | 0.0 | 1/2 | 33.0 | 17.5 | 53.0/2.25 | 11:56:40 | add_preserve_root |
| 11:42:33 | HOLD | 53 | 762.25-762.75 | 1.123 | 0.0 | 3/3 | 19.5 | 51.2 | 39.5/2.25 | 11:56:40 | add_preserve_root_reduced |
| 11:40:59 | CONSUMED | 53 | 762.25-762.75 | 1.115 | 0.0 | 6/4 | 18.25 | 54.4 | 38.25/3.75 | 11:56:40 | add_preserve_root_reduced |
| 11:31:32 | OWNED | 48 | 778.50-779.50 | 1.022 | 0.0 | 0/0 | 36.5 | 8.8 | 56.5/2.0 | 11:56:40 | add_review_no_recent_opp_fail |
| 11:23:44 | HOLD | 40 | 778.25-781.75 | 1.032 | 0.022 | 0/0 | 35.75 | 10.6 | 55.75/5.75 | 11:56:40 | add_review |
| 11:45:23 | HOLD | 54 | 760.25-761.75 | 1.041 | 0.0 | 0/0 | 17.75 | 55.6 | 37.75/1.25 | 11:56:40 | add_review |
| 11:32:17 | TEST | 48 | 778.50-779.50 | 1.198 | 0.0 | 0/0 | 37.5 | 6.2 | 57.5/1.0 | 11:56:40 | watch_contact |
| 11:32:09 | TEST | 40 | 778.25-781.75 | 1.135 | 0.0 | 0/0 | 37.25 | 6.9 | 57.25/1.25 | 11:56:40 | watch_contact |
| 11:23:27 | TEST | 40 | 778.25-781.75 | 1.032 | 0.022 | 0/0 | 37.25 | 6.9 | 57.25/4.25 | 11:56:40 | watch_contact |

## Scale-Out Notes

- `es_20260827_1130_long_7728` 12:34:28 target_floor_touch long 7743-7743 price=7743.0 score= -> start_or_continue_passive_harvest.
- `es_20260827_1330_short_7748` 14:26:35 target_floor_touch short 7728-7729.5 price=7729.5 score= -> start_or_continue_passive_harvest.
- `es_20260827_1330_short_7748` 14:32:23 CONSUMED demand 724.25-727 price=7729.5 score=26.921 -> increase_harvest_or_retire.
- `es_20260828_1120_short_7780` 11:56:40 target_floor_touch short 7740-7740 price=7740.0 score= -> start_or_continue_passive_harvest.
- `es_20260828_1120_short_7780` 11:57:26 HOLD demand 735.75-736.75 price=7739.25 score=11.382 -> increase_harvest_or_retire.
- `es_20260828_1120_short_7780` 11:58:26 HOLD demand 729.25-739 price=7741.5 score=38.491 -> increase_harvest_or_retire.
- `es_20260828_1120_short_7780` 12:03:29 CONSUMED demand 733.75-737.25 price=7740.5 score=33.405 -> increase_harvest_or_retire.
- `es_20260828_1120_short_7780` 12:05:56 HOLD demand 733.75-737.25 price=7740.0 score=33.405 -> increase_harvest_or_retire.

## Initial Read

The promising policy shape is not to lower HoldRoot priority. It is to admit a narrower press decision whose risk anchor is explicitly the root anchor. That keeps the campaign falsifier stable while allowing one or more controlled adds when the rail being challenged is still replenishing and the opposing side has just failed or is being depleted. Late-path versions should reduce size or stop adding.