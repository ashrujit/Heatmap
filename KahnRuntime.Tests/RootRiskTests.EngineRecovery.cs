using System.Reflection;
using KahnRuntime;
using KahnRuntime.Scaling;
using LL = KahnRuntime.LiveEvidence;

internal static partial class RootRiskTests
{
    private static void RunEngineRecoveryTests()
    {
        Action[] tests = [RetainedRailsFailAfterRecovery, MissingTimeDoesNotConfirmFailure,
            RecoveredMoveFailureIsImmediate, FailedIdentityStaysFailedAfterRecovery,
            TestedRootIsNotFailedByRecovery, EngineIdentitySurvivesRepeatedGaps,
            BufferedRootFailureSurvivesCatchup, ShortInterruptionRetainsBaselineAndRestartsTimers,
            CatchupHydrationCannotAuthorizeEntry, OrderedPriceSamplesKeepObserverCurrent];
        foreach (var test in tests)
        {
            try { test(); }
            catch (Exception error) { throw new Exception("FAIL " + test.Method.Name + ": " + error.Message, error); }
        }
        Console.WriteLine($"PASS live LL engine recovery ({tests.Length} checks, both sides and origins)");
    }

    private sealed class EngineFixture
    {
        public readonly LL.ExecutionEvidenceEngine Engine = new(1, new() { EventZThreshold = 1e9 });
        public readonly CampaignSession Session;
        private readonly CampaignSide _side;
        private long _sequence;
        public double Onside => _side == CampaignSide.Long ? 416 : 392;
        public double Adverse => _side == CampaignSide.Long ? 396 : 408;
        public double FailedMove => _side == CampaignSide.Long ? 376 : 428;

        public EngineFixture(CampaignSide side, RootClaimOrigin origin)
        {
            _side = side;
            Session = RootRiskTests.Session(side);
            // Seed an already-owned rail, not synthetic proof of how live ownership forms.
            // Reflection stays in tests so the production engine has no rail-injection API.
            Type bandType = typeof(LL.ExecutionEvidenceEngine).GetNestedType("Band", BindingFlags.NonPublic);
            object band = Activator.CreateInstance(bandType, nonPublic: true);
            void Set(string name, object value) => bandType.GetField(name).SetValue(band, value);
            Set("Id", 77); Set("Role", LL.EvidenceRole.Rail); Set("State", LL.EvidenceState.Owned);
            Set("Side", side == CampaignSide.Long ? LL.EvidenceSide.Demand : LL.EvidenceSide.Supply);
            Set("Source", origin == RootClaimOrigin.Lean ? LL.EvidenceSource.Lean : LL.EvidenceSource.Consumed);
            Set("MinTick", 400L); Set("MaxTick", 404L); Set("FormedUtc", At(-10).UtcDateTime);
            Set("OwnedUtc", At(1).UtcDateTime); Set("LastStateUtc", At(1).UtcDateTime);
            object bands = typeof(LL.ExecutionEvidenceEngine).GetField("_bands", BindingFlags.NonPublic | BindingFlags.Instance).GetValue(Engine);
            bands.GetType().GetMethod("AddLast", [bandType]).Invoke(bands, [band]);
            Step(1, Onside);
            var e = Evidence("77", EvidenceKind.RailOwned, side, price: Onside);
            var order = Session.Reserve(Decision(Session, e), e, null, At(1));
            Session.Report(order, 2, Onside, true, At(2), Onside);
        }

        public void Gap(double at)
        {
            Session.SuspendObservation(At(at), "fixture_feed_or_processing_gap");
            Engine.ResetObservation();
        }

