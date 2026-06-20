using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Security.Cryptography;
using System.Text;
using System.Threading;
using TradingPlatform.BusinessLayer;

namespace ExecAssistantRuntime
{
    public sealed class ExecAssistantRuntime : Strategy
    {
        private const int L1ToleranceTicks = 2;

        [InputParameter("Symbol", sortIndex: 0)]
        public Symbol RuntimeSymbol;

        [InputParameter("Account", sortIndex: 1)]
        public Account RuntimeAccount;

        [InputParameter("Directive Path", sortIndex: 2)]
        public string DirectivePath = @"%USERPROFILE%\Documents\ExecAssistantRuntime\directive.json";

        [InputParameter("Control Path", sortIndex: 3)]
        public string ControlPath = @"%USERPROFILE%\Documents\ExecAssistantRuntime\control.json";

        [InputParameter("Event Log Path", sortIndex: 4)]
        public string EventLogPath = @"%USERPROFILE%\Documents\ExecAssistantRuntime\events.jsonl";

        [InputParameter("Checkpoint Path", sortIndex: 5)]
        public string CheckpointPath = @"%USERPROFILE%\Documents\ExecAssistantRuntime\checkpoint.json";

        [InputParameter("Trading Enabled", sortIndex: 6)]
        public bool TradingEnabled = false;

        [InputParameter("Instance Max Quantity", sortIndex: 7,
            minimum: 1, maximum: 100, increment: 1, decimalPlaces: 0)]
        public int InstanceMaxQuantity = 5;

        [InputParameter("Worker Poll (ms)", sortIndex: 8,
            minimum: 100, maximum: 5000, increment: 100, decimalPlaces: 0)]
        public int WorkerPollMs = 250;

        [InputParameter("Book Sample (ms)", sortIndex: 9,
            minimum: 250, maximum: 5000, increment: 250, decimalPlaces: 0)]
        public int BookSampleMs = 1000;

        [InputParameter("L2 Freshness (sec)", sortIndex: 10,
            minimum: 1, maximum: 60, increment: 1, decimalPlaces: 0)]
        public int BookFreshnessSec = 5;

        [InputParameter("Quote Freshness (ms)", sortIndex: 11,
            minimum: 250, maximum: 10000, increment: 250, decimalPlaces: 0)]
        public int QuoteFreshnessMs = 2000;

        [InputParameter("Run Startup Self Tests", sortIndex: 12)]
        public bool RunStartupSelfTests = true;

        [InputParameter("LL Book Lookback (sec)", sortIndex: 20,
            minimum: 10, maximum: 300, increment: 5, decimalPlaces: 0)]
        public int BookLookbackSeconds = 30;

        [InputParameter("LL Event |z|", sortIndex: 21,
            minimum: 1.5, maximum: 8.0, increment: 0.1, decimalPlaces: 2)]
        public double EventZThreshold = 2.5;

        [InputParameter("LL Cluster Min Events", sortIndex: 22,
            minimum: 2, maximum: 10, increment: 1, decimalPlaces: 0)]
        public int ClusterMinEvents = 3;

        [InputParameter("LL Cluster Ticks", sortIndex: 23,
            minimum: 1, maximum: 40, increment: 1, decimalPlaces: 0)]
        public int ClusterTicks = 10;

        [InputParameter("LL Cluster Seconds", sortIndex: 24,
            minimum: 15, maximum: 600, increment: 15, decimalPlaces: 0)]
        public int ClusterSeconds = 90;

        [InputParameter("LL Confirm Move (ticks)", sortIndex: 25,
            minimum: 2, maximum: 80, increment: 1, decimalPlaces: 0)]
        public int ConfirmMoveTicks = 8;

        [InputParameter("LL Confirm Seconds", sortIndex: 26,
            minimum: 0, maximum: 60, increment: 1, decimalPlaces: 0)]
        public int ConfirmSeconds = 10;

        [InputParameter("LL Failure Buffer (ticks)", sortIndex: 27,
            minimum: 0, maximum: 40, increment: 1, decimalPlaces: 0)]
        public int FailureBufferTicks = 2;

        [InputParameter("LL Failure Confirm (ticks)", sortIndex: 28,
            minimum: 2, maximum: 120, increment: 1, decimalPlaces: 0)]
        public int FailureConfirmTicks = 24;

        [InputParameter("LL Failure Seconds", sortIndex: 29,
            minimum: 0, maximum: 120, increment: 1, decimalPlaces: 0)]
        public int FailureSeconds = 20;

        private readonly object _marketGate = new();
        private readonly object _orderSubscriptionGate = new();
        private readonly HashSet<string> _subscribedOrderIds = new(StringComparer.Ordinal);
        private readonly ConcurrentQueue<BrokerEvent> _brokerEvents = new();
        private readonly Dictionary<string, SubmissionTelemetry> _submissions = new(StringComparer.Ordinal);
        private readonly Dictionary<string, string> _processedControlDigests = new(StringComparer.Ordinal);
        private readonly HashSet<string> _blockedDirectiveIds = new(StringComparer.Ordinal);

        private Timer _workerTimer;
        private RuntimeEventLog _events;
        private RuntimeCheckpointStore _checkpointStore;
        private RuntimeCheckpointData _checkpoint;
        private ExecutionEvidenceEngine _evidence;
        private ExecutionCoordinator _coordinator;
        private QuantowerOrderGateway _gateway;
        private GetDepthOfMarketParameters _domParameters;
        private volatile bool _running;
        private int _workerBusy;
        private double _tickSize;
        private double _latestBid = double.NaN;
        private double _latestAsk = double.NaN;
        private DateTime _quoteUtc = DateTime.MinValue;
        private DateTime _lastL2Utc = DateTime.MinValue;
        private DateTime _lastBookSampleUtc = DateTime.MinValue;
        private DateTime _lastCheckpointUtc = DateTime.MinValue;
        private bool _hadEvidenceSample;
        private bool _bookWasFresh;
        private string _lastDirectiveFileHash;
        private string _lastControlFileHash;
        private string _acceptedDirectiveRaw;
        private string _lastPositionSignature;
        private RuntimePosition _shadowPosition = RuntimePosition.Flat;
        private double? _shadowBreakeven;
        private double? _shadowHardTarget;
        private RuntimeExecutionState _lastLoggedState = RuntimeExecutionState.Idle;

        public ExecAssistantRuntime()
        {
            Name = "Exec Assistant Runtime";
            Description = "Directive-bound NQ execution strategy using copied LevelLedger ownership evidence.";
        }

        public override string[] MonitoringConnectionsIds
            => RuntimeSymbol == null || string.IsNullOrWhiteSpace(RuntimeSymbol.ConnectionId)
                ? Array.Empty<string>()
                : new[] { RuntimeSymbol.ConnectionId };

