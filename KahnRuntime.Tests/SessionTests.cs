using KahnRuntime;
using KahnRuntime.Scaling;

internal static class SessionTests
{
    private static readonly DateTimeOffset Start = DateTimeOffset.Parse("2026-09-07T14:00:00Z");
    private static DateTimeOffset At(double seconds) => Start.AddSeconds(seconds);
    private static PriceRange Range(double lower, double upper) => new() { Lower = lower, Upper = upper };
    private static void Check(bool value, string message) { if (!value) throw new Exception(message); }
    private static void Throws(Action action) { try { action(); } catch (Exception) { return; } throw new Exception("expected rejection"); }

    public static void RunAll()
    {
        Action[] tests = [WatchCannotProbe, GoLiveDoesNotReplayEvidence, GoLiveBindsDigest,
            GoLiveBindsInstance, GoLiveBindsAttempt, StaleGoLiveRejected, FutureGoLiveRejected,
            GoLiveDoesNotExtendExpiry, RestartRequiresNewAuthorization, RootSubmissionIsNotFill,
            RootPartialFillCountsOnce, ZeroFillDoesNotSpendAttempt, UncertainSubmissionBlocksRisk,
            SameSampleFailedRootCannotEnter, ScalePartialFillQueuesOnce, ScaleRejectDoesNotQueue,
            RootOnlyNeverUsesLegacyPress, WatchDoesNotLoseClaims, NoLegacyScaleTracking,
            GroupSponsorPartialFailureDoesNotInvokeRootHull, RootRiskStillTyped,
            ScaledBreakevenEligible, OperatorProbeBreakevenEligible, HoldDoesNotReanchor,
            PostExpiryInventoryStillManaged, DeclaredHarvestPartialFill, DeclaredHarvestFloorLoss,
            RetirementSurvivesLateFill, ObservationGapDuringRootFillKeepsInventory,
            ScopedControlParserRequiresFields, LegacyControlCannotActivate, LegacyPlanReadable,
            NewPlanRejectsLegacyRoles, NewPlanStartsWatch, DuplicateTerminalReportIsIdempotent,
            ChangedTerminalReportRejected, NewRiskSuppressionKeepsObservation,
            OperatorProtectionNeverLoosens, BrokerProtectionNeverLoosens,
            ShortProtectionNeverLoosens, ExternalAdverseClaimRetainsVeto, FlatClearsDeferredRootObservation];
        foreach (var test in tests)
        {
            try { test(); }
            catch (Exception error) { throw new Exception("FAIL " + test.Method.Name + ": " + error.Message, error); }
        }
        Console.WriteLine($"PASS campaign session integration ({tests.Length} checks)");
    }

    private static CampaignPlan Plan(bool rootOnly = false, bool harvest = false, CampaignSide side = CampaignSide.Long) => new()
    {
        SchemaVersion = 2, Id = "test", Digest = "digest", Status = "active", Side = side,
        Policies = new(), Risk = new(), Execution = new(),
        Window = new() { NotBefore = At(-10), ExpiresAt = At(120) }, Arena = Range(390, 600),
        Sizing = new() { ProbeQuantity = 2, AddQuantity = 2, MaxPositionQuantity = rootOnly ? 2 : 10,
            ScaleMode = rootOnly ? CampaignScaleMode.RootOnly : CampaignScaleMode.EvidenceScaled },
        Waypoints = new[] { new CampaignWaypoint { Id = "root", Role = WaypointRole.TrapProbe, Range = Range(398, 410) } },
        Objective = new() { TargetRange = Range(590, 600), TargetProximityTicks = 2,
            PassiveHarvest = harvest ? new() { Enabled = true, Range = Range(590, 600),
                InitialClipQuantity = 1, FollowClipQuantity = 1, MaxWorkingQuantity = 2 } : null },
    };

