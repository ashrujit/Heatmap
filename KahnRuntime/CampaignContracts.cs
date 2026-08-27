using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;

namespace KahnRuntime
{
    internal enum CampaignSide
    {
        Long,
        Short,
    }

    internal enum CampaignPhase
    {
        Idle,
        Ready,
        ProbeArmed,
        ProbeOpen,
        Pressing,
        BuildTrial,
        TargetZone,
        Paused,
        Retired,
    }

    internal enum WaypointRole
    {
        TrapProbe,
        Press,
        BuildTrial,
        Target,
        NoAdd,
        Evaluate,
        Risk,
        RepairHold,
        PathStress,
        Invalidation,
    }

    internal enum EvidenceSource
    {
        Unknown,
        Price,
        LevelLedger,
        BubbleTape,
        Footprint,
        Broker,
        Replay,
    }

    internal enum EvidenceKind
    {
        Unknown,
        PriceTouch,
        PriceCross,
        PriceAccept,
        PriceReclaim,
        RailOwned,
        RailHeld,
        RailFailed,
        RailTested,
        BubbleFinalized,
        Absorption,
        SponsorFailed,
        PositionChanged,
        Timer,
    }

    internal enum EvidenceSide
    {
        None,
        Demand,
        Supply,
        Buy,
        Sell,
        Long,
        Short,
    }

    internal enum PolicyAction
    {
        NoAction,
        ArmProbe,
        AllowProbe,
        AllowAdd,
        SuppressAdd,
        HoldRoot,
        TightenRisk,
        Reduce,
        Flatten,
        Retire,
        Cooldown,
    }

    internal sealed class PriceRange
    {
        public double Lower { get; init; }
        public double Upper { get; init; }

        public double Center => (Lower + Upper) / 2.0;

        public bool IsValid
            => double.IsFinite(Lower) && double.IsFinite(Upper) && Lower <= Upper;

        public bool Contains(double price)
            => double.IsFinite(price) && price >= Lower && price <= Upper;

        public bool Intersects(PriceRange other)
            => other != null && other.IsValid && IsValid
                && other.Upper >= Lower && other.Lower <= Upper;

        public PriceRange Expanded(int ticks, double tickSize)
        {
            double padding = Math.Max(0, ticks) * Math.Max(tickSize, 0.0000001);
            return new PriceRange { Lower = Lower - padding, Upper = Upper + padding };
        }

        public int DistanceTicksTo(double price, double tickSize)
        {
            if (!double.IsFinite(price) || !IsValid)
                return int.MaxValue;
            if (Contains(price))
                return 0;
            double distance = price < Lower ? Lower - price : price - Upper;
            return Ticks(distance, tickSize);
        }

        public int DistanceTicksTo(PriceRange other, double tickSize)
        {
            if (other == null || !other.IsValid || !IsValid)
                return int.MaxValue;
            if (Intersects(other))
                return 0;
            double distance = other.Upper < Lower ? Lower - other.Upper : other.Lower - Upper;
            return Ticks(distance, tickSize);
        }

        public override string ToString()
            => $"{Lower.ToString("0.########", CultureInfo.InvariantCulture)}"
                + "-"
                + $"{Upper.ToString("0.########", CultureInfo.InvariantCulture)}";

        private static int Ticks(double distance, double tickSize)
        {
            double size = Math.Max(tickSize, 0.0000001);
            return (int)Math.Ceiling(Math.Abs(distance) / size);
        }
    }

    internal sealed class CampaignWindow
    {
        public DateTimeOffset NotBefore { get; init; }
        public DateTimeOffset ExpiresAt { get; init; }

        public bool Contains(DateTimeOffset now)
            => now >= NotBefore && now <= ExpiresAt;
    }

    internal sealed class CampaignSizing
    {
        public int ProbeQuantity { get; init; } = 1;
        public int AddQuantity { get; init; } = 1;
        public int MaxPositionQuantity { get; init; } = 1;
    }

    internal sealed class CampaignExecution
    {
        public int MaxRetry { get; init; } = 3;
    }

