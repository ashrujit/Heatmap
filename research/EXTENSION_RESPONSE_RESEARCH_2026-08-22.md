# Extension Response Research - 2026-08-22

Research note only. No EAR or LevelLedger runtime change is implied.

## Question

The prior band-role work may have put too much pressure on the band birth
event. A lean band, consumed conversion, or direct conversion is an auction
claim, but it may not be the thing that needs a special hidden classifier.

When price is auctioning higher, sellers are naturally found. They may appear
as:

- a supply lean band;
- demand consumed into a supply band;
- distributed resting offers that get swept rather than forming one clean band;
- a dense sequence of limit orders visible in the book and footprint.

The existence of that supply is normal. The useful question is what longs do
after encountering it.

For a long campaign, the onus shifts to buyers once supply is found:

- If buyers overwhelm supply and keep urgency, higher prices should become
  available and a new same-side anchor or node should start forming.
- If buyers repeatedly test or poke supply but cannot trade away from it, the
  extension inventory is vulnerable even if the older campaign sponsor remains
  alive.

This reframes the old absorption, book-thinning, and restack work. Those
features should be measured around the extension / supply-encounter sequence,
not only at the sponsor or band birth.

## Working Distinction

Do not ask first whether the sponsor is good or bad. Ask whether the extension
after a supply encounter was confirmed.

### Confirmed Extension

Supply is found, crossed, or formally failed, and then:

- price trades away from the supply rather than only poking through it;
- old child prices stay mostly unavailable;
- a higher same-side demand object or accepted node forms;
- same-side depth/restack appears at or above the new area after first attack;
- later repair tests the new area or prior reference without reopening old
  prices too easily.

### Failed Or Unconfirmed Extension

Supply is found and may even be crossed, but then:

- there is no meaningful urgency beyond the supply;
- the same supply area is tested repeatedly;
- the promoted child or thin node is reopened from above;
- demand children fail top-down;
- counter supply reappears or owns beneath the high;
- the older campaign sponsor may remain alive, but tactical extension inventory
  should be treated as paid/reduced, not campaign-core.

## Labels For The Next Pass

- `supply_encounter_no_escape`: supply is touched/crossed/failed, but price does
  not trade away. Repeated high tests and old-price reopen dominate.
- `supply_encounter_escape`: supply is touched/crossed/failed and price
  migrates. Higher demand or accepted business forms before old prices reopen.
- `thin_sweep_unconfirmed`: distributed resting supply is swept through thin
  prints, but no higher same-side sponsor or node forms.
- `thin_sweep_node_confirmed`: thin sweep is followed by a higher node/sponsor
  that survives first attack or repair.
- `thin_sweep_node_failed`: thin sweep is followed by a higher node/sponsor
  attempt that fails; repair is expected.
- `repair_confirmed_continuation`: after a stall, older same-side campaign
  sponsor survives repair, counter supply fails on a later attempt, and price
  then migrates.
- `core_alive_tactical_failed`: extension child/top inventory fails, but older
  campaign sponsor remains alive. This is not terminal thesis failure.

Mirror the side definitions for short campaigns later. The immediate focus here
is the 2026-08-21 long reversal after both products sold off on the open.

## 2026-08-21 Specimens

### Open Selloff Baseline

NQ sold off harder and longer. The 09:30-10:20 footprint traded from
`29476.00` to `29228.00`, closed `29229.75`, and had delta `-3404`. LevelLedger
showed repeated intradrive demand failures while supply remained active above.
That is the baseline case where repair-position demand inside a live sell
initiative should not be trusted.

ES sold off too, but stopped earlier and built more accepted lower business.
The 09:30-10:20 footprint traded from `7696.00` to `7676.75`, closed
`7681.75`, with positive delta `+4498` and heavy volume around `7683-7688`.
That context made later ES lower demand more campaign-like than the first NQ
reversal shelves.

### NQ 11:00 Stall - Supply Encounter No Escape

NQ first gave buyers a valid reversal base, then immediately exposed the
extension problem.

- Demand `29331.75-29332.25` owned at `11:00:49`, held the first repair at
  `11:01:59`, and held again at `11:21:19`.
