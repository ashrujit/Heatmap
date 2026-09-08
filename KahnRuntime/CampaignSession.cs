using System;
using System.Collections.Generic;
using System.Linq;
using KahnRuntime.Scaling;

namespace KahnRuntime
{
    // Worker-owned; no broker dependencies. Reports are cumulative order facts, not position guesses.
    internal sealed class CampaignSession
    {
        public CampaignPlan Plan { get; }
        public CampaignState State { get; }
        public string InstanceId { get; }
        public double TickSize { get; }
        public RepairEpisodeObserver Observer { get; }
        public GroupSponsorState Sponsors { get; private set; }
        public ScaleOrderReservations Reservations { get; private set; }
        public DateTimeOffset AuthorizedAt { get; private set; }
        public string RecoveryReason { get; private set; }
        public CampaignOrder Outstanding => _orders.Values.FirstOrDefault(o => !o.Terminal);
        public bool HasUnresolvedOrder => Outstanding != null;
        private readonly Dictionary<string, CampaignOrder> _orders = new(StringComparer.Ordinal);
        private bool _attemptOpen;
        private CampaignOrder _awaitingRootObservation;
        public (PolicyDecision Decision, CampaignEvidence Evidence)? PendingRiskExit { get; private set; }
        private readonly CampaignPolicyEngine _policies = CampaignPolicyEngine.CreateDefault();

        public IReadOnlyList<(PolicyDecision Decision, CampaignEvidence Evidence)> PolicyCandidates(
            IEnumerable<CampaignEvidence> evidence, DateTimeOffset now)
        {
            var choices = new List<(PolicyDecision Decision, CampaignEvidence Evidence)>();
            CampaignOrder pendingRoot = Outstanding?.Decision.Action == PolicyAction.AllowProbe ? Outstanding : null;
            foreach (CampaignEvidence item in evidence)
            {
                if (pendingRoot?.Filled == 0 && item.Kind is EvidenceKind.RailFailed or EvidenceKind.SponsorFailed
                    && item.Source == pendingRoot.Evidence.Source && item.EvidenceEpoch == pendingRoot.Evidence.EvidenceEpoch
                    && item.RailId != null && item.RailId == pendingRoot.Evidence.RailId)
                    pendingRoot.FailureBeforeFill = item;
                PolicyDecision decision = _policies.Evaluate(new(Plan, State, TickSize, now), item);
                if (decision.Action is PolicyAction.AllowProbe or PolicyAction.ArmProbe)
                {
                    if (item.Timestamp <= AuthorizedAt || !State.ExecutionAuthorized
                        || HasUnresolvedOrder || RecoveryReason != null) continue;
                    if (item.EvidenceEpoch != null && item.Kind is EvidenceKind.RailOwned or EvidenceKind.RailHeld)
                    {
                        var claim = Observer.Find(new(EvidenceSource.LevelLedger, item.EvidenceEpoch, item.RailId));
                        if (claim?.Confirmed != true) continue;
                    }
                }
                if (decision.Action != PolicyAction.NoAction) choices.Add((decision, item));
            }
            if (PendingRiskExit.HasValue && State.HasPosition) choices.Add(PendingRiskExit.Value);
            if (State.HasPosition && Sponsors?.ActiveHealth == GroupHealth.Failed)
            {
                var failed = new CampaignEvidence { EventId = "group-failed-" + Sponsors.Active.EpisodeId,
                    Timestamp = now, Source = EvidenceSource.LevelLedger, Kind = EvidenceKind.SponsorFailed };
                choices.Add((new PolicyDecision { Action = PolicyAction.Flatten, Policy = "group_sponsor",
                    ReasonCode = "active_group_failed", Priority = 1000, Quantity = State.SimulatedPositionQuantity,
                    EvidenceId = failed.EventId }, failed));
            }
            var exit = choices.Where(x => x.Decision.Action is PolicyAction.Flatten or PolicyAction.Retire)
                .OrderByDescending(x => x.Decision.Priority).FirstOrDefault();
            if (State.HasPosition && exit.Decision != null) PendingRiskExit = exit;
            return choices;
        }

        public bool IsPendingRiskExit(PolicyDecision decision)
            => decision != null && PendingRiskExit?.Decision == decision;

        public void AcknowledgeRiskExit(PolicyDecision decision)
        {
            if (IsPendingRiskExit(decision)) PendingRiskExit = null;
        }

