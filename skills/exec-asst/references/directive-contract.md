# EAR Directive Contract

Use the canonical schemas at:

- `C:\Heatmap\ExecAssistantRuntime\trade-directive-v1.schema.json`
- `C:\Heatmap\ExecAssistantRuntime\control-command-v1.schema.json`

`earctl.py` mirrors the production parser's semantic checks. The runtime parser
remains authoritative.

## Entry Fields

- `order_price_range`: inclusive executable-quote range for base submission.
- `context_price_range`: contains the order range and bounds eligible evidence.
- `add_price_range`: required when adds are enabled; null otherwise.
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

When scaling is disabled, use `add_quantity=0` and `add_price_range=null`.
After the first filled add, EAR protects the complete weighted position at
protectively rounded breakeven. LF/HF flattens the complete position.

## Targets

- `HARD_TP`: resting close limit; the only live-eligible v1 mode.
- `TARGET_DECISION`, `TRAIL_AFTER_TARGET`, and
  `TARGET_DECISION_BEFORE_EXTREME`: observation-only in shadow mode.

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
