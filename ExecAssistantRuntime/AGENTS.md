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
- The selected Quantower `Symbol` and `Account` settings are authoritative.
  Directives must not contain symbol or account because those values cannot
  drift from the running strategy instance.
- Directive activation requires a flat bound position and zero working orders
  on the bound account/symbol. The runtime never adopts discretionary or orphan
  orders into a new directive's stop and protection lifecycle.
- A trade directive is immutable once dispatched. A changed idea is a new
  directive. Urgent control commands such as `FLAT` are separate, out-of-band
  messages rather than edits to the active trade directive.
- Normative trade directives are active-only inputs. Runtime terminal states
  belong in the append-only event log. `CANCEL_DIRECTIVE` and `FLAT` are
  immutable control commands.
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
- `HARD_TP` is the only developed/live target path. Decision/trailing modes
  remain schema-valid compatibility values but are frozen; reject them live and
  do not infer target-gate behavior in shadow mode.
- Campaign protection tracks one causal same-side sponsor internally. A later
  sponsor may promote only when it is newly owned, fully beyond the current
  sponsor in the favorable direction, and has confirmed favorable
  displacement. Promotion is irreversible; only failure or adverse consumption
  of the exact current sponsor flattens. Never move the broker weighted-BE stop
  to a sponsor edge.
- A fresh opposite HF/LF is terminal evidence even while the directive is flat.
  In that case invalidate the directive and cancel runtime entry orders without
  sending a meaningless position-close request; later evidence requires a new
  directive id.
- The Strategy Manager log is the operator's immediate, sparse lifecycle
  channel. Keep JSONL as the canonical detailed audit and do not echo routine
  evidence transitions into the visible log.
- The account/symbol pair should be dedicated while trading is enabled. Net
  position attribution cannot be recovered reliably after a restart.
- `research/export_book_jsonl.py` is a narrow bridge for piping archived
  MarketRecorder snapshots into a temporary C# evidence replay. It exists to
  detect drift in the copied engine; it is not a runtime data source.
