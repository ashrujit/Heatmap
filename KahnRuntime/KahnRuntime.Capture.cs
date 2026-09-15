using System;
using System.Threading;
using System.Diagnostics;
using TradingPlatform.BusinessLayer;

namespace KahnRuntime
{
    public sealed partial class KahnRuntime
    {
        private BookObservationBuffer _bookBuffer;
        private BookRecoveryGate _bookRecovery;
        private Connection _captureConnection;
        private int _captureConnectionChanged;
        private DateTime _captureConnectionBoundary;
        private DateTime _pendingCaptureConnectionBoundary;

        private void CaptureConnectionChanged(object sender, ConnectionStateChangedEventArgs args)
        {
            lock (_marketGate)
            {
                if (_captureConnectionChanged == 0) _captureConnectionBoundary = DateTime.UtcNow;
                Volatile.Write(ref _captureConnectionChanged, 1);
                _quoteSourceUtc = _l2SourceUtc = default;
                _quoteSourceOrdered = _l2SourceOrdered = false;
                _quoteVersion++;
            }
        }
        private Thread _captureThread;
        private ManualResetEvent _captureStop;
        private DateTime _quoteSourceUtc, _l2SourceUtc;
        private bool _quoteSourceOrdered, _l2SourceOrdered;
        private long _quoteVersion;
        private BookCatchupState _captureRecovery = new();
        private bool _captureCatchingUp => _captureRecovery.Active;
        private string _captureReason => _captureRecovery.Reason;
        private double? _captureL2AgeMs, _captureQuoteAgeMs;
        private double _captureWorkerLagMs;

        private void StartBookCapture()
        {
            // Separate from the order worker and ThreadPool timers: a broker/file
            // stall must not erase otherwise available one-second observations.
            int interval = Math.Min(Math.Max(250, BookSampleMs), Math.Max(100, WorkerPollMs));
            int capacity = Math.Clamp(256 * (int)Math.Ceiling(Math.Max(250, BookSampleMs) / (double)interval), 256, 4096);
            var buffer = _bookBuffer = new BookObservationBuffer(capacity);
            _bookRecovery = new BookRecoveryGate(TimeSpan.FromSeconds(Math.Max(1, BookFreshnessSec)));
            var stop = _captureStop = new ManualResetEvent(false);
            _captureThread = new Thread(() =>
            {
                DateTime lastBook = default;
                try
                {
                    while (!stop.WaitOne(interval))
                    {
                        CapturedBook frame;
                        try
                        {
                            bool includeBook = (DateTime.UtcNow - lastBook).TotalMilliseconds >= Math.Max(250, BookSampleMs);
                            frame = CaptureBook(includeBook);
                            if (includeBook) lastBook = frame.At;
                        }
                        catch (Exception ex)
                        {
                            frame = new(DateTime.UtcNow, null, double.NaN, double.NaN,
                                "capture_error:" + ex.GetType().Name);
                        }
                        if (!stop.WaitOne(0)) buffer.Add(frame);
                    }
                }
                finally { stop.Dispose(); }
            }) { IsBackground = true, Name = "Kahn book capture" };
            _captureThread.Start();
        }

        private void StopBookCapture()
        {
            var thread = _captureThread;
            if (thread == null) return;
            try { _captureStop.Set(); } catch (ObjectDisposedException) { }
            thread.Join(TimeSpan.FromSeconds(2));
            _captureThread = null;
            _captureStop = null;
        }

