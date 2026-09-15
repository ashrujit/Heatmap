using KahnRuntime;
using KahnRuntime.Scaling;

internal static partial class RootRiskTests
{
    private static void RunRecoveryTests()
    {
        Action[] tests = [GapSampleCannotEnter, SuspendedReservationCannotEnter,
            DelayedFillRetainsOwner, WarmupFailureStillExits, TransientGapIsNotFailure,
            MissingOwnerIsTrackingLoss, EpochLossBeforeLateFillExits, InvalidRecoveryPriceStillManagesRisk,
            RecoveryDiscardsOldScalePermission, ActiveGroupSurvivesObservationRecovery,
            FailedGroupExitsDuringWarmup, GroupTrackingLossExits, ChangedOwnerGeometryExits];
        foreach (var test in tests)
        {
            try { test(); }
            catch (Exception error) { throw new Exception("FAIL " + test.Method.Name + ": " + error.Message, error); }
        }
        Console.WriteLine($"PASS root and sponsor recovery ({tests.Length} checks)");
        RunEngineRecoveryTests();
    }

    private static void GapSampleCannotEnter()
    {
        var s = Session(); s.Observe(Sample(1, 1), [Claim()]);
        s.Observe(Sample(2, 40, Transition("next")));
        Check(s.Observer.Suspended && s.Roots.Available, "fixture did not expose independent health");
        Check(!s.PolicyCandidates([Evidence("next", EvidenceKind.RailOwned, at: 40)], At(40)).Any()
            && s.LastRootAdmissionReason == "root_observation_recovering", "gap sample admitted root before reset");
    }

    private static void SuspendedReservationCannotEnter()
    {
        var s = Session(); s.Observe(Sample(1, 1), [Claim()]);
        var e = Evidence(); var d = Decision(s, e);
        s.Observer.Suspend(At(1), "gap_after_decision");
        Throws(() => s.Reserve(d, e, null, At(1)));
    }

    private static void DelayedFillRetainsOwner()
    {
        var (s, o) = Pending(); Fill(s, o, at: 40);
        Check(s.Observer.Suspended, "delayed fill fixture was still fresh");
        var binding = s.State.RootBinding;
        s.SuspendObservation(At(41), "processing_gap");
        s.ObserveRootSample(Sample(2, 42), [Claim()]);
        Check(s.Roots.Health(binding, At(42)) == RootHealth.Live && s.PendingRiskExit == null,
            "warmup orphaned live owner");
        s.Observe(Sample(3, 72), [Claim()], recoverScale: true);
        Check(s.State.RootBinding == binding && !s.Observer.Suspended && s.Reservations != null
            && s.Observer.Opportunity == null, "deferred root failed to recover without old permission");
        s.Observe(Sample(4, 73, Transition(kind: EvidenceKind.RailFailed)));
        Check(s.PendingRiskExit?.Decision.ReasonCode == "root_owner_failed", "recovered root no longer failed");
    }

    private static void WarmupFailureStillExits()
    {
        var (s, o) = Pending(); Fill(s, o);
        s.SuspendObservation(At(3), "feed_gap");
        s.ObserveRootSample(Sample(2, 40) with { PriceTicks = double.NaN },
            [Claim() with { FailedAt = At(40), UpdatedAt = At(40), LastKind = EvidenceKind.RailFailed }]);
        Check(s.Observer.Suspended && s.PendingRiskExit?.Decision.ReasonCode == "root_owner_failed",
            "warmup or missing executable quote swallowed LL risk failure");
    }

    private static void TransientGapIsNotFailure()
    {
        var (s, o) = Pending(); Fill(s, o);
        s.SuspendObservation(At(3), "connection_gap");
        Check(s.PolicyCandidates([], At(100)).Count == 0 && s.RootRiskRecoveryReason == "root_owner_health_unknown",
            "gap manufactured auction failure");
        s.ObserveRootSample(Sample(2, 101), [Claim()]);
        Check(s.RootRiskRecoveryReason == null && s.PendingRiskExit == null, "same owner did not restore health");
    }

    private static void MissingOwnerIsTrackingLoss()
    {
        var (s, o) = Pending(); Fill(s, o);
        s.ObserveRootSample(Sample(2, 3), []);
        Check(s.PendingRiskExit?.Decision.ReasonCode == "root_owner_tracking_lost"
            && !s.State.ExecutionAuthorized && s.PendingRiskExit?.Evidence.Kind != EvidenceKind.RailFailed,
            "complete missing-owner snapshot left unmonitored inventory");
    }

