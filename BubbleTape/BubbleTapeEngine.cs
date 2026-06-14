using System;
using System.Collections.Generic;
using System.Linq;

namespace BubbleTape
{
    internal readonly struct TradePrint
    {
        public readonly DateTime TimeUtc;
        public readonly double Price;
        public readonly double Size;
        public readonly int AggressorSign;

        public TradePrint(DateTime timeUtc, double price, double size, int aggressorSign)
        {
            TimeUtc = NormalizeUtc(timeUtc);
            Price = price;
            Size = size;
            AggressorSign = aggressorSign > 0 ? 1 : (aggressorSign < 0 ? -1 : 0);
        }

        private static DateTime NormalizeUtc(DateTime time)
        {
            if (time == default) return DateTime.UtcNow;
            if (time.Kind == DateTimeKind.Utc) return time;
            if (time.Kind == DateTimeKind.Local) return time.ToUniversalTime();
            return DateTime.SpecifyKind(time, DateTimeKind.Utc);
        }
    }

    internal sealed class BubbleTapeSettings
    {
        public int BarMinutes = 5;
        public int PriceBandTicks = 8;
        public int Detail = 1;
        public int LookbackHours = 24;
        public double MinCellVolume = 12.0;
        public double MinDeltaShare = 0.25;
        public double MinClusterDelta = 30.0;
        public int MaxClustersPerBarSide = 4;
        public bool ShowDeveloping = true;

        public BubbleTapeSettings Clone()
        {
            return (BubbleTapeSettings)MemberwiseClone();
        }
    }

    internal sealed class BubbleView
    {
        public DateTime TimeUtc;
        public long CenterTick;
        public long MinTick;
        public long MaxTick;
        public int Side;
        public double BuyVolume;
        public double SellVolume;
        public double Volume;
        public double Delta;
        public double AbsDelta;
        public double DeltaShare;
        public int Bins;
        public double Visual01;
        public bool Developing;
    }

    internal sealed class BubbleTapeSnapshot
    {
        public BubbleView[] Bubbles = Array.Empty<BubbleView>();
        public DateTime? LastTradeUtc;
        public long? LastTradeTick;
        public double Threshold;
        public double Cap;
        public int CandidateBars;
        public int CandidateClusters;
        public string Status = "starting";
    }

    internal sealed class BubbleTapeEngine
    {
        private readonly double _tickSize;
        private readonly TimeZoneInfo _nyZone;
        private readonly List<CandidateBar> _candidateBars = new();
        private readonly List<BubbleView> _bubbles = new();
        private BubbleTapeSettings _settings = new();
        private BarState _bar;
        private DateTime? _lastTradeUtc;
        private long? _lastTradeTick;
        private string _status = "waiting";
        private bool _suppressSelection;
        private double _lastThreshold;
        private double _lastCap;

        public BubbleTapeEngine(double tickSize)
        {
            _tickSize = tickSize > 0 ? tickSize : 0.25;
            try { _nyZone = TimeZoneInfo.FindSystemTimeZoneById("Eastern Standard Time"); }
            catch { _nyZone = TimeZoneInfo.Local; }
        }

        public void UpdateSettings(BubbleTapeSettings settings)
        {
            if (settings == null) return;
            var normalized = NormalizeSettings(settings);
            bool detectionChanged = DetectionSettingsChanged(_settings, normalized);
            _settings = normalized;
            if (detectionChanged)
                RebuildFrozenBubbles();
        }

        public void ResetAndWarm(IEnumerable<TradePrint> trades, DateTime warmupBoundaryUtc)
        {
            _candidateBars.Clear();
            _bubbles.Clear();
            _bar = null;
            _lastTradeUtc = null;
            _lastTradeTick = null;
            _lastThreshold = 0.0;
            _lastCap = 0.0;
            _suppressSelection = true;

            foreach (var trade in trades.OrderBy(t => t.TimeUtc))
                OnTrade(trade);

            Prune(warmupBoundaryUtc);
            RebuildFrozenBubbles();
            _suppressSelection = false;
            _status = $"warm { _candidateBars.Count } bars";
        }

