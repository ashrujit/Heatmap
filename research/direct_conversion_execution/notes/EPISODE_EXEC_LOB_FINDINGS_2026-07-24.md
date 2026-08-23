# 2026-07-24 EAR / LL / LOB Episode Findings

Research-only running note. Keep EAR runtime evidence separate from
MarketRecorder market evidence:

- EAR authority: `C:\Users\j\Documents\ExecAssistantRuntime\events.jsonl`
- Market evidence: `C:\Quantower\Settings\Scripts\Indicators\MarketRecorder\captures\NQU6\2026-07-24`
- Probe script: `research/direct_conversion_execution/scripts/episode_exec_lob_probe.py`
- Broad LL candidate prep script: `research/direct_conversion_execution/scripts/prepare_lob_episode_dataset.py`
- Probe outputs: `research/direct_conversion_execution/out/episode_exec_lob_probe_20260724/`

The base pass uses MarketRecorder ticks plus 1 Hz book snapshots around exact
EAR anchors. A raw quote-id replay was also run for the narrow 10:18-10:24
window:

- Raw E1021 output: `research/direct_conversion_execution/out/episode_exec_lob_probe_20260724_raw_E1021/`
- Raw replay health for E1021: 1740 files, 1 carry day, 25,249,301 rows
  processed, 2 resets, no gaps.

The raw pass did write a complete E1021 report, but the shell command still hit
the five-minute timeout. The reason is structural: the only full book reset
before these windows is at 09:13, so exact quote-id replay must process millions
of deltas before the first anchor. Next script improvement is a checkpointed
replay cache before extending raw replay to later windows.

## Episode Register

These are the current curated 7/24 windows in `episode_exec_lob_probe.py`:

- `E1021`: 10:18-10:24, 28345-28370, supply, 10:21 conversion short.
- `E1055`: 10:45-11:15, 28270-28480, demand, active long directive but no attempt.
- `E1115`: 11:15-11:50, 28470-28540, VPOC/HVN churn stand-aside.
- `E1150`: 11:48-12:05, 28500-28630, demand, 11:50 long exit vs same campaign.
- `E1215`: 12:10-12:35, 28525-28630, demand, repair versus fresh buying.

## E1021 - Conversion Short Maybe Avoidable

Question: could the 10:21:10 short conversion around 28354-28365 have been
avoided?

EAR facts:

- 10:16:05 short directive accepted, target 28217.75, order range 28306.25-28453.75.
- 10:21:10.746 `EnterBase Short` qty 2, reason `direct_conversion_retest`, root/support id 34, band 28356.75-28358.50.
- Fills: 28354.50 and 28354.25.
- 10:21:10.988 sponsor promoted Supply id 34, same band, reason `filled_entry`.
- 10:21:24.023 flattened qty 2, reason `sponsor_failed:34`.
- Exit fill: Long 2 at 28365.

Raw book/tape read around the exact sponsor:

- At submit/promote, same-side ask depth in the sponsor band was 19, then 20 by
  +2s, 0 by +5s, 0 by +10s.
- At the first `RailTested` event 10:21:13.744, same-side depth was only 1,
  then 0 by +2s, 22 by +5s, and 0 by +10s.
- The first-test raw replay shows churn/reload, not clean absorption:
  same-side add/remove over +2s was 107/108 and opposite add/remove was 101/91.
- The six-minute window was not weak to the upside: O 28345.25, H 28423.50,
  L 28299.00, C 28419.00, volume 10384, delta +326.

Current read:

This was a valid EAR direct-conversion entry, but the raw book signature was
fragile: the sponsor did not disappear instantly, but it failed to stay stable
through first contact. The more precise avoid concept is not "sponsor appeared
from zero"; it is "direct conversion sponsor shows high two-sided churn and
cannot maintain same-side depth after first test while the broader tape is
repairing hard against the trade."

Falsifier to test later:

- Find a profitable conversion that also starts with zero same-side depth and
  early depletion. If those exist, the filter needs auction-context gating, not
  a hard book threshold.

## E1055 - Long Directive Active, No Attempt

Question: was there a long entry from 10:45-11:15, especially 10:55-11:05 or
11:05-11:15?

EAR facts:

- 10:57:02.391 long directive accepted, target 28650.50, order range
  28274.75-28436.50.
- No `order_submit` occurred between directive acceptance and 11:15.
- That directive was later canceled at 11:18:48 with base attempts = 0.

Market read:

- 10:45-11:15: O 28287.00, H 28510.00, L 28254.50, C 28493.25, range 255.50,
  volume 49128, delta +1352.
- Book snapshot top20: bid 85 -> 93, ask 54 -> 28.
- EAR emitted 185 evidence transitions in this window, showing plenty of state
  churn rather than a quiet absence of evidence.

Current read:

This confirms the corrected memory: the long directive was active, but EAR never
found a qualifying base trigger. The research question should narrow to "why did
LL/EAR evidence not form a supported reclaim/direct conversion after 10:57?"
rather than "was the directive active?"

Possible direction:

- Build a no-entry audit table for active directives: for each minute, show best
  candidate side, candidate state, blocker/failure parent invalidations, and
  distance from order range. This can tell whether the no-entry was price-range,
  parent invalidation, churn, or missing pattern formation.

## E1115 - VPOC / HVN Churn Stand-Aside

Question: could the 11:15-11:45 churn/VPOC formation have been automatically
recognized even though bands still formed?

EAR facts:

- 11:18:49 long directive accepted.
- 11:19:37 `entry_paused`, directive `2026-07-24-directive-long-111849-0bcb72`.
- 11:23:33 long directive accepted.
- 11:30:07 and 11:33:00 `entry_paused`, directive
  `2026-07-24-directive-long-112333-9fa1f8`.
- 11:48:51 new long directive accepted, which later entered at 11:50.

Market read:

- 11:15-11:50: O 28494.25, H 28577.50, L 28453.50, C 28503.25, range 124.00,
  volume 43329, delta +1047.
- Snapshot top20: bid 55 -> 57, ask 55 -> 77.
- Focus range 28470-28540: bid 87 -> 93, ask 77 -> 120.