- Supply `29346.00-29348.50` owned at `11:01:45`, held tests at `11:02:40` and
  `11:02:54`, then failed at `11:03:39`.
- Supply `29358.00-29362.50` owned at `11:05:29`, held at `11:06:42`, then
  failed at `11:07:20`.
- The higher demand child `29360.75-29361.75` failed at `11:09:03`.
- Demand `29349.00-29354.00` later failed at `11:16:58`.
- Demand `29342.25-29342.50` failed at `11:18:57`.

The 10:55-11:20 footprint reached `29368.75`, but closed `29341.75` with delta
`-209`. Volume concentrated around `29348-29364`, not above the extension. This
is not a special bad-band problem. It is a failed extension response after
supply was encountered. The older base stayed alive; the child inventory did
not deserve campaign authority.

Candidate label: `supply_encounter_no_escape` plus
`core_alive_tactical_failed`.

### NQ 11:20 Continuation - Repair Confirmed Continuation

After the 11:00 stall, NQ repaired back into the older base and then re-extended
successfully.

The 11:20-11:40 footprint traded `29331.50-29444.50`, closed `29442.75`, and
printed delta `+1205`. Demand objects formed higher, including:

- `29364.00-29365.50`, tested and held at `11:30:20-11:30:25`;
- `29364.75-29368.75`, owned at `11:30:48`;
- `29392.50-29394.00`, `29394.25-29399.00`, and later `29410.50-29411.00`.

This is the continuation counterexample. The same campaign that should have
paid or reduced tactical inventory at 11:00 still had a valid continuation
after repair confirmed the older base and higher sponsorship emerged.

Candidate label: `repair_confirmed_continuation`.

### NQ 11:40-12:00 - Thin Extension Node Failed

The late NQ extension showed the failure mode again, more cleanly.

- Supply `29464.25-29465.00` and `29467.50-29468.50` failed at
  `11:51:45-11:51:49`.
- Demand appeared higher at `29468.00-29470.50` and `29474.00-29474.25`.
- Demand `29474.00-29474.25` failed at `11:54:50`.
- Demand then failed top-down: `29468.00-29470.50` at `11:55:22`,
  `29463.00-29464.75` at `11:55:31`, `29458.00-29458.25` at `11:56:46`,
  `29452.50-29453.75` at `11:57:03`, and `29448.25-29449.25` at `11:57:48`.
- New supply owned the repair: `29478.75-29484.25` at `11:54:52`,
  `29472.25-29474.75` at `11:55:25`, `29457.50-29458.25` at `11:57:12`, and
  `29449.75-29452.25` at `11:57:59`.

The 11:40-12:00 footprint reached `29488.75` but closed `29443.00` with delta
`-936`. The high-area demand/node failed and repair was warranted.

Candidate label: `thin_sweep_node_failed`.

### ES 11:00 Stall And 11:35 Continuation

ES showed the same structure with a cleaner campaign base.

- Demand `7690.25-7696.50` owned at `11:06:23`, was tested at `11:06:48`, and
  later held at `11:34:46`.
- Supply `7696.25-7698.75` owned at `11:09:38`, held at `11:13:24`, then
  failed at `11:34:57`.
- Demand `7691.75-7694.50` failed at `11:19:39`, but that did not kill the
  older campaign base.
- After the later supply failure, broad demand `7690.50-7698.00` was consumed
  into ownership at `11:35:15`.

The 10:55-11:20 footprint reached `7699.75` but closed `7691.50` with delta
`-787`, so the first objective-extension inventory was vulnerable. The
11:20-11:40 footprint then closed `7705.75` with delta `+5086`, confirming the
later continuation attempt.

Candidate labels: first `core_alive_tactical_failed`, then
`repair_confirmed_continuation`.

### ES 11:45-12:00 - High-Area Node Pending

ES was less terminal than NQ near noon.

- Supply `7708.25-7709.25` owned at `11:48:53` and failed at `11:51:54`.
- Demand `7705.50-7708.50` owned at `11:51:57`.
- Broader demand `7700.50-7709.50` and `7701.50-7709.50` owned at `11:52:26`.
- These demand objects were tested by `11:55-11:56` but had not failed by noon.

