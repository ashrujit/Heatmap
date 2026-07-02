# EarDispatcher - EAR Operator Console

## Intent

`EarDispatcher` is a small WinForms front end over EAR's existing JSON file
transport. It replaces the low-reasoning Codex dispatch loop with deterministic
controls, but it deliberately does not become a planning tool.

## Design Decisions

- The app shells out to `skills\exec-asst\scripts\earctl.py` instead of writing
  runtime files directly. `earctl` remains the single operator transport for
  atomic writes, schema validation, acknowledgement waits, reissue, cancel, and
  `FLAT`.
- The UI accepts compact price shorthand, but every shorthand price is expanded
  from the editable base field and previewed as a full price before dispatch.
  Hidden price inference is not allowed.
- The app is keyboard-first and visually close to a console because it is an
  execution utility, not an analysis surface.
- Parsed operator summaries are the default output. Raw JSON remains available
  from the right-click debug toggle, but routine status/validate/dispatch should
  be readable without scanning transport payloads.
- `Always on top` is a right-click toggle because it is useful during active
  execution but should not consume permanent screen real estate.
- `campaign` maps to EAR scaling. When campaign is enabled, the app derives the
  add/campaign range from the order edge to `HARD_TP` (order low to TP for
  longs, TP to order high for shorts) and expands the outgoing EAR context
  envelope as needed. The Order field is the executable entry gate; Context is
  the evidence envelope and may be auto-derived from Order plus Target. When
  disabled, it sends `--no-adds`, `add_quantity=0`, and
  `max_position_quantity=base_quantity`.
- EAR's checkpoint is authoritative for the instance quantity ceiling. The max
  field is still visible so a stale or absent checkpoint cannot hide what will
  be sent.
- Tags are stored inside the directive `notes` string because the v1 directive
  schema does not permit arbitrary metadata properties.
