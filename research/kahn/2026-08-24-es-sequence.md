# Kahn Probe Map - ESU6 2026-08-24

Purpose: sketch the campaign-governor decisions Kahn would have needed on the
2026-08-24 ES open. This is a research note, not an execution rule.

## Source Boundary

- MarketRecorder has ESU6 2026-08-24 captures, but same-day BubbleTape replay is
  not identity-backed because the relevant `trade_id` MarketRecorder change came
  after the session. Treat any BubbleTape-like read here as Skurry delta/footprint
  proxy plus fallback grouping, not single-participant proof.
- Skurry footprint/profile supplies the early edge/probe read.
- LevelLedger ownership-band replay supplies synthetic rails and the leverage /
  sponsor-risk read.
- ExecAssistantRuntime ES logs under `C:/Users/j/Documents/ExecAssistantRuntime/ES`
  supply the live EAR behavior comparisons for the 09:50-10:20 leg and the
  deferred 10:31/10:35-style reissue.

## Session Context

- ES RTH key levels: IBH `7682.75`, IBL `7655.00`, ONL `7664.50`.
- Skurry classified the open as open-auction.
- 09:30-10:15 profile: total volume `195632`, delta `-6206`, VWAP `7666.85`,
  value `7661.75-7670.75`, POC `7669.25`.
- 09:50-10:05 profile was double-distribution with POC `7669.25`, HVNs
  `7668` and `7664`, and LVN separation around `7667/7671`.
- Full RTH profile later kept `7670` as the main POC/HVN; this supports treating
  the short as an early auction probe, not a durable all-day short by default.

## Synthetic Rails

- `7672.00-7674.50`: supply from demand-consumed evidence, formed `09:32:04`,
  owned `09:33:13`, tested/held on the 10:01-10:03 repair. This is the user
  `674` waypoint.
- `7668.25-7671.25`: supply lean, formed `10:00:06`, owned `10:03:05`.
  Later tests/failures belong to the deferred 10:35-style reissue, not this leg.
- `7669.50-7672.75`: supply from demand-consumed evidence, formed `10:01:35`,
  owned `10:03:05`. Later failure belongs to the deferred reissue.
- `7663.00-7665.50` and `7662.25-7665.75`: supply rails formed around
  `10:02:55` and owned around `10:12-10:13`; by 10:18-10:20 they are
  management objects, not permission for fresh blind leverage.
- `7655.25-7660.00`: demand from supply-consumed evidence, formed `09:44:23`,
  owned `09:46:52`, repeatedly tested/held around `10:09-10:20` in this scope.
- `7659.75-7664.75`: later demand / supply-consumed cluster, formed
  `10:11-10:13`; ownership after 10:20 is deferred evidence.

## Decision Sequence

| Time | Evidence | Kahn State | Decision |
| --- | --- | --- | --- |
| 09:30-09:33 | Open sells from IBH, then LL forms `7672-7674.50` demand-consumed supply | Ready, not armed | Mark `7674` synthetic interest rail. Do not enter yet; require repair/excess back into the rail. |
| 09:40-09:50 | Sell swing to `7655`, delta `-3829`, single-print zone `7655-7657.50` | Context only | Confirms downside potential but also creates lower target/fragility zone. No fresh chase. |
| 09:55-10:00 | Repair stays below `7671`, mixed/positive delta, POC around `7669.25` | Watch repair | Still no add/probe. The auction has not retested the `7674` rail. |
| 10:01 | Price tags `7674.00` on positive delta | Armed probe | Permit small first short if immediate seller excess / failed buyer continuation appears. Stop is builds above the `7674` rail, not generic sponsor noise. |
| 10:02-10:03 | Sharp rejection from `7672` to `7665`; Skurry delta `-715`; LL holds `7672-7674.50` and forms supply around `7668-7672` | Root short active, add locked | Root entry is justified. Do not leverage yet unless `7668` becomes accepted seller claim. |
| 10:03-10:06 | LL owns `7668.25-7671.25` supply; price holds below/around `7664-7665` | Add unlock candidate | First leverage permission can open only after price sustains below `7668`; risk for adds is builds back above `7670/7671`, not unrelated lower sponsors. |
| 10:08-10:15 | Price probes `7661-7659.50`; delta turns positive on repair minutes; demand rail `7655.25-7660` is tested/held | Harvest zone | Reduce or place limit cover at extreme/fragility. Do not wait for sponsor failure to realize edge. |
| 10:15-10:20 | Supply around `7663-7665` remains relevant, but lower demand has already held and repair attempts keep appearing | Tight manage | No new short leverage. Any remaining short needs tight stop/exit on failure to continue below `7660`. A later 10:35-style setup is a fresh reissue, not continuation evidence for this leg. |

