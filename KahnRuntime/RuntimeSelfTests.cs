using System;

namespace KahnRuntime
{
    internal static class RuntimeSelfTests
    {
        public static void RunAll()
        {
            PlanParserAcceptsMinimalCampaign();
            PlanParserAcceptsPassiveHarvestObjective();
            RetryExhaustionPausesCampaignInsteadOfRetiring();
            TrapProbeAllowsLeanAtEdge();
            ArmedProbeAllowsLaterInsideRail();
            ExpiredFlatCampaignBlocksProbeAdmission();
            ExpiredPositionedCampaignStillManagesAddsAndRisk();
            EdgePriceGateBlocksBodyProbe();
            EdgePriceGateAllowsEdgeProbe();
            EdgePriceGateBlocksBodyAdd();
            TargetZoneSuppressesPressAdd();
            NoAddZoneSuppressesPressAdd();
            EvaluateZoneSuppressesAdd();
            PressAboveNoAddAllowsAdd();
            PreserveRiskAnchorOnAddUsesRoot();
            PassiveHarvestFloorTouchStagesLimitWithoutAssumedFill();
            PassiveHarvestShadowFillReducesPosition();
            PassiveHarvestOppositeOwnershipOverridesTargetRetire();
            PassiveHarvestFloorLossRetires();
            TargetOppositeOwnershipRetires();
            BuildTrialEffortNoRewardRetires();
            SponsorFailureFlattensBeforeHold();
            OppositeRailFailureNearRiskDoesNotFlatten();
            PathStressCapsFullInventoryAndSuppressesAdds();
            PathStressSuppressesAddsAtCoreSize();
            PathStressAbsorptionReducesRunner();
            CheckpointSerializesNonFiniteMarketFields();
        }

        private static void CheckpointSerializesNonFiniteMarketFields()
        {
            string path = System.IO.Path.Combine(
                System.IO.Path.GetTempPath(),
                "kahn-checkpoint-" + Guid.NewGuid().ToString("N") + ".json");
            try
            {
                RuntimeCheckpointStore store = new(path);
                store.Save(new RuntimeCheckpointData
                {
                    RuntimeState = "SelfTest",
                    TickSize = double.NaN,
                    LatestBid = null,
                    LatestAsk = null,
                    EvidenceWarmupRemainingSeconds = 0,
                    PositionQuantity = 0,
                    PositionAveragePrice = 0,
                });
                string json = System.IO.File.ReadAllText(path);
                Assert(json.Contains("latest_bid"), "checkpoint writes latest bid field");
            }
            finally
            {
                try { System.IO.File.Delete(path); } catch { }
            }
        }

        private static void PlanParserAcceptsMinimalCampaign()
        {
            string json = """
            {
              "schema_version": 1,
              "kind": "KAHN_CAMPAIGN",
              "id": "selftest-short",
              "status": "active",
              "created_at": "2026-08-24T13:50:00Z",
              "side": "short",
              "window": {
                "not_before": "2026-08-24T13:50:00Z",
                "expires_at": "2026-08-24T14:20:00Z"
              },
              "arena": { "lower": 7650.0, "upper": 7680.0 },
              "sizing": {
                "probe_quantity": 1,
                "add_quantity": 1,
                "max_position_quantity": 4
              },
              "objective": {
                "target_range": { "lower": 7658.0, "upper": 7660.0 },
                "target_proximity_ticks": 8,
                "suppress_adds_in_target_zone": true
              },
              "waypoints": [
                {
                  "id": "trap-7674",
                  "role": "trap_probe",
                  "range": { "lower": 7673.75, "upper": 7675.25 }
                }
              ]
            }
            """;

            CampaignPlan plan = CampaignPlanParser.Parse(json, "selftest");
            Assert(plan.Side == CampaignSide.Short, "plan side");
            Assert(plan.Waypoints.Count == 1, "waypoint count");
            Assert(plan.Execution.MaxRetry == 3, "default max retry");
        }

        private static void PlanParserAcceptsPassiveHarvestObjective()
        {
            string json = """
            {
              "schema_version": 1,
              "kind": "KAHN_CAMPAIGN",
              "id": "selftest-passive-harvest",
              "status": "active",
              "created_at": "2026-08-24T13:50:00Z",
              "side": "long",
              "window": {
                "not_before": "2026-08-24T13:50:00Z",
                "expires_at": "2026-08-24T14:20:00Z"
              },
              "arena": { "lower": 7670.0, "upper": 7690.0 },
              "objective": {
                "target_range": { "lower": 7680.0, "upper": 7685.0 },
                "passive_harvest": {
                  "range": { "lower": 7680.0, "upper": 7683.0 },
                  "initial_clip_quantity": 1,
                  "follow_clip_quantity": 2,
                  "max_working_quantity": 2,
                  "floor_failure_ticks": 1
                }
              },
              "waypoints": [
                {
                  "id": "trap-7674",
                  "role": "trap_probe",
                  "range": { "lower": 7673.75, "upper": 7675.25 }
                }
              ]
            }
            """;

            CampaignPlan plan = CampaignPlanParser.Parse(json, "selftest");
            PassiveHarvestObjective harvest = plan.Objective.PassiveHarvest;
            Assert(harvest?.IsUsable == true, "passive harvest parses usable");
            Assert(harvest.Floor(plan.Side) == 7680.0, "long passive harvest floor");
            Assert(harvest.Stretch(plan.Side) == 7683.0, "long passive harvest stretch");
            Assert(harvest.FollowClipQuantity == 2, "passive harvest follow clip");
            Assert(harvest.MaxWorkingQuantity == 2, "passive harvest working cap");
        }

