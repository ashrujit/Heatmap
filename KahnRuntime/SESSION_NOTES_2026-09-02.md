# KahnRuntime Session Notes - 2026-09-02

## NQ Live Campaign Observation

- NQ long campaign `nq-long-campaign-20260902-140106-555581` was an overall
  successful live validation of the Kahn design. It behaved materially better
  than the old EAR pattern would have: it did not immediately scale on every
  visible event, did not promote the sponsor on each new price claim, and held
  the larger campaign long enough to reach the ON/ETH high area.
- The first failed probe was acceptable. The early aggregate footprint and LL
  read were mixed/weak, and Kahn flattened when the root-support evidence
  failed instead of fighting the first read.
- The second probe and later adds matched the intended repaired-continuation
  behavior: adverse repair claims paused leverage, failures of those repairs
  were tracked, and adds came only after later same-side continuation.

## Scale Repair Read

- While the outcome was good, the live read exposed a possible future research
  object: a failed repair claim can become a reload/continuation location, not
  merely a consumed state on the way to the next rail.
- The useful question after a repair fails is not just "did the repair fail?"
  It is:
  - Did failure produce continuation in the repair direction?
  - If not, what claim or liquidity sits below/above it?
  - Does renewed interest appear at, beyond, or back through the failed claim?
  - Is the failed claim re-established, or does price reject it and continue
    the original campaign direction?
- Do not change this yet. The current simpler rule is fair and deliberately
  conservative. Collect more live examples before deciding whether Kahn needs a
  first-class failed-repair/reload state.

## Passive Harvest Read

- The harvest cleanup was also defensible. To keep holding past the target
  floor, price needed immediate extension; it arrived shortly after, but
  continuing would have required additional sponsor/target mechanics and would
  have put a completed trade back at risk.
- Today's behavior was stricter than the intuitive expectation of "take a clip,
  then patiently harvest higher." Kahn submitted a small passive harvest order
  at the floor, then treated the floor loss as a full cleanup condition.
- This should remain unchanged for now. The strict cleanup preserved the core
  purpose of passive harvest: get paid in the objective area without turning a
  completed campaign into a new discretionary hold.

## Current Decision

- No code or policy changes from this single observation.
- Keep gathering live evidence around failed repair, reload, target-floor touch,
  and post-floor extension behavior.
- Revisit only after several comparable cases show that the conservative rule
  repeatedly exits before a mechanically recognizable continuation/reload
  pattern.
