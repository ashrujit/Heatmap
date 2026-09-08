using KahnRuntime;
using KahnRuntime.Scaling;

internal static partial class SessionTests
{
    private static void RunBrokerTests()
    {
        Action[] tests = [NqIncidentCallbacks, LongTradeOnlyFill, CumulativeThenTrade,
            PartialStreamsInterleaved, DistinctEqualExecutions, DuplicateAfterReduction,
            LaterFillAfterReduction, CancelWithoutFill, FillAfterCancellation,
            ScaleTradeFillsCountOnce, CancelledScaleLateFillKeepsOldSponsor,
            MissingTradeIdentityRejected, ConflictingTradeIdentityRejected, ExcessTradeQuantityRejected,
            WrongSideRejected, UnknownOrderIgnored, ChangedPositionRejected, InvalidFillFactsRejected,
            RiskFailureSurvivesReconciliation, RootFailureBeforeFillSurvives,
            CycleObservesWhenReconciliationFails, CycleObservesWhenProtectionFails,
            CycleBlocksRiskUntilReconciled, CyclePreservesNormalOrdering,
            RetiredLateFillDoesNotRevive, ConflictingStreamsRejected,
            NqAddMixedPositionSnapshotKeepsCorrectBreakeven, PartialAddMixedAverageNotAdopted,
            RecoveryStillMaintainsKnownProtection, ProtectionRejectsUnknownPosition,
            BrokerAverageAfterReductionStillReconciles];
        foreach (var test in tests)
        {
            try { test(); }
            catch (Exception error) { throw new Exception("FAIL " + test.Method.Name + ": " + error.Message, error); }
        }
        Console.WriteLine($"PASS broker callback and recovery regression ({tests.Length} checks)");
    }

    private static (Fixture Fixture, CampaignOrder Order) PendingRoot()
    {
        var f = new Fixture(false);
        f.Session.GoLive(f.Control(), At(0));
        f.Step(1, 408, f.T("root", 400, 404));
        var order = f.ReserveRoot();
        f.Session.Submitted(order, "root-order", true, false);
        return (f, order);
    }

    private static BrokerEvent Trade(string id, int quantity = 1, double price = 408,
        string order = "root-order", string side = "Long", string position = "position")
        => new() { EventType = "trade_fill", TradeId = id, OrderId = order, PositionId = position,
            Side = side, Quantity = quantity, Price = price, BrokerUtc = At(1.1).UtcDateTime };

    private static BrokerEvent OrderReport(int filled = 0, double average = double.NaN,
        bool terminal = false, string order = "root-order", string type = "order_updated", string side = "Buy")
        => new() { EventType = type, OrderId = order, Side = side, Quantity = 2,
            FilledQuantity = filled, RemainingQuantity = 2 - filled, AverageFillPrice = average,
            Terminal = terminal, Status = terminal ? "Cancelled" : filled == 0 ? "Opened" : "PartiallyFilled" };

    private static void Feed(Fixture f, BrokerEvent report, double at = 2, double price = 408)
        => f.Session.ReportBrokerEvent(report, At(at), price);

