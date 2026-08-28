# 2026-08-27 GexBot / Kahn Decision Study

Question: can intraday GexBot data improve Kahn probe, add, and harvest decisions?

Status: research inventory only. This note is not a policy-change proposal and
does not imply Kahn should ingest GEX live yet. The purpose is to separate:

- where 2026-08-27 GEX adds information beyond LL/Skurry/BubbleTape,
- where older auction maps show the same Kahn management failure mode without
  GEX proof, and
- what offline replay hypotheses are worth testing before any runtime change.

## Data Used

- Kahn runtime decision logs: `C:\Users\j\Documents\KahnRuntime\ES\decisions.jsonl` and `C:\Users\j\Documents\KahnRuntime\NQ\decisions.jsonl`.
- GexBot cache: `GexBotMcp/out/gexbot.sqlite`; 2026-08-27 had minute-level `ES_SPX` and `NQ_NDX` rows from RTH open forward.
- Skurry profiles, VWAP, candles, and aggregate footprint for exact campaign windows.
- BubbleTape replay over MarketRecorder tick captures. Replay found no identity-backed trade IDs, so BubbleTape observations below are fallback price/time or delta-group evidence, not exchange trade-id grouped executions.

Kahn did not poll GexBot directly in the live runtime. GEX influence today was through manually prepared campaign waypoints; this study joins the cached GEX timeline afterward to test whether those waypoints and management choices were improved by GEX context.

Generated artifacts:

- `research/kahn/out/2026-08-27-gex-kahn/summary.md`
- `research/kahn/out/2026-08-27-gex-kahn/campaign_loads.csv`
- `research/kahn/out/2026-08-27-gex-kahn/policy_runs.csv`
- `research/kahn/out/2026-08-27-gex-kahn/key_decisions_gex_join.csv`
- `research/kahn/out/2026-08-27-gex-kahn/gex_wall_changes.csv`
- `research/kahn/out/2026-08-27-gex-kahn/counterfactual_summary.md`
- `research/kahn/out/2026-08-27-gex-kahn/counterfactual_add_candidates.csv`
- `research/kahn/out/2026-08-27-gex-kahn/probe_entry_mode.csv`
- `research/kahn/out/2026-08-27-gex-kahn/synthetic_es_long_original_like.report.md`
- `research/kahn/out/2026-08-27-gex-kahn/synthetic_es_long_original_like.decisions.jsonl`
- `research/kahn/out/2026-08-27-gex-kahn/synthetic_es_long_original_like.campaign.json`
- `research/kahn/out/2026-08-27-gex-kahn/synthetic_es_long_post_7728.evidence.jsonl`
- `research/kahn/out/2026-08-27-gex-kahn/exit_variability_summary.md`
- `research/kahn/out/2026-08-27-gex-kahn/exit_short_harvest_gex.csv`
- `research/kahn/out/2026-08-27-gex-kahn/exit_short_harvest_events.csv`
- `research/kahn/out/2026-08-27-gex-kahn/exit_short_harvest_1m_bars.csv`
- `research/kahn/out/2026-08-27-gex-kahn/exit_long_near_harvest_gex.csv`
- `research/kahn/out/2026-08-27-gex-kahn/exit_long_near_harvest_events.csv`
- `research/kahn/out/2026-08-27-gex-kahn/exit_long_near_harvest_1m_bars.csv`
- `research/kahn/out/2026-08-27-gex-kahn/bubble_es_0954_1008.csv`
- `research/kahn/out/2026-08-27-gex-kahn/bubble_es_1200_1330.csv`
- `research/kahn/out/2026-08-27-gex-kahn/bubble_nq_1001_1015.csv`
- `research/kahn/out/2026-08-27-gex-kahn/bubble_nq_1052_1131.csv`
- `research/kahn/out/2026-08-27-gex-kahn/bubble_es_1330_1432.csv`
- `research/kahn/out/2026-08-27-gex-kahn/gex_overlay_hypothesis_report.md`
- `research/kahn/out/2026-08-27-gex-kahn/gex_overlay_harvest_decisions.csv`
- `research/kahn/out/2026-08-27-gex-kahn/gex_overlay_add_decisions.csv`
- `research/kahn/out/2026-08-27-gex-kahn/gex_overlay_probe_order_mode.csv`

## Kahn Decision Inventory

The refreshed join found 9,622 2026-08-27 log rows, 1,078 policy decisions, and 15 broker-affecting policy decisions:

- `AllowProbe`: 8
- `Flatten`: 5
- `Reduce`: 1
- `Retire`: 1
- `AllowAdd`: 0

