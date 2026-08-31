# KahnRuntime — Code Review, 2026-08-30

Scope: every source file in `KahnRuntime/` (~8,500 LOC across 12 `.cs` files), plus
`AGENTS.md`, `DESIGN.md`, `KahnRuntime.csproj`, and the 12 example campaigns.
`KahnRuntime.Replay` was **not** reviewed (separate project).

Build verified during review: `dotnet build KahnRuntime.csproj` → **0 warnings, 0 errors**.
Quantower API usage was spot-checked against `api-recon` — `Core.ModifyOrder(order, tif,
quantity, price, triggerPrice, trailOffset)` is called correctly (positional `quantity`,
named `triggerPrice`; `price = -1` is treated as "unchanged" by the platform).
`Position.Quantity` is used as a magnitude with `Position.Side` for direction, which
matches the platform convention.

Overall: the architecture is sound and unusually disciplined for this kind of system —
immutable plan, typed decisions, deterministic resolver, append-only audit, narrow broker
adapter, self-tests that actually encode the design invariants. The findings below are
concentrated in three places: **the risk-down execution path**, **the gap between what a
campaign JSON declares and what the runtime actually enforces**, and **evidence-freshness
handling**.

---

## Severity summary

| # | Finding | Severity |
|---|---------|----------|
| 1 | A failed order-cancel blocks FLAT / RETIRE / REDUCE | **High** |
| 2 | `root_stop_ticks` is inert; root-only campaigns have no broker stop | **High** |
| 3 | Breakeven offset is applied twice | Medium-High |
| 4 | `EvidenceInbox` offset uses a stale `FileInfo.Length` | Medium-High |
| 5 | Uncaught file I/O aborts the entire worker tick | Medium |
| 6 | No evidence-age gate; backlogs replay as if current | Medium |
| 7 | Editing the campaign in shadow mode silently discards open state | Medium |
| 8 | Warmup epoch never restarts; spurious z-events after a book gap | Medium |
| 9 | `_bands` grows unbounded for the whole session | Medium |
| 10 | Live position quantity is clamped to plan max on reconcile | Medium |
| 11 | Fixed 5 s settle window can trip a false `orphan_bound_position` | Medium |
| 12 | `KH:` order tag carries no instance identity | Medium |
| 13 | Decision-log writer thread dies silently; audit trail lost | Medium |
| 14 | REDUCE cancels the BE stop, leaving a protection gap | Low-Medium |
| 15 | Stopping the strategy cancels BE but leaves the position open | Low-Medium |
| 16–29 | Dead config surface, resolver tiebreak, cleanup | Low |

---

## High severity

### 1. A failed order-cancel blocks every risk-down action

`KahnOrderGateway.cs:639`

```csharp
if (!CancelRuntimeOrders("order_cancel_before_" + role.ToLowerInvariant()))
{
    return Failure("failed to cancel Kahn working orders before close",
        requiresOperatorAction: true);
}
```

`CancelRuntimeOrders` returns `allAccepted`, which is `false` if **any** cancel returns a
non-`Success` status or throws. `ClosePosition` is the single path for `REDUCE`, `FLAT`,
and `RETIRE`, so one uncooperative cancel prevents the position from being closed at all.

Failure scenario: a `HARVEST` limit is working when the operator writes `FLAT`.
`RuntimeOrders().Where(IsWorkingOrder)` snapshots it as working; between the filter and
`Core.Instance.CancelOrder`, the limit fills. The broker rejects the cancel of a filled
order. `allAccepted` goes `false`, `ClosePosition` returns `Failure`,
`HandleFlatControl` (`KahnRuntime.cs:538-549`) logs `FLAT rejected` and returns `true`.
The operator's emergency flatten did nothing, and the remaining inventory stays open.

The same gate sits in front of the breakeven-touched retire
(`MaintainBreakevenBackstop` → `ExecuteDecision(retire)`) and the
"BE could not be established → flatten" fallback, so the two automated
last-resort exits inherit the same failure mode.

Cancel failure is a normal broker outcome (already filled, already cancelled, pending
state). Closing exposure should not be conditional on it. Suggested shape: attempt the
cancels, log each result, and proceed with `ClosePosition` regardless — then re-attempt
cancellation of any survivors afterwards. Reserve the hard stop for the case where the
close itself is rejected.

### 2. `root_stop_ticks` is parsed, defaulted, and never read — root-only campaigns run with no broker stop

`CampaignContracts.cs:183`, `CampaignPlanStore.cs:187`