    private static void EpochLossBeforeLateFillExits()
    {
        var (s, o) = Pending();
        s.ObserveRootSample(Sample(2, 2) with { Epoch = "new" });
        Check(o.TrackingLostBeforeFill && o.CancelReason != null, "lost pending owner was not cancelled");
        s.Report(o, 0, null, true, At(2), 408);
        Fill(s, o, 1, true, 3);
        Check(s.PendingRiskExit?.Decision.ReasonCode == "root_owner_tracking_lost", "late fill lost safety exit");
        var d = s.PendingRiskExit.Value.Decision;
        s.State.ApplyDecision(d, s.Plan, true, At(3)); s.AcknowledgeRiskExit(d);
        Fill(s, o, 2, true, 4);
        Check(s.State.SimulatedPositionQuantity == 1 && s.PendingRiskExit?.Decision.Quantity == 1,
            "later partial escaped latched tracking loss");
    }

    private static void InvalidRecoveryPriceStillManagesRisk()
    {
        var (s, o) = Pending(); Fill(s, o);
        s.Observe(Sample(2, 3) with { Epoch = "new", PriceTicks = double.NaN }, recoverScale: true);
        Check(s.PendingRiskExit?.Decision.ReasonCode == "root_owner_tracking_lost"
            && s.Observer.Suspended, "invalid recovery price threw before risk evaluation");
    }

    private static (CampaignSession Session, ProofGroup Active, ProofGroup Pending) PromotedGroup()
    {
        var (s, o) = Pending(); Fill(s, o);
        s.Observe(Sample(2, 3, Transition("a", lo: 420, hi: 424), Transition("b", lo: 440, hi: 444)) with { PriceTicks = 480 });
        ProofGroup Group(string id, long lower) => new(id, At(3),
            [new(Key(id), new(lower, lower + 4), ProofForm.Defended)], s.Observer.Attempt, s.Observer.Generation);
        var a = Group("a", 420); var b = Group("b", 440);
        s.Sponsors.FirstFill(a, s.Observer, 480, s.Roots, At(3));
        s.Sponsors.FirstFill(b, s.Observer, 480, s.Roots, At(3));
        s.RefreshRiskHealth(At(3));
        Check(s.State.GroupSponsorActive, "fixture did not promote a sponsor");
        return (s, a, b);
    }

    private static void RecoveryDiscardsOldScalePermission()
    {
        var (s, a, b) = PromotedGroup();
        s.SuspendObservation(At(4), "gap");
        s.Observe(Sample(3, 40) with { PriceTicks = 480 }, recoverScale: true);
        Check(s.Observer.CurrentProof(a, 480) == null && s.Observer.CurrentProof(b, 480) == null
            && s.Observer.Opportunity == null, "pre-gap proof authorized fresh leverage");
    }

    private static void ActiveGroupSurvivesObservationRecovery()
    {
        var (s, a, b) = PromotedGroup();
        s.SuspendObservation(At(4), "gap");
        s.Observe(Sample(3, 40) with { PriceTicks = 480 }, recoverScale: true);
        Check(s.Sponsors.Active.EpisodeId == a.EpisodeId && s.Sponsors.ActiveHealth == GroupHealth.Live
            && s.RootRiskRecoveryReason == null, "scale recovery orphaned active group");
        s.ObserveRootSample(Sample(4, 41, Transition(kind: EvidenceKind.RailFailed)));
        Check(s.PendingRiskExit == null, "old root overrode promoted sponsor");
    }

    private static void FailedGroupExitsDuringWarmup()
    {
        var (s, _, _) = PromotedGroup();
        s.SuspendObservation(At(4), "gap");
        s.ObserveRootSample(Sample(3, 40, Transition("a", EvidenceKind.RailFailed, lo: 420, hi: 424)));
        Check(s.PolicyCandidates([], At(40)).Any(x => x.Decision.ReasonCode == "active_group_failed"),
            "promoted owner failure lost during warmup");
    }

    private static void GroupTrackingLossExits()
    {
        var (s, _, _) = PromotedGroup();
        s.ObserveRootSample(Sample(3, 4) with { Epoch = "replacement" });
        Check(s.PendingRiskExit?.Decision.ReasonCode == "sponsor_tracking_lost", "lost group held indefinitely");
    }

    private static void ChangedOwnerGeometryExits()
    {
        var (s, o) = Pending(); Fill(s, o);
        s.ObserveRootSample(Sample(2, 3), [Claim(lower: 390)]);
        Check(s.PendingRiskExit?.Decision.ReasonCode == "root_owner_tracking_lost", "owner mutation left risk unmonitored");
    }
}
