# Codex Design Thoughts

These are design-level improvement ideas after reading the code, docs, and research notes. They assume the core philosophy is correct:

> Surface microstructure structure; do not classify, confirm, predict, or outsource judgment from the trader to the indicator.

## My Read Of The Philosophy

The suite is not trying to build a mechanical signal. It is trying to make normally invisible auction mechanics visible enough that a skilled trader can read them in context.

That distinction matters. A lot of order-flow tools fail by naming a shape and then smuggling in a meaning: "absorption means reversal", "pulling means continuation", "imbalance means trapped traders." This project is more mature than that. It treats a shape as evidence, not a verdict.

So the design test for any improvement should be:

- Does it make raw structure easier to see?
- Does it preserve ambiguity where ambiguity is real?
- Does it help the trader notice change earlier without pretending the change has one fixed meaning?
- Does it avoid adding another colored thing that demands interpretation but gives no context?

## What I Would Improve

### 1. Make LiquidityMeter's "cum" semantically exact before adding features

The meter's central idea is strong: ROC is the warning shot, cum joining ROC is the meaningful shift. But that depends on cum really representing the chosen anchor horizon.

I would fix this before manual anchoring, extra modes, or new event types. The meter should be brutally honest about its time base:

- Rolling 30m means exactly rolling 30m.
- Session means since NY 09:30.
- Load means since load.
- Future manual trade anchor means since the trader clicked.

If old event retention must be bounded, compact old events into time buckets rather than silently losing them.

### 2. Decide whether live meter measures event onsets or sustained pressure

The research script suppresses duplicate events; the live meter does not. Neither choice is inherently wrong, but they answer different questions.

Onset mode asks: "When did the book regime change?"

Sustained-pressure mode asks: "How long has the book stayed abnormal?"

For your philosophy, I slightly prefer onset mode for cum and sustained mode for VOD. Cum should not overcount one persistent state as many independent votes. VOD, however, probably should glow brighter when chaos persists.

A clean version could expose both internally:

- `event_onsets`: feeds cum/ROC
- `sustained_excursion`: feeds intensity/glow or a small persistence cue

No labels, no classifier. Just separate "new information" from "continued condition."

### 3. Add manual anchor, but keep it humble

Manual click-anchor seems like the most natural next feature once cum semantics are fixed. The trader's real question is often not "what is the 30-minute book lean?" but "since I entered or started caring about this level, has provider behavior confirmed or contradicted the thesis?"

I would keep the interaction minimal:

- One click or hotkey sets anchor at current time.
- A small anchor marker appears near the meter.
- The label changes to `cum@anchor`.
- A second action clears back to the configured default.

I would not add trade labels, entry/exit state, PnL coloring, or "long/short mode." That would push the tool toward trade management automation instead of contextual reading.

### 4. Treat forced-flow divergence as a first-class context cue

The 2026-05-06 squeeze note is important. I would not change the meter math to "handle" squeeze regimes. I would make divergence more visible.

The useful concept is:

> Provider commitment and price direction can decouple. When they decouple persistently, the regime itself is information.

A possible addition:

- Track short-term price drift direction.
- Track short-term cum/ROC direction.
- When price and provider lean diverge while VOD is active, show a small neutral divergence mark near the VOD strip.

This should not say "invert signal" or "squeeze." It should simply surface: price and providers are not agreeing, and the book is noisy.

### 5. Give A/E primitive visibility toggles

A/E's primitives are intentionally independent. The docs already say disabling a noisy primitive is valid. I would make that explicit in the settings.

Add booleans:

- Enable A1
- Enable A2
- Enable E1
- Enable E2

This improves live tuning without changing the philosophy. It lets the trader subtract a shape that is not earning its screen space in a given product/session.

### 6. Consider per-primitive visual fingerprints, but keep the persistent band semantic

Right now the persistent layer is price-and-direction first, which is correct. I would not turn the chart into labeled event confetti.

But for the short-lived glyphs, a tiny primitive-specific shape could help post-session review:

- A1: small square
- A2: small circle
- E1: small diamond
- E2: small tick/triangle

The persistent band should remain direction/price/count based. The primitive type should be a transient hint, not the main visual grammar.

### 7. Make capture harder to accidentally disable

The research loop depends on capture continuity. The 2026-05-06 capture gap happened because settings reverted after indicator changes.

I would improve this operationally, not mathematically:

- Log a loud Quantower system message when capture is disabled at init.
- Optionally render a tiny off-chart/status text only when capture is expected but off.
- Consider defaulting capture to enabled once stability is trusted.
- Or split capture into a tiny dedicated indicator whose only job is recording, so display changes do not reset research collection.

The last option adds deployment surface, but it reduces the chance that visual iteration breaks data continuity.

### 8. Build one replay/fixture harness, not an optimizer

I agree with avoiding parameter sweeps and fake precision. But a small deterministic fixture harness would be valuable.

Purpose:

- Feed captured snapshots/ticks through the C# logic.
- Verify live C# output matches research scripts for known windows.
- Protect design fixtures from accidental drift.

This is not optimization. It is conservation of meaning. The suite is driven by a few carefully studied moments; those moments should become regression fixtures.

### 9. Standardize the docs for future agents

The docs are genuinely useful, but `AGENTS.md` and `CLAUDE.md` now disagree. Since future Codex sessions will privilege `AGENTS.md`, I would standardize on that name or make each `AGENTS.md` a short pointer to the corresponding `CLAUDE.md`.

The content should stay as it is: decisions, invariants, why-not explanations, and gotchas. That is exactly the right kind of documentation for this project.

## My Preferred Next Sequence

If this were my repo, I would do the next iteration in this order:

1. Fix LiquidityMeter cum retention/anchor semantics.
2. Decide and document onset-vs-sustained event behavior; make live match research if onset is intended.
3. Add a small fixture harness for the 2026-05-05 win/loss windows.
4. Add manual anchor.
5. Improve forced-flow divergence visibility through a neutral context cue.
6. Add A/E primitive toggles.
7. Clean up doc naming.

The north star I would keep repeating: make the trader's read faster and cleaner, but never pretend the tool knows what the auction means.
