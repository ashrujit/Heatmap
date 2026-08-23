# Udit Heatmap LOB Research Pass - 2026-07-24

## Scope

This is a research note, not an implementation plan. The immediate goal is to
translate useful visual heatmap ideas into math we can test against prepared
7/23 and 7/24 episode labels before changing LevelLedger or EAR.

Udit source inspected from:

- `.tmp/Skurry-Panel-main-20260724`
- commit: `2435683f79a66d066c87d1a1225b8d423ace5538`

Prepared local dataset:

- `research/direct_conversion_execution/out/lob_episode_prep_20260723_20260724/manifest.json`
- `research/direct_conversion_execution/out/lob_episode_prep_20260723_20260724/human_labels_2026-07-23.md`
- `research/direct_conversion_execution/out/lob_episode_prep_20260723_20260724/human_labels_2026-07-24.md`

Dataset coverage:

- 2026-07-23: 20,919 snapshots, 978 transitions, 162 bands, 9 churn clusters,
  26 candidate rows.
- 2026-07-24: 20,554 snapshots, 1012 transitions, 184 bands, 12 churn clusters,
  40 candidate rows.

## Source Findings

### 1. Refill After Contact

Source:

- `.tmp/Skurry-Panel-main-20260724/Detection/L2/LevelRefillTracker.cs`
- `.tmp/Skurry-Panel-main-20260724/docs/tier-1-indicator/calibration/v0.31-l2-refill-tracker.md`

Udit tracks same-side passive adds inside the consumed price range after a sweep
or stop-run event. The output records first refill time, refill size in the
first 250 ms, total refill in 2 seconds, and refill divided by attack volume.

Translation for us:

- When price attacks a prior demand/supply claim, measure how much same-side
  book comes back in 250 ms and 2 seconds.
- Low refill after a level is consumed argues for continuation through that
  area.
- High refill after a level is consumed argues that the level may not be done
  yet, so market execution is more vulnerable to repair/churn.

Why this matters for EAR:

The user's phrase "LOB hasn't completely finished eating up what's offered" can
be made testable here. A claim can be locally correct but not actionable if
refill keeps reappearing inside or just beyond the attacked area.

Candidate metrics:

- `refill_250ms_same_side`
- `refill_2s_same_side`
- `refill_ratio_2s = refill_2s / max(attack_volume, 1)`
- `first_refill_ms`
- `refill_persistence_count` across repeated contacts in a rolling 30-120s
  window.

Episode tests:

- 7/23 H03/H04: around 10:25-10:40 and 28750, does the failed long / best short
  show low demand refill or strong ask refill after contact?
- 7/23 H08/H09: 28690 supply churned, then 28720 supply survived. Does the
  second supply have stronger same-side refill/reappearance?
- 7/24 H05/H06: valid deeper long repair versus 11:00 demand above 28440 false
  positive. Does false demand refill weakly or face immediate opposing refill?
- 7/24 H11: 13:05 VWAP sell with volume did not continue. Did bid/demand refill
  back into the consumed area quickly?

Falsifier:

If refill does not separate survived repairs from false positives on these
labels, it should remain a descriptive annotation, not an EAR gate.

### 2. Reload / Stack Defense

Source:

- `.tmp/Skurry-Panel-main-20260724/Detection/L2/ReloadZoneDetector.cs`
- `.tmp/Skurry-Panel-main-20260724/Detection/L2/LevelStackTracker.cs`
- `.tmp/Skurry-Panel-main-20260724/docs/tier-1-indicator/calibration/v0.20-reload-zones.md`

Udit's reload logic watches exact price levels where opposite-side aggression
hits the level, displayed size holds or grows, and price does not punch through
beyond a small tick tolerance. It treats replenishment as:

```text
replenishment = aggression + (size_end - size_start)
```

Only a defending replenishment sign fires. Neutral or retreating replenishment
rejects the level. Existing zones can later invalidate by decisive break, size
collapse, or regime flip.

Translation for us:

- A supply/demand claim should gain credibility when it repeatedly absorbs
  attack and replenishes while price fails to migrate through it.
- Re-establishment after repair can be measured as "same side defended again
  after a failed opposite repair," not as a new rail.
- Invalidation should care about whether the book is still defending, not only
  whether price crossed a static band.

Candidate metrics:

- `attack_volume_at_claim`
- `replenishment = attack_volume + delta_visible_size`
- `replenishment_sign = defending | neutral | retreating`
- `max_adverse_ticks_during_attack`
- `reload_event_count_5m`
- `reload_invalidated_reason = decisive_break | size_collapse | regime_flip`

Episode tests:

- 7/23 H03: did 28750-ish repair failure meet reload defense on the offer?
- 7/23 H09: did 28720-ish supply become the first clean surviving stack after
  28690 churn?