    private static void NqIncidentCallbacks()
    {
        DateTimeOffset submit = DateTimeOffset.Parse("2026-09-08T15:06:53.8962538Z");
        var plan = new CampaignPlan { SchemaVersion = 2, Id = "nq-incident", Digest = "fixture", Status = "active",
            Side = CampaignSide.Short, Arena = Range(29400, 29580.25), Policies = new(), Risk = new(), Execution = new(),
            Sizing = new() { ProbeQuantity = 2, AddQuantity = 2, MaxPositionQuantity = 10 },
            Window = new() { NotBefore = submit.AddMinutes(-4), ExpiresAt = submit.AddMinutes(26) },
            Waypoints = [new() { Id = "root", Role = WaypointRole.TrapProbe, Range = Range(29549.5, 29580.25) }] };
        var session = new CampaignSession(plan, CampaignState.ForPlan(plan), "fixture-instance", .25, TimeSpan.FromMinutes(1));
        session.GoLive(new() { SchemaVersion = 2, CampaignId = plan.Id, CampaignDigest = plan.Digest,
            RuntimeInstanceId = session.InstanceId, Attempt = 0, CreatedAt = submit.AddMinutes(-3) }, submit.AddMinutes(-3));
        var evidence = new CampaignEvidence { EventId = "live-ll-18-RailOwned-639244768138528438",
            Timestamp = DateTimeOffset.Parse("2026-09-08T15:06:53.8528438Z"), Source = EvidenceSource.LevelLedger,
            EvidenceEpoch = "incident-epoch", RailId = "18", Kind = EvidenceKind.RailOwned,
            Side = EvidenceSide.Supply, Range = Range(29561.75, 29566), Price = 29554.5 };
        session.Observe(new(EvidenceSource.LevelLedger, "incident-epoch", 1, evidence.Timestamp, 118218,
            [new(new(EvidenceSource.LevelLedger, "incident-epoch", "18"), EvidenceKind.RailOwned,
                CampaignSide.Short, new(118247, 118264))], true));
        var root = session.Reserve(new() { Action = PolicyAction.AllowProbe, Quantity = 2,
            RiskAnchor = evidence.Range, RiskAnchorEvidenceId = evidence.EventId }, evidence, null, submit);
        session.Submitted(root, "38660935", true, false);
        foreach (string type in new[] { "order_added", "order_updated", "order_updated" })
            session.ReportBrokerEvent(OrderReport(order: "38660935", type: type, side: "Sell"), submit.AddSeconds(1), 118218);
        // The old audit omitted Trade.Id. This identity is synthetic; quantity, price and callback order are observed.
        session.ReportBrokerEvent(Trade("synthetic-incident-execution", 2, 29554.25, "38660935", "Short"),
            DateTimeOffset.Parse("2026-09-08T15:06:55.0968715Z"), 118218);
        session.ReportBrokerEvent(OrderReport(order: "38660935", type: "order_removed", side: "Sell"),
            DateTimeOffset.Parse("2026-09-08T15:06:55.0974480Z"), 118218);
        Check(root.Terminal && !session.HasUnresolvedOrder && session.RecoveryReason == null, "stale removal stranded reservation");
        Check(session.State.SimulatedPositionQuantity == 2 && session.State.SimulatedAveragePrice == 29554.25
            && session.State.ExecutionAttemptCount == 1 && session.State.RootRiskAnchor.Lower == 29561.75
            && session.State.RootRiskAnchor.Upper == 29566, "incident fill or original root anchor lost");
        var failed = new CampaignEvidence { EventId = "fixture-typed-failure", Timestamp = submit.AddSeconds(25),
            Source = EvidenceSource.LevelLedger, EvidenceEpoch = "incident-epoch", RailId = "18",
            Kind = EvidenceKind.RailFailed, Side = EvidenceSide.Supply, Range = evidence.Range, Price = 29577.25 };
        Check(session.PolicyCandidates([failed], failed.Timestamp).Any(x => x.Decision.Action == PolicyAction.Flatten),
            "attributed incident root could not respond to subsequent typed failure");
    }

