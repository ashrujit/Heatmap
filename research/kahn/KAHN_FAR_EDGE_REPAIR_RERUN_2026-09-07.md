# Kahn Far-Edge Repair Rerun - 2026-09-07

Offline research after the user aligned with the implementation package and
clarified repair. No production code, controls, campaigns, LL thresholds, builds,
or deployed assemblies changed. Times are New York time.

## Earlier Definition Versus The Clarification

The earlier shared observer was NOT time-bucketed or band-count voting, but it
was broader than the user's definition. A same-side TEST or relevant opposing
OWN/HOLD could open an episode. Membership accumulated favorable evidence since
the preceding episode and carried defended members; root-relative relevance used
the existing two-tick tolerance. Typed opposing failure plus proof/price clearance
could authorize an add without any same-side claim's far edge being crossed.

The clarified definition requires a long's demand to be crossed below its lower
edge, or a short's supply above its upper edge, or that claim to formally fail.
A near-edge touch, interior test, or exact far-edge touch alone is insufficient.
A claim can remain technically alive after the excursion. The whole stack need
not fail, and this observation does not change the root's failure policy.

## Main Results

These are **signal times for adds accepted by the delayed-fill simulation**, not
fill timestamps or historical orders. Both columns use identical seeded roots,
a two-unit root, two-unit adds, maximum three adds, and the same root-plus-weighted-
BE experiment. Failed preceding roots remain in the artifacts with zero adds.

| Fixture | Frozen broader model | Far-edge, excursion-local, recorded-trade path |
| --- | --- | --- |
| NQ Sep 3 long, 10:55-11:30 | 11:02:26; 11:08:45; 11:15:38 | 11:02:26; 11:23:14; 11:26:40 |
| NQ Sep 4 short, 10:00-11:30 | 10:07:57; 10:15:47; 10:26:05 | 10:07:57; 10:15:47; 10:26:05 |
| ES Sep 3 long, 10:55-11:30 | 10:59:51; 11:23:57 | 11:23:57 |
| ES Sep 4 short, 10:00-11:30 | 10:08:18; 10:42:44; 11:19:09 | 10:42:44; 11:19:09 |
| NQ Sep 2 long, 10:00-10:30 | 10:09:45; 10:14:46; 10:18:33 | 10:29:14 |
| NQ Sep 2 long, 11:00-11:30 | 11:03:36; 11:11:52; 11:17:10 | 11:11:52; 11:17:10; 11:25:48 |
| NQ Sep 1 short, 11:50-12:30 | 11:58:05, BE 11:58:43 | 11:58:05, BE 11:58:43 |

The NQ short still demonstrates three early adds, with delayed proxy fills
complete by approximately 10:26:06. The NQ Sep 3 long has only one early add,
then two later ones. Both ES mornings lose their initial add. This does not
preserve the earlier claim of three early adds in both main NQ moves or establish
two/three early adds in ES. Do not relax the definition just to restore counts.

The straight Sep 2 move becomes one add, as the user considered acceptable. The
10:09 candidate is not rejected because newborn demand lacks a second test;
new proof inside a qualifying repair remains allowed. The old episode did not
meet the newly required same-side breach prerequisite.

## Concrete Evidence

### NQ September 3: 11:08:45 Is Defense, Not Far-Edge Repair

The old episode begins at 11:07:41. Supporting demand #82 covers
29421.75-29423.50. Its lowest recorded trade before the 11:08:45 permission is
29422.25; the lowest sampled midpoint is 29423.00. Neither crosses 29421.75.
Deeper demand #81 at 29407.75-29410.50 is not breached either.

The old 11:15:38 candidate also has no qualifying same-side breach. Its demand
#92 confirms at 11:15:10 in 29457.50-29459.00 after an episode opened on an
opposing claim. The missing prerequisite is repair of existing proof, not a
mandatory second test of new proof.

At 11:23:14, #92 supports a real repair resolution. The trade-path episode starts
at 11:17:54 when #95's 29473.00 lower edge is crossed. #95/#96 fail while deeper
#92 defends; opposing #97/#98 then fail. This retains the intended combination
of challenged, destroyed, and surviving members.

### NQ September 4: Regrouping Retains 10:15:47

Filtering only the old episode rejects 10:15:47 because its boundary excludes
the earlier breached claims. The local observer starts at 10:12:59 when supply
#45 is crossed above 29603.75. #45/#44/#43 fail in the same adverse excursion.
Supply #42 at 29647.25-29651.75 defends, and demand #48 fails at 10:15:47.

Thus #42 need not itself fail or share every other member's fate. The episode
connects the earlier breached structure to later defense, without a time/distance
bucket. Merely filtering the old offers is not equivalent to changing grouping.
The 10:30:59 rebuilt #57/#55 opportunity also remains observable after the
three-add capacity is full; it is not a fourth executed add in this experiment.

### A Quote-Only Replay Misses A Real Excursion

