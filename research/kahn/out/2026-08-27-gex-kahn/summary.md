# 2026-08-27 Kahn / GexBot Join

Generated from local Kahn JSONL decision logs and `GexBotMcp/out/gexbot.sqlite`.

## Campaign Loads

| Symbol | ET | Campaign | Status | Side | Probe/Add/Max | Notes |
|---|---:|---|---|---|---:|---|
| NQ | 09:17:36 | `nq-2026-08-26-short-callwall-repair-29260-29280` | active | Short | 2/2/4 | Live NQ Kahn short from 2026-08-26 13:30 ET: first call-wall repair after PM lower break. Probe 29260-29280, base/add 2/2, max 4. Add only back at edge near original entry; no a... |
| ES | 09:17:36 | `es-2026-08-26-short-callwall-repair-7687-7695` | active | Short | 2/2/4 | Live ES Kahn short from 2026-08-26 13:30 ET: first call-wall/zero-gamma repair after PM IB-low break. Probe 7687-7695, base/add 2/2, max 4. Add only back at edge near original e... |
| ES | 09:51:50 | `es-2026-08-27-long-orr-7716-7726` | active | Long | 2/2/4 | Live 2026-08-27 ES ORR long. Probe 7716-7726, scale only above 7728, harvest 7732-7736, target 7741. Base/add 2/2, max 4, max_retry 3. GEX/location context does not replace Kahn... |
| NQ | 09:51:50 | `nq-2026-08-27-long-orr-29480-29520` | active | Long | 2/2/4 | Live 2026-08-27 NQ ORR long. Probe 29480-29520, build/scale only above 29540, target 29655-29662. Base/add 2/2, max 4, max_retry 3. Deeper repair probe, not the earlier high-pro... |
| NQ | 10:24:31 | `nq-2026-08-27-long-orr-29480-29520` | draft | Long | 2/2/4 | Live 2026-08-27 NQ ORR long. Probe 29480-29520, build/scale only above 29540, target 29655-29662. Base/add 2/2, max 4, max_retry 3. Deeper repair probe, not the earlier high-pro... |
| NQ | 10:54:16 | `nq-2026-08-27-long-postib-uppernode-29572-29612` | active | Long | 2/2/4 | Live 2026-08-27 NQ post-IB long continuation/reclaim campaign. Fresh Skurry at ~10:52 ET: RTH p profile, value 29499-29600, POC 29575.5; post-IB DD, value 29557.5-29604, POC 295... |
| NQ | 11:42:56 | `nq-2026-08-27-long-postib-uppernode-29572-29612` | active | Long | 2/2/4 | Live 2026-08-27 NQ post-IB long continuation/reclaim campaign. Fresh Skurry at ~10:52 ET: RTH p profile, value 29499-29600, POC 29575.5; post-IB DD, value 29557.5-29604, POC 295... |
| NQ | 12:27:51 | `nq-2026-08-27-long-postib-uppernode-29572-29612` | draft | Long | 2/2/4 | Live 2026-08-27 NQ post-IB long continuation/reclaim campaign. Fresh Skurry at ~10:52 ET: RTH p profile, value 29499-29600, POC 29575.5; post-IB DD, value 29557.5-29604, POC 295... |
| ES | 12:27:51 | `es-2026-08-27-long-orr-7716-7726` | active | Long | 2/2/4 | Live 2026-08-27 ES ORR long. Probe 7716-7726, scale only above 7728, harvest 7732-7736, target 7741. Base/add 2/2, max 4, max_retry 3. GEX/location context does not replace Kahn... |
| ES | 13:09:15 | `es-2026-08-27-long-lunch-break-repair-7742-7747` | draft | Long | 2/2/6 | Provisional draft only; do not dispatch until the current 5m candle closes. Live 2026-08-27 lunch break-and-repair long. Fresh Skurry/GexBot ~12:46 ET: ES broke above 7743/7744 ... |
| NQ | 13:09:45 | `nq-2026-08-27-long-lunch-break-repair-29633-29644` | draft | Long | 2/2/6 | Provisional draft only; do not dispatch until the current 5m candle closes. Live 2026-08-27 lunch break-and-repair long. Fresh Skurry/GexBot ~12:46 ET: NQ improved with strong b... |
| ES | 13:37:07 | `es-2026-08-27-short-upper-supply-vwap-7754-7756` | active | Short | 2/2/6 | Live 2026-08-27 ES-only active short directive after user-declared rejection setup. Fresh Skurry/GexBot ~13:34 ET: upper 12:30-13:30 profile is p-shaped with value 7748-7754, PO... |
| NQ | 15:06:01 | `nq-2026-08-27-short-repair-failure-29600-29620-to-29511` | active | Short | 2/2/6 | Live 2026-08-27 NQ active short directive after user-declared repair-failure setup. Fresh Skurry/GexBot ~15:01 ET: NQ still in repair while ES extended below 7728 exploration an... |
| NQ | 15:07:03 | `nq-2026-08-27-short-repair-failure-29600-29620-to-29511` | draft | Short | 2/2/6 | Live 2026-08-27 NQ active short directive after user-declared repair-failure setup. Fresh Skurry/GexBot ~15:01 ET: NQ still in repair while ES extended below 7728 exploration an... |

