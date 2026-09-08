using System;
using System.Collections.Generic;

namespace KahnRuntime.Scaling
{
    internal sealed record ScaleAdmissionContext(
        DateTimeOffset At, DateTimeOffset QuoteAt, TimeSpan MaxQuoteAge, TimeSpan MaxEvidenceAge,
        double BidTicks, double AskTicks, double PositionAverageTicks,
        int PositionQuantity, int AddQuantity, int PlanMaxQuantity, int InstanceMaxQuantity,
        bool ExecutionAuthorized, bool PositionIsManaged, bool OutstandingOrdersClear,
        bool PolicyAllowsAdd, bool AtTarget);

    internal enum ScaleOrderState { Reserved, Submitted, Uncertain, PartiallyFilled, Terminal }

    internal sealed record ScaleReservationSnapshot(
        string Id, ScaleOpportunity Opportunity, ProofGroup Proof,
        int RequestedQuantity, int PositionBefore, double AverageBefore,
        ScaleOrderState State, int FilledQuantity, double? FillAverageTicks,
        string BrokerOrderId, string Detail)
    {
        public int RemainingQuantity => State == ScaleOrderState.Terminal ? 0 : RequestedQuantity - FilledQuantity;
        public int ObservedPositionQuantity => PositionBefore + FilledQuantity;
        public double ObservedAverageTicks => FilledQuantity == 0 ? AverageBefore
            : (AverageBefore * PositionBefore + FillAverageTicks.Value * FilledQuantity) / ObservedPositionQuantity;
    }

    // Pure order accounting. The gateway must report cumulative actual fills;
    // neither accepted submission nor an elapsed settle timer is a fill report.
    internal sealed class ScaleOrderReservations
    {
        private readonly RepairEpisodeObserver _observer;
        private readonly GroupSponsorState _sponsors;
        private readonly Dictionary<string, ScaleReservationSnapshot> _orders = new(StringComparer.Ordinal);
        private long _number;
        public ScaleReservationSnapshot Outstanding { get; private set; }
        public bool HasUnresolvedOrder => Outstanding != null;

        public ScaleOrderReservations(RepairEpisodeObserver observer, GroupSponsorState sponsors)
        {
            _observer = observer ?? throw new ArgumentNullException(nameof(observer));
            _sponsors = sponsors ?? throw new ArgumentNullException(nameof(sponsors));
        }

        public bool TryReserve(ScaleOpportunity opportunity, ScaleAdmissionContext context,
            out ScaleReservationSnapshot reservation, out string reason)
        {
            reservation = null;
            reason = Gate(opportunity, context);
            if (reason != null)
            {
                // Rechecking the already reserved episode is not a new veto of its order.
                if (Outstanding?.Opportunity != opportunity)
                    _observer.Miss(opportunity, context.At, reason);
                return false;
            }
            int quantity = Math.Min(context.AddQuantity,
                Math.Min(context.PlanMaxQuantity, context.InstanceMaxQuantity) - context.PositionQuantity);
            double executable = _observer.Side == CampaignSide.Long ? context.BidTicks : context.AskTicks;
            ProofGroup proof = _observer.CurrentProof(opportunity.Proof, executable);
            string id = $"scale:{opportunity.Attempt}:{opportunity.Generation}:{++_number}";
            reservation = new(id, opportunity, proof, quantity,
                context.PositionQuantity, context.PositionAverageTicks, ScaleOrderState.Reserved,
                0, null, null, "reserved_before_submit");
            _orders.Add(id, reservation);
            Outstanding = reservation;
            _observer.MarkReserved(opportunity, context.At);
            return true;
        }

        public string RevalidateBeforeSubmit(string reservationId, ScaleAdmissionContext context)
        {
            ScaleReservationSnapshot order = Required(reservationId);
            if (order.State != ScaleOrderState.Reserved || Outstanding?.Id != reservationId)
                return "reservation_already_submitted_or_terminal";
            if (context.PositionQuantity != order.PositionBefore || context.PositionAverageTicks != order.AverageBefore)
                return "position_changed_during_reservation";
            if ((long)context.PositionQuantity + order.RequestedQuantity
                > Math.Min(context.PlanMaxQuantity, context.InstanceMaxQuantity))
                return "reserved_capacity_no_longer_available";
            return Gate(order.Opportunity, context, ownReservation: true);
        }

        public void AcknowledgeSubmission(string reservationId, string brokerOrderId)
        {
            ScaleReservationSnapshot order = Required(reservationId);
            if (string.IsNullOrWhiteSpace(brokerOrderId))
                throw new ArgumentException("An acknowledgement needs the broker order identity.", nameof(brokerOrderId));
            if (order.BrokerOrderId != null && order.BrokerOrderId != brokerOrderId)
                throw new InvalidOperationException("A reservation cannot bind a second broker order.");
            Save(order with
            {
                BrokerOrderId = brokerOrderId,
                State = order.State == ScaleOrderState.Terminal ? order.State
                    : order.FilledQuantity > 0 ? ScaleOrderState.PartiallyFilled : ScaleOrderState.Submitted,
                Detail = "submission_is_not_fill",
            });
        }

