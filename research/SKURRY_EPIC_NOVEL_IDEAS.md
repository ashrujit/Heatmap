# Skurry Epic Branch Novel Ideas

These are parked notes from reading the Skurry epic branches. They are not part
of the robustness pass and should not be folded into current indicators without
separate auction-design review.

## Current Status

- **Post-event refill:** implemented in LevelLedger as R+/R- refill badges. This
  idea is no longer an open candidate unless we later want a separate tuning pass.
- **Book thinning:** researched against 2026-05-28, 2026-05-29, and 2026-06-01
  NQM6 captures using the Skurry detector recipe. Parked for now. The replay
  suggests thinning is better treated as vacancy / do-not-lean-here context
  until a later demand or supply lean resolves ownership; it is not a standalone
  directional object yet.
- **QI vs TFI divergence:** researched against the same captures. Parked for
  LevelLedger and not ready for LiquidityMeter UI. Strict Skurry-style pressure
  thresholds produced no durable intervals; relaxed thresholds produced sparse
  but noisy disagreement. Keep as possible right-edge / LiquidityMeter research
  vocabulary, not a chart or panel object.

## Candidates To Discuss

- **L2 absorption at sub-second cadence:** visible size is eaten, but price does
  not yield. Possible LevelLedger evidence row or rail-strength enrichment.
- **Post-event refill:** after a sweep or stop-run, measure whether liquidity
  refills within fast and slow windows. Implemented as R+/R- in LevelLedger.
- **Book thinning:** top-N depth disappears with too little tape to explain it.
  Possible ContextMap / LevelLedger evidence for air pockets or passive
  abandonment. Researched and parked; needs post-event lean coupling before any
  trader-facing display.
- **Reload-zone / magnet aftermath:** repeated aggregate-only defense promotes a
  price region, then later resolves as held, broken, or expired. Useful, but it
  changes how we represent regional evidence and needs careful UI discipline.
- **Hidden-liquidity mismatch:** heavy tape through a price that never advertised
  much visible size. Potential confluence marker, not a standalone signal.
- **QI vs TFI divergence:** compare depth-weighted book imbalance with recent
  trade-flow imbalance. This may sharpen LiquidityMeter's "book says X, tape
  says Y" read. Researched and parked; not enough improvement over LiquidityMeter
  cum/ROC + VOD to justify a live display change.
- **Separate temporal register:** a right-edge pane for sub-second moments while
  the chart carries persistent auction structure. Worth discussing only if the
  current chart overlays become too dense.

## Guardrail

Do not import these directly during infra work. Each one changes trader-facing
auction semantics and needs a fixture/read-review pass before implementation.
