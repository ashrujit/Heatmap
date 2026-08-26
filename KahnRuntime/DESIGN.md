# KahnRuntime Design Notes

## Boundary

Kahn is a campaign governor. The user declares the opportunity and important
prices; Kahn manages a bounded campaign from typed evidence. A future agent may
help draft or critique plans, but only deterministic code may enforce decisions.

## Runtime Shape

- `CampaignPlan` is the immutable input contract.
- `CampaignState` is the mutable runtime memory: phase, simulated/live quantity,
  active risk anchor, root risk anchor, armed probe, suppressed-add windows, and
  retirement state.
- `CampaignEvidence` is the normalized event stream from price, LevelLedger,
  BubbleTape, footprint/delta replay, broker state, live LL transitions, or
  manual replay tools.
- `ICampaignPolicy` modules evaluate the current state and one evidence event.
- `DecisionResolver` chooses the highest-priority valid decision.
- `ShadowDecisionLog` writes the detailed audit trail.
- `KahnOrderGateway` is the live adapter boundary. It accepts only resolved
  policy decisions and validates execution symbol/account/side/quantity before
  broker calls.

## Live Adapter

`Trading Enabled=false` keeps Kahn in shadow mode. Accepted entry/add decisions
write synthetic fills when `Shadow Fill Simulation=true`; this is useful for
policy rehearsal and dry runs.

`Trading Enabled=true` submits market entry/add orders and uses Quantower
`ClosePosition` for reduce, flatten, and retire decisions. Runtime orders are
tagged `KH:`. On stop, Kahn cancels only its own tagged working orders.

The adapter deliberately does not manage brackets, TP limits, BE migration, or
protection stops yet. Those require a separate protection-order design because
Kahn's risk can move by policy, waypoint, path stress, and sponsor lineage.

Kahn reconciles live position state from the configured execution
`Symbol`/`Account`. It pauses and logs operator-action errors rather than
adopting manual/orphan positions or ambiguous multiple positions.

Campaign sizing is directive-local. `probe_quantity`, `add_quantity`, and
`max_position_quantity` come from the loaded campaign so an operator can
change size for a new situation without restarting and losing live LL warmup.
The strategy-level `Instance Max Quantity` remains a hard cap over any
campaign request.

## Evidence

Live LL evidence uses the copied EAR/LevelLedger ownership engine against the
configured `Market Data Symbol` DOM. The runtime samples book state, waits for
LL warmup, converts rail ownership/hold/failure/test transitions into
`CampaignEvidence`, and then lets campaign policies decide whether that evidence
means probe, add, suppress, hold, reduce, or flatten.

The JSONL evidence path remains active in live mode. This keeps manual/research
evidence injection available without requiring a constantly waking agent.

## Policy Families

- `TrapProbePolicy`: early, small entries at edges when counter-aggression or a
  same-side lean makes a trap plausible before full LL proof exists.
- `PressPolicy`: in-between participation using LL/EAR-style same-side
  ownership, bounded by runway and target-zone restrictions.
- `BuildTrialPolicy`: decides whether a managed-risk position has earned a new
  risk-owning sponsor, and flattens when the active sponsor fails.
- `TargetZonePolicy`: suppresses adds near objective and trims/harvests when
  same-side effort near target has poor reward.
- `NoAddZonePolicy`: permits holding an existing root/probe through a corridor
  while preventing LL/EAR-style same-side rails from becoming add permission.
- `EvaluateZonePolicy`: locks leverage in a waypoint review zone and can reduce
  when same-side effort is absorbed or opposite ownership appears before target.
- `PathStressPolicy`: handles mature path and exposure stress before a distant
  target by suppressing adds, reducing to a waypoint cap, or trimming when
  same-side effort is absorbed in the watch zone.
- `RepairHoldPolicy`: allows contest against non-causal adverse claims while the
  active sponsor still holds.

## First Replay Target

The first comparison set is ES 2026-08-24:

- 09:50-10:20 short: edge probe and suppressed adds into 7660 demand.
- 10:31-10:51 short reissue: hard failed-buy trap, likely scratch/retire.
- 10:57-11:25 scalp: hold while the below-7660 build trial is alive, then react
  quickly to effort/no-reward.
- 11:35-12:35 long: after clearing 7674-7675, use demand as hold support, not
  automatic add permission, and harvest into 7680-7685.

## Offline Runner

Use `KahnRuntime.Replay` to test campaign grammar and policy behavior without
Quantower or broker state:

```powershell
dotnet run --project KahnRuntime.Replay -- --campaign KahnRuntime\examples\es-2026-08-24-short-0950.campaign.json --evidence KahnRuntime\examples\es-2026-08-24-short-0950.evidence.jsonl --out KahnRuntime\examples\es-2026-08-24-short-0950.decisions.jsonl --include-ignored
```

Replay context time is each evidence timestamp. That matters because campaign
expiry should test the historical slice, not current wall-clock time.
