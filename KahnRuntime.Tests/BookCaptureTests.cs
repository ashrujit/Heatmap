using KahnRuntime;
using KahnRuntime.LiveEvidence;
using System.Text.Json;

internal static class BookCaptureTests
{
    private static DateTime At(double seconds) => new DateTime(2026, 9, 15, 14, 0, 0, DateTimeKind.Utc).AddSeconds(seconds);
    private static void Check(bool value, string why) { if (!value) throw new Exception(why); }
    private static CapturedBook Frame(double at, string error = null) => new(At(at), error == null ? new()
    {
        TimeUtc = At(at), Bids = [new() { Price = 100, Size = 100 + at * at % 47 }],
        Asks = [new() { Price = 101, Size = 100 + at * 17 % 41 }]
    } : null, 100, 101, error);
    public static void RunAll()
    {
        Action[] tests = [ChunkedDrainPreservesRemainder, DelayedWorkerRetainsTimeline, OverflowIsExplicit, ConcurrentBufferIsBounded,
            ShortMismatchPreservesBaseline, LongMismatchResetsOnce, MissingSamplerResets,
            OrderedBacklogDoesNotReset, TimeRegressionRejects, SourceTimesCannotBecomeReceiptTimes,
            SourceHighWaterRecovers, BufferedEngineMatchesContinuousEngine, CatchupRequiresPostBoundaryObservation, InterruptedCatchupMovesBoundary, PriceSamplesDoNotReplaceBooks, HealthyPriceCadenceIsNotBacklog];
        foreach (var test in tests)
        {
            try { test(); }
            catch (Exception ex) { throw new Exception("FAIL " + test.Method.Name, ex); }
        }
        Console.WriteLine($"PASS book capture and continuity ({tests.Length} checks)");
    }
    private static void ChunkedDrainPreservesRemainder()
    {
        var buffer = new BookObservationBuffer(300);
        for (int i = 1; i <= 300; i++) buffer.Add(Frame(i));
        var first = buffer.Drain();
        Check(buffer.HasBefore(At(200)), "disconnect reset would discard remaining pre-boundary history");
        var second = buffer.Drain();
        Check(!buffer.HasBefore(At(200)), "connection boundary never completed");
        var third = buffer.Drain();
        var reconnect = new BookObservationBuffer(300);
        for (int t = 200; t <= 300; t++) reconnect.Add(Frame(t));
        Check(reconnect.Discard() == 101 && reconnect.Count == 0,
            "post-boundary history leaked into reconnect warmup");
        Check(first.Frames.Length == 128 && second.Frames.Length == 128 && third.Frames.Length == 44,
            "drain did not bound worker work");
        Check(first.Frames.Concat(second.Frames).Concat(third.Frames).Select(f => f.At)
            .SequenceEqual(Enumerable.Range(1, 300).Select(t => At(t))) && buffer.Count == 0,
            "chunked drain lost or reordered captured history");
    }
    private static void DelayedWorkerRetainsTimeline()
    {
        var b = new BookObservationBuffer(64);
        for (int t = 1; t <= 40; t++) b.Add(Frame(t));
        var batch = b.Drain();
        Check(!batch.Overflow && batch.Frames.Length == 40 && b.Count == 0, "worker stall lost samples");
        Check(batch.Frames.Select(f => f.At).SequenceEqual(Enumerable.Range(1, 40).Select(t => At(t))), "capture times were rewritten");
    }
    private static void OverflowIsExplicit()
    {
        var b = new BookObservationBuffer(2);
        b.Add(Frame(1)); b.Add(Frame(2)); b.Add(Frame(3));
        var batch = b.Drain();
        Check(batch.Overflow && b.Dropped == 1 && batch.Frames[0].At == At(2), "overflow concealed loss");
        Check(!b.Drain().Overflow, "overflow reported twice");
        var gate = new BookRecoveryGate(TimeSpan.FromSeconds(5));
        gate.Inspect(Frame(1)); gate.LostBuffer();
        Check(gate.LastGood == default && gate.Inspect(Frame(100)).ResetReason == null, "explicit overflow reset was duplicated");
    }
    private static void ConcurrentBufferIsBounded()
    {
        var b = new BookObservationBuffer(16);
        Parallel.For(0, 2000, i => b.Add(Frame(i + 1)));
        var batch = b.Drain();
        Check(batch.Frames.Length == 16 && b.Dropped == 1984 && batch.Overflow, "concurrent writes exceeded bound or hid loss");
    }
    private static void ShortMismatchPreservesBaseline()
    {
        var gate = new BookRecoveryGate(TimeSpan.FromSeconds(5));
        gate.Inspect(Frame(1));
        var bad = gate.Inspect(Frame(2, "l1_dom_mismatch"));
        var good = gate.Inspect(Frame(3));
        Check(!bad.Accept && bad.Interrupt && bad.ResetReason == null && good.Accept && good.ResetReason == null,
            "bounded mismatch caused full warmup or became accepted evidence");
    }
    private static void LongMismatchResetsOnce()
    {
        var gate = new BookRecoveryGate(TimeSpan.FromSeconds(5));
        gate.Inspect(Frame(1));
        Check(gate.Inspect(Frame(6, "stale")).ResetReason == null, "changed existing five-second boundary");
        Check(gate.Inspect(Frame(7, "stale")).ResetReason != null, "long gap kept baseline");
        Check(gate.Inspect(Frame(20, "stale")).ResetReason == null, "repeated unusable sample kept resetting");
        Check(gate.Inspect(Frame(21)).Accept, "valid recovery sample refused");
        Check(gate.Inspect(Frame(27, "stale")).ResetReason != null, "second real gap was ignored");
    }
    private static void MissingSamplerResets()
    {
        var gate = new BookRecoveryGate(TimeSpan.FromSeconds(5));
        gate.Inspect(Frame(1));
        Check(gate.Missing(At(7)).ResetReason != null && gate.Missing(At(8)).ResetReason == null, "missing capture did not reset once");
        Check(gate.Inspect(Frame(9)).Accept, "wall-time missing check contaminated sample ordering");
    }
    private static void OrderedBacklogDoesNotReset()
    {
        var gate = new BookRecoveryGate(TimeSpan.FromSeconds(5));
        for (int i = 1; i <= 60; i++)
        {
            var step = gate.Inspect(Frame(i));
            Check(step.Accept && step.ResetReason == null, "wall-time backlog was interpreted as missing observations");
        }
        Check(gate.Inspect(Frame(70)).ResetReason != null, "real capture gap was not distinguished from worker lag");
    }
    private static void TimeRegressionRejects()
    {
        var gate = new BookRecoveryGate(TimeSpan.FromSeconds(5));
        gate.Inspect(Frame(5));
        Check(!gate.Inspect(Frame(4)).Accept, "out-of-order capture accepted");
        Check(!gate.Inspect(Frame(5)).Accept, "duplicate sample accepted");
        Check(gate.Inspect(Frame(6)).Accept, "clock recovery stayed blocked");
    }
    private static void SourceTimesCannotBecomeReceiptTimes()
    {
        Check(!SourceQuoteClock.Fresh(At(1), At(10), 2000), "old burst appeared fresh");
        Check(!SourceQuoteClock.Fresh(default, At(10), 2000), "missing source time accepted");
        Check(!SourceQuoteClock.Fresh(At(11), At(10), 2000), "future source clock accepted");
        Check(SourceQuoteClock.Fresh(At(9), At(10), 2000), "fresh source refused");
        Check(SourceQuoteClock.Utc(DateTime.SpecifyKind(At(1), DateTimeKind.Unspecified)) == At(1), "unspecified UTC conversion changed time");
    }
    private static void SourceHighWaterRecovers()
    {
        DateTime high = default;
        Check(SourceQuoteClock.TryAdvance(At(5), At(5), ref high), "first timestamp rejected");
        Check(!SourceQuoteClock.TryAdvance(At(4), At(6), ref high) && high == At(5), "regression rewound high water");
        Check(!SourceQuoteClock.TryAdvance(At(1000), At(6), ref high) && high == At(5), "future timestamp poisoned recovery");
        Check(SourceQuoteClock.TryAdvance(At(6), At(6), ref high), "valid source could not recover");
        Check(SourceQuoteClock.TryAdvance(At(6), At(6), ref high), "same timestamp messages were mistaken for loss");
    }
    private static void PriceSamplesDoNotReplaceBooks()
    {
        var gate = new BookRecoveryGate(TimeSpan.FromSeconds(5));
        gate.Inspect(Frame(1));
        CapturedBook Price(double t) => new(At(t), null, 100, 101, null, IsPriceOnly: true);
        Check(gate.Inspect(Price(1.25)).Accept && gate.LastGood == At(1), "price sample replaced book continuity");
        Check(gate.Inspect(Price(7)).ResetReason != null, "continuous L1 concealed missing books");
        var recovery = new BookCatchupState(); recovery.Begin(At(1), "gap", true);
        Check(!recovery.CanResume(Price(2), true), "L1 alone restored book discovery");
    }
    private static void HealthyPriceCadenceIsNotBacklog()
    {
        var prices = new[] { new CapturedBook(At(1), null, 100, 101, null, IsPriceOnly: true), Frame(1.25) };
        Check(!BookCaptureBatch.IsBacklog(prices, At(1.5), 1000, 250), "ordinary price polling caused catch-up");
        Check(BookCaptureBatch.IsBacklog(prices, At(5), 1000, 250), "delayed worker was not caught");
        Check(!BookCaptureBatch.IsBacklog(prices, At(5), 1000, 5000), "configured slow polling was treated as a stall");
    }
    private static void CatchupRequiresPostBoundaryObservation()
    {
        var recovery = new BookCatchupState();
        Check(recovery.Begin(At(30), "worker_backlog", false), "catch-up did not begin");
        Check(!recovery.CanResume(Frame(29), true), "old batch restored entry authority");
        Check(!recovery.CanResume(Frame(31), false), "uncaught backlog restored entry authority");
        Check(!recovery.Begin(At(35), "worker_backlog", false), "ordered backlog restarted recovery");
        Check(recovery.CanResume(Frame(34), true), "slow worker could never catch up");
        recovery.Complete();
        Check(!recovery.Active && recovery.Reason == null, "catch-up remained latched");
    }
    private static void InterruptedCatchupMovesBoundary()
    {
        var recovery = new BookCatchupState();
        recovery.Begin(At(10), "backlog", false);
        recovery.Begin(At(12), "mismatch", true);
        Check(!recovery.CanResume(Frame(11), true), "pre-interruption sample resumed discovery");
        Check(!recovery.CanResume(Frame(13, "stale"), true), "invalid sample resumed discovery");
        Check(recovery.CanResume(Frame(13), true), "new coherent sample did not resume");
    }
    private static void BufferedEngineMatchesContinuousEngine()
    {
        var direct = new ExecutionEvidenceEngine(1, new());
        var buffered = new ExecutionEvidenceEngine(1, new());
        var buffer = new BookObservationBuffer(128);
        var expected = new List<string>(); var actual = new List<string>();
        for (int t = 1; t <= 90; t++)
        {
            var frame = Frame(t);
            expected.Add(JsonSerializer.Serialize(direct.Process(frame.Depth)));
            buffer.Add(frame);
        }
        foreach (var frame in buffer.Drain().Frames)
            actual.Add(JsonSerializer.Serialize(buffered.Process(frame.Depth)));
        Check(expected.SequenceEqual(actual), "buffering changed LL evidence or confirmation timing");
    }
}
