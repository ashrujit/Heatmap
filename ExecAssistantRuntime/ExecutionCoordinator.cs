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
        Paused,
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

    internal enum ContinuationKind
    {
        ProtectiveClear,
        ExpiredRearm,
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
        public bool FailureAssisted { get; init; }
        public int FailureParentObjectId { get; init; }
        public long FailureParentMinTick { get; init; }
        public long FailureParentMaxTick { get; init; }
        public DateTime FailureParentHeldUtc { get; init; }
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

    internal sealed class ReferenceBreakContext
    {
        public int ReferenceObjectId { get; init; }
        public EvidenceSide ReferenceSide { get; init; }
        public long ReferenceMinTick { get; init; }
        public long ReferenceMaxTick { get; init; }
        public DateTime ReferenceFormedUtc { get; init; }
        public DateTime FailedUtc { get; init; }
        public DateTime ExpiresUtc { get; init; }
        public int? BreakSponsorObjectId { get; set; }
    }

    internal sealed class ContinuationContext
    {
        public ContinuationKind Kind { get; init; }
        public string ParentDirectiveId { get; init; }
        public SponsorClearContext ParentSponsorClear { get; init; }
        public long ParentContextMinTick { get; init; }
        public long ParentContextMaxTick { get; init; }
        public DateTime EvidenceAfterUtc { get; init; }
    }

    internal sealed class CoordinatorAuditEvent
    {
        public string EventType { get; init; }
        public DateTime TimeUtc { get; init; }
        public string DirectiveId { get; init; }
        public string Reason { get; init; }
        public int? ParentObjectId { get; init; }
        public EvidenceSide? ParentSide { get; init; }
        public long? ParentMinTick { get; init; }
        public long? ParentMaxTick { get; init; }
        public int? ChildObjectId { get; init; }
        public EvidenceSource? ChildSource { get; init; }
        public long? ChildMinTick { get; init; }
        public long? ChildMaxTick { get; init; }
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
        private const int FailureAssistedParentTtlSeconds = 300;
        private const int FailureAssistedChildTouchTicks = 4;
        private const int ReferenceBreakMinAgeSeconds = 1200;
        private const int ReferenceBreakContextTtlSeconds = 600;
        private const int ReferenceBreakChildSeparationTicks = 8;
        private const int ReferenceBreakReclaimDistanceTicks = 32;
        private const int ReferenceBreakSponsorDistanceTicks = 80;

        private readonly double _tickSize;
        private readonly bool _failureAssistedEntriesEnabled;
        private readonly HashSet<int> _usedRootObjectIds = new();
        private readonly HashSet<int> _baselineFailureIds = new();
        private readonly HashSet<int> _activeAdverseFailureIds = new();
        private readonly List<CoordinatorAuditEvent> _auditEvents = new();
        private TradeDirective _directive;
        private DateTime _activatedUtc;
        private DateTime _freshRootAfterUtc;
        private DateTime _lastFillUtc;
        private int _epoch;
        private int _baseAttempts;
        private bool _everLeveraged;
        private bool _entryAnchorFailed;
        private bool _awaitingSponsorAlignedFailure;
        private ResolutionContext _entryContext;
        private PendingReclaim _pendingReclaim;
        private PendingDirectRetest _pendingRetest;
        private FailureAssistedParent _failureAssistedParent;
        private OrderIntent _pendingEntryIntent;
        private FlattenDisposition _flattenDisposition;
        private double _lastKnownQuantity;
        private double _lastKnownAveragePrice;
        private SponsorContext _currentSponsor;
        private SponsorClearContext _lastSponsorClear;
        private ReferenceBreakContext _referenceBreakContext;
        private ContinuationContext _continuation;
        private bool _continuationLineageBroken;
        private int _sponsorVersion;

        public ExecutionCoordinator(double tickSize)
            : this(tickSize, failureAssistedEntriesEnabled: true)
        {
        }

        public ExecutionCoordinator(double tickSize, bool failureAssistedEntriesEnabled)
        {
            _tickSize = double.IsFinite(tickSize) && tickSize > 0 ? tickSize : 0.25;
            _failureAssistedEntriesEnabled = failureAssistedEntriesEnabled;
        }

        public RuntimeExecutionState State { get; private set; } = RuntimeExecutionState.Idle;
        public TradeDirective Directive => _directive;
        public int BaseAttempts => _baseAttempts;
        public bool EverLeveraged => _everLeveraged;
        public bool HasPendingEntryOrder => _pendingEntryIntent != null;
        public SponsorContext CurrentSponsor => _currentSponsor;
        public SponsorClearContext LastSponsorClear => _lastSponsorClear;
        public int SponsorVersion => _sponsorVersion;
        public bool EntryPaused => State == RuntimeExecutionState.Paused;
        public IReadOnlyCollection<int> ActiveAdverseFailureIds
            => _activeAdverseFailureIds;

        public IReadOnlyList<CoordinatorAuditEvent> DrainAuditEvents()
        {
            if (_auditEvents.Count == 0)
                return Array.Empty<CoordinatorAuditEvent>();
            CoordinatorAuditEvent[] result = _auditEvents.ToArray();
            _auditEvents.Clear();
            return result;
        }

        public void AcceptDirective(
            TradeDirective directive,
            DateTime nowUtc,
            IEnumerable<int> existingHeldFailureIds,
            ContinuationContext continuation = null)
        {
            if (directive == null)
                throw new ArgumentNullException(nameof(directive));
            bool replacesParentForContinuation = continuation != null
                && _directive != null
                && string.Equals(_directive.Id, continuation.ParentDirectiveId,
                    StringComparison.Ordinal);
            if (_directive != null && !IsTerminal(State)
                && State != RuntimeExecutionState.Halted
                && !replacesParentForContinuation)
                throw new InvalidOperationException("A directive is already active.");

            _directive = directive;
            _activatedUtc = NormalizeUtc(nowUtc);
            _freshRootAfterUtc = _activatedUtc;
            _lastFillUtc = DateTime.MinValue;
            _epoch = 0;
            _baseAttempts = 0;
            _everLeveraged = false;
            _entryAnchorFailed = false;
            _awaitingSponsorAlignedFailure = false;
            _entryContext = null;
            _pendingReclaim = null;
            _pendingRetest = null;
            _failureAssistedParent = null;
            _pendingEntryIntent = null;
            _flattenDisposition = null;
            _lastKnownQuantity = 0;
            _lastKnownAveragePrice = 0;
            _currentSponsor = null;
            _lastSponsorClear = null;
            _referenceBreakContext = null;
            _continuation = continuation;
            _continuationLineageBroken = false;
            _sponsorVersion = 0;
            _usedRootObjectIds.Clear();
            _baselineFailureIds.Clear();
            _activeAdverseFailureIds.Clear();
            if (existingHeldFailureIds != null)
            {
                foreach (int id in existingHeldFailureIds)
                    _baselineFailureIds.Add(id);
            }
            State = directive.NotBefore.UtcDateTime > _activatedUtc
                ? RuntimeExecutionState.Waiting
                : RuntimeExecutionState.Armed;
        }

        public bool TryPrepareContinuation(
            TradeDirective directive,
            out ContinuationContext continuation,
            out string reason)
        {
            continuation = null;
            reason = null;
            if (directive?.Lineage?.IsContinuation != true)
                return true;
            if (_directive == null)
            {
                reason = "continuation_parent_not_found";
                return false;
            }
            if (!string.Equals(_directive.Id, directive.Lineage.ParentDirectiveId,
                StringComparison.Ordinal))
            {
                reason = "continuation_parent_not_immediate";
                return false;
            }
            if (directive.Direction != _directive.Direction)
            {
                reason = "continuation_side_mismatch";
                return false;
            }
            if (State == RuntimeExecutionState.Cancelled
                || State == RuntimeExecutionState.Error
                || State == RuntimeExecutionState.Halted
                || State == RuntimeExecutionState.Halting
                || State == RuntimeExecutionState.RecoveryProtected)
            {
                reason = "continuation_parent_state_not_eligible";
                return false;
            }
            if (_continuationLineageBroken)
            {
                reason = "continuation_lineage_broken";
                return false;
            }
            if (!ContinuationRangesMatch(directive))
            {
                reason = "continuation_ranges_changed";
                return false;
            }

            if (_lastSponsorClear?.Sponsor != null
                && IsContinuationProtectiveExit(_lastSponsorClear.FlattenReason))
            {
                continuation = CreateContinuation(
                    ContinuationKind.ProtectiveClear,
                    _lastSponsorClear,
                    _lastSponsorClear.ClearedUtc);
                return true;
            }

            if (State == RuntimeExecutionState.Expired)
            {
                if (_baseAttempts != 0
                    || _everLeveraged
                    || _currentSponsor != null
                    || _pendingEntryIntent != null)
                {
                    reason = "continuation_parent_not_unfilled_expiry";
                    return false;
                }

                continuation = CreateContinuation(
                    ContinuationKind.ExpiredRearm,
                    parentSponsorClear: null,
                    MaxUtc(_activatedUtc, _directive.NotBefore.UtcDateTime));
                return true;
            }

            reason = "continuation_parent_has_no_protective_clear";
            return false;
        }

        private ContinuationContext CreateContinuation(
            ContinuationKind kind,
            SponsorClearContext parentSponsorClear,
            DateTime evidenceAfterUtc)
            => new()
            {
                Kind = kind,
                ParentDirectiveId = _directive.Id,
                ParentSponsorClear = parentSponsorClear,
                ParentContextMinTick = PriceToTick(_directive.ContextPriceRange.Lower),
                ParentContextMaxTick = PriceToTick(_directive.ContextPriceRange.Upper),
                EvidenceAfterUtc = NormalizeUtc(evidenceAfterUtc),
            };

        public IReadOnlyList<OrderIntent> SeedContinuation(
            DateTime nowUtc,
            ExecutableMarket market,
            RuntimePosition position,
            ExecutionEvidenceEngine evidence)
        {
            var intents = new List<OrderIntent>();
            if (_continuation == null || evidence == null || _pendingEntryIntent != null)
                return intents;
            position ??= RuntimePosition.Flat;
            if (!position.IsFlat
                || (State != RuntimeExecutionState.Armed
                    && State != RuntimeExecutionState.Paused))
            {
                return intents;
            }
            if (HasContinuationBoundaryCounterEvidence(evidence, out EvidenceBandView counter))
            {
                State = RuntimeExecutionState.Invalidated;
                intents.Add(CreateCancelOrdersIntent(nowUtc, market,
                    $"continuation_boundary_counter_evidence:{counter.Id}"));
                return intents;
            }
            if (State == RuntimeExecutionState.Paused
                || !QuoteEligible(market, isAdd: false)
                || AtOrBeyondTarget(market))
            {
                return intents;
            }

            OrderIntent reclaim = SeedContinuationSupportedReclaim(nowUtc,
                market, position, evidence);
            if (reclaim != null)
            {
                intents.Add(reclaim);
                return intents;
            }

            OrderIntent direct = SeedContinuationDirectRetest(nowUtc,
                market, position, evidence);
            if (direct != null)
                intents.Add(direct);
            return intents;
        }

        public void BaselineHeldFailures(IEnumerable<int> heldFailureIds, DateTime nowUtc)
        {
            if (heldFailureIds == null)
                return;
            foreach (int id in heldFailureIds)
            {
                _baselineFailureIds.Add(id);
                _activeAdverseFailureIds.Remove(id);
            }
            if (State == RuntimeExecutionState.Paused
                && _activeAdverseFailureIds.Count == 0)
            {
                State = NormalizeUtc(nowUtc) < _directive.NotBefore.UtcDateTime
                    ? RuntimeExecutionState.Waiting
                    : RuntimeExecutionState.Armed;
            }
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
                State = HasActiveAdverseFailures
                    ? RuntimeExecutionState.Paused
                    : RuntimeExecutionState.Armed;
            }

            if (position.IsFlat && nowUtc > _directive.ExpiresAt.UtcDateTime
                && (State == RuntimeExecutionState.Armed
                    || State == RuntimeExecutionState.Paused
                    || State == RuntimeExecutionState.Waiting))
            {
                State = RuntimeExecutionState.Expired;
                return intents;
            }

            if (position.IsFlat
                && (State == RuntimeExecutionState.Armed
                    || State == RuntimeExecutionState.Paused)
                && PreEntryInvalidated(market))
            {
                State = RuntimeExecutionState.Invalidated;
                return intents;
            }

            if (!evidenceAvailable)
                return intents;

            ExpireFailureAssistedParent(nowUtc);
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
                    || State == RuntimeExecutionState.Paused
                    || State == RuntimeExecutionState.Waiting))
            {
                State = RuntimeExecutionState.Expired;
                return intents;
            }
            if (position.IsFlat
                && (State == RuntimeExecutionState.Armed
                    || State == RuntimeExecutionState.Paused)
                && PreEntryInvalidated(market))
            {
                State = RuntimeExecutionState.Invalidated;
                return intents;
            }
            OrderIntent continuationInvalidation = EvaluateContinuationBoundary(
                transitions, nowUtc, market, position);
            if (continuationInvalidation != null)
            {
                intents.Add(continuationInvalidation);
                return intents;
            }
            bool hadActiveAdverseFailures = HasActiveAdverseFailures;
            ObserveAdverseFailures(transitions);
            ObserveFailureAssistedContext(transitions, nowUtc);
            ObserveReferenceBreakContext(transitions, nowUtc, position);
            if (position.IsFlat)
            {
                EvidenceTransition freshAdverseFailure = transitions.FirstOrDefault(
                    IsFreshAdverseFailureHeld);
                if (_awaitingSponsorAlignedFailure && freshAdverseFailure != null)
                {
                    string reason = freshAdverseFailure.Band.Side == EvidenceSide.Demand
                        ? "LF_sponsor_failed_while_flat"
                        : "HF_sponsor_failed_while_flat";
                    _awaitingSponsorAlignedFailure = false;
                    InvalidateWhileFlat();
                    intents.Add(CreateCancelOrdersIntent(
                        freshAdverseFailure.TimeUtc, market, reason));
                    return intents;
                }
                if (HasActiveAdverseFailures)
                {
                    if (State == RuntimeExecutionState.Armed)
                        PauseWhileFlat();
                    if (!hadActiveAdverseFailures && State == RuntimeExecutionState.Paused)
                    {
                        EvidenceTransition pause = transitions.First(transition =>
                            IsFreshAdverseFailureHeld(transition));
                        string reason = pause.Band.Side == EvidenceSide.Demand ? "LF" : "HF";
                        intents.Add(CreateCancelOrdersIntent(
                            pause.TimeUtc, market, $"{reason}_pause_while_flat"));
                        return intents;
                    }
                }
                else if (State == RuntimeExecutionState.Paused)
                {
                    State = nowUtc < _directive.NotBefore.UtcDateTime
                        ? RuntimeExecutionState.Waiting
                        : RuntimeExecutionState.Armed;
                }
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
                    // The directive window gates base admission/retries only.
                    // Once a base fill starts the campaign, fresh add evidence may continue.
                    && position.Quantity + _directive.AddQuantity <= _directive.MaxPositionQuantity;
                if (!mayEnter && !mayAdd)
                    continue;

                OrderIntent intent = null;
                if (transition.Kind == EvidenceTransitionKind.RailOwned
                    && transition.Band?.Side == DesiredEvidenceSide()
                    && _directive.AllowedResolutions.Contains(ResolutionType.DirectConversion))
                {
                    intent = EvaluateFailureAssistedChild(
                        transition, market, position, mayAdd);
                }

                if (intent == null
                    && transition.Kind == EvidenceTransitionKind.RailOwned
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
                _pendingReclaim = null;
                _pendingRetest = null;
                _failureAssistedParent = null;
                _lastFillUtc = nowUtc;
                _freshRootAfterUtc = nowUtc;
                _entryAnchorFailed = false;
                if (filledIntent.Kind == OrderIntentKind.EnterBase)
                {
                    _awaitingSponsorAlignedFailure = false;
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
                if (State == RuntimeExecutionState.RecoveryProtected)
                {
                    intents.Add(CreateProtectionIntent(OrderIntentKind.EnsureBreakeven,
                        nowUtc, market, position, "position_quantity_or_average_changed"));
                }
                return intents;
            }

            if (position.IsFlat && previousQuantity > 0)
            {
                FlattenDisposition disposition = _flattenDisposition;
                bool sponsorAlignedTerminal = disposition?.RearmAfterFlat == true
                    && _awaitingSponsorAlignedFailure
                    && HasActiveAdverseFailures;
                _flattenDisposition = null;
                _pendingEntryIntent = null;
                _entryContext = null;
                _entryAnchorFailed = false;
                _pendingReclaim = null;
                _pendingRetest = null;
                _failureAssistedParent = null;
                _referenceBreakContext = null;
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
                else if (disposition?.TerminalAfterFlat == true || sponsorAlignedTerminal)
                {
                    _awaitingSponsorAlignedFailure = false;
                    State = disposition.Cancelled
                        ? RuntimeExecutionState.Cancelled
                        : RuntimeExecutionState.Completed;
                }
                else if (disposition?.RearmAfterFlat == true
                    && !_everLeveraged
                    && _baseAttempts <= _directive.MaxBaseReentries
                    && nowUtc <= _directive.ExpiresAt.UtcDateTime)
                {
                    State = HasActiveAdverseFailures
                        ? RuntimeExecutionState.Paused
                        : RuntimeExecutionState.Armed;
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

        public OrderIntent FlattenPausedFill(DateTime nowUtc, ExecutableMarket market)
            => CreateFlattenIntent(nowUtc, market, "entry_filled_while_paused",
                terminal: false, rearm: true);

        public OrderIntent SafetyFlatten(DateTime nowUtc, ExecutableMarket market, string reason)
        {
            State = RuntimeExecutionState.Halting;
            _pendingEntryIntent = null;
            _pendingReclaim = null;
            _pendingRetest = null;
            _failureAssistedParent = null;
            _referenceBreakContext = null;
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
            _pendingEntryIntent = null;
            _pendingReclaim = null;
            _pendingRetest = null;
            _failureAssistedParent = null;
            _referenceBreakContext = null;
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
            _pendingReclaim = null;
            _pendingRetest = null;
            _failureAssistedParent = null;
            _referenceBreakContext = null;
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
            _failureAssistedParent = null;
            _currentSponsor = null;
            _referenceBreakContext = null;
            BreakContinuationLineage();
        }

        public void MarkError()
        {
            State = RuntimeExecutionState.Error;
            _pendingEntryIntent = null;
            _pendingReclaim = null;
            _pendingRetest = null;
            _failureAssistedParent = null;
            _referenceBreakContext = null;
            BreakContinuationLineage();
        }

        public void BreakContinuationLineage()
        {
            _lastSponsorClear = null;
            _continuation = null;
            _continuationLineageBroken = true;
        }

        public bool HasContinuationBoundaryCounterEvidence(
            ExecutionEvidenceEngine evidence,
            out EvidenceBandView counter)
        {
            counter = null;
            if (_continuation == null || evidence == null)
                return false;
            EvidenceSide adverse = _directive.Direction == TradeDirection.Long
                ? EvidenceSide.Supply
                : EvidenceSide.Demand;
            return HasContinuationBoundaryCounterEvidence(
                _directive.Direction,
                _continuation,
                evidence.LiveRails(adverse),
                out counter);
        }

        public static bool HasContinuationBoundaryCounterEvidence(
            TradeDirection direction,
            ContinuationContext continuation,
            IEnumerable<EvidenceBandView> liveAdverseRails,
            out EvidenceBandView counter)
        {
            counter = null;
            if (continuation == null || liveAdverseRails == null)
                return false;
            foreach (EvidenceBandView rail in liveAdverseRails)
            {
                if (rail == null || !rail.IsLiveRail)
                    continue;
                bool beyond = direction == TradeDirection.Long
                    ? rail.MaxTick < continuation.ParentContextMinTick
                    : rail.MinTick > continuation.ParentContextMaxTick;
                if (!beyond)
                    continue;
                counter = rail;
                return true;
            }
            return false;
        }

        private OrderIntent SeedContinuationSupportedReclaim(
            DateTime nowUtc,
            ExecutableMarket market,
            RuntimePosition position,
            ExecutionEvidenceEngine evidence)
        {
            EvidenceSide desired = DesiredEvidenceSide();
            EvidenceSide adverse = desired == EvidenceSide.Demand
                ? EvidenceSide.Supply
                : EvidenceSide.Demand;
            foreach (EvidenceBandView failed in evidence.FailedRails(adverse)
                .Where(ContextEligible)
                .Where(f => (f.FailedUtc ?? f.LastStateUtc) >= _continuation.EvidenceAfterUtc)
                .OrderByDescending(f => f.FailedUtc ?? f.LastStateUtc))
            {
                EvidenceBandView support = evidence.LiveRails(desired)
                    .Where(ContextEligible)
                    .Where(s => CorrectTopology(s.MinTick, s.MaxTick,
                        failed.MinTick, failed.MaxTick))
                    .Where(s => RangeDistance(s.MinTick, s.MaxTick,
                        failed.MinTick, failed.MaxTick)
                        <= SupportedCandidateMaxDistanceTicks)
                    .OrderBy(s => RangeDistance(s.MinTick, s.MaxTick,
                        failed.MinTick, failed.MaxTick))
                    .FirstOrDefault();
                if (support == null)
                    continue;

                ResolutionContext resolution = SupportedContext(failed, support, nowUtc);
                return CreateEntryIntent(nowUtc, market, position, resolution,
                    isAdd: false, "continuation_supported_reclaim_snapshot");
            }
            return null;
        }

        private OrderIntent SeedContinuationDirectRetest(
            DateTime nowUtc,
            ExecutableMarket market,
            RuntimePosition position,
            ExecutionEvidenceEngine evidence)
        {
            EvidenceSide desired = DesiredEvidenceSide();
            long quoteTick = PriceToTick(market.Executable(_directive.Direction));
            EvidenceBandView band = evidence.LiveRails(desired)
                .Where(ContextEligible)
                .Where(b => b.Source == EvidenceSource.Consumed)
                .Where(b => b.OwnedUtc >= _continuation.EvidenceAfterUtc
                    || b.FormedUtc >= _continuation.EvidenceAfterUtc)
                .OrderBy(b => RangeDistance(quoteTick, b.MinTick, b.MaxTick))
                .FirstOrDefault();
            if (band == null || _usedRootObjectIds.Contains(band.Id))
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
                TriggerUtc = nowUtc,
            };
            if (RangeDistance(quoteTick, band.MinTick, band.MaxTick)
                <= DirectConversionMaxDistanceTicks)
            {
                return CreateEntryIntent(nowUtc, market, position, resolution,
                    isAdd: false, "continuation_direct_conversion_snapshot");
            }
            _pendingRetest = new PendingDirectRetest
            {
                Resolution = resolution,
                IsAdd = false,
            };
            return null;
        }

        private OrderIntent EvaluateContinuationBoundary(
            IReadOnlyList<EvidenceTransition> transitions,
            DateTime nowUtc,
            ExecutableMarket market,
            RuntimePosition position)
        {
            if (_continuation == null || transitions == null)
                return null;
            EvidenceTransition counter = transitions.FirstOrDefault(
                IsContinuationBoundaryCounterEvidence);
            if (counter == null)
                return null;
            string reason = $"continuation_boundary_counter_evidence:{counter.Band.Id}";
            if (position != null && !position.IsFlat)
                return CreateFlattenIntent(counter.TimeUtc, market, reason,
                    terminal: true, rearm: false);
            State = RuntimeExecutionState.Invalidated;
            return CreateCancelOrdersIntent(
                counter.TimeUtc == default ? nowUtc : counter.TimeUtc,
                market,
                reason);
        }

        private bool IsContinuationBoundaryCounterEvidence(EvidenceTransition transition)
        {
            EvidenceBandView band = transition?.Band;
            if (_continuation == null
                || transition.Kind != EvidenceTransitionKind.RailOwned
                || band == null
                || !band.IsLiveRail
                || !IsAdverseFailure(band))
            {
                return false;
            }
            return _directive.Direction == TradeDirection.Long
                ? band.MaxTick < _continuation.ParentContextMinTick
                : band.MinTick > _continuation.ParentContextMaxTick;
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

        private OrderIntent EvaluateFailureAssistedChild(
            EvidenceTransition transition,
            ExecutableMarket market,
            RuntimePosition position,
            bool isAdd)
        {
            FailureAssistedParent parent = _failureAssistedParent;
            EvidenceBandView band = transition.Band;
            if (!_failureAssistedEntriesEnabled
                || parent == null
                || band == null
                || !FailureAssistedChildEligible(parent, transition, band, isAdd))
            {
                return null;
            }

            if (!QuoteEligible(market, isAdd) || AtOrBeyondTarget(market))
                return null;

            if (!parent.ChildObjectId.HasValue)
            {
                parent.ChildObjectId = band.Id;
                parent.ChildSource = band.Source;
                parent.ChildMinTick = band.MinTick;
                parent.ChildMaxTick = band.MaxTick;
                parent.ChildFormedUtc = band.FormedUtc;
                AddFailureParentAudit("failure_parent_child_selected",
                    transition.TimeUtc, parent, band, "next_same_side_ownership");
            }

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
                FailureAssisted = true,
                FailureParentObjectId = parent.ParentObjectId,
                FailureParentMinTick = parent.MinTick,
                FailureParentMaxTick = parent.MaxTick,
                FailureParentHeldUtc = parent.HeldUtc,
            };

            long quoteTick = PriceToTick(market.Executable(_directive.Direction));
            if (RangeDistance(quoteTick, band.MinTick, band.MaxTick)
                <= DirectConversionMaxDistanceTicks)
            {
                return CreateEntryIntent(transition.TimeUtc, market, position,
                    resolution, isAdd, "failure_parent_child_direct");
            }

            _pendingRetest = new PendingDirectRetest
            {
                Resolution = resolution,
                IsAdd = isAdd,
                Reason = "failure_parent_child_retest",
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
            bool stateStillMatches = PendingIntentMatchesState(
                pending.IsAdd, State, position);
            if (!stateStillMatches)
            {
                _pendingRetest = null;
                return null;
            }
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
            string reason = string.IsNullOrWhiteSpace(pending.Reason)
                ? pending.Resolution?.FailureAssisted == true
                    ? "failure_parent_child_retest"
                    : "direct_conversion_retest"
                : pending.Reason;
            return CreateEntryIntent(nowUtc, market, position, pending.Resolution,
                pending.IsAdd, reason);
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
                _awaitingSponsorAlignedFailure = false;
                InvalidateWhileFlat();
                return CreateCancelOrdersIntent(transition.TimeUtc, market, reason);
            }

            bool terminal = _everLeveraged || HasActiveAdverseFailures;
            bool failureAssistedEntrySupport = confirmedFailure
                && _entryContext?.FailureAssisted == true
                && transition.Band.Id == _entryContext.SupportObjectId;
            if (failureAssistedEntrySupport)
            {
                AddFailureParentAudit("failure_parent_child_failed",
                    transition.TimeUtc,
                    _entryContext,
                    terminal ? reason : $"failure_parent_child_failed:{_currentSponsor.ObjectId}");
                if (!terminal)
                    reason = $"failure_parent_child_failed:{_currentSponsor.ObjectId}";
            }
            _awaitingSponsorAlignedFailure = !terminal;
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
            ExpireReferenceBreakContext(promotedUtc);
            TryBindReferenceBreakSponsor(sponsor, resolution,
                "filled_reference_break_sponsor");
            if (ReferenceBreakSuppressesCampaignPromotion(sponsor))
            {
                AddReferenceBreakAudit("reference_break_tactical_child",
                    promotedUtc,
                    _referenceBreakContext,
                    sponsor,
                    "filled_child_not_campaign_sponsor");
                return;
            }
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

            var sponsor = new SponsorContext
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
            };
            ExpireReferenceBreakContext(transition.TimeUtc);
            TryBindReferenceBreakSponsor(sponsor, resolution: null,
                "owned_reference_break_sponsor");
            if (ReferenceBreakSuppressesCampaignPromotion(sponsor))
            {
                AddReferenceBreakAudit("reference_break_tactical_child",
                    transition.TimeUtc,
                    _referenceBreakContext,
                    sponsor,
                    "owned_child_not_campaign_sponsor");
                return;
            }
            PromoteSponsor(sponsor, requireFavorableAdvance: true);
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

        private bool TryBindReferenceBreakSponsor(
            SponsorContext candidate,
            ResolutionContext resolution,
            string reason)
        {
            ReferenceBreakContext context = _referenceBreakContext;
            if (context == null || candidate == null)
                return false;
            DateTime promotedUtc = NormalizeUtc(candidate.PromotedUtc);
            if (promotedUtc < context.FailedUtc || promotedUtc > context.ExpiresUtc)
                return false;
            if (context.BreakSponsorObjectId == candidate.ObjectId)
                return true;

            bool sameReferenceRoot = resolution?.RootObjectId
                == context.ReferenceObjectId;
            if ((!sameReferenceRoot
                    && !ReferenceBreakSponsorEligible(context, candidate))
                || ReferenceContinuationChild(context,
                    candidate.MinTick, candidate.MaxTick))
            {
                return false;
            }

            context.BreakSponsorObjectId = candidate.ObjectId;
            AddReferenceBreakAudit("reference_break_sponsor_bound",
                promotedUtc,
                context,
                candidate,
                sameReferenceRoot ? $"{reason}_root" : reason);
            return true;
        }

        private bool ReferenceBreakSuppressesCampaignPromotion(
            SponsorContext candidate)
        {
            ReferenceBreakContext context = _referenceBreakContext;
            if (context == null || candidate == null || _currentSponsor == null)
                return false;
            DateTime promotedUtc = NormalizeUtc(candidate.PromotedUtc);
            return promotedUtc >= context.FailedUtc
                && promotedUtc <= context.ExpiresUtc
                && candidate.Side == DesiredEvidenceSide()
                && candidate.ObjectId != context.BreakSponsorObjectId
                && ReferenceContinuationChild(context,
                    candidate.MinTick, candidate.MaxTick);
        }

        private bool ReferenceBreakSponsorEligible(
            ReferenceBreakContext context,
            SponsorContext candidate)
            => context != null
                && candidate != null
                && candidate.Side == DesiredEvidenceSide()
                && !ReferenceContinuationChild(context,
                    candidate.MinTick, candidate.MaxTick)
                && RangeDistance(candidate.MinTick, candidate.MaxTick,
                    context.ReferenceMinTick, context.ReferenceMaxTick)
                    <= ReferenceBreakSponsorDistanceTicks;

        private bool ReferenceContinuationChild(
            ReferenceBreakContext context,
            long minTick,
            long maxTick)
            => context != null
                && (DesiredEvidenceSide() == EvidenceSide.Demand
                    ? minTick > context.ReferenceMaxTick
                        + ReferenceBreakChildSeparationTicks
                    : maxTick < context.ReferenceMinTick
                        - ReferenceBreakChildSeparationTicks);

        private void PauseWhileFlat()
        {
            State = RuntimeExecutionState.Paused;
            _pendingEntryIntent = null;
            _pendingReclaim = null;
            _pendingRetest = null;
            _failureAssistedParent = null;
        }

        private void InvalidateWhileFlat()
        {
            State = RuntimeExecutionState.Invalidated;
            _pendingEntryIntent = null;
            _pendingReclaim = null;
            _pendingRetest = null;
            _failureAssistedParent = null;
        }

        private bool HasActiveAdverseFailures
            => _activeAdverseFailureIds.Count > 0;

        private void ObserveAdverseFailures(IReadOnlyList<EvidenceTransition> transitions)
        {
            foreach (EvidenceTransition transition in transitions)
            {
                if (transition?.Band == null || !IsAdverseFailure(transition.Band))
                    continue;
                if (transition.Kind == EvidenceTransitionKind.FailureInvalidated)
                {
                    _activeAdverseFailureIds.Remove(transition.Band.Id);
                    _baselineFailureIds.Remove(transition.Band.Id);
                }
                else if (IsFreshAdverseFailureHeld(transition))
                {
                    _activeAdverseFailureIds.Add(transition.Band.Id);
                }
            }
        }

        private void ObserveFailureAssistedContext(
            IReadOnlyList<EvidenceTransition> transitions,
            DateTime nowUtc)
        {
            if (!_failureAssistedEntriesEnabled || _directive == null)
                return;
            ExpireFailureAssistedParent(nowUtc);
            foreach (EvidenceTransition transition in transitions)
            {
                EvidenceBandView band = transition?.Band;
                if (band == null)
                    continue;

                if (_failureAssistedParent != null
                    && band.Id == _failureAssistedParent.ParentObjectId
                    && transition.Kind == EvidenceTransitionKind.FailureInvalidated)
                {
                    ClearFailureAssistedParent(transition.TimeUtc,
                        "parent_failure_invalidated");
                    continue;
                }

                if (_failureAssistedParent?.ChildObjectId == band.Id
                    && transition.Kind == EvidenceTransitionKind.RailFailed)
                {
                    AddFailureParentAudit("failure_parent_child_failed",
                        transition.TimeUtc,
                        _failureAssistedParent,
                        band,
                        "child_failed_before_fill");
                    ClearPendingFailureAssistedRetest();
                    _failureAssistedParent = null;
                    continue;
                }

                if (!IsFreshFavorableFailureHeld(transition)
                    || _failureAssistedParent?.ChildObjectId.HasValue == true)
                {
                    continue;
                }

                ArmFailureAssistedParent(transition);
            }
        }

        private void ObserveReferenceBreakContext(
            IReadOnlyList<EvidenceTransition> transitions,
            DateTime nowUtc,
            RuntimePosition position)
        {
            ExpireReferenceBreakContext(nowUtc);
            if (_directive == null || transitions == null
                || position == null || position.IsFlat)
            {
                return;
            }

            foreach (EvidenceTransition transition in transitions)
            {
                EvidenceBandView band = transition?.Band;
                if (band == null)
                    continue;

                if (_referenceBreakContext != null
                    && IsReferenceReclaim(transition, band))
                {
                    AddReferenceBreakAudit("reference_break_invalidated",
                        transition.TimeUtc,
                        _referenceBreakContext,
                        child: null,
                        "old_reference_reclaimed");
                    _referenceBreakContext = null;
                    continue;
                }

                if (IsQualifiedReferenceBreak(transition, band))
                    ArmReferenceBreakContext(transition, band);
            }
        }

        private bool IsQualifiedReferenceBreak(
            EvidenceTransition transition,
            EvidenceBandView band)
        {
            if (transition.Kind != EvidenceTransitionKind.RailFailed
                || band.Role != EvidenceRole.Rail
                || band.Side == DesiredEvidenceSide()
                || band.FormedUtc == default
                || !ContextEligible(band))
            {
                return false;
            }

            DateTime failedUtc = NormalizeUtc(transition.TimeUtc);
            DateTime formedUtc = NormalizeUtc(band.FormedUtc);
            return failedUtc >= _activatedUtc
                && (failedUtc - formedUtc).TotalSeconds
                    >= ReferenceBreakMinAgeSeconds;
        }

        private void ArmReferenceBreakContext(
            EvidenceTransition transition,
            EvidenceBandView band)
        {
            DateTime failedUtc = NormalizeUtc(transition.TimeUtc);
            var context = new ReferenceBreakContext
            {
                ReferenceObjectId = band.Id,
                ReferenceSide = band.Side,
                ReferenceMinTick = band.MinTick,
                ReferenceMaxTick = band.MaxTick,
                ReferenceFormedUtc = NormalizeUtc(band.FormedUtc),
                FailedUtc = failedUtc,
                ExpiresUtc = failedUtc.AddSeconds(ReferenceBreakContextTtlSeconds),
            };

            if (ReferenceBreakSponsorEligible(context, _currentSponsor))
                context.BreakSponsorObjectId = _currentSponsor.ObjectId;

            _referenceBreakContext = context;
            AddReferenceBreakAudit("reference_break_armed",
                transition.TimeUtc,
                context,
                _currentSponsor,
                context.BreakSponsorObjectId.HasValue
                    ? "old_reference_failed_current_sponsor_bound"
                    : "old_reference_failed");
        }

        private bool IsReferenceReclaim(
            EvidenceTransition transition,
            EvidenceBandView band)
        {
            ReferenceBreakContext context = _referenceBreakContext;
            return context != null
                && transition.Kind == EvidenceTransitionKind.RailOwned
                && band.Role == EvidenceRole.Rail
                && band.IsLiveRail
                && band.Side == context.ReferenceSide
                && NormalizeUtc(transition.TimeUtc) >= context.FailedUtc
                && RangeDistance(band.MinTick, band.MaxTick,
                    context.ReferenceMinTick, context.ReferenceMaxTick)
                    <= ReferenceBreakReclaimDistanceTicks;
        }

        private void ExpireReferenceBreakContext(DateTime nowUtc)
        {
            if (_referenceBreakContext == null)
                return;
            nowUtc = NormalizeUtc(nowUtc);
            if (nowUtc <= _referenceBreakContext.ExpiresUtc)
                return;
            AddReferenceBreakAudit("reference_break_expired",
                nowUtc,
                _referenceBreakContext,
                child: null,
                "context_expired");
            _referenceBreakContext = null;
        }

        private bool IsFreshFavorableFailureHeld(EvidenceTransition transition)
            => transition?.Kind == EvidenceTransitionKind.FailureHeld
                && transition.Band != null
                && transition.Band.Role == EvidenceRole.FailureZone
                && !_baselineFailureIds.Contains(transition.Band.Id)
                && transition.TimeUtc >= _activatedUtc
                && (State == RuntimeExecutionState.Armed
                    || State == RuntimeExecutionState.BaseOnly
                    || State == RuntimeExecutionState.Leveraged)
                && (State != RuntimeExecutionState.Armed || !HasActiveAdverseFailures)
                && transition.Band.Side == DesiredEvidenceSide()
                && ContextEligible(transition.Band);

        private void ArmFailureAssistedParent(EvidenceTransition transition)
        {
            EvidenceBandView band = transition.Band;
            _failureAssistedParent = new FailureAssistedParent
            {
                ParentObjectId = band.Id,
                Side = band.Side,
                MinTick = band.MinTick,
                MaxTick = band.MaxTick,
                FormedUtc = band.FormedUtc,
                HeldUtc = NormalizeUtc(transition.TimeUtc),
                ExpiresUtc = NormalizeUtc(transition.TimeUtc)
                    .AddSeconds(FailureAssistedParentTtlSeconds),
            };
            AddFailureParentAudit("failure_parent_armed",
                transition.TimeUtc,
                _failureAssistedParent,
                child: null,
                "favorable_failure_held");
        }

        private bool FailureAssistedChildEligible(
            FailureAssistedParent parent,
            EvidenceTransition transition,
            EvidenceBandView band,
            bool isAdd)
        {
            if (parent.ChildObjectId.HasValue
                && parent.ChildObjectId.Value != band.Id)
            {
                return false;
            }

            return transition.Kind == EvidenceTransitionKind.RailOwned
                && band.Role == EvidenceRole.Rail
                && band.IsLiveRail
                && band.Side == parent.Side
                && band.Side == DesiredEvidenceSide()
                && transition.TimeUtc >= parent.HeldUtc
                && band.FormedUtc >= parent.HeldUtc
                && RootEligible(band.Id, band.FormedUtc, isAdd)
                && ContextEligible(band)
                && OwnershipDisplacedFavorably(transition, band)
                && ChildBeyondFailureParent(parent, band);
        }

        private bool ChildBeyondFailureParent(
            FailureAssistedParent parent,
            EvidenceBandView child)
            => DesiredEvidenceSide() == EvidenceSide.Demand
                ? child.MinTick >= parent.MaxTick - FailureAssistedChildTouchTicks
                : child.MaxTick <= parent.MinTick + FailureAssistedChildTouchTicks;

        private void ExpireFailureAssistedParent(DateTime nowUtc)
        {
            if (_failureAssistedParent == null)
                return;
            nowUtc = NormalizeUtc(nowUtc);
            if (nowUtc <= _failureAssistedParent.ExpiresUtc)
                return;
            ClearFailureAssistedParent(nowUtc, "parent_context_expired");
        }

        private void ClearFailureAssistedParent(DateTime nowUtc, string reason)
        {
            if (_failureAssistedParent == null)
                return;
            AddFailureParentAudit("failure_parent_invalidated",
                nowUtc,
                _failureAssistedParent,
                child: null,
                reason);
            ClearPendingFailureAssistedRetest();
            _failureAssistedParent = null;
        }

        private void ClearPendingFailureAssistedRetest()
        {
            if (_pendingRetest?.Resolution?.FailureAssisted == true)
                _pendingRetest = null;
        }

        private void AddFailureParentAudit(
            string eventType,
            DateTime timeUtc,
            FailureAssistedParent parent,
            EvidenceBandView child,
            string reason)
        {
            if (parent == null)
                return;
            _auditEvents.Add(new CoordinatorAuditEvent
            {
                EventType = eventType,
                TimeUtc = NormalizeUtc(timeUtc),
                DirectiveId = _directive?.Id,
                Reason = reason,
                ParentObjectId = parent.ParentObjectId,
                ParentSide = parent.Side,
                ParentMinTick = parent.MinTick,
                ParentMaxTick = parent.MaxTick,
                ChildObjectId = child?.Id ?? parent.ChildObjectId,
                ChildSource = child?.Source ?? parent.ChildSource,
                ChildMinTick = child?.MinTick ?? parent.ChildMinTick,
                ChildMaxTick = child?.MaxTick ?? parent.ChildMaxTick,
            });
        }

        private void AddFailureParentAudit(
            string eventType,
            DateTime timeUtc,
            ResolutionContext resolution,
            string reason)
        {
            if (resolution?.FailureAssisted != true)
                return;
            _auditEvents.Add(new CoordinatorAuditEvent
            {
                EventType = eventType,
                TimeUtc = NormalizeUtc(timeUtc),
                DirectiveId = _directive?.Id,
                Reason = reason,
                ParentObjectId = resolution.FailureParentObjectId,
                ParentSide = DesiredEvidenceSide(),
                ParentMinTick = resolution.FailureParentMinTick,
                ParentMaxTick = resolution.FailureParentMaxTick,
                ChildObjectId = resolution.SupportObjectId,
                ChildSource = resolution.SupportSource,
                ChildMinTick = resolution.SupportMinTick,
                ChildMaxTick = resolution.SupportMaxTick,
            });
        }

        private void AddReferenceBreakAudit(
            string eventType,
            DateTime timeUtc,
            ReferenceBreakContext parent,
            SponsorContext child,
            string reason)
        {
            if (parent == null)
                return;
            _auditEvents.Add(new CoordinatorAuditEvent
            {
                EventType = eventType,
                TimeUtc = NormalizeUtc(timeUtc),
                DirectiveId = _directive?.Id,
                Reason = reason,
                ParentObjectId = parent.ReferenceObjectId,
                ParentSide = parent.ReferenceSide,
                ParentMinTick = parent.ReferenceMinTick,
                ParentMaxTick = parent.ReferenceMaxTick,
                ChildObjectId = child?.ObjectId,
                ChildSource = child?.Source,
                ChildMinTick = child?.MinTick,
                ChildMaxTick = child?.MaxTick,
            });
        }

        private bool IsFreshAdverseFailureHeld(EvidenceTransition transition)
            => transition?.Kind == EvidenceTransitionKind.FailureHeld
                && transition.Band != null
                && !_baselineFailureIds.Contains(transition.Band.Id)
                && transition.TimeUtc >= _activatedUtc
                && IsAdverseFailure(transition.Band);

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
            AddFailureParentAudit("failure_parent_entry",
                nowUtc,
                resolution,
                reason);
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

        private bool IsAdverseFailure(EvidenceBandView band)
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

        private bool ContinuationRangesMatch(TradeDirective directive)
            => SameRangeByTick(_directive.OrderPriceRange, directive.OrderPriceRange)
                && SameRangeByTick(_directive.ContextPriceRange,
                    directive.ContextPriceRange)
                && SameOptionalRangeByTick(_directive.AddPriceRange,
                    directive.AddPriceRange);

        private bool SameOptionalRangeByTick(PriceRange left, PriceRange right)
        {
            if (left == null || right == null)
                return left == null && right == null;
            return SameRangeByTick(left, right);
        }

        private bool SameRangeByTick(PriceRange left, PriceRange right)
            => left != null && right != null
                && PriceToTick(left.Lower) == PriceToTick(right.Lower)
                && PriceToTick(left.Upper) == PriceToTick(right.Upper);

        private static DateTime MaxUtc(DateTime left, DateTime right)
        {
            left = NormalizeUtc(left);
            right = NormalizeUtc(right);
            return left >= right ? left : right;
        }

        private static bool IsContinuationProtectiveExit(string reason)
            => !string.IsNullOrWhiteSpace(reason)
                && (reason.StartsWith("sponsor_failed:", StringComparison.Ordinal)
                    || reason.StartsWith("sponsor_consumed:", StringComparison.Ordinal)
                    || reason.StartsWith("failure_parent_child_failed:",
                        StringComparison.Ordinal)
                    || string.Equals(reason, "reverse_entry_resolution",
                        StringComparison.Ordinal)
                    || string.Equals(reason, "base_support_lost",
                        StringComparison.Ordinal));

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
            public string Reason;
        }

        private sealed class FailureAssistedParent
        {
            public int ParentObjectId;
            public EvidenceSide Side;
            public long MinTick;
            public long MaxTick;
            public DateTime FormedUtc;
            public DateTime HeldUtc;
            public DateTime ExpiresUtc;
            public int? ChildObjectId;
            public EvidenceSource? ChildSource;
            public long? ChildMinTick;
            public long? ChildMaxTick;
            public DateTime ChildFormedUtc;
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