        private static void RetryExhaustionPausesCampaignInsteadOfRetiring()
        {
            CampaignPlan plan = ShortPlan();
            CampaignState state = CampaignState.ForPlan(plan);

            ApplyProbeAndFlatten(state, plan, "first");
            Assert(state.Phase == CampaignPhase.Ready, "first retry returns ready");
            Assert(state.ExecutionAttemptCount == 1, "first retry count");
            Assert(state.CanAttemptEntry(plan), "first retry can continue");

            ApplyProbeAndFlatten(state, plan, "second");
            Assert(state.Phase == CampaignPhase.Ready, "second retry returns ready");
            Assert(state.ExecutionAttemptCount == 2, "second retry count");
            Assert(state.CanAttemptEntry(plan), "second retry can continue");

            ApplyProbeAndFlatten(state, plan, "third");
            Assert(state.Phase == CampaignPhase.Paused, "retry exhaustion pauses");
            Assert(!state.IsRetired, "retry exhaustion does not retire");
            Assert(state.ExecutionAttemptCount == 3, "retry exhausted count");
            Assert(state.ExecutionRetriesRemaining(plan) == 0, "retry exhausted remaining");
            Assert(!state.CanAttemptEntry(plan), "retry exhaustion blocks entry");

            CampaignEvidence evidence = new()
            {
                EventId = "paused-lean",
                Timestamp = DateTimeOffset.UtcNow,
                Source = EvidenceSource.LevelLedger,
                Kind = EvidenceKind.RailOwned,
                Side = EvidenceSide.Supply,
                Range = new PriceRange { Lower = 7674.0, Upper = 7674.5 },
            };
            PolicyDecision decision = CampaignPolicyEngine.CreateDefault().Evaluate(
                new CampaignContext(plan, state, 0.25, DateTimeOffset.UtcNow),
                evidence);
            Assert(decision.Action == PolicyAction.NoAction, "paused campaign blocks probe");
        }

        private static void TrapProbeAllowsLeanAtEdge()
        {
            CampaignPlan plan = ShortPlan();
            CampaignState state = CampaignState.ForPlan(plan);
            CampaignPolicyEngine engine = CampaignPolicyEngine.CreateDefault();
            CampaignEvidence evidence = new()
            {
                EventId = "lean",
                Timestamp = DateTimeOffset.UtcNow,
                Source = EvidenceSource.LevelLedger,
                Kind = EvidenceKind.RailOwned,
                Side = EvidenceSide.Supply,
                Range = new PriceRange { Lower = 7674.0, Upper = 7674.5 },
            };

            PolicyDecision decision = engine.Evaluate(
                new CampaignContext(plan, state, 0.25, DateTimeOffset.UtcNow),
                evidence);
            Assert(decision.Action == PolicyAction.AllowProbe, "trap probe lean");
        }

        private static void ArmedProbeAllowsLaterInsideRail()
        {
            CampaignPlan plan = ShortPlan();
            CampaignState state = CampaignState.ForPlan(plan);
            DateTimeOffset now = DateTimeOffset.UtcNow;
            state.ApplyDecision(new PolicyDecision
            {
                Action = PolicyAction.ArmProbe,
                Policy = "selftest",
                ReasonCode = "seed_arm",
                WaypointId = "trap-7674",
                ExpiresAt = now.AddSeconds(90),
            }, plan, simulateAcceptedDecisions: true, appliedAt: now);

            CampaignEvidence evidence = new()
            {
                EventId = "inside-lean",
                Timestamp = now.AddSeconds(30),
                Source = EvidenceSource.LevelLedger,
                Kind = EvidenceKind.RailOwned,
                Side = EvidenceSide.Supply,
                Range = new PriceRange { Lower = 7668.25, Upper = 7671.25 },
                WaypointId = "press-7668",
            };

            PolicyDecision decision = CampaignPolicyEngine.CreateDefault().Evaluate(
                new CampaignContext(plan, state, 0.25, evidence.Timestamp),
                evidence);
            Assert(decision.Action == PolicyAction.AllowProbe, "armed probe later inside rail");
        }

        private static void ExpiredFlatCampaignBlocksProbeAdmission()
        {
            CampaignPlan plan = ShortPlan(ExpiredWindow());
            CampaignState state = CampaignState.ForPlan(plan);
            CampaignPolicyEngine engine = CampaignPolicyEngine.CreateDefault();
            DateTimeOffset now = DateTimeOffset.UtcNow;
            CampaignEvidence evidence = new()
            {
                EventId = "expired-flat-lean",
                Timestamp = now,
                Source = EvidenceSource.LevelLedger,
                Kind = EvidenceKind.RailOwned,
                Side = EvidenceSide.Supply,
                Range = new PriceRange { Lower = 7674.0, Upper = 7674.5 },
            };

            Assert(!plan.ShouldEvaluateEvidenceAt(now, state),
                "expired flat campaign skips evidence");
            PolicyDecision decision = engine.Evaluate(new CampaignContext(plan, state, 0.25, now), evidence);
            Assert(decision.Action == PolicyAction.NoAction,
                "expired flat campaign blocks probe");
        }

        private static void ExpiredPositionedCampaignStillManagesAddsAndRisk()
        {
            CampaignPlan plan = LongPlan(ExpiredWindow());
            CampaignState state = CampaignState.ForPlan(plan);
            SeedPosition(state, plan, 1);
            CampaignPolicyEngine engine = CampaignPolicyEngine.CreateDefault();
            DateTimeOffset now = DateTimeOffset.UtcNow;

            CampaignEvidence pressEvidence = new()
            {
                EventId = "expired-position-press",
                Timestamp = now,
                Source = EvidenceSource.LevelLedger,
                Kind = EvidenceKind.RailOwned,
                Side = EvidenceSide.Demand,
                Range = new PriceRange { Lower = 7675.5, Upper = 7676.0 },
            };
            Assert(plan.ShouldEvaluateEvidenceAt(now, state),
                "expired positioned campaign keeps evaluating evidence");
            PolicyDecision add = engine.Evaluate(
                new CampaignContext(plan, state, 0.25, now),
                pressEvidence);
            Assert(add.Action == PolicyAction.AllowAdd,
                "expired positioned campaign still allows campaign add");

            CampaignEvidence sponsorFailure = new()
            {
                EventId = "expired-position-sponsor-fail",
                Timestamp = now.AddSeconds(1),
                Source = EvidenceSource.LevelLedger,
                Kind = EvidenceKind.SponsorFailed,
                Side = EvidenceSide.Demand,
                Range = new PriceRange { Lower = 7676.0, Upper = 7678.0 },
            };
            PolicyDecision flatten = engine.Evaluate(
                new CampaignContext(plan, state, 0.25, sponsorFailure.Timestamp),
                sponsorFailure);
            Assert(flatten.Action == PolicyAction.Flatten,
                "expired positioned campaign still flattens on sponsor failure");
        }
        private static void EdgePriceGateBlocksBodyProbe()
        {
            CampaignPlan plan = ShortEdgePlan();
            CampaignState state = CampaignState.ForPlan(plan);
            CampaignEvidence evidence = new()
            {
                EventId = "edge-rail-body-price",
                Timestamp = DateTimeOffset.UtcNow,
                Source = EvidenceSource.LevelLedger,
                Kind = EvidenceKind.RailOwned,
                Side = EvidenceSide.Supply,
                Price = 7687.75,
                Range = new PriceRange { Lower = 7690.25, Upper = 7691.75 },
                WaypointId = "edge-7690-7692",
            };

            PolicyDecision decision = CampaignPolicyEngine.CreateDefault().Evaluate(
                new CampaignContext(plan, state, 0.25, DateTimeOffset.UtcNow),
                evidence);
            Assert(decision.Action == PolicyAction.NoAction, "edge price gate blocks body probe");
        }

