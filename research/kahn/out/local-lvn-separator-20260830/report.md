# Local LVN Separator Probe

Codex-authored research artifact. This is not accepted Kahn policy.

Hypothesis: add mode is safer when a point-in-time low-volume separator forms between root A and the later add/reclaim event. The separator is measured from root-entry ticks only; the RTH profile comparison is an ex-post check for whether the node was local rather than a visible day profile level.

Separator calls:

- `local_lvn_separator`: local volume is <= 35 percent of nearby/median corridor volume, while the same bin is not a strong RTH LVN.
- `day_visible_lvn_separator`: locally poor volume, but also visible in the broader RTH profile.
- `weak_local_separator`: local separator is present but not strong.
- `no_lvn_separator`: corridor exists, but no local separator is visible.

## Cases

- `es_20260827_1130_long_7728`: long from 11:40:17 ref 7728.0, target floor 7743.0, MFE 21.75, MAE 2.75, target 12:34:28.
- `es_20260827_1330_short_7748`: short from 13:39:03 ref 7748.75, target floor 7729.5, MFE 25.0, MAE 2.5, target 14:26:35.
- `es_20260828_1120_short_7780`: short from 11:20:00 ref 7780.0, target floor 7740.0, MFE 60.0, MAE 1.5, target 11:56:40.

## Candidate Separators

### es_20260827_1130_long_7728

| probe | time | root sep | event gap sep | event | sep | gap sep | root-event | path% | scale call |
| --- | --- | --- | --- | --- | --- | --- | ---: | ---: | --- |
| tail_reclaim | 11:51:54 | weak_local_separator | ranges_overlap | 725.25-732 | 7733.5-7734.0 | - | 7.0 | 46.7 | tail_reclaim_reject_depleted |
| tail_reclaim | 11:52:57 | weak_local_separator | ranges_overlap | 726.50-734.75 | 7736.0-7736.5 | - | 9.25 | 61.7 | tail_reclaim_harvest_not_add |
| tail_reclaim | 11:53:03 | weak_local_separator | ranges_overlap | 725.25-734.50 | 7736.0-7736.5 | - | 9.5 | 63.3 | tail_reclaim_harvest_not_add |
| tail_reclaim | 11:53:03 | weak_local_separator | ranges_overlap | 732-734.50 | 7736.0-7736.5 | - | 9.5 | 63.3 | tail_reclaim_harvest_not_add |
| sponsor_stack | 11:47:42 | no_corridor |  | 723.50-725.75 | - | - | 0.25 | 1.7 | sponsor_stack_add |
| sponsor_stack | 11:49:50 | no_corridor |  | 723.50-725.75 | - | - | 0.25 | 1.7 | stack_watch_retest_only |

### es_20260827_1330_short_7748

| probe | time | root sep | event gap sep | event | sep | gap sep | root-event | path% | scale call |
| --- | --- | --- | --- | --- | --- | --- | ---: | ---: | --- |
| tail_reclaim | 14:10:55 | local_lvn_separator | weak_local_separator | 736.75-739.75 | 7740.5-7741.0 | 7740.5-7741.0 | 14.5 | 75.3 | tail_reclaim_harvest_not_add |
| tail_reclaim | 14:12:34 | local_lvn_separator | weak_local_separator | 736.75-739.75 | 7740.5-7741.0 | 7740.5-7741.0 | 14.5 | 75.3 | tail_reclaim_harvest_not_add |
| tail_reclaim | 14:12:45 | local_lvn_separator | weak_local_separator | 736.25-739.25 | 7740.5-7741.0 | 7740.5-7741.0 | 15.0 | 77.9 | tail_reclaim_harvest_not_add |
| tail_reclaim | 14:12:45 | local_lvn_separator | weak_local_separator | 736.25-737.25 | 7740.5-7741.0 | 7740.5-7741.0 | 15.0 | 77.9 | tail_reclaim_harvest_not_add |
| tail_reclaim | 14:01:13 | weak_local_separator | weak_local_separator | 745-747.25 | 7747.5-7748.0 | 7743.0-7743.5 | 6.25 | 32.5 | tail_reclaim_add |
| tail_reclaim | 14:01:29 | weak_local_separator | no_corridor | 743.50-745.25 | 7742.5-7743.0 | - | 7.25 | 37.7 | tail_reclaim_reject_depleted |
| tail_reclaim | 14:01:29 | weak_local_separator | no_lvn_separator | 743.75-745.25 | 7742.5-7743.0 | 7743.0-7743.5 | 7.25 | 37.7 | tail_reclaim_reject_depleted |
| sponsor_stack | 13:58:28 | weak_local_separator |  | 745-747.25 | 7747.5-7748.0 | - | 5.75 | 29.9 | stack_watch_no_renewal |
| sponsor_stack | 13:44:39 | no_corridor |  | 751.25-753 | - | - | 0.25 | 1.3 | sponsor_stack_add |

