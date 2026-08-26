# Kahn Replay Report

Campaign: `es-2026-08-25-short-open-reject`
Side: `Short`
Status: `active`
Decisions: `6`
Ignored events: `0`
Notes: Capture-backed 2026-08-25 ES short open-reject replay. BubbleTape events are fallback grouped tape because MarketRecorder identity fields were empty.

## Decisions

| ET | Phase | Action | Pos | Reason | Waypoint | Risk | Evidence |
|---|---|---:|---:|---|---|---|---|
| 09:40:23 | Ready->ProbeOpen | AllowProbe | 0->1 | trap_probe/same_side_lean_at_trap_probe | trap-7690-7700 | 7697-7699.5 (es-094023-ll-supply-7697-held) | LevelLedger RailHeld Supply 7697-7699.5 s=10.7 |
| 09:56:15 | ProbeOpen->Pressing | AllowAdd | 1->2 | press/same_side_ownership_inside_press_window | press-below-7690 | 7692.25-7698.25 (es-095615-ll-supply-7692) | LevelLedger RailOwned Supply 7692.25-7698.25 s=62.2 |
| 10:23:24 | Pressing->Pressing | AllowAdd | 2->3 | press/same_side_ownership_inside_press_window | press-below-7690 | 7685.25-7695.5 (es-102324-ll-supply-7685) | LevelLedger RailOwned Supply 7685.25-7695.5 s=154.3 |
| 10:29:56 | Pressing->BuildTrial | HoldRoot | 3->3 | build_trial/build_trial_alive | build-7682-7689 | 7682.25-7689 (es-102956-ll-supply-7682) | LevelLedger RailOwned Supply 7682.25-7689 s=53 |
| 10:30:30 | BuildTrial->TargetZone | Reduce | 3->2 | target_zone/target_same_side_effort_absorbed | target-7668 | - | BubbleTape Absorption Sell 7666-7667.75 d=-359 v=359 |
| 10:30:44 | TargetZone->Retired | Retire | 2->0 | target_zone/opposite_ownership_at_target | target-7668 | 7664.25-7668.5 (es-103044-ll-demand-7664) | LevelLedger RailOwned Demand 7664.25-7668.5 s=16.5 |

## Risk Notes

- 09:40:23: active risk - -> 7697-7699.5 (es-094023-ll-supply-7697-held)
- 09:40:23: root risk - -> 7697-7699.5 (es-094023-ll-supply-7697-held)
- 09:56:15: active risk 7697-7699.5 -> 7692.25-7698.25 (es-095615-ll-supply-7692)
- 10:23:24: active risk 7692.25-7698.25 -> 7685.25-7695.5 (es-102324-ll-supply-7685)
- 10:29:56: active risk 7685.25-7695.5 -> 7682.25-7689 (es-102956-ll-supply-7682)
- 10:30:44: active risk 7682.25-7689 -> -
- 10:30:44: root risk 7697-7699.5 -> -

## Final State

- Phase: `Retired`
- Position: `0`
- Active risk: `-`
- Root risk: `-`
- Suppress adds until: `-`
