using System;
using System.Collections.Generic;
using System.Linq;

namespace ExecAssistantRuntime
{
    internal enum EvidenceSide
    {
        Demand,
        Supply,
    }

    internal enum EvidenceSource
    {
        Lean,
        Consumed,
    }

    internal enum EvidenceRole
    {
        Rail,
        NoOwner,
        Contested,
        FailureZone,
    }

    internal enum EvidenceState
    {
        Candidate,
        Owned,
        Tested,
        Held,
        Failed,
        NoOwner,
        Contested,
        Removed,
    }

    internal enum CandidateDirection
    {
        None,
        Favor,
        Adverse,
    }

    internal enum EvidenceTransitionKind
    {
        CandidateFormed,
        CandidateDisplacementStarted,
        CandidateDisplacementReset,
        RailOwned,
        RailTested,
        RailHeld,
        RailFailed,
        GreyUpdated,
        FailureCandidateFormed,
        FailureHeld,
        FailureInvalidated,
    }

    internal sealed class DepthLevelSnapshot
    {
        public double Price { get; init; }
        public double Size { get; init; }
    }

    internal sealed class BookDepthSnapshot
    {
        public DateTime TimeUtc { get; init; }
        public IReadOnlyList<DepthLevelSnapshot> Bids { get; init; }
        public IReadOnlyList<DepthLevelSnapshot> Asks { get; init; }
    }

    internal sealed class EvidenceCandidateView
    {
        public int Id { get; init; }
        public EvidenceSide Side { get; init; }
        public long MinTick { get; init; }
        public long MaxTick { get; init; }
        public DateTime FormedUtc { get; init; }
        public DateTime LastUpdateUtc { get; init; }
        public int EventCount { get; init; }
        public double Score { get; init; }
        public CandidateDirection Direction { get; init; }
        public DateTime? DirectionStartedUtc { get; init; }
        public bool IsActive { get; init; }
    }

    internal sealed class EvidenceBandView
    {
        public int Id { get; init; }
        public EvidenceRole Role { get; init; }
        public EvidenceSide Side { get; init; }
        public EvidenceSide SourceSide { get; init; }
        public EvidenceSource Source { get; init; }
        public EvidenceState State { get; init; }
        public long MinTick { get; init; }
        public long MaxTick { get; init; }
        public DateTime FormedUtc { get; init; }
        public DateTime OwnedUtc { get; init; }
        public DateTime LastStateUtc { get; init; }
        public DateTime? FailedUtc { get; init; }
        public int EventCount { get; init; }
        public double Score { get; init; }

        public bool IsLiveRail
            => Role == EvidenceRole.Rail && State != EvidenceState.Failed && State != EvidenceState.Removed;
    }

    internal sealed class EvidenceTransition
    {
        public EvidenceTransitionKind Kind { get; init; }
        public DateTime TimeUtc { get; init; }
        public long CurrentMidTick { get; init; }
        public EvidenceCandidateView Candidate { get; init; }
        public EvidenceBandView Band { get; init; }
        public string Reason { get; init; }
    }

    internal sealed class EvidenceEngineSettings
    {
        public int BookLookbackSeconds { get; init; } = 30;
        public double EventZThreshold { get; init; } = 2.5;
        public int ClusterMinEvents { get; init; } = 3;
        public int ClusterTicks { get; init; } = 10;
        public int ClusterSeconds { get; init; } = 90;
        public double ClusterMinScore { get; init; } = 8.0;
        public int ConfirmMoveTicks { get; init; } = 8;
        public int ConfirmSeconds { get; init; } = 10;
        public int FailureBufferTicks { get; init; } = 2;
        public int FailureConfirmTicks { get; init; } = 24;
        public int FailureSeconds { get; init; } = 20;
    }

