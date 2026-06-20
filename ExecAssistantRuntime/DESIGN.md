# ExecAssistantRuntime Design Reference

## Purpose

`ExecAssistantRuntime` exists to stop execution leakage after a discretionary
plan has already been chosen.

The important split is:

- planning decides whether an asymmetric opportunity exists;
- live auction discussion decides whether the plan still makes sense as evidence
  emerges;
- the runtime executes a dispatched directive mechanically.

The runtime is not a trader, not an opportunity detector, and not a replacement
for Dost or premarket work. It is a position protocol engine.

## Origin Of The Design

The March-May journal review showed that the best trading days were not mainly
better prediction days. They were days where the plan had clear conditional
structure:

- what must happen for a scenario to become believable;
- what would invalidate the scenario;
- where participation would be possible;
- what area could reasonably be targeted;
- where the trader should stand aside.

LevelLedger later solved a different problem: it made live ownership, failures,
and contested zones visible. That was a genuine execution upgrade, but it also
created a failure mode: the trader can start over-weighting the live tool and
under-weighting the pre-committed auction map.

The execution assistant is meant to reconnect those pieces. Planning remains
discretionary. LevelLedger remains evidence. The runtime only makes sure a
selected plan is acted on without hesitation, over-holding, or fuzzy mid-trade
reinterpretation.

## System Roles

### Premarket Standup

Premarket Standup is a separate skill/workflow. It should debate the day
aggressively before the open and produce scenario cards that can be kept open in
Obsidian.

Its job:

- identify asymmetric opportunities;
- describe required evidence;
- define invalidation;
- define target logic;
- define no-trade zones;
- account for open location and open behavior.

It must not issue mechanical execution unless a scenario has become a concrete
directive.

### Dost

Dost remains the live auction conversation partner. It is useful when structure
and ownership need to be married, when a contested zone resolves, or when the
trader wants to reassess whether a new plan makes sense.

Dost may help formulate a directive, but the runtime should not rely on Dost
being live.

### Exec Assistant Skill

The `exec-asst` skill is the dispatch layer. It should take a human-readable
directive, normalize it, reject ambiguity, and write a structured directive for
the runtime.

It should ask for missing execution-critical fields before dispatching. Once a
directive is dispatched, it should be treated as immutable. A later idea should
be a new directive, not an edit to the active one.

### ExecAssistantRuntime

The runtime is a Quantower `Strategy`. It reads the directive, watches live
Quantower market data, places/modifies/cancels orders, and exits according to
the directive rules.

It does not discover opportunities. It does not decide that a different plan is
better. If the plan changes, the old directive is cancelled or completed, and a
new directive is issued.

### LevelLedger

LevelLedger remains a visual/evidence indicator. It should continue to work even
if the strategy manager is disabled, removed, or bugged.

This is a hard design boundary. The runtime may copy LevelLedger math, names,
and thresholds where needed, but LevelLedger must not become a runtime
dependency.

## Runtime Location

The runtime lives inside Quantower as a `Strategy`, not as an indicator and not
as an external process.

Reasons:

- it needs direct order lifecycle access through `Core.Instance.PlaceOrder`,
  `ModifyOrder`, `CancelOrder`, and `ClosePosition`;
- it needs direct live `Symbol.NewLast`, `Symbol.NewQuote`, `Symbol.NewLevel2`,
  and DOM access;
- it should run independently of chart paint, chart focus, or any attached
  indicator;
- it can expose explicit `Symbol` and `Account` settings;
- it can be stopped from Strategy Manager without touching LevelLedger.

An indicator can technically place orders, but it is the wrong lifecycle owner
for execution. An external process can read files or MCP data, but it should not
be the first-class execution runtime because parquet/MCP data can lag and is
better suited for replay and audit.

## Isolation From LevelLedger

The preferred architecture is code duplication or copied engine fragments rather
than a shared library, at least until the runtime proves itself.

The reason is operational safety. LevelLedger is part of the regular trading
desk. If the execution engine is disabled, broken, or temporarily abandoned,
LevelLedger must remain unaffected.

Acceptable duplication:

- LF/HF detection math;
- build-band/ownership thresholds;
- failure-zone state transitions;
- grey-zone classification;
- tick-keyed price utilities;
- pseudo-L2 filtering rules.

Unacceptable coupling:

- runtime requiring a LevelLedger indicator instance to exist;
- runtime reading LevelLedger painter or panel state;
- shared mutable state between indicator and strategy;
- changes to runtime math forcing LevelLedger behavior changes.

If code is copied, drift should be managed deliberately. Add comments naming the
source concept, not references to fragile line numbers. When runtime behavior
diverges, document why.

## Data Sources

Runtime execution should use live Quantower data directly:

- L1 quote stream for executable best bid/ask used by order routing,
  profitability, and broker-protection decisions;
- trade stream for prints and aggressor flow;
- L2 heartbeat and sampled DOM, including DOM-derived best prices and midpoint,
  for all ownership/failure math;
- Quantower order/position/trade collections for execution state.

L1-versus-DOM agreement is a stale/queued-book guard only. L1 must never be
substituted into an accepted evidence snapshot; if L2 cannot provide the book,
evidence processing fails closed while existing execution protection may keep
using L1.

MarketRecorder/parquet and MCP are for replay, audit, backtest, and research.
They are not the live execution feed.

## Directive Philosophy

A directive is an executable contract for one trade idea.

It should include:

- unique id;
- side;
- base quantity;
- add quantity;
- maximum position quantity;
- explicit permission to add;
- activation condition;
- invalidation condition;
- add gates;
- stop rule;
- target rule;
- terminal flatten triggers;
- expiry/session window;
- optional notes from the planning conversation.

It should not include symbol or account. Those are bound to the Quantower
strategy instance. To trade a different symbol or account, instantiate a
separate strategy instance with its own settings and directive path. Multi-symbol
operation is out of scope.

Once dispatched, a directive should not be edited in-place. If the market creates
a second leg, that is a new directive. If the first directive is wrong, cancel or
invalidate it.

`max_clips` is intentionally not used in the normative schema. It becomes
ambiguous when the base and add sizes differ. Use `base_quantity`,
`add_quantity`, and `max_position_quantity`.

This intentionally splits later legs and materially changed plans into separate
directives instead of one judgement-heavy hold. A single directive may still
build a campaign when fresh add resolutions occur. What it may not do is turn a
completed target exit or invalidated execution path into an improvised runner.

## Directive Lifecycle

The dispatched JSON envelope is immutable and active-only. Its `status` is
always `active`; terminal states are runtime outcomes written to the event log,
not edits to the input file.

Runtime lifecycle states are:

- `draft`: exists only in the human/skill layer and is not visible to runtime;
- `active`: runtime may act;
- `cancelled`: an explicit `CANCEL_DIRECTIVE` command ended the directive;
- `invalidated`: market evidence or `FLAT` invalidated the execution path;
- `completed`: target, breakeven, LF/HF, or another terminal exit completed it;
- `expired`: its execution window passed;
- `error`: runtime could not proceed safely.

The runtime must be idempotent. Re-reading the same active directive cannot
place duplicate orders. Any execution-field mutation under an accepted id is an
error, even if the file still validates. Cancellation is an immutable control
command, not a status edit. A new trade idea requires a new id and cannot take
ownership until the prior directive is terminal or an explicit control command
has ended it.

