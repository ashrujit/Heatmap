using KahnRuntime;
using KahnRuntime.Scaling;

internal static partial class RootRiskTests
{
    private static readonly DateTimeOffset Start = DateTimeOffset.Parse("2026-09-09T14:00:00Z");
    private static DateTimeOffset At(double seconds) => Start.AddSeconds(seconds);
    private static void Check(bool value, string reason) { if (!value) throw new Exception(reason); }
    private static void Throws(Action action) { try { action(); } catch (InvalidOperationException) { return; } throw new Exception("expected rejection"); }
    private static PriceRange Range(double lo, double hi) => new() { Lower = lo, Upper = hi };
    private static ClaimKey Key(string id = "root", string epoch = "epoch") => new(EvidenceSource.LevelLedger, epoch, id);
    private static RootClaim Claim(string id = "root", CampaignSide side = CampaignSide.Long,
        long lower = 400, long upper = 404, RootClaimOrigin origin = RootClaimOrigin.Lean)
        => new(Key(id), side, new(lower, upper), origin, At(-10), At(-5), At(-5), EvidenceKind.RailOwned, null);
    private static RepairTransition Transition(string id = "root", EvidenceKind kind = EvidenceKind.RailOwned,
        CampaignSide side = CampaignSide.Long, long lo = 400, long hi = 404)
        => new(Key(id), kind, side, new(lo, hi), At(-10), RootClaimOrigin.Lean);
    private static RepairSample Sample(int sequence, double at, params RepairTransition[] transitions)
        => new(EvidenceSource.LevelLedger, "epoch", sequence, At(at), 408, transitions, true);
    private static CampaignEvidence Evidence(string id = "root", EvidenceKind kind = EvidenceKind.RailHeld,
        CampaignSide side = CampaignSide.Long, double at = 1, double price = 408, double lo = 400, double hi = 404)
        => new() { EventId = id + ":" + kind + ":" + at, Timestamp = At(at), Source = EvidenceSource.LevelLedger,
            EvidenceEpoch = "epoch", RailId = id, Kind = kind,
            Side = side == CampaignSide.Long ? EvidenceSide.Demand : EvidenceSide.Supply,
            Price = price, Range = Range(lo, hi) };
    private static CampaignSession Session(CampaignSide side = CampaignSide.Long, int? maximum = null)
    {
        var plan = new CampaignPlan { SchemaVersion = 2, Id = "test", Digest = "digest", Status = "active", Side = side,
            Window = new() { NotBefore = At(-20), ExpiresAt = At(1000) }, Arena = Range(300, 600),
            Policies = new(), Risk = new() { MaxRootEntryDistanceTicks = maximum }, Execution = new(), Objective = new(),
            Sizing = new() { ProbeQuantity = 2, AddQuantity = 2, MaxPositionQuantity = 10 },
            Waypoints = [new() { Id = "probe", Role = WaypointRole.TrapProbe, Range = Range(390, 450) }] };
        var s = new CampaignSession(plan, CampaignState.ForPlan(plan), "runtime", 1, TimeSpan.FromSeconds(30));
        s.GoLive(new() { SchemaVersion = 2, CampaignId = "test", CampaignDigest = "digest",
            RuntimeInstanceId = "runtime", CreatedAt = At(0), Attempt = 0 }, At(0));
        return s;
    }
    private static PolicyDecision Decision(CampaignSession s, CampaignEvidence e)
        => s.PolicyCandidates([e], e.Timestamp).Single(x => x.Decision.Action == PolicyAction.AllowProbe).Decision;
    private static (CampaignSession Session, CampaignOrder Order) Pending()
    {
        var s = Session();
        s.Observe(Sample(1, 1, Transition(kind: EvidenceKind.RailHeld)), [Claim()]);
        var e = Evidence();
        var o = s.Reserve(Decision(s, e), e, null, At(1));
        s.Submitted(o, "order", true, false);
        return (s, o);
    }
    private static void ProbeRangeCannotBeBypassed()
    {
        var s = Session(); // Legacy waypoint flag is false; schema-2 ordinary entry must still stay inside.
        s.Observe(Sample(1, 1, Transition(kind: EvidenceKind.RailHeld)), [Claim()]);
        var outside = Evidence(price: 451);
        Check(!s.PolicyCandidates([outside], At(1)).Any(x => x.Decision.Action == PolicyAction.AllowProbe),
            "legacy waypoint flag bypassed strict range");
        var inside = Evidence();
        var decision = Decision(s, inside);
        Throws(() => s.Reserve(decision, outside, null, At(1)));
    }

