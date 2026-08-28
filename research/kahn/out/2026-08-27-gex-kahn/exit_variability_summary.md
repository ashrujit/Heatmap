# 2026-08-27 ES Exit Variability And GEX

## PM Short Into 7728/7729

GEX snapshots against `7729`:

| ET | Cat | Spot | Zero | Call | OI Call | Put | OI Put | Sum Vol | Sum OI | Nearest/Dist |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| 14:18:25 | gex_zero | 7734.33 | 7735.9 | 7746.75 | 7752.95 | 7712.95 | 7727.95 | 138202 | 18654 | oi_put_wall 1.05 |
| 14:18:25 | gex_full | 7734.33 | 7735.9 | 7745 | 7912.95 | 7712.95 | 7512.95 | 146826 | 54437 | zero_gamma -6.9 |
| 14:19:27 | gex_zero | 7735.53 | 7735.45 | 7743.21 | 7752.95 | 7712.95 | 7727.95 | 187908 | 19186 | oi_put_wall 1.05 |
| 14:19:27 | gex_full | 7735.53 | 7735.45 | 7743.21 | 7812.95 | 7712.95 | 7512.95 | 197233 | 55451 | zero_gamma -6.45 |
| 14:20:29 | gex_zero | 7734.93 | 7734.56 | 7743.03 | 7738.03 | 7722.95 | 7727.95 | 195698 | 20013 | oi_put_wall 1.05 |
| 14:20:30 | gex_full | 7734.93 | 7734.56 | 7743.03 | 7912.95 | 7722.95 | 7512.95 | 204859 | 56143 | zero_gamma -5.56 |
| 14:21:32 | gex_zero | 7734.07 | 7735.45 | 7743.03 | 7738.21 | 7712.95 | 7727.95 | 135453 | 17941 | oi_put_wall 1.05 |
| 14:21:32 | gex_full | 7734.07 | 7735.45 | 7743.03 | 7912.95 | 7712.95 | 7512.95 | 144942 | 54193 | zero_gamma -6.45 |
| 14:22:34 | gex_zero | 7735.08 | 7735 | 7743.03 | 7739.56 | 7712.95 | 7727.95 | 19196 | 19756 | oi_put_wall 1.05 |
| 14:22:35 | gex_full | 7735.08 | 7735 | 7743.03 | 7812.95 | 7712.95 | 7512.95 | 201318 | 56001 | zero_gamma -6 |
| 14:23:36 | gex_zero | 7732.61 | 7736.75 | 7743.21 | 7742.7 | 7723.03 | 7727.95 | 66481 | 16824 | oi_put_wall 1.05 |
| 14:23:37 | gex_full | 7732.61 | 7736.75 | 7743.21 | 7912.95 | 7712.95 | 7512.95 | 75134 | 51249 | zero_gamma -7.75 |
| 14:24:38 | gex_zero | 7731.91 | 7736.34 | 7743.03 | 7738.03 | 7712.95 | 7727.95 | 492 | 16731 | oi_put_wall 1.05 |
| 14:24:39 | gex_full | 7731.91 | 7735.9 | 7743.03 | 7912.95 | 7712.95 | 7512.95 | 57222 | 50502 | zero_gamma -6.9 |
| 14:25:12 | gex_zero | 7731.79 | 7735.45 | 7743.03 | 7738.03 | 7712.95 | 7727.95 | 67132 | 16796 | oi_put_wall 1.05 |
| 14:25:40 | gex_zero | 7730.46 | 7735.45 | 7742.95 | 7737.95 | 7712.95 | 7727.95 | 28494 | 15823 | oi_put_wall 1.05 |
| 14:25:41 | gex_full | 7730.46 | 7735.45 | 7742.95 | 7912.95 | 7712.95 | 7512.95 | 36115 | 49259 | zero_gamma -6.45 |
| 14:26:42 | gex_zero | 7729.84 | 7735.9 | 7743.03 | 7738.03 | 7712.95 | 7727.95 | -10108 | 14799 | oi_put_wall 1.05 |
| 14:26:43 | gex_full | 7729.84 | 7735.9 | 7743.03 | 7912.95 | 7712.95 | 7512.95 | -3094 | 47647 | zero_gamma -6.9 |
| 14:27:44 | gex_zero | 7727.71 | 7735.45 | 7742.95 | 7737.95 | 7712.95 | 7727.95 | -61276 | 1388 | oi_put_wall 1.05 |
| 14:27:45 | gex_full | 7727.71 | 7735.45 | 7742.95 | 7912.95 | 7712.95 | 7512.95 | -55475 | 45233 | zero_gamma -6.45 |
| 14:28:49 | gex_zero | 7726.72 | 7735 | 7742.95 | 7737.95 | 7712.95 | 7727.95 | -85273 | 13423 | oi_put_wall 1.05 |
| 14:28:49 | gex_full | 7726.72 | 7735 | 7742.95 | 7912.95 | 7712.95 | 7512.95 | -80099 | 43845 | zero_gamma -6 |
| 14:29:51 | gex_zero | 7724.52 | 7735 | 7742.95 | 7737.95 | 7712.95 | 7727.95 | -141451 | 11478 | oi_put_wall 1.05 |
| 14:29:51 | gex_full | 7724.95 | 7735 | 7742.95 | 7912.95 | 7712.95 | 7512.95 | -122435 | 41838 | zero_gamma -6 |
| 14:30:14 | gex_zero | 7725.75 | 7735.51 | 7743.01 | 7738.01 | 7713.01 | 7728.01 | -128209 | 12522 | oi_put_wall 0.99 |
| 14:30:53 | gex_zero | 7727.16 | 7735.96 | 7743.01 | 7738.01 | 7713.01 | 7728.01 | -96613 | 1377 | oi_put_wall 0.99 |
| 14:30:54 | gex_full | 7727.16 | 7735.96 | 7743.01 | 7913.01 | 7713.01 | 7513.01 | -91746 | 43641 | zero_gamma -6.96 |
| 14:31:55 | gex_zero | 7728.67 | 7735.51 | 7743.01 | 7738.01 | 7713.01 | 7728.01 | -35318 | 15199 | oi_put_wall 0.99 |
| 14:31:56 | gex_full | 7728.67 | 7735.51 | 7743.01 | 7913.01 | 7713.01 | 7513.01 | -29583 | 4549 | zero_gamma -6.51 |
| 14:32:58 | gex_zero | 7730.04 | 7735.06 | 7743.09 | 7738.01 | 7713.01 | 7728.01 | 1912 | 16546 | oi_put_wall 0.99 |
| 14:32:58 | gex_full | 7730.04 | 7735.06 | 7743.09 | 7913.01 | 7713.01 | 7513.01 | 25666 | 47269 | zero_gamma -6.06 |

Kahn/LL events near target:

