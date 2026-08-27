# Kahn Replay Report

Campaign: `es-2026-08-26-long-reversal-1255`
Side: `Long`
Status: `active`
Decisions: `7`
Ignored events: `0`
Notes: Synthetic Skurry-derived 2026-08-26 ES long replay after the lower exploration. Probe 7680-7690, no add in the probe corridor, add only after accepted demand above 7690, target 7703.

## Decisions

| ET | Phase | Action | Pos | Reason | Waypoint | Risk | Evidence |
|---|---|---:|---:|---|---|---|---|
| 12:55:20 | Ready->ProbeArmed | ArmProbe | 0->0 | trap_probe/counter_effort_at_trap_probe | probe-7680-7690 | - | Footprint Absorption Sell 7674.75-7680 d=-520 v=420 |
| 12:55:45 | ProbeArmed->ProbeOpen | AllowProbe | 0->1 | trap_probe/same_side_lean_at_trap_probe | probe-7680-7690 | 7676.25-7680 (es-125545-ll-demand-7676-7680) | LevelLedger RailOwned Demand 7676.25-7680 s=32 |
| 13:20:00 | ProbeOpen->ProbeOpen | SuppressAdd | 1->1 | no_add_zone/inside_no_add_zone | no-add-7680-7690 | - | LevelLedger RailOwned Demand 7685.5-7688 s=28 |
| 13:55:00 | ProbeOpen->ProbeOpen | SuppressAdd | 1->1 | evaluate_zone/inside_evaluate_zone | evaluate-7688-7692 | - | LevelLedger RailHeld Demand 7688.75-7691 s=29 |
| 14:45:10 | ProbeOpen->Pressing | AllowAdd | 1->2 | press/same_side_ownership_inside_press_window | press-above-7690 | 7691-7696.5 (es-144510-ll-demand-7691-7696) | LevelLedger RailOwned Demand 7691-7696.5 s=43 |
| 15:00:30 | Pressing->TargetZone | Reduce | 2->1 | target_zone/target_same_side_effort_absorbed | target-7703 | - | Footprint Absorption Buy 7702.5-7705.5 d=640 v=520 |
| 15:05:30 | TargetZone->Retired | Retire | 1->0 | target_zone/opposite_ownership_at_target | target-7703 | 7701.75-7704 (es-150530-ll-supply-7702-7704) | LevelLedger RailOwned Supply 7701.75-7704 s=46 |

## Risk Notes

- 12:55:45: active risk - -> 7676.25-7680 (es-125545-ll-demand-7676-7680)
- 12:55:45: root risk - -> 7676.25-7680 (es-125545-ll-demand-7676-7680)
- 14:45:10: active risk 7676.25-7680 -> 7691-7696.5 (es-144510-ll-demand-7691-7696)
- 15:05:30: active risk 7691-7696.5 -> -
- 15:05:30: root risk 7676.25-7680 -> -

## Final State

- Phase: `Retired`
- Position: `0`
- Retries: `1/3 remaining=2`
- Active risk: `-`
- Root risk: `-`
- Suppress adds until: `13:56:30`