## EAR Log Comparison

Actual EAR ES log, `2026-08-24-directive-short-100230-c25742`, covered
`10:02:30-10:32:30` ET with `base_quantity=2`, `add_quantity=2`,
`max_position_quantity=10`, `adds_allowed=true`, `target=7646.75`, execution
policy `NQ_CLASSIC`, `entry_interaction_mode=CLASSIC_PROXIMITY`, and
`semantic_stop_mode=OFF`.

Observed lifecycle:

- `10:03:05`: base short submitted on direct conversion; filled 2 short at
  `7664.75`. Root/support object was `7669.75-7670.00`, so the fill was 20
  ticks below the proof object and roughly 37 ticks below the `7674` waypoint.
- `10:03:51`: add submitted and filled 2 short at `7663.50`; position became 4
  short. This was only 46 seconds after the base fill.
- `10:09:16`: add submitted and filled 2 short at `7661.25`; position became 6
  short while the trade was already entering the `7662-7660` harvest/fragility
  zone.
- `10:12:06`: add submitted and filled 2 short at `7660.75`; position became 8
  short against a new `7663.50-7663.75` consumed-supply sponsor.
- `10:14:38`: `consumed_adverse_claim` and `reference_break_invalidated` fired.
  These were not automatic exits.
- `10:15:02`: Dispatcher cancel flattened 8 long at `7664.50`, cancelled the
  working hard target, and moved runtime from `Leveraged` to `Cancelled`.

Comparison to Kahn:

- EAR waited for proof and entered after displacement; Kahn would allow a smaller
  root probe around the `7674` sweep/failure or back inside the failed supply edge,
  with the root stop tied to acceptance above the parent rail.
- EAR turned each qualifying same-side rail into add permission; Kahn would keep
  add permission locked until seller claims sustained below `7668`.
- EAR added into `7661.25` and `7660.75`; Kahn would treat this area as
  harvest/defense because lower demand was being tested and the downside
  objective/IBL fragility was nearby.
- EAR exit was a manual cancel after adverse/reference events; Kahn needs an
  execution-owned harvest/retirement state so it can reduce risk before sponsor
  failure or manual intervention.

## Deferred Reissue: 10:31-10:51

The same short strategy appears again as `2026-08-24-directive-short-103159-f141b5`.
The log accepted it at `10:31:59` ET, with the same broad short envelope
(`7663.75-7679.50`), same add envelope (`7646.75-7679.50`), and same hard
target (`7646.75`). This is close to the user's 10:35 reissue description.

Market structure was harder than the first leg:

- `10:31-10:37`: Skurry footprint moved `7667.50 -> 7672.50` with delta
  `+720`. EAR evidence showed lower supply failing and demand consuming
  `7664.50-7666.50`. Kahn should not treat this as short permission.
- `10:33-10:35`: parent supply around `7672.50-7673.00` tested and held,
  but this was not enough by itself because buyers were still building above
  `7670`.
- `10:37-10:42`: earlier `7669.75-7670.00` and `7672.50-7673.00`
  supply failed, while BubbleTape replay printed a large BUY bubble at
  `7674.00-7675.50`. This is the difficult part: the short thesis only
  becomes interesting if that buyer assertion becomes trapped/excess.
- `10:43-10:44`: price fell back through `7672/7671`; BubbleTape replay
  printed a smaller SELL bubble at `7669.25-7671.75`; EAR consumed demand
  `7671.75-7673.00` into supply and entered base short.

EAR observed lifecycle:

- `10:44:08`: base short filled 2 at `7669.50`; sponsor
  `7671.75-7673.00`. This was 9 ticks below the proof object, much better
  than the 10:03 first-leg fill.
- `10:46:28`: add filled 2 at `7669.00`; position became 4 short from a
  `7671.50-7671.75` consumed-supply object.
- `10:50:15`: the `7671.50-7671.75` add sponsor failed with price back
  around `7673`; nearby `7671.25-7671.75` supply also failed.
- `10:50:33-10:50:47`: runtime/order reconciliation is messy. The log marks
  the directive completed after a flat reconciliation, then restart protection
  cancels the old target and flattens 4 at `7670.25`. Treat this as an
  operationally noisy protective/scratch exit, not a clean target completion.

Skurry/BubbleTape context for `10:31-10:51`: profile volume `45282`, delta
`+518`, VWAP `7671.08`, value `7669.75-7672.75`, POC `7671.25`,
and HVN `7671.00`. BubbleTape delta replay printed BUY `7674.00-7675.50`
(`+750`) at `10:41` and SELL `7669.25-7671.75` (`-346`) at
`10:43`; fallback trade grouping also found BUY groups at `7674-7675.25`
and a SELL group around `7671.00-7671.50`.

Kahn comparison:

- This was genuinely hard for Kahn because the post-10:31 read is not clean sell
  sponsorship. It is failed-buy/excess at the upper edge followed by a late
  turnover into the `7670/7671` magnet.
- Kahn should probably reject the first 10:33-10:35 holds as insufficient while
  `7669.75-7670.00` supply/demand state is flipping upward.
- Kahn can arm only after the `10:41` buy bubble into `7674-7675.50` fails
  to continue and price falls back below `7672/7671`.
- The actual `10:44` EAR base entry is close to where Kahn could enter if it
  missed the higher edge, but Kahn should stay base-only until sellers sustain
  below `7668`. The `10:46` add at `7669.00` is still too early for
  adaptive leverage.
- Once price reclaims `7671/7673` and the add sponsor fails at `10:50:15`,
  Kahn should scratch/retire rather than keep the hard target alive.

## Post-Scratch Scalp: 10:57-11:25

After the 10:31 reissue scratched/failed, the same broad short strategy was
issued again as `2026-08-24-directive-short-105741-40ef1a`, accepted at
`10:57:41` ET. This is the clearest Kahn motivation: the trade can still
exist, but only as an opportunistic scalp because buyers had already proved they
could appear higher.

EAR observed lifecycle:

- `11:01:33`: base short filled 2 at `7666.75`; sponsor
  `7669.75-7672.50` consumed into supply. This entry is plausible for
  Kahn as a small scalp, not a renewed campaign.
- `11:05:34`: add filled 2 at `7662.75`; sponsor
  `7665.75-7666.00`. The trade is already close to the lower objective
  and should shift toward harvest.
- `11:14:07`: add filled 2 at `7662.25`; position became 6 short.
  The preceding evidence had lower demand `7662.75-7663.00` owned at
  `11:13:30`, so this should be treated as contested, not clean leverage.
- `11:21:27`: add filled 2 at `7658.25`; position became 8 short.
  This is the critical error Kahn is meant to avoid: the new lower sponsor was
  `7660.50-7661.25`, but the fill happened at the low/exhaustion edge.
- `11:23:38-11:23:48`: `7659.75-7660.25` and then
  `7659.75-7661.25` flipped into demand while the `7660.50-7661.25`
  supply sponsor failed. EAR flattened 8 at `7662.75`. The average short
  was roughly `7662.50`, so the full lifecycle became a scratch/slight loss
  even though the base/scalp had real excursion.

Skurry/BubbleTape context:

- `10:50-11:25` profile: volume `63195`, delta `-1021`, VWAP
  `7665.17`, value `7658.25-7668.75`, POC `7663.25`, double
  distribution with HVNs at `7663` and `7670`. This supports a lower
  scalp, not an open runway to `7646.75`.
- `11:02-11:07`: move `7666.75 -> 7663.75`, delta `-606`. This
  validates the scalp direction.