| ET | Event | Action/Kind | Side | Price/Range | Policy/Reason |
|---:|---|---|---|---|---|
| 14:18:01 | policy | SuppressAdd | None | 7733.88 | no_add_zone/inside_no_add_zone |
| 14:18:04 | ll | RailTested | Supply | mid 7734.75; 7735.5-7735.5 | - |
| 14:18:06 | policy | SuppressAdd | None | 7735.38 | no_add_zone/inside_no_add_zone |
| 14:18:11 | policy | SuppressAdd | None | 7735.12 | no_add_zone/inside_no_add_zone |
| 14:18:16 | policy | SuppressAdd | None | 7734.62 | no_add_zone/inside_no_add_zone |
| 14:18:21 | policy | SuppressAdd | None | 7734.88 | no_add_zone/inside_no_add_zone |
| 14:18:26 | policy | SuppressAdd | None | 7734.62 | no_add_zone/inside_no_add_zone |
| 14:18:32 | policy | SuppressAdd | None | 7734.62 | no_add_zone/inside_no_add_zone |
| 14:18:37 | policy | SuppressAdd | None | 7734.38 | no_add_zone/inside_no_add_zone |
| 14:18:42 | policy | SuppressAdd | None | 7734.38 | no_add_zone/inside_no_add_zone |
| 14:18:47 | policy | SuppressAdd | None | 7734.38 | no_add_zone/inside_no_add_zone |
| 14:18:52 | policy | SuppressAdd | None | 7735.38 | no_add_zone/inside_no_add_zone |
| 14:18:57 | policy | SuppressAdd | None | 7735.38 | no_add_zone/inside_no_add_zone |
| 14:19:03 | policy | SuppressAdd | None | 7735.88 | no_add_zone/inside_no_add_zone |
| 14:19:08 | policy | SuppressAdd | None | 7735.62 | no_add_zone/inside_no_add_zone |
| 14:19:12 | ll | RailFailed | Supply | mid 7735.5; 7734.25-7734.25 | time |
| 14:19:12 | ll | GreyUpdated | Demand | mid 7735.5; 7734.25-7752.5 | NoOwner |
| 14:19:12 | ll | GreyUpdated | Demand | mid 7735.5; 7734.25-7752.5 | Contested |
| 14:19:13 | policy | SuppressAdd | None | 7735.62 | no_add_zone/inside_no_add_zone |
| 14:19:16 | ll | RailTested | Supply | mid 7736; 7737-7737.5 | - |
| 14:19:16 | policy | SuppressAdd | Supply | 7737-7737.5 | evaluate_zone/inside_evaluate_zone |
| 14:19:18 | policy | SuppressAdd | None | 7736.12 | no_add_zone/inside_no_add_zone |
| 14:19:23 | policy | SuppressAdd | None | 7735.62 | no_add_zone/inside_no_add_zone |
| 14:19:28 | policy | SuppressAdd | None | 7735.38 | no_add_zone/inside_no_add_zone |
| 14:19:34 | policy | SuppressAdd | None | 7734.88 | no_add_zone/inside_no_add_zone |
| 14:19:35 | ll | RailHeld | Supply | mid 7734.5; 7737-7737.5 | - |
| 14:19:35 | policy | SuppressAdd | Supply | 7737-7737.5 | evaluate_zone/inside_evaluate_zone |
| 14:19:39 | policy | SuppressAdd | None | 7734.38 | no_add_zone/inside_no_add_zone |
| 14:19:44 | policy | SuppressAdd | None | 7733.88 | no_add_zone/inside_no_add_zone |
| 14:19:49 | policy | SuppressAdd | None | 7733.88 | no_add_zone/inside_no_add_zone |
| 14:19:54 | policy | SuppressAdd | None | 7734.12 | no_add_zone/inside_no_add_zone |
| 14:20:00 | policy | SuppressAdd | None | 7734.12 | no_add_zone/inside_no_add_zone |
| 14:20:05 | policy | SuppressAdd | None | 7733.88 | no_add_zone/inside_no_add_zone |
| 14:20:10 | policy | SuppressAdd | None | 7734.62 | no_add_zone/inside_no_add_zone |
| 14:20:15 | policy | SuppressAdd | None | 7734.88 | no_add_zone/inside_no_add_zone |
| 14:20:20 | policy | SuppressAdd | None | 7734.62 | no_add_zone/inside_no_add_zone |
| 14:20:25 | policy | SuppressAdd | None | 7735.12 | no_add_zone/inside_no_add_zone |
| 14:20:30 | policy | SuppressAdd | None | 7734.88 | no_add_zone/inside_no_add_zone |
| 14:20:35 | policy | SuppressAdd | None | 7735.38 | no_add_zone/inside_no_add_zone |
| 14:20:41 | policy | SuppressAdd | None | 7735.62 | no_add_zone/inside_no_add_zone |
| 14:20:46 | policy | SuppressAdd | None | 7735.62 | no_add_zone/inside_no_add_zone |
| 14:20:52 | policy | SuppressAdd | None | 7735.62 | no_add_zone/inside_no_add_zone |
| 14:20:55 | ll | CandidateFormed | Demand | mid 7734.75; 7734.75-7735 | - |
| 14:20:57 | policy | SuppressAdd | None | 7735.12 | no_add_zone/inside_no_add_zone |
| 14:21:02 | policy | SuppressAdd | None | 7735.12 | no_add_zone/inside_no_add_zone |
| 14:21:07 | policy | SuppressAdd | None | 7735.38 | no_add_zone/inside_no_add_zone |
| 14:21:12 | policy | SuppressAdd | None | 7735.38 | no_add_zone/inside_no_add_zone |
| 14:21:17 | policy | SuppressAdd | None | 7734.88 | no_add_zone/inside_no_add_zone |
| 14:21:22 | policy | SuppressAdd | None | 7734.38 | no_add_zone/inside_no_add_zone |
| 14:21:27 | policy | SuppressAdd | None | 7733.88 | no_add_zone/inside_no_add_zone |
| 14:21:33 | policy | SuppressAdd | None | 7734.12 | no_add_zone/inside_no_add_zone |
| 14:21:38 | policy | SuppressAdd | None | 7734.38 | no_add_zone/inside_no_add_zone |
| 14:21:43 | policy | SuppressAdd | None | 7734.88 | no_add_zone/inside_no_add_zone |
| 14:21:48 | policy | SuppressAdd | None | 7734.38 | no_add_zone/inside_no_add_zone |
| 14:21:53 | policy | SuppressAdd | None | 7734.12 | no_add_zone/inside_no_add_zone |
| 14:21:58 | policy | SuppressAdd | None | 7734.12 | no_add_zone/inside_no_add_zone |
| 14:22:04 | policy | SuppressAdd | None | 7734.62 | no_add_zone/inside_no_add_zone |
| 14:22:09 | policy | SuppressAdd | None | 7735.38 | no_add_zone/inside_no_add_zone |
| 14:22:14 | policy | SuppressAdd | None | 7735.38 | no_add_zone/inside_no_add_zone |
| 14:22:19 | policy | SuppressAdd | None | 7735.38 | no_add_zone/inside_no_add_zone |
| 14:22:24 | policy | SuppressAdd | None | 7735.12 | no_add_zone/inside_no_add_zone |
| 14:22:29 | policy | SuppressAdd | None | 7735.62 | no_add_zone/inside_no_add_zone |
| 14:22:34 | policy | SuppressAdd | None | 7734.88 | no_add_zone/inside_no_add_zone |
| 14:22:40 | policy | SuppressAdd | None | 7734.38 | no_add_zone/inside_no_add_zone |
| 14:22:45 | policy | SuppressAdd | None | 7734.12 | no_add_zone/inside_no_add_zone |
| 14:22:50 | policy | SuppressAdd | None | 7733.88 | no_add_zone/inside_no_add_zone |
| 14:22:55 | policy | SuppressAdd | None | 7734.38 | no_add_zone/inside_no_add_zone |
| 14:23:00 | policy | SuppressAdd | None | 7734.12 | no_add_zone/inside_no_add_zone |
| 14:23:05 | policy | SuppressAdd | None | 7734.12 | no_add_zone/inside_no_add_zone |
| 14:23:11 | policy | SuppressAdd | None | 7734.38 | no_add_zone/inside_no_add_zone |
| 14:23:16 | policy | SuppressAdd | None | 7734.12 | no_add_zone/inside_no_add_zone |
| 14:23:20 | ll | CandidateFormed | Supply | mid 7734.5; 7734.25-7734.5 | - |
| 14:23:21 | policy | SuppressAdd | None | 7734.38 | no_add_zone/inside_no_add_zone |
| 14:23:26 | policy | SuppressAdd | None | 7734.12 | no_add_zone/inside_no_add_zone |
| 14:23:31 | policy | SuppressAdd | None | 7734.38 | no_add_zone/inside_no_add_zone |
| 14:23:32 | policy | SuppressAdd | None | 7733.12 | path_stress/mature_path_adds_suppressed |
| 14:23:36 | ll | RailHeld | Supply | mid 7733; 7735.5-7735.5 | - |
| 14:23:36 | policy | SuppressAdd | None | 7733.38 | no_add_zone/inside_no_add_zone |
| 14:23:38 | policy | SuppressAdd | None | 7733.12 | path_stress/mature_path_adds_suppressed |
| 14:23:42 | policy | SuppressAdd | None | 7733.38 | no_add_zone/inside_no_add_zone |
| 14:23:43 | policy | SuppressAdd | None | 7733.12 | path_stress/mature_path_adds_suppressed |
| 14:23:47 | policy | SuppressAdd | None | 7733.38 | no_add_zone/inside_no_add_zone |
| 14:23:48 | policy | SuppressAdd | None | 7733.12 | path_stress/mature_path_adds_suppressed |
| 14:23:52 | policy | SuppressAdd | None | 7733.38 | no_add_zone/inside_no_add_zone |
| 14:23:54 | policy | SuppressAdd | None | 7733.12 | path_stress/mature_path_adds_suppressed |
| 14:23:59 | policy | SuppressAdd | None | 7732.12 | path_stress/mature_path_adds_suppressed |
| 14:24:04 | policy | SuppressAdd | None | 7732.12 | path_stress/mature_path_adds_suppressed |
| 14:24:04 | ll | CandidateDisplacementStarted | Demand | mid 7731.75; 7733.75-7735 | Adverse |
| 14:24:04 | ll | RailHeld | Supply | mid 7731.75; 7734.25-7736 | - |
| 14:24:04 | policy | SuppressAdd | Supply | 7734.25-7736 | no_add_zone/inside_no_add_zone |
| 14:24:05 | ll | CandidateDisplacementReset | Demand | mid 7732; 7733.75-7735 | inside_threshold |
| 14:24:09 | policy | SuppressAdd | None | 7732.38 | path_stress/mature_path_adds_suppressed |
| 14:24:14 | policy | SuppressAdd | None | 7732.12 | path_stress/mature_path_adds_suppressed |
| 14:24:20 | policy | SuppressAdd | None | 7732.12 | path_stress/mature_path_adds_suppressed |
| 14:24:25 | policy | SuppressAdd | None | 7732.62 | path_stress/mature_path_adds_suppressed |
| 14:24:30 | policy | SuppressAdd | None | 7732.62 | path_stress/mature_path_adds_suppressed |
| 14:24:35 | ll | CandidateDisplacementStarted | Demand | mid 7731.75; 7733.75-7735 | Adverse |
| 14:24:35 | policy | SuppressAdd | None | 7731.88 | path_stress/mature_path_adds_suppressed |
| 14:24:37 | ll | CandidateDisplacementReset | Demand | mid 7732.25; 7733.75-7735 | inside_threshold |
| 14:24:40 | policy | SuppressAdd | None | 7732.12 | path_stress/mature_path_adds_suppressed |
| 14:24:43 | ll | CandidateDisplacementStarted | Demand | mid 7731.75; 7733.75-7735 | Adverse |
| 14:24:45 | policy | SuppressAdd | None | 7731.88 | path_stress/mature_path_adds_suppressed |
| 14:24:46 | ll | CandidateDisplacementStarted | Supply | mid 7731.5; 7733.5-7734.5 | Favor |
| 14:24:49 | ll | CandidateDisplacementReset | Supply | mid 7731.75; 7733.5-7734.5 | inside_threshold |
| 14:24:50 | policy | SuppressAdd | None | 7731.88 | path_stress/mature_path_adds_suppressed |
| 14:24:51 | ll | CandidateDisplacementReset | Demand | mid 7732; 7733.75-7735 | inside_threshold |
| 14:24:55 | policy | SuppressAdd | None | 7732.38 | path_stress/mature_path_adds_suppressed |
| 14:25:01 | policy | SuppressAdd | None | 7732.38 | path_stress/mature_path_adds_suppressed |
| 14:25:06 | policy | SuppressAdd | None | 7732.12 | path_stress/mature_path_adds_suppressed |
| 14:25:10 | ll | CandidateDisplacementStarted | Demand | mid 7731.75; 7733.75-7735 | Adverse |
| 14:25:11 | ll | CandidateDisplacementReset | Demand | mid 7732; 7733.75-7735 | inside_threshold |
| 14:25:11 | policy | SuppressAdd | None | 7732.12 | path_stress/mature_path_adds_suppressed |
| 14:25:15 | ll | CandidateDisplacementStarted | Demand | mid 7731.75; 7733.75-7735 | Adverse |
| 14:25:16 | policy | SuppressAdd | None | 7731.88 | path_stress/mature_path_adds_suppressed |
| 14:25:19 | ll | CandidateDisplacementStarted | Supply | mid 7731.5; 7733.5-7734.5 | Favor |
| 14:25:21 | policy | SuppressAdd | None | 7731.62 | path_stress/mature_path_adds_suppressed |
| 14:25:25 | ll | RailOwned | Supply | mid 7731.25; 7733.75-7735 | CONSUMED |
| 14:25:25 | policy | SuppressAdd | Supply | 7733.75-7735 | no_add_zone/inside_no_add_zone |
| 14:25:26 | policy | SuppressAdd | None | 7731.38 | path_stress/mature_path_adds_suppressed |
| 14:25:30 | ll | RailOwned | Supply | mid 7730.75; 7733.5-7734.5 | OWNED |
| 14:25:31 | policy | SuppressAdd | None | 7730.5 | path_stress/mature_path_adds_suppressed |
| 14:25:37 | policy | SuppressAdd | None | 7730.88 | path_stress/mature_path_adds_suppressed |
| 14:25:42 | policy | SuppressAdd | None | 7730.88 | path_stress/mature_path_adds_suppressed |
| 14:25:47 | policy | SuppressAdd | None | 7730.88 | path_stress/mature_path_adds_suppressed |
| 14:25:52 | policy | SuppressAdd | None | 7730.62 | path_stress/mature_path_adds_suppressed |
| 14:25:57 | policy | SuppressAdd | None | 7730.62 | path_stress/mature_path_adds_suppressed |
| 14:26:02 | policy | SuppressAdd | None | 7730.62 | path_stress/mature_path_adds_suppressed |
| 14:26:08 | policy | SuppressAdd | None | 7730.88 | path_stress/mature_path_adds_suppressed |
| 14:26:13 | policy | SuppressAdd | None | 7730.88 | path_stress/mature_path_adds_suppressed |
| 14:26:18 | policy | SuppressAdd | None | 7731.12 | path_stress/mature_path_adds_suppressed |
| 14:26:23 | policy | SuppressAdd | None | 7731.12 | path_stress/mature_path_adds_suppressed |
| 14:26:28 | policy | SuppressAdd | None | 7730.62 | path_stress/mature_path_adds_suppressed |
| 14:26:30 | ll | CandidateFormed | Demand | mid 7730.25; 7730.25-7730.75 | - |
| 14:26:33 | policy | SuppressAdd | None | 7729.75 | path_stress/mature_path_adds_suppressed |
| 14:26:38 | policy | SuppressAdd | None | 7730.38 | path_stress/mature_path_adds_suppressed |
| 14:26:44 | policy | SuppressAdd | None | 7730.12 | path_stress/mature_path_adds_suppressed |
| 14:26:49 | policy | SuppressAdd | None | 7729.88 | path_stress/mature_path_adds_suppressed |
| 14:26:54 | policy | SuppressAdd | None | 7729.62 | path_stress/mature_path_adds_suppressed |
| 14:26:59 | policy | SuppressAdd | None | 7729.62 | path_stress/mature_path_adds_suppressed |
| 14:27:05 | policy | SuppressAdd | None | 7729.12 | path_stress/mature_path_adds_suppressed |
| 14:27:10 | policy | SuppressAdd | None | 7728.88 | path_stress/mature_path_adds_suppressed |
| 14:27:15 | policy | SuppressAdd | None | 7728.12 | path_stress/mature_path_adds_suppressed |
| 14:27:15 | ll | CandidateDisplacementStarted | Demand | mid 7727.75; 7729.75-7730.75 | Adverse |
| 14:27:17 | ll | CandidateDisplacementReset | Demand | mid 7728; 7729.75-7730.75 | inside_threshold |
| 14:27:20 | policy | SuppressAdd | None | 7728.12 | path_stress/mature_path_adds_suppressed |
| 14:27:22 | ll | CandidateDisplacementStarted | Demand | mid 7727.75; 7729.75-7730.75 | Adverse |
| 14:27:25 | policy | SuppressAdd | None | 7727.88 | path_stress/mature_path_adds_suppressed |
| 14:27:26 | ll | CandidateDisplacementReset | Demand | mid 7728.25; 7729.75-7730.75 | inside_threshold |
| 14:27:30 | policy | SuppressAdd | None | 7728.12 | path_stress/mature_path_adds_suppressed |
| 14:27:34 | ll | CandidateDisplacementStarted | Demand | mid 7727.75; 7729.75-7730.75 | Adverse |
| 14:27:35 | policy | SuppressAdd | None | 7728.12 | path_stress/mature_path_adds_suppressed |
| 14:27:35 | ll | CandidateDisplacementReset | Demand | mid 7728; 7729.75-7730.75 | inside_threshold |
| 14:27:40 | policy | SuppressAdd | None | 7728.12 | path_stress/mature_path_adds_suppressed |
| 14:27:42 | ll | CandidateDisplacementStarted | Demand | mid 7727.75; 7729.75-7730.75 | Adverse |
| 14:27:45 | policy | SuppressAdd | None | 7727.62 | path_stress/mature_path_adds_suppressed |
| 14:27:50 | policy | SuppressAdd | None | 7727.38 | path_stress/mature_path_adds_suppressed |
| 14:27:52 | ll | RailOwned | Supply | mid 7727; 7729.75-7730.75 | CONSUMED |
| 14:27:55 | policy | SuppressAdd | None | 7726.38 | path_stress/mature_path_adds_suppressed |
| 14:28:01 | policy | SuppressAdd | None | 7726.62 | path_stress/mature_path_adds_suppressed |
| 14:28:06 | policy | SuppressAdd | None | 7726.12 | path_stress/mature_path_adds_suppressed |
| 14:28:20 | policy | SuppressAdd | None | 7725.88 | path_stress/mature_path_adds_suppressed |
| 14:28:25 | policy | SuppressAdd | None | 7725.88 | path_stress/mature_path_adds_suppressed |
| 14:28:30 | policy | SuppressAdd | None | 7725.88 | path_stress/mature_path_adds_suppressed |
| 14:28:35 | policy | SuppressAdd | None | 7726.12 | path_stress/mature_path_adds_suppressed |
| 14:28:40 | policy | SuppressAdd | None | 7726.88 | path_stress/mature_path_adds_suppressed |
| 14:28:45 | policy | SuppressAdd | None | 7726.62 | path_stress/mature_path_adds_suppressed |
| 14:28:50 | policy | SuppressAdd | None | 7726.38 | path_stress/mature_path_adds_suppressed |
| 14:28:55 | policy | SuppressAdd | None | 7726.62 | path_stress/mature_path_adds_suppressed |
| 14:29:00 | policy | SuppressAdd | None | 7726.62 | path_stress/mature_path_adds_suppressed |
| 14:29:06 | policy | SuppressAdd | None | 7725.88 | path_stress/mature_path_adds_suppressed |
| 14:29:11 | policy | SuppressAdd | None | 7725.88 | path_stress/mature_path_adds_suppressed |
| 14:29:17 | policy | SuppressAdd | None | 7725.88 | path_stress/mature_path_adds_suppressed |
| 14:29:54 | policy | SuppressAdd | None | 7725.88 | path_stress/mature_path_adds_suppressed |
| 14:30:00 | policy | SuppressAdd | None | 7725.88 | path_stress/mature_path_adds_suppressed |
| 14:30:05 | policy | SuppressAdd | None | 7725.88 | path_stress/mature_path_adds_suppressed |
| 14:30:07 | ll | CandidateFormed | Supply | mid 7726.5; 7725.75-7726.5 | - |
| 14:30:11 | policy | SuppressAdd | None | 7725.88 | path_stress/mature_path_adds_suppressed |
| 14:30:16 | policy | SuppressAdd | None | 7725.88 | path_stress/mature_path_adds_suppressed |
| 14:30:21 | policy | SuppressAdd | None | 7727.38 | path_stress/mature_path_adds_suppressed |
| 14:30:26 | policy | SuppressAdd | None | 7727.12 | path_stress/mature_path_adds_suppressed |
| 14:30:31 | policy | SuppressAdd | None | 7726.38 | path_stress/mature_path_adds_suppressed |
| 14:30:36 | policy | SuppressAdd | None | 7726.62 | path_stress/mature_path_adds_suppressed |
| 14:30:41 | policy | SuppressAdd | None | 7727.38 | path_stress/mature_path_adds_suppressed |
| 14:30:46 | policy | SuppressAdd | None | 7727.12 | path_stress/mature_path_adds_suppressed |
| 14:30:51 | policy | SuppressAdd | None | 7727.38 | path_stress/mature_path_adds_suppressed |
| 14:30:57 | policy | SuppressAdd | None | 7727.12 | path_stress/mature_path_adds_suppressed |
| 14:31:02 | policy | SuppressAdd | None | 7727.62 | path_stress/mature_path_adds_suppressed |
| 14:31:07 | policy | SuppressAdd | None | 7728.12 | path_stress/mature_path_adds_suppressed |
| 14:31:12 | policy | SuppressAdd | None | 7728.12 | path_stress/mature_path_adds_suppressed |
| 14:31:17 | policy | SuppressAdd | None | 7727.38 | path_stress/mature_path_adds_suppressed |
| 14:31:22 | policy | SuppressAdd | None | 7727.62 | path_stress/mature_path_adds_suppressed |
| 14:31:28 | policy | SuppressAdd | None | 7728.38 | path_stress/mature_path_adds_suppressed |
| 14:31:33 | policy | SuppressAdd | None | 7727.88 | path_stress/mature_path_adds_suppressed |
| 14:31:35 | ll | CandidateDisplacementStarted | Supply | mid 7728.5; 7725.75-7726.5 | Adverse |
| 14:31:37 | ll | CandidateDisplacementReset | Supply | mid 7728.25; 7725.75-7726.5 | inside_threshold |
| 14:31:38 | policy | SuppressAdd | None | 7728.62 | path_stress/mature_path_adds_suppressed |
| 14:31:38 | ll | CandidateDisplacementStarted | Supply | mid 7728.5; 7725.75-7726.5 | Adverse |
| 14:31:40 | ll | RailTested | Supply | mid 7728.75; 7729.75-7730.75 | - |
| 14:31:43 | policy | SuppressAdd | None | 7728.88 | path_stress/mature_path_adds_suppressed |
| 14:31:48 | policy | SuppressAdd | None | 7729.12 | path_stress/mature_path_adds_suppressed |
| 14:31:48 | ll | RailOwned | Demand | mid 7729; 7725.75-7726.5 | CONSUMED |
| 14:31:48 | policy | Retire | Demand | 7725.75-7726.5 | target_zone/opposite_ownership_at_target |
| 14:31:49 | ll | FailureCandidateFormed | Demand | mid 7729; 7725.75-7729 | - |
| 14:32:22 | ll | CandidateFormed | Supply | mid 7729.5; 7729.5-7729.5 | - |
| 14:33:39 | ll | CandidateFormed | Demand | mid 7728; 7728-7728.75 | - |
| 14:33:49 | ll | CandidateDisplacementStarted | Supply | mid 7727.5; 7729.5-7729.75 | Favor |
| 14:33:49 | ll | RailTested | Demand | mid 7727.5; 7725.75-7726.5 | - |
| 14:33:50 | ll | RailHeld | Supply | mid 7727; 7729.75-7730.75 | - |
| 14:33:59 | ll | RailOwned | Supply | mid 7726.25; 7729.5-7729.75 | OWNED |