```
CampaignContracts.cs:183:  public int RootStopTicks { get; init; } = 16;
CampaignPlanStore.cs:187:  RootStopTicks = OptionalPositiveInt(value, "root_stop_ticks", 16),
```

Those are the only two occurrences in the entire project. Nothing reads the value.

This is not theoretical: **all 12 example campaigns in `examples/` declare
`root_stop_ticks`** (e.g. `es-2026-08-24-short-0950.campaign.json:22` sets `20`). An
operator building a plan from those templates would reasonably conclude Kahn enforces a
20-tick hard stop on the root position. It does not.

The only broker-side protective order Kahn ever places is the weighted-BE stop, and
`CampaignState.BreakevenBackstopEligible` (`CampaignContracts.cs:463`) requires
`AcceptedAddCount > 0`. In `scale_mode: root_only`, `PressPolicy` never emits `AllowAdd`
(`CampaignPolicy.cs:274`), so `AcceptedAddCount` stays at zero forever and BE never arms.

Net effect: **a live `root_only` campaign carries zero broker-side protection.** Every
exit depends on LL sponsor-failure / rail-failure evidence arriving and resolving to
`Flatten`. If the market gaps, the data feed stalls, `book_unusable` fires, or the worker
is stuck in the recovery-required branch (`ReconcileLivePosition` returning `false` skips
`MaintainBreakevenBackstop` *and* `ProcessBookSample`), nothing closes the position.

This is a design decision as much as a bug — `DESIGN.md` does say "Sponsor/root risk still
moves by policy… rather than by broker stop migration." But shipping a `root_stop_ticks`
knob in every example that silently does nothing is the dangerous part. Either implement
it as a real stop-market backstop at root size, or remove it from the schema and the
examples and state the "no root stop" contract explicitly in `AGENTS.md`.

---

## Medium-high severity

### 3. The breakeven offset is applied twice

`KahnRuntime.cs:1005-1012` computes the trigger:

```csharp
private double BreakevenTriggerPrice(CampaignPlan plan, RuntimePosition position)
{
    int offsetTicks = Math.Max(0, plan?.Risk?.BreakevenBackstopOffsetTicks ?? 0);
    double offset = offsetTicks * Math.Max(_tickSize, 0.0000001);
    return plan?.Side == CampaignSide.Long
        ? RoundUp(position.AveragePrice + offset)
        : RoundDown(position.AveragePrice - offset);
}
```

That value is passed into the decision as `ProtectionPrice` (`KahnRuntime.cs:1001`).
`KahnOrderGateway.EnsureBreakeven` (`:450-459`) then treats it as the *basis* and applies
the offset again:

```csharp
double basis = decision.ProtectionPrice ?? position.AveragePrice;   // already avg + offset
int offsetTicks = Math.Max(0, plan.Risk?.BreakevenBackstopOffsetTicks ?? 0);
double offset = offsetTicks * _tickSize;
double trigger = plan.Side == CampaignSide.Long
    ? RoundUp(basis + offset)                                       // avg + 2 * offset
    : RoundDown(basis - offset);
```

The submitted stop sits at `avg ± 2 × offset`. Meanwhile `CampaignState.ArmBreakevenBackstop`
records `decision.ProtectionPrice` — the *single*-offset value — so
`_state.BreakevenBackstopPrice`, the checkpoint, and the `BE` metric all disagree with the
resting broker order. `BreakevenBackstopTouched` also evaluates against the single-offset
price, so the runtime's own touch detection is at the wrong level.

Latent today because `breakeven_backstop_offset_ticks` defaults to `0` and no example sets
it — which is also why no self-test caught it. The direction of the error is "tighter than
configured" rather than "looser", so it locks in more than intended rather than risking
more, but it will stop scaled positions out earlier than the operator's contract.

Fix: have the gateway use `decision.ProtectionPrice` directly when present and apply the
offset only when falling back to `position.AveragePrice`.

### 4. `EvidenceInbox` records a stale offset, causing duplicate delivery and torn-line loss

`EvidenceInbox.cs:28-55`

```csharp
FileInfo info = new(_path);
if (info.Length < _offset)          // ← Length is materialized and cached here
    _offset = 0;
...
using FileStream stream = new(_path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite);
stream.Seek(_offset, SeekOrigin.Begin);
using StreamReader reader = new(stream, Encoding.UTF8, true, 64 * 1024);
while ((line = reader.ReadLine()) != null) { ... }   // reads to *current* EOF
_offset = info.Length;              // ← stale cached value, not what was consumed
```

