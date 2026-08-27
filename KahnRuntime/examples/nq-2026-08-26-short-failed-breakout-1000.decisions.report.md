# Kahn Replay Report

Campaign: `nq-2026-08-26-short-failed-breakout-1000`
Side: `Short`
Status: `active`
Decisions: `6`
Ignored events: `0`
Notes: Synthetic Skurry-derived 2026-08-26 NQ failed-breakout short replay. Evidence is normalized from footprint/profile reads, not live Kahn LL emissions.

## Decisions

| ET | Phase | Action | Pos | Reason | Waypoint | Risk | Evidence |
|---|---|---:|---:|---|---|---|---|
| 10:00:00 | Ready->ProbeArmed | ArmProbe | 0->0 | trap_probe/counter_effort_at_trap_probe | trap-29315-29333 | - | BubbleTape BubbleFinalized Buy 29329-29332.75 d=220 v=420 |
| 10:00:18 | ProbeArmed->ProbeOpen | AllowProbe | 0->1 | trap_probe/same_side_lean_at_trap_probe | trap-29315-29333 | 29329.25-29332.5 (nq-100018-ll-supply-29329-29333) | LevelLedger RailHeld Supply 29329.25-29332.5 s=18 |
| 10:01:00 | ProbeOpen->Pressing | AllowAdd | 1->2 | press/same_side_ownership_add_preserve_root_risk | press-below-29308 | 29329.25-29332.5 (nq-100018-ll-supply-29329-29333) | LevelLedger RailOwned Supply 29306.75-29308.5 s=24 |
| 10:07:30 | Pressing->Pressing | AllowAdd | 2->3 | press/same_side_ownership_add_preserve_root_risk | press-29289-29292 | 29329.25-29332.5 (nq-100018-ll-supply-29329-29333) | LevelLedger RailOwned Supply 29289.75-29291.75 s=31 |
| 10:26:30 | Pressing->TargetZone | Reduce | 3->2 | target_zone/target_same_side_effort_absorbed | target-29172-29180 | - | Footprint Absorption Sell 29175-29182.5 d=-136 v=2080 |
| 10:28:30 | TargetZone->Retired | Retire | 2->0 | target_zone/opposite_ownership_at_target | target-29172-29180 | 29164-29181.5 (nq-102830-ll-demand-29164-29181) | LevelLedger RailOwned Demand 29164-29181.5 s=34 |

## Risk Notes

- 10:00:18: active risk - -> 29329.25-29332.5 (nq-100018-ll-supply-29329-29333)
- 10:00:18: root risk - -> 29329.25-29332.5 (nq-100018-ll-supply-29329-29333)
- 10:28:30: active risk 29329.25-29332.5 -> -
- 10:28:30: root risk 29329.25-29332.5 -> -

## Final State

- Phase: `Retired`
- Position: `0`
- Retries: `1/3 remaining=2`
- Active risk: `-`
- Root risk: `-`
- Suppress adds until: `-`
