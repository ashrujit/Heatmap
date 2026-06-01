# Skurry Epic Branch Novel Ideas

These are parked notes from reading the Skurry epic branches. They are not part
of the robustness pass and should not be folded into current indicators without
separate auction-design review.

## Candidates To Discuss

- **L2 absorption at sub-second cadence:** visible size is eaten, but price does
  not yield. Possible LevelLedger evidence row or rail-strength enrichment.
- **Post-event refill:** after a sweep or stop-run, measure whether liquidity
  refills within fast and slow windows. Strong candidate for distinguishing
  defended levels from one-and-done clears.
- **Book thinning:** top-N depth disappears with too little tape to explain it.
  Possible ContextMap / LevelLedger evidence for air pockets or passive
  abandonment.
- **Reload-zone / magnet aftermath:** repeated aggregate-only defense promotes a
  price region, then later resolves as held, broken, or expired. Useful, but it
  changes how we represent regional evidence and needs careful UI discipline.
- **Hidden-liquidity mismatch:** heavy tape through a price that never advertised
  much visible size. Potential confluence marker, not a standalone signal.
- **QI vs TFI divergence:** compare depth-weighted book imbalance with recent
  trade-flow imbalance. This may sharpen LiquidityMeter's "book says X, tape
  says Y" read.
- **Separate temporal register:** a right-edge pane for sub-second moments while
  the chart carries persistent auction structure. Worth discussing only if the
  current chart overlays become too dense.

## Guardrail

Do not import these directly during infra work. Each one changes trader-facing
auction semantics and needs a fixture/read-review pass before implementation.