        private static void EdgePriceGateAllowsEdgeProbe()
        {
            CampaignPlan plan = ShortEdgePlan();
            CampaignState state = CampaignState.ForPlan(plan);
            CampaignEvidence evidence = new()
            {
                EventId = "edge-rail-edge-price",
                Timestamp = DateTimeOffset.UtcNow,
                Source = EvidenceSource.LevelLedger,
                Kind = EvidenceKind.RailOwned,
                Side = EvidenceSide.Supply,
                Price = 7691.25,
                Range = new PriceRange { Lower = 7690.25, Upper = 7691.75 },
                WaypointId = "edge-7690-7692",
            };

            PolicyDecision decision = CampaignPolicyEngine.CreateDefault().Evaluate(
                new CampaignContext(plan, state, 0.25, DateTimeOffset.UtcNow),
                evidence);
            Assert(decision.Action == PolicyAction.AllowProbe, "edge price gate allows edge probe");
        }

        private static void EdgePriceGateBlocksBodyAdd()
        {
            CampaignPlan plan = ShortEdgePlan();
            CampaignState state = CampaignState.ForPlan(plan);
            state.ApplyDecision(new PolicyDecision
            {
                Action = PolicyAction.AllowProbe,
                Policy = "selftest",
                ReasonCode = "seed_position",
                Quantity = 1,
                RiskAnchor = new PriceRange { Lower = 7690.25, Upper = 7691.75 },
            }, plan, simulateAcceptedDecisions: true);

            CampaignEvidence evidence = new()
            {
                EventId = "edge-add-body-price",
                Timestamp = DateTimeOffset.UtcNow,
                Source = EvidenceSource.LevelLedger,
                Kind = EvidenceKind.RailOwned,
                Side = EvidenceSide.Supply,
                Price = 7688.0,
                Range = new PriceRange { Lower = 7690.25, Upper = 7691.75 },
                WaypointId = "press-edge-7690-7692",
            };

            PolicyDecision decision = CampaignPolicyEngine.CreateDefault().Evaluate(
                new CampaignContext(plan, state, 0.25, DateTimeOffset.UtcNow),
                evidence);
            Assert(decision.Action == PolicyAction.NoAction, "edge price gate blocks body add");
        }
        private static void TargetZoneSuppressesPressAdd()
        {
            CampaignPlan plan = LongPlan();
            CampaignState state = CampaignState.ForPlan(plan);
            state.ApplyDecision(new PolicyDecision
            {
                Action = PolicyAction.AllowProbe,
                Policy = "selftest",
                ReasonCode = "seed_position",
                Quantity = 1,
                RiskAnchor = new PriceRange { Lower = 7671.0, Upper = 7672.0 },
            }, plan, simulateAcceptedDecisions: true);

            CampaignEvidence evidence = new()
            {
                EventId = "target-demand",
                Timestamp = DateTimeOffset.UtcNow,
                Source = EvidenceSource.LevelLedger,
                Kind = EvidenceKind.RailOwned,
                Side = EvidenceSide.Demand,
                Range = new PriceRange { Lower = 7680.0, Upper = 7680.75 },
            };

            PolicyDecision decision = CampaignPolicyEngine.CreateDefault().Evaluate(
                new CampaignContext(plan, state, 0.25, DateTimeOffset.UtcNow),
                evidence);
            Assert(decision.Action == PolicyAction.SuppressAdd, "target suppress priority");
        }

        private static void NoAddZoneSuppressesPressAdd()
        {
            CampaignPlan plan = LongNoAddPlan();
            CampaignState state = CampaignState.ForPlan(plan);
            state.ApplyDecision(new PolicyDecision
            {
                Action = PolicyAction.AllowProbe,
                Policy = "selftest",
                ReasonCode = "seed_position",
                Quantity = 1,
                RiskAnchor = new PriceRange { Lower = 7658.0, Upper = 7660.0 },
            }, plan, simulateAcceptedDecisions: true);

            CampaignEvidence evidence = new()
            {
                EventId = "no-add-demand",
                Timestamp = DateTimeOffset.UtcNow,
                Source = EvidenceSource.LevelLedger,
                Kind = EvidenceKind.RailOwned,
                Side = EvidenceSide.Demand,
                Range = new PriceRange { Lower = 7663.0, Upper = 7664.0 },
                WaypointId = "no-add-7660-7667",
            };

            PolicyDecision decision = CampaignPolicyEngine.CreateDefault().Evaluate(
                new CampaignContext(plan, state, 0.25, DateTimeOffset.UtcNow),
                evidence);
            Assert(decision.Action == PolicyAction.SuppressAdd, "no-add zone suppresses add");
            Assert(decision.ReasonCode == "inside_no_add_zone", "no-add reason");
            state.ApplyDecision(decision, plan, simulateAcceptedDecisions: true);
            Assert(state.Phase == CampaignPhase.ProbeOpen, "no-add preserves phase");
        }