        public IReadOnlyList<LL.EvidenceTransition> Step(double at, double mid, bool warming = false)
        {
            var transitions = Engine.Process(new() { TimeUtc = At(at).UtcDateTime,
                Bids = [new() { Price = mid, Size = 100 }], Asks = [new() { Price = mid + 1, Size = 100 }] });
            var bands = new[] { LL.EvidenceSide.Demand, LL.EvidenceSide.Supply }
                .SelectMany(side => Engine.LiveRails(side).Concat(Engine.FailedRails(side)));
            var claims = bands.Select(b => new RootClaim(Key(b.Id.ToString()),
                b.Side == LL.EvidenceSide.Demand ? CampaignSide.Long : CampaignSide.Short, new(b.MinTick, b.MaxTick),
                b.Source == LL.EvidenceSource.Lean ? RootClaimOrigin.Lean : RootClaimOrigin.Consumed,
                b.FormedUtc, b.OwnedUtc, b.LastStateUtc,
                b.State == LL.EvidenceState.Failed ? EvidenceKind.RailFailed
                    : b.State == LL.EvidenceState.Tested ? EvidenceKind.RailTested : EvidenceKind.RailOwned,
                b.FailedUtc.HasValue ? new DateTimeOffset(b.FailedUtc.Value) : null)).ToArray();
            var sample = new RepairSample(EvidenceSource.LevelLedger, "epoch", ++_sequence, At(at), mid, [], true);
            if (warming) Session.ObserveRootSample(sample, claims);
            else Session.Observe(sample, claims, recoverScale: true);
            return transitions;
        }
    }

    private static void EachEngine(Action<EngineFixture> test)
    {
        foreach (var side in new[] { CampaignSide.Long, CampaignSide.Short })
        foreach (var origin in new[] { RootClaimOrigin.Lean, RootClaimOrigin.Consumed })
            test(new EngineFixture(side, origin));
    }

    private static void BufferedRootFailureSurvivesCatchup() => EachEngine(f =>
    {
        f.Step(3, f.Onside);
        var binding = f.Session.State.RootBinding;
        var buffer = new BookObservationBuffer(64);
        var gate = new BookRecoveryGate(TimeSpan.FromSeconds(5));
        for (int at = 4; at <= 30; at++) buffer.Add(new(At(at).UtcDateTime,
            new() { TimeUtc = At(at).UtcDateTime }, f.Adverse, f.Adverse + 1, null));
        f.Session.SuspendObservation(At(3), "worker_backlog");
        foreach (var frame in buffer.Drain().Frames)
        {
            var step = gate.Inspect(frame);
            Check(step.Accept && step.ResetReason == null, "intact queued history reset discovery");
            int second = (int)(frame.At - Start.UtcDateTime).TotalSeconds;
            f.Step(second, f.Adverse, warming: true);
            if (second < 24) Check(f.Session.PendingRiskExit == null, "drain speed accelerated failure timer");
        }
        Check(f.Session.PendingRiskExit?.Decision.ReasonCode == "root_owner_failed"
            && f.Session.State.RootBinding == binding && f.Session.Observer.Suspended,
            "buffered exact-owner failure was lost or historical batch resumed discovery");
    });

    private static void ShortInterruptionRetainsBaselineAndRestartsTimers() => EachEngine(f =>
    {
        for (int t = 3; t <= 10; t++) f.Step(t, f.Adverse);
        object samples = typeof(LL.ExecutionEvidenceEngine).GetField("_samples", BindingFlags.Instance | BindingFlags.NonPublic).GetValue(f.Engine);
        int count = (int)samples.GetType().GetProperty("Count").GetValue(samples);
        var binding = f.Session.State.RootBinding;
        f.Engine.InterruptObservation();
        f.Session.SuspendObservation(At(11), "brief_mismatch");
        Check((int)samples.GetType().GetProperty("Count").GetValue(samples) == count,
            "brief mismatch erased rolling baseline");
        for (int t = 12; t <= 31; t++) f.Step(t, f.Adverse, warming: true);
        Check(f.Session.PendingRiskExit == null, "missing interval was included in failure timer");
        f.Step(32, f.Adverse, warming: true);
        Check(f.Session.PendingRiskExit?.Decision.ReasonCode == "root_owner_failed"
            && f.Session.State.RootBinding == binding, "fresh confirmation lost retained owner");
    });

    private static void OrderedPriceSamplesKeepObserverCurrent() => EachEngine(f =>
    {
        f.Step(3, f.Onside);
        long generation = f.Session.Observer.Generation;
        for (int second = 3; second <= 10; second++)
        {
            for (int quarter = 1; quarter <= 3; quarter++)
                f.Session.Observer.ObservePrice(At(second + quarter * 0.25), f.Onside);
            f.Step(second + 1, f.Onside);
        }
        Check(!f.Session.Observer.Suspended && f.Session.Observer.Generation == generation,
            "ordered worker-frequency prices caused book recovery or changed generation");
    });

