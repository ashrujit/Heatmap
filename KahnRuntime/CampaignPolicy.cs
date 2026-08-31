using System;
using System.Collections.Generic;
using System.Linq;

namespace KahnRuntime
{
    internal interface ICampaignPolicy
    {
        string Name { get; }

        IEnumerable<PolicyDecision> Evaluate(CampaignContext context, CampaignEvidence evidence);
    }

    internal sealed class CampaignPolicyEngine
    {
        private readonly IReadOnlyList<ICampaignPolicy> _policies;

        public CampaignPolicyEngine(IEnumerable<ICampaignPolicy> policies)
        {
            _policies = policies?.ToArray() ?? throw new ArgumentNullException(nameof(policies));
        }

        public PolicyDecision Evaluate(CampaignContext context, CampaignEvidence evidence)
        {
            if (context == null)
                throw new ArgumentNullException(nameof(context));
            if (evidence == null)
                return PolicyDecision.None("engine", null);

            List<PolicyDecision> candidates = new();
            foreach (ICampaignPolicy policy in _policies)
            {
                candidates.AddRange(policy.Evaluate(context, evidence)
                    .Where(decision => decision != null));
            }
            return DecisionResolver.Resolve(candidates, evidence);
        }

        public static CampaignPolicyEngine CreateDefault()
            => new(new ICampaignPolicy[]
            {
                new NoAddZonePolicy(),
                new EvaluateZonePolicy(),
                new PathStressPolicy(),
                new PassiveHarvestPolicy(),
                new TargetZonePolicy(),
                new BuildTrialPolicy(),
                new RepairHoldPolicy(),
                new TrapProbePolicy(),
                new PressPolicy(),
            });
    }

    internal static class DecisionResolver
    {
        private static readonly Dictionary<PolicyAction, int> ActionPriority = new()
        {
            [PolicyAction.Flatten] = 1000,
            [PolicyAction.Retire] = 950,
            [PolicyAction.Reduce] = 850,
            [PolicyAction.SuppressAdd] = 700,
            [PolicyAction.TightenRisk] = 625,
            [PolicyAction.PassiveHarvest] = 845,
            [PolicyAction.HoldRoot] = 500,
            [PolicyAction.AllowProbe] = 420,
            [PolicyAction.AllowAdd] = 320,
            [PolicyAction.TrackScaleCandidate] = 315,
            [PolicyAction.EnsureBreakeven] = 300,
            [PolicyAction.ArmProbe] = 260,
            [PolicyAction.Cooldown] = 200,
            [PolicyAction.NoAction] = 0,
        };

        public static PolicyDecision Resolve(IEnumerable<PolicyDecision> candidates,
            CampaignEvidence evidence)
        {
            PolicyDecision decision = candidates
                .Where(candidate => candidate.Action != PolicyAction.NoAction)
                .Select(WithDefaultPriority)
                .OrderByDescending(candidate => candidate.Priority)
                .ThenByDescending(candidate => RiskDownTieRank(candidate.Action))
                .FirstOrDefault();

            return decision ?? PolicyDecision.None("resolver", evidence);
        }

        public static int PriorityFor(PolicyAction action)
            => ActionPriority.TryGetValue(action, out int priority) ? priority : 0;

        private static int RiskDownTieRank(PolicyAction action)
            => action switch
            {
                PolicyAction.Flatten => 100,
                PolicyAction.Retire => 90,
                PolicyAction.Reduce => 80,
                PolicyAction.PassiveHarvest => 70,
                PolicyAction.SuppressAdd => 60,
                PolicyAction.TightenRisk => 50,
                PolicyAction.HoldRoot => 40,
                PolicyAction.EnsureBreakeven => 30,
                PolicyAction.AllowProbe => 20,
                PolicyAction.AllowAdd => 10,
                PolicyAction.TrackScaleCandidate => 5,
                _ => 0,
            };

