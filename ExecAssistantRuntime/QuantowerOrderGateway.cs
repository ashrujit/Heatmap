using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Globalization;
using System.Linq;
using TradingPlatform.BusinessLayer;

namespace ExecAssistantRuntime
{
    internal sealed class GatewayResult
    {
        public bool Accepted { get; init; }
        public bool Shadow { get; init; }
        public bool RequiresFlatten { get; init; }
        public string OrderId { get; init; }
        public string Message { get; init; }
        public double SyntheticFillPrice { get; init; } = double.NaN;
    }

    internal sealed class QuantowerOrderGateway
    {
        private const string SendingSource = "ExecAssistantRuntime";
        private const string TagPrefix = "EA:";

        private readonly Symbol _symbol;
        private readonly Account _account;
        private readonly RuntimeEventLog _events;
        private readonly bool _tradingEnabled;
        private readonly double _tickSize;

        public QuantowerOrderGateway(
            Symbol symbol,
            Account account,
            RuntimeEventLog events,
            bool tradingEnabled)
        {
            _symbol = symbol ?? throw new ArgumentNullException(nameof(symbol));
            _account = account ?? throw new ArgumentNullException(nameof(account));
            _events = events ?? throw new ArgumentNullException(nameof(events));
            _tradingEnabled = tradingEnabled;
            _tickSize = double.IsFinite(symbol.TickSize) && symbol.TickSize > 0
                ? symbol.TickSize
                : 0.25;
        }

        public GatewayResult Execute(
            OrderIntent intent,
            RuntimePosition position,
            ExecutableMarket market)
        {
            if (intent == null)
                return Failure("intent is null");
            return intent.Kind switch
            {
                OrderIntentKind.EnterBase => PlaceMarket(intent, market),
                OrderIntentKind.Add => PlaceMarket(intent, market),
                OrderIntentKind.Flatten => Flatten(intent, position),
                OrderIntentKind.EnsureHardTarget => EnsureHardTarget(intent, position),
                OrderIntentKind.EnsureBreakeven => EnsureBreakeven(intent, position, market),
                OrderIntentKind.CancelRuntimeOrders => CancelOrders(intent),
                _ => Failure($"unsupported intent {intent.Kind}"),
            };
        }

        public bool IsRuntimeOrder(IOrder order)
            => order != null
                && SameBoundPair(order.Symbol, order.Account)
                && ((order.Comment?.StartsWith(TagPrefix, StringComparison.Ordinal) ?? false)
                    || (order.GroupId?.StartsWith(TagPrefix, StringComparison.Ordinal) ?? false));

        public IReadOnlyList<Order> RuntimeOrders()
            => Core.Instance.Orders.Where(o => IsRuntimeOrder(o)).ToArray();

        public void CancelEntryOrdersOnStop()
        {
            if (!_tradingEnabled)
                return;
            foreach (Order order in RuntimeOrders()
                .Where(o => IsEntryOrder(o) && IsWorkingOrder(o)))
            {
                try { Core.Instance.CancelOrder((IOrder)order, SendingSource); } catch { }
            }
        }

        public void CancelProtectionWhenFlat()
        {
            if (!_tradingEnabled)
                return;
            foreach (Order order in RuntimeOrders()
                .Where(o => IsProtectionOrder(o) && IsWorkingOrder(o)))
            {
                try { Core.Instance.CancelOrder((IOrder)order, SendingSource); } catch { }
            }
        }

        public bool CancelEntryOrder(string orderId, string intentId)
        {
            if (!_tradingEnabled)
                return false;
            Order[] orders = Core.Instance.Orders
                .Where(o => IsRuntimeOrder(o) && IsEntryOrder(o) && IsWorkingOrder(o))
                .Where(o => (!string.IsNullOrWhiteSpace(orderId) && o.Id == orderId)
                    || HasIntentTag(o, intentId))
                .ToArray();
            bool allAccepted = orders.Length > 0;
            foreach (Order order in orders)
            {
                try
                {
                    TradingOperationResult result = Core.Instance.CancelOrder(
                        (IOrder)order, SendingSource);
                    bool accepted = result.Status == TradingOperationResultStatus.Success;
                    allAccepted &= accepted;
                    _events.Write("entry_timeout_cancel_result",
                        ("intent_id", intentId),
                        ("order_id", order.Id),
                        ("accepted", accepted),
                        ("message", result.Message));
                }
                catch (Exception ex)
                {
                    allAccepted = false;
                    _events.Write("entry_timeout_cancel_exception",
                        ("intent_id", intentId),
                        ("order_id", order.Id),
                        ("message", ex.Message));
                }
            }
            return allAccepted;
        }