- 7/24 H10/H13: after 28560 failed, then 28540 failed, did supply re-establish
  as stacked/reloaded offers stepping down?
- 7/24 H11: if the VWAP sell failed to continue, did supply reload fail or did
  bid reload dominate the response?

Falsifier:

If reload fires frequently inside churn clusters without predicting survival
outside the cluster, it needs a churn/actionability gate before it can influence
execution.

### 3. Flow Field Purity And Churn Suppression

Source:

- `.tmp/Skurry-Panel-main-20260724/Heatmap/FlowLedger/FlowFieldEngine.cs`
- `.tmp/Skurry-Panel-main-20260724/Heatmap/FlowLedger/FlowLedgerEngine.cs`
- `.tmp/Skurry-Panel-main-20260724/Heatmap/Contracts/FlowLedgerOptions.cs`
- `.tmp/Skurry-Panel-main-20260724/docs/heatmap/levelLedger/03-pressure-field-equation.md`

The FlowLedger math is close to our LevelLedger world, but the useful idea is
the actionability hygiene: demand and supply fields decay, are spread spatially,
and only become structural when event support, purity, recency, and single-event
share pass gates.

Translation for us:

- Mixed fields should not be treated as "demand plus supply." They should often
  become "not actionable."
- Same-side nearby rows can merge; mixed-side evidence should define a churn
  boundary or unresolved interior.
- A row needs multiple events and recent one-sided purity before it can become
  something EAR trusts for fresh entry.

Candidate metrics:

- `demand_field`, `supply_field`, `net_field`
- `purity = abs(demand - supply) / max(demand + supply, eps)`
- `event_support = min(1, event_count / min_events)`
- `single_event_share`
- `latest_evidence_age_sec`
- `mixed_boundary_lo`, `mixed_boundary_hi`

Episode tests:

- 7/23 H02: churn before 10:25 should become non-actionable interior.
- 7/23 H10: 13:00-13:30 churn should suppress fresh entries.
- 7/24 H08: 11:15-11:50 VPOC formation should be no-entry despite active local
  ownership assertions.
- 7/24 H12: 13:10-13:35 forceful long repair inside afternoon churn should be
  separated from clean reversal evidence.

Falsifier:

If purity/support gates remove true survived claims more often than they remove
churn pollution, the gate is too blunt. Then keep it as a label for research,
not a live blocker.

### 4. Book Thinning As A Warning, Not A Directive

Source:

- `.tmp/Skurry-Panel-main-20260724/Detection/L2/BookThinningDetector.cs`
- `.tmp/Skurry-Panel-main-20260724/docs/tier-1-indicator/calibration/v0.29-book-thinning.md`

Udit measures top-N aggregate book size disappearing over a short window when
tape volume is too small to explain the drop. The detector already phase-gates
open/close and later added IB suppression because that period was anti-predictive
in his calibration.

Translation for us:

- Thinning can explain "open road" or lack of resistance, but it should not
  become a standalone short/long reason.
- In open/IB and contested periods, thinning probably means repositioning risk
  and should dampen chase entries.
- During a repair, thinning opposite the repair could make a market entry more
  acceptable if refill/reload also confirms.

Candidate metrics:

- `top_n_bid_drop_pct_5s`, `top_n_ask_drop_pct_5s`
- `tape_explained_ratio = tape_volume / max(book_size_drop, 1)`
- `thinning_side = bid_thinning | ask_thinning`
- `phase`
- `inside_distance_to_thin_area_ticks`

Episode tests:

- 7/24 H02: 09:50 downside drive was susceptible to repair. Was the sell drive
  mostly bid-side disappearance rather than real eating?
- 7/24 H03: repair to 28445 was a bad/unproven short. Did nearby book thinning
  warn that there was no stable seller claim?
- 7/24 H11: 13:05 VWAP sell did not continue. Was there thinning without
  follow-through refill/reload, which should become an avoid signal?

Falsifier:

If thinning merely marks every fast auction, it should only enter reports as
context. It should not alter EAR entry/hold logic.

### 5. Driver / Road / Brick / Horizon Split

Source:

- `.tmp/Skurry-Panel-main-20260724/Heatmap/NowLens/NowLensEngine.cs`
- `.tmp/Skurry-Panel-main-20260724/Heatmap/NowLens/DriverMeter.cs`
- `.tmp/Skurry-Panel-main-20260724/Heatmap/NowLens/TerrainMeter.cs`
- `.tmp/Skurry-Panel-main-20260724/Heatmap/NowLens/BrickContactTracker.cs`
- `.tmp/Skurry-Panel-main-20260724/Heatmap/NowLens/HorizonMeter.cs`
- `.tmp/Skurry-Panel-main-20260724/docs/heatmap/now-auction-lens/09-now-lens-implementation-spec.md`

