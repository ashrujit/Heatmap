using System;
using System.Linq;
using KahnRuntime.Scaling;

namespace KahnRuntime
{
    internal sealed record ContinuationEntryContext(DateTimeOffset At, DateTimeOffset QuoteAt,
        TimeSpan MaxQuoteAge, TimeSpan MaxEvidenceAge, double BidTicks, double AskTicks,
        bool FlatAndReconciled, bool OrdersClear, bool PolicyAllowsEntry, int InstanceMaxQuantity);

    internal sealed partial class CampaignSession
    {
        public bool TryContinuationEntry(ContinuationEntryContext context,
            out PolicyDecision decision, out CampaignEvidence evidence, out string reason)
        {
            decision = null;
            evidence = null;
            ScaleOpportunity opportunity = Observer.Opportunity;
            reason = ContinuationGate(opportunity, context);
            if (reason != null)
            {
                if (opportunity != null && !State.HasPosition && !HasUnresolvedOrder)
                    Observer.Miss(opportunity, context.At, reason);
                return false;
            }
            double management = Plan.Side == CampaignSide.Long ? context.BidTicks : context.AskTicks;
            ProofGroup proof = Observer.CurrentProof(opportunity.Proof, management);
            if (proof == null || Roots.Health(proof, Plan.Side, context.At) != GroupHealth.Live)
            {
                reason = "entry_sponsor_not_live";
                Observer.Miss(opportunity, context.At, reason);
                return false;
            }
            string id = $"continuation-entry:{opportunity.Attempt}:{opportunity.Generation}:{opportunity.EpisodeId}";
            evidence = new() { EventId = id, Timestamp = opportunity.At, Source = EvidenceSource.LevelLedger,
                Kind = EvidenceKind.RailHeld, Side = Plan.Side == CampaignSide.Long ? EvidenceSide.Demand : EvidenceSide.Supply,
                Price = (Plan.Side == CampaignSide.Long ? context.AskTicks : context.BidTicks) * TickSize };
            decision = new() { Action = PolicyAction.AllowProbe, Policy = "continuation_entry",
                ReasonCode = "repaired_continuation_first_entry", Priority = 525,
                Quantity = Plan.Sizing.ProbeQuantity, EvidenceId = id,
                EntryOpportunity = opportunity, EntrySponsor = proof,
                // The envelope is diagnostic geometry only. Exact members own all failure decisions.
                RiskAnchor = new() { Lower = proof.Coverage.Min(r => r.Lower) * TickSize,
                    Upper = proof.Coverage.Max(r => r.Upper) * TickSize }, RiskAnchorEvidenceId = id };
            reason = RevalidateContinuation(decision, context);
            if (reason == null) return true;
            Observer.Miss(opportunity, context.At, reason);
            decision = null;
            evidence = null;
            return false;
        }

        private string ContinuationGate(ScaleOpportunity opportunity, ContinuationEntryContext c)
        {
            if (Plan.SchemaVersion != 2 || Plan.Execution.StrictProbeRange) return "strict_probe_range";
            if (!State.ExecutionAuthorized || State.IsRetired || !State.CanAttemptEntry(Plan)
                || !Plan.IsActiveAt(c.At)) return "entry_not_authorized_or_expired";
            if (State.HasPosition || !c.FlatAndReconciled) return "entry_requires_flat";
            if (HasUnresolvedOrder || !c.OrdersClear || RecoveryReason != null || RootRiskRecoveryReason != null)
                return "entry_unresolved_or_recovering";
            if (!c.PolicyAllowsEntry || !Plan.Policies.PressEnabled || State.AddsSuppressed(c.At)) return "entry_policy_veto";
            if (Plan.Sizing.ProbeQuantity > c.InstanceMaxQuantity || Plan.Sizing.ProbeQuantity > Plan.Sizing.MaxPositionQuantity)
                return "entry_capacity";
            if (!Observer.FreshAt(c.At) || c.At < c.QuoteAt || c.QuoteAt == default
                || c.MaxQuoteAge <= TimeSpan.Zero || c.MaxEvidenceAge <= TimeSpan.Zero
                || c.At - c.QuoteAt > c.MaxQuoteAge || c.At - Observer.LastCompleteSampleAt > c.MaxEvidenceAge
                || !double.IsFinite(c.BidTicks) || !double.IsFinite(c.AskTicks) || c.BidTicks <= 0 || c.BidTicks >= c.AskTicks)
                return "entry_stale_market";
            if (opportunity == null || opportunity.At <= AuthorizedAt || opportunity.RepairResolvedAt <= AuthorizedAt
                || opportunity.At > c.At || c.At - opportunity.At > c.MaxEvidenceAge)
                return "entry_requires_fresh_continuation";
            double price = (Plan.Side == CampaignSide.Long ? c.AskTicks : c.BidTicks) * TickSize;
            var probes = Plan.WaypointsByRole(WaypointRole.TrapProbe).ToArray();
            if (!Plan.Arena.Contains(price) || probes.Length == 0 || probes.Any(w => w.Range.Contains(price))
                || !(Plan.Side == CampaignSide.Long ? price > probes.Max(w => w.Range.Upper)
                    : price < probes.Min(w => w.Range.Lower))) return "entry_outside_continuation_area";
            PriceRange target = Plan.Objective?.PassiveHarvest?.IsUsable == true
                ? Plan.Objective.PassiveHarvest.Range : Plan.Objective?.TargetRange;
            double buffer = (Plan.Objective?.TargetProximityTicks ?? 0) * TickSize;
            if (State.PassiveHarvestActive || State.Phase == CampaignPhase.TargetZone || (target != null
                && (Plan.Side == CampaignSide.Long ? price >= target.Lower - buffer : price <= target.Upper + buffer)))
                return "entry_at_target";
            return Observer.Revalidate(opportunity, Plan.Side == CampaignSide.Long ? c.BidTicks : c.AskTicks);
        }

