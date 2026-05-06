// Mirror of L2_Heatmap/BookState.cs. Keep in sync if the L2_Heatmap version
// changes — same L2 delta semantics, same NaN-filter, same tick keying.
// Quantower indicators are loaded into isolated assemblies, so a shared
// helper library would add deployment complexity for one file's worth of
// duplication. Copy-and-keep-aligned is the cleaner trade-off here.
using System;
using System.Collections.Generic;
using TradingPlatform.BusinessLayer;
using TradingPlatform.BusinessLayer.Integration;

namespace LiquidityMeter
{
    public sealed class BookState
    {
        private readonly double _tickSize;
        private readonly Dictionary<string, OrderEntry> _orders = new();
        private readonly SortedDictionary<long, PriceLevel> _bids =
            new(Comparer<long>.Create((a, b) => b.CompareTo(a))); // descending: best bid first
        private readonly SortedDictionary<long, PriceLevel> _asks = new(); // ascending: best ask first

        public BookState(double tickSize)
        {
            _tickSize = tickSize > 0 ? tickSize : 0.25;
        }

        public double TickSize => _tickSize;
        public IReadOnlyDictionary<long, PriceLevel> BidsByTick => _bids;
        public IReadOnlyDictionary<long, PriceLevel> AsksByTick => _asks;

        public long PriceToTicks(double price) => (long)Math.Round(price / _tickSize);
        public double TicksToPrice(long ticks) => ticks * _tickSize;

        public void Clear()
        {
            _orders.Clear();
            _bids.Clear();
            _asks.Clear();
        }

        public void Apply(Level2Quote q)
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
                    if (side.TryGetValue(priorTicks, out var lvl))
                    {
                        lvl.TotalSize -= prior.Size;
                        lvl.Ids.Remove(q.Id);
                        if (lvl.TotalSize <= 0 || lvl.Ids.Count == 0) side.Remove(priorTicks);
                    }
                }
                _orders.Remove(q.Id);
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
                if (side.TryGetValue(priorTicks, out var priorLvl))
                {
                    priorLvl.TotalSize -= prior.Size;
                    // Also drop the ID/level when shrinking to zero at the same
                    // price — otherwise a non-Closed zero-size update leaves a
                    // stale ID in the set with TotalSize == 0.
                    if (priorTicks != newTicks || q.Size <= 0)
                    {
                        priorLvl.Ids.Remove(q.Id);
                        if (priorLvl.TotalSize <= 0 || priorLvl.Ids.Count == 0)
                            side.Remove(priorTicks);
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
            }
        }

        public sealed class PriceLevel
        {
            public double Price;
            public double TotalSize;
            public HashSet<string> Ids = new();
        }

        public struct OrderEntry
        {
            public double Price;
            public double Size;
            public bool IsBid;
        }
    }
}
