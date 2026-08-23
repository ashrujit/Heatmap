# Phase Contact Response Revisit - 2026-08-21

Research note only. No EAR or LevelLedger runtime change is implied.

## Question

The old contact-response work measured dwell, attack volume, same-side depth
change, reload/replenishment, and future movement around EAR/LL-style favorable
anchors. It found real signal in some passes, but not enough to conclude. The
main suspected flaw was population mixing: IB initiative, post-lunch value/VPOC
formation, responsive range traversal, and late-day repair were pooled as if the
same L2 behavior meant the same thing in every auction phase.

The current question is phase-aware:

- In IB / just-post-IB initiative, does same-side depth falling after contact
  mean sponsor failure, or can it mean price is accepting away and those prices
  are no longer available?
- In lunch/range traversal, does temporary same-side build at worse prices mark
  real continuation, or a small trapped distribution that collapses when takers
  step back?
- Is Richard's "separate adds with low interaction between them" advice a proxy
  for auction migration: low interaction between root and child means the child
  may be a new accepted price, while immediate p/balance formation means it is
  still the same range auction?

## Prior Work Reused

Relevant prior artifacts:

- `ExecAssistantRuntime/research/ear_contact_response_probe.py`
- `research/EAR_CONTACT_RESPONSE_2026-06-23_2026-06-24_2026-06-25.md`
- `research/EAR_CONTACT_RESPONSE_2026-08-04_2026-08-13.md`
- `research/BAND_LIFECYCLE_EPISODE_TAXONOMY_2026-06-27.md`
- `research/direct_conversion_execution/notes/CONVERSION_PROVISION_2026-07-25.md`
- `research/direct_conversion_execution/notes/DIRECT_CONVERSION_SPONSOR_LINEAGE_2026-07-25.md`

Important old findings:

- The June 23-25 NQ raw-book pass had strong in-sample signal for held/reload
  metrics: `held_ratio_5s` AUC `0.822`, `reload_ratio_5s` AUC `0.800`,
  `same_net_5s` AUC `0.825` across full RTH pooled sessions.
- The Aug 4/13 ES early-window pass did not replicate that cleanly. Several
  reload/depth metrics inverted or weakened, while future movement remained more
  informative than the depth/reload metric itself.
- The conversion-provision work found that real magnitude matters. In thin VPOC
  churn, ratios can look meaningful but predict little because nobody was truly
  overwhelmed. In thicker engagement, whether the losing side returns after the
  break matters much more.
- The direct-conversion sponsor-lineage note already warned that static depth is
  not enough; role, accepted-value position, field cleanliness, and phase of the
  return change the meaning of the same book action.

## New Scripts And Outputs

New helper:

- `research/phase_contact_response_summary.py`

It post-processes the contact-response CSV by timestamp windows because
`ear_contact_response_probe.py` labels rows only by `date:symbol`, so its
markdown report duplicates the same session summary when two windows on the same
symbol/date are passed together. The CSV timestamps are valid; the phase summary
uses `anchor_ts`.

Generated outputs:

- NQ snapshot/tape pass:
  `research/out/ear_contact_response_phase_revisit_nq_2026-08-21/`
- NQ raw `book_events` pass:
  `research/out/ear_contact_response_phase_revisit_nq_2026-08-21_book/`
- ES snapshot/tape pass:
  `research/out/ear_contact_response_phase_revisit_es_2026-08-21/`

NQ raw-book command:

```powershell
uv run --with polars --with numpy --with tzdata python ExecAssistantRuntime\research\ear_contact_response_probe.py --book-events --session 2026-08-21:NQU6:10:20-12:00 --session 2026-08-21:NQU6:12:00-13:30 --warmup-min 60 --fail-confirm-ticks 8 --fail-sec 10 --out-dir research/out/ear_contact_response_phase_revisit_nq_2026-08-21_book
```

NQ raw-book health from generated report:

- `book_files=1610`
- `book_rows=24936773`
- `book_gaps=0`
- `crossed_repairs=633`
- `snapshot_gaps=1`

## NQ Phase Split - Raw Book Events

Source: `research/out/ear_contact_response_phase_revisit_nq_2026-08-21_book/phase_summary.md`.

