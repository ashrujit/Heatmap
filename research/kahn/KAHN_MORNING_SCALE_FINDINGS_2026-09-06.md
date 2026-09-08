# Kahn Morning Scale Findings - 2026-09-06

Codex-authored research. Proposed decisions, not approved trading policy.
Production source, campaigns, controls, and deployed binaries were not changed.

Scope correction: this document studies FIRST adds. The user's subsequent
question about repeated NQ cycles through 11:30 is addressed by the
[full-morning NQ investigation](KAHN_NQ_CAMPAIGN_CYCLES_2026-09-06.md).
That follow-up takes precedence for the core scaling backlog and sets GEX gates aside.

## Finding In Brief

**Keep repair-first as the baseline; repair the definition before making it faster.**
These examples distinguish three problems:

1. Current state can discard an unfinished repair, including on a no-op favorable
   update. ES September 4 reproduces this without any no-add box or GEX veto.
2. A still-live opposing claim observed just before entry can complete a useful
   first-add sequence afterward. Starting the scale observer at the fill misses
   that sequence. This is not permission to replay old failed claims.
3. Some desired early adds genuinely lack a NEW post-entry opposing claim/failure.
   More persistent state cannot manufacture that event. NQ September 3 at 10:58
   is the important unresolved case for a surviving-stack/retest definition.

**Do not confirm zero-gamma crossing as a universal hard gate yet.** It can filter
premature candidates, but category choice, moving boundaries, whole-rail geometry,
and stale-data rearming materially change participation. It cannot fix lost LL state.

[Comparison chart](../out/kahn-scale-20260906/morning_scale_comparison.png) |
[Reproducible study](scale_cycle_study/README.md) |
[Refined backlog](KAHN_SCALE_INVESTIGATION_AND_REFINED_BACKLOG_2026-09-06.md)

## Scope And Method

- Main windows: September 3 10:55-12:00 long; September 4 10:00-11:45 short;
  both ES and NQ. Earlier controls: September 3 10:00-10:50 long and September 4
  09:40-10:00 short. All times are New York time.
- MarketRecorder ESU6/NQU6 snapshots and ticks, loaded through the shared capture
  loader. Actual current `LevelLedgerEvidenceEngine.cs`, `CampaignPolicy.cs`, and
  `CampaignContracts.cs` are linked into an isolated console project.
- Current profile settings: ES cluster 3 ticks, NQ 10; failure 24 ticks / 20 sec;
  sample interval 1 sec. These differ from the older research adapter defaults.
- Four capture windows contain 35,016 snapshots and 1,337,994 ticks. No duplicate
  snapshot timestamps or rejected crossed/empty snapshots in these windows.
  All >5-second snapshot gaps precede the open; none intersect the studied windows.
  Snapshot replay is not an exact reconstruction of Quantower's live worker clock.
- Force a two-unit root at the first ready same-side ownership/hold after each
  window opens. Retain failed roots and retry up to three times. The main windows
  have five roots, including the failed NQ long at 10:56:04; controls have eleven.
  These are NOT inferred historical entries or recommendations to enter there.
- Compare first two-unit add candidates with the same roots. Quote proxy is the
  first snapshot at least 250 ms after the event, no more than 2 sec after that
  target, at adverse BBO plus one tick. Tick paths label 1/5/15-minute MFE, MAE,
  marks, and weighted-average touches; stop at root failure/window end.
- GEX is joined backward by `max(recorded_at_utc, api_as_of_utc)`, requiring both
  ages <=60 sec. Use captured futures-space price, not the cached GEX spot field.
  Each current-core GEX veto is independently replayed and can wait for later adds.
- No full position/order replay: target geometry, passive harvest, broker stops,
  subsequent sponsor promotion, commissions, and actual fills are not modeled.
  Main dates were selected because of the user examples, not held out for testing.

Sources: `C:\Quantower\Settings\Scripts\Indicators\MarketRecorder\captures`,
`GexBotMcp/out/gexbot.sqlite` (read-only), and the linked current source.
The earlier runtime-log audit remains separate; absent/expired directives are not
evidence of a missed executable order. The broad-arena replay isolates mechanics.

## First Candidates

Times are signal times; prices below are subsequent adverse-BBO fill proxies.
No GEX veto in this table. "Retained" permits a still-live pre-fill claim but
requires its failure after the root fill. All repair models still require typed
opposing failure; the price variant relaxes confirmation geometry, NOT failure proof.

| Main example | Current core | Direct favorable rail | Retained claim + joint range proof | Retained claim + price reclaim |
| --- | --- | --- | --- | --- |
| ES Sep 3 long | 11:02:56 / 7723.75 | 10:56:37 / 7709.25 | 11:02:56 / 7723.75 | 10:59:24 / 7715.75 |
| NQ Sep 3 long, root 2 | 11:02:34 / 29404.00 | 10:56:35 / 29290.25 | 11:02:34 / 29404.00 | 11:02:26 / 29394.25 |
| ES Sep 4 short | None by 11:45 | 10:01:53 / 7742.00 | 10:08:18 / 7739.00 | 10:08:18 / 7739.00 |
| NQ Sep 4 short | 10:08:11 / 29650.25 | 10:00:28 / 29677.00 | 10:08:11 / 29650.25 | 10:07:57 / 29650.00 |

