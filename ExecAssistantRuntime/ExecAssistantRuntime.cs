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
        private const int ProcessedControlHistory = 100;
        private const int SponsorFailureRebuildWindowSeconds = 60;
        private const int SponsorFailureRebuildMaxDistanceTicks = 120;
        private const int SponsorContextRailLimit = 5;

        [InputParameter("Symbol", sortIndex: 0)]
        public Symbol RuntimeSymbol;

        [InputParameter("Market Data Symbol", sortIndex: 1)]
        public Symbol MarketDataSymbol;

        [InputParameter("Account", sortIndex: 2)]
        public Account RuntimeAccount;

        [InputParameter("Directive Path", sortIndex: 3)]
        public string DirectivePath = @"%USERPROFILE%\Documents\ExecAssistantRuntime\directive.json";

        [InputParameter("Control Path", sortIndex: 4)]
        public string ControlPath = @"%USERPROFILE%\Documents\ExecAssistantRuntime\control.json";

        [InputParameter("Event Log Path", sortIndex: 5)]
        public string EventLogPath = @"%USERPROFILE%\Documents\ExecAssistantRuntime\events.jsonl";

        [InputParameter("Checkpoint Path", sortIndex: 6)]
        public string CheckpointPath = @"%USERPROFILE%\Documents\ExecAssistantRuntime\checkpoint.json";

        [InputParameter("Trading Enabled", sortIndex: 7)]
        public bool TradingEnabled = false;

        [InputParameter("Instance Max Quantity", sortIndex: 8,
            minimum: 1, maximum: 100, increment: 1, decimalPlaces: 0)]
        public int InstanceMaxQuantity = 5;

        [InputParameter("Worker Poll (ms)", sortIndex: 9,
            minimum: 100, maximum: 5000, increment: 100, decimalPlaces: 0)]
        public int WorkerPollMs = 250;

        [InputParameter("Book Sample (ms)", sortIndex: 10,
            minimum: 250, maximum: 5000, increment: 250, decimalPlaces: 0)]
        public int BookSampleMs = 1000;

        [InputParameter("L2 Freshness (sec)", sortIndex: 11,
            minimum: 1, maximum: 60, increment: 1, decimalPlaces: 0)]
        public int BookFreshnessSec = 5;

        [InputParameter("L2 Stale/Mismatch Grace (sec)", sortIndex: 12,
            minimum: 1, maximum: 60, increment: 1, decimalPlaces: 0)]
        public int BookUnusableGraceSec = 5;

        [InputParameter("Quote Freshness (ms)", sortIndex: 13,
            minimum: 250, maximum: 10000, increment: 250, decimalPlaces: 0)]
        public int QuoteFreshnessMs = 2000;

        [InputParameter("Run Startup Self Tests", sortIndex: 14)]
        public bool RunStartupSelfTests = true;

        [InputParameter("LF/HF Assisted Entries Enabled", sortIndex: 15)]
        public bool FailureAssistedEntriesEnabled = true;

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
        private readonly Dictionary<string, Order> _subscribedOrders = new(StringComparer.Ordinal);
        private readonly ConcurrentQueue<BrokerEvent> _brokerEvents = new();
        private readonly Dictionary<string, SubmissionTelemetry> _submissions = new(StringComparer.Ordinal);
        private readonly Dictionary<string, string> _processedControlDigests = new(StringComparer.Ordinal);
        private readonly Queue<string> _processedControlOrder = new();
        private readonly HashSet<string> _blockedDirectiveIds = new(StringComparer.Ordinal);
        private readonly List<PendingSponsorFailureAudit> _pendingSponsorFailureAudits = new();
        private readonly BookContinuityTracker _bookContinuity = new();

        private Timer _workerTimer;
        private int _shutdownStarted;
        private RuntimeEventLog _events;
        private RuntimeCheckpointStore _checkpointStore;
        private RuntimeCheckpointData _checkpoint;
        private ExecutionEvidenceEngine _evidence;
        private ExecutionCoordinator _coordinator;
        private QuantowerOrderGateway _gateway;
        private Symbol _marketDataSymbol;
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
        private bool _evidenceActionsPaused = true;
        private DateTime _evidenceEpochStartedUtc = DateTime.MinValue;
        private int _evidenceEpochSampleCount;
        private bool _evidenceWarmupComplete;
        private string _evidenceEpochReason = "startup";
        private string _evidenceState = "AwaitingBook";
        private bool _runTradingEnabled;
        private string _lastDirectiveFileHash;
        private string _lastControlFileHash;
        private string _acceptedDirectiveRaw;
        private string _lastPositionSignature;
        private string _lastShadowLivePositionSignature;
        private RuntimePosition _shadowPosition = RuntimePosition.Flat;
        private double? _shadowBreakeven;
        private double? _shadowHardTarget;
        private RuntimeExecutionState _lastLoggedState = RuntimeExecutionState.Idle;
        private int _lastLoggedSponsorVersion;

        public ExecAssistantRuntime()
        {
            Name = "Exec Assistant Runtime";
            Description = "Directive-bound NQ execution strategy using copied LevelLedger ownership evidence.";
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
            if (!ResolveAccountAndSymbol())
            {
                Stop();
                return;
            }

            try
            {
                ResetForRun();
                _events = new RuntimeEventLog(ExpandPath(EventLogPath),
                    message => Log(message, StrategyLoggingLevel.Error));
                _checkpointStore = new RuntimeCheckpointStore(ExpandPath(CheckpointPath));
                _evidence = NewEvidenceEngine();
                _coordinator = new ExecutionCoordinator(
                    _tickSize,
                    FailureAssistedEntriesEnabled);
                _gateway = new QuantowerOrderGateway(
                    RuntimeSymbol,
                    RuntimeAccount,
                    _events,
                    _runTradingEnabled);
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
                if (!ShadowLivePositionRequiresAction())
                {
                    PollControl();
                    PollDirective();
                }
                int interval = Math.Max(100, WorkerPollMs);
                _workerTimer = new Timer(_ => Worker(), null, interval, interval);
                _events.Write("runtime_started",
                    ("symbol", RuntimeSymbol.Name),
                    ("execution_symbol", RuntimeSymbol.Name),
                    ("execution_symbol_id", RuntimeSymbol.Id),
                    ("execution_connection_id", RuntimeSymbol.ConnectionId),
                    ("market_data_symbol", _marketDataSymbol.Name),
                    ("market_data_symbol_id", _marketDataSymbol.Id),
                    ("market_data_connection_id", _marketDataSymbol.ConnectionId),
                    ("market_data_is_execution_symbol",
                        SameSymbol(RuntimeSymbol, _marketDataSymbol)),
                    ("account", RuntimeAccount.Name),
                    ("tick_size", _tickSize),
                    ("execution_tick_size", EffectiveTickSize(RuntimeSymbol)),
                    ("market_data_tick_size", EffectiveTickSize(_marketDataSymbol)),
                    ("trading_enabled", _runTradingEnabled),
                    ("instance_max_quantity", Math.Max(1, InstanceMaxQuantity)),
                    ("worker_poll_ms", Math.Max(100, WorkerPollMs)),
                    ("quote_freshness_ms", Math.Max(250, QuoteFreshnessMs)),
                    ("book_freshness_sec", Math.Max(1, BookFreshnessSec)),
                    ("book_unusable_grace_sec", Math.Max(1, BookUnusableGraceSec)),
                    ("failure_assisted_entries_enabled",
                        FailureAssistedEntriesEnabled),
                    ("ll_book_lookback_seconds", Math.Max(10, BookLookbackSeconds)),
                    ("ll_event_z_threshold", Math.Max(1.0, EventZThreshold)),
                    ("ll_cluster_min_events", Math.Max(2, ClusterMinEvents)),
                    ("ll_cluster_ticks", Math.Max(1, ClusterTicks)),
                    ("ll_cluster_seconds", Math.Max(1, ClusterSeconds)),
                    ("ll_confirm_move_ticks", Math.Max(1, ConfirmMoveTicks)),
                    ("ll_confirm_seconds", Math.Max(0, ConfirmSeconds)),
                    ("ll_failure_buffer_ticks", Math.Max(0, FailureBufferTicks)),
                    ("ll_failure_confirm_ticks", Math.Max(1, FailureConfirmTicks)),
                    ("ll_failure_seconds", Math.Max(0, FailureSeconds)),
                    ("directive_path", ExpandPath(DirectivePath)),
                    ("control_path", ExpandPath(ControlPath)));
                Log($"Runtime started for exec {RuntimeSymbol.Name}, "
                    + $"data {_marketDataSymbol.Name}, account {RuntimeAccount.Name}; "
                    + $"mode={(_runTradingEnabled ? "LIVE" : "SHADOW")}.");
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
                if (ShadowLivePositionRequiresAction())
                    return;
                ExecutableMarket market = SnapshotMarket(nowUtc);
                bool ambiguous = false;
                RuntimePosition position = _runTradingEnabled
                    ? LivePosition(out ambiguous)
                    : CurrentPosition();
                if (_runTradingEnabled && ambiguous
                    && _coordinator.State != RuntimeExecutionState.Halting)
                {
                    _events.Write("ambiguous_position_detected",
                        ("position_id", position.PositionId),
                        ("quantity", position.Quantity));
                    OrderIntent flatten = _coordinator.SafetyFlatten(
                        nowUtc, market, "ambiguous_bound_positions");
                    ExecuteIntents(new[] { flatten }, position, market);
                    return;
                }
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
                ExpireSponsorFailureAudits(nowUtc);

                position = CurrentPosition();
                IReadOnlyList<OrderIntent> tickIntents = _coordinator.Tick(
                    nowUtc,
                    market,
                    position,
                    _evidence,
                    evidenceAvailable: !_evidenceActionsPaused);
                LogCoordinatorAudit();
                ExecuteIntents(tickIntents, position, market);
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
            var diagnostic = new BookSampleDiagnostic
            {
                SymbolBid = double.IsFinite(_marketDataSymbol.Bid)
                    ? _marketDataSymbol.Bid
                    : null,
                SymbolAsk = double.IsFinite(_marketDataSymbol.Ask)
                    ? _marketDataSymbol.Ask
                    : null,
            };
            bool l2Fresh;
            lock (_marketGate)
            {
                diagnostic.LastL2Utc = _lastL2Utc == DateTime.MinValue
                    ? null
                    : _lastL2Utc;
                diagnostic.L2AgeMs = _lastL2Utc == DateTime.MinValue
                    ? null
                    : Math.Max(0, (nowUtc - _lastL2Utc).TotalMilliseconds);
                l2Fresh = _lastL2Utc != DateTime.MinValue
                    && (nowUtc - _lastL2Utc).TotalSeconds <= Math.Max(1, BookFreshnessSec);
            }

            BookDepthSnapshot depth = null;
            bool usable;
            if (!l2Fresh)
            {
                diagnostic.Reason = "l2_heartbeat_stale";
                usable = false;
            }
            else
            {
                usable = TryBuildDepthSnapshot(nowUtc, out depth, diagnostic);
            }

            if (!usable)
            {
                _evidenceActionsPaused = true;
                _evidenceState = "BookUnusable";
                BookContinuityUpdate update = _bookContinuity.ObserveUnusable(
                    nowUtc,
                    diagnostic.Reason,
                    Math.Max(1, BookUnusableGraceSec));
                if (update.StartedUnusable)
                {
                    WriteBookHealthEvent("book_unusable_started", update, diagnostic);
                }
                else if (update.ReasonChanged)
                {
                    WriteBookHealthEvent("book_unusable_reason_changed", update, diagnostic);
                }
                if (update.ConfirmedLoss && _hadEvidenceSample)
                    HandleForwardDataLoss(nowUtc, market, position, update, diagnostic);
                return;
            }

            BookContinuityUpdate recovered = _bookContinuity.ObserveUsable(nowUtc);
            if (recovered.Recovered)
            {
                WriteBookHealthEvent("book_usable_recovered", recovered, diagnostic);
                if (recovered.RecoveredAfterConfirmedLoss)
                {
                    LogOperator($"L2 book recovered after {recovered.UnusableSeconds:F1}s; "
                        + "new evidence epoch warming.");
                }
            }

            _hadEvidenceSample = true;
            StartEvidenceEpochIfNeeded(nowUtc);
            IReadOnlyList<EvidenceTransition> transitions = _evidence.Process(depth);
            _evidenceEpochSampleCount++;
            CompleteEvidenceWarmupIfReady(nowUtc);
            _evidenceActionsPaused = !_evidenceWarmupComplete;
            _evidenceState = _evidenceWarmupComplete ? "Ready" : "Warming";
            foreach (EvidenceTransition transition in transitions)
            {
                LogEvidence(transition, market);
                ObserveSponsorFailureRebuild(transition);
            }
            if (!_evidenceWarmupComplete)
                return;
            RuntimePosition current = CurrentPosition();
            IReadOnlyList<OrderIntent> intents = _coordinator.ProcessEvidence(
                transitions, nowUtc, market, current, _evidence);
            LogCoordinatorAudit();
            LogSponsorIfChanged();
            ExecuteIntents(intents, current, market);
        }

        private int EvidenceWarmupSeconds
            => Math.Max(10, BookLookbackSeconds);

        private int EvidenceWarmupRequiredSamples
            => Math.Max(5, (int)Math.Ceiling(
                EvidenceWarmupSeconds * 1000.0 / Math.Max(250, BookSampleMs)));

        private void ResetEvidenceEpoch(string reason)
        {
            _evidenceEpochStartedUtc = DateTime.MinValue;
            _evidenceEpochSampleCount = 0;
            _evidenceWarmupComplete = false;
            _evidenceEpochReason = string.IsNullOrWhiteSpace(reason) ? "unknown" : reason;
            _evidenceState = "AwaitingBook";
        }

        private void StartEvidenceEpochIfNeeded(DateTime nowUtc)
        {
            if (_evidenceEpochStartedUtc != DateTime.MinValue)
                return;
            _evidenceEpochStartedUtc = nowUtc;
            _evidenceEpochSampleCount = 0;
            _evidenceWarmupComplete = false;
            _evidenceState = "Warming";
            _events.Write("evidence_warmup_started",
                ("reason", _evidenceEpochReason),
                ("started_utc", nowUtc.ToString("O", CultureInfo.InvariantCulture)),
                ("required_seconds", EvidenceWarmupSeconds),
                ("required_samples", EvidenceWarmupRequiredSamples));
            LogOperator($"Evidence epoch warming for {EvidenceWarmupSeconds}s; "
                + $"reason={_evidenceEpochReason}.");
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
            _coordinator.BaselineHeldFailures(
                _evidence.HeldFailureObjects().Select(b => b.Id), nowUtc);
            _events.Write("evidence_warmup_completed",
                ("reason", _evidenceEpochReason),
                ("started_utc", _evidenceEpochStartedUtc.ToString(
                    "O", CultureInfo.InvariantCulture)),
                ("completed_utc", nowUtc.ToString("O", CultureInfo.InvariantCulture)),
                ("sample_count", _evidenceEpochSampleCount),
                ("required_seconds", EvidenceWarmupSeconds),
                ("required_samples", EvidenceWarmupRequiredSamples),
                ("baselined_failure_ids", string.Join(",",
                    _evidence.HeldFailureObjects().Select(b => b.Id))));
            LogOperator($"Evidence epoch ready after "
                + $"{(nowUtc - _evidenceEpochStartedUtc).TotalSeconds:F1}s "
                + $"and {_evidenceEpochSampleCount} samples.");
        }

        private double EvidenceWarmupRemainingSeconds(DateTime nowUtc)
        {
            if (_evidenceWarmupComplete)
                return 0;
            if (_evidenceEpochStartedUtc == DateTime.MinValue)
                return EvidenceWarmupSeconds;
            return Math.Max(0,
                EvidenceWarmupSeconds - (nowUtc - _evidenceEpochStartedUtc).TotalSeconds);
        }

        private void WriteBookHealthEvent(string eventType,
            BookContinuityUpdate update, BookSampleDiagnostic diagnostic)
        {
            _events.Write(eventType,
                ("initial_reason", update.InitialReason),
                ("latest_reason", update.LatestReason),
                ("unusable_seconds", update.UnusableSeconds),
                ("unusable_since_utc", update.UnusableSinceUtc == DateTime.MinValue
                    ? null
                    : update.UnusableSinceUtc.ToString("O", CultureInfo.InvariantCulture)),
                ("last_usable_utc", update.LastUsableUtc == DateTime.MinValue
                    ? null
                    : update.LastUsableUtc.ToString("O", CultureInfo.InvariantCulture)),
                ("book_freshness_sec", Math.Max(1, BookFreshnessSec)),
                ("confirmation_grace_sec", Math.Max(1, BookUnusableGraceSec)),
                ("market_data_symbol", _marketDataSymbol?.Name),
                ("last_l2_utc", diagnostic.LastL2Utc?.ToString("O",
                    CultureInfo.InvariantCulture)),
                ("l2_age_ms", diagnostic.L2AgeMs),
                ("bid_levels", diagnostic.BidLevels),
                ("ask_levels", diagnostic.AskLevels),
                ("symbol_bid", diagnostic.SymbolBid),
                ("symbol_ask", diagnostic.SymbolAsk),
                ("dom_bid", diagnostic.DomBid),
                ("dom_ask", diagnostic.DomAsk),
                ("error", diagnostic.Error));
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
                LogOperator($"Directive rejected: {ex.Message}", error: true);
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
                    LogOperator($"Directive {directive.Id} rejected: immutable payload changed.",
                        error: true);
                    if (CurrentPosition().IsFlat)
                        _coordinator.MarkError();
                }
                return;
            }

            ContinuationContext continuation = null;
            if (directive.Lineage?.IsContinuation == true)
            {
                if (!_coordinator.TryPrepareContinuation(
                    directive,
                    out continuation,
                    out string continuationReason))
                {
                    _events.Write("directive_rejected",
                        ("directive_id", directive.Id),
                        ("reason", continuationReason),
                        ("parent_directive_id", directive.Lineage.ParentDirectiveId));
                    LogOperator($"Directive {directive.Id} rejected: {continuationReason}.",
                        error: true);
                    return;
                }

                EvidenceSide adverse = directive.Direction == TradeDirection.Long
                    ? EvidenceSide.Supply
                    : EvidenceSide.Demand;
                if (ExecutionCoordinator.HasContinuationBoundaryCounterEvidence(
                    directive.Direction,
                    continuation,
                    _evidence.LiveRails(adverse),
                    out EvidenceBandView counter))
                {
                    _events.Write("directive_rejected",
                        ("directive_id", directive.Id),
                        ("reason", "continuation_boundary_counter_evidence"),
                        ("parent_directive_id", continuation.ParentDirectiveId),
                        ("band_id", counter.Id),
                        ("band_side", counter.Side.ToString()),
                        ("band_lower", counter.MinTick * _tickSize),
                        ("band_upper", counter.MaxTick * _tickSize));
                    LogOperator($"Directive {directive.Id} rejected: continuation "
                        + $"counter-evidence beyond parent boundary (id={counter.Id}).",
                        error: true);
                    return;
                }
            }

            if (_blockedDirectiveIds.Contains(directive.Id))
            {
                _events.Write("directive_rejected",
                    ("directive_id", directive.Id),
                    ("reason", "fresh_id_required_after_restart_or_terminal_state"));
                LogOperator($"Directive {directive.Id} rejected: a fresh id is required.",
                    error: true);
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
                LogOperator($"Directive {directive.Id} rejected: bound position is not flat "
                    + $"(qty={position.Quantity:R}).", error: true);
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
                LogOperator($"Directive {directive.Id} rejected: {workingOrders.Length} "
                    + "bound working order(s) exist.", error: true);
                return;
            }
            int unresolvedEntries = _submissions.Values.Count(t =>
                t.CancelRequested && !t.FillObserved);
            if (unresolvedEntries > 0)
            {
                _events.Write("directive_rejected",
                    ("directive_id", directive.Id),
                    ("reason", "entry_reconciliation_unresolved"),
                    ("unresolved_entry_count", unresolvedEntries));
                LogOperator($"Directive {directive.Id} rejected: {unresolvedEntries} "
                    + "entry reconciliation(s) remain unresolved.", error: true);
                return;
            }
            if (active != null && !IsCoordinatorTerminal())
            {
                bool replacesContinuationParent = continuation != null
                    && string.Equals(active.Id, continuation.ParentDirectiveId,
                        StringComparison.Ordinal);
                if (!replacesContinuationParent)
                {
                    _events.Write("directive_rejected",
                        ("directive_id", directive.Id),
                        ("reason", "prior_directive_active"),
                        ("active_directive_id", active.Id));
                    LogOperator($"Directive {directive.Id} rejected: directive {active.Id} is active.",
                        error: true);
                    return;
                }
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
                        ("target", directive.TargetPrice),
                        ("not_before", directive.NotBefore.ToString("O")));
                    LogOperator($"Directive {directive.Id} rejected: HARD_TP "
                        + $"{directive.TargetPrice:R} has no executable runway.", error: true);
                    return;
                }
            }

            _coordinator.AcceptDirective(
                directive,
                DateTime.UtcNow,
                _evidence.HeldFailureObjects().Select(b => b.Id),
                continuation);
            _lastLoggedSponsorVersion = 0;
            _coordinator.InitializeObservedPosition(position);
            _acceptedDirectiveRaw = json;
            _blockedDirectiveIds.Add(directive.Id);
            _events.Write("directive_accepted",
                ("directive_id", directive.Id),
                ("digest", directive.Digest),
                ("side", directive.Direction.ToString()),
                ("not_before", directive.NotBefore.ToString("O")),
                ("expires_at", directive.ExpiresAt.ToString("O")),
                ("order_price_lower", directive.OrderPriceRange.Lower),
                ("order_price_upper", directive.OrderPriceRange.Upper),
                ("context_price_lower", directive.ContextPriceRange.Lower),
                ("context_price_upper", directive.ContextPriceRange.Upper),
                ("add_price_lower", directive.AddPriceRange?.Lower),
                ("add_price_upper", directive.AddPriceRange?.Upper),
                ("base_quantity", directive.BaseQuantity),
                ("add_quantity", directive.AddQuantity),
                ("max_position_quantity", directive.MaxPositionQuantity),
                ("target_mode", directive.TargetMode.ToString()),
                ("target_price", directive.TargetPrice),
                ("lineage_mode", directive.Lineage?.Mode.ToString()),
                ("parent_directive_id", directive.Lineage?.ParentDirectiveId),
                ("evidence_state", _evidenceState),
                ("failure_assisted_entries_enabled",
                    FailureAssistedEntriesEnabled),
                ("mode", _runTradingEnabled ? "LIVE" : "SHADOW"));
            LogOperator($"Directive {directive.Id} accepted: {directive.Direction}, "
                + $"base={directive.BaseQuantity}, max={directive.MaxPositionQuantity}, "
                + $"{directive.TargetMode}={directive.TargetPrice:R}, "
                + $"mode={(_runTradingEnabled ? "LIVE" : "SHADOW")}.");
            if (continuation != null)
            {
                IReadOnlyList<OrderIntent> seeded = _coordinator.SeedContinuation(
                    DateTime.UtcNow,
                    market,
                    position,
                    _evidence);
                LogCoordinatorAudit();
                ExecuteIntents(seeded, position, market);
            }
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
                LogOperator($"Control rejected: {ex.Message}", error: true);
                return;
            }
            if (_processedControlDigests.TryGetValue(command.CommandId, out string priorDigest))
            {
                if (priorDigest != null && !string.Equals(priorDigest, command.Digest,
                    StringComparison.Ordinal))
                {
                    _events.Write("control_mutation_rejected",
                        ("command_id", command.CommandId));
                    LogOperator($"Control {command.CommandId} rejected: immutable payload changed.",
                        error: true);
                }
                return;
            }

            RememberProcessedControl(command.CommandId, command.Digest);
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
            LogOperator($"Control {command.Action} accepted"
                + (string.IsNullOrWhiteSpace(command.DirectiveId)
                    ? "."
                    : $" for directive {command.DirectiveId}."));
            ExecuteIntents(intents, position, market);
            SaveCheckpointIfDue(DateTime.UtcNow, force: true);
        }

        private void RememberProcessedControl(string commandId, string digest)
        {
            if (string.IsNullOrWhiteSpace(commandId)
                || _processedControlDigests.ContainsKey(commandId))
            {
                return;
            }
            _processedControlDigests[commandId] = digest;
            _processedControlOrder.Enqueue(commandId);
            while (_processedControlOrder.Count > ProcessedControlHistory)
            {
                string expired = _processedControlOrder.Dequeue();
                _processedControlDigests.Remove(expired);
            }
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
                LogIntentResult(intent, result, position, market);

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
                            BrokerOrderId = result.OrderId,
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
            LogCoordinatorAudit();
            LogSponsorIfChanged();
            LogOperator($"{intent.Kind} filled for directive {intent.DirectiveId}: "
                + $"qty={intent.Quantity:R} at {fillPrice:R}; position "
                + $"qty={_shadowPosition.Quantity:R}, avg={_shadowPosition.AveragePrice:R}.");
            ExecuteIntents(protection, _shadowPosition, market);
        }

        private void ApplyShadowFlatten(ExecutableMarket market)
        {
            _shadowPosition = RuntimePosition.Flat;
            _shadowBreakeven = null;
            _shadowHardTarget = null;
            _coordinator.OnPositionChanged(_shadowPosition, DateTime.UtcNow, market);
            LogCoordinatorAudit();
            LogSponsorIfChanged();
        }

        private void EvaluateShadowProtection(DateTime nowUtc, ExecutableMarket market)
        {
            if (_runTradingEnabled || _shadowPosition.IsFlat || market == null || !market.IsValid)
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
            if (position != null && !position.IsFlat
                && _coordinator.State == RuntimeExecutionState.Paused)
            {
                ExecuteIntents(new[]
                {
                    _coordinator.FlattenPausedFill(nowUtc, market),
                }, position, market);
                return;
            }

            if (position != null && !position.IsFlat
                && IsCoordinatorTerminal())
            {
                OrderIntent safety = _coordinator.SafetyFlatten(
                    nowUtc, market, "position_observed_after_terminal_state");
                ExecuteIntents(new[] { safety }, position, market);
                return;
            }

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
            LogOperator(position.IsFlat
                ? $"Position flat; directive={_coordinator.Directive?.Id ?? "none"}."
                : $"Position reconciled: {position.Direction} qty={position.Quantity:R}, "
                    + $"avg={position.AveragePrice:R}, directive="
                    + $"{_coordinator.Directive?.Id ?? "none"}.");
            IReadOnlyList<OrderIntent> protection = _coordinator.OnPositionChanged(
                position, nowUtc, market);
            LogCoordinatorAudit();
            LogSponsorIfChanged();
            ExecuteIntents(protection, position, market);
            if (becameFlat)
                _gateway.CancelProtectionWhenFlat();
        }

        private void HandleForwardDataLoss(DateTime nowUtc, ExecutableMarket market,
            RuntimePosition position, BookContinuityUpdate continuity,
            BookSampleDiagnostic diagnostic)
        {
            _events.Write("forward_data_loss",
                ("position_quantity", position?.Quantity ?? 0),
                ("state", _coordinator.State.ToString()),
                ("initial_reason", continuity.InitialReason),
                ("latest_reason", continuity.LatestReason),
                ("unusable_seconds", continuity.UnusableSeconds),
                ("confirmation_grace_sec", Math.Max(1, BookUnusableGraceSec)),
                ("market_data_symbol", _marketDataSymbol?.Name),
                ("l2_age_ms", diagnostic.L2AgeMs),
                ("bid_levels", diagnostic.BidLevels),
                ("ask_levels", diagnostic.AskLevels),
                ("symbol_bid", diagnostic.SymbolBid),
                ("symbol_ask", diagnostic.SymbolAsk),
                ("dom_bid", diagnostic.DomBid),
                ("dom_ask", diagnostic.DomAsk),
                ("error", diagnostic.Error));
            LogOperator($"Forward L2 continuity lost after "
                + $"{continuity.UnusableSeconds:F1}s; initial={continuity.InitialReason}, "
                + $"latest={continuity.LatestReason}, state={_coordinator.State}, "
                + $"position_qty={(position?.Quantity ?? 0):R}.", error: true);
            _evidence = NewEvidenceEngine();
            ResetEvidenceEpoch("forward_data_loss");
            _coordinator.BreakContinuationLineage();
            _hadEvidenceSample = false;
            _evidenceActionsPaused = true;

            if (position == null || position.IsFlat)
            {
                if (_coordinator.Directive != null && !IsCoordinatorTerminal())
                {
                    ExecuteIntents(_coordinator.CancelDirective(nowUtc, market, position),
                        position, market);
                }
                return;
            }

            var cancel = new OrderIntent
            {
                IntentId = Guid.NewGuid().ToString("N"),
                Kind = OrderIntentKind.CancelRuntimeOrders,
                Direction = position.Direction,
                Reason = "forward_data_loss",
                DirectiveId = _coordinator.Directive?.Id,
                TriggerUtc = nowUtc,
                TriggerBid = market?.Bid ?? double.NaN,
                TriggerAsk = market?.Ask ?? double.NaN,
            };
            GatewayResult cancelResult = _gateway.Execute(cancel, position, market);
            LogIntentResult(cancel, cancelResult, position, market);
            if (!cancelResult.Accepted)
            {
                OrderIntent flatten = _coordinator.SafetyFlatten(nowUtc, market,
                    $"forward_data_loss_cancel_failed:{cancelResult.Message}");
                ExecuteIntents(new[] { flatten }, position, market);
                return;
            }

            if (!_runTradingEnabled)
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
                    RememberProcessedControl(id, null);
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
            if (!_runTradingEnabled)
            {
                ShadowLivePositionRequiresAction();
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
                        Math.Max(1, InstanceMaxQuantity),
                        allowLegacyWeightedBreakeven: true);
                }
                catch (Exception ex)
                {
                    _events.Write("recovery_directive_error", ("message", ex.Message));
                }
            }

            bool unsupportedTarget = recoveredDirective != null
                && recoveredDirective.TargetMode != TargetMode.HardTp;
            if (ambiguous || recoveredDirective == null || unsupportedTarget || !market.IsValid
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
                        : unsupportedTarget ? "restart_unsupported_target_mode"
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
            if (directive == null || directive.TargetMode != TargetMode.HardTp)
            {
                OrderIntent flatten = _coordinator.SafetyFlatten(DateTime.UtcNow,
                    market, "recovery_unsupported_target_mode");
                _gateway.Execute(flatten, position, market);
                return;
            }

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

        private void DrainBrokerEvents()
        {
            while (_brokerEvents.TryDequeue(out BrokerEvent ev))
            {
                BindSubmissionToOrder(ev);
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
                    ("comment", ev.Comment),
                    ("group_id", ev.GroupId));

                if (ev.EventType == "trade_fill")
                {
                    LogFillQuality(ev);
                    if (HasOrderRole(ev, "TP"))
                    {
                        _events.Write("hard_target_fill",
                            ("order_id", ev.OrderId),
                            ("position_id", ev.PositionId),
                            ("quantity", ev.Quantity),
                            ("price", ev.Price));
                    }
                }
                else if ((ev.EventType == "order_removed" || ev.EventType == "order_updated")
                    && (string.Equals(ev.Status, OrderStatus.Refused.ToString(), StringComparison.Ordinal)
                        || string.Equals(ev.Status, OrderStatus.Cancelled.ToString(), StringComparison.Ordinal))
                    && ev.FilledQuantity <= 0
                    && TryFindSubmission(ev, allowSideFallback: false,
                        out string submissionKey,
                        out SubmissionTelemetry terminal,
                        out _))
                {
                    _coordinator.OnOrderAttemptResult(terminal.Intent, accepted: false);
                    _events.Write("entry_order_terminal_without_fill",
                        ("intent_id", terminal.Intent.IntentId),
                        ("order_id", ev.OrderId),
                        ("status", ev.Status));
                    _submissions.Remove(submissionKey);
                }
            }
        }

        private void LogFillQuality(BrokerEvent fill)
        {
            if (!TryFindSubmission(fill, allowSideFallback: true,
                out _, out SubmissionTelemetry telemetry, out bool usedSideFallback))
                return;
            if (usedSideFallback)
            {
                _events.Write("fill_quality_fallback_match",
                    ("intent_id", telemetry.Intent.IntentId),
                    ("order_id", fill.OrderId),
                    ("side", fill.Side),
                    ("reason", "matched most recent submission by side"));
            }
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
                        resolution.SupportMaxTick)),
                ("failure_assisted", resolution?.FailureAssisted),
                ("failure_parent_id", resolution?.FailureParentObjectId),
                ("failure_parent_lower", resolution?.FailureAssisted == true
                    ? (double?)(resolution.FailureParentMinTick * _tickSize)
                    : null),
                ("failure_parent_upper", resolution?.FailureAssisted == true
                    ? (double?)(resolution.FailureParentMaxTick * _tickSize)
                    : null));
            LogOperator($"{telemetry.Intent.Kind} fill for directive "
                + $"{telemetry.Intent.DirectiveId}: qty={fill.Quantity:R} at {fill.Price:R}.");
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
                if (!telemetry.CancelRequested)
                {
                    bool cancelAccepted = _gateway.CancelEntryOrder(
                        telemetry.BrokerOrderId, telemetry.Intent.IntentId);
                    telemetry.CancelRequested = true;
                    telemetry.LastCancelAttemptUtc = nowUtc;
                    _events.Write("entry_fill_timeout",
                        ("intent_id", telemetry.Intent.IntentId),
                        ("order_id", telemetry.BrokerOrderId),
                        ("elapsed_seconds", ageSeconds),
                        ("cancel_accepted", cancelAccepted));
                    if (!cancelAccepted)
                    {
                        _coordinator.MarkError();
                        telemetry.ReconciliationFailureLogged = true;
                        _events.Write("entry_order_unresolved",
                            ("intent_id", telemetry.Intent.IntentId),
                            ("order_id", telemetry.BrokerOrderId),
                            ("operator_action_required", true));
                    }
                    continue;
                }

                if (ageSeconds > 30 && !telemetry.ReconciliationFailureLogged)
                {
                    _coordinator.MarkError();
                    telemetry.ReconciliationFailureLogged = true;
                    _events.Write("entry_cancel_reconciliation_timeout",
                        ("intent_id", telemetry.Intent.IntentId),
                        ("order_id", telemetry.BrokerOrderId),
                        ("elapsed_seconds", ageSeconds),
                        ("operator_action_required", true));
                }

                if ((nowUtc - telemetry.LastCancelAttemptUtc).TotalSeconds >= 5)
                {
                    bool retryAccepted = _gateway.CancelEntryOrder(
                        telemetry.BrokerOrderId, telemetry.Intent.IntentId);
                    telemetry.LastCancelAttemptUtc = nowUtc;
                    _events.Write("entry_timeout_cancel_retry",
                        ("intent_id", telemetry.Intent.IntentId),
                        ("order_id", telemetry.BrokerOrderId),
                        ("accepted", retryAccepted),
                        ("elapsed_seconds", ageSeconds));
                }
            }
        }

        private void BindSubmissionToOrder(BrokerEvent brokerEvent)
        {
            if (brokerEvent == null || string.IsNullOrWhiteSpace(brokerEvent.OrderId))
                return;
            if (_submissions.TryGetValue(brokerEvent.OrderId,
                out SubmissionTelemetry direct))
            {
                direct.BrokerOrderId = brokerEvent.OrderId;
                return;
            }

            KeyValuePair<string, SubmissionTelemetry> tagged = _submissions
                .FirstOrDefault(pair => HasIntentTag(brokerEvent, pair.Value.Intent.IntentId));
            if (tagged.Value == null)
                return;
            _submissions.Remove(tagged.Key);
            tagged.Value.BrokerOrderId = brokerEvent.OrderId;
            _submissions[brokerEvent.OrderId] = tagged.Value;
        }

        private bool TryFindSubmission(
            BrokerEvent brokerEvent,
            bool allowSideFallback,
            out string key,
            out SubmissionTelemetry telemetry,
            out bool usedSideFallback)
        {
            key = null;
            telemetry = null;
            usedSideFallback = false;
            if (brokerEvent == null)
                return false;
            if (!string.IsNullOrWhiteSpace(brokerEvent.OrderId)
                && _submissions.TryGetValue(brokerEvent.OrderId, out telemetry))
            {
                key = brokerEvent.OrderId;
                return true;
            }

            KeyValuePair<string, SubmissionTelemetry> exact = _submissions
                .FirstOrDefault(pair =>
                    (!string.IsNullOrWhiteSpace(brokerEvent.OrderId)
                        && pair.Value.BrokerOrderId == brokerEvent.OrderId)
                    || HasIntentTag(brokerEvent, pair.Value.Intent.IntentId));
            if (exact.Value != null)
            {
                key = exact.Key;
                telemetry = exact.Value;
                return true;
            }
            if (!allowSideFallback)
                return false;

            KeyValuePair<string, SubmissionTelemetry> side = _submissions
                .Where(pair => pair.Value.Intent.Direction.ToString() == brokerEvent.Side)
                .OrderByDescending(pair => pair.Value.SubmitUtc)
                .FirstOrDefault();
            if (side.Value == null)
                return false;
            key = side.Key;
            telemetry = side.Value;
            usedSideFallback = true;
            return true;
        }

        private static bool HasIntentTag(BrokerEvent brokerEvent, string intentId)
        {
            if (brokerEvent == null || string.IsNullOrWhiteSpace(intentId))
                return false;
            string token = intentId.Length > 8 ? intentId.Substring(0, 8) : intentId;
            return (brokerEvent.Comment?.EndsWith($":{token}", StringComparison.Ordinal) ?? false)
                || (brokerEvent.GroupId?.EndsWith($":{token}", StringComparison.Ordinal) ?? false);
        }

        private static bool HasOrderRole(BrokerEvent brokerEvent, string role)
            => brokerEvent != null
                && ((brokerEvent.Comment?.Contains($":{role}:", StringComparison.Ordinal) ?? false)
                    || (brokerEvent.GroupId?.Contains($":{role}:", StringComparison.Ordinal) ?? false));

        private void SaveCheckpointIfDue(
            DateTime nowUtc,
            bool force,
            RuntimePosition positionOverride = null,
            string stateOverride = null,
            bool recoveryActionRequired = false)
        {
            if (!force && (nowUtc - _lastCheckpointUtc).TotalSeconds < 2)
                return;
            _lastCheckpointUtc = nowUtc;
            RuntimePosition position = positionOverride ?? CurrentPosition();
            TradeDirective directive = _coordinator.Directive;
            _checkpoint = new RuntimeCheckpointData
            {
                RuntimeState = stateOverride ?? _coordinator.State.ToString(),
                LastDirectiveId = directive?.Id ?? _checkpoint?.LastDirectiveId,
                LastDirectiveDigest = directive?.Digest ?? _checkpoint?.LastDirectiveDigest,
                LastDirectiveJson = _acceptedDirectiveRaw ?? _checkpoint?.LastDirectiveJson,
                ProcessedControlIds = _processedControlOrder.ToList(),
                TradingEnabled = _runTradingEnabled,
                ExecutionSymbol = RuntimeSymbol?.Name,
                ExecutionSymbolId = RuntimeSymbol?.Id,
                ExecutionConnectionId = RuntimeSymbol?.ConnectionId,
                MarketDataSymbol = _marketDataSymbol?.Name,
                MarketDataSymbolId = _marketDataSymbol?.Id,
                MarketDataConnectionId = _marketDataSymbol?.ConnectionId,
                InstanceMaxQuantity = Math.Max(1, InstanceMaxQuantity),
                WorkerPollMs = Math.Max(100, WorkerPollMs),
                EvidenceState = _evidenceState,
                EvidenceEpochReason = _evidenceEpochReason,
                EvidenceEpochStartedUtc = _evidenceEpochStartedUtc == DateTime.MinValue
                    ? null
                    : _evidenceEpochStartedUtc.ToString("O", CultureInfo.InvariantCulture),
                EvidenceSampleCount = _evidenceEpochSampleCount,
                EvidenceWarmupSeconds = EvidenceWarmupSeconds,
                EvidenceWarmupRequiredSamples = EvidenceWarmupRequiredSamples,
                EvidenceWarmupRemainingSeconds = EvidenceWarmupRemainingSeconds(nowUtc),
                RecoveryActionRequired = recoveryActionRequired,
                BoundWorkingOrderCount = BoundWorkingOrders().Length,
                UnresolvedEntryCount = _submissions.Values.Count(t =>
                    t.CancelRequested && !t.FillObserved),
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

        private bool TryBuildDepthSnapshot(DateTime nowUtc,
            out BookDepthSnapshot snapshot, BookSampleDiagnostic diagnostic)
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
                snapshot = new BookDepthSnapshot
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
                _events.Write("book_sample_error", ("message", ex.Message));
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
            if (!_runTradingEnabled)
                return _shadowPosition;
            return LivePosition(out _);
        }

        private bool ShadowLivePositionRequiresAction()
        {
            if (_runTradingEnabled)
                return false;
            RuntimePosition live = LivePosition(out bool ambiguous);
            if (live.IsFlat)
            {
                _lastShadowLivePositionSignature = null;
                return false;
            }

            SaveCheckpointIfDue(
                DateTime.UtcNow,
                force: false,
                positionOverride: live,
                stateOverride: "RecoveryActionRequired",
                recoveryActionRequired: true);

            string signature = $"{live.PositionId}|{live.Direction}|{live.Quantity:R}|"
                + $"{live.AveragePrice:R}|{ambiguous}";
            if (!string.Equals(signature, _lastShadowLivePositionSignature,
                StringComparison.Ordinal))
            {
                _lastShadowLivePositionSignature = signature;
                _events?.Write("recovery_action_required",
                    ("reason", "bound live position exists while strategy is in shadow mode"),
                    ("position_id", live.PositionId),
                    ("side", live.Direction.ToString()),
                    ("quantity", live.Quantity),
                    ("average_price", live.AveragePrice),
                    ("ambiguous", ambiguous));
            }
            return true;
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
                ("evidence_state", _evidenceState),
                ("actionable", _evidenceWarmupComplete && !_evidenceActionsPaused),
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
                ("ever_leveraged", _coordinator.EverLeveraged),
                ("active_adverse_failure_ids", string.Join(",",
                    _coordinator.ActiveAdverseFailureIds.OrderBy(id => id))));
            if (_lastLoggedState == RuntimeExecutionState.Paused)
            {
                _events.Write("entry_paused",
                    ("directive_id", _coordinator.Directive?.Id),
                    ("active_adverse_failure_ids", string.Join(",",
                        _coordinator.ActiveAdverseFailureIds.OrderBy(id => id))));
                LogOperator($"Directive {_coordinator.Directive?.Id ?? "none"}: entry paused "
                    + $"by local adverse failure object(s) "
                    + $"{string.Join(",", _coordinator.ActiveAdverseFailureIds.OrderBy(id => id))}.");
            }
            else if (previous == RuntimeExecutionState.Paused
                && _lastLoggedState == RuntimeExecutionState.Armed)
            {
                _events.Write("entry_pause_cleared",
                    ("directive_id", _coordinator.Directive?.Id));
                LogOperator($"Directive {_coordinator.Directive?.Id ?? "none"}: "
                    + "local adverse failure cleared; entry re-armed.");
            }
            else
            {
                LogOperator($"Directive {_coordinator.Directive?.Id ?? "none"}: "
                    + $"{previous} -> {_lastLoggedState}.",
                    error: _lastLoggedState == RuntimeExecutionState.Error
                        || _lastLoggedState == RuntimeExecutionState.Halted);
            }
        }

        private void LogCoordinatorAudit()
        {
            if (_coordinator == null || _events == null)
                return;
            foreach (CoordinatorAuditEvent audit in _coordinator.DrainAuditEvents())
            {
                double? parentLower = audit.ParentMinTick.HasValue
                    ? audit.ParentMinTick.Value * _tickSize
                    : null;
                double? parentUpper = audit.ParentMaxTick.HasValue
                    ? audit.ParentMaxTick.Value * _tickSize
                    : null;
                double? childLower = audit.ChildMinTick.HasValue
                    ? audit.ChildMinTick.Value * _tickSize
                    : null;
                double? childUpper = audit.ChildMaxTick.HasValue
                    ? audit.ChildMaxTick.Value * _tickSize
                    : null;
                _events.Write(audit.EventType,
                    ("directive_id", audit.DirectiveId),
                    ("reason", audit.Reason),
                    ("event_utc", audit.TimeUtc.ToString("O", CultureInfo.InvariantCulture)),
                    ("parent_id", audit.ParentObjectId),
                    ("parent_side", audit.ParentSide.HasValue
                        ? audit.ParentSide.Value.ToString()
                        : null),
                    ("parent_min_tick", audit.ParentMinTick),
                    ("parent_max_tick", audit.ParentMaxTick),
                    ("parent_lower", parentLower),
                    ("parent_upper", parentUpper),
                    ("child_id", audit.ChildObjectId),
                    ("child_source", audit.ChildSource.HasValue
                        ? audit.ChildSource.Value.ToString()
                        : null),
                    ("child_min_tick", audit.ChildMinTick),
                    ("child_max_tick", audit.ChildMaxTick),
                    ("child_lower", childLower),
                    ("child_upper", childUpper));
            }
        }

        private void LogSponsorIfChanged()
        {
            if (_coordinator == null
                || _coordinator.SponsorVersion <= _lastLoggedSponsorVersion)
            {
                return;
            }
            _lastLoggedSponsorVersion = _coordinator.SponsorVersion;
            SponsorContext sponsor = _coordinator.CurrentSponsor;
            if (sponsor == null)
            {
                SponsorClearContext cleared = _coordinator.LastSponsorClear;
                if (cleared?.Sponsor == null)
                    return;
                SponsorContext prior = cleared.Sponsor;
                _events.Write("sponsor_cleared",
                    ("directive_id", _coordinator.Directive?.Id),
                    ("sponsor_id", prior.ObjectId),
                    ("prior_sponsor_id", prior.PriorObjectId),
                    ("side", prior.Side.ToString()),
                    ("source", prior.Source.ToString()),
                    ("lower", prior.MinTick * _tickSize),
                    ("upper", prior.MaxTick * _tickSize),
                    ("promotion_reason", prior.Reason),
                    ("flatten_reason", cleared.FlattenReason),
                    ("epoch", prior.Epoch),
                    ("promoted_utc", prior.PromotedUtc.ToString("O")),
                    ("cleared_utc", cleared.ClearedUtc.ToString("O")));
                return;
            }
            double lower = sponsor.MinTick * _tickSize;
            double upper = sponsor.MaxTick * _tickSize;
            _events.Write("sponsor_promoted",
                ("directive_id", _coordinator.Directive?.Id),
                ("sponsor_id", sponsor.ObjectId),
                ("prior_sponsor_id", sponsor.PriorObjectId),
                ("side", sponsor.Side.ToString()),
                ("source", sponsor.Source.ToString()),
                ("lower", lower),
                ("upper", upper),
                ("reason", sponsor.Reason),
                ("epoch", sponsor.Epoch),
                ("promoted_utc", sponsor.PromotedUtc.ToString("O")));
            LogOperator($"Sponsor promoted for directive {_coordinator.Directive?.Id}: "
                + $"id={sponsor.ObjectId}, prior={sponsor.PriorObjectId?.ToString() ?? "none"}, "
                + $"{sponsor.Side} {lower:R}-{upper:R}, "
                + $"reason={sponsor.Reason}.");
        }

        private void LogIntentResult(OrderIntent intent, GatewayResult result,
            RuntimePosition position, ExecutableMarket market)
        {
            string detail = intent.Kind switch
            {
                OrderIntentKind.EnterBase => $"base submission qty={intent.Quantity:R}",
                OrderIntentKind.Add => $"add submission qty={intent.Quantity:R}",
                OrderIntentKind.Flatten => $"market flatten reason={intent.Reason}",
                OrderIntentKind.EnsureHardTarget => $"HARD_TP protection at {intent.Price:R}",
                OrderIntentKind.EnsureBreakeven => $"recovery weighted-BE protection at {intent.Price:R}",
                OrderIntentKind.CancelRuntimeOrders => $"runtime-order cancellation reason={intent.Reason}",
                _ => intent.Kind.ToString(),
            };
            if (result.Accepted)
            {
                if (intent.Kind == OrderIntentKind.Flatten
                    && intent.Reason?.StartsWith("sponsor_", StringComparison.Ordinal) == true)
                {
                    SponsorContext sponsor = _coordinator.CurrentSponsor;
                    _events.Write("sponsor_failed",
                        ("directive_id", intent.DirectiveId),
                        ("sponsor_id", sponsor?.ObjectId),
                        ("side", sponsor?.Side.ToString()),
                        ("lower", sponsor == null ? null : sponsor.MinTick * _tickSize),
                        ("upper", sponsor == null ? null : sponsor.MaxTick * _tickSize),
                        ("reason", intent.Reason),
                        ("flatten_accepted", true));
                    LogSponsorFailureContext(intent, position, market);
                }
                if (intent.Kind == OrderIntentKind.CancelRuntimeOrders
                    && intent.Reason?.EndsWith(
                        "_sponsor_failed_while_flat", StringComparison.Ordinal) == true)
                {
                    _events.Write("directive_invalidated",
                        ("directive_id", intent.DirectiveId),
                        ("reason", intent.Reason));
                    LogOperator($"Directive {intent.DirectiveId} invalidated: "
                        + $"{intent.Reason}.");
                    return;
                }
                bool safety = intent.Kind == OrderIntentKind.Flatten
                    && (string.Equals(intent.Reason, "HF", StringComparison.Ordinal)
                        || string.Equals(intent.Reason, "LF", StringComparison.Ordinal)
                        || intent.Reason?.StartsWith("sponsor_", StringComparison.Ordinal) == true
                        || intent.Reason?.StartsWith("forward_data_loss", StringComparison.Ordinal) == true
                        || intent.Reason?.StartsWith("protection_failed", StringComparison.Ordinal) == true);
                LogOperator($"Directive {intent.DirectiveId}: {detail} accepted "
                    + $"({(result.Shadow ? "SHADOW" : "LIVE")}).", error: safety);
                return;
            }
            LogOperator($"Directive {intent.DirectiveId}: {detail} rejected: "
                + $"{result.Message}.", error: true);
        }

        private void LogSponsorFailureContext(OrderIntent intent,
            RuntimePosition position,
            ExecutableMarket market)
        {
            SponsorContext sponsor = _coordinator.CurrentSponsor;
            if (sponsor == null || _evidence == null)
                return;

            TradeDirection direction = _coordinator.Directive?.Direction
                ?? (sponsor.Side == EvidenceSide.Demand
                    ? TradeDirection.Long
                    : TradeDirection.Short);
            DateTime failureUtc = ToUtc(intent.TriggerUtc == default
                ? DateTime.UtcNow
                : intent.TriggerUtc);
            EvidenceSide adverseSide = Opposite(sponsor.Side);
            IReadOnlyList<EvidenceBandView> adverseRails =
                _evidence.LiveRails(adverseSide);
            IReadOnlyList<EvidenceBandView> sameSideRails =
                _evidence.LiveRails(sponsor.Side);
            List<EvidenceBandView> adverseAhead = adverseRails
                .Where(band => IsAdverseAhead(band, sponsor, direction))
                .ToList();
            List<EvidenceBandView> sameSideProtection = sameSideRails
                .Where(band => band.Id != sponsor.ObjectId
                    && IsSameSideProtection(band, sponsor, direction))
                .ToList();
            List<EvidenceBandView> sameSideAhead = sameSideRails
                .Where(band => band.Id != sponsor.ObjectId
                    && IsSameSideAhead(band, sponsor, direction))
                .ToList();
            EvidenceBandView priorBand = sponsor.PriorObjectId.HasValue
                ? _evidence.FindBand(sponsor.PriorObjectId.Value)
                : null;
            long? lastMidTick = _evidence.LastMidTick;
            long? executableTick = market != null && market.IsValid
                ? PriceToTick(market.Executable(direction))
                : null;

            _events.Write("sponsor_failure_context",
                ("directive_id", intent.DirectiveId),
                ("sponsor_id", sponsor.ObjectId),
                ("prior_sponsor_id", sponsor.PriorObjectId),
                ("failure_reason", intent.Reason),
                ("failure_utc", failureUtc.ToString("O", CultureInfo.InvariantCulture)),
                ("side", sponsor.Side.ToString()),
                ("source", sponsor.Source.ToString()),
                ("lower", sponsor.MinTick * _tickSize),
                ("upper", sponsor.MaxTick * _tickSize),
                ("promotion_reason", sponsor.Reason),
                ("epoch", sponsor.Epoch),
                ("promoted_utc", sponsor.PromotedUtc.ToString("O", CultureInfo.InvariantCulture)),
                ("position_quantity", position?.Quantity),
                ("position_average", position?.AveragePrice),
                ("bid", market?.Bid),
                ("ask", market?.Ask),
                ("last_mid_tick", lastMidTick),
                ("executable_distance_ticks", executableTick.HasValue
                    ? DistanceToRange(executableTick.Value, sponsor.MinTick,
                        sponsor.MaxTick)
                    : null),
                ("ever_leveraged", _coordinator.EverLeveraged),
                ("active_adverse_failure_ids", string.Join(",",
                    _coordinator.ActiveAdverseFailureIds.OrderBy(id => id))),
                ("live_adverse_ahead_count", adverseAhead.Count),
                ("live_adverse_ahead",
                    BuildBandAudits(adverseAhead, sponsor, direction)),
                ("live_same_side_protection_count", sameSideProtection.Count),
                ("live_same_side_protection",
                    BuildBandAudits(sameSideProtection, sponsor, direction)),
                ("live_same_side_ahead_count", sameSideAhead.Count),
                ("live_same_side_ahead",
                    BuildBandAudits(sameSideAhead, sponsor, direction)),
                ("prior_sponsor_live", priorBand?.IsLiveRail ?? false),
                ("prior_sponsor", priorBand == null
                    ? null
                    : BuildBandAudit(priorBand, sponsor, direction)));

            RegisterSponsorFailureAudit(new PendingSponsorFailureAudit
            {
                DirectiveId = intent.DirectiveId,
                SponsorId = sponsor.ObjectId,
                SponsorSide = sponsor.Side,
                Direction = direction,
                SponsorMinTick = sponsor.MinTick,
                SponsorMaxTick = sponsor.MaxTick,
                FailureReason = intent.Reason,
                FailureUtc = failureUtc,
                ExpiresUtc = failureUtc.AddSeconds(SponsorFailureRebuildWindowSeconds),
                HadAdverseAheadAtFailure = adverseAhead.Count > 0,
                HadSameSideProtectionAtFailure = sameSideProtection.Count > 0,
                PriorSponsorLiveAtFailure = priorBand?.IsLiveRail ?? false,
            });
        }

        private void RegisterSponsorFailureAudit(PendingSponsorFailureAudit audit)
        {
            if (audit == null)
                return;
            _pendingSponsorFailureAudits.RemoveAll(existing =>
                string.Equals(existing.DirectiveId, audit.DirectiveId,
                    StringComparison.Ordinal)
                && existing.SponsorId == audit.SponsorId);
            _pendingSponsorFailureAudits.Add(audit);
        }

        private void ObserveSponsorFailureRebuild(EvidenceTransition transition)
        {
            if (_pendingSponsorFailureAudits.Count == 0 || transition?.Band == null)
                return;
            DateTime eventUtc = ToUtc(transition.TimeUtc);
            for (int i = _pendingSponsorFailureAudits.Count - 1; i >= 0; i--)
            {
                PendingSponsorFailureAudit audit = _pendingSponsorFailureAudits[i];
                if (eventUtc < audit.FailureUtc)
                    continue;
                if (eventUtc > audit.ExpiresUtc)
                {
                    LogSponsorFailureNoRebuild(audit, eventUtc);
                    _pendingSponsorFailureAudits.RemoveAt(i);
                    continue;
                }
                if (transition.Kind != EvidenceTransitionKind.RailOwned
                    || !IsRelevantRebuildBand(audit, transition.Band))
                {
                    continue;
                }
                EvidenceBandAudit rebuild = BuildBandAudit(
                    transition.Band,
                    audit.SponsorMinTick,
                    audit.SponsorMaxTick,
                    audit.Direction);
                _events.Write("sponsor_failure_rebuild",
                    ("directive_id", audit.DirectiveId),
                    ("sponsor_id", audit.SponsorId),
                    ("failure_reason", audit.FailureReason),
                    ("failure_utc", audit.FailureUtc.ToString("O", CultureInfo.InvariantCulture)),
                    ("seconds_after_failure",
                        Math.Max(0, (eventUtc - audit.FailureUtc).TotalSeconds)),
                    ("window_seconds", SponsorFailureRebuildWindowSeconds),
                    ("band", rebuild),
                    ("event_utc", eventUtc.ToString("O", CultureInfo.InvariantCulture)),
                    ("current_mid_tick", transition.CurrentMidTick),
                    ("current_mid", transition.CurrentMidTick * _tickSize),
                    ("had_adverse_ahead_at_failure", audit.HadAdverseAheadAtFailure),
                    ("had_same_side_protection_at_failure",
                        audit.HadSameSideProtectionAtFailure),
                    ("prior_sponsor_live_at_failure", audit.PriorSponsorLiveAtFailure));
                _pendingSponsorFailureAudits.RemoveAt(i);
            }
        }

        private void ExpireSponsorFailureAudits(DateTime nowUtc)
        {
            if (_pendingSponsorFailureAudits.Count == 0)
                return;
            nowUtc = ToUtc(nowUtc);
            for (int i = _pendingSponsorFailureAudits.Count - 1; i >= 0; i--)
            {
                PendingSponsorFailureAudit audit = _pendingSponsorFailureAudits[i];
                if (nowUtc < audit.ExpiresUtc)
                    continue;
                LogSponsorFailureNoRebuild(audit, nowUtc);
                _pendingSponsorFailureAudits.RemoveAt(i);
            }
        }

        private void LogSponsorFailureNoRebuild(PendingSponsorFailureAudit audit,
            DateTime observedUntilUtc)
        {
            _events.Write("sponsor_failure_no_rebuild",
                ("directive_id", audit.DirectiveId),
                ("sponsor_id", audit.SponsorId),
                ("failure_reason", audit.FailureReason),
                ("failure_utc", audit.FailureUtc.ToString("O", CultureInfo.InvariantCulture)),
                ("observed_until_utc",
                    ToUtc(observedUntilUtc).ToString("O", CultureInfo.InvariantCulture)),
                ("window_seconds", SponsorFailureRebuildWindowSeconds),
                ("had_adverse_ahead_at_failure", audit.HadAdverseAheadAtFailure),
                ("had_same_side_protection_at_failure",
                    audit.HadSameSideProtectionAtFailure),
                ("prior_sponsor_live_at_failure", audit.PriorSponsorLiveAtFailure));
        }

        private bool IsRelevantRebuildBand(PendingSponsorFailureAudit audit,
            EvidenceBandView band)
            => band.Role == EvidenceRole.Rail
                && band.Side == audit.SponsorSide
                && band.Id != audit.SponsorId
                && RangeDistanceTicks(
                    band.MinTick,
                    band.MaxTick,
                    audit.SponsorMinTick,
                    audit.SponsorMaxTick) <= SponsorFailureRebuildMaxDistanceTicks;

        private static EvidenceSide Opposite(EvidenceSide side)
            => side == EvidenceSide.Demand ? EvidenceSide.Supply : EvidenceSide.Demand;

        private static bool IsAdverseAhead(EvidenceBandView band,
            SponsorContext sponsor,
            TradeDirection direction)
            => direction == TradeDirection.Long
                ? band.MaxTick >= sponsor.MinTick
                : band.MinTick <= sponsor.MaxTick;

        private static bool IsSameSideProtection(EvidenceBandView band,
            SponsorContext sponsor,
            TradeDirection direction)
            => direction == TradeDirection.Long
                ? band.MaxTick < sponsor.MinTick
                : band.MinTick > sponsor.MaxTick;

        private static bool IsSameSideAhead(EvidenceBandView band,
            SponsorContext sponsor,
            TradeDirection direction)
            => direction == TradeDirection.Long
                ? band.MinTick > sponsor.MaxTick
                : band.MaxTick < sponsor.MinTick;

        private List<EvidenceBandAudit> BuildBandAudits(
            IEnumerable<EvidenceBandView> bands,
            SponsorContext sponsor,
            TradeDirection direction)
            => bands
                .OrderBy(band => RangeDistanceTicks(
                    band.MinTick,
                    band.MaxTick,
                    sponsor.MinTick,
                    sponsor.MaxTick))
                .ThenBy(band => band.Id)
                .Take(SponsorContextRailLimit)
                .Select(band => BuildBandAudit(band, sponsor, direction))
                .ToList();

        private EvidenceBandAudit BuildBandAudit(EvidenceBandView band,
            SponsorContext sponsor,
            TradeDirection direction)
            => BuildBandAudit(band, sponsor.MinTick, sponsor.MaxTick, direction);

        private EvidenceBandAudit BuildBandAudit(EvidenceBandView band,
            long referenceMinTick,
            long referenceMaxTick,
            TradeDirection direction)
            => new()
            {
                Id = band.Id,
                Side = band.Side.ToString(),
                Source = band.Source.ToString(),
                State = band.State.ToString(),
                Lower = band.MinTick * _tickSize,
                Upper = band.MaxTick * _tickSize,
                Relation = DirectionalRelation(
                    band.MinTick,
                    band.MaxTick,
                    referenceMinTick,
                    referenceMaxTick,
                    direction),
                DistanceTicks = RangeDistanceTicks(
                    band.MinTick,
                    band.MaxTick,
                    referenceMinTick,
                    referenceMaxTick),
                FormedUtc = band.FormedUtc == default
                    ? null
                    : ToUtc(band.FormedUtc).ToString("O", CultureInfo.InvariantCulture),
                OwnedUtc = band.OwnedUtc == default
                    ? null
                    : ToUtc(band.OwnedUtc).ToString("O", CultureInfo.InvariantCulture),
                LastStateUtc = band.LastStateUtc == default
                    ? null
                    : ToUtc(band.LastStateUtc).ToString("O", CultureInfo.InvariantCulture),
                FailedUtc = band.FailedUtc.HasValue
                    ? ToUtc(band.FailedUtc.Value).ToString("O", CultureInfo.InvariantCulture)
                    : null,
                Events = band.EventCount,
                Score = band.Score,
            };

        private static string DirectionalRelation(long minTick,
            long maxTick,
            long referenceMinTick,
            long referenceMaxTick,
            TradeDirection direction)
        {
            if (maxTick < referenceMinTick)
                return direction == TradeDirection.Long ? "behind" : "ahead";
            if (minTick > referenceMaxTick)
                return direction == TradeDirection.Long ? "ahead" : "behind";
            return "overlap";
        }

        private static long RangeDistanceTicks(long minTick,
            long maxTick,
            long referenceMinTick,
            long referenceMaxTick)
        {
            if (maxTick < referenceMinTick)
                return referenceMinTick - maxTick;
            if (referenceMaxTick < minTick)
                return minTick - referenceMaxTick;
            return 0;
        }

        private static DateTime ToUtc(DateTime value)
        {
            if (value == default)
                return DateTime.SpecifyKind(DateTime.MinValue, DateTimeKind.Utc);
            return value.Kind == DateTimeKind.Local
                ? value.ToUniversalTime()
                : DateTime.SpecifyKind(value, DateTimeKind.Utc);
        }

        private void LogOperator(string message, bool error = false)
        {
            string text = $"[EAR] {message}";
            if (error)
                Log(text, StrategyLoggingLevel.Error);
            else
                Log(text);
        }

        private void Subscribe()
        {
            _marketDataSymbol.NewQuote += Symbol_NewQuote;
            _marketDataSymbol.NewLevel2 += Symbol_NewLevel2;
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
            try
            {
                if (_marketDataSymbol != null)
                    _marketDataSymbol.NewQuote -= Symbol_NewQuote;
            }
            catch { }
            try
            {
                if (_marketDataSymbol != null)
                    _marketDataSymbol.NewLevel2 -= Symbol_NewLevel2;
            }
            catch { }
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
            if (Interlocked.Exchange(ref _shutdownStarted, 1) != 0)
                return;
            _running = false;
            Timer timer = Interlocked.Exchange(ref _workerTimer, null);
            if (timer != null)
            {
                try
                {
                    var callbackDone = new ManualResetEvent(false);
                    bool notifyPending = timer.Dispose(callbackDone);
                    if (notifyPending
                        && !callbackDone.WaitOne(TimeSpan.FromSeconds(5)))
                    {
                        // Keep the handle alive so Timer can signal it if the
                        // in-flight callback eventually returns. A permanently
                        // stuck callback leaks this one handle for the remaining
                        // process lifetime; that is safer than disposing a handle
                        // the Timer may still signal during overdue shutdown.
                        _events?.Write("worker_shutdown_timeout");
                    }
                    else
                    {
                        callbackDone.Dispose();
                    }
                }
                catch { }
            }
            try { _gateway?.CancelEntryOrdersOnStop(); } catch { }
            try { SaveCheckpointIfDue(DateTime.UtcNow, force: true); } catch { }
            try { _events?.Write(eventType, ("state", _coordinator?.State.ToString())); } catch { }
            Unsubscribe();
            try { _events?.Dispose(); } catch { }
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
            _evidenceActionsPaused = true;
            _evidenceEpochStartedUtc = DateTime.MinValue;
            _evidenceEpochSampleCount = 0;
            _evidenceWarmupComplete = false;
            _evidenceEpochReason = "startup";
            _evidenceState = "AwaitingBook";
            _bookContinuity.Reset();
            _runTradingEnabled = TradingEnabled;
            _lastDirectiveFileHash = null;
            _lastControlFileHash = null;
            _acceptedDirectiveRaw = null;
            _lastPositionSignature = null;
            _lastShadowLivePositionSignature = null;
            _shadowPosition = RuntimePosition.Flat;
            _shadowBreakeven = null;
            _shadowHardTarget = null;
            _lastLoggedState = RuntimeExecutionState.Idle;
            _lastLoggedSponsorVersion = 0;
            _submissions.Clear();
            _processedControlDigests.Clear();
            _processedControlOrder.Clear();
            _blockedDirectiveIds.Clear();
            _pendingSponsorFailureAudits.Clear();
            while (_brokerEvents.TryDequeue(out _)) { }
            lock (_orderSubscriptionGate)
                _subscribedOrders.Clear();
            Volatile.Write(ref _shutdownStarted, 0);
        }

        private bool ResolveAccountAndSymbol()
        {
            if (RuntimeSymbol == null)
            {
                Log("No symbol selected.", StrategyLoggingLevel.Error);
                return false;
            }
            _marketDataSymbol = MarketDataSymbol ?? RuntimeSymbol;
            if (_marketDataSymbol == null)
            {
                Log("No market data symbol selected.", StrategyLoggingLevel.Error);
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
            double executionTickSize = EffectiveTickSize(RuntimeSymbol);
            double marketDataTickSize = EffectiveTickSize(_marketDataSymbol);
            if (!TickSizesMatch(executionTickSize, marketDataTickSize))
            {
                Log($"Execution symbol {RuntimeSymbol.Name} tick size "
                    + $"{executionTickSize:R} does not match market data symbol "
                    + $"{_marketDataSymbol.Name} tick size {marketDataTickSize:R}.",
                    StrategyLoggingLevel.Error);
                return false;
            }
            _tickSize = marketDataTickSize;
            return true;
        }

        private static double EffectiveTickSize(Symbol symbol)
            => symbol != null && double.IsFinite(symbol.TickSize) && symbol.TickSize > 0
                ? symbol.TickSize
                : 0.25;

        private static bool TickSizesMatch(double left, double right)
            => Math.Abs(left - right) <= Math.Max(1e-9, Math.Max(left, right) * 1e-9);

        private static bool SameSymbol(Symbol left, Symbol right)
            => left != null && right != null
                && string.Equals(left.Id, right.Id, StringComparison.Ordinal)
                && string.Equals(left.ConnectionId, right.ConnectionId,
                    StringComparison.Ordinal);

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
            public string BrokerOrderId;
            public DateTime SubmitUtc;
            public double SubmitBid;
            public double SubmitAsk;
            public double PositionQuantityBefore;
            public bool FillObserved;
            public bool CancelRequested;
            public bool ReconciliationFailureLogged;
            public DateTime LastCancelAttemptUtc;
        }

        private sealed class BookSampleDiagnostic
        {
            public string Reason;
            public string Error;
            public DateTime? LastL2Utc;
            public double? L2AgeMs;
            public int? BidLevels;
            public int? AskLevels;
            public double? SymbolBid;
            public double? SymbolAsk;
            public double? DomBid;
            public double? DomAsk;
        }

        private sealed class PendingSponsorFailureAudit
        {
            public string DirectiveId;
            public int SponsorId;
            public EvidenceSide SponsorSide;
            public TradeDirection Direction;
            public long SponsorMinTick;
            public long SponsorMaxTick;
            public string FailureReason;
            public DateTime FailureUtc;
            public DateTime ExpiresUtc;
            public bool HadAdverseAheadAtFailure;
            public bool HadSameSideProtectionAtFailure;
            public bool PriorSponsorLiveAtFailure;
        }

        private sealed class EvidenceBandAudit
        {
            public int Id { get; init; }
            public string Side { get; init; }
            public string Source { get; init; }
            public string State { get; init; }
            public double Lower { get; init; }
            public double Upper { get; init; }
            public string Relation { get; init; }
            public long DistanceTicks { get; init; }
            public string FormedUtc { get; init; }
            public string OwnedUtc { get; init; }
            public string LastStateUtc { get; init; }
            public string FailedUtc { get; init; }
            public int Events { get; init; }
            public double Score { get; init; }
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
            public string GroupId;

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
                    GroupId = order.GroupId,
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