    private static void Fill(CampaignSession s, CampaignOrder o, int qty = 2, bool terminal = true, double at = 2)
        => s.Report(o, qty, 408, terminal, At(at), 408);

    public static void RunAll()
    {
        Action[] tests = [DirectLeanAndConsumedBothSides, CounterWithoutOwnerSkipped, CounterWithNearbyOwnerStillUnresolved,
            ConsumedDemandDoesNotResurrectSupply, MissingOwnershipCannotQualifyHeld, HydrationPreservesOldOwnership,
            HydrationIsNotEntryPermission, NeighborFailureDoesNotFlatten, ExactOwnerFailureFlattens,
            TestedOwnerSurvives, LaterHoldDoesNotMoveOwner, WrongEpochCannotFailOwner,
            EpochLossIsUnknownAndVetoesRisk, SameSampleOwnerFailureWins, FailureBeforeSubmitRejects,
            FailureBeforeFillCancelsAndExits, PartialFailureAndLateFillRetainExit, CancelledLateFillRetainsFailure,
            RetryNeedsFreshTriggerAndOwner, UnboundReservationRejected, DistanceGateAndRevalidation,
            UnsetDistanceIsNotAnInventedStop, IncompleteSnapshotCannotAuthorize, FailedIdentityCannotRevive,
            BoundRiskSurvivesSnapshotPruning, BindingIsFrozen, ParserValidatesOptionalDistance,
            ChangedIdentityGeometryIsUnknown, OlderEpochSampleCannotRestoreAuthority, UnattestedExternalCannotProbe,
            OwnerFailureHasIndependentRiskLatch, ProbeRangeCannotBeBypassed];
        foreach (var test in tests)
        {
            try { test(); }
            catch (Exception e) { throw new Exception("FAIL " + test.Method.Name + ": " + e.Message, e); }
        }
        Console.WriteLine($"PASS root ownership and admission ({tests.Length} checks)");
        RunRecoveryTests();
    }

