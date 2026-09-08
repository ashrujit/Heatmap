# Kahn Implementation Completion - 2026-09-07

This records the offline implementation boundary. The subsequent authorized
installation and retained verification artifacts are recorded in
[RELEASE_2026-09-07.md](RELEASE_2026-09-07.md).

## Scope And Status

The approved broad-repair implementation and offline integration TODOs are
complete. TEST or associated opposing OWN/HOLD can open repair; typed opposing
failure, current associated support and executable clearance still gate adds.
No mandatory far-edge breach, GEX cross gate or detector threshold change was made.

This is implementation acceptance, not production release or profitability
acceptance. No active campaign/control file, live order, installed assembly,
Quantower process, commit or remote branch was changed by this task.

| Backlog | Completed implementation | Remaining boundary |
| --- | --- | --- |
| R2-R5, R8 | Shared complete-sample observer, causal association table, no-op repair preservation, exact lineage, epoch/attempt reset, defended/renewed/rebuilt support, reservation and once-only partial-fill consumption. | Broker callback/reconnect trial; detector-setting and CL/GC portability are separate research. |
| R6-R7, V1 | Typed root risk, live pending/active group health, one-behind promotion only on a later filled add, weighted and operator BE, existing risk-down/harvest behavior. | Actual protection/partial-close/rejection timing and declared-target execution in a test account; loaded binary provenance after release. |
| D1-D2 | Schema-2 WATCH, scoped GO LIVE and BE, unchanged entry expiry, restart authorization, replacement/CANCEL guards, FLAT precedence and late-fill latch. | Broker-connected lifecycle trial and flat-only cutover. |
| D5 | Two-box Probe/Dispatcher/assembler contracts, derived arena, explicit legacy conversion, schema-1 audit-only admission, status/acknowledgement and examples. | Authorized installation and user trial against the loaded runtime. |
| R1 | Full supplied mornings, stress/manual-start seeds, earlier controls and an additional fixed-window Aug 31 date check. | Broader untouched adverse/rotational sessions, realistic costs and actual execution validation. |

FLAT retries order cancellation without withholding the attempt to close current
exposure. It cannot acknowledge flatness while a reported fill is still waiting
for its position update. Uncertain orders remain visible and block new risk;
submit acceptance is never treated as a fill or completed flatten.

The frozen research implementation, old outputs, LL detector math and the user's
pre-existing 6J profile additions remain intact. Future GEX maxchange/cache work,
wall relocation, automatic reentry, post-cap sponsor promotion and tranche-local
trims remain separate backlog items, not unfinished parts of this package.

## Verification

- Existing C# runtime checks: 39 passed.
- Shared scaling checks: 69 passed.
- Campaign-session integration checks: 42 passed.
- Python transport/schema/parser parity: 22 passed.
- Frozen research regressions: 85 passed.
- Dispatcher geometry/import contracts passed; rendered 620x540 and 900x620
  layouts were inspected. Screenshots: `.tmp/kahn-dispatcher-layout/`.
- `git diff --check` passed, with only repository CRLF normalization warnings.

Final replay directories, relative to the repository:

| Artifact | Result | Manifest SHA256 |
| --- | --- | --- |
| `research/out/kahn-core-integration-final-20260907/` | 14 windows, 23 root paths, 46 warm/cold runs; 46 prefix and 46 fragmentation checks, no failures/differences. | `eccd49b724bdfc8d75dec45ffa6062d0fb747cbb1e869d91f69f4d99ed154f3b` |
| `research/out/kahn-session-integration-final-20260907/` | 23 integrated seeded paths; all eleven earlier control roots have zero adds. | `0ecdde695dd3d6ce7c18872fb42aab7de71c63f7bc0440dff99eb8801c3e8b54` |
| `research/out/kahn-session-aug31-final-20260907/` | 27 paths: 12 root exits, 8 BE proxy exits, 7 open cutoffs. Nine paths add once; none adds more than once. | `b0d38d33a7d33db4768abfb74224bfcdd980bc0b64c0c4f30278273b275d1982` |

All three manifests were checked against the final current source/build hashes:
zero mismatches. Commands and input provenance are in
[the test README](../KahnRuntime.Tests/README.md) and the manifests.

The integrated diagnostic uses counterfactual roots, 2/2/10 sizing, BBO plus one
tick fill proxies and an unbounded diagnostic arena. It does not invent missing
historical target/harvest plans. Target, reduce, floor-loss and protection logic
are covered synthetically, not as broker-connected execution. Overlapping windows,
warm/cold variants and manual-start alternatives are not independent sessions.

| Principal NQ fixture | Simulated filled adds, New York time | Peak quantity |
| --- | --- | --- |
| Sep 3 surviving second long root | 11:02:26, 11:08:45, 11:15:38, 11:23:14 | 10 |
| Sep 4 morning short | 10:07:57, 10:15:47, 10:26:05, 10:30:59 | 10 |

Both paths remain open at the 11:30 cutoff in this diagnostic. The failed Sep 3
first root remains included. These are not actual fills, measured P&L or a promise
that live execution reaches the same inventory.

## Release Builds

All three Release builds succeeded with zero warnings and zero errors, using
the configured .NET 10 SDK and workspace-local `OutputPath` overrides:

| Component | Output | DLL SHA256 |
| --- | --- | --- |
| KahnRuntime strategy | `.tmp/kahn-integration-build/KahnRuntime.dll` | `c62cd3d49506194290100da1470732ac8003cb8cb607b6fac8acb4b7898bc2d0` |
| KahnDispatcher | `.tmp/kahn-dispatcher-integration-build/KahnDispatcher.dll` | `83cdb943260b9305ad706ef88fa99df6d7da6a352b65c5cc5df011dd9a04002a` |
| SaavikProbe | `.tmp/saavik-probe-integration-build/SaavikProbe.dll` | `34be4f850e3a335af46c0028a3a9f796b38fa15aff30dde1cde5e8ec2ff1a58d` |

Unchanged deployed strategy SHA256:
`80a17594b6b82a9bdee71643f8eafb55341e192f4efc18712e856259cc4cef4a`.
Unchanged LL engine source SHA256:
`cb1bfa09b0ec6223dbc4c9a9093de2a57132d9695a136e7343c9d31a9b2de6aa`.
Unchanged frozen observer SHA256:
`c1233c36407ad32ff14b357aa8d29b19ca6cdda10fa261df6313867c2ecee02a`.

## Remaining Release Gates

1. Separate installation/release authorization and actual-flat/no-unresolved-order
   preflight. Retain rollback binaries/files; do not rewrite active campaigns.
2. Install/restart Quantower and verify loaded assembly/schema/profile provenance.
3. Bounded broker-connected shadow/test-account trial: root/add partial and final
   reports, missing/rejected/late callbacks, reconnect, stop validity/resizing,
   BE/harvest retirement, scoped control races and FLAT reconciliation. Verify
   Probe handle interaction on a Quantower chart, including touching boxes.

Follow [SCHEMA2_CUTOVER.md](SCHEMA2_CUTOVER.md). Offline tests do not replace those
checks or authorize live order routing.
