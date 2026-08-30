# Sponsor Stack Renewal Scale Probe

Codex-authored research artifact. This is not accepted Kahn policy.

Hypothesis: HoldRoot should still suppress ordinary onside pressing, but a root-preserving add can outrank HoldRoot when the campaign has built a same-side sponsor stack and that stack renews after a challenge.

Candidate grammar:

- Root position exists, current price is onside, and the root has already earned at least 0.5 points of cushion before the event.
- Same-side stack depth is at least 2, built from direct consumption and/or same-side lean LL rails near current price.
- Current same-side event is HOLD/OWNED/CONSUMED with replenished MBO flow.
- Full add priority requires renewal stronger than a plain held retest: held retest plus failed/depleted opposition, re-establishment after same-side fail, or direct failed/depleted opposition preceding the event.
- Plain held retests become `stack_watch_retest_only`.
- Target runway remains open; late-path adds reduce or stop.
- Any live implementation must preserve the root risk anchor on add.

## Cases

- `es_20260827_1130_long_7728`: long from 11:40:17 ref 7728.0, target floor 7743.0, MFE 21.75, MAE 2.75, target 12:34:28.
- `es_20260827_1330_short_7748`: short from 13:39:03 ref 7748.75, target floor 7729.5, MFE 25.0, MAE 2.5, target 14:26:35.
- `es_20260828_1120_short_7780`: short from 11:20:00 ref 7780.0, target floor 7740.0, MFE 60.0, MAE 1.5, target 11:56:40.

## Candidate Rows

### es_20260827_1130_long_7728

| time | action | band | family | range | renewal | stack d/l | rootC | replen | runway | path% | future MFE/MAE | call |
| --- | --- | ---: | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 11:47:42 | HOLD | 11 | direct_consumption | 723.50-725.75 | reestablished_after_same_side_fail | 9/5/4 | 7.0 | 1.06 | 14.75 | 1.7 | 21.5/2.0 | sponsor_stack_add |
| 11:49:50 | HOLD | 11 | direct_consumption | 723.50-725.75 | held_after_test | 8/4/4 | 7.0 | 1.102 | 14.75 | 1.7 | 21.5/0.5 | stack_watch_retest_only |
| 11:40:17 | HOLD | 19 | same_side_lean | 727.50-728.50 | held_after_test | 5/3/2 | 0.0 | 1.8 | 12.0 | 20.0 | 18.75/5.75 | watch_stack_before_root_cushion |
| 11:47:02 | HOLD | 10 | same_side_lean | 719-725 | held_after_test | 9/5/4 | 7.0 | 1.608 | 15.5 | 0.0 | 22.25/1.25 | holdroot_no_add_root_not_onside |
| 11:50:21 | HOLD | 16 | direct_consumption | 724.50-727 | opposition_depleted | 8/4/4 | 7.0 | 0.818 | 13.25 | 11.7 | 20.0/0.25 | reject_depleted_contact |
| 11:50:24 | HOLD | 21 | same_side_lean | 725-727.50 | opposition_depleted | 8/4/4 | 7.0 | 0.79 | 13.0 | 13.3 | 19.75/0.0 | reject_depleted_contact |
| 11:50:25 | HOLD | 23 | same_side_lean | 725.75-727.75 | opposition_depleted | 8/4/4 | 7.0 | 0.771 | 12.75 | 15.0 | 19.5/0.0 | reject_depleted_contact |
| 11:50:27 | HOLD | 20 | direct_consumption | 726.25-728 | opposition_depleted | 8/4/4 | 7.0 | 0.788 | 12.5 | 16.7 | 19.25/0.0 | reject_depleted_contact |
| 11:50:30 | OWNED | 42 | same_side_lean | 726.50-727.25 | opposition_depleted | 9/4/5 | 7.0 | 0.768 | 12.0 | 20.0 | 18.75/0.25 | reject_depleted_contact |
| 11:51:32 | HOLD | 18 | direct_consumption | 725.75-730.75 | opposition_depleted | 9/4/5 | 7.0 | 0.58 | 9.75 | 35.0 | 16.5/0.5 | reject_depleted_contact |
| 11:41:36 | HOLD | 18 | direct_consumption | 725.75-730.75 | none | 5/3/2 | 5.25 | 0.865 | 9.75 | 35.0 | 16.5/8.0 | reject_depleted_contact |
| 11:51:41 | HOLD | 17 | same_side_lean | 723-731 | opposition_depleted | 9/4/5 | 7.0 | 0.657 | 9.5 | 36.7 | 16.25/0.75 | reject_depleted_contact |
| 11:41:37 | HOLD | 17 | same_side_lean | 723-731 | none | 5/3/2 | 5.25 | 1.006 | 9.25 | 38.3 | 16.0/8.5 | reject_depleted_contact |
| 11:51:54 | OWNED | 41 | same_side_lean | 725.25-732 | opposition_depleted | 10/4/6 | 7.0 | 0.747 | 8.0 | 46.7 | 14.75/2.25 | reject_depleted_contact |

