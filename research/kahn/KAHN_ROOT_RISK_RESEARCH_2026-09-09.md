# Kahn Root Risk: Ownership, Admission, And Failure

Codex-authored research, 2026-09-09. **Proposed changes only; no runtime,
Dispatcher, profile, deployment, or trading-control changes made.**

## Conclusion

The agreed direction is sound: an opposite-side claim failing can trigger a
probe, but that already-failed claim cannot also be the live defense whose
future failure governs the probe. A lower-demand-failure short needs an
identifiable, live upper supply owner; the long case is symmetric. Missing or
questionable association means skip, not whole-probe-box risk.

There are three distinct gaps to address:

1. **Ownership:** separate the entry trigger from the live claim that owns risk.
2. **Continuity and enforcement:** retain that owner's history across campaign
   reloads and follow its identity through order submission, fills, and failure.
3. **Entry admissibility:** a correctly identified owner can still be very far
   from the fill. Ownership alone does not guarantee a reasonably sized probe.

The third point is material in the September 9 incident. Two possible upper
supply rails already existed around 29533-29537. Neither failed until
11:00:54 ET. Simply substituting either for the dead demand would not establish
the desired earlier exit around 29516, nor prevent a 100-plus-tick excursion.
They are candidates, not a demonstrated causal pair selected by this study.

## Scope And Provenance

- Source inspected: `a2a4d5159ff7a251efbf36e24460ea6555bd963f`.
- Profile: NQ; evidence symbol NQU6, execution symbol MNQU6.
- Input: `%USERPROFILE%\Documents\KahnRuntime\NQ\decisions.jsonl`.
- Reconstructed 31 `AllowProbe` decision snapshots between September 4
  09:30 ET and September 9 11:03 ET; manually reviewed the six cases below.
  This is not 31 validated trades or a complete counterfactual strategy replay.
- Read the complete earlier log prefix to retain pre-campaign live rails.
  Prefix ends at line 71353; SHA-256:
  `73b4ce9bb9236f2dae72661a2ecb1cfa1566cf68b6b55869c17f972b36d63e7e`.
- All clock times below are **America/New_York (ET)**. Log timestamps are UTC.
  Tick calculations use 0.25 index points. Reported losses are price ticks per
  contract, before fees, not dollar P&L or a cross-symbol aggregate.
- Source lines below refer to that frozen input prefix. Later log append does
  not alter them. Old logs without an LL epoch UUID use observed runtime/warmup
  reset boundaries; a campaign reload is not such a boundary.
- [Audit script and reproduction instructions](root_risk_study/README.md).
  Generated evidence is `research/out/kahn-root-risk-20260909/audit.json`.

## Reviewed Entries

### September 9, 10:53:59 Short: Wrong Risk Object, But Upper Supply Existed

Campaign `nq-short-campaign-20260909-145332-b9907b`.

Entry was triggered by **Lean demand #32, 29511.25-29511.50, failing**. It was
not a consumed-demand failure. Runtime used that dead demand's range as the
risk anchor. The 2-contract short filled at 29504. There were no adds or BE
exit in this attempt. Operator FLAT filled at 29544 at 11:01:02, a 160-tick
loss per contract. Sources: lines 71002, 71007, 71035, 71299-71315.

The entry-time inventory contained these live upper supply candidates:

| Rail | Source | Coverage | Owned | Last held before entry |
| --- | --- | --- | --- | --- |
| #27 | Consumed supply | 29533.25-29536.25 | 10:45:25 | 10:50:53 |
| #30 | Lean supply | 29533.75-29536.75 | 10:51:03 | None |
| #9 | Lean supply | 29562.00-29562.75 | 10:15:13 | None |

Sources: lines 70348, 70604, 70822, 70859. #27 and #30 overlap. Neither
overlap nor the presence of a more remote #9 proves which claim caused the
lower demand failure. Do not silently pick the closest/newest or manufacture
a group from their union.

#27 and #30 failed at **11:00:54**, both at logged LL mid 29553.50, already
198 ticks adverse to the fill. Their upper edges alone were 129 and 131 ticks
above entry. With the recorded 24-tick LL move-confirmation setting, the
corresponding move-failure thresholds would be 153 and 155 ticks above entry;
these thresholds are not promised fills or loss caps. Sources: 71276, 71279.