The 11:40-12:00 footprint traded `7704.75-7714.00`, closed `7707.25`, and had
nearly neutral positive delta `+299`, with dense volume at `7708-7709`. This
was a high-area node pending further proof, not the same top-down node failure
that NQ printed.

Candidate label: `thin_sweep_node_confirmed_or_pending`, pending later data.

## Probe Design

The next research pass should anchor on supply encounters in a long context,
not on all same-side sponsors. For shorts, mirror the logic later.

### Encounter Sources

- LL supply lean bands during a long campaign.
- LL demand-consumed bands that become supply.
- Distributed resting supply sweeps from raw `book_events`, even when no single
  clean LL supply band forms.
- Footprint levels where asks are crossed in a sparse or single-print manner.

### Extension Response Fields

For each encounter:

- `encounter_type`: `supply_lean`, `demand_consumed_supply`,
  `distributed_resting_sweep`, `footprint_supply_node`.
- `attempt_index_at_high`: first attempt, second attempt, later attempt.
- `prior_same_side_campaign_live`: whether older demand remains alive.
- `extension_inventory_distance`: distance from older sponsor / root to current
  extension area.
- `old_price_reopened`: whether price reaccepted inside the prior child or
  below the extension sponsor.
- `repeated_high_test_count`: number of tests/pokes of the same upper supply
  area without escape.
- `higher_same_side_anchor_formed`: whether demand forms above the encountered
  supply.
- `higher_anchor_survived_first_attack`: whether that demand survives first
  meaningful repair.
- `node_volume_after_sweep`: volume built at or above the swept area.
- `node_delta_after_sweep`: whether higher business is supported by aligned
  aggression or only passive absorption.
- `top_down_child_fail_sequence`: whether demand fails from the high downward.

### Book / Absorption / Restack Fields

These are the fields that should move from band-birth evaluation to
extension-response evaluation:

- ask-side thinning ahead of/through supply during a long extension;
- ask restack above the swept area after the sweep;
- bid restack at the new higher area after first attack;
- same-side depth change at the child after first touch;
- opposite-side absorption at the high after repeated tests;
- whether disappeared liquidity was explained by aggressive tape or by passive
  pull/thinning;
- whether dense resting supply is replaced higher, or whether the book becomes
  thin with no accepted node.

### Output Classification

The probe should produce rows for supply encounters, then label the outcome as
one of:

- `supply_encounter_escape`;
- `supply_encounter_no_escape`;
- `thin_sweep_unconfirmed`;
- `thin_sweep_node_confirmed`;
- `thin_sweep_node_failed`;
- `repair_confirmed_continuation`;
- `core_alive_tactical_failed`.

## Provisional Trading-System Interpretation

Not an implementation instruction.

EAR currently behaves as if a promoted sponsor can simply be watched until it
formally fails. The revised hypothesis is that promotion after an extension
supply encounter needs post-event acceptance evidence.

If upper supply is encountered, crossed, or even formally failed, but price
cannot trade away and old child prices reopen, tactical extension inventory
should be paid or reduced near the top. That does not imply a short or campaign
failure. It means the system should wait for repair confirmation before treating
the next same-side band as campaign authority.

If a thin sweep through supply produces a higher node or same-side anchor that
survives attack, continuation can be trusted again. If that node fails, repair
is expected and the lower sponsor is at risk of being tested.

## Near-Term Falsifiers

- If repeated high tests without escape still continue cleanly across more
  sessions, then the repeated-test warning is descriptive only.
- If thin sweeps without higher node formation do not produce repairs, then the
  node requirement is too strict.
- If higher nodes fail as often after dense accepted business as after thin
  sweeps, profile density is not doing useful work.
- If older sponsor live / same-side protection does not explain campaign
  survival after child failure, then `core_alive_tactical_failed` is too broad.
- If ES and NQ diverge systematically, the rule may be product-specific pacing
  and sizing rather than shared auction grammar.
