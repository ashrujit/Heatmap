# What LevelLedger's L2 events are actually made of

Provenance: Claude-authored exploratory research. This is evidence for review,
not accepted Kahn policy or live execution permission.

Date: 2026-08-29. Sample: ESU6, 2026-08-27 and 2026-08-28, RTH, 1,747 firings.

## Why this was not measurable before

Two blockers, both now removed:

1. **Clock domains.** `book_events.receipt_timestamp_us` runs a median 895 ms
   behind `exchange_timestamp_us`; the tick tape is on exchange time. Joining
   on receipt time attributes ~20% of traded volume to a matching order
   removal. Joining on exchange time at 5 ms buckets attributes **99.3%**, with
   zero residual lag.
2. That 99.3% is the "proven print-to-order mapping" `BubbleTape/AGENTS.md`
   says is required before quote-hash grouping can be trusted. It exists now —
   not for aggressor identity (`trade_id` is empty on every row), but for
   **passive** identity: which resting order was consumed, its age, its queue
   rank.

So for the first time, every reduction in book size can be labelled *consumed*
or *cancelled*.

## The detector, restated

`LevelLedgerEngine.ComputeSample` sums size over the inner 10 levels a side
(`InnerLevels = 10`). `TryFire` z-scores that against a rolling mean/std over
`BookLookbackSeconds = 30`, sampled at 1 Hz, and fires when |z| > 2.5
(`EventZThreshold`). Positive z is `BID_BUILD`, negative is `BID_PULL`.

That statistic is a **level**, not a flow. Inner bid depth can fall because
sell aggressors consumed the bids, or because bid makers cancelled. Those mean
opposite things and the z-score cannot separate them. The vocabulary ("pull")
asserts the second.

## Result

