# Direct-Conversion Execution Research

This folder owns the July 23-24 research cycle on direct-conversion execution,
retests, book support, and sponsor lineage.

## Invariants

- Curated episodes generate hypotheses; they do not validate a rule alone.
  Every proposed heuristic needs controls or a broader-population falsifier.
- Keep information phases separate: initial 20-tick proximity, approach to the
  rail, first rail interaction, and later reclaim/re-establishment.
- Sponsor-lineage advance/failure is the structural outcome. Fixed favorable
  excursion is not a substitute.
- Generated outputs live in `out/` and remain ignored. Notes and the episode
  registry are durable.
- Shared capture/replay modules stay in `research/`, `MarketRecorder/research/`,
  and `LevelLedger/research/`. Do not duplicate them here.
- This package is research-only. Do not change EAR or LevelLedger behavior from
  a probe without a separate implementation decision.

## Running Scripts

Run scripts from the repository root:

```powershell
python research\direct_conversion_execution\scripts\<script>.py
```

`scripts/_paths.py` is the path boundary. New scripts should use it instead of
hard-coded parent traversal.
