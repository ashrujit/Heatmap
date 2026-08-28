# KahnRuntime - Adaptive Campaign Runtime

## Intent

`KahnRuntime` is a Quantower `Strategy` project for adaptive campaign
management. It reads one active campaign plan, consumes typed evidence, evaluates
deterministic policies, and can either shadow-fill decisions or route bounded
broker orders when `Trading Enabled` is explicitly enabled.

Kahn exists because EAR's immutable directive is the wrong shape for
waypoint-aware campaign decisions. EAR remains the stable execution baseline and
fallback; Kahn should borrow proven mechanics without turning the campaign
governor into a form-filled EAR directive dispatcher.

## Design Decisions

- The campaign plan is immutable audit input. Adaptive behavior belongs in
  mutable `CampaignState` plus append-only decision events, not edits to the
  accepted plan.
- Policies emit typed `PolicyDecision` records. Free-form text, LLM replies, or
  agent messages are never execution authority.
- Enforcement is deterministic. Risk-down decisions outrank add or entry
  permission, and live execution validates quantity, campaign side, quote
  freshness, bound account/symbol state, and instance max before touching orders.
- `Symbol` and `Account` are the execution pair. Optional `Market Data Symbol`
  drives quotes, DOM, and LL evidence; this allows MES/MNQ execution from ES/NQ
  data when tick sizes match. The data symbol never defines order, position, or
  flatten scope.
- `Trading Enabled=false` is the default. In that mode `Shadow Fill Simulation`
  can advance simulated state. With `Trading Enabled=true`, accepted broker
  actions submit live orders or close the bound live position, and Kahn
  reconciles campaign state from the bound position.
- Base/add/max sizing lives in campaign JSON (`probe_quantity`,
  `add_quantity`, `max_position_quantity`) so size can change by situation
  without restarting the strategy. `Instance Max Quantity` is only a runtime
  safety cap and campaign admission guard.
- `execution.max_retry` is directive-local and defaults to `3`. It counts accepted
  probe attempts that later flatten/scratch; quote staleness or broker submit
  rejection is logged but does not spend the campaign retry budget. Once the
  retry budget is exhausted and the campaign is flat, Kahn enters `Paused`
  rather than `Retired`, keeps the loaded auction map/checkpoint context,
  and waits for an amended/reissued campaign digest to resume.
- Kahn does not adopt manual or orphan live positions. If live mode sees an
  existing bound position while campaign state is flat, or multiple bound
  positions, it logs `ERR: recovery action required` and pauses campaign
  decisions until the operator intervenes.
- The live adapter is still narrow: market entry/add orders, reduce-only
  close-limit orders for configured passive harvest objectives, and market
  close-position reduce/flatten/retire. It does not manage bracket orders, BE
  stop migration, or EAR-style protection order lifecycle.
- Passive harvest belongs to the campaign objective, not LL confirmation. A
  plan can declare a side-aware paid range; once price reaches the floor Kahn can
  work tagged `HARVEST` close limits at passive BBO, increase clip size near the
  stretch edge, and actively clean up remaining inventory if the floor is lost.
  Do not require an owned supply/demand band before lightening a paid target.
- Live orders are tagged with `KH:` in `GroupId`/`Comment`. Kahn only cancels its
  own tagged working orders on stop or explicit operator `FLAT`/`CANCEL`
  control; it does not cancel unrelated account orders.
- Operator controls are separate from campaign evidence. `Control Path` reads
  `KAHN_CONTROL` JSON (`FLAT` or `CANCEL`) before active-window/evidence gates,
  so `FLAT` can close bound exposure after campaign expiry. Existing
  `control.json` contents are marked seen at startup to avoid replaying stale
  controls.
- Runtime file paths are an instance boundary. When more than one KahnRuntime can
  run, configure campaign, control, evidence, decision-log, and checkpoint paths
  under the same symbol/account profile directory, such as
  `...\KahnRuntime\ES\` or `...\KahnRuntime\NQ\`. A shared root `control.json`
  is only acceptable for a deliberate single-instance setup.
- Campaign expiry gates new probe admission only. Once Kahn has managed
  inventory from a pre-expiry fill, evidence evaluation continues after
  `window.expires_at` so add, suppress, reduce, flatten, and retire decisions
  still manage the campaign.
- `FLAT` cancels Kahn-owned working orders, submits Quantower close-position
  requests for all bound live positions, and retires campaign state after
  accepted submission. `CANCEL` retires only when the bound position is flat; if
  exposure remains, it rejects loudly and tells the operator to use `FLAT`.
- Strategy log lines use operator buckets: `INFO:`, `ERR:`, `ENTRY:`, `ADD:`,
  `EXIT:`, `RISK:`, and `FILL:`. The JSONL decision log remains the detailed
  audit source.
- `OnGetMetrics()` populates Quantower's Strategy Manager value window with
  mode, campaign, phase, execution/data symbols, evidence warmup, simulated/live
  quantity, and risk anchor.
- LevelLedger/EAR ownership math is an evidence source, not sufficient
  permission to add. Phase, runway, target proximity, and risk ownership can
  suppress or retire otherwise valid LL participation.
- GexBotMCP may propose futures-space campaign context such as walls,
  zero-gamma, net-GEX movement, and large-strike stress zones. Treat it as
  waypoint and management context only: it may suppress adds, tighten risk,
  harvest, or trigger review, but it must not authorize probe or add decisions
  without LL, footprint, BubbleTape, price acceptance, or explicit campaign
  evidence.
- BubbleTape and footprint/delta evidence are allowed to justify aggressive
  trap probes and target-zone harvest decisions before full LL proof is
  complete. Treat BubbleTape as compressed footprint/delta unless the evidence
  record or run summary proves real non-zero `TradeId` identity; quote hashes
  from MBO resting liquidity are not execution identity.
- Waypoints are semantic roles: `trap_probe`, `press`, `build_trial`,
  `no_add`, `evaluate`, `target`, `risk`, `repair_hold`, and `invalidation`. Do
  not turn them into a linear if-this-then-that script.
- If evidence carries an explicit `waypoint_id`, that waypoint's role is
  authoritative. Nearest-waypoint matching is only a fallback for unlabeled
  evidence; otherwise overlapping zones can let a higher-priority policy steal
  an event that was intentionally routed to another policy.
- Waypoints may require current price to be inside their range. Use this for
  responsive edge trades where a valid rail in the body can justify holding,
  but cannot authorize a worse-location entry or add.
- Risk-anchor failure is directional. Same-side sponsor failure can flatten;
  opposite-side rail failure near the anchor is usually campaign-supporting
  field evidence, not an invalidation by itself.
- `path_stress` waypoints are campaign-risk governors, not repair-entry engines.
  They can suppress adds and harvest exposure into a mature path or full-inventory
  stress zone, but a repaired continuation entry should come from a fresh
  campaign/directive unless explicitly modeled later.

## Current Stage

Stage 1 is live-capable dry-run infrastructure:

1. Load one active campaign plan.
2. Read normalized evidence events from JSONL and live LL transitions.
3. Evaluate deterministic policy modules.
4. Resolve one bounded decision per event.
5. Execute through shadow fill or the broker adapter, depending on settings.
6. Write JSONL decisions, operator log buckets, metrics, and checkpoint state.

Use shadow mode first when validating a new directive shape. Enable broker
routing only on a test account and only after confirming `Symbol`, `Market Data
Symbol`, `Account`, paths, campaign sizing, and runtime quantity cap.