        private static void PressAboveNoAddAllowsAdd()
        {
            CampaignPlan plan = LongNoAddPlan();
            CampaignState state = CampaignState.ForPlan(plan);
            state.ApplyDecision(new PolicyDecision
            {
                Action = PolicyAction.AllowProbe,
                Policy = "selftest",
                ReasonCode = "seed_position",
                Quantity = 1,
                RiskAnchor = new PriceRange { Lower = 7658.0, Upper = 7660.0 },
            }, plan, simulateAcceptedDecisions: true);

            CampaignEvidence evidence = new()
            {
                EventId = "press-demand",
                Timestamp = DateTimeOffset.UtcNow,
                Source = EvidenceSource.LevelLedger,
                Kind = EvidenceKind.RailOwned,
                Side = EvidenceSide.Demand,
                Range = new PriceRange { Lower = 7671.0, Upper = 7672.0 },
                WaypointId = "press-7667-7677",
            };

            PolicyDecision decision = CampaignPolicyEngine.CreateDefault().Evaluate(
                new CampaignContext(plan, state, 0.25, DateTimeOffset.UtcNow),
                evidence);
            Assert(decision.Action == PolicyAction.AllowAdd, "press above no-add allows add");
        }
        private static void TargetOppositeOwnershipRetires()
        {
            CampaignPlan plan = LongNoAddPlan();
            CampaignState state = CampaignState.ForPlan(plan);
            state.ApplyDecision(new PolicyDecision
            {
                Action = PolicyAction.AllowProbe,
                Policy = "selftest",
                ReasonCode = "seed_position",
                Quantity = 2,
                RiskAnchor = new PriceRange { Lower = 7670.75, Upper = 7673.5 },
            }, plan, simulateAcceptedDecisions: true);

            CampaignEvidence evidence = new()
            {
                EventId = "target-supply",
                Timestamp = DateTimeOffset.UtcNow,
                Source = EvidenceSource.LevelLedger,
                Kind = EvidenceKind.RailOwned,
                Side = EvidenceSide.Supply,
                Range = new PriceRange { Lower = 7682.5, Upper = 7685.25 },
                WaypointId = "target-7680-7685",
            };

            PolicyDecision decision = CampaignPolicyEngine.CreateDefault().Evaluate(
                new CampaignContext(plan, state, 0.25, DateTimeOffset.UtcNow),
                evidence);
            Assert(decision.Action == PolicyAction.Retire, "target opposite ownership retires");
        }
        private static void BuildTrialEffortNoRewardRetires()
        {
            CampaignPlan plan = ShortPlan();
            CampaignState state = CampaignState.ForPlan(plan);
            state.ApplyDecision(new PolicyDecision
            {
                Action = PolicyAction.AllowProbe,
                Policy = "selftest",
                ReasonCode = "seed_position",
                Quantity = 2,
                RiskAnchor = new PriceRange { Lower = 7665.75, Upper = 7666.0 },
            }, plan, simulateAcceptedDecisions: true);

            CampaignEvidence evidence = new()
            {
                EventId = "effort-no-reward",
                Timestamp = DateTimeOffset.UtcNow,
                Source = EvidenceSource.BubbleTape,
                Kind = EvidenceKind.Absorption,
                Side = EvidenceSide.Sell,
                Range = new PriceRange { Lower = 7658.25, Upper = 7661.0 },
                Volume = 300,
                Delta = -826,
                WaypointId = "build-7660",
            };

            PolicyDecision decision = CampaignPolicyEngine.CreateDefault().Evaluate(
                new CampaignContext(plan, state, 0.25, DateTimeOffset.UtcNow),
                evidence);
            Assert(decision.Action == PolicyAction.Retire, "build trial effort/no reward retires");
        }
        private static void SponsorFailureFlattensBeforeHold()
        {
            CampaignPlan plan = ShortPlan();
            CampaignState state = CampaignState.ForPlan(plan);
            state.ApplyDecision(new PolicyDecision
            {
                Action = PolicyAction.AllowProbe,
                Policy = "selftest",
                ReasonCode = "seed_position",
                Quantity = 1,
                RiskAnchor = new PriceRange { Lower = 7671.0, Upper = 7672.0 },
            }, plan, simulateAcceptedDecisions: true);

            CampaignEvidence evidence = new()
            {
                EventId = "sponsor-fail",
                Timestamp = DateTimeOffset.UtcNow,
                Source = EvidenceSource.LevelLedger,
                Kind = EvidenceKind.RailFailed,
                Side = EvidenceSide.Supply,
                Range = new PriceRange { Lower = 7671.25, Upper = 7671.75 },
            };

            PolicyDecision decision = CampaignPolicyEngine.CreateDefault().Evaluate(
                new CampaignContext(plan, state, 0.25, DateTimeOffset.UtcNow),
                evidence);
            Assert(decision.Action == PolicyAction.Flatten, "sponsor failure flatten");
        }

        private static void OppositeRailFailureNearRiskDoesNotFlatten()
        {
            CampaignPlan plan = ShortPlan();
            CampaignState state = CampaignState.ForPlan(plan);
            state.ApplyDecision(new PolicyDecision
            {
                Action = PolicyAction.AllowProbe,
                Policy = "selftest",
                ReasonCode = "seed_position",
                Quantity = 1,
                RiskAnchor = new PriceRange { Lower = 7671.0, Upper = 7672.0 },
            }, plan, simulateAcceptedDecisions: true);

            CampaignEvidence evidence = new()
            {
                EventId = "opposite-fail-near-risk",
                Timestamp = DateTimeOffset.UtcNow,
                Source = EvidenceSource.LevelLedger,
                Kind = EvidenceKind.RailFailed,
                Side = EvidenceSide.Demand,
                Range = new PriceRange { Lower = 7671.25, Upper = 7671.75 },
            };

            PolicyDecision decision = CampaignPolicyEngine.CreateDefault().Evaluate(
                new CampaignContext(plan, state, 0.25, DateTimeOffset.UtcNow),
                evidence);
            Assert(decision.Action == PolicyAction.NoAction,
                "opposite rail failure near risk does not flatten");
        }
        private static void PathStressCapsFullInventoryAndSuppressesAdds()
        {
            CampaignPlan plan = ShortPathStressPlan();
            CampaignState state = CampaignState.ForPlan(plan);
            SeedPosition(state, plan, quantity: 5);
            DateTimeOffset now = DateTimeOffset.UtcNow;
            CampaignEvidence evidence = new()
            {
                EventId = "b-low-break",
                Timestamp = now,
                Source = EvidenceSource.Price,
                Kind = EvidenceKind.PriceCross,
                Side = EvidenceSide.Sell,
                Price = 7680.0,
                WaypointId = "path-stress-7664-7680",
            };

            PolicyDecision decision = CampaignPolicyEngine.CreateDefault().Evaluate(
                new CampaignContext(plan, state, 0.25, now),
                evidence);
            Assert(decision.Action == PolicyAction.Reduce, "path stress caps inventory");
            Assert(decision.ReasonCode == "inventory_above_path_cap", "path stress cap reason");
            Assert(decision.Quantity == 4, "path stress cap quantity");
            state.ApplyDecision(decision, plan, simulateAcceptedDecisions: true, appliedAt: now);
            Assert(state.SimulatedPositionQuantity == 1, "path stress leaves runner");
            Assert(state.AddsSuppressed(now.AddSeconds(30)), "path stress reduce suppresses adds");
        }