Current read:

EAR already had one expression of "stand aside" here through flat-entry pauses,
but the mechanism is not yet an explicit HVN/churn detector. The interesting
research feature is a two-sided churn score around candidate bands: repeated
same-area evidence transitions, both sides increasing visible depth, and little
net directional displacement from the developing high-volume node.

Possible direction:

- Add a research-only churn classifier to the script: within a price band or
  20-50 point envelope, count demand owned/held/failed and supply owned/held/
  failed transitions, plus net price displacement and local volume concentration.
  This should produce buckets: contested/HVN, repair-inside-churn, survived edge.

## E1150 - 11:50 Long Was Same Campaign, Exit Looks Too Sensitive

Question: should the 11:50 long have remained part of the campaign toward 623
instead of exiting at 11:53?

EAR facts:

- 11:48:51 long directive accepted, target 28820.
- 11:50:22.158 `EnterBase Long` qty 2, reason `direct_conversion_retest`,
  root/support id 84, band 28502.75-28511.75.
- 11:50:22.675 sponsor promoted Demand id 84, reason `filled_entry`.
- 11:50:59.167 sponsor promoted Demand id 86, prior sponsor 84, reason
  `accepted_same_side_ownership`, band 28532.50-28534.00.
- 11:53:01.317 sponsor id 86 failed; EAR flattened.
- 11:55:43.160 the same directive re-entered long at id 89 around
  28549.25-28551.75.
- 12:07:32 and 12:10:42 later adds carried the same directive into leverage
  before the 12:11 failure.

Snapshot/tape read:

- Parent sponsor 84: same-side depth 28 at entry, 21 by +2s, 28 by +5s, 0 by
  +10s. There was no immediate opposite attack at the band.
- Child sponsor 86: same-side depth 18 at promotion, still 18 by +2s, 0 by +5s,
  17 by +10s, then failed at 11:53.
- 11:50 one-minute bar drove 28503.25 -> 28539.50 with +172 delta.
- 11:51 and 11:52 pulled back but did not erase the parent entry band.
- 11:55 re-entry and later leverage show the original long idea was not dead.

Current read:

This is the cleanest finding so far. The premature exit was caused by sponsor
promotion from parent demand id 84 to child demand id 86. The child failed, but
the larger campaign repaired and continued. This does not argue for looser
stops everywhere; it argues for a stricter sponsor-promotion rule inside recent
HVN/churn: a new same-side sponsor should not replace the parent unless it has
both durable reload and favorable displacement beyond the churn envelope.

Potential rule shape:

- In a churn/HVN state, keep the original causal sponsor unless the promoted
  sponsor survives first contact and price accepts beyond the churn boundary.
- Or separate "protective sponsor" from "campaign sponsor": child failures can
  trim or de-leverage, while parent survival keeps campaign state alive.

Falsifier to test later:

- Find a losing long where holding parent id 84-style protection would have made
  the loss meaningfully worse. If common, promotion cannot be simply delayed.

## E1215 - Repair, Not Clean Fresh Buying

Question: could 12:15-12:30 indicate this was repair of a selling leg rather
than a fresh buying attempt?

EAR facts:

- The prior 11:48 long campaign failed at 12:11 after add/sponsor id 103 failed.
- 12:11:46 long reissue accepted.
- 12:14:42 entry paused.
- 12:15:49 new long directive accepted.
- 12:18:22 `EnterBase Long`, reason `supported_reclaim_confirmed`, root supply
  id 111 at 28561.50-28562.75, support demand id 95 at 28559.50-28563.50.
- 12:20:42 sponsor promoted from id 95 to demand id 115 at 28567.25-28569.75.
- 12:21:18 add long against id 115.
- 12:30:03 id 115 failed and EAR flattened.
- 12:30:20 another long directive was accepted; 12:32:20 entered and failed in
  17 seconds, reinforcing the churn/repair-trap read.

Snapshot/tape read:

- 12:10-12:35: O 28603.50, H 28630.75, L 28527.00, C 28542.25, range 103.75,
  volume 21387, delta +365.
- Top20 book: bid 92 -> 73, ask 89 -> 68.
- Focus 28525-28630: bid 139 -> 112, ask 125 -> 126.
- 12:18 entry sponsor id 95: same-side depth 45 at entry, 30 by +2s, 20 by +5s,
  12 by +10s.
- 12:20 child sponsor id 115 started with zero visible same-side depth in the
  1 Hz snapshot metric; the 12:21 add showed reload under attack, but id 115
  still failed at 12:30.
- 12:30 one-minute bar expanded down hard: 28566.00 -> 28539.00, low 28527.50,
  volume 2458, delta -316.

Current read:

This was repair and churn after the prior long campaign had already failed, not
a clean fresh-buying campaign. The 12:18 entry was coherent as a supported
reclaim, but the surrounding state should probably be tagged as "repair against
recent supply / uncertain" until buyers prove acceptance above the failed 560s
area and the child demand sponsor survives.

Potential rule shape:

- After a leveraged same-side campaign fails, treat the next same-side directive
  as repair unless it establishes above the failed sponsor/churn boundary.
- In repair state, require stronger child-sponsor promotion evidence before add
  or before allowing the promoted child to become the sole flatten sponsor.

## Cross-Episode Hypotheses

1. Sponsor promotion is the first high-value research target.
   The 11:50 and 12:18/12:20 sequences both show a parent demand sponsor that
   produced a real campaign, followed by a newer child sponsor that became the
   flatten authority. This can cut too early inside churn/repair.

2. Churn should be state, not just absence of trade.
   11:15-11:50 had many evidence transitions and EAR pauses. A useful automatic
   detector should score contested ownership around the band/envelope, not only
   wait for no signals.

3. Conversion entries need first-contact book quality.
   The 10:21 short was not a bad pattern by definition, but its sponsor appeared
   fragile on immediate book contact while the tape was repairing hard upward.

4. Post-failure same-side reissues should be treated differently.
   The 12:15 long came after a leveraged long campaign failed at 12:11. That
   context matters: it is repair until buyers rebuild above the failed/churn
   boundary.

