using System;
using System.Collections.Generic;
using System.Linq;
using TradingPlatform.BusinessLayer;

namespace LevelLedger
{
    internal sealed class LevelLedgerEngine
    {
        private const int InnerLevels = 10;
        private const int BroadLevels = 30;
        private const int EventRetentionSec = 20 * 60;
        private const int RowRetentionSec = 40 * 60;
        private const int NodeWindowSec = 5 * 60;
        private const int RowMergeSeconds = 75;
        private const int RowMergeTicks = 18;
        private const int SupersededKeepSeconds = 150;
        private const int DominanceWindowSec = 20 * 60;
        private const int DominanceHalfLifeSec = 8 * 60;
        private const int DominanceKernelTicks = 12;
        private const int DominanceZoneMergeTicks = 24;
        private const int DominanceCurrentRelevanceTicks = DominanceKernelTicks * 3;
        private const int DominanceFreshCauseSec = 90;
        private const int DominanceEvalCooldownSec = 20;
        private const int DominanceMaxZonesPerEval = 2;
        private const int SpatialRowUpdatePriceTicks = 8;
        private const int SpatialRowUpdateForceSeconds = 180;
        private const double SpatialRowUpdateRatioDelta = 0.7;
        private const double SpatialRowUpdateRatioRelative = 0.35;
        private const double DominanceMinDensity = 12.0;
        private const double MinDominanceRatio = 1.1;
        private const double ChaosSideDominanceRatio = 1.25;
        private const double OwnershipMinScore = 8.0;
        private const int OwnershipTestBufferTicks = 4;
        private const int OwnershipHoldConfirmTicks = 10;
        private const int OwnershipContestedSec = 20 * 60;
        private const int OwnershipContestedProximityTicks = 80;
        private const int OwnershipContestedSpanTicks = 240;
        private const int OwnershipContestedMinFails = 4;
        private const int OwnershipNoOwnerMinFails = 2;
        private const int OwnershipThesisBackingTicks = 260;
        private const int OwnershipThesisMinStack = 2;
        private const int VodStackClusterMergeSec = 75;
        private const int VodStackClusterMergeTicks = 36;
        private const int VodStackEdgeMergeTicks = 12;
        private const int VodStackMaxLinesPerSide = 4;
        private const int VodStackUnconfirmedKeepSec = 10 * 60;
        private const int RefillRowHalfWidthTicks = 8;
        private const int RefillBandPadTicks = 2;
        private const int RefillPreWindowSec = 20;
        private const int RefillImpactWindowSec = 5;
        private const int RefillPostStartSec = 5;
        private const int RefillPostEndSec = 24;
        private const int RefillSampleRetentionSec = RefillPreWindowSec + RefillPostEndSec + 5;
        private const int RefillProbeMaxAgeSec = RefillPostEndSec + 60;
        private const double RefillMinDepth = 18.0;
        private const double RefillPreDepthRatio = 0.75;
        private const double RefillMinRecoveryDepth = 8.0;
        private const double RefillRecoveryRatio = 0.25;
        private const double RefillOppSideRatio = 1.15;
        private const double RefillMissingDepth = 8.0;
        private const double RefillMissingRatio = 0.35;

        private int _bookLookbackSec;
        private double _eventZThreshold;
        private double _dominanceRatioThreshold;
        private int _activationLookbackMinutes;
        private int _tradeBarSec;
        private double _tradeVolZ;
        private double _tradeDeltaRatio;

        private readonly LinkedList<BookSample> _bookSamples = new();
        private readonly LinkedList<BookEvent> _bookEvents = new();
        private readonly LinkedList<VodBuildDot> _vodBuildDots = new();
        private readonly LinkedList<BuildBandOverlay> _buildBands = new();
        private readonly LinkedList<BuildBandEvent> _buildBandPending = new();
        private readonly List<BuildBandCandidate> _buildBandCandidates = new();
        private readonly LinkedList<VodStackOverlay> _vodStacks = new();
        private readonly LinkedList<TradeBar> _tradeBars = new();
        private readonly List<LedgerRow> _rows = new();
        private readonly List<RefillProbe> _refillProbes = new();

        private TradeBar _currentBar;
        private int _nextRowId = 1;
        private int _nextBuildBandId = 1;
        private int _nextVodStackId = 1;
        private VodStackOverlay _activeVodStack;
        private DateTime? _activeUtc;
        private long? _activationTick;
        private long? _lastNodeTick;
        private DateTime _lastNodeRowUtc = DateTime.MinValue;
        private DateTime _lastDominanceEvalUtc = DateTime.MinValue;

        private readonly LinkedList<TimedDouble> _innerDeltas = new();
        private readonly LinkedList<TimedDouble> _vodValues = new();
        private double? _prevInnerDepth;
        private double? _prevBidInner;
        private double? _prevAskInner;

        public LevelLedgerEngine(
            int bookLookbackSec,
            double eventZThreshold,
            double dominanceRatioThreshold,
            int activationLookbackMinutes,
            int tradeBarSec,
            double tradeVolZ,
            double tradeDeltaRatio)
        {
            UpdateConfig(
                bookLookbackSec,
                eventZThreshold,
                dominanceRatioThreshold,
                activationLookbackMinutes,
                tradeBarSec,
                tradeVolZ,
                tradeDeltaRatio);
        }

        public void UpdateConfig(
            int bookLookbackSec,
            double eventZThreshold,
            double dominanceRatioThreshold,
            int activationLookbackMinutes,
            int tradeBarSec,
            double tradeVolZ,
            double tradeDeltaRatio)
        {
            _bookLookbackSec = Math.Max(10, bookLookbackSec);
            _eventZThreshold = Math.Max(1.0, eventZThreshold);
            _dominanceRatioThreshold = Math.Max(MinDominanceRatio, dominanceRatioThreshold);
            _activationLookbackMinutes = Math.Max(1, activationLookbackMinutes);
            _tradeBarSec = Math.Max(1, tradeBarSec);
            _tradeVolZ = Math.Max(0.1, tradeVolZ);
            _tradeDeltaRatio = Math.Max(0.01, tradeDeltaRatio);
        }

        public bool IsActive => _activeUtc.HasValue;
        public double ChartVodBuildVodZ { get; set; } = 5.0;
        public double ChartVodBuildBuildZ { get; set; } = 4.0;
        public int ChartVodBuildRetentionMinutes { get; set; } = 0;
        public double ChartBuildBandBuildZ { get; set; } = 2.5;
        public int ChartBuildBandClusterN { get; set; } = 3;
        public int ChartBuildBandClusterTicks { get; set; } = 10;
        public int ChartBuildBandClusterSec { get; set; } = 90;
        public int ChartBuildBandConfirmMoveTicks { get; set; } = 8;
        public int ChartBuildBandConfirmSec { get; set; } = 10;
        public int ChartBuildBandPriceThroughBufferTicks { get; set; } = 2;
        public int ChartBuildBandFailureConfirmTicks { get; set; } = 24;
        public int ChartBuildBandFailureSec { get; set; } = 20;
        public int ChartBuildBandMaxRails { get; set; } = 12;
        public int ChartBuildBandRetentionMinutes { get; set; } = 0;
        public double ChartVodStackVodZ { get; set; } = 4.0;
        public double ChartVodStackEdgeZ { get; set; } = 2.5;
        public int ChartVodStackConfirmMoveTicks { get; set; } = 24;
        public int ChartVodStackPriceThroughBufferTicks { get; set; } = 2;
        public int ChartVodStackRetentionMinutes { get; set; } = 120;

        public void Activate(DateTime nowUtc)
        {
            _activeUtc = nowUtc;
            _activationTick = LastKnownTick;
            Prune(nowUtc);
        }

        public void Deactivate()
        {
            _activeUtc = null;
            _activationTick = null;
        }

        public void OnTrade(DateTime timeUtc, double price, double size, int aggressorSign, double tickSize)
        {
            if (!double.IsFinite(price) || price <= 0) return;
            if (!double.IsFinite(size) || size <= 0) return;
            long tick = PriceToTicks(price, tickSize);

            if (_currentBar == null)
                _currentBar = NewBar(AlignTime(timeUtc), tick);

            while (timeUtc >= _currentBar.StartUtc.AddSeconds(_tradeBarSec))
            {
                CloseTradeBar(_currentBar, tickSize);
                _currentBar = NewBar(_currentBar.StartUtc.AddSeconds(_tradeBarSec), tick);
            }

            _currentBar.LastTick = tick;
            _currentBar.HighTick = Math.Max(_currentBar.HighTick, tick);
            _currentBar.LowTick = Math.Min(_currentBar.LowTick, tick);
            _currentBar.Volume += size;
            _currentBar.Delta += aggressorSign * size;
            if (aggressorSign > 0) _currentBar.BuyVolume += size;
            else if (aggressorSign < 0) _currentBar.SellVolume += size;
            if (!_currentBar.Levels.TryGetValue(tick, out var pv))
                _currentBar.Levels[tick] = pv = new PriceVolume();
            pv.Volume += size;
            pv.Delta += aggressorSign * size;
            LastKnownTick = tick;
        }