The lack of live `AllowAdd` decisions matters for the actual-decision read, but it is not the end of the add question. The counterfactual pass treats same-side `HoldRoot` and same-side LL evidence suppressed by `no_add_zone` / `evaluate_zone` as add candidates. That asks the better question: not "did Kahn add," but "where did Kahn see evidence that could have been converted into scale, and did GEX separate good adds from bad ones?"

## Policy Surface

The current policy shape explains why adds were absent. `CampaignPolicyEngine.CreateDefault()` evaluates `NoAddZone`, `EvaluateZone`, `PathStress`, `TargetZone`, `BuildTrial`, `RepairHold`, `TrapProbe`, then `Press`. `DecisionResolver` priorities put `SuppressAdd=700`, `HoldRoot=500`, and `AllowAdd=320`. `PressPolicy` can convert same-side LL ownership into `AllowAdd`, including near a `BuildTrial` waypoint, but a simultaneous `BuildTrialPolicy` `HoldRoot` outranks it. The live adapter also routes both `AllowProbe` and `AllowAdd` through market orders today.

So the implementation issue is not "let GEX permit adds." It is whether Kahn needs a deterministic conversion state: same-side LL evidence first proves the root/build, then a later or stronger event can become `AllowAdd` only if GEX/path context says there is enough runway and no nearer destination/stress.

## Evidence Inventory

### Probe

GEX helped most with probe location selection in the ES 13:37 ET short, not with probe permission.

At 13:38 ET, `ES_SPX gex_zero` had `call_wall=7753.94`, `oi_call_wall=7753.94`, `zero_gamma=7729.19`, and `oi_put_wall=7728.94`. Kahn allowed the short probe at 13:39:03 ET at `7748.75`, but the action was still authorized by `LevelLedger RailHeld Supply`, not by GEX. Skurry/BubbleTape validation supports the location: the 13:34-13:41 ES footprint opened `7751.50`, never traded above it, closed `7749.75`, and had `delta=-277`; BubbleTape replay printed a 13:40 sell bubble across `7748.25-7749.50`.

The early ORR probes were much less persuasive as GEX examples. ES and NQ both had fast open wall/zero-gamma movement, no normal-strength BubbleTape bubbles in the exact early windows, and Kahn decisions were dominated by LL rail ownership/failure. Treat the first 5-15 RTH minutes as too unstable for GEX to independently improve probe selection without strong auction confirmation.

For failed probes, the useful new question is entry mechanics. The `probe_entry_mode.csv` pass found that 1-2 tick better limits were touched quickly on every actual probe tested. That would not have fixed wrong probes: ES 09:54, NQ 10:01, ES 10:01, and NQ 11:25 still failed, but a better limit would have reduced realized loss. On the winners, the same mechanic would usually have improved entry too: ES 13:39 short touched a 1-tick better short limit after 0.103s and a 2-tick better limit after 14.783s; NQ 10:07 touched 1/2/4-tick better long limits after 0.075s.

This is touched-price analysis, not queue-proof. Still, it argues for testing a limit-first probe mode: place a 1-2 tick better limit with a short TTL, then chase with market only if the original evidence is still valid and price is leaving the area. Market entry should be reserved for urgency cases where missed participation is worse than price concession; trap/failure probes around walls or value edges should probably default to limit-first.

### Add

There was no live `AllowAdd` decision on 2026-08-27, but the counterfactual set found 21 same-side moments that could have been reviewed as adds. GEX was useful as a quality separator.

Best add candidates:

- ES ORR long, 10:23:18 and 10:35:36 ET. Same-side demand was suppressed inside the no-add corridor at `7725.25` and `7727.5`. The 10:35 candidate had 30m MFE `11`, 30m MAE `3`, and was only `0.54` points under the `oi_put_wall` near `7728.04`. This looks like the actual "buy after failed short campaign during IB to upper wall" scale point: not the first probe, but the conversion after the 7728 area began to behave as accepted support/runway.
- ES PM short, 13:44:34-13:44:57 ET. Same-side supply around `7749.5`, `7748.25`, and `7747.75` was logged as `HoldRoot` at the build waypoint. Those candidates had 30m MFE `17-18.75` and MAE `0.25-0.5`, with the `call_wall` still above at `7753.94`. BubbleTape had already shown selling around the failed upper area. This is the cleanest missed scale family from the day.

Synthetic ES long replay: current code no longer lets campaign expiry kill active management, but an original-like replay of the 10:07 ES long still did not allow an add past `7728`. It produced three `SuppressAdd` decisions from the `no-add-7716-7728` corridor at 10:37-10:38 ET, then a `Reduce` at 10:38:42 ET on opposite supply around `7730.75` mapped as path stress. Because the original ES long campaign JSON had been overwritten by the later short, this is a reconstructed test from surviving notes/logged waypoint IDs, not a byte-identical replay of the live directive.