`FileInfo.Length` is cached on first access. The read loop runs to the live EOF, which may
be past that snapshot if the campaign agent appended in between (the worker polls every
250 ms, so this window is hit routinely under an active writer).

Two consequences:

- **Duplicate delivery.** Events written after the `FileInfo` snapshot are parsed and
  returned, but `_offset` is rewound to before them, so the next poll replays them.
  `CampaignState.ShouldEmit` absorbs most of this via its 5-second dedupe window
  (`CampaignContracts.cs:478`), but only when the replayed event resolves to the *same*
  `DedupeKey`. If state advanced in between, the duplicate produces a fresh decision.
- **Torn-line loss.** If the writer is mid-line, `info.Length` includes the partial bytes.
  `ReadLine` returns the fragment (parse error, logged), and `_offset` advances past the
  whole partial line — so that evidence event is permanently lost, and the next read may
  start mid-line and log a second garbage parse error.

Fix: bound the read to `info.Length` explicitly (or track consumed bytes by encoding each
line), and stop at the last complete newline so a partial trailing line is re-read on the
next poll rather than consumed.

---

## Medium severity

### 5. Uncaught file I/O aborts the entire worker tick

`CampaignPlanStore.cs:37` and `RuntimeControlStore.cs:61` both call `File.ReadAllText`
*outside* the `try` block that guards parsing:

```csharp
string json = File.ReadAllText(_path);      // not guarded
string digest = Sha256(json);
if (string.Equals(digest, _lastDigest, StringComparison.Ordinal))
    return new ...{ Changed = false };
try { ... CampaignPlanParser.Parse(json, digest) ... }
catch (Exception ex) { return new ...{ Error = ex.Message }; }
```

On Windows, a writer holding the file exclusively produces `IOException: being used by
another process`. That escapes `LoadIfChanged` → escapes `LoadPlan`/`ProcessControl` →
lands in the `Worker` catch-all (`KahnRuntime.cs:332`).

Because `LoadPlan()` is the *first* thing the worker does after `DrainBrokerEvents()`, a
throw there skips **`ProcessControl`, `ReconcileLivePosition`, `MaintainBreakevenBackstop`,
`ProcessBookSample`, and evidence processing** for that tick. If the condition persists —
an editor or agent holding `campaign.json` open — Kahn stops reconciling position state
and stops maintaining the breakeven stop entirely, while still logging a generic
`Worker failed` line each tick.

The control path is the more alarming one: `control.json` is the emergency-`FLAT` channel,
and a sharing violation there means the control is never even read.

`EvidenceInbox.ReadNewEvents` has the same exposure on its `FileStream` constructor.

Fix: wrap the reads and surface them as `Error` on the result object, the way parse
failures already are. Separately, consider moving `ProcessControl` ahead of `LoadPlan` so
control handling never depends on the plan file being readable.

### 6. No evidence-age gate anywhere

Policies are evaluated against wall-clock `now`, never against `evidence.Timestamp`:

- `ProcessEvidence(evidence, now)` is called with `DateTimeOffset.UtcNow` from the worker
  (`KahnRuntime.cs:318-320`) and with `DateTimeOffset.UtcNow` from the book-sample loop
  (`:1161`), even though the latter has already checked `ShouldEvaluateEvidenceAt(evidence.Timestamp, …)`.
- `CampaignEvidenceParser` falls back to `DateTimeOffset.UtcNow` when a record carries no
  timestamp (`EvidenceInbox.cs:77-79`), so an undated line is stamped "now" by definition.
- No policy inspects `evidence.Timestamp` at all.

This interacts badly with the inbox gating in `Worker`. `_evidenceInbox.ReadNewEvents` is
only called inside `if (_plan != null && _state != null && _plan.ShouldEvaluateEvidenceAt(now, _state))`
(`KahnRuntime.cs:313-321`). While no campaign is active, the file is never read, so
`_offset` never advances — and the moment a campaign becomes active, **the entire backlog
of evidence accumulated since strategy start is drained in one tick and evaluated as
current.** A two-hour-old `rail_owned` can authorize a fresh probe.

The queued market events have a milder version of the same issue: `DrainMarketEvents`
returns the whole backlog (up to the 2,000 cap) with no age filter, so a stalled worker can
act on a "harvest floor lost" quote that has since been reclaimed.

Fix: reject or down-weight evidence older than a configurable max age, and advance the
inbox offset even when the campaign is inactive (mark-as-seen rather than
mark-as-unread), mirroring how `RuntimeControlStore` marks existing control content seen
at startup.