### es_20260828_1120_short_7780

| probe | time | root sep | event gap sep | event | sep | gap sep | root-event | path% | scale call |
| --- | --- | --- | --- | --- | --- | --- | ---: | ---: | --- |
| tail_reclaim | 11:40:17 | local_lvn_separator | ranges_overlap | 767.25-772.50 | 7771.0-7771.5 | - | 16.0 | 40.0 | tail_reclaim_reject_depleted |
| tail_reclaim | 11:40:49 | local_lvn_separator | ranges_overlap | 763.75-768.75 | 7763.5-7764.0 | - | 20.0 | 50.0 | tail_reclaim_reject_depleted |
| tail_reclaim | 11:40:59 | local_lvn_separator | local_lvn_separator | 762.25-762.75 | 7763.5-7764.0 | 7763.5-7764.0 | 21.75 | 54.4 | tail_reclaim_add_reduced |
| tail_reclaim | 11:42:33 | local_lvn_separator | local_lvn_separator | 762.25-762.75 | 7763.5-7764.0 | 7763.5-7764.0 | 20.5 | 51.2 | tail_reclaim_add_reduced |
| tail_reclaim | 11:44:00 | local_lvn_separator | local_lvn_separator | 762.25-762.75 | 7763.5-7764.0 | 7763.5-7764.0 | 20.25 | 50.6 | tail_reclaim_reject_depleted |
| tail_reclaim | 11:44:39 | local_lvn_separator | local_lvn_separator | 760.25-761.75 | 7763.5-7764.0 | 7763.5-7764.0 | 22.0 | 55.0 | tail_reclaim_reject_depleted |
| tail_reclaim | 11:45:23 | local_lvn_separator | local_lvn_separator | 760.25-761.75 | 7763.5-7764.0 | 7763.5-7764.0 | 22.25 | 55.6 | tail_reclaim_add_reduced |
| tail_reclaim | 11:48:05 | local_lvn_separator | local_lvn_separator | 756.75-758.50 | 7763.5-7764.0 | 7763.5-7764.0 | 26.0 | 65.0 | tail_reclaim_mature_path_harvest |
| tail_reclaim | 11:48:33 | local_lvn_separator | local_lvn_separator | 754.50-758.50 | 7763.5-7764.0 | 7763.5-7764.0 | 28.5 | 71.2 | tail_reclaim_mature_path_harvest |
| tail_reclaim | 11:49:02 | local_lvn_separator | local_lvn_separator | 754.50-758.50 | 7763.5-7764.0 | 7763.5-7764.0 | 28.5 | 71.2 | tail_reclaim_mature_path_harvest |
| sponsor_stack | 11:40:59 | local_lvn_separator |  | 762.25-762.75 | 7763.5-7764.0 | - | 21.75 | 54.4 | sponsor_stack_add_reduced |
| sponsor_stack | 11:42:33 | local_lvn_separator |  | 762.25-762.75 | 7763.5-7764.0 | - | 20.5 | 51.2 | sponsor_stack_add_reduced |
| sponsor_stack | 11:45:23 | local_lvn_separator |  | 760.25-761.75 | 7763.5-7764.0 | - | 22.25 | 55.6 | stack_watch_retest_only |
| tail_reclaim | 11:36:56 | weak_local_separator | no_lvn_separator | 775.75-781.75 | 7775.5-7776.0 | 7775.5-7776.0 | 6.75 | 16.9 | tail_reclaim_reject_depleted |
| tail_reclaim | 11:37:23 | weak_local_separator | weak_local_separator | 774.75-778 | 7775.5-7776.0 | 7772.5-7773.0 | 8.0 | 20.0 | tail_reclaim_reject_depleted |
| sponsor_stack | 11:23:44 | weak_local_separator |  | 778.25-781.75 | 7778.0-7778.5 | - | 4.25 | 10.6 | stack_watch_retest_only |

## Call Counts

### es_20260827_1130_long_7728
- `no_corridor`: 2
- `weak_local_separator`: 4

### es_20260827_1330_short_7748
- `local_lvn_separator`: 4
- `no_corridor`: 1
- `weak_local_separator`: 4

### es_20260828_1120_short_7780
- `local_lvn_separator`: 13
- `no_lvn_separator`: 6
- `weak_local_separator`: 3

## Policy Read

A local LVN should not authorize an add by itself. It is useful as an `AddModeEligible` context bit: root remains the risk anchor, the candidate must still pass stack/reclaim/reload gates, and the LVN acts as a poor-volume separator/falsifier between A and the new participation area.