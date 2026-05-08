# Research Log — Heatmap Project

A running journal of microstructure analysis sessions. Persists conversation context that doesn't belong in code-side `CLAUDE.md` files: trade narratives used as design fixtures, hypothesis tests, things tried and rejected, open questions for future sessions. Future Claude instances should read this before re-deriving anything.

Memory files (`~/.claude/projects/C--Heatmap/memory/`) capture *patterns to apply*; sub-project `CLAUDE.md` files capture *how the code works*; this log captures *what we've learned about the data and why the indicators look the way they do*.

---

## Session 2026-05-04 — design crystallization + initial ship

Started the day with two indicators in mind: an absorption/exhaustion shape detector, and a liquidity-pull / vol-expansion research workstream. The conversation produced one shipped indicator + capture infrastructure.

### Key reframe: anomaly visibility, not classification

Initial impulse was to build a labeled detector ("this is absorption, this is exhaustion, this is significant"). User pushed back hard: same microstructure shape means *opposite* things in opposite contexts (reversal at extreme vs continuation pause in trend). They've been burned by Bookmap / QT-native / footprint indicators that bake assumed meaning into shapes. They wanted **shape surfacing, not labels**. Rendering with self-clearing on price-through replaces state-machine confirmation tiers.

Direct quote: *"what you name it etc is irrelevant"*.

This anti-classifier stance became the design law for the whole project. See [`feedback_indicator_design_philosophy.md`](../../Users/j/.claude/projects/C--Heatmap/memory/feedback_indicator_design_philosophy.md) — extended later in 2026-05-05 to also cover research outputs.

### Four design fixtures (NQ, captured trade-by-trade analysis)

These are the canonical examples for any future tuning. All on NQM6 unless noted.

| Time (NY) | What it is | Why it matters |
|---|---|---|
| **2026-05-04 10:46:00 @ 27941.00** | Bearish absorption at HOD | Climax bar +248δ in 5s, then HOD prints with reversal inside same bar. Stacked one-sided imbalance at 27939–27940 with no extension. Single-print at 27941 (1 contract). Failed retest 27940.50 with cumD divergence (peak +1091 → bounce +1024). Confirmed by failure to reclaim 27936 (HVN) by 10:46:50 + breakdown past 27932 by 10:48:15. *The cleanest single absorption case of the four.* |
| **2026-05-04 14:45:50 @ 27718.00** | Bullish absorption at swing low (HVN, not session-extreme) | "Balanced absorbing bar" variant. 410 contracts in 5s with delta only +12 (211 buy / 199 sell — both sides ferocious). Below 27719: stacked sell-aggressor imbalance with zero buy aggressors, only single-digit volume each (5–14 contracts per tick). Then 27718 → 27747 rally over 4 minutes. Failed-from-other-side bonus at 27724.00 (144 sell vs 36 buy, but price broke up through it later — failed sell absorption = bullish). |
| **2026-05-04 12:12:45 @ 27688.00** | Bullish exhaustion at recovery high (post news flush) | "Weak-delta extreme" variant. Context: 12:07:50 + 12:08:00 was a news-driven crash (1772 + 1827 contracts in two consecutive 5-sec bars, price 27711 → 27613, -98 pts in 10s). Recovery rally to 27688 by 12:12:45 made the high on delta only +20 / 238 vol = ~50% imbalance ratio. Close 27683.50 well off the high. cumD peaked at -1039 at 12:11:45, lower at the marginal new high. Subsequent fade to 27650. *The "thin print exhaustion at PDL" pattern from user's narrative.* |
| **2026-04-30 15:25:35 @ 27608.50** | Bearish absorption at swing high (substitute for missing 05/02) | User originally cited 2026-05-02 15:25, but that was Saturday. Skurry's tick DB has 04/30 instead. Climax bar +104δ. Above 27606.50: every level 27606.75 / 27607.00 / 27607.25 / 27607.50 / 27607.75 / 27608.00 / 27608.25 / 27608.50 has zero sell aggressors — pure buy aggression up there, all absorbed by static offers. Drop 26 pts to 27582 by 15:30:40. cumD divergence on retest. Structurally identical to the 10:46 case. |

### A1/A2/E1/E2 primitives derived from the fixtures

- **A1 — stacked one-sided imbalance, no extension**: N consecutive levels with imbalance > θ on the side that *failed*. Default θ=0.5, N=3. Volume floor per level (≥10) was added after the dry-run showed thin levels with 1.0 imbalance dominating fires.
- **A2 — balanced absorbing bar**: high vol-z bar with low |delta|/vol at local extreme. Captures the 14:45:50 shape.
- **E1 — single-print at extreme + heavy neighbor imbalance**: thin extreme tick with a heavy stacked-imbalance level within 2 ticks inside.
- **E2 — weak-delta extreme bar**: bar prints new local extreme on |delta|/vol < threshold. Captures the 12:12:45 shape.

### Architecture decisions locked in this session

- Skurry stays read-only research-only; never coupled to Heatmap indicators at runtime or build time.
- Each indicator is its own `.csproj` deploying to `<QT>/Settings/Scripts/Indicators/<Name>/`.
- L2 capture is opt-in inside `L2_Heatmap` (don't pollute the display invariant; also don't fork an indicator just for one writer).
- Capture path debugging: `Assembly.GetExecutingAssembly().Location` is unreliable inside QT's loader (shadow-copies). Replaced with explicit `CaptureRootPath` InputParameter defaulting to the deploy path.
- Parquet over SQLite for L2 (top-50 each side × 2Hz too wide for narrow tables; analytical reads in Polars are easier with column-shaped layout). Schema: flat 202 columns (timestamp_us, ref_tick, then 50 bid offset/size pairs and 50 ask offset/size pairs).
- Tick capture also in parquet under the same root, daily-partitioned.
- `<CopyLocalLockFileAssemblies>true</CopyLocalLockFileAssemblies>` is required so `Parquet.Net` and transitives (`Parquet.dll`, `IronCompress.dll`, `Snappier.dll`, `ZstdSharp.dll`, `Microsoft.IO.RecyclableMemoryStream.dll`, `runtimes/`) deploy alongside the indicator DLL.
- `FileShare.Read` on the parquet writer (added next session) so analysis tools can read while live capture continues.

### Phase-2 research locked but deferred

