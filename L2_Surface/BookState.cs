// Mirror of LiquidityMeter/BookState.cs (which mirrors L2_Heatmap/BookState.cs).
// Three copies now exist (L2_Heatmap, LiquidityMeter, L2_Surface). Keep in sync
// if any change. Per-indicator isolated assemblies; sharing one file across
// projects via reference would require a fourth deployable DLL plus per-project
// references — disproportionate cost for a stable ~120-line file. Copy-and-
// align is the cleaner trade-off here.
using System;
using System.Collections.Generic;
using System.Linq;
using TradingPlatform.BusinessLayer;
using TradingPlatform.BusinessLayer.Integration;

namespace L2_Surface
{
    public sealed class BookState
    {
        private readonly double _tickSize;
        private readonly Dictionary<string, OrderEntry> _orders = new();
        private readonly SortedDictionary<long, PriceLevel> _bids =
            new(Comparer<long>.Create((a, b) => b.CompareTo(a)));
        private readonly SortedDictionary<long, PriceLevel> _asks = new();

        public BookState(double tickSize)
        {
            _tickSize = tickSize > 0 ? tickSize : 0.25;
        }

        public double TickSize => _tickSize;
        public IReadOnlyDictionary<long, PriceLevel> BidsByTick => _bids;
        public IReadOnlyDictionary<long, PriceLevel> AsksByTick => _asks;

        public DateTime LastApplyTime { get; private set; }

        public long PriceToTicks(double price) => (long)Math.Round(price / _tickSize);
        public double TicksToPrice(long ticks) => ticks * _tickSize;

        public bool IsFresh(DateTime nowUtc, double freshnessSec)
        {
            if (LastApplyTime == default) return false;
            return (nowUtc - LastApplyTime).TotalSeconds <= freshnessSec;
        }

        public void Clear()
        {
            _orders.Clear();
            _bids.Clear();
            _asks.Clear();
            LastApplyTime = default;
        }

        public void Apply(Level2Quote q, DateTime nowUtc)
        {
            if (q == null || string.IsNullOrEmpty(q.Id)) return;
            if (double.IsNaN(q.Price) || double.IsNaN(q.Size)) return;

            bool isBid = q.PriceType == QuotePriceType.Bid;
            var side = isBid ? _bids : _asks;
            _orders.TryGetValue(q.Id, out var prior);

            if (q.Closed)
            {
                if (prior.Size > 0)
                {
                    long priorTicks = PriceToTicks(prior.Price);
                    var priorSide = prior.IsBid ? _bids : _asks;
                    if (priorSide.TryGetValue(priorTicks, out var lvl))
                    {
                        lvl.TotalSize -= prior.Size;
                        lvl.Ids.Remove(q.Id);
                        lvl.LastUpdate = nowUtc;
                        if (lvl.TotalSize <= 0 || lvl.Ids.Count == 0) priorSide.Remove(priorTicks);
                    }
                }
                _orders.Remove(q.Id);
                LastApplyTime = nowUtc;
                return;
            }

            long newTicks = PriceToTicks(q.Price);
            if (q.Size > 0)
                _orders[q.Id] = new OrderEntry { Price = q.Price, Size = q.Size, IsBid = isBid };
            else
                _orders.Remove(q.Id);

            if (prior.Size > 0)
            {
                long priorTicks = PriceToTicks(prior.Price);
                var priorSide = prior.IsBid ? _bids : _asks;
                if (priorSide.TryGetValue(priorTicks, out var priorLvl))
                {
                    priorLvl.TotalSize -= prior.Size;
                    priorLvl.LastUpdate = nowUtc;
                    bool sameSlot = priorSide == side && priorTicks == newTicks && q.Size > 0;
                    if (!sameSlot)
                    {
                        priorLvl.Ids.Remove(q.Id);
                        if (priorLvl.TotalSize <= 0 || priorLvl.Ids.Count == 0)
                            priorSide.Remove(priorTicks);
                    }
                    else if (priorLvl.TotalSize < 0)
                    {
                        priorLvl.TotalSize = 0;
                    }
                }
            }

            if (q.Size > 0)
            {
                if (!side.TryGetValue(newTicks, out var newLvl))
                {
                    newLvl = new PriceLevel { Price = q.Price };
                    side[newTicks] = newLvl;
                }
                newLvl.TotalSize += q.Size;
                newLvl.Ids.Add(q.Id);
                newLvl.LastUpdate = nowUtc;
            }

            LastApplyTime = nowUtc;
        }

        public bool ReconcileWithL1(double symbolBid, double symbolAsk, int toleranceTicks)
        {
            if (double.IsNaN(symbolBid) || double.IsNaN(symbolAsk)) return true;
            if (toleranceTicks < 0) toleranceTicks = 0;

            long l1Bid = PriceToTicks(symbolBid);
            long l1Ask = PriceToTicks(symbolAsk);
            long bidCutoff = l1Ask + toleranceTicks;
            long askCutoff = l1Bid - toleranceTicks;

            List<long> toRemove = null;
            foreach (var kv in _bids)
            {
                if (kv.Key > bidCutoff)
                {
                    toRemove ??= new List<long>();
                    toRemove.Add(kv.Key);
                }
            }
            if (toRemove != null) { foreach (var t in toRemove) DropLevel(_bids, t); toRemove.Clear(); }

            foreach (var kv in _asks)
            {
                if (kv.Key < askCutoff)
                {
                    toRemove ??= new List<long>();
                    toRemove.Add(kv.Key);
                }
            }
            if (toRemove != null) { foreach (var t in toRemove) DropLevel(_asks, t); }

            if (_bids.Count == 0 || _asks.Count == 0) return false;
            long bestBid = _bids.First().Key;
            long bestAsk = _asks.First().Key;
            if (Math.Abs(bestBid - l1Bid) > toleranceTicks) return false;
            if (Math.Abs(bestAsk - l1Ask) > toleranceTicks) return false;
            return true;
        }

        private void DropLevel(SortedDictionary<long, PriceLevel> side, long tick)
        {
            if (!side.TryGetValue(tick, out var lvl)) return;
            foreach (var id in lvl.Ids) _orders.Remove(id);
            side.Remove(tick);
        }

        public void PruneStale(DateTime nowUtc, double ttlSec)
        {
            if (ttlSec <= 0) return;
            var cutoff = nowUtc.AddSeconds(-ttlSec);
            PruneSide(_bids, cutoff);
            PruneSide(_asks, cutoff);
        }

        private void PruneSide(SortedDictionary<long, PriceLevel> side, DateTime cutoff)
        {
            List<long> toRemove = null;
            foreach (var kv in side)
            {
                if (kv.Value.LastUpdate < cutoff)
                {
                    toRemove ??= new List<long>();
                    toRemove.Add(kv.Key);
                }
            }
            if (toRemove == null) return;
            foreach (var t in toRemove) DropLevel(side, t);
        }

        public sealed class PriceLevel
        {
            public double Price;
            public double TotalSize;
            public HashSet<string> Ids = new();
            public DateTime LastUpdate;
        }

        public struct OrderEntry
        {
            public double Price;
            public double Size;
            public bool IsBid;
        }
    }
}