## Book Thesis Audit Pass 1

New reusable outputs from `research/direct_conversion_execution/scripts/episode_exec_lob_probe.py`:

- `research/direct_conversion_execution/out/episode_exec_lob_probe_20260724/sponsor_promotion_audit.csv`
- `research/direct_conversion_execution/out/episode_exec_lob_probe_20260724/churn_envelope_audit.csv`
- `research/direct_conversion_execution/out/episode_exec_lob_probe_20260724/anchor_outcome_audit.csv`

### Capture Depth Note

MarketRecorder has two different book data surfaces:

- Snapshot stream: bounded, configured `levelsPerSide=30` on 7/24. With NQ at
  0.25 tick size, the 30th level was typically about 31 ticks / 7.75 points
  from the mid/reference tick. The configured recorder range is levels, not
  points, so sparse books can extend farther.
- Raw `book_events`: not configured by distance. It records every real
  `NewLevel2` quote callback Quantower sends plus on-demand reset seeds from
  the canonical DOM. The 09:13 seed had 3703 quote items. That stream is deeper
  than the 30-level snapshots, but it contains far/off-market quote outliers and
  must be validated against snapshots before use as OFI evidence.

### Sponsor Promotion Audit

The audit separates parent/child sponsor behavior:

- `E1150`, child demand `86` over parent `84`: child was transient. Parent
  demand `84` had 28 same-side depth at promotion and still had 28 by +5s;
  child `86` had 18 at promotion, 0 by +5s, then failed at 11:53. After that
  failure, price moved 70.75 points favorable and only 8.5 adverse before the
  episode ended; the same directive re-entered at 11:55. This is the cleanest
  case for "child failure should not necessarily kill campaign when parent was
  the causal sponsor."
- `E1150`, child demand `95` over parent `89`: this one looks healthier. Child
  started from zero in the 1 Hz snapshot, then had 4 by +2s/+5s and 20 by +10s,
  with no failure inside the episode. This is a useful positive example of a
  child promotion that may have earned authority.
- `E1215`, child demand `103` over parent `102`: both parent and child were
  draining. Parent `102` was 34 -> 7 by +5s; child `103` was 9 -> 1 by +2s and
  later failed. After failure, favorable excursion was only 3.0 points while
  adverse excursion was 88.0 points. This was a proper terminal failure, not a
  premature exit.
- `E1215`, child demand `115` over parent `95`: child was transient/empty in
  the snapshot metric and failed at 12:30. Post-failure favorable excursion was
  only 0.75 points, adverse 34.5 points. This supports the repair-trap read.

Current read:

Sponsor promotion is not simply "bad." The useful distinction is:

- Transient child + parent still plausible + later same-directive continuation
  = likely premature flatten risk (`E1150` id 86).
- Draining child inside post-campaign repair + strong adverse after failure =
  real failure / do not preserve campaign (`E1215` id 103 and id 115).

### Churn Envelope Audit

The churn audit counts two-sided ownership/test/hold/fail transitions inside
the curated price envelope and combines that with volume concentration, net
movement, and range book change.

Key rows:

- `E1115`: high churn. 100 evidence transitions, demand/supply transitions
  40/60, both sides failed, 85.1% of volume inside 28470-28540, net move only
  +9.0 points, and both visible bid/ask depth increased. This matches the HVN /
  stand-aside read.
- `E1150`: high churn score but not an avoid label by itself. It had 95
  evidence transitions and 96.1% of volume inside 28500-28630, but net move was
  +89.5 points and range bid depth increased 6 -> 143. This is directional
  churn / campaign out of churn, not the same thing as dead-center HVN churn.
- `E1215`: high churn with repair failure character. 132 evidence transitions,
  demand/supply failures 9/7, 99.6% of volume in the envelope, net move -61.25,
  and range bid depth fell while ask depth held flat. This supports repair
  turning back down rather than fresh buying.
- `E1055`: mixed churn plus strong directional movement. This does not answer
  the no-entry question yet; it points to a separate active-directive no-entry
  blocker audit.
- `E1021`: directional, not churn. The short problem is first-contact sponsor
  quality inside opposite repair, not HVN churn.

Current read:

The book thesis is separating cases, but a single high-churn label is too broad
for execution by itself. The script now emits `churn_subtype`:

- `HVN_CHURN`: two-sided transitions/failures, high local volume, low net
  displacement, both sides building or absorbing. Stand aside.
- `DIRECTIONAL_CHURN`: high local volume and many transitions, but price
  displaces and one side's failures dominate. Do not automatically stand aside;
  audit sponsor promotion and road/horizon instead.
- `REPAIR_CHURN`: high two-sided churn after a same-side campaign failure, with
  new sponsors draining or failing and price unable to accept beyond the failed
  boundary.

## Next Script Work

- Add checkpointed raw book replay state so `--book-events` can start near any
  episode without replaying from 09:13.
- Add a no-entry audit for active directives, especially E1055.
- Calibrate churn subtype thresholds on more hand-labeled windows so the
  labels are not overfit to this batch.
- Add parent-survival simulation around child sponsor failures, using raw book
  replay checkpoints once available.

## E1021 Comparator Pass

User suggested successful campaign-worthy short comparators on 7/24 in either
09:35-10:00 or 14:00-14:45.

New outputs:

- Broad comparator:
  `research/direct_conversion_execution/out/e1021_short_comparator_20260724/`
- E1021 baseline with current anchor outcome audit:
  `research/direct_conversion_execution/out/e1021_baseline_20260724/`
- Raw morning comparator:
  `research/direct_conversion_execution/out/e1021_success_short_raw_E0949_20260724/`

### Candidate Windows

- 09:35-10:00 was the cleaner market campaign: O 28603.25, H 28622.00,
  L 28313.50, C 28322.25, range 308.50, volume 53669, delta -1455. EAR had no
  directive/order in this window, so this is a MarketRecorder/LL evidence
  comparator rather than an actual EAR trade.
