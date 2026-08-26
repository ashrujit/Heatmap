# KahnRuntime.Replay - Offline Campaign Runner

## Intent

`KahnRuntime.Replay` is a local console harness for Kahn policy research. It
loads the same campaign and evidence contracts as the Quantower strategy, runs
the same deterministic policy engine, and writes comparable JSONL decisions.

## Design Decisions

- Replay defaults to input order. Historical evidence files may contain
  hand-curated event order where exact timestamps are approximations.
- Replay context time is the evidence timestamp, not wall-clock time. Campaign
  expiry therefore tests the historical slice, not today's date.
- Replay may simulate fills after `ALLOW_PROBE`, `ALLOW_ADD`, `REDUCE`,
  `FLATTEN`, or `RETIRE`, but those are state-machine simulations only.
- Do not add broker, account, or Quantower order dependencies here. If replay
  needs fills, encode them as evidence or let the simulation apply accepted
  decisions.
- Human-readable reports are derived from replay JSONL after the run. Keep the
  JSONL decision log as the source of truth and treat Markdown as research
  presentation only.