## Broker-Affecting Decisions

| Symbol | ET | Action | Pos | Campaign | Policy/Reason | Waypoint | Price | GEX category | Nearest GEX | Dist | Snapshot ET |
|---|---:|---:|---:|---|---|---|---:|---|---|---:|---:|
| ES | 09:54:03 | AllowProbe | 0->2 | `es-2026-08-27-long-orr-7716-7726` | trap_probe/same_side_lean_at_trap_probe | probe-7716-7726 | 7723.75 | gex_zero | oi_put_wall | -5.06 | 09:53:46 |
| ES | 09:55:45 | Flatten | 2->0 | `es-2026-08-27-long-orr-7716-7726` | build_trial/risk_anchor_failed | - | 7718 | gex_zero | zero_gamma | 5.39 | 09:54:48 |
| NQ | 10:01:16 | AllowProbe | 0->2 | `nq-2026-08-27-long-orr-29480-29520` | trap_probe/counter_claim_failed_at_trap_probe | probe-29480-29520 | 29516 | gex_zero | zero_gamma | 54.78 | 10:01:00 |
| ES | 10:01:25 | AllowProbe | 0->2 | `es-2026-08-27-long-orr-7716-7726` | trap_probe/same_side_lean_at_trap_probe | probe-7716-7726 | 7717 | gex_zero | zero_gamma | 4.7 | 10:00:59 |
| NQ | 10:07:03 | Flatten | 2->0 | `nq-2026-08-27-long-orr-29480-29520` | build_trial/risk_anchor_failed | - | 29508.5 | gex_zero | oi_call_wall | -65.12 | 10:06:10 |
| NQ | 10:07:08 | AllowProbe | 0->2 | `nq-2026-08-27-long-orr-29480-29520` | trap_probe/same_side_lean_at_trap_probe | probe-29480-29520 | 29517.25 | gex_zero | oi_call_wall | -56.37 | 10:06:10 |
| ES | 10:07:10 | Flatten | 2->0 | `es-2026-08-27-long-orr-7716-7726` | build_trial/risk_anchor_failed | - | 7713 | gex_zero | zero_gamma | 1.11 | 10:06:09 |
| ES | 10:07:53 | AllowProbe | 0->2 | `es-2026-08-27-long-orr-7716-7726` | trap_probe/same_side_lean_at_trap_probe | probe-7716-7726 | 7717.5 | gex_zero | zero_gamma | 4.51 | 10:07:11 |
| NQ | 10:14:41 | Flatten | 2->0 | `nq-2026-08-27-long-orr-29480-29520` | build_trial/risk_anchor_failed | - | 29569 | gex_zero | oi_call_wall | -4.62 | 10:14:26 |
| NQ | 10:57:18 | AllowProbe | 0->2 | `nq-2026-08-27-long-postib-uppernode-29572-29612` | trap_probe/counter_claim_failed_at_trap_probe | probe-29572-29594 | 29584.75 | gex_zero | oi_call_wall | 12.63 | 10:56:45 |
| NQ | 11:03:42 | Reduce | 2->0 | `nq-2026-08-27-long-postib-uppernode-29572-29612` | evaluate_zone/evaluate_opposite_ownership | evaluate-29608-29616 | 29595.25 | gex_zero | call_wall | -17.78 | 11:02:56 |
| NQ | 11:25:59 | AllowProbe | 0->2 | `nq-2026-08-27-long-postib-uppernode-29572-29612` | trap_probe/same_side_lean_at_trap_probe | probe-29572-29594 | 29591 | gex_zero | oi_call_wall | 16.44 | 11:25:37 |
| NQ | 11:29:34 | Flatten | 2->0 | `nq-2026-08-27-long-postib-uppernode-29572-29612` | build_trial/risk_anchor_failed | - | 29577.5 | gex_zero | oi_call_wall | 2.94 | 11:28:43 |
| ES | 13:39:03 | AllowProbe | 0->2 | `es-2026-08-27-short-upper-supply-vwap-7754-7756` | trap_probe/same_side_lean_at_trap_probe | probe-7748-7756 | 7748.75 | gex_zero | call_wall | -5.19 | 13:38:06 |
| ES | 14:31:48 | Retire | 2->0 | `es-2026-08-27-short-upper-supply-vwap-7754-7756` | target_zone/opposite_ownership_at_target | target-7728-7729-50 | 7729 | gex_zero | oi_put_wall | 0.99 | 14:30:53 |