    private sealed class Fixture
    {
        public CampaignSession Session;
        public CampaignState State => Session.State;
        private long _sequence;
        public Fixture(bool root = true, bool rootOnly = false, bool harvest = false)
        {
            var plan = Plan(rootOnly, harvest);
            Session = new(plan, CampaignState.ForPlan(plan), "instance", 1, TimeSpan.FromMinutes(1));
            Step(-1, 408);
            if (root)
            {
                Check(Session.GoLive(Control(), At(0)) == "accepted", "authorization");
                Step(1, 408, T("root", 400, 404));
                var order = ReserveRoot();
                Session.Submitted(order, "root-order", true, false);
                Session.Report(order, 2, 408, true, At(1.1), 408);
            }
        }
        public RuntimeControlCommand Control(string digest = "digest", string instance = "instance", int? attempt = null, double time = 0)
            => new() { SchemaVersion = 2, Id = "cmd", Action = RuntimeControlAction.GoLive,
                CampaignId = "test", CampaignDigest = digest, RuntimeInstanceId = instance,
                Attempt = attempt ?? State.ExecutionAttemptCount, CreatedAt = At(time) };
        public RepairTransition T(string id, long lo, long hi, EvidenceKind kind = EvidenceKind.RailOwned, bool opposite = false)
            => new(new(EvidenceSource.LevelLedger, "epoch", id), kind,
                opposite ? CampaignSide.Short : CampaignSide.Long, new(lo, hi));
        public void Step(double seconds, double price, params RepairTransition[] transitions)
            => Session.Observe(new(EvidenceSource.LevelLedger, "epoch", _sequence++, At(seconds), price, transitions, true));
        public CampaignEvidence Evidence(double time = 1, EvidenceKind kind = EvidenceKind.RailOwned, string id = "root",
            EvidenceSide side = EvidenceSide.Demand, double lower = 400, double upper = 404)
            => new() { EventId = id + kind + time, Timestamp = At(time), Source = EvidenceSource.LevelLedger,
                EvidenceEpoch = "epoch", RailId = id, Kind = kind, Side = side, Range = Range(lower, upper), Price = 408 };
        public CampaignOrder ReserveRoot()
        {
            var ev = Evidence();
            return Session.Reserve(new() { Action = PolicyAction.AllowProbe, Quantity = 2,
                RiskAnchor = ev.Range, RiskAnchorEvidenceId = ev.EventId, EvidenceId = ev.EventId }, ev, null, At(1));
        }
        public ScaleOpportunity Complete()
        {
            Step(5, 460, T("proof", 420, 424));
            Step(10, 420, T("proof", 420, 424, EvidenceKind.RailTested));
            Step(11, 432, T("claim", 440, 444, opposite: true));
            Step(20, 436, T("proof", 420, 424, EvidenceKind.RailHeld));
            Step(30, 472, T("claim", 440, 444, EvidenceKind.RailFailed, true));
            return Session.Observer.Opportunity ?? throw new Exception("missing opportunity");
        }
        public CampaignOrder ReserveScale()
        {
            var opportunity = Complete();
            var context = new ScaleAdmissionContext(At(30), At(30), TimeSpan.FromSeconds(2), TimeSpan.FromSeconds(60),
                472, 473, 408, 2, 2, 10, 10, true, true, true, true, false);
            Check(Session.Reservations.TryReserve(opportunity, context, out var reserved, out var reason), reason);
            var order = Session.Reserve(new() { Action = PolicyAction.AllowAdd, Quantity = 2, Policy = "repair_episode",
                EvidenceId = reserved.Id }, Evidence(30, id: reserved.Id), reserved, At(30));
            Session.Submitted(order, "scale-order", true, false);
            return order;
        }
    }