### IB / Reversal Campaign: 10:20-12:00

Resolved clean anchors: `34/99` confirmed, `34.3%`.

Key rows:

- `same_depth_change_5s < 0`: `25/63`, `39.7%`
- `same_depth_change_5s >= 0`: `9/36`, `25.0%`
- `same_depth_change_5s` low p25 `-14`: `14/26`, `53.8%`
- `same_depth_change_5s` high p75 `1`: `8/28`, `28.6%`
- `reload_ratio_5s` low p25 `-6.5`: `18/25`, `72.0%`
- `reload_ratio_5s` high p75 `1`: `8/30`, `26.7%`
- `attack_vol_5s` high p75 `1`: `0/28`, `0.0%`
- `future_30s_ticks` AUC `0.701`

Read: in this NQ IB/reversal window, falling same-side depth or negative reload
did not mean the anchor was failing. It was associated with better confirmation.
That fits the idea that in initiative/reversal through references, the auction
can confirm by making the prior same-side price unavailable rather than by
restacking visibly at that same price. A visible high-attack/high-reload bucket
looked bad here, possibly because it marked churn at the contacted area rather
than clean migration.

### Lunch / Range Traversal: 12:00-13:30

Resolved clean anchors: `12/47` confirmed, `25.5%`.

Key rows:

- `same_depth_change_5s < 0`: `6/29`, `20.7%`
- `same_depth_change_5s >= 0`: `6/18`, `33.3%`
- `same_depth_change_5s` low p25 `-9`: `3/12`, `25.0%`
- `same_depth_change_5s` high p75 `3`: `6/12`, `50.0%`
- `held_ratio_5s` high p75 `1.065`: `6/12`, `50.0%`
- `future_30s_ticks` AUC `0.779`

Read: NQ lunch moved closer to the intuitive warning. When same-side depth fell,
confirmation was weaker; when the contacted area held/restacked, confirmation
improved. That matches the range-failure scalp observation: the first entry can
be immediately onside, but continuation beyond the next pocket needs fresh
acceptance. If takers step back and no one maintains/provisions the new worse
price, the auction rotates back into the prior range.

## ES Lightweight Comparison

Source: `research/out/ear_contact_response_phase_revisit_es_2026-08-21/phase_summary.md`.

This pass used snapshot/tape metrics, not raw `book_events`.

### ES 10:20-12:00

Resolved clean anchors: `17/46`, `37.0%`.

- `same_depth_change_5s < 0`: `12/36`, `33.3%`
- `same_depth_change_5s >= 0`: `5/10`, `50.0%`
- `future_30s_ticks` AUC `0.709`

### ES 12:00-13:30

Resolved clean anchors: `11/37`, `29.7%`.

- `same_depth_change_5s < 0`: `9/23`, `39.1%`
- `same_depth_change_5s >= 0`: `2/14`, `14.3%`
- `future_30s_ticks` AUC `0.902`

Read: ES does not simply reproduce the NQ split. The samples are smaller and
only snapshot-backed. It may be product-specific, or it may reflect that ES was
already a cleaner campaign / different profile field. Do not average this with
NQ and call it a universal depth rule.

## Current Interpretation

The phase-aware replay supports revisiting the old dwell/depth thesis, but not
as a standalone sponsor-quality rule.

The likely causal object is not "same-side depth fell" or "same-side depth
restacked." It is:

1. phase and role: base, add, tactical child, campaign sponsor, lunch scalp;
2. whether price made old prices unavailable after the event;
3. whether low-interaction space separated root and child;
4. whether a counter pocket produced trapped balance/p-shape rather than
   migrated acceptance;
5. whether the same-side book response happened under existing campaign
   authority or inside unresolved two-sided churn.

This makes Richard's advice more concrete: low interaction between adds may be
valuable because it says the market skipped/accepted through a low-volume road
and is now advertising a new best available price. Immediate two-sided
interaction between the add and its parent can mean the add is still inside the
same unresolved distribution, so sponsor promotion is fragile.

## Provisional Research Labels

Use these labels in the next dataset rather than adding EAR modes:

- `initiative_migration`: price leaves root, low interaction between root and
  child, old prices mostly unavailable, next same-side anchor forms beyond.
- `range_traversal_child`: price gets onside quickly, reaches a counter pocket,
  then forms balance/p-shape with poor follow-through.
- `temporary_worse_price_offer`: same-side build appears beyond sponsor, but
  takers step back and the prior average/best price becomes available again.
- `repair_base`: first repair after directional thesis, where sponsor quality is
  judged by denial of old prices and counter-side failure.
- `campaign_child`: add object whose failure should not automatically kill the
  older campaign sponsor.

## Corrected Phase Boundary - 2026-08-21 10:55-11:20

The `11:40-12:05` check below describes normal terminal behavior for the second
leg. The more important leverage-management question is the first leg's stall
around 11:00, where phase 1 ended and the repair / phase-2 setup began.

NQ had the cleaner early stall signature.

- Skurry absorption flagged `11:00` buying absorbed by limit sellers near
  `29344.75`, then `11:04` two-sided absorption near `29359.75`.
- LevelLedger showed counter supply `29346.00-29348.50` owned at `11:01:45`,
  held tests at `11:02:40` and `11:02:54`, then failed at `11:03:39`. That is
  not a reversal, but it is the first counter claim that did not instantly
  vanish during the buy leg.
- A second upper supply object `29358.00-29362.50` owned at `11:05:29`, held at
  `11:06:42`, and failed at `11:07:20`. Then the same-side demand child
  `29360.75-29361.75` failed at `11:09:03`.
- The `10:55-11:05` profile was double-distribution with positive delta
  `+552`, POC `29364.00`, and weak high excess. The `11:05-11:20` profile kept
  POC at `29360.00` but flipped to delta `-761`, a `p` shape, and lower value
  `29348.00-29362.50`.

Read: NQ's 11:00 stall was an exit/trim signal for leverage, not a thesis
failure. The older base near `29331.75-29332.25` was still alive and held the
first repair at `11:01:59`; what became fragile was the child inventory created
at or after the first objective.

ES had the same idea, but delayed and less binary.

- The `10:55-11:05` profile had strong positive delta `+2019`, double
  distribution, POC `7693.75`, and a poor high. It said objective/top business
  was unfinished, not that the campaign had failed.
- The `11:05-11:20` profile kept POC at `7693.75` but flipped to delta `-2806`
  while value stayed high, `7691.25-7696.75`.
- LevelLedger demand `7691.75-7694.50` owned at `11:03:49` and only failed at
  `11:19:39`; broader demand `7690.25-7696.50` was still tested/active.
- Counter supply `7696.25-7698.75` owned at `11:09:38` and held at `11:13:24`.
  That is the cleaner ES leverage-trim clue, especially for adds taken after
  open / IB high / ETH POC extension.

Research label: `leveraged_phase_stall`.

Candidate fields:

- `first_objective_reached`
- `counter_claim_held_during_drive`
- `absorption_or_two_sided_compression_at_extreme`
- `delta_flip_without_new_value_extension`
- `child_old_price_reopened`
- `older_campaign_sponsor_alive`

Use: reduce or pay tactical leverage when the current phase stalls at an
objective, while preserving the older campaign core if its base remains alive.
Do not treat this as automatic reverse permission.

## Focused Repair-Start Check - 2026-08-21 11:40-12:05

Question: when a pre-lunch drive trades away from a fought range, does repair
start only after the extreme shows more than a wick? The useful signatures are:
counter ownership appears at the drive extreme and refuses to give up after
pokes, or same-side extreme sponsorship fails/re-establishes but price no
longer has urgency beyond it.

NQ showed both signatures cleanly.

- Early counter supply failed while the buy drive was still live:
  `29446.75-29447.50` failed at `11:46:31`, `29441.75-29445.25` at
  `11:50:19`, `29450.75-29452.50` at `11:50:38`, `29464.25-29465.00` at
  `11:51:45`, and `29467.50-29468.50` at `11:51:49`.
