using System;
using System.Collections.Generic;

namespace KahnRuntime
{
    internal sealed partial class BrokerEvent
    {
        public bool Terminal { get; init; }
        public string EventType { get; init; }
        public string OrderId { get; init; }
        public string TradeId { get; init; }
        public string PositionId { get; init; }
        public string Side { get; init; }
        public string Status { get; init; }
        public double Quantity { get; init; }
        public double FilledQuantity { get; init; }
        public double RemainingQuantity { get; init; }
        public double Price { get; init; }
        public double AverageFillPrice { get; init; }
        public DateTime BrokerUtc { get; init; }
        public string Comment { get; init; }
        public string GroupId { get; init; }
    }

    internal readonly record struct BrokerFillSnapshot(int Quantity, double? Average, bool Terminal);

    // Order snapshots and identified executions describe overlapping fills. Never sum the two streams.
    internal sealed class BrokerFillLedger
    {
        private readonly int _requested;
        private readonly Dictionary<string, (int Quantity, double Price)> _executions = new(StringComparer.Ordinal);
        private int _tradeQuantity;
        private double _tradeValue;
        private int _orderQuantity;
        private double? _orderAverage;
        private bool _terminal;

        public BrokerFillLedger(int requested) => _requested = requested;

        public BrokerFillSnapshot Observe(BrokerEvent report, CampaignSide side)
        {
            bool trade = report.EventType == "trade_fill";
            string expected = side == CampaignSide.Long ? "Long" : "Short";
            string brokerSide = side == CampaignSide.Long ? "Buy" : "Sell";
            if (report.Side != expected && report.Side != brokerSide)
                throw new InvalidOperationException("Broker fill side does not match the reserved order.");
            int quantity = ValidQuantity(trade ? report.Quantity : report.FilledQuantity);
            double? average = quantity > 0 ? trade ? report.Price : report.AverageFillPrice : null;
            if (quantity > _requested || (quantity > 0 && (!double.IsFinite(average.Value) || average <= 0)))
                throw new InvalidOperationException("Broker fill quantity or average is invalid.");

            int trades = _tradeQuantity, orders = _orderQuantity;
            double value = _tradeValue;
            double? orderAverage = _orderAverage;
            bool newTrade = false;
            if (trade)
            {
                if (quantity == 0 || string.IsNullOrWhiteSpace(report.TradeId))
                    throw new InvalidOperationException("Execution requires a broker trade identity and positive quantity.");
                if (_executions.TryGetValue(report.TradeId, out var prior))
                {
                    if (prior.Quantity != quantity || prior.Price != average)
                        throw new InvalidOperationException("Broker trade identity was reused with different fill facts.");
                }
                else
                {
                    newTrade = true;
                    trades += quantity;
                    value += quantity * average.Value;
                }
            }
            else if (quantity >= orders)
            {
                if (quantity == orders && quantity > 0 && !SameAverage(average.Value, orderAverage.Value))
                    throw new InvalidOperationException("Cumulative fill average changed without a quantity change.");
                orders = quantity;
                orderAverage = average;
            }
            if (trades > _requested)
                throw new InvalidOperationException("Identified executions exceed the reserved order quantity.");
            if (trades > 0 && trades == orders && !SameAverage(value / trades, orderAverage.Value))
                throw new InvalidOperationException("Execution and cumulative order fill averages disagree.");

            if (newTrade) _executions.Add(report.TradeId, (quantity, average.Value));
            _tradeQuantity = trades;
            _tradeValue = value;
            _orderQuantity = orders;
            _orderAverage = orderAverage;
            int filled = Math.Max(trades, orders);
            _terminal |= (!trade && report.Terminal) || filled == _requested;
            return new(filled, trades > orders ? value / trades : orderAverage, _terminal);
        }

        private static int ValidQuantity(double value)
        {
            if (!double.IsFinite(value) || value < 0 || value > int.MaxValue || value != Math.Round(value))
                throw new InvalidOperationException("Broker quantity must be a nonnegative integer.");
            return (int)value;
        }

        private static bool SameAverage(double left, double right) => Math.Abs(left - right) <= 0.000001;
    }
}