        private static PolicyDecision WithDefaultPriority(PolicyDecision decision)
            => decision.Priority > 0
                ? decision
                : new PolicyDecision
                {
                    Action = decision.Action,
                    Policy = decision.Policy,
                    ReasonCode = decision.ReasonCode,
                    Detail = decision.Detail,
                    Priority = PriorityFor(decision.Action),
                    Quantity = decision.Quantity,
                    WaypointId = decision.WaypointId,
                    RiskAnchor = decision.RiskAnchor,
                    RiskAnchorEvidenceId = decision.RiskAnchorEvidenceId,
                    ChildRiskAnchor = decision.ChildRiskAnchor,
                    ChildRiskAnchorEvidenceId = decision.ChildRiskAnchorEvidenceId,
                    DelayRiskAnchorPromotionOnAdd = decision.DelayRiskAnchorPromotionOnAdd,
                    ProtectionPrice = decision.ProtectionPrice,
                    ExpiresAt = decision.ExpiresAt,
                    EvidenceId = decision.EvidenceId,
                };
    }

    internal abstract class CampaignPolicyBase : ICampaignPolicy
    {
        public abstract string Name { get; }

        public abstract IEnumerable<PolicyDecision> Evaluate(CampaignContext context,
            CampaignEvidence evidence);

        protected static CampaignWaypoint NearestWaypoint(CampaignContext context,
            CampaignEvidence evidence,
            WaypointRole role,
            int proximityTicks)
        {
            CampaignWaypoint exact = context.Plan.FindWaypoint(evidence.WaypointId);
            if (exact != null)
                return exact.Role == role ? exact : null;

            PriceRange evidenceRange = evidence.EffectiveRange(context.TickSize);
            return context.Plan.WaypointsByRole(role)
                .Select(waypoint => new
                {
                    Waypoint = waypoint,
                    Distance = evidenceRange.DistanceTicksTo(waypoint.Range, context.TickSize),
                })
                .Where(candidate => candidate.Distance <= proximityTicks)
                .OrderBy(candidate => candidate.Distance)
                .Select(candidate => candidate.Waypoint)
                .FirstOrDefault();
        }

        protected static PriceRange EvidenceAnchor(CampaignEvidence evidence, double tickSize)
        {
            PriceRange range = evidence.EffectiveRange(tickSize);
            return range.IsValid ? range : null;
        }

        protected static int AddClipQuantity(CampaignContext context)
            => Math.Max(1, context?.Plan?.Sizing?.AddQuantity ?? 1);

        protected static bool PriceGateAllows(CampaignWaypoint waypoint,
            CampaignEvidence evidence)
            => waypoint == null
                || !waypoint.RequirePriceInside
                || (evidence?.Price.HasValue == true
                    && waypoint.Range.Contains(evidence.Price.Value));

        protected static PolicyDecision Decision(PolicyAction action,
            string policy,
            string reason,
            CampaignEvidence evidence,
            string waypointId = null,
            int? quantity = null,
            PriceRange riskAnchor = null,
            DateTimeOffset? expiresAt = null,
            string detail = null,
            int priority = 0,
            string riskAnchorEvidenceId = null,
            PriceRange childRiskAnchor = null,
            string childRiskAnchorEvidenceId = null,
            bool delayRiskAnchorPromotionOnAdd = false,
            double? protectionPrice = null)
            => new()
            {
                Action = action,
                Policy = policy,
                ReasonCode = reason,
                Detail = detail,
                Priority = priority,
                Quantity = quantity,
                WaypointId = waypointId,
                RiskAnchor = riskAnchor,
                RiskAnchorEvidenceId = riskAnchorEvidenceId ?? (riskAnchor != null ? evidence?.EventId : null),
                ChildRiskAnchor = childRiskAnchor,
                ChildRiskAnchorEvidenceId = childRiskAnchorEvidenceId ?? (childRiskAnchor != null ? evidence?.EventId : null),
                DelayRiskAnchorPromotionOnAdd = delayRiskAnchorPromotionOnAdd,
                ProtectionPrice = protectionPrice,
                ExpiresAt = expiresAt,
                EvidenceId = evidence?.EventId,
            };
    }

    internal sealed class TrapProbePolicy : CampaignPolicyBase
    {
        public override string Name => "trap_probe";