Tick bars:

| ET | O | H | L | C | Vol | Delta | Vol pct |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 14:18:00 | 7734 | 7735.75 | 7733.75 | 7735.5 | 2335 | 627 | 59% |
| 14:19:00 | 7735.75 | 7736.25 | 7733.75 | 7734.25 | 1538 | -94 | 3% |
| 14:20:00 | 7734 | 7735.75 | 7733.75 | 7735.25 | 1905 | 263 | 44% |
| 14:21:00 | 7735 | 7735.5 | 7733.75 | 7734.75 | 179 | 106 | 39% |
| 14:22:00 | 7734.75 | 7735.75 | 7733.75 | 7734.25 | 1283 | -11 | 19% |
| 14:23:00 | 7734 | 7734.5 | 7731.75 | 7732 | 2329 | -73 | 59% |
| 14:24:00 | 7732 | 7732.75 | 7731.25 | 7732.25 | 1542 | 6 | 3% |
| 14:25:00 | 7732.25 | 7732.5 | 7730.25 | 7731 | 1813 | -49 | 4% |
| 14:26:00 | 7731 | 7731.5 | 7729.5 | 7729.5 | 2289 | -377 | 58% |
| 14:27:00 | 7729.5 | 7729.5 | 7726.25 | 7726.5 | 2995 | -303 | 76% |
| 14:28:00 | 7726.25 | 7727.25 | 7724.25 | 7726.5 | 4372 | -178 | 88% |
| 14:29:00 | 7726.25 | 7726.5 | 7723.75 | 7725.75 | 359 | 272 | 83% |
| 14:30:00 | 7726 | 7727.75 | 7725.25 | 7727.5 | 3349 | 719 | 81% |
| 14:31:00 | 7727.25 | 7729.75 | 7727.25 | 7729 | 2529 | 421 | 65% |
| 14:32:00 | 7728.75 | 7730.75 | 7728.25 | 7730 | 2694 | 364 | 69% |
| 14:33:00 | 7729.75 | 7730.75 | 7726.25 | 7726.25 | 2778 | 19 | 71% |
| 14:34:00 | 7726.25 | 7727 | 7725.5 | 7726.75 | 201 | -222 | 48% |

BubbleTape:

- No replay rows in this window.

## Late-Morning Long Near 7743

GEX snapshots against `7743`:

| ET | Cat | Spot | Zero | Call | OI Call | Put | OI Put | Sum Vol | Sum OI | Nearest/Dist |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| 10:35:03 | gex_zero | 7724.83 | 7715.09 | 7743.04 | 7753.04 | 7703.04 | 7728.04 | 67791 | 11377 | call_wall -0.04 |
| 10:35:04 | gex_full | 7724.76 | 7715.09 | 7743.04 | 7813.04 | 7703.04 | 7513.04 | 69471 | 38282 | call_wall -0.04 |
| 10:36:05 | gex_zero | 7728.39 | 7715.09 | 7743.04 | 7753.04 | 7703.04 | 7728.04 | 87765 | 13373 | call_wall -0.04 |
| 10:36:06 | gex_full | 7728.39 | 7715.09 | 7743.04 | 7813.04 | 7703.04 | 7513.04 | 9043 | 41204 | call_wall -0.04 |
| 10:37:07 | gex_zero | 7729.02 | 7715.09 | 7743.04 | 7753.04 | 7703.04 | 7728.04 | 93624 | 13918 | call_wall -0.04 |
| 10:37:07 | gex_full | 7729.02 | 7714.65 | 7743.04 | 7813.04 | 7703.04 | 7513.04 | 96586 | 42488 | call_wall -0.04 |
| 10:38:09 | gex_zero | 7728.72 | 7715.54 | 7743.04 | 7753.04 | 7703.04 | 7728.04 | 92983 | 13583 | call_wall -0.04 |
| 10:38:09 | gex_full | 7728.72 | 7715.09 | 7743.04 | 7813.04 | 7703.04 | 7513.04 | 96462 | 42281 | call_wall -0.04 |
| 10:39:11 | gex_zero | 7727.51 | 7715.09 | 7743.04 | 7753.04 | 7703.04 | 7728.04 | 91049 | 1318 | call_wall -0.04 |
| 10:39:11 | gex_full | 7726.76 | 7715.09 | 7743.04 | 7813.04 | 7703.04 | 7513.04 | 91277 | 40932 | call_wall -0.04 |
| 10:40:13 | gex_zero | 7724.35 | 7715.54 | 7743.04 | 7753.04 | 7703.04 | 7728.04 | 68533 | 11092 | call_wall -0.04 |
| 10:40:13 | gex_full | 7724.35 | 7715.54 | 7743.04 | 7813.04 | 7703.04 | 7513.04 | 71468 | 38406 | call_wall -0.04 |
| 10:41:15 | gex_zero | 7726.35 | 7715.54 | 7743.04 | 7753.04 | 7703.04 | 7728.04 | 85305 | 12549 | call_wall -0.04 |
| 10:41:15 | gex_full | 7726.35 | 7715.09 | 7743.04 | 7813.04 | 7703.04 | 7513.04 | 88324 | 39991 | call_wall -0.04 |
| 10:42:17 | gex_zero | 7726.93 | 7715.54 | 7743.04 | 7753.04 | 7703.04 | 7728.04 | 91054 | 13117 | call_wall -0.04 |
| 10:42:17 | gex_full | 7726.93 | 7715.09 | 7743.04 | 7813.04 | 7703.04 | 7513.04 | 94129 | 40566 | call_wall -0.04 |
| 10:43:19 | gex_zero | 7727.6 | 7715.54 | 7743.04 | 7753.04 | 7703.04 | 7728.04 | 92579 | 13039 | call_wall -0.04 |
| 10:43:19 | gex_full | 7727.6 | 7715.54 | 7743.04 | 7813.04 | 7703.04 | 7513.04 | 95784 | 40724 | call_wall -0.04 |
| 10:44:21 | gex_zero | 7725.74 | 7715.54 | 7743.04 | 7753.04 | 7703.04 | 7728.04 | 83205 | 12157 | call_wall -0.04 |
| 10:44:21 | gex_full | 7725.74 | 7715.54 | 7743.04 | 7813.04 | 7703.04 | 7513.04 | 86314 | 39547 | call_wall -0.04 |
| 10:45:22 | gex_zero | 7726.71 | 7716.5 | 7743.55 | 7753.55 | 7703.55 | 7728.55 | 83235 | 12229 | call_wall -0.55 |
| 10:45:23 | gex_full | 7727.69 | 7716.05 | 7743.55 | 7813.55 | 7703.55 | 7513.55 | 92414 | 40166 | call_wall -0.55 |
| 10:46:24 | gex_zero | 7729.29 | 7716.5 | 7743.55 | 7753.55 | 7703.55 | 7728.55 | 103169 | 13905 | call_wall -0.55 |
| 10:46:25 | gex_full | 7729.29 | 7716.05 | 7743.55 | 7813.55 | 7703.55 | 7513.55 | 106188 | 41877 | call_wall -0.55 |
| 10:47:26 | gex_zero | 7726.06 | 7716.05 | 7743.55 | 7753.55 | 7703.55 | 7728.55 | 87603 | 1221 | call_wall -0.55 |
| 10:47:27 | gex_full | 7726.06 | 7715.6 | 7743.55 | 7813.55 | 7703.55 | 7513.55 | 9061 | 39991 | call_wall -0.55 |
| 10:48:28 | gex_zero | 7728.02 | 7716.05 | 7743.55 | 7753.55 | 7703.55 | 7728.55 | 95255 | 13071 | call_wall -0.55 |
| 10:48:29 | gex_full | 7728.02 | 7716.05 | 7743.55 | 7813.55 | 7703.55 | 7513.55 | 98208 | 40756 | call_wall -0.55 |
| 10:49:30 | gex_zero | 7732.78 | 7716.93 | 7743.55 | 7753.55 | 7703.55 | 7728.55 | 123912 | 15688 | call_wall -0.55 |
| 10:49:30 | gex_full | 7732.78 | 7716.5 | 7743.55 | 7813.55 | 7703.55 | 7513.55 | 127673 | 45193 | call_wall -0.55 |
| 10:50:32 | gex_zero | 7733.68 | 7716.5 | 7743.55 | 7753.55 | 7703.55 | 7728.55 | 136925 | 16427 | call_wall -0.55 |
| 10:50:33 | gex_full | 7733.68 | 7716.5 | 7743.55 | 7813.55 | 7703.55 | 7513.55 | 141111 | 47155 | call_wall -0.55 |
| 10:51:34 | gex_zero | 7732.58 | 7716.5 | 7743.55 | 7753.55 | 7703.55 | 7728.55 | 131759 | 15776 | call_wall -0.55 |
| 10:51:35 | gex_full | 7732.58 | 7716.5 | 7743.55 | 7813.55 | 7703.55 | 7513.55 | 135877 | 46294 | call_wall -0.55 |
| 10:52:36 | gex_zero | 7734.24 | 7716.5 | 7743.55 | 7753.55 | 7703.55 | 7728.55 | 143433 | 16822 | call_wall -0.55 |
| 10:52:36 | gex_full | 7734.24 | 7716.5 | 7743.55 | 7813.55 | 7703.55 | 7513.55 | 147531 | 48944 | call_wall -0.55 |
| 10:53:38 | gex_zero | 7733.1 | 7716.5 | 7743.55 | 7753.55 | 7703.55 | 7728.55 | 140762 | 16391 | call_wall -0.55 |
| 10:53:38 | gex_full | 7732.61 | 7716.5 | 7743.55 | 7813.55 | 7703.55 | 7513.55 | 143922 | 47557 | call_wall -0.55 |
| 10:54:40 | gex_zero | 7731.83 | 7717.35 | 7743.55 | 7753.55 | 7703.55 | 7728.55 | 128158 | 15379 | call_wall -0.55 |
| 10:54:40 | gex_full | 7731.83 | 7717.35 | 7743.55 | 7813.55 | 7703.55 | 7513.55 | 131938 | 45828 | call_wall -0.55 |
| 10:55:42 | gex_zero | 7730.51 | 7716.93 | 7743.55 | 7753.55 | 7703.55 | 7728.55 | 123001 | 14841 | call_wall -0.55 |
| 10:55:42 | gex_full | 7730.51 | 7716.93 | 7743.55 | 7813.55 | 7703.55 | 7513.55 | 126852 | 45499 | call_wall -0.55 |
| 10:56:44 | gex_zero | 7730.23 | 7716.93 | 7743.55 | 7753.55 | 7703.55 | 7728.55 | 121577 | 14769 | call_wall -0.55 |
| 10:56:44 | gex_full | 7730.23 | 7716.93 | 7743.55 | 7813.55 | 7703.55 | 7513.55 | 125281 | 45026 | call_wall -0.55 |
| 10:57:45 | gex_zero | 7732.31 | 7716.93 | 7743.55 | 7753.55 | 7703.55 | 7728.55 | 140881 | 16138 | call_wall -0.55 |
| 10:57:46 | gex_full | 7732.27 | 7716.93 | 7743.55 | 7813.55 | 7703.55 | 7513.55 | 142669 | 46709 | call_wall -0.55 |
| 10:58:47 | gex_zero | 7733.15 | 7717.35 | 7743.55 | 7753.55 | 7703.55 | 7728.55 | 140044 | 16112 | call_wall -0.55 |
| 10:58:48 | gex_full | 7733.15 | 7716.93 | 7743.55 | 7813.55 | 7703.55 | 7513.55 | 143962 | 47019 | call_wall -0.55 |
| 10:59:49 | gex_zero | 7734.13 | 7717.35 | 7743.55 | 7753.55 | 7703.55 | 7728.55 | 143384 | 16435 | call_wall -0.55 |
| 10:59:50 | gex_full | 7734.3 | 7717.35 | 7743.55 | 7813.55 | 7703.55 | 7513.55 | 148491 | 49257 | call_wall -0.55 |
| 11:00:51 | gex_zero | 7736.04 | 7717.97 | 7743.8 | 7753.8 | 7703.8 | 7728.8 | 152706 | 17094 | call_wall -0.8 |
| 11:00:52 | gex_full | 7736.04 | 7717.97 | 7743.8 | 7813.8 | 7703.8 | 7513.8 | 157222 | 50471 | call_wall -0.8 |
| 11:01:53 | gex_zero | 7737.96 | 7717.97 | 7743.8 | 7753.8 | 7703.8 | 7728.8 | 170147 | 1848 | call_wall -0.8 |
| 11:01:53 | gex_full | 7737.96 | 7717.97 | 7743.8 | 7813.8 | 7703.8 | 7513.8 | 174995 | 52607 | call_wall -0.8 |
| 11:02:55 | gex_zero | 7736.87 | 7717.97 | 7743.8 | 7753.8 | 7703.8 | 7728.8 | 168731 | 18075 | call_wall -0.8 |
| 11:02:55 | gex_full | 7736.87 | 7717.97 | 7743.8 | 7813.8 | 7703.8 | 7513.8 | 173629 | 52345 | call_wall -0.8 |
| 11:03:57 | gex_zero | 7734.09 | 7718.29 | 7743.8 | 7753.8 | 7703.8 | 7728.8 | 145571 | 16203 | call_wall -0.8 |
| 11:03:57 | gex_full | 7734.09 | 7718.29 | 7743.8 | 7813.8 | 7703.8 | 7513.8 | 150175 | 50095 | call_wall -0.8 |
| 11:04:58 | gex_zero | 7737.8 | 7717.97 | 7743.8 | 7753.8 | 7703.8 | 7728.8 | 18038 | 18986 | call_wall -0.8 |
| 11:04:59 | gex_full | 7737.8 | 7717.97 | 7743.8 | 7813.8 | 7703.8 | 7513.8 | 185233 | 534 | call_wall -0.8 |
| 11:06:00 | gex_zero | 7737.33 | 7718.29 | 7743.8 | 7753.8 | 7703.88 | 7728.8 | 169998 | 18002 | call_wall -0.8 |
| 11:06:01 | gex_full | 7737.33 | 7718.29 | 7743.8 | 7813.8 | 7703.8 | 7513.8 | 17506 | 52663 | call_wall -0.8 |
| 11:07:02 | gex_zero | 7736.42 | 7717.97 | 7743.8 | 7753.8 | 7703.8 | 7728.8 | 174019 | 18133 | call_wall -0.8 |
| 11:07:03 | gex_full | 7736.42 | 7717.97 | 7743.8 | 7813.8 | 7703.8 | 7513.8 | 179102 | 5277 | call_wall -0.8 |
| 11:08:04 | gex_zero | 7735.57 | 7718.54 | 7743.8 | 7753.8 | 7703.8 | 7728.8 | 164877 | 17406 | call_wall -0.8 |
| 11:08:04 | gex_full | 7735.25 | 7718.54 | 7743.8 | 7813.8 | 7703.8 | 7513.8 | 167123 | 51394 | call_wall -0.8 |
| 11:09:06 | gex_zero | 7736.2 | 7718.54 | 7743.8 | 7753.8 | 7703.8 | 7728.8 | 165587 | 17557 | call_wall -0.8 |
| 11:09:06 | gex_full | 7736.2 | 7718.29 | 7743.8 | 7813.8 | 7703.8 | 7513.8 | 170628 | 51718 | call_wall -0.8 |
| 11:10:08 | gex_zero | 7737.72 | 7718.29 | 7743.8 | 7753.8 | 7703.8 | 7728.8 | 185445 | 19145 | call_wall -0.8 |
| 11:10:08 | gex_full | 7737.72 | 7718.29 | 7743.8 | 7813.8 | 7703.8 | 7513.8 | 190637 | 53524 | call_wall -0.8 |
| 11:11:10 | gex_zero | 7737.11 | 7718.54 | 7743.8 | 7753.8 | 7703.88 | 7728.8 | 174231 | 18001 | call_wall -0.8 |
| 11:11:10 | gex_full | 7737.11 | 7718.29 | 7743.8 | 7813.8 | 7703.8 | 7513.8 | 179606 | 52675 | call_wall -0.8 |
| 11:11:47 | gex_zero | 7738.49 | 7718.29 | 7743.8 | 7753.8 | 7703.88 | 7728.8 | 189109 | 19315 | call_wall -0.8 |
| 11:12:12 | gex_zero | 7737.83 | 7718.54 | 7743.8 | 7753.8 | 7703.88 | 7728.8 | 183133 | 18772 | call_wall -0.8 |
| 11:12:12 | gex_full | 7737.83 | 7718.29 | 7743.8 | 7813.8 | 7703.8 | 7513.8 | 188719 | 53856 | call_wall -0.8 |
| 11:13:13 | gex_zero | 7737.48 | 7718.29 | 7743.8 | 7753.8 | 7703.88 | 7728.8 | 18667 | 19123 | call_wall -0.8 |
| 11:13:14 | gex_full | 7737.81 | 7718.29 | 7743.8 | 7813.8 | 7703.88 | 7513.8 | 192243 | 54157 | call_wall -0.8 |
| 11:14:15 | gex_zero | 7737.75 | 7718.54 | 7743.8 | 7753.8 | 7713.54 | 7728.8 | 184669 | 18652 | call_wall -0.8 |
| 11:14:16 | gex_full | 7737.75 | 7718.54 | 7743.8 | 7813.8 | 7703.8 | 7513.8 | 19029 | 53895 | call_wall -0.8 |
| 11:15:17 | gex_zero | 7740.12 | 7718.59 | 7743.84 | 7753.84 | 7713.76 | 7728.84 | 210955 | 20606 | call_wall -0.84 |
| 11:15:18 | gex_full | 7740.03 | 7718.34 | 7743.84 | 7813.84 | 7703.84 | 7513.84 | 216874 | 56998 | call_wall -0.84 |
| 11:16:19 | gex_zero | 7741.8 | 7718.76 | 7743.84 | 7753.84 | 7713.76 | 7728.84 | 214082 | 21187 | call_wall -0.84 |
| 11:16:19 | gex_full | 7741.8 | 7718.59 | 7743.84 | 7813.84 | 7713.76 | 7513.84 | 220457 | 58569 | call_wall -0.84 |
| 11:17:21 | gex_zero | 7742.39 | 7718.59 | 7743.84 | 7753.84 | 7713.76 | 7728.84 | 220238 | 21534 | call_wall -0.84 |
| 11:17:21 | gex_full | 7742.36 | 7718.59 | 7743.84 | 7813.84 | 7713.76 | 7513.84 | 223449 | 59006 | call_wall -0.84 |
| 11:18:23 | gex_zero | 7741.45 | 7718.93 | 7743.84 | 7753.84 | 7713.76 | 7728.84 | 212898 | 20365 | call_wall -0.84 |
| 11:18:23 | gex_full | 7741.45 | 7718.84 | 7743.84 | 7813.84 | 7713.76 | 7513.84 | 220062 | 5824 | call_wall -0.84 |
| 11:19:25 | gex_zero | 7741.67 | 7718.84 | 7743.84 | 7753.84 | 7713.76 | 7728.84 | 23051 | 21478 | call_wall -0.84 |
| 11:19:25 | gex_full | 7741.67 | 7718.76 | 7743.84 | 7813.84 | 7713.76 | 7513.84 | 237902 | 59538 | call_wall -0.84 |
| 11:20:27 | gex_zero | 7741.69 | 7719.1 | 7743.84 | 7753.84 | 7713.76 | 7728.84 | 220047 | 21044 | call_wall -0.84 |
| 11:20:27 | gex_full | 7741.69 | 7718.93 | 7743.84 | 7813.84 | 7713.76 | 7513.84 | 227303 | 5881 | call_wall -0.84 |
| 11:21:28 | gex_zero | 7742.22 | 7718.84 | 7743.84 | 7753.84 | 7713.76 | 7728.84 | 227807 | 21454 | call_wall -0.84 |
| 11:21:29 | gex_full | 7742.22 | 7718.76 | 7743.84 | 7813.84 | 7713.76 | 7513.84 | 235012 | 59218 | call_wall -0.84 |
| 11:22:30 | gex_zero | 7740.29 | 7718.84 | 7743.84 | 7753.84 | 7713.84 | 7728.84 | 222705 | 20682 | call_wall -0.84 |
| 11:22:31 | gex_full | 7740.29 | 7718.76 | 7743.84 | 7813.84 | 7713.76 | 7513.84 | 229963 | 58306 | call_wall -0.84 |
| 11:23:32 | gex_zero | 7739.61 | 7719.35 | 7743.84 | 7753.84 | 7713.76 | 7728.84 | 211133 | 19786 | call_wall -0.84 |
| 11:23:33 | gex_full | 7739.22 | 7719.1 | 7743.84 | 7813.84 | 7713.76 | 7513.84 | 215844 | 56519 | call_wall -0.84 |
| 11:24:34 | gex_zero | 7740.16 | 7719.1 | 7743.84 | 7753.84 | 7713.76 | 7728.84 | 21963 | 20594 | call_wall -0.84 |
| 11:24:34 | gex_full | 7740.16 | 7718.93 | 7743.84 | 7813.84 | 7713.76 | 7513.84 | 226733 | 57695 | call_wall -0.84 |
| 11:25:36 | gex_zero | 7736.92 | 7719.35 | 7743.84 | 7753.84 | 7713.76 | 7728.84 | 187961 | 18011 | call_wall -0.84 |
| 11:25:36 | gex_full | 7737.39 | 7719.67 | 7743.84 | 7813.84 | 7713.76 | 7513.84 | 194998 | 54176 | call_wall -0.84 |
| 11:26:38 | gex_zero | 7737.98 | 7719.35 | 7743.84 | 7753.84 | 7713.84 | 7728.84 | 204198 | 19216 | call_wall -0.84 |
| 11:26:38 | gex_full | 7737.88 | 7719.1 | 7743.84 | 7813.84 | 7713.76 | 7513.84 | 211295 | 55169 | call_wall -0.84 |
| 11:27:40 | gex_zero | 7738.08 | 7719.35 | 7743.84 | 7753.84 | 7713.76 | 7728.84 | 202689 | 18875 | call_wall -0.84 |
| 11:27:40 | gex_full | 7738.08 | 7719.1 | 7743.84 | 7813.84 | 7713.76 | 7513.84 | 209272 | 5486 | call_wall -0.84 |
| 11:28:42 | gex_zero | 7737.05 | 7719.67 | 7743.84 | 7753.84 | 7713.84 | 7728.84 | 192372 | 18186 | call_wall -0.84 |
| 11:28:42 | gex_full | 7737.05 | 7719.67 | 7743.84 | 7813.84 | 7713.84 | 7513.84 | 198712 | 53656 | call_wall -0.84 |
| 11:29:43 | gex_zero | 7734.49 | 7719.35 | 7743.84 | 7753.84 | 7713.84 | 7728.84 | 175662 | 16947 | call_wall -0.84 |
| 11:29:44 | gex_full | 7734.49 | 7719.35 | 7743.84 | 7813.84 | 7713.84 | 7513.84 | 181747 | 51972 | call_wall -0.84 |
| 11:30:45 | gex_zero | 7733.11 | 7719.38 | 7743.87 | 7753.87 | 7713.87 | 7728.87 | 158499 | 16143 | call_wall -0.87 |
| 11:30:46 | gex_full | 7733.16 | 7719.38 | 7743.87 | 7913.87 | 7713.87 | 7513.87 | 159729 | 4894 | call_wall -0.87 |
| 11:31:47 | gex_zero | 7734.36 | 7719.7 | 7743.87 | 7753.87 | 7713.87 | 7728.87 | 169129 | 16906 | call_wall -0.87 |
| 11:31:48 | gex_full | 7734.36 | 7719.7 | 7743.87 | 7913.87 | 7713.87 | 7513.87 | 174513 | 50744 | call_wall -0.87 |
| 11:32:49 | gex_zero | 7734.97 | 7720.48 | 7743.87 | 7753.87 | 7713.87 | 7728.87 | 164168 | 16616 | call_wall -0.87 |
| 11:32:50 | gex_full | 7734.97 | 7720.07 | 7743.87 | 7813.87 | 7713.87 | 7513.87 | 169794 | 50958 | call_wall -0.87 |
| 11:33:51 | gex_zero | 7736.31 | 7720.07 | 7743.87 | 7753.87 | 7713.87 | 7728.87 | 186973 | 18108 | call_wall -0.87 |
| 11:33:52 | gex_full | 7736.27 | 7719.7 | 7743.87 | 7813.87 | 7713.87 | 7513.87 | 194384 | 53167 | call_wall -0.87 |
| 11:34:53 | gex_zero | 7733.95 | 7719.7 | 7743.87 | 7753.87 | 7713.87 | 7728.87 | 165801 | 16569 | call_wall -0.87 |
| 11:34:54 | gex_full | 7733.95 | 7719.7 | 7743.87 | 7913.87 | 7713.87 | 7513.87 | 171328 | 49443 | call_wall -0.87 |
| 11:35:55 | gex_zero | 7732.88 | 7719.7 | 7743.87 | 7753.87 | 7713.87 | 7728.87 | 157255 | 15922 | call_wall -0.87 |
| 11:35:56 | gex_full | 7733.15 | 7720.07 | 7743.87 | 7913.87 | 7713.87 | 7513.87 | 15627 | 48235 | call_wall -0.87 |
| 11:36:57 | gex_zero | 7732.25 | 7720.07 | 7743.87 | 7753.87 | 7713.87 | 7728.87 | 152243 | 1572 | call_wall -0.87 |
| 11:36:58 | gex_full | 7732.25 | 7719.7 | 7743.87 | 7913.87 | 7713.87 | 7513.87 | 157555 | 4813 | call_wall -0.87 |
| 11:37:59 | gex_zero | 7731.76 | 7720.48 | 7743.87 | 7753.87 | 7713.87 | 7728.87 | 14162 | 15138 | call_wall -0.87 |
| 11:37:59 | gex_full | 7731.7 | 7720.48 | 7743.87 | 7913.87 | 7713.87 | 7513.87 | 14218 | 47095 | call_wall -0.87 |
| 11:39:02 | gex_zero | 7731.62 | 7720.48 | 7743.87 | 7753.87 | 7713.87 | 7728.87 | 143613 | 1524 | call_wall -0.87 |
| 11:39:03 | gex_full | 7731.62 | 7720.48 | 7743.87 | 7913.87 | 7713.87 | 7513.87 | 148728 | 47296 | call_wall -0.87 |
| 11:40:05 | gex_zero | 7731.08 | 7720.07 | 7743.87 | 7753.87 | 7713.87 | 7728.87 | 144967 | 15258 | call_wall -0.87 |
| 11:40:05 | gex_full | 7731.08 | 7719.7 | 7743.87 | 7913.87 | 7713.87 | 7513.87 | 14986 | 47042 | call_wall -0.87 |
| 11:41:07 | gex_zero | 7732.26 | 7720.48 | 7743.87 | 7753.87 | 7713.87 | 7728.87 | 15033 | 1556 | call_wall -0.87 |
| 11:41:07 | gex_full | 7732.26 | 7720.48 | 7743.87 | 7913.87 | 7713.87 | 7513.87 | 155096 | 47406 | call_wall -0.87 |
| 11:42:08 | gex_zero | 7734.43 | 7720.48 | 7743.87 | 7753.87 | 7713.87 | 7728.87 | 178689 | 17083 | call_wall -0.87 |
| 11:42:09 | gex_full | 7734.43 | 7720.48 | 7743.87 | 7813.87 | 7713.87 | 7513.87 | 184129 | 50761 | call_wall -0.87 |
| 11:43:10 | gex_zero | 7731.73 | 7720.07 | 7743.87 | 7753.87 | 7713.87 | 7728.87 | 157264 | 15694 | call_wall -0.87 |
| 11:43:11 | gex_full | 7731.43 | 7720.07 | 7743.87 | 7813.87 | 7713.87 | 7513.87 | 157256 | 47834 | call_wall -0.87 |
| 11:44:12 | gex_zero | 7728.52 | 7721.82 | 7743.87 | 7753.87 | 7713.87 | 7728.87 | 101827 | 12896 | call_wall -0.87 |
| 11:44:13 | gex_full | 7728.7 | 7721.37 | 7743.87 | 7813.87 | 7713.87 | 7513.87 | 108075 | 44101 | call_wall -0.87 |

