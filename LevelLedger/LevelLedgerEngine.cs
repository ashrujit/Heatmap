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
        private const double DominanceMinDensity = 12.0;
        private const double MinDominanceRatio = 1.1;
        private const double ChaosSideDominanceRatio = 1.25;

        private readonly int _bookLookbackSec;
        private readonly double _eventZThreshold;
        private readonly double _dominanceRatioThreshold;
        private readonly int _activationLookbackMinutes;
        private readonly int _tradeBarSec;
        private readonly double _tradeVolZ;
        private readonly double _tradeDeltaRatio;

        private readonly LinkedList<BookSample> _bookSamples = new();
        private readonly LinkedList<BookEvent> _bookEvents = new();
        private readonly LinkedList<VodBuildDot> _vodBuildDots = new();
        private readonly LinkedList<BuildBandOverlay> _buildBands = new();
        private readonly LinkedList<BuildBandEvent> _buildBandPending = new();
        private readonly LinkedList<TradeBar> _tradeBars = new();
        private readonly List<LedgerRow> _rows = new();

        private TradeBar _currentBar;
        private int _nextRowId = 1;
        private int _nextBuildBandId = 1;
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
        public double ChartBuildBandBuildZ { get; set; } = 3.0;
        public int ChartBuildBandClusterN { get; set; } = 3;
        public int ChartBuildBandClusterTicks { get; set; } = 8;
        public int ChartBuildBandClusterSec { get; set; } = 90;
        public int ChartBuildBandPriceThroughBufferTicks { get; set; } = 1;
        public int ChartBuildBandRetentionMinutes { get; set; } = 0;

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
            EvictOlderThan(_bookSamples, nowUtc, _bookLookbackSec * 2);

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

            UpdateBuildBands(nowUtc, sample.MidTick, zBi, zAi);
            ApplyBuildBandPriceThrough(nowUtc, sample.MidTick);
            UpdateVod(nowUtc, sample, zBi, zAi);
            EvaluateSpatialDominance(nowUtc, sample.MidTick);
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
            return _buildBands.Select(b => b.Clone()).ToArray();
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
            if (Math.Abs(z) <= _eventZThreshold) return;
            int bias = z > 0 ? biasPos : -biasPos;
            _bookEvents.AddLast(new BookEvent
            {
                TimeUtc = timeUtc,
                PriceTick = priceTick,
                Bias = bias,
                AbsZ = Math.Abs(z),
                Type = z > 0 ? posLabel : negLabel,
            });
        }

        private void UpdateBuildBands(DateTime nowUtc, long priceTick, double zBidInner, double zAskInner)
        {
            PruneBuildBandPending(nowUtc);

            double threshold = Math.Max(1.0, ChartBuildBandBuildZ);
            if (zBidInner > threshold)
            {
                AddBuildBandEvent(new BuildBandEvent
                {
                    TimeUtc = nowUtc,
                    PriceTick = priceTick,
                    Side = BuildBandSide.Demand,
                    AbsZ = zBidInner,
                });
            }

            if (zAskInner > threshold)
            {
                AddBuildBandEvent(new BuildBandEvent
                {
                    TimeUtc = nowUtc,
                    PriceTick = priceTick,
                    Side = BuildBandSide.Supply,
                    AbsZ = zAskInner,
                });
            }
        }

        private void AddBuildBandEvent(BuildBandEvent ev)
        {
            int clusterTicks = Math.Max(1, ChartBuildBandClusterTicks);
            int clusterSec = Math.Max(1, ChartBuildBandClusterSec);

            foreach (var band in _buildBands)
            {
                if (band.BreachedUtc.HasValue) continue;
                if (band.Side != ev.Side) continue;
                if ((ev.TimeUtc - band.LastUpdateUtc).TotalSeconds > clusterSec) continue;

                long lo = band.MinTick - clusterTicks;
                long hi = band.MaxTick + clusterTicks;
                if (ev.PriceTick < lo || ev.PriceTick > hi) continue;

                if (ev.PriceTick < band.MinTick) band.MinTick = ev.PriceTick;
                if (ev.PriceTick > band.MaxTick) band.MaxTick = ev.PriceTick;
                band.LastUpdateUtc = ev.TimeUtc;
                band.EventCount++;
                band.MaxAbsZ = Math.Max(band.MaxAbsZ, ev.AbsZ);
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
            if (members.Count >= minEvents)
            {
                var band = new BuildBandOverlay
                {
                    Id = _nextBuildBandId++,
                    Side = ev.Side,
                    MinTick = members.Min(m => m.PriceTick),
                    MaxTick = members.Max(m => m.PriceTick),
                    StartUtc = members.Min(m => m.TimeUtc),
                    FormedUtc = ev.TimeUtc,
                    LastUpdateUtc = members.Max(m => m.TimeUtc),
                    EventCount = members.Count,
                    MaxAbsZ = members.Max(m => m.AbsZ),
                };
                _buildBands.AddLast(band);

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

        private void ApplyBuildBandPriceThrough(DateTime nowUtc, long currentMidTick)
        {
            int bufferTicks = Math.Max(0, ChartBuildBandPriceThroughBufferTicks);
            foreach (var band in _buildBands)
            {
                if (band.BreachedUtc.HasValue) continue;

                if (band.Side == BuildBandSide.Supply && currentMidTick > band.MaxTick + bufferTicks)
                {
                    band.BreachedUtc = nowUtc;
                    band.BreachPriceTick = currentMidTick;
                }
                else if (band.Side == BuildBandSide.Demand && currentMidTick < band.MinTick - bufferTicks)
                {
                    band.BreachedUtc = nowUtc;
                    band.BreachPriceTick = currentMidTick;
                }
            }
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
                    RowKind.SpatialDominance, candidate.DominantDensity);
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

        private void AddOrUpdateRow(DateTime timeUtc, long priceTick, int direction, string text, RowKind kind, double strength, double displayZ = 0.0)
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

                if (kind != RowKind.SpatialDominance)
                    r.TimeUtc = timeUtc;
                r.PriceTick = priceTick;
                r.Text = text;
                r.Strength = Math.Max(r.Strength, strength);
                r.DisplayZ = Math.Max(r.DisplayZ, displayZ);
                r.Updates++;
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

            _rows.Add(new LedgerRow
            {
                Id = _nextRowId++,
                TimeUtc = timeUtc,
                PriceTick = priceTick,
                Direction = direction,
                Text = text,
                Kind = kind,
                Strength = strength,
                DisplayZ = displayZ,
                Updates = 1,
            });
        }

        private void Prune(DateTime nowUtc)
        {
            EvictOlderThan(_bookEvents, nowUtc, EventRetentionSec);
            EvictOlderThan(_tradeBars, nowUtc, EventRetentionSec);
            PruneVodBuildDots(nowUtc);
            PruneBuildBands(nowUtc);
            PruneBuildBandPending(nowUtc);
            var cutoff = nowUtc.AddSeconds(-RowRetentionSec);
            _rows.RemoveAll(r => r.TimeUtc < cutoff);
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
                DateTime reference = band.BreachedUtc ?? band.LastUpdateUtc;
                if (reference < cutoff)
                    _buildBands.Remove(node);
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
        public BuildBandSide Side;
        public long MinTick;
        public long MaxTick;
        public DateTime StartUtc;
        public DateTime FormedUtc;
        public DateTime LastUpdateUtc;
        public int EventCount;
        public double MaxAbsZ;
        public DateTime? BreachedUtc;
        public long? BreachPriceTick;

        public BuildBandOverlay Clone()
            => (BuildBandOverlay)MemberwiseClone();
    }

    internal sealed class LedgerRow
    {
        public int Id;
        public DateTime TimeUtc;
        public long PriceTick;
        public int Direction;
        public string Text;
        public RowKind Kind;
        public double Strength;
        public double DisplayZ;
        public bool Superseded;
        public DateTime SupersededUtc;
        public int Updates;

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