## GEX Wall Changes

| ET | Ticker | Category | Spot | Changed Fields |
|---:|---|---|---:|---|
| 09:30:00 | ES_SPX | gex_zero | 7690.41 | zero_gamma:7684.8->0, call_wall:7689.72->0, put_wall:7679.72->0, oi_call_wall:7689.72->7714.71, oi_put_wall:7669.72->7689.71 |
| 09:31:02 | ES_SPX | gex_zero | 7720.37 | zero_gamma:0->7715.91, call_wall:0->7764.71, put_wall:0->7679.71, oi_call_wall:7714.71->7754.71, oi_put_wall:7689.71->7729.71 |
| 09:31:02 | ES_SPX | gex_full | 7720.57 | zero_gamma:0->7715.22, call_wall:0->7764.71, put_wall:0->7669.71 |
| 09:31:03 | ES_SPX | gex_one | 7720.57 | zero_gamma:0->7708.1, call_wall:0->7764.71, put_wall:0->7689.71, oi_call_wall:7739.71->7744.71, oi_put_wall:7714.71->7664.71 |
| 09:31:03 | NQ_NDX | gex_zero | 29580.59 | zero_gamma:0->29508.81, call_wall:0->29568.81, put_wall:0->29497.16, oi_call_wall:29578.81->29568.97, oi_put_wall:29344.62->29348.27 |
| 09:31:04 | NQ_NDX | gex_full | 29580.59 | zero_gamma:0->29508.81, call_wall:0->29868.81, put_wall:0->29497.16, oi_put_wall:28718.81->29168.81 |
| 09:31:04 | NQ_NDX | gex_one | 29585.17 | zero_gamma:0->29478.81, call_wall:0->29868.81, put_wall:0->29468.81 |
| 09:32:04 | ES_SPX | gex_zero | 7708.56 | call_wall:7764.71->7719.71, put_wall:7679.71->7659.71, oi_put_wall:7729.71->7649.71 |
| 09:32:05 | ES_SPX | gex_full | 7707.68 | zero_gamma:7715.22->7716.32, call_wall:7764.71->7719.71, put_wall:7669.71->7659.71 |
| 09:32:05 | ES_SPX | gex_one | 7707.68 | zero_gamma:7708.1->7709.79, call_wall:7764.71->7759.71, put_wall:7689.71->7674.71 |
| 09:32:05 | NQ_NDX | gex_zero | 29490.02 | call_wall:29568.81->29538.81, oi_call_wall:29568.97->29578.81, oi_put_wall:29348.27->29346.28 |
| 09:32:06 | NQ_NDX | gex_full | 29490.02 | zero_gamma:29508.81->29528.81, call_wall:29868.81->30068.81 |
| 09:32:06 | NQ_NDX | gex_one | 29490.02 | call_wall:29868.81->30068.81 |
| 09:33:06 | ES_SPX | gex_zero | 7711.94 | zero_gamma:7715.91->7713.1, put_wall:7659.71->7659.79 |
| 09:33:07 | ES_SPX | gex_full | 7712.7 | zero_gamma:7716.32->7712.66, put_wall:7659.71->7659.96 |
| 09:33:07 | ES_SPX | gex_one | 7712.7 | zero_gamma:7709.79->7709.96, call_wall:7759.71->7719.71 |
| 09:33:08 | NQ_NDX | gex_zero | 29505.39 | zero_gamma:29508.81->29512.91, put_wall:29497.16->29498.71, oi_put_wall:29346.28->29343.89 |
| 09:33:08 | NQ_NDX | gex_full | 29509.59 | zero_gamma:29528.81->29628.81, put_wall:29497.16->29498.71 |
| 09:34:09 | ES_SPX | gex_zero | 7709.86 | zero_gamma:7713.1->7712.21, put_wall:7659.79->7664.63 |
| 09:34:09 | ES_SPX | gex_full | 7709.86 | zero_gamma:7712.66->7712.21, put_wall:7659.96->7674.71 |
| 09:34:09 | ES_SPX | gex_one | 7709.86 | zero_gamma:7709.96->7862.21, call_wall:7719.71->7869.71 |
| 09:34:10 | NQ_NDX | gex_zero | 29491.7 | zero_gamma:29512.91->29516.41, put_wall:29498.71->29498.81, oi_put_wall:29343.89->29348.71 |
| 09:34:10 | NQ_NDX | gex_full | 29491.7 | put_wall:29498.71->29498.81 |
| 09:34:10 | NQ_NDX | gex_one | 29493.74 | zero_gamma:29478.81->29078.81, put_wall:29468.81->29068.81 |
| 09:35:11 | ES_SPX | gex_zero | 7705.82 | put_wall:7664.63->7664.71 |
| 09:35:11 | ES_SPX | gex_one | 7705.82 | zero_gamma:7862.21->7862.66 |
| 09:35:12 | NQ_NDX | gex_zero | 29461.76 | zero_gamma:29516.41->29514.71, oi_put_wall:29348.71->29344.06 |
| 09:35:12 | NQ_NDX | gex_full | 29461.76 | zero_gamma:29628.81->29514.71, call_wall:30068.81->29538.81, oi_put_wall:29168.81->29668.81 |
| 09:35:12 | NQ_NDX | gex_one | 29460.26 | call_wall:30068.81->29568.81 |
| 09:36:13 | ES_SPX | gex_zero | 7710.65 | zero_gamma:7712.21->7711.32 |
| 09:36:13 | ES_SPX | gex_full | 7710.65 | zero_gamma:7712.21->7710.91, call_wall:7719.71->7719.79 |
| 09:36:13 | ES_SPX | gex_one | 7710.65 | zero_gamma:7862.66->7705.91 |
| 09:36:13 | NQ_NDX | gex_zero | 29481.94 | oi_put_wall:29344.06->29348.27 |
| 09:36:14 | NQ_NDX | gex_full | 29481.94 | zero_gamma:29514.71->29632.05, call_wall:29538.81->29868.81, oi_put_wall:29668.81->29168.81 |
| 09:36:14 | NQ_NDX | gex_one | 29481.94 | call_wall:29568.81->30068.81 |
| 09:37:14 | ES_SPX | gex_zero | 7709.35 | zero_gamma:7711.32->7710.91, call_wall:7719.71->7719.79, oi_put_wall:7649.71->7649.63 |
| 09:37:15 | ES_SPX | gex_full | 7708.52 | call_wall:7719.79->7724.63 |
| 09:37:15 | ES_SPX | gex_one | 7708.52 | zero_gamma:7705.91->7859.71 |
| 09:37:15 | NQ_NDX | gex_zero | 29469.36 | zero_gamma:29514.71->29512.91 |
| 09:37:16 | NQ_NDX | gex_full | 29469.36 | zero_gamma:29632.05->29677.15, put_wall:29498.81->29668.81 |
| 09:37:16 | NQ_NDX | gex_one | 29469.36 | call_wall:30068.81->29868.81 |
| 09:38:16 | ES_SPX | gex_zero | 7708.32 | zero_gamma:7710.91->7711.76, call_wall:7719.79->7724.71, oi_put_wall:7649.63->7729.71 |
| 09:38:17 | ES_SPX | gex_full | 7708.32 | zero_gamma:7710.91->7711.76, call_wall:7724.63->7724.71 |
| 09:38:17 | NQ_NDX | gex_zero | 29471.45 | zero_gamma:29512.91->29448.81, put_wall:29498.81->29368.81, oi_put_wall:29348.27->29347.94 |
| 09:38:18 | NQ_NDX | gex_full | 29471.45 | call_wall:29868.81->29768.81 |
| 09:38:18 | NQ_NDX | gex_one | 29469.73 | call_wall:29868.81->29568.81 |
| 09:39:18 | ES_SPX | gex_zero | 7710.78 | call_wall:7724.71->7724.63, put_wall:7664.71->7674.79 |
| 09:39:19 | NQ_NDX | gex_zero | 29473.01 | zero_gamma:29448.81->29431.22, call_wall:29538.81->29598.81 |
| 09:39:20 | NQ_NDX | gex_full | 29473.01 | zero_gamma:29677.15->29473.01, call_wall:29768.81->29598.81, oi_put_wall:29168.81->29668.81 |
| 09:39:20 | NQ_NDX | gex_one | 29468.04 | zero_gamma:29078.81->28978.81, put_wall:29068.81->28968.81 |
| 09:40:20 | ES_SPX | gex_zero | 7716.07 | zero_gamma:7711.76->7710.54, call_wall:7724.63->7724.71, put_wall:7674.79->7674.71 |
| 09:40:21 | ES_SPX | gex_full | 7716.07 | zero_gamma:7711.76->7710.54 |
| 09:40:21 | ES_SPX | gex_one | 7716.07 | zero_gamma:7859.71->7704.2, call_wall:7869.71->7774.71 |
| 09:40:21 | NQ_NDX | gex_zero | 29515.08 | oi_put_wall:29347.94->29348.71 |
| 09:40:22 | NQ_NDX | gex_full | 29521.08 | zero_gamma:29473.01->29428.3, put_wall:29668.81->29368.81, oi_put_wall:29668.81->29168.81 |
| 09:40:22 | NQ_NDX | gex_one | 29521.08 | zero_gamma:28978.81->29078.81, call_wall:29568.81->30068.81, put_wall:28968.81->29068.81 |
| 09:41:22 | ES_SPX | gex_zero | 7719.43 | zero_gamma:7710.54->7711.32, call_wall:7724.71->7764.71, put_wall:7674.71->7704.63 |
| 09:41:23 | ES_SPX | gex_full | 7719.43 | zero_gamma:7710.54->7711.32, call_wall:7724.71->7764.71 |
| 09:41:23 | ES_SPX | gex_one | 7720.07 | zero_gamma:7704.2->7705.91 |
| 09:41:24 | NQ_NDX | gex_full | 29540.55 | zero_gamma:29428.3->29540.55, put_wall:29368.81->29668.81 |
| 09:41:24 | NQ_NDX | gex_one | 29540.55 | zero_gamma:29078.81->28978.81, put_wall:29068.81->28968.81 |
| 09:42:24 | ES_SPX | gex_zero | 7714.32 | call_wall:7764.71->7724.71, put_wall:7704.63->7679.71 |
| 09:42:25 | ES_SPX | gex_full | 7714.32 | zero_gamma:7711.32->7710.91, call_wall:7764.71->7724.71, put_wall:7674.71->7679.71 |
| 09:42:25 | ES_SPX | gex_one | 7714.32 | zero_gamma:7705.91->7707.21 |
| 09:42:25 | NQ_NDX | gex_zero | 29502.66 | zero_gamma:29431.22->29358.29, put_wall:29368.81->29268.81 |
| 09:42:25 | NQ_NDX | gex_full | 29502.66 | zero_gamma:29540.55->29502.66, oi_put_wall:29168.81->29668.81 |
| 09:43:26 | ES_SPX | gex_zero | 7717.39 | zero_gamma:7711.32->7711.76 |
| 09:43:27 | ES_SPX | gex_full | 7717.76 | zero_gamma:7710.91->7711.32, put_wall:7679.71->7679.63 |
| 09:43:27 | NQ_NDX | gex_zero | 29528.53 | zero_gamma:29358.29->29431.22, put_wall:29268.81->29368.81, oi_put_wall:29348.71->29348.53 |
| 09:43:28 | NQ_NDX | gex_full | 29528.53 | zero_gamma:29502.66->29528.53 |
| 09:44:28 | ES_SPX | gex_zero | 7723.31 | zero_gamma:7711.76->7710.91, call_wall:7724.71->7739.71 |
| 09:44:29 | ES_SPX | gex_full | 7723.31 | zero_gamma:7711.32->7710.91, call_wall:7724.71->7764.71 |
| 09:44:29 | ES_SPX | gex_one | 7723.31 | zero_gamma:7707.21->7706.76 |
| 09:44:29 | NQ_NDX | gex_zero | 29573 | zero_gamma:29431.22->29511.21, put_wall:29368.81->29498.81, oi_put_wall:29348.53->29348.81 |
| 09:44:30 | NQ_NDX | gex_full | 29573 | zero_gamma:29528.53->29573, oi_put_wall:29668.81->29168.81 |
| 09:44:30 | NQ_NDX | gex_one | 29569.72 | zero_gamma:28978.81->29093.81, put_wall:28968.81->29068.81 |
| 09:45:30 | ES_SPX | gex_zero | 7724.28 | zero_gamma:7710.91->7710.01, call_wall:7739.71->7740.01, put_wall:7679.71->7678.81, oi_call_wall:7754.71->7753.81, oi_put_wall:7729.71->7728.81 |
| 09:45:31 | ES_SPX | gex_full | 7724.47 | zero_gamma:7710.91->7710.01, call_wall:7764.71->7743.72, put_wall:7679.63->7678.72, oi_call_wall:7914.71->7913.81, oi_put_wall:7514.71->7513.81 |
| 09:45:31 | ES_SPX | gex_one | 7724.47 | zero_gamma:7706.76->7706.31, call_wall:7774.71->7773.81, put_wall:7674.71->7673.81, oi_call_wall:7744.71->7743.81, oi_put_wall:7664.71->7663.81 |
| 09:45:31 | NQ_NDX | gex_zero | 29572.84 | zero_gamma:29511.21->29508.98, call_wall:29598.81->29594.88, put_wall:29498.81->29494.88, oi_call_wall:29578.81->29574.88, oi_put_wall:29348.81->29344.88 |
| ... | ... | ... | ... | truncated; see CSV for 1558 changes |

## Output Files

- `research\kahn\out\2026-08-27-gex-kahn\campaign_loads.csv`
- `research\kahn\out\2026-08-27-gex-kahn\policy_runs.csv`
- `research\kahn\out\2026-08-27-gex-kahn\key_decisions_gex_join.csv`
- `research\kahn\out\2026-08-27-gex-kahn\gex_wall_changes.csv`
