using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Threading;
using TradingPlatform.BusinessLayer;
using LlBookDepthSnapshot = KahnRuntime.LiveEvidence.BookDepthSnapshot;
using LlDepthLevelSnapshot = KahnRuntime.LiveEvidence.DepthLevelSnapshot;
using LlEvidenceEngine = KahnRuntime.LiveEvidence.ExecutionEvidenceEngine;
using LlEvidenceEngineSettings = KahnRuntime.LiveEvidence.EvidenceEngineSettings;
using LlEvidenceRole = KahnRuntime.LiveEvidence.EvidenceRole;
using LlEvidenceSide = KahnRuntime.LiveEvidence.EvidenceSide;
using LlEvidenceTransition = KahnRuntime.LiveEvidence.EvidenceTransition;
using LlEvidenceTransitionKind = KahnRuntime.LiveEvidence.EvidenceTransitionKind;

namespace KahnRuntime
{
    public sealed class KahnRuntime : Strategy
    {
        private const int L1ToleranceTicks = 2;

        [InputParameter("Symbol", sortIndex: 0)]
        public Symbol RuntimeSymbol;

        [InputParameter("Market Data Symbol", sortIndex: 1)]
        public Symbol MarketDataSymbol;

        [InputParameter("Account", sortIndex: 2)]
        public Account RuntimeAccount;

        [InputParameter("Campaign Path", sortIndex: 3)]
        public string CampaignPath = @"%USERPROFILE%\Documents\KahnRuntime\campaign.json";

        [InputParameter("Control Path", sortIndex: 4)]
        public string ControlPath = @"%USERPROFILE%\Documents\KahnRuntime\control.json";

        [InputParameter("Evidence Path", sortIndex: 5)]
        public string EvidencePath = @"%USERPROFILE%\Documents\KahnRuntime\evidence.jsonl";

        [InputParameter("Decision Log Path", sortIndex: 6)]
        public string DecisionLogPath = @"%USERPROFILE%\Documents\KahnRuntime\decisions.jsonl";

        [InputParameter("Checkpoint Path", sortIndex: 7)]
        public string CheckpointPath = @"%USERPROFILE%\Documents\KahnRuntime\checkpoint.json";

        [InputParameter("Trading Enabled", sortIndex: 8)]
        public bool TradingEnabled = false;

        [InputParameter("Shadow Fill Simulation", sortIndex: 9)]
        public bool ShadowFillSimulation = true;

        [InputParameter("Instance Max Quantity", sortIndex: 10,
            minimum: 1, maximum: 100, increment: 1, decimalPlaces: 0)]
        public int InstanceMaxQuantity = 5;

        [InputParameter("Run Startup Self Tests", sortIndex: 11)]
        public bool RunStartupSelfTests = true;

        [InputParameter("Worker Poll (ms)", sortIndex: 12,
            minimum: 100, maximum: 5000, increment: 100, decimalPlaces: 0)]
        public int WorkerPollMs = 250;

        [InputParameter("Book Sample (ms)", sortIndex: 13,
            minimum: 250, maximum: 5000, increment: 250, decimalPlaces: 0)]
        public int BookSampleMs = 1000;

        [InputParameter("L2 Freshness (sec)", sortIndex: 14,
            minimum: 1, maximum: 60, increment: 1, decimalPlaces: 0)]
        public int BookFreshnessSec = 5;

        [InputParameter("Quote Freshness (ms)", sortIndex: 15,
            minimum: 250, maximum: 10000, increment: 250, decimalPlaces: 0)]
        public int QuoteFreshnessMs = 2000;

        [InputParameter("LL Book Lookback (sec)", sortIndex: 16,
            minimum: 10, maximum: 300, increment: 5, decimalPlaces: 0)]
        public int BookLookbackSeconds = 30;

        [InputParameter("LL Event |z|", sortIndex: 17,
            minimum: 1.5, maximum: 8.0, increment: 0.1, decimalPlaces: 2)]
        public double EventZThreshold = 2.5;

        [InputParameter("LL Cluster Min Events", sortIndex: 18,
            minimum: 2, maximum: 10, increment: 1, decimalPlaces: 0)]
        public int ClusterMinEvents = 3;

        [InputParameter("LL Cluster Ticks", sortIndex: 19,
            minimum: 1, maximum: 40, increment: 1, decimalPlaces: 0)]
        public int ClusterTicks = 10;

        [InputParameter("LL Cluster Seconds", sortIndex: 20,
            minimum: 15, maximum: 600, increment: 15, decimalPlaces: 0)]
        public int ClusterSeconds = 90;

        [InputParameter("LL Confirm Move (ticks)", sortIndex: 21,
            minimum: 2, maximum: 80, increment: 1, decimalPlaces: 0)]
        public int ConfirmMoveTicks = 8;

        [InputParameter("LL Confirm Seconds", sortIndex: 22,
            minimum: 0, maximum: 60, increment: 1, decimalPlaces: 0)]
        public int ConfirmSeconds = 10;

        [InputParameter("LL Failure Buffer (ticks)", sortIndex: 23,
            minimum: 0, maximum: 40, increment: 1, decimalPlaces: 0)]
        public int FailureBufferTicks = 2;

        [InputParameter("LL Failure Confirm (ticks)", sortIndex: 24,
            minimum: 2, maximum: 120, increment: 1, decimalPlaces: 0)]
        public int FailureConfirmTicks = 24;

        [InputParameter("LL Failure Seconds", sortIndex: 25,
            minimum: 0, maximum: 120, increment: 1, decimalPlaces: 0)]
        public int FailureSeconds = 20;

        private readonly object _marketGate = new();
        private readonly object _orderSubscriptionGate = new();
        private readonly ConcurrentQueue<CampaignEvidence> _marketEvents = new();
        private readonly ConcurrentQueue<BrokerEvent> _brokerEvents = new();
        private readonly Dictionary<string, Order> _subscribedOrders = new(StringComparer.Ordinal);
        private readonly HashSet<string> _processedControlIds = new(StringComparer.Ordinal);

        private Timer _workerTimer;
        private int _shutdownStarted;
        private int _workerBusy;
        private volatile bool _running;
        private bool _runTradingEnabled;
        private ShadowDecisionLog _decisions;
        private RuntimeCheckpointStore _checkpointStore;
        private CampaignPlanStore _planStore;
        private RuntimeControlStore _controlStore;
        private EvidenceInbox _evidenceInbox;
        private CampaignPolicyEngine _policyEngine;
        private LlEvidenceEngine _liveEvidence;
        private KahnOrderGateway _gateway;
        private Symbol _marketDataSymbol;
        private GetDepthOfMarketParameters _domParameters;
        private CampaignPlan _plan;
        private CampaignState _state;
        private double _tickSize = 0.25;
        private double _latestBid = double.NaN;
        private double _latestAsk = double.NaN;
        private DateTime _lastQuoteUtc = DateTime.MinValue;
        private DateTime _lastL2Utc = DateTime.MinValue;
        private DateTime _lastBookSampleUtc = DateTime.MinValue;
        private DateTime _lastCheckpointUtc = DateTime.MinValue;
        private DateTime _evidenceEpochStartedUtc = DateTime.MinValue;
        private DateTime _liveSettleUntilUtc = DateTime.MinValue;
        private int _evidenceEpochSampleCount;
        private bool _evidenceWarmupComplete;
        private string _evidenceState = "AwaitingBook";
        private string _evidenceEpochReason = "startup";
        private string _lastBookHealthSignature;
        private string _lastPositionSignature;
        private string _lastRecoverySignature;
        private string _lastPlanError;
        private string _lastControlError;
        private string _lastControlId;
        private string _lastControlAction;
        private string _lastControlStatus;

        public KahnRuntime()
        {
            Name = "Kahn Runtime";
            Description = "Adaptive campaign governor with shadow replay, live LL evidence, and optional broker execution.";
        }

        public override string[] MonitoringConnectionsIds
        {
            get
            {
                Symbol dataSymbol = _marketDataSymbol ?? MarketDataSymbol ?? RuntimeSymbol;
                return new[]
                    {
                        RuntimeSymbol?.ConnectionId,
                        dataSymbol?.ConnectionId,
                    }
                    .Where(id => !string.IsNullOrWhiteSpace(id))
                    .Distinct(StringComparer.Ordinal)
                    .ToArray();
            }
        }