        protected override void OnRun()
        {
            if (!ResolveAccountAndSymbol())
            {
                Stop();
                return;
            }

            _tickSize = double.IsFinite(RuntimeSymbol.TickSize) && RuntimeSymbol.TickSize > 0
                ? RuntimeSymbol.TickSize
                : 0.25;
            try
            {
                ResetForRun();
                _events = new RuntimeEventLog(ExpandPath(EventLogPath),
                    message => Log(message, StrategyLoggingLevel.Error));
                _checkpointStore = new RuntimeCheckpointStore(ExpandPath(CheckpointPath));
                _evidence = NewEvidenceEngine();
                _coordinator = new ExecutionCoordinator(_tickSize);
                _gateway = new QuantowerOrderGateway(
                    RuntimeSymbol,
                    RuntimeAccount,
                    _events,
                    TradingEnabled);
                if (RunStartupSelfTests)
                {
                    RuntimeSelfTests.RunAll();
                    _events.Write("startup_self_tests_passed");
                }
                _domParameters = new GetDepthOfMarketParameters
                {
                    GetLevel2ItemsParameters = new GetLevel2ItemsParameters
                    {
                        LevelsCount = 30,
                        CalculateCumulative = false,
                    },
                };

                _running = true;
                Subscribe();
                LoadCheckpoint();
                RecoverAtStartup();
                PollControl();
                PollDirective();
                int interval = Math.Max(100, WorkerPollMs);
                _workerTimer = new Timer(_ => Worker(), null, interval, interval);
                _events.Write("runtime_started",
                    ("symbol", RuntimeSymbol.Name),
                    ("account", RuntimeAccount.Name),
                    ("tick_size", _tickSize),
                    ("trading_enabled", TradingEnabled),
                    ("directive_path", ExpandPath(DirectivePath)),
                    ("control_path", ExpandPath(ControlPath)));
                Log($"Runtime started for {RuntimeSymbol.Name}/{RuntimeAccount.Name}; "
                    + $"mode={(TradingEnabled ? "LIVE" : "SHADOW")}.");
            }
            catch (Exception ex)
            {
                Log($"Runtime initialization failed: {ex.Message}", StrategyLoggingLevel.Error);
                _running = false;
                try { _events?.Write("runtime_start_error", ("message", ex.Message)); } catch { }
                Stop();
            }
        }

        protected override void OnStop()
        {
            Shutdown("runtime_stopped");
        }

        protected override void OnRemove()
        {
            Shutdown("runtime_removed");
        }

        private void Worker()
        {
            if (!_running || Interlocked.Exchange(ref _workerBusy, 1) != 0)
                return;
            try
            {
                DateTime nowUtc = DateTime.UtcNow;
                DrainBrokerEvents();
                ExecutableMarket market = SnapshotMarket(nowUtc);
                RuntimePosition position = CurrentPosition();
                ReconcilePosition(position, nowUtc, market);
                if (position.IsFlat)
                    _gateway.CancelProtectionWhenFlat();
                ReconcileSubmissionTimeouts(nowUtc, position);
                EvaluateShadowProtection(nowUtc, market);

                PollControl();
                PollDirective();

                if ((nowUtc - _lastBookSampleUtc).TotalMilliseconds
                    >= Math.Max(250, BookSampleMs))
                {
                    _lastBookSampleUtc = nowUtc;
                    ProcessBookSample(nowUtc, market, position);
                }

                position = CurrentPosition();
                ExecuteIntents(_coordinator.Tick(nowUtc, market, position, _evidence),
                    position, market);
                LogStateIfChanged();
                SaveCheckpointIfDue(nowUtc, force: false);
            }
            catch (Exception ex)
            {
                _events?.Write("worker_error", ("message", ex.Message), ("stack", ex.StackTrace));
                Log($"Worker error: {ex.Message}", StrategyLoggingLevel.Error);
            }
            finally
            {
                Volatile.Write(ref _workerBusy, 0);
            }
        }

        private void ProcessBookSample(DateTime nowUtc, ExecutableMarket market,
            RuntimePosition position)
        {
            bool l2Fresh;
            lock (_marketGate)
            {
                l2Fresh = _lastL2Utc != DateTime.MinValue
                    && (nowUtc - _lastL2Utc).TotalSeconds <= Math.Max(1, BookFreshnessSec);
            }

            if (!l2Fresh || !TryBuildDepthSnapshot(nowUtc, out BookDepthSnapshot depth))
            {
                if (_bookWasFresh && _hadEvidenceSample)
                    HandleForwardDataLoss(nowUtc, market, position);
                _bookWasFresh = false;
                return;
            }

            _bookWasFresh = true;
            _hadEvidenceSample = true;
            IReadOnlyList<EvidenceTransition> transitions = _evidence.Process(depth);
            foreach (EvidenceTransition transition in transitions)
                LogEvidence(transition, market);
            ExecuteIntents(
                _coordinator.ProcessEvidence(transitions, nowUtc, market,
                    CurrentPosition(), _evidence),
                CurrentPosition(),
                market);
        }

