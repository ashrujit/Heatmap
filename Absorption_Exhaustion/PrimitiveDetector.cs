using System;
using System.Collections.Generic;

namespace Absorption_Exhaustion
{
    internal enum PrimitiveType { A1, A2, E1, E2 }
    internal enum FireDirection { Bear, Bull }

    internal readonly struct PrimitiveFire
    {
        public readonly PrimitiveType Type;
        public readonly FireDirection Direction;
        public readonly long PriceTick;       // price as tick-key
        public readonly DateTime FireTime;    // UTC
        public PrimitiveFire(PrimitiveType type, FireDirection dir, long tick, DateTime time)
        { Type = type; Direction = dir; PriceTick = tick; FireTime = time; }
    }

    internal sealed class PrimitiveDetector
    {
        private readonly TradeBuffer _buffer;
        private readonly DetectorParams _p;

        public PrimitiveDetector(TradeBuffer buffer, DetectorParams p)
        { _buffer = buffer; _p = p; }

        // Evaluate primitives against the just-closed bar. Baseline is the prior
        // history *excluding* the bar we're evaluating — vol-z and "new local
        // extreme" must be computed against the past, not against ourselves.
        public IEnumerable<PrimitiveFire> EvaluateClosedBar(TradeBuffer.Bar bar)
        {
            if (bar == null) yield break;
            // Need some baseline history. 4 prior bars = 20s minimum.
            if (_buffer.HistoryCount < 5) yield break;

            // Compute baseline excluding the bar itself (it's already appended).
            double sum = 0, sumSq = 0;
            int n = 0;
            double baseHigh = double.MinValue, baseLow = double.MaxValue;
            foreach (var bb in _buffer.History)
            {
                if (bb == bar) continue;
                sum += bb.Volume; sumSq += (double)bb.Volume * bb.Volume; n++;
                if (bb.High > baseHigh) baseHigh = bb.High;
                if (bb.Low < baseLow) baseLow = bb.Low;
            }
            if (n < 4) yield break;
            double mean = sum / n;
            double var = (sumSq / n) - (mean * mean);
            double std = var > 0 ? Math.Sqrt(var) : 1.0;
            if (std < 1.0) std = 1.0;
            double volZ = (bar.Volume - mean) / std;

            bool isNewHigh = bar.High > baseHigh;
            bool isNewLow = bar.Low < baseLow;
            long delta = bar.BuyVolume - bar.SellVolume;
            double deltaRatio = bar.Volume > 0 ? Math.Abs(delta) / (double)bar.Volume : 0;

            // ---- A2: Balanced high-vol absorbing bar at local extreme ----
            if (volZ > _p.BalancedVolZ && deltaRatio < _p.BalancedDeltaRatio)
            {
                if (isNewHigh)
                    yield return new PrimitiveFire(PrimitiveType.A2, FireDirection.Bear,
                        _buffer.PriceToTicks(bar.High), bar.OpenTime);
                if (isNewLow)
                    yield return new PrimitiveFire(PrimitiveType.A2, FireDirection.Bull,
                        _buffer.PriceToTicks(bar.Low), bar.OpenTime);
            }

            // ---- E2: Weak-delta extreme bar ----
            if (deltaRatio < _p.WeakDeltaRatio)
            {
                if (isNewHigh)
                    yield return new PrimitiveFire(PrimitiveType.E2, FireDirection.Bear,
                        _buffer.PriceToTicks(bar.High), bar.OpenTime);
                if (isNewLow)
                    yield return new PrimitiveFire(PrimitiveType.E2, FireDirection.Bull,
                        _buffer.PriceToTicks(bar.Low), bar.OpenTime);
            }

            // ---- A1: Stacked one-sided imbalance, no extension ----
            // For new-high: descend from top, count consecutive levels with
            // buy-side imbalance above threshold AND volume above floor.
            if (isNewHigh)
            {
                var levels = SortedLevels(bar, descending: true);
                int consec = 0;
                bool fired = false;
                foreach (var px in levels)
                {
                    var v = bar.Vbp[px];
                    long tot = v.buy + v.sell;
                    if (tot < _p.StackedMinVolPerLevel) { consec = 0; continue; }
                    double imb = (v.buy - v.sell) / (double)tot;
                    if (imb > _p.StackedImb)
                    {
                        consec++;
                        if (consec >= _p.StackedN)
                        {
                            yield return new PrimitiveFire(PrimitiveType.A1, FireDirection.Bear,
                                _buffer.PriceToTicks(bar.High), bar.OpenTime);
                            fired = true;
                            break;
                        }
                    }
                    else consec = 0;
                }
                if (fired) { /* no-op, just for clarity */ }
            }
            if (isNewLow)
            {
                var levels = SortedLevels(bar, descending: false);
                int consec = 0;
                foreach (var px in levels)
                {
                    var v = bar.Vbp[px];
                    long tot = v.buy + v.sell;
                    if (tot < _p.StackedMinVolPerLevel) { consec = 0; continue; }
                    double imb = (v.sell - v.buy) / (double)tot;
                    if (imb > _p.StackedImb)
                    {
                        consec++;
                        if (consec >= _p.StackedN)
                        {
                            yield return new PrimitiveFire(PrimitiveType.A1, FireDirection.Bull,
                                _buffer.PriceToTicks(bar.Low), bar.OpenTime);
                            break;
                        }
                    }
                    else consec = 0;
                }
            }

            // ---- E1: Single-print at extreme + heavy neighbor imbalance ----
            if (isNewHigh)
            {
                long topTick = _buffer.PriceToTicks(bar.High);
                if (bar.Vbp.TryGetValue(topTick, out var topV))
                {
                    long topVol = topV.buy + topV.sell;
                    if (topVol <= _p.ThinExtremeMaxVol)
                    {
                        for (int off = 1; off <= 2; off++)
                        {
                            if (bar.Vbp.TryGetValue(topTick - off, out var nbr))
                            {
                                long nbrTot = nbr.buy + nbr.sell;
                                if (nbrTot >= _p.ThinNeighborMinVol)
                                {
                                    double imb = (nbr.buy - nbr.sell) / (double)nbrTot;
                                    if (imb > _p.ThinNeighborMinImb)
                                    {
                                        yield return new PrimitiveFire(PrimitiveType.E1,
                                            FireDirection.Bear, topTick, bar.OpenTime);
                                        break;
                                    }
                                }
                            }
                        }
                    }
                }
            }
            if (isNewLow)
            {
                long botTick = _buffer.PriceToTicks(bar.Low);
                if (bar.Vbp.TryGetValue(botTick, out var botV))
                {
                    long botVol = botV.buy + botV.sell;
                    if (botVol <= _p.ThinExtremeMaxVol)
                    {
                        for (int off = 1; off <= 2; off++)
                        {
                            if (bar.Vbp.TryGetValue(botTick + off, out var nbr))
                            {
                                long nbrTot = nbr.buy + nbr.sell;
                                if (nbrTot >= _p.ThinNeighborMinVol)
                                {
                                    double imb = (nbr.sell - nbr.buy) / (double)nbrTot;
                                    if (imb > _p.ThinNeighborMinImb)
                                    {
                                        yield return new PrimitiveFire(PrimitiveType.E1,
                                            FireDirection.Bull, botTick, bar.OpenTime);
                                        break;
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }

        private static List<long> SortedLevels(TradeBuffer.Bar bar, bool descending)
        {
            var list = new List<long>(bar.Vbp.Count);
            foreach (var k in bar.Vbp.Keys) list.Add(k);
            if (descending) list.Sort((a, b) => b.CompareTo(a));
            else list.Sort();
            return list;
        }
    }

    internal sealed class DetectorParams
    {
        public int StackedN = 3;
        public double StackedImb = 0.5;
        public long StackedMinVolPerLevel = 10;
        public double BalancedVolZ = 3.0;
        public double BalancedDeltaRatio = 0.10;
        public long ThinExtremeMaxVol = 3;
        public long ThinNeighborMinVol = 30;
        public double ThinNeighborMinImb = 0.5;
        public double WeakDeltaRatio = 0.15;
    }
}