        public override IEnumerable<PolicyDecision> Evaluate(CampaignContext context,
            CampaignEvidence evidence)
        {
            if (!context.Plan.Policies.TrapProbeEnabled
                || context.State.IsRetired
                || !context.Plan.IsActiveAt(context.Now)
                || !context.State.CanAttemptEntry(context.Plan)
                || context.State.HasPosition)
            {
                yield break;
            }

            CampaignWaypoint waypoint = NearestWaypoint(context, evidence, WaypointRole.TrapProbe, 8);
            CampaignWaypoint armedWaypoint = context.Plan.FindWaypoint(context.State.ArmedWaypointId);
            CampaignWaypoint triggerWaypoint = waypoint ?? armedWaypoint;
            if (triggerWaypoint == null || !PriceGateAllows(triggerWaypoint, evidence))
                yield break;

            bool sameSide = CampaignSideMath.IsSameSide(context.Plan.Side, evidence.Side);
            bool oppositeSide = CampaignSideMath.IsOppositeSide(context.Plan.Side, evidence.Side);
            bool trapEffort = evidence.Kind is EvidenceKind.BubbleFinalized or EvidenceKind.Absorption
                && oppositeSide
                && evidence.IsLargeEffort;

            if (trapEffort)
            {
                yield return Decision(
                    PolicyAction.ArmProbe,
                    Name,
                    "counter_effort_at_trap_probe",
                    evidence,
                    triggerWaypoint.Id,
                    expiresAt: context.Now.AddSeconds(90),
                    detail: "Counter-side effort appeared at trap waypoint; wait for failure or same-side lean.");
            }

            if (evidence.Kind is EvidenceKind.RailOwned or EvidenceKind.RailHeld && sameSide)
            {
                yield return Decision(
                    PolicyAction.AllowProbe,
                    Name,
                    waypoint == null
                        ? "armed_probe_same_side_lean"
                        : "same_side_lean_at_trap_probe",
                    evidence,
                    triggerWaypoint.Id,
                    context.Plan.Sizing.ProbeQuantity,
                    EvidenceAnchor(evidence, context.TickSize));
            }

            if (evidence.Kind == EvidenceKind.RailFailed && oppositeSide)
            {
                yield return Decision(
                    PolicyAction.AllowProbe,
                    Name,
                    waypoint == null
                        ? "armed_probe_counter_claim_failed"
                        : "counter_claim_failed_at_trap_probe",
                    evidence,
                    triggerWaypoint.Id,
                    context.Plan.Sizing.ProbeQuantity,
                    triggerWaypoint.Range);
            }
        }
    }

    internal sealed class PressPolicy : CampaignPolicyBase
    {
        public override string Name => "press";