        protected override void OnRun()
        {
            try
            {
                ResetForRun();
                _runTradingEnabled = TradingEnabled;
                _decisions = new ShadowDecisionLog(
                    DecisionLogPath,
                    message => LogOperator("ERR", message, error: true));
                _checkpointStore = new RuntimeCheckpointStore(CheckpointPath);

                if (!ResolveAccountAndSymbols())
                {
                    SaveCheckpoint(force: true, runtimeState: "ConfigurationError");
                    Stop();
                    return;
                }

                _tickSize = EffectiveTickSize(_marketDataSymbol);
                _policyEngine = CampaignPolicyEngine.CreateDefault();
                _planStore = new CampaignPlanStore(CampaignPath);
                _controlStore = new RuntimeControlStore(ControlPath);
                _evidenceInbox = new EvidenceInbox(EvidencePath);
                _liveEvidence = NewEvidenceEngine();
                _gateway = new KahnOrderGateway(
                    RuntimeSymbol,
                    RuntimeAccount,
                    _decisions,
                    _runTradingEnabled,
                    Math.Max(1, InstanceMaxQuantity));
                _domParameters = new GetDepthOfMarketParameters
                {
                    GetLevel2ItemsParameters = new GetLevel2ItemsParameters
                    {
                        LevelsCount = 30,
                        CalculateCumulative = false,
                    },
                };

                if (RunStartupSelfTests)
                {
                    RuntimeSelfTests.RunAll();
                    _decisions.Write("startup_self_tests_passed");
                }

                Subscribe();
                _running = true;
                int interval = Math.Max(100, WorkerPollMs);
                _workerTimer = new Timer(_ => Worker(), null, interval, interval);
                _decisions.Write("runtime_initialized",
                    ("execution_symbol", RuntimeSymbol.Name),
                    ("execution_symbol_id", RuntimeSymbol.Id),
                    ("execution_connection_id", RuntimeSymbol.ConnectionId),
                    ("market_data_symbol", _marketDataSymbol.Name),
                    ("market_data_symbol_id", _marketDataSymbol.Id),
                    ("market_data_connection_id", _marketDataSymbol.ConnectionId),
                    ("market_data_is_execution_symbol", SameSymbol(RuntimeSymbol, _marketDataSymbol)),
                    ("account", RuntimeAccount?.Name),
                    ("account_id", RuntimeAccount?.Id),
                    ("tick_size", _tickSize),
                    ("trading_enabled", _runTradingEnabled),
                    ("shadow_fill_simulation", ShadowFillSimulation),
                    ("instance_max_quantity", Math.Max(1, InstanceMaxQuantity)),
                    ("control_path", Environment.ExpandEnvironmentVariables(ControlPath)),
                    ("worker_poll_ms", Math.Max(100, WorkerPollMs)),
                    ("book_sample_ms", Math.Max(250, BookSampleMs)),
                    ("quote_freshness_ms", Math.Max(250, QuoteFreshnessMs)),
                    ("ll_book_lookback_seconds", Math.Max(10, BookLookbackSeconds)),
                    ("ll_event_z_threshold", Math.Max(1.5, EventZThreshold)),
                    ("ll_cluster_min_events", Math.Max(2, ClusterMinEvents)),
                    ("ll_cluster_ticks", Math.Max(1, ClusterTicks)),
                    ("ll_cluster_seconds", Math.Max(15, ClusterSeconds)),
                    ("ll_confirm_move_ticks", Math.Max(2, ConfirmMoveTicks)),
                    ("ll_confirm_seconds", Math.Max(0, ConfirmSeconds)),
                    ("ll_failure_buffer_ticks", Math.Max(0, FailureBufferTicks)),
                    ("ll_failure_confirm_ticks", Math.Max(2, FailureConfirmTicks)),
                    ("ll_failure_seconds", Math.Max(0, FailureSeconds)));
                LogOperator("INFO", $"Initialized exec={RuntimeSymbol.Name}, data={_marketDataSymbol.Name}, "
                    + $"account={RuntimeAccount?.Name ?? "none"}, mode={(_runTradingEnabled ? "LIVE" : "SHADOW")}.");
                SaveCheckpoint(force: true, runtimeState: "Running");
            }
            catch (Exception ex)
            {
                Log($"[Kahn] ERR: initialization failed: {ex.Message}", StrategyLoggingLevel.Error);
                try { _decisions?.Write("runtime_start_error", ("message", ex.Message)); } catch { }
                Stop();
            }
        }

        protected override void OnStop()
            => Shutdown("runtime_stopped");

        protected override void OnRemove()
            => Shutdown("runtime_removed");

        private void Worker()
        {
            if (!_running || Interlocked.Exchange(ref _workerBusy, 1) != 0)
                return;
            try
            {
                DateTimeOffset now = DateTimeOffset.UtcNow;
                DrainBrokerEvents();
                LoadPlan();
                if (ProcessControl(now))
                {
                    ReconcileLivePosition(DateTime.UtcNow);
                    SaveCheckpoint(force: true, runtimeState: _running ? "Running" : "Stopped");
                    return;
                }

                if (!ReconcileLivePosition(now.UtcDateTime))
                {
                    SaveCheckpoint(force: true, runtimeState: "RecoveryActionRequired");
                    return;
                }

                ProcessBookSample(now.UtcDateTime);

                if (_plan != null && _state != null && _plan.IsActiveAt(now))
                {
                    foreach (CampaignEvidence evidence in DrainMarketEvents())
                        ProcessEvidence(evidence, now);
                    foreach (CampaignEvidence evidence in _evidenceInbox.ReadNewEvents(message => LogOperator("INFO", message)))
                        ProcessEvidence(evidence, now);
                }

                ReconcileLivePosition(DateTime.UtcNow);
                SaveCheckpoint(force: false, runtimeState: _running ? "Running" : "Stopped");
            }
            catch (Exception ex)
            {
                LogOperator("ERR", $"Worker failed: {ex.Message}", error: true);
                try { _decisions?.Write("worker_error", ("message", ex.Message)); } catch { }
            }
            finally
            {
                Interlocked.Exchange(ref _workerBusy, 0);
            }
        }

        private void LoadPlan()
        {
            CampaignPlanLoadResult result = _planStore.LoadIfChanged();
            if (!string.IsNullOrWhiteSpace(result.Error))
            {
                if (!string.Equals(result.Error, _lastPlanError, StringComparison.Ordinal))
                {
                    _lastPlanError = result.Error;
                    _decisions.Write("campaign_parse_error", ("message", result.Error));
                    LogOperator("ERR", $"Campaign parse failed: {result.Error}", error: true);
                }
                return;
            }

            if (!result.Changed)
                return;

            _lastPlanError = null;
            _lastControlError = null;
            _lastControlId = null;
            _lastControlAction = null;
            _lastControlStatus = null;
            _processedControlIds.Clear();
            if (!PlanAdmissible(result.Plan))
                return;

            _plan = result.Plan;
            _state = CampaignState.ForPlan(_plan);
            _decisions.Write("campaign_loaded",
                ("campaign_id", _plan.Id),
                ("campaign_digest", _plan.Digest),
                ("status", _plan.Status),
                ("side", _plan.Side),
                ("probe_quantity", _plan.Sizing.ProbeQuantity),
                ("add_quantity", _plan.Sizing.AddQuantity),
                ("campaign_max_position_quantity", _plan.Sizing.MaxPositionQuantity),
                ("instance_max_quantity", Math.Max(1, InstanceMaxQuantity)),
                ("waypoint_count", _plan.Waypoints.Count),
                ("notes", _plan.Notes));
            LogOperator("INFO", $"Loaded campaign {_plan.Id} ({_plan.Side}).");
            SaveCheckpoint(force: true, runtimeState: "Running");
        }


        private bool ProcessControl(DateTimeOffset now)
        {
            RuntimeControlLoadResult result = _controlStore?.LoadIfChanged();
            if (result == null)
                return false;
            if (!string.IsNullOrWhiteSpace(result.Error))
            {
                if (!string.Equals(result.Error, _lastControlError, StringComparison.Ordinal))
                {
                    _lastControlError = result.Error;
                    _decisions.Write("control_parse_error", ("message", result.Error));
                    LogOperator("ERR", $"Control parse failed: {result.Error}", error: true);
                }
                return false;
            }
            if (!result.Changed || result.Command == null)
                return false;

            _lastControlError = null;
            RuntimeControlCommand command = result.Command;
            _lastControlId = command.Id;
            _lastControlAction = command.Action.ToString();
            _lastControlStatus = "received";

            if (!_processedControlIds.Add(command.Id))
            {
                _lastControlStatus = "duplicate_ignored";
                _decisions.Write("control_duplicate_ignored",
                    ("control_id", command.Id),
                    ("action", command.Action.ToString()),
                    ("reason", command.Reason));
                return true;
            }

            _decisions.Write("control_received",
                ("control_id", command.Id),
                ("action", command.Action.ToString()),
                ("raw_action", command.RawAction),
                ("reason", command.Reason),
                ("created_at", command.CreatedAt.ToString("O", CultureInfo.InvariantCulture)),
                ("campaign_id", _plan?.Id),
                ("campaign_active", _plan?.IsActiveAt(now) ?? false),
                ("phase", _state?.Phase.ToString()),
                ("position_quantity", CurrentPosition().Quantity));
            LogOperator("INFO", $"Control {command.Action} received ({command.Id}).");

            return command.Action switch
            {
                RuntimeControlAction.Flat => HandleFlatControl(command, now),
                RuntimeControlAction.Cancel => HandleCancelControl(command, now),
                _ => false,
            };
        }