        public void OnTrade(TradePrint trade)
        {
            if (!double.IsFinite(trade.Price) || trade.Price <= 0) return;
            if (!double.IsFinite(trade.Size) || trade.Size <= 0) return;

            DateTime utc = NormalizeUtc(trade.TimeUtc);
            long tick = PriceToTick(trade.Price);
            DateTime startUtc = BarStartUtc(utc);
            if (_bar == null)
            {
                _bar = new BarState(startUtc, tick);
            }
            else if (_bar.StartUtc != startUtc)
            {
                FinalizeBar(_bar, utc);
                _bar = new BarState(startUtc, tick);
            }

            _bar.HighTick = Math.Max(_bar.HighTick, tick);
            _bar.LowTick = Math.Min(_bar.LowTick, tick);
            _bar.CloseTick = tick;
            _bar.Volume += trade.Size;
            _bar.Delta += trade.Size * trade.AggressorSign;
            _bar.Trades++;

            long binTick = BinTick(tick);
            if (!_bar.Cells.TryGetValue(binTick, out var cell))
            {
                cell = new CellState(binTick);
                _bar.Cells[binTick] = cell;
            }
            cell.Add(tick, trade.Size, trade.AggressorSign);

            _lastTradeUtc = utc;
            _lastTradeTick = tick;
        }

        public BubbleTapeSnapshot GetSnapshot(DateTime nowUtc)
        {
            Prune(nowUtc);

            var rows = new List<BubbleView>(_bubbles.Count + 8);
            rows.AddRange(_bubbles);
            if (_settings.ShowDeveloping && _bar != null)
                rows.AddRange(BuildDevelopingBubbles());

            rows.Sort((a, b) =>
            {
                int cmp = a.TimeUtc.CompareTo(b.TimeUtc);
                if (cmp != 0) return cmp;
                cmp = a.CenterTick.CompareTo(b.CenterTick);
                if (cmp != 0) return cmp;
                return a.Side.CompareTo(b.Side);
            });

            return new BubbleTapeSnapshot
            {
                Bubbles = rows.ToArray(),
                LastTradeUtc = _lastTradeUtc,
                LastTradeTick = _lastTradeTick,
                Threshold = _lastThreshold,
                Cap = _lastCap,
                CandidateBars = _candidateBars.Count,
                CandidateClusters = _candidateBars.Sum(b => b.Clusters.Count),
                Status = _status,
            };
        }

        public void SetStatus(string status)
        {
            _status = status ?? "";
        }

        private void FinalizeBar(BarState bar, DateTime nowUtc)
        {
            var clusters = BuildClusters(bar).ToList();
            _candidateBars.Add(new CandidateBar
            {
                StartUtc = bar.StartUtc,
                DisplayUtc = bar.StartUtc.AddTicks(TimeSpan.FromMinutes(_settings.BarMinutes).Ticks / 2),
                Clusters = clusters,
            });
            Prune(nowUtc);
            if (!_suppressSelection)
                AddFrozenBubblesForBar(_candidateBars[_candidateBars.Count - 1]);
        }

        private IEnumerable<Cluster> BuildClusters(BarState bar)
        {
            var cells = bar.Cells.Values
                .Select(ToCellCandidate)
                .Where(c => c != null)
                .Cast<CellCandidate>()
                .OrderBy(c => c.Side)
                .ThenBy(c => c.BinTick)
                .ToList();

            Cluster current = null;
            long? lastBin = null;
            foreach (var cell in cells)
            {
                bool startsNew = current == null
                              || current.Side != cell.Side
                              || !lastBin.HasValue
                              || cell.BinTick > lastBin.Value + _settings.PriceBandTicks;
                if (startsNew)
                {
                    if (current != null)
                        yield return current;
                    current = new Cluster(cell);
                }
                else
                {
                    current.Add(cell);
                }
                lastBin = cell.BinTick;
            }
            if (current != null)
                yield return current;
        }

