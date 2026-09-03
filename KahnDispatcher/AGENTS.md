# KahnDispatcher - Kahn Campaign Operator Console

## Intent

`KahnDispatcher` is a compact WinForms front end over `kahnctl.py`. It imports
passive `SaavikProbe` sketches, previews the resulting Kahn campaign contract,
and shells out to the existing transport helper for validation, active dispatch,
`CANCEL`, and `FLAT`.

It is an execution utility, not a planning surface. Auction judgment still comes
from the trader, Prep, or Saavik; the dispatcher only makes the mechanical Kahn
campaign handoff less error-prone.

## Design Decisions

- Keep `skills\saavik\scripts\kahnctl.py` as the transport boundary for schema
  assembly, active stamping, atomic writes, flat-ready supersession checks, and
  profile-local control writes.
- Use the same compact terminal-style operator surface as EAR: `Cascadia Mono`,
  dense text fields, and a build-embedded icon. This console is for repeated
  dispatch work, not broad form exposition.
- Keep the runtime state tile compact and near the profile selector. It is a
  fast operator read, not a second status panel: green `READY` means flat/Ready,
  yellow `ARMED` means active but flat, red `IN POS` means the bound runtime
  has exposure, and gray/orange states mean stopped, stale, path, or control
  safety issues.
- Runtime profiles bind the Kahn runtime directory and its passive
  `saavik-probe.json` path together so sketch import and dispatch cannot point
  at different ES/NQ profiles by accident.
- `SaavikProbe` import is form-fill only. It may set side, root/probe range,
  middle scale corridor, and harvest range; it must not change sizing, scale
  mode, TTL, retry, notes, or dispatch state.
- The dispatcher derives `arena` from the probe + middle + harvest envelope.
  In scale mode it also emits the probe/root range as `no_add` and the middle
  range as `press`. Otherwise Kahn's arena fallback can legally scale inside the
  root probe after a repaired-continuation sequence, which is not the operator
  intent for the three-box sketch. Do not emit the middle range as a Kahn
  `evaluate` waypoint from this UI: that role locks leverage, while the operator
  intent here is a non-harvest scale corridor.
- `new-draft --dispatch --activate` is the direct Kahn campaign handoff used
  here. Do not borrow `dispatch-draft` timestamp/id aliases unless `new-draft`
  exposes them; it already defaults created/not-before timestamps to now.
- Probe-only mode sends `scale_mode=root_only` and forces `max_qty=probe_qty`
  in the outgoing command while leaving the visible Max field unchanged.
- Scale mode sends `scale_mode=scale_allowed` and requires the visible Max value
  to exceed Base before shelling out.
- The visible "replace flat" switch maps to
  `--retire-existing-if-flat`. It only permits replacement of an existing Kahn
  campaign when the runtime is already flat and Ready; it is not a flattening or
  cancel command.
- When replacement is rejected as unsafe, append `preflight` diagnostics in the
  dispatcher output. The generic rejection text is not enough for live use
  because stale control, stale checkpoint, stopped runtime, path mismatch, and
  non-flat position require different operator actions.
- `CANCEL` and `FLAT` retain Kahn semantics: cancel retires only when flat;
  FLAT may close the bound runtime position.