        public CampaignSession(CampaignPlan plan, CampaignState state, string instanceId,
            double tickSize, TimeSpan maximumSampleGap)
        {
            Plan = plan;
            State = state;
            InstanceId = instanceId;
            TickSize = tickSize;
            PriceRange root = plan.WaypointsByRole(WaypointRole.TrapProbe).FirstOrDefault()?.Range ?? plan.Arena;
            Observer = new(plan.Side, Ticks(root), maximumSampleGap);
        }

        public TickInterval Ticks(PriceRange range)
            => new((long)Math.Round(range.Lower / TickSize), (long)Math.Round(range.Upper / TickSize));

        public double ProtectionPrice(double average)
        {
            double offset = Math.Max(0, Plan.Risk.BreakevenBackstopOffsetTicks) * TickSize;
            double trigger = Plan.Side == CampaignSide.Long
                ? Math.Ceiling((average + offset) / TickSize - 1e-9) * TickSize
                : Math.Floor((average - offset) / TickSize + 1e-9) * TickSize;
            foreach (double? prior in new[] { State.OperatorProtectionPrice,
                State.BreakevenBackstopActive ? State.BreakevenBackstopPrice : null })
                if (prior.HasValue) trigger = Plan.Side == CampaignSide.Long
                    ? Math.Max(trigger, prior.Value) : Math.Min(trigger, prior.Value);
            return trigger;
        }

        public string ValidateControl(RuntimeControlCommand command, DateTimeOffset now)
        {
            if (command.SchemaVersion != 2 || command.CampaignId != Plan.Id
                || command.CampaignDigest != Plan.Digest || command.RuntimeInstanceId != InstanceId
                || command.Attempt != State.ExecutionAttemptCount)
                return "rejected_scope";
            if (command.CreatedAt > now || now - command.CreatedAt > TimeSpan.FromSeconds(15))
                return "rejected_stale_control";
            if (State.IsRetired || State.ExecutionPaused || RecoveryReason != null || HasUnresolvedOrder)
                return "rejected_lifecycle";
            return null;
        }

        public string GoLive(RuntimeControlCommand command, DateTimeOffset now)
        {
            string error = ValidateControl(command, now);
            if (error != null) return error;
            if (State.HasPosition || !Plan.IsActiveAt(now)) return "rejected_not_watched_or_expired";
            if (!State.ExecutionAuthorized)
            {
                State.AuthorizeExecution();
                AuthorizedAt = now;
            }
            return "accepted";
        }

        public void Observe(RepairSample sample)
        {
            if (Observer.Epoch != sample.Epoch)
                Observer.StartEpoch(sample.Epoch, sample.At, sample.PriceTicks);
            Observer.Observe(sample);
            if (_awaitingRootObservation != null && !Observer.Suspended)
                StartRootObservation(_awaitingRootObservation, sample.At, sample.PriceTicks, false);
            Sponsors?.Observe(Observer);
            State.GroupSponsorActive = Sponsors?.Active != null;
        }

        public void ConfirmFlat(DateTimeOffset now)
        {
            if (!_attemptOpen || HasUnresolvedOrder || State.HasPosition) return;
            Observer.EndFlatAttempt(now, "confirmed_flat_attempt_end");
            Sponsors = null;
            Reservations = null;
            _awaitingRootObservation = null;
            PendingRiskExit = null;
            State.GroupSponsorActive = false;
            _attemptOpen = false;
        }

        public void RequireRecovery(string reason)
        {
            RecoveryReason = reason;
            State.RevokeExecution();
        }

        public CampaignOrder Reserve(PolicyDecision decision, CampaignEvidence evidence,
            ScaleReservationSnapshot scale, DateTimeOffset now)
        {
            if (HasUnresolvedOrder || RecoveryReason != null || !State.ExecutionAuthorized)
                throw new InvalidOperationException("New risk is not admissible.");
            int quantity = scale?.RequestedQuantity ?? decision.Quantity ?? Plan.Sizing.ProbeQuantity;
            if (decision.Action is not (PolicyAction.AllowProbe or PolicyAction.AllowAdd)
                || quantity <= 0 || quantity > Plan.Sizing.MaxPositionQuantity - State.SimulatedPositionQuantity
                || (decision.Action == PolicyAction.AllowProbe && (State.HasPosition || !Plan.IsActiveAt(now) || !State.CanAttemptEntry(Plan)))
                || (decision.Action == PolicyAction.AllowAdd && (scale == null || Reservations?.Outstanding?.Id != scale.Id)))
                throw new InvalidOperationException("Invalid entry or episode reservation.");
            var order = new CampaignOrder(Guid.NewGuid().ToString("N"), decision, evidence,
                scale?.Id, quantity, State.SimulatedPositionQuantity, State.SimulatedAveragePrice ?? 0, now);
            _orders.Add(order.Id, order);
            return order;
        }

