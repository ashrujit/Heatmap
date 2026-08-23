# EAR Contact Response Probe

Research-only replay. Baseline population is current EAR-style favor-displacement episodes from the existing ownership/candidate grammar. Fast-pass contact metrics use canonical snapshot depth plus tape after the displacement starts; raw add/remove deltas are optional.

## Sessions
- 2026-08-21:NQU6 10:20-12:00: candidates=37, episodes=131, favor_anchors=146, snapshot_gaps=1, book_files=1610, carry_days=1, book_rows=24936773, book_gaps=0, crossed_repairs=633
- 2026-08-21:NQU6 12:00-13:30: candidates=37, episodes=131, favor_anchors=146, snapshot_gaps=1, book_files=1610, carry_days=1, book_rows=24936773, book_gaps=0, crossed_repairs=633

## Baseline
- Clean resolved favor-displacement anchors: 46/146 31.5%
- CSV: `research\out\ear_contact_response_phase_revisit_nq_2026-08-21_book\ear_contact_response_2026-08-21_2026-08-21.csv`

## Contact/Reload Separation
- `held_ratio_2s`: low<=p25 13/38 34.2%, high>=p75 12/37 32.4%, AUC=0.503 n=146
- `held_ratio_5s`: low<=p25 14/37 37.8%, high>=p75 12/37 32.4%, AUC=0.442 n=146
- `reload_ratio_2s`: low<=p25 17/41 41.5%, high>=p75 15/49 30.6%, AUC=0.465 n=146
- `reload_ratio_5s`: low<=p25 23/39 59.0%, high>=p75 13/37 35.1%, AUC=0.349 n=146
- `replenishment_5s`: low<=p25 20/38 52.6%, high>=p75 13/50 26.0%, AUC=0.352 n=146
- `hidden_ratio_5s`: low<=p25 46/103 44.7%, high>=p75 0/37 0.0%, AUC=0.285 n=146
- `attack_vol_5s`: low<=p25 46/103 44.7%, high>=p75 0/37 0.0%, AUC=0.285 n=146
- `same_depth_change_5s`: low<=p25 19/38 50.0%, high>=p75 13/38 34.2%, AUC=0.426 n=146
- `opp_depth_change_5s`: low<=p25 46/131 35.1%, high>=p75 46/146 31.5%, AUC=0.425 n=146
- `future_30s_ticks`: low<=p25 3/38 7.9%, high>=p75 17/37 45.9%, AUC=0.728 n=146

## Exploratory Gate Read
- Attack threshold p50=0.00; reload p75=1.50.
- `attacked`: 46/146 31.5%
- `top_reload_response`: 13/37 35.1%
- `negative_reload_response`: 31/76 40.8%
- Thin-attack ratio p75=0.04: 0/37 0.0%
- Attack p75=2.00 paired checks:
  - `high_attack`: 0/37 0.0%
  - `high_attack_and_held_ratio_ge_1`: 0/7 0.0%
  - `high_attack_and_depth_nonnegative`: 0/7 0.0%
  - `high_attack_and_depth_negative`: 0/30 0.0%

## Interpretation Guardrails
- These gates are selected in-sample and are only useful for deciding what to test next.
- `reload_ratio` follows Udit's aggregate idea: attack volume plus same-side size change, normalized by attack.
- `hidden_ratio` is attack volume divided by displayed same-side depth in the candidate band. In this EAR population it behaved as thin support under attack, not supportive hidden liquidity.
- Today may be partial/live. Treat June 23-24 as the completed-session base.