- 14:00-14:45 also sold: O 28467.00, H 28486.00, L 28259.00, C 28276.50,
  range 227.00. EAR accepted a short directive at 14:26:50 with target 28226,
  but no order submit appeared in the window. Snapshot-only anchors around
  14:17 and 14:26 are good later candidates, but raw replay is too expensive
  until we have checkpointed book state.

### Successful Short Comparator: 09:49 Repair Into 28504-28508

The best raw-comparable morning case is the repair into supply 28504.50-28508.00
at 09:49:33-09:49:58, just before the 09:50 sell leg.

Raw book facts:

- 09:49:33 `RailTested` supply 28504.50-28508.00:
  same-side depth 40 -> 30 by +2s, attack2s 50, replenishment2s 40,
  reload ratio2s 0.80.
- 09:49:57 `RailTested` same supply:
  same-side depth 44 -> 43 by +2s, attack2s 6, replenishment2s 5,
  reload ratio2s 0.83.
- Broad 09:35-10:00 forward outcome from those anchors was roughly
  169-171 points favorable within 5 minutes with only 0.75-5.25 points adverse.

Interpretation:

This was a repair that actually contacted overhead supply, found supply still
there after contact, and then resolved almost immediately. The later fixed-band
depth going to zero is not by itself bearish or bullish because price moved far
away from the band and snapshots only capture 30 levels per side. The key
evidence is first-contact survival plus minimal adverse path.

### Failed Short Comparator: E1021 Around 28356.75-28358.50

Raw E1021 facts:

- 10:21:10 `EnterBase Short`/sponsor promoted at supply 28356.75-28358.50:
  same-side depth 19 -> 20 by +2s, but there was no real attack at the band in
  that first 2s.
- 10:21:13 first `RailTested` at the same band:
  same-side depth was only 1 and went to 0 by +2s; opposite depth was 9 -> 21.
  Raw add/remove churn was high on both sides: same-side add/remove 107/108 and
  opposite add/remove 101/91 over +2s.
- Broad forward outcome after the tested contact was roughly 4.25 points
  favorable and 66 points adverse within 5 minutes.

Interpretation:

The failed E1021 short was not missing a visible sponsor at the exact trigger.
It was missing the stronger proof that the successful comparator had: actual
tested absorption after repair contacted the supply. The 10:21 sponsor existed,
but the first meaningful test showed a nearly empty same-side band, opposite
depth building, and two-sided quote churn instead of clean supply control.

### Working Rule Shape

For conversion shorts, do not treat "sponsor exists at submit time" as the same
as "sponsor survived repair contact."

More precise research gate:

- If the trade is a repair fade, require a `RailTested`/`RailHeld` sequence at
  the candidate supply after the repair reaches it.
- Favor cases where first contact has attack volume but same-side depth remains
  present and replenishment is non-negative or positive.
- Penalize cases where the first contact has near-zero same-side depth, opposite
  depth building, or high two-sided add/remove churn.
- Do not require fixed-band depth to remain visible after price has already
  displaced far away; with 30-level snapshots, that can be a distance artifact.

## E1021 Long Counterexample Pass

User asked whether the long campaign from 11:50 through the 12:07/12:10 adds
behaved the same way as the 09:49 successful short comparator.

New output:

- `research/direct_conversion_execution/out/e1021_long_counterexample_20260724/`

This pass is snapshot/tape based, not raw quote replay. Raw replay this late in
the day still needs checkpointed book state.

### 11:50 Base Long

EAR:

- 11:50:22 `EnterBase Long`, reason `direct_conversion_retest`, support/root
  demand id 84 at 28502.75-28511.75.
- Filled around 28515.
- 11:50:59 sponsor promoted to child demand id 86 at 28532.50-28534.00.
- 11:53:01 child id 86 failed and EAR flattened.

Book/outcome:

- Parent id 84 had same-side depth 28 -> 21 by +2s and 28 by +5s, with no
  attack at the band. Forward path from parent sponsor: about 68 points
  favorable, 0 adverse within the episode's 10-minute horizon.
- Child id 86 was transient: 18 -> 18 by +2s, 0 by +5s, 17 by +10s. Its failure
  did not kill the larger idea; after child failure, price moved about 106.75
  points favorable and 8.5 adverse through 12:12.

Read:

This does not behave like the E1021 failed short. It also does not require the
same "repair attacks supply and supply reloads" proof as the 09:49 short. The
better explanation is campaign transition: once demand id 84 formed, price
accepted upward with almost no adverse path. The problem was the local child
sponsor id 86 becoming flatten authority too early.

### 12:03 / 12:07 Add

EAR:

- 12:03:25 sponsor promoted to demand id 95 at 28559.50-28563.50.
- 12:07:25 sponsor promoted to demand id 97 at 28585.25-28585.75.
- 12:07:32 `Add Long`, reason `supported_reclaim_confirmed`, root supply id 96
  at 28590.50-28593.25 and support demand id 97 at 28585.25-28585.75.

Book/outcome:

- Demand id 95 looked healthier than id 86: same-side depth 0 -> 4 by +2s/+5s
  and 20 by +10s; no failure in the window.
- Demand id 97 / the 12:07 support band had zero visible same-side depth in the
  1 Hz snapshot metric, yet the add worked: about 31.75 points favorable and
  only 1.5 adverse from the add anchor.
- The important local event was the root supply failure at 12:07:32 around
  28590.50-28593.25, not resting demand depth at 28585.25-28585.75.

Read:

This is the main counterexample to any naive "must see same-side book stacked at
support" rule. The add behaved like a supported reclaim / supply failure
transition. The proof is sequence plus immediate favorable displacement, not
static book depth at the support tick.

### 12:10 Add / Failure

EAR:

- 12:10:35 sponsor promoted to demand id 102 at 28617.75-28619.50.
- 12:10:42 `Add Long`, reason `direct_conversion_retest`, same band.
- 12:10:55 sponsor promoted to child demand id 103 at 28622.00-28622.25.
- 12:11:34 id 103 failed and EAR flattened the campaign.

Book/outcome:

- Id 102 was draining: 34 -> 22 by +2s, 7 by +5s, replenishment -12 / -27.
- The add band at 12:10:42 was also draining: 42 -> 31 by +2s, 27 by +5s, and
  0 by +10s.
- Child id 103 was draining: 9 -> 1 by +2s, 8 by +5s; after failure, favorable
  was only about 1.25 points and adverse 11.5 through 12:12.

Read:

This one does behave like a failed-late sponsor case. It is much closer to the
E1021 failure than to the 09:49 successful short or the 12:07 reclaim add:
visible demand existed, but it was draining and the forward path turned adverse
quickly.

### Refined Thesis After Counterexample

The book rule cannot be "require same-side stacked liquidity at the execution
band." That would reject valid supported-reclaim adds like 12:07.

Resolution-type split confirmed:

- 10:21 short was `DirectConversion`, reason `direct_conversion_retest`,
  root/support both id 34 at 28356.75-28358.50.
- 11:50 base long was also `DirectConversion`, reason
  `direct_conversion_retest`, root/support both id 84 at 28502.75-28511.75.
  This one worked directionally at the parent/campaign level, but the child
  sponsor id 86 caused a premature local flatten.
- 12:07 add was `SupportedReclaim`, reason `supported_reclaim_confirmed`.
  Root was failed supply id 96 at 28590.50-28593.25; support was demand id 97
  at 28585.25-28585.75. This should be judged by root failure plus reclaim
  acceptance, not by static visible demand at the support tick.
- 12:10 add was `DirectConversion`, reason `direct_conversion_retest`,
  root/support both id 102 at 28617.75-28619.50. This was the cleaner long-side
  analog to E1021: visible sponsor existed, but it was draining and the child
  sponsor id 103 failed quickly.

Better split:

- Repair-fade entries need first-contact proof: the repaired side must attack
  the candidate sponsor and fail to eat it, like the 09:49 short.
- Reclaim/transition entries need root failure and immediate acceptance: the
  support band may not show visible resting depth, but price should displace
  favorably with low adverse path, like the 12:07 add.
- Late adds after extension need sponsor-quality tightening: if the new sponsor
  is draining before/after promotion, treat it as add-risk or de-leverage risk,
  like 12:10.

## Child Sponsor 86 Raw Replay Pass

User hypothesis: child sponsor id 86 might also be a direct-conversion sponsor.
If true, direct-conversion entries/children may often need retest-and-book
scoring around formation and retest.

New raw output:

- `research/direct_conversion_execution/out/e1150_child86_raw_20260724/`

Replay health:

- NQU6 book events, 11:48-12:12 ET.
- 1,740 book-event files with one carry day.
- 31,680,294 rows processed.
- 0 gaps, 2 resets.

Runtime provenance:

- 11:50:22.158 `EnterBase Long`, reason `direct_conversion_retest`,
  resolution `DirectConversion`, root/support both id 84 at 28502.75-28511.75.
- 11:50:22.675 sponsor promoted to id 84, reason `filled_entry`.
- 11:50:44.689 id 86 `CandidateFormed`, demand, 28532.50-28534.00.
- 11:50:45.902 id 86 `CandidateDisplacementStarted`, reason `Favor`.
- 11:50:46.906 id 86 displacement reset inside threshold.
- 11:50:49.181 id 86 displacement restarted, reason `Favor`.
- 11:50:59.165 id 86 became `RailOwned`, reason `OWNED`.
- 11:50:59.167 sponsor promoted to id 86, reason
  `accepted_same_side_ownership`, prior sponsor id 84.
- 11:51:25-11:52:42 id 86 churn-tested repeatedly: six `RailTested` events
  and five `RailHeld` events.
- 11:53:01.317 id 86 failed and triggered campaign flatten.

Important distinction:

Id 86 was not an order-entry `DirectConversion` sponsor. The actual
DirectConversion entry was id 84. Id 86 was a child sponsor succession rail,
promoted by `accepted_same_side_ownership`.

But the user's instinct is directionally important: id 86 was a same-side
ownership claim born immediately after a DirectConversion parent entry, and its
promotion/failure path was governed by the same question we care about for
direct-conversion entries: does the book prove that the newly claimed area can
hold retests, or is it just transient liquidity around a still-live parent
campaign?

Raw book around id 86:

- At 11:50:59 promotion, demand depth was 19 -> 18 by +2s, then 0 by +5s.
  Replenishment was -1 by +2s and -19 by +5s. No attack printed at the band in
  the first 5 seconds. This is a weak promotion: visible depth existed, but it
  drained without tested absorption.
- First meaningful test at 11:51:25 showed demand 28 -> 28 by +2s and 24 by
  +5s, with attack only 0 by +2s and 1 by +5s. That was not a strong hostile
  retest; it was more like local churn.
- Later tests alternated between reload and drain:
  - 11:51:31 test: 25 -> 31 by +2s, attack 10, replenishment +16, reload ratio
    1.6, but 0 depth by +5s.
  - 11:51:45 test: 16 -> 6 by +2s, attack 5, replenishment -5.
  - 11:52:28 test: 20 -> 0 by +2s while ask/opp depth appeared at 27, then
    demand still could not persist.
  - 11:52:42 test: 21 -> 26 by +2s, but 0 by +5s.
- At failure, demand was 0 while opposite depth was 33. Sponsor failure was a
  local child failure, not evidence that parent id 84 had become wrong.

Sponsor audit:

- Id 86 child quality was classified `transient`.
- After id 86 failed, the post-failure path through 12:12 was about 106.75
  points favorable and 8.5 adverse from the post-failure start.
- The next same-directive order was another base long at 11:55:43, again
  `direct_conversion_retest`, from id 89 at 28549.25-28551.75.

Read:

This does identify something real, but not quite as "id 86 was
DirectConversion." The cleaner formulation is:

- DirectConversion parent entries create a campaign sponsor.
- Later same-side child sponsorships can promote on ownership acceptance.
- Those child sponsors need their own book-quality score before they become
  flatten authority.
- A child sponsor that forms without hostile retest absorption and then churns
  through mixed reload/drain should be treated as tactical/local, not as the
  sole campaign kill switch while the parent campaign remains intact.