    internal sealed class CampaignRisk
    {
        public int RootStopTicks { get; init; } = 16;
        public int SponsorFailureBufferTicks { get; init; } = 2;
        public bool AllowContestBeyondRiskAnchor { get; init; } = true;
    }

    internal sealed class CampaignObjective
    {
        public PriceRange TargetRange { get; init; }
        public int TargetProximityTicks { get; init; } = 8;
        public bool SuppressAddsInTargetZone { get; init; } = true;
    }

    internal sealed class CampaignPolicyFlags
    {
        public bool TrapProbeEnabled { get; init; } = true;
        public bool PressEnabled { get; init; } = true;
        public bool BuildTrialEnabled { get; init; } = true;
        public bool TargetZoneEnabled { get; init; } = true;
        public bool RepairHoldEnabled { get; init; } = true;
        public bool PathStressEnabled { get; init; } = true;
    }

    internal sealed class CampaignWaypoint
    {
        public string Id { get; init; }
        public WaypointRole Role { get; init; }
        public PriceRange Range { get; init; }
        public string Label { get; init; }
        public int? SuppressAddsWithinTicks { get; init; }
        public int? MaxPositionQuantity { get; init; }
        public bool PreserveRiskAnchorOnAdd { get; init; }
        public bool RequirePriceInside { get; init; }

        public bool IsNear(CampaignEvidence evidence, double tickSize, int proximityTicks)
            => evidence?.EffectiveRange(tickSize).DistanceTicksTo(Range, tickSize)
                <= Math.Max(0, proximityTicks);
    }

    internal sealed class CampaignPlan
    {
        public int SchemaVersion { get; init; }
        public string Kind { get; init; }
        public string Id { get; init; }
        public string Status { get; init; }
        public DateTimeOffset CreatedAt { get; init; }
        public CampaignSide Side { get; init; }
        public CampaignWindow Window { get; init; }
        public PriceRange Arena { get; init; }
        public CampaignSizing Sizing { get; init; }
        public CampaignExecution Execution { get; init; }
        public CampaignRisk Risk { get; init; }
        public CampaignObjective Objective { get; init; }
        public CampaignPolicyFlags Policies { get; init; }
        public IReadOnlyList<CampaignWaypoint> Waypoints { get; init; }
        public string Notes { get; init; }
        public string Digest { get; init; }

        public bool IsActiveAt(DateTimeOffset now)
            => IsActiveStatus
                && IsEntryWindowOpen(now);

        public bool ShouldEvaluateEvidenceAt(DateTimeOffset now, CampaignState state)
            => IsActiveStatus
                && (IsEntryWindowOpen(now) || state?.HasPosition == true);

        private bool IsActiveStatus
            => string.Equals(Status, "active", StringComparison.OrdinalIgnoreCase);

        private bool IsEntryWindowOpen(DateTimeOffset now)
            => Window != null && Window.Contains(now);

        public IEnumerable<CampaignWaypoint> WaypointsByRole(WaypointRole role)
            => Waypoints?.Where(waypoint => waypoint.Role == role)
                ?? Enumerable.Empty<CampaignWaypoint>();

        public CampaignWaypoint FindWaypoint(string id)
            => string.IsNullOrWhiteSpace(id)
                ? null
                : Waypoints?.FirstOrDefault(waypoint =>
                    string.Equals(waypoint.Id, id, StringComparison.Ordinal));
    }

    internal sealed class CampaignEvidence
    {
        public int SchemaVersion { get; init; } = 1;
        public string EventId { get; init; }
        public DateTimeOffset Timestamp { get; init; }
        public EvidenceSource Source { get; init; }
        public EvidenceKind Kind { get; init; }
        public EvidenceSide Side { get; init; }
        public double? Price { get; init; }
        public PriceRange Range { get; init; }
        public string WaypointId { get; init; }
        public string RailId { get; init; }
        public double? Volume { get; init; }
        public double? Delta { get; init; }
        public double? Score { get; init; }
        public string Note { get; init; }