### 7. Editing the campaign in shadow mode silently discards open simulated state

`KahnRuntime.cs:368-372`

```csharp
if (!PlanAdmissible(result.Plan))
    return;
_plan = result.Plan;
_state = CampaignState.ForPlan(_plan);      // fresh state, prior state discarded
```

`PlanAdmissible` (`:635-695`) performs its position/working-order guards only after:

```csharp
if (!_runTradingEnabled)
    return true;
```

So in shadow mode — the mode `AGENTS.md` explicitly recommends for validating new
directives — any change to `campaign.json` (including a whitespace or `notes` edit, since
the digest is a SHA-256 of the raw text) wipes `SimulatedPositionQuantity`, both risk
anchors, the pending child anchor, `AcceptedAddCount`, and the harvest state mid-rehearsal.

The live-mode guard is correct. The shadow-mode gap makes the primary rehearsal workflow
quietly lossy. Suggest applying the `_state.HasPosition` check regardless of mode.

### 8. The warmup epoch never restarts, and `MeanStd` can emit spurious events after a book gap

Two issues that compound.

`StartEvidenceEpochIfNeeded` (`KahnRuntime.cs:1187-1191`) returns immediately once
`_evidenceEpochStartedUtc != DateTime.MinValue`, and nothing ever resets it outside
`ResetForRun`. `_evidenceEpochReason` is set to `"startup"` in `ResetForRun` and never
changed. So after a `book_unusable` outage — stale L2 heartbeat, empty DOM, L1/DOM
mismatch — the engine resumes and is treated as fully warm on the very first sample back.
The presence of `_evidenceEpochReason` and the `book_usable_recovered` event suggest a
re-epoch was intended but never wired.

Meanwhile `ExecutionEvidenceEngine.MeanStd` (`LevelLedgerEvidenceEngine.cs:751-773`)
returns `(0, 0)` when fewer than two samples fall inside the lookback window, while the
firing gate upstream checks `_samples.Count >= 5` against the *retention* window, which is
`2 × BookLookbackSeconds` (`:189`). For a gap between `lookback` and `2 × lookback`
seconds, `_samples.Count >= 5` passes but `MeanStd` sees only the new sample and returns
zeros. The z-scores then degenerate:

```csharp
double zBi = (sample.BidInner - 0) / Math.Max(1.0, 0);   // = raw inner bid size
double zBc = (sample.BidCentroid - 0) / Math.Max(0.01, 0); // = centroid × 100
```

For ES that trivially exceeds the 2.5 threshold on all four channels, firing a burst of
`BID_BUILD`/`ASK_BUILD`/`BID_OUT`/`ASK_OUT` events at once. Combined with the missing
epoch reset, those fabricated events are immediately actionable and can cluster into a
`Candidate`, then a `RailOwned` band, then an `AllowProbe`.

Fix: reset the epoch on `book_usable_recovered` (the reason field is already there for it),
and require a minimum in-window sample count in `MeanStd` before any z-score is computed
(returning "no signal" rather than zeros).

### 9. `_bands` grows unbounded for the life of the session

`LevelLedgerEvidenceEngine.Prune` (`:775-782`) trims only `_pendingEvents` and
`_candidates`. `UpdateFailureObjects` removes `FailureZone` bands. **Rail bands (including
`Failed` ones) and `NoOwner`/`Contested` grey zones are never removed.**

Every sample tick then pays for it: `UpdateRails` allocates `_bands.ToArray()` (`:420`),
`RecordGrey` walks `_bands` (`:468`), `TryFindOutsideGrey` LINQs over it (`:623`), and
`FindMergeableFailureObject` reverses it (`:636`). At 1 Hz over a full RTH session the
collection only grows, so per-sample cost drifts upward and memory is never reclaimed.

Correctness is mostly preserved (stale zones are filtered by `OwnershipContestedSec` and
failed rails are skipped), so this is a resource/latency finding rather than a behavioural
one — but it is on the 1 Hz path of a long-running strategy.

Fix: prune rails whose `FailedUtc` is older than the grey TTL, and grey zones past
`OwnershipContestedSec`.

### 10. Reconcile clamps the observed live quantity to plan max

`CampaignContracts.cs:708-711`

```csharp
public void ReconcileObservedPositionQuantity(int quantity, CampaignPlan plan)
{
    int max = plan?.Sizing?.MaxPositionQuantity ?? quantity;
    SimulatedPositionQuantity = Math.Max(0, Math.Min(quantity, max));
```

