using System;
using System.Linq;
using KahnRuntime;
using KahnRuntime.Scaling;

internal static class ContinuationEntryTests
{
    private static DateTimeOffset At(double s) => new DateTimeOffset(2026, 9, 16, 14, 0, 0, TimeSpan.Zero).AddSeconds(s);
    private static void Check(bool condition, string message) { if (!condition) throw new Exception(message); }
    private static void Throws(Action action) { try { action(); } catch (InvalidOperationException) { return; } throw new Exception("expected rejection"); }
    private sealed class F
    {
        public readonly CampaignSession Session;
        public CampaignState State => Session.State;
        public readonly bool Short;
        private long _seq;
        public F(bool strict = false, bool shortSide = false, int? distance = null, int retries = 3)
        {
            Short = shortSide;
            var plan = new CampaignPlan { SchemaVersion = 2, Id = "entry", Digest = "digest", Status = "active",
                Side = Short ? CampaignSide.Short : CampaignSide.Long, Policies = new(),
                Execution = new() { StrictProbeRange = strict, MaxRetry = retries },
                Risk = new() { MaxRootEntryDistanceTicks = distance },
                Window = new() { NotBefore = At(-10), ExpiresAt = At(120) }, Arena = R(390, 600),
                Waypoints = [new() { Id = "probe", Role = WaypointRole.TrapProbe, Range = R(398, 410), RequirePriceInside = true }],
                Sizing = new() { ProbeQuantity = 2, AddQuantity = 2, MaxPositionQuantity = 10, ScaleMode = CampaignScaleMode.EvidenceScaled },
                Objective = new() { TargetRange = R(590, 600), TargetProximityTicks = 2 } };
            Session = new(plan, CampaignState.ForPlan(plan), "instance", 1, TimeSpan.FromSeconds(60));
            Step(-1, 408);
        }
        public double P(double p) => Short ? 1000 - p : p;
        public PriceRange R(double a, double b) => new() { Lower = Short ? P(b) : a, Upper = Short ? P(a) : b };
        public RepairTransition T(string id, long lo, long hi, EvidenceKind kind = EvidenceKind.RailOwned, bool opposite = false)
        {
            var range = R(lo, hi);
            return new(new(EvidenceSource.LevelLedger, "epoch", id), kind,
                opposite ? (Short ? CampaignSide.Long : CampaignSide.Short) : Session.Plan.Side,
                new((long)range.Lower, (long)range.Upper));
        }
        public void Step(double s, double p, params RepairTransition[] t)
            => Session.Observe(new(EvidenceSource.LevelLedger, "epoch", _seq++, At(s), P(p), t, true));
        public void Live(double s = 0)
        {
            Check(Session.GoLive(new() { SchemaVersion = 2, Id = "go", CampaignId = "entry", CampaignDigest = "digest",
                RuntimeInstanceId = "instance", Attempt = State.ExecutionAttemptCount, CreatedAt = At(s) }, At(s)) == "accepted", "go live");
        }
        public void Complete(double offset = 0, string suffix = "", bool pair = false)
        {
            Step(offset+5, 460, T("proof"+suffix, 420, 424));
            if (pair) Step(offset+6, 460, T("second"+suffix, 426, 430));
            Step(offset+10, 420, T("proof"+suffix, 420, 424, EvidenceKind.RailTested));
            if (pair) Step(offset+10.5, 426, T("second"+suffix, 426, 430, EvidenceKind.RailTested));
            Step(offset+11, 432, T("opposite"+suffix, 440, 444, opposite: true));
            Step(offset+20, 436, T("proof"+suffix, 420, 424, EvidenceKind.RailHeld));
            if (pair) Step(offset+21, 436, T("second"+suffix, 426, 430, EvidenceKind.RailHeld));
            Step(offset+30, 472, T("opposite"+suffix, 440, 444, EvidenceKind.RailFailed, true));
        }
        public ContinuationEntryContext C(double s = 30, double p = 472) => new(At(s), At(s), TimeSpan.FromSeconds(2), TimeSpan.FromSeconds(60),
            Short ? P(p)-1 : p, Short ? P(p) : p+1, true, true, true, 10);
        public CampaignOrder Reserve(bool pair = false)
        {
            Live(); Complete(pair: pair);
            Check(Session.TryContinuationEntry(C(), out var d, out var e, out string why), why);
            var o = Session.Reserve(d, e, null, At(30), C());
            Session.Submitted(o, "order", true, false);
            return o;
        }
        public void Fill(CampaignOrder o, double s = 30.1, int qty = 2, bool terminal = true)
            => Session.Report(o, qty, Short ? P(472)-1 : 473, terminal, At(s), P(472));
    }