        public void Submitted(CampaignOrder order, string brokerOrderId, bool accepted, bool uncertain)
        {
            if ((order.BrokerOrderId != null && order.BrokerOrderId != brokerOrderId)
                || (!string.IsNullOrWhiteSpace(brokerOrderId) && _orders.Values.Any(o => o != order && o.BrokerOrderId == brokerOrderId)))
                throw new InvalidOperationException("Broker order identity cannot be rebound or reused.");
            order.BrokerOrderId = brokerOrderId;
            if (accepted && !string.IsNullOrWhiteSpace(brokerOrderId))
            {
                if (order.ScaleReservationId != null)
                    Reservations.AcknowledgeSubmission(order.ScaleReservationId, brokerOrderId);
                return;
            }
            if (uncertain || accepted)
            {
                RequireRecovery("submission_identity_or_outcome_uncertain");
                if (order.ScaleReservationId != null)
                    Reservations.MarkUncertain(order.ScaleReservationId, RecoveryReason);
            }
        }

        public CampaignOrder FindBrokerOrder(string id)
            => string.IsNullOrWhiteSpace(id) ? null : _orders.Values.FirstOrDefault(o => o.BrokerOrderId == id);

        public bool PositionMatchesAttributedFills(double quantity, double average)
            => State.HasPosition && double.IsFinite(quantity) && quantity == State.SimulatedPositionQuantity
                && double.IsFinite(average) && average > 0 && State.SimulatedAveragePrice.HasValue
                && Math.Abs(average - State.SimulatedAveragePrice.Value) <= TickSize / 2;

        public bool CanProtectPosition(string managedId, string observedId, CampaignSide side,
            double quantity, double average, bool ambiguous)
            => !ambiguous && !string.IsNullOrWhiteSpace(managedId) && observedId == managedId
                && side == Plan.Side && PositionMatchesAttributedFills(quantity, average);

        public bool TryReconcilePositionAverage(int quantity, double average)
        {
            if (quantity <= 0 || quantity != State.SimulatedPositionQuantity
                || !double.IsFinite(average) || average <= 0) return false;
            // Quantower can publish an add's new average before its quantity/trade callback.
            // Until fill attribution catches up, that mixed snapshot cannot reprice old inventory.
            if (HasUnresolvedOrder && !PositionMatchesAttributedFills(quantity, average)) return false;
            State.ReconcileFill(quantity, average);
            return true;
        }

        public CampaignOrder ReportBrokerEvent(BrokerEvent report, DateTimeOffset now, double executableTicks)
        {
            CampaignOrder order = FindBrokerOrder(report.OrderId);
            if (order == null || (report.EventType != "trade_fill"
                && report.EventType?.StartsWith("order_", StringComparison.Ordinal) != true)) return null;
            if (!string.IsNullOrWhiteSpace(report.PositionId))
            {
                if (order.PositionId != null && order.PositionId != report.PositionId)
                    throw new InvalidOperationException("Reserved order changed broker position identity.");
                order.PositionId = report.PositionId;
            }
            BrokerFillSnapshot fill = order.BrokerFills.Observe(report, Plan.Side);
            double? average = fill.Average;
            if (fill.Quantity == order.Filled && average.HasValue && order.FillAverage.HasValue
                && Math.Abs(average.Value - order.FillAverage.Value) <= 0.000001) average = order.FillAverage;
            Report(order, fill.Quantity, average, fill.Terminal, now, executableTicks);
            return order;
        }

