# HoldRoot Scale Findings 2026-08-30

Codex-authored research note. This is not accepted Kahn policy.

## Objective

Investigate scale-up, and secondarily scale-out, for three ES cases:

- 2026-08-27 long after 11:30 around 7728.
- 2026-08-27 actual short after 13:30 around 7748.
- 2026-08-28 hypothetical short after 11:20 around 7780.

The question is not whether Kahn can avoid every first scratch. The useful
question is whether Kahn can add while preserving HoldRoot's risk priority.

## Method

`holdroot_scale_probe.py` replays LevelLedger ownership transitions and scores
same-side rail contacts with MarketRecorder MBO flow:

- `replenish = added / (consumed + pulled)` over the 60 seconds after rail TEST.
- `paid_share = consumed / (consumed + pulled)`.
- `add_preserve_root` requires same-side OWNED/HOLD/CONSUMED evidence, a
  replenished contact, target runway, and either a recent opposite rail failure
  or a depleted opposite contact.
- `add_preserve_root_reduced` is the same gate after more than 45 percent of
  the planned target path has already paid.
- `mature_path_hold_only` suppresses new adds after 65 percent of the planned
  path has already paid.

Outputs:

- `research/kahn/out/holdroot-scale-20260830/report.md`
- `research/kahn/out/holdroot-scale-20260830/scale_candidates.csv`
- `research/kahn/out/holdroot-scale-20260830/scale_out_events.csv`
- `research/kahn/out/holdroot-scale-20260830/timestamp_sanity.csv`
- `research/kahn/out/sponsor-stack-scale-20260830/report.md`
- `research/kahn/out/sponsor-stack-scale-20260830/stack_candidates.csv`
- `research/kahn/out/sponsor-stack-scale-20260830/call_counts.csv`
- `research/kahn/out/tail-reclaim-sequence-20260830/report.md`
- `research/kahn/out/tail-reclaim-sequence-20260830/tail_reclaim_sequences.csv`
- `research/kahn/out/tail-reclaim-sequence-20260830/call_counts.csv`
- `research/kahn/out/local-lvn-separator-20260830/report.md`
- `research/kahn/out/local-lvn-separator-20260830/local_lvn_rows.csv`
- `research/kahn/out/local-lvn-separator-20260830/call_counts.csv`

## Timestamp Finding

The receipt/exchange timestamp mismatch does not affect Kahn runtime, current
LevelLedger runtime, or snapshot-only LL replay. It matters when offline
research joins MarketRecorder `book_events` to trade ticks to split quote
removals into consumed versus pulled.

The harness uses `exchange_timestamp_us` for book-event/tick attribution.
Measured receipt-minus-exchange offsets in these windows:

- 2026-08-27 11:30 long window: median -151.2 ms.
- 2026-08-27 13:30 short window: median -281.0 ms.
- 2026-08-28 11:20 short window: median -928.5 ms.

So the "~1s" claim is not uniformly true across these cases, but it is large
enough on 2026-08-28 that receipt-time joins would materially damage MBO
research. Existing Kahn/LL production logic is not implicated by this.

## Case Reads

### 2026-08-27 11:30 Long Around 7728

This case did not produce a full preserve-root add.

The 11:40:17 HOLD on 7727.50-7728.50 had strong replenishment, but no recent
opposite failure/depleted contact and a later 5.75 point adverse path if used as
an add. The 11:41-11:43 demand contacts around 7728-7731 were depleted and
should reject scale. The 11:45-11:49 lower demand repairs around 7719-7725 and
7723.50-7725.75 were cleaner, with low future adverse excursion, but they still
classify as `add_review` rather than `add_preserve_root`.

Read: this supports holding/re-entering after lower repair more than it supports
pressing the original 7728 root. HoldRoot conservatism was mostly correct here.

### 2026-08-27 13:30 Short Around 7748

This is the best actual Kahn scale-up case.

Kahn entered at 13:39:03 and retired at 14:31:48. The immediate 13:39:04
same-side HOLD was depleted, so the first add should not fire immediately.
By 13:44:39, supply 7751.25-7753 held with replenish 1.031, paid_share 0.040,
one recent depleted opposing contact, 19 points of runway to the 7729.50 target
floor, and only 0.25 points of future adverse excursion. That is a clean
`add_preserve_root` row.

