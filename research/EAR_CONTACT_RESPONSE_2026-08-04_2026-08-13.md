# EAR Contact Response Probe

Research-only replay. Baseline population is current EAR-style favor-displacement episodes from the existing ownership/candidate grammar. Fast-pass contact metrics use canonical snapshot depth plus tape after the displacement starts; raw add/remove deltas are optional.

## Sessions
- 2026-08-04:ESU6 09:30-10:30: candidates=22, episodes=76, favor_anchors=40, snapshot_gaps=0, book_files=0, carry_days=0, book_rows=0, book_gaps=0, crossed_repairs=0
- 2026-08-13:ESU6 09:30-10:30: candidates=30, episodes=80, favor_anchors=49, snapshot_gaps=57, book_files=0, carry_days=0, book_rows=0, book_gaps=0, crossed_repairs=0

## Baseline
- Clean resolved favor-displacement anchors: 23/89 25.8%
- CSV: `research\out\ear_open_drive\ear_contact_response_2026-08-04_2026-08-13.csv`

## Contact/Reload Separation
- `held_ratio_2s`: low<=p25 6/23 26.1%, high>=p75 4/23 17.4%, AUC=0.481 n=89
- `held_ratio_5s`: low<=p25 12/23 52.2%, high>=p75 2/23 8.7%, AUC=0.304 n=89
- `reload_ratio_2s`: low<=p25 7/25 28.0%, high>=p75 6/23 26.1%, AUC=0.473 n=89
- `reload_ratio_5s`: low<=p25 12/23 52.2%, high>=p75 3/24 12.5%, AUC=0.304 n=89
- `replenishment_5s`: low<=p25 12/23 52.2%, high>=p75 3/24 12.5%, AUC=0.302 n=89
- `hidden_ratio_5s`: low<=p25 23/88 26.1%, high>=p75 23/89 25.8%, AUC=0.492 n=89
- `attack_vol_5s`: low<=p25 23/88 26.1%, high>=p75 23/89 25.8%, AUC=0.492 n=89
- `same_depth_change_5s`: low<=p25 12/23 52.2%, high>=p75 3/24 12.5%, AUC=0.302 n=89
- `opp_depth_change_5s`: low<=p25 23/89 25.8%, high>=p75 23/89 25.8%, AUC=0.500 n=89
- `future_30s_ticks`: low<=p25 3/23 13.0%, high>=p75 13/27 48.1%, AUC=0.737 n=89

## Exploratory Gate Read
- Attack threshold p50=0.00; reload p75=4.00.
- `attacked`: 23/89 25.8%
- `top_reload_response`: 3/24 12.5%
- `negative_reload_response`: 16/51 31.4%
- Thin-attack ratio p75=0.00: 23/89 25.8%
- Attack p75=0.00 paired checks:
  - `high_attack`: 23/89 25.8%
  - `high_attack_and_held_ratio_ge_1`: 7/38 18.4%
  - `high_attack_and_depth_nonnegative`: 7/38 18.4%
  - `high_attack_and_depth_negative`: 16/51 31.4%

## Interpretation Guardrails
- These gates are selected in-sample and are only useful for deciding what to test next.
- `reload_ratio` follows Udit's aggregate idea: attack volume plus same-side size change, normalized by attack.
- `hidden_ratio` is attack volume divided by displayed same-side depth in the candidate band. In this EAR population it behaved as thin support under attack, not supportive hidden liquidity.
- Today may be partial/live. Treat June 23-24 as the completed-session base.
