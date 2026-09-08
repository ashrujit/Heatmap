# September 8 Fill Reconciliation Release

This records the initial fill-callback correction. Its deployed binary was
subsequently replaced by the follow-up in `BE_RECONCILIATION_FIX.md`, which fixes
the mixed position-snapshot average race discovered during live validation.

## Incident

NQ order `38660935` received a trade callback for two shorts at 29554.25,
followed by an order removal still reporting Opened, zero filled and two
remaining. The prior adapter ignored trade callbacks for campaign accounting.
Consequently the root reservation remained unresolved, its original LL risk
anchor was never installed, and the worker's reconciliation early return also
stopped LL sampling and risk evaluation.

This was not a wider root stop or permission to ignore LL failure. No LL
threshold, root/probe failure policy, repair grouping, or sponsor rule is changed
by this release.

## Safety Constraints

- Use broker trade identity for execution deduplication. Order cumulative fills
  and trade executions overlap; adding both counts doubles inventory. Stale
  order snapshots cannot erase an already attributed fill.
- Reconciliation failure blocks new risk while observation and existing-risk
  evaluation continue. Automatic risk-down still requires known managed
  position identity, direction and attributable quantity; do not adopt manual
  or ambiguous positions.
- Keep selected full-exit decisions until submission is accepted, including a
  typed root failure received before the root fill callback. This is deferred
  execution of observed failure, not reuse of stale evidence for entry.
- Apply only incremental fill quantity. Duplicate partial reports must not
  resurrect already reduced inventory. Late fills after a terminal cancel are
  visible inventory but require recovery and cannot promote cancelled proof.
- Missing execution identity or inconsistent broker facts remain explicit
  recovery conditions, not permission to infer fills from position size alone.

## Verification

- 178 C# checks: 39 legacy runtime, 69 shared repair, 42 session, 26 broker/cycle
  regressions and two checkpoint disk cases.
- 24 Python transport tests passed.
- All 85 frozen research tests passed with their archived EngineProbe and
  isolated writable test output. That engine is legacy research provenance,
  not the new strategy binary.
- All 23 integrated historical replay summaries equal the prior final release
  summaries, including add times, quantities, exits and sponsor output.
- Actual strategy Release build: zero warnings and zero errors.

The incident test retains observed quantity, price, original root anchor and
callback order. The old log omitted Trade.Id, so its execution identity is
explicitly synthetic. Its subsequent typed failure is also a test input, not a
claim that the stopped LL engine logged that failure historically.

## Deployment

Installed DLL/PDB/deps hashes were matched against the isolated Release build.
DLL SHA256:
`42175cee1416e7ce65546af74842fe1caea1babc5b27e869cfec6177875cdb99`.

Build, rollback files, checkpoint snapshots and verification artifacts are in
`research/out/kahn-fill-reconciliation-20260908/`. Both ES/NQ checkpoints reported
Stopped, zero position and zero bound working orders before installation.
These are stopped-instance snapshots, not a fresh broker flatness query.
Dispatcher, live campaign files and control files were not changed.

Restart Quantower before starting either strategy instance: assembly caching
means installed hashes do not establish loaded-binary provenance. Offline tests
do not validate connected broker callback delivery or exchange order execution.
No strategy restart, GO LIVE, dispatch or trading command was issued here.