### Operator-Visible Lifecycle Log

The append-only JSONL event log remains the canonical audit record, but it is
not sufficient as the operator's immediate status channel. Quantower Strategy
Manager's visible strategy log must receive concise, deduplicated messages for
human-significant lifecycle events:

- runtime start/stop and live versus shadow mode;
- directive accepted, rejected, armed, invalidated, cancelled, expired, or
  completed;
- base/add submission and fill, current quantity, and weighted average;
- breakeven and hard-target protection establishment or failure;
- sponsor promotion and sponsor failure;
- HF/LF flatten, including HF/LF invalidation while flat;
- accepted `CANCEL_DIRECTIVE` or `FLAT` control;
- data loss, recovery action, halted state, and errors requiring intervention.

Routine quotes, candidate updates, rail tests, and repeated state paint do not
belong in the visible log. Each message includes the directive id, mode, side,
state/reason, and relevant quantity/price so the operator can understand the
runtime without polling through `exec-asst`. Errors and safety actions use the
error severity; normal lifecycle changes use the ordinary strategy-log
severity. No custom audio, popup, or chart UI is required.

## Directive Schema

The normative Draft 2020-12 schemas are:

- [`trade-directive-v1.schema.json`](trade-directive-v1.schema.json);
- [`control-command-v1.schema.json`](control-command-v1.schema.json).

The trade schema fully enumerates the transport shape. A scaling-enabled
directive looks like:

```json
{
  "schema_version": 1,
  "kind": "TRADE_DIRECTIVE",
  "id": "2026-06-19-short-01",
  "status": "active",
  "created_at": "2026-06-19T10:05:00-04:00",
  "side": "short",
  "window": {
    "not_before": "2026-06-19T10:05:00-04:00",
    "expires_at": "2026-06-19T11:30:00-04:00"
  },
  "entry": {
    "mode": "contest_transition",
    "order_price_range": { "lower": 30475, "upper": 30550 },
    "context_price_range": { "lower": 30380, "upper": 30550 },
    "add_price_range": { "lower": 30380, "upper": 30550 },
    "pre_entry_invalidation": null,
    "allowed_resolutions": [
      "direct_conversion",
      "supported_reclaim"
    ]
  },
  "sizing": {
    "base_quantity": 2,
    "add_quantity": 1,
    "max_position_quantity": 5,
    "adds_allowed": true
  },
  "retries": {
    "max_base_reentries": 3
  },
  "stop": {
    "base": "reverse_entry_resolution",
    "leveraged": "weighted_breakeven",
    "opposite_failure_object": "flatten"
  },
  "target": {
    "mode": "HARD_TP",
    "price": 30380,
    "direction": "below"
  },
  "notes": "Human planning context for audit only"
}
```

The schema settles these transport semantics:

- `order_price_range` controls where the quote may be when a base order is
  initiated;
- `context_price_range` controls which live anchors and failed objects may
  participate in a resolution;
- `add_price_range` separately bounds add resolutions and is `null` when
  scaling is disabled;
- all price ranges are inclusive after runtime tick normalization;
- `pre_entry_invalidation` is explicit and never inferred from a range;
- `max_base_reentries` means attempts after the initial base attempt;
- `adds_allowed: false` requires `add_quantity: 0` and a null add range;
- long targets point `above`, short targets point `below`;
- long pre-entry invalidation, when present, points `below`; short invalidation
  points `above`;
- stop policy is fixed to semantic base invalidation, weighted breakeven after
  leverage, and complete flatten on the opposite LF/HF object;
- notes and target reference labels are audit-only and cannot change behavior.

JSON Schema cannot express every relational invariant. The runtime semantic
validator must additionally reject:

- `lower > upper` in any range;
- `not_before >= expires_at`;
- timestamps without a valid ISO-8601 offset or values that cannot be converted
  into the strategy instance's session clock;
- `max_position_quantity < base_quantity`;
- scaling enabled when maximum quantity cannot accept one complete add;
- scaling disabled when maximum quantity differs from base quantity;
- order or add ranges not contained by the context range;
- prices that cannot be normalized to the bound symbol tick size;
- `HARD_TP` directives with no executable runway at acceptance;
- a reused directive or command id with a different payload digest.

Symbol and account are absent by design. They are bound to the Quantower
strategy instance. Target prices remain mandatory in v1; a label such as `IBH`
or `rail` is context, not a substitute for price.

## Execution Model

The execution model uses a base position followed by optional smaller adds:

- enter `base_quantity` when the first valid resolution completes;
- add `add_quantity` only after a fresh, independent same-side resolution;
- never exceed `max_position_quantity`;
- treat maximum quantity as a ceiling, not a position-building objective;
- after the first add fills, protect the complete position at its actual
  weighted breakeven;
- track the currently promoted causal sponsor internally and market-flatten on
  its confirmed failure;
- exit the complete position when a terminal condition fires;
- do not trim individual clips or preserve a discretionary runner.

A useful sizing shape is a larger base with smaller adds, for example base `2`,
add `1`, maximum position `5`. The first add moves weighted breakeven only one
third of the way from the base price to the add price. The next additions move
it by one quarter and one fifth of their distance from the current average.
Later adds therefore have progressively less ability to damage a good base
location. Sponsor protection is independent of this arithmetic: weighted
breakeven remains the broker-native emergency stop, while sponsor failure is an
evidence-conditioned market exit.

This is not free risk reduction. A two-contract base makes every failed base
attempt twice as expensive as a one-contract base. That tradeoff is intentional
and remains a planning decision. The runtime must not invent an arbitrary
stop-distance or risk/reward cap to compensate.

`adds_allowed` is a required human permission flag, not a day-type prediction.
When true, the runtime still adds only on fresh resolution evidence. When false,
it never adds. The runtime does not infer that a campaign must exist from the
configured size capacity.

## Entry Mechanics

The runtime should not encode trade type.

An IB initial-drive failure, an IB extreme test failure, an 11:30 reversal, a
2:30 reversal, and a same-side continuation directive all use the same execution
mechanics once the trader has selected the opportunity. The human layer decides
why the opportunity is asymmetric. The runtime only watches a bounded price
envelope for one of two objective resolution families.

### Direct Conversion

For a long, supply is consumed into demand at the same location. The converted
demand is positive ownership evidence and becomes the entry anchor.

For a short, demand is consumed into supply.

Direct conversion is stronger than a band merely appearing. It creates a wall
that can justify immediate entry and can remain eligible for a later retest. A
conversion can also happen as delayed re-establishment: a failed opposing band
is replaced by fresh same-side ownership in the same or overlapping zone after
contest. The new object must establish and survive; relabeling an old failed
object is not enough.

For v1, direct conversion is executable only when the original opposing
candidate completes LevelLedger's normal `CONSUMED` confirmation: eight ticks
of adverse displacement held for ten seconds. A nearby opposite candidate does
not accelerate that decision. Once `CONSUMED` is confirmed, route immediately;
there is no additional execution delay.

### Supported Reclaim

For a long:

1. live demand exists below or overlaps a supply object;
2. that supply fails;
3. the demand remains live;
4. price reclaims or departs upward through the failed supply;
5. the completed transition triggers the base entry.

