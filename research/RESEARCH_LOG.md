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

When walking new session data, the workflow is:
1. Run `liq_events.py` (events CSV) — primary product
2. If validating meter behavior at specific times: run `meter_walk.py` between (start, end) timestamps
3. If looking at a specific level: load `liq_events.py` at REPL and call `level_read(price, "HH:MM:SS", lookback_min, band_ticks)`