        private CellCandidate ToCellCandidate(CellState cell)
        {
            if (cell.Volume < _settings.MinCellVolume) return null;
            double delta = cell.BuyVolume - cell.SellVolume;
            double absDelta = Math.Abs(delta);
            if (absDelta <= 0.0) return null;
            double share = absDelta / Math.Max(1.0, cell.Volume);
            if (share < _settings.MinDeltaShare) return null;
            return new CellCandidate
            {
                BinTick = cell.BinTick,
                MinTick = cell.MinTick,
                MaxTick = cell.MaxTick,
                CenterTick = (cell.MinTick + cell.MaxTick) / 2.0,
                Side = delta > 0 ? 1 : -1,
                BuyVolume = cell.BuyVolume,
                SellVolume = cell.SellVolume,
                Volume = cell.Volume,
                Delta = delta,
                AbsDelta = absDelta,
                WeightedCenter = ((cell.MinTick + cell.MaxTick) / 2.0) * absDelta,
                WeightedAbs = absDelta,
                Bins = 1,
            };
        }

        private void AddFrozenBubblesForBar(CandidateBar bar)
        {
            var calibration = BuildCalibration();
            _lastThreshold = calibration.Threshold;
            _lastCap = calibration.Cap;
            foreach (var bubble in SelectClusters(bar.Clusters, calibration, includeBelowThreshold: false))
            {
                bubble.TimeUtc = bar.DisplayUtc;
                bubble.Developing = false;
                _bubbles.Add(bubble);
            }
        }

        private IReadOnlyList<BubbleView> BuildDevelopingBubbles()
        {
            var clusters = BuildClusters(_bar).ToList();
            var calibration = BuildCalibration(clusters);
            _lastThreshold = calibration.Threshold;
            _lastCap = calibration.Cap;
            var selected = SelectClusters(clusters, calibration, includeBelowThreshold: false);
            DateTime displayUtc = _bar.StartUtc.AddTicks(TimeSpan.FromMinutes(_settings.BarMinutes).Ticks / 2);
            foreach (var row in selected)
            {
                row.TimeUtc = displayUtc;
                row.Developing = true;
            }
            return selected;
        }

        private List<BubbleView> SelectClusters(
            IReadOnlyList<Cluster> clusters,
            CalibrationState calibration,
            bool includeBelowThreshold)
        {
            IEnumerable<Cluster> eligible = includeBelowThreshold
                ? clusters
                : clusters.Where(c => c.AbsDelta >= calibration.Threshold);

            var selected = eligible
                .GroupBy(c => c.Side)
                .SelectMany(g => g.OrderByDescending(c => c.AbsDelta).Take(_settings.MaxClustersPerBarSide))
                .OrderBy(c => c.CenterTick)
                .ToList();

            var rows = new List<BubbleView>(selected.Count);
            foreach (var c in selected)
            {
                rows.Add(new BubbleView
                {
                    CenterTick = (long)Math.Round(c.CenterTick),
                    MinTick = c.MinTick,
                    MaxTick = c.MaxTick,
                    Side = c.Side,
                    BuyVolume = c.BuyVolume,
                    SellVolume = c.SellVolume,
                    Volume = c.Volume,
                    Delta = c.Delta,
                    AbsDelta = c.AbsDelta,
                    DeltaShare = c.Volume > 0 ? Math.Abs(c.Delta) / c.Volume : 0.0,
                    Bins = c.Bins,
                    Visual01 = VisualStrength(c.AbsDelta, calibration),
                });
            }
            return rows;
        }

        private void RebuildFrozenBubbles()
        {
            _bubbles.Clear();
            var calibration = BuildCalibration();
            _lastThreshold = calibration.Threshold;
            _lastCap = calibration.Cap;
            foreach (var bar in _candidateBars)
            {
                foreach (var bubble in SelectClusters(bar.Clusters, calibration, includeBelowThreshold: false))
                {
                    bubble.TimeUtc = bar.DisplayUtc;
                    bubble.Developing = false;
                    _bubbles.Add(bubble);
                }
            }
        }