        private void PollDirective()
        {
            string path = ExpandPath(DirectivePath);
            if (!TryReadChangedFile(path, ref _lastDirectiveFileHash,
                out string json, out string readError))
            {
                if (readError != null)
                    _events?.Write("directive_read_error", ("message", readError));
                return;
            }

            TradeDirective directive;
            try
            {
                directive = DirectiveContracts.ParseTradeDirective(json,
                    Math.Max(1, InstanceMaxQuantity));
            }
            catch (Exception ex)
            {
                _events.Write("directive_rejected",
                    ("reason", "contract"),
                    ("message", ex.Message));
                Log($"Directive rejected: {ex.Message}", StrategyLoggingLevel.Error);
                return;
            }

            TradeDirective active = _coordinator.Directive;
            if (active != null && string.Equals(active.Id, directive.Id, StringComparison.Ordinal))
            {
                if (!string.Equals(active.Digest, directive.Digest, StringComparison.Ordinal))
                {
                    _events.Write("directive_mutation_rejected",
                        ("directive_id", directive.Id),
                        ("accepted_digest", active.Digest),
                        ("new_digest", directive.Digest));
                    if (CurrentPosition().IsFlat)
                        _coordinator.MarkError();
                }
                return;
            }

            if (_blockedDirectiveIds.Contains(directive.Id))
            {
                _events.Write("directive_rejected",
                    ("directive_id", directive.Id),
                    ("reason", "fresh_id_required_after_restart_or_terminal_state"));
                return;
            }
            RuntimePosition position = CurrentPosition();
            if (!position.IsFlat)
            {
                _events.Write("directive_rejected",
                    ("directive_id", directive.Id),
                    ("reason", "bound_position_not_flat"),
                    ("position_id", position.PositionId),
                    ("position_quantity", position.Quantity));
                return;
            }
            Order[] workingOrders = BoundWorkingOrders();
            if (workingOrders.Length > 0)
            {
                _events.Write("directive_rejected",
                    ("directive_id", directive.Id),
                    ("reason", "bound_working_orders_exist"),
                    ("working_order_count", workingOrders.Length),
                    ("working_order_ids", string.Join(",", workingOrders.Select(o => o.Id))));
                return;
            }
            if (active != null && !IsCoordinatorTerminal())
            {
                _events.Write("directive_rejected",
                    ("directive_id", directive.Id),
                    ("reason", "prior_directive_active"),
                    ("active_directive_id", active.Id));
                return;
            }
            if (TradingEnabled && !directive.IsLiveTargetSupported)
            {
                _events.Write("directive_rejected",
                    ("directive_id", directive.Id),
                    ("reason", "target_mode_shadow_only"),
                    ("target_mode", directive.TargetMode.ToString()));
                Log($"Directive {directive.Id} uses a target mode not enabled for live trading.",
                    StrategyLoggingLevel.Error);
                return;
            }

            ExecutableMarket market = SnapshotMarket(DateTime.UtcNow);
            if (directive.TargetMode == TargetMode.HardTp && market.IsValid)
            {
                double executable = market.Executable(directive.Direction);
                bool noRunway = directive.Direction == TradeDirection.Long
                    ? executable >= directive.TargetPrice
                    : executable <= directive.TargetPrice;
                if (noRunway)
                {
                    _events.Write("directive_rejected",
                        ("directive_id", directive.Id),
                        ("reason", "hard_target_has_no_runway"),
                        ("executable_quote", executable),
                        ("target", directive.TargetPrice));
                    return;
                }
            }

            _coordinator.AcceptDirective(
                directive,
                DateTime.UtcNow,
                _evidence.HeldFailureObjects().Select(b => b.Id));
            _coordinator.InitializeObservedPosition(position);
            _acceptedDirectiveRaw = json;
            _blockedDirectiveIds.Add(directive.Id);
            _events.Write("directive_accepted",
                ("directive_id", directive.Id),
                ("digest", directive.Digest),
                ("side", directive.Direction.ToString()),
                ("not_before", directive.NotBefore.ToString("O")),
                ("expires_at", directive.ExpiresAt.ToString("O")),
                ("base_quantity", directive.BaseQuantity),
                ("add_quantity", directive.AddQuantity),
                ("max_position_quantity", directive.MaxPositionQuantity),
                ("target_mode", directive.TargetMode.ToString()),
                ("target_price", directive.TargetPrice),
                ("mode", TradingEnabled ? "LIVE" : "SHADOW"));
            SaveCheckpointIfDue(DateTime.UtcNow, force: true);
        }

        private void PollControl()
        {
            string path = ExpandPath(ControlPath);
            if (!TryReadChangedFile(path, ref _lastControlFileHash,
                out string json, out string readError))
            {
                if (readError != null)
                    _events?.Write("control_read_error", ("message", readError));
                return;
            }

            ControlCommand command;
            try
            {
                command = DirectiveContracts.ParseControlCommand(json);
            }
            catch (Exception ex)
            {
                _events.Write("control_rejected", ("message", ex.Message));
                return;
            }
            if (_processedControlDigests.TryGetValue(command.CommandId, out string priorDigest))
            {
                if (priorDigest != null && !string.Equals(priorDigest, command.Digest,
                    StringComparison.Ordinal))
                {
                    _events.Write("control_mutation_rejected",
                        ("command_id", command.CommandId));
                }
                return;
            }

            _processedControlDigests[command.CommandId] = command.Digest;
            ExecutableMarket market = SnapshotMarket(DateTime.UtcNow);
            RuntimePosition position = CurrentPosition();
            IReadOnlyList<OrderIntent> intents;
            if (command.Action == ControlAction.Flat)
            {
                intents = _coordinator.Flat(DateTime.UtcNow, market, position);
            }
            else if (_coordinator.Directive != null
                && string.Equals(_coordinator.Directive.Id, command.DirectiveId,
                    StringComparison.Ordinal))
            {
                intents = _coordinator.CancelDirective(DateTime.UtcNow, market, position);
            }
            else
            {
                intents = Array.Empty<OrderIntent>();
            }
            _events.Write("control_accepted",
                ("command_id", command.CommandId),
                ("action", command.Action.ToString()),
                ("directive_id", command.DirectiveId),
                ("reason", command.Reason));
            ExecuteIntents(intents, position, market);
            SaveCheckpointIfDue(DateTime.UtcNow, force: true);
        }

        private void ExecuteIntents(IReadOnlyList<OrderIntent> intents,
            RuntimePosition position, ExecutableMarket market)
        {
            if (intents == null || intents.Count == 0)
                return;
            foreach (OrderIntent intent in intents)
            {
                if (intent == null)
                    continue;
                GatewayResult result = _gateway.Execute(intent, position, market);
                _events.Write("intent_result",
                    ("intent_id", intent.IntentId),
                    ("directive_id", intent.DirectiveId),
                    ("kind", intent.Kind.ToString()),
                    ("reason", intent.Reason),
                    ("accepted", result.Accepted),
                    ("shadow", result.Shadow),
                    ("order_id", result.OrderId),
                    ("message", result.Message));

                if (intent.Kind == OrderIntentKind.EnterBase
                    || intent.Kind == OrderIntentKind.Add)
                {
                    _coordinator.OnOrderAttemptResult(intent, result.Accepted);
                    if (result.Accepted)
                    {
                        string submissionKey = string.IsNullOrWhiteSpace(result.OrderId)
                            ? intent.IntentId
                            : result.OrderId;
                        _submissions[submissionKey] = new SubmissionTelemetry
                        {
                            Intent = intent,
                            SubmitUtc = DateTime.UtcNow,
                            SubmitBid = market?.Bid ?? double.NaN,
                            SubmitAsk = market?.Ask ?? double.NaN,
                            PositionQuantityBefore = position?.Quantity ?? 0,
                        };
                    }
                    if (result.Shadow && result.Accepted)
                    {
                        ApplyShadowFill(intent, result.SyntheticFillPrice, market);
                        position = _shadowPosition;
                    }
                }
                else if (intent.Kind == OrderIntentKind.Flatten
                    && result.Shadow && result.Accepted)
                {
                    ApplyShadowFlatten(market);
                    position = _shadowPosition;
                }
                else if (intent.Kind == OrderIntentKind.EnsureBreakeven
                    && result.Shadow && result.Accepted)
                {
                    _shadowBreakeven = intent.Price;
                }
                else if (intent.Kind == OrderIntentKind.EnsureHardTarget
                    && result.Shadow && result.Accepted)
                {
                    _shadowHardTarget = intent.Price;
                }

                if (result.RequiresFlatten && position != null && !position.IsFlat)
                {
                    OrderIntent safety = _coordinator.SafetyFlatten(
                        DateTime.UtcNow,
                        market,
                        $"protection_failed:{result.Message}");
                    GatewayResult safetyResult = _gateway.Execute(safety, position, market);
                    _events.Write("safety_flatten_result",
                        ("intent_id", safety.IntentId),
                        ("accepted", safetyResult.Accepted),
                        ("message", safetyResult.Message));
                    if (safetyResult.Shadow && safetyResult.Accepted)
                        ApplyShadowFlatten(market);
                }
            }
        }