    private static void DirectLeanAndConsumedBothSides()
    {
        foreach (var side in new[] { CampaignSide.Long, CampaignSide.Short })
        foreach (var origin in new[] { RootClaimOrigin.Lean, RootClaimOrigin.Consumed })
        {
            var s = Session(side);
            s.Observe(Sample(1, 1), [Claim(side: side, origin: origin)]);
            var e = Evidence(side: side, kind: EvidenceKind.RailOwned, price: side == CampaignSide.Long ? 408 : 396);
            var d = Decision(s, e);
            Check(d.RootBinding.Owner.Origin == origin && d.RootBinding.Owner.Side == side, "lost source or side");
        }
    }
    private static void CounterWithoutOwnerSkipped()
    {
        var s = Session(CampaignSide.Short);
        s.Observe(Sample(1, 1, Transition(kind: EvidenceKind.RailFailed)));
        Check(!s.PolicyCandidates([Evidence(kind: EvidenceKind.RailFailed)], At(1)).Any(), "naked counter probe");
        Check(s.LastRootAdmissionReason == "root_owner_missing", "missing diagnostic");
    }
    private static void CounterWithNearbyOwnerStillUnresolved()
    {
        var s = Session(CampaignSide.Short);
        s.Observe(Sample(1, 1, Transition(kind: EvidenceKind.RailFailed)),
            [Claim("supply", CampaignSide.Short, 410, 414), Claim("neighbor", CampaignSide.Short, 411, 415)]);
        Check(!s.PolicyCandidates([Evidence(kind: EvidenceKind.RailFailed)], At(1)).Any(), "nearest or overlapping rail invented pair");
        Check(s.LastRootAdmissionReason == "root_pair_unresolved", "unresolved diagnostic");
    }
    private static void ConsumedDemandDoesNotResurrectSupply()
    {
        var s = Session(CampaignSide.Short);
        s.Observe(Sample(1, 1, Transition(kind: EvidenceKind.RailFailed)), [Claim(origin: RootClaimOrigin.Consumed)]);
        Check(!s.PolicyCandidates([Evidence(kind: EvidenceKind.RailFailed)], At(1)).Any(), "source supply resurrected");
    }
    private static void MissingOwnershipCannotQualifyHeld()
    {
        var s = Session();
        s.Observe(Sample(1, 1, Transition(kind: EvidenceKind.RailHeld)));
        Check(!s.PolicyCandidates([Evidence()], At(1)).Any(), "HOLD invented missing history");
    }
    private static void HydrationPreservesOldOwnership()
    {
        var s = Session();
        s.Observe(Sample(1, 1, Transition(kind: EvidenceKind.RailHeld)), [Claim()]);
        Check(Decision(s, Evidence()).RootBinding.Owner.OwnedAt == At(-5), "campaign reload forgot prior ownership");
    }
    private static void HydrationIsNotEntryPermission()
    {
        var s = Session();
        s.Observe(Sample(1, 1), [Claim()]);
        Check(s.PolicyCandidates([], At(1)).Count == 0 && s.PolicyCandidates([Evidence(at: -5)], At(1)).Count == 0,
            "snapshot or old evidence became permission");
    }
    private static void NeighborFailureDoesNotFlatten()
    {
        var (s, o) = Pending(); Fill(s, o);
        s.Observe(Sample(2, 3, Transition("neighbor", EvidenceKind.RailFailed, lo: 402, hi: 405)));
        Check(s.PolicyCandidates([Evidence("neighbor", EvidenceKind.RailFailed, at: 3, lo: 402, hi: 405)], At(3))
            .All(x => x.Decision.Action != PolicyAction.Flatten), "neighbor killed owner");
        Check(s.DrainRootAudit().Any(x => x.Reason == "non_owner_failure_ignored"), "ignored neighbor not visible");
    }
    private static void ExactOwnerFailureFlattens()
    {
        var (s, o) = Pending(); Fill(s, o);
        s.Observe(Sample(2, 3, Transition(kind: EvidenceKind.RailFailed)));
        Check(s.PolicyCandidates([], At(100)).Any(x => x.Decision.Action == PolicyAction.Flatten), "owner failure lost or aged away");
    }
    private static void TestedOwnerSurvives()
    {
        var (s, o) = Pending(); Fill(s, o);
        s.Observe(Sample(2, 3, Transition(kind: EvidenceKind.RailTested)));
        Check(s.Roots.Health(s.State.RootBinding, At(3)) == RootHealth.Tested
            && s.PolicyCandidates([], At(3)).All(x => x.Decision.Action != PolicyAction.Flatten), "TEST became FAIL");
    }
    private static void LaterHoldDoesNotMoveOwner()
    {
        var (s, o) = Pending(); Fill(s, o);
        s.Observe(Sample(2, 3, Transition("later", lo: 420, hi: 424)));
        s.PolicyCandidates([Evidence("later", at: 3, lo: 420, hi: 424)], At(3));
        Check(s.State.RootBinding.Owner.Key == Key() && s.State.RootRiskAnchor.Lower == 400, "later root adopted silently");
    }
    private static void WrongEpochCannotFailOwner()
    {
        var (s, o) = Pending(); Fill(s, o);
        var e = new CampaignEvidence { Timestamp = At(3), Source = EvidenceSource.LevelLedger,
            EvidenceEpoch = "old", RailId = "root", Kind = EvidenceKind.RailFailed, Side = EvidenceSide.Demand, Range = Range(400, 404) };
        Check(s.PolicyCandidates([e], At(3)).All(x => x.Decision.Action != PolicyAction.Flatten), "reused ID crossed epoch");
    }
    private static void EpochLossIsUnknownAndVetoesRisk()
    {
        var (s, o) = Pending(); Fill(s, o);
        s.Observe(Sample(2, 3) with { Epoch = "new" });
        Check(s.RootRiskRecoveryReason != null && s.Roots.Health(s.State.RootBinding, At(3)) == RootHealth.Unknown
            && s.PendingRiskExit?.Decision.ReasonCode == "root_owner_tracking_lost"
            && s.PendingRiskExit?.Evidence.Kind == EvidenceKind.Timer, "epoch loss needs an infrastructure exit, not typed failure");
    }
    private static void SameSampleOwnerFailureWins()
    {
        var s = Session();
        s.Observe(Sample(1, 1, Transition(kind: EvidenceKind.RailFailed), Transition()));
        Check(!s.PolicyCandidates([Evidence(kind: EvidenceKind.RailOwned)], At(1)).Any(), "same-sample root resurrected");
    }
    private static void FailureBeforeSubmitRejects()
    {
        var s = Session(); s.Observe(Sample(1, 1), [Claim()]); var e = Evidence(); var d = Decision(s, e);
        s.Observe(Sample(2, 2, Transition(kind: EvidenceKind.RailFailed)));
        Throws(() => s.Reserve(d, e, null, At(2)));
    }
    private static void FailureBeforeFillCancelsAndExits()
    {
        var (s, o) = Pending();
        s.Observe(Sample(2, 2, Transition(kind: EvidenceKind.RailFailed)));
        Check(o.CancelReason == "root_owner_failed" && !s.State.HasPosition, "pending failure did not cancel");
        Fill(s, o, at: 3);
        Check(s.PendingRiskExit.HasValue && s.State.RootBinding.Owner.Key == Key(), "late fill lost owner or exit");
    }
    private static void PartialFailureAndLateFillRetainExit()
    {
        var (s, o) = Pending(); Fill(s, o, 1, false);
        s.Observe(Sample(2, 3, Transition(kind: EvidenceKind.RailFailed)));
        var d = s.PendingRiskExit.Value.Decision;
        Check(o.CancelReason != null && d.Quantity == 1, "partial failure missing exit/cancel");
        s.State.ApplyDecision(d, s.Plan, true, At(3)); s.AcknowledgeRiskExit(d);
        Fill(s, o, 2, true, 4);
        Check(s.State.SimulatedPositionQuantity == 1 && s.PendingRiskExit?.Decision.Quantity == 1, "remaining late fill lost required exit");
    }
    private static void CancelledLateFillRetainsFailure()
    {
        var (s, o) = Pending(); s.Observe(Sample(2, 2, Transition(kind: EvidenceKind.RailFailed)));
        s.Report(o, 0, null, true, At(2), 408); Fill(s, o, 1, true, 3);
        Check(s.PendingRiskExit.HasValue && s.RecoveryReason != null, "cancelled late fill ignored");
    }
    private static void RetryNeedsFreshTriggerAndOwner()
    {
        var (s, o) = Pending(); Fill(s, o);
        s.State.ApplyDecision(new() { Action = PolicyAction.Flatten }, s.Plan, true, At(3)); s.ConfirmFlat(At(3));
        Check(!s.PolicyCandidates([Evidence()], At(3)).Any(x => x.Decision.Action == PolicyAction.AllowProbe), "old trigger retried");
        s.Observe(Sample(2, 4, Transition("next")));
        var e = Evidence("next", EvidenceKind.RailOwned, at: 4);
        var retry = s.Reserve(Decision(s, e), e, null, At(4)); Fill(s, retry, at: 5);
        Check(s.State.ExecutionAttemptCount == 2 && s.State.RootBinding.Owner.Key == Key("next"), "retry retained old owner");
    }
    private static void UnboundReservationRejected()
    {
        var s = Session(); s.Observe(Sample(1, 1), [Claim()]);
        Throws(() => s.Reserve(new() { Action = PolicyAction.AllowProbe, Quantity = 2, RiskAnchor = Range(390, 450) }, Evidence(), null, At(1)));
    }
    private static void DistanceGateAndRevalidation()
    {
        var s = Session(maximum: 8); s.Observe(Sample(1, 1), [Claim()]);
        var d = Decision(s, Evidence());
        Check(s.Roots.Revalidate(d.RootBinding, At(1), 409, 1, 8) == "root_entry_distance_exceeded", "quote move bypassed cap");
        Check(!s.PolicyCandidates([Evidence(price: 409)], At(1)).Any(), "wide probe admitted");
        Check(s.LastRootAdmissionReason == "root_entry_distance_exceeded", "cap rejection invisible");
        var shortSession = Session(CampaignSide.Short, 8); shortSession.Observe(Sample(1, 1), [Claim(side: CampaignSide.Short)]);
        Check(!shortSession.PolicyCandidates([Evidence(side: CampaignSide.Short, price: 395)], At(1)).Any(), "short cap asymmetry");
    }
    private static void UnsetDistanceIsNotAnInventedStop()
    {
        var s = Session(); s.Observe(Sample(1, 1), [Claim()]);
        var e = Evidence(price: 440); var o = s.Reserve(Decision(s, e), e, null, At(1));
        s.Report(o, 2, 440, true, At(2), 440);
        Check(s.PolicyCandidates([new CampaignEvidence { Timestamp = At(3), Kind = EvidenceKind.PriceTouch, Price = 300 }], At(3))
            .All(x => x.Decision.Action != PolicyAction.Flatten), "root_stop_ticks became a stop");
    }
    private static void IncompleteSnapshotCannotAuthorize()
    {
        var s = Session(); s.Observe(Sample(1, 1) with { Complete = false }, [Claim()]);
        Check(!s.PolicyCandidates([Evidence()], At(1)).Any(), "incomplete snapshot admitted root");
    }
    private static void FailedIdentityCannotRevive()
    {
        var ledger = new RootEvidenceLedger(TimeSpan.FromSeconds(30));
        ledger.Observe(Sample(1, 1, Transition(kind: EvidenceKind.RailFailed)), [Claim()]);
        ledger.Observe(Sample(2, 2), []); ledger.Observe(Sample(3, 3, Transition()), [Claim()]);
        Check(ledger.Find(Key()).Health == RootHealth.Failed, "pruned failed ID revived");
    }
    private static void BoundRiskSurvivesSnapshotPruning()
    {
        var (s, o) = Pending(); Fill(s, o);
        s.Observe(Sample(2, 3, Transition(kind: EvidenceKind.RailFailed)));
        s.Observe(Sample(3, 4), []);
        Check(s.PolicyCandidates([], At(40)).Any(x => x.Decision.Action == PolicyAction.Flatten), "pruning lost failed owner");
    }
    private static void BindingIsFrozen()
    {
        var (s, o) = Pending(); var original = o.Decision.RootBinding;
        s.Observe(Sample(2, 2, Transition(kind: EvidenceKind.RailTested)));
        Check(original.Owner.Health == RootHealth.Live && s.Roots.Health(original, At(2)) == RootHealth.Tested,
            "entry facts mutated with later health");
    }
    private static void ParserValidatesOptionalDistance()
    {
        string json = """
            {"schema_version":2,"kind":"KAHN_CAMPAIGN","id":"test","status":"draft","created_at":"2026-09-09T14:00:00Z","side":"long",
             "window":{"not_before":"2026-09-09T14:00:00Z","expires_at":"2026-09-09T15:00:00Z"},"arena":{"lower":300,"upper":600},
             "risk":{"max_root_entry_distance_ticks":8},"waypoints":[{"id":"root","role":"trap_probe","range":{"lower":400,"upper":410}}]}
            """;
        Check(CampaignPlanParser.Parse(json).Risk.MaxRootEntryDistanceTicks == 8, "distance setting lost");
        Check(CampaignPlanParser.Parse(json.Replace(":8}", ":null}")).Risk.MaxRootEntryDistanceTicks == null, "unset cap manufactured");
        try { CampaignPlanParser.Parse(json.Replace(":8}", ":0}")); }
        catch (Exception) { return; }
        throw new Exception("invalid cap accepted");
    }

