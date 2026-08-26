using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Globalization;
using System.Linq;
using TradingPlatform.BusinessLayer;

namespace KahnRuntime
{
    internal sealed class ExecutableMarket
    {
        public DateTime TimeUtc { get; init; }
        public double Bid { get; init; }
        public double Ask { get; init; }
        public DateTime QuoteUtc { get; init; }

        public bool IsValid
            => double.IsFinite(Bid) && Bid > 0
                && double.IsFinite(Ask) && Ask > 0
                && Ask >= Bid;

        public double Executable(CampaignSide side)
            => side == CampaignSide.Long ? Ask : Bid;
    }

    internal sealed class RuntimePosition
    {
        public static readonly RuntimePosition Flat = new() { Quantity = 0 };

        public string PositionId { get; init; }
        public CampaignSide Direction { get; init; }
        public double Quantity { get; init; }
        public double AveragePrice { get; init; }
        public Position LivePosition { get; init; }

        public bool IsFlat => Quantity <= 0;
    }

    internal sealed class GatewayResult
    {
        public bool Accepted { get; init; }
        public bool Shadow { get; init; }
        public bool RequiresOperatorAction { get; init; }
        public string OrderId { get; init; }
        public string Message { get; init; }
        public double SyntheticFillPrice { get; init; } = double.NaN;
    }

    internal sealed class KahnOrderGateway
    {
        private const string SendingSource = "KahnRuntime";
        private const string TagPrefix = "KH:";

        private readonly Symbol _symbol;
        private readonly Account _account;
        private readonly ShadowDecisionLog _events;
        private readonly bool _tradingEnabled;
        private readonly int _instanceMaxQuantity;

        public KahnOrderGateway(
            Symbol symbol,
            Account account,
            ShadowDecisionLog events,
            bool tradingEnabled,
            int instanceMaxQuantity)
        {
            _symbol = symbol ?? throw new ArgumentNullException(nameof(symbol));
            if (tradingEnabled && account == null)
                throw new ArgumentNullException(nameof(account));
            _account = account;
            _events = events ?? throw new ArgumentNullException(nameof(events));
            _tradingEnabled = tradingEnabled;
            _instanceMaxQuantity = Math.Max(1, instanceMaxQuantity);
        }

        public GatewayResult Execute(PolicyDecision decision,
            CampaignPlan plan,
            RuntimePosition position,
            ExecutableMarket market)
        {
            if (decision == null)
                return Failure("decision is null");
            if (plan == null)
                return Failure("campaign plan is null");

            return decision.Action switch
            {
                PolicyAction.AllowProbe => PlaceMarket(decision, plan, position, market, "ENTRY"),
                PolicyAction.AllowAdd => PlaceMarket(decision, plan, position, market, "ADD"),
                PolicyAction.Reduce => ClosePosition(decision, plan, position, "REDUCE"),
                PolicyAction.Flatten => ClosePosition(decision, plan, position, "FLAT"),
                PolicyAction.Retire => ClosePosition(decision, plan, position, "RETIRE"),
                _ => Success(null, "no broker action required"),
            };
        }

        public IReadOnlyList<Order> RuntimeOrders()
            => Core.Instance.Orders.Where(IsRuntimeOrder).ToArray();

        public IReadOnlyList<Order> BoundWorkingOrders()
            => Core.Instance.Orders
                .Where(o => SameBoundPair(o.Symbol, o.Account) && IsWorkingOrder(o))
                .ToArray();

        public void CancelRuntimeOrdersOnStop()
            => CancelRuntimeOrders("order_cancel_on_stop");

        public void CancelRuntimeOrders(string eventType)
        {
            if (!_tradingEnabled)
                return;
            string cancelEvent = string.IsNullOrWhiteSpace(eventType)
                ? "order_cancel"
                : eventType;
            foreach (Order order in RuntimeOrders().Where(IsWorkingOrder))
            {
                try
                {
                    TradingOperationResult result = Core.Instance.CancelOrder(
                        (IOrder)order,
                        SendingSource);
                    _events.Write(cancelEvent,
                        ("order_id", order.Id),
                        ("accepted", IsSuccess(result)),
                        ("message", result.Message));
                }
                catch (Exception ex)
                {
                    _events.Write(cancelEvent + "_error",
                        ("order_id", order.Id),
                        ("message", ex.Message));
                }
            }
        }

        public bool IsRuntimeOrder(IOrder order)
            => order != null
                && SameBoundPair(order.Symbol, order.Account)
                && ((order.Comment?.StartsWith(TagPrefix, StringComparison.Ordinal) ?? false)
                    || (order.GroupId?.StartsWith(TagPrefix, StringComparison.Ordinal) ?? false));

