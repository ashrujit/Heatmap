using System;
using System.Collections.Generic;

namespace L2_Heatmap
{
    public sealed class LiquidityHeatmapBuffer
    {
        public readonly struct BookSnapshot
        {
            public readonly DateTime T;
            public readonly long RefTick;
            public readonly Dictionary<long, double> BidsByTick;
            public readonly Dictionary<long, double> AsksByTick;

            public BookSnapshot(DateTime t, long refTick,
                Dictionary<long, double> bids, Dictionary<long, double> asks)
            {
                T = t; RefTick = refTick;
                BidsByTick = bids; AsksByTick = asks;
            }
        }

        public const int AdaptiveRecomputeIntervalSec = 60;
        // Floor for adaptive saturation so a sparse book can't push it absurdly low.
        public const double MinAdaptiveSaturation = 5.0;

        private readonly double _tickSize;
        private readonly int _retentionSec;
        private readonly int _snapshotIntervalMs;
        private readonly int _alphaMax;
        private readonly double _sizeFloor;
        private readonly double _levelsWindowPoints;
        // > 0 → use directly. = 0 → adaptive from buffer's own size distribution.
        private readonly double _sizeAtSaturationOverride;
        private readonly double _adaptivePercentile;

        private readonly Queue<BookSnapshot> _snapshots = new();
        private DateTime _lastSnapshotUtc = DateTime.MinValue;
        private DateTime _lastRecomputeUtc = DateTime.MinValue;
        private double _effectiveSaturation;

        public LiquidityHeatmapBuffer(
            double tickSize, int retentionSec, int snapshotIntervalMs,
            int alphaMax, double sizeFloor, double levelsWindowPoints,
            double sizeAtSaturationOverride, double adaptivePercentile)
        {
            _tickSize = tickSize > 0 ? tickSize : 0.25;
            _retentionSec = retentionSec > 0 ? retentionSec : 600;
            _snapshotIntervalMs = snapshotIntervalMs > 0 ? snapshotIntervalMs : 500;
            _alphaMax = alphaMax > 0 ? Math.Min(255, alphaMax) : 70;
            _sizeFloor = sizeFloor >= 0 ? sizeFloor : 1.0;
            _levelsWindowPoints = levelsWindowPoints > 0 ? levelsWindowPoints : 50.0;
            _sizeAtSaturationOverride = sizeAtSaturationOverride >= 0 ? sizeAtSaturationOverride : 0;
            _adaptivePercentile = adaptivePercentile > 0
                ? Math.Min(0.999, Math.Max(0.5, adaptivePercentile))
                : 0.99;
            _effectiveSaturation = _sizeAtSaturationOverride > 0
                ? _sizeAtSaturationOverride
                : 25.0; // sensible fallback until first adaptive recompute
        }

        public double TickSize => _tickSize;
        public int AlphaMax => _alphaMax;
        public double SizeFloor => _sizeFloor;
        public double LevelsWindowPoints => _levelsWindowPoints;
        public bool IsAdaptive => _sizeAtSaturationOverride <= 0;
        public double EffectiveSaturation => _effectiveSaturation;
        public IReadOnlyCollection<BookSnapshot> Snapshots => _snapshots;

        // NQ/ES (tick 0.25) at 50 points → 200 ticks each side.
        public int LevelsWindowTicks => (int)Math.Round(_levelsWindowPoints / _tickSize);

        // Throttled book-snapshot capture. Called from the L2 drain right after BookState.Apply.
        public void OnPostApply(BookState book, DateTime nowUtc)
        {
            if (book == null) return;
            if (_lastSnapshotUtc != DateTime.MinValue
                && (nowUtc - _lastSnapshotUtc).TotalMilliseconds < _snapshotIntervalMs) return;
            _lastSnapshotUtc = nowUtc;

            // Mid-of-book reference tick (or whichever side exists).
            long bestBid = long.MinValue, bestAsk = long.MaxValue;
            foreach (var kv in book.BidsByTick) { bestBid = kv.Key; break; }
            foreach (var kv in book.AsksByTick) { bestAsk = kv.Key; break; }
            long refTick;
            if (bestBid != long.MinValue && bestAsk != long.MaxValue) refTick = (bestBid + bestAsk) / 2;
            else if (bestBid != long.MinValue) refTick = bestBid;
            else if (bestAsk != long.MaxValue) refTick = bestAsk;
            else return;

            // Clone size-by-tick views so the snapshot is independent of further BookState mutation.
            var bids = new Dictionary<long, double>(book.BidsByTick.Count);
            foreach (var kv in book.BidsByTick) bids[kv.Key] = kv.Value.TotalSize;
            var asks = new Dictionary<long, double>(book.AsksByTick.Count);
            foreach (var kv in book.AsksByTick) asks[kv.Key] = kv.Value.TotalSize;

            _snapshots.Enqueue(new BookSnapshot(nowUtc, refTick, bids, asks));

            DateTime cutoff = nowUtc.AddSeconds(-_retentionSec);
            while (_snapshots.Count > 0 && _snapshots.Peek().T < cutoff)
                _snapshots.Dequeue();

            if (_lastRecomputeUtc == DateTime.MinValue)
            {
                _lastRecomputeUtc = nowUtc;
            }
            else if ((nowUtc - _lastRecomputeUtc).TotalSeconds >= AdaptiveRecomputeIntervalSec)
            {
                UpdateAdaptiveSaturation();
                _lastRecomputeUtc = nowUtc;
            }
        }

        public void Clear()
        {
            _snapshots.Clear();
            _lastSnapshotUtc = DateTime.MinValue;
            _lastRecomputeUtc = DateTime.MinValue;
            _effectiveSaturation = _sizeAtSaturationOverride > 0
                ? _sizeAtSaturationOverride
                : 25.0;
        }

        // Recompute adaptive saturation from the buffer's own size distribution at the
        // configured percentile. Filtered to cells that would actually paint (within
        // window, above floor). Floored at MinAdaptiveSaturation.
        private void UpdateAdaptiveSaturation()
        {
            if (_sizeAtSaturationOverride > 0)
            {
                _effectiveSaturation = _sizeAtSaturationOverride;
                return;
            }
            if (_snapshots.Count == 0) return;

            int windowTicks = LevelsWindowTicks;
            var sizes = new List<double>(_snapshots.Count * 200);

            foreach (var snap in _snapshots)
            {
                long refTick = snap.RefTick;
                foreach (var kv in snap.BidsByTick)
                {
                    if (kv.Value < _sizeFloor) continue;
                    if (Math.Abs(kv.Key - refTick) > windowTicks) continue;
                    sizes.Add(kv.Value);
                }
                foreach (var kv in snap.AsksByTick)
                {
                    if (kv.Value < _sizeFloor) continue;
                    if (Math.Abs(kv.Key - refTick) > windowTicks) continue;
                    sizes.Add(kv.Value);
                }
            }

            if (sizes.Count < 100) return; // not enough data to trust the percentile

            sizes.Sort();
            int idx = (int)Math.Floor(_adaptivePercentile * (sizes.Count - 1));
            if (idx < 0) idx = 0;
            if (idx >= sizes.Count) idx = sizes.Count - 1;
            _effectiveSaturation = Math.Max(MinAdaptiveSaturation, sizes[idx]);
        }
    }
}