        public void OnBookSample(DateTime nowUtc, DepthOfMarketAggregatedCollections dom, double tickSize)
        {
            if (_currentBar != null && nowUtc >= _currentBar.StartUtc.AddSeconds(_tradeBarSec))
            {
                CloseTradeBar(_currentBar, tickSize);
                _currentBar = null;
            }

            var sample = ComputeSample(nowUtc, dom, tickSize);
            LastKnownTick = sample.MidTick;
            _bookSamples.AddLast(sample);
            EvictOlderThan(_bookSamples, nowUtc, Math.Max(_bookLookbackSec * 2, RefillSampleRetentionSec));

            if (_bookSamples.Count < 5) return;

            var (mBi, sBi) = MeanStd(s => s.BidInner, nowUtc, _bookLookbackSec);
            var (mAi, sAi) = MeanStd(s => s.AskInner, nowUtc, _bookLookbackSec);
            var (mBc, sBc) = MeanStd(s => s.BidCentroid, nowUtc, _bookLookbackSec);
            var (mAc, sAc) = MeanStd(s => s.AskCentroid, nowUtc, _bookLookbackSec);

            double zBi = (sample.BidInner - mBi) / Math.Max(1.0, sBi);
            double zAi = (sample.AskInner - mAi) / Math.Max(1.0, sAi);
            double zBc = (sample.BidCentroid - mBc) / Math.Max(0.01, sBc);
            double zAc = (sample.AskCentroid - mAc) / Math.Max(0.01, sAc);

            TryFire(nowUtc, sample.MidTick, zBi, +1, "BID_BUILD", "BID_PULL");
            TryFire(nowUtc, sample.MidTick, zAi, -1, "ASK_BUILD", "ASK_PULL");
            TryFire(nowUtc, sample.MidTick, zBc, -1, "BID_OUT", "BID_IN");
            TryFire(nowUtc, sample.MidTick, zAc, +1, "ASK_OUT", "ASK_IN");

            UpdateBuildBandCandidates(nowUtc, sample.MidTick);
            UpdateBuildBandStates(nowUtc, sample.MidTick);
            UpdateVod(nowUtc, sample, zBi, zAi);
            UpdateVodStackEdges(nowUtc, sample.MidTick, zBi, zAi, zBc, zAc);
            ApplyVodStackPriceThrough(nowUtc, sample.MidTick);
            EvaluateSpatialDominance(nowUtc, sample.MidTick);
            ResolveRefillProbes(nowUtc);
            Prune(nowUtc);
        }

        public LedgerSnapshot GetSnapshot(int maxRows, DateTime nowUtc)
        {
            if (!_activeUtc.HasValue)
            {
                return new LedgerSnapshot
                {
                    IsActive = false,
                    Rows = Array.Empty<LedgerRow>(),
                    ActivatedUtc = null,
                    FocusTick = null,
                    LookbackMinutes = _activationLookbackMinutes,
                };
            }

            var start = _activeUtc.Value.AddMinutes(-_activationLookbackMinutes);
            var rows = _rows
                .Where(r => r.TimeUtc >= start)
                .Where(r => !r.Superseded || (nowUtc - r.SupersededUtc).TotalSeconds <= SupersededKeepSeconds)
                .OrderBy(r => r.TimeUtc)
                .ThenBy(r => r.Id)
                .TakeLast(Math.Max(1, maxRows))
                .Select(r => r.Clone())
                .ToArray();

            return new LedgerSnapshot
            {
                IsActive = true,
                Rows = rows,
                ActivatedUtc = _activeUtc,
                FocusTick = _activationTick,
                LookbackMinutes = _activationLookbackMinutes,
            };
        }

        public IReadOnlyList<VodBuildDot> GetVodBuildDots(DateTime nowUtc)
        {
            PruneVodBuildDots(nowUtc);
            return _vodBuildDots.Select(d => d.Clone()).ToArray();
        }

        public IReadOnlyList<BuildBandOverlay> GetBuildBands(DateTime nowUtc)
        {
            PruneBuildBands(nowUtc);
            long currentTick = LastKnownTick ?? 0;
            MarkThesisRails(currentTick);
            return SelectBuildBandsForDisplay(nowUtc, currentTick)
                .Select(b => b.Clone())
                .ToArray();
        }

        public IReadOnlyList<VodStackOverlay> GetVodStacks(DateTime nowUtc)
        {
            PruneVodStacks(nowUtc);
            return _vodStacks.Select(s => s.Clone()).ToArray();
        }

        private long? LastKnownTick { get; set; }

        private void CloseTradeBar(TradeBar bar, double tickSize)
        {
            if (bar == null || bar.Volume <= 0) return;
            bar.EndUtc = bar.StartUtc.AddSeconds(_tradeBarSec);
            _tradeBars.AddLast(bar);
            EvictOlderThan(_tradeBars, bar.EndUtc, EventRetentionSec);

            EvaluateTradeImpulse(bar, tickSize);
            EvaluateNode(bar.EndUtc);
        }

        private void EvaluateTradeImpulse(TradeBar bar, double tickSize)
        {
            var cutoff = bar.StartUtc.AddSeconds(-120);
            double sum = 0, sumSq = 0;
            int n = 0;
            foreach (var b in _tradeBars)
            {
                if (b == bar || b.StartUtc < cutoff) continue;
                sum += b.Volume;
                sumSq += b.Volume * b.Volume;
                n++;
            }
            if (n < 8 || bar.Volume < 50) return;

            double mean = sum / n;
            double var = sumSq / n - mean * mean;
            double std = var > 0 ? Math.Sqrt(var) : 0;
            double volZ = (bar.Volume - mean) / Math.Max(1.0, std);
            double ratio = Math.Abs(bar.Delta) / Math.Max(1.0, bar.Volume);
            if (volZ < _tradeVolZ || ratio < _tradeDeltaRatio) return;

            int direction = bar.Delta > 0 ? +1 : -1;
            string text = direction > 0 ? "buyers lift" : "sellers hit";
            AddOrUpdateRow(bar.EndUtc, bar.LastTick, direction, text, RowKind.TradeImpulse,
                volZ + ratio * 4.0,
                volZ);
        }

        private void EvaluateNode(DateTime nowUtc)
        {
            var cutoff = nowUtc.AddSeconds(-NodeWindowSec);
            var levels = new Dictionary<long, PriceVolume>();
            double total = 0;

            foreach (var bar in _tradeBars)
            {
                if (bar.EndUtc < cutoff) continue;
                foreach (var kv in bar.Levels)
                {
                    if (!levels.TryGetValue(kv.Key, out var pv))
                        levels[kv.Key] = pv = new PriceVolume();
                    pv.Volume += kv.Value.Volume;
                    pv.Delta += kv.Value.Delta;
                    total += kv.Value.Volume;
                }
            }

            if (total < 500 || levels.Count == 0) return;
            var poc = levels.OrderByDescending(kv => kv.Value.Volume).First();
            double clusterVol = 0;
            double clusterDelta = 0;
            for (long t = poc.Key - 2; t <= poc.Key + 2; t++)
            {
                if (levels.TryGetValue(t, out var pv))
                {
                    clusterVol += pv.Volume;
                    clusterDelta += pv.Delta;
                }
            }

            double concentration = clusterVol / Math.Max(1.0, total);
            if (concentration < 0.07) return;
            if ((nowUtc - _lastNodeRowUtc).TotalSeconds < 60
                && _lastNodeTick.HasValue
                && Math.Abs(poc.Key - _lastNodeTick.Value) <= 8)
                return;

            if (_lastNodeTick.HasValue && Math.Abs(poc.Key - _lastNodeTick.Value) >= 14)
            {
                int dir = poc.Key > _lastNodeTick.Value ? +1 : -1;
                string text = dir > 0 ? "accepts higher" : "accepts lower";
                AddOrUpdateRow(nowUtc, poc.Key, dir, text, RowKind.NodeMigration,
                    concentration * 20.0 + Math.Abs(clusterDelta) / Math.Max(1.0, clusterVol));
            }
            else
            {
                AddOrUpdateRow(nowUtc, poc.Key, 0, "node builds", RowKind.NodeBuild,
                    concentration * 20.0);
            }

            _lastNodeTick = poc.Key;
            _lastNodeRowUtc = nowUtc;
        }

        private void TryFire(DateTime timeUtc, long priceTick, double z, int biasPos, string posLabel, string negLabel)
        {
            double absZ = Math.Abs(z);
            int bias = z > 0 ? biasPos : -biasPos;
            string type = z > 0 ? posLabel : negLabel;
            if (absZ > Math.Max(1.0, ChartBuildBandBuildZ))
            {
                AddBuildBandEvent(new BuildBandEvent
                {
                    TimeUtc = timeUtc,
                    PriceTick = priceTick,
                    Side = bias > 0 ? BuildBandSide.Demand : BuildBandSide.Supply,
                    AbsZ = absZ,
                    Type = type,
                });
            }

            if (absZ <= _eventZThreshold) return;
            _bookEvents.AddLast(new BookEvent
            {
                TimeUtc = timeUtc,
                PriceTick = priceTick,
                Bias = bias,
                AbsZ = absZ,
                Type = type,
            });
        }

