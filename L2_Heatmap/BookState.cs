using System;
using System.Collections.Generic;
using System.Linq;
using TradingPlatform.BusinessLayer;
using TradingPlatform.BusinessLayer.Integration;

namespace L2_Heatmap
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

        // Last time any L2 delta arrived. Indicators consult this to detect
        // feed-paused state ("delayed by X ms" QT message) and pause sampling.
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
            // Skip Quantower's pseudo-L2 events synthesized from L1 best-bid/ask changes
            // (id="generated_from_level1", NaN price/size).
            if (double.IsNaN(q.Price) || double.IsNaN(q.Size)) return;

            bool isBid = q.PriceType == QuotePriceType.Bid;
            var side = isBid ? _bids : _asks;
            _orders.TryGetValue(q.Id, out var prior);

            // Closed → remove the prior contribution at the prior price.
            if (q.Closed)
            {
                if (prior.Size > 0)
                {
                    long priorTicks = PriceToTicks(prior.Price);
                    // Use prior.IsBid to find the level — current q.PriceType could
                    // disagree if the feed ever recycles an ID across sides.
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

            // Update _orders BEFORE mutating the side map (re-entrant defense).
            long newTicks = PriceToTicks(q.Price);
            if (q.Size > 0)
                _orders[q.Id] = new OrderEntry { Price = q.Price, Size = q.Size, IsBid = isBid };
            else
                _orders.Remove(q.Id);

            // Remove prior contribution (same price = modify-in-place, different = move).
            if (prior.Size > 0)
            {
                long priorTicks = PriceToTicks(prior.Price);
                // Same robustness: pick prior side from prior.IsBid, not current q.PriceType.
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
                        // Defensive clamp — feed-delivery edge case (two removes before an add).
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

        // Reconcile L2-derived top-of-book against L1 (Symbol.Bid / Symbol.Ask).
        // L1 is its own stream and doesn't depend on our BookState, so it's an
        // independent reference. Any L2 entry whose tick violates the L1
        // top-of-book by more than `toleranceTicks` is impossible in a healthy
        // book — prune it. Returns false if after pruning the L2 best-of-book
        // still disagrees with L1 by more than tolerance (i.e. the book is in
        // a state we can't reconcile, indicators should pause).
        //
        // Skipped (returns true) when L1 is NaN — early-init or pre-market.
        public bool ReconcileWithL1(double symbolBid, double symbolAsk, int toleranceTicks)
        {
            if (double.IsNaN(symbolBid) || double.IsNaN(symbolAsk)) return true;
            if (toleranceTicks < 0) toleranceTicks = 0;

            long l1Bid = PriceToTicks(symbolBid);
            long l1Ask = PriceToTicks(symbolAsk);

            // Prune bids strictly above (L1 ask + tolerance) — no real bid sits
            // above the live ask. Prune asks strictly below (L1 bid - tolerance)
            // by the same logic.
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

            // After pruning, L2 best-of-book should land within tolerance of
            // L1. If either side is empty, or top-of-book disagrees, we can't
            // reconcile from current L1 — caller pauses.
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

        // Defense in depth against missed Closed events / feed gaps / contract
        // rolls: if a level hasn't been touched in `ttlSec`, treat it as stale
        // and remove. On 2026-05-08 we saw `_asks` retain entries at ~28915
        // through a 29300+ session — best ask got pinned to a phantom low and
        // ref_tick drifted ~200pts below the trade tape. Periodic prune keeps
        // the book honest even when the feed misses a Closed.
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
