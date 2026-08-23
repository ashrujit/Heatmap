# Auction Separation Child Research - 2026-08-22

Research note only. No EAR or LevelLedger runtime change is implied.

## Question

FIFO execution means "trim the child" is not a reliable account-level
operation. If a campaign is 2+2 and the account reduces 2, the vendor/broker
may flatten the earlier lot and leave the newer lot. Therefore the research
object cannot be literal parent/child lot identity. It has to be auction
authority:

- `provisional_child`: a fresh/add sponsor that has not proven the auction moved
  location.
- `auction_separated_child`: a fresh/add sponsor that is separated from the
  prior sponsor by a low-interaction pocket and then proves worse-price
  acceptance.

If the child is only provisional, its failure may be a repair/attempt failure
while the older thesis remains alive. If it is auction-separated, then failure
of that upper distribution is a much better argument for all-flat, because the
market has reopened the pocket it had previously skipped/accepted through.

## New Probe

New helper:

- `research/auction_separation_child_probe.py`

Generated outputs:

- `research/out/auction_separation_child_2026-08-21_1020_1200/`
- `research/out/auction_separation_child_2026-08-19_1010_1200/`

8/21 command:

```powershell
uv run --with polars --with tzdata python research\auction_separation_child_probe.py --date 2026-08-21 --windows 10:20-12:00 --symbols ES,NQ --extension-csv research\out\extension_response_2026-08-21\extension_response_rows.csv --out-dir research\out\auction_separation_child_2026-08-21_1020_1200
```

8/19 command:

```powershell
uv run --with polars --with tzdata python research\auction_separation_child_probe.py --date 2026-08-19 --windows 10:10-12:00 --symbols ES,NQ --out-dir research\out\auction_separation_child_2026-08-19_1010_1200
```

Inputs:

- EAR runtime `sponsor_promoted`, `order_submit`, `fill_quality`,
  `sponsor_failed`, and `sponsor_failure_context`.
- MarketRecorder ticks and snapshots.
- Optional join to `extension_response_probe.py` rows for post-child supply
  encounter labels.

Measured fields:

- directive parent, or nearest lower same-side auction parent within 45 minutes;
- parent-child gap in ticks;
- pocket volume, trades, volume/tick, and volume/tick/second between parent and
  child promotion;
- post-child old-price and beyond-price time ratios;
- first old-price reopen delay, same-side depth change after first touch, and
  next same-side sponsor delay;
- formal sponsor failure and failure-context older-sponsor liveness.

Current low-pocket heuristic:

- ES: `<=0.60` contracts/tick/second through the parent-child pocket.
- NQ: `<=0.15` contracts/tick/second through the parent-child pocket.
- Or a pocket/parent density ratio `<=0.45` where parent comparison exists.

These thresholds are descriptive for this pass, not proposed defaults.

## 2026-08-21 Results

Capture health:

| Symbol | Window | Ticks | Snapshots | Status |
|---|---:|---:|---:|---|
| ES | 10:20-12:00 | 233433 | 5650 | ok |
| NQ | 10:20-12:00 | 133267 | 6318 | ok |

Label counts:

- `auction_separated_child`: 3
- `campaign_base`: 2
- `accepted_child_no_clear_pocket`: 2
- `upper_attempt_reopened`: 2
- `accepted_child_prior_live`: 1
- `provisional_child_unresolved`: 1

Important rows:

| Symbol | Time | Sponsor | Parent | Gap | Pocket flow | Beyond60 | Old60 | Post supply | Read |
|---|---:|---|---|---:|---:|---:|---:|---|---|
| ES | 11:00:45 | `7690.75-7692.00` | `7684.75-7685.75` | 19 | 0.514 | 0.999 | 0.000 |  | `auction_separated_child` |
| ES | 11:03:48 | `7694.00-7694.25` | `7690.75-7692.00` | 7 | 1.593 | 0.993 | 0.000 | `supply_still_holding` | accepted child, but no clear pocket; later failed with prior sponsor live |
| NQ | 11:02:53 | `29338.25-29340.25` | `29331.25-29335.25` | 11 | 0.216 | 0.689 | 0.165 | `supply_encounter_no_escape` | `upper_attempt_reopened` |
| NQ | 11:15:28 | `29355.25-29357.75` | `29338.25-29340.25` | 59 | 0.115 | 0.109 | 0.815 | `supply_encounter_no_escape` | `upper_attempt_reopened` |
| NQ | 11:30:52 | `29363.25-29371.25` | `29355.25-29357.75` | 21 | 0.048 | 0.959 | 0.000 | `repair_confirmed_continuation` | `auction_separated_child` |
| NQ | 11:31:35 | `29372.25-29374.50` | `29363.25-29371.25` | 3 | 0.147 | 0.745 | 0.037 | `repair_confirmed_continuation` | provisional; gap too small |
| NQ | 11:32:59 | `29376.25-29379.00` | `29372.25-29374.50` | 6 | 0.404 | 0.986 | 0.000 |  | accepted, no clear pocket |
| NQ | 11:40:39 | `29438.50-29440.50` | `29376.25-29379.00` | 237 | 0.073 | 0.993 | 0.000 | `unclassified_extension_response` | `auction_separated_child` |

