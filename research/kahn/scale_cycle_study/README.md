# Morning Scale Study

Offline investigation of ES/NQ September 3 longs after 10:55 and September 4
shorts after 10:00, with earlier same-session controls. No production references,
broker gateway, active campaign writes, or Quantower deployment.

Read [the findings](../KAHN_MORNING_SCALE_FINDINGS_2026-09-06.md) before interpreting
candidate timestamps as opportunities. These are seeded counterfactuals, not fills.

## Reproduce

From `C:\Heatmap` in PowerShell:

```powershell
& C:\Users\j\AppData\Local\Microsoft\dotnet\dotnet.exe build research/kahn/scale_cycle_study/EngineProbe/EngineProbe.csproj --configuration Release --nologo
& C:\Heatmap\skills\dost\.venv\Scripts\python.exe research/kahn/scale_cycle_study/study.py prepare
& C:\Heatmap\skills\dost\.venv\Scripts\python.exe research/kahn/scale_cycle_study/study.py analyze
& C:\Heatmap\skills\dost\.venv\Scripts\python.exe research/kahn/scale_cycle_study/study.py sensitivity
& C:\Heatmap\skills\dost\.venv\Scripts\python.exe -m unittest discover -s research/kahn/scale_cycle_study -p test_study.py -v
& C:\Users\j\.local\bin\uv.exe run --offline --with polars --with matplotlib --with tzdata --no-project python research/kahn/scale_cycle_study/render.py
```

Preparation supports `--symbol ES|NQ` and `--day YYYY-MM-DD`. Outputs are under
`research/out/kahn-scale-20260906`, which is ignored by git. Plotting uses cached
packages offline; remove `--offline` only when package downloads are intended.
The tested analysis environment is Python 3.12.12 / Polars 1.41.2. Plotting used
Polars 1.44.1 / Matplotlib 3.11.0 from the local uv cache.

## Comparisons

- `current_core`: linked current policy/state, identical forced root, broad
  arena. Each GEX gate gets its own replay; a veto does not execute the add or
  terminate later candidate search. No target, no-add box, live adapter, or BE
  order is modeled.
- `direct_favorable`: first qualifying event per favorable rail ID. This is the
  aggressive control, not a recommendation to add on every price.
- `serial_identity`: latest eligible opposing claim must fail by exact
  epoch-qualified ID, then a same-side event must overlap/pass its range.
- `joint_range`: retain current same-side ownership/hold observed during the
  repair; allow it to complete the same range condition at formal failure.
- `joint_price`: still requires typed opposing failure and surviving same-side
  proof, but current price can reclaim the repair while the proof rail remains
  behind it. This does NOT infer claim failure from price alone.
- `warm_*`: retain claims observed since the case window opened, before the
  forced root fill. Failure must occur AFTER that fill. A pre-fill failure is
  not reusable permission. This is an explicit first-add hypothesis.

All Python variants use a latest-claim approximation, require progression
beyond the root and an onside signal price, and do not reproduce all current
policy vetoes. They are not isolated one-line patches to the current policy.
`RailTested` suspends retained favorable confirmation until a subsequent HOLD;
failure or epoch reset removes it. Candidate generation never reads future
prices. Outcome scoring is separate.

Gates: `none`, `price_side`, `rail_side`, `rail_renewed` (new proof since the
last observed directional crossing), `rail_rearmed` (also renew after each stale
gap), and `negative_sum_vol` (deliberately non-equivalent sign diagnostic).
No gate creates missing LL proof. Positional gates are not models of persistent
auction acceptance. `rail_renewed` cannot rule out an unobserved crossing during
a stale interval; `rail_rearmed` is the conservative comparison for that gap.

## Files

- `roots.csv`: every forced root, including failures and retry cap.
- `events.jsonl` in each market folder: current C# evidence transitions in order.
- `core/`: seed configuration and before/after current-policy state per event.
- `candidate_events.csv`: causal candidates, context joins, and separate outcomes.
- `first_add_comparison.csv`: first fillable candidate per root/model/category/gate.
- `start_sensitivity.csv`: observation starts shifted by one minute, no GEX gate.
- `gamma_crossings.csv`, `gamma_coverage.csv`: point-in-time context and stale cases.
- `method_summary.csv`, `morning_scale_comparison.png`: inspection summaries.
- `manifest.json`, per-market `quality.json`: rules, settings, source hashes, gaps.

Candidate rows can repeat a proof across later events. They are not separate
executed adds. Only first-add results are compared; no cumulative leverage,
broker-stop simulation, net P&L, or independent statistical sample is claimed.

## Full-Morning NQ Follow-Up

The user's later scope is repeated NQ cycles through 11:30, not first-add selection.
Read [the full-morning findings](../KAHN_NQ_CAMPAIGN_CYCLES_2026-09-06.md).
Reuse the existing NQ prepared inputs; no ES preparation or GEX comparison is needed.

