# ExecAssistantRuntime Code Review Response

Reconciliation for `CODE_REVIEW.md`. This pass prioritizes execution safety,
shutdown correctness, broker-order reconciliation, and telemetry integrity.

## Decisions on the review's open questions

1. **F-01 is not dead code.** Candidate-backed supported reclaims may execute
   after the four-second fast path while their support candidate is still
   active. If that same candidate later confirms adversely,
   `ExecutionEvidenceEngine.UpdateCandidates` emits an opposite-side
   `Consumed` rail with the candidate's original ID. The branch is therefore
   the immediate reverse path described by the design. A code comment and
   self-tests now preserve this non-obvious lineage invariant.
2. **`max_base_reentries` counts submitted base attempts.** The normative
   contract says attempts, not fills. Rejections and zero-fill timeouts now
   consume an attempt slot, and a fresh root formed after the prior submission
   is required. This bounds a rejection storm.
3. **Live `HARD_TP` completion remains broker-driven.** The resting close order
   fills first; position reconciliation then transitions the directive to
   `Completed`. Calling a coordinator runway method would issue a redundant
   flatten. The unused `HardTargetReached` method was removed, and tagged TP
   trades now emit `hard_target_fill` before flat reconciliation.

## Finding reconciliation

| Finding | Status | Resolution |
| --- | --- | --- |
| F-01 | Disagreed / documented | Candidate-fast-path lineage makes the same-ID adverse `Consumed` transition reachable. Added invariant comment and tests. |
| F-02 | Fixed | Pending reclaim completion now verifies that captured base/add intent still matches coordinator and position state. |
| F-03 | Fixed | Shutdown stops the timer with callback notification, waits up to five seconds, and no longer nulls the event-log reference under an in-flight worker. |
| F-04 | Fixed | Non-finite floating-point event values are normalized to JSON `null`; events remain standards-compliant JSON instead of being dropped or emitting named-number strings. |
| F-05 | Fixed / API verified | Protection equality uses `RemainingQuantity`. Quantower v1.145.9's `ModifyOrderRequestParameters(IOrder)` initializes `Quantity` from `RemainingQuantity`, so the modify request continues to pass the desired remaining close size. |
| F-06 | Fixed narrowly | Protection adoption now considers only orders with remaining quantity and active statuses (`Opened`, `PartiallyFilled`, `Inactive`). A stale terminal order no longer enters the modify/flatten path. Intent IDs do not affect adoption because protection lookup is role-based. |
| F-07 | Fixed | Blank-ID submissions are rebound to broker IDs from order tags. Timeout cancellation falls back to the intent token in the `EA:` tag, waits for terminal reconciliation before re-arming, and fails closed if the accepted order cannot be located/cancelled or cancellation never reconciles. |
| F-08 | Covered by F-05; no extra debounce | Quantity shrink already enters terminal remainder-flatten handling. Growth must update protection immediately. Same-size/price repeats short-circuit in the gateway; F-05 restores that guard after partial fills. Broker-specific rate behavior remains a demo validation item. |
| F-09 | Fixed | Base attempts increment when an intent is created, not when a fill is observed. Exhaustion is tested. |
| F-10 | Fixed | Subscription state now retains `Order` references, allowing shutdown to detach every subscribed instance even after it left `Core.Instance.Orders`. |
| F-11 | Fixed | Shadow position state always remains synthetic. Any real bound position pauses worker processing and logs `recovery_action_required` once per position signature until the operator flattens it. |
| F-12 | Fixed | Processed control IDs and digests are capped together at the checkpoint history size of 100. |
| F-13 | Fixed | Live multi-position ambiguity is checked each worker tick. Safety flatten closes every bound position and logs the ambiguity rather than selecting an arbitrary first position. |
| F-14 | Not applicable | `ProcessEvidence` returns immediately in `RecoveryProtected`; rebuilt LF/HF evidence cannot act there, so failure baselines are not consulted during recovery. |
| F-15 | Fixed | Submission matching prefers broker order ID and exact intent tag. Side-only matching remains last-resort and emits `fill_quality_fallback_match`. |
| F-16 | Design retained | DESIGN explicitly rejects no-runway `HARD_TP` at acceptance, so current acceptance-time market remains authoritative even for a future window. Rejection telemetry now includes `not_before`. Deferring this would be a contract change. |
| F-17 | Fixed for constructors | Event-log directory creation moved to its writer thread. Checkpoint directory creation is deferred until `Save`. |
| F-18 | Fixed | Event field names are normalized through `SnakeCaseLower` before insertion. |
| F-19 | Deferred | Current bounded window cost is negligible; no execution correctness benefit justifies incremental-stat complexity in this pass. |
| F-20 | Already correct | `TryCompleteDirectRetest` clears pending state when `!band.IsLiveRail`; `Failed` bands are explicitly not live rails. |
| F-21 | No change | The second 30-level cap is a harmless defensive boundary at the adapter conversion point. |
| F-22 | Fixed | A stale checkpoint `.tmp` is removed before the next atomic save. |
| F-23–F-26 | No action | Informational or already-safe as reviewed. |
| F-27 | Fixed | Evidence self-tests now exercise adverse candidate consumption and assert preservation of the candidate lineage ID. |
| F-28–F-35 | No action | Low-value or informational; none changes the live execution contract in this pass. |

