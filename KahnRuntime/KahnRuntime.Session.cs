using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using KahnRuntime.Scaling;

namespace KahnRuntime
{
    public sealed partial class KahnRuntime
    {
        private CampaignSession _session;
        private string _runtimeInstanceId = Guid.NewGuid().ToString("N");
        private string _llEpoch = Guid.NewGuid().ToString("N");
        private readonly List<CampaignEvidence> _sampleEvidence = new();
        private ScaleReservationSnapshot _selectedScale;
        private bool _awaitingFillPosition;
        private bool _newRiskReady;
        private string _positionReconciliationReason;
        private int? _pendingCloseQuantity;
        private string _managedPositionId;
        private RuntimeControlCommand _latchedFlat;
        private readonly HashSet<string> _flatCloseSubmitted = new(StringComparer.Ordinal);

        private bool ContinueFlatControl(DateTimeOffset now)
        {
            if (_latchedFlat == null) return false;
            bool cancelAccepted = _gateway.CancelRuntimeOrders("order_cancel_flat_pending");
            RuntimePosition[] positions = _runTradingEnabled ? BoundLivePositions() : ShadowPositions();
            if (positions.Length == 0 && _session?.HasUnresolvedOrder != true && BoundWorkingOrders().Count == 0)
                _awaitingFillPosition = false;
            if (_awaitingFillPosition && positions.Length == 1 && _state != null
                && positions[0].Direction == _plan.Side
                && positions[0].Quantity == _state.SimulatedPositionQuantity
                && NearlyEqual(positions[0].AveragePrice, _state.SimulatedAveragePrice ?? 0))
                _awaitingFillPosition = false;
            foreach (var position in positions)
            {
                string key = position.PositionId + ":" + position.Quantity.ToString("R", CultureInfo.InvariantCulture);
                if (_flatCloseSubmitted.Contains(key)) continue;
                var decision = ControlDecision(_latchedFlat, PolicyAction.Flatten, "operator_flat_late_fill", (int)Math.Ceiling(position.Quantity));
                GatewayResult result = _gateway.Execute(decision, PlanForControl(_latchedFlat, position), position, SnapshotMarket(now.UtcDateTime));
                if (!result.Accepted)
                {
                    _lastControlStatus = "rejected_execution: " + result.Message;
                    return true;
                }
                _flatCloseSubmitted.Add(key);
                RetireCurrentCampaign(_latchedFlat, now, "operator_flat_late_fill");
            }
            bool flat = cancelAccepted && positions.Length == 0 && !_awaitingFillPosition
                && _session?.HasUnresolvedOrder != true
                && BoundWorkingOrders().Count == 0;
            _lastControlStatus = flat ? "completed_flat"
                : cancelAccepted ? "pending_flat_reconciliation" : "pending_flat_order_cancellation";
            if (flat)
            {
                _awaitingFillPosition = false;
                _pendingCloseQuantity = null;
                _managedPositionId = null;
                RetireCurrentCampaign(_latchedFlat, now, "operator_flat_confirmed");
                _latchedFlat = null;
                _flatCloseSubmitted.Clear();
            }
            return true;
        }