    /// <summary>
    /// A copied, execution-facing subset of LevelLedger's ownership engine.
    /// Keep changes independent from LevelLedger and document intentional drift.
    /// </summary>
    internal sealed class ExecutionEvidenceEngine
    {
        private const int InnerLevels = 10;
        private const int BroadLevels = 30;
        private const int OwnershipTestBufferTicks = 4;
        private const int OwnershipHoldConfirmTicks = 10;
        private const int OwnershipContestedSec = 20 * 60;
        private const int OwnershipContestedProximityTicks = 80;
        private const int OwnershipContestedSpanTicks = 240;
        private const int OwnershipContestedMinFails = 4;
        private const int OwnershipNoOwnerMinFails = 2;
        private const int FailureZoneGreyTtlSec = 25 * 60;
        private const int FailureZoneMergeSec = 12 * 60;
        private const int FailureZoneMergeTicks = 96;
        private const int FailureZoneSplitExtensionTicks = 96;
        private const int FailureZoneConfirmTicks = 24;
        private const int FailureZoneConfirmSec = 10;
        private const int FailureZoneInvalidateTicks = 8;
        private const int FailureZoneCandidateTtlSec = 30 * 60;

        private readonly EvidenceEngineSettings _settings;
        private readonly double _tickSize;
        private readonly LinkedList<BookSample> _samples = new();
        private readonly LinkedList<BandEvent> _pendingEvents = new();
        private readonly List<Candidate> _candidates = new();
        private readonly LinkedList<Band> _bands = new();
        private readonly List<EvidenceTransition> _transitions = new();
        private int _nextId = 1;

        public ExecutionEvidenceEngine(double tickSize, EvidenceEngineSettings settings = null)
        {
            _tickSize = double.IsFinite(tickSize) && tickSize > 0 ? tickSize : 0.25;
            _settings = settings ?? new EvidenceEngineSettings();
        }

        public long? LastMidTick { get; private set; }

        public IReadOnlyList<EvidenceTransition> Process(BookDepthSnapshot depth)
        {
            _transitions.Clear();
            if (depth == null)
                return Array.Empty<EvidenceTransition>();

            DateTime nowUtc = NormalizeUtc(depth.TimeUtc);
            BookSample sample = ComputeSample(depth, nowUtc);
            if (sample == null)
                return Array.Empty<EvidenceTransition>();

            LastMidTick = sample.MidTick;
            _samples.AddLast(sample);
            EvictSamples(nowUtc, Math.Max(10, _settings.BookLookbackSeconds * 2));

            if (_samples.Count >= 5)
            {
                (double mBi, double sBi) = MeanStd(s => s.BidInner, nowUtc);
                (double mAi, double sAi) = MeanStd(s => s.AskInner, nowUtc);
                (double mBc, double sBc) = MeanStd(s => s.BidCentroid, nowUtc);
                (double mAc, double sAc) = MeanStd(s => s.AskCentroid, nowUtc);

                double zBi = (sample.BidInner - mBi) / Math.Max(1.0, sBi);
                double zAi = (sample.AskInner - mAi) / Math.Max(1.0, sAi);
                double zBc = (sample.BidCentroid - mBc) / Math.Max(0.01, sBc);
                double zAc = (sample.AskCentroid - mAc) / Math.Max(0.01, sAc);

                TryFire(nowUtc, sample.MidTick, zBi, +1, "BID_BUILD", "BID_PULL");
                TryFire(nowUtc, sample.MidTick, zAi, -1, "ASK_BUILD", "ASK_PULL");
                TryFire(nowUtc, sample.MidTick, zBc, -1, "BID_OUT", "BID_IN");
                TryFire(nowUtc, sample.MidTick, zAc, +1, "ASK_OUT", "ASK_IN");
            }

            UpdateCandidates(nowUtc, sample.MidTick);
            UpdateRails(nowUtc, sample.MidTick);
            UpdateFailureObjects(nowUtc, sample.MidTick);
            Prune(nowUtc);
            return _transitions.ToArray();
        }

        public EvidenceCandidateView FindCandidate(int id)
        {
            Candidate candidate = _candidates.FirstOrDefault(c => c.Id == id);
            return candidate == null ? null : View(candidate);
        }

        public EvidenceBandView FindBand(int id)
        {
            Band band = _bands.FirstOrDefault(b => b.Id == id);
            return band == null ? null : View(band);
        }

        public IReadOnlyList<EvidenceCandidateView> ActiveCandidates(EvidenceSide side)
            => _candidates
                .Where(c => c.Active && c.Side == side)
                .Select(View)
                .ToArray();

        public IReadOnlyList<EvidenceBandView> LiveRails(EvidenceSide side)
            => _bands
                .Where(b => b.Role == EvidenceRole.Rail && b.Side == side
                    && b.State != EvidenceState.Failed && b.State != EvidenceState.Removed)
                .Select(View)
                .ToArray();

