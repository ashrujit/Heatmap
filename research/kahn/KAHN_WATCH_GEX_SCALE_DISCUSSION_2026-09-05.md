# Kahn Watch, GEX, And Scale Discussion 2026-09-05

Codex-authored discussion note. This is not accepted Kahn policy and is not an
implementation record.

Follow-up: the [September 7 consolidated implementation proposal](KAHN_IMPLEMENTATION_PROPOSAL_2026-09-07.md)
is the current proposed change list. Subsequent research/user discussion replaced
the gamma-unlock direction below with shared repair-episode scaling without a
GEX prerequisite. This original note is preserved as discussion history, not
current approval to implement its gamma gates or experimental risk alternatives.

## Purpose

Capture the current design direction before code changes so the WATCH/GEX/scale
discussion does not lose detail.

The motivating problem is not entry discovery. The user still supplies the
trade direction and broad playing field. The problem is campaign mechanics:
Kahn should be able to track evidence before the operator is ready, start all
trades as probe, and become less blind to scale opportunities once GEX and
LevelLedger agree that the auction has crossed into the campaign side of gamma.

## Proposed Runtime Lifecycle

Dispatch should load or update a campaign into `WATCH` by default.

`WATCH` means:

- Campaign side, arena, sizing, risk settings, and objective are loaded.
- Kahn tracks LevelLedger, GEX context, and relevant rails.
- Kahn takes no entry or add orders.
- The operator can keep adjusting or replacing the campaign while deciding
  whether the current attempt is worth engaging.

`GO LIVE` should make the already-loaded campaign executable. The first actual
trade remains a probe. This is meant to cover cases where a move is anticipated
but not yet believed: VWAP nearby, ETH level nearby, swing low/high nearby, or
the operator wants to let a few seconds of false attempt risk pass before
engaging.

`FLAT` remains terminal/emergency: cancel Kahn-owned working orders, close bound
exposure, and retire the campaign.

`CANCEL` retains current semantics: retire only when flat.

No separate `CLOSE` or `RESUME` control is planned at this stage. The WATCH
model is preferred because it makes the dormant/live distinction explicit and
keeps the operator's arena-update workflow simple.

## Entry And Risk

All trades start as probe, as today.

Probe risk remains based on LevelLedger bands and Kahn risk settings. The
2026-09-04 root/probe risk-management bug must be audited and fixed before the
new lifecycle work is trusted live.

Add a discretionary `BE` control:

- It is operator initiated.
- It protects an existing probe when price has moved favorably but has not yet
  built through structure.
- It is valid only when Kahn is positioned and the market is onside enough for a
  broker-valid break-even stop.
- If flat, offside, or broker-invalid, the command should fail with a clear
  operator-facing error.

Existing scaled-position break-even and sponsor-promotion behavior should stay
unchanged.

## Scale Direction

The existing no-add/press-zone geometry emitted by KahnDispatcher is likely the
wrong default for the new model.

New scale posture should be driven by GEX context plus LevelLedger evidence:

- For longs, scaling can unlock only when price and current LL claims are on the
  favorable side of zero gamma.
- For shorts, scaling can unlock only when price and current LL claims are on
  the favorable side of zero gamma.
- A price poke through zero gamma is insufficient.
- Fresh same-side `RailOwned` or strong `RailHeld` beyond zero gamma is required.
- If a rail straddles zero gamma, treat it as boundary churn and pause scale.
- If zero gamma later moves back against the position, do not flatten solely for
  that reason. Continue to manage the open position, pause further adds, and
  wait for a new favorable cross plus fresh LL claim before scaling again.
- Opposite repair pauses scale.
- Failed opposite repair plus renewed same-side rail reopens scale.
- If GEX is stale or unavailable, probe behavior can remain directive-driven,
  but GEX-unlocked scale must not silently turn on.

Negative-gamma territory should mean scale is eligible from the start of live
execution, not that Kahn skips the probe stage, skips sponsor promotion, or adds
on every fresh price.

## GEX Storage And Fields

The local GexBot adapter currently preserves raw chain fields and caches chain
snapshots. It exposes `zero_gamma`, volume/OI walls, `sum_gex_vol`, and
`sum_gex_oi` in normalized context.

The API also has a `maxchange` view with `current`, `one`, `five`, `ten`,
`fifteen`, and `thirty` lookbacks. That view should be cached explicitly before
Kahn depends on it for replay or runtime state.

No normalized `net_gex` field has been confirmed in the sampled ES/NQ chain
payloads. If GexBot later returns such a field, raw payload preservation should
make it inspectable before we promote it to normalized context.

GEX remains context. It can unlock or pause a scale posture only when LL or
other campaign evidence independently supplies the ownership/acceptance proof.

## Wall And Harvest Handling

`call_wall` and `put_wall` remain harvest/path-stress context.

If a wall lies between current price and the target:

- Manage it like the existing harvest/scenario-zone behavior.
- If exhaustion or claims break near the wall, harvest or exit.
- If evidence remains strong, hold is allowed.
- Wall relocation should be logged as context, not turned into an automatic
  continuation mode.

Post-wall TPO repair, PM liquidity thinning, and balance formation are manual
management cases for now. Do not encode those edge cases in the first change.

The 2026-09-04 post put-wall migration review suggested:

- NQ had the larger continuation but more repair churn after the wall moved
  lower.
- ES was structurally cleaner for immediate scale after its wall move, but then
  stalled before reaching the shifted wall.

