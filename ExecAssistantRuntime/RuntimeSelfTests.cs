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
            Require(directive.Lineage?.Mode == DirectiveLineageMode.New,
                "default directive lineage is NEW");
            string continuationJson = valid.Replace(
                "\"notes\": \"self test\"",
                "\"lineage\": { \"mode\": \"CONTINUE\", "
                + "\"parent_directive_id\": \"selftest-parent-01\" }, "
                + "\"notes\": \"self test\"");
            TradeDirective continuation = DirectiveContracts.ParseTradeDirective(
                continuationJson,
                5);
            Require(continuation.Lineage.IsContinuation
                    && continuation.Lineage.ParentDirectiveId == "selftest-parent-01",
                "continuation lineage parses parent id");
            ExpectInvalid(valid.Replace(
                    "\"notes\": \"self test\"",
                    "\"lineage\": { \"mode\": \"CONTINUE\" }, \"notes\": \"self test\""),
                "continuation requires parent id");
            ExpectInvalid(valid.Replace(
                    "\"notes\": \"self test\"",
                    "\"lineage\": { \"mode\": \"NEW\", "
                    + "\"parent_directive_id\": \"selftest-parent-01\" }, "
                    + "\"notes\": \"self test\""),
                "NEW lineage rejects parent id");
            string legacyStop = valid.Replace(
                "\"leveraged\": \"current_sponsor_failure\"",
                "\"leveraged\": \"weighted_breakeven\"");
            ExpectInvalid(legacyStop, "legacy leveraged stop grammar");
            TradeDirective legacyRecovery = DirectiveContracts.ParseTradeDirective(
                legacyStop,
                5,
                allowLegacyWeightedBreakeven: true);
            Require(legacyRecovery.Id == directive.Id,
                "legacy leveraged stop grammar remains recovery-readable");

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

            TradeDirective addAfterExpiryDirective = DirectiveContracts.ParseTradeDirective(
                ValidDirectiveJson()
                    .Replace("\"id\": \"selftest-long-01\"",
                        "\"id\": \"selftest-add-after-expiry-01\"")
                    .Replace("\"expires_at\": \"2026-06-19T12:00:00-04:00\"",
                        "\"expires_at\": \"2026-06-19T10:00:20-04:00\""),
                5);
            var addAfterExpiry = new ExecutionCoordinator(0.25);
            addAfterExpiry.AcceptDirective(
                addAfterExpiryDirective, now, Array.Empty<int>());
            OrderIntent expiringBase = addAfterExpiry.ProcessEvidence(
                new[] { baseTransition },
                now.AddSeconds(12),
                market,
                RuntimePosition.Flat,
                evidence).SingleOrDefault();
            Require(expiringBase?.Kind == OrderIntentKind.EnterBase,
                "base may enter before directive expiry");
            addAfterExpiry.OnOrderAttemptResult(expiringBase, accepted: true);
            addAfterExpiry.OnPositionChanged(basePosition, now.AddSeconds(13), market);
            OrderIntent postExpiryAdd = addAfterExpiry.ProcessEvidence(
                new[] { freshAdd },
                now.AddSeconds(25),
                market,
                basePosition,
                evidence).SingleOrDefault();
            Require(postExpiryAdd?.Kind == OrderIntentKind.Add,
                "directive expiry does not block fresh adds after base fill");

            var lfCoordinator = new ExecutionCoordinator(0.25);
            lfCoordinator.AcceptDirective(directive, now, Array.Empty<int>());
            OrderIntent lfBase = lfCoordinator.ProcessEvidence(
                new[] { baseTransition },
                now.AddSeconds(12),
                market,
                RuntimePosition.Flat,
                evidence).Single();
            lfCoordinator.OnOrderAttemptResult(lfBase, accepted: true);
            lfCoordinator.OnPositionChanged(basePosition, now.AddSeconds(13), market);
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
            Require(lfCoordinator.ProcessEvidence(
                new[] { hf },
                now.AddSeconds(30),
                market,
                basePosition,
                evidence).Count == 0,
                "local HF does not flatten while causal sponsor remains owned");
            Require(lfCoordinator.State == RuntimeExecutionState.BaseOnly
                    && lfCoordinator.CurrentSponsor?.ObjectId == 1,
                "local HF preserves campaign state and sponsor");

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
            Require(flatHf?.Reason == "HF_pause_while_flat"
                    && flatHfCoordinator.State == RuntimeExecutionState.Paused,
                "HF while flat pauses rather than invalidates directive");

            EvidenceTransition blockedEntry = ConsumedDemand(
                id: 100,
                formedUtc: now.AddSeconds(31),
                eventUtc: now.AddSeconds(40),
                lower: 30500,
                upper: 30501);
            Require(flatHfCoordinator.ProcessEvidence(
                    new[] { blockedEntry }, now.AddSeconds(40), market,
                    RuntimePosition.Flat, evidence).Count == 0,
                "paused HF state blocks otherwise eligible entry");

            EvidenceTransition hfInvalidated = new()
            {
                Kind = EvidenceTransitionKind.FailureInvalidated,
                TimeUtc = now.AddSeconds(41),
                CurrentMidTick = 122040,
                Band = new EvidenceBandView
                {
                    Id = 99,
                    Role = EvidenceRole.FailureZone,
                    Side = EvidenceSide.Supply,
                    State = EvidenceState.Removed,
                    MinTick = 122000,
                    MaxTick = 122004,
                    FormedUtc = now.AddSeconds(20),
                    OwnedUtc = now.AddSeconds(20),
                },
            };
            Require(flatHfCoordinator.ProcessEvidence(
                    new[] { hfInvalidated }, now.AddSeconds(41), market,
                    RuntimePosition.Flat, evidence).Count == 0
                    && flatHfCoordinator.State == RuntimeExecutionState.Armed,
                "invalidated HF clears flat entry pause");

            EvidenceTransition resumedEntry = ConsumedDemand(
                id: 101,
                formedUtc: now.AddSeconds(42),
                eventUtc: now.AddSeconds(52),
                lower: 30500,
                upper: 30501);
            Require(flatHfCoordinator.ProcessEvidence(
                    new[] { resumedEntry }, now.AddSeconds(52), market,
                    RuntimePosition.Flat, evidence).SingleOrDefault()?.Kind
                    == OrderIntentKind.EnterBase,
                "entry resumes from fresh evidence after HF invalidation");

            var baselineHfCoordinator = new ExecutionCoordinator(0.25);
            baselineHfCoordinator.AcceptDirective(directive, now, new[] { 99 });
            Require(baselineHfCoordinator.ProcessEvidence(
                    new[] { hf }, now.AddSeconds(30), market,
                    RuntimePosition.Flat, evidence).Count == 0
                    && baselineHfCoordinator.State == RuntimeExecutionState.Armed,
                "held HF baselined at activation remains context only");

            EvidenceTransition baseSponsorFailure = RailTransition(
                EvidenceTransitionKind.RailFailed,
                1,
                EvidenceSide.Demand,
                EvidenceSource.Consumed,
                now.AddSeconds(1),
                now.AddSeconds(25),
                30500,
                30501);
            var alignedAfterFlat = new ExecutionCoordinator(0.25);
            alignedAfterFlat.AcceptDirective(directive, now, Array.Empty<int>());
            OrderIntent alignedBase = alignedAfterFlat.ProcessEvidence(
                new[] { baseTransition }, now.AddSeconds(12), market,
                RuntimePosition.Flat, evidence).Single();
            alignedAfterFlat.OnOrderAttemptResult(alignedBase, accepted: true);
            alignedAfterFlat.OnPositionChanged(basePosition, now.AddSeconds(13), market);
            OrderIntent retryableSponsorExit = alignedAfterFlat.ProcessEvidence(
                new[] { baseSponsorFailure }, now.AddSeconds(25), market,
                basePosition, evidence).Single();
            Require(retryableSponsorExit.Kind == OrderIntentKind.Flatten
                    && !retryableSponsorExit.TerminalAfterFlat
                    && retryableSponsorExit.RearmAfterFlat,
                "base sponsor failure remains retryable before aligned HF");
            alignedAfterFlat.OnPositionChanged(
                RuntimePosition.Flat, now.AddSeconds(26), market);
            Require(alignedAfterFlat.State == RuntimeExecutionState.Armed,
                "base sponsor failure rearms while no aligned HF is held");
            OrderIntent alignedTerminal = alignedAfterFlat.ProcessEvidence(
                new[] { hf }, now.AddSeconds(30), market,
                RuntimePosition.Flat, evidence).Single();
            Require(alignedTerminal.Kind == OrderIntentKind.CancelRuntimeOrders
                    && alignedTerminal.Reason == "HF_sponsor_failed_while_flat"
                    && alignedAfterFlat.State == RuntimeExecutionState.Invalidated,
                "HF becomes terminal when the causal sponsor already failed");

            var alignedSameBatch = new ExecutionCoordinator(0.25);
            alignedSameBatch.AcceptDirective(directive, now, Array.Empty<int>());
            OrderIntent sameBatchBase = alignedSameBatch.ProcessEvidence(
                new[] { baseTransition }, now.AddSeconds(12), market,
                RuntimePosition.Flat, evidence).Single();
            alignedSameBatch.OnOrderAttemptResult(sameBatchBase, accepted: true);
            alignedSameBatch.OnPositionChanged(basePosition, now.AddSeconds(13), market);
            OrderIntent sameBatchTerminal = alignedSameBatch.ProcessEvidence(
                new[] { hf, baseSponsorFailure }, now.AddSeconds(30), market,
                basePosition, evidence).Single();
            Require(sameBatchTerminal.Kind == OrderIntentKind.Flatten
                    && sameBatchTerminal.TerminalAfterFlat
                    && !sameBatchTerminal.RearmAfterFlat,
                "same-batch HF plus current-sponsor failure is terminal");

            SponsorTests(directive, now, market, evidence);
            ShortSponsorTests(now, market, evidence);
            FailureAssistedEntryTests(directive, now, evidence);
            ContinuationTests(directive, now, market, evidence);
            StaleDirectRetestTests(directive, now);

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
            Require(!ExecutionCoordinator.PendingIntentMatchesState(
                    false,
                    RuntimeExecutionState.BaseOnly,
                    basePosition),
                "pending base is invalid after base entry fills");

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

        private static void StaleDirectRetestTests(
            TradeDirective directive,
            DateTime now)
        {
            var coordinator = new ExecutionCoordinator(0.25);
            var evidence = new ExecutionEvidenceEngine(0.25);
            DateTime seedUtc = now.AddMinutes(5);
            EvidenceTransition pendingRoot = BuildConsumedDemandRail(
                evidence, seedUtc, 30000);
            var farMarket = new ExecutableMarket
            {
                TimeUtc = pendingRoot.TimeUtc,
                QuoteUtc = pendingRoot.TimeUtc,
                Bid = 30503.75,
                Ask = 30504.00,
            };
            coordinator.AcceptDirective(directive, now, Array.Empty<int>());
            coordinator.InitializeObservedPosition(RuntimePosition.Flat);
            Require(coordinator.ProcessEvidence(
                    new[] { pendingRoot },
                    pendingRoot.TimeUtc,
                    farMarket,
                    RuntimePosition.Flat,
                    evidence).Count == 0,
                "distant direct conversion waits for retest");

            EvidenceTransition separateBase = ConsumedDemand(
                id: 9001,
                formedUtc: pendingRoot.TimeUtc.AddSeconds(1),
                eventUtc: pendingRoot.TimeUtc.AddSeconds(12),
                lower: 30500,
                upper: 30501);
            OrderIntent baseIntent = coordinator.ProcessEvidence(
                new[] { separateBase },
                separateBase.TimeUtc,
                farMarket,
                RuntimePosition.Flat,
                evidence).SingleOrDefault();
            Require(baseIntent?.Kind == OrderIntentKind.EnterBase,
                "separate base can fill while direct retest is pending");
            coordinator.OnOrderAttemptResult(baseIntent, accepted: true);
            var basePosition = new RuntimePosition
            {
                PositionId = "stale-direct-retest-selftest",
                Direction = TradeDirection.Long,
                Quantity = 2,
                AveragePrice = 30504,
            };
            coordinator.OnPositionChanged(
                basePosition,
                separateBase.TimeUtc.AddSeconds(1),
                farMarket);

            var retestMarket = new ExecutableMarket
            {
                TimeUtc = separateBase.TimeUtc.AddSeconds(2),
                QuoteUtc = separateBase.TimeUtc.AddSeconds(2),
                Bid = 30000.25,
                Ask = 30000.50,
            };
            Require(coordinator.Tick(
                    retestMarket.TimeUtc,
                    retestMarket,
                    basePosition,
                    evidence).Count == 0,
                "flat direct retest is stale after base fill");
        }

        private static void FailureAssistedEntryTests(
            TradeDirective directive,
            DateTime now,
            ExecutionEvidenceEngine evidence)
        {
            var coordinator = new ExecutionCoordinator(0.25);
            coordinator.AcceptDirective(directive, now, Array.Empty<int>());
            coordinator.InitializeObservedPosition(RuntimePosition.Flat);

            EvidenceTransition parentLf = FailureTransition(
                EvidenceTransitionKind.FailureHeld,
                810,
                EvidenceSide.Demand,
                now.AddSeconds(10),
                30500,
                30505);
            Require(coordinator.ProcessEvidence(
                    new[] { parentLf },
                    now.AddSeconds(10),
                    Market(now.AddSeconds(10), 30508, 30508.25),
                    RuntimePosition.Flat,
                    evidence).Count == 0,
                "favorable LF is context, not an entry");
            Require(coordinator.DrainAuditEvents()
                    .Any(e => e.EventType == "failure_parent_armed"
                        && e.ParentObjectId == 810),
                "favorable LF arms assisted-entry parent");

            EvidenceTransition childDemand = RailTransition(
                EvidenceTransitionKind.RailOwned,
                811,
                EvidenceSide.Demand,
                EvidenceSource.Lean,
                now.AddSeconds(20),
                now.AddSeconds(31),
                30510,
                30511);
            OrderIntent entry = coordinator.ProcessEvidence(
                new[] { childDemand },
                now.AddSeconds(31),
                Market(now.AddSeconds(31), 30509.75, 30510),
                RuntimePosition.Flat,
                evidence).SingleOrDefault();
            Require(entry?.Kind == OrderIntentKind.EnterBase
                    && entry.Reason == "failure_parent_child_direct"
                    && entry.Resolution.FailureAssisted
                    && entry.Resolution.FailureParentObjectId == 810
                    && entry.Resolution.SupportObjectId == 811,
                "LF-assisted lean demand child authorizes base entry");
            CoordinatorAuditEvent[] childAudits = coordinator.DrainAuditEvents().ToArray();
            Require(childAudits.Any(e => e.EventType == "failure_parent_child_selected"
                    && e.ChildObjectId == 811)
                && childAudits.Any(e => e.EventType == "failure_parent_entry"
                    && e.ChildObjectId == 811),
                "LF-assisted child selection and entry are audited");

            coordinator.OnOrderAttemptResult(entry, accepted: true);
            var basePosition = new RuntimePosition
            {
                PositionId = "failure-assisted-selftest",
                Direction = TradeDirection.Long,
                Quantity = 2,
                AveragePrice = 30510,
            };
            coordinator.OnPositionChanged(basePosition, now.AddSeconds(32),
                Market(now.AddSeconds(32), 30510, 30510.25));
            Require(coordinator.CurrentSponsor?.ObjectId == 811,
                "LF-assisted child becomes filled sponsor");

            OrderIntent flatten = coordinator.ProcessEvidence(
                new[]
                {
                    RailTransition(EvidenceTransitionKind.RailFailed,
                        811,
                        EvidenceSide.Demand,
                        EvidenceSource.Lean,
                        now.AddSeconds(20),
                        now.AddSeconds(45),
                        30510,
                        30511),
                },
                now.AddSeconds(45),
                Market(now.AddSeconds(45), 30508, 30508.25),
                basePosition,
                evidence).SingleOrDefault();
            Require(flatten?.Kind == OrderIntentKind.Flatten
                    && flatten.RearmAfterFlat
                    && !flatten.TerminalAfterFlat
                    && flatten.Reason == "failure_parent_child_failed:811",
                "LF-assisted base child failure flattens and rearms");
            Require(coordinator.DrainAuditEvents()
                    .Any(e => e.EventType == "failure_parent_child_failed"
                        && e.ChildObjectId == 811),
                "LF-assisted child failure is audited");

            var disabled = new ExecutionCoordinator(
                0.25,
                failureAssistedEntriesEnabled: false);
            disabled.AcceptDirective(directive, now, Array.Empty<int>());
            disabled.InitializeObservedPosition(RuntimePosition.Flat);
            Require(disabled.ProcessEvidence(
                    new[] { parentLf },
                    now.AddSeconds(10),
                    Market(now.AddSeconds(10), 30508, 30508.25),
                    RuntimePosition.Flat,
                    evidence).Count == 0
                    && disabled.DrainAuditEvents().Count == 0,
                "disabled LF-assisted setting ignores favorable LF parent");
            Require(disabled.ProcessEvidence(
                    new[] { childDemand },
                    now.AddSeconds(31),
                    Market(now.AddSeconds(31), 30509.75, 30510),
                    RuntimePosition.Flat,
                    evidence).Count == 0,
                "disabled LF-assisted setting does not enter lean child");

            string shortJson = ValidDirectiveJson()
                .Replace("selftest-long-01", "selftest-short-assisted-01")
                .Replace("\"side\": \"long\"", "\"side\": \"short\"")
                .Replace("\"price\": 31000", "\"price\": 29900")
                .Replace("\"direction\": \"above\"", "\"direction\": \"below\"");
            TradeDirective shortDirective = DirectiveContracts.ParseTradeDirective(
                shortJson,
                5);
            var shortCoordinator = new ExecutionCoordinator(0.25);
            shortCoordinator.AcceptDirective(shortDirective, now, Array.Empty<int>());
            shortCoordinator.InitializeObservedPosition(RuntimePosition.Flat);
            shortCoordinator.ProcessEvidence(
                new[]
                {
                    FailureTransition(EvidenceTransitionKind.FailureHeld,
                        820,
                        EvidenceSide.Supply,
                        now.AddSeconds(10),
                        30500,
                        30505),
                },
                now.AddSeconds(10),
                Market(now.AddSeconds(10), 30495, 30495.25),
                RuntimePosition.Flat,
                evidence);
            OrderIntent shortEntry = shortCoordinator.ProcessEvidence(
                new[]
                {
                    RailTransition(EvidenceTransitionKind.RailOwned,
                        821,
                        EvidenceSide.Supply,
                        EvidenceSource.Lean,
                        now.AddSeconds(20),
                        now.AddSeconds(31),
                        30490,
                        30491),
                },
                now.AddSeconds(31),
                Market(now.AddSeconds(31), 30491, 30491.25),
                RuntimePosition.Flat,
                evidence).SingleOrDefault();
            Require(shortEntry?.Kind == OrderIntentKind.EnterBase
                    && shortEntry.Reason == "failure_parent_child_direct"
                    && shortEntry.Resolution.FailureAssisted
                    && shortEntry.Resolution.FailureParentObjectId == 820,
                "HF-assisted lean supply child authorizes short base entry");
        }

        private static void ContinuationTests(
            TradeDirective directive,
            DateTime now,
            ExecutableMarket market,
            ExecutionEvidenceEngine evidence)
        {
            string continuationJson = ValidDirectiveJson()
                .Replace("selftest-long-01", "selftest-long-continue-01")
                .Replace(
                    "\"notes\": \"self test\"",
                    "\"lineage\": { \"mode\": \"CONTINUE\", "
                    + "\"parent_directive_id\": \"selftest-long-01\" }, "
                    + "\"notes\": \"self test\"");
            TradeDirective child = DirectiveContracts.ParseTradeDirective(
                continuationJson,
                5);

            var noClear = new ExecutionCoordinator(0.25);
            noClear.AcceptDirective(directive, now, Array.Empty<int>());
            Require(!noClear.TryPrepareContinuation(child, out _, out string noClearReason)
                    && noClearReason == "continuation_parent_has_no_protective_clear",
                "CONTINUE requires a protective parent clear");

            string expiringParentJson = ValidDirectiveJson()
                .Replace("\"id\": \"selftest-long-01\"",
                    "\"id\": \"selftest-long-expire-01\"")
                .Replace("\"expires_at\": \"2026-06-19T12:00:00-04:00\"",
                    "\"expires_at\": \"2026-06-19T10:01:00-04:00\"");
            TradeDirective expiringParentDirective =
                DirectiveContracts.ParseTradeDirective(expiringParentJson, 5);
            string expiredContinuationJson = expiringParentJson
                .Replace("\"id\": \"selftest-long-expire-01\"",
                    "\"id\": \"selftest-long-expire-continue-01\"")
                .Replace("\"expires_at\": \"2026-06-19T10:01:00-04:00\"",
                    "\"expires_at\": \"2026-06-19T10:30:00-04:00\"")
                .Replace(
                    "\"notes\": \"self test\"",
                    "\"lineage\": { \"mode\": \"CONTINUE\", "
                    + "\"parent_directive_id\": \"selftest-long-expire-01\" }, "
                    + "\"notes\": \"self test\"");
            TradeDirective expiredChild = DirectiveContracts.ParseTradeDirective(
                expiredContinuationJson,
                5);
            DateTime expireAcceptUtc = new(2026, 6, 19, 14, 0, 0, DateTimeKind.Utc);
            var expiredParent = new ExecutionCoordinator(0.25);
            expiredParent.AcceptDirective(
                expiringParentDirective,
                expireAcceptUtc,
                Array.Empty<int>());
            expiredParent.Tick(
                expireAcceptUtc.AddSeconds(61),
                Market(expireAcceptUtc.AddSeconds(61), 30503.75, 30504),
                RuntimePosition.Flat,
                evidence);
            Require(expiredParent.State == RuntimeExecutionState.Expired,
                "parent reaches expired state while unfilled");
            Require(expiredParent.TryPrepareContinuation(expiredChild,
                    out ContinuationContext expiredContinuation,
                    out string expiredContinuationReason),
                $"CONTINUE accepts unfilled expired parent: {expiredContinuationReason}");
            Require(expiredContinuation.Kind == ContinuationKind.ExpiredRearm
                    && expiredContinuation.ParentSponsorClear == null
                    && expiredContinuation.EvidenceAfterUtc == expireAcceptUtc,
                "expired CONTINUE preserves parent active-window context");

            var expiredContinuationEvidence = new ExecutionEvidenceEngine(0.25);
            EvidenceTransition expiredSeed = BuildConsumedDemandRail(
                expiredContinuationEvidence,
                expireAcceptUtc.AddSeconds(5),
                30504);
            double expiredSeedAsk = expiredSeed.Band.MaxTick * 0.25;
            expiredParent.AcceptDirective(
                expiredChild,
                expireAcceptUtc.AddSeconds(90),
                Array.Empty<int>(),
                expiredContinuation);
            expiredParent.InitializeObservedPosition(RuntimePosition.Flat);
            OrderIntent expiredSeeded = expiredParent.SeedContinuation(
                    expireAcceptUtc.AddSeconds(90),
                    Market(expireAcceptUtc.AddSeconds(90),
                        expiredSeedAsk - 0.25,
                        expiredSeedAsk),
                    RuntimePosition.Flat,
                    expiredContinuationEvidence)
                .SingleOrDefault();
            Require(expiredSeeded?.Kind == OrderIntentKind.EnterBase
                    && expiredSeeded.Reason
                        == "continuation_direct_conversion_snapshot",
                "expired CONTINUE seeds entry from parent-window rail");

            var parent = new ExecutionCoordinator(0.25);
            parent.AcceptDirective(directive, now, Array.Empty<int>());
            OrderIntent parentEntry = parent.ProcessEvidence(
                new[]
                {
                    ConsumedDemand(700, now.AddSeconds(1), now.AddSeconds(12),
                        30500, 30501),
                },
                now.AddSeconds(12),
                market,
                RuntimePosition.Flat,
                evidence).Single();
            parent.OnOrderAttemptResult(parentEntry, accepted: true);
            var parentPosition = new RuntimePosition
            {
                PositionId = "continuation-parent",
                Direction = TradeDirection.Long,
                Quantity = 2,
                AveragePrice = 30504,
            };
            parent.OnPositionChanged(parentPosition, now.AddSeconds(13), market);
            OrderIntent parentFlat = parent.ProcessEvidence(
                new[]
                {
                    RailTransition(EvidenceTransitionKind.RailFailed,
                        700,
                        EvidenceSide.Demand,
                        EvidenceSource.Consumed,
                        now.AddSeconds(1),
                        now.AddSeconds(25),
                        30500,
                        30501),
                },
                now.AddSeconds(25),
                market,
                parentPosition,
                evidence).Single();
            Require(parentFlat.Kind == OrderIntentKind.Flatten
                    && parentFlat.RearmAfterFlat,
                "parent protective sponsor failure flattens and can rearm");
            parent.OnPositionChanged(RuntimePosition.Flat, now.AddSeconds(26), market);
            Require(parent.TryPrepareContinuation(child,
                    out ContinuationContext continuation,
                    out string continuationReason),
                $"CONTINUE accepts protective parent clear: {continuationReason}");
            Require(continuation.Kind == ContinuationKind.ProtectiveClear,
                "protective CONTINUE records lineage kind");

            TradeDirective changedRangeChild = DirectiveContracts.ParseTradeDirective(
                continuationJson.Replace(
                    "\"order_price_range\": { \"lower\": 30000, \"upper\": 30900 }",
                    "\"order_price_range\": { \"lower\": 30010, \"upper\": 30900 }"),
                5);
            Require(!parent.TryPrepareContinuation(
                    changedRangeChild,
                    out _,
                    out string changedRangeReason)
                    && changedRangeReason == "continuation_ranges_changed",
                "CONTINUE rejects changed order range");

            EvidenceBandView counter = new()
            {
                Id = 701,
                Role = EvidenceRole.Rail,
                Side = EvidenceSide.Supply,
                Source = EvidenceSource.Consumed,
                State = EvidenceState.Owned,
                MinTick = (long)Math.Round(29800 / 0.25),
                MaxTick = (long)Math.Round(29801 / 0.25),
                FormedUtc = now.AddSeconds(27),
                OwnedUtc = now.AddSeconds(28),
            };
            Require(ExecutionCoordinator.HasContinuationBoundaryCounterEvidence(
                    TradeDirection.Long,
                    continuation,
                    new[] { counter },
                    out EvidenceBandView foundCounter)
                    && foundCounter.Id == 701,
                "CONTINUE rejects adverse ownership beyond parent boundary");

            var continuationEvidence = new ExecutionEvidenceEngine(0.25);
            EvidenceTransition seed = BuildConsumedDemandRail(
                continuationEvidence,
                now.AddSeconds(30),
                30504);
            double seedAsk = seed.Band.MaxTick * 0.25;
            var seedMarket = new ExecutableMarket
            {
                TimeUtc = now.AddSeconds(90),
                QuoteUtc = now.AddSeconds(90),
                Bid = seedAsk - 0.25,
                Ask = seedAsk,
            };
            parent.AcceptDirective(
                child,
                now.AddSeconds(90),
                Array.Empty<int>(),
                continuation);
            parent.InitializeObservedPosition(RuntimePosition.Flat);
            OrderIntent seeded = parent.SeedContinuation(
                    now.AddSeconds(90),
                    seedMarket,
                    RuntimePosition.Flat,
                    continuationEvidence)
                .SingleOrDefault();
            Require(seeded?.Kind == OrderIntentKind.EnterBase
                    && seeded.Reason == "continuation_direct_conversion_snapshot",
                "CONTINUE seeds entry from post-parent consumed rail");
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
            var flatPause = new ExecutionCoordinator(0.25);
            flatPause.AcceptDirective(directive, now, Array.Empty<int>());
            EvidenceTransition lf = new()
            {
                Kind = EvidenceTransitionKind.FailureHeld,
                TimeUtc = now.AddSeconds(10),
                CurrentMidTick = 121900,
                Band = new EvidenceBandView
                {
                    Id = 699,
                    Role = EvidenceRole.FailureZone,
                    Side = EvidenceSide.Demand,
                    State = EvidenceState.Held,
                    MinTick = 121900,
                    MaxTick = 121904,
                    FormedUtc = now.AddSeconds(1),
                    OwnedUtc = now.AddSeconds(1),
                },
            };
            OrderIntent lfPause = flatPause.ProcessEvidence(
                new[] { lf }, now.AddSeconds(10), market,
                RuntimePosition.Flat, evidence).Single();
            Require(lfPause.Reason == "LF_pause_while_flat"
                    && flatPause.State == RuntimeExecutionState.Paused,
                "short directive pauses on local LF while flat");

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
                30504,
                30505);
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

            EvidenceTransition oldReferenceFailure = RailTransition(
                EvidenceTransitionKind.RailFailed,
                610,
                EvidenceSide.Demand,
                EvidenceSource.Consumed,
                now.AddMinutes(-70),
                now.AddSeconds(28),
                30502.25,
                30502.75);
            Require(coordinator.ProcessEvidence(
                    new[] { oldReferenceFailure }, now.AddSeconds(28), market,
                    leveragedPosition, evidence).Count == 0,
                "old demand reference break arms context without flattening");

            EvidenceTransition childSupply = RailTransition(
                EvidenceTransitionKind.RailOwned,
                602,
                EvidenceSide.Supply,
                EvidenceSource.Consumed,
                now.AddSeconds(29),
                now.AddSeconds(40),
                30499.75,
                30500.00);
            OrderIntent tacticalAdd = coordinator.ProcessEvidence(
                new[] { childSupply }, now.AddSeconds(40), market,
                leveragedPosition, evidence).SingleOrDefault();
            Require(tacticalAdd?.Kind == OrderIntentKind.Add
                    && coordinator.CurrentSponsor?.ObjectId == 601,
                "child supply below old demand is add-eligible but not campaign sponsor");
            coordinator.OnOrderAttemptResult(tacticalAdd, accepted: true);
            var secondLeveragedPosition = new RuntimePosition
            {
                PositionId = "short-sponsor-selftest",
                Direction = TradeDirection.Short,
                Quantity = 4,
                AveragePrice = 30502.25,
            };
            coordinator.OnPositionChanged(
                secondLeveragedPosition, now.AddSeconds(41), market);
            Require(coordinator.CurrentSponsor?.ObjectId == 601,
                "filled child add preserves parent reference-break sponsor");

            EvidenceTransition childFailure = RailTransition(
                EvidenceTransitionKind.RailFailed,
                602,
                EvidenceSide.Supply,
                EvidenceSource.Consumed,
                now.AddSeconds(29),
                now.AddSeconds(42),
                30499.75,
                30500.00);
            Require(coordinator.ProcessEvidence(
                    new[] { childFailure }, now.AddSeconds(42), market,
                    secondLeveragedPosition, evidence).Count == 0,
                "child sponsor failure cannot terminally flatten parent campaign");

            EvidenceTransition currentFailure = RailTransition(
                EvidenceTransitionKind.RailFailed,
                601,
                EvidenceSide.Supply,
                EvidenceSource.Consumed,
                now.AddSeconds(14),
                now.AddSeconds(43),
                30504,
                30505);
            OrderIntent flatten = coordinator.ProcessEvidence(
                new[] { currentFailure }, now.AddSeconds(43), market,
                secondLeveragedPosition, evidence).SingleOrDefault();
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

        private static EvidenceTransition FailureTransition(
            EvidenceTransitionKind kind,
            int id,
            EvidenceSide side,
            DateTime eventUtc,
            double lower,
            double upper)
        {
            long minTick = (long)Math.Round(lower / 0.25);
            long maxTick = (long)Math.Round(upper / 0.25);
            return new EvidenceTransition
            {
                Kind = kind,
                TimeUtc = eventUtc,
                CurrentMidTick = side == EvidenceSide.Demand
                    ? maxTick + 9
                    : minTick - 9,
                Band = new EvidenceBandView
                {
                    Id = id,
                    Role = EvidenceRole.FailureZone,
                    Side = side,
                    State = kind == EvidenceTransitionKind.FailureInvalidated
                        ? EvidenceState.Removed
                        : EvidenceState.Held,
                    MinTick = minTick,
                    MaxTick = maxTick,
                    FormedUtc = eventUtc.AddSeconds(-10),
                    OwnedUtc = eventUtc.AddSeconds(-10),
                    LastStateUtc = eventUtc,
                },
            };
        }

        private static ExecutableMarket Market(DateTime timeUtc, double bid, double ask)
            => new()
            {
                TimeUtc = timeUtc,
                QuoteUtc = timeUtc,
                Bid = bid,
                Ask = ask,
            };

        private static EvidenceTransition BuildConsumedDemandRail(
            ExecutionEvidenceEngine engine,
            DateTime startUtc,
            double bid)
        {
            for (int second = 0; second < 35; second++)
                engine.Process(Book(startUtc.AddSeconds(second), bid,
                    bidSize: 1, askSize: 1));

            for (int second = 35; second < 38; second++)
                engine.Process(Book(startUtc.AddSeconds(second), bid,
                    bidSize: 1, askSize: 20));

            for (int second = 38; second <= 50; second++)
            {
                EvidenceTransition transition = engine.Process(
                        Book(startUtc.AddSeconds(second), bid + 2.25,
                            bidSize: 1, askSize: 1))
                    .FirstOrDefault(t => t.Kind == EvidenceTransitionKind.RailOwned
                        && t.Band?.Side == EvidenceSide.Demand
                        && t.Band.Source == EvidenceSource.Consumed);
                if (transition != null)
                    return transition;
            }

            throw new InvalidOperationException(
                "Runtime self-test failed: engine consumed demand rail");
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
                "leveraged": "current_sponsor_failure",
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