### es_20260827_1330_short_7748

| time | action | band | family | range | renewal | stack d/l | rootC | replen | runway | path% | future MFE/MAE | call |
| --- | --- | ---: | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 13:44:39 | HOLD | 25 | direct_consumption | 751.25-753 | held_after_test_and_opposition_failed | 2/2/0 | 0.5 | 1.031 | 19.0 | 1.3 | 24.75/0.25 | sponsor_stack_add |
| 13:58:28 | OWNED | 29 | same_side_lean | 745-747.25 | none | 8/4/4 | 6.0 | 1.091 | 13.5 | 29.9 | 19.25/2.5 | stack_watch_no_renewal |
| 13:39:04 | HOLD | 25 | direct_consumption | 751.25-753 | none | 2/2/0 | 0.0 | 0.891 | 19.25 | 0.0 | 25.0/2.5 | watch_stack_before_root_cushion |
| 14:01:13 | HOLD | 29 | same_side_lean | 745-747.25 | held_after_test_and_opposition_failed | 1/0/1 | 6.0 | 1.101 | 13.0 | 32.5 | 18.75/0.25 | holdroot_no_add_shallow_stack |
| 13:44:35 | HOLD | 22 | direct_consumption | 752-752.75 | held_after_test | 2/2/0 | 0.5 | 1.018 | 20.0 | 0.0 | 25.75/0.25 | holdroot_no_add_root_not_onside |
| 13:45:24 | CONSUMED | 19 | direct_consumption | 749.75-754.25 | opposition_failed | 3/3/0 | 1.5 | 0.901 | 17.75 | 7.8 | 23.5/0.5 | reject_depleted_contact |
| 13:45:24 | CONSUMED | 27 | direct_consumption | 749.75-752 | opposition_failed | 4/4/0 | 1.5 | 0.863 | 17.75 | 7.8 | 23.5/0.5 | reject_depleted_contact |
| 13:45:32 | OWNED | 20 | same_side_lean | 749.50-755 | opposition_failed | 5/4/1 | 1.5 | 0.764 | 17.25 | 10.4 | 23.0/0.75 | reject_depleted_contact |
| 13:45:39 | OWNED | 28 | same_side_lean | 749.25-750.25 | opposition_failed | 6/4/2 | 2.25 | 0.823 | 17.25 | 10.4 | 23.0/0.75 | reject_depleted_contact |
| 13:45:53 | OWNED | 26 | same_side_lean | 748.75-751.75 | opposition_failed | 7/4/3 | 2.25 | 0.874 | 17.0 | 11.7 | 22.75/1.0 | reject_depleted_contact |
| 14:01:29 | CONSUMED | 30 | direct_consumption | 743.50-745.25 | opposition_depleted | 2/1/1 | 7.5 | 0.844 | 12.0 | 37.7 | 17.75/0.25 | reject_depleted_contact |
| 14:01:29 | OWNED | 31 | same_side_lean | 743.75-745.25 | opposition_depleted | 3/1/2 | 7.5 | 0.813 | 12.0 | 37.7 | 17.75/0.25 | reject_depleted_contact |
| 14:19:39 | HOLD | 32 | same_side_lean | 736.75-739.75 | held_after_test | 4/3/1 | 18.0 | 1.103 | 4.75 | 75.3 | 10.5/1.5 | scale_out_zone |
| 14:10:55 | OWNED | 32 | same_side_lean | 736.75-739.75 | opposition_failed | 4/1/3 | 14.75 | 1.143 | 4.75 | 75.3 | 10.5/2.0 | scale_out_zone |

### es_20260828_1120_short_7780