- `11:15-11:25`: price traded `7661.25 -> 7657.75 -> 7665.50`; delta
  only `-178` over the whole window, and the rebound phase `11:22-11:25`
  printed `+753` delta.
- `11:21-11:24`: price opened near `7659.50`, wicked `7657.75`,
  and closed `7663.00` on `+742` delta. That is the below-`7660`
  build failure.
- BubbleTape `10:50-11:25`: SELL bubble at `11:20`
  `7658.25-7661.00` with delta `-826`, then BUY `11:21`
  `7658.00-7658.75` and BUY `11:23` `7662.00-7662.75`. Heavy
  selling below `7660` was absorbed/repaired instead of accepted.

Kahn comparison:

- Permit the `11:01` base short only in scalp posture: root risk above
  `7669.75-7672.50`, expectancy to `7660/7658`, no assumption of a
  full target path to `7646.75`.
- Allow at most one controlled add after `11:05` if sellers sustain below
  `7664`, but move immediately into harvest mode as price approaches
  `7660`.
- Block the `11:14` and especially `11:21` adds unless there is accepted
  business below `7660`. The actual evidence showed test/excess, not
  acceptance.
- Treat the `11:20-11:24` sequence as a mandatory harvest/retire event:
  cover into `7658.50-7660`, then flatten or tighten aggressively on reclaim
  of `7660.75/7661.25`. Do not wait for formal sponsor failure.
- After `11:23:48`, impose a short-side cooldown/retirement condition. The
  `11:24:01` fresh short directive was accepted by EAR, but Kahn should reject
  the same strategy until a new upper-edge trap or fresh downside acceptance is
  proven.

## Long Target-Zone Management: 11:35-12:35

This slice intentionally ignores EAR logs. The imagined position is a long
already held when price clears the earlier `7674-7675` prints. The Kahn
question is not whether longs are valid; it is whether new demand near the
objective deserves more size, or whether the machine should harvest because
large buyers are getting poor reward into target.

Skurry/LL sequence:

- `11:35-11:40`: price moved `7672.50 -> 7674.50`, high `7675.75`,
  delta `+383`. The exact clearance window `11:39-11:41` pushed
  `7673.00 -> 7677.00` on `+924` delta. This validates holding the
  long through the old `7674-7675` prints.
- LL replay showed old supply around `7670-7675.25` failing by
  `11:39-11:40`, and demand ownership behind the move:
  `670.75-673.50` supply-consumed demand and `668-672.50` demand lean.
- `11:45-11:50`: price traded `7676.75 -> 7677.00`, high `7681.50`,
  delta `+832`. BubbleTape printed BUY at `7678.50-7679.75` and a
  large BUY/delta bubble at `7680.00-7680.75`. LL also created demand at
  `7675.25-7676.25` and supply-consumed demand at `7676-7677`.
- Kahn should not automatically add here. The target is already `7680-7685`,
  and new demand is forming above the breakout, close to destination, with
  sellers still answering around `7677-7678`.
- `11:50-12:00`: price churned `7675.50-7680.25` and closed
  `7679.50` with only `+23` delta. That is hold/harvest information,
  not fresh leverage information.
- `12:00-12:05`: strong push `7679.25 -> 7683.75`, high `7686.00`,
  delta `+1824`. LL converted multiple `7676-7679.25` bands into
  demand and failed the small `7680.50-7680.75` supply. This earns a target
  tag, not necessarily more risk.
- BubbleTape at `12:00-12:02`: large SELL at `7678.25-7679.75`, then
  BUY at `7681-7683.50`, then BUY at `7684-7685.50`. Buyers got the
  target, but the buy effort is now occurring at destination.
- `12:05-12:10`: price pulled `7683.50 -> 7679.00` on `-294`
  delta. LL then owned supply at `7682.50-7685.25` by `12:08:28`.
  This is the first clear exit/trim warning for remaining longs.
- `12:20-12:35`: price opened `7684.50`, made `7686.50`, and closed
  `7680.00` on `-1032` delta. LL later owned supply at
  `7685-7686`, then consumed `7682.25-7685.50` into supply by
  `12:31:48`. The target-zone buyers did not create accepted continuation.