        public IReadOnlyList<EvidenceBandView> HeldFailureObjects()
            => _bands
                .Where(b => b.Role == EvidenceRole.FailureZone && b.State == EvidenceState.Held)
                .Select(View)
                .ToArray();

        private void TryFire(DateTime timeUtc, long priceTick, double z, int positiveBias,
            string positiveLabel, string negativeLabel)
        {
            double absZ = Math.Abs(z);
            if (absZ <= Math.Max(1.0, _settings.EventZThreshold))
                return;
            int bias = z > 0 ? positiveBias : -positiveBias;
            AddBandEvent(new BandEvent
            {
                TimeUtc = timeUtc,
                PriceTick = priceTick,
                Side = bias > 0 ? EvidenceSide.Demand : EvidenceSide.Supply,
                AbsZ = absZ,
                Type = z > 0 ? positiveLabel : negativeLabel,
            });
        }

        private void AddBandEvent(BandEvent ev)
        {
            int clusterTicks = Math.Max(1, _settings.ClusterTicks);
            int clusterSeconds = Math.Max(1, _settings.ClusterSeconds);

            foreach (Candidate candidate in _candidates)
            {
                if (!candidate.Active || candidate.Side != ev.Side)
                    continue;
                if ((ev.TimeUtc - candidate.LastUpdateUtc).TotalSeconds > clusterSeconds)
                    continue;
                if (ev.PriceTick < candidate.MinTick - clusterTicks
                    || ev.PriceTick > candidate.MaxTick + clusterTicks)
                    continue;

                candidate.MinTick = Math.Min(candidate.MinTick, ev.PriceTick);
                candidate.MaxTick = Math.Max(candidate.MaxTick, ev.PriceTick);
                candidate.LastUpdateUtc = ev.TimeUtc;
                candidate.EventCount++;
                candidate.Score += ev.AbsZ;
                candidate.Kinds.Add(ev.Type);
                return;
            }

            var members = new List<BandEvent> { ev };
            foreach (BandEvent pending in _pendingEvents)
            {
                if (pending.Side != ev.Side)
                    continue;
                if (Math.Abs(pending.PriceTick - ev.PriceTick) > clusterTicks)
                    continue;
                if ((ev.TimeUtc - pending.TimeUtc).TotalSeconds > clusterSeconds)
                    continue;
                members.Add(pending);
            }

            double score = members.Sum(m => m.AbsZ);
            if (members.Count >= Math.Max(2, _settings.ClusterMinEvents)
                && score >= Math.Max(0, _settings.ClusterMinScore))
            {
                var candidate = new Candidate
                {
                    Id = _nextId++,
                    Side = ev.Side,
                    MinTick = members.Min(m => m.PriceTick),
                    MaxTick = members.Max(m => m.PriceTick),
                    StartUtc = members.Min(m => m.TimeUtc),
                    FormedUtc = ev.TimeUtc,
                    LastUpdateUtc = members.Max(m => m.TimeUtc),
                    EventCount = members.Count,
                    Score = score,
                    Kinds = new HashSet<string>(members.Select(m => m.Type)),
                };
                _candidates.Add(candidate);
                var memberSet = new HashSet<BandEvent>(members);
                LinkedListNode<BandEvent> node = _pendingEvents.First;
                while (node != null)
                {
                    LinkedListNode<BandEvent> next = node.Next;
                    if (memberSet.Contains(node.Value))
                        _pendingEvents.Remove(node);
                    node = next;
                }
                Emit(EvidenceTransitionKind.CandidateFormed, ev.TimeUtc, ev.PriceTick,
                    candidate: candidate);
            }
            else
            {
                _pendingEvents.AddLast(ev);
            }
        }

