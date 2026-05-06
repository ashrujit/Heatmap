using System;
using System.Collections.Generic;

namespace Absorption_Exhaustion
{
    // Accumulates primitive fires keyed by (priceTick, direction). Self-clears
    // bands when current price trades through them in the invalidating direction.
    //
    // Clearing rule:
    //   bear band at tick T → clears when current price > T + clearKTicks
    //   bull band at tick T → clears when current price < T - clearKTicks
    //
    // The recently-cleared list lets the painter render a brief fade-out effect
    // for "level just broke" — visible for ~ClearFadeSec then dropped.
    internal sealed class PriceBandRegistry
    {
        public sealed class BandEntry
        {
            public long PriceTick;
            public FireDirection Direction;
            public int Count;
            public DateTime LastFireTime;
            // Recent fire timestamps for glyph-fade rendering. Capped.
            public readonly List<DateTime> RecentFires = new List<DateTime>(8);
        }

        public sealed class ClearedEntry
        {
            public long PriceTick;
            public FireDirection Direction;
            public int LastCount;
            public DateTime ClearedAt;
        }

        private readonly Dictionary<(long, FireDirection), BandEntry> _bands
            = new Dictionary<(long, FireDirection), BandEntry>();
        private readonly LinkedList<ClearedEntry> _cleared = new LinkedList<ClearedEntry>();
        private readonly int _clearKTicks;
        private readonly int _clearFadeSec;
        private readonly int _glyphRetentionSec;

        public PriceBandRegistry(int clearKTicks, int clearFadeSec, int glyphRetentionSec)
        {
            _clearKTicks = clearKTicks;
            _clearFadeSec = clearFadeSec;
            _glyphRetentionSec = glyphRetentionSec;
        }

        public IReadOnlyDictionary<(long, FireDirection), BandEntry> Bands => _bands;
        public IReadOnlyCollection<ClearedEntry> Cleared => _cleared;

        public void OnFire(PrimitiveFire f)
        {
            var key = (f.PriceTick, f.Direction);
            if (!_bands.TryGetValue(key, out var entry))
            {
                entry = new BandEntry
                {
                    PriceTick = f.PriceTick,
                    Direction = f.Direction,
                };
                _bands[key] = entry;
            }
            entry.Count++;
            entry.LastFireTime = f.FireTime;
            entry.RecentFires.Add(f.FireTime);
            // Cap glyph list — we only render glyphs within retention anyway.
            if (entry.RecentFires.Count > 16)
                entry.RecentFires.RemoveAt(0);
        }

        // Called on every trade (or on a periodic timer using last-known price).
        // Removes bands invalidated by current price; moves them to the cleared
        // list with timestamp for fade-out painting.
        public void OnPriceUpdate(long currentTick, DateTime nowUtc)
        {
            List<(long, FireDirection)> toRemove = null;
            foreach (var kv in _bands)
            {
                var (tick, dir) = kv.Key;
                bool clear = (dir == FireDirection.Bear && currentTick > tick + _clearKTicks)
                          || (dir == FireDirection.Bull && currentTick < tick - _clearKTicks);
                if (clear)
                {
                    if (toRemove == null) toRemove = new List<(long, FireDirection)>(4);
                    toRemove.Add(kv.Key);
                }
            }
            if (toRemove != null)
            {
                foreach (var k in toRemove)
                {
                    var e = _bands[k];
                    _bands.Remove(k);
                    _cleared.AddLast(new ClearedEntry
                    {
                        PriceTick = e.PriceTick,
                        Direction = e.Direction,
                        LastCount = e.Count,
                        ClearedAt = nowUtc,
                    });
                }
            }
            EvictExpiredCleared(nowUtc);
            EvictOldGlyphs(nowUtc);
        }

        private void EvictExpiredCleared(DateTime nowUtc)
        {
            while (_cleared.Count > 0)
            {
                var head = _cleared.First.Value;
                if ((nowUtc - head.ClearedAt).TotalSeconds > _clearFadeSec)
                    _cleared.RemoveFirst();
                else break;
            }
        }

        private void EvictOldGlyphs(DateTime nowUtc)
        {
            foreach (var entry in _bands.Values)
            {
                if (entry.RecentFires.Count == 0) continue;
                int keepFrom = 0;
                for (int i = 0; i < entry.RecentFires.Count; i++)
                {
                    if ((nowUtc - entry.RecentFires[i]).TotalSeconds <= _glyphRetentionSec)
                        break;
                    keepFrom = i + 1;
                }
                if (keepFrom > 0)
                    entry.RecentFires.RemoveRange(0, keepFrom);
            }
        }

        public void Clear()
        {
            _bands.Clear();
            _cleared.Clear();
        }
    }
}