For a short, invert the sequence: live supply is above or overlaps demand, the
demand fails, and price departs downward through the failed demand.

The supporting anchor may form before or after the opposing failure. A
confirmed anchor may be pre-existing and arbitrarily old if it remains live and
is eligible under the directive's price context. The researched candidate fast
path is narrower: the candidate must already be active when the confirmed
opposing rail emits `FAIL`, and all of the following must hold:

- it already satisfies LevelLedger's cluster thresholds;
- price has displaced eight ticks in its favor for at least four uninterrupted
  seconds;
- it is correctly positioned below or overlapping failed supply for a long,
  or above or overlapping failed demand for a short;
- its edge is no more than twenty ticks from the failed opposing object;
- neither direction nor market-data continuity reset during the timer.

If the opposing rail fails before the candidate has persisted for four seconds,
keep the transition pending only until that timer completes. If the candidate
resets first, the transition does not fire. A candidate farther than twenty
ticks away must reach normal ownership confirmation before it can support the
reclaim. A candidate that appears only after `FAIL` also requires normal
ownership confirmation. The runtime cares about object state and topology, not
age alone.

The following are explicitly not entries:

- opposing failure by itself;
- a plain new same-side band by itself;
- for a long, supply failure followed only by demand above the failed supply;
- for a short, demand failure followed only by supply below the failed demand;
- repeated paint, test, or hold messages from one unresolved contest;
- a broad interpretive instruction to find auction failure anywhere.

Failure is negative evidence: one side did not control that object. It does not
prove that the other side controls the auction. Direct conversion and supported
reclaim supply the missing positive evidence without asking the runtime to make
an interpretive auction call.

This keeps the directive mechanically bounded:

```json
{
  "entry": {
    "mode": "contest_transition",
    "side": "long",
    "order_price_range": { "lower": 30390, "upper": 30540 },
    "context_price_range": { "lower": 30380, "upper": 30540 },
    "allowed_resolutions": [
      "direct_conversion",
      "supported_reclaim"
    ]
  }
}
```

The runtime should reject broad interpretive requests such as "look long if
selling fails anywhere." The bounded range and eligible evidence objects must be
specific enough to evaluate mechanically.

## Entry Order Policy

NQ v1 uses vanilla market orders for base entries and adds. Market and ordinary
limit behavior are the portable broker contract; IOC and synthetic cancellation
timing are not assumed. At the strategy's small quantity, missed participation
and adverse passive fills are the larger known risks. Slippage optimization
waits for measured evidence.

For direct conversion:

- submit at market when `CONSUMED` confirms and the executable quote is within
  twenty ticks of the converted wall;
- if price has departed farther, remain armed and submit at market on the first
  live return inside that envelope while the wall remains valid;
- do not park a passive order at the wall.

For supported reclaim:

- when same-side support is already valid within twenty ticks of the failed
  opposing band, submit at market when that failure confirms;
- when the final evidence confirms after price has already crossed, submit
  immediately at the current market while the quote remains inside the human's
  `order_price_range`;
- do not weaken evidence to manufacture a historical boundary fill, and do not
  leave a stale passive order waiting for a return.

For a long, quote eligibility and distance use best ask. For a short, they use
best bid. Midpoint and last trade are audit context only. A fresh quote must be
observed at or after the trigger transition. If it is outside the directive
range, the runtime records `MISSED` and does not chase the same epoch.

Ordinary resting limits remain appropriate for `HARD_TP`. Breakeven uses a
broker-native stop-market when available. Semantic stops, LF/HF, target exits,
`CANCEL_DIRECTIVE`, and `FLAT` prioritize completion and use market closing
behavior.

### Fill Telemetry

The runtime must measure before optimizing. Every order attempt records:

- band IDs, side/source/state, boundaries, and evidence timestamps;
- bid/ask and quote age at trigger and immediately before submission;
- order request/result, broker order updates, fills, and position changes;
- requested, filled, and remaining quantity plus actual fill prices;
- distance from the relevant band at trigger and fill;
- detection drift: submission quote versus trigger quote;
- transport slippage: fill versus executable submission quote;
- total implementation cost: fill versus executable trigger quote.

Use UTC timestamps for reconstruction and a process-local monotonic clock for
latency. This separates LevelLedger confirmation delay, runtime scheduling,
broker transport, spread, and true market impact. More elaborate routing is out
of scope until these logs show a recurring material problem.

## Execution Evidence Versus LevelLedger Paint

LevelLedger's ownership rails are designed for visual trust. That is different
from execution timing.

Current LevelLedger ownership defaults intentionally wait for stable acceptance:

- candidate cluster: at least three same-side events within ten ticks and
  ninety seconds, with aggregate score at least eight;
- rail confirmation: price moves eight ticks away and remains accepted for ten
  seconds;
- failure confirmation: price breaches the rail and either moves far enough
  through it or remains through it long enough;
- display selection favors stable, sparse, readable objects.

Those delays are correct for chart paint. Only one bounded execution case has
enough independent evidence to shorten them.

### Candidate Timing Research

`LevelLedger/research/candidate_timing_probe.py` replayed full RTH windows for
NQM6 on June 11-12 and NQU6 on June 16-18, with ninety minutes of warmup. It
preserved LevelLedger's cluster and eight-tick displacement thresholds.

Across the five sessions:

- 824 candidates resolved only 52.2% toward their original evidence side;
- 2,461 directional displacement episodes were only 45.5% stable after two
  seconds, 67.0% after five seconds, and 94.5% after ten seconds;
- explicitly pairing nearby opposite candidates did not repair direct
  conversion: even after five seconds, only 61-63% of the tested pairs survived;
- 41 supported-reclaim observations combined candidate displacement with the
  independent failure of a confirmed opposing rail;
- within twenty ticks, 31 of 32 active displacement episodes reached normal
  confirmation; the one failure reset after 3.1 seconds, while all 31 episodes
  that persisted for four seconds reached confirmation in this sample.

The supported-reclaim sample is small, so the four-second threshold is an
initial execution rule to audit in live logs, not a claim of universal win
probability. Its structure is nevertheless materially different: the failed
owned rail is independent proof that the opposing side lost control. Bare
candidate conversion has no equivalent proof and retains the visual ten-second
confirmation.

The June 18 fixture validates the practical timing. Supply failed around
10:03:30 while the nearby demand candidate had only one second of favorable
displacement. The four-second rule would have triggered around 10:03:33 near a
`30515.50` sampled midpoint, roughly six seconds before normal ownership paint
near `30524.50`, without acting on raw formation.

The runtime should copy the same event vocabulary and book math, but maintain a
separate execution object model:

- `candidate`: clustered same-side evidence has appeared;
- `live_anchor`: candidate or confirmed rail is inside the directive range and
  has not failed;
- `resolution_epoch`: the bounded set of related candidate, failure,
  conversion, reclaim, and re-establishment events that can authorize at most
  one fill;
- `trigger_transition`: a direct conversion or supported reclaim completes;
- `entry`: submit immediately according to the directive's execution policy;
- `logic_stop`: flatten only after the reverse contest transition, not after
  the first noisy tick through an entry price.