        private void ApplyShadowFill(OrderIntent intent, double fillPrice,
            ExecutableMarket market)
        {
            RuntimePosition before = _shadowPosition;
            double newQuantity = before.Quantity + intent.Quantity;
            double average = before.IsFlat
                ? fillPrice
                : (before.AveragePrice * before.Quantity + fillPrice * intent.Quantity)
                    / newQuantity;
            _shadowPosition = new RuntimePosition
            {
                PositionId = "shadow-position",
                Direction = intent.Direction,
                Quantity = newQuantity,
                AveragePrice = average,
            };
            IReadOnlyList<OrderIntent> protection = _coordinator.OnPositionChanged(
                _shadowPosition, DateTime.UtcNow, market);
            ExecuteIntents(protection, _shadowPosition, market);
        }

        private void ApplyShadowFlatten(ExecutableMarket market)
        {
            _shadowPosition = RuntimePosition.Flat;
            _shadowBreakeven = null;
            _shadowHardTarget = null;
            _coordinator.OnPositionChanged(_shadowPosition, DateTime.UtcNow, market);
        }

        private void EvaluateShadowProtection(DateTime nowUtc, ExecutableMarket market)
        {
            if (TradingEnabled || _shadowPosition.IsFlat || market == null || !market.IsValid)
                return;
            bool target = _shadowHardTarget.HasValue
                && (_shadowPosition.Direction == TradeDirection.Long
                    ? market.Bid >= _shadowHardTarget.Value
                    : market.Ask <= _shadowHardTarget.Value);
            bool breakeven = _shadowBreakeven.HasValue
                && (_shadowPosition.Direction == TradeDirection.Long
                    ? market.Bid <= _shadowBreakeven.Value
                    : market.Ask >= _shadowBreakeven.Value);
            if (!target && !breakeven)
                return;
            OrderIntent flatten = _coordinator.TerminalFlatten(nowUtc, market,
                target ? "HARD_TP_SHADOW" : "BREAKEVEN_SHADOW");
            ExecuteIntents(new[] { flatten }, _shadowPosition, market);
        }

        private void ReconcilePosition(RuntimePosition position, DateTime nowUtc,
            ExecutableMarket market)
        {
            TradeDirective directive = _coordinator.Directive;
            if (directive != null && !position.IsFlat
                && _coordinator.State != RuntimeExecutionState.Halting
                && _coordinator.State != RuntimeExecutionState.Halted
                && (position.Direction != directive.Direction
                    || position.Quantity > directive.MaxPositionQuantity))
            {
                string reason = position.Direction != directive.Direction
                    ? "bound_position_side_mismatch"
                    : "bound_position_exceeds_directive_max";
                OrderIntent safety = _coordinator.SafetyFlatten(nowUtc, market, reason);
                ExecuteIntents(new[] { safety }, position, market);
                return;
            }

            string signature = position.IsFlat
                ? "flat"
                : $"{position.PositionId}|{position.Direction}|{position.Quantity:R}|{position.AveragePrice:R}";
            if (string.Equals(signature, _lastPositionSignature, StringComparison.Ordinal))
                return;
            bool becameFlat = position.IsFlat
                && !string.IsNullOrWhiteSpace(_lastPositionSignature)
                && !string.Equals(_lastPositionSignature, "flat", StringComparison.Ordinal);
            _lastPositionSignature = signature;
            _events.Write("position_reconciled",
                ("position_id", position.PositionId),
                ("side", position.IsFlat ? null : position.Direction.ToString()),
                ("quantity", position.Quantity),
                ("average_price", position.AveragePrice));
            ExecuteIntents(_coordinator.OnPositionChanged(position, nowUtc, market),
                position, market);
            if (becameFlat)
                _gateway.CancelProtectionWhenFlat();
        }

        private void HandleForwardDataLoss(DateTime nowUtc, ExecutableMarket market,
            RuntimePosition position)
        {
            _events.Write("forward_data_loss",
                ("position_quantity", position?.Quantity ?? 0),
                ("state", _coordinator.State.ToString()));
            _evidence = NewEvidenceEngine();
            _hadEvidenceSample = false;

            if (position == null || position.IsFlat)
            {
                if (_coordinator.Directive != null && !IsCoordinatorTerminal())
                {
                    ExecuteIntents(_coordinator.CancelDirective(nowUtc, market, position),
                        position, market);
                }
                return;
            }

            if (!TradingEnabled)
            {
                OrderIntent flatten = _coordinator.SafetyFlatten(nowUtc, market,
                    "forward_data_loss_shadow");
                ExecuteIntents(new[] { flatten }, position, market);
                return;
            }

            if (!IsProfitable(position, market))
            {
                OrderIntent flatten = _coordinator.SafetyFlatten(nowUtc, market,
                    "forward_data_loss_not_profitable");
                ExecuteIntents(new[] { flatten }, position, market);
                return;
            }

            _coordinator.EnterRecoveryProtected();
            ProtectRecoveredPosition(position, market, "forward_data_loss");
        }

        private void LoadCheckpoint()
        {
            try
            {
                _checkpoint = _checkpointStore.Load() ?? new RuntimeCheckpointData();
                foreach (string id in _checkpoint.ProcessedControlIds.TakeLast(100))
                    _processedControlDigests[id] = null;
                if (!string.IsNullOrWhiteSpace(_checkpoint.LastDirectiveId))
                    _blockedDirectiveIds.Add(_checkpoint.LastDirectiveId);
            }
            catch (Exception ex)
            {
                _checkpoint = new RuntimeCheckpointData();
                _events.Write("checkpoint_load_error", ("message", ex.Message));
            }
        }

