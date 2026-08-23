# Direct-Conversion Sponsor Lineage - 2026-07-25

Research status: hypothesis generation. No EAR or LevelLedger runtime rules
have been changed.

## Question

Evaluate direct-consumption events by sponsor survival rather than fixed
favorable/adverse price excursion:

1. Did the consumed root establish a new favorable sponsor before the root
   failed?
2. If that child later failed, was the failure contained/repaired, or did it
   propagate backward into the consumed root?

The practical split is entry permission versus campaign keep/exit authority.

## Reusable Probes

- `research/direct_conversion_execution/scripts/direct_conversion_sponsor_lineage.py`
  - Event-ordered lineage labels for all consumed rails and the traded
    DirectConversion subset.
- `research/direct_conversion_execution/scripts/direct_conversion_entry_provision.py`
  - Raw MarketRecorder exact-band book replay ending at order decision.
- `research/direct_conversion_execution/scripts/analyze_direct_conversion_lineage_features.py`
  - Joins decision-time exact-band evidence to lineage outcomes.
- `research/direct_conversion_execution/scripts/direct_conversion_decision_snapshot.py`
  - Measures nearest-30-level stacking/pulling from conversion break through
    order decision and joins recent LL ownership context.
- `research/direct_conversion_execution/scripts/direct_conversion_child_contact.py`
  - Measures child formation/failure contact and root-child spatial
    independence against failure propagation.
- `research/direct_conversion_execution/scripts/direct_conversion_synthetic_hold_snapshot.py`
  - Tests held synthetic consumed rails under compatible active directives,
    including rails that did not produce an EAR order.

Primary outputs:

- `research/direct_conversion_execution/out/direct_conversion_sponsor_lineage/`
- `research/direct_conversion_execution/out/direct_conversion_lineage_features_20260717_20260724/`
- `research/direct_conversion_execution/out/direct_conversion_decision_snapshot_20260717_20260724/`
- `research/direct_conversion_execution/out/direct_conversion_child_contact_20260716_20260724/`
- `research/direct_conversion_execution/out/direct_conversion_active_hold_snapshot_20260716_20260724/`

## Structural Population

Runtime window: 2026-06-22 through 2026-07-24 ET.

- All consumed roots: 2,591.
  - Favorable successor formed before root failure: 1,310 (50.6%).
  - Root failed first: 1,252 (48.3%).
- Accepted DirectConversion order roots: 391.
  - Favorable successor formed after entry and before root failure: 157
    (40.2%).
  - Root failed after entry before favorable progression: 232 (59.3%).
- Literal "older/worse protection failed before the conversion root" cases:
  zero. Failure propagates through the newer root first by construction. The
  useful interpretation is backward propagation through lineage, not an older
  sponsor failing before the root.

The entry clock must start at order decision. Root 34 had already created and
lost a favorable successor before its 10:21 entry; that stale successor cannot
be credited to the tradeable retest.

## Entry-Stage Finding

Six-session decision-aligned sample:

- 115 accepted/filled DirectConversion entries.
- 46 advanced to a favorable sponsor before root failure.
- 68 roots failed before favorable progression.
- One unresolved.

Exact-band provision and turnover alone are weak. The two-day read that low
turnover favored success reversed in the full sample and is rejected.

The nearest-level book evolution is more useful:

- Owner depth stacked in the nearest five levels:
  - advanced 30/59 (50.8%).
- Owner depth was flat or pulled:
  - advanced 16/55 (29.1%).
- The ordering repeats for long/short and base/add, but not on every date.
  Near-touch stacking is a score/gate candidate, not a standalone trade rule.

Recent ownership context supplies the missing HVN/churn distinction:

- Both demand and supply had failed within 50 points during the prior 10
  minutes:
  - advanced 19/67 (28.4%).
- No such two-sided failure field:
  - advanced 27/47 (57.4%).

An escape is defined structurally: if two-sided failures exist, the conversion
is outside the favorable edge of their price field. Combining that with
near-touch stacking:

| Context | Near-touch book | Advanced | Failed | Advance rate |
|---|---|---:|---:|---:|
| clean or escaped field | stacked | 21 | 11 | 65.6% |
| clean or escaped field | flat/pulled | 12 | 17 | 41.4% |
| inside two-sided churn | stacked | 9 | 18 | 33.3% |
| inside two-sided churn | flat/pulled | 4 | 22 | 15.4% |

This is the current best formulation of "HVN without an HVN heuristic":

- The direct conversion is suspect while it remains inside a recent local field
  where both ownership sides have failed.
- Fresh same-side stacking near touch improves it but does not erase the churn
  penalty.
- Once the conversion establishes beyond the favorable edge of that failed
  field, the same mechanism can become the escape event.

### Selection-Bias Audit

The 115-entry result is conditional on EAR reaching an actual order decision.
Two broader synthetic populations were tested:

- All held consumed rails during recorder coverage:
  - 458 rows; 197 advanced after hold and 261 failed first.
  - The entry interaction did not generalize.
- Held consumed rails while the latest directive was active and
  side-compatible, whether or not EAR entered:
  - 190 rows; 79 advanced and 111 failed first.
  - Clean/escaped plus stacking: 19/34 advanced (55.9%).
  - Inside two-sided churn plus stacking: 14/47 advanced (29.8%).
  - The effect was side-asymmetric at the `RailHeld` timestamp.

This narrows the claim:

- Clean/escape context remains useful under compatible directives.
- Nearest-five-level stacking is strongest at the actual order decision, not
  as a universal property of every held consumed rail.
- The snapshot metric is rank-based. Best-price movement can change the nearest
  five levels and masquerade as pulling/stacking. A fixed-price raw-book replay
  is required before this becomes an implementation heuristic.

## Named Fixtures

- 2026-07-24 root 34, 10:21 short:
  - Root failed before post-entry favorable progression.
  - Inside two-sided churn.
  - Nearest-five owner depth pulled by 9.
  - Failed-field favorable edge gap: -27.25 points.
- 2026-07-24 root 84, 11:50 long:
  - Advanced after entry.
  - Clean/escaped context.
  - Nearest-five owner depth stacked by 4.
  - Child 86 later failed, but same-side sponsorship re-established before root
    84 failed.
- 2026-07-24 root 89, 11:55 long:
  - Advanced despite near-touch depth pulling by 1.
  - Recent two-sided churn existed, but root 89 was 11.25 points beyond its
    favorable failed-field edge. This is the escape counterexample.
- 2026-07-24 root 102, 12:10 add:
  - Entry stage succeeded: clean/escaped context and nearest-five depth stacked
    by 8.
  - Child 103 failure then propagated into root 102 before sponsorship
    re-established. Entry quality and keep/exit quality are separate.
- 2026-07-23 root 111, 12:19 short:
  - Near-touch supply stacked, but the root remained inside two-sided churn and
    failed before progression.
- 2026-07-23 root 208, 14:35 short:
  - Clean/escaped context plus near-touch stacking.
  - Advanced before root failure.

## Child Failure And Campaign Authority

Across all 391 traded roots:

- 157 advanced after entry.
- 134 favorable children later failed: 132 while the root was strictly live and
  two simultaneously with root failure.
- Child failure outcomes:
  - Contained by an already-live favorable sponsor: 28.
  - Same-side sponsorship re-established before root failure: 38.
  - Root failed at/before same-side re-establishment: 68.
- Median child-failure-to-re-establishment: 132.8 seconds.
- Median child-failure-to-root-failure in propagated cases: 41.8 seconds.

Blind parent fallback is therefore not enough: it saves/contains roughly half
and delays a real root failure in roughly half.

MarketRecorder child-contact sample, 2026-07-16 through 2026-07-24:

- 45 failed favorable children.
- 23 contained/re-established.
- 22 propagated to root failure.

The strongest non-outcome dimension is spatial independence:

