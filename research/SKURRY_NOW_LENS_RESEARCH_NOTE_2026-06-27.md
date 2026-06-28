# Skurry Now Lens Research Note - 2026-06-27

## Purpose

This note captures a fresh pass over Udit's current `Skurry-Panel` origin code as inspiration for LevelLedger / EAR research. The goal is not to copy the panel or UI. The goal is to extract testable microstructure theses and validate them one at a time against clean MarketRecorder data.

## Source And Provenance

Reviewed source:

- Repo: `https://github.com/uditmukherjee/Skurry-Panel.git`
- Current main after fetch: `origin/main` at `42185f5`
- Current PR head reviewed for Now Lens work: `origin/pr/22` at `62a3027`
- Local branch `epic/heatmap-indicator-panel` is stale and tracks a deleted remote branch; it should not be treated as current source.

Research data rule:

- Do not compare new findings against live EAR logs from the last several days. Those logs are provenance-contaminated by the MNQ execution symbol versus NQ chart / MarketRecorder data split.
- MarketRecorder is the research source of truth, and its folder structure shows NQ capture.
- If we need to know what LevelLedger or EAR would have done, derive synthetic LL/EAR bands, rows, and decisions from MarketRecorder NQ data using the current logic.
- New live EAR logs only become clean research evidence after confirming `execution_symbol=MNQU6` and `market_data_symbol=NQU6` in the runtime checkpoint/configuration.

## High-Level Read

Now Lens is a present-tense DOM/tape visualization. It is not a standalone signal generator. The useful part for LL/EAR is the decomposition:

- Lean: inside bid/ask imbalance at the current best.
- Driver: short-half-life signed aggressor tape.
- Road / Terrain: nearby book thickness, vacuum, and wall motion.
- Brick: contact response when trades hit a displayed wall.
- Horizon: farther walls and gaps.

For LL/EAR, the biggest candidate improvement is not a new entry rule. It is better classification of what happened at a price zone: did a sponsor hold, did a wall give, did size pull before contact, did passive size refill after contact, and was continuation happening through open road or through real opposition?

Primary validation semantics across all theses:

- The primary outcome is auction/ownership behavior, not where price is after a fixed number of seconds.
- Favorable/adverse excursion is secondary context only.
- Preferred outcomes are: missed/formed band, same-side ownership, consumed ownership, supported reclaim, explicit conversion, test held, test failed, and whether the auction then destroys opposing structure.
- The key question is who continues to sponsor and own the auction after a zone is touched, pierced, consumed, or repaired.
- Follow-up framing lives in `research/BAND_LIFECYCLE_EPISODE_TAXONOMY_2026-06-27.md`: separate directional initiative episodes from balance/distribution episodes, and evaluate tests/failures inside a local micro-auction rather than only at the exact band price.

## Thesis 1 - Lean

Udit's Lean read uses current top-of-book bid/ask size imbalance, smoothed with a very short EWMA. The docs cite this as the strongest cheap primitive in their study, especially at very short horizons.

Possible LL/EAR use:

- Band discovery support: identify areas we may be failing to classify as bands because current `|z|`, support, or persistence gates are too strict.
- Consumed-band classification: after demand consumes supply or supply consumes demand, test whether Lean helps identify which side's test will survive and then destroy the opposite-side structure.
- Normal-band classification: for ordinary demand-lean / supply-lean bands, test whether Lean helps identify which bands are likely to survive a touch/pierce test.
- Qualification tuning: test whether Lean should influence the current `x ticks / y seconds` qualification tool.

What to validate:

- Reconstruct best bid/ask size from MarketRecorder book events.
- Test raw and smoothed inside imbalance around:
  - candidate zones that current LL/EAR did classify
  - near-miss zones that failed current band gates
  - consumed demand/supply bands
  - normal demand-lean / supply-lean bands
- Define primary outcome as test survival, not trade excursion. A survived test means price touches and pierces the band, then reverses and destroys opposing structure.
- For consumed bands, separate stronger survived tests from imminent failures.
- For normal bands, compare Lean state at formation, approach, touch, pierce, and reversal.
- Evaluate whether Lean changes the optimal `x ticks / y seconds` qualification thresholds or only explains failures after the fact.
- Keep favorable/adverse excursion as a secondary diagnostic after the classification question is answered.
- Stratify by session phase, distance from active zone, and whether the band is consumed or normal.

What not to do:

- Do not let Lean override zone ownership by itself.
- Do not treat a positive short-horizon statistic as a durable trade thesis.

Current Thesis 1 takeaway after the first MarketRecorder pass:

- The best Lean finding is direct conversion. When a level is offered a lot of supply, that supply is consumed, and the auction converts the area into demand, Lean aligned to the resulting side is the only clearly interesting cut so far.
- Formation-time Lean does not justify relaxing `|z|` or cluster gates by itself.
- Lean opposed to a band at test may be a warning, but the direct-conversion case is the cleaner takeaway for now.

## Thesis 2 - Driver

Driver is short-half-life signed aggressor flow, normalized by recent regime. The key idea is impulse, not cumulative delta. It asks whether initiative is present now and how unusual that speed is versus the recent tape.

Possible LL/EAR use:

- Separate active initiative from drift when a synthetic LL/EAR event appears.
- Improve entry urgency after a valid consumed rail / direct conversion.
- Help avoid chasing a move whose ownership read is valid but whose active effort has already faded.

What to validate:

- Build 3s half-life signed tape impulse from MarketRecorder trade prints.
- Rank tape speed against a rolling session-local window.
- Compare synthetic LL/EAR entries with Driver aligned, opposed, absent, and exhausted.
- Use this as a conditional overlay on the existing baseline, not as standalone PnL.

Open question:

- Whether Driver adds more than our existing OFI/tape features once all are rebuilt from clean NQ MarketRecorder data.

## Thesis 3 - Road / Terrain

Terrain reads the nearby book around the inside: visible size, vacuum runs, wall candidates, and whether levels are building or eroding. The important implementation detail is that it uses deeper book state for presence, not just render-capped heatmap cells.

Possible LL/EAR use:

- Distinguish "zone failed into open road" from "zone failed into nearby opposing liquidity."
- Explain no-retest continuation after a consumed source.
- Improve no-chase / target-distance context after a valid entry.

What to validate:

- Reconstruct near-band book around inside, likely +/-20 ticks as a starting point.
- Compute vacuum fraction/runs, nearest wall distance, and wall motion.
- Condition existing synthetic LL/EAR events on whether price had open road after the event.
- Evaluate continuation distance and adverse retrace, not only win/loss.

What-if:

- A consumed demand/supply source may need two different labels: consumed into open road versus consumed into immediate opposing wall. EAR should probably treat those differently for entry urgency and target expectations.

## Thesis 4 - Brick Contact Response

This is the most directly relevant Now Lens idea for LL/EAR. Brick tracks what happens when trades contact a displayed level:

- pre-contact resting size
- size consumed by prints
- size that disappeared without coincident trade
- size refilled after contact
- whether the level held or gave after a short quiet window

Possible LL/EAR use:

- Improve sponsor hold/fail classification at the exact tested zone.
- Confirm whether a consumed rail created a legitimate direct conversion entry.
- Separate "real opposition absorbed effort" from "displayed size simply got out of the way."
- Help classify LF/HF pause resolution without redefining LF/HF itself.

What to validate first:

- For each synthetic LL/EAR rail/test event, capture pre-contact displayed size at the contacted ticks.
- Attribute same-price removals near trade time as consumed versus pulled.
- Measure refill over 250ms and 2s.
- Label the subsequent response: held, gave, or ambiguous.
- Compare against the current synthetic LL/EAR baseline labels and outcomes.

Important caveat:

- Spoof detection should stay research-only until live ordering is validated. It is sensitive to event ordering, timestamp precision, and whether book removes can be reliably paired with prints.

Expected value:

- High. This is the cleanest bridge from Udit's math to LL/EAR because it directly addresses who defended, who gave, and whether the test succeeded.

## Thesis 5 - Horizon

Horizon scans beyond the near band for farther walls and air pockets. Udit's docs found NQ extended book often thin/uniform, so a sparse Horizon is itself information: there may simply be open road.

Possible LL/EAR use:

- Context for target distance and chase risk.
- Identify when a valid entry has little visible opposition ahead.
- Avoid over-weighting a single far wall as ownership.

What to validate:

- Scan beyond the near band, roughly 21 to 64 ticks as an initial range.
- Track nearest meaningful wall and largest contiguous low-size gap.
- Test whether open Horizon after a synthetic event improves continuation distance or lowers adverse excursion.

## Thesis 6 - Side-Aware Pressure Field

Udit's LevelLedger-related docs describe a side-aware pressure field:

- demand evidence: bid adds plus ask removes
- supply evidence: ask adds plus bid removes
- normalize by rolling book/flow scale
- spread evidence spatially around nearby ticks
- decay evidence over time
- require purity, event support, and recent dominant evidence

Possible LL/EAR use:

- Better ownership support layer for zones.
- Classify whether a band has clean one-sided pressure or mixed churn.
- Add a purity/support score beside existing LL rows instead of replacing the current grammar.

