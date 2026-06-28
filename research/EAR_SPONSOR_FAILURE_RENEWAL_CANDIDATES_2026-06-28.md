# EAR Sponsor Failure Renewal Candidates - 2026-06-28

## Scope

Question: take sponsor-failure exits from EAR, then compare those timestamps
against MarketRecorder-derived same-side sponsor renewal.

Important provenance:

- EAR `events.jsonl` is used only as the operational list of sponsor-failure
  exits.
- Renewal evidence is taken from synthetic `NQU6` MarketRecorder probes, not
  from the old live EAR evidence stream.
- `2026-06-22` is excluded because its MarketRecorder archive was not available
  locally.

Inputs:

- `C:\Users\j\Documents\ExecAssistantRuntime\events.jsonl`
- `research/out/lean_band_probe_nqu6_20260623_20260626.csv`
- `research/out/sponsor_failure_renewal_probe_nqu6_20260623_20260626.csv`

## EAR Sponsor-Failure Exit List

Window: `2026-06-23` through `2026-06-26`, RTH/active EAR log.

Counts:

| date | sponsor-failure exits |
| --- | ---: |
| 2026-06-23 | 11 |
| 2026-06-24 | 4 |
| 2026-06-25 | 10 |
| 2026-06-26 | 12 |

Full list:

| date | ET | side | failed sponsor band |
| --- | --- | --- | --- |
| 2026-06-23 | 09:46:07 | Demand | 29755.50-29757.25 |
| 2026-06-23 | 10:39:45 | Demand | 29911.50-29912.75 |
| 2026-06-23 | 11:03:39 | Demand | 29828.75-29830.00 |
| 2026-06-23 | 11:16:08 | Demand | 29777.25-29779.75 |
| 2026-06-23 | 11:45:50 | Demand | 29731.75-29732.50 |
| 2026-06-23 | 12:45:31 | Demand | 29892.75-29896.50 |
| 2026-06-23 | 12:50:23 | Demand | 29847.75-29852.00 |
| 2026-06-23 | 13:02:16 | Demand | 29838.25-29842.50 |
| 2026-06-23 | 13:19:16 | Demand | 29830.00-29831.50 |
| 2026-06-23 | 15:07:13 | Demand | 29689.75-29690.50 |
| 2026-06-23 | 15:53:10 | Demand | 29683.50-29684.75 |
| 2026-06-24 | 12:22:36 | Supply | 29773.75-29775.25 |
| 2026-06-24 | 13:02:34 | Supply | 29622.75-29623.50 |
| 2026-06-24 | 14:53:09 | Supply | 29347.25-29348.50 |
| 2026-06-24 | 15:28:33 | Supply | 29373.75-29375.00 |
| 2026-06-25 | 10:54:58 | Supply | 29762.25-29767.25 |
| 2026-06-25 | 11:48:06 | Demand | 29739.75-29741.25 |
| 2026-06-25 | 12:18:50 | Demand | 29846.50-29849.25 |
| 2026-06-25 | 12:35:50 | Supply | 29695.25-29697.25 |
| 2026-06-25 | 12:41:05 | Supply | 29680.50-29682.25 |
| 2026-06-25 | 12:52:22 | Supply | 29680.00-29680.25 |
| 2026-06-25 | 12:57:16 | Supply | 29661.25-29663.50 |
| 2026-06-25 | 13:33:07 | Demand | 29733.50-29736.75 |
| 2026-06-25 | 15:39:56 | Supply | 29635.75-29637.00 |
| 2026-06-25 | 15:47:57 | Demand | 29666.50-29668.25 |
| 2026-06-26 | 10:12:36 | Supply | 29546.50-29546.75 |
| 2026-06-26 | 10:30:36 | Supply | 29598.25-29599.25 |
| 2026-06-26 | 11:59:11 | Supply | 29622.25-29624.00 |
| 2026-06-26 | 12:26:40 | Supply | 29544.75-29545.75 |
| 2026-06-26 | 12:37:10 | Supply | 29621.75-29621.75 |
| 2026-06-26 | 12:42:53 | Supply | 29621.25-29622.00 |
| 2026-06-26 | 13:00:55 | Supply | 29611.50-29615.50 |
| 2026-06-26 | 13:13:20 | Demand | 29659.75-29661.50 |
| 2026-06-26 | 13:21:02 | Demand | 29601.25-29603.50 |
| 2026-06-26 | 13:37:21 | Demand | 29594.75-29597.75 |
| 2026-06-26 | 13:39:30 | Demand | 29586.25-29586.25 |
| 2026-06-26 | 14:07:20 | Demand | 29547.50-29551.50 |