        private GatewayResult PlaceMarket(OrderIntent intent, ExecutableMarket market)
        {
            if (market == null || !market.IsValid)
                return Failure("no valid executable quote");
            double executable = market.Executable(intent.Direction);
            if (!_tradingEnabled)
            {
                _events.Write("order_shadow_fill",
                    ("intent_id", intent.IntentId),
                    ("directive_id", intent.DirectiveId),
                    ("epoch", intent.Epoch),
                    ("role", intent.Kind.ToString()),
                    ("side", intent.Direction.ToString()),
                    ("quantity", intent.Quantity),
                    ("trigger_bid", intent.TriggerBid),
                    ("trigger_ask", intent.TriggerAsk),
                    ("submit_bid", market.Bid),
                    ("submit_ask", market.Ask),
                    ("fill_price", executable),
                    ("reason", intent.Reason));
                return new GatewayResult
                {
                    Accepted = true,
                    Shadow = true,
                    OrderId = $"shadow-{intent.IntentId}",
                    SyntheticFillPrice = executable,
                    Message = "shadow fill",
                };
            }

            OrderType marketType = _symbol.GetAlowedOrderTypes(OrderTypeUsage.Order)?
                .FirstOrDefault(o => o.Behavior == OrderTypeBehavior.Market);
            if (marketType == null)
                return Failure("broker exposes no market entry order type");

            string tag = BuildTag(intent, intent.Kind == OrderIntentKind.Add ? "ADD" : "BASE");
            var request = new PlaceOrderRequestParameters
            {
                Symbol = _symbol,
                Account = _account,
                Side = intent.Direction == TradeDirection.Long ? Side.Buy : Side.Sell,
                Quantity = intent.Quantity,
                OrderTypeId = marketType.Id,
                TimeInForce = TimeInForce.Day,
                GroupId = tag,
                Comment = tag,
                SendingSource = SendingSource,
            };

            long before = Stopwatch.GetTimestamp();
            _events.Write("order_submit",
                ("intent_id", intent.IntentId),
                ("directive_id", intent.DirectiveId),
                ("epoch", intent.Epoch),
                ("role", intent.Kind.ToString()),
                ("side", intent.Direction.ToString()),
                ("quantity", intent.Quantity),
                ("trigger_utc", intent.TriggerUtc.ToString("O", CultureInfo.InvariantCulture)),
                ("trigger_bid", intent.TriggerBid),
                ("trigger_ask", intent.TriggerAsk),
                ("submit_bid", market.Bid),
                ("submit_ask", market.Ask),
                ("quote_utc", market.QuoteUtc.ToString("O", CultureInfo.InvariantCulture)),
                ("quote_age_ms", Math.Max(0, (market.TimeUtc - market.QuoteUtc).TotalMilliseconds)),
                ("resolution", intent.Resolution?.Resolution.ToString()),
                ("root_object_id", intent.Resolution?.RootObjectId),
                ("support_object_id", intent.Resolution?.SupportObjectId),
                ("root_formed_utc", intent.Resolution?.RootFormedUtc.ToString("O",
                    CultureInfo.InvariantCulture)),
                ("root_min_tick", intent.Resolution?.RootMinTick),
                ("root_max_tick", intent.Resolution?.RootMaxTick),
                ("support_min_tick", intent.Resolution?.SupportMinTick),
                ("support_max_tick", intent.Resolution?.SupportMaxTick),
                ("root_min_price", intent.Resolution == null
                    ? null
                    : intent.Resolution.RootMinTick * _tickSize),
                ("root_max_price", intent.Resolution == null
                    ? null
                    : intent.Resolution.RootMaxTick * _tickSize),
                ("support_min_price", intent.Resolution == null
                    ? null
                    : intent.Resolution.SupportMinTick * _tickSize),
                ("support_max_price", intent.Resolution == null
                    ? null
                    : intent.Resolution.SupportMaxTick * _tickSize),
                ("reason", intent.Reason));

            TradingOperationResult result;
            try
            {
                result = Core.Instance.PlaceOrder(request);
            }
            catch (Exception ex)
            {
                _events.Write("order_submit_exception",
                    ("intent_id", intent.IntentId),
                    ("message", ex.Message));
                return Failure(ex.Message);
            }

            double elapsedMs = (Stopwatch.GetTimestamp() - before)
                * 1000.0 / Stopwatch.Frequency;
            bool accepted = result.Status == TradingOperationResultStatus.Success;
            _events.Write("order_submit_result",
                ("intent_id", intent.IntentId),
                ("accepted", accepted),
                ("order_id", result.OrderId),
                ("message", result.Message),
                ("elapsed_ms", elapsedMs));
            return new GatewayResult
            {
                Accepted = accepted,
                OrderId = result.OrderId,
                Message = result.Message,
            };
        }