        private bool HandleCancelControl(RuntimeControlCommand command, DateTimeOffset now)
        {
            bool ambiguous = false;
            RuntimePosition position = _runTradingEnabled
                ? LivePosition(out ambiguous)
                : CurrentPosition();
            bool hasAmbiguousLivePosition = _runTradingEnabled && ambiguous;
            if (hasAmbiguousLivePosition || !position.IsFlat)
            {
                _lastControlStatus = "rejected_position_exists";
                _decisions.Write("control_cancel_rejected",
                    ("control_id", command.Id),
                    ("reason", hasAmbiguousLivePosition
                        ? "ambiguous_bound_positions_use_flat"
                        : "position_exists_use_flat"),
                    ("campaign_id", _plan?.Id),
                    ("position_id", position.PositionId),
                    ("position_quantity", position.Quantity));
                LogOperator("ERR", "CANCEL rejected: bound position exists; use FLAT to close exposure.", error: true);
                return true;
            }

            _gateway?.CancelRuntimeOrders("order_cancel_control");
            RetireCurrentCampaign(command, now, "operator_cancel");
            _lastControlStatus = "accepted";
            _decisions.Write("control_cancel_completed",
                ("control_id", command.Id),
                ("campaign_id", _plan?.Id),
                ("phase", _state?.Phase.ToString()),
                ("reason", command.Reason),
                ("working_order_count", BoundWorkingOrders().Count));
            LogOperator("INFO", $"CANCEL retired campaign {_plan?.Id ?? "-"}.");
            return true;
        }

        private bool HandleFlatControl(RuntimeControlCommand command, DateTimeOffset now)
        {
            _gateway?.CancelRuntimeOrders("order_cancel_control");
            RuntimePosition[] positions = _runTradingEnabled
                ? BoundLivePositions()
                : ShadowPositions();

            if (positions.Length == 0)
            {
                RetireCurrentCampaign(command, now, "operator_flat_already_flat");
                _lastControlStatus = "accepted_already_flat";
                _decisions.Write("control_flat_completed",
                    ("control_id", command.Id),
                    ("campaign_id", _plan?.Id),
                    ("reason", command.Reason),
                    ("result", "already_flat"),
                    ("working_order_count", BoundWorkingOrders().Count));
                LogOperator("INFO", $"FLAT accepted for {_plan?.Id ?? "-"}: already flat.");
                return true;
            }

            foreach (RuntimePosition position in positions)
            {
                PolicyDecision decision = ControlDecision(
                    command,
                    PolicyAction.Flatten,
                    "operator_flatten",
                    Math.Max(1, (int)Math.Ceiling(position.Quantity)));
                CampaignPlan effectivePlan = PlanForControl(command, position);
                GatewayResult result = _gateway.Execute(
                    decision,
                    effectivePlan,
                    position,
                    SnapshotMarket(now.UtcDateTime));
                if (!result.Accepted)
                {
                    _lastControlStatus = "rejected_execution";
                    _decisions.Write("control_flat_rejected",
                        ("control_id", command.Id),
                        ("campaign_id", _plan?.Id),
                        ("position_id", position.PositionId),
                        ("position_quantity", position.Quantity),
                        ("message", result.Message),
                        ("requires_operator_action", result.RequiresOperatorAction));
                    LogOperator("ERR", $"FLAT rejected: {result.Message}", error: true);
                    return true;
                }
            }

            if (_runTradingEnabled)
                _liveSettleUntilUtc = DateTime.UtcNow.AddSeconds(5);
            RetireCurrentCampaign(command, now, "operator_flatten");
            _lastControlStatus = "accepted";
            _decisions.Write("control_flat_completed",
                ("control_id", command.Id),
                ("campaign_id", _plan?.Id),
                ("reason", command.Reason),
                ("result", "close_submitted"),
                ("position_count", positions.Length),
                ("working_order_count", BoundWorkingOrders().Count));
            LogOperator("RISK", $"FLAT accepted for {_plan?.Id ?? "-"}; close submitted for {positions.Length} position(s).");
            return true;
        }

        private RuntimePosition[] ShadowPositions()
        {
            RuntimePosition position = CurrentPosition();
            return position.IsFlat ? Array.Empty<RuntimePosition>() : new[] { position };
        }

        private void RetireCurrentCampaign(RuntimeControlCommand command,
            DateTimeOffset now,
            string reasonCode)
        {
            if (_state == null || _plan == null)
                return;
            _state.ApplyDecision(ControlDecision(
                    command,
                    PolicyAction.Retire,
                    reasonCode,
                    Math.Max(0, _state.SimulatedPositionQuantity)),
                _plan,
                simulateAcceptedDecisions: true,
                appliedAt: now);
            _decisions.Write("control_retired_campaign",
                ("control_id", command.Id),
                ("campaign_id", _plan.Id),
                ("reason_code", reasonCode),
                ("phase", _state.Phase.ToString()));
        }

        private static PolicyDecision ControlDecision(RuntimeControlCommand command,
            PolicyAction action,
            string reasonCode,
            int quantity)
            => new()
            {
                Action = action,
                Policy = "control",
                ReasonCode = reasonCode,
                Detail = command?.Reason,
                Quantity = quantity,
                EvidenceId = command?.Id,
                Priority = DecisionResolver.PriorityFor(action),
            };

        private CampaignPlan PlanForControl(RuntimeControlCommand command,
            RuntimePosition position)
        {
            if (_plan != null
                && (position == null || position.IsFlat || _plan.Side == position.Direction))
            {
                return _plan;
            }

            CampaignSide side = position == null || position.IsFlat
                ? _plan?.Side ?? CampaignSide.Long
                : position.Direction;
            int quantity = Math.Max(1, (int)Math.Ceiling(position?.Quantity ?? 1));
            return new CampaignPlan
            {
                Id = _plan?.Id ?? $"control-{command?.Id ?? Guid.NewGuid().ToString("N")}",
                Side = side,
                Sizing = new CampaignSizing
                {
                    ProbeQuantity = 1,
                    AddQuantity = 1,
                    MaxPositionQuantity = Math.Max(quantity, Math.Max(1, InstanceMaxQuantity)),
                },
            };
        }

        private bool PlanAdmissible(CampaignPlan plan)
        {
            if (plan == null)
                return false;
            int instanceMax = Math.Max(1, InstanceMaxQuantity);
            if (plan.Sizing.MaxPositionQuantity > instanceMax)
            {
                _decisions.Write("campaign_rejected",
                    ("campaign_id", plan.Id),
                    ("reason", "plan_max_exceeds_instance_max"),
                    ("plan_max_position_quantity", plan.Sizing.MaxPositionQuantity),
                    ("instance_max_quantity", instanceMax));
                LogOperator("ERR", $"Campaign {plan.Id} rejected: plan max "
                    + $"{plan.Sizing.MaxPositionQuantity} exceeds instance max {instanceMax}.",
                    error: true);
                return false;
            }

            if (!_runTradingEnabled)
                return true;

            if (_state != null && _state.HasPosition)
            {
                _decisions.Write("campaign_rejected",
                    ("campaign_id", plan.Id),
                    ("reason", "cannot_replace_live_campaign_with_position"),
                    ("active_campaign_id", _plan?.Id),
                    ("position_quantity", _state.SimulatedPositionQuantity));
                LogOperator("ERR", $"Campaign {plan.Id} rejected: existing live campaign "
                    + $"{_plan?.Id ?? "unknown"} still has position state.",
                    error: true);
                return false;
            }

            RuntimePosition position = LivePosition(out bool ambiguous);
            if (ambiguous || !position.IsFlat)
            {
                _decisions.Write("campaign_rejected",
                    ("campaign_id", plan.Id),
                    ("reason", ambiguous ? "ambiguous_bound_positions" : "bound_position_not_flat"),
                    ("position_id", position.PositionId),
                    ("position_quantity", position.Quantity));
                LogOperator("ERR", $"Campaign {plan.Id} rejected: bound position is not cleanly flat.",
                    error: true);
                return false;
            }

            int working = BoundWorkingOrders().Count;
            if (working > 0)
            {
                _decisions.Write("campaign_rejected",
                    ("campaign_id", plan.Id),
                    ("reason", "bound_working_orders_exist"),
                    ("working_order_count", working));
                LogOperator("ERR", $"Campaign {plan.Id} rejected: {working} bound working orders exist.",
                    error: true);
                return false;
            }

            return true;
        }

