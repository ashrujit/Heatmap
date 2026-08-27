# Kahn Replay Report

Campaign: `nq-2026-08-26-long-reversal-1255`
Side: `Long`
Status: `active`
Decisions: `7`
Ignored events: `0`
Notes: Synthetic Skurry-derived 2026-08-26 NQ long replay after the lower exploration. Probe 29260-29290, no add in the probe corridor, add only after accepted demand above 29290, target zone 29365-29370.

## Decisions

| ET | Phase | Action | Pos | Reason | Waypoint | Risk | Evidence |
|---|---|---:|---:|---|---|---|---|
| 13:15:20 | Ready->ProbeOpen | AllowProbe | 0->1 | trap_probe/same_side_lean_at_trap_probe | probe-29260-29290 | 29260-29262 (nq-131520-ll-demand-29260-29262) | LevelLedger RailOwned Demand 29260-29262 s=26 |
| 13:40:00 | ProbeOpen->ProbeOpen | SuppressAdd | 1->1 | no_add_zone/inside_no_add_zone | no-add-29260-29290 | - | LevelLedger RailOwned Demand 29280-29291.75 s=30 |
| 14:05:00 | ProbeOpen->ProbeOpen | SuppressAdd | 1->1 | evaluate_zone/inside_evaluate_zone | evaluate-29288-29296 | - | LevelLedger RailHeld Demand 29291.25-29296 s=31 |
| 14:30:30 | ProbeOpen->Pressing | AllowAdd | 1->2 | press/same_side_ownership_inside_press_window | press-above-29290 | 29290-29303.5 (nq-143030-ll-demand-29290-29303) | LevelLedger RailOwned Demand 29290-29303.5 s=41 |
| 14:45:10 | Pressing->Pressing | AllowAdd | 2->3 | press/same_side_ownership_inside_press_window | press-29300-29330 | 29300.25-29328.75 (nq-144510-ll-demand-29300-29328) | LevelLedger RailOwned Demand 29300.25-29328.75 s=48 |
| 15:00:30 | Pressing->TargetZone | Reduce | 3->2 | target_zone/target_same_side_effort_absorbed | target-29365-29370 | - | Footprint Absorption Buy 29365-29368.25 d=720 v=680 |
| 15:05:30 | TargetZone->Retired | Retire | 2->0 | target_zone/opposite_ownership_at_target | target-29365-29370 | 29361-29368.25 (nq-150530-ll-supply-29361-29368) | LevelLedger RailOwned Supply 29361-29368.25 s=44 |

## Risk Notes

- 13:15:20: active risk - -> 29260-29262 (nq-131520-ll-demand-29260-29262)
- 13:15:20: root risk - -> 29260-29262 (nq-131520-ll-demand-29260-29262)
- 14:30:30: active risk 29260-29262 -> 29290-29303.5 (nq-143030-ll-demand-29290-29303)
- 14:45:10: active risk 29290-29303.5 -> 29300.25-29328.75 (nq-144510-ll-demand-29300-29328)
- 15:05:30: active risk 29300.25-29328.75 -> -
- 15:05:30: root risk 29260-29262 -> -

## Final State

- Phase: `Retired`
- Position: `0`
- Retries: `1/3 remaining=2`
- Active risk: `-`
- Root risk: `-`
- Suppress adds until: `14:06:30`