## Additional fix found during reconciliation

`Worker` processes a book sample before its final coordinator `Tick`. As a
result, expiry and pre-entry invalidation enforced only in `Tick` left a narrow
interval where evidence could authorize an entry first. `ProcessEvidence` now
enforces both guards before consuming transitions.

## Validation

- `dotnet build`: succeeds with zero warnings and zero errors.
- `RuntimeSelfTests.RunAll`: passes through a standalone reflection runner.
- Runtime event-log test: a `double.NaN` field serializes as JSON `null` and
  the resulting line parses successfully with `System.Text.Json`.
- Quantower broker-specific partial-fill, modify, cancel, and recovery behavior
  remains a demo-account validation boundary as documented in `OPERATOR_GUIDE.md`.

## Still open beyond this pass

- Broker-event queue backpressure.
- Captured-session LevelLedger parity replay.
- Incremental book-stat optimization (F-19), only if profiling supports it.
- Live/demo validation of partially filled protection modification semantics.

---

# Reviewer Follow-up (Second Pass)

Verified each claimed fix against the actual diff. Conclusions are based on
reading the modified files; broker-touching paths remain unverifiable until
demo runs.

## Findings I retract

### F-01 — Author is correct; my original claim was wrong
I asserted `sameCandidateConsumed` was unreachable because "each candidate is
one-shot." I missed that *the same candidate id is reused on its derived
band* (`Band.Id = candidate.Id` in `UpdateCandidates`). For a candidate-backed
supported_reclaim, `SupportObjectId` is the still-active candidate's id; if
that candidate later confirms adversely, the engine emits a band with the
*same id*, opposite side, `Consumed` source. `EvaluateBaseStop`'s
`sameCandidateConsumed` matches exactly that lineage. It is the immediate
reverse path described in DESIGN.md:1006-1015, and it really only applies to
the candidate-backed fast path — for direct_conversion or confirmed-support
reclaim, the support id is already a band id and cannot be reused, so the
branch is structurally unreachable there *by design*, not by oversight.

The added `IsCandidateSupportConsumed` helper plus the new
`consumed rail preserves candidate lineage id` and
`candidate-backed reclaim immediate reverse lineage` self-tests pin this
invariant. Accept.

### F-20 — Already correct
I missed that `IsLiveRail` excludes `EvidenceState.Failed`, so the existing
`!band.IsLiveRail` short-circuit in `TryCompleteDirectRetest` already clears
`_pendingRetest` when the rail fails. Author is right; no change needed.

## Fixes I verified land correctly

