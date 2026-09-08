using KahnRuntime;
using KahnRuntime.Scaling;

internal static class ScalingTests
{
    private static readonly DateTimeOffset Start = DateTimeOffset.Parse("2026-09-07T14:00:00Z");
    private const string Epoch = "epoch-1";
    private static int _passed;

    public static void RunAll()
    {
        Action[] tests =
        [
            BroadTestStartsRepair, OppositionCanOpenWithoutTest, FreshProofNeedsNoRetest,
            AlreadyHeldProofQualifiesAtFailure, ProofBehindRepairIsValid,
            EveryOpposingIdentityMustFail, SameSampleCannotAddBeforeLaterOpposition,
            SameSampleProofAndFailureCanQualify, TestHoldAloneCannotAdd, PriceAloneCannotFailClaim,
            PriceClearanceAfterTypedFailure, PartialMemberLossKeepsDefense, BreachedGroupCanRebuild,
            OldUntestedRootCannotRescueGroup, FailedIdentityCannotResurrect,
            DelayedProofMustContactRepair, UnrelatedExtensionCannotInheritFailure,
            NewAttackSupersedesUnusedFailure, RepeatedHoldIsNotAnotherEpisode,
            SameAreaNewAttackCanAddAgain, WatchFailureCannotCarryPermission,
            WatchLiveOppositionCanCarry, RetryDoesNotAdoptOldFailure,
            DuplicateSampleIsIdempotent, ContradictoryDuplicateSuspends,
            IncompleteSampleDoesNotPartiallyApply, OutOfOrderSuspends,
            SequenceGapSuspends, WrongEpochSuspends, EpochResetInvalidatesAuthority,
            FormationRemainsUnknown, FormationDoesNotBackdateOwnership,
            GeometryMutationSuspendsAtomically, CoverageUnionKeepsHoles,
            ReflectedShortMatchesLong, EquivalentFragmentationDoesNotMultiply,
            PrefixDoesNotChangeWithSuffix, VetoDoesNotBankPermission,
            CapacityDoesNotStopObserver, QuoteStalenessBlocksAdmission,
            EvidenceStalenessBlocksAdmission, ExecutableClearanceIsRequired,
            SubmissionIsNotFill, PartialFillConsumesOnce, RejectDoesNotRetryOldEpisode,
            UncertainOrderKeepsReservation, BadFillReportDoesNotChangeInventory,
            NewAttackInvalidatesBeforeSubmit, FailedPendingCannotPromote,
            LaterFillPromotesOneBehind, SameAreaFillPreservesActiveAnchor,
            ActiveGroupSurvivesPartialFailure, UntouchedClaimCannotRescueActiveGroup,
            EpochLossDoesNotMeanSponsorFailed, CapacityObservationCannotPromote,
            WarmOppositionAheadOfFillRemainsLive, RepairAreaIncludesObservedContinuation,
            MissingSamplesSuspendEvenWithSequentialIds, QuoteUpdatesCannotHideSampleGap,
            NewAttemptInvalidatesOldGroups, PreSubmitRevalidatesReservation,
            FormationCannotFollowFirstObservation, NonExactTickPricesAreRejected,
            LateFillCannotRescueFailedActiveSponsor,
            ConsumedClosedEpisodeReportsConsumed, FillDuringGapCountsWithoutPromoting,
            PriorEpochCannotBeReused,
            FlatConfirmationDisarmsObservationAuthority,
            UnrelatedExtensionSeedsTheNextDevelopment,
        ];
        foreach (Action test in tests)
        {
            try { test(); _passed++; }
            catch (Exception error) { throw new Exception($"FAIL {test.Method.Name}: {error.Message}", error); }
        }
        Console.WriteLine($"PASS shared repair core ({_passed} checks)");
    }

    private sealed class Fixture
    {
        public RepairEpisodeObserver Observer;
        public long Sequence;
        public CampaignSide Side;
        public Fixture(bool begin = true, CampaignSide side = CampaignSide.Long)
        {
            Side = side;
            Observer = new(side, Range(400, 404), TimeSpan.FromMinutes(1));
            Observer.StartEpoch(Epoch, At(-1), Price(408));
            Step(0, 408, T("root", 400, 404));
            if (begin)
                Begin(0);
        }
        public void Begin(int second, long attempt = 1, bool carry = true)
            => Observer.BeginAttempt(attempt, Range(400, 404), At(second), Price(408), Key("root"), carry);
        public double Price(double price) => Side == CampaignSide.Long ? price : 1200 - price;
        public TickInterval Range(long lo, long hi)
            => Side == CampaignSide.Long ? new(lo, hi) : new(1200 - hi, 1200 - lo);
        public RepairTransition T(string id, long lo, long hi, EvidenceKind kind = EvidenceKind.RailOwned,
            bool opposite = false, DateTimeOffset? formed = null)
            => new(Key(id), kind, opposite ? Other(Side) : Side, Range(lo, hi), formed);
        public RepairSample Sample(int second, double price, params RepairTransition[] events)
            => new(EvidenceSource.LevelLedger, Epoch, Sequence++, At(second), Price(price), events, true);
        public void Step(int second, double price, params RepairTransition[] events)
            => Check(Observer.Observe(Sample(second, price, events)), "sample rejected");
        public void BaseRepair()
        {
            Step(5, 460, T("proof", 420, 424));
            Step(10, 420, T("proof", 420, 424, EvidenceKind.RailTested));
            Step(11, 432, T("claim", 440, 444, opposite: true));
            Step(20, 436, T("proof", 420, 424, EvidenceKind.RailHeld));
        }
        public ScaleOpportunity Complete()
        {
            BaseRepair();
            Step(30, 472, T("claim", 440, 444, EvidenceKind.RailFailed, true));
            return Observer.Opportunity ?? throw new Exception("expected repaired continuation");
        }
    }

