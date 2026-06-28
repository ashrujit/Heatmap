# EAR Contact Response Probe

Research-only replay. Baseline population is current EAR-style favor-displacement episodes from the existing ownership/candidate grammar. Fast-pass contact metrics use canonical snapshot depth plus tape after the displacement starts; raw add/remove deltas are optional.

## Sessions
- 2026-06-24:NQU6 09:30-16:00: candidates=138, episodes=447, favor_anchors=220, snapshot_gaps=5, book_files=0, carry_days=0, book_rows=0, book_gaps=0, crossed_repairs=0

## Baseline
- Clean resolved favor-displacement anchors: 71/220 32.3%
- CSV: `C:\Heatmap\research\out\ear_contact_response_2026-06-24.csv`

## Contact/Reload Separation
- `held_ratio_2s`: low<=p25 26/55 47.3%, high>=p75 24/57 42.1%, AUC=0.486 n=220
- `held_ratio_5s`: low<=p25 38/86 44.2%, high>=p75 18/56 32.1%, AUC=0.427 n=220
- `reload_ratio_2s`: low<=p25 24/61 39.3%, high>=p75 24/65 36.9%, AUC=0.507 n=220
- `reload_ratio_5s`: low<=p25 39/58 67.2%, high>=p75 15/56 26.8%, AUC=0.344 n=220
- `replenishment_5s`: low<=p25 28/55 50.9%, high>=p75 15/68 22.1%, AUC=0.393 n=220
- `hidden_ratio_5s`: low<=p25 65/105 61.9%, high>=p75 0/56 0.0%, AUC=0.155 n=220
- `attack_vol_5s`: low<=p25 65/105 61.9%, high>=p75 0/63 0.0%, AUC=0.151 n=220
- `same_depth_change_5s`: low<=p25 18/56 32.1%, high>=p75 25/57 43.9%, AUC=0.512 n=220
- `opp_depth_change_5s`: low<=p25 71/162 43.8%, high>=p75 0/58 0.0%, AUC=0.305 n=220
- `future_30s_ticks`: low<=p25 11/56 19.6%, high>=p75 34/56 60.7%, AUC=0.684 n=220

## Exploratory Gate Read
- Attack threshold p50=1.00; reload p75=0.40.
- `attacked`: 6/115 5.2%
- `top_reload_response`: 2/31 6.5%
- `negative_reload_response`: 4/70 5.7%
- Hidden-ratio p75=0.28: 0/56 0.0%

## Interpretation Guardrails
- These gates are selected in-sample and are only useful for deciding what to test next.
- `reload_ratio` follows Udit's aggregate idea: attack volume plus same-side size change, normalized by attack.
- `hidden_ratio` is attack volume divided by displayed same-side depth in the candidate band; it is not an iceberg detector.
- Today may be partial/live. Treat June 23-24 as the completed-session base.