        private void ProcessEvidenceBatch(IReadOnlyList<CampaignEvidence> evidence, DateTimeOffset now)
        {
            if (_plan == null || _state == null || _state.IsRetired
                || (!_plan.ShouldEvaluateEvidenceAt(now, _state) && !_session.HasUnresolvedOrder)) return;
            var choices = _session.PolicyCandidates(evidence.Where(e => EvidenceFreshEnough(e, now)), now).ToList();

            ExecutableMarket market = SnapshotMarket(now.UtcDateTime);
            if (_session != null)
            {
                if (_newRiskReady && CurrentPosition().IsFlat && !_pendingCloseQuantity.HasValue)
                    _session.ConfirmFlat(now);
                if (market.IsValid)
                    _session.Observer.ObservePrice(now, ManagementTicks(market));
                _session.Sponsors?.Observe(_session.Observer);
                ScaleOpportunity opportunity = _session.Observer.Opportunity;
                if (opportunity != null && _session.Reservations != null)
                {
                    bool veto = choices.Any(x => x.Decision.Priority > 525
                        || x.Decision.Action is PolicyAction.SuppressAdd or PolicyAction.Cooldown
                            or PolicyAction.Flatten or PolicyAction.Retire or PolicyAction.Reduce or PolicyAction.PassiveHarvest
                            or PolicyAction.TightenRisk);
                    ScaleAdmissionContext admission = ScaleContext(now, market, !veto);
                    if (_session.Reservations.TryReserve(opportunity, admission, out var reserved, out string reason))
                    {
                        _selectedScale = reserved;
                        var trigger = new CampaignEvidence { EventId = reserved.Id, Timestamp = now,
                            Source = EvidenceSource.LevelLedger, Kind = EvidenceKind.RailHeld,
                            Price = market.Executable(_plan.Side) };
                        choices.Add((new PolicyDecision { Action = PolicyAction.AllowAdd, Policy = "repair_episode",
                            ReasonCode = "repaired_continuation", Quantity = reserved.RequestedQuantity,
                            Priority = 525, EvidenceId = reserved.Id }, trigger));
                    }
                    else _decisions.Write("scale_missed", ("episode_id", opportunity.EpisodeId), ("reason", reason));
                }
                DrainRepairAudit();
            }
            var selected = choices.Where(x => _newRiskReady
                    || x.Decision.Action is not (PolicyAction.AllowProbe or PolicyAction.ArmProbe or PolicyAction.AllowAdd))
                .OrderByDescending(x => x.Decision.Priority > 0
                ? x.Decision.Priority : DecisionResolver.PriorityFor(x.Decision.Action)).FirstOrDefault();
            if (selected.Decision != null) ProcessEvidence(selected.Evidence, now, selected.Decision);
            _selectedScale = null;
        }

        private double ManagementTicks(ExecutableMarket market)
            => (_plan.Side == CampaignSide.Long ? market.Bid : market.Ask) / _tickSize;

        private ScaleAdmissionContext ScaleContext(DateTimeOffset now, ExecutableMarket market, bool policyAllows)
        {
            RuntimePosition position = CurrentPosition();
            double price = market.IsValid ? market.Executable(_plan.Side) : double.NaN;
            bool target = _state.PassiveHarvestActive || _state.Phase == CampaignPhase.TargetZone;
            PriceRange range = _plan.Objective?.PassiveHarvest?.IsUsable == true
                ? _plan.Objective.PassiveHarvest.Range : _plan.Objective?.TargetRange;
            if (range != null && double.IsFinite(price))
            {
                double buffer = (_plan.Objective?.TargetProximityTicks ?? 0) * _tickSize;
                target |= _plan.Side == CampaignSide.Long ? price >= range.Lower - buffer : price <= range.Upper + buffer;
            }
            bool protection = !_state.OperatorProtectionPrice.HasValue
                || (market.IsValid && !StopTouched(_plan.Side, _state.OperatorProtectionPrice.Value, market));
            if (_runTradingEnabled && _state.BreakevenBackstopActive)
            {
                var stops = _gateway.RuntimeProtectionOrders();
                protection &= stops.Count == 1 && NearlyEqual(stops[0].RemainingQuantity, position.Quantity)
                    && _state.BreakevenBackstopPrice.HasValue
                    && NearlyEqual(stops[0].TriggerPrice, _state.BreakevenBackstopPrice.Value);
            }
            bool ordersClear = _newRiskReady && !_session.HasUnresolvedOrder && !_awaitingFillPosition && !_pendingCloseQuantity.HasValue
                && (!_runTradingEnabled || BoundWorkingOrders().All(o =>
                    _gateway.RuntimeProtectionOrders().Any(p => p.Id == o.Id)));
            return new(now, new DateTimeOffset(market.QuoteUtc, TimeSpan.Zero),
                TimeSpan.FromMilliseconds(Math.Max(250, QuoteFreshnessMs)), TimeSpan.FromSeconds(Math.Max(1, EvidenceMaxAgeSec)),
                market.Bid / _tickSize, market.Ask / _tickSize, position.AveragePrice / _tickSize,
                (int)Math.Round(position.Quantity), _plan.Sizing.AddQuantity, _plan.Sizing.MaxPositionQuantity,
                Math.Max(1, InstanceMaxQuantity), _state.ExecutionAuthorized && _session.RecoveryReason == null,
                _state.HasPosition && position.Direction == _plan.Side, ordersClear,
                policyAllows && protection && _evidenceWarmupComplete && !_state.ExecutionPaused
                    && (_session.Sponsors?.Active == null || _session.Sponsors.ActiveHealth == GroupHealth.Live)
                    && !_state.AddsSuppressed(now) && _plan.Policies.PressEnabled
                    && _plan.Sizing.ScaleMode == CampaignScaleMode.EvidenceScaled
                    && _plan.Arena.Contains(price), target);
        }

