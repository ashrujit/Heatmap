using System;
using System.IO;
using System.Linq;

namespace ExecAssistantRuntime
{
    internal static class RuntimeSelfTests
    {
        public static void RunAll()
        {
            ContractTests();
            EvidenceEngineTests();
            CoordinatorTests();
        }

        private static void EvidenceEngineTests()
        {
            var engine = new ExecutionEvidenceEngine(0.25);
            DateTime start = new(2026, 6, 19, 13, 30, 0, DateTimeKind.Utc);
            for (int second = 0; second < 35; second++)
                engine.Process(Book(start.AddSeconds(second), 30000, bidSize: 1));

            bool formed = false;
            for (int second = 35; second < 38; second++)
            {
                formed |= engine.Process(Book(start.AddSeconds(second), 30000, bidSize: 20))
                    .Any(t => t.Kind == EvidenceTransitionKind.CandidateFormed
                        && t.Candidate?.Side == EvidenceSide.Demand);
            }
            Require(formed, "demand candidate formation");

            bool owned = false;
            for (int second = 38; second <= 50; second++)
            {
                owned |= engine.Process(Book(start.AddSeconds(second), 30002.25, bidSize: 1))
                    .Any(t => t.Kind == EvidenceTransitionKind.RailOwned
                        && t.Band?.Side == EvidenceSide.Demand
                        && t.Band.Source == EvidenceSource.Lean);
            }
            Require(owned, "ten-second demand ownership confirmation");

            bool failed = engine.Process(Book(start.AddSeconds(51), 29992, bidSize: 1))
                .Any(t => t.Kind == EvidenceTransitionKind.RailFailed
                    && t.Band?.Side == EvidenceSide.Demand);
            Require(failed, "demand rail failure creates grey memory safely");
        }

        private static void ContractTests()
        {
            string valid = ValidDirectiveJson();
            TradeDirective directive = DirectiveContracts.ParseTradeDirective(valid, 5);
            Require(directive.Id == "selftest-long-01", "directive id");
            Require(directive.Direction == TradeDirection.Long, "directive side");
            Require(directive.TargetMode == TargetMode.HardTp, "target mode");
            Require(directive.AllowedResolutions.Count == 2, "resolution count");

            TradeDirective whitespace = DirectiveContracts.ParseTradeDirective(
                " \r\n" + valid + " \r\n",
                5);
            Require(directive.Digest == whitespace.Digest, "canonical whitespace digest");

            ExpectInvalid(valid.Replace(
                "\"notes\": \"self test\"",
                "\"notes\": \"self test\", \"unknown\": true"),
                "unknown property");
            ExpectInvalid(valid.Replace(
                "\"add_quantity\": 1",
                "\"add_quantity\": 0"),
                "contradictory scaling");
            ExpectInvalid(valid.Replace(
                "\"max_position_quantity\": 5",
                "\"max_position_quantity\": 6"),
                "instance quantity ceiling");

            ControlCommand flat = DirectiveContracts.ParseControlCommand(
                "{\"schema_version\":1,\"kind\":\"CONTROL\","
                + "\"command_id\":\"selftest-flat\","
                + "\"issued_at\":\"2026-06-19T10:00:00-04:00\","
                + "\"action\":\"FLAT\"}");
            Require(flat.Action == ControlAction.Flat, "flat control");
        }

        private static void CoordinatorTests()
        {
            TradeDirective directive = DirectiveContracts.ParseTradeDirective(
                ValidDirectiveJson(),
                5);
            DateTime now = new(2026, 6, 19, 14, 0, 0, DateTimeKind.Utc);
            var coordinator = new ExecutionCoordinator(0.25);
            var evidence = new ExecutionEvidenceEngine(0.25);
            var market = new ExecutableMarket
            {
                TimeUtc = now,
                QuoteUtc = now,
                Bid = 30503.75,
                Ask = 30504.00,
            };
            coordinator.AcceptDirective(directive, now, Array.Empty<int>());
            coordinator.InitializeObservedPosition(RuntimePosition.Flat);

            EvidenceTransition baseTransition = ConsumedDemand(
                id: 1,
                formedUtc: now.AddSeconds(1),
                eventUtc: now.AddSeconds(12),
                lower: 30500,
                upper: 30501);
            OrderIntent baseIntent = coordinator.ProcessEvidence(
                new[] { baseTransition },
                now.AddSeconds(12),
                market,
                RuntimePosition.Flat,
                evidence).SingleOrDefault();
            Require(baseIntent?.Kind == OrderIntentKind.EnterBase, "base intent");
            Require(coordinator.ProcessEvidence(
                new[] { baseTransition },
                now.AddSeconds(13),
                market,
                RuntimePosition.Flat,
                evidence).Count == 0,
                "one attempt per epoch");

            coordinator.OnOrderAttemptResult(baseIntent, accepted: true);
            var basePosition = new RuntimePosition
            {
                PositionId = "selftest-position",
                Direction = TradeDirection.Long,
                Quantity = 2,
                AveragePrice = 30504,
            };
            OrderIntent[] protections = coordinator.OnPositionChanged(
                basePosition,
                now.AddSeconds(13),
                market).ToArray();
            Require(coordinator.State == RuntimeExecutionState.BaseOnly, "base state");
            Require(protections.Any(i => i.Kind == OrderIntentKind.EnsureHardTarget),
                "base target protection");

            EvidenceTransition staleAdd = ConsumedDemand(
                id: 2,
                formedUtc: now.AddSeconds(5),
                eventUtc: now.AddSeconds(15),
                lower: 30501,
                upper: 30502);
            Require(coordinator.ProcessEvidence(
                new[] { staleAdd },
                now.AddSeconds(15),
                market,
                basePosition,
                evidence).Count == 0,
                "add root must form after prior fill");

            EvidenceTransition freshAdd = ConsumedDemand(
                id: 3,
                formedUtc: now.AddSeconds(14),
                eventUtc: now.AddSeconds(25),
                lower: 30501,
                upper: 30502);
            OrderIntent addIntent = coordinator.ProcessEvidence(
                new[] { freshAdd },
                now.AddSeconds(25),
                market,
                basePosition,
                evidence).SingleOrDefault();
            Require(addIntent?.Kind == OrderIntentKind.Add, "fresh add intent");

            var lfCoordinator = new ExecutionCoordinator(0.25);
            lfCoordinator.AcceptDirective(directive, now, Array.Empty<int>());
            EvidenceTransition hf = new()
            {
                Kind = EvidenceTransitionKind.FailureHeld,
                TimeUtc = now.AddSeconds(30),
                CurrentMidTick = 122000,
                Band = new EvidenceBandView
                {
                    Id = 99,
                    Role = EvidenceRole.FailureZone,
                    Side = EvidenceSide.Supply,
                    State = EvidenceState.Held,
                    MinTick = 122000,
                    MaxTick = 122004,
                    FormedUtc = now.AddSeconds(20),
                    OwnedUtc = now.AddSeconds(20),
                },
            };
            OrderIntent flatten = lfCoordinator.ProcessEvidence(
                new[] { hf },
                now.AddSeconds(30),
                market,
                basePosition,
                evidence).SingleOrDefault();
            Require(flatten?.Kind == OrderIntentKind.Flatten, "HF flatten");
        }

