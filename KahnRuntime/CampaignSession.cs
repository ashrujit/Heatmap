using System;
using System.Collections.Generic;
using System.Linq;
using KahnRuntime.Scaling;

namespace KahnRuntime
{
    // Worker-owned; no broker dependencies. Reports are cumulative order facts, not position guesses.
    internal sealed partial class CampaignSession
    {
        public CampaignPlan Plan { get; }
        public CampaignState State { get; }
        public string InstanceId { get; }
        public double TickSize { get; }
        public RepairEpisodeObserver Observer { get; }
        public RootEvidenceLedger Roots { get; }
        public string RootRiskRecoveryReason { get; private set; }
        public string LastRootAdmissionReason { get; private set; }
        public double? RootEntryDistanceTicks { get; private set; }
        private readonly Queue<RootRiskAudit> _rootAudit = new();
        private readonly HashSet<(string Epoch, string Rail, EvidenceKind Kind, DateTimeOffset At)> _reservedRootTriggers = new();
        public GroupSponsorState Sponsors { get; private set; }
        public ScaleOrderReservations Reservations { get; private set; }
        public DateTimeOffset AuthorizedAt { get; private set; }
        public string RecoveryReason { get; private set; }
        public CampaignOrder Outstanding => _orders.Values.FirstOrDefault(o => !o.Terminal);
        public bool HasUnresolvedOrder => Outstanding != null;
        private readonly Dictionary<string, CampaignOrder> _orders = new(StringComparer.Ordinal);
        private bool _attemptOpen;
        private CampaignOrder _awaitingRootObservation;
        private string _lastRiskHealthReason;
        public (PolicyDecision Decision, CampaignEvidence Evidence)? PendingRiskExit { get; private set; }
        private readonly CampaignPolicyEngine _policies = CampaignPolicyEngine.CreateDefault();

        public IReadOnlyList<(PolicyDecision Decision, CampaignEvidence Evidence)> PolicyCandidates(
            IEnumerable<CampaignEvidence> evidence, DateTimeOffset now)
        {
            var choices = new List<(PolicyDecision Decision, CampaignEvidence Evidence)>();
            RefreshRiskHealth(now);
            foreach (CampaignEvidence item in evidence)
            {
                if (item.Kind is EvidenceKind.RailFailed or EvidenceKind.SponsorFailed)
                {
                    Roots.RecordFailure(item);
                    foreach (CampaignOrder order in _orders.Values.Where(o => o.Decision.Action == PolicyAction.AllowProbe
                        && o.Decision.RootBinding?.Matches(item) == true))
                        MarkRootFailure(order, item);
                    if (State.RootBinding?.Matches(item) == true) LatchRootExit(State.RootBinding, item);
                }
                PolicyDecision decision = _policies.Evaluate(new(Plan, State, TickSize, now, Roots), item);
                if (decision.Policy == "root_risk" && item.Timestamp > AuthorizedAt && State.ExecutionAuthorized)
                {
                    LastRootAdmissionReason = decision.ReasonCode;
                    _rootAudit.Enqueue(new(now, decision.ReasonCode, item.EventId, decision.RootBinding,
                        decision.RootBinding != null && item.Price.HasValue
                            ? decision.RootBinding.EntryDistanceTicks(item.Price.Value, TickSize) : null));
                }
                if (decision.Action is PolicyAction.AllowProbe or PolicyAction.ArmProbe)
                {
                    if (!Observer.FreshAt(now))
                    {
                        LastRootAdmissionReason = "root_observation_recovering";
                        _rootAudit.Enqueue(new(now, LastRootAdmissionReason, item.EventId, decision.RootBinding, null));
                        continue;
                    }
                    if (item.Timestamp <= AuthorizedAt || !State.ExecutionAuthorized
                        || HasUnresolvedOrder || RecoveryReason != null || RootRiskRecoveryReason != null) continue;
                    if (decision.Action == PolicyAction.AllowProbe
                        && _reservedRootTriggers.Contains((item.EvidenceEpoch, item.RailId, item.Kind, item.Timestamp))) continue;
                }
                if (State.HasPosition && !State.GroupSponsorActive && State.RootBinding != null
                    && item.Kind == EvidenceKind.RailFailed && CampaignSideMath.IsSameSide(Plan.Side, item.Side)
                    && !State.RootBinding.Matches(item))
                    _rootAudit.Enqueue(new(now, "non_owner_failure_ignored", item.EventId, State.RootBinding, null));
                if (decision.Action != PolicyAction.NoAction) choices.Add((decision, item));
            }
            RefreshRiskHealth(now);
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
            Roots = new(maximumSampleGap);
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
                if (!Plan.Execution.StrictProbeRange) Observer.EnableContinuationEntry(now);
            }
            return "accepted";
        }

