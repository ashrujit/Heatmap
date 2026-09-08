# Kahn Implementation Proposal - 2026-09-07

The user approved this package and subsequently chose the earlier, broader
repair-episode definition after the [far-edge rerun](KAHN_FAR_EDGE_REPAIR_RERUN_2026-09-07.md).
A same-side TEST or relevant opposing OWN/HOLD can open an episode; a far-edge
breach is not a prerequisite. Typed opposing failure, current qualifying support,
and price clearance remain required. GEX boundaries are context, not an added
execution gate. Implementation is authorized; deployment is not.

Implementation progress and remaining integration work are tracked in
[the implementation record](../../KahnRuntime/SCALING_IMPLEMENTATION.md).
Earlier research results remain frozen and are not production fill claims.
All times in the examples are New York time.

## Direction And Scope

There is enough evidence to propose implementing the shared repair-episode model.
The result sought is justified early construction followed by management and
harvest, not a prescribed number of adds or continuous adding until the cutoff.
Research permission times and fill proxies are not historical broker fills or
proof of profitability.

The user's latest clarifications set two important boundaries:

- The Sep 2 10:00 long may legitimately offer few or no adds if it drives without
  useful repairs. Do not manufacture a test or relax permission to capture it.
- The Sep 1 11:50 seeded short is not the intended directive timing. The user
  would engage around 11:55/12:00 or manually reissue after the BE exit. Preserve
  BE retirement; do not add automatic reentry or weaken BE to rescue that fixture.

This proposal consolidates the [original discussion](KAHN_WATCH_GEX_SCALE_DISCUSSION_2026-09-05.md),
[refined backlog](KAHN_SCALE_INVESTIGATION_AND_REFINED_BACKLOG_2026-09-06.md),
[shared-episode study](KAHN_SHARED_EPISODE_RESEARCH_2026-09-06.md), and
[frozen stress test](KAHN_NQ_EPISODE_STRESS_TEST_2026-09-07.md).
It supersedes the original zero-gamma-unlock proposal for the core scale work.

## 1. Replace The Single Scale Slot With A Persistent Episode Observer

Keep a campaign-side proof ledger and an explicit repair episode, rather than
only one advancing favorable candidate and one replaceable opposing rail.

- Each member retains source, evidence epoch, rail identity, formation and
  confirmation times, covered tick intervals, and its OWN/TEST/HOLD/FAIL history.
  Missing formation data is unknown, not silently equal to confirmation time.
- An episode records the structure attacked, relevant opposing claims, observed
  adverse excursion, favorable clearance, qualifying support, and its outcome.
- Related bands are members of one auction development, not independent add
  votes. Preserve covered intervals and holes; do not fill an outer price hull
  with invented ownership. No minimum event count or majority rule.
- One member can fail while other attacked support survives. A completely
  breached initial group can rebuild while its opposing repair remains active.
  New members have new identities; failed members are never resurrected.
- Use the same direction-normalized logic for ES and NQ. Keep current instrument
  tick sizes and LL detector settings; do not tune detector thresholds to produce
  a preferred add count. CL/GC portability is not established by this work.

The observer is independent of policy selection. It continues in WATCH, under
HoldRoot or an add veto, and at maximum size. Observing a completion neither
places an order nor automatically changes the campaign's risk anchor.

## 2. Define Repaired-Continuation Permission

Recommended first implementation: retain typed opposing failure. Change what
Kahn remembers and combines, not the requirement to establish a failed repair.

1. Same-side evidence establishes a relevant area or extension.
2. An observed attack/repair challenges that development. A nearby opposite
   event without a causal relationship does not automatically become its repair.
3. All still-relevant opposing members of that repair formally fail. Failure of
   one overlapping rail cannot stand in for a different, still-live rail.
4. Current executable price clears the repair in the campaign direction, with
   qualifying same-side support that remains valid at the decision time.
5. Ordinary position, sizing, runway, objective, quote, and risk checks pass.

Qualifying support has three explicit forms:

| Form | Required meaning |
| --- | --- |
| Defended structure | Previously minted evidence was attacked and remains defended when the repair clears. |
| Renewed interest | Same-side evidence renews at the attacked area during the repair/resolution. A later distinct attack can reuse that area. |
| Rebuilt structure | Original members failed, but new same-side evidence establishes support within the same repair/resolution and survives its clearance. |

**A new same-side claim in the relevant repair/resolution does not need to be
tested again.** Its role is the response to the existing repair, not the start
of another compulsory repair loop. Conversely, an old failure plus an unrelated
later OWN is not enough.

Proof can be confirmed before, in the same sample as, or after formal failure.
Evaluate their joint current state; do not insist on another future OWN/HOLD
when qualifying proof already exists. The supporting band may remain behind the
cleared repair; it need not itself print beyond the opposing band.

Renewed interest and clearance through a repaired area are parts of this one
mechanism. No extra speed threshold, price-only failure, or TEST-to-HOLD-only
permission is proposed for the first version. A fast move without qualifying
repair evidence can correctly produce no add.

## 3. Make Association, Completion, And Reset Rules Explicit

These are implementation-contract work, not optional tuning after deployment.

- Associate claims by the observed attack and traded/claimed areas, formation
  lineage, and intervening structural development. The whole campaign arena and
  the prototype's broad root-relative relevance test are not sufficient alone.
- Store membership decisions and their reasons as they occur. Never use the
  final-known repair hull or future flow to define an earlier permission.
- Treat nested/overlapping opposition conservatively: a still-live claim in the
  same challenge continues to block completion. Do not discard ES demand #33
  because it delays an add. Independent local repairs require demonstrable
  separation, not a timer or an instrument-specific exemption.
- A resolved repair may await associated confirmation. A new attack supersedes
  the unused resolution; an intervening unrelated extension cannot inherit it.
  Delayed confirmation is allowed, unlimited old-failure authority is not.
- Distinguish building, repair active, resolved/awaiting proof, eligible,
  reserved, consumed, invalidated, and suspended states. A repeated HOLD is not
  another episode. A genuinely new attack can create another episode at the
  same area without requiring an advancing price band.
- A no-op/rejected candidate update cannot erase repair. New favorable evidence
  enriches a still-live episode unless an explicit supersession rule applies.
- Carry currently live observed structures across WATCH -> LIVE -> root fill.
  Do not import completed pre-entry failures as unused add permissions. After
  a failed root or manual reissue, start a new attempt's episode lineage.
- Qualify identities by evidence epoch. On reset, stale feed, or an observation
  gap, suspend scale admission and invalidate unverified completion authority.
  Recover current proof before adding; do not flatten solely because observation
  reset. Existing risk controls and broker protection must still function.

Before implementation of admission, freeze an executable association decision
table covering contact/overlap, behind-repair support, newborn repair-area proof,
delayed confirmation, intervening extension, and nested live opposition. Exact
geometric boundary examples remain to be signed off; this document does not
claim the prototype already supplies a complete production association rule.
Do not fit a five-minute timeout to exclude the Sep 2 10:09 result. Preserve the
short-delay Sep 4 10:48 example only if it satisfies the same causal contract.

## 4. Separate Evidence Batches From Order Admission

- Apply all transitions from one actual LL sample before checking add eligibility.
  Candidate-before-rail update ordering must not cause a temporary false add.
  Timestamp equality alone is not proof of a complete external evidence batch.
- Expose sample/epoch/formation metadata from the evidence adapter where needed.
  Keep LL ownership math unchanged. External evidence lacking required lineage
  cannot silently acquire group-scale authority; retain its separately defined
  legacy/root/risk uses.
- Emit at most one add authorization per episode. Multiple supporting members,
  repeated HOLDs, or both completion forms do not multiply size.
- Revalidate support, new opposition, clearance, executable quote, current
  position, outstanding orders, and remaining size immediately before submission.
- Reserve permission and capacity while an add is outstanding. Submission
  acceptance is not a fill. A first partial fill consumes the episode; do not
  top it up by generating another add from the same evidence. Reconcile actual
  fill quantity and average before updating protection.
- A confirmed rejection or zero-fill cancellation may release the reservation
  only if the episode is still currently valid. No repeated automatic submit
  loop; use bounded retry handling and explicit execution-state reconciliation.