Raw `candidate` or `FORM` state is memory, never an executable event by itself.
The runtime may act before LevelLedger paint only through the four-second
supported-reclaim fast path above. Direct conversion, a plain same-side band,
and target continuation all require normal confirmed ownership unless they are
part of that independently supported transition.

The paint layer asks, "what ownership can I trust on screen?" The execution
layer asks, "has this specifically bounded contest resolved with independent
proof quickly enough that waiting becomes the risk?"

An epoch is consumed when it authorizes a fill. Later paint confirmation,
retests, holds, or a lower supply/demand object produced by the same unresolved
contest cannot authorize another clip. This is the primary guard against
double-counting evidence in fast open-auction rotations.

### Resolution Epoch Identity

Epoch identity is causal, not an arbitrary price-and-time bucket:

- an epoch is rooted in the opposing candidate or owned object that must fail
  or convert, together with any same-side anchor used to prove that resolution;
- one epoch may emit `FORM`, displacement, `FAIL`, `CONSUMED`, `OWNED`, `TEST`,
  and `HOLD` messages, but they remain one resolution;
- the epoch is consumed as soon as it authorizes any confirmed fill; later
  messages or retests from those objects cannot authorize another clip;
- a new add epoch requires a fresh opposing candidate formed strictly after the
  previous fill, followed by its own direct conversion or supported reclaim;
- a base retry requires a fresh opposing candidate formed after the prior
  flatten and order reconciliation;
- an old still-live same-side anchor may support a fresh epoch, but cannot
  create one; a plain new same-side band cannot create an add epoch either;
- a market-data discontinuity makes any unresolved candidate epoch ineligible
  rather than aging it through the gap.

The new opposing candidate may form at the same price as an old one. Object
lineage and formation after the fill/flatten boundary, not spatial novelty by
itself, make it fresh. One epoch authorizes one order objective and one clip;
partial-fill handling must preserve that identity without issuing replacement
quantity twice.

## 2026-06-18 Entry Fixture

The 2026-06-18 NQU6 open is the reference fixture for the first long entry
family.

The relevant sequence:

- a valid lower demand shelf existed around `30402.75`;
- demand formed around `30497-30499`;
- supply formed around `30504-30504.50`;
- supply failed upward at roughly `10:03:29`;
- the `30497-30499` demand became fully owned only later, around `10:03:39`;
- by the time the fully owned rail was visible, price had already left the
  executable area.

Tick replay showed the practical consequence:

- after `10:03:29`, a buy limit at `30499` did not fill in the immediate entry
  window;
- after `10:03:39`, a buy limit at `30499` never filled before the target
  sequence;
- a passive limit back at the failed supply area filled only much later, when
  the auction had already changed;
- the mechanically valid execution was the supply failure while the demand
  anchor was alive, not waiting for the visually comfortable rail.

Design conclusion: do not rest a passive order at the mouth of the anchor before
proof, and do not leave a stale passive order there after proof. Enter on the
contest transition. If the price is still available, limit. If it has already
left, marketable order.

## 2026-06-17 Open-Auction Fixture

The post-10:15 short is the reference fixture for an ambitious target that does
not suspend campaign protection: short inside `30450-30550`, base quantity two,
add quantity one, maximum position five.

Relevant behavior:

- demand at `30479-30482` converted into supply and authorized a two-contract
  retest entry around `30477.50` near 10:20:48;
- no fresh add resolution completed inside the add range, so maximum quantity
  remained a ceiling and the position stayed base-only;
- price first crossed `30360` near 10:47:26, reached `30284.75`, then reclaimed
  the area;
- demand around `30363-30366` established and produced a fresh LF, terminating
  the short around `30377` near 10:50:38;
- the launch/sponsor area was subsequently reclaimed. Later downside did not
  restore the completed campaign.

An intentionally over-ambitious hard target at `30270` would not have changed
that exit. Price did not first reach `30270` until about 14:02 and later traded
substantially lower, but LF and sponsor protection remain active before a hard
target. The afternoon decline was a new auction sequence requiring a new
directive.

This fixture establishes that a target is an objective, never a hold-until
instruction.

## 2026-06-16 Campaign Fixture

The post-10:00 short is the reference fixture for a campaign-capable directive.
The bounded replay uses `30820-30890`, base quantity two, add quantity one, and
maximum position five.

The production evidence/coordinator replay produced:

- a two-contract supported-reclaim base near `30828` around 10:13:48;
- one direct-conversion add near `30801.75` from supply around
  `30806-30808`;
- one direct-conversion add near `30770.50` from supply around
  `30773-30775`;
- four contracts at a weighted average near `30807.06`, with no base retry.

The `30780-30783` demand failure and the subsequent `30773-30775` conversion
belonged to one resolution epoch, not two adds. The campaign therefore reached
four contracts, not the configured maximum of five. Again, maximum size was a
ceiling.

Supply at `30773-30775` sponsored the first break below `30750` and remained
intact. Local counter-demand below it repeatedly failed; later lower supply
established. The prior design claim that the `30728-30730` conversion required
a target-decision exit was incorrect because that local object did not defeat
the causal sponsor.

## 2026-06-18 Sponsor-Handoff Fixture

The later June 18 long establishes why the runtime needs sponsor succession
even when the directive uses a fixed hard target. This is an evidence/design
fixture, not a claim that the current coordinator carried a position through
the sequence; existing breakeven/HF protection completed the replayed campaigns
earlier.

- demand around `30636-30640` sponsored the first move through `30675`;
- several supply objects above the gate survived temporarily but failed before
  defeating that demand;
- after those supplies failed, new demand established around `30691-30693`;
- that accepted higher demand became the promoted sponsor around 12:39;
- the promoted sponsor failed around 12:45:10 while price was near `30684`,
  requiring a market flatten regardless of the later rally.

Promotion is therefore a one-way handoff. Once higher demand or lower supply
becomes the current sponsor, protection must not fall back to an older remote
object merely because the older object remains live. Subsequent validating
evidence belongs to a new campaign after the flatten.

## Adversarial Wrong-Direction Fixture

A deliberately biased June 16 long demonstrates what the runtime must and must
not protect against.

For a long activated after 09:55 above `30750` with an ambitious hard target at
`30884`, the target does not suspend entry-anchor, sponsor, or LF/HF protection.
The first valid supported reclaim produced only a small extension before its
clean execution path failed and the directive completed. Later long triggers
were irrelevant.

For the same long activated after 10:00, two valid countertrend base attempts
could stop before any add occurred. Breakeven protection never activated. Those
losses are expected consequences of a wrong human directive; the runtime must
not hide them behind arbitrary stop-distance, risk/reward, or backtest-derived
caps.

The human response to an unexpectedly large semantic stop is to reassess, flip,
stand aside, or issue `FLAT`. If no control command arrives, the runtime remains
obedient and may take another fresh retry within the directive contract.

## 2026-06-11 Canonical State-Machine Fixture

The June 11 NQM6 session is the canonical end-to-end fixture. It is not a PnL
backtest. It verifies that the same state machine behaves coherently through a
failed early short, repeated human reissues, an unscheduled squeeze, late long
campaigns, fixed targets, and repeated local failure objects.

### Reissued Shorts