The depth-σ / liquidity-pull research is a population-property question (does σ(ΔLiq) lead RV systematically?). Genuinely deferred until 2–4 weeks of capture data accumulate across regime variety (trend, balance, news, OPEX). One day means nothing. See [`project_phase2_depth_sigma.md`](../../Users/j/.claude/projects/C--Heatmap/memory/project_phase2_depth_sigma.md).

---

## Session 2026-05-05 — first-day capture, side-aware events, LiquidityMeter shipped

Captured one full session (RTH 18,352 snapshots / 297,985 ticks after RTH filter). User came back with two real trades from this session — one win and one loss — that became the design fixtures for the rest of the session's work.

### Capture sanity findings

- **Aggressor flag is fully populated** in our captures: 173,765 Buy + 171,463 Sell prints, **zero `None`/`NotSet`**. Better than Skurry's data (which has some 0-side ticks from its CSV pipeline). Means delta math can trust `aggressor_sign` directly.
- **Top-50 each side always populated** for NQ during RTH (median 50, p99 50). LevelsPerSide=50 is right-sized; could even reduce.
- **Cadence: median 1195ms** (target 1000ms). p95 3.4s — quiet stretches stretch the interval. Acceptable; "approximately 1Hz, faster during active hours."
- **Snappy compression: 3.7×** ratio. ~110MB on disk for 19 hours, ~30MB in RAM via Polars.
- **RTH filter is mandatory**: ETH books are thinner and algo-dominated; including them contaminates rolling baselines (RTH events get z-scored against thinner-book ETH window, look more extreme than they really are) and conflates two fundamentally different participant mixes. Filter applied *before* any rolling math.

### Daily asymmetry — a candidate session-summary metric

Side-aware event counts on the day (RTH only):

```
ASK_BUILD   233   (bear)
BID_BUILD   216   (bull)
ASK_OUT     152   (bull)
BID_OUT     145   (bear)
BID_IN      140   (bull)
VOL_OF_DEPTH 131  (neutral)
ASK_IN       91   (bear)
ASK_PULL     80   (bull)
BID_PULL     68   (bear)
```

Bullish total 588, bearish total 537 — slight bull skew matched the directional outcome (NQ +444 pts on the day). Asymmetry ratio `(bull - bear) / (bull + bear) = +0.045`. Hypothesis: trend-day asymmetry will be heavier; balance-day will be ~0. Worth tracking session-over-session as a one-number regime descriptor — much before the cross-correlogram becomes meaningful.

### Win-trade fixture: long off rejection of 28050 floor (10:13–10:25)

User narrative: 10:10 saw responsive sellers stepping down. Plan was to fade them targeting IB high. First add at 28032/33 around 10:13 (price moved away — dropped further). Saw momentum buyers around 28055–28057, 28067, 28080. 10:18 dump. Mental rule: "if price holds/accepts INTO my first entry, then likely it will fail (2-way auction); I'm out." Instead price rejected from a vol node. Adds at 28041, then 28057, 28063, 28067 as price climbed. Exit at day's high / IB high.

Critical decision moment: **why did the user NOT add at 28054 before 10:14?** Skurry-claude had told them 28050 was the planned floor. But the ladder "didn't feel right" to click intuitively at 28054.

**What the events showed at 28054 around 10:14:30**: only ASK_OUT events fired in the immediate window. NO BID_BUILD, NO DEPTH_IN. Pure retreat. The "feel" was reading exactly this — providers showing intent to pull, no offsetting commit.

**What the events showed at 28050.75 around 10:19:30**: BID_BUILD z=+5.01 + BID_IN z=-2.63 simultaneously — one of the two strongest bull-event clusters of the entire day. The "click confirmation" was structurally readable.

The contrast (no-acceptance vs strong-acceptance) at the *same level* 5 minutes apart became the canonical positive/negative pair for the level-read concept.

Cumulative meter behavior through the trade arc: net +31.9 over 17 minutes (120.4 bull / 88.4 bear). Climbed almost monotonically from +5 by 10:09 to +31.9 by 10:25, never below +0. Each scale-in coincided with either ROC already positive AND fresh bull events, or a brief ROC-negative dip with cum holding strongly positive.

Brief ROC dip at 10:20–10:21 (ROC went to -8.8) was *noise within trend* — bears tried to push back, cum stayed +27–30, fresh BID_BUILDs at 10:22:28 reasserted, ROC popped back. Pattern: trend-noise dips don't move cum.

### Loss-trade fixture: short 28145 supply, expecting break to VWAP/VVAL (12:18–12:55)

User narrative: built 4-contract short around 28145 (had been ceiling). Expected visit to VWAP, possibly VVAL. 12:28 hard flush to VWAP, barely touches, violent reaction finds supply at 28112–28115. 12:30 mental rule: if walks down and accepts into 28102, stay short (acceptance into IB = breakdown). 12:39–12:43 returns to 28100/28102 area — user thinks "great, possibly a break." 12:47 toys with upper end of supply zone. **12:53 finds responsive buyers — totally weird, should have broken to 28107–28102**. Slowly exits at 28117 on every touch.

User asked: "did 12:30–12:40 give indication this was a *failed* responsive sell rather than a real one?" and "how did 12:40–12:45 confirm 'this is it' from a long-watcher's perspective?"

**Cumulative meter walk through 12:18–12:45**: net -16.6 (91.6 bull / 108.1 bear). The bears DID have the edge in the events stream during the user's hold window — supports the short thesis. **At 12:30–12:40 specifically there was no clear bull turn** in the running tally. Brief flicker at 12:30:31 (peak +6.4 from ASK_OUT cluster post-flush) got rolled back into deep bear by 12:34 (-20.3). Window ENDED at -17.6, bears still winning. *The user was not wrong to hold based on what the events showed through 12:40.*

**The actual long-watcher confirmation came at 12:47:00, not where the user expected**:

```
12:47:00  BID_BUILD  +4.37  28119.50  +bull   net  +3.8  ↑
12:47:00  BID_IN     -3.14  28119.50  +bull   net  +6.9  ↑↑↑
12:47:19  VOD_SPIKE  +3.41  28120.25   neut
12:47:58  ASK_OUT    +3.56  28127.75  +bull   net  +8.0  ↑↑↑
```

BID_BUILD z=+4.37 paired with BID_IN at 28119.50 = "bid-side stacking AND leaning in close at the upper supply edge." Translation: *responsive buyers committing right at the edge of supply.* This was telegraphed **6 minutes before the user noticed at 12:53** by tape-reading.

### The structural insight that shaped LiquidityMeter