    public static void RunAll()
    {
        Action[] tests = [StrictDefaultAndOptIn, WatchCannotEnter, CompletedWatchCannotReplay, OldResolvedCannotReplay,
            PendingWatchRepairCanComplete, FirstFillLong, FirstFillShort, PartialFillOnce, ExactGroupFailure,
            PendingFailureLateFill, UnknownPendingCancels, TrackingLossExits, ZeroFillNeedsNewEpisode,
            UncertainSubmissionBlocks, NewRepairSupersedes, StaleQuote, Expiry, TargetAndArena, PolicyAndCapacity,
            DistanceLimit, RevalidateBeforeSubmit, DuplicateReservation, NormalAddsAndPromotion, RetryLimit,
            RecoveryInvalidatesUnfilled, RetirementLateFill];
        foreach (var test in tests)
            try { test(); } catch (Exception e) { throw new Exception("FAIL continuation " + test.Method.Name + ": " + e.Message, e); }
        Console.WriteLine($"PASS continuation first entry ({tests.Length} checks)");
    }
    private static void StrictDefaultAndOptIn()
    {
        Check(new CampaignExecution().StrictProbeRange, "default relaxed");
        var f = new F(strict:true); f.Live(); f.Complete();
        Check(!f.Session.TryContinuationEntry(f.C(),out _,out _,out var r) && r == "strict_probe_range", "strict entered");
    }
    private static void WatchCannotEnter() { var f = new F(); f.Complete(); Check(f.Session.Observer.Opportunity == null && !f.Session.TryContinuationEntry(f.C(),out _,out _,out _),"WATCH entered"); }
    private static void CompletedWatchCannotReplay() { var f = new F(); f.Complete(); f.Live(31); f.Step(32,473); Check(!f.Session.TryContinuationEntry(f.C(32),out _,out _,out _),"old completion replayed"); }
    private static void OldResolvedCannotReplay()
    {
        var f = new F(); f.Step(5,460,f.T("opposite",440,444,opposite:true));
        f.Step(10,472,f.T("opposite",440,444,EvidenceKind.RailFailed,true)); f.Live(11);
        f.Step(12,473,f.T("fresh",440,444)); Check(!f.Session.TryContinuationEntry(f.C(12),out _,out _,out _),"pre-live resolution inherited");
    }
    private static void PendingWatchRepairCanComplete()
    {
        var f = new F(); f.Step(5,460,f.T("proof",420,424)); f.Step(10,420,f.T("proof",420,424,EvidenceKind.RailTested));
        f.Step(11,432,f.T("opp",440,444,opposite:true)); f.Live(12);
        f.Step(20,436,f.T("proof",420,424,EvidenceKind.RailHeld)); f.Step(30,472,f.T("opp",440,444,EvidenceKind.RailFailed,true));
        Check(f.Session.TryContinuationEntry(f.C(),out _,out _,out var why),why);
    }
    private static void FirstFill(bool shortSide)
    {
        var f = new F(shortSide:shortSide); var o=f.Reserve();
        Check(!f.State.HasPosition && f.Session.Sponsors == null && f.State.ExecutionAttemptCount==0,"submission was fill");
        f.Fill(o); Check(f.State.SimulatedPositionQuantity==2 && f.State.ExecutionAttemptCount==1 && f.State.AcceptedAddCount==0,"first quantity/count");
        Check(f.Session.Sponsors.Active != null && f.Session.Sponsors.Pending==null && f.Session.Sponsors.FilledAddCount==0 && f.State.GroupSponsorActive,"sponsor not active");
        Check(!f.State.BreakevenBackstopEligible(f.Session.Plan) && f.Session.Observer.Opportunity==null,"first fill treated as add");
        f.Step(31,410,f.T("proof",420,424,EvidenceKind.RailFailed));
        Check(f.Session.PolicyCandidates([],At(31)).Any(x=>x.Decision.ReasonCode=="active_group_failed"),"sponsor failure ignored");
    }
    private static void FirstFillLong()=>FirstFill(false);
    private static void FirstFillShort()=>FirstFill(true);
    private static void PartialFillOnce()
    {
        var f=new F();var o=f.Reserve();f.Fill(o,qty:1,terminal:false);var sponsor=f.Session.Sponsors.Active;f.Fill(o,30.2);
        Check(f.State.ExecutionAttemptCount==1 && f.State.SimulatedPositionQuantity==2 && ReferenceEquals(sponsor,f.Session.Sponsors.Active),"partial rebound");
        f.Fill(o,30.3);Check(f.State.ExecutionAttemptCount==1,"duplicate counted");
    }
    private static void ExactGroupFailure()
    {
        var f=new F();var o=f.Reserve(pair:true);f.Fill(o);Check(f.Session.Sponsors.Active.Members.Count==2,"fixture pair");
        f.Step(31,460,f.T("proof",420,424,EvidenceKind.RailFailed));Check(!f.Session.PolicyCandidates([],At(31)).Any(x=>x.Decision.Action==PolicyAction.Flatten),"one survivor ignored");
        f.Step(32,460,f.T("neighbor",432,434),f.T("second",426,430,EvidenceKind.RailFailed));
        Check(f.Session.PolicyCandidates([],At(32)).Any(x=>x.Decision.Action==PolicyAction.Flatten),"neighbor rescued frozen group");
    }
    private static void PendingFailureLateFill()
    {
        var f=new F();var o=f.Reserve();f.Step(31,410,f.T("proof",420,424,EvidenceKind.RailFailed));
        Check(o.CancelReason=="entry_sponsor_failed","no cancellation");f.Fill(o,31.1,1,false);
        Check(f.Session.PendingRiskExit?.Decision.Action==PolicyAction.Flatten && f.State.SimulatedPositionQuantity==1,"late fill escaped failure");
    }
    private static void UnknownPendingCancels()
    {
        var f=new F();var o=f.Reserve();f.Session.SuspendObservation(At(31),"gap");
        Check(o.CancelReason=="entry_sponsor_health_unknown" && o.FailureBeforeFill==null,"gap fabricated failure");
        f.Fill(o,31.1);Check(f.Session.RootRiskRecoveryReason=="sponsor_health_unknown" && f.State.HasPosition,"gap lost fill");
    }
    private static void TrackingLossExits()
    {
        var f=new F();var o=f.Reserve();f.Fill(o);
        f.Session.Observe(new(EvidenceSource.LevelLedger,"replacement",0,At(31),472,[],true));
        Check(f.Session.PendingRiskExit?.Decision.ReasonCode=="sponsor_tracking_lost" && !f.State.ExecutionAuthorized,"lost identity stayed active");
    }
    private static void ZeroFillNeedsNewEpisode()
    {
        var f=new F();var o=f.Reserve();f.Session.Report(o,0,null,true,At(30.1),472);
        Check(f.State.ExecutionAttemptCount==0 && f.Session.Observer.Opportunity==null,"zero fill spent or banked");
        f.Step(31,473);Check(!f.Session.TryContinuationEntry(f.C(31),out _,out _,out _),"automatic retry");
        f.Complete(35,"new");Check(f.Session.TryContinuationEntry(f.C(65),out _,out _,out var why),why);
    }
    private static void UncertainSubmissionBlocks()
    {
        var f=new F();f.Live();f.Complete();f.Session.TryContinuationEntry(f.C(),out var d,out var e,out _);
        var o=f.Session.Reserve(d,e,null,At(30),f.C());f.Session.Submitted(o,null,false,true);
        Check(f.Session.HasUnresolvedOrder && !f.State.ExecutionAuthorized,"uncertainty released risk");
    }
    private static void NewRepairSupersedes()
    {
        var f=new F();f.Live();f.Complete();f.Step(31,430,f.T("new",450,454,opposite:true));
        Check(!f.Session.TryContinuationEntry(f.C(31),out _,out _,out _),"old repair survived new opposition");
    }
    private static void StaleQuote() { var f=new F();f.Live();f.Complete();Check(!f.Session.TryContinuationEntry(f.C() with { QuoteAt=At(20) },out _,out _,out var r)&&r=="entry_stale_market",r); }
    private static void Expiry() { var f=new F();f.Live();f.Complete();Check(!f.Session.TryContinuationEntry(f.C(121),out _,out _,out var r)&&r=="entry_not_authorized_or_expired",r); }
    private static void TargetAndArena()
    {
        foreach(bool shortSide in new[]{false,true}) foreach(double price in new[]{399,408,589,601})
        {var f=new F(shortSide:shortSide);f.Live();f.Complete();Check(!f.Session.TryContinuationEntry(f.C(p:price),out _,out _,out _),"bad area admitted");}
    }
    private static void PolicyAndCapacity()
    {
        foreach(int gate in Enumerable.Range(0,4)) {var f=new F();f.Live();f.Complete();var c=f.C();
        c=gate switch {0=>c with {PolicyAllowsEntry=false},1=>c with {InstanceMaxQuantity=1},2=>c with {FlatAndReconciled=false},_=>c with {OrdersClear=false}};
        Check(!f.Session.TryContinuationEntry(c,out _,out _,out _),"gate bypass");}
    }
    private static void DistanceLimit(){var f=new F(distance:10);f.Live();f.Complete();Check(!f.Session.TryContinuationEntry(f.C(),out _,out _,out var r)&&r=="root_entry_distance_exceeded",r);}
    private static void RevalidateBeforeSubmit()
    {
        var f=new F();f.Live();f.Complete();f.Session.TryContinuationEntry(f.C(),out var d,out var e,out _);
        f.Step(31,410,f.T("proof",420,424,EvidenceKind.RailFailed));Throws(()=>f.Session.Reserve(d,e,null,At(31),f.C(31)));
    }
    private static void DuplicateReservation()
    {
        var f=new F();var o=f.Reserve();Throws(()=>f.Session.Reserve(o.Decision,o.Evidence,null,At(30),f.C()));
    }
    private static void NormalAddsAndPromotion()
    {
        var f=new F();var o=f.Reserve();f.Fill(o);var initial=f.Session.Sponsors.Active;
        void Add(double start,string suffix,long lower)
        {
            f.Step(start,lower+30,f.T("p"+suffix,lower,lower+4));
            f.Step(start+1,lower,f.T("p"+suffix,lower,lower+4,EvidenceKind.RailTested));
            f.Step(start+2,lower+8,f.T("o"+suffix,lower+10,lower+14,opposite:true));
            f.Step(start+3,lower+8,f.T("p"+suffix,lower,lower+4,EvidenceKind.RailHeld));
            f.Step(start+4,lower+30,f.T("o"+suffix,lower+10,lower+14,EvidenceKind.RailFailed,true));
            var op=f.Session.Observer.Opportunity;Check(op!=null,"later opportunity missing");
            var c=new ScaleAdmissionContext(At(start+4),At(start+4),TimeSpan.FromSeconds(2),TimeSpan.FromSeconds(60),lower+30,lower+31,
                f.State.SimulatedAveragePrice.Value,f.State.SimulatedPositionQuantity,2,10,10,true,true,true,true,false);
            Check(f.Session.Reservations.TryReserve(op,c,out var reserved,out var why),why);
            var ev=new CampaignEvidence {EventId=reserved.Id,Timestamp=At(start+4)};
            var order=f.Session.Reserve(new(){Action=PolicyAction.AllowAdd,Quantity=2,Policy="repair_episode"},ev,reserved,At(start+4));
            f.Session.Report(order,2,lower+31,true,At(start+4.1),lower+30);
        }
        Add(40,"a",480);Check(ReferenceEquals(initial,f.Session.Sponsors.Active)&&f.Session.Sponsors.Pending!=null,"first real add promoted too early");
        var pending=f.Session.Sponsors.Pending;Add(50,"b",520);
        Check(f.Session.Sponsors.Active.EpisodeId==pending.EpisodeId && f.State.AcceptedAddCount==2 && f.State.BreakevenBackstopEligible(f.Session.Plan),"normal promotion/BE lost");
    }
    private static void RetryLimit()
    {
        var f=new F(retries:1);var o=f.Reserve();f.Fill(o);f.State.ApplyDecision(new(){Action=PolicyAction.Flatten},f.Session.Plan,true,At(31));f.Session.ConfirmFlat(At(31));
        f.Complete(35,"new");Check(!f.Session.TryContinuationEntry(f.C(65),out _,out _,out _)&&f.State.ExecutionPaused,"retry budget bypassed");
    }
    private static void RecoveryInvalidatesUnfilled()
    {
        var f=new F();f.Live();f.Complete();f.Session.SuspendObservation(At(31),"gap");
        f.Session.Observe(new(EvidenceSource.LevelLedger,"epoch",100,At(32),472,[],true),recoverScale:true);
        Check(!f.Session.TryContinuationEntry(f.C(32),out _,out _,out _),"recovery resurrected opportunity");
    }
    private static void RetirementLateFill()
    {
        var f=new F();var o=f.Reserve();f.State.ApplyDecision(new(){Action=PolicyAction.Retire},f.Session.Plan,true,At(30.05));
        f.Fill(o);Check(f.State.IsRetired&&!f.State.ExecutionAuthorized&&f.State.HasPosition&&f.Session.RecoveryReason!=null,"late fill revived retired campaign");
    }
}