ES short clarification: the above-`7738` missed candidates were not blocked by the `no-add-7728-7738` waypoint. They were same-side supply events inside both the press/build area; `BuildTrialPolicy` emitted `HoldRoot`, and resolver priority made that outrank the lower-priority `PressPolicy` `AllowAdd`. Below `7738`, the no-add/evaluate/path-stress suppressions behaved as intended.

Keep-suppressed candidates:

- ES 09:54 same-side no-add candidates at `7723.75` / `7724` were too early and still under the relevant OI put wall by about 5 points. 30m MAE was `16.5+`. GEX argues against scale there.
- NQ 11:26:30 same-side demand at `29589.75` had 30m MAE `78.25` after the GEX map had just shifted down. This is `MapChanged` / `SuppressAdd` / `TightenRisk`, not add.
- NQ 10:12-10:14 same-side demand had large MFE but also large MAE and sat into/above an OI wall. It may support a quick-harvest add experiment, but not normal campaign leverage.
- ES 14:10-14:25 shorts near `7734` down to `7731` worked on MFE, but they were already near zero-gamma / OI put target. These remain harvest/path-stress candidates unless a separate continuation-add rule is intentionally modeled.

The useful signal was negative: GEX-shaped no-add/evaluate/path-stress zones kept Kahn from scaling after price left the origin. The cleanest example is NQ post-IB. The long campaign probed at 10:57:18 ET near `29584.75`, then repeatedly suppressed adds through the `29572-29616` no-add/evaluate region. At 11:03:42 ET Kahn reduced to flat on `LevelLedger RailOwned Supply` near the evaluate band.

The later NQ second probe also argues for `MapChanged` / suppress-add behavior, not permissive adds. At 11:25 ET, `NQ_NDX gex_zero` shifted `call_wall` from `29664.56` down to `29614.56` and `zero_gamma` from `29589.48` down to `29529.59`; Kahn allowed a probe at 11:25:59 ET on LL demand hold, then flattened at 11:29:34 ET when the demand rail failed at `29577.5`. BubbleTape replay for 11:20-11:31 had a sell delta bubble around `29574-29579.75`, aligned with the failure area.

### Ignored Post-Noon ES Buy

GEX framed the ignored 12:00-13:30 ES buy idea well, but did not solve the confidence problem. Around the window, the map supported a path from the `7728-7730` support/zero area toward `7749-7754` call-wall / OI-call-wall resistance. BubbleTape showed buy bubbles during the 12:25-12:35 reclaim, especially 12:30 at `7742.00-7743.25` with delta `+635`. But the destination area later showed heavy sell pressure: 13:05 printed a sell delta bubble across `7752.00-7753.75` with delta `-1598`, plus sell trade bubbles at `7752.25`, `7753.50`, and `7753.75`.

That supports the user's live hesitation. The branch could have been modeled as a low-confidence probe after the reclaim, with quick harvest into `7750-7754`. It should not have been modeled as an add/leverage campaign from GEX alone.

### Harvest

Harvest is the strongest 2026-08-27 use case.

The ES short's target `7728-7729.50` was already aligned with `zero_gamma` / `oi_put_wall` near entry: at 13:38 ET, `zero_gamma=7729.19` and `oi_put_wall=7728.94`. Kahn then refused adds through evaluate/no-add/path-stress as price worked lower. At 14:31:48 ET, Kahn retired the short at `7729.0` on `LevelLedger RailOwned Demand`; the latest prior `gex_zero` snapshot had `oi_put_wall=7728.01`. Skurry footprint for 14:23-14:32 had positive delta into the target area (`delta=+492`) and large volume at `7728` / `7726`, consistent with harvesting into opposing demand rather than extending.

The exit-variability pass makes that less like luck. The `gex_zero` OI put wall stayed essentially fixed at `7727.95` / `7728.01` from 14:18-14:32 ET while price moved into and through it. `sum_gex_vol` flipped from `+49,200` at 14:24:38 to `-10,108` at 14:26:42, then `-61,276` at 14:27:44 and `-141,451` at 14:29:51. After the 14:29-14:31 response, it recovered toward `-35,318` and then positive by 14:32:58. MarketRecorder 1m ticks show the move traded through the target: 14:27 low `7726.25`, 14:28 low `7724.25`, 14:29 low `7723.75`, followed by positive delta at 14:30 (`+719`) and 14:31 (`+421`). A passive buy-to-cover harvest staged into the `7728-7729.50` objective would likely have traded on touched-price evidence, though queue fill is not proven.

