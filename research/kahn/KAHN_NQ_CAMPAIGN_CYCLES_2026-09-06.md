# Kahn NQ Full-Morning Scale Investigation - 2026-09-06

Research findings and proposed TODOs, not approved execution policy.
Only research scripts/documents changed. No runtime, campaign, control, or DLL deployment.

Follow-up: [shared ES/NQ episode research](KAHN_SHARED_EPISODE_RESEARCH_2026-09-06.md)
now tests grouping, early two/three-add budgets, and separate inventory maintenance.
The individual-rail experiments below are preserved as the earlier comparison.

Subsequent user clarification: investigate ONE extension/repair/continuation
mechanism whose evidence group can contain one band or many, not separate NQ and
ES scale models. Two or three justified early adds plus management/scale-out are
sufficient; continuous adding is not the objective. The experiments below remain
individual-rail prototypes, not tests of that grouping hypothesis. See the
[updated research contract](KAHN_SCALE_INVESTIGATION_AND_REFINED_BACKLOG_2026-09-06.md#shared-auction-hypothesis-user-clarification).

## Correction To The Earlier Scope

The user's question is about accumulating and holding size through repeated
continuation/repair cycles, not finding one attractive first add. The earlier
first-add comparison did not answer it. This pass follows NQ September 3 long
from 10:55 to 11:30 and September 4 short from 10:00 to 11:30, including subsequent
claims, tests, holds, failures, adds, pending sponsors, and active-risk exits.
All times are New York time. ES, the September 4 PM short, GEX permission, and
geographic no-add/allow-add gates are outside this comparison.

**The repeated evidence is present. Current scale mechanics can lose it or
require a different event shape from the one the market supplies.** This supports
fixing the representation before proposing a gamma-cross prerequisite. It does
not validate adding on every favorable event, nor prove that every repair merits size.

[Full-move chart](../out/kahn-nq-cycles-20260906/nq_campaign_cycles.png) |
[Reproduction](scale_cycle_study/README.md#full-morning-nq-follow-up) |
[Refined backlog](KAHN_SCALE_INVESTIGATION_AND_REFINED_BACKLOG_2026-09-06.md)

## What The Controlled Replay Shows

Identical hypothetical roots, two units per root/add, ten-unit position cap.
These are source-policy simulations, NOT historical Kahn fills or validated P&L.

| Case | Current source adds | Research cycle observer adds |
| --- | --- | --- |
| Sep 3 long, surviving second root | 11:02:34 | 11:02:26, 11:08:45, 11:15:38, 11:23:49 |
| Sep 4 short | 10:08:11, 10:26:24, 10:48:38, 11:18:59 | 10:07:57, 10:15:47, 10:26:05, 10:30:59 |

The short is particularly relevant: **the same four adds build full size by
10:31 instead of 11:19**, then remain held to the study cutoff under the modeled
risk rules. The difference is participation through the move, not simply add count.
The long changes from one add to four. These prototype schedules are hypotheses,
not a claim that the listed prices were executable opportunities that Kahn owed us.

The prototype changes more than event timing: it retains current proof, matches
typed failures by identity, and allows price to reclaim a failed repair while
the sponsoring rail remains behind that repair. The tests below isolate this
last distinction. The prototype does not repair the production sponsor lifecycle;
its ten-unit paths happen not to promote failed pending sponsors in these windows.

## September 3: Repeated Cycles, Not Just The First Add

Replay rail IDs in this window belong to epoch 3. A rail's OWN, TEST, HOLD, and
FAIL are separate transitions, not separate trading opportunities.

| Episode | Observed sequence | What current mechanics do |
| --- | --- | --- |
| 10:56 | First seeded demand root fails at 10:56:22. A new root is seeded at 10:56:25. | All variants retain the failed first attempt; none adds to it. |
| 11:01-11:02 | Demand #73 tests and holds at 11:02:01. Supply #74 fails at 11:02:26. New demand #76 appears at 11:02:34. | Current adds on #76; retained-proof observer can evaluate at the failure. |
| 11:05-11:08 | Demand #82 at 29421.75-29423.50 is owned at 11:05:04, tested at 11:07:41, and held at 11:07:45. Supply #83 appears at 11:07:46 and fails at 11:08:45. | Failure is recorded, but no new same-side OWN/HOLD arrives before the next opposing claim. The surviving HOLD precedes formal opposition by one second. |
| 11:09-11:11 | Supply #87 appears and fails at 11:11:10. No advancing fresh same-side proof is available relative to the observer's already-used #82. | The prototype correctly does not add again merely because another supply claim fails. |
| 11:12-11:15 | Supply #89/#91 occupy 29462.50-29464.50. Demand #92 appears at 29457.50-29459.00 at 11:15:10. Supply #91 fails at 11:15:33; #89 at 11:15:38. | At 11:15:10, favorable candidate tracking erases the repair. Both subsequent failures are then unusable. Prototype waits for both overlapping claims to fail. |
| 11:17-11:23 | New demand #95/#96 appears, then fails at 11:18:30/44. Supply #98/#97 appears at 11:20:20/23. Older demand #92 tests and holds again at 11:22:07. Opposition fails at 11:23:03/14; new demand #100 appears at 11:23:49. | The 11:22:07 HOLD clears repair #97 without advancing the retained candidate. Current misses the later completion. Preserving only no-op tracking recovers this add. |
| 11:24-11:26 | Supply #101 appears at 11:24:48. Demand #100 holds at 11:25:58; new demand #103 appears at 11:26:37. Supply #101 fails at 11:26:40; demand #104 appears at 11:26:51. | The 11:25:58 HOLD again clears repair without advancing the candidate. With diagnostic capacity, the prototype completes at 11:26:40. At ten units it correctly cannot add. |
| 11:28-11:30 | Supply #105 appears at 11:28:39 and fails at 11:29:12. Demand #104 remains owned; no new favorable transition follows before 11:30. | Current waits for another event. Diagnostic prototype uses the still-owned advancing #104 once; the ten-unit path stays capped. Proof age here is 140.5 seconds, a definition still needing validation. |

There are 17 demand OWN, 12 demand HOLD, and 10 supply FAIL transitions in the
window, within 90 total transitions. They cannot be counted as 29 or 10 adds.
Current source clears three repairs on candidate tracking; two of those updates
do not even change the candidate. This is a concrete state defect, not scarce data.

## September 4: Earlier Inventory And A Later Risk Test

Replay rail IDs belong to epoch 5. The root is seeded at 10:00:03. The table
continues after the four-add cap is reached; later cycles are not silently dropped.

| Episode | Same-side proof and failed opposing repair | Consequence |
| --- | --- | --- |
| 10:05-10:08 | Supply #35 tests and holds at 10:07:10; demand #39 fails at 10:07:57. | Prototype first add 10:07:57; current waits for new supply at 10:08:11. |
| 10:09-10:15 | Supply #42 at 29647.25-29651.75 has repeated tests/holds, latest HOLD 10:15:07. Demand #48 at 29644.25-29645.25 fails at 10:15:47. | Prototype second add. Current records failure but cannot use that earlier, higher supply rail as its required lower continuation rail. |
| 10:21-10:26 | Demand #50 repeatedly tests/holds. Supply #52 at 29603.50-29605.50 holds at 10:24:06. Demand #50 fails at 10:26:05. | Prototype third add; current second add waits until 10:26:24. |
| 10:28-10:31 | Demand #55 at 29572.00-29572.25 is alive. Supply #57 at 29591.25-29592.50 appears at 10:30:36. Demand fails at 10:30:59. | Prototype fourth add, reaching ten units. The retained supply is above the failed demand, not a new lower price. |
| 10:36-10:42 | Demand #63 has repeated repairs; supply #65 appears at 10:41:01. Latest tracked demand claim fails at 10:42:19. | Another completion with diagnostic headroom; ten-unit path remains capped. |
| 10:45-10:48 | Demand #66 fails at 10:48:31. Supply #68 appears at 10:48:38. | Current third add; diagnostic prototype sixth add. |
| 10:58-11:02 | Demand #74 is held at 10:59:43. Supply #76 appears at 11:02:30; demand fails at 11:02:37. | Current candidate tracking at 11:02:30 has erased repair. Diagnostic prototype adds at failure. |
| 11:07-11:13 | Newer supply #78/#79/#76/#77 fails during the rally. Supply #68 fails at 11:12:57. | In the diagnostic higher-cap path #68 is active: source risk policy flattens. In the capped path older active supply #52 survives, so it remains held. More adds changed the risk path, not just the quantity. |
| 11:17-11:21 | Demand #82/#81/#80 fails at 11:17:14, 11:18:18, 11:18:49; new supply #85 appears at 11:18:59. Demand #86 later fails at 11:20:37; supply #87 appears at 11:20:41. | Current fourth add is only at 11:18:59. Capped prototype remains full; the higher-cap path is already flat and is not force-reentered. |
| 11:22-11:30 | Supply #89/#87 fails; demand #90 remains owned and #93 repeatedly holds. Supply #85/#91 has repeated tests/holds. | Not an uninterrupted sequence of completed bearish repairs. No mandate to keep adding through the cutoff. |

There are 29 supply OWN, 84 supply HOLD, and 19 demand FAIL transitions within
399 total transitions. The volume of evidence is real; independent add permission
still depends on the cycle, current proof, capacity, and risk lineage.

## What Is A Bug Versus A Policy Decision?

### 1. Repair clearing is demonstrably destructive

`ApplyScaleTracking` clears repair before `TrackScaleCandidate` decides whether
the candidate advances. A no-op can erase the only stored failed/unfinished claim.
Sources: [CampaignContracts.cs](../../KahnRuntime/CampaignContracts.cs#L689),
`ApplyScaleTracking` at 689-712 and `TrackScaleCandidate` at 759-784.

Isolated no-op preservation recovers one later long add, but does not improve
the short schedule. It is necessary cleanup, not a complete scaling solution.
Preserving repair even on a genuinely advancing candidate is a separate decision:
new favorable proof may be part of the existing repair, not a new unrelated setup.

### 2. Chronology and geometry are separate restrictions

Current `PressPolicy` records failure and returns; it then requires a LATER
same-side OWN/HOLD whose range overlaps or progresses beyond the failed repair.
Favorable evidence arriving during the 45-second opposing-claim suppression is
not retained by Press. Sources: [CampaignPolicy.cs](../../KahnRuntime/CampaignPolicy.cs#L309),
309-326, 351-368, 422-433, and 859-916.

Keeping confirmation in memory does not by itself remove the range restriction.
In the short's 10:15 episode, held supply is above failed demand. Price is already
below both. The policy decision is whether that surviving supply sponsors the
continuation, or whether a NEW lower supply rail must form first.

| Research intervention, ten-unit cap | Sep 3 long add times | Sep 4 short add times |
| --- | --- | --- |
| Preserve only no-op tracking | 11:02:34, 11:23:49 | Unchanged current four |
| Preserve all favorable tracking | 11:02:34, 11:17:38, 11:23:49, 11:26:51 | 10:08:11, 10:26:24, 10:48:38, 11:05:41; exits 11:12:57 |
| Retained joint proof, KEEP range-at/beyond-repair rule | 11:02:34, 11:17:38, 11:23:49, 11:26:40 | Same as preserve-all |
| Retained proof + price reclaim, clear overlapping claims | 11:02:26, 11:08:45, 11:15:38, 11:23:49 | 10:07:57, 10:15:47, 10:26:05, 10:30:59 |

Thus the materially earlier short participation is NOT established as a pure
state-memory fix. Its proof geometry must be explicitly agreed and tested.
Every prototype add still requires typed opposing failure; a price cross alone
cannot create it. The overlapping-claim variant delays one long add five seconds
(11:15:33 to 11:15:38); it is an evidence-identity check, not an operator price zone.

### 3. A failed pending sponsor can later become active

This is a separate confirmed source lifecycle defect, reproduced in synthetic
tests and the current-source short replay:

| Queued supply | Failure while pending | Later promotion despite failure |
| --- | --- | --- |
| #53, 29587.25-29589.25, queued 10:26:24 | 10:29:36 | 10:48:38 |
| #68, 29531.25-29533.25, queued 10:48:38 | 11:12:57 | 11:18:59 |

`PromotePendingSponsor` checks progression, not liveness. Pending failure does
not remove the queued authority. Source: [CampaignContracts.cs](../../KahnRuntime/CampaignContracts.cs#L715),
715-757. Production LL treats failure as terminal for that rail within its epoch;
the same old rail will not necessarily produce a second failure after promotion.

The long preserve-all and joint-range variants also promote a failed pending
rail. Their nominal four-add totals must not be interpreted as clean successes.
Keeping an older valid active/root sponsor can be correct; promoting a failed
pending rail as though its proof survived is not the same thing. The agreed
contract must distinguish pending failure from active-risk failure.

### 4. HoldRoot need not conflict with observing the next cycle

Recording newer proof is not an add and need not move the active risk anchor.
A repaired continuation can qualify later while the older valid sponsor governs
the held position. Current eligible adds already outrank HoldRoot (525 vs 500);
a blanket HoldRoot priority reduction is not the fix. Risk-down remains superior.

One-behind promotion must nevertheless validate the pending sponsor at promotion.
The ten-unit prototype short holds with #52 active and #57 pending. Allowing more
adds eventually promotes #68 and exits on its 11:12:57 failure. This is why full
campaign risk behavior must accompany every proposed scale improvement.

## Boundaries And Reproducibility

- Current pure C# LL, policy, and state sources are linked into a research-only
  executable. The runtime worker/order gateway is NOT linked or built/deployed.
- NQU6 captured snapshots use the current NQ settings: ten-tick clusters,
  24-tick/20-second failure, one-second requested sampling. No >5-second capture
  gaps intersect these morning windows. Snapshot replay is not exact live LL timing.
- Root seeds are explicit counterfactuals at the first ready favorable event with
  a subsequent quote: Sep 3 10:56:04 at 29318.75 (fails), 10:56:25 at 29276.00;
  Sep 4 10:00:03 at 29681.50. Initial risk ranges come from those events.
- State replay uses event midpoints for adds. A separate weighted-BE path check
  uses the first BBO at least 250 ms later, within two seconds of that target,
  plus one adverse tick. It rounds the stop in the campaign direction and checks
  executable-side quote touches. No path touches before its modeled evidence exit
  or 11:30. This is not a broker stop simulation, fee-adjusted P&L, or fill guarantee.
- Ten units is the comparison cap, not a sizing recommendation. A 100-unit cap
  is diagnostic headroom only: the joint prototype takes six long adds and seven
  short adds; the latter exits at 11:12:57. It does not force a new root afterward.
- The observer is a latest-claim approximation, not an approved complete proof
  stack. It bundles observation during suppression, repair preservation, exact-ID
  failure, pre-claim proof, and price reclaim. TEST suspends proof; HOLD restores
  it; FAIL removes it. Proof must advance beyond pending/active risk and be observed
  after the prior accepted add. A claim is consumed once. There is no tuned age
  cutoff or formal repair-to-challenged-stack membership yet. Latest proof ages
  at these adds range from zero to 140.5 seconds.
- No passive harvest, target, broker rejection/partial-fill workflow, runtime
  expiry worker, or independent holdout profitability is modeled. A source replay
  staying in a trade with stale sponsor lineage is not evidence of superior risk.

Historical logs are a separate boundary. The NQ Sep 3 window has 34 inactive
records labelled Paused and no order submissions. Sep 4 contains restarts/warmups
and three ENTRY submissions at 11:09:07/18/36, followed by three price-only
`root_stop_touched` exits from the temporary behavior subsequently corrected in
source. There are no ADD submissions in either window. These logs do not show
a continuous live campaign corresponding to the seeded comparison. They also do
not invalidate the user's observation that the market supplied repeated sequences.

Artifacts under `research/out/kahn-nq-cycles-20260906` (git-ignored): full event
streams, `rail_histories.csv`, `cycle_add_lineage.csv`, every before/after policy
state, `event_audit.csv`, `actions.csv`, `summary.json`, sanitized runtime boundary,
source/input/research hashes, and the chart. Thirty-one focused tests pass;
standalone Release build passes with zero warnings/errors. Production source hashes
are unchanged. The first-add study remains preserved as a different, narrower study.

## Proposed Core TODOs

1. Preserve repair state on rejected/no-op candidate updates; specify when an
   advancing candidate enriches versus supersedes the current cycle.
2. Observe proof/claim lifecycles independently of order vetoes, including while
   at capacity. Define the challenged structure, claim membership, and causal
   failure identity so observation is not equated with permission.
3. Specify retained-proof admission: proof may precede the claim/failure, but
   must be current and relevant. Decide price reclaim versus rail-through-repair
   geometry explicitly. Keep typed opposing failure as this study's baseline.
4. Make sponsor liveness explicit: failed pending evidence cannot later be
   promoted unchanged; keep pending failure distinct from active/root failure.
5. Define one-add-per-completed-cycle consumption, progression, nested/overlapping
   claims, expiry, epoch resets, and accepted/rejected/partial-fill boundaries.
6. Validate whole-campaign inventory, risk exits, BE, harvest, and churn controls
   on additional NQ sessions before deciding that the replacement is ready.

GEX crossing and new geographic scale zones are not prerequisites for these
TODOs and should not be used to compensate for these defects. Keep them outside
the core scale proposal; any later case for an overlay must stand independently.
No production implementation starts until the refined contract is agreed.
