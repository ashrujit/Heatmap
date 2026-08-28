# Kahn Replay Report

Campaign: `synthetic-es-2026-08-27-long-orr-post-7728`
Side: `Long`
Status: `active`
Decisions: `5`
Ignored events: `101`
Notes: Synthetic reconstruction from ES 2026-08-27 ORR notes: probe 7716-7726, scale above 7728, harvest 7732-7736, target 7741. Used to test fixed post-expiry management semantics.

## Decisions

| ET | Phase | Action | Pos | Reason | Waypoint | Risk | Evidence |
|---|---|---:|---:|---|---|---|---|
| 10:07:53 | Ready->ProbeOpen | AllowProbe | 0->2 | trap_probe/same_side_lean_at_trap_probe | probe-7716-7726 | 7712-7714.75 (seed-es-100753-long-probe) | LevelLedger RailHeld Demand 7712-7714.75 s=20 |
| 10:37:08 | ProbeOpen->ProbeOpen | SuppressAdd | 2->2 | no_add_zone/inside_no_add_zone | no-add-7716-7728 | - | LevelLedger RailOwned Demand 7723.75-7727.5 s=56.17953272406973 |
| 10:37:29 | ProbeOpen->ProbeOpen | SuppressAdd | 2->2 | no_add_zone/inside_no_add_zone | no-add-7716-7728 | - | LevelLedger RailFailed Supply 7728-7729.75 s=43.4828887540185 |
| 10:38:32 | ProbeOpen->ProbeOpen | SuppressAdd | 2->2 | no_add_zone/inside_no_add_zone | no-add-7716-7728 | - | LevelLedger RailTested Demand 7723.75-7727.5 s=56.17953272406973 |
| 10:38:42 | ProbeOpen->Ready | Reduce | 2->0 | path_stress/path_opposite_ownership | harvest-7732-7736 | 7730.75-7730.75 (live-ll-54-RailOwned-2026-08-27T14:38:42.3442581Z) | LevelLedger RailOwned Supply 7730.75-7730.75 s=8.74790935857636 |

## Risk Notes

- 10:07:53: active risk - -> 7712-7714.75 (seed-es-100753-long-probe)
- 10:07:53: root risk - -> 7712-7714.75 (seed-es-100753-long-probe)
- 10:38:42: active risk 7712-7714.75 -> -
- 10:38:42: root risk 7712-7714.75 -> -

## Final State

- Phase: `Ready`
- Position: `0`
- Retries: `1/3 remaining=2`
- Active risk: `-`
- Root risk: `-`
- Suppress adds until: `10:40:42`