14:01:13 also passes as `add_preserve_root`: supply 7745-7747.25 held with
replenish 1.101, two recent depleted opposing contacts, 13 points of runway, and
0.25 points future adverse excursion. It is a second/add-on candidate, not the
primary missed scale because roughly one-third of the target path was already
paid.

Read: HoldRoot should not have meant "no scale" here. A root-preserving add gate
would likely have allowed one calculated add around 13:44, with a possible
second smaller add around 14:01 if the campaign max allowed it.

### 2026-08-28 11:20 Short Around 7780

This is the cleanest hypothetical scale-up case.

The earliest 11:23:44 high-rail HOLD is constructive but only `add_review`,
because no opposing weakness had arrived and future adverse excursion was 5.75
points. By 11:34:09, both the wide 7778.25-7781.75 rail and tight
7778.50-7779.50 rail held with replenishment above threshold, two recent
depleted opposing contacts, more than 35 points of runway, and only 1 point of
future adverse excursion. 11:35:03 and 11:36:16 also pass as full
`add_preserve_root` candidates.

The lower continuation rails at 11:40:59 and 11:42:33 still pass the quality
gate, but more than half the path was already consumed, so they should be
reduced-size adds at most. By 11:48-11:49, the rail quality remains good but
65-71 percent of the planned path is already paid, so the correct read is
`mature_path_hold_only`.

Read: the good scale window was high and early, roughly 11:34-11:36, not late
near the target. This is exactly the type of campaign where preserving root risk
while adding makes sense.

## Sponsor-Stack Renewal Pass

User hypothesis tested after the first pass: keep a stack of favorable
same-side events once root is onside, including direct consumption and same-side
lean rails, then promote add priority only when that stack is challenged and
renews with replenished book response.

`sponsor_stack_scale_probe.py` adds these gates over the first pass:

- Current price must be onside and root must already have at least 0.5 points
  of pre-event cushion, so the entry tick itself cannot become a scale trigger.
- Same-side stack depth must be at least two rails near current price.
- Current same-side HOLD/OWNED/CONSUMED must have replenished contact quality.
- Full add priority requires renewal stronger than a plain retest: held retest
  plus failed/depleted opposition, or re-establishment after same-side fail.
- Retest-only rows become `stack_watch_retest_only`.

Results:

- 2026-08-27 long: 11:40:17 remains suppressed as
  `watch_stack_before_root_cushion`; it is not a way to avoid the first tax.
  11:47:42 becomes the one real sponsor-stack candidate: demand
  7723.50-7725.75 re-established after a same-side fail, stack depth 9
  with 5 direct-consumption and 4 same-side-lean rails, replenish 1.060,
  14.75 points of runway, and 2.0 points future adverse. 11:49:50 is
  only retest-watch after that, not another priority add.
- 2026-08-27 short: 13:44:39 remains the clean actual missed scale. Supply
  7751.25-7753 held after test while opposition was depleted, stack depth 2,
  replenish 1.031, root cushion 0.5, 19 points of runway, and only 0.25
  future adverse. 14:01:13 loses full priority in this stricter framing because
  the nearby active stack is shallow even though the individual contact is good.
- 2026-08-28 short: the best high-priority scale remains 11:34:09-11:36:16.
  The two 11:34:09 high rails and the 11:35:03/11:36:16 continuation rows pass
  as full `sponsor_stack_add`. 11:40:59 and 11:42:33 remain reduced-size
  candidates because more than half the path has already paid. 11:23:44 is
  demoted to `stack_watch_retest_only`: useful evidence, but not enough by
  itself to outrank HoldRoot.

## Tail-Reclaim Sequence Pass

User refinement tested after sponsor-stack pass: avoid EAR-style premature
A-B-C-D scaling. Hold root A, let favorable B/C/D extend, let price repair,
then look for an opposing ZZ claim inside the earned path. Only after ZZ fails
or is implicitly invalidated by trade back through the prior tail should Kahn
consider participating. This is a sequence state, not a single rail score.

`tail_reclaim_sequence_probe.py` adds these concepts:

- A favorable tail D is the best onside price reached after root.
- A same-side failure can be formal LL `FAIL`, or an implicit tail challenge
  when price repairs at least 1.5 points from D and an opposing HOLD/OWNED claim
  appears in the earned corridor.
- ZZ can fail formally, or implicitly when same-side trade reclaims through ZZ
  or through the prior D tail.
