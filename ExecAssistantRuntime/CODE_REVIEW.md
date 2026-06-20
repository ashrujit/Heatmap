# ExecAssistantRuntime — Code Review

Reviewer pass over `./ExecAssistantRuntime` against `DESIGN.md`,
`IMPLEMENTATION_PLAN.md`, `OPERATOR_GUIDE.md`, the two normative JSON schemas,
and the API constraints in the root `CLAUDE.md`.

No code was modified. Findings are grouped by file and tagged with **severity**
(Blocker / High / Medium / Low / Info) and **category** (Logic / Concurrency /
Robustness / API-Contract / Maintainability / Performance / Telemetry /
Schema-Conformance / Style). Each finding cites a file path and line range so
the location is unambiguous; suggested change is intent-only.

---

## Summary

- 4 Blocker / High findings touch real execution behavior: a dead-code stop
  branch, a pending-reclaim that can fire an Add when no leveraged position
  exists, a Shutdown/Worker race that can crash the strategy mid-event, and a
  silent telemetry-drop pattern (NaN in `fill_quality` JSON).
- Several Medium findings affect retry accounting, restart re-emission of
  protection events, protection-quantity comparison semantics, and listener
  cleanup.
- The contract layer (`DirectiveContracts.cs`) is well-structured. Most
  weaknesses concentrate in `ExecutionCoordinator.cs` (state machine corners)
  and `ExecAssistantRuntime.cs` (lifecycle / cross-thread).

If only a subset of items is actioned in this pass, the recommended priorities
are the Blockers (F-01, F-02, F-03), then F-04, F-05, F-08, F-10.

---

## Open Questions for the Author

These genuinely need human judgment; do not "fix" them without confirmation:

1. **`EvaluateBaseStop.sameCandidateConsumed` (F-01) — what was it supposed to
   detect?** Was it meant to catch the original supporting candidate being
   *re-consumed* into the opposite side (which the engine's one-shot candidate
   lifecycle makes impossible), or was it shorthand for "the support's rail id
   appearing again on the opposing side"? The fix depends on the intent.
2. **Retry counter semantics (F-09).** Should `max_base_reentries` bound
   *filled* attempts (current behavior — rejection storm is unbounded) or
   *submitted* attempts? DESIGN is silent on the distinction.
3. **`HardTargetReached` is defined on the coordinator but never called by
   `ExecutionCoordinator.cs` itself or by `ExecAssistantRuntime.cs`.** The hard
   target completion comes solely via broker fill → `OnPositionChanged`
   draining to flat, with no transition labeled `HARD_TP` on the disposition.
   Is that intentional, or was a coordinator-side runway check supposed to be
   wired up?

---

## Blocker

### F-01 · `EvaluateBaseStop`'s `sameCandidateConsumed` branch is dead code
**Severity:** Blocker · **Category:** Logic

`ExecutionCoordinator.cs:692-719`

```csharp
bool sameCandidateConsumed = opposing.Id == _entryContext.SupportObjectId
    && opposing.Source == EvidenceSource.Consumed;
```

`_entryContext.SupportObjectId` is the *entry-anchor* band/candidate id (the
same-side support for `supported_reclaim` or the converted wall for
`direct_conversion`). The `opposing` band is by construction on the opposite
side, and the evidence engine assigns unique ids to every emitted band
(`Band.Id = candidate.Id`, and each candidate is one-shot — see
`UpdateCandidates` flipping `candidate.Active = false`). So
`opposing.Id == _entryContext.SupportObjectId` can never be true: the engine
cannot recycle an id onto a band with the opposite side.