        public bool ObserveRootSample(RepairSample sample, IReadOnlyList<RootClaim> rootSnapshot = null)
        {
            Roots.Observe(sample, rootSnapshot);
            RefreshRiskHealth(sample.At);
            return Roots.Available;
        }

        public void Observe(RepairSample sample, IReadOnlyList<RootClaim> rootSnapshot = null, bool recoverScale = false)
        {
            ObserveRootSample(sample, rootSnapshot);
            if (!Roots.Available)
            {
                DateTimeOffset at = sample.At < Observer.LastObservedAt ? Observer.LastObservedAt : sample.At;
                Observer.Suspend(at, "root_sample_invalid");
                RefreshRootRisk(at);
                return;
            }
            if (!double.IsFinite(sample.PriceTicks) || sample.At < Observer.LastObservedAt)
            {
                Observer.Suspend(Observer.LastObservedAt > sample.At ? Observer.LastObservedAt : sample.At,
                    "sample_order_or_price_invalid");
                return;
            }
            if (Observer.Epoch != sample.Epoch)
                Observer.StartEpoch(sample.Epoch, sample.At, sample.PriceTicks);
            else if (recoverScale && Observer.Suspended)
                Observer.ResumeObservation(sample.At, sample.PriceTicks);
            Observer.Observe(sample);
            if (_awaitingRootObservation != null && !Observer.Suspended)
                StartRootObservation(_awaitingRootObservation, sample.At, sample.PriceTicks, false);
            RefreshRiskHealth(sample.At);
        }

        public void SuspendObservation(DateTimeOffset now, string reason)
        {
            Observer.Suspend(now, reason);
            SuspendRootEvidence(now);
        }

        public void RefreshRiskHealth(DateTimeOffset now)
        {
            Sponsors?.Observe(Observer, Roots, now);
            State.GroupSponsorActive = Sponsors?.Active != null;
            RefreshRootRisk(now);
        }

        public IReadOnlyList<RootRiskAudit> DrainRootAudit()
        {
            var result = _rootAudit.ToArray();
            _rootAudit.Clear();
            return result;
        }

        public void SuspendRootEvidence(DateTimeOffset now)
        {
            Roots.Suspend();
            RefreshRiskHealth(now);
        }

        private CampaignEvidence OwnerFailure(RootRiskBinding binding, DateTimeOffset at)
            => new() { EventId = "root-owner-failed-" + binding.Owner.Key, Timestamp = at,
                Source = binding.Owner.Key.Source, EvidenceEpoch = binding.Owner.Key.Epoch,
                RailId = binding.Owner.Key.RailId, Kind = EvidenceKind.RailFailed,
                Side = binding.Owner.Side == CampaignSide.Long ? EvidenceSide.Demand : EvidenceSide.Supply,
                Range = binding.Range(TickSize), RailOrigin = binding.Owner.Origin };

        private void MarkRootFailure(CampaignOrder order, CampaignEvidence failed)
        {
            order.FailureBeforeFill ??= failed;
            if (!order.Terminal) order.CancelReason ??= "root_owner_failed";
        }

        private void LatchRootExit(RootRiskBinding binding, CampaignEvidence failure)
        {
            if (!State.HasPosition || State.GroupSponsorActive) return;
            PolicyDecision decision = new() { Action = PolicyAction.Flatten, Policy = "root_risk",
                ReasonCode = "root_owner_failed", Priority = 1000, Quantity = State.SimulatedPositionQuantity,
                RootBinding = binding, RiskAnchor = binding.Range(TickSize),
                RiskAnchorEvidenceId = binding.Owner.Key.ToString(), EvidenceId = failure.EventId };
            PendingRiskExit ??= (decision, failure);
        }

        private void LatchTrackingLoss(DateTimeOffset now, string reason)
        {
            State.RevokeExecution();
            if (!State.HasPosition) return;
            var evidence = new CampaignEvidence { EventId = reason + ":" + State.ExecutionAttemptCount,
                Timestamp = now, Kind = EvidenceKind.Timer, Source = EvidenceSource.Unknown };
            // Infrastructure loss is an exit reason, never fabricated LL failure evidence.
            PendingRiskExit ??= (new PolicyDecision { Action = PolicyAction.Flatten, Policy = "risk_recovery",
                ReasonCode = reason, Priority = 1000, Quantity = State.SimulatedPositionQuantity,
                RootBinding = State.RootBinding, EvidenceId = evidence.EventId }, evidence);
        }

