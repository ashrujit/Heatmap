# Shared Repair Scaling Implementation

## Approved Direction

September 7: implement the agreed package using the earlier broad repair onset,
not the far-edge experiment. A TEST or relevant opposing OWN/HOLD can initiate
repair. Typed opposing failure plus current associated support and executable
clearance remain mandatory. No GEX gate, detector retuning, automatic BE reentry,
tranche trim, or post-cap sponsor promotion is included.

## Implemented Increment

- `Scaling/RepairEpisodeObserver.cs`: complete-sample observation, persistent
  multi-member repair, typed failure/clearance, defended/renewed/rebuilt proof,
  attempt/epoch boundaries and append-only audit output through `DrainAudit`.
- `Scaling/RepairEpisodeContracts.cs`: source/epoch/rail identity, unknown versus
  supplied formation time, immutable group snapshots and real tick-coverage unions.
- `Scaling/ScaleOrderReservation.cs`: one outstanding reservation, pre-submit
  revalidation, uncertainty retention, actual cumulative partial-fill accounting,
  single episode consumption and no automatic zero-fill resubmit loop.
- `Scaling/GroupSponsorState.cs`: first-fill pending proof, one-behind promotion,
  exact qualifying-member liveness and immutable root input. A late fill cannot
  rescue a failed active sponsor by silently promoting another group.
- `KahnRuntime.Tests`: linked-source executable tests and an offline fixture
  adapter. Neither loads Quantower nor writes runtime campaign/control files.

The [association decision table](Scaling/ASSOCIATION_CONTRACT.md) records the
implemented boundaries, including behind-repair support and delayed proof.
Invalidating an old resolution preserves a new unrelated claim as the next
development's seed; it must still earn a new repair/failure, never inherit the
old one. This avoids reproducing the original candidate-update erasure problem.

## Runtime And Operator Integration

The worker now uses `CampaignSession` and `KahnRuntime.Session.cs`. The legacy
single-slot PressPolicy remains readable/testable for schema-1 replay but is not
an executable fallback in the new strategy. New plans are schema 2 and load WATCH.

- Actual in-process LL samples carry epoch, sequence and supplied formation time.
  All transitions are observed before selecting a decision. Empty samples count.
  Arbitrary external JSONL never gains group authority from equal timestamps;
  its existing root/risk uses, including adverse-claim vetoes, remain separate.
- Root/add orders reserve before submission. Cumulative broker order reports
  update filled quantity/average; the first partial add consumes its episode and
  updates sponsorship once. Position quantity/average must reconcile before more
  risk. Missing identity, contradictory reports and orphan/manual increases are
  recovery conditions, not inferred fills. Trade notifications remain audit data
  rather than being double-counted with cumulative order reports.
- Active/pending group health is checked at capacity. Partial member failure is
  not group failure. Typed root risk remains in force until valid group promotion;
  HoldRoot does not move the root just because another band appeared.
- Operator BE is campaign/digest/instance/attempt scoped and rejects stale,
  offside, ambiguous or unreconciled exposure. Existing tighter protection is
  preserved, including a tighter broker trigger. Adds wait for existing BE
  quantity/price reconciliation; scaled BE remains eligible after partial reduce.
- GO LIVE requires a fresh command and never extends entry expiry. Flat restarts
  require fresh authorization. No automatic BE reentry or position adoption.
- Replacement and CANCEL reject unresolved risk/exposure. FLAT is processed before
  reload/expiry and stays pending until orders and actual exposure are reconciled,
  including late fills. Close submission is not a flatness acknowledgement.
- Probe exports schema-2 root/harvest boxes; the intervening gap is not a press
  zone. Dispatcher derives the arena from those two boxes and has Dispatch/WATCH,
  GO LIVE, BE, CANCEL and FLAT with acknowledgements and separate health/quantity.
- CLI `convert-draft` preserves source files, demands named removal of legacy
  `no_add`/`press` constraints, and reports retained/removed roles and arena bounds.
  Legacy sketch/saved geometry conversion requires operator confirmation. Imports
  remain form-fill only and preserve size, mode and TTL.

The user subsequently authorized installation; see
[the release record](RELEASE_2026-09-07.md). Actual-flat activation, loaded
assembly provenance and a broker-connected shadow/test-account trial remain
pending. Offline tests do not establish Quantower callback timing, stop-order
behavior or profitability.

The original research observer and outputs must stay frozen. New comparisons
use a separate output directory and report differences, not retuned fixtures.

## Initial Core Verification

Final verified artifacts: `research/out/kahn-shared-core-20260907-verified/`.
Its manifest hashes all core sources, replay adapter/build and six input datasets.
Earlier implementation iterations are retained separately; the interrupted
`executable-v3` run failed the mixed-build guard and is not validation evidence.

- 69 new core tests and all 39 existing `RuntimeSelfTests` checks pass.
- All 85 existing research tests pass, including the frozen-observer hash guard.
- Isolated strategy Release build passes with zero warnings/errors. Its output
  is `C:\Heatmap\.tmp\kahn-shared-core-build`, not the deploying project default.