If the bound live position exceeds `max_position_quantity` — a manual add by the operator,
or an over-fill — state records `max`, not the truth. The checkpoint, the `Sim Qty` metric,
and the `campaign_state` audit records all under-report real exposure, which is exactly the
number a human would check during an incident.

Downstream safety mostly holds by accident: because the clamp saturates at `max`,
`PressPolicy`'s `>= MaxPositionQuantity` gate still blocks further adds, and
`MaintainBreakevenBackstop` sizes from `CurrentPosition()` (live) rather than state. But
the reconcile step should record what is actually there and flag the excess as a recovery
condition, not quietly truncate it.

### 11. The fixed 5-second settle window can trip a false recovery halt

`ExecuteDecision` sets `_liveSettleUntilUtc = DateTime.UtcNow.AddSeconds(5)`
(`KahnRuntime.cs:1058`) after any accepted non-BE broker action, and
`ReconcileLivePosition` skips reconciliation until it elapses (`:1653`).

In live mode `simulateAcceptedDecisions` is `true` (`:766`), so an accepted `Reduce`
decrements `SimulatedPositionQuantity` at submission time. If the close hasn't fully filled
5 s later — a partial fill, a slow broker, a thin book — reconcile sees
`!_state.HasPosition && !live.IsFlat` and raises `orphan_bound_position` (`:1666-1670`),
returning `false`. The worker then returns early, which halts evidence processing, book
sampling, **and breakeven maintenance**, until an operator intervenes.

The 5 s constant is undocumented and not exposed as an input. Consider deriving the settle
window from actual order state (working quantity on Kahn-tagged close orders) rather than
a fixed timer, and treating "state flat, live not yet flat, close order still working" as
a normal in-flight condition rather than an orphan.

### 12. The `KH:` order tag carries no instance identity

`KahnOrderGateway.IsRuntimeOrder` (`:157-161`) matches any order on the bound
symbol+account whose `Comment` or `GroupId` starts with `KH:`. `BuildTag` (`:766-781`)
encodes `KH:<campaign[0..18]>:<role>:<evidence[0..8]>` but nothing identifies the instance.

`AGENTS.md` designates *file paths* as the instance boundary, but the order-ownership test
is symbol+account. Two Kahn instances on the same symbol and account — two concurrent ES
campaigns, or a restarted instance overlapping a stale one — will each classify the other's
working orders as its own and cancel them on stop, on `FLAT`/`CANCEL`, or before any close.

Separately, the 18-character campaign truncation means two campaigns sharing an 18-char
prefix produce identical tags, which also defeats any future per-campaign filtering.

Fix: mint a per-run instance id at `OnRun` and include it in the tag; match on it in
`IsRuntimeOrder`.

### 13. The decision-log writer thread dies silently, and the audit trail goes with it

`ShadowDecisionLog.WriteLoop` (`:98-132`) wraps its entire body — directory creation, file
open, and the drain loop — in a single `try`. Any failure invokes `_errorSink` once and the
thread **exits permanently**. There is no retry and no restart.

`Write` keeps succeeding afterwards: it serializes, increments `_queued`, and enqueues into
a queue nobody drains, until the 100,000 cap is reached and everything is silently dropped
into `_dropped`. `DroppedCount` does reach the checkpoint as `dropped_decision_log_events`,
but the operator only sees one error line at the moment of failure — and `AGENTS.md`
designates the JSONL as "the detailed audit source."

Given that this is the record of every order Kahn submits, a dead writer deserves a
persistent state, not a single log line. Suggest surfacing it as a metric/`RuntimeState`
and attempting periodic reopen.

Minor related race: `Dispose` calls `_signal.Dispose()` after a 5-second `Join` timeout, so
a slow writer can hit `WaitOne` on a disposed handle. The resulting exception is swallowed
by the loop's catch, but it leaves the final queued lines unwritten.

### 14. REDUCE cancels the breakeven stop and relies on the next tick to replace it

`ClosePosition` calls `CancelRuntimeOrders` for every role including `REDUCE`
(`KahnOrderGateway.cs:639`), which cancels the `BE` stop along with harvest limits.
`_state.BreakevenBackstopActive` stays `true` and `BreakevenBackstopOrderId` goes stale.

The next `MaintainBreakevenBackstop` pass finds no `BE` order and places a new one, so it
self-heals — but the position is unprotected for up to one `WorkerPollMs` (250 ms default,
up to 5 s configurable), and longer if the quote has gone stale
(`MaintainBreakevenBackstop` returns early when `!market.IsValid`, `:855-857`) or if the
worker aborted for any reason in finding #5.