        private void RefreshRootRisk(DateTimeOffset now)
        {
            RootRiskRecoveryReason = null;
            foreach (CampaignOrder order in _orders.Values.Where(o => o.Decision.Action == PolicyAction.AllowProbe && !o.Terminal))
            {
                if (order.Decision.EntrySponsor != null)
                {
                    RefreshPendingEntrySponsor(order, now);
                    continue;
                }
                RootRiskBinding binding = order.Decision.RootBinding;
                RootHealth health = Roots.Health(binding, now);
                if (health == RootHealth.Failed)
                    MarkRootFailure(order, OwnerFailure(binding, Roots.Find(binding.Owner.Key).FailedAt.Value));
                else if (Roots.TrackingLost(binding))
                {
                    order.TrackingLostBeforeFill = true;
                    order.CancelReason ??= "root_owner_tracking_lost";
                    LatchTrackingLoss(now, "root_owner_tracking_lost");
                }
                else if (health == RootHealth.Unknown)
                    order.CancelReason ??= "root_owner_health_unknown";
            }
            if (State.HasPosition && State.GroupSponsorActive)
            {
                if (Sponsors.ActiveHealth == GroupHealth.Unknown)
                {
                    bool lost = Sponsors.Active.Members.Any(m => Roots.TrackingLost(m.Key, Plan.Side, m.Coverage));
                    RootRiskRecoveryReason = lost ? "sponsor_tracking_lost" : "sponsor_health_unknown";
                    if (lost) LatchTrackingLoss(now, RootRiskRecoveryReason);
                }
            }
            else if (State.HasPosition && State.RootBinding != null)
            {
                RootHealth active = Roots.Health(State.RootBinding, now);
                if (active == RootHealth.Failed)
                    LatchRootExit(State.RootBinding, OwnerFailure(State.RootBinding, Roots.Find(State.RootBinding.Owner.Key).FailedAt.Value));
                else if (active == RootHealth.Unknown)
                {
                    bool lost = Roots.TrackingLost(State.RootBinding);
                    RootRiskRecoveryReason = lost ? "root_owner_tracking_lost" : "root_owner_health_unknown";
                    if (lost) LatchTrackingLoss(now, RootRiskRecoveryReason);
                }
            }
            if (_lastRiskHealthReason != RootRiskRecoveryReason)
            {
                _rootAudit.Enqueue(new(now, RootRiskRecoveryReason ?? "risk_owner_health_restored", null, State.RootBinding, null));
                _lastRiskHealthReason = RootRiskRecoveryReason;
            }
        }

        public void ConfirmFlat(DateTimeOffset now)
        {
            if (!_attemptOpen || HasUnresolvedOrder || State.HasPosition) return;
            Observer.EndFlatAttempt(now, "confirmed_flat_attempt_end");
            Sponsors = null;
            Reservations = null;
            _awaitingRootObservation = null;
            PendingRiskExit = null;
            RootRiskRecoveryReason = null;
            State.GroupSponsorActive = false;
            RootEntryDistanceTicks = null;
            _attemptOpen = false;
        }

        public void RequireRecovery(string reason)
        {
            RecoveryReason = reason;
            State.RevokeExecution();
        }