        private static void PathStressSuppressesAddsAtCoreSize()
        {
            CampaignPlan plan = ShortPathStressPlan();
            CampaignState state = CampaignState.ForPlan(plan);
            SeedPosition(state, plan, quantity: 1);
            DateTimeOffset now = DateTimeOffset.UtcNow;
            CampaignEvidence evidence = new()
            {
                EventId = "path-watch",
                Timestamp = now,
                Source = EvidenceSource.Price,
                Kind = EvidenceKind.PriceTouch,
                Side = EvidenceSide.None,
                Price = 7672.0,
                WaypointId = "path-stress-7664-7680",
            };

            PolicyDecision decision = CampaignPolicyEngine.CreateDefault().Evaluate(
                new CampaignContext(plan, state, 0.25, now),
                evidence);
            Assert(decision.Action == PolicyAction.SuppressAdd, "path stress suppresses adds");
            Assert(decision.ReasonCode == "mature_path_adds_suppressed",
                "path stress suppress reason");
        }

        private static void PathStressAbsorptionReducesRunner()
        {
            CampaignPlan plan = ShortPathStressPlan();
            CampaignState state = CampaignState.ForPlan(plan);
            SeedPosition(state, plan, quantity: 1);
            DateTimeOffset now = DateTimeOffset.UtcNow;
            CampaignEvidence evidence = new()
            {
                EventId = "runner-sell-absorbed",
                Timestamp = now,
                Source = EvidenceSource.BubbleTape,
                Kind = EvidenceKind.Absorption,
                Side = EvidenceSide.Sell,
                Range = new PriceRange { Lower = 7666.0, Upper = 7667.75 },
                Volume = 359,
                Delta = -359,
                WaypointId = "path-stress-7664-7680",
            };

            PolicyDecision decision = CampaignPolicyEngine.CreateDefault().Evaluate(
                new CampaignContext(plan, state, 0.25, now),
                evidence);
            Assert(decision.Action == PolicyAction.Reduce, "path stress absorption reduces runner");
            Assert(decision.ReasonCode == "path_same_side_effort_absorbed",
                "path stress absorption reason");
            state.ApplyDecision(decision, plan, simulateAcceptedDecisions: true, appliedAt: now);
            Assert(state.SimulatedPositionQuantity == 0, "path stress runner flattened");
            Assert(state.Phase == CampaignPhase.Ready, "path stress flat leaves plan ready");
        }
        private static void EvaluateZoneSuppressesAdd()
        {
            CampaignPlan plan = LongEvaluatePlan();
            CampaignState state = CampaignState.ForPlan(plan);
            state.ApplyDecision(new PolicyDecision
            {
                Action = PolicyAction.AllowProbe,
                Policy = "selftest",
                ReasonCode = "seed_position",
                Quantity = 1,
                RiskAnchor = new PriceRange { Lower = 29040.0, Upper = 29060.0 },
                EvidenceId = "seed-probe",
            }, plan, simulateAcceptedDecisions: true);

            CampaignEvidence evidence = new()
            {
                EventId = "evaluate-demand",
                Timestamp = DateTimeOffset.UtcNow,
                Source = EvidenceSource.LevelLedger,
                Kind = EvidenceKind.RailOwned,
                Side = EvidenceSide.Demand,
                Range = new PriceRange { Lower = 29155.0, Upper = 29168.0 },
                WaypointId = "evaluate-29150-29185",
            };

            PolicyDecision decision = CampaignPolicyEngine.CreateDefault().Evaluate(
                new CampaignContext(plan, state, 0.25, DateTimeOffset.UtcNow),
                evidence);
            Assert(decision.Action == PolicyAction.SuppressAdd, "evaluate zone suppresses add");
            Assert(decision.ReasonCode == "inside_evaluate_zone", "evaluate suppress reason");
        }

        private static void PreserveRiskAnchorOnAddUsesRoot()
        {
            CampaignPlan plan = LongPreserveRiskPlan();
            CampaignState state = CampaignState.ForPlan(plan);
            state.ApplyDecision(new PolicyDecision
            {
                Action = PolicyAction.AllowProbe,
                Policy = "selftest",
                ReasonCode = "seed_probe",
                Quantity = 1,
                RiskAnchor = new PriceRange { Lower = 29040.0, Upper = 29060.0 },
                EvidenceId = "seed-probe",
            }, plan, simulateAcceptedDecisions: true);
            state.ApplyDecision(new PolicyDecision
            {
                Action = PolicyAction.AllowAdd,
                Policy = "selftest",
                ReasonCode = "seed_child_anchor",
                Quantity = 1,
                RiskAnchor = new PriceRange { Lower = 29088.0, Upper = 29098.0 },
                EvidenceId = "seed-child",
            }, plan, simulateAcceptedDecisions: true);

            CampaignEvidence evidence = new()
            {
                EventId = "preserve-root-add",
                Timestamp = DateTimeOffset.UtcNow,
                Source = EvidenceSource.LevelLedger,
                Kind = EvidenceKind.RailOwned,
                Side = EvidenceSide.Demand,
                Range = new PriceRange { Lower = 29112.0, Upper = 29135.0 },
                WaypointId = "press-29100-29145",
            };

            PolicyDecision decision = CampaignPolicyEngine.CreateDefault().Evaluate(
                new CampaignContext(plan, state, 0.25, DateTimeOffset.UtcNow),
                evidence);
            Assert(decision.Action == PolicyAction.AllowAdd, "preserve risk add allowed");
            Assert(decision.ReasonCode == "same_side_ownership_add_preserve_root_risk",
                "preserve risk reason");
            Assert(decision.RiskAnchor?.Lower == 29040.0 && decision.RiskAnchor.Upper == 29060.0,
                "preserve risk uses root anchor");
            state.ApplyDecision(decision, plan, simulateAcceptedDecisions: true);
            Assert(state.ActiveRiskAnchor?.Lower == 29040.0 && state.ActiveRiskAnchor.Upper == 29060.0,
                "active risk remains root after preserve add");
            Assert(state.ActiveRiskAnchorEvidenceId == "seed-probe",
                "active risk evidence remains root after preserve add");
        }

