# Kahn Replay Report

Campaign: `es-2026-08-25-short-mean-revert-1255`
Side: `Short`
Status: `active`
Decisions: `6`
Ignored events: `0`
Notes: Capture-backed ES 2026-08-25 lunch/late-morning mean-revert short. This fixture tests edge-only execution gating after the true morning DD sell campaign.

## Decisions

| ET | Phase | Action | Pos | Reason | Waypoint | Risk | Evidence |
|---|---|---:|---:|---|---|---|---|
| 12:59:43 | Ready->ProbeOpen | AllowProbe | 0->1 | trap_probe/same_side_lean_at_trap_probe | edge-probe-7690-7692 | 7691.5-7692.5 (es-125943-ll-supply-edge-price) | LevelLedger RailHeld Supply 7691.5-7692.5 s=22.6 |
| 13:01:20 | ProbeOpen->ProbeOpen | SuppressAdd | 1->1 | evaluate_zone/inside_evaluate_zone | field-evaluate-7684-7689 | - | LevelLedger RailHeld Demand 7687.25-7689 s=46.1 |
| 13:04:30 | ProbeOpen->BuildTrial | HoldRoot | 1->1 | build_trial/build_trial_alive | build-7689-7692 | 7689-7691.75 (es-130430-ll-supply-body-hold) | LevelLedger RailOwned Supply 7689-7691.75 s=35.7 |
| 13:05:08 | BuildTrial->BuildTrial | SuppressAdd | 1->1 | evaluate_zone/inside_evaluate_zone | field-evaluate-7684-7689 | - | LevelLedger RailFailed Demand 7687.25-7690 s=83.3 |
| 13:06:23 | BuildTrial->BuildTrial | SuppressAdd | 1->1 | evaluate_zone/inside_evaluate_zone | field-evaluate-7684-7689 | - | LevelLedger RailFailed Demand 7686.5-7687.75 s=36.8 |
| 13:07:30 | BuildTrial->Retired | Reduce | 1->0 | target_zone/target_same_side_effort_absorbed | target-7680-7684 | - | BubbleTape Absorption Sell 7682.75-7683.75 d=-491 v=491 |

## Risk Notes

- 12:59:43: active risk - -> 7691.5-7692.5 (es-125943-ll-supply-edge-price)
- 12:59:43: root risk - -> 7691.5-7692.5 (es-125943-ll-supply-edge-price)
- 13:04:30: active risk 7691.5-7692.5 -> 7689-7691.75 (es-130430-ll-supply-body-hold)
- 13:07:30: active risk 7689-7691.75 -> -
- 13:07:30: root risk 7691.5-7692.5 -> -

## Final State

- Phase: `Retired`
- Position: `0`
- Active risk: `-`
- Root risk: `-`
- Suppress adds until: `13:07:53`