A partial reduce shouldn't require tearing down the account backstop. Consider
role-scoping the pre-close cancel to `HARVEST` orders for `REDUCE`, and modifying the BE
stop quantity afterwards rather than cancel-and-replace.

### 15. Stopping the strategy cancels protection but leaves the position open

`Shutdown` (`KahnRuntime.cs:1937`) calls `_gateway?.CancelRuntimeOrdersOnStop()`, which
cancels the BE stop and any working harvest limits, then unsubscribes and exits. It does
not flatten.

Leaving the position for the operator is a defensible choice — Kahn shouldn't liquidate on
a UI action — but removing the only protective order on the way out is the part that
deserves a loud warning. Neither `AGENTS.md` nor `DESIGN.md` mentions it. At minimum,
`Shutdown` should log an `ERR:`-bucket line when it cancels a `BE` order while a bound
position is still open.

---

## Low severity / cleanup

### 16. Config surface that parses cleanly and does nothing

These all validate, load, and are then ignored — with no warning to the operator:

| Symbol | Where declared | Consumers |
|---|---|---|
| `waypoint.suppress_adds_within_ticks` | `CampaignContracts.cs:266`, `CampaignPlanStore.cs:310` | none |
| `WaypointRole.Risk` | `CampaignContracts.cs:41` | parser only |
| `WaypointRole.Invalidation` | `CampaignContracts.cs:44` | parser only |
| `PolicyAction.TightenRisk` | `CampaignContracts.cs:96` | never emitted by any policy |
| `PolicyAction.Cooldown` | `CampaignContracts.cs:101` | never emitted by any policy |
| `EvidenceKind.RailTested` | emitted by the LL engine and translated at `KahnRuntime.cs:1276` | no policy branches on it |
| `EvidenceKind.PriceCross / PriceAccept / PriceReclaim / PositionChanged / Timer` | `EvidenceInbox.cs:130-142` | no policy branches on them |

`role: "invalidation"` is the sharpest of these — the name promises a flatten and the
runtime is silently inert. `TightenRisk` is named in `AGENTS.md` as something GEX context
"can support," but nothing produces it. One example evidence file already uses
`price_cross`, which no policy reads.

Either wire these up or reject them at parse time so a plan can't silently under-deliver.

### 17. Unreachable switch arms in the parsers

`CampaignPlanParser.Normalize` (`:532-537`) strips `-`, `_`, and spaces before matching, so
these cases in `ParseWaypointRole` (`:506-520`) can never match: `"trap_probe"`,
`"build_trial"`, `"no_add"`, `"repair_hold"`, `"path_stress"`, `"mature_path"`. The
collapsed variants alongside them (`"trapprobe"`, `"buildtrial"`, …) do match, so behaviour
is correct — the underscored arms are simply dead. Same pattern in `ParseScaleMode`.

### 18. The resolver tiebreak contradicts the stated priority invariant

`CampaignPolicy.cs:79-80`

```csharp
.OrderByDescending(candidate => candidate.Priority)
.ThenBy(candidate => candidate.Action)
```

`ThenBy(Action)` sorts by enum ordinal ascending, so on a priority tie the *lower* enum
value wins: `AllowAdd` (3) would beat `Reduce` (9), and `AllowProbe` (2) would beat
`Flatten` (10). That directly inverts the `AGENTS.md` invariant "Risk-down decisions
outrank add or entry permission."

No current pair of policies produces a tie, so this is latent — but it's a landmine for
anyone adding a policy or adjusting a priority constant. Make the tiebreak explicit
risk-down-first (e.g. `ThenByDescending(PriorityFor(Action))`, or reorder the enum and
document that the ordering is load-bearing).

Related: `ActionPriority` (`:56-71`) lists `PassiveHarvest = 845` out of numeric sequence
between `SuppressAdd` and `TightenRisk`, which makes the table harder to audit than it
needs to be.

### 19. `WithDefaultPriority` hand-copies every field

`CampaignPolicy.cs:89-109` reconstructs `PolicyDecision` property by property. All 15 are
currently copied correctly, but any new field added to `PolicyDecision` will be silently
dropped for every decision that didn't set an explicit priority — a very quiet failure
mode for a type that carries risk anchors and quantities. Converting `PolicyDecision` to a
`record` and using `decision with { Priority = … }` removes the hazard entirely.

### 20. `IsLargeEffort` hardcodes instrument-specific thresholds