- The candidate row still requires replenished MBO flow, root cushion, runway,
  and a non-mature path. Near target, the same sequence becomes hold/harvest
  evidence rather than add evidence.

Results:

- 2026-08-27 long: the C/D-ZZ-C/D shape appears around 11:51-11:53 after the
  11:44 supply ZZ claim, but it is not a scale-up. The first reclaim row at
  11:51:54 has depleted contact quality, and the 11:52:57/11:53:03 continuation
  rows are already inside target proximity with only 5.5-5.75 points of runway.
  Read: this strengthens hold/harvest into the 7743 target, not add.
- 2026-08-27 short: the exact sequence catches a second valid add class at
  14:01:13. Demand ZZ held around 7741-7742.75 after the 13:58:28 favorable
  tail near 7743. Price then traded back through the prior tail; supply
  7745-7747.25 held with replenish 1.101, 13 points of runway, 32.5 percent
  path consumed, and 0.25 points future adverse. This is not the same as the
  earlier 13:44 sponsor-stack add; it is the later C/D-ZZ-C/D reclaim add.
- 2026-08-28 short: the exact sequence is more conservative than the
  sponsor-stack pass. It identifies 11:36:16 as the full `tail_reclaim_add`
  after demand ZZ failed at 11:35:03 and price later broke the prior tail at
  11:37:20. The 11:34 rows remain valid under sponsor-stack renewal, but the
  stricter C/D-ZZ-C/D trigger waits for the failed repair cycle. 11:40:59,
  11:42:33, and 11:45:23 are reduced-size only because more than half the path
  is already consumed.

Read: this supports two separate add archetypes. `SponsorStackAdd` is the early
root-preserving add when same-side stack and opposing weakness are already
clear. `TailReclaimAdd` is the later, more selective add after the market tries
to reverse/repair, installs ZZ, then invalidates ZZ and leaves through the
prior tail. The second archetype is the direct answer to HoldRoot blindness:
HoldRoot should prevent premature A-B-C-D scaling, but it should not suppress a
confirmed C/D-ZZ-C/D reclaim while root is still the risk anchor.

## Local LVN Separator Pass

User refinement tested after the sequence pass: ABCD is only an illustration.
The real structural question may be whether a point-in-time low-volume separator
forms between root A and later participation, or between ZZ and the reclaim
rail. This separator would not be a full-session/day-profile level; it would be
local evidence that A is no longer sitting directly behind the add.

`local_lvn_separator_probe.py` measures:

- Root-to-event corridor profile from root entry to candidate time.
- For tail-reclaim rows, ZZ-to-reclaim gap profile as a second "between events"
  view.
- `local_lvn_separator` when the local bin is <= 35 percent of both median
  corridor volume and flanking peak volume.
- RTH profile ratio only as an ex-post check for whether the node was local-only
  rather than a visible day-profile LVN.

Results:

- 2026-08-27 long: no strong LVN separator appears for an add. The 11:51-11:53
  tail-reclaim rows show only weak local separators around 7733.50-7734.00 or
  7736.00-7736.50, and those rows are either depleted or already harvest-zone.
- 2026-08-27 short: the early 13:44 `SponsorStackAdd` has no root-to-event
  corridor yet; it is a stack/reload/opposition-failure add, not an LVN add.
  The 14:01:13 `TailReclaimAdd` has weak local separator evidence:
  root-corridor 7747.50-7748.00 with local median/neighbor ratios
  0.384/0.477, and event-gap 7743.00-7743.50 with 0.525/5.472. That is
  context, not a standalone permission bit.
- 2026-08-28 short: the strong local-only LVN is real, but it appears after the
  first full add window. Around 11:40:59-11:45:23, the root/event and ZZ/event
  corridors repeatedly select 7763.50-7764.00 with local ratios as low as
  0.108/0.039 and RTH ratios around 0.67. That supports the reduced-add /
  hold-harvest phase, not the earliest 11:34-11:36 full add. The 11:36:16
  `TailReclaimAdd` has no strong LVN separator in this measurement.

Read: the LVN hunch is plausible as an `AddModeEligible` or `RootSeparated`
context bit, but this three-case set does not support making it a required
trigger. Strong local LVNs may arrive after the most efficient full-add window.
The better rule is: if a local separator exists, it can raise confidence or
allow a later reduced add; if it does not exist, a stack/reclaim/reload sequence
can still justify a root-preserving add.

## Afternoon Balance Control Pass