        public override IEnumerable<PolicyDecision> Evaluate(CampaignContext context,
            CampaignEvidence evidence)
        {
            if (!context.Plan.Policies.PressEnabled
                || context.State.IsRetired
                || context.State.ExecutionPaused
                || !context.State.HasPosition
                || context.Plan.Sizing.ScaleMode != CampaignScaleMode.EvidenceScaled
                || context.State.SimulatedPositionQuantity >= context.Plan.Sizing.MaxPositionQuantity)
            {
                yield break;
            }

            PriceRange evidenceAnchor = EvidenceAnchor(evidence, context.TickSize);
            if (evidenceAnchor == null)
                yield break;

            PriceRange activeAnchor = context.State.ActiveRiskAnchor ?? context.State.RootRiskAnchor;
            if (activeAnchor == null)
                yield break;
            PriceRange progressionReference = context.State.PendingSponsorAnchor
                ?? activeAnchor;

            if (IsOppositeRepairFailure(context, evidence, evidenceAnchor))
            {
                yield return Decision(
                    PolicyAction.TrackScaleCandidate,
                    Name,
                    "scale_repair_failed",
                    evidence,
                    childRiskAnchor: evidenceAnchor,
                    childRiskAnchorEvidenceId: evidence.EventId,
                    detail: "Opposite repair claim failed; next same-side continuation can participate.",
                    priority: DecisionResolver.PriorityFor(PolicyAction.AllowAdd) + 1);
                yield break;
            }

            if (context.State.AddsSuppressed(context.Now))
                yield break;

            bool sameSideRail = evidence.Kind is EvidenceKind.RailOwned or EvidenceKind.RailHeld
                && CampaignSideMath.IsSameSide(context.Plan.Side, evidence.Side);
            if (!sameSideRail)
                yield break;

            if (!CampaignSideMath.IsFavorableBeyond(
                    context.Plan.Side,
                    evidenceAnchor,
                    progressionReference))
            {
                yield break;
            }

            CampaignWaypoint press = NearestWaypoint(context, evidence, WaypointRole.Press, 12)
                ?? NearestWaypoint(context, evidence, WaypointRole.BuildTrial, 8)
                ?? NearestWaypoint(context, evidence, WaypointRole.RepairHold, 8);
            CampaignWaypoint explicitWaypoint = context.Plan.FindWaypoint(evidence.WaypointId);
            if (press == null && explicitWaypoint != null)
                yield break;

            bool insideArena = context.Plan.Arena?.Intersects(evidenceAnchor) == true;
            if (press == null && !insideArena)
                yield break;
            if (!PriceGateAllows(press, evidence))
                yield break;

            if (!RepairFailureAllowsContinuation(context, evidenceAnchor))
            {
                yield return Decision(
                    PolicyAction.TrackScaleCandidate,
                    Name,
                    press != null
                        ? "scale_candidate_tracked_at_waypoint"
                        : "scale_candidate_tracked_in_arena",
                    evidence,
                    press?.Id,
                    childRiskAnchor: evidenceAnchor,
                    childRiskAnchorEvidenceId: evidence.EventId,
                    detail: "Favorable same-side ownership is tracked as a scale candidate; add requires a repaired-continuation sequence first.");
                yield break;
            }

            int remaining = Math.Max(0,
                context.Plan.Sizing.MaxPositionQuantity - context.State.SimulatedPositionQuantity);
            int quantity = Math.Min(context.Plan.Sizing.AddQuantity, remaining);
            if (quantity <= 0)
                yield break;

            PriceRange riskAnchor = activeAnchor;
            string riskAnchorEvidenceId = context.State.ActiveRiskAnchorEvidenceId
                ?? context.State.RootRiskAnchorEvidenceId;
            bool hasManualPressWaypoint = press != null;
            bool preserveRootLabel = press?.PreserveRiskAnchorOnAdd == true;

            yield return Decision(
                PolicyAction.AllowAdd,
                Name,
                preserveRootLabel
                    ? "same_side_ownership_add_preserve_root_risk"
                    : hasManualPressWaypoint
                        ? "repair_continuation_add_inside_press_window"
                        : "repair_continuation_add_inside_arena",
                evidence,
                press?.Id,
                quantity,
                riskAnchor,
                detail: preserveRootLabel
                    ? "Repaired continuation permits the add; explicit waypoint preserves the current risk anchor."
                    : "Repaired continuation permits the add; the child rail is queued as the next sponsor candidate while older risk remains active.",
                priority: DecisionResolver.PriorityFor(PolicyAction.HoldRoot) + 25,
                riskAnchorEvidenceId: riskAnchorEvidenceId,
                childRiskAnchor: evidenceAnchor,
                childRiskAnchorEvidenceId: evidence.EventId,
                delayRiskAnchorPromotionOnAdd: true);
        }

        private static bool IsOppositeRepairFailure(CampaignContext context,
            CampaignEvidence evidence,
            PriceRange evidenceAnchor)
        {
            if (evidence.Kind != EvidenceKind.RailFailed
                || !CampaignSideMath.IsOppositeSide(context.Plan.Side, evidence.Side)
                || context.State.ScaleRepairAnchor == null)
            {
                return false;
            }

            int toleranceTicks = Math.Max(2, context.Plan.Risk.SponsorFailureBufferTicks);
            return evidenceAnchor.DistanceTicksTo(
                    context.State.ScaleRepairAnchor,
                    context.TickSize)
                <= toleranceTicks;
        }

        private static bool RepairFailureAllowsContinuation(CampaignContext context,
            PriceRange sameSideAnchor)
        {
            PriceRange repairAnchor = context.State.ScaleRepairAnchor;
            return context.State.ScaleRepairFailed
                && repairAnchor != null
                && (sameSideAnchor.Intersects(repairAnchor)
                    || CampaignSideMath.IsFavorableBeyond(
                        context.Plan.Side,
                        sameSideAnchor,
                        repairAnchor));
        }
    }

    internal sealed class BuildTrialPolicy : CampaignPolicyBase
    {
        public override string Name => "build_trial";