On Sep 2 at 11:23:35, recorded trades cross below #35's 29168.25 lower edge and
#34's 29167.75 lower edge. Quote samples miss the qualifying excursion. The
trade-path observer retains the later 11:25:48 permission with defended #34/#35.
Prices are tested only against claims already known, and permissions are decided
after complete LL samples, never backdated to earlier trades or formation.

### ES Initial Defense Does Not Meet The New Requirement

For Sep 3's 10:59:51 permission, five defended demand IDs cover 7705.50-7708.25.
Their recorded trade minima stay above each member's far edge after it is known
in the episode. For Sep 4's 10:08:18 permission, supply #26 is 7743.50-7744.00;
the recorded trade high after its confirmation is 7743.50, not above 7744.00.
Both initial adds disappear. Later live ES demand #33 is not timed out to
manufacture an earlier short add.

## September 1 Later Engagement

The 11:50 fixture and its fixed 12:40 extension retain the BE exit of root plus
add. There is no automatic reentry. Additional starts use the user's suggested
times, with independently seeded roots and the same risk proxy:

| Window starts | Seeded root | Far-edge trade-path adds | Risk exit before 12:40 |
| --- | --- | --- | --- |
| 11:55 | 11:55:47 | 11:58:05 | BE 11:58:42 |
| 12:00 | 12:00:08 | 12:10:09; 12:14:20 | None |

The noon case retains six hypothetical units through 12:40. This supports the
possibility of later construction without weakening BE, not an exact manual
reissue, supplied envelope, broker-fill, or production WATCH reconstruction.
No future post-BE price selected a root.

## Method And Validation

`episode_study.py` remains frozen at SHA256
`c1233c36407ad32ff14b357aa8d29b19ca6cdda10fa261df6313867c2ecee02a`.
The separate `far_edge_study.py` compares:

1. `frozen`: the unchanged prior observer.
2. `edge_gate`: old grouping/closure, rejecting permissions lacking an in-episode
   far-edge breach or same-side typed failure. A diagnostic, not a new observer.
3. `edge_local_mid`: opens on breach/failure, associates live claims intersecting
   the observed adverse excursion from its pre-attack extreme, on sampled midpoints.
4. `edge_local_trade`: the same local contract using recorded trades between
   complete LL samples, while decisions and clearance remain sample-causal.

After formal repair resolution, a fresh far-edge attack starts a new episode
without requiring the old extreme to break. Otherwise, departure beyond the
pre-attack extreme with no live opposition closes the episode even without proof.
The first draft omitted resolved-then-new-attack handling; it was corrected with
a regression test before finalizing this run. No threshold was fitted to an outcome.

These local association/closure choices are additional hypotheses, not solely
the effect of rejecting shallow tests. The old root-relative eligibility and
delayed-fill simulator's broad new-opposition veto remain. This is not a complete
production nested-repair implementation. A price breach alone never grants an
add; formal opposing failure and current supporting proof/clearance still apply.

- All 85 tests pass, including 22 new tests and the frozen-model guard.
- Fourteen fixture windows produce 23 seeded root paths, each observed warm/cold.
  Extensions and alternate starts are not independent market samples.
- All eleven earlier same-session control roots still produce zero typed adds.
  These are not untouched adverse-session holdouts.
- All 46 prefix checks and all 46 explicit-parent fragmentation checks pass
  across both local variants. Unlabelled splitting changes results in 12/46 runs.
  Preserve actual claim identity/edges when splitting representation. Unlabelled
  fragments invent new far edges and are NOT generally invariant; detector-edge
  sensitivity remains a limitation, not a passed robustness claim.
- Warm mode adopts live events from window start to fill; failed-root retries
  are cold. No pre-fill excursion authority is imported. Production WATCH
  continuity requires separate tests.
- No fixture has an evidence reset or a sampled quote gap above five seconds;
  that does not prove lossless tape or broker capture.
- Seed selection/nearby-failure cutoffs are unchanged research approximations,
  not the operator's actual entry rules. Failed roots remain in the results.
- Inventory retains delayed BBO plus one adverse tick, current proof/opposition
  checks, and root-plus-weighted-BE. Production one-behind group sponsorship is
  not modeled here. No tranche-trim/latest-group risk experiment is bundled.
- No paid harvest, fees, broker partial/rejected-order lifecycle, or deployment
  is modeled. A cutoff liquidation is an outcome mark, not a target execution.

## Backlog Implication

Keep the shared architecture and far-edge repair definition. Add causal price-path
breach records tied to actual claims, separate from TEST and formal failure.
Record destroyed, defended, and rebuilt members without event-count batching.
The stricter definition reduces early participation, especially in the long and
ES fixtures. It preserves the NQ short's early construction, not every earlier
permission. This establishes neither profitability nor a reason to alter BE,
retune LL, or introduce GEX gates.

[Reproduce](scale_cycle_study/README.md#far-edge-repair-rerun).
Artifacts: `research/out/kahn-far-edge-20260907/summary.csv`,
`old_offer_classification.csv`, `old_member_extrema.csv`, `new_offer_lineage.csv`,
per-root episode/offer/trace/inventory files, and hashed manifests.