        private GatewayResult PlaceMarket(PolicyDecision decision,
            CampaignPlan plan,
            RuntimePosition position,
            ExecutableMarket market,
            string role)
        {
            int requested = Math.Max(1, decision.Quantity
                ?? (decision.Action == PolicyAction.AllowProbe
                    ? plan.Sizing.ProbeQuantity
                    : plan.Sizing.AddQuantity));
            int current = position == null || position.IsFlat
                ? 0
                : (int)Math.Round(position.Quantity);
            int remaining = Math.Max(0, _instanceMaxQuantity - current);
            int quantity = Math.Min(requested, remaining);
            if (quantity <= 0)
                return Failure("instance max quantity reached");

            if (position != null
                && !position.IsFlat
                && position.Direction != plan.Side)
            {
                return Failure("bound position is opposite campaign side",
                    requiresOperatorAction: true);
            }

            if (market == null || !market.IsValid)
                return Failure("no fresh executable quote");

            double executable = market.Executable(plan.Side);
            if (!_tradingEnabled)
            {
                _events.Write("order_shadow_fill",
                    ("campaign_id", plan.Id),
                    ("decision_action", decision.Action.ToString()),
                    ("policy", decision.Policy),
                    ("reason_code", decision.ReasonCode),
                    ("role", role),
                    ("side", plan.Side.ToString()),
                    ("quantity", quantity),
                    ("submit_bid", market.Bid),
                    ("submit_ask", market.Ask),
                    ("fill_price", executable));
                return new GatewayResult
                {
                    Accepted = true,
                    Shadow = true,
                    OrderId = $"shadow-{decision.EvidenceId}",
                    SyntheticFillPrice = executable,
                    Message = "shadow fill",
                };
            }

            OrderType marketType = _symbol.GetAlowedOrderTypes(OrderTypeUsage.Order)?
                .FirstOrDefault(o => o.Behavior == OrderTypeBehavior.Market);
            if (marketType == null)
                return Failure("broker exposes no market order type",
                    requiresOperatorAction: true);

            string tag = BuildTag(plan.Id, role, decision.EvidenceId);
            var request = new PlaceOrderRequestParameters
            {
                Symbol = _symbol,
                Account = _account,
                Side = plan.Side == CampaignSide.Long ? Side.Buy : Side.Sell,
                Quantity = quantity,
                OrderTypeId = marketType.Id,
                TimeInForce = TimeInForce.Day,
                GroupId = tag,
                Comment = tag,
                SendingSource = SendingSource,
            };

            long before = Stopwatch.GetTimestamp();
            _events.Write("order_submit",
                ("campaign_id", plan.Id),
                ("decision_action", decision.Action.ToString()),
                ("policy", decision.Policy),
                ("reason_code", decision.ReasonCode),
                ("role", role),
                ("side", plan.Side.ToString()),
                ("quantity", quantity),
                ("bid", market.Bid),
                ("ask", market.Ask),
                ("quote_utc", market.QuoteUtc.ToString("O", CultureInfo.InvariantCulture)),
                ("tag", tag));

            TradingOperationResult result;
            try
            {
                result = Core.Instance.PlaceOrder(request);
            }
            catch (Exception ex)
            {
                _events.Write("order_submit_exception",
                    ("campaign_id", plan.Id),
                    ("role", role),
                    ("message", ex.Message));
                return Failure(ex.Message, requiresOperatorAction: true);
            }

            double elapsedMs = (Stopwatch.GetTimestamp() - before)
                * 1000.0 / Stopwatch.Frequency;
            bool accepted = IsSuccess(result);
            _events.Write("order_submit_result",
                ("campaign_id", plan.Id),
                ("role", role),
                ("accepted", accepted),
                ("order_id", result.OrderId),
                ("message", result.Message),
                ("elapsed_ms", elapsedMs));
            return new GatewayResult
            {
                Accepted = accepted,
                OrderId = result.OrderId,
                Message = result.Message,
                RequiresOperatorAction = !accepted,
            };
        }

