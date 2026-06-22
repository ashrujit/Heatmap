# ExecAssistantRuntime Implementation Plan

## Objective

Replace the passive-order spike with a Quantower Strategy that executes one
immutable, human-dispatched NQ directive using copied LevelLedger evidence math.
The strategy owns execution only. It does not discover opportunities, interpret
notes, change direction, or formulate replacement directives.

The first live-capable cut must prove the complete mechanical path:

1. accept and freeze one valid directive;
2. build LevelLedger-compatible evidence from live Quantower L2;
3. resolve one supported reclaim or direct conversion;
4. place a vanilla market base order;
5. retry only from a fresh epoch when the base stops;
6. add only from fresh campaign evidence;
7. protect leverage at weighted breakeven;
8. hand campaign protection to fresh favorable sponsors without moving the
   broker breakeven stop;
9. exit at a hard target, semantic stop, current-sponsor failure, LF/HF,
   cancellation, or `FLAT`;
10. reconcile every order, fill, and position change;
11. produce enough telemetry to diagnose timing and fill quality afterward.

## Safety Cut Line

The strategy starts in shadow mode. Live order placement requires the explicit
Quantower `Trading Enabled` setting.

The v1 contract supports only `HARD_TP` in both shadow and live modes. Any other
target value is rejected during parsing, before shared coordinator or recovery
logic can observe it. Entry, scaling, protection, control, and recovery can be
exercised on a demo account against the same fixed-target contract used live.

The strategy assumes a dedicated account/symbol pair while enabled. Manual or
unrelated position changes inside that pair are treated as reconciliation
errors. `FLAT` and restart recovery act on the complete bound pair because a
partially attributed futures net position is not safe to manage.

## Runtime Components

### Quantower Adapter

`ExecAssistantRuntime.cs` remains the Strategy entry point. It owns:

- symbol/account settings and connection dependency;
- quote, L2, order, trade, and position subscriptions;
- the serialized worker loop;
- DOM snapshot acquisition;
- actual order API calls;
- startup and shutdown reconciliation.

Callbacks capture immutable snapshots or set dirty flags only. File I/O,
directive processing, evidence transitions, and order decisions run on one
worker path so concurrent broker callbacks cannot double-submit.

### Contracts

`DirectiveContracts.cs` strictly parses the two normative v1 schemas without a
second permissive legacy shape. It rejects:

- unknown or duplicate JSON properties;
- missing required fields or incorrect constants;
- invalid IDs, timestamps, ranges, directions, or quantities;
- contradictory scaling fields;
- context that does not contain the executable range;
- quantities above the strategy instance ceiling;
- mutation of an already accepted directive ID.

The parsed model has a canonical SHA-256 digest. Whitespace-only rewrites do not
change identity.

### Evidence Engine

`ExecutionEvidenceEngine.cs` copies the LevelLedger ownership subset rather
than referencing the indicator:

- 30-level DOM sample and 10-level inner depth;
- 30-second rolling book statistics;
- the four side-aware L2 z-score events;
- three-event, ten-tick, ninety-second candidate clustering;
- minimum score eight;
- eight-tick, ten-second ownership/consumption confirmation;
- two-tick failure buffer and 24-tick/20-second failure confirmation;
- tested/held rail states;
- no-owner/contested envelopes;
- outside-grey LF/HF construction and invalidation.

Every candidate, rail, failure, and LF/HF transition carries a stable runtime
object ID and source lineage. The engine exposes transitions; it never places
orders.

The only execution-specific timing divergence is the researched supported
reclaim fast path: an already-active same-side candidate within twenty ticks of
a newly failed confirmed opposing rail may support execution after four
uninterrupted seconds of favorable eight-tick displacement.

### Coordinator

`ExecutionCoordinator.cs` owns directive state and resolution epochs:

- `ARMED`, `BASE_ONLY`, `LEVERAGED`, `RECOVERY_PROTECTED`, and terminal states;
- one order attempt per resolution epoch;
- candidate/rail lineage boundaries for fresh retry and add epochs;
- base semantic invalidation;
- retry allowance before leverage only;
- maximum position as a ceiling, never an objective;
- immediate weighted breakeven after the first add;
- irreversible favorable-only sponsor promotion and exact-current-sponsor
  failure flattening;
- post-activation opposite LF/HF flattening;
- armed-directive invalidation when a fresh opposite LF/HF appears while flat;
- target and control precedence.

The coordinator produces order intents. It does not call Quantower directly.
That separation makes replay of the state machine possible without a broker.

### Order Gateway

`QuantowerOrderGateway.cs` translates intents into vanilla broker operations:

- market base/add entries;
- market semantic and emergency exits;
- close-position calls for reconciliation;
- resting close-order limits for `HARD_TP`;
- resting close-order stops for weighted breakeven;
- modify existing protection when quantity or average changes;
- tag, track, and cancel runtime-owned working orders.

Before an entry/add submission, the executable ask for a long or bid for a
short must be fresh and inside the directive range. Supported reclaim submits
as soon as the full transition is valid. Direct conversion submits only within
twenty ticks of the converted wall; otherwise it remains armed for a live
retest while the wall survives.

### Event Log And Checkpoint

`RuntimeEventLog.cs` writes append-only JSONL on a dedicated writer thread.
Broker and market-data callbacks never write files directly.

Quantower Strategy Manager also receives sparse `[EAR]` lifecycle messages for
directive, order/protection, sponsor, HF/LF, control, recovery, and error events.
It is the immediate operator channel, not a replacement for JSONL audit detail.