- Gap from root edge to child edge, normalized by child width:
  - re-established median: 8.33 child widths.
  - propagated median: 2.20 child widths.
  - descriptive AUC: 0.809.
- Excluding already-contained cases:
  - child within 2 child widths: 0/11 re-established, 11/11 propagated.
  - child more than 10 child widths away: 5/6 re-established.

The two-child-width boundary was discovered in this sample. It repeats across
five dates and both sides, but it is not out-of-sample validation.

Interpretation:

- A nearby/wide child is likely another ownership claim inside the same local
  auction. Its failure is evidence against the root campaign.
- A spatially independent child can fail locally without disproving the lower
  causal root. It should not automatically replace the root as sole flatten
  authority.
- An already-live favorable sponsor at child failure is direct containment
  evidence and should be evaluated before flattening.

## Fixed-Price Auction-Road Pass (Superseded Measurement)

Important correction:

- The original eight-tick "test front" was placed on the already-traversed
  favorable side of the entry price. For a bullish return it measured bids
  above the current test rather than bids underneath it; the supply case was
  mirrored incorrectly in the same way.
- The frozen July 17-22 holdout did not validate the original rule: road
  retrace was 42.9% for advances versus 43.8% for failures and test-front
  provision was +4 versus +2.
- The findings below are retained as the discovery trail, not current evidence.

Probe:

- `research/direct_conversion_execution/scripts/direct_conversion_auction_road.py`
- output:
  `research/direct_conversion_execution/out/direct_conversion_auction_road_20260723_20260724/`
- population: 32 accepted DirectConversion roots on July 23-24; 15 advanced
  before root failure and 17 failed first
- replay health: 39.6 million raw book rows, no gaps, one valid reset per day,
  and no unopened/invalid measurement phases

The direct conversion itself is only local consumption. The next causal
question is whether normal two-sided auction can establish beyond it:

1. favorable aggression trades through available opposing liquidity;
2. same-side passive liquidity forms behind the move;
3. the return does not erase the favorable road; and
4. same-side liquidity re-forms at the moving test front.

The relevant return must be aligned to the actual EAR decision. Root 34's first
material return at 10:19 held and readvanced, but the later return containing
the 10:21 entry erased 97.0% of the road and the root failed. Classifying only
the first retest would therefore answer the wrong execution question.

Decision-time findings:

- full sample road retrace: advanced median 52.3%, failed median 60.5%;
  descriptive AUC 0.384, where lower favors advance
- final eight-tick test-zone net same-side provision: advanced median +7,
  failed median +1; descriptive AUC 0.663
- displayed same-side size at test-zone arrival: advanced median 1, failed
  median 13; static displayed depth did not identify the better tests
- same-side quote adds inside the test zone: advanced median 106, failed median
  46; the evolution was more useful than the seed

The interaction with prior auction context was stronger than any standalone
field:

| context | outcome | n | road retrace median | test-zone provision median | test-zone duration median |
|---|---|---:|---:|---:|---:|
| clean/escaped | advanced | 7 | 46.2% | +16 | 1.858s |
| clean/escaped | failed | 7 | 60.5% | +1 | 1.003s |
| inside two-sided churn | advanced | 8 | 55.6% | +3 | 1.200s |
| inside two-sided churn | failed | 10 | 51.1% | 0 | 1.370s |

Interpretation:

- Inside a clean or already-escaped field, road survival plus fresh
  test-front provision is a plausible entry-quality discriminator.
- Inside active two-sided churn, the same measurements do not separate
  outcomes. A direct conversion there remains one local interaction inside a
  larger ownership-building process.
- Static reload alone is insufficient. Root 34 showed positive local provision
  (+17) while almost the entire favorable road had already been erased.
- The useful object is therefore not "stacked at the band." It is:
  `field state + surviving road + new provision at the current test`.

Named checks:

- July 23 root 111: 68.8% road retrace, failed.
- July 23 root 208: 52.3% road retrace, test-zone provision +26, readvanced and
  advanced.
- July 24 root 34: 97.0% road retrace, failed despite positive local provision.
- July 24 roots 84/89/102: 50.0%/32.4%/46.2% road retrace and all readvanced
  after entry. Root 102 still belongs to the separate later child-propagation
  problem; a good entry test did not make its child sole campaign authority.

This remains discovery, not an implementation threshold. The eight-tick test
strip and 25% material-return definition were fixed before this pass but have
not been sensitivity-tested or validated out of sample.

## Material Road-Step Lifecycle

Probes:

- `research/direct_conversion_execution/scripts/direct_conversion_auction_road.py`
- `research/direct_conversion_execution/scripts/direct_conversion_road_steps.py`
- `research/direct_conversion_execution/scripts/analyze_direct_conversion_road_steps.py`
- main output:
  `research/direct_conversion_execution/out/direct_conversion_road_steps_20260717_20260724/`

Population and provenance:

- 114 classifiable accepted DirectConversion roots across July 17, 20-24
- 953 eight-tick material returns
- 850 returns readvanced, 35 formed favorable sponsorship during the active
  return, and 68 ended in root failure
- 96 actual first entries occurred during an active material return; 92 had
  valid reconstructed book state
- 38,700 fixed-price phase rows from MarketRecorder raw book events
- July 21 late capture has an incomplete reset; affected phases remain flagged
  and are excluded from book tables

The correct lifecycle atom is not one conversion or its first retest. It is one
material return:

`favorable peak -> material step back -> readvance / sponsor advance / root failure`

This resolves root 34 without hindsight. It had 18 completed readvances, then a
nineteenth return beginning at 10:19:09 remained active through the 10:21:10
entry and ended in root failure. The earlier returns were correctly healthy;
the later return changed state.

Named entry-step checks:

| date/root | result | active-step age | penetration | favorable road remaining |
|---|---|---:|---:|---:|
| July 23 root 111 | root failed | 24.7s | 55 ticks | 25 ticks |
| July 23 root 208 | readvanced | 5.0s | 23 ticks | 21 ticks |
| July 24 root 34 | root failed | 120.9s | 224 ticks | 7 ticks |
| July 24 root 84 | readvanced | 3.2s | 22 ticks | 22 ticks |
| July 24 root 89 | readvanced | 0.7s | 11 ticks | 23 ticks |
| July 24 root 102 | readvanced | 3.1s | 18 ticks | 21 ticks |

Across all valid actual entry steps:

- held/advanced step age median 7.3s versus 10.7s for root failures
- favorable displacement from return onset -11 ticks versus -20
- penetration 19 ticks versus 30
- displayed book and whole-step net provision at the entry itself remained
  weak

The role split matters:

- For `EnterBase`, path state was more useful: age 6.3s versus 10.7s,
  displacement -11 versus -22, and penetration 20 versus 30 ticks.
- For `Add`, those path fields did not separate. Net same-side provision during
  the active entry step was -4 for held/advanced versus -11.5 for failure
  (descriptive AUC 0.660). Existing campaign authority can carry a messier
  child return.

Book evolution is useful for the local return, not sufficient for the whole
campaign:

- At one second into an unresolved material return, net same-side provision was
  +5.5 for returns that later held/readvanced versus -4 for returns that ended
  in root failure; descriptive AUC 0.715.
- Across 44 directives containing both outcomes, median within-directive AUC
  for one-second provision was 0.800.
- The direction repeated on all six sessions; day-level AUCs were 0.591, 0.805,
  0.769, 0.611, 0.708, and 0.741 from July 17 through July 24.
- At one second, penetration relative to prior returns was 0.25 for held steps
  versus 0.512 for failures; lower was better.
- Static displayed same-side depth was weak. The causal information was whether
  liquidity was being newly provisioned while the step remained unresolved.

That local-step result does not promote directly to campaign authority:

- On final sponsor-deciding steps, favorable road remaining separated better
  than book provision: one-second medians 90 ticks for sponsor advance versus
  35 for root failure.
