# Tail Reclaim Sequence Probe

Codex-authored research artifact. This is not accepted Kahn policy.

Hypothesis: a root-preserving add may be justified after A-B-C-D extension, C/D repair failure, opposing ZZ claim, ZZ invalidation, and same-side reclaim back through the prior tail. This is stricter than adding during the first favorable extension.

## Cases

- `es_20260827_1130_long_7728`: long from 11:40:17 ref 7728.0, target floor 7743.0, MFE 21.75, MAE 2.75, target 12:34:28.
- `es_20260827_1330_short_7748`: short from 13:39:03 ref 7748.75, target floor 7729.5, MFE 25.0, MAE 2.5, target 14:26:35.
- `es_20260828_1120_short_7780`: short from 11:20:00 ref 7780.0, target floor 7740.0, MFE 60.0, MAE 1.5, target 11:56:40.

## Sequence Rows

### es_20260827_1130_long_7728

| time | action | range | ZZ | fail | prior D | break | stack | replen | runway | path% | future MFE/MAE | call |
| --- | --- | --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| 11:51:54 | OWNED | 725.25-732 | 11:44:08 7730.5-7736.25 | implicit_zz_fail_by_reclaim 11:51:54 | 11:41:37 7733.75 | 11:51:54 | 10/4/6 | 0.747 | 8.0 | 46.7 | 14.75/2.25 | tail_reclaim_reject_depleted |
| 11:52:57 | HOLD | 726.50-734.75 | 11:44:08 7730.5-7736.25 | implicit_zz_fail_by_reclaim 11:51:54 | 11:41:37 7733.75 | 11:52:57 | 10/5/5 | 0.584 | 5.75 | 61.7 | 12.5/2.25 | tail_reclaim_harvest_not_add |
| 11:53:03 | CONSUMED | 725.25-734.50 | 11:44:08 7730.5-7736.25 | implicit_zz_fail_by_reclaim 11:51:54 | 11:41:37 7733.75 | 11:53:03 | 11/6/5 | 0.62 | 5.5 | 63.3 | 12.25/2.5 | tail_reclaim_harvest_not_add |
| 11:53:03 | CONSUMED | 732-734.50 | 11:44:08 7730.5-7736.25 | implicit_zz_fail_by_reclaim 11:51:54 | 11:41:37 7733.75 | 11:53:03 | 12/7/5 | 0.914 | 5.5 | 63.3 | 12.25/2.5 | tail_reclaim_harvest_not_add |

### es_20260827_1330_short_7748

| time | action | range | ZZ | fail | prior D | break | stack | replen | runway | path% | future MFE/MAE | call |
| --- | --- | --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| 14:01:13 | HOLD | 745-747.25 | 14:00:09 7741-7742.75 | implicit_zz_fail_by_reclaim 14:01:13 | 13:58:28 7743.0 | 14:01:13 | 1/0/1 | 1.101 | 13.0 | 32.5 | 18.75/0.25 | tail_reclaim_add |
| 14:01:29 | CONSUMED | 743.50-745.25 | 14:00:09 7741-7742.75 | implicit_zz_fail_by_reclaim 14:01:13 | 13:58:28 7743.0 | 14:01:29 | 2/1/1 | 0.844 | 12.0 | 37.7 | 17.75/0.25 | tail_reclaim_reject_depleted |
| 14:01:29 | OWNED | 743.75-745.25 | 14:00:09 7741-7742.75 | implicit_zz_fail_by_reclaim 14:01:13 | 13:58:28 7743.0 | 14:01:29 | 3/1/2 | 0.813 | 12.0 | 37.7 | 17.75/0.25 | tail_reclaim_reject_depleted |
| 14:10:55 | OWNED | 736.75-739.75 | 14:00:09 7741-7742.75 | implicit_zz_fail_by_reclaim 14:01:13 | 13:58:28 7743.0 | 14:10:55 | 4/1/3 | 1.143 | 4.75 | 75.3 | 10.5/2.0 | tail_reclaim_harvest_not_add |
| 14:12:34 | HOLD | 736.75-739.75 | 14:00:09 7741-7742.75 | implicit_zz_fail_by_reclaim 14:01:13 | 13:58:28 7743.0 | 14:12:34 | 4/1/3 | 1.261 | 4.75 | 75.3 | 10.5/2.0 | tail_reclaim_harvest_not_add |
| 14:12:45 | CONSUMED | 736.25-739.25 | 14:00:09 7741-7742.75 | implicit_zz_fail_by_reclaim 14:01:13 | 13:58:28 7743.0 | 14:12:45 | 5/2/3 | 1.041 | 4.25 | 77.9 | 10.0/2.5 | tail_reclaim_harvest_not_add |
| 14:12:45 | CONSUMED | 736.25-737.25 | 14:00:09 7741-7742.75 | implicit_zz_fail_by_reclaim 14:01:13 | 13:58:28 7743.0 | 14:12:45 | 6/3/3 | 1.085 | 4.25 | 77.9 | 10.0/2.5 | tail_reclaim_harvest_not_add |

### es_20260828_1120_short_7780