A short activated after 12:25 below `29000`, with a hard target below `28600`, found
a supported reclaim near 12:29. A formal LF printed at 12:30:24 before any add,
so the base flattened and the directive became terminal. The later continuation
lower did not make that local LF exit wrong.

When the short was reissued after 12:35, a supported reclaim around `28875` and
a direct-conversion add around `28870` produced a leveraged position. Its normal
retest crossed weighted breakeven, so the campaign completed near flat. With
scaling disabled, the same base would instead have remained live until the
13:09 LF and exited materially lower. This difference is intentional: invoking
campaign scaling also invokes immediate whole-position breakeven protection.

A third short reissued after 12:55 entered much lower after pre-existing demand
failed under surviving supply. A second lower demand failure belonged to the
same traversal epoch and did not add. The 13:09 LF flattened the base for a
material loss even though price later continued lower. This is the canonical
warning that repeated human reissues can accumulate damage. The runtime limits
each attempt and withholds unjustified leverage; it cannot make strategic
stubbornness harmless.

### Squeeze Participation

A long activated at 13:28 above `28940`, with a hard target above `29250`, did not
chase the vertical squeeze. The first supply failure above the entry floor had
no eligible supporting demand inside the directive's context range. The runtime
waited until supply around `29139-29142` converted into demand at 13:37:54 and
entered the base near `29174`.

Supply around `29216-29219` converted into demand at 13:42:58 and authorized one
add near `29240`. The hard target completed the directive near `29250` at
13:43:14. Demand that later established around `29253-29259` belonged to a new
possible campaign and could not keep the completed directive open.

This is the reference behavior for a fast squeeze: no random probing, no
repeated scratching, no fill simply because price crossed the activation floor,
and no forced use of maximum quantity. Late evidence is preferable to an
unmanaged ideal price.

### Late Long Reissues

A long activated after 13:50 above `29050`, with a hard target above `29320`, entered
on direct conversion around `29168-29175`, then added on independent conversions
around `29215-29219` and `29248`. The four-contract weighted average was around
`29200-29204`. Price crossed it at 14:01:55-14:01:58, before the demand stack
failed. Breakeven completed the directive correctly.

Reissued at 14:03, the long entered around `29180`, added around `29219`, and
added again around `29232`. Weighted breakeven near `29203` flattened the
campaign at 14:22:09, four seconds before base demand failed.

Reissued again at 14:30, the long took one base stop from roughly `29208` to
`29190`. A fresh supported reclaim then authorized a base retry around `29245`.
A new HF at 14:47:34 flattened that base around `29243` before any add. The
eventual trade above `29320` at 15:11 belonged to a later leg, not this terminal
directive.

The discretionary trader held some of this late rally because repeated HFs were
quickly invalidated and little selling interest remained after the squeeze.
That late-session judgement is intentionally outside the runtime. An HF is a
valid local flatten trigger even when it later invalidates. Fresh evidence after
invalidation may justify a new directive; it does not retroactively authorize
holding the old one.

### Required Assertions

Deterministic replay of June 11 must assert all of the following:

- an activation-floor cross alone never places an order;
- a plain band, repeated hold, or same-epoch confirmation never adds;
- supporting evidence outside `context_price_range` cannot authorize entry;
- maximum quantity is a ceiling and is never filled without independent adds;
- the first filled add immediately changes the state to `LEVERAGED` and arms
  whole-position weighted breakeven;
- a leveraged breakeven flatten is terminal even when the planned direction
  later resumes;
- a base semantic stop may re-arm only from a fresh epoch and within the retry
  allowance;
- LF/HF flatten the opposite side and terminate the directive;
- failure objects already live at activation are context, not immediate flatten
  triggers; only a fresh post-activation failure epoch may trigger;
- a fixed hard-target fill completes the directive before any later evidence
  may act;
- a causal same-side sponsor can promote only in the favorable direction, and
  failure of the currently promoted sponsor market-flattens the campaign;
- sponsor promotion never moves the broker breakeven stop to a sponsor edge;
- LF/HF remain unconditional terminal events rather than waiting to see whether
  a sponsor later fails;
- a fresh LF/HF while flat invalidates an armed directive and requires a human
  reissue instead of producing a no-op flatten;
- every reissue starts with a new id, fresh counters, and an activation baseline;
- no terminal directive can reactivate when later evidence validates its old
  thesis.

## Academic Reference Points

There is relevant market-microstructure literature, but it should be treated as
supporting language rather than a replacement for the directive grammar.

Useful concepts:

- Order-flow imbalance: Cont, Kukanov, and Stoikov model short-horizon price
  changes from net order-book event imbalance, including limit orders,
  cancellations, and trades. This supports using L2 event transitions instead
  of trade prints alone.
  <https://arxiv.org/abs/1011.6402>
- Queue imbalance: Gould and Bonart show bid/ask queue imbalance has predictive
  power for the next mid-price movement, especially in large-tick names. This is
  adjacent to the runtime's need to know whether the immediate book favors
  limit, marketable-limit, or market execution.
  <https://arxiv.org/abs/1512.03492>
- Meso-scale resiliency: Bechler and Ludkovski find that limit-order flows and
  addition/cancellation rates can matter more than trade imbalance alone, and
  that deeper book shape matters on the execution-scheduling timescale. This
  supports keeping depth-shape and refill/repair logic available for add/exit
  decisions.
  <https://arxiv.org/abs/1708.02715>
- Post-shock resiliency: Xu et al. study spread, depth, and order intensity
  after effective market orders. This maps to the runtime's question of whether
  a fast market entry is likely to be followed by same-side refill or by adverse
  retest.
  <https://arxiv.org/abs/1602.00731>

What these papers do not provide is a turnkey discretionary-trading entry rule.
They describe measurable LOB pressure, imbalance, and resiliency. The runtime
still needs the human-dispatched directive to define the price envelope,
opportunity context, target, and invalidation. The useful build takeaway is to
log enough raw state around each candidate/trigger/fill to later test whether
queue imbalance, OFI, or resiliency metrics improve execution policy.

## Activation

Activation is not opportunity discovery. The plan has already said what to look
for.

Examples:

- long if selling initiative fails inside ETH and demand survives;
- long after LF/demand sustains inside IB;
- short if prior supply re-establishes above a balance edge;
- trade a grey zone only after new evidence supports it after contest.

Activation must be specific enough for the runtime to evaluate. If a directive
says only "look long if bullish", it should be rejected by `exec-asst`.

At acceptance, the runtime snapshots the currently live LF/HF objects. They may
remain contextual evidence, but they cannot immediately flatten the new
directive. Only a fresh failure epoch after activation is a terminal LF/HF
trigger. If the directive is positioned, that event market-flattens and
completes it. If it is flat but still armed, the same event invalidates the
directive without sending a meaningless close request. In either case later
evidence requires a human reissue with a new id. Ordinary demand/supply anchors
are different: a pre-existing anchor may participate at any age when it is
still live and intersects `context_price_range`.

Activation does not reconstruct an entry resolution that completed before the
directive arrived. Existing anchors may support a fresh post-activation
transition, but an opposing failure that already completed is not replayed when
later context is inspected. A late directive may therefore miss the original
trade. That cost belongs to dispatch timing; the runtime must not blur context
into a synthetic trigger to recover it.

