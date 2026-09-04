# KahnRuntime Design Notes

## Boundary

Kahn is a campaign governor. The user declares the opportunity and important
prices; Kahn manages a bounded campaign from typed evidence. A future agent may
help draft or critique plans, but only deterministic code may enforce decisions.

## Runtime Shape

- `CampaignPlan` is the immutable input contract.
- `CampaignState` is the mutable runtime memory: phase, simulated/live quantity,
  active risk anchor, root risk anchor, armed probe, suppressed-add windows,
  accepted probe-attempt count, execution-pause reason, and retirement state.
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

`Trading Enabled=true` submits market entry/add orders, can work tagged
reduce-only close-limit orders for configured passive harvest objectives, can
maintain a tagged weighted-BE stop-market backstop after scale inventory exists,
and uses Quantower `ClosePosition` for active reduce, flatten, and retire
decisions. Runtime orders are tagged `KH:`. On stop, Kahn cancels only its own
tagged working orders and logs a warning if doing so would remove runtime BE
protection while a bound live position remains open.

Operator controls are not campaign evidence and do not depend on the campaign
active window. A changed `Control Path` file with `kind=KAHN_CONTROL` and
`action=FLAT` cancels Kahn-owned working orders, closes all bound live
positions, and retires campaign state once close submission is accepted.
`action=CANCEL` retires only when flat; with exposure still open it rejects and
asks for `FLAT`. Existing control contents are marked seen at startup so stale
controls are not replayed into a new run.