    private static void LongTradeOnlyFill()
    {
        var (f, o) = PendingRoot(); Feed(f, Trade("a", 2)); Feed(f, OrderReport(type: "order_removed"));
        Check(o.Terminal && f.State.SimulatedPositionQuantity == 2 && f.State.RootRiskAnchor.Lower == 400, "long trade missing");
    }
    private static void CumulativeThenTrade()
    {
        var (f, o) = PendingRoot(); Feed(f, OrderReport(2, 409)); Feed(f, Trade("a", price: 408));
        Feed(f, Trade("b", price: 410)); Feed(f, Trade("b", price: 410)); Feed(f, OrderReport());
        Check(o.Filled == 2 && f.State.SimulatedAveragePrice == 409 && f.State.ExecutionAttemptCount == 1, "streams double counted");
    }
    private static void PartialStreamsInterleaved()
    {
        var (f, o) = PendingRoot(); Feed(f, Trade("a")); Feed(f, OrderReport(1, 408)); Feed(f, OrderReport());
        Feed(f, Trade("b", price: 410)); Feed(f, OrderReport(1, 408)); Feed(f, OrderReport(2, 409));
        Check(o.Terminal && f.State.SimulatedPositionQuantity == 2 && f.State.SimulatedAveragePrice == 409, "partial merge");
    }
    private static void DistinctEqualExecutions()
    {
        var (f, o) = PendingRoot(); Feed(f, Trade("a")); Feed(f, Trade("b"));
        Check(o.Filled == 2, "equal price/quantity/time executions were collapsed");
    }
    private static void DuplicateAfterReduction()
    {
        var (f, o) = PendingRoot(); Feed(f, Trade("a")); f.State.ReconcileObservedPositionQuantity(0, f.Session.Plan);
        Feed(f, Trade("a")); Feed(f, OrderReport(1, 408));
        Check(o.Filled == 1 && !f.State.HasPosition, "duplicate resurrected reduced inventory");
    }
    private static void LaterFillAfterReduction()
    {
        var (f, o) = PendingRoot(); Feed(f, Trade("a")); f.State.ReconcileObservedPositionQuantity(0, f.Session.Plan);
        Feed(f, Trade("b", price: 410));
        Check(o.Filled == 2 && f.State.SimulatedPositionQuantity == 1 && f.State.SimulatedAveragePrice == 410, "late delta restored old exposure");
    }
    private static void CancelWithoutFill()
    {
        var (f, o) = PendingRoot(); Feed(f, OrderReport(terminal: true));
        Check(o.Terminal && !f.State.HasPosition && f.State.ExecutionAttemptCount == 0, "cancel spent attempt");
    }
    private static void FillAfterCancellation()
    {
        var (f, o) = PendingRoot(); Feed(f, OrderReport(terminal: true)); Feed(f, Trade("a"));
        Check(o.Filled == 1 && f.State.SimulatedPositionQuantity == 1 && f.Session.RecoveryReason != null
            && !f.State.ExecutionAuthorized, "cancel race discarded exposure or allowed new risk");
    }
    private static void ScaleTradeFillsCountOnce()
    {
        var f = new Fixture(); var o = f.ReserveScale();
        Feed(f, Trade("a", price: 473, order: "scale-order"), 30.1, 472); var pending = f.Session.Sponsors.Pending;
        Feed(f, OrderReport(1, 473, order: "scale-order"), 30.2, 472);
        Feed(f, Trade("b", price: 475, order: "scale-order"), 30.3, 472);
        Feed(f, OrderReport(order: "scale-order", type: "order_removed"), 30.4, 472);
        Check(o.Terminal && f.State.AcceptedAddCount == 1 && f.Session.Sponsors.FilledAddCount == 1
            && ReferenceEquals(pending, f.Session.Sponsors.Pending) && f.State.SimulatedPositionQuantity == 4
            && f.State.SimulatedAveragePrice == 441, "trade scale duplicated promotion or inventory");
    }
    private static void CancelledScaleLateFillKeepsOldSponsor()
    {
        var f = new Fixture(); var o = f.ReserveScale();
        Feed(f, OrderReport(terminal: true, order: "scale-order"), 30.1, 472);
        Feed(f, Trade("a", price: 473, order: "scale-order"), 30.2, 472);
        Check(o.Filled == 1 && f.State.SimulatedPositionQuantity == 3 && f.Session.Sponsors.Pending == null
            && f.Session.RecoveryReason != null, "late cancelled add promoted proof or hid inventory");
    }
    private static void MissingTradeIdentityRejected() { var (f, o) = PendingRoot(); Throws(() => Feed(f, Trade(null))); Check(o.Filled == 0, "identity fabricated"); }
    private static void ConflictingTradeIdentityRejected() { var (f, o) = PendingRoot(); Feed(f, Trade("a")); Throws(() => Feed(f, Trade("a", price: 410))); Check(o.Filled == 1, "identity reused"); }
    private static void ExcessTradeQuantityRejected() { var (f, o) = PendingRoot(); Feed(f, Trade("a", 2)); Throws(() => Feed(f, Trade("b"))); Check(o.Filled == 2, "overfill silently adopted"); }
    private static void WrongSideRejected() { var (f, o) = PendingRoot(); Throws(() => Feed(f, Trade("a", side: "Short"))); Check(!f.State.HasPosition, "wrong side adopted"); }
    private static void UnknownOrderIgnored() { var (f, o) = PendingRoot(); Feed(f, Trade("a", order: "manual-order")); Check(o.Filled == 0, "manual order adopted"); }
    private static void ChangedPositionRejected() { var (f, o) = PendingRoot(); Feed(f, Trade("a")); Throws(() => Feed(f, Trade("b", position: "another"))); Check(o.Filled == 1, "position rebound"); }
    private static void InvalidFillFactsRejected()
    {
        var (f, o) = PendingRoot(); Throws(() => Feed(f, OrderReport(1))); Throws(() => Feed(f, Trade("a", price: double.NaN)));
        Throws(() => Feed(f, new() { EventType = "trade_fill", OrderId = o.BrokerOrderId, Side = "Long", TradeId = "b", Quantity = .5, Price = 408 }));
        Check(o.Filled == 0, "invalid facts adopted");
    }
    private static void RiskFailureSurvivesReconciliation()
    {
        var (f, o) = PendingRoot(); Feed(f, Trade("a", 2)); f.Session.RequireRecovery("test-position-lag");
        var failed = f.Evidence(3, EvidenceKind.RailFailed);
        RuntimeManagementCycle.Run(() => false, () => false,
            () => f.Step(3, 390, f.T("root", 400, 404, EvidenceKind.RailFailed)),
            allowed => { Check(!allowed, "recovery allowed risk"); f.Session.PolicyCandidates([failed], At(3)); });
        var decision = f.Session.PolicyCandidates([], At(130)).Single(x => x.Decision.Action == PolicyAction.Flatten).Decision;
        Check(f.Session.IsPendingRiskExit(decision) && f.Session.Observer.Find(new(EvidenceSource.LevelLedger, "epoch", "root")).FailedAt.HasValue,
            "one-shot failure was lost during recovery");
        f.State.ApplyDecision(decision, f.Session.Plan, true, At(130)); f.Session.AcknowledgeRiskExit(decision);
        Check(f.Session.PendingRiskExit == null, "accepted exit not acknowledged");
    }
    private static void RootFailureBeforeFillSurvives()
    {
        var (f, o) = PendingRoot(); f.Session.PolicyCandidates([f.Evidence(1.1, EvidenceKind.RailFailed)], At(1.1));
        Feed(f, Trade("a", 2));
        Check(f.Session.PolicyCandidates([], At(4)).Any(x => x.Decision.Action == PolicyAction.Flatten), "pending root lost terminal failure");
    }
    private static void CycleObservesWhenReconciliationFails()
    {
        int samples = 0, evaluations = 0;
        Check(!RuntimeManagementCycle.Run(() => false, () => false, () => samples++,
            allowed => { Check(!allowed, "new risk allowed"); evaluations++; }) && samples == 1 && evaluations == 1, "recovery starved evidence");
    }
    private static void CycleObservesWhenProtectionFails()
    {
        int samples = 0;
        Check(!RuntimeManagementCycle.Run(() => true, () => false, () => samples++,
            allowed => Check(!allowed, "unprotected new risk")) && samples == 1, "protection failure starved evidence");
    }
    private static void CycleBlocksRiskUntilReconciled()
    {
        int calls = 0;
        Check(RuntimeManagementCycle.Run(() => ++calls > 1, () => true, () => { },
            allowed => Check(!allowed, "late reconciliation retroactively authorized risk")), "recovery did not clear");
    }
    private static void CyclePreservesNormalOrdering()
    {
        var trace = new List<string>();
        Check(RuntimeManagementCycle.Run(() => { trace.Add("reconcile"); return true; }, () => { trace.Add("protect"); return true; },
            () => trace.Add("observe"), allowed => { Check(allowed, "normal risk denied"); trace.Add("evaluate"); })
            && string.Join(",", trace) == "reconcile,protect,observe,evaluate,reconcile,protect", "cycle order changed");
    }
    private static void RetiredLateFillDoesNotRevive()
    {
        var (f, o) = PendingRoot(); f.State.ApplyDecision(new() { Action = PolicyAction.Retire }, f.Session.Plan, true, At(1.1));
        Feed(f, Trade("a", 2));
        Check(f.State.IsRetired && f.State.SimulatedPositionQuantity == 2 && !f.State.ExecutionAuthorized
            && f.Session.RecoveryReason != null, "retired campaign revived or late exposure hidden");
    }
    private static void ConflictingStreamsRejected()
    {
        var (f, o) = PendingRoot(); Feed(f, OrderReport(1, 408)); Throws(() => Feed(f, Trade("a", price: 410)));
        Feed(f, Trade("a", price: 408)); Check(o.Filled == 1 && o.FillAverage == 408, "failed merge poisoned ledger");
    }