        private static void PassiveHarvestFloorTouchStagesLimitWithoutAssumedFill()
        {
            CampaignPlan plan = LongPassiveHarvestPlan();
            CampaignState state = CampaignState.ForPlan(plan);
            SeedPosition(state, plan, quantity: 4);
            DateTimeOffset now = DateTimeOffset.UtcNow;
            CampaignEvidence evidence = new()
            {
                EventId = "harvest-floor-touch",
                Timestamp = now,
                Source = EvidenceSource.Price,
                Kind = EvidenceKind.PriceTouch,
                Side = EvidenceSide.None,
                Price = 7680.25,
            };

            PolicyDecision decision = CampaignPolicyEngine.CreateDefault().Evaluate(
                new CampaignContext(plan, state, 0.25, now),
                evidence);
            Assert(decision.Action == PolicyAction.PassiveHarvest,
                "passive harvest floor touch");
            Assert(decision.Quantity == 1, "passive harvest initial clip");
            state.ApplyDecision(decision, plan, simulateAcceptedDecisions: true, appliedAt: now);
            Assert(state.PassiveHarvestActive, "passive harvest active after submit");
            Assert(state.SimulatedPositionQuantity == 4,
                "passive harvest submit does not assume live fill");
            Assert(state.Phase == CampaignPhase.TargetZone, "passive harvest phase");
        }

        private static void PassiveHarvestShadowFillReducesPosition()
        {
            CampaignPlan plan = LongPassiveHarvestPlan();
            CampaignState state = CampaignState.ForPlan(plan);
            SeedPosition(state, plan, quantity: 4);
            DateTimeOffset now = DateTimeOffset.UtcNow;
            PolicyDecision decision = new()
            {
                Action = PolicyAction.PassiveHarvest,
                Policy = "passive_harvest",
                ReasonCode = "harvest_floor_reached",
                Quantity = 1,
                ExpiresAt = now.AddSeconds(90),
                EvidenceId = "shadow-harvest",
            };

            state.ApplyDecision(decision,
                plan,
                simulateAcceptedDecisions: true,
                appliedAt: now,
                passiveHarvestFilledQuantity: 1);
            Assert(state.PassiveHarvestActive, "shadow passive harvest active");
            Assert(state.SimulatedPositionQuantity == 3,
                "shadow passive harvest fill reduces position");
        }

        private static void PassiveHarvestOppositeOwnershipOverridesTargetRetire()
        {
            CampaignPlan plan = LongPassiveHarvestPlan();
            CampaignState state = CampaignState.ForPlan(plan);
            SeedPosition(state, plan, quantity: 4);
            DateTimeOffset now = DateTimeOffset.UtcNow;
            CampaignEvidence evidence = new()
            {
                EventId = "harvest-opposite-owned",
                Timestamp = now,
                Source = EvidenceSource.LevelLedger,
                Kind = EvidenceKind.RailOwned,
                Side = EvidenceSide.Supply,
                Price = 7683.25,
                Range = new PriceRange { Lower = 7682.75, Upper = 7683.5 },
                WaypointId = "target-7680",
            };

            PolicyDecision decision = CampaignPolicyEngine.CreateDefault().Evaluate(
                new CampaignContext(plan, state, 0.25, now),
                evidence);
            Assert(decision.Action == PolicyAction.PassiveHarvest,
                "passive harvest beats target retire while floor holds");
            Assert(decision.ReasonCode == "opposite_ownership_at_harvest",
                "passive harvest opposite ownership reason");
            Assert(decision.Quantity == 2, "passive harvest follow clip at stretch");
        }

        private static void PassiveHarvestFloorLossRetires()
        {
            CampaignPlan plan = LongPassiveHarvestPlan();
            CampaignState state = CampaignState.ForPlan(plan);
            SeedPosition(state, plan, quantity: 3);
            DateTimeOffset now = DateTimeOffset.UtcNow;
            state.ApplyDecision(new PolicyDecision
            {
                Action = PolicyAction.PassiveHarvest,
                Policy = "passive_harvest",
                ReasonCode = "harvest_floor_reached",
                Quantity = 1,
                EvidenceId = "seed-harvest",
            }, plan, simulateAcceptedDecisions: true, appliedAt: now);

            CampaignEvidence evidence = new()
            {
                EventId = "floor-lost",
                Timestamp = now.AddSeconds(10),
                Source = EvidenceSource.Price,
                Kind = EvidenceKind.PriceTouch,
                Side = EvidenceSide.None,
                Price = 7679.75,
            };
            PolicyDecision decision = CampaignPolicyEngine.CreateDefault().Evaluate(
                new CampaignContext(plan, state, 0.25, evidence.Timestamp),
                evidence);
            Assert(decision.Action == PolicyAction.Retire,
                "passive harvest floor loss retires");
            Assert(decision.ReasonCode == "harvest_floor_lost",
                "passive harvest floor loss reason");
        }