    private static void CatchupHydrationCannotAuthorizeEntry()
    {
        var s = Session();
        s.Observe(Sample(1, 1), [Claim()]);
        s.SuspendObservation(At(1), "worker_backlog");
        s.ObserveRootSample(Sample(2, 10, Transition()), [Claim()]);
        var candidates = s.PolicyCandidates([Evidence(at: 10)], At(10));
        Check(!candidates.Any(x => x.Decision.Action is PolicyAction.AllowProbe or PolicyAction.AllowAdd)
            && s.Observer.Opportunity == null, "historical root hydration authorized new risk");
    }

    private static void RetainedRailsFailAfterRecovery() => EachEngine(f =>
    {
        var binding = f.Session.State.RootBinding;
        f.Gap(3); f.Step(40, f.Adverse, warming: true);
        Check(f.Session.PendingRiskExit == null, "first recovered excursion was treated as time failure");
        for (int at = 41; at <= 60; at++) f.Step(at, f.Adverse, warming: true);
        Check(f.Session.State.RootBinding == binding && f.Engine.FindBand(77).State == LL.EvidenceState.Failed
            && f.Session.PendingRiskExit?.Decision.ReasonCode == "root_owner_failed",
            "retained exact owner did not fail during warmup");
    });

    private static void MissingTimeDoesNotConfirmFailure() => EachEngine(f =>
    {
        f.Step(3, f.Adverse); f.Gap(4);
        f.Step(100, f.Adverse, warming: true);
        Check(f.Engine.FindBand(77).State != LL.EvidenceState.Failed, "unobserved time completed LL timer");
        for (int at = 101; at <= 119; at++) f.Step(at, f.Adverse, warming: true);
        Check(f.Session.PendingRiskExit == null, "failure timer resumed before full fresh confirmation");
        f.Step(120, f.Adverse, warming: true);
        Check(f.Session.PendingRiskExit?.Decision.ReasonCode == "root_owner_failed", "fresh timed failure missing");
    });

    private static void RecoveredMoveFailureIsImmediate() => EachEngine(f =>
    {
        f.Gap(3);
        var transitions = f.Step(100, f.FailedMove, warming: true);
        Check(transitions.Any(t => t.Kind == LL.EvidenceTransitionKind.RailFailed && t.Band.Id == 77 && t.Reason == "move")
            && f.Session.PendingRiskExit.HasValue, "fresh move failure waited for discovery warmup");
    });

    private static void FailedIdentityStaysFailedAfterRecovery() => EachEngine(f =>
    {
        f.Step(3, f.FailedMove); f.Gap(4); f.Step(40, f.Onside, warming: true);
        Check(f.Engine.FindBand(77).State == LL.EvidenceState.Failed
            && f.Session.PendingRiskExit.HasValue, "gap resurrected failed ownership");
    });

    private static void TestedRootIsNotFailedByRecovery() => EachEngine(f =>
    {
        f.Step(3, 402); f.Gap(4); f.Step(40, 402, warming: true);
        Check(f.Session.Roots.Health(f.Session.State.RootBinding, At(40)) == RootHealth.Tested
            && f.Session.PendingRiskExit == null, "TEST became FAIL across recovery");
    });

    private static void EngineIdentitySurvivesRepeatedGaps() => EachEngine(f =>
    {
        var binding = f.Session.State.RootBinding;
        f.Gap(3); f.Step(40, f.Onside, warming: true); f.Gap(41); f.Step(80, f.Onside, warming: true);
        Check(f.Engine.FindBand(77).OwnedUtc == binding.Owner.OwnedAt.Value.UtcDateTime
            && f.Session.Roots.Health(binding, At(80)) == RootHealth.Live, "recovery replaced owner identity/history");
        f.Step(81, f.FailedMove, warming: true);
        Check(f.Session.PendingRiskExit.HasValue, "second gap detached root failure tracking");
    });
}