Kahn/LL events near 7740-7743:

| ET | Event | Action/Kind | Side | Price/Range | Policy/Reason |
|---:|---|---|---|---|---|
| 10:35:00 | policy | SuppressAdd | None | 7725.38 | no_add_zone/inside_no_add_zone |
| 10:35:05 | policy | SuppressAdd | None | 7726.12 | no_add_zone/inside_no_add_zone |
| 10:35:10 | policy | SuppressAdd | None | 7726.12 | no_add_zone/inside_no_add_zone |
| 10:35:14 | ll | RailHeld | Demand | mid 7726.5; 7723.5-7724 | - |
| 10:35:15 | policy | SuppressAdd | None | 7726.62 | no_add_zone/inside_no_add_zone |
| 10:35:20 | policy | SuppressAdd | None | 7725.62 | no_add_zone/inside_no_add_zone |
| 10:35:25 | ll | CandidateDisplacementStarted | Demand | mid 7727; 7724.75-7725 | Favor |
| 10:35:25 | ll | RailTested | Supply | mid 7727; 7728-7729.75 | - |
| 10:35:25 | policy | SuppressAdd | Supply | 7728-7729.75 | no_add_zone/inside_no_add_zone |
| 10:35:31 | policy | SuppressAdd | None | 7727.12 | no_add_zone/inside_no_add_zone |
| 10:35:36 | ll | RailOwned | Demand | mid 7727.5; 7724.75-7725 | OWNED |
| 10:35:36 | policy | SuppressAdd | Demand | 7724.75-7725 | no_add_zone/inside_no_add_zone |
| 10:35:41 | policy | SuppressAdd | None | 7727.88 | no_add_zone/inside_no_add_zone |
| 10:35:46 | policy | SuppressAdd | None | 7728.38 | no_add_zone/inside_no_add_zone |
| 10:35:51 | policy | SuppressAdd | None | 7728.62 | no_add_zone/inside_no_add_zone |
| 10:35:56 | policy | SuppressAdd | None | 7728.88 | no_add_zone/inside_no_add_zone |
| 10:36:02 | policy | SuppressAdd | None | 7728.88 | no_add_zone/inside_no_add_zone |
| 10:36:06 | ll | RailFailed | Supply | mid 7728.75; 7726.5-7727.5 | time |
| 10:36:06 | ll | GreyUpdated | Demand | mid 7728.75; 7707.75-7727.5 | NoOwner |
| 10:36:06 | ll | GreyUpdated | Demand | mid 7728.75; 7707.75-7727.5 | Contested |
| 10:36:07 | policy | SuppressAdd | None | 7728.88 | no_add_zone/inside_no_add_zone |
| 10:36:12 | policy | SuppressAdd | None | 7729.12 | no_add_zone/inside_no_add_zone |
| 10:36:17 | policy | SuppressAdd | None | 7729.12 | no_add_zone/inside_no_add_zone |
| 10:36:22 | ll | CandidateFormed | Demand | mid 7729; 7728.5-7729 | - |
| 10:36:22 | policy | SuppressAdd | None | 7729.12 | no_add_zone/inside_no_add_zone |
| 10:36:28 | policy | SuppressAdd | None | 7728.88 | no_add_zone/inside_no_add_zone |
| 10:36:33 | policy | SuppressAdd | None | 7728.62 | no_add_zone/inside_no_add_zone |
| 10:36:38 | policy | SuppressAdd | None | 7728.38 | no_add_zone/inside_no_add_zone |
| 10:36:43 | policy | SuppressAdd | None | 7728.88 | no_add_zone/inside_no_add_zone |
| 10:36:48 | policy | SuppressAdd | None | 7728.88 | no_add_zone/inside_no_add_zone |
| 10:36:50 | ll | CandidateDisplacementStarted | Supply | mid 7729.5; 7723.75-7727.5 | Adverse |
| 10:36:51 | ll | CandidateDisplacementReset | Supply | mid 7729.25; 7723.75-7727.5 | inside_threshold |
| 10:36:58 | ll | CandidateDisplacementStarted | Supply | mid 7729.5; 7723.75-7727.5 | Adverse |
| 10:37:08 | ll | RailOwned | Demand | mid 7730.5; 7723.75-7727.5 | CONSUMED |
| 10:37:19 | ll | CandidateDisplacementStarted | Demand | mid 7731.5; 7728.25-7729.5 | Favor |
| 10:37:20 | ll | CandidateDisplacementReset | Demand | mid 7731.25; 7728.25-7729.5 | inside_threshold |
| 10:37:29 | ll | RailFailed | Supply | mid 7730.5; 7728-7729.75 | time |
| 10:37:29 | ll | GreyUpdated | Demand | mid 7730.5; 7707.75-7729.75 | NoOwner |
| 10:37:29 | ll | GreyUpdated | Demand | mid 7730.5; 7707.75-7729.75 | Contested |
| 10:37:38 | ll | CandidateFormed | Supply | mid 7730.75; 7730.75-7730.75 | - |
| 10:38:31 | ll | CandidateDisplacementStarted | Supply | mid 7728.75; 7730.75-7730.75 | Favor |
| 10:38:32 | ll | RailTested | Demand | mid 7728.5; 7723.75-7727.5 | - |
| 10:38:42 | ll | RailOwned | Supply | mid 7728.75; 7730.75-7730.75 | OWNED |
| 10:38:56 | ll | CandidateFormed | Supply | mid 7728; 7727.75-7728.25 | - |
| 10:39:28 | ll | CandidateDisplacementStarted | Demand | mid 7726.25; 7728.25-7729.5 | Adverse |
| 10:39:29 | ll | CandidateDisplacementReset | Demand | mid 7726.5; 7728.25-7729.5 | inside_threshold |
| 10:39:33 | ll | CandidateDisplacementStarted | Demand | mid 7726; 7728.25-7729.5 | Adverse |
| 10:39:33 | ll | RailTested | Demand | mid 7726; 7724.75-7725 | - |
| 10:39:35 | ll | CandidateDisplacementReset | Demand | mid 7726.5; 7728.25-7729.5 | inside_threshold |
| 10:39:41 | ll | CandidateDisplacementStarted | Demand | mid 7725.75; 7728.25-7729.5 | Adverse |
| 10:39:41 | ll | CandidateDisplacementStarted | Supply | mid 7725.75; 7727.75-7728.25 | Favor |
| 10:39:51 | ll | RailOwned | Supply | mid 7725; 7728.25-7729.5 | CONSUMED |
| 10:39:51 | ll | RailOwned | Supply | mid 7725; 7727.75-7728.25 | OWNED |
| 10:39:51 | ll | RailTested | Demand | mid 7725; 7723.5-7724 | - |
| 10:40:23 | ll | CandidateFormed | Supply | mid 7726; 7725.75-7726.5 | - |
| 10:40:27 | ll | RailHeld | Demand | mid 7726.5; 7723.5-7724 | - |
| 10:40:29 | ll | RailTested | Supply | mid 7726.75; 7727.75-7728.25 | - |
| 10:41:31 | ll | RailTested | Supply | mid 7727.25; 7728.25-7729.5 | - |
| 10:41:48 | ll | RailHeld | Supply | mid 7725.75; 7728.25-7729.5 | - |
| 10:41:49 | ll | RailHeld | Supply | mid 7725.25; 7727.75-7728.25 | - |
| 10:42:02 | ll | RailTested | Supply | mid 7726.75; 7727.75-7728.25 | - |
| 10:42:05 | ll | RailTested | Supply | mid 7727.25; 7728.25-7729.5 | - |
| 10:42:14 | ll | RailHeld | Demand | mid 7727.5; 7724.75-7725 | - |
| 10:42:25 | ll | CandidateFormed | Supply | mid 7727.75; 7727.5-7727.75 | - |
| 10:44:12 | ll | RailTested | Demand | mid 7726; 7724.75-7725 | - |
| 10:44:16 | ll | RailHeld | Supply | mid 7725.75; 7728.25-7729.5 | - |
| 10:44:17 | ll | CandidateFormed | Demand | mid 7725.75; 7725.75-7725.75 | - |
| 10:44:41 | ll | RailTested | Supply | mid 7727.25; 7728.25-7729.5 | - |
| 10:44:42 | ll | CandidateDisplacementStarted | Demand | mid 7727.75; 7725.75-7725.75 | Favor |
| 10:44:42 | ll | RailHeld | Demand | mid 7727.75; 7724.75-7725 | - |
| 10:44:46 | ll | CandidateDisplacementReset | Demand | mid 7727.25; 7725.75-7725.75 | inside_threshold |
| 10:44:49 | ll | CandidateDisplacementStarted | Demand | mid 7727.75; 7725.75-7725.75 | Favor |
| 10:44:50 | ll | CandidateDisplacementReset | Demand | mid 7727.25; 7725.75-7725.75 | inside_threshold |
| 10:45:09 | ll | RailTested | Demand | mid 7726; 7724.75-7725 | - |
| 10:45:58 | ll | CandidateDisplacementStarted | Demand | mid 7727.75; 7725.75-7725.75 | Favor |
| 10:45:58 | ll | RailHeld | Demand | mid 7727.75; 7724.75-7725 | - |
| 10:46:08 | ll | RailOwned | Demand | mid 7728.75; 7725.75-7725.75 | OWNED |
| 10:46:34 | ll | CandidateFormed | Demand | mid 7728; 7727.75-7728 | - |
| 10:47:17 | ll | RailTested | Demand | mid 7726.25; 7725.75-7725.75 | - |
| 10:47:19 | ll | CandidateDisplacementStarted | Demand | mid 7725.75; 7727.75-7728 | Adverse |
| 10:47:19 | ll | RailTested | Demand | mid 7725.75; 7724.75-7725 | - |
| 10:47:19 | ll | RailHeld | Supply | mid 7725.75; 7728.25-7729.5 | - |
| 10:47:22 | ll | RailHeld | Supply | mid 7725.25; 7727.75-7728.25 | - |
| 10:47:29 | ll | RailOwned | Supply | mid 7725; 7727.75-7728 | CONSUMED |
| 10:47:29 | ll | RailTested | Demand | mid 7725; 7723.5-7724 | - |
| 10:47:36 | ll | RailHeld | Demand | mid 7726.75; 7723.5-7724 | - |
| 10:47:36 | ll | RailTested | Supply | mid 7726.75; 7727.75-7728.25 | - |
| 10:47:36 | ll | RailTested | Supply | mid 7726.75; 7727.75-7728 | - |
| 10:48:26 | ll | RailTested | Supply | mid 7727.25; 7728.25-7729.5 | - |
| 10:48:27 | ll | RailHeld | Demand | mid 7727.5; 7724.75-7725 | - |
| 10:48:39 | ll | RailHeld | Demand | mid 7728.25; 7725.75-7725.75 | - |
| 10:48:51 | ll | RailTested | Supply | mid 7729.75; 7730.75-7730.75 | - |
| 10:48:52 | ll | RailHeld | Demand | mid 7730; 7723.75-7727.5 | - |
| 10:49:00 | ll | CandidateFormed | Demand | mid 7730.5; 7730.25-7730.5 | - |
| 10:49:03 | ll | RailFailed | Supply | mid 7730.25; 7727.75-7728 | time |
| 10:49:03 | ll | GreyUpdated | Demand | mid 7730.25; 7707.75-7729.75 | NoOwner |
| 10:49:03 | ll | GreyUpdated | Demand | mid 7730.25; 7707.75-7729.75 | Contested |
| 10:49:04 | ll | RailFailed | Supply | mid 7730.25; 7727.75-7728.25 | time |
| 10:49:04 | ll | GreyUpdated | Demand | mid 7730.25; 7707.75-7729.75 | NoOwner |
| 10:49:04 | ll | GreyUpdated | Demand | mid 7730.25; 7707.75-7729.75 | Contested |
| 10:49:17 | ll | RailFailed | Supply | mid 7731.5; 7728.25-7729.5 | time |
| 10:49:17 | ll | GreyUpdated | Demand | mid 7731.5; 7707.75-7729.75 | NoOwner |
| 10:49:17 | ll | GreyUpdated | Demand | mid 7731.5; 7707.75-7729.75 | Contested |
| 10:49:18 | ll | CandidateFormed | Supply | mid 7731.75; 7731.25-7731.75 | - |
| 10:49:31 | ll | CandidateDisplacementStarted | Demand | mid 7732.5; 7730.25-7730.5 | Favor |
| 10:49:32 | ll | FailureInvalidated | Supply | mid 7733; 7728-7730.75 | - |
| 10:49:33 | ll | CandidateDisplacementStarted | Supply | mid 7733.75; 7731.25-7731.75 | Adverse |
| 10:49:34 | ll | CandidateDisplacementReset | Supply | mid 7733.25; 7731.25-7731.75 | inside_threshold |
| 10:49:39 | ll | CandidateDisplacementStarted | Supply | mid 7733.75; 7731.25-7731.75 | Adverse |
| 10:49:40 | ll | CandidateDisplacementReset | Supply | mid 7733.5; 7731.25-7731.75 | inside_threshold |
| 10:49:41 | ll | CandidateFormed | Demand | mid 7733.75; 7733.75-7733.75 | - |
| 10:49:41 | ll | CandidateDisplacementStarted | Supply | mid 7733.75; 7731.25-7731.75 | Adverse |
| 10:49:42 | ll | RailOwned | Demand | mid 7733.75; 7730.25-7730.5 | OWNED |
| 10:49:47 | ll | RailFailed | Supply | mid 7733.75; 7730.75-7730.75 | time |
| 10:49:47 | ll | GreyUpdated | Demand | mid 7733.75; 7707.75-7730.75 | NoOwner |
| 10:49:47 | ll | GreyUpdated | Demand | mid 7733.75; 7707.75-7730.75 | Contested |
| 10:49:51 | ll | RailOwned | Demand | mid 7734.25; 7731.25-7731.75 | CONSUMED |
| 10:50:03 | ll | RailTested | Demand | mid 7732.75; 7731.25-7731.75 | - |
| 10:50:39 | ll | RailHeld | Demand | mid 7734.25; 7731.25-7731.75 | - |
| 10:50:47 | ll | CandidateFormed | Supply | mid 7733.75; 7733-7734.25 | - |
| 10:51:07 | ll | RailTested | Demand | mid 7732.5; 7731.25-7731.75 | - |
| 10:51:34 | ll | CandidateFormed | Demand | mid 7732.25; 7732.25-7732.5 | - |
| 10:52:13 | ll | CandidateDisplacementStarted | Demand | mid 7731.75; 7733.75-7733.75 | Adverse |
| 10:52:16 | ll | CandidateDisplacementReset | Demand | mid 7732; 7733.75-7733.75 | inside_threshold |
| 10:52:32 | ll | RailHeld | Demand | mid 7734.25; 7731.25-7731.75 | - |
| 10:52:38 | ll | CandidateDisplacementStarted | Demand | mid 7734.75; 7731.75-7732.5 | Favor |
| 10:52:46 | ll | CandidateDisplacementStarted | Demand | mid 7735.75; 7733.75-7733.75 | Favor |
| 10:52:47 | ll | CandidateDisplacementReset | Demand | mid 7735.5; 7733.75-7733.75 | inside_threshold |
| 10:52:48 | ll | RailOwned | Demand | mid 7735.5; 7731.75-7732.5 | OWNED |
| 10:53:19 | ll | RailTested | Demand | mid 7733.5; 7731.75-7732.5 | - |
| 10:53:27 | ll | CandidateFormed | Demand | mid 7733; 7733-7733.25 | - |
| 10:53:28 | ll | RailTested | Demand | mid 7732.5; 7731.25-7731.75 | - |
| 10:53:41 | ll | CandidateDisplacementStarted | Demand | mid 7731.75; 7733.75-7733.75 | Adverse |
| 10:53:42 | ll | RailTested | Demand | mid 7731.5; 7730.25-7730.5 | - |
| 10:53:47 | ll | CandidateDisplacementStarted | Supply | mid 7730.5; 7732.5-7734.75 | Favor |
| 10:53:49 | ll | CandidateDisplacementStarted | Demand | mid 7730.25; 7732.25-7733.25 | Adverse |
| 10:53:50 | ll | CandidateDisplacementReset | Supply | mid 7730.75; 7732.5-7734.75 | inside_threshold |
| 10:53:50 | ll | CandidateDisplacementReset | Demand | mid 7730.75; 7732.25-7733.25 | inside_threshold |
| 10:54:51 | ll | RailHeld | Demand | mid 7733; 7730.25-7730.5 | - |
| 10:55:31 | ll | RailTested | Demand | mid 7731.5; 7730.25-7730.5 | - |
| 10:55:35 | ll | CandidateFormed | Demand | mid 7730.25; 7730.25-7731 | - |
| 10:55:38 | ll | CandidateDisplacementStarted | Demand | mid 7730; 7732-7733.25 | Adverse |
| 10:55:39 | ll | CandidateDisplacementReset | Demand | mid 7730.5; 7732-7733.25 | inside_threshold |
| 10:55:42 | ll | CandidateDisplacementStarted | Demand | mid 7730; 7732-7733.25 | Adverse |
| 10:55:43 | ll | CandidateFormed | Supply | mid 7729.75; 7729.75-7730.5 | - |
| 10:55:52 | ll | RailOwned | Supply | mid 7729.75; 7732-7733.25 | CONSUMED |
| 10:55:52 | ll | RailFailed | Demand | mid 7729.75; 7731.75-7732.5 | time |
| 10:55:52 | ll | GreyUpdated | Demand | mid 7729.75; 7707.75-7732.5 | NoOwner |
| 10:55:52 | ll | GreyUpdated | Demand | mid 7729.75; 7707.75-7732.5 | Contested |
| 10:55:54 | ll | RailFailed | Demand | mid 7729.5; 7731.25-7731.75 | time |
| 10:55:54 | ll | GreyUpdated | Demand | mid 7729.5; 7707.75-7732.5 | NoOwner |
| 10:55:54 | ll | GreyUpdated | Demand | mid 7729.5; 7707.75-7732.5 | Contested |
| 10:55:56 | ll | CandidateDisplacementStarted | Supply | mid 7729; 7731-7734.75 | Favor |
| 10:55:58 | ll | CandidateDisplacementReset | Supply | mid 7729.5; 7731-7734.75 | inside_threshold |
| 10:56:28 | ll | RailTested | Supply | mid 7731; 7732-7733.25 | - |
| 10:56:52 | ll | RailHeld | Supply | mid 7729.5; 7732-7733.25 | - |
| 10:57:19 | ll | RailTested | Supply | mid 7731.25; 7732-7733.25 | - |
| 10:57:27 | ll | CandidateDisplacementStarted | Supply | mid 7732.5; 7729.5-7730.5 | Adverse |
| 10:57:28 | ll | CandidateDisplacementReset | Supply | mid 7732.25; 7729.5-7730.5 | inside_threshold |
| 10:58:40 | ll | CandidateDisplacementStarted | Supply | mid 7732.5; 7729.5-7730.5 | Adverse |
| 10:58:46 | ll | CandidateDisplacementStarted | Demand | mid 7733; 7729.25-7731 | Favor |
| 10:58:46 | ll | RailHeld | Demand | mid 7733; 7730.25-7730.5 | - |
| 10:58:47 | ll | CandidateDisplacementReset | Demand | mid 7732.75; 7729.25-7731 | inside_threshold |
| 10:58:48 | ll | CandidateDisplacementStarted | Demand | mid 7733; 7729.25-7731 | Favor |
| 10:58:51 | ll | RailOwned | Demand | mid 7733; 7729.5-7730.5 | CONSUMED |
| 10:58:53 | ll | CandidateDisplacementReset | Demand | mid 7732.75; 7729.25-7731 | inside_threshold |
| 10:58:54 | ll | CandidateDisplacementStarted | Demand | mid 7733; 7729.25-7731 | Favor |
| 10:59:05 | ll | RailOwned | Demand | mid 7734.25; 7729.25-7731 | OWNED |
| 10:59:24 | ll | RailFailed | Supply | mid 7735; 7732-7733.25 | time |
| 10:59:24 | ll | GreyUpdated | Demand | mid 7735; 7707.75-7733.25 | NoOwner |
| 10:59:24 | ll | GreyUpdated | Demand | mid 7735; 7707.75-7733.25 | Contested |
| 10:59:33 | ll | CandidateFormed | Supply | mid 7734.25; 7734.25-7734.5 | - |
| 11:00:05 | ll | CandidateFormed | Demand | mid 7734.5; 7734.5-7734.5 | - |
| 11:00:35 | ll | CandidateFormed | Supply | mid 7736; 7735.75-7736 | - |
| 11:00:52 | ll | CandidateDisplacementStarted | Supply | mid 7736.5; 7734.25-7734.5 | Adverse |
| 11:00:52 | ll | CandidateDisplacementStarted | Demand | mid 7736.5; 7734.25-7734.5 | Favor |
| 11:01:01 | ll | CandidateDisplacementReset | Supply | mid 7736.25; 7734.25-7734.5 | inside_threshold |
| 11:01:01 | ll | CandidateDisplacementReset | Demand | mid 7736.25; 7734.25-7734.5 | inside_threshold |
| 11:01:03 | ll | CandidateDisplacementStarted | Supply | mid 7736.5; 7734.25-7734.5 | Adverse |
| 11:01:03 | ll | CandidateDisplacementStarted | Demand | mid 7736.5; 7734.25-7734.5 | Favor |
| 11:01:04 | ll | CandidateDisplacementReset | Supply | mid 7736.25; 7734.25-7734.5 | inside_threshold |
| 11:01:04 | ll | CandidateDisplacementReset | Demand | mid 7736.25; 7734.25-7734.5 | inside_threshold |
| 11:01:11 | ll | CandidateDisplacementStarted | Supply | mid 7736.5; 7734.25-7734.5 | Adverse |
| 11:01:11 | ll | CandidateDisplacementStarted | Demand | mid 7736.5; 7734.25-7734.5 | Favor |
| 11:01:12 | ll | CandidateDisplacementReset | Supply | mid 7736.25; 7734.25-7734.5 | inside_threshold |
| 11:01:12 | ll | CandidateDisplacementReset | Demand | mid 7736.25; 7734.25-7734.5 | inside_threshold |
| 11:01:21 | ll | CandidateDisplacementStarted | Supply | mid 7736.5; 7734.25-7734.5 | Adverse |
| 11:01:21 | ll | CandidateDisplacementStarted | Demand | mid 7736.5; 7734.25-7734.5 | Favor |
| 11:01:32 | ll | RailOwned | Demand | mid 7736.75; 7734.25-7734.5 | CONSUMED |
| 11:01:32 | ll | RailOwned | Demand | mid 7736.75; 7734.25-7734.5 | OWNED |
| 11:03:24 | ll | CandidateFormed | Demand | mid 7735.5; 7735.5-7736.25 | - |
| 11:03:24 | ll | RailTested | Demand | mid 7735.5; 7734.25-7734.5 | - |
| 11:03:24 | ll | RailTested | Demand | mid 7735.5; 7734.25-7734.5 | - |
| 11:03:58 | ll | CandidateDisplacementStarted | Supply | mid 7733.75; 7735.75-7737.75 | Favor |
| 11:03:59 | ll | CandidateDisplacementReset | Supply | mid 7734; 7735.75-7737.75 | inside_threshold |
| 11:04:26 | ll | RailHeld | Demand | mid 7737; 7734.25-7734.5 | - |
| 11:04:26 | ll | RailHeld | Demand | mid 7737; 7734.25-7734.5 | - |
| 11:05:08 | ll | CandidateDisplacementStarted | Demand | mid 7738.25; 7734.25-7736.25 | Favor |
| 11:05:14 | ll | CandidateDisplacementReset | Demand | mid 7738; 7734.25-7736.25 | inside_threshold |
| 11:05:32 | ll | CandidateFormed | Demand | mid 7737.25; 7737.25-7738 | - |
| 11:05:36 | ll | CandidateDisplacementStarted | Demand | mid 7738.25; 7734.25-7736.25 | Favor |
| 11:05:37 | ll | CandidateDisplacementReset | Demand | mid 7737.75; 7734.25-7736.25 | inside_threshold |
| 11:07:18 | ll | CandidateFormed | Supply | mid 7736.5; 7736.25-7736.5 | - |
| 11:07:35 | ll | RailTested | Demand | mid 7735.5; 7734.25-7734.5 | - |
| 11:07:35 | ll | RailTested | Demand | mid 7735.5; 7734.25-7734.5 | - |
| 11:09:02 | ll | CandidateFormed | Supply | mid 7736.25; 7736-7736.25 | - |
| 11:09:56 | ll | RailHeld | Demand | mid 7737.25; 7734.25-7734.5 | - |
| 11:09:56 | ll | RailHeld | Demand | mid 7737.25; 7734.25-7734.5 | - |
| 11:12:57 | ll | CandidateFormed | Demand | mid 7736.75; 7736.75-7737.25 | - |
| 11:14:29 | ll | CandidateDisplacementStarted | Demand | mid 7739.25; 7736.75-7737.25 | Favor |
| 11:14:39 | ll | RailOwned | Demand | mid 7739.75; 7736.75-7737.25 | OWNED |
| 11:14:54 | ll | CandidateFormed | Demand | mid 7739.75; 7739.75-7740 | - |
| 11:15:33 | ll | CandidateFormed | Demand | mid 7741.5; 7741-7741.5 | - |
| 11:15:38 | ll | CandidateDisplacementStarted | Supply | mid 7741.75; 7736-7739.75 | Adverse |
| 11:15:39 | ll | CandidateDisplacementStarted | Demand | mid 7742; 7739.75-7740 | Favor |
| 11:15:40 | ll | CandidateDisplacementReset | Demand | mid 7741.75; 7739.75-7740 | inside_threshold |
| 11:15:42 | ll | CandidateDisplacementReset | Supply | mid 7741.5; 7736-7739.75 | inside_threshold |
| 11:15:47 | ll | CandidateDisplacementStarted | Supply | mid 7741.75; 7736-7739.75 | Adverse |
| 11:15:48 | ll | CandidateDisplacementReset | Supply | mid 7741.5; 7736-7739.75 | inside_threshold |
| 11:16:03 | ll | CandidateDisplacementStarted | Supply | mid 7741.75; 7736-7739.75 | Adverse |
| 11:16:08 | ll | CandidateDisplacementStarted | Demand | mid 7742.25; 7739.75-7740 | Favor |
| 11:16:14 | ll | RailOwned | Demand | mid 7742.25; 7736-7739.75 | CONSUMED |
| 11:16:17 | ll | CandidateDisplacementReset | Demand | mid 7741.75; 7739.75-7740 | inside_threshold |
| 11:16:19 | ll | CandidateDisplacementStarted | Demand | mid 7742; 7739.75-7740 | Favor |
| 11:16:30 | ll | CandidateDisplacementReset | Demand | mid 7741.75; 7739.75-7740 | inside_threshold |
| 11:16:32 | ll | CandidateDisplacementStarted | Demand | mid 7742; 7739.75-7740 | Favor |
| 11:16:34 | ll | CandidateDisplacementReset | Demand | mid 7741.75; 7739.75-7740 | inside_threshold |
| 11:16:50 | ll | CandidateDisplacementStarted | Demand | mid 7742; 7739.75-7740 | Favor |
| 11:16:52 | ll | CandidateDisplacementReset | Demand | mid 7741.75; 7739.75-7740 | inside_threshold |
| 11:16:59 | ll | CandidateDisplacementStarted | Demand | mid 7742; 7739.75-7740 | Favor |
| 11:17:09 | ll | RailOwned | Demand | mid 7742.25; 7739.75-7740 | OWNED |
| 11:17:23 | ll | CandidateFormed | Supply | mid 7742; 7742-7742.25 | - |
| 11:18:21 | ll | RailTested | Demand | mid 7741; 7739.75-7740 | - |
| 11:18:59 | ll | RailHeld | Demand | mid 7742.5; 7739.75-7740 | - |
| 11:19:21 | ll | RailTested | Demand | mid 7741; 7739.75-7740 | - |
| 11:19:29 | ll | RailTested | Demand | mid 7740.75; 7736-7739.75 | - |
| 11:20:14 | ll | CandidateFormed | Supply | mid 7742; 7741.5-7742.5 | - |
| 11:20:15 | ll | RailHeld | Demand | mid 7742.25; 7736-7739.75 | - |
| 11:20:50 | ll | RailTested | Demand | mid 7740.75; 7736-7739.75 | - |
| 11:21:22 | ll | CandidateFormed | Demand | mid 7740.5; 7740.5-7740.5 | - |
| 11:21:49 | ll | CandidateDisplacementStarted | Supply | mid 7739.5; 7741.5-7742.5 | Favor |
| 11:21:50 | ll | CandidateDisplacementReset | Supply | mid 7739.75; 7741.5-7742.5 | inside_threshold |
| 11:21:53 | ll | CandidateDisplacementStarted | Supply | mid 7739.5; 7741.5-7742.5 | Favor |
| 11:21:55 | ll | CandidateDisplacementReset | Supply | mid 7739.75; 7741.5-7742.5 | inside_threshold |
| 11:22:26 | ll | CandidateDisplacementStarted | Supply | mid 7739.5; 7741.5-7742.5 | Favor |
| 11:22:27 | ll | CandidateDisplacementReset | Supply | mid 7739.75; 7741.5-7742.5 | inside_threshold |
| 11:23:10 | ll | CandidateDisplacementStarted | Supply | mid 7739.25; 7741.5-7742.5 | Favor |
| 11:24:40 | ll | CandidateFormed | Supply | mid 7739.25; 7739.25-7739.5 | - |
| 11:25:14 | ll | RailTested | Demand | mid 7738.25; 7736.75-7737.25 | - |
| 11:25:20 | ll | CandidateFormed | Demand | mid 7737.75; 7737.75-7738.25 | - |
| 11:25:21 | ll | CandidateDisplacementStarted | Supply | mid 7737.25; 7739.25-7739.5 | Favor |
| 11:25:22 | ll | CandidateDisplacementReset | Supply | mid 7737.5; 7739.25-7739.5 | inside_threshold |
| 11:25:23 | ll | CandidateDisplacementStarted | Supply | mid 7737.25; 7739.25-7739.5 | Favor |
| 11:25:24 | ll | CandidateDisplacementStarted | Demand | mid 7737; 7739-7740.5 | Adverse |
| 11:25:28 | ll | CandidateDisplacementReset | Demand | mid 7737.25; 7739-7740.5 | inside_threshold |
| 11:25:29 | ll | CandidateDisplacementStarted | Demand | mid 7736.75; 7739-7740.5 | Adverse |
| 11:25:31 | ll | CandidateDisplacementReset | Demand | mid 7737.25; 7739-7740.5 | inside_threshold |
| 11:25:31 | ll | RailFailed | Demand | mid 7737.25; 7739.75-7740 | time |
| 11:25:31 | ll | GreyUpdated | Demand | mid 7737.25; 7739.75-7740 | NoOwner |
| 11:25:31 | ll | GreyUpdated | Demand | mid 7737.25; 7739.75-7740 | Contested |
| 11:25:32 | ll | CandidateDisplacementStarted | Demand | mid 7737; 7739-7740.5 | Adverse |
| 11:25:34 | ll | RailOwned | Supply | mid 7737; 7739.25-7739.5 | OWNED |
| 11:25:36 | ll | CandidateDisplacementReset | Demand | mid 7737.25; 7739-7740.5 | inside_threshold |
| 11:25:37 | ll | CandidateDisplacementStarted | Demand | mid 7737; 7739-7740.5 | Adverse |
| 11:25:38 | ll | CandidateDisplacementReset | Demand | mid 7737.25; 7739-7740.5 | inside_threshold |
| 11:25:39 | ll | CandidateDisplacementStarted | Demand | mid 7737; 7739-7740.5 | Adverse |
| 11:25:49 | ll | CandidateDisplacementReset | Demand | mid 7737.25; 7739-7740.5 | inside_threshold |
| 11:25:51 | ll | CandidateDisplacementStarted | Demand | mid 7737; 7739-7740.5 | Adverse |
| 11:25:53 | ll | CandidateDisplacementReset | Demand | mid 7737.25; 7739-7740.5 | inside_threshold |
| 11:26:06 | ll | RailTested | Supply | mid 7738.25; 7739.25-7739.5 | - |
| 11:27:53 | ll | RailHeld | Supply | mid 7736.75; 7739.25-7739.5 | - |
| 11:28:54 | ll | CandidateFormed | Supply | mid 7736.75; 7736.75-7736.75 | - |
| 11:29:17 | ll | RailTested | Demand | mid 7735.5; 7734.25-7734.5 | - |
| 11:29:17 | ll | RailTested | Demand | mid 7735.5; 7734.25-7734.5 | - |
| 11:29:33 | ll | CandidateDisplacementStarted | Demand | mid 7735; 7737-7738.25 | Adverse |
| 11:29:33 | ll | RailFailed | Demand | mid 7735; 7736.75-7737.25 | time |
| 11:29:33 | ll | GreyUpdated | Demand | mid 7735; 7736.75-7740 | NoOwner |
| 11:29:33 | ll | GreyUpdated | Demand | mid 7735; 7736.75-7740 | Contested |
| 11:29:44 | ll | RailOwned | Supply | mid 7734.25; 7737-7738.25 | CONSUMED |
| 11:29:49 | ll | RailFailed | Demand | mid 7734.25; 7736-7739.75 | time |
| 11:29:49 | ll | GreyUpdated | Demand | mid 7734.25; 7736-7740 | NoOwner |
| 11:29:49 | ll | GreyUpdated | Demand | mid 7734.25; 7736-7740 | Contested |
| 11:29:52 | ll | CandidateDisplacementStarted | Supply | mid 7733.75; 7735.75-7736.75 | Favor |
| 11:29:53 | ll | CandidateDisplacementReset | Supply | mid 7734; 7735.75-7736.75 | inside_threshold |
| 11:30:16 | ll | CandidateDisplacementStarted | Supply | mid 7733.5; 7735.75-7736.75 | Favor |
| 11:30:26 | ll | RailOwned | Supply | mid 7733; 7735.75-7736.75 | OWNED |
| 11:30:37 | ll | RailFailed | Demand | mid 7733; 7734.25-7734.5 | time |
| 11:30:37 | ll | GreyUpdated | Demand | mid 7733; 7734.25-7740 | NoOwner |
| 11:30:37 | ll | GreyUpdated | Demand | mid 7733; 7734.25-7740 | Contested |
| 11:30:37 | ll | RailFailed | Demand | mid 7733; 7734.25-7734.5 | time |
| 11:30:37 | ll | GreyUpdated | Demand | mid 7733; 7734.25-7740 | NoOwner |
| 11:30:37 | ll | GreyUpdated | Demand | mid 7733; 7734.25-7740 | Contested |
| 11:31:45 | ll | CandidateFormed | Demand | mid 7734; 7734-7734.25 | - |
| 11:32:48 | ll | RailTested | Supply | mid 7735; 7735.75-7736.75 | - |
| 11:32:55 | ll | RailTested | Supply | mid 7736; 7737-7738.25 | - |
| 11:32:57 | ll | CandidateFormed | Demand | mid 7736.25; 7735.75-7736.25 | - |
| 11:32:57 | ll | CandidateDisplacementStarted | Demand | mid 7736.25; 7734-7734.25 | Favor |
| 11:33:08 | ll | RailOwned | Demand | mid 7737.5; 7734-7734.25 | OWNED |
| 11:33:31 | ll | RailTested | Demand | mid 7735.25; 7734-7734.25 | - |
| 11:34:10 | ll | RailHeld | Supply | mid 7734.5; 7737-7738.25 | - |
| 11:34:15 | ll | CandidateDisplacementStarted | Demand | mid 7733.5; 7735.5-7736.25 | Adverse |
| 11:34:22 | ll | RailHeld | Supply | mid 7733.25; 7735.75-7736.75 | - |
| 11:34:25 | ll | CandidateFormed | Demand | mid 7732.75; 7732.75-7733.5 | - |
| 11:34:25 | ll | RailOwned | Supply | mid 7732.75; 7735.5-7736.25 | CONSUMED |
| 11:34:42 | ll | RailFailed | Demand | mid 7732.75; 7734-7734.25 | time |
| 11:34:42 | ll | GreyUpdated | Demand | mid 7732.75; 7734-7740 | NoOwner |
| 11:34:43 | ll | GreyUpdated | Demand | mid 7732.75; 7734-7740 | Contested |
| 11:35:19 | ll | RailTested | Supply | mid 7734.5; 7735.5-7736.25 | - |
| 11:35:43 | ll | RailHeld | Supply | mid 7733; 7735.5-7736.25 | - |
| 11:35:47 | ll | CandidateFormed | Supply | mid 7733; 7732.75-7733 | - |