This supports a simple rule: wall shift can improve context, but LL still has
to show same-side ownership, repair failure, or renewed same-side claims.

## Press Mechanics Remain Unresolved

The exact press geometry needs more thought.

History so far:

- EAR-style press acted faster and could work, but sponsor-promotion logic often
  got the trade out.
- Current Kahn-style press waits for repair first. That prevents premature
  belief in every new claim, but recent sessions show Kahn often keeps building
  evidence and then does nothing useful before price has migrated elsewhere.
- The correct answer is probably between those two models.

Open geometry question:

- What is the earliest scale add that is still root-preserving and not just
  chasing a new price?
- When does same-side continuation beyond zero gamma deserve an immediate add?
- When must Kahn first wait for a repair claim and a failed repair?
- How should repair churn near moved walls or emerging TPO balance affect scale
  timing without hardcoding PM edge cases?

Working hypothesis:

- `SponsorStackAdd` covers earlier root-preserving scale when same-side stack,
  opposing weakness, and runway are already clear.
- `TailReclaimAdd` covers the later C/D-ZZ-C/D shape: favorable extension,
  repair claim, repair invalidation, and renewed same-side rail.
- Zero-gamma-side favorable context may lower the burden for the first add, but
  it should not eliminate LL proof or sponsor/risk discipline.

This remains research/design work, not an implementation-ready rule book.

## Suspected Scale-State Mismatch

The scale/add playbook is still considered directionally sound:

- Do not buy/sell every new price.
- Let same-side LL evidence build into a stack of proof.
- Wait for a test or repair of that stack.
- Add only when the repair fails, the stack survives, or the campaign side
  renews with enough structure to preserve root risk.

The concern is that the current runtime may be treating that multi-rail proof
stack as a narrow one-step token:

- Same-side `RailOwned`/`RailHeld` can become a tracked scale candidate.
- An opposite `RailOwned`/`RailHeld` becomes `non_causal_adverse_claim`, which
  is functionally a repair claim and suppresses leverage.
- Kahn then appears to need a fairly exact repair-failure event near that
  repair anchor, followed by fresh same-side continuation, before it can act.

That can create a fast-auction dead zone. The repair may have failed in the
operator's sense because price reclaimed the repair, adverse reward was poor,
the prior stack held, or the next favorable drive began. But if LL does not
emit the exact event shape Kahn expects, or if the next rail is not fresh/in
zone/near enough, Kahn can keep evidence and still not add.

Going back to EAR-style "any new favorable evidence is press evidence" is too
loose. The likely middle ground is a persistent `PressSetup` or `ProofStack`
state that survives across several LL events:

- `StackBuilding`: favorable rails are accumulating after the probe is onside.
- `RepairObserved`: an opposite claim tests the stack and stores the repair
  range plus the favorable stack it challenged.
- `RepairInvalidated`: the opposite claim fails either formally by LL
  `RailFailed` or implicitly by price reclaim, poor adverse reward, survival of
  prior favorable rails, or renewed favorable ownership after repair.
- `PressEligible`: an add can be taken under normal root-risk and sponsor rules.

GEX/zero-gamma context should adjust scale posture and burden of proof, but it
should not replace this LL proof-stack decision.

## Legacy No-Add And Press Parsing Question

The value of keeping legacy `no_add` and `press` parsing is not settled.

Potential reason to keep it briefly:

- Old replay examples, saved campaign JSON, and operator-drafted artifacts may
  still contain those roles.
- Keeping the parser tolerant can help read old artifacts while the new model is
  introduced.

Potential reason to remove or quarantine it:

- If the live runtime continues honoring old `no_add`/`press` semantics, those
  roles can clash with the WATCH/GEX scale posture.
- The current no-add corridor is exactly the behavior being questioned.
- Carrying legacy roles forward may confuse future debugging if a new campaign
  unexpectedly suppresses scale because an old geometry field survived.

Preferred compromise:

- Stop emitting `no_add` and `press` from new KahnDispatcher campaigns.
- Decide separately whether runtime parsing should reject them, ignore them for
  new schema versions, or preserve them only for named legacy replay fixtures.
- Do not let legacy roles silently affect new WATCH/GEX campaigns.

## Dispatcher Shape

Planned visible controls:

- `Dispatch`: create/update campaign in WATCH.
- `GO LIVE`: enable execution for the watched campaign.
- `BE`: discretionary probe break-even protection.
- `FLAT`: terminal flatten and retire.
- `CANCEL`: flat-only retire.

Avoid adding `CLOSE` for now.

Status should distinguish at least:

- `WATCH`
- `LIVE/flat`
- `IN POS`
- `PAUSED`
- `RETIRED`
- stale/stopped/path/control-error states

Validation should warn if a scale-capable campaign lacks fresh GEX context.

## Verification Needed Before Release

- Root/probe risk bug regression.
- WATCH loads/tracks without orders.
- WATCH can be updated/replaced while flat.
- GO LIVE enables probe from fresh current evidence.
- WATCH evidence does not become stale authority.
- BE succeeds only when positioned and onside enough for a valid stop.
- BE fails clearly when flat, offside, or broker-invalid.
- GexBot cache stores maxchange lookbacks with provenance.
- New Dispatcher campaigns do not emit `no_add` or `press` roles.
- Legacy `no_add`/`press` behavior is explicitly decided and tested.
- 2026-09-03 and 2026-09-04 replay fixtures cover zero-gamma/wall migration and
  the difference between probe permission, scale posture, and harvest context.
