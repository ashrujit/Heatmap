# BubbleTape - Sparse Footprint Compression

## Intent

BubbleTape compresses L1 aggressor tape into sparse price-time bubbles on a
naked chart. It is an auction-memory overlay, not a signal. Its job is to make
review fast: where did buyers press, where did sellers press, and what did the
next rotation do around that same price area?

The indicator deliberately does not use wick/extreme logic. A meaningful bubble
can appear in a candle body, a breakout, a pullback, or a rotation. The unit of
truth is a time bar plus nearby price band with one-sided aggressive volume.

## Visual Grammar

- Green means buyer aggression happened there. It is not bullish by itself.
- Red means seller aggression happened there. It is not bearish by itself.
- Bubble diameter is bounded and relative to the active lookback distribution.
- Finalized bubbles do not shrink, fade, or delete because later opposing
  bubbles are the contested-auction story.
- The currently developing bar may resize until the bar finalizes.
- No CVD is painted; Quantower's native CVD panel already covers that job.

## Design Decisions

- Detail is a visual-density setting, not a model term:
  - Low detail uses the stricter percentile and shows only major landmarks.
  - Normal detail is the live default.
  - High detail shows smaller local assertions for review.
- Raw trade size is not winsorized. Large 700-1500 lot executions can be the
  point of the read. Only rendered diameter is capped.
- Bubble size stores a frozen 0-1 strength when finalized. User pixel-bound
  settings can change the drawn size, but new market data does not rescale old
  bubble meaning.
- Historical warmup uses `Symbol.GetTickHistory(HistoryType.Last, from, to)` on
  a background task. Live ticks are subscribed first and queued until warmup is
  applied so the handoff does not leave a gap.
- Lookback is calendar-day based, not trading-session based. This keeps weekend
  handling predictable without adding exchange-calendar assumptions; the default
  is three days so Sunday/Monday startup can still see Friday context.
- The raw warmup tick list is a transient load buffer. Once it has been folded
  into candidate bars and frozen bubbles, the completed task/result is released
  so a chart left open all week retains only the bounded lookback state.

## Current Constraints

- Warmup quality depends on the broker/history feed preserving
  `AggressorFlag`. Prints with `None` or `NotSet` contribute to total volume
  but not delta, matching the MarketRecorder research data.
- The bar length is a BubbleTape setting. Set it to match the host chart
  interval, typically 1 or 5 minutes.
- The first live version rebuilds visible bubbles from retained candidate bars
  when detection settings change. That is an explicit settings action, not
  automatic rescaling from later market data.