The missed ES long exit is the opposite case and is probably the better example of GEX reducing variability. The current LL math needed auction failure; the actual failure evidence came late and lower. MarketRecorder shows the high-area touch peaked at `7742.75` from 11:17-11:19 ET, one tick under the user's `7743` harvest and about 1.1 points under the stable `gex_zero` call wall at `7743.84`. Volume was not an excess expansion: the 11:17 bar volume percentile was about `50%`, 11:18 about `43%`, and 11:19 about `35%` of RTH 1m bars. LL did not print a decisive seller claim at `7742`; the first meaningful supply ownership came later near `7739.25-7739.50` at 11:25:34, then stronger supply around `7737-7738.25` / `7735.75-7736.75` into 11:29-11:30. A Kahn exit waiting for LL failure would likely have harvested materially lower.

So the rule to test is not "exit because GEX changed." It is "when price enters a predeclared GEX-derived terminal zone or reaches a configured near-miss distance from a stable wall, begin passive harvest or tighten aggressively even without an opposing LL claim." For the short, that means staged passive cover into `7728-7729.50`; for the long, it means not requiring a literal `7743` limit fill if the auction reaches `7742.75` against a stable `7743.8` wall on mediocre volume and no fresh sponsorship.

## Cross-Map Controls

The older Kahn replay maps do not prove GEX usefulness because intraday GEX
history is only available for 2026-08-27. They do show whether the same decision
problem repeats without GEX:

- ES 2026-08-24 short 09:50/10:57 maps: Kahn needs harvest/retire behavior
  before formal sponsor failure when same-side selling reaches a lower objective
  and gets absorbed. The 10:57 scalp allows one controlled add, then suppresses
  later adds near `7660` and retires on sell effort with no reward.
- ES 2026-08-25 mean-revert map: edge-only short entry is valid, but demand
  failure in the body supports hold, not worsening average. `7684` is a pay zone;
  continuation to `7680` requires renewed failure, not hope.
- ES/NQ 2026-08-26 reversal maps: after no-add/evaluate corridors, adds only
  occur once accepted same-side demand forms beyond the conversion boundary.
  Target-zone absorption then reduces, and opposite ownership retires.
- NQ 2026-08-25/26 short maps: good adds happen near early accepted continuation
  below the broken area, while target-zone evidence becomes harvest. This matches
  the ES pattern and argues against a broad "same-side LL equals add" rule.

Control read: the recurring Kahn problem is not simply finding more same-side
evidence. It is deciding when same-side evidence means `add`, when it means
`hold root`, and when it means `harvest because destination is being paid`.
GEX can only be useful if it reduces that classification ambiguity.

## Offline Overlay Pass

`evaluate_gex_overlay_hypotheses_20260827.py` adds one more descriptive pass:
it classifies Kahn-observed evidence through a GEX management overlay without
adding runtime policy. Inputs are existing 8/27 research CSVs plus
MarketRecorder touched-price checks.

Counts:

- Harvest overlay rows: `7`
  (`stage_passive_harvest=4`, `test_nearmiss_reduce=2`,
  `tighten_no_passive_fill=1`).
- Add candidate rows: `21`
  (`test_holdroot_to_add_conversion=3`,
  `arm_wall_conversion_pending_acceptance=2`,
  `keep_suppressed_terminal=8`,
  `keep_suppressed_path_variance=4`,
  `review_possible_add=1`,
  `keep_suppressed_or_review=3`).
- Probe rows: `8`
  (`test_limit_first_loss_reduction=4`,
  `test_limit_first_variance_reduction=3`,
  `market_or_one_tick_urgency=1`).

Harvest overlay:

- ES long near `7743`: exact `7743.00` was not touched, but `7742.75` touched
  at `11:17:09` and `7742.50` touched at `11:17:00`. That supports a
  near-miss reduce/tighten test, not a claim that the original limit would have
  filled.
- ES short into `7728-7729.50`: after the `14:26:42` GEX trigger, passive cover
  limits at `7729.50`, `7729.00`, `7728.50`, and `7728.00` all touched between
  `14:26:48` and `14:27:15`, about `4.5-5.0` minutes before Kahn's logged
  `14:31:48` retire. This is touched-price only, not queue-fill proof.

Add overlay:

- The ES short 13:44 family becomes the cleanest add-conversion test:
  `7749.50`, `7748.25`, and `7747.75` were `HoldRoot` rows with
  `17-18.75` points of 30m MFE, `0.25-0.50` MAE, failed upper-wall source
  context, and about `18.8-20.6` points of runway to the OI put wall.