        private void AddBuildBandEvent(BuildBandEvent ev)
        {
            int clusterTicks = Math.Max(1, ChartBuildBandClusterTicks);
            int clusterSec = Math.Max(1, ChartBuildBandClusterSec);

            foreach (var candidate in _buildBandCandidates)
            {
                if (candidate.State != BuildBandCandidateState.Candidate) continue;
                if (candidate.Side != ev.Side) continue;
                if ((ev.TimeUtc - candidate.LastUpdateUtc).TotalSeconds > clusterSec) continue;

                long lo = candidate.MinTick - clusterTicks;
                long hi = candidate.MaxTick + clusterTicks;
                if (ev.PriceTick < lo || ev.PriceTick > hi) continue;

                if (ev.PriceTick < candidate.MinTick) candidate.MinTick = ev.PriceTick;
                if (ev.PriceTick > candidate.MaxTick) candidate.MaxTick = ev.PriceTick;
                candidate.LastUpdateUtc = ev.TimeUtc;
                candidate.EventCount++;
                candidate.Score += ev.AbsZ;
                candidate.MaxAbsZ = Math.Max(candidate.MaxAbsZ, ev.AbsZ);
                candidate.Kinds.Add(ev.Type);
                return;
            }

            var members = new List<BuildBandEvent> { ev };
            foreach (var pending in _buildBandPending)
            {
                if (pending.Side != ev.Side) continue;
                if (Math.Abs(pending.PriceTick - ev.PriceTick) > clusterTicks) continue;
                if ((ev.TimeUtc - pending.TimeUtc).TotalSeconds > clusterSec) continue;
                members.Add(pending);
            }

            int minEvents = Math.Max(2, ChartBuildBandClusterN);
            double score = members.Sum(m => m.AbsZ);
            if (members.Count >= minEvents && score >= OwnershipMinScore)
            {
                var candidate = new BuildBandCandidate
                {
                    Id = _nextBuildBandId++,
                    Side = ev.Side,
                    MinTick = members.Min(m => m.PriceTick),
                    MaxTick = members.Max(m => m.PriceTick),
                    StartUtc = members.Min(m => m.TimeUtc),
                    FormedUtc = ev.TimeUtc,
                    LastUpdateUtc = members.Max(m => m.TimeUtc),
                    EventCount = members.Count,
                    Score = score,
                    MaxAbsZ = members.Max(m => m.AbsZ),
                    Kinds = new HashSet<string>(members.Select(m => m.Type)),
                };
                _buildBandCandidates.Add(candidate);

                var node = _buildBandPending.First;
                while (node != null)
                {
                    var next = node.Next;
                    if (members.Contains(node.Value))
                        _buildBandPending.Remove(node);
                    node = next;
                }
            }
            else
            {
                _buildBandPending.AddLast(ev);
            }
        }

        private void UpdateBuildBandCandidates(DateTime nowUtc, long currentMidTick)
        {
            int confirmTicks = Math.Max(1, ChartBuildBandConfirmMoveTicks);
            foreach (var candidate in _buildBandCandidates)
            {
                if (candidate.State != BuildBandCandidateState.Candidate) continue;

                bool favor = MovedWithEvidence(candidate, currentMidTick, confirmTicks);
                bool adverse = MovedAgainstEvidence(candidate, currentMidTick, confirmTicks);
                if (favor)
                {
                    NoteOrConfirm(candidate, nowUtc, BuildBandConfirm.Favor, currentMidTick);
                }
                else if (adverse)
                {
                    NoteOrConfirm(candidate, nowUtc, BuildBandConfirm.Adverse, currentMidTick);
                }
                else
                {
                    candidate.PendingConfirm = BuildBandConfirm.None;
                    candidate.PendingConfirmUtc = null;
                }
            }
        }

        private void NoteOrConfirm(
            BuildBandCandidate candidate,
            DateTime nowUtc,
            BuildBandConfirm confirm,
            long currentMidTick)
        {
            if (candidate.PendingConfirm != confirm)
            {
                candidate.PendingConfirm = confirm;
                candidate.PendingConfirmUtc = nowUtc;
                return;
            }

            if (!candidate.PendingConfirmUtc.HasValue)
            {
                candidate.PendingConfirmUtc = nowUtc;
                return;
            }

            if ((nowUtc - candidate.PendingConfirmUtc.Value).TotalSeconds < Math.Max(0, ChartBuildBandConfirmSec))
                return;

            BuildBandSide side = confirm == BuildBandConfirm.Favor
                ? candidate.Side
                : Opposite(candidate.Side);
            BuildBandSource source = confirm == BuildBandConfirm.Favor
                ? BuildBandSource.Lean
                : BuildBandSource.Consumed;

            var band = new BuildBandOverlay
            {
                Id = candidate.Id,
                Role = BuildBandRole.Rail,
                Side = side,
                Source = source,
                State = BuildBandState.Owned,
                MinTick = candidate.MinTick,
                MaxTick = candidate.MaxTick,
                StartUtc = candidate.StartUtc,
                FormedUtc = candidate.FormedUtc,
                LastUpdateUtc = candidate.LastUpdateUtc,
                OwnedUtc = nowUtc,
                LastStateUtc = nowUtc,
                EventCount = candidate.EventCount,
                Score = candidate.Score,
                MaxAbsZ = candidate.MaxAbsZ,
                SourceSide = candidate.Side,
            };
            _buildBands.AddLast(band);
            MarkBandRefillPending(band, nowUtc);
            candidate.State = BuildBandCandidateState.Confirmed;
        }

        private static bool MovedWithEvidence(BuildBandCandidate candidate, long currentMidTick, int confirmTicks)
            => candidate.Side == BuildBandSide.Demand
                ? currentMidTick >= candidate.MaxTick + confirmTicks
                : currentMidTick <= candidate.MinTick - confirmTicks;

        private static bool MovedAgainstEvidence(BuildBandCandidate candidate, long currentMidTick, int confirmTicks)
            => candidate.Side == BuildBandSide.Demand
                ? currentMidTick <= candidate.MinTick - confirmTicks
                : currentMidTick >= candidate.MaxTick + confirmTicks;

        private static BuildBandSide Opposite(BuildBandSide side)
            => side == BuildBandSide.Demand ? BuildBandSide.Supply : BuildBandSide.Demand;

        private void UpdateBuildBandStates(DateTime nowUtc, long currentMidTick)
        {
            foreach (var band in _buildBands)
            {
                if (band.Role != BuildBandRole.Rail || band.State == BuildBandState.Failed)
                    continue;

                if (BuildBandFailCondition(band, currentMidTick))
                {
                    if (!band.PendingFailureUtc.HasValue)
                        band.PendingFailureUtc = nowUtc;

                    bool moveConfirmed = BuildBandFailMoveConfirmed(band, currentMidTick);
                    bool timeConfirmed = (nowUtc - band.PendingFailureUtc.Value).TotalSeconds
                        >= Math.Max(0, ChartBuildBandFailureSec);
                    if (moveConfirmed || timeConfirmed)
                    {
                        band.State = BuildBandState.Failed;
                        band.FailedUtc = nowUtc;
                        band.BreachedUtc = nowUtc;
                        band.BreachPriceTick = currentMidTick;
                        band.FailPriceTick = currentMidTick;
                        band.WasThesis = band.WasThesis || band.IsThesis;
                        band.LastStateUtc = nowUtc;
                        MarkBandRefillPending(band, nowUtc);
                        RecordNoOwnerZone(band, nowUtc);
                        RecordBuildBandFailure(band, nowUtc);
                    }
                    continue;
                }

                band.PendingFailureUtc = null;

                if (BuildBandTestCondition(band, currentMidTick))
                {
                    if (band.State != BuildBandState.Tested)
                    {
                        band.State = BuildBandState.Tested;
                        band.TestedUtc = nowUtc;
                        band.LastStateUtc = nowUtc;
                    }
                    continue;
                }

                if (band.State == BuildBandState.Tested && BuildBandHoldCondition(band, currentMidTick))
                {
                    band.State = BuildBandState.Owned;
                    band.HeldUtc = nowUtc;
                    band.LastStateUtc = nowUtc;
                }
            }
        }

        private bool BuildBandTestCondition(BuildBandOverlay band, long currentMidTick)
        {
            int failBuffer = Math.Max(0, ChartBuildBandPriceThroughBufferTicks);
            if (band.Side == BuildBandSide.Demand)
                return currentMidTick >= band.MinTick - failBuffer
                    && currentMidTick <= band.MaxTick + OwnershipTestBufferTicks;
            return currentMidTick >= band.MinTick - OwnershipTestBufferTicks
                && currentMidTick <= band.MaxTick + failBuffer;
        }

        private bool BuildBandFailCondition(BuildBandOverlay band, long currentMidTick)
        {
            int failBuffer = Math.Max(0, ChartBuildBandPriceThroughBufferTicks);
            return band.Side == BuildBandSide.Demand
                ? currentMidTick < band.MinTick - failBuffer
                : currentMidTick > band.MaxTick + failBuffer;
        }

        private bool BuildBandFailMoveConfirmed(BuildBandOverlay band, long currentMidTick)
        {
            int confirmTicks = Math.Max(1, ChartBuildBandFailureConfirmTicks);
            return band.Side == BuildBandSide.Demand
                ? currentMidTick <= band.MinTick - confirmTicks
                : currentMidTick >= band.MaxTick + confirmTicks;
        }

        private static bool BuildBandHoldCondition(BuildBandOverlay band, long currentMidTick)
            => band.Side == BuildBandSide.Demand
                ? currentMidTick >= band.MaxTick + OwnershipHoldConfirmTicks
                : currentMidTick <= band.MinTick - OwnershipHoldConfirmTicks;

        private void RecordBuildBandFailure(BuildBandOverlay failedBand, DateTime nowUtc)
            => RecordFailureZone(failedBand, nowUtc, BuildBandRole.Contested);

        private void RecordNoOwnerZone(BuildBandOverlay failedBand, DateTime nowUtc)
            => RecordFailureZone(failedBand, nowUtc, BuildBandRole.NoOwner);

        private void RecordFailureZone(BuildBandOverlay failedBand, DateTime nowUtc, BuildBandRole role)
        {
            BuildBandOverlay matched = null;
            foreach (var zone in _buildBands)
            {
                if (zone.Role != role)
                    continue;
                if ((nowUtc - zone.LastUpdateUtc).TotalSeconds > OwnershipContestedSec)
                    continue;
                if (failedBand.MaxTick < zone.MinTick - OwnershipContestedProximityTicks)
                    continue;
                if (failedBand.MinTick > zone.MaxTick + OwnershipContestedProximityTicks)
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
                matched = new BuildBandOverlay
                {
                    Id = _nextBuildBandId++,
                    Role = role,
                    State = role == BuildBandRole.NoOwner ? BuildBandState.NoOwner : BuildBandState.Contested,
                    Side = failedBand.Side,
                    MinTick = failedBand.MinTick,
                    MaxTick = failedBand.MaxTick,
                    StartUtc = nowUtc,
                    FormedUtc = nowUtc,
                    LastUpdateUtc = nowUtc,
                    OwnedUtc = nowUtc,
                    LastStateUtc = nowUtc,
                    Score = failedBand.Score,
                    EventCount = 1,
                    MaxAbsZ = failedBand.MaxAbsZ,
                };
                _buildBands.AddLast(matched);
            }
            else
            {
                matched.MinTick = Math.Min(matched.MinTick, failedBand.MinTick);
                matched.MaxTick = Math.Max(matched.MaxTick, failedBand.MaxTick);
                matched.LastUpdateUtc = nowUtc;
                matched.LastStateUtc = nowUtc;
                matched.Score += failedBand.Score;
                matched.EventCount++;
                matched.MaxAbsZ = Math.Max(matched.MaxAbsZ, failedBand.MaxAbsZ);
            }

            if (failedBand.Side == BuildBandSide.Demand)
                matched.DemandFailCount++;
            else
                matched.SupplyFailCount++;
        }