        private GatewayResult ExecuteNewRisk(PolicyDecision decision, CampaignEvidence evidence, DateTimeOffset now)
        {
            if (!_newRiskReady || _session == null || !_state.ExecutionAuthorized || _session.HasUnresolvedOrder
                || _session.RecoveryReason != null || _awaitingFillPosition || _pendingCloseQuantity.HasValue)
                return new GatewayResult { Message = "new risk is not authorized or reconciled" };
            ExecutableMarket market = SnapshotMarket(DateTime.UtcNow);
            RuntimePosition position = CurrentPosition();
            if (decision.Action == PolicyAction.AllowProbe && (!position.IsFlat || !_plan.IsActiveAt(now)))
                return new GatewayResult { Message = "probe requires flat position and unexpired entry window" };
            if (decision.Action == PolicyAction.AllowProbe && (_runTradingEnabled && BoundWorkingOrders().Count > 0
                || !market.IsValid || (_plan.FindWaypoint(decision.WaypointId) is { RequirePriceInside: true } probe
                    && !probe.Range.Contains(market.Executable(_plan.Side)))))
                return new GatewayResult { Message = "probe quote/location or outstanding orders changed before submission" };
            ScaleReservationSnapshot scale = decision.Action == PolicyAction.AllowAdd ? _selectedScale : null;
            if (decision.Action == PolicyAction.AllowAdd)
            {
                if (scale == null) return new GatewayResult { Message = "missing episode reservation" };
                string error = _session.Reservations.RevalidateBeforeSubmit(scale.Id,
                    ScaleContext(DateTimeOffset.UtcNow, market, true));
                if (error != null)
                {
                    _session.Reservations.Report(scale.Id, 0, null, true, DateTimeOffset.UtcNow, ManagementTicks(market));
                    return new GatewayResult { Message = error };
                }
            }
            if (!_runTradingEnabled && !ShadowFillSimulation)
            {
                if (scale != null) _session.Reservations.Report(scale.Id, 0, null, true, now, ManagementTicks(market));
                return new GatewayResult { Message = "shadow fill simulation disabled" };
            }
            CampaignOrder order = _session.Reserve(decision, evidence, scale, now);
            GatewayResult result = _gateway.Execute(decision, _plan, position, market);
            _session.Submitted(order, result.OrderId, result.Accepted, result.SubmissionUncertain);
            if (result.Shadow && result.Accepted)
                _session.Report(order, order.Quantity, result.SyntheticFillPrice, true,
                    DateTimeOffset.UtcNow, ManagementTicks(market));
            else if (!result.Accepted && !result.SubmissionUncertain)
                _session.Report(order, 0, null, true, DateTimeOffset.UtcNow, ManagementTicks(market));
            _decisions.Write("campaign_order_reserved", ("reservation_id", order.Id),
                ("episode_reservation_id", order.ScaleReservationId), ("order_id", result.OrderId),
                ("accepted", result.Accepted), ("filled_quantity", order.Filled), ("terminal", order.Terminal));
            DrainRepairAudit();
            return result;
        }

        private void ReportCampaignOrder(BrokerEvent ev)
        {
            CampaignOrder order = _session?.FindBrokerOrder(ev.OrderId);
            if (order == null) return;
            try
            {
                int prior = order.Filled;
                double? priorAverage = order.FillAverage;
                if (_session.ReportBrokerEvent(ev, DateTimeOffset.UtcNow,
                    ManagementTicks(SnapshotMarket(DateTime.UtcNow))) == null) return;
                if (order.Filled != prior || order.FillAverage != priorAverage) _awaitingFillPosition = true;
                if (order.Filled > 0 && order.Decision.Action == PolicyAction.AllowProbe)
                    _managedPositionId ??= order.PositionId;
                _decisions.Write("campaign_order_report", ("reservation_id", order.Id), ("order_id", order.BrokerOrderId),
                    ("source_event", ev.EventType), ("trade_id", ev.TradeId),
                    ("filled_quantity", order.Filled), ("fill_average", order.FillAverage), ("terminal", order.Terminal),
                    ("active_group", _session.Sponsors?.Active), ("pending_group", _session.Sponsors?.Pending));
            }
            catch (Exception ex)
            {
                _session.RequireRecovery("fill_reconciliation: " + ex.Message);
                LogOperator("ERR", _session.RecoveryReason, error: true);
            }
            DrainRepairAudit();
        }