        private void ProcessEvidence(CampaignEvidence evidence, DateTimeOffset now)
        {
            if (_plan == null || _state == null || _state.IsRetired || !_plan.IsActiveAt(now))
                return;

            CampaignContext context = new(_plan, _state, _tickSize, now);
            PolicyDecision decision = _policyEngine.Evaluate(context, evidence);
            if (!_state.ShouldEmit(decision, now, TimeSpan.FromSeconds(5)))
                return;

            _decisions.Write("policy_decision",
                ("campaign_id", _plan.Id),
                ("campaign_digest", _plan.Digest),
                ("phase_before", _state.Phase),
                ("action", decision.Action),
                ("policy", decision.Policy),
                ("reason_code", decision.ReasonCode),
                ("detail", decision.Detail),
                ("priority", decision.Priority),
                ("quantity", decision.Quantity),
                ("waypoint_id", decision.WaypointId),
                ("risk_anchor", decision.RiskAnchor),
                ("risk_anchor_evidence_id", decision.RiskAnchorEvidenceId),
                ("expires_at", decision.ExpiresAt?.ToString("O", CultureInfo.InvariantCulture)),
                ("evidence_id", evidence.EventId),
                ("evidence_source", evidence.Source),
                ("evidence_kind", evidence.Kind),
                ("evidence_side", evidence.Side),
                ("evidence_price", evidence.Price),
                ("evidence_range", evidence.Range),
                ("evidence_delta", evidence.Delta),
                ("evidence_volume", evidence.Volume),
                ("evidence_score", evidence.Score),
                ("position_before", CurrentPosition().Quantity),
                ("simulated_position_before", _state.SimulatedPositionQuantity));

            GatewayResult execution = ExecuteDecision(decision, now);
            if (!execution.Accepted && RequiresBrokerAction(decision.Action))
            {
                _decisions.Write("policy_execution_rejected",
                    ("campaign_id", _plan.Id),
                    ("action", decision.Action.ToString()),
                    ("policy", decision.Policy),
                    ("reason_code", decision.ReasonCode),
                    ("message", execution.Message),
                    ("requires_operator_action", execution.RequiresOperatorAction));
                LogOperator("ERR", $"Execution rejected: {decision.Action} {decision.Policy}/"
                    + $"{decision.ReasonCode}: {execution.Message}", error: true);
                SaveCheckpoint(force: true, runtimeState: execution.RequiresOperatorAction
                    ? "RecoveryActionRequired"
                    : "Running");
                return;
            }

            bool simulateAccepted = !_runTradingEnabled ? ShadowFillSimulation : true;
            _state.ApplyDecision(decision, _plan, simulateAccepted, now);
            LogDecisionForOperator(decision, execution);

            _decisions.Write("campaign_state",
                ("campaign_id", _plan.Id),
                ("phase", _state.Phase),
                ("simulated_position_quantity", _state.SimulatedPositionQuantity),
                ("live_position_quantity", LivePosition(out _).Quantity),
                ("active_risk_anchor", _state.ActiveRiskAnchor),
                ("active_risk_anchor_evidence_id", _state.ActiveRiskAnchorEvidenceId),
                ("root_risk_anchor", _state.RootRiskAnchor),
                ("root_risk_anchor_evidence_id", _state.RootRiskAnchorEvidenceId),
                ("armed_waypoint_id", _state.ArmedWaypointId),
                ("suppress_adds_until", _state.SuppressAddsUntil?.ToString("O", CultureInfo.InvariantCulture)),
                ("execution_accepted", execution.Accepted),
                ("execution_shadow", execution.Shadow),
                ("execution_order_id", execution.OrderId),
                ("execution_message", execution.Message));

            SaveCheckpoint(force: true, runtimeState: "Running");
        }

        private GatewayResult ExecuteDecision(PolicyDecision decision, DateTimeOffset now)
        {
            if (!RequiresBrokerAction(decision.Action))
                return new GatewayResult { Accepted = true, Message = "state-only decision" };
            if (_gateway == null)
                return new GatewayResult
                {
                    Accepted = false,
                    RequiresOperatorAction = true,
                    Message = "gateway is unavailable",
                };

            RuntimePosition position = CurrentPosition();
            ExecutableMarket market = SnapshotMarket(now.UtcDateTime);
            GatewayResult result = _gateway.Execute(decision, _plan, position, market);
            if (_runTradingEnabled && result.Accepted)
                _liveSettleUntilUtc = DateTime.UtcNow.AddSeconds(5);
            return result;
        }

        private static bool RequiresBrokerAction(PolicyAction action)
            => action is PolicyAction.AllowProbe
                or PolicyAction.AllowAdd
                or PolicyAction.Reduce
                or PolicyAction.Flatten
                or PolicyAction.Retire;

        private void LogDecisionForOperator(PolicyDecision decision, GatewayResult execution)
        {
            string bucket = decision.Action switch
            {
                PolicyAction.AllowProbe => "ENTRY",
                PolicyAction.AllowAdd => "ADD",
                PolicyAction.Reduce => "EXIT",
                PolicyAction.Flatten => "RISK",
                PolicyAction.Retire => "EXIT",
                PolicyAction.TightenRisk => "RISK",
                _ => "INFO",
            };
            string mode = execution.Shadow ? "shadow" : (_runTradingEnabled ? "live" : "state");
            LogOperator(bucket, $"{_plan?.Id ?? "no-campaign"} {decision.Action} "
                + $"{decision.Policy}/{decision.ReasonCode} qty={decision.Quantity?.ToString(CultureInfo.InvariantCulture) ?? "-"} "
                + $"wp={decision.WaypointId ?? "-"} mode={mode}.");
        }

        private IReadOnlyList<CampaignEvidence> DrainMarketEvents()
        {
            List<CampaignEvidence> result = new();
            while (_marketEvents.TryDequeue(out CampaignEvidence evidence))
                result.Add(evidence);
            return result;
        }

        private void ProcessBookSample(DateTime nowUtc)
        {
            if (_liveEvidence == null || _marketDataSymbol == null)
                return;
            if ((nowUtc - _lastBookSampleUtc).TotalMilliseconds < Math.Max(250, BookSampleMs))
                return;
            _lastBookSampleUtc = nowUtc;

            BookSampleDiagnostic diagnostic = new()
            {
                SymbolBid = double.IsFinite(_marketDataSymbol.Bid) ? _marketDataSymbol.Bid : null,
                SymbolAsk = double.IsFinite(_marketDataSymbol.Ask) ? _marketDataSymbol.Ask : null,
            };
            bool l2Fresh;
            lock (_marketGate)
            {
                diagnostic.LastL2Utc = _lastL2Utc == DateTime.MinValue ? null : _lastL2Utc;
                diagnostic.L2AgeMs = _lastL2Utc == DateTime.MinValue
                    ? null
                    : Math.Max(0, (nowUtc - _lastL2Utc).TotalMilliseconds);
                l2Fresh = _lastL2Utc != DateTime.MinValue
                    && (nowUtc - _lastL2Utc).TotalSeconds <= Math.Max(1, BookFreshnessSec);
            }

            if (!l2Fresh)
            {
                MarkBookUnusable("l2_heartbeat_stale", diagnostic);
                return;
            }

            if (!TryBuildDepthSnapshot(nowUtc, out LlBookDepthSnapshot depth, diagnostic))
            {
                MarkBookUnusable(diagnostic.Reason ?? "dom_unusable", diagnostic);
                return;
            }

            if (_evidenceState == "BookUnusable")
            {
                _decisions.Write("book_usable_recovered",
                    ("market_data_symbol", _marketDataSymbol.Name),
                    ("bid_levels", diagnostic.BidLevels),
                    ("ask_levels", diagnostic.AskLevels));
                LogOperator("INFO", "L2 book usable again.");
            }

            StartEvidenceEpochIfNeeded(nowUtc);
            IReadOnlyList<LlEvidenceTransition> transitions = _liveEvidence.Process(depth);
            _evidenceEpochSampleCount++;
            CompleteEvidenceWarmupIfReady(nowUtc);
            _evidenceState = _evidenceWarmupComplete ? "Ready" : "Warming";

            foreach (LlEvidenceTransition transition in transitions)
            {
                LogLiveEvidenceTransition(transition);
                if (!_evidenceWarmupComplete)
                    continue;
                if (TryTranslateLiveEvidence(transition, out CampaignEvidence evidence)
                    && _plan != null
                    && _state != null
                    && _plan.IsActiveAt(evidence.Timestamp))
                {
                    ProcessEvidence(evidence, DateTimeOffset.UtcNow);
                }
            }
        }

        private void MarkBookUnusable(string reason, BookSampleDiagnostic diagnostic)
        {
            _evidenceState = "BookUnusable";
            string signature = $"{reason}|{diagnostic?.L2AgeMs}|{diagnostic?.BidLevels}|{diagnostic?.AskLevels}";
            if (string.Equals(signature, _lastBookHealthSignature, StringComparison.Ordinal))
                return;
            _lastBookHealthSignature = signature;
            _decisions.Write("book_unusable",
                ("reason", reason),
                ("market_data_symbol", _marketDataSymbol?.Name),
                ("last_l2_utc", diagnostic?.LastL2Utc?.ToString("O", CultureInfo.InvariantCulture)),
                ("l2_age_ms", diagnostic?.L2AgeMs),
                ("bid_levels", diagnostic?.BidLevels),
                ("ask_levels", diagnostic?.AskLevels),
                ("symbol_bid", diagnostic?.SymbolBid),
                ("symbol_ask", diagnostic?.SymbolAsk),
                ("dom_bid", diagnostic?.DomBid),
                ("dom_ask", diagnostic?.DomAsk),
                ("error", diagnostic?.Error));
        }