User supplied a negative/control example after the add archetypes: the
2026-08-28 ES short around 7725/7726 near 13:30-14:00. This is the state where
the root idea can still be defensible, but pressing leverage is usually the
wrong inference because price is happy to trade at a HVN/value center.

`afternoon_balance_control_probe.py` tests that case as root-only versus
leveraged/add behavior:

- A root-only short from 13:49:34 at 7726.00 eventually had 13.75 points of MFE
  and only 1.25 points of MAE, reaching the 7716.50 floor at 14:48:56.
- The same trade also repaired to break-even quickly after favorable movement:
  after +2 points, BE returned at 13:52:37; after +4 points, BE returned at
  14:00:43. That makes a leveraged BE scratch a reasonable outcome, not a
  failure to be "fixed" by more add authority.
- From 13:45-14:30 the local profile POC was 7723.50, top HVN band was
  7723.00-7726.50, and 81.3 percent of local volume printed inside 7721-7727.
- LL churn in 7719-7729 showed 48 supply claims, 23 demand claims, 5 supply
  fails, 5 demand fails, and 17 claim-side switches.
- The first two post-balance 5-minute closes below 7720 arrived at 14:25, but
  the next 5-minute close repaired back above 7720 at 14:30. The cleaner lower
  extension did not show until the 14:45-14:55 leg, when it was already late-day
  harvest / no-new-leverage territory.

The important result is that the earlier scale probes emit plausible add rows
inside this churn: 4 `sponsor_stack_add` rows and 4 `add_preserve_root` rows
around 13:50-14:13, plus 2 `add_review` rows. The control overlay suppresses
all of them as `suppress_add_value_churn_root_only`.

Read: this is the missing guardrail on the add policy. `SponsorStackAdd` and
`TailReclaimAdd` should not outrank HoldRoot blindly when the current state is
accepted value/HVN churn. In this state, Kahn should either run root-only
(`max_adds=0`) or treat any discretionary leverage as an explicit BE-scratch
campaign. Do not keep re-adding inside the HVN just because the root eventually
pays. Wait for accepted extension and failed reclaim, or do nothing because the
session has moved into late-day balance/harvest conditions.

## Scale-Out Read

The scale-out side supports Kahn's current passive-harvest philosophy:
do not wait for full opposite ownership before starting to lighten a paid
target. The target floor touch itself should start/continue harvest.

- 2026-08-27 long touched 7743 at 12:34:28.
- 2026-08-27 short touched the 7729.50 floor at 14:26:35; opposite demand
  evidence appeared after that, so waiting for it would have been late.
- 2026-08-28 short touched 7740 at 11:56:40; demand held/consumed evidence
  printed repeatedly from 11:57:26 through 12:05:56, supporting increased
  harvest or retirement after the floor touch.

## Policy Candidate

Do not lower HoldRoot globally. Add a narrow root-preserving press path:

1. Position exists and root risk anchor exists.
2. Campaign plan explicitly allows press/add and has room under max size.
3. Candidate evidence is same-side `RailOwned`, `RailHeld`, or consumed
   ownership inside a press/build-trial/repair-hold waypoint.
4. Waypoint or candidate path requires `preserve_risk_anchor_on_add=true`.
5. Recent rail contact quality is replenished.
6. Either recent opposing rail failure or recent depleted opposing contact is
   present.
7. Target runway and path-consumed gates pass.
8. Value/HVN churn suppression remains above add permission. If the local
   profile is accepting around the participation price, LL claims are two-sided,
   and structural breaks keep repairing, the campaign can hold root but should
   not press leverage.
9. `NoAdd`, `Evaluate`, `Target`, `PathStress`, `Reduce`, `Flatten`, and
   `Retire` priorities remain above this path.

Implementation shape to test later: emit distinct high-priority root-preserving
add decisions only when the relevant sequence gates pass:

- `SponsorStackAdd`: same-side stack renewal with failed/depleted opposition.
- `TailReclaimAdd`: A-B-C-D extension, ZZ repair claim, ZZ invalidation, and
  same-side reclaim/acceptance through the prior D tail.

Current `AllowAdd` priority is below `HoldRoot`, so a plain `AllowAdd` will
still lose the resolver. These paths should sit above `HoldRoot` but below
suppress, tighten-risk, harvest, reduce, flatten, and retire. The child rail
must not become the active risk anchor. A point-in-time local LVN separator can
be a supporting context bit, but not independent add permission.