        private void RecoverAtStartup()
        {
            RuntimePosition position = LivePosition(out bool ambiguous);
            _coordinator.InitializeObservedPosition(position);
            var cancel = new OrderIntent
            {
                IntentId = Guid.NewGuid().ToString("N"),
                Kind = OrderIntentKind.CancelRuntimeOrders,
                Reason = position.IsFlat ? "restart_flat" : "restart_position",
                TriggerUtc = DateTime.UtcNow,
            };
            _gateway.Execute(cancel, position, SnapshotMarket(DateTime.UtcNow));

            if (position.IsFlat)
                return;
            if (!TradingEnabled)
            {
                _events.Write("recovery_action_required",
                    ("reason", "bound live position exists while strategy is in shadow mode"),
                    ("position_id", position.PositionId),
                    ("quantity", position.Quantity));
                return;
            }

            ExecutableMarket market = SnapshotMarket(DateTime.UtcNow);
            TradeDirective recoveredDirective = null;
            if (!string.IsNullOrWhiteSpace(_checkpoint.LastDirectiveJson))
            {
                try
                {
                    recoveredDirective = DirectiveContracts.ParseTradeDirective(
                        _checkpoint.LastDirectiveJson,
                        Math.Max(1, InstanceMaxQuantity));
                }
                catch (Exception ex)
                {
                    _events.Write("recovery_directive_error", ("message", ex.Message));
                }
            }

            if (ambiguous || recoveredDirective == null || !market.IsValid
                || !IsProfitable(position, market))
            {
                var flatten = new OrderIntent
                {
                    IntentId = Guid.NewGuid().ToString("N"),
                    Kind = OrderIntentKind.Flatten,
                    Direction = position.Direction,
                    Quantity = position.Quantity,
                    Reason = ambiguous ? "restart_ambiguous_position"
                        : recoveredDirective == null ? "restart_missing_directive"
                        : !market.IsValid ? "restart_missing_quote"
                        : "restart_position_not_profitable",
                    TriggerUtc = DateTime.UtcNow,
                };
                _gateway.Execute(flatten, position, market);
                return;
            }

            _coordinator.AcceptDirective(recoveredDirective, DateTime.UtcNow,
                Array.Empty<int>());
            _coordinator.InitializeObservedPosition(position);
            _coordinator.EnterRecoveryProtected();
            _acceptedDirectiveRaw = _checkpoint.LastDirectiveJson;
            ProtectRecoveredPosition(position, market, "startup_recovery");
        }

        private void ProtectRecoveredPosition(RuntimePosition position,
            ExecutableMarket market, string reason)
        {
            string directiveId = _coordinator.Directive?.Id ?? _checkpoint.LastDirectiveId;
            var be = new OrderIntent
            {
                IntentId = Guid.NewGuid().ToString("N"),
                Kind = OrderIntentKind.EnsureBreakeven,
                Direction = position.Direction,
                Quantity = position.Quantity,
                Price = position.AveragePrice,
                Reason = reason,
                DirectiveId = directiveId,
                TriggerUtc = DateTime.UtcNow,
                TriggerBid = market.Bid,
                TriggerAsk = market.Ask,
            };
            GatewayResult beResult = _gateway.Execute(be, position, market);
            if (!beResult.Accepted)
            {
                OrderIntent flatten = _coordinator.SafetyFlatten(DateTime.UtcNow,
                    market, $"recovery_breakeven_failed:{beResult.Message}");
                _gateway.Execute(flatten, position, market);
                return;
            }

            TradeDirective directive = _coordinator.Directive;
            if (directive != null)
            {
                var target = new OrderIntent
                {
                    IntentId = Guid.NewGuid().ToString("N"),
                    Kind = OrderIntentKind.EnsureHardTarget,
                    Direction = position.Direction,
                    Quantity = position.Quantity,
                    Price = directive.TargetPrice,
                    Reason = reason,
                    DirectiveId = directive.Id,
                    TriggerUtc = DateTime.UtcNow,
                    TriggerBid = market.Bid,
                    TriggerAsk = market.Ask,
                };
                GatewayResult targetResult = _gateway.Execute(target, position, market);
                if (!targetResult.Accepted)
                {
                    OrderIntent flatten = _coordinator.SafetyFlatten(DateTime.UtcNow,
                        market, $"recovery_target_failed:{targetResult.Message}");
                    _gateway.Execute(flatten, position, market);
                }
            }
        }

        private void DrainBrokerEvents()
        {
            while (_brokerEvents.TryDequeue(out BrokerEvent ev))
            {
                _events.Write(ev.EventType,
                    ("order_id", ev.OrderId),
                    ("position_id", ev.PositionId),
                    ("side", ev.Side),
                    ("status", ev.Status),
                    ("quantity", ev.Quantity),
                    ("filled_quantity", ev.FilledQuantity),
                    ("remaining_quantity", ev.RemainingQuantity),
                    ("price", ev.Price),
                    ("average_fill_price", ev.AverageFillPrice),
                    ("broker_utc", ev.BrokerUtc == default
                        ? null
                        : ev.BrokerUtc.ToString("O", CultureInfo.InvariantCulture)),
                    ("comment", ev.Comment));

                if (ev.EventType == "trade_fill")
                    LogFillQuality(ev);
                else if ((ev.EventType == "order_removed" || ev.EventType == "order_updated")
                    && (string.Equals(ev.Status, OrderStatus.Refused.ToString(), StringComparison.Ordinal)
                        || string.Equals(ev.Status, OrderStatus.Cancelled.ToString(), StringComparison.Ordinal))
                    && ev.FilledQuantity <= 0
                    && !string.IsNullOrWhiteSpace(ev.OrderId)
                    && _submissions.TryGetValue(ev.OrderId, out SubmissionTelemetry terminal))
                {
                    _coordinator.OnOrderAttemptResult(terminal.Intent, accepted: false);
                    _events.Write("entry_order_terminal_without_fill",
                        ("intent_id", terminal.Intent.IntentId),
                        ("order_id", ev.OrderId),
                        ("status", ev.Status));
                    _submissions.Remove(ev.OrderId);
                }
            }
        }

        private void LogFillQuality(BrokerEvent fill)
        {
            SubmissionTelemetry telemetry = null;
            if (!string.IsNullOrWhiteSpace(fill.OrderId))
                _submissions.TryGetValue(fill.OrderId, out telemetry);
            telemetry ??= _submissions.Values
                .Where(t => t.Intent.Direction.ToString() == fill.Side)
                .OrderByDescending(t => t.SubmitUtc)
                .FirstOrDefault();
            if (telemetry == null)
                return;
            telemetry.FillObserved = true;
            bool isLong = telemetry.Intent.Direction == TradeDirection.Long;
            double triggerExecutable = isLong
                ? telemetry.Intent.TriggerAsk
                : telemetry.Intent.TriggerBid;
            double submitExecutable = isLong
                ? telemetry.SubmitAsk
                : telemetry.SubmitBid;
            double detectionDrift = isLong
                ? submitExecutable - triggerExecutable
                : triggerExecutable - submitExecutable;
            double transportSlippage = isLong
                ? fill.Price - submitExecutable
                : submitExecutable - fill.Price;
            double totalCost = isLong
                ? fill.Price - triggerExecutable
                : triggerExecutable - fill.Price;
            long fillTick = PriceToTick(fill.Price);
            ResolutionContext resolution = telemetry.Intent.Resolution;
            _events.Write("fill_quality",
                ("intent_id", telemetry.Intent.IntentId),
                ("directive_id", telemetry.Intent.DirectiveId),
                ("order_id", fill.OrderId),
                ("fill_price", fill.Price),
                ("trigger_executable", triggerExecutable),
                ("submit_executable", submitExecutable),
                ("detection_drift_points", detectionDrift),
                ("transport_slippage_points", transportSlippage),
                ("total_implementation_cost_points", totalCost),
                ("root_distance_ticks", resolution == null
                    ? null
                    : DistanceToRange(fillTick, resolution.RootMinTick,
                        resolution.RootMaxTick)),
                ("support_distance_ticks", resolution == null
                    ? null
                    : DistanceToRange(fillTick, resolution.SupportMinTick,
                        resolution.SupportMaxTick)));
        }