    private static (CampaignSession Session, CampaignOrder Add) NqDefendedScale()
    {
        var plan = new CampaignPlan { SchemaVersion = 2, Id = "nq-be", Digest = "fixture", Status = "active",
            Side = CampaignSide.Long, Arena = Range(29557.25, 29685), Policies = new(), Risk = new(), Execution = new(),
            Sizing = new() { ProbeQuantity = 2, AddQuantity = 2, MaxPositionQuantity = 10 },
            Window = new() { NotBefore = At(-1), ExpiresAt = At(120) },
            Waypoints = [new() { Id = "root", Role = WaypointRole.TrapProbe, Range = Range(29557.25, 29593) }] };
        var s = new CampaignSession(plan, CampaignState.ForPlan(plan), "instance", .25, TimeSpan.FromMinutes(1));
        s.GoLive(new() { SchemaVersion = 2, CampaignId = plan.Id, CampaignDigest = plan.Digest,
            RuntimeInstanceId = s.InstanceId, Attempt = 0, CreatedAt = At(0) }, At(0));
        RepairTransition T(string id, EvidenceKind kind, CampaignSide side, long lo, long hi)
            => new(new(EvidenceSource.LevelLedger, "nq-epoch", id), kind, side, new(lo, hi));
        s.Observe(new(EvidenceSource.LevelLedger, "nq-epoch", 1, At(1), 118346,
            [T("34", EvidenceKind.RailHeld, CampaignSide.Short, 118366, 118370),
             T("42", EvidenceKind.RailOwned, CampaignSide.Short, 118357, 118367),
             T("41", EvidenceKind.RailHeld, CampaignSide.Long, 118328, 118331)], true));
        var rootEvidence = new CampaignEvidence { EventId = "root-held", Timestamp = At(1),
            Source = EvidenceSource.LevelLedger, EvidenceEpoch = "nq-epoch", RailId = "41",
            Kind = EvidenceKind.RailHeld, Side = EvidenceSide.Demand, Range = Range(29582, 29582.75), Price = 29586.25 };
        var root = s.Reserve(new() { Action = PolicyAction.AllowProbe, Quantity = 2,
            RiskAnchor = rootEvidence.Range }, rootEvidence, null, At(1));
        s.Submitted(root, "38669544", true, false);
        s.ReportBrokerEvent(Trade("38669544@2", 2, 29587, "38669544"), At(1.1), 118346);
        // Real claim/fill values; compressed synthetic sample timing isolates the callback race.
        s.Observe(new(EvidenceSource.LevelLedger, "nq-epoch", 2, At(30), 118335,
            [T("41", EvidenceKind.RailTested, CampaignSide.Long, 118328, 118331)], true));
        s.Observe(new(EvidenceSource.LevelLedger, "nq-epoch", 3, At(31), 118365,
            [T("41", EvidenceKind.RailHeld, CampaignSide.Long, 118328, 118331)], true));
        s.Observe(new(EvidenceSource.LevelLedger, "nq-epoch", 4, At(32), 118391,
            [T("42", EvidenceKind.RailFailed, CampaignSide.Short, 118357, 118367)], true));
        Check(s.Observer.Opportunity == null, "add granted before final opposition failure");
        s.Observe(new(EvidenceSource.LevelLedger, "nq-epoch", 5, At(33), 118425,
            [T("34", EvidenceKind.RailFailed, CampaignSide.Short, 118366, 118370)], true));
        var opportunity = s.Observer.Opportunity ?? throw new Exception("defended continuation missing");
        Check(opportunity.Proof.Members.Single().Key.RailId == "41"
            && opportunity.Proof.Members.Single().Form == ProofForm.Defended, "fresh-price substitute for tested proof");
        var context = new ScaleAdmissionContext(At(33), At(33), TimeSpan.FromSeconds(2), TimeSpan.FromSeconds(60),
            118401, 118404, 29587 / .25, 2, 2, 10, 10, true, true, true, true, false);
        Check(s.Reservations.TryReserve(opportunity, context, out var reservation, out var reason), reason);
        var add = s.Reserve(new() { Action = PolicyAction.AllowAdd, Quantity = 2 }, rootEvidence, reservation, At(33));
        s.Submitted(add, "38669647", true, false);
        return (s, add);
    }