The later supply near the user's 29516 reference was **#34,
29516.25-29517.25**. It owned at 10:57:26, held at 10:57:42, then failed at
10:58:29. It did not exist as an owned rail before the 10:53 entry. Using it
later would require an explicit tighter-root adoption rule, not pretending it
was the original entry owner. Restoring the old whole-box proximity rule
would catch its failure, but would also restore the invalid risk definition.

The LL engine had been running in the same epoch since 10:03:36. Campaign load
at 10:53:32 created a new session/observer without hydrating all live rails.
When #27 and #30 next tested at 10:58:45, the new observer logged their first
observation with `owned_at: null`, despite their earlier ownership in the
engine. This supports a **session-history gap**, not a claim that LL itself
had just started or that no supply evidence existed. The observer also marked
these transitions `outside_observed_development`; that scale-development
filter must not decide whether the separately bound root is alive.

### September 9, 10:45:25 Short: Neighbor Failure Masqueraded As Owner Failure

Campaign `nq-short-campaign-20260909-143102-e163a6`.

This was a direct **Consumed supply #27** entry, risk range
29533.25-29536.25, with 2 contracts filled at 29525.50. The reason string
`same_side_lean_at_trap_probe` is misleading here: it covers consumed rails
too. The LL source field identifies the actual mechanism.

At 10:49:55, **Lean supply #29, 29532.50-29534.25**, failed. Runtime flattened
under `risk_anchor_failed` because it overlapped #27. Actual exit was
29540.50. But #27 had not failed: it subsequently held at 10:50:53 and
triggered another probe. #27's actual failure was not until 11:00:54.

Sources: entry 70604-70636; #29 failure/exit 70791-70810; #27 held/retry
70822-70824; #27 failure 71276.

This is the reverse error: location-based matching can abandon a still-live
owner. Exact ownership is a semantic correction, **not a claim that holding
longer improves this trade's P&L**. It makes the separate risk-width decision
more important. If multiple rails genuinely own the root, membership and the
group failure rule must be explicit before they govern exits.

### September 9, 09:44:32 Long: Correct Owner Exit Can Still Be Wide

Campaign `nq-long-campaign-20260909-134216-ecca49`.

Direct **Consumed demand #5, 29464.00-29468.25** entry. Two fills averaged
29480.875. The same #5 failed at 09:46:02 and runtime flattened at 29457.75:
92.5 ticks adverse per contract, despite identifying and reacting to the
correct owner. Sources: 69511-69550, 69604-69624.

This is a positive identity/failure control and a negative control for the
claim that identity alone makes root risk small. Direct same-side ownership
does not require finding an additional opposing pair; its existing owner
still needs an admissible entry distance.

### September 4, 09:39:17 Short: No Live Supply Owner

Campaign `nq-short-campaign-20260904-133735-b2125e`.

**Lean demand #7, 29623.00-29625.25**, failed. There were no live owned supply
rails in the reconstructed LL generation, which began at 09:31:11. Runtime
shorted 1 at 29617.75 with the entire 29605.75-29686.00 probe as risk. A later
supply #10 failure caused an exit at 29631.50 at 09:43:55.

Sources: entry 52858-52886; failure/exit 53149-53167. Under the proposed
no-owner/no-entry rule this probe would be skipped. The later supply cannot
retroactively qualify it.

### September 4, 09:51:50 Short: Consumed Demand Does Not Imply Live Supply

Campaign `nq-short-campaign-20260904-134421-24c80c`.

**Consumed demand #14, 29626.25-29628.25**, failed. Its original source was
supply, but that provenance does not resurrect a separate, presently live
supply risk owner. There were no live owned supply rails at entry in the
reconstructed generation.

Runtime shorted 2 at average 29619.625 with whole-probe risk
29605.75-29686.00. Operator FLAT exited at 29653.25 at 09:54:10: **134.5 ticks
adverse per contract**. Sources: 53181-53214, 53314-53333.

This probe would also be skipped by the proposed ownership prerequisite. It
also establishes that large root tolerance existed before the September 5-6
scaling work. It would be inaccurate to attribute all such tolerance to that
work or the recent BE/fill fixes.