- An opportunity blocked by capacity or another veto is logged, not banked as
  an order to execute later after price has moved or harvest freed capacity.

Keep Base/Add/Max sizing and `root_only` versus `scale_allowed`. Two or three
early additions are an objective, not a mandatory quota or a new hard add-count
limit. A later new episode may use available capacity under existing policy;
capacity freed by a risk reduction is not permission to reuse an old completion.

## 5. Preserve Root Risk And Repair Sponsor Lifecycle

Recommended initial risk model: keep the existing one-behind promotion intent,
adapted to valid group support. Do not substitute the study's latest-group-
governs-the-whole-campaign experiment.

- Entry still begins with the configured probe. Its risk anchor remains the
  actual qualifying evidence, not the width of the drawn root box and not a
  newly invented hard `root_stop_ticks` price stop.
- The first filled add queues its qualifying group as pending; it does not
  immediately replace the older/root sponsor. A later filled add may promote
  that pending group only after liveness and favorable risk progression checks.
- Record exactly which defended/rebuilt intervals support each queued/promoted
  group. An unrelated untouched rail cannot rescue a failed sponsor. Partial
  member failure is not whole-group failure while qualifying support survives.
- Failed pending proof cannot later promote. Invalidate it explicitly; do not
  flatten solely for its failure while the active/root sponsor remains valid.
  A replacement must qualify under its own identity and episode.
- An add at a renewed area need not improve the risk anchor. Permit the add if
  its episode qualifies, while leaving the older valid anchor unchanged. Do not
  force risk promotion merely to make scaling possible.
- Once a group is active sponsor, failure of its qualifying support invokes the
  existing applicable campaign risk-down action. Do not silently replace failed
  support with a new untested group or widen the anchor to keep it alive.
- Continue checking active and pending liveness at capacity. Later observations
  alone do not promote a sponsor. Preserve other existing explicit risk policies;
  do not give HoldRoot or adds a blanket priority change.

Tranche-local automatic trims, a new lifetime reload budget, and automatic
post-cap campaign-anchor advancement remain separate proposals, not implicit
parts of this implementation. Existing risk-down, BE, and harvest still manage
inventory; deferring those experiments does not mean entry-and-forget behavior.

## 6. Retain Scaled BE And Target Harvest; Add Operator BE

Preserve automatic weighted-BE eligibility after scaled inventory is observed,
broker-valid arming, position-average/quantity reconciliation, and retirement
after BE closes the campaign. Root-only positions do not automatically gain BE.
The Sep 1 seeded exit was root plus add; it is not evidence to weaken protection.
Manual reissue creates a new attempt, rather than reviving spent permissions.

Add the separately proposed operator `BE` control for a managed onside probe:

- Bind it to the intended profile, campaign, and current execution attempt.
- Use actual bound quantity/average and side-correct executable quotes. Never
  place an invalid stop, adopt a manual position, or treat an offside request as
  permission to close at an arbitrary market price.
- Reject flat, offside, stale-quote, wrong-attempt, or broker-invalid requests
  clearly. Preserve tighter existing protection; repeated requests are idempotent.
- Share the existing protection lifecycle. After scaling, reconcile quantity
  without silently loosening an operator-protected stop. Surface a protection
  conflict instead of submitting an unprotected add or silently changing policy.
- If the operator BE is filled, use the same terminal retirement convention.

Retain configured passive harvest floors/stretch ranges, close-limit clips, and
floor-loss cleanup. Test earlier scale inventory through real declared targets,
partial harvest, BE resizing, and risk exits. Do not invent targets for fixtures
that never supplied them or call a cutoff mark a profit-taking execution.

## 7. Add WATCH And Campaign-Scoped GO LIVE

- Dispatch/update while flat loads an immutable campaign into WATCH. It observes
  evidence but cannot enter or add. Keep GEX optional, not a readiness dependency.
- GO LIVE authorizes the exact watched campaign ID/digest on the intended runtime
  instance. Require a fresh, deduplicated command and visible acknowledgement;
  stale commands cannot activate a replacement campaign or another profile.