## Fresh Same-Side Renewal Candidates

Filter:

- Same side as failed sponsor.
- Fresh synthetic `base_8t` ownership candidate after the EAR failure.
- Within 180 seconds.
- Within 24 ticks of the failed sponsor band.
- Expected fake-failure geometry:
  - failed supply renews at/above the failed supply area;
  - failed demand renews at/below the failed demand area.

This leaves two clean fresh-renewal candidates.

| date | EAR failure | failed sponsor | synthetic renewal | relation | read |
| --- | --- | --- | --- | --- | --- |
| 2026-06-23 | 12:50:23 Demand | 29847.75-29852.00 | 12:53:03 Demand `demand_lean` 29841.00-29844.50 | below by 13 ticks, +160.1s | Strong renewal-watch candidate. EAR also saw Demand `RailOwned` at 12:52:34 in 29838.25-29842.50, then another at 12:53:46 in 29843.00-29843.75. This was not terminal opposite ownership; demand renewed lower and later became the next sponsor before failing at 13:02:16. |
| 2026-06-25 | 12:57:16 Supply | 29661.25-29663.50 | 12:58:38 Supply `supply_consumed` 29663.50-29664.50 | overlap/above, +81.9s | Possible renewal-watch candidate, weaker than 6/23. The synthetic row held on test, but it did not show as a live EAR `RailOwned` row in the old event stream, so treat it as synthetic-only evidence. |

## Excluded But Nearby

These are useful review points but are not the same as fresh sponsor renewal:

| date | failure | reason excluded |
| --- | --- | --- |
| 2026-06-23 11:03:39 Demand | Same-side held test about 3 seconds later, but no fresh ownership candidate. |
| 2026-06-23 11:45:50 Demand | Same-side held test about 88 seconds later, but no fresh ownership candidate. |
| 2026-06-23 13:19:16 Demand | Synthetic failure probe labels near `hold` renewal at 13:19:34, not fresh ownership. |
| 2026-06-25 12:35:50 Supply | Same-side held test about 171 seconds later, but no fresh ownership candidate. |
| 2026-06-25 15:39:56 Supply | Fresh same-side seed appeared at 15:41:13, but it was 32 ticks away / 64 ticks worse, outside the near-renewal filter. |
| 2026-06-26 12:42:53 Supply | Synthetic probe eventually labels sponsor-side continuation, but the next seed was about 140 seconds later and 72 ticks away, not a quick nearby renewal. |

## Working Read

The two clean cases support the practical concern but keep it narrow:

- A sponsor can fail mechanically, flatten correctly, and still leave the
  failed side alive as a `renewal_watch` context.
- The old failed sponsor should not remain protective evidence.
- If a fresh same-side band appears quickly near or just beyond the failed
  area, the retry logic should probably be allowed to reference that old area
  as context instead of waiting blindly for much worse independent evidence.
- 6/23 12:50 is the cleaner example. 6/25 12:57 is worth chart review but is
  less clean because the renewal was synthetic-only relative to the live EAR
  evidence log.

## Review Addendum

User review corrected the practical examples:

- `2026-06-23 12:50` was a counter-trade context and should not be used as the
  main sponsor-renewal example.
- `2026-06-25 12:57` was a balance-building long/fail/renewal context; it is
  lower consequence for the current product problem because there was not much
  payoff available even if classified better.
- The better example is `2026-06-25 10:54:58` after the short from 10:53.

### 2026-06-25 10:54 Supply Renewal

Live EAR sequence:

| ET | event | read |
| --- | --- | --- |
| 10:53:28 | Supply `28` owned | `29762.25-29767.25`, source `Consumed` |
| 10:53:29 | short fill | base short promoted supply `28` as sponsor |
| 10:54:39 | supply `28` held | old sponsor still alive |
| 10:54:58 | supply `28` failed | EAR flattened on sponsor failure |
| 10:55:59 | demand `31` owned | opposite repair at `29737.75-29738.50` |
| 10:56:33 | demand `31` failed | repair did not hold |

Synthetic MarketRecorder sequence around the same failure:

| ET | event | band | read |
| --- | --- | --- | --- |
| 10:54:56 | supply candidate | `29771.75-29772.50` | fresh supply begins two seconds before the logged sponsor failure |
| 10:55:00 | supply displacement confirmed | `29771.75-29772.50` | confirmation prints two seconds after the logged sponsor failure |
| 10:55:01 | explicit conversion row | supply | marked failed in broad explicit-conversion cut |
| 10:58:46 | supply candidate | `29637.00-29638.75` | later lower supply; not immediate renewal of the failed area |

This changes the filter lesson:

- Looking only for same-side ownership strictly after the `sponsor_failed`
  timestamp can miss the renewal.
- The watch window should include same-side candidates already forming at the
  moment of failure, for example `failure_ts - 5s` through `failure_ts + 180s`.
- For a failed supply sponsor, a same-side candidate slightly above the failed
  band is the expected fake-failure/renewal geometry.

### 2026-06-23 13:34 Short Check

EAR did have a short directive:

| ET | event |
| --- | --- |
| 13:34:30 | short directive accepted, target `29700`, base-only `2` |
| 13:36:48 | supply lean owned `29885.25-29887.75` |
| 13:37:36 | supply consumed owned `29882.50-29882.75` |
| 13:39:17 | supply consumed owned `29862.25-29863.50` |
| 13:42:32 | short directive canceled manually, no entry submitted |
| 13:42:44 | fresh short directive accepted, target `29670` |
| 13:43:20 | fresh short invalidated by LF while flat |

There was no live short fill around `13:35-13:40`. The earlier `13:25-13:29`
activity was long-side, not a short that failed and then continued lower.

The 13:34 short's accepted event predates the richer range-audit fields, so the
JSONL does not prove whether order-range gating was the reason no entry fired.
What the log does prove is narrower: eligible-looking supply evidence existed
while the short directive was active, but EAR never emitted an `order_submit`.

### 2026-06-25 10:54 Microstructure Read

The object that made supply `28` fail was not clean demand sponsorship. In the
synthetic `NQU6` replay it was demand candidate `33`:

| ET | object | band | read |
| --- | --- | --- | --- |
| 10:54:28 | demand candidate `33` | `29764.00-29768.50` | demand attack through the old supply area |
| 10:54:39-10:55:01 | candidate `33` episodes | `29764.00-29768.50` | repeated reset attempts |
| 10:54:56 | supply candidate `34` | `29771.75-29772.50` | fresh same-side supply appears just above the failed sponsor |
| 10:55:00 | supply candidate `34` confirms | `29771.75-29772.50` | supply renewal confirms before demand becomes durable |
| 10:55:10 | demand candidate `33` episode confirms | `29764.00-29768.50` | too late to be clean demand ownership; candidate-level final outcome is consumed into supply |

The candidate row for `33` has:

- `side=demand`
- `final_side=supply`
- `source=demand_consumed`
- `outcome=consumed`

So the better read is:

- old supply `28` failed mechanically because price traded above it;
- the opposing demand push was not a durable demand sponsor;
- fresh supply `34` appeared and confirmed just above the failure while demand
  was still unstable;
- waiting for a later demand rail to fail missed the relevant transition,
  because the later demand rail at `29737.75-29738.50` was far below and not
  topologically useful for a near supported-reclaim entry.

This is a stronger product problem than a normal post-failure retry:

- classify the failure-causing opposing initiative, not only the failed
  sponsor;
- if that opposing initiative is still resetting / unstable and same-side
  sponsorship confirms nearby beyond the failed sponsor, mark the failure as
  `renewal_watch` or `failure_absorbed`;
- keep the flatten discipline, but do not require a later, separate failed
  demand rail before considering the same-side renewal actionable.