- One-second provision on terminal steps was inconsistent by day.
- Therefore `book underneath` answers whether the current step can hold;
  `road remaining + prior sponsor lineage` answers whether failure of that step
  should propagate into the campaign.

## Point-In-Time Profile And Execution Field - 2026-07-26

Research boundary:

- Direct-conversion and lean/rail definitions were not changed.
- Every profile was built only from trades available at the query timestamp.
  The final session profile was never used to label an earlier event.
- RTH cumulative, rolling 30-minute, and rolling 60-minute profiles were tested
  at two- and four-point bin widths.
- Location was measured at root ownership, first test/hold, every material
  return, and each actual EAR order decision.
- Raw trailing book windows covered the fixed eight-tick strip underneath
  current price at each actual decision.

Reusable probes:

- `research/direct_conversion_execution/scripts/direct_conversion_profile_field.py`
  - Builds point-in-time HVN/LVN topology and node-escape state.
- `research/direct_conversion_execution/scripts/analyze_direct_conversion_profile_field.py`
  - Joins topology to first-test, post-hold, entry, local-step, and terminal
    sponsor outcomes.
- `research/direct_conversion_execution/scripts/direct_conversion_entry_provision.py`
  - Now includes 0.5/1/2/5-second fixed-price trailing book windows at each
    accepted order decision.
- `research/direct_conversion_execution/scripts/analyze_direct_conversion_entry_field.py`
  - Joins all 115 actual entries to profile location, ownership-field state,
    trailing book evolution, and sponsor-lineage outcome.

Primary outputs:

- `research/direct_conversion_execution/out/direct_conversion_profile_field_20260716_20260724/`
- `research/direct_conversion_execution/out/direct_conversion_entry_field_20260717_20260724/`

### Static Location Does Not Reclassify The Event

Among 529 tested roots with valid two-point RTH profiles at ownership:

- HVN interior first-test hold: 135/187 (72.2%).
- One-sided LVN first-test hold: 73/101 (72.3%).
- Transition first-test hold: 140/189 (74.1%).
- HVN edge samples were smaller and did not produce a stable ordering.

Post-first-hold sponsor outcomes were similarly flat:

- HVN interior advanced: 58/132 (43.9%).
- One-sided LVN advanced: 27/66 (40.9%).
- Transition advanced: 62/143 (43.4%).

Therefore neither `inside HVN` nor `inside LVN` is a defensible validity or
suppression rule for the original direct conversion. This supports preserving
the event as a local ownership fact.

The strict "LVN between two HVNs" population was sparse:

- RTH two-point root events: 3/3 held first test, but only two dates.
- Rolling 60-minute two-point root events: 8/11 held (72.7%), effectively the
  same as the full first-test population.

The user's observed pattern remains plausible, but this sample does not validate
it as a general rule. Broadening the node search and valley cutoff did not
materially increase the point-in-time population. A retrospective final profile
would produce more examples but would leak the later node formation being
studied.

### Location Matters More As The Field Evolves

The stronger effect appears at the current material return rather than at the
original conversion.

Across 793 valid RTH two-point material steps:

- Successful/readvancing steps began at median profile percentile 0.535.
- Root-failing steps began at median percentile 0.740.
- Descriptive AUC was 0.366, where lower traded density favored local survival.

Across the rolling 60-minute profile:

- Successful steps began 25.6 points in the favorable direction from rolling
  VPOC versus 8.25 points for failures; AUC 0.622.
- At terminal sponsor-deciding steps, the separation increased to 36.6 versus
  8.25 points; AUC 0.699.
- Day AUCs for terminal promotion were 0.500, 0.690, 0.667, 0.842, 0.833,
  and 0.614 from July 17 through July 24.

A coarse, descriptive terminal split:

| start relative to rolling VPOC | terminal steps | sponsor-advanced |
|---|---:|---:|
| more than 20 points favorable | 44 | 47.7% |
| 0-20 points favorable | 20 | 30.0% |
| 0-20 points adverse | 16 | 25.0% |
| more than 20 points adverse | 20 | 15.0% |

The 20-point cut was chosen after seeing the medians and is not an
implementation threshold. The defensible result is the continuous ordering:
sponsor promotion became more likely as the current return established farther
in the favorable direction from recent accepted business.

This is closer to "permission to escape" than an HVN/LVN label. The event may
be valid inside value, but the evolving campaign earns promotion by establishing
normal business beyond recent value.

### Book Evolution Has Different Jobs At Different Stages

At one second into all unresolved material returns, positive net same-side
provision improved local step survival across the 60-minute topology:

- HVN interior: 90.0% provisioning versus 76.1% draining.
- One-sided LVN: 97.2% versus 87.3%.
- Transition: 93.6% versus 82.6%.

That does not make provision a sponsor-promotion rule. On the smaller set of
terminal steps:

- HVN interior promotion was 12.5% while provisioning versus 38.9% while
  draining.
- One-sided LVN promotion was 63.6% while provisioning versus 43.8% while
  draining.
- Transition was 20.0% versus 25.0%.

The exact rates are small-sample discovery. The durable distinction is that
`book underneath` can answer whether the current return can hold/readvance,
while location and prior lineage still determine whether that local hold should
promote the campaign. Restacking inside an HVN can be another turn of the
contest rather than escape evidence.

### Actual EAR Order Decisions

Raw-book decision sample:

- 115 accepted DirectConversion entries on July 17 and July 20-24.
- 113 had resolved lineage outcomes: 46 advanced before root failure and 67
  failed first.
- 61 directives.
- July 16 was excluded because all reconstructed windows were unopened due to
  missing reset state.
- The six admitted sessions replayed with no gaps or unopened windows.

Simple net restacking in the final 0.5-5 seconds failed as a base-entry
qualifier:

- One-second net owner provision had day AUCs 0.312, 0.434, 0.345, 0.520,
  0.643, and 0.402.
- Successful bases often had more net depletion at the decision, consistent
  with favorable passive liquidity being actively tested rather than quietly
  stacked.

Gross activity had a role-dependent meaning:

- For adds, 500ms gross owner additions had AUC 0.707 and removals had AUC
  0.677. Both rose, which looks like defended turnover under existing campaign
  authority rather than a static stack.
- For bases, 500ms owner additions were much weaker alone (AUC 0.587).

Rolling profile position helped actual entry outcomes modestly:

- Current price versus 60-minute VPOC: successful median +9.875 points,
  failures 0.0; AUC 0.603.
- Day AUCs were 0.417, 0.643, 0.524, 0.656, 0.810, and 0.545. July 17 is the
  explicit counterexample.

The strongest base interaction restored LL's prior ownership-field memory:

| base context at decision | entries | advanced |
|---|---:|---:|
| clean field + favorable of 60m VPOC | 11 | 63.6% |
| clean field + adverse of 60m VPOC | 16 | 43.8% |
| two-sided failure churn + favorable of 60m VPOC | 22 | 31.8% |
| two-sided failure churn + adverse of 60m VPOC | 21 | 19.0% |

All four cells span at least five dates. They are correlated within directives
and remain discovery, but this ordering matches the old gray-zone workflow:
ownership inside a contested field is not enough; escape/clean context and
where the current auction sits relative to accepted business change execution
permission.

Gross 500ms owner additions reinforce that interpretation. Using a same-date,
same-role median only as a rank audit:

- Base, adverse of rolling VPOC: high activity advanced 16.7% versus 42.1% for
  lower activity. Aggressive restacking there may be active contest, not
  defense.
- Base, favorable of rolling VPOC: high activity advanced 50.0% versus 35.3%.
- Adds improved with higher owner-add activity on both sides of VPOC, consistent
  with parent campaign authority changing the meaning of the same book action.

Do not implement those median cuts. The causal candidate is the interaction:
`ownership field state + accepted-value position + role + order evolution`.