        private void UpdateCandidates(DateTime nowUtc, long currentMidTick)
        {
            int confirmTicks = Math.Max(1, _settings.ConfirmMoveTicks);
            foreach (Candidate candidate in _candidates)
            {
                if (!candidate.Active)
                    continue;
                CandidateDirection direction = Direction(candidate, currentMidTick, confirmTicks);
                if (direction == CandidateDirection.None)
                {
                    if (candidate.PendingDirection != CandidateDirection.None)
                    {
                        Emit(EvidenceTransitionKind.CandidateDisplacementReset, nowUtc,
                            currentMidTick, candidate: candidate, reason: "inside_threshold");
                    }
                    candidate.PendingDirection = CandidateDirection.None;
                    candidate.PendingDirectionUtc = null;
                    continue;
                }

                if (candidate.PendingDirection != direction)
                {
                    if (candidate.PendingDirection != CandidateDirection.None)
                    {
                        Emit(EvidenceTransitionKind.CandidateDisplacementReset, nowUtc,
                            currentMidTick, candidate: candidate, reason: "direction_changed");
                    }
                    candidate.PendingDirection = direction;
                    candidate.PendingDirectionUtc = nowUtc;
                    Emit(EvidenceTransitionKind.CandidateDisplacementStarted, nowUtc,
                        currentMidTick, candidate: candidate, reason: direction.ToString());
                    continue;
                }

                if (!candidate.PendingDirectionUtc.HasValue
                    || (nowUtc - candidate.PendingDirectionUtc.Value).TotalSeconds
                        < Math.Max(0, _settings.ConfirmSeconds))
                {
                    continue;
                }

                EvidenceSide resultingSide = direction == CandidateDirection.Favor
                    ? candidate.Side
                    : Opposite(candidate.Side);
                EvidenceSource source = direction == CandidateDirection.Favor
                    ? EvidenceSource.Lean
                    : EvidenceSource.Consumed;
                var band = new Band
                {
                    Id = candidate.Id,
                    Role = EvidenceRole.Rail,
                    Side = resultingSide,
                    SourceSide = candidate.Side,
                    Source = source,
                    State = EvidenceState.Owned,
                    MinTick = candidate.MinTick,
                    MaxTick = candidate.MaxTick,
                    FormedUtc = candidate.FormedUtc,
                    OwnedUtc = nowUtc,
                    LastUpdateUtc = candidate.LastUpdateUtc,
                    LastStateUtc = nowUtc,
                    EventCount = candidate.EventCount,
                    Score = candidate.Score,
                };
                _bands.AddLast(band);
                candidate.Active = false;
                Emit(EvidenceTransitionKind.RailOwned, nowUtc, currentMidTick,
                    candidate: candidate, band: band,
                    reason: source == EvidenceSource.Consumed ? "CONSUMED" : "OWNED");
                RecordFailureObjectFromRail(band, nowUtc, currentMidTick);
            }
        }

        private void UpdateRails(DateTime nowUtc, long currentMidTick)
        {
            // Rail failure can create grey-zone objects in the same sample.
            // Iterate a stable snapshot so those additions cannot invalidate the walk.
            foreach (Band band in _bands.ToArray())
            {
                if (band.Role != EvidenceRole.Rail || band.State == EvidenceState.Failed)
                    continue;

                if (RailFailCondition(band, currentMidTick))
                {
                    band.PendingFailureUtc ??= nowUtc;
                    bool moveConfirmed = RailFailMoveConfirmed(band, currentMidTick);
                    bool timeConfirmed = (nowUtc - band.PendingFailureUtc.Value).TotalSeconds
                        >= Math.Max(0, _settings.FailureSeconds);
                    if (moveConfirmed || timeConfirmed)
                    {
                        band.State = EvidenceState.Failed;
                        band.FailedUtc = nowUtc;
                        band.LastStateUtc = nowUtc;
                        Emit(EvidenceTransitionKind.RailFailed, nowUtc, currentMidTick,
                            band: band, reason: moveConfirmed ? "move" : "time");
                        RecordGrey(band, nowUtc, EvidenceRole.NoOwner, currentMidTick);
                        RecordGrey(band, nowUtc, EvidenceRole.Contested, currentMidTick);
                    }
                    continue;
                }

                band.PendingFailureUtc = null;
                if (RailTestCondition(band, currentMidTick))
                {
                    if (band.State != EvidenceState.Tested)
                    {
                        band.State = EvidenceState.Tested;
                        band.LastStateUtc = nowUtc;
                        Emit(EvidenceTransitionKind.RailTested, nowUtc, currentMidTick, band: band);
                    }
                    continue;
                }

                if (band.State == EvidenceState.Tested && RailHoldCondition(band, currentMidTick))
                {
                    band.State = EvidenceState.Owned;
                    band.LastStateUtc = nowUtc;
                    Emit(EvidenceTransitionKind.RailHeld, nowUtc, currentMidTick, band: band);
                }
            }
        }