        private static CampaignPlan ShortPlan(CampaignWindow window = null)
            => new()
            {
                SchemaVersion = 1,
                Kind = "KAHN_CAMPAIGN",
                Id = "short-plan",
                Status = "active",
                CreatedAt = DateTimeOffset.UtcNow,
                Side = CampaignSide.Short,
                Window = window ?? Window(),
                Arena = new PriceRange { Lower = 7650.0, Upper = 7680.0 },
                Sizing = new CampaignSizing
                {
                    ProbeQuantity = 1,
                    AddQuantity = 1,
                    MaxPositionQuantity = 4,
                },
                Risk = new CampaignRisk(),
                Objective = new CampaignObjective
                {
                    TargetRange = new PriceRange { Lower = 7658.0, Upper = 7660.0 },
                    TargetProximityTicks = 8,
                },
                Policies = new CampaignPolicyFlags(),
                Waypoints = new[]
                {
                    new CampaignWaypoint
                    {
                        Id = "trap-7674",
                        Role = WaypointRole.TrapProbe,
                        Range = new PriceRange { Lower = 7673.75, Upper = 7675.25 },
                    },
                    new CampaignWaypoint
                    {
                        Id = "build-7660",
                        Role = WaypointRole.BuildTrial,
                        Range = new PriceRange { Lower = 7658.0, Upper = 7660.0 },
                    },
                },
            };

        private static CampaignPlan LongPassiveHarvestPlan()
            => new()
            {
                SchemaVersion = 1,
                Kind = "KAHN_CAMPAIGN",
                Id = "long-passive-harvest-plan",
                Status = "active",
                CreatedAt = DateTimeOffset.UtcNow,
                Side = CampaignSide.Long,
                Window = Window(),
                Arena = new PriceRange { Lower = 7660.0, Upper = 7690.0 },
                Sizing = new CampaignSizing
                {
                    ProbeQuantity = 1,
                    AddQuantity = 1,
                    MaxPositionQuantity = 4,
                },
                Risk = new CampaignRisk(),
                Objective = new CampaignObjective
                {
                    TargetRange = new PriceRange { Lower = 7680.0, Upper = 7685.0 },
                    TargetProximityTicks = 8,
                    PassiveHarvest = new PassiveHarvestObjective
                    {
                        Range = new PriceRange { Lower = 7680.0, Upper = 7683.0 },
                        InitialClipQuantity = 1,
                        FollowClipQuantity = 2,
                        MaxWorkingQuantity = 2,
                    },
                },
                Policies = new CampaignPolicyFlags(),
                Waypoints = new[]
                {
                    new CampaignWaypoint
                    {
                        Id = "target-7680",
                        Role = WaypointRole.Target,
                        Range = new PriceRange { Lower = 7680.0, Upper = 7685.0 },
                    },
                },
            };

        private static CampaignPlan ShortEdgePlan()
            => new()
            {
                SchemaVersion = 1,
                Kind = "KAHN_CAMPAIGN",
                Id = "short-edge-plan",
                Status = "active",
                CreatedAt = DateTimeOffset.UtcNow,
                Side = CampaignSide.Short,
                Window = Window(),
                Arena = new PriceRange { Lower = 7680.0, Upper = 7695.0 },
                Sizing = new CampaignSizing
                {
                    ProbeQuantity = 1,
                    AddQuantity = 1,
                    MaxPositionQuantity = 2,
                },
                Risk = new CampaignRisk(),
                Objective = new CampaignObjective
                {
                    TargetRange = new PriceRange { Lower = 7680.0, Upper = 7684.0 },
                    TargetProximityTicks = 4,
                },
                Policies = new CampaignPolicyFlags(),
                Waypoints = new[]
                {
                    new CampaignWaypoint
                    {
                        Id = "edge-7690-7692",
                        Role = WaypointRole.TrapProbe,
                        Range = new PriceRange { Lower = 7690.0, Upper = 7692.5 },
                        RequirePriceInside = true,
                    },
                    new CampaignWaypoint
                    {
                        Id = "press-edge-7690-7692",
                        Role = WaypointRole.Press,
                        Range = new PriceRange { Lower = 7690.0, Upper = 7692.5 },
                        RequirePriceInside = true,
                    },
                },
            };
        private static CampaignPlan LongNoAddPlan()
            => new()
            {
                SchemaVersion = 1,
                Kind = "KAHN_CAMPAIGN",
                Id = "long-no-add-plan",
                Status = "active",
                CreatedAt = DateTimeOffset.UtcNow,
                Side = CampaignSide.Long,
                Window = Window(),
                Arena = new PriceRange { Lower = 7650.0, Upper = 7688.0 },
                Sizing = new CampaignSizing
                {
                    ProbeQuantity = 1,
                    AddQuantity = 1,
                    MaxPositionQuantity = 3,
                },
                Risk = new CampaignRisk(),
                Objective = new CampaignObjective
                {
                    TargetRange = new PriceRange { Lower = 7680.0, Upper = 7685.0 },
                    TargetProximityTicks = 8,
                },
                Policies = new CampaignPolicyFlags(),
                Waypoints = new[]
                {
                    new CampaignWaypoint
                    {
                        Id = "probe-7650-7660",
                        Role = WaypointRole.TrapProbe,
                        Range = new PriceRange { Lower = 7650.0, Upper = 7660.0 },
                    },
                    new CampaignWaypoint
                    {
                        Id = "no-add-7660-7667",
                        Role = WaypointRole.NoAdd,
                        Range = new PriceRange { Lower = 7660.0, Upper = 7667.0 },
                    },
                    new CampaignWaypoint
                    {
                        Id = "press-7667-7677",
                        Role = WaypointRole.Press,
                        Range = new PriceRange { Lower = 7667.0, Upper = 7677.0 },
                    },
                    new CampaignWaypoint
                    {
                        Id = "target-7680-7685",
                        Role = WaypointRole.Target,
                        Range = new PriceRange { Lower = 7680.0, Upper = 7685.0 },
                    },
                },
            };
        private static CampaignPlan LongEvaluatePlan()
            => new()
            {
                SchemaVersion = 1,
                Kind = "KAHN_CAMPAIGN",
                Id = "long-evaluate-plan",
                Status = "active",
                CreatedAt = DateTimeOffset.UtcNow,
                Side = CampaignSide.Long,
                Window = Window(),
                Arena = new PriceRange { Lower = 29000.0, Upper = 29260.0 },
                Sizing = new CampaignSizing
                {
                    ProbeQuantity = 1,
                    AddQuantity = 1,
                    MaxPositionQuantity = 3,
                },
                Risk = new CampaignRisk(),
                Objective = new CampaignObjective
                {
                    TargetRange = new PriceRange { Lower = 29220.0, Upper = 29245.0 },
                    TargetProximityTicks = 20,
                },
                Policies = new CampaignPolicyFlags(),
                Waypoints = new[]
                {
                    new CampaignWaypoint
                    {
                        Id = "evaluate-29150-29185",
                        Role = WaypointRole.Evaluate,
                        Range = new PriceRange { Lower = 29150.0, Upper = 29185.0 },
                    },
                },
            };

