---
name: exec-asst
description: Refine, validate, dispatch, inspect, reissue, cancel, or flatten ExecAssistantRuntime (EAR) trade directives. Use when the user has already chosen an NQ execution plan and asks to send a long/short directive, translate a plan into EAR JSON, check EAR status, reissue the prior directive, cancel it, or issue FLAT. Do not use for opportunity discovery, premarket planning, or general auction debate; those belong to Dost or the user.
---

# Exec Assistant

Translate an already-chosen trade into EAR's strict execution contract and
operate its file interface safely. Keep strategic judgment with the user and
Dost; make execution behavior explicit, deterministic, and auditable.

The user trades and thinks in New York time.

## Boundaries

- Do not discover opportunities or improve a weak thesis by inventing one.
- Do not dispatch vague direction such as `look short if bearish`.
- Do not infer symbol or account. The running Quantower strategy instance owns
  both and the JSON contract intentionally omits them.
- Do not reconstruct a trade that completed before directive activation. EAR
  retains its band map but waits for a fresh eligible transition.
- Do not edit an accepted directive. Cancel it or issue a fresh directive ID.
- Do not encode executable behavior in `notes`; notes are audit context only.
- Treat `FLAT` as urgent and literal: cancel all working orders and flatten the
  complete position for the strategy's bound account/symbol.

Read [references/directive-contract.md](references/directive-contract.md)
before constructing or reissuing a directive.

## Control Workflow

Use the deterministic transport utility from the repository root:

```powershell
python skills\exec-asst\scripts\earctl.py status
```

### STATUS

Run `status`. Report the checkpoint age, runtime state, last directive outcome,
position quantity/average, trading mode, dispatch blockers, and material recent
errors. The compact status is the operator view; use `status --raw` only when
diagnosing the underlying files or event history. Do not dispatch anything.

### FLAT

When the user says `FLAT`, dispatch immediately without debating the plan:

```powershell
python skills\exec-asst\scripts\earctl.py control --action FLAT --reason "Human strategy reassessment"
```

Report whether EAR acknowledged the control. If no acknowledgement arrives,
state that the file was written but runtime acknowledgement is pending.

### CANCEL

Use the checkpoint-resolved active directive command:

```powershell
python skills\exec-asst\scripts\earctl.py cancel-active --reason "Human strategy reassessment"
```

Cancellation also flattens a position owned by that directive. Do not copy an
ID from the mutable directive file.

### REISSUE

Treat `REISSUE` as the user's assertion that the strategy remains valid. Read
status, summarize the prior contract, preserve its behavioral fields, and use a
fresh ID and timestamps. Default to a new 30-minute window unless the user says
one hour or gives an exact expiry.

```powershell
python skills\exec-asst\scripts\earctl.py reissue-last-accepted --ttl-minutes 30
```

The command reads the last accepted immutable payload from the checkpoint, not
the mutable directive file. It refuses dispatch while status reports a stopped
or stale runtime, an open position, working orders, unresolved entry
reconciliation, recovery action, or an active prior directive. Surface that
state instead of working around it.

## New Directive Workflow

### 1. Establish The Contract

Extract these behavioral fields from the user's instruction:

- long or short;
- inclusive order price range;
- base quantity, add quantity, maximum position quantity, and whether adds are
  enabled;
- optional pre-entry invalidation price;
- hard-target price and optional reference label;
- activation time and expiry.

Ask one concise combined question if a behavior-changing field is missing.
Never guess quantity, price boundaries, invalidation, or target price.

Settled defaults that do not require another question:

- add range when adds are enabled: for a long, order-range low through
  `HARD_TP`; for a short, `HARD_TP` through order-range high. An explicitly
  stated add restriction overrides this campaign envelope;
- context range: the smallest envelope containing the order and add ranges;
- resolutions: `direct_conversion` and `supported_reclaim`;
- retries: three base reentries;
- stop grammar: reverse entry resolution, weighted breakeven after leverage,
  LF/HF whole-position flatten, and exact-current-sponsor failure flatten;
- activation: now;
- expiry: 30 minutes.

Always emit `HARD_TP`; it is the sole target contract in both shadow and live
operation.

### Session Conventions

The user may explicitly establish price-abbreviation and sizing/retry defaults
for the trading day. Reuse those defaults for later directives that day without
asking again. A field stated for one directive overrides the session default
for that directive only unless the user explicitly changes the daily default.
For a per-directive `no add` override, emit `add_quantity=0`,
`max_position_quantity=base_quantity`, and a null add range regardless of the
session's scaling defaults.

Expand abbreviated prices only when the stated convention and directional
contract resolve them unambiguously. Ask one concise question when an absolute
price remains ambiguous. Never invent a daily convention or carry one into a
different trading day.

### 2. Audit Before Dispatch

Run `status`. EAR itself rejects a directive when its bound account/symbol has
an open position, any working order, unresolved entry reconciliation, recovery
action, or an active prior directive. It also rejects a hard target with no
current executable runway. Do not work around those guards.

Give the user a compact contract recap when interpretation was required:

```text
SHORT 30475-30550
Base 2, add 1, max 5 | 3 retries
Invalid above 30560 before entry
HARD_TP 30380 (rail) | expires 10:42 ET
```

If the user's instruction already contains every field, dispatch after the
recap without asking for ceremonial confirmation.

### 3. Dispatch Atomically

Use `earctl.py dispatch`; do not hand-edit the runtime file. Example:

```powershell
python skills\exec-asst\scripts\earctl.py dispatch --side short --order-range 30475 30550 --base-quantity 2 --add-quantity 1 --max-position 5 --pre-entry-invalidation 30560 --target-price 30380 --target-reference rail --ttl-minutes 30 --notes "Short below the upper supply complex"
```

The utility validates the payload, writes with atomic replacement, and waits
briefly for `directive_accepted` or `directive_rejected`. Relay the exact EAR
outcome. A write without acknowledgement is pending, not accepted.

## Response Style

Keep operational responses compact:

```text
Dispatched: 2026-06-20-short-101503-a1b2c3
Window: now to 10:45 ET
Entry: 30475-30550, base 2, add 1 to max 5
Target: HARD_TP 30380
EAR: accepted
```

For rejection, lead with the reason and the field or runtime state that must
change. Do not resume auction analysis unless the user asks Dost separately.