        private void RecordGrey(Band failedBand, DateTime nowUtc, EvidenceRole role, long currentMidTick)
        {
            Band matched = null;
            foreach (Band zone in _bands)
            {
                if (zone.Role != role)
                    continue;
                if ((nowUtc - zone.LastUpdateUtc).TotalSeconds > OwnershipContestedSec)
                    continue;
                if (failedBand.MaxTick < zone.MinTick - OwnershipContestedProximityTicks
                    || failedBand.MinTick > zone.MaxTick + OwnershipContestedProximityTicks)
                    continue;
                long nextMin = Math.Min(zone.MinTick, failedBand.MinTick);
                long nextMax = Math.Max(zone.MaxTick, failedBand.MaxTick);
                if (nextMax - nextMin > OwnershipContestedSpanTicks)
                    continue;
                matched = zone;
                break;
            }

            if (matched == null)
            {
                matched = new Band
                {
                    Id = _nextId++,
                    Role = role,
                    Side = failedBand.Side,
                    State = role == EvidenceRole.NoOwner
                        ? EvidenceState.NoOwner
                        : EvidenceState.Contested,
                    MinTick = failedBand.MinTick,
                    MaxTick = failedBand.MaxTick,
                    FormedUtc = nowUtc,
                    OwnedUtc = nowUtc,
                    LastUpdateUtc = nowUtc,
                    LastStateUtc = nowUtc,
                    EventCount = 1,
                    Score = failedBand.Score,
                };
                _bands.AddLast(matched);
            }
            else
            {
                matched.MinTick = Math.Min(matched.MinTick, failedBand.MinTick);
                matched.MaxTick = Math.Max(matched.MaxTick, failedBand.MaxTick);
                matched.LastUpdateUtc = nowUtc;
                matched.LastStateUtc = nowUtc;
                matched.Score += failedBand.Score;
                matched.EventCount++;
            }

            if (failedBand.Side == EvidenceSide.Demand)
                matched.DemandFailCount++;
            else
                matched.SupplyFailCount++;
            Emit(EvidenceTransitionKind.GreyUpdated, nowUtc, currentMidTick,
                band: matched, reason: role.ToString());
        }

        private void RecordFailureObjectFromRail(Band rail, DateTime nowUtc, long currentMidTick)
        {
            long minTick = rail.MinTick;
            long maxTick = rail.MaxTick;
            if (rail.Source == EvidenceSource.Consumed)
            {
                if (rail.Side == EvidenceSide.Demand)
                    maxTick = Math.Max(maxTick, currentMidTick);
                else
                    minTick = Math.Min(minTick, currentMidTick);
            }

            if (!TryFindOutsideGrey(rail.Side, minTick, maxTick, nowUtc, out Band grey))
                return;

            Band existing = FindMergeableFailureObject(
                rail.Side, minTick, maxTick, nowUtc);
            if (existing != null)
            {
                existing.MinTick = Math.Min(existing.MinTick, minTick);
                existing.MaxTick = Math.Max(existing.MaxTick, maxTick);
                existing.LastUpdateUtc = nowUtc;
                existing.LastStateUtc = nowUtc;
                existing.EventCount += rail.EventCount;
                existing.Score += rail.Score;
                existing.Source = rail.Source == EvidenceSource.Consumed
                    ? EvidenceSource.Consumed
                    : existing.Source;
                return;
            }

            var zone = new Band
            {
                Id = _nextId++,
                Role = EvidenceRole.FailureZone,
                Side = rail.Side,
                SourceSide = rail.SourceSide,
                Source = rail.Source,
                State = EvidenceState.Candidate,
                MinTick = minTick,
                MaxTick = maxTick,
                FormedUtc = nowUtc,
                OwnedUtc = nowUtc,
                LastUpdateUtc = nowUtc,
                LastStateUtc = nowUtc,
                EventCount = rail.EventCount,
                Score = rail.Score,
                GreyMinTick = grey.MinTick,
                GreyMaxTick = grey.MaxTick,
            };
            _bands.AddLast(zone);
            Emit(EvidenceTransitionKind.FailureCandidateFormed, nowUtc, currentMidTick,
                band: zone);
        }