Consequence: the *only* path that can fire the semantic base stop is
`nearbyReverse`, which requires `_entryAnchorFailed = true` first AND a fresh
opposing rail within 20 ticks. The "candidate-support-consumed-directly" path
described in DESIGN.md:1006-1015 ("candidate support consumed directly into the
opposite side is an immediate reverse resolution") is not implemented. For
direct_conversion entries this is the *primary* invalidation in the
specification; trades may therefore stay open well past the documented stop.

**Suggested:** either drop the dead expression and document that the only stop
path is `_entryAnchorFailed` + nearby opposing rail, or track the original
*candidate identity used for entry* (not just its later band id) and detect
re-consumption against that lineage. DESIGN.md:1006-1015 is the controlling
text.

---

### F-02 · Pending reclaim can fire an Add after the base has stopped out
**Severity:** Blocker · **Category:** Logic / State machine

`ExecutionCoordinator.cs:564-664` (`EvaluateSupportedReclaim`,
`TryCompletePendingReclaim`)

When `EvaluateSupportedReclaim` sees a failed opposing rail with no
*confirmed* same-side support but with an active *candidate*, it stashes a
`PendingReclaim` whose `IsAdd` flag is captured from the originating state. The
4-second timer is then completed by `TryCompletePendingReclaim`, which is
called from both `Tick(...)` (line 207) and `ProcessEvidence(...)` (line 313).

Completion re-verifies the candidate, the failed band, quote eligibility, and
target distance — but it does **not** re-check that the position state still
matches `IsAdd`. If between arming and completion the base position stopped
out and the coordinator rearmed (`State == Armed`, `position.IsFlat == true`)
the deferred completion will still call
`CreateEntryIntent(... pending.IsAdd ...)` with `isAdd: true`. That will
submit an Add intent against a flat position, sized from `AddQuantity` not
`BaseQuantity`, and the intent will be tagged `:ADD:`. The reverse symmetry
(armed → leveraged transition between arm and complete) is implausible but
also unvalidated.

**Suggested:** before constructing the intent in
`TryCompletePendingReclaim`, re-derive `isAdd` from current
`position.IsFlat`/state, or invalidate the pending reclaim if the position
state no longer matches the captured intent.

---

### F-03 · Shutdown can NRE the Worker via a disposed/nulled `_events`
**Severity:** Blocker · **Category:** Concurrency / Robustness

`ExecAssistantRuntime.cs:1232-1246`, with consumers throughout the same file
that call `_events.Write(...)` directly (no null-prop).

```csharp
private void Shutdown(string eventType)
{
    ...
    _running = false;
    try { _workerTimer?.Dispose(); } catch { }    // does NOT wait for callback
    ...
    try { _events?.Dispose(); } catch { }
    _events = null;
    ...
}
```

`Timer.Dispose()` does not wait for an in-flight callback; only
`Dispose(WaitHandle)` does. The Worker reads `_running` once at the top and
then runs for tens or hundreds of milliseconds touching `_events.Write`
unguarded (e.g. `ExecuteIntents`, `ReconcilePosition`, `DrainBrokerEvents`,
`ProcessBookSample`, `LogStateIfChanged`). A `Stop()`/`OnRemove()` that lands
in the middle of one Worker tick can null `_events` underneath an active call,
yielding a `NullReferenceException` during shutdown — exactly when telemetry
should be most reliable.

`RuntimeEventLog.Write` is itself null-safe once entered (it short-circuits on
`_stopping`), so the failure mode is dereferencing a `null` field reference,
not a disposed-object exception.

**Suggested:** either (a) use `_workerTimer.Dispose(waitHandle)` and wait on
that handle before disposing `_events`, or (b) keep `_events` alive (don't
null it) and let `RuntimeEventLog.Dispose` continue to short-circuit writes
silently. Either way, audit every `_events.Write(...)` call site for
`?.` consistency.

---

### F-04 · `fill_quality` events silently fail to serialize when telemetry is NaN
**Severity:** High · **Category:** Telemetry / Robustness

`RuntimeEventLog.cs:66-75`, `ExecAssistantRuntime.cs:860-908`,
`QuantowerOrderGateway.cs:159-194` (and elsewhere).

`System.Text.Json` rejects `double.NaN` and `±Infinity` by default. The serializer
options used (`SerializerOptions` in `RuntimeEventLog.cs:134-138`) do not set
`NumberHandling = JsonNumberHandling.AllowNamedFloatingPointLiterals`. Many
fields can legitimately be NaN at runtime:

- `SubmitBid`/`SubmitAsk` are initialized to `double.NaN` in
  `SubmissionTelemetry` and remain NaN when the market snapshot was invalid at
  submit time.
- `TriggerBid`/`TriggerAsk` likewise default to NaN via `market?.Bid ?? NaN`
  in `CreateEntryIntent` and `CreateFlattenIntent`.
- `detection_drift_points`, `transport_slippage_points`,
  `total_implementation_cost_points`, and `quote_age_ms` (when `QuoteUtc` is
  `DateTime.MinValue`) can be derived from NaN inputs.

When that happens, `JsonSerializer.Serialize` throws, the catch in
`Write(...)` invokes `_errorSink` once, and the event is *dropped*. The
operator never sees `fill_quality`, `order_submit`, or `intent_result`
diagnostics for the most interesting cases (stale-quote fills, fills after
disconnect, etc.) — directly contradicting `OPERATOR_GUIDE.md:147-158` and
DESIGN.md:482-498.

**Suggested:** set
`NumberHandling = JsonNumberHandling.AllowNamedFloatingPointLiterals` on the
`SerializerOptions` (and ensure downstream consumers can parse `"NaN"`), or
scrub NaN to `null` before serialization.

---

## High

### F-05 · `EnsureHardTarget` quantity comparison uses `TotalQuantity` against position quantity
**Severity:** High · **Category:** API-Contract / Logic

`QuantowerOrderGateway.cs:244-263`

```csharp
Order existing = FindProtection("TP");
if (existing != null)
{
    if (NearlyEqual(existing.Price, price)
        && NearlyEqual(existing.TotalQuantity, position.Quantity))
        return Success(existing.Id, "hard target already correct");
    TradingOperationResult modify = Core.Instance.ModifyOrder(
        existing,
        TimeInForce.Default,
        position.Quantity,
        price: price);
    ...
}
```

`Order.TotalQuantity` is the placed size; it does not decrease as partial
fills consume the TP. After any partial TP fill, `existing.TotalQuantity`
will not equal the *remaining* position quantity, so the "already correct"
branch will misfire (modify when no modify is needed) — or, worse, a modify
will reset working quantity in a way the broker may interpret as resizing
either total or remaining depending on broker conventions. The same pattern
appears in `EnsureBreakeven` (`QuantowerOrderGateway.cs:336-348`).

**Suggested:** use `existing.RemainingQuantity` for "already correct"
comparison; document whether `ModifyOrder(...quantity:...)` is interpreted by
the broker as TotalQuantity or RemainingQuantity (the v1.145.9 BL convention
is TotalQuantity, but verify in `api-recon` before changing).

---

### F-06 · Restart-recovery may not adopt protection if broker already has TP/BE attached
**Severity:** High · **Category:** Logic / Restart

`ExecAssistantRuntime.cs:770-820` (`ProtectRecoveredPosition`)

`ProtectRecoveredPosition` unconditionally issues `EnsureBreakeven` then
`EnsureHardTarget` for a recovered position. `EnsureHardTarget` calls
`FindProtection("TP")` which only matches runtime-tagged orders
(`IsRuntimeOrder` requires the `EA:` tag prefix). After a restart, any
protection placed in the *previous* process still carries the `EA:` tag, so
it will be found — but only if the tag prefix and directive id substring
survived. Tag format is `EA:<directiveId>:<role>:<intent-prefix>` with
directiveId truncated to 18 chars (`BuildTag`). If the previously placed TP
used a different `intentId` (it did — intentId is a fresh `Guid.NewGuid()`
per intent), the tag bodies differ; `FindProtection("TP")` will still find
the *first* `:TP:` runtime order, but if it can't be adopted by Quantower
(stale order id, status flipped), the modify path returns `requiresFlatten:
true` and the position is flattened during the very recovery flow that was
trying to protect it.

This is partly intentional ("Failure to establish valid leveraged protection
is a flattening error"), but in restart recovery the operator usually wants
the existing valid TP retained rather than recreated. There's no logic that
checks `existing.Status` before deciding to modify vs. recreate.

**Suggested:** in restart recovery, gate the modify path on
`existing.Status == OrderStatus.Working` (or equivalent); fall back to a fresh
place if the prior order is not actually live; otherwise leave existing valid
TP untouched (no modify) when it already matches within tick tolerance.

---

### F-07 · `ReconcileSubmissionTimeouts` cancels by intent-id when the broker returned no order id
**Severity:** High · **Category:** API-Contract / Robustness

`ExecAssistantRuntime.cs:507-512` and `ExecAssistantRuntime.cs:910-933`

```csharp
string submissionKey = string.IsNullOrWhiteSpace(result.OrderId)
    ? intent.IntentId
    : result.OrderId;
_submissions[submissionKey] = ...;
```

…then in `ReconcileSubmissionTimeouts`:

```csharp
_gateway.CancelOrderById(key);  // key may be the intentId, not a real order id
```

`CancelOrderById` looks up `Core.Instance.Orders.FirstOrDefault(o => o.Id ==
orderId && IsRuntimeOrder(o))`. When `key` is an intentId, no order will ever
match and the cancel is a silent no-op. The 10-second timeout will mark the
attempt failed in the coordinator, but the working order (if it exists under
a delayed-acknowledgement broker id) keeps running and may fill late, leaving
the runtime with a position that the coordinator believes was never placed.

This is the precise failure mode that prompted F-15 of the design ("Quantower
returns success without an order id" — `AGENTS.md:40`). The mitigation is
implemented for *finding* the order (the `EA:` tag), but not for *cancelling*
it on timeout.

**Suggested:** on timeout for an intent whose `result.OrderId` was blank,
look up by tag (e.g. `RuntimeOrders().Where(o => o.Comment?.Contains(intent
.IntentId.Substring(0,8)) ?? false)`) and cancel everything that matches,
rather than calling `CancelOrderById(intentId)`.

---

### F-08 · `OnPositionChanged` re-issues `EnsureHardTarget` and `EnsureBreakeven` on every quantity/average change
**Severity:** High · **Category:** Performance / Broker behavior

`ExecutionCoordinator.cs:381-398`

The "position quantity or average changed" branch fires `EnsureHardTarget`
and `EnsureBreakeven` intents whenever `position.Quantity != previousQuantity
|| Math.Abs(avg - prevAvg) > 1e-9`. The gateway then either modifies or
recreates the protection orders. Broker rate-limits on order modifications
can be brittle — and `position.AveragePrice` can wobble micro-ticks during
partial fills if Quantower averages cumulatively.

Combined with the per-Worker-tick check in `ReconcilePosition`
(`ExecAssistantRuntime.cs:609-645`), each broker fill notification can trigger
multiple modify cycles. The gateway does have a `NearlyEqual` short-circuit,
so this is bounded — but only if `existing.TotalQuantity` matches (see F-05).

**Suggested:** debounce protection re-issue: only fire if the change exceeds
one tick on price or the position grew (not shrank). Shrinkage during exit
should not re-arm BE/TP at all.

---

### F-09 · Retry counter is bounded only on *filled* attempts; rejection storm is unbounded
**Severity:** High · **Category:** Logic / Safety

`ExecutionCoordinator.cs:332-350` and `ExecutionCoordinator.cs:730-765`

`_baseAttempts++` runs only inside `OnPositionChanged` when a base fill is
observed (`filledIntent.Kind == OrderIntentKind.EnterBase`). The
`OnOrderAttemptResult(intent, accepted: false)` path clears
`_pendingEntryIntent` but does *not* increment `_baseAttempts` and does *not*
consume an "attempt slot."

`_usedRootObjectIds` is added per root candidate, which limits re-arming on
the *same* root, but a directive with broad eligible evidence can produce
many fresh roots in a session. If the broker keeps rejecting (margin, market
closed, instrument halted), the runtime will keep submitting on every fresh
evidence resolution until the directive expires or the position fills.

DESIGN.md is ambiguous (`max_base_reentries: "Number of new base attempts
allowed after the initial base attempt"`) — it does not commit to
filled-vs-attempted semantics. The current implementation favors maximizing
the chance of getting in, which may be intentional. Worth confirming.

**Suggested:** open question for the author. If the intended interpretation
is "attempts submitted," increment a separate `_baseSubmits` counter on
`CreateEntryIntent` and gate `_pendingEntryIntent != null || _baseSubmits >
MaxBaseReentries+1` early.

---

### F-10 · Unsubscribe leaks `Order.Updated` handlers for already-removed orders
**Severity:** High · **Category:** Concurrency / Maintainability

`ExecAssistantRuntime.cs:1129-1144`

```csharp
foreach (Order order in Core.Instance.Orders.Where(o => SameBoundPair(...)))
{
    try { order.Updated -= Order_Updated; } catch { }
}
lock (_orderSubscriptionGate)
    _subscribedOrderIds.Clear();
```

The iteration enumerates *currently visible* orders. Any order that was
previously subscribed and has since been removed from
`Core.Instance.Orders` (via `Core_OrderRemoved`) is also gone from the
enumeration. Its `Updated` handler is unhooked there
(`ExecAssistantRuntime.cs:1186` — `order.Updated -= Order_Updated;`), so this
is largely a non-leak in practice. But the bookkeeping is fragile:
`_subscribedOrderIds.Clear()` happens *after* the iteration, so any new
`Order_Updated` event during the iteration would be processed against a
strategy whose `_running` may have been set false but whose state hash hasn't
yet been cleared. Result: a few last events queued to `_brokerEvents` after
`_running = false` and never drained.

**Suggested:** invert the order — clear `_subscribedOrderIds` before
iterating, and iterate `_subscribedOrderIds` (looking up each Order by id)
rather than `Core.Instance.Orders`. Discard the broker queue at the end of
Shutdown to make the silent-drop explicit.

---

### F-11 · Shadow `CurrentPosition` is masked when a real broker position appears in shadow mode
**Severity:** High · **Category:** Logic / Mode separation

`ExecAssistantRuntime.cs:1035-1040`

```csharp
private RuntimePosition CurrentPosition()
{
    if (!TradingEnabled && !_shadowPosition.IsFlat)
        return _shadowPosition;
    return LivePosition(out _);
}
```

In shadow mode with `_shadowPosition` flat, the method returns
`LivePosition()` — i.e., a manually-opened broker position on the bound pair
becomes visible to the coordinator, which then tries to reconcile it
(`ReconcilePosition` can issue `SafetyFlatten` if the side mismatches
directive direction). In `TradingEnabled = false`, `SafetyFlatten` resolves
to `Flatten → SuccessShadow`, which writes "shadow flatten" to the log but
does nothing real, while `ApplyShadowFlatten` clears `_shadowPosition` to
flat. Next tick, `CurrentPosition()` still sees the live broker position and
the loop repeats every Worker tick.

The startup path already handles this correctly with
`recovery_action_required` (`ExecAssistantRuntime.cs:718-724`), but that
check fires only at `OnRun`. A position opened *during* a shadow run is not
handled.

**Suggested:** in shadow mode, treat any non-zero `LivePosition` as an
operator error: log `recovery_action_required` once per signature change and
*do not* reconcile through the coordinator until the operator flattens
manually or restarts in live mode.

---

## Medium

### F-12 · `_processedControlDigests` may grow unbounded across a long session
**Severity:** Medium · **Category:** Memory / Maintainability

`ExecAssistantRuntime.cs:107`, `ExecAssistantRuntime.cs:445-456`

`_processedControlDigests` accepts every control id ever seen and is only
ever pruned by the checkpoint write
(`_processedControlDigests.Keys.TakeLast(100)`) for *persistence*, not for
in-memory state. A long-running session that receives thousands of control
messages will retain all of them in the dictionary.

**Suggested:** cap the in-memory dictionary at the same 100 entries or
prune oldest entries after each insert.

---

### F-13 · Multi-position recovery silently picks the first bound position
**Severity:** Medium · **Category:** Logic / Restart

`QuantowerOrderGateway.cs:427-432`

```csharp
Position live = FindBoundPositions()
    .FirstOrDefault(p => p.Id == position.PositionId)
    ?? FindBoundPositions().FirstOrDefault();
```

If multiple positions exist on the bound pair (broker-side aggregation
misconfigured, or two strategy instances briefly running on the same pair),
`ClosePosition` runs against the *first* enumerated one. The runtime
`Reconcile` path will detect that "the position" did not flatten and may
re-issue. Net result: the wrong position may be touched while the right one
stays open.

`AGENTS.md:47-48` explicitly says "The account/symbol pair should be
dedicated while trading is enabled" — so this is operator-error territory —
but the silent fallback is unsafe. `LivePosition`'s `ambiguous = positions
.Length > 1` is detected once at startup but not on every Worker tick.

**Suggested:** during `Flatten`, if `FindBoundPositions().Length > 1`, log
`ambiguous_position_flatten` and either close all of them or refuse with
`RequiresFlatten = true` so the coordinator latches into `Halting`.

---

### F-14 · `_baselineFailureIds` snapshot is reset on every `AcceptDirective` but never on `EnterRecoveryProtected`
**Severity:** Medium · **Category:** Logic / Restart

`ExecutionCoordinator.cs:155-162`, `ExecutionCoordinator.cs:510-516`

`AcceptDirective` snapshots `existingHeldFailureIds` so that pre-existing
held failure objects don't immediately trigger LF/HF flatten on activation.
`EnterRecoveryProtected` does not — recovery path re-uses whatever
`_baselineFailureIds` was last set to (from the prior session, which is
empty after `ResetForRun` and possibly from the recovered `AcceptDirective`
call in `RecoverAtStartup` which passes `Array.Empty<int>()`). Result: after
a restart with a profitable recovered position, the very first
`FailureHeld` transition on the *opposing* side will flatten — exactly the
"old candidates / rails / LF/HF baselines never resume" rule of
IMPLEMENTATION_PLAN.md:209-210 but applied in a way that could exit a
healthy recovery on the first new opposite failure rather than letting
the recovered breakeven/HARD_TP do their work.

**Suggested:** in `RecoverAtStartup`, after switching to
`RecoveryProtected`, capture the current `evidence.HeldFailureObjects()` ids
into `_baselineFailureIds` just as `AcceptDirective` does. Or have
`EnterRecoveryProtected` accept a baseline list as an argument.

---

### F-15 · `LogFillQuality` fallback by side can match the wrong submission
**Severity:** Medium · **Category:** Telemetry

`ExecAssistantRuntime.cs:860-870`

When the fill event has no `OrderId` (or `_submissions` was keyed under a
different id), the fallback selects the most recent submission with a
matching direction. If two entries (e.g., the base and a quick add) were
both submitted within seconds and the broker delivered fills out of order,
fill telemetry can be attributed to the wrong intent, polluting the
`detection_drift_points` / `transport_slippage_points` distributions used to
diagnose execution quality.

**Suggested:** prefer matching `trade.OrderId` to the submission's stored
broker `OrderId`; only fall back to side-matching when nothing else matches,
and log a `fill_quality_fallback_match` event when the fallback is used.

---

### F-16 · `PollDirective` runway check uses *current* market for an activation event that may have just been written for a future window
**Severity:** Medium · **Category:** Logic / Schema-Conformance

`ExecAssistantRuntime.cs:384-400`

```csharp
ExecutableMarket market = SnapshotMarket(DateTime.UtcNow);
if (directive.TargetMode == TargetMode.HardTp && market.IsValid)
{
    double executable = market.Executable(directive.Direction);
    bool noRunway = ...;
    if (noRunway) { rejected; return; }
}
```

If `directive.NotBefore` is in the future and price is currently beyond the
target, the directive is rejected at write time — even though the runway
check should arguably be deferred until the `Armed` state is entered. This
contradicts `DESIGN.md:309` ("`HARD_TP` directives with no executable runway
at acceptance") only if "acceptance" means *now*, not "at the moment the
window opens." Worth confirming. Either way, the rejected event message
should include `NotBefore` so the operator can see whether to re-dispatch
after the window opens.

**Suggested:** if `NotBefore > now`, skip the runway check at activation;
re-check in `Tick` when transitioning from `Waiting → Armed`.

---

### F-17 · `Directory.CreateDirectory` runs from `RuntimeCheckpointStore`/`RuntimeEventLog` constructors on the UI thread
**Severity:** Medium · **Category:** Concurrency

`RuntimeCheckpoint.cs:32-35`, `RuntimeEventLog.cs:33-35`

Both constructors call `Directory.CreateDirectory`. This is fast but does I/O
on whichever thread called `OnRun` (Strategy thread, not the dedicated event
log thread). For default `%USERPROFILE%\Documents\...` paths this is
negligible, but a misconfigured `EventLogPath` pointing at a slow network
share would block strategy start.

**Suggested:** defer the directory creation until the writer thread's first
flush; surface failures to the existing `_errorSink` path.

---

### F-18 · `JsonNamingPolicy.SnakeCaseLower` is applied only to `RuntimeCheckpointData` — event log dictionary keys bypass it
**Severity:** Medium · **Category:** Maintainability / Telemetry

`RuntimeEventLog.cs:50-65` writes `payload` as `Dictionary<string, object>`.
`System.Text.Json` does not transform dictionary keys via
`PropertyNamingPolicy`. The current keys
(`"ts_utc"`, `"mono_us"`, `"event"`, plus all `Write(...)` field tuples) are
manually snake_case, so the output is consistent — but a future contributor
who adds a tuple like `("orderId", x)` will break the on-disk convention
silently.

**Suggested:** add a comment to `Write(...)` documenting the snake_case
convention, or run keys through `JsonNamingPolicy.SnakeCaseLower.ConvertName`
explicitly before insertion.

---

### F-19 · `MeanStd` and the four z-score firings recompute window stats on every sample
**Severity:** Medium · **Category:** Performance

`ExecutionEvidenceEngine.cs:193-209`, `ExecutionEvidenceEngine.cs:747-769`

Each `Process(...)` call computes four separate mean/std passes across the
in-window samples (one selector per pass), each enumerating the full
`_samples` linked list. At a 1 Hz sample with 30s lookback, this is ~120 ops
per tick — negligible. At higher sample rates (250ms `Book Sample (ms)` is
allowed by the input parameter, capped at 250ms minimum) this becomes 480
ops × 4 selectors. Still tiny in absolute terms, but a running incremental
sum/sum-of-squares with eviction would be O(1) per sample. Mostly noted for
robustness if the operator dials sample rate down (e.g., 250ms with a 300s
lookback = 1200 samples per pass × 4 passes per tick).

**Suggested:** maintain four running pairs (sum, sumSq) updated on
`_samples.AddLast` / `_samples.RemoveFirst`. Reuse in `MeanStd`.

---

### F-20 · `_pendingRetest` is cleared inside `ProcessEvidence`'s late-arrival check but the pending state is never timed out
**Severity:** Medium · **Category:** Logic

`ExecutionCoordinator.cs:556-561`, `ExecutionCoordinator.cs:666-690`

When `EvaluateDirectConversion` arms a `_pendingRetest`, completion is
gated on `band.IsLiveRail` and quote returning within 20 ticks. If price
never returns and the rail eventually fails, `TryCompleteDirectRetest`
returns null (silently), and the pending state persists indefinitely. The
band-failed transition does not explicitly clear `_pendingRetest`.

This is largely benign — once the band is no longer `IsLiveRail`, the
pending entry stays dormant forever — but the only path that clears it is
"the engine evicts the band entirely and `evidence.FindBand` returns null."
In long sessions with many candidates that's eventual, but it would be
cleaner to clear on first detection of `band.State == Failed`.

**Suggested:** in `TryCompleteDirectRetest`, also clear `_pendingRetest`
when `band.State == EvidenceState.Failed`.

---

## Low

### F-21 · `ConvertLevels` re-applies the 30-level truncation already set on `_domParameters`
**Severity:** Low · **Category:** Maintainability

`ExecAssistantRuntime.cs:1006-1012` plus `ExecAssistantRuntime.cs:178-185`.
Redundant `.Take(30)` after `LevelsCount = 30` on `_domParameters`. Harmless
but worth a one-line cleanup or a comment that it's defensive.

### F-22 · `RuntimeCheckpointStore.Save` may leak a `.tmp` file on crash
**Severity:** Low · **Category:** Robustness

`RuntimeCheckpoint.cs:51-61`. If the process dies between `WriteAllText`
and `File.Move`, a `.tmp` file is left behind. `Load` ignores it, so no
correctness issue, but accumulating debris over months matters on slow
disks. **Suggested:** delete any pre-existing `<path>.tmp` at start of
`Save`, or sweep on `Load`.

### F-23 · `OperatorGuide` mentions a `ConfigureAwait`-style stop sequence but `Shutdown` is fully synchronous
**Severity:** Low · **Category:** Maintainability

`OPERATOR_GUIDE.md:142-144`: "Stopping the strategy cancels runtime entry/add
orders. It intentionally leaves accepted target/breakeven protection
attached to an open position." Implementation matches (`CancelEntryOrdersOnStop`
only matches `:BASE:`/`:ADD:`). Just confirm the doc reads correctly for a
future reader; the implementation is right.

### F-24 · `ResolveAccountAndSymbol` short-circuits on `RuntimeSymbol == null` without disposing the partially-initialized fields
**Severity:** Low · **Category:** Robustness

`ExecAssistantRuntime.cs:149-156`. If `ResolveAccountAndSymbol` fails, `Stop()`
is called but the fields (`_events`, `_evidence`, etc.) are still null at this
point, so it's harmless today. Future contributors moving initialization
above `ResolveAccountAndSymbol` would introduce a leak.

### F-25 · `Order_Updated` handler doesn't guard against null `Symbol`/`Account`
**Severity:** Low · **Category:** Robustness

`ExecAssistantRuntime.cs:1204-1209`: `SameBoundPair(order.Symbol, order.Account)`
handles null on either side. ✓

### F-26 · `SubmissionTelemetry` is `private sealed class` with public mutable fields
**Severity:** Low · **Category:** Style

`ExecAssistantRuntime.cs:1366-1374`. Internal-only DTO; reasonable. Same for
`BrokerEvent`. Worth a comment or `record` migration eventually.

### F-27 · `RuntimeSelfTests.EvidenceEngineTests` asserts behavior on a synthetic book that does not exercise consumed-source (only Lean)
**Severity:** Low · **Category:** Testing

`RuntimeSelfTests.cs:31-46`: validates `EvidenceSource.Lean` rail ownership
but never asserts `EvidenceSource.Consumed`. The coordinator self-test then
synthesizes a `Consumed` transition directly (`ConsumedDemand` helper). The
engine path that *produces* `Consumed` (adverse displacement on a candidate)
is not exercised. Worth adding before live trading.

### F-28 · `DirectiveContracts.RequireConstant<T>` boxes value types
**Severity:** Low · **Category:** Performance

`DirectiveContracts.cs:529-533`. Negligible at directive-acceptance frequency
(< 1 Hz). Noted only because the rest of the file is allocation-conscious.

### F-29 · Schema vs. parser drift: `target.reference` is optional in the schema but `OptionalString` allows empty/null with no min length
**Severity:** Low · **Category:** Schema-Conformance

`trade-directive-v1.schema.json:438-442` defines `reference` as
`"type": "string", "maxLength": 128"`. The parser
(`DirectiveContracts.cs:329-351`) allows `null`/absent (schema does require
the property to be a string if present, but does not require min length).
`OptionalString` returns null when absent; that matches. ✓

### F-30 · `MonitoringConnectionsIds` returns empty array if `RuntimeSymbol == null`
**Severity:** Low · **Category:** API-Contract

`ExecAssistantRuntime.cs:144-147`. Quantower may interpret an empty list as
"no connection dependency." Acceptable because `OnRun` fails closed if the
symbol is null, but a missing connection while the strategy is "started but
not running" could be misleading in the UI.

---

## Info

### F-31 · The "one resolution epoch → one intent" rule is enforced by `_usedRootObjectIds.Add(resolution.RootObjectId)` inside `CreateEntryIntent`, BEFORE quantity guard
**Severity:** Info · **Category:** Logic

`ExecutionCoordinator.cs:730-748`: when `quantity` ends up zero (e.g., add
would exceed `MaxPositionQuantity`), `_usedRootObjectIds` is *already
populated* and the return is `null`. The root is then permanently retired
even though no intent was issued. This is conservative (no risk of double-
submitting) but means a subsequent identical resolution must wait for a
fresh root id. Probably intended; documenting for future readers.

### F-32 · `EvidenceEngineSettings` re-enforces minima inside both the constructor's defaults *and* `NewEvidenceEngine`'s `Math.Max` clamps
**Severity:** Info · **Category:** Maintainability

`ExecutionEvidenceEngine.cs:122-135` and `ExecAssistantRuntime.cs:1297-1311`.
Two layers of clamping with slightly different floors (e.g., engine accepts
`ClusterSeconds = 1`, runtime clamps to `>= 1`; engine accepts `ConfirmSeconds
>= 0`, runtime clamps to `>= 0`). Consistent today; would drift if one is
edited without the other.

### F-33 · `_directive` is read after `MarkError`/`SafetyFlatten` from many call sites without a guard
**Severity:** Info · **Category:** Robustness

After `MarkError()` runs, `_directive` is still set (only `_pendingEntryIntent`
is cleared). Subsequent `Tick()`/`OnPositionChanged()` calls early-out on
`IsTerminal(State)`, so `_directive` is not dereferenced. ✓ holds today;
fragile to refactor.

### F-34 · `IPriceTrigger.IsBelow` is derived from `direction` text but stored as redundant bool
**Severity:** Info · **Category:** Maintainability

`DirectiveContracts.cs:51-55` and `:354-370`. The bool is set from
`text == "below"`, and `text` is `RequireConstant`'d to the expected direction
already. The bool could be derived from the directive direction at use time,
removing duplicated state.

### F-35 · `ExecAssistantRuntime.csproj` sets `UseWindowsForms = true` but no `System.Windows.Forms` reference is used in the codebase
**Severity:** Info · **Category:** Build

Probably inherited from a Quantower strategy template. Drop unless something
in the Quantower BL requires the Forms SDK at runtime (it likely doesn't for
Strategy hosts).

---

## Cross-cutting Observations

1. **Mode flag is captured at gateway construction.** `TradingEnabled` is
   read into `QuantowerOrderGateway._tradingEnabled` once. Quantower
   `InputParameter` values can change at runtime via the strategy settings
   panel without restart. The `Trading Enabled` flag in particular is the
   safety cut line — operators may *intend* to flip it mid-session.
   Behavior in that case: changes don't take effect until restart. Worth
   documenting in `OPERATOR_GUIDE.md` or wiring the gateway to read the
   live flag.

2. **Telemetry vs. operational events are not partitioned.** All events
   land in one JSONL stream. Operators reading `events.jsonl` to diagnose
   one trade have to filter by `directive_id`. A rotating per-directive
   sub-log (or at least one log per session day) would scale better. Not a
   bug, an observation.

3. **No backpressure on the broker event queue.** `_brokerEvents` is an
   unbounded `ConcurrentQueue<BrokerEvent>`. A pathological broker that
   fires thousands of `order_updated` per second during a halt-resume
   storm could OOM the strategy. The event log queue has a cap and a drop
   counter (`RuntimeEventLog.QueueCapacity = 100000`); broker queue has
   no such guard.

4. **The "evidence engine is a copy of LevelLedger" invariant is asserted
   in DESIGN.md and AGENTS.md but the engine has no test-level proof of
   parity** with the LevelLedger sister project. IMPLEMENTATION_PLAN.md:9
   names "Replay the June fixtures through the pure coordinator" as a
   gate; the only fixture replay present is `RuntimeSelfTests`, which uses
   synthetic books, not captured June L2. If the parent project's fixtures
   ever change shape, divergence will be silent.

---

## What I did not review

- `research/export_book_jsonl.py` — out of scope per AGENTS.md:49-51 ("a
  narrow bridge, not a runtime data source").
- The actual Quantower BL DLL behavior for `Order.TotalQuantity` vs.
  `RemainingQuantity` modify semantics — flagged as F-05 to verify in
  `api-recon/`.
- LevelLedger parity (would require reading the sister project; out of
  scope for this pass).
- Performance profiling of the unsafe pixel-write path — not present in this
  project (it's a Strategy, no `OnPaintChart`).