        private void ReconcileSubmissionTimeouts(DateTime nowUtc, RuntimePosition position)
        {
            foreach ((string key, SubmissionTelemetry telemetry) in _submissions.ToArray())
            {
                if (position.Quantity > telemetry.PositionQuantityBefore)
                    telemetry.FillObserved = true;
                double ageSeconds = (nowUtc - telemetry.SubmitUtc).TotalSeconds;
                if (telemetry.FillObserved)
                {
                    if (ageSeconds > 60)
                        _submissions.Remove(key);
                    continue;
                }
                if (ageSeconds <= 10)
                    continue;
                _gateway.CancelOrderById(key);
                _coordinator.OnOrderAttemptResult(telemetry.Intent, accepted: false);
                _events.Write("entry_fill_timeout",
                    ("intent_id", telemetry.Intent.IntentId),
                    ("order_id", key),
                    ("elapsed_seconds", ageSeconds));
                _submissions.Remove(key);
            }
        }

        private void SaveCheckpointIfDue(DateTime nowUtc, bool force)
        {
            if (!force && (nowUtc - _lastCheckpointUtc).TotalSeconds < 2)
                return;
            _lastCheckpointUtc = nowUtc;
            RuntimePosition position = CurrentPosition();
            TradeDirective directive = _coordinator.Directive;
            _checkpoint = new RuntimeCheckpointData
            {
                RuntimeState = _coordinator.State.ToString(),
                LastDirectiveId = directive?.Id ?? _checkpoint?.LastDirectiveId,
                LastDirectiveDigest = directive?.Digest ?? _checkpoint?.LastDirectiveDigest,
                LastDirectiveJson = _acceptedDirectiveRaw ?? _checkpoint?.LastDirectiveJson,
                ProcessedControlIds = _processedControlDigests.Keys.TakeLast(100).ToList(),
                PositionId = position.PositionId,
                PositionDirection = position.IsFlat ? null : position.Direction.ToString(),
                PositionQuantity = position.Quantity,
                PositionAveragePrice = position.AveragePrice,
            };
            try
            {
                _checkpointStore.Save(_checkpoint);
            }
            catch (Exception ex)
            {
                _events.Write("checkpoint_save_error", ("message", ex.Message));
            }
        }

        private bool TryBuildDepthSnapshot(DateTime nowUtc, out BookDepthSnapshot snapshot)
        {
            snapshot = null;
            try
            {
                DepthOfMarketAggregatedCollections dom = RuntimeSymbol.DepthOfMarket?
                    .GetDepthOfMarketAggregatedCollections(_domParameters);
                if (dom == null || ((dom.Bids == null || dom.Bids.Length == 0)
                    && (dom.Asks == null || dom.Asks.Length == 0)))
                    return false;
                if (!L1Agrees(dom))
                    return false;
                snapshot = new BookDepthSnapshot
                {
                    TimeUtc = nowUtc,
                    BestBid = RuntimeSymbol.Bid,
                    BestAsk = RuntimeSymbol.Ask,
                    Bids = ConvertLevels(dom.Bids),
                    Asks = ConvertLevels(dom.Asks),
                };
                return true;
            }
            catch (Exception ex)
            {
                _events.Write("book_sample_error", ("message", ex.Message));
                return false;
            }
        }

        private bool L1Agrees(DepthOfMarketAggregatedCollections dom)
        {
            double domBid = FirstValidPrice(dom.Bids);
            double domAsk = FirstValidPrice(dom.Asks);
            if (double.IsFinite(domBid) && double.IsFinite(RuntimeSymbol.Bid)
                && Math.Abs(PriceToTick(domBid) - PriceToTick(RuntimeSymbol.Bid)) > L1ToleranceTicks)
                return false;
            if (double.IsFinite(domAsk) && double.IsFinite(RuntimeSymbol.Ask)
                && Math.Abs(PriceToTick(domAsk) - PriceToTick(RuntimeSymbol.Ask)) > L1ToleranceTicks)
                return false;
            return true;
        }

        private static IReadOnlyList<DepthLevelSnapshot> ConvertLevels(Level2Item[] levels)
            => (levels ?? Array.Empty<Level2Item>())
                .Where(l => l != null && double.IsFinite(l.Price) && l.Price > 0
                    && double.IsFinite(l.Size) && l.Size > 0)
                .Take(30)
                .Select(l => new DepthLevelSnapshot { Price = l.Price, Size = l.Size })
                .ToArray();

        private static double FirstValidPrice(Level2Item[] levels)
            => (levels ?? Array.Empty<Level2Item>())
                .FirstOrDefault(l => l != null && double.IsFinite(l.Price) && l.Price > 0
                    && double.IsFinite(l.Size) && l.Size > 0)?.Price ?? double.NaN;

        private ExecutableMarket SnapshotMarket(DateTime nowUtc)
        {
            lock (_marketGate)
            {
                bool fresh = _quoteUtc != DateTime.MinValue
                    && (nowUtc - _quoteUtc).TotalMilliseconds <= Math.Max(250, QuoteFreshnessMs);
                return new ExecutableMarket
                {
                    TimeUtc = nowUtc,
                    Bid = fresh ? _latestBid : double.NaN,
                    Ask = fresh ? _latestAsk : double.NaN,
                    QuoteUtc = _quoteUtc,
                };
            }
        }

        private RuntimePosition CurrentPosition()
        {
            if (!TradingEnabled && !_shadowPosition.IsFlat)
                return _shadowPosition;
            return LivePosition(out _);
        }

        private RuntimePosition LivePosition(out bool ambiguous)
        {
            Position[] positions = Core.Instance.Positions
                .Where(p => SameBoundPair(p.Symbol, p.Account))
                .ToArray();
            ambiguous = positions.Length > 1;
            if (positions.Length == 0)
                return RuntimePosition.Flat;
            Position position = positions[0];
            return new RuntimePosition
            {
                PositionId = position.Id,
                Direction = position.Side == Side.Buy
                    ? TradeDirection.Long
                    : TradeDirection.Short,
                Quantity = position.Quantity,
                AveragePrice = position.OpenPrice,
            };
        }

