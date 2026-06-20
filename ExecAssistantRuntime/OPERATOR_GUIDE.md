# ExecAssistantRuntime Operator Guide

## Current Live Scope

The deployed strategy supports the settled NQ execution path:

- strict immutable v1 directive and control JSON;
- copied LevelLedger ownership rails, conversion, failure, and LF/HF math;
- market base/add entries;
- base semantic stop and fresh-epoch retries;
- strict fresh-epoch adds;
- weighted-breakeven stop after the first add;
- resting `HARD_TP` limit;
- `CANCEL_DIRECTIVE`, `FLAT`, and fail-closed restart recovery;
- append-only evidence/order/fill telemetry.

`TARGET_DECISION`, `TRAIL_AFTER_TARGET`, and
`TARGET_DECISION_BEFORE_EXTREME` remain observation-only in shadow mode. They
do not create a simulated hard target. With `Trading Enabled` checked, the
strategy rejects those modes before activation.

## Installation

Build from `C:\Heatmap\ExecAssistantRuntime`:

```powershell
& 'C:\Users\j\AppData\Local\Microsoft\dotnet\dotnet.exe' build
```

The project deploys `ExecAssistantRuntime.dll` directly to:

```text
C:\Quantower\Settings\Scripts\Strategies\ExecAssistantRuntime\
```

Restart Quantower after each DLL rebuild. Quantower caches strategy assemblies
for the life of the application.

## Strategy Settings

Required:

- `Symbol`: the one instrument owned by this instance;
- `Account`: use a dedicated demo/throwaway account for initial validation;
- `Instance Max Quantity`: hard ceiling above all directive quantities.

Directive activation requires both a flat bound account/symbol position and no
working orders on that pair. Manual orders and orphan runtime orders are not
adopted; cancel them before dispatching a new directive.

Safety:

- `Trading Enabled=false` is shadow mode and is the default;
- `Trading Enabled=true` permits actual broker operations;
- startup self-tests should remain enabled.

`Trading Enabled` is captured when the strategy starts so the runtime and order
gateway cannot disagree about mode. Stop and restart the strategy after changing
it; changing the setting on a running instance has no effect until restart.

The LL-prefixed settings intentionally mirror LevelLedger's current ownership
defaults. Do not tune them casually. Runtime and visual behavior may diverge if
one copy changes without an explicit research decision.

Default runtime files:

```text
%USERPROFILE%\Documents\ExecAssistantRuntime\directive.json
%USERPROFILE%\Documents\ExecAssistantRuntime\control.json
%USERPROFILE%\Documents\ExecAssistantRuntime\events.jsonl
%USERPROFILE%\Documents\ExecAssistantRuntime\checkpoint.json
```

The strategy does not create an active directive template. Payloads must match
the repository schemas exactly. Symbol and account never belong in JSON.

## First Shadow Run

1. Restart Quantower and create one strategy instance for NQ and the demo
   account.
2. Leave `Trading Enabled` unchecked.
3. Start the strategy before the intended directive window so its forward-only
   L2 engine can warm up. Thirty seconds is the statistical minimum; several
   minutes gives it useful rail context.
4. Write a new `TRADE_DIRECTIVE` with a unique ID, current timestamps, and
   `HARD_TP`.
5. Confirm the strategy log reports `directive_accepted` and the JSONL log
   contains evidence transitions.
6. A shadow trigger creates `order_shadow_fill`, simulated position protection,
   and eventual shadow exit without touching the broker.

Repeated edits to an accepted ID are rejected as mutation. After completion,
cancel, `FLAT`, or restart, issue a new directive ID even when the plan is the
same.

## Demo Live Run

After reviewing a shadow log:

1. Stop the strategy and verify the bound demo account/symbol is flat.
2. Check `Trading Enabled` and restart the strategy.
3. Use base quantity one for the first order-path test.
4. Keep the target close and hard so entry, target, order tagging, and position
   reconciliation can be observed in one short cycle.
5. Verify `order_submit`, `order_submit_result`, broker order events,
   `trade_fill`, `fill_quality`, and `position_reconciled` are present.

The first live tests are broker API validation, not strategy-performance tests.
Specifically verify that the connection accepts:

- ordinary market entry;
- position-linked close limit;
- position-linked stop-market;
- quantity/price modification of those protection orders;
- close-position while protection cancellation is in flight.

## Controls

`CANCEL_DIRECTIVE` is directive-scoped but still flattens the position owned by
that directive.

`FLAT` is deliberately broader:

- latch the strategy against new entries;
- cancel all working orders for the bound account/symbol, including manual
  orders;
- close the complete bound net position;
- remain halted until a directive with a new ID is accepted.

Control files are immutable commands. Rewriting the same command ID does not
repeat the action.

## Restart And Data Loss

L2 state is forward-only. Restart never resumes candidates, rails, epochs, or
LF/HF baselines.

- Flat on restart: cancel orphan runtime orders and require a fresh directive
  ID.
- Losing, ambiguous, unquoted, or unprotectable live position: flatten.
- Profitable live position: install protective breakeven and a fixed target,
  then enter `RECOVERY_PROTECTED`; no adds or evidence management resume.
- Shadow mode plus an existing broker position: do not touch it; log
  `recovery_action_required` and reject directives until the pair is flat.
  Worker processing pauses before control-file polling, so `FLAT` is not
  available in this state. Flatten the position in Quantower, then let the
  shadow instance resume.

`entry_order_unresolved` and `entry_cancel_reconciliation_timeout` require
operator attention. Inspect the bound pair in Quantower and confirm that no
entry order remains working. The runtime latches `ERROR`, continues attempting
to cancel the tagged entry every five seconds, rejects new directives until the
submission reconciles, and safety-flattens any late fill. The broker DOM is
authoritative when cancellation acknowledgement is lost.

Stopping the strategy cancels runtime entry/add orders. It intentionally leaves
accepted target/breakeven protection attached to an open position.

## Reading Fill Quality

For every entry/add fill, `fill_quality` separates:

- `detection_drift_points`: submission quote versus trigger quote;
- `transport_slippage_points`: fill versus submission quote;
- `total_implementation_cost_points`: fill versus trigger quote;
- `root_distance_ticks` and `support_distance_ticks`: fill location relative to
  the evidence objects.

Do not change routing from market to limit based on one fill. Review repeated
cost by resolution type, time of day, spread, and broker response. The purpose
of v1 is to measure whether a fill problem exists before creating another
execution subsystem.

## Known Validation Boundary

The strategy compiles, deploys, and its pure contract/evidence/coordinator
self-tests pass. Broker-specific order behavior cannot be proven by offline
tests. Keep live validation on a throwaway account until market, target, stop,
modify, cancellation, partial fill, and restart paths have all appeared in the
JSONL log.
