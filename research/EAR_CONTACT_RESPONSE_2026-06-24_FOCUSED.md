# EAR Contact Response Focus - 2026-06-24

Corrected focus: June 24, 2026, 11:50-12:35 ET. This uses the raw-book
rerun of `ear_contact_response_probe.py` plus the live EAR event log at
`C:\Users\j\Documents\ExecAssistantRuntime\events.jsonl`.

## EAR directive lifecycle

| NY time | directive | action | read |
| --- | --- | --- | --- |
| 11:30:04 | `short-113004-6fc0de` | accepted | The 11:30 short idea was armed. |
| 11:31:19 | `short-113004-6fc0de` | short 2 @ 29813.25 | Base entry filled and supply sponsor promoted. |
| 11:54:05 | `short-113004-6fc0de` | add 1 @ 29788.75 | EAR added on `supported_reclaim_candidate`; average became about 29805.08 and BE protection was placed. |
| 11:55:33 | `short-113004-6fc0de` | long 3 @ 29805.00 | BE order filled, flat, directive completed. This is the BE case. |
| 12:04:04 | `short-120404-577ddf` | accepted | Brief replacement short directive. |
| 12:07:03 | `short-120404-577ddf` | cancelled | Human reassessment cancelled it before entry. |
| 12:07:15 | `short-120715-11a40d` | accepted | New short directive armed. |
| 12:09:47 | `short-120715-11a40d` | paused while flat | LF adverse failure paused entry, then cleared at 12:10:15. |
| 12:20:38 | `short-120715-11a40d` | short 2 @ 29770.00 | Base entry filled. |
| 12:22:36 | `short-120715-11a40d` | long 2 @ 29785.00 | Flattened on `sponsor_failed:95`; this was a 15-point adverse exit, not BE. |
| 12:29:10 | `short-120715-11a40d` | invalidated while flat | `LF_sponsor_failed_while_flat` invalidated the directive just before the demand rail failed at 12:30:07. |

## Contact/reload rows

| NY time | side | band | outcome | 30s/60s future | 5s attack | 5s held | 5s depth/reload | read |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | --- |
| 11:51:40 | demand | 29783.00-29783.25 | confirmed | -19.0 / +15.5 | 0 | 0.83 | -2 / -2 | Demand ownership was mixed but adverse to a short hold. |
| 11:52:39 | demand | 29781.25-29782.75 | confirmed | +63.0 / +70.0 | 0 | 0.00 | -18 / -18 | Strong adverse warning for an existing short. |
| 11:54:01 | supply | 29802.00-29803.50 | confirmed | +54.0 / +46.5 | 0 | 0.00 | -24 / -24 | Current grammar saw a clean supply confirmation, but book support vanished. This is a bad add/sponsor-promotion row. |
| 12:15:59 | supply | 29777.00-29778.00 | confirmed | +39.5 / -5.5 | 0 | 0.36 | -7 / -7 | Another weak supply confirmation; not enough to explain a fresh short. |
| 12:26:46 | supply | 29744.75-29748.25 | reset | -36.0 / -24.5 | 17 | 0.00 | -39 / -22 | High attack and downside follow-through; continuation-pressure row, not a current-entry confirmation. |
| 12:28:43 | supply | 29752.25-29755.25 | reset | -76.5 / -49.0 | 23 | 0.08 | -22 / +1 | Best continuation-pressure clue in the corrected window. Current grammar resets it, so EAR does not use it. |
| 12:29:05 | demand | 29751.50-29753.75 | confirmed | +25.0 / -39.0 | 0 | 0.81 | -6 / -6 | Mixed demand confirmation; it should not dominate the prior heavy supply attack by itself. |
| 12:33:03 | supply | 29710.00-29712.50 | reset | -8.5 / -51.5 | 7 | 0.29 | -25 / -18 | Late continuation-pressure row after the break. |
| 12:33:06 | supply | 29710.00-29712.50 | reset | -10.0 / -47.5 | 18 | 0.26 | -20 / -2 | Same read; pressure remains, but this is continuation context rather than a fresh entry. |

## What changed from the earlier read

The 12:50 area is not the relevant short-entry area. The interesting behavior
is 11:50-12:35:

- The 11:30 directive did not exit because the short thesis was cleanly
  disproved. It added at 11:54 on a supply confirmation whose book support was
  already gone, then the add-triggered BE protection flattened the whole
  position at 11:55:33.
- The 12:07 directive did enter later, but it flattened on sponsor failure at
  12:22:36. After that, EAR invalidated while flat at 12:29:10, one minute
  before the demand rail failed and the continuation leg resumed.
- The contact/reload component still does not look like a new candidate
  generator. It is more useful as an add/sponsor-quality veto and as a
  short-horizon "wait, pressure is still present" modifier after a flat exit.

## EAR hooks to test next

1. Add gate: block `supported_reclaim_candidate` adds when the confirming
   sponsor band has no held depth/reload after contact. The 11:54 row is the
   concrete fixture: supply confirmed, but held ratio was 0 and same-side depth
   fell by 24.
2. Sponsor promotion quality: do not promote a filled add to a stronger sponsor
   unless the post-fill band either holds or reloads. This keeps a bad add from
   immediately forcing BE policy onto the whole position.
3. Flat invalidation hysteresis: after a sponsor-fail flatten, avoid immediate
   `LF_sponsor_failed_while_flat` invalidation if the last 30-60 seconds contain
   high-attack same-direction continuation-pressure rows. The 12:28:43 to
   12:30:07 sequence is the fixture.

## Secondary hypothesis: fake failure handling

Do not over-optimize the 12:22 flatten itself. Sponsor `95` was a supply rail at
29773.75-29775.25 and failed by move with the mid around 29784.50, so the
current price-only sponsor-failure rule was mechanically doing what it is
designed to do.

The better research target is what happens after that base-only sponsor-fail
flatten:

- current policy rearms after a base-only sponsor failure, but sets an
  awaiting-sponsor-aligned-failure latch;
- the next fresh adverse LF/HF while flat becomes terminal invalidation;
- on this replay, the LF at 12:29:10 invalidated the directive, then that same
  demand rail failed at 12:30:07 while supply-pressure rows were already
  appearing.

That suggests a two-stage classification: a price-only sponsor failure can still
flatten risk, but terminal flat invalidation should require the adverse failure
object to survive a short hysteresis window and not be contradicted by
same-direction contact pressure. This is where "fake failure" handling belongs
first, before weakening the actual positioned flatten rule.

The expected effect remains fewer false positives and fewer bad adds, not more
early entries. In this focused window it also suggests fewer premature flat
invalidations after the first short attempt has already been stopped.