        private void StartEvidenceEpochIfNeeded(DateTime nowUtc)
        {
            if (_evidenceEpochStartedUtc != DateTime.MinValue)
                return;
            _evidenceEpochStartedUtc = nowUtc;
            _evidenceEpochSampleCount = 0;
            _evidenceWarmupComplete = false;
            _evidenceState = "Warming";
            _decisions.Write("evidence_warmup_started",
                ("reason", _evidenceEpochReason),
                ("started_utc", nowUtc.ToString("O", CultureInfo.InvariantCulture)),
                ("required_seconds", EvidenceWarmupSeconds),
                ("required_samples", EvidenceWarmupRequiredSamples));
            LogOperator("INFO", $"Evidence epoch warming for {EvidenceWarmupSeconds}s; reason={_evidenceEpochReason}.");
        }

        private void CompleteEvidenceWarmupIfReady(DateTime nowUtc)
        {
            if (_evidenceWarmupComplete
                || _evidenceEpochStartedUtc == DateTime.MinValue
                || _evidenceEpochSampleCount < EvidenceWarmupRequiredSamples
                || (nowUtc - _evidenceEpochStartedUtc).TotalSeconds < EvidenceWarmupSeconds)
            {
                return;
            }

            _evidenceWarmupComplete = true;
            _decisions.Write("evidence_warmup_completed",
                ("reason", _evidenceEpochReason),
                ("started_utc", _evidenceEpochStartedUtc.ToString("O", CultureInfo.InvariantCulture)),
                ("completed_utc", nowUtc.ToString("O", CultureInfo.InvariantCulture)),
                ("sample_count", _evidenceEpochSampleCount),
                ("required_seconds", EvidenceWarmupSeconds),
                ("required_samples", EvidenceWarmupRequiredSamples));
            LogOperator("INFO", $"Evidence epoch ready after {(nowUtc - _evidenceEpochStartedUtc).TotalSeconds:F1}s.");
        }

        private int EvidenceWarmupSeconds
            => Math.Max(10, BookLookbackSeconds);

        private int EvidenceWarmupRequiredSamples
            => Math.Max(5, (int)Math.Ceiling(
                EvidenceWarmupSeconds * 1000.0 / Math.Max(250, BookSampleMs)));

        private double EvidenceWarmupRemainingSeconds(DateTime nowUtc)
        {
            if (_evidenceWarmupComplete)
                return 0;
            if (_evidenceEpochStartedUtc == DateTime.MinValue)
                return EvidenceWarmupSeconds;
            return Math.Max(0, EvidenceWarmupSeconds - (nowUtc - _evidenceEpochStartedUtc).TotalSeconds);
        }

        private void LogLiveEvidenceTransition(LlEvidenceTransition transition)
        {
            _decisions.Write("ll_transition",
                ("kind", transition.Kind.ToString()),
                ("reason", transition.Reason),
                ("evidence_state", _evidenceState),
                ("actionable", _evidenceWarmupComplete),
                ("event_utc", transition.TimeUtc.ToString("O", CultureInfo.InvariantCulture)),
                ("mid_tick", transition.CurrentMidTick),
                ("band_id", transition.Band?.Id),
                ("band_role", transition.Band?.Role.ToString()),
                ("band_side", transition.Band?.Side.ToString()),
                ("band_source", transition.Band?.Source.ToString()),
                ("band_state", transition.Band?.State.ToString()),
                ("band_min_tick", transition.Band?.MinTick),
                ("band_max_tick", transition.Band?.MaxTick),
                ("band_score", transition.Band?.Score),
                ("candidate_id", transition.Candidate?.Id),
                ("candidate_side", transition.Candidate?.Side.ToString()),
                ("candidate_min_tick", transition.Candidate?.MinTick),
                ("candidate_max_tick", transition.Candidate?.MaxTick),
                ("candidate_score", transition.Candidate?.Score));
        }

        private bool TryTranslateLiveEvidence(LlEvidenceTransition transition,
            out CampaignEvidence evidence)
        {
            evidence = null;
            if (transition?.Band == null || transition.Band.Role != LlEvidenceRole.Rail)
                return false;

            EvidenceKind kind = transition.Kind switch
            {
                LlEvidenceTransitionKind.RailOwned => EvidenceKind.RailOwned,
                LlEvidenceTransitionKind.RailHeld => EvidenceKind.RailHeld,
                LlEvidenceTransitionKind.RailFailed => EvidenceKind.RailFailed,
                LlEvidenceTransitionKind.RailTested => EvidenceKind.RailTested,
                _ => EvidenceKind.Unknown,
            };
            if (kind == EvidenceKind.Unknown)
                return false;

            PriceRange range = new()
            {
                Lower = transition.Band.MinTick * _tickSize,
                Upper = transition.Band.MaxTick * _tickSize,
            };
            string railId = transition.Band.Id.ToString(CultureInfo.InvariantCulture);
            evidence = new CampaignEvidence
            {
                EventId = $"live-ll-{railId}-{transition.Kind}-{transition.TimeUtc.Ticks}",
                Timestamp = new DateTimeOffset(transition.TimeUtc, TimeSpan.Zero),
                Source = EvidenceSource.LevelLedger,
                Kind = kind,
                Side = MapSide(transition.Band.Side),
                Price = transition.CurrentMidTick * _tickSize,
                Range = range,
                RailId = railId,
                Score = transition.Band.Score,
                Note = $"{transition.Band.Source}:{transition.Reason}",
            };
            return true;
        }

        private static EvidenceSide MapSide(LlEvidenceSide side)
            => side == LlEvidenceSide.Demand
                ? EvidenceSide.Demand
                : EvidenceSide.Supply;

        private void Symbol_NewQuote(Symbol symbol, Quote quote)
        {
            if (quote == null)
                return;

            double bid = double.IsFinite(quote.Bid) && quote.Bid > 0 ? quote.Bid : double.NaN;
            double ask = double.IsFinite(quote.Ask) && quote.Ask > 0 ? quote.Ask : double.NaN;
            double price = double.NaN;
            if (double.IsFinite(bid) && double.IsFinite(ask))
                price = (bid + ask) / 2.0;
            else if (double.IsFinite(bid))
                price = bid;
            else if (double.IsFinite(ask))
                price = ask;
            if (!double.IsFinite(price))
                return;

            DateTime now = DateTime.UtcNow;
            lock (_marketGate)
            {
                _latestBid = bid;
                _latestAsk = ask;
                _lastQuoteUtc = now;
            }

            _marketEvents.Enqueue(new CampaignEvidence
            {
                EventId = "quote-" + now.Ticks.ToString(CultureInfo.InvariantCulture),
                Timestamp = new DateTimeOffset(now, TimeSpan.Zero),
                Source = EvidenceSource.Price,
                Kind = EvidenceKind.PriceTouch,
                Side = EvidenceSide.None,
                Price = price,
            });

            while (_marketEvents.Count > 2000 && _marketEvents.TryDequeue(out _))
            {
            }
        }

        private void Symbol_NewLevel2(Symbol symbol, Level2Quote l2, DOMQuote dom)
        {
            if (l2 != null
                && (string.Equals(l2.Id, "generated_from_level1", StringComparison.OrdinalIgnoreCase)
                    || !double.IsFinite(l2.Price)
                    || !double.IsFinite(l2.Size)))
            {
                return;
            }
            lock (_marketGate)
                _lastL2Utc = DateTime.UtcNow;
        }

        private bool TryBuildDepthSnapshot(DateTime nowUtc,
            out LlBookDepthSnapshot snapshot,
            BookSampleDiagnostic diagnostic)
        {
            snapshot = null;
            try
            {
                DepthOfMarketAggregatedCollections dom = _marketDataSymbol.DepthOfMarket?
                    .GetDepthOfMarketAggregatedCollections(_domParameters);
                if (dom == null)
                {
                    diagnostic.Reason = "dom_unavailable";
                    return false;
                }
                diagnostic.BidLevels = dom.Bids?.Length ?? 0;
                diagnostic.AskLevels = dom.Asks?.Length ?? 0;
                diagnostic.DomBid = NullableFinite(FirstValidPrice(dom.Bids));
                diagnostic.DomAsk = NullableFinite(FirstValidPrice(dom.Asks));
                if (diagnostic.BidLevels == 0 && diagnostic.AskLevels == 0)
                {
                    diagnostic.Reason = "dom_empty";
                    return false;
                }
                if (!L1Agrees(diagnostic))
                {
                    diagnostic.Reason = "l1_dom_mismatch";
                    return false;
                }
                snapshot = new LlBookDepthSnapshot
                {
                    TimeUtc = nowUtc,
                    Bids = ConvertLevels(dom.Bids),
                    Asks = ConvertLevels(dom.Asks),
                };
                return true;
            }
            catch (Exception ex)
            {
                diagnostic.Reason = "dom_read_error";
                diagnostic.Error = ex.Message;
                _decisions.Write("book_sample_error", ("message", ex.Message));
                return false;
            }
        }