        private bool CanManageKnownPosition()
        {
            if (!_runTradingEnabled) return true;
            RuntimePosition live = LivePosition(out bool ambiguous);
            return !ambiguous && !live.IsFlat && _state?.HasPosition == true && _plan != null
                && _managedPositionId != null && live.PositionId == _managedPositionId
                && live.Direction == _plan.Side && double.IsFinite(live.Quantity)
                && live.Quantity == Math.Round(live.Quantity) && live.Quantity <= _state.SimulatedPositionQuantity;
        }

        private void DrainRepairAudit()
        {
            if (_session == null) return;
            foreach (RepairAudit audit in _session.Observer.DrainAudit())
                _decisions.Write("repair_episode", ("campaign_id", _plan.Id), ("epoch", _session.Observer.Epoch),
                    ("sample", _evidenceEpochSampleCount), ("audit", audit));
        }

        private bool HandleScopedControl(RuntimeControlCommand command, DateTimeOffset now)
        {
            string error = _session == null ? "rejected_no_watched_campaign" : _session.ValidateControl(command, now);
            if (_pendingCloseQuantity.HasValue || _latchedFlat != null) error = "rejected_unresolved_close";
            if (error == null && command.Action == RuntimeControlAction.GoLive)
                error = _session.GoLive(command, now);
            else if (error == null)
            {
                bool ambiguous = false;
                RuntimePosition position = _runTradingEnabled ? LivePosition(out ambiguous) : CurrentPosition();
                ExecutableMarket market = SnapshotMarket(now.UtcDateTime);
                if (!_state.HasPosition || position.IsFlat || position.Direction != _plan.Side || _awaitingFillPosition
                    || ambiguous || !double.IsFinite(position.AveragePrice) || position.AveragePrice <= 0
                    || position.Quantity != _state.SimulatedPositionQuantity
                    || (_managedPositionId != null && position.PositionId != _managedPositionId))
                    error = "rejected_no_reconciled_managed_position";
                else if (!market.IsValid) error = "rejected_stale_quote";
                else
                {
                    double trigger = ProtectedBreakevenPrice(position);
                    if (StopTouched(_plan.Side, trigger, market)) error = "rejected_offside_or_invalid_stop";
                    else
                    {
                        var decision = BreakevenDecision(PolicyAction.EnsureBreakeven, "operator_be", position, trigger, now);
                        GatewayResult result = ExecuteDecision(decision, now);
                        if (!result.Accepted) error = "rejected_protection: " + result.Message;
                        else
                        {
                            _state.SetOperatorProtection(trigger);
                            _state.ArmBreakevenBackstop(trigger, now, result.OrderId);
                            error = "accepted";
                        }
                    }
                }
            }
            _lastControlStatus = error;
            _decisions.Write("control_acknowledged", ("control_id", command.Id), ("status", error),
                ("campaign_id", _plan?.Id), ("campaign_digest", _plan?.Digest), ("runtime_instance_id", _runtimeInstanceId),
                ("attempt", _state?.ExecutionAttemptCount));
            return true;
        }

        private double ProtectedBreakevenPrice(RuntimePosition position)
        {
            double trigger = _session?.ProtectionPrice(position.AveragePrice) ?? BreakevenTriggerPrice(_plan, position);
            if (_runTradingEnabled)
                foreach (var stop in _gateway.RuntimeProtectionOrders())
                    if (double.IsFinite(stop.TriggerPrice) && stop.TriggerPrice > 0)
                        trigger = _plan.Side == CampaignSide.Long ? Math.Max(trigger, stop.TriggerPrice) : Math.Min(trigger, stop.TriggerPrice);
            return trigger;
        }
    }
}
