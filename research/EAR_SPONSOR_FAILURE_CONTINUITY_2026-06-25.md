# EAR Sponsor Failure Continuity - 2026-06-25

This note looks only at sponsor-failure continuity, not the opening liquidation
drive.

## Current coordinator behavior

After a base-only sponsor failure, the same directive preserves more state than
a fresh directive:

- `_baseAttempts` remains incremented;
- `_lastSponsorClear` records the failed sponsor and flatten reason;
- `_freshRootAfterUtc` moves to the flat time, forcing future base roots to be
  newly formed after the failed attempt;
- the directive can rearm until expiry / max base reentries, unless a terminal
  sponsor-aligned LF/HF invalidation fires.

A fresh directive sees the current evidence engine map, but loses this campaign
sequence. It has no previous sponsor clear, no pending state, no used roots, and
no base-attempt history.

## 10:53 short base failure

Directive `2026-06-25-directive-short-103853-583119`:

| ET | event | read |
| --- | --- | --- |
| 10:38:53 | directive accepted | short, context 29300-29800, order 29600-29800 |
| 10:53:28 | entry short 2 @ 29758 | direct conversion from consumed supply `28`, 29762.25-29767.25 |
| 10:54:58 | sponsor `28` failed | supply failed by move, mid 29773.25 |
| 10:54:58 | flat and rearmed | base-only sponsor failure, not terminal |
| 10:55:59 | demand `31` owned | opposite-side repair at 29737.75-29738.50 |
| 10:56:33 | demand `31` failed | repair gave way, but no nearby same-side supply support emerged |
| 11:08:53 | directive expired | no second entry |

The sequence after the flatten was not immediate same-side handoff. It was
opposite-side repair, then that repair failed. Under current supported-reclaim
rules, a short reentry needs the adverse demand rail to fail while suitable
same-side supply support is live nearby. That second ingredient did not appear
near the failed demand rail, so same-directive rearm had no clean entry.

This is different from the June 24 12:29 case, where a flat invalidation killed
the directive before the failure/continuation sequence could fully play out.

## 12:38 short sequence to 5 contracts

Directive `2026-06-25-reissue-short-123800-9acb6c`:

| ET | event | read |
| --- | --- | --- |
| 12:38:12 | short 2 @ 29684.75 | supported reclaim: failed demand `80`, supply support `83` |
| 12:38:35 | short 2 @ 29698.25 | logged as another `EnterBase`, direct retest of supply `83` |
| 12:39:38 | sponsor promoted to `84` | lower supply `29690.25` |
| 12:39:57 | add 1 @ 29686.75 | direct retest of sponsor `84`, position to 5 |
| 12:40:40 | sponsor promoted to `85` | lower supply 29680.50-29682.25 |
| 12:41:05 | sponsor `85` failed | flattened 5, campaign completed |
| 12:41:12 onward | demand repair / residual failure | confirms exit was well placed |

Auction-wise this looked correct: EAR accepted nearby same-side handoffs, added
only after newer lower supply appeared, and flattened when the current sponsor
failed. The residual repair after the exit makes the flatten read sensible.

Implementation caveat: the second 2-lot at 12:38:35 was logged as
`EnterBase`, not `Add`. It appears to come from a pending direct-retest path
for supply `83` that survived the first base fill. `OnPositionChanged` clears
`_pendingEntryIntent` on fill but does not clear `_pendingRetest` unless the
position goes flat, pauses, invalidates, or recovery starts. That allowed a
flat-created pending retest to fire while already base-only, preserving its
`IsAdd=false` flag.

The outcome was acceptable here, but the role semantics are suspect. If the
intent is to allow a second base-sized entry after first fill, it should be an
explicit policy. If not, `_pendingRetest` should be cleared on any filled entry,
or revalidated against current state before firing.

## Working conclusion

The sponsor-failure problem is not solved by forcing fresh directives. Same
directive rearm has the right memory shape. The next question is narrower:

1. Should base-only sponsor failure preserve two more attempts? Probably yes,
   but only inside the same directive, not via manual reissue.
2. What sequence should qualify the next attempt? Either:
   - a new same-side sponsor forms after the flat time and is retested within
     distance; or
   - an adverse repair rail fails while a nearby same-side sponsor/support is
     live.
3. What should not qualify? A naked adverse repair failure with no same-side
   support nearby.

The 10:53 sequence falls into the third bucket. The 12:38 sequence mostly falls
into the first bucket, with a code-level caveat around stale pending retest
state.