Kahn implication:

- Above `7675`, switch from accumulation to target-zone management. New
  supply-consumed demand between `11:45-11:50` is hold support, not automatic
  add permission, because the trade is already approaching `7680-7685`.
- Adds near destination require a different proof standard: not just demand
  ownership, but accepted continuation above the target node, shallow pullbacks,
  and absence of heavy buyer effort with no upward reward.
- If already over-added, Kahn should harvest into `7680-7685`. When large
  buyers appear at `7680-7685` and price cannot extend/hold, reduce or exit.
- Once LL owns `7682.50-7685.25` supply after the target tag, long-side
  continuation should be retired unless price reclaims and accepts above
  `7685/7686`.

## Grammar Gap: Failed Build Trial

This is not a prediction that price must flip at `7660`. The decision question is
whether the market can finally build below a waypoint that has rejected/failed all
morning. While the break is active and price is attempting to sustain below the
waypoint, Kahn has to hold enough exposure to let the trial resolve. The missing
EAR behavior is the fast reaction when the trial shows effort without reward.

For Kahn this should be an explicit state, not a discretionary label:

- Build trial starts when price breaks a known waypoint and creates a same-side
  LL/EAR object below it. In this case the trial was below `7660` with
  lower supply at `7660.50-7661.25`.
- Trial success requires accepted business below the waypoint: continued lower
  prints, lower value/POC migration, sponsor survival on retest, and no quick
  reclaim of the breakdown object.
- Trial failure occurs when large same-side effort cannot move price or hold
  below the waypoint. On 8/24 that was the `11:20` SELL bubble through
  `7658.25-7661.00`, followed by buy response at `7658`, positive-delta
  repair through `7662/7663`, and demand conversion around
  `7659.75-7661.25`.
- Kahn response: block new adds at/below the failed-break low, reduce into the
  break, collapse any deep target to local management, and flatten/tighten on
  reclaim of `7660.75/7661.25`. After failure, short-side continuation is
  retired until a fresh upper-edge trap or accepted sub-`7660` business
  appears.

This is why current EAR is structurally late. EAR saw `7660.50-7661.25`
as a valid same-side sponsor and added at `7658.25`; it reacted only when
that sponsor failed at `11:23:48`. Kahn needs to treat the sell bubble plus
no downward reward as an actionable management event before formal sponsor
failure.

## Kahn Contract Implications

- Early probe permission cannot wait for full LL ownership; it needs a weaker but
  explicit edge object: repair into a predeclared synthetic rail plus failure to
  continue, delta/BubbleTape-style excess, or immediate LL lean.
- Leverage permission should wait for LL/EAR-grade ownership or accepted seller
  claims below a waypoint. In this case, `7668` was the first leverage boundary.
- Stops are phase-specific:
  - Root stop: builds/acceptance above `7674`.
  - Add stop: builds/acceptance above `7670/7671` after leverage below `7670`.
  - Extension stop: failure to sustain below `7660` or lower demand consuming
    the `7659.75-7664.75` area.
- Exit/harvest logic must be independent from sponsor failure. The `7662/7660`
  area created positive-delta repair and LL demand tests before upper supply
  formally failed.
- No extension below `7658` was earned in this sequence. The `7655.25-7660`
  demand rail and the `7655-7657.50` single-print/IBL zone were target and
  fragility, not continuation permission.

## Local Replay Verification

- BubbleTape delta replay 09:55-10:08: one 10:02 SELL bubble, range 7666.00-7669.75, center 7668.25, abs-delta 663. This is delta-proxy evidence, not identity-backed trade grouping.
- LevelLedger local replay 09:55-10:08: supply 668.25-671.25 formed 10:00:06 and owned 10:03:05; supply 669.50-672.75 formed 10:01:35 and owned 10:03:05; prior 672-674.50 supply tested/held into the rejection.
- BubbleTape fallback-trades replay 09:55-10:08 produced non-identity SELL groups at 10:02 around 7668.00-7669.75, 7666.00-7667.75, and 7664.75-7665.75. This agrees with the delta bubble but remains fallback grouping.