Now Lens separates four questions that we currently tend to compress:

- Driver: who is pushing now, how hard, and how one-sided?
- Road: is near liquidity building, eroding, or vacuum?
- Brick: when a visible wall is attacked, did it hold, give, or pull?
- Horizon: what wall/air pocket sits ahead of the current move?

Translation for us:

- This split is probably more valuable than any single formula.
- EAR can use these as actionability annotations around LL ownership, not as
  primary rail discovery.
- A market entry should need a different combination than a wait/repair entry.

Candidate state split:

- `sponsor_state`: survived | failed | reloaded | invalidated
- `road_state`: building | eroding | vacuum | wall
- `driver_state`: aligned | divergent | strained | absent
- `horizon_state`: open | capped | nearby_opposition | no_read
- `actionability`: executable | wait_for_repair | hold_only | no_new_trade

Episode tests:

- 7/23 H03: likely executable short if sponsor_state=supply_reloaded and
  road/horizon support continuation.
- 7/24 H05: executable long repair if demand sponsor reloaded and road above was
  not capped too quickly.
- 7/24 H06: false positive if sponsor_state looked locally long but horizon or
  opposing reload capped it immediately.
- 7/24 H09: valid long but capped payoff; horizon should show nearby opposition.
- 7/24 H12: hold/avoid instead of fresh entry if the driver was forceful but
  actionability remained mixed.

Falsifier:

If actionability states only restate what price already did, they are too late.
The useful version needs to differ before or during the trigger candle.

### 6. Effort / Progress Mismatch

Source:

- `.tmp/Skurry-Panel-main-20260724/HeatmapV2/Engine/EffortMeter.cs`
- `.tmp/Skurry-Panel-main-20260724/docs/heatmap-v2/03-driver-v2-and-math-foundations.md`

Udit's V2 meter separates effort rank from price progress rank:

```text
strain = effort_rank * (1 - progress_rank)
slide  = progress_rank * (1 - effort_rank)
```

Translation for us:

- High effort with poor progress is a churn/repair warning.
- Progress with light effort can be open-road continuation, but only if refill
  and horizon do not contradict it.
- This can help distinguish "market execute now" from "wait for repair / do not
  chase."

Episode tests:

- 7/24 H02: downside drive susceptible to repair should show strain or weak
  progress quality.
- 7/24 H11: high-volume VWAP test that did not continue should show sell strain.
- 7/24 H13: renewed selling after 13:35 should show better progress/slide or
  reduced opposing refill versus the 13:05 attempt.

Falsifier:

If strain only appears after reversal has already happened, it is diagnostic but
not execution-useful.

### 7. Scale Robustness

Source:

- `.tmp/Skurry-Panel-main-20260724/HeatmapV2/Rendering/V2TerrainSaturationLaw.cs`
- `.tmp/Skurry-Panel-main-20260724/docs/heatmap-v2/06-terrain-saturation-law.md`

This is display-oriented, but the math warning applies to research: one huge
wall or heavy-tailed side should not make all surrounding book look meaningless.
Udit addressed this visually with body-anchored/log scaling.

Translation for us:

- For research metrics, avoid raw p99-only scaling that suppresses the body of
  the book.
- Use per-side scales.
- Consider body-anchored p90/p95 caps or log transforms for refill/reload
  magnitude before comparing sessions.

Falsifier:

If body-anchored scaling creates false importance for normal low-lot churn, keep
it for visualization only.

## First Research Buckets

### Positive / Executable Candidates

- 7/23 H03: failed repair long / best short trigger around 28750 after 10:25.
- 7/23 H09: higher 28720-ish supply survived after 28690 churn failed.
- 7/24 H05: deeper long repair after low break / node build, before the 11:00
  false-positive area.
- 7/24 H09: reissued long after VPOC formed, but mark as capped payoff.
- 7/24 H09 trade-log overlay: 11:50 long entered/held around 515-524ish and
  exited at 11:53; later continuation ran 556 to 600, added/leverage near 623,
  exited 614. Treat this as a campaign-continuity / premature-exit candidate,
  not only an entry candidate.
- 7/24 H13: supply re-establishment after 28540 failed and 28460s broke again.

### Negative / False-Positive Candidates

- 7/23 H04: false long sponsorship near the 28750 failure.
- 7/23 H08: 28690-ish supply claim churned instead of surviving.
- 7/24 H03: repair to 28445 was a bad or unproven short.
- 7/24 H04A: 10:21:10 conversion short exited at 10:21:24 around 354-365; test
  whether repair-risk/churn/low-node formation could have filtered it.
- 7/24 H06: 11:00 demand above 28440 false positive.
- 7/24 H11: 13:05 high-volume VWAP sell did not continue.

### Avoid / Churn Candidates

