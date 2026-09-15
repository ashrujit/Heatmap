# Offline Kahn Verification

This project links pure runtime/session sources. It neither references the
deploying strategy project nor loads a broker API. Cumulative fake reports test
the coordinator used by the worker; they are not exchange/Quantower integration.
Broker regressions also use identified trade events and stale order snapshots
through the production fill merger and worker-cycle orchestration. The incident
identity and connected-validation limits are recorded in
`KahnRuntime/FILL_RECONCILIATION_FIX.md`.

```powershell
& "$env:USERPROFILE\AppData\Local\Microsoft\dotnet\dotnet.exe" run --project KahnRuntime.Tests/KahnRuntime.Tests.csproj -c Release
& .\skills\dost\.venv\Scripts\python.exe -m unittest discover -s KahnRuntime.Tests -p 'test_*.py'
& "$env:USERPROFILE\AppData\Local\Microsoft\dotnet\dotnet.exe" run --project KahnDispatcher.Tests/KahnDispatcher.Tests.csproj -c Release
```

Finish the build before running the fixture harness. It refuses to mix builds
or overwrite prior results. Use an empty dedicated output directory:

```powershell
& .\skills\dost\.venv\Scripts\python.exe KahnRuntime.Tests/replay_fixtures.py --checks --out research/out/kahn-core-new-run
```

The default uses executable bid for longs and ask for shorts. Optional
`--price-basis midpoint` reproduces the earlier research price basis solely for
comparison. Input cases reuse the frozen root selector, preserve failed roots,
and include ES/NQ September 3-4 mornings and the requested September 1-2 NQ
stress windows. Warm/cold variants and window extensions are not independent
market samples. No P&L, BE, passive harvest, or actual broker fills are inferred.

Complete LL samples are reconstructed from the prepared `snapshots.jsonl`
boundaries and the matching EngineProbe export, including empty samples. This
does not generalize timestamp grouping to arbitrary external evidence streams.
Cold initialization observes the complete seed sample, unlike the prototype's
single selected seed event. Optional formation metadata is never backdated into
ownership; the baseline comparison leaves formation unknown.

Outputs include per-operation input, offers, transition/membership audit records,
a comparison CSV, prefix/fragmentation checks, and source/data/build hashes.
The frozen research observer is hash-checked and its outputs are not overwritten.

Integrated inventory diagnostics use separate outputs and explicit BBO-plus-one-
tick synthetic fills. They retain the existing seeds, terminal BE and group risk.
No fixture target or broker fill is invented:

```powershell
& .\skills\dost\.venv\Scripts\python.exe KahnRuntime.Tests/replay_sessions.py --out research/out/kahn-session-new-run
```

`--holdout-day 2026-08-31 --engine <isolated EngineProbe.dll>` selects both sides
in three fixed windows for ES/NQ before reading outcomes. `--holdout-data <dir>`
reuses previously prepared, hashed capture inputs without changing old artifacts.
No source or test binary may change while a replay is running.

Root-risk verification also checks exact owner identity, Lean/Consumed provenance,
reload hydration, pre-submit revalidation, pending/partial/late-fill failures,
unknown epochs and the optional entry-distance gate. The integrated replay now
hydrates root history from the actual pre-window prefix without replaying old
scale events. Missing or offside owners produce `root_proxy_rejected` rows.
Seeds remain explicitly counterfactual, not claimed as fresh live entry signals.

Recovery regressions also run the actual pure LL engine. Discovery resets retain
owned identities and reset pending failure timers; the coordinator must process
their failures during warmup, preserve filled sponsor risk, reject gap-sample
entries and handle irreversible identity loss through a separate recovery exit.
The synthetic owned-rail fixtures do not establish live entry permission, and no
offline test proves connectivity or executable exits during a broker outage.

To compile the actual strategy without deploying:

```powershell
& "$env:USERPROFILE\AppData\Local\Microsoft\dotnet\dotnet.exe" build KahnRuntime/KahnRuntime.csproj -c Release '-p:OutputPath=C:\Heatmap\.tmp\kahn-shared-core-build\'
```

Do not omit that output override: the project's default output path deploys
directly into Quantower.

Capture recovery regressions cover bounded/concurrent queue overflow, delayed
workers, short mismatches, repeated long gaps, clock regression, source-time
freshness, slow-worker catch-up, deterministic LL equivalence, retained baseline
and exact-owner failure timing through catch-up. The tests do not attest to QT
provider timestamp quality or private delivery queue completeness.
