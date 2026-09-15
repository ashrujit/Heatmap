using System;
using System.Collections.Generic;
using KahnRuntime.LiveEvidence;

namespace KahnRuntime
{
    internal sealed record CapturedBook(DateTime At, BookDepthSnapshot Depth,
        double Bid, double Ask, string Error, double? L2SourceAgeMs = null,
        double? QuoteSourceAgeMs = null, BookCaptureDiagnostic Diagnostic = null, bool IsPriceOnly = false)
    {
        public bool Valid => Error == null && (Depth != null || IsPriceOnly);
    }

    internal sealed record BookCaptureDiagnostic(int BidLevels, int AskLevels,
        double? SymbolBid, double? SymbolAsk, double? DomBid, double? DomAsk, string Error);

    // Only immutable, already sampled books cross this boundary. Never regenerate
    // past samples by repeatedly reading today's DOM after a worker stall.
    internal sealed class BookObservationBuffer
    {
        private readonly object _gate = new();
        private readonly Queue<CapturedBook> _frames = new();
        private readonly int _capacity;
        private bool _overflow;
        private long _dropped;
        public long Dropped { get { lock (_gate) return _dropped; } }
        public BookObservationBuffer(int capacity)
        {
            if (capacity < 2) throw new ArgumentOutOfRangeException(nameof(capacity));
            _capacity = capacity;
        }
        public int Count { get { lock (_gate) return _frames.Count; } }
        public bool HasBefore(DateTime boundary)
        {
            lock (_gate) return _frames.TryPeek(out var first) && first.At < boundary;
        }
        public int Discard()
        {
            lock (_gate)
            {
                int count = _frames.Count;
                _frames.Clear();
                _overflow = false;
                return count;
            }
        }
        public void Add(CapturedBook frame)
        {
            lock (_gate)
            {
                if (_frames.Count == _capacity)
                {
                    _frames.Dequeue();
                    _overflow = true;
                    _dropped++;
                }
                _frames.Enqueue(frame);
            }
        }
        public (CapturedBook[] Frames, bool Overflow) Drain(int maximum = 128)
        {
            if (maximum < 1) throw new ArgumentOutOfRangeException(nameof(maximum));
            lock (_gate)
            {
                var frames = new CapturedBook[Math.Min(maximum, _frames.Count)];
                for (int i = 0; i < frames.Length; i++) frames[i] = _frames.Dequeue();
                bool overflow = _overflow;
                _overflow = false;
                return (frames, overflow);
            }
        }
    }

    internal readonly record struct BookRecoveryStep(bool Accept, bool Interrupt, string ResetReason);

    // The existing maximum sample gap remains the continuity budget. Elapsed
    // worker time alone is irrelevant when every captured sample is retained.
    internal sealed class BookRecoveryGate
    {
        private readonly TimeSpan _maximumGap;
        private DateTime _lastSeen;
        private bool _resetIssued;
        public DateTime LastGood { get; private set; }
        public BookRecoveryGate(TimeSpan maximumGap) => _maximumGap = maximumGap;
        public void LostBuffer()
        {
            LastGood = default;
            _resetIssued = true;
        }
        public BookRecoveryStep Missing(DateTime now)
            => Unusable(now, "capture_observation_gap");
        private BookRecoveryStep Unusable(DateTime at, string reason)
        {
            bool reset = !_resetIssued && LastGood != default && at - LastGood > _maximumGap;
            if (reset) _resetIssued = true;
            return new(false, true, reset ? reason : null);
        }
        public BookRecoveryStep Inspect(CapturedBook frame)
        {
            if (frame.At == default || (_lastSeen != default && frame.At <= _lastSeen))
            {
                LostBuffer();
                return new(false, true, "capture_time_order_invalid");
            }
            _lastSeen = frame.At;
            if (!frame.Valid) return Unusable(frame.At, frame.Error);
            if (frame.IsPriceOnly)
            {
                var missingBook = Unusable(frame.At, "capture_book_sample_gap");
                return new(true, missingBook.ResetReason != null, missingBook.ResetReason);
            }
            string reset = !_resetIssued && LastGood != default && frame.At - LastGood > _maximumGap
                ? "capture_observation_gap" : null;
            LastGood = frame.At;
            _resetIssued = false;
            return new(true, false, reset);
        }
    }

    internal static class BookCaptureBatch
    {
        public static bool IsBacklog(CapturedBook[] frames, DateTime now, int bookMs, int workerMs)
            => frames.Length > 0 && (now - frames[0].At).TotalMilliseconds
                > Math.Max(Math.Max(250, bookMs), Math.Max(100, workerMs)) + 250;
    }

    internal sealed class BookCatchupState
    {
        public bool Active { get; private set; }
        public DateTime ResumeAfter { get; private set; }
        public string Reason { get; private set; }
        public bool Begin(DateTime now, string reason, bool interrupted)
        {
            bool started = !Active;
            // Additional ordered backlog does not move the recovery boundary;
            // otherwise a slower configured worker could never finish catching up.
            if (started || interrupted) ResumeAfter = now;
            Active = true;
            Reason = reason;
            return started;
        }
        public bool CanResume(CapturedBook frame, bool current)
            => Active && current && frame.Valid && !frame.IsPriceOnly && frame.At > ResumeAfter;
        public void Complete() { Active = false; Reason = null; }
    }

    internal static class SourceQuoteClock
    {
        // Unspecified provider timestamps are UTC, matching the existing recorder.
        // No receipt-time fallback: it would turn delayed deliveries into fresh data.
        public static DateTime Utc(DateTime at) => at == default ? default
            : at.Kind == DateTimeKind.Local ? at.ToUniversalTime()
            : DateTime.SpecifyKind(at, DateTimeKind.Utc);
        public static bool TryAdvance(DateTime source, DateTime receipt, ref DateTime highWater)
        {
            if (source == default || source < highWater || source > receipt.AddMilliseconds(250)) return false;
            highWater = source;
            return true;
        }
        public static double? AgeMs(DateTime source, DateTime now)
            => source == default ? null : (now - source).TotalMilliseconds;
        public static bool Fresh(DateTime source, DateTime now, double limitMs)
            => AgeMs(source, now) is double age && age >= -250 && age <= limitMs;
    }
}