        private bool L1Agrees(BookSampleDiagnostic diagnostic)
        {
            if (diagnostic.DomBid.HasValue && diagnostic.SymbolBid.HasValue
                && Math.Abs(PriceToTick(diagnostic.DomBid.Value)
                    - PriceToTick(diagnostic.SymbolBid.Value)) > L1ToleranceTicks)
                return false;
            if (diagnostic.DomAsk.HasValue && diagnostic.SymbolAsk.HasValue
                && Math.Abs(PriceToTick(diagnostic.DomAsk.Value)
                    - PriceToTick(diagnostic.SymbolAsk.Value)) > L1ToleranceTicks)
                return false;
            return true;
        }

        private static double? NullableFinite(double value)
            => double.IsFinite(value) ? value : null;

        private static double FiniteOrZero(double value)
            => double.IsFinite(value) ? value : 0.0;

        private static IReadOnlyList<LlDepthLevelSnapshot> ConvertLevels(Level2Item[] levels)
            => (levels ?? Array.Empty<Level2Item>())
                .Where(l => l != null && double.IsFinite(l.Price) && l.Price > 0
                    && double.IsFinite(l.Size) && l.Size > 0)
                .Take(30)
                .Select(l => new LlDepthLevelSnapshot { Price = l.Price, Size = l.Size })
                .ToArray();

        private static double FirstValidPrice(Level2Item[] levels)
            => (levels ?? Array.Empty<Level2Item>())
                .FirstOrDefault(l => l != null && double.IsFinite(l.Price) && l.Price > 0
                    && double.IsFinite(l.Size) && l.Size > 0)?.Price ?? double.NaN;

        private ExecutableMarket SnapshotMarket(DateTime nowUtc)
        {
            lock (_marketGate)
            {
                bool fresh = _lastQuoteUtc != DateTime.MinValue
                    && (nowUtc - _lastQuoteUtc).TotalMilliseconds <= Math.Max(250, QuoteFreshnessMs);
                return new ExecutableMarket
                {
                    TimeUtc = nowUtc,
                    Bid = fresh ? _latestBid : double.NaN,
                    Ask = fresh ? _latestAsk : double.NaN,
                    QuoteUtc = _lastQuoteUtc,
                };
            }
        }

        private void SaveCheckpoint(bool force, string runtimeState)
        {
            DateTime now = DateTime.UtcNow;
            if (!force && now - _lastCheckpointUtc < TimeSpan.FromSeconds(1))
                return;
            _lastCheckpointUtc = now;

            double bid;
            double ask;
            DateTime quoteUtc;
            DateTime l2Utc;
            lock (_marketGate)
            {
                bid = _latestBid;
                ask = _latestAsk;
                quoteUtc = _lastQuoteUtc;
                l2Utc = _lastL2Utc;
            }

            RuntimePosition position = CurrentPosition();
            _checkpointStore?.Save(new RuntimeCheckpointData
            {
                RuntimeState = runtimeState,
                CampaignId = _plan?.Id,
                CampaignDigest = _plan?.Digest,
                CampaignStatus = _plan?.Status,
                ControlPath = Environment.ExpandEnvironmentVariables(ControlPath),
                LastControlId = _lastControlId,
                LastControlAction = _lastControlAction,
                LastControlStatus = _lastControlStatus,
                Symbol = RuntimeSymbol?.Name,
                SymbolId = RuntimeSymbol?.Id,
                ConnectionId = RuntimeSymbol?.ConnectionId,
                ExecutionSymbol = RuntimeSymbol?.Name,
                ExecutionSymbolId = RuntimeSymbol?.Id,
                ExecutionConnectionId = RuntimeSymbol?.ConnectionId,
                MarketDataSymbol = _marketDataSymbol?.Name,
                MarketDataSymbolId = _marketDataSymbol?.Id,
                MarketDataConnectionId = _marketDataSymbol?.ConnectionId,
                Account = RuntimeAccount?.Name,
                AccountId = RuntimeAccount?.Id,
                TradingEnabled = _runTradingEnabled,
                ShadowFillSimulation = ShadowFillSimulation,
                CampaignProbeQuantity = _plan?.Sizing?.ProbeQuantity,
                CampaignAddQuantity = _plan?.Sizing?.AddQuantity,
                CampaignMaxPositionQuantity = _plan?.Sizing?.MaxPositionQuantity,
                InstanceMaxQuantity = Math.Max(1, InstanceMaxQuantity),
                WorkerPollMs = Math.Max(100, WorkerPollMs),
                BookSampleMs = Math.Max(250, BookSampleMs),
                BookFreshnessSec = Math.Max(1, BookFreshnessSec),
                QuoteFreshnessMs = Math.Max(250, QuoteFreshnessMs),
                LlBookLookbackSeconds = Math.Max(10, BookLookbackSeconds),
                LlEventZThreshold = Math.Max(1.5, EventZThreshold),
                LlClusterMinEvents = Math.Max(2, ClusterMinEvents),
                LlClusterTicks = Math.Max(1, ClusterTicks),
                LlClusterSeconds = Math.Max(15, ClusterSeconds),
                LlConfirmMoveTicks = Math.Max(2, ConfirmMoveTicks),
                LlConfirmSeconds = Math.Max(0, ConfirmSeconds),
                LlFailureBufferTicks = Math.Max(0, FailureBufferTicks),
                LlFailureConfirmTicks = Math.Max(2, FailureConfirmTicks),
                LlFailureSeconds = Math.Max(0, FailureSeconds),
                TickSize = FiniteOrZero(_tickSize),
                EvidenceState = _evidenceState,
                EvidenceEpochReason = _evidenceEpochReason,
                EvidenceEpochStartedUtc = _evidenceEpochStartedUtc == DateTime.MinValue
                    ? null
                    : _evidenceEpochStartedUtc.ToString("O", CultureInfo.InvariantCulture),
                EvidenceSampleCount = _evidenceEpochSampleCount,
                EvidenceWarmupSeconds = EvidenceWarmupSeconds,
                EvidenceWarmupRequiredSamples = EvidenceWarmupRequiredSamples,
                EvidenceWarmupRemainingSeconds = FiniteOrZero(EvidenceWarmupRemainingSeconds(now)),
                Phase = _state?.Phase.ToString(),
                SimulatedPositionQuantity = _state?.SimulatedPositionQuantity ?? 0,
                PositionId = position.PositionId,
                PositionDirection = position.IsFlat ? null : position.Direction.ToString(),
                PositionQuantity = FiniteOrZero(position.Quantity),
                PositionAveragePrice = FiniteOrZero(position.AveragePrice),
                BoundWorkingOrderCount = BoundWorkingOrders().Count,
                ArmedWaypointId = _state?.ArmedWaypointId,
                ActiveRiskAnchor = _state?.ActiveRiskAnchor,
                ActiveRiskAnchorEvidenceId = _state?.ActiveRiskAnchorEvidenceId,
                RootRiskAnchor = _state?.RootRiskAnchor,
                RootRiskAnchorEvidenceId = _state?.RootRiskAnchorEvidenceId,
                SuppressAddsUntilUtc = _state?.SuppressAddsUntil?.ToString("O", CultureInfo.InvariantCulture),
                LastDecisionUtc = _state?.LastDecisionUtc == default
                    ? null
                    : _state?.LastDecisionUtc.ToString("O", CultureInfo.InvariantCulture),
                LatestBid = NullableFinite(bid),
                LatestAsk = NullableFinite(ask),
                LastQuoteUtc = quoteUtc == default
                    ? null
                    : quoteUtc.ToString("O", CultureInfo.InvariantCulture),
                LastL2Utc = l2Utc == default
                    ? null
                    : l2Utc.ToString("O", CultureInfo.InvariantCulture),
                DroppedDecisionLogEvents = _decisions?.DroppedCount ?? 0,
            });
        }

        private void DrainBrokerEvents()
        {
            while (_brokerEvents.TryDequeue(out BrokerEvent ev))
            {
                _decisions.Write(ev.EventType,
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
                    ("comment", ev.Comment),
                    ("group_id", ev.GroupId));
                if (ev.EventType == "trade_fill")
                {
                    LogOperator("FILL", $"{ev.Side} qty={ev.Quantity:R} price={ev.Price:R} "
                        + $"order={ev.OrderId ?? "-"} pos={ev.PositionId ?? "-"}.");
                }
            }
        }