Research implication:

For the next pass, split sponsor objects into:

- Entry sponsor: the object that justified the order resolution.
- Campaign sponsor: the object allowed to keep/kill the position.
- Child/local sponsor: a promoted same-side ownership claim that can justify
  tightening, de-leveraging, or adding only if its formation/retest book quality
  passes.

The likely rule is not "direct conversions always retest." It is:

- DirectConversion entries and their immediate child promotions often need a
  first-contact/retest audit.
- If the sponsor is a repair-fade object, require hostile attack plus reload or
  failed eating.
- If the sponsor is a transition/reclaim child, require favorable acceptance
  plus low adverse path, and do not let an unproven child flatten a still-live
  parent campaign by itself.

## 7/23 DirectConversion Retest Thesis Pass

User refinement: set aside child sponsor 86 for now. Test the independent
thesis that `DirectConversion` retest should not be blindly executable just
because the rail is confirmed/live. This may also explain HVN/VPOC churn false
entries, because HVN formation tends to create repeated direct-conversion
opportunities on both sides.

New scripts:

- `research/direct_conversion_execution/scripts/extract_direct_conversion_retests.py`
  - Scans EAR `events.jsonl` by ET date and writes actual
    `order_submit` rows where `resolution=DirectConversion` and
    `reason=direct_conversion_retest`.
- `research/direct_conversion_execution/scripts/summarize_episode_order_outcomes.py`
  - Joins a probe output directory's `ear_events.csv`, `bars_5s.csv`,
    `book_anchors.csv`, and `churn_envelope_audit.csv` into order-level
    outcome rows.

New outputs:

- `research/direct_conversion_execution/out/direct_conversion_retests_2026-07-23.csv`
- `research/direct_conversion_execution/out/dc_retest_20260723/`
- `research/direct_conversion_execution/out/dc_retest_20260723_raw_primary/`
- `research/direct_conversion_execution/out/dc_retest_20260723_raw_late_short/`

Raw replay health:

- Primary 12:14-13:25 pass: 1,846 NQU6 book-event files, 1 carry day,
  27,250,597 rows, 0 gaps, 2 resets.
- Late-short 14:30-15:00 pass: 1,846 NQU6 book-event files, 1 carry day,
  30,531,746 rows, 0 gaps, 2 resets.

### Actual 7/23 DirectConversion Retest Attempts

EAR submitted seven `direct_conversion_retest` orders on 7/23:

- 12:19:50 short, id 111, 28629.50-28635.25.
- 12:33:23 long, id 125, 28695.75-28699.75.
- 13:06:39 long, id 155, 28596.25-28596.75.
- 14:35:52 short, id 208, 28590.50-28593.00.
- 14:50:17 short add, id 217, 28572.25-28576.50.
- 15:06:12 long, id 228, 28516.25-28517.50.
- 15:56:26 long, id 268, 28574.75-28577.75.

The user-labeled HVN/churn zones line up with several of these:

- 12:33 long is inside the 690s churn / false-supply-survival area.
- 13:06 long is inside the 13:00-13:30 no-trade churn area.
- 15:06 long is inside late `HIGH_CHURN` / repair churn.

### 12:19 Short - Confirmed Rail, Bad Entry

Context:

- User label around 12:15-12:25 was expected VWAP/630ish repair churn before
  up resolution.
- EAR shorted at 12:19:50 on supply id 111, 28629.50-28635.25.

Book/outcome:

- At order submit: supply depth 87 -> 87 by +2s, 62 by +5s, 81 by +10s.
- No hostile attack printed at the order band in the first 5s.
- Replenishment was 0 by +2s, -25 by +5s, +37 by +10s.
- Fill was 28624.75, flatten was 28645.25, about -20.5 points.
- Forward path was only 0.75 favorable versus 34.25 adverse by 2m, 71.5
  adverse by 5m.

Read:

This is a clean example where a live supply rail and proximity/retest did not
prove the repaired side had failed. The book was present, but the entry had no
first-contact failure proof; the broader repair was still resolving upward.

### 12:33 Long - HVN/690s Churn False Positive

Context:

- User label: around the 690s, supply claims were expected to survive but
  churned instead.
- Churn envelope: `HIGH_CHURN`, `MIXED_CHURN`, two-sided failure true, churn
  score 7.11.
- EAR entered long at 12:33:23 on demand id 125, 28695.75-28699.75.

Book/outcome:

- At order submit: demand depth 66 -> 55 by +2s, 63 by +5s, 44 by +10s.
- No hostile attack printed at the order anchor in the first 5s.
- Replenishment was -11 by +2s, -3 by +5s, -22 by +10s.
- The nearby predecessor at 28695.50-28698.75 had already failed:
  - 12:30:15 test: 64 -> 40 by +2s, 0 by +5s, attack 14/30,
    replenishment -10/-34.
  - 12:30:36 rail failed.
- Fill was 28704.75, flatten was 28689.00, about -15.75 points.
- Forward path was 2.5 favorable versus 22.5 adverse by 2m.

Read:

This strongly supports the thesis. DirectConversion retest confirmed the live
rail/proximity condition, but the area was already a two-sided churn/HVN zone
with a recent failed same-side claim. The correct quality rule would discount
or block the retest until a post-churn edge establishes.

### 13:06 Long - Churn Counterexample, Not Simple Block

Context:

- User label: 13:00-13:30 was broad no-trade churn.
- Churn envelope: `HIGH_CHURN`, `MIXED_CHURN`, two-sided failure true, churn
  score 6.72.
- EAR entered long at 13:06:39 on demand id 155, 28596.25-28596.75.

Book/outcome:

- At order submit: demand depth 10 -> 15 by +2s, 8 by +5s, 11 by +10s.
- Attack was small but present: 2 by +2s and +5s.
- Replenishment was +7 by +2s, 0 by +5s, +3 by +10s.
- Fill was 28599.50.
- Forward path was 29.25 favorable vs 9.5 adverse by 2m, 48.25 favorable by
  5m, 58.75 favorable by 10m.
