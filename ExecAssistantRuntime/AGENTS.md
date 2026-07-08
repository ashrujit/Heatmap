# ExecAssistantRuntime - Directive Execution Strategy

## Intent

`ExecAssistantRuntime` is the mechanical execution strategy for an already
chosen discretionary plan. It is a Quantower `Strategy`, not an indicator,
because order lifecycle must not depend on chart paint, chart focus, or a
visual LevelLedger instance being loaded.

Read `DESIGN.md`, `IMPLEMENTATION_PLAN.md`, and `OPERATOR_GUIDE.md` before
changing behavior. They capture the planning/runtime split, directive
philosophy, LevelLedger isolation boundary, researched timing, safety cut line,
and staged build order.

`trade-directive-v1.schema.json` and `control-command-v1.schema.json` are the
only normative transport contracts. Do not preserve or reintroduce the loose
spike JSON shape as an alternate parser.

## Design Decisions

- JSON file polling is used instead of `FileSystemWatcher`.
  Strategy has no `OnUpdate`, and polling avoids missed Windows watcher events
  during atomic writes or editor temp-file saves.
- The selected Quantower execution `Symbol` and `Account` settings are
  authoritative. Directives must not contain symbol or account because those
  values cannot drift from the running strategy instance.
- `Market Data Symbol` may differ from the execution `Symbol` only to make the
  quote/L2/DOM source explicit, for example trading MNQ from NQ evidence.
  Orders, positions, recovery, and `FLAT` remain scoped only to the execution
  account/symbol pair.
- Directive activation requires a flat bound position and zero working orders
  on the bound account/symbol. The runtime never adopts discretionary or orphan
  orders into a new directive's stop and protection lifecycle.
- A trade directive is immutable once dispatched. A changed idea is a new
  directive. Urgent control commands such as `FLAT` are separate, out-of-band
  messages rather than edits to the active trade directive.
- `CONTINUE` is explicit directive lineage, not automatic reissue. It may only
  name the immediately previous directive with unchanged ranges. It can preserve
  either that parent's protective-exit chain or, when the parent expired flat
  and unfilled, the parent's active-window context. Arbitrary historical rails
  remain LevelLedger/strategy context, not executable runtime memory.
- Normative trade directives are active-only inputs. Runtime terminal states
  belong in the append-only event log. `CANCEL_DIRECTIVE` and `FLAT` are
  immutable control commands.
- The checkpoint is also the machine-readable operator heartbeat. Keep its
  mode, instance ceiling, poll cadence, position, admission blockers, and last
  accepted immutable JSON current so transport tooling never infers accepted
  state from `directive.json` or liveness from a bounded event-log tail.
- One resolution epoch may authorize one order attempt. Repeated evidence,
  manual cancellation, or a zero-fill terminal result must not create a polling
  loop that resubmits it.
- Orders are tagged with `EA:<directive-id>` in both `GroupId` and `Comment` so
  they can be found if Quantower returns success without an order id.
- Live NQ entry/add routing uses vanilla market orders. Do not add IOC or
  marketable-limit policy until logs demonstrate a real fill problem.
- L2 callbacks and broker callbacks must not perform file I/O. Serialize runtime
  decisions through one worker and write JSONL on a dedicated logger thread.
- L1 best bid/ask is authoritative only for executable-market, order-routing,
  profitability, and broker-protection decisions. Evidence snapshots derive
  their best prices and midpoint from DOM/L2. L1 agreement may reject a stale
  DOM sample but must never replace its prices.
- A rejected DOM sample is not an L2 continuity break. Pause evidence-dependent
  actions while the book is unusable, but preserve the evidence epoch unless
  stale heartbeat, empty DOM, L1/DOM disagreement, or read failure remains
  continuous through the configured grace. Only confirmed loss invokes the
  restart-style cancel/flatten/recovery contract; a good sample resets the grace.
- `HARD_TP` is the sole target contract in both shadow and live modes. Reject
  any other target value during parsing so abandoned exit concepts cannot reach
  shared coordinator or restart-recovery paths.
- Campaign protection tracks one causal same-side sponsor internally. A later
  sponsor may promote only when it is newly owned, fully beyond the current
  sponsor in the favorable direction, and has confirmed favorable
  displacement. Promotion is irreversible; only failure or adverse consumption
  of the exact current sponsor flattens. Normal campaign leverage does not use
  broker weighted-BE; BE is recovery-only after sponsor lineage has been lost.
- Inside an active position, failure of a qualified old opposite-side reference
  rail creates a short-lived reference-break context instead of redefining the
  rail or failure itself. Same-side child rails beyond that failed reference
  remain add-eligible, but they cannot inherit campaign-sponsor authority while
  the context is active; the campaign sponsor stays with the parent/break
  sponsor until the old reference is reclaimed or the context expires.
- Sponsor lineage is explicit in the canonical JSONL audit: promotion opens a
  sponsor interval and the sponsored-position-to-flat transition closes it with
  `sponsor_cleared`, preserving the last sponsor and flatten reason. Clearance
  is deliberately not echoed to the Strategy Manager log.
- Sponsor-failure context/rebuild telemetry is audit-only. Ambiguous late-move
  exits should be classified from adverse ownership, surviving same-side
  protection, and quick rebuild evidence before sponsor promotion or flatten
  rules are changed.
- A fresh opposite HF/LF is local auction evidence first. While flat it pauses
  entry and cancels runtime entry orders until that failure object invalidates.
  While positioned it cannot override an intact causal sponsor. It becomes
  terminal when the current sponsor fails in the same sequence, or when it
  appears after a sponsor-failure base exit before a fresh base fills.
- A favorable LF/HF is never an entry by itself. With `LF/HF Assisted Entries`
  enabled, a fresh favorable failure object only arms short-lived parent
  context; the next newly owned same-side rail beyond that parent is the
  tradeable anchor, sponsor, and base-risk object. Turning the setting off
  restores strict direct-conversion/supported-reclaim entry behavior.
- Restart and confirmed L2 loss never deserialize old candidates, rails, or
  timers. A new evidence engine processes but cannot act until one full
  configured book-lookback interval and the corresponding sample count have
  accumulated. Publish `AwaitingBook`, `Warming`, `Ready`, or `BookUnusable` in
  the checkpoint so the operator can see this boundary.
- Live startup treats a restored `IsTradingAllowed == false` as transient
  broker readiness until proven otherwise. Quantower can restore a strategy
  before connected symbol/account handles are tradable; EAR should stay alive,
  refresh those handles by id/connection, publish `TradingUnavailable`, and run
  the normal recovery scan only after trading permission returns.
- `directive_accepted` is the canonical contract audit and must include the
  accepted order, context, and add range boundaries. Do not rely on the latest
  input file to reconstruct constrained or missed execution.
- The Strategy Manager log is the operator's immediate, sparse lifecycle
  channel. Keep JSONL as the canonical detailed audit and do not echo routine
  evidence transitions into the visible log.
- The account/symbol pair should be dedicated while trading is enabled. Net
  position attribution cannot be recovered reliably after a restart.
- `research/export_book_jsonl.py` is a narrow bridge for piping archived
  MarketRecorder snapshots into a temporary C# evidence replay. It exists to
  detect drift in the copied engine; it is not a runtime data source.