        private GatewayResult ClosePosition(PolicyDecision decision,
            CampaignPlan plan,
            RuntimePosition position,
            string role)
        {
            if (position == null || position.IsFlat)
                return Success(null, "already flat");

            if (position.Direction != plan.Side)
            {
                return Failure("bound position is opposite campaign side",
                    requiresOperatorAction: true);
            }

            double requested = role == "REDUCE"
                ? Math.Max(1, decision.Quantity ?? 1)
                : position.Quantity;
            double quantity = Math.Min(position.Quantity, requested);

            if (!_tradingEnabled)
            {
                _events.Write("close_shadow",
                    ("campaign_id", plan.Id),
                    ("decision_action", decision.Action.ToString()),
                    ("policy", decision.Policy),
                    ("reason_code", decision.ReasonCode),
                    ("role", role),
                    ("side", position.Direction.ToString()),
                    ("quantity", quantity),
                    ("position_quantity", position.Quantity));
                return SuccessShadow("shadow close");
            }

            if (position.LivePosition == null)
                return Failure("live position handle is unavailable",
                    requiresOperatorAction: true);

            string tag = BuildTag(plan.Id, role, decision.EvidenceId);
            _events.Write("close_submit",
                ("campaign_id", plan.Id),
                ("decision_action", decision.Action.ToString()),
                ("policy", decision.Policy),
                ("reason_code", decision.ReasonCode),
                ("role", role),
                ("position_id", position.PositionId),
                ("side", position.Direction.ToString()),
                ("quantity", quantity),
                ("position_quantity", position.Quantity),
                ("tag", tag));

            TradingOperationResult result;
            try
            {
                result = Core.Instance.ClosePosition(new ClosePositionRequestParameters
                {
                    Position = position.LivePosition,
                    CloseQuantity = quantity,
                    SendingSource = SendingSource,
                });
            }
            catch (Exception ex)
            {
                _events.Write("close_submit_exception",
                    ("campaign_id", plan.Id),
                    ("role", role),
                    ("position_id", position.PositionId),
                    ("message", ex.Message));
                return Failure(ex.Message, requiresOperatorAction: true);
            }

            bool accepted = IsSuccess(result);
            _events.Write("close_submit_result",
                ("campaign_id", plan.Id),
                ("role", role),
                ("position_id", position.PositionId),
                ("accepted", accepted),
                ("order_id", result.OrderId),
                ("message", result.Message));
            return new GatewayResult
            {
                Accepted = accepted,
                OrderId = result.OrderId,
                Message = result.Message,
                RequiresOperatorAction = !accepted,
            };
        }

        private bool SameBoundPair(Symbol symbol, Account account)
            => symbol != null && account != null && _account != null
                && string.Equals(symbol.Id, _symbol.Id, StringComparison.Ordinal)
                && string.Equals(symbol.ConnectionId, _symbol.ConnectionId,
                    StringComparison.Ordinal)
                && string.Equals(account.Id, _account?.Id, StringComparison.Ordinal);

        private static bool IsWorkingOrder(Order order)
            => order != null
                && order.RemainingQuantity > 0
                && (order.Status == OrderStatus.Opened
                    || order.Status == OrderStatus.PartiallyFilled
                    || order.Status == OrderStatus.Inactive);

        private static bool IsSuccess(TradingOperationResult result)
            => result != null && result.Status == TradingOperationResultStatus.Success;

        private static string BuildTag(string campaignId, string role, string evidenceId)
        {
            string campaign = string.IsNullOrWhiteSpace(campaignId)
                ? "none"
                : campaignId;
            if (campaign.Length > 18)
                campaign = campaign.Substring(0, 18);

            string token = string.IsNullOrWhiteSpace(evidenceId)
                ? Guid.NewGuid().ToString("N").Substring(0, 8)
                : evidenceId;
            if (token.Length > 8)
                token = token.Substring(0, 8);

            return $"{TagPrefix}{campaign}:{role}:{token}";
        }

        private static GatewayResult Success(string orderId, string message)
            => new() { Accepted = true, OrderId = orderId, Message = message };

        private static GatewayResult SuccessShadow(string message)
            => new() { Accepted = true, Shadow = true, Message = message };

        private static GatewayResult Failure(string message,
            bool requiresOperatorAction = false)
            => new()
            {
                Accepted = false,
                RequiresOperatorAction = requiresOperatorAction,
                Message = message,
            };
    }

    internal sealed class BrokerEvent
    {
        public string EventType { get; init; }
        public string OrderId { get; init; }
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

        public static BrokerEvent FromOrder(string eventType, IOrder order)
            => new()
            {
                EventType = eventType,
                OrderId = order?.Id,
                PositionId = order?.PositionId,
                Side = order?.Side.ToString(),
                Status = order?.Status.ToString(),
                Quantity = order?.TotalQuantity ?? 0,
                FilledQuantity = order?.FilledQuantity ?? 0,
                RemainingQuantity = order?.RemainingQuantity ?? 0,
                Price = order?.Price ?? double.NaN,
                AverageFillPrice = order?.AverageFillPrice ?? double.NaN,
                BrokerUtc = DateTime.UtcNow,
                Comment = order?.Comment,
                GroupId = order?.GroupId,
            };

        public static BrokerEvent FromTrade(Trade trade)
            => new()
            {
                EventType = "trade_fill",
                OrderId = trade?.OrderId,
                PositionId = trade?.PositionId,
                Side = trade?.Side == TradingPlatform.BusinessLayer.Side.Buy ? "Long" : "Short",
                Quantity = trade?.Quantity ?? 0,
                Price = trade?.Price ?? double.NaN,
                BrokerUtc = trade?.DateTime ?? DateTime.UtcNow,
            };
    }
}
