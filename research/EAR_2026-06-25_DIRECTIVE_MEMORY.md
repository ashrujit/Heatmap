# EAR Directive Memory Focus - 2026-06-25

This note separates the June 25, 2026 opening short directive from the later
base-only sponsor-failure continuity question.

## 09:32 opening short directive

Directive `2026-06-25-directive-short-093251-771f15` was accepted at 09:32:51 ET.
It was live, not warming:

- order range: 30062-30200
- context range: 29750-30200
- target: 29750
- state: `Armed`

Why no entry:

- The useful supply ownership around the open had already fired. Supply `13`
  owned at 09:30:23 in 30158.25-30163.00, with the market already near
  30142.75. A directive accepted at 09:32:51 cannot replay that `RailOwned`
  transition.
- By the time fresh evidence appeared under the active directive, it was demand:
  demand `14` owned at 09:34:14 in 30048.00-30049.50, and the derived LF held at
  09:34:24. That paused the short while flat.
- The directive was manually cancelled at 09:36:58, before the LF invalidated at
  09:37:33 and the demand rail failed at 09:37:36.

Would a pre-open directive have helped:

- If allowed to trade before 09:30, probably yes mechanically: supply `12`
  owned at 09:28:40 and retested around 09:28:58 near 30162, inside the later
  directive's price envelope. That would likely have entered before RTH open,
  but the same sponsor failed on the 09:30 opening drive, so it likely would
  have been a bad pre-open fill.
- If armed before open but constrained to `not_before=09:30`, probably not. The
  next useful supply ownership at 09:30:23 was already too far below the supply
  band for direct conversion, so EAR would have waited for a retest that never
  came before lower demand/LF evidence appeared.

The opening miss is therefore not primarily a missing contact/reload feature.
It is a directive timing and transition-replay boundary: EAR does not turn
already-fired supply ownership into an entry after the directive arrives.

## Pause-release hypothesis

The 09:34 LF did not fail a sponsor. It was a flat-entry pause object: demand
owned, demand held, and EAR correctly paused a short while flat. It then
invalidated at 09:37:33 and the parent demand rail failed at 09:37:36.

This is a distinct auction pattern:

- normal LF/HF pause: price moves away, goes back to ask the originating
  sponsor, and the sponsor's response decides whether a new directive-quality
  sponsor is needed;
- release-style LF/HF pause: the originating sponsor is not meaningfully
  reclaimed, or is quickly rejected, and price continues through the LF/HF area
  in the directive direction. The LF/HF area becomes the last fill zone for
  participants who hesitated.

Current EAR only resumes waiting after the pause clears. It does not treat the
clearing of the pausing LF/HF as an auction result. That is conservative and
prevents chasing, but in fast directional auctions it means no fresh evidence
appears until price has displaced far away from the business area.

The possible research target is therefore not "enter on every pause clear." It
is to classify flat-entry pause resolution:

- if the pausing LF/HF clears against the directive, keep blocking or invalidate;
- if it clears in the directive direction but price is already outside the
  directive's order envelope, do not chase;
- if it clears in the directive direction while still inside a trader-approved
  continuation envelope, allow a controlled continuation/retest path that uses
  the failed LF/HF zone as the reference, not a brand-new sponsor requirement.

This preserves the pause mechanism while acknowledging that a failed pause is
itself information about auction acceptance.

## Fresh directive memory

A fresh directive does not start the evidence engine from scratch. Current live
rails, candidates, and held failure objects are still in the engine unless the
runtime restarted or book continuity was lost.

But a fresh directive does reset campaign/coordinator memory:

- no previous sponsor lineage;
- no base attempts;
- no pending direct-retest or supported-reclaim state;
- no used root ids;
- no last sponsor clear context;
- existing held LF/HF objects are baselined as context at acceptance.

So a fresh directive sees the surrounding map, but not the sequence. It can use
an existing live rail as support for a later fresh trigger, but it cannot replay
an old `RailOwned` transition and it cannot know that a new rail is a handoff
from the just-flattened sponsor in a prior directive.

## Continuity implication

The cleaner design question is whether base-only sponsor failure should preserve
the directive's remaining attempts and campaign context. Current same-directive
rearm already preserves more state than a fresh directive:

- `_baseAttempts` remains incremented;
- `_lastSponsorClear` records the cleared sponsor and flatten reason;
- `_freshRootAfterUtc` forces new roots after the flat time;
- the directive can continue until expiry/max reentries unless terminal LF/HF
  invalidation fires.

That makes "continue inside the same directive after base-only sponsor failure"
the better place to solve continuity. Requiring a human reissue throws away the
very sequence needed to decide whether the failure was thesis death or just a
handoff/reset inside the same campaign idea.