        private bool ReconcileLivePosition(DateTime nowUtc)
        {
            RuntimePosition position = CurrentPosition();
            LogPositionIfChanged(position);
            if (!_runTradingEnabled || _state == null)
                return true;

            RuntimePosition live = LivePosition(out bool ambiguous);
            if (nowUtc < _liveSettleUntilUtc)
                return true;

            if (ambiguous)
            {
                LogRecoveryOnce(live, "ambiguous_bound_positions");
                return false;
            }
            if (!live.IsFlat && _plan != null && live.Direction != _plan.Side)
            {
                LogRecoveryOnce(live, "opposite_bound_position");
                return false;
            }
            if (!_state.HasPosition && !live.IsFlat)
            {
                LogRecoveryOnce(live, "orphan_bound_position");
                return false;
            }

            int observed = live.IsFlat
                ? 0
                : Math.Max(1, (int)Math.Round(live.Quantity));
            if (observed != _state.SimulatedPositionQuantity)
            {
                _decisions.Write("position_state_reconciled",
                    ("campaign_id", _plan?.Id),
                    ("from_simulated_quantity", _state.SimulatedPositionQuantity),
                    ("to_live_quantity", observed),
                    ("position_id", live.PositionId));
                _state.ReconcileObservedPositionQuantity(observed, _plan);
            }
            return true;
        }

        private void LogRecoveryOnce(RuntimePosition position, string reason)
        {
            string signature = $"{reason}|{position.PositionId}|{position.Direction}|{position.Quantity:R}|{position.AveragePrice:R}";
            if (string.Equals(signature, _lastRecoverySignature, StringComparison.Ordinal))
                return;
            _lastRecoverySignature = signature;
            _decisions.Write("recovery_action_required",
                ("reason", reason),
                ("campaign_id", _plan?.Id),
                ("position_id", position.PositionId),
                ("side", position.IsFlat ? null : position.Direction.ToString()),
                ("quantity", position.Quantity),
                ("average_price", position.AveragePrice));
            LogOperator("ERR", $"Recovery action required: {reason}; "
                + $"pos={position.Quantity:R} {position.Direction} avg={position.AveragePrice:R}.",
                error: true);
        }

        private void LogPositionIfChanged(RuntimePosition position)
        {
            string signature = position == null || position.IsFlat
                ? "flat"
                : $"{position.PositionId}|{position.Direction}|{position.Quantity:R}|{position.AveragePrice:R}";
            if (string.Equals(signature, _lastPositionSignature, StringComparison.Ordinal))
                return;
            _lastPositionSignature = signature;
            _decisions?.Write("position_reconciled",
                ("position_id", position?.PositionId),
                ("side", position == null || position.IsFlat ? null : position.Direction.ToString()),
                ("quantity", position?.Quantity ?? 0),
                ("average_price", position?.AveragePrice ?? 0));
        }

        private RuntimePosition CurrentPosition()
        {
            if (_runTradingEnabled)
                return LivePosition(out _);
            if (_state == null || _state.SimulatedPositionQuantity <= 0)
                return RuntimePosition.Flat;
            return new RuntimePosition
            {
                Direction = _plan?.Side ?? CampaignSide.Long,
                Quantity = _state.SimulatedPositionQuantity,
            };
        }

        private RuntimePosition LivePosition(out bool ambiguous)
        {
            ambiguous = false;
            if (RuntimeSymbol == null || RuntimeAccount == null)
                return RuntimePosition.Flat;
            RuntimePosition[] positions = BoundLivePositions();
            ambiguous = positions.Length > 1;
            if (positions.Length == 0)
                return RuntimePosition.Flat;
            return positions[0];
        }

        private RuntimePosition[] BoundLivePositions()
        {
            if (RuntimeSymbol == null || RuntimeAccount == null)
                return Array.Empty<RuntimePosition>();
            return Core.Instance.Positions
                .Where(p => SameBoundPair(p.Symbol, p.Account))
                .Select(ToRuntimePosition)
                .ToArray();
        }

        private static RuntimePosition ToRuntimePosition(Position position)
            => new()
            {
                PositionId = position.Id,
                Direction = position.Side == Side.Buy
                    ? CampaignSide.Long
                    : CampaignSide.Short,
                Quantity = position.Quantity,
                AveragePrice = position.OpenPrice,
                LivePosition = position,
            };

        private IReadOnlyList<Order> BoundWorkingOrders()
        {
            if (_gateway != null)
                return _gateway.BoundWorkingOrders();
            if (RuntimeSymbol == null || RuntimeAccount == null)
                return Array.Empty<Order>();
            return Core.Instance.Orders
                .Where(o => SameBoundPair(o.Symbol, o.Account) && o.RemainingQuantity > 0)
                .ToArray();
        }

        private void Subscribe()
        {
            _marketDataSymbol.NewQuote += Symbol_NewQuote;
            _marketDataSymbol.NewLevel2 += Symbol_NewLevel2;
            if (RuntimeAccount == null)
                return;
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
            try { if (_marketDataSymbol != null) _marketDataSymbol.NewQuote -= Symbol_NewQuote; } catch { }
            try { if (_marketDataSymbol != null) _marketDataSymbol.NewLevel2 -= Symbol_NewLevel2; } catch { }
            try { Core.Instance.OrderAdded -= Core_OrderAdded; } catch { }
            try { Core.Instance.OrderRemoved -= Core_OrderRemoved; } catch { }
            try { Core.Instance.TradeAdded -= Core_TradeAdded; } catch { }
            try { Core.Instance.PositionAdded -= Core_PositionChanged; } catch { }
            try { Core.Instance.PositionRemoved -= Core_PositionChanged; } catch { }
            Order[] subscribed;
            lock (_orderSubscriptionGate)
            {
                subscribed = _subscribedOrders.Values.ToArray();
                _subscribedOrders.Clear();
            }
            foreach (Order order in subscribed)
            {
                try { order.Updated -= Order_Updated; } catch { }
            }
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
                _subscribedOrders.Remove(order.Id);
            _brokerEvents.Enqueue(BrokerEvent.FromOrder("order_removed", order));
        }

        private void SubscribeOrder(Order order)
        {
            if (order == null || string.IsNullOrWhiteSpace(order.Id))
                return;
            lock (_orderSubscriptionGate)
            {
                if (_subscribedOrders.TryGetValue(order.Id, out Order prior))
                {
                    if (ReferenceEquals(prior, order))
                        return;
                    try { prior.Updated -= Order_Updated; } catch { }
                }
                _subscribedOrders[order.Id] = order;
                order.Updated += Order_Updated;
            }
        }