        private Order[] BoundWorkingOrders()
            => Core.Instance.Orders
                .Where(o => SameBoundPair(o.Symbol, o.Account)
                    && o.RemainingQuantity > 0)
                .ToArray();

        private bool IsProfitable(RuntimePosition position, ExecutableMarket market)
        {
            if (position == null || position.IsFlat || market == null || !market.IsValid)
                return false;
            return position.Direction == TradeDirection.Long
                ? market.Bid > position.AveragePrice
                : market.Ask < position.AveragePrice;
        }

        private void LogEvidence(EvidenceTransition transition, ExecutableMarket market)
        {
            _events.Write("evidence_transition",
                ("kind", transition.Kind.ToString()),
                ("reason", transition.Reason),
                ("event_utc", transition.TimeUtc.ToString("O", CultureInfo.InvariantCulture)),
                ("mid_tick", transition.CurrentMidTick),
                ("bid", market?.Bid),
                ("ask", market?.Ask),
                ("candidate_id", transition.Candidate?.Id),
                ("candidate_side", transition.Candidate?.Side.ToString()),
                ("candidate_min_tick", transition.Candidate?.MinTick),
                ("candidate_max_tick", transition.Candidate?.MaxTick),
                ("candidate_direction", transition.Candidate?.Direction.ToString()),
                ("candidate_direction_started_utc",
                    transition.Candidate?.DirectionStartedUtc?.ToString("O")),
                ("band_id", transition.Band?.Id),
                ("band_role", transition.Band?.Role.ToString()),
                ("band_side", transition.Band?.Side.ToString()),
                ("band_source", transition.Band?.Source.ToString()),
                ("band_state", transition.Band?.State.ToString()),
                ("band_min_tick", transition.Band?.MinTick),
                ("band_max_tick", transition.Band?.MaxTick));
        }

        private void LogStateIfChanged()
        {
            if (_coordinator.State == _lastLoggedState)
                return;
            RuntimeExecutionState previous = _lastLoggedState;
            _lastLoggedState = _coordinator.State;
            _events.Write("runtime_state",
                ("from", previous.ToString()),
                ("to", _lastLoggedState.ToString()),
                ("directive_id", _coordinator.Directive?.Id),
                ("base_attempts", _coordinator.BaseAttempts),
                ("ever_leveraged", _coordinator.EverLeveraged));
        }

        private void Subscribe()
        {
            RuntimeSymbol.NewQuote += Symbol_NewQuote;
            RuntimeSymbol.NewLevel2 += Symbol_NewLevel2;
            Core.Instance.OrderAdded += Core_OrderAdded;
            Core.Instance.OrderRemoved += Core_OrderRemoved;
            Core.Instance.TradeAdded += Core_TradeAdded;
            Core.Instance.PositionAdded += Core_PositionChanged;
            Core.Instance.PositionRemoved += Core_PositionChanged;
            foreach (Order order in Core.Instance.Orders.Where(o => SameBoundPair(o.Symbol, o.Account)))
                SubscribeOrder(order);
        }

        private void Unsubscribe()
        {
            try { RuntimeSymbol.NewQuote -= Symbol_NewQuote; } catch { }
            try { RuntimeSymbol.NewLevel2 -= Symbol_NewLevel2; } catch { }
            try { Core.Instance.OrderAdded -= Core_OrderAdded; } catch { }
            try { Core.Instance.OrderRemoved -= Core_OrderRemoved; } catch { }
            try { Core.Instance.TradeAdded -= Core_TradeAdded; } catch { }
            try { Core.Instance.PositionAdded -= Core_PositionChanged; } catch { }
            try { Core.Instance.PositionRemoved -= Core_PositionChanged; } catch { }
            foreach (Order order in Core.Instance.Orders.Where(o => SameBoundPair(o.Symbol, o.Account)))
            {
                try { order.Updated -= Order_Updated; } catch { }
            }
            lock (_orderSubscriptionGate)
                _subscribedOrderIds.Clear();
        }

        private void Symbol_NewQuote(Symbol symbol, Quote quote)
        {
            if (quote == null)
                return;
            lock (_marketGate)
            {
                if (double.IsFinite(quote.Bid) && quote.Bid > 0)
                    _latestBid = quote.Bid;
                if (double.IsFinite(quote.Ask) && quote.Ask > 0)
                    _latestAsk = quote.Ask;
                _quoteUtc = DateTime.UtcNow;
            }
        }

        private void Symbol_NewLevel2(Symbol symbol, Level2Quote l2, DOMQuote dom)
        {
            if (l2 != null
                && (string.Equals(l2.Id, "generated_from_level1",
                        StringComparison.OrdinalIgnoreCase)
                    || !double.IsFinite(l2.Price)
                    || !double.IsFinite(l2.Size)))
            {
                return;
            }
            lock (_marketGate)
                _lastL2Utc = DateTime.UtcNow;
        }

        private void Core_OrderAdded(Order order)
        {
            if (!SameBoundPair(order?.Symbol, order?.Account))
                return;
            SubscribeOrder(order);
            _brokerEvents.Enqueue(BrokerEvent.FromOrder("order_added", order));
        }

        private void Core_OrderRemoved(Order order)
        {
            if (!SameBoundPair(order?.Symbol, order?.Account))
                return;
            try { order.Updated -= Order_Updated; } catch { }
            lock (_orderSubscriptionGate)
                _subscribedOrderIds.Remove(order.Id);
            _brokerEvents.Enqueue(BrokerEvent.FromOrder("order_removed", order));
        }

        private void SubscribeOrder(Order order)
        {
            if (order == null || string.IsNullOrWhiteSpace(order.Id))
                return;
            lock (_orderSubscriptionGate)
            {
                if (!_subscribedOrderIds.Add(order.Id))
                    return;
                order.Updated += Order_Updated;
            }
        }

        private void Order_Updated(IOrder order)
        {
            if (order == null || !SameBoundPair(order.Symbol, order.Account))
                return;
            _brokerEvents.Enqueue(BrokerEvent.FromOrder("order_updated", order));
        }

        private void Core_TradeAdded(Trade trade)
        {
            if (!SameBoundPair(trade?.Symbol, trade?.Account))
                return;
            _brokerEvents.Enqueue(BrokerEvent.FromTrade(trade));
        }

        private void Core_PositionChanged(Position position)
        {
            if (!SameBoundPair(position?.Symbol, position?.Account))
                return;
            _brokerEvents.Enqueue(new BrokerEvent
            {
                EventType = "position_event",
                PositionId = position.Id,
                Side = position.Side == Side.Buy ? "Long" : "Short",
                Quantity = position.Quantity,
                Price = position.OpenPrice,
            });
        }

