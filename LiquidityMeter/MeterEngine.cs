using System;
using System.Collections.Generic;
using TradingPlatform.BusinessLayer;

namespace LiquidityMeter
{
    // Live port of research/liq_events.py side-aware event detection +
    // cum/ROC tracking. Samples the live BookState at fixed cadence,
    // computes inner depth and centroid distance per side, z-scores against
    // rolling baseline, fires directionally-tagged events. Maintains:
    //   - Cumulative since anchor (slow indicator — "where is the lean")
    //   - Rate-of-change over rolling window (fast indicator — "what's pressure now")
    //
    // Same posture as A/E: surfaces structure, doesn't predict. The trader
    // reads cum + ROC alongside their existing chart context.
    internal sealed class MeterEngine
    {
        // Top-N levels per side. Inner = closest 10 (tight depth signal).
        // Broad = closest 30 (used for centroid distance computation).
        private const int InnerLevels = 10;
        private const int BroadLevels = 30;

        private readonly int _lookbackSec;
        private readonly int _rocWindowSec;
        private readonly double _zThreshold;
        private readonly double _stdFloor = 1.0;
        private readonly double _centStdFloor = 0.01;

        private readonly LinkedList<Sample> _samples = new();
        private readonly LinkedList<MeterEvent> _events = new();
        private DateTime _anchorUtc;
        public TimeSpan? RollingAnchorWindow;  // if set, anchor = now - window

        public MeterEngine(int lookbackSec, double zThreshold, int rocWindowSec)
        {
            _lookbackSec = lookbackSec;
            _zThreshold = zThreshold;
            _rocWindowSec = rocWindowSec;
            _anchorUtc = DateTime.UtcNow;
        }

        public double Cumulative { get; private set; }
        public double RateOfChange { get; private set; }
        public int EventCount => _events.Count;
        public DateTime AnchorUtc => _anchorUtc;
        // VOL_OF_DEPTH chaos signal (neutral bias — does NOT contribute to cum/ROC).
        // Painter uses LastVodTime + VodCount30s for a flicker indicator.
        public DateTime LastVodTime { get; private set; } = DateTime.MinValue;
        public int VodCount30s { get; private set; }
        public double LastVodZ { get; private set; }

        // Separate buffers for VOD computation. Inner-depth deltas (rolling 30s
        // stdev = VOD), then VOD values themselves (rolling 120s baseline = z).
        private readonly LinkedList<TimedDouble> _innerDeltas = new();
        private readonly LinkedList<TimedDouble> _vodValues = new();
        private readonly LinkedList<DateTime> _vodEvents = new();
        private double? _prevInnerDepth;

        public void SetAnchor(DateTime utc)
        {
            _anchorUtc = utc;
            RecomputeCumulative();
        }