| time | action | band | family | range | renewal | stack d/l | rootC | replen | runway | path% | future MFE/MAE | call |
| --- | --- | ---: | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 11:34:09 | HOLD | 40 | same_side_lean | 778.25-781.75 | held_after_test_and_opposition_failed | 3/1/2 | 7.75 | 1.135 | 35.75 | 10.6 | 55.75/1.0 | sponsor_stack_add |
| 11:34:09 | HOLD | 48 | same_side_lean | 778.50-779.50 | held_after_test_and_opposition_failed | 3/1/2 | 7.75 | 1.198 | 35.75 | 10.6 | 55.75/1.0 | sponsor_stack_add |
| 11:35:03 | CONSUMED | 49 | direct_consumption | 776.50-777.50 | opposition_depleted | 4/2/2 | 7.75 | 1.015 | 33.75 | 15.6 | 53.75/1.75 | sponsor_stack_add |
| 11:36:16 | HOLD | 39 | direct_consumption | 775.75-781.75 | opposition_failed | 4/2/2 | 7.75 | 1.06 | 33.0 | 17.5 | 53.0/2.25 | sponsor_stack_add |
| 11:42:33 | HOLD | 53 | direct_consumption | 762.25-762.75 | held_after_test_and_opposition_failed | 3/2/1 | 24.5 | 1.123 | 19.5 | 51.2 | 39.5/2.25 | sponsor_stack_add_reduced |
| 11:40:59 | CONSUMED | 53 | direct_consumption | 762.25-762.75 | opposition_failed | 3/2/1 | 21.75 | 1.115 | 18.25 | 54.4 | 38.25/3.75 | sponsor_stack_add_reduced |
| 11:31:32 | OWNED | 48 | same_side_lean | 778.50-779.50 | none | 3/1/2 | 7.75 | 1.022 | 36.5 | 8.8 | 56.5/2.0 | stack_watch_no_renewal |
| 11:23:44 | HOLD | 40 | same_side_lean | 778.25-781.75 | held_after_test | 3/1/2 | 7.75 | 1.032 | 35.75 | 10.6 | 55.75/5.75 | stack_watch_retest_only |
| 11:45:23 | HOLD | 54 | same_side_lean | 760.25-761.75 | held_after_test | 4/2/2 | 24.5 | 1.041 | 17.75 | 55.6 | 37.75/1.25 | stack_watch_retest_only |
| 11:31:14 | HOLD | 40 | same_side_lean | 778.25-781.75 | none | 2/1/1 | 7.75 | 0.958 | 35.5 | 11.2 | 55.5/3.0 | reject_depleted_contact |
| 11:36:56 | HOLD | 39 | direct_consumption | 775.75-781.75 | held_after_test_and_opposition_failed | 4/2/2 | 7.75 | 0.904 | 33.25 | 16.9 | 53.25/0.5 | reject_depleted_contact |
| 11:21:38 | HOLD | 39 | direct_consumption | 775.75-781.75 | held_after_test | 2/1/1 | 7.75 | 0.999 | 32.5 | 18.8 | 52.5/9.0 | reject_depleted_contact |
| 11:37:23 | OWNED | 50 | same_side_lean | 774.75-778 | opposition_failed | 5/2/3 | 7.75 | 0.779 | 32.0 | 20.0 | 52.0/1.25 | reject_depleted_contact |
| 11:40:17 | CONSUMED | 51 | direct_consumption | 767.25-772.50 | opposition_failed | 3/2/1 | 16.25 | 0.314 | 24.0 | 40.0 | 44.0/0.75 | reject_depleted_contact |

## Call Counts

### es_20260827_1130_long_7728
- `holdroot_no_add_root_not_onside`: 1
- `reject_depleted_contact`: 10
- `reject_low_runway`: 2
- `scale_out_zone`: 9
- `sponsor_stack_add`: 1
- `stack_watch_retest_only`: 1
- `watch_stack_before_root_cushion`: 1

### es_20260827_1330_short_7748
- `holdroot_no_add_root_not_onside`: 1
- `holdroot_no_add_shallow_stack`: 1
- `reject_depleted_contact`: 7
- `scale_out_zone`: 22
- `sponsor_stack_add`: 1
- `stack_watch_no_renewal`: 1
- `watch_stack_before_root_cushion`: 1

### es_20260828_1120_short_7780
- `mature_path_hold_only`: 3
- `reject_depleted_contact`: 12
- `scale_out_zone`: 16
- `sponsor_stack_add`: 4
- `sponsor_stack_add_reduced`: 2
- `stack_watch_no_renewal`: 1
- `stack_watch_retest_only`: 2

## Policy Read

This supports a separate `SponsorStackRenewed` add path rather than weakening HoldRoot. Its priority should sit above HoldRoot because the decision is no longer a generic press; it is a renewed, replenished sponsor-stack event after root cushion exists. It should remain below `SuppressAdd`, `PassiveHarvest`, `Reduce`, `Flatten`, and `Retire`, and the add must use `preserve_risk_anchor_on_add` so the child rail never becomes the campaign sponsor.