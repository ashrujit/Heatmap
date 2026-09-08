# Repair Association Contract

This is the executable contract of the initial isolated C# core, not a claim that
the whole runtime migration is complete. Tests live in `KahnRuntime.Tests`.
All geometry is direction-normalized and tick-keyed. No instrument-specific
event count, clock bucket, far-edge prerequisite, or GEX condition is used.

## Observation And Association

| Case | Core behavior |
| --- | --- |
| Same-side upper-edge TEST | Opens a repair; no deeper excursion is required. |
| Relevant opposing OWN/HOLD | Opens or enriches the challenge without requiring a prior TEST. |
| Opening relevance | Retains the earlier prototype's broad root-relative screen, including its two-tick allowance. This is a screen, not proof association or a price stop. |
| Opposing claim ahead of current quote | Retain it, particularly across WATCH/root fill. A live typed claim need not first be traded through again to remain a blocker. |
| Same-side proof already in the current development | Keep currently live forming/carried members; do not replace one candidate slot or erase repair on a non-advancing update. |
| Additional same-side proof during repair | It must contact recorded attacked/claimed coverage, fresh members, or the price path observed during this repair. The path includes both adverse travel and subsequent favorable travel, not just the old pre-attack extreme. |
| Proof behind the failed opposing band | Valid if otherwise associated, current and executable price is beyond its favorable edge. The proof band need not itself be beyond the repair. |
| Delayed new OWN after typed resolution | It must contact the repair area frozen at resolution. No retest is required; ownership permission begins now, not at formation. |
| Unrelated new OWN after resolution | Close the unused old resolution. Retain the new claim as the next development's seed, but require a new repair/failure before it can authorize an add. |
| New TEST/opposing OWN/HOLD after resolution | Supersede the old episode and require the new challenge to resolve. |
| Nested live opposition | Every associated exact claim must formally fail. A nearby failed ID cannot substitute for a survivor. |
| TEST/HOLD with no opposing failure | Observation only; never a scale permission in this version. |
| Whole attacked group fails | Keep rebuilding possible while its opposition remains live. An old untouched root is not replacement proof. |
| Partial qualifying-member loss | Surviving current qualifying proof can remain valid; no voting or majority rule. |

Proof coverage unions only actual member intervals and preserves holes. Repair
association may include an observed price corridor; that corridor is not owned
coverage and must never be used as a group risk anchor.

The broad opposing-claim screen is intentionally conservative about retaining
blockers. A production feature for independent nested local repairs still needs
explicit lineage/separation evidence; this increment does not discard a live
opponent by distance or timeout. Formation time is preserved when supplied but
is not, by itself, proof of a parent/child causal relationship.

## Ordering And Admission

- A complete source sample is an adapter contract. Equal external timestamps do
  not establish a batch. Reject incomplete, contradictory, skipped, reordered,
  mixed-epoch, or identity-changing samples before partial mutation.
- An OWN never resurrects a failed identity. A new epoch requires a new identity
  and invalidates old completion/group authority without inventing sponsor failure.
- Gap limits are explicit feed-health settings, not grouping time buckets. Quote
  activity cannot conceal missing LL samples. Recovery requires a new epoch.
- WATCH retains observations but cannot emit a scale opportunity. Root fill
  begins a new attempt lineage, retaining only live challenges as configured.
  Flat confirmation disarms the attempt; a new attempt cannot reuse its number.
- Admission uses side-correct executable BBO, managed inventory, quote/evidence
  health, policy/target vetoes, outstanding orders, Base/Add/Max and instance cap.
  Midpoint replay is diagnostic only, never a broker price claim.
- A veto/capacity miss is not saved for later execution. Further observation and
  genuinely new episodes remain possible. No lifetime add-count quota is added.
- Reserve before submission, revalidate immediately before submission, and hold
  the reservation through unknown submission state. Broker acknowledgement is
  not a fill. A confirmed zero-fill terminal report frees capacity without an
  automatic retry loop; a new episode must justify another automatic submission.
- The first actual partial fill consumes the episode and queues one qualifying
  group. Later cumulative fills only reconcile actual quantity/average. Duplicate
  terminal reports are idempotent; inconsistent reports require reconciliation.
- Report timestamps are current processing/observation time. A real fill during
  an evidence gap still counts as exposure but cannot refresh stale sponsor proof.

## Sponsor Boundary

The root anchor is immutable input here; this module does not place a root stop.
The first filled add queues pending proof. A later filled add can promote the
prior pending group only if current support remains valid and both favorable
progression checks pass. Same-area adds can leave active/root risk unchanged.

Active and pending membership is frozen to the actual qualifying intervals.
Untouched neighbors cannot rescue a failed group. A late fill cannot turn an
already failed active group back into a live one by promoting a different group.
Missing epoch/attempt authority is unknown, not typed failure. Merely observing
another completion at capacity cannot promote pending proof.