    private static void WatchCannotProbe() { var f = new Fixture(false); Check(!f.Session.PolicyCandidates([f.Evidence()], At(1)).Any(x => x.Decision.Action == PolicyAction.AllowProbe), "watch entered"); }
    private static void GoLiveDoesNotReplayEvidence() { var f = new Fixture(false); f.Session.GoLive(f.Control(time: 10), At(10)); Check(f.Session.PolicyCandidates([f.Evidence()], At(10)).Count == 0, "old signal replayed"); }
    private static void GoLiveBindsDigest() { var f = new Fixture(false); Check(f.Session.GoLive(f.Control(digest: "other"), At(0)) == "rejected_scope", "digest"); }
    private static void GoLiveBindsInstance() { var f = new Fixture(false); Check(f.Session.GoLive(f.Control(instance: "other"), At(0)) == "rejected_scope", "instance"); }
    private static void GoLiveBindsAttempt() { var f = new Fixture(false); Check(f.Session.GoLive(f.Control(attempt: 2), At(0)) == "rejected_scope", "attempt"); }
    private static void StaleGoLiveRejected() { var f = new Fixture(false); Check(f.Session.GoLive(f.Control(), At(16)) == "rejected_stale_control", "stale"); }
    private static void FutureGoLiveRejected() { var f = new Fixture(false); Check(f.Session.GoLive(f.Control(time: 2), At(0)) == "rejected_stale_control", "future"); }
    private static void GoLiveDoesNotExtendExpiry() { var f = new Fixture(false); Check(f.Session.GoLive(f.Control(time: 121), At(121)) == "rejected_not_watched_or_expired", "expiry"); }
    private static void RestartRequiresNewAuthorization() { var f = new Fixture(); var state = CampaignState.ForPlan(f.Session.Plan); Check(!state.ExecutionAuthorized && !state.HasPosition, "restart adopted"); }
    private static void RootSubmissionIsNotFill() { var f = new Fixture(false); f.Session.GoLive(f.Control(), At(0)); var o = f.ReserveRoot(); f.Session.Submitted(o, "id", true, false); Check(!f.State.HasPosition && f.State.ExecutionAttemptCount == 0 && f.Session.HasUnresolvedOrder, "accepted as fill"); }
    private static void RootPartialFillCountsOnce() { var f = new Fixture(false); f.Session.GoLive(f.Control(), At(0)); var o = f.ReserveRoot(); f.Session.Report(o, 1, 408, false, At(1.1), 408); f.Session.Report(o, 2, 409, true, At(2), 410); Check(f.State.ExecutionAttemptCount == 1 && f.State.SimulatedPositionQuantity == 2 && f.State.SimulatedAveragePrice == 409, "partial accounting"); }
    private static void ZeroFillDoesNotSpendAttempt() { var f = new Fixture(false); f.Session.GoLive(f.Control(), At(0)); var o = f.ReserveRoot(); f.Session.Report(o, 0, null, true, At(1), 408); Check(!f.Session.HasUnresolvedOrder && f.State.ExecutionAttemptCount == 0, "zero fill spent retry"); }
    private static void UncertainSubmissionBlocksRisk() { var f = new Fixture(false); f.Session.GoLive(f.Control(), At(0)); var o = f.ReserveRoot(); f.Session.Submitted(o, null, false, true); Check(f.Session.HasUnresolvedOrder && !f.State.ExecutionAuthorized, "uncertain released"); Throws(() => f.ReserveRoot()); }
    private static void SameSampleFailedRootCannotEnter() { var f = new Fixture(false); f.Session.GoLive(f.Control(), At(0)); f.Step(1, 408, f.T("root", 400, 404), f.T("root", 400, 404, EvidenceKind.RailFailed)); Check(f.Session.PolicyCandidates([f.Evidence()], At(1)).Count == 0, "intra-sample entry"); }
    private static void ScalePartialFillQueuesOnce() { var f = new Fixture(); var o = f.ReserveScale(); Check(f.State.AcceptedAddCount == 0 && f.Session.Sponsors.Pending == null, "submit promoted"); f.Session.Report(o, 1, 473, false, At(30.1), 472); var pending = f.Session.Sponsors.Pending; f.Session.Report(o, 2, 474, true, At(30.2), 475); Check(f.State.AcceptedAddCount == 1 && f.Session.Sponsors.FilledAddCount == 1 && ReferenceEquals(pending, f.Session.Sponsors.Pending) && f.State.SimulatedPositionQuantity == 4 && f.State.SimulatedAveragePrice == 441, "scale accounting"); }
    private static void ScaleRejectDoesNotQueue() { var f = new Fixture(); var o = f.ReserveScale(); f.Session.Report(o, 0, null, true, At(30.1), 472); Check(f.State.AcceptedAddCount == 0 && f.Session.Sponsors.Pending == null && !f.Session.HasUnresolvedOrder && f.Session.Observer.Opportunity == null, "rejected add banked"); }
    private static void RootOnlyNeverUsesLegacyPress() { var f = new Fixture(rootOnly: true); Check(f.Session.PolicyCandidates([f.Evidence(5, lower: 420, upper: 424)], At(5)).All(x => x.Decision.Action is not (PolicyAction.AllowAdd or PolicyAction.TrackScaleCandidate)), "legacy press"); }
    private static void WatchDoesNotLoseClaims() { var f = new Fixture(false); f.Step(1, 408, f.T("root", 400, 404)); f.Session.GoLive(f.Control(time: 2), At(2)); Check(f.Session.Observer.KnownClaimCount == 1, "watch claims lost"); }
    private static void NoLegacyScaleTracking() { var f = new Fixture(); f.Step(5, 430, f.T("proof", 420, 424)); Check(f.Session.PolicyCandidates([f.Evidence(5, id: "proof", lower: 420, upper: 424)], At(5)).All(x => x.Decision.Action is not (PolicyAction.TrackScaleCandidate or PolicyAction.AllowAdd)), "new price entered"); }
    private static void GroupSponsorPartialFailureDoesNotInvokeRootHull() { var f = new Fixture(); f.State.GroupSponsorActive = true; Check(f.Session.PolicyCandidates([f.Evidence(5, EvidenceKind.RailFailed)], At(5)).All(x => x.Decision.Action != PolicyAction.Flatten), "group replaced by hull"); }
    private static void RootRiskStillTyped() { var f = new Fixture(); Check(f.Session.PolicyCandidates([new CampaignEvidence { Timestamp = At(5), Price = 350, Kind = EvidenceKind.PriceTouch }], At(5)).All(x => x.Decision.Action != PolicyAction.Flatten), "hard root stop invented"); Check(f.Session.PolicyCandidates([f.Evidence(6, EvidenceKind.RailFailed)], At(6)).Any(x => x.Decision.Action == PolicyAction.Flatten), "typed root lost"); }
    private static void ScaledBreakevenEligible() { var f = new Fixture(); Check(!f.State.BreakevenBackstopEligible(f.Session.Plan), "root auto BE"); var o = f.ReserveScale(); f.Session.Report(o, 1, 473, false, At(30.1), 472); Check(f.State.BreakevenBackstopEligible(f.Session.Plan), "filled scale BE missing"); }
    private static void OperatorProbeBreakevenEligible() { var f = new Fixture(); f.State.SetOperatorProtection(408); Check(f.State.BreakevenBackstopEligible(f.Session.Plan), "operator BE missing"); }
    private static void HoldDoesNotReanchor() { var f = new Fixture(); f.State.ApplyDecision(new() { Action = PolicyAction.HoldRoot, RiskAnchor = Range(450, 454) }, f.Session.Plan, false, At(5)); Check(f.State.ActiveRiskAnchor.Lower == 400, "hold moved root"); }
    private static void PostExpiryInventoryStillManaged() { var f = new Fixture(); Check(f.Session.Plan.ShouldEvaluateEvidenceAt(At(130), f.State), "expired management stopped"); }
    private static void DeclaredHarvestPartialFill() { var f = new Fixture(harvest: true); var ev = new CampaignEvidence { EventId = "target", Timestamp = At(5), Price = 595, Kind = EvidenceKind.PriceTouch }; var decision = f.Session.PolicyCandidates([ev], At(5)).Single().Decision; Check(decision.Action == PolicyAction.PassiveHarvest, "harvest missing"); f.State.ApplyDecision(decision, f.Session.Plan, true, At(5), passiveHarvestFilledQuantity: 1); Check(f.State.SimulatedPositionQuantity == 1 && !f.State.IsRetired, "partial harvest"); }
    private static void DeclaredHarvestFloorLoss() { var f = new Fixture(harvest: true); f.State.ApplyDecision(new() { Action = PolicyAction.PassiveHarvest }, f.Session.Plan, false, At(5)); var ev = new CampaignEvidence { EventId = "floor-lost", Timestamp = At(6), Price = 580, Kind = EvidenceKind.PriceTouch }; Check(f.Session.PolicyCandidates([ev], At(6)).Any(x => x.Decision.ReasonCode == "harvest_floor_lost" && x.Decision.Action == PolicyAction.Retire), "floor cleanup missing"); }
    private static void RetirementSurvivesLateFill() { var f = new Fixture(); var o = f.ReserveScale(); f.State.ApplyDecision(new() { Action = PolicyAction.Retire }, f.Session.Plan, true, At(30.05)); f.Session.Report(o, 1, 473, false, At(30.1), 472); Check(f.State.IsRetired && !f.State.ExecutionAuthorized && f.Session.RecoveryReason != null && f.State.HasPosition, "late fill revived campaign"); }
    private static void ObservationGapDuringRootFillKeepsInventory() { var f = new Fixture(false); f.Session.GoLive(f.Control(), At(0)); var o = f.ReserveRoot(); f.Session.Observer.Suspend(At(1), "gap"); f.Session.Report(o, 2, 408, true, At(2), double.NaN); Check(f.State.SimulatedPositionQuantity == 2 && f.Session.Reservations == null, "gap lost actual fill"); }
    private static void ScopedControlParserRequiresFields() => Throws(() => RuntimeControlParser.Parse("""{"schema_version":2,"id":"x","action":"GO_LIVE"}"""));
    private static void LegacyControlCannotActivate() => Throws(() => RuntimeControlParser.Parse("""{"schema_version":1,"id":"x","action":"BE"}"""));
    private static string Json(int version, string role = "trap_probe") => $$$"""
        {"schema_version":{{{version}}},"kind":"KAHN_CAMPAIGN","id":"test","status":"draft","created_at":"2026-09-07T14:00:00Z","side":"long",
        "window":{"not_before":"2026-09-07T14:00:00Z","expires_at":"2026-09-07T15:00:00Z"},"arena":{"lower":390,"upper":600},
        "waypoints":[{"id":"root","role":"{{{role}}}","range":{"lower":400,"upper":410}}]}
        """;
    private static void LegacyPlanReadable() => Check(CampaignPlanParser.Parse(Json(1, "press")).SchemaVersion == 1, "legacy unreadable");
    private static void NewPlanRejectsLegacyRoles() { Throws(() => CampaignPlanParser.Parse(Json(2, "press"))); Throws(() => CampaignPlanParser.Parse(Json(2, "no_add"))); }
    private static void NewPlanStartsWatch() => Check(!CampaignState.ForPlan(CampaignPlanParser.Parse(Json(2))).ExecutionAuthorized, "not WATCH");
    private static void DuplicateTerminalReportIsIdempotent() { var f = new Fixture(); var o = f.Session.FindBrokerOrder("root-order"); Check(!f.Session.Report(o, 2, 408, true, At(5), 450) && f.State.ExecutionAttemptCount == 1, "duplicate filled twice"); }
    private static void ChangedTerminalReportRejected() { var f = new Fixture(); Throws(() => f.Session.Report(f.Session.FindBrokerOrder("root-order"), 1, 408, true, At(5), 450)); }
    private static void NewRiskSuppressionKeepsObservation() { var f = new Fixture(); f.State.ApplyDecision(new() { Action = PolicyAction.SuppressAdd, ExpiresAt = At(60) }, f.Session.Plan, false, At(2)); Check(f.Complete() != null && f.State.AddsSuppressed(At(30)), "veto stopped observation"); }
    private static void OperatorProtectionNeverLoosens() { var f = new Fixture(); f.State.SetOperatorProtection(415); Check(f.Session.ProtectionPrice(408.1) == 415, "operator stop loosened"); }
    private static void BrokerProtectionNeverLoosens() { var f = new Fixture(); f.State.ArmBreakevenBackstop(415, At(2)); Check(f.Session.ProtectionPrice(408.1) == 415, "armed stop loosened"); }
    private static void ShortProtectionNeverLoosens() { var plan = Plan(side: CampaignSide.Short); var state = CampaignState.ForPlan(plan); state.SetOperatorProtection(405); var session = new CampaignSession(plan, state, "instance", 1, TimeSpan.FromSeconds(5)); Check(session.ProtectionPrice(408.9) == 405, "short stop loosened"); }
    private static void ExternalAdverseClaimRetainsVeto() { var f = new Fixture(); var ev = new CampaignEvidence { Timestamp = At(5), Kind = EvidenceKind.RailOwned, Source = EvidenceSource.LevelLedger, Side = EvidenceSide.Supply, Range = Range(420, 424), Price = 430 }; Check(f.Session.PolicyCandidates([ev], At(5)).Any(x => x.Decision.Action == PolicyAction.SuppressAdd), "external risk use removed"); }
    private static void FlatClearsDeferredRootObservation() { var f = new Fixture(false); f.Session.GoLive(f.Control(), At(0)); var o = f.ReserveRoot(); f.Session.Observer.Suspend(At(1), "gap"); f.Session.Report(o, 2, 408, true, At(2), double.NaN); f.State.ApplyDecision(new() { Action = PolicyAction.Flatten }, f.Session.Plan, true, At(3)); f.Session.ConfirmFlat(At(3)); f.Session.Observe(new(EvidenceSource.LevelLedger, "new-epoch", 0, At(4), 410, Array.Empty<RepairTransition>(), true)); Check(f.Session.Sponsors == null, "flat restarted root proof"); }
}