Runtime paths are part of the instance boundary. In multi-symbol use, keep
campaign, control, evidence, decision-log, and checkpoint files under the same
symbol/account profile directory, for example `...\KahnRuntime\ES\` and
`...\KahnRuntime\NQ\`. A shared root `control.json` can be used for a deliberate
single-instance setup, but it is not safe as the normal ES/NQ live convention
because controls are delivered by path.

Passive harvest is not a bracket/TP engine. It is a campaign objective that lets
Kahn progressively lighten inside a declared paid area before waiting for full
opposite-side proof. Routine broker protection is limited to weighted BE after
scale inventory exists. Sponsor/root failure still moves by typed policy
evidence, waypoint, path stress, and sponsor lineage rather than by broker stop
migration or raw tick-touch orders.

Kahn reconciles live position state from the configured execution
`Symbol`/`Account`. It pauses and logs operator-action errors rather than
adopting manual/orphan positions or ambiguous multiple positions.

Campaign expiry is an entry-admission boundary, not a campaign kill switch.
`window.expires_at` blocks fresh flat probe entries, but if a probe filled
before expiry, Kahn continues evaluating typed evidence for adds, suppressions,
reductions, sponsor-failure flattening, and target/retirement decisions.

`objective.passive_harvest` describes the paid area where exit inventory should
be offered/bid before Kahn waits for a confirmed auction failure. It accepts a
side-aware `range`: for longs the lower edge is the harvest floor and upper edge
is stretch; for shorts the upper edge is the floor and lower edge is stretch.
Kahn submits reduce-only close-limit orders at the passive BBO (`ask` to sell a
long, `bid` to cover a short), capped by `max_working_quantity` and the current
position. A live limit submission marks harvest active but does not decrement
campaign quantity until broker fills/position reconciliation prove it. Shadow
mode can simulate a touched passive fill. Once harvest is active, loss of the
floor triggers active retire/cleanup of remaining inventory.

Example:

```json
"objective": {
  "target_range": { "lower": 7740.0, "upper": 7743.0 },
  "target_proximity_ticks": 8,
  "suppress_adds_in_target_zone": true,
  "passive_harvest": {
    "range": { "lower": 7740.0, "upper": 7743.0 },
    "initial_clip_quantity": 1,
    "follow_clip_quantity": 2,
    "max_working_quantity": 2,
    "floor_failure_ticks": 0
  }
}
```

Campaign sizing is directive-local. `probe_quantity`, `add_quantity`, and
`max_position_quantity` come from the loaded campaign so an operator can
change size for a new situation without restarting and losing live LL warmup.
The strategy-level `Instance Max Quantity` remains a hard cap over any
campaign request.

`scale_mode` is the coarse scaling switch. `root_only` keeps the campaign at
the probe/root position and ignores otherwise valid add evidence. `scale_allowed`
removes manual add-price selection from the directive: Kahn may track same-side
LL ownership/hold evidence inside the arena as a scale candidate, unless a
higher-priority no-add, evaluate, path-stress, target, harvest, reduce, flatten,
or retire policy wins first. That first worse-price same-side rail is not an add
by itself. A repair/counter-claim must appear, fail as typed evidence, and then
fresh same-side continuation must reassert at or beyond the failed repair before
`AllowAdd` can fire. There is no fixed wall-clock continuation window; stale
context is reset structurally when a new candidate is tracked, a fresh repair
claim appears, scale inventory is reduced/harvested, or the campaign flattens.
Explicit `press`/`build_trial`/`repair_hold` waypoints still label and gate
evidence when supplied, but they are no longer required for scale participation.

Scale sponsor promotion is one accepted add behind the newest child evidence.
The first add after root queues a pending sponsor while active risk stays at the
older/root sponsor and weighted BE is the account backstop. When a later add
fires farther in the favorable direction, Kahn promotes the previously queued
child and queues the new child. If price reaches harvest before the next add,
the pending child never has to become sponsor.

Weighted BE is a separate account backstop. It is not armed at root/probe size.
After the first accepted add, Kahn waits until the actual shadow/live position is
larger than probe size and the executable quote is beyond weighted average. Only
then does it place or maintain one `BE` stop-market order for the open quantity.
If an armed BE is touched, or a live position disappears while BE is active, the
campaign retires. If BE cannot be established while scaled, Kahn attempts an
active retire/flatten because scaled inventory without the account backstop is
outside the intended contract.
An active `REDUCE` cancels the current BE first and clears BE state; after the
reduce is accepted, normal backstop maintenance can place a fresh BE only if the
remaining live position is still larger than probe size.
Broker rejects during BE cancel/replace or close submission are treated as
transient once: Kahn refreshes the bound live position and retries that path one
time. If the retry also fails, runtime enters `RecoveryActionRequired`; that
state is manual human intervention, not an automatic strategy branch.

The drawn `trap_probe` window is only the area where entry evidence may fire and
retry attempts may occur; it is not the stop range. Same-side and
counter-claim-failed probe entries anchor to the actual evidence range, never
the full probe waypoint. Root/sponsor failure remains policy evidence: raw
displacement beyond the anchor can be context, but campaign failure requires
typed evidence such as `SponsorFailed` or same-side `RailFailed` near the active
risk anchor. That keeps Kahn's root semantics aligned with LL
time/repair/failure behavior instead of turning `risk.root_stop_ticks` into a
touch-triggered stop order.

`execution.max_retry` is also directive-local and defaults to `3`. It is a
probe-attempt budget, not an evidence retry counter and not a broker-rejection
counter. Once the budget is exhausted and the campaign has flattened, the
state moves to `Paused` rather than `Retired`. The plan, waypoints, live LL
warmup, decision log, and checkpoint context remain available; an amended or
reissued campaign digest can clear the pause and continue evaluation from the
current auction map.

## Evidence

Live LL evidence uses the copied EAR/LevelLedger ownership engine against the
configured `Market Data Symbol` DOM. The runtime samples book state, waits for
LL warmup, converts rail ownership/hold/failure/test transitions into
`CampaignEvidence`, and then lets campaign policies decide whether that evidence
means probe, add, suppress, hold, reduce, or flatten.

The JSONL evidence path remains active in live mode. This keeps manual/research
evidence injection available without requiring a constantly waking agent.
External evidence must include `ts_utc` or `timestamp`, and runtime processing
rejects records older than `Evidence Max Age (sec)` or materially ahead of the
runtime clock. Kahn still drains evidence while no campaign is eligible, so a
temporary campaign parse failure or inactive window cannot leave a stale backlog
to be treated as fresh authority later.

## GexBot Integration Plan

GexBotMCP is the options-context source, not an execution signal. The first Kahn
integration should use GexBot data during campaign drafting and replay, where a
human-woken agent or prep pass converts futures-space context into explicit
waypoints and management constraints.

Useful GEX-derived campaign context:

- `call_wall`, `put_wall`, major positive/negative GEX, and nearby large strikes
  can become `target`, `no_add`, `evaluate`, `path_stress`, or `risk` waypoints.
- `zero_gamma` can mark an evaluate boundary where add permission, repair
  survival, and continuation tolerance need stricter auction proof.
- net-GEX level and movement can adjust management posture: positive/stable GEX
  favors quicker harvest and slower chase; negative/falling GEX can justify more
  extension tolerance only after LL, footprint, BubbleTape, or price acceptance
  proves sponsorship.
- wall removal, wall relocation, or a sharp wall-history change should wake
  Saavik or prompt a fresh campaign proposal. It is not a policy decision by
  itself.

Do not let GEX authorize `AllowProbe` or `AllowAdd`. Kahn still requires LL,
BubbleTape/footprint, price acceptance, or explicit campaign evidence for any
entry/add decision. GEX can support `SuppressAdd`, `TightenRisk`, `Reduce`,
`Harvest`, `EvaluateZone`, `PathStress`, or `Retire` decisions when auction
context agrees.

The likely runtime shape is a typed, cache-provenanced `GexContext` or
`ContextMarker` evidence source with ticker, category, snapshot timestamp, cache
source, futures-space levels, and derived waypoint suggestions. Start offline in
`KahnRuntime.Replay` against the 2026-08-26 failed-breakout and reversal legs,
then validate on a full live cached session before wiring any automatic runtime
polling. A direct MCP poller inside Kahn is deferred; one separately running
GexBotMCP service should own SQLite collection and freshness.

## Policy Families

- `TrapProbePolicy`: early, small entries at edges when counter-aggression or a
  same-side lean makes a trap plausible before full LL proof exists.
- `PressPolicy`: scale participation using repaired-continuation LL ownership,
  bounded by scale mode, favorable progression, arena/runway, and target-zone
  restrictions. First same-side ownership tracks a scale candidate; the add
  requires a failed repair/counter-claim and renewed same-side continuation.
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
  active sponsor still holds, and marks qualifying adverse repair claims so
  `PressPolicy` can recognize their later failure as add context.

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