- GO LIVE does not mean buy/sell immediately. It enables normal probe admission
  from current valid evidence and location. Watched evidence may retain live
  structural history, but old completed signals cannot replay as fresh authority.
- Recommended expiry default: retain the plan's explicit entry-window deadline;
  GO LIVE does not silently extend it. An expired watched plan needs explicit
  reissue. Once positioned, current post-expiry management semantics remain.
- Preserve existing ordinary probe retry limits. BE/FLAT retirement is terminal;
  no CLOSE/RESUME or automatic post-BE retry is added.
- Recommended restart default: flat campaigns require fresh GO LIVE. Positioned
  recovery must not adopt orphan inventory or assume phase proves flatness;
  protect/reconcile managed exposure and suspend new risk while recovery is
  uncertain. No new seamless broker-position adoption feature is implied.
- Reject campaign replacement while exposure or an unresolved entry/add exists
  in the initial workflow. Do not turn an active position into WATCH by replacing
  its file. Keep CANCEL flat-only and FLAT available before entry-window gates,
  including when the campaign file is unreadable.

## 8. Simplify Probe/Dispatcher Geometry With Explicit Compatibility

Current SaavikProbe/Dispatcher use root, middle, and harvest boxes. The current
root `no_add` plus middle `press` emission intentionally enforced that older
workflow; removing it is a policy migration, not undoing an accidental UI bug.

Recommended new default:

- Use two boxes: root/probe and harvest/target. Derive the campaign arena from
  them; no mandatory middle permission corridor.
- Stop automatically emitting root `no_add` and middle `press` waypoints. Let the
  repair episode authorize scaling within the arena, subject to normal risk,
  runway, and target/harvest restrictions. Root is an entry eligibility area,
  not an automatic permanent prohibition on a later repaired same-area add.
- Preserve root-only mode, sizing, objective controls, and passive import. Import
  fills the draft; it neither dispatches nor overrides operator sizing/mode.
- Update sketch schema, Dispatcher preview, assembler, CLI validation, campaign
  parser, examples, and operator documentation together. Show semantic roles,
  not just a waypoint count carried over from the old four-waypoint layout.
- Version the new lifecycle/scale contract explicitly. Old runtimes must reject
  new executable plans rather than ignore WATCH or changed scale semantics.
- Keep legacy plans readable for audit/replay. Require explicit conversion before
  new-mode dispatch; report retained/removed constraints and changed arena bounds.
  Never silently ignore a user-authored `no_add`/`press` field. Initial new-mode
  validation should reject unresolved legacy roles rather than guess intent.
- Do not rewrite active campaigns on upgrade. Cut over flat with old files and
  binaries retained for rollback; any legacy execution remains explicitly labeled.

Dispatcher gains Dispatch/WATCH, GO LIVE, BE, CANCEL, and FLAT. Status separates
WATCH, LIVE/flat, IN POS, PAUSED, RETIRED, actual quantity, warmup/recovery, and
stopped/stale/path/control errors. A phase label is never a substitute for
position or runtime-health reporting.

## 9. Add Diagnostics And Deterministic Acceptance Tests

Log episode ID, evidence epoch/sample, member admission reasons, attacked and
support intervals, live opposition, completion form, decision time, execution
reservation/fill, and invalidation/reset reason. Also log why a completed episode
did not add: capacity, target/runway, explicit veto, protection, or execution.
Expose a compact summary in checkpoint/status; keep full membership in audit logs.

Required acceptance coverage:

1. Confirmed no-op repair loss and failed-pending promotion regressions.
2. Proof before/same-sample/after opposing failure, with no intra-sample permission.
3. Partial failure, rebuilt support, same-area renewal, duplicate HOLD, and exact
   identity matching despite overlapping bands or reused rail numbers.
4. Related newborn evidence needs no retest; unrelated later OWN cannot borrow
   old failure. Missing formation provenance must not be silently invented.
5. Fragmentation invariance, preserved interval holes, long/short symmetry, and
   future-prefix causality. Different LL detector settings are a separate test.
6. WATCH/pre-fill continuity, failed-root/reissue reset, feed gaps, restart,
   expired plans, and cross-profile/campaign/attempt control races.