    private static void BroadTestStartsRepair()
    {
        var f = new Fixture();
        f.Step(5, 460, f.T("p", 420, 424));
        f.Step(10, 424, f.T("p", 420, 424, EvidenceKind.RailTested));
        Equal(RepairStage.RepairActive, f.Observer.CurrentEpisode.Stage);
        Check(!f.Observer.CurrentEpisode.Breached, "upper-edge test is not a far-edge breach");
    }
    private static void OppositionCanOpenWithoutTest()
    {
        var f = new Fixture();
        f.Step(5, 460, f.T("p", 420, 424));
        f.Step(10, 432, f.T("c", 440, 444, opposite: true));
        Equal(1, f.Observer.CurrentEpisode.OpposingClaims.Count);
    }
    private static void FreshProofNeedsNoRetest()
    {
        var f = new Fixture();
        f.Step(5, 460, f.T("p", 420, 424));
        f.Step(10, 432, f.T("c", 440, 444, opposite: true));
        f.Step(20, 472, f.T("c", 440, 444, EvidenceKind.RailFailed, true));
        Equal(ProofForm.Renewed, f.Observer.Opportunity.Proof.Members.Single().Form);
    }
    private static void AlreadyHeldProofQualifiesAtFailure()
    {
        var f = new Fixture(); var offer = f.Complete();
        Equal(At(30), offer.At);
        Equal(ProofForm.Defended, offer.Proof.Members.Single().Form);
    }
    private static void ProofBehindRepairIsValid()
    {
        var f = new Fixture(); var offer = f.Complete();
        Check(offer.Proof.Coverage.Single().Upper < offer.RepairFrontTicks, "proof may remain behind repair");
    }
    private static void EveryOpposingIdentityMustFail()
    {
        var f = new Fixture(); f.BaseRepair();
        f.Step(21, 436, f.T("nested", 439, 443, opposite: true));
        f.Step(30, 472, f.T("claim", 440, 444, EvidenceKind.RailFailed, true));
        Check(f.Observer.Opportunity == null, "nearby failure must not substitute nested identity");
        f.Step(31, 472, f.T("nested", 439, 443, EvidenceKind.RailFailed, true));
        Equal(At(31), f.Observer.Opportunity.At);
    }
    private static void SameSampleCannotAddBeforeLaterOpposition()
    {
        var f = new Fixture(); f.BaseRepair();
        f.Step(30, 472, f.T("claim", 440, 444, EvidenceKind.RailFailed, true),
            f.T("nested", 448, 452, opposite: true));
        Check(f.Observer.Opportunity == null, "complete sample must block transient permission");
    }
    private static void SameSampleProofAndFailureCanQualify()
    {
        var f = new Fixture(); f.Step(5, 460);
        f.Step(10, 432, f.T("c", 440, 444, opposite: true));
        f.Step(30, 472, f.T("c", 440, 444, EvidenceKind.RailFailed, true), f.T("p", 441, 443));
        Check(f.Observer.Opportunity != null, "joint state should qualify after complete sample");
    }
    private static void TestHoldAloneCannotAdd()
    {
        var f = new Fixture();
        f.Step(5, 460, f.T("p", 420, 424));
        f.Step(10, 424, f.T("p", 420, 424, EvidenceKind.RailTested));
        f.Step(20, 472, f.T("p", 420, 424, EvidenceKind.RailHeld));
        Check(f.Observer.Opportunity == null, "TEST/HOLD is not typed opposing failure");
    }
    private static void PriceAloneCannotFailClaim()
    {
        var f = new Fixture(); f.BaseRepair(); f.Observer.ObservePrice(At(30), 500);
        Check(f.Observer.Opportunity == null, "price cannot invent failure");
    }
    private static void PriceClearanceAfterTypedFailure()
    {
        var f = new Fixture(); f.BaseRepair();
        f.Step(30, 443, f.T("claim", 440, 444, EvidenceKind.RailFailed, true));
        Check(f.Observer.Opportunity == null, "typed failure without clearance");
        f.Observer.ObservePrice(At(31), 472);
        Equal(At(31), f.Observer.Opportunity.At);
    }
    private static void PartialMemberLossKeepsDefense()
    {
        var f = new Fixture(); f.BaseRepair();
        f.Step(21, 436, f.T("other", 425, 426));
        f.Step(22, 436, f.T("other", 425, 426, EvidenceKind.RailFailed));
        f.Step(30, 472, f.T("claim", 440, 444, EvidenceKind.RailFailed, true));
        Equal("proof", f.Observer.Opportunity.Proof.Members.Single().Key.RailId);
    }
    private static void BreachedGroupCanRebuild()
    {
        var f = new Fixture(); f.BaseRepair();
        f.Step(21, 418, f.T("proof", 420, 424, EvidenceKind.RailFailed));
        f.Step(25, 436, f.T("replacement", 420, 424));
        f.Step(30, 472, f.T("claim", 440, 444, EvidenceKind.RailFailed, true));
        Equal(ProofForm.Rebuilt, f.Observer.Opportunity.Proof.Members.Single().Form);
    }
    private static void OldUntestedRootCannotRescueGroup()
    {
        var f = new Fixture(); f.BaseRepair();
        f.Step(21, 418, f.T("proof", 420, 424, EvidenceKind.RailFailed));
        f.Step(30, 472, f.T("claim", 440, 444, EvidenceKind.RailFailed, true));
        Check(f.Observer.Opportunity == null, "untested root cannot replace failed proof");
    }
    private static void FailedIdentityCannotResurrect()
    {
        var f = new Fixture(); f.BaseRepair();
        f.Step(21, 418, f.T("proof", 420, 424, EvidenceKind.RailFailed));
        f.Step(25, 436, f.T("proof", 420, 424));
        f.Step(30, 472, f.T("claim", 440, 444, EvidenceKind.RailFailed, true));
        Check(f.Observer.Opportunity == null, "failed identity is terminal");
        Equal(EvidenceKind.RailFailed, f.Observer.Find(Key("proof")).LastKind);
    }
    private static Fixture Awaiting()
    {
        var f = new Fixture(); f.Step(5, 460);
        f.Step(10, 432, f.T("c", 440, 444, opposite: true));
        f.Step(30, 448, f.T("c", 440, 444, EvidenceKind.RailFailed, true));
        Equal(RepairStage.ResolvedAwaitingProof, f.Observer.CurrentEpisode.Stage);
        return f;
    }
    private static void DelayedProofMustContactRepair()
    {
        var f = Awaiting(); f.Step(35, 450, f.T("p", 441, 443));
        Check(f.Observer.Opportunity != null, "new claim inside repair needs no retest");
    }
    private static void UnrelatedExtensionCannotInheritFailure()
    {
        var f = Awaiting(); f.Step(35, 488, f.T("unrelated", 480, 484));
        Check(f.Observer.Opportunity == null, "old failure cannot authorize unrelated extension");
        Equal("unrelated_extension", f.Observer.LastClosedEpisode.Outcome);
        f.Step(40, 490, f.T("late", 441, 443));
        Check(f.Observer.Opportunity == null, "superseded failure must remain unavailable");
    }
    private static void NewAttackSupersedesUnusedFailure()
    {
        var f = Awaiting(); f.Step(35, 446, f.T("c2", 446, 450, opposite: true));
        f.Step(40, 455, f.T("p", 441, 443));
        Check(f.Observer.Opportunity == null, "new opposition remains live");
    }
    private static void RepeatedHoldIsNotAnotherEpisode()
    {
        var f = new Fixture(); var offer = f.Complete();
        f.Observer.Miss(offer, At(30), "capacity");
        f.Step(40, 472, f.T("proof", 420, 424, EvidenceKind.RailHeld));
        f.Step(50, 480, f.T("proof", 420, 424, EvidenceKind.RailHeld));
        Check(f.Observer.Opportunity == null, "repeated HOLD cannot rearm spent permission");
    }
    private static void NextSameArea(Fixture f)
    {
        f.Step(40, 424, f.T("proof", 420, 424, EvidenceKind.RailTested));
        f.Step(41, 436, f.T("c2", 440, 444, opposite: true));
        f.Step(50, 436, f.T("proof", 420, 424, EvidenceKind.RailHeld));
        f.Step(60, 472, f.T("c2", 440, 444, EvidenceKind.RailFailed, true));
    }
    private static void SameAreaNewAttackCanAddAgain()
    {
        var f = new Fixture(); var first = f.Complete(); NextSameArea(f);
        Check(f.Observer.Opportunity.EpisodeId != first.EpisodeId, "new attack has new lineage");
        Equal(first.Proof.Coverage.Single(), f.Observer.Opportunity.Proof.Coverage.Single());
    }
    private static void WatchFailureCannotCarryPermission()
    {
        var f = new Fixture(false); f.BaseRepair();
        f.Step(30, 472, f.T("claim", 440, 444, EvidenceKind.RailFailed, true));
        Check(f.Observer.Opportunity == null, "WATCH cannot authorize scale");
        f.Begin(31); f.Step(40, 472, f.T("new", 442, 443));
        Check(f.Observer.Opportunity == null, "pre-fill failure cannot be banked");
    }
    private static void WatchLiveOppositionCanCarry()
    {
        var f = new Fixture(false); f.BaseRepair();
        f.Observer.BeginAttempt(1, f.Range(400, 404), At(21), 460, Key("root"));
        f.Step(25, 448, f.T("new", 441, 443));
        f.Step(30, 472, f.T("claim", 440, 444, EvidenceKind.RailFailed, true));
        Check(f.Observer.Opportunity != null, "live pre-fill opposition should carry");
    }
    private static void RetryDoesNotAdoptOldFailure()
    {
        var f = new Fixture(); f.Complete(); f.Begin(31, 2, false);
        f.Step(40, 472, f.T("new", 441, 443));
        Check(f.Observer.Opportunity == null, "retry starts a fresh episode lineage");
    }
    private static void DuplicateSampleIsIdempotent()
    {
        var f = new Fixture(); var sample = f.Sample(5, 460, f.T("p", 420, 424));
        Check(f.Observer.Observe(sample), "first sample");
        int count = f.Observer.KnownClaimCount;
        Check(f.Observer.Observe(sample), "duplicate sample"); Equal(count, f.Observer.KnownClaimCount);
    }
    private static void ContradictoryDuplicateSuspends()
    {
        var f = new Fixture(); var sample = f.Sample(5, 460, f.T("p", 420, 424));
        f.Observer.Observe(sample); f.Observer.Observe(sample with { PriceTicks = 461 });
        Check(f.Observer.Suspended, "changed duplicate is not idempotent");
    }
    private static void IncompleteSampleDoesNotPartiallyApply()
    {
        var f = new Fixture(); int before = f.Observer.KnownClaimCount;
        f.Observer.Observe(f.Sample(5, 460, f.T("p", 420, 424)) with { Complete = false });
        Check(f.Observer.Suspended, "incomplete batch cannot grant authority"); Equal(before, f.Observer.KnownClaimCount);
    }
    private static void OutOfOrderSuspends()
    {
        var f = new Fixture(); f.Step(10, 460);
        f.Observer.Observe(f.Sample(5, 460)); Check(f.Observer.Suspended, "out-of-order observation");
    }
    private static void SequenceGapSuspends()
    {
        var f = new Fixture(); f.Sequence++;
        f.Observer.Observe(f.Sample(5, 460)); Check(f.Observer.Suspended, "missing complete sample");
    }
    private static void WrongEpochSuspends()
    {
        var f = new Fixture(); f.Observer.Observe(f.Sample(5, 460) with { Epoch = "other" });
        Check(f.Observer.Suspended, "mixed epoch sample");
    }
    private static void EpochResetInvalidatesAuthority()
    {
        var f = new Fixture(); var offer = f.Complete();
        f.Observer.StartEpoch("epoch-2", At(31), 472);
        Check(f.Observer.Opportunity == null, "reset clears authority");
        Equal(GroupHealth.Unknown, f.Observer.Health(offer.Proof));
    }
    private static void FormationRemainsUnknown()
    {
        var f = new Fixture(); f.Step(5, 460, f.T("p", 420, 424));
        Check(f.Observer.Find(Key("p")).FormedAt == null, "OWN is not formation time");
    }
    private static void FormationDoesNotBackdateOwnership()
    {
        var f = Awaiting(); f.Step(35, 450, f.T("p", 441, 443, formed: At(15)));
        Equal(At(35), f.Observer.Opportunity.At); Equal(At(15), f.Observer.Find(Key("p")).FormedAt.Value);
    }
    private static void GeometryMutationSuspendsAtomically()
    {
        var f = new Fixture(); f.Step(5, 460, f.T("p", 420, 424)); int before = f.Observer.KnownClaimCount;
        f.Observer.Observe(f.Sample(10, 430, f.T("other", 430, 431), f.T("p", 419, 424, EvidenceKind.RailHeld)));
        Equal(before, f.Observer.KnownClaimCount); Check(f.Observer.Suspended, "identity geometry changed");
    }
    private static void CoverageUnionKeepsHoles()
    {
        var ranges = TickInterval.Union([new(400, 402), new(402, 404), new(420, 424)]);
        Equal(2, ranges.Count); Equal(new TickInterval(400, 404), ranges[0]);
    }
    private static void ReflectedShortMatchesLong()
    {
        var l = new Fixture(); var s = new Fixture(side: CampaignSide.Short);
        var a = l.Complete(); var b = s.Complete();
        Equal(a.At, b.At); Equal(a.Proof.Members.Single().Form, b.Proof.Members.Single().Form);
        Equal(new TickInterval(1200 - a.Proof.Coverage[0].Upper, 1200 - a.Proof.Coverage[0].Lower), b.Proof.Coverage[0]);
    }
    private static void EquivalentFragmentationDoesNotMultiply()
    {
        var one = new Fixture(); var a = one.Complete();
        var f = new Fixture();
        f.Step(5, 460, f.T("p1", 420, 422), f.T("p2", 422, 424));
        f.Step(10, 420, f.T("p1", 420, 422, EvidenceKind.RailTested), f.T("p2", 422, 424, EvidenceKind.RailTested));
        f.Step(11, 432, f.T("c1", 440, 442, opposite: true), f.T("c2", 442, 444, opposite: true));
        f.Step(20, 436, f.T("p1", 420, 422, EvidenceKind.RailHeld), f.T("p2", 422, 424, EvidenceKind.RailHeld));
        f.Step(30, 472, f.T("c1", 440, 442, EvidenceKind.RailFailed, true), f.T("c2", 442, 444, EvidenceKind.RailFailed, true));
        Equal(a.At, f.Observer.Opportunity.At); Equal(a.Proof.Coverage.Single(), f.Observer.Opportunity.Proof.Coverage.Single());
        Equal(1, f.Observer.DrainAudit().Count(x => x.Reason == "repaired_continuation_eligible"));
    }
    private static void PrefixDoesNotChangeWithSuffix()
    {
        var f = new Fixture(); var offer = f.Complete(); var before = offer.Proof.Members.ToArray();
        f.Step(40, 480, f.T("future", 470, 474, opposite: true));
        Check(before.SequenceEqual(offer.Proof.Members), "later evidence mutated an earlier proof snapshot");
    }

