# Kahn Replay Report

Campaign: `nq-2026-08-25-short-open-reject`
Side: `Short`
Status: `active`
Decisions: `8`
Ignored events: `0`
Notes: Capture-backed 2026-08-25 NQ short open-reject replay. BubbleTape events are fallback grouped or delta-mode evidence because MarketRecorder identity fields were empty.

## Decisions

| ET | Phase | Action | Pos | Reason | Waypoint | Risk | Evidence |
|---|---|---:|---:|---|---|---|---|
| 09:47:30 | Ready->ProbeArmed | ArmProbe | 0->0 | trap_probe/counter_effort_at_trap_probe | trap-29315-29420 | - | BubbleTape BubbleFinalized Buy 29392-29395.75 d=230 v=230 |
| 09:47:44 | ProbeArmed->ProbeOpen | AllowProbe | 0->1 | trap_probe/same_side_lean_at_trap_probe | trap-29315-29420 | 29377.25-29378.75 (nq-094744-ll-supply-29377) | LevelLedger RailOwned Supply 29377.25-29378.75 s=8.8 |
| 09:48:10 | ProbeOpen->Ready | Flatten | 1->0 | build_trial/risk_anchor_failed | - | 29377.25-29378.75 (nq-094810-ll-supplyfail-29377) | LevelLedger RailFailed Supply 29377.25-29378.75 s=8.8 |
| 09:54:16 | Ready->ProbeOpen | AllowProbe | 0->1 | trap_probe/same_side_lean_at_trap_probe | trap-29315-29420 | 29361.5-29364.5 (nq-095416-ll-supply-29361) | LevelLedger RailOwned Supply 29361.5-29364.5 s=13.3 |
| 09:59:52 | ProbeOpen->Pressing | AllowAdd | 1->2 | press/same_side_ownership_inside_press_window | press-below-29315 | 29308-29311.75 (nq-095952-ll-supply-29308) | LevelLedger RailOwned Supply 29308-29311.75 s=16.8 |
| 10:00:56 | Pressing->Pressing | AllowAdd | 2->3 | press/same_side_ownership_inside_press_window | press-below-29315 | 29301.75-29302.75 (nq-100056-ll-supply-29302) | LevelLedger RailOwned Supply 29301.75-29302.75 s=12.2 |
| 10:30:28 | Pressing->TargetZone | Reduce | 3->2 | target_zone/target_same_side_effort_absorbed | target-29080-29166 | - | Footprint Absorption Sell 29174-29181.75 d=-167 v=329 |
| 10:30:45 | TargetZone->Retired | Retire | 2->0 | target_zone/opposite_ownership_at_target | target-29080-29166 | 29172.25-29174.5 (nq-103045-ll-demand-29172) | LevelLedger RailOwned Demand 29172.25-29174.5 s=13.5 |

## Risk Notes

- 09:47:44: active risk - -> 29377.25-29378.75 (nq-094744-ll-supply-29377)
- 09:47:44: root risk - -> 29377.25-29378.75 (nq-094744-ll-supply-29377)
- 09:48:10: active risk 29377.25-29378.75 -> -
- 09:48:10: root risk 29377.25-29378.75 -> -
- 09:54:16: active risk - -> 29361.5-29364.5 (nq-095416-ll-supply-29361)
- 09:54:16: root risk - -> 29361.5-29364.5 (nq-095416-ll-supply-29361)
- 09:59:52: active risk 29361.5-29364.5 -> 29308-29311.75 (nq-095952-ll-supply-29308)
- 10:00:56: active risk 29308-29311.75 -> 29301.75-29302.75 (nq-100056-ll-supply-29302)
- 10:30:45: active risk 29301.75-29302.75 -> -
- 10:30:45: root risk 29361.5-29364.5 -> -

## Final State

- Phase: `Retired`
- Position: `0`
- Active risk: `-`
- Root risk: `-`
- Suppress adds until: `-`