No model adds to the failed first NQ long root. Current Kahn can admit an add in
three of these four auction examples with a positioned root and unrestricted
arena. That contradicts "the typed repair rule can almost never fire" as a general
explanation, but does not contradict the user's live experience under real plans.

### ES September 4: Two Distinct State Boundaries

- Demand 7741-7742.75 HELD at 10:00:57. The forced short root fills at 10:01:21.
  This demand is still alive, but the current positioned scale observer never saw
  its HOLD. Supply 7741.75-7743 appears at 10:08:13; that demand formally fails
  at 10:08:18. Retaining both supplies the joint-range candidate at 7739.00.
- Without pre-fill observation, the retained model first qualifies at 10:42:44,
  not 10:08. Merely retaining post-fill favorable proof does not solve cold start.
- Later, current-core state records demand 7732.5-7734.5, then clears it at
  10:15:38 while the candidate does not advance. At 10:19:45 another unchanged
  candidate clears demand 7730.75-7732.25. At 10:30:57 an advancing candidate
  clears the renewed repair too. Demand failures at 10:42:36/44 then have no
  retained repair to complete.

This needs more than a no-op guard: decide when genuinely new favorable proof
advances the SAME repair rather than resetting it. Also decide whether completing
opposition already present at entry is a valid first-add episode. That is a
specific rule question, not an invitation to add on the first supply print.

### September 3: Geometry And A Missing Episode Definition

ES's typed repair failure at 10:59:24 occurs with surviving demand 7708.5-7708.75
and current price 7715.25. The price-reclaim variant qualifies; the range variant
waits until 11:02:56. This is more consequential than event-order retention alone.

NQ's demand 29251-29253.5 is TESTED at 10:56:23 and HELD at 10:56:24 after the
sharp flush. New demand appears at 10:56:35 and 10:58:10. The conservative models
do not find a newly completed post-fill opposing repair until about 11:02.

An exploratory sensitivity initially appeared to recover 10:58:10 by observing
from 10:54. It reused supply 29298.5-29302.5, HELD at 10:54:31 and FAILED at
10:54:57, BEFORE the 10:56 flush and failed first root. That is an old failure
token, not a newly failed repair. The final model explicitly rejects it, and a
regression test protects that boundary.

Therefore 10:58 remains a research candidate for "a tested surviving structure
plus renewed acceptance", not evidence that simple state persistence validates
the earlier add. Define what was challenged, what survived, and why the flush
does or does not create a new episode without a new opposing `RailOwned` event.

Moving observation start +/-1 minute preserves the principal current-core times.
ES Sep 4 retained first-add timing changes from 10:08:18 to 10:42:44 when observation
begins at 10:01, after the live demand assertion. This sensitivity is itself a
reason to specify continuous observation and adoption, not choose the best start.

## What The Controls Say

The direct model creates four main first candidates; three revisit the hypothetical
combined weighted average within five minutes. Two cannot immediately place a
one-tick-onside weighted-BE stop. The retained range model produces four, with
no five-minute average touches and immediate BE-price feasibility in these examples.
These are path diagnostics, NOT modeled scratches, net profits, or independent trials.

In the earlier windows, direct favorable evidence produces three first candidates,
two followed by weighted-average touches and root failure. Cold price-reclaim adds
an ES short at 09:44:55 that also fails. Conversely, the NQ early long is not simply
a negative example: its 10:09 root can support a useful advance. Current core adds
at 10:23:18, but the combined average is revisited within fifteen minutes.

The evidence supports neither "every favorable rail is unsafe" nor "more repairs
always improve results". Earlier price-reclaim candidates deserve a separate
control set. No threshold was tuned to maximize these outcomes.

## Zero-Gamma Reassessment

### Definitions Must Not Be Interchanged

