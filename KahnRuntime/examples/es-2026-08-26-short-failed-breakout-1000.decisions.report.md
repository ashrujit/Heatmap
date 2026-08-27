# Kahn Replay Report

Campaign: `es-2026-08-26-short-failed-breakout-1000`
Side: `Short`
Status: `active`
Decisions: `6`
Ignored events: `0`
Notes: Synthetic Skurry-derived 2026-08-26 ES failed-breakout short replay. First leg harvests around 7680-7682 because the exact 7678 objective does not print until later.

## Decisions

| ET | Phase | Action | Pos | Reason | Waypoint | Risk | Evidence |
|---|---|---:|---:|---|---|---|---|
| 10:04:00 | Ready->ProbeArmed | ArmProbe | 0->0 | trap_probe/counter_effort_at_trap_probe | trap-7700-7703 | - | BubbleTape BubbleFinalized Buy 7701-7702.5 d=230 v=454 |
| 10:05:10 | ProbeArmed->ProbeOpen | AllowProbe | 0->1 | trap_probe/same_side_lean_at_trap_probe | trap-7700-7703 | 7701-7702.5 (es-100510-ll-supply-7701-7702) | LevelLedger RailHeld Supply 7701-7702.5 s=21 |
| 10:07:20 | ProbeOpen->Pressing | AllowAdd | 1->2 | press/same_side_ownership_add_preserve_root_risk | press-below-7700 | 7701-7702.5 (es-100510-ll-supply-7701-7702) | LevelLedger RailOwned Supply 7698.75-7701.5 s=28 |
| 10:20:20 | Pressing->Pressing | AllowAdd | 2->3 | press/same_side_ownership_add_preserve_root_risk | press-7687-7692 | 7701-7702.5 (es-100510-ll-supply-7701-7702) | LevelLedger RailOwned Supply 7687.25-7692.5 s=42 |
| 10:25:30 | Pressing->Pressing | Reduce | 3->1 | path_stress/inventory_above_path_cap | stress-7680-7683 | - | Footprint Absorption Sell 7680.5-7682.75 d=-3565 v=3899 |
| 12:37:30 | Pressing->Retired | Reduce | 1->0 | target_zone/target_same_side_effort_absorbed | target-7678 | - | Footprint Absorption Sell 7676.5-7678.75 d=-845 v=2993 |

## Risk Notes

- 10:05:10: active risk - -> 7701-7702.5 (es-100510-ll-supply-7701-7702)
- 10:05:10: root risk - -> 7701-7702.5 (es-100510-ll-supply-7701-7702)
- 12:37:30: active risk 7701-7702.5 -> -
- 12:37:30: root risk 7701-7702.5 -> -

## Final State

- Phase: `Retired`
- Position: `0`
- Retries: `1/3 remaining=2`
- Active risk: `-`
- Root risk: `-`
- Suppress adds until: `10:27:30`