        private void UpdateVod(DateTime nowUtc, BookSample sample, double zBidInner, double zAskInner)
        {
            double curr = sample.BidInner + sample.AskInner;
            if (_prevInnerDepth.HasValue)
            {
                _innerDeltas.AddLast(new TimedDouble { TimeUtc = nowUtc, Value = curr - _prevInnerDepth.Value });
                EvictOlderThan(_innerDeltas, nowUtc, _bookLookbackSec * 2);
                if (_innerDeltas.Count >= 4)
                {
                    double vod = StdOver(_innerDeltas, nowUtc, _bookLookbackSec);
                    _vodValues.AddLast(new TimedDouble { TimeUtc = nowUtc, Value = vod });
                    EvictOlderThan(_vodValues, nowUtc, _bookLookbackSec * 8);
                    if (_vodValues.Count >= 8)
                    {
                        var (m, s) = MeanStdOf(_vodValues, nowUtc, _bookLookbackSec * 4);
                        double z = (vod - m) / Math.Max(0.1, s);
                        AddVodBuildDotIfNeeded(nowUtc, sample, z, zBidInner, zAskInner);
                        AddOrUpdateVodStackAnchor(nowUtc, sample, z);
                        if (Math.Abs(z) >= Math.Max(4.0, _eventZThreshold + 1.0))
                            AddOrUpdateRow(nowUtc, sample.MidTick, 0, "VOD chaos", RowKind.Chaos, Math.Abs(z), Math.Abs(z));
                    }
                }
            }
            _prevInnerDepth = curr;
            _prevBidInner = sample.BidInner;
            _prevAskInner = sample.AskInner;
        }

        private void AddVodBuildDotIfNeeded(DateTime nowUtc, BookSample sample, double vodZ, double zBidInner, double zAskInner)
        {
            if (vodZ < Math.Max(_eventZThreshold, ChartVodBuildVodZ)) return;

            double buildFloor = Math.Max(_eventZThreshold, ChartVodBuildBuildZ);
            double bidBuildZ = zBidInner >= buildFloor ? zBidInner : 0.0;
            double askBuildZ = zAskInner >= buildFloor ? zAskInner : 0.0;
            if (bidBuildZ <= 0 && askBuildZ <= 0) return;

            _vodBuildDots.AddLast(new VodBuildDot
            {
                TimeUtc = nowUtc,
                PriceTick = sample.MidTick,
                VodAbsZ = Math.Abs(vodZ),
                BidBuildZ = bidBuildZ,
                AskBuildZ = askBuildZ,
                ChaosSide = ResolveChaosSide(sample),
            });
        }

        private VodChaosSide ResolveChaosSide(BookSample sample)
        {
            if (!_prevBidInner.HasValue || !_prevAskInner.HasValue)
                return VodChaosSide.Mixed;

            double bidMove = Math.Abs(sample.BidInner - _prevBidInner.Value);
            double askMove = Math.Abs(sample.AskInner - _prevAskInner.Value);
            if (bidMove <= 0 && askMove <= 0)
                return VodChaosSide.Mixed;
            if (bidMove >= askMove * ChaosSideDominanceRatio)
                return VodChaosSide.Bid;
            if (askMove >= bidMove * ChaosSideDominanceRatio)
                return VodChaosSide.Ask;
            return VodChaosSide.Mixed;
        }

        private void AddOrUpdateVodStackAnchor(DateTime nowUtc, BookSample sample, double vodZ)
        {
            if (vodZ < Math.Max(1.0, ChartVodStackVodZ)) return;

            var side = ResolveChaosSide(sample);
            var stack = _activeVodStack;
            bool merge = stack != null
                && !stack.FadedUtc.HasValue
                && (nowUtc - stack.LastVodUtc).TotalSeconds <= VodStackClusterMergeSec
                && sample.MidTick >= stack.AnchorMinTick - VodStackClusterMergeTicks
                && sample.MidTick <= stack.AnchorMaxTick + VodStackClusterMergeTicks;

            if (!merge)
            {
                FadeOpenVodStacks(nowUtc);
                stack = new VodStackOverlay
                {
                    Id = _nextVodStackId++,
                    StartUtc = nowUtc,
                    LastVodUtc = nowUtc,
                    AnchorMinTick = sample.MidTick,
                    AnchorMaxTick = sample.MidTick,
                    CenterTick = sample.MidTick,
                    MaxVodAbsZ = Math.Abs(vodZ),
                    ChaosSide = side,
                    Edges = new List<VodStackEdge>(),
                };
                _vodStacks.AddLast(stack);
                _activeVodStack = stack;
                return;
            }

            stack.LastVodUtc = nowUtc;
            stack.AnchorMinTick = Math.Min(stack.AnchorMinTick, sample.MidTick);
            stack.AnchorMaxTick = Math.Max(stack.AnchorMaxTick, sample.MidTick);
            stack.CenterTick = (stack.AnchorMinTick + stack.AnchorMaxTick) / 2;
            stack.MaxVodAbsZ = Math.Max(stack.MaxVodAbsZ, Math.Abs(vodZ));
            stack.ChaosSide = MergeChaosSide(stack.ChaosSide, side);
        }

        private void FadeOpenVodStacks(DateTime nowUtc)
        {
            foreach (var stack in _vodStacks)
            {
                if (!stack.FadedUtc.HasValue)
                    stack.FadedUtc = nowUtc;
            }
        }

        private void UpdateVodStackEdges(
            DateTime nowUtc,
            long currentMidTick,
            double zBidInner,
            double zAskInner,
            double zBidCentroid,
            double zAskCentroid)
        {
            var stack = _activeVodStack;
            if (stack == null || stack.FadedUtc.HasValue) return;

            double threshold = Math.Max(1.0, ChartVodStackEdgeZ);
            if (zBidInner >= threshold)
                AddVodStackEdgeEvent(stack, nowUtc, currentMidTick, VodStackEdgeSide.Demand, zBidInner, "BID_BUILD");
            if (zAskInner >= threshold)
                AddVodStackEdgeEvent(stack, nowUtc, currentMidTick, VodStackEdgeSide.Supply, zAskInner, "ASK_BUILD");
            if (zBidCentroid >= threshold)
                AddVodStackEdgeEvent(stack, nowUtc, currentMidTick, VodStackEdgeSide.Supply, zBidCentroid, "BID_OUT");
            else if (zBidCentroid <= -threshold)
                AddVodStackEdgeEvent(stack, nowUtc, currentMidTick, VodStackEdgeSide.Demand, -zBidCentroid, "BID_IN");
            if (zAskCentroid >= threshold)
                AddVodStackEdgeEvent(stack, nowUtc, currentMidTick, VodStackEdgeSide.Demand, zAskCentroid, "ASK_OUT");
            else if (zAskCentroid <= -threshold)
                AddVodStackEdgeEvent(stack, nowUtc, currentMidTick, VodStackEdgeSide.Supply, -zAskCentroid, "ASK_IN");

            ConfirmVodStackEdges(stack, nowUtc, currentMidTick);
            PruneVodStackEdges(stack, nowUtc);
        }

        private void AddVodStackEdgeEvent(
            VodStackOverlay stack,
            DateTime nowUtc,
            long priceTick,
            VodStackEdgeSide side,
            double absZ,
            string eventType)
        {
            foreach (var edge in stack.Edges)
            {
                if (edge.Side != side) continue;
                if (edge.InvalidUtc.HasValue) continue;
                if (edge.BreachedUtc.HasValue) continue;
                if (Math.Abs(edge.CenterTick - priceTick) > VodStackEdgeMergeTicks) continue;

                edge.MinTick = Math.Min(edge.MinTick, priceTick);
                edge.MaxTick = Math.Max(edge.MaxTick, priceTick);
                edge.CenterTick = (edge.MinTick + edge.MaxTick) / 2;
                edge.LastUpdateUtc = nowUtc;
                edge.EventCount++;
                edge.MaxAbsZ = Math.Max(edge.MaxAbsZ, absZ);
                edge.EventType = eventType;
                return;
            }

            stack.Edges.Add(new VodStackEdge
            {
                Side = side,
                MinTick = priceTick,
                MaxTick = priceTick,
                CenterTick = priceTick,
                EventUtc = nowUtc,
                LastUpdateUtc = nowUtc,
                MaxAbsZ = absZ,
                EventCount = 1,
                EventType = eventType,
            });

            TrimVodStackLines(stack, side);
        }

        private void ConfirmVodStackEdges(VodStackOverlay stack, DateTime nowUtc, long currentMidTick)
        {
            int confirmTicks = Math.Max(1, ChartVodStackConfirmMoveTicks);
            foreach (var edge in stack.Edges)
            {
                if (edge.ConfirmedUtc.HasValue || edge.InvalidUtc.HasValue) continue;

                if (edge.Side == VodStackEdgeSide.Supply
                    && currentMidTick <= edge.MinTick - confirmTicks)
                {
                    edge.ConfirmedUtc = nowUtc;
                }
                else if (edge.Side == VodStackEdgeSide.Demand
                    && currentMidTick >= edge.MaxTick + confirmTicks)
                {
                    edge.ConfirmedUtc = nowUtc;
                }
            }
        }