        // Sample current book at this time. Updates rolling baseline, detects
        // events, recomputes cum and ROC. Caller (LiquidityMeter.OnUpdate)
        // invokes this on a 1-sec timer with the canonical book state pulled
        // from Symbol.DepthOfMarket — see RESEARCH_LOG 2026-05-08 migration.
        public void OnSample(DateTime nowUtc, DepthOfMarketAggregatedCollections dom, double tickSize)
        {
            var sample = ComputeSample(nowUtc, dom, tickSize);
            _samples.AddLast(sample);
            // Keep ~2x lookback in samples buffer for safety.
            EvictOlderThan(_samples, nowUtc, _lookbackSec * 2);

            if (_samples.Count < 5) return;  // need history before z-scoring

            // Rolling stats over the lookback window for each metric.
            (double mBi, double sBi) = MeanStd(s => s.BidInner, nowUtc);
            (double mAi, double sAi) = MeanStd(s => s.AskInner, nowUtc);
            (double mBc, double sBc) = MeanStd(s => s.BidCentroid, nowUtc);
            (double mAc, double sAc) = MeanStd(s => s.AskCentroid, nowUtc);

            double zBi = (sample.BidInner    - mBi) / Math.Max(_stdFloor,    sBi);
            double zAi = (sample.AskInner    - mAi) / Math.Max(_stdFloor,    sAi);
            double zBc = (sample.BidCentroid - mBc) / Math.Max(_centStdFloor, sBc);
            double zAc = (sample.AskCentroid - mAc) / Math.Max(_centStdFloor, sAc);

            // Directional bias map (matches research/liq_events.py):
            //   z_bi > 0  → BID_BUILD  (bull)        z_bi < 0 → BID_PULL  (bear)
            //   z_ai > 0  → ASK_BUILD  (bear)        z_ai < 0 → ASK_PULL  (bull)
            //   z_bc > 0  → BID_OUT    (bear)        z_bc < 0 → BID_IN    (bull)
            //   z_ac > 0  → ASK_OUT    (bull)        z_ac < 0 → ASK_IN    (bear)
            TryFire(nowUtc, zBi, +1, "BID_BUILD", "BID_PULL");
            TryFire(nowUtc, zAi, -1, "ASK_BUILD", "ASK_PULL");
            TryFire(nowUtc, zBc, -1, "BID_OUT",   "BID_IN");
            TryFire(nowUtc, zAc, +1, "ASK_OUT",   "ASK_IN");

            // ── VOL_OF_DEPTH detection ──────────────────────────────────
            // 1) Inner-depth delta this sample (vs previous).
            // 2) Rolling 30s stdev of those deltas → "vod" current value.
            // 3) Rolling 120s mean/std of vod itself → z-score.
            // 4) |z| > threshold fires a chaos event (no bias contribution).
            double currInner = sample.BidInner + sample.AskInner;
            if (_prevInnerDepth.HasValue)
            {
                double delta = currInner - _prevInnerDepth.Value;
                _innerDeltas.AddLast(new TimedDouble { Time = nowUtc, Value = delta });
                EvictOlderThan(_innerDeltas, nowUtc, _lookbackSec * 2);

                if (_innerDeltas.Count >= 4)
                {
                    double vod = StdOver(_innerDeltas, nowUtc, _lookbackSec);
                    _vodValues.AddLast(new TimedDouble { Time = nowUtc, Value = vod });
                    EvictOlderThan(_vodValues, nowUtc, _lookbackSec * 8);  // keep 4× the vod window

                    if (_vodValues.Count >= 8)
                    {
                        var (mVod, sVod) = MeanStdOf(_vodValues, nowUtc, _lookbackSec * 4);
                        double zVod = (vod - mVod) / Math.Max(0.1, sVod);
                        if (Math.Abs(zVod) > _zThreshold)
                        {
                            LastVodTime = nowUtc;
                            LastVodZ = zVod;
                            _vodEvents.AddLast(nowUtc);
                        }
                    }
                }
            }
            _prevInnerDepth = currInner;
            // Keep VOD event list small + recompute count.
            var vodCutoff = nowUtc.AddSeconds(-30);
            while (_vodEvents.Count > 0 && _vodEvents.First.Value < vodCutoff)
                _vodEvents.RemoveFirst();
            VodCount30s = _vodEvents.Count;

            // Maintain rolling anchor (if configured) before publishing cum.
            if (RollingAnchorWindow.HasValue)
            {
                var newAnchor = nowUtc - RollingAnchorWindow.Value;
                if (newAnchor > _anchorUtc) _anchorUtc = newAnchor;
            }

            RecomputeCumulative();
            RecomputeROC(nowUtc);
            // Retention must cover the active anchor horizon. With only a
            // rocWindow*6 floor, cum silently became a ~6min sum even when
            // the configured anchor was rolling-30m / session / load.
            int rocFloorSec = _rocWindowSec * 6;
            int retentionSec = RollingAnchorWindow.HasValue
                ? Math.Max(rocFloorSec, (int)RollingAnchorWindow.Value.TotalSeconds + _rocWindowSec)
                : Math.Max(rocFloorSec, (int)Math.Max(0, (nowUtc - _anchorUtc).TotalSeconds) + _rocWindowSec);
            EvictOlderThan(_events, nowUtc, retentionSec);
        }