```powershell
& C:\Users\j\AppData\Local\Microsoft\dotnet\dotnet.exe build research/kahn/scale_cycle_study/EngineProbe/EngineProbe.csproj --configuration Release --nologo
& C:\Heatmap\skills\dost\.venv\Scripts\python.exe research/kahn/scale_cycle_study/campaign_cycles.py
& C:\Heatmap\skills\dost\.venv\Scripts\python.exe research/kahn/scale_cycle_study/audit_cycles.py
& C:\Heatmap\skills\dost\.venv\Scripts\python.exe -m unittest discover -s research/kahn/scale_cycle_study -p 'test_*.py' -v
& C:\Users\j\.local\bin\uv.exe run --offline --with polars --with matplotlib --with tzdata --no-project python research/kahn/scale_cycle_study/render_cycles.py
```

Outputs: `research/out/kahn-nq-cycles-20260906`. The driver preserves the failed
first long root and runs six interventions at capacities 10 and 100. Capacity
100 is diagnostic headroom, not recommended size. Replay continues through
accepted adds and source risk exits, without forced reentry after sponsor exits.

- `current`: unchanged linked source policy and state.
- `preserve_noop`: bypass candidate-triggered repair clearing only when the
  proposed candidate does not advance. Source candidate tracking still runs.
- `preserve_all`: preserve repair on all favorable candidate tracking.
- `cycle_joint_range`: persistent observer, exact typed claim failure, current
  advancing proof observed after the preceding add; keep the requirement that
  proof range overlaps/passes repair. Proof can precede the claim/failure.
- `cycle_joint`: same observer but price reclaim can qualify while the proof
  rail remains behind the repair. TEST suspends proof, HOLD restores, FAIL removes.
- `cycle_joint_zone`: also wait until all live opposite rails within two ticks
  of the selected claim fail. This is rail identity grouping, not a no-add box.

Joint variants replace serial Press admission, including its repair suppression,
and preserve source risk-down decision resolution and one-behind promotion.
They bundle several hypotheses and do not silently fix failed-pending promotion.
Only the no-op/all-preservation variants isolate that single state intervention.

`event_audit.csv` exposes repair clears, unchanged candidates, suppression, and
failed pending-sponsor promotions. `cycle_add_lineage.csv` supplies every prototype
add's claim/proof history and source decision at the same event. `rail_histories.csv`
continues through 11:30 even after capacity/risk prevents orders. `runtime_boundary`
files distinguish historical runtime activity from the seeded policy experiment.
`nq_campaign_cycles.png` plots price and ten-unit capped inventory for the surviving
long root and short root; the failed first long root is marked separately.

BE is a separate BBO path diagnostic, not an integrated order simulation. There
is no broker gateway, runtime expiry worker, harvest, or net P&L. Proof freshness,
challenged-stack membership, and complete campaign execution remain open decisions.
New `manifest.json` hashes identify the extended harness; older first-add artifacts
retain their original run provenance. Thirty-one tests include first-add compatibility.

## Shared-Episode Follow-Up

Read [the shared-episode findings](../KAHN_SHARED_EPISODE_RESEARCH_2026-09-06.md).
`episode_study.py` reuses the four prepared ES/NQ market folders without GEX.
It observes causal attack/repair groups, not fixed-time batches or band-count
votes. The formal-failure baseline and two no-owned-claim defense alternatives
are separate hypotheses. Warm/cold pre-fill adoption and reset-on-breach
ablations are retained; failed IDs never become live simply because a group rebuilds.

```powershell
& C:\Heatmap\skills\dost\.venv\Scripts\python.exe research/kahn/scale_cycle_study/episode_study.py
& C:\Heatmap\skills\dost\.venv\Scripts\python.exe research/kahn/scale_cycle_study/audit_episodes.py
& C:\Heatmap\skills\dost\.venv\Scripts\python.exe -m unittest discover -s research/kahn/scale_cycle_study -p 'test_*.py' -v
& C:\Users\j\.local\bin\uv.exe run --offline --with polars --with matplotlib --with tzdata --no-project python research/kahn/scale_cycle_study/render_episodes.py
```

Outputs: `research/out/kahn-episodes-20260906`. Root/add tranches are two units;
add budgets are zero (root-only control), two, and three. Compare root plus BE,
tranche-group trims, and cap-independent latest-group campaign protection. These
are research risk policies, not linked production order handling. Delayed BBO
fill proxies recheck support, opposition, clearance, and favorable price versus
average; per-run `decisions` log evaluated fills and vetoes. No real target harvest,
fee model, broker partial/rejected order lifecycle, or independent holdouts.

