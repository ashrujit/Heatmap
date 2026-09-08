# Schema 2 Cutover

Build verification is not release authorization. After offline acceptance, the
user authorized installation; see [RELEASE_2026-09-07.md](RELEASE_2026-09-07.md)
for installed artifacts and the still-pending activation/broker checks. Active
campaign/control files were not changed.

1. Before release, verify the intended profile paths, execution/data symbol and
   account. Confirm actual flatness and no unresolved entry/add/close, not merely
   a Ready or Retired phase. Keep old binaries and campaign/control files for rollback.
2. Stop the old instance only after checking exposure and protection. Install the
   separately authorized binaries and restart Quantower; cached assemblies are
   not replaced merely by copying a DLL. Verify the loaded binary provenance.
3. Old campaigns remain audit-readable but schema-1 runtime admission is rejected.
   Use `kahnctl.py convert-draft --draft old.json` for a preview. Name each obsolete
   constraint with `--remove-waypoint ID`; use `--derive-arena` only deliberately.
   `--out` must name a new draft file. Conversion never dispatches or rewrites source.
4. Review retained/removed constraints and the unchanged entry expiry. Reissue the
   reviewed draft with explicit timestamps/TTL before dispatch. Do not infer that
   conversion extended its lifetime. A schema-2 draft must not contain `press` or
   `no_add`; other explicit risk/review/target constraints remain authoritative.
5. Dispatch loads WATCH. Check the acknowledged campaign ID/digest, runtime
   instance ID, quantity, warmup and health. GO LIVE authorizes that exact watched
   campaign, not an immediate entry; a flat restart requires fresh GO LIVE.
6. In a bounded shadow/test-account trial, verify first/partial/terminal order
   reports, protection resizing, rejection and reconnect behavior, operator BE,
   target harvest and FLAT late-fill reconciliation. A file write or submit
   acceptance is not a fill, flatness acknowledgement, or production acceptance.

`BE` rejects flat, offside, stale, wrong-attempt and unreconciled exposure. It
preserves tighter protection and shares terminal BE retirement. CANCEL is flat-
only with no unresolved orders; use FLAT for exposure. No automatic BE reentry,
GEX execution gate or post-cap sponsor advancement is part of this release.