        // bias_pos is the bias of the POSITIVE-z event. Negative-z gets the
        // opposite bias. e.g., bias_pos=+1 for BID_BUILD/BID_PULL means
        // BID_BUILD (z>0) is +1 (bull), BID_PULL (z<0) is -1 (bear).
        private void TryFire(DateTime time, double z, int biasPos, string posLabel, string negLabel)
        {
            if (Math.Abs(z) <= _zThreshold) return;
            int bias = z > 0 ? biasPos : -biasPos;
            string label = z > 0 ? posLabel : negLabel;
            _events.AddLast(new MeterEvent
            {
                Time = time, Bias = bias, AbsZ = Math.Abs(z), Type = label
            });
        }

        private void RecomputeCumulative()
        {
            double cum = 0;
            foreach (var ev in _events)
            {
                if (ev.Time >= _anchorUtc)
                    cum += ev.Bias * ev.AbsZ;
            }
            Cumulative = cum;
        }

        private void RecomputeROC(DateTime nowUtc)
        {
            double roc = 0;
            var cutoff = nowUtc.AddSeconds(-_rocWindowSec);
            foreach (var ev in _events)
            {
                if (ev.Time >= cutoff)
                    roc += ev.Bias * ev.AbsZ;
            }
            RateOfChange = roc;
        }

        private (double mean, double std) MeanStd(Func<Sample, double> sel, DateTime nowUtc)
        {
            var cutoff = nowUtc.AddSeconds(-_lookbackSec);
            double sum = 0, sumSq = 0;
            int n = 0;
            foreach (var s in _samples)
            {
                if (s.Time < cutoff) continue;
                double v = sel(s);
                sum += v;
                sumSq += v * v;
                n++;
            }
            if (n < 2) return (0, 0);
            double mean = sum / n;
            double var = (sumSq / n) - mean * mean;
            double std = var > 0 ? Math.Sqrt(var) : 0;
            return (mean, std);
        }