7. Capacity/veto observation, outstanding/partial/rejected adds, exactly-once
   episode consumption, broker reconciliation, and protection failures.
8. Original evidence-based root risk, delayed valid sponsor promotion, HoldRoot,
   operator/scaled BE, reduce/harvest resizing, and terminal retirement.
9. New/legacy schema handling, two/three-box import, root-only mode, and preview
   parity between UI, assembler, CLI, and runtime parser.
10. Full supplied NQ mornings and corresponding ES comparisons, plus untouched
    adverse/rotational sessions. Compare original behavior, isolated defects,
    and the combined model; do not claim the selected trend cases are holdouts.

The prior research reported 63 passing tests. That is not production integration
coverage. Preserve those manifests/results and add implementation tests rather
than rewriting old expected results to make the new policy look identical.
Replay the user's Sep 1 later-start/manual-reissue scenario explicitly as a
separate fixture; do not rewrite the original 11:50 experiment as an actual trade.

## 10. Components, Sequence, And Deferred Work

| Component | Proposed responsibility |
| --- | --- |
| KahnRuntime contracts/policy | Episode state, causal membership, completion, sizing permission, group sponsor liveness. |
| KahnRuntime evidence adapter | Epoch/sample/formation provenance and complete-sample observation; no detector retune. |
| KahnRuntime runtime/gateway/checkpoint | Order reservation/reconciliation, protection integration, WATCH/controls, recovery, diagnostics. |
| SaavikProbe | Two-box passive draft and explicit old-sketch import/version handling. |
| KahnDispatcher | New lifecycle controls/status, simplified geometry, conversion preview. |
| Saavik assembler/kahnctl | Matching schema, validation, scoped control transport, acknowledgement/status, dry runs. |
| Research and self-tests | Shared fixtures, isolated regression tests, end-to-end execution/harvest verification. |
| Component AGENTS/DESIGN/examples | Record agreed invariants, compatibility, and reasons for policy boundaries. |

Recommended order after approval:

1. Freeze the association decision table and risk/lifecycle defaults above.
2. Implement observer/provenance plus confirmed state/sponsor fixes in isolated
   tests; compare against frozen captures without live routing.
3. Wire repaired-continuation admission and execution/protection accounting;
   validate full inventory paths, adverse controls, and actual declared harvest.
4. Integrate versioned WATCH/BE and Probe/Dispatcher/transport changes. Exercise
   dry runs and shadow mode before any broker-enabled trial.
5. Only with separate release authorization: build/deploy, verify loaded binary
   provenance, cut over flat, and run a bounded test-account rollout. Production
   builds deploy directly into Quantower paths, so a build is not a neutral test.

Keep these on the separate backlog, not bundled into core implementation:

- Zero-gamma crossing prerequisites, negative-gamma exceptions, GEX allow/suppress
  maps, and fresh-GEX-required scale warnings: not part of this model.
- GexBot maxchange cache (`current`, `one`, `five`, `ten`, `fifteen`, `thirty`), raw
  payload preservation, and cache provenance: optional adapter work. No runtime
  HTTP/MCP calls and no invented normalized `net_gex` field.
- Wall relocation/path/harvest context: later, separately specified interaction
  with the declared objective. No automatic moving target or continuation mode.
- No-owned-claim defense, price-speed-only clearance, tranche-local risk trims,
  automatic post-cap sponsor advancement, or a new reload budget: separate policy
  experiments requiring agreement, not silent fallbacks.
- PM/post-wall balance automation, CLOSE/RESUME, automatic BE reentry, and CL/GC
  validation: outside this implementation package.

## Approval Boundary

Recommended package: sections 1-9 and the staged integration in section 10.
The remaining material choices are explicit: typed-failure first version; causal
association decision table; one-behind group sponsorship without automatic local
trims/post-cap promotion; existing BE retirement; WATCH with explicit expiry;
two-box/versioned migration. The user aligned with this package after review.
The user subsequently selected the earlier broad repair version, not the
far-edge alternative. Implementation and final offline verification are recorded
in [the completion report](../../KahnRuntime/IMPLEMENTATION_COMPLETION_2026-09-07.md).
Deployment and broker-connected release acceptance remain separate.
