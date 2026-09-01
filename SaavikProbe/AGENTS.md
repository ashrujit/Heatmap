# SaavikProbe - Passive Kahn Campaign Sketch

## Intent

`SaavikProbe` is the Kahn-specific successor to `DirectiveSketchProbe`. It uses
the Quantower chart as a spatial input surface for a proposed campaign probe,
middle scale corridor, and harvest area, then writes a separate JSON draft for
`KahnDispatcher` to import.

The probe is deliberately passive. It must not write `campaign.json`, issue
`control.json`, dispatch, flatten, cancel, or infer execution permission.

## Design Decisions

- The first rectangle is the proposed Kahn root / `trap_probe` area.
- The second rectangle is the middle scale corridor. It separates probe from
  paid harvest so Kahn does not stage passive exits as soon as price leaves the
  probe box.
- The third rectangle is the proposed harvest / target area. Its far edge is
  the side-aware target price.
- The JSON output uses Kahn vocabulary (`root_range`, `middle_range`,
  `harvest_range`) instead of EAR's `order_context_range` so downstream code
  cannot silently treat the draft as an EAR directive.
- The probe captures absolute chart prices. Any shorthand expansion, sizing,
  scale intent, TTL, active status, and profile selection belongs to
  `KahnDispatcher`.
- Idle mode only hit-tests the fixed panel. Ordinary chart clicks and drags pass
  through to Quantower until the operator explicitly arms capture from the panel.
- The output path is an input parameter because ES and NQ Kahn runtimes should
  keep sketch drafts under their own profile directories.