Read:

- NQ 11:02 was not campaign authority. It reopened old prices in `3.304s`,
  spent `16.5%` of the first 60s in old prices, same-side depth fell by `25`
  after first touch, and the next same-side worse-price sponsor did not arrive
  for `755s`.
- NQ 11:15 was a worse upper attempt, not a healthy continuation child. Old
  prices reopened after `11.004s`, old-price dwell was `81.5%` in the first
  minute, and the post-child supply read was still `supply_encounter_no_escape`.
- NQ 11:30 was different: the parent-child pocket flow was only `0.048`
  contracts/tick/second, old prices stayed unavailable, and another same-side
  worse-price sponsor appeared `43s` later. That is the cleaner "auction moved
  location" object.
- ES 11:03 explains why "accepted beyond" alone is not enough. The child
  accepted beyond immediately, but the pocket was too actively traded to show
  clean separation, and its later sponsor failure still had prior sponsor live
  plus eight same-side protections behind it.

### Focused ES 11:03 Pocket-Failure Check

Object:

- parent sponsor: `7690.75-7692.00`, promoted `11:00:45`
- child/add sponsor: `7694.00-7694.25`, promoted `11:03:48`
- add/fill/upper test area: roughly `7696.25-7698.75`
- parent-child pocket: `7692.25-7693.75`

Runtime context:

- supply `7696.25-7698.75` owned at `11:09:13-11:09:36` in EAR events
  (`81` consumed / `82` lean in the local runtime sequence);
- same supply was later held/tested around `11:11:39-11:12:31`;
- formal current-sponsor failure of child `7694.00-7694.25` fired at
  `11:14:37`, with fill/flatten around `7692.50`;
- failure context still had prior sponsor `7690.75-7692.00` live and
  `8` same-side protections behind.

MarketRecorder timing after the upper supply/add area was challenged:

| Time | State | Read |
|---:|---|---|
| `11:09:27-11:09:28` | first trade/mid back into `7694.00-7694.25`, then `7692.25-7693.75` | first pocket reopen; too early alone for all-flat |
| `11:09:28-11:11:26` | repeated dwell between child sponsor and parent-child pocket | upper add prices were no longer holding cleanly |
| `11:11:26-11:12:27` | mid repaired only into `7694.50-7696.00`, not back into `7696.25-7698.75` | reclaim attempt of the upper/add supply area failed |
| `11:12:27` | mid rolled back to `7694.25` | cleaner pocket-failure / leveraged-add give-up point |
| `11:13:24` | mid back in `7692.25-7693.75` | late confirmation; still before formal sponsor failure |
| `11:14:37` | formal sponsor failure at `7692.50-7692.75` quote | current EAR exit |

Snapshot dwell from `11:09:38` to `11:14:37`:

- `7694.50-7696.00`: `113.2s`, `37.8%`
- `7694.00-7694.25`: `62.0s`, `20.7%`
- `7692.25-7693.75`: `123.5s`, `41.3%`
- `7696.25-7698.75`: effectively no accepted dwell after the failure sequence
  started

Read:

- If the rule is "first pocket touch," the exit would trigger around
  `11:09:28`, but that is probably too reactive. Price had just met upper
  supply; a single re-entry into the gap can still be normal repair.
- If the rule is "pocket reopens, then the reclaim of the upper add/supply area
  fails," the cleaner exit is around `11:12:27`, roughly two minutes before the
  current formal sponsor failure and around six to seven ES ticks better than
  the `11:14:37` flatten.
- This is not evidence to kill the older long thesis. It is evidence to stop
  treating the `7694.00-7694.25`/`7696-7698` add as campaign authority.
  Because FIFO prevents reliable child-only trimming, the practical action is
  either all-flat or an explicit new execution model that never pretends it is
  preserving a parent lot.