        public override IEnumerable<PolicyDecision> Evaluate(CampaignContext context,
            CampaignEvidence evidence)
        {
            if (!context.Plan.Policies.BuildTrialEnabled
                || context.State.IsRetired
                || !context.State.HasPosition)
            {
                yield break;
            }

            PriceRange evidenceRange = evidence.EffectiveRange(context.TickSize);
            bool sameSide = CampaignSideMath.IsSameSide(context.Plan.Side, evidence.Side);

            if (evidence.Kind == EvidenceKind.SponsorFailed)
            {
                yield return Decision(
                    PolicyAction.Flatten,
                    Name,
                    "active_sponsor_failed",
                    evidence,
                    quantity: context.State.SimulatedPositionQuantity,
                    riskAnchor: context.State.ActiveRiskAnchor,
                    priority: DecisionResolver.PriorityFor(PolicyAction.Flatten));
                yield break;
            }

            if (context.State.ActiveRiskAnchor != null
                && evidence.Kind == EvidenceKind.RailFailed
                && CampaignSideMath.IsSameSide(context.Plan.Side, evidence.Side)
                && evidenceRange.DistanceTicksTo(
                    context.State.ActiveRiskAnchor,
                    context.TickSize) <= context.Plan.Risk.SponsorFailureBufferTicks)
            {
                yield return Decision(
                    PolicyAction.Flatten,
                    Name,
                    "risk_anchor_failed",
                    evidence,
                    quantity: context.State.SimulatedPositionQuantity,
                    riskAnchor: context.State.ActiveRiskAnchor,
                    priority: DecisionResolver.PriorityFor(PolicyAction.Flatten));
                yield break;
            }

            CampaignWaypoint buildTrial = NearestWaypoint(context, evidence, WaypointRole.BuildTrial, 10);
            if (buildTrial == null)
                yield break;

            if (evidence.Kind is EvidenceKind.RailOwned or EvidenceKind.RailHeld && sameSide)
            {
                yield return Decision(
                    PolicyAction.HoldRoot,
                    Name,
                    "build_trial_alive",
                    evidence,
                    buildTrial.Id,
                    riskAnchor: EvidenceAnchor(evidence, context.TickSize));
            }

            if (evidence.Kind == EvidenceKind.Absorption
                && sameSide
                && evidence.IsLargeEffort)
            {
                yield return Decision(
                    PolicyAction.Retire,
                    Name,
                    "same_side_effort_no_reward",
                    evidence,
                    buildTrial.Id,
                    context.State.SimulatedPositionQuantity,
                    context.State.ActiveRiskAnchor,
                    priority: DecisionResolver.PriorityFor(PolicyAction.Retire));
            }
        }
    }

    internal sealed class PassiveHarvestPolicy : CampaignPolicyBase
    {
        public override string Name => "passive_harvest";

        public override IEnumerable<PolicyDecision> Evaluate(CampaignContext context,
            CampaignEvidence evidence)
        {
            PassiveHarvestObjective harvest = context.Plan.Objective?.PassiveHarvest;
            if (harvest?.IsUsable != true
                || context.State.IsRetired
                || !context.State.HasPosition)
            {
                yield break;
            }

            if (context.State.PassiveHarvestActive
                && evidence.Price.HasValue
                && harvest.IsFloorLost(context.Plan.Side, evidence.Price.Value, context.TickSize))
            {
                yield return Decision(
                    PolicyAction.Retire,
                    Name,
                    "harvest_floor_lost",
                    evidence,
                    NearestWaypoint(context, evidence, WaypointRole.Target, 12)?.Id,
                    context.State.SimulatedPositionQuantity,
                    riskAnchor: new PriceRange
                    {
                        Lower = harvest.Floor(context.Plan.Side),
                        Upper = harvest.Floor(context.Plan.Side),
                    },
                    priority: 940,
                    detail: "Passive harvest was active, but price lost the harvest floor; clean up remaining inventory.");
                yield break;
            }

            PriceRange evidenceRange = evidence.EffectiveRange(context.TickSize);
            if (!harvest.IsAtOrBeyondFloor(context.Plan.Side, evidenceRange))
                yield break;

            bool atStretch = harvest.IsAtOrBeyondStretch(context.Plan.Side, evidenceRange);
            bool sameSideAbsorbed = evidence.Kind == EvidenceKind.Absorption
                && CampaignSideMath.IsSameSide(context.Plan.Side, evidence.Side)
                && evidence.IsLargeEffort;
            bool oppositeOwnership = evidence.Kind == EvidenceKind.RailOwned
                && CampaignSideMath.IsOppositeSide(context.Plan.Side, evidence.Side);

            string reason = "harvest_floor_reached";
            int priority = 745;
            int quantity = context.State.PassiveHarvestActive
                ? harvest.FollowClipQuantity
                : harvest.InitialClipQuantity;
            if (atStretch)
            {
                reason = "harvest_stretch_reached";
                priority = 880;
                quantity = Math.Max(quantity, harvest.FollowClipQuantity);
            }
            if (sameSideAbsorbed)
            {
                reason = "same_side_effort_absorbed_at_harvest";
                priority = 885;
                quantity = Math.Max(quantity, harvest.FollowClipQuantity);
            }
            if (oppositeOwnership)
            {
                reason = "opposite_ownership_at_harvest";
                priority = 960;
                quantity = Math.Max(quantity, harvest.FollowClipQuantity);
            }

            yield return Decision(
                PolicyAction.PassiveHarvest,
                Name,
                reason,
                evidence,
                NearestWaypoint(context, evidence, WaypointRole.Target, 12)?.Id,
                Math.Min(quantity, Math.Max(1, context.State.SimulatedPositionQuantity)),
                expiresAt: context.Now.AddSeconds(90),
                detail: "Paid target area is active; work reduce-only limit exits before asking for more continuation.",
                priority: priority);
        }
    }

