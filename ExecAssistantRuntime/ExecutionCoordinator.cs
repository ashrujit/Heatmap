using System;
using System.Collections.Generic;
using System.Linq;

namespace ExecAssistantRuntime
{
    internal enum RuntimeExecutionState
    {
        Idle,
        Waiting,
        Armed,
        BaseOnly,
        Leveraged,
        RecoveryProtected,
        Halting,
        Halted,
        Completed,
        Cancelled,
        Invalidated,
        Expired,
        Error,
    }

    internal enum OrderIntentKind
    {
        EnterBase,
        Add,
        Flatten,
        EnsureHardTarget,
        EnsureBreakeven,
        CancelRuntimeOrders,
    }

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

        public double Executable(TradeDirection direction)
            => direction == TradeDirection.Long ? Ask : Bid;
    }

    internal sealed class RuntimePosition
    {
        public static readonly RuntimePosition Flat = new() { Quantity = 0 };

        public string PositionId { get; init; }
        public TradeDirection Direction { get; init; }
        public double Quantity { get; init; }
        public double AveragePrice { get; init; }

        public bool IsFlat => Quantity <= 0;
    }

    internal sealed class ResolutionContext
    {
        public ResolutionType Resolution { get; init; }
        public int RootObjectId { get; init; }
        public int SupportObjectId { get; init; }
        public long RootMinTick { get; init; }
        public long RootMaxTick { get; init; }
        public long SupportMinTick { get; init; }
        public long SupportMaxTick { get; init; }
        public EvidenceSource SupportSource { get; init; }
        public DateTime RootFormedUtc { get; init; }
        public DateTime SupportFormedUtc { get; init; }
        public DateTime TriggerUtc { get; init; }
    }

    internal sealed class SponsorContext
    {
        public int ObjectId { get; init; }
        public int? PriorObjectId { get; init; }
        public EvidenceSide Side { get; init; }
        public EvidenceSource Source { get; init; }
        public long MinTick { get; init; }
        public long MaxTick { get; init; }
        public DateTime FormedUtc { get; init; }
        public DateTime PromotedUtc { get; init; }
        public string Reason { get; init; }
        public int Epoch { get; init; }
    }

    internal sealed class SponsorClearContext
    {
        public SponsorContext Sponsor { get; init; }
        public string FlattenReason { get; init; }
        public DateTime ClearedUtc { get; init; }
    }

    internal sealed class OrderIntent
    {
        public string IntentId { get; init; }
        public OrderIntentKind Kind { get; init; }
        public TradeDirection Direction { get; init; }
        public double Quantity { get; init; }
        public double Price { get; init; }
        public string Reason { get; init; }
        public string DirectiveId { get; init; }
        public int Epoch { get; init; }
        public DateTime TriggerUtc { get; init; }
        public double TriggerBid { get; init; }
        public double TriggerAsk { get; init; }
        public ResolutionContext Resolution { get; init; }
        public bool TerminalAfterFlat { get; init; }
        public bool RearmAfterFlat { get; init; }
    }

    internal sealed class ExecutionCoordinator
    {
        private const int SupportedCandidateSeconds = 4;
        private const int SupportedCandidateMaxDistanceTicks = 20;
        private const int DirectConversionMaxDistanceTicks = 20;
        private const int ReverseResolutionProximityTicks = 20;

        private readonly double _tickSize;
        private readonly HashSet<int> _usedRootObjectIds = new();
        private readonly HashSet<int> _baselineFailureIds = new();
        private TradeDirective _directive;
        private DateTime _activatedUtc;
        private DateTime _freshRootAfterUtc;
        private DateTime _lastFillUtc;
        private int _epoch;
        private int _baseAttempts;
        private bool _everLeveraged;
        private bool _entryAnchorFailed;
        private ResolutionContext _entryContext;
        private PendingReclaim _pendingReclaim;
        private PendingDirectRetest _pendingRetest;
        private OrderIntent _pendingEntryIntent;
        private FlattenDisposition _flattenDisposition;
        private double _lastKnownQuantity;
        private double _lastKnownAveragePrice;
        private SponsorContext _currentSponsor;
        private SponsorClearContext _lastSponsorClear;
        private int _sponsorVersion;

        public ExecutionCoordinator(double tickSize)
        {
            _tickSize = double.IsFinite(tickSize) && tickSize > 0 ? tickSize : 0.25;
        }

        public RuntimeExecutionState State { get; private set; } = RuntimeExecutionState.Idle;
        public TradeDirective Directive => _directive;
        public int BaseAttempts => _baseAttempts;
        public bool EverLeveraged => _everLeveraged;
        public bool HasPendingEntryOrder => _pendingEntryIntent != null;
        public SponsorContext CurrentSponsor => _currentSponsor;
        public SponsorClearContext LastSponsorClear => _lastSponsorClear;
        public int SponsorVersion => _sponsorVersion;

        public void AcceptDirective(
            TradeDirective directive,
            DateTime nowUtc,
            IEnumerable<int> existingHeldFailureIds)
        {
            if (directive == null)
                throw new ArgumentNullException(nameof(directive));
            if (_directive != null && !IsTerminal(State)
                && State != RuntimeExecutionState.Halted)
                throw new InvalidOperationException("A directive is already active.");

            _directive = directive;
            _activatedUtc = NormalizeUtc(nowUtc);
            _freshRootAfterUtc = _activatedUtc;
            _lastFillUtc = DateTime.MinValue;
            _epoch = 0;
            _baseAttempts = 0;
            _everLeveraged = false;
            _entryAnchorFailed = false;
            _entryContext = null;
            _pendingReclaim = null;
            _pendingRetest = null;
            _pendingEntryIntent = null;
            _flattenDisposition = null;
            _lastKnownQuantity = 0;
            _lastKnownAveragePrice = 0;
            _currentSponsor = null;
            _lastSponsorClear = null;
            _sponsorVersion = 0;
            _usedRootObjectIds.Clear();
            _baselineFailureIds.Clear();
            if (existingHeldFailureIds != null)
            {
                foreach (int id in existingHeldFailureIds)
                    _baselineFailureIds.Add(id);
            }
            State = directive.NotBefore.UtcDateTime > _activatedUtc
                ? RuntimeExecutionState.Waiting
                : RuntimeExecutionState.Armed;
        }

        public IReadOnlyList<OrderIntent> Tick(
            DateTime nowUtc,
            ExecutableMarket market,
            RuntimePosition position,
            ExecutionEvidenceEngine evidence,
            bool evidenceAvailable = true)
        {
            var intents = new List<OrderIntent>();
            if (_directive == null || IsTerminal(State)
                || State == RuntimeExecutionState.Halted
                || State == RuntimeExecutionState.Halting)
                return intents;

            nowUtc = NormalizeUtc(nowUtc);
            position ??= RuntimePosition.Flat;
            if (State == RuntimeExecutionState.Waiting
                && nowUtc >= _directive.NotBefore.UtcDateTime)
            {
                State = RuntimeExecutionState.Armed;
            }

            if (position.IsFlat && nowUtc > _directive.ExpiresAt.UtcDateTime
                && (State == RuntimeExecutionState.Armed || State == RuntimeExecutionState.Waiting))
            {
                State = RuntimeExecutionState.Expired;
                return intents;
            }

            if (position.IsFlat && State == RuntimeExecutionState.Armed
                && PreEntryInvalidated(market))
            {
                State = RuntimeExecutionState.Invalidated;
                return intents;
            }

            if (!evidenceAvailable)
                return intents;

            if (_pendingEntryIntent == null
                && (State == RuntimeExecutionState.Armed
                    || State == RuntimeExecutionState.BaseOnly
                    || State == RuntimeExecutionState.Leveraged))
            {
                OrderIntent pending = TryCompletePendingReclaim(nowUtc, market, evidence, position);
                if (pending != null)
                    intents.Add(pending);
                else
                {
                    pending = TryCompleteDirectRetest(nowUtc, market, evidence, position);
                    if (pending != null)
                        intents.Add(pending);
                }
            }

            if (State == RuntimeExecutionState.BaseOnly && !position.IsFlat
                && CandidateSupportBecameAmbiguous(evidence))
            {
                intents.Add(CreateFlattenIntent(nowUtc, market,
                    "base_support_lost", terminal: false, rearm: true));
            }
            return intents;
        }

        public IReadOnlyList<OrderIntent> ProcessEvidence(
            IReadOnlyList<EvidenceTransition> transitions,
            DateTime nowUtc,
            ExecutableMarket market,
            RuntimePosition position,
            ExecutionEvidenceEngine evidence)
        {
            var intents = new List<OrderIntent>();
            if (_directive == null || transitions == null || IsTerminal(State)
                || State == RuntimeExecutionState.Halted
                || State == RuntimeExecutionState.Halting
                || State == RuntimeExecutionState.RecoveryProtected)
            {
                return intents;
            }

            position ??= RuntimePosition.Flat;
            nowUtc = NormalizeUtc(nowUtc);
            if (position.IsFlat && nowUtc > _directive.ExpiresAt.UtcDateTime
                && (State == RuntimeExecutionState.Armed
                    || State == RuntimeExecutionState.Waiting))
            {
                State = RuntimeExecutionState.Expired;
                return intents;
            }
            if (position.IsFlat && State == RuntimeExecutionState.Armed
                && PreEntryInvalidated(market))
            {
                State = RuntimeExecutionState.Invalidated;
                return intents;
            }
            EvidenceTransition terminalFailure = transitions.FirstOrDefault(transition =>
                transition?.Kind == EvidenceTransitionKind.FailureHeld
                && transition.Band != null
                && !_baselineFailureIds.Contains(transition.Band.Id)
                && transition.TimeUtc >= _activatedUtc
                && OppositeFailureFlattens(transition.Band));
            if (terminalFailure != null)
            {
                string reason = terminalFailure.Band.Side == EvidenceSide.Demand ? "LF" : "HF";
                if (position.IsFlat)
                {
                    InvalidateWhileFlat();
                    intents.Add(CreateCancelOrdersIntent(
                        terminalFailure.TimeUtc, market, $"{reason}_while_flat"));
                }
                else
                {
                    intents.Add(CreateFlattenIntent(terminalFailure.TimeUtc, market,
                        reason, terminal: true, rearm: false));
                }
                return intents;
            }
            foreach (EvidenceTransition transition in transitions)
            {
                if (transition == null)
                    continue;

                OrderIntent sponsorFailure = EvaluateSponsorFailure(
                    transition, market, position);
                if (sponsorFailure != null)
                {
                    intents.Add(sponsorFailure);
                    break;
                }

                if (!position.IsFlat)
                    TryPromoteSponsor(transition);

                if (State == RuntimeExecutionState.BaseOnly && !position.IsFlat)
                {
                    OrderIntent stop = EvaluateBaseStop(transition, market);
                    if (stop != null)
                    {
                        intents.Add(stop);
                        break;
                    }
                }

                if (_pendingEntryIntent != null || State == RuntimeExecutionState.Waiting)
                    continue;

                bool mayEnter = position.IsFlat && State == RuntimeExecutionState.Armed;
                bool mayAdd = !position.IsFlat
                    && (State == RuntimeExecutionState.BaseOnly || State == RuntimeExecutionState.Leveraged)
                    && _directive.AddsAllowed
                    && nowUtc <= _directive.ExpiresAt.UtcDateTime
                    && position.Quantity + _directive.AddQuantity <= _directive.MaxPositionQuantity;
                if (!mayEnter && !mayAdd)
                    continue;

                OrderIntent intent = null;
                if (transition.Kind == EvidenceTransitionKind.RailOwned
                    && transition.Band?.Source == EvidenceSource.Consumed
                    && transition.Band.Side == DesiredEvidenceSide()
                    && _directive.AllowedResolutions.Contains(ResolutionType.DirectConversion))
                {
                    intent = EvaluateDirectConversion(transition, market, position, mayAdd);
                }
                else if (transition.Kind == EvidenceTransitionKind.RailFailed
                    && transition.Band != null
                    && transition.Band.Side != DesiredEvidenceSide()
                    && _directive.AllowedResolutions.Contains(ResolutionType.SupportedReclaim))
                {
                    intent = EvaluateSupportedReclaim(
                        transition, market, position, evidence, mayAdd);
                }

                if (intent != null)
                {
                    intents.Add(intent);
                    break;
                }
            }

            if (intents.Count == 0 && _pendingEntryIntent == null
                && (State == RuntimeExecutionState.Armed
                    || State == RuntimeExecutionState.BaseOnly
                    || State == RuntimeExecutionState.Leveraged))
            {
                OrderIntent pending = TryCompletePendingReclaim(nowUtc, market, evidence, position);
                if (pending != null)
                    intents.Add(pending);
            }
            return intents;
        }

        public IReadOnlyList<OrderIntent> OnPositionChanged(
            RuntimePosition position,
            DateTime nowUtc,
            ExecutableMarket market)
        {
            var intents = new List<OrderIntent>();
            position ??= RuntimePosition.Flat;
            nowUtc = NormalizeUtc(nowUtc);
            double previousQuantity = _lastKnownQuantity;
            double previousAverage = _lastKnownAveragePrice;
            _lastKnownQuantity = position.Quantity;
            _lastKnownAveragePrice = position.AveragePrice;

            if (_pendingEntryIntent != null && position.Quantity > previousQuantity)
            {
                OrderIntent filledIntent = _pendingEntryIntent;
                _pendingEntryIntent = null;
                _lastFillUtc = nowUtc;
                _freshRootAfterUtc = nowUtc;
                _entryAnchorFailed = false;
                if (filledIntent.Kind == OrderIntentKind.EnterBase)
                {
                    _entryContext = filledIntent.Resolution;
                    State = RuntimeExecutionState.BaseOnly;
                    PromoteFilledResolution(filledIntent.Resolution, nowUtc, "filled_entry");
                }
                else if (filledIntent.Kind == OrderIntentKind.Add)
                {
                    _everLeveraged = true;
                    State = RuntimeExecutionState.Leveraged;
                    PromoteFilledResolution(filledIntent.Resolution, nowUtc, "filled_add");
                }

                if (_directive.TargetMode == TargetMode.HardTp)
                {
                    intents.Add(CreateProtectionIntent(OrderIntentKind.EnsureHardTarget,
                        nowUtc, market, position, "position_fill"));
                }
                if (State == RuntimeExecutionState.Leveraged)
                {
                    intents.Add(CreateProtectionIntent(OrderIntentKind.EnsureBreakeven,
                        nowUtc, market, position, "first_or_later_add"));
                }
                return intents;
            }

            if (!position.IsFlat && position.Quantity < previousQuantity)
            {
                FlattenDisposition prior = _flattenDisposition;
                OrderIntent remainder = CreateFlattenIntent(nowUtc, market,
                    prior?.Reason ?? "partial_protective_or_external_exit",
                    terminal: prior?.TerminalAfterFlat ?? true,
                    rearm: prior?.RearmAfterFlat ?? false);
                if (prior != null)
                {
                    _flattenDisposition.HaltAfterFlat = prior.HaltAfterFlat;
                    _flattenDisposition.Cancelled = prior.Cancelled;
                }
                intents.Add(remainder);
                return intents;
            }

            if (!position.IsFlat && position.Quantity > 0
                && (position.Quantity != previousQuantity
                    || Math.Abs(position.AveragePrice - previousAverage) > 1e-9)
                && (State == RuntimeExecutionState.BaseOnly
                    || State == RuntimeExecutionState.Leveraged
                    || State == RuntimeExecutionState.RecoveryProtected))
            {
                if (_directive.TargetMode == TargetMode.HardTp)
                {
                    intents.Add(CreateProtectionIntent(OrderIntentKind.EnsureHardTarget,
                        nowUtc, market, position, "position_quantity_or_average_changed"));
                }
                if (State == RuntimeExecutionState.Leveraged
                    || State == RuntimeExecutionState.RecoveryProtected)
                {
                    intents.Add(CreateProtectionIntent(OrderIntentKind.EnsureBreakeven,
                        nowUtc, market, position, "position_quantity_or_average_changed"));
                }
                return intents;
            }

            if (position.IsFlat && previousQuantity > 0)
            {
                FlattenDisposition disposition = _flattenDisposition;
                _flattenDisposition = null;
                _pendingEntryIntent = null;
                _entryContext = null;
                _entryAnchorFailed = false;
                _pendingReclaim = null;
                _pendingRetest = null;
                if (_currentSponsor != null)
                {
                    _lastSponsorClear = new SponsorClearContext
                    {
                        Sponsor = _currentSponsor,
                        FlattenReason = disposition?.Reason
                            ?? "protective_or_external_exit",
                        ClearedUtc = nowUtc,
                    };
                    _sponsorVersion++;
                }
                _currentSponsor = null;

                if (disposition?.HaltAfterFlat == true)
                    State = RuntimeExecutionState.Halted;
                else if (disposition?.TerminalAfterFlat == true)
                    State = disposition.Cancelled
                        ? RuntimeExecutionState.Cancelled
                        : RuntimeExecutionState.Completed;
                else if (disposition?.RearmAfterFlat == true
                    && !_everLeveraged
                    && _baseAttempts <= _directive.MaxBaseReentries
                    && nowUtc <= _directive.ExpiresAt.UtcDateTime)
                {
                    State = RuntimeExecutionState.Armed;
                    _freshRootAfterUtc = nowUtc;
                }
                else
                {
                    State = RuntimeExecutionState.Completed;
                }
            }
            return intents;
        }

        public void OnOrderAttemptResult(OrderIntent intent, bool accepted)
        {
            if (intent == null)
                return;
            if (intent.Kind == OrderIntentKind.EnterBase || intent.Kind == OrderIntentKind.Add)
            {
                if (!accepted && ReferenceEquals(_pendingEntryIntent, intent))
                {
                    _pendingEntryIntent = null;
                    if (intent.Kind == OrderIntentKind.EnterBase
                        && _baseAttempts > _directive.MaxBaseReentries)
                    {
                        State = RuntimeExecutionState.Completed;
                    }
                }
            }
        }

        public void InitializeObservedPosition(RuntimePosition position)
        {
            _lastKnownQuantity = position?.Quantity ?? 0;
            _lastKnownAveragePrice = position?.AveragePrice ?? 0;
        }

        public OrderIntent TerminalFlatten(DateTime nowUtc, ExecutableMarket market, string reason)
            => CreateFlattenIntent(nowUtc, market, reason, terminal: true, rearm: false);

        public OrderIntent SafetyFlatten(DateTime nowUtc, ExecutableMarket market, string reason)
        {
            State = RuntimeExecutionState.Halting;
            OrderIntent intent = CreateFlattenIntent(nowUtc, market, reason,
                terminal: true, rearm: false);
            _flattenDisposition.HaltAfterFlat = true;
            return intent;
        }

        public IReadOnlyList<OrderIntent> CancelDirective(
            DateTime nowUtc,
            ExecutableMarket market,
            RuntimePosition position)
        {
            var intents = new List<OrderIntent>();
            if (_directive == null || IsTerminal(State))
                return intents;
            intents.Add(CreateCancelOrdersIntent(nowUtc, market, "cancel_directive"));
            if (position != null && !position.IsFlat)
            {
                OrderIntent flatten = CreateFlattenIntent(nowUtc, market,
                    "cancel_directive", terminal: true, rearm: false);
                _flattenDisposition.Cancelled = true;
                intents.Add(flatten);
            }
            else
            {
                State = RuntimeExecutionState.Cancelled;
            }
            return intents;
        }

        public IReadOnlyList<OrderIntent> Flat(
            DateTime nowUtc,
            ExecutableMarket market,
            RuntimePosition position)
        {
            var intents = new List<OrderIntent>();
            State = RuntimeExecutionState.Halting;
            _pendingEntryIntent = null;
            intents.Add(CreateCancelOrdersIntent(nowUtc, market, "FLAT"));
            if (position != null && !position.IsFlat)
            {
                OrderIntent flatten = CreateFlattenIntent(nowUtc, market,
                    "FLAT", terminal: true, rearm: false);
                _flattenDisposition.HaltAfterFlat = true;
                intents.Add(flatten);
            }
            else
            {
                State = RuntimeExecutionState.Halted;
            }
            return intents;
        }

        public void EnterRecoveryProtected()
        {
            State = RuntimeExecutionState.RecoveryProtected;
            _pendingEntryIntent = null;
            _pendingReclaim = null;
            _pendingRetest = null;
            _currentSponsor = null;
        }

        public void MarkError()
        {
            State = RuntimeExecutionState.Error;
            _pendingEntryIntent = null;
        }

        private OrderIntent EvaluateDirectConversion(
            EvidenceTransition transition,
            ExecutableMarket market,
            RuntimePosition position,
            bool isAdd)
        {
            EvidenceBandView band = transition.Band;
            if (!RootEligible(band.Id, band.FormedUtc, isAdd) || !ContextEligible(band))
                return null;
            ResolutionContext resolution = new()
            {
                Resolution = ResolutionType.DirectConversion,
                RootObjectId = band.Id,
                SupportObjectId = band.Id,
                RootMinTick = band.MinTick,
                RootMaxTick = band.MaxTick,
                SupportMinTick = band.MinTick,
                SupportMaxTick = band.MaxTick,
                SupportSource = band.Source,
                RootFormedUtc = band.FormedUtc,
                SupportFormedUtc = band.FormedUtc,
                TriggerUtc = transition.TimeUtc,
            };

            if (!QuoteEligible(market, isAdd) || AtOrBeyondTarget(market))
                return null;
            long quoteTick = PriceToTick(market.Executable(_directive.Direction));
            if (RangeDistance(quoteTick, band.MinTick, band.MaxTick)
                <= DirectConversionMaxDistanceTicks)
            {
                return CreateEntryIntent(transition.TimeUtc, market, position,
                    resolution, isAdd, "direct_conversion");
            }

            _pendingRetest = new PendingDirectRetest
            {
                Resolution = resolution,
                IsAdd = isAdd,
            };
            return null;
        }

        private OrderIntent EvaluateSupportedReclaim(
            EvidenceTransition transition,
            ExecutableMarket market,
            RuntimePosition position,
            ExecutionEvidenceEngine evidence,
            bool isAdd)
        {
            EvidenceBandView failed = transition.Band;
            if (!RootEligible(failed.Id, failed.FormedUtc, isAdd)
                || !ContextEligible(failed))
                return null;
            if (!QuoteEligible(market, isAdd) || AtOrBeyondTarget(market))
            {
                _usedRootObjectIds.Add(failed.Id);
                return null;
            }

            EvidenceSide desired = DesiredEvidenceSide();
            EvidenceBandView confirmedSupport = evidence.LiveRails(desired)
                .Where(ContextEligible)
                .Where(s => CorrectTopology(s.MinTick, s.MaxTick, failed.MinTick, failed.MaxTick))
                .Where(s => RangeDistance(s.MinTick, s.MaxTick, failed.MinTick, failed.MaxTick)
                    <= SupportedCandidateMaxDistanceTicks)
                .OrderBy(s => RangeDistance(s.MinTick, s.MaxTick, failed.MinTick, failed.MaxTick))
                .FirstOrDefault();
            if (confirmedSupport != null)
            {
                ResolutionContext resolution = SupportedContext(failed, confirmedSupport,
                    transition.TimeUtc);
                return CreateEntryIntent(transition.TimeUtc, market, position,
                    resolution, isAdd, "supported_reclaim_confirmed");
            }

            EvidenceCandidateView candidate = evidence.ActiveCandidates(desired)
                .Where(c => c.Direction == CandidateDirection.Favor
                    && c.DirectionStartedUtc.HasValue)
                .Where(c => _directive.ContextPriceRange.Intersects(
                    TickToPrice(c.MinTick), TickToPrice(c.MaxTick)))
                .Where(c => CorrectTopology(c.MinTick, c.MaxTick, failed.MinTick, failed.MaxTick))
                .Where(c => RangeDistance(c.MinTick, c.MaxTick, failed.MinTick, failed.MaxTick)
                    <= SupportedCandidateMaxDistanceTicks)
                .OrderBy(c => RangeDistance(c.MinTick, c.MaxTick, failed.MinTick, failed.MaxTick))
                .FirstOrDefault();
            if (candidate == null)
                return null;

            _pendingReclaim = new PendingReclaim
            {
                FailedBand = failed,
                CandidateId = candidate.Id,
                CandidateDirectionStartedUtc = candidate.DirectionStartedUtc.Value,
                FailedUtc = transition.TimeUtc,
                IsAdd = isAdd,
            };
            return TryCompletePendingReclaim(
                transition.TimeUtc, market, evidence, position);
        }

        private OrderIntent TryCompletePendingReclaim(
            DateTime nowUtc,
            ExecutableMarket market,
            ExecutionEvidenceEngine evidence,
            RuntimePosition position)
        {
            PendingReclaim pending = _pendingReclaim;
            if (pending == null || _pendingEntryIntent != null)
                return null;
            bool stateStillMatches = PendingIntentMatchesState(
                pending.IsAdd, State, position);
            if (!stateStillMatches)
            {
                _pendingReclaim = null;
                return null;
            }
            EvidenceCandidateView candidate = evidence.FindCandidate(pending.CandidateId);
            EvidenceBandView failed = evidence.FindBand(pending.FailedBand.Id);
            if (candidate == null || !candidate.IsActive
                || candidate.Direction != CandidateDirection.Favor
                || candidate.DirectionStartedUtc != pending.CandidateDirectionStartedUtc
                || failed == null || failed.State != EvidenceState.Failed)
            {
                _pendingReclaim = null;
                return null;
            }

            if ((nowUtc - pending.CandidateDirectionStartedUtc).TotalSeconds
                < SupportedCandidateSeconds)
                return null;
            if (!QuoteEligible(market, pending.IsAdd) || AtOrBeyondTarget(market))
            {
                _pendingReclaim = null;
                _usedRootObjectIds.Add(failed.Id);
                return null;
            }

            var support = new EvidenceBandView
            {
                Id = candidate.Id,
                MinTick = candidate.MinTick,
                MaxTick = candidate.MaxTick,
                FormedUtc = candidate.FormedUtc,
                Side = candidate.Side,
            };
            ResolutionContext resolution = SupportedContext(failed, support, nowUtc);
            _pendingReclaim = null;
            return CreateEntryIntent(nowUtc, market, position, resolution,
                pending.IsAdd, "supported_reclaim_candidate");
        }

        internal static bool PendingIntentMatchesState(
            bool isAdd,
            RuntimeExecutionState state,
            RuntimePosition position)
        {
            position ??= RuntimePosition.Flat;
            return isAdd
                ? !position.IsFlat
                    && (state == RuntimeExecutionState.BaseOnly
                        || state == RuntimeExecutionState.Leveraged)
                : position.IsFlat && state == RuntimeExecutionState.Armed;
        }

        private OrderIntent TryCompleteDirectRetest(
            DateTime nowUtc,
            ExecutableMarket market,
            ExecutionEvidenceEngine evidence,
            RuntimePosition position)
        {
            PendingDirectRetest pending = _pendingRetest;
            if (pending == null || _pendingEntryIntent != null)
                return null;
            EvidenceBandView band = evidence.FindBand(pending.Resolution.RootObjectId);
            if (band == null || !band.IsLiveRail)
            {
                _pendingRetest = null;
                return null;
            }
            if (!QuoteEligible(market, pending.IsAdd) || AtOrBeyondTarget(market))
                return null;
            long quoteTick = PriceToTick(market.Executable(_directive.Direction));
            if (RangeDistance(quoteTick, band.MinTick, band.MaxTick)
                > DirectConversionMaxDistanceTicks)
                return null;
            _pendingRetest = null;
            return CreateEntryIntent(nowUtc, market, position, pending.Resolution,
                pending.IsAdd, "direct_conversion_retest");
        }

        private OrderIntent EvaluateBaseStop(EvidenceTransition transition, ExecutableMarket market)
        {
            if (_entryContext == null || _pendingEntryIntent != null)
                return null;
            if (transition.Kind == EvidenceTransitionKind.RailFailed
                && transition.Band?.Id == _entryContext.SupportObjectId)
            {
                _entryAnchorFailed = true;
                return null;
            }

            if (transition.Kind != EvidenceTransitionKind.RailOwned
                || transition.Band == null
                || transition.Band.Side == DesiredEvidenceSide())
                return null;

            EvidenceBandView opposing = transition.Band;
            // Candidate-backed supported reclaims enter after the four-second fast
            // path while the support candidate is still active. If that candidate
            // later confirms adversely, the evidence engine emits the opposite
            // Consumed rail with the same candidate id. Already-owned rails cannot
            // reuse an id this way.
            bool sameCandidateConsumed = IsCandidateSupportConsumed(_entryContext, opposing);
            bool nearbyReverse = _entryAnchorFailed
                && RangeDistance(opposing.MinTick, opposing.MaxTick,
                    _entryContext.SupportMinTick, _entryContext.SupportMaxTick)
                    <= ReverseResolutionProximityTicks;
            if (!sameCandidateConsumed && !nearbyReverse)
                return null;
            return CreateFlattenIntent(transition.TimeUtc, market,
                "reverse_entry_resolution", terminal: false, rearm: true);
        }

        private OrderIntent EvaluateSponsorFailure(
            EvidenceTransition transition,
            ExecutableMarket market,
            RuntimePosition position)
        {
            if (_currentSponsor == null || transition?.Band == null
                || transition.Band.Id != _currentSponsor.ObjectId)
            {
                return null;
            }

            bool confirmedFailure = transition.Kind == EvidenceTransitionKind.RailFailed;
            bool consumedAdversely = transition.Kind == EvidenceTransitionKind.RailOwned
                && transition.Band.Side != DesiredEvidenceSide()
                && transition.Band.Source == EvidenceSource.Consumed;
            if (!confirmedFailure && !consumedAdversely)
                return null;

            string reason = consumedAdversely
                ? $"sponsor_consumed:{_currentSponsor.ObjectId}"
                : $"sponsor_failed:{_currentSponsor.ObjectId}";
            if (position == null || position.IsFlat)
            {
                InvalidateWhileFlat();
                return CreateCancelOrdersIntent(transition.TimeUtc, market, reason);
            }

            bool terminal = _everLeveraged;
            return CreateFlattenIntent(transition.TimeUtc, market, reason,
                terminal: terminal, rearm: !terminal);
        }

        private void PromoteFilledResolution(
            ResolutionContext resolution,
            DateTime promotedUtc,
            string reason)
        {
            if (resolution == null || resolution.SupportObjectId <= 0)
                return;
            var sponsor = new SponsorContext
            {
                ObjectId = resolution.SupportObjectId,
                PriorObjectId = _currentSponsor?.ObjectId,
                Side = DesiredEvidenceSide(),
                Source = resolution.SupportSource,
                MinTick = resolution.SupportMinTick,
                MaxTick = resolution.SupportMaxTick,
                FormedUtc = resolution.SupportFormedUtc,
                PromotedUtc = NormalizeUtc(promotedUtc),
                Reason = reason,
                Epoch = _epoch,
            };
            PromoteSponsor(sponsor, requireFavorableAdvance: _currentSponsor != null);
        }

        private void TryPromoteSponsor(EvidenceTransition transition)
        {
            EvidenceBandView band = transition?.Band;
            if (_currentSponsor == null
                || transition.Kind != EvidenceTransitionKind.RailOwned
                || band == null
                || band.Role != EvidenceRole.Rail
                || !band.IsLiveRail
                || band.Side != DesiredEvidenceSide()
                || band.Id == _currentSponsor.ObjectId
                || transition.TimeUtc <= _currentSponsor.PromotedUtc
                || band.FormedUtc <= _currentSponsor.FormedUtc
                || !OwnershipDisplacedFavorably(transition, band))
            {
                return;
            }

            PromoteSponsor(new SponsorContext
            {
                ObjectId = band.Id,
                PriorObjectId = _currentSponsor.ObjectId,
                Side = band.Side,
                Source = band.Source,
                MinTick = band.MinTick,
                MaxTick = band.MaxTick,
                FormedUtc = band.FormedUtc,
                PromotedUtc = NormalizeUtc(transition.TimeUtc),
                Reason = "accepted_same_side_ownership",
                Epoch = _epoch,
            }, requireFavorableAdvance: true);
        }

        private void PromoteSponsor(SponsorContext sponsor, bool requireFavorableAdvance)
        {
            if (sponsor == null)
                return;
            if (requireFavorableAdvance && !IsFullyBeyondCurrentSponsor(sponsor))
                return;
            _lastSponsorClear = null;
            _currentSponsor = sponsor;
            _sponsorVersion++;
        }

        private bool IsFullyBeyondCurrentSponsor(SponsorContext candidate)
        {
            if (_currentSponsor == null)
                return true;
            return _directive.Direction == TradeDirection.Long
                ? candidate.MinTick > _currentSponsor.MaxTick
                : candidate.MaxTick < _currentSponsor.MinTick;
        }

        private bool OwnershipDisplacedFavorably(
            EvidenceTransition transition,
            EvidenceBandView band)
            => _directive.Direction == TradeDirection.Long
                ? transition.CurrentMidTick > band.MaxTick
                : transition.CurrentMidTick < band.MinTick;

        private void InvalidateWhileFlat()
        {
            State = RuntimeExecutionState.Invalidated;
            _pendingEntryIntent = null;
            _pendingReclaim = null;
            _pendingRetest = null;
        }

        internal static bool IsCandidateSupportConsumed(
            ResolutionContext entryContext,
            EvidenceBandView opposing)
            => entryContext != null
                && opposing != null
                && opposing.Id == entryContext.SupportObjectId
                && opposing.Source == EvidenceSource.Consumed;

        private bool CandidateSupportBecameAmbiguous(ExecutionEvidenceEngine evidence)
        {
            if (_entryContext?.Resolution != ResolutionType.SupportedReclaim)
                return false;
            EvidenceCandidateView candidate = evidence.FindCandidate(_entryContext.SupportObjectId);
            EvidenceBandView band = evidence.FindBand(_entryContext.SupportObjectId);
            return candidate == null && band == null;
        }

        private OrderIntent CreateEntryIntent(
            DateTime nowUtc,
            ExecutableMarket market,
            RuntimePosition position,
            ResolutionContext resolution,
            bool isAdd,
            string reason)
        {
            if (_pendingEntryIntent != null || _usedRootObjectIds.Contains(resolution.RootObjectId))
                return null;
            if (!isAdd && _baseAttempts > _directive.MaxBaseReentries)
            {
                State = RuntimeExecutionState.Completed;
                return null;
            }
            int quantity = isAdd ? _directive.AddQuantity : _directive.BaseQuantity;
            if (isAdd)
                quantity = Math.Min(quantity,
                    Math.Max(0, _directive.MaxPositionQuantity - (int)Math.Round(position.Quantity)));
            if (quantity <= 0)
                return null;

            _usedRootObjectIds.Add(resolution.RootObjectId);
            _epoch++;
            if (!isAdd)
            {
                _baseAttempts++;
                _freshRootAfterUtc = NormalizeUtc(nowUtc);
            }

            var intent = new OrderIntent
            {
                IntentId = Guid.NewGuid().ToString("N"),
                Kind = isAdd ? OrderIntentKind.Add : OrderIntentKind.EnterBase,
                Direction = _directive.Direction,
                Quantity = quantity,
                Reason = reason,
                DirectiveId = _directive.Id,
                Epoch = _epoch,
                TriggerUtc = NormalizeUtc(nowUtc),
                TriggerBid = market?.Bid ?? double.NaN,
                TriggerAsk = market?.Ask ?? double.NaN,
                Resolution = resolution,
            };
            _pendingEntryIntent = intent;
            return intent;
        }

        private OrderIntent CreateFlattenIntent(DateTime nowUtc, ExecutableMarket market,
            string reason, bool terminal, bool rearm)
        {
            _flattenDisposition = new FlattenDisposition
            {
                TerminalAfterFlat = terminal,
                RearmAfterFlat = rearm,
                Reason = reason,
            };
            return new OrderIntent
            {
                IntentId = Guid.NewGuid().ToString("N"),
                Kind = OrderIntentKind.Flatten,
                Direction = _directive?.Direction ?? TradeDirection.Long,
                Reason = reason,
                DirectiveId = _directive?.Id,
                Epoch = _epoch,
                TriggerUtc = NormalizeUtc(nowUtc),
                TriggerBid = market?.Bid ?? double.NaN,
                TriggerAsk = market?.Ask ?? double.NaN,
                TerminalAfterFlat = terminal,
                RearmAfterFlat = rearm,
            };
        }

        private OrderIntent CreateCancelOrdersIntent(DateTime nowUtc,
            ExecutableMarket market, string reason)
            => new()
            {
                IntentId = Guid.NewGuid().ToString("N"),
                Kind = OrderIntentKind.CancelRuntimeOrders,
                Direction = _directive?.Direction ?? TradeDirection.Long,
                Reason = reason,
                DirectiveId = _directive?.Id,
                Epoch = _epoch,
                TriggerUtc = NormalizeUtc(nowUtc),
                TriggerBid = market?.Bid ?? double.NaN,
                TriggerAsk = market?.Ask ?? double.NaN,
            };

        private OrderIntent CreateProtectionIntent(OrderIntentKind kind, DateTime nowUtc,
            ExecutableMarket market, RuntimePosition position, string reason)
            => new()
            {
                IntentId = Guid.NewGuid().ToString("N"),
                Kind = kind,
                Direction = _directive.Direction,
                Quantity = position.Quantity,
                Price = kind == OrderIntentKind.EnsureHardTarget
                    ? _directive.TargetPrice
                    : position.AveragePrice,
                Reason = reason,
                DirectiveId = _directive.Id,
                Epoch = _epoch,
                TriggerUtc = NormalizeUtc(nowUtc),
                TriggerBid = market?.Bid ?? double.NaN,
                TriggerAsk = market?.Ask ?? double.NaN,
            };

        private ResolutionContext SupportedContext(EvidenceBandView failed,
            EvidenceBandView support, DateTime triggerUtc)
            => new()
            {
                Resolution = ResolutionType.SupportedReclaim,
                RootObjectId = failed.Id,
                SupportObjectId = support.Id,
                RootMinTick = failed.MinTick,
                RootMaxTick = failed.MaxTick,
                SupportMinTick = support.MinTick,
                SupportMaxTick = support.MaxTick,
                SupportSource = support.Source,
                RootFormedUtc = failed.FormedUtc,
                SupportFormedUtc = support.FormedUtc,
                TriggerUtc = triggerUtc,
            };

        private bool RootEligible(int id, DateTime formedUtc, bool isAdd)
        {
            if (_usedRootObjectIds.Contains(id))
                return false;
            if (isAdd)
                return formedUtc > _lastFillUtc;
            if (_baseAttempts == 0)
                return true;
            return formedUtc > _freshRootAfterUtc;
        }

        private bool ContextEligible(EvidenceBandView band)
            => band != null && _directive.ContextPriceRange.Intersects(
                TickToPrice(band.MinTick), TickToPrice(band.MaxTick));

        private bool QuoteEligible(ExecutableMarket market, bool isAdd)
        {
            if (market == null || !market.IsValid)
                return false;
            PriceRange range = isAdd ? _directive.AddPriceRange : _directive.OrderPriceRange;
            return range != null && range.Contains(market.Executable(_directive.Direction));
        }

        private bool AtOrBeyondTarget(ExecutableMarket market)
        {
            if (market == null || !market.IsValid)
                return true;
            double quote = market.Executable(_directive.Direction);
            return _directive.Direction == TradeDirection.Long
                ? quote >= _directive.TargetPrice
                : quote <= _directive.TargetPrice;
        }

        private bool PreEntryInvalidated(ExecutableMarket market)
        {
            PriceTrigger trigger = _directive.PreEntryInvalidation;
            if (trigger == null || market == null || !market.IsValid)
                return false;
            double reference = trigger.IsBelow ? market.Bid : market.Ask;
            return trigger.IsBelow ? reference < trigger.Price : reference > trigger.Price;
        }

        private bool CorrectTopology(long supportMin, long supportMax,
            long failedMin, long failedMax)
        {
            double supportCenter = (supportMin + supportMax) / 2.0;
            double failedCenter = (failedMin + failedMax) / 2.0;
            return DesiredEvidenceSide() == EvidenceSide.Demand
                ? supportCenter <= failedCenter
                : supportCenter >= failedCenter;
        }

        private bool OppositeFailureFlattens(EvidenceBandView band)
            => _directive.Direction == TradeDirection.Long
                ? band.Side == EvidenceSide.Supply
                : band.Side == EvidenceSide.Demand;

        private EvidenceSide DesiredEvidenceSide()
            => _directive.Direction == TradeDirection.Long
                ? EvidenceSide.Demand
                : EvidenceSide.Supply;

        private long PriceToTick(double price)
            => (long)Math.Round(price / _tickSize);

        private double TickToPrice(long tick)
            => tick * _tickSize;

        private static int RangeDistance(long tick, long minTick, long maxTick)
            => tick < minTick ? (int)(minTick - tick)
                : tick > maxTick ? (int)(tick - maxTick)
                : 0;

        private static int RangeDistance(long leftMin, long leftMax,
            long rightMin, long rightMax)
            => leftMax < rightMin ? (int)(rightMin - leftMax)
                : rightMax < leftMin ? (int)(leftMin - rightMax)
                : 0;

        private static DateTime NormalizeUtc(DateTime value)
            => value.Kind switch
            {
                DateTimeKind.Utc => value,
                DateTimeKind.Local => value.ToUniversalTime(),
                _ => DateTime.SpecifyKind(value, DateTimeKind.Utc),
            };

        private static bool IsTerminal(RuntimeExecutionState state)
            => state == RuntimeExecutionState.Completed
                || state == RuntimeExecutionState.Cancelled
                || state == RuntimeExecutionState.Invalidated
                || state == RuntimeExecutionState.Expired
                || state == RuntimeExecutionState.Error;

        private sealed class PendingReclaim
        {
            public EvidenceBandView FailedBand;
            public int CandidateId;
            public DateTime CandidateDirectionStartedUtc;
            public DateTime FailedUtc;
            public bool IsAdd;
        }

        private sealed class PendingDirectRetest
        {
            public ResolutionContext Resolution;
            public bool IsAdd;
        }

        private sealed class FlattenDisposition
        {
            public bool TerminalAfterFlat;
            public bool RearmAfterFlat;
            public bool HaltAfterFlat;
            public bool Cancelled;
            public string Reason;
        }
    }
}
