# BubbleTape - Sparse Footprint Compression

## Intent

BubbleTape compresses aggressor tape into sparse price-time bubbles on a
naked chart. It is an auction-memory overlay, not a signal. Its job is to make
review fast: where did buyers press, where did sellers press, and what did the
next rotation do around that same price area? Trades mode may use live
`Last.TradeId` only when the feed proves non-zero, meaningful identity. On the
current connection this is often `0`, so treat the practical default as
same-side price/time footprint compression.

The indicator deliberately does not use wick/extreme logic. A meaningful bubble
can appear in a candle body, a breakout, a pullback, or a rotation. The unit of
truth is a one-sided execution group at a time/price area. The older bar-level
delta cluster remains available as a comparison source, but it is not the
default read.

## Visual Grammar

- Green means buyer aggression happened there. It is not bullish by itself.
- Red means seller aggression happened there. It is not bearish by itself.
- Bubble diameter is bounded and relative to the active lookback distribution.
- The small white number inside a bubble is the raw size behind the bubble: trade-group volume for Trades mode, absolute delta for Delta mode.
- Finalized bubbles do not shrink, fade, or delete because later opposing
  bubbles are the contested-auction story.
- The currently developing bar may resize until the bar finalizes.
- No CVD is painted; Quantower's native CVD panel already covers that job.
- The optional status panel includes a `basis` row so visible trade bubbles show how many are exchange `TradeId` backed versus fallback price/time groups.

## Design Decisions

- Bubble source is a review setting, not a thesis selector:
  - Trades is the default and shows large execution groups.
  - Delta keeps the original bar/price-band delta-cluster view for comparison.
  - Both is for debugging density, not for live conviction.
- Strength filter is a visibility threshold, not conviction:
  - Low uses the looser percentile and shows more smaller groups.
  - Normal is the live default.
  - High uses the stricter percentile and shows only stronger groups.
- Raw trade size is not winsorized. Large 700-1500 lot executions can be the
  point of the read. Only rendered diameter is capped. When `TradeId` is
  populated with real identity, prints with the same id are grouped before the
  visual threshold is applied; otherwise grouping uses a short same-side
  price/time bucket and should be read like compressed footprint/delta.
- Bubble size stores a frozen 0-1 strength when finalized. User pixel-bound
  settings can change the drawn size, but new market data does not rescale old
  bubble meaning.
- Historical warmup uses `Symbol.GetTickHistory(HistoryType.Last, from, to)` on
  a background task. Live ticks are subscribed first and queued until warmup is
  applied so the handoff does not leave a gap.
- MarketRecorder `book_events.quote_id_hash` identifies resting-book quotes and can validate nearby passive close/reload context in replay, but it is not an execution identity key. Do not regroup BubbleTape bubbles by quote hash without a proven print-to-order mapping.
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
  `HistoryItemLast` exposes buyer/seller fields but not `TradeId`, so
  historical warmup uses the fallback grouping path.
- The bar length is a BubbleTape setting. Set it to match the host chart
  interval, typically 1 or 5 minutes.
- Detection setting changes trigger a warmup reload when historical warmup is
  enabled. Live-only charts can only rebuild from already retained candidate
  clusters, so lowered thresholds do not resurrect groups that were never kept.

- `research/replay_bubbletape.py` mirrors the engine against MarketRecorder tick
  parquet for replay/research. Schema v2 can store `trade_id`, `buyer`, and
  `seller`, but the feed may leave them empty; treat Trades output as
  identity-backed only when the run summary and CSV `identity_backed` field show
  populated identity groups.
