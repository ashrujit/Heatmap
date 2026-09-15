# Risk Monitoring Across Observation Gaps

## Incident

NQ profile, MNQU6 execution / NQU6 evidence, 2026-09-10 ET:

- 12:31:53: A sample-health gap suspended the scale observer, but a direct
  Lean-supply probe at 29187.00-29187.75 still passed admission.
- 12:31:58: Two contracts filled short at 29182.50. The submit call had taken
  about 4.84 seconds. Recovery then replaced the LL engine and its identity
  epoch, detaching the filled root from its failure detector.
- 12:42:48: A later Consumed supply at 29186-29188 failed. Exact-identity checking
  correctly recognized it as a different owner, but the original owner's health
  remained unknown with no automatic exit. The original detector was gone, so
  its counterfactual failure time cannot be inferred from this log.
- 12:44:09: Operator FLAT closed two at 29201.25, 75 ticks adverse to entry.
  There were no adds or automatic root-close submissions.

The installed 5b50749 build was running: the logs contain its root binding and
`non_owner_failure_ignored` audit. This was not a failure to load the new DLL.

## Correction

Observation lifetime and ownership identity are now separate. Rewarming resets
LL book statistics, unfinished candidates, grey/failure objects and pending
failure timers, but keeps owned/failed rails and monotonically allocated rail
IDs. The source epoch changes only with a real strategy run reset, not routine
observation recovery. Sample sequence is monotonic across warmups.

The runtime detects sample gaps before processing the next source sample or
admitting a new root. Policy, reservation and pre-submit gates reject a suspended
or stale observer. Executable-quote validity is checked using the current clock
after DOM processing rather than its earlier start time.

The root ledger consumes full LL state during warmup, including when no valid
executable quote is available. Typed failure retains its exit obligation through
the existing reconciliation/close machinery. TEST remains TEST. The established
LL failure-buffer, move-confirmation and time-confirmation settings are unchanged;
unobserved time is not credited to the failure timer. A sufficiently adverse
fresh sample can confirm the existing move-based failure immediately.

Scale recovery clears unfinished episodes and advances observer generation.
Pre-gap proof cannot authorize an add or a later sponsor promotion. Filled active
sponsor health instead uses its exact retained LL members, independent of the
discovery generation. One-behind promotion and weighted BE remain unchanged.

Transient unavailable observations remain unknown health and veto new risk.
Actual loss of the bound identity, absence from a complete snapshot or conflicting
geometry latches `risk_recovery/root_owner_tracking_lost` (or
`sponsor_tracking_lost`) and revokes execution authorization. This infrastructure
exit is not fabricated LL failure. Working roots cancel and partial/late fills
retain the exit obligation; a subsequent attempt needs fresh authorization.

Health-loss/restoration and observation-reset reasons are logged. The optional
root entry-distance cap remains unset. Counter-claim-only entries remain blocked
pending a validated pairing rule. No fixed MAE stop or later-rail adoption was
introduced.

## Limits

No system can observe an excursion while data is absent or guarantee an order
executes while broker connectivity is unavailable. This fix preserves the owner
and resumes its actual failure semantics when usable observations return; it
does not invent a maximum disconnect duration or claim a bounded monetary loss.
Known broker protection continues through its existing independent lifecycle.

Tests use actual pure LL/session code with synthetic owned-rail fixtures and
counterfactual historical replay fills. They are not connected broker validation.