- Campaign later flattened at 13:17:45 on child sponsor id 160, with a
  favorable flatten around +31.94 points from the base fill.

Read:

This is the necessary counterexample. A churn envelope alone should not say
"impossible." The base entry had better immediate quality than 12:33 and did
move favorably. But it still sits in a no-trade/HVN zone from the user's
framework, so the rule should likely downgrade size/permission or demand a
cleaner edge, not simply treat every DirectConversion in churn as false.

### 14:35 / 14:50 Short Comparators

14:35 short:

- EAR shorted at 14:35:52 on supply id 208, 28590.50-28593.00.
- At order submit: supply depth 43 -> 44 by +2s, 48 by +5s.
- Forward path: 30.12 favorable vs 0.12 adverse by 2m, 32.12 favorable by 5m.
- It flattened at 14:40:14 after child sponsor 210 failed, still about +13.12
  points from the base fill.

14:50 short add:

- EAR added short at 14:50:17 on supply id 217, 28572.25-28576.50.
- At order submit: supply depth 91 -> 21 by +2s, 0 by +5s.
- Forward path: 12.75 favorable vs 2.0 adverse by 2m, 40.5 favorable by 5m.
- This is a useful warning: same-side depth draining is not automatically bad.
  If price immediately displaces favorably away from the band, visible resting
  supply may cancel/withdraw after doing its job. The quality test must
  distinguish favorable displacement from adverse eating.

### 15:06 / 15:56 Broad Context

The broad non-raw seven-episode pass also showed:

- 15:06 long, id 228, inside `HIGH_CHURN` / `REPAIR_CHURN`: fill 28521.25,
  sponsor failed at 15:08:02, flatten 28510.75, about -10.5 points. This is
  another direct retest false positive inside churn, but it still needs raw
  replay if we want book-level proof.
- 15:56 long, id 268, near close: directional path was favorable. Treat this
  as low-priority because the close dynamics and time left are different.

### 7/23 Rule Hypothesis

The thesis stands, with refinement.

`DirectConversion + retest` is currently a structural/execution condition:
price returned close enough to a live same-side rail. It is not sufficient
evidence that the rail passed a book-quality test.

Potential research rule:

- Do not classify HVN/LVN first and then decide whether the direct conversion
  is tradeable. Evaluate the direct-conversion lifecycle, and let churn,
  balance, or escape emerge from that lifecycle.
- Extra proof can be one of:
  - hostile contact at the sponsor with reload/absorption and failed eating;
  - immediate favorable displacement with very low adverse path;
  - re-establishment at or beyond the edge of the recent interaction field,
    not a fresh claim in the middle of the still-forming node.
- Discount same-side claims when the same price area had a recent same-side
  rail test-and-fail before the new retest, as at 12:33.
- Do not use raw depth drain alone as the failure signal. Drain after favorable
  displacement can be healthy; drain during or after hostile contact is the
  warning.

HVN/VPOC implication:

During HVN/VPOC formation, both sides repeatedly create rails that can satisfy
DirectConversion retest mechanics. That explains why EAR can faithfully take
entries in the middle of a forming node even though the discretionary read is
"nothing inside should be tradeable." The missing layer is not a new rail
definition first; it is an admission-quality layer over direct conversions:
churn envelope + recent same-zone failure history + contact/reload/path quality.

## DirectConversion Lifecycle Frame

User reframing on 2026-07-25:

The central question is not "are we in HVN or LVN?" The central question is
"how do we better evaluate direct conversion events?"

Example frame:

- Price rises from below.
- Sellers lean in around 98-100 after some two-sided interaction around 90/95.
- Buyers consume the seller lean at 98-100 and then some.
- The z-score detects both the seller lean and the overwhelming of that lean;
  this is the direct-conversion event.
- Price naturally auctions higher because the seller liquidity at 98-100 has
  been consumed and the auction must seek the next participants.
- If price flies to 112-115, there is no retest question.
- If price comes back below 97 into 95, the consumed-band event failed.
- The interesting case is when price pauses after 105-107 and returns toward
  98-100.

Important refinement:

In a strict narrow model, we want buyers to reload with limit at 98-100 on the
retest. In live auction behavior, the quality question is broader:

- What was below the conversion band before the conversion event formed?
- Was there unfinished liquidity or two-sided participation below 98 that
  should invite trade back into 95?
- How did price approach the conversion band on the retest?
- Did the retest meet resting reload, failed eating, or immediate favorable
  re-displacement?
- Did price trade back through the conversion band into the pre-conversion
  interaction field, which would mean the conversion failed?

Working idea:

HVN/LVN state should be an output of the direct-conversion lifecycle, not a
separate heuristic input. During node formation, direct conversions will appear
and fail repeatedly because both sides are still discovering participation.
When the node-building job is done, a later direct conversion can be the escape
engine from the same area. The difference should be visible in the lifecycle:

- Before: prior interaction field below/above the conversion, leftover
  liquidity, repeated same-zone failures, and whether the band forms at the
  interior or edge of that field.
- During: strength of the consumption event, displacement away from the band,
  and whether the new side had to absorb hostile contact or merely traded
  through empty space.
- After: retest approach speed/shape, same-side reload, opposite-side stacking
  or pulling, whether the band holds without deep re-entry into the
  pre-conversion field, and whether price re-displaces favorably.

Implication for 7/24 11:50/11:55:

- The 515 area may have been an HVN/VPOC node where earlier direct conversions
  were still node-building/churn behavior.
- The 555 area may have been after escape from the node, where a direct
  conversion became more tradeable because the lifecycle showed acceptance
  away from the node rather than another interior churn claim.

Next research target:

Build a direct-conversion event score around `before/during/after` fields:

- Before: recent interaction width, two-sided failure density, prior same-zone
  same-side failure, distance from interaction-field boundary, and leftover
  book depth below/above the conversion band.
- During: consumed/lean z-score, side-depth change, hostile attack volume,
  replenishment/reload ratio, and first displacement away from the band.
- After: retest approach velocity, time away before retest, band-touch depth,
  same-side reload, opposite-side pull/stack, max re-entry into the
  pre-conversion field, and favorable/adverse path after retest.

