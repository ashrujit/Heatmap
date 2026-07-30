# ExecAssistantRuntime Operator Guide

## Current Live Scope

The deployed strategy supports the settled NQ execution path by default, plus
an opt-in ES rail-interaction policy:

- strict immutable v1 directive and control JSON;
- copied LevelLedger ownership rails, conversion, failure, and LF/HF math;
- market base/add entries;
- base semantic stop and fresh-epoch retries;
- strict fresh-epoch adds;
- no routine weighted-breakeven stop after adds; leveraged campaigns exit by
  exact current-sponsor failure, `HARD_TP`, sponsor-aligned LF/HF, or control;
- internal favorable-only sponsor handoff and market flatten on exact current
  sponsor failure;
- optional `CONTINUE` directive lineage for the same unchanged range after a
  local protective exit or an unfilled expiry, without replaying arbitrary
  historical rails;
- local-first LF/HF handling that pauses flat entry and defers positioned
  termination to causal sponsor failure;
- broad context/add envelopes are preferred; LF/HF pause/re-arm should filter
  local repair risk rather than be defeated by overly tight wick-entry ranges;
- resting `HARD_TP` limit;
- `CANCEL_DIRECTIVE`, `FLAT`, and fail-closed restart recovery;
- append-only evidence/order/fill telemetry plus sparse `[EAR]` Strategy Manager
  lifecycle messages.

With `Execution Policy=ES Rail Interaction`, entry and stop mechanics diverge
from NQ while the directive schema and LevelLedger evidence math stay the same:

- direct conversion, supported reclaim, and LF/HF-assisted child rails arm a
  rail interaction instead of entering merely because price is near the rail;
- the armed rail must be contacted or punctured, then price must escape in the
  directive direction before the runtime routes the market entry/add;
- fresh direct-conversion rails may enter immediately only when the executable
  quote is already at least one tick beyond the favorable edge;
- positioned sponsor protection adds an ES semantic stop: `8` ticks adverse
  beyond the current sponsor plus `10` seconds without re-entry into that rail;
- confirmed current-sponsor/rail failure still flattens immediately and does
  not wait for the no-reentry timer.

`HARD_TP` is the sole accepted target mode in both shadow and live operation.
The parser rejects any other value before directive activation.

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

- `Symbol`: the execution instrument owned by this instance;
- `Market Data Symbol`: optional quote/L2/DOM source for evidence. Leave it
  blank to use `Symbol`; set it to `NQU6` when executing `MNQU6` from the NQ
  book;
- `Account`: use a dedicated demo/throwaway account for initial validation;
- `Instance Max Quantity`: hard ceiling above all directive quantities.

Directive activation requires both a flat bound account/symbol position and no
working orders on that pair. Manual orders and orphan runtime orders are not
adopted; cancel them before dispatching a new directive.

Only `Symbol` and `Account` define the bound execution pair. `Market Data
Symbol` is captured at strategy start and drives `NewQuote`, `NewLevel2`, DOM
snapshots, L1/DOM agreement checks, and evidence math. It does not change order,
position, recovery, or `FLAT` scope. The execution and data symbols must share
the same tick size, or startup fails closed.

Safety:

- `Trading Enabled=false` is shadow mode and is the default;
- `Trading Enabled=true` permits actual broker operations;
- `LF/HF Assisted Entries Enabled=true` is the default. A favorable LF/HF can
  arm the next same-side ownership rail as an entry/add anchor; it does not
  make the LF/HF itself directly tradeable;
- `Execution Policy=NQ Classic` is the default and preserves NQ market-on-
  proximity retest behavior;
- `Execution Policy=ES Rail Interaction` is the ES policy. Start with
  `ES Entry Escape (ticks)=0`, `ES Stop Breach (ticks)=8`, and
  `ES Stop No-Reentry (sec)=10`;
- startup self-tests should remain enabled.

Market-data continuity:

- `L2 Freshness (sec)` is the no-real-L2-callback threshold; default `5`;
- `L2 Stale/Mismatch Grace (sec)` is the continuous confirmation delay before
  EAR invokes cancel/flatten/recovery; default `5`;
- empty DOM, L1/DOM mismatch, and DOM read failure start the grace immediately;
- one good snapshot clears an unconfirmed grace and resumes evidence processing.

With both defaults, a missing heartbeat becomes unusable after five seconds and
must remain unusable for another five seconds before continuity loss confirms.
A continuously mismatched or empty DOM confirms after five seconds. Transient
failures are written as `book_unusable_started` / `book_usable_recovered` audit
events but are not Strategy Manager errors.

`Trading Enabled` is captured when the strategy starts so the runtime and order
gateway cannot disagree about mode. Stop and restart the strategy after changing
it; changing the setting on a running instance has no effect until restart.
`Market Data Symbol` is also captured at strategy start; stop and restart after
changing it.
`Execution Policy` and the ES policy settings are also captured at strategy
start; stop and restart after changing them.

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

