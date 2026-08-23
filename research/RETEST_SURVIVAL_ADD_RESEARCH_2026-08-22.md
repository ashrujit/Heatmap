# Retest Survival Add Research - 2026-08-22

Research note only. No EAR implementation change is implied.

## Question

What if a long directive continues recording newly formed demand bands, but
does not add immediately on band creation? Instead, after the first/base entry,
new demand bands become add candidates only after their first retest survives.

This targets the observed problem where a band forms during fast extension,
EAR triggers while current price is already near the distance limit, and market
execution fills another 20-60 ticks away from the band.

## Probe

Script:

- `research/retest_survival_add_probe.py`

Outputs:

- `research/out/retest_survival_add_2026-08-21_1020_1200/`
- `research/out/retest_survival_add_2026-08-21_1025_1200/`

The probe replays LevelLedger ownership transitions and labels long-side demand
bands by first retest outcome:

- `first_retest_survived`
- `first_retest_failed`
- `tested_unresolved`
- `no_retest_before_end`

It uses creation distance `0-20` ticks beyond the band as a proxy for rows that
would have been immediately eligible under a chase-style add rule. This is not
a fill-accurate EAR backtest.

## 10:25-12:00 Result

The 10:25-12:00 ES/NQ pass produced `58` demand-extension rows:

- `first_retest_survived`: `25`
- `no_retest_before_end`: `21`
- `first_retest_failed`: `9`
- `tested_unresolved`: `3`

For immediate-eligible rows only:

- `first_retest_survived`: `16`
- `no_retest_before_end`: `12`
- `first_retest_failed`: `4`
- `tested_unresolved`: `3`

Read: a strict first-retest-survival rule would have taken less than half of
the immediate-eligible add candidates (`16/35`) and skipped `19/35`. That is
directionally useful for reducing chase inventory, but it is not a complete
position-management rule.

## Useful 8/21 Examples

### NQ 11:02 Fragile Child Would Not Be Added Immediately

The actual EAR add around `11:02` promoted a child near `29338.25-29340.25` and
filled around `29345`, with root distance `19` ticks. The sponsor consequence
probe showed quick old-price reopen, same-side depth loss, and
`passed_through_no_restack`.

Under the retest-survival lens, the related lower demand did not become a clean
add until after repair:

- `11:20:38` demand `29338.25-29340.75`, first retest `11:20:42`, held
  `11:20:43`, hold-entry distance `10` ticks.

This is the best argument for the mechanism: keep recording the object, but do
not let the first fast child govern added inventory until repair proves it.

### NQ 11:08 / 11:15 Fragile Shelves Filtered

The probe filtered several upper/mid shelves:

- `11:08:27` demand `29360.75-29361.75`, immediate eligible, first retest
  failed at `11:09:03`.
- `11:15:27` demand `29350.75-29353.00`, first retest failed at `11:15:53`.

These match the prior read: the older campaign base could remain alive, but
extension inventory should not have campaign authority.

### NQ 11:29-11:30 Continuation Had A Repair-Survival Add

The mechanism did not miss every good continuation add.

- `11:29:49` demand `29364.00-29365.50`, immediate eligible, first retest
  `11:29:53`, held `11:30:00`, hold-entry distance `12` ticks, MFE to noon
  `476` ticks, MAE `16` ticks.

This is the clean positive example: retest survival allowed an add before the
vertical continuation while keeping the entry tied to a tested object.

### NQ 11:34-11:36 Vertical Adds Would Mostly Be Missed

Several immediate-eligible NQ extension bands did not retest before noon:

- `11:30:48` demand `29364.75-29368.75`, no retest before noon.
- `11:34:41` demand `29392.50-29394.00`, no retest before noon.
- `11:34:58` demand `29394.25-29399.00`, no retest before noon.
- `11:36:51` demand `29401.75-29404.75`, no retest before noon.

Strict retest-only adds would reduce payout in the fastest no-repair segments.
That may be acceptable for a safer EAR add policy, but it is a real tradeoff.

### Late NQ Top Shows Raw HOLD Is Too Weak

The late high-area rows show why `first_retest_survived` cannot mean "safe add"
by itself:

- `11:51:16` demand `29458.00-29458.25`, first retest held, MFE `0` ticks,
  MAE `108` ticks.
- `11:52:22` demand `29468.00-29470.50`, first retest held, MFE `2` ticks,
  MAE `146` ticks.

These rows mechanically held, but they were in a thin/newly auctioned high area
where the extension-response probe already labeled the later structure as node
failure / repair risk. The stronger requirement is not "LL printed HOLD"; it is
"first repair survives with consequence."

## Working Interpretation

The useful mechanism is:

1. Keep recording newly formed same-side bands after the base entry.
2. Do not immediately add to fast extension children.
3. Allow add eligibility when the first retest survives and the response shows
   consequence:
   - old prices do not reopen meaningfully;
   - higher same-side demand chains or survives;
   - opposing supply encountered above fails and price trades away;
   - the location is not already a thin/objective-edge node failure.

This would likely have improved 8/21 management by:

- avoiding the NQ 11:02 add;
- avoiding fragile 11:08/11:15 shelves;
- allowing the cleaner 11:20 repair and 11:29-11:30 continuation add;
- skipping several vertical 11:34-11:36 chase adds;
- still requiring an additional top/extension-response filter to avoid late
  high-area holds that mechanically passed but had poor forward asymmetry.

## Falsifiers

- If no-retest vertical adds are the dominant source of payout across sessions,
  strict retest-only adds may be too conservative.
- If first-retest-survived rows still have frequent large MAE in non-terminal
  locations, LL `HOLD` is too weak as a survival proxy.
- If adding after first repair gives much worse average price but no material
  drawdown reduction, the rule may be comfort rather than edge.
- If late high-area holds can be filtered cleanly by extension-response labels,
  then the combined mechanism deserves a larger replay.