- **F-02** — `PendingIntentMatchesState` is consulted before
  `TryCompletePendingReclaim` proceeds; an `IsAdd=true` pending no longer
  fires against a flat-and-Armed coordinator.
  ([ExecutionCoordinator.cs:645-700](ExecAssistantRuntime/ExecutionCoordinator.cs))
- **F-03** — `Timer.Dispose(callbackDone)` is awaited up to 5 s; `_events` is
  no longer nulled, and `RuntimeEventLog.Write` short-circuits on
  `_stopping`, so an in-flight Worker survives shutdown with at worst silent
  log drops. The `_shutdownStarted` interlock prevents reentrant disposal.
  ([ExecAssistantRuntime.cs:1428-1462](ExecAssistantRuntime/ExecAssistantRuntime.cs))
- **F-04** — `NormalizeValue` collapses non-finite `double`/`float` to JSON
  `null`. `fill_quality` now survives NaN inputs as standards-compliant JSON.
  ([RuntimeEventLog.cs:134-141](ExecAssistantRuntime/RuntimeEventLog.cs))
- **F-05** — Both `EnsureHardTarget` and `EnsureBreakeven` use
  `RemainingQuantity` for the "already correct" comparison.
  ([QuantowerOrderGateway.cs:269-275, 363-369](ExecAssistantRuntime/QuantowerOrderGateway.cs))
- **F-06** — `FindProtection` requires `IsWorkingOrder` (status in
  `Opened`/`PartiallyFilled`/`Inactive` and remaining > 0); a stale terminal
  protection no longer enters the modify/flatten path.
  ([QuantowerOrderGateway.cs:568-579](ExecAssistantRuntime/QuantowerOrderGateway.cs))
- **F-07** — `CancelEntryOrder(orderId, intentId)` falls back to tag matching
  (`EndsWith($":{token}")`). `BindSubmissionToOrder` rebinds blank-id
  submissions to the broker id as soon as a tagged event arrives. Timeouts
  fail closed (`MarkError`) if the order is unresolvable after the cancel
  grace window. Good.
  ([QuantowerOrderGateway.cs:98-131](ExecAssistantRuntime/QuantowerOrderGateway.cs),
   [ExecAssistantRuntime.cs:976-1018](ExecAssistantRuntime/ExecAssistantRuntime.cs))
- **F-09** — `_baseAttempts++` moved to `CreateEntryIntent`. Both `<=` rearm
  gate and `>` exhaustion gate (in `OnOrderAttemptResult` and the next
  `CreateEntryIntent`) terminate after the configured attempt budget. The
  retry-exhaustion self-test confirms it. `_freshRootAfterUtc` is moved to
  intent creation too, which correctly tightens "fresh root" semantics for
  retries after rejection.
  ([ExecutionCoordinator.cs:786-810](ExecAssistantRuntime/ExecutionCoordinator.cs))
- **F-10** — Order-subscription bookkeeping switched to
  `Dictionary<string, Order>`; `Unsubscribe` enumerates a captured snapshot
  of those refs, not `Core.Instance.Orders`, so orders that left the live
  collection still get their `Updated` handlers detached.
  ([ExecAssistantRuntime.cs:1323-1336](ExecAssistantRuntime/ExecAssistantRuntime.cs))
- **F-11** — `ShadowLivePositionRequiresAction` halts worker processing on
  shadow-vs-live mismatch and signature-dedupes the
  `recovery_action_required` event. Correctly bypassed in `OnRun` so the
  startup signal still fires.
  ([ExecAssistantRuntime.cs:1199-1226](ExecAssistantRuntime/ExecAssistantRuntime.cs))
- **F-12** — `RememberProcessedControl` keeps `_processedControlOrder` (a
  FIFO) capped at 100 and prunes the digest dictionary in lockstep.
- **F-13** — `Flatten` iterates every bound position, ordering the
  intent-named one first; emits `ambiguous_position_flatten`. Worker also
  preemptively `SafetyFlatten`s on ambiguity in live mode.