        private void ApplyVodStackPriceThrough(DateTime nowUtc, long currentMidTick)
        {
            int bufferTicks = Math.Max(0, ChartVodStackPriceThroughBufferTicks);
            foreach (var stack in _vodStacks)
            {
                foreach (var edge in stack.Edges)
                {
                    if (edge.InvalidUtc.HasValue || edge.BreachedUtc.HasValue) continue;

                    bool throughSupply = edge.Side == VodStackEdgeSide.Supply
                        && currentMidTick > edge.MaxTick + bufferTicks;
                    bool throughDemand = edge.Side == VodStackEdgeSide.Demand
                        && currentMidTick < edge.MinTick - bufferTicks;

                    if (!throughSupply && !throughDemand) continue;

                    if (edge.ConfirmedUtc.HasValue)
                    {
                        edge.BreachedUtc = nowUtc;
                        edge.BreachPriceTick = currentMidTick;
                    }
                    else
                    {
                        edge.InvalidUtc = nowUtc;
                    }
                }
            }
        }

        private static void PruneVodStackEdges(VodStackOverlay stack, DateTime nowUtc)
        {
            for (int i = stack.Edges.Count - 1; i >= 0; i--)
            {
                var edge = stack.Edges[i];
                if (edge.InvalidUtc.HasValue)
                {
                    stack.Edges.RemoveAt(i);
                    continue;
                }

                if (!edge.ConfirmedUtc.HasValue
                    && (nowUtc - edge.LastUpdateUtc).TotalSeconds > VodStackUnconfirmedKeepSec)
                    stack.Edges.RemoveAt(i);
            }
        }

        private static void TrimVodStackLines(VodStackOverlay stack, VodStackEdgeSide side)
        {
            var sideLines = stack.Edges
                .Where(e => e.Side == side)
                .OrderBy(e => e.EventUtc)
                .ToList();

            while (sideLines.Count > VodStackMaxLinesPerSide)
            {
                var remove = sideLines[0];
                stack.Edges.Remove(remove);
                sideLines.RemoveAt(0);
            }
        }

        private static VodChaosSide MergeChaosSide(VodChaosSide existing, VodChaosSide next)
        {
            if (existing == VodChaosSide.Mixed || next == VodChaosSide.Mixed)
                return VodChaosSide.Mixed;
            return existing == next ? existing : VodChaosSide.Mixed;
        }

        private void EvaluateSpatialDominance(DateTime nowUtc, long currentMidTick)
        {
            if ((nowUtc - _lastDominanceEvalUtc).TotalSeconds < DominanceEvalCooldownSec)
                return;
            _lastDominanceEvalUtc = nowUtc;

            var cutoff = nowUtc.AddSeconds(-DominanceWindowSec);
            var centers = new HashSet<long>();
            foreach (var ev in _bookEvents)
            {
                if (ev.TimeUtc < cutoff) continue;
                long center = RoundToGrid(ev.PriceTick, 4);
                if (Math.Abs(center - currentMidTick) > DominanceCurrentRelevanceTicks) continue;
                centers.Add(center);
            }

            if (centers.Count == 0) return;

            var candidates = new List<DominanceCandidate>();
            foreach (long center in centers)
            {
                var candidate = ComputeDominance(nowUtc, center);
                if (candidate == null) continue;
                if (candidate.DominantDensity < DominanceMinDensity) continue;
                if (candidate.Ratio < _dominanceRatioThreshold) continue;
                if ((nowUtc - candidate.LatestDominantUtc).TotalSeconds > DominanceFreshCauseSec) continue;
                candidates.Add(candidate);
            }

            if (candidates.Count == 0) return;

            var accepted = new List<DominanceCandidate>();
            foreach (var candidate in candidates.OrderByDescending(c => c.DominantDensity))
            {
                bool overlaps = accepted.Any(a => Math.Abs(a.PriceTick - candidate.PriceTick) <= DominanceZoneMergeTicks);
                if (overlaps) continue;
                accepted.Add(candidate);
                if (accepted.Count >= DominanceMaxZonesPerEval) break;
            }

            foreach (var candidate in accepted.OrderBy(c => c.PriceTick))
            {
                string side = candidate.Direction > 0 ? "demand dom" : "supply dom";
                string text = $"{candidate.Ratio:0.#}x {side}";
                AddOrUpdateRow(nowUtc, candidate.PriceTick, candidate.Direction, text,
                    RowKind.SpatialDominance, candidate.DominantDensity, 0.0, candidate.Ratio);
            }
        }

        private DominanceCandidate ComputeDominance(DateTime nowUtc, long centerTick)
        {
            double demand = 0;
            double supply = 0;
            int count = 0;
            DateTime latestDemandUtc = DateTime.MinValue;
            DateTime latestSupplyUtc = DateTime.MinValue;
            var cutoff = nowUtc.AddSeconds(-DominanceWindowSec);

            foreach (var ev in _bookEvents)
            {
                if (ev.TimeUtc < cutoff || ev.TimeUtc > nowUtc) continue;
                long dist = Math.Abs(ev.PriceTick - centerTick);
                if (dist > DominanceKernelTicks * 3) continue;

                double ageSec = (nowUtc - ev.TimeUtc).TotalSeconds;
                double timeWeight = Math.Pow(0.5, ageSec / DominanceHalfLifeSec);
                double x = dist / (double)DominanceKernelTicks;
                double priceWeight = Math.Exp(-0.5 * x * x);
                double contribution = ev.AbsZ * timeWeight * priceWeight;

                if (ev.Bias > 0)
                {
                    demand += contribution;
                    if (ev.TimeUtc > latestDemandUtc) latestDemandUtc = ev.TimeUtc;
                }
                else
                {
                    supply += contribution;
                    if (ev.TimeUtc > latestSupplyUtc) latestSupplyUtc = ev.TimeUtc;
                }
                count++;
            }

            if (count == 0) return null;
            int direction = demand >= supply ? +1 : -1;
            double dominant = Math.Max(demand, supply);
            double opposing = Math.Min(demand, supply);
            double ratio = dominant / Math.Max(1.0, opposing);

            return new DominanceCandidate
            {
                PriceTick = centerTick,
                Direction = direction,
                Demand = demand,
                Supply = supply,
                EventCount = count,
                Ratio = ratio,
                DominantDensity = dominant,
                LatestDominantUtc = direction > 0 ? latestDemandUtc : latestSupplyUtc,
            };
        }

        private void AddOrUpdateRow(
            DateTime timeUtc,
            long priceTick,
            int direction,
            string text,
            RowKind kind,
            double strength,
            double displayZ = 0.0,
            double signalRatio = 0.0)
        {
            int mergeTicks = kind == RowKind.SpatialDominance ? DominanceZoneMergeTicks : RowMergeTicks;
            int mergeSeconds = kind == RowKind.SpatialDominance ? DominanceWindowSec : RowMergeSeconds;
            int supersedeSeconds = kind == RowKind.SpatialDominance ? DominanceWindowSec : SupersededKeepSeconds;

            for (int i = _rows.Count - 1; i >= 0; i--)
            {
                var r = _rows[i];
                if (r.Superseded) continue;
                if (r.Kind != kind) continue;
                if (r.Direction != direction) continue;
                if (Math.Abs(r.PriceTick - priceTick) > mergeTicks) continue;
                if ((timeUtc - r.TimeUtc).TotalSeconds > mergeSeconds) continue;

                if (kind == RowKind.SpatialDominance
                    && !ShouldUpdateSpatialRow(r, timeUtc, priceTick, text, signalRatio))
                {
                    r.Strength = Math.Max(r.Strength, strength);
                    r.DisplayZ = Math.Max(r.DisplayZ, displayZ);
                    return;
                }

                if (kind != RowKind.SpatialDominance)
                    r.TimeUtc = timeUtc;
                r.LastUpdateUtc = timeUtc;
                r.PriceTick = priceTick;
                r.Text = text;
                r.Strength = Math.Max(r.Strength, strength);
                r.DisplayZ = Math.Max(r.DisplayZ, displayZ);
                r.SignalRatio = signalRatio;
                r.Updates++;
                MarkRowRefillPending(r, timeUtc);
                return;
            }

            foreach (var r in _rows)
            {
                if (r.Superseded) continue;
                if (r.Direction == 0 || direction == 0) continue;
                if (r.Direction == direction) continue;
                if (Math.Abs(r.PriceTick - priceTick) <= mergeTicks
                    && (timeUtc - r.TimeUtc).TotalSeconds <= supersedeSeconds)
                {
                    r.Superseded = true;
                    r.SupersededUtc = timeUtc;
                }
            }

            var row = new LedgerRow
            {
                Id = _nextRowId++,
                TimeUtc = timeUtc,
                LastUpdateUtc = timeUtc,
                PriceTick = priceTick,
                Direction = direction,
                Text = text,
                Kind = kind,
                Strength = strength,
                DisplayZ = displayZ,
                SignalRatio = signalRatio,
                Updates = 1,
            };
            _rows.Add(row);
            MarkRowRefillPending(row, timeUtc);
        }

        private void MarkRowRefillPending(LedgerRow row, DateTime anchorUtc)
        {
            if (row.Kind != RowKind.SpatialDominance || row.Direction == 0)
                return;

            var side = row.Direction > 0 ? BuildBandSide.Demand : BuildBandSide.Supply;
            row.Refill = RefillState.Pending;
            row.RefillAnchorUtc = anchorUtc;
            row.RefillResolvedUtc = null;
            AddRefillProbe(new RefillProbe
            {
                Kind = RefillTargetKind.Row,
                TargetId = row.Id,
                AnchorUtc = anchorUtc,
                Side = side,
                MinTick = row.PriceTick - RefillRowHalfWidthTicks,
                MaxTick = row.PriceTick + RefillRowHalfWidthTicks,
            });
        }