        private void UpdateFailureObjects(DateTime nowUtc, long currentMidTick)
        {
            LinkedListNode<Band> node = _bands.First;
            while (node != null)
            {
                LinkedListNode<Band> next = node.Next;
                Band band = node.Value;
                if (band.Role == EvidenceRole.FailureZone)
                {
                    if (FailureObjectInvalidated(band, currentMidTick))
                    {
                        band.State = EvidenceState.Removed;
                        Emit(EvidenceTransitionKind.FailureInvalidated, nowUtc,
                            currentMidTick, band: band);
                        _bands.Remove(node);
                    }
                    else if (band.State == EvidenceState.Candidate)
                    {
                        double age = (nowUtc - band.OwnedUtc).TotalSeconds;
                        if (age > FailureZoneCandidateTtlSec)
                        {
                            band.State = EvidenceState.Removed;
                            Emit(EvidenceTransitionKind.FailureInvalidated, nowUtc,
                                currentMidTick, band: band, reason: "ttl");
                            _bands.Remove(node);
                        }
                        else if (age >= FailureZoneConfirmSec
                            && FailureObjectMovedAway(band, currentMidTick))
                        {
                            band.State = EvidenceState.Held;
                            band.LastStateUtc = nowUtc;
                            Emit(EvidenceTransitionKind.FailureHeld, nowUtc,
                                currentMidTick, band: band,
                                reason: band.Side == EvidenceSide.Demand ? "LF" : "HF");
                        }
                    }
                }
                node = next;
            }
        }

        private bool TryFindOutsideGrey(EvidenceSide side, long minTick, long maxTick,
            DateTime nowUtc, out Band grey)
        {
            IEnumerable<Band> active = _bands.Where(b => IsVisibleGrey(b)
                && (nowUtc - b.LastUpdateUtc).TotalSeconds <= FailureZoneGreyTtlSec);
            grey = side == EvidenceSide.Demand
                ? active.Where(g => maxTick < g.MinTick)
                    .OrderBy(g => g.MinTick - maxTick).FirstOrDefault()
                : active.Where(g => minTick > g.MaxTick)
                    .OrderBy(g => minTick - g.MaxTick).FirstOrDefault();
            return grey != null;
        }

        private Band FindMergeableFailureObject(EvidenceSide side, long minTick,
            long maxTick, DateTime nowUtc)
        {
            foreach (Band band in _bands.Reverse())
            {
                if (band.Role != EvidenceRole.FailureZone || band.Side != side)
                    continue;
                if ((nowUtc - band.LastUpdateUtc).TotalSeconds > FailureZoneMergeSec)
                    continue;
                if (side == EvidenceSide.Demand
                    && minTick < band.MinTick - FailureZoneSplitExtensionTicks)
                    continue;
                if (side == EvidenceSide.Supply
                    && maxTick > band.MaxTick + FailureZoneSplitExtensionTicks)
                    continue;
                if (maxTick < band.MinTick - FailureZoneMergeTicks
                    || minTick > band.MaxTick + FailureZoneMergeTicks)
                    continue;
                return band;
            }
            return null;
        }

        private static bool IsVisibleGrey(Band band)
            => band.Role == EvidenceRole.NoOwner
                ? band.EventCount >= OwnershipNoOwnerMinFails
                : band.Role == EvidenceRole.Contested
                    && band.DemandFailCount > 0
                    && band.SupplyFailCount > 0
                    && band.EventCount >= OwnershipContestedMinFails;

        private bool RailTestCondition(Band band, long tick)
        {
            int buffer = Math.Max(0, _settings.FailureBufferTicks);
            return band.Side == EvidenceSide.Demand
                ? tick >= band.MinTick - buffer && tick <= band.MaxTick + OwnershipTestBufferTicks
                : tick >= band.MinTick - OwnershipTestBufferTicks && tick <= band.MaxTick + buffer;
        }

        private bool RailFailCondition(Band band, long tick)
        {
            int buffer = Math.Max(0, _settings.FailureBufferTicks);
            return band.Side == EvidenceSide.Demand
                ? tick < band.MinTick - buffer
                : tick > band.MaxTick + buffer;
        }

        private bool RailFailMoveConfirmed(Band band, long tick)
        {
            int confirm = Math.Max(1, _settings.FailureConfirmTicks);
            return band.Side == EvidenceSide.Demand
                ? tick <= band.MinTick - confirm
                : tick >= band.MaxTick + confirm;
        }

        private static bool RailHoldCondition(Band band, long tick)
            => band.Side == EvidenceSide.Demand
                ? tick >= band.MaxTick + OwnershipHoldConfirmTicks
                : tick <= band.MinTick - OwnershipHoldConfirmTicks;