    internal sealed class TargetZonePolicy : CampaignPolicyBase
    {
        public override string Name => "target_zone";

        public override IEnumerable<PolicyDecision> Evaluate(CampaignContext context,
            CampaignEvidence evidence)
        {
            if (!context.Plan.Policies.TargetZoneEnabled
                || context.Plan.Objective?.TargetRange == null
                || context.State.IsRetired
                || !context.IsNearTarget(evidence))
            {
                yield break;
            }

            if (context.Plan.Objective.SuppressAddsInTargetZone)
            {
                yield return Decision(
                    PolicyAction.SuppressAdd,
                    Name,
                    "inside_target_add_suppression",
                    evidence,
                    NearestWaypoint(context, evidence, WaypointRole.Target, 12)?.Id,
                    expiresAt: context.Now.AddSeconds(90),
                    priority: 740);
            }

            if (!context.State.HasPosition)
                yield break;

            bool sameSide = CampaignSideMath.IsSameSide(context.Plan.Side, evidence.Side);
            bool oppositeSide = CampaignSideMath.IsOppositeSide(context.Plan.Side, evidence.Side);
            if (evidence.Kind == EvidenceKind.Absorption && sameSide && evidence.IsLargeEffort)
            {
                yield return Decision(
                    PolicyAction.Reduce,
                    Name,
                    "target_same_side_effort_absorbed",
                    evidence,
                    NearestWaypoint(context, evidence, WaypointRole.Target, 12)?.Id,
                    Math.Min(AddClipQuantity(context),
                        Math.Max(1, context.State.SimulatedPositionQuantity)));
            }

            if (evidence.Kind == EvidenceKind.RailOwned && oppositeSide)
            {
                yield return Decision(
                    PolicyAction.Retire,
                    Name,
                    "opposite_ownership_at_target",
                    evidence,
                    NearestWaypoint(context, evidence, WaypointRole.Target, 12)?.Id,
                    context.State.SimulatedPositionQuantity,
                    EvidenceAnchor(evidence, context.TickSize),
                    priority: DecisionResolver.PriorityFor(PolicyAction.Retire));
            }
        }
    }

    internal sealed class NoAddZonePolicy : CampaignPolicyBase
    {
        public override string Name => "no_add_zone";

        public override IEnumerable<PolicyDecision> Evaluate(CampaignContext context,
            CampaignEvidence evidence)
        {
            if (context.State.IsRetired || !context.State.HasPosition)
                yield break;

            CampaignWaypoint noAdd = NearestWaypoint(context, evidence, WaypointRole.NoAdd, 4);
            if (noAdd == null)
                yield break;

            yield return Decision(
                PolicyAction.SuppressAdd,
                Name,
                "inside_no_add_zone",
                evidence,
                noAdd.Id,
                expiresAt: context.Now.AddSeconds(90),
                detail: "Campaign is allowed to hold risk here, but leverage is locked until fresh evidence appears beyond the no-add corridor.");
        }
    }
    internal sealed class EvaluateZonePolicy : CampaignPolicyBase
    {
        public override string Name => "evaluate_zone";