        public PriceRange EffectiveRange(double tickSize)
        {
            if (Range != null && Range.IsValid)
                return Range;
            if (Price.HasValue && double.IsFinite(Price.Value))
            {
                double halfTick = Math.Max(tickSize, 0.0000001) / 2.0;
                return new PriceRange
                {
                    Lower = Price.Value - halfTick,
                    Upper = Price.Value + halfTick,
                };
            }
            return new PriceRange
            {
                Lower = double.PositiveInfinity,
                Upper = double.NegativeInfinity,
            };
        }

        public bool IsLargeEffort
            => Math.Abs(Delta ?? 0) >= 500 || (Volume ?? 0) >= 200;
    }

    internal sealed class CampaignContext
    {
        public CampaignContext(CampaignPlan plan,
            CampaignState state,
            double tickSize,
            DateTimeOffset now)
        {
            Plan = plan ?? throw new ArgumentNullException(nameof(plan));
            State = state ?? throw new ArgumentNullException(nameof(state));
            TickSize = tickSize > 0 ? tickSize : 0.25;
            Now = now;
        }

        public CampaignPlan Plan { get; }
        public CampaignState State { get; }
        public double TickSize { get; }
        public DateTimeOffset Now { get; }

        public bool IsNearTarget(CampaignEvidence evidence)
        {
            PriceRange target = Plan.Objective?.TargetRange;
            if (target == null || !target.IsValid)
                return false;
            return evidence.EffectiveRange(TickSize)
                .DistanceTicksTo(target, TickSize)
                <= Math.Max(0, Plan.Objective.TargetProximityTicks);
        }
    }

    internal sealed class PolicyDecision
    {
        public PolicyAction Action { get; init; }
        public string Policy { get; init; }
        public string ReasonCode { get; init; }
        public string Detail { get; init; }
        public int Priority { get; init; }
        public int? Quantity { get; init; }
        public string WaypointId { get; init; }
        public PriceRange RiskAnchor { get; init; }
        public string RiskAnchorEvidenceId { get; init; }
        public DateTimeOffset? ExpiresAt { get; init; }
        public string EvidenceId { get; init; }

        public string DedupeKey
            => $"{Action}:{Policy}:{ReasonCode}:{WaypointId}:{RiskAnchor}";

        public static PolicyDecision None(string policy, CampaignEvidence evidence)
            => new()
            {
                Action = PolicyAction.NoAction,
                Policy = policy,
                ReasonCode = "no_action",
                Priority = 0,
                EvidenceId = evidence?.EventId,
            };
    }

    internal sealed class CampaignState
    {
        private readonly Dictionary<string, DateTimeOffset> _decisionDedupe = new(StringComparer.Ordinal);

        public string PlanId { get; private set; }
        public CampaignPhase Phase { get; private set; } = CampaignPhase.Idle;
        public int SimulatedPositionQuantity { get; private set; }
        public string ArmedWaypointId { get; private set; }
        public PriceRange ActiveRiskAnchor { get; private set; }
        public string ActiveRiskAnchorEvidenceId { get; private set; }
        public PriceRange RootRiskAnchor { get; private set; }
        public string RootRiskAnchorEvidenceId { get; private set; }
        public DateTimeOffset? SuppressAddsUntil { get; private set; }
        public DateTimeOffset LastDecisionUtc { get; private set; }
        public int ExecutionAttemptCount { get; private set; }
        public string ExecutionPauseReason { get; private set; }
        public DateTimeOffset? ExecutionPausedAt { get; private set; }

        public bool HasPosition => SimulatedPositionQuantity > 0;
        public bool IsRetired => Phase == CampaignPhase.Retired;
        public bool ExecutionPaused => Phase == CampaignPhase.Paused;

        public bool CanAttemptEntry(CampaignPlan plan)
            => !ExecutionPaused && ExecutionAttemptCount < MaxRetry(plan);

        public int ExecutionRetriesRemaining(CampaignPlan plan)
            => Math.Max(0, MaxRetry(plan) - ExecutionAttemptCount);

        public static CampaignState ForPlan(CampaignPlan plan)
            => new()
            {
                PlanId = plan?.Id,
                Phase = CampaignPhase.Ready,
            };

        public bool AddsSuppressed(DateTimeOffset now)
            => SuppressAddsUntil.HasValue && now <= SuppressAddsUntil.Value;

