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
            BookContinuityTests();
            EvidenceEngineTests();
            CoordinatorTests();
        }

        private static void BookContinuityTests()
        {
            var tracker = new BookContinuityTracker();
            DateTime start = new(2026, 6, 22, 13, 30, 0, DateTimeKind.Utc);

            BookContinuityUpdate startup = tracker.ObserveUnusable(
                start, "l2_heartbeat_stale", confirmationSeconds: 5);
            Require(!startup.ConfirmedLoss,
                "startup warmup does not declare forward loss");

            BookContinuityUpdate firstUsable = tracker.ObserveUsable(
                start.AddSeconds(1));
            Require(!firstUsable.Recovered,
                "first usable book completes warmup without recovery event");
            BookContinuityUpdate transient = tracker.ObserveUnusable(
                start.AddSeconds(2), "l1_dom_mismatch", confirmationSeconds: 5);
            Require(transient.StartedUnusable && !transient.ConfirmedLoss,
                "first mismatch starts grace without confirming loss");
            BookContinuityUpdate transientRecovery = tracker.ObserveUsable(
                start.AddSeconds(4));
            Require(transientRecovery.Recovered
                && !transientRecovery.RecoveredAfterConfirmedLoss,
                "good sample clears transient mismatch");

            tracker.ObserveUnusable(
                start.AddSeconds(10), "dom_empty", confirmationSeconds: 5);
            BookContinuityUpdate changed = tracker.ObserveUnusable(
                start.AddSeconds(12), "l2_heartbeat_stale", confirmationSeconds: 5);
            Require(changed.ReasonChanged && !changed.ConfirmedLoss,
                "reason change preserves one continuous grace window");
            BookContinuityUpdate confirmed = tracker.ObserveUnusable(
                start.AddSeconds(15), "l2_heartbeat_stale", confirmationSeconds: 5);
            Require(confirmed.ConfirmedLoss
                && confirmed.InitialReason == "dom_empty"
                && confirmed.LatestReason == "l2_heartbeat_stale",
                "continuous unusable book confirms once after grace");
            Require(!tracker.ObserveUnusable(
                    start.AddSeconds(16), "l2_heartbeat_stale", confirmationSeconds: 5)
                    .ConfirmedLoss,
                "confirmed loss does not repeat while unusable");
            BookContinuityUpdate confirmedRecovery = tracker.ObserveUsable(
                start.AddSeconds(17));
            Require(confirmedRecovery.RecoveredAfterConfirmedLoss,
                "usable book marks confirmed-loss recovery");
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

            var consumedEngine = new ExecutionEvidenceEngine(0.25);
            for (int second = 0; second < 35; second++)
                consumedEngine.Process(Book(start.AddMinutes(2).AddSeconds(second),
                    30000, bidSize: 1, askSize: 1));

            int supplyCandidateId = 0;
            for (int second = 35; second < 38; second++)
            {
                EvidenceTransition formedSupply = consumedEngine.Process(
                        Book(start.AddMinutes(2).AddSeconds(second),
                            30000, bidSize: 1, askSize: 20))
                    .FirstOrDefault(t => t.Kind == EvidenceTransitionKind.CandidateFormed
                        && t.Candidate?.Side == EvidenceSide.Supply);
                if (formedSupply != null)
                    supplyCandidateId = formedSupply.Candidate.Id;
            }
            Require(supplyCandidateId > 0, "supply candidate formation");

            EvidenceTransition consumed = null;
            for (int second = 38; second <= 50; second++)
            {
                consumed ??= consumedEngine.Process(
                        Book(start.AddMinutes(2).AddSeconds(second),
                            30002.25, bidSize: 1, askSize: 1))
                    .FirstOrDefault(t => t.Kind == EvidenceTransitionKind.RailOwned
                        && t.Band?.Side == EvidenceSide.Demand
                        && t.Band.Source == EvidenceSource.Consumed);
            }
            Require(consumed?.Band.Id == supplyCandidateId,
                "consumed rail preserves candidate lineage id");
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
                "\"max_position_quantity\": 2"),
                "scaling without capacity for one add");
            string disabledWithExcessMaximum = valid
                .Replace(
                    "\"add_price_range\": { \"lower\": 30000, \"upper\": 30900 }",
                    "\"add_price_range\": null")
                .Replace("\"add_quantity\": 1", "\"add_quantity\": 0")
                .Replace("\"adds_allowed\": true", "\"adds_allowed\": false");
            ExpectInvalid(disabledWithExcessMaximum,
                "disabled scaling maximum differs from base");
            ExpectInvalid(valid.Replace(
                "\"max_position_quantity\": 5",
                "\"max_position_quantity\": 6"),
                "instance quantity ceiling");
            ExpectInvalid(valid.Replace(
                "\"add_price_range\": { \"lower\": 30000, \"upper\": 30900 }",
                "\"add_price_range\": { \"lower\": 29800, \"upper\": 30900 }"),
                "add range outside context");
            foreach (string legacyMode in new[]
            {
                "TARGET_DECISION",
                "TRAIL_AFTER_TARGET",
                "TARGET_DECISION_BEFORE_EXTREME",
            })
            {
                ExpectInvalid(valid.Replace(
                    "\"mode\": \"HARD_TP\"",
                    $"\"mode\": \"{legacyMode}\""),
                    $"legacy target mode {legacyMode}");
            }

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
            Require(coordinator.CurrentSponsor?.ObjectId == 1,
                "filled entry initializes sponsor from causal support");

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

            var flatHfCoordinator = new ExecutionCoordinator(0.25);
            flatHfCoordinator.AcceptDirective(directive, now, Array.Empty<int>());
            OrderIntent flatHf = flatHfCoordinator.ProcessEvidence(
                new[] { hf },
                now.AddSeconds(30),
                market,
                RuntimePosition.Flat,
                evidence).SingleOrDefault();
            Require(flatHf?.Kind == OrderIntentKind.CancelRuntimeOrders,
                "HF while flat cancels runtime entry orders without a close request");
            Require(flatHfCoordinator.State == RuntimeExecutionState.Invalidated,
                "HF while flat invalidates directive");

            SponsorTests(directive, now, market, evidence);
            ShortSponsorTests(now, market, evidence);

            var candidateEntry = new ResolutionContext { SupportObjectId = 77 };
            var consumedOpposite = new EvidenceBandView
            {
                Id = 77,
                Side = EvidenceSide.Supply,
                Source = EvidenceSource.Consumed,
            };
            Require(ExecutionCoordinator.IsCandidateSupportConsumed(
                    candidateEntry, consumedOpposite),
                "candidate-backed reclaim immediate reverse lineage");
            Require(!ExecutionCoordinator.PendingIntentMatchesState(
                    true,
                    RuntimeExecutionState.Armed,
                    RuntimePosition.Flat),
                "pending add is invalid after base position becomes flat");

            var retryCoordinator = new ExecutionCoordinator(0.25);
            retryCoordinator.AcceptDirective(directive, now, Array.Empty<int>());
            for (int attempt = 0; attempt <= directive.MaxBaseReentries; attempt++)
            {
                DateTime triggerUtc = now.AddSeconds(20 + attempt * 10);
                EvidenceTransition retryTransition = ConsumedDemand(
                    id: 200 + attempt,
                    formedUtc: triggerUtc.AddSeconds(-1),
                    eventUtc: triggerUtc,
                    lower: 30500,
                    upper: 30501);
                OrderIntent retry = retryCoordinator.ProcessEvidence(
                    new[] { retryTransition },
                    triggerUtc,
                    market,
                    RuntimePosition.Flat,
                    evidence).SingleOrDefault();
                Require(retry?.Kind == OrderIntentKind.EnterBase,
                    $"base submit attempt {attempt + 1}");
                retryCoordinator.OnOrderAttemptResult(retry, accepted: false);
            }
            Require(retryCoordinator.State == RuntimeExecutionState.Completed,
                "submitted base attempts exhaust retry allowance");
        }

        private static void SponsorTests(
            TradeDirective directive,
            DateTime now,
            ExecutableMarket market,
            ExecutionEvidenceEngine evidence)
        {
            var coordinator = new ExecutionCoordinator(0.25);
            coordinator.AcceptDirective(directive, now, Array.Empty<int>());
            coordinator.InitializeObservedPosition(RuntimePosition.Flat);

            OrderIntent entry = coordinator.ProcessEvidence(
                new[]
                {
                    ConsumedDemand(500, now.AddSeconds(1), now.AddSeconds(12),
                        30500, 30501),
                },
                now.AddSeconds(12),
                market,
                RuntimePosition.Flat,
                evidence).Single();
            coordinator.OnOrderAttemptResult(entry, accepted: true);
            var basePosition = new RuntimePosition
            {
                PositionId = "sponsor-selftest",
                Direction = TradeDirection.Long,
                Quantity = 2,
                AveragePrice = 30504,
            };
            coordinator.OnPositionChanged(basePosition, now.AddSeconds(13), market);
            Require(coordinator.CurrentSponsor?.ObjectId == 500,
                "initial sponsor identity");

            EvidenceTransition overlap = RailTransition(
                EvidenceTransitionKind.RailOwned,
                id: 501,
                side: EvidenceSide.Demand,
                source: EvidenceSource.Lean,
                formedUtc: now.AddSeconds(14),
                eventUtc: now.AddSeconds(25),
                lower: 30500.50,
                upper: 30501.50);
            Require(coordinator.ProcessEvidence(
                    new[] { overlap }, now.AddSeconds(25), market, basePosition, evidence)
                    .Count == 0,
                "overlapping same-side ownership is not an order trigger");
            Require(coordinator.CurrentSponsor?.ObjectId == 500,
                "overlapping rail cannot promote sponsor");

            EvidenceTransition advancing = ConsumedDemand(
                id: 502,
                formedUtc: now.AddSeconds(26),
                eventUtc: now.AddSeconds(38),
                lower: 30506,
                upper: 30507);
            OrderIntent add = coordinator.ProcessEvidence(
                new[] { advancing }, now.AddSeconds(38), market, basePosition, evidence)
                .SingleOrDefault();
            Require(add?.Kind == OrderIntentKind.Add,
                "fresh favorable conversion adds");
            Require(coordinator.CurrentSponsor?.ObjectId == 502,
                "fresh non-overlapping ownership promotes sponsor");

            coordinator.OnOrderAttemptResult(add, accepted: true);
            var leveragedPosition = new RuntimePosition
            {
                PositionId = "sponsor-selftest",
                Direction = TradeDirection.Long,
                Quantity = 3,
                AveragePrice = 30504.50,
            };
            coordinator.OnPositionChanged(
                leveragedPosition, now.AddSeconds(39), market);
            Require(coordinator.State == RuntimeExecutionState.Leveraged,
                "sponsor test leveraged state");

            EvidenceTransition tested = RailTransition(
                EvidenceTransitionKind.RailTested,
                502,
                EvidenceSide.Demand,
                EvidenceSource.Consumed,
                now.AddSeconds(26),
                now.AddSeconds(40),
                30506,
                30507);
            EvidenceTransition held = RailTransition(
                EvidenceTransitionKind.RailHeld,
                502,
                EvidenceSide.Demand,
                EvidenceSource.Consumed,
                now.AddSeconds(26),
                now.AddSeconds(41),
                30506,
                30507);
            Require(coordinator.ProcessEvidence(
                    new[] { tested, held }, now.AddSeconds(41), market,
                    leveragedPosition, evidence).Count == 0,
                "sponsor tests and holds do not flatten");

            EvidenceTransition oldFailure = RailTransition(
                EvidenceTransitionKind.RailFailed,
                500,
                EvidenceSide.Demand,
                EvidenceSource.Consumed,
                now.AddSeconds(1),
                now.AddSeconds(42),
                30500,
                30501);
            Require(coordinator.ProcessEvidence(
                    new[] { oldFailure }, now.AddSeconds(42), market,
                    leveragedPosition, evidence).Count == 0,
                "older sponsor failure cannot override promoted sponsor");

            EvidenceTransition currentFailure = RailTransition(
                EvidenceTransitionKind.RailFailed,
                502,
                EvidenceSide.Demand,
                EvidenceSource.Consumed,
                now.AddSeconds(26),
                now.AddSeconds(43),
                30506,
                30507);
            OrderIntent flatten = coordinator.ProcessEvidence(
                new[] { currentFailure }, now.AddSeconds(43), market,
                leveragedPosition, evidence).SingleOrDefault();
            Require(flatten?.Kind == OrderIntentKind.Flatten
                    && flatten.TerminalAfterFlat
                    && flatten.Reason == "sponsor_failed:502",
                "current sponsor failure terminally flattens leveraged campaign");

            int promotedVersion = coordinator.SponsorVersion;
            coordinator.OnPositionChanged(
                RuntimePosition.Flat, now.AddSeconds(44), market);
            Require(coordinator.CurrentSponsor == null,
                "flat position clears current sponsor");
            Require(coordinator.SponsorVersion == promotedVersion + 1,
                "sponsor clearance advances telemetry version");
            Require(coordinator.LastSponsorClear?.Sponsor?.ObjectId == 502
                    && coordinator.LastSponsorClear.FlattenReason == "sponsor_failed:502"
                    && coordinator.LastSponsorClear.ClearedUtc == now.AddSeconds(44),
                "sponsor clearance preserves sponsor lineage and flatten reason");
            coordinator.OnPositionChanged(
                RuntimePosition.Flat, now.AddSeconds(45), market);
            Require(coordinator.SponsorVersion == promotedVersion + 1,
                "repeated flat reconciliation does not duplicate sponsor clearance");
        }

        private static void ShortSponsorTests(
            DateTime now,
            ExecutableMarket market,
            ExecutionEvidenceEngine evidence)
        {
            string shortJson = ValidDirectiveJson()
                .Replace("selftest-long-01", "selftest-short-01")
                .Replace("\"side\": \"long\"", "\"side\": \"short\"")
                .Replace("\"price\": 31000", "\"price\": 29900")
                .Replace("\"direction\": \"above\"", "\"direction\": \"below\"");
            TradeDirective directive = DirectiveContracts.ParseTradeDirective(shortJson, 5);
            var coordinator = new ExecutionCoordinator(0.25);
            coordinator.AcceptDirective(directive, now, Array.Empty<int>());
            coordinator.InitializeObservedPosition(RuntimePosition.Flat);

            EvidenceTransition initial = RailTransition(
                EvidenceTransitionKind.RailOwned,
                600,
                EvidenceSide.Supply,
                EvidenceSource.Consumed,
                now.AddSeconds(1),
                now.AddSeconds(12),
                30508,
                30509);
            OrderIntent entry = coordinator.ProcessEvidence(
                new[] { initial }, now.AddSeconds(12), market,
                RuntimePosition.Flat, evidence).Single();
            coordinator.OnOrderAttemptResult(entry, accepted: true);
            var basePosition = new RuntimePosition
            {
                PositionId = "short-sponsor-selftest",
                Direction = TradeDirection.Short,
                Quantity = 2,
                AveragePrice = 30503.75,
            };
            coordinator.OnPositionChanged(basePosition, now.AddSeconds(13), market);
            Require(coordinator.CurrentSponsor?.ObjectId == 600,
                "short initial sponsor identity");

            EvidenceTransition advancing = RailTransition(
                EvidenceTransitionKind.RailOwned,
                601,
                EvidenceSide.Supply,
                EvidenceSource.Consumed,
                now.AddSeconds(14),
                now.AddSeconds(25),
                30500,
                30501);
            OrderIntent add = coordinator.ProcessEvidence(
                new[] { advancing }, now.AddSeconds(25), market,
                basePosition, evidence).SingleOrDefault();
            Require(add?.Kind == OrderIntentKind.Add
                    && coordinator.CurrentSponsor?.ObjectId == 601,
                "lower supply promotes short sponsor and adds");
            coordinator.OnOrderAttemptResult(add, accepted: true);
            var leveragedPosition = new RuntimePosition
            {
                PositionId = "short-sponsor-selftest",
                Direction = TradeDirection.Short,
                Quantity = 3,
                AveragePrice = 30503,
            };
            coordinator.OnPositionChanged(
                leveragedPosition, now.AddSeconds(26), market);

            EvidenceTransition oldFailure = RailTransition(
                EvidenceTransitionKind.RailFailed,
                600,
                EvidenceSide.Supply,
                EvidenceSource.Consumed,
                now.AddSeconds(1),
                now.AddSeconds(27),
                30508,
                30509);
            Require(coordinator.ProcessEvidence(
                    new[] { oldFailure }, now.AddSeconds(27), market,
                    leveragedPosition, evidence).Count == 0,
                "short old sponsor failure ignored after promotion");

            EvidenceTransition currentFailure = RailTransition(
                EvidenceTransitionKind.RailFailed,
                601,
                EvidenceSide.Supply,
                EvidenceSource.Consumed,
                now.AddSeconds(14),
                now.AddSeconds(28),
                30500,
                30501);
            OrderIntent flatten = coordinator.ProcessEvidence(
                new[] { currentFailure }, now.AddSeconds(28), market,
                leveragedPosition, evidence).SingleOrDefault();
            Require(flatten?.Kind == OrderIntentKind.Flatten
                    && flatten.TerminalAfterFlat
                    && flatten.Reason == "sponsor_failed:601",
                "current short sponsor failure terminally flattens campaign");
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
                CurrentMidTick = (long)Math.Round(upper / 0.25) + 9,
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

        private static EvidenceTransition RailTransition(
            EvidenceTransitionKind kind,
            int id,
            EvidenceSide side,
            EvidenceSource source,
            DateTime formedUtc,
            DateTime eventUtc,
            double lower,
            double upper)
        {
            long minTick = (long)Math.Round(lower / 0.25);
            long maxTick = (long)Math.Round(upper / 0.25);
            long currentMidTick = side == EvidenceSide.Demand
                ? maxTick + 9
                : minTick - 9;
            return new EvidenceTransition
            {
                Kind = kind,
                TimeUtc = eventUtc,
                CurrentMidTick = currentMidTick,
                Band = new EvidenceBandView
                {
                    Id = id,
                    Role = EvidenceRole.Rail,
                    Side = side,
                    SourceSide = side == EvidenceSide.Demand
                        ? EvidenceSide.Supply
                        : EvidenceSide.Demand,
                    Source = source,
                    State = kind switch
                    {
                        EvidenceTransitionKind.RailTested => EvidenceState.Tested,
                        EvidenceTransitionKind.RailHeld => EvidenceState.Held,
                        EvidenceTransitionKind.RailFailed => EvidenceState.Failed,
                        _ => EvidenceState.Owned,
                    },
                    MinTick = minTick,
                    MaxTick = maxTick,
                    FormedUtc = formedUtc,
                    OwnedUtc = eventUtc,
                    LastStateUtc = eventUtc,
                    FailedUtc = kind == EvidenceTransitionKind.RailFailed
                        ? eventUtc
                        : null,
                    EventCount = 3,
                    Score = 9,
                },
            };
        }

        private static BookDepthSnapshot Book(DateTime timeUtc, double bid,
            double bidSize, double askSize = 1)
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
                    Size = askSize,
                })
                .ToArray();
            return new BookDepthSnapshot
            {
                TimeUtc = timeUtc,
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