        private GatewayResult EnsureHardTarget(OrderIntent intent, RuntimePosition position)
        {
            if (position == null || position.IsFlat)
                return Failure("cannot place target without a position", requiresFlatten: true);
            double price = RoundNearest(intent.Price);
            if (!_tradingEnabled)
            {
                _events.Write("protection_shadow",
                    ("intent_id", intent.IntentId),
                    ("role", "HARD_TP"),
                    ("quantity", position.Quantity),
                    ("price", price));
                return SuccessShadow("shadow hard target");
            }

            try
            {
                Order existing = FindProtection("TP");
                if (existing != null)
                {
                    if (NearlyEqual(existing.Price, price)
                        && NearlyEqual(existing.RemainingQuantity, position.Quantity))
                        return Success(existing.Id, "hard target already correct");
                    // Quantower initializes modify quantity from RemainingQuantity;
                    // this is the desired remaining close size.
                    TradingOperationResult modify = Core.Instance.ModifyOrder(
                        existing,
                        TimeInForce.Default,
                        position.Quantity,
                        price: price);
                    bool accepted = modify.Status == TradingOperationResultStatus.Success;
                    LogProtectionResult("target_modify", intent, existing.Id, price,
                        position.Quantity, accepted, modify.Message);
                    return new GatewayResult
                    {
                        Accepted = accepted,
                        RequiresFlatten = !accepted,
                        OrderId = existing.Id,
                        Message = modify.Message,
                    };
                }

                OrderType limit = _symbol.GetAlowedOrderTypes(OrderTypeUsage.CloseOrder)?
                    .FirstOrDefault(o => o.Behavior == OrderTypeBehavior.Limit);
                if (limit == null)
                    return Failure("broker exposes no close-position limit order type",
                        requiresFlatten: true);
                string tag = BuildTag(intent, "TP");
                var request = new PlaceOrderRequestParameters
                {
                    Symbol = _symbol,
                    Account = _account,
                    Side = position.Direction == TradeDirection.Long ? Side.Sell : Side.Buy,
                    Quantity = position.Quantity,
                    OrderTypeId = limit.Id,
                    Price = price,
                    TimeInForce = TimeInForce.Day,
                    PositionId = position.PositionId,
                    GroupId = tag,
                    Comment = tag,
                    SendingSource = SendingSource,
                };
                TradingOperationResult result = Core.Instance.PlaceOrder(request);
                bool ok = result.Status == TradingOperationResultStatus.Success;
                LogProtectionResult("target_place", intent, result.OrderId, price,
                    position.Quantity, ok, result.Message);
                return new GatewayResult
                {
                    Accepted = ok,
                    RequiresFlatten = !ok,
                    OrderId = result.OrderId,
                    Message = result.Message,
                };
            }
            catch (Exception ex)
            {
                _events.Write("target_exception",
                    ("intent_id", intent.IntentId),
                    ("message", ex.Message));
                return Failure(ex.Message, requiresFlatten: true);
            }
        }