- Then supply stopped failing and started owning the extreme: `29478.75-29484.25`
  owned at `11:54:52`, `29472.25-29474.75` at `11:55:25`, `29457.50-29458.25`
  at `11:57:12`, `29449.75-29452.25` at `11:57:59`, and `29440.25-29446.00`
  held a `12:02:06` test by `12:02:14`.
- Same-side demand failed top-down after the high: `29474.00-29474.25` failed
  at `11:54:50`, `29468.00-29470.50` at `11:55:22`, `29463.00-29464.75` at
  `11:55:31`, `29458.00-29458.25` at `11:56:46`, `29452.50-29453.75` at
  `11:57:03`, `29448.25-29449.25` at `11:57:48`, and lower demand near
  `29428-29432` failed at `12:04:44-12:04:45`.
- Skurry 11:40-12:05 profile was double-distribution, delta `-1436`, value
  `29437.25-29471.25`, POC `29445.25`, with strong high excess. New upper
  prices were not accepted; value was forming back underneath.

Read: NQ's current buy phase ended around `11:54-11:58`, with confirmation by
`12:04`. This was not a wick-only exit. It was thin-build / extreme-sponsor
failure plus counter ownership.

ES was later and less clean.

- Counter supply at `7708.25-7709.25` owned at `11:48:53` but failed by
  `11:51:54`, which still matched a live buy drive.
- Demand `7705.50-7708.50` consumed at `11:51:57` and failed only at
  `12:02:25`; broader demand `7700.50-7709.50` / `7701.50-7709.50` remained
  active through the window.
- Supply appeared at `7706.75-7712.25` at `12:02:25` and `7704.75-7713.25` at
  `12:04:55`, but Skurry profile was a normal high-volume balance around POC
  `7707.50`, value `7705.00-7710.00`, and nearly neutral delta `-85`.

Read: ES was showing high-area balance / repair beginning by `12:02`, not the
same clean top/phase failure that NQ printed. Treat this detector as
`stop adding / trim tactical child / retire initiative`, not as automatic
reverse permission.

## Next Pass

Research objective: stop asking whether a band/sponsor is intrinsically good.
Ask what phase produced it and what should happen next.

### Stall Outcome Split

Primary question:

- `temporary_stall_continuation`: counter claim appears at the drive/objective
  edge, but fails quickly; old prices remain mostly unavailable; the next
  same-side anchor forms at a worse price; price resumes in the favorable
  direction without meaningful dwell back inside the prior child.
- `stall_to_repair`: counter claim survives pokes or re-establishes; same-side
  urgency fades; prior prices reopen; value/dwell starts forming behind the
  child; the older campaign base may remain alive, but leveraged child inventory
  should be paid or reduced.

Outcome labels should be applied to stall events, not just sponsor events.
Measure max favorable excursion, max adverse excursion, old-price dwell,
time-to-next-same-side-anchor, counter-claim survival, and whether the older
campaign sponsor survived the repair.

### Fast Child / Root Distance Split

Secondary question:

- Are `20-40+` tick root-distance adds usually born in thin, newly auctioned
  areas after the first objective?
- If yes, do they still have value as tactical participation once a
  stall/repair pattern is known, or should they be suppressed until a
  repair-confirmed sponsor appears?

Working hypothesis: do not classify these as good/bad sponsors. Classify them
as `fast_child_after_objective`. They can be paid like tactical inventory if
continuation resumes quickly, but they should not replace the older campaign
anchor unless post-event acceptance appears: old prices stay unavailable, a new
same-side anchor forms at worse prices, or the child survives a repair.
1. Add explicit phase tags to the contact-response population: IB initiative,
   post-IB continuation, lunch/range traversal, late responsive repair.
2. Add low-interaction metrics between parent/root and child: volume, dwell,
   number of bid x ask trades, profile density, and whether a p/balance forms at
   the child.
3. Combine with `sponsor_consequence_probe.py`: old-price dwell, first old-price
   reopen, same-side restack after touch, and next same-side sponsor delay.
4. Run more days before designing anything. One day shows the right direction of
   the question, not a rule.

## Implementation Boundary

Do not create a `scalp only` button or sponsor gate from this note. The current
value is research framing: phase separation and post-event consequence should be
measured before any dispatcher/EAR shape is discussed.