- **F-14** — `ProcessEvidence` early-outs on `RecoveryProtected`; verified.
- **F-15** — `TryFindSubmission` is the right shape (exact id → tag → side
  fallback with an explicit `fill_quality_fallback_match` event). The side
  fallback is structurally safe because TP/BE close-side strings are the
  opposite of the entry direction string, so a TP fill cannot accidentally
  be attributed to its entry intent.
- **F-17, F-18, F-22, F-27** — Verified.

## Author's bonus fix is real

> "Worker processes a book sample before its final coordinator `Tick`."

Confirmed. The new guards at the top of `ProcessEvidence`
([ExecutionCoordinator.cs:244-256](ExecAssistantRuntime/ExecutionCoordinator.cs))
move the expiry and pre-entry invalidation checks ahead of the transition
loop. Without them, a transition fired during the same book sample that
crossed `ExpiresAt` could authorize an entry that `Tick` would then have
been one call too late to block. Good catch.

## New observations introduced by this pass

These are *not* regressions; they're consequences of the new behavior worth
noting.

### N-01 · `entry_cancel_reconciliation_timeout` leaves a working order at the broker
**Severity:** High · **Category:** Robustness

`ExecAssistantRuntime.cs:991-1003`. When the cancel was accepted but the
broker never reconciled within 30 s, the runtime calls `MarkError`, removes
the submission, and stops trying. The order may still be live at the broker.
This is the intended fail-closed behavior, but the operator must intervene
manually (cancel via Quantower UI, or send `FLAT`). Worth surfacing in
`OPERATOR_GUIDE.md` next to the existing recovery-action guidance so an
operator knows that `entry_cancel_reconciliation_timeout` /
`entry_order_unresolved` mean "go look at the broker DOM."

### N-02 · `ShadowLivePositionRequiresAction` blocks every Worker path including FLAT
**Severity:** Medium · **Category:** Operator UX

In shadow mode with a live position present, the entire Worker
returns early *before* `PollControl`. The operator cannot use `FLAT` to
clean up — they must flatten via the Quantower UI or restart in live mode.
This is internally consistent (a shadow strategy shouldn't be sending
broker orders), but if the live position is *unrelated* to anything the
strategy did and the operator was hoping a `FLAT` would tear it down, it
won't. Document or move `PollControl` above the gate.

### N-03 · `IsWorkingOrder` whitelist may be incomplete for the configured broker
**Severity:** Medium · **Category:** API-Contract

`QuantowerOrderGateway.cs:574-579` accepts `Opened`, `PartiallyFilled`,
`Inactive`. Quantower's `OrderStatus` enum also includes `Pending`
(broker-side acknowledgement in flight). A protection order in `Pending`
state would be considered "not working" by `FindProtection` and the runtime
would attempt to place a duplicate. Worth checking the v1.145.9 enum in
`api-recon/` and adding any in-flight states.

### N-04 · `TryFindSubmission` is O(n) per broker event
**Severity:** Low · **Category:** Performance

Tag-fallback path `_submissions.FirstOrDefault(pair => HasIntentTag(...))`
iterates the dictionary on every order/trade event. n is small (typically
1-5 in-flight submissions) so this is fine in practice. Note if the
submission cap ever grows.

### N-05 · `_subscribedOrders` replacement path detaches the prior handler
**Severity:** Info · **Category:** Robustness

The new `SubscribeOrder` swaps a prior `Order` reference if the same id
re-appears with a new instance. The replacement detaches the prior
handler under the lock. Quantower's typical lifecycle doesn't recycle ids,
so this is defensive but cheap. ✓

### N-06 · `Shutdown` may leak the `ManualResetEvent` if the worker callback never returns
**Severity:** Low · **Category:** Robustness