        private CapturedBook CaptureBook(bool includeBook)
        {
            CapturedBook result = null;
            // BBO and DOM are separate QT reads. Retry a torn read immediately,
            // without sleeping or doing expensive work on a market callback.
            for (int attempt = 0; attempt < 3; attempt++)
            {
                long readStarted = Stopwatch.GetTimestamp();
                DateTime at = DateTime.UtcNow;
                if (_captureConnection?.State != ConnectionState.Connected)
                    return new(at, null, double.NaN, double.NaN, "capture_connection_unavailable");
                double bid, ask;
                long version;
                string error = null;
                double? l2Age, quoteAge;
                lock (_marketGate)
                {
                    bid = _latestBid; ask = _latestAsk; version = _quoteVersion;
                    l2Age = SourceQuoteClock.AgeMs(_l2SourceUtc, at);
                    quoteAge = SourceQuoteClock.AgeMs(_quoteSourceUtc, at);
                    if (!_l2SourceOrdered || !SourceQuoteClock.Fresh(_l2SourceUtc, at, Math.Max(1, BookFreshnessSec) * 1000)
                        || !SourceQuoteClock.Fresh(_lastL2Utc, at, Math.Max(1, BookFreshnessSec) * 1000))
                        error = "l2_source_stale_or_invalid";
                    else if (!_quoteSourceOrdered || !SourceQuoteClock.Fresh(_quoteSourceUtc, at, Math.Max(250, QuoteFreshnessMs))
                        || !SourceQuoteClock.Fresh(_lastQuoteUtc, at, Math.Max(250, QuoteFreshnessMs)))
                        error = "quote_source_stale_or_invalid";
                }
                if (error != null) return new(at, null, bid, ask, error, l2Age, quoteAge);
                var diagnostic = new BookSampleDiagnostic { SymbolBid = bid, SymbolAsk = ask };
                bool valid = double.IsFinite(bid) && double.IsFinite(ask) && bid > 0 && ask >= bid;
                if (!includeBook)
                    return new(at, null, bid, ask, valid ? null : "quote_invalid", l2Age, quoteAge, IsPriceOnly: true);
                LiveEvidence.BookDepthSnapshot depth = null;
                if (valid) valid = TryBuildDepthSnapshot(at, out depth, diagnostic);
                if (Stopwatch.GetElapsedTime(readStarted).TotalMilliseconds > Math.Max(250, BookSampleMs))
                    return new(DateTime.UtcNow, null, bid, ask, "capture_read_delayed", l2Age, quoteAge);
                lock (_marketGate)
                    if (version != _quoteVersion) { valid = false; diagnostic.Reason = "book_read_changed"; }
                result = new(at, valid ? depth : null, bid, ask,
                    valid ? null : diagnostic.Reason ?? "quote_invalid", l2Age, quoteAge,
                    new(diagnostic.BidLevels, diagnostic.AskLevels, diagnostic.SymbolBid, diagnostic.SymbolAsk,
                        diagnostic.DomBid, diagnostic.DomAsk, diagnostic.Error));
                if (valid) return result;
            }
            return result;
        }

        private void BeginCaptureCatchup(string reason, bool interrupt)
        {
            if (_captureRecovery.Begin(DateTime.UtcNow, reason, interrupt))
            {
                _decisions.Write("evidence_catchup_started", ("reason", reason), ("identity_epoch", _llEpoch));
                // Suspend at the observed boundary, not wall time: queued root
                // observations still need to be consumed in their original order.
                if (_session != null) _session.SuspendObservation(_session.Observer.LastObservedAt, reason);
            }
            if (interrupt) _liveEvidence.InterruptObservation();
            _evidenceState = "CatchingUp";
        }

        private bool CaptureAllowsNewRisk(DateTime now)
        {
            if (!_running || Volatile.Read(ref _captureConnectionChanged) != 0
                || _captureConnection?.State != ConnectionState.Connected
                || _captureCatchingUp || _evidenceState != "Ready" || !_evidenceWarmupComplete
                || _bookBuffer == null || _bookBuffer.Count > 0
                || !SourceQuoteClock.Fresh(_lastEvidenceSampleUtc, now, Math.Max(1, BookFreshnessSec) * 1000)) return false;
            lock (_marketGate)
                return _quoteSourceOrdered && SourceQuoteClock.Fresh(_quoteSourceUtc, now, Math.Max(250, QuoteFreshnessMs))
                    && SourceQuoteClock.Fresh(_lastQuoteUtc, now, Math.Max(250, QuoteFreshnessMs))
                    && _l2SourceOrdered && SourceQuoteClock.Fresh(_l2SourceUtc, now, Math.Max(1, BookFreshnessSec) * 1000)
                    && SourceQuoteClock.Fresh(_lastL2Utc, now, Math.Max(1, BookFreshnessSec) * 1000);
        }
    }
}