        private static CampaignPlan LongPreserveRiskPlan()
            => new()
            {
                SchemaVersion = 1,
                Kind = "KAHN_CAMPAIGN",
                Id = "long-preserve-risk-plan",
                Status = "active",
                CreatedAt = DateTimeOffset.UtcNow,
                Side = CampaignSide.Long,
                Window = Window(),
                Arena = new PriceRange { Lower = 29000.0, Upper = 29260.0 },
                Sizing = new CampaignSizing
                {
                    ProbeQuantity = 1,
                    AddQuantity = 1,
                    MaxPositionQuantity = 4,
                },
                Risk = new CampaignRisk(),
                Objective = new CampaignObjective
                {
                    TargetRange = new PriceRange { Lower = 29220.0, Upper = 29245.0 },
                    TargetProximityTicks = 20,
                },
                Policies = new CampaignPolicyFlags(),
                Waypoints = new[]
                {
                    new CampaignWaypoint
                    {
                        Id = "press-29080-29100",
                        Role = WaypointRole.Press,
                        Range = new PriceRange { Lower = 29080.0, Upper = 29100.0 },
                    },
                    new CampaignWaypoint
                    {
                        Id = "press-29100-29145",
                        Role = WaypointRole.Press,
                        Range = new PriceRange { Lower = 29100.0, Upper = 29145.0 },
                        PreserveRiskAnchorOnAdd = true,
                    },
                },
            };
        private static CampaignPlan ShortPathStressPlan()
            => new()
            {
                SchemaVersion = 1,
                Kind = "KAHN_CAMPAIGN",
                Id = "short-path-stress-plan",
                Status = "active",
                CreatedAt = DateTimeOffset.UtcNow,
                Side = CampaignSide.Short,
                Window = Window(),
                Arena = new PriceRange { Lower = 7650.0, Upper = 7705.0 },
                Sizing = new CampaignSizing
                {
                    ProbeQuantity = 1,
                    AddQuantity = 1,
                    MaxPositionQuantity = 5,
                },
                Risk = new CampaignRisk(),
                Objective = new CampaignObjective
                {
                    TargetRange = new PriceRange { Lower = 7656.0, Upper = 7660.0 },
                    TargetProximityTicks = 8,
                },
                Policies = new CampaignPolicyFlags(),
                Waypoints = new[]
                {
                    new CampaignWaypoint
                    {
                        Id = "path-stress-7664-7680",
                        Role = WaypointRole.PathStress,
                        Range = new PriceRange { Lower = 7664.0, Upper = 7680.0 },
                        MaxPositionQuantity = 1,
                    },
                },
            };
        private static CampaignPlan LongPlan(CampaignWindow window = null)
            => new()
            {
                SchemaVersion = 1,
                Kind = "KAHN_CAMPAIGN",
                Id = "long-plan",
                Status = "active",
                CreatedAt = DateTimeOffset.UtcNow,
                Side = CampaignSide.Long,
                Window = window ?? Window(),
                Arena = new PriceRange { Lower = 7660.0, Upper = 7690.0 },
                Sizing = new CampaignSizing
                {
                    ProbeQuantity = 1,
                    AddQuantity = 1,
                    MaxPositionQuantity = 4,
                },
                Risk = new CampaignRisk(),
                Objective = new CampaignObjective
                {
                    TargetRange = new PriceRange { Lower = 7680.0, Upper = 7685.0 },
                    TargetProximityTicks = 8,
                },
                Policies = new CampaignPolicyFlags(),
                Waypoints = new[]
                {
                    new CampaignWaypoint
                    {
                        Id = "press-7676",
                        Role = WaypointRole.Press,
                        Range = new PriceRange { Lower = 7675.5, Upper = 7681.0 },
                    },
                    new CampaignWaypoint
                    {
                        Id = "target-7680",
                        Role = WaypointRole.Target,
                        Range = new PriceRange { Lower = 7680.0, Upper = 7685.0 },
                    },
                },
            };

        private static CampaignWindow Window()
            => new()
            {
                NotBefore = DateTimeOffset.UtcNow.AddMinutes(-1),
                ExpiresAt = DateTimeOffset.UtcNow.AddMinutes(30),
            };

        private static CampaignWindow ExpiredWindow()
            => new()
            {
                NotBefore = DateTimeOffset.UtcNow.AddMinutes(-30),
                ExpiresAt = DateTimeOffset.UtcNow.AddMinutes(-1),
            };

        private static void Assert(bool condition, string name)
        {
            if (!condition)
                throw new InvalidOperationException($"Kahn self-test failed: {name}");
        }
        private static void ApplyProbeAndFlatten(CampaignState state,
            CampaignPlan plan,
            string token)
        {
            state.ApplyDecision(new PolicyDecision
            {
                Action = PolicyAction.AllowProbe,
                Policy = "selftest",
                ReasonCode = "probe_" + token,
                Quantity = 1,
                RiskAnchor = new PriceRange { Lower = 7673.75, Upper = 7675.25 },
                EvidenceId = "probe-" + token,
            }, plan, simulateAcceptedDecisions: true);
            state.ApplyDecision(new PolicyDecision
            {
                Action = PolicyAction.Flatten,
                Policy = "selftest",
                ReasonCode = "flatten_" + token,
                Quantity = 1,
                EvidenceId = "flatten-" + token,
            }, plan, simulateAcceptedDecisions: true);
        }

        private static void SeedPosition(CampaignState state,
            CampaignPlan plan,
            int quantity)
        {
            state.ApplyDecision(new PolicyDecision
            {
                Action = PolicyAction.AllowProbe,
                Policy = "selftest",
                ReasonCode = "seed_position",
                Quantity = quantity,
                RiskAnchor = new PriceRange { Lower = 7688.0, Upper = 7692.0 },
                EvidenceId = "seed-position",
            }, plan, simulateAcceptedDecisions: true);
        }
    }
}