        private static EvidenceTransition ConsumedDemand(
            int id,
            DateTime formedUtc,
            DateTime eventUtc,
            double lower,
            double upper)
            => new()
            {
                Kind = EvidenceTransitionKind.RailOwned,
                TimeUtc = eventUtc,
                CurrentMidTick = (long)Math.Round(((lower + upper) / 2.0) / 0.25),
                Band = new EvidenceBandView
                {
                    Id = id,
                    Role = EvidenceRole.Rail,
                    Side = EvidenceSide.Demand,
                    SourceSide = EvidenceSide.Supply,
                    Source = EvidenceSource.Consumed,
                    State = EvidenceState.Owned,
                    MinTick = (long)Math.Round(lower / 0.25),
                    MaxTick = (long)Math.Round(upper / 0.25),
                    FormedUtc = formedUtc,
                    OwnedUtc = eventUtc,
                    LastStateUtc = eventUtc,
                    EventCount = 3,
                    Score = 9,
                },
            };

        private static BookDepthSnapshot Book(DateTime timeUtc, double bid,
            double bidSize)
        {
            const double tick = 0.25;
            DepthLevelSnapshot[] bids = Enumerable.Range(0, 30)
                .Select(i => new DepthLevelSnapshot
                {
                    Price = bid - i * tick,
                    Size = bidSize,
                })
                .ToArray();
            DepthLevelSnapshot[] asks = Enumerable.Range(0, 30)
                .Select(i => new DepthLevelSnapshot
                {
                    Price = bid + tick + i * tick,
                    Size = 1,
                })
                .ToArray();
            return new BookDepthSnapshot
            {
                TimeUtc = timeUtc,
                BestBid = bid,
                BestAsk = bid + tick,
                Bids = bids,
                Asks = asks,
            };
        }

        private static void ExpectInvalid(string json, string label)
        {
            try
            {
                DirectiveContracts.ParseTradeDirective(json, 5);
                throw new InvalidOperationException($"Self-test expected rejection: {label}");
            }
            catch (InvalidDataException)
            {
            }
        }

        private static void Require(bool condition, string label)
        {
            if (!condition)
                throw new InvalidOperationException($"Runtime self-test failed: {label}");
        }

        private static string ValidDirectiveJson()
            => """
            {
              "schema_version": 1,
              "kind": "TRADE_DIRECTIVE",
              "id": "selftest-long-01",
              "status": "active",
              "created_at": "2026-06-19T09:55:00-04:00",
              "side": "long",
              "window": {
                "not_before": "2026-06-19T09:55:00-04:00",
                "expires_at": "2026-06-19T12:00:00-04:00"
              },
              "entry": {
                "mode": "contest_transition",
                "order_price_range": { "lower": 30000, "upper": 30900 },
                "context_price_range": { "lower": 29900, "upper": 30900 },
                "add_price_range": { "lower": 30000, "upper": 30900 },
                "pre_entry_invalidation": null,
                "allowed_resolutions": ["direct_conversion", "supported_reclaim"]
              },
              "sizing": {
                "base_quantity": 2,
                "add_quantity": 1,
                "max_position_quantity": 5,
                "adds_allowed": true
              },
              "retries": { "max_base_reentries": 3 },
              "stop": {
                "base": "reverse_entry_resolution",
                "leveraged": "weighted_breakeven",
                "opposite_failure_object": "flatten"
              },
              "target": {
                "mode": "HARD_TP",
                "price": 31000,
                "direction": "above",
                "reference": "selftest"
              },
              "notes": "self test"
            }
            """;
    }
}