        public override IEnumerable<PolicyDecision> Evaluate(CampaignContext context,
            CampaignEvidence evidence)
        {
            if (context.State.IsRetired || !context.State.HasPosition)
                yield break;

            CampaignWaypoint evaluate = NearestWaypoint(context, evidence, WaypointRole.Evaluate, 4);
            if (evaluate == null)
                yield break;

            bool sameSide = CampaignSideMath.IsSameSide(context.Plan.Side, evidence.Side);
            bool oppositeSide = CampaignSideMath.IsOppositeSide(context.Plan.Side, evidence.Side);

            if (evidence.Kind == EvidenceKind.Absorption
                && sameSide
                && evidence.IsLargeEffort)
            {
                yield return Decision(
                    PolicyAction.Reduce,
                    Name,
                    "evaluate_same_side_effort_absorbed",
                    evidence,
                    evaluate.Id,
                    Math.Min(AddClipQuantity(context),
                        Math.Max(1, context.State.SimulatedPositionQuantity)),
                    priority: 825);
                yield break;
            }

            if (evidence.Kind == EvidenceKind.RailOwned && oppositeSide)
            {
                yield return Decision(
                    PolicyAction.Reduce,
                    Name,
                    "evaluate_opposite_ownership",
                    evidence,
                    evaluate.Id,
                    Math.Min(AddClipQuantity(context),
                        Math.Max(1, context.State.SimulatedPositionQuantity)),
                    EvidenceAnchor(evidence, context.TickSize),
                    priority: 825);
                yield break;
            }

            yield return Decision(
                PolicyAction.SuppressAdd,
                Name,
                "inside_evaluate_zone",
                evidence,
                evaluate.Id,
                expiresAt: context.Now.AddSeconds(90),
                detail: "Campaign is in a review zone; leverage is locked while evidence is evaluated.",
                priority: 720);
        }
    }
    internal sealed class PathStressPolicy : CampaignPolicyBase
    {
        public override string Name => "path_stress";

        public override IEnumerable<PolicyDecision> Evaluate(CampaignContext context,
            CampaignEvidence evidence)
        {
            if (!context.Plan.Policies.PathStressEnabled
                || context.State.IsRetired
                || !context.State.HasPosition)
            {
                yield break;
            }

            CampaignWaypoint stress = NearestWaypoint(context, evidence, WaypointRole.PathStress, 8);
            if (stress == null)
                yield break;

            DateTimeOffset suppressUntil = context.Now.AddSeconds(120);
            int position = context.State.SimulatedPositionQuantity;
            if (stress.MaxPositionQuantity.HasValue
                && position > stress.MaxPositionQuantity.Value)
            {
                int targetPosition = Math.Max(1, stress.MaxPositionQuantity.Value);
                yield return Decision(
                    PolicyAction.Reduce,
                    Name,
                    "inventory_above_path_cap",
                    evidence,
                    stress.Id,
                    position - targetPosition,
                    expiresAt: suppressUntil,
                    detail: "Path maturity or exposure stress requires harvesting to the waypoint cap before lower objectives are pursued.",
                    priority: 875);
                yield break;
            }

            bool sameSide = CampaignSideMath.IsSameSide(context.Plan.Side, evidence.Side);
            bool oppositeSide = CampaignSideMath.IsOppositeSide(context.Plan.Side, evidence.Side);
            if (evidence.Kind == EvidenceKind.Absorption
                && sameSide
                && evidence.IsLargeEffort)
            {
                yield return Decision(
                    PolicyAction.Reduce,
                    Name,
                    "path_same_side_effort_absorbed",
                    evidence,
                    stress.Id,
                    Math.Min(AddClipQuantity(context),
                        Math.Max(1, position)),
                    expiresAt: suppressUntil,
                    detail: "Same-side effort in a mature path did not earn enough reward; harvest before asking for continuation.",
                    priority: 860);
                yield break;
            }

            if (evidence.Kind == EvidenceKind.RailOwned && oppositeSide)
            {
                yield return Decision(
                    PolicyAction.Reduce,
                    Name,
                    "path_opposite_ownership",
                    evidence,
                    stress.Id,
                    Math.Min(AddClipQuantity(context),
                        Math.Max(1, position)),
                    EvidenceAnchor(evidence, context.TickSize),
                    expiresAt: suppressUntil,
                    detail: "Opposite ownership appeared inside the mature path watch zone; reduce and require fresh continuation proof.",
                    priority: 860);
                yield break;
            }

            yield return Decision(
                PolicyAction.SuppressAdd,
                Name,
                "mature_path_adds_suppressed",
                evidence,
                stress.Id,
                expiresAt: suppressUntil,
                detail: "Path is mature; hold only existing risk until continuation proves itself from this zone.",
                priority: 760);
        }
    }