- 7/23 H02: pre-10:25 messy churn.
- 7/23 H07: VWAP/28630 repair churn before up resolution.
- 7/23 H10: 13:00-13:30 churn.
- 7/24 H08: 11:15-11:50 VPOC formation churn.
- 7/24 H12: 13:10-13:35 forceful long repair inside afternoon churn.

## Added Execution Questions

These are trade-log overlays supplied by the user after the first pass. They
are not yet verified against directive/status/events logs.

### 10:55-11:15 No Long Attempt

The user may have had a long directive active during the first two long windows,
but the corrected recollection is that no long attempt appeared in trade logs
until 11:50. This changes the research question:

- Was no directive actually active?
- Was a directive active but EAR found no eligible trigger?
- Did LL/EAR require a retest or confirmation that never arrived?
- Did protection, blocker, TTL, position state, or account state suppress an
  otherwise valid attempt?

The raw book work alone cannot answer this. The feature pass needs an EAR
directive/status/trade-attempt overlay for the 10:45-11:15 window.

### 11:50 Long Exit Versus Campaign Continuity

User reports:

- 11:50 long entered/held around 515-524ish.
- Exited at 11:53.
- Later continuation long from 556 to 600.
- Added/leverage near 623.
- Exit near 614.

Hypothesis: the 11:50 exit may have been too local. If VPOC churn had finished
and the long campaign was valid, then the first 11:50 leg should perhaps have
remained alive into the later 556 -> 623 campaign unless supply reload or
explicit sponsor invalidation appeared.

Research target:

- Separate "entry was right" from "campaign should still be active."
- Test whether H09 had sufficient demand reload/refill and clean-enough
  actionability after 11:53 to continue holding.
- Test whether the supply above 28600 was a cap for scaling/exiting, not an
  early exit reason at 11:53.

### 10:21 Conversion Short

User reports a conversion short at 10:21:10 that exited at 10:21:24 around
354-365. The question is whether it could have been avoided.

Research target:

- Was the short trying to convert the 10:05-10:20 repair/VPOC area back down?
- Was the lower-node branch already developing enough that short continuation
  had poor expectancy?
- Did refill/reload, thinning, or effort/progress mismatch show repair risk
  before the entry?
- Did the setup have enough horizon/payoff before running into bid/demand
  rebuilding?

## Proposed Feature Pass

Run the next extraction pass on raw MarketRecorder book events and trades, not
only LL synthetic bands:

1. Build per-price, per-side L2 event primitives:
   - bid add, bid remove, ask add, ask remove
   - trade-at-bid, trade-at-ask
   - crossed-book repair remove legs, if observable from snapshots

2. Attach episode-relative metrics:
   - same-side refill 250 ms and 2 s after attack/contact
   - reload defense windows at candidate claim prices
   - top-N thinning within 5 s and 15 s
   - FlowLedger-style purity/support/recency/single-event-share
   - effort/progress/strain/slide around trigger candles
   - horizon walls/gaps within 10-40 ticks in the continuation direction
   - EAR directive/status/trade-attempt overlay for 10:21, 10:45-11:15, and
     11:50-12:05

3. Score each human-labeled episode separately:
   - executable
   - false positive
   - avoid/churn
   - capped payoff
   - premature exit / campaign continuity

4. Do not pool churn and executable cases in one outcome table. Pooling them is
   exactly how VPOC/HVN formation can pollute the conclusion.

## Early LL / EAR Design Implication

The likely improvement is not new rails. The likely improvement is an
actionability layer around existing ownership:

```text
ownership claim + refill/reload confirms + clean enough road/horizon = executable
ownership claim + mixed purity/churn or opposing reload nearby = hold only or wait
ownership claim + high strain / poor progress = avoid market chase
ownership failure + low refill + open road = continuation allowed
```

This should be tested as research first. If the labels separate, EAR can later
use the result as a market-entry dampener or repair-wait state, while
LevelLedger can expose it as ownership quality/actionability rather than as a
new rail definition.

## Running Episode Findings

The first execution/LOB probe pass is recorded separately in
`research/direct_conversion_execution/notes/EPISODE_EXEC_LOB_FINDINGS_2026-07-24.md`.

Current high-value threads:

- 10:21 conversion short: exact raw book replay suggests the sponsor failed
  through first-contact churn inside an upward repair, not that the pattern was
  categorically invalid.
- 10:57-11:15 long: directive was active but no base entry formed; next pass
  should audit no-entry blockers minute by minute.
- 11:50 long: sponsor promotion from parent demand id 84 to child id 86 caused
  the 11:53 exit; campaign then resumed under the same directive. This is the
  strongest sponsor-promotion research case so far.
- 12:15-12:30 long: looks like repair after the 12:11 long-campaign failure,
  not clean fresh buying; promotion/add rules probably need stronger proof in
  that state.
