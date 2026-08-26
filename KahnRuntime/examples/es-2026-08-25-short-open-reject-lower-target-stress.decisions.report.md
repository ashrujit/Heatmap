# Kahn Replay Report

Campaign: `es-2026-08-25-short-open-reject-lower-target-stress`
Side: `Short`
Status: `active`
Decisions: `7`
Ignored events: `0`
Notes: Stress fixture: same ES open-reject thesis, but with a farther target below 7660. The path_stress waypoint models B-low/full-inventory harvest risk, not a repair re-entry.

## Decisions

| ET | Phase | Action | Pos | Reason | Waypoint | Risk | Evidence |
|---|---|---:|---:|---|---|---|---|
| 09:40:23 | Ready->ProbeOpen | AllowProbe | 0->1 | trap_probe/same_side_lean_at_trap_probe | trap-7690-7700 | 7697-7699.5 (es-094023-ll-supply-7697-held) | LevelLedger RailHeld Supply 7697-7699.5 s=10.7 |
| 09:56:15 | ProbeOpen->Pressing | AllowAdd | 1->2 | press/same_side_ownership_inside_press_window | press-below-7690 | 7692.25-7698.25 (es-095615-ll-supply-7692) | LevelLedger RailOwned Supply 7692.25-7698.25 s=62.2 |
| 10:19:00 | Pressing->Pressing | AllowAdd | 2->3 | press/same_side_ownership_inside_press_window | press-7682-7686 | 7686.25-7688.5 (es-101900-ll-supply-7686-synthetic) | Replay RailOwned Supply 7686.25-7688.5 s=48 |
| 10:23:24 | Pressing->Pressing | AllowAdd | 3->4 | press/same_side_ownership_inside_press_window | press-7682-7686 | 7685.25-7695.5 (es-102324-ll-supply-7685) | LevelLedger RailOwned Supply 7685.25-7695.5 s=154.3 |
| 10:28:56 | Pressing->Pressing | AllowAdd | 4->5 | press/same_side_ownership_inside_press_window | press-7682-7686 | 7682.25-7684.25 (es-102856-ll-supply-7682-synthetic) | Replay RailOwned Supply 7682.25-7684.25 s=42 |
| 10:29:56 | Pressing->Pressing | Reduce | 5->1 | path_stress/inventory_above_path_cap | path-stress-7664-7680 | - | Price PriceCross Sell |
| 10:30:30 | Pressing->Ready | Reduce | 1->0 | path_stress/path_same_side_effort_absorbed | path-stress-7664-7680 | - | BubbleTape Absorption Sell 7666-7667.75 d=-359 v=359 |

## Risk Notes

- 09:40:23: active risk - -> 7697-7699.5 (es-094023-ll-supply-7697-held)
- 09:40:23: root risk - -> 7697-7699.5 (es-094023-ll-supply-7697-held)
- 09:56:15: active risk 7697-7699.5 -> 7692.25-7698.25 (es-095615-ll-supply-7692)
- 10:19:00: active risk 7692.25-7698.25 -> 7686.25-7688.5 (es-101900-ll-supply-7686-synthetic)
- 10:23:24: active risk 7686.25-7688.5 -> 7685.25-7695.5 (es-102324-ll-supply-7685)
- 10:28:56: active risk 7685.25-7695.5 -> 7682.25-7684.25 (es-102856-ll-supply-7682-synthetic)
- 10:30:30: active risk 7682.25-7684.25 -> -
- 10:30:30: root risk 7697-7699.5 -> -

## Final State

- Phase: `Ready`
- Position: `0`
- Active risk: `-`
- Root risk: `-`
- Suppress adds until: `10:32:30`