### Named Decisions Under The New Lens

- July 24 root 34, 10:21 short:
  - HVN interior, node not escaped, current price 14 points adverse of rolling
    VPOC; root failed.
- July 24 root 84, 11:50 long:
  - HVN interior and not escaped, but current price 8.25 points favorable of
    rolling VPOC; entry advanced. This is the counterexample to suppressing HVN
    entries categorically.
- July 24 root 89, 11:55 long:
  - Transition field, 48.5 points favorable of rolling VPOC; advanced.
- July 24 root 102, 12:10 add:
  - One-sided LVN, 115.75 points favorable of rolling VPOC; entry advanced.
  - Its later child failure remains a separate campaign-authority problem.
- July 23 root 111, 12:19 short:
  - HVN adverse edge, current price 122.25 points adverse of rolling VPOC;
    failed.
- July 23 root 208, 14:35 short:
  - Transition field but 14.25 points adverse of rolling VPOC; advanced.
  - This prevents rolling VPOC position from becoming a hard gate.

### Revised Research Interpretation

1. A direct conversion remains a valid local ownership event.
2. Proximity opens an execution decision; it should not be the full decision.
3. For a base, recent two-sided ownership failure is the strongest warning.
   Rolling accepted-value position refines whether the event is still inside
   contest or beginning to escape it.
4. Local provision describes whether the current return is holding. The same
   provision inside an HVN cannot independently promote the campaign.
5. Adds inherit parent sponsor authority, so high same-side turnover can be
   supportive even when it would be ambiguous for a base.
6. Sponsor promotion belongs to the evolving road and current location, not to
   a permanent quality label attached to the root.
7. Existing sponsor-failure exits remain defensible. This pass concerns order
   admission and promotion, not weakening failure response.

No runtime rule should be changed from this discovery sample. The next
implementation step, if future sessions reproduce the ordering, is shadow-only
state: point-in-time rolling VPOC distance, ownership-field state, role, active
return state, and short-window gross/net owner flow.

## Current Two-Stage Thesis

Entry permission:

1. A confirmed direct consumption seeds a provisional root; displacement and
   execution proximity are not campaign proof.
2. Determine whether entry occurs during an active material return.
3. For a base, evaluate unresolved-step age, penetration, worsening versus
   prior returns, and road remaining.
4. For an add, retain parent sponsor context and put more weight on whether
   same-side provision is re-establishing during the active return.
5. Do not substitute static depth for evolution.

Campaign authority:

1. Re-evaluate each material return rather than assigning one permanent quality
   label to the conversion.
2. One-second path and provision describe whether the local step is holding.
3. A local step failure is not automatically campaign failure.
4. Road remaining, prior sponsor survival, and child spatial independence
   determine whether the local failure is contained or propagates.
5. A local child should not become sole flatten authority merely because it
   promoted.

## Falsifiers And Limits

- Static same-side depth or reload is not sufficient. Root 84's child depth
  disappeared quickly but the parent campaign survived; root 102 stacked at
  entry but its later child failure propagated.
- Plain time-to-retest and "fast/urgent" remain rejected. Active-step age is
  retained only as part of a causal state with penetration, prior-step
  comparison, remaining road, and book evolution.
- Snapshot features are 1 Hz and cover the nearest 30 levels per side. Raw book
  events capture all real L2 updates, but broad historical state still requires
  forward replay.
- The synthetic held-rail audit shows that directive and decision alignment are
  material. Results from accepted orders cannot be promoted to a universal LL
  event classifier.
- Entries within one directive/campaign are correlated.
- July 21 is a regime counterexample where all sampled conversions failed,
  including stacked clean/escape cases. Auction context is still incomplete.
- Fixed 0.5/1/2/5-second checkpoints avoid terminal endpoint leakage, but steps
  remain correlated within roots and directives.
- One-second provision is consistent for local step readvance but not for final
  sponsor outcome. It must not become a standalone campaign rule.
- Eighteen accepted roots entered outside an active eight-tick return; being on
  a material return by itself did not change the advance rate.
- Static HVN/LVN location at the original conversion did not separate first
  test or post-hold outcomes. Profile location must not be used to invalidate
  the event.
- Rolling VPOC position was directionally useful but not universal; July 17
  and the July 23 root 208 fixture are explicit counterexamples to a hard gate.
- Trailing net restacking at actual entry was inconsistent by day. Gross owner
  activity only became interpretable after role and field context were known.

## Next Tests

1. Freeze the point-in-time profile and actual-entry measurements, then validate
   the ownership-field/VPOC ordering on future sessions without changing cuts.
2. Sensitivity-test 6/8/12-tick material returns and underneath zones as
   robustness checks, not threshold selection.
3. Apply point-in-time profile state to compatible synthetic held roots so the
   actual-order interaction is audited for EAR selection bias.
4. If the future pass holds, add shadow-only runtime fields for active return
   ordinal, age, penetration, road remaining, rolling VPOC distance,
   ownership-field state, and gross/net provision; do not gate orders yet.
5. Align the same step state to first child failure, then combine it with the
   already-discovered child spatial-independence rule.
6. Audit July 21's incomplete capture separately and do not infer book state
   from the invalid late partition.
7. Add ETH/prior-session topology only after consistent overnight recorder
   coverage exists; do not backfill it from final-session hindsight.

## Conditional Terrain Execution Policy - 2026-07-26

### Question

Static profile terrain at conversion did not classify whether a direct
conversion would hold. This pass asked the narrower execution question:

> Among conversions whose first test eventually holds, should point-in-time
> terrain change how the test is executed?

The replay is in
`research/direct_conversion_execution/scripts/direct_conversion_terrain_execution_policy.py`. Primary output is:

- `research/direct_conversion_execution/out/direct_conversion_terrain_execution_20260716_20260724/`
- `policy_decisions.csv`: every root/configuration/policy counterfactual.
- `terrain_policy_summary.csv`: policy behavior by terrain.
- `cluster_uncertainty.csv`: whole-date bootstrap and leave-one-date-out audit.
- `age_policy_summary.csv`: prompt versus late first-test audit.

Two timestamps are deliberately separate:

1. `first_test` freezes terrain when the root is first touched. This directly
   answers the conditional execution question, but membership uses the later
   `HELD_FIRST_TEST` verdict and therefore is not a causal hold classifier.
2. `first_hold` freezes terrain when `RailHeld` is causally known. This is
   implementable information, but a root can receive its first test much later
   than the original entry campaign.

The primary rolling 60-minute, two-point population had 416 valid first-test
profiles: 177 later established a favorable successor before root failure and
239 failed first.

### Main Result: An Unescaped HVN Creates A Proof Obligation

At first test, 150 held roots were still inside their containing 60-minute HVN:

| policy inside unescaped HVN | advances captured | failures exposed | selectivity |
|---|---:|---:|---:|
| market immediately | 63/63 | 87/87 | 0.000 |
| wait for favorable HVN-edge trade | 45/63 | 46/87 | +0.186 |
| require two-sided trade beyond edge | 44/63 | 42/87 | +0.216 |
| passive at consumed-band edge for 30s | 59/63 | 83/87 | -0.018 |

`Selectivity` is advance-capture rate minus failure-exposure rate. It is not a
PnL objective.

The HVN-edge result survived every profile sensitivity:

- 30-minute, two-point: +0.363.
- 30-minute, four-point: +0.264.
- 60-minute, two-point: +0.186.
- 60-minute, four-point: +0.266.
- RTH, two-point: +0.296.
- RTH, four-point: +0.278.

For the primary configuration, whole-date bootstrap intervals were:

- Edge touch: +0.094 to +0.281.
- Two-sided beyond-edge trade: +0.131 to +0.307.

Edge touch was positive on five dates, negative on one, and neutral on one.
The two-sided variant was positive on six and neutral on one. Leave-one-date-out
selectivity remained positive.