        public void MarkUncertain(string reservationId, string reason)
        {
            var order = Required(reservationId);
            if (order.State != ScaleOrderState.Terminal)
                Save(order with { State = ScaleOrderState.Uncertain, Detail = reason });
        }

        public bool Report(string reservationId, int cumulativeFilledQuantity,
            double? cumulativeFillAverageTicks, bool terminal, DateTimeOffset at,
            double currentExecutableTicks)
        {
            ScaleReservationSnapshot order = Required(reservationId);
            if (at < order.Opportunity.At || cumulativeFilledQuantity < order.FilledQuantity || cumulativeFilledQuantity > order.RequestedQuantity
                || (cumulativeFilledQuantity > 0 && (!cumulativeFillAverageTicks.HasValue
                    || !double.IsFinite(cumulativeFillAverageTicks.Value)))
                || (cumulativeFilledQuantity == 0 && cumulativeFillAverageTicks.HasValue))
                throw new ArgumentException("Invalid cumulative broker fill report.");
            if (order.State == ScaleOrderState.Terminal)
            {
                if (order.FilledQuantity != cumulativeFilledQuantity || order.FillAverageTicks != cumulativeFillAverageTicks)
                    throw new InvalidOperationException("A terminal report changed; operator reconciliation is required.");
                return false;
            }
            bool firstFill = order.FilledQuantity == 0 && cumulativeFilledQuantity > 0;
            ScaleReservationSnapshot updated = order with
            {
                FilledQuantity = cumulativeFilledQuantity,
                FillAverageTicks = cumulativeFillAverageTicks,
                State = terminal || cumulativeFilledQuantity == order.RequestedQuantity ? ScaleOrderState.Terminal
                    : cumulativeFilledQuantity > 0 ? ScaleOrderState.PartiallyFilled : order.State,
                Detail = firstFill ? "first_partial_fill_consumes_episode" : "cumulative_fill_reconciled",
            };
            if (firstFill)
            {
                if (!_observer.FreshAt(at) && !_observer.Suspended)
                    _observer.Suspend(at, "fill_report_observation_stale");
                _observer.MarkConsumed(order.Opportunity, at);
                _sponsors.FirstFill(order.Proof, _observer, currentExecutableTicks);
            }
            Save(updated);
            if (updated.State == ScaleOrderState.Terminal && cumulativeFilledQuantity == 0)
                _observer.Miss(order.Opportunity, at, "zero_fill_terminal_no_automatic_retry");
            return firstFill;
        }

        public ScaleReservationSnapshot Find(string id) => _orders.GetValueOrDefault(id);

        private string Gate(ScaleOpportunity opportunity, ScaleAdmissionContext context, bool ownReservation = false)
        {
            if (context == null)
                throw new ArgumentNullException(nameof(context));
            if (HasUnresolvedOrder && !ownReservation || !context.OutstandingOrdersClear)
                return "unresolved_order";
            if (!context.ExecutionAuthorized)
                return "watch";
            if (!context.PositionIsManaged || context.PositionQuantity <= 0)
                return "no_managed_position";
            if (!context.PolicyAllowsAdd || context.AtTarget)
                return "policy_veto";
            if (context.AddQuantity <= 0 || context.PlanMaxQuantity <= context.PositionQuantity
                || context.InstanceMaxQuantity <= context.PositionQuantity)
                return "capacity";
            if (context.At < context.QuoteAt || context.At < _observer.LastCompleteSampleAt
                || context.At < _observer.LastObservedAt || context.QuoteAt == default
                || context.MaxQuoteAge <= TimeSpan.Zero || context.MaxEvidenceAge <= TimeSpan.Zero
                || context.At - context.QuoteAt > context.MaxQuoteAge
                || context.At - _observer.LastCompleteSampleAt > context.MaxEvidenceAge
                || !double.IsFinite(context.BidTicks) || !double.IsFinite(context.AskTicks)
                || context.BidTicks >= context.AskTicks || !double.IsFinite(context.PositionAverageTicks))
                return "stale_or_invalid_market";
            double executable = _observer.Side == CampaignSide.Long ? context.BidTicks : context.AskTicks;
            if (_observer.Side == CampaignSide.Long ? executable <= context.PositionAverageTicks
                : executable >= context.PositionAverageTicks)
                return "not_favorable_to_average";
            return _observer.Revalidate(opportunity, executable);
        }

        private ScaleReservationSnapshot Required(string id)
            => _orders.TryGetValue(id, out var order) ? order
                : throw new ArgumentException("Unknown scale reservation.", nameof(id));

        private void Save(ScaleReservationSnapshot order)
        {
            _orders[order.Id] = order;
            if (Outstanding?.Id == order.Id)
                Outstanding = order.State == ScaleOrderState.Terminal ? null : order;
        }
    }
}