        public bool ShouldEmit(PolicyDecision decision, DateTimeOffset now, TimeSpan minimumInterval)
        {
            if (decision == null || decision.Action == PolicyAction.NoAction)
                return false;
            string key = decision.DedupeKey;
            if (_decisionDedupe.TryGetValue(key, out DateTimeOffset prior)
                && now - prior < minimumInterval)
            {
                return false;
            }
            _decisionDedupe[key] = now;
            return true;
        }

        public void ApplyDecision(PolicyDecision decision,
            CampaignPlan plan,
            bool simulateAcceptedDecisions,
            DateTimeOffset? appliedAt = null)
        {
            if (decision == null || decision.Action == PolicyAction.NoAction)
                return;

            DateTimeOffset now = appliedAt ?? DateTimeOffset.UtcNow;
            LastDecisionUtc = now;
            switch (decision.Action)
            {
                case PolicyAction.ArmProbe:
                    Phase = CampaignPhase.ProbeArmed;
                    ArmedWaypointId = decision.WaypointId;
                    break;
                case PolicyAction.AllowProbe:
                    ExecutionAttemptCount = Math.Min(MaxRetry(plan), ExecutionAttemptCount + 1);
                    ClearExecutionPause();
                    if (simulateAcceptedDecisions)
                        SimulatedPositionQuantity = Math.Max(
                            SimulatedPositionQuantity,
                            Math.Max(1, decision.Quantity ?? plan.Sizing.ProbeQuantity));
                    Phase = CampaignPhase.ProbeOpen;
                    SetRiskAnchor(decision);
                    SetRootRiskAnchorIfUnset(decision);
                    ArmedWaypointId = null;
                    break;
                case PolicyAction.AllowAdd:
                    if (simulateAcceptedDecisions)
                    {
                        int quantity = Math.Max(1, decision.Quantity ?? plan.Sizing.AddQuantity);
                        SimulatedPositionQuantity = Math.Min(
                            plan.Sizing.MaxPositionQuantity,
                            SimulatedPositionQuantity + quantity);
                    }
                    Phase = CampaignPhase.Pressing;
                    SetRiskAnchor(decision);
                    break;
                case PolicyAction.SuppressAdd:
                    SuppressAddsUntil = decision.ExpiresAt
                        ?? now.AddSeconds(30);
                    if (Phase != CampaignPhase.Retired)
                    {
                        if (string.Equals(decision.Policy, "target_zone", StringComparison.Ordinal))
                            Phase = HasPosition ? CampaignPhase.TargetZone : CampaignPhase.Ready;
                        else if (!HasPosition)
                            Phase = CampaignPhase.Ready;
                    }
                    break;
                case PolicyAction.HoldRoot:
                case PolicyAction.TightenRisk:
                    if (decision.RiskAnchor != null)
                        SetRiskAnchor(decision);
                    if (HasPosition && Phase != CampaignPhase.TargetZone)
                        Phase = CampaignPhase.BuildTrial;
                    break;
                case PolicyAction.Reduce:
                    if (simulateAcceptedDecisions && SimulatedPositionQuantity > 0)
                    {
                        int quantity = Math.Max(1, decision.Quantity ?? 1);
                        SimulatedPositionQuantity = Math.Max(0, SimulatedPositionQuantity - quantity);
                    }
                    if (decision.ExpiresAt.HasValue)
                        SuppressAddsUntil = decision.ExpiresAt;
                    if (SimulatedPositionQuantity > 0)
                    {
                        Phase = string.Equals(decision.Policy, "target_zone", StringComparison.Ordinal)
                            ? CampaignPhase.TargetZone
                            : CampaignPhase.Pressing;
                    }
                    else
                    {
                        ClearRiskAnchors();
                        Phase = string.Equals(decision.Policy, "target_zone", StringComparison.Ordinal)
                            ? CampaignPhase.Retired
                            : CampaignPhase.Ready;
                    }
                    break;
                case PolicyAction.Flatten:
                    if (simulateAcceptedDecisions)
                        SimulatedPositionQuantity = 0;
                    ClearRiskAnchors();
                    ArmedWaypointId = null;

                    if (ExecutionAttemptCount >= MaxRetry(plan))
                        PauseExecution("max_retry_exhausted", now);
                    else
                        Phase = CampaignPhase.Ready;
                    break;
                case PolicyAction.Retire:
                    if (simulateAcceptedDecisions)
                        SimulatedPositionQuantity = 0;
                    ClearRiskAnchors();

                    Phase = CampaignPhase.Retired;
                    break;
                case PolicyAction.Cooldown:
                    SuppressAddsUntil = decision.ExpiresAt
                        ?? now.AddSeconds(60);
                    break;
            }
        }

