# 2026-06-23 Hypothetical Short After 13:10

## Question and assumptions

Evaluate a short directive beginning after 13:10 with an order-price range of
29790-29950 and a hard target of 29615. `20615` is treated as a typo because the
session traded in the 29xxx handle. Unless stated otherwise, the directive uses
the normal 30-minute entry window and permits `direct_conversion` and
`supported_reclaim`.

This is a counterfactual execution fixture, not evidence that LL, EAR, or OFI
predicts direction.

## Verdict

The short thesis and target were structurally valid, and the explicit price
range would have admitted materially better inventory than the late directives.
The durable EAR-compatible entry was the 13:37:36-13:37:39 supply conversion,
with a second supply conversion at 13:39:17-13:39:18. Their 29882 and 29861
supply bands remained owned through at least 14:10 and in the longer replay
through the eventual target sequence.

Current EAR policy still would not have held that position to 29615. The 13:43
LF would have flattened or invalidated the short even though its demand rail
failed at 13:45:05 and the upstream supply owners survived. OFI confirmed that
the LF was real local demand, but did not show that it had displaced the broader
supply lineage. The primary defect is therefore LF scope and its precedence
over the existing sponsor state, not sponsor promotion or missing OFI direction
confirmation.

## Operational constraint at 13:10

At 13:10 the prior long directive was leveraged with three contracts. It did
not flatten until the 13:13:15 HF at about 29869.75, and the runtime stopped at
13:13:22. A contrary short could not simply replace it. The counterfactual
requires one of:

1. cancel/flatten the long and arm the short before the 13:13 supply evidence;
2. arm a fresh short immediately after the long completed and avoid the restart;
3. after the restart, issue a fresh short id and accept that evidence state has
   restarted.

The uninterrupted offline replay converted the pre-restart demand candidate to
supply at 13:13:59. Actual EAR lost that candidate on restart.

## Grey/no-owner constraint

The active grey/no-owner envelope around this decision was approximately
29837.50-29896.50. That disqualifies a naive claim that price movement inside
the range proved seller ownership. The entry becomes valid only when new
post-contest evidence appears. The 13:37 and 13:39 demand-to-supply conversions
provide that evidence; the raw 13:13 lean rail by itself does not.

## Evidence sequence

| Time | Evidence | Execution meaning | OFI read |
|---|---|---|---|
| 13:12:50-13:13:15 | Supply 29878.75-29879.25 owned, tested, held; HF flattened the long | Good local short/reversal evidence, but not yet durable lineage | Event OFI 3s/5s was -20.9/-22.2 at ownership and -47.2/-27.6 at HF, supporting supply |
| 13:13:59 | Uninterrupted replay converts 29871.75-29873 demand to supply | Earliest post-long direct conversion if the runtime had not restarted | Supply-aligned event OFI was positive at 3s/5s, but mixed by 10s |
| 13:21:37 | The 29871.75-29873 supply sponsor fails | Early entry was local only; it had about 45.5 points MFE before reversing | No OFI rule repairs the sponsor failure |
| 13:29:01-13:36:08 | Supply conversion at 29885.25-29888.25, then failure above 29895 | First post-restart direct conversion; about 49.75 points MFE, then sponsor failure | OFI 3s/5s was +11.9/+18.7, opposing supply; filtering this one would help |
| 13:36:48 | Supply lean owns 29885.25-29887.75 | Supporting parent for the next conversion; raw lean ownership is not itself an allowed entry resolution | OFI was mixed: +1.4 at 3s, -18.0 at 5s |
| 13:37:36-13:37:39 | Demand converts to durable supply near 29882; trigger near 29867 | Best EAR-compatible base entry inside 29790-29950 | OFI was mixed across horizons, not a clean qualifier |
| 13:39:17-13:39:18 | Second demand conversion creates supply near 29861 | Possible add/newer confirmation; both durable supply bands remain owned | OFI again mixed: +6.2 at 3s, -1.2 at 5s |
| 13:43:01-13:43:20 | Local demand conversion and LF near 29837-29843 | Current policy terminates the short after roughly 25 points from the durable base | OFI +37.0/+28.7 supports the local demand response |
| 13:45:05 | The LF's demand rail fails | Demonstrates that the LF was local opposition, not failure of the broader short | Supply lineage remains intact |
| 13:50 | Price returns below prepared 29790-29794 supply | Upper acceptance failure becomes explicit; chasing now has worse inventory | Context, not a new entry oracle |
| 14:40-14:50 | 29690-29694 demand breaks; lower business changes from building to accepted | Confirms the second leg needed for the hard target | Target 29615 trades between about 14:45:42 and 14:45:59 |

## Counterfactual under current EAR policy

With a fresh short active after the restart, the likely path is:

1. base short on the 13:29 supply conversion;
2. exit when that sponsor fails at 13:36;
3. re-enter on the durable 13:37 supply conversion;
4. possibly add on the 13:39 conversion;
5. flatten on the 13:43 LF, well before 29615.

The durable base had only about 3.5 points of adverse excursion before the LF
and about 40 points of favorable excursion by then. If the LF had paused adds or
required failure of the current supply sponsor instead of terminating the
position, the surviving supply lineage was sufficient to hold through the
later no-build traversal and into the target sequence.

## Target and no-build context

29615 was not an arbitrary unvisited target. It was adjacent to the session's
29616.50 IB/OR low. It was still a stretch target at entry because price first
had to break the prepared 29690-29694 demand rail. The replay labels that break
`building` at 14:40 and `accepted` at 14:50.

The late no-build observation was therefore a valid reason not to chase fresh
inventory after the move had already traversed down toward 29790. It was not a
reason an earlier 29867 short with surviving supply ownership had to be flat.

## OFI conclusion

OFI would have helped describe two moments:

- strong supply pressure around the 13:13 local high;
- opposing OFI on the 13:29 supply rail that later failed.

It would not have cleanly selected the durable 13:37/13:39 supply lineage, and
it positively confirmed the 13:43 local demand response that should not have
been terminal. Keep OFI experimental for initiative/absorption and candidate
discovery. The execution improvement supported by this fixture is LF handling
conditioned on the existing ownership lineage.

## Artifacts

- `research/out/execution_ownership_ofi_2026-06-23_1300-1400.txt`
- `research/out/execution_ownership_ofi_2026-06-23_1300-1400_events.csv`
- `research/out/execution_ownership_ofi_2026-06-23_1300-1400_grid.csv`
- `research/out/auction_quality_2026-06-23.txt`
- `research/out/tape_auction_2026-06-23.txt`