This is not evidence that an HVN conversion is invalid. It says the same valid
local ownership event has a different execution burden while the containing
node remains unescaped. The auction must first demonstrate that normal business
can occur beyond the node.

### Confirmation Is Expensive

The policy did not manufacture better prices:

- Successful edge-touch entries inside the unescaped 60-minute HVN paid a
  median 6.5 points versus market at first test.
- Across profile sensitivities, the successful confirmation cost was roughly
  6.5 to 9 points.
- Waiting did not improve subsequent MAE enough to offset that cost in this
  structural study.

An escape-then-passive-retest policy did not solve the tradeoff. It captured
fewer advances, remained several points worse than market at the original test,
and was less selective than entering on escape.

Therefore this result supports `wait or skip` inside an unescaped HVN more than
it supports a universal delayed market order. Whether the confirmation cost is
acceptable depends on campaign role and available road, which this
sponsor-outcome study does not price.

### Passive Return To The Consumed Band Is Not Protection

At first test, a 30-second passive opportunity at the consumed-band edge filled
90.4% of later advances and 95.0% of later failures across the primary
population. After hold confirmation it became more anti-selective: 47.5% of
advances versus 76.2% of failures.

That matches the auction mechanism. Failed sponsors are especially likely to
trade back through the consumed band. A better price at the old band is not
additional ownership proof.

### VPOC Is Terrain-Conditional, Not A Global Gate

Waiting while adverse of rolling VPOC was useful in some terrain and harmful or
empty in others:

- Unescaped HVN: +0.199 selectivity.
- Transition: +0.177.
- LVN: -0.026 with a wide date-clustered interval.
- Already-escaped HVN: -0.133 on only 16 roots.

The pooled VPOC gate looked useful because it mixed these states. The safer
interpretation is not "never execute adverse of VPOC." Rolling accepted value
helps specify the remaining proof obligation only after current terrain is
known.

### Two-Sided Acceptance Sensitivity

The exact beyond-edge tape definition was not fragile:

| trailing acceptance definition | advances captured | failures exposed |
|---|---:|---:|
| 1 second, 2 prints, both signs | 45/63 | 42/87 |
| 2 seconds, 4 prints, both signs | 44/63 | 42/87 |
| 5 seconds, 8 prints, both signs | 44/63 | 42/87 |

This small incremental improvement over edge touch is not enough to choose a
runtime threshold. It does justify continuing to study the book underneath
after escape; the main result does not depend on a fast/urgent time heuristic.

### Fixture Corrections

- July 24 roots 34 and July 23 root 111 failed their first test and correctly
  do not enter this held-test population.
- July 24 root 89 tested 16 seconds after ownership in transition terrain,
  already favorable of rolling VPOC. Terrain policies correctly reduce to
  immediate execution; it later advanced.
- July 24 root 102 tested after 41.5 seconds in an LVN and favorable of rolling
  VPOC. Terrain did not protect it from its later root failure. This remains a
  campaign-authority/child problem, not an HVN escape problem.
- July 24 root 84 did advance after its 11:50 entry, but its first held test was
  not until 12:40 and that later post-hold root outcome failed. Those statements
  describe different stages.
- July 23 root 208 first tested around 15:25, roughly 49.5 minutes after its
  14:35 entry. Its adverse rolling-VPOC position would have skipped a later
  advance, preserving it as a counterexample to a global VPOC gate.

### Revised Answer

Terrain does not replace direct-conversion validity. It can modulate execution
after the event:

1. Inside an unescaped containing HVN, proximity is insufficient. Arm the idea
   and require favorable node escape; two-sided business beyond the edge is a
   plausible refinement.
2. In transition/LVN or after the containing node has escaped, there is no
   evidence for imposing that same HVN gate. Execution must return to road,
   lineage, and book evolution.
3. Do not default to passive execution back at the consumed band. That price is
   disproportionately revisited by failures.
4. Do not turn rolling VPOC into a universal admission rule.

No EAR or LevelLedger runtime rule changed. The next defensible step is
prospective shadow output that records the causal profile edge, escaped/not
escaped state, beyond-edge two-sided acceptance, confirmation cost, parent
sponsor context, and remaining road on future sessions.

## Time-Of-Day Separation - 2026-07-26

The reusable audit is
`research/direct_conversion_execution/scripts/analyze_direct_conversion_time_windows.py`. Output is under:

- `research/direct_conversion_execution/out/direct_conversion_time_windows_20260716_20260724/`
- `lifecycle_window_summary.csv`: all tested direct conversions by daypart.
- `morning_midday_comparison.csv`: whole-date comparison and bootstrap.
- `policy_window_summary.csv`: held-test counterfactuals by daypart.
- `midday_afternoon_transition.csv`: continuous price and LL transition map.
- `afternoon_midday_role_policy_summary.csv`: afternoon execution conditioned
  only on information known at 13:30.

Windows use first-test timestamp:

- Morning: 09:30-11:30.
- Midday: 11:30-13:30.
- Afternoon: 13:30-15:30.
- Late: 15:30-16:00.

### Midday Is More Contested, Not More Structurally Unreliable

Across every tested consumed rail:

| first-test window | tested | first test held | post-hold advanced | questionable | two-sided churn |
|---|---:|---:|---:|---:|---:|
| morning | 137 | 74.5% | 27.5% | 79.6% | 41.6% |
| midday | 216 | 72.2% | 46.8% | 66.2% | 75.5% |
| afternoon | 190 | 71.6% | 47.0% | 66.7% | 69.5% |

`Questionable` means failed first test or a held first test whose root failed
before establishing a favorable successor.

Midday versus morning:

- First-test hold rate was only 2.2 percentage points lower, with a
  date-bootstrap interval spanning zero.
- Two-sided LL failure churn was 33.9 points higher, interval +24.1 to +43.8,
  and higher on all seven dates.
- Post-hold advancement was 19.3 points higher, interval +6.2 to +33.6.
- Structural questionable rate was 13.4 points lower, interval -25.7 to -1.4.

Therefore the user's visual observation is right about the fight and wrong only
if "questionable" is defined as eventual sponsor reliability. Midday creates
many more ownership claims and failures around the same field, but the claims
that survive can become the resolution of that fight.

The practical midday problem is execution ambiguity:

- The unescaped-HVN edge gate retained +0.219 selectivity.
- Successful entries paid a median 7.875 points of confirmation cost, versus
  2.375 points in the morning.

This supports reduced participation during the fight because timing and price
quality deteriorate, not because midday direct conversions are intrinsically
invalid.

### Excluding Midday Does Not Improve The Main Terrain Result

For first tests inside an unescaped 60-minute HVN:

| sample | edge-touch selectivity | two-sided escape selectivity |
|---|---:|---:|
| full RTH | +0.201 | +0.233 |
| all non-midday | +0.194 | +0.233 |
| morning + afternoon only | +0.168 | not promoted |

The full edge-touch date-bootstrap interval was +0.099 to +0.301. Excluding
midday widened it to +0.021 to +0.352. The two-sided result remained positive:
+0.080 to +0.365.

Removing 11:30-13:30 therefore does not reveal a cleaner hidden relationship.
It reduces the population and slightly weakens the pooled result. The terrain
conclusion is not being manufactured by midday churn.

### Separating Windows Does Improve The Interpretation

The same unescaped-HVN edge policy has different costs and usefulness:

| window | edge selectivity | successful confirmation cost |
|---|---:|---:|
| morning | +0.333 | 2.375 points |
| midday | +0.219 | 7.875 points |
| afternoon | +0.102 | 5.250 points |

Morning is the cleanest execution environment. Midday still benefits from
escape proof, but often at a price that can consume the available road.
Afternoon is weak when pooled, supporting the user's view that it inherits
state from the midday resolution.

### Afternoon Needs A Midday-Role Variable

The first future-labeled audit split afternoons into price continuation versus
counter:

- Continuation afternoons: HVN edge selectivity -0.094.
- Counter afternoons: +0.420.

This cannot be generalized. Every afternoon in the seven-day sample had a
negative net move, so the split is entangled with one directional regime.

A causal version uses only the completed 11:30-13:30 net direction, known at
13:30:

| afternoon conversion role | HVN edge | two-sided HVN escape | VPOC gate |
|---|---:|---:|---:|
| with midday direction | +0.346 | +0.346 | -0.024 |
| against midday direction | -0.038 | +0.045 | +0.108 |

Cells are small:

- HVN policies: 25 with-midday roots and 25 against-midday roots.
- VPOC policy: 64 and 66 roots.

This is hypothesis-strength evidence, not an implementation rule. It suggests
that afternoon events need an explicit role:

1. A conversion aligned with the completed midday move asks whether that move
   can escape its next containing node. HVN-edge proof is informative.
2. A conversion against the midday move is a repair/counter attempt. Merely
   escaping its local HVN is not enough; recent accepted-value position may be
   more relevant.

This is more precise than a blanket "avoid afternoon" or "exclude midday."
Time does not supply the rule by itself. The completed midday auction supplies
campaign context that changes the meaning of the same terrain interaction.

### Revised Time-Window Conclusion

1. Keep midday in research datasets.
2. Report morning, midday, and afternoon separately.
3. Treat midday as a high-churn, high-confirmation-cost formation phase.
4. Treat afternoon direct conversions relative to the completed midday
   direction and accepted-value field.
5. Do not use time-of-day alone to invalidate ownership or suppress rails.

No runtime behavior changed. Future-session validation needs both positive and
negative afternoon regimes before the midday-role interaction can enter even a
shadow runtime field.

## Proximity LOB And Competing-Passage Audit - 2026-07-26

The reusable builders and analyzers are:

- `research/direct_conversion_execution/scripts/direct_conversion_proximity_book_state.py`
  - Replays validated quote-ID deltas and starts observation at the first
    executable quote inside EAR's 20-tick direct-conversion envelope.
  - Separates quote additions/removals from tape consumption and reports
    removal-minus-consumption only as a pulling proxy.
  - Measures the fixed rail, eight ticks behind it, the 1-20 tick bridge, the
    21-28 tick road beyond it, and the live eight-level road from the quote.
- `research/direct_conversion_execution/scripts/analyze_direct_conversion_proximity_policy.py`
  - Audits market-now, fixed delay, static/dynamic field gates, and whether an
    advancing campaign was still enterable after a delay.
- `research/direct_conversion_execution/scripts/analyze_direct_conversion_competing_passage.py`
  - Replaces clock delay with event-time passage: favorable escape from the
    envelope versus a step back toward the rail, followed by escape-return or
    challenge-recovery.

Primary outputs:

- `research/direct_conversion_execution/out/direct_conversion_proximity_book_20260717_20260724/`
- `research/direct_conversion_execution/out/direct_conversion_proximity_policy_waitability_20260717_20260724/`
- `research/direct_conversion_execution/out/direct_conversion_competing_passage_20260717_20260724/`

### Capture And Label Integrity

The six-day replay processed 92,877,618 raw book rows. There were no sequence
gaps; reset boundaries were honored. Of 538 structurally resolved roots
presented to the audit, 492 had complete proximity/book episodes:

- 206 advanced to a favorable successor after proximity.
- 286 failed before a favorable successor formed after proximity.
- 23 were book-invalid at ownership.
- 10 never entered the 20-tick envelope.
- 6 resolved before observable activation.
- 5 crossed a capture reset before proximity.
- 2 remained unresolved after proximity.

The successor clock deliberately restarts at proximity. A child formed before
the executable decision cannot make a later entry look successful. This
corrects July 24 root 34: its earlier child was stale by the 10:21:10 proximity
decision, and the root failed at 10:21:23.

### Static Book Confirmation Does Not Solve Entry

Book state carries weak ranking information but not a robust admission gate.
At first proximity, supportive-flow AUCs were 0.55-0.57. At five seconds,
owner-under-depth survival reached AUC 0.613.

The actionable policies failed:

- At 60 seconds, the joint support/road gate captured 35.0% of advances and
  exposed 34.3% of failures: only +0.007 selectivity.
- Waiting for non-eroding support captured 77.7% of advances but exposed 88.1%
  of failures.
- Waiting for road clearing captured 39.3% of advances and exposed 54.2% of
  failures.
- A blind 0.5-second delay captured 92.7% of advances while still exposing
  99.0% of failures. Two seconds captured 87.4% versus 97.2%.

Failed roots remain close and repeatedly visit supportive-looking states. A
generic "wait for confirmation" rule therefore creates adverse selection: it
misses advancing campaigns that leave while retaining failures that keep
offering apparently attractive entries.

### Immediate Versus Waitable Advances

Among the 206 advancing roots:

| delay | no later eligible quote | still enterable | median improvement if enterable |
|---:|---:|---:|---:|
| 0.5 seconds | 14 | 93.2% | 0.25 points |
| 1.0 second | 16 | 92.2% | 0.25 points |
| 2.0 seconds | 23 | 88.8% | 0.50 points |
| 5.0 seconds | 40 | 80.6% | 0.75 points |

At the same delays, 99.7%, 99.7%, 99.3%, and 97.2% of failed roots were still
enterable. Delay improves price modestly but does almost nothing to remove bad
entries.

Low pre-proximity support/road clearing was the strongest marker of the rare
"must enter now" winners. That is mechanically plausible: some successful
escapes are aggression-led before passive support can rebuild. It is not a
quality signal. Leave-one-date-out 0.5-second urgency recall was 71.4%, but
precision was only 11.1%; the resulting policy exposed every failure and still
missed 1.9% of advances.

### Event-Time Passage And Retest

With a favorable move beyond the 20-tick envelope competing against an
eight-tick step back toward the rail:

- Escape occurred first in 84.0% of advances and 77.6% of failures.
- Challenge occurred first in 16.0% of advances and 22.4% of failures.
- The escape-first advantage was only +0.064 and was similar under 4-, 8-, and
  12-tick challenge definitions.

Waiting for event-defined retests was not sufficient:

- Escape-return captured 70.4% of advances and exposed 71.3% of failures.
- Challenge-recovery captured 13.1% and exposed 15.0%.
- Taking either retest captured 83.5% and exposed 86.4%.

Book state measured specifically at escape-return was more coherent than the
generic gate. Greater two-second owner support had AUC 0.594. A
leave-one-date-out, single-feature book gate improved escape-return selectivity
from -0.009 to +0.027, capturing 51.0% of all advances and exposing 48.3% of
all failures. It is not stable enough to promote:

- Date-cluster bootstrap interval: -0.108 to +0.171.
- Held-out July 17 and July 20 were negative.
- Held-out July 24 was strongly positive and dominates the intuitive fixtures.

Challenge-recovery book qualification was negative overall and is rejected.

### Named Fixtures

- July 24 root 34 at 10:21 challenged first and did not recover within 60
  seconds. A challenge-recovery policy avoids it, but July 23 root 111 is the
  necessary counterexample: it challenged, recovered, and still failed.
- July 24 root 84 escaped and returned at 11:50:26, offering 28516.00, 0.75
  points better than first proximity. The held-out support gate accepted it.
- July 24 root 89 escaped and returned after two seconds at 28556.50. The gate
  accepted it.
- July 24 root 102 escaped and returned after 0.5 seconds at 28624.00. The gate
  accepted it.
- July 23 root 208 advanced without a 60-second return into the envelope. Any
  mandatory escape-return policy misses this successful campaign.

### Revised Execution Answer

1. There is no evidence yet to replace first eligible market execution with a
   fixed delay or a generic supportive-book threshold.