- The ES long 10:23/10:35 family is not immediate add permission. It is better
  described as `arm_wall_conversion_pending_acceptance`: same-side demand was
  appearing near the `7728` OI put wall, but the evidence prices were still
  under the wall by `2.87` and `0.54` points. The next question is whether Kahn
  should arm a conversion add and require acceptance above/against `7728`.
- The ES short 14:01 row remains review, not a clean add. MFE/MAE was excellent,
  but the nearest GEX context was zero-gamma about `7.14` points ahead and the
  target OI put wall was only `12.97` points away.
- The ES short 14:14/14:24/14:25 rows stay suppressed because they were within
  about `3-4` points of the OI put destination.
- NQ remains mostly negative evidence for adds: the early long candidates were
  too close to upper OI/call walls, and the 11:26 candidate had excessive
  adverse excursion.

Overlay read: harvest is ready for a replayable candidate rule; adds need a
conversion-state test; probe order mode should stay behind those two.

## Hypotheses Still To Test

1. GEX waypoint ranking:
   - Let GEX rank or tighten candidate `trap_probe`, `target`, `evaluate`, `no_add`, and `path_stress` waypoints.
   - Do not let GEX create `AllowProbe` or `AllowAdd` without LL, footprint, BubbleTape, price acceptance, or explicit campaign evidence.

2. Probe quality filter:
   - If a probe zone is within a configured distance of a stable call/put/OI wall and Skurry/LL/BubbleTape shows rejection/failed claim, mark the probe as higher quality.
   - Penalize or ignore this during the first 5-15 RTH minutes unless the wall is stable across consecutive snapshots and `gex_zero` / `gex_full` agree.

3. Add suppression:
   - If an open position is approaching a GEX wall, zero-gamma, or OI wall mapped as `evaluate` / `target`, suppress adds unless LL sponsorship remains strong and price is still near the origin/build zone.
   - If a relevant wall relocates materially toward price or against the campaign while in `ProbeOpen` / `BuildTrial`, emit `MapChanged` / `SuppressAdd` / `TightenRisk`, not `AllowAdd`.

4. Harvest acceleration:
   - If target/evaluate zone overlaps a GEX wall or zero-gamma and opposing LL ownership or BubbleTape opposing pressure appears, prefer `Reduce` / `Retire`.
   - ES 14:31 ET is the model case from this sample.

5. Category weighting:
   - Favor `gex_zero` and `gex_full` agreement for intraday decisions.
   - Treat `gex_one` as lower-confidence for Kahn policy because it was often farther from active price and less useful at the tested decision points.

6. Build-to-add conversion:
   - Add an offline-only candidate rule that can convert `HoldRoot` into `AllowAdd` after a same-side LL rail survives or upgrades, but only when target/evaluate/path-stress zones are not immediately ahead.
   - Require GEX runway: either price has accepted beyond a source wall that now supports the campaign, or the nearest adverse wall/zero/target is far enough away to justify add risk.
   - If a wall relocates against the campaign during `ProbeOpen` / `BuildTrial`, suppress or tighten; do not convert.
   - Preserve root risk on the first conversion add unless the child sponsor tightens, rather than widens, campaign risk.

7. Probe order mode:
   - Test `limit_first` for trap/failure probes: 1-2 tick better limit, short TTL, then optional market chase only if the evidence remains fresh.
   - Keep `market` for explicit urgency cases: price leaving a reclaimed wall/zero boundary with strong LL sponsorship and no nearby destination.

## Current Research Posture

The strongest evidence so far is for harvest/exit variability. The ES short
exit near `7728-7729.50` aligned with a stable OI put wall and later LL demand;
the ES long near-miss around `7742.75` shows the opposite problem, where waiting
for LL failure probably exits materially lower than the predeclared GEX-derived
terminal area.

The add evidence is mixed. ES has two useful families to investigate: the
post-`7728` long conversion candidates and the 13:44 short `HoldRoot` candidates
above the lower no-add zone. NQ is the warning case: same-side LL evidence
often had large MFE but unacceptable MAE or sat too close to upper-wall stress.

Root-probe defensiveness is last priority. The touched-price check says
`limit_first` might reduce variance, but it does not solve wrong-probe selection
and the ES short entry remains an urgency exception.

No Kahn runtime change should follow directly from this note. The overlay pass
has narrowed the next replay target: encode synthetic context-marker evidence
for terminal harvest/near-miss and build-to-add conversion, then compare cloned
campaigns against baseline before considering any live integration.