        private void SetRiskAnchor(PolicyDecision decision)
        {
            if (decision.RiskAnchor == null)
                return;
            ActiveRiskAnchor = decision.RiskAnchor;
            ActiveRiskAnchorEvidenceId = decision.RiskAnchorEvidenceId ?? decision.EvidenceId;
        }

        public void ReconcileObservedPositionQuantity(int quantity, CampaignPlan plan)
        {
            int max = plan?.Sizing?.MaxPositionQuantity ?? quantity;
            SimulatedPositionQuantity = Math.Max(0, Math.Min(quantity, max));
            if (SimulatedPositionQuantity <= 0)
            {
                ClearRiskAnchors();
                if (Phase != CampaignPhase.Retired && Phase != CampaignPhase.Paused)
                    Phase = CampaignPhase.Ready;
                return;
            }

            if (Phase == CampaignPhase.Idle || Phase == CampaignPhase.Ready)
                Phase = CampaignPhase.ProbeOpen;
        }

        private void SetRootRiskAnchorIfUnset(PolicyDecision decision)
        {
            if (RootRiskAnchor != null || decision.RiskAnchor == null)
                return;
            RootRiskAnchor = decision.RiskAnchor;
            RootRiskAnchorEvidenceId = decision.RiskAnchorEvidenceId ?? decision.EvidenceId;
        }

        private void PauseExecution(string reasonCode, DateTimeOffset now)
        {
            if (Phase == CampaignPhase.Retired)
                return;
            Phase = CampaignPhase.Paused;
            ExecutionPauseReason = string.IsNullOrWhiteSpace(reasonCode)
                ? "execution_paused"
                : reasonCode;
            ExecutionPausedAt = now;
            SuppressAddsUntil = null;
            ArmedWaypointId = null;
        }

        private void ClearExecutionPause()
        {
            ExecutionPauseReason = null;
            ExecutionPausedAt = null;
        }

        private static int MaxRetry(CampaignPlan plan)
            => Math.Max(1, plan?.Execution?.MaxRetry ?? 3);

        private void ClearRiskAnchors()
        {
            ActiveRiskAnchor = null;
            ActiveRiskAnchorEvidenceId = null;
            RootRiskAnchor = null;
            RootRiskAnchorEvidenceId = null;
        }
    }

    internal static class CampaignSideMath
    {
        public static bool IsSameSide(CampaignSide campaignSide, EvidenceSide evidenceSide)
            => campaignSide switch
            {
                CampaignSide.Long => evidenceSide is EvidenceSide.Demand
                    or EvidenceSide.Buy
                    or EvidenceSide.Long,
                CampaignSide.Short => evidenceSide is EvidenceSide.Supply
                    or EvidenceSide.Sell
                    or EvidenceSide.Short,
                _ => false,
            };

        public static bool IsOppositeSide(CampaignSide campaignSide, EvidenceSide evidenceSide)
            => campaignSide switch
            {
                CampaignSide.Long => evidenceSide is EvidenceSide.Supply
                    or EvidenceSide.Sell
                    or EvidenceSide.Short,
                CampaignSide.Short => evidenceSide is EvidenceSide.Demand
                    or EvidenceSide.Buy
                    or EvidenceSide.Long,
                _ => false,
            };

        public static bool IsFavorableBeyond(CampaignSide side,
            PriceRange candidate,
            PriceRange reference)
        {
            if (candidate == null || reference == null
                || !candidate.IsValid || !reference.IsValid)
            {
                return false;
            }
            return side == CampaignSide.Long
                ? candidate.Lower > reference.Upper
                : candidate.Upper < reference.Lower;
        }
    }
}