### September 4, 11:47:30 Short: Do Not Require Supply To Predate Demand Birth

Campaign `nq-short-campaign-20260904-154723-f1a1af`.

**Lean demand #15, 29503.75-29505.00**, failed; 2 contracts short at 29496.
Live upper supply candidates #21, #20, and #17 had all formed after #15's
initial formation but were owned before it failed. #21 and #20 overlapped
and owned in the same sample at 11:47:09. Sources: 54404, 54423, 54443,
54455, 54472, 54485-54486, 54499-54517.

Requiring a risk owner to predate the failed claim's *birth* would discard
this inventory without examining the auction sequence. The necessary
ordering is valid ownership/association by the entry decision, with complete
sample processing. Causal association remains unresolved here; the inventory
is not proof of an eligible entry.

## Required Implementation Backlog

These items implement the agreed ownership direction. Association selection
and risk-width parameters remain proposals, not approved production rules.

### R1. Separate Trigger And Risk Owner

Primary surfaces: `CampaignContracts.cs`, `CampaignPolicy.cs` (`TrapProbePolicy`).

Introduce an immutable root-risk binding containing typed source/epoch/rail
identity, side, coverage, qualification time, and association provenance.
Reuse the existing `Scaling.ClaimKey` identity shape where appropriate.
Keep the triggering evidence separate. Production must not parse log event
strings to recover this identity.

- Same-side OWN/HOLD: the qualified live claim itself can own root risk,
  whether Lean or Consumed.
- Opposite-side FAIL: require an independently live, associated same-side
  defense on the adverse side. The failed opponent is only the trigger.
- Missing, failed, wrong-epoch, incomplete, or ambiguous association: no order,
  with a specific observable reason. No fallback to the probe box, dead
  counter-claim, or nearest unrelated rail.
- A consumed claim's original source side is provenance, not a second live
  owner. Preserve that distinction in qualification and logs.

### R2. Preserve Authoritative Root Evidence Across Campaign Reload

Primary surfaces: `KahnRuntime.cs` (`LoadPlan`, live sample handling),
`LevelLedgerEvidenceEngine.cs` (`LiveRails`/band views), `CampaignSession.cs`.

Provide an epoch-scoped root-evidence view from the live LL engine, including
ownership history and current state. Hydrate a new campaign session without
resetting the live engine. Apply a complete LL sample before resolving or
revalidating an entry so same-sample failures cannot leave a stale owner.

This is state continuity, not permission continuity: GO LIVE must still
require fresh qualifying entry evidence. Historical snapshots must not
manufacture completed repair cycles or fresh scale-up permission. Root
health must not depend on the scale observer's forward-development filter.

### R3. Bind Failure To The Actual Owner, Not Spatial Proximity

Primary surfaces: `CampaignPolicy.cs` (`BuildTrialPolicy`), `CampaignSession.cs`,
and the shared risk state/checkpoint.

Replace nearby-rail inference for bound roots with source/epoch/identity
matching. A neighbor's failure does not become the owner's failure merely
because its coverage overlaps. A root group would need explicit membership
and an agreed health rule, not an implicit range union.

Owner tests/repairs are allowed while LL has not failed it. Do not use
`ClaimSnapshot.Confirmed == false` as a stop: TEST also makes that expression
false. Confirmed owner failure latches an attempt exit. Evidence loss is
unknown health, not proof of either survival or failure; retain explicit
recovery handling rather than silently continuing without an observable owner.

Do not change LL detection thresholds as part of this binding correction.

### R4. Carry The Binding Through The Entire Order Lifecycle

Primary surfaces: `CampaignSession.cs` (`PolicyCandidates`, reservation/report,
`StartRootObservation`), runtime order submission and reconciliation.

Freeze the selected owner before submission and revalidate it immediately
before placing risk. The current pre-fill failure check follows the entry
evidence ID; for a paired entry that would still be the failed demand, not
the supply owner. Follow the reserved owner instead.

Handle owner failure before submission, while an order is working, after a
partial fill, and before a delayed fill report. Cancel remaining entry risk
and retain required exit intent through callback lag/late fills. No repeated
close orders from duplicate failure events. First-fill root observation must
use the actual owner, without making historical owner evidence a new add.

