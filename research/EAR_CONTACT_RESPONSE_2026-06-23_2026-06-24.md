# EAR Contact Response Probe

Research-only replay. Baseline population is current EAR-style favor-displacement episodes from the existing ownership/candidate grammar. Fast-pass contact metrics use canonical snapshot depth plus tape after the displacement starts; raw add/remove deltas are optional.

## Sessions
- 2026-06-23:NQU6 09:30-16:00: candidates=142, episodes=402, favor_anchors=204, snapshot_gaps=15, book_files=2786, carry_days=0, book_rows=30842803, book_gaps=0, crossed_repairs=0
- 2026-06-24:NQU6 09:30-16:00: candidates=138, episodes=447, favor_anchors=220, snapshot_gaps=5, book_files=4686, carry_days=1, book_rows=60276800, book_gaps=0, crossed_repairs=1606

## Baseline
- Clean resolved favor-displacement anchors: 71/220 32.3%
- CSV: `C:\Heatmap\research\out\ear_contact_response_2026-06-23_2026-06-24.csv`

## Contact/Reload Separation
- `held_ratio_2s`: low<=p25 26/55 47.3%, high>=p75 24/75 32.0%, AUC=0.430 n=220
- `held_ratio_5s`: low<=p25 38/86 44.2%, high>=p75 16/56 28.6%, AUC=0.410 n=220
- `reload_ratio_2s`: low<=p25 30/56 53.6%, high>=p75 16/56 28.6%, AUC=0.371 n=220
- `reload_ratio_5s`: low<=p25 44/58 75.9%, high>=p75 11/56 19.6%, AUC=0.236 n=220
- `replenishment_5s`: low<=p25 34/62 54.8%, high>=p75 11/62 17.7%, AUC=0.296 n=220
- `hidden_ratio_5s`: low<=p25 65/105 61.9%, high>=p75 0/58 0.0%, AUC=0.148 n=220
- `attack_vol_5s`: low<=p25 65/105 61.9%, high>=p75 0/63 0.0%, AUC=0.151 n=220
- `same_depth_change_5s`: low<=p25 24/58 41.4%, high>=p75 16/59 27.1%, AUC=0.408 n=220
- `opp_depth_change_5s`: low<=p25 71/162 43.8%, high>=p75 0/58 0.0%, AUC=0.305 n=220
- `future_30s_ticks`: low<=p25 11/56 19.6%, high>=p75 34/56 60.7%, AUC=0.684 n=220

## Exploratory Gate Read
- Attack threshold p50=1.00; reload p75=0.18.
- `attacked`: 6/115 5.2%
- `top_reload_response`: 1/34 2.9%
- `negative_reload_response`: 4/72 5.6%
- Thin-attack ratio p75=0.25: 0/58 0.0%
- Attack p75=5.00 paired checks:
  - `high_attack`: 0/63 0.0%
  - `high_attack_and_held_ratio_ge_1`: 0/5 0.0%
  - `high_attack_and_depth_nonnegative`: 0/5 0.0%
  - `high_attack_and_depth_negative`: 0/58 0.0%

## Interpretation Guardrails
- These gates are selected in-sample and are only useful for deciding what to test next.
- `reload_ratio` follows Udit's aggregate idea: attack volume plus same-side size change, normalized by attack.
- `hidden_ratio` is attack volume divided by displayed same-side depth in the candidate band. In this EAR population it behaved as thin support under attack, not supportive hidden liquidity.
- Today may be partial/live. Treat June 23-24 as the completed-session base.