        private void MarkBandRefillPending(BuildBandOverlay band, DateTime anchorUtc)
        {
            if (band.Role != BuildBandRole.Rail)
                return;

            band.Refill = RefillState.Pending;
            band.RefillAnchorUtc = anchorUtc;
            band.RefillResolvedUtc = null;
            AddRefillProbe(new RefillProbe
            {
                Kind = RefillTargetKind.BuildBand,
                TargetId = band.Id,
                AnchorUtc = anchorUtc,
                Side = band.Side,
                MinTick = band.MinTick - RefillBandPadTicks,
                MaxTick = band.MaxTick + RefillBandPadTicks,
            });
        }

        private void AddRefillProbe(RefillProbe probe)
        {
            _refillProbes.RemoveAll(p => p.Kind == probe.Kind && p.TargetId == probe.TargetId);
            _refillProbes.Add(probe);
        }

        private void ResolveRefillProbes(DateTime nowUtc)
        {
            for (int i = _refillProbes.Count - 1; i >= 0; i--)
            {
                var probe = _refillProbes[i];
                double ageSec = (nowUtc - probe.AnchorUtc).TotalSeconds;
                if (ageSec < RefillPostEndSec)
                    continue;

                var result = AssessRefill(probe);
                ApplyRefillResult(probe, result, nowUtc);
                _refillProbes.RemoveAt(i);
            }
        }

        private RefillState AssessRefill(RefillProbe probe)
        {
            var opposite = Opposite(probe.Side);

            double preSame = MedianDepth(probe.Side, probe.MinTick, probe.MaxTick,
                probe.AnchorUtc.AddSeconds(-RefillPreWindowSec), probe.AnchorUtc);
            double impactSame = MinDepth(probe.Side, probe.MinTick, probe.MaxTick,
                probe.AnchorUtc, probe.AnchorUtc.AddSeconds(RefillImpactWindowSec));
            double postSame = MaxDepth(probe.Side, probe.MinTick, probe.MaxTick,
                probe.AnchorUtc.AddSeconds(RefillPostStartSec), probe.AnchorUtc.AddSeconds(RefillPostEndSec));

            double preOpp = MedianDepth(opposite, probe.MinTick, probe.MaxTick,
                probe.AnchorUtc.AddSeconds(-RefillPreWindowSec), probe.AnchorUtc);
            double impactOpp = MinDepth(opposite, probe.MinTick, probe.MaxTick,
                probe.AnchorUtc, probe.AnchorUtc.AddSeconds(RefillImpactWindowSec));
            double postOpp = MaxDepth(opposite, probe.MinTick, probe.MaxTick,
                probe.AnchorUtc.AddSeconds(RefillPostStartSec), probe.AnchorUtc.AddSeconds(RefillPostEndSec));

            if (preSame <= 0 && postSame <= 0 && postOpp <= 0)
                return RefillState.None;

            double sameRecovery = postSame - impactSame;
            double oppRecovery = postOpp - impactOpp;
            bool sameStrong = postSame >= Math.Max(RefillMinDepth, preSame * RefillPreDepthRatio)
                && sameRecovery >= Math.Max(RefillMinRecoveryDepth, preSame * RefillRecoveryRatio)
                && postSame >= postOpp * RefillOppSideRatio;
            bool oppositeStrong = postOpp >= Math.Max(RefillMinDepth, preOpp * RefillPreDepthRatio)
                && oppRecovery >= Math.Max(RefillMinRecoveryDepth, preOpp * RefillRecoveryRatio)
                && postOpp >= postSame * RefillOppSideRatio;
            bool sameMissing = postSame < Math.Max(RefillMissingDepth, preSame * RefillMissingRatio);

            if (sameStrong)
                return RefillState.Confirmed;
            if (oppositeStrong || sameMissing)
                return RefillState.Conflict;
            return RefillState.None;
        }

        private void ApplyRefillResult(RefillProbe probe, RefillState result, DateTime nowUtc)
        {
            if (probe.Kind == RefillTargetKind.Row)
            {
                var row = _rows.FirstOrDefault(r => r.Id == probe.TargetId);
                if (row == null)
                    return;
                row.Refill = result;
                row.RefillResolvedUtc = result == RefillState.None ? null : nowUtc;
                return;
            }

            foreach (var band in _buildBands)
            {
                if (band.Id != probe.TargetId)
                    continue;
                band.Refill = result;
                band.RefillResolvedUtc = result == RefillState.None ? null : nowUtc;
                return;
            }
        }

        private double MedianDepth(BuildBandSide side, long minTick, long maxTick, DateTime startUtc, DateTime endUtc)
            => DepthWindow(side, minTick, maxTick, startUtc, endUtc, RefillDepthAgg.Median);

        private double MinDepth(BuildBandSide side, long minTick, long maxTick, DateTime startUtc, DateTime endUtc)
            => DepthWindow(side, minTick, maxTick, startUtc, endUtc, RefillDepthAgg.Min);

        private double MaxDepth(BuildBandSide side, long minTick, long maxTick, DateTime startUtc, DateTime endUtc)
            => DepthWindow(side, minTick, maxTick, startUtc, endUtc, RefillDepthAgg.Max);

        private double DepthWindow(
            BuildBandSide side,
            long minTick,
            long maxTick,
            DateTime startUtc,
            DateTime endUtc,
            RefillDepthAgg agg)
        {
            var values = new List<double>();
            foreach (var sample in _bookSamples)
            {
                if (sample.TimeUtc < startUtc || sample.TimeUtc > endUtc)
                    continue;
                values.Add(DepthInBand(sample, side, minTick, maxTick));
            }

            if (values.Count == 0)
                return 0.0;

            if (agg == RefillDepthAgg.Min)
                return values.Min();
            if (agg == RefillDepthAgg.Max)
                return values.Max();

            values.Sort();
            int mid = values.Count / 2;
            return values.Count % 2 == 1
                ? values[mid]
                : (values[mid - 1] + values[mid]) * 0.5;
        }

        private static double DepthInBand(BookSample sample, BuildBandSide side, long minTick, long maxTick)
        {
            var levels = side == BuildBandSide.Demand ? sample.Bids : sample.Asks;
            double total = 0.0;
            foreach (var level in levels)
            {
                if (level.Tick >= minTick && level.Tick <= maxTick)
                    total += level.Size;
            }
            return total;
        }

        private static bool ShouldUpdateSpatialRow(
            LedgerRow row,
            DateTime timeUtc,
            long priceTick,
            string text,
            double signalRatio)
        {
            if (Math.Abs(row.PriceTick - priceTick) >= SpatialRowUpdatePriceTicks)
                return true;

            if (row.SignalRatio > 0 && signalRatio > 0)
            {
                double ratioDelta = Math.Abs(signalRatio - row.SignalRatio);
                if (ratioDelta >= SpatialRowUpdateRatioDelta)
                    return true;
                if (ratioDelta / Math.Max(1.0, Math.Abs(row.SignalRatio)) >= SpatialRowUpdateRatioRelative)
                    return true;
            }

            DateTime reference = row.LastUpdateUtc == default ? row.TimeUtc : row.LastUpdateUtc;
            return text != row.Text
                && (timeUtc - reference).TotalSeconds >= SpatialRowUpdateForceSeconds;
        }

        private IEnumerable<BuildBandOverlay> SelectBuildBandsForDisplay(DateTime nowUtc, long currentTick)
        {
            int maxRails = Math.Max(1, ChartBuildBandMaxRails);
            var noOwnerZones = _buildBands
                .Where(IsVisibleNoOwnerZone)
                .OrderByDescending(z => z.LastUpdateUtc)
                .Take(4)
                .ToList();

            var contestedZones = _buildBands
                .Where(IsVisibleContestedZone)
                .Where(z => !noOwnerZones.Any(noOwner => CoversFailureEnvelope(noOwner, z)))
                .OrderByDescending(z => z.LastUpdateUtc)
                .Take(Math.Max(0, 4 - noOwnerZones.Count))
                .ToList();

            var zones = noOwnerZones.Concat(contestedZones);

            var activeRails = _buildBands
                .Where(b => b.Role == BuildBandRole.Rail && b.State != BuildBandState.Failed)
                .OrderByDescending(b => BuildBandRelevance(b, nowUtc, currentTick))
                .Take(maxRails);

            var failedRails = _buildBands
                .Where(b => b.Role == BuildBandRole.Rail
                    && b.State == BuildBandState.Failed
                    && !noOwnerZones.Any(zone => CoversFailureEnvelope(zone, b))
                    && b.FailedUtc.HasValue
                    && ((nowUtc - b.FailedUtc.Value).TotalMinutes <= 20.0 || b.WasThesis))
                .OrderByDescending(b => BuildBandRelevance(b, nowUtc, currentTick))
                .Take(6);

            return zones.Concat(activeRails).Concat(failedRails)
                .GroupBy(b => b.Id)
                .Select(g => g.First())
                .OrderBy(b => b.Role == BuildBandRole.NoOwner ? 0 : b.Role == BuildBandRole.Contested ? 1 : 2)
                .ThenBy(b => b.MinTick);
        }

        private static bool IsVisibleNoOwnerZone(BuildBandOverlay zone)
            => zone.Role == BuildBandRole.NoOwner
                && zone.EventCount >= OwnershipNoOwnerMinFails;

        private static bool IsVisibleContestedZone(BuildBandOverlay zone)
            => zone.Role == BuildBandRole.Contested
                && zone.DemandFailCount > 0
                && zone.SupplyFailCount > 0
                && zone.EventCount >= OwnershipContestedMinFails;

