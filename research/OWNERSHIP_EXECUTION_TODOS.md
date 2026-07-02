# Ownership / Execution Decisions and TODOs

These decisions incorporate all 2026-06-23 fixtures, including the late long
campaign. The first section records the implemented live-policy work.

## Implemented 2026-06-23

- **LF/HF scope and precedence:** a fresh adverse LF/HF now pauses flat entry and
  re-arms when that failure object invalidates. In position it cannot override
  an intact current sponsor. Same-sequence sponsor failure is terminal; if a
  base sponsor fails first, a subsequently held LF/HF invalidates the flat retry
  before another base fills. This distinguishes the June 23 13:43 local LF from
  the June 11 sponsor-aligned LF.
- **Directive audit:** `directive_accepted` now persists normalized order,
  context, and add price boundaries.
- **Restart continuity:** old forward-only evidence is not restored. Each new
  engine enforces one full configured book-lookback warm-up and required sample
  count, baselines failure objects held at completion, and exposes its evidence
  state and progress through checkpoint/status.

## Leave unchanged

- **Sponsor lineage and promotion:** current favorable-only, non-overlapping
  promotion is working as designed. The late long promoted lean demand near
  29689.75-29690.50 and exited correctly near 29681 when that sponsor failed.
  The 11:45 exit from the earlier long is not sufficient evidence to constrain
  lean promotion or require a post-ownership retest.
- **Add/epoch qualification:** current guards already consume each root once,
  require an add root to form after the latest fill, serialize pending intents,
  and enforce directive price/size limits. The adjacent 11:30 objects are an
  atypical outcome from a non-primary campaign, not evidence that causal epoch
  identity should be replaced by a spatial-clearance rule.
- **Side-switch and emergency control:** use `CANCEL_DIRECTIVE` for normal
  cancel/flatten/reissue workflow. Reserve `FLAT` for the emergency kill switch;
  no runtime change is required.
- **OFI live policy:** no implementation. Continue initiative-vs-absorption and
  non-z-score candidate research as more sessions are recorded; the first
  fixture does not justify an OFI ownership or direction gate.

## Observed 2026-07-02

- **Post-LF-candidate add before held LF:** EAR's 14:12 short from the
  29486.50-29487.75 supply direct conversion was correct, and sponsor promotion
  down to 29450.50-29452.75 then 29445.25-29447.00 matched the intended
  defensive sequence. The 14:20 add was not HF/LF-assisted; telemetry recorded
  `failure_assisted=false` and a direct-conversion retest of the 29450.50-
  29452.75 consumed supply rail. An adverse demand/LF candidate had already
  formed around 29418.75-29440.00, but it had not yet reached `FailureHeld`, so
  current policy did not block leverage. Net effect was operational rather than
  thesis-damaging: the leveraged sponsor failure completed the parent directive
  and required an explicit `CONTINUE`. Leave unchanged unless this repeats or
  materially degrades execution; possible future questions are whether add
  eligibility should notice fresh adverse failure candidates, or whether adds
  should require current-sponsor alignment rather than any eligible same-side
  direct-conversion rail.