`CampaignContracts.cs:357-358`

```csharp
public bool IsLargeEffort
    => Math.Abs(Delta ?? 0) >= 500 || (Volume ?? 0) >= 200;
```

This gates trap-probe entries, build-trial retires, target-zone reduces, evaluate-zone
reduces, and path-stress reduces. The same constants apply to ES and NQ despite very
different volume profiles, and they're not exposed as `InputParameter`s or plan fields —
which sits awkwardly against the project's "tune via QT sliders" convention.

### 21. `_decisionDedupe` is never trimmed

`CampaignState._decisionDedupe` (`:424`) grows one entry per distinct `DedupeKey`, and the
key embeds `RiskAnchor`, `ChildRiskAnchor`, and `ProtectionPrice` string forms — so every
new price anchor mints a new permanent entry. Bounded in practice by session length, but
it's a monotonic dictionary on a long-running object with no eviction.

### 22. `BrokerEvent.FromTrade` null-handling and field asymmetry

`KahnOrderGateway.cs:833-843`

```csharp
Side = trade?.Side == TradingPlatform.BusinessLayer.Side.Buy ? "Long" : "Short",
```

When `trade` is null, `trade?.Side` is `null`, `null == Side.Buy` is `false`, and the event
is labelled `"Short"` — a fabricated direction in the audit log. Also, `FromTrade` leaves
`AverageFillPrice` at its `0.0` default while `FromOrder` sets it to `NaN`, so the two
event shapes encode "unknown" differently in the JSONL.

### 23. `CheckpointSerializesNonFiniteMarketFields` doesn't test what it's named

`RuntimeSelfTests.cs:43-68` passes `TickSize = double.NaN` (sanitized to `0` before
serialization) and `LatestBid/Ask = null`, then asserts only that the output contains
`latest_bid`. It never exercises a non-finite value actually reaching `JsonSerializer`.

The real exposure is the `PriceRange` fields — `ActiveRiskAnchor`, `RootRiskAnchor`,
`PendingAddRiskAnchor`, `PassiveHarvestRange` — which `RuntimeCheckpointStore.Sanitize`
(`:139-150`) does **not** touch. `System.Text.Json` throws on non-finite doubles by default,
so an infinite bound would make every checkpoint save fail. Current call paths guard
against it (`EvidenceAnchor` returns `null` for the invalid sentinel range from
`CampaignEvidence.EffectiveRange`), but the sanitizer should cover the ranges and the test
should assert the throw-free path with real infinities.

### 24. Dead API surface in `ExecutionEvidenceEngine`

Declared and never called anywhere in the project: `LastMidTick`, `FindCandidate`,
`FindBand`, `ActiveCandidates`, `LiveRails`, `FailedRails`, `HeldFailureObjects`, and
`EvidenceBandView.IsLiveRail` (~45 lines). `Band.GreyMinTick`/`GreyMaxTick`,
`Candidate.Kinds`, and `Candidate.StartUtc` are written but never read.

Also unused: `PriceRange.Expanded` (`CampaignContracts.cs:121`),
`CampaignWaypoint.IsNear` (`:271`), and the `LogOperator(string message, bool error)`
overload (`KahnRuntime.cs:1994`).

The `KahnRuntime.LiveEvidence.EvidenceSide` / `EvidenceSource` types also collide by name
with the root-namespace `KahnRuntime` versions, which is why `KahnRuntime.cs:9-16` needs
seven `using` aliases. Worth a rename (`LlSide`, `LlSource`) for readability.

### 25. Every L1 quote becomes a policy-engine evaluation

`Symbol_NewQuote` (`:1334-1346`) enqueues a `PriceTouch` evidence record for **every**
quote, then trims:

```csharp
while (_marketEvents.Count > 2000 && _marketEvents.TryDequeue(out _)) { }
```