Entry eligibility, contextual anchor eligibility, and pre-entry invalidation are
separate concepts. A phrase such as "long above 30750" may define where an order
may be submitted while still allowing lower demand to support a reclaim. It must
not silently become a hard stop or pre-entry invalidation boundary.

If an explicit pre-entry invalidation is breached before a valid trigger
transition occurs, the directive invalidates without trade. If price later snaps
back and the trader still wants the idea, issue a new directive.

The runtime should not rescue a breached pre-entry directive by inventing a new
auction-failure interpretation. That belongs to the human/Dost/exec-asst layer.

## Base Retries

A stopped base position may re-arm inside the original directive contract.
Retries exist because open-auction contests can produce one or two mechanically
valid failures before a durable resolution appears.

Retry rules:

- retries apply only while the position has never exceeded base quantity;
- the failed resolution epoch is retired;
- a new attempt requires a fresh direct conversion or supported reclaim after
  the prior flatten;
- repeated state messages or a second fill from the same failed object are not
  fresh evidence;
- older anchors remain eligible only if they are still live and a new trigger
  transition forms around them;
- pre-entry invalidation, expiry, target completion, LF/HF, `FLAT`, or exhausted
  retry allowance terminates re-arming;
- once any add fills, later flattening terminates the directive and cannot retry.

The runtime should emit a high-visibility base-stop event containing quantity,
loss in points, retry count, and whether the directive remains armed. It must not
interpret the size of the loss or auto-halt from an arbitrary threshold.

## Add Mechanics

An add is not another entry search and is not a response to spare quantity.
It requires a fresh same-side resolution after the prior fill.

Eligible add evidence is intentionally stringent:

- fresh opposing ownership converts directly into same-side ownership; or
- fresh opposing ownership fails and new same-side ownership establishes or
  re-establishes as a durable wall;
- the resolution occurs inside the directive's add-eligible price context;
- the previous entry/add resolution epoch has already been consumed;
- the new event advances or independently reinforces campaign ownership.

The following do not add:

- a plain same-side band appearing in weak new auction space;
- a retest or hold of the object that authorized the previous fill;
- the same demand/supply area failing repeatedly inside one unresolved contest;
- a confirmation object that merely completes the previous resolution;
- evidence outside the directive's add-eligible range;
- any event at or beyond the fixed hard target, where no executable runway
  remains.

One resolution epoch can authorize at most one add. `adds_allowed: false` is a
hard human veto. Otherwise, these evidence rules decide whether the campaign
uses zero, some, or all available quantity.

## Position States

The execution state machine distinguishes evidence burden by position state:

- `ARMED`: flat and eligible for a base resolution;
- `BASE_ONLY`: base position is live and protected by its semantic entry stop;
- `LEVERAGED`: at least one add has filled; weighted breakeven and terminal
  adverse rules are active;
- `RECOVERY_PROTECTED`: a pre-existing profitable position was found after
  restart; no old L2 evidence may act, weighted breakeven is installed, and
  only fixed-price exit protection remains;
- `HALTING`: emergency control is cancelling orders and flattening;
- `HALTED`: no directive may act until an explicitly new directive is accepted;
- `COMPLETED`, `INVALIDATED`, `EXPIRED`, `ERROR`: terminal trade-directive
  states.

Sponsor protection is an orthogonal tracked object, not a separate target
state. `BASE_ONLY` and `LEVERAGED` may each carry a current sponsor id and its
lineage. `HARD_TP`, weighted breakeven, LF/HF, and sponsor failure retain their
own precedence; reaching an unsupported decision-mode price does not create a
new execution state.

## Restart And Forward-Only Data Loss

Strategy restart, Strategy Manager restart, and an L2 continuity break destroy
the runtime's evidence memory. Level 2 is forward-only, so old rails, candidate
timers, LF/HF baselines, retries, and resolution epochs cannot be reconstructed
reliably from the live feed. The runtime must not resume normal management from
the directive file alone.

Recovery is account-and-symbol scoped:

- cancel all runtime-tagged entry, add, and semantic evidence orders;
- if the bound net position is flat, cancel the old directive and require a
  fresh directive;
- if the position is losing at the current executable quote, flatten it;
- if the position is profitable and a protective stop at actual weighted
  breakeven is valid and accepted, enter `RECOVERY_PROTECTED`;
- if cost basis, quote freshness, side, quantity, or protective-order state is
  ambiguous, or breakeven protection is rejected, flatten;
- do not add, retry, rebuild an old candidate timer, or react to newly rebuilt
  rails while in `RECOVERY_PROTECTED`.

A valid fixed `HARD_TP` may be retained or recreated. Sponsor lineage cannot be
reconstructed after restart, so recovered positions do not resume sponsor
promotion or sponsor-failure exits. They exit only by retained/recreated hard
target, breakeven, or explicit `FLAT`. A fresh directive cannot take ownership
until the recovered position is flat.

Profitability and breakeven validity use executable bid/ask, not last trade or
unrealized-PnL display. For a long, the breakeven sell stop must be valid below
the current executable market; for a short, the buy stop must be valid above
it. This recovery path protects a surviving position but never pretends that
lost L2 state still exists.

## Stops

While only the base is live, the stop is the invalidation of the entry reason.

Examples:

- long from direct conversion: stop is the converted demand failing with
  opposing supply holding or re-establishing;
- long from supported reclaim: stop is failure of the supporting demand plus a
  reverse supply resolution through the reclaimed area;
- short from direct conversion: stop is the converted supply failing with
  opposing demand holding or re-establishing;
- short from supported reclaim: stop is failure of the supporting supply plus a
  reverse demand resolution through the reclaimed area.

The first implementation maps that grammar mechanically:

- candidate support consumed directly into the opposite side is an immediate
  reverse resolution;
- failure of a confirmed support/converted rail arms invalidation, but does not
  flatten by itself;
- a fresh confirmed opposite rail within twenty ticks of the failed support
  completes the reverse resolution and flattens;
- a candidate merely resetting inside the eight-tick displacement threshold is
  not a stop.

This mapping remains a replay and demo audit surface. The event log preserves
both the early reset and eventual reverse resolution so later diagnosis can
show whether the twenty-tick completion rule is too narrow or too permissive.

The stop is not "a few ticks beyond entry." NQ often invalidates a band by a few
ticks and then continues. The runtime should flatten on the reverse of the entry
logic, not on arbitrary proximity to the fill.

After the first add fills, the runtime immediately moves the complete position
to actual weighted breakeven. It does not wait for the add-producing object to
retest or hold. Every later add updates that weighted average from confirmed
fills. The breakeven order protects against the directive itself being wrong;
it is not a trailing-profit algorithm and does not replace LF/HF or target
flatten events.

When weighted average is off tick, the broker stop must still use a legal
price. Round in the protective direction: up for a long sell stop and down for
a short buy stop. This avoids deliberately placing nominal breakeven on the
loss side; actual stop-market slippage remains measured in the fill log.

A leveraged position has three independent adverse protections:

- the unchanged weighted-breakeven broker order;
- the opposite post-activation failure object: HF for a long, LF for a short;
- confirmed failure of the internally tracked current sponsor, which produces
  a market-flatten intent.