    private static void ChangedIdentityGeometryIsUnknown()
    {
        var (s, o) = Pending(); Fill(s, o);
        s.Observe(Sample(2, 3), [Claim(lower: 390)]);
        Check(!s.Roots.Available && s.RootRiskRecoveryReason != null, "same identity silently widened");
    }
    private static void OlderEpochSampleCannotRestoreAuthority()
    {
        var s = Session(); s.Observe(Sample(1, 1), [Claim()]);
        s.Observe(Sample(2, 0) with { Epoch = "old" });
        Check(!s.Roots.Available && s.Roots.Epoch == "epoch", "old epoch adopted out of order");
    }
    private static void UnattestedExternalCannotProbe()
    {
        var s = Session(); s.Observe(Sample(1, 1), [Claim()]);
        var e = new CampaignEvidence { EventId = "external", Timestamp = At(1), Source = EvidenceSource.LevelLedger,
            Kind = EvidenceKind.RailOwned, RailId = "root", Side = EvidenceSide.Demand, Range = Range(400, 404), Price = 408 };
        Check(!s.PolicyCandidates([e], At(1)).Any(), "JSONL forged in-process ownership");
    }
    private static void OwnerFailureHasIndependentRiskLatch()
    {
        var (s, o) = Pending(); Fill(s, o);
        // Root health has its own exit latch; it does not need a build-trial waypoint or policy event.
        s.Observe(Sample(2, 3, Transition(kind: EvidenceKind.RailFailed)));
        Check(s.PendingRiskExit?.Decision.Policy == "root_risk", "root stop delegated to optional build policy");
    }
}