        private void Shutdown(string eventType)
        {
            if (!_running && _events == null)
                return;
            _running = false;
            try { _workerTimer?.Dispose(); } catch { }
            _workerTimer = null;
            try { _gateway?.CancelEntryOrdersOnStop(); } catch { }
            try { SaveCheckpointIfDue(DateTime.UtcNow, force: true); } catch { }
            try { _events?.Write(eventType, ("state", _coordinator?.State.ToString())); } catch { }
            Unsubscribe();
            try { _events?.Dispose(); } catch { }
            _events = null;
            Log("Runtime stopped.");
        }

        private void ResetForRun()
        {
            _latestBid = double.NaN;
            _latestAsk = double.NaN;
            _quoteUtc = DateTime.MinValue;
            _lastL2Utc = DateTime.MinValue;
            _lastBookSampleUtc = DateTime.MinValue;
            _lastCheckpointUtc = DateTime.MinValue;
            _hadEvidenceSample = false;
            _bookWasFresh = false;
            _lastDirectiveFileHash = null;
            _lastControlFileHash = null;
            _acceptedDirectiveRaw = null;
            _lastPositionSignature = null;
            _shadowPosition = RuntimePosition.Flat;
            _shadowBreakeven = null;
            _shadowHardTarget = null;
            _lastLoggedState = RuntimeExecutionState.Idle;
            _submissions.Clear();
            _processedControlDigests.Clear();
            _blockedDirectiveIds.Clear();
            while (_brokerEvents.TryDequeue(out _)) { }
            lock (_orderSubscriptionGate)
                _subscribedOrderIds.Clear();
        }

        private bool ResolveAccountAndSymbol()
        {
            if (RuntimeSymbol == null)
            {
                Log("No symbol selected.", StrategyLoggingLevel.Error);
                return false;
            }
            RuntimeAccount ??= RuntimeSymbol.GetDefaultAccount();
            if (RuntimeAccount == null)
            {
                Log("No account selected and no default account is available.",
                    StrategyLoggingLevel.Error);
                return false;
            }
            if (!RuntimeSymbol.IsTradingAllowed(RuntimeAccount))
            {
                Log($"Trading is not allowed for {RuntimeSymbol.Name}/{RuntimeAccount.Name}.",
                    StrategyLoggingLevel.Error);
                return false;
            }
            return true;
        }

        private ExecutionEvidenceEngine NewEvidenceEngine()
            => new(_tickSize, new EvidenceEngineSettings
            {
                BookLookbackSeconds = Math.Max(10, BookLookbackSeconds),
                EventZThreshold = Math.Max(1.0, EventZThreshold),
                ClusterMinEvents = Math.Max(2, ClusterMinEvents),
                ClusterTicks = Math.Max(1, ClusterTicks),
                ClusterSeconds = Math.Max(1, ClusterSeconds),
                ClusterMinScore = 8.0,
                ConfirmMoveTicks = Math.Max(1, ConfirmMoveTicks),
                ConfirmSeconds = Math.Max(0, ConfirmSeconds),
                FailureBufferTicks = Math.Max(0, FailureBufferTicks),
                FailureConfirmTicks = Math.Max(1, FailureConfirmTicks),
                FailureSeconds = Math.Max(0, FailureSeconds),
            });

        private bool IsCoordinatorTerminal()
            => _coordinator.State == RuntimeExecutionState.Completed
                || _coordinator.State == RuntimeExecutionState.Cancelled
                || _coordinator.State == RuntimeExecutionState.Invalidated
                || _coordinator.State == RuntimeExecutionState.Expired
                || _coordinator.State == RuntimeExecutionState.Error
                || _coordinator.State == RuntimeExecutionState.Halted;

        private bool SameBoundPair(Symbol symbol, Account account)
            => symbol != null && account != null
                && string.Equals(symbol.Id, RuntimeSymbol.Id, StringComparison.Ordinal)
                && string.Equals(symbol.ConnectionId, RuntimeSymbol.ConnectionId,
                    StringComparison.Ordinal)
                && string.Equals(account.Id, RuntimeAccount.Id, StringComparison.Ordinal);

        private long PriceToTick(double price)
            => (long)Math.Round(price / _tickSize);

        private static long DistanceToRange(long tick, long minTick, long maxTick)
            => tick < minTick ? minTick - tick
                : tick > maxTick ? tick - maxTick
                : 0;

        private static bool TryReadChangedFile(string path, ref string lastHash,
            out string json, out string error)
        {
            json = null;
            error = null;
            try
            {
                if (string.IsNullOrWhiteSpace(path) || !File.Exists(path))
                    return false;
                using var stream = new FileStream(path, FileMode.Open, FileAccess.Read,
                    FileShare.ReadWrite | FileShare.Delete);
                using var reader = new StreamReader(stream, Encoding.UTF8, true);
                string text = reader.ReadToEnd();
                string hash = Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(text)));
                if (string.Equals(hash, lastHash, StringComparison.Ordinal))
                    return false;
                lastHash = hash;
                json = text;
                return true;
            }
            catch (Exception ex)
            {
                error = ex.Message;
                return false;
            }
        }

        private static string ExpandPath(string path)
            => Environment.ExpandEnvironmentVariables(path ?? string.Empty);

        private sealed class SubmissionTelemetry
        {
            public OrderIntent Intent;
            public DateTime SubmitUtc;
            public double SubmitBid;
            public double SubmitAsk;
            public double PositionQuantityBefore;
            public bool FillObserved;
        }

        private sealed class BrokerEvent
        {
            public string EventType;
            public string OrderId;
            public string PositionId;
            public string Side;
            public string Status;
            public double Quantity;
            public double FilledQuantity;
            public double RemainingQuantity;
            public double Price;
            public double AverageFillPrice;
            public DateTime BrokerUtc;
            public string Comment;

            public static BrokerEvent FromOrder(string eventType, IOrder order)
                => new()
                {
                    EventType = eventType,
                    OrderId = order.Id,
                    PositionId = order.PositionId,
                    Side = order.Side.ToString(),
                    Status = order.Status.ToString(),
                    Quantity = order.TotalQuantity,
                    FilledQuantity = order.FilledQuantity,
                    RemainingQuantity = order.RemainingQuantity,
                    Price = order.Price,
                    AverageFillPrice = order.AverageFillPrice,
                    BrokerUtc = order.LastUpdateTime,
                    Comment = order.Comment,
                };

            public static BrokerEvent FromTrade(Trade trade)
                => new()
                {
                    EventType = "trade_fill",
                    OrderId = trade.OrderId,
                    PositionId = trade.PositionId,
                    Side = trade.Side == TradingPlatform.BusinessLayer.Side.Buy
                        ? "Long"
                        : "Short",
                    Quantity = trade.Quantity,
                    FilledQuantity = trade.Quantity,
                    Price = trade.Price,
                    AverageFillPrice = trade.Price,
                    BrokerUtc = trade.DateTime,
                    Comment = trade.Comment,
                };
        }
    }
}