`episodes.csv` and per-root traces preserve membership and lifecycle;
`offers.csv` separates structural permissions from inventory;
`inventory_summary.csv`/`actions.csv` expose adds, reductions, and risk exits.
`episode_diagnostics.csv` records coverage and descriptive traversal timings,
not a fitted speed threshold. `breach_boundary_comparison.csv` exposes effects
of prematurely resetting a breached group. `validation.json` contains 16 real
fragmentation and 16 future-prefix checks, plus study/test/audit source hashes.
The full suite has 56 passing tests. The plot and its manifest are separate
artifacts so rendering does not overwrite analysis provenance.

## September 1-2 Frozen Stress Test

Read [the September 7 findings](../KAHN_NQ_EPISODE_STRESS_TEST_2026-09-07.md).
`stress_episodes.py` pins the September 6 episode-model SHA256 and imports its
observer/inventory logic unchanged. The new fixtures are NQ Sep 2 long
10:00-10:30 and 11:00-11:30, and Sep 1 short 11:50-12:30, with a fixed extension
to 12:40. Start shifts of minus/plus one minute do not shift the endpoints.

```powershell
& C:\Users\j\AppData\Local\Microsoft\dotnet\dotnet.exe build research/kahn/scale_cycle_study/EngineProbe/EngineProbe.csproj --configuration Release --nologo
& C:\Heatmap\skills\dost\.venv\Scripts\python.exe research/kahn/scale_cycle_study/stress_episodes.py prepare
& C:\Heatmap\skills\dost\.venv\Scripts\python.exe research/kahn/scale_cycle_study/stress_episodes.py lineage
& C:\Heatmap\skills\dost\.venv\Scripts\python.exe research/kahn/scale_cycle_study/stress_episodes.py analyze
& C:\Heatmap\skills\dost\.venv\Scripts\python.exe research/kahn/scale_cycle_study/audit_stress.py
& C:\Heatmap\skills\dost\.venv\Scripts\python.exe -m unittest discover -s research/kahn/scale_cycle_study -p 'test_*.py'
& C:\Users\j\.local\bin\uv.exe run --offline --with polars --with matplotlib --with tzdata --no-project python research/kahn/scale_cycle_study/render_stress.py
```

Output is isolated under `research/out/kahn-episode-stress-20260907`, including
its own prepared `data` folders. Capture preparation has optional output/time
parameters; older defaults remain unchanged. No GEX is loaded for this pass.
`lineage` uses the offline probe's optional seventh argument to emit formation,
ownership-confirmation, and source-side metadata separately. Both primary rail
streams must remain byte-identical. Lineage is diagnostic, not model permission.

`permission_context.csv` distinguishes failure age from proof formation and
confirmation. `risk_exit_context.json` records root/support states and actual
proxy BE inputs at exit; later opportunities are explicitly outcome labels.
`start_sensitivity.csv` retains failed alternative roots. `add_paths.csv` measures
excursions only until that tranche's modeled exit, not the subsequent favorable
move. Current-source comparison uses event-midpoint adds without integrated BE;
do not compare its performance with the delayed-fill group-risk experiment.

All 63 tests pass. Ten new warm/cold case-root invariance checks include the
short's duplicated root under the longer horizon, not ten independent cases.
The frozen model deliberately retains the discovered unlimited resolved-wait
weakness; its diagnostic regression test is not approval of that future contract.

## Far-Edge Repair Rerun

Read the [far-edge findings](../KAHN_FAR_EDGE_REPAIR_RERUN_2026-09-07.md).
The earlier observer remains frozen. `far_edge_study.py` compares an isolated
far-edge filter, excursion-local grouping on sampled midpoints, and the same
observer using recorded trades between complete LL samples. Roots, LL settings,
typed opposing failure, and root-plus-BE management are held constant. No build
is needed with the six previously prepared market folders present.

```powershell
& C:\Heatmap\skills\dost\.venv\Scripts\python.exe research/kahn/scale_cycle_study/far_edge_study.py --validate
& C:\Heatmap\skills\dost\.venv\Scripts\python.exe research/kahn/scale_cycle_study/audit_far_edge.py
& C:\Heatmap\skills\dost\.venv\Scripts\python.exe -m unittest discover -s research/kahn/scale_cycle_study -p 'test_*.py'
```

Output: `research/out/kahn-far-edge-20260907`. Includes four main mornings, four
earlier controls, stress cases/extension, and Sep 1 11:55/12:00 starts. `--case`
writes a separate focused directory, not the full aggregate. All 85 tests pass.
`old_offer_classification.csv` compares exact times, not episode equivalence;
`old_member_extrema.csv` explains crossings with history truncated at permission;
`new_offer_lineage.csv` records breach origins and support. Fragment tests preserve
parent claim boundaries; unlabelled splits are a separate sensitivity. Local
association and expiry are additional hypotheses, not an isolated state fix.