        private static bool FailureObjectInvalidated(Band band, long tick)
            => band.Side == EvidenceSide.Demand
                ? tick <= band.MinTick - FailureZoneInvalidateTicks
                : tick >= band.MaxTick + FailureZoneInvalidateTicks;

        private static bool FailureObjectMovedAway(Band band, long tick)
            => band.Side == EvidenceSide.Demand
                ? tick >= band.MaxTick + FailureZoneConfirmTicks
                : tick <= band.MinTick - FailureZoneConfirmTicks;

        private static CandidateDirection Direction(Candidate candidate, long tick, int confirmTicks)
        {
            bool favor = candidate.Side == EvidenceSide.Demand
                ? tick >= candidate.MaxTick + confirmTicks
                : tick <= candidate.MinTick - confirmTicks;
            if (favor)
                return CandidateDirection.Favor;
            bool adverse = candidate.Side == EvidenceSide.Demand
                ? tick <= candidate.MinTick - confirmTicks
                : tick >= candidate.MaxTick + confirmTicks;
            return adverse ? CandidateDirection.Adverse : CandidateDirection.None;
        }

        private BookSample ComputeSample(BookDepthSnapshot depth, DateTime timeUtc)
        {
            var bids = ValidLevels(depth.Bids).Take(BroadLevels).ToArray();
            var asks = ValidLevels(depth.Asks).Take(BroadLevels).ToArray();
            if (bids.Length == 0 && asks.Length == 0)
                return null;
            // Evidence price state belongs to the sampled DOM. L1 is kept out
            // of this contract so executable-quote freshness cannot shift an
            // ownership, rail, sponsor, or HF/LF transition.
            double bestBid = bids.FirstOrDefault()?.Price ?? double.NaN;
            double bestAsk = asks.FirstOrDefault()?.Price ?? double.NaN;
            long bidTick = double.IsFinite(bestBid) ? PriceToTick(bestBid) : 0;
            long askTick = double.IsFinite(bestAsk) ? PriceToTick(bestAsk) : 0;
            long midTick = double.IsFinite(bestBid) && double.IsFinite(bestAsk)
                ? (bidTick + askTick) / 2
                : double.IsFinite(bestBid) ? bidTick : askTick;

            var sample = new BookSample
            {
                TimeUtc = timeUtc,
                MidTick = midTick,
                BidInner = bids.Take(InnerLevels).Sum(l => l.Size),
                AskInner = asks.Take(InnerLevels).Sum(l => l.Size),
            };
            double bidSize = bids.Sum(l => l.Size);
            double askSize = asks.Sum(l => l.Size);
            sample.BidCentroid = bidSize > 0
                ? bids.Sum(l => Math.Abs(PriceToTick(l.Price) - midTick) * l.Size) / bidSize
                : 0;
            sample.AskCentroid = askSize > 0
                ? asks.Sum(l => Math.Abs(PriceToTick(l.Price) - midTick) * l.Size) / askSize
                : 0;
            return sample;
        }

        private (double Mean, double Std) MeanStd(
            Func<BookSample, double> selector,
            DateTime nowUtc)
        {
            DateTime cutoff = nowUtc.AddSeconds(-Math.Max(10, _settings.BookLookbackSeconds));
            double sum = 0;
            double sumSq = 0;
            int count = 0;
            foreach (BookSample sample in _samples)
            {
                if (sample.TimeUtc < cutoff)
                    continue;
                double value = selector(sample);
                sum += value;
                sumSq += value * value;
                count++;
            }
            if (count < 2)
                return (0, 0);
            double mean = sum / count;
            double variance = sumSq / count - mean * mean;
            return (mean, variance > 0 ? Math.Sqrt(variance) : 0);
        }

        private void Prune(DateTime nowUtc)
        {
            DateTime eventCutoff = nowUtc.AddSeconds(-Math.Max(1, _settings.ClusterSeconds));
            while (_pendingEvents.Count > 0 && _pendingEvents.First.Value.TimeUtc < eventCutoff)
                _pendingEvents.RemoveFirst();
            DateTime candidateCutoff = nowUtc.AddSeconds(-Math.Max(1, _settings.ClusterSeconds * 2));
            _candidates.RemoveAll(c => c.LastUpdateUtc < candidateCutoff);
        }