    private static void NqAddMixedPositionSnapshotKeepsCorrectBreakeven()
    {
        var (s, add) = NqDefendedScale();
        Check(!s.TryReconcilePositionAverage(2, 29594.25) && s.State.SimulatedAveragePrice == 29587,
            "mixed old quantity/new average repriced root before add attribution");
        s.ReportBrokerEvent(Trade("38669647@2", 2, 29601.5, add.BrokerOrderId), At(34), 118404);
        Check(s.State.SimulatedPositionQuantity == 4 && s.State.SimulatedAveragePrice == 29594.25
            && s.PositionMatchesAttributedFills(4, 29594.25), "add average was blended twice");
        Check(s.State.BreakevenBackstopEligible(s.Plan) && s.ProtectionPrice(29594.25) == 29594.25
            && s.CanProtectPosition("position", "position", CampaignSide.Long, 4, 29594.25, false), "valid weighted BE blocked");
        int protectedQuantity = 0;
        Check(RuntimeManagementCycle.Run(() => s.PositionMatchesAttributedFills(4, 29594.25),
            () => { protectedQuantity = 4; s.State.ArmBreakevenBackstop(s.ProtectionPrice(29594.25), At(34)); return true; },
            () => { }, allowed => Check(allowed, "consistent add remained in recovery")), "cycle failed");
        Check(protectedQuantity == 4 && s.State.BreakevenBackstopActive && s.State.BreakevenBackstopPrice == 29594.25,
            "cycle did not request four-contract BE");
    }