        private GatewayResult EnsureBreakeven(
            OrderIntent intent,
            RuntimePosition position,
            ExecutableMarket market)
        {
            if (position == null || position.IsFlat || market == null || !market.IsValid)
                return Failure("cannot establish breakeven without position and quote", requiresFlatten: true);
            double trigger = position.Direction == TradeDirection.Long
                ? RoundUp(position.AveragePrice)
                : RoundDown(position.AveragePrice);
            bool valid = position.Direction == TradeDirection.Long
                ? trigger < market.Bid
                : trigger > market.Ask;
            if (!valid)
                return Failure("breakeven trigger is no longer valid relative to market", requiresFlatten: true);

            if (!_tradingEnabled)
            {
                _events.Write("protection_shadow",
                    ("intent_id", intent.IntentId),
                    ("role", "BREAKEVEN"),
                    ("quantity", position.Quantity),
                    ("price", trigger));
                return SuccessShadow("shadow breakeven");
            }

            try
            {
                Order existing = FindProtection("BE");
                if (existing != null)
                {
                    if (NearlyEqual(existing.TriggerPrice, trigger)
                        && NearlyEqual(existing.RemainingQuantity, position.Quantity))
                        return Success(existing.Id, "breakeven already correct");
                    TradingOperationResult modify = Core.Instance.ModifyOrder(
                        existing,
                        TimeInForce.Default,
                        position.Quantity,
                        triggerPrice: trigger);
                    bool accepted = modify.Status == TradingOperationResultStatus.Success;
                    LogProtectionResult("breakeven_modify", intent, existing.Id, trigger,
                        position.Quantity, accepted, modify.Message);
                    return new GatewayResult
                    {
                        Accepted = accepted,
                        RequiresFlatten = !accepted,
                        OrderId = existing.Id,
                        Message = modify.Message,
                    };
                }

                OrderType stop = _symbol.GetAlowedOrderTypes(OrderTypeUsage.CloseOrder)?
                    .FirstOrDefault(o => o.Behavior == OrderTypeBehavior.Stop);
                if (stop == null)
                    return Failure("broker exposes no close-position stop-market order type",
                        requiresFlatten: true);
                string tag = BuildTag(intent, "BE");
                var request = new PlaceOrderRequestParameters
                {
                    Symbol = _symbol,
                    Account = _account,
                    Side = position.Direction == TradeDirection.Long ? Side.Sell : Side.Buy,
                    Quantity = position.Quantity,
                    OrderTypeId = stop.Id,
                    TriggerPrice = trigger,
                    TimeInForce = TimeInForce.Day,
                    PositionId = position.PositionId,
                    GroupId = tag,
                    Comment = tag,
                    SendingSource = SendingSource,
                };
                TradingOperationResult result = Core.Instance.PlaceOrder(request);
                bool ok = result.Status == TradingOperationResultStatus.Success;
                LogProtectionResult("breakeven_place", intent, result.OrderId, trigger,
                    position.Quantity, ok, result.Message);
                return new GatewayResult
                {
                    Accepted = ok,
                    RequiresFlatten = !ok,
                    OrderId = result.OrderId,
                    Message = result.Message,
                };
            }
            catch (Exception ex)
            {
                _events.Write("breakeven_exception",
                    ("intent_id", intent.IntentId),
                    ("message", ex.Message));
                return Failure(ex.Message, requiresFlatten: true);
            }
        }