The sponsor is not represented by a resting stop at either edge of its price
band. Tests and ordinary `HOLD` transitions do not move or flatten the position.
Only the evidence engine's confirmed failure of the exact current sponsor acts.
The broker breakeven order remains in place as protection against fast movement,
evidence delay, data loss, disconnect, or a rejected market flatten.

### Sponsor Handoff

Sponsor handoff is campaign protection, not target interpretation and not a
price trail.

- the initial sponsor comes from the causal support/converted object that
  authorized the filled entry resolution and promotes when that entry fills;
- a later `OWNED` same-side rail is eligible only when it has a different id,
  formed after the current sponsor, owned after the current promotion, and the
  ownership transition's mid is favorably beyond the new band;
- promotion must advance protection completely beyond the current band: the
  new demand minimum must exceed the current demand maximum for a long, while
  the new supply maximum must be below the current supply minimum for a short;
- overlapping same-side rails are one auction for protection purposes and do
  not promote repeatedly;
- promotion is irreversible; after a handoff the runtime never falls back to an
  older, more remote sponsor;
- a promoted sponsor may be tested repeatedly while it remains live;
- confirmed failure of the current sponsor market-flattens the complete
  position;
- if the position has ever been leveraged, that flatten completes the
  directive. Base-only retry behavior remains governed by the explicit retry
  contract and fresh-epoch requirement.

This deliberately conservative spatial/temporal rule is the mechanical causal
proxy for v1. A candidate, repeated paint message, test/hold, overlapping rail,
or ownership that has not displaced price beyond its own band is not enough.
The promoted object id, prior sponsor id, causal epoch, promotion time, band
boundaries, and later outcome are logged so replay can prove every handoff.

No arbitrary maximum stop distance, risk/reward ratio, or backtest-derived stop
cap belongs in this strategy. The plan came from human judgement rather than a
statistical signal system. A large semantic stop is diagnostic information for
the human layer, not permission for the runtime to substitute another stop.

There are no clip-specific trims. A terminal adverse event or breakeven stop
flattens the complete runtime position. Once the position has been leveraged,
that flatten completes the directive; it does not return to base quantity and
does not re-arm.

Opposite failure objects are flatten triggers:

- long plus HF means flatten;
- short plus LF means flatten.

This does not mean the full day thesis is invalid. It means this directive's
clean execution path is no longer clean. If the trader still wants the same side,
issue another directive, likely at a better price.

When the position is flat but the directive remains armed, a fresh opposite
LF/HF invalidates the directive immediately. It must not emit a no-op flatten
and remain eligible for a later automatic entry.

## Targets

`HARD_TP` is the only target behavior selected for development and live use. It
is a resting close-order limit at the normalized target price and completes the
directive when filled. The human may choose a moderately ambitious fixed target
because sponsor protection, weighted breakeven, and LF/HF remain active on the
way there. A target is still finite; sponsor protection is not permission for an
unbounded objective.

`TARGET_DECISION`, `TRAIL_AFTER_TARGET`, and
`TARGET_DECISION_BEFORE_EXTREME` remain schema-valid for compatibility but are
frozen entirely. They are not the next design layer, do not receive inferred
shadow exit behavior, and remain rejected for live execution. No
`DECISION_ACTIVE` state or gate-specific continuation grammar should be added.

Sponsor handoff supplies the useful continuation behavior without coupling it
to a target boundary. It operates before a hard target, can terminate an
over-ambitious directive before the objective is touched, and can ratchet
protection after new favorable business establishes. A hard-target fill or any
earlier terminal protection event ends the campaign even if price later resumes
in the planned direction.

## Grey Zones

Grey zones are tradeable only when new evidence emerges after contest.

Examples:

- supply consumed into demand;
- LF forms after contest and supplies context for a later supported reclaim;
- supply fails, then demand survives;
- demand fails, then supply survives.

The runtime should not treat grey zones as automatic entries. A directive must
specify what post-contest evidence activates the trade.

## Balance Edge Case

A common trap is a large, unbroken IB or contained day.

Example: short above 30250 from prior supply around 30280, invalidation above
IBH 30300. If IBL has never been visited and there is an LF there, blindly using
IBL as target is too aggressive.

Rules:

- if there is a clear rail below, use that rail as `HARD_TP`;
- if the proposed hard target is an unvisited/no-build area with no defensible
  finite objective, choose a closer hard target or do not dispatch the trade;
- do not assume edge-to-edge rotation just because the balance exists.

## Emergency FLAT Control

`FLAT` is an out-of-band control command, not a mutable trade directive and not
an automatically inferred response to loss size.

Example control envelope:

```json
{
  "schema_version": 1,
  "kind": "CONTROL",
  "action": "FLAT",
  "command_id": "flat-20260619-001",
  "issued_at": "2026-06-19T10:12:05-04:00"
}
```

`CANCEL_DIRECTIVE` is the narrower immutable control. It names one directive
id, cancels that directive's working orders, flattens any position owned by that
directive, and records `cancelled`. It does not imply the broader account/symbol
scope or halted latch of `FLAT`.

The runtime gives control messages priority over every trade-directive action.
`FLAT` must:

1. latch the instance into `HALTING` before any asynchronous order work begins;
2. prevent new entries, adds, retries, and order recreation;
3. invalidate every active trade directive for that instance;
4. cancel working orders in scope;
5. flatten the bound account/symbol net position at market;
6. reconcile until position is zero and no in-scope working orders remain;
7. acknowledge the command and enter `HALTED`;
8. remain idempotent when the same or another `FLAT` command is received;
9. resume only after an explicitly new directive is accepted.

The purpose is to let the human react to information the runtime is forbidden to
interpret. An unexpectedly large semantic base stop may show that the strategy
is wrong, the intended direction should flip, or the trader should stand aside.
The runtime reports the event; the human or Dost decides whether to issue
`FLAT`.

## Runtime Safety Requirements

Minimum live safety requirements before real use:

- deterministic replay plus tiny-size demo/throwaway-account validation;
- explicit account and symbol settings;
- max quantity hard cap;
- one directive owns one managed order/position group;
- all orders tagged with directive id;
- stop strategy cancels working runtime orders;
- stale quote/book protection;
- reject directive if side, quantity, activation, stop, or target is ambiguous;
- write an append-only runtime event log;
- never recreate a manually cancelled order unless an explicitly new directive
  id is accepted;
- out-of-band `FLAT` control cancels in-scope orders, flattens, reconciles, and
  latches the strategy halted.

The runtime should fail closed. No directive is better than an unclear directive.

### Safety Model And Operator Responsibility

The runtime cannot make trading harmless without also removing the authority to
trade. Its safety objective is predictable, bounded behavior:

- act only from an explicit, validated, immutable directive;
- remain bound to the configured account, symbol, and quantity ceiling;
- never discover, mutate, reverse, or automatically reissue a strategy;
- stop on ambiguous input, stale data, disconnect, or unreconciled order state;
- make every trigger, fill, retry, add, stop, target, and control outcome
  auditable;
- provide an immediate, idempotent `FLAT` path.

The runtime does not decide that repeated reissues are stubborn, that a plan is
strategically wrong, or that a semantic stop is too large. Arbitrary loss caps
and automatic revenge-trading detectors would change the human contract and can
create their own counter-behavior. The operator, Premarket Standup, Dost, and
`exec-asst` retain responsibility for whether a directive should be issued or
reissued. Bounded execution is the runtime's responsibility; strategic use is
the operator's.