Prior EAR rule boundary:

- EAR already has a reference-break guard: after a qualified old opposing rail
  fails, same-side children beyond that failed reference remain add-eligible but
  cannot inherit campaign-sponsor authority while the reference-break context is
  active.
- That older rule is not the same as the current pocket-failure idea. It is
  scoped to old opposing-reference failures and tactical children beyond them.
  The current research asks for a more general authority rule: when an added
  upper distribution fails to keep the pocket closed, it should lose authority
  even if the exact sponsor boundary has not formally failed yet.
## 2026-08-19 Cross-Check

Capture health:

| Symbol | Window | Ticks | Snapshots | Status |
|---|---:|---:|---:|---|
| ES | 10:10-12:00 | 265568 | 5725 | ok |
| NQ | 10:10-12:00 | 0 | 0 | missing_capture |

Only ES is L2-classified here. NQ runtime rows exist, but no local L2 capture is
available for this window, so the probe skips NQ instead of assigning false
fragility labels.

ES label counts:

- `accepted_child_no_clear_pocket`: 3
- `auction_separated_child`: 3
- `campaign_base`: 2
- `provisional_child_unresolved`: 1
- `auction_separated_child_failed`: 1

Important ES rows:

| Time | Sponsor | Parent | Gap | Pocket flow | Beyond60 | Old60 | Failed | Read |
|---:|---|---|---:|---:|---:|---:|---|---|
| 10:37:25 | `7743.75-7744.75` | `7741.75-7742.25` | 5 | 0.204 | 0.997 | 0.000 | false | `auction_separated_child` |
| 10:51:36 | `7747.25-7747.75` | `7743.75-7744.75` | 9 | 0.201 | 0.999 | 0.000 | false | `auction_separated_child` |
| 10:58:58 | `7756.75-7757.75` | `7753.75-7754.75` | 7 | 0.528 | 0.987 | 0.000 | false | `auction_separated_child` |
| 11:01:46 | `7760.25-7761.75` | `7756.75-7757.75` | 9 | 0.070 | 0.329 | 0.018 | true | `auction_separated_child_failed` |

Read:

- 8/19 ES supports the user's FIFO objection. When the upper distribution was
  truly separated, sponsor failure around 11:07 was not obviously an overreaction.
  The auction had marched across low-interaction pockets and then the upper
  separated child failed.
- Prior sponsor liveness still existed in the failure context, but the structural
  argument was different from 8/21 ES 11:03. In 8/19 the failing object had a
  cleaner low-volume separation behind it; in 8/21 ES 11:03 the parent-child
  pocket was actively traded.

## Current Heuristics

This pass points to a useful L2/profile mechanics split:

1. `auction_separated_child`
   - parent-child gap is present;
   - pocket flow is low for the product;
   - old prices stay mostly unavailable after child promotion;
   - worse-price same-side sponsor chains quickly or post-child beyond dwell is
     high;
   - if this object later fails, FIFO all-flat is structurally defensible.

2. `provisional_child` / `upper_attempt_reopened`
   - old prices reopen quickly or dwell meaningfully behind the child;
   - same-side depth falls on the first touch instead of restacking;
   - next same-side worse-price sponsor is delayed;
   - supply is crossed or failed but the auction does not escape;
   - failure is more consistent with repair/attempt failure than campaign
     failure.

3. `accepted_child_no_clear_pocket`
   - post-child acceptance looks fine, but the parent-child region traded too
     actively to prove a low-interaction separation;
   - this supports participation, but is weaker evidence for making the child
     the sole campaign authority.

## Interpretation

This research argues against a hard "add only after first retest" rule as the
first solution. The better object is sponsor authority:

- EAR can stay aggressive on entries/adds.
- Promotion to campaign authority should be conditional on auction separation,
  not merely on band birth or immediate favorable movement.
- Under FIFO, if a separated upper child fails, all-flat is not inherently bad.
- If a provisional upper child fails while older sponsorship is alive, all-flat
  is more likely to abandon a valid thesis and force a re-entry hunt.

## Caveats

- The low-pocket flow thresholds are exploratory and product/session specific.
- This is not an EAR-accurate PnL simulation.
- 8/19 NQ is not L2-confirmed because local MarketRecorder capture for
  `10:10-12:00` was missing.
- More sessions are needed before converting this into dispatcher/EAR language.