        public bool Report(CampaignOrder order, int filled, double? average, bool terminal,
            DateTimeOffset now, double executableTicks)
        {
            if (now < order.SubmittedAt || filled < order.Filled || filled > order.Quantity
                || (filled == 0 && average.HasValue)
                || (filled > 0 && (!average.HasValue || !double.IsFinite(average.Value) || average <= 0))
                || (filled == order.Filled && average != order.FillAverage))
                throw new InvalidOperationException("Contradictory cumulative fill report; recovery required.");
            if (order.Terminal && filled == order.Filled) return false;
            bool first = order.Filled == 0 && filled > 0;
            bool retired = State.IsRetired;
            bool late = order.Terminal && filled > order.Filled;
            int added = filled - order.Filled;
            int positionBefore = State.SimulatedPositionQuantity;
            double valueBefore = (State.SimulatedAveragePrice ?? 0) * positionBefore;
            double addedValue = filled * (average ?? 0) - order.Filled * (order.FillAverage ?? 0);
            if (order.ScaleReservationId != null && !late)
                Reservations.Report(order.ScaleReservationId, filled, average / TickSize, terminal, now, executableTicks);
            if (first)
            {
                State.ApplyDecision(new PolicyDecision
                {
                    Action = order.Decision.Action, Policy = order.Decision.Policy,
                    ReasonCode = order.Decision.ReasonCode, Quantity = filled,
                    RiskAnchor = order.Decision.RiskAnchor,
                    RiskAnchorEvidenceId = order.Decision.RiskAnchorEvidenceId,
                    EvidenceId = order.Evidence.EventId,
                }, Plan, true, now, simulatedFillPrice: average);
                if (order.Decision.Action == PolicyAction.AllowProbe)
                {
                    TickInterval root = Ticks(State.RootRiskAnchor ?? Plan.Arena);
                    Sponsors = new(Plan.Side, root);
                    _attemptOpen = true;
                    if (!Observer.Suspended && Observer.FreshAt(now) && double.IsFinite(executableTicks))
                        StartRootObservation(order, now, executableTicks, State.ExecutionAttemptCount == 1 && order.CarryLiveEvidence);
                    else
                    {
                        Observer.Suspend(now, "root_fill_needs_fresh_observation");
                        _awaitingRootObservation = order;
                    }
                }
            }
            if (added > 0)
            {
                // Only new fills change exposure; repeated snapshots cannot undo an intervening exit.
                State.ReconcileFill(positionBefore + added, (valueBefore + addedValue) / (positionBefore + added));
                if (first && order.FailureBeforeFill != null)
                {
                    PolicyDecision failure = _policies.Evaluate(new(Plan, State, TickSize, now), order.FailureBeforeFill);
                    if (failure.Action is PolicyAction.Flatten or PolicyAction.Retire)
                        PendingRiskExit = (failure, order.FailureBeforeFill);
                }
            }
            order.Filled = filled;
            order.FillAverage = average;
            order.Terminal |= terminal || filled == order.Quantity;
            State.GroupSponsorActive = Sponsors?.Active != null;
            if (retired && filled > 0)
            {
                State.ApplyDecision(new PolicyDecision { Action = PolicyAction.Retire }, Plan, false, now);
                RequireRecovery("late_fill_after_retirement_requires_flat");
            }
            else if (late) RequireRecovery("late_fill_after_terminal_order");
            return first;
        }

        private void StartRootObservation(CampaignOrder order, DateTimeOffset now, double priceTicks, bool carry)
        {
            ClaimKey? key = order.Evidence.Source == EvidenceSource.LevelLedger
                && order.Evidence.EvidenceEpoch != null && order.Evidence.RailId != null
                ? new ClaimKey(EvidenceSource.LevelLedger, order.Evidence.EvidenceEpoch, order.Evidence.RailId) : null;
            Observer.BeginAttempt(State.ExecutionAttemptCount, Sponsors.RootAnchor, now, priceTicks, key, carry);
            Reservations = new(Observer, Sponsors);
            _awaitingRootObservation = null;
        }
    }

    internal sealed class CampaignOrder
    {
        public string Id { get; }
        public PolicyDecision Decision { get; }
        public CampaignEvidence Evidence { get; }
        public string ScaleReservationId { get; }
        public int Quantity { get; }
        public int PositionBefore { get; }
        public double AverageBefore { get; }
        public DateTimeOffset SubmittedAt { get; }
        public string BrokerOrderId { get; set; }
        public int Filled { get; set; }
        public double? FillAverage { get; set; }
        public bool Terminal { get; set; }
        public bool CarryLiveEvidence { get; set; } = true;
        public string PositionId { get; set; }
        public CampaignEvidence FailureBeforeFill { get; set; }
        public BrokerFillLedger BrokerFills { get; }
        public CampaignOrder(string id, PolicyDecision decision, CampaignEvidence evidence, string scaleId,
            int quantity, int before, double average, DateTimeOffset at)
        {
            Id = id; Decision = decision; Evidence = evidence; ScaleReservationId = scaleId;
            Quantity = quantity; PositionBefore = before; AverageBefore = average; SubmittedAt = at;
            BrokerFills = new(quantity);
        }
    }
}