        // Read aggregate metrics from QT's canonical DepthOfMarket. Best-first
        // ordered Level2Item arrays. Same math as before: sum top-N sizes for
        // inner_depth, size-weighted centroid distances over broad-N. Mid-tick
        // = (best_bid + best_ask) / 2 in tick units. See RESEARCH_LOG
        // 2026-05-08 for why we read DOM directly instead of maintaining a
        // delta-merged BookState.
        private Sample ComputeSample(DateTime time, DepthOfMarketAggregatedCollections dom, double tickSize)
        {
            var s = new Sample { Time = time };
            var bids = dom?.Bids ?? Array.Empty<Level2Item>();
            var asks = dom?.Asks ?? Array.Empty<Level2Item>();

            // Top-N inner depth, skipping non-finite / zero entries so leaks
            // can't poison sums (and the resulting z-scores).
            int taken = 0;
            for (int i = 0; i < bids.Length && taken < InnerLevels; i++)
            {
                double p = bids[i].Price;
                double sz = bids[i].Size;
                if (!double.IsFinite(p) || p <= 0) continue;
                if (!double.IsFinite(sz) || sz <= 0) continue;
                s.BidInner += sz; taken++;
            }
            taken = 0;
            for (int i = 0; i < asks.Length && taken < InnerLevels; i++)
            {
                double p = asks[i].Price;
                double sz = asks[i].Size;
                if (!double.IsFinite(p) || p <= 0) continue;
                if (!double.IsFinite(sz) || sz <= 0) continue;
                s.AskInner += sz; taken++;
            }

            // Best-of-side from first finite-price, size>0 level.
            double bbPrice = FirstValidPrice(bids);
            double baPrice = FirstValidPrice(asks);
            bool haveBid = !double.IsNaN(bbPrice);
            bool haveAsk = !double.IsNaN(baPrice);
            long bestBid = haveBid ? PriceToTicks(bbPrice, tickSize) : 0;
            long bestAsk = haveAsk ? PriceToTicks(baPrice, tickSize) : 0;
            long refTick = (haveBid && haveAsk) ? (bestBid + bestAsk) / 2 :
                           (haveBid ? bestBid : (haveAsk ? bestAsk : 0));

            double bWsum = 0, bSize = 0;
            taken = 0;
            for (int i = 0; i < bids.Length && taken < BroadLevels; i++)
            {
                double p = bids[i].Price;
                double sz = bids[i].Size;
                if (!double.IsFinite(p) || p <= 0) continue;
                if (!double.IsFinite(sz) || sz <= 0) continue;
                long t = PriceToTicks(p, tickSize);
                bWsum += Math.Abs(t - refTick) * sz;
                bSize += sz;
                taken++;
            }
            double aWsum = 0, aSize = 0;
            taken = 0;
            for (int i = 0; i < asks.Length && taken < BroadLevels; i++)
            {
                double p = asks[i].Price;
                double sz = asks[i].Size;
                if (!double.IsFinite(p) || p <= 0) continue;
                if (!double.IsFinite(sz) || sz <= 0) continue;
                long t = PriceToTicks(p, tickSize);
                aWsum += Math.Abs(t - refTick) * sz;
                aSize += sz;
                taken++;
            }
            s.BidCentroid = bSize > 0 ? bWsum / bSize : 0;
            s.AskCentroid = aSize > 0 ? aWsum / aSize : 0;
            return s;
        }

        private static long PriceToTicks(double price, double tickSize)
            => (long)Math.Round(price / tickSize);

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
            where T : ITimestamped
        {
            var cutoff = nowUtc.AddSeconds(-seconds);
            while (list.Count > 0 && list.First.Value.Time < cutoff)
                list.RemoveFirst();
        }

        private static double StdOver(LinkedList<TimedDouble> values, DateTime nowUtc, int seconds)
        {
            var cutoff = nowUtc.AddSeconds(-seconds);
            double sum = 0, sumSq = 0; int n = 0;
            foreach (var v in values)
            {
                if (v.Time < cutoff) continue;
                sum += v.Value; sumSq += v.Value * v.Value; n++;
            }
            if (n < 2) return 0;
            double mean = sum / n;
            double var = (sumSq / n) - mean * mean;
            return var > 0 ? Math.Sqrt(var) : 0;
        }

        private static (double mean, double std) MeanStdOf(LinkedList<TimedDouble> values, DateTime nowUtc, int seconds)
        {
            var cutoff = nowUtc.AddSeconds(-seconds);
            double sum = 0, sumSq = 0; int n = 0;
            foreach (var v in values)
            {
                if (v.Time < cutoff) continue;
                sum += v.Value; sumSq += v.Value * v.Value; n++;
            }
            if (n < 2) return (0, 0);
            double mean = sum / n;
            double var = (sumSq / n) - mean * mean;
            return (mean, var > 0 ? Math.Sqrt(var) : 0);
        }

        public interface ITimestamped { DateTime Time { get; } }

        public sealed class TimedDouble : ITimestamped
        {
            public DateTime Time { get; set; }
            public double Value;
        }

        private sealed class Sample : ITimestamped
        {
            public DateTime Time { get; set; }
            public double BidInner;
            public double AskInner;
            public double BidCentroid;
            public double AskCentroid;
        }

        public sealed class MeterEvent : ITimestamped
        {
            public DateTime Time { get; set; }
            public int Bias;          // +1 bull, -1 bear
            public double AbsZ;
            public string Type;
        }
    }
}