    private static ScaleAdmissionContext Context(Fixture f, int second = 30, int quantity = 2)
        => new(At(second), At(second), TimeSpan.FromSeconds(2), TimeSpan.FromSeconds(2),
            f.Side == CampaignSide.Long ? 471 : 727, f.Side == CampaignSide.Long ? 473 : 729,
            f.Price(408), quantity, 2, 8, 8, true, true, true, true, false);
    private static ScaleOrderReservations Orders(Fixture f, out GroupSponsorState sponsors)
    {
        sponsors = new(f.Side, f.Range(400, 404)); return new(f.Observer, sponsors);
    }
    private static void VetoDoesNotBankPermission()
    {
        var f = new Fixture(); var offer = f.Complete(); var orders = Orders(f, out _);
        Check(!orders.TryReserve(offer, Context(f) with { PolicyAllowsAdd = false }, out _, out var reason), "veto");
        Equal("policy_veto", reason);
        Check(!orders.TryReserve(offer, Context(f), out _, out _), "later capacity cannot revive missed episode");
    }
    private static void CapacityDoesNotStopObserver()
    {
        var f = new Fixture(); var offer = f.Complete(); var orders = Orders(f, out _);
        orders.TryReserve(offer, Context(f, quantity: 8), out _, out var reason); Equal("capacity", reason);
        NextSameArea(f); Check(f.Observer.Opportunity != null, "observer keeps building at cap");
    }
    private static void QuoteStalenessBlocksAdmission()
    {
        var f = new Fixture(); var offer = f.Complete(); var orders = Orders(f, out _);
        Check(!orders.TryReserve(offer, Context(f) with { QuoteAt = At(20) }, out _, out var reason), "stale quote");
        Equal("stale_or_invalid_market", reason);
    }
    private static void EvidenceStalenessBlocksAdmission()
    {
        var f = new Fixture(); var offer = f.Complete(); var orders = Orders(f, out _);
        Check(!orders.TryReserve(offer, Context(f, 40), out _, out var reason), "stale evidence");
        Equal("stale_or_invalid_market", reason);
    }
    private static void ExecutableClearanceIsRequired()
    {
        var f = new Fixture(); var offer = f.Complete(); var orders = Orders(f, out _);
        Check(!orders.TryReserve(offer, Context(f) with { BidTicks = 444, AskTicks = 446 }, out _, out var reason), "BBO clearance");
        Equal("repair_not_clear", reason);
    }
    private static (Fixture F, ScaleOrderReservations Orders, GroupSponsorState Sponsors, ScaleReservationSnapshot Order) Reserved()
    {
        var f = new Fixture(); var offer = f.Complete(); var orders = Orders(f, out var sponsors);
        Check(orders.TryReserve(offer, Context(f), out var order, out var reason), reason);
        return (f, orders, sponsors, order);
    }
    private static void SubmissionIsNotFill()
    {
        var x = Reserved(); x.Orders.AcknowledgeSubmission(x.Order.Id, "broker-1");
        Equal(0, x.Sponsors.FilledAddCount); Equal(0, x.Orders.Outstanding.FilledQuantity);
        Check(x.Sponsors.Pending == null, "submission cannot queue sponsor");
        Check(!x.Orders.TryReserve(x.Order.Opportunity, Context(x.F), out _, out _), "reservation must block duplicates");
    }
    private static void PartialFillConsumesOnce()
    {
        var x = Reserved(); x.Orders.AcknowledgeSubmission(x.Order.Id, "broker-1");
        Check(x.Orders.Report(x.Order.Id, 1, 473, false, At(30), 471), "first partial fill");
        Check(x.F.Observer.Opportunity == null, "first partial consumes episode");
        Equal(1, x.Sponsors.FilledAddCount); Equal(1, x.Orders.Outstanding.RemainingQuantity);
        Check(!x.Orders.Report(x.Order.Id, 2, 474, true, At(31), 471), "second fill is not second add");
        Equal(1, x.Sponsors.FilledAddCount); Equal(4, x.Orders.Find(x.Order.Id).ObservedPositionQuantity);
        Equal(441.0, x.Orders.Find(x.Order.Id).ObservedAverageTicks);
        Check(!x.Orders.Report(x.Order.Id, 2, 474, true, At(32), 471), "duplicate terminal idempotent");
        Check(!x.Orders.HasUnresolvedOrder, "terminal fill releases outstanding capacity");
    }
    private static void RejectDoesNotRetryOldEpisode()
    {
        var x = Reserved(); x.Orders.Report(x.Order.Id, 0, null, true, At(30), 471);
        Equal(0, x.Sponsors.FilledAddCount); Check(!x.Orders.HasUnresolvedOrder, "reject releases capacity");
        Check(!x.Orders.TryReserve(x.Order.Opportunity, Context(x.F), out _, out _), "no automatic retry loop");
    }
    private static void UncertainOrderKeepsReservation()
    {
        var x = Reserved(); x.Orders.MarkUncertain(x.Order.Id, "submission_timeout");
        Check(x.Orders.HasUnresolvedOrder, "unknown submission must retain reservation");
        Equal(ScaleOrderState.Uncertain, x.Orders.Outstanding.State);
        Check(!x.Orders.TryReserve(x.Order.Opportunity, Context(x.F), out _, out _), "uncertainty blocks more risk");
    }
    private static void BadFillReportDoesNotChangeInventory()
    {
        var x = Reserved(); Throws(() => x.Orders.Report(x.Order.Id, 3, 474, true, At(31), 471));
        Equal(0, x.Orders.Outstanding.FilledQuantity); Equal(0, x.Sponsors.FilledAddCount);
    }
    private static void NewAttackInvalidatesBeforeSubmit()
    {
        var f = new Fixture(); var offer = f.Complete(); f.Step(31, 468, f.T("c2", 465, 469, opposite: true));
        var orders = Orders(f, out _);
        Check(!orders.TryReserve(offer, Context(f, 31), out _, out _), "new opposition invalidates old permission");
    }