`ExecAssistantRuntime.cs:1438-1454`. When `WaitOne(5s)` times out, the
handle is intentionally not disposed so the Timer can still signal it. If
the callback never returns, the handle is leaked for the rest of the
process lifetime. Acceptable for a strategy that has just decided shutdown
is overdue, but worth a comment-confirmed accept.

### N-07 · `Worker`'s ambiguous-position branch loops SafetyFlatten every tick until reconciled
**Severity:** Low · **Category:** Telemetry noise

While the broker is reconciling the safety flatten, every Worker tick will
re-detect ambiguity, write `ambiguous_position_detected`, and call
`SafetyFlatten` again. Each repeats `_flattenDisposition` assignment but the
gateway will keep trying to close already-closing positions; broker
rejections produce log noise. Consider gating on `State !=
RuntimeExecutionState.Halting` (the early-return at line 240 of the diff
already checks Halting in some paths — extend to this branch).

## Items I left open in the original review

| Item | Status |
| --- | --- |
| F-08 | Author argument accepted (F-05 restores the short-circuit after partial fills; no debounce needed). |
| F-19 | Deferred as agreed. |
| F-21, F-23–F-26, F-28–F-35 | Informational; no action accepted. |
| Open Question 3 (`HardTargetReached`) | Resolved by removal of the unused method and the new `hard_target_fill` telemetry emitted by `DrainBrokerEvents` when a `:TP:`-tagged trade arrives. ([ExecAssistantRuntime.cs:880-894](ExecAssistantRuntime/ExecAssistantRuntime.cs)) |
| Cross-cutting: `TradingEnabled` captured at gateway construction | Not addressed in this pass; documented behavior. Worth adding to `OPERATOR_GUIDE.md` ("restart the strategy after toggling Trading Enabled"). |

## Summary

The blocker-level findings (F-02, F-03, F-04) have correct, narrow fixes.
F-09's retry semantics are now consistent and tested. F-07's blank-broker-id
recovery is the most complex change and looks structurally sound; the
fail-closed behavior on unresolvable orders is the right default but
deserves the operator-guide pointer N-01 calls out. F-01 was my error and
I retract it.

Remaining live-validation risks (broker partial-fill modify semantics,
`OrderStatus.Pending` handling, the cancel-reconciliation timeout outcome)
are all surface-able only on a demo account.

---

# Author Follow-up to Second Pass

- **N-01 hardened and documented.** Unresolved submissions are retained instead
  of being forgotten, tagged cancellation retries continue every five seconds,
  new directives are rejected until reconciliation, and `ERROR` positions are
  safety-flattened if a late fill appears. Operator guidance now identifies both
  reconciliation events as broker-DOM checks.
- **N-02 documented.** Shadow/live mismatch intentionally pauses before control
  polling; shadow `FLAT` cannot touch the broker. The operator guide now says to
  flatten through Quantower.
- **N-03 does not apply to v1.145.9.** The extracted enum contains
  `Unspecified`, `Opened`, `PartiallyFilled`, `Filled`, `Cancelled`, `Refused`,
  and `Inactive`; it has no `Pending` member. The current active-status filter
  covers every nonterminal state exposed by this installed API except
  `Unspecified`, which is deliberately not adopted as valid protection.
- **N-04 accepted.** Submission cardinality is deliberately small; no index is
  warranted.
- **N-05 acknowledged.** No change.
- **N-06 comment expanded.** A permanently stuck callback can intentionally
  leak one wait handle for the remaining process lifetime; retaining a handle
  that `Timer` may still signal is safer than disposing it after timeout.
- **N-07 was already gated.** The ambiguous-position branch requires
  `State != Halting`, so subsequent worker ticks do not resubmit the safety
  flatten while reconciliation is in progress.
- **Start-captured mode made explicit in code.** The runtime now snapshots
  `TradingEnabled` once per run and uses that value everywhere, matching the
  gateway. The operator guide requires a restart after changing the setting.

Follow-up validation: the project builds with zero warnings/errors, the full
runtime self-test suite passes, and the non-finite event serialization probe
continues to pass against the deployed DLL.