`ConcurrentQueue<T>.Count` is recomputed on each iteration, on the market-data callback
thread. Each surviving event is then run through all nine policies on the worker thread.
Normal ES/NQ rates make this fine, but the design means a worker stall converts directly
into a 2,000-event burst of full policy evaluations (see also finding #6). Consider
coalescing quotes to at most one evidence event per book-sample interval.

### 26. Parse failures re-read and re-fail every tick

Neither `CampaignPlanStore.LoadIfChanged` nor `RuntimeControlStore.LoadIfChanged` advances
`_lastDigest` when parsing throws, so a malformed file is re-read, re-hashed, and
re-parsed on every 250 ms poll until fixed. `LoadPlan`/`ProcessControl` suppress the
*log* spam via `_lastPlanError`/`_lastControlError` signature comparison, but the work
repeats indefinitely. Recording the failed digest (with the error) would make the retry a
no-op while still re-attempting on any content change.

### 27. Harvest limits are never re-priced, and the floor check precedes rounding

`PlaceHarvestLimit` (`:300-307`) computes the passive BBO price, validates it against the
harvest floor, and *then* rounds:

```csharp
double limitPrice = HarvestLimitPrice(plan.Side, market);
if (harvest?.IsUsable == true
    && !HarvestQuoteSatisfiesFloor(plan.Side, limitPrice, harvest))
{
    return Failure("quote is outside passive harvest floor");
}
limitPrice = RoundPrice(limitPrice);        // can move the price back through the floor
```

Rounding after validation can submit a price marginally through the floor. Separately,
once submitted, harvest limits are `Day` orders that are never re-priced as the BBO moves —
they simply rest until filled, until floor-loss triggers cleanup, or until a close cancels
them. That's a reasonable design for passive harvest, but it's worth stating in
`DESIGN.md` so it isn't mistaken for a working/chasing exit.

### 28. Plan validation gaps

`CampaignPlanParser.Parse` validates that every waypoint intersects the arena
(`:132-138`), but performs no equivalent check on `objective.target_range` or
`objective.passive_harvest.range`. Nothing verifies the harvest range is on the favorable
side of the campaign — a `long` campaign whose harvest range sits below the arena would
satisfy `IsAtOrBeyondFloor` immediately and start working reduce-only exits from the first
quote. Given that harvest submits live orders, side/arena validation belongs in the parser.

### 29. `CampaignWindow` accepts an unvalidated construction path

`Parse` checks `expires_at > not_before` (`:113-114`), but `CampaignWindow` itself has no
invariant, and `CampaignWindow.Contains` (`:164-165`) would silently return `false` for
everything if the two were ever inverted by a non-parser construction path (the self-test
helpers build windows directly). Low risk, but a `IsValid` guard would make the contract
self-enforcing.

---

## What's working well

Worth recording alongside the defects:

- **`ExecutionAttemptCount` is only spent on accepted submissions.** `ProcessEvidence`
  returns before `ApplyDecision` when the gateway rejects (`:749-764`), so quote staleness
  and broker rejections don't consume the retry budget — exactly as `AGENTS.md` specifies.
- **Delayed sponsor promotion is implemented correctly and well tested.**
  `PromotePendingAddRiskAnchor` requires both that the new child validates the pending
  anchor *and* that the pending anchor improves on the current reference
  (`CampaignContracts.cs:664-681`), and `DelayedSponsorPromotionLagsAcceptedAdds` walks
  three adds to prove the one-behind invariant holds.
- **Explicit `waypoint_id` correctly short-circuits nearest-waypoint matching.**
  `NearestWaypoint` returns `exact.Role == role ? exact : null` (`CampaignPolicy.cs:124-126`)
  with no fallback, and `PressPolicy` bails when an explicit waypoint doesn't resolve
  (`:305-307`) — this is precisely the "zone stealing" hazard the design doc calls out.
- **Passive harvest does not assume a live fill.** `passiveHarvestFillQuantity` is gated on
  `execution.Shadow` (`KahnRuntime.cs:767-771`), so live harvest submissions only move
  campaign quantity once reconciliation proves it.
- **Checkpoint writes are atomic** (temp file + `File.Move(overwrite: true)`) with
  signature-throttled error reporting.
- **Self-tests encode design invariants, not implementation details.** 32 tests covering
  retry-pause semantics, post-expiry management, price gates, zone precedence, sponsor
  lineage, and harvest ordering — and they run at startup with a hard failure, so a broken
  invariant stops the strategy rather than trading on it.

---

## Suggested order of work

1. **#1** — unblock the risk-down path. Nothing else matters if `FLAT` can be refused.
2. **#2** — decide whether `root_stop_ticks` becomes real or leaves the schema. Either way,
   document the actual protection contract for `root_only` before the next live run.
3. **#5** — wrap the file reads so a locked file can't silently suspend reconciliation and
   breakeven maintenance.
4. **#3, #4** — both are small, contained fixes with clear correct behaviour.
5. **#6, #7, #8** — evidence freshness and state preservation; these shape whether shadow
   rehearsal results are trustworthy.
6. The rest as cleanup, with **#16** and **#18** worth doing early since they're cheap and
   both are traps for future changes.
