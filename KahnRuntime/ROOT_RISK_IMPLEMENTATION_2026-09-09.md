# Root Risk Ownership Update

Codex implementation, 2026-09-09. Based on the approved direction in
[the root-risk investigation](../research/kahn/KAHN_ROOT_RISK_RESEARCH_2026-09-09.md).
Built and verified offline, then deployed with explicit user authorization.
See [the release record](RELEASE_2026-09-09.md) for hashes and the cutover boundary.

## Implemented Scope

- Schema-2 probes bind an immutable live LL owner separately from the trigger.
  Identity includes source, evidence epoch, and rail ID. Lean and Consumed origin,
  original coverage, ownership time, qualification time and trigger are retained.
- Complete engine snapshots restore pre-campaign root ownership on the first
  sample after load. They do not replay old entry signals or scale episodes.
  Root health is independent of the forward-development observer's range filter.
- Direct same-side OWN/HOLD requires known live ownership. A HOLD with missing
  ownership history, an unattested external event, or a failed/unknown owner
  cannot authorize a probe. WATCH/GO LIVE freshness remains required.
- **Counter-claim-only probes are blocked in this increment.** LL has no
  established causal-pair export/selector. The runtime reports
  `root_owner_missing` or `root_pair_unresolved`; it does not select the nearest
  rail, merge overlapping supplies, or use a dead opponent/probe box as risk.
  Enabling these entries requires a separately validated causal-pair resolver.
- Actual root-owner failure latches an attempt exit. Neighbor failures are
  logged as non-owner failures, not inferred invalidations. TEST remains
  repair/testing, not failure. LL detection settings are unchanged.
- Root bindings are revalidated before submission and carried through first
  partial fills. Failed/unknown owners request cancellation of working root
  orders. Confirmed failure survives partial fills, cancellation/late fills,
  delayed position reconciliation and pruning of old engine views.
- Unknown health is visible as recovery and blocks new risk without inventing
  a typed failure. Later complete current-epoch evidence may restore known
  health; losing the bound epoch cannot replace it with a reused ID.
- Confirmed flatness clears attempt state. A retry needs a fresh trigger and
  newly valid binding; the same reserved event cannot reopen a position.
  Retry limits, terminal BE behavior and one-behind group sponsorship remain.
- The optional positive JSON field `risk.max_root_entry_distance_ticks` rejects
  entries too far from the owner's adverse edge and is rechecked against the
  submission quote. **It defaults to unset. No ES/NQ values were selected or
  written to profiles.** This is not a hard stop and excludes LL confirmation
  allowance and execution slippage. `root_stop_ticks` is not repurposed.
- Checkpoints/logs expose the binding, owner health/origin, actual root-fill
  distance, configured optional limit, and admission/recovery reasons. The
  existing checkpoint version stays 2; new fields are additive. Dispatcher
  source and control/dispatch contracts did not require changes.

No automatic adoption of later supply near 29516 is included. That would be
new root-tightening policy, not repair of the original owner's identity.
Correct ownership alone can still permit a wide probe while the admission
limit is unset; this update does not claim a fixed maximum loss.

## Verification

- Existing runtime self-tests: 39 checks passed.
- Shared repaired-continuation core: 69 checks passed.
- Campaign session integration: 42 checks passed.
- Broker callback/recovery regressions: 31 checks passed.
- New root ownership/admission regressions: 31 checks passed.
- Checkpoint disk serialization: 3 cases passed, including distinct trigger and
  owner IDs, Consumed origin, entry distance and an explicitly unset limit.
- Python transport suite: 24 tests passed.
- Dispatcher geometry/import tests passed with layout captures. No operator
  command handlers or live forms were invoked.
- KahnRuntime, KahnRuntime.Replay and the linked-source EngineProbe compile in
  isolated Release output directories. No Quantower default output path used.
- `git diff --check` passed.

Strategy DLL: `.tmp/kahn-root-risk-release/runtime/KahnRuntime.dll`.
SHA-256: `9D822988AEEE1407EFA049375AF872A23F5DB82B99CB0703C82558879FBC7ECD`.

## Historical Session Replay

Final artifacts:
`research/out/kahn-root-risk-session-20260909-final/summary.json` and
`manifest.json`. The manifest pins source, test binary, and input data hashes.
All 23 existing selected paths completed; rejected seeds remain in results.

The adapter now reconstructs root ownership from the actual pre-window event
prefix. This hydration is root-only, not replayed scale permission. Missing or
offside owners produce explicit `root_proxy_rejected` output. Entries/fills
remain counterfactual fixture seeds, not claims of fresh live entry permission.

| Selected path | Adds | Last add (ET) | Peak quantity |
| --- | ---: | --- | ---: |
| NQ Sep 3, main surviving second root | 4 | 11:23:14 | 10 |
| NQ Sep 4, main short | 4 | 10:30:59 | 10 |
| ES Sep 3, main long | 2 | 11:23:57 | 6 |
| ES Sep 4, main short | 3 | 11:19:09 | 8 |

The NQ Sep 3 failed first root still exits without adds. Two earlier-control
seeds on that date are rejected: one was already beyond its owner's adverse
edge, and one lacked an admissible live owner. The Sep 1 stress paths retain
their terminal synthetic BE exits. No target/harvest fills or profitability
are inferred, and no live broker behavior was validated.

Intermediate `r1` was incomplete because a rejected proxy seed initially
raised instead of recording rejection. `r2` completed but preceded the final
out-of-order-sample handling fix. Use the `final` directory for verification.

## Release Boundary

Implementation and replay initially changed source, tests and documentation
only. After the user confirmed retired directives and stopped Kahn, the tested
build was installed on 2026-09-09 with verified rollback copies. No strategy
restart, live campaign/control write or order action was performed. Installation
alone does not establish that Quantower has loaded the new assembly or validate
live broker behavior; see the release record before restarting.