Tick bars:

| ET | O | H | L | C | Vol | Delta | Vol pct |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 10:35:00 | 7725.5 | 7729 | 7725.5 | 7728.75 | 2759 | 491 | 71% |
| 10:36:00 | 7728.75 | 7729.75 | 7728.25 | 7729.75 | 2129 | -189 | 51% |
| 10:37:00 | 7729.75 | 7732.25 | 7729.25 | 7729.75 | 3171 | 185 | 79% |
| 10:38:00 | 7729.5 | 7730 | 7727.5 | 7728.5 | 2961 | -355 | 75% |
| 10:39:00 | 7728.5 | 7728.75 | 7725 | 7725 | 4339 | -853 | 88% |
| 10:40:00 | 7725 | 7727.25 | 7724.5 | 7726.5 | 3359 | -145 | 81% |
| 10:41:00 | 7726.25 | 7727.5 | 7725 | 7726.75 | 2553 | 19 | 66% |
| 10:42:00 | 7726.5 | 7728.25 | 7726.5 | 7728.25 | 2475 | 251 | 64% |
| 10:43:00 | 7728 | 7728.25 | 7726.5 | 7727.25 | 1999 | 59 | 48% |
| 10:44:00 | 7727.25 | 7728.25 | 7725.75 | 7727.75 | 2424 | -94 | 63% |
| 10:45:00 | 7727.5 | 7728 | 7725.75 | 7728 | 2695 | -81 | 69% |
| 10:46:00 | 7727.75 | 7729.5 | 7727.75 | 7729.25 | 2251 | 21 | 55% |
| 10:47:00 | 7729.25 | 7729.25 | 7725 | 7725.75 | 2701 | -57 | 69% |
| 10:48:00 | 7726 | 7730.75 | 7725.25 | 7730.75 | 2708 | 178 | 7% |
| 10:49:00 | 7730.75 | 7734.5 | 7730 | 7733.75 | 4997 | 981 | 92% |
| 10:50:00 | 7733.75 | 7734.75 | 7732.5 | 7733 | 5451 | -53 | 95% |
| 10:51:00 | 7733 | 7733.5 | 7732.25 | 7732.5 | 2569 | -65 | 67% |
| 10:52:00 | 7732.75 | 7736 | 7731.75 | 7734.25 | 4821 | 395 | 91% |
| 10:53:00 | 7734.25 | 7734.5 | 7730.5 | 7732.25 | 2796 | -228 | 71% |
| 10:54:00 | 7732 | 7733.5 | 7730.75 | 7732.75 | 3347 | 293 | 8% |
| 10:55:00 | 7733 | 7733.5 | 7729 | 7729.75 | 448 | -982 | 9% |
| 10:56:00 | 7729.75 | 7731.25 | 7728.75 | 7729.75 | 2569 | -159 | 67% |
| 10:57:00 | 7729.75 | 7732.5 | 7729.75 | 7731 | 2389 | 45 | 62% |
| 10:58:00 | 7731 | 7734 | 7730.5 | 7733.75 | 195 | 64 | 46% |
| 10:59:00 | 7733.75 | 7735.5 | 7733.75 | 7735.25 | 375 | -66 | 85% |
| 11:00:00 | 7735.5 | 7737 | 7734 | 7736.5 | 3746 | 62 | 84% |
| 11:01:00 | 7736.75 | 7738.25 | 7736 | 7737.5 | 2867 | -113 | 73% |
| 11:02:00 | 7737.5 | 7738 | 7736.5 | 7736.75 | 1968 | -178 | 47% |
| 11:03:00 | 7737 | 7737.25 | 7733.75 | 7734.25 | 303 | -296 | 77% |
| 11:04:00 | 7734.25 | 7738 | 7734 | 7737.75 | 2368 | 1 | 61% |
| 11:05:00 | 7738 | 7738.5 | 7737 | 7737.75 | 2015 | 27 | 49% |
| 11:06:00 | 7737.75 | 7737.75 | 7735.75 | 7735.75 | 1604 | -196 | 34% |
| 11:07:00 | 7736 | 7737 | 7735 | 7736.25 | 2288 | -12 | 57% |
| 11:08:00 | 7736 | 7736.25 | 7734.75 | 7736.25 | 1325 | -107 | 2% |
| 11:09:00 | 7736.25 | 7737.5 | 7735.25 | 7737 | 1281 | 37 | 19% |
| 11:10:00 | 7737 | 7738 | 7736.75 | 7737 | 1604 | -32 | 34% |
| 11:11:00 | 7737.25 | 7738.5 | 7737 | 7738 | 153 | 28 | 29% |
| 11:12:00 | 7738 | 7739.25 | 7736.75 | 7737 | 1903 | -29 | 44% |
| 11:13:00 | 7737.25 | 7738.25 | 7737 | 7737.75 | 1191 | -153 | 15% |
| 11:14:00 | 7737.75 | 7740.25 | 7737.75 | 7740 | 2351 | 407 | 6% |
| 11:15:00 | 7740 | 7742 | 7739.75 | 7741.75 | 3129 | 181 | 78% |
| 11:16:00 | 7741.75 | 7742.5 | 7741.25 | 7742.25 | 2411 | 143 | 63% |
| 11:17:00 | 7742.25 | 7742.75 | 7741.5 | 7742 | 2104 | -292 | 5% |
| 11:18:00 | 7741.75 | 7742.75 | 7741 | 7742.5 | 1902 | 62 | 43% |
| 11:19:00 | 7742.5 | 7742.75 | 7740.25 | 7741.25 | 1667 | -83 | 35% |
| 11:20:00 | 7741.5 | 7742.5 | 7740.75 | 7741.5 | 176 | -36 | 38% |
| 11:21:00 | 7741.25 | 7742 | 7739.5 | 7740.25 | 1963 | -149 | 46% |
| 11:22:00 | 7740 | 7741 | 7739.75 | 7740.75 | 1684 | 64 | 36% |
| 11:23:00 | 7740.75 | 7741 | 7739 | 7741 | 1972 | -12 | 47% |
| 11:24:00 | 7741 | 7741.25 | 7739 | 7739.5 | 2222 | -148 | 54% |
| 11:25:00 | 7739.75 | 7739.75 | 7736.75 | 7738.25 | 2702 | -274 | 7% |
| 11:26:00 | 7738 | 7739 | 7737.25 | 7738.25 | 1857 | 15 | 41% |
| 11:27:00 | 7738 | 7738.75 | 7736.25 | 7736.5 | 1869 | -175 | 42% |
| 11:28:00 | 7736.5 | 7737.5 | 7736.25 | 7736.5 | 1224 | -22 | 16% |
| 11:29:00 | 7736.5 | 7736.75 | 7733.75 | 7734.75 | 3234 | -46 | 8% |
| 11:30:00 | 7734.75 | 7735.25 | 7732.25 | 7734 | 4632 | -318 | 9% |
| 11:31:00 | 7734 | 7734.75 | 7733 | 7734.75 | 3435 | 321 | 82% |
| 11:32:00 | 7734.75 | 7736.75 | 7732.75 | 7736.75 | 3229 | 657 | 79% |
| 11:33:00 | 7736.75 | 7737.75 | 7735.25 | 7735.75 | 252 | 124 | 65% |
| 11:34:00 | 7735.75 | 7735.75 | 7732.25 | 7733.75 | 2835 | -127 | 72% |
| 11:35:00 | 7733.5 | 7735 | 7732.25 | 7733.25 | 2821 | 163 | 72% |
| 11:36:00 | 7733.25 | 7733.5 | 7731.5 | 7732.25 | 1866 | -146 | 42% |
| 11:37:00 | 7732.25 | 7732.5 | 7730.75 | 7731.5 | 3836 | -374 | 85% |
| 11:38:00 | 7731.25 | 7732.5 | 7730.5 | 7731.25 | 2903 | 71 | 75% |
| 11:39:00 | 7731.25 | 7731.25 | 7729.5 | 7730.5 | 3101 | -225 | 78% |
| 11:40:00 | 7730.5 | 7732 | 7729.75 | 7731.5 | 3017 | 223 | 77% |
| 11:41:00 | 7731.5 | 7735 | 7731.5 | 7735 | 3687 | 745 | 84% |
| 11:42:00 | 7735 | 7735 | 7731.75 | 7732.25 | 1948 | -208 | 46% |
| 11:43:00 | 7732.25 | 7732.25 | 7729 | 7729.25 | 3629 | -537 | 83% |
| 11:44:00 | 7729.5 | 7729.5 | 7727.25 | 7727.75 | 4637 | 81 | 9% |
| 11:45:00 | 7728 | 7728 | 7725.25 | 7726.75 | 4469 | -405 | 89% |

BubbleTape:

- No replay rows in this window.