        public CampaignOrder Reserve(PolicyDecision decision, CampaignEvidence evidence,
            ScaleReservationSnapshot scale, DateTimeOffset now, ContinuationEntryContext entryContext = null)
        {
            if (HasUnresolvedOrder || RecoveryReason != null || RootRiskRecoveryReason != null || !State.ExecutionAuthorized)
                throw new InvalidOperationException("New risk is not admissible.");
            if (decision.EntryOpportunity != null)
            {
                if (decision.Action != PolicyAction.AllowProbe || entryContext == null
                    || decision.Quantity != Plan.Sizing.ProbeQuantity
                    || decision.EvidenceId != evidence.EventId || entryContext.At != now)
                    throw new InvalidOperationException("Invalid continuation entry reservation.");
                string error = RevalidateContinuation(decision, entryContext);
                if (error != null) throw new InvalidOperationException(error);
            }
            else if (decision.Action == PolicyAction.AllowProbe)
            {
                if (Plan.SchemaVersion == 2 && (evidence.Price == null
                    || !Plan.WaypointsByRole(WaypointRole.TrapProbe).Any(w => w.Range.Contains(evidence.Price.Value))))
                    throw new InvalidOperationException("Ordinary probe requires price inside the probe range.");
                if (!Observer.FreshAt(now)) throw new InvalidOperationException("Root observation is recovering.");
                string error = Roots.Revalidate(decision.RootBinding, now, evidence.Price ?? double.NaN,
                    TickSize, Plan.Risk.MaxRootEntryDistanceTicks);
                if (error != null || decision.RootBinding.TriggerEventId != evidence.EventId
                    || decision.RootBinding.TriggerKey != new ClaimKey(evidence.Source, evidence.EvidenceEpoch, evidence.RailId)
                    || decision.RootBinding.Owner.Side != Plan.Side || evidence.Timestamp <= AuthorizedAt
                    || decision.RiskAnchor?.Lower != decision.RootBinding.Range(TickSize).Lower
                    || decision.RiskAnchor?.Upper != decision.RootBinding.Range(TickSize).Upper)
                    throw new InvalidOperationException(error ?? "Root binding does not belong to this entry.");
                if (_reservedRootTriggers.Contains((evidence.EvidenceEpoch, evidence.RailId, evidence.Kind, evidence.Timestamp)))
                    throw new InvalidOperationException("Root trigger already reserved; fresh evidence required.");
            }
            int quantity = scale?.RequestedQuantity ?? decision.Quantity ?? Plan.Sizing.ProbeQuantity;
            if (decision.Action is not (PolicyAction.AllowProbe or PolicyAction.AllowAdd)
                || quantity <= 0 || quantity > Plan.Sizing.MaxPositionQuantity - State.SimulatedPositionQuantity
                || (decision.Action == PolicyAction.AllowProbe && (State.HasPosition || !Plan.IsActiveAt(now) || !State.CanAttemptEntry(Plan)))
                || (decision.Action == PolicyAction.AllowAdd && (scale == null || Reservations?.Outstanding?.Id != scale.Id)))
                throw new InvalidOperationException("Invalid entry or episode reservation.");
            var order = new CampaignOrder(Guid.NewGuid().ToString("N"), decision, evidence,
                scale?.Id, quantity, State.SimulatedPositionQuantity, State.SimulatedAveragePrice ?? 0, now);
            _orders.Add(order.Id, order);
            if (decision.EntryOpportunity != null)
                Observer.MarkReserved(decision.EntryOpportunity, now);
            else if (decision.Action == PolicyAction.AllowProbe)
                _reservedRootTriggers.Add((evidence.EvidenceEpoch, evidence.RailId, evidence.Kind, evidence.Timestamp));
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
            if (order.Decision.EntrySponsor != null)
                RefreshPendingEntrySponsor(order, now);
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
                    RootBinding = order.Decision.RootBinding,
                    EvidenceId = order.Evidence.EventId,
                }, Plan, true, now, simulatedFillPrice: average);
                if (order.Decision.Action == PolicyAction.AllowProbe)
                {
                    TickInterval root = Ticks(State.RootRiskAnchor ?? Plan.Arena);
                    Sponsors = new(Plan.Side, root);
                    if (order.Decision.EntrySponsor != null)
                    {
                        Observer.MarkConsumed(order.Decision.EntryOpportunity, now);
                        Sponsors.ActivateInitial(order.Decision.EntrySponsor);
                        State.GroupSponsorActive = true;
                    }
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
                if (order.Decision.Action == PolicyAction.AllowProbe)
                    RootEntryDistanceTicks = order.Decision.EntrySponsor != null
                        ? EntrySponsorDistance(order.Decision.EntrySponsor, average.Value / TickSize)
                        : order.Decision.RootBinding.EntryDistanceTicks(average.Value, TickSize);
                // Only new fills change exposure; repeated snapshots cannot undo an intervening exit.
                State.ReconcileFill(positionBefore + added, (valueBefore + addedValue) / (positionBefore + added));
                if (order.FailureBeforeFill != null)
                {
                    if (order.Decision.EntrySponsor != null) LatchEntrySponsorExit(order, now);
                    else LatchRootExit(order.Decision.RootBinding, order.FailureBeforeFill);
                }
                if (order.TrackingLostBeforeFill)
                    LatchTrackingLoss(now, "root_owner_tracking_lost");
            }
            order.Filled = filled;
            order.FillAverage = average;
            order.Terminal |= terminal || filled == order.Quantity;
            if (order.Terminal && filled == 0 && order.Decision.EntryOpportunity != null)
                Observer.Miss(order.Decision.EntryOpportunity, now, "entry_zero_fill_no_automatic_retry");
            RefreshRiskHealth(now);
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
            ClaimKey? key = order.Decision.RootBinding?.Owner.Key;
            Observer.BeginAttempt(State.ExecutionAttemptCount, Sponsors.RootAnchor, now, priceTicks, key, carry);
            Reservations = new(Observer, Sponsors, Roots);
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
        public bool TrackingLostBeforeFill { get; set; }
        public string CancelReason { get; set; }
        public BrokerFillLedger BrokerFills { get; }
        public CampaignOrder(string id, PolicyDecision decision, CampaignEvidence evidence, string scaleId,
            int quantity, int before, double average, DateTimeOffset at)
        {
            Id = id; Decision = decision; Evidence = evidence; ScaleReservationId = scaleId;
            Quantity = quantity; PositionBefore = before; AverageBefore = average; SubmittedAt = at;
            BrokerFills = new(quantity);
        }
    }

    internal sealed record RootRiskAudit(DateTimeOffset At, string Reason, string EvidenceId,
        RootRiskBinding Binding, double? EntryDistanceTicks);
}
