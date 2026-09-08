# September 8 NQ Add And Missing BE

Status: deployed to Quantower on September 8 after explicit release approval.

## Auction Evidence

Campaign `nq-long-campaign-20260908-164734-c8d885`, execution MNQU6, data NQU6.
Times below are New York time; source log timestamps are UTC.

- 12:49:18: root permission followed demand #41 HOLD, at 29582-29582.75.
  The root filled two at 29587.
- 12:50:24: demand #41 was tested again; at 12:50:25 it held.
- 12:50:27: opposing supply #42, 29589.25-29591.75, failed.
- 12:50:31: opposing supply #34, 29591.5-29592.5, failed. Only then did
  episode `2:2` become eligible. Its proof was defended #41, not a fresh
  favorable OWN or an untested band. The add filled two at 29601.5.
- New demand #43 and #44 were confirmed at 12:50:36 and 12:50:37, after
  the add. They did not authorize it.

This example does not demonstrate an add-on-new-price policy regression. No
repair/grouping or root failure policy is changed by this correction.

## Accounting Failure

At 12:50:33.141 the broker position snapshot exposed old quantity 2 with the
new weighted average 29594.25, before the add trade callback was drained.
Reconciliation copied that average into campaign state while the add remained
unresolved. The later fill used that already blended average as its base:

`(2 * 29594.25 + 2 * 29601.5) / 4 = 29597.875` (incorrect).

The correct average is `(2 * 29587 + 2 * 29601.5) / 4 = 29594.25`.

Actual quantity subsequently matched four, but the averages did not. The
`awaiting_attributed_fill_position` gate persisted, and the worker skipped BE
maintenance. There was no BE submission or broker BE rejection in this campaign.
This race was missed by the preceding fill-reconciliation release's tests.

At 12:53:04 the broker position became flat after closing fills. The log records
runtime stop at 12:53:11. Its checkpoint still displayed RecoveryActionRequired
and simulated quantity four, so phase/checkpoint status must not be mistaken
for live exposure or proof that the strategy remained running.

## Correction

- Do not adopt a changed broker average from an unresolved order's mixed
  position snapshot. Preserve attributed cost until fill facts catch up.
- Run BE maintenance even when new-risk reconciliation is not ready. Protection
  has a separate gate requiring the managed position identity, side, quantity
  and average to match attributed inventory. Pending closes remain a veto.
- Preserve broker-average reconciliation after completed risk orders and
  observed reductions; do not restore a fixed pre-order inventory snapshot.

The regression uses the actual bands, broker order/trade identities and fill
prices, with explicitly compressed synthetic observation timing. It verifies
defended proof, final opposing failure, correct average, protection admission and
the four-contract BE maintenance callback. It does not submit a real broker order.

Verification: 183 C# checks and 24 Python transport tests passed; actual strategy
Release build completed with zero warnings/errors. All 23 historical replay
summaries matched the prior final release. Comparisons and artifact hashes are
retained under `research/out/kahn-be-reconciliation-20260908/`.

Connected broker stop placement and loaded-binary provenance are not established
by an isolated build. Both strategy logs ended with stopped, flat instances before
deployment. NQ's checkpoint retained its recovery label despite the explicit stop
event; this was not treated as proof of a running strategy or live exposure.

The installed DLL, PDB and deps hashes match the tested Release artifacts. DLL
SHA256: `32318e2cbe2cebd33d7349de90bc46b72bf2b77d4dc51d9d088b3f97a08e7152`.
The preceding installed files are retained in the release directory's `rollback/`.
Campaign/control files were not changed, and no activation or trading command was
issued. Restart Quantower before restarting the strategies to load the new assembly.