What to validate:

- Replay MarketRecorder book deltas into demand/supply fields.
- Generate synthetic LL/EAR bands using current logic.
- Ask whether pressure purity/support improves classification of:
  - source holds
  - consumed-source direct conversions
  - failed retests
  - continuation after pause

What-if:

- The useful output may be a confidence/quality score, not a new row type.

## Thesis 7 - Refill After Sweep / Stoprun

The current Skurry code has a refill tracker that measures passive same-side adds in a consumed price band, including a fast bucket and a 2s bucket. This overlaps strongly with Brick but frames the problem around event aftermath.

Possible LL/EAR use:

- Post-contact classification: did passive interest reappear quickly enough to defend the zone?
- Distinguish continuation sweeps from stoprun/fade candidates.
- Improve handling of direct conversion after a rail is consumed.

What to validate:

- Run this together with Brick as the first research topic.
- Use refill ratio relative to consumed/displayed size.
- Compare 250ms versus 2s refill value; the fast bucket may be useful for entry timing, while 2s may be better for classification.

## Thesis 8 - Book Thinning

Book thinning detects top-of-book depth disappearing without matching tape. In Skurry it is phase-gated, with historical notes warning that open/IB behavior differs materially from lunch/afternoon behavior.

Possible LL/EAR use:

- Road/vacuum context, not ownership.
- Warn that price can travel because liquidity left rather than because a sponsor won.

What to validate:

- Rebuild top-N side depth drop from MarketRecorder.
- Compare thinning before synthetic LL/EAR failures and continuations.
- Always stratify by open, IB, lunch, afternoon, and close.

Risk:

- This can easily become a false "signal" if not phase-gated.

## Thesis 9 - Hidden Liquidity

Hidden liquidity logic looks for large traded volume through small displayed size at a price. Side comes from aggressor majority.

Possible LL/EAR use:

- Identify hidden bid/ask defense when displayed size is too small to explain traded volume.
- Add evidence to sponsor-hold classification when Brick says size held despite tape.

What to validate:

- Per-price rolling trade volume versus displayed max size.
- Aggressor majority and subsequent price response.
- Compare to Brick held/gave labels and pressure-field purity.

Risk:

- Needs careful handling around feed artifacts, refresh behavior, and changing displayed depth.

## Important Negative Finding

Udit's docs explicitly warn against a simple "effort with no result means fade" read. Their study treated effort-with-no-result as more continuation than fade. For our work, this means absorption should not be inferred from tape effort alone. It needs contact response: displayed size, consumed size, pulls, refill, and subsequent survival.

## LF/HF Impact

I do not expect Lean, Driver, or raw QI/OFI to redefine LF/HF logic. LF/HF is a rail/failure-state concept. The likely improvements are narrower:

- Brick/refill may classify whether an LF/HF pause actually resolved or failed.
- Road/Horizon may explain whether the failed side had open travel space.
- Pressure purity may improve confidence in which side owns the zone before the LF/HF sequence.

## Proposed Validation Order

1. Brick plus refill contact response around current synthetic LL/EAR rails.
2. Lean plus Driver as execution-timing overlays on existing synthetic LL/EAR events.
3. Road plus Horizon as continuation/no-chase context.
4. Side-aware pressure field as an ownership-quality layer.
5. Book thinning and hidden liquidity as specialized classifiers.

## Validation Standards

Every topic should be tested one thesis at a time:

- Use MarketRecorder NQ data only.
- Generate synthetic LL/EAR bands/logs from MarketRecorder; do not use old live EAR logs from the contaminated MNQ/NQ period.
- Predefine labels, windows, and thresholds before checking outcome.
- Compare against current LL/EAR baseline behavior, not standalone PnL.
- Stratify by session phase.
- Track favorable/adverse excursion, retest quality, and classification error, not just win/loss.
- Keep thresholds adaptive where the source math uses adaptive scaling.
- Treat UI-facing language separately from research labels.

## Immediate Next Research Task

Start with Brick/refill because it directly maps to the unresolved LL/EAR question: when demand consumes supply, or supply consumes demand, did the contacted side hold, give, pull, or refill?

The first script should replay recent MarketRecorder NQ sessions, derive current synthetic LL/EAR zones, and emit one row per contact episode:

- timestamp
- side contacted
- price band
- related synthetic LL/EAR event
- pre-contact displayed size
- consumed size
- pulled size
- refill size at 250ms
- refill size at 2s
- survival ratio
- held/gave/ambiguous label
- forward favorable/adverse excursion

That output gives us a clean topic-by-topic bridge from Udit's math into EAR/LL without relying on the mixed-symbol EAR logs.