        public string RevalidateContinuation(PolicyDecision decision, ContinuationEntryContext context)
        {
            string reason = ContinuationGate(decision.EntryOpportunity, context);
            if (reason != null) return reason;
            ProofGroup proof = decision.EntrySponsor;
            if (proof == null || proof.EpisodeId != decision.EntryOpportunity.EpisodeId
                || proof.Members.Any(m => !decision.EntryOpportunity.Proof.Members.Contains(m))
                || Roots.Health(proof, Plan.Side, context.At) != GroupHealth.Live)
                return "entry_sponsor_not_live";
            double management = Plan.Side == CampaignSide.Long ? context.BidTicks : context.AskTicks;
            if (Observer.CurrentProof(proof, management) == null) return "entry_sponsor_not_clear";
            double entry = Plan.Side == CampaignSide.Long ? context.AskTicks : context.BidTicks;
            double distance = EntrySponsorDistance(proof, entry);
            return Plan.Risk.MaxRootEntryDistanceTicks is int max && distance > max + 1e-8
                ? "root_entry_distance_exceeded" : null;
        }

        private double EntrySponsorDistance(ProofGroup proof, double entryTicks)
            => Plan.Side == CampaignSide.Long ? entryTicks - proof.Coverage.Min(r => r.Lower)
                : proof.Coverage.Max(r => r.Upper) - entryTicks;

        private CampaignEvidence EntrySponsorFailure(CampaignOrder order, DateTimeOffset at)
            => new() { EventId = "entry-sponsor-failed:" + order.Id, Timestamp = at,
                Source = EvidenceSource.LevelLedger, Kind = EvidenceKind.SponsorFailed };

        private void LatchEntrySponsorExit(CampaignOrder order, DateTimeOffset at)
        {
            if (!State.HasPosition) return;
            var failed = order.FailureBeforeFill ?? EntrySponsorFailure(order, at);
            PendingRiskExit ??= (new PolicyDecision { Action = PolicyAction.Flatten,
                Policy = "group_sponsor", ReasonCode = "active_group_failed", Priority = 1000,
                Quantity = State.SimulatedPositionQuantity, EvidenceId = failed.EventId }, failed);
        }

        private void RefreshPendingEntrySponsor(CampaignOrder order, DateTimeOffset now)
        {
            var proof = order.Decision.EntrySponsor;
            GroupHealth health = Roots.Health(proof, Plan.Side, now);
            bool lost = proof.Members.Any(m => Roots.TrackingLost(m.Key, Plan.Side, m.Coverage));
            if (health == GroupHealth.Failed)
            {
                order.FailureBeforeFill ??= EntrySponsorFailure(order, now);
                order.CancelReason ??= "entry_sponsor_failed";
                if (order.Filled > 0) LatchEntrySponsorExit(order, now);
            }
            else if (health == GroupHealth.Unknown && lost)
            {
                order.TrackingLostBeforeFill = true;
                order.CancelReason ??= "entry_sponsor_tracking_lost";
                LatchTrackingLoss(now, "entry_sponsor_tracking_lost");
            }
            else if (health == GroupHealth.Unknown)
                order.CancelReason ??= "entry_sponsor_health_unknown";
        }
    }
}