    private static ProofGroup Group(Fixture f, string id, int second, long lo, long hi, double price)
    {
        f.Step(second, price, f.T(id, lo, hi));
        return new(id, At(second), [new(Key(id), f.Range(lo, hi), ProofForm.Renewed)],
            f.Observer.Attempt, f.Observer.Generation);
    }
    private static void FailedPendingCannotPromote()
    {
        var x = Reserved(); x.Orders.Report(x.Order.Id, 2, 473, true, At(30), 471);
        x.F.Step(40, 418, x.F.T("proof", 420, 424, EvidenceKind.RailFailed));
        x.Sponsors.Observe(x.F.Observer); Check(x.Sponsors.Pending == null, "failed pending must be discarded");
        var next = Group(x.F, "next", 50, 460, 464, 480);
        x.Sponsors.FirstFill(next, x.F.Observer, 479); Check(x.Sponsors.Active == null, "failed pending cannot promote");
    }
    private static void LaterFillPromotesOneBehind()
    {
        var x = Reserved(); x.Orders.Report(x.Order.Id, 2, 473, true, At(30), 471);
        Check(x.Sponsors.Active == null, "first add retains root");
        var next = Group(x.F, "next", 50, 460, 464, 480);
        x.Sponsors.FirstFill(next, x.F.Observer, 479);
        Equal("proof", x.Sponsors.Active.Members.Single().Key.RailId);
        Equal("next", x.Sponsors.Pending.Members.Single().Key.RailId);
    }
    private static void SameAreaFillPreservesActiveAnchor()
    {
        var x = Reserved(); x.Orders.Report(x.Order.Id, 2, 473, true, At(30), 471);
        NextSameArea(x.F); var next = x.F.Observer.Opportunity;
        Check(x.Orders.TryReserve(next, Context(x.F, 60, 4), out var order, out var reason), reason);
        x.Orders.Report(order.Id, 2, 473, true, At(60), 471);
        Equal(2, x.Sponsors.FilledAddCount); Check(x.Sponsors.Active == null, "same area cannot force risk advancement");
    }
    private static (Fixture F, GroupSponsorState Sponsors) ActiveTwoMemberGroup()
    {
        var f = new Fixture();
        var p = Group(f, "p", 5, 420, 424, 460);
        var q = Group(f, "q", 6, 428, 430, 460);
        var group = new ProofGroup("pair", At(6), p.Members.Concat(q.Members), f.Observer.Attempt, f.Observer.Generation);
        var sponsors = new GroupSponsorState(CampaignSide.Long, new(400, 404));
        sponsors.FirstFill(group, f.Observer, 459);
        var child = Group(f, "child", 10, 460, 464, 480);
        sponsors.FirstFill(child, f.Observer, 479);
        return (f, sponsors);
    }
    private static void ActiveGroupSurvivesPartialFailure()
    {
        var x = ActiveTwoMemberGroup(); x.F.Step(15, 419, x.F.T("p", 420, 424, EvidenceKind.RailFailed));
        x.Sponsors.Observe(x.F.Observer); Equal(GroupHealth.Live, x.Sponsors.ActiveHealth);
        Equal(2, x.Sponsors.Active.Coverage.Count);
    }
    private static void UntouchedClaimCannotRescueActiveGroup()
    {
        var x = ActiveTwoMemberGroup(); Group(x.F, "untouched", 12, 426, 427, 480);
        x.F.Step(15, 419, x.F.T("p", 420, 424, EvidenceKind.RailFailed), x.F.T("q", 428, 430, EvidenceKind.RailFailed));
        x.Sponsors.Observe(x.F.Observer); Equal(GroupHealth.Failed, x.Sponsors.ActiveHealth);
    }
    private static void EpochLossDoesNotMeanSponsorFailed()
    {
        var x = ActiveTwoMemberGroup(); x.F.Observer.StartEpoch("new-epoch", At(15), 480);
        x.Sponsors.Observe(x.F.Observer); Equal(GroupHealth.Unknown, x.Sponsors.ActiveHealth);
        Check(x.Sponsors.Active != null, "reset is not a sponsor failure or silent re-anchor");
    }
    private static void CapacityObservationCannotPromote()
    {
        var x = Reserved(); x.Orders.Report(x.Order.Id, 2, 473, true, At(30), 471);
        Group(x.F, "next", 50, 460, 464, 480); x.Sponsors.Observe(x.F.Observer);
        Check(x.Sponsors.Active == null, "observation alone cannot promote pending");
    }

