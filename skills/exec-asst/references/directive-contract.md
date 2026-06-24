# EAR Directive Contract

Use the canonical schemas at:

- `C:\Heatmap\ExecAssistantRuntime\trade-directive-v1.schema.json`
- `C:\Heatmap\ExecAssistantRuntime\control-command-v1.schema.json`

`earctl.py` mirrors the production parser's semantic checks. The runtime parser
remains authoritative.

## Entry Fields

- `order_price_range`: inclusive executable-quote range for base submission.
- `context_price_range`: required in runtime JSON and bounds eligible evidence,
  but is not normally a conversational input. `earctl.py` derives the smallest
  envelope containing the order and enabled add ranges.
- `add_price_range`: required in runtime JSON when adds are enabled, contained
  by the context range, and null otherwise. It is not normally a conversational
  input. Unless the user states a restriction, `earctl.py` derives the campaign
  envelope: order-range low through `HARD_TP` for a long, and `HARD_TP` through
  order-range high for a short.
- `pre_entry_invalidation`: optional one-way price gate before any entry. It is
  `below` for longs and `above` for shorts.
- `allowed_resolutions`: normally both `direct_conversion` and
  `supported_reclaim`.

EAR starts recognizing eligible transitions only after activation. Existing
bands remain context, but completed pre-activation resolutions are not replayed.

## Sizing And Retries

Quantities are contracts, not abstract clips:

- `base_quantity`: initial position quantity;
- `add_quantity`: quantity for each independently justified add;
- `max_position_quantity`: ceiling, never a fill objective;
- `max_base_reentries`: attempts after the initial base; settled default is 3.

When scaling is disabled, use `add_quantity=0`, `add_price_range=null`, and
`max_position_quantity=base_quantity`. When enabled, the maximum must have room
for at least one complete add; it remains a ceiling rather than a fill goal.
After the first filled add, EAR protects the complete weighted position at
protectively rounded breakeven. LF/HF flattens the complete position. The
causal same-side sponsor may promote only favorably; confirmed failure of the
exact current sponsor also flattens. Tests, holds, and overlapping rails do not
move protection. A fresh opposite LF/HF while armed but flat invalidates the
directive and requires a new ID.

## Targets

- `HARD_TP`: resting close limit and the sole accepted v1 target mode in both
  shadow and live operation.

For a long, target direction is `above`; for a short, `below`. The target must
leave executable runway from the entry range.

## Timing

Use RFC 3339 timestamps with an explicit New York offset. Default activation is
now and default TTL is 30 minutes. Use 60 minutes when the user explicitly asks
for two TPOs or one hour.

## Controls

- `CANCEL_DIRECTIVE` is directive-scoped and flattens its owned position.
- `FLAT` is account/symbol scoped: it cancels every working order on the bound
  pair, closes the complete net position, and halts the runtime.

Every directive ID and control command ID must be unique. Never rewrite an
accepted payload under the same ID.

## Runtime Status Authority

The checkpoint is the current-state authority for mode, strategy quantity
ceiling, position, active directive identity, working-order count, unresolved
entry reconciliation, and the last accepted immutable directive. The event log
is the outcome history. `directive.json` is only the latest attempted input and
must never be treated as proof that EAR accepted it.

Checkpoint evidence state is independent of directive state. `AwaitingBook` and
`Warming` are non-actionable, `Ready` permits evidence decisions, and
`BookUnusable` pauses them. Status includes epoch reason/start, sample count,
required samples, and remaining warm-up time.