Each event includes UTC and monotonic timestamps. Order telemetry records:

- directive, epoch, evidence object, order, and position IDs;
- band side, source, state, boundaries, and lifecycle timestamps;
- bid/ask and quote age at trigger and immediately before submission;
- submit result, broker acknowledgement/update, and every fill;
- requested, filled, and remaining quantity;
- fill price and distance from the relevant band;
- detection drift, transport slippage, and total implementation cost;
- rejection, cancellation, partial fill, and reconciliation outcomes.

`RuntimeCheckpoint.cs` atomically records only the state required for safe
restart: accepted directive digest, processed control IDs, runtime state,
position context, and owned protection IDs. It is not an L2 snapshot and cannot
be used to resume old evidence.

## Execution Rules In The First Cut

### Entry

- `direct_conversion`: normal ten-second LevelLedger `CONSUMED` confirmation;
  market within twenty ticks of the converted wall, otherwise wait for a live
  retest inside that envelope.
- `supported_reclaim`: confirmed opposing rail fails while same-side support
  survives with correct topology within twenty ticks; confirmed support acts
  immediately, while candidate support uses the four-second fast path.
- executable quote must be fresh, inside `order_price_range`, and before target;
- pre-existing bands remain context, but completed pre-activation resolutions
  are never replayed as entry triggers;
- one epoch may submit once; a zero-fill/rejected attempt closes as `MISSED` and
  cannot loop on repeated evidence messages.

### Base Stop And Retry

- stop on the reverse of the entry resolution, never on arbitrary tick distance;
- flatten the complete base quantity at market;
- re-arm only after flat/order reconciliation and only from a fresh opposing
  candidate formed after that boundary;
- stop re-arming after pre-entry invalidation, expiry, target, LF/HF, control,
  retry exhaustion, or any prior leverage.

### Adds And Protection

- fresh post-fill opposing evidence must independently convert or fail under
  surviving same-side support;
- no plain same-side candidate, retest, hold, or repeated message can add;
- submit one `add_quantity` clip without exceeding `max_position_quantity`;
- after the first add fill, install whole-position weighted breakeven
  immediately from actual broker position average and quantity;
- later adds modify breakeven and hard-target quantity;
- the filled entry support initializes the sponsor; a later newly owned,
  non-overlapping same-side rail may promote only fully in the favorable
  direction after price confirms beyond its band;
- sponsor tests/holds do nothing; failure or adverse consumption of the exact
  current sponsor market-flattens, while older sponsor failures are ignored;
- sponsor promotion never moves the weighted-breakeven broker stop;
- failure to establish valid leveraged protection is a flattening error.

### Targets

- `HARD_TP`: resting close-order limit at the normalized target;
- reaching the hard target or any terminal exit completes the directive and
  prevents re-arming.

### Control And Recovery

- `CANCEL_DIRECTIVE` cancels runtime orders, flattens its bound position, and
  records `cancelled`;
- `FLAT` latches first, cancels in-scope orders, closes all bound positions,
  reconciles to zero, and remains halted until a new directive ID is accepted;
- restart while flat cancels the old directive and requires a new ID;
- restart with a losing, ambiguous, or unprotectable position flattens;
- restart with a profitable position installs breakeven and retains/recreates
  only fixed hard-target protection in `RECOVERY_PROTECTED`;
- old candidates, rails, LF/HF baselines, retries, and epochs never resume.
- one rejected DOM sample pauses evidence actions without changing directive or
  position state; restart-style recovery runs only after the configured
  stale/mismatch grace remains continuously breached;
- every unusable interval records its initial/latest reason and recovery, and a
  confirmed positioned recovery explicitly cancels runtime orders before
  establishing breakeven and hard-target protection.

## Build Sequence

1. Replace the legacy parser and passive probe with strict v1 contracts.
2. Add asynchronous JSONL logging and atomic checkpointing.
3. Add serialized market-data sampling and copied ownership evidence.
4. Add shadow coordinator with deterministic transition logs.
5. Add control and restart reconciliation.
6. Add market entry/exit gateway and `HARD_TP`.
7. Add base semantic stop/retry.
8. Add fresh-epoch scaling and weighted breakeven.
9. Replay the June fixtures through the pure coordinator.
10. Build/deploy, restart Quantower, run shadow, then enable on a throwaway
    account at one base clip.

## Verification Gates

Before enabling orders:

- strict contract positive and negative fixtures pass;
- the copied evidence engine matches LevelLedger transitions on selected June
  windows;
- repeated polling and repeated evidence cannot duplicate an order intent;
- `CANCEL_DIRECTIVE` and `FLAT` are idempotent;
- restart fixtures produce cancel, flatten, or `RECOVERY_PROTECTED` exactly as
  specified;
- leveraged fixtures arm breakeven immediately and terminate after flatten;
- sponsor fixtures prove initial identity, favorable non-overlapping promotion,
  no fallback to an older sponsor, and exact-current-sponsor failure flatten;
- a fresh opposite HF/LF while flat invalidates without a no-op close request;
- event logs can reconstruct trigger quote, submission quote, and fill price;
- Quantower build succeeds and the deployed DLL loads after restart.

Live rollout is demo-first. Fill logic is not optimized until logs show a
repeatable cost attributable to runtime or broker execution rather than evidence
confirmation.

## Deferred By Design

- opportunity discovery and all Codex skills;
- multi-symbol or multi-account operation inside one instance;
- automated strategy reversal or reissue;
- adaptive ES routing or liquidity-aware limit placement;
- changing LevelLedger or sharing a mutable math library with it.