        private void Order_Updated(IOrder order)
        {
            if (!SameBoundPair(order?.Symbol, order?.Account))
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
                BrokerUtc = DateTime.UtcNow,
            });
        }

        private void Shutdown(string eventType)
        {
            if (Interlocked.Exchange(ref _shutdownStarted, 1) != 0)
                return;
            _running = false;

            Timer timer = Interlocked.Exchange(ref _workerTimer, null);
            if (timer != null)
            {
                try
                {
                    using ManualResetEvent callbackDone = new(false);
                    bool notifyPending = timer.Dispose(callbackDone);
                    if (notifyPending)
                        callbackDone.WaitOne(TimeSpan.FromSeconds(5));
                }
                catch { }
            }

            try { _gateway?.CancelRuntimeOrdersOnStop(); } catch { }
            Unsubscribe();

            try
            {
                _decisions?.Write(eventType,
                    ("campaign_id", _plan?.Id),
                    ("phase", _state?.Phase.ToString()),
                    ("simulated_position_quantity", _state?.SimulatedPositionQuantity ?? 0),
                    ("live_position_quantity", LivePosition(out _).Quantity));
                SaveCheckpoint(force: true, runtimeState: "Stopped");
            }
            catch { }
            _decisions?.Dispose();
            _decisions = null;
        }

        private void ResetForRun()
        {
            _shutdownStarted = 0;
            _workerBusy = 0;
            _running = false;
            _runTradingEnabled = false;
            _marketDataSymbol = null;
            _gateway = null;
            _controlStore = null;
            _liveEvidence = null;
            _plan = null;
            _state = null;
            _lastPlanError = null;
            _lastControlError = null;
            _lastControlId = null;
            _lastControlAction = null;
            _lastControlStatus = null;
            _processedControlIds.Clear();
            _lastBookHealthSignature = null;
            _lastPositionSignature = null;
            _lastRecoverySignature = null;
            _lastBookSampleUtc = DateTime.MinValue;
            _lastQuoteUtc = DateTime.MinValue;
            _lastL2Utc = DateTime.MinValue;
            _liveSettleUntilUtc = DateTime.MinValue;
            _evidenceEpochStartedUtc = DateTime.MinValue;
            _evidenceEpochSampleCount = 0;
            _evidenceWarmupComplete = false;
            _evidenceState = "AwaitingBook";
            _evidenceEpochReason = "startup";
            while (_marketEvents.TryDequeue(out _))
            {
            }
            while (_brokerEvents.TryDequeue(out _))
            {
            }
            lock (_orderSubscriptionGate)
                _subscribedOrders.Clear();
        }

        private void LogOperator(string message, bool error = false)
            => LogOperator(error ? "ERR" : "INFO", message, error);

        private void LogOperator(string bucket, string message, bool error = false)
        {
            string text = $"[Kahn] {bucket}: {message}";
            if (error)
                Log(text, StrategyLoggingLevel.Error);
            else
                Log(text);
        }

        [Obsolete("Quantower uses this legacy hook for the Strategy Manager value window.")]
        protected override List<StrategyMetric> OnGetMetrics()
        {
            List<StrategyMetric> metrics = new();
            RuntimePosition position;
            try { position = CurrentPosition(); }
            catch { position = RuntimePosition.Flat; }
            CampaignSizing sizing = _plan?.Sizing;

            AddMetric(metrics, "Mode", _runTradingEnabled ? "LIVE" : "SHADOW");
            AddMetric(metrics, "Campaign", _plan?.Id ?? "-");
            AddMetric(metrics, "Control", string.IsNullOrWhiteSpace(_lastControlStatus)
                ? "-"
                : $"{_lastControlAction}:{_lastControlStatus}");
            AddMetric(metrics, "Phase", _state?.Phase.ToString() ?? "-");
            AddMetric(metrics, "Exec/Data", $"{RuntimeSymbol?.Name ?? "-"}/{_marketDataSymbol?.Name ?? MarketDataSymbol?.Name ?? "-"}");
            AddMetric(metrics, "Evidence", _evidenceState);
            AddMetric(metrics, "Warmup Left", $"{EvidenceWarmupRemainingSeconds(DateTime.UtcNow):0}s");
            AddMetric(metrics, "Base Qty", sizing?.ProbeQuantity.ToString(CultureInfo.InvariantCulture) ?? "-");
            AddMetric(metrics, "Add Qty", sizing?.AddQuantity.ToString(CultureInfo.InvariantCulture) ?? "-");
            AddMetric(metrics, "Plan Max", sizing?.MaxPositionQuantity.ToString(CultureInfo.InvariantCulture) ?? "-");
            AddMetric(metrics, "Inst Cap", Math.Max(1, InstanceMaxQuantity).ToString(CultureInfo.InvariantCulture));
            AddMetric(metrics, "Sim Qty", (_state?.SimulatedPositionQuantity ?? 0).ToString(CultureInfo.InvariantCulture));
            AddMetric(metrics, "Live Qty", position.Quantity.ToString(CultureInfo.InvariantCulture));
            AddMetric(metrics, "Risk", _state?.ActiveRiskAnchor?.ToString() ?? "-");
            return metrics;
        }

        private static void AddMetric(List<StrategyMetric> metrics, string name, string value)
            => metrics.Add(new StrategyMetric { Name = name, FormattedValue = value });

        private LlEvidenceEngine NewEvidenceEngine()
            => new(_tickSize, new LlEvidenceEngineSettings
            {
                BookLookbackSeconds = Math.Max(10, BookLookbackSeconds),
                EventZThreshold = Math.Max(1.5, EventZThreshold),
                ClusterMinEvents = Math.Max(2, ClusterMinEvents),
                ClusterTicks = Math.Max(1, ClusterTicks),
                ClusterSeconds = Math.Max(15, ClusterSeconds),
                ConfirmMoveTicks = Math.Max(2, ConfirmMoveTicks),
                ConfirmSeconds = Math.Max(0, ConfirmSeconds),
                FailureBufferTicks = Math.Max(0, FailureBufferTicks),
                FailureConfirmTicks = Math.Max(2, FailureConfirmTicks),
                FailureSeconds = Math.Max(0, FailureSeconds),
            });

        private bool ResolveAccountAndSymbols()
        {
            RuntimeSymbol = ResolveConnectedSymbol(RuntimeSymbol);
            if (MarketDataSymbol != null)
                MarketDataSymbol = ResolveConnectedSymbol(MarketDataSymbol);
            _marketDataSymbol = ResolveConnectedSymbol(MarketDataSymbol ?? RuntimeSymbol);
            RuntimeAccount = ResolveConnectedAccount(RuntimeAccount);
            if (RuntimeAccount == null && RuntimeSymbol != null)
                RuntimeAccount = ResolveConnectedAccount(RuntimeSymbol.GetDefaultAccount());

            if (RuntimeSymbol == null)
            {
                LogOperator("ERR", "Kahn requires a Symbol setting.", error: true);
                return false;
            }
            if (_marketDataSymbol == null)
            {
                LogOperator("ERR", "Kahn requires a Market Data Symbol or Symbol setting.", error: true);
                return false;
            }

            double executionTickSize = EffectiveTickSize(RuntimeSymbol);
            double marketDataTickSize = EffectiveTickSize(_marketDataSymbol);
            if (!TickSizesMatch(executionTickSize, marketDataTickSize))
            {
                LogOperator("ERR", $"Execution symbol {RuntimeSymbol.Name} tick size {executionTickSize:R} "
                    + $"does not match market data symbol {_marketDataSymbol.Name} tick size {marketDataTickSize:R}.",
                    error: true);
                return false;
            }

            if (!_runTradingEnabled)
                return true;
            if (RuntimeAccount == null)
            {
                LogOperator("ERR", "Trading Enabled requires an Account setting.", error: true);
                return false;
            }

            bool allowed;
            try
            {
                allowed = RuntimeSymbol.IsTradingAllowed(RuntimeAccount);
            }
            catch (Exception ex)
            {
                LogOperator("ERR", $"Trading permission check failed: {ex.Message}", error: true);
                return false;
            }
            if (!allowed)
            {
                LogOperator("ERR", $"Trading is not currently allowed for {RuntimeSymbol.Name}/{RuntimeAccount.Name}.",
                    error: true);
                return false;
            }
            return true;
        }

        private bool SameBoundPair(Symbol symbol, Account account)
            => symbol != null && account != null && RuntimeSymbol != null && RuntimeAccount != null
                && string.Equals(symbol.Id, RuntimeSymbol.Id, StringComparison.Ordinal)
                && string.Equals(symbol.ConnectionId, RuntimeSymbol.ConnectionId, StringComparison.Ordinal)
                && string.Equals(account.Id, RuntimeAccount.Id, StringComparison.Ordinal);

        private long PriceToTick(double price)
            => (long)Math.Round(price / _tickSize);

        private static bool TickSizesMatch(double left, double right)
            => Math.Abs(left - right) <= Math.Max(Math.Abs(left), Math.Abs(right)) * 0.000001;

        private static bool SameSymbol(Symbol left, Symbol right)
            => SameSymbolIdentity(left, right) || SameSymbolName(left, right);

        private static Symbol ResolveConnectedSymbol(Symbol selected)
        {
            if (selected == null)
                return null;
            try
            {
                Symbol[] symbols = Core.Instance.Symbols;
                return symbols.FirstOrDefault(s => SameSymbolIdentity(s, selected))
                    ?? symbols.FirstOrDefault(s => SameSymbolName(s, selected))
                    ?? selected;
            }
            catch
            {
                return selected;
            }
        }

        private static Account ResolveConnectedAccount(Account selected)
        {
            if (selected == null)
                return null;
            try
            {
                Account[] accounts = Core.Instance.Accounts;
                return accounts.FirstOrDefault(a => SameAccountIdentity(a, selected))
                    ?? accounts.FirstOrDefault(a => SameAccountName(a, selected))
                    ?? selected;
            }
            catch
            {
                return selected;
            }
        }

        private static bool SameSymbolIdentity(Symbol left, Symbol right)
            => left != null && right != null
                && !string.IsNullOrWhiteSpace(left.Id)
                && string.Equals(left.Id, right.Id, StringComparison.Ordinal)
                && string.Equals(left.ConnectionId, right.ConnectionId, StringComparison.Ordinal);

        private static bool SameSymbolName(Symbol left, Symbol right)
            => left != null && right != null
                && !string.IsNullOrWhiteSpace(left.Name)
                && string.Equals(left.Name, right.Name, StringComparison.Ordinal)
                && string.Equals(left.ConnectionId, right.ConnectionId, StringComparison.Ordinal);

        private static bool SameAccountIdentity(Account left, Account right)
            => left != null && right != null
                && !string.IsNullOrWhiteSpace(left.Id)
                && string.Equals(left.Id, right.Id, StringComparison.Ordinal);

        private static bool SameAccountName(Account left, Account right)
            => left != null && right != null
                && !string.IsNullOrWhiteSpace(left.Name)
                && string.Equals(left.Name, right.Name, StringComparison.Ordinal);

        private static double EffectiveTickSize(Symbol symbol)
            => symbol != null && double.IsFinite(symbol.TickSize) && symbol.TickSize > 0
                ? symbol.TickSize
                : 0.25;

        private sealed class BookSampleDiagnostic
        {
            public DateTime? LastL2Utc { get; set; }
            public double? L2AgeMs { get; set; }
            public int BidLevels { get; set; }
            public int AskLevels { get; set; }
            public double? SymbolBid { get; set; }
            public double? SymbolAsk { get; set; }
            public double? DomBid { get; set; }
            public double? DomAsk { get; set; }
            public string Reason { get; set; }
            public string Error { get; set; }
        }
    }
}