Use `skills\exec-asst\scripts\earctl.py status` for the machine-readable
operator snapshot. Its checkpoint heartbeat carries the captured trading mode,
execution symbol, market-data symbol, instance quantity ceiling, position,
active directive identity, and admission blockers. `directive.json` is only the
latest attempted input; the checkpoint's last accepted JSON is authoritative
for reissue.

The status snapshot also reports evidence state, epoch reason/start, accumulated
samples, and warm-up remaining. `AwaitingBook` means no usable sample has
started the epoch; `Warming` is non-actionable; `Ready` permits evidence action;
`BookUnusable` pauses it.
It also reports `execution_policy` and the active ES rail/stop parameters, so
verify those before judging a shadow replay.

## First Shadow Run

1. Restart Quantower and create one strategy instance for the execution symbol
   and demo account. For MNQ execution from NQ evidence, set `Symbol=MNQU6` and
   `Market Data Symbol=NQU6`.
2. Leave `Trading Enabled` unchecked.
3. Start the strategy before the intended directive window. The runtime now
   enforces one full configured book-lookback interval (30 seconds by default)
   and the corresponding sample count before evidence may act; several minutes
   still gives it more useful rail context.
4. Write a new `TRADE_DIRECTIVE` with a unique ID, current timestamps, and
   `HARD_TP`.
5. Confirm the Strategy Manager log reports an `[EAR] Directive ... accepted`
   message and the JSONL log contains `directive_accepted` plus evidence
   transitions.
6. A shadow trigger creates `order_shadow_fill`, simulated position protection,
   and eventual shadow exit without touching the broker.

Repeated edits to an accepted ID are rejected as mutation. After completion,
cancel, `FLAT`, or restart, issue a new directive ID even when the plan is the
same. If the same unchanged range should continue after a local protective exit
or after an unfilled expiry, use a new directive id with
`lineage.mode: "CONTINUE"` and the immediately previous
`parent_directive_id`; do not cancel the parent first unless the intent is to
discard that lineage. If the order, context, or add range changes, issue a
`NEW` directive.

Directive expiry is the base-entry window. If no base is filled by expiry, the
directive expires flat and a continuation or new directive is required. If the
base filled before expiry, normal campaign management continues: fresh add
evidence can still scale inside `add_price_range`, while target, sponsor,
control, and protection exits remain active.

A fresh opposite HF/LF while the directive is armed but flat cancels any runtime
entry order and moves the directive to `Paused`. If that failure object
invalidates, the same directive re-arms. Once a position exists, the initial
filled entry support is its sponsor. A local opposite HF/LF does not flatten
while that sponsor remains intact. Same-sequence sponsor failure is terminal;
if a base sponsor fails first, a subsequently held adverse HF/LF invalidates the
flat retry before another base fills. Tests and holds do not move weighted BE.

In ES mode, a same-side ownership rail can be valid context without being an
immediate order. The runtime emits `es_rail_interaction_armed`,
`es_rail_interaction_contact`, and `es_rail_interaction_entry` audit events.
For exits it emits `es_semantic_stop_armed`, `es_semantic_stop_cleared`, and
`es_semantic_stop_fired`. These events are the first monitoring surface for
deciding whether to tighten from `8t/10s` to `4t/10s` or `4t/5s`.

With `LF/HF Assisted Entries Enabled`, a fresh favorable LF for a long or HF for
a short is parent context for the next newly owned same-side rail beyond it.
That child rail, not the failure object, becomes the entry/add support and
initial sponsor. If the child fails while only the base is live, the runtime
flattens and can re-arm under the normal retry contract; after leverage, current
sponsor failure remains terminal.

`CONTINUE` is not a reverse, not a control command, and not a way to make EAR
choose the trade. It only admits the immediate parent directive's protective-exit
evidence chain or, for an unfilled expired parent, eligible evidence formed
during the parent's active window. A fresh opposite directive is still the way to
trade the other side.

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
LF/HF baselines. The replacement engine processes samples during a visible,
non-actionable warm-up of one configured book-lookback interval. Failure objects
already held when warm-up completes are baselined as context.

A rejected sample alone is not data loss. While a sample is unusable, EAR pauses
evidence-dependent entry, add, retry, and semantic-stop decisions. If the book
recovers inside the configured grace, the directive and evidence epoch remain
intact. If the grace expires, EAR logs `forward_data_loss`, cancels runtime
orders, and applies the restart-style rules below. Recovery afterward starts a
new visible evidence warm-up; it does not silently appear ready.

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
accepted target and recovery-breakeven protection attached to an open position.

A complete Quantower/Windows crash cannot run stale-data logic. The resting
`HARD_TP` remains broker-side, but normal base and leveraged sponsor stops are
runtime-driven. Recovery/restart may install broker-side weighted breakeven
only after sponsor lineage has already been lost. A separate broker-resident
disaster-stop price would require an explicit directive-contract addition; the
continuity settings do not provide crash protection by themselves.

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