The right rule for the meter as a sizing/exit aid:

> **ROC alone is a warning shot; cum starting to follow ROC is the confirmation.**

Several false bull-ROC pulses came and went during the loss trade (12:30 +8.7, 12:35 +7.0, 12:39 +8.2, 12:41 +6.7) — none of them moved cum. The 12:47 pulse was different: ROC popped AND cum started climbing too (from -21.8 at 12:46:28 to -14.3 at 12:47:00 in under a minute). When *cumulative joins ROC against the position*, that's the unambiguous "this is it."

A live meter showing this running tally would have prompted the user to start lightening at 12:47 instead of 12:53 — saving ~6 min × 4 contracts of adverse drift, non-trivial slippage.

### Bid/ask side separation was non-negotiable

Initial events were unsigned (`LIQ_BUILD`, `LIQ_PULL`, `DEPTH_IN`, `DEPTH_OUT`, `VOL_OF_DEPTH_SPIKE`). At the loss-trade level (12:39–12:44), unsigned events showed contested-but-mixed pattern. Without splitting bid-side from ask-side, "LIQ_BUILD at supply" remains structurally ambiguous: sellers reloading offers (bear) vs buyers stepping in (bull). Same shape, opposite implications.

Splitting into 8 directional events (`BID_BUILD`/`PULL`, `ASK_BUILD`/`PULL`, `BID_IN`/`OUT`, `ASK_IN`/`OUT`) made the loss-trade narrative read cleanly. **Side awareness is a hard requirement for the level-read and meter concepts**; both research script and live indicator implement it.

### What was tried and explicitly rejected

- **Per-PULL composite significance score** (computed for one turn, immediately removed). User pointed out it's classifier framing in research clothing — same anti-pattern as A/E's confirmation tier. Direct quote: *"finding sequences or correlation can be maddening (misleading at best) ... perhaps they are more of use as timing something rather than finding a correlation and then building a mechanical understanding and a signal? sort of the same philosophy that followed A/E design?"* The right output shape is a time-ordered event stream, not a ranked-by-score view.
- **Sequence templates for "significant pulls"** (PULL → no rebuild → vol expansion = significant, etc.). Same trap. The trader supplies context, the meter surfaces structure, classification stays out.
- **Top-by-|z| as the primary view**. Kept as an overview but not a ranking. Real product is the time-ordered CSV.

### LiquidityMeter design — what shipped this session

Decisions:

1. Side-aware event detection (the 8 directional events) at 1Hz from L2 snapshots in the live BookState. Mirrors `research/liq_events.py`.
2. Cum = `Σ (bias × |z|)` over events newer than anchor. Default anchor: rolling 30-minute window (always-on, no user input).
3. ROC = `Σ (bias × |z|)` over events in last 60s.
4. Visual: left-center vertical cum bar + horizontal ROC dial (separate axis so the eye doesn't hunt) + small VOD flicker box.
5. Anchor modes: Rolling (default), Indicator-Load, Session-Start (NY 09:30). Manual click-anchor deferred to v0.2.
6. **VOL_OF_DEPTH events** added (neutral on bias, fed into the flicker indicator only). User wants live observation to decide cut/keep.

Initial design was a single vertical-bar with overlaid ROC needle. User pointed out they were "searching" for the needle when it was near zero. Refactored to give ROC its own horizontal dial below the cum bar — distinct shape, distinct axis, no hunting. *Lesson: visual elements with the same orientation collide in attention. Different orientations let the eye parse two channels independently.*

---

## Session 2026-05-06 — squeeze-day regime caveat (no capture data)

User reported back after a full short-squeeze session. Headline: **cum and ROC "worked well, except they pointed in exactly the other direction at turning points."** User adapted within 5–10 minutes of recognizing the regime; nothing to change in the math.

This is structurally important and worth permanent capture as a *regime caveat for the meter*.

### What was happening

Short squeeze = forced-flow regime. Aggressive buyers are not discretionary; they are shorts being forced to cover. At turning points (small dips that reverse back up):

- During the pullback: providers stack offers (ASK_BUILD, bear-leaning) and bids retreat slightly (BID_OUT, bear-leaning) — meter reads bearish.
- *But* the squeeze flow continues — shorts must cover regardless of provider commitment — so price reverses back up.
- Result: meter said BEAR right before price went UP at the turning point. Inverted reading.

### Why this is informative, not broken

The meter measures **provider commitment** (resting-depth dynamics). In *normal discretionary auction regimes* — what most of our design fixtures are — provider commitment leads price because the auction is driven by where providers choose to engage. In *forced-flow regimes* (short squeezes, capitulations, news-driven crashes, OPEX gamma chases) — flow drives price *despite* what providers do, because non-discretionary participants must transact. Provider commitment can decouple from price direction, sometimes invert.

The meter is doing the right thing — it's accurately reading *the wrong question* for that regime. Once the trader recognizes "we're in forced flow," the same reading tells you something different: providers are positioning *against* the squeeze (rationally — they expect mean reversion). When their commitment finally aligns with price (cum starts following price), that's the squeeze's structural exhaustion.

### Practical use during forced-flow

When a regime feels forced (squeeze, capitulation, news flush):
- *Don't* read meter direction as price direction. Invert mentally, or just discount.
- *Do* watch for the moment cum and price re-align. That's the structural turn — providers have given up fading and joined the move (squeeze topping) or finally stepped in to fade (capitulation bottoming).
- *VOD chaos* is a regime-detection candidate: heavy sustained VOD spikes correlate (anecdotally, today) with forced-flow regimes. Provider thrash + cum/price divergence = "this is squeeze-like, discount cum." Worth tracking forward.

### What changed in the code this session

- VOD indicator made significantly more visible: vertical strip beside the ROC dial (matching ROC height), two-channel intensity (steady amber from rolling 30s count + pulse on each fire), configurable `VOD Strip Width` and `VOD Steady-Glow Saturation Count` InputParameters. Previous 10×10 box below labels was easy to miss; user explicitly flagged it.
- No math changes. Per user: "nothing to change."

### Capture gap (resolved root cause)

Today's session was not captured (no `snapshots-2026-05-06.parquet` exists). **Root cause**: yesterday's L2_Heatmap update (the `Capture Root Path` InputParameter addition + `FileShare.Read` fix) caused QT to re-load the indicator, and `Capture Enabled` defaults to `false` — so the existing chart's capture setting reverted to off after the rebuild. User caught it; will re-enable.

**Config gotcha to remember**: any time L2_Heatmap is rebuilt with new InputParameter additions, QT may reset its settings to defaults. After any L2_Heatmap edit + restart, *re-verify Capture Enabled is on* before the next session. Worth considering switching the default to `true` once we're confident capture is stable, so this doesn't keep biting on indicator updates.

---

## Session 2026-05-07 — liquidation day + VOD-as-fragility-indicator observation

NQ liquidation-day session: price 28868 → 28600, ~270 pts down. User didn't lean on cum/ROC for decision-making (paid more attention to ladder), but contributed an important observation about VOD now that it's visible.

### User's VOD observation (worth permanent capture)

> "vod usually flickered when level/position might get taken out, especially at swing points when range behavior started"

Two distinct contexts the user named:
1. **Level / position about to break** — VOD spikes
2. **Swing points where range behavior begins** — VOD spikes

Structurally this is exactly what σ-belief theory would predict: VOD = rolling stdev of Δinner_depth = rate at which providers are *changing* their depth. Heavy VOD means providers are repositioning rapidly. That happens at:
- **Level fragility moments**: some providers exiting (defenders giving up), others stepping in (new participants taking the level), all in seconds → high Δinner_depth variance.
- **Regime transitions** (trend → range, range → trend): providers shift from "fade the move" posture to "set the new range" posture (or vice versa). Same population repositioning their σ-expectation.

VOD isn't measuring direction; it's measuring **how unsettled provider conviction is at this moment**. That makes it a *fragility / regime-shift signal*, complementary to the directional cum/ROC.

### Today's data confirms this is a heavy regime

Top 20 events |z|-sorted are dominated by VOD:

```
12:15:48  VOD z=+10.26  @ 28651.75  inner=598    ← largest of the day
14:00:12  VOD z= +8.70  @ 28696.75
14:44:45  VOD z= +8.31  @ 28600.25  ← at session low (level break)
13:29:24  VOD z= +8.19  @ 28619.50
09:48:58  VOD z= +7.89  @ 28727.00
13:22:45  VOD z= +7.61  @ 28655.25
13:54:44  VOD z= +6.63  @ 28629.50
11:19:54  VOD z= +6.54  @ 28868.75  ← at session high (level break — opposite side)
14:12:15  VOD z= +6.53  @ 28676.00
14:18:51  VOD z= +6.38  @ 28705.50
10:36:52  VOD z= +6.20  @ 28870.75  ← also near session high
12:02:21  VOD z= +5.99  @ 28765.75
```

12 of 20 top events are VOD spikes. Several cluster at session extremes (28868 = day high near 11:19 / 10:36; 28600 = day low at 14:44:45). **The user's hypothesis is supported by the data on this session**: VOD spikes correlate with level-break moments. The 12:15:48 event is the strongest of the day (z=10.26) at inner=598 — way above median ~300, suggesting a major participant repositioning a lot of size in seconds.

### Daily summary

```
BID_BUILD  253   ┐
ASK_OUT    173   ├─ 597 bullish
BID_IN     112   │
ASK_PULL    59   ┘
ASK_BUILD  242   ┐
BID_OUT    226   ├─ 651 bearish
ASK_IN     126   │
BID_PULL    57   ┘
VOL_OF_DEPTH_SPIKE 136 (neutral)
```

Asymmetry = (597 - 651) / (597 + 651) = **-0.043** (mild bear lean). Compare to 2026-05-05 (+0.045 bull on a directional-up day). The asymmetry sign matched price direction both days, with similar small magnitudes (~0.04 each side). Whether this metric distinguishes regime types (trend vs balance vs forced-flow) needs more sessions.

### Cross-correlogram

Peak at lag **+5s** (corr +0.1118), slightly biased to *positive* lag — which would mean RV slightly leads VOD (provider repositioning trails realized vol). Opposite of the σ-belief-leads-RV hypothesis. **One day, no signal yet**, but on a forced-flow regime day it's structurally consistent: liquidation-driven vol spikes happen first, providers reposition after. The hypothesis predicts negative-k peaks on *normal* discretionary regimes; tracking this peak's drift across regime types is the long-game.

### Implication for the meter

VOD-as-fragility makes the indicator more useful than pure "chaos noise" framing. New mental model: **a strong VOD glow at a swing point is a regime-transition warning shot**. Combined with cum/ROC reading:
- Strong VOD + cum and ROC aligned with current price direction → "trend continuing, but some level turbulence — watch for breaks of nearby levels"
- Strong VOD + cum/ROC diverging from price → "regime shifting; the meter's directional read is about to update; be cautious about leaning on the current cum interpretation"
- Strong VOD at a session extreme → "this level is being tested and contested; outcome is fragile"

Keep VOD detection on. Worth tracking session-over-session whether VOD events cluster at user-identified swing points (manual marking would help for that study).

### Code changes this session

- L2_Heatmap & LiquidityMeter `BookState.cs`: fixed a stale-ID bug. Original logic only removed the order ID when the *price changed*; on a non-Closed quote update where size shrinks to zero at the *same price*, the ID was kept in the set with `TotalSize == 0`, eventually leaking. Fix: also drop the ID/level when `q.Size <= 0` even at the same price. Both mirror copies updated.

---

## Session 2026-05-07 (continued) — design conversation: indicator suite plan + L2_Heatmap demotion

User came back through today's session after the live trading retro and walked three decision windows from today against the captured events:

1. **11:24–11:38 — VWAP touch + 880 fizzle** (the trade where user bought 28875/28880, flattened at BE, then read VPOC accumulation correctly as distribution-lower)
2. **11:38–12:18 — down leg into 28640s** (where user took the short but couldn't add into the fast-ladder leg)
3. **12:18–12:55 — bounce to 28760 + open rejection** (where user identified the rejection but anxiety overrode the entry)

The retro produced a permanent set of design fixtures + design laws + a multi-indicator build plan. This session's content informs everything we ship next.

### Three fixtures from 2026-05-07 (canonical)

**Fixture A — distribution-while-rallying (11:24–11:38)**

The 11:26:54 VWAP touch at 28834 had a legitimate responsive-buy signature: `ASK_OUT z=3.69 + ASK_PULL z=-2.84` at the touch tick paired with `BID_BUILD` z=2.51/2.68/2.94 stacked at 28842/28848 over the next two minutes. Cum momentarily improved from -12 → -0.5; ROC peaked +5.3 by 11:28. *Same shape as the 2026-05-05 win-trade at 28050.75.*

But from 11:30 onward, **five `ASK_BUILD` events with z>2.5 fired between 28874 and 28888** in 7 minutes (11:30:48, 11:32:50, 11:35:10, 11:36:08, 11:37:31). Three `ASK_IN` (sellers leaning into top-of-book offers). No `BID_BUILD ≥ 3` below price in this stretch. The only strong bull event was at the very top: `BID_BUILD z=4.19 + BID_IN z=-4.08 + VOD z=4.0` at 28894.75 at 11:37:45 — the "fragility-at-swing-point" signature, landed on the top tick.

**Cum/ROC at 11:32:09 (when user bought 28880): cum –17.2, ROC –5.4**. Cum stayed pinned bear through the entire arc, never recovered, contrasting sharply with the 05-05 win-trade where cum climbed monotonically positive across scale-ins. The 05-05 rule applied verbatim: *ROC alone is a warning shot; cum following ROC is the confirmation.* Cum never followed.

**Fixture B — down-leg add zones in fast liquidation (11:38–12:18)**

User couldn't add into the ladder once it accelerated. The events stream had clean re-add zones at every level where `ASK_BUILD ≥ 3` reasserted on a small bounce:
- 28859 (11:48:50, z=4.01 + VOD 3.17)
- 28831 (11:50:27, z=**4.87**) — at the prior VWAP test from below
- 28812 (11:55:41, z=3.20)
- 28786 (11:58:06, z=3.52)
- 28722 (12:11:42, z=**4.44**) — last clean layer before the climax leg

Bid-vacuum companion signals (the leg-not-done tells, distinct from add zones): 12:00:32 BID_OUT z=3.76 @ 28757; 12:08:02 BID_OUT z=3.61 @ 28720; 12:15:04–17 cascade @ 28678 → 28669 → 28660. The "stop adding" tell was the day's loudest event: 12:15:48 VOD z=**10.26** + BID_BUILD z=5.19 at 28651.75 (inner_depth 70 → 598 in one snapshot).

**Fixture C — bounce-rejection at supply (12:18–12:55)**

Cum bounced briefly to +5 by 12:30. Then **12:31:42 ASK_BUILD z=4.19 + VOD z=3.21 + ASK_IN z=-2.91 at 28744** — triple-fire. Cum flipped +3 → –7 in 30 seconds, ROC tanked to –10. From 12:31:42 onward cum monotonically deteriorated to –51.5 by 12:47.

Cascading supply: 28756 (12:36:20, z=3.97), 28737 (12:41:45, z=3.42), 28734 (12:42:21), 28727 (12:43:34), 28720 (12:47:45, z=3.17). Each bounce attempt got sold into. **28744 was the structural rejection; 28732–28737 was the second clean entry, 12–15 ticks better than where user actually engaged at 28720.** Anxiety-about-position-average overrode an unambiguous structural signal.

### LiquidityMeter v0.2 manual-anchor click — first validated live use

User clicked the meter to anchor at ~11:32:09 when buying 28880. From the anchor cum painted **flat**, ROC painted **red**. User initially read this as "feature broken — shouldn't this reset on a bull leg." On reflection: math was correct.

Post-anchor 11:32:09 → 11:35:00 weights:
- Bull events: BID_BUILD z=3.55 at 28882 (only one) → ~3.5 weight
- Bear events: BID_OUT 3.10 + ASK_BUILD 3.74 + ASK_IN 2.75 + BID_OUT 3.19 + BID_OUT 2.91 + VOD 2.71 → ~17 weight
- Net cum ≈ –13, painted as flat-to-mildly-red on a +cum scale; ROC dominated by ASK_BUILD/BID_OUT cluster painting deep red.

**Cum should have been "filling green" if the buy was leveraging into provider commitment. It wasn't.** The anchor surfaced absence-of-bull-commitment immediately, in real time. The failure mode it exposed was structural, not behavioral. First live validation of the manual-anchor feature.

### Design laws confirmed/refined this session

1. **Persistence-as-confirmation** (new). The 28744 structural rejection didn't act on its own — user saw it but didn't engage. The cascade *below* 28744 (28737, 28734, 28732) confirmed the rejection. Self-clearing markers would have lost the cascade structure that made the second entry tradeable. **L2 event markers should default to no-auto-clear**, configurable TTL but off by default, optional price-through clearing for BUILD-type events only. Direct user words: *"keeping them around for 10-15 mins is important... 737 is now the best available, take it before too late."*

2. **Edge is a prompt, not a signal** (new). For climax/edge detection (L2_Flow), the line marks "level was contested, look here" — not "act now." Decision lives in what the bounce does after the line, read from L2_Events dots painting in the post-edge window. The indicator never tries to make the add/reverse/flatten call.

3. **Eyes on the road, glance at the mile marker** (user's framing, locked). All indicators in the suite are guideposts in decision-making; none are decision-makers. Consistent across A/E, LiquidityMeter, SinglePrints, and the new L2_* family.

### L2_Heatmap demotion decision

User explicit: *"since the day 0 of making L2 Heatmap live, I haven't made a single practical use of it. rather the cum/roc has been useful from day 0."* Across three captured sessions (05-05 win/loss, 05-06 squeeze-day caveat, 05-07 liquidation), the cloud overlay drove zero decisions. The events stream + cum/ROC carried the full decision load, including all of today's retro analysis (no heatmap visualization was opened to derive any of the three fixtures above).

**Decision**: keep `L2_Heatmap` capture infrastructure exactly as-is (it's the data foundation for everything else); make the cloud display a flippable toggle. Renamed `LiquidityHeatmapEnabled` display string to `"Show Heatmap Painting (capture is independent)"` (sortIndex 700) so the decoupling is obvious in the settings dialog. Default stays `true` for backward compat; user flips false on main chart, optionally true on a spare chart.

No siblings (one project), no code restructure, no capture-path changes.

### Indicator suite plan — five new indicators, each surfacing a different shape

Each indicator paints a specific structural element. Together they layer into a complete view; alone each one is its own guidepost. All follow the design laws above.

| # | Indicator | Surfaces | Today's signal |
|---|---|---|---|
| 1 | **L2_Events** | Per-tick BUILD/PULL/IN/OUT events as side-colored dots on price track | The 28744 → 28737 → 28734 cascade |
| 2 | **L2_Inflection** | Cum-joins-ROC moments labeled at price level | The 11:32 anchor read; the 12:31:42 cum-flip |
| 3 | **L2_Flow** | Vacuum-traversal *band* (vertical) + climax/thrash *lines* (horizontal) | 28619 climax line, 28651 climax line, 11:38–12:18 down-leg band |
| 4 | **L2_Supply_Layer** | Same-side BUILDs clustered into horizontal bands | The 28732–28744 supply zone |
| 5 | (L2_Heatmap demotion) | n/a — settings change only, no new indicator | shipped 2026-05-07 |

Build order: 1 (smallest, foundational, reuses MeterEngine pattern) → 2 → 3 (most consequential, builds on pattern from 1+2) → 4. Each gets its own `CLAUDE.md` capturing design fixtures and rationale.

### L2_Events specific design (locked in this session)

- **Trigger**: any `BID_BUILD`/`ASK_BUILD`/`BID_PULL`/`ASK_PULL`/`BID_IN`/`ASK_IN`/`BID_OUT`/`ASK_OUT` with `|z| ≥ 3` (configurable). VOD spikes get their own neutral color.
- **Color scheme**: 3 colors total. Blue = bull-leaning (BID_BUILD, BID_IN, ASK_OUT, ASK_PULL). Orange = bear-leaning (ASK_BUILD, ASK_IN, BID_OUT, BID_PULL). Amber = VOD (neutral / fragility). Side is meaningful; event-type-within-side is not. Trader doesn't need to remember 8 colors.
- **Density via additive alpha**: each dot rendered at α≈70/255. Five overlapping dots → α≈245 = bright saturated cluster. No clustering logic. Cluster intensity emerges from rendering. Today's 12:31:42 28744 (3 events same tick) → loud blob; lone ASK_BUILD elsewhere → faint dot.
- **Persistence**: default no auto-clear (full session). Configurable `Auto-Clear After (min)` defaults 0=never. Optional `Clear BUILDs On Price-Through` toggle, default off.
- **Size**: 6×6 px default, configurable 4–12 range.
- **No count badges, no labels.** Density alone communicates. *"intensity alone is enough."*

### L2_Flow specific design (locked, build deferred to after L2_Events + L2_Inflection)

- **Line trigger**: `VOD z≥5 AND any BUILD z≥4 within 5s at same tick`. Persistent until price-through. Line color amber (neutral — line marks level, not direction).
- **Band trigger**: rolling 30s — vacuum-event density (count of OUT/PULL z≥3 same direction) AND RV elevated AND inner_depth thinning, all sustained for 10s. Band ends when criteria normalize for 30s. Band color tinted by vacuum direction (orange = bear flow, blue = bull flow). Vertical translucent strip across full chart height.
- **Validation against 5/5 (trend day, +444pts)**: 4 fingerprint candidates fired (28087, 28107, 28139, 28147). On a trending day all eventually traded through upward → lines self-clear → indicator behaves correctly. Only `12:11:03 28147.5` was strictly contested (both BUILDs ≥4); others were one-sided.
- **Validation against 5/7 (liquidation)**: 3 lines would fire (28765, 28651, 28619). None traded through up → lines accumulate → confirms regime. The 12:31:42 28744 case (`VOD only z=3.21`) does **not** fire L2_Flow line — it's a cascade-start, naturally handled by L2_Events dots + L2_Supply_Layer band. **The not-firing is correct division of labor.**

### Future test cases (data not in capture; mark and validate when sessions accumulate)

- **5/4 12:05pm** — flush worth flattening, no day reversal expected (Type A: continuation). News-driven crash 27711 → 27613 in 10s. Capture infrastructure was being built that session; not in parquet.
- **5/6 9:30am** — failed initial drive lower (Type B: auction-failed-at-extreme). User added on the failure, plans for 27350. *Auction failure shape, not a vacuum* — would likely fire L2_Flow line without a band (gentler shape than today's flush+band+line). Capture was off (defaults bug).
- **5/1 9:30am** — opening-range thin-air drive (Type C: vacuum screams "join"). User failed to tag on. Pre-capture.
- **4/30 9:30am** — opening-range thin-air drive (Type C). User joined right price. Pre-capture.

Three flush taxonomy types: continuation, auction-failed, thin-air-join. Same indicator surfaces them; trader read of post-edge dots discriminates. *"the indicator's job is identical across all three: paint the band, paint the line, paint the dots. The trader's job is different in each — and that's the design law working."*

### The "right sequence" — canonical L2_Flow workflow target

User's articulation of the intended trade arc that L2_Flow should support, paraphrased and locked:

> 28641 lighten significantly (flush in progress, post-edge band still active, climax line forming) → 28744 / 28737 / 28735 add back **heavier than what was lightened by** (post-edge dots painting orange on bounce, line at 28744 holding as supply, structural confirmation) → flatten below 28608 (PD VVAH structural reference reached/breached, regime question resolved).

Three different reads at three different timescales. Lighten = react to flush band. Add back = read post-edge dot character against climax line. Flatten = price interaction with structural reference (volume-profile / market-profile, NOT an L2 thing — indicator's job is just "we got here"). Richard's "if you see a flush, flatten" rule (Axia, ES-era 5-pt-was-mega-win) was correct at the lighten step; the user's nuance is that lightening prevents seeing the deeper structural pivots. The indicator suite should support both reads: the band = "lighten now," the post-edge dots + climax line = "add back here," and your VP framework = "flatten there."

### Consolidation: one indicator (L2_Surface), four layers

Mid-build the originally-planned four separate indicators (L2_Events, L2_Inflection, L2_Flow, L2_Supply_Layer) consolidated into a single `L2_Surface` indicator with toggleable layers. User flagged correctly that they share `BookState`, the event-detection math, the sample loop, and the thesis — four separate `.csproj`s would have meant four BookState copies, four L2 subscriptions, four sample loops, for no functional gain. Layers also compose better visually with explicit z-order (Flow band background → Build Bands → Climax → Inflection → Events dots in front) than as four independently-rendering chart instances.

L2_Events (which had shipped earlier in this session as a standalone indicator) was deleted; its design + code folded into L2_Surface's Events layer. Same defaults (z=3.0, dot size 6, alpha 70, no auto-clear). The L2_Inflection scaffolding was discarded mid-creation; its math went into L2_Surface's Inflection layer. L2_Flow and L2_Supply_Layer never shipped as separate projects; they were built directly as layers from day one.

Naming: "Surface" matches the design law ("surface structure, don't classify"). Single instance on the chart now hosts all four layers under one settings dialog with six grouped sections.

---

## Session 2026-05-08 — L2_Surface first live session, BookState stale-level bug discovered

L2_Surface shipped late 2026-05-07. Today (Friday 5/8) was its first full RTH session. User read: "non-stop buying with anemic auctions, no retracements, no opportunities." Headline NQ move ~190pts up.

Set out to do per-session L2_Surface effectiveness research. Discovered a fundamental data-quality bug en route: **BookState was retaining orphaned ask levels through the day, pinning best ask to a phantom low price and dragging `ref_tick` ~200pts below the actual market**. This corrupted every L2_Surface paint coordinate (Build Bands, Climax lines, Inflection lines, Events dots) for the entire session. Effectiveness analysis on this data is invalid; reposting it would mislead future sessions. Bug fixed in code; this entry documents the diagnosis + fix instead.

### How the bug was found

Built `research/surface_walk.py` as the per-session L2_Surface effectiveness simulator — forward-pass replay of captured snapshots+ticks through the same per-layer trigger logic as `SurfaceEngine.cs` (same bias map, z-thresholds, proximity/cooldown rules). Output is a per-layer firing report: count, time, price, persistence.

### Capture-folder change to know about

Today's parquet landed under `captures/NQ/` instead of `captures/NQM6/`. User flagged the cause and will fix on the indicator side; for now, research scripts (`liq_events.py`, `surface_walk.py`) accept `SYMBOL_DIR` env var (default `NQM6`).

### The discovery — tape vs L2 mid disagree by 200pts

User cross-checked surface_walk's reported price levels (Build Bands at 29111-29112 / 29103.50) against the actual market (NQ open 28878.5, day high 29387, ~29311 at 13:28 NY). My output disagreed by ~200pts.

Inspecting the same parquet directly:

```
RTH ticks (trade tape):    open 28878.50, last 29324.25 at 15:56, max 29331.75
L2 snapshot ref_tick:      09:30 = 28895.25, 13:28 = 29109.25, peak ~29115
```

Tape matches the user's reality; L2 ref_tick lags by a gap that **grows** through the day (open: +34pt → midday: +186pt → close: +197pt). A calendar spread or fixed contract mismatch can't produce a growing gap. Drilling into a sample snapshot at 13:28 NY revealed the cause:

```
ref_tick = 116437  (mid 29109.25)
bids at offsets +766..+776  → absolute ticks 117203-117213 → price 29300-29303 ✓ matches tape
asks at offsets -776..-771  → ticks ~115661 → price ~28915 ✗ STALE (~400 ticks below tape)
asks at offsets +778..+784  → ticks 117215-117222 → price 29303-29305 ✓ matches tape
tape at 13:28 NY:           29300.75 - 29310.75
```

The book had **valid fresh bids around 29302 and valid fresh asks around 29303** (1-2 tick spread, normal NQ). It also had **stale asks pinned at ~28915 from earlier in the session that were never cleared.** Since `bestAsk = _asks.Keys.First()` (lowest tick), the stale low ask wins, and `refTick = (bestBid + bestAsk) / 2` gets dragged to a phantom midpoint between the real top-of-book and the stale low.

### Root cause

`BookState.Apply` removes a level when an order ID's `Closed` event arrives for it (or when a non-Closed update at a different price arrives, in which case the prior price's contribution is subtracted). The removal path relies on **receiving** those events. When Quantower drops a Closed event (feed gap, contract roll without symbol-clear, edge-case mid-session subscription quirk), the level keeps `TotalSize > 0` indefinitely. Aggregated L2 normally hides this — every level is rewritten frequently — but stranded levels at prices the market has long since left receive no rewrites and are invisible to all the bid/ask delta logic.

### Fix shipped this session

Three-part fix in `BookState.cs` (mirrored across all three copies — `L2_Heatmap`, `LiquidityMeter`, `L2_Surface`):

1. **`PriceLevel.LastUpdate` timestamp.** Stamped on every Apply that touches the level (add, modify, partial-decrement). The book now tracks per-level recency.
2. **`PruneStale(nowUtc, ttlSec)` method.** Walks both sides; any level whose `LastUpdate` is older than `ttlSec` gets force-removed, along with any `_orders` entries that pointed at it (so a late Closed for a stranded ID can't resurrect the level).
3. **Use `prior.IsBid` not current `q.PriceType` to pick the side during cleanup.** Defensive against any feed that recycles IDs across sides; previously the current-quote side was used, which would silently miss the cleanup if an ID flipped sides.

`Apply` signature changed: `Apply(Level2Quote q)` → `Apply(Level2Quote q, DateTime nowUtc)`. All three indicator drain loops updated to pass `nowUtc` and call `PruneStale(now, BookStaleTtlSec)` once per sample (not once per drain — sample cadence is 1 Hz, prune cost is O(level_count) per side, ~100 entries × 2 sides = trivial).

`BookStaleTtlSec` exposed as InputParameter on each indicator (default **60s**, configurable). Rationale: NQ aggregated L2 rewrites every level near mid many times per second — 60s is hugely conservative for the active book region. Stranded levels (the bug we're fixing) by definition aren't being touched, so a TTL anywhere in the seconds-to-minutes range catches them. `0` disables the prune.

### What was lost / regained

- **2026-05-08 captured parquet is permanently broken** for any analysis that depends on `ref_tick` being the real mid. The depth offsets stored relative to that bad ref_tick mean every "level X is at price P" claim from this dataset is wrong. The events stream from `liq_events.py` is similarly affected — the `price` column is `ref_tick * 0.25`, also bad. The *aggregate* metrics (`bid_inner`, `ask_inner`, asymmetry counts) are sums-across-the-book; those still mean "total resting size on bid side / ask side" and are usable as regime descriptors, just not as anything tied to a specific price level.
- **LiquidityMeter cum/ROC math today is unaffected.** The meter sums z-scored event weights, doesn't care about `ref_tick`. Whatever it painted live during today is meaningful.
- **L2_Heatmap cloud display would have been painted at the wrong y-coordinates** today (also affected by ref_tick). User had already deprioritized that display 5/7, so practical impact ~zero.
- **Going forward, all three indicators have the prune in place.** Next live session should produce ref_tick that matches the trade tape within normal spread distance. Trivially testable: `surface_walk.py` will report Build Band / Inflection / Climax prices that match what the user sees on chart.

### Effectiveness analysis: deferred

The per-layer firing densities and engine-behavior observations from today are still meaningful (Flow Band correctly silent on no-flush regime, Inflection density, Build Band count, etc. — all instrument-agnostic). But binding them to specific structural levels requires correct prices, which requires the fix to be live. **Re-run on next session's clean capture.** Don't act on this session's price-tagged findings.

### What's still meaningful from today's data

Aggregate-metric findings that survive the ref_tick corruption:

- **Events asymmetry: 319 bull-leaning / 348 bear-leaning / 458 VOD = -0.043 asymmetry** on a +190pt up day. Same squeeze-regime fingerprint as 5/6 (events bearish, price bullish). VOD = 41% of events confirms the user's "anemic auction / providers thrashing" read.
- **VOD dominance carries fragility info.** With ref_tick corruption affecting price tagging, we can still say "lots of VOD spikes in the day's middle hours" — provider repositioning was heavy regardless of where exactly. The earlier 5/7 hypothesis (VOD-as-fragility correlates with regime-transition / level-fragility moments) is unaffected.
- **Flow Band 0 fires** is a real observation — the trigger logic doesn't depend on ref_tick (event counts + RV + inner-thinning z, all aggregates).

### Files added / changed this session

| File | Change |
|---|---|
| `L2_Heatmap/BookState.cs` | + `PriceLevel.LastUpdate`, + `PruneStale`, side-aware cleanup via `prior.IsBid`. `Apply` signature now takes `nowUtc`. |
| `LiquidityMeter/BookState.cs` | Same fix mirrored. |
| `L2_Surface/BookState.cs` | Same fix mirrored. |
| `L2_Heatmap/L2_Heatmap.cs` | Pass `nowUtc` to `Apply`; call `PruneStale` per captured snapshot. New `BookStaleTtlSec` InputParameter (sortIndex 724, default 60). |
| `LiquidityMeter/LiquidityMeter.cs` | Same wiring; `BookStaleTtlSec` at sortIndex 906. |
| `L2_Surface/L2_Surface.cs` | Same wiring; `BookStaleTtlSec` at sortIndex 804. |
| `research/surface_walk.py` | New — per-session L2_Surface simulator. Output: per-layer firing report. |
| `research/liq_events.py` | `SESSION` + `SYMBOL_DIR` env-var overrides (was hardcoded). |
| `research/out/surface_walk_<DATE>.txt` | Per-session L2_Surface effectiveness artifact (stdout from `surface_walk.py`). |

### Things flagged for next live session

- **Sanity-check the fix works.** Run `surface_walk.py` after the next session and verify Build Band / Climax / Inflection prices match what was actually on chart (not 200pts below). If the prune didn't catch a leak path, `ref_tick` will still drift. Diagnostic: `bestBid > bestAsk` (book crossed) is the unambiguous bug signature.
- **Re-do the L2_Surface effectiveness analysis** once we have a clean capture. The per-layer firing-density questions (Inflection over-firing on directional regimes? Build Band density as regime descriptor? Flow Band calibration?) all need clean price data to answer well.
- **TTL=60s is conservative-but-not-validated.** If next session shows legitimate quiet far levels getting evicted on slow symbols, lower it. If we see persistent ref_tick drift, lower it (more aggressive prune). Tune from observation.

---

## Open questions / things to revisit

These are deliberately not resolved; they need real-session observations before answering.

1. **Does the meter actually help in real-time use?** User has zero expectations and intends to observe across many session types (trend / balance / news / OPEX) before drawing conclusions. Same posture as A/E.
2. **Is VOL_OF_DEPTH useful as a flicker?** Cut/keep depends on whether the user finds it informative live. Possibilities: useful chaos warning, or visual clutter.
3. **What's the right anchor mode for sizing decisions?** Rolling-30min is always-on but not trade-specific. Manual click-anchor (v0.2) gives trade-specific reading. Which one matches actual workflow needs proving.
4. **Daily asymmetry as regime descriptor.** Does `(BUILD_count - PULL_count) / (BUILD_count + PULL_count)` correlate with end-of-day trend/balance classification? Need 5–10 sessions to see.
5. **The cross-correlogram** σ(ΔLiq) vs RV(t+k). Today's peak was at lag 0 with corr +0.084 — meaningless on one day. Track week-over-week. If a stable peak emerges at negative k across regimes, the depth-σ-leads-RV hypothesis has support. If it stays flat or contemporaneous, the book is reactive not anticipatory.
6. **Is the cum/ROC math right at session boundaries?** Rolling-30min anchor effectively means cum can't span pre-RTH-open observations. May need a session-aware anchor that resets cleanly at 09:30 NY. Watch behavior on session opens.
7. **TPO single-print zones** (parked from this session). User wanted to add but recognized it's a different time-horizon (session-state market profile) than A/E's rolling 60s. If revisited, builds as its own tiny indicator (~150 lines), doesn't bundle into A/E.

## Files relevant to this conversation

| File | Purpose |
|---|---|
| `research/peek_capture.py` | Sanity-check capture parquet on a new session day |
| `research/liq_events.py` | Side-aware event extractor + cross-correlogram. The math `LiquidityMeter.MeterEngine` mirrors live. |
| `research/walk_trades.py` | Driver script — walks both win and loss trade arcs, calls `level_read` + `show_window` for each scale-in / decision moment |
| `research/meter_walk.py` | ASCII-meter visualization of cum/ROC dynamics through trade arcs. Validation tool — what the live meter would have shown. |
| `research/out/liq_events_<DATE>.csv` | Time-ordered events CSV — the primary research artifact. Trader-readable for context-reading. |
| `LiquidityMeter/MeterEngine.cs` | C# port of `liq_events.py` event detection + cum/ROC. Same bias map, same z-threshold. |
| `research/surface_walk.py` | Per-session L2_Surface simulator — replays captures through the same trigger logic as `SurfaceEngine.cs`, reports per-layer firing density + persistence. |
| `research/out/surface_walk_<DATE>.txt` | Per-session L2_Surface effectiveness artifact (stdout from `surface_walk.py`). |

When walking new session data, the workflow is:
1. Run `liq_events.py` (events CSV) — primary product
2. If validating meter behavior at specific times: run `meter_walk.py` between (start, end) timestamps
3. If looking at a specific level: load `liq_events.py` at REPL and call `level_read(price, "HH:MM:SS", lookback_min, band_ticks)`
