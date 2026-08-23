# Direct-Conversion Execution Research

This package preserves the research cycle that began with the July 23-24 EAR
episodes and the review of peripheral LOB information around direct-conversion
events.

## Current Conclusion

EAR remains deliberately narrow. The six-day work does not justify replacing
market execution at first 20-tick proximity or changing strict rail-failure
flattening. The strongest unresolved candidate is phase-specific: after an
actual challenge or reclaim, owner support underneath may qualify hold, rearm,
or promotion. Heavy and efficient adverse arrival without support is a shadow
candidate for suppressing adds or exiting provisional exposure.

Start with:

- `notes/DIRECT_CONVERSION_SPONSOR_LINEAGE_2026-07-25.md` for the accumulated
  research record.
- `out/direct_conversion_execution_phase_policy_20260717_20260724/findings.md`
  for the final phase-separated policy audit.
- `episodes/episode_registry.csv` for future targeted cases and controls.

## Layout

```text
direct_conversion_execution/
  AGENTS.md
  README.md
  episodes/
    episode_registry.csv
  notes/
  scripts/
  out/
```

`out/` is generated and ignored. Raw MarketRecorder capture remains outside
this package.

## Episode Method

Record the operator complaint before investigating the tape. Preserve what was
known at decision time, the proposed alternative action, and a falsifier.
Pair intervention candidates with cases where current EAR behavior was correct.
Use the curated set for mechanism discovery, then test any heuristic against
controls and the broader population.

## Reproduce The Final Audit

From `C:\Heatmap`:

```powershell
python research\direct_conversion_execution\scripts\direct_conversion_execution_phase_policy.py
```

The script reads the retained proximity and lifecycle artifacts in `out/` and
rewrites the final policy tables there.