        private static bool CoversFailureEnvelope(BuildBandOverlay zone, BuildBandOverlay band)
            => band.MinTick >= zone.MinTick - OwnershipTestBufferTicks
                && band.MaxTick <= zone.MaxTick + OwnershipTestBufferTicks;

        private static double BuildBandRelevance(BuildBandOverlay band, DateTime nowUtc, long currentTick)
        {
            double center = (band.MinTick + band.MaxTick) / 2.0;
            double distance = Math.Abs(currentTick - center);
            double ageMin = Math.Max(0.0, (nowUtc - band.OwnedUtc).TotalMinutes);
            double stateBoost = band.State == BuildBandState.Tested ? 20.0 : 0.0;
            double thesisBoost = band.IsThesis ? 45.0 : (band.WasThesis ? 25.0 : 0.0);
            double failedPenalty = band.State == BuildBandState.Failed ? 20.0 : 0.0;
            double sourceBoost = band.Source == BuildBandSource.Consumed ? 5.0 : 0.0;
            return band.Score + stateBoost + thesisBoost + sourceBoost - failedPenalty - distance * 0.10 - ageMin * 0.05;
        }

        private void MarkThesisRails(long currentTick)
        {
            foreach (var band in _buildBands)
            {
                if (band.Role != BuildBandRole.Rail)
                    continue;
                band.WasThesis = band.WasThesis || band.IsThesis;
                band.IsThesis = false;
            }

            MarkThesisRailForSide(BuildBandSide.Demand, currentTick);
            MarkThesisRailForSide(BuildBandSide.Supply, currentTick);
        }

        private void MarkThesisRailForSide(BuildBandSide side, long currentTick)
        {
            var candidates = _buildBands
                .Where(b => b.Role == BuildBandRole.Rail
                    && b.Side == side
                    && b.State != BuildBandState.Failed
                    && IsRailOnCorrectSideOfPrice(b, currentTick))
                .OrderBy(b => Math.Abs(currentTick - ((b.MinTick + b.MaxTick) / 2.0)))
                .ThenByDescending(b => b.Score)
                .ToList();

            foreach (var candidate in candidates)
            {
                int backing = _buildBands.Count(b => b.Role == BuildBandRole.Rail
                    && b.Side == side
                    && b.State != BuildBandState.Failed
                    && b.Id != candidate.Id
                    && IsBackingRail(side, candidate, b));
                if (backing < OwnershipThesisMinStack - 1)
                    continue;

                candidate.IsThesis = true;
                candidate.WasThesis = true;
                return;
            }
        }

        private static bool IsRailOnCorrectSideOfPrice(BuildBandOverlay band, long currentTick)
            => band.Side == BuildBandSide.Demand
                ? currentTick >= band.MinTick - OwnershipTestBufferTicks
                : currentTick <= band.MaxTick + OwnershipTestBufferTicks;

        private static bool IsBackingRail(BuildBandSide side, BuildBandOverlay candidate, BuildBandOverlay other)
        {
            double candidateCenter = (candidate.MinTick + candidate.MaxTick) / 2.0;
            double otherCenter = (other.MinTick + other.MaxTick) / 2.0;
            if (Math.Abs(candidateCenter - otherCenter) > OwnershipThesisBackingTicks)
                return false;
            return side == BuildBandSide.Demand
                ? otherCenter < candidateCenter - OwnershipHoldConfirmTicks
                : otherCenter > candidateCenter + OwnershipHoldConfirmTicks;
        }

        private void Prune(DateTime nowUtc)
        {
            EvictOlderThan(_bookEvents, nowUtc, EventRetentionSec);
            EvictOlderThan(_tradeBars, nowUtc, EventRetentionSec);
            PruneVodBuildDots(nowUtc);
            PruneBuildBands(nowUtc);
            PruneBuildBandPending(nowUtc);
            PruneBuildBandCandidates(nowUtc);
            PruneVodStacks(nowUtc);
            PruneRefillProbes(nowUtc);
            var cutoff = nowUtc.AddSeconds(-RowRetentionSec);
            _rows.RemoveAll(r => r.TimeUtc < cutoff);
        }

        private void PruneRefillProbes(DateTime nowUtc)
        {
            _refillProbes.RemoveAll(p => (nowUtc - p.AnchorUtc).TotalSeconds > RefillProbeMaxAgeSec);
        }

        private void PruneVodBuildDots(DateTime nowUtc)
        {
            int minutes = Math.Max(0, ChartVodBuildRetentionMinutes);
            if (minutes == 0) return;
            EvictOlderThan(_vodBuildDots, nowUtc, minutes * 60);
        }

        private void PruneBuildBandPending(DateTime nowUtc)
        {
            int seconds = Math.Max(1, ChartBuildBandClusterSec);
            EvictOlderThan(_buildBandPending, nowUtc, seconds);
        }

        private void PruneBuildBandCandidates(DateTime nowUtc)
        {
            int seconds = Math.Max(1, ChartBuildBandClusterSec * 2);
            var cutoff = nowUtc.AddSeconds(-seconds);
            _buildBandCandidates.RemoveAll(c =>
                c.LastUpdateUtc < cutoff);
        }

        private void PruneBuildBands(DateTime nowUtc)
        {
            int minutes = Math.Max(0, ChartBuildBandRetentionMinutes);
            if (minutes == 0) return;

            var cutoff = nowUtc.AddMinutes(-minutes);
            var node = _buildBands.First;
            while (node != null)
            {
                var next = node.Next;
                var band = node.Value;
                DateTime reference = band.FailedUtc ?? band.LastUpdateUtc;
                if (reference < cutoff)
                    _buildBands.Remove(node);
                node = next;
            }
        }

        private void PruneVodStacks(DateTime nowUtc)
        {
            int minutes = Math.Max(0, ChartVodStackRetentionMinutes);
            if (minutes == 0) return;

            var cutoff = nowUtc.AddMinutes(-minutes);
            var node = _vodStacks.First;
            while (node != null)
            {
                var next = node.Next;
                var stack = node.Value;
                DateTime reference = stack.FadedUtc ?? stack.LastVodUtc;
                if (reference < cutoff)
                {
                    if (ReferenceEquals(_activeVodStack, stack))
                        _activeVodStack = null;
                    _vodStacks.Remove(node);
                }
                node = next;
            }
        }

        private BookSample ComputeSample(DateTime timeUtc, DepthOfMarketAggregatedCollections dom, double tickSize)
        {
            var s = new BookSample { TimeUtc = timeUtc };
            var bids = dom?.Bids ?? Array.Empty<Level2Item>();
            var asks = dom?.Asks ?? Array.Empty<Level2Item>();

            int taken = 0;
            for (int i = 0; i < bids.Length && taken < InnerLevels; i++)
            {
                double p = bids[i].Price;
                double sz = bids[i].Size;
                if (!double.IsFinite(p) || p <= 0 || !double.IsFinite(sz) || sz <= 0) continue;
                s.BidInner += sz;
                taken++;
            }

            taken = 0;
            for (int i = 0; i < asks.Length && taken < InnerLevels; i++)
            {
                double p = asks[i].Price;
                double sz = asks[i].Size;
                if (!double.IsFinite(p) || p <= 0 || !double.IsFinite(sz) || sz <= 0) continue;
                s.AskInner += sz;
                taken++;
            }

            double bb = FirstValidPrice(bids);
            double ba = FirstValidPrice(asks);
            long bestBid = double.IsFinite(bb) ? PriceToTicks(bb, tickSize) : 0;
            long bestAsk = double.IsFinite(ba) ? PriceToTicks(ba, tickSize) : 0;
            s.MidTick = double.IsFinite(bb) && double.IsFinite(ba)
                ? (bestBid + bestAsk) / 2
                : (double.IsFinite(bb) ? bestBid : bestAsk);

            double bWsum = 0, bSize = 0;
            taken = 0;
            for (int i = 0; i < bids.Length && taken < BroadLevels; i++)
            {
                double p = bids[i].Price;
                double sz = bids[i].Size;
                if (!double.IsFinite(p) || p <= 0 || !double.IsFinite(sz) || sz <= 0) continue;
                long t = PriceToTicks(p, tickSize);
                s.Bids.Add(new BookLevel { Tick = t, Size = sz });
                bWsum += Math.Abs(t - s.MidTick) * sz;
                bSize += sz;
                taken++;
            }

            double aWsum = 0, aSize = 0;
            taken = 0;
            for (int i = 0; i < asks.Length && taken < BroadLevels; i++)
            {
                double p = asks[i].Price;
                double sz = asks[i].Size;
                if (!double.IsFinite(p) || p <= 0 || !double.IsFinite(sz) || sz <= 0) continue;
                long t = PriceToTicks(p, tickSize);
                s.Asks.Add(new BookLevel { Tick = t, Size = sz });
                aWsum += Math.Abs(t - s.MidTick) * sz;
                aSize += sz;
                taken++;
            }

            s.BidCentroid = bSize > 0 ? bWsum / bSize : 0;
            s.AskCentroid = aSize > 0 ? aWsum / aSize : 0;
            return s;
        }

        private (double mean, double std) MeanStd(Func<BookSample, double> sel, DateTime nowUtc, int seconds)
        {
            var cutoff = nowUtc.AddSeconds(-seconds);
            double sum = 0, sumSq = 0;
            int n = 0;
            foreach (var s in _bookSamples)
            {
                if (s.TimeUtc < cutoff) continue;
                double v = sel(s);
                sum += v;
                sumSq += v * v;
                n++;
            }
            if (n < 2) return (0, 0);
            double mean = sum / n;
            double var = sumSq / n - mean * mean;
            return (mean, var > 0 ? Math.Sqrt(var) : 0);
        }