This should be tested directly on direct-conversion events, not by building a
separate HVN/LVN detector first.

## Synthetic DirectConversion Population Pass - 2026-07-23/2026-07-24

Artifacts:

- Dataset builder:
  `research/direct_conversion_execution/scripts/direct_conversion_lifecycle_dataset.py`
- Predictor ranking:
  `research/direct_conversion_execution/scripts/analyze_direct_conversion_buckets.py`
- Output root:
  `research/direct_conversion_execution/out/direct_conversion_lifecycle_20260723_20260724/`
- Analyzer outputs: 224 single-feature bucket rows, 66 ranked predictor
  features, 18,913 pairwise bucket rows, and 14,352 non-missing pairwise bucket
  rows.

Population:

- Synthetic source is LL `CONSUMED` transitions from MarketRecorder snapshots.
  This maps to a direct-conversion event as currently framed: one side's
  evidence band is confirmed adverse and ownership flips to the consuming
  side.
- 2026-07-23: 21,849 snapshots, 455,141 ticks, 72 conversions, 0 snapshot
  gaps.
- 2026-07-24: 20,877 snapshots, 417,197 ticks, 95 conversions, 6 snapshot
  gaps.
- Total: 167 synthetic direct conversions.

Outcome counts:

- `retest_held`: 79
- `retest_failed`: 67
- `failed_without_retest`: 14
- `no_retest_seen`: 7

First separation:

- Time-to-retest is the dominant simple dimension.
- `time_to_test_bucket=0-30s`: n=69, failed within 5m = 0.899.
- `time_to_test_bucket=30-120s`: n=34, failed within 5m = 0.912.
- `time_to_test_bucket=5m+`: n=32, failed within 5m = 0.000, but many can
  still fail on later same-band retest. So "held through 5m" and "eventual
  retest failed" must remain separate labels.

Conversion-time features are weaker alone:

- `conv_replenishment_2s_bucket=reload`: n=35, failed within 5m = 0.886.
- `conv_replenishment_2s_bucket=strong_reload`: n=11, failed within 5m =
  0.818.
- `conv_replenishment_5s_bucket=reload`: n=45, failed within 5m = 0.800.
- `width_pts=3_high>2.17`: n=56, durable success = 0.339, failed within 5m =
  0.571.
- `conv_replenishment_5s_bucket=flat`: n=68, durable success = 0.309, failed
  within 5m = 0.515.

This is useful mostly because naive same-side reload at the conversion point is
not enough. In this population, immediate post-conversion reload often belongs
to churn/unfinished auction rather than clean escape. The approach/retest
context has to decide whether reload is sponsorship or just the next
two-sided fight.

Cleaner non-missing pair buckets:

- Failure:
  `fav_before_test_pts=1_low<=2.83 | conv_reload_ratio_5s=3_high>0.84`:
  n=25, failed within 5m = 1.000.
- Failure:
  `time_to_test_bucket=0-30s | test_opp_depth=3_high>1.00`:
  n=23, failed within 5m = 1.000.
- Failure:
  `time_to_first_test_s=1_low<=14.7 | conv_replenishment_5s_bucket=reload`:
  n=20, failed within 5m = 1.000.
- Durable:
  `time_to_test_bucket=5m+ | test_reload_ratio_2s=3_high>1.00`:
  n=12, durable success = 0.750, failed within 5m = 0.000.
- Durable:
  `time_to_test_bucket=5m+ | test_same_depth=3_high>28.0`:
  n=10, durable success = 0.700, failed within 5m = 0.000.
- Durable:
  `time_to_test_bucket=5m+ | width_pts=3_high>2.17`:
  n=13, durable success = 0.692, failed within 5m = 0.000.

Current interpretation:

- The working shape is not "direct conversion is good/bad." It is:
  direct conversion creates a claim; the first return to that claim reveals
  whether the auction is still unresolved.
- Fast return to the band is usually a warning, especially when the event has
  not travelled far before retest or opposite-side depth is still waiting at
  the test.
- Late return after meaningful displacement is a different state. If the
  retest then shows owner-side reload/depth, it starts to look like repair and
  re-establishment instead of churn.
- This explains why HVN/VPOC churn does not need a separate detector first:
  repeated fast-return direct conversions are the node-building signature,
  while a later direct conversion with time away and retest reload can be the
  escape signature.

Known mismatch to investigate:

- The 2026-07-24 11:50/11:55 EAR long campaign did not map cleanly to a
  synthetic LL `CONSUMED` row at the exact child-promotion area. The new
  `rail_transitions.csv` sidecar explains why:
  - 11:50:12 demand `CONSUMED`, `supply_consumed`, 28503.00-28507.00.
  - 11:50:45 demand `FORM`, candidate, 28531.75-28534.00.
  - 11:50:59 demand `OWNED`, `demand_lean`, 28531.75-28534.00. This matches
    the EAR child demand id 86 area.
  - 11:51:37 demand `FAIL`, `demand_lean`, 28531.75-28534.00.
  - 11:53:38 demand `CONSUMED`, `supply_consumed`, 28526.00-28530.50.
- This matters for the 11:50 early-exit question. The child sponsor around
  28532-28534 failed quickly in synthetic LL, but the lower 11:50:12 direct
  conversion and the later 11:53:38 demand conversion were still better
  campaign context. A child sponsor failure may be too local to flatten if the
  parent/direct-conversion campaign remains intact.
- The sidecar now exports all synthetic LL rail transitions, not just
  `CONSUMED`, so EAR `DirectConversion` attempts can be reconciled as either
  pure consumed conversions, fresh same-side ownership, or seeded runtime
  variants.

Next falsification steps:

- Validate a small set of top failure and top durable buckets with raw
  quote-event replay, starting with the 7/24 10:21 failure, 7/24 11:50/11:55
  long campaign, 7/24 12:10 add failure, and 7/23 post-12:25 churn examples.
- Add more dates before proposing runtime logic. This first pass is strong
  enough to continue the research direction, not strong enough to code an EAR
  gate.