        private void EvictSamples(DateTime nowUtc, int seconds)
        {
            DateTime cutoff = nowUtc.AddSeconds(-seconds);
            while (_samples.Count > 0 && _samples.First.Value.TimeUtc < cutoff)
                _samples.RemoveFirst();
        }

        private void Emit(EvidenceTransitionKind kind, DateTime timeUtc, long currentMidTick,
            Candidate candidate = null, Band band = null, string reason = null)
        {
            _transitions.Add(new EvidenceTransition
            {
                Kind = kind,
                TimeUtc = timeUtc,
                CurrentMidTick = currentMidTick,
                Candidate = candidate == null ? null : View(candidate),
                Band = band == null ? null : View(band),
                Reason = reason,
            });
        }

        private static EvidenceCandidateView View(Candidate candidate)
            => new()
            {
                Id = candidate.Id,
                Side = candidate.Side,
                MinTick = candidate.MinTick,
                MaxTick = candidate.MaxTick,
                FormedUtc = candidate.FormedUtc,
                LastUpdateUtc = candidate.LastUpdateUtc,
                EventCount = candidate.EventCount,
                Score = candidate.Score,
                Direction = candidate.PendingDirection,
                DirectionStartedUtc = candidate.PendingDirectionUtc,
                IsActive = candidate.Active,
            };

        private static EvidenceBandView View(Band band)
            => new()
            {
                Id = band.Id,
                Role = band.Role,
                Side = band.Side,
                SourceSide = band.SourceSide,
                Source = band.Source,
                State = band.State,
                MinTick = band.MinTick,
                MaxTick = band.MaxTick,
                FormedUtc = band.FormedUtc,
                OwnedUtc = band.OwnedUtc,
                LastStateUtc = band.LastStateUtc,
                FailedUtc = band.FailedUtc,
                EventCount = band.EventCount,
                Score = band.Score,
            };

        private static EvidenceSide Opposite(EvidenceSide side)
            => side == EvidenceSide.Demand ? EvidenceSide.Supply : EvidenceSide.Demand;

        private long PriceToTick(double price)
            => (long)Math.Round(price / _tickSize);

        private static IEnumerable<DepthLevelSnapshot> ValidLevels(
            IReadOnlyList<DepthLevelSnapshot> levels)
            => (levels ?? Array.Empty<DepthLevelSnapshot>())
                .Where(l => l != null && double.IsFinite(l.Price) && l.Price > 0
                    && double.IsFinite(l.Size) && l.Size > 0);

        private static DateTime NormalizeUtc(DateTime value)
            => value.Kind switch
            {
                DateTimeKind.Utc => value,
                DateTimeKind.Local => value.ToUniversalTime(),
                _ => DateTime.SpecifyKind(value, DateTimeKind.Utc),
            };

        private sealed class BookSample
        {
            public DateTime TimeUtc;
            public long MidTick;
            public double BidInner;
            public double AskInner;
            public double BidCentroid;
            public double AskCentroid;
        }

        private sealed class BandEvent
        {
            public DateTime TimeUtc;
            public long PriceTick;
            public EvidenceSide Side;
            public double AbsZ;
            public string Type;
        }

        private sealed class Candidate
        {
            public int Id;
            public EvidenceSide Side;
            public long MinTick;
            public long MaxTick;
            public DateTime StartUtc;
            public DateTime FormedUtc;
            public DateTime LastUpdateUtc;
            public int EventCount;
            public double Score;
            public HashSet<string> Kinds = new();
            public bool Active = true;
            public CandidateDirection PendingDirection;
            public DateTime? PendingDirectionUtc;
        }

        private sealed class Band
        {
            public int Id;
            public EvidenceRole Role;
            public EvidenceSide Side;
            public EvidenceSide SourceSide;
            public EvidenceSource Source;
            public EvidenceState State;
            public long MinTick;
            public long MaxTick;
            public DateTime FormedUtc;
            public DateTime OwnedUtc;
            public DateTime LastUpdateUtc;
            public DateTime LastStateUtc;
            public DateTime? FailedUtc;
            public DateTime? PendingFailureUtc;
            public int EventCount;
            public double Score;
            public int DemandFailCount;
            public int SupplyFailCount;
            public long? GreyMinTick;
            public long? GreyMaxTick;
        }
    }
}
