using System;
using System.Collections.Generic;

namespace Absorption_Exhaustion
{
    // Aggregates trade prints into fixed-duration bars (default 5s) and exposes
    // a rolling window of recent bars for baseline statistics. The bar boundary
    // is wall-clock-aligned via floor(time_us / barUs); empty time slots leave
    // gaps in the history rather than synthesizing zero-vol bars (cheaper and
    // baseline math handles variable-length windows naturally).
    internal sealed class TradeBuffer
    {
        public sealed class Bar
        {
            public long BucketKey;          // floor(timeUs / barUs)
            public DateTime OpenTime;       // bucket start (UTC)
            public double Open, High, Low, Close;
            public long Volume;
            public long BuyVolume;          // Aggressor.Buy
            public long SellVolume;         // Aggressor.Sell
            // Volume-by-price keyed by tick (long), with separate buy/sell sums.
            public readonly Dictionary<long, (long buy, long sell)> Vbp
                = new Dictionary<long, (long buy, long sell)>(16);
        }

        private readonly double _tickSize;
        private readonly long _barUs;
        private readonly long _lookbackUs;
        private readonly LinkedList<Bar> _history = new LinkedList<Bar>();
        private Bar _current;

        public TradeBuffer(double tickSize, int barSeconds, int lookbackSeconds)
        {
            _tickSize = tickSize;
            _barUs = barSeconds * 1_000_000L;
            _lookbackUs = lookbackSeconds * 1_000_000L;
        }

        public long PriceToTicks(double price)
            => (long)Math.Round(price / _tickSize);

        public double TicksToPrice(long ticks)
            => ticks * _tickSize;

        // Returns the bar that just closed (or null) plus a flag indicating a
        // bar boundary was crossed. Caller runs detectors when a bar closes.
        public Bar OnTrade(DateTime timeUtc, double price, double size, int aggressorSign)
        {
            long timeUs = ToMicros(timeUtc);
            long bucket = timeUs / _barUs;

            Bar closed = null;
            if (_current == null)
            {
                _current = NewBar(bucket, timeUtc);
            }
            else if (bucket != _current.BucketKey)
            {
                closed = _current;
                _history.AddLast(closed);
                EvictOlderThan(timeUs);
                _current = NewBar(bucket, FloorBucket(timeUs));
            }

            UpdateBar(_current, price, size, aggressorSign);
            return closed;
        }

        // Forces close of the current bar without a new trade. Used on timer
        // ticks so we don't sit on a stale open bar during quiet stretches.
        public Bar TryCloseStaleBar(DateTime nowUtc)
        {
            if (_current == null) return null;
            long nowUs = ToMicros(nowUtc);
            long bucket = nowUs / _barUs;
            if (bucket == _current.BucketKey) return null;
            var closed = _current;
            _history.AddLast(closed);
            EvictOlderThan(nowUs);
            _current = null;
            return closed;
        }

        public IReadOnlyCollection<Bar> History => _history;

        public int HistoryCount => _history.Count;

        private Bar NewBar(long bucket, DateTime openTime)
            => new Bar
            {
                BucketKey = bucket,
                OpenTime = openTime,
                Open = double.NaN,
                High = double.MinValue,
                Low = double.MaxValue,
                Close = double.NaN,
            };

        private void UpdateBar(Bar b, double price, double size, int aggressorSign)
        {
            if (double.IsNaN(b.Open)) b.Open = price;
            if (price > b.High) b.High = price;
            if (price < b.Low) b.Low = price;
            b.Close = price;
            long sz = (long)size;
            if (sz <= 0) sz = 1;
            b.Volume += sz;
            long tick = PriceToTicks(price);
            b.Vbp.TryGetValue(tick, out var v);
            if (aggressorSign > 0) { b.BuyVolume += sz; v.buy += sz; }
            else if (aggressorSign < 0) { b.SellVolume += sz; v.sell += sz; }
            b.Vbp[tick] = v;
        }

        private void EvictOlderThan(long nowUs)
        {
            while (_history.Count > 0)
            {
                var head = _history.First.Value;
                long headUs = ToMicros(head.OpenTime);
                if (nowUs - headUs > _lookbackUs)
                    _history.RemoveFirst();
                else
                    break;
            }
        }

        private DateTime FloorBucket(long timeUs)
        {
            long floored = (timeUs / _barUs) * _barUs;
            return new DateTime(1970, 1, 1, 0, 0, 0, DateTimeKind.Utc).AddTicks(floored * 10);
        }

        private static long ToMicros(DateTime t)
            => (t.ToUniversalTime() - new DateTime(1970, 1, 1, 0, 0, 0, DateTimeKind.Utc)).Ticks / 10;
    }
}