        private CalibrationState BuildCalibration(IReadOnlyList<Cluster> extraClusters = null)
        {
            var values = new List<double>();
            foreach (var bar in _candidateBars)
            {
                foreach (var cluster in bar.Clusters)
                    values.Add(cluster.AbsDelta);
            }
            if (extraClusters != null)
            {
                foreach (var cluster in extraClusters)
                    values.Add(cluster.AbsDelta);
            }

            double threshold = Math.Max(_settings.MinClusterDelta, Percentile(values, DetailPercentile()));
            double cap = Math.Max(threshold + 1.0, Percentile(values, 99.0));
            return new CalibrationState(threshold, cap);
        }

        private double DetailPercentile()
        {
            if (_settings.Detail <= 0) return 96.0;
            if (_settings.Detail >= 2) return 92.0;
            return 94.0;
        }

        private static double VisualStrength(double absDelta, CalibrationState calibration)
        {
            if (calibration.Cap <= calibration.Threshold)
                return 0.65;
            double norm = (absDelta - calibration.Threshold) / (calibration.Cap - calibration.Threshold);
            norm = Math.Max(0.0, Math.Min(1.0, norm));
            return Math.Sqrt(norm);
        }

        private void Prune(DateTime nowUtc)
        {
            DateTime cutoff = NormalizeUtc(nowUtc).AddHours(-Math.Max(1, _settings.LookbackHours));
            _candidateBars.RemoveAll(b => b.StartUtc < cutoff);
            _bubbles.RemoveAll(b => b.TimeUtc < cutoff);
        }

        private DateTime BarStartUtc(DateTime utc)
        {
            var local = TimeZoneInfo.ConvertTimeFromUtc(NormalizeUtc(utc), _nyZone);
            int minutes = Math.Max(1, _settings.BarMinutes);
            int m = (local.Minute / minutes) * minutes;
            var localStart = new DateTime(local.Year, local.Month, local.Day, local.Hour, m, 0);
            return TimeZoneInfo.ConvertTimeToUtc(localStart, _nyZone);
        }

        private long PriceToTick(double price)
        {
            return (long)Math.Round(price / _tickSize);
        }

        private long BinTick(long tick)
        {
            int width = Math.Max(1, _settings.PriceBandTicks);
            return (long)Math.Floor((double)tick / width) * width;
        }

        private static DateTime NormalizeUtc(DateTime time)
        {
            if (time == default) return DateTime.UtcNow;
            if (time.Kind == DateTimeKind.Utc) return time;
            if (time.Kind == DateTimeKind.Local) return time.ToUniversalTime();
            return DateTime.SpecifyKind(time, DateTimeKind.Utc);
        }

        private static BubbleTapeSettings NormalizeSettings(BubbleTapeSettings settings)
        {
            return new BubbleTapeSettings
            {
                BarMinutes = Clamp(settings.BarMinutes, 1, 60),
                PriceBandTicks = Clamp(settings.PriceBandTicks, 1, 400),
                Detail = Clamp(settings.Detail, 0, 2),
                LookbackHours = Clamp(settings.LookbackHours, 1, 168),
                MinCellVolume = Math.Max(0.0, settings.MinCellVolume),
                MinDeltaShare = Math.Max(0.01, Math.Min(0.99, settings.MinDeltaShare)),
                MinClusterDelta = Math.Max(0.0, settings.MinClusterDelta),
                MaxClustersPerBarSide = Clamp(settings.MaxClustersPerBarSide, 1, 20),
                ShowDeveloping = settings.ShowDeveloping,
            };
        }

        private static bool DetectionSettingsChanged(BubbleTapeSettings a, BubbleTapeSettings b)
        {
            if (a == null || b == null) return true;
            return a.BarMinutes != b.BarMinutes
                || a.PriceBandTicks != b.PriceBandTicks
                || a.Detail != b.Detail
                || a.LookbackHours != b.LookbackHours
                || Math.Abs(a.MinCellVolume - b.MinCellVolume) > 0.0001
                || Math.Abs(a.MinDeltaShare - b.MinDeltaShare) > 0.0001
                || Math.Abs(a.MinClusterDelta - b.MinClusterDelta) > 0.0001
                || a.MaxClustersPerBarSide != b.MaxClustersPerBarSide;
        }

