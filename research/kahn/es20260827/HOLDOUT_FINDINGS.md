# ES 2026-08-27 long — holdout test

Provenance: Claude-authored exploratory research. This is evidence for review,
not accepted Kahn policy or live execution permission.

Campaign as declared: long after 11:30 ET at 7728, allowed to scale up to 7730,
harvest above 7743.

Nothing refitted. Rail grading uses the same replenishment threshold (1.012)
and the fill model is unchanged from the 8/28 work.

## Realised path after 11:30

| time | event |
| --- | --- |
| 11:39:15 | first print <= 7730 |
| 11:42-11:44 | every demand rail at 7728-7730 grades **weak** |
| 11:44:03 | first print <= 7728 |
| 11:44:14 | LL demand id24 (score **109.23**) and id25 **FAIL** at 7728 |
| ~11:46 | session low **7722.75** |
| 11:50:21 | supply id37 (score 57.22) grades **weak** — replen 0.947, consumed 1495 |
| 11:52:53 / 11:53:06 | LL supply id39 and id37 **FAIL** — the turn |
| 12:34:28 | first print >= 7743 (target) |
| later | high 7755.50 |

## The grading call, out of sample

Demand rails at the declared entry zone, 11:42-11:44:

| time | band | range | LL score | replen | consumed | grade |
| --- | --- | --- | --- | --- | --- | --- |
| 11:42:26 | 17 | 7723-7731 | 38.36 | 0.864 | 966 | weak |
| 11:42:31 | 18 | 7725.75-7730.75 | 26.28 | 0.889 | 1046 | weak |
| 11:43:20 | 19 | 7727.50-7728.50 | 8.91 | 0.956 | 1131 | weak |
| 11:43:22 | 20 | 7726.25-7728 | 24.57 | 1.002 | 681 | weak |
| 11:44:02 | 23 | 7725.75-7727.75 | 8.08 | 0.997 | 769 | weak |

Every one weak, all being heavily consumed without reloading. LL then failed
id24, id25 and id19 within 90 seconds.

The rails that graded STRONG were **lower**:

| time | band | range | LL score | replen | consumed | grade |
| --- | --- | --- | --- | --- | --- | --- |
| 11:44:03 | 16 | 7724.50-7727 | 30.80 | 1.309 | 0 | STRONG |
| 11:44:03 | 21 | 7725-7727.50 | 17.58 | 1.013 | 348 | STRONG |
| 11:45:04 | 11 | 7723.50-7725.75 | 31.16 | 1.060 | 471 | STRONG |
| 11:45:27 | 10 | 7719-7725 | 45.51 | **1.608** | **0** | STRONG |
| 11:48:30 | 11 | 7723.50-7725.75 | 31.16 | 1.102 | 0 | STRONG |

**Price bottomed at 7722.75 — inside id10's 7719-7725 band.**

So with an unchanged threshold the metric said: the declared 7728-7730 entry is
being consumed and not reloading; the defended demand is 7719-7727. That is
exactly the 6.07 points of adverse excursion the campaign actually took.

Supply side confirms the turn. Rails graded STRONG at 11:32-11:35 (7735-7739),
then flipped weak from 11:41:42. id37 (score 57.22) graded weak at 11:50:21
(replen 0.947, consumed 1495); LL failed it at 11:53:06 — about 3 minutes later.

## Fill simulation

Entry ladder 7730 -> 7728, bids rested 11:35, TTL 28 min: **14 of 14 filled,
average long 7728.82**. Worst excursion to 7722.75 = 6.07 pts = $4,250 open
drawdown on 14 lots.

Harvest, rested 12:30 (target first touched 12:34:28):

| plan | sold | avg sell | pts/lot | realised $ | residual |
| --- | --- | --- | --- | --- | --- |
| flat at 7743 | 14 | 7743.00 | 14.18 | 9,925 | 0 |
| tight ladder (7743-7746) | 14 | 7744.36 | 15.54 | 10,875 | 0 |
| wide ladder (7743-7748) | 14 | 7745.21 | 16.39 | 11,475 | 0 |
| greedy ladder (7743-7755) | 14 | 7749.00 | 20.18 | **14,125** | 0 |
| Kahn BBO clip (today) | **3** | 7743.25 | 14.43 | 2,164 | **11** |

Three things replicate from 8/28: laddering beats the flat target limit; the
greedy ladder wins when the move keeps trending; and Kahn's current passive-BBO
harvest covers a fraction of the position (3 of 14) and leaves the rest open.

The greedy ladder's last two rungs cleared at 13:01 and 13:10 — roughly 30
minutes after the wide ladder finished — so it again bought its extra points
with holding time, which on 8/28 was where the risk lived.

## Caveat that matters

The 1.012 threshold was fitted on the pooled 8/27+8/28 TEST sample, so 8/27 is
**not strictly out of sample for the threshold**. This specific campaign was not
used to fit anything, and the observed separation (0.86-1.00 weak versus
1.01-1.61 strong) is far enough from the boundary that threshold choice does not
drive the call — but a clean holdout needs a day outside the fitted sample, and
GEX history only starts 8/27, so an L2-only holdout on 8/19-8/26 is the next
honest test.