GexBot Classic nets call/put gamma for its display and derives zero gamma from
volume gamma. Its full, nearest, and following-expiry views are distinct. Its
classified-position products are separate. Consequently, neither a Classic
price-side test nor `sum_gex_vol < 0` is a verified dealer-position regime label.
This is an inference from the product definitions, not a new estimate of dealer
positions. [Official GexBot documentation](https://www.gexbot.com/docs)

The adapter currently labels `zero_gamma` "Gamma flip / regime boundary" in
`src/gexbot_mcp/context.py`. Clarify that semantics before using it as a hard
execution predicate. Keep the recorded vendor field and provenance unchanged.

The study compares:

| Gate | Long | Short |
| --- | --- | --- |
| Price side | Current price > current ZG | Current price < current ZG |
| Whole rail | Price side AND proof lower edge > ZG | Price side AND proof upper edge < ZG |
| Renewed rail | Whole rail AND proof after last observed favorable crossing | Same side-adjusted rule |
| Rearmed rail | Renewed rail AND proof after latest stale-to-fresh recovery | Same side-adjusted rule |

Stale/missing GEX blocks all four. Crossing an updated boundary is not necessarily
price crossing a fixed level. A post-gap unknown interval and an observed adverse
cross are deliberately distinct comparisons, not silently equivalent resets.

### Measured Consequences

- **Existing candidates:** full and nearest whole-rail gates retain all three
  current-core main candidates at the same times. They supply no missing repair.
- **ES Sep 3 earlier repair:** 10:59:24 price 7715.25 is above ZG 7710.48, but
  surviving demand 7708.5-7708.75 is below it. Price-side admits the candidate;
  whole-rail waits until 11:02:56 / 7723.75, eight points worse than the earlier
  quote proxy. This selected trend favored the earlier candidate, but does not
  establish that a whole-rail filter loses more than it prevents in other sessions.
- **NQ Sep 4 category:** current-core + full/nearest whole-rail first qualifies
  at 10:08:11 / 29650.25. Following-expiry (`gex_one`) first qualifies at
  10:48:38 / 29522.75. This is a 40-minute difference from category choice alone,
  not evidence to choose whichever category happens to approve the trade.
- **NQ Sep 4 relocation:** cached full ZG moves from 29615.45 (available 10:04:09)
  to 29673.85 (10:05:11). Boundary movement materially changes the side test.
  Preserve the collection/API clocks; do not narrate every transition as acceptance.
- **Negative-sum substitute:** current-core + negative `sum_gex_vol` first qualifies
  at 10:48:38 full, 10:28:13 nearest, and 10:12:49 following expiry on this short.
  It is not interchangeable with the zero-gamma-side condition. This diagnostic
  does not implement or validate the discussion's negative-gamma exemption.
- **Freshness:** 4.1-4.7% of sampled main-window quote observations have stale
  GEX by the 60-second dual-clock rule. Requiring a new LL event after every
  stale recovery delays ES's retained 10:08:18 candidate to 10:09:48; NQ's
  retained-price candidates move from 11:02:26 to 11:02:34 and 10:07:57 to 10:08:11.
  Data freshness is not the same thing as proof being defeated.
- **No shortcut:** direct favorable NQ supply with a full whole-rail gamma gate
  qualifies at 10:05:54 / 29663.00, but revisits the combined weighted average
  within five minutes. Crossing plus a new rail does not eliminate repair risk.

Runway also matters independently. At NQ's 10:08:11 signal the cached full put
wall is 29643.20, only 6.30 points below signal price 29649.50. A large subsequent
MFE cannot be credited to an executable campaign without modeling wall/harvest
handling and later relocation. The study reports runway but does not spend it.

## Decisions To Carry Into The Backlog

| Item | Evidence status | Proposed next specification |
| --- | --- | --- |
| Repair loss on no-op candidate | Confirmed source defect; reproduced in morning replay | Preserve state on rejected candidate updates; define genuine supersession separately. |
| Observation vs order permission | Confirmed representation problem | Continuous campaign-scoped observer; no-add, target, GEX, and WATCH veto orders without silently erasing observed claims. Risk-down still wins. |
| Pre-fill live claims | Supported first-add hypothesis, NOT approved | Allow adoption only while still valid in the same epoch; require fresh completion after activation/fill. Decide whether this is initial resolution or a new repair episode. |
| Proof before failure | Supported design candidate | Joint current proof may complete at failure; TEST/FAIL/reset revoke it. Define claim/zone membership and batch ordering. |
| Range vs price reclaim | Unresolved, controls include failure | Keep separate named alternatives. No implicit `RailFailed` from price alone. |
| NQ Sep 3 10:58 surviving-stack add | Unresolved structural definition | Study test/hold and renewed acceptance without new opposing ownership; prohibit reusing the 10:54 failure token. |
| Zero-gamma hard gate/exemption | Not validated | Choose category, provenance, actual field semantics, crossing/rearm truth table, and stale behavior before deciding whether this is a veto or graded posture. |
| Later adds | Not tested by this first-add study | One accepted add consumes an episode; require independent next-cycle proof. Validate pending-sponsor promotion, BE, retries, reductions, and harvest in full replay. |

Keep WATCH/GO LIVE, discretionary probe BE, typed GEX transport/maxchange caching,
legacy no-add/press migration, and wall harvest in the prior backlog. Their
implementation must follow the agreed scale and activation contract. No new
`CLOSE`/`RESUME`, post-wall discretionary engine, or sponsor-stack exception is approved.

## Validation And Remaining Limits

The standalone .NET Release build passes with zero warnings/errors. Sixteen
research tests pass, including event order, exact claim failure identity, stale
and future GEX rejection, tested-proof invalidation, pre-fill failure rejection,
and continuing current-policy replay after a vetoed first candidate. The chart
was rendered and visually inspected. Research outputs and source hashes are
under `research/out/kahn-scale-20260906`; production was not built or deployed.

This pass gives a reproducible first-add comparison, not a profitable validated
strategy or full backlog approval. Next research should target the NQ surviving-
stack alternative and episode invalidation with full sponsor/BE/harvest behavior,
then September 2 successful scaling and independent trend/churn holdouts. Preserve
the current risk contract while comparing those admission rules.