    private static void PartialAddMixedAverageNotAdopted()
    {
        var f = new Fixture(); var add = f.ReserveScale();
        Feed(f, Trade("a", price: 473, order: add.BrokerOrderId), 30.1, 472);
        double prior = f.State.SimulatedAveragePrice.Value;
        Check(!f.Session.TryReconcilePositionAverage(3, 441) && f.State.SimulatedAveragePrice == prior,
            "partial order adopted final average ahead of final quantity");
        Feed(f, Trade("b", price: 475, order: add.BrokerOrderId), 30.2, 472);
        Check(f.State.SimulatedAveragePrice == 441 && f.State.SimulatedPositionQuantity == 4, "partial add accounting drift");
    }

    private static void RecoveryStillMaintainsKnownProtection()
    {
        var (s, add) = NqDefendedScale();
        s.ReportBrokerEvent(Trade("38669647@2", 2, 29601.5, add.BrokerOrderId), At(34), 118404);
        s.RequireRecovery("unrelated-order-status-uncertainty");
        int protections = 0;
        Check(!RuntimeManagementCycle.Run(() => false,
            () => { Check(s.CanProtectPosition("position", "position", CampaignSide.Long, 4, 29594.25, false),
                "known position could not be protected"); protections++; return true; },
            () => { }, allowed => Check(!allowed, "recovery allowed new risk")) && protections == 2,
            "new-risk recovery bypassed protection maintenance");
    }

    private static void ProtectionRejectsUnknownPosition()
    {
        var (s, add) = NqDefendedScale();
        Check(!s.CanProtectPosition("position", "position", CampaignSide.Long, 2, 29594.25, false), "mixed average protected");
        Check(!s.CanProtectPosition("position", "manual", CampaignSide.Long, 2, 29587, false), "manual position protected");
        Check(!s.CanProtectPosition(null, "position", CampaignSide.Long, 2, 29587, false), "unbound position protected");
        Check(!s.CanProtectPosition("position", "position", CampaignSide.Short, 2, 29587, false), "wrong side protected");
        Check(!s.CanProtectPosition("position", "position", CampaignSide.Long, 2, 29587, true), "ambiguous position protected");
        Check(!s.CanProtectPosition("position", "position", CampaignSide.Long, 4, 29594.25, false), "unattributed quantity protected");
    }

    private static void BrokerAverageAfterReductionStillReconciles()
    {
        var f = new Fixture(); var add = f.ReserveScale();
        Feed(f, Trade("a", 2, 474, add.BrokerOrderId), 30.1, 472);
        f.State.ReconcileObservedPositionQuantity(2, f.Session.Plan);
        Check(f.Session.TryReconcilePositionAverage(2, 474) && f.State.SimulatedAveragePrice == 474,
            "completed order prevented remaining-lot broker average reconciliation");
    }
}