        private static int Clamp(int value, int min, int max)
        {
            if (value < min) return min;
            if (value > max) return max;
            return value;
        }

        private static double Percentile(List<double> values, double percentile)
        {
            if (values == null || values.Count == 0) return 0.0;
            values.Sort();
            int index = (int)Math.Ceiling((percentile / 100.0) * values.Count) - 1;
            index = Math.Max(0, Math.Min(values.Count - 1, index));
            return values[index];
        }

        private readonly struct CalibrationState
        {
            public readonly double Threshold;
            public readonly double Cap;

            public CalibrationState(double threshold, double cap)
            {
                Threshold = threshold;
                Cap = cap;
            }
        }

        private sealed class BarState
        {
            public readonly DateTime StartUtc;
            public long OpenTick;
            public long HighTick;
            public long LowTick;
            public long CloseTick;
            public double Volume;
            public double Delta;
            public int Trades;
            public readonly Dictionary<long, CellState> Cells = new();

            public BarState(DateTime startUtc, long openTick)
            {
                StartUtc = startUtc;
                OpenTick = openTick;
                HighTick = openTick;
                LowTick = openTick;
                CloseTick = openTick;
            }
        }

        private sealed class CellState
        {
            public readonly long BinTick;
            public long MinTick = long.MaxValue;
            public long MaxTick = long.MinValue;
            public double BuyVolume;
            public double SellVolume;
            public double Volume;
            public int Trades;

            public CellState(long binTick)
            {
                BinTick = binTick;
            }

            public void Add(long tick, double size, int sign)
            {
                MinTick = Math.Min(MinTick, tick);
                MaxTick = Math.Max(MaxTick, tick);
                Volume += size;
                if (sign > 0) BuyVolume += size;
                else if (sign < 0) SellVolume += size;
                Trades++;
            }
        }

        private sealed class CandidateBar
        {
            public DateTime StartUtc;
            public DateTime DisplayUtc;
            public List<Cluster> Clusters = new();
        }

        private sealed class CellCandidate
        {
            public long BinTick;
            public long MinTick;
            public long MaxTick;
            public double CenterTick;
            public int Side;
            public double BuyVolume;
            public double SellVolume;
            public double Volume;
            public double Delta;
            public double AbsDelta;
            public double WeightedCenter;
            public double WeightedAbs;
            public int Bins;
        }

        private sealed class Cluster
        {
            public long MinTick;
            public long MaxTick;
            public double CenterTick;
            public int Side;
            public double BuyVolume;
            public double SellVolume;
            public double Volume;
            public double Delta;
            public double AbsDelta;
            public double WeightedCenter;
            public double WeightedAbs;
            public int Bins;

            public Cluster(CellCandidate cell)
            {
                MinTick = cell.MinTick;
                MaxTick = cell.MaxTick;
                CenterTick = cell.CenterTick;
                Side = cell.Side;
                BuyVolume = cell.BuyVolume;
                SellVolume = cell.SellVolume;
                Volume = cell.Volume;
                Delta = cell.Delta;
                AbsDelta = Math.Abs(cell.Delta);
                WeightedCenter = cell.WeightedCenter;
                WeightedAbs = cell.WeightedAbs;
                Bins = cell.Bins;
            }

            public void Add(CellCandidate cell)
            {
                MinTick = Math.Min(MinTick, cell.MinTick);
                MaxTick = Math.Max(MaxTick, cell.MaxTick);
                BuyVolume += cell.BuyVolume;
                SellVolume += cell.SellVolume;
                Volume += cell.Volume;
                Delta += cell.Delta;
                AbsDelta = Math.Abs(Delta);
                WeightedCenter += cell.WeightedCenter;
                WeightedAbs += cell.WeightedAbs;
                Bins += cell.Bins;
                CenterTick = WeightedAbs > 0
                    ? WeightedCenter / WeightedAbs
                    : (MinTick + MaxTick) / 2.0;
            }
        }
    }
}