        private GatewayResult Flatten(OrderIntent intent, RuntimePosition position)
        {
            if (position == null || position.IsFlat)
                return Success(null, "already flat");
            if (!_tradingEnabled)
            {
                _events.Write("flatten_shadow",
                    ("intent_id", intent.IntentId),
                    ("directive_id", intent.DirectiveId),
                    ("quantity", position.Quantity),
                    ("reason", intent.Reason));
                return SuccessShadow("shadow flatten");
            }

            try
            {
                foreach (Order order in RuntimeOrders().Where(IsWorkingOrder))
                {
                    try { Core.Instance.CancelOrder((IOrder)order, SendingSource); } catch { }
                }
            }
            catch (Exception ex)
            {
                _events.Write("flatten_cancel_exception",
                    ("intent_id", intent.IntentId),
                    ("message", ex.Message));
            }

            Position[] livePositions = FindBoundPositions();
            if (livePositions.Length == 0)
                return Success(null, "position already absent");
            if (livePositions.Length > 1)
            {
                _events.Write("ambiguous_position_flatten",
                    ("intent_id", intent.IntentId),
                    ("position_count", livePositions.Length),
                    ("position_ids", string.Join(",", livePositions.Select(p => p.Id))));
            }

            bool allAccepted = true;
            var messages = new List<string>();
            foreach (Position live in livePositions
                .OrderByDescending(p => p.Id == position.PositionId))
            {
                try
                {
                    TradingOperationResult result = Core.Instance.ClosePosition(live);
                    bool accepted = result.Status == TradingOperationResultStatus.Success;
                    allAccepted &= accepted;
                    messages.Add(result.Message);
                    _events.Write("flatten_result",
                        ("intent_id", intent.IntentId),
                        ("directive_id", intent.DirectiveId),
                        ("position_id", live.Id),
                        ("quantity", live.Quantity),
                        ("reason", intent.Reason),
                        ("accepted", accepted),
                        ("message", result.Message));
                }
                catch (Exception ex)
                {
                    allAccepted = false;
                    messages.Add(ex.Message);
                    _events.Write("flatten_exception",
                        ("intent_id", intent.IntentId),
                        ("position_id", live.Id),
                        ("message", ex.Message));
                }
            }
            return new GatewayResult
            {
                Accepted = allAccepted,
                RequiresFlatten = !allAccepted,
                Message = string.Join("; ", messages.Where(m => !string.IsNullOrWhiteSpace(m))),
            };
        }

        private GatewayResult CancelOrders(OrderIntent intent)
        {
            IEnumerable<Order> orders = intent.Reason == "FLAT"
                ? Core.Instance.Orders.Where(o =>
                    SameBoundPair(o.Symbol, o.Account) && IsWorkingOrder(o))
                : Core.Instance.Orders.Where(o => IsRuntimeOrder(o) && IsWorkingOrder(o));
            bool allAccepted = true;
            int count = 0;
            try
            {
                foreach (Order order in orders.ToArray())
                {
                    count++;
                    if (!_tradingEnabled)
                        continue;
                    try
                    {
                        TradingOperationResult result = Core.Instance.CancelOrder(
                            (IOrder)order, SendingSource);
                        bool accepted = result.Status == TradingOperationResultStatus.Success;
                        allAccepted &= accepted;
                        _events.Write("cancel_order_result",
                            ("intent_id", intent.IntentId),
                            ("order_id", order.Id),
                            ("accepted", accepted),
                            ("message", result.Message),
                            ("reason", intent.Reason));
                    }
                    catch (Exception ex)
                    {
                        allAccepted = false;
                        _events.Write("cancel_order_exception",
                            ("intent_id", intent.IntentId),
                            ("order_id", order.Id),
                            ("message", ex.Message),
                            ("reason", intent.Reason));
                    }
                }
            }
            catch (Exception ex)
            {
                allAccepted = false;
                _events.Write("cancel_enumeration_exception",
                    ("intent_id", intent.IntentId),
                    ("message", ex.Message),
                    ("reason", intent.Reason));
            }
            if (!_tradingEnabled)
            {
                _events.Write("cancel_orders_shadow",
                    ("intent_id", intent.IntentId),
                    ("count", count),
                    ("reason", intent.Reason));
            }
            return new GatewayResult
            {
                Accepted = allAccepted,
                Shadow = !_tradingEnabled,
                Message = $"cancelled/requested {count} orders",
            };
        }

        private Position[] FindBoundPositions()
            => Core.Instance.Positions
                .Where(p => SameBoundPair(p.Symbol, p.Account))
                .ToArray();

        private Order FindProtection(string role)
            => Core.Instance.Orders.FirstOrDefault(o => IsRuntimeOrder(o)
                && IsWorkingOrder(o)
                && ((o.Comment?.Contains($":{role}:", StringComparison.Ordinal) ?? false)
                    || (o.GroupId?.Contains($":{role}:", StringComparison.Ordinal) ?? false)));

