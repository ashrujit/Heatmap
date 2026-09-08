# Kahn NQ Episode Stress Test - 2026-09-07

Research only. No production policy, runtime control, campaign, or deployment
changes. The September 6 episode observer and inventory model were frozen
byte-for-byte. New scripts extend capture preparation, run the requested cases,
and diagnose the results; the offline C# probe adds optional lineage output only.

## Assessment

The new cases strengthen the **defended repair-group mechanism**, but do not
validate the complete scaling policy. They expose two material qualifications:

1. Unlimited retention of a resolved repair can authorize unrelated later fresh
   evidence, recreating the very "take a new price" behavior the user rejects.
2. Correctly recognizing repeated repairs does not ensure campaign participation.
   Whole-position BE or treating a child group's failure as campaign failure can
   end the trade while root evidence remains valid.

The 11:00 Sep 2 long is the clearest positive example. The 10:00 long distinguishes
child-tranche failure from root failure. The Sep 1 short demonstrates repeated
structural evidence but an early weighted-BE exit. These are different results,
not three successful full-size campaigns.

[Chart](../out/kahn-episode-stress-20260907/nq_stress_mornings.png) |
[Reproduce](scale_cycle_study/README.md#september-1-2-frozen-stress-test) |
[Backlog](KAHN_SCALE_INVESTIGATION_AND_REFINED_BACKLOG_2026-09-06.md#refined-backlog)

## Frozen Comparison

All times are New York time. Roots are hypothetical first-ready same-side
OWN/HOLD entries, with the prior delayed-BBO rule and up to three attempts.
The table uses formal opposing failure, warm observation, a two-unit root,
two-unit adds, a three-add lifetime budget, tranche-local risk, and weighted BE.
Times in the add column are permission times; fills occur later.

| Requested case | Accepted add permissions | Subsequent result |
| --- | --- | --- |
| Sep 2 long, 10:00-10:30 | 10:09:45, 10:14:46, 10:18:33 | First added tranche fails and is trimmed at 10:09:55. Root and two later tranches reach 10:30, six units rather than eight. |
| Sep 2 long, 11:00-11:30 | 11:03:36, 11:11:52, 11:17:10 | Three defended-group adds; eight units remain until the cutoff. |
| Sep 1 short, 11:50-12:30 | 11:58:05 | Whole position exits at 11:58:43 via the weighted-BE proxy. Later structural completions are not executed adds. |

The 10:00 case's first root enters at 10:01:24 and exits at 10:02:21 without
adding. The reported scale sequence belongs to its second root, 10:02:38 at
29043.75. The initial exit is a nearby same-side failure under the unchanged
root-anchor matching rule: #22 fails near seed #21, not #21's own exact-ID failure.

The 11:00 root enters at 11:02:43 at 29121.25. The short root enters at
11:50:12 at 29304.00. These are not historical Kahn fills or validated entries.

## September 2 At 11:00: Positive Structural Test

| Permission | Qualifying support | Delayed fill proxy |
| --- | --- | --- |
| 11:03:36 | Defended demand #20, 29111.50-29116.50 | 11:03:37 at 29131.75 |
| 11:11:52 | Defended #25 and #28, jointly 29140.00-29142.50 | 11:11:53 at 29158.25 |
| 11:17:10 | Renewed #25/#28 plus defended #29, 29145.25-29147.25 | 11:17:11 at 29172.25 |

The second and third permissions reuse defended areas after another attack;
they do not require an entirely new advancing rail for every tranche. Relevant
opposing claims fail in each episode. A fourth defended completion at 11:25:48
is observed after the add budget is spent, without creating another order.

All three tested management modes retain the built inventory to 11:30 here.
The two-add budget stops at six units after 11:11:53. Starting observation at
10:59, 11:00, or 11:01 produces the same root and three-add schedule. Warm/cold
pre-fill adoption also leaves this schedule unchanged.

This is evidence that repeated same-area defense can support early construction
without GEX gating or adding on every favorable event. It is not proof of
profitability across session types. The second tranche experiences 67 ticks of
adverse excursion relative to its own fill before the cutoff; "held successfully"
does not mean the marginal entry had no meaningful repair.

## September 2 At 10:00: Persistence And Risk Scope

The first add is a counterexample to unlimited `resolved-awaiting-proof` state:

| Time | Observed evidence |
| --- | --- |
| 10:03:02 onward | Opposing supply #23 holds repeatedly around 29056.75-29058.00. |
| 10:04:14 | #23 formally fails. The episode lacks qualifying fresh or newly defended favorable proof. |
| 10:09:32 | A different demand candidate #24 starts forming at 29102.25-29103.00. |
| 10:09:45 | #24 confirms OWN; the old resolved episode emits permission. It has no defended member. |
| 10:09:46 | Two-unit add proxy at 29111.25. |
| 10:09:52 / 10:09:55 | #24 is tested, then fails. Two added units exit at 29091.50. |

The permission is **331 seconds after repair failure**, with signal price
206 ticks beyond the failed claim's favorable edge. The formation-sidecar audit
confirms that #24 was not quietly building during that earlier repair: it forms
more than five minutes after failure. This is not merely delayed OWN confirmation.

The interpretation is a research-contract weakness, not a new production bug:
the observer preserves an unused failure until a new attack or qualifying proof
arrives, but lacks a sufficient structural-lapse rule. Keeping history is useful;
letting that history authorize any later fresh OWN is too broad for the intended
mechanism. A useful future contract must establish the proof's relationship to
the attack, rebuild, or continuous repair resolution.

Do not fit a timeout just below 331 seconds to remove a loser. Another add at
10:14:46 uses a failure 79 seconds earlier and survives; its proof also forms
after failure. The prior Sep 4 10:48:38 fixture needs a short wait after failure
for new confirmation. Formation, confirmation, source side, spatial continuity,
and intervening auction development must be separated before deciding a rule.
Formation of a consumed candidate is not itself same-side ownership permission.

Risk handling produces a second distinction:

- Tranche-local failure removes only the first added pair at 10:09:55. Root #17
  remains held. Later adds at 10:14:46 and 10:18:33 remain until 10:30.
- Latest-group campaign protection instead closes all four units at 10:09:55.
  The root is still held, and the campaign misses the later construction.
- Root-plus-BE without a child-group trim holds the failed add as well. That
  different exposure is not evidence that ignoring child failure is preferable.

With a two-add lifetime budget, the trimmed first add still spends one slot;
only one later add is taken, leaving four units at cutoff. With three slots,
six units remain. "Two or three adds" must distinguish lifetime attempts from
concurrent exposure and reloading after a justified reduction. No slot is
silently replenished in this frozen test.

Start sensitivity matters: a 09:59 start selects an earlier root and exits via
BE at 10:04:26 after one add. A 10:01 start reproduces the 10:00 two-root sequence.
The case is not robust to every nearby seed, even though the later trend is clear.

## September 1 Short: Evidence Persists, Inventory Does Not

Warm observation produces nine formal-failure completions through 12:30:

`11:50:27, 11:58:05, 12:00:54, 12:06:33, 12:10:09, 12:14:20, 12:19:27, 12:19:52, 12:21:09`.

The initial 11:50:27 opportunity is rejected at delayed fill because new
opposition has appeared. The first filled add follows the 11:58:05 completion:
one of six attacked supplies has failed, five are defended, and the two tracked
opposing demands have failed. The five defended IDs cover three price areas,
not five independent add entitlements.

| Position/account item | Value |
| --- | --- |
| Root | Two short units at 29304.00 |
| First add | Two short units at 29290.25, filled proxy 11:58:06 |
| Position average | 29297.125 |
| Rounded short BE trigger | 29297.00 |
| Quote at 11:58:43 | Bid 29297.25 / ask 29297.75 |
| BE exit proxy | All four units at 29298.00 |
| Root and five supporting IDs at exit | All last observed `RailHeld`; none failed |

Thus the exit is account protection, not failure of the root or supporting
group. A new repair starts at 11:58:42 and completes at 12:00:54. That later
completion is observed, but the frozen inventory path is already closed.

This is also a real lifecycle question in current source, not just an arbitrary
replay assumption. `MaintainBreakevenBackstop` emits `Retire` on its managed
touch/close path, and reconciliation of a flat position with active BE also
applies `Retire`. It does not take the ordinary probe-failure retry path.
See [KahnRuntime.cs](../../KahnRuntime/KahnRuntime.cs), especially
`MaintainBreakevenBackstop`, `BreakevenTriggerPrice`, and the
`breakeven_backstop_filled` reconciliation branch.

The study does **not** justify removing or widening BE to capture a known later
move. It requires evaluation of add sizing and price, protection of account versus
root/tranche evidence, and whether retirement or a separately qualified retry is
the intended outcome. No post-BE re-entry is invented here.

The fixed extension to 12:40 adds observations at 12:30:21, 12:31:01, and
12:34:40. It does not revive the retired simulated position or alter any pre-12:30
permission. Starting at 11:49 yields the same first add and BE exit; starting at
11:51 introduces a failed root and a later seed, but still exits via BE at
11:59:11 after the same 11:58:05 add permission.

## Current Source And Historical Activity

The linked current-policy comparison uses the same roots, an eight-unit cap,
and root cutoffs. Its adds use event-midpoint state simulation without integrated
BE or paid harvest, so counts/times are a mechanics comparison, not a P&L contest.

| Case | Current-policy add permissions | No-op repair clears |
| --- | --- | ---: |
| Sep 2 10:00, second root | 10:09:45, 10:14:46, 10:21:58 | 0 |
| Sep 2 11:00 | 11:03:40, 11:27:52 | 2 |
| Sep 1 11:50-12:30 | 12:16:32 | 5 |
| Sep 1 extension through 12:40 | 12:16:32, 12:30:30 | 6 |

Current source also takes the questionable 10:09:45 add. That weakness is not
evidence that only the shared observer can be too permissive. Conversely, the
11:00 example still exposes serial state/timing loss relative to grouped defense.

Historical NQ logs independently show accepted ADD submissions at 10:06:56 and
10:17:59 on Sep 2 for campaign `nq-long-campaign-20260902-140106-555581`. These
are not the table's replay timings. The saved plan had a 29171-29238.75 target,
passive harvest, and a ten-unit cap; the frozen stress test has no target and an
eight-unit cap. The [original session note](../../KahnRuntime/SESSION_NOTES_2026-09-02.md)
is preserved. No historical fills or live campaign equivalence are inferred.

## Backlog Refinement

The shared mechanism remains the leading hypothesis, with these refinements
before implementation agreement:

1. **Repair-proof association and lapse:** preserve the episode's history without
   preserving unlimited add authority. Define a causal relationship for later
   confirmation, separate from elapsed-time tuning. Use 10:04:14 -> 10:09:45 as
   a required counterexample and retain the earlier short-delay/rebuild fixtures.
2. **Formation versus confirmation:** retain the candidate's formation, source
   side, confirmation, TEST/HOLD, and failure provenance. Do not backdate execution
   permission to candidate formation or mistake a consumed candidate's original
   side for its eventual ownership.
3. **Risk scope:** define which tranche or campaign inventory a group's failure
   governs. The 10:09:55 child failure occurs while the root is held.
4. **BE interaction and retirement:** test whole-position protection together
   with earlier adds and renewed repairs. Sep 1 proves that fixing recognition
   alone does not guarantee participation. Changing BE remains a policy decision.
5. **Budgets after reduction:** distinguish a lifetime add count from concurrent
   size and permitted rebuilding after a trim; do not add a reload automatically.
6. Preserve confirmed no-op state-loss and failed-pending-sponsor defects as
   separate work. Continue independent adverse/rotational testing and paid
   harvest/cost validation. No GEX dependency or separate ES/NQ engines added.

## Verification And Limits

- `episode_study.py` still hashes to
  `c1233c36407ad32ff14b357aa8d29b19ca6cdda10fa261df6313867c2ecee02a`.
  No observer, admission, BE, or group-risk rule was retuned on these cases.
- Both capture days have clean requested windows with no evidence reset or
  quote gap above three seconds. Sep 2 has a 9.33-second gap at 10:33, between
  the requested windows; replay resets its evidence epoch there.
- Optional formation-lineage export reproduces both primary event files
  byte-for-byte. The sidecar is diagnostic only, not an additional model input.
- All **63 tests pass**. Fragmentation and prefix checks pass for all ten
  warm/cold case-root runs: four distinct roots, plus the short's repeated root
  under the longer cutoff. These are not ten independent market examples.
- Root choice, favorable-at-fill checks, 250 ms minimum delay, captured BBO,
  one adverse tick, and two-unit sizing remain the prior assumptions. Broker
  scheduling, queue position, real partial/rejected fills, paid target harvest,
  and fees remain unmodeled. Excursion outputs are future outcome labels only.
- The windows were user-selected, and Sep 2's first campaign was already known
  from prior research. These are useful new model fixtures, not random holdouts
  or statistical proof. ES, PM Sep 4, CL, and GC are outside this pass.
- Only the offline EngineProbe was built; it passed with zero warnings/errors.
  Production source hashes and existing unrelated working-tree edits are preserved.

Generated artifacts live under `research/out/kahn-episode-stress-20260907`:
`roots.csv`, `offers.csv`, `inventory_summary.csv`, `actions.csv`, `add_paths.csv`,
`start_sensitivity.csv`, `permission_context.csv`, `risk_exit_context.json`,
`current_source_summary.csv`, quality/validation/manifests, per-root traces,
formation sidecars, and the chart. This output directory is ignored by git.