## Spike Result

The first spike proved the basic Quantower path:

- Strategy loads from `Settings/Scripts/Strategies`;
- strategy reads JSON from disk;
- active directive places a far passive limit order;
- terminal directive cancels it almost immediately;
- order tagging and one-order ownership are feasible.

This validates the transport and lifecycle. It does not validate trading logic.

## Open Questions

The core trading contract is now settled. Remaining questions are mechanical
definitions and order-lifecycle decisions, not invitations for the runtime to
improvise strategy.

Closed by the June fixtures:

- leveraged adverse management includes weighted breakeven, opposite
  post-activation LF/HF, and confirmed current-sponsor failure;
- breakeven arms immediately after the first confirmed add fill;
- the broker breakeven order never moves to a sponsor edge;
- only the tracked current sponsor, whether initial or promoted, can produce the
  sponsor-failure exit;
- sponsor promotion is favorable-only, non-overlapping, irreversible, and
  requires a fresh same-side `OWNED` transition with price displaced beyond the
  new band;
- a base-only sponsor failure uses the configured retry/fresh-epoch contract,
  while failure after any add completes the directive;
- LF/HF flatten the complete position and terminate the directive;
- LF/HF while flat invalidates an armed directive and requires human reissue;
- pre-existing LF/HF objects are baselined as context at activation;
- `HARD_TP` is the only target selected for development/live use; decision and
  trailing modes are frozen rather than awaiting threshold research;
- maximum quantity is never a fill objective;
- `max_base_reentries` counts attempts after the initial base;
- ranges are inclusive after tick normalization;
- anchors may sit outside `order_price_range` only when they intersect the
  explicit `context_price_range`;
- `HARD_TP` with no executable runway is rejected;
- a terminal leg never re-arms from later validating evidence;
- raw candidate formation is never executable by itself;
- supported reclaim requires same-side support with correct topology and at
  most twenty ticks to the failed confirmed opposing rail; only candidate
  support may use shortened timing: eight-tick displacement and four-second
  persistence;
- direct conversion retains normal ten-second `CONSUMED` confirmation;
- epoch identity follows object lineage, and a new add/retry requires fresh
  opposing evidence formed after the prior fill/flatten boundary;
- restart never resumes old L2 state: flat directives are cancelled, losing or
  ambiguous positions are flattened, and profitable positions may retain only
  breakeven plus fixed-price exit protection;
- NQ v1 uses vanilla market entries/adds and measures fill quality before
  introducing broker-dependent routing;
- off-tick weighted breakeven rounds protectively: up for longs and down for
  shorts;
- `FLAT` cancels all working orders for the bound account/symbol before closing
  the complete bound net position;
- Quantower's visible Strategy Manager log is the operator status channel for
  high-signal lifecycle events; JSONL remains the detailed audit record.

The remaining decisions should be resolved in this order:

1. base invalidation and retry reconciliation transitions;
2. partial-fill and breakeven replacement behavior observed against the demo
   broker;
3. stale-data, disconnect, and end-of-session contracts.

### Retry Accounting

- Should every base logic stop re-arm immediately, or is a small mechanical
  state-reset delay needed to prevent an asynchronous fill/cancel race?
- How is a fresh trigger held pending until the prior flatten and order
  reconciliation are complete without losing or double-firing that trigger?

### Base Invalidation Mapping

- What exact candidate/live-anchor transition implements the reverse of a
  direct-conversion base?
- What exact transition implements the reverse of a supported reclaim when the
  failed opposing object and supporting anchor resolve at different times?
- Which reverse events are one noisy continuation of the active epoch and which
  retire the base attempt?

### Breakeven Order Mechanics

- When an add partially fills, is protection updated immediately from actual
  filled quantity or only after the add order is terminal?
- How are replace/cancel races reconciled so an old stop cannot reverse the
  position after a newer stop or flatten fills?

### Sponsor Replay Validation

- Does the conservative non-overlap rule miss a materially useful handoff in
  live/replay evidence? Do not loosen it without a concrete counterexample.
- Are sponsor-failure market exits accepted promptly enough under live broker
  conditions for weighted breakeven to remain emergency protection rather than
  the common exit?

### Price Context

- Must an evidence object be wholly contained by `context_price_range`, or is
  price overlap sufficient?
- Is add eligibility tested from trigger price, order-submission quote, object
  range, or all three?
- How much quote movement outside `order_price_range` is tolerated between
  validation and an acknowledged marketable fill?

### Order Routing

- What quote-relative slippage cap and time-in-force should a marketable limit
  use before falling back to market or abandoning the fill?
- Where exactly does a retest limit sit inside a converted wall, and how long
  does it remain eligible?
- How are partial entry/add fills assigned to a resolution epoch without
  accidentally sending replacement quantity twice?

### Operational Boundaries

- Exact directive expiry and end-of-session behavior remain to be specified.
- News avoidance belongs to human dispatch windows, but stale-data and exchange
  disconnect behavior must be mechanical and fail closed.
- Runtime events need a stable schema for candidate, trigger, order, fill,
  semantic stop, retry, add, breakeven, sponsor promotion/failure, control, and
  reconciliation records. Human-visible lifecycle messages must remain sparse
  and deduplicated.

## Next Design Step

The v1 trade/control schemas, candidate timing, epoch identity, restart posture,
sponsor handoff, flat HF/LF invalidation, and visible lifecycle log now exist.
The next design layer is live/demo order-lifecycle validation: partial fills,
replace/cancel races, and base-retry reconciliation. TARGET_DECISION remains
frozen.

Deterministic replay remains valuable, but demo/throwaway accounts can shorten
the gap between replay and live order-lifecycle validation.

The next spike should:

- parse and reject mutated or ambiguous directives;
- validate both JSON Schema and the cross-field semantic rules;
- process `CANCEL_DIRECTIVE` and `FLAT` with priority and idempotent
  reconciliation;
- compute candidate/live-anchor/resolution-epoch state from copied LL-style
  math;
- invalidate an armed flat directive on fresh opposite LF/HF and emit a visible
  Strategy Manager message;
- replay sponsor promotion and failure through the June 16-18 fixtures;
- replay June 11 as the canonical state-machine fixture, with June 16, June 17,
  and June 18 as focused fixtures;
- log every state transition and proposed order;
- validate the same state machine with tiny size on a demo/throwaway account.

The right build order from the current spike is:

1. directive/control schema loader, validator, and immutable-payload digest;
2. `CANCEL_DIRECTIVE` and `FLAT` state machines;
3. runtime event log;
4. order/position ownership and restart reconciliation;
5. copied LL event math with candidate and resolution-epoch objects;
6. base entry, semantic stop, and retry replay;
7. direct-conversion retest routing and supported-reclaim market routing;
8. add gates and asymmetric quantity handling;
9. sponsor handoff, HF/LF-flat invalidation, and operator-visible lifecycle
   logging;
10. weighted breakeven plus fixed `HARD_TP` interaction;
11. tiny-size live validation on a demo/throwaway account.

The runtime should become reliable one directive family at a time.