Order flow in the 30 s preceding each firing, inside the inner-10 band of that
side (the detector's own lookback):

| event | n | consumed share | add/removal | add/ev | fill/ev | pull/ev | med \|Δmid\| |
| --- | --- | --- | --- | --- | --- | --- | --- |
| BID_PULL | 362 | 0.169 | 1.031 | 3,420 | 591 | 2,744 | 1.00 |
| ASK_PULL | 361 | 0.176 | 1.041 | 3,371 | 621 | 2,642 | 1.00 |
| BID_BUILD | 470 | 0.164 | 1.053 | 4,361 | 745 | 3,393 | 1.00 |
| ASK_BUILD | 554 | 0.175 | 1.020 | 3,655 | 608 | 2,894 | 1.00 |

Three things fall out:

1. **The four event types have indistinguishable flow signatures.** Consumed
   share 0.164–0.176. Add/removal ratio 1.020–1.053. Median absolute mid
   movement 1.00 pt in every bucket. Whatever separates a BUILD firing from a
   PULL firing, it is not visible in the adds, fills, or cancels underneath it.

2. **A "PULL" fires while that side is net *adding* liquidity.** Add/removal is
   1.031 for BID_PULL — more size arrived than left over the lookback. The name
   asserts withdrawal; the flow shows accumulation, at the same rate as during
   a BUILD.

3. **0 of 362 BID_PULL firings were majority-consumption** (same for ASK_PULL
   at 5 s and 30 s windows). Removals are ~83% cancellation. But that is the
   constant background of the ES inner book at *every* moment, event or not —
   so the "pull" label is technically true and carries no information.

At the 5 s window the picture is identical (consumed share 0.168–0.176,
add/removal 1.051–1.092), so this is not an artefact of window choice.

## What this does and does not say

**Does not say** the ledger's displayed rows are noise. Spatial-dominance rows
and ownership rails apply decay, a price kernel, ratio gates, freshness gates,
and current-auction gating on top of these atomic events. This measures the
**event vocabulary underneath**, not the rows the trader sees.

**Does say** that the atomic BUILD/PULL distinction — which Kahn consumes via
`LevelLedgerEvidenceEngine` as `RailOwned` / `RailHeld` / `RailFailed`
evidence — does not correspond to a difference in order flow. Any downstream
object that relies on BUILD-versus-PULL meaning "leaning in versus withdrawing"
is relying on a distinction the data does not support at the event level.

**The fixable version** is now cheap to build: replace the level z-score with
the directly measured quantities. `pull_size` and `fill_size` per level per
second are computable at 99.3% attribution, so a genuine "support withdrew
without being paid for" event is a real thing that can be detected — it just
is not what BID_PULL currently detects.

## Caveats

- Detector replicated from MarketRecorder 1 Hz `snapshots` parquet, not from
  the live Quantower `DepthOfMarket` the indicator actually reads. Close, not
  identical.
- Inner-10 is reconstructed mid-relative as price moves; if the live sampler
  anchors differently the band mapping is imperfect.
- Two days, ES only, one contract month.
- I did not test whether the *displayed* rows separate. That is the next
  question and it is a different experiment.

## Separately: three predictive nulls

For the record, so this is not re-derived. None of these beat aggressor delta
on forward returns at 60/180/300 s (ES, 8/27–8/28, 30 s buckets, mid-relative
20-tick band):

- book add / pull / fill imbalance: |corr| ≤ 0.06, ΔR² ≤ 0.003
- resting-add imbalance (quotes surviving ≥ 1 s): same
- age-resolved liquidity — volume-weighted age of consumed orders, old-vs-young
  pull split (5 s threshold), old-fill share: |corr| ≤ 0.05, ΔR² ≤ 0.003

Aggressor delta itself does not predict either (R² ≈ 0.001–0.002). Directional
prediction from order flow at these horizons is not there. Descriptively:
**only 9.8% of pulled size comes from orders older than 5 s** — 90% of book
withdrawal is sub-5-second churn.

## Reproduce

```bash
uv run --with polars --with tzdata python research/kahn/ll_event_decomposition.py --window-sec 30
uv run --with polars --with tzdata python research/kahn/mbo_liquidity_age.py --days 2026-08-27 2026-08-28
```

---

# Part 2: can rails owned/held/failed be improved by themselves?

## The defect, stated precisely

Three properties of the current rail object, all verified on ESU6 8/27-8/28:

1. **TEST is pure geometry.** Of 81 TEST transitions in the 11:00-12:30 window,
   58 fired at exactly 4 ticks from the band's near edge, 18 at 3, 4 at 2, 1 at
   1 — i.e. the moment price enters `test_buffer_ticks`. No liquidity content.
2. **The score is frozen at birth.** Across 40 bands with 2+ post-ownership
   transitions, the score changed in **0** of them. Band 46 carried score 76.03
   from 11:08:47 to 12:29 through 9 TEST/HOLD cycles.
3. **So TEST/HOLD is a price-proximity oscillator over a static band.** It never
   asks whether the liquidity that justified the rail is still there.

## The fix, and it works

Re-measure the owning side's flow inside the band during the 60s of contact
after a TEST: `replenish = added / (consumed + pulled)`. Label = does the rail
FAIL in the 15 minutes *after* that feature window (no leakage).

780 TEST events, ES, 8/27-8/28:

| signal | AUC as failure predictor |
| --- | --- |
| LevelLedger's frozen score | 0.655 |
| **replenish ratio (new)** | **0.612** |
| consumed volume | 0.583 |
| pulled volume | 0.568 |
| paid share | 0.561 |

`corr(LL score, replenish) = +0.041` — **nearly orthogonal**. So it is not a
restatement of the score, it is independent information.

Failure rate by quadrant (score median 26.3, replenish median 1.012):

| | low replenish | high replenish |
| --- | --- | --- |
| **high LL score** | 42.6% (n=190) | **22.5% (n=204)** |
| **low LL score** | **62.5% (n=200)** | 49.5% (n=186) |

The score alone separates 42.6% from 62.5%. Adding replenishment separates
22.5% from 62.5% — roughly doubling the discrimination, for a measurement that
is now cheap and reliable.

Note the sign on `consumed`: more consumption at test time means *more* failure.
A rail being paid through is being spent. A rail reloading is being defended.
Those are the two directional-consumption states the current event vocabulary
cannot express.

## Applied to the 7780 campaign

Two owned supply rails covered the entry zone, both formed 11:08, both among
the strongest of the day. Under the current grammar their TEST events are
indistinguishable. Under the replenishment re-measurement they are not:

| time | act | band | range | score | replen | consumed | grade |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 11:20:12 | TEST | 46 | 7775.75-7781.75 | 76.03 | 0.999 | 935 | weak |
| 11:23:13 | TEST | 46 | 7775.75-7781.75 | 76.03 | 0.917 | 1400 | weak |
| **11:23:27** | TEST | 47 | 7778.25-7781.75 | 72.49 | 1.032 | 12 | **STRONG** |
| **11:23:58** | TEST | 47 | 7778.25-7781.75 | 72.49 | 1.033 | 93 | **STRONG** |
| **11:32:09** | TEST | 47 | 7778.25-7781.75 | 72.49 | 1.135 | 0 | **STRONG** |

Band 46 is the wide band price actually traded into — it was being consumed
(935, 1400 lots) with replenishment under 1. Band 47 is the tight band at the
high — barely consumed at all (12, 93, 0 lots) with replenishment above 1.
Offers there were being replaced faster than they left, and buyers could not
get into them.

So: **there was enter-able LL evidence at 7780** — and the graded version
identifies the exact right one. The passive entry ladder filled 11:23:25-11:26:08,
bracketing the 11:23:27 and 11:23:58 STRONG tests on band 47.

## Add-zone evidence below 7765

Same-side supply rails formed continuously through the decline, so add
permission was never absent:

7762.25-7762.75 (11:40:59) -> 7760.25-7761.75 (11:44:39) ->
7756.75-7758.50 (11:48:05, score 42.3) -> 7754.50-7758.50 (11:48:33) ->
7750-7752.75 (11:51:59) -> 7745.50-7750 (11:56:23) ->
7740-7748.25 (11:57:18, score 59.0)

Each OWNED or CONSUMED with subsequent HOLDs. The 7740-7748.25 rail sits in the
declared target zone, which is where `TargetZonePolicy` should suppress rather
than add. And LL flagged the counter-rally correctly: bands 70 (7736.50-7740,
score 74.85) and 69 (7738.75-7741) both FAILED at 7742-7742.75 at 12:07,
two minutes before the 12:09 high.

## Caveats

- Two days, ES only, 780 TEST events. AUC 0.61 is a real but modest edge.
- The replenish threshold (median 1.012) is an in-sample split.
- Rails come from `ownership_bands_probe` replay, not the live indicator.
- This improves rail *durability* classification. It is not an entry signal —
  the earlier predictive nulls still stand.