        private static double StdOver(LinkedList<TimedDouble> values, DateTime nowUtc, int seconds)
        {
            var cutoff = nowUtc.AddSeconds(-seconds);
            double sum = 0, sumSq = 0;
            int n = 0;
            foreach (var v in values)
            {
                if (v.TimeUtc < cutoff) continue;
                sum += v.Value;
                sumSq += v.Value * v.Value;
                n++;
            }
            if (n < 2) return 0;
            double mean = sum / n;
            double var = sumSq / n - mean * mean;
            return var > 0 ? Math.Sqrt(var) : 0;
        }

        private static (double mean, double std) MeanStdOf(LinkedList<TimedDouble> values, DateTime nowUtc, int seconds)
        {
            var cutoff = nowUtc.AddSeconds(-seconds);
            double sum = 0, sumSq = 0;
            int n = 0;
            foreach (var v in values)
            {
                if (v.TimeUtc < cutoff) continue;
                sum += v.Value;
                sumSq += v.Value * v.Value;
                n++;
            }
            if (n < 2) return (0, 0);
            double mean = sum / n;
            double var = sumSq / n - mean * mean;
            return (mean, var > 0 ? Math.Sqrt(var) : 0);
        }

        private static TradeBar NewBar(DateTime startUtc, long tick)
            => new()
            {
                StartUtc = startUtc,
                EndUtc = startUtc,
                FirstTick = tick,
                LastTick = tick,
                HighTick = tick,
                LowTick = tick,
            };

        private DateTime AlignTime(DateTime t)
        {
            long ticks = t.Ticks - (t.Ticks % TimeSpan.FromSeconds(_tradeBarSec).Ticks);
            return new DateTime(ticks, DateTimeKind.Utc);
        }

        private static long PriceToTicks(double price, double tickSize)
            => (long)Math.Round(price / tickSize);

        private static long RoundToGrid(long tick, int gridTicks)
            => (long)Math.Round(tick / (double)Math.Max(1, gridTicks)) * Math.Max(1, gridTicks);

        private static double FirstValidPrice(Level2Item[] arr)
        {
            if (arr == null) return double.NaN;
            for (int i = 0; i < arr.Length; i++)
            {
                double p = arr[i].Price;
                double s = arr[i].Size;
                if (double.IsFinite(p) && p > 0 && double.IsFinite(s) && s > 0) return p;
            }
            return double.NaN;
        }

        private static void EvictOlderThan<T>(LinkedList<T> list, DateTime nowUtc, int seconds)
            where T : ITimed
        {
            var cutoff = nowUtc.AddSeconds(-seconds);
            while (list.Count > 0 && list.First.Value.TimeUtc < cutoff)
                list.RemoveFirst();
        }

        internal interface ITimed
        {
            DateTime TimeUtc { get; }
        }

        private sealed class BookSample : ITimed
        {
            public DateTime TimeUtc { get; set; }
            public long MidTick;
            public double BidInner;
            public double AskInner;
            public double BidCentroid;
            public double AskCentroid;
            public List<BookLevel> Bids = new();
            public List<BookLevel> Asks = new();
        }

        private sealed class BookLevel
        {
            public long Tick;
            public double Size;
        }

        private sealed class BookEvent : ITimed
        {
            public DateTime TimeUtc { get; set; }
            public long PriceTick;
            public int Bias;
            public double AbsZ;
            public string Type;
        }

        private sealed class BuildBandEvent : ITimed
        {
            public DateTime TimeUtc { get; set; }
            public long PriceTick;
            public BuildBandSide Side;
            public double AbsZ;
            public string Type;
        }

        private sealed class BuildBandCandidate
        {
            public int Id;
            public BuildBandSide Side;
            public long MinTick;
            public long MaxTick;
            public DateTime StartUtc;
            public DateTime FormedUtc;
            public DateTime LastUpdateUtc;
            public int EventCount;
            public double Score;
            public double MaxAbsZ;
            public HashSet<string> Kinds = new();
            public BuildBandCandidateState State = BuildBandCandidateState.Candidate;
            public BuildBandConfirm PendingConfirm = BuildBandConfirm.None;
            public DateTime? PendingConfirmUtc;
        }

        private sealed class TimedDouble : ITimed
        {
            public DateTime TimeUtc { get; set; }
            public double Value;
        }

        private sealed class TradeBar : ITimed
        {
            public DateTime TimeUtc => EndUtc;
            public DateTime StartUtc;
            public DateTime EndUtc;
            public long FirstTick;
            public long LastTick;
            public long HighTick;
            public long LowTick;
            public double Volume;
            public double Delta;
            public double BuyVolume;
            public double SellVolume;
            public Dictionary<long, PriceVolume> Levels = new();
        }

        private sealed class PriceVolume
        {
            public double Volume;
            public double Delta;
        }

        private sealed class DominanceCandidate
        {
            public long PriceTick;
            public int Direction;
            public double Demand;
            public double Supply;
            public int EventCount;
            public double Ratio;
            public double DominantDensity;
            public DateTime LatestDominantUtc;
        }

        private sealed class RefillProbe
        {
            public RefillTargetKind Kind;
            public int TargetId;
            public DateTime AnchorUtc;
            public BuildBandSide Side;
            public long MinTick;
            public long MaxTick;
        }
    }

    internal enum RowKind
    {
        SpatialDominance,
        TradeImpulse,
        NodeBuild,
        NodeMigration,
        Chaos,
    }

    internal enum VodChaosSide
    {
        Mixed,
        Bid,
        Ask,
    }

    internal enum BuildBandSide
    {
        Demand,
        Supply,
    }

    internal enum BuildBandRole
    {
        Rail,
        Contested,
        NoOwner,
    }

    internal enum BuildBandSource
    {
        Lean,
        Consumed,
    }

    internal enum BuildBandState
    {
        Owned,
        Tested,
        Failed,
        Contested,
        NoOwner,
    }

    internal enum BuildBandCandidateState
    {
        Candidate,
        Confirmed,
    }

    internal enum BuildBandConfirm
    {
        None,
        Favor,
        Adverse,
    }

    internal enum RefillState
    {
        None,
        Pending,
        Confirmed,
        Conflict,
    }

    internal enum RefillTargetKind
    {
        Row,
        BuildBand,
    }

    internal enum RefillDepthAgg
    {
        Median,
        Min,
        Max,
    }

    internal enum VodStackEdgeSide
    {
        Demand,
        Supply,
    }

    internal sealed class VodBuildDot : LevelLedgerEngine.ITimed
    {
        public DateTime TimeUtc { get; set; }
        public long PriceTick;
        public double VodAbsZ;
        public double BidBuildZ;
        public double AskBuildZ;
        public VodChaosSide ChaosSide;

        public VodBuildDot Clone()
            => (VodBuildDot)MemberwiseClone();
    }

    internal sealed class BuildBandOverlay
    {
        public int Id;
        public BuildBandRole Role = BuildBandRole.Rail;
        public BuildBandSide Side;
        public BuildBandSide SourceSide;
        public BuildBandSource Source = BuildBandSource.Lean;
        public BuildBandState State = BuildBandState.Owned;
        public long MinTick;
        public long MaxTick;
        public DateTime StartUtc;
        public DateTime FormedUtc;
        public DateTime OwnedUtc;
        public DateTime LastUpdateUtc;
        public DateTime LastStateUtc;
        public int EventCount;
        public double Score;
        public double MaxAbsZ;
        public DateTime? BreachedUtc;
        public long? BreachPriceTick;
        public DateTime? TestedUtc;
        public DateTime? HeldUtc;
        public DateTime? FailedUtc;
        public long? FailPriceTick;
        public DateTime? PendingFailureUtc;
        public bool IsThesis;
        public bool WasThesis;
        public int DemandFailCount;
        public int SupplyFailCount;
        public RefillState Refill;
        public DateTime? RefillAnchorUtc;
        public DateTime? RefillResolvedUtc;

        public BuildBandOverlay Clone()
            => (BuildBandOverlay)MemberwiseClone();
    }

    internal sealed class VodStackOverlay
    {
        public int Id;
        public DateTime StartUtc;
        public DateTime LastVodUtc;
        public long AnchorMinTick;
        public long AnchorMaxTick;
        public long CenterTick;
        public double MaxVodAbsZ;
        public VodChaosSide ChaosSide;
        public DateTime? FadedUtc;
        public List<VodStackEdge> Edges = new();

        public VodStackOverlay Clone()
        {
            var copy = (VodStackOverlay)MemberwiseClone();
            copy.Edges = Edges.Select(e => e.Clone()).ToList();
            return copy;
        }
    }

    internal sealed class VodStackEdge
    {
        public VodStackEdgeSide Side;
        public long MinTick;
        public long MaxTick;
        public long CenterTick;
        public DateTime EventUtc;
        public DateTime LastUpdateUtc;
        public DateTime? ConfirmedUtc;
        public DateTime? BreachedUtc;
        public long? BreachPriceTick;
        public DateTime? InvalidUtc;
        public double MaxAbsZ;
        public int EventCount;
        public string EventType;

        public VodStackEdge Clone()
            => (VodStackEdge)MemberwiseClone();
    }

    internal sealed class LedgerRow
    {
        public int Id;
        public DateTime TimeUtc;
        public DateTime LastUpdateUtc;
        public long PriceTick;
        public int Direction;
        public string Text;
        public RowKind Kind;
        public double Strength;
        public double DisplayZ;
        public double SignalRatio;
        public bool Superseded;
        public DateTime SupersededUtc;
        public int Updates;
        public RefillState Refill;
        public DateTime? RefillAnchorUtc;
        public DateTime? RefillResolvedUtc;

        public LedgerRow Clone()
            => (LedgerRow)MemberwiseClone();
    }

    internal sealed class LedgerSnapshot
    {
        public bool IsActive;
        public DateTime? ActivatedUtc;
        public long? FocusTick;
        public int LookbackMinutes;
        public IReadOnlyList<LedgerRow> Rows;
    }
}