- Fourteen fixture windows produce 23 seeded root paths, observed warm/cold in
  46 runs. All 46 prefix checks and 46 equivalent-fragmentation checks pass.
  These fragments preserve the source lifecycle; this is not a detector-setting
  robustness claim. Extensions and warm/cold paths are not independent sessions.
- All eleven earlier control roots still offer zero typed adds. Failed main and
  stress roots remain included. These are not previously untouched holdouts.
- The deployed Quantower DLL is unchanged at SHA256
  `80a17594b6b82a9bdee71643f8eafb55341e192f4efc18712e856259cc4cef4a`.
  No campaigns, controls, live orders or deployed files were changed.

The final replay uses bid for longs and ask for shorts, while the frozen
prototype uses midpoint. Full main-window permission sequences are retained:

| Fixture | Core permissions through 11:30, New York time |
| --- | --- |
| NQ Sep 3 long, surviving second root | 11:02:26, 11:08:45, 11:15:38, 11:23:14, 11:26:40, 11:29:12 |
| NQ Sep 4 short | 10:07:57, 10:15:47, 10:26:05, 10:30:59, 10:42:38, 10:48:38, 11:02:37, 11:18:49, 11:20:37 |
| ES Sep 3 long, warm | 10:59:51, 11:23:57 |
| ES Sep 4 short, warm | 10:08:18, 10:42:44, 11:19:09 |

These are observation permissions, not executed adds, a full-load assertion, or
historical broker fills. That initial core replay did not combine inventory,
existing risk policies, BE, passive harvest or gateway reconciliation.
Quantity/average and sponsor mechanics were tested synthetically at that stage;
the subsequent integration verification is described below.

## Integration Verification

Final runs are written separately under `research/out` with source/data/build
hash manifests; prior outputs above remain frozen. See the test README for
commands and [the completion report](IMPLEMENTATION_COMPLETION_2026-09-07.md)
for final artifact paths and build hashes.

The integrated diagnostic uses the existing counterfactual root selector and
2/2/10 inventory, BBO plus one tick proxy fills, actual complete sample boundaries,
one-behind sponsors, risk policies and weighted BE. It does not invent targets
or historical fills. No supplied full arena/harvest plan exists for these fixture
roots, so the replay explicitly uses an unbounded diagnostic arena; declared
target/partial-harvest/floor-loss behavior is covered separately by synthetic tests.

| Main fixture | Simulated filled adds before 11:30 |
| --- | --- |
| NQ Sep 3 surviving second root | 11:02:26, 11:08:45, 11:15:38, 11:23:14 |
| NQ Sep 4 short | 10:07:57, 10:15:47, 10:26:05, 10:30:59 |
| ES Sep 3 long | 10:59:51, 11:23:57 |
| ES Sep 4 short | 10:08:18, 10:42:44, 11:19:09 |

The eleven earlier control roots have no adds. Sep 1 retains terminal BE after
one add for the 11:50, 11:55 and noon seeds; these are separate seeded paths, not
an automatic reentry feature. The supplied-window diagnostic has 23 root paths.

An additional Aug 31 check froze 09:35-10:00, 10:00-10:30 and 10:30-11:00 windows
for both sides in ES/NQ before reading results. It produced 27 seeded paths:
12 typed-root exits, 8 BE proxy exits, 7 open cutoffs; no path added more than once.
Nine paths added once, with one of those still open at cutoff. Captures begin
around 09:23; recorded pre-window gaps reset/warm the unchanged LL engine. This
is an additional date check, not pristine out-of-sample profitability evidence.

## Differences To Retain

Do not require exact prototype parity where it depended on a looser association
or timestamp shortcut:

- Sep 2 10:09:45 is omitted. The new demand at 29102.25-29103 does not contact
  the old repair area around the failed 29056.75-29058 claim. An untested new
  claim *inside* a relevant repaired area remains valid without another TEST.
  Later 10:14:46, 10:18:33, 10:21:43 and 10:29:14 permissions remain.
- Sep 1 warm 11:50:27 is omitted. Its fresh-support OWN shares the hypothetical
  fill timestamp but occurs in the complete sample observed before `BeginAttempt`.
  Timestamp equality cannot convert that observation into post-fill fresh proof.
  Live opposition still carries, and later 11:58:05 permission remains. This does
  not change BE policy or reconstruct the user's preferred later directive.
- Sep 1 extended 12:31:01 is omitted: newly confirmed #125 at 29166.25-29168.50
  is outside the observed repair path/claimed area around #24 at 29152.50-29153.50.
  No supplied formation/parent lineage proves that relationship; the core does
  not infer it from confirmation time alone.
- Sep 1 12:21:09 survives with executable ask but not the midpoint diagnostic;
  the ask reaches the supporting area that the midpoint misses. This is a price
  basis difference, not a far-edge requirement or an instrument-specific rule.

The Sep 2 11:00 window and the preferred Sep 1 11:55/noon starts are also in the
manifest and comparison CSV. Their root selection remains counterfactual and
unchanged. The full integration retains these differences rather than tuning a
timeout or a gamma gate to recover a chosen number of adds.

Reproduction commands are in [the offline test README](../KahnRuntime.Tests/README.md).