        private static bool IsWorkingOrder(Order order)
            => order != null
                && IsWorkingOrderState(order.RemainingQuantity, order.Status);

        internal static bool IsWorkingOrderState(double remainingQuantity,
            OrderStatus status)
            => remainingQuantity > 0
                && (status == OrderStatus.Opened
                    || status == OrderStatus.PartiallyFilled
                    || status == OrderStatus.Inactive);

        private static bool IsEntryOrder(Order order)
            => order != null
                && ((order.Comment?.Contains(":BASE:", StringComparison.Ordinal) ?? false)
                    || (order.Comment?.Contains(":ADD:", StringComparison.Ordinal) ?? false)
                    || (order.GroupId?.Contains(":BASE:", StringComparison.Ordinal) ?? false)
                    || (order.GroupId?.Contains(":ADD:", StringComparison.Ordinal) ?? false));

        private static bool HasIntentTag(Order order, string intentId)
        {
            string token = IntentToken(intentId);
            return token != null
                && ((order.Comment?.EndsWith($":{token}", StringComparison.Ordinal) ?? false)
                    || (order.GroupId?.EndsWith($":{token}", StringComparison.Ordinal) ?? false));
        }

        private static bool IsProtectionOrder(Order order)
            => order != null
                && ((order.Comment?.Contains(":TP:", StringComparison.Ordinal) ?? false)
                    || (order.Comment?.Contains(":BE:", StringComparison.Ordinal) ?? false)
                    || (order.GroupId?.Contains(":TP:", StringComparison.Ordinal) ?? false)
                    || (order.GroupId?.Contains(":BE:", StringComparison.Ordinal) ?? false));

        private bool SameBoundPair(Symbol symbol, Account account)
            => symbol != null && account != null
                && string.Equals(symbol.Id, _symbol.Id, StringComparison.Ordinal)
                && string.Equals(symbol.ConnectionId, _symbol.ConnectionId, StringComparison.Ordinal)
                && string.Equals(account.Id, _account.Id, StringComparison.Ordinal);

        private string BuildTag(OrderIntent intent, string role)
        {
            string directive = intent.DirectiveId ?? "none";
            if (directive.Length > 18)
                directive = directive.Substring(0, 18);
            string id = IntentToken(intent.IntentId)
                ?? Guid.NewGuid().ToString("N").Substring(0, 8);
            return $"{TagPrefix}{directive}:{role}:{id}";
        }

        private static string IntentToken(string intentId)
        {
            if (string.IsNullOrWhiteSpace(intentId))
                return null;
            return intentId.Length > 8 ? intentId.Substring(0, 8) : intentId;
        }

        private void LogProtectionResult(string eventType, OrderIntent intent,
            string orderId, double price, double quantity, bool accepted, string message)
            => _events.Write(eventType,
                ("intent_id", intent.IntentId),
                ("directive_id", intent.DirectiveId),
                ("order_id", orderId),
                ("price", price),
                ("quantity", quantity),
                ("accepted", accepted),
                ("message", message));

        private double RoundNearest(double price)
            => Math.Round(price / _tickSize) * _tickSize;

        private double RoundUp(double price)
            => Math.Ceiling((price / _tickSize) - 1e-9) * _tickSize;

        private double RoundDown(double price)
            => Math.Floor((price / _tickSize) + 1e-9) * _tickSize;

        private bool NearlyEqual(double left, double right)
            => double.IsFinite(left) && double.IsFinite(right)
                && Math.Abs(left - right) <= _tickSize * 0.1;

        private static GatewayResult Success(string orderId, string message)
            => new() { Accepted = true, OrderId = orderId, Message = message };

        private static GatewayResult SuccessShadow(string message)
            => new() { Accepted = true, Shadow = true, Message = message };

        private static GatewayResult Failure(string message, bool requiresFlatten = false)
            => new()
            {
                Accepted = false,
                RequiresFlatten = requiresFlatten,
                Message = message,
            };
    }
}