### R5. Keep Attempt Failure, Retry, And Scale Sponsorship Distinct

Primary surfaces: `CampaignSession.cs`, `CampaignState`, scaling integration.

An owner failure ends the current attempt; after confirmed flatness a fresh
qualifying trigger may start a newly validated attempt within the existing
retry/expiry constraints. Do not recycle a dead binding or immediately reopen
from the same consumed failure event. Preserve the existing terminal BE
policy; reissuing a new directive is separate from retry within a campaign.

Keep the root binding stable until an already-authorized sponsorship change.
Preserve one-behind group promotion, weighted-BE protection, and fill identity
reconciliation. Do not promote the newest same-side rail just to make this
incident exit earlier.

### R6. Explicit Entry-To-Owner Risk Admissibility

Primary surfaces: root qualification and pre-submit checks; plan/schema/UI only
if a new operator-controlled admission parameter is approved.

Measure the executable entry's adverse distance to the chosen owner's failure
edge in a consistent price frame, and expose the current LL confirmation
allowance. Distinguish a valid auction owner from an acceptable probe entry.
Reject rather than move a valid structural boundary closer to make the math
look better. Revalidate after quote movement before order submission.

**Unsettled:** the admissibility criterion and limit. Do not silently repurpose
`root_stop_ticks`, invent a 16-tick stop, or choose a numeric limit to fit this
one incident. A pre-entry distance limit is not a broker hard stop and cannot
guarantee maximum fill loss during a rapid move or missing data. A separate
emergency stop would require its own explicit agreement.

### R7. Observable Root Decisions And Regression Coverage

Primary surfaces: decision logs, `RuntimeCheckpoint`, runtime tests. Dispatcher
only needs changes if the resulting operator display or plan contract changes.

Expose trigger versus owner, Lean/Consumed source, epoch, owner qualification
reason, live/tested/failed/unknown health, entry-to-owner distance, and skip
reason. Log which identity caused an exit and whether a neighboring failure
was ignored. Never report generic `risk_anchor_failed` without that provenance.

Replace fixtures that bless a dead counter-claim as the risk owner. Add focused
tests for missing/ambiguous owners, direct OWN/HOLD, long/short symmetry,
Consumed/Lean provenance, overlapping neighbors, pre-campaign hydration,
same-sample failure ordering, TEST versus FAIL, epoch loss, submission/partial
fill/late-fill races, retry freshness, and scale/BE preservation. Add separate
admission tests once R6's rule is agreed. Update `KahnRuntime/AGENTS.md` to
explain why root identity supersedes the existing proximity invariant.

## Decisions Still Needed

1. **Causal association:** encode the actual upper-defense/lower-break auction
   relationship. Geometry alone is insufficient. Start conservatively: use
   explicit supported lineage/sequence evidence; skip unresolved alternatives.
   The audit does not yet establish such a resolver for #27 versus #30. If
   both are to own risk jointly, define that relationship and failure rule
   explicitly, without unrelated time/distance grouping.
2. **Entry distance:** determine what makes a structurally valid probe too
   far from its owner to enter. The September 9 short and morning long show
   this cannot be assumed solved by R1-R5.
3. **Optional later tightening:** adopting later supply #34 as a tighter root
   defense is a separate policy expansion. It needs qualification and
   no-widening rules and must not bypass the agreed scaling sponsor lifecycle.
   It is not necessary to implement missing-owner rejection, and is not
   silently included in the baseline correction.

## Validation And Limits

The research helper has 11 unit tests for reconstruction invariants, including
prefix invariance, epoch reset, campaign continuity, side symmetry, TEST
liveness, and refusing to silently choose overlapping candidates. These test
the **research tool**, not proposed production behavior. No production test
suite, build, or deployment was run because production code is unchanged.

This review establishes concrete ownership and lifecycle gaps; it does not
prove a profitable replacement entry policy or a precise counterfactual exit
fill. Later favorable price movement cannot validate a previously unowned
probe. Further resolver research should preserve the frozen entry prefix and
evaluate holdouts before implementation approval.
