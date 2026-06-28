# EAR Contact Response Probe

Research-only replay. Baseline population is current EAR-style favor-displacement episodes from the existing ownership/candidate grammar. Fast-pass contact metrics use canonical snapshot depth plus tape after the displacement starts; raw add/remove deltas are optional.

## Sessions
- 2026-06-23:NQU6 09:30-16:00: candidates=142, episodes=402, favor_anchors=204, snapshot_gaps=15, book_files=0, carry_days=0, book_rows=0, book_gaps=0, crossed_repairs=0

## Baseline
- Clean resolved favor-displacement anchors: 73/201 36.3%
- CSV: `C:\Heatmap\research\out\ear_contact_response_2026-06-23.csv`

## Contact/Reload Separation
- `held_ratio_2s`: low<=p25 24/51 47.1%, high>=p75 21/51 41.2%, AUC=0.488 n=201
- `held_ratio_5s`: low<=p25 31/71 43.7%, high>=p75 24/51 47.1%, AUC=0.507 n=201
- `reload_ratio_2s`: low<=p25 23/53 43.4%, high>=p75 28/72 38.9%, AUC=0.477 n=201
- `reload_ratio_5s`: low<=p25 33/54 61.1%, high>=p75 26/62 41.9%, AUC=0.411 n=201
- `replenishment_5s`: low<=p25 28/55 50.9%, high>=p75 19/52 36.5%, AUC=0.437 n=201
- `hidden_ratio_5s`: low<=p25 67/114 58.8%, high>=p75 2/51 3.9%, AUC=0.213 n=201
- `attack_vol_5s`: low<=p25 67/114 58.8%, high>=p75 4/58 6.9%, AUC=0.219 n=201
- `same_depth_change_5s`: low<=p25 21/51 41.2%, high>=p75 26/58 44.8%, AUC=0.512 n=201
- `opp_depth_change_5s`: low<=p25 73/163 44.8%, high>=p75 73/201 36.3%, AUC=0.352 n=201
- `future_30s_ticks`: low<=p25 11/51 21.6%, high>=p75 27/52 51.9%, AUC=0.641 n=200

## Exploratory Gate Read
- Attack threshold p50=0.00; reload p75=1.00.
- `attacked`: 73/201 36.3%
- `top_reload_response`: 26/62 41.9%
- `negative_reload_response`: 43/115 37.4%
- Hidden-ratio p75=0.18: 2/51 3.9%

## Interpretation Guardrails
- These gates are selected in-sample and are only useful for deciding what to test next.
- `reload_ratio` follows Udit's aggregate idea: attack volume plus same-side size change, normalized by attack.
- `hidden_ratio` is attack volume divided by displayed same-side depth in the candidate band; it is not an iceberg detector.
- Today may be partial/live. Treat June 23-24 as the completed-session base.