    private static void WarmOppositionAheadOfFillRemainsLive()
    {
        var f = new Fixture(false);
        f.Step(5, 450, f.T("opposition", 440, 444, opposite: true));
        f.Begin(10);
        Equal(1, f.Observer.CurrentEpisode.OpposingClaims.Count);
        f.Step(20, 430, f.T("new", 420, 424));
        f.Step(30, 472, f.T("opposition", 440, 444, EvidenceKind.RailFailed, true));
        Check(f.Observer.Opportunity != null, "known live challenge above fill must be carried");
    }

    private static void RepairAreaIncludesObservedContinuation()
    {
        var f = new Fixture(); f.Step(5, 440);
        f.Step(10, 435, f.T("opposition", 460, 464, opposite: true));
        f.Step(20, 455, f.T("rebuilt", 448, 452));
        f.Step(30, 472, f.T("opposition", 460, 464, EvidenceKind.RailFailed, true));
        Check(f.Observer.Opportunity != null, "actual path through the repair links proof, without owning its gaps");
        Equal(new TickInterval(448, 452), f.Observer.Opportunity.Proof.Coverage.Single());
    }

    private static void MissingSamplesSuspendEvenWithSequentialIds()
    {
        var f = new Fixture(); f.Complete();
        f.Observer.Observe(f.Sample(120, 472));
        Check(f.Observer.Suspended && f.Observer.Opportunity == null, "time gap must invalidate authority");
    }
    private static void QuoteUpdatesCannotHideSampleGap()
    {
        var f = new Fixture(); f.Complete(); f.Observer.ObservePrice(At(120), 472);
        Check(f.Observer.Suspended, "fresh quotes cannot conceal missing LL samples");
    }
    private static void NewAttemptInvalidatesOldGroups()
    {
        var f = new Fixture(); var offer = f.Complete(); f.Begin(31, 2);
        Equal(GroupHealth.Unknown, f.Observer.Health(offer.Proof));
        Check(f.Observer.CurrentProof(offer.Proof, 472) == null, "old attempt cannot sponsor new attempt");
    }
    private static void PreSubmitRevalidatesReservation()
    {
        var x = Reserved();
        Equal(null, x.Orders.RevalidateBeforeSubmit(x.Order.Id, Context(x.F)));
        x.F.Step(31, 468, x.F.T("new", 465, 469, opposite: true));
        Equal("opportunity_not_current", x.Orders.RevalidateBeforeSubmit(x.Order.Id, Context(x.F, 31)));
        Check(x.Orders.HasUnresolvedOrder, "revalidation is not a cancellation acknowledgement");
    }
    private static void FormationCannotFollowFirstObservation()
    {
        var f = new Fixture(); f.Step(5, 460, f.T("p", 420, 424));
        f.Observer.Observe(f.Sample(10, 460, f.T("p", 420, 424, EvidenceKind.RailHeld, formed: At(6))));
        Check(f.Observer.Suspended, "formation after a known claim is contradictory");
    }
    private static void NonExactTickPricesAreRejected()
    {
        var f = new Fixture(); f.Observer.Observe(f.Sample(5, double.MaxValue));
        Check(f.Observer.Suspended, "out-of-range double must not wrap into a tick interval");
    }
    private static void LateFillCannotRescueFailedActiveSponsor()
    {
        var x = ActiveTwoMemberGroup();
        x.F.Step(15, 419, x.F.T("p", 420, 424, EvidenceKind.RailFailed), x.F.T("q", 428, 430, EvidenceKind.RailFailed));
        var later = Group(x.F, "later", 20, 480, 484, 500);
        x.Sponsors.FirstFill(later, x.F.Observer, 499);
        Equal(GroupHealth.Failed, x.Sponsors.ActiveHealth);
        Equal("pair", x.Sponsors.Active.EpisodeId);
    }
    private static void ConsumedClosedEpisodeReportsConsumed()
    {
        var x = Reserved();
        Equal(RepairStage.Reserved, x.F.Observer.LastClosedEpisode.Stage);
        Equal(RepairStage.Reserved, x.F.Observer.Stage);
        x.Orders.Report(x.Order.Id, 1, 473, false, At(30), 471);
        Equal(RepairStage.Consumed, x.F.Observer.LastClosedEpisode.Stage);
    }
    private static void FillDuringGapCountsWithoutPromoting()
    {
        var x = Reserved(); x.Orders.Report(x.Order.Id, 1, 473, false, At(120), 471);
        Equal(1, x.Sponsors.FilledAddCount); Equal(1, x.Orders.Outstanding.FilledQuantity);
        Check(x.F.Observer.Suspended, "stale observation suspends new scale authority");
        Check(x.Sponsors.Pending == null && x.Sponsors.Active == null, "a real fill cannot refresh stale proof");
    }
    private static void PriorEpochCannotBeReused()
    {
        var f = new Fixture(); f.Observer.StartEpoch("epoch-2", At(5), 460);
        Throws(() => f.Observer.StartEpoch(Epoch, At(10), 460));
    }
    private static void FlatConfirmationDisarmsObservationAuthority()
    {
        var f = new Fixture(); f.Complete(); f.Observer.EndFlatAttempt(At(31), "root_closed");
        NextSameArea(f);
        Check(f.Observer.Opportunity == null, "observation after flatness cannot authorize a new attempt");
        Throws(() => f.Begin(61, 1));
        f.Begin(61, 2, false);
        Check(f.Observer.Opportunity == null, "reentry does not inherit the flat interval's completion");
    }
    private static void UnrelatedExtensionSeedsTheNextDevelopment()
    {
        var f = Awaiting(); f.Step(35, 488, f.T("new-development", 480, 484));
        Check(f.Observer.Opportunity == null, "new development cannot inherit the old failure");
        f.Step(40, 484, f.T("new-repair", 490, 494, opposite: true));
        f.Step(50, 500, f.T("new-repair", 490, 494, EvidenceKind.RailFailed, true));
        Equal("new-development", f.Observer.Opportunity.Proof.Members.Single().Key.RailId);
        Equal("new-repair", f.Observer.Opportunity.OpposingClaims.Single().RailId);
    }

    private static CampaignSide Other(CampaignSide side) => side == CampaignSide.Long ? CampaignSide.Short : CampaignSide.Long;
    private static ClaimKey Key(string id) => new(EvidenceSource.LevelLedger, Epoch, id);
    private static DateTimeOffset At(int seconds) => Start.AddSeconds(seconds);
    private static void Check(bool value, string message) { if (!value) throw new Exception(message); }
    private static void Equal<T>(T expected, T actual) => Check(EqualityComparer<T>.Default.Equals(expected, actual), $"expected {expected}, got {actual}");
    private static void Throws(Action action)
    {
        try { action(); } catch (ArgumentException) { return; } catch (InvalidOperationException) { return; }
        throw new Exception("expected rejected operation");
    }
}