2. The useful stochastic framing is competing first passage and conditional
   retest, not a diffusion-time urgency scalar. Direct absorptions from
   quarter-second Markov states are too sparse, and repeated state samples are
   not independent.
3. The best surviving motif is escape, return, and owner support rebuilding
   during that return. It is a research lead for retest entry, add/promotion,
   and hold authority, not a suppression rule for the initial entry.
4. A future shadow field should preserve the whole sequence: first passage,
   return type, support/road changes from proximity to return, and whether
   ownership advances afterward. More dates are required before considering a
   runtime action.

No EAR or LevelLedger runtime behavior changed.

## Execution Phase Policy: Proximity, Rail Arrival, And Reclaim - 2026-07-26

The reusable audit is:

- `research/direct_conversion_execution/scripts/direct_conversion_execution_phase_policy.py`

Primary output:

- `research/direct_conversion_execution/out/direct_conversion_execution_phase_policy_20260717_20260724/`

It reuses the same 492 complete roots and keeps three information sets
separate: the first 20-tick proximity, the road from proximity to the rail,
and the later reclaimed-edge test. A rail crossing means the executable quote
reached or passed the favorable edge. It does not prove that a passive order
received a queue fill.

### Waiting For The Actual Rail Is Not A Replacement For Market At 20

Only 87 of 206 advancing roots reached the favorable rail edge before their
favorable successor formed. By contrast, 283 of 286 failing roots reached it:

| window | winner rail-touch capture | failure rail-touch exposure |
|---|---:|---:|
| all day | 42.2% | 99.0% |
| 09:30-11:30 | 36.4% | 98.9% |
| 11:30-13:30 | 42.7% | 99.0% |
| 13:30-16:00 | 45.2% | 98.9% |

For advancing roots that did touch, the median executable-price improvement
from waiting was 5.25 points and the median delay was 20 seconds. That price
improvement is not free: waiting would miss most advancing roots while avoiding
almost none of the roots that eventually fail.

Information already available at initial proximity did not identify which
advancing roots were safe to wait on. The strongest all-day feature AUC was
only 0.562. Before 11:30, owner-field adverse quantity reached 0.647 on just
16 rail-touch and 28 no-touch winners; that is small, outcome-conditioned, and
not an execution rule.

Two-sided exact-band interaction is also generally unavailable at the initial
decision: 491 of 492 roots had zero measured two-sided band quantity by first
20-tick proximity. The interaction happens later. A proposed "market fresh,
require support if already contested" entry gate therefore changes only one
root in this sample.

### Interaction Makes Owner Support More Meaningful, Not Less

At the prior eight-tick escape-return re-approach, 349 roots had an opportunity
and 19 had already accumulated two-sided exact-band business:

| interaction by re-approach | owner support | n | advance rate |
|---|---|---:|---:|
| none | pass | 232 | 43.1% |
| none | fail | 98 | 39.8% |
| two-sided | pass | 11 | 45.5% |
| two-sided | fail | 8 | 12.5% |

Without a measured challenge, the held-out owner-support gate adds only 3.3
points and its date-cluster interval crosses zero. After two-sided interaction,
the raw difference is +33.0 points; the date-cluster interval is 0.0 to +75.0
points. This is promising but only 19 roots. It is not morning evidence: the
pre-11:30 two-sided subset contains five roots and none advances regardless of
the support gate.

At the first actual rail crossing, contemporaneous five-second exact-rail
interaction and owner support produce the same directional pattern:

| rail interaction | owner support | n | advance rate |
|---|---|---:|---:|
| none | pass | 97 | 28.9% |
| none | fail | 100 | 19.0% |
| two-sided | pass | 116 | 27.6% |
| two-sided | fail | 57 | 14.0% |

Within the two-sided stratum, the date-cluster interval for the support effect
is +0.2 to +24.0 points. Therefore continued two-sided business does not mean
automatic failure. When owner support appears while both sides transact, that
business can be the test that proves absorption or defense. The adverse case
is challenged business without owner support.

The strongest combination remains the later reclaimed-edge phase. With
two-sided reclaim transit, the held-out five-second support gate advances
structurally 34.6% versus 12.5%; the date-cluster interval is +3.7 to +35.9
points. Before 11:30, the same combination readvances locally 78.6% versus
38.5%, with a +13.9 to +72.7 point cluster interval. Its structural morning
sample remains too small to establish a campaign rule.

### Thin Versus Strong Approach

Arrival shape was defined from information accumulated while waiting:

- `THIN_EFFICIENT`: high adverse displacement per contract with below-median
  adverse quantity.
- `HEAVY_ABSORBED`: above-median adverse quantity with low displacement
  efficiency.
- `HEAVY_EFFICIENT`: above-median quantity and high displacement efficiency.

Thin-efficient and heavy-absorbed arrivals do not independently separate
survival. All-day advance rates are 23.7% and 25.0%. Owner support improves
both:

| arrival | support pass | support fail |
|---|---:|---:|
| thin-efficient | 28.6% | 14.6% |
| heavy-absorbed | 29.2% | 20.3% |
| heavy-efficient | 28.6% (n=7) | 16.3% (n=43) |

The notable adverse bucket is a heavy, efficient attack before 11:30: only one
of 22 advances, and only three pass the owner-support gate. This is evidence
that an effective adverse approach with no rebuilding underneath should not be
made safer merely by changing a market order to a passive rail order.

### Execution Implication

1. Do not replace first-proximity market execution with a universal wait for
   the rail. The wait misses 58% of advancing roots and retains 99% of failures.
2. Do not interpret two-sided band interaction as an automatic flatten. It can
   make contemporaneous owner support more informative because the support has
   actually been challenged.
3. Treat heavy-efficient adverse arrival plus absent owner support as the first
   candidate for suppressing an add/promotion or for an earlier provisional
   exit. Keep this shadow-only until the named failures and counterexamples are
   visually audited.
4. At a deliberately awaited rail test, "no support" means withhold execution,
   not "use a limit instead of market." A passive order at a run-through rail
   is not a quality improvement.
5. Keep strict `RailFailed` flatten semantics. At the reclaimed-edge repair
   phase, phase-aligned owner support remains the better candidate for hold,
   rearm, or promotion.

No EAR or LevelLedger runtime behavior changed.

### Owner-Flow Manual Review Shortlist

The saved shortlist is
`research/direct_conversion_execution/out/direct_conversion_competing_passage_20260717_20260724/manual_review_shortlist.csv`.
It deliberately compares the positive July 24 held-out fold with the negative
July 17 fold. Both folds used the same two-second owner-net-flow feature, with
thresholds -0.346930 and -0.340501 respectively.

Correct July 24 calls:

| root | side / rail | return | owner add/remove | score | resolution |
|---:|---|---|---:|---:|---|
| 41 | Demand 28278.00-28281.00 | 10:45:01 at 28278.50 | 521 / 699 | -1.194631 | correctly rejected; failed 10:45:36 |
| 63 | Supply 28489.75-28491.50 | 11:19:11 at 28485.25 | 380 / 459 | -1.295082 | correctly rejected; failed 11:20:28 |
| 84 | Demand 28502.75-28511.75 | 11:50:26 at 28516.00 | 234 / 255 | -0.095890 | accepted; child 86 at 11:50:59 |
| 89 | Demand 28549.25-28551.75 | 11:55:45 at 28556.50 | 391 / 402 | -0.067073 | accepted; child 95 at 12:03:25 |
| 102 | Demand 28617.75-28619.50 | 12:10:42 at 28624.00 | 324 / 338 | -0.070000 | accepted; child 103 at 12:10:55 |

July 17 mistakes and falsifiers:

| root | side / rail | return | owner add/remove | score | mistake |
|---:|---|---|---:|---:|---|
| 10 | Demand 28625.25 | 09:30:24 at 28628.00 | 486 / 515 | -0.906250 | rejected, but child 11 formed 09:31:57 |
| 26 | Demand 28674.75-28676.75 | 10:00:22 at 28680.25 | 200 / 220 | -0.555556 | rejected, but child 33 formed 10:08:35 |
| 75 | Supply 28738.25-28740.00 | 11:27:04 at 28733.25 | 220 / 214 | +0.042553 | accepted despite root failure 11:29:28 |
| 93 | Supply 28917.50-28921.50 | 11:58:05 at 28912.50 | 362 / 380 | -0.214286 | accepted despite root failure 11:58:59 |
| 102 | Demand 28853.75-28854.00 | 12:08:04 at 28857.50 | 399 / 430 | -1.192308 | rejected, but child 106 formed 12:12:18 |

The first manual checks should be:

1. Whether additions/removals were concentrated at the rail and underneath or
   elsewhere in the broad owner field.
2. Whether removals were aggressive consumption or cancellations.
3. Whether the return itself was an opposing-side attack that was absorbed or
   merely a quote/path oscillation.
4. For false negatives, whether a second repair after the measured return
   rebuilt ownership before the child formed.
5. For false positives, whether displayed support disappeared immediately
   after the two-second measurement.

## Post-Formation Band Lifecycle And Phase-Aligned Book - 2026-07-26

The reusable builder is:

- `research/direct_conversion_execution/scripts/direct_conversion_band_lifecycle.py`

Primary output:

- `research/direct_conversion_execution/out/direct_conversion_band_lifecycle_20260717_20260724/`

The population is the same 492 complete six-day proximity episodes: 206
advanced to a favorable successor and 286 failed first. The script preserves
the exact consumed-band edges, aggressor tape, structural lineage endpoint,
the prior escape-return decision, and the existing 250 ms proximity-book state.

### Definitions

For either side, coordinates are normalized so positive is favorable to the
owner. Post-formation two-sided business inside the exact consumed band is:

```
min_side_qty = min(favorable_aggressor_qty, adverse_aggressor_qty)
balance = 2 * min_side_qty / (favorable_aggressor_qty + adverse_aggressor_qty)
```

Fixed two-, five-, ten-, twenty-, and thirty-second checkpoints exclude roots
that had already structurally resolved. An adverse traversal is one traded tick
past the adverse band edge. A full reclaim trades one tick beyond the favorable
edge. After a four-tick favorable clearance and return to that edge, the support
test is a symmetric first passage: four ticks favorable is `READVANCED`; four
ticks through the favorable edge is `LOST_FAVORABLE_EDGE`.

The first implementation of the support test waited for price to cross the far
adverse edge of the whole band. That produced a false strong result because
wider bands both print more two-sided volume and mechanically provide more room
to readvance. The saved result uses only the corrected symmetric four-tick test.

### Continued Business At The Original Band

Early continued two-sided business is adverse evidence:

| checkpoint | no two-sided n / failure | two-sided n / failure |
|---:|---:|---:|
| 2 seconds | 480 / 57.3% | 12 / 91.7% |
| 5 seconds | 457 / 56.2% | 34 / 85.3% |
| 10 seconds | 422 / 55.2% | 64 / 75.0% |
| 20 seconds | 352 / 52.6% | 113 / 69.9% |
| 30 seconds | 319 / 49.8% | 127 / 69.3% |

At ten seconds the failure-rate difference is +19.8 points. A date-cluster
bootstrap gives +15.2 to +22.8 points. The ten-second effect remains in each
clock regime:

- 09:30-11:30: 84.2% failure with two-sided tape versus 62.1% without.
- 11:30-13:30: 79.2% versus 49.4%.
- 13:30-16:00: 61.9% versus 56.3%.

This supports the narrow statement that a conversion still conducting business
inside its original band has not escaped its contest. It does not prove that
all such roots should be suppressed; 16 of the 64 ten-second cases advanced.

### Adverse Traversal, Reclaim, And Edge Support

Before structural resolution:

- 128 roots never breached adversely; all advanced first.
- 19 breached and never re-entered; all failed first.
- 76 re-entered the band but did not fully reclaim; all failed first.
- 269 fully reclaimed at least once; 78 advanced and 191 later failed.

These path classes are mechanism diagnostics, not independent predictors. Root
failure itself requires adverse acceptance, while successor ownership requires
favorable progress.

The corrected favorable-edge support test has 239 resolved cases:

- 112 readvanced four ticks.
- 127 lost four ticks through the favorable edge.
- Two-sided reclaim transit readvanced 47.7%; zero-min-side transit readvanced
  44.4%.
- The date-cluster difference is -10.5 to +15.0 points.

Therefore tape-only "clean passage" versus "more two-sided passage" does not
qualify the reclaimed edge. A local readvance is useful but incomplete:
readvanced tests eventually advanced sponsorship 33.0% of the time versus
22.0% after favorable-edge loss. Most local readvances still belonged to roots
that failed later.

### The Book Claim Was Measured At The Wrong Phase

Of 349 complete prior escape-return book decisions, 338 occurred before any
adverse breach of the consumed band. That event is a return into EAR's 20-tick
execution envelope, not a repair/reclaim test of the ownership band. In this
no-breach stratum the old two-second owner-support gate improves advance rate
from 38.8% when rejected to 43.8% when accepted, but its date-cluster interval
is -8.6 to +17.4 points. Lifecycle stratification does not rescue it.

The existing 250 ms book states were then sampled causally at the actual
reclaimed favorable-edge test. Only 113 of 239 tests had a sample no more than
0.5 seconds old; stale states were not carried forward. In this phase:

| feature | AUC to local readvance | date-cluster 95% |
|---|---:|---:|
| 5s owner support net | 0.601 | 0.521 to 0.707 |
| 2s owner-under net | 0.637 | 0.524 to 0.727 |
| owner-under depth ratio | 0.622 | 0.521 to 0.694 |

Leave-one-date-out gates trained for 70% local readvance capture show:

| feature | local capture / edge-loss exposure | sponsor advance capture / failure exposure |
|---|---:|---:|
| 5s owner support net | 71.4% / 56.1% | 85.2% / 57.0% |
| 2s owner-under net | 69.6% / 50.9% | 70.4% / 57.0% |

The five-second owner-support sponsor-lineage selectivity is +28.2 points with
a date-cluster interval of +15.6 to +38.9 points. Every held-out date is
positive, but the sample is selected and small: 27 advancing and 86 failing
roots. It is not an initial-entry gate. It is the first defensible candidate
for a phase-specific hold, rearm, or promotion modifier after:

1. adverse traversal,
2. full favorable reclaim,
3. favorable clearance,
4. return to the reclaimed edge.

It remains insufficient alone. July 17 root 93 and July 24 root 63 both pass
the held-out five-second support gate and still fail structurally; root 63
readvances locally before failing later.

### Strict Failure And Later Re-establishment

After a strict root failure:

- Within 120 seconds, 162 of 286 price paths fully reclaim, but only 6 have a
  recorded favorable successor.
- Within 300 seconds, 202 fully reclaim and 38 have a favorable successor.

Call these repair-like re-establishments, not false failures. The original
sponsor failed and EAR's defensive exit can still be correct. Price reclaim
alone is common and is not equivalent to renewed sponsorship.

### Revised Research Direction

1. Keep the direct-conversion event and current failure semantics intact.
2. Do not use generic owner support at first 20-tick proximity as confirmation.
3. Treat early post-formation two-sided business inside the original band as
   unresolved-contest evidence.
4. Treat adverse traversal and full reclaim as a new phase; tape shape alone
   does not qualify its edge.
5. At the actual reclaimed-edge test, measure book underneath and owner support
   over a multi-second window. This is the strongest surviving execution lead.
6. Validate the phase-aligned five-second support gate on more sessions and on
   every eligible edge test with a dedicated replay before adding a shadow
   field or changing execution.

No EAR or LevelLedger runtime behavior changed.