    internal sealed class RepairHoldPolicy : CampaignPolicyBase
    {
        public override string Name => "repair_hold";

        public override IEnumerable<PolicyDecision> Evaluate(CampaignContext context,
            CampaignEvidence evidence)
        {
            if (!context.Plan.Policies.RepairHoldEnabled
                || context.State.IsRetired
                || !context.State.HasPosition)
            {
                yield break;
            }

            bool sameSide = CampaignSideMath.IsSameSide(context.Plan.Side, evidence.Side);
            bool oppositeSide = CampaignSideMath.IsOppositeSide(context.Plan.Side, evidence.Side);
            CampaignWaypoint repairHold = NearestWaypoint(context, evidence, WaypointRole.RepairHold, 10);

            if (repairHold != null
                && evidence.Kind is EvidenceKind.RailHeld or EvidenceKind.RailOwned
                && sameSide)
            {
                yield return Decision(
                    PolicyAction.HoldRoot,
                    Name,
                    "repair_hold_supports_campaign",
                    evidence,
                    repairHold.Id,
                    riskAnchor: EvidenceAnchor(evidence, context.TickSize));
            }

            if (evidence.Kind is EvidenceKind.RailOwned or EvidenceKind.RailHeld
                && oppositeSide)
            {
                PriceRange evidenceAnchor = EvidenceAnchor(evidence, context.TickSize);
                bool hitsRiskAnchor = context.State.ActiveRiskAnchor != null
                    && evidenceAnchor != null
                    && evidenceAnchor.DistanceTicksTo(
                        context.State.ActiveRiskAnchor,
                        context.TickSize) <= context.Plan.Risk.SponsorFailureBufferTicks;
                if (!hitsRiskAnchor && context.Plan.Risk.AllowContestBeyondRiskAnchor)
                {
                    bool scaleRepair = IsScaleRepairClaim(context, evidenceAnchor);
                    yield return Decision(
                        PolicyAction.SuppressAdd,
                        Name,
                        "non_causal_adverse_claim",
                        evidence,
                        repairHold?.Id,
                        expiresAt: context.Now.AddSeconds(45),
                        detail: scaleRepair
                            ? "Opposite repair claim is alive; suppress leverage until it fails or expires."
                            : "Adverse claim is not the active risk anchor; suppress leverage but do not flatten.",
                        childRiskAnchor: scaleRepair ? evidenceAnchor : null,
                        childRiskAnchorEvidenceId: scaleRepair ? evidence.EventId : null);
                }
            }
        }

        private static bool IsScaleRepairClaim(CampaignContext context,
            PriceRange evidenceAnchor)
        {
            if (context.Plan.Sizing.ScaleMode != CampaignScaleMode.EvidenceScaled
                || evidenceAnchor == null
                || context.Plan.Arena?.Intersects(evidenceAnchor) != true)
            {
                return false;
            }

            PriceRange reference = context.State.PendingSponsorAnchor
                ?? context.State.ActiveRiskAnchor
                ?? context.State.RootRiskAnchor;
            if (reference == null)
                return false;

            if (CampaignSideMath.IsFavorableBeyond(
                    context.Plan.Side,
                    evidenceAnchor,
                    reference))
            {
                return true;
            }

            PriceRange candidate = context.State.ScaleCandidateAnchor;
            return candidate != null
                && evidenceAnchor.DistanceTicksTo(
                    candidate,
                    context.TickSize)
                <= Math.Max(4, context.Plan.Risk.RootStopTicks);
        }
    }
}