| time | action | range | ZZ | fail | prior D | break | stack | replen | runway | path% | future MFE/MAE | call |
| --- | --- | --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| 11:36:16 | HOLD | 775.75-781.75 | 11:23:14 7769-7774.5 | formal_zz_fail 11:35:03 | 11:21:38 7772.5 | 11:37:20 | 4/2/2 | 1.06 | 33.0 | 17.5 | 53.0/2.25 | tail_reclaim_add |
| 11:40:59 | CONSUMED | 762.25-762.75 | 11:35:15 7766.75-7772.5 | formal_zz_fail 11:37:21 | 11:21:38 7772.5 | 11:40:59 | 3/2/1 | 1.115 | 18.25 | 54.4 | 38.25/3.75 | tail_reclaim_add_reduced |
| 11:42:33 | HOLD | 762.25-762.75 | 11:35:15 7766.75-7772.5 | formal_zz_fail 11:37:21 | 11:21:38 7772.5 | 11:42:33 | 3/2/1 | 1.123 | 19.5 | 51.2 | 39.5/2.25 | tail_reclaim_add_reduced |
| 11:45:23 | HOLD | 760.25-761.75 | 11:35:15 7766.75-7772.5 | formal_zz_fail 11:37:21 | 11:21:38 7772.5 | 11:45:23 | 4/2/2 | 1.041 | 17.75 | 55.6 | 37.75/1.25 | tail_reclaim_add_reduced |
| 11:36:56 | HOLD | 775.75-781.75 | 11:23:14 7769-7774.5 | formal_zz_fail 11:35:03 | 11:21:38 7772.5 | 11:37:20 | 4/2/2 | 0.904 | 33.25 | 16.9 | 53.25/0.5 | tail_reclaim_reject_depleted |
| 11:37:23 | OWNED | 774.75-778 | 11:35:15 7766.75-7772.5 | formal_zz_fail 11:37:21 | 11:21:38 7772.5 | 11:37:23 | 5/2/3 | 0.779 | 32.0 | 20.0 | 52.0/1.25 | tail_reclaim_reject_depleted |
| 11:40:17 | CONSUMED | 767.25-772.50 | 11:35:15 7766.75-7772.5 | formal_zz_fail 11:37:21 | 11:21:38 7772.5 | 11:40:17 | 3/2/1 | 0.314 | 24.0 | 40.0 | 44.0/0.75 | tail_reclaim_reject_depleted |
| 11:40:49 | OWNED | 763.75-768.75 | 11:35:15 7766.75-7772.5 | formal_zz_fail 11:37:21 | 11:21:38 7772.5 | 11:40:49 | 2/1/1 | 0.564 | 20.0 | 50.0 | 40.0/2.0 | tail_reclaim_reject_depleted |
| 11:44:00 | HOLD | 762.25-762.75 | 11:35:15 7766.75-7772.5 | formal_zz_fail 11:37:21 | 11:21:38 7772.5 | 11:44:00 | 3/2/1 | 0.959 | 19.75 | 50.6 | 39.75/0.75 | tail_reclaim_reject_depleted |
| 11:44:39 | OWNED | 760.25-761.75 | 11:35:15 7766.75-7772.5 | formal_zz_fail 11:37:21 | 11:21:38 7772.5 | 11:44:39 | 4/2/2 | 0.846 | 18.0 | 55.0 | 38.0/1.5 | tail_reclaim_reject_depleted |
| 11:48:05 | CONSUMED | 756.75-758.50 | 11:35:15 7766.75-7772.5 | formal_zz_fail 11:37:21 | 11:21:38 7772.5 | 11:48:05 | 4/2/2 | 1.374 | 14.0 | 65.0 | 34.0/0.75 | tail_reclaim_mature_path_harvest |
| 11:48:33 | OWNED | 754.50-758.50 | 11:35:15 7766.75-7772.5 | formal_zz_fail 11:37:21 | 11:21:38 7772.5 | 11:48:33 | 4/2/2 | 1.209 | 11.5 | 71.2 | 31.5/2.5 | tail_reclaim_mature_path_harvest |
| 11:49:02 | HOLD | 754.50-758.50 | 11:35:15 7766.75-7772.5 | formal_zz_fail 11:37:21 | 11:21:38 7772.5 | 11:49:02 | 4/2/2 | 1.188 | 11.5 | 71.2 | 31.5/2.5 | tail_reclaim_mature_path_harvest |

## Call Counts

### es_20260827_1130_long_7728
- `tail_reclaim_harvest_not_add`: 3
- `tail_reclaim_reject_depleted`: 1

### es_20260827_1330_short_7748
- `tail_reclaim_add`: 1
- `tail_reclaim_harvest_not_add`: 4
- `tail_reclaim_reject_depleted`: 2

### es_20260828_1120_short_7780
- `tail_reclaim_add`: 1
- `tail_reclaim_add_reduced`: 3
- `tail_reclaim_mature_path_harvest`: 3
- `tail_reclaim_reject_depleted`: 6

## Policy Read

This sequence is a candidate for a higher-priority add path than HoldRoot because it waits for a failed repair cycle instead of scaling the first impulse. The live trigger should probably be two stage: mark `ReclaimWatch` when ZZ is invalidated and same-side C reloads, then allow `TailReclaimAdd` only as price accepts through the prior D/tail with root risk still preserved. Near target, the same sequence should strengthen hold/harvest rather than add.